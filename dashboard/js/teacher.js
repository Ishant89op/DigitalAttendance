/* ============================================
   Teacher Dashboard Logic
   ============================================ */

const user = requireAuth();

if (user) {
    initSidebar(user);
}

let classChartInstance = null;

async function loadClassAnalytics() {

    const courseId = document.getElementById('course_id').value.trim();

    if (!courseId) {
        showToast('Please enter a Course ID', 'error');
        return;
    }

    try {

        const res = await fetch(API_BASE + `/analytics/class/${courseId}`);
        const data = await res.json();

        document.getElementById('presentToday').textContent = data.present_today;
        document.getElementById('absentToday').textContent = data.absent_today;

        // Show stats and chart
        document.getElementById('statsGrid').style.display = '';
        document.getElementById('chartCard').style.display = '';

        // Destroy previous chart if exists
        if (classChartInstance) {
            classChartInstance.destroy();
        }

        classChartInstance = createTeacherChart(data);

        showToast(`Loaded analytics for ${courseId}`, 'success');

    } catch (err) {
        showToast('Could not load class analytics', 'error');
    }
}


async function markAttendance() {

    const studentId = document.getElementById('student_id').value.trim();
    const courseId = document.getElementById('course_id').value.trim();
    const status = document.getElementById('status').value;

    if (!studentId || !courseId) {
        showToast('Please enter both Student ID and Course ID', 'error');
        return;
    }

    try {

        const res = await fetch(API_BASE + '/attendance/mark', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                student_id: studentId,
                course_id: courseId,
                status: status
            })
        });

        const data = await res.json();

        showToast(data.message || 'Attendance marked', 'success');

        // Refresh analytics
        if (courseId) {
            loadClassAnalytics();
        }

    } catch (err) {
        showToast('Failed to mark attendance', 'error');
    }
}


async function loadStudents() {

    try {

        const res = await fetch(API_BASE + '/students');
        const students = await res.json();

        const container = document.getElementById('studentsList');

        if (students.length === 0) {
            container.innerHTML = `
        <div class="empty-state">
          <div class="icon">📭</div>
          <p>No students registered yet</p>
        </div>
      `;
            return;
        }

        let html = `
      <table class="data-table">
        <thead>
          <tr>
            <th>Student ID</th>
            <th>User ID</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
    `;

        for (const s of students) {
            html += `
        <tr>
          <td>${s.student_id}</td>
          <td>${s.user_id}</td>
          <td><span class="badge badge-success">Active</span></td>
        </tr>
      `;
        }

        html += '</tbody></table>';
        container.innerHTML = html;

        showToast(`Loaded ${students.length} students`, 'info');

    } catch (err) {
        showToast('Could not load students', 'error');
    }
}

// Allow Enter key on course input
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('course_id').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') loadClassAnalytics();
    });
});
