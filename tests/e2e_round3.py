"""Optional browser test (390px phone, real app), v0.8.37 Round 3: tutorial grading (teacher grades, student sees it), the week timetable,
My files, bulk actions (waive invoices, make accounts inactive) and monthly expenses. Run: python tests/e2e_round3.py (needs playwright + chromium)"""
import os, sys, time, subprocess, tempfile, shutil, json, sqlite3, urllib.request
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import e2e_shim  # noqa: F401
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(); DB = os.path.join(tmp, "r3.db")
env = dict(os.environ, DATABASE_PATH=DB, ADMIN_EMAIL="admin@r3.test", ADMIN_PASSWORD="AdminPass123", PORT="5093", SECRET_KEY="r3")
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
open(os.path.join(tmp, "notes.pdf"), "wb").write(b"%PDF-1.4 notes")
try:
    adm = api("/auth/login", {"email": "admin@r3.test", "password": "AdminPass123"})["token"]
    tch = api("/auth/login", {"email": "teacher@baleegh.test", "password": "ChangeMe-Teach1"})["token"]
    stu = api("/auth/login", {"email": "student@baleegh.test", "password": "ChangeMe-Stud1"})["token"]
    api("/courses/1", {"monthly_fee_mvr": 400}, adm, "PATCH")
    api("/batches/1", {"days": "Mon,Tue,Wed,Thu,Fri,Sat,Sun", "start_time": "16:00"}, adm, "PATCH")
    api("/invoices/generate", {"month": time.strftime("%Y-%m")}, adm)
    for i in range(2): api("/users", {"email": f"old{i}@r3.test", "password": "Password123", "full_name": f"Old Student {i}", "role": "student"}, adm)
    with sync_playwright() as p:
        br = p.chromium.launch()
        def page_for():
            pg = br.new_context(viewport={"width": 390, "height": 800}, accept_downloads=True).new_page()
            pg.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
            return pg
        flat = lambda pg: pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        # ---- teacher posts a tutorial; student answers ----
        t = page_for(); e2e_shim.login(t, BASE, "teacher@baleegh.test", "ChangeMe-Teach1", db=DB)
        t.click("nav [data-v=tutorials]"); t.wait_for_selector("#tfp")
        check(t.input_value("#tp_m") == "100", "the post form has Marks out of (100 by default)")
        t.fill("#tp_t", "Write five words"); t.fill("#tp_x", "Use new letters"); t.fill("#tp_m", "10"); t.click("#tfp button.btn.alt"); t.wait_for_selector("text=Write five words")
        s = page_for(); e2e_shim.login(s, BASE, "student@baleegh.test", "ChangeMe-Stud1", db=DB)
        s.click("nav [data-v=tutorials]"); s.wait_for_selector("[data-do=openT]"); s.click("[data-do=openT]"); s.wait_for_selector("#tans_x")
        s.fill("#tans_x", "alif ba ta tha jim"); s.click("[data-do=sendTAns]"); s.wait_for_selector("text=Answered")
        # ---- teacher grades from the answers list ----
        t.click("nav [data-v=home]"); t.wait_for_selector("text=tutorial answers to grade")
        check(True, "teacher Home shows tutorial answers to grade")
        t.click("nav [data-v=tutorials]"); t.wait_for_selector("text=1 to grade"); t.click("[data-do=openT]"); t.wait_for_selector("[data-do=tGrade]")
        t.fill("input[id^=tg_]", "9"); t.fill("input[id^=tc_]", "Very good"); t.click("[data-do=tGrade]"); t.wait_for_selector("text=Grade 9/10")
        check(t.locator("text=Saved. Only an admin").count() == 1, "after saving, the teacher sees the grade and that changing it needs permission")
        check(flat(t), "teacher Tutorials does not scroll sideways"); t.locator(".sub").first.screenshot(path=os.path.join(tempfile.gettempdir(), "baleegh-e2e-tutorial-grade.png"))
        s.click("nav [data-v=home]"); s.click("nav [data-v=tutorials]"); s.wait_for_selector("text=Grade 9/10")
        s.click("[data-do=openT]"); s.wait_for_selector("text=Very good")
        check(True, "student sees the grade 9/10 and the feedback")
        # ---- timetable ----
        s.click("nav [data-v=timetable]"); s.wait_for_selector(".tt-d")
        check(s.locator(".tt-d").count() == 7 and s.locator(".tt-d.now").count() == 1, "student timetable shows seven days with today marked")
        check(s.locator(".tt-i").count() >= 7, "every day has the class")
        check(flat(s), "timetable does not scroll sideways on a phone"); s.screenshot(path=os.path.join(tempfile.gettempdir(), "baleegh-e2e-timetable.png"))
        s.click("[data-do=ttWeek][data-w='1']"); s.wait_for_selector("[data-do=ttWeek][data-w='0']")
        check(s.locator(".tt-d.now").count() == 0, "next week has no 'today'")
        # ---- my files ----
        rq = urllib.request.Request(BASE + "/api/batches/1/materials", method="POST", headers={"Authorization": "Bearer " + tch, "Content-Type": "multipart/form-data; boundary=XX"},
                                    data=b'--XX\r\nContent-Disposition: form-data; name="title"\r\n\r\nWeek 1 notes\r\n--XX\r\nContent-Disposition: form-data; name="file"; filename="notes.pdf"\r\nContent-Type: application/pdf\r\n\r\n%PDF-1.4 notes\r\n--XX--\r\n')
        urllib.request.urlopen(rq)
        s.click("nav [data-v=my_files]"); s.wait_for_selector("[data-do=mfOpen]")
        check("Week 1 notes" in s.inner_text("main") and "Material" in s.inner_text("main"), "My files lists the class material")
        check(e2e_shim.preview_bytes(s, "[data-do=mfOpen]").startswith(b"%PDF"), "the file opens from My files")
        check(flat(s), "My files does not scroll sideways")
        # ---- admin: bulk waive, bulk inactive, monthly expense ----
        a = page_for(); e2e_shim.login(a, BASE, "admin@r3.test", "AdminPass123", db=DB)
        a.click("nav [data-v=timetable]"); a.wait_for_selector(".tt-d"); check(a.locator("#ttf_t").count() == 1, "admin timetable has a teacher filter")
        a.click("nav [data-v=fees]"); a.click("[data-tabs=fees] [data-key=invoices]"); a.wait_for_selector("input.bulk[data-g=inv]")
        n_open = a.locator("input.bulk[data-g=inv]").count()
        check(a.locator("[data-bulkbar=inv]").is_hidden(), "the bulk bar is hidden until something is ticked")
        a.check("input.bulk-all[data-g=inv]"); a.wait_for_selector("[data-bulkbar=inv]:not([hidden])")
        check(a.inner_text("[data-bulkbar=inv] [data-bulkn]") == str(n_open), f"select all ticks the {n_open} open invoices")
        a.click("[data-do=fxBulkWaive]"); e2e_shim.dialog(a, "Scholarship"); a.wait_for_selector(f"text=Done for {n_open} of {n_open}.")
        check(sql("SELECT COUNT(*) FROM invoices WHERE status='waived'")[0][0] == n_open, "all ticked invoices were waived, each with the reason")
        a.click("nav [data-v=people]"); a.wait_for_selector("input.bulk[data-g=ppl]")
        for i in range(2): a.locator(f"tr:has-text('Old Student {i}') input.bulk").check()
        a.click("[data-do=peBulkOff]"); e2e_shim.dialog(a); a.wait_for_selector("text=Done for 2 of 2.")
        check(sql("SELECT COUNT(*) FROM users WHERE full_name LIKE 'Old Student%' AND is_active=0")[0][0] == 2, "two accounts made inactive in one go")
        check(a.locator("tr:has-text('admin@r3.test') input.bulk").count() == 0, "your own account cannot be ticked")
        a.click("nav [data-v=finance]"); a.wait_for_selector("#fcat")
        a.fill("#fc_name", "Rent"); a.click("#fcat button"); a.wait_for_selector("#frec", state="attached")
        if not a.is_visible("#frec"): a.click("details.addp:has(#frec) summary")
        a.fill("#fr2_amt", "7000"); a.fill("#fr2_day", "1"); a.fill("#fr2_desc", "Office rent"); a.click("#frec button.btn.alt")
        a.wait_for_selector(".cl:has-text('Office rent')")
        check("Office rent" in a.inner_text("main") and "monthly" in a.inner_text("main"), "the monthly expense is listed and this month's expense was entered")
        check(sql("SELECT COUNT(*) FROM expenses WHERE recurring_id IS NOT NULL")[0][0] == 1, "exactly one expense written for this month")
        check(flat(a), "Finance does not scroll sideways"); a.locator(".panel:has-text('Monthly expenses')").screenshot(path=os.path.join(tempfile.gettempdir(), "baleegh-e2e-monthly.png"))
        a.set_viewport_size({"width": 1280, "height": 900}); a.click("nav [data-v=timetable]"); a.wait_for_selector(".tt-d"); a.screenshot(path=os.path.join(tempfile.gettempdir(), "baleegh-e2e-timetable-wide.png"))
        br.close()
finally:
    srv.terminate(); shutil.rmtree(tmp, ignore_errors=True)
print("Problems:", errors or "none"); sys.exit(1 if errors else 0)
