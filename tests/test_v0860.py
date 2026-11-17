"""v0.8.60: Interest list (admins with Admissions): add, rules, batch by batch, status, PDF, who may use it."""
import os, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PW = "Password123"


class V0860(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        old = os.environ.get("SEED_DEMO")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@v60.test", ADMIN_PASSWORD="AdminPass123", SEED_DEMO="0")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path}); cls.c = cls.app.test_client()
        cls.H = cls.login("admin@v60.test", "AdminPass123")
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H).get_json()
        mk = lambda e, n, role, **k: P("/api/users", {"email": e, "password": PW, "full_name": n, "role": role, "phone": "7771234", **k})["id"]
        mk("t@v60.test", "Teacher", "teacher"); mk("s@v60.test", "Student", "student")
        mk("fees@v60.test", "Fees Admin", "admin", permissions=["fees"]); mk("adm@v60.test", "Admissions Admin", "admin", permissions=["admissions"])
        cls.T, cls.S, cls.F, cls.A = (cls.login(f"{x}@v60.test", PW) for x in ("t", "s", "fees", "adm"))
        co = P("/api/courses", {"name": "Arabic Level 1", "monthly_fee_mvr": 500, "status": "open"})["id"]
        cls.b1 = P("/api/batches", {"course_id": co, "code": "A1-JAN", "capacity": 10, "days": "Sun,Tue", "start_time": "16:00", "end_time": "17:30", "start_date": "2027-01-10"})["id"]
        cls.b2 = P("/api/batches", {"course_id": co, "code": "A1-FEB", "capacity": 10})["id"]
        cls.b3 = P("/api/batches", {"course_id": co, "code": "OLD", "capacity": 10})["id"]
        cls.c.patch(f"/api/batches/{cls.b3}", json={"status": "closed"}, headers=cls.H)

    @classmethod
    def login(cls, who, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": who, "password": pw}).get_json()["token"]}

    def sql(self, q, a=()):
        con = sqlite3.connect(self.path)
        try: return con.execute(q, a).fetchall()
        finally: con.close()

    def add(self, h=None, **k):
        d = {"batch_id": self.b1, "full_name": "Aishath Ali", "id_card": "A123456", "phone": "7771234", **k}
        return self.c.post("/api/interest", json=d, headers=h or self.H)

    def test_01_add_and_rules(self):
        r = self.add(full_name="  Mohamed   Hassan ", id_card="a 300100", phone="+960 777 0001", email="M@Example.com", notes="Prefers evenings")
        self.assertEqual(r.status_code, 201, r.get_json())
        self.assertEqual(self.sql("SELECT full_name,id_card,email,status FROM interest_list WHERE id=?", (r.get_json()["id"],))[0],
                         ("Mohamed Hassan", "A300100", "m@example.com", "waiting"))
        self.assertEqual(self.add(id_card="A300100").status_code, 409)                 # same person twice in one batch
        self.assertEqual(self.add(id_card="A300100", batch_id=self.b2).status_code, 201)  # another batch is fine
        for bad in ({"full_name": ""}, {"id_card": ""}, {"id_card": "!!"}, {"phone": ""}, {"phone": "123"}, {"email": "nope"},
                    {"batch_id": None}, {"batch_id": 9999}, {"batch_id": self.b3}):
            self.assertEqual(self.add(**{"id_card": "A999999", **bad}).status_code, 400, bad)
        self.assertTrue(self.sql("SELECT 1 FROM audit_log WHERE action='interest_add'"))

    def test_02_batchwise_filter_status_search(self):
        a = self.add(full_name="Ibrahim Naseer", id_card="A500001").get_json()["id"]
        self.add(full_name="Fathimath Zahra", id_card="A500002", batch_id=self.b2)
        j = self.c.get(f"/api/interest?batch_id={self.b1}", headers=self.H).get_json()
        self.assertTrue(j["entries"] and all(e["batch_id"] == self.b1 for e in j["entries"]))
        names = {b["code"]: b for b in j["batches"]}
        self.assertIn("A1-JAN", names); self.assertNotIn("OLD", names)   # closed batch with nobody on it is not offered
        self.assertGreaterEqual(names["A1-JAN"]["waiting"], 1)
        self.assertEqual([e["full_name"] for e in self.c.get("/api/interest?q=a500002", headers=self.H).get_json()["entries"]], ["Fathimath Zahra"])
        self.assertEqual(self.c.patch(f"/api/interest/{a}", json={"status": "joined"}, headers=self.H).status_code, 200)
        self.assertEqual(self.c.patch(f"/api/interest/{a}", json={"status": "maybe"}, headers=self.H).status_code, 400)
        act = [e["id"] for e in self.c.get("/api/interest?status=active", headers=self.H).get_json()["entries"]]
        self.assertNotIn(a, act)
        self.assertEqual(self.c.patch(f"/api/interest/{a}", json={"batch_id": self.b2, "phone": "7770000"}, headers=self.H).status_code, 200)
        self.assertEqual(self.c.patch(f"/api/interest/{a}", json={"batch_id": self.b3}, headers=self.H).status_code, 400)   # no moving into a closed batch
        self.assertTrue(self.sql("SELECT 1 FROM audit_log WHERE action='interest_update' AND entity_id=?", (a,)))
        self.assertEqual(self.c.delete(f"/api/interest/{a}", headers=self.H).status_code, 200)
        self.assertEqual(self.c.delete(f"/api/interest/{a}", headers=self.H).status_code, 404)

    def test_03_pdf(self):
        self.add(full_name="Hawwa Shareef", id_card="A600001")
        for q in ("", f"?batch_id={self.b1}", "?status=active", f"?batch_id={self.b2}&q=nobody"):
            r = self.c.get("/api/interest/report.pdf" + q, headers=self.H)
            self.assertEqual(r.status_code, 200, q); self.assertTrue(r.data.startswith(b"%PDF"))
        r = self.c.get(f"/api/interest/report.pdf?batch_id={self.b1}", headers=self.H)
        self.assertIn("interest-list-A1-JAN.pdf", r.headers["Content-Disposition"])
        self.assertTrue(self.sql("SELECT 1 FROM audit_log WHERE action='interest_pdf'"))

    def test_04_who(self):
        self.assertEqual(self.add(self.A, id_card="A700001").status_code, 201)   # an admin limited to Admissions
        for h in (self.T, self.S, self.F):
            self.assertEqual(self.c.get("/api/interest", headers=h).status_code, 403)
            self.assertEqual(self.c.get("/api/interest/report.pdf", headers=h).status_code, 403)
            self.assertEqual(self.add(h, id_card="A700002").status_code, 403)
        tabs = lambda h: (lambda j: (j.get("user") or j)["tabs"])(self.c.get("/api/auth/me", headers=h).get_json())
        self.assertIn("interest", tabs(self.A)); self.assertNotIn("interest", tabs(self.F)); self.assertNotIn("interest", tabs(self.T))

    def test_05_batch_with_list_is_not_deleted(self):
        P = lambda p, j: self.c.post(p, json=j, headers=self.H).get_json()
        co = P("/api/courses", {"name": "Quran", "monthly_fee_mvr": 300, "status": "open"})["id"]
        b = P("/api/batches", {"course_id": co, "code": "Q-NEW", "capacity": 5})["id"]
        self.add(batch_id=b, id_card="A800001")
        r = self.c.delete(f"/api/batches/{b}", headers=self.H)
        self.assertEqual(r.status_code, 409); self.assertIn("interest list", r.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
