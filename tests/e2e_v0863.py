"""Optional browser test, v0.8.63: Notice board (post with a picture and a video link, the student sees it, comments, Seen by) and the bell's
To-do tab and New/Read labels. At 390 px and 1280 px. Run: python tests/e2e_v0863.py"""
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
PNG = os.path.join(tmp, "class-photo.png")
import zlib, struct
def png(w, h):   # a small real picture (teal and coral stripes)
    raw = b"".join(b"\x00" + b"".join((b"\x1b\x7f\x79" if (x // 20) % 2 else b"\xe3\x6b\x4f") for x in range(w)) for _ in range(h))
    ch = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b"")
open(PNG, "wb").write(png(320, 180))
def check(ok, m):
    print("PASS" if ok else "FAIL", m)
    if not ok: errors.append(m)
def api(path, body=None, tok=None):
    r = urllib.request.Request(BASE + "/api" + path, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    return json.load(urllib.request.urlopen(r))
try:
    adm = api("/auth/login", {"login": "admin@v.test", "password": "AdminPass123"})["token"]
    co = api("/courses", {"name": "Arabic Level 1", "monthly_fee_mvr": 500, "status": "open"}, adm)["id"]
    b1 = api("/batches", {"course_id": co, "code": "A1-JAN", "capacity": 12, "days": "Sun,Tue", "start_time": "16:00", "start_date": "2026-11-01"}, adm)["id"]
    with sync_playwright() as p:
        br = p.chromium.launch()
        for w in (390, 1280):
            sid = api("/users", {"email": f"s{w}@v.test", "password": "Password123", "full_name": f"Student {w}", "role": "student", "phone": "7771234", "guardian_phone": "7771234"}, adm)["id"]
            sql("UPDATE users SET must_change_password=0")
            api("/enrollments", {"student_id": sid, "batch_id": b1}, adm)
            title = f"Eid holiday {w}"
            # ---- admin posts with a picture and a video link ----
            pg = br.new_context(viewport={"width": w, "height": 900}).new_page(); pg.on("pageerror", lambda e: errors.append(str(e)))
            e2e_shim.login(pg, BASE, "admin@v.test", "AdminPass123", db=DB)
            pg.goto(BASE + "/#posts"); pg.wait_for_selector("#po_new")
            pg.click("#po_new summary"); pg.fill("#po_title", title); pg.fill("#po_body", "No classes on Monday and Tuesday.\nEid Mubarak!")
            pg.fill("#po_video", "https://youtu.be/dQw4w9WgXcQ"); pg.set_input_files("#po_files", PNG); pg.select_option("#po_aud", "students")
            pg.click("#po_f button.btn"); pg.locator("dialog[open]").wait_for(); pg.locator("dialog[open] button.btn:not(.alt)").last.click()
            pg.wait_for_selector(f"article.po:has-text('{title}')", timeout=10000); pg.wait_for_timeout(800)
            pid = sql("SELECT id FROM posts WHERE title=?", (title,))[0][0]
            check(sql("SELECT COUNT(*) FROM post_files WHERE post_id=?", (pid,))[0][0] == 1, f"Post saved with its picture ({w})")
            check(pg.locator(f"#post{pid} iframe[src*='youtube-nocookie.com/embed/dQw4w9WgXcQ']").count() == 1, f"Video plays in the post ({w})")
            check(pg.locator(f"#post{pid} img[src^='blob:']").count() == 1, f"Picture shown in the post ({w})")
            check(sql("SELECT COUNT(*) FROM notifications WHERE user_id=? AND link=?", (sid, f"posts:{pid}"))[0][0] == 1, f"Student notified ({w})")
            pg.screenshot(path=os.path.join(OUT, f"v0863-admin-{w}.png"), full_page=True)
            # ---- the student: bell shows New, opens the post; To do tab; comment ----
            sp = br.new_context(viewport={"width": w, "height": 900}).new_page(); sp.on("pageerror", lambda e: errors.append(str(e)))
            e2e_shim.login(sp, BASE, f"s{w}@v.test", "Password123", db=DB)
            sp.wait_for_selector("#bell"); sp.wait_for_timeout(600)
            check((sp.locator("#bellN").inner_text() or "0") != "", f"Bell shows unread count ({w})")
            sp.click("#bell"); sp.wait_for_selector("#npanel .it")
            check(sp.locator("#npanel .it.un .nst.nw").count() >= 1, f"Unread notifications say New ({w})")
            sp.click("#ntab_td"); sp.wait_for_selector("#ntd")
            td = sp.locator("#ntd").inner_text()
            check("To do" in td and "New posts to read" in td and "Pay 500 MVR" in td, f"To-do tab lists posts to read and fees ({w})")
            sp.screenshot(path=os.path.join(OUT, f"v0863-todo-{w}.png"))
            sp.click("#ntab_in"); sp.wait_for_selector("#nl .it")
            sp.locator("#nl .it", has_text="New post from").first.click()
            sp.wait_for_selector(f"#post{pid}"); sp.wait_for_timeout(2200)
            check(sp.locator(f"#post{pid}.po-hl").count() == 1, f"Notification opens that post ({w})")
            check(sql("SELECT COUNT(*) FROM post_reads WHERE post_id=? AND user_id=?", (pid, sid))[0][0] == 1, f"Shown = read ({w})")
            sp.click(f"[data-do=poComments][data-id='{pid}']"); sp.wait_for_selector(f"#pocx{pid}")
            sp.fill(f"#pocx{pid}", "Eid Mubarak, teacher!"); sp.click(f"#poc{pid} form button")
            sp.wait_for_selector(f"#poc{pid} li:has-text('Eid Mubarak, teacher!')")
            check(sp.locator(f"[data-do=poComments][data-id='{pid}']").inner_text().strip().endswith("(1)"), f"Comment count updates ({w})")
            check(sp.locator(f"#post{pid} [data-do=poSeen]").count() == 0 and sp.locator("#po_new").count() == 0, f"Students cannot post or see Seen by ({w})")
            sp.click("#bell"); sp.wait_for_selector("#npanel"); sp.click("#ntab_td"); sp.wait_for_selector("#ntd")
            check("All Notice board posts read" in sp.locator("#ntd").inner_text(), f"To-do shows the posts as done ({w})")
            sp.screenshot(path=os.path.join(OUT, f"v0863-student-{w}.png"), full_page=True)
            sp.keyboard.press("Escape")
            # ---- admin: Seen by ----
            pg.reload(); pg.wait_for_selector(f"#post{pid}")
            pg.click(f"#post{pid} [data-do=poSeen]"); d = pg.locator("dialog[open]"); d.wait_for()
            check(f"Student {w}" in d.inner_text() and "Seen (1)" in d.inner_text(), f"Seen by lists the student ({w})")
            pg.screenshot(path=os.path.join(OUT, f"v0863-seen-{w}.png"))
            pg.keyboard.press("Escape")
        br.close()
finally:
    srv.terminate()
print("FAILURES:", errors) if errors else print("ALL PASS")
sys.exit(1 if errors else 0)
