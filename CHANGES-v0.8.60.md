# v0.8.60: Interest list (people who want to join a batch), with a PDF report

Asked:
- An admin section to note new students who want to join an upcoming batch: name, ID card number and contact.
- Choose from batches that already exist, or make an upcoming batch from there.
- Shown batch by batch, and downloadable as a PDF report.

**Name:** the section is called **Interest list**. "Waitlist" is already a status for applications and enrolments, and the same name for both would be confusing.

## Database change (added on its own when the new version starts)
One new empty table, `interest_list`. Nothing existing changes.

## Interest list (new tab, next to Admissions)
**Who:** admins with the Admissions area. Admins limited to other areas, teachers and students cannot see it, and the server refuses them.

**Adding a person** needs:
- the batch;
- the name;
- the ID card number (spaces removed and letters made capital, so `a 123456` becomes `A123456`; passport numbers are accepted);
- a contact number (at least 7 digits).

Email and notes are optional. The same ID card number cannot be added twice to the same batch.

**Batches to choose from:**
- Every batch that is not closed. Batches that have not started are marked "Not started".
- **New upcoming batch** (shown to admins who also have Batches) makes a real batch with the status Open, from the course, code, days, start and end time, start date and seats. Add the teacher and class link in Batches later.

**The list:**
- Shown batch by batch. Each batch shows its days and time, start date, teacher, seats taken and how many people are on its list.
- Filter by batch and by status. The status filter starts at "Still to join". You can also search by name, ID card or number.
- Contact numbers are tap-to-call.
- Each person has a status: **New**, **Contacted**, **Joined** or **Not joining**. You change it straight from the list.
- **Edit** changes any detail or moves the person to another batch. **Delete** removes them.

**Download PDF** gives the list exactly as filtered:
- totals at the top;
- then one section per batch, with the batch details, and #, name, ID card, contact, email, status, date added and notes;
- choose one batch for that batch alone.

**Other details:**
- This list is a reference only: it creates no account, application, enrolment or invoice.
- A batch with names on its interest list cannot be deleted. Close it instead.
- The activity log records adding, changing and deleting people, and every PDF download.
- Settings → Clear data clears the list too.

## Checks run
- Unit tests: whole suite, **586, all pass**.
- New `tests/test_v0860.py` (5 tests):
  - the rules for adding: tidy ID, duplicates, bad contact or email, closed batch;
  - batch by batch, filters, search and status;
  - editing, moving and deleting;
  - the PDF for all batches, one batch and an empty filter;
  - who may use it;
  - a batch with names on its list cannot be deleted.
- Updated tests: `test_session32` (security map) and `test_permissions` (tab list).
- Browser: new `tests/e2e_v0860.py`, at 390 px and 1280 px, **11 checks, all pass**:
  - adding people;
  - a duplicate is refused with a message;
  - people shown under their batch;
  - changing the status and editing;
  - the PDF download;
  - New upcoming batch;
  - no sideways scrolling.
- Not tested: a real PostgreSQL database and the live Vercel site.
