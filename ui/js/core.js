/* ──────────────────────────────────────────────────────────────
   AttendX UI runtime
   - api: same-origin fetch, session cookie + CSRF header, uniform errors
   - html``: tagged template that ESCAPES every interpolation by default.
             Use raw() only for markup this file produced itself.
   - shell: sidebar/topbar, hash routing, toasts, dialogs, formatters
   ────────────────────────────────────────────────────────────── */
(() => {
  'use strict';

  // ── Safe templating ──────────────────────────────────────────
  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;', '`': '&#96;' };
  const escapeHtml = (v) => String(v ?? '').replace(/[&<>"'`]/g, (c) => ESC[c]);

  class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
  const raw = (s) => new Raw(String(s));

  function render(v) {
    if (v == null || v === false) return '';
    if (v instanceof Raw) return v.s;
    if (Array.isArray(v)) return v.map(render).join('');
    return escapeHtml(v);
  }
  function html(strings, ...values) {
    let out = strings[0];
    values.forEach((v, i) => { out += render(v) + strings[i + 1]; });
    return raw(out);
  }

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function mount(target, content) {
    const el = typeof target === 'string' ? $(target) : target;
    if (!el) return null;
    el.innerHTML = render(content);
    applyMeters(el);
    return el;
  }

  // Width/height of bars, rings and sparklines are set through CSSOM (allowed
  // by CSP), never through inline style attributes in markup.
  function applyMeters(root) {
    requestAnimationFrame(() => {
      $$('[data-w]', root).forEach((el) => { el.style.width = clampPct(el.dataset.w) + '%'; });
      $$('[data-h]', root).forEach((el) => { el.style.height = Math.max(2, clampPct(el.dataset.h)) + '%'; });
      $$('.ring[data-pct]', root).forEach((el) => {
        const c = $('.fill', el); if (!c) return;
        const r = Number(c.getAttribute('r')); const len = 2 * Math.PI * r;
        c.style.strokeDasharray = String(len);
        c.style.strokeDashoffset = String(len * (1 - clampPct(el.dataset.pct) / 100));
      });
    });
  }
  const clampPct = (v) => Math.max(0, Math.min(100, Number(v) || 0));

  // ── Icons (inline SVG, stroke = currentColor) ────────────────
  const P = {
    home: '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
    history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/>',
    flag: '<path d="M4 21V4"/><path d="M4 4h12l-2 4 2 4H4"/>',
    book: '<path d="M4 19.5V5a2 2 0 0 1 2-2h13v16H6.5A2.5 2.5 0 0 0 4 21.5"/><path d="M19 17v4H6.5"/>',
    play: '<circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4z"/>',
    edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 1 1 3 3L7 19l-4 1 1-4z"/>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9"/><path d="M16 3.1a4 4 0 0 1 0 7.8"/>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5"/><path d="M12 3v12"/>',
    bell: '<path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
    shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
    key: '<circle cx="7.5" cy="15.5" r="4.5"/><path d="m10.7 12.3 9.3-9.3"/><path d="m18 5 3 3"/><path d="m15 8 3 3"/>',
    logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
    menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
    refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4L21 8"/><path d="M21 3v5h-5"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    alert: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    eyeOff: '<path d="M9.9 4.2A10 10 0 0 1 12 4c6.5 0 10 8 10 8a17 17 0 0 1-2.2 3.2M6.6 6.6C3.9 8.4 2 12 2 12s3.5 7 10 7a9.7 9.7 0 0 0 5.4-1.6"/><path d="m2 2 20 20"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
    camera: '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3z"/><circle cx="12" cy="13" r="3.5"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    file: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    trash: '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/>',
    face: '<path d="M3 8V5a2 2 0 0 1 2-2h3M16 3h3a2 2 0 0 1 2 2v3M21 16v3a2 2 0 0 1-2 2h-3M8 21H5a2 2 0 0 1-2-2v-3"/><path d="M9 9h.01M15 9h.01"/><path d="M9 15c1.5 1.5 4.5 1.5 6 0"/>',
    lock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5h13L22 12v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6z"/>',
  };
  const icon = (name) => raw(`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[name] || ''}</svg>`);
  const brandMark = raw(`<svg class="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="9" fill="currentColor" class="bm-bg"/>
      <path d="M9 12V10a1.5 1.5 0 0 1 1.5-1.5H12M20 8.5h1.5A1.5 1.5 0 0 1 23 10v2M23 20v2a1.5 1.5 0 0 1-1.5 1.5H20M12 23.5h-1.5A1.5 1.5 0 0 1 9 22v-2" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M12.5 16.5l2.4 2.4 4.6-5.2" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>`);

  // ── Session / CSRF ───────────────────────────────────────────
  const CSRF_KEY = 'ax.csrf';
  const store = {
    get(k) { try { return sessionStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { v == null ? sessionStorage.removeItem(k) : sessionStorage.setItem(k, v); } catch { /* private mode */ } },
  };
  const setCsrf = (t) => store.set(CSRF_KEY, t || null);

  class ApiError extends Error {
    constructor(status, message) { super(message); this.status = status; }
  }

  async function request(method, path, { body, form, raw: rawResponse } = {}) {
    const headers = { Accept: 'application/json' };
    if (method !== 'GET') headers['X-CSRF-Token'] = store.get(CSRF_KEY) || '';
    let payload;
    if (form) payload = form;
    else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }

    let res;
    try {
      res = await fetch(path, { method, headers, body: payload, credentials: 'same-origin', cache: 'no-store', redirect: 'error' });
    } catch {
      throw new ApiError(0, 'Cannot reach the server. Is it running?');
    }
    if (rawResponse && res.ok) return res;

    let data = null;
    const type = res.headers.get('content-type') || '';
    if (type.includes('application/json')) data = await res.json().catch(() => null);

    if (!res.ok) {
      const detail = (data && typeof data.detail === 'string') ? data.detail : `Request failed (${res.status})`;
      if (res.status === 401 && !path.startsWith('/auth/login')) {
        setCsrf(null);
        location.replace('/login.html?next=' + encodeURIComponent(location.pathname));
      }
      if (res.status === 403 && detail === 'password_change_required') {
        location.replace('/login.html?setup=1');
      }
      throw new ApiError(res.status, detail);
    }
    return data;
  }

  const api = {
    get: (p) => request('GET', p),
    post: (p, body = {}) => request('POST', p, { body }),
    put: (p, body = {}) => request('PUT', p, { body }),
    del: (p) => request('DELETE', p),
    upload: (p, form) => request('POST', p, { form }),
  };

  // Query-string builder that skips empty values.
  function qs(params) {
    const u = new URLSearchParams();
    Object.entries(params || {}).forEach(([k, v]) => { if (v !== '' && v != null) u.set(k, v); });
    const s = u.toString();
    return s ? '?' + s : '';
  }
  const enc = encodeURIComponent;

  async function boot(role) {
    let me;
    try {
      const s = await api.get('/auth/session');
      if (!s.authenticated) { location.replace('/login.html?next=' + encodeURIComponent(location.pathname)); return null; }
      me = await api.get('/auth/me');
    } catch { return null; }
    setCsrf(me.csrf_token);
    if (me.must_change_password) { location.replace('/login.html?setup=1'); return null; }
    if (role && me.role !== role) { location.replace(homeFor(me.role)); return null; }
    return me;
  }
  const homeFor = (role) => ({ student: '/student.html', teacher: '/teacher.html', admin: '/admin.html', classroom: '/classroom.html' }[role] || '/login.html');

  async function logout() {
    try { await api.post('/auth/logout'); } catch { /* already gone */ }
    setCsrf(null);
    location.replace('/login.html');
  }

  // ── Toasts ───────────────────────────────────────────────────
  let toastWrap;
  function toast(message, tone = 'info', ms = 3600) {
    if (!toastWrap) { toastWrap = document.createElement('div'); toastWrap.className = 'toasts'; toastWrap.setAttribute('role', 'status'); document.body.appendChild(toastWrap); }
    const el = document.createElement('div');
    el.className = `toast ${tone}`;
    el.innerHTML = render(html`<i class="dot"></i><div>${message}</div>`);
    toastWrap.appendChild(el);
    setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 220); }, ms);
  }
  const fail = (e) => toast(e && e.message ? e.message : String(e), 'bad', 5200);

  // ── Dialogs ──────────────────────────────────────────────────
  /**
   * openDialog({ title, text, body, submit, tone, onSubmit(form, dialog) })
   * onSubmit may throw to keep the dialog open; its message is shown inline.
   */
  function openDialog({ title, text = '', body = '', submit = 'Save', cancel = 'Cancel', tone = 'primary', onSubmit, onOpen, wide = false }) {
    const dlg = document.createElement('dialog');
    dlg.className = 'modal';
    dlg.innerHTML = render(html`
      <form method="dialog" novalidate>
        <div class="modal-head"><h3>${title}</h3>${text ? html`<p>${text}</p>` : ''}</div>
        <div class="modal-body">${body}<div class="form-error" data-role="error"></div></div>
        <div class="modal-foot">
          ${cancel ? html`<button type="button" class="btn ghost" data-role="cancel">${cancel}</button>` : ''}
          ${submit ? html`<button type="submit" class="btn ${tone}" data-role="submit">${submit}</button>` : ''}
        </div>
      </form>`);
    if (wide) dlg.style.width = 'min(720px, calc(100vw - 32px))';
    document.body.appendChild(dlg);
    const form = $('form', dlg);
    const err = $('[data-role="error"]', dlg);
    const btn = $('[data-role="submit"]', dlg);
    const close = () => { dlg.close(); };
    dlg.addEventListener('close', () => dlg.remove());
    $('[data-role="cancel"]', dlg)?.addEventListener('click', close);
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      if (!onSubmit) return close();
      err.textContent = '';
      if (btn) { btn.disabled = true; btn.dataset.label = btn.textContent; btn.innerHTML = '<span class="spin"></span>'; }
      try {
        const keepOpen = await onSubmit(form, dlg);
        if (keepOpen !== true) close();
      } catch (e) {
        err.textContent = e && e.message ? e.message : String(e);
      } finally {
        if (btn && dlg.open) { btn.disabled = false; btn.textContent = btn.dataset.label; }
      }
    });
    dlg.showModal();
    applyMeters(dlg);
    onOpen && onOpen(form, dlg);
    $('input, select, textarea', dlg)?.focus();
    return dlg;
  }

  function confirmDialog({ title, text, submit = 'Confirm', tone = 'primary' }) {
    return new Promise((resolve) => {
      let ok = false;
      const dlg = openDialog({ title, text, submit, tone, onSubmit: () => { ok = true; } });
      dlg.addEventListener('close', () => resolve(ok));
    });
  }

  function showSecret({ title, text, secret, note }) {
    openDialog({
      title, text, submit: 'Done', cancel: null,
      body: html`<div class="secret">${secret}</div>
        <div class="row end"><button type="button" class="btn sm" data-role="copy">${icon('copy')} Copy</button></div>
        ${note ? html`<div class="callout warn">${icon('alert')}<div class="body">${note}</div></div>` : ''}`,
      onOpen: (form) => {
        $('[data-role="copy"]', form).addEventListener('click', () => {
          if (!navigator.clipboard) return toast('Select the text and copy it manually', 'warn');
          navigator.clipboard.writeText(secret).then(() => toast('Copied to clipboard', 'good'), () => toast('Copy failed — select it manually', 'warn'));
        });
      },
    });
  }

  // Password field + strength meter (mirrors server policy for feedback;
  // the server is the one that actually enforces it).
  function passwordScore(pw) {
    let s = 0;
    if (pw.length >= 10) s++;
    if (pw.length >= 14) s++;
    const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(pw)).length;
    if (classes >= 3) s++;
    if (classes === 4 && pw.length >= 12) s++;
    return Math.min(4, s);
  }
  function wirePasswordToggles(root = document) {
    $$('.pw-wrap .toggle', root).forEach((btn) => {
      btn.addEventListener('click', () => {
        const input = $('input', btn.parentElement);
        const show = input.type === 'password';
        input.type = show ? 'text' : 'password';
        btn.innerHTML = render(icon(show ? 'eyeOff' : 'eye'));
        btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
      });
    });
  }
  const pwField = (name, label, autocomplete) => html`
    <label class="field"><span>${label}</span>
      <div class="pw-wrap"><input class="input" type="password" name="${name}" autocomplete="${autocomplete}" maxlength="128" required>
      <button type="button" class="toggle" aria-label="Show password">${icon('eye')}</button></div>
    </label>`;

  function changePasswordDialog() {
    openDialog({
      title: 'Change password',
      text: 'Use 10+ characters mixing upper/lower case, digits or symbols. Other devices will be signed out.',
      submit: 'Update password',
      body: html`${pwField('current', 'Current password', 'current-password')}
        ${pwField('next', 'New password', 'new-password')}
        <div class="strength" data-score="0"><i></i><i></i><i></i><i></i></div>
        ${pwField('confirm', 'Confirm new password', 'new-password')}`,
      onOpen: (form) => {
        wirePasswordToggles(form);
        form.elements.next.addEventListener('input', () => { $('.strength', form).dataset.score = passwordScore(form.elements.next.value); });
      },
      onSubmit: async (form) => {
        const { current, next, confirm } = form.elements;
        if (next.value !== confirm.value) throw new Error('New passwords do not match.');
        const res = await api.post('/auth/change-password', { current_password: current.value, new_password: next.value });
        setCsrf(res.csrf_token);
        toast('Password updated', 'good');
      },
    });
  }

  // ── Shell ────────────────────────────────────────────────────
  const ROLE_LABEL = { student: 'Student', teacher: 'Faculty', admin: 'Administrator', classroom: 'Classroom device' };
  const initials = (name) => String(name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]).join('').toUpperCase() || '?';

  /**
   * shell({ user, nav: [{ id, label, icon, title, sub }], onRoute(id) })
   * Renders the sidebar/topbar and routes on location.hash.
   */
  function shell({ user, nav, onRoute }) {
    const app = $('#app');
    app.className = 'app';
    app.innerHTML = render(html`
      <aside class="sidebar" id="sidebar">
        <div class="brand">${brandMark}<div><div class="brand-name">Attend<b>X</b></div><div class="brand-role">${ROLE_LABEL[user.role] || user.role}</div></div></div>
        <nav class="nav" aria-label="Sections">
          ${nav.map((n) => html`<button class="nav-item" data-route="${n.id}">${icon(n.icon)}<span>${n.label}</span><span class="nav-count hidden" data-count="${n.id}"></span></button>`)}
        </nav>
        <div class="sidebar-foot">
          ${user.role !== 'classroom' ? html`<button class="nav-item" data-action="password">${icon('key')}<span>Change password</span></button>` : ''}
          <button class="nav-item" data-action="logout">${icon('logout')}<span>Sign out</span></button>
          <div class="user-chip"><div class="avatar">${initials(user.name)}</div><div class="who"><div class="name">${user.name}</div><div class="id">${user.user_id}</div></div></div>
        </div>
      </aside>
      <main class="main">
        <header class="topbar">
          <button class="btn icon ghost menu-btn" data-action="menu" aria-label="Menu">${icon('menu')}</button>
          <div><h1 id="page-title"></h1><div class="sub" id="page-sub"></div></div>
          <div class="topbar-right" id="topbar-actions"><span class="clock" id="clock"></span></div>
        </header>
        <div class="content" id="view"></div>
      </main>`);

    const sidebar = $('#sidebar');
    app.addEventListener('click', (ev) => {
      const r = ev.target.closest('[data-route]');
      if (r) { location.hash = r.dataset.route; sidebar.classList.remove('open'); return; }
      const a = ev.target.closest('[data-action]');
      if (!a || !sidebar.contains(a) && a.dataset.action !== 'menu') return;
      if (a.dataset.action === 'logout') logout();
      if (a.dataset.action === 'password') changePasswordDialog();
      if (a.dataset.action === 'menu') sidebar.classList.toggle('open');
    });

    const go = () => {
      const id = (location.hash || '').slice(1);
      const item = nav.find((n) => n.id === id) || nav[0];
      $$('.nav-item[data-route]').forEach((b) => b.classList.toggle('active', b.dataset.route === item.id));
      $('#page-title').textContent = item.title || item.label;
      $('#page-sub').textContent = item.sub || '';
      document.title = `${item.label} · AttendX`;
      const view = $('#view');
      view.innerHTML = '';
      const section = document.createElement('section');
      section.className = 'view';
      view.appendChild(section);
      onRoute(item.id, section);
    };
    window.addEventListener('hashchange', go);
    startClock($('#clock'));
    go();
    return { go };
  }

  function setCount(id, n) {
    const el = $(`[data-count="${CSS.escape(id)}"]`);
    if (!el) return;
    el.textContent = n > 99 ? '99+' : String(n);
    el.classList.toggle('hidden', !n);
  }

  function startClock(el) {
    if (!el) return;
    const tick = () => { el.textContent = new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }); };
    tick(); setInterval(tick, 15000);
  }

  // Delegated actions inside a view: <button data-act="save" data-id="…">
  function actions(root, handlers) {
    root.addEventListener('click', (ev) => {
      const el = ev.target.closest('[data-act]');
      if (!el || !root.contains(el)) return;
      const fn = handlers[el.dataset.act];
      if (fn) { ev.preventDefault(); fn(el.dataset, el, ev); }
    });
  }

  async function busy(btn, fn) {
    if (!btn) return fn();
    const label = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spin"></span>';
    try { return await fn(); } finally { btn.disabled = false; btn.innerHTML = label; }
  }

  // ── Formatting ───────────────────────────────────────────────
  const fmt = {
    pct: (v) => `${(Math.round((Number(v) || 0) * 10) / 10).toString()}%`,
    num: (v) => Number(v || 0).toLocaleString('en-IN'),
    date: (ts) => (ts ? new Date(ts).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : '—'),
    shortDate: (ts) => (ts ? new Date(ts).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : '—'),
    time: (ts) => (ts ? new Date(ts).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }) : '—'),
    dateTime: (ts) => (ts ? `${fmt.shortDate(ts)}, ${fmt.time(ts)}` : '—'),
    relative(ts) {
      if (!ts) return '—';
      const diff = (Date.now() - new Date(ts).getTime()) / 1000;
      if (diff < 60) return 'just now';
      if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
      if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
      return fmt.shortDate(ts);
    },
    minutes(m) {
      if (m <= 0) return 'now';
      if (m < 60) return `in ${m}m`;
      const h = Math.floor(m / 60); const r = m % 60;
      if (h >= 24) return `in ${Math.floor(h / 24)}d`;
      return r ? `in ${h}h ${r}m` : `in ${h}h`;
    },
  };
  const tone = (pct, warn = 75, crit = 60) => (pct >= warn ? 'good' : pct >= crit ? 'warn' : 'bad');

  // UI building blocks
  const ui = {
    stat: ({ label, value, unit = '', foot = '', toneClass = '' }) => html`
      <div class="card stat"><div class="label">${label}</div>
      <div class="value ${toneClass}">${value}${unit ? html`<small> ${unit}</small>` : ''}</div>
      ${foot ? html`<div class="foot">${foot}</div>` : ''}</div>`,
    bar: (pct, t) => html`<div class="bar ${t || tone(pct)}"><i data-w="${pct}"></i></div>`,
    ring: (pct, label, t) => html`<div class="ring ${t || tone(pct)}" data-pct="${pct}">
      <svg viewBox="0 0 120 120"><circle class="track" cx="60" cy="60" r="52"/><circle class="fill" cx="60" cy="60" r="52"/></svg>
      <div class="center"><div><b>${fmt.pct(pct)}</b><span>${label}</span></div></div></div>`,
    empty: (title, text = '', ic = 'inbox') => html`<div class="empty">${icon(ic)}<div class="t">${title}</div>${text ? html`<div>${text}</div>` : ''}</div>`,
    skeleton: (n = 3) => html`${Array.from({ length: n }, () => html`<div class="skeleton sk-line"></div>`)}`,
    badge: (text, t = 'neutral') => html`<span class="badge ${t}">${text}</span>`,
    statusBadge: (s) => ({ open: ui.badge('Open', 'info'), approved: ui.badge('Approved', 'good'), rejected: ui.badge('Rejected', 'bad'),
      active: html`<span class="badge good"><i class="dot live"></i>Live</span>`, closed: ui.badge('Closed', 'neutral'),
      pending: ui.badge('Pending', 'warn'), sent: ui.badge('Sent', 'good') }[s] || ui.badge(s || '—')),
    options: (items, value, placeholder) => html`${placeholder != null ? html`<option value="">${placeholder}</option>` : ''}${items.map((o) => html`<option value="${o.value}" ${String(o.value) === String(value ?? '') ? raw('selected') : ''}>${o.label}</option>`)}`,
  };

  // Evidence links are only ever built from a validated server file name.
  const EVIDENCE_RE = /\/attendance\/disputes\/evidence\/(\d{14}_[0-9a-f]{32}\.pdf)/i;
  function evidenceCell(row) {
    const file = row.evidence_file || (EVIDENCE_RE.exec(row.evidence || '') || [])[1];
    const note = String(row.evidence || '').replace(EVIDENCE_RE, '').replace(/Medical leave PDF:\s*/i, '').trim();
    return html`${file ? html`<a href="/attendance/disputes/evidence/${file}" target="_blank" rel="noopener noreferrer" class="row">${icon('file')} PDF</a>` : ''}
      ${note ? html`<div class="sub wrap">${note}</div>` : ''}${!file && !note ? '—' : ''}`;
  }

  window.AX = {
    html, raw, escapeHtml, mount, applyMeters, $, $$, icon, brandMark,
    api, ApiError, qs, enc, boot, logout, setCsrf, homeFor,
    toast, fail, openDialog, confirmDialog, showSecret, changePasswordDialog, wirePasswordToggles, pwField, passwordScore,
    shell, setCount, actions, busy, fmt, tone, ui, evidenceCell, initials, startClock,
  };
})();
