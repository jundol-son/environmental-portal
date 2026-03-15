// static/js/waste_charts.js

function renderWasteCharts(typeLabels, typeValues, trendMonths, trendValues) {
    // 1. 도넛 차트 (종류별 비중)
    new Chart(document.getElementById('typeChart'), {
        type: 'doughnut',
        data: {
            labels: typeLabels,
            datasets: [{
                data: typeValues,
                backgroundColor: ['#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b']
            }]
        },
        options: { responsive: true }
    });

    // 2. 라인 차트 (월별 추이)
    new Chart(document.getElementById('trendChart'), {
        type: 'line',
        data: {
            labels: trendMonths,
            datasets: [{
                label: '배출량(kg)',
                data: trendValues,
                borderColor: '#4e73df',
                fill: false,
                tension: 0.1
            }]
        },
        options: { responsive: true }
    });
}