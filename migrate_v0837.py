"""v0.8.37 migration: tutorial grading (marks and comments on tutorial answers) and recurring expenses.

  python migrate_v0837.py                            # DRY RUN (default): shows what would change, changes nothing
  python migrate_v0837.py --apply                    # SQLite: makes a backup copy next to the .db file first, then applies
  python migrate_v0837.py --apply --i-have-a-backup  # hosted PostgreSQL: take the provider's backup (or pg_dump) first

What it does, additive only:
  tutorials            + max_points  (marks out of; existing tutorials get 100, the teacher can post new ones as "comments only")
  tutorial_submissions + grade, feedback, graded_by, graded_at (empty for every existing answer: nothing is graded until a teacher does it)
  expenses             + recurring_id, recurring_month (empty for every existing expense)
The two new tables (recurring_expenses, recurring_done) are created empty when the new version starts.
No row is deleted or changed otherwise; the script checks the row counts and every existing answer's text before committing and stops if
anything moved. Starting the new version of the portal does the same additions automatically; this script lets you see it first and keep a backup.
Safe to run twice (the second run finds nothing to add). Needs the same environment (DATABASE_PATH or DATABASE_URL) as the web app."""
import argparse, datetime as dt, hashlib, os, shutil, sys
import dbx

BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(BASE, "instance", "portal.db")


def fingerprint(conn):
    """Counts and a hash of every existing answer and tutorial: what must be identical after the change."""
    h = hashlib.sha256()
    for r in conn.execute("SELECT id,tutorial_id,student_id,text_answer,file,submitted_at FROM tutorial_submissions ORDER BY id").fetchall(): h.update(repr(dbx.values(r)).encode())
    for r in conn.execute("SELECT id,title,body,course_id,file,uploaded_by FROM tutorials ORDER BY id").fetchall(): h.update(repr(dbx.values(r)).encode())
    for r in conn.execute("SELECT id,expense_date,amount_mvr,category_id,description FROM expenses ORDER BY id").fetchall(): h.update(repr(dbx.values(r)).encode())
    n = lambda t: conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
    return {"tutorials": n("tutorials"), "answers": n("tutorial_submissions"), "expenses": n("expenses"), "users": n("users"), "hash": h.hexdigest()}


def missing(conn):
    return [(t, c, d) for t, c, d in dbx.V0837_COLUMNS if c not in conn.columns(t)]


def run(conn, apply, log=print):
    todo = missing(conn)
    before = fingerprint(conn)
    log(f"Found {before['tutorials']} tutorial(s), {before['answers']} answer(s) and {before['expenses']} expense(s).")
    if not todo:
        log("Nothing to add: this database already has the v0.8.37 columns."); conn.rollback(); return []
    for t, c, d in todo: log(f"  add column {t}.{c} {d}")
    if not conn.pg and not conn.raw.in_transaction: conn.raw.execute("BEGIN")   # SQLite: without this, Python commits ALTER TABLE at once and a dry run could not undo it
    for t, c, d in todo: conn.execute(f"ALTER TABLE {t} ADD COLUMN {c} {dbx.schema_to_pg(d) if conn.pg else d}")
    after = fingerprint(conn)
    if after != before:
        conn.rollback(); raise SystemExit("STOPPED, nothing changed: existing tutorials, answers or expenses looked different after the change.")
    if "max_points" in [c for _, c, _ in todo]:
        n = conn.execute("SELECT COUNT(*) AS n FROM tutorials WHERE max_points=100").fetchone()["n"]
        log(f"  {n} existing tutorial(s) will be marked out of 100; all {after['answers']} answer(s) stay ungraded.")
    if apply: conn.commit(); log("APPLIED.")
    else: conn.rollback(); log("DRY RUN: nothing was changed. Run again with --apply to do it.")
    return todo


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true"); ap.add_argument("--i-have-a-backup", action="store_true")
    a = ap.parse_args(argv)
    url, path = os.environ.get("DATABASE_URL", ""), os.environ.get("DATABASE_PATH", DEFAULT_DB)
    pg = dbx.is_postgres(url)
    if not pg and not os.path.exists(path): sys.exit(f"No database at {path}. Set DATABASE_PATH (or DATABASE_URL for PostgreSQL).")
    if a.apply and pg and not a.i_have_a_backup:
        sys.exit("Refusing to run: take a backup of the PostgreSQL database first (provider snapshot or pg_dump), then add --i-have-a-backup.")
    if a.apply and not pg:
        copy = f"{path}.before-v0.8.37-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.bak"
        shutil.copy2(path, copy); print(f"Backup written: {copy}")
    conn = dbx.connect({"DATABASE_URL": url, "DATABASE_PATH": path}, BASE)
    try: run(conn, a.apply)
    finally: conn.close()


if __name__ == "__main__":
    main()
