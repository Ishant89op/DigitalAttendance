/* ============================================
   Shared Utilities — Digital Attendance
   ============================================ */

const API_BASE = 'http://127.0.0.1:8000';

/* ─── Theme Management ─── */

function getTheme() {
  return localStorage.getItem('theme') || 'dark';
}

function setTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('theme', theme);
  updateToggleIcon(theme);
}

function toggleTheme() {
  const current = getTheme();
  setTheme(current === 'dark' ? 'light' : 'dark');
}

function updateToggleIcon(theme) {
  const btn = document.getElementById('themeToggle');
  if (btn) btn.textContent = theme === 'dark' ? '☀️' : '🌙';
}

// Apply saved theme immediately
(function () {
  const saved = getTheme();
  document.documentElement.setAttribute('data-theme', saved);
})();

// Update icon after DOM loads
document.addEventListener('DOMContentLoaded', () => {
  updateToggleIcon(getTheme());
});

/* ─── Toast Notifications ─── */

function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;

  const icons = { success: '✓', error: '✗', info: 'i' };
  toast.innerHTML = `<strong>${icons[type] || 'i'}</strong> ${message}`;

  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

/* ─── Auth Guard ─── */

function requireAuth() {
  const user = JSON.parse(localStorage.getItem('user'));
  if (!user) {
    window.location = 'index.html';
    return null;
  }
  return user;
}

/* ─── Logout ─── */

function logout() {
  localStorage.removeItem('user');
  window.location = 'index.html';
}

/* ─── Sidebar Init ─── */

function initSidebar(user) {
  if (!user) return;
  const avatarEl = document.getElementById('userAvatar');
  const nameEl = document.getElementById('userName');
  if (avatarEl) avatarEl.textContent = user.name.charAt(0).toUpperCase();
  if (nameEl) nameEl.textContent = user.name;
}
