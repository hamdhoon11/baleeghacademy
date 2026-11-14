"""v0.8.49: contact number required when adding a person; unexpected server errors recorded with a reference (and the reason for admins);
Excel templates survive characters Excel cannot hold; Calculate (teacher earnings) explains what it found."""
import datetime as dt, io, os, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MVT = dt.timezone(dt.timedelta(hours=5))
PW = "Password123"


class S49(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        old = os.environ.get("SEED_DEMO"); oldp = os.environ.pop("PORTAL_PHONE_OPTIONAL", None)
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s49.test", ADMIN_PASSWORD="AdminPass123", SEED_DEMO="0")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path})   # the phone rule ON, as on a real server
        if oldp is not None: os.environ["PORTAL_PHONE_OPTIONAL"] = oldp
        cls.app.config["NOW"] = lambda: dt.datetime(2026, 11, 14, 10, 0, tzinfo=MVT)
        cls.c = cls.app.test_client()
        cls.H = {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": "admin@s49.test", "password": "AdminPass123"}).get_json()["token"]}

    def sql(self, q, a=()):
        con = sqlite3.connect(self.path)
        try: r = con.execute(q, a).fetchall(); con.commit(); return r
        finally: con.close()

    def add(self, **kw):
        body = {"email": kw.pop("email", "p@s49.test"), "full_name": "Person", "role": "student", "password": PW}; body.update(kw)
        return self.c.post("/api/users", json=body, headers=self.H)

    def test_01_contact_number_required(self):
        self.assertFalse(self.app.config["PHONE_OPTIONAL"])
        r = self.add(email="a@s49.test"); self.assertEqual(r.status_code, 400); self.assertIn("contact number", r.get_json()["error"])
        for bad in ("12", "abcdefg", "77-12", "7" * 31):
            self.assertEqual(self.add(email="b@s49.test", phone=bad).status_code, 400, bad)
        for i, ok in enumerate(("7771234", "+960 777 1234", "(960) 777-1234")):
            r = self.add(email=f"ok{i}@s49.test", phone=ok, role=("student", "teacher", "admin")[i]); self.assertEqual(r.status_code, 201, r.get_json())
        self.assertEqual(self.sql("SELECT phone FROM users WHERE email='ok1@s49.test'")[0][0], "+960 777 1234")

    def test_02_server_error_recorded_with_reference(self):
        orig = self.app.view_functions["earn_teachers"]
        def boom(): raise KeyError("missing_key")
        self.app.view_functions["earn_teachers"] = self._wrap(boom)
        try: r = self.c.get("/api/earnings/teachers", headers=self.H)
        finally: self.app.view_functions["earn_teachers"] = orig
        self.assertEqual(r.status_code, 500)
        j = r.get_json(); self.assertTrue(j["ref"]); self.assertIn(j["ref"], j["error"]); self.assertIn("KeyError", j["error"])   # admins see the reason
        e = self.c.get("/api/admin/server-errors", headers=self.H).get_json()[0]
        self.assertEqual((e["ref"], e["error_type"], e["path"]), (j["ref"], "KeyError", "/api/earnings/teachers"))
        self.assertIn("missing_key", e["message"])

    def _wrap(self, fn):
        from flask import g
        def w():
            g.user = {"id": 1, "role": "admin", "permissions": None}
            return fn()
        return w

    def test_03_server_errors_full_admins_only(self):
        self.add(email="lim@s49.test", phone="7771111", role="admin")
        uid = self.sql("SELECT id FROM users WHERE email='lim@s49.test'")[0][0]
        self.c.patch(f"/api/users/{uid}", json={"permissions": ["people"]}, headers=self.H)
        self.sql("UPDATE users SET must_change_password=0")
        L = {"Authorization": "Bearer " + self.c.post("/api/auth/login", json={"login": "lim@s49.test", "password": PW}).get_json()["token"]}
        self.assertEqual(self.c.get("/api/admin/server-errors", headers=L).status_code, 403)
        self.assertEqual(self.c.get("/api/admin/server-errors").status_code, 401)

    def test_04_templates_survive_control_characters(self):
        self.c.post("/api/expense-categories", json={"name": "Rent"}, headers=self.H)
        self.sql("INSERT INTO expense_categories(name,is_active) VALUES(?,1)", ("Bad\x0bname\x01",))
        r = self.c.get("/api/import/expenses/template.xlsx", headers=self.H)
        self.assertEqual(r.status_code, 200)
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(r.data))
        vals = [c.value for c in wb["Lists"]["A"]]
        self.assertIn("Badname", vals)

    def test_05_calculate_explains(self):
        r = self.c.post("/api/earnings/calculate", json={"month": "2026-10"}, headers=self.H).get_json()
        self.assertEqual(r["count"], 0)
        self.assertIn("month they were PAID", " ".join(r["why"]))


if __name__ == "__main__":
    unittest.main()
