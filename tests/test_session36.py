"""v0.8.36 (Round 2): fee statement PDFs for students and admins (voided invoices left out, reversed payments not counted,
Arabic names drawn); duplicate-applicant warning on the review panel; approval message carries the sign-in link."""
import datetime as dt, io, os, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MVT = dt.timezone(dt.timedelta(hours=5))
PW = "Password123"


class Round2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        old = os.environ.get("SEED_DEMO")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s36.test", ADMIN_PASSWORD="AdminPass123", SEED_DEMO="0")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path}); cls.c = cls.app.test_client()
        cls.app.config["NOW"] = lambda: dt.datetime(2027, 3, 10, 17, 0, tzinfo=MVT)
        cls.sql_("UPDATE users SET must_change_password=0")
        cls.H = cls.tok("admin@s36.test", "AdminPass123")
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, role, **kw: P("/api/users", {"email": e, "password": PW, "full_name": kw.pop("name", e.split("@")[0]), "role": role, **kw}).get_json()["id"]
        cls.t1 = mk("t1@s36.test", "teacher")
        cls.s1 = mk("s1@s36.test", "student", phone="7772222", name="محمد علي")
        cls.s2 = mk("s2@s36.test", "student")
        cls.sql_("UPDATE users SET must_change_password=0")
        cls.course = P("/api/courses", {"name": "Arabic", "monthly_fee_mvr": 1000, "registration_fee_mvr": 200, "status": "open"}).get_json()["id"]
        cls.b1 = P("/api/batches", {"course_id": cls.course, "code": "A1", "teacher_id": cls.t1, "capacity": 9, "days": "Wed", "start_time": "16:00"}).get_json()["id"]
        for s in (cls.s1, cls.s2): assert P("/api/enrollments", {"student_id": s, "batch_id": cls.b1}).status_code == 201
        cls.inv1 = cls.c.get(f"/api/invoices?student_id={cls.s1}&status=all", headers=cls.H).get_json()
        reg = [i for i in cls.inv1 if i["kind"] != "monthly"][0]
        assert P("/api/payments", {"invoice_id": reg["id"], "amount_mvr": 200, "method": "cash", "paid_on": "2027-03-04"}).status_code == 201
        cls.S1, cls.S2, cls.T1 = cls.tok("s1@s36.test", PW), cls.tok("s2@s36.test", PW), cls.tok("t1@s36.test", PW)

    @classmethod
    def tok(cls, login, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    @classmethod
    def sql_(cls, q, a=()):
        con = sqlite3.connect(cls.path)
        try: r = con.execute(q, a).fetchall(); con.commit(); return r
        finally: con.close()

    def text(self, pdf):
        from pypdf import PdfReader
        return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)

    # ---- fee statement ----
    def test_01_student_downloads_own_statement(self):
        r = self.c.get("/api/my/fees/statement.pdf", headers=self.S1)
        self.assertEqual(r.status_code, 200, r.data[:200]); self.assertEqual(r.mimetype, "application/pdf")
        self.assertTrue(r.data.startswith(b"%PDF")); self.assertIn("fee-statement-", r.headers["Content-Disposition"])
        self.assertIn(b"FreeSerif", r.data)                                  # the Arabic name is drawn with the bundled font
        t = self.text(r.data)
        for i in self.inv1: self.assertIn(i["number"], t)
        flat = t.replace(" ", "").replace(",", "").replace("MVR", "")
        self.assertIn("Totalbilled\n1200", flat); self.assertIn("Totalpaid\n200", flat); self.assertIn("Balancetopay\n1000", flat)

    def test_02_voided_left_out_reversed_not_counted(self):
        mon = [i for i in self.inv1 if i["kind"] == "monthly"][0]
        self.sql_("UPDATE invoices SET status='void', status_reason='mistake' WHERE id=?", (mon["id"],))
        try:
            t = self.text(self.c.get(f"/api/students/{self.s1}/statement.pdf", headers=self.H).data)
            self.assertNotIn(mon["number"], t)
        finally:
            self.sql_("UPDATE invoices SET status='unpaid', status_reason=NULL WHERE id=?", (mon["id"],))
        pay = self.c.get(f"/api/payments?student_id={self.s1}", headers=self.H).get_json()
        pid = (pay if isinstance(pay, list) else pay.get("items", []))[0]["id"]
        self.assertEqual(self.c.post(f"/api/payments/{pid}/reverse", json={"reason": "bounced"}, headers=self.H).status_code, 200)
        t = self.text(self.c.get(f"/api/students/{self.s1}/statement.pdf", headers=self.H).data)
        self.assertIn("reversed", t.lower())

    def test_03_permissions(self):
        self.assertEqual(self.c.get("/api/my/fees/statement.pdf").status_code, 401)
        self.assertEqual(self.c.get("/api/my/fees/statement.pdf", headers=self.T1).status_code, 403)
        self.assertEqual(self.c.get(f"/api/students/{self.s1}/statement.pdf", headers=self.S2).status_code, 403)
        self.assertEqual(self.c.get(f"/api/students/{self.s1}/statement.pdf", headers=self.T1).status_code, 403)
        self.assertEqual(self.c.get(f"/api/students/{self.t1}/statement.pdf", headers=self.H).status_code, 404)
        self.assertEqual(self.c.get("/api/students/999999/statement.pdf", headers=self.H).status_code, 404)

    # ---- admissions ----
    def apply(self, **kw):
        d = {"full_name": "Aisha Ahmed", "date_of_birth": "1995-05-05", "phone": "7770001", "email": "aisha@x.test", "course_id": str(self.course),
             "id_card": (io.BytesIO(b"%PDF-1.4\n%%EOF\n"), "id.pdf")}
        d.update(kw)
        r = self.c.post("/api/public/apply", data=d, content_type="multipart/form-data", environ_base={"REMOTE_ADDR": "10.0.0." + str(len(kw) + 1)})
        self.assertEqual(r.status_code, 201, r.data[:300])
        return [a for a in self.c.get("/api/applications?status=pending", headers=self.H).get_json() if a["email"] == d["email"]][0]

    def test_04_duplicate_applicant_warning(self):
        a1 = self.apply()
        self.assertEqual(self.c.get(f"/api/applications/{a1['id']}", headers=self.H).get_json()["duplicates"], [])
        a2 = self.apply(email="aisha2@x.test", phone="+960 777-0001", full_name="A. Ahmed")                           # same phone, written differently
        dup = self.c.get(f"/api/applications/{a2['id']}", headers=self.H).get_json()["duplicates"]
        self.assertEqual([(d["kind"], d["id"], d["why"]) for d in dup], [("application", a1["id"], ["phone"])])
        a3 = self.apply(email="s1@s36.test", phone="7009999", full_name="Someone", date_of_birth="2000-01-01")   # existing student's email
        dup = self.c.get(f"/api/applications/{a3['id']}", headers=self.H).get_json()["duplicates"]
        self.assertIn(("account", self.s1), [(d["kind"], d["id"]) for d in dup])
        a4 = self.apply(email="other@x.test", phone="7005555")                                  # same name and date of birth as a1
        why = {d["id"]: d["why"] for d in self.c.get(f"/api/applications/{a4['id']}", headers=self.H).get_json()["duplicates"]}
        self.assertEqual(why.get(a1["id"]), ["name and date of birth"])

    def test_05_approval_message_has_sign_in_link(self):
        a = self.apply(email="new1@x.test", phone="7006666", full_name="New Person", date_of_birth="1990-02-02")
        r = self.c.post(f"/api/applications/{a['id']}/approve", json={"batch_id": self.b1}, headers=self.H)
        self.assertEqual(r.status_code, 200, r.data[:300])
        link = r.get_json()["whatsapp_link"]
        from urllib.parse import unquote
        self.assertIn("Sign in at http", unquote(link))


if __name__ == "__main__":
    unittest.main()
