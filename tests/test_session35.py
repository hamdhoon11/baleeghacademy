"""v0.8.35 (Round 1): voided invoices are not revenue and are found with the Void filter; teacher pay = 50% of monthly fees collected
(registration fees and voided invoices left out); "Forgot password" through the admins; admin To do; student and teacher Home data;
PDF receipts with Arabic and Dhivehi names."""
import datetime as dt, os, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rtltext, receipts  # noqa: E402

MVT = dt.timezone(dt.timedelta(hours=5))
PW = "Password123"


class Round1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        old = os.environ.get("SEED_DEMO")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s35.test", ADMIN_PASSWORD="AdminPass123", SEED_DEMO="0")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)   # later test files expect the demo accounts
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path}); cls.c = cls.app.test_client()
        cls.app.config["NOW"] = lambda: dt.datetime(2027, 3, 10, 17, 0, tzinfo=MVT)   # Wednesday 17:00
        cls.sql_("UPDATE users SET must_change_password=0")
        cls.H = cls.tok("admin@s35.test", "AdminPass123")
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, role, **kw: P("/api/users", {"email": e, "password": PW, "full_name": e.split("@")[0], "role": role, **kw}).get_json()["id"]
        cls.t1 = mk("t1@s35.test", "teacher", phone="7771111")
        cls.s1, cls.s2 = mk("s1@s35.test", "student", phone="7772222"), mk("s2@s35.test", "student")
        cls.sql_("UPDATE users SET must_change_password=0")
        cls.course = P("/api/courses", {"name": "Arabic", "monthly_fee_mvr": 1000, "registration_fee_mvr": 200, "status": "open"}).get_json()["id"]
        cls.b1 = P("/api/batches", {"course_id": cls.course, "code": "A1", "teacher_id": cls.t1, "capacity": 9, "days": "Wed", "start_time": "16:00"}).get_json()["id"]
        for s in (cls.s1, cls.s2): assert P("/api/enrollments", {"student_id": s, "batch_id": cls.b1}).status_code == 201
        inv = lambda s: cls.c.get(f"/api/invoices?student_id={s}&status=all", headers=cls.H).get_json()
        cls.inv1, cls.inv2 = inv(cls.s1), inv(cls.s2)
        for i in cls.inv1: assert P("/api/payments", {"invoice_id": i["id"], "amount_mvr": i["amount_due_mvr"], "method": "cash", "paid_on": "2027-03-04"}).status_code == 201
        cls.T1, cls.S1 = cls.tok("t1@s35.test", PW), cls.tok("s1@s35.test", PW)

    @classmethod
    def tok(cls, login, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    @classmethod
    def sql_(cls, q, a=()):
        con = sqlite3.connect(cls.path)
        try: r = con.execute(q, a).fetchall(); con.commit(); return r
        finally: con.close()

    # ---- voided invoices ----
    def test_01_voided_invoice_is_not_revenue_and_is_findable(self):
        rev0 = self.c.get("/api/finance/revenue?date_from=2027-03-01&date_to=2027-03-31", headers=self.H).get_json()["total_collected"]
        self.assertEqual(rev0, 1200)                                                   # s1 paid the month (1000) and registration (200)
        # a payment on an invoice that is later voided (older data could have this; the screen refuses to void a paid invoice)
        mon = [i for i in self.inv2 if i["kind"] == "monthly"][0]
        cols = [r[1] for r in self.sql_("PRAGMA table_info(payments)")]
        src = self.sql_("SELECT * FROM payments ORDER BY id LIMIT 1")[0]
        row = dict(zip(cols, src)); row.pop("id")
        row.update(invoice_id=mon["id"], student_id=self.s2, amount_mvr=300, paid_on="2027-03-05", receipt_no="BA-R-X1", receipt_seq=(row.get("receipt_seq") or 0) + 900)
        self.sql_(f"INSERT INTO payments({','.join(row)}) VALUES({','.join('?' * len(row))})", tuple(row.values()))
        self.sql_("UPDATE invoices SET status='void', status_reason='entered twice' WHERE id=?", (mon["id"],))
        rev = self.c.get("/api/finance/revenue?date_from=2027-03-01&date_to=2027-03-31", headers=self.H).get_json()
        self.assertEqual(rev["total_collected"], 1200)                                 # the 300 on the voided invoice is not revenue
        self.assertEqual(sum(m["collected"] for m in rev["by_month"]), 1200)
        dash = self.c.get("/api/finance/dashboard?date_from=2027-03-01&date_to=2027-03-31", headers=self.H).get_json()
        self.assertEqual(dash["revenue"], 1200)
        self.assertEqual(self.c.get("/api/dashboard", headers=self.H).get_json()["month_collection_mvr"], 1200)
        default = {i["id"] for i in self.c.get("/api/invoices", headers=self.H).get_json()}
        self.assertNotIn(mon["id"], default)                                           # out of the normal list
        voids = self.c.get("/api/invoices?status=void", headers=self.H).get_json()
        self.assertEqual([i["id"] for i in voids], [mon["id"]]); self.assertEqual(voids[0]["status_reason"], "entered twice")
        self.assertIn(mon["id"], {i["id"] for i in self.c.get("/api/invoices?status=all", headers=self.H).get_json()})
        self.assertIn(mon["id"], {i["id"] for i in self.c.get(f"/api/invoices?q={mon['number']}", headers=self.H).get_json()})   # by its number
        self.assertEqual(self.c.get("/api/invoices?status=nonsense", headers=self.H).status_code, 400)

    def test_02_teacher_pay_is_half_of_monthly_fees_only(self):
        r = self.c.post("/api/earnings/calculate", json={"month": "2027-03"}, headers=self.H)
        self.assertEqual(r.status_code, 200, r.get_json())
        e = self.c.get("/api/earnings?month=2027-03", headers=self.H).get_json()
        row = [x for x in e["items"] if x["batch_id"] == self.b1][0]
        self.assertEqual(row["collected_mvr"], 1000)          # not the 200 registration fee, not the 300 on the voided invoice
        self.assertEqual(row["share_percent"], 50)
        self.assertEqual(row["teacher_share_mvr"], 500); self.assertEqual(row["academy_share_mvr"], 500)

    # ---- forgot password ----
    def test_03_forgot_password_goes_to_admins(self):
        same = lambda r: (r.status_code, r.get_json()["message"])
        a = same(self.c.post("/api/auth/forgot", json={"login": "S1@S35.TEST", "contact": "7772222"}))
        b = same(self.c.post("/api/auth/forgot", json={"login": "nobody@s35.test"}))
        self.assertEqual(a, b)                                                         # the answer never says whether the account exists
        self.assertEqual(self.c.post("/api/auth/forgot", json={}).status_code, 400)
        lst = self.c.get("/api/password-help", headers=self.H).get_json()
        mine = [x for x in lst if x["user_id"] == self.s1]; other = [x for x in lst if x["user_id"] is None]
        self.assertEqual(len(mine), 1); self.assertEqual(len(other), 1)
        self.assertEqual(self.c.get("/api/dashboard", headers=self.H).get_json()["password_help"], 2)
        self.c.post("/api/auth/forgot", json={"login": "s1@s35.test"})                # a second request for the same person: still one
        self.assertEqual(len([x for x in self.c.get("/api/password-help", headers=self.H).get_json() if x["user_id"] == self.s1]), 1)
        note = self.c.get("/api/notifications", headers=self.H).get_json()["items"]
        self.assertTrue(any(n["kind"] == "password_help" and n["link"] == f"people:{self.s1}" for n in note))
        r = self.c.post(f"/api/users/{self.s1}/reset-password", headers=self.H).get_json()
        self.assertTrue(r["temporary_password"]); self.assertIn("https://wa.me/9607772222?text=", r["whatsapp_link"])
        self.assertIn(r["temporary_password"], __import__("urllib.parse").parse.unquote(r["whatsapp_link"]))
        self.assertEqual([x for x in self.c.get("/api/password-help", headers=self.H).get_json() if x["user_id"] == self.s1], [])   # handled by the reset
        self.assertEqual(self.c.post(f"/api/password-help/{other[0]['id']}/dismiss", headers=self.H).status_code, 200)
        self.assertEqual(self.c.post(f"/api/password-help/{other[0]['id']}/dismiss", headers=self.H).status_code, 409)
        self.assertEqual(self.c.get("/api/password-help", headers=self.T1).status_code, 403)
        self.sql_("UPDATE users SET must_change_password=0 WHERE id=?", (self.s1,))
        self.sql_("UPDATE users SET password_hash=(SELECT password_hash FROM users WHERE id=?) WHERE id=?", (self.s2, self.s1))   # back to PW for later tests
        type(self).S1 = self.tok("s1@s35.test", PW)   # v0.8.39: a reset ends the student's old sign-in, so later tests sign in again

    def test_04_forgot_is_limited_per_address(self):
        self.app.config["FORGOT_LIMIT"] = 2
        try:
            for i in range(4): self.assertEqual(self.c.post("/api/auth/forgot", json={"login": f"x{i}@s35.test"}, environ_base={"REMOTE_ADDR": "10.9.9.9"}).status_code, 200)
            n = self.sql_("SELECT COUNT(*) FROM password_help WHERE ip='10.9.9.9'")[0][0]
            self.assertEqual(n, 2)
        finally:
            self.app.config.pop("FORGOT_LIMIT")

    # ---- admin To do, home data ----
    def test_05_admin_todo(self):
        d = self.c.get("/api/admin/todo", headers=self.H).get_json()
        keys = {x["key"]: x for x in d["items"]}
        self.assertEqual([c["batch_id"] for c in d["classes"]], [self.b1])            # Wednesday 16:00 class has started, no attendance
        self.assertEqual(keys["todo_attendance"]["n"], 1); self.assertEqual(keys["todo_attendance"]["view"], "classroom")
        self.assertEqual(self.c.get("/api/admin/todo", headers=self.T1).status_code, 403)
        self.c.post(f"/api/batches/{self.b1}/attendance", json={"date": "2027-03-10", "records": [{"student_id": self.s1, "status": "present"}]}, headers=self.T1)
        self.assertEqual(self.c.get("/api/admin/todo", headers=self.H).get_json()["classes"], [])

    def test_06_teacher_and_student_home(self):
        h = self.c.get("/api/my/home", headers=self.T1).get_json()
        self.assertEqual(len(h["today"]), 1); self.assertIn("attendance_taken", h["today"][0]); self.assertTrue(h["today"][0]["started"])
        P = lambda p, j: self.c.post(p, json=j, headers=self.T1)
        for k in range(7): P(f"/api/batches/{self.b1}/assignments", {"title": f"Work {k}", "max_points": 10, "due_date": "2027-03-0" + str(k + 1)})
        s = self.c.get("/api/my/home", headers=self.S1).get_json()
        self.assertEqual(s["todo_count"], 7); self.assertEqual(len(s["todo"]), 7)                 # the badge used to stop at 5
        self.assertTrue(all(a["overdue"] for a in s["todo"]))                                        # due 1-7 March, today is the 10th
        self.assertIn("new_grades", s); self.assertIn("new_materials", s)


class Pdf(unittest.TestCase):
    def test_01_arabic_is_joined_and_right_to_left(self):
        self.assertEqual(rtltext.visual("Aisha Ali"), "Aisha Ali")
        self.assertEqual(rtltext.visual("محمد"), "ﺪﻤﺤﻣ")                     # dal final, meem medial, hah medial, meem initial
        self.assertIn("ﻼ", rtltext.visual("السلام"))                                          # lam-alef ligature
        th = rtltext.visual("ދަރުސް")
        self.assertEqual(th, "ސް" + "ރު" + "ދަ")                                                   # Thaana: right to left, each vowel sign stays on its letter

    def test_02_receipt_draws_names_instead_of_question_marks(self):
        r = {"academy": "Baleegh Academy", "phone": "7771234", "receipt_no": "BA-R-1", "paid_on": "2027-03-04", "student": "عائشة / ދަރުސް", "course": "Arabic",
             "batch": "A1", "invoice_no": "INV-1", "period": "2027-03", "amount": 350, "method": "Cash", "reference": "", "reversed": False}
        pdf = receipts.build(r)
        self.assertTrue(pdf.startswith(b"%PDF")); self.assertNotIn(b"(????", pdf); self.assertTrue(b"FreeSerif" in pdf, "bundled font not embedded")
        self.assertEqual(receipts.build(r), pdf)                                                     # still byte-identical on re-download


if __name__ == "__main__":
    unittest.main()
