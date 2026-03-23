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
const VISIBLE_BARS = {
  daily:   { 1: 25,  3: 70,  6: 135, 12: 260, 36: 780, 0: 0 },
  weekly:  { 1: 5,   3: 13,  6: 26,  12: 52,  36: 156, 0: 0 },
  monthly: { 1: 1,   3: 3,   6: 6,   12: 12,  36: 36,  0: 0 },
};

const KLINE_RED   = '#E04040';
const KLINE_GREEN = '#45AA55';
const KLINE_WHITE = '#d1d4dc';

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
let currentFreq  = 'daily';
let currentRange = 6;
let activeMA     = new Set([5, 10, 20, 60]);
let allCandleCount = 0;   // 全量已加载的 K 线根数，供滑动窗口计算

const detailMap = new Map();  // time → {open,high,low,close,pct_chg,amount,turnover_rate,prevClose}
let currentIsIndex = false;

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

  const CROSSHAIR_STYLE = {
    mode: LightweightCharts.CrosshairMode.Normal,
    vertLine: {
      color: '#787b86', width: 1,
      style: LightweightCharts.LineStyle.Dotted,
      labelBackgroundColor: '#2a2e39',
    },
    horzLine: {
      color: '#787b86', width: 1,
      style: LightweightCharts.LineStyle.Dotted,
      labelBackgroundColor: '#2a2e39',
    },
  };

  chart = LightweightCharts.createChart(candleEl, {
    ...BASE_OPTS,
    crosshair:    CROSSHAIR_STYLE,
    localization: { timeFormatter: fmtDate },
    timeScale:    { ...BASE_TIMESCALE, visible: false },
    width:  candleEl.clientWidth,
    height: candleEl.clientHeight,
  });

  // 阳线（红）空心：只有外框，无填充；阴线（绿）实心
  const UP_COLOR   = '#E04040';
  const DOWN_COLOR = '#45AA55';
  candleSeries = chart.addCandlestickSeries({
    upColor:         'rgba(0,0,0,0)',  // 透明填充 → 空心
    downColor:        DOWN_COLOR,
    borderVisible:    true,
    borderUpColor:    UP_COLOR,
    borderDownColor:  DOWN_COLOR,
    wickUpColor:      UP_COLOR,
    wickDownColor:    DOWN_COLOR,
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
    crosshair:    CROSSHAIR_STYLE,
    localization: { timeFormatter: fmtDate },
    rightPriceScale: {
      borderColor:  '#2a2e39',
      scaleMargins: { top: 0.08, bottom: 0.02 },
    },
    timeScale:    { ...BASE_TIMESCALE },
    handleScroll: { pressedMouseMove: false, horzTouchDrag: false },
    width:  volumeEl.clientWidth,
    height: volumeEl.clientHeight,
  });

  volumeSeries = volChart.addHistogramSeries({
    priceFormat:  { type: 'volume' },
    priceScaleId: 'right',
  });

  chart.subscribeCrosshairMove(param => {
    if (!_crosshairOn) return;
    if (!param.time) {
      volChart.clearCrosshairPosition();
      hideDetailPanel();
      return;
    }
    const t = fmtDate(param.time);
    const vol = volumeMap.get(t) ?? 0;
    volChart.setCrosshairPosition(vol, param.time, volumeSeries);
    updateDetailPanel(t, param.point);
  });
  volChart.subscribeCrosshairMove(param => {
    if (!_crosshairOn) return;
    if (!param.time) {
      chart.clearCrosshairPosition();
      hideDetailPanel();
      return;
    }
    const t = fmtDate(param.time);
    const price = candleMap.get(t) ?? 0;
    chart.setCrosshairPosition(price, param.time, candleSeries);
    updateDetailPanel(t, param.point);
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
    syncPriceScaleWidth();
  });
  ro.observe(candleEl);
  ro.observe(volumeEl);
}

// ── 同步两图右侧价格刻度宽度，消除网格错位 ───────────────
function syncPriceScaleWidth() {
  const w = Math.max(
    chart.priceScale('right').width(),
    volChart.priceScale('right').width(),
  );
  chart.applyOptions({   rightPriceScale: { minimumWidth: w } });
  volChart.applyOptions({ rightPriceScale: { minimumWidth: w } });
}

// ── 十字线开关状态 ────────────────────────────────────────
let _crosshairOn = false;

function applyCrosshairVisibility() {
  const v = _crosshairOn;
  const opts = {
    vertLine: { visible: v, labelVisible: v },
    horzLine: { visible: v, labelVisible: v },
  };
  chart.applyOptions({ crosshair: opts });
  volChart.applyOptions({ crosshair: opts });
  if (!v) {
    chart.clearCrosshairPosition();
    volChart.clearCrosshairPosition();
    hideDetailPanel();
  }
}

// ── K 线详情浮窗 ──────────────────────────────────────────
function _colorOf(val, ref) {
  if (ref === null || val === null || ref === undefined || val === undefined) return KLINE_WHITE;
  if (val > ref) return KLINE_RED;
  if (val < ref) return KLINE_GREEN;
  return KLINE_WHITE;
}

function _fmtVol(vol) {
  if (vol === null || vol === undefined) return '-';
  if (vol >= 1e8)  return (vol / 1e8).toFixed(2) + '亿手';
  if (vol >= 1e4)  return (vol / 1e4).toFixed(2) + '万手';
  return vol.toFixed(0) + '手';
}

function _fmtAmount(amount) {
  // amount 单位：千元
  if (amount === null || amount === undefined) return '-';
  if (amount >= 1e5) return (amount / 1e5).toFixed(2) + '亿';
  if (amount >= 10)  return (amount / 10).toFixed(2) + '万';
  return amount.toFixed(0) + '千';
}

function _fmtPct(v) {
  if (v === null || v === undefined) return '-';
  return (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
}

function _setText(id, text, color) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.style.color  = color;
}

function updateDetailPanel(timeStr, point) {
  const detail = detailMap.get(timeStr);
  if (!detail) { hideDetailPanel(); return; }

  const panel = document.getElementById('kline-detail');
  if (!panel) return;

  const { open, high, low, close, pct_chg, amount, turnover_rate, prevClose } = detail;
  const vol = volumeMap.get(timeStr);

  // 颜色计算
  const openColor  = _colorOf(open,  prevClose);
  const closeColor = _colorOf(close, open);
  const highColor  = _colorOf(high,  prevClose);
  const lowColor   = _colorOf(low,   prevClose);

  // 振幅 = (最高 - 最低) / 昨收 × 100%
  const ampStr = (prevClose !== null && prevClose !== undefined && prevClose !== 0)
    ? ((high - low) / prevClose * 100).toFixed(2) + '%'
    : '-';

  _setText('kd-time',     timeStr,                   KLINE_WHITE);
  _setText('kd-open',     open.toFixed(2),            openColor);
  _setText('kd-close',    close.toFixed(2),           closeColor);
  _setText('kd-high',     high.toFixed(2),            highColor);
  _setText('kd-low',      low.toFixed(2),             lowColor);
  _setText('kd-pct',      _fmtPct(pct_chg),           closeColor);
  _setText('kd-amp',      ampStr,                     KLINE_WHITE);
  _setText('kd-vol',      _fmtVol(vol),               KLINE_WHITE);
  _setText('kd-amount',   _fmtAmount(amount),         KLINE_WHITE);
  if (!currentIsIndex) {
    const trStr = (turnover_rate !== null && turnover_rate !== undefined)
      ? turnover_rate.toFixed(2) + '%' : '-';
    _setText('kd-turnover', trStr, KLINE_WHITE);
  }

  panel.style.display = '';

  // 位置：十字线 x < 面板宽+边距 时切换到右上角，否则默认左上角
  // 右侧时，right 偏移量 = 纵坐标轴宽度，确保面板右边缘对齐 K 线绘图区右边缘
  if (point) {
    const panelW       = panel.offsetWidth + 15;
    const priceScaleW  = chart.priceScale('right').width();
    if (point.x < panelW) {
      panel.style.left  = 'auto';
      panel.style.right = priceScaleW + 'px';
    } else {
      panel.style.left  = '10px';
      panel.style.right = 'auto';
    }
  }
}

function hideDetailPanel() {
  const panel = document.getElementById('kline-detail');
  if (panel) panel.style.display = 'none';
}

// ── 单击两图区域切换十字线；左键拖拽仅限K线图 ────────────
function setupInteraction() {
  const candleEl = document.getElementById('candle-chart');
  const volumeEl = document.getElementById('volume-chart');
  const DRAG_PX  = 4;
  let   _downPos = null;

  [candleEl, volumeEl].forEach(el => {
    el.addEventListener('mousedown', e => {
      if (e.button === 0) _downPos = { x: e.clientX, y: e.clientY };
    });
    el.addEventListener('mouseup', e => {
      if (e.button === 0 && _downPos) {
        const moved = Math.abs(e.clientX - _downPos.x) > DRAG_PX
                   || Math.abs(e.clientY - _downPos.y) > DRAG_PX;
        if (!moved) {
          _crosshairOn = !_crosshairOn;
          applyCrosshairVisibility();
        }
        _downPos = null;
      }
    });
  });

  // 初始状态：隐藏十字线
  applyCrosshairVisibility();
}

// ── 加载数据（全量加载，前端控制滑动窗口） ────────────────
async function loadData(tsCode) {
  if (!tsCode) return;
  currentCode = tsCode;

  // 不传 start/end，一次性取全部历史，拖动时才能滑窗到更早的K线
  const params = new URLSearchParams({ adj: currentAdj, freq: currentFreq });

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

  // 构建浮窗详情 Map，附带 prevClose（前一日收盘价，用于颜色判断和振幅计算）
  detailMap.clear();
  data.candles.forEach((c, i) => {
    detailMap.set(c.time, { ...c, prevClose: i > 0 ? data.candles[i - 1].close : null });
  });

  currentIsIndex = data.is_index || false;
  const turnoverRow = document.getElementById('kd-turnover-row');
  if (turnoverRow) turnoverRow.style.display = currentIsIndex ? 'none' : '';

  allCandleCount = data.candles.length;
  applyVisibleRange();

  const maSnapshot = data.ma;
  requestAnimationFrame(() => {
    MA_WINDOWS.forEach(w => maSeries[w].setData(maSnapshot[String(w)] || []));
    syncPriceScaleWidth();
  });
}

// ── 按 currentRange 设置可见窗口（不重新请求数据） ─────────
function applyVisibleRange() {
  if (!allCandleCount) return;
  const targetBars = (VISIBLE_BARS[currentFreq] || VISIBLE_BARS.daily)[currentRange];
  if (!targetBars || allCandleCount <= targetBars) {
    // 全部 或 数据不足指定范围 → 自适应
    chart.timeScale().fitContent();
    volChart.timeScale().fitContent();
  } else {
    // 定位到最新的 targetBars 根，logical index 从 0 起
    const range = { from: allCandleCount - targetBars, to: allCandleCount - 1 };
    chart.timeScale().setVisibleLogicalRange(range);
    volChart.timeScale().setVisibleLogicalRange(range);
  }
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
    const badge = r.type === 'index'
      ? `<span class="sug-badge sug-badge-index">指数</span>`
      : '';
    item.innerHTML = `${badge}<span class="sug-code">${r.ts_code}</span><span class="sug-name">${r.name}</span>`;
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

// ── 频率切换（日K / 周K / 月K）────────────────────────────
function updateAdjBtnState() {
  const disabled = currentFreq !== 'daily';
  document.querySelectorAll('.adj-btn').forEach(b => {
    b.disabled = disabled;
    b.classList.toggle('btn-disabled', disabled);
  });
}

document.querySelectorAll('.freq-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    if (btn.dataset.freq === currentFreq) return;
    document.querySelectorAll('.freq-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentFreq = btn.dataset.freq;
    updateAdjBtnState();
    if (currentCode) loadData(currentCode);
  });
});

// ── 复权切换 ──────────────────────────────────────────────
document.querySelectorAll('.adj-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    if (currentFreq !== 'daily') return;   // 周/月线无复权数据，忽略点击
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

// ── 时间范围切换（只改可见窗口，不重新加载） ─────────────
document.querySelectorAll('.range-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentRange = parseInt(btn.dataset.months);
    applyVisibleRange();
  });
});

// ── 启动 ──────────────────────────────────────────────────
requireAuth();
initNav();
initChart();
setupInteraction();

// 读取 URL 参数 ?code=，无参数时默认加载上证指数
const urlCode = new URLSearchParams(location.search).get('code');
loadData(urlCode || '000001.SH');
