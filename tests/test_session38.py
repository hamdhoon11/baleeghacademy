"""v0.8.38: Excel imports (with templates) and exports.
Templates open in Excel and carry the right columns, drop-downs and lists; imports read .xlsx and .csv; a check (dry run) saves nothing,
also through the screen routes; an import gives the same result and the same log lines as typing it in; exports match the screen lists."""
import datetime as dt, io, os, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from openpyxl import Workbook, load_workbook

MVT = dt.timezone(dt.timedelta(hours=5))
PW = "Password123"


def xlsx(head, rows, sheet="Data", extra_sheets=()):
    wb = Workbook(); ws = wb.active; ws.title = sheet
    for name in extra_sheets: wb.create_sheet(name, 0)
    ws.append(head)
    for r in rows: ws.append(r)
    b = io.BytesIO(); wb.save(b); return b.getvalue()


class Excel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        old = os.environ.get("SEED_DEMO")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s38.test", ADMIN_PASSWORD="AdminPass123", SEED_DEMO="0")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path}); cls.c = cls.app.test_client()
        cls.app.config["NOW"] = lambda: dt.datetime(2027, 3, 10, 17, 0, tzinfo=MVT)
        cls.sql_("UPDATE users SET must_change_password=0")
        cls.H = cls.tok("admin@s38.test", "AdminPass123")
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, role, **kw: P("/api/users", {"email": e, "password": PW, "full_name": e.split("@")[0], "role": role, **kw}).get_json()["id"]
        cls.t1, cls.t2 = mk("t1@s38.test", "teacher"), mk("t2@s38.test", "teacher")
        cls.s1, cls.s2 = mk("s1@s38.test", "student"), mk("s2@s38.test", "student")
        cls.lim = mk("lim@s38.test", "admin")
        cls.c.patch(f"/api/users/{cls.lim}", json={"permissions": ["people"]}, headers=cls.H)
        cls.sql_("UPDATE users SET must_change_password=0")
        cls.course = P("/api/courses", {"name": "Arabic", "code": "AR1", "monthly_fee_mvr": 500, "status": "open"}).get_json()["id"]
        cls.b1 = P("/api/batches", {"course_id": cls.course, "code": "A1", "teacher_id": cls.t1, "capacity": 9, "days": "Mon,Wed", "start_time": "16:00"}).get_json()["id"]
        for s in (cls.s1, cls.s2): assert P("/api/enrollments", {"student_id": s, "batch_id": cls.b1}).status_code == 201
        cls.T1, cls.T2, cls.S1, cls.L = (cls.tok(e, p) for e, p in (("t1@s38.test", PW), ("t2@s38.test", PW), ("s1@s38.test", PW), ("lim@s38.test", PW)))
        cls.codes = {r[0]: r[1] for r in cls.sql_("SELECT user_id, student_code FROM students")}

    @classmethod
    def tok(cls, login, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    @classmethod
    def sql_(cls, q, a=()):
        con = sqlite3.connect(cls.path)
        try: r = con.execute(q, a).fetchall(); con.commit(); return r
        finally: con.close()

    def up(self, path, data, name="f.xlsx", h=None, dry=True):
        r = self.c.post(path + ("&" if "?" in path else "?") + f"dry_run={1 if dry else 0}", data={"file": (io.BytesIO(data), name)}, headers=h or self.H, content_type="multipart/form-data")
        return r

    def book(self, r):
        self.assertEqual(r.status_code, 200, r.data[:300])
        self.assertIn("spreadsheetml", r.mimetype)
        return load_workbook(io.BytesIO(r.data))

    # ---- templates ----
    def test_01_templates(self):
        for kind in ("students", "teachers", "enrolments", "courses", "batches", "expenses"):
            wb = self.book(self.c.get(f"/api/import/{kind}/template.xlsx", headers=self.H))
            self.assertEqual(wb.sheetnames[0], "Data", kind); self.assertIn("Instructions", wb.sheetnames)
            head = [c.value for c in wb["Data"][1]]
            self.assertTrue(head and all(head), kind)
            self.assertEqual(wb["Data"].max_row, 1, kind)                                   # empty: nothing to import by mistake
        wb = self.book(self.c.get("/api/import/enrolments/template.xlsx", headers=self.H))
        self.assertIn("Lists", wb.sheetnames); self.assertIn("AR1", [c.value for c in wb["Lists"]["A"]])
        dv = [d for d in wb["Data"].data_validations.dataValidation]
        self.assertTrue(any("active" in (d.formula1 or "") for d in dv))                  # the status drop-down
        st = self.book(self.c.get("/api/import/students/template.xlsx", headers=self.H))["Data"]
        self.assertEqual(st.column_dimensions["E"].number_format, "@")                                       # phone kept as text: 0771234 keeps its 0
        self.assertEqual(self.c.get("/api/import/courses/template.xlsx", headers=self.L).status_code, 403)
        self.assertEqual(self.c.get("/api/import/students/template.xlsx", headers=self.L).status_code, 200)

    # ---- people imports now read Excel ----
    def test_02_students_from_excel(self):
        data = xlsx(["full_name", "email", "phone", "date_of_birth", "is_active"],
                    [["Aishath Ali", "aishath@x.test", "0771234", dt.datetime(2012, 4, 30), 1], ["Bad Row", "not-an-email", None, None, None]], extra_sheets=("Instructions",))
        r = self.up("/api/import/students", data).get_json()
        self.assertEqual((r["ok"], r["rejected"], r["dry_run"]), (1, 1, True))
        self.assertEqual(self.sql_("SELECT COUNT(*) FROM users WHERE email='aishath@x.test'")[0][0], 0)
        r = self.up("/api/import/students", data, dry=False).get_json()
        self.assertEqual(r["ok"], 1)
        u = self.sql_("SELECT u.phone, s.date_of_birth FROM users u JOIN students s ON s.user_id=u.id WHERE u.email='aishath@x.test'")[0]
        self.assertEqual(u, ("0771234", "2012-04-30"))                                      # leading 0 kept, Excel date read as a date
        self.assertEqual(self.up("/api/import/students", b"\xd0\xcf\x11\xe0junk", "old.xls").status_code, 400)

    # ---- courses and batches through the screen routes ----
    def test_03_courses_and_batches(self):
        data = xlsx(["code", "name", "kind", "monthly_fee_mvr", "registration_fee_mvr", "status"],
                    [["QR1", "Quran Reading", "course", 300, 50, "open"], ["QR1", "Same code again", "course", 300, 0, "open"], ["", "Maths Grade 8", "tuition", 250, None, "open"],
                     ["XX", "Bad", "lesson", 1, 0, "open"]])
        n0 = self.sql_("SELECT COUNT(*) FROM courses")[0][0]
        r = self.up("/api/import/courses", data).get_json()
        self.assertEqual([x["status"] for x in r["rows"]], ["would_create", "rejected", "would_create", "rejected"], r)   # the duplicate in the same file is caught
        self.assertEqual(self.sql_("SELECT COUNT(*) FROM courses")[0][0], n0)               # the check saved nothing
        self.assertEqual(self.sql_("SELECT COUNT(*) FROM audit_log WHERE action='create_course' AND detail='Quran Reading'")[0][0], 0)
        r = self.up("/api/import/courses", data, dry=False).get_json()
        self.assertEqual((r["ok"], r["rejected"]), (2, 2))
        self.assertEqual(self.sql_("SELECT name, registration_fee_mvr FROM courses WHERE code='QR1'")[0], ("Quran Reading", 50))
        self.assertEqual(self.sql_("SELECT COUNT(*) FROM audit_log WHERE action='create_course' AND detail IN ('Quran Reading','Maths Grade 8')")[0][0], 2)   # same log line as the screen
        t1code = self.sql_("SELECT teacher_code FROM teachers WHERE user_id=?", (self.t1,))[0][0]
        b = xlsx(["course_code", "code", "teacher", "days", "start_time", "capacity"],
                 [["QR1", "Q1", t1code, "sun, tue", dt.time(16, 30), 12], ["QR1", "Q2", "t2@s38.test", "Mon", "9:00", None], ["NOPE", "Z", "", "", "", ""], ["QR1", "Q3", "nobody", "", "", ""]])
        r = self.up("/api/import/batches", b, dry=False).get_json()
        self.assertEqual([x["status"] for x in r["rows"]], ["created", "created", "rejected", "rejected"], r)
        self.assertIn("No course with code NOPE", r["rows"][2]["message"])
        q1 = self.sql_("SELECT days, start_time, capacity, teacher_id FROM batches WHERE code='Q1'")[0]
        self.assertEqual(q1, ("Tue,Sun", "16:30", 12, self.t1))                              # days in the portal's own order
        self.assertEqual(self.sql_("SELECT start_time, teacher_id FROM batches WHERE code='Q2'")[0], ("09:00", self.t2))
        # exports carry the same columns, so a file can go out and back
        wb = self.book(self.c.get("/api/courses/export.xlsx", headers=self.H)).active
        self.assertEqual([c.value for c in wb[1]][:3], ["code", "name", "kind"]); self.assertIn("QR1", [c.value for c in wb["A"]])
        wb = self.book(self.c.get("/api/batches/export.xlsx", headers=self.H)).active
        self.assertEqual([c.value for c in wb[1]][:3], ["course_code", "code", "teacher"])
        self.assertEqual(self.c.get("/api/batches/export.csv", headers=self.H).data[:3], b"\xef\xbb\xbf")

    # ---- expenses ----
    def test_04_expenses(self):
        self.c.post("/api/expense-categories", json={"name": "Rent"}, headers=self.H)
        r = self.c.get("/api/import/expenses/template.xlsx", headers=self.H)
        self.assertIn("Rent", [c.value for c in self.book(r)["Lists"]["A"]])
        data = xlsx(["expense_date", "amount_mvr", "category", "description"],
                    [[dt.date(2027, 3, 1), 9000, "rent", "March rent"], ["2027-04-01", 10, "Rent", "future"], ["2027-03-02", 50, "Snacks", ""], ["2027-03-03", "abc", "Rent", ""]])
        r = self.up("/api/import/expenses", data, dry=False).get_json()
        self.assertEqual([x["status"] for x in r["rows"]], ["created", "rejected", "rejected", "rejected"], r)
        self.assertIn("No category called Snacks", r["rows"][2]["message"])
        self.assertEqual(self.sql_("SELECT expense_date, amount_mvr FROM expenses")[0], ("2027-03-01", 9000))
        wb = self.book(self.c.get("/api/expenses/export.xlsx?date_from=2027-03-01", headers=self.H)).active
        self.assertEqual(wb["D2"].value, 9000); self.assertEqual(wb["B3"].value, "Total")
        self.assertEqual(self.c.get("/api/expenses/export.xlsx", headers=self.T1).status_code, 403)
        self.assertEqual(self.c.get("/api/expenses/export.xlsx?date_from=bad", headers=self.H).status_code, 400)

    # ---- grades ----
    def test_05_grades(self):
        aid = self.c.post(f"/api/batches/{self.b1}/assignments", json={"title": "Quiz 1", "kind": "test", "max_points": 20}, headers=self.T1).get_json()["id"]
        r = self.c.get(f"/api/import/grades/template.xlsx?assignment_id={aid}", headers=self.T1)
        ws = self.book(r)["Data"]
        got = sorted([ws.cell(row=i, column=1).value for i in range(2, ws.max_row + 1)])
        self.assertEqual(got, sorted([self.codes[self.s1], self.codes[self.s2]]))       # the class list, filled in
        self.assertEqual(self.c.get(f"/api/import/grades/template.xlsx?assignment_id={aid}", headers=self.T2).status_code, 403)
        data = xlsx(["student_code", "student", "grade", "feedback"], [[self.codes[self.s1], "s1", 18, "Good"], [self.codes[self.s2], "s2", None, ""], ["BAL/ZZ/999", "x", 5, ""]])
        r = self.up(f"/api/import/grades?assignment_id={aid}", data, h=self.T1).get_json()
        self.assertEqual([x["status"] for x in r["rows"]], ["would_create", "skipped", "rejected"], r)
        self.assertEqual(self.sql_("SELECT COUNT(*) FROM submissions WHERE grade IS NOT NULL")[0][0], 0)
        self.assertEqual(self.sql_("SELECT COUNT(*) FROM notifications WHERE kind='grade'")[0][0], 0)   # a check sends nothing
        r = self.up(f"/api/import/grades?assignment_id={aid}", data, h=self.T1, dry=False).get_json()
        self.assertEqual(r["ok"], 1)
        self.assertEqual(self.sql_("SELECT grade, feedback FROM submissions WHERE student_id=?", (self.s1,))[0], (18.0, "Good"))
        again = xlsx(["student_code", "grade"], [[self.codes[self.s1], 15]])
        r = self.up(f"/api/import/grades?assignment_id={aid}", again, h=self.T1, dry=False).get_json()
        self.assertEqual(r["rows"][0]["status"], "rejected"); self.assertIn("already saved", r["rows"][0]["message"])   # the same rule as the screen
        self.assertEqual(self.up(f"/api/import/grades?assignment_id={aid}", data, h=self.T2).status_code, 403)
        # gradebook and attendance registers
        wb = self.book(self.c.get(f"/api/batches/{self.b1}/gradebook.xlsx", headers=self.T1)).active
        self.assertIn("Quiz 1 (/20)", [c.value for c in wb[1]])
        self.assertEqual(self.c.get(f"/api/batches/{self.b1}/gradebook.xlsx", headers=self.T2).status_code, 403)
        self.c.post(f"/api/batches/{self.b1}/attendance", json={"date": "2027-03-08", "records": [{"student_id": self.s1, "status": "present"}, {"student_id": self.s2, "status": "absent"}]}, headers=self.T1)
        wb = self.book(self.c.get(f"/api/batches/{self.b1}/attendance.xlsx?month=2027-03", headers=self.T1)).active
        head = [c.value for c in wb[1]]
        self.assertIn("03-08", head)
        vals = {wb.cell(row=i, column=1).value: wb.cell(row=i, column=head.index("03-08") + 1).value for i in range(2, 4)}
        self.assertEqual(vals, {self.codes[self.s1]: "P", self.codes[self.s2]: "A"})

    # ---- list exports ----
    def test_06_exports(self):
        for path in ("/api/invoices/export.xlsx", "/api/applications/export.xlsx", "/api/audit.xlsx", "/api/fees/report.xlsx?month=2027-03", "/api/enrollment-events.xlsx"):
            self.book(self.c.get(path, headers=self.H))
        wb = self.book(self.c.get("/api/invoices/export.xlsx?status=all", headers=self.H)).active
        self.assertEqual(wb.max_row - 1, len(self.c.get("/api/invoices?status=all", headers=self.H).get_json()))
        for path in ("/api/invoices/export.xlsx", "/api/applications/export.csv", "/api/courses/export.xlsx"):
            self.assertEqual(self.c.get(path, headers=self.L).status_code, 403, path)
            self.assertEqual(self.c.get(path).status_code, 401, path)
        acts = {r[0] for r in self.sql_("SELECT action FROM audit_log WHERE action LIKE 'export_%'")}
        self.assertTrue({"export_invoices_xlsx", "export_applications_xlsx", "export_audit_xlsx", "export_fees_xlsx"} <= acts, acts)

    def test_07_formula_text_is_safe(self):
        wb = Workbook(); ws = wb.active; ws.title = "Data"; ws.append(["name", "monthly_fee_mvr"]); ws["A2"] = '=HYPERLINK("x")'; ws["A2"].data_type = "s"; ws["B2"] = 10
        b = io.BytesIO(); wb.save(b)
        r = self.up("/api/import/courses", b.getvalue(), dry=False).get_json()
        self.assertEqual(r["ok"], 1, r)
        ws = self.book(self.c.get("/api/courses/export.xlsx", headers=self.H)).active
        names = [ws.cell(row=i, column=2).value for i in range(2, ws.max_row + 1)]
        self.assertIn("'=HYPERLINK(\"x\")", names)                                          # exported as text, not as a formula


if __name__ == "__main__":
    unittest.main()
