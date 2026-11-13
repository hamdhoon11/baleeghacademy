"""v0.8.43: the office marks invoices paid with the slip the person sent (WhatsApp etc.), one invoice or several at once;
students who started earlier are billed from their start month; Generate can make a range of months."""
import datetime as dt, io, os, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MVT = dt.timezone(dt.timedelta(hours=5))
PW = "Password123"
PNG = b"\x89PNG\r\n\x1a\n" + b"whatsapp screenshot" * 20


class MarkPaid(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        old = os.environ.get("SEED_DEMO")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s43.test", ADMIN_PASSWORD="AdminPass123", SEED_DEMO="0")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path, "UPLOAD_DIR": os.path.join(tmp, "up")}); cls.c = cls.app.test_client()
        cls.app.config["NOW"] = lambda: dt.datetime(2026, 11, 13, 17, 0, tzinfo=MVT)
        cls.H = cls.tok("admin@s43.test", "AdminPass123")
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, role, **kw: P("/api/users", {"email": e, "password": PW, "full_name": kw.pop("name", e.split("@")[0]), "role": role, **kw}).get_json()["id"]
        cls.t1 = mk("t1@s43.test", "teacher")
        cls.s1, cls.s2, cls.s3 = mk("s1@s43.test", "student"), mk("s2@s43.test", "student"), mk("s3@s43.test", "student")
        cls.sql_("UPDATE users SET must_change_password=0")
        cls.course = P("/api/courses", {"name": "Arabic", "monthly_fee_mvr": 500, "status": "open"}).get_json()["id"]
        cls.b1 = P("/api/batches", {"course_id": cls.course, "code": "A1", "teacher_id": cls.t1, "capacity": 9, "days": "Wed", "start_time": "16:00"}).get_json()["id"]
        cls.S1, cls.T1 = cls.tok("s1@s43.test", PW), cls.tok("t1@s43.test", PW)

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

    # ---- start date in the past ----
    def test_01_enrol_with_april_start_bills_april_to_november(self):
        r = self.c.post("/api/enrollments", json={"student_id": self.s1, "batch_id": self.b1, "start_date": "2026-04-05"}, headers=self.H)
        self.assertEqual(r.status_code, 201, r.get_json()); self.assertEqual(r.get_json()["earlier_invoices"], 7)
        ps = [i["period"] for i in self.invs(self.s1)]
        self.assertEqual(ps, ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11"])
        self.assertTrue(all(i["overdue"] for i in self.invs(self.s1) if i["period"] < "2026-11"))

    def test_02_start_date_checks(self):
        for bad, msg in (("2026-11-20", "future"), ("2024-01-01", "two years"), ("01/04/2026", "look like")):
            r = self.c.post("/api/enrollments", json={"student_id": self.s3, "batch_id": self.b1, "start_date": bad}, headers=self.H)
            self.assertEqual(r.status_code, 400); self.assertIn(msg, r.get_json()["error"])

    def test_03_no_start_date_bills_only_this_month(self):
        r = self.c.post("/api/enrollments", json={"student_id": self.s2, "batch_id": self.b1}, headers=self.H)
        self.assertEqual(r.status_code, 201); self.assertEqual(r.get_json()["earlier_invoices"], 0)
        self.assertEqual([i["period"] for i in self.invs(self.s2)], ["2026-11"])

    # ---- mark paid ----
    def test_04_one_invoice_with_whatsapp_slip(self):
        apr = self.invs(self.s1)[0]
        r = self.paid({"invoice_ids": str(apr["id"]), "method": "bank_transfer", "paid_on": "2026-04-08", "reference": "BML123"}, files=("IMG-20260408-WA0001.png", PNG))
        self.assertEqual(r.status_code, 201, r.get_json()); j = r.get_json()
        self.assertEqual(j["total_mvr"], 500); self.assertEqual(j["invoices"][0]["status"], "paid")
        p = j["payments"][0]; self.assertEqual(p["paid_on"], "2026-04-08"); self.assertTrue(p["slip_id"])
        s = self.sql_("SELECT status, amount_mvr, transfer_date, reference FROM payment_slips WHERE id=?", (p["slip_id"],))[0]
        self.assertEqual(s, ("verified", 500, "2026-04-08", "BML123"))
        self.assertEqual(self.c.get("/api/slips?status=pending", headers=self.H).get_json(), [])        # never in the queue to check
        f = self.c.get(f"/api/slips/{p['slip_id']}/file", headers=self.H); self.assertEqual(f.status_code, 200); self.assertEqual(f.data, PNG)
        self.assertEqual(self.c.get(f"/api/slips/{p['slip_id']}/file", headers=self.S1).status_code, 200)   # the student sees it too
        lst = self.c.get("/api/payments", headers=self.H).get_json()
        self.assertEqual([x["slip_file_name"] for x in lst if x["id"] == p["id"]], ["IMG-20260408-WA0001.png"])
        self.assertEqual(self.c.get(f"/api/payments/{p['id']}/receipt.pdf", headers=self.H).status_code, 200)

    def test_05_several_months_one_slip(self):
        ids = [i["id"] for i in self.invs(self.s1) if i["period"] in ("2026-05", "2026-06", "2026-07")]
        r = self.paid({"invoice_ids": ",".join(map(str, ids)), "method": "bank_transfer", "paid_on": "2026-07-02"}, files=("slip.pdf", b"%PDF-1.4 x"))
        self.assertEqual(r.status_code, 201, r.get_json()); j = r.get_json()
        self.assertEqual(len(j["payments"]), 3); self.assertEqual(j["total_mvr"], 1500)
        self.assertEqual(len({p["receipt_no"] for p in j["payments"]}), 3)
        self.assertEqual(len(self.sql_("SELECT DISTINCT file FROM payment_slips WHERE id IN (%s)" % ",".join(str(p["slip_id"]) for p in j["payments"]))), 1)   # stored once

    def test_06_without_a_slip_and_part_payment(self):
        aug = [i for i in self.invs(self.s1) if i["period"] == "2026-08"][0]
        r = self.paid({"invoice_ids": str(aug["id"]), "amount_mvr": "200", "method": "cash", "paid_on": "2026-08-10"})
        self.assertEqual(r.status_code, 201, r.get_json()); i = r.get_json()["invoices"][0]
        self.assertEqual((i["status"], i["balance"]), ("unpaid", 300)); self.assertIsNone(r.get_json()["payments"][0]["slip_id"])
        r = self.c.post("/api/payments/mark-paid", json={"invoice_id": aug["id"], "method": "cash", "paid_on": "2026-08-20"}, headers=self.H)   # JSON works too; default = the balance
        self.assertEqual(r.status_code, 201, r.get_json()); self.assertEqual(r.get_json()["invoices"][0]["status"], "paid")

    def test_07_refusals_leave_nothing(self):
        open_ = [i for i in self.invs(self.s1) if i["status"] == "unpaid"]
        n_slips, n_pay = self.sql_("SELECT COUNT(*) FROM payment_slips")[0][0], self.sql_("SELECT COUNT(*) FROM payments")[0][0]
        paid = [i for i in self.invs(self.s1) if i["status"] == "paid"][0]
        cases = [({"invoice_ids": str(open_[0]["id"]), "paid_on": "2026-12-01"}, 400, "future"),
                 ({"invoice_ids": str(open_[0]["id"]), "amount_mvr": "900"}, 400, "more than the balance"),
                 ({"invoice_ids": f"{open_[0]['id']},{open_[1]['id']}", "amount_mvr": "100"}, 400, "in full"),
                 ({"invoice_ids": f"{open_[0]['id']},{paid['id']}"}, 409, "nothing to pay"),
                 ({"invoice_ids": "", "method": "cash"}, 400, "Choose the invoices"),
                 ({"invoice_ids": str(open_[0]["id"]), "method": "cheque"}, 400, "how it was paid")]
        for data, code, msg in cases:
            r = self.paid(data, files=("s.png", PNG))
            self.assertEqual(r.status_code, code, (data, r.get_json())); self.assertIn(msg, r.get_json()["error"])
        r = self.paid({"invoice_ids": str(open_[0]["id"])}, files=("s.gif", b"GIF89a"))
        self.assertEqual(r.status_code, 400); self.assertIn("PDF, JPG or PNG", r.get_json()["error"])
        self.assertEqual(self.sql_("SELECT COUNT(*) FROM payment_slips")[0][0], n_slips); self.assertEqual(self.sql_("SELECT COUNT(*) FROM payments")[0][0], n_pay)
        self.assertEqual([i["status"] for i in self.invs(self.s1) if i["id"] == open_[0]["id"]], ["unpaid"])

    def test_08_student_slip_waiting_gives_a_warning(self):
        sep = [i for i in self.invs(self.s1) if i["period"] == "2026-09"][0]
        r = self.c.post(f"/api/invoices/{sep['id']}/slips", data={"amount_mvr": "500", "transfer_date": "2026-11-01", "file": (io.BytesIO(PNG), "mine.png")},
                        headers=self.S1, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 201, r.get_json())
        r = self.paid({"invoice_ids": str(sep["id"]), "paid_on": "2026-11-01"})
        self.assertEqual(r.status_code, 201); self.assertIn("waiting in Slips to check", r.get_json()["warnings"][0])

    def test_09_tell_the_student_only_when_asked(self):
        before = self.sql_("SELECT COUNT(*) FROM notifications WHERE user_id=?", (self.s2,))[0][0]
        nov = self.invs(self.s2)[0]
        r = self.paid({"invoice_ids": str(nov["id"]), "amount_mvr": "100", "paid_on": "2026-11-12"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.sql_("SELECT COUNT(*) FROM notifications WHERE user_id=?", (self.s2,))[0][0], before)
        r = self.paid({"invoice_ids": str(nov["id"]), "amount_mvr": "100", "paid_on": "2026-11-12", "notify": "1"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.sql_("SELECT COUNT(*) FROM notifications WHERE user_id=?", (self.s2,))[0][0], before + 1)

    def test_10_reverse_keeps_the_slip_marked(self):
        oct_ = [i for i in self.invs(self.s1) if i["period"] == "2026-10"][0]
        p = self.paid({"invoice_ids": str(oct_["id"]), "paid_on": "2026-10-05"}, files=("o.png", PNG)).get_json()["payments"][0]
        r = self.c.post(f"/api/payments/{p['id']}/reverse", json={"reason": "wrong student"}, headers=self.H); self.assertEqual(r.status_code, 200)
        self.assertEqual(self.sql_("SELECT status FROM payment_slips WHERE id=?", (p["slip_id"],))[0][0], "reversed")
        self.assertEqual(r.get_json()["invoice"]["status"], "unpaid")

    def test_11_only_fee_admins(self):
        inv = self.invs(self.s2)[0]
        for h in (self.S1, self.T1):
            self.assertEqual(self.paid({"invoice_ids": str(inv["id"])}, hdr=h).status_code, 403)

    # ---- Generate a range ----
    def test_12_generate_from_april(self):
        con = sqlite3.connect(self.path)
        con.execute("UPDATE enrollments SET enrolled_at='2026-03-31 20:00:00' WHERE student_id=?", (self.s2,)); con.commit(); con.close()   # 1 April, Maldives time
        r = self.c.post("/api/invoices/generate", json={"from_month": "2026-04", "month": "2026-11"}, headers=self.H)
        self.assertEqual(r.status_code, 200, r.get_json()); j = r.get_json()
        self.assertEqual(j["created"], 7); self.assertEqual(len(j["months"]), 8)
        self.assertEqual(len(self.invs(self.s2)), 8)
        self.assertEqual(self.c.post("/api/invoices/generate", json={"from_month": "2026-04", "month": "2026-11"}, headers=self.H).get_json()["created"], 0)
        self.assertEqual(self.c.post("/api/invoices/generate", json={"from_month": "2026-12", "month": "2026-11"}, headers=self.H).status_code, 400)


if __name__ == "__main__":
    unittest.main()
