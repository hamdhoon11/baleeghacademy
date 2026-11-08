"""Session 29: WhatsApp messages from the academy's own WhatsApp, by phone number (click-to-chat; no provider, no cost, nothing sent by the server).

  POST /api/whatsapp/prepare   admin   {audience: student|batch|students|teachers|everyone, student_id, batch_id, message, guardians}
       -> {items[{user_id, name, to, phone, url, sent_today}], missing[{name, to}], count}
       Placeholders in message: {name} (who it is addressed to), {student}, {academy}. Needs student_information (students, guardians) and/or teacher_information (teachers).
  POST /api/whatsapp/sent      admin   {user_id, to}  records that the admin opened the chat (log + activity log); returns {ok}

The admin taps "Open WhatsApp" for each person; WhatsApp opens with the text ready and the admin presses Send. WhatsApp does not allow a normal number to be
driven automatically, so the portal prepares and remembers, it never sends by itself. 7-digit Maldives numbers get 960 (common.digits_intl).
"""
import re
from urllib.parse import quote
from flask import g, jsonify, request
import common

MAX_PEOPLE, MAX_TEXT = 500, 1000
AUDIENCES = ("student", "batch", "students", "teachers", "everyone")


def register(app, c, now):
    db, rows, one, err, auth, audit = c.db, c.rows, c.one, c.err, c.auth, c.audit
    stamp = lambda: now().isoformat(timespec="seconds")
    fill = lambda tpl, vals: re.sub(r"\{(\w+)\}", lambda m: str(vals.get(m.group(1), m.group(0))), tpl)
    valid = lambda num: 8 <= len(num) <= 15

    @app.post("/api/whatsapp/prepare")
    @auth("admin")
    def wa_prepare():
        d = request.get_json(silent=True) or {}
        text, aud = (d.get("message") or "").strip(), d.get("audience")
        if not text: return err("Write the message first")
        if len(text) > MAX_TEXT: return err(f"The message can be up to {MAX_TEXT} characters")
        if aud not in AUDIENCES: return err("Choose who should get it: one student, a batch, all students, all teachers or everyone")
        u, guardians = g.user, bool(d.get("guardians"))
        need_s = aud in ("student", "batch", "students", "everyone") or guardians
        need_t = aud in ("teachers", "everyone") or aud == "batch"
        if need_s and not c.has_perm(u, "student_information"): return err("Your account does not have permission to use student phone numbers", 403)
        if aud in ("teachers", "everyone") and not c.has_perm(u, "teacher_information"): return err("Your account does not have permission to use teacher phone numbers", 403)
        st_sql = ("SELECT u.id,u.full_name,u.phone,s.guardian_name,s.guardian_phone FROM users u LEFT JOIN students s ON s.user_id=u.id WHERE u.role='student' AND u.is_active=1")
        people = []                                           # (user row, kind)
        if aud == "student":
            try: sid = int(d.get("student_id"))
            except (TypeError, ValueError): return err("Choose a student")
            r = one(st_sql + " AND u.id=?", (sid,))
            if not r: return err("Student not found", 404)
            people = [(r, "student")]
        elif aud == "batch":
            try: bid = int(d.get("batch_id"))
            except (TypeError, ValueError): return err("Choose a batch")
            b = one("SELECT id,teacher_id FROM batches WHERE id=?", (bid,))
            if not b: return err("Batch not found", 404)
            people = [(r, "student") for r in rows(st_sql + " AND u.id IN (SELECT student_id FROM enrollments WHERE batch_id=? AND status='active') ORDER BY LOWER(u.full_name)", (bid,))]
        elif aud in ("students", "everyone"):
            people = [(r, "student") for r in rows(st_sql + " ORDER BY LOWER(u.full_name)")]
        if aud in ("teachers", "everyone"):
            people += [(r, "teacher") for r in rows("SELECT id,full_name,phone,NULL AS guardian_name,NULL AS guardian_phone FROM users WHERE role='teacher' AND is_active=1 ORDER BY LOWER(full_name)")]
        if aud == "batch" and b["teacher_id"] and c.has_perm(u, "teacher_information"):
            t = one("SELECT id,full_name,phone,NULL AS guardian_name,NULL AS guardian_phone FROM users WHERE id=? AND is_active=1", (b["teacher_id"],))
            if t: people.append((t, "teacher"))
        academy = (c.raw_setting("academy_name") or "").strip() or "Baleegh Academy"
        today, items, missing = stamp()[:10], [], []
        for r, kind in people:
            targets = [(kind, r["phone"], r["full_name"])]
            if guardians and kind == "student": targets.append(("guardian", r["guardian_phone"], r["guardian_name"] or "Parent/Guardian of " + r["full_name"]))
            for to, phone, who in targets:
                num = common.digits_intl(phone)
                if not valid(num): missing.append({"user_id": r["id"], "name": who if to != "guardian" else f"{who} (guardian)", "to": to}); continue
                body = fill(text, {"name": who, "student": r["full_name"], "academy": academy})
                done = one("SELECT 1 x FROM wa_log WHERE user_id=? AND to_kind=? AND SUBSTR(sent_at,1,10)=?", (r["id"], to, today))
                items.append({"user_id": r["id"], "name": who, "to": to, "phone": phone, "url": f"https://wa.me/{num}?text={quote(body)}", "sent_today": bool(done)})
        if len(items) > MAX_PEOPLE: return err(f"That is {len(items)} chats. Send to a batch at a time (at most {MAX_PEOPLE}).", 400)
        resp = jsonify(items=items, missing=missing, count=len(items))
        resp.headers["Cache-Control"] = "private, no-store"      # phone numbers
        return resp

    @app.post("/api/whatsapp/sent")
    @auth("admin")
    def wa_sent():
        d = request.get_json(silent=True) or {}
        to = d.get("to")
        if to not in ("student", "teacher", "guardian"): return err("to must be student, teacher or guardian")
        try: uid = int(d.get("user_id"))
        except (TypeError, ValueError): return err("Missing: user_id")
        row = one("SELECT u.id,u.role,u.phone,s.guardian_phone FROM users u LEFT JOIN students s ON s.user_id=u.id WHERE u.id=?", (uid,))
        if not row or row["role"] != ("teacher" if to == "teacher" else "student"): return err("Person not found", 404)
        phone = row["guardian_phone"] if to == "guardian" else row["phone"]
        db().execute("INSERT INTO wa_log(user_id,to_kind,phone,preview,sent_by,sent_at) VALUES(?,?,?,?,?,?)", (uid, to, phone, (d.get("preview") or "")[:80] or None, g.user["id"], stamp()))
        audit("whatsapp_sent", "user", uid, f"{to} chat opened")
        db().commit()
        return jsonify(ok=True), 201
