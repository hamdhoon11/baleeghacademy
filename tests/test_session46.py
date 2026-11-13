"""v0.8.46: hand-made invoices and revenue types in the reports (Fees report, Payment report, student history, student
information); a dropped student still sees and pays their fees. Set-up as v0.8.45: manual invoices (a student, or a customer who is not in the portal), revenue types, editing invoice amounts,
revenue by type; and the upgrade of an older database (NOT NULL loosened, no row changed)."""
import datetime as dt, io, os, re, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MVT = dt.timezone(dt.timedelta(hours=5))
PW = "Password123"
PNG = b"\x89PNG\r\n\x1a\n" + b"whatsapp" * 40


class Reports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        old = os.environ.get("SEED_DEMO")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s46.test", ADMIN_PASSWORD="AdminPass123", SEED_DEMO="0")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path}); cls.c = cls.app.test_client()
        cls.app.config["NOW"] = lambda: dt.datetime(2026, 11, 13, 17, 0, tzinfo=MVT)
        cls.H = cls.tok("admin@s46.test", "AdminPass123")
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, role: P("/api/users", {"email": e, "password": PW, "full_name": e.split("@")[0].title(), "role": role}).get_json()["id"]
        cls.t1, cls.s1, cls.s2 = mk("t1@s46.test", "teacher"), mk("s1@s46.test", "student"), mk("s2@s46.test", "student")
        cls.sql_("UPDATE users SET must_change_password=0")
        cls.course = P("/api/courses", {"name": "Arabic", "monthly_fee_mvr": 500, "status": "open"}).get_json()["id"]
        cls.b1 = P("/api/batches", {"course_id": cls.course, "code": "A1", "teacher_id": cls.t1, "capacity": 9, "days": "Wed", "start_time": "16:00"}).get_json()["id"]
        cls.b2 = P("/api/batches", {"course_id": cls.course, "code": "A2", "teacher_id": cls.t1, "capacity": 9, "days": "Thu", "start_time": "16:00"}).get_json()["id"]
        P("/api/enrollments", {"student_id": cls.s1, "batch_id": cls.b1})
        cls.S1, cls.T1 = cls.tok("s1@s46.test", PW), cls.tok("t1@s46.test", PW)
        cls.types = {r["code"] or r["name"]: r["id"] for r in cls.c.get("/api/revenue-types", headers=cls.H).get_json()}

    @classmethod
    def tok(cls, login, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    @classmethod
    def sql_(cls, q, a=()):
        con = sqlite3.connect(cls.path)
        try: r = con.execute(q, a).fetchall(); con.commit(); return r
        finally: con.close()

    def manual(self, data):
        r = self.c.post("/api/invoices/manual", json=data, headers=self.H); self.assertEqual(r.status_code, 201, r.get_json()); return r.get_json()["invoice"]

    def test_01_reports_show_manual_invoices(self):
        books = self.c.post("/api/revenue-types", json={"name": "Books"}, headers=self.H).get_json()["id"]
        w = self.manual({"customer_name": "Walk-in Ali", "revenue_type_id": books, "amount_mvr": 150, "invoice_date": "2026-11-02", "description": "Workbook"})
        s = self.manual({"student_id": self.s1, "batch_id": self.b1, "revenue_type_id": self.types["registration"], "amount_mvr": 100, "invoice_date": "2026-11-01",
                         "paid": "1", "method": "cash"})
        # Fees > Report (month)
        r = self.c.get("/api/fees/report?month=2026-11", headers=self.H).get_json()
        by = {x["revenue_type_name"]: (x["invoiced"], x["collected"]) for x in r["by_type"]}
        self.assertEqual(by["Books"], (150, 0)); self.assertEqual(by["Registration fees"], (100, 100)); self.assertEqual(by["Monthly fees"], (500, 0))
        ow = [o for o in r["owing"] if o["id"] == w["id"]][0]
        self.assertEqual((ow["walk_in"], ow["description"], ow["revenue_type_name"]), (True, "Workbook", "Books"))
        x = self.c.get("/api/fees/report.csv?month=2026-11", headers=self.H).get_data(as_text=True)
        self.assertIn("revenue_type,description", x.splitlines()[0]); self.assertIn("Walk-in Ali", x)
        # Fees > Payment report
        p = self.c.get("/api/fees/payment-report?month=2026-11", headers=self.H).get_json()
        o = {x["invoice_id"]: x for x in p["other_rows"]}
        self.assertEqual(set(o), {w["id"], s["id"]}); self.assertEqual(p["other_totals"], {"invoices": 2, "due": 250, "paid": 100, "balance": 150})
        self.assertEqual((o[w["id"]]["walk_in"], o[w["id"]]["status"], o[s["id"]]["status"]), (True, "unpaid", "paid"))
        self.assertEqual([x["invoice_id"] for x in self.c.get("/api/fees/payment-report?month=2026-11&status=paid", headers=self.H).get_json()["other_rows"]], [s["id"]])
        self.assertEqual([x["invoice_id"] for x in self.c.get(f"/api/fees/payment-report?month=2026-11&batch_id={self.b1}", headers=self.H).get_json()["other_rows"]], [s["id"]])
        self.assertEqual(self.c.get("/api/fees/payment-report?month=2026-10", headers=self.H).get_json()["other_rows"], [])
        csv_ = self.c.get("/api/fees/payment-report.csv?month=2026-11", headers=self.H).get_data(as_text=True)
        self.assertIn("Walk-in Ali (not in the portal)", csv_); self.assertIn("Workbook", csv_)
        self.assertEqual(self.c.get("/api/fees/payment-report.xlsx?month=2026-11", headers=self.H).status_code, 200)
        # student history and student information
        h = self.c.get(f"/api/fees/student-history/{self.s1}", headers=self.H).get_json()
        hi = [i for i in h["invoices"] if i["id"] == s["id"]][0]
        self.assertEqual((hi["kind"], hi["revenue_type_name"], hi["description"]), ("manual", "Registration fees", "Registration fees"))
        si = self.c.get(f"/api/student-information/{self.s1}", headers=self.H).get_json()["fees"]["invoices"]
        self.assertIn("Registration fees", [i["description"] for i in si])
        # Finance and the Dashboard
        rev = self.c.get("/api/finance/revenue?date_from=2026-11-01&date_to=2026-11-30", headers=self.H).get_json()
        self.assertIn("Registration fees", [x["revenue_type_name"] for x in rev["by_type"]])
        self.assertEqual(rev["outstanding"], 500 + 150)
        self.assertEqual(self.c.get("/api/finance/dashboard", headers=self.H).get_json()["outstanding_fees"], 650)

    def test_02_dropped_student_still_sees_and_pays_fees(self):
        e = [x for x in self.c.get("/api/enrollments", headers=self.H).get_json() if x["student_id"] == self.s1][0]
        self.c.post(f"/api/enrollments/{e['id']}/start-date", json={"start_date": "2026-09-01"}, headers=self.H)
        r = self.c.patch(f"/api/enrollments/{e['id']}", json={"status": "dropped", "reason": "left"}, headers=self.H); self.assertEqual(r.status_code, 200)
        me = self.c.get("/api/auth/me", headers=self.S1).get_json()
        self.assertIn("fees", me.get("tabs") or me["user"]["tabs"])
        f = self.c.get("/api/my/fees", headers=self.S1).get_json()
        open_ = [i for i in f["invoices"] if i["balance"] > 0]
        self.assertEqual(sorted(i["period"] for i in open_ if i["kind"] == "monthly"), ["2026-09", "2026-10", "2026-11"])
        self.assertEqual(sum(i["balance"] for i in open_), 1500)
        sep = [i for i in open_ if i["period"] == "2026-09"][0]
        r = self.c.post(f"/api/invoices/{sep['id']}/slips", data={"amount_mvr": "500", "transfer_date": "2026-11-10", "file": (io.BytesIO(PNG), "s.png")},
                        headers=self.S1, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 201, r.get_json())
        self.assertEqual(self.c.get("/api/my/fees/statement.pdf", headers=self.S1).status_code, 200)
        oct_ = [i for i in open_ if i["period"] == "2026-10"][0]
        self.assertIn(oct_["id"], [i["id"] for i in self.c.get("/api/fees/overdue", headers=self.H).get_json()["items"]])   # still chased after the drop


if __name__ == "__main__":
    unittest.main()
