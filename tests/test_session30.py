"""Session 30: teacher earnings from real payments. Hand-counted seed."""
import datetime as dt, os, sqlite3, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PW = "Passw0rd!x1"
MVT = dt.timezone(dt.timedelta(hours=5))


class S30(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s30.test", ADMIN_PASSWORD="AdminPass123")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path}); cls.c = cls.app.test_client()
        cls.app.config["NOW"] = lambda: dt.datetime(2027, 3, 20, 12, 0, tzinfo=MVT)
        cls.H = cls.tok("admin@s30.test", "AdminPass123")
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, role, **kw: P("/api/users", {"email": e, "password": PW, "full_name": e, "role": role, **kw}).get_json()["id"]
        cls.t1, cls.t2 = mk("t1@s30.test", "teacher"), mk("t2@s30.test", "teacher")
        cls.st = [mk(f"s{i}@s30.test", "student") for i in range(1, 6)]
        cls.fin = mk("fin@s30.test", "admin", permissions=["finance"]); cls.nofin = mk("nofin@s30.test", "admin", permissions=["fees"])
        ar = P("/api/courses", {"name": "Arabic", "monthly_fee_mvr": 1000, "status": "open"}).get_json()["id"]
        bt = lambda code, t: P("/api/batches", {"course_id": ar, "code": code, "teacher_id": t, "capacity": 9, "days": "Mon", "start_time": "16:00"}).get_json()["id"]
        cls.b1, cls.b2, cls.b3 = bt("A1", cls.t1), bt("A2", cls.t1), bt("A3", cls.t2)
        for s, b in zip(cls.st, (cls.b1, cls.b1, cls.b2, cls.b3, cls.b3)): assert P("/api/enrollments", {"student_id": s, "batch_id": b}).status_code == 201
        inv = lambda s: cls.c.get(f"/api/invoices?student_id={s}", headers=cls.H).get_json()[0]["id"]
        cls.i = [inv(s) for s in cls.st]
        def pay(i, amt, day):
            r = P("/api/payments", {"invoice_id": i, "amount_mvr": amt, "method": "cash", "paid_on": day}); assert r.status_code == 201, r.get_json(); return r.get_json()["payment"]["id"]
        # March: b1 = 1000 + 400 (partial) ; b2 = 1000 ; b3 = 1000 paid then reversed in March (nets 0) + 700
        pay(cls.i[0], 1000, "2027-03-02"); pay(cls.i[1], 400, "2027-03-05"); pay(cls.i[2], 1000, "2027-03-06")
        gone = pay(cls.i[3], 1000, "2027-03-07"); assert P(f"/api/payments/{gone}/reverse", {"reason": "twice"}).status_code == 200
        pay(cls.i[4], 700, "2027-03-09")
        cls.F, cls.NF, cls.T, cls.ST = (cls.tok(e, PW) for e in ("fin@s30.test", "nofin@s30.test", "t1@s30.test", "s1@s30.test"))

    @classmethod
    def tok(cls, login, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    def sql(self, q, a=()):
        con = sqlite3.connect(self.path)
        try: r = con.execute(q, a).fetchall(); con.commit(); return r
        finally: con.close()

    def calc(self, month="2027-03", H=None, **kw): return self.c.post("/api/earnings/calculate", json={"month": month, **kw}, headers=self.H if H is None else H)
    def row(self, b): return {r["batch_id"]: r for r in self.c.get("/api/earnings?month=2027-03", headers=self.H).get_json()["items"]}[b]

    def test_01_default_split_ten_thousand(self):
        self.assertEqual(__import__("earnings").split(10000, 50), (5000, 5000))
        self.assertEqual(__import__("earnings").split(-301, 50), (-150, -151))

    def test_02_partial_reversed_and_multi_batch(self):
        r = self.calc(); self.assertEqual(r.status_code, 200, r.get_json())
        j = r.get_json(); self.assertEqual(j["share_percent"], 50)
        self.assertEqual((self.row(self.b1)["collected_mvr"], self.row(self.b1)["teacher_share_mvr"], self.row(self.b1)["academy_share_mvr"]), (1400, 700, 700))   # full + partial
        self.assertEqual(self.row(self.b2)["collected_mvr"], 1000)
        self.assertEqual((self.row(self.b3)["collected_mvr"], self.row(self.b3)["teacher_share_mvr"]), (700, 350))                                            # reversed 1000 nets to zero
        by = {t["teacher_id"]: t for t in j["by_teacher"]}
        self.assertEqual((by[self.t1]["collected_mvr"], by[self.t1]["teacher_share_mvr"], by[self.t1]["batches"]), (2400, 1200, 2))                         # two batches rolled up
        self.assertEqual((by[self.t2]["teacher_share_mvr"]), 350)
        self.assertEqual(j["totals"], {"collected_mvr": 3100, "teacher_share_mvr": 1550, "academy_share_mvr": 1550})
        self.assertEqual(self.sql("SELECT SUM(amount_mvr) FROM payments WHERE reversed_at IS NULL AND paid_on LIKE '2027-03%'")[0][0], 3100)

    def test_03_rerun_updates_and_does_not_duplicate(self):
        self.calc(); self.assertEqual(self.sql("SELECT COUNT(*) FROM teacher_earnings WHERE period='2027-03'")[0][0], 3)
        self.c.post("/api/payments", json={"invoice_id": self.i[1], "amount_mvr": 100, "method": "cash", "paid_on": "2027-03-12"}, headers=self.H)
        self.calc(); self.assertEqual(self.sql("SELECT COUNT(*) FROM teacher_earnings WHERE period='2027-03'")[0][0], 3)
        self.assertEqual(self.row(self.b1)["collected_mvr"], 1500)

    def test_04_dry_run_writes_nothing_and_percent_setting(self):
        n = self.sql("SELECT COUNT(*) FROM teacher_earnings")[0][0]
        r = self.calc("2027-02", dry_run=1).get_json(); self.assertTrue(r["dry_run"]); self.assertEqual(self.sql("SELECT COUNT(*) FROM teacher_earnings")[0][0], n)
        self.assertEqual(self.c.put("/api/settings", json={"revenue_share_percent": "40"}, headers=self.H).status_code, 200)
        r = self.calc(dry_run=1).get_json(); self.assertEqual(r["share_percent"], 40); self.assertEqual(r["totals"]["teacher_share_mvr"], sum(__import__("earnings").split(x["collected_mvr"], 40)[0] for x in r["items"]))
        self.assertEqual(self.row(self.b1)["share_percent"], 50)   # saved rows keep the percent they were calculated with
        self.c.put("/api/settings", json={"revenue_share_percent": "50"}, headers=self.H)

    def test_05_reversal_in_a_later_month_is_a_correction_there(self):
        pid = self.sql("SELECT id FROM payments WHERE invoice_id=? AND paid_on='2027-03-12'", (self.i[1],))[0][0]
        self.assertEqual(self.c.post(f"/api/payments/{pid}/reverse", json={"reason": "x"}, headers=self.H).status_code, 200)   # reversed 'now' = March 20, same month
        self.calc(); self.assertEqual(self.row(self.b1)["collected_mvr"], 1400)
        self.sql("UPDATE payments SET reversed_at='2027-04-03 10:00:00' WHERE id=?", (pid,))
        self.app.config["NOW"] = lambda: dt.datetime(2027, 4, 20, 12, 0, tzinfo=MVT)
        try:
            self.calc("2027-03"); self.assertEqual(self.row(self.b1)["collected_mvr"], 1500)      # March still counts it
            self.calc("2027-04"); a = {r["batch_id"]: r for r in self.c.get("/api/earnings?month=2027-04", headers=self.H).get_json()["items"]}
            self.assertEqual((a[self.b1]["collected_mvr"], a[self.b1]["teacher_share_mvr"]), (-100, -50))   # the correction lands in April
        finally: self.app.config["NOW"] = lambda: dt.datetime(2027, 3, 20, 12, 0, tzinfo=MVT)

    def test_06_void_invoice_excluded(self):
        self.sql("UPDATE invoices SET status='void' WHERE id=?", (self.i[2],))
        self.calc(); self.assertEqual(self.row(self.b2)["collected_mvr"], 0)
        self.sql("UPDATE invoices SET status='paid' WHERE id=?", (self.i[2],))
        self.calc(); self.assertEqual(self.row(self.b2)["collected_mvr"], 1000)

    def test_07_approved_month_is_never_touched(self):
        self.calc(); self.sql("UPDATE teacher_earnings SET status='approved' WHERE period='2027-03'")
        before = self.sql("SELECT batch_id,collected_mvr,teacher_share_mvr FROM teacher_earnings WHERE period='2027-03' ORDER BY batch_id")
        self.c.post("/api/payments", json={"invoice_id": self.i[0], "amount_mvr": 1, "method": "cash", "paid_on": "2027-03-15"}, headers=self.H)
        self.assertEqual(self.calc().status_code, 409)
        self.assertEqual(self.sql("SELECT batch_id,collected_mvr,teacher_share_mvr FROM teacher_earnings WHERE period='2027-03' ORDER BY batch_id"), before)

    def test_08_permissions_and_input(self):
        for H in (self.NF, self.T, self.ST, {}):
            self.assertIn(self.c.get("/api/earnings", headers=H).status_code, (401, 403)); self.assertIn(self.calc(H=H).status_code, (401, 403))
        self.assertEqual(self.c.get("/api/earnings?month=2027-03", headers=self.F).status_code, 200)
        self.assertEqual(self.calc("2027-13").status_code, 400); self.assertEqual(self.calc("2030-01").status_code, 400)
        self.assertEqual(self.c.get("/api/earnings?month=2027-03&teacher_id=x", headers=self.H).status_code, 400)

    def test_09_audit_row(self):
        self.calc("2027-02")
        self.assertTrue(self.sql("SELECT 1 FROM audit_log WHERE action='earnings_calculated'"))

    def test_10_migration_dry_run_then_apply_twice(self):
        import migrate_session30 as m, dbx
        self.sql("DELETE FROM teacher_earnings")   # (March was approved in test_07; the table is emptied so the migration starts clean)
        conn = dbx.connect(self.app.config, ROOT)
        try:
            b, a = m.run(conn, False, log=lambda *_: None, this_month="2027-03"); self.assertEqual(b, 0); self.assertEqual(self.sql("SELECT COUNT(*) FROM teacher_earnings")[0][0], 0)
            m.run(conn, True, log=lambda *_: None, this_month="2027-03"); n = self.sql("SELECT COUNT(*) FROM teacher_earnings")[0][0]; self.assertGreater(n, 0)
            m.run(conn, True, log=lambda *_: None, this_month="2027-03"); self.assertEqual(self.sql("SELECT COUNT(*) FROM teacher_earnings")[0][0], n)
        finally: conn.close()


if __name__ == "__main__":
    unittest.main()
