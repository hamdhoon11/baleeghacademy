/* Phase 4 screens: Fees tab for students and admins, fee notices on Home and Dashboard.
   Loaded after learning.js and reuses its helpers (api, apiForm, download, DO, tag, mvToday, S, t, esc, $, val, field, flash, render).
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

DO.fxGo = () => { S.view = "fees"; };
DO.fxRcpt = async d => { await download(`/payments/${d.id}/receipt.pdf`, `receipt-${d.no}.pdf`); return false; };
DO.fxTab = d => { S.fxt = d.v; S.fxmsg = null; };

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
const fxDash = views.dashboard;
views.dashboard = async () => {
  const [h, d] = await Promise.all([fxDash(), api("/dashboard")]);
  const st = [[t("fx_unpaid_invoices"), d.unpaid_invoices], [t("fx_overdue_invoices"), d.overdue_invoices], [t("fx_slips_pending"), d.slips_pending], [t("fx_month_collection"), "MVR " + d.month_collection_mvr]];
  return h.replace('<div class="panel">', `<div class="stats">${st.map(([k, v]) => `<div class="stat"><b><bdi dir="ltr">${esc(v)}</bdi></b>${esc(k)}</div>`).join("")}</div><div class="panel">`);
};

// ---------- student ----------
DO.fxUp = d => { S.fxu = +d.id; };
DO.fxUpClose = () => { S.fxu = null; };

async function fxStudent() {
  const d = await api("/my/fees"), b = d.bank;
  setTimeout(() => {
    const f = $("#fxs"); if (!f) return;
    f.onsubmit = async e => {
      e.preventDefault();
      const fd = new FormData();
      fd.append("amount_mvr", val("fxs_a")); fd.append("transfer_date", val("fxs_d")); fd.append("reference", val("fxs_r"));
      const file = $("#fxs_f").files[0]; if (file) fd.append("file", file);
      try { await apiForm(`/invoices/${S.fxu}/slips`, fd); S.fxu = null; flash(t("fx_slip_sent"), true); } catch (x) { flash(x.message); }
      render();
    };
  });
  const bank = b.configured
    ? `<p>${esc(b.bank_name)}<br>${esc(b.bank_account_name)}<br><b>${ltr(b.bank_account_number)}</b></p><p class="hint">${t("fx_bank_note")}</p>`
    : `<p>${t("fx_bank_missing")}</p>`;
  const form = i => `<form id="fxs" class="row"><label>${t("fx_amount_sent")}<input id="fxs_a" type="number" min="1" step="1" inputmode="numeric" value="${i.balance}" required></label>
    <label>${t("fx_transfer_date")}<input id="fxs_d" type="date" max="${mvToday()}" value="${mvToday()}" required></label>
    <label>${t("fx_reference")}<input id="fxs_r" maxlength="80"></label>
    <label>${t("fx_slip_file")}<input id="fxs_f" type="file" accept="${fxFile}" required></label>
    <p class="hint" style="flex:1 1 100%">${t("fx_slip_hint")}</p>
    <button class="btn alt">${t("fx_send_slip")}</button> <button type="button" class="btn" data-do="fxUpClose">${t("close")}</button></form>`;
  const card = i => `<div class="panel"><div class="cl"><div><b>${esc(i.description)}</b><br><span class="hint">${ltr(i.number)} · ${t("fx_due_on")} ${ltr(i.due_date)}</span></div>${fxBadge(i)}</div>
    <p>${t("fx_amount_due")}: ${mvr(i.amount_due_mvr)}${i.discount_mvr ? ` · ${t("fx_discount")}: ${mvr(i.discount_mvr)}` : ""}${i.paid_mvr ? ` · ${t("fx_paid")}: ${mvr(i.paid_mvr)}` : ""}${i.balance && !["paid", "waived"].includes(i.status) ? ` · <b>${t("fx_balance")}: ${mvr(i.balance)}</b>` : ""}</p>
    ${i.overdue ? `<div class="msg err">${t("fx_overdue_by")} ${ltr(i.days_overdue)}</div>` : ""}
    ${i.last_rejection ? `<div class="msg err"><b>${t("fx_slip_rejected")}:</b> ${esc(i.last_rejection.reason)}</div>` : ""}
    ${i.pending_slip ? `<div class="msg ok">${t("fx_slip_waiting")} ${mvr(i.pending_slip.amount_mvr)}</div>` : ""}
    ${S.fxu === i.id ? form(i) : i.can_upload ? `<button class="btn" data-do="fxUp" data-id="${i.id}">${t("fx_upload_slip")}</button>` : ""}</div>`;
  const hist = d.payments.length ? d.payments.map(p => `<div class="cl"><div>${ltr(p.paid_on)} · ${mvr(p.amount_mvr)} · ${t("fx_m_" + p.method)}<br><span class="hint">${ltr(p.receipt_no)} · ${ltr(p.period)}</span></div>
    ${p.reversed_at ? tag(t("fx_reversed"), "bad") : `<button class="btn sm" data-do="fxRcpt" data-id="${p.id}" data-no="${esc(p.receipt_no)}">${t("fx_receipt")}</button>`}</div>`).join("") : `<p>${t("empty")}</p>`;
  return `<h1>${t("fees")}</h1><div class="panel"><h2>${t("fx_bank")}</h2>${bank}</div>${d.invoices.length ? d.invoices.map(card).join("") : `<div class="panel"><p>${t("fx_no_invoices")}</p></div>`}
    <div class="panel"><h2>${t("fx_history")}</h2>${hist}</div>`;
}

// ---------- admin ----------
const fxAsk = text => { const r = prompt(text); return r && r.trim() ? r.trim() : null; };
const fxSet = (k, v) => { S.fxf = {...(S.fxf || {}), [k]: v}; };

DO.fxView = async d => { await viewFile(`/slips/${d.id}/file`, d.name || "slip"); return false; };
DO.fxVerify = async d => {
  const amount = $("#fxv_" + d.id).value.trim();
  if (d.dup === "1" && !confirm(t("fx_confirm_dup"))) return false;
  const r = await api(`/slips/${d.id}/verify`, "POST", {amount_mvr: amount, confirm_duplicate: d.dup === "1"});
  flash(`${t("fx_verified")}: ${r.receipt_no}`, true);
};
DO.fxReject = async d => { const r = fxAsk(t("fx_prompt_reject")); if (!r) return false; await api(`/slips/${d.id}/reject`, "POST", {reason: r}); flash(t("saved"), true); };
DO.fxGen = async () => {
  const r = await api("/invoices/generate", "POST", {month: val("fxg_m")});
  S.fxGenResult = r.details.filter(x => x.reason !== "already_invoiced");   // shown under the button: who was skipped and why
  flash(`${t("fx_created")}: ${r.created} · ${t("fx_skipped")}: ${r.skipped_total}`, true);
};
DO.fxInvPdf = async d => { await download(`/invoices/${d.id}/invoice.pdf`, `${d.no}.pdf`); return false; };
const fxSkipText = r => ({fee_zero: t("fx_skip_fee_zero"), inactive_student: t("fx_skip_inactive_student"), not_enrolled_yet: t("fx_skip_not_enrolled_yet"),
  first_month_skipped: t("fx_skip_first_month_skipped"), already_invoiced: t("fx_skip_already_invoiced"), not_active: t("fx_skip_not_active")})[r] || r;
const fxSkipList = () => (S.fxGenResult || []).length ? `<div class="msg err"><b>${t("fx_skip_title")}</b><ul>${S.fxGenResult.map(x => `<li>${esc(x.student)} · ${esc(x.course)} ${esc(x.batch)}: ${esc(fxSkipText(x.reason))}</li>`).join("")}</ul></div>` : "";
DO.fxDisc = async d => {
  const v = fxAsk(t("fx_prompt_discount")); if (!v) return false;
  const r = fxAsk(t("fx_prompt_reason")); if (!r) return false;
  const pctv = v.endsWith("%");
  await api(`/invoices/${d.id}/discount`, "POST", {kind: pctv ? "percent" : "fixed", value: v.replace("%", "").trim(), reason: r}); flash(t("saved"), true);
};
DO.fxVoid = async d => { const r = fxAsk(t("fx_prompt_reason")); if (!r) return false; await api(`/invoices/${d.id}/void`, "POST", {reason: r}); flash(t("saved"), true); };
DO.fxWaive = async d => { const r = fxAsk(t("fx_prompt_reason")); if (!r) return false; await api(`/invoices/${d.id}/waive`, "POST", {reason: r}); flash(t("saved"), true); };
DO.fxReopen = async d => { const r = fxAsk(t("fx_prompt_reason")); if (!r) return false; await api(`/invoices/${d.id}/reopen`, "POST", {reason: r}); flash(t("saved"), true); };
DO.fxRev = async d => { const r = fxAsk(t("fx_prompt_reason")); if (!r) return false; await api(`/payments/${d.id}/reverse`, "POST", {reason: r}); flash(t("saved"), true); };
DO.fxEnd = async d => { await api("/discounts/" + d.id, "DELETE"); flash(t("saved"), true); };
DO.fxFamDel = async d => { await api(`/families/${d.fid}/members/${d.sid}`, "DELETE"); flash(t("saved"), true); };
DO.fxRemind = async d => {   // open the chat first (popup blockers need it inside the click), then record that it was sent
  if (d.url) window.open(d.url, "_blank", "noopener");
  await api(`/invoices/${d.id}/reminders`, "POST", {channel: d.ch, to: d.to}); flash(t("fx_reminder_logged"), true);
};
DO.fxEmail = async d => { await api(`/invoices/${d.id}/reminders/email`, "POST", {}); flash(t("fx_email_sent"), true); };
DO.fxPrCsv = async () => { const q = fxPrQuery(); await download("/fees/payment-report.csv?" + q, `payments-${fxPrMonth()}.csv`); return false; };
DO.fxPrXlsx = async () => { const q = fxPrQuery(); await download("/fees/payment-report.xlsx?" + q, `payments-${fxPrMonth()}.xlsx`); return false; };
DO.fxPrHist = d => { S.fxf = {...(S.fxf || {}), hist: +d.id}; };
DO.fxPrBack = () => { S.fxf = {...(S.fxf || {}), hist: null}; };
DO.fxCsv = async () => { const m = val("fxr_m") || fxMonth(); await download("/fees/report.csv?month=" + m, `fees-${m}.csv`); return false; };

const invRow = i => `<div class="cl ${i.status === "void" ? "off" : ""}"><div><b>${esc(i.student_name)}</b> ${fxBadge(i)}<br><span class="hint">${ltr(i.number)} · ${esc(i.course_name)} ${esc(i.batch_code)} · ${t("fx_due_on")} ${ltr(i.due_date)}</span><br>${mvr(i.amount_due_mvr)} · ${t("fx_balance")}: ${mvr(i.balance)}${i.status_reason ? `<br><span class="hint">${esc(i.status_reason)}</span>` : ""}</div>
  <div class="seg"><button class="btn sm" data-do="fxInvPdf" data-id="${i.id}" data-no="${esc(i.number)}">${t("fx_invoice_pdf")}</button>${["unpaid", "slip_submitted"].includes(i.status) ? `<button class="btn sm" data-do="fxDisc" data-id="${i.id}">${t("fx_discount")}</button><button class="btn sm" data-do="fxWaive" data-id="${i.id}">${t("fx_waive")}</button><button class="btn sm" data-do="fxVoid" data-id="${i.id}">${t("fx_void")}</button>` : ""}${["void", "waived"].includes(i.status) ? `<button class="btn sm" data-do="fxReopen" data-id="${i.id}">${t("fx_reopen")}</button>` : ""}</div></div>`;

const FX = {
  async slips() {
    const l = await api("/slips?status=pending");
    return `<div class="panel"><h2>${t("fx_tab_slips")}</h2>${l.length ? l.map(s => `<div class="sub"><b>${esc(s.student_name)}</b> · ${ltr(s.invoice_number)} · ${esc(s.course_name)} ${esc(s.batch_code)}<br>
      ${t("fx_amount_sent")}: ${mvr(s.amount_mvr)} · ${t("fx_balance")}: ${mvr(s.balance)} · ${t("fx_transfer_date")}: ${ltr(s.transfer_date)}${s.reference ? ` · ${t("fx_reference")}: ${ltr(s.reference)}` : ""}
      ${s.duplicates.length ? `<div class="msg err">${t("fx_dup_warn")} ${s.duplicates.map(x => ltr(x.invoice_number) + " " + esc(x.student_name)).join(", ")}</div>` : ""}
      <div class="row" style="display:flex;flex-wrap:wrap;gap:.6rem;align-items:end"><button class="btn sm" data-do="fxView" data-id="${s.id}" data-name="${esc(s.file_name)}">${t("fx_view_slip")}</button>
      <label style="flex:0 1 150px">${t("fx_amount_received")}<input id="fxv_${s.id}" type="number" min="1" step="1" inputmode="numeric" value="${Math.min(s.amount_mvr, s.balance) || s.amount_mvr}"></label>
      <button class="btn" data-do="fxVerify" data-id="${s.id}" data-dup="${s.duplicate_verified ? 1 : 0}">${t("fx_verify")}</button><button class="btn alt" data-do="fxReject" data-id="${s.id}">${t("reject")}</button></div></div>`).join("") : `<p>${t("fx_no_slips")}</p>`}</div>`;
  },
  async invoices() {
    const f = S.fxf || {}, q = new URLSearchParams();
    if (f.month) q.set("month", f.month); if (f.status) q.set("status", f.status); if (f.q) q.set("q", f.q);
    const l = await api("/invoices?" + q);
    setTimeout(() => { const ff = $("#fxff"); if (ff) { $("#fxf_s").value = f.status || ""; ff.onsubmit = e => { e.preventDefault(); fxSet("month", val("fxf_m")); fxSet("status", val("fxf_s")); fxSet("q", val("fxf_q")); render(); }; } });
    return `<div class="panel"><h2>${t("fx_generate")}</h2><div class="row" style="display:flex;flex-wrap:wrap;gap:.6rem;align-items:end"><label>${t("fx_month")}<input id="fxg_m" type="month" value="${fxMonth()}"></label><button class="btn alt" data-do="fxGen">${t("fx_generate")}</button></div><p class="hint">${t("fx_generate_hint")}</p>${fxSkipList()}</div>
      <div class="panel"><form id="fxff" class="row"><label>${t("fx_month")}<input id="fxf_m" type="month" value="${esc(f.month || "")}"></label>
      <label>${t("status")}<select id="fxf_s"><option value="">${t("fx_all")}</option>${["unpaid", "slip_submitted", "overdue", "paid", "waived", "void"].map(s => `<option value="${s}">${t("fx_st_" + s)}</option>`).join("")}</select></label>
      <label>${t("fx_search")}<input id="fxf_q" value="${esc(f.q || "")}"></label><button class="btn">${t("fx_filter")}</button></form></div>
      <div class="panel">${l.length ? l.map(invRow).join("") : `<p>${t("empty")}</p>`}</div>`;
  },
  async record() {
    const [inv, pays] = await Promise.all([api("/invoices?status=open"), api("/payments")]);
    setTimeout(() => onSubmit("fxp", () => api("/payments", "POST", {invoice_id: val("fxp_i"), amount_mvr: val("fxp_a"), method: val("fxp_m"), paid_on: val("fxp_d") || undefined, reference: val("fxp_r"), note: val("fxp_n")})));
    return `<div class="panel"><h2>${t("fx_tab_record")}</h2>${inv.length ? `<form id="fxp" class="row">${field("fxp_i", t("fx_invoice"), "", inv.map(i => [i.id, `${i.number} · ${i.student_name} · MVR ${i.balance}`]))}
      <label>${t("fx_amount_received")}<input id="fxp_a" type="number" min="1" step="1" inputmode="numeric" required></label>${field("fxp_m", t("fx_method"), "", ["cash", "bank_transfer", "other"].map(m => [m, t("fx_m_" + m)]))}
      <label>${t("date")}<input id="fxp_d" type="date" max="${mvToday()}" value="${mvToday()}"></label><label>${t("fx_reference")}<input id="fxp_r"></label><label>${t("fx_note")}<input id="fxp_n"></label><button class="btn alt">${t("fx_record")}</button></form>` : `<p>${t("fx_nothing_open")}</p>`}</div>
      <div class="panel"><h2>${t("fx_payments")}</h2>${pays.slice(0, 30).map(p => `<div class="cl ${p.reversed_at ? "off" : ""}"><div><b>${esc(p.student_name)}</b> · ${mvr(p.amount_mvr)} · ${t("fx_m_" + p.method)}<br><span class="hint">${ltr(p.receipt_no)} · ${ltr(p.invoice_number)} · ${ltr(p.paid_on)}${p.reversed_at ? " · " + esc(p.reverse_reason || "") : ""}</span></div>
      <div class="seg">${p.reversed_at ? tag(t("fx_reversed"), "bad") : `<button class="btn sm" data-do="fxRcpt" data-id="${p.id}" data-no="${esc(p.receipt_no)}">${t("fx_receipt")}</button><button class="btn sm" data-do="fxRev" data-id="${p.id}">${t("fx_reverse")}</button>`}</div></div>`).join("") || `<p>${t("empty")}</p>`}</div>`;
  },
  async discounts() {
    const [ds, fams, en, st] = await Promise.all([api("/discounts"), api("/families"), api("/enrollments"), api("/users?role=student")]);
    const kinds = [["fixed", "MVR"], ["percent", "%"]];
    setTimeout(() => {
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
    return `<div class="panel"><h2>${t("fx_tab_overdue")}</h2>${r.email_enabled ? "" : `<p class="hint">${t("fx_email_off")}</p>`}${l.length ? l.map(i => `<div class="sub"><b>${esc(i.student_name)}</b> · ${ltr(i.number)} · ${mvr(i.balance)}<br><span class="hint">${t("fx_overdue_by")} ${ltr(i.days_overdue)} · ${t("fx_due_on")} ${ltr(i.due_date)}</span>
      ${i.last_reminder ? `<div class="msg ${i.reminded_today ? "err" : "ok"}">${t("fx_last_reminder")}: ${esc(i.last_reminder.channel)} · ${ltr(i.last_reminder.sent_at.slice(0, 10))} · ${esc(i.last_reminder.by_name || "")}${i.reminded_today ? " · " + t("fx_reminded_today") : ""}</div>` : ""}
      <div class="seg">${Object.entries(i.links).map(([who, k]) => btn(i, who, "whatsapp", k.whatsapp) + btn(i, who, "viber", k.viber)).join("") || `<span class="hint">${t("fx_no_phone")}</span>`}${r.email_enabled ? `<button class="btn sm" data-do="fxEmail" data-id="${i.id}">${t("fx_email")}</button>` : ""}</div></div>`).join("") : `<p>${t("fx_no_overdue")}</p>`}</div>`;
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
    setTimeout(() => { const fm = $("#fxpr"); if (fm) fm.onsubmit = e => { e.preventDefault(); S.fxf = {...(S.fxf || {}), prm: val("fxp_m") || fxMonth(), prc: val("fxp_c"), prb: val("fxp_b"), prk: val("fxp_k"), prs: val("fxp_s")}; render(); }; });
    return `<div class="panel"><form id="fxpr" class="row" style="display:flex;flex-wrap:wrap;gap:.6rem;align-items:end"><label>${t("fx_month")}<input id="fxp_m" type="month" value="${esc(r.month)}"></label>
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
    setTimeout(() => { const f = $("#fxr"); if (f) f.onsubmit = e => { e.preventDefault(); fxSet("rep", val("fxr_m") || fxMonth()); render(); }; });
    return `<div class="panel"><form id="fxr" class="row"><label>${t("fx_month")}<input id="fxr_m" type="month" value="${esc(m)}"></label><button class="btn">${t("fx_show")}</button><button type="button" class="btn alt" data-do="fxCsv">${t("fx_csv")}</button></form></div>
      <div class="stats">${[[t("fx_invoiced"), T_.invoiced], [t("fx_collected"), T_.collected], [t("fx_outstanding"), T_.outstanding]].map(([k, v]) => `<div class="stat"><b>${mvr(v)}</b>${k}</div>`).join("")}<div class="stat"><b>${T_.overdue_count}</b>${t("fx_st_overdue")}</div></div>
      <div class="panel"><h2>${t("fx_by_course")}</h2>${r.by_course.map(c => `<div class="cl"><span>${esc(c.course_name)}</span><span>${mvr(c.collected)} / ${mvr(c.invoiced)}</span></div>`).join("") || `<p>${t("empty")}</p>`}</div>
      <div class="panel"><h2>${t("fx_who_owes")}</h2>${r.owing.map(o => `<div class="cl"><div><b>${esc(o.student_name)}</b> ${o.overdue ? tag(t("fx_st_overdue"), "bad") : ""}<br><span class="hint">${ltr(o.number)} · ${esc(o.course_name)} ${esc(o.batch_code)}</span></div>${mvr(o.balance)}</div>`).join("") || `<p>${t("fx_nobody_owes")}</p>`}</div>`;
  },
};
const FX_TABS = ["slips", "invoices", "record", "discounts", "overdue", "report", "payrep"];

async function fxAdmin() {
  if (!S.fxCaughtUp) { S.fxCaughtUp = true; try { await api("/invoices/catch-up", "POST"); } catch (x) { /* not allowed or offline: the Fees screen still opens */ } }   // bills anyone enrolled since the last run
  const tab = S.fxt || "slips";
  const inner = await FX[tab]();
  return `<h1>${t("fees")}</h1><div class="subtabs" role="tablist">${FX_TABS.map(k => `<button data-do="fxTab" data-v="${k}" ${k === tab ? 'aria-current="true"' : ""}>${t("fx_tab_" + k)}</button>`).join("")}</div>${inner}`;
}

views.fees = async () => S.user.role === "admin" ? fxAdmin() : fxStudent();
