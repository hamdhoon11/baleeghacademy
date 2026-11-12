"""Optional browser test (needs: pip install playwright && playwright install chromium).
Runs the real app on a phone-sized screen: admin sets class days, teacher marks attendance / creates assignment / uploads material,
student sees Join class, submits work, downloads files, sees grade; Phase 4 fees flow (bank details, invoices, slip upload, reject, verify, receipt); no sideways scrolling. Run: python tests/e2e_browser.py"""
import os, sys, time, subprocess, datetime as dt, tempfile, shutil
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import e2e_shim  # noqa: F401  (opens the phone menu when a script clicks a tab behind More)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
env = dict(os.environ, DATABASE_PATH=os.path.join(tmp, "e2e.db"), ADMIN_EMAIL="admin@e2e.test", ADMIN_PASSWORD="AdminPass123", PORT="5077", SECRET_KEY="e2e")
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
import sqlite3; _c = sqlite3.connect(env["DATABASE_PATH"]); _c.execute("UPDATE users SET must_change_password=0"); _c.commit(); _c.close()   # the forced first-sign-in password screen (Session 11) is not what these scripts test
srv = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2)
BASE = "http://127.0.0.1:5077"
errors, log = [], []
PROMPT = {"v": ""}   # what the browser answers when the app asks for a reason in a prompt() box
mv = dt.datetime.now(dt.timezone(dt.timedelta(hours=5)))
wd = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][mv.weekday()]
start = (mv + dt.timedelta(minutes=5)).strftime("%H:%M")
def ok(msg): log.append("PASS " + msg); print("PASS", msg)
def check(cond, msg):
    if not cond: log.append("FAIL " + msg); print("FAIL", msg); errors.append(msg)
    else: ok(msg)
open(os.path.join(tmp, "work.pdf"), "wb").write(b"%PDF-1.4 student work")
open(os.path.join(tmp, "lesson.pdf"), "wb").write(b"%PDF-1.4 lesson one")
open(os.path.join(tmp, "slip1.pdf"), "wb").write(b"%PDF-1.4 transfer slip one")
open(os.path.join(tmp, "slip2.pdf"), "wb").write(b"%PDF-1.4 transfer slip two")
try:
    with sync_playwright() as p:
        br = p.chromium.launch()
        def page_for():
            ctx = br.new_context(viewport={"width": 390, "height": 800}, accept_downloads=True)
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
            pg.on("console", lambda m: errors.append("console: " + m.text) if m.type == "error" and "fonts.g" not in m.text and "ERR_" not in m.text and "Failed to load resource" not in m.text else None)
            pg.on("dialog", lambda d: d.accept(PROMPT["v"]))
            return pg
        def login(pg, email, pw):
            e2e_shim.login(pg, BASE, email, pw, db=env["DATABASE_PATH"])   # Session 22
        # ---- admin sets class days, time and Meet link in the UI ----
        a = page_for(); login(a, "admin@e2e.test", "AdminPass123")
        a.click("nav [data-v=batches]"); a.wait_for_selector("[data-do=editB]")
        a.click("[data-do=editB][data-id='1']"); a.wait_for_selector("#be_t")
        a.check(f"input[name=bde][value={wd}]"); a.fill("#be_t", start)   # v0.8.33: the editor's day boxes are "bde" (the create form keeps "bd"); the Meet link is set in Classroom (Session 4)
        a.click("[data-do=saveB]"); a.wait_for_selector("text=Saved")
        check(wd in a.inner_text("table"), f"admin saved class day {wd} for batch 004")
        check(a.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "admin batches page does not scroll sideways on a phone"); a.screenshot(path=os.path.join(tempfile.gettempdir(), "baleegh-e2e-admin-batches.png"))
        # ---- teacher ----
        t = page_for(); login(t, "teacher@baleegh.test", "ChangeMe-Teach1")
        t.wait_for_selector(".next")
        check("Arabic · 004" in t.inner_text(".next") and "Next class" in t.inner_text(".next"), "teacher home shows the next class (Arabic batch 004)")
        t.click("nav [data-v=classroom]"); t.wait_for_selector(".seg")
        check(t.locator(".seg input[value=present]:checked").count() >= 1, "attendance roster loads with present by default")
        t.locator(".seg input[value=late]").first.click(); t.fill("#atopic", "Lesson 1")
        t.click("[data-do=saveAtt]"); t.wait_for_selector("text=Saved")
        check("Demo Student" in t.inner_text("table"), "attendance saved and summary lists the student")
        check(t.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "teacher attendance page does not scroll sideways on a phone"); t.screenshot(path=os.path.join(tempfile.gettempdir(), "baleegh-e2e-teacher-attendance.png"))
        t.click("[data-tabs=classroom] [data-key=assignments]"); t.wait_for_selector("#fa")
        t.fill("#at", "Copy lesson 1"); t.fill("#adesc", "Write the letters 3 times"); t.fill("#ad", (mv + dt.timedelta(days=2)).strftime("%Y-%m-%d"))
        t.click("#fa button"); t.wait_for_selector("text=Copy lesson 1")
        check(True, "teacher created an assignment")
        t.click("[data-tabs=classroom] [data-key=materials]"); t.wait_for_selector("#fm")
        t.fill("#mt", "Lesson 1 notes"); t.set_input_files("#mf", os.path.join(tmp, "lesson.pdf")); t.click("#fm button"); t.wait_for_selector("text=Lesson 1 notes")
        check(True, "teacher uploaded a material")
        t.click("[data-tabs=classroom] [data-key=schedule]"); t.wait_for_selector("[data-do=setSess]")
        check(wd in t.inner_text(".panel:has-text('Schedule')") or "Today" in t.inner_text("main"), "schedule lists today's class")
        t.fill("#ml", "https://meet.google.com/abc-defg-hij"); t.click("[data-do=saveLink]"); t.wait_for_selector("a[href='https://meet.google.com/abc-defg-hij']")   # Session 4: the class link is set in Classroom
        check(True, "teacher saved the class link in Classroom")
        # ---- student ----
        s = page_for(); login(s, "student@baleegh.test", "ChangeMe-Stud1")
        s.wait_for_selector(".next")
        check(s.locator(".next a.btn.big").count() == 1 and s.get_attribute(".next a.btn.big", "href") == "https://meet.google.com/abc-defg-hij", "student sees the Join class button (class starts in 5 minutes)")
        s.screenshot(path=os.path.join(tempfile.gettempdir(), "baleegh-e2e-student-home.png"))
        s.click("nav [data-v=assignments]"); s.wait_for_selector("[data-do=goA]"); s.click("[data-do=goA]"); s.wait_for_selector("#atext")
        s.fill("#atext", "alif ba ta"); s.set_input_files("#afile", os.path.join(tmp, "work.pdf")); s.click("[data-do=submitA]"); s.wait_for_selector("text=Submitted")
        check(True, "student submitted text and a file")
        check(e2e_shim.preview_bytes(s, "[data-do=dlSub]").startswith(b"%PDF"), "student can open their own submitted file (PDF preview tab)")
        s.click("nav [data-v=materials]"); s.wait_for_selector("[data-do=dlMat]")
        check(e2e_shim.preview_bytes(s, "[data-do=dlMat]").startswith(b"%PDF"), "student opened the material (PDF preview tab)")
        # ---- teacher grades, student sees it ----
        t.click("[data-tabs=classroom] [data-key=assignments]"); t.wait_for_selector("[data-do=selA]"); t.click("[data-do=selA]"); t.wait_for_selector("[id^=g_]")
        check("alif ba ta" in t.inner_text("main"), "teacher sees the written answer")
        t.fill("[id^=g_]", "90"); t.fill("[id^=f_]", "Mashaa Allah"); t.click("[data-do=saveG]"); t.wait_for_selector("text=Saved")
        s.click("nav [data-v=progress]"); s.wait_for_selector("text=Mashaa Allah")
        check("90/100" in s.inner_text("main") and "90%" in s.inner_text("main"), "student sees grade, feedback and average")
        check("Late" in s.inner_text("main") or "late" in s.inner_text("main").lower(), "student sees attendance status (late)")
        check(s.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "student progress page does not scroll sideways on a phone"); s.screenshot(path=os.path.join(tempfile.gettempdir(), "baleegh-e2e-student-progress.png"))
        # ---- Phase 4: fees ----
        a.click("nav [data-v=settings]"); a.click("[data-tabs=settings] [data-key=fees]"); a.wait_for_selector("#set_bank_name")   # Session 12: grouped settings
        a.fill("#set_bank_name", "Bank of Maldives"); a.fill("#set_bank_account_name", "Baleegh Academy"); a.fill("#set_bank_account_number", "7700000000001")
        a.click("[data-do=saveSet]"); a.wait_for_selector("text=Saved")
        a.click("nav [data-v=fees]"); a.wait_for_selector("[data-tabs=fees]")
        for tab in ("invoices", "record", "discounts", "overdue", "report", "slips"):
            a.click(f"[data-tabs=fees] [data-key={tab}]"); a.wait_for_selector(f"[data-tabs=fees] [data-key={tab}][aria-selected=true]"); a.wait_for_timeout(250)
            check(a.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), f"admin Fees > {tab} does not scroll sideways on a phone")
        a.click("[data-tabs=fees] [data-key=invoices]"); a.wait_for_selector("[data-do=fxGen]"); a.wait_for_selector("text=Demo Student")   # Session 9: opening Fees runs the catch-up, which already made this month's invoice
        check("MVR 350" in a.inner_text("main"), "this month's invoice exists: Demo Student, MVR 350")
        a.click("[data-do=fxGen]"); a.wait_for_selector("text=Created: 0")
        check("Skipped: 1" in a.inner_text("main"), "generating again creates nothing new (no duplicate invoice)")
        s.click("nav [data-v=fees]"); s.wait_for_selector("text=INV-")
        check("7700000000001" in s.inner_text("main") and "Bank of Maldives" in s.inner_text("main"), "student sees the bank details the admin entered")
        late_now = mv.day > 10   # the invoice is due on the 10th, so after that it is correctly shown as overdue
        check("MVR 350" in s.inner_text("main") and ("Overdue" if late_now else "Unpaid") in s.inner_text("main"), f"student sees the invoice: MVR 350, {'Overdue' if late_now else 'Unpaid'}")
        check(s.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "student Fees page does not scroll sideways on a phone")
        s.click("[data-do=fxUp]"); s.wait_for_selector("#fxs_f"); s.set_input_files("#fxs_f", os.path.join(tmp, "slip1.pdf")); s.click("#fxs button.btn.alt"); s.wait_for_selector("text=Slip sent. The academy will check it.")
        check("Your slip is waiting" in s.inner_text("main") and s.locator("[data-do=fxUp]").count() == 0, "after uploading, the student sees the slip is waiting and cannot upload a second one")
        s.screenshot(path=os.path.join(tempfile.gettempdir(), "baleegh-e2e-student-fees.png"))
        a.click("[data-tabs=fees] [data-key=slips]"); a.wait_for_selector("[data-do=fxVerify]")
        check("Demo Student" in a.inner_text("main") and "MVR 350" in a.inner_text("main"), "admin sees the slip in the verification queue")
        check(e2e_shim.preview_bytes(a, "[data-do=fxView]").startswith(b"%PDF"), "admin can open the uploaded slip")
        a.click("[data-do=fxReject]"); e2e_shim.dialog(a, "Slip is blurry"); a.wait_for_selector("text=No slips are waiting.")   # Session 4: reason dialog
        s.click("nav [data-v=home]"); s.click("nav [data-v=fees]"); s.wait_for_selector("text=Slip is blurry")
        check(s.locator("[data-do=fxUp]").count() == 1, "rejected slip shows its reason and the student can upload again")
        s.click("[data-do=fxUp]"); s.wait_for_selector("#fxs_f"); s.set_input_files("#fxs_f", os.path.join(tmp, "slip2.pdf")); s.click("#fxs button.btn.alt"); s.wait_for_selector("text=Slip sent. The academy will check it.")
        a.click("[data-tabs=fees] [data-key=record]"); a.click("[data-tabs=fees] [data-key=slips]"); a.wait_for_selector("[data-do=fxVerify]")
        a.fill("input[id^=fxv_]", "300"); a.click("[data-do=fxVerify]"); a.wait_for_selector("text=Verified. Receipt: BA-R-0001")
        s.click("nav [data-v=home]"); s.click("nav [data-v=fees]"); s.wait_for_selector("text=BA-R-0001")
        check(("Overdue" if late_now else "Part paid") in s.inner_text("main") and "MVR 50" in s.inner_text("main") and "MVR 300" in s.inner_text("main"), "partial payment: student sees MVR 300 paid, a balance of MVR 50, and the right status")
        a.click("[data-tabs=fees] [data-key=record]"); a.wait_for_selector("#fxp"); a.fill("#fxp_a", "50"); a.click("#fxp button.btn.alt"); a.wait_for_selector("text=BA-R-0002")
        s.click("nav [data-v=home]"); s.click("nav [data-v=fees]"); s.wait_for_selector("text=BA-R-0002")
        check("Paid" in s.locator(".panel .tag").first.inner_text() and s.locator("[data-do=fxUp]").count() == 0, "after the cash payment the invoice shows Paid and no upload button")
        with s.expect_download() as rd: s.locator("[data-do=fxRcpt]").first.click()
        pdf = open(rd.value.path(), "rb").read()
        check(rd.value.suggested_filename.startswith("receipt-BA-R-000") and pdf.startswith(b"%PDF") and b"Demo Student" in pdf and b"7700000000001" not in pdf, "student downloaded a PDF receipt (no bank account number on it)")
        check(s.evaluate("[...document.querySelectorAll('main button, main a.btn, main input:not([type=checkbox]):not([type=radio]), main select')].filter(e => e.offsetParent).every(e => e.getBoundingClientRect().height >= 43.5)"), "every button and field on the student Fees page is at least 44px tall")
        a.click("nav [data-v=dashboard]"); a.wait_for_selector(".stat:has-text('Revenue')")   # Session 8: the one Dashboard is admin.js's (Revenue card)
        check("MVR 350" in a.inner_text(".stat:has-text('Revenue')"), "admin dashboard shows the collected MVR 350 as revenue")
        a.click("nav [data-v=fees]"); a.click("[data-tabs=fees] [data-key=report]"); a.wait_for_selector("#fxr")
        check("MVR 350" in a.inner_text("main") and "Nobody owes anything" in a.inner_text("main"), "monthly report: collected 350 and nobody owes")
        with a.expect_download() as cd: a.click("[data-do=fxCsv]")
        csv_text = open(cd.value.path(), encoding="utf-8-sig").read()   # v0.8.34: CSVs start with a BOM for Excel
        check(csv_text.startswith("invoice,period") and "Demo Student" in csv_text and ",350,0,350,0,350,0," in csv_text, "monthly report CSV downloads with the right numbers")
        # ---- fees tab on a phone ----
        s.click("nav [data-v=fees]"); s.wait_for_selector("text=BA-R-0001"); s.wait_for_timeout(300)
        check(s.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "Fees tab does not scroll sideways on a phone")
        # ---- admin classroom monitor ----
        a.click("nav [data-v=classroom]"); a.wait_for_selector("select[data-ch=batch]")
        check(a.locator("select[data-ch=batch] option").count() >= 2, "admin can open any batch in the classroom")
        br.close()
finally:
    srv.terminate(); shutil.rmtree(tmp, ignore_errors=True)
print("\nJS/console errors:", errors or "none")
sys.exit(1 if errors else 0)
