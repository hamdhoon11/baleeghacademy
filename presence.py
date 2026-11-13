"""v0.8.47: who is online, sign-in history and account control. Full admins only (role admin with no permission limit = the superadmin).

  GET  /api/admin/presence                      everyone: online status, device, last seen, account state, warning flags; counts
  GET  /api/admin/presence/summary              counts only (Dashboard card)
  GET  /api/admin/accounts/<id>/history         one person's sign-ins (good and failed), devices and account actions
  POST /api/admin/accounts/<id>/signout         sign the person out on every device now (they can sign in again)
  POST /api/admin/accounts/<id>/pause           {until: "YYYY-MM-DDTHH:MM" Maldives time, or hours: n; reason; message}  lifts by itself
  POST /api/admin/accounts/<id>/suspend         {reason (staff only); message (shown to the person)}  until a full admin restores it
  POST /api/admin/accounts/<id>/restore         lifts a pause or a suspension
  POST /api/admin/accounts/bulk                 {ids, action: signout|pause|suspend|restore, ...the same fields}  per-person result
  POST /api/admin/accounts/signout-all          {role: ""|student|teacher|admin, reason}  everyone except you

How it works
- Every signed-in request (auth() in app.py) calls touch(): last_seen_at, IP and browser are written at most every TOUCH_SECONDS.
  The page asks for the notification count every 60 seconds while it is open and visible, which keeps an open portal "online".
- Online = seen in the last ONLINE_SECONDS and not signed out since. Away = seen in the last AWAY_SECONDS. Otherwise offline.
- Tokens carry "tv" (users.token_version). Sign out, pause and suspend raise it, so every open session gets 401 on its next request.
- blocked() is checked at sign-in (after the right password only) and on every request.
- Every sign-in attempt goes into login_events (kept RETAIN_DAYS). Flags: failed sign-ins in the last 24 hours; the last sign-in
  came from a kind of device ("Phone · Chrome") not used in the 90 days before.
- sweep(): a pause that has ended is cleared, logged, and every full admin gets a notification. It runs when a full admin uses
  the portal (at most every TOUCH_SECONDS) and when this page is opened, so the notice can come a little after the exact time.
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
RETAIN_DAYS = 180
NEW_DEVICE_DAYS = 90
FAILED_WARN = 3
KICKED = ("signed_out_by_admin", "You were signed out by the academy. Please sign in again.")
FMT = "%Y-%m-%d %H:%M:%S"
ACTIONS = ("signout", "pause", "suspend", "restore")


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
    msg = f" Message from the academy: {u['account_message']}" if u.get("account_message") else ""
    if u.get("suspended_at"):
        return ("account_suspended", "Your account has been suspended. Please contact the academy." + msg)
    if u.get("paused_until") and u["paused_until"] > now:
        return ("account_paused", f"Your account is paused until {local_text(u['paused_until'])} (Maldives time). Please try again then." + msg)
    return None


def agent_of(req):
    return (req.headers.get("User-Agent") or "")[:200] or None


def log_login(conn, uid, typed, ok, reason, now, req):
    conn.execute("INSERT INTO login_events(user_id, login_text, ok, reason, ip, agent, at) VALUES(?,?,?,?,?,?,?)",
                 (uid, (typed or "")[:80] or None, 1 if ok else 0, reason, req.remote_addr, agent_of(req), now))


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
    def full_admin_ids():
        return [r["id"] for r in c.rows("SELECT id FROM users WHERE role='admin' AND is_active=1 AND permissions IS NULL")]

    def sweep(now):
        """Pauses that have ended: clear them, log it, tell the full admins. Also trims old sign-in records. Does NOT commit."""
        for r in c.rows("SELECT id, full_name, login_id, paused_until FROM users WHERE paused_until IS NOT NULL AND paused_until<=?", (now,)):
            c.db().execute("UPDATE users SET paused_until=NULL, pause_reason=NULL, account_message=NULL WHERE id=? AND paused_until=?", (r["id"], r["paused_until"]))
            c.audit("account_pause_ended", "user", r["id"], f"{r['full_name']} ({r['login_id']}): pause ended {local_text(r['paused_until'])}", role="system")
            c.notify(full_admin_ids(), "account", "Pause ended", f"{r['full_name']} ({r['login_id']}) can sign in again.", f"online:{r['id']}",
                     f"pause-end:{r['id']}:{r['paused_until']}")
        c.db().execute("DELETE FROM login_events WHERE at<?", (shift(now, -RETAIN_DAYS * 86400),))

    def touch(conn, u, now, req, full):
        """Record activity, at most every TOUCH_SECONDS (and always right after a sign-out, so a second device shows online again)."""
        last, out = u.get("last_seen_at"), u.get("signed_out_at")
        if last and last > shift(now, -TOUCH_SECONDS) and not (out and out >= last):
            return
        conn.execute("UPDATE users SET last_seen_at=?, last_ip=?, last_agent=? WHERE id=?", (now, req.remote_addr, agent_of(req), u["id"]))
        if full: sweep(now)
        conn.commit()

    app.extensions["presence"] = {"touch": touch, "sweep": sweep}

    def guard():
        return None if c.is_full_admin(g.user) else c.err("Only a full admin can do this", 403)

    def target(uid):
        """(error message, status) or (None, row)."""
        t = c.one("SELECT id, full_name, login_id, role, is_active, permissions, suspended_at, paused_until FROM users WHERE id=?", (uid,))
        if not t: return ("User not found", 404), None
        if t["id"] == g.user["id"]: return ("You cannot do this to your own account", 409), None
        return None, t

    def clean(v, n):
        return re.sub(r"\s+", " ", str(v or "")).strip()[:n] or None

    def kick(uid, now):
        c.db().execute("UPDATE users SET token_version=COALESCE(token_version,0)+1, signed_out_at=? WHERE id=?", (now, uid))

    def pause_end(d, now):
        """(until, None) or (None, error) from {hours} or {until}."""
        try:
            if d.get("hours") not in (None, ""):
                h = float(d["hours"])
                if not 0 < h <= MAX_PAUSE_DAYS * 24: raise ValueError
                until = shift(now, round(h * 3600))
            else:
                loc = dt.datetime.strptime(str(d.get("until") or "").strip()[:16].replace(" ", "T"), "%Y-%m-%dT%H:%M").replace(tzinfo=MVT)
                until = loc.astimezone(dt.timezone.utc).strftime(FMT)
        except (ValueError, TypeError):
            return None, "Choose how long to pause the account"
        if until <= now: return None, "The pause must end in the future"
        if until > shift(now, MAX_PAUSE_DAYS * 86400): return None, "A pause can last at most one year. Suspend the account instead."
        return until, None

    def apply(action, t, d, now, until=None):
        """Do one action on one person (already checked). Returns (result dict, None) or (None, (error, status)). Does NOT commit."""
        who = f"{t['full_name']} ({t['login_id']})"
        reason, message = clean(d.get("reason"), 300), clean(d.get("message"), 200)
        if action == "signout":
            kick(t["id"], now)
            c.audit("account_signout", "user", t["id"], f"{who} signed out on every device" + (f": {reason}" if reason else ""))
            return {}, None
        if action == "pause":
            if t["suspended_at"]: return None, ("This account is suspended. Restore it first, then pause it.", 409)
            if until is None:
                until, bad = pause_end(d, now)
                if bad: return None, (bad, 400)
            c.db().execute("UPDATE users SET paused_until=?, pause_reason=?, account_message=?, account_changed_by=? WHERE id=?",
                           (until, reason, message, g.user["id"], t["id"]))
            kick(t["id"], now)
            c.audit("account_pause", "user", t["id"], f"{who} paused until {local_text(until)}" + (f": {reason}" if reason else ""), new=until)
            return {"paused_until": until}, None
        if action == "suspend":
            if not reason: return None, ("Write a reason", 400)
            c.db().execute("UPDATE users SET suspended_at=?, suspend_reason=?, paused_until=NULL, pause_reason=NULL, account_message=?, account_changed_by=? WHERE id=?",
                           (now, reason, message, g.user["id"], t["id"]))
            kick(t["id"], now)
            c.audit("account_suspend", "user", t["id"], f"{who} suspended: {reason}")
            return {}, None
        if action == "restore":
            was = "suspended" if t["suspended_at"] else "paused" if t["paused_until"] and t["paused_until"] > now else None
            if not was: return None, ("This account is not paused or suspended", 409)
            c.db().execute("UPDATE users SET suspended_at=NULL, suspend_reason=NULL, paused_until=NULL, pause_reason=NULL, account_message=NULL, account_changed_by=? WHERE id=?",
                           (g.user["id"], t["id"]))
            c.audit("account_restore", "user", t["id"], f"{who} can sign in again (was {was})", old=was)
            return {}, None
        return None, ("Unknown action", 400)

    def flags(now):
        """{user_id: {failed_24h, new_device}}"""
        out = {}
        for r in c.rows("SELECT user_id, COUNT(*) n FROM login_events WHERE ok=0 AND user_id IS NOT NULL AND at>=? GROUP BY user_id", (shift(now, -86400),)):
            out.setdefault(r["user_id"], {})["failed_24h"] = r["n"]
        seen, last = {}, {}
        for r in c.rows("SELECT user_id, agent, at FROM login_events WHERE ok=1 AND user_id IS NOT NULL AND at>=? ORDER BY at, id",
                        (shift(now, -(NEW_DEVICE_DAYS + 7) * 86400),)):
            uid, dv = r["user_id"], device(r["agent"]) or "?"
            if uid in last: seen.setdefault(uid, set()).add(last[uid][0])
            last[uid] = (dv, r["at"])
        for uid, (dv, at) in last.items():
            if uid in seen and dv not in seen[uid] and at >= shift(now, -7 * 86400):
                out.setdefault(uid, {})["new_device"] = dv
        return out

    def people(now):
        fl = flags(now)
        out, counts = [], {"online": 0, "away": 0, "offline": 0, "suspended": 0, "paused": 0, "disabled": 0, "warnings": 0}
        by_role = {k: {"online": 0, "total": 0} for k in ("admin", "teacher", "student")}
        for r in c.rows("SELECT id, full_name, login_id, role, is_active, permissions, last_seen_at, last_login_at, signed_out_at, last_ip, last_agent,"
                        " suspended_at, suspend_reason, paused_until, pause_reason, account_message FROM users ORDER BY full_name"):
            st, acc, f = status(r, now), account_state(r, now), fl.get(r["id"], {})
            counts[st] += 1
            if acc != "active": counts[acc] += 1
            failed = f.get("failed_24h", 0)
            if failed >= FAILED_WARN or f.get("new_device"): counts["warnings"] += 1
            by_role[r["role"]]["total"] += 1
            if st == "online": by_role[r["role"]]["online"] += 1
            out.append({"id": r["id"], "full_name": r["full_name"], "login_id": r["login_id"], "role": r["role"],
                        "full_admin": r["role"] == "admin" and r["permissions"] is None, "is_self": r["id"] == g.user["id"],
                        "status": st, "last_seen_at": r["last_seen_at"], "last_login_at": r["last_login_at"], "ip": r["last_ip"],
                        "device": device(r["last_agent"]), "account": acc, "failed_24h": failed, "new_device": f.get("new_device"),
                        "paused_until": r["paused_until"] if acc == "paused" else None, "pause_reason": r["pause_reason"] if acc == "paused" else None,
                        "suspended_at": r["suspended_at"], "suspend_reason": r["suspend_reason"],
                        "message": r["account_message"] if acc in ("paused", "suspended") else None})
        order = {"online": 0, "away": 1, "offline": 2}
        out.sort(key=lambda x: (order[x["status"]], -(int(re.sub(r"\D", "", x["last_seen_at"] or "0") or 0)), x["full_name"].lower()))
        return out, counts, by_role

    @app.get("/api/admin/presence")
    @c.auth("admin")
    def presence_list():
        bad = guard()
        if bad: return bad
        now = c.utc_stamp(); sweep(now); c.db().commit()
        out, counts, by_role = people(now)
        return jsonify(now=now, people=out, counts=counts, by_role=by_role, online_seconds=ONLINE_SECONDS, away_seconds=AWAY_SECONDS, failed_warn=FAILED_WARN)

    @app.get("/api/admin/presence/summary")
    @c.auth("admin")
    def presence_summary():
        bad = guard()
        if bad: return bad
        now = c.utc_stamp(); sweep(now); c.db().commit()
        _, counts, by_role = people(now)
        failed = c.one("SELECT COUNT(*) n FROM login_events WHERE ok=0 AND at>=?", (shift(now, -86400),))["n"]
        return jsonify(now=now, counts=counts, by_role=by_role, failed_24h=failed)

    @app.get("/api/admin/accounts/<int:uid>/history")
    @c.auth("admin")
    def acc_history(uid):
        bad = guard()
        if bad: return bad
        t = c.one("SELECT id, full_name, login_id, role FROM users WHERE id=?", (uid,))
        if not t: return c.err("User not found", 404)
        now = c.utc_stamp()
        ev = c.rows("SELECT at, ok, reason, ip, agent FROM login_events WHERE user_id=? ORDER BY at DESC, id DESC LIMIT 60", (uid,))
        devices = {}
        for e in ev:
            e["device"] = device(e.pop("agent"))
            if e["ok"]:
                k = (e["device"] or "?", e["ip"] or "")
                x = devices.setdefault(k, {"device": k[0], "ip": k[1], "last_at": e["at"], "count": 0}); x["count"] += 1
        acts = c.rows("SELECT at, action, detail, login_id AS by_login FROM audit_log WHERE entity='user' AND entity_id=? AND action LIKE 'account_%' "
                      "ORDER BY at DESC, id DESC LIMIT 30", (uid,))
        failed = sum(1 for e in ev if not e["ok"] and e["at"] >= shift(now, -86400))
        return jsonify(person=t, events=ev, devices=list(devices.values()), actions=acts, failed_24h=failed, now=now)

    def one_action(action):
        def view(uid):
            bad = guard()
            if bad: return bad
            miss, t = target(uid)
            if miss: return c.err(*miss)
            res, e = apply(action, t, request.get_json(silent=True) or {}, c.utc_stamp())
            if e: return c.err(*e)
            c.db().commit()
            return jsonify(ok=True, **res)
        view.__name__ = "acc_" + action
        return view

    for a in ACTIONS:
        app.add_url_rule(f"/api/admin/accounts/<int:uid>/{a}", "acc_" + a, c.auth("admin")(one_action(a)), methods=["POST"])

    @app.post("/api/admin/accounts/bulk")
    @c.auth("admin")
    def acc_bulk():
        bad = guard()
        if bad: return bad
        d = request.get_json(silent=True) or {}
        action = d.get("action")
        if action not in ACTIONS: return c.err("Choose an action")
        ids = list(dict.fromkeys(int(i) for i in (d.get("ids") or []) if str(i).isdigit()))
        if not ids: return c.err("Tick at least one person")
        if len(ids) > 500: return c.err("At most 500 people at a time")
        now = c.utc_stamp()
        until = None
        if action == "pause":   # one end time for everyone, checked once
            until, e = pause_end(d, now)
            if e: return c.err(e)
        if action == "suspend" and not clean(d.get("reason"), 300): return c.err("Write a reason")
        done, skipped = [], []
        for uid in ids:
            miss, t = target(uid)
            if miss: skipped.append({"id": uid, "error": miss[0]}); continue
            res, e = apply(action, t, d, now, until)
            (skipped.append({"id": uid, "name": t["full_name"], "error": e[0]}) if e else done.append(uid))
        c.db().commit()
        return jsonify(ok=True, done=len(done), skipped=skipped)

    @app.post("/api/admin/accounts/signout-all")
    @c.auth("admin")
    def acc_signout_all():
        bad = guard()
        if bad: return bad
        d = request.get_json(silent=True) or {}
        role = d.get("role") or ""
        if role not in ("", "student", "teacher", "admin"): return c.err("Unknown role")
        now, reason = c.utc_stamp(), clean(d.get("reason"), 300)
        sql, args = "UPDATE users SET token_version=COALESCE(token_version,0)+1, signed_out_at=? WHERE id<>?", [now, g.user["id"]]
        if role: sql += " AND role=?"; args.append(role)
        n = c.db().execute(sql, args).rowcount
        c.audit("account_signout_all", "user", None, f"Signed out everyone{' (' + role + 's)' if role else ''} except {g.user['full_name']}: {n} accounts"
                + (f": {reason}" if reason else ""))
        c.db().commit()
        return jsonify(ok=True, count=n)
