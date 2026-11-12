"""v0.8.39: attempt limits kept in the database, and the real address of the person.

Before, the limits for sign-in, "Forgot password" and the public application form were lists in the server's memory. On Vercel every
copy of the app has its own memory and loses it when it stops, so a limit was only as strong as one copy's lifetime. They now live in
the table `rate_hits`, which every copy shares.

client_ip(): behind Vercel (or another proxy you trust: TRUST_PROXY=1) the connection the app sees is the proxy's, so the person's
address is read from the header the proxy sets. Vercel overwrites X-Real-IP and X-Forwarded-For itself, so a visitor cannot fake them.
Without a trusted proxy the headers are ignored, because anyone could send them.
"""
import time

KEEP_SECONDS = 24 * 3600   # rows older than this are removed whenever a new one is written


def client_ip(request, trust_proxy):
    if trust_proxy:
        ip = (request.headers.get("X-Real-IP") or request.headers.get("X-Forwarded-For", "").split(",")[0]).strip()
        if ip: return ip[:60]
    return request.remote_addr or "?"


def count(conn, key, window, now=None):
    """How many attempts were recorded for this key in the last `window` seconds."""
    now = time.time() if now is None else now
    return conn.execute("SELECT COUNT(*) AS n FROM rate_hits WHERE key=? AND at>?", (key[:120], now - window)).fetchone()["n"]


def hit(conn, key, now=None):
    """Record one attempt. The caller commits (so it is saved together with the activity-log row)."""
    now = time.time() if now is None else now
    conn.execute("DELETE FROM rate_hits WHERE at<?", (now - KEEP_SECONDS,))
    conn.execute("INSERT INTO rate_hits(key,at) VALUES(?,?)", (key[:120], now))
