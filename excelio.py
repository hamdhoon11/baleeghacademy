"""v0.8.38: Excel (and CSV) for imports and exports, in one place.

read_table(file)       an uploaded .xlsx or .csv -> (header, [(row_number, {column: text})]). Excel dates, times and numbers become plain text
                       (2026-09-01, 16:00, 350), so the same checks work for both kinds of file.
template(...)          an .xlsx to fill in: a "Data" sheet with the column names (required ones marked in the header colour), drop-down
                       lists where a column has fixed choices, text format for codes and phone numbers (so 0771234 keeps its 0),
                       an "Instructions" sheet (what to write in each column, with an example) and, when given, a "Lists" sheet of what
                       already exists (course codes, batch codes, teachers, categories) that the drop-downs point to.
send_table(...)        a table as a .csv or .xlsx download (formula-safe text, logged by the caller).
call(...)              runs one existing API route inside the current request, as the same signed-in person. Imports of courses, batches,
                       expenses and grades send every row through the route the screen uses, so each row gets exactly the same checks,
                       rules and activity-log line as typing it in by hand.
dry_run_scope(conn)    lets a check ("dry run") go through those routes and then undo everything: commits are held and each row sits in a
                       savepoint, so a bad row is undone on its own and the good rows still count for the next ones (a code used twice
                       in one file is caught).
"""
import contextlib, csv, datetime as dt, io, re
from flask import Response, current_app, jsonify, request
from werkzeug.exceptions import HTTPException

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_ROWS, MAX_BYTES = 2000, 2 * 1024 * 1024
HEAD_FILL, REQ_FILL = "0B4F5C", "B8432F"


def csv_safe(v):
    """Text that a spreadsheet would run as a formula (= + - @, tab, return at the start) gets an apostrophe in front (same rule as payreports)."""
    return "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") else ("" if v is None else v)


def unsafe(v):
    return v[1:] if v[:1] == "'" and v[1:2] in ("=", "+", "-", "@") else v


def norm_head(h):
    h = re.sub(r"\s*\*\s*$", "", str(h or "").strip().lower())   # "full_name *" in older templates
    return re.sub(r"[\s-]+", "_", h)


def _cell_text(v):
    if v is None: return ""
    if isinstance(v, bool): return "1" if v else "0"
    if isinstance(v, dt.datetime):
        return v.date().isoformat() if (v.hour, v.minute, v.second) == (0, 0, 0) else v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, dt.date): return v.isoformat()
    if isinstance(v, dt.time): return v.strftime("%H:%M")
    if isinstance(v, float): return str(int(v)) if v.is_integer() else repr(v)
    return str(v).strip()


def read_table(f=None):
    """The uploaded file (form field "file", or the raw body for CSV). Raises ValueError with a message fit to show."""
    f = f if f is not None else request.files.get("file")
    raw = f.read(MAX_BYTES + 1) if f else (request.get_data() or b"")
    name = (getattr(f, "filename", "") or "").lower()
    if not raw.strip(): raise ValueError("No file received. Choose an Excel (.xlsx) or CSV file.")
    if len(raw) > MAX_BYTES: raise ValueError("The file is larger than 2 MB. Split it into smaller files.")
    if raw[:2] == b"PK" or name.endswith((".xlsx", ".xlsm")):
        grid = _xlsx_rows(raw)
    elif name.endswith(".xls") or raw[:4] == b"\xd0\xcf\x11\xe0":
        raise ValueError("This is an old Excel file (.xls). In Excel choose File > Save As > Excel Workbook (.xlsx), then try again.")
    else:
        try: text = raw.decode("utf-8-sig")
        except UnicodeDecodeError: raise ValueError("The file must be an Excel workbook (.xlsx) or a CSV saved as UTF-8.")
        grid = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text))]
    grid = [(n, r) for n, r in enumerate(grid, 1)]
    while grid and not any(grid[0][1]): grid.pop(0)
    if not grid: raise ValueError("The file is empty.")
    hn, head = grid[0]; head = [norm_head(h) for h in head]
    body = []
    for n, r in grid[1:]:
        if not any(x for x in r): continue
        body.append((n, {head[i]: unsafe(r[i]) for i in range(min(len(head), len(r))) if head[i]}))
    if len(body) > MAX_ROWS: raise ValueError(f"More than {MAX_ROWS} rows. Split the file.")
    return head, body


def _xlsx_rows(raw):
    from openpyxl import load_workbook
    try: wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception: raise ValueError("This Excel file could not be opened. Save it again as .xlsx and try once more.")
    try:
        names = wb.sheetnames
        sheet = wb["Data"] if "Data" in names else next((wb[n] for n in names if n not in ("Instructions", "Lists")), wb[names[0]])
        out = []
        for i, r in enumerate(sheet.iter_rows(values_only=True)):
            if i > MAX_ROWS + 50: break
            out.append([_cell_text(v) for v in r])
        while out and not any(out[-1]): out.pop()
        return out
    finally:
        wb.close()


def template(title, columns, lists=None, rows=None, note=None):
    """columns: dicts {key, required, example, help, choices (list) or list_ref ("Lists" column title), text (bool), width}.
    lists: {title: [values]} written to a "Lists" sheet. rows: optional rows to pre-fill (e.g. the class list for grades)."""
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.utils import get_column_letter as L
    wb = Workbook(); ws = wb.active; ws.title = "Data"
    lists = {k: v for k, v in (lists or {}).items() if v is not None}
    for i, c in enumerate(columns, 1):
        cell = ws.cell(row=1, column=i, value=c["key"])
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=REQ_FILL if c.get("required") else HEAD_FILL)
        cell.alignment = Alignment(vertical="center")
        if c.get("help"): cell.comment = Comment(("Required. " if c.get("required") else "") + c["help"] + (f"\nExample: {c['example']}" if c.get("example") not in (None, "") else ""), "Baleegh Academy")
        ws.column_dimensions[L(i)].width = c.get("width") or max(14, min(40, len(c["key"]) + 4))
    ws.freeze_panes = "A2"
    for r in rows or []:
        ws.append([csv_safe(v) for v in r])
    for i, c in enumerate(columns, 1):   # text format for codes and phone numbers: on the whole column, and on the rows already filled in
        if c.get("text"):
            ws.column_dimensions[L(i)].number_format = "@"
            for r in range(2, ws.max_row + 1): ws.cell(row=r, column=i).number_format = "@"
    # Lists sheet and drop-downs
    if lists:
        ls = wb.create_sheet("Lists")
        for j, (name, vals) in enumerate(lists.items(), 1):
            ls.cell(row=1, column=j, value=name).font = Font(bold=True)
            for k, v in enumerate(vals, 2): ls.cell(row=k, column=j, value=v)
            ls.column_dimensions[L(j)].width = max(16, min(44, max([len(str(name))] + [len(str(v)) for v in vals]) + 2))
    for i, c in enumerate(columns, 1):
        src = None
        if c.get("choices"): src = '"' + ",".join(c["choices"]) + '"'
        elif c.get("list_ref") and c["list_ref"] in lists and lists[c["list_ref"]]:
            j = list(lists).index(c["list_ref"]) + 1
            src = f"Lists!${L(j)}$2:${L(j)}${len(lists[c['list_ref']]) + 1}"
        if src and len(src) < 255:
            dv = DataValidation(type="list", formula1=src, allow_blank=not c.get("required"), showErrorMessage=not c.get("free"))
            dv.error, dv.errorTitle = "Choose a value from the list.", "Not in the list"
            ws.add_data_validation(dv); dv.add(f"{L(i)}2:{L(i)}1001")
    # Instructions
    ins = wb.create_sheet("Instructions", 1)   # Data, Instructions, Lists
    ins.append([title]); ins["A1"].font = Font(bold=True, size=14)
    ins.append(["Fill in the Data sheet: one row per record, from row 2. Red column names are required; the others may be left empty."])
    ins.append(["Do not rename the column names in row 1. Save as Excel (.xlsx) and upload it in the portal. Press Check file first: nothing is saved until you press Import."])
    if note: ins.append([note])
    ins.append([])
    ins.append(["Column", "Required", "What to write", "Example"])
    for cell in ins[ins.max_row]: cell.font = Font(bold=True)
    for c in columns:
        ins.append([c["key"], "yes" if c.get("required") else "", (c.get("help") or "") + (f" Choose from: {', '.join(c['choices'])}." if c.get("choices") else ""), str(c.get("example") if c.get("example") is not None else "")])
    for col, w in zip("ABCD", (24, 10, 90, 26)): ins.column_dimensions[col].width = w
    for r in ins.iter_rows(min_row=1):
        for cell in r: cell.alignment = Alignment(wrap_text=True, vertical="top")
    wb.active = 0
    out = io.BytesIO(); wb.save(out)
    return out.getvalue()


def xlsx_bytes(headers, table, sheet="Report", text_cols=()):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter as L
    wb = Workbook(); ws = wb.active; ws.title = (sheet or "Report")[:31]
    ws.append(list(headers))
    for cell in ws[1]: cell.font, cell.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor=HEAD_FILL)
    for r in table: ws.append([csv_safe(v) for v in r])
    for i, h in enumerate(headers, 1):
        width = max([len(str(h))] + [len(str(r[i - 1] if i - 1 < len(r) and r[i - 1] is not None else "")) for r in table[:300]])
        ws.column_dimensions[L(i)].width = min(max(width + 2, 10), 50)
        if h in text_cols:
            for row in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                for cell in row: cell.number_format = "@"
    ws.freeze_panes = "A2"
    if table: ws.auto_filter.ref = f"A1:{L(len(headers))}{len(table) + 1}"
    out = io.BytesIO(); wb.save(out)
    return out.getvalue()


def send_table(ext, name, headers, table, sheet=None, text_cols=()):
    if ext == "csv":
        buf = io.StringIO(); w = csv.writer(buf); w.writerow(headers)
        for r in table: w.writerow([csv_safe(v) for v in r])
        body, mime = buf.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8"
    else:
        body, mime = xlsx_bytes(headers, table, sheet or name, text_cols), XLSX_MIME
    resp = Response(body, mimetype=mime)
    resp.headers["Content-Disposition"] = f'attachment; filename="{name}.{ext}"'
    resp.headers["Cache-Control"] = "private, no-store"
    return resp


def send_xlsx(body, name):
    resp = Response(body, mimetype=XLSX_MIME)
    resp.headers["Content-Disposition"] = f'attachment; filename="{name}.xlsx"'
    resp.headers["Cache-Control"] = "private, no-store"
    return resp


def call(method, path, json=None, query=None):
    """Run an API route as the person making this request. Returns (status_code, json_body or {})."""
    app = current_app._get_current_object()
    with app.test_request_context(path, method=method, json=json, query_string=query, headers={"Authorization": request.headers.get("Authorization", "")}):
        from flask import request as inner
        try:
            if inner.routing_exception: raise inner.routing_exception
            rv = app.view_functions[inner.url_rule.endpoint](**(inner.view_args or {}))
            resp = app.make_response(rv)
        except HTTPException as x:
            return x.code or 400, {"error": x.description}
        return resp.status_code, (resp.get_json(silent=True) or {})


@contextlib.contextmanager
def dry_run_scope(conn):
    """During a check: commit() does nothing and rollback() only undoes the current row; at the end everything is undone."""
    conn.commit()   # whatever came before the check (sign-in bookkeeping) is kept; nothing of the check is
    if not conn.pg: conn.raw.execute("BEGIN")   # SQLite: an outer transaction, or releasing the first savepoint would commit it
    orig_commit, orig_rollback = conn.commit, conn.rollback
    conn.commit = lambda: None
    conn.rollback = lambda: conn.execute("ROLLBACK TO SAVEPOINT imp_row")
    try: yield
    finally:
        conn.commit, conn.rollback = orig_commit, orig_rollback
        conn.raw.rollback()


@contextlib.contextmanager
def row_savepoint(conn, dry):
    """In a check: each row in its own savepoint (kept when it passes, undone when it fails). In a real import: nothing extra."""
    if not dry:
        yield; return
    conn.execute("SAVEPOINT imp_row")
    try:
        yield
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT imp_row"); conn.execute("RELEASE SAVEPOINT imp_row"); raise
    conn.execute("RELEASE SAVEPOINT imp_row")


def import_response(kind, dry, total, ok, bad, out):
    resp = jsonify(kind=kind, dry_run=dry, total=total, ok=ok, rejected=bad, rows=out)
    resp.headers["Cache-Control"] = "no-store"
    return resp


def want_dry():
    return request.args.get("dry_run", "1").lower() not in ("0", "false", "no")
