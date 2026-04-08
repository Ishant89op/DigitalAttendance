/* ─── AttendX API Helper ─── */

const API = 'http://localhost:8000';

const api = {
  get: async (path) => {
    const res = await fetch(`${API}${path}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `API ${res.status}: ${path}`);
    }
    return res.json();
  },
  post: async (path, body) => {
    const res = await fetch(`${API}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `API ${res.status}: ${path}`);
    }
    return res.json();
  },
  put: async (path, body) => {
    const res = await fetch(`${API}${path}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `API ${res.status}: ${path}`);
    }
    return res.json();
  },
  delete: async (path) => {
    const res = await fetch(`${API}${path}`, { method: 'DELETE' });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `API ${res.status}: ${path}`);
    }
    return res.json();
  },
  upload: async (path, formData) => {
    const res = await fetch(`${API}${path}`, { method: 'POST', body: formData });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `API ${res.status}: ${path}`);
    }
    return res.json();
  },
};

/* ── Auth guard ── */
function requireAuth(expectedRole) {
  const role = localStorage.getItem('role');
  const id   = localStorage.getItem('user_id');
  if (!role || !id || (expectedRole && role !== expectedRole)) {
    window.location.href = 'login.html';
    return false;
  }
  return true;
}

function getUser() {
  return {
    role: localStorage.getItem('role'),
    id:   localStorage.getItem('user_id'),
    name: localStorage.getItem('user_name'),
  };
}

function logout() {
  localStorage.clear();
  window.location.href = 'login.html';
}

/* ── Sidebar builder ── */
function initSidebar(role, name, uid, navItems) {
  const sb = document.getElementById('sidebar');
  if (!sb) return;

  const roleLabel = {
    student:   'Student Portal',
    teacher:   'Faculty Portal',
    admin:     'Admin Console',
    classroom: 'Classroom Device',
  };

  sb.innerHTML = `
    <div class="sidebar-brand">
      <div class="logo">Attend<span>X</span></div>
      <span class="role-badge">${roleLabel[role] || role}</span>
    </div>
    <div class="sidebar-user">
      <div class="name">${name}</div>
      <div class="uid">${uid}</div>
    </div>
    <nav class="sidebar-nav">
      ${navItems.map(n => `
        <button class="nav-item ${n.active ? 'active' : ''}" onclick="${n.onclick}">
          <span class="icon">${n.icon}</span>${n.label}
        </button>
      `).join('')}
    </nav>
    <div class="sidebar-bottom">
      <button class="nav-item" onclick="logout()">
        <span class="icon">↩</span>Sign Out
      </button>
    </div>
  `;
}

/* ── Helpers ── */
function pctClass(pct) {
  if (pct >= 75) return 'good';
  if (pct >= 60) return 'warn';
  return 'danger';
}

function pctBadge(pct) {
  const cls = pctClass(pct);
  return `<span class="badge ${cls}">${pct}%</span>`;
}

function formatTime(ts) {
  return new Date(ts).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
}

function formatDate(ts) {
  return new Date(ts).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
}

function formatMinutes(mins) {
  if (mins <= 0) return 'Now';
  if (mins < 60) return `in ${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `in ${h}h ${m}m` : `in ${h}h`;
}

/* ── Toast notifications (light theme) ── */
let _toastWrap = null;
function _getToastWrap() {
  if (!_toastWrap) {
    _toastWrap = document.createElement('div');
    _toastWrap.className = 'toast-wrap';
    document.body.appendChild(_toastWrap);
  }
  return _toastWrap;
}

function toast(msg, type = 'info') {
  const colors = {
    info:    { bg: '#eff6ff', border: '#bfdbfe', text: '#1d4ed8' },
    success: { bg: '#f0fdf4', border: '#bbf7d0', text: '#15803d' },
    error:   { bg: '#fef2f2', border: '#fecaca', text: '#dc2626' },
    warn:    { bg: '#fffbeb', border: '#fde68a', text: '#d97706' },
  };
  const c = colors[type] || colors.info;

  const el = document.createElement('div');
  el.style.cssText = `
    background:${c.bg}; border:1px solid ${c.border}; color:${c.text};
    padding:10px 16px; border-radius:8px;
    font-family:'Inter',sans-serif; font-size:13px; font-weight:500;
    box-shadow:0 2px 8px rgba(0,0,0,0.08);
    animation:toastIn 0.25s ease; max-width:320px;
  `;
  el.textContent = msg;

  const wrap = _getToastWrap();
  wrap.appendChild(el);

  if (!document.getElementById('toast-style')) {
    const s = document.createElement('style');
    s.id = 'toast-style';
    s.textContent = `@keyframes toastIn{from{opacity:0;transform:translateX(12px)}to{opacity:1;transform:translateX(0)}}`;
    document.head.appendChild(s);
  }

  setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity 0.2s'; }, 3000);
  setTimeout(() => el.remove(), 3300);
}

/* ── Clock updater ── */
function startClock(elementId) {
  const el = document.getElementById(elementId);
  if (!el) return;
  const tick = () => {
    el.textContent = new Date().toLocaleTimeString('en-IN', {
      hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
  };
  tick();
  setInterval(tick, 1000);
}
