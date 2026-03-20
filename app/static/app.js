'use strict';

// ── 日期格式化（兼容 BusinessDay 对象 / UNIX 秒时间戳 / 字符串） ──
function fmtDate(time) {
  if (time && typeof time === 'object' && 'year' in time) {
    // { year, month, day }
    return `${time.year}-${String(time.month).padStart(2,'0')}-${String(time.day).padStart(2,'0')}`;
  }
  if (typeof time === 'number') {
    // UNIX 秒级时间戳（库内部实际传递的形式）
    const d = new Date(time * 1000);
    return `${d.getUTCFullYear()}-${String(d.getUTCMonth()+1).padStart(2,'0')}-${String(d.getUTCDate()).padStart(2,'0')}`;
  }
  return String(time).slice(0, 10);
}

// 横轴刻度：年 / 年月 / 日（仅周一·周三·周五显示）
const _WEEK = ['日','一','二','三','四','五','六'];
function tickFormatter(time, tickMarkType) {
  const s = fmtDate(time);
  const [y, m, d] = s.split('-').map(Number);
  switch (tickMarkType) {
    case 0: return `${y}年`;
    case 1: return `${y}/${String(m).padStart(2,'0')}`;
    case 2: {
      const dow = new Date(Date.UTC(y, m - 1, d)).getUTCDay(); // 0=日 1=一 … 6=六
      if (dow === 1 || dow === 3 || dow === 5) {
        return `${String(m).padStart(2,'0')}/${String(d).padStart(2,'0')} 周${_WEEK[dow]}`;
      }
      return '';   // 周二·周四·周末不显示标签
    }
    default: return s;
  }
}

// ── 每个时间范围默认显示的 K 线根数 ─────────────────────────
//   短周期全部显示；3年/全部默认只显示最近 ~1 年，可左滑查看更早
const VISIBLE_BARS = { 1: 25, 3: 70, 6: 135, 12: 260, 36: 260, 0: 260 };

// ── MA 配色 ──────────────────────────────────────────────────
const MA_COLORS = {
  5:   '#FF6B35',
  10:  '#FFE66D',
  20:  '#4ECDC4',
  30:  '#A8E6CF',
  60:  '#C7CEEA',
  120: '#FF8B94',
  250: '#9B9B9B',
};
const MA_WINDOWS = Object.keys(MA_COLORS).map(Number);

// ── 状态 ─────────────────────────────────────────────────────
let chart, candleSeries, volumeSeries;
const maSeries = {};

let currentCode  = null;
let currentAdj   = 'qfq';
let currentRange = 6;        // months；0 = 全部
let activeMA     = new Set([5, 10, 20, 60]);

// ── 初始化图表 ───────────────────────────────────────────────
function initChart() {
  const container = document.getElementById('chart-container');

  chart = LightweightCharts.createChart(container, {
    layout: {
      background: { color: '#131722' },
      textColor:  '#787b86',
    },
    grid: {
      vertLines: { color: '#1e222d' },
      horzLines: { color: '#1e222d' },
    },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    localization: {
      timeFormatter: fmtDate,   // 十字线底部日期标签
    },
    rightPriceScale: { borderColor: '#2a2e39' },
    timeScale: {
      borderColor:      '#2a2e39',
      timeVisible:      false,   // 日线无需显示时间，避免出现 00:00:00
      fixLeftEdge:      true,
      fixRightEdge:     true,
      tickMarkFormatter: tickFormatter,  // 横轴刻度标签
    },
    width:  container.clientWidth,
    height: container.clientHeight,
  });

  // K 线
  candleSeries = chart.addCandlestickSeries({
    upColor:      '#26a69a',
    downColor:    '#ef5350',
    borderVisible: false,
    wickUpColor:   '#26a69a',
    wickDownColor: '#ef5350',
  });

  // 成交量（叠加在主图底部 25%）
  volumeSeries = chart.addHistogramSeries({
    priceFormat:  { type: 'volume' },
    priceScaleId: 'volume',
  });
  chart.priceScale('volume').applyOptions({
    scaleMargins: { top: 0.75, bottom: 0 },
  });

  // 均线
  MA_WINDOWS.forEach(w => {
    maSeries[w] = chart.addLineSeries({
      color:                  MA_COLORS[w],
      lineWidth:              1,
      priceLineVisible:       false,
      lastValueVisible:       false,
      crosshairMarkerVisible: false,
      visible:                activeMA.has(w),
    });
  });

  // 响应窗口大小
  const ro = new ResizeObserver(() => {
    chart.applyOptions({
      width:  container.clientWidth,
      height: container.clientHeight,
    });
  });
  ro.observe(container);
}

// ── 计算起始日期 ─────────────────────────────────────────────
function calcStartDate(months) {
  if (!months) return null;
  const d = new Date();
  d.setMonth(d.getMonth() - months);
  return d.toISOString().slice(0, 10).replace(/-/g, '');
}

// ── 加载数据 ─────────────────────────────────────────────────
async function loadData(tsCode) {
  if (!tsCode) return;
  currentCode = tsCode;

  const params = new URLSearchParams({ adj: currentAdj });
  const start  = calcStartDate(currentRange);
  if (start) params.set('start', start);

  const [dailyRes, infoRes] = await Promise.all([
    fetch(`/api/stock/${tsCode}/daily?${params}`),
    fetch(`/api/stock/${tsCode}/info`),
  ]);
  const data = await dailyRes.json();
  const info = await infoRes.json();

  // 更新标题
  document.getElementById('stock-name').textContent =
    info ? `${info.name}（${info.ts_code}）` : tsCode;

  // K 线
  candleSeries.setData(data.candles);

  // 成交量
  volumeSeries.setData(data.volume);

  // 均线
  MA_WINDOWS.forEach(w => {
    maSeries[w].setData(data.ma[String(w)] || []);
  });

  // 设置可视 K 线窗口
  const candles = data.candles;
  if (candles.length > 0) {
    const targetBars = VISIBLE_BARS[currentRange] ?? 260;
    if (candles.length <= targetBars) {
      chart.timeScale().fitContent();
    } else {
      chart.timeScale().setVisibleRange({
        from: candles[candles.length - targetBars].time,
        to:   candles[candles.length - 1].time,
      });
    }
  }
}

// ── 搜索 ─────────────────────────────────────────────────────
let searchTimer = null;
const searchEl      = document.getElementById('search');
const suggestionsEl = document.getElementById('suggestions');

searchEl.addEventListener('input', () => {
  clearTimeout(searchTimer);
  const q = searchEl.value.trim();
  if (!q) { hideSuggestions(); return; }
  searchTimer = setTimeout(async () => {
    const res     = await fetch(`/api/stocks/search?q=${encodeURIComponent(q)}`);
    const results = await res.json();
    renderSuggestions(results);
  }, 180);
});

searchEl.addEventListener('keydown', e => {
  if (e.key === 'Escape') hideSuggestions();
  if (e.key === 'Enter') {
    const first = suggestionsEl.querySelector('.sug-item');
    if (first) first.click();
  }
});

document.addEventListener('click', e => {
  if (!e.target.closest('#search-wrap')) hideSuggestions();
});

function renderSuggestions(results) {
  suggestionsEl.innerHTML = '';
  if (!results.length) { hideSuggestions(); return; }
  results.forEach(r => {
    const item    = document.createElement('div');
    item.className = 'sug-item';
    item.innerHTML = `<span class="sug-code">${r.ts_code}</span><span class="sug-name">${r.name}</span>`;
    item.addEventListener('click', () => {
      searchEl.value = r.ts_code;
      hideSuggestions();
      loadData(r.ts_code);
    });
    suggestionsEl.appendChild(item);
  });
  suggestionsEl.style.display = 'block';
}

function hideSuggestions() {
  suggestionsEl.style.display = 'none';
}

// ── 复权切换 ─────────────────────────────────────────────────
document.querySelectorAll('.adj-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.adj-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentAdj = btn.dataset.adj;
    if (currentCode) loadData(currentCode);
  });
});

// ── 均线开关 ─────────────────────────────────────────────────
document.querySelectorAll('.ma-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const w = parseInt(btn.dataset.ma);
    if (activeMA.has(w)) {
      activeMA.delete(w);
      btn.classList.remove('active');
      maSeries[w]?.applyOptions({ visible: false });
    } else {
      activeMA.add(w);
      btn.classList.add('active');
      maSeries[w]?.applyOptions({ visible: true });
    }
  });
});

// ── 时间范围切换 ─────────────────────────────────────────────
document.querySelectorAll('.range-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentRange = parseInt(btn.dataset.months);
    if (currentCode) loadData(currentCode);
  });
});

// ── 启动 ─────────────────────────────────────────────────────
initChart();
