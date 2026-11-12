"""Optional browser test (390px phone, real app), v0.8.41: Settings → Clear portal data. A limited admin does not see it; a full admin sees
the preview, must type the words and the password, and ends with admins only. Run: python tests/e2e_reset.py (needs playwright + chromium)"""
import os, sys, time, subprocess, tempfile, shutil, json, sqlite3, urllib.request
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import e2e_shim  # noqa: F401
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(); DB = os.path.join(tmp, "e41.db")
env = dict(os.environ, DATABASE_PATH=DB, ADMIN_EMAIL="admin@e41.test", ADMIN_PASSWORD="AdminPass123", PORT="5097", SECRET_KEY="e41-" + "k" * 40, SEED_DEMO="1")
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
def sql(q, a=()):
    c = sqlite3.connect(DB)
    try: r = c.execute(q, a).fetchall(); c.commit(); return r
    finally: c.close()
sql("UPDATE users SET must_change_password=0")
srv = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(2.5)
BASE = "http://127.0.0.1:5097"; errors = []
def check(c, m):
    print("PASS" if c else "FAIL", m)
    if not c: errors.append(m)
def api(path, body=None, tok=None, method=None):
    r = urllib.request.Request(BASE + "/api" + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    return json.load(urllib.request.urlopen(r))
try:
    adm = api("/auth/login", {"email": "admin@e41.test", "password": "AdminPass123"})["token"]
    api("/users", {"email": "lim@e41.test", "password": "Password123", "full_name": "Limited Admin", "role": "admin", "permissions": ["settings"]}, adm)
    with sync_playwright() as p:
        br = p.chromium.launch()
        def page_for():
            pg = br.new_context(viewport={"width": 390, "height": 800}).new_page()
            pg.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
            return pg
        lim = page_for(); e2e_shim.login(lim, BASE, "lim@e41.test", "Password123", db=DB)
        lim.click("nav [data-v=settings]"); lim.wait_for_selector("#setp")
        check(not lim.is_visible("#resetp"), "a limited admin with Settings does not see Clear portal data")
        pg = page_for(); e2e_shim.login(pg, BASE, "admin@e41.test", "AdminPass123", db=DB)
        pg.click("nav [data-v=settings]"); pg.wait_for_selector("#resetp")
        check("cannot be undone" in pg.inner_text("#resetp"), "a full admin sees the panel and its warning")
        users = sql("SELECT COUNT(*) FROM users")[0][0]
        def go_on():   # open the preview and press Continue; the second dialog (password and words) opens straight after it
            pg.click("[data-do=rdStart]"); pg.wait_for_selector("dialog.dlg[open] ul.dlg-list")
            pg.click("dialog.dlg[open] button[value=ok]"); pg.wait_for_selector("dialog.dlg[open] input[type=password]")
        pg.click("[data-do=rdStart]"); pg.wait_for_selector("dialog.dlg[open]")
        txt = pg.inner_text("dialog.dlg[open]")
        check("Courses: 3" in txt and "Batches: 2" in txt and "Teacher and student accounts: 2" in txt and "Kept: 2 admin" in txt, "the preview lists what goes and what stays")
        check(pg.evaluate("document.activeElement && document.activeElement.value") == "cancel", "the dialog starts on Cancel")
        e2e_shim.dialog(pg, ok=False)
        check(sql("SELECT COUNT(*) FROM users")[0][0] == users and sql("SELECT COUNT(*) FROM courses")[0][0] == 3, "Cancel deletes nothing")
        go_on()
        pg.fill("dialog.dlg[open] input[type=password]", "AdminPass123"); pg.fill("dialog.dlg[open] input[type=text]", "delete")
        pg.click("dialog.dlg[open] button[value=ok]"); time.sleep(.4)
        check(pg.is_visible("dialog.dlg[open]") and sql("SELECT COUNT(*) FROM courses")[0][0] == 3, "the wrong words are refused inside the dialog")
        pg.fill("dialog.dlg[open] input[type=text]", "DELETE ALL DATA"); pg.fill("dialog.dlg[open] input[type=password]", "not-my-password")
        pg.click("dialog.dlg[open] button[value=ok]"); pg.wait_for_selector("[role=alert]")
        check(sql("SELECT COUNT(*) FROM courses")[0][0] == 3, "a wrong password deletes nothing and shows a message")
        go_on()
        pg.fill("dialog.dlg[open] input[type=password]", "AdminPass123"); pg.fill("dialog.dlg[open] input[type=text]", "DELETE ALL DATA")
        pg.click("dialog.dlg[open] button[value=ok]"); pg.wait_for_selector("dialog.dlg[open]", state="detached")
        pg.wait_for_function("() => document.body.innerText.includes('Admin accounts, settings and the activity log were kept')", timeout=15000)
        check(sql("SELECT role, COUNT(*) FROM users GROUP BY role") == [("admin", 2)], "only the two admins are left")
        check(sql("SELECT (SELECT COUNT(*) FROM courses) + (SELECT COUNT(*) FROM batches) + (SELECT COUNT(*) FROM enrollments)")[0][0] == 0, "courses, batches and enrolments are gone")
        pg.click("nav [data-v=people]"); pg.wait_for_selector("main table")
        check("Demo Teacher" not in pg.inner_text("main") and "Academy Admin" in pg.inner_text("main"), "People shows the admins and no demo accounts")
        pg.click("nav [data-v=settings]"); pg.wait_for_selector("#resetp"); pg.click("[data-do=rdStart]")
        pg.wait_for_function("() => document.body.innerText.includes('There is nothing to delete')", timeout=15000)
        check(not pg.is_visible("dialog.dlg[open]"), "a second time says there is nothing to delete")
        check(pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "no sideways scrolling on a phone")
        br.close()
finally:
    srv.terminate(); shutil.rmtree(tmp, ignore_errors=True)
print("\nProblems:", errors or "none"); sys.exit(1 if errors else 0)
