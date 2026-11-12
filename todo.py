"""v0.8.35: the admin Dashboard's "To do today": everything waiting for an admin, each with where to go. Only areas the admin has.

  GET /api/admin/todo -> {items: [{key, n, view, patch, level}], classes: [today's started classes without attendance]}
Read only. Counts use the same rules as the screens they open (Admissions pending, Fees slips/overdue, People password help, ...).
"""
from flask import g, jsonify

import filecheck


def register(app, c):
    @app.get("/api/admin/todo")
    @c.auth("admin")
    def admin_todo():
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
        return jsonify(items=items, classes=classes)
