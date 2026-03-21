'use strict';

// ── Auth 工具 ─────────────────────────────────────────────
function getToken()    { return localStorage.getItem('token'); }
function getUsername() { return localStorage.getItem('username'); }

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
  const el = document.getElementById('nav-username');
  if (el) el.textContent = getUsername() || '';
  document.getElementById('nav-logout').addEventListener('click', logout);
}

// ── 格式化数字 ────────────────────────────────────────────
function fmt(v, digits = 2) {
  if (v === null || v === undefined) return '—';
  return Number(v).toFixed(digits);
}

function fmtVol(v) {
  if (v === null || v === undefined) return '—';
  const n = Number(v);
  if (n >= 1e8) return (n / 1e8).toFixed(2) + '亿';
  if (n >= 1e4) return (n / 1e4).toFixed(2) + '万';
  return n.toFixed(0);
}

// 万元 / 万股 单位的大数：>= 10000万 显示为"xx亿"
function fmtWan(v) {
  if (v === null || v === undefined) return '—';
  const n = Number(v);
  if (n >= 10000) return (n / 10000).toFixed(2) + '亿';
  return n.toFixed(0) + '万';
}

// ── 渲染持仓列表 ──────────────────────────────────────────
function renderPortfolio(items) {
  const emptyHint = document.getElementById('empty-hint');
  const tableWrap = document.getElementById('table-wrap');
  const tbody     = document.getElementById('portfolio-tbody');

  if (!items.length) {
    emptyHint.style.display = 'flex';
    tableWrap.style.display = 'none';
    return;
  }

  emptyHint.style.display = 'none';
  tableWrap.style.display = 'block';
  tbody.innerHTML = '';

  items.forEach(item => {
    const pct = item.pct_chg;
    let pctClass = 'pct-flat';
    let pctText  = '—';
    if (pct !== null && pct !== undefined) {
      pctClass = pct > 0 ? 'pct-up' : pct < 0 ? 'pct-down' : 'pct-flat';
      pctText  = (pct > 0 ? '+' : '') + fmt(pct) + '%';
    }

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${item.idx}</td>
      <td style="font-family:monospace">${item.ts_code}</td>
      <td>${item.name}</td>
      <td class="num-col">${fmt(item.close)}</td>
      <td class="num-col ${pctClass}">${pctText}</td>
      <td class="num-col">${fmtVol(item.vol)}</td>
      <td class="num-col">${fmt(item.turnover_rate)}%</td>
      <td class="num-col">${fmt(item.turnover_rate_f)}%</td>
      <td class="num-col">${fmt(item.volume_ratio)}</td>
      <td class="num-col${item.pe_ttm === null ? ' pct-down' : ''}">${item.pe_ttm === null ? '亏损' : fmt(item.pe_ttm)}</td>
      <td class="num-col">${fmt(item.dv_ratio)}%</td>
      <td class="num-col">${fmt(item.dv_ttm)}%</td>
      <td class="num-col">${fmtWan(item.total_share)}</td>
      <td class="num-col">${fmtWan(item.float_share)}</td>
      <td class="num-col">${fmtWan(item.free_share)}</td>
      <td class="num-col">${fmtWan(item.total_mv)}</td>
      <td class="num-col">${fmtWan(item.circ_mv)}</td>
      <td><button class="del-btn" data-code="${item.ts_code}" title="移除">×</button></td>
    `;

    // 行点击跳转行情（忽略删除按钮）
    tr.addEventListener('click', e => {
      if (e.target.classList.contains('del-btn')) return;
      location.href = `/chart?code=${encodeURIComponent(item.ts_code)}`;
    });

    tbody.appendChild(tr);
  });

  // 删除按钮
  tbody.querySelectorAll('.del-btn').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      const code = btn.dataset.code;
      await removeStock(code);
    });
  });
}

// ── 加载持仓 ──────────────────────────────────────────────
async function loadPortfolio() {
  const res = await fetch('/api/portfolio', { headers: authHeaders() });
  if (res.status === 401) { logout(); return; }
  const items = await res.json();
  renderPortfolio(items);
}

// ── 删除持仓 ──────────────────────────────────────────────
async function removeStock(tsCode) {
  const res = await fetch(`/api/portfolio/${encodeURIComponent(tsCode)}`, {
    method:  'DELETE',
    headers: authHeaders(),
  });
  if (res.status === 401) { logout(); return; }
  await loadPortfolio();
}

// ── 添加持仓（浮层搜索） ───────────────────────────────────
async function addStock(tsCode) {
  const res = await fetch('/api/portfolio', {
    method:  'POST',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body:    JSON.stringify({ ts_code: tsCode }),
  });
  if (res.status === 401) { logout(); return; }
  closeModal();
  await loadPortfolio();
}

// ── 浮层控制 ──────────────────────────────────────────────
const modal         = document.getElementById('modal');
const modalSearch   = document.getElementById('modal-search');
const modalSugs     = document.getElementById('modal-suggestions');

function openModal() {
  modal.classList.add('open');
  modalSearch.value = '';
  modalSugs.classList.remove('open');
  modalSugs.innerHTML = '';
  setTimeout(() => modalSearch.focus(), 50);
}

function closeModal() {
  modal.classList.remove('open');
}

document.getElementById('open-modal').addEventListener('click', openModal);
document.getElementById('close-modal').addEventListener('click', closeModal);
document.getElementById('empty-hint').addEventListener('click', openModal);

modal.addEventListener('click', e => {
  if (e.target === modal) closeModal();
});

// 搜索逻辑
let searchTimer = null;

modalSearch.addEventListener('input', () => {
  clearTimeout(searchTimer);
  const q = modalSearch.value.trim();
  if (!q) { modalSugs.classList.remove('open'); modalSugs.innerHTML = ''; return; }
  searchTimer = setTimeout(async () => {
    const res     = await fetch(`/api/stocks/search?q=${encodeURIComponent(q)}`, { headers: authHeaders() });
    if (res.status === 401) { logout(); return; }
    const results = await res.json();
    renderModalSugs(results);
  }, 180);
});

modalSearch.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeModal();
  if (e.key === 'Enter') {
    const first = modalSugs.querySelector('.sug-item');
    if (first) first.click();
  }
});

function renderModalSugs(results) {
  modalSugs.innerHTML = '';
  if (!results.length) { modalSugs.classList.remove('open'); return; }
  results.forEach(r => {
    const item     = document.createElement('div');
    item.className = 'sug-item';
    const badge = r.type === 'index'
      ? `<span class="sug-badge sug-badge-index">指数</span>`
      : '';
    item.innerHTML = `${badge}<span class="sug-code">${r.ts_code}</span><span class="sug-name">${r.name}</span>`;
    item.addEventListener('click', () => addStock(r.ts_code));
    modalSugs.appendChild(item);
  });
  modalSugs.classList.add('open');
}

// ── 启动 ──────────────────────────────────────────────────
if (!getToken()) { location.href = '/login'; }
else {
  initNav();
  loadPortfolio();
}
