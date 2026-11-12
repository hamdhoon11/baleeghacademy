"""Optional browser test (390px phone, real app), v0.8.38: Excel templates, imports and exports from the screens.
The admin downloads the student template, fills it with openpyxl as a person would in Excel, checks it (nothing saved) and imports it;
imports courses and expenses; downloads invoice and course exports; a teacher enters grades from the class-list template and downloads
the gradebook and the attendance register. Run: python tests/e2e_excel.py (needs playwright + chromium)"""
import os, sys, time, subprocess, tempfile, shutil, json, sqlite3, urllib.request
from openpyxl import load_workbook
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import e2e_shim  # noqa: F401
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(); DB = os.path.join(tmp, "x.db")
env = dict(os.environ, DATABASE_PATH=DB, ADMIN_EMAIL="admin@xl.test", ADMIN_PASSWORD="AdminPass123", PORT="5095", SECRET_KEY="xl")
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
def sql(q, a=()):
    c = sqlite3.connect(DB)
    try: r = c.execute(q, a).fetchall(); c.commit(); return r
    finally: c.close()
sql("UPDATE users SET must_change_password=0")
srv = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(2)
BASE = "http://127.0.0.1:5095"; errors = []
def check(c, m):
    print("PASS" if c else "FAIL", m)
    if not c: errors.append(m)
def api(path, body=None, tok=None, method=None):
    r = urllib.request.Request(BASE + "/api" + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    return json.load(urllib.request.urlopen(r))
def fill(path, rows, out):
    wb = load_workbook(path); ws = wb["Data"]
    for r in rows: ws.append(r)
    wb.save(out); return out
try:
    adm = api("/auth/login", {"email": "admin@xl.test", "password": "AdminPass123"})["token"]
    tch = api("/auth/login", {"email": "teacher@baleegh.test", "password": "ChangeMe-Teach1"})["token"]
    api("/courses/1", {"monthly_fee_mvr": 400}, adm, "PATCH")
    api("/invoices/generate", {"month": time.strftime("%Y-%m")}, adm)
    api("/expense-categories", {"name": "Rent"}, adm)
    aid = api("/batches/1/assignments", {"title": "Quiz 1", "kind": "test", "max_points": 20}, tch)["id"]
    with sync_playwright() as p:
        br = p.chromium.launch()
        def page_for():
            pg = br.new_context(viewport={"width": 390, "height": 800}, accept_downloads=True).new_page()
            pg.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
            return pg
        flat = lambda pg: pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        def dl(pg, sel):
            with pg.expect_download() as d: pg.click(sel)
            path = os.path.join(tmp, d.value.suggested_filename); d.value.save_as(path); return path, d.value.suggested_filename
        a = page_for(); e2e_shim.login(a, BASE, "admin@xl.test", "AdminPass123", db=DB)
        # ---- People: student template -> fill -> check -> import ----
        a.click("nav [data-v=people]"); a.wait_for_selector("[data-do=impPTpl]")
        a.select_option("#imp_k", "students")
        tpl, name = dl(a, "[data-do=impPTpl]")
        wb = load_workbook(tpl)
        check(name == "import-students-template.xlsx" and wb.sheetnames[:2] == ["Data", "Instructions"], "student template downloads with Data and Instructions sheets")
        f = fill(tpl, [["Mariyam Hassan", "mariyam@xl.test", "", "", "0779999"], ["No Email", "", "", "", ""]], os.path.join(tmp, "students.xlsx"))
        a.set_input_files("#imp_f", f); a.click("[data-do=impCheck]"); a.wait_for_selector("text=Check result: nothing was saved")
        check("1 would be created" in a.inner_text("main") and "email is missing" in a.inner_text("main"), "check shows 1 good row and the reason for the bad one")
        check(sql("SELECT COUNT(*) FROM users WHERE email='mariyam@xl.test'")[0][0] == 0, "nothing saved by the check")
        check("Chosen: students.xlsx" in a.inner_text("main"), "after the check the chosen file is still there")
        a.click("[data-do=impGo]"); e2e_shim.dialog(a); a.wait_for_selector("text=Temporary passwords are shown only now")
        check(sql("SELECT phone FROM users WHERE email='mariyam@xl.test'") == [("0779999",)], "student imported from Excel, phone keeps its leading 0")
        check(flat(a), "People does not scroll sideways")
        # ---- Courses: export + import ----
        a.click("nav [data-v=courses]"); a.wait_for_selector("[data-imp=courses]")
        path, name = dl(a, "[data-do=xlGet][data-p='/courses/export'][data-x=xlsx]")
        check(name == "courses.xlsx" and load_workbook(path).active["A1"].value == "code", "courses export downloads as Excel")
        a.click("[data-imp=courses] summary")
        tpl, _ = dl(a, "[data-imp=courses] [data-do=impTpl]")
        f = fill(tpl, [["HF1", "Hifz", "course", "", 600, 0]], os.path.join(tmp, "courses.xlsx"))
        a.set_input_files("#impf_courses", f); a.click("[data-imp=courses] [data-do=impChk]"); a.wait_for_selector("text=Every row passed")
        a.click("[data-imp=courses] [data-do=impRun]"); e2e_shim.dialog(a); a.wait_for_selector("td:text-is('Hifz')")
        check(sql("SELECT monthly_fee_mvr FROM courses WHERE code='HF1'") == [(600,)], "course imported and listed")
        check(flat(a), "Courses does not scroll sideways")
        # ---- Finance: expenses import ----
        a.click("nav [data-v=finance]"); a.wait_for_selector("[data-imp=expenses]"); a.click("[data-imp=expenses] summary")
        tpl, _ = dl(a, "[data-imp=expenses] [data-do=impTpl]")
        f = fill(tpl, [[time.strftime("%Y-%m-%d"), 1200, "Rent", "Office"], [time.strftime("%Y-%m-%d"), 50, "Tea", ""]], os.path.join(tmp, "exp.xlsx"))
        a.set_input_files("#impf_expenses", f); a.click("[data-imp=expenses] [data-do=impRun]"); e2e_shim.dialog(a); a.wait_for_selector("text=No category called Tea")
        check(sql("SELECT COUNT(*) FROM expenses WHERE amount_mvr=1200")[0][0] == 1, "the good expense was saved, the bad one listed with its reason")
        path, _ = dl(a, "[data-do=xlGet][data-p='/expenses/export'][data-x=xlsx]")
        check(load_workbook(path).active["D2"].value == 1200, "expenses export has the imported expense")
        # ---- Fees: invoices export ----
        a.click("nav [data-v=fees]"); a.click("[data-tabs=fees] [data-key=invoices]"); a.wait_for_selector("[data-do=xlGet][data-p='/invoices/export']")
        path, _ = dl(a, "[data-do=xlGet][data-p='/invoices/export'][data-x=xlsx]")
        ws = load_workbook(path).active
        check(ws["A1"].value == "invoice" and ws.max_row >= 2, "invoices export downloads with the listed invoices")
        # ---- Teacher: grades from the class-list template ----
        t = page_for(); e2e_shim.login(t, BASE, "teacher@baleegh.test", "ChangeMe-Teach1", db=DB)
        t.click("nav [data-v=classroom]"); t.click("[data-tabs=classroom] [data-key=assignments]"); t.wait_for_selector(f"[data-do=selA][data-id='{aid}']")
        t.click(f"[data-do=selA][data-id='{aid}']"); t.wait_for_selector("[data-imp=grades]"); t.click("[data-imp=grades] summary")
        tpl, name = dl(t, "[data-imp=grades] [data-do=impTpl]")
        wb = load_workbook(tpl); ws = wb["Data"]
        check(ws["B2"].value == "Demo Student", "grades template lists the class")
        ws["C2"] = 17; ws["D2"] = "Good"; wb.save(os.path.join(tmp, "grades.xlsx"))
        t.set_input_files("#impf_grades", os.path.join(tmp, "grades.xlsx")); t.click("[data-imp=grades] [data-do=impRun]"); e2e_shim.dialog(t); t.wait_for_selector("text=Imported")
        check(sql("SELECT grade FROM submissions WHERE assignment_id=?", (aid,)) == [(17.0,)], "grade saved from Excel")
        check(flat(t), "assignment page does not scroll sideways")
        t.click("[data-tabs=classroom] [data-key=gradebook]"); t.wait_for_selector("[data-do=xlAtt]")
        path, _ = dl(t, "[data-do=xlGet][data-p$='/gradebook']")
        check("Quiz 1 (/20)" in [c.value for c in load_workbook(path).active[1]], "gradebook Excel has the quiz column")
        path, name = dl(t, "[data-do=xlAtt]")
        check(name.startswith("attendance-") and load_workbook(path).active["A1"].value == "student_code", "attendance register downloads")
        br.close()
finally:
    srv.terminate(); shutil.rmtree(tmp, ignore_errors=True)
print("Problems:", errors or "none"); sys.exit(1 if errors else 0)
