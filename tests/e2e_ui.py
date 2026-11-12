"""Browser checks for the v0.8.33 UI corrections (Session 22c): Session 1 (a failed save keeps the form), Session 2 (dialogs: Escape,
focus back to the button that opened them), Session 9A (tabs are links, crumbs, Back), Session 14 (grading in place, Save all,
attendance guard). Run: python tests/e2e_ui.py (needs playwright + chromium)"""
import os, sys, subprocess, time, tempfile, json, urllib.request, urllib.parse
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import e2e_shim  # noqa: E402
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(); PORT = "5086"; B = f"http://127.0.0.1:{PORT}"
env = dict(os.environ, DATABASE_PATH=os.path.join(tmp, "u.db"), ADMIN_EMAIL="admin@u.test", ADMIN_PASSWORD="AdminPass123", PORT=PORT, SECRET_KEY="u", NO_PROXY="127.0.0.1,localhost")
subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=env, check=True, capture_output=True)
srv = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(2.5)
fails, errs = [], []
def ok(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (" " + str(extra) if not cond and extra else ""))
    if not cond: fails.append(name)
def api(path, body=None, tok=None, method=None):
    r = urllib.request.Request(B + "/api" + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    return json.load(urllib.request.urlopen(r))
e2e_shim.clear_forced_change(env["DATABASE_PATH"])   # seeded accounts start with the forced password change (Session 11)
try:
    adm = api("/auth/login", {"email": "admin@u.test", "password": "AdminPass123"})["token"]
    aid = api("/batches/1/assignments", {"title": "Essay one", "max_points": 10}, adm)["id"]
    with sync_playwright() as p:
        b = p.chromium.launch()
        def page(w=1366, h=800):
            pg = b.new_context(viewport={"width": w, "height": h}).new_page(); pg.on("pageerror", lambda x: errs.append(str(x))); return pg

        # ---- Session 1: a failed save keeps what was typed, shows the message next to the form, button usable again ----
        a = page(); e2e_shim.login(a, B, "admin@u.test", "AdminPass123", db=env["DATABASE_PATH"])
        a.click("nav [data-v=people]"); a.click("details.addp[data-add=person] summary")
        a.evaluate("document.querySelector('#fu').dataset.mark = 'same-node'")   # proves the form was not redrawn
        a.fill("#un", "Second Admin Copy"); a.fill("#ue", "admin@u.test"); a.select_option("#ur", "admin")   # the email is taken: the server says no
        a.click("#fu button"); a.wait_for_selector("[data-err][role=alert]")
        ok("S1: error shown in a role=alert banner right before the form", a.evaluate("document.querySelector('#fu').previousElementSibling.matches('[data-err][role=alert]')"))
        ok("S1: the form is the same element and keeps what was typed", a.evaluate("document.querySelector('#fu').dataset.mark") == "same-node" and a.input_value("#un") == "Second Admin Copy")
        ok("S1: the submit button is enabled again and not busy", a.evaluate("(b => !b.disabled && !b.hasAttribute('aria-busy'))(document.querySelector('#fu button'))"))
        ok("S1: the banner has focus (screen readers and keyboard land on it)", a.evaluate("document.activeElement.matches('[data-err]')"))

        # ---- Session 1: the button is disabled while its request runs ----
        a.route("**/api/courses/*", lambda r: (time.sleep(1.2), r.continue_()) if r.request.method == "DELETE" else r.continue_())
        # ---- Session 2: dialog opens with focus on Cancel (danger), Escape closes, focus returns to the opener ----
        a.click("nav [data-v=courses]"); a.click("[data-do=ecEdit]"); a.wait_for_selector("#fce")
        ok("S9A: crumb 'Courses and tuition > course' above the h1", a.is_visible(".crumb") and a.evaluate("document.querySelector('.crumb').nextElementSibling.tagName") == "H1")
        a.click("[data-do=ecDel]"); a.wait_for_selector("dialog.dlg[open]")
        ok("S2: delete confirm is a danger dialog that names what will be deleted", a.is_visible("dialog.dlg.danger[open]") and "Arabic" in a.inner_text("dialog.dlg[open]"))
        ok("S2: focus starts on Cancel for a danger dialog", a.evaluate("document.activeElement.value") == "cancel")
        a.keyboard.press("Tab"); a.keyboard.press("Tab"); a.keyboard.press("Tab")
        ok("S2: Tab stays inside the dialog", a.evaluate("!!document.activeElement.closest('dialog.dlg')"))
        a.keyboard.press("Escape"); a.wait_for_selector("dialog.dlg", state="detached")
        ok("S2: Escape cancels and focus returns to the Delete button", a.evaluate("document.activeElement.dataset.do") == "ecDel")
        ok("S2: nothing was deleted (still editing)", a.is_visible("#fce"))
        a.click("[data-do=ecDel]"); a.wait_for_selector("dialog.dlg[open]"); a.click("dialog.dlg[open] button[value=ok]")
        a.wait_for_function("(b => b && b.disabled && b.getAttribute('aria-busy') === 'true')(document.querySelector('[data-do=ecDel]'))", timeout=3000)
        ok("S1: the clicked button is disabled with aria-busy while the request runs", True)
        a.wait_for_selector("[data-err][role=alert]")   # the seeded course has batches: the server refuses
        ok("S1: refused delete shows the reason next to the editor, editor kept", a.is_visible("#fce") and "batch" in a.inner_text("[data-err]").lower())
        a.unroute("**/api/courses/*")

        # ---- Session 9A: tabs are links; Back from an editor; quick jump also reachable by the Search button ----
        ok("S9A: every tab is a link to #name", a.evaluate("[...document.querySelectorAll('nav [data-v]')].every(e => e.tagName === 'A' && e.getAttribute('href') === '#' + e.dataset.v)"))
        a.click(".crumb a"); a.wait_for_selector("#fce", state="detached")
        ok("S9A: the crumb link goes back to the list", a.evaluate("location.hash") == "#courses")
        a.click("#qjTop"); a.wait_for_selector("dialog.dlg[open] [role=combobox]"); a.keyboard.press("Escape")
        ok("S9B: Search button in the sidebar opens quick jump; Escape returns focus to it", a.evaluate("document.activeElement.id") == "qjTop")

        # ---- Session 14: grading in place ----
        t = page(); e2e_shim.login(t, B, "teacher@baleegh.test", "ChangeMe-Teach1", db=env["DATABASE_PATH"], batch=1)
        t.click("nav [data-v=classroom]"); t.click(e2e_shim.subtab("classroom", "assignments")); t.click(f"[data-do=selA][data-id='{aid}']"); t.wait_for_selector("#gradep")
        t.evaluate("document.querySelector('#gradep').dataset.mark = 'same-node'")
        sid = t.get_attribute("#gradep .sub[data-sid]", "data-sid")
        t.fill(f"#g_{sid}", "8"); t.fill(f"#f_{sid}", "Good work"); t.click(f"[data-do=saveG][data-sid='{sid}']"); t.wait_for_selector(f"#gs_{sid}:not([hidden])")
        ok("S14: grade saved in place with a Saved mark (no redraw)", t.evaluate("document.querySelector('#gradep').dataset.mark") == "same-node")
        ok("S14: focus stays in the student's row (on the Saved mark once the row locks)", t.evaluate(f"!!document.activeElement.closest('.sub[data-sid=\\'{sid}\\']')"))
        g = api(f"/assignments/{aid}/submissions", tok=api("/auth/login", {"email": "teacher@baleegh.test", "password": "ChangeMe-Teach1"})["token"])
        ok("S14: the server has the grade", any(r["grade"] == 8 for r in g["students"]))
        ok("S14: without 'Change saved grades' the saved row locks itself (no redraw needed)", t.is_disabled(f"#g_{sid}") and t.locator(f"[data-do=saveG][data-sid='{sid}']").count() == 0)
        tid = [u for u in api("/users?role=teacher", tok=adm) if u["email"] == "teacher@baleegh.test"][0]["id"]
        api(f"/users/{tid}", {"permissions": ["classroom", "tutorials", "create_tutorials", "class_links", "add_recordings", "edit_grades", "cancel_class"]}, adm, "PATCH")
        t.reload(); t.wait_for_selector("[data-tabs=classroom]"); t.click(e2e_shim.subtab("classroom", "assignments")); t.click(f"[data-do=selA][data-id='{aid}']")
        t.wait_for_selector(f"#f_{sid}:not([disabled])")
        t.fill(f"#f_{sid}", "Very good work"); t.click("[data-do=saveGAll]"); t.wait_for_selector("#gradep .saved[data-err]")
        ok("S14: Save all saves the changed row and says how many", "1 grades saved" in t.inner_text("#gradep .saved[data-err]"))
        t.click("[data-do=saveGAll]"); t.wait_for_timeout(400)
        ok("S14: Save all with nothing changed says so", "Nothing changed" in t.inner_text("#gradep .saved[data-err]"))
        # attendance: Mark all present, then a date change asks first; Cancel keeps the date and the marks
        t.click(e2e_shim.subtab("classroom", "attendance")); t.wait_for_selector("#attp")
        t.locator(".seg input[value=absent]").first.check(); t.click("[data-do=attAllPresent]")
        ok("S14: Mark all present ticks everyone present", t.evaluate("[...document.querySelectorAll('#attp .seg input[value=present]')].every(i => i.checked)"))
        before = t.input_value("#adate")
        t.fill("#adate", "2026-01-05"); t.dispatch_event("#adate", "change"); t.wait_for_selector("dialog.dlg[open]"); t.wait_for_timeout(300)
        ok("S14: only one dialog even when the date field sends change twice", t.locator("dialog.dlg[open]").count() == 1)
        ok("S14: changing the date with unsaved marks asks first", "not saved" in t.inner_text("dialog.dlg[open]"))
        e2e_shim.dialog(t, ok=False)
        ok("S14: Cancel keeps the date", t.input_value("#adate") == before)
        t.click("[data-do=saveAtt]"); t.wait_for_selector("text=Attendance saved for")
        ok("S14: the save message counts the students", "Attendance saved for 1 students" in t.inner_text("main"))
        # ---- v0.8.34: downloads. A material named in Arabic opens in the viewer and downloads with its real name; on Android, no inline PDF ----
        name = "درس النحو.pdf"
        r = urllib.request.Request(B + f"/api/batches/1/materials", method="POST")
        import io as _io, uuid as _uuid
        bnd = _uuid.uuid4().hex
        bodyb = (f"--{bnd}\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\nNahw\r\n--{bnd}\r\nContent-Disposition: form-data; name=\"file\"; filename*=UTF-8''{urllib.parse.quote(name)}; filename=\"{name}\"\r\nContent-Type: application/pdf\r\n\r\n").encode() + b"%PDF-1.4 nahw" + f"\r\n--{bnd}--\r\n".encode()
        r = urllib.request.Request(B + "/api/batches/1/materials", data=bodyb, method="POST", headers={"Content-Type": "multipart/form-data; boundary=" + bnd, "Authorization": "Bearer " + adm})
        mid = json.load(urllib.request.urlopen(r))["id"]
        st = page(); e2e_shim.login(st, B, "student@baleegh.test", "ChangeMe-Stud1", db=env["DATABASE_PATH"], batch=1)
        st.click("nav [data-v=materials]") if st.locator("nav [data-v=materials]").count() else None
        st.goto(B + "/#materials"); st.wait_for_selector(f"[data-do=dlMat][data-id='{mid}']")
        st.click(f"[data-do=dlMat][data-id='{mid}']"); st.wait_for_selector("dialog.dlg.view[open]")
        ok("v0.8.34: a PDF opens in the viewer inside the page (no blank tab)", st.locator("dialog.dlg.view[open] .fv-pdf, dialog.dlg.view[open] .fv .hint").count() == 1 and len(st.context.pages) == 1)
        ok("v0.8.34: the viewer's Download keeps the Arabic name", st.get_attribute("dialog.dlg.view[open] a[download]", "download") == name)
        with st.expect_download() as dl: st.click("dialog.dlg.view[open] a[download]")
        ok("v0.8.34: Download saves the file with its Arabic name", dl.value.suggested_filename == name)
        st.keyboard.press("Escape"); st.wait_for_selector("dialog.dlg", state="detached")
        ok("v0.8.34: closing the viewer returns focus to the button", st.evaluate("document.activeElement.dataset.do") == "dlMat")
        an = b.new_context(viewport={"width": 390, "height": 800}, user_agent="Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36").new_page()
        an.on("pageerror", lambda x: errs.append(str(x)))
        e2e_shim.login(an, B, "student@baleegh.test", "ChangeMe-Stud1", db=env["DATABASE_PATH"], batch=1)
        an.goto(B + "/#materials"); an.wait_for_selector(f"[data-do=dlMat][data-id='{mid}']"); an.click(f"[data-do=dlMat][data-id='{mid}']"); an.wait_for_selector("dialog.dlg.view[open]")
        ok("v0.8.34: on Android the viewer says PDFs cannot show here and offers Download", an.locator("dialog.dlg.view[open] .fv-pdf").count() == 0 and an.is_visible("dialog.dlg.view[open] a[download]"))
        # admin: storage panel in Settings, missing-file check
        a.goto(B + "/#settings"); a.wait_for_selector("#storep")
        ok("v0.8.34: Settings shows Files and storage", "Where files are kept" in a.inner_text("#storep"))
        a.click("[data-do=stCheck]"); a.wait_for_selector("#storep .msg.ok, #storep table:not(.kv)")
        ok("v0.8.34: the missing-files check runs", "files are there" in a.inner_text("#storep") or "no longer stored" in a.inner_text("#storep"))
        # ---- v0.8.35: Forgot password, admin To do, teacher Today, student What to do next ----
        fp = page(390, 800); fp.goto(B + "/"); fp.wait_for_selector("#forgotBtn"); fp.click("#forgotBtn")
        api("/users", {"full_name": "Forgetful Student", "email": "forget@u.test", "password": "Password123", "role": "student", "phone": "7779999"}, adm)
        fp.fill("#fg_l", "forget@u.test"); fp.click("#ffg button:not([type=button])"); fp.wait_for_selector(".msg.ok")
        ok("v0.8.35: Forgot password sends a request and says so", "academy has been told" in fp.inner_text(".msg.ok"))
        a.goto(B + "/#people"); a.wait_for_selector("[data-do=phReset]")
        ok("v0.8.35: People shows the password help request", "Password help" in a.inner_text("main"))
        a.click("[data-do=phReset]"); e2e_shim.dialog(a); a.wait_for_selector("text=Temporary password")
        a.wait_for_selector("main a[href^='https://wa.me/9607779999']")
        ok("v0.8.35: Reset and send shows the password and a WhatsApp button with the person's number", "Forgetful Student" in a.inner_text("main"))
        a.goto(B + "/#dashboard"); a.wait_for_selector("#todop")
        ok("v0.8.35: the admin Dashboard starts with To do today", a.evaluate("document.querySelector('#todop').previousElementSibling.tagName") in ("H1", "DIV"))
        th = page(390, 800); e2e_shim.login(th, B, "teacher@baleegh.test", "ChangeMe-Teach1", db=env["DATABASE_PATH"], batch=1)
        th.goto(B + "/#home"); th.wait_for_selector("#todayp")
        ok("v0.8.35: the teacher Home starts with Today", "Today" in th.inner_text("#todayp"))
        sh = page(390, 800); e2e_shim.login(sh, B, "student@baleegh.test", "ChangeMe-Stud1", db=env["DATABASE_PATH"], batch=1)
        sh.goto(B + "/#home"); sh.wait_for_selector("#nextp")
        ok("v0.8.35: the student Home has What to do next", "What to do next" in sh.inner_text("#nextp"))
        if sh.locator("#nextp [data-do=goA]").count():
            sh.click("#nextp [data-do=goA]"); sh.wait_for_selector("[data-do=backA]")
            ok("v0.8.35: Hand in opens the assignment", True)
        ok("no script errors", not errs, errs[:3])
        b.close()
finally:
    srv.terminate()
print("\n%d failure(s)" % len(fails)); sys.exit(1 if fails else 0)
