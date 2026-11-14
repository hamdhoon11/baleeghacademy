# v0.8.52: Record payment, batch by batch, with the fee month on every payment

Asked: in Fees → Record payment, make it easier to find students (batch by batch). Each payment should show which month's fee it paid; until now only the date it was recorded was shown.

## Fees → Record payment
- **Filters at the top:** Batch (or "No batch (other invoices)"), Fee month and Student name. They narrow the fees to collect, the invoice list in the form, and the payment list.
- **Fees to collect, batch by batch:** one fold-out per batch ("Arabic Level 1 A1 · 3 students · MVR 4,000 to pay"), then each student with a button per unpaid month ("Sep 2026 · MVR 500"). A month with a slip waiting says "Slip sent".
- **Tap a month** to fill the form below with that invoice and its full balance; then check the method and date and press Record payment.
- The invoice list in the form now starts with the month ("Sep 2026 · Mariyam Shifa · Quran Tuition Q1 · MVR 300"), and choosing one fills in its balance.
- **Recent payments:** each one shows **"For Sep 2026"** (the fee month it paid) with the course and batch, then "Paid on 2026-11-10", the receipt and invoice numbers. Up to 100 shown, filtered as above.

## Server
`GET /api/payments` also gives course_name, batch_code, batch_id, student_code, and takes `batch_id` (or `none`), `period` (fee month) and `q` (name).

## Checks run
- Unit tests: whole suite, 544, all pass (test_phase4 language check included).
- Browser: new `tests/e2e_v0852.py` at 390 and 1280 px (14 checks, all pass): grouped by batch, "For Sep 2026" and "Paid on", tapping a month fills invoice and amount, batch filter narrows both lists, no sideways scrolling. Also pass: e2e_mark_paid, e2e_v0849.
- The older browser scripts create people without a contact number, so `tests/e2e_shim.py` now switches the v0.8.49 phone rule off for the servers they start; `e2e_v0849.py` still checks the rule.
