/* ============================================
   Login Page Logic
   ============================================ */

async function login() {

    const id = document.getElementById('user_id').value.trim();
    const password = document.getElementById('password').value.trim();
    const errorEl = document.getElementById('error');
    const btn = document.getElementById('loginBtn');

    errorEl.textContent = '';

    if (!id || !password) {
        errorEl.textContent = 'Please enter both ID and password';
        return;
    }

    // Loading state
    btn.disabled = true;
    btn.innerHTML = '<div class="spinner"></div> Signing in...';

    try {

        const response = await fetch(API_BASE + '/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id, password })
        });

        const data = await response.json();

        if (data.error) {
            errorEl.textContent = data.error;
            btn.disabled = false;
            btn.innerHTML = 'Sign In';
            return;
        }

        localStorage.setItem('user', JSON.stringify(data));

        showToast('Login successful!', 'success');

        // Route by role
        setTimeout(() => {
            if (data.role === 'student') {
                window.location = 'student.html';
            } else if (data.role === 'teacher') {
                window.location = 'teacher.html';
            } else if (data.role === 'admin') {
                window.location = 'admin.html';
            }
        }, 500);

    } catch (err) {
        errorEl.textContent = 'Cannot connect to server. Make sure the API is running.';
        btn.disabled = false;
        btn.innerHTML = 'Sign In';
    }
}

// Allow pressing Enter to submit
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('password').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') login();
    });
    document.getElementById('user_id').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') document.getElementById('password').focus();
    });
});
