# v0.8.39: security fixes

Builds on v0.8.38. Six fixes from the code review of the live repository. No screen changes.

## Before you deploy (Vercel → Settings → Environment Variables)
1. **`SECRET_KEY` must be set** to your own long random text (at least 32 characters). If it is missing, shorter than 16 characters, or still an example value, **the portal now refuses to start** and the Vercel log says why. To make one: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. If you set a new key, everyone is signed out once.
2. Nothing else is required. `ADMIN_EMAIL` and `ADMIN_PASSWORD` are only needed when the database is empty (see fix 2).

## Database change (additive, automatic)
- `users.token_version` (number, 0 for everyone) and a new empty table `rate_hits`. Both are added when the new version starts, as earlier additions were. No existing row changes, and nobody is signed out by the update.

## Fixes
1. **Sign-in key.** The code is public, and the app used `dev-only-change-me` when `SECRET_KEY` was not set, so anyone could have made an admin sign-in token. A hosted portal (Vercel or PostgreSQL) now starts only with a real key. A local SQLite copy still starts without one.
2. **Example admin password.** On an empty hosted database the app created `admin@baleegh.test` with the password written in `seed.py`. Now a hosted portal creates the first admin only from `ADMIN_EMAIL` and `ADMIN_PASSWORD` (your own, at least 10 characters), and stops with a clear message otherwise. An admin that already exists is never touched. Demo teacher and student accounts are also off by default on Vercel without PostgreSQL (they were on).
3. **Dates after midnight.** A transfer or withdrawal without a date got the UTC date, which is yesterday from 00:00 to 05:00 Maldives time. It now gets the Maldives date. The age check on the application form uses the Maldives date too.
4. **Attempt limits** (sign-in, Forgot password, public application form) were kept in the server's memory, which every Vercel copy has separately and loses when it stops. They are now in the database (`ratelimit.py`, table `rate_hits`), so the limit is the same whichever copy answers. On Vercel the person's address is read from the header Vercel sets (`X-Real-IP`), also for the activity log; before, it could be the proxy's address. Elsewhere headers are ignored unless `TRUST_PROXY=1`.
5. **Sign-out and password changes end old sign-ins.** Before, a token kept working until it expired (8 hours) even after sign-out or a password change. Now sign-out, changing your password, an admin reset and an admin typing a new password all end every older sign-in of that account at once. After changing their own password the person stays signed in (the page gets a new token). **Changed on purpose:** signing out on one device signs the account out on all its devices.
6. **Repository.** `instance/portal.db` (an empty database) is no longer in the repository; `.gitignore` now covers `instance/`, `.env` and backups.

## Changed routes
- `POST /api/auth/change-password` now also returns `token` (use it from then on; the old one stops working).
- `POST /api/auth/logout` ends every sign-in of the account.

## Not done
- A Content-Security-Policy header and moving the token out of sessionStorage (needs a decision and changes in the page).
- Files are still stored in the database on Vercel.

## Checks run
- Unit tests: whole suite in one run, 467 tests, all pass. New `tests/test_session39.py` (11): weak keys refused on a hosted app and a token forged with the example key refused; hosted seed refuses a missing, example or short admin password and creates nothing; withdrawal at 02:00 Maldives time gets the Maldives date; sign-in limit shared by two copies of the app, per account and per address, and lifted after five minutes; header trusted only behind a proxy; Forgot and apply limits shared; sign-out, password change, reset and admin password end old sign-ins; tokens from before the update keep working; the page stores the new token; git ignores data and secrets.
- Three older tests updated for the new behaviour: `test_phase2` (rate-limit test uses its own address), `test_session35` (signs in again after a reset), `test_warm_connection` (sets a real key). The `test_session13` date test, which failed between 00:00 and 05:00, passes.
- Browser: `e2e_ui.py`, `e2e_browser.py`, `e2e_navigation.py`, `e2e_permissions.py` pass. The other nine scripts were not run.
- Not tested: a real Vercel deployment, PostgreSQL, real phones.
