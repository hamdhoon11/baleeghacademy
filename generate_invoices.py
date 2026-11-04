"""Create this month's invoices for every active enrollment. Safe to run as often as you like: an enrollment never gets two invoices
for the same month, so a daily or monthly scheduler only ever adds what is missing.

  python generate_invoices.py                 # current month (Maldives time)
  python generate_invoices.py --month 2026-04 # a specific month (up to next month)

Example cron (on the server that runs the portal; use your own paths), 06:00 Maldives time on the 1st of each month:
  0 1 1 * *  cd /path/to/baleegh-portal && . .venv/bin/activate && python generate_invoices.py >> instance/invoices.log 2>&1
(01:00 UTC = 06:00 Maldives time.) Use `0 1 * * *` to run daily instead; it will only add invoices for students who joined since the last run.
Needs the same environment variables as the web app (DATABASE_PATH, SECRET_KEY), so load your .env first."""
import argparse, sys
from app import create_app

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--month", help="YYYY-MM (default: the current month in Maldives time)")
a = ap.parse_args()
app = create_app()
with app.app_context():
    fx = app.extensions["fees"]
    period = fx["parse_period"](a.month) if a.month else fx["month_of"](fx["today"]())
    if not period:
        sys.exit("--month must look like 2026-04 and be no later than next month")
    from flask import g
    r = fx["generate"](period, None)
    # generate() writes through the app-context connection; log it and commit before the context closes
    g.db.execute("INSERT INTO audit_log(user_id,action,entity,detail) VALUES(NULL,'generate_invoices','invoice',?)",
                  (f"{period}: created {r['created']}, skipped {r['skipped_total']} (scheduled run)",))
    g.db.commit()
print(f"{r['period']}: created {r['created']} invoice(s), skipped {r['skipped_total']} {r['skipped'] or ''}")
