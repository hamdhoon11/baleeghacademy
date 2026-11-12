"""v0.8.38: Excel exports and imports for the parts that had none.

Exports (.xlsx, and .csv where a CSV makes sense). Each list export reads the SAME route the screen uses, with the same filters and the
same permission check, so the file always matches what the screen shows. Every download is in the activity log.
  GET /api/invoices/export.xlsx|csv            Fees area       ?month=&status=&q= (as Fees > Invoices)
  GET /api/expenses/export.xlsx|csv            Finance area    ?category_id=&date_from=&date_to=&q= (as Finance > Expenses)
  GET /api/applications/export.xlsx|csv        Admissions      ?status= (no ID copies, only whether one was sent)
  GET /api/courses/export.xlsx|csv             Courses         the same columns as the course import
  GET /api/batches/export.xlsx|csv             Batches         the same columns as the batch import
  GET /api/batches/<id>/gradebook.xlsx         Classroom       one row per student, one column per assignment or test, average, attendance
  GET /api/batches/<id>/attendance.xlsx        Classroom       ?month=YYYY-MM: register, one row per student, one column per class date

Imports (Excel .xlsx or CSV; ?dry_run=1 is the default and saves nothing). Each row goes through the route the screen uses, so it gets
the same checks and the same activity-log line as typing it in. A rejected row never blocks the others.
  POST /api/import/courses                     Courses         template: GET /api/import/courses/template.xlsx
  POST /api/import/batches                     Batches         template: GET /api/import/batches/template.xlsx
  POST /api/import/expenses                    Finance         template: GET /api/import/expenses/template.xlsx
  POST /api/import/grades?assignment_id=       Classroom       template: GET /api/import/grades/template.xlsx?assignment_id= (the class list, filled in)
"""
import datetime as dt, re
from flask import g, jsonify, request
import excelio as X

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def register(app, c, today):
    db, rows, one, err, auth, audit = c.db, c.rows, c.one, c.err, c.auth, c.audit

    def logged(action, detail):
        audit(action, "report", None, detail); db().commit()

    def via(path, keep=()):
        """GET a list route with the caller's own filters; returns (rows, error response)."""
        q = {k: v for k, v in request.args.items() if k in keep}
        code, body = X.call("GET", path, query=q)
        if code != 200: return None, err((body or {}).get("error") or "Could not read the list", code)
        return body, None

    # ---------------- exports ----------------
    def ext_rule(path, endpoint, fn, roles=("admin",), perm=None):
        for ext in ("xlsx", "csv"):
            app.add_url_rule(path.format(ext=ext), f"{endpoint}_{ext}", auth(*roles, perm=perm)(lambda ext=ext, **kw: fn(ext, **kw)))

    def invoices_export(ext):
        code, body = X.call("GET", "/api/invoices", query={**{k: v for k, v in request.args.items() if k in ("month", "status", "q", "student_id")}, "limit": "5000"})
        if code != 200: return err(body.get("error") or "Could not read the invoices", code)
        head = ["invoice", "period", "kind", "student", "course", "batch", "due_date", "amount_due_mvr", "waived_mvr", "paid_mvr", "balance_mvr", "status", "overdue", "days_overdue", "status_reason"]
        table = [[i["number"], i["period"], i.get("kind") or "monthly", i["student_name"], i["course_name"], i["batch_code"], i["due_date"], i["amount_due_mvr"], i["waived_mvr"],
                  i["paid_mvr"], i["balance"], i["status"], "yes" if i["overdue"] else "no", i["days_overdue"], i.get("status_reason") or ""] for i in body]
        logged(f"export_invoices_{ext}", f"{len(table)} rows; {dict(request.args)}")
        return X.send_table(ext, "invoices", head, table, "Invoices")
    ext_rule("/api/invoices/export.{ext}", "sh_invoices", invoices_export, perm="fees")

    def expenses_export(ext):
        items, page = [], 1
        while True:
            code, body = X.call("GET", "/api/expenses", query={**{k: v for k, v in request.args.items() if k in ("category_id", "date_from", "date_to", "q")}, "page": str(page), "per_page": "200"})
            if code != 200: return err(body.get("error") or "Could not read the expenses", code)
            items += body["items"]
            if page * 200 >= body["count"] or page >= 50: break
            page += 1
        head = ["expense_date", "category", "description", "amount_mvr", "receipt", "monthly", "entered_by", "entered_at"]
        table = [[x["expense_date"], x["category"], x["description"] or "", x["amount_mvr"], "yes" if x["has_receipt"] else "", "yes" if x.get("recurring_id") else "",
                  x.get("entered_by_name") or "", x["created_at"]] for x in items]
        table.append(["", "Total", "", sum(x["amount_mvr"] for x in items), "", "", "", ""])
        logged(f"export_expenses_{ext}", f"{len(items)} rows; {dict(request.args)}")
        return X.send_table(ext, "expenses", head, table, "Expenses")
    ext_rule("/api/expenses/export.{ext}", "sh_expenses", expenses_export, perm="finance")

    def applications_export(ext):
        body, e = via("/api/applications", ("status",))
        if e: return e
        head = ["ref", "status", "full_name", "date_of_birth", "under_18", "phone", "email", "island", "grade", "course", "batch", "guardian_name", "guardian_relationship",
                "guardian_phone", "id_copy_sent", "reject_reason", "applied_at", "decided_at"]
        table = [[a["ref"], a["status"], a["full_name"], a["date_of_birth"], "yes" if a["is_minor"] else "", a["phone"], a["email"], a["island"] or "", a["grade"] or "", a["course_name"],
                  a["batch_code"] or "", a["guardian_name"] or "", a["guardian_relationship"] or "", a["guardian_phone"] or "", "yes" if a["has_id"] else "", a["reject_reason"] or "",
                  a["created_at"], a["decided_at"] or ""] for a in body]
        logged(f"export_applications_{ext}", f"{len(table)} rows; {dict(request.args)}")
        return X.send_table(ext, "applications", head, table, "Applications", text_cols=("phone", "guardian_phone"))
    ext_rule("/api/applications/export.{ext}", "sh_applications", applications_export, perm="admissions")

    COURSE_COLS = ["code", "name", "kind", "level", "monthly_fee_mvr", "registration_fee_mvr", "days_per_week", "minutes_per_class", "status", "is_active", "textbook", "description"]
    BATCH_COLS = ["course_code", "code", "teacher", "days", "start_time", "start_date", "capacity", "status", "meet_link"]

    def courses_export(ext):
        cs = rows("SELECT * FROM courses ORDER BY id")
        table = [[x["code"] or "", x["name"], x["kind"], x["level"] or "", x["monthly_fee_mvr"], x["registration_fee_mvr"], x["days_per_week"] or "", x["minutes_per_class"] or "",
                  x["status"], 1 if x["is_active"] else 0, x["textbook"] or "", x["description"] or ""] for x in cs]
        logged(f"export_courses_{ext}", f"{len(table)} rows")
        return X.send_table(ext, "courses", COURSE_COLS, table, "Courses", text_cols=("code",))
    ext_rule("/api/courses/export.{ext}", "sh_courses", courses_export, perm="courses")

    def batches_export(ext):
        bs = rows("SELECT b.*, c.code AS course_code, t.teacher_code, u.login_id, u.full_name AS teacher_name, (SELECT COUNT(*) FROM enrollments e WHERE e.batch_id=b.id AND e.status='active') AS enrolled "
                  "FROM batches b JOIN courses c ON c.id=b.course_id LEFT JOIN users u ON u.id=b.teacher_id LEFT JOIN teachers t ON t.user_id=b.teacher_id ORDER BY c.code, b.code")
        table = [[x["course_code"] or "", x["code"], x["teacher_code"] or x["login_id"] or "", x["days"] or "", x["start_time"] or "", x["start_date"] or "", x["capacity"], x["status"],
                  x["meet_link"] or "", x["teacher_name"] or "", x["enrolled"]] for x in bs]
        logged(f"export_batches_{ext}", f"{len(table)} rows")
        return X.send_table(ext, "batches", BATCH_COLS + ["teacher_name", "students_enrolled"], table, "Batches", text_cols=("course_code", "code", "teacher"))
    ext_rule("/api/batches/export.{ext}", "sh_batches", batches_export, perm="batches")

    def batch_name(bid):
        b = one("SELECT b.code, c.name FROM batches b JOIN courses c ON c.id=b.course_id WHERE b.id=?", (bid,))
        return re.sub(r"[^A-Za-z0-9_-]+", "-", f"{b['name']}-{b['code']}").strip("-").lower() if b else str(bid)

    @app.get("/api/batches/<int:bid>/gradebook.xlsx")
    @auth("admin", "teacher", perm="classroom")
    def sh_gradebook(bid):
        code, gb = X.call("GET", f"/api/batches/{bid}/gradebook")   # the same access rule as the Gradebook screen
        if code != 200: return err(gb.get("error") or "Not allowed", code)
        items = rows("SELECT id,title,kind,max_points,due_date FROM assignments WHERE batch_id=? ORDER BY COALESCE(due_date,'9999-12-31'), id", (bid,))
        marks = {(r["assignment_id"], r["student_id"]): r["grade"] for r in rows(
            "SELECT s.assignment_id, s.student_id, s.grade FROM submissions s JOIN assignments a ON a.id=s.assignment_id WHERE a.batch_id=? AND s.grade IS NOT NULL", (bid,))}
        codes = {r["user_id"]: r["student_code"] for r in rows("SELECT user_id, student_code FROM students")}
        head = ["student_code", "student"] + [f"{a['title']} (/{a['max_points']})" for a in items] + ["average_%", "attendance_%"]
        table = [[codes.get(s["student_id"]) or "", s["full_name"]] + [marks.get((a["id"], s["student_id"]), "") for a in items] + [s["avg_pct"] if s["avg_pct"] is not None else "",
                                                                                                                                       s["attendance_pct"] if s["attendance_pct"] is not None else ""] for s in gb]
        logged("export_gradebook_xlsx", f"batch {bid}: {len(table)} students, {len(items)} items")
        return X.send_table("xlsx", f"gradebook-{batch_name(bid)}", head, table, "Gradebook", text_cols=("student_code",))

    @app.get("/api/batches/<int:bid>/attendance.xlsx")
    @auth("admin", "teacher", perm="classroom")
    def sh_attendance(bid):
        code, sm = X.call("GET", f"/api/batches/{bid}/attendance/summary")
        if code != 200: return err(sm.get("error") or "Not allowed", code)
        month = request.args.get("month") or today().isoformat()[:7]
        if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", month): return err("Month must look like 2026-03")
        ses = rows("SELECT id, session_date, start_time FROM sessions WHERE batch_id=? AND session_date LIKE ? AND status='held' ORDER BY session_date, start_time", (bid, month + "-%"))
        mk = {(r["session_id"], r["student_id"]): r["status"] for r in rows(
            f"SELECT session_id, student_id, status FROM attendance WHERE session_id IN ({','.join('?' * len(ses)) or 'NULL'})", [s["id"] for s in ses])}
        short = {"present": "P", "absent": "A", "late": "L", "excused": "E"}
        codes = {r["user_id"]: r["student_code"] for r in rows("SELECT user_id, student_code FROM students")}
        head = ["student_code", "student"] + [s["session_date"][5:] + (f" {s['start_time']}" if sum(1 for x in ses if x["session_date"] == s["session_date"]) > 1 else "") for s in ses] + ["present", "late", "absent", "excused"]
        table = []
        for st in sm["students"]:
            cells = [short.get(mk.get((s["id"], st["id"])), "") for s in ses]
            table.append([codes.get(st["id"]) or "", st["full_name"]] + cells + [cells.count("P"), cells.count("L"), cells.count("A"), cells.count("E")])
        table.append([]); table.append(["", "P present · L late · A absent · E excused"])
        logged("export_attendance_xlsx", f"batch {bid} {month}: {len(sm['students'])} students, {len(ses)} classes")
        return X.send_table("xlsx", f"attendance-{batch_name(bid)}-{month}", head, table, f"Attendance {month}", text_cols=("student_code",))

    # ---------------- imports through the screen's own routes ----------------
    C = lambda key, help, example="", required=False, **kw: {"key": key, "help": help, "example": example, "required": required, **kw}

    def run(kind, need, row_fn, area_note=""):
        """row_fn(row) -> (method, path, json) or raises ValueError; or returns ("skip", reason)."""
        try: head, body = X.read_table()
        except ValueError as x: return err(str(x))
        miss = [h for h in need if h not in head]
        if miss: return err("The file has no column: " + ", ".join(miss) + ". Use the template.")
        dry = X.want_dry()
        out, ok, bad = [], 0, 0
        conn = db()
        scope = X.dry_run_scope(conn) if dry else _null()
        with scope:
            for n, r in body:
                item = {"row": n, "name": r.get("name") or r.get("code") or r.get("student") or r.get("student_code") or r.get("description") or r.get("category") or ""}
                try:
                    with X.row_savepoint(conn, dry):
                        call = row_fn(r)
                        if call[0] == "skip":
                            item.update(status="skipped", message=call[1]); out.append(item); continue
                        code, res = X.call(*call)
                        if code >= 400: raise ValueError(res.get("error") or res.get("message") or f"Refused ({code})")
                        if res.get("changed") is False: item.update(status="unchanged"); out.append(item); continue
                        item["status"] = "would_create" if dry else "created"; ok += 1
                        for k in ("id", "code"):
                            if k in res: item[k] = res[k]
                except ValueError as x:
                    item.update(status="rejected", message=str(x)); bad += 1
                except Exception:
                    if not dry: db().rollback()
                    item.update(status="rejected", message="Could not be saved. Nothing was changed for this row"); bad += 1
                out.append(item)
        if not dry:
            audit(f"import_{kind}", "import", None, f"{ok} saved, {bad} rejected of {len(body)}", new=ok); db().commit()
        return X.import_response(kind, dry, len(body), ok, bad, out)

    class _null:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def num(v, what, empty=None):
        v = (v or "").strip()
        if v == "": return empty
        try: return int(float(v)) if float(v).is_integer() else float(v)
        except ValueError: raise ValueError(f"{what} must be a number")

    # courses
    def course_row(r):
        if not (r.get("name") or "").strip(): raise ValueError("name is missing")
        d = {"name": r["name"], "kind": (r.get("kind") or "course").lower(), "level": r.get("level") or None, "textbook": r.get("textbook") or None,
             "description": r.get("description") or None, "status": (r.get("status") or "open").lower(),
             "monthly_fee_mvr": num(r.get("monthly_fee_mvr"), "monthly_fee_mvr", 0), "registration_fee_mvr": num(r.get("registration_fee_mvr"), "registration_fee_mvr", 0),
             "days_per_week": num(r.get("days_per_week"), "days_per_week"), "minutes_per_class": num(r.get("minutes_per_class"), "minutes_per_class")}
        if r.get("code"): d["code"] = r["code"]
        if r.get("is_active", "") != "": d["is_active"] = r["is_active"] in ("1", "yes", "true", "active")
        return ("POST", "/api/courses", d)

    def course_template():
        return X.template("Import courses and tuition classes", [
            C("code", "Short code, 2 to 8 letters or digits. Empty = the portal makes one.", "AL1", text=True),
            C("name", "Course or tuition class name.", "Arabic Language", True, width=26), C("kind", "course or tuition.", "course", choices=["course", "tuition"]),
            C("level", "Level, if any.", "Level 1"), C("monthly_fee_mvr", "Whole MVR. 0 means students are not invoiced.", "350"),
            C("registration_fee_mvr", "One-time fee in whole MVR; 0 or empty for none.", "100"), C("days_per_week", "Classes per week.", "2"),
            C("minutes_per_class", "Length of one class in minutes.", "60"), C("status", "open (default), upcoming or closed.", "open", choices=["open", "upcoming", "closed"]),
            C("is_active", "1 = offered (default), 0 = not offered.", "1", choices=["1", "0"]), C("textbook", "Book used.", ""), C("description", "A short description.", "", width=40)],
            note="Courses that already exist (same code) are refused, not changed. Then add batches with the Batches template.")

    # batches
    def teacher_id(v):
        v = (v or "").strip()
        if not v: return None
        t = one("SELECT u.id FROM users u LEFT JOIN teachers t ON t.user_id=u.id WHERE u.role='teacher' AND (UPPER(t.teacher_code)=UPPER(?) OR UPPER(u.login_id)=UPPER(?) OR LOWER(u.email)=LOWER(?))", (v, v, v))
        if not t: raise ValueError(f"No teacher {v} (use the teacher ID, sign-in ID or email)")
        return t["id"]

    def batch_row(r):
        cc, code = (r.get("course_code") or "").strip(), (r.get("code") or "").strip()
        if not cc or not code: raise ValueError("course_code and code are required")
        co = one("SELECT id FROM courses WHERE UPPER(code)=UPPER(?)", (cc,))
        if not co: raise ValueError(f"No course with code {cc}. Import or add the course first")
        d = {"course_id": co["id"], "code": code, "days": r.get("days") or None, "start_time": r.get("start_time") or None, "start_date": r.get("start_date") or None,
             "teacher_id": teacher_id(r.get("teacher")), "status": (r.get("status") or "open").lower(), "meet_link": r.get("meet_link") or None}
        if d["start_time"] and re.match(r"^\d:\d\d$", d["start_time"]): d["start_time"] = "0" + d["start_time"]
        if r.get("capacity"): d["capacity"] = num(r["capacity"], "capacity")
        return ("POST", "/api/batches", d)

    def batch_template():
        cs = rows("SELECT code, name FROM courses WHERE is_active=1 AND code IS NOT NULL ORDER BY code")
        ts = rows("SELECT COALESCE(t.teacher_code, u.login_id, u.email) AS k, u.full_name FROM users u LEFT JOIN teachers t ON t.user_id=u.id WHERE u.role='teacher' AND u.is_active=1 ORDER BY u.full_name")
        return X.template("Import batches", [
            C("course_code", "The course's code (see the Lists sheet).", cs[0]["code"] if cs else "AL1", True, list_ref="Course codes", text=True),
            C("code", "Batch name or code, unique within the course.", "005", True, text=True), C("teacher", "Teacher ID, sign-in ID or email (see the Lists sheet).", "", list_ref="Teachers", text=True, free=True),
            C("days", "Class days, comma separated.", "Sun,Tue,Thu"), C("start_time", "24-hour time.", "16:00", text=True), C("start_date", "First class date.", "2026-12-01"),
            C("capacity", "Seats. Empty = the default from Settings.", "15"), C("status", "open (default), running or closed.", "open", choices=["open", "running", "closed"]),
            C("meet_link", "Class link starting with https://", "", width=34)],
            lists={"Course codes": [x["code"] for x in cs], "Course names": [x["name"] for x in cs], "Teachers": [x["k"] for x in ts], "Teacher names": [x["full_name"] for x in ts]},
            note="The course must already exist. Days use Mon Tue Wed Thu Fri Sat Sun.")

    # expenses
    def expense_row(r):
        cat = (r.get("category") or "").strip()
        k = one("SELECT id, is_active FROM expense_categories WHERE LOWER(name)=LOWER(?)", (cat,)) if cat else None
        if not cat: raise ValueError("category is missing")
        if not k: raise ValueError(f"No category called {cat}. Add it in Finance > Categories first")
        return ("POST", "/api/expenses", {"expense_date": r.get("expense_date") or "", "amount_mvr": r.get("amount_mvr") or "", "category_id": k["id"], "description": r.get("description") or ""})

    def expense_template():
        cats = [x["name"] for x in rows("SELECT name FROM expense_categories WHERE is_active=1 ORDER BY name")]
        return X.template("Import expenses", [
            C("expense_date", "Date paid, like 2026-11-05 (not in the future).", "2026-11-05", True), C("amount_mvr", "Whole MVR.", "1500", True),
            C("category", "One of your categories (see the Lists sheet).", cats[0] if cats else "Rent", True, list_ref="Categories", width=22), C("description", "What it was for.", "Electricity October", width=40)],
            lists={"Categories": cats}, note="Receipts cannot be imported; attach them to an expense afterwards with Edit.")

    # grades for one assignment
    def assignment_of():
        aid = request.args.get("assignment_id", type=int)
        if not aid: raise ValueError("Choose the assignment or test first")
        code, body = X.call("GET", f"/api/assignments/{aid}/submissions")   # the Grades screen's own access rule
        if code != 200: raise PermissionError(body.get("error") or "Not allowed", code)
        return aid, body

    def grades_run():
        try: aid, info = assignment_of()
        except ValueError as x: return err(str(x))
        except PermissionError as x: return err(x.args[0], x.args[1])
        ids = {s["student_id"] for s in info["students"]}
        codes = {r["student_code"].upper(): r["user_id"] for r in rows("SELECT user_id, student_code FROM students WHERE student_code IS NOT NULL")}
        names = {}
        for s in info["students"]: names.setdefault(s["full_name"].strip().lower(), []).append(s["student_id"])

        def grade_row(r):
            k = (r.get("student_code") or "").strip().upper()
            sid = codes.get(k) if k else None
            if not sid and not k and r.get("student"):
                hit = names.get(r["student"].strip().lower(), [])
                if len(hit) == 1: sid = hit[0]
            if not sid: raise ValueError(f"No student {k or r.get('student') or ''} in this batch")
            if sid not in ids: raise ValueError(f"{k} is not in this batch")
            if (r.get("grade") or "").strip() == "": return ("skip", "no grade written")
            return ("POST", f"/api/assignments/{aid}/grades", {"student_id": sid, "grade": r["grade"], "feedback": r.get("feedback") or ""})
        return run("grades", ["grade"], grade_row)

    def grades_template():
        aid, info = assignment_of()
        a = info["assignment"]
        codes = {r["user_id"]: r["student_code"] for r in rows("SELECT user_id, student_code FROM students")}
        roster = [[codes.get(s["student_id"]) or "", s["full_name"], "" if s["grade"] is None else s["grade"], s["feedback"] or ""] for s in info["students"]]
        body = X.template(f"Grades: {a['title']} (out of {a['max_points']})", [
            C("student_code", "Filled in for you. Do not change it.", "", True, text=True), C("student", "Filled in for you.", "", width=28),
            C("grade", f"A number from 0 to {a['max_points']}. Leave empty to skip the student.", str(a["max_points"])), C("feedback", "A short comment (optional).", "Well done", width=40)],
            rows=roster, note="Grades already saved show in the grade column. Changing a saved grade needs the 'Change saved grades' permission, as on the screen.")
        return aid, body, a["title"]

    TEMPLATES = {"courses": ("courses", course_template), "batches": ("batches", batch_template), "expenses": ("finance", expense_template)}
    RUNS = {"courses": ("courses", ["name"], course_row), "batches": ("batches", ["course_code", "code"], batch_row), "expenses": ("finance", ["expense_date", "amount_mvr", "category"], expense_row)}
    for kind, (area, need, fn) in RUNS.items():
        app.add_url_rule(f"/api/import/{kind}", f"sh_imp_{kind}", auth("admin", perm=area)(lambda kind=kind, need=need, fn=fn: run(kind, need, fn)), methods=["POST"])
    for kind, (area, fn) in TEMPLATES.items():
        def tpl(kind=kind, fn=fn):
            audit("download_template", "import", None, kind); db().commit()
            return X.send_xlsx(fn(), f"import-{kind}-template")
        app.add_url_rule(f"/api/import/{kind}/template.xlsx", f"sh_tpl_{kind}", auth("admin", perm=area)(tpl))

    @app.post("/api/import/grades")
    @auth("admin", "teacher", perm="classroom")
    def sh_imp_grades():
        return grades_run()

    @app.get("/api/import/grades/template.xlsx")
    @auth("admin", "teacher", perm="classroom")
    def sh_tpl_grades():
        try: aid, body, title = grades_template()
        except ValueError as x: return err(str(x))
        except PermissionError as x: return err(x.args[0], x.args[1])
        audit("download_template", "import", None, f"grades for assignment {aid}"); db().commit()
        return X.send_xlsx(body, "grades-" + (re.sub(r"[^A-Za-z0-9_-]+", "-", title).strip("-").lower() or str(aid)))
