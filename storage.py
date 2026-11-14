"""Private file storage for ID copies, payment slips, assignment files, class materials and tutorials.

  * Default: a folder on disk (instance/uploads), exactly as before.
  * S3_BUCKET set: any S3-compatible bucket (Supabase Storage, Cloudflare R2, Backblaze B2, AWS S3, MinIO).
  * On Vercel without a bucket (v0.8.34): inside the database (table stored_files). Vercel's disk is temporary and differs between its copies of
    the app, so files kept there "could not be found" minutes after upload. FILE_STORAGE=db|s3|local forces a choice.

Files are never public. Every download goes through the portal, which checks who is asking first.
Areas keep file kinds apart: "ids" (admission ID copies), "learning" (assignments, submissions, materials, tutorials), "slips" (payment slips), "receipts" (expense receipts, Session 23).
"""
import datetime as dt
import io
import mimetypes
import os

from flask import send_file, send_from_directory

AREAS = ("ids", "learning", "slips", "receipts", "branding")   # v0.8.48: branding = the academy logo (the only file anyone may see without signing in)


def _safe(name):
    return os.path.basename(name or "")


class LocalStorage:
    kind = "local"

    def __init__(self, root):
        self.root = root
        for a in AREAS: os.makedirs(self._dir(a), exist_ok=True)

    def _dir(self, area):
        # ID copies have always lived directly in the uploads folder; keep that so existing installs keep working
        return self.root if area == "ids" else os.path.join(self.root, area)

    def put(self, area, name, data, content_type=None):
        os.makedirs(self._dir(area), exist_ok=True)
        with open(os.path.join(self._dir(area), _safe(name)), "wb") as f: f.write(data)

    def read(self, area, name):
        with open(os.path.join(self._dir(area), _safe(name)), "rb") as f: return f.read()

    def delete(self, area, name):
        try: os.remove(os.path.join(self._dir(area), _safe(name)))
        except FileNotFoundError: pass

    def send(self, area, name, download_name=None, as_attachment=False):
        if not os.path.isfile(os.path.join(self._dir(area), _safe(name))): raise FileNotFoundError(name)
        kw = {"as_attachment": True, "download_name": download_name or name} if as_attachment else {}
        return send_from_directory(self._dir(area), _safe(name), **kw)

    def exists(self, area, name):
        return bool(name) and os.path.isfile(os.path.join(self._dir(area), _safe(name)))

    def describe(self):
        return f"local folder {self.root}"


def _missing(exc):
    code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
    return code in ("NoSuchKey", "404", "NotFound")


class S3Storage:
    kind = "s3"

    def __init__(self, client, bucket, prefix=""):
        self.c, self.bucket = client, bucket
        self.prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""

    def _key(self, area, name):
        return f"{self.prefix}{area}/{_safe(name)}"

    def put(self, area, name, data, content_type=None):
        self.c.put_object(Bucket=self.bucket, Key=self._key(area, name), Body=data,
                          ContentType=content_type or mimetypes.guess_type(name)[0] or "application/octet-stream")

    def read(self, area, name):
        try:
            return self.c.get_object(Bucket=self.bucket, Key=self._key(area, name))["Body"].read()
        except Exception as x:
            if _missing(x): raise FileNotFoundError(name)
            raise

    def delete(self, area, name):
        try: self.c.delete_object(Bucket=self.bucket, Key=self._key(area, name))
        except Exception as x:
            if not _missing(x): raise

    def send(self, area, name, download_name=None, as_attachment=False):
        data = self.read(area, name)   # FileNotFoundError when the file is gone; the app answers with a JSON 404
        shown = download_name or name
        return send_file(io.BytesIO(data), mimetype=mimetypes.guess_type(shown)[0] or mimetypes.guess_type(name)[0] or "application/octet-stream",
                         as_attachment=as_attachment, download_name=shown)

    def exists(self, area, name):
        if not name: return False
        try:
            self.c.head_object(Bucket=self.bucket, Key=self._key(area, name)); return True
        except Exception as x:
            if _missing(x) or "404" in str(x): return False
            raise

    def describe(self):
        return f"bucket {self.bucket}"


class DbStorage:
    """Files as rows of stored_files (BLOB in SQLite, BYTEA in PostgreSQL). Uses the request's own connection, so a file and the row that points
    to it are saved by the same commit (and both disappear if the request fails). Sized for the portal's files (4 MB each on Vercel)."""
    kind = "db"

    def __init__(self, conn):
        self.conn = conn   # a function returning this request's dbx connection

    def put(self, area, name, data, content_type=None):
        c, n = self.conn(), _safe(name)
        c.execute("DELETE FROM stored_files WHERE area=? AND name=?", (area, n))
        c.execute("INSERT INTO stored_files(area,name,content_type,size,data,created_at) VALUES(?,?,?,?,?,?)",
                  (area, n, content_type or mimetypes.guess_type(n)[0] or "application/octet-stream", len(data), bytes(data),
                   dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")))

    def read(self, area, name):
        r = self.conn().execute("SELECT data FROM stored_files WHERE area=? AND name=?", (area, _safe(name))).fetchone()
        if not r: raise FileNotFoundError(name)
        return bytes(r["data"])   # PostgreSQL gives a memoryview/bytes, SQLite bytes

    def delete(self, area, name):
        self.conn().execute("DELETE FROM stored_files WHERE area=? AND name=?", (area, _safe(name)))

    def exists(self, area, name):
        return bool(name) and self.conn().execute("SELECT 1 FROM stored_files WHERE area=? AND name=?", (area, _safe(name))).fetchone() is not None

    def send(self, area, name, download_name=None, as_attachment=False):
        data = self.read(area, name)
        shown = download_name or name
        return send_file(io.BytesIO(data), mimetype=mimetypes.guess_type(shown)[0] or mimetypes.guess_type(name)[0] or "application/octet-stream",
                         as_attachment=as_attachment, download_name=shown)

    def describe(self):
        return "inside the database (table stored_files)"


def make(config, local_root, conn=None):
    """Pick the storage: an injected STORAGE (tests); FILE_STORAGE if set (db, s3 or local); else S3 when S3_BUCKET is set;
    else the database on Vercel (its disk does not keep files); else a local folder. conn: function giving the request's database connection."""
    if config.get("STORAGE") is not None:
        return config["STORAGE"]
    bucket = (config.get("S3_BUCKET") or "").strip()
    want = (config.get("FILE_STORAGE") or "").strip().lower() or ("s3" if bucket else "db" if config.get("ON_VERCEL") else "local")
    if want == "db":
        if conn is None: raise RuntimeError("FILE_STORAGE=db needs the database connection")
        return DbStorage(conn)
    if want == "local" or not bucket:
        if want == "s3": raise RuntimeError("FILE_STORAGE=s3 but S3_BUCKET is empty")
        return LocalStorage(local_root)
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        raise RuntimeError("S3_BUCKET is set but the 'boto3' package is not installed. Run: pip install boto3")
    client = boto3.client(
        "s3",
        endpoint_url=(config.get("S3_ENDPOINT_URL") or None),
        region_name=(config.get("S3_REGION") or None),
        aws_access_key_id=config.get("S3_ACCESS_KEY_ID") or None,
        aws_secret_access_key=config.get("S3_SECRET_ACCESS_KEY") or None,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}, retries={"max_attempts": 3}, connect_timeout=10, read_timeout=30),
    )
    return S3Storage(client, bucket, config.get("S3_PREFIX") or "")
