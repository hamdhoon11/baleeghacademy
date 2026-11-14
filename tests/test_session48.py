"""v0.8.48: superadmin; fee reminders per person (total and months, 5 days before, WhatsApp list, Home banner, daily notices);
PDF for every report; the monthly report batch by batch; the academy logo."""
import datetime as dt, io, json, os, sqlite3, sys, tempfile, unittest
from urllib.parse import unquote
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MVT = dt.timezone(dt.timedelta(hours=5))
PW = "Password123"


def png(w=40, h=20):
    from reportlab.graphics.shapes import Drawing, Rect
    from reportlab.graphics import renderPM
    d = Drawing(w, h); d.add(Rect(0, 0, w, h, fillColor=None))
    try: return renderPM.drawToString(d, fmt="PNG")
    except Exception:   # no renderPM backend: a hand-made 1x1 PNG
        import zlib, struct
        raw = b"\x00\xff\x00\x00"
        chunk = lambda t, b: struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xffffffff)
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class S48(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        old = os.environ.get("SEED_DEMO")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s48.test", ADMIN_PASSWORD="AdminPass123", SEED_DEMO="0")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path}); cls.c = cls.app.test_client()
        cls.clock = [dt.datetime(2026, 11, 14, 10, 0, tzinfo=MVT)]
        cls.app.config["NOW"] = lambda: cls.clock[0]
        cls.H = cls.tok("admin@s48.test", "AdminPass123")
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, role, n=None: P("/api/users", {"email": e, "password": PW, "full_name": n or e.split("@")[0].title(), "role": role, "phone": "7771234"}).get_json()["id"]
        cls.adm = cls.sql_("SELECT id FROM users WHERE email='admin@s48.test'")[0][0]
        cls.adm2, cls.lim, cls.t1 = mk("adm2@s48.test", "admin"), mk("lim@s48.test", "admin"), mk("t1@s48.test", "teacher", "Ustaz Ahmed")
        cls.s = [mk(f"s{i}@s48.test", "student", n) for i, n in enumerate(["Aisha Ali", "Ibrahim Naseem", "Hassan Rasheed", "عائشة محمد"])]
        cls.c.patch(f"/api/users/{cls.lim}", json={"permissions": ["people", "settings", "fees"]}, headers=cls.H)
        cls.sql_("UPDATE users SET must_change_password=0")
        cls.co = P("/api/courses", {"name": "Arabic Level 1", "monthly_fee_mvr": 500, "status": "open"}).get_json()["id"]
        cls.co2 = P("/api/courses", {"name": "Quran Tuition", "monthly_fee_mvr": 300, "status": "open", "kind": "tuition"}).get_json()["id"]
        cls.b1 = P("/api/batches", {"course_id": cls.co, "code": "A1", "teacher_id": cls.t1, "capacity": 20, "days": "Wed", "start_time": "16:00"}).get_json()["id"]
        cls.b2 = P("/api/batches", {"course_id": cls.co2, "code": "Q1", "teacher_id": cls.t1, "capacity": 20, "days": "Thu", "start_time": "16:00"}).get_json()["id"]
        for i, sid in enumerate(cls.s):
            r = P("/api/enrollments", {"student_id": sid, "batch_id": cls.b1 if i < 3 else cls.b2, "start_date": "2026-08-01"}); assert r.status_code == 201, r.get_json()
        # Aisha paid everything; Ibrahim paid Aug and Sep; the others nothing
        cls.pay(cls.s[0]); cls.pay(cls.s[1], ("2026-08", "2026-09"))

    @classmethod
    def pay(cls, sid, periods=None):
        q = "SELECT id FROM invoices WHERE student_id=?" + (f" AND period IN ({','.join('?' * len(periods))})" if periods else "")
        ids = [r[0] for r in cls.sql_(q, (sid, *(periods or ())))]
        r = cls.c.post("/api/payments/mark-paid", json={"invoice_ids": ",".join(map(str, ids)), "method": "cash", "paid_on": "2026-11-01"}, headers=cls.H)
        assert r.status_code in (200, 201), r.get_json()

    @classmethod
    def tok(cls, login, pw):
        r = cls.c.post("/api/auth/login", json={"login": login, "password": pw}); assert r.status_code == 200, r.get_json()
        return {"Authorization": "Bearer " + r.get_json()["token"]}

    @classmethod
    def sql_(cls, q, a=()):
        con = sqlite3.connect(cls.path)
        try: r = con.execute(q, a).fetchall(); con.commit(); return r
        finally: con.close()

    # ---------------- superadmin ----------------
    def test_01_superadmin_is_the_first_full_admin_and_only_they_act(self):
        me = lambda h: self.c.get("/api/auth/me", headers=h).get_json()["user"]
        A2, L = self.tok("adm2@s48.test", PW), self.tok("lim@s48.test", PW)
        self.assertTrue(me(self.H)["is_super"]); self.assertFalse(me(A2)["is_super"]); self.assertFalse(me(L)["is_super"])
        # every admin may look
        for h in (self.H, A2, L):
            self.assertEqual(self.c.get("/api/admin/presence", headers=h).status_code, 200)
            self.assertEqual(self.c.get("/api/admin/presence/summary", headers=h).status_code, 200)
            self.assertIn("online", me(h)["tabs"])
        self.assertTrue(self.c.get("/api/admin/presence", headers=self.H).get_json()["can_act"])
        self.assertFalse(self.c.get("/api/admin/presence", headers=A2).get_json()["can_act"])
        # only the superadmin acts (a full admin is refused now)
        for what in ("signout", "pause", "suspend", "restore"):
            self.assertEqual(self.c.post(f"/api/admin/accounts/{self.s[2]}/{what}", json={"reason": "x", "hours": 1}, headers=A2).status_code, 403, what)
        self.assertEqual(self.c.post("/api/admin/accounts/bulk", json={"ids": [self.s[2]], "action": "signout"}, headers=A2).status_code, 403)
        self.assertEqual(self.c.post("/api/admin/accounts/signout-all", json={}, headers=A2).status_code, 403)
        self.assertEqual(self.c.post("/api/admin/reset-data", json={}, headers=A2).status_code, 403)
        self.assertEqual(self.c.post(f"/api/admin/accounts/{self.s[2]}/signout", json={}, headers=self.H).status_code, 200)
        self.assertEqual(self.c.post("/api/admin/reset-data", json={}, headers=self.H).status_code, 200)   # the preview; nothing deleted
        # the superadmin's account is protected from other admins
        for body in ({"is_active": False}, {"permissions": ["people"]}, {"full_name": "X"}):
            self.assertEqual(self.c.patch(f"/api/users/{self.adm}", json=body, headers=A2).status_code, 403, body)
        self.assertEqual(self.c.post(f"/api/users/{self.adm}/reset-password", headers=A2).status_code, 403)
        self.assertEqual(self.c.delete(f"/api/users/{self.adm}", headers=A2).status_code, 403)
        self.assertEqual(self.c.patch(f"/api/users/{self.adm2}", json={"is_super": True}, headers=A2).status_code, 403)   # cannot make themself (or anyone) superadmin

    def test_02_hand_over_superadmin(self):
        A2 = self.tok("adm2@s48.test", PW)
        self.assertEqual(self.c.patch(f"/api/users/{self.lim}", json={"is_super": True}, headers=self.H).status_code, 409)   # a limited admin cannot be superadmin
        self.assertEqual(self.c.patch(f"/api/users/{self.adm}", json={"is_super": False}, headers=self.H).status_code, 409)   # the only one
        self.assertEqual(self.c.patch(f"/api/users/{self.adm2}", json={"is_super": True}, headers=self.H).status_code, 200)
        users = {u["id"]: u for u in self.c.get("/api/users", headers=self.H).get_json()}
        self.assertTrue(users[self.adm]["is_super"] and users[self.adm2]["is_super"])
        self.assertEqual(self.c.patch(f"/api/users/{self.adm2}", json={"permissions": ["people"]}, headers=self.H).status_code, 409)   # remove superadmin first
        self.assertEqual(self.c.get("/api/admin/presence", headers=A2).get_json()["can_act"], True)
        self.assertEqual(self.c.patch(f"/api/users/{self.adm2}", json={"is_super": False}, headers=self.H).status_code, 200)
        self.assertFalse(self.c.get("/api/auth/me", headers=A2).get_json()["user"]["is_super"])
        log = [r[0] for r in self.sql_("SELECT action FROM audit_log WHERE action='superadmin_change'")]
        self.assertEqual(len(log), 2)

    # ---------------- reminders ----------------
    def test_03_reminders_per_person_with_total_and_months(self):
        r = self.c.get("/api/fees/reminders", headers=self.H).get_json()
        self.assertEqual(r["window_days"], 5)
        od = {x["student_id"]: x for x in r["overdue"]}
        self.assertNotIn(self.s[0], od)   # paid everything
        self.assertEqual((od[self.s[1]]["total"], od[self.s[1]]["months"]), (500, ["Oct 2026"]))
        self.assertEqual((od[self.s[2]]["total"], od[self.s[2]]["months"], od[self.s[2]]["count"]), (1500, ["Aug 2026", "Sep 2026", "Oct 2026"], 3))
        x = od[self.s[2]]
        self.assertIn("MVR 1,500 for Aug 2026, Sep 2026 and Oct 2026 are overdue", x["message"])
        self.assertIn("3 unpaid months", x["message"])
        self.assertIn("Aug 2026, Sep 2026 and Oct 2026", unquote(x["links"]["student"]["whatsapp"]))
        self.assertTrue(x["links"]["student"]["whatsapp"].startswith("https://wa.me/9607771234?text="))
        # opening the chat records it on every invoice in the message
        self.assertEqual(self.c.post("/api/fees/reminders/sent", json={"key": x["key"], "kind": "overdue", "to": "student"}, headers=self.H).status_code, 201)
        again = [y for y in self.c.get("/api/fees/reminders", headers=self.H).get_json()["overdue"] if y["key"] == x["key"]][0]
        self.assertTrue(again["reminded_today"])
        self.assertEqual(self.sql_("SELECT COUNT(*) FROM reminders r JOIN invoices i ON i.id=r.invoice_id WHERE i.student_id=?", (self.s[2],))[0][0], 3)
        self.assertEqual(self.c.post("/api/fees/reminders/sent", json={"key": "s999999", "kind": "overdue"}, headers=self.H).status_code, 409)
        T = self.tok("t1@s48.test", PW)
        self.assertEqual(self.c.get("/api/fees/reminders", headers=T).status_code, 403)

    def test_04_due_soon_five_days_before_then_banner_then_gone(self):
        sid = self.s[3]
        nov = self.sql_("SELECT id, due_date FROM invoices WHERE student_id=? AND period='2026-11'", (sid,))[0]
        self.sql_("UPDATE invoices SET due_date='2026-11-20' WHERE id=?", (nov[0],))
        S = self.tok("s3@s48.test", PW)
        summ = lambda: self.c.get("/api/my/fees/summary", headers=S).get_json()["reminder"]
        self.clock[0] = dt.datetime(2026, 11, 14, 10, 0, tzinfo=MVT)   # 6 days before: not yet
        self.assertIsNone(summ()["due_soon"])
        self.clock[0] = dt.datetime(2026, 11, 15, 10, 0, tzinfo=MVT)   # 5 days before: shown
        d = summ()["due_soon"]
        self.assertEqual((d["total"], d["months"], d["days_left"]), (300, ["Nov 2026"], 5))
        self.assertIn("settle the payment before the due date", d["text"])
        r = self.c.get("/api/fees/reminders", headers=self.H).get_json()
        self.assertIn(sid, [x["student_id"] for x in r["due_soon"]])
        self.assertIn("is due on 20 Nov 2026", [x for x in r["due_soon"] if x["student_id"] == sid][0]["message"])
        self.clock[0] = dt.datetime(2026, 11, 21, 10, 0, tzinfo=MVT)   # past the date: now overdue with the other months
        rm = summ()
        self.assertIsNone(rm["due_soon"]); self.assertIn("Nov 2026", rm["overdue"]["months"])
        self.clock[0] = dt.datetime(2026, 11, 14, 10, 0, tzinfo=MVT)

    def test_05_daily_notices_one_per_student_with_months(self):
        self.sql_("DELETE FROM notifications")
        j = self.c.post("/api/notifications/run?dry_run=0", headers=self.H).get_json()
        people = {r[0]: r[1] for r in self.sql_("SELECT user_id, body FROM notifications WHERE kind='fee_overdue'")}
        self.assertEqual(j["fee_overdue"], len(people))
        self.assertIn("Aug 2026, Sep 2026 and Oct 2026", people[self.s[2]])
        self.assertNotIn(self.s[0], people)
        j2 = self.c.post("/api/notifications/run?dry_run=0", headers=self.H).get_json()
        self.assertEqual(j2["fee_overdue"], 0)   # not twice
        digest = self.sql_("SELECT body FROM notifications WHERE kind='admin_overdue' AND user_id=?", (self.adm,))[0][0]
        self.assertIn("to remind on WhatsApp", digest)

    def test_06_slip_waiting_is_not_reminded(self):
        sid = self.s[1]
        iid = self.sql_("SELECT id FROM invoices WHERE student_id=? AND period='2026-10'", (sid,))[0][0]
        self.sql_("UPDATE invoices SET status='slip_submitted' WHERE id=?", (iid,))
        try:
            r = self.c.get("/api/fees/reminders", headers=self.H).get_json()
            self.assertNotIn(sid, [x["student_id"] for x in r["overdue"]])
            self.assertIn(f"s{sid}", [x["key"] for x in r["slips_only"]])
        finally:
            self.sql_("UPDATE invoices SET status='unpaid' WHERE id=?", (iid,))

    # ---------------- reports ----------------
    def test_07_monthly_report_batch_by_batch(self):
        r = self.c.get("/api/fees/report?month=2026-10", headers=self.H).get_json()
        b = {x["batch_code"]: x for x in r["by_batch"]}
        self.assertEqual((b["A1"]["students"], b["A1"]["invoiced"], b["A1"]["collected"], b["A1"]["outstanding"], b["A1"]["paid"], b["A1"]["overdue"]), (3, 1500, 500, 1000, 1, 2))
        self.assertEqual((b["Q1"]["invoiced"], b["Q1"]["rate"], b["A1"]["teacher_name"]), (300, 0, "Ustaz Ahmed"))
        self.assertEqual(sum(x["invoiced"] for x in r["by_batch"]), r["totals"]["invoiced"])
        self.assertEqual(r["status_counts"], {"paid": 1, "partial": 0, "unpaid": 0, "overdue": 3})
        self.assertEqual([x["month"] for x in r["trend"]], ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"])
        self.assertEqual(r["trend"][-1]["invoiced"], 1800)

    def test_08_every_report_has_a_pdf(self):
        self.c.post(f"/api/batches/{self.b1}/sessions", json={"session_date": "2026-11-11", "status": "held"}, headers=self.H)
        urls = ["/api/fees/report.pdf?month=2026-10", "/api/fees/payment-report.pdf?month=2026-10", f"/api/fees/payment-report.pdf?month=2026-10&batch_id={self.b1}&status=unpaid",
                "/api/fees/reminders.pdf", "/api/earnings/report.pdf", "/api/enrollment-events.pdf", "/api/audit.pdf", "/api/audit.pdf?action=login",
                "/api/finance/report.pdf", "/api/finance/report.pdf?date_from=2026-08-01&date_to=2026-11-14",
                f"/api/batches/{self.b1}/gradebook.pdf", f"/api/batches/{self.b1}/attendance.pdf?month=2026-11"]
        for u in urls:
            r = self.c.get(u, headers=self.H)
            self.assertEqual((r.status_code, r.mimetype), (200, "application/pdf"), u)
            self.assertTrue(r.data.startswith(b"%PDF"), u)
            self.assertIn("attachment", r.headers["Content-Disposition"])
        # the right people only
        T, L = self.tok("t1@s48.test", PW), self.tok("lim@s48.test", PW)
        self.assertEqual(self.c.get(f"/api/batches/{self.b1}/gradebook.pdf", headers=T).status_code, 200)   # the batch's own teacher
        for u in ("/api/fees/report.pdf", "/api/earnings/report.pdf", "/api/finance/report.pdf", "/api/audit.pdf"):
            self.assertEqual(self.c.get(u, headers=T).status_code, 403, u)
        self.assertEqual(self.c.get("/api/finance/report.pdf", headers=L).status_code, 403)   # no Finance area
        self.assertEqual(self.c.get("/api/fees/report.pdf", headers=L).status_code, 200)
        self.assertEqual(self.c.get("/api/fees/report.pdf?month=bad", headers=self.H).status_code, 400)
        self.assertTrue(self.sql_("SELECT 1 FROM audit_log WHERE action='export_fees_pdf'"))

    def test_09_pdf_text_has_the_numbers(self):
        try: from pypdf import PdfReader
        except ImportError: self.skipTest("pypdf not installed")
        r = self.c.get("/api/fees/report.pdf?month=2026-10", headers=self.H)
        txt = "".join(p.extract_text() for p in PdfReader(io.BytesIO(r.data)).pages)
        for s in ("Monthly fees report: Oct 2026", "Batch by batch", "Arabic Level 1", "Ustaz Ahmed", "1,500", "Who still has to pay", "Hassan Rasheed"):
            self.assertIn(s, txt)

    # ---------------- logo ----------------
    def test_10_logo_upload_show_remove(self):
        self.assertIsNone(self.c.get("/api/public/info").get_json()["logo_url"])
        self.assertEqual(self.c.get("/api/public/logo").status_code, 404)
        up = lambda data, name, h=self.H: self.c.post("/api/settings/logo", data={"file": (io.BytesIO(data), name)}, headers=h, content_type="multipart/form-data")
        self.assertEqual(up(b"%PDF-1.4 not a picture", "x.png").status_code, 400)
        self.assertEqual(up(b"\x89PNG\r\n\x1a\n" + b"x" * (1024 * 1024 + 5), "big.png").status_code, 413)
        self.assertEqual(up(png(), "logo.png", self.tok("t1@s48.test", PW)).status_code, 403)
        r = up(png(), "logo.png"); self.assertEqual(r.status_code, 200, r.get_json())
        url = self.c.get("/api/public/info").get_json()["logo_url"]
        self.assertTrue(url.startswith("/api/public/logo?v="))
        g = self.c.get(url); self.assertEqual((g.status_code, g.mimetype), (200, "image/png")); self.assertIn("max-age", g.headers["Cache-Control"])
        # on the PDFs (a report and a receipt) - they still build
        self.assertEqual(self.c.get("/api/fees/report.pdf?month=2026-10", headers=self.H).status_code, 200)
        pid = self.sql_("SELECT id FROM payments LIMIT 1")[0][0]
        self.assertEqual(self.c.get(f"/api/payments/{pid}/receipt.pdf", headers=self.H).status_code, 200)
        # the reset keeps it, like the settings (preview only here: check the logo row is not counted as data to delete is not needed)
        self.assertEqual(self.c.delete("/api/settings/logo", headers=self.H).status_code, 200)
        self.assertIsNone(self.c.get("/api/public/info").get_json()["logo_url"])
        self.assertEqual(self.c.get("/api/public/logo").status_code, 404)
        self.assertEqual(len(self.sql_("SELECT 1 FROM audit_log WHERE action='logo_change'")), 2)

    def test_11_upgrade_adds_the_column(self):
        import dbx
        self.assertIn("is_super", dbx.V0847_USER_COLUMNS[-1])
        self.assertIn("is_super", [r[1] for r in self.sql_("PRAGMA table_info(users)")])


if __name__ == "__main__":
    unittest.main()
