"use strict";

// ── Auth ──────────────────────────────────────────────────────────

function getToken() { return localStorage.getItem("token"); }
function getUsername() { return localStorage.getItem("username"); }

function authHeaders() {
  const t = getToken();
  if (!t) { location.href = "/login"; throw new Error("no token"); }
  return { "Authorization": `Bearer ${t}`, "Content-Type": "application/json" };
}

async function apiFetch(url, opts = {}) {
  opts.headers = { ...authHeaders(), ...(opts.headers || {}) };
  const res = await fetch(url, opts);
  if (res.status === 401) { location.href = "/login"; throw new Error("401"); }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ── Toast ─────────────────────────────────────────────────────────

function showToast(msg, type = "info") {
  const wrap = document.getElementById("toast-wrap");
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  wrap.appendChild(el);
  requestAnimationFrame(() => el.classList.add("visible"));
  setTimeout(() => {
    el.classList.remove("visible");
    setTimeout(() => el.remove(), 300);
  }, 3500);
}

// ── Cron 预览 ─────────────────────────────────────────────────────

function humanizeCron(cron) {
  if (!cron) return "—";
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return cron;
  const [min, hr, dom, mon, dow] = parts;

  const dayMap = { "1-5": "周一至周五", "5": "每周五", "1": "每周一",
                   "*": "每天", "1-7": "每天", "0": "周日" };
  const dowLabel = dayMap[dow] || `周${dow}`;

  let domPart = "";
  if (dom !== "*") {
    domPart = `${dom}日 `;
  }

  const hrNum = parseInt(hr, 10);
  const minNum = parseInt(min, 10);
  const time = `${String(hrNum).padStart(2,"0")}:${String(minNum).padStart(2,"0")}`;

  if (dom !== "*" && dow === "*") return `每月 ${domPart}${time}`;
  if (dom !== "*") return `${dowLabel} ${domPart}${time}`;
  return `${dowLabel} ${time}`;
}

// ── 状态显示 ──────────────────────────────────────────────────────

const STATUS_CFG = {
  pending: { label: "待执行", cls: "st-pending" },
  running: { label: "执行中", cls: "st-running" },
  success: { label: "成功",   cls: "st-success" },
  failed:  { label: "失败",   cls: "st-failed"  },
  skipped: { label: "已跳过", cls: "st-skipped" },
};

function statusBadge(status) {
  const cfg = STATUS_CFG[status] || STATUS_CFG.pending;
  return `<span class="status-badge ${cfg.cls}">${cfg.label}</span>`;
}

function timeDiff(start, end) {
  if (!start || !end) return "";
  const s = new Date(start.replace(" ", "T"));
  const e = new Date(end.replace(" ", "T"));
  const sec = Math.round((e - s) / 1000);
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60), r = sec % 60;
  return `${m}m ${r}s`;
}

function timeRange(start, end) {
  const fmt = t => t ? t.slice(11, 19) : "—";
  if (!start) return "";
  if (!end) return `${fmt(start)} →`;
  return `${fmt(start)} → ${fmt(end)}  (${timeDiff(start, end)})`;
}

// ── 日期工具 ──────────────────────────────────────────────────────

function _fmtDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
function getTodayStr() { return _fmtDate(new Date()); }
function getWeekMondayStr() {
  const d = new Date();
  const wd = d.getDay();
  d.setDate(d.getDate() + (wd === 0 ? -6 : 1 - wd));
  return _fmtDate(d);
}
function getMonthStartStr() {
  const d = new Date(); d.setDate(1); return _fmtDate(d);
}
function getCurrentMonthStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

// ── 任务状态渲染 ──────────────────────────────────────────────────

// 存储 stage 数据供弹层使用
const _stageDataMap = new Map();

function renderStages(data) {
  const container = document.getElementById("stages-container");
  container.innerHTML = "";
  _stageDataMap.clear();

  // 更新日期标签
  document.getElementById("admin-date").textContent =
    `${data.date}  ${data.weekday}`;

  if (!data.stages || data.stages.length === 0) {
    container.innerHTML = '<p class="admin-empty">暂无阶段配置</p>';
    return;
  }

  data.stages.forEach(stage => {
    _stageDataMap.set(stage.name, stage);
    const card = document.createElement("div");
    card.className = "stage-card" + (stage.enabled === false ? " stage-disabled" : "");

    // 阶段触发状态徽章
    let triggerBadge = "";
    if (!stage.enabled) {
      triggerBadge = `<span class="trigger-badge tb-disabled">已禁用</span>`;
    } else if (!stage.should_run_today) {
      triggerBadge = `<span class="trigger-badge tb-skip" title="${stage.condition_reason}">今日跳过</span>`;
    } else if (stage.triggered_today === true) {
      triggerBadge = `<span class="trigger-badge tb-ok">已触发</span>`;
    } else if (stage.triggered_today === false) {
      triggerBadge = `<span class="trigger-badge tb-skip">已跳过</span>`;
    } else {
      triggerBadge = `<span class="trigger-badge tb-pending" title="${stage.condition_reason}">等待触发</span>`;
    }

    // 整体阶段状态（所有任务都成功则成功，有失败则失败，有运行中则运行中）
    const allSuccess = stage.tasks.every(t => t.status === "success");
    const anyFailed  = stage.tasks.some(t => t.status === "failed");
    const anyRunning = stage.tasks.some(t => t.status === "running");
    const stageStatus = anyFailed ? "failed" : anyRunning ? "running" : allSuccess ? "success" : "pending";

    // 任务行
    const taskRows = stage.tasks.map(task => {
      const hasLog = task.log_tail && task.log_tail.length > 0;
      return `
        <div class="task-row task-${task.status}">
          <span class="task-dot task-dot-${task.status}"></span>
          <span class="task-name">${task.name}</span>
          <span class="task-status-badge">${statusBadge(task.status)}</span>
          <span class="task-time">${timeRange(task.started_at, task.finished_at)}</span>
          ${hasLog
            ? `<button class="task-log-btn" data-task="${task.name}">查看日志</button>`
            : `<span class="task-log-btn-placeholder"></span>`}
        </div>`;
    }).join("");

    card.innerHTML = `
      <div class="stage-header">
        <div class="stage-header-left">
          <span class="stage-name">${stage.name}</span>
          ${triggerBadge}
          <span class="stage-overall-status">${statusBadge(stageStatus)}</span>
        </div>
        <div class="stage-header-right">
          <span class="stage-cron" title="${stage.cron}">
            ${humanizeCron(stage.cron)}
          </span>
          <button class="admin-btn admin-btn-sm admin-btn-trigger"
                  data-stage="${stage.name}"
                  ${stage.enabled === false ? 'disabled title="阶段已禁用"' : ''}>
            手动执行
          </button>
        </div>
      </div>
      <div class="stage-condition">
        触发条件：${stage.condition_reason}
      </div>
      <div class="task-list">
        ${taskRows}
      </div>`;

    container.appendChild(card);
  });

  // 绑定手动执行按钮
  container.querySelectorAll(".admin-btn-trigger").forEach(btn => {
    btn.addEventListener("click", () => {
      const stage = _stageDataMap.get(btn.dataset.stage);
      openTriggerModal(stage);
    });
  });

  // 绑定日志查看按钮
  container.querySelectorAll(".task-log-btn").forEach(btn => {
    btn.addEventListener("click", () => openLogModal(btn.dataset.task));
  });
}

// ── 手动执行弹层 ──────────────────────────────────────────────────

let _currentTriggerStage = null;

function openTriggerModal(stage) {
  _currentTriggerStage = stage;

  document.getElementById("trigger-modal-title").textContent = `执行：${stage.name}`;

  // 任务列表
  const taskNames = stage.tasks.map(t => t.name);
  document.getElementById("trigger-task-list").innerHTML =
    `<span class="trigger-tasks-label">包含任务</span>` +
    taskNames.map(n => `<span class="trigger-task-chip">${n}</span>`).join("");

  // 根据 date_type 显示对应区域
  const dateType = stage.date_type || "none";
  const rangeSection = document.getElementById("trigger-range-section");
  const monthSection = document.getElementById("trigger-month-section");
  const noneNote     = document.getElementById("trigger-none-note");

  rangeSection.classList.add("hidden");
  monthSection.classList.add("hidden");
  noneNote.classList.add("hidden");

  const today      = getTodayStr();
  const onlyOn     = stage.only_on || [];

  if (dateType === "range") {
    rangeSection.classList.remove("hidden");

    let defaultStart = today;
    if (onlyOn.includes("friday")) {
      defaultStart = getWeekMondayStr();
    } else if (onlyOn.includes("month_last")) {
      defaultStart = getMonthStartStr();
    }

    document.getElementById("trigger-start").value = defaultStart;
    document.getElementById("trigger-end").value   = today;
    document.getElementById("trigger-range-hint").textContent =
      `默认：${defaultStart} → ${today}。可修改为任意历史区间以补拉数据。`;

  } else if (dateType === "month") {
    monthSection.classList.remove("hidden");
    document.getElementById("trigger-month").value = getCurrentMonthStr();

  } else {
    noneNote.classList.remove("hidden");
  }

  // 重置确认按钮状态
  const confirmBtn = document.getElementById("trigger-modal-confirm");
  confirmBtn.disabled = false;
  confirmBtn.textContent = "立即执行";

  document.getElementById("trigger-modal").classList.add("open");
}

async function confirmTrigger() {
  const stage = _currentTriggerStage;
  if (!stage) return;

  const dateType = stage.date_type || "none";
  const payload  = { stage: stage.name };

  if (dateType === "range") {
    const start = document.getElementById("trigger-start").value;
    const end   = document.getElementById("trigger-end").value;
    if (start) payload.start_date = start.replace(/-/g, "");
    if (end)   payload.end_date   = end.replace(/-/g, "");
    if (payload.start_date && payload.end_date && payload.start_date > payload.end_date) {
      showToast("开始日期不能晚于结束日期", "error");
      return;
    }
  } else if (dateType === "month") {
    const month = document.getElementById("trigger-month").value; // YYYY-MM
    if (month) payload.start_date = month.replace("-", "") + "01";
  }

  const btn = document.getElementById("trigger-modal-confirm");
  btn.disabled = true;
  btn.textContent = "启动中…";

  try {
    const res = await apiFetch("/api/admin/run", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    showToast(res.message, "success");
    document.getElementById("trigger-modal").classList.remove("open");
    // 清除普通刷新倒计时，改为快速轮询（2s）同时展示实时进度
    clearInterval(_refreshTimer);
    startTriggerPoll(stage.name);
  } catch (e) {
    showToast(`触发失败：${e.message}`, "error");
    btn.disabled = false;
    btn.textContent = "立即执行";
  }
}

function closeTriggerModal() {
  document.getElementById("trigger-modal").classList.remove("open");
  _currentTriggerStage = null;
}

async function openLogModal(taskName) {
  const modal = document.getElementById("log-modal");
  const content = document.getElementById("log-modal-content");
  const title = document.getElementById("log-modal-title");

  title.textContent = `${taskName} — 今日日志`;
  content.textContent = "加载中…";
  modal.classList.add("open");

  try {
    const res = await apiFetch(`/api/admin/log/${taskName}`);
    content.textContent = res.lines.length ? res.lines.join("\n") : "（暂无日志）";
    // 滚动到底部
    content.scrollTop = content.scrollHeight;
  } catch (e) {
    content.textContent = `加载失败：${e.message}`;
  }
}

// ── 配置渲染 ──────────────────────────────────────────────────────

let _configData = null;

function renderConfig(data) {
  _configData = data;

  document.getElementById("cfg-project-root").value = data.global.project_root || "";
  document.getElementById("cfg-python").value       = data.global.python       || "python3";
  document.getElementById("cfg-log-dir").value      = data.global.log_dir      || "logs/daily_update";
  document.getElementById("cfg-env-file").value     = data.global.env_file     || "";

  const rows = document.getElementById("schedule-rows");
  rows.innerHTML = "";

  data.stages.forEach((stage, idx) => {
    const row = document.createElement("div");
    row.className = "schedule-row";
    row.dataset.idx = idx;

    const cronId = `cron-${idx}`;
    const preview = humanizeCron(stage.cron);

    row.innerHTML = `
      <span class="sch-col-en">
        <label class="toggle">
          <input type="checkbox" class="toggle-input" data-idx="${idx}"
                 ${stage.enabled !== false ? "checked" : ""}>
          <span class="toggle-slider"></span>
        </label>
      </span>
      <span class="sch-col-name">${stage.name}</span>
      <span class="sch-col-cron">
        <input type="text" id="${cronId}" class="cron-input" value="${stage.cron}"
               placeholder="0 19 * * 1-5">
      </span>
      <span class="sch-col-preview" id="preview-${idx}">${preview}</span>
      <span class="sch-col-tasks">${(stage.tasks || []).join(", ")}</span>`;

    rows.appendChild(row);

    // 实时预览
    row.querySelector(`#${cronId}`).addEventListener("input", e => {
      document.getElementById(`preview-${idx}`).textContent = humanizeCron(e.target.value);
    });
  });
}

async function saveConfig() {
  if (!_configData) return;

  const global_cfg = {
    project_root: document.getElementById("cfg-project-root").value.trim(),
    python:       document.getElementById("cfg-python").value.trim(),
    log_dir:      document.getElementById("cfg-log-dir").value.trim(),
    env_file:     document.getElementById("cfg-env-file").value.trim(),
  };

  const stages = _configData.stages.map((stage, idx) => {
    const cronInput = document.getElementById(`cron-${idx}`);
    const enabledInput = document.querySelector(`input[data-idx="${idx}"]`);
    return {
      name:    stage.name,
      cron:    cronInput ? cronInput.value.trim() : stage.cron,
      enabled: enabledInput ? enabledInput.checked : stage.enabled,
    };
  });

  const btn = document.getElementById("btn-save-config");
  btn.disabled = true;
  btn.textContent = "保存中…";
  try {
    const res = await apiFetch("/api/admin/config", {
      method: "PUT",
      body: JSON.stringify({ global_cfg, stages }),
    });
    showToast(res.message, "success");
    await loadConfig(); // 重新加载
  } catch (e) {
    showToast(`保存失败：${e.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "保存配置";
  }
}

// ── 触发轮询（手动执行后快速更新状态 + 进度日志） ────────────────

let _triggerPollTimer  = null;
let _triggerPollCount  = 0;
let _triggerStageName  = null;
let _triggerDonePosted = false;
const TRIGGER_POLL_INTERVAL = 2000;   // 2s
const TRIGGER_POLL_MAX      = 120;    // 最多 4 分钟

function startTriggerPoll(stageName) {
  stopTriggerPoll();
  _triggerStageName  = stageName;
  _triggerPollCount  = 0;
  _triggerDonePosted = false;

  // 显示进度面板
  const prog = document.getElementById("trigger-progress");
  document.getElementById("trigger-progress-title").textContent = `执行进度 — ${stageName}`;
  document.getElementById("trigger-log-content").textContent = "等待日志…";
  prog.classList.remove("hidden");

  _triggerPollTimer = setInterval(_triggerPollTick, TRIGGER_POLL_INTERVAL);
  _triggerPollTick();   // 立即执行一次
}

function stopTriggerPoll() {
  if (_triggerPollTimer) { clearInterval(_triggerPollTimer); _triggerPollTimer = null; }
}

async function _triggerPollTick() {
  if (activeTab() !== "status") { stopTriggerPoll(); return; }

  _triggerPollCount++;
  if (_triggerPollCount > TRIGGER_POLL_MAX) { stopTriggerPoll(); scheduleRefresh(); return; }

  // 刷新任务状态
  try {
    const data = await apiFetch("/api/admin/status");
    renderStages(data);

    // 检查触发阶段是否全部结束
    const stageData = data.stages.find(s => s.name === _triggerStageName);
    if (stageData && !_triggerDonePosted) {
      const allDone = stageData.tasks.every(
        t => ["success", "failed", "skipped"].includes(t.status)
      );
      if (allDone && _triggerPollCount > 1) {
        _triggerDonePosted = true;
        // 再最终刷新一次，然后切回普通刷新
        setTimeout(() => { stopTriggerPoll(); loadStatus(); scheduleRefresh(); }, 2000);
      }
    }
  } catch { /* 忽略，继续下次 */ }

  // 更新进度日志
  _fetchTriggerLog(_triggerStageName);
}

async function _fetchTriggerLog(stageName) {
  const el = document.getElementById("trigger-log-content");
  if (!el || document.getElementById("trigger-progress").classList.contains("hidden")) return;
  try {
    const data = await apiFetch(`/api/admin/trigger-log/${encodeURIComponent(stageName)}`);
    if (!data.found || !data.lines.length) return;
    const text = data.lines.join("\n");
    // 保持在底部：只有已在底部时才自动滚动
    const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 20;
    el.textContent = text;
    if (atBottom) el.scrollTop = el.scrollHeight;
  } catch { /* 忽略 */ }
}

// ── 数据加载 ──────────────────────────────────────────────────────

async function loadStatus() {
  const loadingEl = document.getElementById("status-loading");
  if (loadingEl) loadingEl.style.display = "flex";
  try {
    const data = await apiFetch("/api/admin/status");
    if (loadingEl) loadingEl.style.display = "none";
    renderStages(data);
    // 如有任务正在运行且未处于触发轮询中，5秒后自动刷新
    const anyRunning = data.stages.some(s => s.tasks.some(t => t.status === "running"));
    if (anyRunning && !_triggerPollTimer) scheduleRefresh(5);
  } catch (e) {
    if (loadingEl) loadingEl.style.display = "none";
    showToast(`加载状态失败：${e.message}`, "error");
  }
}

async function loadConfig() {
  document.getElementById("config-loading").style.display = "flex";
  document.getElementById("config-form").classList.add("hidden");
  try {
    const data = await apiFetch("/api/admin/config");
    document.getElementById("config-loading").style.display = "none";
    document.getElementById("config-form").classList.remove("hidden");
    renderConfig(data);
  } catch (e) {
    document.getElementById("config-loading").style.display = "none";
    showToast(`加载配置失败：${e.message}`, "error");
  }
}

// ── 自动刷新 ──────────────────────────────────────────────────────

const AUTO_REFRESH_SEC = 30;
let _refreshTimer = null;
let _countdown = 0;

function scheduleRefresh(seconds = AUTO_REFRESH_SEC) {
  clearInterval(_refreshTimer);
  _countdown = seconds;
  updateCountdown();
  _refreshTimer = setInterval(() => {
    _countdown--;
    updateCountdown();
    if (_countdown <= 0) {
      clearInterval(_refreshTimer);
      if (activeTab() === "status") loadStatus();
    }
  }, 1000);
}

function updateCountdown() {
  const el = document.getElementById("refresh-countdown");
  if (_countdown > 0) el.textContent = `${_countdown}s 后刷新`;
  else el.textContent = "";
}

function activeTab() {
  const btn = document.querySelector(".admin-tab.active");
  return btn ? btn.dataset.tab : "status";
}

// ── Tab 切换 ──────────────────────────────────────────────────────

function switchTab(tab) {
  document.querySelectorAll(".admin-tab").forEach(b => {
    b.classList.toggle("active", b.dataset.tab === tab);
  });
  document.getElementById("panel-status").classList.toggle("hidden", tab !== "status");
  document.getElementById("panel-config").classList.toggle("hidden", tab !== "config");

  if (tab === "config" && !_configData) loadConfig();
  if (tab === "status") scheduleRefresh();
  else {
    clearInterval(_refreshTimer);
    document.getElementById("refresh-countdown").textContent = "";
  }
}

// ── 初始化 ────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  // 检查登录
  if (!getToken()) { location.href = "/login"; return; }
  document.getElementById("nav-username").textContent = getUsername() || "";

  // 退出登录
  document.getElementById("nav-logout").addEventListener("click", () => {
    localStorage.clear();
    location.href = "/login";
  });

  // Tab 切换
  document.querySelectorAll(".admin-tab").forEach(btn => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  // 刷新按钮
  document.getElementById("btn-refresh").addEventListener("click", () => {
    if (activeTab() === "status") loadStatus();
    else loadConfig();
  });

  // 保存配置
  document.getElementById("btn-save-config").addEventListener("click", saveConfig);

  // 手动执行弹层
  document.getElementById("trigger-modal-confirm").addEventListener("click", confirmTrigger);
  document.getElementById("trigger-modal-cancel").addEventListener("click", closeTriggerModal);
  document.getElementById("trigger-modal-close").addEventListener("click", closeTriggerModal);
  document.getElementById("trigger-modal").addEventListener("click", e => {
    if (e.target === e.currentTarget) closeTriggerModal();
  });
  // 日期联动：结束日期不能早于开始日期
  document.getElementById("trigger-start").addEventListener("change", () => {
    const s = document.getElementById("trigger-start").value;
    const e = document.getElementById("trigger-end");
    if (s && e.value && e.value < s) e.value = s;
    e.min = s || "";
  });

  // 进度面板关闭
  document.getElementById("trigger-progress-close").addEventListener("click", () => {
    document.getElementById("trigger-progress").classList.add("hidden");
    stopTriggerPoll();
  });

  // 日志弹层关闭
  document.getElementById("log-modal-close").addEventListener("click", () => {
    document.getElementById("log-modal").classList.remove("open");
  });
  document.getElementById("log-modal").addEventListener("click", e => {
    if (e.target === e.currentTarget)
      document.getElementById("log-modal").classList.remove("open");
  });

  // 首次加载任务状态
  loadStatus();
  scheduleRefresh();
});
