"""Copy an existing portal (SQLite file + uploads folder) into hosted PostgreSQL and a file bucket.

Use it once, when you move from the old setup to persistent storage. Nothing is deleted from the old copy.

  1. Set DATABASE_URL (and S3_BUCKET, S3_ENDPOINT_URL, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY if you use a bucket) in your shell.
  2. python migrate_to_hosted.py --dry-run                      (shows what would be copied)
  3. python migrate_to_hosted.py --db instance/portal.db --uploads instance/uploads

It refuses to run if the new database already has people in it, so it can never create duplicates.
"""
import argparse, os, sqlite3, sys

import dbx

BASE = os.path.dirname(os.path.abspath(__file__))


def table_order():
    import re
    return re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", dbx.read_schema(BASE))   # schema order already puts parents before children


def migrate(app, src_db, uploads, dry_run=False, log=print):
    """Copy rows and files into what `app` is configured to use. Returns {'tables': {name: rows}, 'files': n}."""
    store = app.extensions["store"]
    dst = dbx.connect(app.config, BASE)
    src = sqlite3.connect(f"file:{src_db}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    out = {"tables": {}, "files": 0}
    try:
        if dst.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            raise SystemExit("The new database already has people in it. Migration only runs into an empty database.")
        have = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in table_order():
            if t not in have: continue
            cols = [c for c in (r[1] for r in src.execute(f"PRAGMA table_info({t})")) if c in dst.columns(t)]
            data = [tuple(r[c] for c in cols) for r in src.execute(f"SELECT {','.join(cols)} FROM {t}")]
            out["tables"][t] = len(data)
            log(f"  {t}: {len(data)} row(s)")
            if dry_run or not data: continue
            if t == "counters": dst.execute("DELETE FROM counters")   # the schema pre-fills the receipt counter; use the real one
            for row in data:
                dst.execute(f"INSERT INTO {t}({','.join(cols)}) VALUES({','.join('?' * len(cols))})", row)
        if not dry_run:
            dst.commit()
            dst.reset_sequences()
        with app.app_context():   # the database file store (v0.8.34) writes through the app's connection
            for area, folder in (("ids", uploads), ("learning", os.path.join(uploads, "learning")), ("slips", os.path.join(uploads, "slips")), ("receipts", os.path.join(uploads, "receipts"))):
                if not os.path.isdir(folder): continue
                for name in sorted(os.listdir(folder)):
                    path = os.path.join(folder, name)
                    if not os.path.isfile(path): continue
                    out["files"] += 1
                    if not dry_run:
                        with open(path, "rb") as f: store.put(area, name, f.read())
            if not dry_run and store.kind == "db":
                from flask import g
                if "db" in g: g.db.commit()
        log(f"  files: {out['files']}")
    finally:
        src.close(); dst.close()
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.path.join(BASE, "instance", "portal.db"), help="old SQLite file")
    ap.add_argument("--uploads", default=os.path.join(BASE, "instance", "uploads"), help="old uploads folder")
    ap.add_argument("--dry-run", action="store_true", help="only count, copy nothing")
    a = ap.parse_args()
    if not os.path.exists(a.db): sys.exit(f"Cannot find the old database at {a.db}")
    if not os.environ.get("DATABASE_URL") and not a.dry_run: sys.exit("Set DATABASE_URL to the new PostgreSQL address first.")
    from app import create_app
    app = create_app()
    print("Copying" if not a.dry_run else "Dry run, nothing will be copied:", a.db, "->", "PostgreSQL" if app.config["USE_POSTGRES"] else app.config["DATABASE_PATH"],
          "| files ->", app.extensions["store"].describe())
    migrate(app, a.db, a.uploads, a.dry_run)
    print("Done." if not a.dry_run else "Dry run finished.")


if __name__ == "__main__":
    main()
