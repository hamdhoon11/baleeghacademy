"""Optional browser test, v0.8.47: Who's online. A student signs in in a second browser; the full admin sees them online, signs them out,
pauses, restores and suspends the account; the student sees the right message each time. A limited admin sees the list without buttons (v0.8.48).
Phone (390 px) and computer widths. Run: python tests/e2e_presence.py (needs playwright + chromium)"""
import os, sys, time, subprocess, tempfile, json, sqlite3, urllib.request
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import e2e_shim  # noqa: F401
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(); DB = os.path.join(tmp, "p.db")
env = dict(os.environ, DATABASE_PATH=DB, ADMIN_EMAIL="admin@p.test", ADMIN_PASSWORD="AdminPass123", PORT="5097", SECRET_KEY="p" * 32)
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
def sql(q, a=()):
    c = sqlite3.connect(DB)
    try: r = c.execute(q, a).fetchall(); c.commit(); return r
    finally: c.close()
sql("UPDATE users SET must_change_password=0")
srv = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(2)
BASE = "http://127.0.0.1:5097"; errors = []
def check(c, m):
    print("PASS" if c else "FAIL", m)
    if not c: errors.append(m)
def api(path, body=None, tok=None, method=None):
    r = urllib.request.Request(BASE + "/api" + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    return json.load(urllib.request.urlopen(r))
SHOT = lambda a, n: a.screenshot(path=os.path.join(tempfile.gettempdir(), f"baleegh-e2e-presence-{n}.png"), full_page=True)
OK = "dialog.dlg[open] button[value=ok]"
try:
    adm = api("/auth/login", {"email": "admin@p.test", "password": "AdminPass123"})["token"]
    sid = api("/users", {"email": "sara@p.test", "password": "Password123", "full_name": "Sara Student", "role": "student"}, adm)["id"]
    ali = api("/users", {"email": "ali@p.test", "password": "Password123", "full_name": "Ali Student", "role": "student"}, adm)["id"]
    lid = api("/users", {"email": "lim@p.test", "password": "Password123", "full_name": "Limited Admin", "role": "admin"}, adm)["id"]
    api(f"/users/{lid}", {"permissions": ["people"]}, adm, "PATCH")
    sql("UPDATE users SET must_change_password=0")
    row = lambda pg: pg.locator("tr:has-text('Sara Student')")
    with sync_playwright() as p:
        br = p.chromium.launch()
        for width in (1280, 390):
            sql("UPDATE users SET suspended_at=NULL, suspend_reason=NULL, paused_until=NULL WHERE id=?", (sid,))
            a = br.new_context(viewport={"width": width, "height": 900}).new_page(); a.on("pageerror", lambda e: errors.append(str(e)))
            s = br.new_context(viewport={"width": 390, "height": 800}, user_agent="Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36").new_page(); s.on("pageerror", lambda e: errors.append(str(e)))
            e2e_shim.login(s, BASE, "sara@p.test", "Password123", db=DB)
            e2e_shim.login(a, BASE, "admin@p.test", "AdminPass123", db=DB)
            a.goto(BASE + "/#online"); a.wait_for_selector("main h1:has-text(\"Who's online\")")
            check(row(a).locator(".tag", has_text="Online").count() == 1, f"[{width}] student shows Online")
            check(row(a).locator("text=Phone").count() == 1, f"[{width}] device shown (Phone)")
            check(a.locator("tr:has-text('You')").count() >= 1, f"[{width}] own row has no buttons")
            SHOT(a, f"list-{width}")
            # ---- Sign out everywhere ----
            row(a).locator("button", has_text="Sign out").click(); a.click(OK); a.wait_for_selector("text=Signed out")
            s.reload(); s.wait_for_selector("#le", timeout=15000)
            check(s.is_visible("#le"), f"[{width}] student is back at the sign-in screen after Sign out")
            a.click("[data-do=onRefresh]"); a.wait_for_timeout(500)
            check(row(a).locator(".tag", has_text="Offline").count() == 1, f"[{width}] student now Offline")
            # ---- Pause for 1 hour ----
            e2e_shim.login(s, BASE, "sara@p.test", "Password123", db=DB)
            row(a).locator("button", has_text="Pause").click()
            a.wait_for_selector("dialog.dlg[open] select"); a.locator("dialog.dlg[open] select").select_option("1")
            a.locator("dialog.dlg[open] input[maxlength='300']").fill("Exam week"); SHOT(a, f"pause-{width}"); a.click(OK)
            a.wait_for_selector("text=Paused until")
            check(row(a).locator(".tag", has_text="Paused").count() == 1 and row(a).locator("text=Exam week").count() == 1, f"[{width}] Paused with reason shown")
            s.reload(); s.wait_for_selector("#le", timeout=15000)
            s.fill("#le", "sara@p.test"); s.fill("#lp", "Password123"); s.click("#fl button"); s.wait_for_selector("text=paused until", timeout=10000)
            check(s.locator("text=paused until").count() >= 1, f"[{width}] student is told the account is paused and until when")
            SHOT(s, f"student-paused-{width}")
            # ---- Restore ----
            row(a).locator("button", has_text="Restore").click(); a.click(OK); a.wait_for_selector("text=Restored")
            s.click("#fl button"); s.wait_for_selector("nav", timeout=15000)
            check(s.is_visible("nav"), f"[{width}] student can sign in after Restore")
            # ---- Suspend (reason required) ----
            row(a).locator("button", has_text="Suspend").click(); a.wait_for_selector("dialog.dlg[open] textarea")
            a.click(OK); check(a.is_visible("dialog.dlg[open]"), f"[{width}] Suspend refuses an empty reason")
            a.locator("dialog.dlg[open] textarea").fill("Rude in class chat"); a.click(OK); a.wait_for_selector("text=Suspended")
            s.reload(); s.wait_for_selector("#le", timeout=15000)
            s.fill("#le", "sara@p.test"); s.fill("#lp", "Password123"); s.click("#fl button"); s.wait_for_selector("text=suspended", timeout=10000)
            check(s.locator("text=Rude").count() == 0, f"[{width}] student sees suspended, not the staff reason")
            a.click("[data-do=onPick][data-v=suspended]"); a.wait_for_timeout(400)
            check(a.locator("tbody tr").count() == 1, f"[{width}] Suspended card filters the list")
            SHOT(a, f"suspended-{width}")
            a.context.close(); s.context.close()
        # ---- a limited admin has no tab, and the address does not open it ----
        l = br.new_context(viewport={"width": 1280, "height": 900}).new_page(); l.on("pageerror", lambda e: errors.append(str(e)))
        e2e_shim.login(l, BASE, "lim@p.test", "Password123", db=DB)
        # v0.8.48: every admin may look; only the superadmin gets the buttons
        l.goto(BASE + "/#online"); l.wait_for_selector("main h1:has-text(\"Who's online\")")
        check(l.locator("[data-do=onKick],[data-do=onPause],[data-do=onSuspend],[data-do=onKickAll]").count() == 0, "limited admin: sees the list, no action buttons")
        # ---- extras: dashboard card, bulk pause with a message, history, sign out everyone (computer width) ----
        sql("UPDATE users SET suspended_at=NULL, suspend_reason=NULL, paused_until=NULL, account_message=NULL")
        for _ in range(3):
            try: api("/auth/login", {"login": "ali@p.test", "password": "bad"})
            except urllib.error.HTTPError: pass
        a = br.new_context(viewport={"width": 1280, "height": 900}).new_page(); a.on("pageerror", lambda e: errors.append(str(e)))
        s2 = br.new_context(viewport={"width": 390, "height": 800}).new_page(); s2.on("pageerror", lambda e: errors.append(str(e)))
        e2e_shim.login(s2, BASE, "sara@p.test", "Password123", db=DB)
        e2e_shim.login(a, BASE, "admin@p.test", "AdminPass123", db=DB)
        a.goto(BASE + "/#dashboard"); a.wait_for_selector("#onp")
        check(a.locator("#onp", has_text="Online now").count() == 1 and a.locator("#onp", has_text="failed sign-ins (24 h)").count() == 1, "dashboard: Online now panel with failed sign-ins")
        SHOT(a, "dashboard")
        a.goto(BASE + "/#online"); a.wait_for_selector("main h1:has-text(\"Who's online\")")
        check(a.locator("tr:has-text('Ali Student') .tag", has_text="failed sign-ins").count() == 1, "row warns about failed sign-ins")
        for name in ("Sara Student", "Ali Student"): a.locator(f"tr:has-text('{name}') input.bulk").check()
        a.wait_for_selector("[data-bulkbar=onl]:not([hidden])")
        a.click("[data-bulkbar=onl] [data-do=onBulkPause]"); a.wait_for_selector("dialog.dlg[open] select")
        a.locator("dialog.dlg[open] select").select_option("72")
        a.locator("dialog.dlg[open] input[maxlength='200']").fill("See you after the holiday"); SHOT(a, "bulk-pause"); a.click(OK)
        a.wait_for_selector("text=2 / 2", timeout=10000)
        r = sql("SELECT COUNT(*) FROM users WHERE paused_until IS NOT NULL AND account_message='See you after the holiday'")[0][0]
        check(r == 2, f"bulk pause: both paused with the message ({r})")
        s2.reload(); s2.wait_for_selector("#le", timeout=15000)
        s2.fill("#le", "sara@p.test"); s2.fill("#lp", "Password123"); s2.click("#fl button"); s2.wait_for_selector("text=See you after the holiday", timeout=10000)
        check(True, "paused student sees the academy's message")
        a.locator("tr:has-text('Ali Student') [data-do=onHist]").click(); a.wait_for_selector("dialog.dlg[open] h3")
        check(a.locator("dialog.dlg[open]", has_text="Wrong password").count() == 1, "history lists the failed attempts")
        check(a.locator("dialog.dlg[open]", has_text="paused until").count() == 1, "history lists the account action")
        SHOT(a, "history"); a.click("dialog.dlg[open] button[value=ok]")
        for name in ("Sara Student", "Ali Student"): a.locator(f"tr:has-text('{name}') input.bulk").check()
        a.click("[data-bulkbar=onl] [data-do=onBulkRestore]"); a.click(OK); a.wait_for_selector("text=2 / 2", timeout=10000)
        check(sql("SELECT COUNT(*) FROM users WHERE paused_until IS NOT NULL")[0][0] == 0, "bulk restore")
        e2e_shim.login(s2, BASE, "sara@p.test", "Password123", db=DB)
        a.click("[data-do=onKickAll]"); a.wait_for_selector("dialog.dlg[open] select"); a.locator("dialog.dlg[open] select").select_option("student"); a.click(OK)
        a.wait_for_selector("text=accounts signed out")
        s2.reload(); s2.wait_for_selector("#le", timeout=15000)
        check(s2.is_visible("#le"), "Sign out everyone (students): the student is signed out")
        check(a.locator("main h1").count() == 1 and not a.is_visible("#le"), "the admin who did it stays signed in")
        br.close()
finally:
    srv.terminate()
print("\n" + ("ALL PASS" if not errors else f"{len(errors)} FAILED: {errors}"))
sys.exit(1 if errors else 0)
