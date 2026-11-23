# v0.8.64: imports follow the Excel registry, an income statement, and a better Fees grid

Asked: "The Baleegh Academy expenses and revenue registry was updated in this Excel file, so the import template should be based on it. Make
the changes, and make more improvements to the Finance and Fees sections after a good review."

**Database change: additive only.** It is made automatically when the new version starts; there is no script to run.
- New columns: `revenue_types.ledger_code`, `expense_categories.code` and `kind`. Expenses get `supplier`, `supplier_gst_no`,
  `invoice_no`, `gst_mvr`, `usd_amount`, `fx_rate` and `amount_exact`.
- New table: `fee_notes`.
- The two built-in revenue types get the registry's codes: Registration fees 1001, Monthly fees 1002.

## Imports now use the registry's layout
You can **upload the registry workbook as it is**. The portal reads its *Revenue Registry* or *Expense Registry* sheet and ignores the
other sheets. It skips the title row, the scratch cells beside the table, the numbered empty rows and the SUM rows at the bottom.

The templates have the same sheet names and the same columns, so you can copy rows between your Excel and a template. Every import is
still **Check file** (nothing is saved, every row is listed) → **Import**. The check now says what each row will do.

### Revenue registry (new). Fees → New invoice → "Import the revenue registry"
The columns are as in your registry: No, Date, Student ID, Name, Course, Revenue Code, Payment Type, GST %, Discount, Amount Due, Total Paid,
Invoice No. Three optional columns can be added at the end: **Fee Month**, Method and Reference.

What happens to each row:
1. **The same payment is already in the portal** (same person, day, amount and type): the row is skipped. The same file can be imported
   again without doubling anything.
2. **A monthly or registration fee with an open invoice in the portal**: the payment is recorded on that invoice, with a receipt number.
   - A month that is **already paid in the portal** is skipped.
   - A month **paid by an earlier row of the same file** is refused, with the reason. The registry has no fee-month column, so the month of
     the Date is used. If the second payment was for another month, write that month in Fee Month.
3. **Anything else** becomes a new invoice that is already paid. It is tied to the student's batch, so it counts in the grid and the reports.

Other rules:
- **Student ID typed with the letter I for the digit 1** (BAL/ALI/0NN): it is read as BAL/AL1/0NN when that matches exactly one student.
  The check tells you it did this.
- **A Student ID that is not in the portal** is refused. If you tick "Record under their name", it is recorded as "not in the portal",
  like a walk-in customer.
- **A Revenue Code the portal does not know** (1003 Advance Payment) becomes a new revenue type named after the Payment Type. Untick
  "Add new codes" to refuse such rows instead.
- The registry invoice number is kept as the payment reference. Nobody is sent a message.

### Expense registry. Finance → "Import the expense registry"
The columns are as in your registry: No, Date, GST No., Name, Invoice No., Expense Code, Expense Type, MVR, GST %, Discount, Amount Due, $,
Total.
- **Amount**: Total. When Total is empty, MVR + $ × the dollar rate − Discount.
  - The rate is **Settings → Fees → US dollar rate**, default 15.42, as in the registry.
  - Amounts are rounded to whole MVR, like every amount in the portal.
  - The exact amount, the dollars and the rate are kept with the expense.
- **Expense Code → category**. An unknown code becomes a new category named after the Expense Type. Cap-EX types are marked capital
  spending.
- **Already in the portal** (same supplier and invoice number; or, without an invoice number, same day, amount, category and supplier):
  skipped.
- The old template (expense_date, amount_mvr, category) still works.

## Finance
- **Income statement** (new panel): your Monthly Report, made from the portal. Choose the year; months run January to this month.
  - **Revenue by revenue code**, by the month the money was received.
  - **Accrued**: fees for that month still to pay, by batch.
  - **Expenses by code**.
  - **Capital spending** (Cap-EX), shown apart.
  - Profit lines: **Collected profit** (revenue − expenses), **Budgeted profit** (if all fees were paid), and **After capital spending**.
  - **Download Excel**: the Monthly Report layout with live SUM formulas. **Download PDF** is also there.
- **Download the registry (Excel)**: one workbook for the year with Revenue Registry (every payment), Expense Registry, Monthly Report,
  and one payment-history sheet per batch. Uploading it again adds nothing.
- **Categories** have a code and a kind (running expense or capital spending). **Edit** changes the name, code and kind together.
- **Expenses** have optional "Paid to", "Their invoice number" and "Paid in US dollars". Typing dollars fills the MVR amount at the rate.
  The list shows the supplier, invoice number and dollars. The Excel export has these columns too.

## Fees
- **Record payment → Fee status by batch**, like the registry's payment history sheets:
  - **"2 months late"** tag on each student who is behind. It counts all their overdue months in that batch, not only the months shown.
    The tooltip gives the amount and since when.
  - **Comment** per student and batch, like the registry's Comments column (for example "Need reminder 3rd month"). Tap to add or change
    it. It is for the office only, and it is in the activity log.
  - **Paid / not paid** counts for each month.
  - **Download Excel**: one sheet per batch with Student ID, Name, the months (Paid / Not paid / Part paid / Slip sent / Waived), Months
    late, Comments, Total Paid and Total Not Paid.
- **Revenue types** show their registry code. **Code** sets it, and a new type can have one.

## Found in the registry workbook (not changed, for you to look at)
- **Monthly Report revenue for July, August and September shows 0.** The SUMIFS formulas in J5:L7 point at C5, G5 and H5 instead of B5.
  The registry itself has 6,650, 5,950 and 2,800 MVR of monthly fees in those months.
- **"Student Payment History_A1B1" looks up the wrong cell for October to December.** Columns I:K use `B3`, `C3`, `D3`… instead of
  `$A3`, so those months can never show "Paid".
- **Total Revenue subtracts the Advance Fee** (`-G7`), and Total Expenses leaves out Capex. The portal counts the advance as revenue in the
  month it was paid, and shows Capex apart.
- **Expense Registry totals**: `=SUM(H3:H45)` and similar stop at row 45.
- **Rows to check before importing** (two fees for the same month, a second registration fee, students not in the portal, IDs typed with
  the letter I, an invoice number used twice): the Check file result lists each one with its reason. The details for this registry are
  in the Project's copy of these notes, not here, because this repository is public.

## Checks run
- **Unit tests:** whole suite, **611, all pass**.
- **New `tests/test_v0864.py`** (8 tests). It uses a made-up workbook with the registry's exact shape. Your real file and the names in it are **not**
  in the repository, which is public.
  - The templates.
  - Revenue: check, import, and import again (nothing added). An open invoice is paid; a month paid twice is refused; Fee Month fixes it;
    the ALI typo; students not in the portal; a new revenue code; too much for an open invoice; and permissions.
  - Expenses: dollars, the rate setting, capital, skipping duplicates, and the old template.
  - Codes.
  - The income statement, its Excel and PDF, the registry workbook, and the round trip.
  - The grid: months late, comments, counts and Excel.
  - Formula text stays text. A walk-in with a student's name stays a walk-in.
  - The upgrade of an older database.
- **Updated tests:**
  - `test_session32`: the security map lists `/api/import/revenue` (Fees).
  - `test_session38` and `test_session49`: the expense template has the registry layout.
  - `e2e_excel`: fills the new template.
- **Your real workbook**, against a copy set up like the academy (Arabic, batches L1001–L1003, the registry's student IDs):
  - Revenue: 113 of 122 rows import. The 5 refused are listed above. 2 are recorded under their names when that box is ticked. The 4
    numbered empty rows are skipped.
  - Expenses: all 59 import.
  - Importing again adds nothing.
  - The income statement matches your sheet's figures within rounding: marketing 7,494 against 7,492.58; maintenance 1,483; salaries
    5,548; capex 4,190. For July to September it shows the real figures.
- **Browser:**
  - **New `tests/e2e_v0864.py`**, at 390 px and 1280 px, **all pass**: both imports, the grid tag, comment and Excel, the income
    statement and its downloads, a dollar expense, and category edit.
  - Also re-run and passing: `e2e_excel`, `e2e_manual_invoice`, `e2e_v0852`, `e2e_mark_paid`, `e2e_permissions`, `e2e_navigation`,
    `e2e_v0863`, `e2e_browser`.
- **Not tested:**
  - **PostgreSQL.** The database driver cannot be installed in this session. The new SQL is standard; `REAL` becomes `DOUBLE PRECISION`
    there.
  - The live Vercel site.
  - Microsoft Excel itself. The files were opened in LibreOffice.

## Good to know
- **Teacher earnings.** Imported monthly fees tied to a batch count in teacher earnings, by fee month, the same as fees entered by hand. A
  month that is already approved gets them as late rows when you press Calculate.
- **Salary rows** (5005) come in as plain expenses. To link one to a teacher's pay record, open it and choose the teacher.
- **Very long files** are sent in parts of 200 rows. A month paid twice across two parts is reported as "already paid in the portal"
  (skipped) instead of refused. The registry is well under 200 rows a year.
