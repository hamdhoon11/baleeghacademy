"""v0.8.61: an admin can remove a person who already has records. Money records stay under their name."""
import os, sys, tempfile, unittest, sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class RemovePerson(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        cls.path = os.path.join(tmp, "t.db")
        os.environ["DATABASE_PATH"] = cls.path
        os.environ["ADMIN_EMAIL"] = "admin@rm.test"
        os.environ["ADMIN_PASSWORD"] = "AdminPass123"
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path})
        cls.sql("UPDATE users SET must_change_password=0")

    @classmethod
    def sql(cls, q, a=()):
        c = sqlite3.connect(cls.path); c.row_factory = sqlite3.Row
        r = c.execute(q, a).fetchall(); c.commit(); c.close(); return r

    def setUp(self): self.c = self.app.test_client()

    def login(self, email, pw):
        r = self.c.post("/api/auth/login", json={"email": email, "password": pw})
        return {"Authorization": "Bearer " + (r.get_json() or {}).get("token", "x")}

    def adm(self): return self.login("admin@rm.test", "AdminPass123")
    def J(self, m, url, h=None, **kw): return getattr(self.c, m)(url, headers=h or self.adm(), **kw)
    n = 0

    def mk(self, role="student", fee=None):
        RemovePerson.n += 1
        e = f"p{self.n}@rm.test"
        r = self.J("post", "/api/users", json={"email": e, "password": "Password123", "full_name": f"Person {self.n}", "role": role,
                                               "phone": "7771234", "guardian_phone": "7771234"})
        self.assertEqual(r.status_code, 201, r.get_json())
        self.sql("UPDATE users SET must_change_password=0")
        return r.get_json()["id"], e

    def enrolled(self):
        sid, e = self.mk()
        bid = self.J("get", "/api/batches").get_json()[0]["id"]
        r = self.J("post", "/api/enrollments", json={"student_id": sid, "batch_id": bid})
        self.assertEqual(r.status_code, 201, r.get_json())
        return sid, e, bid

    def test_01_every_reference_to_users_has_a_decision(self):
        import removeperson
        c = sqlite3.connect(self.path)
        missing = []
        for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            for fk in c.execute(f"PRAGMA foreign_key_list({t})"):
                if fk[2] == "users" and (t, fk[3]) not in removeperson.PLAN: missing.append((t, fk[3]))
        c.close()
        self.assertEqual(missing, [], "add these to removeperson.PLAN")

    def test_02_student_with_records_removed_money_kept(self):
        sid, e, bid = self.enrolled()
        inv = self.sql("SELECT id, amount_due_mvr FROM invoices WHERE student_id=?", (sid,))
        self.assertTrue(inv, "enrolment should make an invoice")
        before_total = self.sql("SELECT COUNT(*) n, COALESCE(SUM(amount_due_mvr),0) s FROM invoices")[0]
        self.sql("INSERT INTO notifications(user_id,kind,title,created_at) VALUES(?,?,?,datetime('now'))", (sid, "x", "hi"))
        p = self.J("get", f"/api/users/{sid}/removal").get_json()
        self.assertTrue(p["has_records"]); self.assertEqual(p["blocked"], [])
        self.assertIn("enrollments", [d["table"] for d in p["deleted"]])
        self.assertEqual(p["kept"]["invoices"], len(inv))
        # no password, wrong password: nothing happens
        r = self.J("delete", f"/api/users/{sid}")
        self.assertEqual((r.status_code, r.get_json().get("code")), (400, "password_needed"))
        self.assertEqual(self.J("delete", f"/api/users/{sid}", json={"password": "nope"}).status_code, 403)
        self.assertEqual(self.J("get", f"/api/users/{sid}").status_code, 200)
        r = self.J("delete", f"/api/users/{sid}", json={"password": "AdminPass123"})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(self.J("get", f"/api/users/{sid}").status_code, 404)
        self.assertEqual(self.sql("SELECT COUNT(*) n FROM enrollments WHERE student_id=?", (sid,))[0]["n"], 0)
        self.assertEqual(self.sql("SELECT COUNT(*) n FROM notifications WHERE user_id=?", (sid,))[0]["n"], 0)
        after = self.sql("SELECT COUNT(*) n, COALESCE(SUM(amount_due_mvr),0) s FROM invoices")[0]
        self.assertEqual(tuple(before_total), tuple(after))
        kept = self.sql("SELECT student_id, customer_name, enrollment_id FROM invoices WHERE id=?", (inv[0]["id"],))[0]
        self.assertEqual((kept["student_id"], kept["customer_name"], kept["enrollment_id"]), (None, f"Person {self.n}", None))
        # the Fees list still shows it under the name
        rows = self.J("get", "/api/invoices?q=" + f"Person {self.n}").get_json()
        rows = rows.get("items", rows) if isinstance(rows, dict) else rows
        self.assertTrue(any(x["id"] == inv[0]["id"] for x in rows))
        log = self.sql("SELECT detail FROM audit_log WHERE action='delete_user' ORDER BY id DESC LIMIT 1")[0]["detail"]
        self.assertIn("enrollments 1", log)
        self.assertEqual(self.J("get", "/api/batches").status_code, 200)

    def test_03_no_records_needs_no_password(self):
        uid, _ = self.mk()
        self.assertFalse(self.J("get", f"/api/users/{uid}/removal").get_json()["has_records"])
        self.assertEqual(self.J("delete", f"/api/users/{uid}").status_code, 200)

    def test_04_teacher_batches_kept_without_teacher(self):
        tid, _ = self.mk("teacher")
        bid = self.J("get", "/api/batches").get_json()[0]["id"]
        self.sql("UPDATE batches SET teacher_id=? WHERE id=?", (tid, bid))
        r = self.J("delete", f"/api/users/{tid}", json={"password": "AdminPass123"})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertIsNone(self.sql("SELECT teacher_id FROM batches WHERE id=?", (bid,))[0]["teacher_id"])

    def test_05_teacher_with_pay_records_refused(self):
        tid, _ = self.mk("teacher")
        self.sql("INSERT INTO teacher_payments(teacher_id,amount_mvr,paid_on,method,created_at) VALUES(?,100,'2026-11-01','cash',datetime('now'))", (tid,))
        p = self.J("get", f"/api/users/{tid}/removal").get_json()
        self.assertEqual(p["blocked"], ["teacher_payments"])
        r = self.J("delete", f"/api/users/{tid}", json={"password": "AdminPass123"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.J("get", f"/api/users/{tid}").status_code, 200)

    def test_06_limited_admin_and_self(self):
        sid, _, _ = self.enrolled()
        aid, ae = self.mk("admin")
        self.J("patch", f"/api/users/{aid}", json={"permissions": ["courses"]})
        h = self.login(ae, "Password123")
        self.assertEqual(self.J("delete", f"/api/users/{sid}", h, json={"password": "Password123"}).status_code, 403)
        self.assertEqual(self.J("get", f"/api/users/{sid}/removal", h).status_code, 403)
        me = self.c.get("/api/auth/me", headers=self.adm()).get_json()["user"]["id"]
        self.assertEqual(self.J("delete", f"/api/users/{me}", json={"password": "AdminPass123"}).status_code, 400)
        self.assertTrue(self.J("get", f"/api/users/{me}/removal").get_json()["refused"])


if __name__ == "__main__":
    unittest.main()
