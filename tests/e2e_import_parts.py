"""Optional browser test (390px phone, real app), v0.8.42: long import files travel in parts of 10 rows. People: 45 students (Check, then Import,
new-accounts download offered). Courses: 25 courses with one code repeated far apart. A part that fails says where the import stopped.
Run: python tests/e2e_import_parts.py (needs playwright + chromium)"""
import os, sys, time, subprocess, tempfile, shutil, sqlite3
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import e2e_shim  # noqa: F401
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(); DB = os.path.join(tmp, "e42.db")
env = dict(os.environ, DATABASE_PATH=DB, ADMIN_EMAIL="admin@e42.test", ADMIN_PASSWORD="AdminPass123", PORT="5098", SECRET_KEY="e42-" + "k" * 40, SEED_DEMO="0")
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
def sql(q, a=()):
    c = sqlite3.connect(DB)
    try: r = c.execute(q, a).fetchall(); c.commit(); return r
    finally: c.close()
sql("UPDATE users SET must_change_password=0")
srv = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(2.5)
BASE = "http://127.0.0.1:5098"; errors = []
def check(c, m):
    print("PASS" if c else "FAIL", m)
    if not c: errors.append(m)
students = "full_name,email,phone\n" + "".join(f"Student {i},st{i}@e42.test,77{i:05d}\n" for i in range(45))
more = "full_name,email\n" + "".join(f"More {i},more{i}@e42.test\n" for i in range(50))
courses = "code,name,monthly_fee_mvr\n" + "".join(f"K{i:02d},Course {i},100\n" for i in range(24)) + "k03,Course 3 again,100\n"
csv = lambda name, text: {"name": name, "mimeType": "text/csv", "buffer": text.encode()}
try:
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_context(viewport={"width": 390, "height": 800}).new_page()
        pg.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
        sent = []
        pg.on("request", lambda r: sent.append(r.url) if "/api/import/" in r.url and r.method == "POST" else None)
        e2e_shim.login(pg, BASE, "admin@e42.test", "AdminPass123", db=DB)
        pg.click("nav [data-v=people]"); pg.wait_for_selector("#imp_f")
        panel = lambda: pg.evaluate("document.querySelector('#imp_f').closest('.panel').innerText").lower()
        pg.set_input_files("#imp_f", csv("students.csv", students)); pg.click("[data-do=impCheck]")
        pg.wait_for_function("() => document.body.innerText.toLowerCase().includes('45 would be created')", timeout=30000)
        check("0 rejected / 45" in panel() and sql("SELECT COUNT(*) FROM users WHERE role='student'")[0][0] == 0, "Check: 45 would be created, 0 rejected, nothing saved")
        check(len(sent) == 5 and all("limit=10" in u and "dry_run=1" in u for u in sent) and [u.split("offset=")[1].split("&")[0] for u in sent] == ["0", "10", "20", "30", "40"], "the check went in five parts of 10 rows")
        del sent[:]
        pg.click("[data-do=impGo]"); e2e_shim.dialog(pg)
        pg.wait_for_function("() => document.body.innerText.toLowerCase().includes('45 created')", timeout=60000)
        check(sql("SELECT COUNT(*) FROM users WHERE role='student'")[0][0] == 45 and len(sent) == 5, "Import: 45 students saved in five parts")
        check(pg.is_visible("[data-do=impCreds]"), "the new-accounts download (temporary passwords) is offered for all of them")
        with pg.expect_download() as d: pg.click("[data-do=impCreds]")
        lines = open(d.value.path(), encoding="utf-8").read().strip().split("\n")
        check(len(lines) == 46 and lines[1].startswith('"BAL/STU/'), "the download lists all 45 accounts with their sign-in IDs")
        # a part that fails half way: the screen says how far it got
        n = {"k": 0}
        def flaky(route):
            n["k"] += 1
            route.fulfill(status=504, content_type="text/html", body="<html>timeout</html>") if n["k"] == 2 else route.continue_()
        pg.route("**/api/import/students*", flaky)
        pg.set_input_files("#imp_f", csv("more.csv", more)); pg.click("[data-do=impGo]"); e2e_shim.dialog(pg)
        pg.wait_for_selector(".panel:has(#imp_f) [role=alert]", timeout=60000)
        txt = panel()
        check("stopped after 10 of 50 rows" in txt and "did not finish in time" in txt and "10 created" in txt, "a part that times out: the screen says it stopped after 10 of 50 rows")
        check(sql("SELECT COUNT(*) FROM users WHERE email LIKE 'more%'")[0][0] == 10, "the 10 rows before the stop are saved, none after")
        pg.unroute("**/api/import/students*")
        pg.set_input_files("#imp_f", csv("more.csv", more)); pg.click("[data-do=impGo]"); e2e_shim.dialog(pg)
        pg.wait_for_function("() => document.body.innerText.toLowerCase().includes('40 created')", timeout=60000)
        check(sql("SELECT COUNT(*) FROM users WHERE email LIKE 'more%'")[0][0] == 50 and "10 rejected / 50" in panel(), "importing the same file again adds the other 40 and refuses the 10 already there")
        # courses: the repeated code is 22 rows away, in another part
        pg.click("nav [data-v=courses]"); pg.wait_for_selector("details[data-imp=courses]"); pg.click("details[data-imp=courses] summary")
        box = lambda: pg.evaluate("document.querySelector('details[data-imp=courses]').innerText").lower()
        pg.set_input_files("#impf_courses", csv("courses.csv", courses)); pg.click("[data-do=impChk][data-k=courses]")
        pg.wait_for_function("() => document.querySelector('details[data-imp=courses]').innerText.toLowerCase().includes('24 would be created')", timeout=30000)
        check("1 rejected / 25" in box() and "already in row 5 of this file" in box() and sql("SELECT COUNT(*) FROM courses WHERE code LIKE 'K__'")[0][0] == 0, "Courses check in parts finds the code repeated 22 rows earlier; nothing saved")
        pg.click("[data-do=impRun][data-k=courses]"); e2e_shim.dialog(pg)
        pg.wait_for_function("() => document.querySelector('details[data-imp=courses]').innerText.toLowerCase().includes('24 created')", timeout=60000)
        check(sql("SELECT COUNT(*) FROM courses WHERE code LIKE 'K__'")[0][0] == 24, "Courses import: 24 saved, the repeated one refused")
        check(pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "no sideways scrolling on a phone")
        br.close()
finally:
    srv.terminate(); shutil.rmtree(tmp, ignore_errors=True)
print("\nProblems:", errors or "none"); sys.exit(1 if errors else 0)
