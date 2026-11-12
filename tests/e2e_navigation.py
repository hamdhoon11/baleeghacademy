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

    # ---- Session 9B (v0.8.33): tabs are links, Back arrow on detail screens, last tab remembered, Ctrl+K, badges ----
    def signin(pg, role):
        e, pw = WHO[role]; pg.goto(B + "/"); pg.fill("#le", e); pg.fill("#lp", pw); pg.click("#fl button")
        pg.wait_for_selector("nav, [data-sb]")
        if pg.is_visible("[data-sb]"): pg.click("[data-sb]")
        pg.wait_for_selector("main h1")
    ctx = b.new_context(viewport={"width": 1366, "height": 768}); pg = ctx.new_page(); errs = []
    pg.on("pageerror", lambda x: errs.append(str(x)))
    signin(pg, "admin")
    links = pg.eval_on_selector_all("nav [data-v]", "els=>els.map(e=>[e.tagName, e.getAttribute('href'), e.dataset.v])")
    ok("tabs are <a href=#name> links", links and all(t_ == "A" and h == "#" + v for t_, h, v in links), links[:3])
    # Ctrl/Cmd-click and middle-click are left to the browser (new tab); only a plain left click is handled in the page
    left_alone = pg.evaluate("""() => { const a = document.querySelector('nav [data-v=people]'), r = {};
      for (const [k, o] of Object.entries({ctrl: {ctrlKey: true}, meta: {metaKey: true}, middle: {button: 1}})) {
        document.addEventListener('click', e => { r[k] = e.defaultPrevented; e.preventDefault(); }, {once: true});   // runs after the app's handler; then stops the real navigation
        a.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, ...o})); }
      return r; }""")
    ok("Ctrl-, Cmd- and middle-click on a tab are left to the browser (open in a new tab)", left_alone == {"ctrl": False, "meta": False, "middle": False}, left_alone)
    pg.click("nav [data-v=people]")
    pg.wait_for_timeout(600)
    ok("plain click is handled in the page (no reload) and lands on #people", pg.evaluate("location.hash") == "#people")
    pg.click("nav [data-v=people]"); pg.wait_for_selector("[data-do=euEdit]")
    pg.click("[data-do=euEdit]"); pg.wait_for_selector("#fue")
    ok("desktop: breadcrumb above the h1 on a detail screen", pg.is_visible(".crumb") and "People" in pg.inner_text(".crumb"))
    pg.go_back(); pg.wait_for_selector("#fue", state="detached")
    ok("browser Back closes the editor but stays on People", pg.evaluate("location.hash") == "#people")
    pg.keyboard.press("Control+k"); pg.wait_for_selector("dialog.dlg[open] [role=combobox]")
    ok("Ctrl+K opens quick jump with a filter box", pg.is_visible("dialog.dlg[open] [role=listbox]"))
    pg.keyboard.type("fees"); pg.keyboard.press("Enter"); pg.wait_for_selector("dialog.dlg[open]", state="detached"); pg.wait_for_timeout(600)
    ok("typing and Enter in quick jump navigates", pg.evaluate("location.hash") == "#fees")
    pg.keyboard.press("Control+k"); pg.wait_for_selector("dialog.dlg[open]"); pg.keyboard.type("add course"); pg.keyboard.press("Enter"); pg.wait_for_timeout(800)
    ok("quick action Add course opens the collapsed Add panel with the cursor in it", pg.evaluate("location.hash") == "#courses" and pg.evaluate("document.querySelector('details.addp[data-add=course]').open && document.activeElement.id === 'cn'"))
    pg.keyboard.press("Alt+1"); pg.wait_for_timeout(300)
    ok("shortcuts are ignored while typing in a field", pg.evaluate("location.hash") == "#courses")
    pg.evaluate("document.activeElement.blur()"); pg.keyboard.press("Alt+1"); pg.wait_for_timeout(700)
    ok("Alt+1 jumps to the first tab", pg.evaluate("location.hash") == "#dashboard")
    pg.keyboard.press("Shift+?"); pg.wait_for_selector("dialog.dlg[open]"); ok("? opens the shortcuts help", "Ctrl" in pg.inner_text("dialog.dlg[open]")); pg.keyboard.press("Escape")
    ok("badge on Admissions hidden when nothing is pending", pg.eval_on_selector("nav [data-v=admissions] .bdg", "e=>e.hidden") and pg.eval_on_selector("nav [data-v=admissions]", "e=>!e.hasAttribute('aria-label')"))
    c_ = sqlite3.connect(env["DATABASE_PATH"]); c_.execute("INSERT INTO applications(ref,full_name,date_of_birth,phone,email,course_id,status) VALUES('BA-T1','Test Applicant','2000-01-01','7000000','x@x.test',1,'pending')"); c_.commit(); c_.close()
    pg.evaluate("BADGE.at = 0"); pg.click("nav [data-v=courses]"); pg.wait_for_function("!document.querySelector('nav [data-v=admissions] .bdg').hidden", timeout=5000)
    ok("badge on Admissions shows 1 and the count is in its aria-label", pg.inner_text("nav [data-v=admissions] .bdg") == "1" and "(1)" in (pg.get_attribute("nav [data-v=admissions]", "aria-label") or ""))
    pg.goto(B + "/"); pg.wait_for_selector("main h1")
    ok("last tab is remembered when the URL has no #name", pg.evaluate("location.hash") == "#courses")
    ok("no script errors in the Session 9B checks (desktop)", not errs, errs[:2])
    # phone: Back arrow in the top bar on a detail screen, section title next to the mark
    ph = b.new_context(viewport={"width": 390, "height": 800}).new_page(); perr = []; ph.on("pageerror", lambda x: perr.append(str(x)))
    signin(ph, "admin"); ph.click("nav [data-v=people]"); ph.wait_for_selector("[data-do=euEdit]")
    ok("phone top bar shows the section title", ph.inner_text(".brand .btitle").strip() == "People" and not ph.is_visible("#topBack"))
    ph.click("[data-do=euEdit]"); ph.wait_for_selector("#fue")
    ok("phone: Back arrow on a detail screen", ph.is_visible("#topBack") and not ph.is_visible(".crumb"))
    ph.click("#topBack"); ph.wait_for_selector("#fue", state="detached"); ph.wait_for_timeout(300)
    ok("phone: Back arrow returns to the list", ph.evaluate("location.hash") == "#people" and not ph.is_visible("#topBack"))
    ph.click("#moreBtn"); ph.wait_for_timeout(200); ph.keyboard.press("Tab"); ph.keyboard.press("Shift+Tab"); ph.keyboard.press("Shift+Tab")
    ok("phone: focus stays inside the open More sheet", ph.evaluate("!!document.activeElement.closest('#sheet')"))
    ph.keyboard.press("Escape"); ph.wait_for_timeout(200)
    ok("phone: Escape closes More and focus returns to it", ph.evaluate("document.activeElement.id") == "moreBtn" and not ph.is_visible("#so"))
    ok("no script errors in the Session 9B checks (phone)", not perr, perr[:2])
    st = b.new_context(viewport={"width": 390, "height": 800}).new_page(); signin(st, "student")
    ok("student phone bar is Home, Assignments, Fees, Progress", st.eval_on_selector_all("nav .pri [data-v]", "els=>els.map(e=>e.dataset.v)") == ["home", "assignments", "fees", "progress"])
    b.close()
finally:
    srv.terminate()
print("\n%d failure(s)" % len(fails)); sys.exit(1 if fails else 0)
