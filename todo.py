"""v0.8.35: the admin Dashboard's "To do today": everything waiting for an admin, each with where to go. Only areas the admin has.
v0.8.63: GET /api/my/todo, everyone's own to-do list (the bell's "To do" tab): what is still to do, what is waiting, and what is done.

  GET /api/admin/todo -> {items: [{key, n, view, patch, level}], classes: [today's started classes without attendance]}
  GET /api/my/todo    -> {items: [{key, status: todo|waiting|done, title, sub, level, view, patch, n}], todo: number still to do}
Read only. Counts use the same rules as the screens they open (Admissions pending, Fees slips/overdue, People password help, ...).
"""
import datetime as dt

from flask import g, jsonify

import filecheck


def register(app, c):
    def admin_items():
        u, items = g.user, []
        can = lambda area: c.has_perm(u, area)
        add = lambda key, n, view, patch=None, level="warn": items.append({"key": key, "n": int(n or 0), "view": view, "patch": patch or {}, "level": level}) if n else None
        if can("admissions"):
            add("todo_applications", c.one("SELECT COUNT(*) n FROM applications WHERE status='pending'")["n"], "admissions")
        if can("fees"):
            fx = app.extensions.get("fees", {}).get("dashboard")
            d = fx() if fx else {}
            add("todo_slips", d.get("slips_pending"), "fees", {"fxt": "slips"})
            add("todo_overdue", d.get("overdue_invoices"), "fees", {"fxt": "overdue"})
        if can("people"):
            ph = app.extensions.get("passhelp")
            if ph: add("todo_password_help", ph["pending"](), "people")
        if can("enrollments"):
            add("todo_waitlist", c.one("SELECT COUNT(*) n FROM enrollments WHERE status='waitlist'")["n"], "enrollments", level="info")
        classes = []
        if can("classroom"):
            f = app.extensions.get("classes_without_attendance")
            classes = [{"batch_id": o["batch_id"], "batch_code": o["batch_code"], "course_name": o["course_name"], "teacher_name": o["teacher_name"],
                        "start_time": o["start_time"], "date": o["date"]} for o in (f() if f else [])]
            add("todo_attendance", len(classes), "classroom", {"ct": "attendance"})
        if can("settings"):
            h = filecheck.health(app, c.store)
            if not h["persistent"]: add("todo_storage", 1, "settings", level="bad")
        return items, classes

    @app.get("/api/admin/todo")
    @c.auth("admin")
    def admin_todo():
        items, classes = admin_items()
        return jsonify(items=items, classes=classes)

    def fee_items(u):
        """The student's open invoices: to pay, or a slip waiting to be checked. Nothing open = one 'done' line."""
        out = []
        for i in c.rows("SELECT id,description,amount_due_mvr,paid_mvr,due_date,status FROM invoices WHERE student_id=? AND status IN ('unpaid','slip_submitted') "
                        "ORDER BY due_date, id LIMIT 10", (u["id"],)):
            owed = int(i["amount_due_mvr"] or 0) - int(i["paid_mvr"] or 0)
            if owed <= 0: continue
            late = bool(i["due_date"] and i["due_date"][:10] < mv_today())
            out.append({"key": "td_fee_slip" if i["status"] == "slip_submitted" else "td_fee", "status": "waiting" if i["status"] == "slip_submitted" else "todo",
                        "title": i["description"], "sub": i["due_date"], "level": "info" if i["status"] == "slip_submitted" else ("bad" if late else "warn"),
                        "view": "fees", "patch": {"fxhl": i["id"]}, "n": owed})
        return out or [{"key": "td_fees_clear", "status": "done", "title": None, "sub": None, "level": "ok", "view": "fees", "patch": {}, "n": None}]

    def mv_today():   # Maldives date; tests inject a clock through NOW
        n = app.config["NOW"]() if app.config.get("NOW") else dt.datetime.now(dt.timezone(dt.timedelta(hours=5)))
        return n.date().isoformat()

    @app.get("/api/my/todo")
    @c.auth()
    def my_todo():
        u = g.user
        if u["role"] == "admin":
            raw, _ = admin_items()
            items = [{"key": x["key"], "status": "todo", "title": None, "sub": None, "level": x["level"], "view": x["view"], "patch": x["patch"], "n": x["n"]} for x in raw]
            if not items: items.append({"key": "td_admin_clear", "status": "done", "title": None, "sub": None, "level": "ok", "view": "dashboard", "patch": {}, "n": None})
        else:
            f = app.extensions.get("my_todo")
            items = f() if f else []
            if u["role"] == "student" and c.has_perm(u, "fees"): items += fee_items(u)
        pu = app.extensions.get("posts_unread")
        if pu:
            n = pu(u)
            items.append({"key": "td_posts" if n else "td_posts_read", "status": "todo" if n else "done", "title": None, "sub": None,
                          "level": "info" if n else "ok", "view": "posts", "patch": {}, "n": n or None})
        order = {"todo": 0, "waiting": 1, "done": 2}
        items.sort(key=lambda x: order[x["status"]])   # stable: each part keeps its own order
        resp = jsonify(items=items, todo=sum(1 for x in items if x["status"] == "todo"))
        resp.headers["Cache-Control"] = "private, no-store"
        return resp
