"""Optional browser test (390px phone, real app), v0.8.43: add a student who started earlier (start date) and see the earlier months billed;
Fees > Invoices > Mark paid on one invoice with a WhatsApp screenshot; tick several months and mark them paid with one slip;
Record payment shows Open slip; Generate with a From month. Run: python tests/e2e_mark_paid.py (needs playwright + chromium)"""
import os, sys, time, subprocess, tempfile, json, sqlite3, urllib.request, datetime as dt
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import e2e_shim  # noqa: F401
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(); DB = os.path.join(tmp, "m.db")
env = dict(os.environ, DATABASE_PATH=DB, ADMIN_EMAIL="admin@m.test", ADMIN_PASSWORD="AdminPass123", PORT="5093", SECRET_KEY="m" * 32)
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
def sql(q, a=()):
    c = sqlite3.connect(DB)
    try: r = c.execute(q, a).fetchall(); c.commit(); return r
    finally: c.close()
sql("UPDATE users SET must_change_password=0")
srv = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(2)
BASE = "http://127.0.0.1:5093"; errors = []
def check(c, m):
    print("PASS" if c else "FAIL", m)
    if not c: errors.append(m)
def api(path, body=None, tok=None, method=None):
    r = urllib.request.Request(BASE + "/api" + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    return json.load(urllib.request.urlopen(r))
png = os.path.join(tmp, "IMG-WA0001.png"); open(png, "wb").write(b"\x89PNG\r\n\x1a\n" + b"x" * 300)
mv = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5)
start = f"{mv.year if mv.month > 3 else mv.year - 1}-{(mv.month - 3 - 1) % 12 + 1:02d}-03"   # three months back
try:
    adm = api("/auth/login", {"email": "admin@m.test", "password": "AdminPass123"})["token"]
    api("/courses/1", {"monthly_fee_mvr": 400}, adm, "PATCH")
    sid = api("/users", {"email": "late@m.test", "password": "Password123", "full_name": "Late Joiner", "role": "student"}, adm)["id"]
    with sync_playwright() as p:
        br = p.chromium.launch()
        ctx = br.new_context(viewport={"width": 390, "height": 800}); a = ctx.new_page()
        a.on("pageerror", lambda e: errors.append(str(e)))
        e2e_shim.login(a, BASE, "admin@m.test", "AdminPass123", db=DB)
        # ---- enrol with a start date ----
        a.click("nav [data-v=enrollments]"); a.click("[data-add=enrollment] summary"); a.wait_for_selector("#esd")
        a.select_option("#es", str(sid)); a.select_option("#eb", index=1); a.fill("#esd", start)
        a.click("#fe button:not([type=button])"); a.wait_for_selector("text=invoices made for the earlier months")
        n = sql("SELECT COUNT(*) FROM invoices WHERE student_id=? AND kind='monthly'", (sid,))[0][0]
        check(n == 4, f"start date three months back: 4 monthly invoices made ({n})")
        # ---- mark one paid with a slip ----
        a.click("nav [data-v=fees]"); a.click("[data-tabs=fees] [data-key=invoices]"); a.wait_for_selector("[data-do=fxGen]")
        a.fill("#fxf_q", "Late Joiner"); a.click("#fxff button"); a.wait_for_selector("[data-do=fxPaid]")
        rows = a.locator(".cl:has-text('Late Joiner')"); check(rows.count() == 4, "four invoices listed for the student")
        rows.first.locator("[data-do=fxPaid]").click(); a.wait_for_selector("dialog.dlg input[type=file]")
        check(a.locator("dialog.dlg input[type=number]").input_value() == "400", "amount is filled with the balance")
        a.locator("dialog.dlg input[type=date]").fill(start)
        a.set_input_files("dialog.dlg input[type=file]", png)
        a.screenshot(path=os.path.join(tempfile.gettempdir(), "baleegh-e2e-mark-paid-dialog.png"))
        a.click("dialog.dlg button[value=ok]"); a.wait_for_selector("text=1 paid, MVR 400 recorded.")
        check(sql("SELECT COUNT(*) FROM payment_slips WHERE student_id=? AND status='verified'", (sid,))[0][0] == 1, "slip stored as verified with the payment")
        # ---- tick the rest, mark them paid with one slip ----
        a.wait_for_selector("[data-do=fxPaid]")
        a.locator(".cl:has-text('Late Joiner') input.bulk").first.wait_for()
        for i in range(a.locator(".cl:has-text('Late Joiner') input.bulk").count()): a.locator(".cl:has-text('Late Joiner') input.bulk").nth(i).check()
        a.click("[data-do=fxBulkPaid]"); a.wait_for_selector("dialog.dlg input[type=file]")
        check(a.locator("dialog.dlg input[type=number]").count() == 0 and "MVR 1,200" in a.inner_text("dialog.dlg"), "bulk dialog: no amount, shows the total of the three")
        a.set_input_files("dialog.dlg input[type=file]", png)
        a.click("dialog.dlg button[value=ok]"); a.wait_for_selector("text=3 paid, MVR 1,200 recorded.")
        st = [r[0] for r in sql("SELECT status FROM invoices WHERE student_id=? AND kind='monthly'", (sid,))]
        check(st == ["paid"] * 4, f"all four months paid ({st})")
        check(len(a.locator("[data-do=fxPaid]").all()) == 0 or "Late Joiner" not in " ".join(a.locator(".cl:has([data-do=fxPaid])").all_inner_texts()), "no Mark paid left for the student")
        # ---- payments list shows the slip ----
        a.click("[data-tabs=fees] [data-key=record]"); a.wait_for_selector("#fxp_f")
        check(a.locator(".cl:has-text('Late Joiner') [data-do=fxView]").count() == 4, "every payment has Open slip")
        check(e2e_shim.preview_bytes(a, ".cl:has-text('Late Joiner') [data-do=fxView]").startswith(b"\x89PNG"), "the slip opens")
        # ---- Generate with From ----
        a.click("[data-tabs=fees] [data-key=invoices]"); a.wait_for_selector("#fxg_f")
        a.fill("#fxg_f", start[:7]); a.click("[data-do=fxGen]"); a.wait_for_selector("text=Created:")
        check(not a.locator("dialog[open]").count(), "generate with a From month runs")
        sw = a.evaluate("document.documentElement.scrollWidth"); check(sw <= 392, f"no sideways scrolling on a phone ({sw})")
        a.screenshot(path=os.path.join(tempfile.gettempdir(), "baleegh-e2e-mark-paid.png"), full_page=True)
        br.close()
finally:
    srv.terminate()
print("ERRORS:", errors) if errors else print("ALL OK")
sys.exit(1 if errors else 0)
