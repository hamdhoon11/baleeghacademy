"""v0.8.44: change the start date of enrolments already in the portal (students added this month who began in April).
Based on the v0.8.43 test set-up: the office marks invoices paid with the slip the person sent (WhatsApp etc.), one invoice or several at once;
students who started earlier are billed from their start month; Generate can make a range of months."""
import datetime as dt, io, os, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MVT = dt.timezone(dt.timedelta(hours=5))
PW = "Password123"
PNG = b"\x89PNG\r\n\x1a\n" + b"whatsapp screenshot" * 20


class StartDate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        old = os.environ.get("SEED_DEMO")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s44.test", ADMIN_PASSWORD="AdminPass123", SEED_DEMO="0")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path, "UPLOAD_DIR": os.path.join(tmp, "up")}); cls.c = cls.app.test_client()
        cls.app.config["NOW"] = lambda: dt.datetime(2026, 11, 13, 17, 0, tzinfo=MVT)
        cls.H = cls.tok("admin@s44.test", "AdminPass123")
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, role, **kw: P("/api/users", {"email": e, "password": PW, "full_name": kw.pop("name", e.split("@")[0]), "role": role, **kw}).get_json()["id"]
        cls.t1 = mk("t1@s44.test", "teacher")
        cls.s1, cls.s2, cls.s3 = mk("s1@s44.test", "student"), mk("s2@s44.test", "student"), mk("s3@s44.test", "student")
        cls.sql_("UPDATE users SET must_change_password=0")
        cls.course = P("/api/courses", {"name": "Arabic", "monthly_fee_mvr": 500, "status": "open"}).get_json()["id"]
        cls.b1 = P("/api/batches", {"course_id": cls.course, "code": "A1", "teacher_id": cls.t1, "capacity": 9, "days": "Wed", "start_time": "16:00"}).get_json()["id"]
        cls.S1, cls.T1 = cls.tok("s1@s44.test", PW), cls.tok("t1@s44.test", PW)

    @classmethod
    def tok(cls, login, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    @classmethod
    def sql_(cls, q, a=()):
        con = sqlite3.connect(cls.path)
        try: r = con.execute(q, a).fetchall(); con.commit(); return r
        finally: con.close()

    def invs(self, sid):
        return sorted(self.c.get(f"/api/invoices?student_id={sid}&status=all", headers=self.H).get_json(), key=lambda i: i["period"])

    def paid(self, data, hdr=None, files=None):
        d = dict(data)
        if files: d["file"] = (io.BytesIO(files[1]), files[0])
        return self.c.post("/api/payments/mark-paid", data=d, headers=hdr or self.H, content_type="multipart/form-data")

    def test_01_change_start_bills_the_months_between(self):
        r = self.c.post("/api/enrollments", json={"student_id": self.s1, "batch_id": self.b1}, headers=self.H); eid = r.get_json()["id"]
        self.assertEqual([i["period"] for i in self.invs(self.s1)], ["2026-11"])
        r = self.c.post(f"/api/enrollments/{eid}/start-date", json={"start_date": "2026-04-01"}, headers=self.H)
        self.assertEqual(r.status_code, 200, r.get_json()); self.assertEqual(r.get_json()["earlier_invoices"], 7)
        self.assertEqual(len(self.invs(self.s1)), 8)
        e = [x for x in self.c.get("/api/enrollments", headers=self.H).get_json() if x["id"] == eid][0]
        self.assertEqual(e["enrolled_at"], "2026-03-31 19:00:00")                       # 1 April 00:00 Maldives time
        r = self.c.post(f"/api/enrollments/{eid}/start-date", json={"start_date": "2026-04-01"}, headers=self.H)
        self.assertEqual(r.get_json()["earlier_invoices"], 0)                            # repeating doubles nothing
        self.assertIn("enrollment_start", [a["action"] for a in self.c.get("/api/audit", headers=self.H).get_json()])

    def test_02_later_start_removes_nothing_and_says_so(self):
        eid = [x for x in self.c.get("/api/enrollments", headers=self.H).get_json() if x["student_id"] == self.s1][0]["id"]
        r = self.c.post(f"/api/enrollments/{eid}/start-date", json={"start_date": "2026-06-15"}, headers=self.H)
        self.assertEqual(r.status_code, 200); self.assertEqual(r.get_json()["invoices_before_start"], 2)
        self.assertEqual(len(self.invs(self.s1)), 8)

    def test_03_checks_and_rights(self):
        r = self.c.post("/api/enrollments", json={"student_id": self.s2, "batch_id": self.b1}, headers=self.H); eid = r.get_json()["id"]
        for bad, msg in (("2026-12-01", "future"), ("2024-01-01", "two years"), ("1/4/2026", "look like"), ("", "Choose")):
            r = self.c.post(f"/api/enrollments/{eid}/start-date", json={"start_date": bad}, headers=self.H)
            self.assertEqual(r.status_code, 400); self.assertIn(msg, r.get_json()["error"])
        self.assertEqual(self.c.post("/api/enrollments/99999/start-date", json={"start_date": "2026-04-01"}, headers=self.H).status_code, 404)
        for h in (self.S1, self.T1):
            self.assertEqual(self.c.post(f"/api/enrollments/{eid}/start-date", json={"start_date": "2026-04-01"}, headers=h).status_code, 403)

    def test_04_waitlist_is_not_billed(self):
        eid = [x for x in self.c.get("/api/enrollments", headers=self.H).get_json() if x["student_id"] == self.s2][0]["id"]
        self.sql_("UPDATE enrollments SET status='waitlist' WHERE id=?", (eid,))
        r = self.c.post(f"/api/enrollments/{eid}/start-date", json={"start_date": "2026-04-01"}, headers=self.H)
        self.assertEqual(r.get_json()["earlier_invoices"], 0)


if __name__ == "__main__":
    unittest.main()
