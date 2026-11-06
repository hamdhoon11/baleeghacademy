"""Optional browser test (390px phone, real app): an admin searches for a teacher and opens the one-page view (profile, workload, batches,
students); a limited admin without the area has no tab; a teacher has no such tab.
Run: python tests/e2e_teacher_info.py (needs playwright + chromium)"""
import os, sys, time, subprocess, tempfile, shutil, json, urllib.request
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
env = dict(os.environ, DATABASE_PATH=os.path.join(tmp, "s.db"), ADMIN_EMAIL="admin@s.test", ADMIN_PASSWORD="AdminPass123", PORT="5085", SECRET_KEY="s")
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
srv = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(2)
BASE = "http://127.0.0.1:5085"; errors = []
def check(c, m):
    print("PASS" if c else "FAIL", m)
    if not c: errors.append(m)
def api(path, body=None, tok=None, method=None):
    r = urllib.request.Request(BASE + "/api" + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    return json.load(urllib.request.urlopen(r))
try:
    adm = api("/auth/login", {"email": "admin@s.test", "password": "AdminPass123"})["token"]
    a2 = api("/users", {"email": "a2@s.test", "password": "Password123", "full_name": "Limited Admin", "role": "admin"}, adm)["id"]
    api(f"/users/{a2}", {"permissions": ["student_information"]}, adm, "PATCH")
    a3 = api("/users", {"email": "a3@s.test", "password": "Password123", "full_name": "Teacher Viewer", "role": "admin"}, adm)["id"]
    api(f"/users/{a3}", {"permissions": ["teacher_information"]}, adm, "PATCH")
    with sync_playwright() as p:
        br = p.chromium.launch()
        def page_for():
            pg = br.new_context(viewport={"width": 390, "height": 800}).new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            return pg
        def login(pg, e, w): pg.goto(BASE + "/"); pg.fill("#le", e); pg.fill("#lp", w); pg.click("#fl button"); pg.wait_for_selector("nav")
        def opened(pg):
            pg.click("nav [data-v=teacher_information]"); pg.wait_for_selector("#tif")
            pg.fill("#tif_q", "demo"); pg.click("#tif button"); pg.wait_for_selector(".cl:has-text('Demo Teacher')")
            pg.click("[data-do=tiOpen]"); pg.wait_for_selector("[data-do=tiBack]")

        a = page_for(); login(a, "admin@s.test", "AdminPass123"); opened(a)
        check(a.locator("h2:has-text('Demo Teacher')").count() == 1, "admin opens the teacher's page")
        check(a.locator("h2:text-is('Workload')").count() == 1 and a.locator("h2:text-is('Batches')").count() == 1 and a.locator("h2:has-text('Students')").count() == 1, "workload, batches and students sections are shown")
        check(a.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "no sideways scroll on the phone")
        a.click("[data-do=tiBack]"); a.wait_for_selector("#tif"); check(True, "Back returns to the search")

        v = page_for(); login(v, "a3@s.test", "Password123"); opened(v); check(True, "an admin with only Teacher information can use it")
        l = page_for(); login(l, "a2@s.test", "Password123")
        check(l.locator("nav [data-v=teacher_information]").count() == 0 and l.locator("nav [data-v=student_information]").count() == 1, "an admin without the area has no Teacher information tab")
        t = page_for(); login(t, "teacher@baleegh.test", "ChangeMe-Teach1")
        check(t.locator("nav [data-v=teacher_information]").count() == 0, "a teacher has no Teacher information tab")
        br.close()
finally:
    srv.terminate(); shutil.rmtree(tmp, ignore_errors=True)
print("Problems:", errors or "none"); sys.exit(1 if errors else 0)
