"""Optional browser test (phone-sized screen, real app): a teacher adds a Drive recording, the student of that batch sees Open/Download,
another teacher cannot see it, and a teacher without Add class recordings sees no form.
Run: python tests/e2e_recordings.py (needs playwright + chromium)"""
import os, sys, time, subprocess, tempfile, shutil, json, urllib.request, datetime as dt
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import e2e_shim  # noqa: F401  (opens the phone menu when a script clicks a tab behind More)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
env = dict(os.environ, DATABASE_PATH=os.path.join(tmp, "s.db"), ADMIN_EMAIL="admin@s.test", ADMIN_PASSWORD="AdminPass123", PORT="5083", SECRET_KEY="s")
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
import sqlite3; _c = sqlite3.connect(env["DATABASE_PATH"]); _c.execute("UPDATE users SET must_change_password=0"); _c.commit(); _c.close()   # the forced first-sign-in password screen (Session 11) is not what these scripts test
srv = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(2)
BASE = "http://127.0.0.1:5083"; errors = []
def check(c, m):
    print("PASS" if c else "FAIL", m)
    if not c: errors.append(m)
def api(path, body=None, tok=None, method=None):
    r = urllib.request.Request(BASE + "/api" + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    return json.load(urllib.request.urlopen(r))
LINK = "https://drive.google.com/file/d/1AbCdEf/view"
today = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5)).strftime("%Y-%m-%d")
try:
    adm = api("/auth/login", {"email": "admin@s.test", "password": "AdminPass123"})["token"]
    t2 = api("/users", {"email": "t2@s.test", "password": "Password123", "full_name": "Limited Teacher", "role": "teacher"}, adm)["id"]
    api("/batches", {"course_id": 1, "code": "L1", "teacher_id": t2, "capacity": 5}, adm)
    t3 = api("/users", {"email": "t3@s.test", "password": "Password123", "full_name": "No Recordings", "role": "teacher"}, adm)["id"]
    api("/batches", {"course_id": 1, "code": "N1", "teacher_id": t3, "capacity": 5}, adm)
    api(f"/users/{t3}", {"permissions": ["classroom"]}, adm, "PATCH")
    with sync_playwright() as p:
        br = p.chromium.launch()
        def page_for():
            pg = br.new_context(viewport={"width": 390, "height": 800}).new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            return pg
        def login(pg, e, w): e2e_shim.login(pg, BASE, e, w, db=env["DATABASE_PATH"])   # Session 22: forced change, course chooser, waits for the app
        def recs(pg): pg.click("nav [data-v=classroom]"); pg.wait_for_selector("[data-tabs=classroom] [data-key=recordings]"); pg.click("[data-tabs=classroom] [data-key=recordings]"); pg.wait_for_selector("h2:has-text('Recordings')")

        t = page_for(); login(t, "teacher@baleegh.test", "ChangeMe-Teach1"); recs(t)
        t.wait_for_selector("#fr"); check(t.locator("#fr").count() == 1, "teacher sees the Add a recording form")
        t.fill("#rt", "Lesson 1 recording"); t.fill("#rd", today); t.fill("#ru", LINK); t.click("#fr button")
        t.wait_for_selector(".cl:has-text('Lesson 1 recording')"); check(True, "teacher adds a recording and it is listed")
        t.fill("#ru", "https://evil.example/x"); t.fill("#rt", "Bad"); t.fill("#rd", today); t.click("#fr button")
        time.sleep(1)
        check(t.locator(".cl:has-text('Bad')").count() == 0, "a non-Drive link is refused")

        s = page_for(); login(s, "student@baleegh.test", "ChangeMe-Stud1"); s.click("nav [data-v=recordings]"); s.wait_for_selector(".cl")
        check(s.locator(f".cl:has-text('Lesson 1 recording') a[href='{LINK}']").count() == 1, "student sees the recording with an Open link")
        check(s.locator("a:has-text('Download')").count() == 1 and "export=download&id=1AbCdEf" in s.locator("a:has-text('Download')").get_attribute("href"), "and a Download link")
        check(s.locator("[data-do=delRec]").count() == 0, "student cannot delete")
        check(s.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "student page fits the phone width")

        l = page_for(); login(l, "t2@s.test", "Password123"); l.click("nav [data-v=classroom]"); l.wait_for_selector("[data-tabs=classroom]")   # one batch: no picker, the batch name is the heading
        l.click("[data-tabs=classroom] [data-key=recordings]"); l.wait_for_selector("h2:has-text('Recordings')")
        check(l.locator(".cl:has-text('Lesson 1 recording')").count() == 0, "another teacher does not see it")
        n = page_for(); login(n, "t3@s.test", "Password123"); recs(n)
        check(n.locator("#fr").count() == 0 and n.locator("text=Add class recordings permission").count() == 1, "a teacher without Add class recordings sees no form and is told who to ask")
        br.close()
finally:
    srv.terminate(); shutil.rmtree(tmp, ignore_errors=True)
print("Problems:", errors or "none"); sys.exit(1 if errors else 0)
