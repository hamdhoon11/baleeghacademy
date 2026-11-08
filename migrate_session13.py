"""Session 13 migration: history of transfers and withdrawals (table enrollment_events) for an existing database (v0.8.12 or later).

  python migrate_session13.py                           # DRY RUN (default): shows every event it would write, changes nothing
  python migrate_session13.py --apply --i-have-a-backup # does it

BACK UP THE DATABASE FIRST. SQLite: copy the .db file (and the uploads folder). Hosted PostgreSQL: use the provider's backup / snapshot
(for example Supabase: Database -> Backups) or `pg_dump "$DATABASE_URL" > backup.sql`.

What it does:
  1. Opens the app, which creates the new empty table enrollment_events (additive; also happens whenever the new version starts).
  2. For every enrolment that is already 'dropped' and has no event yet, writes one event:
       - a row in the activity log for a transfer or a drop gives the real date, the admin and (for a transfer) the new batch;
       - otherwise, a later enrolment of the same student in another batch of the same course is taken as a transfer (date approximate);
       - otherwise it is a withdrawal with an unknown date. Every such row is marked 'Backfilled' in its reason.
It never changes or deletes an enrolment, attendance, submission or grade. Safe to run twice (the second run finds nothing to do).
The dry run does the real work inside a transaction and rolls it back, so what it prints is exactly what --apply will do.
Needs the same environment as the web app (DATABASE_PATH or DATABASE_URL, SECRET_KEY). Load your .env first."""
import argparse, os, sys
import dbx, transfers

BASE = os.path.dirname(os.path.abspath(__file__))


def run(conn, apply, log=print):
    """Returns (events written, count before, count after). Commits only when apply is True."""
    before = conn.execute("SELECT COUNT(*) FROM enrollment_events").fetchone()[0]
    enrol = conn.execute("SELECT COUNT(*) FROM enrollments").fetchone()[0]
    ev = transfers.backfill(conn)
    after = conn.execute("SELECT COUNT(*) FROM enrollment_events").fetchone()[0]
    now_enrol = conn.execute("SELECT COUNT(*) FROM enrollments").fetchone()[0]
    if now_enrol != enrol:
        conn.rollback(); raise SystemExit("STOPPED, nothing changed: the enrolment count moved, which must never happen.")
    log(f"dropped enrolments without an event: {len(ev)} ({sum(1 for e in ev if e['kind'] == 'transfer')} transfer(s), {sum(1 for e in ev if e['kind'] == 'withdrawal')} withdrawal(s))")
    for e in ev[:10]: log(f"    enrolment {e['enrollment_id']} student {e['student_id']}: {e['kind']} from batch {e['from_batch_id']} to {e['to_batch_id']} on {e['effective_date'] or 'unknown date'}")
    if len(ev) > 10: log(f"    ... and {len(ev) - 10} more")
    log(f"enrollment_events rows {before} -> {after}; enrolments {enrol} -> {now_enrol}")
    if apply: conn.commit(); log("APPLIED.")
    else: conn.rollback(); log("DRY RUN: nothing was changed. Run again with --apply --i-have-a-backup to do it.")
    return ev, before, after


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="really write the events (default is a dry run)")
    ap.add_argument("--i-have-a-backup", action="store_true", help="required with --apply")
    a = ap.parse_args(argv)
    if a.apply and not a.i_have_a_backup:
        sys.exit("Refusing to run: take a backup of the database first, then add --i-have-a-backup.")
    from app import create_app
    app = create_app()                      # creates the table (step 1)
    conn = dbx.connect(app.config, BASE)
    try: run(conn, a.apply)
    finally: conn.close()


if __name__ == "__main__":
    main()
