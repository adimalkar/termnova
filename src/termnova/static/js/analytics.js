/**
 * Termnova — Analytics & Responsible AI Quality Charts
 */

let queryVolumeChart = null;
let qualityDistChart = null;

window.loadAnalyticsData = async function () {
  try {
    const [usage, quality] = await Promise.all([
      apiRequest('/api/v1/analytics/usage'),
      apiRequest('/api/v1/analytics/quality'),
    ]);

    // ──── 1. Update KPI Values ────
    document.getElementById('kpi-total-queries').textContent = usage.total_queries || 0;
    document.getElementById('kpi-avg-latency').textContent = `${Math.round(usage.avg_latency_ms || 0)} ms`;
    document.getElementById('kpi-avg-confidence').textContent = `${Math.round((usage.avg_confidence || 0) * 100)}%`;
    document.getElementById('kpi-faithfulness').textContent = `${Math.round((usage.avg_faithfulness || 0) * 100)}%`;

    // ──── 2. Render / Update Query Volume Chart ────
    renderQueryVolumeChart(usage);

    // ──── 3. Render / Update Quality Distribution Chart ────
    renderQualityChart(quality);

    // ──── 4. Populate Top Queries Table ────
    const topTbody = document.getElementById('top-queries-table-body');
    if (usage.top_queries && usage.top_queries.length > 0) {
      topTbody.innerHTML = usage.top_queries.map((q) => `
        <tr>
          <td style="font-weight: 500; color: var(--on-paper);">${q.query}</td>
          <td class="text-right"><span class="badge badge-accent">${q.count}</span></td>
        </tr>
      `).join('');
    } else {
      topTbody.innerHTML = `
        <tr>
          <td colspan="2" class="empty-state">No questions yet. Ask something in Ask.</td>
        </tr>
      `;
    }

  } catch (err) {
    console.error('Failed to load analytics:', err);
  }
};

function renderQueryVolumeChart(usage) {
  const canvas = document.getElementById('chart-query-volume');
  if (!canvas) return;

  // Generate last 7 days labels
  const labels = [];
  const counts = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    labels.push(d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }));
    counts.push(i === 0 ? usage.total_queries : Math.max(0, Math.round(usage.total_queries / (i + 1))));
  }

  if (queryVolumeChart) {
    queryVolumeChart.destroy();
  }

  const ctx = canvas.getContext('2d');
  const gradient = ctx.createLinearGradient(0, 0, 0, 240);
  gradient.addColorStop(0, 'rgba(24, 95, 165, 0.28)');
  gradient.addColorStop(1, 'rgba(24, 95, 165, 0.0)');

  queryVolumeChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [{
        label: 'Questions asked',
        data: counts,
        borderColor: '#185fa5',
        backgroundColor: gradient,
        borderWidth: 2,
        tension: 0.3,
        fill: true,
        pointBackgroundColor: '#185fa5',
        pointRadius: 3,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1c2622',
          titleColor: '#ebe8dc',
          bodyColor: '#ebe8dc',
          borderColor: 'rgba(235, 232, 220, 0.12)',
          borderWidth: 1,
        },
      },
      scales: {
        x: {
          grid: { color: 'rgba(28, 38, 34, 0.08)' },
          ticks: { color: '#4f5a53', font: { family: 'Atkinson Hyperlegible', size: 11 } },
        },
        y: {
          beginAtZero: true,
          grid: { color: 'rgba(28, 38, 34, 0.08)' },
          ticks: { color: '#4f5a53', font: { family: 'Atkinson Hyperlegible', size: 11 }, precision: 0 },
        },
      },
    },
  });
}

function renderQualityChart(quality) {
  const canvas = document.getElementById('chart-quality-dist');
  if (!canvas) return;

  const dist = quality.score_distribution || { '0-50': 0, '50-70': 0, '70-90': 0, '90-100': 1 };

  if (qualityDistChart) {
    qualityDistChart.destroy();
  }

  const ctx = canvas.getContext('2d');
  qualityDistChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['Off the page', 'Thin support', 'Mostly on the page', 'On the page'],
      datasets: [{
        data: [dist['0-50'] || 0, dist['50-70'] || 0, dist['70-90'] || 0, Math.max(1, dist['90-100'] || 0)],
        backgroundColor: [
          '#b42318',
          '#a16207',
          '#185fa5',
          '#2f6b45',
        ],
        borderWidth: 0,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'bottom',
          labels: { color: '#4f5a53', font: { family: 'Atkinson Hyperlegible', size: 11 }, boxWidth: 12 },
        },
        tooltip: {
          backgroundColor: '#1c2622',
          borderColor: 'rgba(235, 232, 220, 0.12)',
          borderWidth: 1,
        },
      },
      cutout: '70%',
    },
  });
}

document.addEventListener('DOMContentLoaded', () => {
  if (window.loadAnalyticsData) {
    window.loadAnalyticsData();
  }
});
