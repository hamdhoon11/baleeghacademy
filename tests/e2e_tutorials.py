"""Optional browser test (phone-sized screen, real app): a teacher posts a tutorial, a student downloads it and sends an answer,
the teacher and admin read the answer, and the screens respect the two permissions.
Run: python tests/e2e_tutorials.py (needs playwright + chromium)"""
import os, re, sys, time, subprocess, tempfile, shutil, json, urllib.request
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
env = dict(os.environ, DATABASE_PATH=os.path.join(tmp, "s.db"), ADMIN_EMAIL="admin@s.test", ADMIN_PASSWORD="AdminPass123", PORT="5081", SECRET_KEY="s")
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
srv = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(2)
BASE = "http://127.0.0.1:5081"; errors = []
def check(c, m):
    print("PASS" if c else "FAIL", m)
    if not c: errors.append(m)
def api(path, body=None, tok=None, method=None):
    r = urllib.request.Request(BASE + "/api" + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    return json.load(urllib.request.urlopen(r))
PDF = b"%PDF-1.4 test"
open(os.path.join(tmp, "lesson.pdf"), "wb").write(PDF); open(os.path.join(tmp, "answer.pdf"), "wb").write(PDF + b" answer")
try:
    adm = api("/auth/login", {"email": "admin@s.test", "password": "AdminPass123"})["token"]
    other = api("/users", {"email": "t2@s.test", "password": "Password123", "full_name": "Other Teacher", "role": "teacher"}, adm)["id"]
    lim = api("/users", {"email": "lim@s.test", "password": "Password123", "full_name": "Limited Student", "role": "student"}, adm)["id"]
    api(f"/users/{lim}", {"permissions": ["tutorials"]}, adm, "PATCH")   # may read, but "Submit tutorial work" is not ticked
    with sync_playwright() as p:
        br = p.chromium.launch()
        def page_for():
            pg = br.new_context(viewport={"width": 390, "height": 800}, accept_downloads=True).new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            return pg
        def login(pg, e, w):
            pg.goto(BASE + "/"); pg.fill("#le", e); pg.fill("#lp", w); pg.click("#fl button"); pg.wait_for_selector("nav")
            pg.click("nav [data-v=tutorials]"); pg.wait_for_selector("#tff")

        # teacher posts
        t = page_for(); login(t, "teacher@baleegh.test", "ChangeMe-Teach1")
        check(t.locator("#tfp").count() == 1, "teacher sees the Share a tutorial form")
        t.fill("#tp_t", "Verb tables"); t.fill("#tp_x", "Learn page 4"); t.set_input_files("#tp_f", os.path.join(tmp, "lesson.pdf")); t.click("#tfp button")
        t.wait_for_selector("text=Verb tables"); check(True, "teacher's tutorial appears")
        check(t.locator("[data-do=openT]").count() == 1 and "(0)" in t.locator("[data-do=openT]").inner_text(), "teacher sees an Answers (0) button on their own tutorial")

        # student reads, downloads, answers
        s = page_for(); login(s, "student@baleegh.test", "ChangeMe-Stud1")
        check(s.locator("#tfp").count() == 0, "student does not see the post form")
        s.wait_for_selector("text=Verb tables")
        check(s.locator(".tag", has_text="Not answered yet").count() == 1, "student sees Not answered yet")
        with s.expect_download() as dl: s.click("[data-do=dlTut]")
        check(open(dl.value.path(), "rb").read() == PDF, "student downloads the tutorial file")
        s.click("[data-do=openT]"); s.wait_for_selector("#tans_x"); check(s.locator("#tans_f").count() == 1, "answer box has text and file")
        s.click("[data-do=sendTAns]"); s.wait_for_selector(".msg, .flash, [role=alert], #fl, body"); time.sleep(0.5)
        check(s.locator(".tag", has_text=re.compile(r"^Answered$")).count() == 0 and s.locator("[data-do=dlTAns]").count() == 0, "an empty answer is refused and nothing is saved")
        s.fill("#tans_x", "My answer text"); s.set_input_files("#tans_f", os.path.join(tmp, "answer.pdf")); s.click("[data-do=sendTAns]")
        s.wait_for_selector("[data-do=dlTAns]"); check(s.locator(".tag", has_text=re.compile(r"^Answered$")).count() == 1, "student sees Answered after sending")
        check(s.input_value("#tans_x") == "My answer text" and s.locator("[data-do=dlTAns]").count() == 1, "the box shows the saved text and file")
        s.fill("#tans_x", "Changed text"); s.click("[data-do=sendTAns]"); s.wait_for_selector("[data-do=dlTAns]")
        check(s.input_value("#tans_x") == "Changed text" and s.locator("[data-do=dlTAns]").count() == 1, "changing only the text keeps the earlier file")

        # teacher and admin read the answer
        t.click("nav [data-v=home]"); t.click("nav [data-v=tutorials]"); t.wait_for_selector("[data-do=openT]")
        check("(1)" in t.locator("[data-do=openT]").inner_text(), "teacher now sees Answers (1)")
        t.click("[data-do=openT]"); t.wait_for_selector("text=Changed text"); check(t.locator("[data-do=dlTAns]").count() == 1, "teacher sees the student's text and file")
        with t.expect_download() as dl2: t.click("[data-do=dlTAns]")
        check(open(dl2.value.path(), "rb").read() == PDF + b" answer", "teacher downloads the student's file")
        a = page_for(); login(a, "admin@s.test", "AdminPass123"); a.wait_for_selector("[data-do=openT]"); a.click("[data-do=openT]")
        a.wait_for_selector("text=Demo Student"); check(True, "admin sees the answer with the student's name")

        # other people
        o = page_for(); login(o, "t2@s.test", "Password123"); o.wait_for_selector("text=Verb tables")
        check(o.locator("[data-do=openT]").count() == 0, "another teacher sees no answers button")
        l = page_for(); login(l, "lim@s.test", "Password123"); l.wait_for_selector("text=Verb tables")
        check(l.locator("[data-do=openT]").count() == 0 and l.locator(".tag", has_text="Not answered yet").count() == 0, "a student without Submit tutorial work sees no answer box")
        check(s.locator("[data-do=delTut]").count() == 0, "student has no delete button")
        t.click("nav [data-v=home]"); t.click("nav [data-v=tutorials]"); t.wait_for_selector("[data-do=delTut]")
        t.once("dialog", lambda d: d.accept()); t.click("[data-do=delTut]"); t.wait_for_selector("text=Verb tables", state="detached"); check(True, "teacher deletes their tutorial")
        br.close()
finally:
    srv.terminate(); shutil.rmtree(tmp, ignore_errors=True)
print("Problems:", errors or "none"); sys.exit(1 if errors else 0)
