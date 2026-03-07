/* ============================================
   Student Dashboard Logic
   ============================================ */

const user = requireAuth();

if (user) {
    initSidebar(user);
    document.getElementById('greetName').textContent = user.name;
    loadStudentAnalytics();
}

async function loadStudentAnalytics() {

    try {

        const res = await fetch(API_BASE + `/analytics/student/${user.id}`);
        const data = await res.json();

        const percentage = data.attendance_percentage;
        const total = data.total_classes;
        const present = data.present;
        const absent = total - present;

        // Animate stat values
        document.getElementById('percentage').textContent = percentage + '%';
        document.getElementById('totalClasses').textContent = total;
        document.getElementById('present').textContent = present;
        document.getElementById('absent').textContent = absent;

        // Show warning if below 75%
        if (percentage < 75) {
            document.getElementById('warningAlert').classList.remove('hidden');
        }

        // Create chart
        createStudentChart(data);

    } catch (err) {
        showToast('Could not load analytics. Is the API running?', 'error');
    }
}
