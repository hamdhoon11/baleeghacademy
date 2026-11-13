"""v0.8.45: manual invoices (a student, or a customer who is not in the portal), revenue types, editing invoice amounts,
revenue by type; and the upgrade of an older database (NOT NULL loosened, no row changed)."""
import datetime as dt, io, os, re, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MVT = dt.timezone(dt.timedelta(hours=5))
PW = "Password123"
PNG = b"\x89PNG\r\n\x1a\n" + b"whatsapp" * 40


class Manual(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        old = os.environ.get("SEED_DEMO")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s45.test", ADMIN_PASSWORD="AdminPass123", SEED_DEMO="0")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path}); cls.c = cls.app.test_client()
        cls.app.config["NOW"] = lambda: dt.datetime(2026, 11, 13, 17, 0, tzinfo=MVT)
        cls.H = cls.tok("admin@s45.test", "AdminPass123")
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, role: P("/api/users", {"email": e, "password": PW, "full_name": e.split("@")[0].title(), "role": role}).get_json()["id"]
        cls.t1, cls.s1, cls.s2 = mk("t1@s45.test", "teacher"), mk("s1@s45.test", "student"), mk("s2@s45.test", "student")
        cls.sql_("UPDATE users SET must_change_password=0")
        cls.course = P("/api/courses", {"name": "Arabic", "monthly_fee_mvr": 500, "status": "open"}).get_json()["id"]
        cls.b1 = P("/api/batches", {"course_id": cls.course, "code": "A1", "teacher_id": cls.t1, "capacity": 9, "days": "Wed", "start_time": "16:00"}).get_json()["id"]
        cls.b2 = P("/api/batches", {"course_id": cls.course, "code": "A2", "teacher_id": cls.t1, "capacity": 9, "days": "Thu", "start_time": "16:00"}).get_json()["id"]
        P("/api/enrollments", {"student_id": cls.s1, "batch_id": cls.b1})
        cls.S1, cls.T1 = cls.tok("s1@s45.test", PW), cls.tok("t1@s45.test", PW)
        cls.types = {r["code"] or r["name"]: r["id"] for r in cls.c.get("/api/revenue-types", headers=cls.H).get_json()}

    @classmethod
    def tok(cls, login, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    @classmethod
    def sql_(cls, q, a=()):
        con = sqlite3.connect(cls.path)
        try: r = con.execute(q, a).fetchall(); con.commit(); return r
        finally: con.close()

    def manual(self, data, files=None, hdr=None):
        if files is None: return self.c.post("/api/invoices/manual", json=data, headers=hdr or self.H)
        d = dict(data); d["file"] = (io.BytesIO(files[1]), files[0])
        return self.c.post("/api/invoices/manual", data=d, headers=hdr or self.H, content_type="multipart/form-data")

    # ---- revenue types ----
    def test_01_types(self):
        l = self.c.get("/api/revenue-types", headers=self.H).get_json()
        self.assertEqual([(r["name"], r["code"], r["built_in"]) for r in l], [("Monthly fees", "monthly", True), ("Registration fees", "registration", True)])
        self.assertEqual(l[0]["invoices"], 1)                                                   # the November invoice made on enrolment
        r = self.c.post("/api/revenue-types", json={"name": "  Books  "}, headers=self.H); self.assertEqual(r.status_code, 201)
        type(self).books = r.get_json()["id"]
        self.assertEqual(self.c.post("/api/revenue-types", json={"name": "books"}, headers=self.H).status_code, 409)
        self.assertEqual(self.c.post("/api/revenue-types", json={"name": ""}, headers=self.H).status_code, 400)
        self.assertEqual(self.c.patch(f"/api/revenue-types/{self.types['monthly']}", json={"is_active": False}, headers=self.H).status_code, 409)
        self.assertEqual(self.c.patch(f"/api/revenue-types/{self.types['monthly']}", json={"name": "Monthly tuition"}, headers=self.H).status_code, 200)
        self.c.patch(f"/api/revenue-types/{self.types['monthly']}", json={"name": "Monthly fees"}, headers=self.H)
        ex = self.c.post("/api/revenue-types", json={"name": "Exam fee"}, headers=self.H).get_json()["id"]
        self.assertEqual(self.c.patch(f"/api/revenue-types/{ex}", json={"is_active": False}, headers=self.H).status_code, 200)
        r = self.manual({"customer_name": "X", "revenue_type_id": ex, "amount_mvr": 10})
        self.assertEqual(r.status_code, 400); self.assertIn("revenue type", r.get_json()["error"])
        for h in (self.S1, self.T1): self.assertEqual(self.c.post("/api/revenue-types", json={"name": "Z"}, headers=h).status_code, 403)

    # ---- manual invoices ----
    def test_02_walk_in_paid_with_slip(self):
        r = self.manual({"customer_name": "Ahmed Walk-in", "customer_phone": "7771234", "revenue_type_id": self.books, "amount_mvr": "150",
                         "description": "Arabic workbook", "invoice_date": "2026-04-20", "paid": "1", "method": "cash", "paid_on": "2026-04-20"}, files=("IMG-WA.png", PNG))
        self.assertEqual(r.status_code, 201, r.get_json()); j = r.get_json(); i = j["invoice"]
        self.assertEqual((i["student_name"], i["walk_in"], i["status"], i["period"], i["revenue_type_name"], i["kind"]), ("Ahmed Walk-in", True, "paid", "2026-04", "Books", "manual"))
        self.assertTrue(i["number"].startswith("INV-202604-"))
        p = j["payments"][0]; self.assertIsNone(p["student_id"]); self.assertTrue(p["slip_id"])
        self.assertEqual(self.c.get(f"/api/payments/{p['id']}/receipt.pdf", headers=self.H).status_code, 200)
        self.assertEqual(self.c.get(f"/api/invoices/{i['id']}/invoice.pdf", headers=self.H).status_code, 200)
        self.assertEqual(self.c.get(f"/api/slips/{p['slip_id']}/file", headers=self.H).status_code, 200)
        self.assertEqual(self.c.get(f"/api/payments/{p['id']}/receipt.pdf", headers=self.S1).status_code, 404)   # not the student's
        row = [x for x in self.c.get("/api/payments", headers=self.H).get_json() if x["id"] == p["id"]][0]
        self.assertEqual((row["student_name"], row["revenue_type_name"]), ("Ahmed Walk-in", "Books"))
        found = self.c.get("/api/invoices?q=walk-in&status=all", headers=self.H).get_json()
        self.assertEqual([x["id"] for x in found], [i["id"]])
        self.assertEqual([x["id"] for x in self.c.get(f"/api/invoices?revenue_type={self.books}&status=all", headers=self.H).get_json()], [i["id"]])

    def test_03_student_manual_unpaid_and_linked(self):
        r = self.manual({"student_id": self.s1, "revenue_type_id": self.types["registration"], "amount_mvr": 100, "invoice_date": "2026-04-01", "due_date": "2026-04-10", "batch_id": self.b1})
        self.assertEqual(r.status_code, 201, r.get_json()); i = r.get_json()["invoice"]
        self.assertEqual((i["student_name"], i["course_name"], i["batch_code"], i["description"], i["overdue"]), ("S1", "Arabic", "A1", "Registration fees", True))
        mine = self.c.get("/api/my/fees", headers=self.S1).get_json()
        self.assertIn(i["id"], [x["id"] for x in mine["invoices"]])
        self.assertEqual(self.c.get(f"/api/students/{self.s1}/statement.pdf", headers=self.H).status_code, 200)
        self.assertEqual(self.c.get("/api/my/fees/statement.pdf", headers=self.S1).status_code, 200)

    def test_04_refusals(self):
        cases = [({"student_id": self.s1, "customer_name": "X", "revenue_type_id": self.books, "amount_mvr": 5}, 400, "not both"),
                 ({"revenue_type_id": self.books, "amount_mvr": 5}, 400, "Choose a student"),
                 ({"customer_name": "X", "revenue_type_id": self.books, "amount_mvr": 5, "batch_id": self.b1}, 400, "only be linked"),
                 ({"student_id": self.s1, "revenue_type_id": self.books, "amount_mvr": 5, "batch_id": self.b2}, 400, "not in that batch"),
                 ({"student_id": self.t1, "revenue_type_id": self.books, "amount_mvr": 5}, 404, "Student not found"),
                 ({"customer_name": "X", "amount_mvr": 5}, 400, "revenue type"),
                 ({"customer_name": "X", "revenue_type_id": self.books, "amount_mvr": "5.5"}, 400, "whole number"),
                 ({"customer_name": "X", "revenue_type_id": self.books, "amount_mvr": 5, "invoice_date": "2026-05-02", "due_date": "2026-05-01"}, 400, "before the invoice"),
                 ({"customer_name": "X", "revenue_type_id": self.books, "amount_mvr": 5, "paid": "1", "paid_amount_mvr": "6"}, 400, "more than the invoice"),
                 ({"customer_name": "X", "revenue_type_id": self.books, "amount_mvr": 5, "paid": "1", "paid_on": "2026-12-01"}, 400, "future")]
        n = self.sql_("SELECT COUNT(*) FROM invoices")[0][0]
        for data, code, msg in cases:
            r = self.manual(data); self.assertEqual(r.status_code, code, (data, r.get_json())); self.assertIn(msg, r.get_json()["error"])
        r = self.manual({"customer_name": "X", "revenue_type_id": self.books, "amount_mvr": "5", "paid": "1"}, files=("x.gif", b"GIF89a"))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.sql_("SELECT COUNT(*) FROM invoices")[0][0], n)
        for h in (self.S1, self.T1): self.assertEqual(self.manual({"customer_name": "X", "revenue_type_id": self.books, "amount_mvr": 5}, hdr=h).status_code, 403)

    def test_05_part_paid_then_mark_paid(self):
        r = self.manual({"customer_name": "Mariyam", "revenue_type_id": self.books, "amount_mvr": "300", "paid": "1", "paid_amount_mvr": "100", "method": "cash"}, files=("a.png", PNG))
        self.assertEqual(r.status_code, 201, r.get_json()); i = r.get_json()["invoice"]
        self.assertEqual((i["status"], i["balance"]), ("unpaid", 200))
        r = self.c.post("/api/payments/mark-paid", json={"invoice_ids": str(i["id"]), "method": "cash"}, headers=self.H)
        self.assertEqual(r.status_code, 201, r.get_json()); self.assertEqual(r.get_json()["invoices"][0]["status"], "paid")

    # ---- editing ----
    def test_06_edit_amount(self):
        nov = [i for i in self.c.get(f"/api/invoices?student_id={self.s1}&status=all", headers=self.H).get_json() if i["kind"] == "monthly"][0]
        E = lambda j: self.c.patch(f"/api/invoices/{nov['id']}", json=j, headers=self.H)
        self.assertEqual(E({"amount_mvr": 450}).status_code, 400)                                  # reason needed
        r = E({"amount_mvr": 450, "reason": "old fee in April"}); self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual((r.get_json()["invoice"]["amount_due_mvr"], r.get_json()["invoice"]["balance"]), (450, 450))
        self.c.post("/api/payments/mark-paid", json={"invoice_ids": str(nov["id"]), "method": "cash"}, headers=self.H)
        r = E({"amount_mvr": 400, "reason": "x"}); self.assertEqual(r.status_code, 409); self.assertIn("already paid", r.get_json()["error"])
        r = E({"amount_mvr": 500, "reason": "fee is 500"}); self.assertEqual(r.status_code, 200)
        self.assertEqual((r.get_json()["invoice"]["status"], r.get_json()["invoice"]["balance"]), ("unpaid", 50))   # paid 450 of 500
        r = E({"revenue_type_id": self.books, "description": "Corrected", "due_date": "2026-11-30"}); self.assertEqual(r.status_code, 200)
        i = r.get_json()["invoice"]; self.assertEqual((i["revenue_type_name"], i["description"], i["due_date"]), ("Books", "Corrected", "2026-11-30"))
        self.assertEqual(E({"customer_name": "Y"}).status_code, 400)                               # only for customers not in the portal
        self.assertEqual(E({"amount_mvr": "0", "reason": "x"}).status_code, 400)
        self.assertEqual(self.c.patch(f"/api/invoices/{nov['id']}", json={"amount_mvr": 1}, headers=self.S1).status_code, 403)
        self.assertIn("invoice_edit", [a["action"] for a in self.c.get("/api/audit", headers=self.H).get_json()])
        E({"revenue_type_id": self.types["monthly"]})

    def test_07_edit_walk_in_name(self):
        i = self.manual({"customer_name": "Hassan", "revenue_type_id": self.books, "amount_mvr": 20}).get_json()["invoice"]
        r = self.c.patch(f"/api/invoices/{i['id']}", json={"customer_name": "Hassan Ali", "customer_phone": "7654321"}, headers=self.H)
        self.assertEqual(r.status_code, 200); self.assertEqual((r.get_json()["invoice"]["student_name"], r.get_json()["invoice"]["student_phone"]), ("Hassan Ali", "7654321"))
        self.assertEqual(self.c.patch(f"/api/invoices/{i['id']}", json={"customer_name": " "}, headers=self.H).status_code, 400)

    # ---- reports ----
    def test_08_revenue_by_type_and_overdue(self):
        rev = self.c.get("/api/finance/revenue?date_from=2026-04-01&date_to=2026-11-30", headers=self.H).get_json()
        by = {r["revenue_type_name"]: r["collected"] for r in rev["by_type"]}
        self.assertEqual(sum(by.values()), rev["total_collected"]); self.assertIn("Books", by); self.assertIn("Monthly fees", by)
        self.assertIn("other", rev["by_kind"])
        self.assertEqual(self.c.get("/api/finance/dashboard", headers=self.H).status_code, 200)
        rep = self.c.get("/api/fees/report?month=2026-04", headers=self.H); self.assertEqual(rep.status_code, 200, rep.get_json())
        self.assertIn("Other (no course)", re.findall(r"Other \(no course\)", rep.get_data(as_text=True)) and ["Other (no course)"])
        self.assertEqual(self.c.get("/api/fees/report.xlsx?month=2026-04", headers=self.H).status_code, 200)
        self.manual({"customer_name": "Late Payer", "customer_phone": "7654321", "revenue_type_id": self.books, "amount_mvr": 20, "invoice_date": "2026-10-01"})
        od = self.c.get("/api/fees/overdue", headers=self.H).get_json()["items"]
        w = [i for i in od if i["student_name"] == "Late Payer"]
        self.assertEqual(len(w), 1); self.assertTrue(w[0]["links"]["student"]["whatsapp"].startswith("https://wa.me/9607654321"))
        r = self.c.post("/api/notifications/run?dry_run=0", headers=self.H); self.assertEqual(r.status_code, 200, r.get_json())

    def earn(self):
        return self.c.post("/api/earnings/calculate", json={"month": "2026-11", "dry_run": True}, headers=self.H).get_json()["totals"]["collected_mvr"]

    def test_09_teacher_earnings(self):
        e0 = self.earn()
        for rt, add in ((self.types["monthly"], 70), (self.books, 0)):
            r = self.manual({"student_id": self.s1, "batch_id": self.b1, "revenue_type_id": rt, "amount_mvr": 70, "paid": "1", "method": "cash"})
            self.assertEqual(r.status_code, 201, r.get_json())
            e1 = self.earn()
            self.assertEqual(e1 - e0, add); e0 = e1
        self.manual({"customer_name": "Z", "revenue_type_id": self.types["monthly"], "amount_mvr": 70, "paid": "1", "method": "cash"})   # no batch: not a teacher's
        self.assertEqual(self.earn(), e0)


class Upgrade(unittest.TestCase):
    def test_older_database_is_loosened_and_unchanged(self):
        import dbx
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        old = dbx.read_schema(base)
        for col in ("enrollment_id", "student_id", "course_id", "batch_id"):
            old = old.replace(f"  {col} INTEGER REFERENCES", f"  {col} INTEGER NOT NULL REFERENCES")   # as before v0.8.45 (also payments/slips student_id)
        old = re.sub(r"  customer_name TEXT,.*\n|  customer_phone TEXT,\n|  revenue_type_id INTEGER REFERENCES revenue_types\(id\),.*\n", "", old)
        path = os.path.join(tempfile.mkdtemp(), "old.db")
        con = sqlite3.connect(path); con.executescript(old)
        self.assertNotIn("customer_name", [r[1] for r in con.execute("PRAGMA table_info(invoices)")])
        con.execute("INSERT INTO users(id,email,password_hash,full_name,role,created_at) VALUES(5,'s@x','h','S','student','2026-01-01')")
        con.execute("INSERT INTO courses(id,name,monthly_fee_mvr) VALUES(1,'C',500)")
        con.execute("INSERT INTO batches(id,course_id,code) VALUES(1,1,'B')")
        con.execute("INSERT INTO enrollments(id,student_id,batch_id,status,enrolled_at) VALUES(1,5,1,'active','2026-01-01')")
        con.execute("INSERT INTO invoices(id,enrollment_id,student_id,course_id,batch_id,period,description,amount_mvr,amount_due_mvr,due_date,created_at) VALUES(1,1,5,1,1,'2026-04','x',500,500,'2026-04-10','t')")
        con.commit(); before = con.execute("SELECT * FROM invoices").fetchall(); con.close()
        c = dbx.Conn(None, path, ()); dbx.upgrade_v0845(c); c.commit()
        con = sqlite3.connect(path)
        self.assertEqual({r[1]: r[3] for r in con.execute("PRAGMA table_info(invoices)") if r[1] in ("enrollment_id", "student_id", "course_id", "batch_id")},
                         {"enrollment_id": 0, "student_id": 0, "course_id": 0, "batch_id": 0})
        self.assertEqual([r[3] for r in con.execute("PRAGMA table_info(payments)") if r[1] == "student_id"], [0])
        self.assertEqual([r[3] for r in con.execute("PRAGMA table_info(payment_slips)") if r[1] == "student_id"], [0])
        self.assertEqual(con.execute("SELECT * FROM invoices").fetchall()[0][:len(before[0])], before[0])
        self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual([r[0] for r in con.execute("SELECT code FROM revenue_types ORDER BY id")], ["monthly", "registration"])
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("INSERT INTO invoices(period,description,kind,amount_mvr,amount_due_mvr,due_date,created_at,customer_name) VALUES('2026-11','w','manual',5,5,'2026-11-13','t','Walk in')")
        con.commit(); con.close()
        c = dbx.Conn(None, path, ()); dbx.upgrade_v0845(c); c.commit()                         # a second run changes nothing
        self.assertEqual(sqlite3.connect(path).execute("SELECT COUNT(*) FROM revenue_types").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
