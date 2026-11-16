"""Optional browser test, v0.8.59: installable app and "Keep me signed in on this device", at 390 px and 1280 px.
Checks: manifest and service worker load; the worker never answers /api/; the app opens offline; Keep me signed in survives closing the tab and
Sign out forgets it; an unticked sign-in does not survive; the Install button appears without wiping a half-typed sign-in; the iPhone steps.
Run: python tests/e2e_v0859.py"""
import os, sys, time, subprocess, tempfile, json, sqlite3, urllib.request
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import e2e_shim  # noqa: F401
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(); DB = os.path.join(tmp, "v.db")
env = dict(os.environ, DATABASE_PATH=DB, ADMIN_EMAIL="admin@v.test", ADMIN_PASSWORD="AdminPass123", PORT="5099", SECRET_KEY="v" * 32, SEED_DEMO="0")
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
c = sqlite3.connect(DB); c.execute("UPDATE users SET must_change_password=0"); c.commit(); c.close()
srv = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(2)
BASE = "http://127.0.0.1:5099"; errors = []
OUT = os.environ.get("E2E_SHOTS") or tempfile.gettempdir()
IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"


def check(ok, m):
    print("PASS" if ok else "FAIL", m)
    if not ok: errors.append(m)


def store(pg):
    return pg.evaluate("() => ({s: sessionStorage.getItem('tok'), l: localStorage.getItem('tok')})")


def sign_in(pg, keep):
    pg.goto(BASE + "/"); pg.wait_for_selector("#lkeep")
    pg.fill("#le", "admin@v.test"); pg.fill("#lp", "AdminPass123")
    if keep: pg.check("#lkeep")
    pg.click("#fl button"); pg.wait_for_selector("nav .foot #so", state="attached")


try:
    m = json.load(urllib.request.urlopen(BASE + "/manifest.webmanifest"))
    check(m["display"] == "standalone" and len(m["icons"]) == 3, "manifest: standalone with the three built-in icons")
    with sync_playwright() as p:
        br = p.chromium.launch()
        for w in (390, 1280):
            ctx = br.new_context(viewport={"width": w, "height": 860})
            pg = ctx.new_page(); pg.on("pageerror", lambda e: errors.append(str(e)))
            # ---- service worker ----
            pg.goto(BASE + "/"); pg.wait_for_selector("#fl")
            ok = pg.evaluate("() => navigator.serviceWorker.ready.then(r => !!r.active)")
            check(ok, f"{w}: service worker registered and active")
            pg.reload(); pg.wait_for_selector("#fl")
            check(pg.evaluate("() => !!navigator.serviceWorker.controller"), f"{w}: page is controlled by the worker after a reload")
            check(not pg.is_checked("#lkeep"), f"{w}: Keep me signed in is off by default in a browser tab")
            # ---- not kept: gone in a new tab ----
            sign_in(pg, keep=False)
            s = store(pg); check(bool(s["s"]) and not s["l"], f"{w}: unticked sign-in kept only for this tab")
            pg2 = ctx.new_page(); pg2.goto(BASE + "/"); pg2.wait_for_selector("#fl")
            check(True, f"{w}: a new tab asks to sign in again"); pg2.close()
            pg.click(".foot #so") if pg.is_visible(".foot #so") else (pg.click("#moreBtn"), pg.click(".foot #so"))
            pg.wait_for_selector("#fl")
            # ---- kept: survives closing the tab ----
            sign_in(pg, keep=True)
            s = store(pg); check(bool(s["l"]) and not s["s"], f"{w}: ticked sign-in kept on this device")
            pg.close(); pg = ctx.new_page(); pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(BASE + "/"); pg.wait_for_selector("nav .foot #so", state="attached", timeout=15000)
            check(True, f"{w}: still signed in after closing and reopening")
            # ---- /api/ is never stored by the worker ----
            names = pg.evaluate("async () => { const out = []; for (const k of await caches.keys()) for (const r of await (await caches.open(k)).keys()) out.push(new URL(r.url).pathname); return out; }")
            check(names and not any(n.startswith("/api/") for n in names), f"{w}: saved copies hold no /api/ replies ({len(names)} files)")
            # ---- offline ----
            ctx.set_offline(True)
            pg.reload(); pg.wait_for_selector("#root .auth, #root .app, main", timeout=15000)
            body = pg.inner_text("body")
            check("This site can" not in body and len(body) > 10, f"{w}: the app still opens offline and explains")
            if w == 390: pg.screenshot(path=os.path.join(OUT, "v0859_offline_390.png"))
            ctx.set_offline(False)
            pg.reload(); pg.wait_for_selector("nav .foot #so", state="attached", timeout=15000)
            # ---- Sign out forgets the device ----
            if not pg.is_visible(".foot #so"): pg.click("#moreBtn")
            pg.click(".foot #so"); pg.wait_for_selector("#fl")
            s = store(pg); check(not s["l"] and not s["s"], f"{w}: Sign out forgets the token everywhere")
            # ---- Install button appears without wiping typing (Chrome's install event, faked) ----
            pg.fill("#le", "BAL/AL1/001")
            pg.evaluate("() => { const e = new Event('beforeinstallprompt'); e.prompt = () => { window.__prompted = true; }; e.userChoice = Promise.resolve({outcome: 'accepted'}); window.dispatchEvent(e); }")
            pg.wait_for_selector("#instBtn")
            check(pg.input_value("#le") == "BAL/AL1/001", f"{w}: Install button appears and the typed ID is kept")
            if w == 390: pg.screenshot(path=os.path.join(OUT, "v0859_signin_390.png"), full_page=True)
            pg.click("#instBtn"); check(pg.evaluate("() => window.__prompted === true"), f"{w}: Install button opens the browser's install prompt")
            ctx.close()
        # ---- iPhone: steps instead of a prompt; Keep me signed in ticked in the installed app ----
        ctx = br.new_context(viewport={"width": 390, "height": 844}, user_agent=IPHONE, is_mobile=True, has_touch=True)
        pg = ctx.new_page(); pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(BASE + "/"); pg.wait_for_selector("#instBtn")
        pg.click("#instBtn"); pg.wait_for_selector("dialog[open] ol.steps")
        check("Add to Home Screen" in pg.inner_text("dialog[open]"), "iPhone: Install shows the Add to Home Screen steps")
        pg.screenshot(path=os.path.join(OUT, "v0859_iphone_steps.png"))
        pg.keyboard.press("Escape")
        pg.add_init_script("Object.defineProperty(navigator, 'standalone', {get: () => true})")
        pg.reload(); pg.wait_for_selector("#lkeep")
        check(pg.is_checked("#lkeep") and not pg.is_visible("#instBtn"), "installed app: Keep me signed in ticked, no Install button")
        ctx.close(); br.close()
finally:
    srv.terminate()
print("\n" + ("ALL PASSED" if not errors else "FAILED:\n" + "\n".join(errors)))
sys.exit(1 if errors else 0)
