"""Session 27: exports and imports of people and enrolments.

Exports (CSV or Excel, every download is logged; no fees, no internal notes, no passwords or hashes):
  GET /api/student-information/export.csv|.xlsx      area student_information  ?q=&batch_id=&status=active|inactive
  GET /api/student-information/enrolments.csv|.xlsx  area student_information  one row per enrolment (the file the enrolment import reads)
  GET /api/teacher-information/export.csv|.xlsx      area teacher_information  ?q=&status=active|inactive

Imports (v0.8.38: Excel .xlsx or CSV UTF-8; multipart field "file" or a text/csv body; at most 2000 rows and 2 MB).
Templates to fill in: GET /api/import/<students|teachers|enrolments>/template.xlsx (same areas as the import):
  POST /api/import/students    area people       columns: full_name, email (required); student_code, login_id, phone, date_of_birth, grade, island,
                                                 guardian_name, guardian_relationship, guardian_phone, is_active (optional)
  POST /api/import/teachers    area people       columns: full_name, email (required); teacher_code, login_id, phone, bio, is_active
  POST /api/import/enrolments  area enrollments  columns: course_code, batch_code and one of student_code / login_id / student_email (required);
                                                 status (default active), enrol_code, enrolled_at (optional)
  ?dry_run=1 is the DEFAULT: nothing is written, every row is checked and reported. Send dry_run=0 to import.
  A rejected row never blocks the others; every rejected row comes back with its row number and the reason.
  New accounts get a random temporary password and must change it at first sign-in. The passwords are returned ONCE in the import response
  (Cache-Control: no-store) and are never written to the log. IDs in the file are kept when unused; otherwise the Session 10 generator issues them.
  Courses and batches are not created by an import: they must exist (matched by course code and batch code).
"""
import csv, datetime as dt, io, re, secrets
from flask import Response, jsonify, request
from werkzeug.security import generate_password_hash

import excelio, idcodes
from payreports import to_xlsx, csv_safe, XLSX_MIME

CODE = re.compile(r"^[A-Z0-9][A-Z0-9/._-]{2,39}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_ROWS, MAX_BYTES = 2000, 2 * 1024 * 1024
STUDENT_COLS = ["student_code", "login_id", "full_name", "email", "phone", "date_of_birth", "grade", "island", "guardian_name", "guardian_relationship", "guardian_phone", "is_active"]
TEACHER_COLS = ["teacher_code", "login_id", "full_name", "email", "phone", "bio", "is_active"]
ENROL_COLS = ["student_code", "student_name", "course_code", "batch_code", "status", "enrol_code", "enrolled_at"]
STATUSES = ("active", "waitlist", "dropped", "completed")
TEMP_HASH = "pbkdf2:sha256:1000"   # only for the random temporary passwords of imported accounts, see apply_person()


def register(app, c):
    db, rows, one, err, auth, audit = c.db, c.rows, c.one, c.err, c.auth, c.audit

    # ---------------- exports ----------------
    def like(v): return "%" + v.lower().replace("\\", "").replace("%", "").replace("_", "") + "%"

    def send(ext, name, headers, table, action, detail):
        if ext == "csv":
            buf = io.StringIO(); w = csv.writer(buf); w.writerow(headers)
            for r in table: w.writerow([csv_safe(v) for v in r])
            body, mime = buf.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8"
        else:
            body, mime = to_xlsx(table, headers, name), XLSX_MIME
        audit(action, "report", None, f"{ext} {detail} {len(table)} rows"); db().commit()
        resp = Response(body, mimetype=mime)
        resp.headers["Content-Disposition"] = f'attachment; filename="{name}.{ext}"'
        resp.headers["Cache-Control"] = "private, no-store"
        return resp

    def people_where(role, a):
        w, args = [f"u.role='{role}'"], []
        qs = (a.get("q") or "").strip()[:100]
        if qs: w.append("(LOWER(u.full_name) LIKE ? OR LOWER(u.email) LIKE ? OR LOWER(COALESCE(u.phone,'')) LIKE ?)"); args += [like(qs)] * 3
        if a.get("batch_id", "").isdigit() and role == "student":
            w.append("u.id IN (SELECT student_id FROM enrollments WHERE batch_id=? AND status IN ('active','completed'))"); args.append(int(a["batch_id"]))
        if a.get("status") in ("active", "inactive"): w.append("u.is_active=?"); args.append(1 if a["status"] == "active" else 0)
        return " WHERE " + " AND ".join(w), args

    def student_export(ext):
        where, a = people_where("student", request.args)
        sts = rows("SELECT u.id, u.full_name, u.email, u.phone, u.is_active, u.login_id, s.* FROM users u LEFT JOIN students s ON s.user_id=u.id" + where + " ORDER BY LOWER(u.full_name), u.id", a)
        en = {}
        for r in rows("SELECT e.student_id, e.status, e.enrol_code, b.code AS bc, c.name AS cn FROM enrollments e JOIN batches b ON b.id=e.batch_id JOIN courses c ON c.id=b.course_id ORDER BY e.id"):
            en.setdefault(r["student_id"], []).append(f"{r['cn']} · {r['bc']} ({r['enrol_code'] or '-'}, {r['status']})")
        table = [[s["student_code"] or "", s["login_id"] or "", s["full_name"], s["email"], s["phone"] or "", s["date_of_birth"] or "", s["grade"] or "", s["island"] or "",
                  s["guardian_name"] or "", s["guardian_relationship"] or "", s["guardian_phone"] or "", 1 if s["is_active"] else 0, "; ".join(en.get(s["id"], []))] for s in sts]
        return send(ext, "student-information", STUDENT_COLS + ["enrolments"], table, "export_student_information", "students")

    def teacher_export(ext):
        where, a = people_where("teacher", request.args)
        ts = rows("SELECT u.id, u.full_name, u.email, u.phone, u.is_active, u.login_id, t.teacher_code, t.bio FROM users u LEFT JOIN teachers t ON t.user_id=u.id" + where + " ORDER BY LOWER(u.full_name), u.id", a)
        bt = {}
        for r in rows("SELECT b.teacher_id, b.code AS bc, c.name AS cn FROM batches b JOIN courses c ON c.id=b.course_id WHERE b.teacher_id IS NOT NULL ORDER BY b.id"):
            bt.setdefault(r["teacher_id"], []).append(f"{r['cn']} · {r['bc']}")
        table = [[t["teacher_code"] or "", t["login_id"] or "", t["full_name"], t["email"], t["phone"] or "", t["bio"] or "", 1 if t["is_active"] else 0, "; ".join(bt.get(t["id"], []))] for t in ts]
        return send(ext, "teacher-information", TEACHER_COLS + ["batches"], table, "export_teacher_information", "teachers")

    def enrol_export(ext):
        rs = rows("SELECT u.full_name, s.student_code, c.code AS cc, b.code AS bc, e.status, e.enrol_code, e.enrolled_at FROM enrollments e JOIN users u ON u.id=e.student_id "
                  "LEFT JOIN students s ON s.user_id=u.id JOIN batches b ON b.id=e.batch_id JOIN courses c ON c.id=b.course_id ORDER BY e.id")
        table = [[r["student_code"] or "", r["full_name"], r["cc"] or "", r["bc"], r["status"], r["enrol_code"] or "", r["enrolled_at"] or ""] for r in rs]
        return send(ext, "enrolments", ENROL_COLS, table, "export_enrolments", "enrolments")

    for ext in ("csv", "xlsx"):
        app.add_url_rule(f"/api/student-information/export.{ext}", f"pio_students_{ext}", auth("admin", perm="student_information")(lambda ext=ext: student_export(ext)))
        app.add_url_rule(f"/api/student-information/enrolments.{ext}", f"pio_enrol_{ext}", auth("admin", perm="student_information")(lambda ext=ext: enrol_export(ext)))
        app.add_url_rule(f"/api/teacher-information/export.{ext}", f"pio_teachers_{ext}", auth("admin", perm="teacher_information")(lambda ext=ext: teacher_export(ext)))

    # ---------------- imports ----------------
    def unsafe(v):
        """Undo the export's formula protection (csv_safe put an apostrophe in front of a text starting with = + - @), so a round trip keeps the text."""
        return v[1:] if v[:1] == "'" and v[1:2] in ("=", "+", "-", "@") else v

    def read_file():
        """v0.8.38: an Excel workbook (.xlsx, the "Data" sheet of the template) or a CSV file."""
        return excelio.read_table()

    def flag(v, default=1):
        s = str(v or "").strip().lower()
        if not s: return default
        if s in ("1", "yes", "true", "y", "active"): return 1
        if s in ("0", "no", "false", "n", "inactive"): return 0
        raise ValueError("is_active must be 1 or 0")

    def date_of(v, what):
        try: return dt.date.fromisoformat(v).isoformat()
        except ValueError: raise ValueError(f"{what} must be a date like 2012-04-30")

    def free(table, col, val, seen, what):
        if val in seen: raise ValueError(f"{what} {val} appears twice in this file")
        if one(f"SELECT 1 x FROM {table} WHERE {col}=?", (val,)): raise ValueError(f"{what} {val} is already used")
        seen.add(val)

    def check_person(kind, r, seen):
        code_col = "student_code" if kind == "student" else "teacher_code"
        table = "students" if kind == "student" else "teachers"
        name = " ".join((r.get("full_name") or "").split())
        if not name: raise ValueError("full_name is missing")
        if len(name) > 120: raise ValueError("full_name is too long")
        email = (r.get("email") or "").lower()
        if not EMAIL.match(email): raise ValueError("email is missing or not valid")
        if len(r.get("phone") or "") > 30: raise ValueError("phone is too long")
        code, login = (r.get(code_col) or "").upper(), (r.get("login_id") or "").upper()
        for v, what in ((code, code_col), (login, "login_id")):
            if v and not CODE.match(v): raise ValueError(f"{what} {v} is not a valid ID (letters, digits and / . _ - only)")
        free("users", "email", email, seen["email"], "Email")
        if code: free(table, code_col, code, seen["code"], "ID")
        if login or code:
            lid = login or code
            if lid in seen["login"] or one("SELECT 1 x FROM users WHERE login_id=?", (lid,)): raise ValueError(f"Sign-in ID {lid} is already used")
            seen["login"].add(lid)
        d = {"full_name": name, "email": email, "phone": r.get("phone") or None, "code": code or None, "login": login or None, "is_active": flag(r.get("is_active"))}
        if kind == "student":
            d["dob"] = date_of(r["date_of_birth"], "date_of_birth") if r.get("date_of_birth") else None
            for k in ("grade", "island", "guardian_name", "guardian_relationship", "guardian_phone"): d[k] = r.get(k) or None
        else: d["bio"] = r.get("bio") or None
        return d

    def check_enrol(r, seen):
        who = (r.get("student_code") or r.get("login_id") or "").upper()
        if who: u = one("SELECT u.id FROM users u LEFT JOIN students s ON s.user_id=u.id WHERE u.role='student' AND (s.student_code=? OR u.login_id=?)", (who, who))
        elif r.get("student_email"): u = one("SELECT id FROM users WHERE role='student' AND email=?", (r["student_email"].lower(),))
        else: raise ValueError("student_code (or login_id or student_email) is missing")
        if not u: raise ValueError("No student found for " + (who or r["student_email"]))
        if not r.get("course_code") or not r.get("batch_code"): raise ValueError("course_code and batch_code are required")
        b = one("SELECT b.id, b.capacity, c.is_active FROM batches b JOIN courses c ON c.id=b.course_id WHERE UPPER(c.code)=UPPER(?) AND UPPER(b.code)=UPPER(?)", (r["course_code"], r["batch_code"]))
        if not b: raise ValueError(f"No batch {r['batch_code']} in course {r['course_code']}. Create the course and batch first")
        status = (r.get("status") or "active").lower()
        if status not in STATUSES: raise ValueError("status must be one of " + ", ".join(STATUSES))
        who_key = (who or r["student_email"].lower(), r["course_code"].upper(), r["batch_code"].upper())
        if (u["id"], b["id"]) in seen["pair"] or who_key in seen["pair_txt"]: raise ValueError("This student and batch appear twice in this file")
        ex = one("SELECT status FROM enrollments WHERE student_id=? AND batch_id=?", (u["id"], b["id"]))
        if ex: raise ValueError(f"Already enrolled in this batch (status {ex['status']})")
        if status in ("active", "waitlist") and not b["is_active"]: raise ValueError("This course or tuition class is inactive")
        if status == "active":
            n = one("SELECT COUNT(*) n FROM enrollments WHERE batch_id=? AND status='active'", (b["id"],))["n"]
            # v0.8.42: seats taken by earlier rows of this file are added only in a check, where nothing is saved. In a real import those rows
            # are already in the database and were counted twice: a batch could only be filled to half its seats by an import.
            if seen["dry"]: n += seen["filled"].get(b["id"], 0) + seen["filled_txt"].get((r["course_code"].upper(), r["batch_code"].upper()), 0)
            if n >= b["capacity"]: raise ValueError("The batch is full (capacity %d)" % b["capacity"])
        at = (r.get("enrolled_at") or "").strip()
        if at:
            try: at = dt.datetime.fromisoformat(at.replace("T", " ")).strftime("%Y-%m-%d %H:%M:%S")
            except ValueError: raise ValueError("enrolled_at must look like 2026-09-01 or 2026-09-01 10:30:00")
        code = (r.get("enrol_code") or "").upper()
        if code:
            if not CODE.match(code): raise ValueError(f"enrol_code {code} is not a valid ID")
            free("enrollments", "enrol_code", code, seen["code"], "Enrolment ID")
        seen["pair"].add((u["id"], b["id"]))
        if status == "active": seen["filled"][b["id"]] = seen["filled"].get(b["id"], 0) + 1
        return {"student_id": u["id"], "batch_id": b["id"], "status": status, "at": at or None, "code": code or None}

    def apply_person(kind, d):
        pw = secrets.token_urlsafe(9)
        # v0.8.42: TEMP_HASH. The usual hash is slow on purpose (about 0.1 s each), which protects passwords people choose; 100 imported
        # students spent 9 s on it alone and the request ran out of time. This password is 12 random characters (72 bits: guessing it is
        # out of reach whatever the hash) and must be changed at the first sign-in, when the usual slow hash is used.
        uid = db().execute("INSERT INTO users(email,password_hash,full_name,role,phone,must_change_password,is_active,login_id) VALUES(?,?,?,?,?,1,?,?)",
                           (d["email"], generate_password_hash(pw, method=TEMP_HASH), d["full_name"], kind, d["phone"], d["is_active"], d["login"] or d["code"])).lastrowid
        if kind == "student":
            db().execute("INSERT INTO students(user_id,date_of_birth,grade,island,guardian_name,guardian_relationship,guardian_phone,student_code) VALUES(?,?,?,?,?,?,?,?)",
                         (uid, d["dob"], d["grade"], d["island"], d["guardian_name"], d["guardian_relationship"], d["guardian_phone"], d["code"]))
        else: db().execute("INSERT INTO teachers(user_id,bio,teacher_code) VALUES(?,?,?)", (uid, d["bio"], d["code"]))
        lid = idcodes.give_login_id(db(), uid)
        audit("create_user", "user", uid, f"{kind} {lid} (imported)")
        return uid, lid, pw

    def apply_enrol(d):
        at = d["at"] or one("SELECT datetime('now') n")["n"]
        eid = db().execute("INSERT INTO enrollments(student_id,batch_id,status,enrolled_at,enrol_code) VALUES(?,?,?,?,?)", (d["student_id"], d["batch_id"], d["status"], at, d["code"])).lastrowid
        idcodes.fill_missing(db(), unenrolled_students=False)
        idcodes.give_login_id(db(), d["student_id"])
        audit("enroll", "enrollment", eid, "imported " + d["status"], batch_id=d["batch_id"], new=d["status"])
        return eid, one("SELECT enrol_code FROM enrollments WHERE id=?", (eid,))["enrol_code"]

    def seen_before(kind, earlier, seen):
        """v0.8.42, a check sent in parts: what the rows before this part hold, so "appears twice in this file" is still found across parts.
        (In a real import the earlier parts are already saved, and the database says "already used".)"""
        for _n, r in earlier:
            if kind == "enrolment":
                who = (r.get("student_code") or r.get("login_id") or "").upper() or (r.get("student_email") or "").lower()
                cc, bc = (r.get("course_code") or "").upper(), (r.get("batch_code") or "").upper()
                if not (who and cc and bc): continue
                seen["pair_txt"].add((who, cc, bc))
                if (r.get("status") or "active").lower() == "active": seen["filled_txt"][(cc, bc)] = seen["filled_txt"].get((cc, bc), 0) + 1
                continue
            code_col = "student_code" if kind == "student" else "teacher_code"
            email, code, login = (r.get("email") or "").lower(), (r.get(code_col) or "").upper(), (r.get("login_id") or "").upper()
            if email: seen["email"].add(email)
            if code: seen["code"].add(code)
            if login or code: seen["login"].add(login or code)

    def run(kind):
        try:
            head, body = read_file()
            earlier, body, part = excelio.window(body)
        except ValueError as x: return err(str(x))
        need = {"student": ["full_name", "email"], "teacher": ["full_name", "email"], "enrolment": ["course_code", "batch_code"]}[kind]
        miss = [h for h in need if h not in head]
        if miss: return err("The file has no column: " + ", ".join(miss))
        dry = (request.args.get("dry_run", "1").lower() not in ("0", "false", "no"))
        seen = {"email": set(), "code": set(), "login": set(), "pair": set(), "filled": {}, "pair_txt": set(), "filled_txt": {}, "dry": dry}
        if dry: seen_before(kind, earlier, seen)
        out, ok, bad = [], 0, 0
        for n, r in body:
            item = {"row": n, "name": r.get("full_name") or r.get("student_code") or r.get("student_email") or ""}
            try:
                d = check_enrol(r, seen) if kind == "enrolment" else check_person(kind, r, seen)
                if not dry:
                    try:
                        if kind == "enrolment": eid, code = apply_enrol(d); item["enrol_code"] = code
                        else:
                            uid, lid, pw = apply_person(kind, d); item.update(id=uid, login_id=lid, temporary_password=pw)
                            item["student_code" if kind == "student" else "teacher_code"] = d["code"]
                        db().commit()
                    except Exception:
                        db().rollback(); raise ValueError("Could not be saved (it may clash with another record). Nothing was changed for this row")
                item["status"] = "would_create" if dry else "created"; ok += 1
            except ValueError as x:
                item["status"] = "rejected"; item["message"] = str(x); bad += 1
            out.append(item)
        if not dry:
            audit("import_" + kind + "s", "import", None, f"{ok} created, {bad} rejected of {len(body)}", new=ok); db().commit()
        return excelio.import_response(kind, dry, len(body), ok, bad, out, part)

    # ---------------- v0.8.38: templates ----------------
    def template_for(kind):
        C = lambda key, help, example="", required=False, **kw: {"key": key, "help": help, "example": example, "required": required, **kw}
        yn = ["1", "0"]
        if kind == "students":
            cols = [C("full_name", "The student's full name.", "Aishath Ali", True, width=26), C("email", "Email address; must not be used by another account.", "aishath@example.com", True, width=28),
                    C("student_code", "Leave empty and the portal gives one. Or your own ID (letters, digits, / . _ -).", "BAL/AX/120", text=True),
                    C("login_id", "What they type to sign in. Empty = the same as the student ID.", "", text=True), C("phone", "WhatsApp number.", "7771234", text=True),
                    C("date_of_birth", "Date like 2012-04-30.", "2012-04-30"), C("grade", "School grade or class.", "Grade 7"), C("island", "Island or city.", "Male'"),
                    C("guardian_name", "For students under 18.", "Ali Ahmed"), C("guardian_relationship", "Father, mother, ...", "Father"), C("guardian_phone", "Guardian's number.", "7775678", text=True),
                    C("is_active", "1 = can sign in (default), 0 = not yet.", "1", choices=yn)]
            return excelio.template("Import students", cols, note="Each new account gets a temporary password, shown once after the import. Enrol them with the Enrolments template.")
        if kind == "teachers":
            cols = [C("full_name", "The teacher's full name.", "Ahmed Rasheed", True, width=26), C("email", "Email address; must not be used by another account.", "ahmed@example.com", True, width=28),
                    C("teacher_code", "Leave empty and the portal gives one.", "", text=True), C("login_id", "What they type to sign in. Empty = the same as the teacher ID.", "", text=True),
                    C("phone", "WhatsApp number.", "7779876", text=True), C("bio", "A short line about the teacher.", "Quran and Arabic teacher"), C("is_active", "1 = can sign in (default), 0 = not yet.", "1", choices=yn)]
            return excelio.template("Import teachers", cols)
        bs = rows("SELECT c.code AS cc, b.code AS bc, c.name AS cn FROM batches b JOIN courses c ON c.id=b.course_id WHERE c.is_active=1 AND b.status<>'closed' ORDER BY c.code, b.code")
        cols = [C("student_code", "The student's ID (see Student information), or fill login_id or student_email instead.", "BAL/AX/120", text=True),
                C("login_id", "Instead of student_code.", "", text=True), C("student_email", "Instead of student_code.", ""),
                C("course_code", "The course code (see the Lists sheet).", bs[0]["cc"] if bs else "AL1", True, list_ref="Course codes", text=True),
                C("batch_code", "The batch name/code in that course (see the Lists sheet).", bs[0]["bc"] if bs else "004", True, list_ref="Batch codes", text=True, free=True),
                C("status", "active (default), waitlist, dropped or completed.", "active", choices=list(STATUSES)),
                C("enrol_code", "Leave empty and the portal gives one.", "", text=True), C("enrolled_at", "Date like 2026-09-01. Empty = today.", "2026-09-01")]
        return excelio.template("Import enrolments", cols, lists={"Course codes": sorted({b["cc"] for b in bs if b["cc"]}), "Batch codes": [b["bc"] for b in bs],
                                                                  "Batch is in course": [f"{b['cc']} · {b['cn']}" for b in bs]},
                                note="Courses and batches are not created by this import: they must already exist. The Lists sheet shows each batch next to its course.")

    def template_route(kind):
        audit("download_template", "import", None, kind); db().commit()
        return excelio.send_xlsx(template_for(kind), f"import-{kind}-template")

    app.add_url_rule("/api/import/students/template.xlsx", "pio_tpl_students", auth("admin", perm="people")(lambda: template_route("students")))
    app.add_url_rule("/api/import/teachers/template.xlsx", "pio_tpl_teachers", auth("admin", perm="people")(lambda: template_route("teachers")))
    app.add_url_rule("/api/import/enrolments/template.xlsx", "pio_tpl_enrolments", auth("admin", perm="enrollments")(lambda: template_route("enrolments")))

    app.add_url_rule("/api/import/students", "pio_imp_students", auth("admin", perm="people")(lambda: run("student")), methods=["POST"])
    app.add_url_rule("/api/import/teachers", "pio_imp_teachers", auth("admin", perm="people")(lambda: run("teacher")), methods=["POST"])
    app.add_url_rule("/api/import/enrolments", "pio_imp_enrolments", auth("admin", perm="enrollments")(lambda: run("enrolment")), methods=["POST"])
