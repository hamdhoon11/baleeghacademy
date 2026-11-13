"""Session 28: in-app notifications, announcements and scheduled reminders.

Everyone (student, teacher, admin) sees their OWN notifications only:
  GET  /api/notifications            ?unread=1&limit=30&before=<id>   -> {items, unread}
  GET  /api/notifications/unread-count                                -> {unread}   (the bell polls this)
  POST /api/notifications/<id>/read
  POST /api/notifications/read-all

Admin:
  POST /api/announcements            area classroom   {title, message, audience: batch|students|teachers|everyone, batch_id}
  POST /api/notifications/run        area settings    ?dry_run=1 is the DEFAULT (counts only, nothing kept); dry_run=0 runs the reminders now
  GET  /api/notifications/status     area settings    when the scheduled run last happened and what the reminder settings are

Scheduled (Vercel Cron, daily 02:30 UTC = 07:30 Maldives; Bearer CRON_SECRET, same rule as the invoice cron):
  GET|POST /api/cron/reminders

Events create notifications through `ns.notify(...)` (called by fees, learning and substitutions before their own commit, so a rolled-back
request leaves no notification behind). Scheduled reminders use a dedupe key, so running twice in one day sends nothing twice.
Links (Session 16, v0.8.33): "tab" or "tab:id" (assignments:<assignment id>, fees:<invoice id>, classroom:<batch id>). The page opens the
tab and then the item; rows written before v0.8.33 hold a plain tab name and still work.
Nothing here sends email, WhatsApp or SMS: the Fees -> Overdue screen still does that by hand.
"""
import datetime as dt, hmac, os
from flask import g, jsonify, request
import settings_schema as SS

LAST_RUN_KEY = "_last_reminder_run"          # stored in the settings table but not in SETTING_KEYS, so the Settings screen never shows or edits it
KEEP_READ_DAYS, KEEP_ALL_DAYS = 90, 180
FALLBACK_TABS = ("home", "dashboard")


def register(app, c, now):
    """now() -> timezone-aware datetime (Maldives time, or the injected test clock)."""
    db, rows, one, err, auth, audit = c.db, c.rows, c.one, c.err, c.auth, c.audit

    def utc(n=None):
        return (n or now()).astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")      # same text format as datetime('now')

    def conf(key):
        v = (c.raw_setting(key) or "").strip()
        return v or SS.SETTINGS[key]["default"]

    def num(key):
        try: return max(0, int(conf(key)))
        except ValueError: return int(SS.SETTINGS[key]["default"])

    def enabled():
        return conf("notify_enabled") not in ("0", "false", "no", "off")

    # ---------------- helpers other modules call ----------------
    def push(user_ids, kind, title, body=None, link=None, dedupe=None):
        """Add one notification per person (people listed twice get one). Does NOT commit. Returns how many were created."""
        if not enabled(): return 0
        n, title, body = 0, str(title)[:120], (str(body)[:500] if body else None)
        for uid in dict.fromkeys(u for u in user_ids if u):
            cur = db().execute("INSERT OR IGNORE INTO notifications(user_id,kind,title,body,link,dedupe_key,created_at) VALUES(?,?,?,?,?,?,?)",
                               (uid, kind, title, body, link, dedupe(uid) if callable(dedupe) else dedupe, utc()))
            n += 1 if cur.rowcount and cur.rowcount > 0 else 0
        return n

    def students_of(bid):
        return [r["student_id"] for r in rows("SELECT e.student_id FROM enrollments e JOIN users u ON u.id=e.student_id WHERE e.batch_id=? AND e.status='active' AND u.is_active=1", (bid,))]

    def admins_with(area):
        return [u["id"] for u in rows("SELECT id,role,permissions FROM users WHERE role='admin' AND is_active=1") if c.has_perm(u, area)]

    c.notify, c.notify_students_of, c.notify_admins_with = push, students_of, admins_with

    # ---------------- my notifications ----------------
    def unread(uid):
        return one("SELECT COUNT(*) n FROM notifications WHERE user_id=? AND read_at IS NULL", (uid,))["n"]

    @app.get("/api/notifications")
    @auth()
    def n_list():
        a = request.args
        try: limit = max(1, min(100, int(a.get("limit", 30))))
        except ValueError: return err("limit must be a number")
        w, args = ["user_id=?"], [g.user["id"]]
        if a.get("unread") == "1": w.append("read_at IS NULL")
        if a.get("before", "").isdigit(): w.append("id<?"); args.append(int(a["before"]))
        items = rows("SELECT id,kind,title,body,link,created_at,read_at FROM notifications WHERE " + " AND ".join(w) + " ORDER BY id DESC LIMIT ?", args + [limit])
        resp = jsonify(items=items, unread=unread(g.user["id"]))
        resp.headers["Cache-Control"] = "private, no-store"
        return resp

    @app.get("/api/notifications/unread-count")
    @auth()
    def n_count():
        resp = jsonify(unread=unread(g.user["id"]))
        resp.headers["Cache-Control"] = "private, no-store"
        return resp

    @app.post("/api/notifications/<int:nid>/read")
    @auth()
    def n_read(nid):
        cur = db().execute("UPDATE notifications SET read_at=? WHERE id=? AND user_id=? AND read_at IS NULL", (utc(), nid, g.user["id"]))
        if not cur.rowcount and not one("SELECT 1 x FROM notifications WHERE id=? AND user_id=?", (nid, g.user["id"])):
            db().rollback(); return err("Notification not found", 404)
        db().commit()
        return jsonify(ok=True, unread=unread(g.user["id"]))

    @app.post("/api/notifications/read-all")
    @auth()
    def n_read_all():
        cur = db().execute("UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL", (utc(), g.user["id"]))
        db().commit()
        return jsonify(ok=True, marked=max(cur.rowcount or 0, 0), unread=0)

    # ---------------- announcements ----------------
    @app.post("/api/announcements")
    @auth("admin", perm="classroom")
    def announce():
        d = request.get_json(silent=True) or {}
        title, text, aud = (d.get("title") or "").strip(), (d.get("message") or "").strip(), d.get("audience")
        if not title: return err("Write a title")
        if len(title) > 100: return err("The title can be up to 100 characters")
        if len(text) > 500: return err("The message can be up to 500 characters")
        if not enabled(): return err("Notifications are turned off in Settings, so nothing was sent", 409)
        active = lambda role: [r["id"] for r in rows("SELECT id FROM users WHERE role=? AND is_active=1", (role,))]
        where = aud
        if aud == "batch":
            try: bid = int(d.get("batch_id"))
            except (TypeError, ValueError): return err("Choose a batch")
            b = one("SELECT id,code,teacher_id FROM batches WHERE id=?", (bid,))
            if not b: return err("Batch not found", 404)
            ids, where = students_of(bid) + ([b["teacher_id"]] if b["teacher_id"] else []), f"batch {b['code']}"
        elif aud == "students": ids = active("student")
        elif aud == "teachers": ids = active("teacher")
        elif aud == "everyone": ids = active("student") + active("teacher")
        else: return err("Choose who should get it: a batch, all students, all teachers or everyone")
        ids = list(dict.fromkeys(ids))
        if not ids: return err("There is nobody in that group to send it to", 409)
        push(ids, "announcement", title, text or None, "home")
        audit("send_announcement", "announcement", None, f"{where}: {len(ids)} people: {title}", **({"batch_id": bid} if aud == "batch" else {}))
        db().commit()
        return jsonify(ok=True, sent=len(ids)), 201

    # ---------------- scheduled reminders ----------------
    def run_reminders(dry):
        """Create the day's reminders. Safe to run any number of times a day. dry=True counts what WOULD be created and keeps nothing."""
        n, t = now(), now().date()
        out = {"date": t.isoformat(), "fee_due_soon": 0, "fee_overdue": 0, "assignment_due": 0, "admin_digest": 0, "removed_old": 0, "skipped": ""}
        if not enabled():
            out["skipped"] = "Notifications are turned off in Settings"
            return out
        bal = "i.amount_due_mvr-i.waived_mvr-i.paid_mvr"
        # 1. fees due soon (unpaid only: a student who already sent a slip is waiting for the admin, not for a reminder)
        days = num("remind_fee_days_before")
        if days:
            for r in rows(f"SELECT i.id,i.student_id,i.period,i.due_date,{bal} AS bal,COALESCE(c.name, i.description) AS course FROM invoices i LEFT JOIN courses c ON c.id=i.course_id "
                          f"WHERE i.student_id IS NOT NULL AND i.status='unpaid' AND i.due_date>=? AND i.due_date<=? AND {bal}>0", (t.isoformat(), (t + dt.timedelta(days=days)).isoformat())):
                out["fee_due_soon"] += push([r["student_id"]], "fee_due_soon", "Fee due soon",
                                            f"{r['course']} ({r['period']}): {r['bal']} MVR is due on {r['due_date']}.", f"fees:{r['id']}", f"due:{r['id']}")
        # 2. overdue fees: first the day after the due date, then every N days (one dedupe bucket per N days, so a missed day still sends once)
        every = num("remind_overdue_every_days")
        over = rows(f"SELECT i.id,i.student_id,i.period,i.due_date,{bal} AS bal,COALESCE(c.name, i.description) AS course FROM invoices i LEFT JOIN courses c ON c.id=i.course_id "
                    f"WHERE i.student_id IS NOT NULL AND i.status='unpaid' AND i.due_date<? AND {bal}>0", (t.isoformat(),))
        if every:
            for r in over:
                late = (t - dt.date.fromisoformat(r["due_date"])).days
                out["fee_overdue"] += push([r["student_id"]], "fee_overdue", "Fee overdue",
                                           f"{r['course']} ({r['period']}): {r['bal']} MVR was due on {r['due_date']} ({late} day{'s' if late != 1 else ''} ago).",
                                           f"fees:{r['id']}", f"overdue:{r['id']}:{(late - 1) // every}")
        # 3. assignments due soon, for students who have not handed in
        days = num("remind_assignment_days_before")
        if days:
            for r in rows("SELECT a.id,a.title,a.due_date,e.student_id FROM assignments a JOIN enrollments e ON e.batch_id=a.batch_id AND e.status='active' "
                          "JOIN users u ON u.id=e.student_id AND u.is_active=1 WHERE a.due_date IS NOT NULL AND SUBSTR(a.due_date,1,10)>=? AND SUBSTR(a.due_date,1,10)<=? "
                          "AND NOT EXISTS (SELECT 1 FROM submissions s WHERE s.assignment_id=a.id AND s.student_id=e.student_id AND s.submitted_at IS NOT NULL)",
                          (t.isoformat(), (t + dt.timedelta(days=days)).isoformat())):
                out["assignment_due"] += push([r["student_id"]], "assignment_due", "Assignment due soon", f"{r['title']} is due on {r['due_date'][:10]}.", f"assignments:{r['id']}", f"assign:{r['id']}")
        # 4. one daily line for admins who handle fees
        fee_admins = admins_with("fees")
        slips = one("SELECT COUNT(*) n FROM payment_slips WHERE status='pending'")["n"]
        if over:
            out["admin_digest"] += push(fee_admins, "admin_overdue", "Overdue invoices", f"{len(over)} invoice{'s are' if len(over) != 1 else ' is'} overdue.", "fees", f"digest-overdue:{t.isoformat()}")
        if slips:
            out["admin_digest"] += push(fee_admins, "admin_slips", "Payment slips waiting", f"{slips} slip{'s are' if slips != 1 else ' is'} waiting to be checked.", "fees", f"digest-slips:{t.isoformat()}")
        # 5. housekeeping: read ones after 90 days, everything after 180
        read_cut, all_cut = utc(n - dt.timedelta(days=KEEP_READ_DAYS)), utc(n - dt.timedelta(days=KEEP_ALL_DAYS))
        cur = db().execute("DELETE FROM notifications WHERE (read_at IS NOT NULL AND read_at<?) OR created_at<?", (read_cut, all_cut))
        out["removed_old"] = max(cur.rowcount or 0, 0)
        return out

    def finish(out, dry, system):
        made = out["fee_due_soon"] + out["fee_overdue"] + out["assignment_due"] + out["admin_digest"]
        if dry: db().rollback(); return out
        db().execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (LAST_RUN_KEY, utc()))
        if made or out["removed_old"]:
            audit("run_reminders", "notification", None,
                  f"{out['date']}: fee due soon {out['fee_due_soon']}, overdue {out['fee_overdue']}, assignments {out['assignment_due']}, admin {out['admin_digest']}, removed {out['removed_old']} ({'scheduled run' if system else 'run by an admin'})",
                  **({"role": "system"} if system else {}))
        db().commit()
        return out

    def cron_ok():
        secret = app.config.get("CRON_SECRET") or os.environ.get("CRON_SECRET") or ""
        got = request.headers.get("Authorization") or ""
        return bool(secret) and got.startswith("Bearer ") and hmac.compare_digest(got[7:].encode(), secret.encode())

    @app.route("/api/cron/reminders", methods=["GET", "POST"])
    def cron_reminders():
        if not cron_ok(): return err("Not allowed", 401)
        return jsonify(finish(run_reminders(False), False, True))

    @app.post("/api/notifications/run")
    @auth("admin", perm="settings")
    def n_run():
        dry = request.args.get("dry_run", "1") != "0"
        out = finish(run_reminders(dry), dry, False)
        return jsonify(dry_run=dry, **out)

    @app.get("/api/notifications/status")
    @auth("admin", perm="settings")
    def n_status():
        return jsonify(enabled=enabled(), last_run=c.raw_setting(LAST_RUN_KEY) or None, cron_secret_set=bool(app.config.get("CRON_SECRET") or os.environ.get("CRON_SECRET")),
                       fee_days_before=num("remind_fee_days_before"), overdue_every_days=num("remind_overdue_every_days"), assignment_days_before=num("remind_assignment_days_before"),
                       unread_total=one("SELECT COUNT(*) n FROM notifications WHERE read_at IS NULL")["n"])
