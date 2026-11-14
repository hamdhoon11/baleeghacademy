"""Optional browser test, v0.8.49 (390 px): Add person needs a contact number; Settings shows Server errors; Calculate explains an empty month.
Run: python tests/e2e_v0849.py (needs playwright + chromium)"""
import os, sys, time, subprocess, tempfile, sqlite3
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import e2e_shim  # noqa: F401
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(); DB = os.path.join(tmp, "v.db")
env = {k: v for k, v in os.environ.items() if k != "PORTAL_PHONE_OPTIONAL"}
env.update(DATABASE_PATH=DB, ADMIN_EMAIL="admin@v.test", ADMIN_PASSWORD="AdminPass123", PORT="5099", SECRET_KEY="v" * 32, SEED_DEMO="0")
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
c = sqlite3.connect(DB); c.execute("UPDATE users SET must_change_password=0"); c.commit(); c.close()
srv = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(2)
BASE = "http://127.0.0.1:5099"; errors = []
OUT = os.environ.get("E2E_SHOTS") or tempfile.gettempdir()
def check(ok, m):
    print("PASS" if ok else "FAIL", m)
    if not ok: errors.append(m)
try:
    with sync_playwright() as p:
        br = p.chromium.launch(); a = br.new_context(viewport={"width": 390, "height": 900}).new_page(); a.on("pageerror", lambda e: errors.append(str(e)))
        e2e_shim.login(a, BASE, "admin@v.test", "AdminPass123", db=DB)
        a.goto(BASE + "/#people"); a.wait_for_selector("details[data-add=person]")
        a.click("details[data-add=person] summary")
        a.fill("#un", "New Student"); a.fill("#ue", "new@v.test"); a.click("#fu button.btn")
        a.wait_for_timeout(600)
        check(a.evaluate("!document.querySelector('#uph').checkValidity()"), "form stops without a contact number")
        check(sqlite3.connect(DB).execute("SELECT COUNT(*) FROM users WHERE email='new@v.test'").fetchone()[0] == 0, "nobody added without a number")
        a.fill("#uph", "7771234"); a.click("#fu button.btn"); a.wait_for_timeout(1200)
        check(sqlite3.connect(DB).execute("SELECT phone FROM users WHERE email='new@v.test'").fetchone() == ("7771234",), "added with the number")
        a.screenshot(path=os.path.join(OUT, "v0849-people.png"), full_page=True)
        a.goto(BASE + "/#settings"); a.wait_for_selector("#errp")
        check(a.locator("#errp", has_text="Server errors").count() == 1, "Settings shows the Server errors panel")
        a.goto(BASE + "/#finance"); a.wait_for_selector("#fe_month")
        a.click("[data-do=feCalc]"); a.wait_for_selector(".msg.warn", timeout=8000)
        check(a.locator(".msg.warn", has_text="month they were PAID").count() == 1, "Calculate explains an empty month")
        a.screenshot(path=os.path.join(OUT, "v0849-earnings.png"), full_page=True)
        br.close()
finally:
    srv.terminate()
print("\n" + ("ALL PASS" if not errors else f"{len(errors)} FAILED: " + "; ".join(errors)))
sys.exit(1 if errors else 0)
