# v0.8.61: Admins can remove people who already have records

Asked: "I can't delete people in the portal now, but an admin should be able to remove people."

**Why it failed:** Delete in People only worked for an account with no records at all. As soon as a student had an enrolment (and so an invoice), the portal said "Disable the account instead". That was on purpose, but it meant almost nobody real could be removed.

**Chosen (asked):** remove the person and their class records, and **keep the money records** under their name, so finance totals never change.

No database change.

## People → open a person → Delete
1. A preview first. Nothing is changed yet. It lists:
   - what is **deleted with them**, with counts;
   - what is **kept**: invoices and payments, unpaid invoices with the amount still owed, batches they teach, tutorials they made, applications.
2. **Continue** asks for **your own password**. A wrong password removes nothing and is written to the activity log.
3. Someone with no records at all is deleted as before, with one confirm and no password.

**Deleted with them:** the account and profile, enrolments, attendance marks, submitted work and grades, tutorial answers, transfer and withdrawal history, family membership, notifications, WhatsApp log entries, password requests, sign-in history, Teachers' room messages, classes they were booked to cover as a substitute, recurring discounts on their enrolments, and their uploaded answer files.

**Kept:**
- **Invoices, payments, payment slips and one-off discounts.** The invoices keep the person's name and phone and show as "Not in portal", like a walk-in customer. Fees, receipts, reports and finance show the same totals as before.
- **Unpaid invoices stay owed.** Void them in Fees if they will not be paid.
- Applications stay in Admissions.
- Batches they taught are kept, with no teacher.
- Their tutorials move to the admin who removes them, because a tutorial must have an owner.
- Assignments, materials, recordings, grades they gave and payments they recorded stay. Only the "by whom" is emptied; the activity log still shows who did it.

**Not allowed:**
- A **teacher with pay records** (earnings, payments to the teacher, salary expenses). Payroll needs the teacher, so the portal says to disable the account instead.
- Removing yourself, the only full admin, or the superadmin (unchanged).
- A limited admin removing an admin (unchanged). Admins without the People area cannot remove anyone.

**Activity log:** `delete_user` now says who was removed, what was deleted with counts, and how many invoices and payments were kept. `delete_user_refused` is written when the password is wrong.

## Routes
- `GET /api/users/<id>/removal` (new): the preview `{deleted, kept, blocked, blocked_message, has_records, refused, name, role, login_id}`. Changes nothing.
- `DELETE /api/users/<id>`: now removes people with records. Body `{"password"}` is required when `has_records`. Without it the reply is 400 with `code: "password_needed"`; with a wrong password, 403; for a teacher with pay records, 409.

## How it works (for the next session)
- `removeperson.py` (new): `PLAN` gives every `(table, column)` that points at `users` one decision: delete, detach (keep, link emptied), null ("by whom" emptied), owner (moved to the acting admin) or block. `plan(conn, uid)` is the preview, `remove(conn, uid, actor_id)` runs inside the request's transaction, `file_refs` and `remove_files` handle the files.
- **A new table or column that points at `users` must be added to `PLAN`.** `tests/test_v0861.py::test_01` fails until it is.
- `app.py`: `removal_problem()` holds the old rules (self, only full admin, superadmin, limited admin). It is shared by the preview and the delete.

## Checks run
- Unit tests: whole suite, **592, all pass**.
- New `tests/test_v0861.py` (6 tests):
  - every reference to `users` has a decision;
  - a student with an enrolment and an invoice: no password or a wrong password removes nothing; the right password removes them; invoice count and total unchanged; the invoice is kept under their name and found in Fees; the log has the counts;
  - no records means no password is needed;
  - a teacher's batch is kept without a teacher;
  - a teacher with pay records is refused;
  - a limited admin is refused, and you cannot remove yourself.
- Updated `test_admin_controls` test 02: a person with records now needs the password (400) instead of being refused (409).
- Browser: new `tests/e2e_v0861.py`, at 390 px and 1280 px, **12 checks, all pass**: preview, wrong password, removal, invoice totals, invoice under the name, gone from People.
- Not tested: a real PostgreSQL database, the live Vercel site, files in a bucket.
