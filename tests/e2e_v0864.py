"""Optional browser test, v0.8.64: Finance (income statement, category codes, USD expense, the expense registry import) and Fees (revenue
type codes, the revenue registry import, the fee grid's months-late tag, comment and Excel). At 390 px and 1280 px.
Run: python tests/e2e_v0864.py"""
import os, sys, time, subprocess, tempfile, json, sqlite3, urllib.request, datetime as dt
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import e2e_shim  # noqa: F401
from test_v0864 import registry_book
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(); DB = os.path.join(tmp, "v.db")
env = dict(os.environ, DATABASE_PATH=DB, ADMIN_EMAIL="admin@v.test", ADMIN_PASSWORD="AdminPass123", PORT="5098", SECRET_KEY="v" * 32, SEED_DEMO="0")
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
def sql(q, a=()):
    c = sqlite3.connect(DB)
    try: r = c.execute(q, a).fetchall(); c.commit(); return r
    finally: c.close()
sql("UPDATE users SET must_change_password=0")
srv = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(2)
BASE = "http://127.0.0.1:5098"; errors = []
OUT = os.environ.get("E2E_SHOTS") or tempfile.gettempdir()
def check(ok, m):
    print("PASS" if ok else "FAIL", m)
    if not ok: errors.append(m)
def api(path, body=None, tok=None, method=None):
    r = urllib.request.Request(BASE + "/api" + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                               headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    return json.load(urllib.request.urlopen(r))
try:
    adm = api("/auth/login", {"login": "admin@v.test", "password": "AdminPass123"})["token"]
    co = api("/courses", {"name": "Arabic E2E", "code": "AE1", "monthly_fee_mvr": 350, "registration_fee_mvr": 350, "status": "open"}, adm)["id"]
    b1 = api("/batches", {"course_id": co, "code": "L1001", "capacity": 30}, adm)["id"]
    sids = {}
    for code, name in (("BAL/AE1/001", "Test Student A"), ("BAL/AE1/002", "Test Student B")):
        sid = api("/users", {"email": code.replace("/", "").lower() + "@v.test", "password": "Password123", "full_name": name, "role": "student", "phone": "7771234"}, adm)["id"]
        sql("UPDATE students SET student_code=? WHERE user_id=?", (code, sid)); api("/enrollments", {"student_id": sid, "batch_id": b1}, adm); sids[code] = sid
    sql("UPDATE invoices SET due_date='2026-10-10' WHERE student_id=? AND kind='monthly'", (sids["BAL/AE1/002"],))   # student B is late
    REV = [[1, dt.datetime(2026, 4, 2), "BAL/AE1/001", "Test Student A", "Arabic - L1001", 1001, "Registration Fee", "-", "-", "-", 350, "INV2026/001"],
           [2, dt.datetime(2026, 4, 18), "BAL/AEI/002", "Test Student B", "Arabic - L1001", 1003, "Advance Payment", "-", "-", "-", 150, "INV2026/002"],
           [3, dt.datetime(2026, 5, 3), "BAL/AE1/001", "Test Student A", "Arabic - L1001", 1002, "Monthly Fee", "-", "-", "-", 350, "INV2026/003"]]
    EXP = [[1, dt.datetime(2026, 1, 1), "GST-TEST-1", "Google", 9000000001, 5002, "Maintenance Expense", None, None, "-", "-", 12.59, None],
           [2, dt.datetime(2026, 3, 12), "GST-TEST-2", "Example Furniture Pvt Ltd", "EX-0001", 5004, "Cap-EX", 1944, 144, "-", "-", None, None]]
    XL = os.path.join(tmp, "Registry_Income_Statement.xlsx"); open(XL, "wb").write(registry_book(REV, EXP))
    with sync_playwright() as p:
        br = p.chromium.launch()
        for w in (390, 1280):
            pg = br.new_context(viewport={"width": w, "height": 900}, accept_downloads=True).new_page(); pg.on("pageerror", lambda e: errors.append(str(e)))
            e2e_shim.login(pg, BASE, "admin@v.test", "AdminPass123", db=DB)
            # ---- Fees > New invoice: codes and the revenue registry import ----
            pg.goto(BASE + "/#fees"); pg.wait_for_selector("[data-tabs=fees]"); pg.click("[data-tabs=fees] [data-key=manual]"); pg.wait_for_selector("#fxm")
            check(pg.locator(".chip", has_text="1002").count() >= 1, f"Revenue types show their registry codes ({w})")
            if w == 390:
                pg.click("[data-imp=revenue] summary"); pg.set_input_files("#impf_revenue", XL); pg.click("[data-imp=revenue] [data-do=impChk]")
                pg.wait_for_selector("[data-imp=revenue] >> text=Check result"); res = pg.locator("[data-imp=revenue]").inner_text()
                check("3 would be created" in res, f"Revenue check: 3 rows would be created ({w})")
                pg.click("[data-imp=revenue] summary:has-text('What each row did')")
                check("read as BAL/AE1/002" in pg.locator("[data-imp=revenue]").inner_text(), f"Check says what each row does ({w})")
                pg.screenshot(path=os.path.join(OUT, f"v0864-revimp-{w}.png"), full_page=True)
                pg.click("[data-imp=revenue] [data-do=impRun]"); e2e_shim.dialog(pg); pg.wait_for_selector("[data-imp=revenue] >> text=Imported")
                check(sql("SELECT COUNT(*) FROM payments WHERE note LIKE 'Revenue registry%'")[0][0] == 3, f"Revenue registry imported ({w})")
            # ---- Fees > Record payment: grid with months late, comment, Excel ----
            pg.click("[data-tabs=fees] [data-key=record]"); pg.wait_for_selector(".fg")
            check(pg.locator(".fg .tag", has_text="month late").count() >= 1, f"Grid shows how many months a student is late ({w})")
            pg.locator(".fg [data-do=fxNote]").first.click(); d = pg.locator("dialog[open]"); d.wait_for()
            d.locator("input, textarea").first.fill(f"Need reminder 2nd month {w}"); d.locator("button.btn:not(.alt)").last.click()
            pg.wait_for_selector(f".fg [data-do=fxNote]:has-text('Need reminder 2nd month {w}')")
            check(sql("SELECT COUNT(*) FROM fee_notes WHERE note=?", (f"Need reminder 2nd month {w}",))[0][0] == 1, f"Comment saved ({w})")
            with pg.expect_download() as dl: pg.click("[data-do=fxGridXlsx]")
            check(dl.value.suggested_filename.endswith(".xlsx"), f"Grid downloads as Excel ({w})")
            pg.screenshot(path=os.path.join(OUT, f"v0864-grid-{w}.png"), full_page=True)
            # ---- Finance: income statement, expense import, USD expense, category codes ----
            pg.goto(BASE + "/#finance"); pg.wait_for_selector("table.is")
            if w == 390:
                pg.click("[data-imp=expenses] summary"); pg.set_input_files("#impf_expenses", XL); pg.click("[data-imp=expenses] [data-do=impRun]"); e2e_shim.dialog(pg)
                pg.wait_for_selector("[data-imp=expenses] >> text=Imported")
                check(sql("SELECT COUNT(*) FROM expenses WHERE supplier IN ('Google','Example Furniture Pvt Ltd')")[0][0] == 2, f"Expense registry imported ({w})")
                pg.wait_for_selector("table.is")
            tbl = pg.locator("table.is").inner_text()
            check("Registration fees" in tbl and "Advance Payment" in tbl and "Capital spending" in tbl.title() or "CAPITAL" in tbl.upper(), f"Income statement lists revenue codes and capital apart ({w})")
            check("Collected profit" in tbl, f"Income statement has the profit line ({w})")
            with pg.expect_download() as dl: pg.click("[data-do=fisGet][data-x=xlsx]")
            check(dl.value.suggested_filename == "income-statement-2026.xlsx" or dl.value.suggested_filename.startswith("income-statement"), f"Income statement Excel ({w})")
            with pg.expect_download() as dl: pg.click("[data-do=fisReg]")
            check(dl.value.suggested_filename.startswith("registry"), f"Registry workbook download ({w})")
            pg.screenshot(path=os.path.join(OUT, f"v0864-finance-{w}.png"), full_page=True)
            pg.fill("#fx_usd", "10"); pg.wait_for_timeout(200)
            check(pg.input_value("#fx_amt") == "154", f"Dollars fill the MVR amount at 15.42 ({w})")
            pg.fill("#fx_sup", f"Meta ads {w}"); pg.fill("#fx_inv", f"FB{w}"); pg.click("#fex button.btn.alt"); pg.wait_for_timeout(900)
            r = sql("SELECT amount_mvr, usd_amount, fx_rate, invoice_no FROM expenses WHERE supplier=?", (f"Meta ads {w}",))
            check(r == [(154, 10.0, 15.42, f"FB{w}")], f"USD expense saved with supplier and invoice ({w}): {r}")
            pg.locator("[data-do=fnCatEdit]").first.click(); d = pg.locator("dialog[open]"); d.wait_for()
            check(d.locator("select").count() == 1, f"Category edit has the kind choice ({w})")
            pg.keyboard.press("Escape")
        br.close()
finally:
    srv.terminate()
print("FAILURES:", errors) if errors else print("ALL PASS")
