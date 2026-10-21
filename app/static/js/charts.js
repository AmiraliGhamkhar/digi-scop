(() => {
  'use strict';

  let rankChart = null;
  let priceChart = null;
  const palette = ['#0b9495', '#3775c5', '#9b6517', '#7b61a8', '#287a54'];
  const faNumber = new Intl.NumberFormat('fa-IR');
  const shortDate = new Intl.DateTimeFormat('fa-IR', { month: 'short', day: 'numeric' });

  const commonOptions = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { intersect: false, mode: 'index' },
    animation: { duration: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 250 },
    plugins: {
      legend: { labels: { usePointStyle: true, boxWidth: 7, font: { family: 'Vazirmatn', size: 9 } } },
      tooltip: { titleFont: { family: 'Vazirmatn' }, bodyFont: { family: 'Vazirmatn' }, rtl: true },
    },
    scales: {
      x: { grid: { display: false }, ticks: { maxTicksLimit: 7, font: { family: 'Vazirmatn', size: 9 } } },
      y: { border: { display: false }, grid: { color: '#edf1f5' }, ticks: { font: { family: 'Vazirmatn', size: 9 } } },
    },
  };

  const dateLabel = (iso) => {
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? '—' : shortDate.format(date);
  };

  const updateRank = (history) => {
    if (rankChart) { rankChart.destroy(); rankChart = null; }
    const canvas = document.getElementById('rank-chart');
    const empty = document.getElementById('rank-chart-empty');
    if (!window.Chart || !history || history.length === 0) {
      empty.classList.remove('hidden');
      return;
    }
    const groups = new Map();
    history.forEach((point) => {
      const label = point.scope_type === 'global' ? 'کل بازار' : `دسته ${point.scope_id ?? ''}`;
      if (!groups.has(label)) groups.set(label, []);
      groups.get(label).push(point);
    });
    const labels = [...new Set(history.map((point) => point.observed_at))].sort();
    const datasets = [...groups.entries()].map(([label, points], index) => {
      const lookup = new Map(points.map((point) => [point.observed_at, point.rank_position]));
      return {
        label,
        data: labels.map((value) => lookup.get(value) ?? null),
        borderColor: palette[index % palette.length],
        backgroundColor: palette[index % palette.length],
        borderWidth: 2,
        pointRadius: 2.5,
        pointHoverRadius: 4,
        tension: 0.18,
        spanGaps: false,
      };
    });
    rankChart = new window.Chart(canvas, {
      type: 'line',
      data: { labels: labels.map(dateLabel), datasets },
      options: {
        ...commonOptions,
        scales: {
          ...commonOptions.scales,
          y: { ...commonOptions.scales.y, reverse: true, beginAtZero: false, ticks: { ...commonOptions.scales.y.ticks, precision: 0 } },
        },
      },
    });
    empty.classList.add('hidden');
  };

  const updatePrice = (history) => {
    if (priceChart) { priceChart.destroy(); priceChart = null; }
    const canvas = document.getElementById('price-chart');
    const empty = document.getElementById('price-chart-empty');
    const points = (history || []).filter((point) => point.price_toman !== null);
    if (!window.Chart || points.length === 0) {
      empty.classList.remove('hidden');
      return;
    }
    const variants = new Map();
    points.forEach((point) => {
      const key = point.variant_key || 'default';
      if (!variants.has(key)) variants.set(key, []);
      variants.get(key).push(point);
    });
    const labels = [...new Set(points.map((point) => point.observed_at))].sort();
    const datasets = [...variants.entries()].slice(0, 5).map(([variant, rows], index) => {
      const lookup = new Map(rows.map((point) => [point.observed_at, point.price_toman]));
      return {
        label: variant === 'default' ? 'قیمت مشاهده‌شده' : variant,
        data: labels.map((value) => lookup.get(value) ?? null),
        borderColor: palette[(index + 1) % palette.length],
        backgroundColor: palette[(index + 1) % palette.length],
        borderWidth: 2,
        pointRadius: 2,
        tension: 0.18,
        spanGaps: true,
      };
    });
    priceChart = new window.Chart(canvas, {
      type: 'line',
      data: { labels: labels.map(dateLabel), datasets },
      options: {
        ...commonOptions,
        plugins: {
          ...commonOptions.plugins,
          tooltip: {
            ...commonOptions.plugins.tooltip,
            callbacks: { label: (context) => `${context.dataset.label}: ${faNumber.format(context.parsed.y)} تومان` },
          },
        },
        scales: {
          ...commonOptions.scales,
          y: { ...commonOptions.scales.y, ticks: { ...commonOptions.scales.y.ticks, callback: (value) => faNumber.format(value) } },
        },
      },
    });
    empty.classList.add('hidden');
  };

  window.DigiCharts = Object.freeze({ updateRank, updatePrice });
})();
