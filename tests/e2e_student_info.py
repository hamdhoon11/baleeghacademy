"""Optional browser test (390px phone, real app): an admin searches for a student and opens the one-page view (profile, batches,
attendance, grades, fees); a limited admin without Fees sees it with the fees hidden; a teacher has no such tab.
Run: python tests/e2e_student_info.py (needs playwright + chromium)"""
import os, sys, time, subprocess, tempfile, shutil, json, urllib.request
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
env = dict(os.environ, DATABASE_PATH=os.path.join(tmp, "s.db"), ADMIN_EMAIL="admin@s.test", ADMIN_PASSWORD="AdminPass123", PORT="5084", SECRET_KEY="s")
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
srv = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(2)
BASE = "http://127.0.0.1:5084"; errors = []
def check(c, m):
    print("PASS" if c else "FAIL", m)
    if not c: errors.append(m)
def api(path, body=None, tok=None, method=None):
    r = urllib.request.Request(BASE + "/api" + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    return json.load(urllib.request.urlopen(r))
try:
    adm = api("/auth/login", {"email": "admin@s.test", "password": "AdminPass123"})["token"]
    api("/courses/1", {"monthly_fee_mvr": 400}, adm, "PATCH")
    api("/invoices/generate", {"month": time.strftime("%Y-%m")}, adm)
    a2 = api("/users", {"email": "a2@s.test", "password": "Password123", "full_name": "Limited Admin", "role": "admin"}, adm)["id"]
    api(f"/users/{a2}", {"permissions": ["student_information"]}, adm, "PATCH")
    with sync_playwright() as p:
        br = p.chromium.launch()
        def page_for():
            pg = br.new_context(viewport={"width": 390, "height": 800}).new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            return pg
        def login(pg, e, w): pg.goto(BASE + "/"); pg.fill("#le", e); pg.fill("#lp", w); pg.click("#fl button"); pg.wait_for_selector("nav")
        def opened(pg):
            pg.click("nav [data-v=student_information]"); pg.wait_for_selector("#sif")
            pg.fill("#sif_q", "demo"); pg.click("#sif button"); pg.wait_for_selector(".cl:has-text('Demo Student')")
            pg.click("[data-do=siOpen]"); pg.wait_for_selector("[data-do=siBack]")

        a = page_for(); login(a, "admin@s.test", "AdminPass123"); opened(a)
        check(a.locator("h2:has-text('Demo Student')").count() == 1, "admin opens the student's page")
        check(a.locator("h2:text-is('Batches')").count() == 1 and a.locator("h2:text-is('Fees')").count() == 1, "batches and fees sections are shown")
        check(a.locator("text=Attendance and grades").count() == 1, "attendance and grades section is shown")
        check(a.locator("text=MVR 400").count() >= 1, "fees show the invoice amount")
        check(a.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "no sideways scroll on the phone")
        a.click("[data-do=siBack]"); a.wait_for_selector("#sif"); check(True, "Back returns to the search")

        l = page_for(); login(l, "a2@s.test", "Password123"); opened(l)
        check(l.locator("text=does not have the Fees permission").count() == 1 and l.locator("text=MVR 400").count() == 0, "limited admin sees no fee details")
        t = page_for(); login(t, "teacher@baleegh.test", "ChangeMe-Teach1")
        check(t.locator("nav [data-v=student_information]").count() == 0, "a teacher has no Student information tab")
        br.close()
finally:
    srv.terminate(); shutil.rmtree(tmp, ignore_errors=True)
print("Problems:", errors or "none"); sys.exit(1 if errors else 0)
