"""Session 24: revenue from real payments, outstanding, financial dashboard. Hand-counted seed, checked against SQL."""
import datetime as dt, os, sqlite3, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PW = "Passw0rd!x1"
MVT = dt.timezone(dt.timedelta(hours=5))


class S24(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s24.test", ADMIN_PASSWORD="AdminPass123")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path}); cls.c = cls.app.test_client()
        cls.app.config["NOW"] = lambda: dt.datetime(2027, 3, 10, 12, 0, tzinfo=MVT)
        cls.H = cls.tok("admin@s24.test", "AdminPass123")
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, role, **kw: P("/api/users", {"email": e, "password": PW, "full_name": e, "role": role, **kw}).get_json()["id"]
        t = mk("t@s24.test", "teacher"); cls.s1, cls.s2, cls.s3 = (mk(f"s{i}@s24.test", "student") for i in (1, 2, 3))
        cls.fin = mk("fin@s24.test", "admin", permissions=["finance"]); cls.nofin = mk("nofin@s24.test", "admin", permissions=["fees"])
        mk("t2@s24.test", "teacher")
        cls.ar = P("/api/courses", {"name": "Arabic", "monthly_fee_mvr": 1000, "status": "open"}).get_json()["id"]
        cls.tu = P("/api/courses", {"name": "Grade 8 Mathematics", "kind": "tuition", "code": "G8M", "monthly_fee_mvr": 600, "status": "open"}).get_json()["id"]
        bt = lambda cid, code: P("/api/batches", {"course_id": cid, "code": code, "teacher_id": t, "capacity": 9, "days": "Mon", "start_time": "16:00"}).get_json()["id"]
        cls.b1, cls.b2 = bt(cls.ar, "A1"), bt(cls.tu, "M1")
        for s, b in ((cls.s1, cls.b1), (cls.s2, cls.b1), (cls.s3, cls.b2)): P("/api/enrollments", {"student_id": s, "batch_id": b})
        inv = lambda s: cls.c.get(f"/api/invoices?student_id={s}", headers=cls.H).get_json()[0]["id"]
        cls.i1, cls.i2, cls.i3 = inv(cls.s1), inv(cls.s2), inv(cls.s3)
        pay = lambda i, amt, day: P("/api/payments", {"invoice_id": i, "amount_mvr": amt, "method": "cash", "paid_on": day})
        for r in (pay(cls.i1, 400, "2027-03-02"), pay(cls.i1, 300, "2027-03-08"), pay(cls.i2, 250, "2027-03-05"), pay(cls.i3, 600, "2027-03-09")):
            assert r.status_code == 201, r.get_json()
        gone = pay(cls.i2, 1000 - 250, "2027-02-20"); assert gone.status_code == 201, gone.get_json()   # a payment later reversed
        assert P(f"/api/payments/{gone.get_json()['payment']['id']}/reverse", {"reason": "entered twice"}).status_code == 200
        cat = P("/api/expense-categories", {"name": "Rent"}).get_json()["id"]
        for day, amt in (("2027-03-03", 200), ("2027-02-15", 100)):
            r = cls.c.post("/api/expenses", data={"expense_date": day, "amount_mvr": str(amt), "category_id": str(cat)}, headers=cls.H, content_type="multipart/form-data"); assert r.status_code == 201
        cls.F, cls.NF, cls.T, cls.ST = (cls.tok(e, PW) for e in ("fin@s24.test", "nofin@s24.test", "t2@s24.test", "s1@s24.test"))

    @classmethod
    def tok(cls, login, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    def sql(self, q, a=()):
        con = sqlite3.connect(self.path)
        try: return con.execute(q, a).fetchall()
        finally: con.close()

    def rev(self, qs=""): return self.c.get("/api/finance/revenue?" + qs, headers=self.H).get_json()

    def test_01_totals_partial_and_reversed(self):
        r = self.rev()
        self.assertEqual((r["total_collected"], r["payment_count"]), (1550, 4))        # 400+300+250+600; the reversed 750 is not revenue
        self.assertEqual(r["reversed_not_counted"], 750)
        self.assertEqual(r["outstanding"], 1050)                                       # s1 owes 300, s2 owes 750, s3 owes 0
        self.assertEqual(self.sql("SELECT SUM(amount_mvr) FROM payments WHERE reversed_at IS NULL")[0][0], 1550)
        self.assertEqual(self.sql("SELECT SUM(amount_due_mvr-waived_mvr-paid_mvr) FROM invoices")[0][0], 1050)

    def test_02_by_kind_course_batch_month(self):
        r = self.rev()
        self.assertEqual(r["by_kind"], {"course": 950, "tuition": 600})
        self.assertEqual({x["course_name"]: x["collected"] for x in r["by_course"]}, {"Arabic": 950, "Grade 8 Mathematics": 600})
        self.assertEqual({x["batch_code"]: x["collected"] for x in r["by_batch"]}, {"A1": 950, "M1": 600})
        self.assertEqual([(x["month"], x["collected"], x["payments"]) for x in r["by_month"]], [("2027-03", 1550, 4)])   # February has only the reversed payment

    def test_03_filters(self):
        self.assertEqual((self.rev("kind=tuition")["total_collected"], self.rev("kind=tuition")["outstanding"]), (600, 0))
        self.assertEqual((self.rev(f"batch_id={self.b1}")["total_collected"], self.rev(f"batch_id={self.b1}")["outstanding"]), (950, 1050))
        self.assertEqual(self.rev(f"course_id={self.tu}")["total_collected"], 600)
        self.assertEqual(self.rev("date_to=2027-03-05")["total_collected"], 650)       # 400 on the 2nd, 250 on the 5th
        self.assertEqual(self.rev("date_from=2027-03-06&date_to=2027-03-08")["total_collected"], 300)
        self.assertEqual(self.rev("date_from=2027-03-06&date_to=2027-03-08")["by_month"][0]["payments"], 1)
        for bad in ("date_from=nope", "date_from=2027-03-09&date_to=2027-03-01", "kind=other", "course_id=x"):
            self.assertEqual(self.c.get("/api/finance/revenue?" + bad, headers=self.H).status_code, 400, bad)

    def test_04_waived_and_void_are_not_outstanding(self):
        before = self.rev()["outstanding"]
        con = sqlite3.connect(self.path); con.execute("UPDATE invoices SET status='void' WHERE id=?", (self.i2,)); con.commit(); con.close()
        try: self.assertEqual(self.rev()["outstanding"], before - 750)
        finally:
            con = sqlite3.connect(self.path); con.execute("UPDATE invoices SET status='unpaid' WHERE id=?", (self.i2,)); con.commit(); con.close()
        self.assertEqual(self.rev()["outstanding"], before)

    def test_05_dashboard_default_is_this_month(self):
        d = self.c.get("/api/finance/dashboard", headers=self.H).get_json()
        self.assertEqual((d["date_from"], d["date_to"]), ("2027-03-01", "2027-03-10"))
        self.assertEqual((d["revenue"], d["expenses"], d["net"], d["outstanding_fees"]), (1550, 200, 1350, 1050))
        self.assertEqual((d["teacher_earnings"], d["academy_revenue"]), (0, 0))   # Session 31: approved months only; none approved here
        m = {x["month"]: x for x in d["months"]}
        self.assertEqual(len(d["months"]), 12); self.assertEqual(d["months"][-1]["month"], "2027-03"); self.assertEqual(d["months"][0]["month"], "2026-04")
        self.assertEqual((m["2027-03"]["revenue"], m["2027-03"]["expenses"], m["2027-03"]["net"]), (1550, 200, 1350))
        self.assertEqual((m["2027-02"]["revenue"], m["2027-02"]["expenses"], m["2027-02"]["net"]), (0, 100, -100))   # a loss month

    def test_06_dashboard_range_and_loss(self):
        d = self.c.get("/api/finance/dashboard?date_from=2027-02-01&date_to=2027-02-28", headers=self.H).get_json()
        self.assertEqual((d["revenue"], d["expenses"], d["net"]), (0, 100, -100))
        d = self.c.get("/api/finance/dashboard?date_from=2027-02-01&date_to=2027-03-31", headers=self.H).get_json()
        self.assertEqual((d["revenue"], d["expenses"], d["net"]), (1550, 300, 1250))
        self.assertEqual(self.c.get("/api/finance/dashboard?date_from=bad", headers=self.H).status_code, 400)
        # expense totals agree with the expenses list
        self.assertEqual(self.c.get("/api/expenses?date_from=2027-02-01&date_to=2027-03-31", headers=self.H).get_json()["total_mvr"], 300)

    def test_07_reversing_another_payment_updates_revenue(self):
        pid = self.sql("SELECT id FROM payments WHERE invoice_id=? AND amount_mvr=300", (self.i1,))[0][0]
        self.assertEqual(self.c.post(f"/api/payments/{pid}/reverse", json={"reason": "test"}, headers=self.H).status_code, 200)
        r = self.rev(); self.assertEqual((r["total_collected"], r["outstanding"]), (1250, 1350))
        self.assertEqual(self.c.get("/api/finance/dashboard", headers=self.H).get_json()["net"], 1050)

    def test_08_permissions(self):
        for p in ("/api/finance/revenue", "/api/finance/dashboard"):
            self.assertEqual(self.c.get(p).status_code, 401)
            for who in (self.NF, self.T, self.ST): self.assertEqual(self.c.get(p, headers=who).status_code, 403, p)   # NF has fees but not finance
            self.assertEqual(self.c.get(p, headers=self.F).status_code, 200)


if __name__ == "__main__":
    unittest.main()
