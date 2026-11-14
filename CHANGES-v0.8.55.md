# v0.8.55: a Batch filter on every list of students

Asked: in every section, include the batch-wise view so students are easier to sort and find.

## One Batch filter, on every list
Choices: **All batches**, **All, sorted by batch**, each batch by name, and **Not in a batch**. The choice is kept for each screen while you move around the portal.

| Screen | What the filter uses |
|---|---|
| People | students in the batch and the batch's teacher (admins are hidden while a batch is chosen); each student and teacher shows their batches under the name |
| Enrollments | the enrolment's batch; "sorted by batch" lists batch by batch |
| Admissions | the batch the applicant asked for |
| Fees → Slips to verify | the student's batches |
| Fees → Invoices | the invoice's batch (a hand-made invoice with no batch goes by the student's batches; "Not in a batch" = invoices with no batch) |
| Fees → Overdue invoices | as Invoices; each row also shows the course and batch |
| Fees → Fee reminders (WhatsApp) | the student's batches (people not in the portal are under "Not in a batch"); totals follow the filter; the batch shows under the name |
| Who's online | students in the batch and its teacher |

Already batch by batch (unchanged): Fees → Record payment (filter and fee status grid, v0.8.52–54), Student information (batch filter), Payment report and Monthly report, Classroom, Batches.

## Server
New `GET /api/batch-members` (any admin): the batches, which students are in each (active enrolments), and who teaches each. Cached by the page for 30 seconds.

## Checks run
- Unit tests: whole suite, **548, all pass**. `test_session53` test_04 checks the batch-members data and that sign-in is needed. `test_session32`'s security map lists the new route.
- Browser: new `tests/e2e_v0855.py` at 390 px: People, Enrollments (sorted and one batch), Invoices, Overdue invoices, Fee reminders, Slips and Who's online filters, no sideways scrolling; plus the Record payment checks at 390 and 1280 px. **30 checks, all pass.** On a phone the batch shows on its own line under the name.
