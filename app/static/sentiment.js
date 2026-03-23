// ── 认证工具（与其他页面一致）─────────────────────────────────
function getToken() { return localStorage.getItem('token'); }

function apiFetch(url, opts = {}) {
  const token = getToken();
  return fetch(url, {
    ...opts,
    headers: { ...(opts.headers || {}), Authorization: `Bearer ${token}` },
  });
}

// ── 导航栏用户名 + 退出 ────────────────────────────────────────
function initNav() {
  const payload = getToken()
    ? JSON.parse(atob(getToken().split('.')[1]))
    : null;
  if (payload) {
    document.getElementById('nav-username').textContent = payload.sub || '';
  }
  document.getElementById('nav-logout').addEventListener('click', () => {
    localStorage.removeItem('token');
    location.href = '/login';
  });
}

// ── 日期格式化 ─────────────────────────────────────────────────
const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六'];

function formatDateCell(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr.replace(/-/g, '/'));
  const y = d.getFullYear();
  const m = d.getMonth() + 1;
  const day = d.getDate();
  const wd = WEEKDAYS[d.getDay()];
  return `${y}/${m}/${day}\n星期${wd}`;
}

// ── 涨跌幅着色 ─────────────────────────────────────────────────
function pctClass(pct) {
  if (pct === null || pct === undefined) return '';
  return pct > 0 ? 'up' : pct < 0 ? 'dn' : '';
}

function fmtPct(pct) {
  if (pct === null || pct === undefined) return '—';
  const sign = pct > 0 ? '+' : '';
  return `${sign}${pct.toFixed(2)}%`;
}

function fmtClose(val) {
  if (val === null || val === undefined) return '—';
  return val.toFixed(2);
}

// ── 渲染指数表格 ───────────────────────────────────────────────
function renderIndexTable(groups) {
  const tbody = document.getElementById('index-tbody');
  const dateCell = document.getElementById('index-date-cell');
  tbody.innerHTML = '';

  // 取第一组第一个有效日期作为日期标签
  const sampleDate = groups.flat().find(r => r.trade_date)?.trade_date || '';
  const dateTxt = formatDateCell(sampleDate);
  dateCell.innerHTML = dateTxt.replace('\n', '<br>');

  const leftGrp = groups[0] || [];
  const rightGrp = groups[1] || [];
  const rows = Math.max(leftGrp.length, rightGrp.length);

  for (let i = 0; i < rows; i++) {
    const L = leftGrp[i];
    const R = rightGrp[i];
    const tr = document.createElement('tr');

    if (L) {
      tr.innerHTML += `
        <td class="idx-name">${L.name}</td>
        <td class="num-col bold">${fmtClose(L.close)}</td>
        <td class="num-col muted">${fmtClose(L.pre_close)}</td>
        <td class="num-col pct ${pctClass(L.pct_chg)}">${fmtPct(L.pct_chg)}</td>
      `;
    } else {
      tr.innerHTML += '<td colspan="4"></td>';
    }

    tr.innerHTML += '<td class="sep-col"></td>';

    if (R) {
      tr.innerHTML += `
        <td class="idx-name">${R.name}</td>
        <td class="num-col bold">${fmtClose(R.close)}</td>
        <td class="num-col muted">${fmtClose(R.pre_close)}</td>
        <td class="num-col pct ${pctClass(R.pct_chg)}">${fmtPct(R.pct_chg)}</td>
      `;
    } else {
      tr.innerHTML += '<td colspan="4"></td>';
    }

    tbody.appendChild(tr);
  }

  document.getElementById('index-loading').style.display = 'none';
  document.getElementById('index-table').style.display = '';
}

// ── 加载数据 ───────────────────────────────────────────────────
async function loadIndexSummary() {
  try {
    const res = await apiFetch('/api/sentiment/index-summary');
    if (res.status === 401) { location.href = '/login'; return; }
    const data = await res.json();
    renderIndexTable(data);
  } catch (e) {
    document.getElementById('index-loading').textContent = '加载失败，请刷新重试';
    console.error(e);
  }
}

// ── 初始化 ─────────────────────────────────────────────────────
if (!getToken()) {
  location.href = '/login';
} else {
  initNav();
  loadIndexSummary();
}
