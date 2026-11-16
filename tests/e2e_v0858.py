"""Optional browser test, v0.8.58: batch end time on the Batches screen and in the timetable; the Teachers' room (chat, pin, head teacher,
teachers' guide, locked folder) for an admin, a head teacher and a plain teacher, at 390 px and 1280 px. Run: python tests/e2e_v0858.py"""
import os, sys, time, subprocess, tempfile, json, sqlite3, urllib.request
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import e2e_shim  # noqa: F401
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(); DB = os.path.join(tmp, "v.db")
env = dict(os.environ, DATABASE_PATH=DB, ADMIN_EMAIL="admin@v.test", ADMIN_PASSWORD="AdminPass123", PORT="5098", SECRET_KEY="v" * 32, SEED_DEMO="0")
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
def sql(q, a=()):
    c = sqlite3.connect(DB)
    try: r = c.execute(q, a).fetchall(); c.commit(); return r
    finally: c.close()
sql("UPDATE users SET must_change_password=0")
srv = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(2)
BASE = "http://127.0.0.1:5098"; errors = []
OUT = os.environ.get("E2E_SHOTS") or tempfile.gettempdir()
PDF = os.path.join(tmp, "Level 1 answer key.pdf"); open(PDF, "wb").write(b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")
def check(ok, m):
    print("PASS" if ok else "FAIL", m)
    if not ok: errors.append(m)
def api(path, body=None, tok=None):
    r = urllib.request.Request(BASE + "/api" + path, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    return json.load(urllib.request.urlopen(r))
try:
    adm = api("/auth/login", {"login": "admin@v.test", "password": "AdminPass123"})["token"]
    def mk(e, n, role="teacher"):
        i = api("/users", {"email": e, "password": "Password123", "full_name": n, "role": role, "phone": "7771234"}, adm)["id"]; sql("UPDATE users SET must_change_password=0"); return i
    t1, t2 = mk("t1@v.test", "Ustaz Ahmed"), mk("t2@v.test", "Ustaza Fathimath")
    co = api("/courses", {"name": "Arabic Level 1", "monthly_fee_mvr": 500, "status": "open", "minutes_per_class": 60}, adm)["id"]
    with sync_playwright() as p:
        br = p.chromium.launch()
        for w in (390, 1280):
            a = br.new_context(viewport={"width": w, "height": 900}).new_page(); a.on("pageerror", lambda e: errors.append(str(e)))
            e2e_shim.login(a, BASE, "admin@v.test", "AdminPass123", db=DB)
            if w == 390:
                # ---- Batches: create with start and end time ----
                a.goto(BASE + "/#batches"); a.wait_for_selector("#bet")
                a.select_option("#bc", str(co)); a.fill("#bn", "E1"); a.fill("#bt", "16:00"); a.fill("#bet", "17:30"); a.fill("#bp", "12")
                a.select_option("#bh", str(t1)); a.check("input[name=bd][value=Mon]"); a.check("input[name=bd][value=Wed]")
                a.click("#fb button:not([type=button])"); a.wait_for_timeout(1000)
                check(sql("SELECT start_time, end_time FROM batches WHERE code='E1'") == [("16:00", "17:30")], "Batches: start and end time saved")
                check(a.locator("main table tbody tr", has_text="E1").locator("text=16:00–17:30").count() == 1, "Batches: list shows 16:00–17:30")
                bid = sql("SELECT id FROM batches WHERE code='E1'")[0][0]
                a.locator("main table tbody tr", has_text="E1").locator("[data-do=editB]").click(); a.wait_for_selector("#be_et")
                check(a.input_value("#be_et") == "17:30", "Batches: editor shows the end time")
                a.fill("#be_et", "18:00"); a.click("[data-do=saveB]"); a.wait_for_timeout(900)
                check(sql("SELECT end_time FROM batches WHERE id=?", (bid,)) == [("18:00",)], "Batches: end time changed")
                a.locator("main table tbody tr", has_text="E1").locator("[data-do=editB]").click(); a.wait_for_selector("#be_et")
                a.fill("#be_et", "15:00"); a.click("[data-do=saveB]"); a.wait_for_timeout(900)
                check(a.locator("main .msg.err, main [role=alert]").filter(has_text="end time must be after").count() >= 1, "Batches: end before start is refused with a message")
                a.screenshot(path=os.path.join(OUT, "v0858-batch-editor.png"), full_page=True)
                a.click("[data-do=closeB]"); a.wait_for_timeout(500)
                a.goto(BASE + "/#timetable"); a.wait_for_selector(".tt")
                check(a.locator(".tt-i", has_text="16:00–18:00").count() >= 1, "Timetable: class shows 16:00–18:00")
                # ---- make a head teacher ----
                a.goto(BASE + "/#staff_room"); a.wait_for_selector("[data-tabs=sr]")
                a.click(e2e_shim.subtab("sr", "heads")); a.wait_for_selector("[data-do=srHead]")
                a.locator(".cl", has_text="Ustaz Ahmed").locator("[data-do=srHead]").click()
                a.locator("dialog[open] button.btn:not(.alt)").last.click(); a.wait_for_timeout(900)
                check(sql("SELECT is_head FROM teachers WHERE user_id=?", (t1,)) == [(1,)], "Admin: made Ustaz Ahmed head teacher")
                a.click(e2e_shim.subtab("sr", "chat")); a.wait_for_selector("#sr_text")
                a.fill("#sr_text", "Assalaamu alaikum. Staff meeting on Thursday after Asr."); a.click("#sr_f button[type=submit]"); a.wait_for_timeout(900)
                check(a.locator("#sr_list .srm.sr-me", has_text="Staff meeting").count() == 1, "Admin: message posted without a page reload")
            else:
                a.goto(BASE + "/#staff_room"); a.wait_for_selector("#sr_list")
                check(a.locator("#sr_list .srm", has_text="Staff meeting").count() == 1, "Admin (1280): sees the chat")
                a.screenshot(path=os.path.join(OUT, "v0858-admin-1280.png"), full_page=True)
            a.context.close()

        # ---- plain teacher at 390: posts with an attachment, adds a guide file, cannot use a locked folder ----
        tp = br.new_context(viewport={"width": 390, "height": 900}).new_page(); tp.on("pageerror", lambda e: errors.append(str(e)))
        e2e_shim.login(tp, BASE, "t2@v.test", "Password123", db=DB)
        tp.goto(BASE + "/#staff_room"); tp.wait_for_selector("#sr_text")
        check(tp.locator("text=Head teacher: Ustaz Ahmed").count() >= 1, "Teacher: sees who the head teacher is")
        check(tp.locator("[data-do=srPin]").count() == 0, "Teacher: no Pin buttons")
        tp.fill("#sr_text", "Here is the answer key"); tp.set_input_files("#sr_file", PDF); tp.click("#sr_f button[type=submit]"); tp.wait_for_timeout(1200)
        check(tp.locator("#sr_list .srm.sr-me", has_text="answer key").locator("[data-do=srMsgFile]").count() == 1, "Teacher: message with attachment")
        tp.fill("#sr_text", "half typed"); tp.wait_for_timeout(9000)   # one poll goes by
        check(tp.input_value("#sr_text") == "half typed", "Teacher: polling keeps a half-typed message")
        tp.fill("#sr_text", "")
        # head teacher posts meanwhile; the teacher sees it without reloading
        h = api("/auth/login", {"login": "t1@v.test", "password": "Password123"})["token"]
        api("/staff/messages", {"body": "Please upload your exam papers by Sunday."}, h)
        tp.wait_for_timeout(9000)
        check(tp.locator("#sr_list .srm", has_text="exam papers").count() == 1, "Teacher: a new message appears by itself")
        tp.screenshot(path=os.path.join(OUT, "v0858-teacher-chat.png"), full_page=True)
        tp.click(e2e_shim.subtab("sr", "guide")); tp.wait_for_selector("[data-do=srAddFile]")
        check(tp.locator("[data-do=srNewFolder]").count() == 0, "Teacher: cannot make folders")
        tp.click("[data-do=srAddFile]"); tp.wait_for_selector("dialog[open]")
        d = tp.locator("dialog[open]")
        d.locator("input").first.fill("Week 1 lesson plan"); d.locator("input[type=file]").set_input_files(PDF)
        d.locator("button.btn:not(.alt)").last.click(); tp.wait_for_timeout(1200)
        check(tp.locator(".cl", has_text="Week 1 lesson plan").count() == 1, "Teacher: added a guide file")
        tp.context.close()

        # ---- head teacher at 390: pins, makes a locked folder ----
        hp = br.new_context(viewport={"width": 390, "height": 900}).new_page(); hp.on("pageerror", lambda e: errors.append(str(e)))
        e2e_shim.login(hp, BASE, "t1@v.test", "Password123", db=DB)
        hp.goto(BASE + "/#staff_room"); hp.wait_for_selector("#sr_list")
        check(hp.locator("text=You are a head teacher").count() == 1, "Head teacher: knows it")
        hp.locator("#sr_list .srm", has_text="Staff meeting").locator("[data-do=srPin]").click(); hp.wait_for_timeout(1000)
        check(hp.locator("#sr_pins .srpins", has_text="Staff meeting").count() == 1, "Head teacher: pinned message on top")
        check(sql("SELECT COUNT(*) FROM notifications WHERE user_id=? AND kind='staff_room'", (t2,))[0][0] >= 1, "Teacher notified of the pin")
        hp.click(e2e_shim.subtab("sr", "guide")); hp.wait_for_selector("[data-do=srNewFolder]")
        hp.click("[data-do=srNewFolder]"); d = hp.locator("dialog[open]")
        d.locator("input").first.fill("Official guides"); d.locator("input[type=checkbox]").check(); d.locator("button.btn:not(.alt)").last.click(); hp.wait_for_timeout(1000)
        check(sql("SELECT locked FROM staff_folders WHERE name='Official guides'") == [(1,)], "Head teacher: locked folder made")
        hp.screenshot(path=os.path.join(OUT, "v0858-head-guide.png"), full_page=True)
        hp.context.close()
        tok2 = api("/auth/login", {"login": "t2@v.test", "password": "Password123"})["token"]
        fs = api("/staff/folders", None, tok2)["folders"]
        check([f["can_add"] for f in fs if f["name"] == "Official guides"] == [False], "Teacher: cannot add to the locked folder")
        br.close()
finally:
    srv.terminate()
print("ALL PASS" if not errors else f"{len(errors)} FAILED: {errors}")
sys.exit(1 if errors else 0)
