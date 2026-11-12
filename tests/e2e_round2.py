"""Optional browser test (390px phone, real app), v0.8.36 Round 2: the admissions review panel warns about a possible duplicate applicant,
and Fees > Overdue has "Remind next" that opens WhatsApp for the next person not reminded today and records it.
Run: python tests/e2e_round2.py (needs playwright + chromium)"""
import os, sys, time, subprocess, tempfile, shutil, json, sqlite3, urllib.request
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import e2e_shim  # noqa: F401
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(); DB = os.path.join(tmp, "r.db")
env = dict(os.environ, DATABASE_PATH=DB, ADMIN_EMAIL="admin@r.test", ADMIN_PASSWORD="AdminPass123", PORT="5091", SECRET_KEY="r")
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
def sql(q, a=()):
    c = sqlite3.connect(DB)
    try: r = c.execute(q, a).fetchall(); c.commit(); return r
    finally: c.close()
sql("UPDATE users SET must_change_password=0")
srv = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(2)
BASE = "http://127.0.0.1:5091"; errors = []
def check(c, m):
    print("PASS" if c else "FAIL", m)
    if not c: errors.append(m)
def api(path, body=None, tok=None, method=None):
    r = urllib.request.Request(BASE + "/api" + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    return json.load(urllib.request.urlopen(r))
try:
    adm = api("/auth/login", {"email": "admin@r.test", "password": "AdminPass123"})["token"]
    api("/courses/1", {"monthly_fee_mvr": 400}, adm, "PATCH")
    api("/invoices/generate", {"month": time.strftime("%Y-%m")}, adm)
    sql("UPDATE invoices SET due_date='2020-01-10' WHERE status='unpaid'")                 # make them overdue
    sql("UPDATE users SET phone='7771234' WHERE role='student' AND (phone IS NULL OR phone='')")
    for ref, email in (("BA-OLD1", "first@x.test"), ("BA-NEW1", "second@x.test")):
        sql("INSERT INTO applications(ref,full_name,date_of_birth,phone,email,course_id,status) VALUES(?,?,?,?,?,1,'pending')", (ref, "Same Person", "1999-09-09", "7775555", email))
    with sync_playwright() as p:
        br = p.chromium.launch()
        ctx = br.new_context(viewport={"width": 390, "height": 800}); a = ctx.new_page()
        opened = []
        ctx.route(lambda u: "127.0.0.1" not in u, lambda r: (opened.append(r.request.url), r.fulfill(body="ok")))   # no internet here: record where it goes
        a.on("pageerror", lambda e: errors.append(str(e)))
        e2e_shim.login(a, BASE, "admin@r.test", "AdminPass123", db=DB)
        a.click("nav [data-v=admissions]"); a.wait_for_selector("[data-do=apReview]")
        a.locator("tr:has-text('BA-NEW1') [data-do=apReview]").click(); a.wait_for_selector("[data-detail]")
        a.wait_for_selector("text=This may be someone already known")
        w = a.inner_text("[data-detail] .msg.err")
        check("BA-OLD1" in w and "same phone" in w and "same name and date of birth" in w, "review panel warns about the earlier application and says why")
        check(a.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "admissions page does not scroll sideways")

        a.click("nav [data-v=fees]"); a.click("[data-tabs=fees] [data-key=overdue]"); a.wait_for_selector("[data-do=fxNext]")
        before = a.inner_text("main")
        check("not reminded today" in before, "overdue tab says how many are not reminded today")
        with ctx.expect_page() as wa: a.click("[data-do=fxNext]")
        wa.value.wait_for_load_state(); wa.value.close(); url = " ".join(u for u in opened if "font" not in u)
        check("wa.me" in url or "whatsapp" in url, "Remind next opens WhatsApp: " + url[:60])
        a.wait_for_selector("text=already reminded today")
        check(sql("SELECT COUNT(*) FROM reminders")[0][0] == 1, "one reminder was recorded")
        br.close()
finally:
    srv.terminate(); shutil.rmtree(tmp, ignore_errors=True)
print("Problems:", errors or "none"); sys.exit(1 if errors else 0)
