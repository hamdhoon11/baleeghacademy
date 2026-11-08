"""Session 23: expenses. Add with receipt, filter, download, edit, delete, categories, permissions, audit rows."""
import datetime as dt, io, os, sqlite3, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PW = "Passw0rd!x1"
MVT = dt.timezone(dt.timedelta(hours=5))
PDF = b"%PDF-1.4\n%test receipt\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


class S23(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s23.test", ADMIN_PASSWORD="AdminPass123")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path})
        cls.c = cls.app.test_client()
        cls.app.config["NOW"] = lambda: dt.datetime(2027, 3, 10, 12, 0, tzinfo=MVT)
        cls.H = cls.tok("admin@s23.test", "AdminPass123")
        mk = lambda email, role, **kw: cls.c.post("/api/users", json={"email": email, "password": PW, "full_name": email, "role": role, **kw}, headers=cls.H).get_json()["id"]
        # a limited admin who may use fees but not finance, and one who may use finance
        cls.nofin = mk("nofin@s23.test", "admin", permissions=["fees", "courses"])
        cls.fin = mk("fin@s23.test", "admin", permissions=["finance"])
        mk("t@s23.test", "teacher"); mk("s@s23.test", "student")
        cls.NF, cls.F, cls.T, cls.ST = (cls.tok(e, PW) for e in ("nofin@s23.test", "fin@s23.test", "t@s23.test", "s@s23.test"))
        cls.rent = cls.c.post("/api/expense-categories", json={"name": "Rent"}, headers=cls.H).get_json()["id"]
        cls.sup = cls.c.post("/api/expense-categories", json={"name": "Supplies"}, headers=cls.H).get_json()["id"]

    @classmethod
    def tok(cls, login, pw):
        r = cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()
        return {"Authorization": "Bearer " + r["token"]}

    def sql(self, q, a=()):
        con = sqlite3.connect(self.path)
        try: return con.execute(q, a).fetchall()
        finally: con.close()

    def add(self, day="2027-03-05", amount=500, cat=None, desc="", file=None, H=None):
        data = {"expense_date": day, "amount_mvr": str(amount), "category_id": str(cat or self.rent), "description": desc}
        if file: data["file"] = (io.BytesIO(file[1]), file[0])
        return self.c.post("/api/expenses", data=data, headers=H or self.H, content_type="multipart/form-data")

    def audit_rows(self, action, eid):
        return self.sql("SELECT user_role,login_id,old_value,new_value FROM audit_log WHERE action=? AND entity_id=?", (action, eid))

    def test_01_add_with_receipt_list_and_download(self):
        r = self.add(day="2027-03-02", amount=1200, desc="March office rent", file=("rent.pdf", PDF))
        self.assertEqual(r.status_code, 201); eid = r.get_json()["id"]
        row = [x for x in self.c.get("/api/expenses", headers=self.H).get_json()["items"] if x["id"] == eid][0]
        self.assertEqual((row["amount_mvr"], row["category"], row["has_receipt"]), (1200, "Rent", True))
        d = self.c.get(f"/api/expenses/{eid}/receipt", headers=self.H)
        self.assertEqual((d.status_code, d.data, d.headers["Content-Type"]), (200, PDF, "application/pdf"))
        self.assertIn("attachment", d.headers["Content-Disposition"])
        self.assertEqual(len(self.audit_rows("view_expense_receipt", eid)), 1)
        # the stored receipt name is a random one, never a path from the user
        self.assertNotIn("rent", self.sql("SELECT receipt_file FROM expenses WHERE id=?", (eid,))[0][0])

    def test_02_png_receipt_and_bad_files(self):
        self.assertEqual(self.add(file=("r.png", PNG)).status_code, 201)
        bad = self.add(file=("r.pdf", b"not a pdf"))
        self.assertEqual(bad.status_code, 400); self.assertIn("does not match", bad.get_json()["error"])
        self.assertEqual(self.add(file=("r.exe", b"MZ")).status_code, 400)
        no = self.add(); self.assertEqual(no.status_code, 201)       # a receipt is optional
        self.assertEqual(self.c.get(f"/api/expenses/{no.get_json()['id']}/receipt", headers=self.H).status_code, 404)

    def test_03_filters_and_totals_match_sql(self):
        a = self.add(day="2027-01-10", amount=300, cat=self.sup, desc="whiteboard markers").get_json()["id"]
        self.add(day="2027-01-20", amount=700, cat=self.sup, desc="printer paper")
        g = lambda q: self.c.get("/api/expenses?" + q, headers=self.H).get_json()
        j = g(f"category_id={self.sup}&date_from=2027-01-01&date_to=2027-01-31")
        self.assertEqual((j["count"], j["total_mvr"]), (2, 1000))
        self.assertEqual(g("q=markers")["count"], 1)
        self.assertEqual(g(f"category_id={self.sup}&date_from=2027-01-11")["total_mvr"], 700)
        want = self.sql("SELECT COUNT(*),SUM(amount_mvr) FROM expenses")[0]
        allj = g("per_page=200"); self.assertEqual((allj["count"], allj["total_mvr"]), tuple(want))
        self.assertEqual(g("per_page=2&page=2")["page"], 2); self.assertEqual(len(g("per_page=2")["items"]), 2)
        self.assertEqual(self.c.get("/api/expenses?date_from=nope", headers=self.H).status_code, 400)
        self.assertTrue(a)

    def test_04_validation(self):
        for kw in ({"amount": 0}, {"amount": -5}, {"amount": "12.5"}, {"amount": "abc"}, {"day": "2027-03-11"}, {"day": "garbage"}):
            self.assertEqual(self.add(**kw).status_code, 400, kw)
        self.assertEqual(self.add(cat=99999).status_code, 400)
        self.assertEqual(self.add(desc="x" * 501).status_code, 400)

    def test_05_edit_replace_receipt_and_audit_old_new(self):
        eid = self.add(amount=400, desc="before", file=("a.pdf", PDF)).get_json()["id"]
        old_file = self.sql("SELECT receipt_file FROM expenses WHERE id=?", (eid,))[0][0]
        r = self.c.patch(f"/api/expenses/{eid}", data={"amount_mvr": "450", "description": "after", "file": (io.BytesIO(PNG), "b.png")}, headers=self.H, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200); self.assertIn("amount_mvr", r.get_json()["changed"]); self.assertIn("receipt", r.get_json()["changed"])
        new_file = self.sql("SELECT receipt_file FROM expenses WHERE id=?", (eid,))[0][0]
        self.assertNotEqual(old_file, new_file)
        up = os.path.join(os.path.dirname(self.path), "uploads", "receipts")
        self.assertFalse(os.path.exists(os.path.join(up, old_file))); self.assertTrue(os.path.exists(os.path.join(up, new_file)))   # old file removed, new one stored
        self.assertEqual(self.c.get(f"/api/expenses/{eid}/receipt", headers=self.H).data, PNG)   # the new file is served
        self.assertEqual(self.audit_rows("expense_update", eid), [("admin", self.sql("SELECT login_id FROM users WHERE email='admin@s23.test'")[0][0], "400", "450")])
        # removing the receipt, and an edit that changes nothing writes no log row
        self.c.patch(f"/api/expenses/{eid}", data={"remove_receipt": "1"}, headers=self.H, content_type="multipart/form-data")
        self.assertEqual(self.c.get(f"/api/expenses/{eid}/receipt", headers=self.H).status_code, 404)
        n = len(self.audit_rows("expense_update", eid))
        self.c.patch(f"/api/expenses/{eid}", json={"amount_mvr": 450}, headers=self.H)
        self.assertEqual(len(self.audit_rows("expense_update", eid)), n)
        self.assertEqual(self.c.patch("/api/expenses/999999", json={"amount_mvr": 5}, headers=self.H).status_code, 404)

    def test_06_create_and_delete_are_logged_and_file_removed(self):
        eid = self.add(amount=250, desc="to delete", file=("d.pdf", PDF)).get_json()["id"]
        self.assertEqual([r[3] for r in self.audit_rows("expense_create", eid)], ["250"])
        self.assertEqual(self.c.delete(f"/api/expenses/{eid}", headers=self.H).status_code, 200)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM expenses WHERE id=?", (eid,))[0][0], 0)
        self.assertEqual([r[2] for r in self.audit_rows("expense_delete", eid)], ["250"])
        self.assertEqual(self.c.get(f"/api/expenses/{eid}/receipt", headers=self.H).status_code, 404)
        self.assertEqual(self.c.delete(f"/api/expenses/{eid}", headers=self.H).status_code, 404)

    def test_07_categories(self):
        j = lambda m, p, **kw: getattr(self.c, m)(p, headers=self.H, **kw)
        self.assertEqual(j("post", "/api/expense-categories", json={"name": " rent "}).status_code, 409)   # same name, any case
        self.assertEqual(j("post", "/api/expense-categories", json={"name": ""}).status_code, 400)
        k = j("post", "/api/expense-categories", json={"name": "Internet"}).get_json()["id"]
        self.assertEqual(j("patch", f"/api/expense-categories/{k}", json={"name": "Internet and phone"}).status_code, 200)
        self.assertEqual(j("patch", f"/api/expense-categories/{k}", json={"name": "Rent"}).status_code, 409)
        e = self.add(cat=k).get_json()["id"]
        self.assertEqual(j("delete", f"/api/expense-categories/{k}").status_code, 409)        # in use: deactivate instead
        self.assertEqual(j("patch", f"/api/expense-categories/{k}", json={"is_active": False}).status_code, 200)
        self.assertEqual(self.add(cat=k).status_code, 400)                                    # inactive: not for new expenses
        self.assertEqual(self.c.get("/api/expenses", headers=self.H).get_json()["items"][0]["id"] > 0, True)
        self.assertEqual(self.c.patch(f"/api/expenses/{e}", json={"description": "still editable"}, headers=self.H).status_code, 200)   # old expense keeps it
        k2 = j("post", "/api/expense-categories", json={"name": "Temp"}).get_json()["id"]
        self.assertEqual(j("delete", f"/api/expense-categories/{k2}").status_code, 200)
        self.assertEqual(len(self.sql("SELECT 1 FROM audit_log WHERE action LIKE 'expense_category_%'")) >= 5, True)

    def test_08_permissions(self):
        e = self.add(file=("p.pdf", PDF)).get_json()["id"]
        calls = [("get", "/api/expenses", None), ("post", "/api/expenses", {"amount_mvr": 5}), (("patch"), f"/api/expenses/{e}", {"amount_mvr": 6}),
                 ("delete", f"/api/expenses/{e}", None), ("get", f"/api/expenses/{e}/receipt", None),
                 ("get", "/api/expense-categories", None), ("post", "/api/expense-categories", {"name": "Z"}),
                 ("patch", f"/api/expense-categories/{self.rent}", {"name": "Z"}), ("delete", f"/api/expense-categories/{self.rent}", None)]
        for m, p, body in calls:
            kw = {"json": body} if body is not None else {}
            self.assertEqual(getattr(self.c, m)(p, **kw).status_code, 401, (m, p))
            for who in (self.NF, self.T, self.ST):
                self.assertEqual(getattr(self.c, m)(p, headers=who, **kw).status_code, 403, (m, p))
        self.assertEqual(self.c.get("/api/expenses", headers=self.F).status_code, 200)       # the finance admin works
        self.assertEqual(self.c.get(f"/api/expenses/{e}/receipt", headers=self.F).status_code, 200)
        self.assertEqual(self.c.get("/api/expenses", headers=self.H).status_code, 200)       # a full admin works too
        tabs = lambda H: self.c.get("/api/auth/me", headers=H).get_json()
        self.assertIn("finance", str(tabs(self.F))); self.assertNotIn("finance", str(tabs(self.NF)))
        self.assertIn("finance", str(tabs(self.H)))
        # nothing about the receipt file location leaks in the list
        self.assertNotIn("receipt_file", self.c.get("/api/expenses", headers=self.H).get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
