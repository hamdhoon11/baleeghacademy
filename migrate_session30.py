"""Session 30 migration: teacher earnings (table teacher_earnings) and a first calculation of every past month that has payments.

  python migrate_session30.py                           # DRY RUN (default): prints what it would calculate, changes nothing
  python migrate_session30.py --apply --i-have-a-backup # does it

BACK UP THE DATABASE FIRST. SQLite: copy the .db file. Hosted PostgreSQL: the provider's backup/snapshot or `pg_dump "$DATABASE_URL" > backup.sql`.

What it does: (1) opening the app creates the new empty table (additive, also happens whenever the new version starts);
(2) for each month that has payments up to this month, writes DRAFT rows (one per batch) using the Teacher earnings setting (default 50%).
Drafts are not approved and nothing is paid; you review them in Finance before Session 31's approval. It never changes payments, invoices,
enrolments or an approved month. Safe to run twice (the second run only refreshes drafts). Needs the same environment as the web app."""
import argparse, os, sys, datetime as dt
import dbx, earnings, settings_schema as SS

BASE = os.path.dirname(os.path.abspath(__file__))


def run(conn, apply, log=print, this_month=None):
    q = lambda s, a=(): [dbx.values(r) for r in conn.execute(s, a).fetchall()]   # v0.8.40: tuple(r) is the column names on PostgreSQL
    x = lambda s, a=(): conn.execute(s, a)
    try: pct = int((q("SELECT value FROM settings WHERE key='revenue_share_percent'") or [("",)])[0][0] or "")
    except ValueError: pct = int(SS.default_of("revenue_share_percent"))
    months = sorted({r[0] for r in q("SELECT SUBSTR(paid_on,1,7) FROM payments") if r[0]} | {r[0] for r in q("SELECT SUBSTR(reversed_at,1,7) FROM payments WHERE reversed_at IS NOT NULL") if r[0]})
    months = [m for m in months if m <= (this_month or dt.date.today().isoformat()[:7])]
    before_p = q("SELECT COUNT(*), COALESCE(SUM(amount_mvr),0) FROM payments")[0]
    before = q("SELECT COUNT(*) FROM teacher_earnings")[0][0]
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    for m in months:
        res, locked = earnings.run_month(q, x, m, pct, None, now, apply=True)   # always inside the transaction; the dry run rolls it back
        log(f"{m}: " + ("approved, skipped" if locked else f"{len(res)} batch(es), collected {sum(r['collected'] for r in res)} MVR, teacher {sum(r['teacher_share'] for r in res)}, academy {sum(r['academy_share'] for r in res)} (at {pct}%)"))
    after = q("SELECT COUNT(*) FROM teacher_earnings")[0][0]
    if q("SELECT COUNT(*), COALESCE(SUM(amount_mvr),0) FROM payments")[0] != before_p:
        conn.rollback(); raise SystemExit("STOPPED, nothing changed: the payments moved, which must never happen.")
    log(f"teacher_earnings rows {before} -> {after}")
    if apply: conn.commit(); log("APPLIED.")
    else: conn.rollback(); log("DRY RUN: nothing was changed. Run again with --apply --i-have-a-backup to do it.")
    return before, after


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true"); ap.add_argument("--i-have-a-backup", action="store_true")
    a = ap.parse_args(argv)
    if a.apply and not a.i_have_a_backup: sys.exit("Refusing to run: take a backup of the database first, then add --i-have-a-backup.")
    from app import create_app
    app = create_app(); conn = dbx.connect(app.config, BASE)
    try: run(conn, a.apply)
    finally: conn.close()


if __name__ == "__main__":
    main()
