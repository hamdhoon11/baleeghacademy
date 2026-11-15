# v0.8.56: security review and fixes

Asked: do a security test on the portal and say whether it is ready.

## What was tested
- Whole unit suite, the Session 32 who-can-call-what matrix, and the v0.8.55 browser checks.
- New attack probes against a local copy:
  - forged sign-in tokens (default key, wrong key, `alg=none`, a student's token claiming "admin");
  - old sessions after a password change, a password reset and deactivation;
  - login guessing, the lockout, and a spoofed `X-Forwarded-For`;
  - a student editing their own account to admin;
  - a student calling every GET route with ids 1–24, looking for another student's or teacher's data;
  - password hashes in any admin response;
  - CORS from a stranger's site;
  - an HTML file renamed to .pdf;
  - stored XSS: hostile code in names, course, description, assignment, banner, tagline and "Forgot password", then every screen opened as admin (16 screens), teacher (7) and student (10), plus sign-in and Apply pages.

## Held up (no change needed)
Forged, wrong-key and `alg=none` tokens are refused. The role is read from the database, not from the token. A deactivated account is locked out at once. A student cannot make themselves admin and sees nobody else's data. No password hashes are returned. CORS only answers the listed site. Uploads are checked by their content. No XSS fired anywhere.

## Fixed
| Issue | Risk | Fix |
|---|---|---|
| If `SECRET_KEY` was not set, the server used a built-in key printed in the code, so anyone could make an admin token | Critical (only if the key is unset) | A hosted server (Vercel or hosted PostgreSQL) **refuses to start** without a `SECRET_KEY` of 32+ characters |
| A stolen session kept working after the person changed their password | Medium | A new password signs out every other device; this device gets a new token |
| Same after an admin set or reset someone's password | Medium | Setting or resetting a password ends that person's sessions |
| No limit on "check my application" (reference + phone) | Low | 30 lookups per hour per connection |
| No CSP / HSTS headers | Low | `Content-Security-Policy: object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'`, and HSTS over HTTPS |
| (not security) A withdrawal made between midnight and 05:00 got yesterday's date | Bug | It now uses the date in Maldives |

## Still open (owner to decide)
- **Lockout can be abused.** Eight wrong passwords lock an account for 5 minutes, so someone who knows the admin's ID can keep the admin locked out. Next step: count failures per account *and* connection, or add a CAPTCHA after a few failures.
- **The limits are kept in memory.** On Vercel each server instance has its own count, and the count is lost on a cold start. The limits slow guessing down but do not stop it. A shared store (a database table or Upstash Redis) would fix that.
- **Check on the live site:** that `request.remote_addr` is the visitor's real IP on Vercel. If it is Vercel's own address, everyone shares one counter.
- Sign-in tokens are kept in `sessionStorage`. That is fine while no XSS exists (none was found).

## Checks run
- Unit tests: **553, all pass**. New `tests/test_security_review.py` (4 tests). `test_session35` and `test_warm_connection` were updated for the new rules.
- Browser: `tests/e2e_v0855.py` **36/36 pass**. Changing the temporary password in the browser: the app opens, it survives a reload, and the other device's token gets 401.
