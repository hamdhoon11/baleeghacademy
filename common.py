"""Small helpers shared by app.py and the feature modules (learning.py, fees.py)."""
import hashlib, os, re, unicodedata, uuid
from urllib.parse import quote

ON_VERCEL = bool(os.environ.get("VERCEL"))
# Vercel refuses request bodies over 4.5 MB before they reach the app, so on Vercel the portal says 4 MB itself instead of failing silently.
VERCEL_MAX_MB = 4

MAGIC = {".pdf": b"%PDF", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff", ".png": b"\x89PNG"}
MAX_FILE = (VERCEL_MAX_MB if ON_VERCEL else 5) * 1024 * 1024


def cap_mb(mb):
    """The upload limit in MB that really applies here (the configured one, but never above what Vercel can carry)."""
    return min(mb, VERCEL_MAX_MB) if ON_VERCEL else mb


def digits_intl(phone):
    """Digits only; Maldives 7-digit local numbers get the 960 prefix."""
    d = re.sub(r"\D", "", phone or "")
    return "960" + d if len(d) == 7 else d


def save_private(f, store, area, max_bytes=None):
    """Validate (type by extension, size, real content by magic bytes) and store privately in `store` under `area`.
    Returns (stored_name, sha256_hex, safe_original_name). Raises ValueError with a message fit to show the user."""
    if not f or not f.filename:
        raise ValueError("A file is required")
    ext = os.path.splitext(f.filename.lower())[1]
    if ext not in MAGIC:
        raise ValueError("Upload a PDF, JPG or PNG file")
    max_bytes = max_bytes or MAX_FILE
    data = f.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"File is too large ({max_bytes // (1024 * 1024)} MB max)")
    if not data.startswith(MAGIC[ext]):
        raise ValueError("File content does not match its type")
    name = uuid.uuid4().hex + (".jpg" if ext == ".jpeg" else ext)
    store.put(area, name, data)
    return name, hashlib.sha256(data).hexdigest(), shown_name(f.filename)


def shown_name(filename):
    """The name people see for an upload: letters of any script WITH their vowel marks (Dhivehi and Arabic need them), digits, . - _ and spaces.
    v0.8.34: marks (Unicode category M) are kept; before, Dhivehi names lost every vowel sign."""
    base = os.path.basename((filename or "").replace("\\", "/"))
    clean = "".join(ch if (ch.isalnum() or ch in "._- " or unicodedata.category(ch).startswith("M")) else "_" for ch in base)
    return clean.strip()[:80] or "file"


def ascii_name(name):
    """An English-letters-only copy of a file name, for the old filename="..." header (HTTP headers cannot carry other scripts)."""
    stem, ext = os.path.splitext(name or "file")
    ext = re.sub(r"[^A-Za-z0-9.]", "", ext)[:10]
    flat = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    flat = re.sub(r"[^A-Za-z0-9._\- ]", "_", flat).strip(" _")
    return (flat if re.search(r"[A-Za-z0-9]", flat) else "file")[:70] + ext


def file_headers(resp, shown_name, attachment=False):
    """Make a private file response safe and predictable: right Content-Type kept, name shown, never cached, never sniffed as HTML."""
    # v0.8.34: a name in Arabic or Dhivehi used to go straight into the header, which only takes Latin-1, so the server crashed and the
    # download failed. Now: an English-only fallback in filename="..." and the full name, percent-encoded, in filename*= (RFC 6266 / 5987).
    full = re.sub(r'[\x00-\x1f\x7f"\\/]', "_", os.path.basename(shown_name or "file"))[:120] or "file"
    resp.headers["Content-Disposition"] = (f'{"attachment" if attachment else "inline"}; filename="{ascii_name(full)}"'
                                           + (f"; filename*=UTF-8''{quote(full, safe='')}" if ascii_name(full) != full else ""))
    resp.headers["Cache-Control"] = "private, no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Access-Control-Expose-Headers"] = "Content-Disposition, Content-Type"
    return resp
