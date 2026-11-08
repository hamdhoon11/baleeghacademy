"""Session 27: exports and imports of people and enrolments.

Exports (CSV or Excel, every download is logged; no fees, no internal notes, no passwords or hashes):
  GET /api/student-information/export.csv|.xlsx      area student_information  ?q=&batch_id=&status=active|inactive
  GET /api/student-information/enrolments.csv|.xlsx  area student_information  one row per enrolment (the file the enrolment import reads)
  GET /api/teacher-information/export.csv|.xlsx      area teacher_information  ?q=&status=active|inactive

Imports (CSV only, UTF-8; multipart field "file" or a text/csv body; at most 2000 rows and 2 MB):
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

import idcodes
from payreports import to_xlsx, csv_safe, XLSX_MIME

CODE = re.compile(r"^[A-Z0-9][A-Z0-9/._-]{2,39}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_ROWS, MAX_BYTES = 2000, 2 * 1024 * 1024
STUDENT_COLS = ["student_code", "login_id", "full_name", "email", "phone", "date_of_birth", "grade", "island", "guardian_name", "guardian_relationship", "guardian_phone", "is_active"]
TEACHER_COLS = ["teacher_code", "login_id", "full_name", "email", "phone", "bio", "is_active"]
ENROL_COLS = ["student_code", "student_name", "course_code", "batch_code", "status", "enrol_code", "enrolled_at"]
STATUSES = ("active", "waitlist", "dropped", "completed")


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
        f = request.files.get("file")
        raw = f.read(MAX_BYTES + 1) if f else (request.get_data() or b"")
        if not raw.strip(): raise ValueError("No file received. Choose a CSV file.")
        if len(raw) > MAX_BYTES: raise ValueError("The file is larger than 2 MB. Split it into smaller files.")
        try: text = raw.decode("utf-8-sig")
        except UnicodeDecodeError: raise ValueError("The file must be saved as CSV (UTF-8).")
        rd = csv.reader(io.StringIO(text))
        try: head = [re.sub(r"\s+", "_", h.strip().lower()) for h in next(rd)]
        except StopIteration: raise ValueError("The file is empty.")
        body = []
        for n, r in enumerate(rd, 2):
            if not any(x.strip() for x in r): continue
            body.append((n, {head[i]: unsafe(r[i].strip()) for i in range(min(len(head), len(r)))}))
        if len(body) > MAX_ROWS: raise ValueError(f"More than {MAX_ROWS} rows. Split the file.")
        return head, body

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
        if (u["id"], b["id"]) in seen["pair"]: raise ValueError("This student and batch appear twice in this file")
        ex = one("SELECT status FROM enrollments WHERE student_id=? AND batch_id=?", (u["id"], b["id"]))
        if ex: raise ValueError(f"Already enrolled in this batch (status {ex['status']})")
        if status in ("active", "waitlist") and not b["is_active"]: raise ValueError("This course or tuition class is inactive")
        if status == "active":
            n = one("SELECT COUNT(*) n FROM enrollments WHERE batch_id=? AND status='active'", (b["id"],))["n"] + seen["filled"].get(b["id"], 0)
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
        uid = db().execute("INSERT INTO users(email,password_hash,full_name,role,phone,must_change_password,is_active,login_id) VALUES(?,?,?,?,?,1,?,?)",
                           (d["email"], generate_password_hash(pw), d["full_name"], kind, d["phone"], d["is_active"], d["login"] or d["code"])).lastrowid
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

    def run(kind):
        try: head, body = read_file()
        except ValueError as x: return err(str(x))
        need = {"student": ["full_name", "email"], "teacher": ["full_name", "email"], "enrolment": ["course_code", "batch_code"]}[kind]
        miss = [h for h in need if h not in head]
        if miss: return err("The file has no column: " + ", ".join(miss))
        dry = (request.args.get("dry_run", "1").lower() not in ("0", "false", "no"))
        seen = {"email": set(), "code": set(), "login": set(), "pair": set(), "filled": {}}
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
        resp = jsonify(kind=kind, dry_run=dry, total=len(body), ok=ok, rejected=bad, rows=out)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    app.add_url_rule("/api/import/students", "pio_imp_students", auth("admin", perm="people")(lambda: run("student")), methods=["POST"])
    app.add_url_rule("/api/import/teachers", "pio_imp_teachers", auth("admin", perm="people")(lambda: run("teacher")), methods=["POST"])
    app.add_url_rule("/api/import/enrolments", "pio_imp_enrolments", auth("admin", perm="enrollments")(lambda: run("enrolment")), methods=["POST"])
