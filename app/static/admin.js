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

// ── 任务状态渲染（局部更新，避免整页闪烁） ──────────────────────

// 存储 stage 数据供弹层使用
const _stageDataMap = new Map();

// 将阶段/任务名转为合法 DOM ID 片段
function _sid(name) { return name.replace(/[^\w\u4e00-\u9fff]/g, "_"); }

function _triggerBadgeHtml(stage) {
  if (!stage.enabled)
    return `<span class="trigger-badge tb-disabled">已禁用</span>`;
  if (!stage.should_run_today)
    return `<span class="trigger-badge tb-skip" title="${stage.condition_reason}">今日跳过</span>`;
  if (stage.triggered_today === true)
    return `<span class="trigger-badge tb-ok">已触发</span>`;
  if (stage.triggered_today === false)
    return `<span class="trigger-badge tb-skip">已跳过</span>`;
  return `<span class="trigger-badge tb-pending" title="${stage.condition_reason}">等待触发</span>`;
}

function renderStages(data) {
  const container = document.getElementById("stages-container");
  _stageDataMap.clear();

  const _dateEl = document.getElementById("admin-date");
  const _dateStr = `${data.date}  ${data.weekday}`;
  if (_dateEl.textContent !== _dateStr) _dateEl.textContent = _dateStr;

  if (!data.stages || data.stages.length === 0) {
    container.innerHTML = '<p class="admin-empty">暂无阶段配置</p>';
    return;
  }

  // 清除"无阶段"占位文字（如果有）
  const emptyEl = container.querySelector(".admin-empty");
  if (emptyEl) emptyEl.remove();

  const activeCardIds = new Set();

  data.stages.forEach(stage => {
    _stageDataMap.set(stage.name, stage);

    const ssid   = _sid(stage.name);
    const cardId = `sc-${ssid}`;
    activeCardIds.add(cardId);

    const allSuccess  = stage.tasks.every(t => t.status === "success");
    const anyFailed   = stage.tasks.some(t  => t.status === "failed");
    const anyRunning  = stage.tasks.some(t  => t.status === "running") || stage.is_manual_running;
    const stageStatus = anyFailed ? "failed" : anyRunning ? "running"
                      : allSuccess ? "success" : "pending";
    const trigHtml    = _triggerBadgeHtml(stage);

    let card = document.getElementById(cardId);

    if (!card) {
      // ── 首次渲染：构建完整卡片结构 ────────────────────────────
      card = document.createElement("div");
      card.id        = cardId;
      card.className = "stage-card" + (stage.enabled === false ? " stage-disabled" : "");

      const taskRowsHtml = stage.tasks.map(task => {
        const tid    = `${ssid}_${_sid(task.name)}`;
        const hasLog = task.log_tail && task.log_tail.length > 0;
        return `
          <div class="task-row task-${task.status}" id="tr-${tid}">
            <span class="task-dot task-dot-${task.status}" id="td-${tid}"></span>
            <span class="task-name">${task.name}</span>
            ${task.date_range ? `<span class="task-date-range">${task.date_range}</span>` : ""}
            <span class="task-status-badge" id="tb-${tid}">${statusBadge(task.status)}</span>
            <span class="task-time" id="tt-${tid}">${timeRange(task.started_at, task.finished_at)}</span>
            <button class="task-log-btn" id="tlb-${tid}" data-task="${task.name}"
                    style="${hasLog ? "" : "visibility:hidden"}">查看日志</button>
          </div>`;
      }).join("");

      const latestHtml = stage.latest_date
        ? `<span class="stage-latest-date" id="slatd-${ssid}">最新&nbsp;${stage.latest_date}</span>`
        : `<span class="stage-latest-date" id="slatd-${ssid}"></span>`;

      card.innerHTML = `
        <div class="stage-header">
          <div class="stage-header-left">
            <span class="stage-name">${stage.name}</span>
            ${latestHtml}
            <span id="strig-${ssid}">${trigHtml}</span>
            <span id="sstat-${ssid}">${statusBadge(stageStatus)}</span>
          </div>
          <div class="stage-header-right">
            <span class="stage-cron" title="${stage.cron}">${humanizeCron(stage.cron)}</span>
            <button class="admin-btn admin-btn-sm admin-btn-trigger"
                    id="tbtn-${ssid}"
                    data-stage="${stage.name}"
                    ${stage.enabled === false ? 'disabled title="阶段已禁用"' :
                      anyRunning ? 'disabled title="执行中，请等待完成"' : ''}>
              ${anyRunning ? "执行中…" : "手动执行"}
            </button>
          </div>
        </div>
        <div class="stage-condition">触发条件：${stage.condition_reason}</div>
        <div class="task-list">${taskRowsHtml}</div>`;

      container.appendChild(card);

    } else {
      // ── 局部更新：只改动态内容，不重建 DOM ─────────────────────
      // 脏检查工具：仅值变化时才写 DOM，避免不必要的重排
      const _setTxt = (el, v) => { if (el && el.textContent !== v) el.textContent = v; };
      const _setHtml = (el, v) => { if (el && el.innerHTML !== v) el.innerHTML = v; };

      const latdEl = document.getElementById(`slatd-${ssid}`);
      _setTxt(latdEl, stage.latest_date ? `最新\u00a0${stage.latest_date}` : "");

      const trigEl = document.getElementById(`strig-${ssid}`);
      _setHtml(trigEl, trigHtml);

      const statEl = document.getElementById(`sstat-${ssid}`);
      _setHtml(statEl, statusBadge(stageStatus));

      // 运行中时禁用手动执行按钮
      const trigBtnEl = document.getElementById(`tbtn-${ssid}`);
      if (trigBtnEl && stage.enabled !== false) {
        const newTitle = anyRunning ? "执行中，请等待完成" : "";
        const newText  = anyRunning ? "执行中…" : "手动执行";
        if (trigBtnEl.disabled !== anyRunning)  trigBtnEl.disabled = anyRunning;
        if (trigBtnEl.title !== newTitle)        trigBtnEl.title = newTitle;
        if (trigBtnEl.textContent !== newText)   trigBtnEl.textContent = newText;
      }

      stage.tasks.forEach(task => {
        const tid     = `${ssid}_${_sid(task.name)}`;
        const hasLog  = task.log_tail && task.log_tail.length > 0;
        const rowEl   = document.getElementById(`tr-${tid}`);
        const dotEl   = document.getElementById(`td-${tid}`);
        const badgeEl = document.getElementById(`tb-${tid}`);
        const timeEl  = document.getElementById(`tt-${tid}`);
        const logBtn  = document.getElementById(`tlb-${tid}`);

        const newRowCls = `task-row task-${task.status}`;
        const newDotCls = `task-dot task-dot-${task.status}`;
        const newBadge  = statusBadge(task.status);
        const newTime   = timeRange(task.started_at, task.finished_at);
        const newVis    = hasLog ? "" : "hidden";

        if (rowEl   && rowEl.className           !== newRowCls) rowEl.className = newRowCls;
        if (dotEl   && dotEl.className           !== newDotCls) dotEl.className = newDotCls;
        if (badgeEl && badgeEl.innerHTML         !== newBadge)  badgeEl.innerHTML = newBadge;
        if (timeEl  && timeEl.textContent        !== newTime)   timeEl.textContent = newTime;
        if (logBtn  && logBtn.style.visibility   !== newVis)    logBtn.style.visibility = newVis;
      });
    }
  });

  // 移除已不存在的 stage 卡片
  Array.from(container.children).forEach(el => {
    if (el.id?.startsWith("sc-") && !activeCardIds.has(el.id)) el.remove();
  });
}

// ── 事件委托（替代每次 renderStages 后的重新绑定） ───────────────
function setupStageListeners() {
  const container = document.getElementById("stages-container");
  container.addEventListener("click", e => {
    const trigBtn = e.target.closest(".admin-btn-trigger");
    if (trigBtn && !trigBtn.disabled) {
      const stage = _stageDataMap.get(trigBtn.dataset.stage);
      if (stage) openTriggerModal(stage);
      return;
    }
    const logBtn = e.target.closest(".task-log-btn");
    if (logBtn) openLogModal(logBtn.dataset.task);
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

  // 涨跌停类型复选框
  const limitTypeSection = document.getElementById("trigger-limit-type-section");
  const limitTypesContainer = document.getElementById("trigger-limit-types");
  const limitTypeOptions = stage.limit_type_options || [];

  if (limitTypeOptions.length > 0) {
    limitTypesContainer.innerHTML = limitTypeOptions.map(t =>
      `<label class="trigger-limit-type-label">
        <input type="checkbox" class="trigger-limit-type-cb" value="${t}" checked>
        <span>${t}</span>
      </label>`
    ).join("");
    limitTypeSection.classList.remove("hidden");
  } else {
    limitTypesContainer.innerHTML = "";
    limitTypeSection.classList.add("hidden");
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

  // 涨跌停类型
  const limitTypeCbs = document.querySelectorAll(".trigger-limit-type-cb");
  if (limitTypeCbs.length > 0) {
    const selected = Array.from(limitTypeCbs).filter(cb => cb.checked).map(cb => cb.value);
    if (selected.length === 0) {
      showToast("请至少选择一种板单类型", "error");
      return;
    }
    payload.limit_types = selected;
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

let _logModalTimer = null;

function _isTaskRunning(taskName) {
  for (const stage of _stageDataMap.values()) {
    const t = stage.tasks.find(t => t.name === taskName);
    if (t && t.status === "running") return true;
  }
  return false;
}

async function openLogModal(taskName) {
  const modal   = document.getElementById("log-modal");
  const content = document.getElementById("log-modal-content");
  const title   = document.getElementById("log-modal-title");

  clearInterval(_logModalTimer);
  title.textContent = `${taskName} — 今日日志`;
  content.textContent = "加载中…";
  modal.classList.add("open");

  const fetchLog = async () => {
    try {
      const res = await apiFetch(`/api/admin/log/${taskName}`);
      const text = res.lines.length ? res.lines.join("\n") : "（暂无日志）";
      const atBottom = content.scrollTop + content.clientHeight >= content.scrollHeight - 20;
      content.textContent = text;
      if (atBottom) content.scrollTop = content.scrollHeight;
    } catch (e) {
      content.textContent = `加载失败：${e.message}`;
    }
  };

  await fetchLog();

  // 任务运行中：每 3s 自动刷新日志
  if (_isTaskRunning(taskName)) {
    _logModalTimer = setInterval(async () => {
      if (!modal.classList.contains("open")) { clearInterval(_logModalTimer); return; }
      await fetchLog();
      if (!_isTaskRunning(taskName)) clearInterval(_logModalTimer);
    }, 3000);
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

  // 显示进度面板，恢复停止按钮
  const prog    = document.getElementById("trigger-progress");
  const stopBtn = document.getElementById("trigger-stop-btn");
  document.getElementById("trigger-progress-title").textContent = `执行进度 — ${stageName}`;
  document.getElementById("trigger-log-content").textContent = "等待日志…";
  if (stopBtn) { stopBtn.style.display = ""; stopBtn.disabled = false; stopBtn.textContent = "停止执行"; }
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
        // 隐藏停止执行按钮（任务已结束，无需再停止）
        const stopBtn = document.getElementById("trigger-stop-btn");
        if (stopBtn) stopBtn.style.display = "none";
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

async function loadStatus(showSpinner = false) {
  const loadingEl = document.getElementById("status-loading");
  if (loadingEl && showSpinner) loadingEl.style.display = "flex";
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

  // 刷新按钮（手动刷新才显示 spinner）
  document.getElementById("btn-refresh").addEventListener("click", () => {
    if (activeTab() === "status") loadStatus(true);
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

  // 进度面板 — 停止执行
  document.getElementById("trigger-stop-btn").addEventListener("click", async () => {
    if (!_triggerStageName) return;
    const btn = document.getElementById("trigger-stop-btn");
    btn.disabled = true;
    btn.textContent = "停止中…";
    try {
      const res = await apiFetch("/api/admin/stop", {
        method: "POST",
        body: JSON.stringify({ stage: _triggerStageName }),
      });
      showToast(res.message, "success");
      stopTriggerPoll();
      document.getElementById("trigger-progress").classList.add("hidden");
      loadStatus();
      scheduleRefresh();
    } catch (e) {
      showToast(`停止失败：${e.message}`, "error");
      btn.disabled = false;
      btn.textContent = "停止执行";
    }
  });

  // 日志弹层关闭
  const closeLogModal = () => {
    document.getElementById("log-modal").classList.remove("open");
    clearInterval(_logModalTimer);
  };
  document.getElementById("log-modal-close").addEventListener("click", closeLogModal);
  document.getElementById("log-modal").addEventListener("click", e => {
    if (e.target === e.currentTarget) closeLogModal();
  });

  // 事件委托（只注册一次，不随 renderStages 重建）
  setupStageListeners();

  // 首次加载任务状态（首次显示 spinner）
  loadStatus(true);
  scheduleRefresh();
});
