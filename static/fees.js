/* Phase 4 screens: Fees tab for students and admins, fee notices on Home and Dashboard.
   Loaded after learning.js and reuses its helpers (api, apiForm, download, DO, tag, mvToday, S, t, esc, $, val, field, flash, render, mount, ui).
   Money, dates and invoice numbers are wrapped in <bdi dir="ltr"> so they stay left-to-right inside Dhivehi (right-to-left) text. */
const ltr = s => `<bdi dir="ltr">${esc(s)}</bdi>`;
const mvr = n => `<bdi dir="ltr">MVR ${esc(n)}</bdi>`;
const fxMonth = () => mvToday().slice(0, 7);
const fxBadge = i => i.overdue ? tag(t("fx_st_overdue"), "bad") : i.partly_paid ? tag(t("fx_st_partial"), "warn")
  : tag(t("fx_st_" + i.status), {paid: "ok", waived: "ok", unpaid: "warn", slip_submitted: "warn"}[i.status] || "");
const fxPrMonth = () => (S.fxf || {}).prm || fxMonth();
const fxPrQuery = () => { const f = S.fxf || {}; return Object.entries({month: fxPrMonth(), course_id: f.prc, batch_id: f.prb, kind: f.prk, status: f.prs}).filter(([, v]) => v).map(([k, v]) => k + "=" + encodeURIComponent(v)).join("&"); };
const fxPrTag = r => tag(t(r.status_label), {paid: "ok", waived: "ok", partial: "warn", unpaid: "bad", none: ""}[r.status] || "");
const fxFile = ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png";

DO.fxGo = () => { openTab("fees"); return false; };
DO.fxRcpt = async d => { await download(`/payments/${d.id}/receipt.pdf`, `receipt-${d.no}.pdf`); return false; };
DO.fxTab = d => { S.fxt = d.v; S.fxmsg = null; };
const fxSelect = k => { S.fxt = k; S.fxmsg = null; S.fxhl = null; };

// ---------- notices on existing screens ----------
const fxHome = views.home;
views.home = async () => {
  const h = await fxHome();
  if (S.user.role !== "student" || !S.user.tabs.includes("fees")) return h;
  let s; try { s = await api("/my/fees/summary"); } catch (x) { return h; }
  if (!s.open_count) return h;
  const n = `<div class="msg ${s.overdue_count ? "err" : "ok"}" role="status"><b>${t("fx_due_notice")}</b> ${mvr(s.balance_due)} · ${t("fx_due_on")} ${ltr(s.next_due)}${s.overdue_count ? " · " + t("fx_st_overdue") : ""} <button class="btn sm alt" data-do="fxGo">${t("fx_view_fees")}</button></div>`;
  const i = h.indexOf("</h1>");
  return i < 0 ? n + h : h.slice(0, i + 5) + n + h.slice(i + 5);
};
// Session 8: the fee cards on the admin Dashboard are drawn by admin.js (views.dashboard); the old wrapper here was never shown.

// ---------- student ----------
DO.fxUp = d => { S.fxu = +d.id; };
DO.fxUpClose = () => { S.fxu = null; };

async function fxStudent() {
  const d = await api("/my/fees"), b = d.bank;
  mount(() => {
    onSubmit("fxs", async () => {   // an error keeps the form as typed (Session 1)
      const fd = new FormData();
      fd.append("amount_mvr", wholeNum("fxs_a", "fx_amount_sent", {min: 1, empty: false})); fd.append("transfer_date", val("fxs_d")); fd.append("reference", val("fxs_r"));
      const file = $("#fxs_f").files[0]; if (file) fd.append("file", file);
      await apiForm(`/invoices/${S.fxu}/slips`, fd); S.fxu = null;
      return t("fx_slip_sent");
    });
    if (S.fxhl) { const c = $("#inv-" + S.fxhl); S.fxhl = null; if (c) { c.scrollIntoView({block: "center"}); c.focus({preventScroll: true}); } }   // opened from a notification (Session 15)
  });
  const bank = b.configured
    ? `<p>${esc(b.bank_name)}<br>${esc(b.bank_account_name)}<br><b>${ltr(b.bank_account_number)}</b></p><p class="hint">${t("fx_bank_note")}</p>`
    : `<p>${t("fx_bank_missing")}</p>`;
  const form = i => `<form id="fxs" class="row"><label>${t("fx_amount_sent")}<input id="fxs_a" type="number" min="1" step="1" inputmode="numeric" value="${i.balance}" required></label>
    <label>${t("fx_transfer_date")}<input id="fxs_d" type="date" max="${mvToday()}" value="${mvToday()}" required></label>
    <label>${t("fx_reference")}<input id="fxs_r" maxlength="80"></label>
    <label>${t("fx_slip_file")}<input id="fxs_f" type="file" accept="${fxFile}" required></label>
    <p class="full hint">${t("fx_slip_hint")}</p>
    <button class="btn alt">${t("fx_send_slip")}</button> <button type="button" class="btn" data-do="fxUpClose">${t("close")}</button></form>`;
  const card = i => `<div class="panel${S.fxhl === i.id ? " next" : ""}" id="inv-${i.id}" tabindex="-1"><div class="cl"><div><b>${esc(i.description)}</b><br><span class="hint">${ltr(i.number)} · ${t("fx_due_on")} ${ltr(i.due_date)}</span></div>${fxBadge(i)}</div>
    <p>${t("fx_amount_due")}: ${mvr(i.amount_due_mvr)}${i.discount_mvr ? ` · ${t("fx_discount")}: ${mvr(i.discount_mvr)}` : ""}${i.paid_mvr ? ` · ${t("fx_paid")}: ${mvr(i.paid_mvr)}` : ""}${i.balance && !["paid", "waived"].includes(i.status) ? ` · <b>${t("fx_balance")}: ${mvr(i.balance)}</b>` : ""}</p>
    ${i.overdue ? `<div class="msg err">${t("fx_overdue_by")} ${ltr(i.days_overdue)}</div>` : ""}
    ${i.last_rejection ? `<div class="msg err"><b>${t("fx_slip_rejected")}:</b> ${esc(i.last_rejection.reason)}</div>` : ""}
    ${i.pending_slip ? `<div class="msg ok">${t("fx_slip_waiting")} ${mvr(i.pending_slip.amount_mvr)}</div>` : ""}
    ${S.fxu === i.id ? form(i) : i.can_upload ? `<button class="btn" data-do="fxUp" data-id="${i.id}">${t("fx_upload_slip")}</button>` : ""}</div>`;
  const hist = d.payments.length ? d.payments.map(p => `<div class="cl"><div>${ltr(p.paid_on)} · ${mvr(p.amount_mvr)} · ${t("fx_m_" + p.method)}<br><span class="hint">${ltr(p.receipt_no)} · ${ltr(p.period)}</span></div>
    ${p.reversed_at ? tag(t("fx_reversed"), "bad") : `<button class="btn sm" data-do="fxRcpt" data-id="${p.id}" data-no="${esc(p.receipt_no)}">${t("fx_receipt")}</button>`}</div>`).join("") : `<p>${t("empty")}</p>`;
  return `<h1>${t("fees")}</h1><p><button class="btn alt" data-do="fxMyStmt">${t("fx_statement")}</button> <span class="hint">${t("fx_statement_hint")}</span></p><div class="panel"><h2>${t("fx_bank")}</h2>${bank}</div>${d.invoices.length ? d.invoices.map(card).join("") : `<div class="panel"><p>${t("fx_no_invoices")}</p></div>`}
    <div class="panel"><h2>${t("fx_history")}</h2>${hist}</div>`;
}

// ---------- admin ----------
// Session 4: every reason is asked in a ui.js dialog; the server needs one for all of these
const fxAsk = (title, opts = {}) => ui.ask(title, {label: t("fx_prompt_reason"), required: true, multiline: true, ...opts});
const fxSet = (k, v) => { S.fxf = {...(S.fxf || {}), [k]: v}; };

DO.fxView = async d => { await viewFile(`/slips/${d.id}/file`, d.name || "slip"); return false; };
const fxDoVerify = async (id, amount, dup) => {
  if (dup && !await ui.confirm(t("fx_confirm_dup"), {danger: true, okText: t("fx_verify")})) return false;
  const r = await api(`/slips/${id}/verify`, "POST", {amount_mvr: amount, confirm_duplicate: dup});
  flash(`${t("fx_verified")}: ${r.receipt_no}`, true);
};
DO.fxVerify = d => fxDoVerify(d.id, $("#fxv_" + d.id).value.trim(), d.dup === "1");
DO.fxReject = async d => { const r = await fxAsk(t("reject"), {label: t("fx_prompt_reject")}); if (!r) return false; await api(`/slips/${d.id}/reject`, "POST", {reason: r}); flash(t("saved"), true); };
DO.fxMyStmt = async () => { await download("/my/fees/statement.pdf", "fee-statement.pdf"); return false; };
DO.fxStmt = async d => { await download(`/students/${d.id}/statement.pdf`, `fee-statement-${d.id}.pdf`); return false; };
// v0.8.36: one-tap check. The slip and the invoice facts side by side, with Verify and Reject in the same dialog
const fxMatch = s => s.amount_mvr === s.balance ? tag(t("fx_match_full"), "ok") : s.amount_mvr < s.balance ? tag(t("fx_match_part"), "warn") : tag(t("fx_match_over"), "bad");
DO.fxCheck = async d => {
  const s = (S.fxSlipList || []).find(x => x.id === +d.id); if (!s) return;
  const def = Math.min(s.amount_mvr, s.balance) || s.amount_mvr;
  const extra = `<div class="fx-check"><p><b>${esc(s.student_name)}</b> · ${ltr(s.invoice_number)} · ${esc(s.course_name)} ${esc(s.batch_code)}</p>
    <table><tbody><tr><th>${t("fx_amount_sent")}</th><td>${mvr(s.amount_mvr)} ${fxMatch(s)}</td></tr><tr><th>${t("fx_due")}</th><td>${mvr(s.amount_due_mvr)}</td></tr>
    <tr><th>${t("fx_paid_so_far")}</th><td>${mvr(s.paid_mvr)}</td></tr><tr><th>${t("fx_balance")}</th><td>${mvr(s.balance)}</td></tr>
    <tr><th>${t("fx_transfer_date")}</th><td>${ltr(s.transfer_date)}</td></tr>${s.reference ? `<tr><th>${t("fx_reference")}</th><td>${ltr(s.reference)}</td></tr>` : ""}</tbody></table>
    ${s.duplicates.length ? `<div class="msg err">${t("fx_dup_warn")} ${s.duplicates.map(x => ltr(x.invoice_number) + " " + esc(x.student_name)).join(", ")}</div>` : ""}
    <label>${t("fx_amount_received")}<input name="amount" type="number" min="1" step="1" inputmode="numeric" value="${def}"></label>
    <p><button type="button" class="btn sm danger" data-act="reject">${t("reject")}</button></p></div>`;
  const v = await fetchFile(`/slips/${s.id}/file`, {name: s.file_name || "slip", dialog: {title: t("fx_check_slip") + " · " + s.student_name, extra, okText: t("fx_verify"),
    collect: f => { const a = f.elements.amount.value.trim(); if (!(+a > 0)) { f.elements.amount.setAttribute("aria-invalid", "true"); throw new Error(t("fx_amount_needed")); } return {amount: a}; },
    init: (dl, id, finish) => { dl.querySelector('[data-act="reject"]').onclick = () => finish("reject"); }}});
  if (v === "reject") return DO.fxReject({id: s.id});
  if (v && v.amount) return fxDoVerify(s.id, v.amount, !!s.duplicate_verified);
  return false;
};
DO.fxGen = async () => {
  const r = await api("/invoices/generate", "POST", {month: val("fxg_m"), from_month: val("fxg_f") || undefined});
  S.fxGenResult = r.details.filter(x => x.reason !== "already_invoiced");   // shown under the button: who was skipped and why
  flash(`${t("fx_created")}: ${r.created} · ${t("fx_skipped")}: ${r.skipped_total}`, true);
};
DO.fxInvPdf = async d => { await download(`/invoices/${d.id}/invoice.pdf`, `${d.no}.pdf`); return false; };
const fxSkipText = r => ({fee_zero: t("fx_skip_fee_zero"), inactive_student: t("fx_skip_inactive_student"), not_enrolled_yet: t("fx_skip_not_enrolled_yet"),
  first_month_skipped: t("fx_skip_first_month_skipped"), already_invoiced: t("fx_skip_already_invoiced"), not_active: t("fx_skip_not_active")})[r] || r;
const fxSkipList = () => (S.fxGenResult || []).length ? `<div class="msg err"><b>${t("fx_skip_title")}</b><ul>${S.fxGenResult.map(x => `<li>${x.period ? ltr(x.period) + " · " : ""}${esc(x.student)} · ${esc(x.course)} ${esc(x.batch)}: ${esc(fxSkipText(x.reason))}</li>`).join("")}</ul></div>` : "";
// Session 4: one form instead of two prompts and the old "10%" convention
DO.fxDisc = async d => {
  const v = await ui.form(t("fx_discount") + (d.no ? " · " + d.no : ""), [
    {id: "kind", label: t("fx_kind"), type: "select", options: [["fixed", t("fx_disc_fixed")], ["percent", t("fx_disc_percent")]], value: "fixed"},
    {id: "value", label: t("fx_value"), type: "number", required: true, min: 1, step: 1, inputmode: "numeric"},
    {id: "reason", label: t("fx_prompt_reason"), type: "textarea", required: true, maxlength: 300}],
    {okText: t("fx_discount"), validate: x => x.kind === "percent" && +x.value > 100 ? t("fx_disc_over_100") : ""});
  if (!v) return false;
  await api(`/invoices/${d.id}/discount`, "POST", {kind: v.kind, value: v.value, reason: v.reason}); flash(t("saved"), true);
};
// v0.8.37: one reason for all the ticked invoices; each goes through the same route as its own button
DO.fxBulkWaive = async () => { const n = bulkSel("inv").length; const r = await fxAsk(t("fx_waive") + " · " + n, {okText: t("fx_waive")}); if (!r) return false; await bulkRun("inv", id => api(`/invoices/${id}/waive`, "POST", {reason: r})); };
DO.fxBulkVoid = async () => { const n = bulkSel("inv").length; const r = await fxAsk(t("fx_void") + " · " + n, {danger: true, okText: t("fx_void")}); if (!r) return false; await bulkRun("inv", id => api(`/invoices/${id}/void`, "POST", {reason: r})); };
DO.fxVoid = async d => { const r = await fxAsk(t("fx_void"), {danger: true, okText: t("fx_void")}); if (!r) return false; await api(`/invoices/${d.id}/void`, "POST", {reason: r}); flash(t("saved"), true); };
DO.fxWaive = async d => { const r = await fxAsk(t("fx_waive"), {okText: t("fx_waive")}); if (!r) return false; await api(`/invoices/${d.id}/waive`, "POST", {reason: r}); flash(t("saved"), true); };
DO.fxReopen = async d => { const r = await fxAsk(t("fx_reopen"), {okText: t("fx_reopen")}); if (!r) return false; await api(`/invoices/${d.id}/reopen`, "POST", {reason: r}); flash(t("saved"), true); };
DO.fxRev = async d => { const r = await fxAsk(t("fx_reverse"), {danger: true, okText: t("fx_reverse")}); if (!r) return false; await api(`/payments/${d.id}/reverse`, "POST", {reason: r}); flash(t("saved"), true); };
// v0.8.43: the office marks invoices paid and keeps the slip the person sent (WhatsApp, Viber, in person) with the payment
const FX_SLIP_ACCEPT = ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png";
const fxPaidFields = (one, bal) => [
  ...(one ? [{id: "amount", label: t("fx_amount_received"), type: "number", required: true, min: 1, max: bal, step: 1, inputmode: "numeric", value: bal}] : []),
  {id: "method", label: t("fx_method"), type: "select", options: ["bank_transfer", "cash", "other"].map(m => [m, t("fx_m_" + m)]), value: "bank_transfer"},
  {id: "paid_on", label: t("fx_paid_on"), type: "date", required: true, max: mvToday(), value: mvToday(), hint: t("fx_paid_on_hint")},
  {id: "reference", label: t("fx_reference"), maxlength: 80},
  {id: "note", label: t("fx_note"), maxlength: 300},
  {id: "file", label: t("fx_attach_slip"), type: "file", accept: FX_SLIP_ACCEPT, hint: t("fx_attach_slip_hint")},
  {id: "notify", label: t("fx_tell_student"), type: "checkbox", value: one}];
async function fxSendPaid(ids, v) {
  const fd = new FormData();
  fd.append("invoice_ids", ids.join(","));
  if (v.amount) fd.append("amount_mvr", v.amount);
  for (const k of ["method", "paid_on", "reference", "note"]) fd.append(k, v[k] || "");
  if (v.notify) fd.append("notify", "1");
  if (v.file) fd.append("file", v.file);
  const r = await apiForm("/payments/mark-paid", fd);
  return t("fx_marked_paid").replace("{n}", r.payments.length).replace("{m}", fmtNum(r.total_mvr)) + (r.warnings.length ? " " + r.warnings.join(" ") : "");   // the message to show
}
DO.fxPaid = async d => {
  const bal = +d.bal;
  const v = await ui.form(t("fx_mark_paid") + " · " + (d.no || ""), fxPaidFields(true, bal), {okText: t("fx_mark_paid"), hint: (d.name ? d.name + " · " : "") + t("fx_balance") + ": MVR " + fmtNum(bal)});
  if (!v) return false;
  flash(await fxSendPaid([d.id], v), true);
};
DO.fxBulkPaid = async () => {
  const ids = [...bulkSel("inv")], list = (S.fxInvList || []).filter(i => ids.includes(i.id));
  const total = list.reduce((a, i) => a + i.balance, 0);
  const v = await ui.form(t("fx_mark_paid") + " · " + ids.length, fxPaidFields(false), {okText: t("fx_mark_paid"),
    hint: t("fx_bulk_paid_hint").replace("{n}", ids.length).replace("{m}", fmtNum(total)) + " " + list.map(i => i.number + " " + i.student_name).join(", ")});
  if (!v) return false;
  const msg = await fxSendPaid(ids, v); S.bulk.inv = []; flash(msg, true);
};
// ---- v0.8.45: revenue types, manual invoices, editing an invoice ----
async function fxTypes(fresh) { if (fresh || !S.fxTypeList) S.fxTypeList = await api("/revenue-types"); return S.fxTypeList; }
function fxBatchOpts() {
  const s = $("#fxm_b"); if (!s) return;
  const sid = +val("fxm_s"), mine = (S.fxEnr || []).filter(e => e.student_id === sid && ["active", "completed", "dropped"].includes(e.status));
  s.innerHTML = `<option value="">${esc(t("fx_no_batch"))}</option>` + mine.map(e => `<option value="${e.batch_id}">${esc(e.course_name + " " + e.batch_code)}</option>`).join("");
}
async function fxManualSend() {
  const fd = new FormData(), w = val("fxm_w");
  if (w === "student") { if (!val("fxm_s")) throw new Error(t("fx_choose_student")); fd.append("student_id", val("fxm_s")); if (val("fxm_b")) fd.append("batch_id", val("fxm_b")); }
  else { if (!val("fxm_cn")) throw new Error(t("fx_type_customer")); fd.append("customer_name", val("fxm_cn")); fd.append("customer_phone", val("fxm_cp")); }
  fd.append("revenue_type_id", val("fxm_t")); fd.append("amount_mvr", wholeNum("fxm_a", "fx_amount_mvr", {min: 1, empty: false}));
  for (const [k, id] of [["description", "fxm_d"], ["invoice_date", "fxm_id"], ["due_date", "fxm_dd"], ["note", "fxm_n"]]) fd.append(k, val(id));
  if ($("#fxm_p").checked) {
    fd.append("paid", "1"); fd.append("paid_amount_mvr", val("fxm_pa")); fd.append("method", val("fxm_pm")); fd.append("paid_on", val("fxm_pd")); fd.append("reference", val("fxm_pr"));
    if ($("#fxm_pt").checked) fd.append("notify", "1");
    if ($("#fxm_f").files[0]) fd.append("file", $("#fxm_f").files[0]);
  }
  const r = await apiForm("/invoices/manual", fd), i = r.invoice;
  return t("fx_invoice_made").replace("{no}", i.number).replace("{name}", i.student_name) + (r.payments.length ? " " + t("fx_marked_paid").replace("{n}", 1).replace("{m}", fmtNum(r.payments[0].amount_mvr)) : "") + (r.warnings.length ? " " + r.warnings.join(" ") : "");
}
DO.fxRtRename = async d => {
  const v = await ui.ask(t("fx_rename") + ": " + d.name, {label: t("fx_type_name"), value: d.name, required: true}); if (v === null) return false;
  await api("/revenue-types/" + d.id, "PATCH", {name: v}); S.fxTypeList = null; flash(t("saved"), true);
};
DO.fxRtToggle = async d => { await api("/revenue-types/" + d.id, "PATCH", {is_active: d.on === "1"}); S.fxTypeList = null; flash(t("saved"), true); };
document.addEventListener("submit", async e => {
  if (e.target.id !== "fxrt") return; e.preventDefault();
  try { await api("/revenue-types", "POST", {name: val("fxrt_n")}); S.fxTypeList = null; flash(t("saved"), true); render(); } catch (x) { flash(x.message, false); }
});
DO.fxEdit = async d => {
  const i = (S.fxInvList || []).find(x => x.id === +d.id) || await api("/invoices/" + d.id), types = await fxTypes();
  const opts = types.filter(r => r.is_active || r.id === i.revenue_type).map(r => [String(r.id), r.name]);
  const v = await ui.form(t("edit") + " · " + i.number, [
    {id: "amount", label: t("fx_amount_mvr"), type: "number", required: true, min: 1, step: 1, inputmode: "numeric", value: i.amount_mvr, hint: i.discount_mvr ? t("fx_edit_disc_hint").replace("{m}", fmtNum(i.discount_mvr)) : t("fx_edit_amount_hint").replace("{m}", fmtNum(i.paid_mvr))},
    {id: "reason", label: t("fx_edit_reason"), hint: t("fx_edit_reason_hint")},
    {id: "type", label: t("fx_revenue_type"), type: "select", options: opts, value: String(i.revenue_type)},
    {id: "desc", label: t("fx_description"), required: true, value: i.description},
    {id: "due", label: t("fx_due_on"), type: "date", required: true, value: i.due_date},
    ...(i.walk_in ? [{id: "cn", label: t("fx_customer_name"), required: true, value: i.student_name}, {id: "cp", label: t("phone"), value: i.student_phone || ""}] : [])],
    {okText: t("save"), hint: i.student_name + " · " + t("fx_balance") + ": MVR " + fmtNum(i.balance), validate: v => +v.amount !== i.amount_mvr && !v.reason ? t("fx_edit_reason_needed") : null});
  if (!v) return false;
  const b = {revenue_type_id: v.type, description: v.desc, due_date: v.due};
  if (+v.amount !== i.amount_mvr) { b.amount_mvr = v.amount; b.reason = v.reason; }
  if (i.walk_in) { b.customer_name = v.cn; b.customer_phone = v.cp; }
  const r = await api("/invoices/" + i.id, "PATCH", b); flash(r.changed ? t("saved") : t("fx_nothing_changed"), true);
};
DO.fxEnd = async d => { await api("/discounts/" + d.id, "DELETE"); flash(t("saved"), true); };
DO.fxFamDel = async d => { await api(`/families/${d.fid}/members/${d.sid}`, "DELETE"); flash(t("saved"), true); };
DO.fxRemind = async d => {   // open the chat first (popup blockers need it inside the click), then record that it was sent
  if (d.url) window.open(d.url, "_blank", "noopener");
  await api(`/invoices/${d.id}/reminders`, "POST", {channel: d.ch, to: d.to}); flash(t("fx_reminder_logged"), true);
};
// v0.8.36: step through everyone not reminded today, oldest first; WhatsApp to the student (or the guardian when only that number is there)
DO.fxNext = async () => {
  const i = (S.fxOverdue || []).filter(x => !x.reminded_today && Object.keys(x.links).length).sort((a, b) => b.days_overdue - a.days_overdue)[0];
  if (!i) return;
  const who = i.links.student ? "student" : Object.keys(i.links)[0];
  return DO.fxRemind({id: i.id, ch: "whatsapp", to: who, url: i.links[who].whatsapp});
};
DO.fxEmail = async d => { await api(`/invoices/${d.id}/reminders/email`, "POST", {}); flash(t("fx_email_sent"), true); };
DO.fxPrCsv = async () => { const q = fxPrQuery(); await download("/fees/payment-report.csv?" + q, `payments-${fxPrMonth()}.csv`); return false; };
DO.fxPrXlsx = async () => { const q = fxPrQuery(); await download("/fees/payment-report.xlsx?" + q, `payments-${fxPrMonth()}.xlsx`); return false; };
DO.fxPrHist = d => { S.fxf = {...(S.fxf || {}), hist: +d.id}; };
DO.fxPrBack = () => { S.fxf = {...(S.fxf || {}), hist: null}; };
DO.fxXlsx = async () => { const m = val("fxr_m") || fxMonth(); await download("/fees/report.xlsx?month=" + m, `fees-${m}.xlsx`); return false; };   // v0.8.38
DO.fxCsv = async () => { const m = val("fxr_m") || fxMonth(); await download("/fees/report.csv?month=" + m, `fees-${m}.csv`); return false; };

const FX_OPEN = i => ["unpaid", "slip_submitted"].includes(i.status);
const invRow = i => `<div class="cl ${i.status === "void" ? "off" : ""}"><div>${FX_OPEN(i) ? bulkBox("inv", i.id, i.number + " " + i.student_name) + " " : ""}<b>${esc(i.student_name)}</b> ${fxBadge(i)}${i.walk_in ? " " + tag(t("fx_not_in_portal")) : ""}<br><span class="hint">${ltr(i.number)} · ${i.course_name ? esc(i.course_name) + " " + esc(i.batch_code || "") : esc(i.description)} · ${esc(i.revenue_type_name || "")} · ${t("fx_due_on")} ${ltr(i.due_date)}</span><br>${mvr(i.amount_due_mvr)} · ${t("fx_balance")}: ${mvr(i.balance)}${i.status_reason ? `<br><span class="hint">${esc(i.status_reason)}</span>` : ""}</div>
  <div class="seg"><button class="btn sm" data-do="fxInvPdf" data-id="${i.id}" data-no="${esc(i.number)}">${t("fx_invoice_pdf")}</button>${i.status !== "void" ? `<button class="btn sm alt" data-do="fxEdit" data-id="${i.id}">${t("edit")}</button>` : ""}${["unpaid", "slip_submitted"].includes(i.status) && i.balance > 0 ? `<button class="btn sm" data-do="fxPaid" data-id="${i.id}" data-no="${esc(i.number)}" data-name="${esc(i.student_name)}" data-bal="${i.balance}">${t("fx_mark_paid")}</button>` : ""}${["unpaid", "slip_submitted"].includes(i.status) ? `<button class="btn sm" data-do="fxDisc" data-id="${i.id}" data-no="${esc(i.number)}">${t("fx_discount")}</button><button class="btn sm" data-do="fxWaive" data-id="${i.id}">${t("fx_waive")}</button><button class="btn sm" data-do="fxVoid" data-id="${i.id}">${t("fx_void")}</button>` : ""}${["void", "waived"].includes(i.status) ? `<button class="btn sm" data-do="fxReopen" data-id="${i.id}">${t("fx_reopen")}</button>` : ""}</div></div>`;

const FX = {
  async slips() {
    const l = await api("/slips?status=pending"); S.fxSlipList = l;
    const hl = S.fxhl; if (hl) mount(() => { const c = document.querySelector(`[data-inv="${hl}"]`); S.fxhl = null; if (c) { c.scrollIntoView({block: "center"}); c.focus({preventScroll: true}); } });
    return `<div class="panel"><h2>${t("fx_tab_slips")}</h2>${l.length ? l.map(s => `<div class="sub${hl === s.invoice_id ? " next" : ""}" data-inv="${s.invoice_id}" tabindex="-1"><b>${esc(s.student_name)}</b> · ${ltr(s.invoice_number)} · ${esc(s.course_name)} ${esc(s.batch_code)}<br>
      ${t("fx_amount_sent")}: ${mvr(s.amount_mvr)} · ${t("fx_balance")}: ${mvr(s.balance)} · ${t("fx_transfer_date")}: ${ltr(s.transfer_date)}${s.reference ? ` · ${t("fx_reference")}: ${ltr(s.reference)}` : ""}
      ${s.duplicates.length ? `<div class="msg err">${t("fx_dup_warn")} ${s.duplicates.map(x => ltr(x.invoice_number) + " " + esc(x.student_name)).join(", ")}</div>` : ""}
      <div class="rowflex row"><button class="btn sm" data-do="fxCheck" data-id="${s.id}">${t("fx_check_slip")}</button><button class="btn sm alt" data-do="fxView" data-id="${s.id}" data-name="${esc(s.file_name)}">${t("fx_view_slip")}</button>
      <label style="flex:0 1 150px">${t("fx_amount_received")}<input id="fxv_${s.id}" type="number" min="1" step="1" inputmode="numeric" value="${Math.min(s.amount_mvr, s.balance) || s.amount_mvr}"></label>
      <button class="btn" data-do="fxVerify" data-id="${s.id}" data-dup="${s.duplicate_verified ? 1 : 0}">${t("fx_verify")}</button><button class="btn alt" data-do="fxReject" data-id="${s.id}">${t("reject")}</button></div></div>`).join("") : `<p>${t("fx_no_slips")}</p>`}</div>`;
  },
  async invoices() {
    const f = S.fxf || {}, q = new URLSearchParams();
    if (f.month) q.set("month", f.month); if (f.status) q.set("status", f.status); if (f.q) q.set("q", f.q); if (f.rt) q.set("revenue_type", f.rt);
    const [l, types] = await Promise.all([api("/invoices?" + q), fxTypes()]); S.fxInvList = l;
    mount(() => { const ff = $("#fxff"); if (ff) { $("#fxf_s").value = f.status || ""; $("#fxf_t").value = f.rt || ""; ff.onsubmit = e => { e.preventDefault(); fxSet("month", val("fxf_m")); fxSet("status", val("fxf_s")); fxSet("q", val("fxf_q")); fxSet("rt", val("fxf_t")); render(); }; } });
    return `<div class="panel"><h2>${t("fx_generate")}</h2><div class="rowflex row"><label>${t("fx_from_month")}<input id="fxg_f" type="month"></label><label>${t("fx_month")}<input id="fxg_m" type="month" value="${fxMonth()}"></label><button class="btn alt" data-do="fxGen">${t("fx_generate")}</button></div><p class="hint">${t("fx_generate_hint")} ${t("fx_from_month_hint")}</p>${fxSkipList()}</div>
      <div class="panel"><form id="fxff" class="row"><label>${t("fx_month")}<input id="fxf_m" type="month" value="${esc(f.month || "")}"></label>
      <label>${t("status")}<select id="fxf_s"><option value="">${t("fx_all_but_void")}</option><option value="all">${t("fx_all_with_void")}</option>${["unpaid", "slip_submitted", "overdue", "paid", "waived", "void"].map(s => `<option value="${s}">${t("fx_st_" + s)}</option>`).join("")}</select></label>
      <label>${t("fx_revenue_type")}<select id="fxf_t"><option value="">${t("all")}</option>${types.map(r => `<option value="${r.id}">${esc(r.name)}</option>`).join("")}</select></label>
      <label>${t("fx_search")}<input id="fxf_q" value="${esc(f.q || "")}"></label><button class="btn">${t("fx_filter")}</button></form><p>${xlBtns("/invoices/export", q.toString(), "invoices")}</p></div>
      <div class="panel">${bulkBar("inv", [["fxBulkPaid", "fx_mark_paid"], ["fxBulkWaive", "fx_waive"], ["fxBulkVoid", "fx_void", true]], l.filter(FX_OPEN).map(i => i.id))}${bulkAll("inv", l.filter(FX_OPEN).map(i => i.id))}${l.length ? l.map(invRow).join("") : `<p>${t("empty")}</p>`}</div>`;
  },
  // v0.8.45: an invoice made by hand: a student (optionally tied to one of their batches) or someone not in the portal; can be paid in the same step
  async manual() {
    const [types, studs, enr] = await Promise.all([fxTypes(true), api("/users?role=student"), api("/enrollments")]);
    const act = types.filter(r => r.is_active);
    S.fxEnr = enr;
    mount(() => {
      const who = () => { const w = val("fxm_w"); $("#fxm_sbox").hidden = w !== "student"; $("#fxm_cbox").hidden = w !== "customer"; fxBatchOpts(); };
      const paid = () => { $("#fxm_pbox").hidden = !$("#fxm_p").checked; };
      if ($("#fxm_w")) { $("#fxm_w").onchange = who; $("#fxm_s").onchange = fxBatchOpts; $("#fxm_p").onchange = paid; who(); paid(); }
      onSubmit("fxm", fxManualSend);
    });
    const typeRow = r => `<div class="cl${r.is_active ? "" : " off"}"><div><b>${esc(r.name)}</b> ${r.built_in ? tag(t("fx_built_in")) : ""} ${r.is_active ? "" : tag(t("inactive"), "warn")}<br><span class="hint">${t("fx_n_invoices").replace("{n}", r.invoices)}</span></div>
      <div class="seg"><button class="btn sm alt" data-do="fxRtRename" data-id="${r.id}" data-name="${esc(r.name)}">${t("fx_rename")}</button>${r.built_in ? "" : `<button class="btn sm" data-do="fxRtToggle" data-id="${r.id}" data-on="${r.is_active ? 0 : 1}">${r.is_active ? t("fx_turn_off") : t("fx_turn_on")}</button>`}</div></div>`;
    return `<div class="panel"><h2>${t("fx_tab_manual")}</h2><p class="hint">${t("fx_manual_hint")}</p><form id="fxm" class="row">
      <label>${t("fx_bill_to")}<select id="fxm_w"><option value="student">${t("fx_bill_student")}</option><option value="customer">${t("fx_bill_customer")}</option></select></label>
      <div id="fxm_sbox" class="rowflex full">${pickField("fxm_s", "student", [["", "-"], ...studs.filter(u => u.is_active !== 0).map(u => [u.id, u.full_name + (u.login_id ? " (" + u.login_id + ")" : "")])], "")}
        <label>${t("fx_link_batch")}<select id="fxm_b"></select><span class="hint">${t("fx_link_batch_hint")}</span></label></div>
      <div id="fxm_cbox" class="rowflex full" hidden><label>${t("fx_customer_name")}<input id="fxm_cn" maxlength="100"></label><label>${t("phone")}<input id="fxm_cp" maxlength="30" inputmode="tel"></label></div>
      <label>${t("fx_revenue_type")}<select id="fxm_t">${act.map(r => `<option value="${r.id}">${esc(r.name)}</option>`).join("")}</select></label>
      <label>${t("fx_description")}<input id="fxm_d" maxlength="200" placeholder="${esc(t("fx_description_ph"))}"></label>
      <label>${t("fx_amount_mvr")}<input id="fxm_a" type="number" min="1" step="1" inputmode="numeric" required></label>
      <label>${t("fx_invoice_date")}<input id="fxm_id" type="date" value="${mvToday()}"><span class="hint">${t("fx_invoice_date_hint")}</span></label>
      <label>${t("fx_due_date_opt")}<input id="fxm_dd" type="date"></label>
      <label>${t("fx_note")}<input id="fxm_n" maxlength="300"></label>
      <label class="inl full"><input id="fxm_p" type="checkbox"> ${t("fx_already_paid")}</label>
      <div id="fxm_pbox" class="rowflex full" hidden>
        <label>${t("fx_amount_paid_opt")}<input id="fxm_pa" type="number" min="1" step="1" inputmode="numeric"><span class="hint">${t("fx_amount_paid_hint")}</span></label>
        ${field("fxm_pm", t("fx_method"), "", ["bank_transfer", "cash", "other"].map(m => [m, t("fx_m_" + m)]))}
        <label>${t("fx_paid_on")}<input id="fxm_pd" type="date" max="${mvToday()}" value="${mvToday()}"></label><label>${t("fx_reference")}<input id="fxm_pr" maxlength="80"></label>
        <label>${t("fx_attach_slip")}<input id="fxm_f" type="file" accept="${FX_SLIP_ACCEPT}"><span class="hint">${t("fx_attach_slip_hint")}</span></label>
        <label class="inl"><input id="fxm_pt" type="checkbox"> ${t("fx_tell_student")}</label></div>
      <button class="btn alt">${t("fx_create_invoice")}</button></form></div>
      <div class="panel"><h2>${t("fx_revenue_types")}</h2><p class="hint">${t("fx_revenue_types_hint")}</p>${types.map(typeRow).join("")}
      <form id="fxrt" class="row"><label>${t("fx_new_type")}<input id="fxrt_n" maxlength="60" required></label><button class="btn alt">${t("add")}</button></form></div>`;
  },
  async record() {
    const [inv, pays] = await Promise.all([api("/invoices?status=open"), api("/payments")]);
    mount(() => onSubmit("fxp", () => fxSendPaid([val("fxp_i")], {amount: wholeNum("fxp_a", "fx_amount_received", {min: 1, empty: false}), method: val("fxp_m"), paid_on: val("fxp_d"), reference: val("fxp_r"), note: val("fxp_n"), file: $("#fxp_f").files[0] || null, notify: $("#fxp_t").checked})));
    return `<div class="panel"><h2>${t("fx_tab_record")}</h2>${inv.length ? `<form id="fxp" class="row">${field("fxp_i", t("fx_invoice"), "", inv.map(i => [i.id, `${i.number} · ${i.student_name} · MVR ${i.balance}`]))}
      <label>${t("fx_amount_received")}<input id="fxp_a" type="number" min="1" step="1" inputmode="numeric" required></label>${field("fxp_m", t("fx_method"), "", ["cash", "bank_transfer", "other"].map(m => [m, t("fx_m_" + m)]))}
      <label>${t("date")}<input id="fxp_d" type="date" max="${mvToday()}" value="${mvToday()}"></label><label>${t("fx_reference")}<input id="fxp_r"></label><label>${t("fx_note")}<input id="fxp_n"></label><label>${t("fx_attach_slip")}<input id="fxp_f" type="file" accept="${FX_SLIP_ACCEPT}"><span class="hint">${t("fx_attach_slip_hint")}</span></label><label class="inl"><input id="fxp_t" type="checkbox" checked> ${t("fx_tell_student")}</label><button class="btn alt">${t("fx_record")}</button></form>` : `<p>${t("fx_nothing_open")}</p>`}</div>
      <div class="panel"><h2>${t("fx_payments")}</h2>${pays.slice(0, 30).map(p => `<div class="cl ${p.reversed_at ? "off" : ""}"><div><b>${esc(p.student_name)}</b> · ${mvr(p.amount_mvr)} · ${t("fx_m_" + p.method)}<br><span class="hint">${ltr(p.receipt_no)} · ${ltr(p.invoice_number)} · ${ltr(p.paid_on)}${p.reversed_at ? " · " + esc(p.reverse_reason || "") : ""}</span></div>
      <div class="seg">${p.reversed_at ? tag(t("fx_reversed"), "bad") : `${p.slip_id ? `<button class="btn sm alt" data-do="fxView" data-id="${p.slip_id}" data-name="${esc(p.slip_file_name || "slip")}">${t("fx_view_slip")}</button>` : ""}<button class="btn sm" data-do="fxRcpt" data-id="${p.id}" data-no="${esc(p.receipt_no)}">${t("fx_receipt")}</button><button class="btn sm" data-do="fxRev" data-id="${p.id}">${t("fx_reverse")}</button>`}</div></div>`).join("") || `<p>${t("empty")}</p>`}</div>`;
  },
  async discounts() {
    const [ds, fams, en, st] = await Promise.all([api("/discounts"), api("/families"), api("/enrollments"), api("/users?role=student")]);
    const kinds = [["fixed", "MVR"], ["percent", "%"]];
    mount(() => {
      onSubmit("fxd", () => api("/discounts", "POST", {enrollment_id: val("fxd_e"), kind: val("fxd_k"), value: val("fxd_v"), reason: val("fxd_r")}));
      onSubmit("fxfam", () => api("/families", "POST", {name: val("fxfam_n"), concession_kind: val("fxfam_k"), concession_value: val("fxfam_v") || 0, concession_reason: val("fxfam_r")}));
      onSubmit("fxm", () => api(`/families/${val("fxm_f")}/members`, "POST", {student_id: val("fxm_s")}));
    });
    const dsHtml = ds.length ? ds.map(d => `<div class="cl"><div><b>${esc(d.student_name)}</b> · ${esc(d.course_name)} ${esc(d.batch_code)}<br>${d.kind === "percent" ? ltr(d.value + "%") : mvr(d.value)} · ${esc(d.reason)}</div><button class="btn sm" data-do="fxEnd" data-id="${d.id}">${t("fx_end")}</button></div>`).join("") : `<p>${t("empty")}</p>`;
    const famHtml = fams.length ? fams.map(f => `<div class="sub"><b>${esc(f.name)}</b> · ${f.concession_kind ? (f.concession_kind === "percent" ? ltr(f.concession_value + "%") : mvr(f.concession_value)) : t("fx_none")}${f.concession_reason ? " · " + esc(f.concession_reason) : ""}
      ${f.members.map(m => `<div class="cl"><span>${esc(m.full_name)}</span><button class="btn sm" data-do="fxFamDel" data-fid="${f.id}" data-sid="${m.student_id}">${t("fx_remove")}</button></div>`).join("")}</div>`).join("") : `<p>${t("empty")}</p>`;
    return `<div class="panel"><h2>${t("fx_recurring")}</h2>${dsHtml}${form("fxd", field("fxd_e", t("fx_enrollment"), "", en.filter(e => e.status === "active").map(e => [e.id, `${e.student_name} · ${e.course_name} ${e.batch_code}`])) + field("fxd_k", t("fx_kind"), "", kinds) + `<label>${t("fx_value")}<input id="fxd_v" type="number" min="1" step="1" required></label>` + `<label>${t("fx_reason")}<input id="fxd_r" required></label>`, "add")}</div>
      <div class="panel"><h2>${t("fx_families")}</h2><p class="hint">${t("fx_family_hint")}</p>${famHtml}
      ${form("fxfam", `<label>${t("fx_family_name")}<input id="fxfam_n" required></label>` + field("fxfam_k", t("fx_kind"), "", kinds) + `<label>${t("fx_value")}<input id="fxfam_v" type="number" min="0" step="1"></label><label>${t("fx_reason")}<input id="fxfam_r"></label>`, "add")}
      ${fams.length && st.length ? form("fxm", field("fxm_f", t("fx_family_name"), "", fams.map(f => [f.id, f.name])) + field("fxm_s", "student", "", st.map(s => [s.id, s.full_name])), t("fx_add_member")) : ""}</div>`;
  },
  async overdue() {
    const r = await api("/fees/overdue"), l = r.items;
    const btn = (i, who, ch, url) => `<button class="btn sm" data-do="fxRemind" data-id="${i.id}" data-ch="${ch}" data-to="${who}" data-url="${esc(url)}">${ch === "whatsapp" ? t("fx_whatsapp") : t("fx_viber")}${who === "guardian" ? " · " + t("fx_guardian") : ""}</button>`;
    S.fxOverdue = l;
    const left = l.filter(i => !i.reminded_today && Object.keys(i.links).length).length;
    const next = l.length ? `<p class="rowflex">${left ? `<button class="btn" data-do="fxNext">${t("fx_remind_next")}</button>` : ""}<span class="hint">${left ? t("fx_remind_left").replace("{n}", left) : t("fx_remind_done")}</span></p>` : "";
    return `<div class="panel"><h2>${t("fx_tab_overdue")}</h2>${next}${r.email_enabled ? "" : `<p class="hint">${t("fx_email_off")}</p>`}${l.length ? l.map(i => `<div class="sub"><b>${esc(i.student_name)}</b> · ${ltr(i.number)} · ${mvr(i.balance)}<br><span class="hint">${t("fx_overdue_by")} ${ltr(i.days_overdue)} · ${t("fx_due_on")} ${ltr(i.due_date)}</span>
      ${i.last_reminder ? `<div class="msg ${i.reminded_today ? "err" : "ok"}">${t("fx_last_reminder")}: ${esc(i.last_reminder.channel)} · ${ltr(i.last_reminder.sent_at.slice(0, 10))} · ${esc(i.last_reminder.by_name || "")}${i.reminded_today ? " · " + t("fx_reminded_today") : ""}</div>` : ""}
      <div class="seg"><button class="btn sm" data-do="fxPaid" data-id="${i.id}" data-no="${esc(i.number)}" data-name="${esc(i.student_name)}" data-bal="${i.balance}">${t("fx_mark_paid")}</button>${Object.entries(i.links).map(([who, k]) => btn(i, who, "whatsapp", k.whatsapp) + btn(i, who, "viber", k.viber)).join("") || `<span class="hint">${t("fx_no_phone")}</span>`}${r.email_enabled ? `<button class="btn sm" data-do="fxEmail" data-id="${i.id}">${t("fx_email")}</button>` : ""}</div></div>`).join("") : `<p>${t("fx_no_overdue")}</p>`}</div>`;
  },
  async payrep() {
    const f = S.fxf || {};
    if (f.hist) {
      const h = await api("/fees/student-history/" + f.hist);
      return `<div class="panel"><p><button class="btn sm alt" data-do="fxPrBack">${t("Back")}</button></p><h2>${esc(h.student.full_name)} <span class="hint">${esc(h.student.student_code || "")}</span></h2>
        <p>${t("Due")}: ${mvr(h.totals.due)} · ${t("fx_collected")}: ${mvr(h.totals.paid)} · ${t("fx_balance")}: ${mvr(h.totals.balance)}</p>
        ${h.invoices.map(i => `<div class="sub"><b>${ltr(i.period)}</b> · ${esc(i.course_name)} ${esc(i.batch_code)} · ${mvr(i.amount_due_mvr)} · ${t("fx_balance")}: ${mvr(i.balance_mvr)} ${tag(t("fx_st_" + i.status), i.status === "paid" ? "ok" : "warn")}
          ${i.payments.map(p => `<div class="hint">${ltr(p.paid_on)} · ${mvr(p.amount_mvr)} · ${esc(p.method)} · ${ltr(p.receipt_no)}${p.reversed_at ? " · " + t("Reversed") : ""}</div>`).join("") || `<div class="hint">${t("No payments yet")}</div>`}</div>`).join("") || `<p>${t("empty")}</p>`}</div>`;
    }
    const [r, courses, batches] = await Promise.all([api("/fees/payment-report?" + fxPrQuery()), api("/courses"), api("/batches")]);
    const T_ = r.totals, sel = (id, cur, opts) => `<select id="${id}"><option value="">${t("All")}</option>${opts.map(([v, l]) => `<option value="${esc(v)}" ${String(cur || "") === String(v) ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
    mount(() => { const fm = $("#fxpr"); if (fm) fm.onsubmit = e => { e.preventDefault(); S.fxf = {...(S.fxf || {}), prm: val("fxp_m") || fxMonth(), prc: val("fxp_c"), prb: val("fxp_b"), prk: val("fxp_k"), prs: val("fxp_s")}; render(); }; });
    return `<div class="panel"><form id="fxpr" class="rowflex row"><label>${t("fx_month")}<input id="fxp_m" type="month" value="${esc(r.month)}"></label>
      <label>${t("Course")}${sel("fxp_c", f.prc, courses.map(c => [c.id, c.name]))}</label><label>${t("Batch")}${sel("fxp_b", f.prb, batches.map(b => [b.id, (b.course_name || "") + " " + b.code]))}</label>
      <label>${t("Type")}${sel("fxp_k", f.prk, [["course", t("Course")], ["tuition", t("Tuition class")]])}</label>
      <label>${t("Status")}${sel("fxp_s", f.prs, [["paid", t("Paid")], ["partial", t("Partially Paid")], ["unpaid", t("Unpaid")], ["waived", t("Waived")], ["none", t("No invoice")]])}</label>
      <button class="btn">${t("fx_show")}</button><button type="button" class="btn alt" data-do="fxPrCsv">${t("fx_csv")}</button><button type="button" class="btn alt" data-do="fxPrXlsx">${t("Download Excel")}</button></form></div>
      <div class="stats">${[[t("Students"), T_.students, 0], [t("Due"), T_.due, 1], [t("fx_collected"), T_.paid, 1], [t("fx_outstanding"), T_.balance, 1]].map(([k, v, m]) => `<div class="stat"><b>${m ? mvr(v) : v}</b>${k}</div>`).join("")}</div>
      <div class="panel">${r.rows.length ? `<table><thead><tr><th>${t("Student")}</th><th>${t("Course")}</th><th>${t("Batch")}</th><th>${t("Fee")}</th><th>${t("Status")}</th><th>${t("Paid")}</th><th>${t("fx_balance")}</th><th>${t("Payment dates")}</th><th></th></tr></thead><tbody>${r.rows.map(x => `<tr><td>${esc(x.student_name)} <span class="hint">${esc(x.student_code || "")}</span></td><td>${esc(x.course_name)}</td><td>${esc(x.batch_code)}</td><td>${mvr(x.monthly_fee_mvr)}</td><td>${fxPrTag(x)}</td><td>${mvr(x.paid_mvr)}</td><td>${mvr(x.balance_mvr)}</td><td>${x.payments.map(p => ltr(p.paid_on)).join(", ")}</td><td><button class="btn sm" data-do="fxPrHist" data-id="${x.student_id}">${t("History")}</button></td></tr>`).join("")}</tbody></table>` : `<p>${t("empty")}</p>`}</div>`;
  },
  async report() {
    const m = (S.fxf || {}).rep || fxMonth();
    const r = await api("/fees/report?month=" + m), T_ = r.totals;
    mount(() => { const f = $("#fxr"); if (f) f.onsubmit = e => { e.preventDefault(); fxSet("rep", val("fxr_m") || fxMonth()); render(); }; });
    return `<div class="panel"><form id="fxr" class="row"><label>${t("fx_month")}<input id="fxr_m" type="month" value="${esc(m)}"></label><button class="btn">${t("fx_show")}</button><button type="button" class="btn alt" data-do="fxCsv">${t("fx_csv")}</button><button type="button" class="btn alt" data-do="fxXlsx">${t("Download Excel")}</button></form></div>
      <div class="stats">${[[t("fx_invoiced"), T_.invoiced], [t("fx_collected"), T_.collected], [t("fx_outstanding"), T_.outstanding]].map(([k, v]) => `<div class="stat"><b>${mvr(v)}</b>${k}</div>`).join("")}<div class="stat"><b>${T_.overdue_count}</b>${t("fx_st_overdue")}</div></div>
      <div class="panel"><h2>${t("fx_by_course")}</h2>${r.by_course.map(c => `<div class="cl"><span>${esc(c.course_name)}</span><span>${mvr(c.collected)} / ${mvr(c.invoiced)}</span></div>`).join("") || `<p>${t("empty")}</p>`}</div>
      <div class="panel"><h2>${t("fx_who_owes")}</h2>${r.owing.map(o => `<div class="cl"><div><b>${esc(o.student_name)}</b> ${o.overdue ? tag(t("fx_st_overdue"), "bad") : ""}<br><span class="hint">${ltr(o.number)} · ${esc(o.course_name)} ${esc(o.batch_code)}</span></div>${mvr(o.balance)}</div>`).join("") || `<p>${t("fx_nobody_owes")}</p>`}</div>`;
  },
};
const FX_TABS = ["slips", "invoices", "manual", "record", "discounts", "overdue", "report", "payrep"];

async function fxAdmin() {
  if (!S.fxCaughtUp) { S.fxCaughtUp = true; try { await api("/invoices/catch-up", "POST"); } catch (x) { /* not allowed or offline: the Fees screen still opens */ } }   // bills anyone enrolled since the last run
  const tab = S.fxt || "slips";
  const inner = await FX[tab]();
  return `<h1>${t("fees")}</h1>${tabs({id: "fees", items: FX_TABS.map(k => [k, t("fx_tab_" + k)]), current: tab, onSelect: fxSelect, label: t("fees")})}${inner}`;
}

views.fees = async () => S.user.role === "admin" ? fxAdmin() : fxStudent();
