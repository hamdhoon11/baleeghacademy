# v0.8.46: hand-made invoices and revenue types in every fees report; dropped students and their fees checked

Builds on v0.8.45. No database change.

Asked: the new invoices should show in the Fees section, the Finance section and the reports; and students should still see the fees they owe after being dropped from a course.

## Checked first
- **Dropped students:** already working, nothing to correct. After a drop the student can still sign in. Home shows "Fees to pay", the Fees page lists every invoice (overdue ones marked), they can upload a slip and download their fee statement. The admin still sees the invoices in Overdue, and reminders continue. Checked in the browser and by a new test, so it cannot break unnoticed later.
- **Already showing manual invoices (v0.8.45):** Fees → Invoices, Overdue, Record payment and slips; Finance → Revenue (by revenue type) and the Financial dashboard (revenue and outstanding); the Dashboard's fee figures; the student's own Fees page and statement.

## Fixed (they were missing)
- **Fees → Monthly report:** new **By revenue type** panel (invoiced and collected per type). "Who owes" shows people not in the portal (tagged) and the description when there is no course. The CSV/Excel has `revenue_type` and `description` columns.
- **Fees → Payment report:** this report is built from enrolments and monthly fees, so hand-made invoices never appeared in it. It now has an **Other invoices this month** section: student or customer, revenue type, description, due, status, paid, balance and payment dates, with its own totals. The month, course, batch and status filters apply. The CSV/Excel adds these as extra rows: the Type column holds the revenue type, and people not in the portal are marked "(not in the portal)".
- **Payment report → History (one student):** manual invoices show their description and revenue type instead of an empty course.
- **Student information → Fees:** new Description column, so a registration fee or book sale is told apart from a monthly fee.

## Checks run
- Unit tests: whole suite, 508 tests, all pass. New `tests/test_session46.py` (2): the monthly report by type, "who owes" and its CSV; the payment report's other invoices with totals, status filter, batch filter, an empty month, CSV and Excel; student history; student information; Finance revenue by type, outstanding and the dashboard; a dropped student still has the Fees tab, sees three open months, uploads a slip, downloads the statement, and still appears in Overdue.
- Browser (390 px phone): `tests/e2e_manual_invoice.py` now also opens the Monthly report and the Payment report for April; `e2e_mark_paid.py`, `e2e_browser.py`, `e2e_student_info.py` pass. A dropped student's Home and Fees pages were checked in the browser.
- Not tested: the real hosted database and Vercel deployment, real phones.
