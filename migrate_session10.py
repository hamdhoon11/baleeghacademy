"""Session 10 migration: course type and ID codes for an existing database (v0.8.7 or later).

  python migrate_session10.py                           # DRY RUN (default): shows every code it would give out, changes nothing
  python migrate_session10.py --apply --i-have-a-backup # does it

BACK UP THE DATABASE FIRST. SQLite: copy the .db file (and the uploads folder). Hosted PostgreSQL: use the provider's backup / snapshot
(for example Supabase: Database -> Backups) or `pg_dump "$DATABASE_URL" > backup.sql`.

What it does, in this order:
  1. Opens the app, which adds the new empty columns (courses.kind/code/is_active, students.student_code, teachers.teacher_code,
     enrollments.enrol_code) and unique indexes. This part is additive and also happens whenever the new version starts.
  2. Gives every existing course a code (AL1 from Arabic + Level 1) and sets is_active from its status (closed = inactive); kind stays 'course'.
  3. Gives every existing teacher BAL/T/NNN, every student BAL/<first course code>/NNN, every enrolment BAL/<course code>/ENNN, in id order.
It only fills EMPTY codes, never changes one that exists, never deletes anything, and is safe to run again (the second run finds nothing to do).
The dry run does the real work inside a transaction and rolls it back, so what it prints is exactly what --apply will do.
Needs the same environment as the web app (DATABASE_PATH or DATABASE_URL, SECRET_KEY). Load your .env first."""
import argparse, os, sys
import dbx, idcodes

BASE = os.path.dirname(os.path.abspath(__file__))
TABLES = ("users", "students", "teachers", "courses", "batches", "enrollments", "invoices", "payments", "assignments", "submissions")


def counts(conn):
    out = {}
    for t in TABLES:
        try: out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except Exception:
            conn.rollback(); out[t] = None
    return out


def run(conn, apply, log=print):
    """Returns (report, before, after). Commits only when apply is True."""
    before = counts(conn)
    rep = idcodes.fill_missing(conn)
    dup = idcodes.duplicates(conn)
    after = counts(conn)
    if dup:
        conn.rollback()
        raise SystemExit(f"STOPPED, nothing changed: duplicate codes would exist: {dup}")
    for k in ("courses", "teachers", "students", "enrollments", "login_ids"):   # login_ids: Session 11
        log(f"{k}: {len(rep[k])} code(s) to give out")
        for row in rep[k][:8]: log(f"    id {row[0]} -> {row[1]}")
        if len(rep[k]) > 8: log(f"    ... and {len(rep[k]) - 8} more")
    log(f"people profile rows created: {rep['profiles_created']}; courses set inactive (status closed): {rep['courses_deactivated']}")
    log("row counts before -> after: " + ", ".join(f"{t} {before[t]}->{after[t]}" for t in TABLES if before[t] is not None))
    if apply: conn.commit(); log("APPLIED.")
    else: conn.rollback(); log("DRY RUN: nothing was changed. Run again with --apply --i-have-a-backup to do it.")
    return rep, before, after


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="really write the codes (default is a dry run)")
    ap.add_argument("--i-have-a-backup", action="store_true", help="required with --apply")
    a = ap.parse_args(argv)
    if a.apply and not a.i_have_a_backup:
        sys.exit("Refusing to run: take a backup of the database first, then add --i-have-a-backup.")
    from app import create_app
    app = create_app()                      # adds the columns and indexes (step 1)
    conn = dbx.connect(app.config, BASE)
    try: run(conn, a.apply)
    finally: conn.close()


if __name__ == "__main__":
    main()
