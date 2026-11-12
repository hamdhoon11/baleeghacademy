"""v0.8.33 (UI correction sessions 1-22): the small server additions the screens rely on.
- GET /api/audit accepts ?offset= so the Activity log can ask for one row more than a page (Session 13).
- GET /api/public/info tells the forms the real upload limits (Session 21).
- Notification links are "tab:id" (Session 16) - covered in test_session28 (test_02, test_07, test_20a)."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_session28 import make_app  # noqa: E402


class Session33(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app, cls.c, cls.H, cls.path = make_app("a33")
        for i in range(7): cls.c.post("/api/courses", json={"name": f"Course {i}", "monthly_fee_mvr": 100, "status": "open"}, headers=cls.H)

    def test_01_audit_offset_gives_one_extra_row_without_skipping(self):
        allrows = self.c.get("/api/audit?per_page=500", headers=self.H).get_json()
        self.assertGreaterEqual(len(allrows), 8)
        per = 3
        p1 = self.c.get(f"/api/audit?per_page={per + 1}&offset=0", headers=self.H).get_json()
        p2 = self.c.get(f"/api/audit?per_page={per + 1}&offset={per}", headers=self.H).get_json()
        self.assertEqual(len(p1), per + 1)                                   # the extra row says "there is a next page"
        self.assertEqual([r["id"] for r in p1[:per]], [r["id"] for r in allrows[:per]])
        self.assertEqual([r["id"] for r in p2[:per]], [r["id"] for r in allrows[per:2 * per]])   # page 2 starts right after page 1: nothing skipped
        self.assertEqual(p1[per]["id"], p2[0]["id"])
        last = self.c.get(f"/api/audit?per_page={per + 1}&offset={len(allrows) - 2}", headers=self.H).get_json()
        self.assertEqual(len(last), 2)                                       # fewer than per+1: no next page
        self.assertEqual(self.c.get("/api/audit?offset=x", headers=self.H).status_code, 400)
        self.assertEqual(self.c.get("/api/audit?page=2&per_page=3", headers=self.H).get_json()[0]["id"], allrows[3]["id"])   # page still works

    def test_02_public_info_has_upload_limits(self):
        i = self.c.get("/api/public/info").get_json()
        self.assertIsInstance(i["upload_max_mb"], int); self.assertIsInstance(i["learning_max_mb"], int)
        self.assertGreaterEqual(i["upload_max_mb"], 4); self.assertLessEqual(i["upload_max_mb"], 5)


if __name__ == "__main__":
    unittest.main()
