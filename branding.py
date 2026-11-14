"""v0.8.48: the academy's logo (Settings -> Academy logo). Shown on the sign-in page, in the menu, on the application form, as the
browser tab icon, and at the top of receipts, invoices, statements and every report PDF.

  POST   /api/settings/logo     admin, Settings   multipart "file": PNG or JPG, up to 1 MB (checked by its real content, not its name)
  DELETE /api/settings/logo     admin, Settings   back to the built-in mark
  GET    /api/public/logo       anyone            the image (public on purpose: the sign-in page shows it before anyone signs in)
  /api/public/info              gives logo_url ("/api/public/logo?v=<version>") or null

The file lives in the portal's file storage, area "branding"; the settings table keeps only {name, type, v} under the hidden key _logo
(not in SETTING_KEYS, so the Settings form never shows or overwrites it). Clearing the portal's data keeps the logo, like the settings.
"""
import hashlib
import json
import uuid

from flask import Response, jsonify, request

KEY = "_logo"
MAX_BYTES = 1024 * 1024
KINDS = {b"\x89PNG\r\n\x1a\n": ("png", "image/png"), b"\xff\xd8\xff": ("jpg", "image/jpeg")}


def kind_of(data):
    for magic, k in KINDS.items():
        if data.startswith(magic): return k
    return None


def register(app, c):
    def meta():
        try: return json.loads(c.raw_setting(KEY) or "null")
        except ValueError: return None

    def logo_bytes():
        """The logo's bytes, or None. Used by the PDF builders; never raises."""
        m = meta()
        if not m: return None
        try: return c.store.read("branding", m["name"])
        except Exception: return None

    def logo_url():
        m = meta()
        return f"/api/public/logo?v={m['v']}" if m else None

    def save(m):
        c.db().execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (KEY, json.dumps(m) if m else ""))

    app.extensions["branding"] = {"logo_bytes": logo_bytes, "logo_url": logo_url}

    @app.post("/api/settings/logo")
    @c.auth("admin", perm="settings")
    def logo_put():
        f = request.files.get("file")
        if not f or not f.filename: return c.err("Choose a PNG or JPG picture")
        data = f.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES: return c.err("The logo can be up to 1 MB. Make the picture smaller and try again.", 413)
        k = kind_of(data)
        if not k: return c.err("The logo must be a PNG or JPG picture")
        try:   # the PDFs must be able to draw it: a damaged picture is refused now, not when a receipt is printed
            from reportlab.lib.utils import ImageReader
            import io
            w, h = ImageReader(io.BytesIO(data)).getSize()
            if not w or not h: raise ValueError
        except Exception:
            return c.err("This picture could not be read. Save it again as PNG or JPG.")
        old = meta()
        name = f"logo-{uuid.uuid4().hex[:12]}.{k[0]}"
        c.store.put("branding", name, data, k[1])
        m = {"name": name, "type": k[1], "v": hashlib.sha256(data).hexdigest()[:10], "w": w, "h": h}
        save(m)
        c.audit("logo_change", "settings", None, f"logo uploaded ({len(data) // 1024} KB, {w}x{h})")
        c.db().commit()
        if old and old.get("name") != name:
            try: c.store.delete("branding", old["name"]); c.db().commit()
            except Exception: pass
        return jsonify(ok=True, logo_url=logo_url(), width=w, height=h)

    @app.delete("/api/settings/logo")
    @c.auth("admin", perm="settings")
    def logo_delete():
        old = meta()
        if not old: return jsonify(ok=True, logo_url=None)
        save(None)
        try: c.store.delete("branding", old["name"])
        except Exception: pass
        c.audit("logo_change", "settings", None, "logo removed")
        c.db().commit()
        return jsonify(ok=True, logo_url=None)

    @app.get("/api/public/logo")
    def logo_get():
        m = meta()
        data = logo_bytes() if m else None
        if not data: return c.err("No logo", 404)
        r = Response(data, mimetype=m["type"])
        # the URL carries the version, so a new logo is a new URL: safe to keep for a day
        r.headers["Cache-Control"] = "public, max-age=86400" if request.args.get("v") == m["v"] else "no-cache"
        r.headers["X-Content-Type-Options"] = "nosniff"
        return r
