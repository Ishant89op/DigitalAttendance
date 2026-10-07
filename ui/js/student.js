(async () => {
  'use strict';
  const { html, mount, $, api, enc, qs, icon, ui, fmt, tone, toast, fail, actions, busy, evidenceCell } = AX;

  const me = await AX.boot('student');
  if (!me) return;

  const THRESHOLD = 75;
  let summary = null;
  let prefill = null;

  // How many more classes can be missed (or must be attended) to stay at/above
  // the threshold, assuming every future lecture counts.
  function skipMath(attended, total, p = THRESHOLD / 100) {
    if (!total) return { kind: 'none' };
    if (attended / total >= p) return { kind: 'skip', n: Math.floor(attended / p - total) };
    return { kind: 'need', n: Math.ceil((p * total - attended) / (1 - p)) };
  }
  const skipText = (s) => (s.kind === 'none' ? 'No lectures yet'
    : s.kind === 'skip' ? (s.n === 0 ? 'On the edge — attend the next one' : `You can miss ${s.n} more`)
    : `Attend the next ${s.n} to reach ${THRESHOLD}%`);

  AX.shell({
    user: me,
    nav: [
      { id: 'overview', label: 'Overview', icon: 'home', title: `Hi, ${String(me.name).split(' ')[0]}`, sub: 'Your attendance at a glance' },
      { id: 'history', label: 'History', icon: 'history', sub: 'Every closed lecture, present or absent' },
      { id: 'disputes', label: 'Disputes', icon: 'flag', sub: 'Request a correction with evidence' },
    ],
    onRoute(id, view) {
      if (id === 'overview') return overview(view);
      if (id === 'history') return history(view);
      return disputes(view);
    },
  });

  async function loadSummary() {
    summary = await api.get(`/analytics/student/${enc(me.user_id)}`);
    return summary;
  }

  // ── Overview ─────────────────────────────────────────────────
  async function overview(view) {
    mount(view, html`
      <div class="grid cols-4" id="stats">${[1, 2, 3, 4].map(() => html`<div class="card stat"><div class="skeleton sk-line"></div><div class="skeleton sk-block"></div></div>`)}</div>
      <div class="grid cols-3">
        <div class="card span-2"><div class="card-head"><h2>Subjects</h2><span class="hint">Threshold ${THRESHOLD}%</span><div class="actions" id="risk-badge"></div></div><div class="card-body" id="subjects">${ui.skeleton(5)}</div></div>
        <div class="stack">
          <div class="card"><div class="card-head"><h2>Forecast</h2><span class="hint">next 6 lectures</span></div><div class="card-body" id="forecast">${ui.skeleton(3)}</div></div>
          <div class="card"><div class="card-head"><h2>Recently marked</h2></div><div class="card-body flush" id="recent">${ui.skeleton(4)}</div></div>
        </div>
      </div>`);

    try {
      const d = await loadSummary();
      const subjects = d.subjects || [];
      const atRisk = subjects.filter((s) => s.percentage < THRESHOLD && s.total_lectures > 0);
      const overall = skipMath(d.total_attended, d.total_lectures);
      mount('#stats', html`
        ${ui.stat({ label: 'Overall attendance', value: fmt.pct(d.overall_percentage), toneClass: `tone-${tone(d.overall_percentage)}`, foot: d.total_lectures ? (d.alert ? 'Below threshold' : 'On track') : 'No lectures yet' })}
        ${ui.stat({ label: 'Classes attended', value: fmt.num(d.total_attended), unit: `/ ${fmt.num(d.total_lectures)}`, foot: 'Closed lectures this semester' })}
        ${ui.stat({ label: 'Subjects at risk', value: atRisk.length, toneClass: atRisk.length ? 'tone-bad' : 'tone-good', foot: `Below ${THRESHOLD}%` })}
        ${ui.stat({ label: 'Skip budget', value: overall.kind === 'skip' ? overall.n : overall.kind === 'need' ? `−${overall.n}` : '—', toneClass: overall.kind === 'need' ? 'tone-bad' : '', foot: skipText(overall) })}`);

      mount('#risk-badge', atRisk.length ? ui.badge(`${atRisk.length} at risk`, 'bad') : ui.badge('All clear', 'good'));
      mount('#subjects', subjects.length ? subjects.map((s) => {
        const sk = skipMath(s.attended, s.total_lectures);
        return html`<div class="subject">
          <div class="title" title="${s.course_name}">${s.course_name} <span class="faint mono">${s.course_id}</span></div>
          <div class="pct">${s.total_lectures ? fmt.pct(s.percentage) : '—'}</div>
          ${ui.bar(s.percentage)}
          <div class="meta"><span>${s.attended} of ${s.total_lectures} attended</span><span class="${sk.kind === 'need' ? 'tone-bad' : ''}">${skipText(sk)}</span></div>
        </div>`;
      }) : ui.empty('No subjects yet', 'Your courses appear once the admin enrols your semester.', 'book'));
    } catch (e) { fail(e); }

    api.get(`/analytics/student/${enc(me.user_id)}/forecast`).then((fc) => {
      const risky = (fc.courses || []).filter((c) => c.likely_below_threshold);
      mount('#forecast', html`
        <div class="row between">
          <div><div class="muted">Now</div><div class="big-num">${fmt.pct(fc.overall_current_percentage)}</div></div>
          <div>${icon('history')}</div>
          <div><div class="muted">Projected</div><div class="big-num tone-${tone(fc.overall_projected_percentage)}">${fmt.pct(fc.overall_projected_percentage)}</div></div>
        </div>
        <div class="callout ${fc.likely_below_threshold ? 'bad' : 'good'}">${icon(fc.likely_below_threshold ? 'alert' : 'check')}
          <div class="body">${fc.likely_below_threshold ? `At your recent pace you'd finish below ${fc.threshold}%.` : 'At your recent pace you stay above the threshold.'}
          ${risky.length ? html` Watch <b>${risky.map((c) => c.course_name).join(', ')}</b>.` : ''}</div></div>`);
    }).catch(() => mount('#forecast', ui.empty('Forecast unavailable')));

    api.get(`/analytics/student/${enc(me.user_id)}/history?limit=6`).then((rows) => {
      mount('#recent', rows.length ? html`<div class="list">${rows.map((h) => html`
        <div class="list-item"><div class="avatar">${icon('check')}</div>
          <div class="grow"><div class="t">${h.course_name}</div><div class="s">${fmt.date(h.timestamp)} · ${h.classroom_id || ''}</div></div>
          <span class="badge ${h.source === 'face_recognition' ? 'accent' : 'info'}">${h.source === 'face_recognition' ? 'Face' : 'Manual'} · ${fmt.time(h.timestamp)}</span>
        </div>`)}</div>` : ui.empty('Nothing marked yet', 'Walk into a scheduled class — the camera does the rest.', 'face'));
    }).catch(() => mount('#recent', ui.empty('History unavailable')));
  }

  // ── History ──────────────────────────────────────────────────
  async function history(view) {
    if (!summary) { try { await loadSummary(); } catch (e) { fail(e); } }
    const subjects = (summary && summary.subjects) || [];
    mount(view, html`
      <div class="card">
        <div class="card-head"><h2>Lecture history</h2>
          <div class="actions">
            <select class="input w-auto" id="course-filter">${ui.options(subjects.map((s) => ({ value: s.course_id, label: s.course_name })), '', 'All subjects')}</select>
            <select class="input w-auto" id="status-filter"><option value="">Present & absent</option><option value="present">Present only</option><option value="absent">Absent only</option></select>
          </div>
        </div>
        <div class="card-body flush table-wrap" id="history-table">${ui.skeleton(6)}</div>
      </div>`);

    async function load() {
      const course = $('#course-filter').value;
      const status = $('#status-filter').value;
      try {
        let rows = await api.get(`/analytics/student/${enc(me.user_id)}/history${qs({ limit: 300, include_absent: true, course_id: course })}`);
        if (status) rows = rows.filter((r) => r.attendance_status === status);
        mount('#history-table', rows.length ? html`<table class="table"><thead><tr>
            <th>Date</th><th>Subject</th><th>Room</th><th>Status</th><th>Marked</th><th></th></tr></thead><tbody>
          ${rows.map((h) => html`<tr>
            <td><div>${fmt.date(h.start_time)}</div><div class="sub">${fmt.time(h.start_time)} · #${h.lecture_id}</div></td>
            <td><div>${h.course_name}</div><div class="sub mono">${h.course_id}</div></td>
            <td class="mono">${h.classroom_id || '—'}</td>
            <td>${h.attendance_status === 'present' ? ui.badge('Present', 'good') : ui.badge('Absent', 'bad')}</td>
            <td class="sub">${h.marked_at ? html`${fmt.time(h.marked_at)} · ${h.source === 'face_recognition' ? 'Face' : 'Manual'}` : '—'}</td>
            <td class="num">${h.attendance_status === 'absent' ? html`<button class="btn sm" data-act="dispute" data-course="${h.course_id}" data-lecture="${h.lecture_id}">${icon('flag')} Dispute</button>` : ''}</td>
          </tr>`)}</tbody></table>` : ui.empty('No lectures match', 'Try another subject or filter.', 'calendar'));
      } catch (e) { fail(e); }
    }
    $('#course-filter').addEventListener('change', load);
    $('#status-filter').addEventListener('change', load);
    actions(view, {
      dispute: (d) => { prefill = { course: d.course, lecture: d.lecture }; location.hash = 'disputes'; },
    });
    load();
  }

  // ── Disputes ─────────────────────────────────────────────────
  async function disputes(view) {
    if (!summary) { try { await loadSummary(); } catch (e) { fail(e); } }
    const subjects = (summary && summary.subjects) || [];
    const p = prefill; prefill = null;
    mount(view, html`
      <div class="grid cols-3">
        <form class="card" id="dispute-form" novalidate>
          <div class="card-head"><h2>Raise a dispute</h2></div>
          <div class="card-body stack">
            <label class="field"><span>Subject</span>
              <select class="input" name="course" required>${ui.options(subjects.map((s) => ({ value: s.course_id, label: `${s.course_name} (${s.course_id})` })), p && p.course, 'Choose subject')}</select></label>
            <label class="field"><span>Lecture ID</span>
              <input class="input" name="lecture" inputmode="numeric" pattern="[0-9]*" maxlength="9" placeholder="From History → Dispute" value="${p ? p.lecture : ''}">
              <span class="help">Leave empty for a course-level request.</span></label>
            <label class="field"><span>What happened?</span>
              <textarea class="input" name="reason" maxlength="1000" required placeholder="I was present but the camera did not mark me.">${p ? 'I was present but was marked absent for this lecture.' : ''}</textarea></label>
            <label class="field"><span>Notes for the reviewer <span class="faint">(optional)</span></span>
              <input class="input" name="note" maxlength="2000"></label>
            <label class="field"><span>Supporting PDF <span class="faint">(optional, ≤ 5 MB)</span></span>
              <input class="input" type="file" name="pdf" accept="application/pdf,.pdf">
              <span class="help">Medical certificates etc. PDFs with scripts or attachments are rejected.</span></label>
            <button class="btn primary" type="submit">${icon('flag')} Submit dispute</button>
          </div>
        </form>
        <div class="card span-2">
          <div class="card-head"><h2>My disputes</h2><div class="actions"><button class="btn sm" data-act="refresh">${icon('refresh')} Refresh</button></div></div>
          <div class="card-body flush table-wrap" id="dispute-list">${ui.skeleton(4)}</div>
        </div>
      </div>`);

    async function load() {
      try {
        const rows = await api.get(`/attendance/disputes/student/${enc(me.user_id)}?limit=100`);
        mount('#dispute-list', rows.length ? html`<table class="table"><thead><tr><th>#</th><th>Subject</th><th>Reason</th><th>Evidence</th><th>Status</th><th>Reviewer note</th></tr></thead><tbody>
          ${rows.map((r) => html`<tr>
            <td class="mono">${r.dispute_id}<div class="sub">${fmt.shortDate(r.created_at)}</div></td>
            <td>${r.course_name || r.course_id || '—'}${r.lecture_id ? html`<div class="sub">Lecture #${r.lecture_id}</div>` : ''}</td>
            <td class="wrap">${r.reason}</td>
            <td>${evidenceCell(r)}</td>
            <td>${ui.statusBadge(r.status)}</td>
            <td class="wrap sub">${r.resolution_note || (r.reviewed_at ? '' : 'Awaiting review')}</td>
          </tr>`)}</tbody></table>` : ui.empty('No disputes', 'If the camera ever misses you, raise one here.', 'flag'));
      } catch (e) { fail(e); }
    }

    const form = $('#dispute-form');
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const f = form.elements;
      const lectureRaw = f.lecture.value.trim();
      if (!f.course.value) return toast('Choose a subject', 'warn');
      if (lectureRaw && !/^\d{1,9}$/.test(lectureRaw)) return toast('Lecture ID must be a number', 'warn');
      if (f.reason.value.trim().length < 3) return toast('Describe what happened', 'warn');
      const file = f.pdf.files && f.pdf.files[0];
      if (file && (file.size > 5 * 1024 * 1024 || !/\.pdf$/i.test(file.name))) return toast('Attach a PDF up to 5 MB', 'warn');

      await busy($('button[type="submit"]', form), async () => {
        try {
          let evidenceFile = null;
          if (file) {
            const fd = new FormData(); fd.append('file', file);
            evidenceFile = (await api.upload('/attendance/disputes/evidence', fd)).file_name;
          }
          await api.post('/attendance/disputes', {
            course_id: f.course.value,
            lecture_id: lectureRaw ? Number(lectureRaw) : null,
            reason: f.reason.value.trim(),
            evidence: f.note.value.trim() || null,
            evidence_file: evidenceFile,
          });
          toast('Dispute submitted — your teacher will review it', 'good');
          form.reset();
          load();
        } catch (e) { fail(e); }
      });
    });
    actions(view, { refresh: () => load() });
    load();
  }
})();
