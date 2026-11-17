"""Optional browser test, v0.8.60: Interest list at 390 px and 1280 px: add people, batch by batch, status, edit, PDF download,
New upcoming batch. Run: python tests/e2e_v0860.py"""
import os, sys, time, subprocess, tempfile, json, sqlite3, urllib.request
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import e2e_shim  # noqa: F401
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(); DB = os.path.join(tmp, "v.db")
env = dict(os.environ, DATABASE_PATH=DB, ADMIN_EMAIL="admin@v.test", ADMIN_PASSWORD="AdminPass123", PORT="5099", SECRET_KEY="v" * 32, SEED_DEMO="0")
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
def sql(q, a=()):
    c = sqlite3.connect(DB)
    try: r = c.execute(q, a).fetchall(); c.commit(); return r
    finally: c.close()
sql("UPDATE users SET must_change_password=0")
srv = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(2)
BASE = "http://127.0.0.1:5099"; errors = []
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
    b1 = api("/batches", {"course_id": co, "code": "A1-JAN", "capacity": 12, "days": "Sun,Tue", "start_time": "16:00", "end_time": "17:30", "start_date": "2027-01-10"}, adm)["id"]
    with sync_playwright() as p:
        br = p.chromium.launch()
        for w in (390, 1280):
            pg = br.new_context(viewport={"width": w, "height": 900}, accept_downloads=True).new_page(); pg.on("pageerror", lambda e: errors.append(str(e)))
            e2e_shim.login(pg, BASE, "admin@v.test", "AdminPass123", db=DB)
            pg.goto(BASE + "/#interest"); pg.wait_for_selector("#wl_fb")
            if w == 390:
                check(pg.locator("#wl_f").is_visible(), "Add form open while the list is empty")
                for n, i, ph in (("Aishath Ali", "a 123456", "7771234"), ("Mohamed Hassan", "A300100", "+960 777 0001")):
                    pg.select_option("#wl_b", str(b1)); pg.fill("#wl_n", n); pg.fill("#wl_id", i); pg.fill("#wl_p", ph)
                    pg.click("#wl_f button.btn"); pg.wait_for_timeout(900)
                    if not pg.locator("#wl_f").is_visible(): pg.click("details.panel summary")
                check(sql("SELECT full_name,id_card FROM interest_list ORDER BY id") == [("Aishath Ali", "A123456"), ("Mohamed Hassan", "A300100")], "Two people added; ID card tidied")
                pg.select_option("#wl_b", str(b1)); pg.fill("#wl_n", "Again"); pg.fill("#wl_id", "A123456"); pg.fill("#wl_p", "7771234"); pg.click("#wl_f button.btn"); pg.wait_for_timeout(700)
                check(pg.locator("main", has_text="already on the list for this batch").count() == 1, "Same ID card in the same batch is refused with a message")
                pg.goto(BASE + "/#interest"); pg.wait_for_selector("[data-wlst]")
                check(pg.locator(".panel h2", has_text="Arabic Level 1 · A1-JAN").count() == 1, "Shown under its batch")
                pg.locator("tr", has_text="Mohamed Hassan").locator("[data-wlst]").select_option("contacted"); pg.wait_for_timeout(900)
                check(sql("SELECT status FROM interest_list WHERE full_name='Mohamed Hassan'") == [("contacted",)], "Status changed in the list")
                pg.locator("tr", has_text="Aishath Ali").locator("[data-do=wlEdit]").click(); d = pg.locator("dialog[open]")
                d.locator("textarea").fill("Prefers weekend"); d.locator("button.btn:not(.alt)").last.click(); pg.wait_for_timeout(900)
                check(sql("SELECT notes FROM interest_list WHERE full_name='Aishath Ali'") == [("Prefers weekend",)], "Edit saves notes")
                with pg.expect_download() as dl: pg.click("[data-do=wlPdf]")
                f = dl.value; path = os.path.join(OUT, "v0860-" + f.suggested_filename); f.save_as(path)
                check(open(path, "rb").read(4) == b"%PDF", f"PDF downloaded ({f.suggested_filename})")
                pg.click("[data-do=wlNewBatch]"); d = pg.locator("dialog[open]")
                d.locator("select").first.select_option(str(co)); d.locator("input").nth(0).fill("A1-MAR"); d.locator("input").nth(1).fill("Sun,Tue")
                d.locator("button.btn:not(.alt)").last.click(); pg.wait_for_timeout(1000)
                check(sql("SELECT status FROM batches WHERE code='A1-MAR'") == [("open",)], "New upcoming batch made")
                check(pg.locator(".panel h2", has_text="A1-MAR").count() == 1 and pg.input_value("#wl_fb") != "", "…and chosen in the filter")
                pg.select_option("#wl_fb", ""); pg.wait_for_timeout(700)
            pg.screenshot(path=os.path.join(OUT, f"v0860-{w}.png"), full_page=True)
            check(pg.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), f"No sideways scroll at {w}")
            pg.context.close()
        br.close()
finally:
    srv.terminate()
print("ALL PASS" if not errors else f"{len(errors)} FAILED: {errors}")
sys.exit(1 if errors else 0)
