"""Session 20 migration: activity log v2 (new columns on audit_log) for an existing database (v0.8.19 or earlier).

  python migrate_session20.py                           # DRY RUN (default): shows how many old rows would be filled, changes nothing
  python migrate_session20.py --apply --i-have-a-backup # does it

BACK UP THE DATABASE FIRST. SQLite: copy the .db file. Hosted PostgreSQL: the provider's backup / snapshot or `pg_dump "$DATABASE_URL" > backup.sql`.

What it does:
  1. Opens the app, which adds the seven empty columns to audit_log (additive; also happens whenever the new version starts).
  2. Fills them for old rows where it can be worked out exactly: role and login ID from the user, batch and course from the entity,
     old/new values from the grade and transfer text. Rows it cannot work out stay empty and stay readable.
Nothing is deleted and no old column is changed. Safe to run twice (the second run finds nothing to do).
The dry run does the real work inside a transaction and rolls it back. Needs the same environment as the web app (DATABASE_PATH or DATABASE_URL, SECRET_KEY)."""
import argparse, os, sys
import dbx, auditlog

BASE = os.path.dirname(os.path.abspath(__file__))


def run(conn, apply, log=print):
    """Returns (changes per step, rows before, rows after). Commits only when apply is True."""
    before = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    ch = auditlog.backfill(conn)
    after = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    if after != before:
        conn.rollback(); raise SystemExit("STOPPED, nothing changed: the log row count moved, which must never happen.")
    for k, v in ch.items(): log(f"  {k}: {v} row(s)")
    log(f"audit_log rows {before} -> {after}")
    if apply: conn.commit(); log("APPLIED.")
    else: conn.rollback(); log("DRY RUN: nothing was changed. Run again with --apply --i-have-a-backup to do it.")
    return ch, before, after


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="really fill the columns (default is a dry run)")
    ap.add_argument("--i-have-a-backup", action="store_true", help="required with --apply")
    a = ap.parse_args(argv)
    if a.apply and not a.i_have_a_backup:
        sys.exit("Refusing to run: take a backup of the database first, then add --i-have-a-backup.")
    from app import create_app
    app = create_app()                      # adds the columns (step 1)
    conn = dbx.connect(app.config, BASE)
    try: run(conn, a.apply)
    finally: conn.close()


if __name__ == "__main__":
    main()
