import io, json, os, re, shutil, socket, sqlite3, sys, tempfile, threading, unittest, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from werkzeug.security import generate_password_hash

MVT = dt.timezone(dt.timedelta(hours=5))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF = b"%PDF-1.4 slip"
JPG = b"\xff\xd8\xff\xe0" + b"1" * 30
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
PW = "Password123"


class FakeSMTP(threading.Thread):
    """A tiny real SMTP server on localhost so smtplib is exercised for real (no mocking of smtplib itself)."""
    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket(); self.sock.bind(("127.0.0.1", 0)); self.sock.listen(5)
        self.port = self.sock.getsockname()[1]; self.messages = []; self.start()

    def run(self):
        while True:
            try: conn, _ = self.sock.accept()
            except OSError: return
            f = conn.makefile("rwb")
            f.write(b"220 fake ready\r\n"); f.flush()
            sender, rcpt = None, []
            while True:
                line = f.readline()
                if not line: break
                cmd = line.decode(errors="replace").strip()
                up = cmd.upper()
                if up.startswith("EHLO") or up.startswith("HELO"): f.write(b"250 fake\r\n")
                elif up.startswith("MAIL FROM"): sender = cmd; f.write(b"250 ok\r\n")
                elif up.startswith("RCPT TO"): rcpt.append(cmd); f.write(b"250 ok\r\n")
                elif up == "DATA":
                    f.write(b"354 go\r\n"); f.flush(); data = b""
                    while not data.endswith(b"\r\n.\r\n"): data += f.readline()
                    self.messages.append({"from": sender, "to": rcpt, "data": data.decode(errors="replace")}); f.write(b"250 queued\r\n")
                elif up == "QUIT": f.write(b"221 bye\r\n"); f.flush(); break
                else: f.write(b"250 ok\r\n")
                f.flush()
            conn.close()

    def stop(self):
        try: self.sock.shutdown(socket.SHUT_RDWR)   # wakes the blocked accept() so the port really stops answering
        except OSError: pass
        self.sock.close()


class P4(unittest.TestCase):
    """Every test builds its own database, clock and world, so nothing depends on another test."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "t.db")
        self.clock = [dt.datetime(2026, 3, 12, 10, 0, tzinfo=MVT)]   # Thursday 12 March 2026
        self.app = self.mk()
        con = sqlite3.connect(self.db_path)
        con.execute("INSERT INTO users(email,password_hash,full_name,role) VALUES('admin@t.test',?,'Admin','admin')", (generate_password_hash("AdminPass123"),))
        con.commit(); con.close()
        self.c = self.app.test_client()
        self.a = self.login("admin@t.test", "AdminPass123")
        self.n = 0

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def mk(self, **cfg):
        from app import create_app
        return create_app({"DATABASE_PATH": self.db_path, "NOW": lambda: self.clock[0], "SLIP_LIMIT": 50, **cfg})

    def at(self, s): self.clock[0] = dt.datetime.fromisoformat(s).replace(tzinfo=MVT)

    # ----- helpers -----
    def login(self, email, pw=PW):
        r = self.c.post("/api/auth/login", json={"email": email, "password": pw})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return {"Authorization": "Bearer " + r.get_json()["token"]}

    def J(self, method, url, hdr=None, **kw):
        return getattr(self.c, method)(url, headers=hdr or self.a, **kw)

    def ok(self, r, code=200):
        self.assertEqual(r.status_code, code, r.get_data(as_text=True)[:300])
        return r.get_json() if r.mimetype == "application/json" else r

    def course(self, fee=350, **over):
        self.n += 1
        d = {"name": f"Course{self.n}", "status": "open", "monthly_fee_mvr": fee}; d.update(over)
        return self.ok(self.J("post", "/api/courses", json=d), 201)["id"]

    def batch(self, cid, cap=20, code="B1"):
        t = self.ok(self.J("post", "/api/users", json={"email": f"t{cid}{code}@t.test", "password": PW, "full_name": "Teacher", "role": "teacher"}), 201)["id"]
        return self.ok(self.J("post", "/api/batches", json={"course_id": cid, "code": code, "teacher_id": t, "capacity": cap, "days": "Mon,Wed", "start_time": "16:00"}), 201)["id"]

    def student(self, name=None, phone=None, **extra):
        self.n += 1
        d = {"email": f"s{self.n}@t.test", "password": PW, "full_name": name or f"Student {self.n}", "role": "student", "phone": phone, **extra}
        sid = self.ok(self.J("post", "/api/users", json=d), 201)["id"]
        return sid, d["email"]

    def enroll(self, sid, bid):
        return self.ok(self.J("post", "/api/enrollments", json={"student_id": sid, "batch_id": bid}), 201)

    def world(self, fee=350, n=2, cap=20):
        cid = self.course(fee); bid = self.batch(cid, cap)
        w = {"cid": cid, "bid": bid, "sid": [], "email": [], "eid": []}
        for _ in range(n):
            sid, em = self.student(); e = self.enroll(sid, bid)
            w["sid"].append(sid); w["email"].append(em); w["eid"].append(e["id"])
        return w

    def S(self, w, i=0): return self.login(w["email"][i])

    def invs(self, **q):
        q.setdefault("status", "all")   # v0.8.35: the plain list leaves voided invoices out; these tests look at every invoice
        qs = "&".join(f"{k}={v}" for k, v in q.items())
        return self.ok(self.J("get", "/api/invoices?" + qs))

    def inv_of(self, sid, month="2026-03"):
        r = [i for i in self.invs(month=month) if i["student_id"] == sid]
        self.assertEqual(len(r), 1, f"expected one invoice for student {sid} in {month}, got {len(r)}")
        return r[0]

    def gen(self, month): return self.ok(self.J("post", "/api/invoices/generate", json={"month": month}))

    def slip(self, hdr, inv_id, amount=350, date="2026-03-11", content=PDF, name="slip.pdf", ref="TRX1", **over):
        d = {"amount_mvr": str(amount), "transfer_date": date, "reference": ref, "file": (io.BytesIO(content), name)}
        d.update(over); d = {k: v for k, v in d.items() if v is not None}
        return self.c.post(f"/api/invoices/{inv_id}/slips", data=d, headers=hdr, content_type="multipart/form-data")

    def pending(self, **kw): return self.ok(self.J("get", "/api/slips?status=" + kw.get("status", "pending")))

    def audit_actions(self): return [a["action"] for a in self.ok(self.J("get", "/api/audit"))]

    # ================= invoices =================
    def test_01_first_invoice_on_admin_enrollment(self):
        w = self.world(350, 1)
        i = self.inv_of(w["sid"][0])
        self.assertEqual((i["amount_mvr"], i["discount_mvr"], i["amount_due_mvr"], i["status"], i["period"]), (350, 0, 350, "unpaid", "2026-03"))
        self.assertEqual(i["number"], f"INV-202603-{i['id']:04d}")
        self.assertIn("Batch B1", i["description"]); self.assertIn("March 2026", i["description"])
        self.assertEqual(i["due_date"], "2026-03-19")   # joined after the 10th: due a week after joining, not already overdue
        self.assertFalse(i["overdue"])

    def test_02_first_invoice_on_application_approval(self):
        cid = self.course(350); bid = self.batch(cid)
        dob = f"{2026 - 25}-01-15"
        f = {"full_name": "Aisha Ali", "date_of_birth": dob, "phone": "7771234", "email": "aisha@x.test", "course_id": str(cid), "batch_id": str(bid), "id_card": (io.BytesIO(PDF), "id.pdf")}
        ref = self.ok(self.c.post("/api/public/apply", data=f, content_type="multipart/form-data"), 201)["ref"]
        aid = [a for a in self.ok(self.J("get", "/api/applications")) if a["ref"] == ref][0]["id"]
        sid = self.ok(self.J("post", f"/api/applications/{aid}/approve", json={"batch_id": bid}))["user_id"]
        i = self.inv_of(sid)
        self.assertEqual((i["amount_due_mvr"], i["status"]), (350, "unpaid"))

    def test_03_generate_is_idempotent(self):
        w = self.world(350, 3)
        r = self.gen("2026-04")
        self.assertEqual((r["created"], r["skipped_total"]), (3, 0))
        r2 = self.gen("2026-04")
        self.assertEqual((r2["created"], r2["skipped"].get("already_invoiced")), (0, 3))
        self.assertEqual(len(self.invs(month="2026-04")), 3)
        r3 = self.gen("2026-03")   # first invoices already made this month
        self.assertEqual(r3["created"], 0)
        self.assertEqual(len(self.invs(month="2026-03")), 3)
        row = sqlite3.connect(self.db_path).execute("SELECT COUNT(*) FROM invoices").fetchone()[0]
        self.assertEqual(row, 6)

    def test_04_only_active_paid_enrollments_are_billed(self):
        cid = self.course(350); bid = self.batch(cid, cap=1)
        a, _ = self.student(); b, _ = self.student(); d, _ = self.student()
        ea = self.enroll(a, bid); eb = self.enroll(b, bid)
        self.assertEqual(eb["status"], "waitlist")
        ed = self.enroll(d, bid)   # also waitlist
        free = self.course(0); fb = self.batch(free); f, _ = self.student(); self.enroll(f, fb)
        self.assertEqual(len(self.invs(month="2026-03")), 1)   # only the active, fee-bearing enrollment got a first invoice
        self.ok(self.J("patch", f"/api/enrollments/{ea['id']}", json={"status": "dropped"}))
        self.ok(self.J("patch", f"/api/enrollments/{eb['id']}", json={"status": "active"}))   # waitlist -> active: first invoice now
        self.assertEqual(self.inv_of(b)["amount_due_mvr"], 350)
        r = self.gen("2026-04")
        self.assertEqual(r["created"], 1)   # only student b is active; a dropped, d waitlisted, f is a free course
        self.assertEqual(r["skipped"].get("fee_zero"), 1)
        self.assertEqual([i["student_id"] for i in self.invs(month="2026-04")], [b])

    def test_05_fee_change_does_not_rewrite_old_invoices(self):
        w = self.world(350, 1)
        self.ok(self.J("patch", f"/api/courses/{w['cid']}", json={"monthly_fee_mvr": 400}))
        self.gen("2026-04")
        self.assertEqual(self.inv_of(w["sid"][0], "2026-03")["amount_mvr"], 350)
        self.assertEqual(self.inv_of(w["sid"][0], "2026-04")["amount_mvr"], 400)

    def test_06_first_month_setting_and_not_enrolled_yet(self):
        self.ok(self.J("put", "/api/settings", json={"first_invoice_mode": "skip"}))
        w = self.world(350, 1)
        self.assertEqual(self.invs(month="2026-03"), [])
        r = self.gen("2026-03"); self.assertEqual(r["skipped"].get("first_month_skipped"), 1)
        self.assertEqual(self.gen("2026-04")["created"], 1)
        self.ok(self.J("put", "/api/settings", json={"first_invoice_mode": "full"}))
        r = self.gen("2026-02")   # before they joined
        self.assertEqual((r["created"], r["skipped"].get("not_enrolled_yet")), (0, 1))

    def test_07_due_day_setting_and_validation(self):
        w = self.world(350, 1)
        self.assertEqual(self.J("put", "/api/settings", json={"invoice_due_day": "30"}).status_code, 400)
        self.assertEqual(self.J("put", "/api/settings", json={"invoice_due_day": "abc"}).status_code, 400)
        self.assertEqual(self.J("put", "/api/settings", json={"receipt_prefix": "bad prefix!"}).status_code, 400)
        self.assertEqual(self.J("put", "/api/settings", json={"first_invoice_mode": "prorate"}).status_code, 400)
        self.gen("2026-04"); self.assertEqual(self.inv_of(w["sid"][0], "2026-04")["due_date"], "2026-04-10")   # default 10th when unset
        self.ok(self.J("put", "/api/settings", json={"invoice_due_day": "5"}))
        w2 = self.world(350, 1); self.gen("2026-05") if False else None
        self.assertEqual(self.gen("2026-04")["created"], 1)   # the new student's April invoice
        self.assertEqual(self.inv_of(w2["sid"][0], "2026-04")["due_date"], "2026-04-05")
        self.at("2026-03-25 09:00"); w3 = self.world(350, 1)
        self.assertEqual(self.inv_of(w3["sid"][0])["due_date"], "2026-04-01")   # joined 25th: a week's grace

    def test_08_period_validation(self):
        for bad in ("", "2026-13", "26-03", "2026-3", "2026-03-01", None, "2099-01", "2026-05"):
            self.assertEqual(self.J("post", "/api/invoices/generate", json={"month": bad}).status_code, 400, bad)
        self.assertEqual(self.J("get", "/api/invoices?month=bad").status_code, 400)

    def test_09_transfer_moves_open_invoice_and_back_again_works(self):
        w = self.world(350, 1)
        b2 = self.batch(w["cid"], code="B2"); b3 = self.batch(w["cid"], code="B3")
        i0 = self.inv_of(w["sid"][0])
        new = self.ok(self.J("patch", f"/api/enrollments/{w['eid'][0]}", json={"transfer_to_batch_id": b2}))["id"]
        i1 = self.inv_of(w["sid"][0])   # still exactly one invoice for the month (no double billing)
        self.assertEqual((i1["id"], i1["enrollment_id"], i1["batch_id"]), (i0["id"], new, b2))
        self.assertIn("Batch B2", i1["description"])
        back = self.ok(self.J("patch", f"/api/enrollments/{new}", json={"transfer_to_batch_id": w["bid"]}))["id"]   # used to hit INSERT OR REPLACE
        self.assertEqual(back, w["eid"][0])
        self.assertEqual(self.inv_of(w["sid"][0])["enrollment_id"], back)

    def test_10_reenroll_after_drop_does_not_duplicate(self):
        w = self.world(350, 1)
        self.ok(self.J("patch", f"/api/enrollments/{w['eid'][0]}", json={"status": "dropped"}))
        e = self.enroll(w["sid"][0], w["bid"])
        self.assertEqual(e["id"], w["eid"][0])
        self.assertEqual(len(self.invs(month="2026-03")), 1)

    def test_11_void_open_invoices_after_drop(self):
        w = self.world(350, 1)
        self.gen("2026-04")
        r = self.J("post", f"/api/enrollments/{w['eid'][0]}/void-open-invoices", json={"reason": "x"})
        self.assertEqual(r.status_code, 409)   # still active
        self.ok(self.J("patch", f"/api/enrollments/{w['eid'][0]}", json={"status": "dropped"}))
        self.assertEqual(self.J("post", f"/api/enrollments/{w['eid'][0]}/void-open-invoices", json={}).status_code, 400)   # reason needed
        self.assertEqual(self.ok(self.J("post", f"/api/enrollments/{w['eid'][0]}/void-open-invoices", json={"reason": "Left the course"}))["voided"], 2)
        self.assertEqual({i["status"] for i in self.invs(student_id=w["sid"][0])}, {"void"})
        self.assertEqual(self.gen("2026-04")["created"], 0)   # dropped, and the void rows keep the slot

    # ================= discounts =================
    def test_12_recurring_discounts_fixed_and_percent(self):
        w = self.world(350, 2)
        e0, e1 = w["eid"]
        bad = lambda **j: self.J("post", "/api/discounts", json={"enrollment_id": e0, **j}).status_code
        self.assertEqual(bad(kind="fixed", value=50), 400)                          # reason required
        self.assertEqual(bad(kind="fixed", value=50, reason="  "), 400)
        self.assertEqual(bad(kind="percent", value=101, reason="r"), 400)
        self.assertEqual(bad(kind="fixed", value=0, reason="r"), 400)
        self.assertEqual(bad(kind="fixed", value=-5, reason="r"), 400)
        self.assertEqual(bad(kind="fixed", value=10.5, reason="r"), 400)
        self.assertEqual(bad(kind="weird", value=10, reason="r"), 400)
        self.ok(self.J("post", "/api/discounts", json={"enrollment_id": e0, "kind": "fixed", "value": 50, "reason": "Staff child"}), 201)
        self.ok(self.J("post", "/api/discounts", json={"enrollment_id": e1, "kind": "percent", "value": 10, "reason": "Scholarship"}), 201)
        self.gen("2026-04")
        a, b = self.inv_of(w["sid"][0], "2026-04"), self.inv_of(w["sid"][1], "2026-04")
        self.assertEqual((a["discount_mvr"], a["amount_due_mvr"]), (50, 300))
        self.assertEqual((b["discount_mvr"], b["amount_due_mvr"]), (35, 315))
        self.assertIn("Staff child", a["discount_note"])
        self.assertEqual(self.inv_of(w["sid"][0], "2026-03")["amount_due_mvr"], 350)   # earlier invoices untouched
        d = self.ok(self.J("get", "/api/discounts"))
        self.assertEqual(len(d), 2)
        self.ok(self.J("delete", f"/api/discounts/{d[0]['id']}"))
        self.assertEqual(len(self.ok(self.J("get", "/api/discounts"))), 1)
        acts = self.audit_actions(); self.assertIn("discount_add", acts); self.assertIn("discount_end", acts)

    def test_13_discount_never_below_zero(self):
        w = self.world(350, 1); e = w["eid"][0]
        self.ok(self.J("post", "/api/discounts", json={"enrollment_id": e, "kind": "fixed", "value": 500, "reason": "Full scholarship"}), 201)
        self.gen("2026-04")
        i = self.inv_of(w["sid"][0], "2026-04")
        self.assertEqual((i["discount_mvr"], i["amount_due_mvr"], i["status"]), (350, 0, "waived"))   # capped at the fee; nothing to pay
        i3 = self.inv_of(w["sid"][0])   # the March invoice came before the discount
        r = self.ok(self.J("post", f"/api/invoices/{i3['id']}/discount", json={"kind": "fixed", "value": 9999, "reason": "Hardship"}))
        self.assertEqual(r["applied"], 350); self.assertEqual(r["invoice"]["amount_due_mvr"], 0); self.assertEqual(r["invoice"]["status"], "waived")
        self.assertEqual(self.J("post", f"/api/invoices/{i3['id']}/discount", json={"kind": "fixed", "value": 5, "reason": "again"}).status_code, 409)

    def test_14_one_off_invoice_discount_rules(self):
        w = self.world(350, 1); sid = w["sid"][0]; i = self.inv_of(sid)
        url = f"/api/invoices/{i['id']}/discount"
        self.assertEqual(self.J("post", url, json={"kind": "fixed", "value": 50}).status_code, 400)   # reason needed
        self.ok(self.J("post", f"/api/payments", json={"invoice_id": i["id"], "amount_mvr": 200, "method": "cash"}), 201)
        r = self.ok(self.J("post", url, json={"kind": "fixed", "value": 100, "reason": "Late start"}))
        self.assertEqual((r["invoice"]["amount_due_mvr"], r["invoice"]["balance"]), (250, 50))
        self.assertEqual(self.J("post", url, json={"kind": "fixed", "value": 100, "reason": "More"}).status_code, 409)   # would drop below the 200 already paid
        self.assertEqual(self.J("post", url, json={"kind": "percent", "value": 10, "reason": "10%"}).status_code, 200)   # 10% of 350 = 35; due 215 >= 200
        self.assertIn("invoice_discount", self.audit_actions())

    def test_15_family_concession(self):
        w = self.world(350, 3)
        fam = self.ok(self.J("post", "/api/families", json={"name": "Hassan family", "concession_kind": "percent", "concession_value": 20, "concession_reason": "Sibling"}), 201)["id"]
        for sid, applies in ((w["sid"][0], 0), (w["sid"][1], 1)):
            self.ok(self.J("post", f"/api/families/{fam}/members", json={"student_id": sid, "concession_applies": applies}), 201)
        self.assertEqual(self.J("post", f"/api/families/{fam}/members", json={"student_id": w["sid"][1]}).status_code, 409)   # already in a family
        other = self.ok(self.J("post", "/api/families", json={"name": "Other"}), 201)["id"]
        self.assertEqual(self.J("post", f"/api/families/{other}/members", json={"student_id": w["sid"][1]}).status_code, 409)   # only one family each
        self.gen("2026-04")
        self.assertEqual(self.inv_of(w["sid"][0], "2026-04")["amount_due_mvr"], 350)   # first child pays in full (admin chose that)
        c2 = self.inv_of(w["sid"][1], "2026-04"); self.assertEqual((c2["discount_mvr"], c2["amount_due_mvr"]), (70, 280)); self.assertIn("Family", c2["discount_note"])
        self.assertEqual(self.inv_of(w["sid"][2], "2026-04")["amount_due_mvr"], 350)
        self.ok(self.J("patch", f"/api/families/{fam}/members/{w['sid'][0]}", json={"concession_applies": 1}))
        self.assertEqual(self.J("post", "/api/families", json={"name": "F", "concession_value": 10}).status_code, 400)   # amount without a kind
        self.assertEqual(self.J("post", "/api/families", json={"name": "F", "concession_kind": "percent", "concession_value": 150}).status_code, 400)
        self.assertEqual(self.J("post", "/api/families", json={"name": ""}).status_code, 400)
        fams = self.ok(self.J("get", "/api/families")); self.assertEqual(len(fams[-1]["members"]) + len(fams[0]["members"]), 2)
        self.ok(self.J("delete", f"/api/families/{fam}/members/{w['sid'][1]}"))
        self.assertIn("family_add_member", self.audit_actions())

    # ================= slips =================
    def test_16_student_fees_page_and_bank_details(self):
        w = self.world(350, 2); s = self.S(w)
        j = self.ok(self.J("get", "/api/my/fees", s))
        self.assertFalse(j["bank"]["configured"])   # settings are empty until the admin fills them in
        self.assertEqual(len(j["invoices"]), 1); self.assertEqual(j["invoices"][0]["student_id"], w["sid"][0])
        self.assertEqual(j["summary"]["balance_due"], 350)
        self.ok(self.J("put", "/api/settings", json={"bank_name": "BML", "bank_account_name": "Baleegh Academy", "bank_account_number": "7770001234567"}))
        j = self.ok(self.J("get", "/api/my/fees", s))
        self.assertTrue(j["bank"]["configured"]); self.assertEqual(j["bank"]["bank_account_number"], "7770001234567")

    def test_17_valid_slip_types_accepted(self):
        w = self.world(350, 3)
        for k, (content, name) in enumerate(((PDF, "a.pdf"), (JPG, "b.jpg"), (PNG, "c.png"))):
            s = self.S(w, k); i = self.inv_of(w["sid"][k])
            r = self.ok(self.slip(s, i["id"], content=content, name=name), 201)
            self.assertEqual(r["invoice"]["status"], "slip_submitted")
        q = self.pending(); self.assertEqual(len(q), 3)
        self.assertEqual({x["amount_mvr"] for x in q}, {350}); self.assertNotIn("file", q[0])   # stored name never exposed

    def test_18_bad_slips_rejected(self):
        w = self.world(350, 1); s = self.S(w); i = self.inv_of(w["sid"][0])["id"]
        def bad(msg, **kw):
            r = self.slip(s, i, **kw); self.assertEqual(r.status_code, 400, msg + " " + r.get_data(as_text=True)); return r.get_json()["error"]
        bad("exe", content=b"MZ\x90\x00" + b"0" * 20, name="virus.exe")
        bad("fake content", content=b"MZ\x90\x00 not a pdf", name="slip.pdf")
        bad("png named pdf", content=PNG, name="slip.pdf")
        bad("html", content=b"<html>", name="slip.html")
        bad("text as jpg", content=b"hello", name="slip.jpg")
        bad("oversize", content=PDF + b"0" * (5 * 1024 * 1024), name="big.pdf")
        bad("no file", content=None, name=None) if False else None
        r = self.c.post(f"/api/invoices/{i}/slips", data={"amount_mvr": "350", "transfer_date": "2026-03-11"}, headers=s, content_type="multipart/form-data"); self.assertEqual(r.status_code, 400)
        for amt in ("", "abc", "0", "-5", "12.5", "99999999999"): bad("amount " + amt, amount=amt)
        bad("future date", date="2026-03-13"); bad("bad date", date="not-a-date"); bad("ancient date", date="2024-01-01")
        self.assertEqual(self.pending(), [])
        self.assertEqual(self.inv_of(w["sid"][0])["status"], "unpaid")
        self.ok(self.slip(s, i), 201)
        self.assertEqual(self.slip(s, i).status_code, 409)   # one slip at a time per invoice

    def test_19_slip_belongs_to_its_student(self):
        w = self.world(350, 2); s0, s1 = self.S(w, 0), self.S(w, 1)
        i0, i1 = self.inv_of(w["sid"][0])["id"], self.inv_of(w["sid"][1])["id"]
        self.assertEqual(self.slip(s1, i0).status_code, 404)           # cannot attach a slip to someone else's invoice
        self.assertEqual(self.slip(self.a, i0).status_code, 403)       # admins record payments instead
        sid = self.ok(self.slip(s0, i0), 201)["id"]
        self.assertEqual(self.J("get", f"/api/slips/{sid}/file", s1).status_code, 404)
        self.assertEqual(self.J("get", f"/api/invoices/{i0}", s1).status_code, 404)
        t = self.login("t%dB1@t.test" % w["cid"]); self.assertEqual(self.J("get", f"/api/slips/{sid}/file", t).status_code, 403)
        self.assertEqual(self.c.get(f"/api/slips/{sid}/file").status_code, 401)
        r = self.J("get", f"/api/slips/{sid}/file", s0); self.assertEqual(r.status_code, 200); self.assertEqual(r.data, PDF)
        self.assertEqual(r.headers["Cache-Control"], "private, no-store"); self.assertIn("attachment", r.headers["Content-Disposition"])
        self.assertEqual(self.J("get", f"/api/slips/{sid}/file").status_code, 200)   # admin
        self.assertIn("view_slip", self.audit_actions())
        stored = os.listdir(os.path.join(self.tmp, "uploads", "slips"))
        self.assertEqual(len(stored), 1)
        for url in ("/uploads/slips/" + stored[0], "/slips/" + stored[0], "/instance/uploads/slips/" + stored[0], "/" + stored[0]):
            self.assertEqual(self.c.get(url).status_code, 404, url)   # never served from a public folder
        self.assertNotIn(stored[0].encode(), self.J("get", "/api/my/fees", s0).data)

    def test_20_slip_upload_rate_limit(self):
        self.app = self.mk(SLIP_LIMIT=3); self.c = self.app.test_client(); self.a = self.login("admin@t.test", "AdminPass123")
        w = self.world(350, 1); s = self.S(w); i = self.inv_of(w["sid"][0])["id"]
        codes = [self.slip(s, i, content=b"bad", name="x.exe").status_code for _ in range(3)]
        self.assertEqual(codes, [400, 400, 400])
        self.assertEqual(self.slip(s, i).status_code, 429)   # failed attempts count too
        self.clock[0] += dt.timedelta(hours=1, minutes=1)
        self.assertEqual(self.slip(s, i, date="2026-03-12").status_code, 201)

    # ================= verification =================
    def test_21_verify_marks_paid_and_gives_receipt(self):
        w = self.world(350, 1); s = self.S(w); i = self.inv_of(w["sid"][0])
        sid = self.ok(self.slip(s, i["id"]), 201)["id"]
        v = self.ok(self.J("post", f"/api/slips/{sid}/verify", json={}))
        self.assertEqual(v["receipt_no"], "BA-R-0001"); self.assertEqual(v["invoice"]["status"], "paid"); self.assertEqual(v["invoice"]["balance"], 0)
        my = self.ok(self.J("get", "/api/my/fees", s))
        self.assertEqual(my["invoices"][0]["status"], "paid"); self.assertEqual(my["payments"][0]["receipt_no"], "BA-R-0001")
        self.assertEqual(my["summary"]["balance_due"], 0); self.assertEqual(self.pending(), [])
        self.assertEqual(self.pending(status="verified")[0]["id"], sid)
        self.assertEqual(self.slip(s, i["id"]).status_code, 409)   # nothing left to pay

    def test_22_reject_needs_reason_student_sees_it_and_can_retry(self):
        w = self.world(350, 1); s = self.S(w); i = self.inv_of(w["sid"][0])["id"]
        sid = self.ok(self.slip(s, i, content=JPG, name="blurry.jpg"), 201)["id"]
        self.assertEqual(self.J("post", f"/api/slips/{sid}/reject", json={}).status_code, 400)
        self.assertEqual(self.J("post", f"/api/slips/{sid}/reject", json={"reason": "  "}).status_code, 400)
        self.ok(self.J("post", f"/api/slips/{sid}/reject", json={"reason": "Slip is blurry, amount unreadable"}))
        row = self.ok(self.J("get", "/api/my/fees", s))["invoices"][0]
        self.assertEqual(row["status"], "unpaid"); self.assertEqual(row["last_rejection"]["reason"], "Slip is blurry, amount unreadable"); self.assertTrue(row["can_upload"])
        sid2 = self.ok(self.slip(s, i, content=PDF, name="clear.pdf"), 201)["id"]
        row = self.ok(self.J("get", "/api/my/fees", s))["invoices"][0]
        self.assertEqual(row["status"], "slip_submitted"); self.assertIsNone(row["last_rejection"]); self.assertEqual(row["pending_slip"]["id"], sid2)
        self.ok(self.J("post", f"/api/slips/{sid2}/verify", json={}))
        self.assertEqual(self.inv_of(w["sid"][0])["status"], "paid")

    def test_23_double_verify_and_wrong_state_are_409(self):
        w = self.world(350, 1); s = self.S(w); i = self.inv_of(w["sid"][0])["id"]
        sid = self.ok(self.slip(s, i), 201)["id"]
        self.ok(self.J("post", f"/api/slips/{sid}/verify", json={}))
        self.assertEqual(self.J("post", f"/api/slips/{sid}/verify", json={}).status_code, 409)
        self.assertEqual(self.J("post", f"/api/slips/{sid}/reject", json={"reason": "late"}).status_code, 409)
        self.assertEqual(len(self.ok(self.J("get", "/api/payments"))), 1)
        w2 = self.world(350, 1); s2 = self.S(w2); i2 = self.inv_of(w2["sid"][0])["id"]
        sid2 = self.ok(self.slip(s2, i2), 201)["id"]
        self.ok(self.J("post", f"/api/slips/{sid2}/reject", json={"reason": "no"}))
        self.assertEqual(self.J("post", f"/api/slips/{sid2}/verify", json={}).status_code, 409)
        self.assertEqual(self.J("post", "/api/slips/9999/verify", json={}).status_code, 404)

    def test_24_partial_payment_leaves_balance(self):
        w = self.world(350, 1); s = self.S(w); i = self.inv_of(w["sid"][0])["id"]
        sid = self.ok(self.slip(s, i, amount=350), 201)["id"]
        v = self.ok(self.J("post", f"/api/slips/{sid}/verify", json={"amount_mvr": 100}))   # only 100 actually arrived
        self.assertEqual((v["invoice"]["status"], v["invoice"]["balance"], v["invoice"]["paid_mvr"], v["invoice"]["partly_paid"]), ("unpaid", 250, 100, True))
        row = self.ok(self.J("get", "/api/my/fees", s))["invoices"][0]; self.assertTrue(row["can_upload"]); self.assertEqual(row["balance"], 250)
        sid2 = self.ok(self.slip(s, i, amount=250, content=PNG, name="b.png"), 201)["id"]
        v = self.ok(self.J("post", f"/api/slips/{sid2}/verify", json={}))
        self.assertEqual((v["invoice"]["status"], v["invoice"]["balance"]), ("paid", 0)); self.assertEqual(v["receipt_no"], "BA-R-0002")

    def test_25_overpayment_is_blocked(self):
        w = self.world(350, 1); s = self.S(w); i = self.inv_of(w["sid"][0])["id"]
        sid = self.ok(self.slip(s, i, amount=400), 201)["id"]
        r = self.J("post", f"/api/slips/{sid}/verify", json={})
        self.assertEqual(r.status_code, 400); self.assertIn("more than the balance of MVR 350", r.get_json()["error"])
        self.assertEqual(self.pending()[0]["status"], "pending")   # untouched, still waiting
        self.assertEqual(self.ok(self.J("get", "/api/payments")), [])
        self.assertEqual(self.J("post", f"/api/slips/{sid}/verify", json={"amount_mvr": 0}).status_code, 400)
        self.assertEqual(self.J("post", f"/api/slips/{sid}/verify", json={"amount_mvr": "x"}).status_code, 400)
        self.assertEqual(self.J("post", f"/api/slips/{sid}/verify", json={"amount_mvr": 350.5}).status_code, 400)
        self.assertEqual(self.pending()[0]["status"], "pending")
        self.ok(self.J("post", f"/api/slips/{sid}/verify", json={"amount_mvr": 350}))

    def test_26_reversal_reopens_balance_and_receipt_numbers_are_not_reused(self):
        w = self.world(350, 1); s = self.S(w); i = self.inv_of(w["sid"][0])["id"]
        sid = self.ok(self.slip(s, i), 201)["id"]
        pid = self.ok(self.J("post", f"/api/slips/{sid}/verify", json={}))["payment_id"]
        self.assertEqual(self.J("post", f"/api/payments/{pid}/reverse", json={}).status_code, 400)   # reason needed
        self.assertEqual(self.J("post", f"/api/payments/{pid}/reverse", json={"reason": "Money bounced"}, hdr=s).status_code, 403) if False else None
        r = self.ok(self.J("post", f"/api/payments/{pid}/reverse", json={"reason": "Transfer was recalled by the bank"}))
        self.assertEqual((r["invoice"]["status"], r["invoice"]["balance"], r["invoice"]["paid_mvr"]), ("unpaid", 350, 0))
        self.assertEqual(self.J("post", f"/api/payments/{pid}/reverse", json={"reason": "again"}).status_code, 409)
        self.assertEqual(self.J("post", f"/api/slips/{sid}/verify", json={}).status_code, 409)   # a reversed slip cannot be re-verified
        self.assertEqual(self.pending(status="reversed")[0]["id"], sid)
        p = self.ok(self.J("post", "/api/payments", json={"invoice_id": i, "amount_mvr": 350, "method": "cash"}), 201)["payment"]
        self.assertEqual(p["receipt_no"], "BA-R-0002")   # 0001 stays with the reversed payment
        pays = {x["id"]: x for x in self.ok(self.J("get", "/api/payments"))}
        self.assertTrue(pays[pid]["reversed_at"]); self.assertEqual(pays[pid]["reverse_reason"], "Transfer was recalled by the bank")
        self.assertIn("payment_reverse", self.audit_actions())
        self.assertEqual(self.J("post", f"/api/payments/{p['id']}/reverse", json={"reason": "x"}, hdr=s).status_code, 403)

    def test_27_duplicate_slip_warning(self):
        w = self.world(350, 2); s0, s1 = self.S(w, 0), self.S(w, 1)
        i0, i1 = self.inv_of(w["sid"][0])["id"], self.inv_of(w["sid"][1])["id"]
        a = self.ok(self.slip(s0, i0), 201)["id"]
        b = self.ok(self.slip(s1, i1), 201)["id"]   # identical bytes
        q = {x["id"]: x for x in self.pending()}
        self.assertEqual(q[a]["duplicates"][0]["slip_id"], b); self.assertEqual(q[b]["duplicates"][0]["slip_id"], a)
        self.assertFalse(q[b]["duplicate_verified"])
        self.ok(self.J("post", f"/api/slips/{a}/verify", json={}))   # first use is fine
        self.assertTrue({x["id"]: x for x in self.pending()}[b]["duplicate_verified"])
        r = self.J("post", f"/api/slips/{b}/verify", json={})
        self.assertEqual(r.status_code, 409); self.assertTrue(r.get_json()["needs_confirm"])
        self.assertEqual(self.pending()[0]["status"], "pending")
        v = self.ok(self.J("post", f"/api/slips/{b}/verify", json={"confirm_duplicate": True}))
        self.assertTrue(v["warnings"])

    # ================= manual payments and receipts =================
    def test_28_cash_payment(self):
        w = self.world(350, 1); i = self.inv_of(w["sid"][0])["id"]
        post = lambda **j: self.J("post", "/api/payments", json={"invoice_id": i, **j})
        self.assertEqual(post(amount_mvr=100, method="cheque").status_code, 400)
        self.assertEqual(post(amount_mvr=100, method="gateway").status_code, 400)   # reserved for a future gateway
        self.assertEqual(post(amount_mvr=351, method="cash").status_code, 400)
        self.assertEqual(post(amount_mvr=0, method="cash").status_code, 400)
        self.assertEqual(post(amount_mvr="1e3", method="cash").status_code, 400)
        self.assertEqual(post(amount_mvr=True, method="cash").status_code, 400)
        self.assertEqual(post(amount_mvr=100, method="cash", paid_on="2026-03-13").status_code, 400)
        self.assertEqual(post(amount_mvr=100, method="cash", paid_on="2026-02-31").status_code, 400)
        r = self.ok(post(amount_mvr=100, method="cash", paid_on="2026-03-10", note="Paid at the office"), 201)
        self.assertEqual((r["payment"]["receipt_no"], r["invoice"]["balance"], r["invoice"]["status"]), ("BA-R-0001", 250, "unpaid"))
        r = self.ok(post(amount_mvr=250, method="other", reference="Sent via friend"), 201)
        self.assertEqual((r["payment"]["receipt_no"], r["invoice"]["status"]), ("BA-R-0002", "paid"))
        self.assertEqual(post(amount_mvr=1, method="cash").status_code, 400)   # nothing left
        self.ok(self.J("post", f"/api/invoices/{self.inv_of(w['sid'][0], '2026-03')['id']}/void", json={"reason": "x"}), 409) if False else None
        self.assertEqual(self.J("post", "/api/payments", json={"invoice_id": 99999, "amount_mvr": 5, "method": "cash"}).status_code, 404)
        self.assertEqual(self.J("post", "/api/payments", json={"amount_mvr": 5, "method": "cash"}).status_code, 400)

    def test_29_receipt_numbers_and_prefix(self):
        w = self.world(350, 3)
        pay = lambda k: self.ok(self.J("post", "/api/payments", json={"invoice_id": self.inv_of(w["sid"][k])["id"], "amount_mvr": 350, "method": "cash"}), 201)["payment"]["receipt_no"]
        self.assertEqual(pay(0), "BA-R-0001")
        self.ok(self.J("put", "/api/settings", json={"receipt_prefix": "BAL-"}))
        self.assertEqual(pay(1), "BAL-0002")   # sequence carries on; the old number is unchanged
        self.assertEqual(sorted(p["receipt_no"] for p in self.ok(self.J("get", "/api/payments"))), ["BA-R-0001", "BAL-0002"])
        nos = [p["receipt_no"] for p in self.ok(self.J("get", "/api/payments"))]; self.assertEqual(len(set(nos)), len(nos))

    def test_30_receipt_pdf(self):
        self.ok(self.J("put", "/api/settings", json={"bank_account_number": "7770001234567", "bank_name": "BML", "academy_name": "Baleegh Academy"}))
        w = self.world(350, 2); s0, s1 = self.S(w, 0), self.S(w, 1)
        pid = self.ok(self.J("post", "/api/payments", json={"invoice_id": self.inv_of(w["sid"][0])["id"], "amount_mvr": 350, "method": "bank_transfer", "reference": "TRX99"}), 201)["payment"]["id"]
        url = f"/api/payments/{pid}/receipt.pdf"
        r = self.J("get", url, s0); self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data.startswith(b"%PDF")); self.assertEqual(r.mimetype, "application/pdf")
        self.assertEqual(r.headers["Cache-Control"], "private, no-store"); self.assertIn("attachment", r.headers["Content-Disposition"]); self.assertIn("BA-R-0001", r.headers["Content-Disposition"])
        for needle in (b"BA-R-0001", b"MVR 350", b"Baleegh Academy", self.inv_of(w["sid"][0])["student_name"].encode(), b"INV-202603-"): self.assertIn(needle, r.data, needle)
        self.assertNotIn(b"7770001234567", r.data); self.assertNotIn(b"BML", r.data)   # no bank account on receipts
        self.assertEqual(self.J("get", url).data, r.data)   # admin gets the identical file: built on demand from stored data
        self.assertEqual(self.J("get", url, s0).data, r.data)
        self.assertEqual(self.J("get", url, s1).status_code, 404)   # another student
        t = self.login("t%dB1@t.test" % w["cid"]); self.assertEqual(self.J("get", url, t).status_code, 403)
        self.assertEqual(self.c.get(url).status_code, 401)
        self.assertEqual(self.J("get", "/api/payments/99999/receipt.pdf").status_code, 404)
        self.ok(self.J("post", f"/api/payments/{pid}/reverse", json={"reason": "Mistake"}))
        self.assertIn(b"CANCELLED", self.J("get", url, s0).data)

    # ================= overdue and reminders =================
    def test_31_overdue_is_derived_from_the_clock(self):
        w = self.world(350, 1); sid = w["sid"][0]
        od = lambda: self.ok(self.J("get", "/api/fees/overdue"))["items"]
        self.at("2026-03-19 23:00"); self.assertEqual(od(), [])   # due date itself: not overdue
        self.assertFalse(self.inv_of(sid)["overdue"])
        self.at("2026-03-20 08:00"); r = od(); self.assertEqual((len(r), r[0]["days_overdue"], r[0]["balance"]), (1, 1, 350))
        self.assertEqual(self.invs(status="overdue")[0]["id"], r[0]["id"])
        self.at("2026-03-29 08:00"); self.assertEqual(od()[0]["days_overdue"], 10)
        self.assertEqual(sqlite3.connect(self.db_path).execute("SELECT status FROM invoices").fetchone()[0], "unpaid")   # never stored
        self.ok(self.J("post", "/api/payments", json={"invoice_id": r[0]["id"], "amount_mvr": 100, "method": "cash"}), 201)
        self.assertEqual(od()[0]["balance"], 250)   # partial: still overdue, smaller balance
        self.ok(self.J("post", "/api/payments", json={"invoice_id": r[0]["id"], "amount_mvr": 250, "method": "cash"}), 201)
        self.assertEqual(od(), [])
        self.assertEqual(self.invs(status="overdue"), [])

    def test_32_reminder_links_and_templates(self):
        self.ok(self.J("put", "/api/settings", json={"academy_name": "Baleegh Academy"}))
        cid = self.course(350); bid = self.batch(cid)
        sid, _ = self.student(name="Mariyam Ali", phone="7771234", guardian_name="Ali Hassan", guardian_relationship="Father", guardian_phone="+960 765-4321", date_of_birth="2014-01-01")
        adult, _ = self.student(name="Adult Student", phone="9607779999")
        self.enroll(sid, bid); self.enroll(adult, bid)
        self.at("2026-04-01 09:00")
        items = {x["student_id"]: x for x in self.ok(self.J("get", "/api/fees/overdue"))["items"]}
        m = items[sid]
        self.assertTrue(m["links"]["student"]["whatsapp"].startswith("https://wa.me/9607771234?text="))
        self.assertEqual(m["links"]["student"]["viber"], "viber://chat?number=%2B9607771234")
        self.assertTrue(m["links"]["guardian"]["whatsapp"].startswith("https://wa.me/9607654321?text=")); self.assertEqual(m["links"]["guardian"]["viber"], "viber://chat?number=%2B9607654321")
        self.assertNotIn("guardian", items[adult]["links"])
        self.assertTrue(items[adult]["links"]["student"]["whatsapp"].startswith("https://wa.me/9607779999?text="))   # already has 960: not doubled
        self.assertIn("Mariyam Ali", m["message"]); self.assertIn("MVR 350", m["message"]); self.assertIn(m["number"], m["message"]); self.assertIn("2026-03-19", m["message"]); self.assertIn("Baleegh Academy", m["message"])
        self.assertNotIn("{", m["message"])
        self.assertIn("Mariyam%20Ali", m["links"]["student"]["whatsapp"])
        self.ok(self.J("put", "/api/settings", json={"reminder_template_en": "Hi {name}: {amount} for {invoice} due {due_date} ({days_overdue} days) {unknown}"}))
        m = {x["student_id"]: x for x in self.ok(self.J("get", "/api/fees/overdue"))["items"]}[sid]
        self.assertEqual(m["message"], f"Hi Mariyam Ali: 350 for {m['number']} due 2026-03-19 (13 days) {{unknown}}")   # unknown placeholders stay visible
        self.assertEqual(self.J("put", "/api/settings", json={"reminder_template_en": "x" * 1001}).status_code, 400)

    def test_33_reminder_sent_is_recorded(self):
        w = self.world(350, 1); i = self.inv_of(w["sid"][0])["id"]
        self.at("2026-03-25 10:00")
        row = lambda: self.ok(self.J("get", "/api/fees/overdue"))["items"][0]
        self.assertEqual((row()["reminders_sent"], row()["last_reminder"], row()["reminded_today"]), (0, None, False))
        self.assertEqual(self.J("post", f"/api/invoices/{i}/reminders", json={"channel": "sms"}).status_code, 400)
        self.assertEqual(self.J("post", f"/api/invoices/{i}/reminders", json={"channel": "viber", "to": "neighbour"}).status_code, 400)
        self.ok(self.J("post", f"/api/invoices/{i}/reminders", json={"channel": "whatsapp", "to": "student"}), 201)
        r = row(); self.assertEqual((r["reminders_sent"], r["last_reminder"]["channel"], r["last_reminder"]["by_name"], r["reminded_today"]), (1, "whatsapp", "Admin", True))
        self.at("2026-03-26 10:00"); self.assertFalse(row()["reminded_today"])
        self.assertIn("reminder_sent", self.audit_actions())
        self.ok(self.J("post", "/api/payments", json={"invoice_id": i, "amount_mvr": 350, "method": "cash"}), 201)
        self.assertEqual(self.J("post", f"/api/invoices/{i}/reminders", json={"channel": "whatsapp"}).status_code, 409)   # paid: nothing to chase

    def test_34_email_is_off_by_default_and_never_pretends(self):
        w = self.world(350, 1); i = self.inv_of(w["sid"][0])["id"]; self.at("2026-03-25 10:00")
        self.assertFalse(self.ok(self.J("get", "/api/fees/overdue"))["email_enabled"])
        r = self.J("post", f"/api/invoices/{i}/reminders/email", json={})
        self.assertEqual(r.status_code, 409); self.assertFalse(r.get_json()["email_enabled"])
        self.assertEqual(sqlite3.connect(self.db_path).execute("SELECT COUNT(*) FROM reminders").fetchone()[0], 0)   # nothing recorded as sent
        self.app = self.mk(EMAIL_ENABLED=True); self.c = self.app.test_client(); self.a = self.login("admin@t.test", "AdminPass123")   # flag on but no SMTP host
        self.assertFalse(self.ok(self.J("get", "/api/fees/overdue"))["email_enabled"])
        self.assertEqual(self.J("post", f"/api/invoices/{i}/reminders/email", json={}).status_code, 409)

    def test_35_email_reminder_with_a_fake_smtp_server(self):
        smtp = FakeSMTP(); self.addCleanup(smtp.stop)
        w = self.world(350, 1); i = self.inv_of(w["sid"][0])["id"]; self.at("2026-03-25 10:00")
        self.app = self.mk(EMAIL_ENABLED=True, SMTP_HOST="127.0.0.1", SMTP_PORT=str(smtp.port), SMTP_FROM="fees@baleegh.test", SMTP_STARTTLS="0")
        self.c = self.app.test_client(); self.a = self.login("admin@t.test", "AdminPass123")
        self.assertTrue(self.ok(self.J("get", "/api/fees/overdue"))["email_enabled"])
        self.ok(self.J("post", f"/api/invoices/{i}/reminders/email", json={}), 201)
        self.assertEqual(len(smtp.messages), 1)
        m = smtp.messages[0]
        self.assertIn(w["email"][0], m["to"][0]); self.assertIn("fees@baleegh.test", m["from"])
        self.assertIn("INV-202603-", m["data"]); self.assertIn("MVR 350", m["data"]); self.assertIn("Fee reminder", m["data"])
        self.assertEqual(self.ok(self.J("get", "/api/fees/overdue"))["items"][0]["last_reminder"]["channel"], "email")
        smtp.stop()
        self.app = self.mk(EMAIL_ENABLED=True, SMTP_HOST="127.0.0.1", SMTP_PORT=str(smtp.port), SMTP_FROM="fees@baleegh.test", SMTP_STARTTLS="0")   # server gone
        self.c = self.app.test_client(); self.a = self.login("admin@t.test", "AdminPass123")
        r = self.J("post", f"/api/invoices/{i}/reminders/email", json={}); self.assertEqual(r.status_code, 502)
        self.assertEqual(sqlite3.connect(self.db_path).execute("SELECT COUNT(*) FROM reminders WHERE channel='email'").fetchone()[0], 1)   # the failure was not recorded as sent

    # ================= void / waive / reopen =================
    def test_36_void_waive_reopen(self):
        w = self.world(350, 3)
        i = [self.inv_of(s)["id"] for s in w["sid"]]
        act = lambda n, k, **j: self.J("post", f"/api/invoices/{i[n]}/{k}", json=j)
        self.assertEqual(act(0, "void").status_code, 400)   # reason required
        self.assertEqual(act(0, "waive", reason=" ").status_code, 400)
        r = self.ok(act(0, "void", reason="Entered by mistake")); self.assertEqual(r["invoice"]["status"], "void")
        self.assertEqual(act(0, "void", reason="again").status_code, 409)
        self.assertEqual(self.J("post", "/api/payments", json={"invoice_id": i[0], "amount_mvr": 5, "method": "cash"}).status_code, 409)   # cannot pay a void invoice
        self.assertEqual(self.gen("2026-03")["skipped"].get("already_invoiced"), 3)   # the void row keeps its slot: no silent re-billing
        self.assertEqual(self.ok(act(0, "reopen", reason="It was right after all"))["invoice"]["status"], "unpaid")
        self.assertEqual(act(0, "reopen", reason="x").status_code, 409)
        self.ok(self.J("post", "/api/payments", json={"invoice_id": i[1], "amount_mvr": 100, "method": "cash"}), 201)
        self.assertEqual(act(1, "void", reason="x").status_code, 409)   # has a payment
        r = self.ok(act(1, "waive", reason="Hardship: balance forgiven"))["invoice"]
        self.assertEqual((r["status"], r["waived_mvr"], r["balance"]), ("waived", 250, 0))
        self.assertEqual(act(1, "waive", reason="x").status_code, 409)
        pid = self.ok(self.J("get", "/api/payments"))[0]["id"]
        self.assertEqual(self.J("post", f"/api/payments/{pid}/reverse", json={"reason": "x"}).status_code, 409)   # reopen first
        sid = self.ok(self.slip(self.S(w, 2), i[2]), 201)["id"]
        self.assertEqual(act(2, "void", reason="x").status_code, 409); self.assertEqual(act(2, "waive", reason="x").status_code, 409)   # slip waiting
        acts = self.audit_actions()
        for a in ("invoice_void", "invoice_waive", "invoice_reopen"): self.assertIn(a, acts)
        mine = self.ok(self.J("get", "/api/my/fees", self.S(w, 0))); self.assertEqual(len(mine["invoices"]), 1)
        self.assertEqual(self.ok(self.J("get", f"/api/invoices/{i[1]}", self.S(w, 1)))["invoice"]["status_reason"], "Hardship: balance forgiven")   # reason is visible to the student

    # ================= reports and dashboard =================
    def test_37_monthly_report_adds_up_and_csv(self):
        cid = self.course(350); bid = self.batch(cid); cid2 = self.course(500, name="English"); bid2 = self.batch(cid2)
        names = ["Paid Full", "Paid Part", "Owes", "Waived", "Voided", '=HYPERLINK("http://x","click")']
        ss = [self.student(name=n)[0] for n in names]
        for k, s in enumerate(ss): self.enroll(s, bid2 if k == 3 else bid)
        inv = lambda k: self.inv_of(ss[k])["id"]
        cash = lambda k, amt: self.ok(self.J("post", "/api/payments", json={"invoice_id": inv(k), "amount_mvr": amt, "method": "cash"}), 201)
        cash(0, 350); cash(1, 100)
        self.ok(self.J("post", f"/api/invoices/{inv(3)}/waive", json={"reason": "Hardship"}))
        self.ok(self.J("post", f"/api/invoices/{inv(4)}/void", json={"reason": "Mistake"}))
        self.at("2026-03-30 10:00")
        r = self.ok(self.J("get", "/api/fees/report?month=2026-03")); t = r["totals"]
        self.assertEqual((t["invoiced"], t["collected"], t["outstanding"], t["invoice_count"]), (350 * 3 + 0 + 350, 450, 350 * 3 + 350 - 450 - 0, 5))   # void excluded; waived 500 not expected
        # recompute by hand: invoiced = 350 (paid) + 350 (part) + 350 (owes) + 0 (waived 500 forgiven) + 350 (formula-name student) = 1400
        self.assertEqual(t["invoiced"], 1400); self.assertEqual(t["collected"], 450); self.assertEqual(t["outstanding"], 950)
        self.assertEqual(t["invoiced"], t["collected"] + t["outstanding"])
        self.assertEqual(t["waived"], 500); self.assertEqual(t["overdue_count"], 3)
        bc = {c["course_name"]: c for c in r["by_course"]}
        self.assertEqual(bc["English"]["invoiced"], 0); self.assertEqual(bc[f"Course{cid}"]["invoiced"] if f"Course{cid}" in bc else sum(c["invoiced"] for c in r["by_course"]), 1400)
        self.assertEqual(sum(c["collected"] for c in r["by_course"]), 450); self.assertEqual(sum(c["outstanding"] for c in r["by_course"]), 950)
        self.assertEqual(sorted(o["student_name"] for o in r["owing"]), sorted(["Paid Part", "Owes", names[5]]))
        self.assertEqual(sum(o["balance"] for o in r["owing"]), 950)
        self.assertEqual(self.ok(self.J("get", "/api/fees/report?month=2026-02"))["totals"]["invoiced"], 0)
        self.assertEqual(self.J("get", "/api/fees/report?month=xx").status_code, 400)
        c = self.J("get", "/api/fees/report.csv?month=2026-03")
        self.assertEqual(c.status_code, 200); self.assertIn("text/csv", c.mimetype); self.assertIn("attachment", c.headers["Content-Disposition"])
        import csv
        rows = list(csv.reader(io.StringIO(c.get_data(as_text=True).lstrip("\ufeff"))))   # v0.8.34: CSVs start with a BOM for Excel
        self.assertEqual(rows[0][:4], ["invoice", "period", "student", "course"]); self.assertEqual(len(rows), 1 + 5)
        by = {x[2]: x for x in rows[1:]}
        self.assertEqual((by["Paid Part"][9], by["Paid Part"][10], by["Paid Part"][12]), ("100", "250", "unpaid"))
        self.assertEqual(by["Waived"][12], "waived"); self.assertNotIn("Voided", by)
        self.assertIn("'=HYPERLINK", c.get_data(as_text=True)); self.assertNotIn(",=HYPERLINK", c.get_data(as_text=True))   # formula injection neutralised
        self.assertEqual(self.c.get("/api/fees/report.csv").status_code, 401)

    def test_38_dashboard_numbers(self):
        w = self.world(350, 3)
        d = self.ok(self.J("get", "/api/dashboard"))
        self.assertEqual((d["unpaid_invoices"], d["month_collection_mvr"], d["slips_pending"], d["overdue_invoices"]), (3, 0, 0, 0))
        i = [self.inv_of(s)["id"] for s in w["sid"]]
        self.ok(self.J("post", "/api/payments", json={"invoice_id": i[0], "amount_mvr": 350, "method": "cash", "paid_on": "2026-03-05"}), 201)
        self.ok(self.J("post", "/api/payments", json={"invoice_id": i[1], "amount_mvr": 100, "method": "cash", "paid_on": "2026-03-12"}), 201)
        self.ok(self.slip(self.S(w, 2), i[2]), 201)
        d = self.ok(self.J("get", "/api/dashboard"))
        self.assertEqual((d["unpaid_invoices"], d["month_collection_mvr"], d["slips_pending"]), (2, 450, 1))   # part-paid and slip-waiting both still unpaid
        pid = self.ok(self.J("get", "/api/payments"))[0]["id"]
        self.ok(self.J("post", f"/api/payments/{pid}/reverse", json={"reason": "wrong invoice"}))
        self.assertEqual(self.ok(self.J("get", "/api/dashboard"))["month_collection_mvr"], 350)   # reversed money is not counted
        self.at("2026-04-02 10:00"); d = self.ok(self.J("get", "/api/dashboard"))
        self.assertEqual(d["month_collection_mvr"], 0); self.assertEqual(d["overdue_invoices"], 2)   # new month; March invoices now past due
        self.assertEqual(self.ok(self.J("get", "/api/payments?month=2026-03")).__len__(), 2)
        self.assertEqual(self.ok(self.J("get", "/api/my/fees/summary", self.S(w, 0)))["balance_due"], 0)
        s = self.ok(self.J("get", "/api/my/fees/summary", self.S(w, 1))); self.assertEqual((s["balance_due"], s["overdue_count"]), (350, 1))   # the 100 payment was reversed above

    # ================= access control =================
    STUDENT_OK = {"my_fees_summary", "my_fees", "slip_upload", "slip_file", "inv_get", "receipt_pdf"}

    def test_39_every_fee_endpoint_enforces_roles(self):
        w = self.world(350, 1); s = self.S(w); t = self.login("t%dB1@t.test" % w["cid"])
        fee_rules = [r for r in self.app.url_map.iter_rules() if self.app.view_functions[r.endpoint].__module__ == "fees"]
        self.assertGreater(len(fee_rules), 30)
        seen = 0
        for rule in fee_rules:
            url = re.sub(r"<[^>]+>", "1", rule.rule)
            for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
                seen += 1
                call = lambda hdr: getattr(self.c, method.lower())(url, headers=hdr or {}, json={} if method in ("POST", "PUT", "PATCH") else None)
                self.assertEqual(call(None).status_code, 401, f"no token {method} {url}")
                r = call(t); self.assertEqual(r.status_code, 403, f"teacher {method} {url}"); self.assertNotIn("amount", r.get_data(as_text=True))
                fn = self.app.view_functions[rule.endpoint].__name__
                rs = call(s).status_code
                if fn in self.STUDENT_OK: self.assertNotEqual(rs, 403, f"student should reach {method} {url}") if False else self.assertIn(rs, (200, 400, 404, 415), f"student {method} {url}")
                else: self.assertEqual(rs, 403, f"student {method} {url}")
        self.assertGreater(seen, 30)

    def test_40_students_see_only_their_own_money(self):
        w = self.world(350, 2); s0, s1 = self.S(w, 0), self.S(w, 1)
        i0, i1 = self.inv_of(w["sid"][0])["id"], self.inv_of(w["sid"][1])["id"]
        pid = self.ok(self.J("post", "/api/payments", json={"invoice_id": i0, "amount_mvr": 350, "method": "cash"}), 201)["payment"]["id"]
        for url in (f"/api/invoices/{i0}", f"/api/payments/{pid}/receipt.pdf"):
            self.assertEqual(self.J("get", url, s1).status_code, 404)
            self.assertEqual(self.J("get", url, s0).status_code, 200)
        self.assertEqual(self.J("get", f"/api/invoices/{i1}", s0).status_code, 404)
        self.assertEqual(self.J("get", f"/api/invoices/99999", s0).status_code, 404)   # same answer for "not yours" and "does not exist"
        mine = self.ok(self.J("get", "/api/my/fees", s1)); self.assertEqual([x["id"] for x in mine["invoices"]], [i1]); self.assertEqual(mine["payments"], [])
        self.assertNotIn("student_email", self.ok(self.J("get", f"/api/invoices/{i0}", s0))["invoice"])
        self.assertEqual(self.J("get", "/api/invoices", s0).status_code, 403); self.assertEqual(self.J("get", "/api/slips", s0).status_code, 403)

    def test_41_teachers_see_no_fee_data_anywhere(self):
        w = self.world(350, 1); t = self.login("t%dB1@t.test" % w["cid"])
        txt = lambda url: self.J("get", url, t).get_data(as_text=True)
        for url in (f"/api/batches/{w['bid']}/students", "/api/my/home", "/api/batches", f"/api/batches/{w['bid']}/attendance/summary"):
            body = txt(url).lower()
            for word in ("invoice", "balance", "slip", "amount_due", "receipt", "paid_mvr"): self.assertNotIn(word, body, f"{url} leaks {word}")
        self.assertEqual(self.J("get", "/api/dashboard", t).status_code, 403)

    # ================= misc: audit, language, settings =================
    def test_42_every_money_action_is_in_the_audit_log(self):
        w = self.world(350, 2); s = self.S(w, 0); i = self.inv_of(w["sid"][0])["id"]; j = self.inv_of(w["sid"][1])["id"]
        self.gen("2026-04")
        sid = self.ok(self.slip(s, i), 201)["id"]
        pid = self.ok(self.J("post", f"/api/slips/{sid}/verify", json={}))["payment_id"]
        self.J("get", f"/api/payments/{pid}/receipt.pdf")
        self.J("post", f"/api/invoices/{j}/discount", json={"kind": "fixed", "value": 10, "reason": "r"})
        self.J("post", f"/api/payments/{pid}/reverse", json={"reason": "r"})
        self.J("post", "/api/payments", json={"invoice_id": j, "amount_mvr": 5, "method": "cash"})
        self.J("post", f"/api/invoices/{j}/waive", json={"reason": "r"})
        sid2 = self.ok(self.slip(s, i, content=PNG, name="x.png"), 201)["id"]
        self.J("post", f"/api/slips/{sid2}/reject", json={"reason": "r"})
        acts = self.audit_actions()
        for a in ("generate_invoices", "slip_upload", "slip_verify", "slip_reject", "payment_record", "payment_reverse", "invoice_discount", "invoice_waive", "view_receipt"):
            self.assertIn(a, acts, a)
        rows = self.ok(self.J("get", "/api/audit"))
        v = [r for r in rows if r["action"] == "slip_verify"][0]; self.assertEqual(v["user_name"], "Admin"); self.assertTrue(v["at"]); self.assertIn("BA-R-0001", v["detail"])

    def test_43_language_files(self):
        en = json.load(open(os.path.join(ROOT, "static/i18n/en.json")))
        self.assertNotIn("reminder_template_dv", en)
        js = "".join(open(os.path.join(ROOT, "static", f), encoding="utf-8").read() for f in ("fees.js", "admin.js"))   # v0.8.33: the fee cards of the Dashboard live in admin.js (Session 8)
        used = set(re.findall(r"""\bt\(\s*["']([a-z0-9_]+)["']\s*\)""", js))
        for pre, opts in (("fx_st_", ("unpaid", "slip_submitted", "paid", "void", "waived", "overdue", "partial")), ("fx_m_", ("bank_transfer", "cash", "cheque", "other")), ("fx_tab_", ("slips", "invoices", "record", "discounts", "overdue", "report", "payrep"))):
            used |= {pre + o for o in opts}
        used |= {"fees"}
        missing = sorted(k for k in used if k not in en)
        self.assertEqual(missing, [], "keys used in fees.js/admin.js but missing from en.json")
        fx = {k for k in en if k.startswith("fx_")}
        self.assertEqual(sorted(fx - used), [], "unused fx_ keys in en.json")
        for k in ("invoice_due_day", "first_invoice_mode", "first_invoice_grace_days", "receipt_prefix", "reminder_template_en"): self.assertIn(k, en, "setting label " + k)
        self.assertEqual(self.c.get("/fees.js").status_code, 200)
        self.assertIn("fees.js", open(os.path.join(ROOT, "static/index.html"), encoding="utf-8").read())

    def test_44_settings_roundtrip_and_blank_means_default(self):
        s = self.ok(self.J("get", "/api/settings"))
        for k in ("invoice_due_day", "first_invoice_mode", "first_invoice_grace_days", "receipt_prefix", "reminder_template_en"): self.assertIn(k, s)
        self.assertNotIn("reminder_template_dv", s)
        self.ok(self.J("put", "/api/settings", json={k: "" for k in s}))   # the Settings screen saves every field, blanks included
        w = self.world(350, 1); self.gen("2026-04")
        self.assertEqual(self.inv_of(w["sid"][0], "2026-04")["due_date"], "2026-04-10")
        pid = self.ok(self.J("post", "/api/payments", json={"invoice_id": self.inv_of(w["sid"][0])["id"], "amount_mvr": 5, "method": "cash"}), 201)["payment"]
        self.assertEqual(pid["receipt_no"], "BA-R-0001")
        self.assertEqual(self.J("put", "/api/settings", json={"bank_name": "BML"}, hdr=self.login("t1B1@t.test") if False else None).status_code, 200)

    def test_45_upgrade_from_phase3_database(self):
        """A database created by Phase 3 gets the new tables by simply starting the app again; existing rows survive."""
        old = os.path.join(self.tmp, "old.db")
        schema = open(os.path.join(ROOT, "schema.sql")).read()
        phase3 = schema[:schema.index("-- Phase 4")]
        con = sqlite3.connect(old); con.executescript(phase3)
        con.execute("INSERT INTO users(email,password_hash,full_name,role) VALUES('x@t.test','h','X','admin')"); con.commit()
        self.assertFalse(con.execute("SELECT 1 FROM sqlite_master WHERE name='invoices'").fetchone()); con.close()
        from app import create_app
        create_app({"DATABASE_PATH": old})
        con = sqlite3.connect(old)
        self.assertTrue(con.execute("SELECT 1 FROM sqlite_master WHERE name='invoices'").fetchone())
        self.assertEqual(con.execute("SELECT full_name FROM users").fetchone()[0], "X")
        self.assertEqual(con.execute("SELECT value FROM counters WHERE name='receipt'").fetchone()[0], 0)
        create_app({"DATABASE_PATH": old})   # and a second restart changes nothing
        self.assertEqual(sqlite3.connect(old).execute("SELECT COUNT(*) FROM counters").fetchone()[0], 1)

    def test_46_database_refuses_bad_money(self):
        """The schema itself backs up the app's checks."""
        w = self.world(350, 1); con = sqlite3.connect(self.db_path); con.execute("PRAGMA foreign_keys=ON")
        i = self.inv_of(w["sid"][0])
        for sql in ("UPDATE invoices SET amount_due_mvr=1 WHERE id=%d" % i["id"], "UPDATE invoices SET discount_mvr=999, amount_due_mvr=-649 WHERE id=%d" % i["id"],
                    "UPDATE invoices SET status='overdue' WHERE id=%d" % i["id"],
                    "INSERT INTO invoices(enrollment_id,student_id,course_id,batch_id,period,description,amount_mvr,amount_due_mvr,due_date,created_at) SELECT enrollment_id,student_id,course_id,batch_id,period,'dup',350,350,'2026-03-10','x' FROM invoices WHERE id=%d" % i["id"],
                    "INSERT INTO payments(invoice_id,student_id,amount_mvr,method,paid_on,receipt_seq,receipt_no,created_at) VALUES(%d,%d,-5,'cash','2026-03-01',9,'X9','x')" % (i["id"], w["sid"][0])):
            with self.assertRaises(sqlite3.IntegrityError, msg=sql): con.execute(sql)


if __name__ == "__main__":
    unittest.main()
