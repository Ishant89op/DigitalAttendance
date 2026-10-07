(async () => {
  'use strict';
  const { html, mount, $, api, enc, qs, icon, ui, fmt, tone, toast, fail, actions, busy, openDialog, confirmDialog, showSecret } = AX;

  const me = await AX.boot('admin');
  if (!me) return;

  const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  const ID_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$/;

  AX.shell({
    user: me,
    nav: [
      { id: 'overview', label: 'Overview', icon: 'home', sub: 'Institution-wide attendance and security posture' },
      { id: 'people', label: 'People', icon: 'users', sub: 'Students, faculty and their sign-in access' },
      { id: 'academics', label: 'Academics', icon: 'grid', sub: 'Courses, classrooms, schedule and assignments' },
      { id: 'import', label: 'Import', icon: 'upload', sub: 'Bulk-load data from CSV' },
      { id: 'risk', label: 'Risk & reminders', icon: 'bell', sub: 'Who is heading below the threshold' },
      { id: 'exports', label: 'Exports', icon: 'download', sub: 'Download attendance by course, semester or date' },
      { id: 'audit', label: 'Audit log', icon: 'shield', sub: 'Every sign-in, change and override, append-only' },
    ],
    onRoute(id, view) { ({ overview, people, academics, import: importView, risk, exports, audit }[id] || overview)(view); },
  });

  // Shared: issue a one-time password and show it exactly once.
  async function issuePassword(role, id) {
    const ok = await confirmDialog({
      title: `Issue a one-time password for ${id}?`,
      text: 'Any existing password stops working and their devices are signed out. The new password expires in 72 hours and must be changed at first sign-in.',
      submit: 'Issue password',
    });
    if (!ok) return;
    try {
      const r = await api.post('/auth/issue-password', { target_role: role, target_user_id: id });
      showSecret({ title: 'One-time password', text: `${role} · ${id}`, secret: r.temporary_password, note: 'Shown only once. Hand it over privately — never by group chat.' });
    } catch (e) { fail(e); }
  }

  // ── Overview ─────────────────────────────────────────────────
  async function overview(view) {
    mount(view, html`
      <div class="grid cols-6" id="totals">${ui.skeleton(2)}</div>
      <div class="grid cols-3">
        <div class="card span-2"><div class="card-head"><h2>Marks per day</h2><span class="hint">last 30 days</span></div><div class="card-body" id="trend">${ui.skeleton(4)}</div></div>
        <div class="card"><div class="card-head"><h2>Security</h2><span class="hint">last 24h</span></div><div class="card-body" id="security">${ui.skeleton(4)}</div></div>
      </div>
      <div class="grid cols-2">
        <div class="card"><div class="card-head"><h2>Departments</h2></div><div class="card-body" id="depts">${ui.skeleton(3)}</div></div>
        <div class="card"><div class="card-head"><h2>Below threshold</h2></div><div class="card-body flush" id="low">${ui.skeleton(4)}</div></div>
      </div>`);
    try {
      const [d, sec] = await Promise.all([api.get('/analytics/admin/dashboard'), api.get('/admin/security/overview')]);
      const t = d.totals;
      mount('#totals', html`
        ${ui.stat({ label: 'Students', value: fmt.num(t.total_students) })}
        ${ui.stat({ label: 'Faculty', value: fmt.num(t.total_teachers) })}
        ${ui.stat({ label: 'Courses', value: fmt.num(t.total_courses) })}
        ${ui.stat({ label: 'Live lectures', value: t.active_lectures, toneClass: t.active_lectures ? 'tone-good' : '' })}
        ${ui.stat({ label: 'Marked today', value: fmt.num(t.today_attendance) })}
        ${ui.stat({ label: 'Active sessions', value: sec.active_sessions })}`);

      const trend = d.daily_trend || [];
      const max = Math.max(1, ...trend.map((x) => x.count));
      mount('#trend', trend.length ? html`<div class="spark">${trend.map((x) => html`<i data-h="${(x.count / max) * 100}" title="${fmt.shortDate(x.day)} · ${x.count}"></i>`)}</div>
        <div class="row between muted"><span>${fmt.shortDate(trend[0].day)}</span><span>${fmt.num(trend.reduce((a, x) => a + x.count, 0))} marks</span><span>${fmt.shortDate(trend[trend.length - 1].day)}</span></div>`
        : ui.empty('No attendance yet', 'Marks appear here as lectures run.', 'calendar'));

      const secRow = (label, n, warnIf = 1) => html`<div class="row between"><span class="muted">${label}</span>${ui.badge(n, n >= warnIf ? 'warn' : 'good')}</div>`;
      mount('#security', html`<div class="stack">
        ${secRow('Failed sign-ins', sec.failed_logins_24h, 10)}
        ${secRow('Denied requests', sec.denied_requests_24h, 1)}
        ${secRow('Locked accounts', sec.locked_accounts)}
        ${secRow('Accounts without password', sec.accounts_without_password)}
        ${secRow('Classrooms without PIN', sec.classrooms_without_pin)}
        <button class="btn sm" data-route-to="audit">${icon('shield')} Open audit log</button></div>`);

      const depts = d.department_stats || [];
      mount('#depts', depts.length ? depts.map((x) => html`<div class="subject"><div class="title">${x.department} <span class="faint">· ${x.students} students</span></div>
        <div class="pct">${fmt.pct(x.avg_pct || 0)}</div>${ui.bar(x.avg_pct || 0)}</div>`) : ui.empty('No departments yet'));

      const low = d.low_attendance_students || [];
      mount('#low', low.length ? html`<div class="list">${low.slice(0, 8).map((s) => html`<div class="list-item"><div class="avatar">${AX.initials(s.name)}</div>
        <div class="grow"><div class="t">${s.name}</div><div class="s">${s.student_id} · ${s.department} · Sem ${s.semester}</div></div>
        ${ui.badge(fmt.pct(s.percentage), tone(s.percentage))}</div>`)}</div>` : ui.empty('Everyone is above threshold', '', 'check'));
    } catch (e) { fail(e); }
    view.addEventListener('click', (e) => { const b = e.target.closest('[data-route-to]'); if (b) location.hash = b.dataset.routeTo; });
  }

  // ── People ───────────────────────────────────────────────────
  async function people(view) {
    mount(view, html`
      <div class="card">
        <div class="card-head"><h2>Students</h2>
          <div class="actions"><input class="input search w-auto" id="s-search" placeholder="Search name or ID" autocomplete="off">
            <select class="input w-auto" id="s-sem"><option value="">All semesters</option>${Array.from({ length: 12 }, (_, i) => html`<option value="${i + 1}">Semester ${i + 1}</option>`)}</select>
            <button class="btn sm primary" data-act="add-student">${icon('plus')} Add student</button></div></div>
        <div class="card-body flush table-wrap" id="students">${ui.skeleton(6)}</div>
      </div>
      <div class="card">
        <div class="card-head"><h2>Faculty</h2><div class="actions"><button class="btn sm primary" data-act="add-teacher">${icon('plus')} Add faculty</button></div></div>
        <div class="card-body flush table-wrap" id="teachers">${ui.skeleton(4)}</div>
      </div>`);

    let students = [];
    const drawStudents = () => {
      const q = $('#s-search').value.trim().toLowerCase();
      const sem = $('#s-sem').value;
      const rows = students.filter((s) => (!sem || String(s.semester) === sem) && (!q || `${s.student_id} ${s.name} ${s.email || ''}`.toLowerCase().includes(q)));
      mount('#students', rows.length ? html`<table class="table"><thead><tr><th>Student</th><th>Department</th><th>Face</th><th>Sign-in</th><th></th></tr></thead><tbody>
        ${rows.map((s) => html`<tr>
          <td><div>${s.name}</div><div class="sub mono">${s.student_id}${s.email ? ` · ${s.email}` : ''}</div></td>
          <td>${s.department} · Sem ${s.semester}</td>
          <td>${s.face_registered ? ui.badge('Enrolled', 'good') : ui.badge('Not enrolled', 'warn')}</td>
          <td>${s.has_password ? html`${ui.badge('Active', 'good')}<div class="sub">${s.last_login_at ? `last ${fmt.relative(s.last_login_at)}` : 'never signed in'}</div>` : ui.badge('No password', 'neutral')}</td>
          <td class="num"><div class="row end">
            <button class="btn sm" data-act="issue" data-role="student" data-id="${s.student_id}">${icon('key')} Password</button>
            <button class="btn sm ghost" data-act="edit-student" data-id="${s.student_id}" title="Edit">${icon('edit')}</button>
            ${s.face_registered ? html`<button class="btn sm ghost" data-act="erase-face" data-id="${s.student_id}" title="Erase face template">${icon('face')}</button>` : ''}
            <button class="btn sm ghost" data-act="delete-student" data-id="${s.student_id}" title="Delete">${icon('trash')}</button></div></td>
        </tr>`)}</tbody></table>` : ui.empty('No students', 'Add one, or bulk-import from CSV.', 'users'));
    };
    async function loadStudents() { try { students = await api.get('/admin/students'); drawStudents(); } catch (e) { fail(e); } }
    async function loadTeachers() {
      try {
        const rows = await api.get('/admin/teachers');
        mount('#teachers', rows.length ? html`<table class="table"><thead><tr><th>Faculty</th><th>Department</th><th>Courses</th><th>Sign-in</th><th></th></tr></thead><tbody>
          ${rows.map((t) => html`<tr><td><div>${t.name}</div><div class="sub mono">${t.teacher_id}${t.email ? ` · ${t.email}` : ''}</div></td>
            <td>${t.department}</td><td>${(t.courses || []).length ? t.courses.map((c) => html`<span class="badge neutral mono">${c}</span> `) : html`<span class="faint">—</span>`}</td>
            <td>${t.has_password ? ui.badge('Active', 'good') : ui.badge('No password', 'neutral')}</td>
            <td class="num"><button class="btn sm" data-act="issue" data-role="teacher" data-id="${t.teacher_id}">${icon('key')} Password</button></td></tr>`)}</tbody></table>`
          : ui.empty('No faculty yet', '', 'users'));
      } catch (e) { fail(e); }
    }

    const studentForm = (s = {}) => html`
      ${s.student_id ? '' : html`<label class="field"><span>Student ID</span><input class="input mono" name="student_id" maxlength="32" required></label>`}
      <label class="field"><span>Full name</span><input class="input" name="name" maxlength="120" value="${s.name || ''}" required></label>
      <label class="field"><span>Email</span><input class="input" type="email" name="email" maxlength="254" value="${s.email || ''}"></label>
      <div class="grid cols-2"><label class="field"><span>Department</span><input class="input" name="department" maxlength="32" value="${s.department || 'CSE'}" required></label>
        <label class="field"><span>Semester</span><input class="input" name="semester" type="number" min="1" max="12" value="${s.semester || 1}" required></label></div>`;
    const readStudent = (f) => ({ name: f.name.value.trim(), email: f.email.value.trim() || null, department: f.department.value.trim(), semester: Number(f.semester.value) });

    actions(view, {
      'add-student': () => openDialog({
        title: 'Add student', submit: 'Create', body: studentForm(),
        onSubmit: async (form) => {
          const f = form.elements;
          if (!ID_RE.test(f.student_id.value.trim())) throw new Error('Student ID: letters, digits, . _ - only (max 32).');
          await api.post('/admin/students', { student_id: f.student_id.value.trim(), ...readStudent(f) });
          toast('Student created — issue a password when they are ready to sign in', 'good');
          loadStudents();
        },
      }),
      'edit-student': (d) => {
        const s = students.find((x) => x.student_id === d.id);
        openDialog({
          title: `Edit ${d.id}`, body: studentForm(s),
          onSubmit: async (form) => { await api.put(`/admin/students/${enc(d.id)}`, readStudent(form.elements)); toast('Saved', 'good'); loadStudents(); },
        });
      },
      'erase-face': async (d) => {
        if (!(await confirmDialog({ title: 'Erase face template?', text: `${d.id} will need to register their face again before the camera can mark them.`, submit: 'Erase', tone: 'danger' }))) return;
        try { await api.del(`/admin/students/${enc(d.id)}/face`); toast('Face template erased', 'good'); loadStudents(); } catch (e) { fail(e); }
      },
      'delete-student': async (d) => {
        if (!(await confirmDialog({ title: `Delete ${d.id}?`, text: 'This removes the student, their sign-in and their attendance history. It cannot be undone.', submit: 'Delete', tone: 'danger' }))) return;
        try { await api.del(`/admin/students/${enc(d.id)}`); toast('Student deleted', 'good'); loadStudents(); } catch (e) { fail(e); }
      },
      'add-teacher': () => openDialog({
        title: 'Add faculty', submit: 'Create',
        body: html`<label class="field"><span>Faculty ID</span><input class="input mono" name="teacher_id" maxlength="32" required></label>
          <label class="field"><span>Full name</span><input class="input" name="name" maxlength="120" required></label>
          <label class="field"><span>Email</span><input class="input" type="email" name="email" maxlength="254"></label>
          <label class="field"><span>Department</span><input class="input" name="department" maxlength="32" value="CSE" required></label>`,
        onSubmit: async (form) => {
          const f = form.elements;
          if (!ID_RE.test(f.teacher_id.value.trim())) throw new Error('Faculty ID: letters, digits, . _ - only (max 32).');
          await api.post('/admin/teachers', { teacher_id: f.teacher_id.value.trim(), name: f.name.value.trim(), email: f.email.value.trim() || null, department: f.department.value.trim() });
          toast('Faculty created', 'good'); loadTeachers();
        },
      }),
      issue: (d) => issuePassword(d.role, d.id),
    });
    $('#s-search').addEventListener('input', drawStudents);
    $('#s-sem').addEventListener('change', drawStudents);
    loadStudents(); loadTeachers();
  }

  // ── Academics ────────────────────────────────────────────────
  async function academics(view) {
    mount(view, html`
      <div class="grid cols-2">
        <div class="card"><div class="card-head"><h2>Classrooms</h2><div class="actions"><button class="btn sm primary" data-act="add-room">${icon('plus')} Add room</button></div></div>
          <div class="card-body flush table-wrap" id="rooms">${ui.skeleton(3)}</div></div>
        <div class="card"><div class="card-head"><h2>Courses</h2><div class="actions"><button class="btn sm" data-act="assign">${icon('users')} Assign faculty</button><button class="btn sm primary" data-act="add-course">${icon('plus')} Add course</button></div></div>
          <div class="card-body flush table-wrap" id="courses">${ui.skeleton(3)}</div></div>
      </div>
      <div class="card"><div class="card-head"><h2>Weekly schedule</h2>
        <div class="actions"><select class="input w-auto" id="sched-room"></select><button class="btn sm primary" data-act="add-slot">${icon('plus')} Add slot</button></div></div>
        <div class="card-body" id="schedule">${ui.skeleton(3)}</div></div>`);

    let rooms = []; let courseList = [];
    async function loadRooms() {
      rooms = await api.get('/admin/classrooms');
      mount('#rooms', rooms.length ? html`<table class="table"><thead><tr><th>Room</th><th>Capacity</th><th>Device PIN</th><th></th></tr></thead><tbody>
        ${rooms.map((r) => html`<tr><td><div class="mono">${r.classroom_id}</div><div class="sub">${r.room_number}${r.building ? ` · ${r.building}` : ''}</div></td>
          <td>${r.capacity || '—'}</td>
          <td>${r.pin_locked ? ui.badge('Locked', 'bad') : r.has_pin ? ui.badge('Set', 'good') : ui.badge('Not set', 'warn')}</td>
          <td class="num"><button class="btn sm" data-act="pin" data-id="${r.classroom_id}">${icon('lock')} Set PIN</button></td></tr>`)}</tbody></table>`
        : ui.empty('No classrooms', '', 'grid'));
      const current = $('#sched-room').value;
      mount('#sched-room', ui.options(rooms.map((r) => ({ value: r.classroom_id, label: r.classroom_id })), current || (rooms[0] && rooms[0].classroom_id)));
    }
    async function loadCourses() {
      courseList = await api.get('/admin/courses');
      mount('#courses', courseList.length ? html`<table class="table"><thead><tr><th>Course</th><th>Dept · Sem</th><th class="num">Credits</th></tr></thead><tbody>
        ${courseList.map((c) => html`<tr><td><div>${c.course_name}</div><div class="sub mono">${c.course_id}</div></td><td>${c.department} · ${c.semester}</td><td class="num">${c.credits}</td></tr>`)}</tbody></table>`
        : ui.empty('No courses', '', 'book'));
    }
    async function loadSchedule() {
      const room = $('#sched-room').value;
      if (!room) return mount('#schedule', ui.empty('Add a classroom first', '', 'calendar'));
      const rows = await api.get(`/admin/schedule/${enc(room)}`);
      const byDay = DAYS.map((d) => ({ d, slots: rows.filter((r) => r.day_of_week === d) })).filter((x) => x.slots.length);
      mount('#schedule', byDay.length ? html`<div class="grid cols-3">${byDay.map((x) => html`<div class="card pad stack"><b>${x.d}</b>
        ${x.slots.map((s) => html`<div class="row between"><span>${s.course_name}<div class="sub mono faint">${s.course_id}</div></span><span class="mono muted">${s.start_time.slice(0, 5)}–${s.end_time.slice(0, 5)}</span></div>`)}</div>`)}</div>`
        : ui.empty('Nothing scheduled in this room', 'Add a slot or import a schedule CSV.', 'calendar'));
    }
    const pinField = html`<label class="field"><span>Device PIN</span><input class="input mono" name="pin" inputmode="numeric" maxlength="12" autocomplete="off"><span class="help">6–12 digits, not a sequence. Changing it signs out the room's device.</span></label>`;

    actions(view, {
      'add-room': () => openDialog({
        title: 'Add classroom', submit: 'Save',
        body: html`<div class="grid cols-2"><label class="field"><span>Classroom ID</span><input class="input mono" name="id" maxlength="32" placeholder="CR-2113" required></label>
          <label class="field"><span>Room number</span><input class="input" name="room" maxlength="40" required></label></div>
          <div class="grid cols-2"><label class="field"><span>Building</span><input class="input" name="building" maxlength="80"></label>
          <label class="field"><span>Capacity</span><input class="input" name="capacity" type="number" min="1" max="2000"></label></div>${pinField}`,
        onSubmit: async (form) => {
          const f = form.elements;
          if (!ID_RE.test(f.id.value.trim())) throw new Error('Classroom ID: letters, digits, . _ - only.');
          await api.post('/admin/classrooms', { classroom_id: f.id.value.trim(), room_number: f.room.value.trim(), building: f.building.value.trim() || null, capacity: f.capacity.value ? Number(f.capacity.value) : null, access_pin: f.pin.value.trim() || null });
          toast('Classroom saved', 'good'); loadRooms().then(loadSchedule);
        },
      }),
      pin: (d) => openDialog({
        title: `Set PIN for ${d.id}`, submit: 'Set PIN', body: pinField,
        onSubmit: async (form) => { await api.put(`/admin/classrooms/${enc(d.id)}/pin`, { pin: form.elements.pin.value.trim() }); toast('PIN updated', 'good'); loadRooms(); },
      }),
      'add-course': () => openDialog({
        title: 'Add course', submit: 'Create',
        body: html`<div class="grid cols-2"><label class="field"><span>Course ID</span><input class="input mono" name="id" maxlength="32" required></label>
          <label class="field"><span>Credits</span><input class="input" name="credits" type="number" min="0" max="12" value="3"></label></div>
          <label class="field"><span>Course name</span><input class="input" name="name" maxlength="120" required></label>
          <div class="grid cols-2"><label class="field"><span>Department</span><input class="input" name="dept" value="CSE" maxlength="32" required></label>
          <label class="field"><span>Semester</span><input class="input" name="sem" type="number" min="1" max="12" value="1" required></label></div>`,
        onSubmit: async (form) => {
          const f = form.elements;
          if (!ID_RE.test(f.id.value.trim())) throw new Error('Course ID: letters, digits, . _ - only.');
          await api.post('/admin/courses', { course_id: f.id.value.trim(), course_name: f.name.value.trim(), department: f.dept.value.trim(), semester: Number(f.sem.value), credits: Number(f.credits.value || 3) });
          toast('Course created', 'good'); loadCourses();
        },
      }),
      assign: async () => {
        let teachers = [];
        try { teachers = await api.get('/admin/teachers'); } catch (e) { return fail(e); }
        openDialog({
          title: 'Assign faculty to course', submit: 'Assign',
          body: html`<label class="field"><span>Course</span><select class="input" name="course" required>${ui.options(courseList.map((c) => ({ value: c.course_id, label: `${c.course_name} (${c.course_id})` })), '', 'Choose course')}</select></label>
            <label class="field"><span>Faculty</span><select class="input" name="teacher" required>${ui.options(teachers.map((t) => ({ value: t.teacher_id, label: `${t.name} (${t.teacher_id})` })), '', 'Choose faculty')}</select></label>`,
          onSubmit: async (form) => {
            const f = form.elements;
            if (!f.course.value || !f.teacher.value) throw new Error('Choose both a course and a faculty member.');
            await api.post('/admin/course-teachers', { course_id: f.course.value, teacher_id: f.teacher.value });
            toast('Assigned', 'good');
          },
        });
      },
      'add-slot': () => openDialog({
        title: 'Add schedule slot', submit: 'Add',
        body: html`<label class="field"><span>Course</span><select class="input" name="course" required>${ui.options(courseList.map((c) => ({ value: c.course_id, label: `${c.course_name} (${c.course_id})` })), '', 'Choose course')}</select></label>
          <div class="grid cols-3"><label class="field"><span>Day</span><select class="input" name="day">${ui.options(DAYS.map((d) => ({ value: d, label: d })), 'Monday')}</select></label>
          <label class="field"><span>Start</span><input class="input" type="time" name="start" required></label>
          <label class="field"><span>End</span><input class="input" type="time" name="end" required></label></div>`,
        onSubmit: async (form) => {
          const f = form.elements;
          if (!f.course.value || !f.start.value || !f.end.value) throw new Error('Fill in every field.');
          await api.post('/admin/schedule', { course_id: f.course.value, classroom_id: $('#sched-room').value, day_of_week: f.day.value, start_time: f.start.value, end_time: f.end.value });
          toast('Slot added', 'good'); loadSchedule();
        },
      }),
    });
    $('#sched-room').addEventListener('change', () => loadSchedule().catch(fail));
    try { await Promise.all([loadRooms(), loadCourses()]); await loadSchedule(); } catch (e) { fail(e); }
  }

  // ── Import ───────────────────────────────────────────────────
  function importView(view) {
    const kinds = [
      { id: 'students', title: 'Students', cols: 'student_id, name, email, department, semester' },
      { id: 'teachers', title: 'Faculty', cols: 'teacher_id, name, email, department' },
      { id: 'courses', title: 'Courses', cols: 'course_id, course_name, department, semester, credits' },
      { id: 'schedule', title: 'Schedule', cols: 'course_id, classroom_id, day_of_week, start_time, end_time' },
      { id: 'course-teachers', title: 'Faculty assignments', cols: 'course_id, teacher_id' },
    ];
    mount(view, html`
      <div class="callout info">${icon('info')}<div class="body">UTF-8 CSV with a header row, up to 2 MB / 5,000 rows. Each row is validated on its own — bad rows are skipped and reported, good rows still go in. Imported accounts have <b>no password</b> until you issue one.</div></div>
      <div class="grid cols-3">${kinds.map((k) => html`
        <form class="card" data-kind="${k.id}">
          <div class="card-head"><h2>${k.title}</h2></div>
          <div class="card-body stack"><div class="code-box"><code>${k.cols}</code></div>
            <input class="input" type="file" name="file" accept=".csv,text/csv" required>
            <button class="btn primary" type="submit">${icon('upload')} Import</button>
            <div class="sub" data-result></div></div>
        </form>`)}</div>`);
    view.addEventListener('submit', async (e) => {
      const form = e.target.closest('form[data-kind]'); if (!form) return;
      e.preventDefault();
      const file = form.elements.file.files[0];
      if (!file) return toast('Choose a CSV file', 'warn');
      if (file.size > 2 * 1024 * 1024) return toast('CSV must be 2 MB or smaller', 'warn');
      await busy($('button', form), async () => {
        try {
          const fd = new FormData(); fd.append('file', file);
          const r = await api.upload(`/admin/upload/${form.dataset.kind}`, fd);
          mount($('[data-result]', form), html`<div class="row">${ui.badge(`${r.inserted} added`, 'good')}${ui.badge(`${r.skipped} skipped`, r.skipped ? 'warn' : 'neutral')}</div>
            ${(r.errors || []).length ? html`<ul class="sub">${r.errors.map((x) => html`<li>${x}</li>`)}</ul>` : ''}`);
          toast(`Imported ${r.inserted} row(s)`, 'good');
        } catch (ex) { fail(ex); }
      });
    });
  }

  // ── Risk & reminders ─────────────────────────────────────────
  async function risk(view) {
    mount(view, html`
      <div class="card"><div class="card-head"><h2>Risk forecast</h2><span class="hint">projected over the next 6 lectures at each student's recent pace</span></div>
        <div class="card-body flush table-wrap" id="forecast">${ui.skeleton(5)}</div></div>
      <div class="card"><div class="card-head"><h2>Weekly reminders</h2>
        <div class="actions"><select class="input w-auto" id="r-status"><option value="">All</option><option value="pending">Pending</option><option value="sent">Sent</option></select>
          <button class="btn sm" data-act="generate">${icon('bell')} Generate this week</button><button class="btn sm primary" data-act="sent">${icon('check')} Mark pending as sent</button></div></div>
        <div class="card-body flush table-wrap" id="reminders">${ui.skeleton(4)}</div></div>`);
    async function loadForecast() {
      try {
        const rows = await api.get('/analytics/admin/risk-forecast?limit=50');
        mount('#forecast', rows.length ? html`<table class="table"><thead><tr><th>Student</th><th class="num">Now</th><th class="num">Recent pace</th><th class="num">Projected</th><th>Risk</th></tr></thead><tbody>
          ${rows.map((r) => html`<tr><td><div>${r.name}</div><div class="sub mono">${r.student_id} · ${r.department} · Sem ${r.semester}</div></td>
            <td class="num">${fmt.pct(r.current_percentage)}</td><td class="num">${fmt.pct(r.recent_rate)}</td>
            <td class="num tone-${tone(r.projected_percentage)}">${fmt.pct(r.projected_percentage)}</td>
            <td>${ui.badge(r.risk, r.risk === 'high' ? 'bad' : r.risk === 'medium' ? 'warn' : 'good')}</td></tr>`)}</tbody></table>`
          : ui.empty('No students to forecast yet'));
      } catch (e) { fail(e); }
    }
    async function loadReminders() {
      try {
        const rows = await api.get(`/analytics/admin/reminders${qs({ status: $('#r-status').value, limit: 300 })}`);
        mount('#reminders', rows.length ? html`<table class="table"><thead><tr><th>Student</th><th>Course</th><th class="num">%</th><th>Week</th><th>Status</th><th>Message</th></tr></thead><tbody>
          ${rows.map((r) => html`<tr><td><div>${r.student_name}</div><div class="sub mono">${r.student_id}</div></td><td>${r.course_name}</td>
            <td class="num tone-${tone(Number(r.percentage))}">${fmt.pct(r.percentage)}</td><td class="sub">${fmt.shortDate(r.week_start)}</td>
            <td>${ui.statusBadge(r.status)}</td><td class="wrap sub">${r.message || ''}</td></tr>`)}</tbody></table>`
          : ui.empty('No reminders', 'Generate this week’s list of defaulters.', 'bell'));
      } catch (e) { fail(e); }
    }
    actions(view, {
      generate: (d, btn) => busy(btn, async () => { try { const r = await api.post('/analytics/admin/reminders/generate'); toast(`${r.inserted} new, ${r.updated} updated`, 'good'); loadReminders(); } catch (e) { fail(e); } }),
      sent: (d, btn) => busy(btn, async () => { try { const r = await api.post('/analytics/admin/reminders/mark-sent', { reminder_ids: null }); toast(`${r.updated} marked as sent`, 'good'); loadReminders(); } catch (e) { fail(e); } }),
    });
    $('#r-status').addEventListener('change', loadReminders);
    loadForecast(); loadReminders();
  }

  // ── Exports ──────────────────────────────────────────────────
  async function exports(view) {
    let courses = [];
    try { courses = await api.get('/admin/courses'); } catch (e) { fail(e); }
    const depts = [...new Set(courses.map((c) => c.department))];
    mount(view, html`<form class="card" id="export-form" novalidate>
      <div class="card-head"><h2>Attendance export</h2><span class="hint">up to 5,000 marks per file</span></div>
      <div class="card-body"><div class="grid cols-3">
        <label class="field"><span>Course</span><select class="input" name="course">${ui.options(courses.map((c) => ({ value: c.course_id, label: `${c.course_name} (${c.course_id})` })), '', 'All courses')}</select></label>
        <label class="field"><span>Department</span><select class="input" name="dept">${ui.options(depts.map((d) => ({ value: d, label: d })), '', 'All departments')}</select></label>
        <label class="field"><span>Semester</span><select class="input" name="sem"><option value="">All semesters</option>${Array.from({ length: 12 }, (_, i) => html`<option value="${i + 1}">Semester ${i + 1}</option>`)}</select></label>
        <label class="field"><span>From</span><input class="input" type="date" name="from"></label>
        <label class="field"><span>To</span><input class="input" type="date" name="to"></label>
        <div class="field"><span>&nbsp;</span><div class="row"><button class="btn primary" type="submit" name="excel" value="excel">${icon('download')} Excel</button><button class="btn" type="submit" name="pdf" value="pdf">${icon('download')} PDF</button></div></div>
      </div></div></form>`);
    $('#export-form').addEventListener('submit', (e) => {
      e.preventDefault();
      const f = e.target.elements;
      if (f.from.value && f.to.value && f.from.value > f.to.value) return toast('“From” must be before “To”', 'warn');
      const format = (e.submitter && e.submitter.value) || 'excel';
      const a = document.createElement('a');
      a.href = `/analytics/admin/export${qs({ format, course_id: f.course.value, department: f.dept.value, semester: f.sem.value, from_date: f.from.value, to_date: f.to.value })}`;
      document.body.appendChild(a); a.click(); a.remove();
    });
  }

  // ── Audit ────────────────────────────────────────────────────
  async function audit(view) {
    const EVENTS = ['', 'login_success', 'login_failed', 'account_locked', 'access_denied', 'csrf_rejected', 'password_changed', 'password_issued',
      'attendance_marked', 'manual_override', 'dispute_created', 'dispute_resolved', 'lecture_started', 'lecture_ended', 'export_downloaded',
      'evidence_uploaded', 'evidence_rejected', 'face_registered', 'face_erased', 'duplicate_face_blocked', 'classroom_pin_changed', 'csv_import'];
    mount(view, html`<div class="card"><div class="card-head"><h2>Audit trail</h2>
      <div class="actions"><select class="input w-auto" id="a-event">${ui.options(EVENTS.filter(Boolean).map((e) => ({ value: e, label: e.replace(/_/g, ' ') })), '', 'All events')}</select>
        <button class="btn sm" data-act="reload">${icon('refresh')} Refresh</button></div></div>
      <div class="card-body flush table-wrap" id="audit">${ui.skeleton(8)}</div></div>`);
    const toneFor = (e) => (/failed|denied|rejected|locked|blocked|csrf/.test(e) ? 'bad' : /override|erased|issued|pin|deleted/.test(e) ? 'warn' : /success|marked|created|resolved/.test(e) ? 'good' : 'neutral');
    async function load() {
      try {
        const rows = await api.get(`/admin/audit-log${qs({ limit: 300, event_type: $('#a-event').value })}`);
        mount('#audit', rows.length ? html`<table class="table"><thead><tr><th>When</th><th>Event</th><th>Actor</th><th>Target</th><th>Detail</th></tr></thead><tbody>
          ${rows.map((r) => {
            let detail = r.detail;
            if (typeof detail === 'string') { try { detail = JSON.parse(detail); } catch { /* keep string */ } }
            const pairs = detail && typeof detail === 'object' ? Object.entries(detail).filter(([k]) => k !== 'ts') : [];
            return html`<tr><td class="sub">${fmt.dateTime(r.created_at)}</td><td>${ui.badge(r.event_type.replace(/_/g, ' '), toneFor(r.event_type))}</td>
              <td class="mono">${r.actor_id || '—'}</td><td class="mono">${r.target_id || '—'}</td>
              <td class="sub clip" title="${pairs.map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`).join('  ')}">${pairs.map(([k, v]) => html`<span class="faint">${k}</span> ${typeof v === 'object' ? JSON.stringify(v) : String(v)}  `)}</td></tr>`;
          })}</tbody></table>` : ui.empty('Nothing logged yet', '', 'shield'));
      } catch (e) { fail(e); }
    }
    actions(view, { reload: () => load() });
    $('#a-event').addEventListener('change', load);
    load();
  }

})();
