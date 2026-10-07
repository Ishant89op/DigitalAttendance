(async () => {
  'use strict';
  const { html, mount, $, api, enc, icon, ui, fmt, toast, fail, actions, busy, confirmDialog, brandMark } = AX;

  const me = await AX.boot('classroom');
  if (!me) return;
  const room = me.user_id;
  let lastLecture = null;
  let pollTimer = null;
  let seen = new Set();

  mount('#top', html`${brandMark}
    <div class="room">${me.name} <span>· ${room}</span></div>
    <span class="badge neutral" id="cam-badge">Camera idle</span>
    <div class="kiosk-clock"><b id="kclock"></b><span id="kdate"></span></div>
    <button class="btn sm ghost" data-act="logout">${icon('logout')} Lock</button>`);
  const tick = () => {
    const now = new Date();
    $('#kclock').textContent = now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
    $('#kdate').textContent = now.toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' });
  };
  tick(); setInterval(tick, 10000);

  actions(document.body, {
    logout: () => AX.logout(),
    start: (d, btn) => busy(btn, async () => {
      try {
        const r = await api.post('/lecture/start', { course_id: d.course });
        toast(r.message, r.camera_active || r.resumed_today ? 'good' : 'warn', 6000);
        await refresh();
      } catch (e) { fail(e); }
    }),
    end: async (d, btn) => {
      if (!(await confirmDialog({ title: 'End this lecture?', text: 'The camera stops and attendance for this lecture is closed.', submit: 'End lecture', tone: 'danger' }))) return;
      busy(btn, async () => { try { await api.post('/lecture/end', { lecture_id: Number(d.id) }); toast('Lecture closed', 'good'); await refresh(); } catch (e) { fail(e); } });
    },
    reset: async (d, btn) => {
      if (!(await confirmDialog({ title: 'Force-close stuck sessions?', text: 'Use this only if a lecture shows as running but nothing is happening.', submit: 'Force close', tone: 'danger' }))) return;
      busy(btn, async () => { try { const r = await api.post(`/lecture/force-close/${enc(room)}`); toast(`${r.lectures_closed} session(s) closed`, 'good'); await refresh(); } catch (e) { fail(e); } });
    },
    copy: (d) => { navigator.clipboard?.writeText(d.cmd).then(() => toast('Command copied', 'good')); },
  });

  async function refresh() {
    let state;
    try { state = await api.get(`/lecture/upcoming/${enc(room)}?limit=5`); } catch (e) { return fail(e); }
    const camBadge = $('#cam-badge');
    camBadge.className = `badge ${state.camera_active ? 'good' : 'neutral'}`;
    camBadge.innerHTML = '';
    mount(camBadge, state.camera_active ? html`<i class="dot live"></i>Camera running` : html`Camera idle`);

    if (state.active_lecture_id) {
      if (lastLecture !== state.active_lecture_id) { seen = new Set(); lastLecture = state.active_lecture_id; }
      renderActive(state);
    } else {
      lastLecture = null;
      stopPoll();
      renderIdle(state);
    }
  }

  function renderIdle(state) {
    const list = state.upcoming || [];
    mount('#main', html`
      <div class="card hero-session">
        ${ui.ring(0, 'idle', 'neutral')}
        <div class="stack"><span class="badge neutral">No lecture running</span>
          <h2>${list[0] ? (list[0].status === 'ongoing' ? `${list[0].course_name} is scheduled now` : `Next: ${list[0].course_name}`) : 'Nothing scheduled'}</h2>
          <p class="muted">${list[0] ? `${list[0].day_of_week} · ${list[0].start_time}–${list[0].end_time} · ${fmt.minutes(list[0].minutes_until_start)}` : 'Ask an admin to add this room to the weekly schedule.'}</p>
          ${list[0] ? html`<div class="row"><button class="btn primary lg" data-act="start" data-course="${list[0].course_id}">${icon('play')} Start attendance</button></div>` : ''}
        </div>
      </div>
      <div class="card">
        <div class="card-head"><h2>Upcoming in this room</h2></div>
        <div class="card-body flush">${list.length ? list.map((l) => html`<div class="lecture-row">
          <div class="time">${l.day_of_week.slice(0, 3)} ${l.start_time}</div>
          <div class="grow"><div><b>${l.course_name}</b></div><div class="muted mono">${l.course_id} · until ${l.end_time}</div></div>
          ${l.status === 'ongoing' ? ui.badge('Now', 'good') : ui.badge(fmt.minutes(l.minutes_until_start), 'neutral')}
          <button class="btn sm" data-act="start" data-course="${l.course_id}">${icon('play')} Start</button></div>`) : ui.empty('No upcoming lectures', '', 'calendar')}</div>
      </div>`);
  }

  function renderActive(state) {
    if (!$('#live-hero')) {
      mount('#main', html`
        <div class="stack">
          <div class="card hero-session" id="live-hero">${ui.skeleton(3)}</div>
          <div class="card" id="cmd-card"></div>
        </div>
        <div class="card"><div class="card-head"><h2>Just marked</h2><span class="hint" id="feed-count"></span></div>
          <div class="card-body flush" id="feed">${ui.empty('Waiting for the first face…', 'Look at the camera, blink once, and stay still for a moment.', 'face')}</div></div>`);
    }
    mount('#cmd-card', !state.camera_active && state.manual_command ? html`
      <div class="card-body stack"><div class="callout warn">${icon('alert')}<div class="body"><b>Camera not confirmed.</b> If no camera window opened on this PC, start it manually:</div></div>
        <div class="code-box"><code>${state.manual_command}</code><button class="btn sm" data-act="copy" data-cmd="${state.manual_command}">${icon('copy')}</button></div>
        <div class="row end"><button class="btn sm danger" data-act="reset">Force-close stuck session</button></div></div>` : '');
    startPoll(state.active_lecture_id);
  }

  function startPoll(lectureId) {
    if (pollTimer && pollTimer.id === lectureId) return;
    stopPoll();
    const run = () => poll(lectureId);
    pollTimer = { id: lectureId, h: setInterval(run, 3000) };
    run();
  }
  function stopPoll() { if (pollTimer) { clearInterval(pollTimer.h); pollTimer = null; } }

  async function poll(lectureId) {
    try {
      const [live, present] = await Promise.all([api.get(`/lecture/${lectureId}/live`), api.get(`/attendance/list/${lectureId}`)]);
      const started = new Date(live.start_time);
      const mins = Math.max(0, Math.round((Date.now() - started.getTime()) / 60000));
      mount('#live-hero', html`${ui.ring(live.percentage, `${live.present} of ${live.enrolled}`)}
        <div class="stack grow"><span class="badge good"><i class="dot live"></i>Attendance open · ${mins} min</span>
          <h2>${live.course_name}</h2><p class="muted mono">${live.course_id} · Lecture #${live.lecture_id} · since ${fmt.time(live.start_time)}</p>
          <div class="row"><button class="btn danger" data-act="end" data-id="${live.lecture_id}">${icon('stop')} End lecture</button></div></div>`);
      const recent = [...present].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp)).slice(0, 14);
      $('#feed-count').textContent = `${present.length} present`;
      if (recent.length) {
        mount('#feed', html`<div class="list">${recent.map((p) => html`<div class="feed-item"><div class="avatar">${AX.initials(p.name)}</div>
          <div class="grow"><b>${p.name}</b></div><span class="muted mono">${fmt.time(p.timestamp)}</span></div>`)}</div>`);
      }
      present.forEach((p) => {
        if (!seen.has(p.student_id)) { if (seen.size) toast(`${p.name} marked present`, 'good', 2200); seen.add(p.student_id); }
      });
    } catch (e) {
      if (e.status === 403 || e.status === 404) { stopPoll(); refresh(); } else fail(e);
    }
  }

  refresh();
  setInterval(refresh, 15000);
})();
