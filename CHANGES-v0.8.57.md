# v0.8.57: a stranger can no longer lock you out; attempt limits shared by every server

Asked: fix the admin lockout problem found in the v0.8.56 security review.

## The problem
- Eight wrong passwords locked the account for 5 minutes, for everyone. Anyone who knew the admin's login ID could keep the admin locked out.
- The counts were kept in each server's memory. On Vercel every instance had its own count, and a cold start reset it, so guessing was only slowed down.

## Sign-in now
| Who | Limit | What happens |
|---|---|---|
| One connection guessing one account | 8 wrong in 5 min | Only **that connection** is refused for that account. The owner, anywhere else, signs in as usual. |
| One connection trying many accounts | 30 wrong in 15 min | That connection is refused for every account |
| Many connections on one account | 50 wrong in 1 hour | Only connections that have **themselves** failed on it are refused. A clean one (the owner) still gets in. |

- A correct sign-in clears that connection's count.
- Your email and your login ID count as one account.

## Shared counts
- New table `rate_hits` (new `ratelimit.py`). It is created automatically on the next start, on SQLite and on hosted PostgreSQL.
- These limits also moved there:
  - applications: 5 per hour per connection;
  - "check my application": 30 per hour;
  - Forgot password;
  - payment slips (`SLIP_LIMIT` per student per hour).
- Counters older than a day are tidied away.
- Settings → Clear data clears them too ("Attempt counters").

## The visitor's real address
On Vercel the address now comes from `x-vercel-forwarded-for`. Vercel sets that header itself, and a visitor's own value is replaced. This also corrects the IP shown in the activity log and in Who's online. When not on Vercel, a sent `X-Forwarded-For` is ignored, because anyone can send one.

## Checks run
- Unit tests: **559, all pass**.
- New `tests/test_ratelimit.py` (6 tests):
  - the owner signs in while a stranger is blocked;
  - a successful sign-in clears the count;
  - spraying many accounts is stopped;
  - a many-connection attack is stopped while a clean connection still gets in;
  - two server instances share the counts;
  - the real address is read on Vercel, and a faked header is ignored elsewhere.
- `test_phase2` test_06 now clears the shared counts first.
- Browser: `tests/e2e_v0855.py`. The first run counted 35 of 36 passes, but its output named no failure. The next three runs printed ALL PASS. The password-change flow also passes.
