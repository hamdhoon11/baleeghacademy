"""v0.8.47: who is online, and account control. Full admins only (role admin with no permission limit = the superadmin).

  GET  /api/admin/presence                      everyone with their online status, device, last seen and account state; counts
  POST /api/admin/accounts/<id>/signout         sign the person out on every device now (they can sign in again)
  POST /api/admin/accounts/<id>/pause           {until: "YYYY-MM-DDTHH:MM" Maldives time, or hours: n; reason}  blocked until then, lifts by itself
  POST /api/admin/accounts/<id>/suspend         {reason}  blocked until a full admin restores the account
  POST /api/admin/accounts/<id>/restore         lifts a pause or a suspension

How it works
- Every signed-in request (auth() in app.py) calls touch(): last_seen_at, IP and browser are written at most every TOUCH_SECONDS.
  The page asks for the notification count every 60 seconds while it is open and visible, which keeps an open portal "online".
- Online = seen in the last ONLINE_SECONDS and not signed out since. Away = seen in the last AWAY_SECONDS. Otherwise offline.
- Tokens carry "tv" (users.token_version). Sign out, pause and suspend raise it, so every open session gets 401 on its next request.
- blocked() is checked at sign-in (after the right password only) and on every request.
- Nobody can act on their own account. Every action is in the activity log with the reason.
"""
import datetime as dt
import re

from flask import g, jsonify, request

MVT = dt.timezone(dt.timedelta(hours=5))
TOUCH_SECONDS = 30
ONLINE_SECONDS = 150
AWAY_SECONDS = 15 * 60
MAX_PAUSE_DAYS = 366
KICKED = ("signed_out_by_admin", "You were signed out by the academy. Please sign in again.")
FMT = "%Y-%m-%d %H:%M:%S"


def parse(stamp):
    return dt.datetime.strptime(stamp, FMT).replace(tzinfo=dt.timezone.utc) if stamp else None


def shift(stamp, seconds):
    return (parse(stamp) + dt.timedelta(seconds=seconds)).strftime(FMT)


def local_text(stamp):
    """UTC stamp -> '20 Nov 2026, 18:00' in Maldives time."""
    d = parse(stamp).astimezone(MVT)
    return f"{d.day} {d.strftime('%b %Y, %H:%M')}"


def blocked(u, now):
    """(code, message) when the account may not be used right now, else None."""
    if u.get("suspended_at"):
        return ("account_suspended", "Your account has been suspended. Please contact the academy.")
    if u.get("paused_until") and u["paused_until"] > now:
        return ("account_paused", f"Your account is paused until {local_text(u['paused_until'])} (Maldives time). Please try again then.")
    return None


def agent_of(req):
    return (req.headers.get("User-Agent") or "")[:200] or None


def touch(conn, u, now, req):
    """Record activity, at most every TOUCH_SECONDS (and always right after a sign-out, so a second device shows online again)."""
    last, out = u.get("last_seen_at"), u.get("signed_out_at")
    if last and last > shift(now, -TOUCH_SECONDS) and not (out and out >= last):
        return
    conn.execute("UPDATE users SET last_seen_at=?, last_ip=?, last_agent=? WHERE id=?", (now, req.remote_addr, agent_of(req), u["id"]))
    conn.commit()


def signed_in(conn, uid, now, req):
    conn.execute("UPDATE users SET last_login_at=?, last_seen_at=?, signed_out_at=NULL, last_ip=?, last_agent=? WHERE id=?",
                 (now, now, req.remote_addr, agent_of(req), uid))


def device(agent):
    """A short, human description of a user-agent: 'Phone · Chrome'."""
    a = agent or ""
    if not a: return ""
    kind = "Tablet" if re.search(r"iPad|Tablet", a) else "Phone" if re.search(r"Mobi|iPhone|Android", a) else "Computer"
    for name, rx in (("Edge", r"Edg/"), ("Opera", r"OPR/"), ("Samsung Internet", r"SamsungBrowser"), ("Chrome", r"Chrome/|CriOS"),
                     ("Firefox", r"Firefox/|FxiOS"), ("Safari", r"Safari/")):
        if re.search(rx, a): return f"{kind} · {name}"
    return kind


def status(r, now):
    last, out = r.get("last_seen_at"), r.get("signed_out_at")
    if not last or (out and out >= last): return "offline"
    if last >= shift(now, -ONLINE_SECONDS): return "online"
    if last >= shift(now, -AWAY_SECONDS): return "away"
    return "offline"


def account_state(r, now):
    if not r["is_active"]: return "disabled"
    if r.get("suspended_at"): return "suspended"
    if r.get("paused_until") and r["paused_until"] > now: return "paused"
    return "active"


def register(app, c):
    def guard(uid=None):
        """Only a full admin, never on their own account. Returns (error response or None, target row)."""
        if not c.is_full_admin(g.user): return c.err("Only a full admin can do this", 403), None
        if uid is None: return None, None
        t = c.one("SELECT id, full_name, login_id, role, is_active, permissions, suspended_at, paused_until FROM users WHERE id=?", (uid,))
        if not t: return c.err("User not found", 404), None
        if t["id"] == g.user["id"]: return c.err("You cannot do this to your own account", 409), None
        return None, t

    def reason_of(d, required):
        r = re.sub(r"\s+", " ", str(d.get("reason") or "")).strip()[:300]
        return (None, "Write a reason") if required and not r else (r or None, None)

    def kick(uid, now):
        c.db().execute("UPDATE users SET token_version=COALESCE(token_version,0)+1, signed_out_at=? WHERE id=?", (now, uid))

    @app.get("/api/admin/presence")
    @c.auth("admin")
    def presence_list():
        bad, _ = guard()
        if bad: return bad
        now = c.utc_stamp()
        out, counts = [], {"online": 0, "away": 0, "offline": 0, "suspended": 0, "paused": 0, "disabled": 0}
        by_role = {k: {"online": 0, "total": 0} for k in ("admin", "teacher", "student")}
        for r in c.rows("SELECT id, full_name, login_id, role, is_active, permissions, last_seen_at, last_login_at, signed_out_at, last_ip, last_agent,"
                        " suspended_at, suspend_reason, paused_until, pause_reason FROM users ORDER BY full_name"):
            st, acc = status(r, now), account_state(r, now)
            counts[st] += 1
            if acc != "active": counts[acc] += 1
            by_role[r["role"]]["total"] += 1
            if st == "online": by_role[r["role"]]["online"] += 1
            out.append({"id": r["id"], "full_name": r["full_name"], "login_id": r["login_id"], "role": r["role"],
                        "full_admin": r["role"] == "admin" and r["permissions"] is None, "is_self": r["id"] == g.user["id"],
                        "status": st, "last_seen_at": r["last_seen_at"], "last_login_at": r["last_login_at"], "ip": r["last_ip"],
                        "device": device(r["last_agent"]), "account": acc,
                        "paused_until": r["paused_until"] if acc == "paused" else None, "pause_reason": r["pause_reason"] if acc == "paused" else None,
                        "suspended_at": r["suspended_at"], "suspend_reason": r["suspend_reason"]})
        order = {"online": 0, "away": 1, "offline": 2}
        out.sort(key=lambda x: (order[x["status"]], -(int(re.sub(r"\D", "", x["last_seen_at"] or "0") or 0)), x["full_name"].lower()))
        return jsonify(now=now, people=out, counts=counts, by_role=by_role, online_seconds=ONLINE_SECONDS, away_seconds=AWAY_SECONDS)

    @app.post("/api/admin/accounts/<int:uid>/signout")
    @c.auth("admin")
    def acc_signout(uid):
        bad, t = guard(uid)
        if bad: return bad
        reason, _ = reason_of(request.get_json(silent=True) or {}, False)
        kick(uid, c.utc_stamp())
        c.audit("account_signout", "user", uid, f"{t['full_name']} ({t['login_id']}) signed out on every device" + (f": {reason}" if reason else ""))
        c.db().commit()
        return jsonify(ok=True)

    @app.post("/api/admin/accounts/<int:uid>/pause")
    @c.auth("admin")
    def acc_pause(uid):
        bad, t = guard(uid)
        if bad: return bad
        if t["suspended_at"]: return c.err("This account is suspended. Restore it first, then pause it.", 409)
        d = request.get_json(silent=True) or {}
        reason, miss = reason_of(d, False)
        now = c.utc_stamp()
        try:
            if d.get("hours") not in (None, ""):
                h = float(d["hours"])
                if not 0 < h <= MAX_PAUSE_DAYS * 24: raise ValueError
                until = shift(now, round(h * 3600))
            else:
                loc = dt.datetime.strptime(str(d.get("until") or "").strip()[:16].replace(" ", "T"), "%Y-%m-%dT%H:%M").replace(tzinfo=MVT)
                until = loc.astimezone(dt.timezone.utc).strftime(FMT)
        except (ValueError, TypeError):
            return c.err("Choose how long to pause the account")
        if until <= now: return c.err("The pause must end in the future")
        if until > shift(now, MAX_PAUSE_DAYS * 86400): return c.err("A pause can last at most one year. Suspend the account instead.")
        c.db().execute("UPDATE users SET paused_until=?, pause_reason=?, account_changed_by=? WHERE id=?", (until, reason, g.user["id"], uid))
        kick(uid, now)
        c.audit("account_pause", "user", uid, f"{t['full_name']} ({t['login_id']}) paused until {local_text(until)}" + (f": {reason}" if reason else ""),
                new=until)
        c.db().commit()
        return jsonify(ok=True, paused_until=until)

    @app.post("/api/admin/accounts/<int:uid>/suspend")
    @c.auth("admin")
    def acc_suspend(uid):
        bad, t = guard(uid)
        if bad: return bad
        reason, miss = reason_of(request.get_json(silent=True) or {}, True)
        if miss: return c.err(miss)
        now = c.utc_stamp()
        c.db().execute("UPDATE users SET suspended_at=?, suspend_reason=?, paused_until=NULL, pause_reason=NULL, account_changed_by=? WHERE id=?",
                       (now, reason, g.user["id"], uid))
        kick(uid, now)
        c.audit("account_suspend", "user", uid, f"{t['full_name']} ({t['login_id']}) suspended: {reason}")
        c.db().commit()
        return jsonify(ok=True)

    @app.post("/api/admin/accounts/<int:uid>/restore")
    @c.auth("admin")
    def acc_restore(uid):
        bad, t = guard(uid)
        if bad: return bad
        now = c.utc_stamp()
        was = "suspended" if t["suspended_at"] else "paused" if t["paused_until"] and t["paused_until"] > now else None
        if not was: return c.err("This account is not paused or suspended", 409)
        c.db().execute("UPDATE users SET suspended_at=NULL, suspend_reason=NULL, paused_until=NULL, pause_reason=NULL, account_changed_by=? WHERE id=?",
                       (g.user["id"], uid))
        c.audit("account_restore", "user", uid, f"{t['full_name']} ({t['login_id']}) can sign in again (was {was})", old=was)
        c.db().commit()
        return jsonify(ok=True)
