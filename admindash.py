"""Session 25: admin dashboard, one endpoint with filters.

  GET /api/admin/dashboard   ?course_id=&batch_id=&kind=course|tuition&teacher_id=&date_from=&date_to=   (any admin)

Academic cards (always): students, teachers, courses, tuition_classes, batches, admissions (pending / received), classes held / upcoming / cancelled,
assignments, tests, submissions, graded, pending_grading, tutorials. Financial cards only for an admin with area "finance"; fee notices only with "fees".
No date range = all time. Dates are Maldives days.

One query layer: the filters first pick a set of batches (`scope`), and every card is counted for that set. Nothing is counted a second way:
class and assignment numbers come from learning.scope_counts() (which uses assign_counts() from Session 18), money from finance.py (Session 24).

Definitions (so a hand count matches):
  students      distinct ACTIVE student accounts with an active enrolment in a scope batch (student_accounts = all active student accounts, unfiltered)
  teachers      distinct ACTIVE teacher accounts assigned to an open/running scope batch (teacher_accounts = all active teacher accounts, unfiltered)
  batches       scope batches with status open or running; courses / tuition_classes = distinct courses of those batches, by courses.kind
  admissions    pending = applications with status pending in scope (dates ignored); received = applications created in the date range
  classes       held / cancelled sessions by session_date in range; upcoming = timetable occurrences from today (28 days, or up to date_to)
  assignments   given (created) in the date range; submissions / graded / pending_grading belong to those assignments
  tutorials     tutorials of the scope's courses (all tutorials when no filter is set) created in the range
  revenue / outstanding  the same scope (course, batch, teacher, kind); expenses are academy wide (only the dates apply)"""
import datetime as dt
from flask import g, jsonify, request
import auditview


def register(app, c, today):
    db, rows, one, err, auth = c.db, c.rows, c.one, c.err, c.auth

    def parse(a):
        """Validated filters. Raises ValueError with a message fit to show."""
        f = {}
        for k in ("course_id", "batch_id", "teacher_id"):
            if a.get(k):
                try: f[k] = int(a[k])
                except ValueError: raise ValueError("Bad " + k.replace("_", " "))
        if a.get("kind"):
            if a["kind"] not in ("course", "tuition"): raise ValueError("kind must be course or tuition")
            f["kind"] = a["kind"]
        for k in ("date_from", "date_to"):
            if a.get(k):
                try: f[k] = dt.date.fromisoformat(a[k]).isoformat()
                except ValueError: raise ValueError("Dates must look like 2027-03-31")
        if f.get("date_from") and f.get("date_to") and f["date_from"] > f["date_to"]: raise ValueError("The start date is after the end date")
        return f

    def scope(f):
        w, a = [], []
        if "course_id" in f: w.append("b.course_id=?"); a.append(f["course_id"])
        if "batch_id" in f: w.append("b.id=?"); a.append(f["batch_id"])
        if "teacher_id" in f: w.append("b.teacher_id=?"); a.append(f["teacher_id"])
        if "kind" in f: w.append("c.kind=?"); a.append(f["kind"])
        return rows("SELECT b.id,b.course_id,b.status,b.teacher_id,c.kind FROM batches b JOIN courses c ON c.id=b.course_id" + (" WHERE " + " AND ".join(w) if w else ""), tuple(a))

    marks = lambda n: ",".join("?" * n)

    @app.get("/api/admin/dashboard")
    @auth("admin")
    def admin_dashboard():
        try: f = parse(request.args)
        except ValueError as x: return err(str(x))
        d1, d2 = f.get("date_from"), f.get("date_to")
        bs = scope(f); bids = [b["id"] for b in bs]
        active = [b for b in bs if b["status"] in ("open", "running")]
        out = {"filters": f}
        # people, courses, batches
        out["students"] = one(f"SELECT COUNT(DISTINCT e.student_id) n FROM enrollments e JOIN users u ON u.id=e.student_id WHERE e.status='active' AND u.is_active=1 AND u.role='student' AND e.batch_id IN ({marks(len(bids))})", tuple(bids))["n"] if bids else 0
        tids = sorted({b["teacher_id"] for b in active if b["teacher_id"]})
        out["teachers"] = one(f"SELECT COUNT(*) n FROM users WHERE role='teacher' AND is_active=1 AND id IN ({marks(len(tids))})", tuple(tids))["n"] if tids else 0
        out["batches"] = len(active)
        out["courses"] = len({b["course_id"] for b in active if b["kind"] == "course"})
        out["tuition_classes"] = len({b["course_id"] for b in active if b["kind"] == "tuition"})
        out["student_accounts"] = one("SELECT COUNT(*) n FROM users WHERE role='student' AND is_active=1")["n"]
        out["teacher_accounts"] = one("SELECT COUNT(*) n FROM users WHERE role='teacher' AND is_active=1")["n"]
        # admissions
        aw, aa = [], []
        if "course_id" in f: aw.append("a.course_id=?"); aa.append(f["course_id"])
        if "batch_id" in f: aw.append("a.batch_id=?"); aa.append(f["batch_id"])
        if "teacher_id" in f: aw.append("a.batch_id IN (SELECT id FROM batches WHERE teacher_id=?)"); aa.append(f["teacher_id"])
        if "kind" in f: aw.append("a.course_id IN (SELECT id FROM courses WHERE kind=?)"); aa.append(f["kind"])
        base = "SELECT COUNT(*) n FROM applications a" + "".join(f" AND {x}" if i else f" WHERE {x}" for i, x in enumerate(aw))
        glue = " AND " if aw else " WHERE "
        out["admissions_pending"] = one(base + glue + "a.status='pending'", tuple(aa))["n"]
        rw, ra = "", []
        if d1: rw += " AND a.created_at>=?"; ra.append(auditview.utc_bounds(d1))
        if d2: rw += " AND a.created_at<?"; ra.append(auditview.utc_bounds(d2, end=True))
        out["admissions_received"] = one(base + (glue + "1=1" + rw), tuple(aa + ra))["n"]
        # classes and assignments: the shared functions
        out.update(app.extensions["scope_counts"](bids, d1, d2))
        # tutorials
        tw, ta = "", []
        if any(k in f for k in ("course_id", "batch_id", "teacher_id", "kind")):
            cids = sorted({b["course_id"] for b in bs})
            tw = f" WHERE course_id IN ({marks(len(cids))})" if cids else " WHERE 1=0"; ta = list(cids)
        if d1: tw += (" AND" if tw else " WHERE") + " created_at>=?"; ta.append(auditview.utc_bounds(d1))
        if d2: tw += (" AND" if tw else " WHERE") + " created_at<?"; ta.append(auditview.utc_bounds(d2, end=True))
        out["tutorials"] = one("SELECT COUNT(*) n FROM tutorials" + tw, tuple(ta))["n"]
        # money (finance area) and fee notices (fees area)
        if c.has_perm(g.user, "finance"):
            fin = app.extensions["finance"]
            rev, _ = fin["collected"]({k: str(v) for k, v in f.items()})
            exp = fin["expenses_total"](d1, d2)
            out["financial"] = {"revenue": rev, "expenses": exp, "net": rev - exp, "outstanding": fin["outstanding"]({k: str(v) for k, v in f.items() if k not in ("date_from", "date_to")})}
            ap = app.extensions["earnings"]["approved_in"]((d1 or "0000-00")[:7], (d2 or "9999-12")[:7])   # Session 31: approved months only
            out["financial"].update(teacher_earnings=int(ap["t"]), academy_revenue=int(ap["a"]))
        if c.has_perm(g.user, "fees"):
            fx = app.extensions.get("fees", {}).get("dashboard")
            if fx: out["fees"] = {k: v for k, v in fx().items() if k != "month_collection_mvr"}
        # filter choices (no need for the People permission to fill the dropdowns)
        out["options"] = {"courses": rows("SELECT id,name,kind FROM courses ORDER BY name"),
                          "batches": rows("SELECT b.id,b.code,c.name AS course_name FROM batches b JOIN courses c ON c.id=b.course_id ORDER BY c.name,b.code"),
                          "teachers": rows("SELECT id,full_name FROM users WHERE role='teacher' AND is_active=1 ORDER BY full_name")}
        return jsonify(out)
