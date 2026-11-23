"""v0.8.64: the academy's Excel registry and the portal. Revenue and expense imports in the registry's layout (the workbook can be uploaded
as it is), registry codes, USD expenses, the income statement (Monthly Report), the registry workbook export, and the fee grid's
months-late, comments, paid/not-paid counts and Excel.

The workbook here is made up, but has the real registry's shape: a title row above the column names, scratch cells to the right, numbered
empty rows and SUM rows at the bottom, a Student ID typed with the letter I, two payments for the same month, a USD expense with a formula."""
import datetime as dt, io, os, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MVT = dt.timezone(dt.timedelta(hours=5))
PW = "Password123"


def registry_book(revenue, expenses, extra_sheets=True):
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.title = "Student Payment History_A1B1"   # the first sheet is not the registry (as in the real file)
    ws["A1"] = "ARABIC LEVEL 1 - BATCH 1"
    r = wb.create_sheet("Revenue Registry")
    r["A1"] = "Revenue Registry (Invoices)"
    r.append(["No", "Date", "Student ID", "Name", "Course", "Revenue Code", "Payment Type", "GST %", "Discount", "Amount Due", "Total Paid", "Invoice No."])
    for row in revenue: r.append(row)
    r["P5"], r["Q5"] = "Month", "Revenue"                                              # scratch cells with no column name
    for k in range(3): r.append([None] * 11 + [f"INV2026/9{k}"])                       # numbered empty rows
    e = wb.create_sheet("Expense Registry")
    e["A1"] = "Invoice registry ( Expenses )"
    e.append(["No", "Date", "GST No.", "Name", "Invoice No.", "Expense Code", "Expense Type", "MVR", "GST %", "Discount", "Amount Due", "$", "Total"])
    for row in expenses: e.append(row)
    n = e.max_row
    e.append([None] * 12 + [f"=SUM(M3:M{n})"])                                         # the totals row
    if extra_sheets: wb.create_sheet("Monthly Report")["B2"] = "Arabic Level 1_Income Statement_Report 2026"
    out = io.BytesIO(); wb.save(out); return out.getvalue()


class V0864(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        old = os.environ.get("SEED_DEMO")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@v64.test", ADMIN_PASSWORD="AdminPass123", SEED_DEMO="0")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path}); cls.c = cls.app.test_client()
        cls.app.config["NOW"] = lambda: dt.datetime(2026, 11, 23, 17, 0, tzinfo=MVT)
        cls.sql_("UPDATE users SET must_change_password=0")
        cls.H = cls.tok("admin@v64.test", "AdminPass123")
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, role, name: P("/api/users", {"email": e, "password": PW, "full_name": name, "role": role, "phone": "7771234"}).get_json()["id"]
        cls.t1 = mk("t1@v64.test", "teacher", "Teacher One")
        cls.course = P("/api/courses", {"name": "Arabic Test", "code": "AT1", "monthly_fee_mvr": 350, "registration_fee_mvr": 350, "status": "open"}).get_json()["id"]
        cls.b1 = P("/api/batches", {"course_id": cls.course, "code": "L1001", "teacher_id": cls.t1, "capacity": 30}).get_json()["id"]
        cls.b2 = P("/api/batches", {"course_id": cls.course, "code": "L1002", "teacher_id": cls.t1, "capacity": 30}).get_json()["id"]
        cls.st = {}
        for code, name, b in (("BAL/AT1/001", "Test Student A", "b1"), ("BAL/AT1/002", "Test Student B", "b1"), ("BAL/AT1/021", "Test Student C", "b1"),
                              ("BAL/AT1/030", "Test Student D", "b2"), ("BAL/AT1/040", "Two Batches", "b1")):
            uid = mk(code.replace("/", "").lower() + "@v64.test", "student", name)
            cls.sql_("UPDATE students SET student_code=? WHERE user_id=?", (code, uid))
            P("/api/enrollments", {"student_id": uid, "batch_id": getattr(cls, b)})
            cls.st[code] = uid
        P("/api/enrollments", {"student_id": cls.st["BAL/AT1/040"], "batch_id": cls.b2})
        cls.sql_("UPDATE users SET must_change_password=0")
        cls.T1 = cls.tok("t1@v64.test", PW)
        cls.F = cls.limited("fin@v64.test", "finance")       # Finance only
        cls.FE = cls.limited("fee@v64.test", "fees")         # Fees only

    @classmethod
    def limited(cls, email, perm):
        uid = cls.c.post("/api/users", json={"email": email, "password": PW, "full_name": email[:3], "role": "admin", "phone": "7771234"}, headers=cls.H).get_json()["id"]
        cls.sql_("UPDATE users SET permissions=?, must_change_password=0 WHERE id=?", (perm, uid))
        return cls.tok(email, PW)

    @classmethod
    def tok(cls, login, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    @classmethod
    def sql_(cls, q, a=()):
        con = sqlite3.connect(cls.path)
        try: r = con.execute(q, a).fetchall(); con.commit(); return r
        finally: con.close()

    def up(self, kind, data, dry=True, q="", h=None):
        r = self.c.post(f"/api/import/{kind}?dry_run={1 if dry else 0}{q}", data={"file": (io.BytesIO(data), "registry.xlsx")}, headers=h or self.H, content_type="multipart/form-data")
        return r

    def book(self, r):
        from openpyxl import load_workbook
        self.assertEqual(r.status_code, 200, r.data[:200]); return load_workbook(io.BytesIO(r.data))

    REV = [[1, dt.datetime(2026, 4, 2), "BAL/AT1/001", "Test Student A", "Arabic - L1001", 1001, "Registration Fee", "-", "-", "-", 350, "INV2026/001"],
           [2, dt.datetime(2026, 4, 18), "BAL/AT1/002", "Test Student B", "Arabic - L1001", 1001, "Registration Fee", "-", "-", "-", 350, "INV2026/002"],
           [3, dt.datetime(2026, 4, 18), "BAL/AT1/002", "Test Student B", "Arabic - L1001", 1003, "Advance Payment", "-", "-", "-", 150, "INV2026/002"],
           [4, dt.datetime(2026, 5, 3), "BAL/ATI/021", "Test Student C", "Arabic - L1001", 1002, "Monthly Fee", "-", "-", "-", 350, "INV2026/003"],
           [5, dt.datetime(2026, 6, 1), "BAL/AT1/002", "Test Student B", "Arabic - L1001", 1002, "Monthly Fee", "-", "-", "-", 350, "INV2026/004"],
           [6, dt.datetime(2026, 6, 1), "BAL/AT1/002", "Test Student B", "Arabic - L1001", 1002, "Monthly Fee", "-", "-", "-", 350, "INV2026/005"],   # same month again
           [7, dt.datetime(2026, 4, 7), "BAL/AT1/005", "Left Student", "Arabic - L1001", 1001, "Registration Fee", "-", "-", "-", 350, "INV2026/006"],   # not in the portal
           [8, dt.datetime(2026, 11, 2), "BAL/AT1/030", "Test Student D", "Arabic - L1002", 1002, "Monthly Fee", "-", "-", "-", 350, "INV2026/007"],  # pays the generated November invoice
           [9, dt.datetime(2026, 8, 11), "BAL/AT1/030", "Test Student D", "Arabic - L1002", 1002, "Monthly Fee", "-", "-", "-", 175, "INV2026/008"],  # half month
           [10, dt.datetime(2026, 7, 1), "BAL/AT1/040", "Two Batches", "", 1002, "Monthly Fee", "-", "-", "-", 350, "INV2026/009"]]              # two batches, no Course

    EXP = [[1, dt.datetime(2026, 1, 1), "GST-TEST-1", "Google", 9000000001, 5002, "Maintenance Expense", None, None, "-", "-", 12.59, "=+L3*15.42+H3"],
           [2, dt.datetime(2026, 1, 29), "-", "Meta ads", "-", 5001, "Marketing Expense", None, "-", "-", "-", 6, "=+L4*15.42+H4"],
           [3, dt.datetime(2026, 3, 12), "GST-TEST-2", "Example Furniture Pvt Ltd", "EX-0001", 5004, "Cap-EX", 1944, 144, "-", "-", None, "=+L5*15.42+H5"],
           [4, dt.datetime(2026, 6, 8), None, "Test Staff Pay", "-", 5005, "Employee Salary", None, None, None, None, None, 700]]

    # ---- 1. templates in the registry's layout ----
    def test_01_templates(self):
        wb = self.book(self.c.get("/api/import/revenue/template.xlsx", headers=self.H))
        self.assertEqual(wb.sheetnames, ["Revenue Registry", "Lists", "Instructions"])
        ws = wb["Revenue Registry"]
        self.assertEqual(ws["A1"].value, "Revenue Registry (Invoices)")
        self.assertEqual([c.value for c in ws[2]][:12], ["No", "Date", "Student ID", "Name", "Course", "Revenue Code", "Payment Type", "GST %", "Discount", "Amount Due", "Total Paid", "Invoice No."])
        self.assertEqual(ws.max_row, 2)                                                    # nothing to import by mistake
        self.assertIn("BAL/AT1/001", [c.value for c in wb["Lists"]["A"]])
        self.assertIn("1001", [c.value for c in wb["Lists"]["E"]])                        # the built-in types have the registry's codes
        wb = self.book(self.c.get("/api/import/expenses/template.xlsx", headers=self.H))
        self.assertEqual(wb.sheetnames[0], "Expense Registry")
        self.assertEqual([c.value for c in wb["Expense Registry"][2]][:13], ["No", "Date", "GST No.", "Name", "Invoice No.", "Expense Code", "Expense Type", "MVR", "GST %", "Discount", "Amount Due", "$", "Total"])
        for path, ok, bad in (("/api/import/revenue/template.xlsx", self.FE, self.F), ("/api/import/expenses/template.xlsx", self.F, self.FE)):
            self.assertEqual(self.c.get(path, headers=ok).status_code, 200); self.assertEqual(self.c.get(path, headers=bad).status_code, 403)
            self.assertEqual(self.c.get(path, headers=self.T1).status_code, 403)

    # ---- 2. revenue: check, then import, then import again ----
    def test_02_revenue(self):
        data = registry_book(self.REV, self.EXP)
        before = self.sql_("SELECT COUNT(*) FROM payments")[0][0]
        r = self.up("revenue", data).get_json()
        st = {x["row"]: x for x in r["rows"]}
        self.assertEqual(r["total"], 13)                                                   # 10 payments and the 3 numbered empty rows
        self.assertEqual(self.sql_("SELECT COUNT(*) FROM payments")[0][0], before)         # a check saves nothing
        self.assertEqual(self.sql_("SELECT COUNT(*) FROM revenue_types WHERE ledger_code='1003'")[0][0], 0)
        self.assertIn("paid the portal's invoice", st[3]["message"])                       # registration: the invoice made at enrolment
        self.assertIn("new revenue type 1003 Advance Payment", st[5]["message"])
        self.assertIn("read as BAL/AT1/021", st[6]["message"])                             # BAL/ATI/021: I for 1
        self.assertEqual(st[7]["status"], "would_create"); self.assertIn("new invoice, paid", st[7]["message"])
        self.assertEqual(st[8]["status"], "rejected"); self.assertIn("Fee Month", st[8]["message"])   # June twice
        self.assertEqual(st[9]["status"], "rejected"); self.assertIn("No student BAL/AT1/005", st[9]["message"])
        self.assertIn("paid the portal's invoice INV-202611", st[10]["message"])
        self.assertEqual(st[12]["status"], "rejected"); self.assertIn("2 batches", st[12]["message"])
        self.assertTrue(all(st[n]["status"] == "skipped" for n in (13, 14, 15)))
        # walk-ins recorded under their name; the second June payment marked as July
        rev = [list(x) for x in self.REV]; rev[5].append(None)
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data)); ws = wb["Revenue Registry"]
        ws["M2"] = "Fee Month"; ws["M8"] = "2026-07"; ws["E12"] = "AT1/L1001"
        out = io.BytesIO(); wb.save(out); data2 = out.getvalue()
        r = self.up("revenue", data2, dry=False, q="&unknown=walkin").get_json()
        self.assertEqual((r["ok"], r["rejected"]), (10, 0), [x for x in r["rows"] if x["status"] == "rejected"])
        inv = self.sql_("SELECT i.period, i.kind, i.status, i.batch_id, i.customer_name, rt.ledger_code, i.amount_due_mvr, i.paid_mvr FROM invoices i "
                        "JOIN revenue_types rt ON rt.id=COALESCE(i.revenue_type_id,(SELECT id FROM revenue_types WHERE code=i.kind)) WHERE i.student_id=? ORDER BY i.id", (self.st["BAL/AT1/002"],))
        self.assertIn(("2026-06", "manual", "paid", self.b1, None, "1002", 350, 350), inv)
        self.assertIn(("2026-07", "manual", "paid", self.b1, None, "1002", 350, 350), inv)
        self.assertEqual([x for x in inv if x[5] == "1003"], [("2026-04", "manual", "paid", self.b1, None, "1003", 150, 150)])   # the advance: a new type, tied to her batch
        self.assertEqual(self.sql_("SELECT COUNT(*) FROM invoices WHERE customer_name='Left Student' AND status='paid'")[0][0], 1)
        p = self.sql_("SELECT reference, note, paid_on, method FROM payments WHERE reference='INV2026/001'")[0]
        self.assertEqual((p[2], p[3]), ("2026-04-02", "bank_transfer")); self.assertIn("Revenue registry", p[1])
        self.assertEqual(self.sql_("SELECT COUNT(*) FROM notifications WHERE kind IN ('slip_verified','invoice_new') AND created_at>datetime('now','-1 minute')")[0][0], 0)   # nobody is messaged
        self.assertTrue(self.sql_("SELECT 1 FROM audit_log WHERE action='import_revenue'"))
        # the same file again: every row skipped, nothing added
        n = self.sql_("SELECT COUNT(*) FROM payments")[0][0]
        r = self.up("revenue", data2, dry=False, q="&unknown=walkin").get_json()
        self.assertEqual((r["ok"], r["rejected"]), (0, 0), r["rows"]); self.assertEqual(self.sql_("SELECT COUNT(*) FROM payments")[0][0], n)
        # an amount above what the open invoice still needs is refused with the reason
        nov = self.sql_("SELECT id FROM invoices WHERE student_id=? AND period='2026-11' AND kind='monthly'", (self.st["BAL/AT1/001"],))[0][0]
        bad = registry_book([[1, dt.datetime(2026, 11, 3), "BAL/AT1/001", "Test Student A", "Arabic - L1001", 1002, "Monthly Fee", "-", "-", "-", 400, "X1"]], [])
        r = self.up("revenue", bad).get_json(); self.assertIn("more than the MVR 350", r["rows"][0]["message"])
        self.assertEqual(self.sql_("SELECT status FROM invoices WHERE id=?", (nov,))[0][0], "unpaid")
        # add_codes=0: an unknown code is refused
        unk = registry_book([[1, dt.datetime(2026, 9, 3), "BAL/AT1/001", "Test Student A", "", 1009, "Books", "-", "-", "-", 80, "X2"]], [])
        self.assertIn("No revenue type has the code 1009", self.up("revenue", unk, q="&add_codes=0").get_json()["rows"][0]["message"])
        # permissions: Fees area
        self.assertEqual(self.up("revenue", data, h=self.F).status_code, 403); self.assertEqual(self.up("revenue", data, h=self.T1).status_code, 403)
        self.assertEqual(self.up("revenue", data, h=self.FE).status_code, 200)

    # ---- 3. expenses ----
    def test_03_expenses(self):
        data = registry_book([], self.EXP)
        r = self.up("expenses", data).get_json()
        self.assertEqual((r["ok"], r["rejected"]), (4, 0), r["rows"])
        self.assertEqual(self.sql_("SELECT COUNT(*) FROM expenses")[0][0], 0)
        r = self.up("expenses", data, dry=False).get_json()
        self.assertEqual(r["ok"], 4)
        rows = {x[0]: x[1:] for x in self.sql_("SELECT supplier, amount_mvr, usd_amount, fx_rate, amount_exact, invoice_no, supplier_gst_no, gst_mvr FROM expenses")}
        self.assertEqual(rows["Google"][:4], (194, 12.59, 15.42, 194.1378))               # USD x 15.42 (the formula has no saved value here), rounded
        self.assertEqual(rows["Meta ads"][0], 93); self.assertIsNone(rows["Meta ads"][4 - 0])   # '-' invoice number is empty
        self.assertEqual(rows["Example Furniture Pvt Ltd"][:1] + rows["Example Furniture Pvt Ltd"][5:], (1944, "GST-TEST-2", 144.0))
        self.assertEqual(rows["Test Staff Pay"][0], 700)
        cats = {x[0]: x[1:] for x in self.sql_("SELECT code, name, kind FROM expense_categories WHERE code IS NOT NULL")}
        self.assertEqual(cats["5004"], ("Cap-EX", "capital")); self.assertEqual(cats["5001"], ("Marketing Expense", "operating"))
        r = self.up("expenses", data, dry=False).get_json(); self.assertEqual((r["ok"], r["rejected"]), (0, 0))   # again: skipped
        # the rate in Settings is used
        self.assertEqual(self.c.put("/api/settings", json={"usd_rate": "abc"}, headers=self.H).status_code, 400)
        self.c.put("/api/settings", json={"usd_rate": "15.5"}, headers=self.H)
        r = self.up("expenses", registry_book([], [[1, dt.datetime(2026, 2, 3), "-", "Meta ads", "FB1", 5001, "Marketing Expense", None, "-", "-", "-", 10, None]])).get_json()
        self.assertIn("USD 10 x 15.5", r["rows"][0]["message"])
        self.c.put("/api/settings", json={"usd_rate": ""}, headers=self.H)
        # the old template still works; permissions
        from openpyxl import Workbook
        wb = Workbook(); ws = wb.active; ws.title = "Data"; ws.append(["expense_date", "amount_mvr", "category", "description"]); ws.append(["2026-10-01", 500, "Cap-EX", "Chairs"])
        out = io.BytesIO(); wb.save(out)
        self.assertEqual(self.up("expenses", out.getvalue()).get_json()["ok"], 1)
        self.assertEqual(self.up("expenses", data, h=self.FE).status_code, 403)
        # the expense list and export carry the new columns
        e = self.c.get("/api/expenses?q=furniture", headers=self.H).get_json()
        self.assertEqual((e["items"][0]["category_kind"], e["items"][0]["invoice_no"], e["usd_rate"]), ("capital", "EX-0001", 15.42))

    # ---- 4. codes on categories and revenue types ----
    def test_04_codes(self):
        built = {x[0]: x[1] for x in self.sql_("SELECT code, ledger_code FROM revenue_types WHERE code IS NOT NULL")}
        self.assertEqual(built, {"monthly": "1002", "registration": "1001"})
        k = self.c.post("/api/expense-categories", json={"name": "Rent", "code": "5006", "kind": "operating"}, headers=self.H)
        self.assertEqual(k.status_code, 201); kid = k.get_json()["id"]
        self.assertEqual(self.c.post("/api/expense-categories", json={"name": "Rent 2", "code": "5006"}, headers=self.H).status_code, 400)
        self.assertEqual(self.c.post("/api/expense-categories", json={"name": "X", "kind": "weird"}, headers=self.H).status_code, 400)
        self.assertEqual(self.c.patch(f"/api/expense-categories/{kid}", json={"kind": "capital", "code": "5007"}, headers=self.H).status_code, 200)
        self.assertEqual(self.sql_("SELECT code, kind FROM expense_categories WHERE id=?", (kid,))[0], ("5007", "capital"))
        r = self.c.post("/api/revenue-types", json={"name": "Books", "ledger_code": "1005"}, headers=self.H); self.assertEqual(r.status_code, 201)
        self.assertEqual(self.c.post("/api/revenue-types", json={"name": "Exam", "ledger_code": "1005"}, headers=self.H).status_code, 409)
        self.assertEqual(self.c.patch(f"/api/revenue-types/{r.get_json()['id']}", json={"ledger_code": ""}, headers=self.H).status_code, 200)
        self.assertIsNone(self.sql_("SELECT ledger_code FROM revenue_types WHERE name='Books'")[0][0])

    # ---- 5. income statement, its Excel and PDF, the registry workbook, and the round trip ----
    def test_05_statement_and_registry(self):
        self.test_02_revenue() if not self.sql_("SELECT 1 FROM payments WHERE reference='INV2026/001'") else None
        self.test_03_expenses() if not self.sql_("SELECT 1 FROM expenses WHERE supplier='Google'") else None
        s = self.c.get("/api/finance/income-statement?year=2026", headers=self.H).get_json()
        rev = {x["code"]: x for x in s["revenue"]}
        self.assertEqual(rev["1001"]["months"]["2026-04"], 1050)                          # three registration fees in April
        self.assertEqual(rev["1003"]["months"]["2026-04"], 150)
        self.assertEqual(rev["1002"]["months"]["2026-11"], 350)
        self.assertEqual(s["months_shown"], 11)
        capex = {x["code"]: x for x in s["capital"]}["5004"]
        self.assertEqual(capex["months"]["2026-03"], 1944)
        self.assertNotIn("5004", [x["code"] for x in s["expenses"]])
        m = "2026-03"; self.assertEqual(s["pl"]["profit"][m], s["totals"]["revenue"][m] - s["totals"]["operating"][m])
        self.assertEqual(s["pl"]["after_capital"][m], s["pl"]["profit"][m] - 1944)
        self.assertGreater(s["totals"]["accrued"]["2026-11"], 0)                           # November fees not paid yet
        self.assertEqual(self.c.get("/api/finance/income-statement?year=26", headers=self.H).status_code, 400)
        wb = self.book(self.c.get("/api/finance/income-statement.xlsx?year=2026", headers=self.H))
        ws = wb["Monthly Report"]
        self.assertEqual([ws.cell(row=4, column=j).value for j in range(2, 5)], ["Code", "Revenue", "Jan"])
        self.assertTrue(str(ws.cell(row=5, column=16).value).startswith("=SUM(D5:O5)"))    # live totals
        self.assertEqual(self.c.get("/api/finance/income-statement.pdf?year=2026", headers=self.H).status_code, 200)
        reg = self.c.get("/api/finance/registry.xlsx?year=2026", headers=self.H)
        wb = self.book(reg)
        self.assertEqual(wb.sheetnames[:3], ["Revenue Registry", "Expense Registry", "Monthly Report"])
        self.assertTrue(any(n.startswith("Payments ") for n in wb.sheetnames))
        self.assertEqual(wb["Revenue Registry"]["C2"].value, "Student ID")
        for p in ("/api/finance/income-statement", "/api/finance/registry.xlsx"):
            self.assertEqual(self.c.get(p, headers=self.FE).status_code, 403); self.assertEqual(self.c.get(p, headers=self.F).status_code, 200)
        # round trip: the registry made by the portal, uploaded again, adds nothing
        n = self.sql_("SELECT (SELECT COUNT(*) FROM payments) + (SELECT COUNT(*) FROM expenses)")[0][0]
        for kind in ("revenue", "expenses"):
            r = self.up(kind, reg.data, dry=False, q="&unknown=walkin").get_json()
            self.assertEqual(r["ok"], 0, [x for x in r["rows"] if x["status"] != "skipped"])
        self.assertEqual(self.sql_("SELECT (SELECT COUNT(*) FROM payments) + (SELECT COUNT(*) FROM expenses)")[0][0], n)

    # ---- 6. fee grid: months late, comments, counts, Excel ----
    def test_06_grid(self):
        sid = self.st["BAL/AT1/021"]
        self.sql_("UPDATE invoices SET due_date='2026-10-10' WHERE student_id=? AND period='2026-11' AND kind='monthly'", (sid,))
        self.sql_("INSERT INTO invoices(enrollment_id,student_id,course_id,batch_id,period,description,kind,amount_mvr,discount_mvr,amount_due_mvr,due_date,status,created_at) "
                  "SELECT enrollment_id,student_id,course_id,batch_id,'2026-10',description,'monthly',350,0,350,'2026-10-10','unpaid',created_at FROM invoices WHERE student_id=? AND period='2026-11' AND kind='monthly'", (sid,))
        g = self.c.get(f"/api/fees/status-grid?end=2026-11&months=3&batch_id={self.b1}", headers=self.H).get_json()
        b = g["batches"][0]; p = [x for x in b["students"] if x["student_id"] == sid][0]
        self.assertEqual((p["months_late"], p["owed_late"], p["late_since"]), (2, 700, "2026-10"))
        self.assertEqual(set(b["counts"]["2026-11"]), {"paid", "not_paid"}); self.assertGreaterEqual(b["counts"]["2026-11"]["not_paid"], 1)
        self.assertEqual(set(b["months"]["2026-11"]), {"due", "collected", "outstanding"})   # unchanged shape
        put = lambda j, h=None: self.c.put("/api/fees/notes", json=j, headers=h or self.H)
        self.assertEqual(put({"student_id": sid, "batch_id": self.b1, "note": "  Need reminder   3rd month "}).get_json()["note"], "Need reminder 3rd month")
        self.assertEqual(put({"student_id": sid, "batch_id": self.b2, "note": "x"}).status_code, 404)   # not in that batch
        self.assertEqual(put({"student_id": sid, "batch_id": self.b1, "note": "x" * 201}).status_code, 400)
        self.assertEqual(put({"student_id": sid, "batch_id": self.b1, "note": "x"}, self.F).status_code, 403)
        g = self.c.get(f"/api/fees/status-grid?end=2026-11&months=3&batch_id={self.b1}", headers=self.H).get_json()
        p = [x for x in g["batches"][0]["students"] if x["student_id"] == sid][0]
        self.assertEqual(p["note"], "Need reminder 3rd month"); self.assertTrue(p["note_by"]); self.assertTrue(p["note_at"])
        self.assertTrue(self.sql_("SELECT 1 FROM audit_log WHERE action='fee_note' AND entity_id=?", (sid,)))
        wb = self.book(self.c.get(f"/api/fees/status-grid.xlsx?end=2026-11&months=3&batch_id={self.b1}", headers=self.H))
        ws = wb[wb.sheetnames[0]]
        head = [c.value for c in ws[2]]
        self.assertEqual(head[:2] + head[-2:], ["Student ID", "Name", "Months late", "Comments"])
        rowv = [[c.value for c in r] for r in ws.iter_rows(min_row=3) if r[0].value == "BAL/AT1/021"][0]
        self.assertEqual((rowv[-2], rowv[-1], rowv[3]), (2, "Need reminder 3rd month", "Not paid"))
        self.assertIn("Total Not Paid", [r[1].value for r in ws.iter_rows(min_row=3)])
        self.assertEqual(put({"student_id": sid, "batch_id": self.b1, "note": ""}).get_json()["note"], None)
        self.assertEqual(self.sql_("SELECT COUNT(*) FROM fee_notes")[0][0], 0)
        self.assertEqual(self.c.get("/api/fees/status-grid.xlsx", headers=self.F).status_code, 403)

    # ---- 6b. formula text in names stays text; a walk-in with a student's name stays a walk-in ----
    def test_06b_safety(self):
        kid = self.c.post("/api/expense-categories", json={"name": "=HYPERLINK(\"x\")", "code": "5090"}, headers=self.H).get_json()["id"]
        self.c.post("/api/expenses", json={"expense_date": "2026-02-02", "amount_mvr": 10, "category_id": kid}, headers=self.H)
        ws = self.book(self.c.get("/api/finance/income-statement.xlsx?year=2026", headers=self.H))["Monthly Report"]
        names = [ws.cell(row=r, column=3).value for r in range(1, ws.max_row + 1)]
        self.assertIn("'=HYPERLINK(\"x\")", names)
        self.c.post("/api/invoices/manual", json={"customer_name": "Test Student A", "revenue_type_id": self.sql_("SELECT id FROM revenue_types WHERE code='registration'")[0][0],
                                                   "amount_mvr": 99, "invoice_date": "2026-02-01", "paid": "1", "paid_on": "2026-02-01", "method": "cash"}, headers=self.H)
        data = registry_book([[1, dt.datetime(2026, 2, 1), "", "Test Student A", "", 1001, "Registration Fee", "-", "-", "-", 99, "W1"]], [])
        r = self.up("revenue", data, q="&unknown=walkin").get_json()
        self.assertEqual(r["rows"][0]["status"], "skipped", r["rows"][0])                 # the walk-in's own payment, not the student's

    # ---- 7. an older database gets the new columns; nothing else changes ----
    def test_07_upgrade(self):
        import dbx
        con = sqlite3.connect(self.path)
        for t, col in (("expenses", "supplier"), ("expense_categories", "kind"), ("revenue_types", "ledger_code")):
            con.execute(f"ALTER TABLE {t} DROP COLUMN {col}")
        con.execute("UPDATE schema_meta SET version='old'"); con.commit(); con.close()
        n = self.sql_("SELECT COUNT(*) FROM expenses")[0][0]
        conn = dbx.Conn(path=self.path)
        dbx.init_schema(conn, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        cols = lambda t: [r[1] for r in self.sql_(f"PRAGMA table_info({t})")]
        self.assertIn("supplier", cols("expenses")); self.assertIn("kind", cols("expense_categories")); self.assertIn("ledger_code", cols("revenue_types"))
        self.assertEqual(self.sql_("SELECT COUNT(*) FROM expenses")[0][0], n)
        self.assertEqual({x[0]: x[1] for x in self.sql_("SELECT code, ledger_code FROM revenue_types WHERE code IS NOT NULL")}, {"monthly": "1002", "registration": "1001"})
        self.assertEqual(self.sql_("SELECT COUNT(*) FROM expense_categories WHERE kind IS NULL OR kind NOT IN ('operating','capital')")[0][0], 0)
        self.assertEqual(self.sql_("PRAGMA integrity_check")[0][0], "ok")


if __name__ == "__main__":
    unittest.main()
