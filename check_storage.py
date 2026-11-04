"""Prove that the portal can really reach its database and file storage. Run it once after you set DATABASE_URL / S3_* (it changes nothing that lasts).

  python check_storage.py

It reports each step as OK or FAILED with the reason. Safe to run any time."""
import os, sys, uuid

ok = True


def step(label, fn):
    global ok
    try:
        detail = fn()
        print(f"  OK      {label}" + (f"  ({detail})" if detail else ""))
    except Exception as x:   # show the reason in plain words
        ok = False
        print(f"  FAILED  {label}: {type(x).__name__}: {x}")


def main():
    from app import create_app
    try:
        app = create_app()
    except Exception as x:
        sys.exit(f"  FAILED  start the portal and set up the tables: {type(x).__name__}: {x}")
    import dbx
    pg, store = app.config["USE_POSTGRES"], app.extensions["store"]
    print("Database:", "PostgreSQL" if pg else f"SQLite file {app.config['DATABASE_PATH']}", "| Files:", store.describe())
    if not pg and os.environ.get("VERCEL"): print("  WARNING: on Vercel a SQLite file is wiped regularly. Set DATABASE_URL.")
    if store.kind == "local" and os.environ.get("VERCEL"): print("  WARNING: on Vercel local files are wiped regularly. Set S3_BUCKET.")

    def database():
        c = dbx.connect(app.config, os.path.dirname(os.path.abspath(__file__)))
        try:
            new_id = c.execute("INSERT INTO audit_log(action,detail) VALUES('check_storage','test row, rolled back')").lastrowid
            assert new_id, "inserting a row did not return its id"
            r = c.execute("SELECT id, "at", (SELECT COUNT(*) FROM users) AS people FROM audit_log WHERE id=?", (new_id,)).fetchone()
            assert len(str(r["at"])) == 19, f"timestamp looks wrong: {r['at']!r}"
            assert c.execute("SELECT SUM(x) s FROM (SELECT 2 x UNION ALL SELECT 3 x) t").fetchone()["s"] == 5
            assert c.execute("SELECT 1 FROM users WHERE LOWER(email) LIKE ?", ("%nobody-here%",)).fetchone() is None
            return f"{r['people']} people in it, test row rolled back"
        finally:
            c.rollback(); c.close()

    def files():
        name = f"check-{uuid.uuid4().hex}.pdf"
        store.put("slips", name, b"%PDF-1.4 check")
        try:
            assert store.read("slips", name) == b"%PDF-1.4 check", "file read back differently"
        finally:
            store.delete("slips", name)
        try:
            store.read("slips", name); raise AssertionError("file was still there after delete")
        except FileNotFoundError:
            pass

    step("database: create tables, add a row, read it back", database)
    step("files: save, read back and delete a test file", files)
    print("\nAll good." if ok else "\nSomething needs fixing (see FAILED above).")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
