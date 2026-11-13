/* Admin control screens: edit/correct/delete for courses, batches, people (with admin permissions), enrollments, applications,
   the grouped Settings screen, student and teacher information, activity log, finance and the dashboard.
   Loaded last; reuses helpers from index.html, ui.js and learning.js (api, S, t, esc, $, val, field, flash, render, onSubmit, mount, go, navBack, closeDetail, crumb, tabs, ui, DO, tag).
   Each view is defined ONCE here (Sessions 5, 6, 8): no wrappers, no regex HTML injection, DOM wiring through mount(). */
const AREA_LABELS = {admissions: "Admissions", courses: "Courses", batches: "Batches", classroom: "Classroom (attendance, grades)", people: "People", enrollments: "Enrollments", fees: "Fees", settings: "Settings", audit: "Audit log", tutorials: "Tutorials", assignments: "Assignments", progress: "Progress (grades, attendance)", materials: "Materials", create_tutorials: "Create tutorials and see answers", submit_tutorial_work: "Submit tutorial work", class_links: "Class links (Meet links)", recordings: "Recordings (view)", add_recordings: "Add class recordings", student_information: "Student information", teacher_information: "Teacher information", finance: "Finance (expenses)", edit_grades: "Change saved grades", cancel_class: "Cancel classes"};
// which areas exist for each role (the server holds the same list and checks every request against it)
const ROLE_AREAS = {admin: ["admissions", "courses", "batches", "classroom", "people", "enrollments", "fees", "settings", "audit", "tutorials", "create_tutorials", "class_links", "add_recordings", "student_information", "teacher_information", "finance"], teacher: ["classroom", "tutorials", "create_tutorials", "class_links", "add_recordings", "edit_grades", "cancel_class"], student: ["assignments", "progress", "materials", "recordings", "fees", "tutorials", "submit_tutorial_work"]};
const iv = (id, label, v, type = "text", extra = "") => `<label>${esc(t(label))}<input id="${id}" type="${type}" value="${esc(v ?? "")}" ${extra}></label>`;
const sel = (id, label, opts, cur) => `<label>${esc(t(label))}<select id="${id}">${opts.map(o => `<option value="${esc(o[0])}" ${String(o[0]) === String(cur ?? "") ? "selected" : ""}>${esc(o[1])}</option>`).join("")}</select></label>`;
const nv = id => { const v = val(id); return v === "" ? null : v; };
const bar = (...btns) => `<div style="flex:1 1 100%;display:flex;gap:.6rem;flex-wrap:wrap">${btns.join("")}</div>`;
const moreBtn = (n, shown, total, doName) => shown < total ? `<p><button type="button" class="btn" data-do="${doName}">${t("load_more")}</button> <span class="hint">${shown} / ${total}</span></p>` : (total ? `<p class="hint">${total} / ${total}</p>` : "");
// an admin limited to a picker area gets names only from /users, without is_active: treat them as active (the server still refuses inactive accounts)
const isActive = u => u.is_active !== 0 && u.is_active !== false;
const personLabel = s => s.full_name + (s.login_id ? " (" + s.login_id + ")" : "");

// ---- Session 11: a searchable picker = a filter box above a select. Typing narrows the options; the select is what is sent. ----
const PICK = {};
const pickOpts = (opts, cur) => opts.map(o => `<option value="${esc(o[0])}" ${String(o[0]) === String(cur ?? "") ? "selected" : ""}>${esc(o[1])}</option>`).join("");
function pickField(id, label, opts, cur) {
  PICK[id] = opts;
  return `<div class="pick"><label>${esc(t("find_label").replace("{f}", t(label)))}<input type="search" data-pick="${id}" autocomplete="off" placeholder="${esc(t("Type to filter"))}"></label><label>${esc(t(label))}<select id="${id}">${pickOpts(opts, cur)}</select></label></div>`;
}
document.addEventListener("input", e => {
  const id = e.target.dataset && e.target.dataset.pick; if (!id) return;
  const s = $("#" + id), q = e.target.value.trim().toLowerCase(), cur = s.value;
  const list = (PICK[id] || []).filter(o => !q || String(o[1]).toLowerCase().includes(q) || o[0] === "");
  s.innerHTML = list.length ? pickOpts(list, cur) : `<option value="">${esc(t("no_match"))}</option>`;
});

// ---------- courses: edit everything, delete mistakes (Session 10: collapsed Add panel, whole-number money) ----------
views.courses = async () => {
  const c = await api("/courses");
  const e = c.find(x => x.id === S.ec);
  const statuses = [["open", t("open")], ["upcoming", t("upcoming")], ["closed", t("closed")]];
  const kinds = [["course", t("Course")], ["tuition", t("Tuition class")]];
  mount(() => {
    fcWarn("cf"); if (e) fcWarn("ce_f");
    onSubmit("fc", () => api("/courses", "POST", {name: val("cn"), level: val("cl"), kind: val("ck"), code: val("cc") || undefined, monthly_fee_mvr: wholeNum("cf", "fee"), registration_fee_mvr: wholeNum("cg", "Registration fee (one time)") || 0, textbook: val("ct"), status: val("cs")}));
    if (e) onSubmit("fce", async () => { await api("/courses/" + e.id, "PATCH", {name: val("ce_n"), level: nv("ce_l"), textbook: nv("ce_t"), description: nv("ce_d"), monthly_fee_mvr: wholeNum("ce_f", "fee") || 0, registration_fee_mvr: wholeNum("ce_g", "Registration fee (one time)") || 0, days_per_week: nv("ce_w"), minutes_per_class: nv("ce_m"), status: val("ce_s"), kind: val("ce_k"), code: val("ce_c") || undefined, is_active: $("#ce_a").checked}); closeDetail({ec: null}); });
  });
  const editor = e ? `<div class="panel" data-detail><h2>${esc(t("edit"))}: ${esc(e.name)}</h2><form class="row" id="fce">${iv("ce_n", "name", e.name)}${iv("ce_l", "level", e.level)}${iv("ce_t", "textbook", e.textbook)}${iv("ce_f", "fee", e.monthly_fee_mvr, "number", moneyAttrs)}${iv("ce_g", "Registration fee (one time)", e.registration_fee_mvr || 0, "number", moneyAttrs)}${iv("ce_w", "Days per week", e.days_per_week, "number", 'min="1" max="7"')}${iv("ce_m", "Minutes per class", e.minutes_per_class, "number", 'min="1"')}${sel("ce_s", "status", statuses, e.status)}${sel("ce_k", "Type", kinds, e.kind)}${iv("ce_c", "Code", e.code)}<label class="inl"><input type="checkbox" id="ce_a" ${e.is_active ? "checked" : ""}> ${esc(t("Active (offered for new enrolments and invoices)"))}</label><label class="full">${esc(t("Description"))}<textarea id="ce_d" rows="3">${esc(e.description || "")}</textarea></label>${bar(`<button class="btn alt">${t("save")}</button>`, `<button type="button" class="btn" data-do="ecClose">${t("cancel")}</button>`, `<button type="button" class="btn danger" data-do="ecDel" data-id="${e.id}">${t("delete")}</button>`)}</form><p class="hint">${esc(t("Courses that already have batches cannot be deleted. Set the status to closed instead; the old records stay safe."))}</p></div>` : "";
  const add = addPanel("course", "Add course", form("fc", field("cn", "name") + field("cl", "level") + field("ck", "Type", "", kinds) + field("cc", "Code (optional, made from the name)") + iv("cf", "fee", "", "number", moneyAttrs) + iv("cg", "Registration fee (one time)", "", "number", moneyAttrs) + field("ct", "textbook") + field("cs", "status", "", statuses)));
  return `${e ? crumbFor(e.name, {ec: null}) : ""}<h1>${t("courses")}</h1>${editor}${add}<div class="panel"><p>${xlBtns("/courses/export", "", "courses")}</p>${c.length ? `<table><thead><tr><th>${t("name")}</th><th>${t("Type")}</th><th>${t("Code")}</th><th>${t("level")}</th><th>${t("fee")}</th><th>${t("status")}</th><th></th></tr></thead><tbody>${c.map(x => `<tr><td>${esc(x.name)}</td><td>${esc(x.kind === "tuition" ? t("Tuition class") : t("Course"))}</td><td>${esc(x.code || "")}</td><td>${esc(x.level || "")}</td><td>${esc(x.monthly_fee_mvr)}</td><td>${esc(t(x.status))} ${x.is_active ? "" : tag(t("Inactive"), "warn")}</td><td><button class="btn sm" data-do="ecEdit" data-id="${x.id}">${t("edit")}</button></td></tr>`).join("")}</tbody></table>` : `<p>${t("empty")}</p>`}</div>` + impBox("courses", t("xl_imp_courses"));
};
// Session 9: a fee of 0 means students in the course get no invoices; say so while the admin types
function fcWarn(id) {
  const el = $("#" + id); if (!el || el.dataset.warn) return; el.dataset.warn = "1";
  const w = document.createElement("div"); w.className = "msg err"; w.style.flex = "1 1 100%"; w.textContent = t("fee_zero_warn");
  el.closest("label").after(w);
  // v0.8.35: an empty new form does not warn yet; it warns once the fee was touched, or when a saved course really has 0
  let touched = el.value !== "";
  const upd = () => { w.hidden = !(touched && (el.value === "" || +el.value <= 0)); };
  el.addEventListener("input", () => { touched = true; upd(); }); el.addEventListener("blur", () => { touched = true; upd(); }); upd();
}
DO.ecEdit = d => { go({ec: +d.id}); return false; };
DO.ecClose = () => { closeDetail({ec: null}); };
DO.ecDel = async (d, b) => {
  const f = b.closest("form"), name = f ? $("#ce_n").value : "";
  if (!await ui.confirm(t("Delete this course? This cannot be undone."), {danger: true, details: [name + (f && val("ce_l") ? " · " + val("ce_l") : ""), t("Code") + ": " + (f ? val("ce_c") || "-" : "-"), t("Courses that already have batches cannot be deleted. Set the status to closed instead; the old records stay safe.")]})) return false;
  await api("/courses/" + d.id, "DELETE"); closeDetail({ec: null}); flash(t("saved"), true);
};

// ---------- batches (Session 6): ONE view. Editor, students panel and substitutes panel are plain template pieces. ----------
const DAYS_IN = (sel, name) => `<fieldset class="days"><legend>${t("days")}</legend>${DAYS7.map(d => `<label><input type="checkbox" name="${name}" value="${d}" ${(sel || "").split(",").includes(d) ? "checked" : ""}><span>${dayName(d)}</span></label>`).join("")}</fieldset>`;
const pickedDays = name => [...document.querySelectorAll(`input[name="${name}"]:checked`)].map(i => i.value).join(",");
const batchEditor = (e, courses, teachers) => `<div class="panel" data-detail><h2>${esc(e.course_name)} · ${esc(e.code)}</h2>`
  + `<div class="rowflex mb1 row">${iv("be_n", "Batch name / code", e.code)}${sel("be_c2", "course", courses.filter(x => x.is_active || x.id === e.course_id).map(x => [x.id, x.name + " " + (x.level || "")]), e.course_id)}<button class="btn danger" data-do="delB" data-id="${e.id}">${t("delete")}</button></div>`
  + DAYS_IN(e.days, "bde")
  + `<div class="rowflex row"><label>${t("time")}<input type="time" id="be_t" value="${esc(e.start_time || "")}"></label><label>${t("start_date")}<input type="date" id="be_sd" value="${esc(e.start_date || "")}"></label><label>${t("capacity")}<input type="number" id="be_c" value="${e.capacity}" min="1" step="1" inputmode="numeric"></label>${sel("be_h", "teacher", teachers, e.teacher_id || "")}${sel("be_s", "status", [["open", t("open")], ["running", t("running")], ["closed", t("closed")]], e.status)}<p class="full hint">${esc(t("The class link is set in Classroom, not here."))}</p><button class="btn" data-do="saveB">${t("save")}</button><button class="btn alt" data-do="closeB">${t("cancel")}</button></div></div>`;
const batchStudents = (e, studs, allSt) => { const inBatch = new Set(studs.map(s => s.id));
  return `<div class="panel"><h2>${esc(t("Students in this batch"))} (${studs.filter(s => s.status === "active").length}/${e.capacity})</h2>`
    + `<div class="rowflex row">${pickField("bs_add", "student", [["", "-"], ...allSt.filter(s => isActive(s) && !inBatch.has(s.id)).map(s => [s.id, personLabel(s)])], "")}<button class="btn alt" data-do="bEnrol" data-id="${e.id}">${esc(t("enroll"))}</button></div>`
    + (studs.length ? `<table><thead><tr><th>${t("name")}</th><th>${t("status")}</th><th></th></tr></thead><tbody>${studs.map(s => `<tr><td>${esc(s.full_name)}</td><td>${esc(t(s.status))}</td><td><button class="btn sm" data-do="bUnenrol" data-id="${s.enrollment_id}" data-name="${esc(s.full_name)}">${esc(t("Remove from batch"))}</button></td></tr>`).join("")}</tbody></table>` : `<p>${t("empty")}</p>`) + `</div>`; };
const batchSubs = (subs, teachers) => {
  const rows = subs.map(r => `<tr><td>${esc(r.substitute_teacher)}</td><td>${esc(r.class_date)}${r.last_day !== r.class_date ? " → " + esc(r.last_day) : ""}</td><td>${esc(r.reason || "")}</td><td>${esc(t(r.state))}</td><td>${r.state === "active" || r.state === "upcoming" ? `<button class="btn sm" data-do="subRemove" data-id="${r.id}" data-name="${esc(r.substitute_teacher)}">${t("Remove")}</button>` : ""}</td></tr>`).join("");
  return `<div class="panel"><h2>${t("Substitute teachers")}</h2><p class="hint">${t("A substitute can see this batch's class students, join link and attendance only on the dates you choose. The batch keeps its own teacher.")}</p>`
    + form("fsub", field("sb_t", "Substitute teacher", "text", [["", "-"], ...teachers.filter(isActive).map(x => [x.id, x.full_name])]) + field("sb_from", "From", "date") + field("sb_to", "To (empty = one day)", "date") + field("sb_r", "Reason"), "Add")
    + (subs.length ? `<table><thead><tr><th>${t("Substitute teacher")}</th><th>${t("date")}</th><th>${t("Reason")}</th><th>${t("status")}</th><th></th></tr></thead><tbody>${rows}</tbody></table>` : "") + "</div>"; };
views.batches = async () => {
  const [b, c, tc] = await Promise.all([api("/batches"), api("/courses"), api("/users?role=teacher")]);
  const e = b.find(x => x.id === S.eb);
  const [studs, allSt, subs] = e ? await Promise.all([api(`/batches/${e.id}/students`), api("/users?role=student"), api("/substitutions?batch_id=" + e.id)]) : [[], [], []];
  S.ebInfo = e ? {name: `${e.course_name} · ${e.code}`, active: studs.filter(s => s.status === "active").length, all: studs.length} : null;
  mount(() => {
    onSubmit("fb", () => api("/batches", "POST", {course_id: val("bc"), code: val("bn"), days: pickedDays("bd"), start_time: val("bt"), start_date: val("bsd") || null, capacity: val("bp"), teacher_id: val("bh") || null}));
    if (e) onSubmit("fsub", () => api("/substitutions", "POST", {batch_id: e.id, substitute_teacher_id: val("sb_t"), class_date: val("sb_from"), ends_on: val("sb_to") || null, reason: val("sb_r")}));
  });
  const teachers = [["", "-"], ...tc.map(x => [x.id, x.full_name])];
  const detail = e ? batchEditor(e, c, teachers) + batchStudents(e, studs, allSt) + batchSubs(subs, tc) : "";
  return `${e ? crumbFor(`${e.course_name} · ${e.code}`, {eb: null}) : ""}<h1>${t("batches")}</h1>${detail}<div class="panel"><p>${xlBtns("/batches/export", "", "batches")}</p>${form("fb", field("bc", "course", "", c.filter(x => x.is_active).map(x => [x.id, x.name + " " + (x.level || "")])) + field("bn", "code") + field("bt", "time", "time") + field("bsd", "start_date", "date") + field("bp", "capacity", "number") + field("bh", "teacher", "", teachers) + DAYS_IN("", "bd"))}</div><div class="panel"><table><thead><tr><th>${t("course")}</th><th>${t("code")}</th><th>${t("days")}</th><th>${t("time")}</th><th>${t("seats")}</th><th>${t("teacher")}</th><th>${t("status")}</th><th></th></tr></thead><tbody>${b.map(x => `<tr><td>${esc(x.course_name)}</td><td>${esc(x.code)}</td><td>${x.days ? esc(x.days.split(",").map(dayName).join(", ")) : tag("–", "warn")}</td><td>${esc(x.start_time || "–")}</td><td>${x.enrolled}/${x.capacity}</td><td>${esc(x.teacher_name || "–")}</td><td>${esc(t(x.status))}</td><td><button class="btn sm" data-do="editB" data-id="${x.id}">${t("edit")}</button></td></tr>`).join("")}</tbody></table></div>` + impBox("batches", t("xl_imp_batches"));
};
DO.editB = d => { go({eb: +d.id}); return false; };
DO.closeB = () => { closeDetail({eb: null}); };
DO.saveB = async () => {
  await api("/batches/" + S.eb, "PATCH", {code: val("be_n"), course_id: val("be_c2"), days: pickedDays("bde"), start_time: val("be_t") || null, start_date: val("be_sd") || null, capacity: val("be_c"), teacher_id: val("be_h") || null, status: val("be_s")});
  closeDetail({eb: null}); flash(t("saved"), true);
};
DO.delB = async d => {
  const i = S.ebInfo || {};
  if (!await ui.confirm(t("Delete this batch? This cannot be undone."), {danger: true, details: [i.name || "", t("del_batch_students").replace("{n}", i.active ?? 0).replace("{m}", i.all ?? 0), t("del_batch_hint")]})) return false;
  await api("/batches/" + d.id, "DELETE"); closeDetail({eb: null}); flash(t("saved"), true);
};
DO.bEnrol = async d => {   // enrol through the normal enrolment route (capacity, waitlist, inactive course and first invoice are decided there)
  if (!val("bs_add")) throw new Error(t("Choose a student"));
  const r = await api("/enrollments", "POST", {student_id: val("bs_add"), batch_id: d.id});
  flash(r.invoice_message ? t("saved") + ": " + r.invoice_message : t("saved"), true);
};
DO.bUnenrol = async d => {
  const reason = await ui.ask(t("Remove from batch") + ": " + (d.name || ""), {label: t("Reason (optional)"), hint: t("Remove this student from the batch? Their records stay."), okText: t("Remove from batch"), danger: true});
  if (reason === null) return false;
  await api("/enrollments/" + d.id, "PATCH", {status: "dropped", reason}); flash(t("saved"), true);
};
DO.subRemove = async d => { if (!await ui.confirm(t("End this substitution now? The teacher loses access at once."), {danger: true, okText: t("Remove"), details: [d.name || ""]})) return false; await api("/substitutions/" + d.id, "DELETE"); };

// ---------- people: edit anything, permissions for admins, delete mistakes. Session 11: search and paging; the create form is a collapsed panel ----------
DO.peBulkOff = async () => { if (!await ui.confirm(t("bulk_deactivate_q").replace("{n}", bulkSel("ppl").length), {danger: true, okText: t("bulk_deactivate")})) return false; await bulkRun("ppl", id => api("/users/" + id, "PATCH", {is_active: false})); };
DO.peBulkOn = async () => { await bulkRun("ppl", id => api("/users/" + id, "PATCH", {is_active: true})); };
views.people = async () => {
  const roleF = S.pf || "";
  const u = await api("/users" + (roleF ? "?role=" + roleF : ""));
  const [e, help] = await Promise.all([S.eu ? api("/users/" + S.eu).catch(() => null) : null, api("/password-help").catch(() => [])]);
  const self = S.user.id, full = !S.user.permissions;
  mount(() => {
    onSubmit("fu", async () => {   // no password typed = the server makes a random one; it is shown once below
      const name = val("un"), r = await api("/users", "POST", {full_name: name, email: val("ue"), password: val("up") || undefined, role: val("ur")});
      if (r.temporary_password) S.tmp = {name, id: r.login_id, pw: r.temporary_password};
    });
    if ($("#pf")) $("#pf").onchange = ev => { S.pf = ev.target.value; S.plim = 30; render(); };
    const pq = $("#pqf"); if (pq) pq.onsubmit = ev => { ev.preventDefault(); S.pq = val("pq"); S.plim = 30; render(); };
    if (e) {
      const toggle = () => { const m = $("#pm_limited"); if ($("#pm_box")) $("#pm_box").hidden = !(m && m.checked); };
      document.querySelectorAll('input[name="pm"]').forEach(r => r.onchange = toggle); toggle();
      onSubmit("fue", async () => {
        const body = {full_name: val("eu_n"), login_id: val("eu_l"), email: val("eu_e"), phone: nv("eu_p"), is_active: $("#eu_a").checked, must_change_password: $("#eu_mc").checked};
        if (val("eu_pw")) body.password = val("eu_pw");
        if (e.id !== self) body.role = val("eu_r");
        if (e.role === "student") for (const k of ["date_of_birth", "grade", "island", "guardian_name", "guardian_relationship", "guardian_phone"]) body[k] = nv("eu_" + k);
        if (e.role === "teacher") body.bio = nv("eu_bio");
        // permissions are sent only when the role is unchanged (changing the role resets them to "everything the new role has")
        if (full && e.id !== self && body.role === e.role) body.permissions = $("#pm_limited").checked ? [...document.querySelectorAll('input[name="pa"]:checked')].map(i => i.value) : "all";
        await api("/users/" + e.id, "PATCH", body); closeDetail({eu: null});
      });
    }
  });
  const roles = [["student", t("student")], ["teacher", t("teacher")], ["admin", t("admin")]];
  const prof = !e ? "" : e.role === "student" ? `${iv("eu_date_of_birth", "date_of_birth", e.date_of_birth, "date")}${iv("eu_grade", "Grade / class", e.grade)}${iv("eu_island", "Island", e.island)}${iv("eu_guardian_name", "guardian_name", e.guardian_name)}${iv("eu_guardian_relationship", "Guardian relationship", e.guardian_relationship)}${iv("eu_guardian_phone", "Guardian phone", e.guardian_phone)}`
    : e.role === "teacher" ? `<label class="full">${esc(t("Bio"))}<textarea id="eu_bio" rows="3">${esc(e.bio || "")}</textarea></label>` : "";
  const permTitle = {admin: "Admin permissions", teacher: "Teacher permissions", student: "Student permissions"};
  const permAll = {admin: "Full admin (everything, including other admins' permissions)", teacher: "Everything a teacher has", student: "Everything a student has"};
  const perms = e && e.id !== self ? (full ? `<fieldset class="full days"><legend>${esc(t(permTitle[e.role]))}</legend><label><input type="radio" name="pm" id="pm_full" ${e.permissions === null ? "checked" : ""}> <span>${esc(t(permAll[e.role]))}</span></label><label><input type="radio" name="pm" id="pm_limited" ${e.permissions !== null ? "checked" : ""}> <span>${esc(t("Limited to the areas ticked below"))}</span></label><div id="pm_box" style="flex:1 1 100%;display:flex;flex-wrap:wrap;gap:.3rem">${ROLE_AREAS[e.role].map(k => `<label><input type="checkbox" name="pa" value="${k}" ${(e.permissions || []).includes(k) ? "checked" : ""}> <span>${esc(t(AREA_LABELS[k]))}</span></label>`).join("")}</div><p class="full m0 hint">${esc(t("Changing the role resets these permissions. Save the new role first, then set permissions."))}</p></fieldset>` : `<p class="hint">${esc(t("Only a full admin can change permissions."))}</p>`)
    : e && e.id === self ? `<p class="hint">${esc(t("You cannot change your own role or permissions. Ask another full admin."))}</p>` : "";
  if (e) S.euInfo = {name: e.full_name, role: e.role, login: e.login_id, enr: e.enrollments, taught: e.batches_taught};
  const editor = e ? `<div class="panel" data-detail><h2>${esc(t("edit"))}: ${esc(e.full_name)} ${tag(t(e.role))}</h2><form class="row" id="fue">${iv("eu_n", "name", e.full_name)}${iv("eu_l", "Login ID", e.login_id, "text", 'autocomplete="off"')}${iv("eu_e", "email", e.email, "email")}${iv("eu_p", "Phone", e.phone, "tel")}${e.id === self ? "" : sel("eu_r", "role", roles, e.role)}${prof}${perms}${iv("eu_pw", "Set a new password (leave empty to keep)", "", "text", 'autocomplete="off"')}<label class="inl"><input type="checkbox" id="eu_mc" ${e.must_change_password ? "checked" : ""}> ${esc(t("Must change password at next sign-in"))}</label><label class="inl"><input type="checkbox" id="eu_a" ${e.is_active ? "checked" : ""} ${e.id === self ? "disabled" : ""}> ${esc(t("Account active"))}</label>${bar(`<button class="btn alt">${t("save")}</button>`, `<button type="button" class="btn" data-do="euClose">${t("cancel")}</button>`, e.id === self ? "" : `<button type="button" class="btn" data-do="euReset" data-id="${e.id}">${esc(t("Reset password"))}</button> <button type="button" class="btn danger" data-do="euDel" data-id="${e.id}">${t("delete")}</button>`)}</form><p class="hint">${esc(t("Enrollments"))}: ${e.enrollments} · ${esc(t("Batches taught"))}: ${e.batches_taught}. ${esc(t("People with enrollments, grades or invoices cannot be deleted or change role. Disable the account instead."))}</p></div>` : "";
  // search (name, login ID, email) and paging on the client: GET /api/users has no search parameter
  const q = (S.pq || "").toLowerCase(), lim = S.plim || 30;
  const found = q ? u.filter(x => [x.full_name, x.login_id, x.email].some(v => String(v || "").toLowerCase().includes(q))) : u;
  const canBulk = x => x.id !== self;
  const rows = found.slice(0, lim).map(x => `<tr><td>${canBulk(x) ? bulkBox("ppl", x.id, x.full_name) + " " : ""}${esc(x.full_name)}</td><td>${esc(x.login_id || "")}</td><td>${esc(x.email)}</td><td>${esc(t(x.role))}${x.permissions !== null ? " " + tag(t("Limited"), "warn") : x.role === "admin" ? " " + tag(t("Full"), "ok") : ""}</td><td>${x.is_active ? "✓" : "✗"}<span class="sr-only">${esc(t(x.is_active ? "active" : "inactive"))}</span></td><td><button class="btn sm" data-do="euEdit" data-id="${x.id}">${t("edit")}</button></td></tr>`).join("");
  const listbar = `<form id="pqf" class="listbar" role="search"><label>${esc(t("role"))}<select id="pf"><option value="">${esc(t("all"))}</option>${roles.map(r => `<option value="${r[0]}" ${r[0] === roleF ? "selected" : ""}>${esc(r[1])}</option>`).join("")}</select></label><label>${esc(t("search"))}<input id="pq" type="search" value="${esc(S.pq || "")}" placeholder="${esc(t("people_search_hint"))}"></label><button class="btn">${t("search")}</button></form>`;
  const add = addPanel("person", "Add person", form("fu", field("un", "name") + field("ue", "email", "email") + field("up", "password", "password") + field("ur", "role", "", roles)));
  return `${e ? crumbFor(e.full_name, {eu: null}) : ""}<h1>${t("people")}</h1>${tmpPanel()}${helpPanel(help)}${editor}${add}<div class="panel">${listbar}${bulkBar("ppl", [["peBulkOn", "bulk_activate"], ["peBulkOff", "bulk_deactivate", true]], found.slice(0, lim).filter(canBulk).map(x => x.id))}${bulkAll("ppl", found.slice(0, lim).filter(canBulk).map(x => x.id))}${found.length ? `<table><thead><tr><th>${t("name")}</th><th>${t("Login ID")}</th><th>${t("email")}</th><th>${t("role")}</th><th>${t("is_active")}</th><th></th></tr></thead><tbody>${rows}</tbody></table>` : `<p>${t(q ? "no_match" : "empty")}</p>`}${moreBtn(0, Math.min(lim, found.length), found.length, "peMore")}</div>${impPanel()}`;
};
DO.peMore = () => { S.plim = (S.plim || 30) + 30; };
DO.euEdit = d => { go({eu: +d.id}); return false; };
DO.euClose = () => { closeDetail({eu: null}); };
DO.tmpClose = () => { S.tmp = null; };
DO.euReset = async d => {
  if (!await ui.confirm(t("Make a new temporary password for this person? Their old password stops working."), {okText: t("Reset password"), details: [(S.euInfo || {}).name || ""]})) return false;
  const r = await api("/users/" + d.id + "/reset-password", "POST");
  S.tmp = {name: r.name || "", id: r.login_id, pw: r.temporary_password, wa: r.whatsapp_link}; closeDetail({eu: null}); flash(t("saved"), true);
};
// v0.8.35: "Forgot password" requests. Reset and send = new temporary password + a WhatsApp message ready to send.
function helpPanel(list) {
  if (!list || !list.length) return "";
  const row = h => `<div class="cl"><div><b>${esc(h.full_name || h.login_text)}</b> ${h.user_id ? tag(t(h.role)) : tag(t("No matching account"), "warn")}<br><span class="hint">${esc(h.login_id || h.login_text)}${h.contact ? " · <bdi dir=\"ltr\">" + esc(h.contact) + "</bdi>" : ""} · <bdi dir="ltr">${esc(fmtTime(h.created_at))}</bdi></span></div>`
    + `<div class="rowflex">${h.user_id ? `<button class="btn sm" data-do="phReset" data-id="${h.user_id}" data-name="${esc(h.full_name)}">${esc(t("Reset and send"))}</button>` : ""}<button class="btn sm alt" data-do="phDismiss" data-id="${h.id}">${esc(t("Dismiss"))}</button></div></div>`;
  return `<div class="panel" role="region" aria-label="${esc(t("Password help"))}"><h2>${esc(t("Password help"))} (${list.length})</h2><p class="hint">${esc(t("password_help_hint"))}</p>${list.map(row).join("")}</div>`;
}
DO.phReset = async d => {
  if (!await ui.confirm(t("Make a new temporary password for this person? Their old password stops working."), {okText: t("Reset and send"), details: [d.name || ""]})) return false;
  const r = await api("/users/" + d.id + "/reset-password", "POST");
  S.tmp = {name: r.name || d.name, id: r.login_id, pw: r.temporary_password, wa: r.whatsapp_link}; flash(t("saved"), true);
};
DO.phDismiss = async d => { if (!await ui.confirm(t("Dismiss this request? Nothing is changed for the person."), {okText: t("Dismiss")})) return false; await api(`/password-help/${d.id}/dismiss`, "POST"); };
// The temporary password is shown once, only here, and only until "Done" is pressed (the server keeps just a hash and cannot show it again).
function tmpPanel() {
  if (!S.tmp) return "";
  return `<div class="panel" role="alert"><h2>${esc(t("Temporary password"))}${S.tmp.name ? ": " + esc(S.tmp.name) : ""}</h2><p>${esc(t("Login ID"))}: <b>${esc(S.tmp.id || "")}</b><br>${esc(t("password"))}: <b>${esc(S.tmp.pw)}</b></p><p class="hint">${esc(t("Copy this now and give it to the person. It will not be shown again. They must choose their own password at first sign-in."))}</p><p class="rowflex">${S.tmp.wa ? `<a class="btn" href="${esc(S.tmp.wa)}" target="_blank" rel="noopener">${esc(t("send_whatsapp"))}</a>` : `<span class="hint">${esc(t("No phone number saved for this person: give the password another way."))}</span>`}<button type="button" class="btn alt" data-do="tmpClose">${esc(t("Done"))}</button></p></div>`;
}
DO.euDel = async d => {
  const i = S.euInfo || {};
  if (!await ui.confirm(t("Delete this account? This cannot be undone."), {danger: true, details: [`${i.name || ""} · ${t(i.role || "")}${i.login ? " · " + i.login : ""}`, `${t("Enrollments")}: ${i.enr ?? 0} · ${t("Batches taught")}: ${i.taught ?? 0}`, t("People with enrollments, grades or invoices cannot be deleted or change role. Disable the account instead.")]})) return false;
  await api("/users/" + d.id, "DELETE"); closeDetail({eu: null}); flash(t("saved"), true);
};

// ---------- enrollments: drop, move, delete a mistake. Session 11: searchable pickers, list search and paging, collapsed Add panel ----------
views.enrollments = async () => {
  const [e, st, b, ev] = await Promise.all([api("/enrollments"), api("/users?role=student"), api("/batches"), api("/enrollment-events")]);
  const m = e.find(x => x.id === S.em);
  const hist = `<div class="panel"><h2>${t("Transfers and withdrawals")}</h2><p><button class="btn sm alt" data-do="evCsv">${t("Download CSV")}</button> <button class="btn sm alt" data-do="evXlsx">${t("Download Excel")}</button></p>${ev.length ? `<table><thead><tr><th>${t("date")}</th><th>${t("kind")}</th><th>${t("student_name")}</th><th>${t("Previous batch")}</th><th>${t("New batch")}</th><th>${t("Reason")}</th></tr></thead><tbody>${ev.map(x => `<tr><td>${esc(x.effective_date || "?")}</td><td>${esc(t(x.kind === "transfer" ? "Transfer" : "Withdrawal"))}</td><td>${esc(x.student_name)} <span class="hint">${esc(x.student_code || "")}</span></td><td>${esc((x.from_course || "") + " " + (x.from_batch_code || ""))}</td><td>${esc((x.to_course || "") + " " + (x.to_batch_code || ""))}</td><td>${esc(x.reason || "")}</td></tr>`).join("")}</tbody></table>` : `<p class="hint">${t("empty")}</p>`}</div>`;
  const bo = b.filter(x => x.course_active).map(x => [x.id, x.course_name + " " + x.code]);   // inactive courses are not offered for new enrolments
  mount(() => {
    onSubmit("fe", () => { if (!val("es")) throw new Error(t("Choose a student")); if (!val("eb")) throw new Error(t("Choose a batch")); return api("/enrollments", "POST", {student_id: val("es"), batch_id: val("eb"), start_date: val("esd") || undefined}).then(r => r.earlier_invoices ? t("saved") + " " + t("earlier_invoices_made").replace("{n}", r.earlier_invoices) : r); });
    const f = $("#enqf"); if (f) f.onsubmit = ev2 => { ev2.preventDefault(); S.enq = val("enq"); S.enlim = 30; render(); };
  });
  if (m) S.emInfo = {name: m.student_name, where: m.course_name + " " + m.batch_code, status: m.status};
  const mover = m ? `<div class="panel" data-detail><h2>${esc(m.student_name)}: ${esc(m.course_name)} ${esc(m.batch_code)}</h2><div class="rowflex row">${sel("em_b", "Move to batch", bo.filter(x => x[0] !== m.batch_id), "")}<button class="btn" data-do="emMove" data-id="${m.id}">${t("Move")}</button><button class="btn alt" data-do="emSet" data-id="${m.id}" data-s="completed">${t("Mark completed")}</button><button class="btn alt" data-do="emSet" data-id="${m.id}" data-s="active">${t("Mark active")}</button><button class="btn alt" data-do="emSet" data-id="${m.id}" data-s="waitlist">${t("Waitlist")}</button><button class="btn danger" data-do="emDel" data-id="${m.id}">${t("delete")}</button><button class="btn" data-do="emClose">${t("cancel")}</button></div><div class="rowflex row"><label>${t("start_date")}<input id="em_sd" type="date" max="${mvToday()}" value="${esc(fmtDate(m.enrolled_at))}"></label><button class="btn alt" data-do="emStart" data-id="${m.id}">${t("Change start date")}</button></div><p class="hint">${t("start_date_hint")}</p><p class="hint">${esc(t("Delete is only for enrollments added by mistake. If invoices exist, use Dropped to keep the history."))}</p></div>` : "";
  const studs = [["", "-"], ...st.filter(isActive).map(s => [s.id, personLabel(s)])];   // active students only, as on the Batches screen
  const add = addPanel("enrollment", "Add enrollment", form("fe", pickField("es", "student", studs, "") + pickField("eb", "batch", [["", "-"], ...bo], "") + `<label>${t("start_date_optional")}<input id="esd" type="date" max="${mvToday()}"><span class="hint">${t("start_date_hint")}</span></label>`, "enroll"));
  const q = (S.enq || "").toLowerCase(), lim = S.enlim || 30;
  const found = q ? e.filter(r => [r.student_name, r.course_name, r.batch_code, r.status, r.enrol_code].some(v => String(v || "").toLowerCase().includes(q))) : e;
  const listbar = `<form id="enqf" class="listbar" role="search"><label>${esc(t("search"))}<input id="enq" type="search" value="${esc(S.enq || "")}" placeholder="${esc(t("enrol_search_hint"))}"></label><button class="btn">${t("search")}</button></form>`;
  return `${m ? crumbFor(m.student_name, {em: null}) : ""}<h1>${t("enrollments")}</h1>${mover}${add}<div class="panel">${listbar}${found.length ? `${bulkBar("enr", [["emBulkStart", "Set start date"]], found.slice(0, lim).map(r => r.id))}${bulkAll("enr", found.slice(0, lim).map(r => r.id))}<table><thead><tr><th></th><th>${t("student_name")}</th><th>${t("course_name")}</th><th>${t("batch_code")}</th><th>${t("status")}</th><th>${t("start_date")}</th><th></th></tr></thead><tbody>${found.slice(0, lim).map(r => `<tr><td>${bulkBox("enr", r.id, r.student_name + " " + r.batch_code)}</td><td>${esc(r.student_name)}</td><td>${esc(r.course_name)}</td><td>${esc(r.batch_code)}</td><td>${esc(t(r.status))}</td><td><bdi dir="ltr">${esc(fmtDate(r.enrolled_at))}</bdi></td><td>${["active", "waitlist"].includes(r.status) ? `<button class="btn sm" data-do="emSet" data-id="${r.id}" data-s="dropped" data-name="${esc(r.student_name)}">${t("drop")}</button> ` : ""}<button class="btn sm" data-do="emEdit" data-id="${r.id}">${t("edit")}</button></td></tr>`).join("")}</tbody></table>` : `<p>${t(q ? "no_match" : "empty")}</p>`}${moreBtn(0, Math.min(lim, found.length), found.length, "enMore")}</div>${hist}`;
};
DO.enMore = () => { S.enlim = (S.enlim || 30) + 30; };
DO.emEdit = d => { go({em: +d.id}); return false; };
DO.emClose = () => { closeDetail({em: null}); };
// v0.8.44: change when an enrolment started; earlier start = the months in between are billed
const emStartMsg = rs => {
  const made = rs.reduce((a, r) => a + (r.earlier_invoices || 0), 0), before = rs.reduce((a, r) => a + (r.invoices_before_start || 0), 0);
  return t("saved") + (made ? " " + t("earlier_invoices_made").replace("{n}", made) : "") + (before ? " " + t("invoices_before_start").replace("{n}", before) : "");
};
DO.emStart = async d => {
  const v = val("em_sd"); if (!v) throw new Error(t("Choose the start date"));
  const r = await api("/enrollments/" + d.id + "/start-date", "POST", {start_date: v}); flash(emStartMsg([r]), !r.invoices_before_start);
};
DO.emBulkStart = async () => {
  const n = bulkSel("enr").length;
  const v = await ui.form(t("Set start date") + " · " + n, [{id: "d", label: t("start_date"), type: "date", required: true, max: mvToday(), hint: t("start_date_hint")}], {okText: t("Set start date")});
  if (!v) return false;
  const rs = []; await bulkRun("enr", async id => rs.push(await api("/enrollments/" + id + "/start-date", "POST", {start_date: v.d})));
  if (rs.length) flash(emStartMsg(rs), true);
};
DO.emSet = async d => {
  let reason;
  if (d.s === "dropped") { reason = await ui.ask(t("drop") + ": " + (d.name || (S.emInfo || {}).name || ""), {label: t("Reason (optional)"), okText: t("drop"), danger: true}); if (reason === null) return false; }
  await api("/enrollments/" + d.id, "PATCH", {status: d.s, reason}); closeDetail({em: null}); flash(t("saved"), true);
};
DO.emMove = async d => {
  if (!val("em_b")) throw new Error(t("Choose a batch"));
  const to = $("#em_b").selectedOptions[0].text;
  const reason = await ui.ask(t("Move") + ": " + ((S.emInfo || {}).name || "") + " → " + to, {label: t("Reason (optional)"), okText: t("Move")}); if (reason === null) return false;
  await api("/enrollments/" + d.id, "PATCH", {transfer_to_batch_id: val("em_b"), reason}); closeDetail({em: null}); flash(t("saved"), true);
};
DO.evCsv = () => fetchFile("/enrollment-events.csv", {name: "transfers-withdrawals.csv"});
DO.evXlsx = () => fetchFile("/enrollment-events.xlsx", {name: "transfers-withdrawals.xlsx"});   // v0.8.38
DO.emDel = async d => {
  const i = S.emInfo || {};
  if (!await ui.confirm(t("Delete this enrollment? This cannot be undone."), {danger: true, details: [`${i.name || ""} · ${i.where || ""} · ${t(i.status || "")}`, t("Delete is only for enrollments added by mistake. If invoices exist, use Dropped to keep the history.")]})) return false;
  await api("/enrollments/" + d.id, "DELETE"); closeDetail({em: null}); flash(t("saved"), true);
};

// ---------- admissions (Session 10): ONE view. The review panel sits above the list; deleting ID copies is its own action with a confirmation ----------
views.admissions = async () => {
  const f = S.filter || "pending";
  const [list, bs] = await Promise.all([api("/applications?status=" + f), api("/batches")]);
  const a = S.sel ? list.find(x => x.id === S.sel) : null;
  const editable = a && ["pending", "waitlist"].includes(a.status);
  const [full, courses] = editable ? await Promise.all([api("/applications/" + a.id), api("/courses")]) : [null, []];
  if (a) S.apInfo = {name: a.full_name, ref: a.ref};
  mount(() => {
    $("#af").onchange = e => { S.filter = e.target.value; S.result = null; if (S.sel) closeDetail({sel: null}); render(); };
    if (a && $("#ab") && a.batch_id) $("#ab").value = a.batch_id;
    if (full) onSubmit("fa", () => api("/applications/" + a.id, "PATCH", {full_name: val("fa_n"), date_of_birth: val("fa_d"), phone: val("fa_p"), email: val("fa_e"), island: nv("fa_i"), grade: nv("fa_g"), course_id: val("fa_c"), batch_id: nv("fa_b"), guardian_name: nv("fa_gn"), guardian_relationship: nv("fa_gr"), guardian_phone: nv("fa_gp")}));
  });
  const R = S.result ? `<div class="msg ok" role="status"><b>${esc(t("temp_pw"))}:</b> ${esc(S.result.temp_password)}<br><a class="btn sm alt" href="${esc(S.result.whatsapp_link)}" target="_blank" rel="noopener">${t("send_whatsapp")}</a></div>` : "";
  const D = a ? `<div class="panel" data-detail><h2>${esc(a.full_name)} · ${esc(a.ref)}</h2><p>${esc(a.course_name)} ${esc(a.batch_code || "")} · ${esc(a.phone)} · ${esc(a.email)} · ${esc(a.island || "")}<br>${esc(t("date_of_birth"))}: ${esc(a.date_of_birth)} ${a.is_minor ? '<span class="tag">&lt;18</span>' : ""}</p>${full && full.duplicates.length ? `<div class="msg err" role="note"><b>${esc(t("ap_dup_title"))}</b><ul>${full.duplicates.map(x => `<li>${esc(x.label)} · ${esc(x.why.map(w => t("ap_dup_" + w.replace(/ /g, "_"))).join(", "))}${x.kind === "account" ? " · " + esc(t("ap_dup_account")) : ""}</li>`).join("")}</ul></div>` : ""}${a.is_minor ? `<p>${esc(t("guardian_name"))}: ${esc(a.guardian_name)} (${esc(a.guardian_relationship)}) ${esc(a.guardian_phone)}</p>` : ""}${a.reject_reason ? `<p>${esc(a.reject_reason)}</p>` : ""}
      <p>${a.has_id ? `<button class="btn sm" id="vi" data-do="apView" data-w="id">${t("view_id")}</button> ` : ""}${a.has_guardian_id ? `<button class="btn sm" id="vg" data-do="apView" data-w="guardian_id">${t("view_guardian_id")}</button> ` : ""}${a.has_id || a.has_guardian_id ? `<button class="btn sm danger" id="df" data-do="apDelFiles" data-id="${a.id}">${t("delete_files")}</button>` : ""}</p>
      ${editable ? `<div class="rowflex row">${field("ab", "assign_batch", "", bs.map(x => [x.id, x.course_name + " " + x.code]))}<button class="btn" id="ap" data-do="apApprove" data-id="${a.id}">${t("approve")}</button>${a.status === "pending" ? `<button class="btn alt" id="wl" data-do="apWait" data-id="${a.id}">${t("put_waitlist")}</button>` : ""}<button class="btn alt" id="rj" data-do="apReject" data-id="${a.id}">${t("reject")}</button></div><p class="hint">${esc(t("ap_files_hint"))}</p>` : ""}
      <p><button type="button" class="btn sm alt" data-do="apBack">${t("back")}</button></p></div>` : "";
  const C = full ? (() => { const bopts = [["", "-"], ...bs.filter(x => x.course_id === full.course_id).map(x => [x.id, x.code])];
    return `<div class="panel"><h2>${esc(t("Correct details"))}</h2><form class="row" id="fa">${iv("fa_n", "name", full.full_name)}${iv("fa_d", "date_of_birth", full.date_of_birth, "date")}${iv("fa_p", "Phone", full.phone, "tel")}${iv("fa_e", "email", full.email, "email")}${iv("fa_i", "Island", full.island)}${iv("fa_g", "Grade / class", full.grade)}${sel("fa_c", "course", courses.filter(x => x.is_active || x.id === full.course_id).map(x => [x.id, x.name + " " + (x.level || "")]), full.course_id)}${sel("fa_b", "batch", bopts, full.batch_id)}${full.is_minor ? iv("fa_gn", "guardian_name", full.guardian_name) + iv("fa_gr", "Guardian relationship", full.guardian_relationship) + iv("fa_gp", "Guardian phone", full.guardian_phone) : ""}<button class="btn alt">${t("save")}</button></form><p class="hint">${esc(t("If you change the course, pick the batch again after saving."))}</p></div>`; })() : "";
  return `${a ? crumbFor(a.full_name, {sel: null}) : ""}<h1>${t("admissions")}</h1>${R}${D}${C}<div class="panel"><p>${xlBtns("/applications/export", "status=" + f, "applications-" + f)}</p><label>${t("status")}<select id="af">${["pending", "waitlist", "approved", "rejected"].map(x => `<option value="${x}" ${x === f ? "selected" : ""}>${esc(t(x === "waitlist" ? "waitlist" : x))}</option>`).join("")}</select></label>${["pending", "waitlist"].includes(f) ? bulkBar("apps", [...(f === "pending" ? [["apBulkWait", "put_waitlist"]] : []), ["apBulkReject", "reject", true]], list.map(r => r.id)) + bulkAll("apps", list.map(r => r.id)) : ""}${table(["ref", "full_name", "course_name", "batch_code", "phone", "created_at"], list, r => `${["pending", "waitlist"].includes(f) ? bulkBox("apps", r.id, r.full_name) + " " : ""}<button class="btn sm" data-do="apReview" data-id="${r.id}" data-rev="${r.id}">${t("review")}</button>`, t("admissions"))}</div>`;
};
DO.apBulkWait = async () => { const had = bulkSel("apps").includes(S.sel); await bulkRun("apps", id => api("/applications/" + id + "/waitlist", "POST")); if (had) closeDetail({sel: null}); };
DO.apBulkReject = async () => {
  const n = bulkSel("apps").length, r = await ui.ask(t("reject") + " · " + n, {label: t("reason_prompt"), required: true, multiline: true, danger: true, okText: t("reject")});
  if (!r) return false; const had = bulkSel("apps").includes(S.sel);
  await bulkRun("apps", id => api("/applications/" + id + "/reject", "POST", {reason: r})); if (had) closeDetail({sel: null});
};
DO.apReview = d => { go({sel: +d.id, result: null}); return false; };
DO.apBack = () => { S.result = null; navBack({sel: null}); return false; };
DO.apView = async d => { await fetchFile("/applications/" + S.sel + "/file/" + d.w, {preview: true}); return false; };
DO.apApprove = async d => { S.result = await api("/applications/" + d.id + "/approve", "POST", {batch_id: val("ab"), delete_files: false}); S.filter = "approved"; };
DO.apWait = async d => { await api("/applications/" + d.id + "/waitlist", "POST"); S.result = null; closeDetail({sel: null}); flash(t("saved"), true); };
DO.apReject = async d => {
  const r = await ui.ask(t("reject") + ": " + ((S.apInfo || {}).name || ""), {label: t("reason_prompt"), required: true, multiline: true, okText: t("reject"), danger: true}); if (!r) return false;
  await api("/applications/" + d.id + "/reject", "POST", {reason: r}); S.result = null; closeDetail({sel: null}); flash(t("saved"), true);
};
DO.apDelFiles = async d => {
  const i = S.apInfo || {};
  if (!await ui.confirm(t("ap_delete_files_q"), {danger: true, details: [`${i.name || ""} · ${i.ref || ""}`]})) return false;
  await api("/applications/" + d.id + "/files", "DELETE"); flash(t("saved"), true);
};

// ---------- settings: grouped, typed, with defaults and hints. Session 12: shared sub-tabs; unsaved edits are not lost by switching group ----------
const setSelect = async k => { if (S.setDirty && !await ui.confirm(t("set_discard"), {okText: t("Discard changes")})) return false; S.sg = k; S.setDirty = false; };
views.settings = async () => {
  const sc = await api("/settings/schema");
  const gid = S.sg || sc.groups[0].id;
  const g = sc.groups.find(x => x.id === gid) || sc.groups[0];
  S.setDirty = false;
  const input = it => {
    const id = "set_" + it.key, v = it.value || "";
    const dflt = it.default ? `${t("Default")}: ${it.default}` : "";
    let ctl;
    if (it.type === "longtext") ctl = `<textarea id="${id}" rows="3" placeholder="${esc(it.default)}">${esc(v)}</textarea>`;
    else if (it.type === "bool") ctl = `<select id="${id}"><option value="1" ${(v || it.default) !== "0" ? "selected" : ""}>${esc(t("On"))}</option><option value="0" ${(v || it.default) === "0" ? "selected" : ""}>${esc(t("Off"))}</option></select>`;
    else if (it.type === "select") ctl = `<select id="${id}">${it.options.map(o => `<option value="${esc(o)}" ${(v || it.default) === o ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
    else ctl = `<input id="${id}" type="${it.type === "number" ? "number" : it.type === "email" ? "email" : it.type === "url" ? "url" : "text"}" value="${esc(v)}" placeholder="${esc(it.default)}" ${it.min != null ? `min="${it.min}"` : ""} ${it.max != null ? `max="${it.max}"` : ""}>`;
    return `<div class="sub"><label class="full"><b>${esc(t(it.label))}</b>${ctl}</label><span class="hint">${esc(it.hint ? t(it.hint) + " " : "")}${esc(dflt)}</span></div>`;
  };
  DO.saveSet = async () => {
    const body = {}; for (const it of g.items) body[it.key] = val("set_" + it.key);
    await api("/settings", "PUT", body); S.setDirty = false; flash(t("saved"), true);
  };
  mount(() => {
    const p = $("#setp"); if (!p) return;
    const mark = () => { if (S.setDirty) return; S.setDirty = true; $("#setDirty").hidden = false; announce(t("Unsaved changes")); };
    p.addEventListener("input", mark); p.addEventListener("change", mark);
  });
  const store = await storagePanel();
  return `<h1>${t("settings")}</h1>${store.banner}${tabs({id: "settings", items: sc.groups.map(x => [x.id, t(x.title)]), current: g.id, onSelect: setSelect, label: t("settings")})}<div class="mt1 panel" id="setp"><h2>${esc(t(g.title))}</h2>${g.hint ? `<p class="hint">${esc(t(g.hint))}</p>` : ""}${g.items.map(input).join("")}<p><button class="btn" data-do="saveSet">${t("save")}</button> <span class="tag warn" id="setDirty" hidden>${esc(t("Unsaved changes"))}</span></p><p class="hint">${esc(t("Empty fields use the default. Every change is written to the audit log."))}</p></div>${store.panel}${resetPanel()}`;
};
DO.setTab = d => { S.sg = d.g; };

// ---------- student information (Session 6): admins find a student and see profile, batches, attendance, grades and fees in one place ----------
const siMoney = n => "MVR " + fmtNum(n || 0);
DO.siOpen = d => { go({si: +d.id}); return false; };
DO.siBack = () => { navBack({si: null}); return false; };
DO.siMore = () => { S.silimit = (S.silimit || 30) + 30; };
const siList = async () => {
  const f = S.sif || {}, q = new URLSearchParams({limit: S.silimit || 30});
  if (f.q) q.set("q", f.q); if (f.batch) q.set("batch_id", f.batch); if (f.status) q.set("status", f.status);
  const [r, bs] = await Promise.all([api("/student-information?" + q), S.sibatches ? S.sibatches : api("/batches").then(b => (S.sibatches = b)).catch(() => [])]);
  mount(() => { const ff = $("#sif"); if (ff) { $("#sif_b").value = f.batch || ""; $("#sif_s").value = f.status || ""; ff.onsubmit = e => { e.preventDefault(); S.sif = {q: val("sif_q"), batch: val("sif_b"), status: val("sif_s")}; S.silimit = 30; render(); }; } });
  return `<h1>${t("student_information")}</h1><p class="hint">${t("si_intro")}</p>
    <div class="panel"><form id="sif" class="row"><label>${t("search")}<input id="sif_q" value="${esc(f.q || "")}" placeholder="${esc(t("si_search_hint"))}"></label>
      <label>${t("batch")}<select id="sif_b"><option value="">${t("si_all_batches")}</option>${bs.map(b => `<option value="${b.id}">${esc(b.course_name)} · ${esc(b.code)}</option>`).join("")}</select></label>
      <label>${t("status")}<select id="sif_s"><option value="">${t("si_any")}</option><option value="active">${t("si_active")}</option><option value="inactive">${t("si_inactive")}</option></select></label>
      <button class="btn">${t("search")}</button></form></div>
    <div class="panel"><p>${["csv", "xlsx"].map(x => `<button class="btn sm alt" data-do="siExp" data-ext="${x}">${x === "csv" ? t("Download CSV") : t("Download Excel")}</button>`).join(" ")} <button class="btn sm alt" data-do="siExpEn">${t("Enrolments CSV")}</button> <button class="btn sm alt" data-do="siExpEnX">${t("xl_enrolments_excel")}</button></p></div>
    <div class="panel"><p class="hint">${r.students.length} / ${r.total}</p>${r.students.map(s => `<div class="cl"><div><b>${esc(s.full_name)}</b> ${s.is_active ? "" : tag(t("si_inactive"), "bad")}<br><span class="hint">${esc(s.email)}${s.phone ? " · <bdi dir=\"ltr\">" + esc(s.phone) + "</bdi>" : ""}</span><br>${s.batches.length ? esc(s.batches.join(", ")) : `<span class="hint">${t("si_no_batches")}</span>`}</div>
      <div>${s.balance_due ? tag(siMoney(s.balance_due), "warn") + " " : ""}<button class="btn sm" data-do="siOpen" data-id="${s.id}">${t("open")}</button></div></div>`).join("") || `<p>${t("empty")}</p>`}
      ${r.students.length < r.total ? `<p><button class="btn" data-do="siMore">${t("load_more")}</button></p>` : ""}</div>`;
};
const siDetail = async id => {
  const r = await api("/student-information/" + id), p = r.profile;
  const kv = (k, v) => v ? `<p><span class="hint">${t(k)}</span><br>${esc(v)}</p>` : "";
  const prof = `<div class="panel" data-detail><h2>${esc(p.full_name)} ${p.is_active ? "" : tag(t("si_inactive"), "bad")}</h2>
    <div class="stats"><div class="stat"><b>${r.enrollments.filter(e => e.status === "active").length}</b>${t("si_active_batches")}</div>${r.fees_visible ? `<div class="stat"><b>${siMoney(r.fees.balance_due)}</b>${t("si_balance_due")}${r.fees.overdue_count ? "<br>" + tag(r.fees.overdue_count + " " + t("overdue"), "bad") : ""}</div>` : ""}</div>
    ${kv("email", p.email)}${kv("phone", p.phone)}${kv("date_of_birth", p.date_of_birth)}${kv("Grade / class", p.grade)}${kv("island", p.island)}${kv("guardian_name", p.guardian_name)}${kv("guardian_relationship", p.guardian_relationship)}${kv("guardian_phone", p.guardian_phone)}${kv("si_joined", fmtDate(p.created_at))}</div>`;
  const batches = `<div class="panel"><h2>${t("batches")}</h2>${r.enrollments.map(e => `<div class="cl"><div><b>${esc(e.course_name)} · ${esc(e.code)}</b><br><span class="hint">${esc(e.teacher_name || "–")} · <bdi dir="ltr">${esc(fmtDate(e.enrolled_at))}</bdi></span></div>${tag(t("si_enr_" + e.status), e.status === "active" ? "ok" : e.status === "dropped" ? "bad" : "")}</div>`).join("") || `<p>${t("empty")}</p>`}</div>`;
  const prog = r.progress.map(c => { const a = c.attendance;
    return `<div class="panel"><h2>${esc(c.course_name)} · ${esc(c.batch_code)}</h2>
      <div class="stats"><div class="stat"><b>${pct(a.pct)}</b>${t("attendance_pct")} ${a.low ? tag(t("low_attendance"), "bad") : ""}<br><small>${t("present")} ${a.present} · ${t("late")} ${a.late} · ${t("absent")} ${a.absent} · ${t("excused")} ${a.excused}</small></div><div class="stat"><b>${pct(c.avg_pct)}</b>${t("avg_pct")}</div></div>
      <p>${c.recent.map(x => tag(x.date.slice(5) + " " + t(x.status), x.status === "absent" ? "bad" : x.status === "present" ? "ok" : "")).join(" ") || t("empty")}</p>
      ${c.items.length ? `<table><thead><tr><th>${t("title")}</th><th>${t("kind")}</th><th>${t("due_date")}</th><th>${t("grade")}</th></tr></thead><tbody>${c.items.map(i => `<tr><td>${esc(i.title)}</td><td>${t(i.kind)}</td><td>${esc(i.due_date || "–")}</td><td>${i.grade != null ? i.grade + "/" + i.max_points : t("not_graded_yet")}${i.feedback ? `<br><small>${esc(i.feedback)}</small>` : ""}</td></tr>`).join("")}</tbody></table>` : ""}</div>`; }).join("");
  const fees = !r.fees_visible ? `<div class="panel"><h2>${t("fees")}</h2><p class="hint">${t("si_fees_hidden")}</p></div>` : `<div class="panel"><h2>${t("fees")}</h2><p><button class="btn sm alt" data-do="fxStmt" data-id="${p.id}">${t("fx_statement")}</button></p>
    ${r.fees.invoices.length ? `<table><thead><tr><th>${t("si_period")}</th><th>${t("fx_description")}</th><th>${t("due_date")}</th><th>${t("si_due")}</th><th>${t("si_paid")}</th><th>${t("status")}</th></tr></thead><tbody>${r.fees.invoices.map(i => `<tr><td><bdi dir="ltr">${esc(i.period)}</bdi></td><td>${esc(i.description)}</td><td><bdi dir="ltr">${esc(i.due_date)}</bdi></td><td>${siMoney(i.amount_due_mvr)}</td><td>${siMoney(i.paid_mvr)}</td><td>${i.overdue ? tag(t("overdue"), "bad") : tag(t("si_inv_" + i.status), i.status === "paid" ? "ok" : "warn")}</td></tr>`).join("")}</tbody></table>` : `<p>${t("empty")}</p>`}
    ${r.fees.payments.length ? `<h3>${t("si_payments")}</h3>${r.fees.payments.map(x => `<div class="cl"><div><b>${esc(x.receipt_no)}</b> ${x.reversed_at ? tag(t("si_reversed"), "bad") : ""}<br><span class="hint"><bdi dir="ltr">${esc(x.paid_on)}</bdi> · ${esc(x.period)} · ${esc(x.method)}</span></div><b>${siMoney(x.amount_mvr)}</b></div>`).join("")}` : ""}</div>`;
  return `${crumbFor(p.full_name, {si: null})}<h1>${t("student_information")}</h1><p><button class="btn sm alt" data-do="siBack">${t("back")}</button></p>${prof}${batches}<h2>${t("si_attendance_grades")}</h2>${prog || `<div class="panel"><p>${t("empty")}</p></div>`}${fees}`;
};
views.student_information = async () => S.si ? siDetail(S.si).catch(x => { S.si = null; throw x; }) : siList();

// ---------- teacher information (Session 7): admins find a teacher and see profile, batches taught, students and workload ----------
DO.tiOpen = d => { go({ti: +d.id}); return false; };
DO.tiBack = () => { navBack({ti: null}); return false; };
DO.tiMore = () => { S.tilimit = (S.tilimit || 30) + 30; };
const tiList = async () => {
  const f = S.tif || {}, q = new URLSearchParams({limit: S.tilimit || 30});
  if (f.q) q.set("q", f.q); if (f.status) q.set("status", f.status);
  const r = await api("/teacher-information?" + q);
  mount(() => { const ff = $("#tif"); if (ff) { $("#tif_s").value = f.status || ""; ff.onsubmit = e => { e.preventDefault(); S.tif = {q: val("tif_q"), status: val("tif_s")}; S.tilimit = 30; render(); }; } });
  return `<h1>${t("teacher_information")}</h1><p class="hint">${t("ti_intro")}</p>
    <div class="panel"><form id="tif" class="row"><label>${t("search")}<input id="tif_q" value="${esc(f.q || "")}" placeholder="${esc(t("si_search_hint"))}"></label>
      <label>${t("status")}<select id="tif_s"><option value="">${t("si_any")}</option><option value="active">${t("si_active")}</option><option value="inactive">${t("si_inactive")}</option></select></label>
      <button class="btn">${t("search")}</button></form></div>
    <div class="panel"><p>${["csv", "xlsx"].map(x => `<button class="btn sm alt" data-do="tiExp" data-ext="${x}">${x === "csv" ? t("Download CSV") : t("Download Excel")}</button>`).join(" ")}</p></div>
    <div class="panel"><p class="hint">${r.teachers.length} / ${r.total}</p>${r.teachers.map(x => `<div class="cl"><div><b>${esc(x.full_name)}</b> ${x.is_active ? "" : tag(t("si_inactive"), "bad")}<br><span class="hint">${esc(x.email)}${x.phone ? " · <bdi dir=\"ltr\">" + esc(x.phone) + "</bdi>" : ""}</span><br>${x.batch_count} ${t("ti_batches")} · ${x.student_count} ${t("students")} · <bdi dir="ltr">${x.weekly_hours} ${t("ti_hours_week")}</bdi></div>
      <button class="btn sm" data-do="tiOpen" data-id="${x.id}">${t("open")}</button></div>`).join("") || `<p>${t("empty")}</p>`}
      ${r.teachers.length < r.total ? `<p><button class="btn" data-do="tiMore">${t("load_more")}</button></p>` : ""}</div>`;
};
const tiDetail = async id => {
  const r = await api("/teacher-information/" + id), p = r.profile, w = r.workload;
  const kv = (k, v) => v ? `<p><span class="hint">${t(k)}</span><br>${esc(v)}</p>` : "";
  const prof = `<div class="panel" data-detail><h2>${esc(p.full_name)} ${p.is_active ? "" : tag(t("si_inactive"), "bad")}</h2>${kv("email", p.email)}${kv("phone", p.phone)}${kv("Bio", p.bio)}${kv("si_joined", fmtDate(p.created_at))}</div>`;
  const load = `<div class="panel"><h2>${t("ti_workload")}</h2><div class="stats">
    <div class="stat"><b>${w.active_batches}</b>${t("ti_active_batches")}</div><div class="stat"><b>${w.students}</b>${t("students")}</div>
    <div class="stat"><b>${w.weekly_classes}</b>${t("ti_classes_week")}</div><div class="stat"><b><bdi dir="ltr">${w.weekly_hours}</bdi></b>${t("ti_hours_week")}</div>
    <div class="stat"><b>${w.classes_held_30d}</b>${t("ti_held_30d")}</div><div class="stat"><b>${w.to_grade}</b>${t("pending_grading")}</div></div></div>`;
  const batches = `<div class="panel"><h2>${t("batches")}</h2>${r.batches.map(b => `<div class="cl"><div><b>${esc(b.course_name)} · ${esc(b.code)}</b> ${tag(t(b.status), b.status === "closed" ? "" : "ok")}<br><span class="hint">${esc(b.days ? b.days.split(",").map(dayName).join(", ") : "–")} · <bdi dir="ltr">${esc(b.start_time || "–")}</bdi> · ${b.minutes} min</span></div><div>${b.students} / ${b.capacity}</div></div>`).join("") || `<p>${t("empty")}</p>`}</div>`;
  const studs = `<div class="panel"><h2>${t("students")} (${r.students.length})</h2>${r.students.map(s => `<div class="cl"><div><b>${esc(s.full_name)}</b><br><span class="hint">${esc(s.batches.join(", "))}</span></div></div>`).join("") || `<p>${t("empty")}</p>`}</div>`;
  return `${crumbFor(p.full_name, {ti: null})}<h1>${t("teacher_information")}</h1><p><button class="btn sm alt" data-do="tiBack">${t("back")}</button></p>${prof}${load}${batches}${studs}`;
};
views.teacher_information = async () => S.ti ? tiDetail(S.ti).catch(x => { S.ti = null; throw x; }) : tiList();

// ---------- Activity log (Sessions 21 and 13): filters, paging, drill-down, CSV. Read only: there is no edit or delete anywhere. ----------
// Session 13: one row more than a page is asked for, so "Next" is only enabled when a next page really exists; 5 columns, the rest under "More".
const AL_PER = 50, AL_KEYS = ["user_id", "login_id", "role", "action", "batch_id", "date_from", "date_to", "q"];
const alQuery = (extra = {}) => { const f = {...(S.al ? S.al.f : {}), ...extra}; return Object.keys(f).filter(k => f[k] !== "" && f[k] != null).map(k => encodeURIComponent(k) + "=" + encodeURIComponent(f[k])).join("&"); };
views.audit = async () => {
  S.al = S.al || {page: 1, f: {}};
  const q = alQuery({per_page: AL_PER + 1, offset: (S.al.page - 1) * AL_PER});
  const drill = S.al.f.user_id || S.al.f.batch_id;
  const [got, acts, b, sm] = await Promise.all([api("/audit?" + q), api("/audit/actions"), api("/batches"), drill ? api("/audit/summary?" + alQuery()) : null]);
  const hasNext = got.length > AL_PER, r = got.slice(0, AL_PER);
  const f = S.al.f;
  mount(() => {
    AL_KEYS.forEach(k => { const el = $("#al_" + k); if (el && f[k] != null) el.value = f[k]; });
    onSubmit("fal", async () => {   // the user drill-down (This user) stays when other filters are applied; the batch one is in the Batch box
      const nf = Object.fromEntries(AL_KEYS.filter(k => k !== "user_id" && val("al_" + k) !== "").map(k => [k, val("al_" + k)]));
      if (S.al.f.user_id) nf.user_id = S.al.f.user_id;
      S.al = {page: 1, f: nf};
    });
  });
  const roles = [["", t("all")], ...["admin", "teacher", "student", "system", "anonymous"].map(x => [x, t(x)])];
  const filters = form("fal", field("al_login_id", "Login ID") + field("al_role", "role", "text", roles) + field("al_action", "action", "text", [["", t("all")], ...acts.map(x => [x, x])])
    + field("al_batch_id", "batch", "text", [["", t("all")], ...b.map(x => [x.id, x.course_name + " " + x.code])]) + field("al_date_from", "From", "date") + field("al_date_to", "To", "date") + field("al_q", "Words in detail"), "Filter");
  const chips = sm ? `<div class="panel"><h2>${t("What has this " + (f.user_id ? "user" : "batch") + " done?")}</h2><p>${sm.total} ${t("actions")}${sm.first_at ? ` · ${esc(fmtTime(sm.first_at))} → ${esc(fmtTime(sm.last_at))}` : ""}</p><p>${sm.by_action.map(x => `<span class="chip">${esc(x.action)}: ${x.n}</span>`).join(" ")}</p>${f.batch_id ? `<p>${sm.by_user.map(x => `${esc(x.user_name || "?")} (${esc(x.user_role || "")}): ${x.n}`).join(" · ")}</p>` : ""}<p><button class="btn sm alt" data-do="alClear">${t("Show everything again")}</button></p></div>` : "";
  const nav = `<p><button class="btn sm alt" data-do="alPage" data-n="-1" ${S.al.page <= 1 ? "disabled" : ""}>${t("Previous")}</button> ${t("Page")} ${S.al.page} <button class="btn sm alt" data-do="alPage" data-n="1" ${hasNext ? "" : "disabled"}>${t("Next")}</button> <button class="btn sm alt" data-do="alCsv">${t("Download CSV")}</button> <button class="btn sm alt" data-do="alXlsx">${t("Download Excel")}</button></p>`;
  const kv = (k, v) => v != null && v !== "" ? `<tr><th scope="row">${esc(t(k))}</th><td>${esc(v)}</td></tr>` : "";
  const rows = r.map((x, i) => `<tr><td><bdi dir="ltr">${esc(fmtTime(x.at))}</bdi></td><td>${esc(x.user_name || "–")}${x.user_role ? ` <span class="hint">${esc(t(x.user_role))}</span>` : ""}</td><td>${esc(x.action)}</td><td>${esc(x.entity || "")}${x.entity_id != null ? " " + esc(x.entity_id) : ""}</td><td>${esc(x.detail || "")}</td><td><button type="button" class="btn sm alt" data-do="alMore" data-id="${i}" aria-expanded="false" aria-controls="alx_${i}">${t("More")}</button></td></tr>`
    + `<tr class="xrow" id="alx_${i}" hidden><td colspan="6" data-label=""><table class="kv nostack"><tbody>${kv("role", x.user_role && t(x.user_role))}${kv("Login ID", x.login_id)}${kv("batch", x.batch_id)}${kv("Old value", x.old_value)}${kv("New value", x.new_value)}${kv("IP", x.ip)}</tbody></table><p>${x.user_id ? `<button class="btn sm alt" data-do="alUser" data-id="${x.user_id}">${t("This user")}</button> ` : ""}${x.batch_id ? `<button class="btn sm alt" data-do="alBatch" data-id="${x.batch_id}">${t("This batch")}</button>` : ""}</p></td></tr>`).join("");
  const tbl = r.length ? `<table><caption class="sr-only">${esc(t("audit"))}</caption><thead><tr><th scope="col">${t("Time")}</th><th scope="col">${t("Who")}</th><th scope="col">${t("action")}</th><th scope="col">${t("Entity")}</th><th scope="col">${t("Detail")}</th><th scope="col"><span class="sr-only">${t("More")}</span></th></tr></thead><tbody>${rows}</tbody></table>` : `<p>${t("empty")}</p>`;
  return `<h1>${t("audit")}</h1><div class="panel">${filters}</div>${chips}<div class="panel">${nav}<p class="hint">${t("Times are Maldives time.")}</p>${tbl}${nav}</div>`;
};
DO.alMore = (d, b) => { const x = $("#alx_" + d.id); x.hidden = !x.hidden; b.setAttribute("aria-expanded", x.hidden ? "false" : "true"); b.textContent = t(x.hidden ? "More" : "Less"); return false; };
DO.alUser = d => { S.al = {page: 1, f: {user_id: d.id}}; window.scrollTo(0, 0); };
DO.alBatch = d => { S.al = {page: 1, f: {batch_id: d.id}}; window.scrollTo(0, 0); };
DO.alClear = () => { S.al = {page: 1, f: {}}; };
DO.alPage = d => { S.al.page = Math.max(1, S.al.page + (+d.n)); };
DO.alCsv = () => fetchFile("/audit.csv?" + alQuery(), {name: "activity-log.csv"});
DO.alXlsx = () => fetchFile("/audit.xlsx?" + alQuery(), {name: "activity-log.xlsx"});   // v0.8.38

// ---------- Finance (Sessions 23, 24, 30, 31; one view since Session 8): dashboard, revenue, teacher earnings, then expenses and categories ----------
const FN_KEYS = ["category_id", "date_from", "date_to", "q"];
const fnQuery = (extra = {}) => { const f = {...(S.fn ? S.fn.f : {}), ...extra}; return Object.keys(f).filter(k => f[k] !== "" && f[k] != null).map(k => encodeURIComponent(k) + "=" + encodeURIComponent(f[k])).join("&"); };
const fnMoney = n => `<bdi dir="ltr">MVR ${esc(n)}</bdi>`;
const fnTable = (head, body) => body ? `<div class="scrollx"><table><thead><tr>${head.map(h => `<th>${esc(t(h))}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div>` : `<p>${t("empty")}</p>`;
async function fnDashPanel() {   // financial dashboard and revenue (Session 24). Revenue = real payments only.
  S.fr = S.fr || {f: {}};
  const q = Object.keys(S.fr.f).filter(k => S.fr.f[k]).map(k => k + "=" + encodeURIComponent(S.fr.f[k])).join("&");
  const [dash, rev, courses, batches, types] = await Promise.all([api("/finance/dashboard?" + q.replace(/course_id=\d+&?|batch_id=\d+&?|kind=\w+&?|revenue_type=\d+&?/g, "")), api("/finance/revenue?" + q), api("/courses"), api("/batches"), api("/revenue-types").catch(() => [])]);
  S.fnTypes = types;   // v0.8.45 (needs the Fees area too; without it the filter just lists nothing)
  const f = S.fr.f;
  mount(() => {
    ["date_from", "date_to", "course_id", "batch_id", "kind", "revenue_type"].forEach(k => { const el = $("#fr_" + k); if (el && f[k]) el.value = f[k]; });
    onSubmit("ffr", async () => { S.fr = {f: Object.fromEntries(["date_from", "date_to", "course_id", "batch_id", "kind", "revenue_type"].filter(k => val("fr_" + k) !== "").map(k => [k, val("fr_" + k)]))}; });
  });
  const card = (k, v) => `<div class="stat"><b>${v}</b>${esc(t(k))}</div>`;
  const cards = `<div class="stats">${card("Revenue", fnMoney(dash.revenue))}${card("Expenses", fnMoney(dash.expenses))}${card(dash.net < 0 ? "Net loss" : "Net profit", fnMoney(dash.net))}${card("Outstanding fees", fnMoney(dash.outstanding_fees))}${card("Teacher earnings", fnMoney(dash.teacher_earnings))}${card("Academy revenue", fnMoney(dash.academy_revenue))}${card("Paid to teachers", fnMoney(dash.teacher_paid))}</div>`;
  const filt = form("ffr", field("fr_date_from", "From", "date") + field("fr_date_to", "To", "date")
    + field("fr_course_id", "Course", "text", [["", t("all")], ...courses.map(c => [c.id, c.name])]) + field("fr_batch_id", "batch", "text", [["", t("all")], ...batches.map(b => [b.id, b.course_name + " " + b.code])])
    + field("fr_kind", "Type", "text", [["", t("all")], ["course", t("Course")], ["tuition", t("Tuition class")]]) + field("fr_revenue_type", "fx_revenue_type", "text", [["", t("all")], ...(S.fnTypes || []).map(r => [r.id, r.name])]), "Filter");
  const m = fnTable(["Month", "Collected", "Payments"], rev.by_month.map(r => `<tr><td>${esc(r.month)}</td><td>${fnMoney(r.collected)}</td><td>${r.payments}</td></tr>`).join(""));
  const ty = fnTable(["fx_revenue_type", "Collected", "Payments"], (rev.by_type || []).map(r => `<tr><td>${esc(r.revenue_type_name || "-")}</td><td>${fnMoney(r.collected)}</td><td>${r.payments}</td></tr>`).join(""));   // v0.8.45
  const c = fnTable(["Course", "Type", "Collected"], rev.by_course.map(r => `<tr><td>${esc(r.course_name || t("fx_no_course"))}</td><td>${esc(r.kind ? t(r.kind === "tuition" ? "Tuition class" : "Course") : "-")}</td><td>${fnMoney(r.collected)}</td></tr>`).join(""));
  const b = fnTable(["batch", "Course", "Collected"], rev.by_batch.map(r => `<tr><td>${esc(r.batch_code || "-")}</td><td>${esc(r.course_name || t("fx_no_course"))}</td><td>${fnMoney(r.collected)}</td></tr>`).join(""));
  return `<h2>${t("Financial dashboard")}</h2><p class="hint">${esc(dash.date_from || "")} → ${esc(dash.date_to || "")}</p>${cards}`
    + `<div class="panel"><h2>${t("Revenue")}</h2><p class="hint">${t("Revenue is money actually received (reversed payments are not counted).")}</p>${filt}`
    + `<p>${t("Total collected")}: <b>${fnMoney(rev.total_collected)}</b> · ${t("Outstanding")}: <b>${fnMoney(rev.outstanding)}</b> · ${t("Course")}: ${fnMoney(rev.by_kind.course)} · ${t("Tuition class")}: ${fnMoney(rev.by_kind.tuition)}${rev.by_kind.other ? ` · ${t("fx_no_course")}: ${fnMoney(rev.by_kind.other)}` : ""}</p>${ty}${m}${c}${b}</div>`;
}
async function fnExpensesPanels() {   // expenses, categories, receipts (Session 23). Needs the "finance" area; the server refuses everyone else.
  S.fn = S.fn || {page: 1, f: {}, edit: null};
  const recs = await api("/recurring-expenses");   // first: it writes any monthly expense that is due, so the list below includes it
  const [r, cats] = await Promise.all([api("/expenses?" + fnQuery({page: S.fn.page, per_page: 50})), api("/expense-categories")]);
  const f = S.fn.f, ed = S.fn.edit ? r.items.find(x => x.id === S.fn.edit) : null;
  const active = cats.filter(k => k.is_active || (ed && k.id === ed.category_id));
  mount(() => {
    FN_KEYS.forEach(k => { const el = $("#fn_" + k); if (el && f[k] != null) el.value = f[k]; });
    if (ed) { $("#fx_date").value = ed.expense_date; $("#fx_amt").value = ed.amount_mvr; $("#fx_cat").value = ed.category_id; $("#fx_desc").value = ed.description || ""; }
    onSubmit("ffn", async () => { S.fn = {page: 1, f: Object.fromEntries(FN_KEYS.filter(k => val("fn_" + k) !== "").map(k => [k, val("fn_" + k)])), edit: null}; });
    onSubmit("fex", async () => {
      const fd = new FormData();
      fd.append("expense_date", val("fx_date")); fd.append("amount_mvr", wholeNum("fx_amt", "Amount (MVR)", {min: 1, empty: false})); fd.append("category_id", val("fx_cat")); fd.append("description", val("fx_desc"));
      const file = $("#fx_file").files[0]; if (file) fd.append("file", file);
      if (ed && $("#fx_rm") && $("#fx_rm").checked) fd.append("remove_receipt", "1");
      await apiForm(ed ? "/expenses/" + ed.id : "/expenses", fd, ed ? "PATCH" : "POST"); S.fn.edit = null;
    });
    onSubmit("fcat", async () => { await api("/expense-categories", "POST", {name: val("fc_name")}); });
    onSubmit("frec", async () => {
      const res = await api("/recurring-expenses", "POST", {category_id: val("fr2_cat"), amount_mvr: wholeNum("fr2_amt", "Amount (MVR)", {min: 1, empty: false}), day_of_month: val("fr2_day"), description: val("fr2_desc"), start_month: val("fr2_from"), end_month: val("fr2_to") || null});
      S.recNote = t("rec_added").replace("{n}", res.written);   // onSubmit shows "Saved"; this line under the list says how many were entered
    });
  });
  const filters = form("ffn", field("fn_category_id", "Category", "text", [["", t("all")], ...cats.map(k => [k.id, k.name])]) + field("fn_date_from", "From", "date") + field("fn_date_to", "To", "date") + field("fn_q", "Words in description"), "Filter");
  const entry = `<form class="row" id="fex"><label>${esc(t("Expense date"))}<input id="fx_date" type="date" value="${mvToday()}" max="${mvToday()}" required></label>`
    + `<label>${esc(t("Amount (MVR)"))}<input id="fx_amt" type="number" min="1" step="1" inputmode="numeric" required></label>`
    + field("fx_cat", "Category", "text", active.map(k => [k.id, k.name])) + field("fx_desc", "Description")
    + `<label>${t("Receipt (PDF, JPG or PNG)")}<input id="fx_file" type="file" accept=".pdf,.jpg,.jpeg,.png"></label>`
    + (ed && ed.has_receipt ? `<label><input id="fx_rm" type="checkbox"> ${t("Remove the current receipt")}</label>` : "")
    + `<button class="btn alt">${t(ed ? "Save" : "Add expense")}</button>${ed ? ` <button type="button" class="btn" data-do="fnCancel">${t("Cancel")}</button>` : ""}</form>`;
  const body = r.items.map(x => `<tr><td>${esc(x.expense_date)}</td><td>${esc(x.category)}</td><td>${esc(x.description || "")}${x.recurring_id ? " " + tag(t("rec_monthly")) : ""}</td><td><bdi dir="ltr">${esc(x.amount_mvr)}</bdi></td><td>${x.has_receipt ? `<button class="btn sm alt" data-do="fnReceipt" data-id="${x.id}" data-name="${esc(x.receipt_name || "receipt")}">${t("Receipt")}</button>` : ""}</td>`
    + `<td><button class="btn sm alt" data-do="fnEdit" data-id="${x.id}">${t("Edit")}</button> <button class="btn sm" data-do="fnDel" data-id="${x.id}" data-name="${esc(x.expense_date + " · " + x.category + " · MVR " + x.amount_mvr)}">${t("Delete")}</button></td></tr>`).join("");
  const nav = `<p><button class="btn sm alt" data-do="fnPage" data-n="-1" ${S.fn.page <= 1 ? "disabled" : ""}>${t("Previous")}</button> ${t("Page")} ${S.fn.page} <button class="btn sm alt" data-do="fnPage" data-n="1" ${r.page * r.per_page >= r.count ? "disabled" : ""}>${t("Next")}</button></p>`;
  const catRows = cats.map(k => `<span class="chip">${esc(k.name)} (${k.expense_count})${k.is_active ? "" : " · " + t("inactive")} <button class="btn sm alt" data-do="fnCatToggle" data-id="${k.id}" data-on="${k.is_active ? 0 : 1}">${t(k.is_active ? "Make inactive" : "Make active")}</button> <button class="btn sm alt" data-do="fnCatRename" data-id="${k.id}" data-name="${esc(k.name)}">${t("Rename")}</button>${k.expense_count ? "" : ` <button class="btn sm" data-do="fnCatDel" data-id="${k.id}" data-name="${esc(k.name)}">${t("Delete")}</button>`}</span>`).join(" ");
  // v0.8.37: monthly expenses written automatically on their day
  const recRows = recs.map(x => `<div class="cl${x.is_active ? "" : " off"}"><div><b>${esc(x.category)}</b> · <bdi dir="ltr">MVR ${esc(x.amount_mvr)}</bdi> · ${t("rec_day")} ${x.day_of_month}${x.description ? " · " + esc(x.description) : ""} ${x.is_active ? "" : tag(t("rec_paused"), "warn")}<br>
    <span class="hint">${t("rec_from")} <bdi dir="ltr">${esc(x.start_month)}</bdi>${x.end_month ? ` ${t("rec_until")} <bdi dir="ltr">${esc(x.end_month)}</bdi>` : ""} · ${t("rec_written")}: ${x.months_written}${x.next_date ? ` · ${t("rec_next")} <bdi dir="ltr">${esc(x.next_date)}</bdi>` : ""}</span></div>
    <div class="seg"><button class="btn sm alt" data-do="recEdit" data-id="${x.id}" data-amt="${x.amount_mvr}" data-day="${x.day_of_month}" data-desc="${esc(x.description || "")}" data-end="${esc(x.end_month || "")}">${t("Edit")}</button><button class="btn sm alt" data-do="recToggle" data-id="${x.id}" data-on="${x.is_active ? 0 : 1}">${t(x.is_active ? "rec_pause" : "rec_resume")}</button><button class="btn sm" data-do="recDel" data-id="${x.id}" data-name="${esc(x.category + " · MVR " + x.amount_mvr)}">${t("Delete")}</button></div></div>`).join("");
  const month = mvToday().slice(0, 7);
  const recForm = `<form class="row" id="frec">${field("fr2_cat", "Category", "text", active.map(k => [k.id, k.name]))}<label>${esc(t("Amount (MVR)"))}<input id="fr2_amt" type="number" min="1" step="1" inputmode="numeric" required></label>`
    + `<label>${t("rec_day_label")}<input id="fr2_day" type="number" min="1" max="28" step="1" inputmode="numeric" value="1" required></label>${field("fr2_desc", "Description")}`
    + `<label>${t("rec_start")}<input id="fr2_from" type="month" value="${month}" required></label><label>${t("rec_end")}<input id="fr2_to" type="month"></label><button class="btn alt">${t("rec_add")}</button></form><p class="hint">${t("rec_hint")}</p>`;
  return `<div class="panel"><h2>${t(ed ? "Edit expense" : "Add expense")}</h2>${cats.some(k => k.is_active) ? entry : `<p>${t("Add a category first.")}</p>`}</div>`
    + `<div class="panel"><h2>${t("rec_title")}</h2>${S.recNote ? `<p class="msg ok" role="status">${esc(S.recNote)}</p>` : ""}${(S.recNote = null, "")}${recRows || `<p class="hint">${t("rec_none")}</p>`}${cats.some(k => k.is_active) ? `<details class="addp"${recs.length ? "" : " open"}><summary>${t("rec_add")}</summary>${recForm}</details>` : ""}</div>`
    + `<div class="panel"><h2>${t("Categories")}</h2><p>${catRows || t("empty")}</p>${form("fcat", field("fc_name", "Category name"), "Add category")}</div>`
    + `<div class="panel"><h2>${t("Expenses")}</h2>${filters}<p><b>${r.count}</b> ${t("expenses")} · ${t("Total")}: <b><bdi dir="ltr">MVR ${esc(r.total_mvr)}</bdi></b> ${xlBtns("/expenses/export", new URLSearchParams(Object.entries(f).filter(([, v]) => v)).toString(), "expenses")}</p>${nav}`
    + (r.items.length ? `<table><thead><tr><th>${t("date")}</th><th>${t("Category")}</th><th>${t("Description")}</th><th>MVR</th><th></th><th></th></tr></thead><tbody>${body}</tbody></table>` : `<p>${t("empty")}</p>`) + `${nav}</div>` + impBox("expenses", t("xl_imp_expenses"));
}
DO.recToggle = async d => { await api("/recurring-expenses/" + d.id, "PATCH", {is_active: d.on === "1"}); flash(t("saved"), true); };
DO.recDel = async d => { if (!await ui.confirm(t("rec_del_q"), {danger: true, okText: t("Delete"), details: [d.name || ""]})) return false; await api("/recurring-expenses/" + d.id, "DELETE"); flash(t("saved"), true); };
DO.recEdit = async d => {
  const v = await ui.form(t("Edit"), [{id: "amount_mvr", label: t("Amount (MVR)"), type: "number", required: true, min: 1, step: 1, value: d.amt, inputmode: "numeric"},
    {id: "day_of_month", label: t("rec_day_label"), type: "number", required: true, min: 1, max: 28, step: 1, value: d.day, inputmode: "numeric"},
    {id: "description", label: t("Description"), value: d.desc, maxlength: 200}, {id: "end_month", label: t("rec_end"), type: "month", value: d.end}], {okText: t("Save")});
  if (!v) return false;
  await api("/recurring-expenses/" + d.id, "PATCH", {...v, end_month: v.end_month || null}); flash(t("rec_edit_done"), true);
};
views.finance = async () => {
  const [dash, earn, exp] = await Promise.all([fnDashPanel(), feEarnPanel(), fnExpensesPanels()]);
  return `<h1>${t("finance")}</h1>${dash}${earn}${exp}`;
};
DO.fnPage = d => { S.fn.page = Math.max(1, S.fn.page + (+d.n)); };
DO.fnEdit = d => { S.fn.edit = +d.id; window.scrollTo(0, 0); };
DO.fnCancel = () => { S.fn.edit = null; };
DO.fnReceipt = async d => { await viewFile("/expenses/" + d.id + "/receipt", d.name); return false; };
DO.fnDel = async d => { if (!await ui.confirm(t("Delete this expense? The activity log keeps a record of it."), {danger: true, details: [d.name || ""]})) return false; await api("/expenses/" + d.id, "DELETE"); };
DO.fnCatToggle = async d => { await api("/expense-categories/" + d.id, "PATCH", {is_active: +d.on}); };
DO.fnCatRename = async d => { const n = await ui.ask(t("Rename"), {label: t("Category name"), value: d.name, required: true, maxlength: 80, okText: t("save")}); if (!n || n === d.name) return false; await api("/expense-categories/" + d.id, "PATCH", {name: n}); };
DO.fnCatDel = async d => { if (!await ui.confirm(t("Delete this category?"), {danger: true, details: [d.name || ""]})) return false; await api("/expense-categories/" + d.id, "DELETE"); };

// ---------- Teacher earnings (Sessions 30 and 31) ----------
// Session 13: the month before this one in Maldives time (the old "32 days ago" could skip or repeat a month)
const prevMonth = () => { const d = new Date(Date.now() + 5 * 3600e3), y = d.getUTCFullYear(), m = d.getUTCMonth(); return m === 0 ? `${y - 1}-12` : `${y}-${String(m).padStart(2, "0")}`; };
const feMonth = () => (S.fe && S.fe.month) || prevMonth();
async function feEarnPanel() {
  S.fe = S.fe || {month: feMonth()};
  const m = S.fe.month;
  // v0.8.40: a month the server refuses (not started yet, or typed in another form) no longer breaks the whole Finance tab:
  // the message is shown in this panel and the month goes back to last month.
  let monthErr = "";
  const [r, tt, pays] = await Promise.all([
    api("/earnings?month=" + encodeURIComponent(m)).catch(x => { monthErr = x.message; S.fe = null; return {items: [], totals: {collected_mvr: 0, teacher_share_mvr: 0, academy_share_mvr: 0}}; }),
    api("/earnings/teachers"), api("/earnings/payments")]);
  const approved = r.items.length && r.items.every(x => x.status === "approved");
  const rowsHtml = r.items.map(x => `<tr><td>${esc(x.teacher_name || "-")}</td><td>${esc(x.course_name)} ${esc(x.batch_code)}</td><td>${fnMoney(x.collected_mvr)}</td><td>${x.share_percent}%</td><td>${fnMoney(x.teacher_share_mvr)}</td><td>${fnMoney(x.academy_share_mvr)}</td><td>${esc(t(x.status))}</td></tr>`).join("");
  const tRows = tt.items.map(x => `<tr><td>${esc(x.teacher_name)}</td><td>${fnMoney(x.earned_mvr)}</td><td>${fnMoney(x.paid_mvr)}</td><td><b>${fnMoney(x.outstanding_mvr)}</b></td><td><button class="btn sm" data-do="fePay" data-id="${x.teacher_id}" data-name="${esc(x.teacher_name)}" data-owed="${esc(x.outstanding_mvr)}">${esc(t("Record payment"))}</button></td></tr>`).join("");
  const pRows = pays.map(x => `<tr${x.voided_at ? ' style="opacity:.5"' : ""}><td>${esc(x.paid_on)}</td><td>${esc(x.teacher_name)}</td><td>${fnMoney(x.amount_mvr)}</td><td>${esc(t("fx_m_" + x.method))} ${esc(x.reference || "")}</td><td>${x.voided_at ? esc(t("Voided")) : `<button class="btn sm danger" data-do="feVoid" data-id="${x.id}" data-name="${esc(x.teacher_name + " · MVR " + x.amount_mvr + " · " + x.paid_on)}">${esc(t("Void"))}</button>`}</td></tr>`).join("");
  mount(() => { const el = $("#fe_month"); if (el) el.value = m; });
  return `<div class="panel"><h2>${t("Teacher earnings")}</h2><p class="hint">${esc(t("Share of the fees actually collected each month (registration fees are not included). Approve a finished month to lock it."))}</p>
    <div class="rowflex row"><label>${esc(t("Month"))}<input type="month" id="fe_month" placeholder="YYYY-MM" pattern="\\d{4}-\\d{2}"></label>
    <button class="btn" data-do="feShow">${esc(t("Show"))}</button><button class="btn alt" data-do="feCalc" ${approved ? "disabled" : ""}>${esc(t("Calculate"))}</button>
    <button class="btn" data-do="feApprove" data-total="${r.totals.teacher_share_mvr}" ${approved || !r.items.length ? "disabled" : ""}>${esc(t("Approve month"))}</button>
    <button class="btn" data-do="feCsv">CSV</button><button class="btn" data-do="feXlsx">Excel</button></div>
    ${monthErr ? `<p class="msg err" role="alert">${esc(m)}: ${esc(monthErr)}</p>` : ""}
    ${!monthErr && !r.items.length ? `<p class="hint">${esc(t("fe_empty_hint"))}</p>` : ""}
    ${fnTable(["Teacher", "Batch", "Collected", "Share", "Teacher share", "Academy share", "status"], rowsHtml)}
    <p>${t("Total")}: ${fnMoney(r.totals.collected_mvr)} → ${fnMoney(r.totals.teacher_share_mvr)} / ${fnMoney(r.totals.academy_share_mvr)}</p>
    <h3>${t("Owed to teachers (approved months)")}</h3>${fnTable(["Teacher", "Earned", "Paid", "Outstanding", ""], tRows)}
    <h3>${t("Payments to teachers")}</h3>${fnTable(["Date", "Teacher", "Amount", "Method", ""], pRows)}</div>`;
}
DO.feShow = () => { S.fe = {month: val("fe_month") || feMonth()}; };
DO.feCalc = async () => { S.fe = {month: val("fe_month") || feMonth()}; await api("/earnings/calculate", "POST", {month: S.fe.month}); flash(t("saved"), true); };
DO.feApprove = async d => { const m = val("fe_month") || feMonth(); if (!await ui.confirm(t("Approve and lock") + " " + m + "?", {okText: t("Approve month"), details: [t("Total") + ": MVR " + d.total, t("fe_approve_hint")]})) return false; await api("/earnings/approve", "POST", {month: m, expected_teacher_total: d.total}); S.fe = {month: m}; flash(t("saved"), true); };
// Session 3: one form instead of three prompts; the method is a list, not typed text
DO.fePay = async d => {
  const v = await ui.form(t("Record payment") + ": " + (d.name || ""), [
    {id: "amount", label: t("Amount (MVR)"), type: "number", required: true, min: 1, step: 1, inputmode: "numeric", value: +d.owed > 0 ? d.owed : "", hint: t("Outstanding") + ": MVR " + (d.owed || 0)},
    {id: "method", label: t("Method"), type: "select", options: ["bank_transfer", "cash", "cheque", "other"].map(k => [k, t("fx_m_" + k)]), value: "bank_transfer"},
    {id: "reference", label: t("Reference (optional)"), maxlength: 80},
    {id: "note", label: t("fx_note"), type: "textarea", maxlength: 300, rows: 2}], {okText: t("Record payment")});
  if (!v) return false;
  await api("/earnings/payments", "POST", {teacher_id: d.id, amount_mvr: v.amount, method: v.method, reference: v.reference, note: v.note}); flash(t("saved"), true);
};
DO.feVoid = async d => { const why = await ui.ask(t("Void") + ": " + (d.name || ""), {label: t("Reason"), required: true, multiline: true, okText: t("Void"), danger: true}); if (!why) return false; await api("/earnings/payments/" + d.id + "/void", "POST", {reason: why}); flash(t("saved"), true); };
DO.feCsv = () => fetchFile("/earnings/report.csv?from=" + (val("fe_month") || feMonth()) + "&to=" + (val("fe_month") || feMonth()), {name: "teacher-earnings.csv"});
DO.feXlsx = () => fetchFile("/earnings/report.xlsx?from=" + (val("fe_month") || feMonth()) + "&to=" + (val("fe_month") || feMonth()), {name: "teacher-earnings.xlsx"});

// ---------- Admin dashboard (Session 25; the only Dashboard since Session 8): academic and financial cards with filters, from one endpoint ----------
const adKeys = ["course_id", "batch_id", "kind", "teacher_id", "date_from", "date_to"];
views.dashboard = async () => {
  S.ad = S.ad || {f: {}};
  const q = adKeys.filter(k => S.ad.f[k]).map(k => k + "=" + encodeURIComponent(S.ad.f[k])).join("&");
  const d = await api("/admin/dashboard" + (q ? "?" + q : ""));
  const o = d.options, f = S.ad.f;
  mount(() => {
    adKeys.forEach(k => { const el = $("#ad_" + k); if (el && f[k]) el.value = f[k]; });
    onSubmit("fad", async () => { S.ad = {f: Object.fromEntries(adKeys.filter(k => val("ad_" + k) !== "").map(k => [k, val("ad_" + k)]))}; });
  });
  const filt = form("fad", field("ad_course_id", "Course", "text", [["", t("all")], ...o.courses.map(c => [c.id, c.name])]) + field("ad_batch_id", "batch", "text", [["", t("all")], ...o.batches.map(b => [b.id, b.course_name + " " + b.code])])
    + field("ad_kind", "Type", "text", [["", t("all")], ["course", t("Course")], ["tuition", t("Tuition class")]]) + field("ad_teacher_id", "Teacher", "text", [["", t("all")], ...o.teachers.map(x => [x.id, x.full_name])])
    + field("ad_date_from", "From", "date") + field("ad_date_to", "To", "date"), "Filter");
  const cards = list => `<div class="stats">${list.map(([k, v]) => `<div class="stat"><b><bdi dir="ltr">${esc(v)}</bdi></b>${esc(t(k))}</div>`).join("")}</div>`;
  const acad = cards([["Students", d.students], ["Teachers", d.teachers], ["Admissions waiting", d.admissions_pending], ["Admissions received", d.admissions_received], ["Courses", d.courses], ["Tuition classes", d.tuition_classes], ["batches", d.batches],
    ["Classes held", d.classes_held], ["Classes coming up", d.classes_upcoming], ["Classes cancelled", d.classes_cancelled], ["Assignments", d.assignments], ["Tests", d.tests], ["Tutorials", d.tutorials],
    ["Submissions", d.submissions], ["Graded", d.graded], ["Waiting for grading", d.pending_grading]]);
  const fin = d.financial ? `<h2>${t("Finance")}</h2>` + cards([["Revenue", "MVR " + d.financial.revenue], ["Expenses", "MVR " + d.financial.expenses], [d.financial.net < 0 ? "Net loss" : "Net profit", "MVR " + d.financial.net], ["Outstanding fees", "MVR " + d.financial.outstanding], ["Teacher earnings", "MVR " + d.financial.teacher_earnings], ["Academy revenue", "MVR " + d.financial.academy_revenue]]) : "";
  const fee = d.fees ? cards([[t("fx_unpaid_invoices"), d.fees.unpaid_invoices], [t("fx_overdue_invoices"), d.fees.overdue_invoices], [t("fx_slips_pending"), d.fees.slips_pending]]) : "";
  const [store, todo, on] = await Promise.all([storagePanel(true), api("/admin/todo").catch(() => null), S.user.permissions ? null : api("/admin/presence/summary").catch(() => null)]);
  return `<h1>${t("dashboard")}</h1>${store.banner}${onlinePanel(on)}${todoPanel(todo)}<div class="panel">${filt}<p class="hint">${t("No dates chosen means all time. Accounts: ")}${d.student_accounts} ${t("Students")}, ${d.teacher_accounts} ${t("Teachers")}.</p></div>${acad}${fin}${fee}<div class="panel">${esc(t("apply_link"))}: <a href="/apply.html" target="_blank" rel="noopener">/apply.html</a></div>`;
};

// Session 27: exports and CSV import (the import panel is drawn at the bottom of People)
const exQuery = f => { const q = new URLSearchParams(); if (f.q) q.set("q", f.q); if (f.batch) q.set("batch_id", f.batch); if (f.status) q.set("status", f.status); return q.toString(); };
DO.siExp = d => fetchFile(`/student-information/export.${d.ext}?` + exQuery(S.sif || {}), {name: "student-information." + d.ext});
DO.siExpEn = () => fetchFile("/student-information/enrolments.csv", {name: "enrolments.csv"});
DO.siExpEnX = () => fetchFile("/student-information/enrolments.xlsx", {name: "enrolments.xlsx"});
DO.tiExp = d => fetchFile(`/teacher-information/export.${d.ext}?` + exQuery(S.tif || {}), {name: "teacher-information." + d.ext});
const impRun = async dry => {
  const f = $("#imp_f").files[0] || (S.impPFile && S.impPFile.k === val("imp_k") ? S.impPFile.f : null); if (!f) throw new Error(t("xl_choose_file"));
  S.impPFile = {f, k: val("imp_k")};   // kept across the redraw after Check file
  S.impkind = val("imp_k"); S.imp = await importInParts(`/import/${S.impkind}`, f, dry, impProgress("impprog_people"));   // v0.8.42: in parts
};
DO.impCheck = async () => { await impRun(true); };
DO.impPTpl = async () => { const k = val("imp_k"); await fetchFile(`/import/${k}/template.xlsx`, {name: `import-${k}-template.xlsx`}); return false; };
DO.impGo = async () => { if (!await ui.confirm(t("Import this file now? Rows that pass the check will be created."), {okText: t("Import"), details: S.imp && S.imp.dry_run ? [`${S.imp.ok} ${t("would be created")} · ${S.imp.rejected} ${t("rejected")}`] : []})) return false; await impRun(false); };
DO.impCreds = () => {   // the temporary passwords exist only in this response: save them as a CSV on the admin's own device
  const lines = ["login_id,name,temporary_password", ...S.imp.rows.filter(x => x.temporary_password).map(x => [x.login_id, x.name, x.temporary_password].map(v => '"' + String(v).replace(/"/g, '""') + '"').join(","))];
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([lines.join("\n")], {type: "text/csv"})); a.download = "new-accounts.csv"; a.click(); return false;
};
const impPanel = () => {
  const r = S.imp, made = r && !r.dry_run && r.rows.some(x => x.temporary_password);
  return `<div class="panel"><h2>${t("xl_import_people")}</h2><p class="hint">${t("xl_import_hint")} ${t("Courses and batches must already exist.")}</p>
    <div class="rowflex row"><label>${t("What to import")}<select id="imp_k">${[["students", "Students"], ["teachers", "Teachers"], ["enrolments", "Enrolments"]].map(([v, l]) => `<option value="${v}" ${S.impkind === v ? "selected" : ""}>${t(l)}</option>`).join("")}</select></label>
    <button type="button" class="btn sm alt" data-do="impPTpl">${t("xl_template")}</button><label>${t("xl_file")}<input id="imp_f" type="file" accept="${XL_ACCEPT}">${S.impPFile ? `<span class="hint">${t("xl_chosen")}: <bdi>${esc(S.impPFile.f.name)}</bdi></span>` : ""}</label><button class="btn alt" data-do="impCheck">${t("Check file")}</button><button class="btn" data-do="impGo">${t("Import")}</button></div><p class="hint" role="status" id="impprog_people"></p>
    ${r ? impStopped(r) + `<p><b>${r.dry_run ? t("Check result: nothing was saved") : t("Imported")}</b> · ${r.ok} ${r.dry_run ? t("would be created") : t("created")} · ${r.rejected} ${t("rejected")} / ${r.total}</p>
      ${made ? `<p class="msg err">${t("Temporary passwords are shown only now. Save them before leaving this page.")} <button class="btn sm" data-do="impCreds">${t("Download new accounts CSV")}</button></p>` : ""}
      ${r.rows.filter(x => x.status === "rejected").map(x => `<div class="msg err">${t("Row")} ${x.row} · ${esc(x.name)}: ${esc(x.message)}</div>`).join("")}` : ""}</div>`;
};

// ---------- v0.8.34: files and storage. Where uploads are kept, whether that lasts, and which records lost their file ----------
const canStorage = () => S.user && S.user.role === "admin" && (S.user.tabs || []).includes("settings");
async function storagePanel(bannerOnly) {
  if (!canStorage()) return {banner: "", panel: ""};
  let h; try { h = await api("/admin/storage"); } catch (_) { return {banner: "", panel: ""}; }
  const banner = h.persistent ? "" : `<div class="msg err" role="alert"><b>${esc(t("storage_not_kept"))}</b> ${esc(h.advice)}</div>`;
  if (bannerOnly) return {banner, panel: ""};
  const m = S.stMissing;
  const list = !m ? "" : m.missing ? `<p><b>${m.missing}</b> ${esc(t("storage_missing_n"))}${m.complete ? "" : " " + esc(t("storage_partial").replace("{n}", m.checked).replace("{m}", m.total))}</p><p>${Object.entries(m.by_kind).map(([k, n]) => `<span class="chip">${esc(t(k))}: ${n}</span>`).join(" ")}</p>`
      + `<table><thead><tr><th>${t("kind")}</th><th>${t("name")}</th><th>${t("date")}</th></tr></thead><tbody>${m.items.map(x => `<tr><td>${esc(t(x.kind))}</td><td>${esc(x.label || "#" + x.id)}</td><td><bdi dir="ltr">${esc(fmtTime(x.at))}</bdi></td></tr>`).join("")}</tbody></table><p class="hint">${esc(t("storage_missing_hint"))}</p>`
    : `<p class="msg ok">${esc(t("storage_none_missing").replace("{n}", m.checked))}</p>`;
  const panel = `<div class="panel mt1" id="storep"><h2>${esc(t("Files and storage"))}</h2><table class="kv nostack"><tbody>`
    + `<tr><th scope="row">${esc(t("storage_where"))}</th><td>${esc(h.where)}</td></tr>`
    + `<tr><th scope="row">${esc(t("storage_database"))}</th><td>${esc(h.database === "postgresql" ? "PostgreSQL" : "SQLite")}${h.on_vercel ? " · Vercel" : ""}</td></tr>`
    + (h.files != null ? `<tr><th scope="row">${esc(t("storage_files"))}</th><td>${h.files} · <bdi dir="ltr">${h.mb} MB</bdi></td></tr>` : "")
    + `<tr><th scope="row">${esc(t("storage_kept"))}</th><td>${h.persistent ? tag(t("Yes"), "ok") : tag(t("No"), "bad")}</td></tr></tbody></table>`
    + `<p><button type="button" class="btn alt" data-do="stCheck">${esc(t("storage_check"))}</button></p>${list}</div>`;
  return {banner, panel};
}
DO.stCheck = async () => { S.stMissing = await api("/admin/storage/missing"); };

// ---------- v0.8.41: clear portal data (full admins only). Preview first, then the admin's password and the words DELETE ALL DATA ----------
function resetPanel() {
  if (S.user.role !== "admin" || S.user.permissions) return "";
  return `<div class="panel mt1" id="resetp"><h2>${esc(t("rd_title"))}</h2><p class="hint">${esc(t("rd_hint"))}</p>`
    + `<p><button type="button" class="btn danger" data-do="rdStart">${esc(t("rd_button"))}</button></p></div>`;
}
DO.rdStart = async () => {
  const p = await api("/admin/reset-data", "POST", {});   // a preview: nothing is changed
  if (!p.total) { flash(t("rd_nothing"), true); return false; }
  const kept = t("rd_kept").replace("{a}", p.kept.admins);
  if (!await ui.confirm(t("rd_confirm").replace("{n}", fmtNum(p.total)), {danger: true, title: t("rd_title"), okText: t("rd_continue"),
    details: p.items.map(x => t(x.label) + ": " + fmtNum(x.rows)).concat([kept])})) return false;
  const v = await ui.form(t("rd_title"), [
    {id: "numbers", label: t("rd_numbers"), type: "select", options: [["keep", t("rd_numbers_keep")], ["restart", t("rd_numbers_restart")]], value: "keep"},
    {id: "password", label: t("rd_password"), type: "password", required: true, autocomplete: "current-password"},
    {id: "confirm", label: t("rd_type").replace("{p}", p.phrase), required: true, autocomplete: "off", placeholder: p.phrase}],
    {okText: t("rd_button"), danger: true, hint: t("rd_form_hint"), validate: x => x.confirm === p.phrase ? "" : t("rd_type").replace("{p}", p.phrase)});
  if (!v) return false;
  const r = await api("/admin/reset-data", "POST", {apply: true, password: v.password, confirm: v.confirm, reset_numbers: v.numbers === "restart"});
  S.stMissing = null; staleBadges();
  flash(t("rd_done").replace("{n}", fmtNum(r.total)), true);
};

// v0.8.47: "Who's online" on a full admin's Dashboard (others get nothing: the server answers 403 and the panel is left out)
function onlinePanel(d) {
  if (!d) return "";
  const c = d.counts, r = d.by_role, warn = c.warnings || d.failed_24h >= 3;
  return `<div class="panel" id="onp"><h2>${esc(t("online"))}</h2><div class="cl"><div><b><bdi dir="ltr">${fmtNum(c.online)}</bdi></b> ${esc(t("Online now"))}`
    + ` <span class="hint">· ${esc(t("Students"))} ${r.student.online} · ${esc(t("Teachers"))} ${r.teacher.online} · ${esc(t("Admins"))} ${r.admin.online}</span>`
    + `${c.paused || c.suspended ? `<br>${c.paused ? tag(c.paused + " " + t("Paused"), "warn") + " " : ""}${c.suspended ? tag(c.suspended + " " + t("Suspended"), "bad") : ""}` : ""}`
    + `${warn ? `<br>${tag(t("failed_signins_24h").replace("{n}", d.failed_24h), "warn")}` : ""}</div>`
    + `<button class="btn sm" data-do="todoGo" data-v="online" data-p="{}">${t("open")}</button></div></div>`;
}

// v0.8.35: "To do today" on the admin Dashboard: one tap to each thing that is waiting
function todoPanel(d) {
  if (!d) return "";
  const rows = d.items.filter(x => x.key !== "todo_attendance").map(x => `<div class="cl"><div>${tag(String(x.n), x.level === "info" ? "" : x.level === "bad" ? "bad" : "warn")} ${esc(t(x.key))}</div><button class="btn sm" data-do="todoGo" data-v="${esc(x.view)}" data-p="${esc(JSON.stringify(x.patch))}">${t("open")}</button></div>`);
  const cls = d.classes.map(o => `<div class="cl"><div><b>${esc(o.course_name)} · ${esc(o.batch_code)}</b> ${tag(t("No attendance yet"), "warn")}<br><span class="hint"><bdi dir="ltr">${esc(o.start_time)}</bdi> · ${esc(o.teacher_name || "–")}</span></div><button class="btn sm" data-do="todoGo" data-v="classroom" data-p="${esc(JSON.stringify({cb: o.batch_id, ct: "attendance", adate: null}))}">${t("Take attendance")}</button></div>`);
  const all = rows.concat(cls);
  return `<div class="panel" id="todop"><h2>${t("To do today")}</h2>${all.join("") || `<p class="msg ok">${esc(t("todo_all_clear"))}</p>`}</div>`;
}
DO.todoGo = d => { let p = {}; try { p = JSON.parse(d.p || "{}"); } catch (_) {} openTab(d.v, p); return false; };

// ---------- v0.8.47: Who's online. Full admins only (the server sends this tab only to them and checks every call). ----------
// Online = used the portal in the last ~2 minutes; Away = in the last 15 minutes. Refreshes itself every 30 seconds while open.
const ON_ST = {online: ["Online", "ok"], away: ["Away", "warn"], offline: ["Offline", ""]};
const ON_ACC = {paused: ["Paused", "warn"], suspended: ["Suspended", "bad"], disabled: ["Disabled", "bad"]};
function onAgo(stamp, now) {
  if (!stamp) return t("never");
  const s = Math.max(0, (utcDate(now) - utcDate(stamp)) / 1000);
  if (s < 60) return t("just now");
  if (s < 3600) return Math.floor(s / 60) + " " + t("min ago");
  if (s < 86400) return Math.floor(s / 3600) + " " + t("h ago");
  return fmtTime(stamp);
}
const onWarn = (p, lim) => (p.failed_24h >= lim ? tag(t("failed_signins_24h").replace("{n}", p.failed_24h), "warn") + " " : "") + (p.new_device ? tag(t("New device") + ": " + p.new_device, "warn") : "");
views.online = async () => {
  const d = await api("/admin/presence"), f = S.onf = S.onf || {role: "", st: "", q: ""};
  mount(() => {
    ["role", "st"].forEach(k => { const el = $("#on_" + k); if (el) el.onchange = () => { f[k] = el.value; render(); }; });
    const fq = $("#on_qf"); if (fq) fq.onsubmit = ev => { ev.preventDefault(); f.q = val("on_q"); render(); };
  });
  const q = (f.q || "").toLowerCase(), lim = d.failed_warn;
  const list = d.people.filter(p => (!f.role || p.role === f.role)
    && (!f.st || (["online", "away", "offline"].includes(f.st) ? p.status === f.st : f.st === "warnings" ? (p.failed_24h >= lim || p.new_device) : p.account === f.st))
    && (!q || [p.full_name, p.login_id, p.ip].some(v => String(v || "").toLowerCase().includes(q))));
  S.onInfo = Object.fromEntries(d.people.map(p => [p.id, p]));
  const c = d.counts, br = d.by_role;
  const card = (k, v, st) => `<button type="button" class="stat" data-do="onPick" data-v="${st}" aria-pressed="${f.st === st}" style="text-align:start;cursor:pointer;font:inherit${f.st === st ? ";outline:2px solid var(--brand,#0b7)" : ""}"><b><bdi dir="ltr">${fmtNum(v)}</bdi></b>${esc(t(k))}</button>`;
  const cards = `<div class="stats">${card("Online now", c.online, "online")}${card("Away", c.away, "away")}${card("Offline", c.offline, "offline")}${card("Paused", c.paused, "paused")}${card("Suspended", c.suspended, "suspended")}${card("Warnings", c.warnings, "warnings")}</div>`
    + `<p class="hint">${["student", "teacher", "admin"].map(r => `${esc(t(r === "student" ? "Students" : r === "teacher" ? "Teachers" : "Admins"))} ${esc(t("online_count"))}: <b>${br[r].online}</b> / ${br[r].total}`).join(" · ")}</p>`;
  const sel_ = (id, cur, opts) => `<select id="${id}">${opts.map(o => `<option value="${o[0]}" ${o[0] === cur ? "selected" : ""}>${esc(t(o[1]))}</option>`).join("")}</select>`;
  const bar_ = `<form id="on_qf" class="listbar" role="search"><label>${esc(t("role"))}${sel_("on_role", f.role, [["", "all"], ["student", "Students"], ["teacher", "Teachers"], ["admin", "Admins"]])}</label>`
    + `<label>${esc(t("Status"))}${sel_("on_st", f.st, [["", "all"], ["online", "Online"], ["away", "Away"], ["offline", "Offline"], ["paused", "Paused"], ["suspended", "Suspended"], ["disabled", "Disabled"], ["warnings", "Warnings"]])}</label>`
    + `<label>${esc(t("search"))}<input id="on_q" type="search" value="${esc(f.q || "")}" placeholder="${esc(t("Name, login ID or IP"))}"></label><button class="btn">${t("search")}</button></form>`;
  const acts = p => {
    const b = (k, label, cls = "") => `<button type="button" class="btn sm ${cls}" data-do="${k}" data-id="${p.id}">${esc(t(label))}</button>`;
    const hist = b("onHist", "History", "alt");
    if (p.is_self) return `<div class="rowflex"><span class="hint">${esc(t("You"))}</span>${hist}</div>`;
    if (p.account === "disabled") return `<div class="rowflex">${hist}<span class="hint">${esc(t("Turn the account on in People"))}</span></div>`;
    if (p.account !== "active") return `<div class="rowflex">${b("onRestore", "Restore", "alt")}${p.account === "paused" ? b("onSuspend", "Suspend", "danger") : ""}${hist}</div>`;
    return `<div class="rowflex">${b("onKick", "Sign out")}${b("onPause", "Pause")}${b("onSuspend", "Suspend", "danger")}${hist}</div>`;
  };
  const accCell = p => {
    if (p.account === "active") return tag(t("Active"), "ok");
    const [lbl, cls] = ON_ACC[p.account];
    const why = p.account === "paused" ? `${t("until")} ${fmtTime(p.paused_until)}${p.pause_reason ? " · " + p.pause_reason : ""}`
      : p.account === "suspended" ? `${fmtTime(p.suspended_at)}${p.suspend_reason ? " · " + p.suspend_reason : ""}` : "";
    return tag(t(lbl), cls) + (why ? `<br><span class="hint">${esc(why)}</span>` : "") + (p.message ? `<br><span class="hint">${esc(t("Message to the person"))}: ${esc(p.message)}</span>` : "");
  };
  const shown = list.slice(0, S.onlim || 50), canBulk = p => !p.is_self;
  const rows = shown.map(p => {
    const [sl, sc] = ON_ST[p.status], w = onWarn(p, lim);
    return `<tr><td><div>${canBulk(p) ? bulkBox("onl", p.id, p.full_name) + " " : ""}<b>${esc(p.full_name)}</b>${p.full_admin ? " " + tag(t("Full"), "ok") : ""}<br><span class="hint"><bdi dir="ltr">${esc(p.login_id || "")}</bdi></span>${w ? "<br>" + w : ""}</div></td><td>${esc(t(p.role))}</td>`
      + `<td><div>${tag(t(sl), sc)} <span class="hint">${esc(p.status === "online" ? t("now") : onAgo(p.last_seen_at, d.now))}</span></div></td>`
      + `<td><div>${esc(p.device || "–")}${p.ip ? `<br><span class="hint"><bdi dir="ltr">${esc(p.ip)}</bdi></span>` : ""}</div></td><td><bdi dir="ltr">${esc(p.last_login_at ? fmtTime(p.last_login_at) : t("never"))}</bdi></td><td><div>${accCell(p)}</div></td><td>${acts(p)}</td></tr>`;
  }).join("");
  const ids = shown.filter(canBulk).map(p => p.id);
  const bulk = bulkBar("onl", [["onBulkKick", "Sign out"], ["onBulkPause", "Pause"], ["onBulkSuspend", "Suspend", true], ["onBulkRestore", "Restore"]], ids) + bulkAll("onl", ids);
  const table = list.length ? `<table><thead><tr><th>${t("name")}</th><th>${t("role")}</th><th>${t("Status")}</th><th>${t("Device")}</th><th>${t("Last sign-in")}</th><th>${t("Account")}</th><th>${t("actions")}</th></tr></thead><tbody>${rows}</tbody></table>` : `<p>${t("no_match")}</p>`;
  const more = moreBtn(0, Math.min(S.onlim || 50, list.length), list.length, "onMore");
  return `<h1>${t("online")}</h1><p class="hint">${esc(t("online_hint"))}</p>${cards}<div class="panel">${bar_}${bulk}${table}${more}</div>`
    + `<div class="panel"><h2>${esc(t("Sign out everyone"))}</h2><p class="hint">${esc(t("signout_all_hint"))}</p><p><button type="button" class="btn danger" data-do="onKickAll">${esc(t("Sign out everyone"))}…</button></p></div>`
    + `<p class="hint">${esc(t("Updated"))} <bdi dir="ltr">${esc(fmtTime(d.now))}</bdi> · ${esc(t("Times are Maldives time."))} <button type="button" class="btn sm" data-do="onRefresh">${esc(t("Refresh"))}</button></p>`;
};
DO.onMore = () => { S.onlim = (S.onlim || 50) + 50; };
DO.onRefresh = () => {};
DO.onPick = d => { S.onf = S.onf || {}; S.onf.st = S.onf.st === d.v ? "" : d.v; };
const onWho = id => { const p = (S.onInfo || {})[id] || {}; return `${p.full_name || ""}${p.login_id ? " · " + p.login_id : ""} · ${t(p.role || "")}`; };
const onMany = () => t("bulk_n_people").replace("{n}", bulkSel("onl").length);
// the two forms are shared by one person and by the ticked people
const pauseForm = who => ui.form(t("Pause account"), [
  {id: "len", label: t("For how long"), type: "select", value: "24", options: [["1", t("1 hour")], ["24", t("1 day")], ["72", t("3 days")], ["168", t("1 week")], ["720", t("30 days")], ["custom", t("Until a date and time")]]},
  {id: "until", label: t("Until (Maldives time)"), type: "datetime-local", hint: t("Only when you chose 'Until a date and time'.")},
  {id: "reason", label: t("Reason (staff only, optional)"), maxlength: 300},
  {id: "message", label: t("Message to the person (optional)"), maxlength: 200, hint: t("Shown when they try to sign in.")}],
  {okText: t("Pause"), hint: who + ". " + t("pause_hint"), validate: x => x.len === "custom" && !x.until ? t("dlg_required").replace("{f}", t("Until (Maldives time)")) : ""})
  .then(v => v && Object.assign(v.len === "custom" ? {until: v.until} : {hours: +v.len}, {reason: v.reason, message: v.message}));
const suspendForm = who => ui.form(t("Suspend account"), [
  {id: "reason", label: t("Reason (staff only; the person is not shown it)"), type: "textarea", rows: 3, required: true, maxlength: 300},
  {id: "message", label: t("Message to the person (optional)"), maxlength: 200, hint: t("Shown when they try to sign in.")}],
  {okText: t("Suspend"), danger: true, hint: who + ". " + t("suspend_hint")});
DO.onKick = async d => {
  if (!await ui.confirm(t("Sign this person out on every device now? They can sign in again straight away."), {okText: t("Sign out"), details: [onWho(d.id)]})) return false;
  await api(`/admin/accounts/${d.id}/signout`, "POST", {}); flash(t("Signed out"), true);
};
DO.onPause = async d => {
  const v = await pauseForm(onWho(d.id)); if (!v) return false;
  const r = await api(`/admin/accounts/${d.id}/pause`, "POST", v);
  flash(t("Paused until") + " " + fmtTime(r.paused_until), true);
};
DO.onSuspend = async d => {
  const v = await suspendForm(onWho(d.id)); if (!v) return false;
  await api(`/admin/accounts/${d.id}/suspend`, "POST", v); flash(t("Suspended"), true);
};
DO.onRestore = async d => {
  if (!await ui.confirm(t("Let this person sign in again?"), {okText: t("Restore"), details: [onWho(d.id)]})) return false;
  await api(`/admin/accounts/${d.id}/restore`, "POST", {}); flash(t("Restored"), true);
};
// ticked people: one request; the server skips yourself and anyone the action does not fit, and says who
async function onBulk(action, body) {
  const r = await api("/admin/accounts/bulk", "POST", Object.assign({ids: bulkSel("onl"), action}, body || {}));
  S.bulk.onl = [];
  const why = r.skipped.slice(0, 3).map(x => (x.name ? x.name + ": " : "") + x.error).join(" · ");
  flash(t("bulk_done").replace("{n}", r.done).replace("{m}", r.done + r.skipped.length) + (r.skipped.length ? ` ${t("bulk_failed").replace("{n}", r.skipped.length)}: ${why}` : ""), !r.skipped.length);
}
DO.onBulkKick = async () => { if (!await ui.confirm(t("Sign these people out on every device now?"), {okText: t("Sign out"), details: [onMany()]})) return false; await onBulk("signout"); };
DO.onBulkPause = async () => { const v = await pauseForm(onMany()); if (!v) return false; await onBulk("pause", v); };
DO.onBulkSuspend = async () => { const v = await suspendForm(onMany()); if (!v) return false; await onBulk("suspend", v); };
DO.onBulkRestore = async () => { if (!await ui.confirm(t("Let these people sign in again?"), {okText: t("Restore"), details: [onMany()]})) return false; await onBulk("restore"); };
DO.onKickAll = async () => {
  const v = await ui.form(t("Sign out everyone"), [
    {id: "role", label: t("Who"), type: "select", value: "", options: [["", t("Everyone except me")], ["student", t("All students")], ["teacher", t("All teachers")], ["admin", t("All other admins")]]},
    {id: "reason", label: t("Reason (optional)"), maxlength: 300}], {okText: t("Sign out"), danger: true, hint: t("signout_all_hint")});
  if (!v) return false;
  const r = await api("/admin/accounts/signout-all", "POST", v); flash(t("signed_out_n").replace("{n}", r.count), true);
};
// sign-in history of one person: devices, every attempt (good and failed) and the account actions taken
DO.onHist = async d => {
  const h = await api(`/admin/accounts/${d.id}/history`), p = h.person;
  const why = r => r ? t({"wrong password": "Wrong password", "unknown ID": "Unknown ID", "account disabled": "Account disabled", account_paused: "Account paused", account_suspended: "Account suspended"}[r] || r) : "";
  const dev = h.devices.length ? `<table class="nostack"><thead><tr><th>${t("Device")}</th><th>IP</th><th>${t("Sign-ins")}</th><th>${t("Last")}</th></tr></thead><tbody>${h.devices.map(x => `<tr><td>${esc(x.device)}</td><td><bdi dir="ltr">${esc(x.ip)}</bdi></td><td>${x.count}</td><td><bdi dir="ltr">${esc(fmtTime(x.last_at))}</bdi></td></tr>`).join("")}</tbody></table>` : `<p class="hint">${esc(t("No sign-ins yet."))}</p>`;
  const ev = h.events.length ? `<table class="nostack"><thead><tr><th>${t("When")}</th><th>${t("Result")}</th><th>${t("Device")}</th><th>IP</th></tr></thead><tbody>${h.events.map(e => `<tr><td><bdi dir="ltr">${esc(fmtTime(e.at))}</bdi></td><td>${e.ok ? tag(t("Signed in"), "ok") : tag(why(e.reason) || t("Failed"), "bad")}</td><td>${esc(e.device || "–")}</td><td><bdi dir="ltr">${esc(e.ip || "")}</bdi></td></tr>`).join("")}</tbody></table>` : "";
  const acts = h.actions.length ? `<h3>${esc(t("Account actions"))}</h3><ul class="dlg-list">${h.actions.map(a => `<li><bdi dir="ltr">${esc(fmtTime(a.at))}</bdi> · ${esc(a.detail || a.action)}${a.by_login ? ` <span class="hint">(${esc(a.by_login)})</span>` : ""}</li>`).join("")}</ul>` : "";
  await ui.show(t("Sign-in history") + ": " + p.full_name, `<p class="hint"><bdi dir="ltr">${esc(p.login_id || "")}</bdi> · ${esc(t(p.role))}${h.failed_24h ? " · " + esc(t("failed_signins_24h").replace("{n}", h.failed_24h)) : ""}</p><h3>${esc(t("Devices used"))}</h3>${dev}${ev ? `<h3>${esc(t("Recent attempts"))}</h3>${ev}` : ""}${acts}`);
  return false;
};
setInterval(() => {   // keep the list fresh without disturbing typing, an open dialog or ticked boxes
  if (S.view !== "online" || document.hidden || !S.user || document.querySelector("dialog[open]") || (S.bulk && (S.bulk.onl || []).length)) return;
  const a = document.activeElement; if (a && /^(INPUT|SELECT|TEXTAREA)$/.test(a.tagName)) return;
  render();
}, 30000);
