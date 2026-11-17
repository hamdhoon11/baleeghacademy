"""Optional browser test, v0.8.61: People → Delete removes a student who has an enrolment and an invoice, after a preview and the admin's
password. At 390 px and 1280 px. Run: python tests/e2e_v0861.py"""
import os, sys, time, subprocess, tempfile, json, sqlite3, urllib.request
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import e2e_shim  # noqa: F401
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(); DB = os.path.join(tmp, "v.db")
env = dict(os.environ, DATABASE_PATH=DB, ADMIN_EMAIL="admin@v.test", ADMIN_PASSWORD="AdminPass123", PORT="5098", SECRET_KEY="v" * 32, SEED_DEMO="0")
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
def sql(q, a=()):
    c = sqlite3.connect(DB)
    try: r = c.execute(q, a).fetchall(); c.commit(); return r
    finally: c.close()
sql("UPDATE users SET must_change_password=0")
srv = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(2)
BASE = "http://127.0.0.1:5098"; errors = []
OUT = os.environ.get("E2E_SHOTS") or tempfile.gettempdir()
def check(ok, m):
    print("PASS" if ok else "FAIL", m)
    if not ok: errors.append(m)
def api(path, body=None, tok=None):
    r = urllib.request.Request(BASE + "/api" + path, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    return json.load(urllib.request.urlopen(r))
try:
    adm = api("/auth/login", {"login": "admin@v.test", "password": "AdminPass123"})["token"]
    co = api("/courses", {"name": "Arabic Level 1", "monthly_fee_mvr": 500, "status": "open"}, adm)["id"]
    b1 = api("/batches", {"course_id": co, "code": "A1-JAN", "capacity": 12, "days": "Sun,Tue", "start_time": "16:00", "end_time": "17:30", "start_date": "2026-11-01"}, adm)["id"]
    with sync_playwright() as p:
        br = p.chromium.launch()
        for w in (390, 1280):
            name = f"Leaving Student {w}"
            sid = api("/users", {"email": f"s{w}@v.test", "password": "Password123", "full_name": name, "role": "student", "phone": "7771234", "guardian_phone": "7771234"}, adm)["id"]
            api("/enrollments", {"student_id": sid, "batch_id": b1}, adm)
            inv = sql("SELECT COUNT(*), COALESCE(SUM(amount_due_mvr),0) FROM invoices")[0]
            pg = br.new_context(viewport={"width": w, "height": 900}).new_page(); pg.on("pageerror", lambda e: errors.append(str(e)))
            e2e_shim.login(pg, BASE, "admin@v.test", "AdminPass123", db=DB)
            pg.goto(BASE + "/#people"); pg.wait_for_selector("[data-do=euEdit]")
            pg.locator(f"[data-do=euEdit][data-id='{sid}']").first.click(); pg.wait_for_selector("[data-do=euDel]")
            pg.click("[data-do=euDel]"); d = pg.locator("dialog[open]"); d.wait_for()
            txt = d.inner_text(); pg.screenshot(path=os.path.join(OUT, f"v0861-preview-{w}.png"))
            check("Enrolments: 1" in txt and "invoice(s)" in txt, f"Preview lists what goes and what stays ({w})")
            d.locator("button.btn:not(.alt)").last.click(); pg.wait_for_timeout(500)
            d = pg.locator("dialog[open]"); d.locator("input[type=password]").fill("wrong-one"); d.locator("button.btn:not(.alt)").last.click(); pg.wait_for_timeout(900)
            check(sql("SELECT COUNT(*) FROM users WHERE id=?", (sid,))[0][0] == 1, f"Wrong password removes nothing ({w})")
            if pg.locator("dialog[open]").count(): pg.keyboard.press("Escape")
            pg.click("[data-do=euDel]"); d = pg.locator("dialog[open]"); d.wait_for(); d.locator("button.btn:not(.alt)").last.click(); pg.wait_for_timeout(500)
            d = pg.locator("dialog[open]"); d.locator("input[type=password]").fill("AdminPass123"); d.locator("button.btn:not(.alt)").last.click(); pg.wait_for_timeout(1200)
            check(sql("SELECT COUNT(*) FROM users WHERE id=?", (sid,))[0][0] == 0, f"Removed with the right password ({w})")
            check(sql("SELECT COUNT(*), COALESCE(SUM(amount_due_mvr),0) FROM invoices")[0] == inv, f"Invoice totals unchanged ({w})")
            check(sql("SELECT COUNT(*) FROM invoices WHERE customer_name=?", (name,))[0][0] == 1, f"Invoice kept under the name ({w})")
            check(pg.locator("main", has_text=name).count() == 0 or pg.locator("[data-do=euEdit]", has_text=name).count() == 0, f"Gone from People ({w})")
            pg.screenshot(path=os.path.join(OUT, f"v0861-{w}.png"), full_page=True)
        br.close()
finally:
    srv.terminate()
print("FAILURES:", errors) if errors else print("ALL PASS")
sys.exit(1 if errors else 0)
