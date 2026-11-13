"""Optional browser test (390px phone, real app), v0.8.45: add a revenue type; Fees > New invoice for someone not in the portal, already paid
with a WhatsApp slip; for a student tied to their batch, unpaid; Edit an invoice's amount (reason asked); Finance > Revenue by type.
Run: python tests/e2e_manual_invoice.py (needs playwright + chromium)"""
import os, sys, time, subprocess, tempfile, json, sqlite3, urllib.request
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import e2e_shim  # noqa: F401
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(); DB = os.path.join(tmp, "m.db")
env = dict(os.environ, DATABASE_PATH=DB, ADMIN_EMAIL="admin@m.test", ADMIN_PASSWORD="AdminPass123", PORT="5094", SECRET_KEY="m" * 32)
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
def sql(q, a=()):
    c = sqlite3.connect(DB)
    try: r = c.execute(q, a).fetchall(); c.commit(); return r
    finally: c.close()
sql("UPDATE users SET must_change_password=0")
srv = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(2)
BASE = "http://127.0.0.1:5094"; errors = []
def check(c, m):
    print("PASS" if c else "FAIL", m)
    if not c: errors.append(m)
def api(path, body=None, tok=None, method=None):
    r = urllib.request.Request(BASE + "/api" + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    return json.load(urllib.request.urlopen(r))
png = os.path.join(tmp, "IMG-WA0002.png"); open(png, "wb").write(b"\x89PNG\r\n\x1a\n" + b"x" * 300)
SHOT = lambda a, n: a.screenshot(path=os.path.join(tempfile.gettempdir(), f"baleegh-e2e-manual-{n}.png"), full_page=True)
try:
    adm = api("/auth/login", {"email": "admin@m.test", "password": "AdminPass123"})["token"]
    sid = api("/users", {"email": "old@m.test", "password": "Password123", "full_name": "Old Student", "role": "student"}, adm)["id"]
    api("/enrollments", {"student_id": sid, "batch_id": 1}, adm)
    with sync_playwright() as p:
        br = p.chromium.launch()
        ctx = br.new_context(viewport={"width": 390, "height": 800}); a = ctx.new_page()
        a.on("pageerror", lambda e: errors.append(str(e)))
        e2e_shim.login(a, BASE, "admin@m.test", "AdminPass123", db=DB)
        a.click("nav [data-v=fees]"); a.click("[data-tabs=fees] [data-key=manual]"); a.wait_for_selector("#fxm")
        # ---- add a revenue type ----
        a.fill("#fxrt_n", "Books"); a.click("#fxrt button"); a.wait_for_selector(".cl:has-text('Books')")
        check(a.locator("#fxm_t option", has_text="Books").count() == 1, "new revenue type offered in the form")
        # ---- someone not in the portal, already paid, with a slip ----
        a.select_option("#fxm_w", "customer"); check(a.is_visible("#fxm_cn") and not a.is_visible("#fxm_s"), "customer fields shown, student hidden")
        a.fill("#fxm_cn", "Walk-in Ahmed"); a.fill("#fxm_cp", "7771234"); a.select_option("#fxm_t", label="Books")
        a.fill("#fxm_d", "Arabic workbook"); a.fill("#fxm_a", "150"); a.fill("#fxm_id", "2026-04-20")
        a.check("#fxm_p"); check(a.is_visible("#fxm_pm"), "payment fields shown after ticking Already paid")
        a.select_option("#fxm_pm", "cash"); a.fill("#fxm_pd", "2026-04-20"); a.set_input_files("#fxm_f", png)
        SHOT(a, "form")
        a.click("#fxm button.alt:has-text('Create invoice')"); a.wait_for_selector("text=made for Walk-in Ahmed")
        r = sql("SELECT i.status, i.period, i.customer_name, p.student_id, s.status FROM invoices i JOIN payments p ON p.invoice_id=i.id JOIN payment_slips s ON s.id=p.slip_id WHERE i.customer_name='Walk-in Ahmed'")
        check(r == [("paid", "2026-04", "Walk-in Ahmed", None, "verified")], f"walk-in invoice paid, April, slip verified ({r})")
        # ---- a student, tied to the batch, not paid ----
        a.wait_for_selector("#fxm_s"); a.select_option("#fxm_w", "student"); a.select_option("#fxm_s", str(sid))
        check(a.locator("#fxm_b option").count() == 2, "the student's batch is offered")
        a.select_option("#fxm_b", index=1); a.select_option("#fxm_t", label="Registration fees"); a.fill("#fxm_a", "100"); a.fill("#fxm_id", "2026-04-01")
        a.click("#fxm button.alt:has-text('Create invoice')"); a.wait_for_selector("text=made for Old Student")
        r = sql("SELECT status, batch_id IS NOT NULL, description FROM invoices WHERE student_id=? AND kind='manual'", (sid,))
        check(r == [("unpaid", 1, "Registration fees")], f"student invoice unpaid, tied to the batch ({r})")
        # ---- the invoice list shows it; edit the amount ----
        a.click("[data-tabs=fees] [data-key=invoices]"); a.wait_for_selector("#fxf_t")
        a.select_option("#fxf_s", "all"); a.select_option("#fxf_t", label="Books"); a.click("#fxff button"); a.wait_for_selector(".cl:has-text('Walk-in Ahmed')")
        check(a.locator(".cl:has-text('Walk-in Ahmed') .tag", has_text="Not in portal").count() == 1, "walk-in tagged Not in portal")
        check(a.locator(".cl:has-text('Old Student')").count() == 0, "type filter leaves out other types")
        a.select_option("#fxf_t", ""); a.fill("#fxf_q", "Old Student"); a.click("#fxff button"); a.wait_for_selector(".cl:has-text('Registration fees')")
        a.locator(".cl:has-text('Registration fees') [data-do=fxEdit]").click(); a.wait_for_selector("dialog.dlg input[type=number]")
        a.locator("dialog.dlg input[type=number]").fill("120"); a.click("dialog.dlg button[value=ok]")
        a.wait_for_selector("dialog.dlg :text('Give a reason for changing the amount')"); check(True, "reason asked when the amount changes")
        a.locator("dialog.dlg input").nth(1).fill("April price"); SHOT(a, "edit"); a.click("dialog.dlg button[value=ok]"); a.wait_for_selector("text=Saved")
        check(sql("SELECT amount_due_mvr FROM invoices WHERE student_id=? AND kind='manual'", (sid,)) == [(120,)], "amount changed to 120")
        # ---- v0.8.46: the Fees reports show them ----
        a.click("[data-tabs=fees] [data-key=report]"); a.wait_for_selector("#fxr_m"); a.fill("#fxr_m", "2026-04"); a.click("#fxr button:not([type=button])")
        a.wait_for_selector("h2:has-text('By revenue type')"); txt = a.inner_text("body")
        check("Books" in txt and "Registration fees" in txt, "Fees > Report: by revenue type for April")
        a.click("[data-tabs=fees] [data-key=payrep]"); a.wait_for_selector("#fxp_m"); a.fill("#fxp_m", "2026-04"); a.click("#fxpr button:not([type=button])")
        a.wait_for_selector("h2:has-text('Other invoices this month')"); a.wait_for_selector("td:has-text('Walk-in Ahmed')")
        check(a.locator("td:has-text('Old Student')").count() >= 1, "Payment report: other invoices list the walk-in and the student")
        SHOT(a, "payrep")
        # ---- Finance: revenue by type ----
        a.click("nav [data-v=finance]"); a.wait_for_selector("text=Total collected")
        txt = a.inner_text("main") if a.locator("main").count() else a.inner_text("body")
        check("Books" in txt and "Revenue type" in txt, "Finance shows revenue by type")
        sw = a.evaluate("document.documentElement.scrollWidth"); check(sw <= 392, f"no sideways scrolling on a phone ({sw})")
        SHOT(a, "finance")
        br.close()
finally:
    srv.terminate()
print("ERRORS:", errors) if errors else print("ALL OK")
sys.exit(1 if errors else 0)
