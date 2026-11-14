"""v0.8.53: Fees -> Record payment, fee status grid: each student's fee for each month, batch by batch."""
import datetime as dt, os, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MVT = dt.timezone(dt.timedelta(hours=5)); PW = "Password123"


class S53(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        old = os.environ.get("SEED_DEMO")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s53.test", ADMIN_PASSWORD="AdminPass123", SEED_DEMO="0")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path}); cls.c = cls.app.test_client()
        cls.app.config["NOW"] = lambda: dt.datetime(2026, 11, 14, 10, 0, tzinfo=MVT)
        cls.H = {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": "admin@s53.test", "password": "AdminPass123"}).get_json()["token"]}
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, n, role="student": P("/api/users", {"email": e, "password": PW, "full_name": n, "role": role, "phone": "7771234"}).get_json()["id"]
        t1 = mk("t1@s53.test", "Teacher", "teacher")
        cls.s = [mk(f"s{i}@s53.test", n) for i, n in enumerate(["Aisha", "Ibrahim", "Mariyam"])]
        co = P("/api/courses", {"name": "Arabic", "monthly_fee_mvr": 500, "status": "open"}).get_json()["id"]
        cls.b1 = P("/api/batches", {"course_id": co, "code": "A1", "teacher_id": t1, "capacity": 9, "days": "Mon", "start_time": "16:00"}).get_json()["id"]
        cls.b2 = P("/api/batches", {"course_id": co, "code": "A2", "teacher_id": t1, "capacity": 9, "days": "Tue", "start_time": "16:00"}).get_json()["id"]
        for sid, b in zip(cls.s, (cls.b1, cls.b1, cls.b2)): assert P("/api/enrollments", {"student_id": sid, "batch_id": b, "start_date": "2026-09-01"}).status_code == 201
        inv = lambda sid, m: cls.sql_("SELECT id FROM invoices WHERE student_id=? AND period=?", (sid, m))[0][0]
        P("/api/payments", {"invoice_id": inv(cls.s[0], "2026-09"), "amount_mvr": 500, "method": "cash", "paid_on": "2026-11-01"})
        P("/api/payments", {"invoice_id": inv(cls.s[0], "2026-10"), "amount_mvr": 200, "method": "cash", "paid_on": "2026-11-02"})

    @classmethod
    def sql_(cls, q, a=()):
        con = sqlite3.connect(cls.path)
        try: r = con.execute(q, a).fetchall(); con.commit(); return r
        finally: con.close()

    def test_01_grid(self):
        r = self.c.get("/api/fees/status-grid?months=3", headers=self.H)
        self.assertEqual(r.status_code, 200, r.get_json()); j = r.get_json()
        self.assertEqual(j["months"], ["2026-09", "2026-10", "2026-11"])
        b = {x["batch_id"]: x for x in j["batches"]}
        a1 = {p["name"]: p["cells"] for p in b[self.b1]["students"]}
        self.assertEqual((a1["Aisha"]["2026-09"]["status"], a1["Aisha"]["2026-09"]["paid_on"]), ("paid", "2026-11-01"))
        self.assertEqual((a1["Aisha"]["2026-10"]["status"], a1["Aisha"]["2026-10"]["balance"]), ("partial", 300))
        self.assertEqual(a1["Ibrahim"]["2026-09"]["status"], "overdue")
        self.assertEqual(b[self.b1]["months"]["2026-09"], {"due": 1000, "collected": 500, "outstanding": 500})
        self.assertEqual([p["name"] for p in b[self.b2]["students"]], ["Mariyam"])

    def test_02_filters_and_rights(self):
        j = self.c.get(f"/api/fees/status-grid?end=2026-10&months=1&batch_id={self.b2}", headers=self.H).get_json()
        self.assertEqual((j["months"], [x["batch_id"] for x in j["batches"]]), (["2026-10"], [self.b2]))
        j = self.c.get("/api/fees/status-grid?q=ibra", headers=self.H).get_json()
        self.assertEqual([p["name"] for b in j["batches"] for p in b["students"]], ["Ibrahim"])
        self.assertEqual(self.c.get("/api/fees/status-grid?end=bad", headers=self.H).status_code, 400)
        self.assertEqual(self.c.get("/api/fees/status-grid").status_code, 401)


if __name__ == "__main__":
    unittest.main()
