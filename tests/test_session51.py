"""v0.8.51: teacher earnings by FEE month; the current month can be approved (pay day around the 15th); fees for an approved month collected
later become late (accrued) rows; a salary entered as an expense is also a payment to the teacher (and the other way round)."""
import datetime as dt, os, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MVT = dt.timezone(dt.timedelta(hours=5))
PW = "Password123"


class S51(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        old = os.environ.get("SEED_DEMO")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s51.test", ADMIN_PASSWORD="AdminPass123", SEED_DEMO="0")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path}); cls.c = cls.app.test_client()
        cls.clock = [dt.datetime(2026, 11, 15, 10, 0, tzinfo=MVT)]
        cls.app.config["NOW"] = lambda: cls.clock[0]
        cls.H = {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": "admin@s51.test", "password": "AdminPass123"}).get_json()["token"]}
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, role: P("/api/users", {"email": e, "password": PW, "full_name": e.split("@")[0].title(), "role": role, "phone": "7771234"}).get_json()["id"]
        cls.t1 = mk("t1@s51.test", "teacher")
        cls.s = [mk(f"s{i}@s51.test", "student") for i in range(3)]
        co = P("/api/courses", {"name": "Arabic", "monthly_fee_mvr": 1000, "status": "open"}).get_json()["id"]
        cls.b1 = P("/api/batches", {"course_id": co, "code": "A1", "teacher_id": cls.t1, "capacity": 9, "days": "Mon", "start_time": "16:00"}).get_json()["id"]
        for sid in cls.s: assert P("/api/enrollments", {"student_id": sid, "batch_id": cls.b1, "start_date": "2026-10-01"}).status_code == 201

    def sql(self, q, a=()):
        con = sqlite3.connect(self.path)
        try: r = con.execute(q, a).fetchall(); con.commit(); return r
        finally: con.close()

    def inv(self, sid, period): return self.sql("SELECT id FROM invoices WHERE student_id=? AND period=?", (sid, period))[0][0]
    def pay(self, sid, period, day, amt=1000):
        r = self.c.post("/api/payments", json={"invoice_id": self.inv(sid, period), "amount_mvr": amt, "method": "cash", "paid_on": day}, headers=self.H); assert r.status_code == 201, r.get_json()
    def calc(self, m): return self.c.post("/api/earnings/calculate", json={"month": m}, headers=self.H).get_json()
    def month(self, m): return self.c.get(f"/api/earnings?month={m}", headers=self.H).get_json()
    def owed(self): return {t["teacher_id"]: t for t in self.c.get("/api/earnings/teachers", headers=self.H).get_json()["items"]}.get(self.t1)

    def test_01_by_fee_month_whatever_day_it_was_entered(self):
        # October fees of two students, entered in November: they count for OCTOBER
        self.pay(self.s[0], "2026-10", "2026-11-10"); self.pay(self.s[1], "2026-10", "2026-11-12")
        j = self.calc("2026-10")
        self.assertEqual((j["mode"], j["totals"]["collected_mvr"], j["totals"]["teacher_share_mvr"]), ("month", 2000, 1000))
        self.assertEqual(self.calc("2026-11")["totals"]["collected_mvr"], 0)   # nothing for November's fees yet

    def test_02_pay_day_approve_then_late_collection_is_accrued(self):
        self.pay(self.s[0], "2026-11", "2026-11-05"); self.pay(self.s[1], "2026-11", "2026-11-14")
        self.calc("2026-11")
        tot = self.month("2026-11")["totals"]["teacher_share_mvr"]
        r = self.c.post("/api/earnings/approve", json={"month": "2026-11", "expected_teacher_total": tot}, headers=self.H)   # the 15th: the running month
        self.assertEqual(r.status_code, 200, r.get_json()); self.assertEqual(r.get_json()["teacher_total"], 1000)
        # the third student pays November after pay day
        self.clock[0] = dt.datetime(2026, 11, 22, 10, 0, tzinfo=MVT)
        self.pay(self.s[2], "2026-11", "2026-11-22")
        self.assertEqual(self.month("2026-11")["late_not_calculated"], 1000)   # the screen says so
        j = self.calc("2026-11")
        self.assertEqual(j["mode"], "late"); self.assertIn("after approval", " ".join(j["why"]))
        late = [x for x in self.month("2026-11")["items"] if x["late"]]
        self.assertEqual([(x["collected_mvr"], x["teacher_share_mvr"], x["status"], x["booked_month"]) for x in late], [(1000, 500, "draft", "2026-11")])
        self.assertEqual(self.sql("SELECT collected_mvr, status FROM teacher_earnings WHERE period='2026-11' AND seq=0"), [(2000, "approved")])   # untouched
        self.assertEqual(self.calc("2026-11")["count"], 1)   # calculating again replaces the draft, never doubles it
        self.assertEqual(self.sql("SELECT COUNT(*) FROM teacher_earnings WHERE period='2026-11' AND seq>0")[0][0], 1)
        before = self.owed()["earned_mvr"]
        tot = self.month("2026-11")["totals"]["teacher_share_mvr"]
        r = self.c.post("/api/earnings/approve", json={"month": "2026-11", "expected_teacher_total": tot}, headers=self.H)
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(self.owed()["earned_mvr"] - before, 500)   # the late share is now payable
        self.assertEqual(self.month("2026-11")["late_not_calculated"], 0)
        self.assertEqual(self.c.post("/api/earnings/approve", json={"month": "2026-11"}, headers=self.H).status_code, 409)   # nothing new
        self.assertEqual(self.calc("2026-11")["count"], 0)
        rep = self.c.get("/api/earnings/report?from=2026-11&to=2026-11", headers=self.H).get_json()["items"]
        self.assertTrue(any("collected late" in x["status"] for x in rep))
        self.assertEqual(self.c.post("/api/earnings/approve", json={"month": "2026-12"}, headers=self.H).status_code, 400)   # not started

    def test_03_salary_expense_is_a_teacher_payment(self):
        kid = self.c.post("/api/expense-categories", json={"name": "Staff salary"}, headers=self.H).get_json()["id"]
        o0 = self.owed()["outstanding_mvr"]
        r = self.c.post("/api/expenses", json={"expense_date": "2026-11-15", "amount_mvr": 400, "category_id": kid, "description": "Nov salary", "teacher_id": self.t1}, headers=self.H)
        self.assertEqual(r.status_code, 201, r.get_json()); eid = r.get_json()["id"]
        self.assertEqual(self.owed()["outstanding_mvr"], o0 - 400)
        tp = self.sql("SELECT amount_mvr, paid_on, voided_at FROM teacher_payments WHERE expense_id=?", (eid,))
        self.assertEqual(tp, [(400, "2026-11-15", None)])
        self.assertEqual(self.c.patch(f"/api/expenses/{eid}", json={"amount_mvr": 450}, headers=self.H).status_code, 200)
        self.assertEqual(self.sql("SELECT amount_mvr FROM teacher_payments WHERE expense_id=? AND voided_at IS NULL", (eid,)), [(450,)])
        self.assertEqual(self.c.patch(f"/api/expenses/{eid}", json={"teacher_id": ""}, headers=self.H).status_code, 200)   # not a salary after all
        self.assertEqual(self.sql("SELECT COUNT(*) FROM teacher_payments WHERE expense_id=? AND voided_at IS NULL", (eid,))[0][0], 0)
        self.assertEqual(self.owed()["outstanding_mvr"], o0)
        self.c.patch(f"/api/expenses/{eid}", json={"teacher_id": self.t1}, headers=self.H)
        self.assertEqual(self.owed()["outstanding_mvr"], o0 - 450)
        self.assertEqual(self.c.delete(f"/api/expenses/{eid}", headers=self.H).status_code, 200)
        self.assertEqual(self.owed()["outstanding_mvr"], o0)
        self.assertEqual(self.c.post("/api/expenses", json={"expense_date": "2026-11-15", "amount_mvr": 1, "category_id": kid, "teacher_id": 999999}, headers=self.H).status_code, 400)

    def test_04_payment_on_earnings_screen_is_an_expense(self):
        o0 = self.owed()["outstanding_mvr"]
        r = self.c.post("/api/earnings/payments", json={"teacher_id": self.t1, "amount_mvr": 300, "method": "bank_transfer", "paid_on": "2026-11-15"}, headers=self.H)
        self.assertEqual(r.status_code, 201, r.get_json()); pid = r.get_json()["id"]
        e = self.sql("SELECT e.amount_mvr, k.name, e.teacher_id FROM expenses e JOIN expense_categories k ON k.id=e.category_id JOIN teacher_payments p ON p.expense_id=e.id WHERE p.id=?", (pid,))
        self.assertEqual(e, [(300, "Teacher salaries", self.t1)])
        self.assertEqual(self.owed()["outstanding_mvr"], o0 - 300)
        self.assertEqual(self.c.post(f"/api/earnings/payments/{pid}/void", json={"reason": "wrong"}, headers=self.H).status_code, 200)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM expenses e JOIN teacher_payments p ON p.expense_id=e.id WHERE p.id=?", (pid,))[0][0], 0)
        self.assertEqual(self.owed()["outstanding_mvr"], o0)


if __name__ == "__main__":
    unittest.main()
