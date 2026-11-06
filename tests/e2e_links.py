"""Optional browser test (phone-sized screen, real app): a teacher sets the class link and a one-off link, the student's Join button uses them,
and a teacher without the Class links permission sees the link read-only.
Run: python tests/e2e_links.py (needs playwright + chromium)"""
import os, sys, time, subprocess, tempfile, shutil, json, urllib.request, datetime as dt
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
env = dict(os.environ, DATABASE_PATH=os.path.join(tmp, "s.db"), ADMIN_EMAIL="admin@s.test", ADMIN_PASSWORD="AdminPass123", PORT="5082", SECRET_KEY="s")
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
srv = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(2)
BASE = "http://127.0.0.1:5082"; errors = []
def check(c, m):
    print("PASS" if c else "FAIL", m)
    if not c: errors.append(m)
def api(path, body=None, tok=None, method=None):
    r = urllib.request.Request(BASE + "/api" + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    return json.load(urllib.request.urlopen(r))
LINK_A, ONE_OFF = "https://meet.google.com/batch-link-aaa", "https://meet.google.com/one-off-bbb"
mv = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(hours=5)   # Maldives time; the extra class starts 5 minutes ago so it is live now
start = max(mv - dt.timedelta(minutes=5), mv.replace(hour=0, minute=0))
try:
    adm = api("/auth/login", {"email": "admin@s.test", "password": "AdminPass123"})["token"]
    t2 = api("/users", {"email": "t2@s.test", "password": "Password123", "full_name": "Limited Teacher", "role": "teacher"}, adm)["id"]
    api("/batches", {"course_id": 1, "code": "L1", "teacher_id": t2, "capacity": 5, "meet_link": "https://meet.google.com/limited-ccc"}, adm)
    api(f"/users/{t2}", {"permissions": ["classroom"]}, adm, "PATCH")      # Class links not ticked
    with sync_playwright() as p:
        br = p.chromium.launch()
        def page_for():
            pg = br.new_context(viewport={"width": 390, "height": 800}).new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            return pg
        def login(pg, e, w): pg.goto(BASE + "/"); pg.fill("#le", e); pg.fill("#lp", w); pg.click("#fl button"); pg.wait_for_selector("nav")
        def schedule(pg): pg.click("nav [data-v=classroom]"); pg.wait_for_selector("[data-do=ctab][data-v=schedule]"); pg.click("[data-do=ctab][data-v=schedule]"); pg.wait_for_selector("#fx")

        t = page_for(); login(t, "teacher@baleegh.test", "ChangeMe-Teach1"); schedule(t)
        check(t.locator("#ml").count() == 1 and t.locator("#xm").count() == 1, "teacher sees the class link box and the one-off link field")
        t.fill("#ml", LINK_A); t.click("[data-do=saveLink]"); t.wait_for_selector(f"a[href='{LINK_A}']"); check(True, "teacher saves the batch link and it is shown")
        t.fill("#xd", start.strftime("%Y-%m-%d")); t.fill("#xt", start.strftime("%H:%M")); t.fill("#xp", "Extra revision"); t.fill("#xm", ONE_OFF); t.click("#fx button")
        t.wait_for_selector(".tag:has-text('Own link')"); check(True, "the extra class shows an Own link tag")

        s = page_for(); login(s, "student@baleegh.test", "ChangeMe-Stud1"); s.wait_for_selector(".next")
        check(s.locator(f"a.btn.big[href='{ONE_OFF}']").count() == 1, "student's Join button uses the one-off link")

        t.click("[data-do=rmOneLink]"); t.wait_for_selector(".tag:has-text('Own link')", state="detached"); check(True, "teacher removes the one-off link")
        s.click("nav [data-v=progress]"); s.click("nav [data-v=home]"); s.wait_for_selector(".next")
        check(s.locator(f"a.btn.big[href='{LINK_A}']").count() == 1, "student's Join button falls back to the batch link")

        l = page_for(); login(l, "t2@s.test", "Password123"); schedule(l)
        check(l.locator("#ml").count() == 0 and l.locator("#xm").count() == 0 and l.locator("[data-do=saveLink]").count() == 0, "a teacher without Class links cannot edit it")
        check(l.locator("a[href='https://meet.google.com/limited-ccc']").count() == 1, "but still sees the link, read-only")
        check(l.locator("text=Class links permission").count() >= 1, "and is told who can change it")
        t.click("nav [data-v=home]"); t.click("nav [data-v=classroom]"); t.wait_for_selector("select[data-ch=batch]")
        check([o for o in t.locator("select[data-ch=batch] option").all_inner_texts() if "L1" in o] == [], "a teacher does not see another teacher's batch")
        br.close()
finally:
    srv.terminate(); shutil.rmtree(tmp, ignore_errors=True)
print("Problems:", errors or "none"); sys.exit(1 if errors else 0)
