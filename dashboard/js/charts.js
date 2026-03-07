/* ============================================
   Chart.js — Theme-Aware Charts
   ============================================ */

const chartColors = {
    present: '#22c55e',
    absent: '#ef4444',
    late: '#eab308'
};

function getChartThemeColors() {
    const theme = document.documentElement.getAttribute('data-theme') || 'dark';
    return {
        text: theme === 'dark' ? '#94a3b8' : '#64748b',
        border: theme === 'dark' ? 'rgba(80,90,120,0.15)' : 'rgba(15,23,42,0.06)',
        tooltipBg: theme === 'dark' ? 'rgba(12,14,20,0.95)' : 'rgba(255,255,255,0.97)',
        tooltipTitle: theme === 'dark' ? '#e2e8f0' : '#1e293b',
        tooltipBody: theme === 'dark' ? '#94a3b8' : '#64748b',
        tooltipBorder: theme === 'dark' ? 'rgba(80,90,120,0.2)' : 'rgba(15,23,42,0.08)'
    };
}

function buildChartOptions(themeColors) {
    return {
        responsive: true,
        maintainAspectRatio: true,
        cutout: '62%',
        plugins: {
            legend: {
                position: 'bottom',
                labels: {
                    usePointStyle: true,
                    pointStyle: 'circle',
                    padding: 18,
                    color: themeColors.text,
                    font: { family: "'Inter', sans-serif", size: 12, weight: '500' }
                }
            },
            tooltip: {
                backgroundColor: themeColors.tooltipBg,
                titleColor: themeColors.tooltipTitle,
                bodyColor: themeColors.tooltipBody,
                borderColor: themeColors.tooltipBorder,
                borderWidth: 1,
                padding: 10,
                cornerRadius: 8,
                titleFont: { family: "'Inter', sans-serif", weight: '600', size: 13 },
                bodyFont: { family: "'Inter', sans-serif", size: 12 },
                callbacks: {
                    label: function (ctx) {
                        const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                        const pct = total > 0 ? ((ctx.parsed / total) * 100).toFixed(1) : 0;
                        return ` ${ctx.label}: ${ctx.parsed} (${pct}%)`;
                    }
                }
            }
        },
        animation: {
            animateRotate: true,
            animateScale: true,
            duration: 700,
            easing: 'easeOutQuart'
        }
    };
}


function createStudentChart(data) {
    const ctx = document.getElementById('attendanceChart');
    if (!ctx) return;

    const themeColors = getChartThemeColors();
    const present = data.present;
    const absent = data.total_classes - data.present;

    return new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['Present', 'Absent'],
            datasets: [{
                data: [present, absent],
                backgroundColor: [chartColors.present, chartColors.absent],
                hoverBackgroundColor: ['#16a34a', '#dc2626'],
                borderWidth: 0,
                borderRadius: 3,
                spacing: 2
            }]
        },
        options: buildChartOptions(themeColors)
    });
}


function createTeacherChart(data) {
    const ctx = document.getElementById('classChart');
    if (!ctx) return null;

    const themeColors = getChartThemeColors();

    return new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['Present Today', 'Absent Today'],
            datasets: [{
                data: [data.present_today, data.absent_today],
                backgroundColor: [chartColors.present, chartColors.absent],
                hoverBackgroundColor: ['#16a34a', '#dc2626'],
                borderWidth: 0,
                borderRadius: 3,
                spacing: 2
            }]
        },
        options: buildChartOptions(themeColors)
    });
}
