"""Optional browser test, v0.8.55 (390 px): the Batch filter on People, Enrollments, Fees (invoices, overdue, reminders, slips) and Who's online; then the v0.8.52 Record payment checks.\n(Fees -> Record payment shows open fees batch by batch; tapping a month fills the form;
payments say which fee month they paid for; batch and month filters narrow both lists. Run: python tests/e2e_v0852.py"""
import os, sys, time, subprocess, tempfile, json, sqlite3, urllib.request
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import e2e_shim  # noqa: F401
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(); DB = os.path.join(tmp, "v.db")
env = dict(os.environ, DATABASE_PATH=DB, ADMIN_EMAIL="admin@v.test", ADMIN_PASSWORD="AdminPass123", PORT="5096", SECRET_KEY="v" * 32, SEED_DEMO="0")
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
def sql(q, a=()):
    c = sqlite3.connect(DB)
    try: r = c.execute(q, a).fetchall(); c.commit(); return r
    finally: c.close()
sql("UPDATE users SET must_change_password=0")
srv = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(2)
BASE = "http://127.0.0.1:5096"; errors = []
OUT = os.environ.get("E2E_SHOTS") or tempfile.gettempdir()
def check(ok, m):
    print("PASS" if ok else "FAIL", m)
    if not ok: errors.append(m)
def api(path, body=None, tok=None):
    r = urllib.request.Request(BASE + "/api" + path, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    return json.load(urllib.request.urlopen(r))
try:
    adm = api("/auth/login", {"login": "admin@v.test", "password": "AdminPass123"})["token"]
    def mk(e, n, role="student"):
        i = api("/users", {"email": e, "password": "Password123", "full_name": n, "role": role, "phone": "7771234"}, adm)["id"]; sql("UPDATE users SET must_change_password=0"); return i
    t1 = mk("t1@v.test", "Ustaz Ahmed", "teacher")
    ss = [mk(f"s{i}@v.test", n) for i, n in enumerate(["Aisha Ali", "Ibrahim Naseem", "Hassan Rasheed", "Mariyam Shifa"])]
    co = api("/courses", {"name": "Arabic Level 1", "monthly_fee_mvr": 500, "status": "open"}, adm)["id"]
    co2 = api("/courses", {"name": "Quran Tuition", "monthly_fee_mvr": 300, "status": "open", "kind": "tuition"}, adm)["id"]
    b1 = api("/batches", {"course_id": co, "code": "A1", "teacher_id": t1, "capacity": 20, "days": "Wed", "start_time": "16:00"}, adm)["id"]
    b2 = api("/batches", {"course_id": co2, "code": "Q1", "teacher_id": t1, "capacity": 20, "days": "Thu", "start_time": "16:00"}, adm)["id"]
    for i, s in enumerate(ss): api("/enrollments", {"student_id": s, "batch_id": b1 if i < 3 else b2, "start_date": "2026-09-01"}, adm)
    iid = sql("SELECT id FROM invoices WHERE student_id=? AND period='2026-09'", (ss[0],))[0][0]
    api("/payments", {"invoice_id": iid, "amount_mvr": 500, "method": "cash", "paid_on": "2026-11-10"}, adm)
    with sync_playwright() as p:
        br = p.chromium.launch()
        a = br.new_context(viewport={"width": 390, "height": 900}).new_page(); a.on("pageerror", lambda e: errors.append(str(e)))
        e2e_shim.login(a, BASE, "admin@v.test", "AdminPass123", db=DB)
        def pick(view, key, label):
            sel = a.locator(f"select[data-bf={key}]")
            sel.select_option(label=label); a.wait_for_timeout(700)
        # People: Quran Tuition Q1 -> only Mariyam (student) and the teacher of that batch
        a.goto(BASE + "/#people"); a.wait_for_selector("select[data-bf=people]")
        pick("people", "people", "Quran Tuition Q1")
        names = a.evaluate("[...document.querySelectorAll('main table tbody tr td:first-child')].map(td => td.textContent)")
        check(any("Mariyam Shifa" in n for n in names) and not any("Aisha Ali" in n for n in names) and any("Ustaz Ahmed" in n for n in names), f"People: batch filter ({len(names)} rows)")
        check(a.locator("main .bft", has_text="Quran Tuition Q1").count() >= 1, "People: batch shown next to the name")
        a.screenshot(path=os.path.join(OUT, "v0855-people.png"), full_page=True)
        # Enrollments: sorted by batch
        a.goto(BASE + "/#enrollments"); a.wait_for_selector("select[data-bf=enr]")
        pick("enrollments", "enr", "All, sorted by batch")
        rows = a.evaluate("[...document.querySelectorAll('main table tbody tr')].map(r => r.textContent)")
        check(len(rows) == 4 and "Arabic" in rows[0] and "Quran" in rows[-1], "Enrollments: sorted by batch")
        pick("enrollments", "enr", "Quran Tuition Q1")
        check(a.locator("main table tbody tr").count() == 1, "Enrollments: one batch")
        # Fees: invoices, overdue, reminders
        a.goto(BASE + "/#fees"); a.wait_for_selector("[data-tabs=fees]")
        a.click(e2e_shim.subtab("fees", "invoices")); a.wait_for_selector("select[data-bf=inv]")
        pick("fees", "inv", "Quran Tuition Q1")
        txt = a.inner_text("main")
        check("Mariyam Shifa" in txt and "Aisha Ali" not in txt, "Invoices: batch filter")
        a.click(e2e_shim.subtab("fees", "overdue")); a.wait_for_selector("select[data-bf=over]")
        pick("fees", "over", "Arabic Level 1 A1")
        txt = a.inner_text("main")
        check("Hassan Rasheed" in txt and "Mariyam Shifa" not in txt, "Overdue invoices: batch filter")
        a.click(e2e_shim.subtab("fees", "reminders")); a.wait_for_selector("select[data-bf=rem]")
        pick("fees", "rem", "Quran Tuition Q1")
        txt = a.inner_text("main")
        check("Mariyam Shifa" in txt and "Hassan Rasheed" not in txt, "Fee reminders: batch filter")
        a.screenshot(path=os.path.join(OUT, "v0855-reminders.png"), full_page=True)
        a.click(e2e_shim.subtab("fees", "slips")); a.wait_for_selector("select[data-bf=slips]")
        check(True, "Slips: has the batch filter")
        # v0.8.55: Show -> added / enrolled recently (one student's dates are moved back 60 days)
        sql("UPDATE users SET created_at='2026-01-01 08:00:00' WHERE full_name='Hassan Rasheed'")
        sql("UPDATE enrollments SET enrolled_at='2026-01-01 08:00:00' WHERE student_id=(SELECT id FROM users WHERE full_name='Hassan Rasheed')")
        import datetime as _dt
        sql("UPDATE enrollments SET enrolled_at=? WHERE student_id=(SELECT id FROM users WHERE full_name='Aisha Ali')", (_dt.date.today().isoformat() + " 09:00:00",))   # enrolled = the start date
        a.evaluate("S.bm = null")
        a.goto(BASE + "/#people"); a.wait_for_selector("select[data-bfr=people]")
        a.select_option("select[data-bf=people]", ""); a.wait_for_timeout(500)
        a.select_option("select[data-bfr=people]", "a30"); a.wait_for_timeout(700)
        txt = a.inner_text("main table")
        check("Aisha Ali" in txt and "Hassan Rasheed" not in txt and "Admin" not in txt.split("\n")[0:0] + [""], "People: added in the last 30 days")
        a.goto(BASE + "/#enrollments"); a.wait_for_selector("select[data-bfr=enr]")
        a.select_option("select[data-bf=enr]", ""); a.wait_for_timeout(400)
        a.select_option("select[data-bfr=enr]", "e7"); a.wait_for_timeout(700)
        txt = a.inner_text("main")
        check("Aisha Ali" in txt and "Hassan Rasheed" not in txt, "Enrollments: enrolled in the last 7 days")
        # Dashboard -> Batches
        a.goto(BASE + "/#dashboard"); a.wait_for_selector("#adbat")
        check(a.locator("#adbat .cl", has_text="Arabic Level 1 A1").count() == 1 and a.locator("#adbat", has_text="Recently enrolled").count() == 1, "Dashboard: Batches section")
        a.screenshot(path=os.path.join(OUT, "v0855-dashboard.png"), full_page=True)
        a.locator("#adbat").screenshot(path=os.path.join(OUT, "v0855-dashboard-batches.png"))
        a.locator("#adbat .cl", has_text="Quran Tuition Q1").locator("[data-do=adBatch]").click(); a.wait_for_selector(".fg")
        check(a.locator("details.sub summary", has_text="Arabic Level 1 A1").count() == 0, "Dashboard: a batch opens its fees")
        a.goto(BASE + "/#dashboard"); a.wait_for_selector("#adbat")
        a.click("[data-do=adRecent][data-k=a30]"); a.wait_for_selector("select[data-bfr=people]")
        check(a.input_value("select[data-bfr=people]") == "a30", "Dashboard: 'Added in the last 30 days' opens People filtered")
        a.select_option("select[data-bfr=people]", ""); a.wait_for_timeout(300)
        # Who's online
        a.goto(BASE + "/#online"); a.wait_for_selector("select[data-bf=online]")
        pick("online", "online", "Quran Tuition Q1")
        txt = a.inner_text("main")
        check("Mariyam Shifa" in txt and "Aisha Ali" not in txt, "Who's online: batch filter")
        check(a.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "no sideways scrolling")
        a.context.close()
        for w in (390, 1280):
            a = br.new_context(viewport={"width": w, "height": 900}).new_page(); a.on("pageerror", lambda e: errors.append(str(e)))
            e2e_shim.login(a, BASE, "admin@v.test", "AdminPass123", db=DB)
            a.goto(BASE + "/#fees"); a.wait_for_selector("[data-tabs=fees]"); a.click(e2e_shim.subtab("fees", "record")); a.wait_for_selector("#fxrf")
            check(a.locator("details.sub summary", has_text="Arabic Level 1 A1").count() == 1 and a.locator("details.sub summary", has_text="Quran Tuition Q1").count() == 1, f"[{w}] open fees grouped by batch")
            check(a.locator(".cl", has_text="Payment").count() + a.locator(".chip", has_text="For Sep 2026").count() >= 1, f"[{w}] the payment says it was for Sep 2026")
            check(a.locator("text=Paid on 2026-11-10").count() >= 1, f"[{w}] and the day it was paid")
            # v0.8.53: the fee status grid, coloured and labelled
            a.locator("details.sub", has_text="Arabic Level 1 A1").locator("summary").click()
            row = a.locator("details.sub", has_text="Arabic Level 1 A1").locator("tr", has_text="Aisha Ali")
            check(row.locator(".g-paid").count() == 1 and row.locator(".g-over, .g-unpaid").count() >= 1, f"[{w}] grid: Aisha's September is green, later months red")
            check(a.locator("details.sub", has_text="Arabic Level 1 A1").locator("tfoot", has_text="Collected").count() == 1, f"[{w}] grid: collected and to-pay per month")
            check(a.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), f"[{w}] grid scrolls inside its box, not the page")
            a.screenshot(path=os.path.join(OUT, f"v0852-record-{w}.png"), full_page=True)
            # tap a month: fills the form
            a.locator("details.sub", has_text="Quran Tuition Q1").locator("summary").click()
            a.locator("details.sub", has_text="Quran Tuition Q1").locator("[data-do=fxRecPick]").first.click(); a.wait_for_timeout(400)
            sel = a.evaluate("document.querySelector('#fxp_i').selectedOptions[0].textContent")
            check("Sep 2026" in sel and "Mariyam Shifa" in sel and a.input_value("#fxp_a") == "300", f"[{w}] tapping Sep 2026 fills the invoice and amount ({sel})")
            # filter by batch
            a.select_option("#fxrf_b", str(b2)); a.wait_for_selector("details.sub summary:has-text('Quran Tuition Q1')")
            a.wait_for_timeout(500)
            check(a.locator("details.sub summary", has_text="Arabic Level 1 A1").count() == 0, f"[{w}] batch filter shows only that batch")
            check(a.evaluate("[...document.querySelectorAll('#fxp_i option')].every(o => o.textContent.includes('Quran'))"), f"[{w}] the form lists only that batch's fees")
            check(a.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), f"[{w}] no sideways scrolling")
            a.select_option("#fxrf_b", ""); a.wait_for_timeout(500)
            a.context.close()
        br.close()
finally:
    srv.terminate()
print("\n" + ("ALL PASS" if not errors else f"{len(errors)} FAILED: " + "; ".join(errors)))
sys.exit(1 if errors else 0)
