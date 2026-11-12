"""Imported by the browser scripts.

1. On a phone, only the first four tabs sit in the bottom bar; the rest are behind "More". A real person taps More first,
   so the shim does the same when a script clicks a tab that is not showing yet.
2. login(): one sign-in helper for every script (Session 22, v0.8.33). It
   - clears the forced first-sign-in password change (Session 11) for accounts the script created after seeding,
   - accepts a login ID or an email (email sign-in stays on while ALLOW_EMAIL_LOGIN is not 0),
   - gets past the course chooser that a teacher or student with several batches sees (Sessions 14/15),
   - waits until the app shell (nav) is really there.
3. Selectors for the shared sub-tabs (Session 12): subtab("classroom", "schedule") instead of the old [data-do=ctab][data-v=...].
"""
import sqlite3
from playwright.sync_api import Page

_click = Page.click


def _click_with_menu(self, selector, *a, **k):
    if isinstance(selector, str) and selector.startswith("nav [data-v") and not self.is_visible(selector) and self.is_visible("#moreBtn"):
        _click(self, "#moreBtn")
    return _click(self, selector, *a, **k)


Page.click = _click_with_menu


def clear_forced_change(db_path):
    c = sqlite3.connect(db_path)
    c.execute("UPDATE users SET must_change_password=0"); c.commit(); c.close()


def login(pg, base, who, pw, db=None, batch=None):
    """Sign in and wait for the app. batch: the batch id to pick on the course chooser (default: the first one)."""
    if db: clear_forced_change(db)
    pg.goto(base + "/")
    pg.fill("#le", who); pg.fill("#lp", pw); pg.click("#fl button")
    pg.wait_for_selector("nav, [data-sb], #fcp", timeout=15000)
    if pg.is_visible("[data-sb]"):
        _click(pg, f"[data-sb='{batch}']" if batch else "[data-sb]")
    pg.wait_for_selector("nav", timeout=15000)
    pg.wait_for_selector("main h1", timeout=15000)


def subtab(group, key):
    return f"[data-tabs={group}] [data-key={key}]"


def preview_bytes(pg, selector):
    """PDFs and images open in a new tab (Session 8) instead of downloading. Headless Chrome has no PDF viewer, so window.open is
    replaced by a stand-in for this one click; the test reads the file the app gives that tab (its blob URL)."""
    pg.evaluate("""() => { window.__tabs = []; window.open = () => { const w = {closed: false, close() { this.closed = true; }, location: null}; window.__tabs.push(w); return w; }; }""")
    pg.click(selector)
    pg.wait_for_function("window.__tabs.length && window.__tabs[0].location", timeout=15000)
    data = pg.evaluate("fetch(String(window.__tabs[0].location)).then(r=>r.arrayBuffer()).then(b=>Array.from(new Uint8Array(b)))")
    return bytes(data)


def dialog(pg, text=None, ok=True):
    """Answer the next ui.js dialog (Session 2): optionally type into its first field, then press OK or Cancel."""
    pg.wait_for_selector("dialog.dlg[open]")
    if text is not None:
        pg.fill("dialog.dlg[open] input:not([type=search]), dialog.dlg[open] textarea", text)
    pg.click("dialog.dlg[open] button[value=%s]" % ("ok" if ok else "cancel"))
    pg.wait_for_selector("dialog.dlg[open]", state="detached")
