"""Session 20: activity log v2 helpers (no Flask here, so the migration script and tests can use it).

audit_log keeps its old columns; v2 adds user_role, login_id, course_id, batch_id, old_value, new_value, ip (all nullable).
backfill() fills what can be worked out for OLD rows, and only where the new column is still empty, so it is safe to run twice.
It never changes user_id, action, entity, entity_id, detail or at. Run it before the Session 21 triggers make the log read-only."""
import re

MSG = "audit_log is append-only: rows cannot be changed or deleted"
# SQLite. UPDATE is allowed only while a row sits in audit_unlock, which only backfill() below does, inside its own transaction
# (so the row is gone again after commit or rollback). DELETE is never allowed.
SQLITE_TRIGGERS = (
    f"CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log WHEN NOT EXISTS (SELECT 1 FROM audit_unlock) BEGIN SELECT RAISE(ABORT, '{MSG}'); END",
    f"CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log BEGIN SELECT RAISE(ABORT, '{MSG}'); END",
)
PG_TRIGGERS = f"""
CREATE OR REPLACE FUNCTION audit_log_guard() RETURNS trigger AS $fn$
BEGIN
  IF TG_OP = 'UPDATE' AND EXISTS (SELECT 1 FROM audit_unlock) THEN RETURN NEW; END IF;
  RAISE EXCEPTION '{MSG}';
END;
$fn$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS audit_log_guard_t ON audit_log;
CREATE TRIGGER audit_log_guard_t BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW EXECUTE PROCEDURE audit_log_guard();
"""


def install_triggers(conn):
    """Make audit_log append-only. Safe to run on every start. Needs the audit_unlock table (schema.sql). Does not commit."""
    if conn.pg: conn.raw.cursor().execute(PG_TRIGGERS)
    else:
        for sql in SQLITE_TRIGGERS: conn.execute(sql)


GRADE = re.compile(r"grade (\S+) -> (\S+)")
TO_BATCH = re.compile(r"to batch (\d+)")


def backfill(conn):
    """Returns {step: rows changed}. Does not commit."""
    n = {}
    conn.execute("INSERT INTO audit_unlock(flag) VALUES(1)")   # lifts the UPDATE guard for this transaction only; removed below (and by a rollback)

    def run(name, sql, args=()):
        n[name] = conn.execute(sql, args).rowcount
    # who did it: role and login ID from the user row (the user may have been deleted since; then they stay empty)
    run("user_role", "UPDATE audit_log SET user_role=(SELECT role FROM users WHERE users.id=audit_log.user_id) WHERE user_role IS NULL AND user_id IS NOT NULL")
    run("login_id", "UPDATE audit_log SET login_id=(SELECT login_id FROM users WHERE users.id=audit_log.user_id) WHERE login_id IS NULL AND user_id IS NOT NULL")
    run("system_rows", "UPDATE audit_log SET user_role='system' WHERE user_role IS NULL AND user_id IS NULL AND action='generate_invoices'")
    # which batch / course: only where the entity says so exactly
    run("batch_of_batch", "UPDATE audit_log SET batch_id=entity_id WHERE batch_id IS NULL AND entity='batch' AND entity_id IN (SELECT id FROM batches)")
    run("batch_of_enrollment", "UPDATE audit_log SET batch_id=(SELECT batch_id FROM enrollments WHERE enrollments.id=audit_log.entity_id) WHERE batch_id IS NULL AND entity='enrollment' AND entity_id IN (SELECT id FROM enrollments)")
    run("batch_of_assignment", "UPDATE audit_log SET batch_id=(SELECT batch_id FROM assignments WHERE assignments.id=audit_log.entity_id) WHERE batch_id IS NULL AND entity='assignment' AND entity_id IN (SELECT id FROM assignments)")
    run("batch_of_session", "UPDATE audit_log SET batch_id=(SELECT batch_id FROM sessions WHERE sessions.id=audit_log.entity_id) WHERE batch_id IS NULL AND entity='session' AND entity_id IN (SELECT id FROM sessions)")
    run("course_of_course", "UPDATE audit_log SET course_id=entity_id WHERE course_id IS NULL AND entity='course' AND entity_id IN (SELECT id FROM courses)")
    run("course_of_tutorial", "UPDATE audit_log SET course_id=(SELECT course_id FROM tutorials WHERE tutorials.id=audit_log.entity_id) WHERE course_id IS NULL AND entity='tutorial' AND entity_id IN (SELECT id FROM tutorials)")
    run("course_of_batch", "UPDATE audit_log SET course_id=(SELECT course_id FROM batches WHERE batches.id=audit_log.batch_id) WHERE course_id IS NULL AND batch_id IN (SELECT id FROM batches)")
    # old / new values that were written into the detail text by Sessions 17 (grades) and 13 (transfers)
    g = t = 0
    for r in conn.execute("SELECT id,action,detail,entity_id FROM audit_log WHERE old_value IS NULL AND new_value IS NULL AND action IN ('grade_change','grade','transfer')").fetchall():
        old = new = None
        if r["action"] in ("grade_change", "grade"):
            m = GRADE.search(r["detail"] or "")
            if m: old, new = (None if m.group(1) == "none" else m.group(1)), m.group(2); g += 1
        else:
            m = TO_BATCH.search(r["detail"] or "")
            e = conn.execute("SELECT batch_id FROM enrollments WHERE id=?", (r["entity_id"],)).fetchone() if m else None
            if m and e: old, new = str(e["batch_id"]), m.group(1); t += 1
        if old is not None or new is not None:
            conn.execute("UPDATE audit_log SET old_value=?, new_value=? WHERE id=?", (old, new, r["id"]))
    n["old_new_grades"], n["old_new_transfers"] = g, t
    conn.execute("DELETE FROM audit_unlock")
    return n
