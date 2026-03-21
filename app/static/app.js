'use strict';

// ── Auth 工具 ─────────────────────────────────────────────
function getToken() { return localStorage.getItem('token'); }
function getUsername() { return localStorage.getItem('username'); }

function requireAuth() {
  if (!getToken()) { location.href = '/login'; }
}

function logout() {
  localStorage.removeItem('token');
  localStorage.removeItem('username');
  location.href = '/login';
}

function authHeaders() {
  return { 'Authorization': `Bearer ${getToken()}` };
}

// ── 初始化导航栏 ──────────────────────────────────────────
function initNav() {
  const usernameEl = document.getElementById('nav-username');
  const logoutBtn  = document.getElementById('nav-logout');
  if (usernameEl) usernameEl.textContent = getUsername() || '';
  if (logoutBtn)  logoutBtn.addEventListener('click', logout);
}

// ── 日期格式化 ────────────────────────────────────────────
function fmtDate(time) {
  if (time && typeof time === 'object' && 'year' in time) {
    return `${time.year}-${String(time.month).padStart(2,'0')}-${String(time.day).padStart(2,'0')}`;
  }
  if (typeof time === 'number') {
    const d = new Date(time * 1000);
    return `${d.getUTCFullYear()}-${String(d.getUTCMonth()+1).padStart(2,'0')}-${String(d.getUTCDate()).padStart(2,'0')}`;
  }
  return String(time).slice(0, 10);
}

// 横轴刻度
function tickFormatter(time, tickMarkType) {
  const s = fmtDate(time);
  const [y, m, d] = s.split('-').map(Number);
  switch (tickMarkType) {
    case 0: return `${y}年`;
    case 1: return `${y}/${String(m).padStart(2,'0')}`;
    case 2: return `${m}/${d}`;
    default: return s;
  }
}

// ── 配置 ──────────────────────────────────────────────────
const VISIBLE_BARS = { 1: 25, 3: 70, 6: 135, 12: 260, 36: 780 };

const MA_COLORS = {
  5:   '#FF6B35',
  10:  '#FFE66D',
  15:  '#F9A825',
  20:  '#4ECDC4',
  30:  '#A8E6CF',
  60:  '#C7CEEA',
  120: '#FF8B94',
  250: '#9B9B9B',
};
const MA_WINDOWS = Object.keys(MA_COLORS).map(Number);

// ── 状态 ─────────────────────────────────────────────────
let chart, candleSeries;
let volChart, volumeSeries;
const maSeries = {};
const candleMap = new Map();
const volumeMap = new Map();

let currentCode  = null;
let currentAdj   = 'qfq';
let currentRange = 6;
let activeMA     = new Set([5, 10, 20, 60]);

// ── 公共图表配置 ──────────────────────────────────────────
const BASE_OPTS = {
  layout:     { background: { color: '#131722' }, textColor: '#787b86' },
  grid:       { vertLines: { color: '#1e222d' }, horzLines: { color: '#1e222d' } },
  rightPriceScale: { borderColor: '#2a2e39' },
};

const BASE_TIMESCALE = {
  borderColor:       '#2a2e39',
  fixLeftEdge:       true,
  fixRightEdge:      true,
  timeVisible:       false,
  tickMarkFormatter: tickFormatter,
};

// ── 初始化图表 ────────────────────────────────────────────
function initChart() {
  const candleEl = document.getElementById('candle-chart');
  const volumeEl = document.getElementById('volume-chart');

  chart = LightweightCharts.createChart(candleEl, {
    ...BASE_OPTS,
    crosshair:    { mode: LightweightCharts.CrosshairMode.Normal },
    localization: { timeFormatter: fmtDate },
    timeScale:    { ...BASE_TIMESCALE, visible: false },
    width:  candleEl.clientWidth,
    height: candleEl.clientHeight,
  });

  candleSeries = chart.addCandlestickSeries({
    upColor:       '#ef5350',
    downColor:     '#26a69a',
    borderVisible: false,
    wickUpColor:   '#ef5350',
    wickDownColor: '#26a69a',
  });

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

  volChart = LightweightCharts.createChart(volumeEl, {
    ...BASE_OPTS,
    localization: { timeFormatter: fmtDate },
    rightPriceScale: {
      borderColor:  '#2a2e39',
      scaleMargins: { top: 0.08, bottom: 0.02 },
    },
    timeScale: { ...BASE_TIMESCALE },
    width:  volumeEl.clientWidth,
    height: volumeEl.clientHeight,
  });

  volumeSeries = volChart.addHistogramSeries({
    priceFormat:  { type: 'volume' },
    priceScaleId: 'right',
  });

  chart.subscribeCrosshairMove(param => {
    if (!param.time) { volChart.clearCrosshairPosition(); return; }
    const vol = volumeMap.get(fmtDate(param.time)) ?? 0;
    volChart.setCrosshairPosition(vol, param.time, volumeSeries);
  });
  volChart.subscribeCrosshairMove(param => {
    if (!param.time) { chart.clearCrosshairPosition(); return; }
    const price = candleMap.get(fmtDate(param.time)) ?? 0;
    chart.setCrosshairPosition(price, param.time, candleSeries);
  });

  let syncing = false;
  chart.timeScale().subscribeVisibleLogicalRangeChange(range => {
    if (syncing || !range) return;
    syncing = true;
    volChart.timeScale().setVisibleLogicalRange(range);
    syncing = false;
  });
  volChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
    if (syncing || !range) return;
    syncing = true;
    chart.timeScale().setVisibleLogicalRange(range);
    syncing = false;
  });

  const ro = new ResizeObserver(() => {
    chart.applyOptions({   width: candleEl.clientWidth, height: candleEl.clientHeight });
    volChart.applyOptions({ width: volumeEl.clientWidth, height: volumeEl.clientHeight });
  });
  ro.observe(candleEl);
  ro.observe(volumeEl);
}

// ── 计算起始日期 ──────────────────────────────────────────
function calcStartDate(months) {
  if (!months) return null;
  const d = new Date();
  d.setMonth(d.getMonth() - months);
  return d.toISOString().slice(0, 10).replace(/-/g, '');
}

// ── 加载数据 ──────────────────────────────────────────────
async function loadData(tsCode) {
  if (!tsCode) return;
  currentCode = tsCode;

  const params = new URLSearchParams({ adj: currentAdj });
  const start  = calcStartDate(currentRange);
  if (start) params.set('start', start);

  const [dailyRes, infoRes] = await Promise.all([
    fetch(`/api/stock/${tsCode}/daily?${params}`, { headers: authHeaders() }),
    fetch(`/api/stock/${tsCode}/info`,            { headers: authHeaders() }),
  ]);

  if (dailyRes.status === 401 || infoRes.status === 401) { logout(); return; }

  const data = await dailyRes.json();
  const info = await infoRes.json();

  document.getElementById('stock-name').textContent =
    info ? `${info.name}（${info.ts_code}）` : tsCode;

  candleSeries.setData(data.candles);
  volumeSeries.setData(data.volume);

  candleMap.clear();
  data.candles.forEach(c => candleMap.set(c.time, c.close));
  volumeMap.clear();
  data.volume.forEach(v => volumeMap.set(v.time, v.value));

  const candles = data.candles;
  if (candles.length > 0) {
    const targetBars = VISIBLE_BARS[currentRange];
    if (!targetBars || candles.length <= targetBars) {
      chart.timeScale().fitContent();
      volChart.timeScale().fitContent();
    } else {
      const range = {
        from: candles[candles.length - targetBars].time,
        to:   candles[candles.length - 1].time,
      };
      chart.timeScale().setVisibleRange(range);
      volChart.timeScale().setVisibleRange(range);
    }
  }

  const maSnapshot = data.ma;
  requestAnimationFrame(() => {
    MA_WINDOWS.forEach(w => maSeries[w].setData(maSnapshot[String(w)] || []));
  });
}

// ── 搜索 ──────────────────────────────────────────────────
let searchTimer = null;
const searchEl      = document.getElementById('search');
const suggestionsEl = document.getElementById('suggestions');

searchEl.addEventListener('input', () => {
  clearTimeout(searchTimer);
  const q = searchEl.value.trim();
  if (!q) { hideSuggestions(); return; }
  searchTimer = setTimeout(async () => {
    const res     = await fetch(`/api/stocks/search?q=${encodeURIComponent(q)}`, { headers: authHeaders() });
    if (res.status === 401) { logout(); return; }
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
    const item     = document.createElement('div');
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

// ── 复权切换 ──────────────────────────────────────────────
document.querySelectorAll('.adj-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.adj-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentAdj = btn.dataset.adj;
    if (currentCode) loadData(currentCode);
  });
});

// ── 均线开关 ──────────────────────────────────────────────
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

// ── 时间范围切换 ──────────────────────────────────────────
document.querySelectorAll('.range-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentRange = parseInt(btn.dataset.months);
    if (currentCode) loadData(currentCode);
  });
});

// ── 启动 ──────────────────────────────────────────────────
requireAuth();
initNav();
initChart();

// 读取 URL 参数 ?code=600519.SH 自动加载
const urlCode = new URLSearchParams(location.search).get('code');
if (urlCode) loadData(urlCode);
