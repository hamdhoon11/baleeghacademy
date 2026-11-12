# v0.8.35: Round 1 (fixes and "make it easier")

Builds on v0.8.34 (download fixes). Decisions from you: voided invoices are not revenue and are found with a filter; teacher pay is 50% of monthly fees collected, without registration fees (already so; now also tested).

## Fixes
- **PDF receipts and invoices print Arabic and Dhivehi names** instead of "????". A trimmed GNU FreeSerif font (`fonts/`, licence in `fonts/LICENSE.txt`) plus `rtltext.py`, which joins Arabic letters, makes the lam-alef ligature, orders right to left and keeps each Thaana vowel sign on its letter. English-only receipts are byte-for-byte unchanged. Please have a Dhivehi reader check one real receipt.
- **Voided invoices are never revenue**: Finance revenue, the financial dashboard, the admin dashboard and the monthly collection figure leave out payments on voided invoices. Voiding already requires reversing payments first, so this guards older data.
- **Voided invoices are out of the normal invoice list.** Fees → Invoices → Status: "Void" (only voided), "All, including voided", or type the invoice number. The reason for voiding is shown.
- **Student Assignments badge** showed at most 5 even with more open work; it now shows the real number.
- **"Fee is 0" warning** no longer appears on an empty "Add course" form; it shows once the fee was touched, or for a saved course with fee 0.
- Teacher Home: times in "recent activity" are Maldives time.

## New
- **Forgot password?** on the sign-in page. The person types their login ID or email (and optionally a WhatsApp number). Admins with the People area get a notification; People shows a "Password help" list with **Reset and send**, which makes a temporary password and opens WhatsApp with the message ready (their phone, or the guardian's). The answer never reveals whether an account exists; at most 5 requests per hour per network address, one open request per person. Routes: `POST /api/auth/forgot` (public), `GET /api/password-help`, `POST /api/password-help/<id>/dismiss` (People area). The reset response now includes `whatsapp_link`.
- **Admin Dashboard "To do today"**: applications waiting, payment slips to check, overdue invoices, password requests, waiting lists, today's classes that started without attendance (each with Take attendance), and a storage warning. One tap opens the right tab and sub-tab. Only areas the admin has. Route `GET /api/admin/todo`.
- **Teacher Home "Today"**: each class today with **Take attendance** (or "Attendance taken" + Edit), and the grading queue with one tap to it.
- **Student Home "What to do next"**: work to hand in (late ones marked), new grades from the last 14 days, new materials from the last 7 days, each with one tap.
- People tab badge: number of password requests waiting.

## Database
Two new tables, created automatically (no migration step): `password_help` (v0.8.35) and `stored_files` (v0.8.34).

## Checks run
- Unit tests: whole suite in one run, including `tests/test_session35.py` (8: revenue without voided invoices, void filter and search, teacher pay 50% without registration and voided, forgot password flow and limits, admin To do, home data, PDF names).
- Browser: all 10 `tests/e2e_*.py`; `e2e_ui.py` adds Forgot password, Reset and send with WhatsApp, the Dashboard To do, teacher Today, student What to do next.
- Not tested: a real Vercel deployment, PostgreSQL, real phones, a Dhivehi reader checking PDFs.

## Next (Round 2, as agreed)
Fees and Admissions: one-tap slip check next to the invoice, WhatsApp login after approval, WhatsApp reminders for all overdue students in one list, fee statement PDF per student.
