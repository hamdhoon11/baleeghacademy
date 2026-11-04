/* Admin control screens: edit/correct/delete for courses, people (with admin permissions), enrollments, applications,
   and the grouped Settings screen. Loaded last; reuses helpers from index.html and learning.js (api, S, t, esc, $, val, field, flash, render, onSubmit, DO, tag). */
const AREA_LABELS = {admissions: "Admissions", courses: "Courses", batches: "Batches", classroom: "Classroom (attendance, grades)", people: "People", enrollments: "Enrollments", fees: "Fees", settings: "Settings", audit: "Audit log"};
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
        if (full && e.role === "admin" && e.id !== self) body.permissions = $("#pm_limited").checked ? [...document.querySelectorAll('input[name="pa"]:checked')].map(i => i.value) : "all";
        await api("/users/" + e.id, "PATCH", body); S.eu = null;
      });
    }
  });
  const roles = [["student", t("student")], ["teacher", t("teacher")], ["admin", t("admin")]];
  const prof = !e ? "" : e.role === "student" ? `${iv("eu_date_of_birth", "date_of_birth", e.date_of_birth, "date")}${iv("eu_grade", "Grade / class", e.grade)}${iv("eu_island", "Island", e.island)}${iv("eu_guardian_name", "guardian_name", e.guardian_name)}${iv("eu_guardian_relationship", "Guardian relationship", e.guardian_relationship)}${iv("eu_guardian_phone", "Guardian phone", e.guardian_phone)}`
    : e.role === "teacher" ? `<label style="flex:1 1 100%">${esc(t("Bio"))}<textarea id="eu_bio" rows="3">${esc(e.bio || "")}</textarea></label>` : "";
  const perms = e && e.role === "admin" && e.id !== self ? (full ? `<fieldset class="days" style="flex:1 1 100%"><legend>${esc(t("Admin permissions"))}</legend><label><input type="radio" name="pm" id="pm_full" ${e.permissions === null ? "checked" : ""}> <span>${esc(t("Full admin (everything, including other admins' permissions)"))}</span></label><label><input type="radio" name="pm" id="pm_limited" ${e.permissions !== null ? "checked" : ""}> <span>${esc(t("Limited to the areas ticked below"))}</span></label><div id="pm_box" style="flex:1 1 100%;display:flex;flex-wrap:wrap;gap:.3rem">${Object.entries(AREA_LABELS).map(([k, l]) => `<label><input type="checkbox" name="pa" value="${k}" ${(e.permissions || []).includes(k) ? "checked" : ""}> <span>${esc(t(l))}</span></label>`).join("")}</div></fieldset>` : `<p class="hint">${esc(t("Only a full admin can change admin permissions."))}</p>`)
    : e && e.id === self && e.role === "admin" ? `<p class="hint">${esc(t("You cannot change your own role or permissions. Ask another full admin."))}</p>` : "";
  const editor = e ? `<div class="panel"><h2>${esc(t("edit"))}: ${esc(e.full_name)} ${tag(e.role)}</h2><form class="row" id="fue">${iv("eu_n", "name", e.full_name)}${iv("eu_e", "email", e.email, "email")}${iv("eu_p", "Phone", e.phone, "tel")}${e.id === self ? "" : sel("eu_r", "role", roles, e.role)}${prof}${perms}${iv("eu_pw", "Set a new password (leave empty to keep)", "", "text", 'autocomplete="off"')}<label style="flex:0 0 auto;flex-direction:row;align-items:center;gap:.4rem"><input type="checkbox" id="eu_mc" ${e.must_change_password ? "checked" : ""}> ${esc(t("Must change password at next sign-in"))}</label><label style="flex:0 0 auto;flex-direction:row;align-items:center;gap:.4rem"><input type="checkbox" id="eu_a" ${e.is_active ? "checked" : ""} ${e.id === self ? "disabled" : ""}> ${esc(t("Account active"))}</label>${bar(`<button class="btn alt">${t("save")}</button>`, `<button type="button" class="btn" data-do="euClose">${t("cancel")}</button>`, e.id === self ? "" : `<button type="button" class="btn danger" data-do="euDel" data-id="${e.id}">${t("delete")}</button>`)}</form><p class="hint">${esc(t("Enrollments") )}: ${e.enrollments} · ${esc(t("Batches taught"))}: ${e.batches_taught}. ${esc(t("People with enrollments, grades or invoices cannot be deleted or change role. Disable the account instead."))}</p></div>` : "";
  const rows = u.map(x => `<tr><td>${esc(x.full_name)}</td><td>${esc(x.email)}</td><td>${esc(x.role)}${x.role === "admin" ? " " + tag(x.permissions === null ? t("Full") : t("Limited"), x.permissions === null ? "ok" : "warn") : ""}</td><td>${x.is_active ? "✓" : "✗"}</td><td><button class="btn sm" data-do="euEdit" data-id="${x.id}">${t("edit")}</button></td></tr>`).join("");
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
