# v0.8.47: Who's online, and sign out / pause / suspend accounts (full admins only)

Builds on v0.8.46. **Database change: additive only** (new columns on `users`, added automatically on start; no row is changed, no migration script to run).

Asked: the admin should see who is online and offline right now, and be able to suspend, kick out or pause accounts. Only for the superadmin.

"Superadmin" = a **full admin** (an admin with no permission limit), the same rule the People screen already uses for changing permissions.

## New: People and admissions → Who's online
- Cards: Online now, Away, Offline, Paused, Suspended (tap one to filter), plus "Students online 3 / 40 · Teachers … · Admins …".
- List of everyone, online people first: name and login ID, role, status (Online / Away / Offline, with "5 min ago"), device ("Phone · Chrome") and IP, last sign-in, account state (Active / Paused until … / Suspended / Disabled, with the reason).
- Filters: role, status, search by name, login ID or IP. Refreshes by itself every 30 seconds (not while you type or a dialog is open), and has a Refresh button.
- **Online** = used the portal in the last 2 minutes; **Away** = in the last 15 minutes; otherwise **Offline**. Pressing Sign out shows the person offline at once.

## Actions (on every person except yourself)
- **Sign out**: ends their sessions on every device now. They can sign in again straight away.
- **Pause**: 1 hour, 1 day, 3 days, 1 week, 30 days, or until a date and time (Maldives time); optional reason. Signed out at once; at sign-in they see "Your account is paused until 20 Nov 2026, 18:00 (Maldives time)". Lifts by itself. At most one year.
- **Suspend**: reason required (staff only, never shown to the person). Signed out at once; at sign-in they see "Your account has been suspended. Please contact the academy." Stays until restored.
- **Restore**: lifts a pause or a suspension.
- The paused/suspended message is shown **only after the right password**, so a stranger guessing IDs learns nothing.
- Every action is in the Activity log: `account_signout`, `account_pause`, `account_suspend`, `account_restore` (with the reason), and `login_blocked` when a paused/suspended person tries to sign in.
- Limited admins, teachers and students: no tab, and every call is refused (403). Works on other full admins too (the one acting always stays a working full admin).
- "Disabled" accounts (People → Account active unticked) are shown but left to People.

## How it works (for the next session)
- `presence.py` (new): routes, `blocked()`, `touch()`, `signed_in()`, `device()`.
- Columns on `users` (`dbx.V0847_USER_COLUMNS`, also in schema.sql): last_seen_at, last_login_at, signed_out_at, last_ip, last_agent, token_version, suspended_at, suspend_reason, paused_until, pause_reason, account_changed_by.
- Tokens now carry `tv` (token_version). Sign out / pause / suspend raise it, so open sessions get 401 on their next request. Old tokens without `tv` count as 0 and keep working.
- `auth()` writes last_seen at most every 30 seconds per person. An open portal stays "online" through the existing 60-second notification check.
- Tab rule: `settings_schema.FULL_ONLY` (a tab only a full admin ever gets).
- Routes: `GET /api/admin/presence`, `POST /api/admin/accounts/<id>/signout|pause|suspend|restore` (in the test_session32 map as NO_AREA).

## Checks run
- New `tests/test_session47.py` (10): online/away/offline and logout; at most one write per 30 s; sign out on two devices; pause by hours lifts by itself, message only after the right password; pause until a date, bad input; suspend (reason required, not shown to the person, never lifts), restore; only full admins (limited admin, teacher, student, no token); not on yourself, works on another admin; old tokens; upgrade of a v0.8.8 database.
- Unit tests: whole suite, 518 tests. All pass except `test_session13 test_02`, which fails only between midnight and 05:00 Maldives time (an older issue: the withdrawal date defaults to the UTC date). Not caused by this change.
- Browser: new `tests/e2e_presence.py` at 1280 px and 390 px (49 checks, all pass): student shows online on a phone, sign out, pause with reason, the student's message, restore, suspend, filter, limited admin has no tab.
- Not tested: the hosted PostgreSQL database and Vercel, real phones.
