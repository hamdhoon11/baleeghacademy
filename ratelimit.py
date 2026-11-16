"""v0.8.57: attempt counters kept in the database (table rate_hits), so every server instance shares them and a cold start does not reset them.

Sign-in rules (check_login / login_failed / login_ok):
- One connection guessing one account: 8 wrong passwords in 5 minutes blocks THAT connection for THAT account. Anyone else, the real owner
  included, can still sign in. Before v0.8.57 the 8 failures locked the account for everyone, so a stranger could keep the admin locked out.
- One connection trying many accounts: 30 wrong passwords in 15 minutes blocks that connection for every account.
- Many connections guessing one account: after 50 wrong passwords in an hour from anywhere, only connections that have themselves failed
  on that account in the last hour are refused. A connection with a clean record (the owner at home) still gets in.
- A correct sign-in clears that connection's count for that account.

Other limits (hit / over): applications, application status, Forgot password, payment-slip uploads.

client_ip(): on Vercel, the visitor's address comes from x-vercel-forwarded-for / x-forwarded-for, which Vercel sets itself and overwrites
when a visitor sends one; elsewhere the socket address is used and those headers are ignored (anyone could send them).
"""
import random, time

LOGIN_PAIR = (8, 300)        # per connection + account
LOGIN_IP = (30, 900)         # per connection, any account
LOGIN_ACCOUNT = (50, 3600)   # per account, from anywhere: then only connections with failures of their own are refused
KEEP_SECONDS = 86400


def now_s(app):
    fn = app.config.get("RATE_NOW")
    return int(fn() if fn else time.time())


def count(conn, bucket, key, since):
    return conn.execute("SELECT COUNT(*) n FROM rate_hits WHERE bucket=? AND k=? AND at>=?", (bucket, key, since)).fetchone()["n"]


def hit(conn, bucket, key, at):
    conn.execute("INSERT INTO rate_hits(bucket, k, at) VALUES(?,?,?)", (bucket, key[:200], at))
    if random.random() < 0.02:   # tidy now and then; old rows never count anyway
        conn.execute("DELETE FROM rate_hits WHERE at<?", (at - KEEP_SECONDS,))


def clear(conn, bucket, key):
    conn.execute("DELETE FROM rate_hits WHERE bucket=? AND k=?", (bucket, key[:200]))


def over(conn, bucket, key, limit, window, at):
    return count(conn, bucket, key[:200], at - window) >= limit


def client_ip_middleware(wsgi_app):
    """Vercel only: put the visitor's real address in REMOTE_ADDR, so the limits, the activity log and Who's online all see it."""
    def mw(environ, start_response):
        fwd = environ.get("HTTP_X_VERCEL_FORWARDED_FOR") or environ.get("HTTP_X_FORWARDED_FOR") or environ.get("HTTP_X_REAL_IP")
        if fwd:
            environ["REMOTE_ADDR"] = fwd.split(",")[0].strip()[:64]
        return wsgi_app(environ, start_response)
    return mw


# ---- sign-in ----
def _keys(ip, account):
    return ip + "|" + account, ip, account


def check_login(conn, ip, account, at):
    """True when this connection may not try this account now."""
    pair, ipk, acct = _keys(ip, account)
    if over(conn, "login_pair", pair, *LOGIN_PAIR, at): return True
    if over(conn, "login_ip", ipk, *LOGIN_IP, at): return True
    if account and over(conn, "login_acct", acct, *LOGIN_ACCOUNT, at):
        return count(conn, "login_pair", pair, at - LOGIN_ACCOUNT[1]) > 0   # under attack: only connections with failures of their own wait
    return False


def login_failed(conn, ip, account, at):
    pair, ipk, acct = _keys(ip, account)
    hit(conn, "login_pair", pair, at); hit(conn, "login_ip", ipk, at)
    if account: hit(conn, "login_acct", acct, at)


def login_ok(conn, ip, account):
    clear(conn, "login_pair", _keys(ip, account)[0])
