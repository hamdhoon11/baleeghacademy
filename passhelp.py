"""v0.8.35: "Forgot password" without email.

  POST /api/auth/forgot            public. {login: login ID or email, contact: optional phone}. Always the same answer, so it never
                                   tells whether an account exists. Limited per network address and per account.
  GET  /api/password-help          admins with People: open requests (newest first)
  POST /api/password-help/<id>/dismiss

Resetting is the normal POST /api/users/<id>/reset-password (app.py); it closes that person's open requests and now also returns a
WhatsApp link with the new password, so the admin can send it in one tap.
"""
import datetime as dt
import time
from urllib.parse import quote

from flask import g, jsonify, request

import common

ANSWER = "Thank you. If this account exists, the academy has been told and will send you a new password by WhatsApp."
PER_IP_HOUR = 5


def stamp():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def wa_link(phone, text):
    d = common.digits_intl(phone)
    return f"https://wa.me/{d}?text={quote(text)}" if len(d) >= 7 else None


def register(app, c):
    hits = {}

    @app.post("/api/auth/forgot")
    def forgot():
        d = request.get_json(silent=True) or {}
        login = str(d.get("login") or "").strip()[:120]
        contact = str(d.get("contact") or "").strip()[:40] or None
        if not login: return c.err("Type your login ID or email")
        ip = request.remote_addr or "?"
        now = time.time()
        hits[ip] = [x for x in hits.get(ip, []) if now - x < 3600]
        if len(hits[ip]) >= app.config.get("FORGOT_LIMIT", PER_IP_HOUR):
            return jsonify(ok=True, message=ANSWER)   # same answer: nothing to learn from the limit either
        hits[ip].append(now)
        u = c.one("SELECT id, full_name, login_id, role, is_active FROM users WHERE UPPER(login_id)=UPPER(?) OR LOWER(email)=LOWER(?)", (login, login))
        uid = u["id"] if u and u["is_active"] else None
        if uid and c.one("SELECT 1 x FROM password_help WHERE user_id=? AND status='pending'", (uid,)):
            return jsonify(ok=True, message=ANSWER)   # one open request per person is enough
        c.db().execute("INSERT INTO password_help(user_id,login_text,contact,status,ip,created_at) VALUES(?,?,?,'pending',?,?)", (uid, login, contact, ip, stamp()))
        c.audit("forgot_request", "user", uid, ("matched " if uid else "no match: ") + login)
        if uid:
            c.notify(c.notify_admins_with("people"), "password_help", "Password help requested",
                     f"{u['full_name']} ({u['login_id'] or login}) asked for a new password.", f"people:{uid}")
        c.db().commit()
        return jsonify(ok=True, message=ANSWER)

    @app.get("/api/password-help")
    @c.auth("admin", perm="people")
    def help_list():
        r = c.rows("SELECT h.id, h.user_id, h.login_text, h.contact, h.created_at, u.full_name, u.login_id, u.role, u.phone, "
                   "(SELECT s.guardian_phone FROM students s WHERE s.user_id=u.id) AS guardian_phone "
                   "FROM password_help h LEFT JOIN users u ON u.id=h.user_id WHERE h.status='pending' ORDER BY h.id DESC LIMIT 100")
        return jsonify(r)

    @app.post("/api/password-help/<int:hid>/dismiss")
    @c.auth("admin", perm="people")
    def help_dismiss(hid):
        h = c.one("SELECT id, status FROM password_help WHERE id=?", (hid,))
        if not h: return c.err("Not found", 404)
        if h["status"] != "pending": return c.err("Already handled", 409)
        c.db().execute("UPDATE password_help SET status='dismissed', handled_by=?, handled_at=? WHERE id=?", (g.user["id"], stamp(), hid))
        c.audit("forgot_dismiss", "user", None, str(hid)); c.db().commit()
        return jsonify(ok=True)

    def close_for(uid):
        c.db().execute("UPDATE password_help SET status='done', handled_by=?, handled_at=? WHERE user_id=? AND status='pending'", (g.user["id"], stamp(), uid))

    app.extensions["passhelp"] = {"close_for": close_for, "wa_link": wa_link,
                                  "pending": lambda: c.one("SELECT COUNT(*) n FROM password_help WHERE status='pending'")["n"]}
