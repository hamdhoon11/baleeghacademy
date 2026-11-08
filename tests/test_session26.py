"""Session 26: payment reports per batch and month, student history, CSV and Excel. Hand-counted seed, checked against SQL."""
import csv, datetime as dt, io, os, sqlite3, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PW = "Passw0rd!x1"
MVT = dt.timezone(dt.timedelta(hours=5))


class S26(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s26.test", ADMIN_PASSWORD="AdminPass123")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path}); cls.c = cls.app.test_client()
        cls.app.config["NOW"] = lambda: dt.datetime(2027, 3, 10, 12, 0, tzinfo=MVT)
        cls.H = cls.tok("admin@s26.test", "AdminPass123")
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, role, **kw: P("/api/users", {"email": e, "password": PW, "full_name": e, "role": role, **kw}).get_json()["id"]
        t = mk("t@s26.test", "teacher")
        cls.s = [mk(f"s{i}@s26.test", "student") for i in range(1, 7)]
        cls.nofees = mk("nf@s26.test", "admin", permissions=["finance"])
        cls.ar = P("/api/courses", {"name": "Arabic", "monthly_fee_mvr": 1000, "status": "open"}).get_json()["id"]
        cls.tu = P("/api/courses", {"name": "Grade 8 Mathematics", "kind": "tuition", "code": "G8M", "monthly_fee_mvr": 600, "status": "open"}).get_json()["id"]
        bt = lambda cid, code: P("/api/batches", {"course_id": cid, "code": code, "teacher_id": t, "capacity": 9, "days": "Mon", "start_time": "16:00"}).get_json()["id"]
        cls.b1, cls.b2 = bt(cls.ar, "A1"), bt(cls.tu, "M1")
        # s1,s2,s3,s4 in Arabic; s5 in tuition; s6 not enrolled
        for s, b in ((0, cls.b1), (1, cls.b1), (2, cls.b1), (3, cls.b1), (4, cls.b2)): P("/api/enrollments", {"student_id": cls.s[s], "batch_id": b})
        inv = lambda s: cls.c.get(f"/api/invoices?student_id={cls.s[s]}", headers=cls.H).get_json()[0]["id"]
        cls.i = [inv(k) for k in range(5)]
        pay = lambda i, amt, day: P("/api/payments", {"invoice_id": cls.i[i], "amount_mvr": amt, "method": "cash", "paid_on": day})
        for r in (pay(0, 400, "2027-03-02"), pay(0, 600, "2027-03-08"),      # s1 paid in full in two parts
                  pay(1, 250, "2027-03-05"),                                  # s2 partial
                  pay(4, 600, "2027-03-09")):                                 # s5 tuition paid
            assert r.status_code == 201, r.get_json()
        gone = pay(2, 1000, "2027-03-06"); assert gone.status_code == 201       # s3 paid then reversed -> unpaid
        assert P(f"/api/payments/{gone.get_json()['payment']['id']}/reverse", {"reason": "entered twice"}).status_code == 200
        r = P(f"/api/invoices/{cls.i[3]}/waive", {"reason": "scholarship"}); assert r.status_code == 200, r.get_json()   # s4 waived
        # an enrolment dropped after being invoiced still appears (it has an invoice) -- use a 7th student
        cls.s7 = mk("s7@s26.test", "student")
        e = P("/api/enrollments", {"student_id": cls.s7, "batch_id": cls.b1}).get_json()
        cls.i7 = cls.c.get(f"/api/invoices?student_id={cls.s7}", headers=cls.H).get_json()[0]["id"]
        assert cls.c.patch(f"/api/enrollments/{e['id']}", json={"status": "dropped"}, headers=cls.H).status_code == 200
        cls.F, cls.T, cls.ST = (cls.tok(x, PW) for x in ("nf@s26.test", "t@s26.test", "s1@s26.test"))

    @classmethod
    def tok(cls, login, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    def sql(self, q, a=()):
        con = sqlite3.connect(self.path)
        try: return con.execute(q, a).fetchall()
        finally: con.close()

    def rep(self, qs="month=2027-03"):
        r = self.c.get("/api/fees/payment-report?" + qs, headers=self.H); self.assertEqual(r.status_code, 200, r.get_json()); return r.get_json()

    def by_name(self, r): return {x["student_name"]: x for x in r["rows"] if x["student_name"].startswith("s")}   # the seeded demo student has no invoice and is ignored here

    def test_statuses_and_amounts(self):
        r = self.rep(); n = self.by_name(r)
        self.assertEqual(n["s1@s26.test"]["status"], "paid");     self.assertEqual((n["s1@s26.test"]["paid_mvr"], n["s1@s26.test"]["balance_mvr"]), (1000, 0))
        self.assertEqual(n["s1@s26.test"]["status_label"], "Paid")
        self.assertEqual(n["s2@s26.test"]["status_label"], "Partially Paid"); self.assertEqual((n["s2@s26.test"]["paid_mvr"], n["s2@s26.test"]["balance_mvr"]), (250, 750))
        self.assertEqual(n["s3@s26.test"]["status_label"], "Unpaid");         self.assertEqual((n["s3@s26.test"]["paid_mvr"], n["s3@s26.test"]["balance_mvr"]), (0, 1000))
        self.assertEqual(n["s4@s26.test"]["status"], "waived")
        self.assertEqual(n["s5@s26.test"]["status"], "paid"); self.assertEqual(n["s5@s26.test"]["monthly_fee_mvr"], 600); self.assertEqual(n["s5@s26.test"]["kind"], "tuition")
        self.assertNotIn("s6@s26.test", n)                      # not enrolled anywhere

    def test_payment_dates(self):
        n = self.by_name(self.rep())
        self.assertEqual([p["paid_on"] for p in n["s1@s26.test"]["payments"]], ["2027-03-02", "2027-03-08"])
        self.assertEqual(n["s1@s26.test"]["last_payment"], "2027-03-08")
        self.assertEqual(n["s3@s26.test"]["payments"], [])      # the reversed payment is not shown as paid

    def test_totals_equal_invoices_and_payments(self):
        r = self.rep(); T = r["totals"]
        inv = self.sql("SELECT COALESCE(SUM(amount_due_mvr-waived_mvr),0), COALESCE(SUM(paid_mvr),0), COUNT(*) FROM invoices WHERE period='2027-03' AND status!='void'")[0]
        pays = self.sql("SELECT COALESCE(SUM(p.amount_mvr),0) FROM payments p JOIN invoices i ON i.id=p.invoice_id WHERE i.period='2027-03' AND i.status!='void' AND p.reversed_at IS NULL")[0][0]
        self.assertEqual(T["due"], inv[0]); self.assertEqual(T["paid"], inv[1]); self.assertEqual(T["paid"], pays); self.assertEqual(T["invoice_count"], inv[2])
        self.assertEqual(T["balance"], sum(x["balance_mvr"] for x in r["rows"]))
        self.assertEqual(T["due"] - T["paid"], T["balance"])
        self.assertEqual(sum(T[k + "_count"] for k in ("paid", "partial", "unpaid", "waived", "none")), T["students"])
        self.assertEqual(T["paid"], 1000 + 250 + 600)           # hand count

    def test_dropped_student_with_invoice_listed(self):
        n = self.by_name(self.rep())
        self.assertIn("s7@s26.test", n); self.assertEqual(n["s7@s26.test"]["enrollment_status"], "dropped"); self.assertEqual(n["s7@s26.test"]["status"], "unpaid")

    def test_filters(self):
        self.assertEqual({x["student_name"] for x in self.rep(f"month=2027-03&batch_id={self.b2}")["rows"]}, {"s5@s26.test"})
        self.assertEqual(len([x for x in self.rep(f"month=2027-03&course_id={self.ar}")["rows"] if x["student_name"].startswith("s")]), 5)
        self.assertEqual({x["student_name"] for x in self.rep("month=2027-03&kind=tuition")["rows"]}, {"s5@s26.test"})
        self.assertEqual({x["student_name"] for x in self.rep("month=2027-03&status=partial")["rows"]}, {"s2@s26.test"})
        self.assertEqual(self.rep("month=2027-03&status=partial")["totals"]["balance"], 750)
        self.assertEqual({x["student_name"] for x in self.rep("month=2027-03&status=none")["rows"]}, {"Demo Student"})

    def test_month_without_invoices_shows_no_invoice(self):
        r = self.rep("month=2027-03&status=none"); self.assertEqual({x["student_name"] for x in r["rows"]}, {"Demo Student"})
        d = r["rows"][0]; self.assertEqual((d["amount_due_mvr"], d["balance_mvr"], d["paid_mvr"]), (0, 0, 0)); self.assertGreater(d["monthly_fee_mvr"], 0)
        e = self.rep("month=2027-02")["rows"]; self.assertFalse([x for x in e if x["student_name"].startswith("s")])   # none of my students existed in February

    def test_bad_filters(self):
        for q in ("month=2027-13", "month=abc", "kind=other", "status=late", "course_id=x", "batch_id=1;DROP"):
            self.assertEqual(self.c.get("/api/fees/payment-report?" + q, headers=self.H).status_code, 400, q)

    def test_history(self):
        h = self.c.get(f"/api/fees/student-history/{self.s[1]}", headers=self.H).get_json()
        self.assertEqual(h["totals"], {"due": 1000, "paid": 250, "balance": 750}); self.assertEqual(h["invoices"][0]["payments"][0]["amount_mvr"], 250)
        h3 = self.c.get(f"/api/fees/student-history/{self.s[2]}", headers=self.H).get_json()
        self.assertEqual(h3["totals"]["paid"], 0); self.assertTrue(h3["invoices"][0]["payments"][0]["reversed_at"])   # reversal visible in history
        self.assertEqual(self.c.get("/api/fees/student-history/999999", headers=self.H).status_code, 404)

    def test_csv_matches_report(self):
        r = self.c.get("/api/fees/payment-report.csv?month=2027-03", headers=self.H)
        self.assertEqual(r.status_code, 200); self.assertIn("text/csv", r.headers["Content-Type"]); self.assertIn("payments-2027-03.csv", r.headers["Content-Disposition"])
        lines = list(csv.reader(io.StringIO(r.get_data(as_text=True))))
        rep = self.rep()
        self.assertEqual(len(lines) - 1, len(rep["rows"])); self.assertEqual(sum(int(l[8]) for l in lines[1:]), rep["totals"]["paid"])
        self.assertEqual(lines[0][10], "Status")
        self.assertTrue(self.sql("SELECT 1 FROM audit_log WHERE action='export_payment_report'"))

    def test_xlsx(self):
        from openpyxl import load_workbook
        r = self.c.get("/api/fees/payment-report.xlsx?month=2027-03&status=partial", headers=self.H)
        self.assertEqual(r.status_code, 200); self.assertIn("spreadsheetml", r.headers["Content-Type"]); self.assertIn(".xlsx", r.headers["Content-Disposition"])
        ws = load_workbook(io.BytesIO(r.data)).active
        vals = [[c.value for c in row] for row in ws.iter_rows()]
        self.assertEqual(vals[0][0], "Student ID"); self.assertEqual(len(vals), 2); self.assertEqual(vals[1][10], "Partially Paid"); self.assertEqual(vals[1][8], 250)

    def test_to_xlsx_helper_is_formula_safe(self):
        from openpyxl import load_workbook
        import payreports
        ws = load_workbook(io.BytesIO(payreports.to_xlsx([["=1+1", 5], {"A": "@x", "B": 6}][:1] + [["@x", 6]], ["A", "B"]))).active
        self.assertEqual(ws["A2"].value, "'=1+1"); self.assertEqual(ws["A3"].value, "'@x"); self.assertEqual(ws["B3"].value, 6)

    def test_permissions(self):
        urls = ["/api/fees/payment-report", "/api/fees/payment-report.csv", "/api/fees/payment-report.xlsx", f"/api/fees/student-history/{self.s[0]}"]
        for u in urls:
            self.assertEqual(self.c.get(u).status_code, 401, u)
            for h in (self.F, self.T, self.ST): self.assertEqual(self.c.get(u, headers=h).status_code, 403, u)
            self.assertEqual(self.c.get(u, headers=self.H).status_code, 200, u)


if __name__ == "__main__":
    unittest.main()
