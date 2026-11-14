"""Optional browser test, v0.8.48 (phone 390 px and computer 1280 px): logo in Settings (menu, sign-in page); Fees -> Reminders with the
total and the months and the WhatsApp button; the student's Home banner; the monthly report batch by batch with charts and the PDF button;
another full admin sees Who's online without buttons and cannot clear data. Run: python tests/e2e_v0848.py (needs playwright + chromium)"""
import os, sys, time, subprocess, tempfile, json, sqlite3, urllib.request, io
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import e2e_shim  # noqa: F401
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
def check(c, m):
    print("PASS" if c else "FAIL", m)
    if not c: errors.append(m)
def api(path, body=None, tok=None, method=None):
    r = urllib.request.Request(BASE + "/api" + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    return json.load(urllib.request.urlopen(r))
OUT = os.environ.get("E2E_SHOTS") or tempfile.gettempdir()
SHOT = lambda a, n: a.screenshot(path=os.path.join(OUT, f"v0848-{n}.png"), full_page=True)
LOGO = os.path.join(tmp, "logo.png")
try:
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (240, 120), "#0b4f5c"); d = ImageDraw.Draw(im); d.ellipse((20, 20, 100, 100), fill="#d9a21b"); d.rectangle((120, 45, 220, 75), fill="#ffffff"); im.save(LOGO)
except ImportError:
    from reportlab.graphics.shapes import Drawing, Rect, Circle; from reportlab.graphics import renderPM; from reportlab.lib import colors
    dr = Drawing(240, 120); dr.add(Rect(0, 0, 240, 120, fillColor=colors.HexColor("#0b4f5c"))); dr.add(Circle(60, 60, 40, fillColor=colors.HexColor("#d9a21b"))); renderPM.drawToFile(dr, LOGO, fmt="PNG")
try:
    adm = api("/auth/login", {"login": "admin@v.test", "password": "AdminPass123"})["token"]
    def mk(e, n, role="student"):
        i = api("/users", {"email": e, "password": "Password123", "full_name": n, "role": role, "phone": "7771234"}, adm)["id"]; sql("UPDATE users SET must_change_password=0"); return i
    t1 = mk("t1@v.test", "Ustaz Ahmed", "teacher"); a2 = mk("a2@v.test", "Second Admin", "admin")
    ss = [mk(f"s{i}@v.test", n) for i, n in enumerate(["Aisha Ali", "Ibrahim Naseem", "Hassan Rasheed", "Mariyam Shifa"])]
    co = api("/courses", {"name": "Arabic Level 1", "monthly_fee_mvr": 500, "status": "open"}, adm)["id"]
    co2 = api("/courses", {"name": "Quran Tuition", "monthly_fee_mvr": 300, "status": "open", "kind": "tuition"}, adm)["id"]
    b1 = api("/batches", {"course_id": co, "code": "A1", "teacher_id": t1, "capacity": 20, "days": "Wed", "start_time": "16:00"}, adm)["id"]
    b2 = api("/batches", {"course_id": co2, "code": "Q1", "teacher_id": t1, "capacity": 20, "days": "Thu", "start_time": "16:00"}, adm)["id"]
    for i, s in enumerate(ss): api("/enrollments", {"student_id": s, "batch_id": b1 if i < 3 else b2, "start_date": "2026-08-01"}, adm)
    ids = [r[0] for r in sql("SELECT id FROM invoices WHERE student_id=?", (ss[0],))]
    api("/payments/mark-paid", {"invoice_ids": ",".join(map(str, ids)), "method": "cash", "paid_on": "2026-11-01"}, adm)
    ids = [r[0] for r in sql("SELECT id FROM invoices WHERE student_id=? AND period IN ('2026-08','2026-09')", (ss[1],))]
    api("/payments/mark-paid", {"invoice_ids": ",".join(map(str, ids)), "method": "cash", "paid_on": "2026-11-01"}, adm)
    import datetime as dt
    soon = (dt.datetime.now(dt.timezone(dt.timedelta(hours=5))).date() + dt.timedelta(days=3)).isoformat()
    sql("UPDATE invoices SET due_date=? WHERE student_id=? AND period=(SELECT MAX(period) FROM invoices WHERE student_id=?)", (soon, ss[3], ss[3]))
    sql("UPDATE users SET must_change_password=0")
    with sync_playwright() as p:
        br = p.chromium.launch()
        for width in (390, 1280):
            a = br.new_context(viewport={"width": width, "height": 900}, accept_downloads=True).new_page(); a.on("pageerror", lambda e: errors.append(str(e)))
            e2e_shim.login(a, BASE, "admin@v.test", "AdminPass123", db=DB)
            # ---- logo ----
            if width == 390:
                a.goto(BASE + "/#settings"); a.wait_for_selector("#logop")
                a.set_input_files("#logo_f", LOGO); a.click("[data-do=logoUp]"); a.wait_for_selector("#logop img", timeout=10000)
                check(a.locator("#logop img").count() == 1, "settings: logo preview after upload")
                SHOT(a, f"settings-logo-{width}")
            a.reload(); a.wait_for_selector("main h1")
            check(a.locator("img.mark.logo").count() >= 1, f"[{width}] menu shows the logo")
            href = a.evaluate("document.querySelector('link[rel=icon]').href")
            check("/api/public/logo" in href, f"[{width}] tab icon is the logo")
            # ---- Fees -> Reminders ----
            a.goto(BASE + "/#fees"); a.wait_for_selector("[data-tabs=fees]")
            a.click(e2e_shim.subtab("fees", "reminders")); a.wait_for_selector("text=Hassan Rasheed")
            card = a.locator(".sub", has_text="Hassan Rasheed")
            check(card.locator("text=MVR 1,500").count() >= 1 and card.locator(".chip").count() == 3, f"[{width}] reminder card: total MVR 1,500 and 3 months")
            check(a.locator(".sub", has_text="Mariyam Shifa").locator("text=due in 3 days").count() == 1, f"[{width}] due-soon card for the fee due in 3 days")
            SHOT(a, f"reminders-{width}")
            card.locator("[data-do=fxRemMsg]").click(); a.wait_for_selector("dialog.dlg[open]")
            check(a.locator("dialog.dlg[open]", has_text="Aug 2026, Sep 2026 and Oct 2026").count() == 1, f"[{width}] message names the months")
            a.click("dialog.dlg[open] button[value=ok]")
            if width == 390:
                a.context.route("https://wa.me/**", lambda r: r.fulfill(body="whatsapp", content_type="text/plain"))   # no real WhatsApp in the test
                with a.context.expect_page() as pop:
                    card.locator("[data-do=fxRem]").first.click()
                pop.value.wait_for_load_state()
                check("wa.me/9607771234" in pop.value.url and "Aug%202026" in pop.value.url, "WhatsApp opens with the number and the message")
                pop.value.close(); a.wait_for_timeout(600)
                check(a.locator(".sub", has_text="Hassan Rasheed").locator("text=Reminded today").count() + a.locator(".sub", has_text="Hassan Rasheed").locator(".msg.err").count() >= 1, "card shows reminded today")
            # ---- monthly report ----
            a.click(e2e_shim.subtab("fees", "report")); a.wait_for_selector("#fxr_m")
            a.fill("#fxr_m", "2026-10"); a.click("#fxr button.btn:not([type=button])"); a.wait_for_selector(".hbars")
            check(a.locator(".hbars .hb").count() == 2, f"[{width}] batch chart has 2 batches")
            hs = a.evaluate("[...document.querySelectorAll('.cols .col i')].map(i => i.getBoundingClientRect().height)")
            check(len(hs) >= 3 and max(hs) > 40, f"[{width}] 6-month columns are drawn ({[round(h) for h in hs]})")
            check(a.locator("table", has_text="Ustaz Ahmed").count() >= 1, f"[{width}] batch table names the teacher")
            sw = a.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
            check(sw, f"[{width}] no sideways scrolling on the report")
            SHOT(a, f"report-{width}")
            a.click("[data-do=fxPdf]"); a.wait_for_timeout(1500)
            check(a.locator("dialog[open]").count() + 1 >= 1, f"[{width}] PDF button works")
            if a.locator("dialog[open]").count(): SHOT(a, f"report-pdf-{width}"); a.keyboard.press("Escape")
            a.context.close()
        # ---- the sign-in page shows the logo ----
        g = br.new_context(viewport={"width": 390, "height": 800}).new_page(); g.on("pageerror", lambda e: errors.append(str(e)))
        g.goto(BASE + "/"); g.wait_for_selector("#le"); g.wait_for_timeout(500)
        check(g.locator(".hero img.mark").count() == 1, "sign-in page shows the logo"); SHOT(g, "signin-logo")
        # ---- student Home banner ----
        e2e_shim.login(g, BASE, "s2@v.test", "Password123", db=DB)
        g.goto(BASE + "/#home"); g.wait_for_selector("[data-fee-reminder]", timeout=10000)
        check(g.locator("[data-fee-reminder=overdue]", has_text="Aug 2026, Sep 2026 and Oct 2026").count() == 1, "student Home: overdue banner with the months")
        SHOT(g, "student-home-overdue")
        g.context.close(); g = br.new_context(viewport={"width": 390, "height": 800}).new_page(); g.on("pageerror", lambda e: errors.append(str(e)))
        e2e_shim.login(g, BASE, "s3@v.test", "Password123", db=DB)
        g.goto(BASE + "/#home"); g.wait_for_selector("[data-fee-reminder]", timeout=10000)
        check(g.locator("[data-fee-reminder=due_soon]", has_text="before the due date").count() == 1, "student Home: settle-before-the-due-date banner")
        SHOT(g, "student-home-due-soon")
        # ---- another full admin: sees Who's online, no buttons; no data clearing ----
        g.context.close(); g = br.new_context(viewport={"width": 390, "height": 800}).new_page(); g.on("pageerror", lambda e: errors.append(str(e)))
        e2e_shim.login(g, BASE, "a2@v.test", "Password123", db=DB)
        g.goto(BASE + "/#online"); g.wait_for_selector("main h1:has-text(\"Who's online\")")
        check(g.locator("[data-do=onKick],[data-do=onPause],[data-do=onSuspend],[data-do=onKickAll]").count() == 0, "second admin: no sign out / pause / suspend buttons")
        check(g.locator("text=Only the superadmin").count() == 1, "second admin: told only the superadmin can act")
        check(g.locator("tr:has-text('Admin') .tag", has_text="Superadmin").count() >= 1, "the superadmin is tagged")
        SHOT(g, "online-second-admin")
        g.goto(BASE + "/#settings"); g.wait_for_selector("#resetp")
        check(g.locator("[data-do=rdStart]").count() == 0 and g.locator("#resetp", has_text="Only the superadmin").count() == 1, "second admin: no Clear portal data button")
        br.close()
finally:
    srv.terminate()
print("\n" + ("ALL PASS" if not errors else f"{len(errors)} FAILED: " + "; ".join(errors)))
sys.exit(1 if errors else 0)
