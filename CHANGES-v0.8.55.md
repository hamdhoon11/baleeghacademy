# v0.8.55: a Batch filter and a "Show recent" filter on every list of students; Batches on the Dashboard

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

## Show: recently enrolled / added
Next to Batch, every list (not Admissions) has **Show**:
- **Everyone**;
- **Enrolled in the last 7 days** or **in the last 30 days**, by the enrolment's start date;
- **Added in the last 7 days** or **in the last 30 days**, by when the account was made;
- **Newest first**.

The chosen list is shown newest first. Admins are hidden while a Show choice is on (they are neither enrolled nor students).

## Dashboard → Batches (new section)
- Each batch with students:
  - its teacher;
  - students now / capacity, and "+2 new" (enrolled in the last 30 days);
  - for admins with the Fees area, this month's fees collected / due, a small bar (blue = collected, orange = still to pay) and how many still owe.
- **Fees** opens that batch in Fees → Record payment (its fee status grid). Without the Fees area, the button is **Students** and opens People filtered to the batch.
- **Recently enrolled** (last 8) and **Recently added** (last 8) lists.
- **Enrolled / Added in the last 30 days** buttons open Enrollments / People with that filter on.
- Batches with no students are counted, not listed.

## Server
- New `GET /api/batch-members` (any admin): the batches, which students are in each (active enrolments), who teaches each, each student's newest enrolment date, and when each account was made. The page caches it for 30 seconds.
- New `GET /api/admin/batch-overview` (any admin; money figures only with the Fees area).

## Checks run
- Unit tests: whole suite, **549, all pass**.
  - `test_session53` test_04 and test_05: the batch-members data and its dates, the dashboard overview, no money figures without the Fees area, sign-in needed.
  - `test_session32`'s security map lists both new routes.
- Browser: new `tests/e2e_v0855.py` at 390 px, **36 checks, all pass**:
  - Batch filters on People, Enrollments (sorted and one batch), Invoices, Overdue invoices, Fee reminders, Slips and Who's online;
  - Show → added in 30 days (People) and enrolled in 7 days (Enrollments);
  - Dashboard → Batches, its Fees button and its "Added in the last 30 days" button;
  - no sideways scrolling;
  - the Record payment checks at 390 and 1280 px.
- On a phone the batch shows on its own line under the name.
