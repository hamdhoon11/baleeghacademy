"""Session 13: transfer and withdrawal history (table enrollment_events) and the admin report.

record_event()  - called by app.py whenever an enrolment is transferred or set to 'dropped'.
backfill()      - used by migrate_session13.py: writes an event for every old 'dropped' enrolment that has none,
                  using the audit_log row for the real date when one exists. Safe to run twice.
register()      - GET /api/enrollment-events and /api/enrollment-events.csv (admin, permission 'enrollments').
"""
import csv, datetime as dt, io, re
from flask import Response, g, jsonify, request

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def clean_date(v, default):
    """'YYYY-MM-DD' that is a real date, or the default when empty. Raises ValueError otherwise."""
    v = (v or "").strip() if isinstance(v, str) or v is None else str(v)
    if not v: return default
    if not DATE.match(v): raise ValueError("Date must look like 2026-03-31")
    dt.date.fromisoformat(v)
    return v


def record_event(conn, student_id, from_batch_id, to_batch_id, kind, effective_date, reason, by_user, at):
    reason = (reason or "").strip()[:500] or None
    return conn.execute("INSERT INTO enrollment_events(student_id,from_batch_id,to_batch_id,kind,effective_date,reason,by_user,at) VALUES(?,?,?,?,?,?,?,?)",
                        (student_id, from_batch_id, to_batch_id, kind, effective_date, reason, by_user, at)).lastrowid


def backfill(conn):
    """Old dropped enrolments get one event each. Returns a list of the events written (dicts) for the report."""
    out = []
    for e in conn.execute("SELECT e.id,e.student_id,e.batch_id,e.enrolled_at,b.course_id FROM enrollments e JOIN batches b ON b.id=e.batch_id "
                          "WHERE e.status='dropped' AND NOT EXISTS (SELECT 1 FROM enrollment_events v WHERE v.student_id=e.student_id AND v.from_batch_id=e.batch_id) ORDER BY e.id").fetchall():
        eid, sid, bid, enrolled, cid = e[0], e[1], e[2], e[3], e[4]
        tr = conn.execute("SELECT user_id,detail,at FROM audit_log WHERE action='transfer' AND entity='enrollment' AND entity_id=? ORDER BY id DESC", (eid,)).fetchone()
        dr = None if tr else conn.execute("SELECT user_id,detail,at FROM audit_log WHERE action='enrollment_status' AND entity='enrollment' AND entity_id=? AND detail='dropped' ORDER BY id DESC", (eid,)).fetchone()
        kind, to_b, why, when, who = "withdrawal", None, "Backfilled: date unknown", None, None
        if tr:
            m = re.search(r"to batch (\d+)", tr[1] or "")
            kind, to_b, when, who, why = "transfer", int(m.group(1)) if m else None, tr[2], tr[0], "Backfilled from the activity log"
        elif dr:
            when, who, why = dr[2], dr[0], "Backfilled from the activity log"
        else:   # no log row: a later enrolment of the same student in another batch of the same course looks like a transfer
            nxt = conn.execute("SELECT x.batch_id,x.enrolled_at FROM enrollments x JOIN batches xb ON xb.id=x.batch_id WHERE x.student_id=? AND x.batch_id!=? AND xb.course_id=? "
                               "AND x.status IN ('active','completed') AND x.enrolled_at>=? ORDER BY x.enrolled_at LIMIT 1", (sid, bid, cid, enrolled)).fetchone()
            if nxt: kind, to_b, why, when = "transfer", nxt[0], "Backfilled: inferred from a later enrolment, date approximate", nxt[1]
        eff = (when or "")[:10] or None
        record_event(conn, sid, bid, to_b, kind, eff, why, who, when or enrolled)
        out.append({"enrollment_id": eid, "student_id": sid, "from_batch_id": bid, "to_batch_id": to_b, "kind": kind, "effective_date": eff})
    return out


SQL = ("SELECT v.id,v.student_id,u.full_name AS student_name,s.student_code,v.kind,v.effective_date,v.reason,v.at,"
       "v.from_batch_id,fb.code AS from_batch_code,fc.name AS from_course,v.to_batch_id,tb.code AS to_batch_code,tc.name AS to_course,"
       "v.by_user,bu.full_name AS by_name "
       "FROM enrollment_events v JOIN users u ON u.id=v.student_id LEFT JOIN students s ON s.user_id=v.student_id "
       "LEFT JOIN batches fb ON fb.id=v.from_batch_id LEFT JOIN courses fc ON fc.id=fb.course_id "
       "LEFT JOIN batches tb ON tb.id=v.to_batch_id LEFT JOIN courses tc ON tc.id=tb.course_id LEFT JOIN users bu ON bu.id=v.by_user")


def register(app, c):
    db, rows, err, auth, audit = c.db, c.rows, c.err, c.auth, c.audit

    def query():
        w, a = [], []
        a_from, a_to = request.args.get("from"), request.args.get("to")
        for v in (a_from, a_to):
            if v and not DATE.match(v): return None, err("Dates must look like 2026-03-31")
        if a_from: w.append("v.effective_date>=?"); a.append(a_from)
        if a_to: w.append("v.effective_date<=?"); a.append(a_to)
        kind = request.args.get("kind")
        if kind:
            if kind not in ("transfer", "withdrawal"): return None, err("kind must be transfer or withdrawal")
            w.append("v.kind=?"); a.append(kind)
        for key, col in (("student_id", "v.student_id"), ("batch_id", None)):
            v = request.args.get(key, type=int)
            if v and col: w.append(f"{col}=?"); a.append(v)
            elif v: w.append("(v.from_batch_id=? OR v.to_batch_id=?)"); a += [v, v]
        return rows(SQL + (" WHERE " + " AND ".join(w) if w else "") + " ORDER BY COALESCE(v.effective_date,'0000') DESC, v.id DESC LIMIT 5000", a), None

    @app.get("/api/enrollment-events")
    @auth("admin", perm="enrollments")
    def ev_list():
        r, e = query()
        return e or jsonify(r)

    def ev_export(ext):
        import excelio
        r, e = query()
        if e: return e
        head = ["date", "type", "student_id", "student", "previous_course", "previous_batch", "new_course", "new_batch", "reason", "recorded_by", "recorded_at"]
        table = [[x["effective_date"], x["kind"], x["student_code"], x["student_name"], x["from_course"], x["from_batch_code"], x["to_course"], x["to_batch_code"], x["reason"], x["by_name"], x["at"]] for x in r]
        audit(f"export_enrollment_events_{ext}", "report", None, f"{len(r)} rows"); db().commit()
        return excelio.send_table(ext, "transfers-withdrawals", head, table, "Transfers and withdrawals")

    @app.get("/api/enrollment-events.csv")
    @auth("admin", perm="enrollments")
    def ev_csv(): return ev_export("csv")

    @app.get("/api/enrollment-events.xlsx")
    @auth("admin", perm="enrollments")
    def ev_xlsx(): return ev_export("xlsx")   # v0.8.38
