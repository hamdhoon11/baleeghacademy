"""Session 27: exports (CSV and Excel) and CSV imports with dry run, plus a round trip into an empty database."""
import csv, datetime as dt, io, os, sqlite3, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PW = "Passw0rd!x1"
MVT = dt.timezone(dt.timedelta(hours=5))


def make_app(tag):
    tmp = tempfile.mkdtemp(); path = os.path.join(tmp, "t.db")
    old = os.environ.get("SEED_DEMO")
    os.environ.update(DATABASE_PATH=path, ADMIN_EMAIL=f"admin@{tag}.test", ADMIN_PASSWORD="AdminPass123", SEED_DEMO="0")
    import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
    os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)   # do not leak into the other test modules
    from app import create_app
    app = create_app({"DATABASE_PATH": path}); c = app.test_client()
    app.config["NOW"] = lambda: dt.datetime(2027, 3, 10, 12, 0, tzinfo=MVT)
    tok = c.post("/api/auth/login", json={"login": f"admin@{tag}.test", "password": "AdminPass123"}).get_json()["token"]
    return app, c, {"Authorization": "Bearer " + tok}, path


def csv_file(text, name="x.csv"): return {"file": (io.BytesIO(text.encode("utf-8")), name)}


class S27(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app, cls.c, cls.H, cls.path = make_app("a27")
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, role, **kw: P("/api/users", {"email": e, "password": PW, "full_name": kw.pop("n", e), "role": role, **kw}).get_json()["id"]
        cls.t1 = mk("t1@a27.test", "teacher", n="Teacher One", bio="Maths teacher")
        cls.ar = P("/api/courses", {"name": "Arabic", "code": "AR1", "monthly_fee_mvr": 1000, "status": "open"}).get_json()["id"]
        cls.tu = P("/api/courses", {"name": "Grade 8 Mathematics", "kind": "tuition", "code": "G8M", "monthly_fee_mvr": 600, "status": "open"}).get_json()["id"]
        bt = lambda cid, code, cap=9: P("/api/batches", {"course_id": cid, "code": code, "teacher_id": cls.t1, "capacity": cap, "days": "Mon", "start_time": "16:00"}).get_json()["id"]
        cls.b1, cls.b2, cls.b3 = bt(cls.ar, "A1"), bt(cls.tu, "M1"), bt(cls.ar, "A2", 1)
        cls.s1 = mk("s1@a27.test", "student", n="Student One", phone="7771111", grade="8", island="Male", guardian_name="Guardian One", date_of_birth="2012-04-30", course_id=cls.ar)
        cls.s2 = mk("s2@a27.test", "student", n="=cmd|calc", course_id=cls.tu)
        cls.s3 = mk("s3@a27.test", "student", n="Student Three")       # no enrolment, no student code
        for s, b in ((cls.s1, cls.b1), (cls.s2, cls.b2), (cls.s1, cls.b2)): assert P("/api/enrollments", {"student_id": s, "batch_id": b}).status_code == 201
        e = cls.c.get("/api/enrollments", headers=cls.H).get_json()
        drop = [x for x in e if x["student_id"] == cls.s1 and x["batch_id"] == cls.b2][0]["id"]
        assert cls.c.patch(f"/api/enrollments/{drop}", json={"status": "dropped"}, headers=cls.H).status_code == 200
        assert cls.c.patch(f"/api/users/{cls.s3}", json={"is_active": False}, headers=cls.H).status_code == 200
        cls.lim = mk("lim@a27.test", "admin", permissions=["people"])
        cls.lim2 = mk("lim2@a27.test", "admin", permissions=["student_information"])
        cls.L, cls.L2, cls.T, cls.S = (cls.tok(x) for x in ("lim@a27.test", "lim2@a27.test", "t1@a27.test", "s1@a27.test"))

    @classmethod
    def tok(cls, login, pw=PW):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    def sql(self, q, a=(), path=None):
        con = sqlite3.connect(path or self.path)
        try: return con.execute(q, a).fetchall()
        finally: con.close()

    def table(self, url, c=None, h=None):
        r = (c or self.c).get(url, headers=h or self.H); self.assertEqual(r.status_code, 200, url)
        return list(csv.DictReader(io.StringIO(r.get_data(as_text=True).lstrip("\ufeff")))), r

    # ---------- exports ----------
    def test_student_export(self):
        rows, r = self.table("/api/student-information/export.csv")
        self.assertIn("text/csv", r.headers["Content-Type"]); self.assertIn("student-information.csv", r.headers["Content-Disposition"])
        self.assertEqual(len(rows), 3); by = {x["email"]: x for x in rows}
        s1 = by["s1@a27.test"]
        self.assertEqual((s1["full_name"], s1["student_code"], s1["phone"], s1["grade"], s1["island"], s1["date_of_birth"], s1["is_active"]), ("Student One", "BAL/AR1/001", "7771111", "8", "Male", "2012-04-30", "1"))
        self.assertIn("AR1", s1["student_code"]); self.assertIn("Arabic · A1", s1["enrolments"]); self.assertIn("dropped", s1["enrolments"])
        self.assertEqual(by["s3@a27.test"]["is_active"], "0"); self.assertEqual(by["s3@a27.test"]["student_code"], "")
        self.assertEqual(by["s2@a27.test"]["full_name"], "'=cmd|calc")           # formula-injection safe
        text = self.c.get("/api/student-information/export.csv", headers=self.H).get_data(as_text=True).lower()
        for bad in ("password", "pbkdf2", "scrypt", "hash", "balance", "invoice"): self.assertNotIn(bad, text)
        self.assertTrue(self.sql("SELECT 1 FROM audit_log WHERE action='export_student_information'"))

    def test_student_export_filters(self):
        self.assertEqual({x["email"] for x in self.table("/api/student-information/export.csv?status=inactive")[0]}, {"s3@a27.test"})
        self.assertEqual({x["email"] for x in self.table(f"/api/student-information/export.csv?batch_id={self.b2}")[0]}, {"s2@a27.test"})   # active or completed only
        self.assertEqual({x["email"] for x in self.table("/api/student-information/export.csv?q=one")[0]}, {"s1@a27.test"})

    def test_teacher_export_and_xlsx(self):
        rows, _ = self.table("/api/teacher-information/export.csv")
        self.assertEqual(len(rows), 1); t = rows[0]
        self.assertEqual((t["full_name"], t["teacher_code"], t["bio"], t["is_active"]), ("Teacher One", "BAL/T/001", "Maths teacher", "1")); self.assertIn("Arabic · A1", t["batches"])
        from openpyxl import load_workbook
        r = self.c.get("/api/teacher-information/export.xlsx", headers=self.H)
        self.assertIn("spreadsheetml", r.headers["Content-Type"])
        ws = load_workbook(io.BytesIO(r.data)).active; self.assertEqual([c.value for c in ws[1]][:3], ["teacher_code", "login_id", "full_name"]); self.assertEqual(ws["C2"].value, "Teacher One")
        r = self.c.get("/api/student-information/export.xlsx", headers=self.H); self.assertEqual(r.status_code, 200)
        self.assertTrue(self.sql("SELECT 1 FROM audit_log WHERE action='export_teacher_information'"))

    def test_enrolment_export(self):
        rows, _ = self.table("/api/student-information/enrolments.csv")
        self.assertEqual(len(rows), 3); st = sorted((x["student_code"], x["course_code"], x["batch_code"], x["status"]) for x in rows)
        self.assertEqual(st, [("BAL/AR1/001", "AR1", "A1", "active"), ("BAL/AR1/001", "G8M", "M1", "dropped"), ("BAL/G8M/001", "G8M", "M1", "active")])
        self.assertTrue(all(x["enrol_code"] for x in rows))

    def test_export_permissions(self):
        for u in ("/api/student-information/export.csv", "/api/student-information/export.xlsx", "/api/student-information/enrolments.csv", "/api/teacher-information/export.csv", "/api/teacher-information/export.xlsx"):
            self.assertEqual(self.c.get(u).status_code, 401, u)
            for h in (self.T, self.S): self.assertEqual(self.c.get(u, headers=h).status_code, 403, u)
        self.assertEqual(self.c.get("/api/student-information/export.csv", headers=self.L).status_code, 403)       # people only
        self.assertEqual(self.c.get("/api/teacher-information/export.csv", headers=self.L2).status_code, 403)     # student_information only
        self.assertEqual(self.c.get("/api/student-information/export.csv", headers=self.L2).status_code, 200)

    # ---------- imports ----------
    def imp(self, kind, text, dry=None, h=None, c=None):
        q = "" if dry is None else f"?dry_run={dry}"
        return (c or self.c).post(f"/api/import/{kind}{q}", data=csv_file(text), headers=h or self.H, content_type="multipart/form-data")

    def test_dry_run_is_default_and_writes_nothing(self):
        app, c, H, path = make_app("d27")
        before = self.sql("SELECT COUNT(*) FROM users", path=path)[0][0]
        r = self.imp("students", "full_name,email\nAmina Ali,amina@d27.test\nBad Row,not-an-email\n", h=H, c=c).get_json()
        self.assertTrue(r["dry_run"]); self.assertEqual((r["total"], r["ok"], r["rejected"]), (2, 1, 1)); self.assertEqual(r["rows"][0]["status"], "would_create")
        self.assertEqual(r["rows"][1]["row"], 3); self.assertIn("email", r["rows"][1]["message"])
        self.assertNotIn("temporary_password", r["rows"][0])
        self.assertEqual(self.sql("SELECT COUNT(*) FROM users", path=path)[0][0], before)
        self.assertFalse(self.sql("SELECT 1 FROM audit_log WHERE action='import_students'", path=path))
        self.imp("students", "full_name,email\nAmina Ali,amina@d27.test\n", dry=1, h=H, c=c)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM users", path=path)[0][0], before)

    def test_apply_with_rejected_rows(self):
        app, c, H, path = make_app("r27")
        txt = ("full_name,email,phone,date_of_birth,student_code\n"
               "Good One,good1@r27.test,7770001,2011-01-02,BAL/AR1/050\n"
               "Dup Email,GOOD1@r27.test,,,\n"                      # same email (case) as row 2
               "Bad Date,bad@r27.test,,31/12/2011,\n"
               "Good Two,good2@r27.test,,,\n"
               ",noname@r27.test,,,\n"
               "Same Code,same@r27.test,,,BAL/AR1/050\n"
               "admin,admin@r27.test,,,\n")                          # already registered
        r = self.imp("students", txt, dry=0, h=H, c=c).get_json()
        self.assertEqual((r["total"], r["ok"], r["rejected"]), (7, 2, 5))
        st = [x["status"] for x in r["rows"]]; self.assertEqual(st, ["created", "rejected", "rejected", "created", "rejected", "rejected", "rejected"])
        self.assertIn("twice", r["rows"][1]["message"]); self.assertIn("date", r["rows"][2]["message"]); self.assertIn("already", r["rows"][6]["message"])
        g1 = r["rows"][0]; self.assertEqual(g1["student_code"], "BAL/AR1/050"); self.assertEqual(g1["login_id"], "BAL/AR1/050"); self.assertTrue(g1["temporary_password"])
        self.assertTrue(r["rows"][3]["login_id"].startswith("BAL/STU/"))
        # the temporary password works once, then the account must change it
        lg = c.post("/api/auth/login", json={"login": "BAL/AR1/050", "password": g1["temporary_password"]}).get_json()
        self.assertTrue(lg["user"]["must_change_password"])
        self.assertEqual(self.sql("SELECT COUNT(*) FROM users WHERE email LIKE '%r27.test' AND role='student'", path=path)[0][0], 2)
        # passwords never reach the log or any stored text
        log = " ".join(str(x) for row in self.sql("SELECT detail, old_value, new_value FROM audit_log", path=path) for x in row)
        self.assertNotIn(g1["temporary_password"], log); self.assertTrue(self.sql("SELECT 1 FROM audit_log WHERE action='import_students'", path=path))
        # importing the same file again creates nobody
        r2 = self.imp("students", txt, dry=0, h=H, c=c).get_json(); self.assertEqual(r2["ok"], 0)

    def test_teacher_import(self):
        app, c, H, path = make_app("t27")
        r = self.imp("teachers", "full_name,email,bio,teacher_code\nMr Ali,ali@t27.test,Physics,BAL/T/009\nMs Beta,beta@t27.test,,\n", dry=0, h=H, c=c).get_json()
        self.assertEqual(r["ok"], 2); self.assertEqual(r["rows"][0]["teacher_code"], "BAL/T/009"); self.assertEqual(r["rows"][1]["login_id"], "BAL/T/001")
        self.assertEqual(self.sql("SELECT teacher_code FROM teachers t JOIN users u ON u.id=t.user_id WHERE u.email='ali@t27.test'", path=path)[0][0], "BAL/T/009")
        self.assertEqual(c.get("/api/users?role=teacher", headers=H).get_json()[0]["role"], "teacher")

    def test_import_file_problems(self):
        self.assertEqual(self.c.post("/api/import/students", headers=self.H).status_code, 400)                                  # nothing sent
        self.assertEqual(self.imp("students", "full_name\nA\n").status_code, 400)                                                 # no email column
        self.assertEqual(self.imp("enrolments", "student_code\nX\n").status_code, 400)
        r = self.c.post("/api/import/students", data={"file": (io.BytesIO(b"full_name,email\n\xff\xfe\x00bad\n"), "x.csv")}, headers=self.H, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)
        r = self.c.post("/api/import/students?dry_run=1", data="full_name,email\nRaw Body,raw@a27.test\n", headers={**self.H, "Content-Type": "text/csv"})
        self.assertEqual(r.status_code, 200); self.assertEqual(r.get_json()["ok"], 1)

    def test_enrolment_import_rules(self):
        app, c, H, path = make_app("e27")
        P = lambda p, j: c.post(p, json=j, headers=H)
        t = P("/api/users", {"email": "t@e27.test", "password": PW, "full_name": "T", "role": "teacher"}).get_json()["id"]
        ar = P("/api/courses", {"name": "Arabic", "code": "AR1", "monthly_fee_mvr": 1000, "status": "open"}).get_json()["id"]
        P("/api/batches", {"course_id": ar, "code": "A1", "teacher_id": t, "capacity": 1, "days": "Mon", "start_time": "16:00"})
        self.imp("students", "full_name,email,student_code\nOne,one@e27.test,BAL/AR1/001\nTwo,two@e27.test,BAL/AR1/002\n", dry=0, h=H, c=c)
        txt = ("student_code,course_code,batch_code,status,enrol_code,enrolled_at\n"
               "BAL/AR1/001,AR1,A1,active,BAL/AR1/E007,2027-02-01\n"
               "BAL/AR1/002,AR1,A1,active,,\n"                    # batch full (capacity 1)
               "BAL/AR1/002,AR1,A1,waitlist,,\n"                  # second row same pair -> twice (first one was rejected, so allowed)
               "BAL/AR1/999,AR1,A1,active,,\n"                    # unknown student
               "BAL/AR1/002,AR1,ZZ,active,,\n"                    # unknown batch
               "BAL/AR1/002,AR1,A1,sleeping,,\n")                 # bad status
        r = self.imp("enrolments", txt, dry=1, h=H, c=c).get_json()
        self.assertEqual([x["status"] for x in r["rows"]], ["would_create", "rejected", "would_create", "rejected", "rejected", "rejected"])
        self.assertIn("full", r["rows"][1]["message"]); self.assertIn("No student", r["rows"][3]["message"]); self.assertIn("No batch", r["rows"][4]["message"])
        self.assertEqual(self.sql("SELECT COUNT(*) FROM enrollments", path=path)[0][0], 0)
        r = self.imp("enrolments", txt, dry=0, h=H, c=c).get_json(); self.assertEqual(r["ok"], 2)
        self.assertEqual(r["rows"][0]["enrol_code"], "BAL/AR1/E007")
        self.assertEqual(self.sql("SELECT status, SUBSTR(enrolled_at,1,10) FROM enrollments ORDER BY id", path=path), [("active", "2027-02-01"), ("waitlist", self.sql("SELECT SUBSTR(enrolled_at,1,10) FROM enrollments WHERE status='waitlist'", path=path)[0][0])])
        again = self.imp("enrolments", txt, dry=0, h=H, c=c).get_json(); self.assertEqual(again["ok"], 0); self.assertIn("Already enrolled", again["rows"][0]["message"])

    def test_import_permissions(self):
        txt = "full_name,email\nX,x@a27.test\n"
        for k in ("students", "teachers", "enrolments"):
            self.assertEqual(self.c.post(f"/api/import/{k}").status_code, 401)
            for h in (self.T, self.S, self.L2): self.assertEqual(self.imp(k, txt, h=h).status_code, 403, k)
        self.assertEqual(self.imp("students", txt, h=self.L).status_code, 200)        # people
        self.assertEqual(self.imp("enrolments", "course_code,batch_code\n", h=self.L).status_code, 403)   # needs enrollments

    # ---------- round trip ----------
    def test_round_trip_into_empty_database(self):
        stu, _ = self.table("/api/student-information/export.csv"); tea, _ = self.table("/api/teacher-information/export.csv"); en, _ = self.table("/api/student-information/enrolments.csv")
        raw = lambda url: self.c.get(url, headers=self.H).get_data(as_text=True).lstrip("\ufeff")
        app, c, H, path = make_app("b27")
        P = lambda p, j: c.post(p, json=j, headers=H)
        r = self.imp("teachers", raw("/api/teacher-information/export.csv"), dry=0, h=H, c=c).get_json(); self.assertEqual(r["rejected"], 0, r)
        t = r["rows"][0]["id"]
        for name, code, kind, batches in (("Arabic", "AR1", "course", (("A1", 9), ("A2", 1))), ("Grade 8 Mathematics", "G8M", "tuition", (("M1", 9),))):
            cid = P("/api/courses", {"name": name, "code": code, "kind": kind, "monthly_fee_mvr": 1000, "status": "open"}).get_json()["id"]
            for bc, cap in batches: P("/api/batches", {"course_id": cid, "code": bc, "teacher_id": t, "capacity": cap, "days": "Mon", "start_time": "16:00"})
        r = self.imp("students", raw("/api/student-information/export.csv"), dry=0, h=H, c=c).get_json(); self.assertEqual(r["rejected"], 0, r)
        r = self.imp("enrolments", raw("/api/student-information/enrolments.csv"), dry=0, h=H, c=c).get_json(); self.assertEqual(r["rejected"], 0, r)
        q = "SELECT u.email, u.full_name, u.phone, u.is_active, s.student_code, s.date_of_birth, s.grade, s.island, s.guardian_name FROM users u JOIN students s ON s.user_id=u.id ORDER BY u.email"
        self.assertEqual(self.sql(q), self.sql(q, path=path))
        self.assertEqual(self.sql("SELECT u.email, t.teacher_code, t.bio FROM users u JOIN teachers t ON t.user_id=u.id WHERE u.email='t1@a27.test'"),
                         self.sql("SELECT u.email, t.teacher_code, t.bio FROM users u JOIN teachers t ON t.user_id=u.id WHERE u.email='t1@a27.test'", path=path))
        q = ("SELECT s.student_code, c.code, b.code, e.status, e.enrol_code, SUBSTR(e.enrolled_at,1,10) FROM enrollments e JOIN students s ON s.user_id=e.student_id "
             "JOIN batches b ON b.id=e.batch_id JOIN courses c ON c.id=b.course_id ORDER BY s.student_code, c.code, b.code")
        a, b = self.sql(q), self.sql(q, path=path)
        self.assertEqual(len(a), 3); self.assertEqual(a, b)
        # the people and enrolments in the new database export to the same files (apart from sign-in IDs of people with no course yet)
        stu2 = list(csv.DictReader(io.StringIO(c.get("/api/student-information/export.csv", headers=H).get_data(as_text=True).lstrip("\ufeff"))))
        self.assertEqual(sorted((x["email"], x["student_code"], x["full_name"]) for x in stu2), sorted((x["email"], x["student_code"], x["full_name"]) for x in stu))


if __name__ == "__main__":
    unittest.main()
