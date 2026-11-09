"""Browser check of the app shell: every tab of every role on a phone and a computer.
Looks for sideways scrolling, script errors, a reachable Sign out, working Back button and the phone menu."""
import os, sys, subprocess, time, sqlite3, tempfile
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import e2e_shim  # noqa: F401
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(); PORT = "5083"; B = f"http://127.0.0.1:{PORT}"
env = dict(os.environ, DATABASE_PATH=tmp + "/n.db", ADMIN_EMAIL="admin@e2e.test", ADMIN_PASSWORD="AdminPass123", PORT=PORT, SECRET_KEY="x", NO_PROXY="127.0.0.1,localhost")
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
c = sqlite3.connect(env["DATABASE_PATH"]); c.execute("UPDATE users SET must_change_password=0"); c.commit(); c.close()
srv = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(2.5)
WHO = {"admin": ("admin@e2e.test", "AdminPass123"), "teacher": ("teacher@baleegh.test", "ChangeMe-Teach1"), "student": ("student@baleegh.test", "ChangeMe-Stud1")}
fails = []
def ok(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (" " + str(extra) if not cond and extra else "")); 
    if not cond: fails.append(name)
try:
  with sync_playwright() as p:
    b = p.chromium.launch()
    for vp, (w, h) in {"phone": (390, 800), "desktop": (1366, 768)}.items():
      for role, (e, pw) in WHO.items():
        pg = b.new_page(viewport={"width": w, "height": h}); errs = []
        pg.on("pageerror", lambda x: errs.append(str(x)))
        pg.goto(B + "/"); pg.fill("#le", e); pg.fill("#lp", pw); pg.click("#fl button"); pg.wait_for_timeout(1000)
        if pg.is_visible("[data-sb]"): pg.click("[data-sb]"); pg.wait_for_timeout(800)
        tabs = pg.eval_on_selector_all("nav [data-v]", "els=>els.map(e=>e.dataset.v)")
        ok(f"{vp}/{role}: has tabs", len(tabs) >= 4, tabs)
        for v in tabs:
            pg.click(f"nav [data-v={v}]"); pg.wait_for_timeout(700)
            over = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            ok(f"{vp}/{role}/{v}: no sideways page scroll", over <= 1, over)
            ok(f"{vp}/{role}/{v}: URL follows tab", pg.evaluate("location.hash") == "#" + v)
            ok(f"{vp}/{role}/{v}: tab marked current", pg.eval_on_selector(f"nav [data-v={v}]", "e=>e.getAttribute('aria-current')") == "page")
        ok(f"{vp}/{role}: no script errors", not errs, errs[:2])
        if vp == "desktop":
            ok(f"{role}: sign out visible without scrolling", pg.evaluate("(()=>{const r=document.querySelector('#so').getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight})()"))
        else:
            ok(f"{role}: bottom bar clear of content edge", pg.evaluate("document.querySelector('nav').getBoundingClientRect().bottom<=innerHeight+1"))
            pg.click("#moreBtn"); pg.wait_for_timeout(300)
            ok(f"{role}: More opens menu with Sign out", pg.is_visible("#so"))
            pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
            ok(f"{role}: Escape closes menu", not pg.is_visible("#so"))
        if len(tabs) > 2 and vp == "desktop":
            pg.click(f"nav [data-v={tabs[1]}]"); pg.wait_for_timeout(500); pg.click(f"nav [data-v={tabs[2]}]"); pg.wait_for_timeout(500)
            pg.go_back(); pg.wait_for_timeout(700)
            ok(f"{role}: Back returns to previous tab", pg.evaluate("location.hash") == "#" + tabs[1] and pg.eval_on_selector(f"nav [data-v={tabs[1]}]", "e=>e.getAttribute('aria-current')") == "page")
            pg.reload(); pg.wait_for_timeout(1000)
            if pg.is_visible("[data-sb]"): pg.click("[data-sb]"); pg.wait_for_timeout(700)
            ok(f"{role}: refresh stays on the tab", pg.evaluate("location.hash") == "#" + tabs[1])
        pg.close()
    b.close()
finally:
    srv.terminate()
print("\n%d failure(s)" % len(fails)); sys.exit(1 if fails else 0)
