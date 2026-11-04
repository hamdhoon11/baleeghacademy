"""Private file storage for ID copies, payment slips, assignment files, class materials and tutorials.

  * Default: a folder on disk (instance/uploads), exactly as before.
  * S3_BUCKET set: any S3-compatible bucket (Supabase Storage, Cloudflare R2, Backblaze B2, AWS S3, MinIO).

Files are never public. Every download goes through the portal, which checks who is asking first.
Areas keep file kinds apart: "ids" (admission ID copies), "learning" (assignments, submissions, materials, tutorials), "slips" (payment slips).
"""
import io
import mimetypes
import os

from flask import abort, send_file, send_from_directory

AREAS = ("ids", "learning", "slips")


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
        kw = {"as_attachment": True, "download_name": download_name or name} if as_attachment else {}
        return send_from_directory(self._dir(area), _safe(name), **kw)

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
        try: data = self.read(area, name)
        except FileNotFoundError: abort(404)
        shown = download_name or name
        return send_file(io.BytesIO(data), mimetype=mimetypes.guess_type(shown)[0] or mimetypes.guess_type(name)[0] or "application/octet-stream",
                         as_attachment=as_attachment, download_name=shown)

    def describe(self):
        return f"bucket {self.bucket}"


def make(config, local_root):
    """Pick the storage from settings: an injected STORAGE (tests), S3 when S3_BUCKET is set, else a local folder."""
    if config.get("STORAGE") is not None:
        return config["STORAGE"]
    bucket = (config.get("S3_BUCKET") or "").strip()
    if not bucket:
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
