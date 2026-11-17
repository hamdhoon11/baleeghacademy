/* v0.8.60: Interest list (admins with Admissions). Note people who want to join a batch: name, ID card number, contact.
   Shown batch by batch; filter by batch, status and search; download what is shown as a PDF; quick "New upcoming batch". A reference only:
   nothing here makes an account, an enrolment or an invoice. Loaded after index.html and learning.js. */
const WL = {batch: "", status: "active", q: ""};
const WL_ST = ["waiting", "contacted", "joined", "not_joining"];
const wlQuery = () => [WL.batch ? "batch_id=" + WL.batch : "", WL.status ? "status=" + WL.status : "", WL.q ? "q=" + encodeURIComponent(WL.q) : ""].filter(Boolean).join("&");
const wlBName = b => `${b.course_name} · ${b.code}`;
const wlWhen = b => [(b.days || "").replace(/,/g, ", "), b.start_time ? b.start_time + (b.end_time ? "–" + b.end_time : "") : "", b.start_date ? t("wl_starts") + " " + b.start_date : ""].filter(Boolean).join(" · ");

views.interest = async () => {
  const j = await api("/interest" + (wlQuery() ? "?" + wlQuery() : "")), bs = j.batches, open = bs.filter(b => b.status !== "closed");
  WL.data = j;
  const canBatch = S.user.tabs.includes("batches");
  mount(() => {
    const sel = (id, k) => { const e = $("#" + id); if (e) { e.value = WL[k]; e.onchange = () => { WL[k] = e.value; render(); }; } };
    sel("wl_fb", "batch"); sel("wl_fs", "status");
    const sf = $("#wl_sf"); if (sf) sf.onsubmit = e => { e.preventDefault(); WL.q = val("wl_q"); render(); };
    const ab = $("#wl_b"); if (ab && WL.batch && open.some(b => String(b.id) === WL.batch)) ab.value = WL.batch;
    onSubmit("wl_f", async () => {
      await api("/interest", "POST", {batch_id: +val("wl_b") || null, full_name: val("wl_n"), id_card: val("wl_id"), phone: val("wl_p"), email: val("wl_e"), notes: val("wl_no")});
      return t("wl_added");
    });
  });
  const stOpts = [["active", t("wl_still")], ["", t("wl_everyone")], ...WL_ST.map(s => [s, t("wl_" + s)])];
  const filters = `<div class="panel"><div class="listbar">
      ${field("wl_fb", "batch", "", [["", t("wl_all_batches")], ...bs.map(b => [String(b.id), `${wlBName(b)} (${b.waiting})`])])}
      ${field("wl_fs", "status", "", stOpts)}
      <form id="wl_sf" class="rowflex"><label>${t("search")}<input id="wl_q" value="${esc(WL.q)}" placeholder="${esc(t("wl_search_ph"))}"></label><button class="btn alt">${t("search")}</button></form></div>
    <div class="rowflex"><button type="button" class="btn" data-do="wlPdf">${t("wl_pdf")}</button>${canBatch ? `<button type="button" class="btn alt" data-do="wlNewBatch">${t("wl_new_batch")}</button>` : ""}</div></div>`;
  const add = open.length ? `<details class="panel"${j.entries.length ? "" : " open"}><summary><h2 class="m0">${t("wl_add")}</h2></summary>
      <form id="wl_f" class="row">${field("wl_b", "batch", "", open.map(b => [String(b.id), wlBName(b) + (b.status === "open" ? " · " + t("wl_not_started") : "")]))}
      <label>${t("full_name")}<input id="wl_n" required maxlength="120" autocomplete="off"></label>
      <label>${t("wl_id_card")}<input id="wl_id" required maxlength="20" autocomplete="off" placeholder="A123456" dir="ltr"></label>
      <label>${t("wl_contact")}<input id="wl_p" type="tel" required maxlength="30" placeholder="7771234" dir="ltr"></label>
      <label>${t("email")} (${t("optional")})<input id="wl_e" type="email" maxlength="120" dir="ltr"></label>
      <label class="full">${t("notes")} (${t("optional")})<textarea id="wl_no" rows="2" maxlength="1000"></textarea></label>
      <button class="btn">${t("wl_add_btn")}</button></form></details>`
    : `<div class="panel"><p>${t("wl_no_batches")}</p></div>`;
  const by = {}; j.entries.forEach(e => (by[e.batch_id] = by[e.batch_id] || []).push(e));
  const shown = bs.filter(b => by[b.id] || String(b.id) === WL.batch);
  const row = (e, i) => `<tr><td>${i + 1}</td><td><b>${esc(e.full_name)}</b></td>
    <td><bdi dir="ltr">${esc(e.id_card)}</bdi></td><td><a href="tel:${esc(e.phone.replace(/[^\d+]/g, ""))}" dir="ltr">${esc(e.phone)}</a>${e.email ? `<br><a href="mailto:${esc(e.email)}">${esc(e.email)}</a>` : ""}</td>
    <td><label class="sr-only" for="wls${e.id}">${t("status")}</label><select id="wls${e.id}" data-wlst="${e.id}">${WL_ST.map(s => `<option value="${s}"${s === e.status ? " selected" : ""}>${esc(t("wl_" + s))}</option>`).join("")}</select></td>
    <td><bdi class="nowrap" dir="ltr">${esc((e.created_at || "").slice(0, 10))}</bdi></td><td dir="auto">${esc(e.notes || "")}</td>
    <td><div class="rowflex"><button type="button" class="btn sm alt" data-do="wlEdit" data-id="${e.id}">${t("edit")}</button><button type="button" class="btn sm danger" data-do="wlDel" data-id="${e.id}" data-name="${esc(e.full_name)}">${t("delete")}</button></div></td></tr>`;
  const head = ["#", t("full_name"), t("wl_id_card"), t("wl_contact"), t("status"), t("wl_added_on"), t("notes"), ""];
  const groups = shown.map(b => `<div class="panel"><h2 class="m0">${esc(wlBName(b))} ${b.status === "open" ? tag(t("wl_not_started"), "ok") : b.status === "closed" ? tag(t("closed")) : ""}</h2>
    <p class="hint">${esc(wlWhen(b))}${b.teacher_name ? " · " + esc(b.teacher_name) : ""} · ${t("wl_seats").replace("{n}", b.enrolled).replace("{c}", b.capacity)} · ${t("wl_on_list").replace("{n}", (by[b.id] || []).length)}</p>
    ${by[b.id] ? `<table><caption class="sr-only">${esc(wlBName(b))}</caption><thead><tr>${head.map(h => `<th scope="col">${h ? esc(h) : `<span class="sr-only">${t("actions")}</span>`}</th>`).join("")}</tr></thead><tbody>${by[b.id].map(row).join("")}</tbody></table>` : `<p>${t("wl_nobody")}</p>`}</div>`).join("");
  mount(() => document.querySelectorAll("[data-wlst]").forEach(s => s.onchange = async () => {
    s.disabled = true;
    try { await api(`/interest/${s.dataset.wlst}`, "PATCH", {status: s.value}); flash(t("saved"), true); render(); }
    catch (x) { s.disabled = false; flash(x.message); }
  }));
  return `<h1>${t("interest")}</h1><p class="hint">${t("wl_intro")}</p>${filters}${add}${groups || `<div class="panel"><p>${t(WL.q || WL.batch || (WL.status && WL.status !== "active") ? "wl_none_match" : "wl_empty")}</p></div>`}`;
};
DO.wlPdf = async () => { const b = WL.data && WL.data.batches.find(x => String(x.id) === WL.batch); await fetchFile("/interest/report.pdf" + (wlQuery() ? "?" + wlQuery() : ""), {name: `interest-list${b ? "-" + b.code : ""}.pdf`}); return false; };
DO.wlEdit = async d => {
  const e = WL.data.entries.find(x => x.id === +d.id); if (!e) return false;
  const bs = WL.data.batches.filter(b => b.status !== "closed" || b.id === e.batch_id);
  const v = await ui.form(t("edit"), [
    {id: "batch_id", label: t("batch"), type: "select", options: bs.map(b => [String(b.id), wlBName(b)]), value: String(e.batch_id)},
    {id: "full_name", label: t("full_name"), required: true, value: e.full_name, maxlength: 120},
    {id: "id_card", label: t("wl_id_card"), required: true, value: e.id_card, maxlength: 20},
    {id: "phone", label: t("wl_contact"), type: "tel", required: true, value: e.phone, maxlength: 30},
    {id: "email", label: t("email"), type: "email", value: e.email || "", maxlength: 120},
    {id: "notes", label: t("notes"), type: "textarea", rows: 2, value: e.notes || ""}], {okText: t("save")});
  if (!v) return false;
  await api(`/interest/${d.id}`, "PATCH", {...v, batch_id: +v.batch_id}); flash(t("saved"), true);
};
DO.wlDel = async d => { if (!await ui.confirm(t("wl_del_q"), {danger: true, okText: t("delete"), details: [d.name || ""]})) return false; await api(`/interest/${d.id}`, "DELETE"); };
DO.wlNewBatch = async () => {
  const cs = await api("/courses?active=1");
  const v = await ui.form(t("wl_new_batch"), [
    {id: "course_id", label: t("course"), type: "select", options: cs.map(c => [String(c.id), c.name]), required: true},
    {id: "code", label: t("wl_batch_code"), required: true, maxlength: 30},
    {id: "days", label: t("wl_days"), placeholder: "Mon,Wed"},
    {id: "start_time", label: t("time"), type: "time"}, {id: "end_time", label: t("end_time"), type: "time"},
    {id: "start_date", label: t("start_date"), type: "date"}, {id: "capacity", label: t("capacity"), type: "number", value: "20", required: true}],
    {okText: t("add"), hint: t("wl_new_batch_hint")});
  if (!v) return false;
  const r = await api("/batches", "POST", {...v, course_id: +v.course_id, capacity: +v.capacity, status: "open",
    days: (v.days || "").split(/[\s,]+/).filter(Boolean).map(x => x.slice(0, 1).toUpperCase() + x.slice(1, 3).toLowerCase()).join(",") || null,
    start_time: v.start_time || null, end_time: v.end_time || null, start_date: v.start_date || null});
  WL.batch = String(r.id); flash(t("saved"), true);
};
