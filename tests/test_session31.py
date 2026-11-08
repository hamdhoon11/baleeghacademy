"""Session 31: registration fee, approval, teacher payments, report, teacher's own view, dashboards. Hand-counted seed."""
import datetime as dt, os, sqlite3, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PW = "Passw0rd!x1"
MVT = dt.timezone(dt.timedelta(hours=5))
NOW = lambda d: (lambda: dt.datetime(2027, 3, d, 12, 0, tzinfo=MVT))


class S31(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s31.test", ADMIN_PASSWORD="AdminPass123")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path}); cls.c = cls.app.test_client()
        cls.app.config["NOW"] = NOW(10)
        cls.H = cls.tok("admin@s31.test", "AdminPass123")
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, role, **kw: P("/api/users", {"email": e, "password": PW, "full_name": e, "role": role, **kw}).get_json()["id"]
        cls.t1, cls.t2 = mk("t1@s31.test", "teacher"), mk("t2@s31.test", "teacher")
        cls.s1, cls.s2 = mk("s1@s31.test", "student"), mk("s2@s31.test", "student")
        mk("nofin@s31.test", "admin", permissions=["fees"])
        r = P("/api/courses", {"name": "Arabic", "monthly_fee_mvr": 1000, "registration_fee_mvr": 200, "status": "open"}); assert r.status_code == 201, r.get_json()
        cls.ar = r.get_json()["id"]
        bt = lambda code, t: P("/api/batches", {"course_id": cls.ar, "code": code, "teacher_id": t, "capacity": 9, "days": "Mon", "start_time": "16:00"}).get_json()["id"]
        cls.b1, cls.b2 = bt("A1", cls.t1), bt("A2", cls.t2)
        for s, b in ((cls.s1, cls.b1), (cls.s2, cls.b2)): assert P("/api/enrollments", {"student_id": s, "batch_id": b}).status_code == 201
        inv = lambda s: cls.c.get(f"/api/invoices?student_id={s}", headers=cls.H).get_json()
        pay = lambda i, amt, day: P("/api/payments", {"invoice_id": i, "amount_mvr": amt, "method": "cash", "paid_on": day})
        for s in (cls.s1, cls.s2):
            for i in inv(s): assert pay(i["id"], i["amount_due_mvr"], "2027-03-04").status_code == 201   # pays the month AND the registration fee
        cls.NF, cls.T1, cls.T2, cls.ST = (cls.tok(e, PW) for e in ("nofin@s31.test", "t1@s31.test", "t2@s31.test", "s1@s31.test"))

    @classmethod
    def tok(cls, login, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    def sql(self, q, a=()):
        con = sqlite3.connect(self.path)
        try: r = con.execute(q, a).fetchall(); con.commit(); return r
        finally: con.close()

    def inv(self, s): return self.c.get(f"/api/invoices?student_id={s}", headers=self.H).get_json()

    def post(self, p, j=None, H=None): return self.c.post(p, json=j or {}, headers=self.H if H is None else H)
    def get(self, p, H=None): return self.c.get(p, headers=self.H if H is None else H)

    def test_01_registration_invoice_once_and_not_in_earnings(self):
        invs = self.inv(self.s1)
        self.assertEqual(sorted(i["kind"] for i in invs), ["monthly", "registration"])
        reg = [i for i in invs if i["kind"] == "registration"][0]; self.assertEqual((reg["amount_due_mvr"], reg["period"]), (200, "REG-FEE"))
        self.assertEqual(self.sql("SELECT COUNT(*) FROM invoices WHERE student_id=? AND kind='registration'", (self.s1,))[0][0], 1)
        j = self.post("/api/earnings/calculate", {"month": "2027-03"}).get_json()
        self.assertEqual(j["totals"], {"collected_mvr": 2000, "teacher_share_mvr": 1000, "academy_share_mvr": 1000})     # 2 x 1000; the 2 x 200 registration is excluded
        self.assertEqual(self.sql("SELECT SUM(amount_mvr) FROM payments")[0][0], 2400)                                 # but it is real revenue
        self.assertEqual(self.get("/api/finance/revenue").get_json()["total_collected"], 2400)

    def test_02_course_without_registration_fee_unchanged(self):
        r = self.post("/api/courses", {"name": "Plain", "monthly_fee_mvr": 500, "status": "open"}); self.assertEqual(r.status_code, 201)
        self.assertEqual(self.sql("SELECT registration_fee_mvr FROM courses WHERE id=?", (r.get_json()["id"],))[0][0], 0)
        self.assertEqual(self.post("/api/courses", {"name": "Bad", "registration_fee_mvr": -1}).status_code, 400)
        self.assertEqual(self.c.patch(f"/api/courses/{self.ar}", json={"registration_fee_mvr": 200}, headers=self.H).status_code, 200)

    def test_03_transfer_does_not_charge_registration_again(self):
        s3 = self.post("/api/users", {"email": "s3@s31.test", "password": PW, "full_name": "s3", "role": "student"}).get_json()["id"]
        self.assertEqual(self.post("/api/enrollments", {"student_id": s3, "batch_id": self.b1}).status_code, 201)
        eid = self.sql("SELECT id FROM enrollments WHERE student_id=?", (s3,))[0][0]
        self.assertEqual(self.sql("SELECT COUNT(*) FROM invoices WHERE student_id=? AND kind='registration'", (s3,))[0][0], 1)
        self.assertEqual(self.c.patch(f"/api/enrollments/{eid}", json={"transfer_to_batch_id": self.b2}, headers=self.H).status_code, 200)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM invoices WHERE student_id=? AND kind='registration'", (s3,))[0][0], 1)
        self.sql("UPDATE invoices SET status='void' WHERE student_id=?", (s3,))   # s3 never paid; keep March figures to the two paying students

    def test_04_approve_rules(self):
        self.assertEqual(self.post("/api/earnings/approve", {"month": "2027-03"}).status_code, 400)     # March is not over yet
        self.app.config["NOW"] = NOW(28); self.app.config["NOW"] = lambda: dt.datetime(2027, 4, 5, 12, 0, tzinfo=MVT)
        self.post("/api/earnings/calculate", {"month": "2027-03"})
        r = self.post("/api/earnings/approve", {"month": "2027-03", "expected_teacher_total": 1}); self.assertEqual(r.status_code, 409)   # figures differ from what was reviewed
        tot = self.get("/api/earnings?month=2027-03").get_json()["totals"]["teacher_share_mvr"]
        r = self.post("/api/earnings/approve", {"month": "2027-03", "expected_teacher_total": tot}); self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(self.sql("SELECT COUNT(DISTINCT status) FROM teacher_earnings WHERE period='2027-03'")[0][0], 1)
        self.assertEqual(self.post("/api/earnings/approve", {"month": "2027-03"}).status_code, 409)
        self.assertEqual(self.post("/api/earnings/calculate", {"month": "2027-03"}).status_code, 409)
        self.assertEqual(self.post("/api/earnings/approve", {"month": "2027-02"}).status_code, 400)     # nothing collected in February

    def test_05_payments_to_teachers(self):
        tt = {t["teacher_id"]: t for t in self.get("/api/earnings/teachers").get_json()["items"]}
        self.assertEqual((tt[self.t1]["earned_mvr"], tt[self.t2]["earned_mvr"]), (500, 500))   # one paying student in each teacher's batch
        self.assertEqual(self.post("/api/earnings/payments", {"teacher_id": self.t1, "amount_mvr": 600, "method": "cash"}).status_code, 409)   # more than owed
        r = self.post("/api/earnings/payments", {"teacher_id": self.t1, "amount_mvr": 200, "method": "bank_transfer", "reference": "TX1"}); self.assertEqual(r.status_code, 201); pid = r.get_json()["id"]
        self.assertEqual(r.get_json()["outstanding_mvr"], 300)
        self.assertEqual(self.post("/api/earnings/payments", {"teacher_id": self.t1, "amount_mvr": 5, "method": "gold"}).status_code, 400)
        self.assertEqual(self.post(f"/api/earnings/payments/{pid}/void", {}).status_code, 400)       # a reason is needed
        self.assertEqual(self.post(f"/api/earnings/payments/{pid}/void", {"reason": "typo"}).status_code, 200)
        self.assertEqual({t["teacher_id"]: t for t in self.get("/api/earnings/teachers").get_json()["items"]}[self.t1]["outstanding_mvr"], 500)
        self.post("/api/earnings/payments", {"teacher_id": self.t1, "amount_mvr": 200, "method": "cash"})

    def test_06_teacher_sees_only_own_approved(self):
        r = self.get("/api/my/earnings", self.T1).get_json()
        self.assertEqual((r["earned_mvr"], r["paid_mvr"], r["outstanding_mvr"], len(r["items"])), (500, 200, 300, 1))
        self.assertNotIn("academy_share_mvr", r["items"][0])
        self.assertEqual(self.get("/api/my/earnings", self.T2).get_json()["paid_mvr"], 0)
        self.sql("UPDATE teacher_earnings SET status='draft' WHERE period='2027-03'")      # a draft is never shown to a teacher
        self.assertEqual(self.get("/api/my/earnings", self.T1).get_json()["items"], []); self.sql("UPDATE teacher_earnings SET status='approved' WHERE period='2027-03'")
        self.assertEqual(self.c.put("/api/settings", json={"teachers_see_earnings": "0"}, headers=self.H).status_code, 200)
        self.assertEqual(self.get("/api/my/earnings", self.T1).status_code, 403)
        self.c.put("/api/settings", json={"teachers_see_earnings": "1"}, headers=self.H)
        self.assertEqual(self.get("/api/my/earnings", self.ST).status_code, 403)

    def test_07_report_csv_xlsx_and_dashboards(self):
        r = self.get("/api/earnings/report?from=2027-03&to=2027-03").get_json(); self.assertEqual(r["totals"]["teacher_share_mvr"], 1000)
        csv = self.get("/api/earnings/report.csv?from=2027-03&to=2027-03"); self.assertEqual(csv.status_code, 200); self.assertIn("teacher_share_mvr", csv.get_data(as_text=True))
        x = self.get("/api/earnings/report.xlsx?from=2027-03&to=2027-03"); self.assertEqual(x.status_code, 200); self.assertTrue(x.data[:2] == b"PK")
        self.assertEqual(self.get("/api/earnings/report?from=bad").status_code, 400)
        d = self.get("/api/finance/dashboard?date_from=2027-03-01&date_to=2027-04-30").get_json()
        self.assertEqual((d["teacher_earnings"], d["academy_revenue"], d["teacher_paid"], d["revenue"]), (1000, 1000, 200, 2400))
        a = self.get("/api/admin/dashboard?date_from=2027-03-01&date_to=2027-04-30")
        if a.status_code == 200: self.assertEqual(a.get_json()["financial"]["teacher_earnings"], 1000)

    def test_08_permissions_and_log(self):
        for p in ("/api/earnings/teachers", "/api/earnings/payments", "/api/earnings/report", "/api/earnings/report.csv"):
            for H in (self.NF, self.T1, self.ST, {}): self.assertIn(self.get(p, H).status_code, (401, 403), p)
        for p in ("/api/earnings/approve", "/api/earnings/payments"):
            for H in (self.NF, self.T1, {}): self.assertIn(self.post(p, {}, H).status_code, (401, 403), p)
        for act in ("earnings_approved", "teacher_payment", "teacher_payment_void", "export_teacher_earnings"):
            self.assertTrue(self.sql("SELECT 1 FROM audit_log WHERE action=?", (act,)), act)


if __name__ == "__main__":
    unittest.main()
