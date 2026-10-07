(async () => {
  'use strict';
  const { html, raw, mount, $, $$, api, enc, qs, icon, ui, fmt, tone, toast, fail, actions, busy, openDialog, confirmDialog, evidenceCell } = AX;

  const me = await AX.boot('teacher');
  if (!me) return;

  const safeGet = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
  const state = { dash: null, course: null, detail: null, liveTimer: null };
  try { state.course = localStorage.getItem('ax.t.course'); } catch { /* ignore */ }

  const stopLive = () => { if (state.liveTimer) { clearInterval(state.liveTimer); state.liveTimer = null; } };

  AX.shell({
    user: me,
    nav: [
      { id: 'courses', label: 'Courses', icon: 'book', sub: 'Attendance till date for every course you teach' },
      { id: 'session', label: 'Live session', icon: 'play', sub: 'Start the camera and watch attendance arrive' },
      { id: 'manual', label: 'Corrections', icon: 'edit', sub: 'Fix attendance for a past lecture' },
      { id: 'disputes', label: 'Disputes', icon: 'flag', sub: 'Student correction requests for your courses' },
    ],
    onRoute(id, view) {
      stopLive();
      ({ courses, session, manual, disputes }[id] || courses)(view);
    },
  });

  async function loadDash() {
    state.dash = await api.get(`/analytics/teacher/${enc(me.user_id)}/dashboard`);
    const courses = state.dash.courses || [];
    if (!courses.some((c) => c.course_id === state.course)) state.course = courses[0] ? courses[0].course_id : null;
    return state.dash;
  }
  function selectCourse(id) {
    state.course = id;
    try { localStorage.setItem('ax.t.course', id); } catch { /* ignore */ }
  }
  const courseOptions = (value) => ui.options((state.dash?.courses || []).map((c) => ({ value: c.course_id, label: `${c.course_name} (${c.course_id})` })), value);
  refreshDisputeCount();

  async function refreshDisputeCount() {
    try { AX.setCount('disputes', (await api.get('/attendance/disputes?status=open&limit=500')).length); } catch { /* ignore */ }
  }

  // ── Courses ──────────────────────────────────────────────────
  async function courses(view) {
    mount(view, html`<div class="grid cols-4" id="summary">${ui.skeleton(2)}</div>
      <div class="grid cols-4" id="course-grid"></div>
      <div id="detail"></div>`);
    try { await loadDash(); } catch (e) { return fail(e); }
    const s = state.dash.summary;
    mount('#summary', html`
      ${ui.stat({ label: 'Courses', value: s.total_courses })}
      ${ui.stat({ label: 'Enrolments', value: fmt.num(s.total_students) })}
      ${ui.stat({ label: 'Closed lectures', value: fmt.num(s.total_lectures) })}
      ${ui.stat({ label: 'Average attendance', value: fmt.pct(s.avg_attendance_pct), toneClass: `tone-${tone(s.avg_attendance_pct)}` })}`);
    const list = state.dash.courses || [];
    if (!list.length) { mount('#course-grid', html`<div class="card span-2">${ui.empty('No courses assigned', 'Ask an admin to assign you to a course.', 'book')}</div>`); return; }
    mount('#course-grid', list.map((c) => html`
      <button class="course-card" data-act="pick" data-id="${c.course_id}" aria-pressed="${String(c.course_id === state.course)}">
        <div class="row between"><span class="code">${c.course_id}</span>${c.today_status === 'active' ? ui.statusBadge('active') : ''}</div>
        <div class="name">${c.course_name}</div>
        ${ui.bar(c.avg_attendance_pct)}
        <div class="nums"><span>${fmt.pct(c.avg_attendance_pct)} avg</span><span>${c.total_students} students</span><span>${c.total_lectures} lectures</span></div>
      </button>`));
    actions(view, {
      pick: (d) => { selectCourse(d.id); $$('.course-card', view).forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.id === d.id))); loadDetail(); },
      export: (d) => exportDialog(d.format),
    });
    loadDetail();
  }

  async function loadDetail() {
    const box = $('#detail');
    if (!box || !state.course) return;
    mount(box, html`<div class="card">${ui.skeleton(6)}</div>`);
    try {
      state.detail = await api.get(`/analytics/teacher/${enc(me.user_id)}/courses/${enc(state.course)}`);
    } catch (e) { return fail(e); }
    const { course, students, recent_lectures: lectures } = state.detail;
    mount(box, html`
      <div class="grid cols-3">
        <div class="card span-2">
          <div class="card-head"><div><h2>${course.course_name}</h2><div class="hint">${course.department} · Semester ${course.semester} · ${course.teacher_names || ''}</div></div>
            <div class="actions">
              <input class="input search w-auto" id="student-search" placeholder="Search students" autocomplete="off">
              <button class="btn sm" data-act="export" data-format="excel">${icon('download')} Excel</button>
              <button class="btn sm" data-act="export" data-format="pdf">${icon('download')} PDF</button>
            </div></div>
          <div class="card-body flush table-wrap" id="students"></div>
        </div>
        <div class="card">
          <div class="card-head"><h2>Recent lectures</h2></div>
          <div class="card-body flush">${lectures.length ? html`<div class="list">${lectures.slice(0, 10).map((l) => html`
            <div class="list-item"><div class="grow"><div class="t">${fmt.date(l.start_time)} <span class="faint mono">#${l.lecture_id}</span></div>
              <div class="s">${fmt.time(l.start_time)} · ${l.classroom_id} · ${l.present_count} present</div></div>
              ${l.status === 'active' ? ui.statusBadge('active') : ui.badge(fmt.pct(l.percentage), tone(l.percentage))}</div>`)}</div>`
            : ui.empty('No lectures yet', 'Start a live session to record one.', 'calendar')}</div>
        </div>
      </div>`);
    const renderStudents = () => {
      const q = ($('#student-search')?.value || '').trim().toLowerCase();
      const rows = students.filter((s) => !q || `${s.student_id} ${s.name} ${s.email || ''}`.toLowerCase().includes(q));
      mount('#students', rows.length ? html`<table class="table"><thead><tr><th>Student</th><th class="num">Attended</th><th>Attendance</th><th>Last present</th><th>Face</th></tr></thead><tbody>
        ${rows.map((s) => html`<tr><td><div>${s.name}</div><div class="sub mono">${s.student_id}</div></td>
          <td class="num">${s.attended}/${s.total_lectures}</td>
          <td><div class="row"><div class="grow">${ui.bar(s.percentage)}</div><span class="mono">${fmt.pct(s.percentage)}</span></div></td>
          <td class="sub">${s.last_present_at ? fmt.relative(s.last_present_at) : 'Never'}</td>
          <td>${s.face_registered ? ui.badge('Enrolled', 'good') : ui.badge('Missing', 'warn')}</td></tr>`)}</tbody></table>`
        : ui.empty('No students match'));
    };
    $('#student-search').addEventListener('input', renderStudents);
    renderStudents();
  }

  function exportDialog(format) {
    openDialog({
      title: `Download ${format === 'pdf' ? 'PDF' : 'Excel'} sheet`,
      text: 'Leave dates empty for attendance till date; set a range to export individual marks.',
      submit: 'Download',
      body: html`<div class="grid cols-2"><label class="field"><span>From</span><input class="input" type="date" name="from"></label>
        <label class="field"><span>To</span><input class="input" type="date" name="to"></label></div>`,
      onSubmit: (form) => {
        const { from, to } = form.elements;
        if (from.value && to.value && from.value > to.value) throw new Error('“From” must be before “To”.');
        const url = `/analytics/teacher/${enc(me.user_id)}/courses/${enc(state.course)}/export${qs({ format, from_date: from.value, to_date: to.value })}`;
        const a = document.createElement('a'); a.href = url; a.rel = 'noopener'; document.body.appendChild(a); a.click(); a.remove();
      },
    });
  }

  // ── Live session ─────────────────────────────────────────────
  async function session(view) {
    mount(view, html`
      <div class="card"><div class="card-body"><div class="row">
        <label class="field grow"><span>Classroom</span><select class="input" id="room"></select></label>
        <label class="field grow"><span>Course</span><select class="input" id="course"></select></label>
        <div class="field"><span>&nbsp;</span><div class="row" id="session-actions"></div></div>
      </div><div class="muted" id="session-note"></div></div></div>
      <div id="live"></div>`);
    try {
      const [rooms] = await Promise.all([api.get('/lecture/classrooms'), state.dash ? null : loadDash()]);
      mount('#room', ui.options(rooms.map((r) => ({ value: r.classroom_id, label: `${r.classroom_id} · ${r.room_number}${r.building ? ` · ${r.building}` : ''}` })), safeGet('ax.t.room')));
      mount('#course', courseOptions(state.course));
    } catch (e) { return fail(e); }
    $('#room').addEventListener('change', () => { try { localStorage.setItem('ax.t.room', $('#room').value); } catch { /* ignore */ } check(); });
    $('#course').addEventListener('change', () => selectCourse($('#course').value));
    actions(view, {
      start: (d, btn) => busy(btn, start),
      end: (d, btn) => busy(btn, () => end(Number(d.id))),
      mark: (d, btn) => busy(btn, () => override(d.student, Number(d.lecture), true)),
      unmark: (d, btn) => busy(btn, () => override(d.student, Number(d.lecture), false)),
    });
    check();

    async function check() {
      stopLive();
      const room = $('#room').value;
      if (!room) return;
      try {
        const a = await api.get(`/lecture/active/${enc(room)}`);
        if (a.lecture_id && a.can_manage) {
          mount('#session-actions', html`<button class="btn danger" data-act="end" data-id="${a.lecture_id}">${icon('stop')} End session</button>`);
          $('#session-note').textContent = a.camera_active ? 'Camera is running in this room.' : 'Lecture is open but the camera process is not confirmed — check the classroom PC.';
          showLive(a.lecture_id);
        } else if (a.lecture_id) {
          mount('#session-actions', html`<button class="btn" disabled>${icon('lock')} Room busy</button>`);
          $('#session-note').textContent = `Another course (${a.course_id}) is running in this room.`;
          mount('#live', '');
        } else {
          mount('#session-actions', html`<button class="btn primary" data-act="start">${icon('play')} Start attendance</button>`);
          $('#session-note').textContent = 'Starting opens the camera on the classroom PC. Reopening the same course today resumes the earlier session.';
          mount('#live', html`<div class="card">${ui.empty('No session running', 'Pick a classroom and course, then start attendance.', 'camera')}</div>`);
        }
      } catch (e) { fail(e); }
    }

    async function start() {
      try {
        const r = await api.post('/lecture/start', { classroom_id: $('#room').value, course_id: $('#course').value || null });
        toast(r.message, r.camera_active || r.resumed_today ? 'good' : 'warn', 6000);
        await check();
      } catch (e) { fail(e); }
    }
    async function end(id) {
      if (!(await confirmDialog({ title: 'End this session?', text: 'The camera stops and the lecture is closed. Attendance stays editable from Corrections.', submit: 'End session', tone: 'danger' }))) return;
      try { await api.post('/lecture/end', { lecture_id: id }); toast('Session closed', 'good'); await check(); } catch (e) { fail(e); }
    }
  }

  async function override(studentId, lectureId, present) {
    try {
      await api.post('/attendance/override', { student_id: studentId, lecture_id: lectureId, present });
      toast(present ? 'Marked present' : 'Marked absent', 'good', 1800);
      if (state.liveTimer) pollLive(lectureId);
    } catch (e) { fail(e); }
  }

  function showLive(lectureId) {
    mount('#live', html`<div class="grid cols-3">
      <div class="card pad row" id="live-ring"></div>
      <div class="card"><div class="card-head"><h2>Present</h2><span class="hint" id="present-count"></span></div><div class="card-body flush" id="present-list">${ui.skeleton(3)}</div></div>
      <div class="card"><div class="card-head"><h2>Not yet seen</h2><span class="hint" id="absent-count"></span></div><div class="card-body flush" id="absent-list">${ui.skeleton(3)}</div></div>
    </div>`);
    pollLive(lectureId);
    state.liveTimer = setInterval(() => pollLive(lectureId), 4000);
  }

  async function pollLive(lectureId) {
    if (!$('#live-ring')) return stopLive();
    try {
      const [live, present] = await Promise.all([api.get(`/lecture/${lectureId}/live`), api.get(`/attendance/list/${lectureId}`)]);
      mount('#live-ring', html`${ui.ring(live.percentage, `${live.present}/${live.enrolled}`)}
        <div class="stack"><h2>${live.course_name}</h2><div class="muted">${live.classroom_id} · started ${fmt.time(live.start_time)}</div>
        <div class="row"><span class="badge good"><i class="dot live"></i>Recording</span><span class="badge neutral">Lecture #${live.lecture_id}</span></div></div>`);
      $('#present-count').textContent = String(present.length);
      $('#absent-count').textContent = String(live.absent_students.length);
      mount('#present-list', present.length ? html`<div class="list">${present.map((p) => html`<div class="list-item"><div class="avatar">${AX.initials(p.name)}</div>
        <div class="grow"><div class="t">${p.name}</div><div class="s">${fmt.time(p.timestamp)} · ${p.source === 'face_recognition' ? 'Face' : 'Manual'}</div></div>
        <button class="btn sm ghost" data-act="unmark" data-student="${p.student_id}" data-lecture="${lectureId}" title="Mark absent">${icon('x')}</button></div>`)}</div>`
        : ui.empty('Waiting for faces…', 'Students are marked after liveness and 3 confident frames.', 'face'));
      mount('#absent-list', live.absent_students.length ? html`<div class="list">${live.absent_students.map((s) => html`<div class="list-item"><div class="avatar">${AX.initials(s.name)}</div>
        <div class="grow"><div class="t">${s.name}</div><div class="s mono">${s.student_id}</div></div>
        <button class="btn sm" data-act="mark" data-student="${s.student_id}" data-lecture="${lectureId}">${icon('check')} Present</button></div>`)}</div>`
        : ui.empty('Everyone is here', '', 'check'));
    } catch (e) { stopLive(); fail(e); }
  }

  // ── Manual corrections ───────────────────────────────────────
  async function manual(view) {
    try { if (!state.dash) await loadDash(); } catch (e) { return fail(e); }
    mount(view, html`<div class="card">
      <div class="card-body"><div class="grid cols-4">
        <label class="field"><span>Course</span><select class="input" id="m-course">${courseOptions(state.course)}</select></label>
        <label class="field"><span>Lecture</span><select class="input" id="m-lecture"></select></label>
        <label class="field"><span>Show</span><select class="input" id="m-scope"><option value="absent">Only absentees</option><option value="all">Everyone</option></select></label>
        <label class="field"><span>Search</span><input class="input search" id="m-search" placeholder="Name or ID" autocomplete="off"></label>
      </div></div>
      <div class="card-head"><h2>Students</h2><span class="hint" id="m-selected">0 selected</span>
        <div class="actions"><button class="btn sm ghost" data-act="all">Select visible</button><button class="btn sm ghost" data-act="none">Clear</button>
          <button class="btn sm good" data-act="apply" data-present="1">${icon('check')} Mark present</button>
          <button class="btn sm danger" data-act="apply" data-present="0">${icon('x')} Mark absent</button></div></div>
      <div class="card-body" id="m-list">${ui.skeleton(4)}</div></div>`);

    const sel = new Set();
    let roster = []; let presentIds = new Set();

    async function loadLectures() {
      selectCourse($('#m-course').value);
      try {
        state.detail = await api.get(`/analytics/teacher/${enc(me.user_id)}/courses/${enc(state.course)}`);
        roster = state.detail.students;
        const lectures = state.detail.recent_lectures;
        mount('#m-lecture', lectures.length ? ui.options(lectures.map((l) => ({ value: l.lecture_id, label: `${fmt.dateTime(l.start_time)} · ${l.classroom_id} · #${l.lecture_id}${l.status === 'active' ? ' (live)' : ''}` }))) : html`<option value="">No lectures yet</option>`);
        await loadPresent();
      } catch (e) { fail(e); }
    }
    async function loadPresent() {
      sel.clear();
      const id = $('#m-lecture').value;
      if (!id) { mount('#m-list', ui.empty('No lectures to correct', 'Lectures appear here once a session has been started.', 'calendar')); return; }
      try { presentIds = new Set((await api.get(`/attendance/list/${id}`)).map((r) => r.student_id)); } catch (e) { return fail(e); }
      draw();
    }
    function visible() {
      const q = $('#m-search').value.trim().toLowerCase();
      const scope = $('#m-scope').value;
      return roster.filter((s) => (scope === 'all' || !presentIds.has(s.student_id)) && (!q || `${s.student_id} ${s.name}`.toLowerCase().includes(q)));
    }
    function draw() {
      const rows = visible();
      $('#m-selected').textContent = `${sel.size} selected`;
      mount('#m-list', rows.length ? html`<div class="pick-list">${rows.map((s) => html`
        <label class="pick ${sel.has(s.student_id) ? 'on' : ''}"><input type="checkbox" data-id="${s.student_id}" ${sel.has(s.student_id) ? raw('checked') : ''}>
          <div class="grow"><div class="t">${s.name}</div><div class="s">${s.student_id}</div></div>
          ${presentIds.has(s.student_id) ? ui.badge('Present', 'good') : ui.badge('Absent', 'bad')}</label>`)}</div>`
        : ui.empty('Nobody to show', 'Everyone in this lecture is already present.', 'check'));
    }
    $('#m-list').addEventListener('change', (e) => {
      const cb = e.target.closest('input[type="checkbox"]'); if (!cb) return;
      cb.checked ? sel.add(cb.dataset.id) : sel.delete(cb.dataset.id);
      cb.closest('.pick').classList.toggle('on', cb.checked);
      $('#m-selected').textContent = `${sel.size} selected`;
    });
    $('#m-course').addEventListener('change', loadLectures);
    $('#m-lecture').addEventListener('change', loadPresent);
    $('#m-scope').addEventListener('change', draw);
    $('#m-search').addEventListener('input', draw);
    actions(view, {
      all: () => { visible().forEach((s) => sel.add(s.student_id)); draw(); },
      none: () => { sel.clear(); draw(); },
      apply: (d, btn) => busy(btn, async () => {
        const lectureId = Number($('#m-lecture').value);
        if (!lectureId || !sel.size) return toast('Select a lecture and at least one student', 'warn');
        const present = d.present === '1';
        let ok = 0;
        for (const id of sel) {
          try { await api.post('/attendance/override', { student_id: id, lecture_id: lectureId, present }); ok++; } catch (e) { fail(e); break; }
        }
        toast(`${ok} student${ok === 1 ? '' : 's'} marked ${present ? 'present' : 'absent'}`, 'good');
        await loadPresent();
      }),
    });
    loadLectures();
  }

  // ── Disputes ─────────────────────────────────────────────────
  async function disputes(view) {
    try { if (!state.dash) await loadDash(); } catch (e) { return fail(e); }
    mount(view, html`<div class="card">
      <div class="card-head"><h2>Dispute queue</h2>
        <div class="actions">
          <select class="input w-auto" id="d-course">${ui.options((state.dash.courses || []).map((c) => ({ value: c.course_id, label: c.course_name })), '', 'All my courses')}</select>
          <select class="input w-auto" id="d-status"><option value="open">Open</option><option value="approved">Approved</option><option value="rejected">Rejected</option><option value="">All</option></select>
        </div></div>
      <div class="card-body flush table-wrap" id="d-list">${ui.skeleton(5)}</div></div>`);
    async function load() {
      try {
        const rows = await api.get(`/attendance/disputes${qs({ status: $('#d-status').value, course_id: $('#d-course').value, limit: 300 })}`);
        mount('#d-list', rows.length ? html`<table class="table"><thead><tr><th>#</th><th>Student</th><th>Course / lecture</th><th>Reason</th><th>Evidence</th><th>Status</th><th></th></tr></thead><tbody>
          ${rows.map((r) => html`<tr>
            <td class="mono">${r.dispute_id}<div class="sub">${fmt.shortDate(r.created_at)}</div></td>
            <td><div>${r.student_name}</div><div class="sub mono">${r.student_id}</div></td>
            <td><div>${r.course_name || r.course_id || '—'}</div><div class="sub">${r.lecture_id ? `Lecture #${r.lecture_id}` : 'Course-level'}</div></td>
            <td class="wrap">${r.reason}</td>
            <td>${evidenceCell(r)}</td>
            <td>${ui.statusBadge(r.status)}${r.resolution_note ? html`<div class="sub wrap">${r.resolution_note}</div>` : ''}</td>
            <td class="num">${r.status === 'open' ? html`<div class="row end">
              <button class="btn sm good" data-act="resolve" data-id="${r.dispute_id}" data-verdict="approved">${icon('check')} Approve</button>
              <button class="btn sm danger" data-act="resolve" data-id="${r.dispute_id}" data-verdict="rejected">${icon('x')}</button></div>` : ''}</td>
          </tr>`)}</tbody></table>` : ui.empty('Inbox zero', 'No disputes match this filter.', 'inbox'));
      } catch (e) { fail(e); }
    }
    actions(view, {
      resolve: (d) => openDialog({
        title: d.verdict === 'approved' ? 'Approve dispute' : 'Reject dispute',
        text: d.verdict === 'approved' ? 'If a lecture is attached, the student is marked present for it.' : 'The student will see your note.',
        submit: d.verdict === 'approved' ? 'Approve' : 'Reject', tone: d.verdict === 'approved' ? 'good' : 'danger',
        body: html`<label class="field"><span>Note to student <span class="faint">(optional)</span></span><textarea class="input" name="note" maxlength="1000"></textarea></label>`,
        onSubmit: async (form) => {
          await api.post(`/attendance/disputes/${Number(d.id)}/resolve`, { action: d.verdict, resolution_note: form.elements.note.value.trim() || null });
          toast('Dispute resolved', 'good');
          load(); refreshDisputeCount();
        },
      }),
    });
    $('#d-status').addEventListener('change', load);
    $('#d-course').addEventListener('change', load);
    load();
  }
})();
