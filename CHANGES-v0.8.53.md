# v0.8.53: fee status grid by batch in Record payment

Asked: in Fees → Record payment, a batch-by-batch view with the fees collected too. Fee status by month: green when paid, red when not paid.

## Fees → Record payment → Fee status by batch
- One fold-out per batch. The heading says, for the latest month shown, how much was collected out of how much was due, and how many students still owe.
- Inside: a grid with **one row per student and one column per month**. Each cell is coloured **and** labelled:
  - **✓ green** paid (with the amount);
  - **! red** overdue;
  - **○ light red** not paid yet (not due yet);
  - **½ yellow** part paid (what is left);
  - **◷ blue** slip sent (waiting to be checked);
  - **– grey** waived;
  - **·** no fee that month.
- Under the students: **Collected** and **To pay** for each month.
- **Tap a red or yellow month** to fill the payment form below with that fee and its balance. Hold or hover on any cell to see the amount, what was paid and the day it was paid.
- Months: the last 6 on a computer and the last 3 on a phone (the "Show" choice offers 3, 6 or 12). Picking a Fee month shows just that month. The Batch and Student filters work on the grid too.
- On a phone the grid opens scrolled to the newest month, and slides sideways inside its box.
- Invoices with no batch (hand-made ones) are listed under "Other invoices", as before.

## Server
New `GET /api/fees/status-grid?end=YYYY-MM&months=1..12&batch_id=&q=` (Fees area).

## Checks run
- Unit tests: whole suite, 546, all pass. New `tests/test_session53.py` checks the statuses, the paid date, part payments, the month totals, the filters and that sign-in is needed.
- Browser: `tests/e2e_v0852.py`, extended for the grid, at 390 and 1280 px, all pass:
  - paid green and overdue red;
  - the totals row;
  - no sideways scrolling of the page;
  - tapping a month fills the form.
- e2e_mark_paid also passes.
