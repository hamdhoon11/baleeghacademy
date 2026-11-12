"""v0.8.40: teacher earnings on the hosted (PostgreSQL) database.

Calculate and Approve answered "Something went wrong on the server" on PostgreSQL only: earnings.py turned each database row into a
tuple with tuple(row), and on PostgreSQL a row is a dict, so the tuple held the column NAMES ('batch_id', 'sum') instead of the values.
On SQLite (the tests, a local copy) tuple(row) gives the values, so nothing showed it.

These tests run the whole earnings flow twice: on SQLite rows, and with every row handed over in the PostgreSQL shape (dbx.Row).
No PostgreSQL server is needed.
"""
import datetime as dt, glob, os, re, sqlite3, sys, tempfile, unittest
from unittest import mock
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PW = "Passw0rd!x1"
MVT = dt.timezone(dt.timedelta(hours=5))


def pg_shape(self, r):
    """What dbx.Cur._wrap returns on PostgreSQL: a dbx.Row (a dict that can also be read by position)."""
    import dbx
    return None if r is None else dbx.Row(r.keys(), [dbx._py(v) for v in tuple(r)])


class Earnings40(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        old = os.environ.get("SEED_DEMO")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s40.test", ADMIN_PASSWORD="AdminPass123", SEED_DEMO="0")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path}); cls.c = cls.app.test_client()
        cls.app.config["NOW"] = lambda: dt.datetime(2027, 3, 20, 12, 0, tzinfo=MVT)
        cls.sql_("UPDATE users SET must_change_password=0")
        cls.H = cls.tok("admin@s40.test", "AdminPass123")
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, role: P("/api/users", {"email": e, "password": PW, "full_name": e.split("@")[0], "role": role}).get_json()["id"]
        cls.t1, cls.t2 = mk("t1@s40.test", "teacher"), mk("t2@s40.test", "teacher")
        cls.st = [mk(f"s{i}@s40.test", "student") for i in range(1, 4)]
        cls.sql_("UPDATE users SET must_change_password=0")
        ar = P("/api/courses", {"name": "Arabic", "monthly_fee_mvr": 1000, "status": "open"}).get_json()["id"]
        bt = lambda code, t: P("/api/batches", {"course_id": ar, "code": code, "teacher_id": t, "capacity": 9, "days": "Mon", "start_time": "16:00"}).get_json()["id"]
        cls.b1, cls.b2 = bt("A1", cls.t1), bt("A2", cls.t2)
        for s, b in zip(cls.st, (cls.b1, cls.b1, cls.b2)): assert P("/api/enrollments", {"student_id": s, "batch_id": b}).status_code == 201
        cls.i = [cls.c.get(f"/api/invoices?student_id={s}", headers=cls.H).get_json()[0]["id"] for s in cls.st]
        def pay(i, amt, day):
            r = P("/api/payments", {"invoice_id": i, "amount_mvr": amt, "method": "cash", "paid_on": day}); assert r.status_code == 201, r.get_json(); return r.get_json()["payment"]["id"]
        # February (a finished month): b1 = 600 + 300, b2 = 500.   March (the running month): b1 = 400, b2 = 500 paid and reversed (nets 0)
        pay(cls.i[0], 600, "2027-02-10"); pay(cls.i[1], 300, "2027-02-11"); pay(cls.i[2], 500, "2027-02-12")
        pay(cls.i[0], 400, "2027-03-03")
        gone = pay(cls.i[2], 500, "2027-03-04"); assert P(f"/api/payments/{gone}/reverse", {"reason": "twice"}).status_code == 200
        cls.T1 = cls.tok("t1@s40.test", PW)

    @classmethod
    def tok(cls, login, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    @classmethod
    def sql_(cls, q, a=()):
        con = sqlite3.connect(cls.path)
        try: r = con.execute(q, a).fetchall(); con.commit(); return r
        finally: con.close()

    def as_postgres(self):
        import dbx
        p = mock.patch.object(dbx.Cur, "_wrap", pg_shape); p.start(); self.addCleanup(p.stop)

    def J(self, method, path, h=None, **kw):
        r = getattr(self.c, method)(path, headers=h or self.H, **kw)
        return r.status_code, r.get_json()

    def test_01_values_helper(self):
        import dbx
        row = dbx.Row(["batch_id", "sum"], [7, 900])
        self.assertEqual(tuple(row), ("batch_id", "sum"))        # the trap: the names
        self.assertEqual(dbx.values(row), (7, 900))
        con = sqlite3.connect(":memory:"); con.row_factory = sqlite3.Row
        self.assertEqual(dbx.values(con.execute("SELECT 7 AS batch_id, 900 AS s").fetchone()), (7, 900)); con.close()

    def test_02_preview_and_calculate_on_postgres_rows(self):
        self.as_postgres()
        code, j = self.J("post", "/api/earnings/calculate", json={"month": "2027-03", "dry_run": 1})
        self.assertEqual(code, 200, j)                           # was 500: int('SUM(p.amount_mvr)')
        self.assertEqual(j["totals"], {"collected_mvr": 400, "teacher_share_mvr": 200, "academy_share_mvr": 200})
        self.assertEqual(self.sql_("SELECT COUNT(*) FROM teacher_earnings WHERE period='2027-03'")[0][0], 0)   # a preview saves nothing
        code, j = self.J("post", "/api/earnings/calculate", json={"month": "2027-03"})
        self.assertEqual(code, 200, j)
        rows = {r["batch_id"]: r for r in j["items"]}
        self.assertEqual((rows[self.b1]["collected_mvr"], rows[self.b1]["teacher_share_mvr"], rows[self.b1]["teacher_id"], rows[self.b1]["status"]), (400, 200, self.t1, "draft"))
        self.assertEqual((rows[self.b2]["collected_mvr"], rows[self.b2]["teacher_share_mvr"], rows[self.b2]["teacher_id"]), (0, 0, self.t2))   # paid and reversed in March
        self.assertEqual({t["teacher_id"]: t["teacher_share_mvr"] for t in j["by_teacher"]}, {self.t1: 200, self.t2: 0})
        # a second run updates the same rows; a batch whose payments are all gone is set to 0, not left as it was
        self.sql_("UPDATE teacher_earnings SET collected_mvr=999, teacher_share_mvr=499 WHERE period='2027-03'")
        self.sql_("INSERT INTO teacher_earnings(teacher_id,batch_id,period,collected_mvr,teacher_share_mvr,academy_share_mvr) "
                  "SELECT teacher_id,id,'2027-01',50,25,25 FROM batches WHERE id=?", (self.b1,))
        self.assertEqual(self.J("post", "/api/earnings/calculate", json={"month": "2027-03"})[0], 200)
        self.assertEqual(self.sql_("SELECT batch_id, collected_mvr, teacher_share_mvr FROM teacher_earnings WHERE period='2027-03' ORDER BY batch_id"), [(self.b1, 400, 200), (self.b2, 0, 0)])
        self.assertEqual(self.J("post", "/api/earnings/calculate", json={"month": "2027-01"})[0], 200)
        self.assertEqual(self.sql_("SELECT collected_mvr, teacher_share_mvr FROM teacher_earnings WHERE period='2027-01'"), [(0, 0)])
        self.sql_("DELETE FROM teacher_earnings WHERE period='2027-01'")

    def test_03_show_approve_pay_report_on_postgres_rows(self):
        self.as_postgres()
        code, j = self.J("get", "/api/earnings?month=2027-02")
        self.assertEqual((code, j["items"]), (200, []))          # nothing calculated yet: an empty month, not an error
        code, j = self.J("post", "/api/earnings/approve", json={"month": "2027-03"})
        self.assertEqual(code, 400, j); self.assertIn("after it has ended", j["error"])
        code, j = self.J("post", "/api/earnings/approve", json={"month": "2027-02", "expected_teacher_total": 1})
        self.assertEqual(code, 409, j); self.assertIn("700", j["error"])                       # figures differ from what was on screen
        self.assertEqual(self.sql_("SELECT COUNT(*) FROM teacher_earnings WHERE period='2027-02'")[0][0], 0)
        code, j = self.J("post", "/api/earnings/approve", json={"month": "2027-02"})            # approve recalculates first, then locks
        self.assertEqual(code, 200, j)                           # was 500 on PostgreSQL
        self.assertEqual((j["approved"], j["teacher_total"]), (2, 700))
        self.assertTrue(all(r["status"] == "approved" for r in j["items"]))
        self.assertEqual(self.J("post", "/api/earnings/approve", json={"month": "2027-02"})[0], 409)
        self.assertEqual(self.J("post", "/api/earnings/calculate", json={"month": "2027-02"})[0], 409)   # locked
        code, j = self.J("get", "/api/earnings/teachers")
        owed = {r["teacher_id"]: (r["earned_mvr"], r["paid_mvr"], r["outstanding_mvr"]) for r in j["items"]}
        self.assertEqual(owed, {self.t1: (450, 0, 450), self.t2: (250, 0, 250)})
        self.assertEqual(self.J("post", "/api/earnings/payments", json={"teacher_id": self.t1, "amount_mvr": 451, "method": "cash"})[0], 409)
        code, j = self.J("post", "/api/earnings/payments", json={"teacher_id": self.t1, "amount_mvr": 300, "method": "bank_transfer", "reference": "TR1"})
        self.assertEqual((code, j["outstanding_mvr"]), (201, 150)); pid = j["id"]
        self.assertEqual([p["amount_mvr"] for p in self.J("get", "/api/earnings/payments")[1]], [300])
        code, j = self.J("get", "/api/my/earnings", h=self.T1)
        self.assertEqual((code, j["earned_mvr"], j["paid_mvr"], j["outstanding_mvr"], len(j["items"])), (200, 450, 300, 150, 1))
        self.assertEqual(self.J("post", f"/api/earnings/payments/{pid}/void", json={"reason": "wrong teacher"})[0], 200)
        self.assertEqual(self.J("get", "/api/earnings/teachers")[1]["totals"], {"earned_mvr": 700, "paid_mvr": 0, "outstanding_mvr": 700})
        code, j = self.J("get", "/api/earnings/report?from=2027-02&to=2027-02")
        self.assertEqual((code, j["totals"]), (200, {"collected_mvr": 1400, "teacher_share_mvr": 700, "academy_share_mvr": 700}))
        r = self.c.get("/api/earnings/report.csv?from=2027-02&to=2027-02", headers=self.H)
        self.assertEqual(r.status_code, 200); self.assertIn("2027-02,t1,Arabic,A1,900,50,450,450,approved", r.get_data(as_text=True))
        self.assertEqual(self.c.get("/api/earnings/report.xlsx?from=2027-02&to=2027-02", headers=self.H).status_code, 200)

    def test_04_no_tuple_of_a_database_row_in_the_server_code(self):
        """tuple(row) / list(row) on a database row works on SQLite and silently gives the column names on PostgreSQL. Use dbx.values(row)."""
        bad = []
        for f in sorted(glob.glob(os.path.join(ROOT, "*.py"))):
            if os.path.basename(f) == "dbx.py": continue                    # dbx.values() itself
            for n, line in enumerate(open(f, encoding="utf-8"), 1):
                code = line.split("#")[0]
                if re.search(r"\b(tuple|list)\((r|row|rec)\)", code) and "isinstance" not in code: bad.append(f"{os.path.basename(f)}:{n}")
        self.assertEqual(bad, [])

    def test_05_screen_survives_a_refused_month(self):
        js = open(os.path.join(ROOT, "static/admin.js"), encoding="utf-8").read()
        self.assertIn('api("/earnings?month=" + encodeURIComponent(m)).catch(', js)     # the Finance tab no longer fails as a whole
        self.assertIn('t("fe_empty_hint")', js)
        import json
        self.assertIn("fe_empty_hint", json.load(open(os.path.join(ROOT, "static/i18n/en.json"), encoding="utf-8")))
        code, j = self.J("get", "/api/earnings?month=2031-01")
        self.assertEqual(code, 400); self.assertIn("not started", j["error"])


if __name__ == "__main__":
    unittest.main()
