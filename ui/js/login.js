(() => {
  'use strict';
  const { $, $$, api, html, mount, icon, brandMark, setCsrf, homeFor, wirePasswordToggles, passwordScore } = AX;

  const ROLES = {
    student:   { id: 'Student ID',   ph: 'e.g. 202411052', pw: 'Password', help: 'First time? Use the one-time password from your admin.' },
    teacher:   { id: 'Faculty ID',   ph: 'e.g. T001',      pw: 'Password', help: 'First time? Use the one-time password from your admin.' },
    admin:     { id: 'Admin ID',     ph: 'admin',          pw: 'Password', help: 'The first admin password is in instance/initial_admin_password.txt on the server.' },
    classroom: { id: 'Classroom ID', ph: 'e.g. CR-2113',   pw: 'Device PIN', help: 'Ask an admin for this room\'s 6-12 digit PIN.' },
  };
  let role = 'student';

  mount('#brand', html`${brandMark}<div><div class="brand-name">Attend<b>X</b></div></div>`);
  mount('#trust', html`${icon('lock')}<span>Encrypted session · locked out after repeated failed attempts</span>`);
  $$('.pw-wrap .toggle').forEach((b) => mount(b, icon('eye')));
  wirePasswordToggles();

  function setRole(next) {
    role = next;
    $$('#roles button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.role === role)));
    const c = ROLES[role];
    $('#id-label').textContent = c.id;
    $('#user-id').placeholder = c.ph;
    $('#pw-label').textContent = c.pw;
    $('#pw-help').textContent = c.help;
    $('#password').inputMode = role === 'classroom' ? 'numeric' : 'text';
    $('#error').textContent = '';
    try { localStorage.setItem('ax.lastRole', role); } catch { /* ignore */ }
  }
  $('#roles').addEventListener('click', (e) => { const b = e.target.closest('button[data-role]'); if (b) setRole(b.dataset.role); });
  try { const last = localStorage.getItem('ax.lastRole'); if (ROLES[last]) setRole(last); } catch { /* ignore */ }

  const params = new URLSearchParams(location.search);
  const nextPath = params.get('next');

  function goHome(r) {
    const home = homeFor(r);
    // Only honour same-site paths that match the role's own page.
    location.replace(nextPath && nextPath === home ? nextPath : home);
  }

  function showSetup() {
    $('#signin').classList.add('hidden');
    $('#setup').classList.remove('hidden');
    $('#setup-form').elements.current.focus();
  }

  $('#login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = $('#submit');
    const userId = $('#user-id').value.trim();
    const password = $('#password').value;
    if (!userId || !password) { $('#error').textContent = 'Enter your ID and password.'; return; }
    btn.disabled = true; btn.innerHTML = '<span class="spin"></span>';
    $('#error').textContent = '';
    try {
      const res = await api.post('/auth/login', { role, user_id: userId, password });
      setCsrf(res.csrf_token);
      if (res.must_change_password) {
        $('#setup-form').elements.current.value = password;
        showSetup();
        $('#setup-form').elements.next.focus();
      } else {
        goHome(res.role);
      }
    } catch (err) {
      $('#error').textContent = err.message;
      $('#password').select();
    } finally {
      btn.disabled = false; btn.textContent = 'Sign in';
    }
  });

  const setupForm = $('#setup-form');
  setupForm.elements.next.addEventListener('input', () => { $('#strength').dataset.score = passwordScore(setupForm.elements.next.value); });
  setupForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const { current, next, confirm } = setupForm.elements;
    const err = $('#setup-error');
    err.textContent = '';
    if (next.value !== confirm.value) { err.textContent = 'New passwords do not match.'; return; }
    const btn = $('button[type="submit"]', setupForm);
    btn.disabled = true;
    try {
      const res = await api.post('/auth/change-password', { current_password: current.value, new_password: next.value });
      setCsrf(res.csrf_token);
      const me = await api.get('/auth/me');
      goHome(me.role);
    } catch (ex) {
      err.textContent = ex.message;
    } finally {
      btn.disabled = false;
    }
  });
  $('#setup-cancel').addEventListener('click', () => AX.logout());

  // Already signed in? Skip the form (or resume the set-password step).
  (async () => {
    try {
      const data = await api.get('/auth/session');
      if (!data.authenticated) return;
      setCsrf(data.csrf_token);
      if (data.must_change_password) showSetup();
      else if (!params.has('setup')) goHome(data.role);
    } catch { /* not signed in */ }
  })();

})();
