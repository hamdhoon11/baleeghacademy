# v0.8.44: change the start date of enrolments already in the portal

Builds on v0.8.43. No database change.

Reported: students already enrolled this month could not get invoices for the old months (Generate skips months before the enrolment date). Asked: make the enrolment date changeable so the back data can be added.

## New
- **Enrollments list** has a **Start date** column and tick boxes. Tick students and press **Set start date**: one date for all of them (for example 2026-04-01). Every month from that month to now is billed for each; months already billed are not doubled.
- **Edit an enrolment** (Enrollments → Edit): a Start date field with **Change start date**, for one student with a different date.
- Moving a start date **later** removes nothing: the message says how many invoices are now dated before the start, so you can void them in Fees if they should not be paid.
- Waitlisted, dropped and completed enrolments get the date but no new invoices.
- Every change is in the Activity log (`enrollment_start`, old and new date).
- New route `POST /api/enrollments/<id>/start-date` `{start_date}` (Enrollments area) → `{earlier_invoices, invoices_before_start, enrolled_at}`. The date must be real, not in the future and at most two years back.

## Adding the April data, start to finish
1. Enrollments: search or filter, tick everyone who started in April, Set start date → 2026-04-01. (Others: Edit, change one by one.)
2. Fees → Invoices: search a student, tick the months paid, Mark paid with the date and the WhatsApp slip.
3. Do both on the same day, so the daily run does not send "Fee overdue" for months already paid.

## Checks run
- Unit tests: whole suite, 496 tests, all pass. New `tests/test_session44.py` (4): April start on a November enrolment makes 7 invoices and stores 1 April Maldives time; repeating makes none; a later start removes nothing and reports 2; date checks, missing enrolment, students and teachers refused; waitlist not billed.
- Browser (390 px phone): `tests/e2e_mark_paid.py` now also ticks a student added today, sets the start date three months back (4 invoices), and checks the list and the edit panel show it. `e2e_navigation.py`, `e2e_ui.py` pass.
- Not tested: real PostgreSQL, real Vercel deployment, real phones.
