"""Optional browser test for per-user permissions (needs: pip install playwright && playwright install chromium).
Admin limits the demo student in the People screen; the student then sees only the allowed tabs; a student cannot reach a blocked screen's data.
Run: python tests/e2e_permissions.py"""
import os, sys, time, subprocess, tempfile, shutil
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import e2e_shim  # noqa: F401  (opens the phone menu when a script clicks a tab behind More)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
env = dict(os.environ, DATABASE_PATH=os.path.join(tmp, "p.db"), ADMIN_EMAIL="admin@p.test", ADMIN_PASSWORD="AdminPass123", PORT="5078", SECRET_KEY="p")
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
import sqlite3; _c = sqlite3.connect(env["DATABASE_PATH"]); _c.execute("UPDATE users SET must_change_password=0"); _c.commit(); _c.close()   # the forced first-sign-in password screen (Session 11) is not what these scripts test
srv = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2)
BASE = "http://127.0.0.1:5078"
errors = []
def check(cond, msg):
    print("PASS" if cond else "FAIL", msg)
    if not cond: errors.append(msg)
try:
    with sync_playwright() as p:
        br = p.chromium.launch()
        def page_for():
            pg = br.new_context(viewport={"width": 390, "height": 800}).new_page()
            pg.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
            pg.on("console", lambda m: errors.append("console: " + m.text) if m.type == "error" and "fonts.g" not in m.text and "ERR_" not in m.text and "Failed to load resource" not in m.text else None)
            pg.on("dialog", lambda d: d.accept())
            return pg
        def login(pg, email, pw):
            e2e_shim.login(pg, BASE, email, pw, db=env["DATABASE_PATH"])   # Session 22
        nav = lambda pg: [b.get_attribute("data-v") for b in pg.query_selector_all("nav [data-v]")]
        s = page_for(); login(s, "student@baleegh.test", "ChangeMe-Stud1")
        server = s.evaluate("S.user.tabs")   # Session 9: the phone bar puts Fees 4th, so compare the tabs, not their DOM order
        check(sorted(nav(s)) == sorted(["home", "timetable", "assignments", "progress", "materials", "recordings", "fees", "tutorials", "my_files", "my_information"]) and sorted(server) == sorted(nav(s)), "student starts with every student tab")
        check(s.query_selector("nav .lang") is None and s.query_selector("[data-l]") is None, "no language switch in the app")
        a = page_for(); login(a, "admin@p.test", "AdminPass123")
        a.click("nav [data-v=people]"); a.wait_for_selector("[data-do=euEdit]")
        a.locator("tr", has_text="Demo Student").locator("[data-do=euEdit]").click(); a.wait_for_selector("#pm_limited")
        check(a.locator("input[name=pa]").count() == 7, "student editor lists the 7 student areas")
        a.check("#pm_limited"); a.uncheck("input[name=pa][value=fees]"); a.uncheck("input[name=pa][value=progress]")
        for k in ("assignments", "materials", "tutorials"): a.check(f"input[name=pa][value={k}]")
        a.click("#fue button.btn.alt"); a.wait_for_selector("tr:has-text('Demo Student') .tag:has-text('Limited')")
        check(True, "people list marks the student as Limited")
        s.reload(); s.wait_for_selector("nav")
        check(sorted(t_ for t_ in nav(s) if t_ != "my_information") == sorted(["home", "timetable", "my_files", "assignments", "materials", "tutorials"]), "student now sees only the ticked tabs")
        code = s.evaluate("fetch('/api/my/grades',{headers:{Authorization:'Bearer '+sessionStorage.getItem('tok')}}).then(r=>r.status)")
        check(code == 403, "server refuses the blocked data even when the page asks for it")
        s.click("nav [data-v=home]"); s.wait_for_selector("h1")
        check(s.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "no sideways scroll on a phone")
        br.close()
finally:
    srv.terminate(); shutil.rmtree(tmp, ignore_errors=True)
print("\nProblems:", errors or "none"); sys.exit(1 if errors else 0)
