# v0.8.43: mark invoices paid with the slip people send on WhatsApp; bill students who started earlier

Builds on v0.8.42. No database change (the existing `payment_slips` and `payments` tables are used).

Asked: can an admin mark a due invoice as paid and attach the payment slip, since people pay and send the slip on WhatsApp? Courses started in April, so students will be added now with all their payments up to now.

## What was there before
- Fees → Record payment could already record a payment on an open invoice (amount, method, date, reference, note) and the invoice became Paid. **No slip could be attached**, and the invoice had to be found in one long list.
- A student added today was billed from this month only. Earlier months could be made only by importing enrolments with a date and then pressing Generate once per month.

## New
- **Mark paid** button on every open invoice (Fees → Invoices) and on every row of Fees → Overdue. One dialog: amount (the balance is filled in; less is a part payment), method (bank transfer, cash, other), date paid (any earlier date, not the future), reference, note, **payment slip (optional: PDF, JPG or PNG, such as a WhatsApp screenshot)**, and "Tell the student" (a portal notice; on by default for one invoice, off for several).
- **Several months at once.** Tick invoices in Fees → Invoices and press **Mark paid** in the bar: each is paid in full with the same date, reference and slip (one transfer that covered several months). The slip is stored once and shown on each payment. Each payment still gets its own receipt number.
- **Record payment** tab: the same slip field and "Tell the student" box.
- Payments list: **Open slip** on every payment that has one. The student can open it from their side too.
- Slips attached by the office are saved as already verified, so they never appear in Slips to check. Reversing such a payment marks the slip reversed, as for slips the student sent.
- If the student had also sent a slip for the same invoice, the result says so; reject it in Slips to check if it is the same payment.
- **Start date when enrolling** (Enrollments → Add enrollment, optional). A student who started in April is billed every month from April to now; the message says how many earlier invoices were made. Leave it empty for students starting now (as before).
- **Generate with a From month** (Fees → Invoices). From 2026-04 to 2026-11 makes every missing invoice of those months for enrolments that had started by then; safe to repeat. For students brought in by the enrolment import with an `enrolled_at` date.
- New route `POST /api/payments/mark-paid` (Fees area): `invoice_ids` (one or up to 24, comma-separated), `amount_mvr` (one invoice only; default the balance), `method`, `paid_on`, `reference`, `note`, `notify`, `file`. Multipart or JSON. All or nothing: if one invoice is refused, nothing is saved and the uploaded file is removed. `POST /api/enrollments` takes `start_date` and returns `earlier_invoices`. `POST /api/invoices/generate` takes `from_month`. `GET /api/payments` returns `slip_file_name`.

## Adding the April students: suggested order
1. Enrollments → Add enrollment: pick the student and batch, set Start date to the day they began (for example 2026-04-01). April to November invoices are made.
2. Fees → Invoices, search the student's name: tick the months they paid together, Mark paid, set the date, attach the slip. Or Mark paid one by one.
3. Months they have not paid stay open and show in Overdue.

Note: earlier months are due on the usual due day of that month, so they count as overdue until marked paid. The daily reminder run will send "Fee overdue" notices for months still open, so mark the paid ones on the same day you add the student.

## Checks run
- Unit tests: whole suite, 492 tests, all pass. New `tests/test_session43.py` (12): start date April bills April to November; start date checks (future, over two years, format); no start date bills this month only; one invoice with a PNG slip (verified, not in the queue, admin and student can open it, receipt works, payments list has the file name); three months with one slip (three receipts, file stored once); part payment then the rest by JSON; six refusals each save nothing; warning when the student's own slip is waiting; notice only when asked; reverse marks the slip reversed; students and teachers refused; Generate from April to November and repeat makes nothing.
- Browser (390 px phone): new `tests/e2e_mark_paid.py` (11 checks: enrol with a start date three months back, Mark paid with a slip, tick three and mark paid with one slip, Open slip on every payment, Generate with From, no sideways scrolling). `e2e_browser.py`, `e2e_round2.py`, `e2e_ui.py` pass.
- **Not tested: a real PostgreSQL database, a real Vercel deployment, real phones.**
