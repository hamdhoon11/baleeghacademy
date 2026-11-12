"""Optional browser test: a student sees Submit work, writes an answer and attaches a file, and the teacher sees both.
Run: python tests/e2e_submit.py (needs playwright + chromium)"""
import os, sys, time, subprocess, tempfile, shutil, json, urllib.request
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import e2e_shim  # noqa: F401  (opens the phone menu when a script clicks a tab behind More)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
env = dict(os.environ, DATABASE_PATH=os.path.join(tmp, "s.db"), ADMIN_EMAIL="admin@s.test", ADMIN_PASSWORD="AdminPass123", PORT="5079", SECRET_KEY="s")
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
import sqlite3; _c = sqlite3.connect(env["DATABASE_PATH"]); _c.execute("UPDATE users SET must_change_password=0"); _c.commit(); _c.close()   # the forced first-sign-in password screen (Session 11) is not what these scripts test
srv = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(2)
BASE = "http://127.0.0.1:5079"; errors = []
def check(c, m):
    print("PASS" if c else "FAIL", m)
    if not c: errors.append(m)
def api(path, body=None, tok=None):
    r = urllib.request.Request(BASE + "/api" + path, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    return json.load(urllib.request.urlopen(r))
open(os.path.join(tmp, "work.pdf"), "wb").write(b"%PDF-1.4 student work")
try:
    adm = api("/auth/login", {"email": "admin@s.test", "password": "AdminPass123"})["token"]
    for title, kind in (("Homework 1", "assignment"), ("Quiz 1", "test")): api("/batches/1/assignments", {"title": title, "kind": kind, "max_points": 20}, adm)
    with sync_playwright() as p:
        br = p.chromium.launch()
        def page_for():
            pg = br.new_context(viewport={"width": 390, "height": 800}).new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            return pg
        def login(pg, e, w): e2e_shim.login(pg, BASE, e, w, db=env["DATABASE_PATH"])   # Session 22: forced change, course chooser, waits for the app
        s = page_for(); login(s, "student@baleegh.test", "ChangeMe-Stud1")
        s.click("nav [data-v=assignments]"); s.wait_for_selector("main h1:has-text('Assignments')"); s.wait_for_selector("[data-do=goA]")   # Home also has goA buttons (v0.8.35), so wait for the Assignments page itself
        check(s.locator("[data-do=goA]", has_text="Submit work").count() == 2, "both the assignment and the test show a Submit work button")
        s.locator("[data-do=goA]").first.click(); s.wait_for_selector("#atext")
        check(s.locator("#afile").count() == 1, "student sees the answer box and the file attachment")
        s.fill("#atext", "My written answer"); s.set_input_files("#afile", os.path.join(tmp, "work.pdf")); s.click("[data-do=submitA]")
        s.wait_for_selector("text=My written answer"); check(True, "student sees the submitted answer")
        check(s.locator("[data-do=dlSub]").count() == 1, "student sees the attached file")
        tok = api("/auth/login", {"email": "admin@s.test", "password": "AdminPass123"})["token"]
        subs = api("/assignments/2/submissions", tok=tok)["students"]
        check(subs[0]["text_answer"] == "My written answer" and subs[0]["has_file"], "teacher side receives the text and the file")
        s.click("[data-do=backA]"); s.wait_for_selector("[data-do=goA]"); s.locator("[data-do=goA]").nth(1).click(); s.wait_for_selector("#atext")
        check(True, "a test also accepts an answer")
        br.close()
finally:
    srv.terminate(); shutil.rmtree(tmp, ignore_errors=True)
print("Problems:", errors or "none"); sys.exit(1 if errors else 0)
