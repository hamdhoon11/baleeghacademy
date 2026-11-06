/* Admin control screens: edit/correct/delete for courses, people (with admin permissions), enrollments, applications,
   and the grouped Settings screen. Loaded last; reuses helpers from index.html and learning.js (api, S, t, esc, $, val, field, flash, render, onSubmit, DO, tag). */
const AREA_LABELS = {admissions: "Admissions", courses: "Courses", batches: "Batches", classroom: "Classroom (attendance, grades)", people: "People", enrollments: "Enrollments", fees: "Fees", settings: "Settings", audit: "Audit log", tutorials: "Tutorials", assignments: "Assignments", progress: "Progress (grades, attendance)", materials: "Materials", create_tutorials: "Create tutorials and see answers", submit_tutorial_work: "Submit tutorial work", class_links: "Class links (Meet links)", recordings: "Recordings (view)", add_recordings: "Add class recordings", student_information: "Student information", teacher_information: "Teacher information"};
// which areas exist for each role (the server holds the same list and checks every request against it)
const ROLE_AREAS = {admin: ["admissions", "courses", "batches", "classroom", "people", "enrollments", "fees", "settings", "audit", "tutorials", "create_tutorials", "class_links", "add_recordings", "student_information", "teacher_information"], teacher: ["classroom", "tutorials", "create_tutorials", "class_links", "add_recordings"], student: ["assignments", "progress", "materials", "recordings", "fees", "tutorials", "submit_tutorial_work"]};
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
  setTimeout(() => {
    onSubmit("fc", () => api("/courses", "POST", {name: val("cn"), level: val("cl"), monthly_fee_mvr: val("cf"), textbook: val("ct"), status: val("cs")}));
    if (e) onSubmit("fce", async () => { await api("/courses/" + e.id, "PATCH", {name: val("ce_n"), level: nv("ce_l"), textbook: nv("ce_t"), description: nv("ce_d"), monthly_fee_mvr: val("ce_f") || 0, days_per_week: nv("ce_w"), minutes_per_class: nv("ce_m"), status: val("ce_s")}); S.ec = null; });
  });
  const editor = e ? `<div class="panel"><h2>${esc(t("edit"))}: ${esc(e.name)}</h2><form class="row" id="fce">${iv("ce_n", "name", e.name)}${iv("ce_l", "level", e.level)}${iv("ce_t", "textbook", e.textbook)}${iv("ce_f", "fee", e.monthly_fee_mvr, "number", 'min="0"')}${iv("ce_w", "Days per week", e.days_per_week, "number", 'min="1" max="7"')}${iv("ce_m", "Minutes per class", e.minutes_per_class, "number", 'min="1"')}${sel("ce_s", "status", statuses, e.status)}<label style="flex:1 1 100%">${esc(t("Description"))}<textarea id="ce_d" rows="3">${esc(e.description || "")}</textarea></label>${bar(`<button class="btn alt">${t("save")}</button>`, `<button type="button" class="btn" data-do="ecClose">${t("cancel")}</button>`, `<button type="button" class="btn danger" data-do="ecDel" data-id="${e.id}">${t("delete")}</button>`)}</form><p class="hint">${esc(t("Courses that already have batches cannot be deleted. Set the status to closed instead; the old records stay safe."))}</p></div>` : "";
  return `<h1>${t("courses")}</h1>${editor}<div class="panel">${form("fc", field("cn", "name") + field("cl", "level") + field("cf", "fee", "number") + field("ct", "textbook") + field("cs", "status", "", statuses))}</div><div class="panel">${c.length ? `<table><thead><tr><th>${t("name")}</th><th>${t("level")}</th><th>${t("fee")}</th><th>${t("status")}</th><th></th></tr></thead><tbody>${c.map(x => `<tr><td>${esc(x.name)}</td><td>${esc(x.level || "")}</td><td>${esc(x.monthly_fee_mvr)}</td><td>${esc(x.status)}</td><td><button class="btn sm" data-do="ecEdit" data-id="${x.id}">${t("edit")}</button></td></tr>`).join("")}</tbody></table>` : `<p>${t("empty")}</p>`}</div>`;
};
DO.ecEdit = d => { S.ec = +d.id; };
DO.ecClose = () => { S.ec = null; };
DO.ecDel = async d => { if (!sure(t("Delete this course? This cannot be undone."))) return false; await api("/courses/" + d.id, "DELETE"); S.ec = null; flash(t("saved"), true); };

// ---------- batches: the editor from learning.js gets name, course and delete ----------
DO.saveB = async () => {
  await api("/batches/" + S.eb, "PATCH", {code: val("be_n"), course_id: val("be_c2"), days: pickedDays(), start_time: val("be_t") || null, start_date: val("be_sd") || null, meet_link: val("be_m"), capacity: val("be_c"), teacher_id: val("be_h") || null, status: val("be_s")});
  S.eb = null; flash(t("saved"), true);
};
DO.delB = async d => { if (!sure(t("Delete this batch? This cannot be undone."))) return false; await api("/batches/" + d.id, "DELETE"); S.eb = null; flash(t("saved"), true); };
const batchesBase = views.batches;
views.batches = async () => {
  // fetch our extra data BEFORE calling the base view: the base view schedules DOM work with setTimeout, which must run right after render
  const [b, c] = S.eb ? await Promise.all([api("/batches"), api("/courses")]) : [[], []];
  let h = await batchesBase();
  if (!S.eb) return h;
  const e = b.find(x => x.id === S.eb); if (!e) return h;
  const extra = `<div class="row" style="display:flex;flex-wrap:wrap;gap:.6rem;align-items:end;margin-bottom:.8rem">${iv("be_n", "Batch name / code", e.code)}${sel("be_c2", "course", c.map(x => [x.id, x.name + " " + (x.level || "")]), e.course_id)}<button class="btn danger" data-do="delB" data-id="${e.id}">${t("delete")}</button></div>`;
  return h.replace(/(<div class="panel"><h2>[^<]*<\/h2>)/, `$1${extra}`);
};

// ---------- people: edit anything, permissions for admins, delete mistakes ----------
views.people = async () => {
  const roleF = S.pf || "";
  const u = await api("/users" + (roleF ? "?role=" + roleF : ""));
  const e = S.eu ? await api("/users/" + S.eu).catch(() => null) : null;
  const self = S.user.id, full = !S.user.permissions;
  setTimeout(() => {
    onSubmit("fu", () => api("/users", "POST", {full_name: val("un"), email: val("ue"), password: val("up"), role: val("ur")}));
    if ($("#pf")) $("#pf").onchange = ev => { S.pf = ev.target.value; render(); };
    if (e) {
      const toggle = () => { const m = $("#pm_limited"); if ($("#pm_box")) $("#pm_box").hidden = !(m && m.checked); };
      document.querySelectorAll('input[name="pm"]').forEach(r => r.onchange = toggle); toggle();
      onSubmit("fue", async () => {
        const body = {full_name: val("eu_n"), email: val("eu_e"), phone: nv("eu_p"), is_active: $("#eu_a").checked, must_change_password: $("#eu_mc").checked};
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
  const editor = e ? `<div class="panel"><h2>${esc(t("edit"))}: ${esc(e.full_name)} ${tag(e.role)}</h2><form class="row" id="fue">${iv("eu_n", "name", e.full_name)}${iv("eu_e", "email", e.email, "email")}${iv("eu_p", "Phone", e.phone, "tel")}${e.id === self ? "" : sel("eu_r", "role", roles, e.role)}${prof}${perms}${iv("eu_pw", "Set a new password (leave empty to keep)", "", "text", 'autocomplete="off"')}<label style="flex:0 0 auto;flex-direction:row;align-items:center;gap:.4rem"><input type="checkbox" id="eu_mc" ${e.must_change_password ? "checked" : ""}> ${esc(t("Must change password at next sign-in"))}</label><label style="flex:0 0 auto;flex-direction:row;align-items:center;gap:.4rem"><input type="checkbox" id="eu_a" ${e.is_active ? "checked" : ""} ${e.id === self ? "disabled" : ""}> ${esc(t("Account active"))}</label>${bar(`<button class="btn alt">${t("save")}</button>`, `<button type="button" class="btn" data-do="euClose">${t("cancel")}</button>`, e.id === self ? "" : `<button type="button" class="btn danger" data-do="euDel" data-id="${e.id}">${t("delete")}</button>`)}</form><p class="hint">${esc(t("Enrollments") )}: ${e.enrollments} · ${esc(t("Batches taught"))}: ${e.batches_taught}. ${esc(t("People with enrollments, grades or invoices cannot be deleted or change role. Disable the account instead."))}</p></div>` : "";
  const rows = u.map(x => `<tr><td>${esc(x.full_name)}</td><td>${esc(x.email)}</td><td>${esc(x.role)}${x.permissions !== null ? " " + tag(t("Limited"), "warn") : x.role === "admin" ? " " + tag(t("Full"), "ok") : ""}</td><td>${x.is_active ? "✓" : "✗"}</td><td><button class="btn sm" data-do="euEdit" data-id="${x.id}">${t("edit")}</button></td></tr>`).join("");
  return `<h1>${t("people")}</h1>${editor}<div class="panel">${form("fu", field("un", "name") + field("ue", "email", "email") + field("up", "password", "password") + field("ur", "role", "", roles))}</div><div class="panel"><label style="max-width:240px">${esc(t("role"))}<select id="pf"><option value="">${esc(t("All"))}</option>${roles.map(r => `<option value="${r[0]}" ${r[0] === roleF ? "selected" : ""}>${esc(r[1])}</option>`).join("")}</select></label>${u.length ? `<table><thead><tr><th>${t("name")}</th><th>${t("email")}</th><th>${t("role")}</th><th>${t("is_active")}</th><th></th></tr></thead><tbody>${rows}</tbody></table>` : `<p>${t("empty")}</p>`}</div>`;
};
DO.euEdit = d => { S.eu = +d.id; window.scrollTo(0, 0); };
DO.euClose = () => { S.eu = null; };
DO.euDel = async d => { if (!sure(t("Delete this account? This cannot be undone."))) return false; await api("/users/" + d.id, "DELETE"); S.eu = null; flash(t("saved"), true); };

// ---------- enrollments: drop, move, delete a mistake ----------
views.enrollments = async () => {
  const [e, st, b] = await Promise.all([api("/enrollments"), api("/users?role=student"), api("/batches")]);
  const m = e.find(x => x.id === S.em);
  const bo = b.map(x => [x.id, x.course_name + " " + x.code]);
  setTimeout(() => onSubmit("fe", () => api("/enrollments", "POST", {student_id: val("es"), batch_id: val("eb")})));
  const mover = m ? `<div class="panel"><h2>${esc(m.student_name)}: ${esc(m.course_name)} ${esc(m.batch_code)}</h2><div class="row" style="display:flex;flex-wrap:wrap;gap:.6rem;align-items:end">${sel("em_b", "Move to batch", bo.filter(x => x[0] !== m.batch_id), "")}<button class="btn" data-do="emMove" data-id="${m.id}">${t("Move")}</button><button class="btn alt" data-do="emSet" data-id="${m.id}" data-s="completed">${t("Mark completed")}</button><button class="btn alt" data-do="emSet" data-id="${m.id}" data-s="active">${t("Mark active")}</button><button class="btn alt" data-do="emSet" data-id="${m.id}" data-s="waitlist">${t("Waitlist")}</button><button class="btn danger" data-do="emDel" data-id="${m.id}">${t("delete")}</button><button class="btn" data-do="emClose">${t("cancel")}</button></div><p class="hint">${esc(t("Delete is only for enrollments added by mistake. If invoices exist, use Dropped to keep the history."))}</p></div>` : "";
  return `<h1>${t("enrollments")}</h1>${mover}<div class="panel">${form("fe", field("es", "student", "", st.map(x => [x.id, x.full_name])) + field("eb", "batch", "", bo), "enroll")}</div><div class="panel">${e.length ? `<table><thead><tr><th>${t("student_name")}</th><th>${t("course_name")}</th><th>${t("batch_code")}</th><th>${t("status")}</th><th></th></tr></thead><tbody>${e.map(r => `<tr><td>${esc(r.student_name)}</td><td>${esc(r.course_name)}</td><td>${esc(r.batch_code)}</td><td>${esc(r.status)}</td><td>${["active", "waitlist"].includes(r.status) ? `<button class="btn sm" data-do="emSet" data-id="${r.id}" data-s="dropped">${t("drop")}</button> ` : ""}<button class="btn sm" data-do="emEdit" data-id="${r.id}">${t("edit")}</button></td></tr>`).join("")}</tbody></table>` : `<p>${t("empty")}</p>`}</div>`;
};
DO.emEdit = d => { S.em = +d.id; window.scrollTo(0, 0); };
DO.emClose = () => { S.em = null; };
DO.emSet = async d => { await api("/enrollments/" + d.id, "PATCH", {status: d.s}); S.em = null; flash(t("saved"), true); };
DO.emMove = async d => { await api("/enrollments/" + d.id, "PATCH", {transfer_to_batch_id: val("em_b")}); S.em = null; flash(t("saved"), true); };
DO.emDel = async d => { if (!sure(t("Delete this enrollment? This cannot be undone."))) return false; await api("/enrollments/" + d.id, "DELETE"); S.em = null; flash(t("saved"), true); };

// ---------- admissions: correct an application's details ----------
const admBase = views.admissions;
views.admissions = async () => {
  const [a, courses, bs] = S.sel ? await Promise.all([api("/applications/" + S.sel), api("/courses"), api("/batches")]) : [null, [], []];
  let h = await admBase();   // after our fetches (see batches note above)
  if (!a || !["pending", "waitlist"].includes(a.status)) return h;
  setTimeout(() => onSubmit("fa", async () => { await api("/applications/" + a.id, "PATCH", {full_name: val("fa_n"), date_of_birth: val("fa_d"), phone: val("fa_p"), email: val("fa_e"), island: nv("fa_i"), grade: nv("fa_g"), course_id: val("fa_c"), batch_id: nv("fa_b"), guardian_name: nv("fa_gn"), guardian_relationship: nv("fa_gr"), guardian_phone: nv("fa_gp")}); }));
  const bopts = [["", "-"], ...bs.filter(x => x.course_id === a.course_id).map(x => [x.id, x.code])];
  return h + `<div class="panel"><h2>${esc(t("Correct details"))}</h2><form class="row" id="fa">${iv("fa_n", "name", a.full_name)}${iv("fa_d", "date_of_birth", a.date_of_birth, "date")}${iv("fa_p", "Phone", a.phone, "tel")}${iv("fa_e", "email", a.email, "email")}${iv("fa_i", "Island", a.island)}${iv("fa_g", "Grade / class", a.grade)}${sel("fa_c", "course", courses.map(x => [x.id, x.name + " " + (x.level || "")]), a.course_id)}${sel("fa_b", "batch", bopts, a.batch_id)}${a.is_minor ? iv("fa_gn", "guardian_name", a.guardian_name) + iv("fa_gr", "Guardian relationship", a.guardian_relationship) + iv("fa_gp", "Guardian phone", a.guardian_phone) : ""}<button class="btn alt">${t("save")}</button></form><p class="hint">${esc(t("If you change the course, pick the batch again after saving."))}</p></div>`;
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
