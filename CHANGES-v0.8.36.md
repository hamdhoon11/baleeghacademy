# v0.8.36: Round 2 (Fees and Admissions)

Builds on v0.8.35 (Round 1). Notifications are unchanged (students see only their own; you chose no change).

## New
- **One-tap slip check.** Fees → Slips to check → **Check slip** opens one dialog with the slip and the invoice facts side by side: amount transferred, amount due, paid so far, balance, transfer date, reference, and a label saying whether the amount **matches the balance**, is less, or is more. Duplicate-slip warnings show there too. **Verify** (amount editable) and **Reject** (asks the reason) are in the same dialog. The old View / Verify / Reject buttons are still on each row.
- **Remind next on WhatsApp.** Fees → Overdue shows "N not reminded today" and a **Remind next on WhatsApp** button. Each tap opens WhatsApp with the reminder ready for the most overdue person not reminded today (the student's number, or the guardian's when only that is there) and records it in the reminder log, so the list moves on. The per-invoice WhatsApp/Viber buttons are unchanged. (No second reminder system was added to the WhatsApp tool; the Overdue tab already had one.)
- **Fee statement PDF.** Students: Fees → **Download fee statement**. Admins with the Fees area: Student information → Fees → **Download fee statement**. One A4 PDF: totals (billed, paid, balance), every invoice with status, every payment; reversed payments are listed but not counted; voided invoices are not shown. Arabic and Dhivehi names print correctly. Routes: `GET /api/my/fees/statement.pdf` (student, own only), `GET /api/students/<id>/statement.pdf` (Fees area).
- **Duplicate-applicant warning.** Admissions → Review shows "This may be someone already known" when another application or an existing account has the same phone (any formatting), the same email, or the same name and date of birth, and says which and why. Nothing is blocked. `GET /api/applications/<id>` now returns `duplicates`.
- **Login by WhatsApp after approval.** The approval WhatsApp message now ends with the portal's sign-in link, after the login ID and temporary password.

## Checks run
- Unit tests: whole suite (442 tests) in one run, including `tests/test_session36.py` (statement contents and totals, voided left out, reversed marked, permissions; duplicate detection by phone, email account, name + date of birth; sign-in link in the approval message). `test_session32` security map and `test_phase4` fee-role test updated for the two new routes.
- Browser: all 11 `tests/e2e_*.py`. New `e2e_round2.py` (duplicate warning, Remind next opens WhatsApp and is logged); `e2e_browser.py` verifies a slip through the Check dialog and downloads the student statement; `e2e_student_info.py` checks the admin statement and that a limited admin without Fees has no button.
- Not tested: a real Vercel deployment, PostgreSQL, real phones.

## Next (Round 3, as agreed)
Tutorial grading (with a backup and a dry run before the data change), bulk actions, timetable view, "My files", recurring expenses.
