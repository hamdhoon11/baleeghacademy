"""Session 25: admin dashboard. Every card against a hand count; every filter changes the right cards."""
import datetime as dt, os, sqlite3, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PW = "Passw0rd!x1"
MVT = dt.timezone(dt.timedelta(hours=5))


class S25(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s25.test", ADMIN_PASSWORD="AdminPass123")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path}); cls.c = cls.app.test_client()
        cls.app.config["NOW"] = lambda: dt.datetime(2027, 3, 10, 12, 0, tzinfo=MVT)   # a Wednesday
        con = sqlite3.connect(cls.path)   # start from an empty academy: remove the demo course, batches, enrolment and demo logins
        for q in ("DELETE FROM enrollments", "DELETE FROM batches", "DELETE FROM courses", "UPDATE users SET is_active=0 WHERE email LIKE '%@baleegh.test'"): con.execute(q)
        con.commit(); con.close()
        cls.H = cls.tok("admin@s25.test", "AdminPass123")
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, role, **kw: P("/api/users", {"email": e, "password": PW, "full_name": e, "role": role, **kw}).get_json()["id"]
        cls.t1, cls.t2 = mk("t1@s25.test", "teacher"), mk("t2@s25.test", "teacher")
        cls.s1, cls.s2, cls.s3, cls.s4 = (mk(f"s{i}@s25.test", "student") for i in (1, 2, 3, 4))
        cls.fin = mk("fin@s25.test", "admin", permissions=["finance"]); cls.fee = mk("fee@s25.test", "admin", permissions=["fees"]); cls.none = mk("none@s25.test", "admin", permissions=["courses"])
        cls.ar = P("/api/courses", {"name": "Arabic", "monthly_fee_mvr": 1000, "status": "open"}).get_json()["id"]
        cls.tu = P("/api/courses", {"name": "Grade 8 Mathematics", "kind": "tuition", "code": "G8M", "monthly_fee_mvr": 600, "status": "open"}).get_json()["id"]
        cls.a1 = P("/api/batches", {"course_id": cls.ar, "code": "A1", "teacher_id": cls.t1, "capacity": 9, "days": "Mon,Wed", "start_time": "16:00"}).get_json()["id"]
        cls.m1 = P("/api/batches", {"course_id": cls.tu, "code": "M1", "teacher_id": cls.t2, "capacity": 9, "days": "Mon", "start_time": "17:00"}).get_json()["id"]
        en = {}
        for s, b in ((cls.s1, cls.a1), (cls.s2, cls.a1), (cls.s3, cls.m1), (cls.s4, cls.a1)): en[s] = P("/api/enrollments", {"student_id": s, "batch_id": b}).get_json()["id"]
        assert cls.c.patch(f"/api/enrollments/{en[cls.s4]}", json={"status": "dropped"}, headers=cls.H).status_code == 200
        inv = lambda s: cls.c.get(f"/api/invoices?student_id={s}", headers=cls.H).get_json()[0]["id"]
        for s, amt, day in ((cls.s1, 500, "2027-03-04"), (cls.s3, 600, "2027-03-09")):
            assert P("/api/payments", {"invoice_id": inv(s), "amount_mvr": amt, "method": "cash", "paid_on": day}).status_code == 201
        cat = P("/api/expense-categories", {"name": "Rent"}).get_json()["id"]
        assert cls.c.post("/api/expenses", data={"expense_date": "2027-03-03", "amount_mvr": "200", "category_id": str(cat)}, headers=cls.H, content_type="multipart/form-data").status_code == 201
        con = sqlite3.connect(cls.path)
        for b, d, st in ((cls.a1, "2027-03-01", "held"), (cls.a1, "2027-03-03", "held"), (cls.a1, "2027-03-08", "held"), (cls.a1, "2027-03-05", "cancelled"), (cls.m1, "2027-03-02", "held")):
            con.execute("INSERT INTO sessions(batch_id,session_date,start_time,status) VALUES(?,?,?,?)", (b, d, "09:00", st))
        A = lambda b, title, kind, day: con.execute("INSERT INTO assignments(batch_id,title,kind,created_by,created_at) VALUES(?,?,?,?,?)", (b, title, kind, cls.t1, day + " 06:00:00")).lastrowid
        x1, x2, tt, x3 = A(cls.a1, "a1", "assignment", "2027-03-01"), A(cls.a1, "a2", "assignment", "2027-03-05"), A(cls.a1, "t1", "test", "2027-03-06"), A(cls.m1, "a3", "assignment", "2027-03-02")
        S = lambda a, s, sub, gr: con.execute("INSERT INTO submissions(assignment_id,student_id,submitted_at,grade) VALUES(?,?,?,?)", (a, s, sub, gr))
        S(x1, cls.s1, "2027-03-02 05:00:00", 8); S(x1, cls.s2, "2027-03-02 05:00:00", None); S(x1, cls.s4, "2027-03-02 05:00:00", None)   # s4 was dropped: not counted
        S(x2, cls.s1, "2027-03-06 05:00:00", None); S(tt, cls.s1, None, 7); S(x3, cls.s3, "2027-03-03 05:00:00", None)
        T = lambda title, cid, day: con.execute("INSERT INTO tutorials(title,body,course_id,uploaded_by,created_at) VALUES(?,?,?,?,?)", (title, "b", cid, cls.t1, day + " 06:00:00"))
        T("general", None, "2027-03-03"); T("ar1", cls.ar, "2027-02-10"); T("ar2", cls.ar, "2027-03-03"); T("tu1", cls.tu, "2027-03-03")
        AP = lambda ref, cid, st: con.execute("INSERT INTO applications(ref,full_name,date_of_birth,phone,email,course_id,status,created_at) VALUES(?,?,?,?,?,?,?,?)", (ref, ref, "2000-01-01", "7000000", ref + "@x.test", cid, st, "2027-03-04 05:00:00"))
        AP("AP1", cls.ar, "pending"); AP("AP2", cls.tu, "pending"); AP("AP3", cls.ar, "rejected")
        con.commit(); con.close()
        cls.F, cls.FE, cls.NO, cls.T1, cls.ST = (cls.tok(e, PW) for e in ("fin@s25.test", "fee@s25.test", "none@s25.test", "t1@s25.test", "s1@s25.test"))

    @classmethod
    def tok(cls, login, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    def dash(self, qs="", H=None):
        r = self.c.get("/api/admin/dashboard?" + qs, headers=H or self.H); self.assertEqual(r.status_code, 200, r.get_data(as_text=True)); return r.get_json()

    def sql_one(self, q):
        con = sqlite3.connect(self.path)
        try: return con.execute(q).fetchone()[0]
        finally: con.close()

    def pick(self, d, *keys): return {k: d[k] for k in keys}

    def test_01_unfiltered_cards_match_hand_count(self):
        d = self.dash()
        self.assertEqual(self.pick(d, "students", "teachers", "batches", "courses", "tuition_classes", "student_accounts", "teacher_accounts"),
                         {"students": 3, "teachers": 2, "batches": 2, "courses": 1, "tuition_classes": 1, "student_accounts": 4, "teacher_accounts": 2})   # s4 dropped
        self.assertEqual(self.pick(d, "classes_held", "classes_cancelled", "classes_upcoming"), {"classes_held": 4, "classes_cancelled": 1, "classes_upcoming": 12})   # 8 Mon/Wed of A1 + 4 Mondays of M1
        self.assertEqual(self.pick(d, "assignments", "tests", "submissions", "graded", "pending_grading", "tutorials"),
                         {"assignments": 3, "tests": 1, "submissions": 4, "graded": 2, "pending_grading": 3, "tutorials": 4})
        self.assertEqual((d["admissions_pending"], d["admissions_received"]), (2, 3))

    def test_02_tuition_filter(self):
        d = self.dash("kind=tuition")
        self.assertEqual(self.pick(d, "students", "teachers", "batches", "courses", "tuition_classes", "classes_held", "classes_upcoming", "assignments", "tests", "submissions", "graded", "pending_grading", "tutorials", "admissions_pending"),
                         {"students": 1, "teachers": 1, "batches": 1, "courses": 0, "tuition_classes": 1, "classes_held": 1, "classes_upcoming": 4, "assignments": 1, "tests": 0, "submissions": 1, "graded": 0, "pending_grading": 1, "tutorials": 1, "admissions_pending": 1})
        self.assertEqual(self.dash("teacher_id=%d" % self.t2)["submissions"], 1)        # the tuition teacher gives the same answer
        self.assertEqual(self.dash("batch_id=%d" % self.m1)["classes_upcoming"], 4)

    def test_03_course_filter(self):
        d = self.dash("course_id=%d" % self.ar)
        self.assertEqual(self.pick(d, "students", "teachers", "courses", "tuition_classes", "classes_held", "classes_cancelled", "classes_upcoming", "assignments", "tests", "submissions", "graded", "pending_grading", "tutorials", "admissions_pending"),
                         {"students": 2, "teachers": 1, "courses": 1, "tuition_classes": 0, "classes_held": 3, "classes_cancelled": 1, "classes_upcoming": 8, "assignments": 2, "tests": 1, "submissions": 3, "graded": 2, "pending_grading": 2, "tutorials": 2, "admissions_pending": 1})
        by_batch = self.dash("batch_id=%d" % self.a1); self.assertEqual({k: v for k, v in by_batch.items() if k not in ("filters", "admissions_pending", "admissions_received")}, {k: v for k, v in d.items() if k not in ("filters", "admissions_pending", "admissions_received")})   # applications name a course, not always a batch
        self.assertEqual(self.dash("teacher_id=%d" % self.t1)["pending_grading"], 2)

    def test_04_date_range(self):
        d = self.dash("date_from=2027-03-02&date_to=2027-03-05")
        self.assertEqual(self.pick(d, "classes_held", "classes_cancelled", "classes_upcoming", "assignments", "tests", "submissions", "graded", "pending_grading", "tutorials", "admissions_received", "admissions_pending"),
                         {"classes_held": 2, "classes_cancelled": 1, "classes_upcoming": 0, "assignments": 2, "tests": 0, "submissions": 2, "graded": 0, "pending_grading": 2, "tutorials": 3, "admissions_received": 3, "admissions_pending": 2})
        self.assertEqual(self.dash("date_from=2027-03-06&date_to=2027-03-09")["tests"], 1)
        self.assertEqual(self.dash("date_from=2028-01-01")["assignments"], 0)

    def test_05_money_follows_the_same_filters(self):
        d = self.dash(H=self.F)["financial"]
        self.assertEqual(d, {"revenue": 1100, "expenses": 200, "net": 900, "outstanding": d["outstanding"], "teacher_earnings": 0, "academy_revenue": 0})   # Session 31 added the last two
        self.assertEqual(d["outstanding"], 2500)                                         # s1 owes 500, s2 owes 1000, s3 nothing, and dropped s4 still owes the invoice raised before leaving
        self.assertEqual(self.sql_one("SELECT SUM(amount_due_mvr-waived_mvr-paid_mvr) FROM invoices WHERE status<>'void'"), 2500)
        self.assertEqual(self.dash("kind=tuition", H=self.F)["financial"]["revenue"], 600)
        self.assertEqual(self.dash("course_id=%d" % self.ar, H=self.F)["financial"]["outstanding"], 2500)
        self.assertEqual(self.dash("teacher_id=%d" % self.t2, H=self.F)["financial"]["revenue"], 600)
        self.assertEqual(self.dash("date_from=2027-03-05", H=self.F)["financial"]["revenue"], 600)          # the 500 was paid on the 4th
        self.assertEqual(self.dash("date_to=2027-03-02", H=self.F)["financial"]["expenses"], 0)

    def test_06_same_numbers_as_the_teacher_dashboard(self):
        t = self.c.get("/api/teacher/dashboard", headers=self.T1).get_json()
        d = self.dash("teacher_id=%d" % self.t1)
        self.assertEqual((t["classes"]["held"], t["assignments"]["pending_grading"], t["assignments"]["submissions"], t["assignments"]["graded"], t["assignments"]["given"], t["assignments"]["tests"]),
                         (d["classes_held"], d["pending_grading"], d["submissions"], d["graded"], d["assignments"], d["tests"]))
        self.assertEqual((t["classes"]["upcoming"], t["students"]), (d["classes_upcoming"], d["students"]))

    def test_07_permissions_and_validation(self):
        self.assertEqual(self.c.get("/api/admin/dashboard").status_code, 401)
        for who in (self.T1, self.ST): self.assertEqual(self.c.get("/api/admin/dashboard", headers=who).status_code, 403)
        self.assertNotIn("financial", self.dash(H=self.NO)); self.assertNotIn("fees", self.dash(H=self.NO))
        self.assertIn("financial", self.dash(H=self.F)); self.assertNotIn("fees", self.dash(H=self.F))
        self.assertIn("fees", self.dash(H=self.FE)); self.assertNotIn("financial", self.dash(H=self.FE))
        full = self.dash(); self.assertIn("financial", full); self.assertIn("fees", full)
        self.assertEqual({"courses", "batches", "teachers"}, set(self.dash(H=self.NO)["options"]))        # dropdowns need no People permission
        for bad in ("date_from=x", "date_from=2027-03-09&date_to=2027-03-01", "kind=other", "course_id=x", "teacher_id=1.5"):
            self.assertEqual(self.c.get("/api/admin/dashboard?" + bad, headers=self.H).status_code, 400, bad)
        self.assertEqual(self.pick(self.dash("course_id=99999"), "students", "classes_held", "assignments", "tutorials"), {"students": 0, "classes_held": 0, "assignments": 0, "tutorials": 0})

    def test_08_old_dashboard_route_still_answers(self):
        o = self.c.get("/api/dashboard", headers=self.H).get_json()
        for k in ("students", "teachers", "pending_applications", "unpaid_invoices", "month_collection_mvr"): self.assertIn(k, o)


if __name__ == "__main__":
    unittest.main()
