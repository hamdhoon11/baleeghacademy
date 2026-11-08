/* Admin control screens: edit/correct/delete for courses, people (with admin permissions), enrollments, applications,
   and the grouped Settings screen. Loaded last; reuses helpers from index.html and learning.js (api, S, t, esc, $, val, field, flash, render, onSubmit, DO, tag). */
const AREA_LABELS = {admissions: "Admissions", courses: "Courses", batches: "Batches", classroom: "Classroom (attendance, grades)", people: "People", enrollments: "Enrollments", fees: "Fees", settings: "Settings", audit: "Audit log", tutorials: "Tutorials", assignments: "Assignments", progress: "Progress (grades, attendance)", materials: "Materials", create_tutorials: "Create tutorials and see answers", submit_tutorial_work: "Submit tutorial work", class_links: "Class links (Meet links)", recordings: "Recordings (view)", add_recordings: "Add class recordings", student_information: "Student information", teacher_information: "Teacher information", finance: "Finance (expenses)", edit_grades: "Change saved grades", cancel_class: "Cancel classes"};
// which areas exist for each role (the server holds the same list and checks every request against it)
const ROLE_AREAS = {admin: ["admissions", "courses", "batches", "classroom", "people", "enrollments", "fees", "settings", "audit", "tutorials", "create_tutorials", "class_links", "add_recordings", "student_information", "teacher_information", "finance"], teacher: ["classroom", "tutorials", "create_tutorials", "class_links", "add_recordings", "edit_grades", "cancel_class"], student: ["assignments", "progress", "materials", "recordings", "fees", "tutorials", "submit_tutorial_work"]};
const iv = (id, label, v, type = "text", extra = "") => `<label>${esc(t(label))}<input id="${id}" type="${type}" value="${esc(v ?? "")}" ${extra}></label>`;
const sel = (id, label, opts, cur) => `<label>${esc(t(label))}<select id="${id}">${opts.map(o => `<option value="${esc(o[0])}" ${String(o[0]) === String(cur ?? "") ? "selected" : ""}>${esc(o[1])}</option>`).join("")}</select></label>`;
const nv = id => { const v = val(id); return v === "" ? null : v; };
const sure = msg => confirm(msg);
const bar = (...btns) => `<div style="flex:1 1 100%;display:flex;gap:.6rem;flex-wrap:wrap">${btns.join("")}</div>`;

// ---------- courses: edit everything, delete mistakes ----------
views.courses = async () => {
  const c = await api("/courses");
  const e = c.find(x => x.id === S.ec);
  const statuses = [["open", t("open")], ["upcoming", t("upcoming")], ["closed", t("closed")]];
  const kinds = [["course", t("Course")], ["tuition", t("Tuition class")]];
  setTimeout(() => {
    fcWarn("cf"); if (e) fcWarn("ce_f");
    onSubmit("fc", () => api("/courses", "POST", {name: val("cn"), level: val("cl"), kind: val("ck"), code: val("cc") || undefined, monthly_fee_mvr: val("cf"), registration_fee_mvr: val("cg") || 0, textbook: val("ct"), status: val("cs")}));
    if (e) onSubmit("fce", async () => { await api("/courses/" + e.id, "PATCH", {name: val("ce_n"), level: nv("ce_l"), textbook: nv("ce_t"), description: nv("ce_d"), monthly_fee_mvr: val("ce_f") || 0, registration_fee_mvr: val("ce_g") || 0, days_per_week: nv("ce_w"), minutes_per_class: nv("ce_m"), status: val("ce_s"), kind: val("ce_k"), code: val("ce_c") || undefined, is_active: $("#ce_a").checked}); S.ec = null; });
  });
  const editor = e ? `<div class="panel"><h2>${esc(t("edit"))}: ${esc(e.name)}</h2><form class="row" id="fce">${iv("ce_n", "name", e.name)}${iv("ce_l", "level", e.level)}${iv("ce_t", "textbook", e.textbook)}${iv("ce_f", "fee", e.monthly_fee_mvr, "number", 'min="0"')}${iv("ce_g", "Registration fee (one time)", e.registration_fee_mvr || 0, "number", 'min="0"')}${iv("ce_w", "Days per week", e.days_per_week, "number", 'min="1" max="7"')}${iv("ce_m", "Minutes per class", e.minutes_per_class, "number", 'min="1"')}${sel("ce_s", "status", statuses, e.status)}${sel("ce_k", "Type", kinds, e.kind)}${iv("ce_c", "Code", e.code)}<label style="flex:0 0 auto;flex-direction:row;align-items:center;gap:.4rem"><input type="checkbox" id="ce_a" ${e.is_active ? "checked" : ""}> ${esc(t("Active (offered for new enrolments and invoices)"))}</label><label style="flex:1 1 100%">${esc(t("Description"))}<textarea id="ce_d" rows="3">${esc(e.description || "")}</textarea></label>${bar(`<button class="btn alt">${t("save")}</button>`, `<button type="button" class="btn" data-do="ecClose">${t("cancel")}</button>`, `<button type="button" class="btn danger" data-do="ecDel" data-id="${e.id}">${t("delete")}</button>`)}</form><p class="hint">${esc(t("Courses that already have batches cannot be deleted. Set the status to closed instead; the old records stay safe."))}</p></div>` : "";
  return `<h1>${t("courses")}</h1>${editor}<div class="panel">${form("fc", field("cn", "name") + field("cl", "level") + field("ck", "Type", "", kinds) + field("cc", "Code (optional, made from the name)") + field("cf", "fee", "number") + field("cg", "Registration fee (one time)", "number") + field("ct", "textbook") + field("cs", "status", "", statuses))}</div><div class="panel">${c.length ? `<table><thead><tr><th>${t("name")}</th><th>${t("Type")}</th><th>${t("Code")}</th><th>${t("level")}</th><th>${t("fee")}</th><th>${t("status")}</th><th></th></tr></thead><tbody>${c.map(x => `<tr><td>${esc(x.name)}</td><td>${esc(x.kind === "tuition" ? t("Tuition class") : t("Course"))}</td><td>${esc(x.code || "")}</td><td>${esc(x.level || "")}</td><td>${esc(x.monthly_fee_mvr)}</td><td>${esc(x.status)} ${x.is_active ? "" : tag(t("Inactive"), "warn")}</td><td><button class="btn sm" data-do="ecEdit" data-id="${x.id}">${t("edit")}</button></td></tr>`).join("")}</tbody></table>` : `<p>${t("empty")}</p>`}</div>`;
};
// Session 9: a fee of 0 means students in the course get no invoices; say so while the admin types
function fcWarn(id) {
  const el = $("#" + id); if (!el || el.dataset.warn) return; el.dataset.warn = "1";
  const w = document.createElement("div"); w.className = "msg err"; w.style.flex = "1 1 100%"; w.textContent = t("fee_zero_warn");
  el.closest("label").after(w);
  const upd = () => { w.hidden = !(el.value === "" || +el.value <= 0); }; el.addEventListener("input", upd); upd();
}
DO.ecEdit = d => { S.ec = +d.id; };
DO.ecClose = () => { S.ec = null; };
DO.ecDel = async d => { if (!sure(t("Delete this course? This cannot be undone."))) return false; await api("/courses/" + d.id, "DELETE"); S.ec = null; flash(t("saved"), true); };

// ---------- batches: the editor from learning.js gets name, course and delete ----------
DO.saveB = async () => {
  await api("/batches/" + S.eb, "PATCH", {code: val("be_n"), course_id: val("be_c2"), days: pickedDays(), start_time: val("be_t") || null, start_date: val("be_sd") || null, capacity: val("be_c"), teacher_id: val("be_h") || null, status: val("be_s")});
  S.eb = null; flash(t("saved"), true);
};
DO.delB = async d => { if (!sure(t("Delete this batch? This cannot be undone."))) return false; await api("/batches/" + d.id, "DELETE"); S.eb = null; flash(t("saved"), true); };
const batchesBase = views.batches;
views.batches = async () => {
  // fetch our extra data BEFORE calling the base view: the base view schedules DOM work with setTimeout, which must run right after render
  const [b, c, studs, allSt] = S.eb ? await Promise.all([api("/batches"), api("/courses"), api(`/batches/${S.eb}/students`), api("/users?role=student")]) : [[], [], [], []];
  let h = await batchesBase();
  if (!S.eb) return h;
  const e = b.find(x => x.id === S.eb); if (!e) return h;
  const extra = `<div class="row" style="display:flex;flex-wrap:wrap;gap:.6rem;align-items:end;margin-bottom:.8rem">${iv("be_n", "Batch name / code", e.code)}${sel("be_c2", "course", c.filter(x => x.is_active || x.id === e.course_id).map(x => [x.id, x.name + " " + (x.level || "")]), e.course_id)}<button class="btn danger" data-do="delB" data-id="${e.id}">${t("delete")}</button></div>`;
  const inBatch = new Set(studs.map(s => s.id));
  const people = `<div class="panel"><h2>${esc(t("Students in this batch"))} (${studs.filter(s => s.status === "active").length}/${e.capacity})</h2>
    <div class="row" style="display:flex;flex-wrap:wrap;gap:.6rem;align-items:end">${sel("bs_add", "student", [["", "-"], ...allSt.filter(s => s.is_active && !inBatch.has(s.id)).map(s => [s.id, s.full_name + (s.login_id ? " (" + s.login_id + ")" : "")])], "")}<button class="btn alt" data-do="bEnrol" data-id="${e.id}">${esc(t("enroll"))}</button></div>
    ${studs.length ? `<table><thead><tr><th>${t("name")}</th><th>${t("status")}</th><th></th></tr></thead><tbody>${studs.map(s => `<tr><td>${esc(s.full_name)}</td><td>${esc(s.status)}</td><td><button class="btn sm" data-do="bUnenrol" data-id="${s.enrollment_id}">${esc(t("Remove from batch"))}</button></td></tr>`).join("")}</tbody></table>` : `<p>${t("empty")}</p>`}</div>`;
  return h.replace(/(<div class="panel"><h2>[^<]*<\/h2>)/, `$1${extra}`) + people;
};
DO.bEnrol = async d => {   // enrol through the normal enrolment route (capacity, waitlist, inactive course and first invoice are decided there)
  if (!val("bs_add")) throw new Error(t("Choose a student"));
  const r = await api("/enrollments", "POST", {student_id: val("bs_add"), batch_id: d.id});
  flash(r.invoice_message ? t("saved") + ": " + r.invoice_message : t("saved"), true);
};
DO.bUnenrol = async d => { if (!sure(t("Remove this student from the batch? Their records stay."))) return false; const reason = prompt(t("Reason (optional)"), ""); if (reason === null) return false; await api("/enrollments/" + d.id, "PATCH", {status: "dropped", reason}); flash(t("saved"), true); };

// ---------- people: edit anything, permissions for admins, delete mistakes ----------
views.people = async () => {
  const roleF = S.pf || "";
  const u = await api("/users" + (roleF ? "?role=" + roleF : ""));
  const e = S.eu ? await api("/users/" + S.eu).catch(() => null) : null;
  const self = S.user.id, full = !S.user.permissions;
  setTimeout(() => {
    onSubmit("fu", async () => {   // no password typed = the server makes a random one; it is shown once below
      const name = val("un"), r = await api("/users", "POST", {full_name: name, email: val("ue"), password: val("up") || undefined, role: val("ur")});
      if (r.temporary_password) S.tmp = {name, id: r.login_id, pw: r.temporary_password};
    });
    if ($("#pf")) $("#pf").onchange = ev => { S.pf = ev.target.value; render(); };
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
        await api("/users/" + e.id, "PATCH", body); S.eu = null;
      });
    }
  });
  const roles = [["student", t("student")], ["teacher", t("teacher")], ["admin", t("admin")]];
  const prof = !e ? "" : e.role === "student" ? `${iv("eu_date_of_birth", "date_of_birth", e.date_of_birth, "date")}${iv("eu_grade", "Grade / class", e.grade)}${iv("eu_island", "Island", e.island)}${iv("eu_guardian_name", "guardian_name", e.guardian_name)}${iv("eu_guardian_relationship", "Guardian relationship", e.guardian_relationship)}${iv("eu_guardian_phone", "Guardian phone", e.guardian_phone)}`
    : e.role === "teacher" ? `<label style="flex:1 1 100%">${esc(t("Bio"))}<textarea id="eu_bio" rows="3">${esc(e.bio || "")}</textarea></label>` : "";
  const permTitle = {admin: "Admin permissions", teacher: "Teacher permissions", student: "Student permissions"};
  const permAll = {admin: "Full admin (everything, including other admins' permissions)", teacher: "Everything a teacher has", student: "Everything a student has"};
  const perms = e && e.id !== self ? (full ? `<fieldset class="days" style="flex:1 1 100%"><legend>${esc(t(permTitle[e.role]))}</legend><label><input type="radio" name="pm" id="pm_full" ${e.permissions === null ? "checked" : ""}> <span>${esc(t(permAll[e.role]))}</span></label><label><input type="radio" name="pm" id="pm_limited" ${e.permissions !== null ? "checked" : ""}> <span>${esc(t("Limited to the areas ticked below"))}</span></label><div id="pm_box" style="flex:1 1 100%;display:flex;flex-wrap:wrap;gap:.3rem">${ROLE_AREAS[e.role].map(k => `<label><input type="checkbox" name="pa" value="${k}" ${(e.permissions || []).includes(k) ? "checked" : ""}> <span>${esc(t(AREA_LABELS[k]))}</span></label>`).join("")}</div><p class="hint" style="flex:1 1 100%;margin:0">${esc(t("Changing the role resets these permissions. Save the new role first, then set permissions."))}</p></fieldset>` : `<p class="hint">${esc(t("Only a full admin can change permissions."))}</p>`)
    : e && e.id === self ? `<p class="hint">${esc(t("You cannot change your own role or permissions. Ask another full admin."))}</p>` : "";
  const editor = e ? `<div class="panel"><h2>${esc(t("edit"))}: ${esc(e.full_name)} ${tag(e.role)}</h2><form class="row" id="fue">${iv("eu_n", "name", e.full_name)}${iv("eu_l", "Login ID", e.login_id, "text", 'autocomplete="off"')}${iv("eu_e", "email", e.email, "email")}${iv("eu_p", "Phone", e.phone, "tel")}${e.id === self ? "" : sel("eu_r", "role", roles, e.role)}${prof}${perms}${iv("eu_pw", "Set a new password (leave empty to keep)", "", "text", 'autocomplete="off"')}<label style="flex:0 0 auto;flex-direction:row;align-items:center;gap:.4rem"><input type="checkbox" id="eu_mc" ${e.must_change_password ? "checked" : ""}> ${esc(t("Must change password at next sign-in"))}</label><label style="flex:0 0 auto;flex-direction:row;align-items:center;gap:.4rem"><input type="checkbox" id="eu_a" ${e.is_active ? "checked" : ""} ${e.id === self ? "disabled" : ""}> ${esc(t("Account active"))}</label>${bar(`<button class="btn alt">${t("save")}</button>`, `<button type="button" class="btn" data-do="euClose">${t("cancel")}</button>`, e.id === self ? "" : `<button type="button" class="btn" data-do="euReset" data-id="${e.id}">${esc(t("Reset password"))}</button> <button type="button" class="btn danger" data-do="euDel" data-id="${e.id}">${t("delete")}</button>`)}</form><p class="hint">${esc(t("Enrollments") )}: ${e.enrollments} · ${esc(t("Batches taught"))}: ${e.batches_taught}. ${esc(t("People with enrollments, grades or invoices cannot be deleted or change role. Disable the account instead."))}</p></div>` : "";
  const rows = u.map(x => `<tr><td>${esc(x.full_name)}</td><td>${esc(x.login_id || "")}</td><td>${esc(x.email)}</td><td>${esc(x.role)}${x.permissions !== null ? " " + tag(t("Limited"), "warn") : x.role === "admin" ? " " + tag(t("Full"), "ok") : ""}</td><td>${x.is_active ? "✓" : "✗"}</td><td><button class="btn sm" data-do="euEdit" data-id="${x.id}">${t("edit")}</button></td></tr>`).join("");
  return `<h1>${t("people")}</h1>${tmpPanel()}${editor}<div class="panel">${form("fu", field("un", "name") + field("ue", "email", "email") + field("up", "password", "password") + field("ur", "role", "", roles))}</div><div class="panel"><label style="max-width:240px">${esc(t("role"))}<select id="pf"><option value="">${esc(t("All"))}</option>${roles.map(r => `<option value="${r[0]}" ${r[0] === roleF ? "selected" : ""}>${esc(r[1])}</option>`).join("")}</select></label>${u.length ? `<table><thead><tr><th>${t("name")}</th><th>${t("Login ID")}</th><th>${t("email")}</th><th>${t("role")}</th><th>${t("is_active")}</th><th></th></tr></thead><tbody>${rows}</tbody></table>` : `<p>${t("empty")}</p>`}</div>`;
};
DO.euEdit = d => { S.eu = +d.id; window.scrollTo(0, 0); };
DO.euClose = () => { S.eu = null; };
DO.tmpClose = () => { S.tmp = null; };
DO.euReset = async d => {
  if (!sure(t("Make a new temporary password for this person? Their old password stops working."))) return false;
  const r = await api("/users/" + d.id + "/reset-password", "POST");
  S.tmp = {name: "", id: r.login_id, pw: r.temporary_password}; S.eu = null; flash(t("saved"), true);
};
// The temporary password is shown once, only here, and only until "Done" is pressed (the server keeps just a hash and cannot show it again).
function tmpPanel() {
  if (!S.tmp) return "";
  return `<div class="panel" role="alert"><h2>${esc(t("Temporary password"))}${S.tmp.name ? ": " + esc(S.tmp.name) : ""}</h2><p>${esc(t("Login ID"))}: <b>${esc(S.tmp.id || "")}</b><br>${esc(t("password"))}: <b>${esc(S.tmp.pw)}</b></p><p class="hint">${esc(t("Copy this now and give it to the person. It will not be shown again. They must choose their own password at first sign-in."))}</p><button type="button" class="btn alt" data-do="tmpClose">${esc(t("Done"))}</button></div>`;
}
DO.euDel = async d => { if (!sure(t("Delete this account? This cannot be undone."))) return false; await api("/users/" + d.id, "DELETE"); S.eu = null; flash(t("saved"), true); };

// ---------- enrollments: drop, move, delete a mistake ----------
views.enrollments = async () => {
  const [e, st, b, ev] = await Promise.all([api("/enrollments"), api("/users?role=student"), api("/batches"), api("/enrollment-events")]);
  const m = e.find(x => x.id === S.em);
  const hist = `<div class="panel"><h2>${t("Transfers and withdrawals")}</h2><p><button class="btn sm alt" data-do="evCsv">${t("Download CSV")}</button></p>${ev.length ? `<table><thead><tr><th>${t("date")}</th><th>${t("kind")}</th><th>${t("student_name")}</th><th>${t("Previous batch")}</th><th>${t("New batch")}</th><th>${t("Reason")}</th></tr></thead><tbody>${ev.map(x => `<tr><td>${esc(x.effective_date || "?")}</td><td>${esc(t(x.kind === "transfer" ? "Transfer" : "Withdrawal"))}</td><td>${esc(x.student_name)} <span class="hint">${esc(x.student_code || "")}</span></td><td>${esc((x.from_course || "") + " " + (x.from_batch_code || ""))}</td><td>${esc((x.to_course || "") + " " + (x.to_batch_code || ""))}</td><td>${esc(x.reason || "")}</td></tr>`).join("")}</tbody></table>` : `<p class="hint">${t("empty")}</p>`}</div>`;
  const bo = b.filter(x => x.course_active).map(x => [x.id, x.course_name + " " + x.code]);   // inactive courses are not offered for new enrolments
  setTimeout(() => onSubmit("fe", () => api("/enrollments", "POST", {student_id: val("es"), batch_id: val("eb")})));
  const mover = m ? `<div class="panel"><h2>${esc(m.student_name)}: ${esc(m.course_name)} ${esc(m.batch_code)}</h2><div class="row" style="display:flex;flex-wrap:wrap;gap:.6rem;align-items:end">${sel("em_b", "Move to batch", bo.filter(x => x[0] !== m.batch_id), "")}<button class="btn" data-do="emMove" data-id="${m.id}">${t("Move")}</button><button class="btn alt" data-do="emSet" data-id="${m.id}" data-s="completed">${t("Mark completed")}</button><button class="btn alt" data-do="emSet" data-id="${m.id}" data-s="active">${t("Mark active")}</button><button class="btn alt" data-do="emSet" data-id="${m.id}" data-s="waitlist">${t("Waitlist")}</button><button class="btn danger" data-do="emDel" data-id="${m.id}">${t("delete")}</button><button class="btn" data-do="emClose">${t("cancel")}</button></div><p class="hint">${esc(t("Delete is only for enrollments added by mistake. If invoices exist, use Dropped to keep the history."))}</p></div>` : "";
  return `<h1>${t("enrollments")}</h1>${mover}<div class="panel">${form("fe", field("es", "student", "", st.map(x => [x.id, x.full_name])) + field("eb", "batch", "", bo), "enroll")}</div><div class="panel">${e.length ? `<table><thead><tr><th>${t("student_name")}</th><th>${t("course_name")}</th><th>${t("batch_code")}</th><th>${t("status")}</th><th></th></tr></thead><tbody>${e.map(r => `<tr><td>${esc(r.student_name)}</td><td>${esc(r.course_name)}</td><td>${esc(r.batch_code)}</td><td>${esc(r.status)}</td><td>${["active", "waitlist"].includes(r.status) ? `<button class="btn sm" data-do="emSet" data-id="${r.id}" data-s="dropped">${t("drop")}</button> ` : ""}<button class="btn sm" data-do="emEdit" data-id="${r.id}">${t("edit")}</button></td></tr>`).join("")}</tbody></table>` : `<p>${t("empty")}</p>`}</div>${hist}`;
};
DO.emEdit = d => { S.em = +d.id; window.scrollTo(0, 0); };
DO.emClose = () => { S.em = null; };
DO.emSet = async d => { let reason; if (d.s === "dropped") { reason = prompt(t("Reason (optional)"), ""); if (reason === null) return false; } await api("/enrollments/" + d.id, "PATCH", {status: d.s, reason}); S.em = null; flash(t("saved"), true); };
DO.emMove = async d => { const reason = prompt(t("Reason (optional)"), ""); if (reason === null) return false; await api("/enrollments/" + d.id, "PATCH", {transfer_to_batch_id: val("em_b"), reason}); S.em = null; flash(t("saved"), true); };
DO.evCsv = () => fetchFile("/enrollment-events.csv", {name: "transfers-withdrawals.csv"});
DO.emDel = async d => { if (!sure(t("Delete this enrollment? This cannot be undone."))) return false; await api("/enrollments/" + d.id, "DELETE"); S.em = null; flash(t("saved"), true); };

// ---------- admissions: correct an application's details ----------
const admBase = views.admissions;
views.admissions = async () => {
  const [a, courses, bs] = S.sel ? await Promise.all([api("/applications/" + S.sel), api("/courses"), api("/batches")]) : [null, [], []];
  let h = await admBase();   // after our fetches (see batches note above)
  if (!a || !["pending", "waitlist"].includes(a.status)) return h;
  setTimeout(() => onSubmit("fa", async () => { await api("/applications/" + a.id, "PATCH", {full_name: val("fa_n"), date_of_birth: val("fa_d"), phone: val("fa_p"), email: val("fa_e"), island: nv("fa_i"), grade: nv("fa_g"), course_id: val("fa_c"), batch_id: nv("fa_b"), guardian_name: nv("fa_gn"), guardian_relationship: nv("fa_gr"), guardian_phone: nv("fa_gp")}); }));
  const bopts = [["", "-"], ...bs.filter(x => x.course_id === a.course_id).map(x => [x.id, x.code])];
  return h + `<div class="panel"><h2>${esc(t("Correct details"))}</h2><form class="row" id="fa">${iv("fa_n", "name", a.full_name)}${iv("fa_d", "date_of_birth", a.date_of_birth, "date")}${iv("fa_p", "Phone", a.phone, "tel")}${iv("fa_e", "email", a.email, "email")}${iv("fa_i", "Island", a.island)}${iv("fa_g", "Grade / class", a.grade)}${sel("fa_c", "course", courses.filter(x => x.is_active || x.id === a.course_id).map(x => [x.id, x.name + " " + (x.level || "")]), a.course_id)}${sel("fa_b", "batch", bopts, a.batch_id)}${a.is_minor ? iv("fa_gn", "guardian_name", a.guardian_name) + iv("fa_gr", "Guardian relationship", a.guardian_relationship) + iv("fa_gp", "Guardian phone", a.guardian_phone) : ""}<button class="btn alt">${t("save")}</button></form><p class="hint">${esc(t("If you change the course, pick the batch again after saving."))}</p></div>`;
};

// ---------- settings: grouped, typed, with defaults and hints ----------
views.settings = async () => {
  const sc = await api("/settings/schema");
  const gid = S.sg || sc.groups[0].id;
  const g = sc.groups.find(x => x.id === gid) || sc.groups[0];
  const input = it => {
    const id = "set_" + it.key, v = it.value || "";
    const dflt = it.default ? `${t("Default")}: ${it.default}` : "";
    let ctl;
    if (it.type === "longtext") ctl = `<textarea id="${id}" rows="3" placeholder="${esc(it.default)}">${esc(v)}</textarea>`;
    else if (it.type === "bool") ctl = `<select id="${id}"><option value="1" ${(v || it.default) !== "0" ? "selected" : ""}>${esc(t("On"))}</option><option value="0" ${(v || it.default) === "0" ? "selected" : ""}>${esc(t("Off"))}</option></select>`;
    else if (it.type === "select") ctl = `<select id="${id}">${it.options.map(o => `<option value="${esc(o)}" ${(v || it.default) === o ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
    else ctl = `<input id="${id}" type="${it.type === "number" ? "number" : it.type === "email" ? "email" : it.type === "url" ? "url" : "text"}" value="${esc(v)}" placeholder="${esc(it.default)}" ${it.min != null ? `min="${it.min}"` : ""} ${it.max != null ? `max="${it.max}"` : ""}>`;
    return `<div class="sub"><label style="flex:1 1 100%"><b>${esc(t(it.label))}</b>${ctl}</label><span class="hint">${esc(it.hint ? t(it.hint) + " " : "")}${esc(dflt)}</span></div>`;
  };
  DO.saveSet = async () => {
    const body = {}; for (const it of g.items) body[it.key] = val("set_" + it.key);
    await api("/settings", "PUT", body); flash(t("saved"), true);
  };
  return `<h1>${t("settings")}</h1><div class="subtabs" role="tablist">${sc.groups.map(x => `<button data-do="setTab" data-g="${x.id}" ${x.id === g.id ? 'aria-current="true"' : ""}>${esc(t(x.title))}</button>`).join("")}</div><div class="panel" style="margin-top:1rem"><h2>${esc(t(g.title))}</h2>${g.hint ? `<p class="hint">${esc(t(g.hint))}</p>` : ""}${g.items.map(input).join("")}<p><button class="btn" data-do="saveSet">${t("save")}</button></p><p class="hint">${esc(t("Empty fields use the default. Every change is written to the audit log."))}</p></div>`;
};
DO.setTab = d => { S.sg = d.g; };

// ---------- student information (Session 6): admins find a student and see profile, batches, attendance, grades and fees in one place ----------
const siMoney = n => "MVR " + (n || 0).toLocaleString("en-US");
DO.siOpen = d => { S.si = +d.id; };
DO.siBack = () => { S.si = null; };
DO.siMore = () => { S.silimit = (S.silimit || 30) + 30; };
const siList = async () => {
  const f = S.sif || {}, q = new URLSearchParams({limit: S.silimit || 30});
  if (f.q) q.set("q", f.q); if (f.batch) q.set("batch_id", f.batch); if (f.status) q.set("status", f.status);
  const [r, bs] = await Promise.all([api("/student-information?" + q), S.sibatches ? S.sibatches : api("/batches").then(b => (S.sibatches = b)).catch(() => [])]);
  setTimeout(() => { const ff = $("#sif"); if (ff) { $("#sif_b").value = f.batch || ""; $("#sif_s").value = f.status || ""; ff.onsubmit = e => { e.preventDefault(); S.sif = {q: val("sif_q"), batch: val("sif_b"), status: val("sif_s")}; S.silimit = 30; render(); }; } });
  return `<h1>${t("student_information")}</h1><p class="hint">${t("si_intro")}</p>
    <div class="panel"><form id="sif" class="row"><label>${t("search")}<input id="sif_q" value="${esc(f.q || "")}" placeholder="${esc(t("si_search_hint"))}"></label>
      <label>${t("batch")}<select id="sif_b"><option value="">${t("si_all_batches")}</option>${bs.map(b => `<option value="${b.id}">${esc(b.course_name)} · ${esc(b.code)}</option>`).join("")}</select></label>
      <label>${t("status")}<select id="sif_s"><option value="">${t("si_any")}</option><option value="active">${t("si_active")}</option><option value="inactive">${t("si_inactive")}</option></select></label>
      <button class="btn">${t("search")}</button></form></div>
    <div class="panel"><p>${["csv", "xlsx"].map(x => `<button class="btn sm alt" data-do="siExp" data-ext="${x}">${x === "csv" ? t("Download CSV") : t("Download Excel")}</button>`).join(" ")} <button class="btn sm alt" data-do="siExpEn">${t("Enrolments CSV")}</button></p></div>
    <div class="panel"><p class="hint">${r.students.length} / ${r.total}</p>${r.students.map(s => `<div class="cl"><div><b>${esc(s.full_name)}</b> ${s.is_active ? "" : tag(t("si_inactive"), "bad")}<br><span class="hint">${esc(s.email)}${s.phone ? " · <bdi dir=\"ltr\">" + esc(s.phone) + "</bdi>" : ""}</span><br>${s.batches.length ? esc(s.batches.join(", ")) : `<span class="hint">${t("si_no_batches")}</span>`}</div>
      <div>${s.balance_due ? tag(siMoney(s.balance_due), "warn") + " " : ""}<button class="btn sm" data-do="siOpen" data-id="${s.id}">${t("open")}</button></div></div>`).join("") || `<p>${t("empty")}</p>`}
      ${r.students.length < r.total ? `<p><button class="btn" data-do="siMore">${t("load_more")}</button></p>` : ""}</div>`;
};
const siDetail = async id => {
  const r = await api("/student-information/" + id), p = r.profile;
  const kv = (k, v) => v ? `<p><span class="hint">${t(k)}</span><br>${esc(v)}</p>` : "";
  const prof = `<div class="panel"><h2>${esc(p.full_name)} ${p.is_active ? "" : tag(t("si_inactive"), "bad")}</h2>
    <div class="stats"><div class="stat"><b>${r.enrollments.filter(e => e.status === "active").length}</b>${t("si_active_batches")}</div>${r.fees_visible ? `<div class="stat"><b>${siMoney(r.fees.balance_due)}</b>${t("si_balance_due")}${r.fees.overdue_count ? "<br>" + tag(r.fees.overdue_count + " " + t("overdue"), "bad") : ""}</div>` : ""}</div>
    ${kv("email", p.email)}${kv("phone", p.phone)}${kv("date_of_birth", p.date_of_birth)}${kv("Grade / class", p.grade)}${kv("island", p.island)}${kv("guardian_name", p.guardian_name)}${kv("guardian_relationship", p.guardian_relationship)}${kv("guardian_phone", p.guardian_phone)}${kv("si_joined", (p.created_at || "").slice(0, 10))}</div>`;
  const batches = `<div class="panel"><h2>${t("batches")}</h2>${r.enrollments.map(e => `<div class="cl"><div><b>${esc(e.course_name)} · ${esc(e.code)}</b><br><span class="hint">${esc(e.teacher_name || "–")} · <bdi dir="ltr">${esc((e.enrolled_at || "").slice(0, 10))}</bdi></span></div>${tag(t("si_enr_" + e.status), e.status === "active" ? "ok" : e.status === "dropped" ? "bad" : "")}</div>`).join("") || `<p>${t("empty")}</p>`}</div>`;
  const prog = r.progress.map(c => { const a = c.attendance;
    return `<div class="panel"><h2>${esc(c.course_name)} · ${esc(c.batch_code)}</h2>
      <div class="stats"><div class="stat"><b>${pct(a.pct)}</b>${t("attendance_pct")} ${a.low ? tag(t("low_attendance"), "bad") : ""}<br><small>${t("present")} ${a.present} · ${t("late")} ${a.late} · ${t("absent")} ${a.absent} · ${t("excused")} ${a.excused}</small></div><div class="stat"><b>${pct(c.avg_pct)}</b>${t("avg_pct")}</div></div>
      <p>${c.recent.map(x => tag(x.date.slice(5) + " " + t(x.status), x.status === "absent" ? "bad" : x.status === "present" ? "ok" : "")).join(" ") || t("empty")}</p>
      ${c.items.length ? `<table><thead><tr><th>${t("title")}</th><th>${t("kind")}</th><th>${t("due_date")}</th><th>${t("grade")}</th></tr></thead><tbody>${c.items.map(i => `<tr><td>${esc(i.title)}</td><td>${t(i.kind)}</td><td>${esc(i.due_date || "–")}</td><td>${i.grade != null ? i.grade + "/" + i.max_points : t("not_graded_yet")}${i.feedback ? `<br><small>${esc(i.feedback)}</small>` : ""}</td></tr>`).join("")}</tbody></table>` : ""}</div>`; }).join("");
  const fees = !r.fees_visible ? `<div class="panel"><h2>${t("fees")}</h2><p class="hint">${t("si_fees_hidden")}</p></div>` : `<div class="panel"><h2>${t("fees")}</h2>
    ${r.fees.invoices.length ? `<table><thead><tr><th>${t("si_period")}</th><th>${t("due_date")}</th><th>${t("si_due")}</th><th>${t("si_paid")}</th><th>${t("status")}</th></tr></thead><tbody>${r.fees.invoices.map(i => `<tr><td><bdi dir="ltr">${esc(i.period)}</bdi></td><td><bdi dir="ltr">${esc(i.due_date)}</bdi></td><td>${siMoney(i.amount_due_mvr)}</td><td>${siMoney(i.paid_mvr)}</td><td>${i.overdue ? tag(t("overdue"), "bad") : tag(t("si_inv_" + i.status), i.status === "paid" ? "ok" : "warn")}</td></tr>`).join("")}</tbody></table>` : `<p>${t("empty")}</p>`}
    ${r.fees.payments.length ? `<h3>${t("si_payments")}</h3>${r.fees.payments.map(x => `<div class="cl"><div><b>${esc(x.receipt_no)}</b> ${x.reversed_at ? tag(t("si_reversed"), "bad") : ""}<br><span class="hint"><bdi dir="ltr">${esc(x.paid_on)}</bdi> · ${esc(x.period)} · ${esc(x.method)}</span></div><b>${siMoney(x.amount_mvr)}</b></div>`).join("")}` : ""}</div>`;
  return `<h1>${t("student_information")}</h1><p><button class="btn sm alt" data-do="siBack">${t("back")}</button></p>${prof}${batches}<h2>${t("si_attendance_grades")}</h2>${prog || `<div class="panel"><p>${t("empty")}</p></div>`}${fees}`;
};
views.student_information = async () => S.si ? siDetail(S.si).catch(x => { S.si = null; throw x; }) : siList();

// ---------- teacher information (Session 7): admins find a teacher and see profile, batches taught, students and workload ----------
DO.tiOpen = d => { S.ti = +d.id; };
DO.tiBack = () => { S.ti = null; };
DO.tiMore = () => { S.tilimit = (S.tilimit || 30) + 30; };
const tiList = async () => {
  const f = S.tif || {}, q = new URLSearchParams({limit: S.tilimit || 30});
  if (f.q) q.set("q", f.q); if (f.status) q.set("status", f.status);
  const r = await api("/teacher-information?" + q);
  setTimeout(() => { const ff = $("#tif"); if (ff) { $("#tif_s").value = f.status || ""; ff.onsubmit = e => { e.preventDefault(); S.tif = {q: val("tif_q"), status: val("tif_s")}; S.tilimit = 30; render(); }; } });
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
  const prof = `<div class="panel"><h2>${esc(p.full_name)} ${p.is_active ? "" : tag(t("si_inactive"), "bad")}</h2>${kv("email", p.email)}${kv("phone", p.phone)}${kv("Bio", p.bio)}${kv("si_joined", (p.created_at || "").slice(0, 10))}</div>`;
  const load = `<div class="panel"><h2>${t("ti_workload")}</h2><div class="stats">
    <div class="stat"><b>${w.active_batches}</b>${t("ti_active_batches")}</div><div class="stat"><b>${w.students}</b>${t("students")}</div>
    <div class="stat"><b>${w.weekly_classes}</b>${t("ti_classes_week")}</div><div class="stat"><b><bdi dir="ltr">${w.weekly_hours}</bdi></b>${t("ti_hours_week")}</div>
    <div class="stat"><b>${w.classes_held_30d}</b>${t("ti_held_30d")}</div><div class="stat"><b>${w.to_grade}</b>${t("pending_grading")}</div></div></div>`;
  const batches = `<div class="panel"><h2>${t("batches")}</h2>${r.batches.map(b => `<div class="cl"><div><b>${esc(b.course_name)} · ${esc(b.code)}</b> ${tag(b.status, b.status === "closed" ? "" : "ok")}<br><span class="hint">${esc(b.days ? b.days.split(",").map(dayName).join(", ") : "–")} · <bdi dir="ltr">${esc(b.start_time || "–")}</bdi> · ${b.minutes} min</span></div><div>${b.students} / ${b.capacity}</div></div>`).join("") || `<p>${t("empty")}</p>`}</div>`;
  const studs = `<div class="panel"><h2>${t("students")} (${r.students.length})</h2>${r.students.map(s => `<div class="cl"><div><b>${esc(s.full_name)}</b><br><span class="hint">${esc(s.batches.join(", "))}</span></div></div>`).join("") || `<p>${t("empty")}</p>`}</div>`;
  return `<h1>${t("teacher_information")}</h1><p><button class="btn sm alt" data-do="tiBack">${t("back")}</button></p>${prof}${load}${batches}${studs}`;
};
views.teacher_information = async () => S.ti ? tiDetail(S.ti).catch(x => { S.ti = null; throw x; }) : tiList();

// ---------- Activity log (Session 21): filters, paging, drill-down, CSV. Read only: there is no edit or delete anywhere. ----------
const AL_PER = 50, AL_KEYS = ["user_id", "login_id", "role", "action", "batch_id", "date_from", "date_to", "q"];
const alQuery = (extra = {}) => { const f = {...(S.al ? S.al.f : {}), ...extra}; return Object.keys(f).filter(k => f[k] !== "" && f[k] != null).map(k => encodeURIComponent(k) + "=" + encodeURIComponent(f[k])).join("&"); };
views.audit = async () => {
  S.al = S.al || {page: 1, f: {}};
  const q = alQuery({page: S.al.page, per_page: AL_PER});
  const drill = S.al.f.user_id || S.al.f.batch_id;
  const [r, acts, b, sm] = await Promise.all([api("/audit?" + q), api("/audit/actions"), api("/batches"), drill ? api("/audit/summary?" + alQuery()) : null]);
  const f = S.al.f;
  setTimeout(() => {
    AL_KEYS.forEach(k => { const el = $("#al_" + k); if (el && f[k] != null) el.value = f[k]; });
    onSubmit("fal", async () => { S.al = {page: 1, f: Object.fromEntries(AL_KEYS.filter(k => !["user_id"].includes(k) && val("al_" + k) !== "").map(k => [k, val("al_" + k)])) }; });
  });
  const roles = [["", t("all")], ...["admin", "teacher", "student", "system", "anonymous"].map(x => [x, x])];
  const filters = form("fal", field("al_login_id", "Login ID") + field("al_role", "role", "text", roles) + field("al_action", "action", "text", [["", t("all")], ...acts.map(x => [x, x])])
    + field("al_batch_id", "batch", "text", [["", t("all")], ...b.map(x => [x.id, x.course_name + " " + x.code])]) + field("al_date_from", "From", "date") + field("al_date_to", "To", "date") + field("al_q", "Words in detail"), "Filter");
  const chips = sm ? `<div class="panel"><h2>${t("What has this " + (f.user_id ? "user" : "batch") + " done?")}</h2><p>${sm.total} ${t("actions")}${sm.first_at ? ` · ${esc(sm.first_at)} → ${esc(sm.last_at)}` : ""}</p><p>${sm.by_action.map(x => `<span class="chip">${esc(x.action)}: ${x.n}</span>`).join(" ")}</p>${f.batch_id ? `<p>${sm.by_user.map(x => `${esc(x.user_name || "?")} (${esc(x.user_role || "")}): ${x.n}`).join(" · ")}</p>` : ""}<p><button class="btn sm alt" data-do="alClear">${t("Show everything again")}</button></p></div>` : "";
  const extra = x => (x.user_id ? `<button class="btn sm alt" data-do="alUser" data-id="${x.user_id}">${t("This user")}</button> ` : "") + (x.batch_id ? `<button class="btn sm alt" data-do="alBatch" data-id="${x.batch_id}">${t("This batch")}</button>` : "");
  const nav = `<p><button class="btn sm alt" data-do="alPage" data-n="-1" ${S.al.page <= 1 ? "disabled" : ""}>${t("Previous")}</button> ${t("Page")} ${S.al.page} <button class="btn sm alt" data-do="alPage" data-n="1" ${r.length < AL_PER ? "disabled" : ""}>${t("Next")}</button> <button class="btn sm alt" data-do="alCsv">${t("Download CSV")}</button></p>`;
  return `<h1>${t("audit")}</h1><div class="panel">${filters}</div>${chips}<div class="panel">${nav}${table(["at", "user_name", "user_role", "login_id", "action", "entity", "batch_id", "old_value", "new_value", "detail"], r, extra)}${nav}</div>`;
};
DO.alUser = d => { S.al = {page: 1, f: {user_id: d.id}}; window.scrollTo(0, 0); };
DO.alBatch = d => { S.al = {page: 1, f: {batch_id: d.id}}; window.scrollTo(0, 0); };
DO.alClear = () => { S.al = {page: 1, f: {}}; };
DO.alPage = d => { S.al.page = Math.max(1, S.al.page + (+d.n)); };
DO.alCsv = () => fetchFile("/audit.csv?" + alQuery(), {name: "activity-log.csv"});

// ---------- Substitute teachers (Session 22): a panel under the batch being edited ----------
const batchesNoSubs = views.batches;
views.batches = async () => {
  const [subs, teachers] = S.eb ? await Promise.all([api("/substitutions?batch_id=" + S.eb), api("/users?role=teacher")]) : [[], []];   // fetched before the base view, which schedules DOM work
  const h = await batchesNoSubs();
  if (!S.eb) return h;
  setTimeout(() => onSubmit("fsub", async () => {
    await api("/substitutions", "POST", {batch_id: S.eb, substitute_teacher_id: val("sb_t"), class_date: val("sb_from"), ends_on: val("sb_to") || null, reason: val("sb_r")});
  }));
  const rows = subs.map(r => `<tr><td>${esc(r.substitute_teacher)}</td><td>${esc(r.class_date)}${r.last_day !== r.class_date ? " → " + esc(r.last_day) : ""}</td><td>${esc(r.reason || "")}</td><td>${esc(t(r.state))}</td><td>${r.state === "active" || r.state === "upcoming" ? `<button class="btn sm" data-do="subRemove" data-id="${r.id}">${t("Remove")}</button>` : ""}</td></tr>`).join("");
  const panel = `<div class="panel"><h2>${t("Substitute teachers")}</h2><p class="hint">${t("A substitute can see this batch's class students, join link and attendance only on the dates you choose. The batch keeps its own teacher.")}</p>`
    + form("fsub", field("sb_t", "Substitute teacher", "text", [["", "-"], ...teachers.filter(x => x.is_active).map(x => [x.id, x.full_name])]) + field("sb_from", "From", "date") + field("sb_to", "To (empty = one day)", "date") + field("sb_r", "Reason"), "Add")
    + (subs.length ? `<table><thead><tr><th>${t("Substitute teacher")}</th><th>${t("date")}</th><th>${t("Reason")}</th><th>${t("status")}</th><th></th></tr></thead><tbody>${rows}</tbody></table>` : "") + "</div>";
  return h + panel;
};
DO.subRemove = async d => { if (!sure(t("End this substitution now? The teacher loses access at once."))) return false; await api("/substitutions/" + d.id, "DELETE"); };

// ---------- Finance (Session 23): expenses, categories, receipts. Needs the "finance" area; the server refuses everyone else. ----------
const FN_KEYS = ["category_id", "date_from", "date_to", "q"];
const fnQuery = (extra = {}) => { const f = {...(S.fn ? S.fn.f : {}), ...extra}; return Object.keys(f).filter(k => f[k] !== "" && f[k] != null).map(k => encodeURIComponent(k) + "=" + encodeURIComponent(f[k])).join("&"); };
views.finance = async () => {
  S.fn = S.fn || {page: 1, f: {}, edit: null};
  const [r, cats] = await Promise.all([api("/expenses?" + fnQuery({page: S.fn.page, per_page: 50})), api("/expense-categories")]);
  const f = S.fn.f, ed = S.fn.edit ? r.items.find(x => x.id === S.fn.edit) : null;
  const active = cats.filter(k => k.is_active || (ed && k.id === ed.category_id));
  setTimeout(() => {
    FN_KEYS.forEach(k => { const el = $("#fn_" + k); if (el && f[k] != null) el.value = f[k]; });
    if (ed) { $("#fx_date").value = ed.expense_date; $("#fx_amt").value = ed.amount_mvr; $("#fx_cat").value = ed.category_id; $("#fx_desc").value = ed.description || ""; }
    onSubmit("ffn", async () => { S.fn = {page: 1, f: Object.fromEntries(FN_KEYS.filter(k => val("fn_" + k) !== "").map(k => [k, val("fn_" + k)])), edit: null}; });
    onSubmit("fex", async () => {
      const fd = new FormData();
      fd.append("expense_date", val("fx_date")); fd.append("amount_mvr", val("fx_amt")); fd.append("category_id", val("fx_cat")); fd.append("description", val("fx_desc"));
      const file = $("#fx_file").files[0]; if (file) fd.append("file", file);
      if (ed && $("#fx_rm") && $("#fx_rm").checked) fd.append("remove_receipt", "1");
      await apiForm(ed ? "/expenses/" + ed.id : "/expenses", fd, ed ? "PATCH" : "POST"); S.fn.edit = null;
    });
    onSubmit("fcat", async () => { await api("/expense-categories", "POST", {name: val("fc_name")}); });
  });
  const filters = form("ffn", field("fn_category_id", "Category", "text", [["", t("all")], ...cats.map(k => [k.id, k.name])]) + field("fn_date_from", "From", "date") + field("fn_date_to", "To", "date") + field("fn_q", "Words in description"), "Filter");
  const entry = `<form class="row" id="fex">${field("fx_date", "Expense date", "date").replace("<input", `<input value="${mvToday()}" max="${mvToday()}" required`)}`
    + field("fx_amt", "Amount (MVR)", "number").replace("<input", '<input min="1" step="1" inputmode="numeric" required')
    + field("fx_cat", "Category", "text", active.map(k => [k.id, k.name])) + field("fx_desc", "Description")
    + `<label>${t("Receipt (PDF, JPG or PNG)")}<input id="fx_file" type="file" accept=".pdf,.jpg,.jpeg,.png"></label>`
    + (ed && ed.has_receipt ? `<label><input id="fx_rm" type="checkbox"> ${t("Remove the current receipt")}</label>` : "")
    + `<button class="btn alt">${t(ed ? "Save" : "Add expense")}</button>${ed ? ` <button type="button" class="btn" data-do="fnCancel">${t("Cancel")}</button>` : ""}</form>`;
  const body = r.items.map(x => `<tr><td>${esc(x.expense_date)}</td><td>${esc(x.category)}</td><td>${esc(x.description || "")}</td><td><bdi dir="ltr">${esc(x.amount_mvr)}</bdi></td><td>${x.has_receipt ? `<button class="btn sm alt" data-do="fnReceipt" data-id="${x.id}" data-name="${esc(x.receipt_name || "receipt")}">${t("Receipt")}</button>` : ""}</td>`
    + `<td><button class="btn sm alt" data-do="fnEdit" data-id="${x.id}">${t("Edit")}</button> <button class="btn sm" data-do="fnDel" data-id="${x.id}">${t("Delete")}</button></td></tr>`).join("");
  const nav = `<p><button class="btn sm alt" data-do="fnPage" data-n="-1" ${S.fn.page <= 1 ? "disabled" : ""}>${t("Previous")}</button> ${t("Page")} ${S.fn.page} <button class="btn sm alt" data-do="fnPage" data-n="1" ${r.page * r.per_page >= r.count ? "disabled" : ""}>${t("Next")}</button></p>`;
  const catRows = cats.map(k => `<span class="chip">${esc(k.name)} (${k.expense_count})${k.is_active ? "" : " · " + t("inactive")} <button class="btn sm alt" data-do="fnCatToggle" data-id="${k.id}" data-on="${k.is_active ? 0 : 1}">${t(k.is_active ? "Make inactive" : "Make active")}</button> <button class="btn sm alt" data-do="fnCatRename" data-id="${k.id}" data-name="${esc(k.name)}">${t("Rename")}</button>${k.expense_count ? "" : ` <button class="btn sm" data-do="fnCatDel" data-id="${k.id}">${t("Delete")}</button>`}</span>`).join(" ");
  return `<h1>${t("finance")}</h1><div class="panel"><h2>${t(ed ? "Edit expense" : "Add expense")}</h2>${cats.some(k => k.is_active) ? entry : `<p>${t("Add a category first.")}</p>`}</div>`
    + `<div class="panel"><h2>${t("Categories")}</h2><p>${catRows || t("empty")}</p>${form("fcat", field("fc_name", "Category name"), "Add category")}</div>`
    + `<div class="panel"><h2>${t("Expenses")}</h2>${filters}<p><b>${r.count}</b> ${t("expenses")} · ${t("Total")}: <b><bdi dir="ltr">MVR ${esc(r.total_mvr)}</bdi></b></p>${nav}`
    + (r.items.length ? `<table><thead><tr><th>${t("date")}</th><th>${t("Category")}</th><th>${t("Description")}</th><th>MVR</th><th></th><th></th></tr></thead><tbody>${body}</tbody></table>` : `<p>${t("empty")}</p>`) + `${nav}</div>`;
};
DO.fnPage = d => { S.fn.page = Math.max(1, S.fn.page + (+d.n)); };
DO.fnEdit = d => { S.fn.edit = +d.id; window.scrollTo(0, 0); };
DO.fnCancel = () => { S.fn.edit = null; };
DO.fnReceipt = async d => { await viewFile("/expenses/" + d.id + "/receipt", d.name); return false; };
DO.fnDel = async d => { if (!sure(t("Delete this expense? The activity log keeps a record of it."))) return false; await api("/expenses/" + d.id, "DELETE"); };
DO.fnCatToggle = async d => { await api("/expense-categories/" + d.id, "PATCH", {is_active: +d.on}); };
DO.fnCatRename = async d => { const n = prompt(t("Category name"), d.name); if (!n) return false; await api("/expense-categories/" + d.id, "PATCH", {name: n}); };
DO.fnCatDel = async d => { if (!sure(t("Delete this category?"))) return false; await api("/expense-categories/" + d.id, "DELETE"); };

// ---------- Finance dashboard and revenue (Session 24): sits above the expenses screen. Revenue = real payments only. ----------
const fnBase = views.finance;
const fnMoney = n => `<bdi dir="ltr">MVR ${esc(n)}</bdi>`;
views.finance = async () => {
  S.fr = S.fr || {f: {}};
  const q = Object.keys(S.fr.f).filter(k => S.fr.f[k]).map(k => k + "=" + encodeURIComponent(S.fr.f[k])).join("&");
  const [dash, rev, courses, batches] = await Promise.all([api("/finance/dashboard?" + q.replace(/course_id=\d+&?|batch_id=\d+&?|kind=\w+&?/g, "")), api("/finance/revenue?" + q), api("/courses"), api("/batches")]);
  const base = await fnBase();   // fetched after the data above: it schedules its own DOM work
  const f = S.fr.f;
  setTimeout(() => {
    ["date_from", "date_to", "course_id", "batch_id", "kind"].forEach(k => { const el = $("#fr_" + k); if (el && f[k]) el.value = f[k]; });
    onSubmit("ffr", async () => { S.fr = {f: Object.fromEntries(["date_from", "date_to", "course_id", "batch_id", "kind"].filter(k => val("fr_" + k) !== "").map(k => [k, val("fr_" + k)]))}; });
  });
  const card = (k, v, cls) => `<div class="stat"><b${cls ? ` class="${cls}"` : ""}>${v}</b>${esc(t(k))}</div>`;
  const coming = `<span class="hint">${t("coming soon")}</span>`;
  const cards = `<div class="stats">${card("Revenue", fnMoney(dash.revenue))}${card("Expenses", fnMoney(dash.expenses))}${card(dash.net < 0 ? "Net loss" : "Net profit", fnMoney(dash.net))}${card("Outstanding fees", fnMoney(dash.outstanding_fees))}${card("Teacher earnings", fnMoney(dash.teacher_earnings))}${card("Academy revenue", fnMoney(dash.academy_revenue))}${card("Paid to teachers", fnMoney(dash.teacher_paid))}</div>`;
  const filt = form("ffr", field("fr_date_from", "From", "date") + field("fr_date_to", "To", "date")
    + field("fr_course_id", "Course", "text", [["", t("all")], ...courses.map(c => [c.id, c.name])]) + field("fr_batch_id", "batch", "text", [["", t("all")], ...batches.map(b => [b.id, b.course_name + " " + b.code])])
    + field("fr_kind", "Type", "text", [["", t("all")], ["course", "Course"], ["tuition", "Tuition class"]]), "Filter");
  const tbl = (head, body) => body ? `<div style="overflow-x:auto"><table><thead><tr>${head.map(h => `<th>${esc(t(h))}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div>` : `<p>${t("empty")}</p>`;
  const m = tbl(["Month", "Collected", "Payments"], rev.by_month.map(r => `<tr><td>${esc(r.month)}</td><td>${fnMoney(r.collected)}</td><td>${r.payments}</td></tr>`).join(""));
  const c = tbl(["Course", "Type", "Collected"], rev.by_course.map(r => `<tr><td>${esc(r.course_name)}</td><td>${esc(r.kind)}</td><td>${fnMoney(r.collected)}</td></tr>`).join(""));
  const b = tbl(["batch", "Course", "Collected"], rev.by_batch.map(r => `<tr><td>${esc(r.batch_code)}</td><td>${esc(r.course_name)}</td><td>${fnMoney(r.collected)}</td></tr>`).join(""));
  const h = `<h2>${t("Financial dashboard")}</h2><p class="hint">${esc(dash.date_from || "")} → ${esc(dash.date_to || "")}</p>${cards}`
    + `<div class="panel"><h2>${t("Revenue")}</h2><p class="hint">${t("Revenue is money actually received (reversed payments are not counted).")}</p>${filt}`
    + `<p>${t("Total collected")}: <b>${fnMoney(rev.total_collected)}</b> · ${t("Outstanding")}: <b>${fnMoney(rev.outstanding)}</b> · ${t("Course")}: ${fnMoney(rev.by_kind.course)} · ${t("Tuition class")}: ${fnMoney(rev.by_kind.tuition)}</p>${m}${c}${b}</div>`;
  const earn = await feEarnPanel();
  const i = base.indexOf("</h1>");
  return i < 0 ? h + earn + base : base.slice(0, i + 5) + h + earn + base.slice(i + 5);
};

// ---------- Teacher earnings (Sessions 30 and 31) ----------
const feMonth = () => (S.fe && S.fe.month) || new Date(Date.now() - 32 * 864e5).toISOString().slice(0, 7);
async function feEarnPanel() {
  S.fe = S.fe || {month: feMonth()};
  const m = S.fe.month;
  const [r, tt, pays] = await Promise.all([api("/earnings?month=" + m), api("/earnings/teachers"), api("/earnings/payments")]);
  const approved = r.items.length && r.items.every(x => x.status === "approved");
  const tb = (head, body) => body ? `<div style="overflow-x:auto"><table><thead><tr>${head.map(h => `<th>${esc(t(h))}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div>` : `<p>${t("empty")}</p>`;
  const rowsHtml = r.items.map(x => `<tr><td>${esc(x.teacher_name || "-")}</td><td>${esc(x.course_name)} ${esc(x.batch_code)}</td><td>${fnMoney(x.collected_mvr)}</td><td>${x.share_percent}%</td><td>${fnMoney(x.teacher_share_mvr)}</td><td>${fnMoney(x.academy_share_mvr)}</td><td>${esc(x.status)}</td></tr>`).join("");
  const tRows = tt.items.map(x => `<tr><td>${esc(x.teacher_name)}</td><td>${fnMoney(x.earned_mvr)}</td><td>${fnMoney(x.paid_mvr)}</td><td><b>${fnMoney(x.outstanding_mvr)}</b></td><td><button class="btn sm" data-do="fePay" data-id="${x.teacher_id}">${esc(t("Record payment"))}</button></td></tr>`).join("");
  const pRows = pays.map(x => `<tr${x.voided_at ? ' style="opacity:.5"' : ""}><td>${esc(x.paid_on)}</td><td>${esc(x.teacher_name)}</td><td>${fnMoney(x.amount_mvr)}</td><td>${esc(x.method)} ${esc(x.reference || "")}</td><td>${x.voided_at ? esc(t("Voided")) : `<button class="btn sm danger" data-do="feVoid" data-id="${x.id}">${esc(t("Void"))}</button>`}</td></tr>`).join("");
  setTimeout(() => { const el = $("#fe_month"); if (el) el.value = m; }, 0);
  return `<div class="panel"><h2>${t("Teacher earnings")}</h2><p class="hint">${esc(t("Share of the fees actually collected each month (registration fees are not included). Approve a finished month to lock it."))}</p>
    <div class="row" style="display:flex;flex-wrap:wrap;gap:.6rem;align-items:end"><label>${esc(t("Month"))}<input type="month" id="fe_month"></label>
    <button class="btn" data-do="feShow">${esc(t("Show"))}</button><button class="btn alt" data-do="feCalc" ${approved ? "disabled" : ""}>${esc(t("Calculate"))}</button>
    <button class="btn" data-do="feApprove" data-total="${r.totals.teacher_share_mvr}" ${approved || !r.items.length ? "disabled" : ""}>${esc(t("Approve month"))}</button>
    <button class="btn" data-do="feCsv">CSV</button><button class="btn" data-do="feXlsx">Excel</button></div>
    ${tb(["Teacher", "Batch", "Collected", "Share", "Teacher share", "Academy share", "status"], rowsHtml)}
    <p>${t("Total")}: ${fnMoney(r.totals.collected_mvr)} → ${fnMoney(r.totals.teacher_share_mvr)} / ${fnMoney(r.totals.academy_share_mvr)}</p>
    <h3>${t("Owed to teachers (approved months)")}</h3>${tb(["Teacher", "Earned", "Paid", "Outstanding", ""], tRows)}
    <h3>${t("Payments to teachers")}</h3>${tb(["Date", "Teacher", "Amount", "Method", ""], pRows)}</div>`;
}
DO.feShow = () => { S.fe = {month: val("fe_month") || feMonth()}; };
DO.feCalc = async () => { S.fe = {month: val("fe_month") || feMonth()}; await api("/earnings/calculate", "POST", {month: S.fe.month}); flash(t("saved"), true); };
DO.feApprove = async d => { const m = val("fe_month") || feMonth(); if (!confirm(t("Approve and lock") + " " + m + "?")) return false; await api("/earnings/approve", "POST", {month: m, expected_teacher_total: d.total}); S.fe = {month: m}; flash(t("saved"), true); };
DO.fePay = async d => { const amt = prompt(t("Amount (MVR)"), ""); if (!amt) return false; const method = prompt("cash / bank_transfer / cheque / other", "bank_transfer"); if (!method) return false; const ref = prompt(t("Reference (optional)"), "") || ""; await api("/earnings/payments", "POST", {teacher_id: d.id, amount_mvr: amt, method, reference: ref}); flash(t("saved"), true); };
DO.feVoid = async d => { const why = prompt(t("Reason"), ""); if (!why) return false; await api("/earnings/payments/" + d.id + "/void", "POST", {reason: why}); flash(t("saved"), true); };
DO.feCsv = () => fetchFile("/earnings/report.csv?from=" + (val("fe_month") || feMonth()) + "&to=" + (val("fe_month") || feMonth()), {name: "teacher-earnings.csv"});
DO.feXlsx = () => fetchFile("/earnings/report.xlsx?from=" + (val("fe_month") || feMonth()) + "&to=" + (val("fe_month") || feMonth()), {name: "teacher-earnings.xlsx"});

// ---------- Admin dashboard (Session 25): academic and financial cards with filters, from one endpoint ----------
const adKeys = ["course_id", "batch_id", "kind", "teacher_id", "date_from", "date_to"];
views.dashboard = async () => {
  S.ad = S.ad || {f: {}};
  const q = adKeys.filter(k => S.ad.f[k]).map(k => k + "=" + encodeURIComponent(S.ad.f[k])).join("&");
  const d = await api("/admin/dashboard" + (q ? "?" + q : ""));
  const o = d.options, f = S.ad.f;
  setTimeout(() => {
    adKeys.forEach(k => { const el = $("#ad_" + k); if (el && f[k]) el.value = f[k]; });
    onSubmit("fad", async () => { S.ad = {f: Object.fromEntries(adKeys.filter(k => val("ad_" + k) !== "").map(k => [k, val("ad_" + k)]))}; });
  });
  const filt = form("fad", field("ad_course_id", "Course", "text", [["", t("all")], ...o.courses.map(c => [c.id, c.name])]) + field("ad_batch_id", "batch", "text", [["", t("all")], ...o.batches.map(b => [b.id, b.course_name + " " + b.code])])
    + field("ad_kind", "Type", "text", [["", t("all")], ["course", "Course"], ["tuition", "Tuition class"]]) + field("ad_teacher_id", "Teacher", "text", [["", t("all")], ...o.teachers.map(x => [x.id, x.full_name])])
    + field("ad_date_from", "From", "date") + field("ad_date_to", "To", "date"), "Filter");
  const cards = list => `<div class="stats">${list.map(([k, v]) => `<div class="stat"><b><bdi dir="ltr">${esc(v)}</bdi></b>${esc(t(k))}</div>`).join("")}</div>`;
  const acad = cards([["Students", d.students], ["Teachers", d.teachers], ["Admissions waiting", d.admissions_pending], ["Admissions received", d.admissions_received], ["Courses", d.courses], ["Tuition classes", d.tuition_classes], ["batches", d.batches],
    ["Classes held", d.classes_held], ["Classes coming up", d.classes_upcoming], ["Classes cancelled", d.classes_cancelled], ["Assignments", d.assignments], ["Tests", d.tests], ["Tutorials", d.tutorials],
    ["Submissions", d.submissions], ["Graded", d.graded], ["Waiting for grading", d.pending_grading]]);
  const fin = d.financial ? `<h2>${t("Finance")}</h2>` + cards([["Revenue", "MVR " + d.financial.revenue], ["Expenses", "MVR " + d.financial.expenses], [d.financial.net < 0 ? "Net loss" : "Net profit", "MVR " + d.financial.net], ["Outstanding fees", "MVR " + d.financial.outstanding], ["Teacher earnings", "MVR " + d.financial.teacher_earnings], ["Academy revenue", "MVR " + d.financial.academy_revenue]]) : "";
  const fee = d.fees ? cards([[t("fx_unpaid_invoices"), d.fees.unpaid_invoices], [t("fx_overdue_invoices"), d.fees.overdue_invoices], [t("fx_slips_pending"), d.fees.slips_pending]]) : "";
  return `<h1>${t("dashboard")}</h1><div class="panel">${filt}<p class="hint">${t("No dates chosen means all time. Accounts: ")}${d.student_accounts} ${t("Students")}, ${d.teacher_accounts} ${t("Teachers")}.</p></div>${acad}${fin}${fee}<div class="panel">${esc(t("apply_link"))}: <a href="/apply.html" target="_blank" rel="noopener">/apply.html</a></div>`;
};

// Session 27: exports and CSV import
const exQuery = f => { const q = new URLSearchParams(); if (f.q) q.set("q", f.q); if (f.batch) q.set("batch_id", f.batch); if (f.status) q.set("status", f.status); return q.toString(); };
DO.siExp = d => fetchFile(`/student-information/export.${d.ext}?` + exQuery(S.sif || {}), {name: "student-information." + d.ext});
DO.siExpEn = () => fetchFile("/student-information/enrolments.csv", {name: "enrolments.csv"});
DO.tiExp = d => fetchFile(`/teacher-information/export.${d.ext}?` + exQuery(S.tif || {}), {name: "teacher-information." + d.ext});
const impRun = async dry => {
  const f = $("#imp_f").files[0]; if (!f) throw new Error(t("Choose a CSV file first"));
  const fd = new FormData(); fd.append("file", f);
  S.impkind = val("imp_k"); S.imp = await apiForm(`/import/${S.impkind}?dry_run=${dry ? 1 : 0}`, fd);
};
DO.impCheck = async () => { await impRun(true); };
DO.impGo = async () => { if (!sure(t("Import this file now? Rows that pass the check will be created."))) return false; await impRun(false); };
DO.impCreds = () => {   // the temporary passwords exist only in this response: save them as a CSV on the admin's own device
  const lines = ["login_id,name,temporary_password", ...S.imp.rows.filter(x => x.temporary_password).map(x => [x.login_id, x.name, x.temporary_password].map(v => '"' + String(v).replace(/"/g, '""') + '"').join(","))];
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([lines.join("\n")], {type: "text/csv"})); a.download = "new-accounts.csv"; a.click(); return false;
};
const impPanel = () => {
  const r = S.imp, made = r && !r.dry_run && r.rows.some(x => x.temporary_password);
  return `<div class="panel"><h2>${t("Import from CSV")}</h2><p class="hint">${t("Check the file first. Nothing is saved until you press Import. Courses and batches must already exist.")}</p>
    <div class="row" style="display:flex;flex-wrap:wrap;gap:.6rem;align-items:end"><label>${t("What to import")}<select id="imp_k">${[["students", "Students"], ["teachers", "Teachers"], ["enrolments", "Enrolments"]].map(([v, l]) => `<option value="${v}" ${S.impkind === v ? "selected" : ""}>${t(l)}</option>`).join("")}</select></label>
    <label>${t("CSV file")}<input id="imp_f" type="file" accept=".csv,text/csv"></label><button class="btn alt" data-do="impCheck">${t("Check file")}</button><button class="btn" data-do="impGo">${t("Import")}</button></div>
    ${r ? `<p><b>${r.dry_run ? t("Check result: nothing was saved") : t("Imported")}</b> · ${r.ok} ${r.dry_run ? t("would be created") : t("created")} · ${r.rejected} ${t("rejected")} / ${r.total}</p>
      ${made ? `<p class="msg err">${t("Temporary passwords are shown only now. Save them before leaving this page.")} <button class="btn sm" data-do="impCreds">${t("Download new accounts CSV")}</button></p>` : ""}
      ${r.rows.filter(x => x.status === "rejected").map(x => `<div class="msg err">${t("Row")} ${x.row} · ${esc(x.name)}: ${esc(x.message)}</div>`).join("")}` : ""}</div>`;
};
{ const peopleView = views.people; views.people = async () => (await peopleView()) + impPanel(); }
