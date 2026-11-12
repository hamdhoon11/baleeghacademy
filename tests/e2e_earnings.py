"""Optional browser test (390px phone, real app), v0.8.40: Finance → Teacher earnings, with the server handing over every database row
in the PostgreSQL shape (as on the hosted portal): empty month hint, Calculate, Approve month, Owed to teachers, Record payment, and a month
the server refuses no longer breaking the Finance tab. Run: python tests/e2e_earnings.py (needs playwright + chromium)"""
import os, sys, time, subprocess, tempfile, shutil, json, sqlite3, urllib.request, datetime as dt
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import e2e_shim  # noqa: F401
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(); DB = os.path.join(tmp, "e40.db")
env = dict(os.environ, DATABASE_PATH=DB, ADMIN_EMAIL="admin@e40.test", ADMIN_PASSWORD="AdminPass123", PORT="5096", SECRET_KEY="e40-" + "k" * 40, SEED_DEMO="1")
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
def sql(q, a=()):
    c = sqlite3.connect(DB)
    try: r = c.execute(q, a).fetchall(); c.commit(); return r
    finally: c.close()
sql("UPDATE users SET must_change_password=0")
# the server, with rows shaped as PostgreSQL gives them (a dict that can also be read by position)
PG_SERVER = ("import os, dbx\n"
             "dbx.Cur._wrap = lambda self, r: None if r is None else dbx.Row(r.keys(), [dbx._py(v) for v in tuple(r)])\n"
             "import app\n"
             "app.app.run(host='127.0.0.1', port=int(os.environ['PORT']), debug=False)\n")
srv = subprocess.Popen([sys.executable, "-c", PG_SERVER], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(2.5)
BASE = "http://127.0.0.1:5096"; errors = []
def check(c, m):
    print("PASS" if c else "FAIL", m)
    if not c: errors.append(m)
def api(path, body=None, tok=None, method=None):
    r = urllib.request.Request(BASE + "/api" + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    return json.load(urllib.request.urlopen(r))
now = dt.datetime.now(dt.timezone(dt.timedelta(hours=5)))
first = now.date().replace(day=1); last_day = first - dt.timedelta(days=1)
LAST, NEXT = last_day.strftime("%Y-%m"), (first + dt.timedelta(days=40)).strftime("%Y-%m")
try:
    adm = api("/auth/login", {"email": "admin@e40.test", "password": "AdminPass123"})["token"]
    api("/courses/1", {"monthly_fee_mvr": 400}, adm, "PATCH")
    sql("UPDATE enrollments SET enrolled_at=?", (last_day.replace(day=1).isoformat() + " 00:00:00",))   # the demo student was already enrolled last month
    api("/invoices/generate", {"month": LAST}, adm)
    inv = [i for i in api("/invoices?limit=50", tok=adm) if i["period"] == LAST]
    api("/payments", {"invoice_id": inv[0]["id"], "amount_mvr": 300, "method": "cash", "paid_on": last_day.isoformat()}, adm)
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_context(viewport={"width": 390, "height": 800}).new_page()
        pg.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
        e2e_shim.login(pg, BASE, "admin@e40.test", "AdminPass123", db=DB)
        pg.click("nav [data-v=finance]"); pg.wait_for_selector("#fe_month")
        panel = lambda: pg.inner_text(".panel:has(#fe_month)")
        check(pg.input_value("#fe_month") == LAST, "the month starts at last month")
        check("Nothing is calculated for this month yet" in panel(), "an empty month says so and points to Calculate")
        check(pg.is_disabled("[data-do=feApprove]"), "Approve is off until there is something to approve")
        pg.click("[data-do=feCalc]"); pg.wait_for_selector(".panel:has(#fe_month) td:has-text('Demo Teacher')")
        check("150" in panel() and "draft" in panel().lower(), "Calculate shows the batch: 300 collected, 150 for the teacher, draft")
        check(not pg.is_visible("[role=alert]"), "no error after Calculate")
        pg.click("[data-do=feApprove]"); e2e_shim.dialog(pg)
        pg.wait_for_selector(".panel:has(#fe_month) td:has-text('approved'), .panel:has(#fe_month) td:has-text('Approved')")
        check(pg.is_disabled("[data-do=feCalc]") and pg.is_disabled("[data-do=feApprove]"), "an approved month is locked")
        check(pg.is_visible("[data-do=fePay]"), "the teacher appears under Owed to teachers with Record payment")
        pg.click("[data-do=fePay]"); pg.wait_for_selector("dialog.dlg[open]")
        check(pg.input_value("dialog.dlg[open] input[type=number]") == "150", "Record payment starts at the outstanding 150")
        pg.click("dialog.dlg[open] button[value=ok]"); pg.wait_for_selector("[data-do=feVoid]")
        check(sql("SELECT amount_mvr FROM teacher_payments WHERE voided_at IS NULL") == [(150,)], "the payment to the teacher is saved")
        # a month that has not started: before, the whole Finance tab turned into an error and stayed so
        pg.evaluate("m => { document.querySelector('#fe_month').value = m; }", NEXT); pg.click("[data-do=feShow]")
        pg.wait_for_selector(".panel:has(#fe_month) [role=alert]")
        check("not started" in panel(), "a month that has not started gives a message inside the panel")
        check(pg.is_visible("[data-do=fnCatAdd], [data-do=fnAdd], #fn_f, .panel:has-text('Expenses')"), "the rest of Finance is still there")
        pg.evaluate("m => { document.querySelector('#fe_month').value = m; }", LAST); pg.click("[data-do=feShow]")
        pg.wait_for_selector(".panel:has(#fe_month) td:has-text('Demo Teacher')")
        check(not pg.is_visible(".panel:has(#fe_month) [role=alert]"), "Show works again for a real month")
        check(pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "no sideways scrolling on a phone")
        br.close()
finally:
    srv.terminate(); shutil.rmtree(tmp, ignore_errors=True)
print("\nProblems:", errors or "none"); sys.exit(1 if errors else 0)
