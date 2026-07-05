"use strict";

const state = {
  page: 1,
  pageSize: 30,
  total: 0,
  modalOpen: false,
  timer: null,
  currentItems: [],
  imageUrls: new Map(),
};

const classificationLabels = {
  same_person: "同人确认",
  camera_missed_but_gallery_hit: "摄像头漏识别",
  camera_hit_but_recheck_filtered: "摄像头命中但模型过滤",
  identity_conflict: "疑似识错",
  both_unknown_or_filtered: "未知或已过滤",
};

const cameraResultLabels = {
  known: "已匹配",
  stranger: "陌生人",
  unknown: "未知",
};

const recheckStatusLabels = {
  passed: "通过",
  filtered: "已过滤",
  error: "异常",
  not_rechecked: "未复核",
};

const roleLabels = {
  member: "会员",
  class_member: "上课会员",
  staff: "员工",
  coach: "教练",
};

const els = {};

function getToken() { return localStorage.getItem("token"); }
function getUsername() { return localStorage.getItem("username"); }

function logout() {
  localStorage.removeItem("token");
  localStorage.removeItem("username");
  location.href = "/login";
}

function authHeaders(contentType = "application/json") {
  const token = getToken();
  if (!token) { logout(); throw new Error("no token"); }
  const headers = { "Authorization": `Bearer ${token}` };
  if (contentType) headers["Content-Type"] = contentType;
  return headers;
}

async function apiFetch(url) {
  const res = await fetch(url, { headers: authHeaders() });
  if (res.status === 401) { logout(); throw new Error("401"); }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

async function imageFetch(apiUrl) {
  const res = await fetch(apiUrl, { headers: authHeaders(null) });
  if (res.status === 401) { logout(); throw new Error("401"); }
  if (!res.ok) throw new Error(`image HTTP ${res.status}`);
  return res.blob();
}

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

function html(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function text(value, fallback = "—") {
  const raw = value === null || value === undefined ? "" : String(value).trim();
  return raw || fallback;
}

function numberText(value, digits = 3) {
  if (value === null || value === undefined || value === "") return "—";
  const num = Number(value);
  if (!Number.isFinite(num)) return text(value);
  return num.toFixed(digits);
}

function percentText(value) {
  const num = Number(value || 0);
  if (!Number.isFinite(num)) return "0.0%";
  return `${(num * 100).toFixed(1)}%`;
}

function shortTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return text(value);
  return date.toLocaleString("zh-CN", { hour12: false });
}

function localDateValue(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function label(map, value) {
  return map[value] || text(value);
}

function roleText(value, fallbackValue = "") {
  return roleLabels[value] || text(fallbackValue || value);
}

function badgeClass(classification) {
  if (classification === "same_person") return "monitor-badge monitor-badge-good";
  if (classification === "identity_conflict") return "monitor-badge monitor-badge-danger";
  if (classification === "camera_missed_but_gallery_hit") return "monitor-badge monitor-badge-warn";
  if (classification === "camera_hit_but_recheck_filtered") return "monitor-badge monitor-badge-muted";
  return "monitor-badge";
}

function initElements() {
  [
    "nav-username", "nav-logout", "btn-refresh", "monitor-summary-text", "monitor-refresh-state",
    "stat-total", "stat-conflict", "stat-missed", "stat-same", "stat-filtered", "stat-no-face",
    "filter-date", "filter-classification", "filter-camera-result", "filter-recheck-status",
    "filter-reason", "filter-person", "filter-person-type", "filter-accepted", "btn-apply-filters", "btn-reset-filters",
    "quality-days", "quality-desc", "quality-conflict-rate", "quality-missed-rate",
    "quality-filtered-rate", "quality-trends", "quality-reasons", "quality-examples",
    "page-size", "events-body", "monitor-list-desc", "btn-prev-page", "btn-next-page", "page-state",
    "event-modal", "modal-backdrop", "modal-close", "modal-classification", "modal-title",
    "modal-subtitle", "modal-background-img", "modal-background-placeholder", "modal-capture-img",
    "modal-background-overlay", "modal-capture-placeholder", "modal-crop-img", "modal-crop-placeholder", "modal-camera-kv",
    "modal-recheck-kv", "modal-gallery-kv", "modal-candidates", "modal-faces", "modal-safe-json",
  ].forEach(id => { els[id] = document.getElementById(id); });
}

function initNav() {
  els["nav-username"].textContent = getUsername() || "";
  els["nav-logout"].addEventListener("click", logout);
}

function initFilters() {
  els["filter-date"].value = localDateValue();
  els["page-size"].value = String(state.pageSize);

  els["btn-apply-filters"].addEventListener("click", () => {
    state.page = 1;
    loadDashboard();
  });
  els["btn-reset-filters"].addEventListener("click", () => {
    els["filter-date"].value = localDateValue();
    ["filter-classification", "filter-camera-result", "filter-recheck-status", "filter-person-type", "filter-accepted"].forEach(id => {
      els[id].value = "";
    });
    els["filter-reason"].value = "";
    els["filter-person"].value = "";
    state.page = 1;
    state.pageSize = 30;
    els["page-size"].value = "30";
    loadDashboard();
  });

  ["filter-date", "filter-classification", "filter-camera-result", "filter-recheck-status", "filter-person-type", "filter-accepted"].forEach(id => {
    els[id].addEventListener("change", () => {
      state.page = 1;
      loadDashboard();
    });
  });
  ["filter-reason", "filter-person"].forEach(id => {
    els[id].addEventListener("keydown", event => {
      if (event.key === "Enter") {
        state.page = 1;
        loadDashboard();
      }
    });
  });
  els["page-size"].addEventListener("change", () => {
    state.pageSize = Number(els["page-size"].value) || 30;
    state.page = 1;
    loadDashboard();
  });
  els["quality-days"].addEventListener("change", () => loadDashboard());
}

function initActions() {
  els["btn-refresh"].addEventListener("click", () => loadDashboard());
  document.querySelectorAll("[data-quality-filter]").forEach(button => {
    button.addEventListener("click", () => {
      els["filter-classification"].value = button.dataset.qualityFilter || "";
      state.page = 1;
      loadDashboard();
    });
  });
  els["btn-prev-page"].addEventListener("click", () => {
    if (state.page <= 1) return;
    state.page -= 1;
    loadDashboard();
  });
  els["btn-next-page"].addEventListener("click", () => {
    const maxPage = Math.max(1, Math.ceil(state.total / state.pageSize));
    if (state.page >= maxPage) return;
    state.page += 1;
    loadDashboard();
  });
  els["modal-close"].addEventListener("click", closeModal);
  els["modal-backdrop"].addEventListener("click", closeModal);
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && state.modalOpen) closeModal();
  });
}

function initAutoRefresh() {
  state.timer = setInterval(() => {
    if (!state.modalOpen) {
      loadDashboard({ silent: true });
    }
  }, 10000);
}

function currentFilters() {
  return {
    date: els["filter-date"].value || localDateValue(),
    classification: els["filter-classification"].value,
    camera_result: els["filter-camera-result"].value,
    recheck_status: els["filter-recheck-status"].value,
    reason: els["filter-reason"].value.trim(),
    person: els["filter-person"].value.trim(),
    person_type: els["filter-person-type"].value,
    accepted: els["filter-accepted"].value,
  };
}

function buildQuery(extra = {}) {
  const params = new URLSearchParams();
  Object.entries({ ...currentFilters(), ...extra }).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) params.set(key, value);
  });
  return params.toString();
}

function currentQualityRange() {
  const dateTo = currentFilters().date;
  const days = Math.max(3, Math.min(Number(els["quality-days"].value) || 7, 14));
  const start = new Date(`${dateTo}T00:00:00`);
  if (Number.isNaN(start.getTime())) {
    return { date_from: dateTo, date_to: dateTo };
  }
  start.setDate(start.getDate() - days + 1);
  return { date_from: localDateValue(start), date_to: dateTo };
}

async function loadDashboard(opts = {}) {
  const silent = opts.silent === true;
  if (!silent) setLoading();
  try {
    const summaryUrl = `/api/recognition-monitor/summary?${buildQuery()}`;
    const eventsUrl = `/api/recognition-monitor/events?${buildQuery({ page: state.page, page_size: state.pageSize })}`;
    const qualityUrl = `/api/recognition-monitor/quality?${new URLSearchParams(currentQualityRange()).toString()}`;
    const [summary, events, quality] = await Promise.all([apiFetch(summaryUrl), apiFetch(eventsUrl), apiFetch(qualityUrl)]);
    renderSummary(summary);
    renderQuality(quality);
    renderEvents(events);
    els["monitor-refresh-state"].textContent = `已刷新 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`;
  } catch (err) {
    if (!silent) {
      renderError(err.message || "加载失败");
      showToast(err.message || "加载失败", "error");
    }
  }
}

function setLoading() {
  els["events-body"].innerHTML = '<tr><td colspan="7" class="monitor-empty">正在加载...</td></tr>';
}

function renderError(message) {
  els["events-body"].innerHTML = `<tr><td colspan="7" class="monitor-empty monitor-error">${html(message)}</td></tr>`;
}

function renderSummary(summary) {
  const classification = summary.classification_counts || {};
  const status = summary.recheck_status_counts || {};
  const reasons = summary.reason_counts || {};
  els["stat-total"].textContent = summary.total ?? 0;
  els["stat-conflict"].textContent = classification.identity_conflict || 0;
  els["stat-missed"].textContent = classification.camera_missed_but_gallery_hit || 0;
  els["stat-same"].textContent = classification.same_person || 0;
  els["stat-filtered"].textContent = status.filtered || 0;
  els["stat-no-face"].textContent = reasons.no_face || 0;
  els["monitor-summary-text"].textContent = `${summary.date || currentFilters().date} · 共 ${summary.total || 0} 条识别记录`;
}

function renderQuality(quality) {
  const rates = quality.rates || {};
  els["quality-desc"].textContent = `${quality.date_from || "—"} 至 ${quality.date_to || "—"} · 共 ${quality.total || 0} 条`;
  els["quality-conflict-rate"].textContent = percentText(rates.identity_conflict);
  els["quality-missed-rate"].textContent = percentText(rates.camera_missed_but_gallery_hit);
  els["quality-filtered-rate"].textContent = percentText(rates.filtered);
  renderQualityTrends(quality.by_day || []);
  renderQualityReasons(quality.reason_counts || {});
  renderQualityExamples(quality.attention_examples || {});
}

function renderQualityTrends(days) {
  if (!days.length) {
    els["quality-trends"].innerHTML = '<p class="monitor-muted">暂无趋势数据</p>';
    return;
  }
  const maxTotal = Math.max(...days.map(day => day.total || 0), 1);
  els["quality-trends"].innerHTML = days.map(day => {
    const classification = day.classification_counts || {};
    const width = Math.max(4, Math.round(((day.total || 0) / maxTotal) * 100));
    return `
      <div class="monitor-trend-row">
        <span>${html(day.date)}</span>
        <div class="monitor-trend-bar"><i style="width:${width}%"></i></div>
        <strong>${html(day.total || 0)}</strong>
        <small>冲突 ${html(classification.identity_conflict || 0)} · 漏识别 ${html(classification.camera_missed_but_gallery_hit || 0)}</small>
      </div>
    `;
  }).join("");
}

function renderQualityReasons(reasonCounts) {
  const items = Object.entries(reasonCounts)
    .filter(([key]) => key && key !== "unknown")
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 8);
  if (!items.length) {
    els["quality-reasons"].innerHTML = '<p class="monitor-muted">暂无过滤原因</p>';
    return;
  }
  els["quality-reasons"].innerHTML = items.map(([reason, count]) => `
    <button class="monitor-reason-chip" data-reason="${html(reason)}" type="button">
      <span>${html(reason)}</span>
      <strong>${html(count)}</strong>
    </button>
  `).join("");
  els["quality-reasons"].querySelectorAll("[data-reason]").forEach(button => {
    button.addEventListener("click", () => {
      els["filter-reason"].value = button.dataset.reason || "";
      state.page = 1;
      loadDashboard();
    });
  });
}

function renderQualityExamples(examples) {
  const groups = [
    ["identity_conflict", "疑似识错"],
    ["camera_missed_but_gallery_hit", "摄像头漏识别"],
    ["camera_hit_but_recheck_filtered", "模型过滤"],
  ];
  const cards = [];
  groups.forEach(([key, title]) => {
    (examples[key] || []).slice(0, 3).forEach(item => {
      const person = item.gallery && item.gallery.name ? item.gallery.name : (item.camera && item.camera.name);
      cards.push(`
        <button class="monitor-example-row" data-event-key="${html(item.event_key)}" type="button">
          <span>${html(title)}</span>
          <strong>${html(text(person, "未知人员"))}</strong>
          <small>${html(shortTime(item.event_time))} · ${html(label(classificationLabels, item.classification))}</small>
        </button>
      `);
    });
  });
  els["quality-examples"].innerHTML = cards.length ? cards.join("") : '<p class="monitor-muted">暂无典型问题样例</p>';
  els["quality-examples"].querySelectorAll("[data-event-key]").forEach(button => {
    button.addEventListener("click", () => openDetail(button.dataset.eventKey));
  });
}

function renderEvents(payload) {
  state.total = payload.total || 0;
  state.currentItems = payload.items || [];
  const maxPage = Math.max(1, Math.ceil(state.total / state.pageSize));
  els["monitor-list-desc"].textContent = `共 ${state.total} 条，当前第 ${state.page} / ${maxPage} 页`;
  els["page-state"].textContent = `第 ${state.page} / ${maxPage} 页`;
  els["btn-prev-page"].disabled = state.page <= 1;
  els["btn-next-page"].disabled = state.page >= maxPage;

  if (!state.currentItems.length) {
    els["events-body"].innerHTML = '<tr><td colspan="7" class="monitor-empty">没有符合条件的识别记录</td></tr>';
    return;
  }

  els["events-body"].innerHTML = state.currentItems.map(item => renderEventRow(item)).join("");
  els["events-body"].querySelectorAll("[data-event-key]").forEach(button => {
    button.addEventListener("click", () => openDetail(button.dataset.eventKey));
  });
  els["events-body"].querySelectorAll("[data-monitor-image]").forEach(img => {
    loadImageInto(img.dataset.monitorImage, img, img.closest(".monitor-thumb"));
  });
}

function renderEventRow(item) {
  const camera = item.camera || {};
  const recheck = item.recheck || {};
  const gallery = item.gallery || {};
  const background = imageApi(item.images && item.images.background);
  const galleryName = gallery.accepted ? `${text(gallery.name)} · ${roleText(gallery.person_type, gallery.group_name)}` : "未命中";
  return `
    <tr>
      <td>
        <div class="monitor-time-cell">
          <button class="monitor-thumb" data-event-key="${html(item.event_key)}" type="button" title="查看详情">
            ${background ? `<img data-monitor-image="${html(background)}" alt="背景缩略图">` : '<span>无图</span>'}
          </button>
          <div>
            <strong>${html(shortTime(item.event_time))}</strong>
            <small>${html(text(item.device_sn, "未知设备"))}</small>
          </div>
        </div>
      </td>
      <td>
        <strong>${html(text(item.event_id))}</strong>
      </td>
      <td>
        <strong>${html(label(cameraResultLabels, camera.result))}</strong>
        <small>${html(text(camera.name || camera.id, "无匹配人员"))}</small>
        <small>${html(text(camera.role_name || camera.role, ""))}</small>
      </td>
      <td>
        <strong>${html(label(recheckStatusLabels, recheck.status))}</strong>
        <small>${html(text(recheck.reason, "无过滤原因"))}</small>
        <small>人脸 ${html(recheck.face_count || 0)} · 通过 ${html(recheck.accepted_face_count || 0)} · 冲突 ${recheck.has_identity_conflict ? "是" : "否"}</small>
        <small>检测分 ${html(numberText(recheck.det_score))} · 正脸 ${html(numberText(recheck.frontal_score))}</small>
      </td>
      <td>
        <strong>${html(galleryName)}</strong>
        <small>ID ${html(text(gallery.person_id, "—"))}</small>
        <small>相似度 ${html(numberText(gallery.similarity))} / 第二名 ${html(numberText(gallery.second_similarity))}</small>
      </td>
      <td>
        <span class="${badgeClass(item.classification)}">${html(label(classificationLabels, item.classification))}</span>
        <small>${html(text(gallery.camera_identity_status, ""))}</small>
      </td>
      <td>
        <button class="admin-btn admin-btn-ghost" data-event-key="${html(item.event_key)}" type="button">详情</button>
      </td>
    </tr>
  `;
}

function imageApi(image) {
  if (!image || image.status !== "saved" || !image.api_url) return "";
  return image.api_url;
}

async function loadImageInto(apiUrl, img, frame) {
  if (!apiUrl || !img) return;
  try {
    const blob = await imageFetch(apiUrl);
    const oldUrl = state.imageUrls.get(img);
    if (oldUrl) URL.revokeObjectURL(oldUrl);
    const objectUrl = URL.createObjectURL(blob);
    state.imageUrls.set(img, objectUrl);
    await new Promise(resolve => {
      img.onload = resolve;
      img.onerror = resolve;
      img.src = objectUrl;
    });
    img.onload = null;
    img.onerror = null;
    img.hidden = !img.naturalWidth;
    if (frame) frame.classList.toggle("has-image", !img.hidden);
  } catch {
    img.hidden = true;
    if (frame) frame.classList.remove("has-image");
  }
}

async function openDetail(eventKey) {
  if (!eventKey) return;
  state.modalOpen = true;
  els["event-modal"].classList.add("visible");
  els["event-modal"].setAttribute("aria-hidden", "false");
  clearModal();
  try {
    const detail = await apiFetch(`/api/recognition-monitor/events/${encodeURIComponent(eventKey)}`);
    renderDetail(detail);
  } catch (err) {
    showToast(err.message || "详情加载失败", "error");
    closeModal();
  }
}

function closeModal() {
  state.modalOpen = false;
  els["event-modal"].classList.remove("visible");
  els["event-modal"].setAttribute("aria-hidden", "true");
}

function clearModal() {
  els["modal-classification"].textContent = "加载中";
  els["modal-title"].textContent = "识别详情";
  els["modal-subtitle"].textContent = "正在读取详细数据...";
  ["modal-background-img", "modal-capture-img", "modal-crop-img"].forEach(id => {
    els[id].removeAttribute("src");
    els[id].hidden = true;
  });
  ["modal-background-placeholder", "modal-capture-placeholder", "modal-crop-placeholder"].forEach(id => {
    els[id].hidden = false;
  });
  els["modal-camera-kv"].innerHTML = "";
  els["modal-recheck-kv"].innerHTML = "";
  els["modal-gallery-kv"].innerHTML = "";
  els["modal-candidates"].innerHTML = "";
  els["modal-background-overlay"].innerHTML = "";
  els["modal-faces"].innerHTML = "";
  els["modal-safe-json"].textContent = "—";
}

function renderDetail(detail) {
  const camera = detail.camera || {};
  const recheck = detail.recheck || {};
  const gallery = detail.gallery || {};
  const record = detail.record || {};
  els["modal-classification"].className = badgeClass(detail.classification);
  els["modal-classification"].textContent = label(classificationLabels, detail.classification);
  els["modal-title"].textContent = camera.name || gallery.name || "未知人员";
  els["modal-subtitle"].textContent = `${shortTime(detail.event_time)} · ${text(detail.device_sn, "未知设备")} · 事件 ${text(detail.event_id)}`;

  loadModalImage(detail.images && detail.images.background, "modal-background-img", "modal-background-placeholder")
    .then(() => renderBackgroundBoxes(detail.faces || []));
  loadModalImage(detail.images && detail.images.capture, "modal-capture-img", "modal-capture-placeholder");
  loadModalImage(detail.images && detail.images.insightface_crop, "modal-crop-img", "modal-crop-placeholder");

  els["modal-camera-kv"].innerHTML = kvHtml([
    ["识别结果", label(cameraResultLabels, camera.result)],
    ["姓名", camera.name],
    ["ID", camera.id],
    ["身份", camera.role_name || camera.role],
  ]);
  els["modal-recheck-kv"].innerHTML = kvHtml([
    ["状态", label(recheckStatusLabels, recheck.status)],
    ["原因", recheck.reason],
    ["人脸数量", recheck.face_count],
    ["Gallery 通过", recheck.accepted_face_count],
    ["摄像头目标", recheck.camera_target_face_status],
    ["身份冲突", recheck.has_identity_conflict ? "是" : "否"],
    ["检测分", numberText(recheck.det_score)],
    ["人脸尺寸", recheck.face_size],
    ["模糊分", numberText(recheck.blur_score)],
    ["正脸分", numberText(recheck.frontal_score)],
    ["质量标签", (recheck.quality_flags || []).join(", ")],
  ]);
  els["modal-gallery-kv"].innerHTML = kvHtml([
    ["是否命中", gallery.accepted === true ? "是" : (gallery.accepted === false ? "否" : "—")],
    ["姓名", gallery.name],
    ["ID", gallery.person_id],
    ["身份", roleText(gallery.person_type, gallery.group_name)],
    ["相似度", numberText(gallery.similarity)],
    ["第二名", numberText(gallery.second_similarity)],
    ["对齐状态", gallery.camera_identity_status],
  ]);
  renderCandidates(gallery.top5_candidates || []);
  renderFaces(detail.faces || []);
  els["modal-safe-json"].textContent = JSON.stringify({
    thresholds: record.thresholds || {},
    quality_flags: recheck.quality_flags || [],
    face_recheck_status: recheck.status,
    face_recheck_reason: recheck.reason,
  }, null, 2);
}

function loadModalImage(image, imgId, placeholderId) {
  const apiUrl = imageApi(image);
  const img = els[imgId];
  const placeholder = els[placeholderId];
  if (!apiUrl) {
    img.hidden = true;
    placeholder.hidden = false;
    return Promise.resolve();
  }
  return loadImageInto(apiUrl, img, img.closest(".monitor-image-frame")).then(() => {
    placeholder.hidden = !img.hidden;
  });
}

function kvHtml(rows) {
  return rows.map(([key, value]) => `
    <div class="monitor-kv-row">
      <span>${html(key)}</span>
      <strong>${html(text(value))}</strong>
    </div>
  `).join("");
}

function renderCandidates(candidates) {
  if (!candidates.length) {
    els["modal-candidates"].innerHTML = '<p class="monitor-muted">暂无候选集</p>';
    return;
  }
  els["modal-candidates"].innerHTML = candidates.slice(0, 5).map((item, index) => {
    const name = item.name || item.person_name || item.person_id || "未知";
    const id = item.person_id || item.credential_no || item.id || "";
    const type = item.person_type || item.group_name || "";
    const similarity = item.similarity ?? item.score;
    return `
      <div class="monitor-candidate-row">
        <span>${index + 1}</span>
        <strong>${html(text(name))}</strong>
        <small>${html(roleText(type))} · ID ${html(text(id))} · ${html(numberText(similarity))}</small>
      </div>
    `;
  }).join("");
}

function renderFaces(faces) {
  if (!faces.length) {
    els["modal-faces"].innerHTML = '<p class="monitor-muted">暂无逐脸结果</p>';
    return;
  }
  const groups = [
    ["background", "背景图人脸"],
    ["capture", "摄像头人脸图"],
  ];
  els["modal-faces"].innerHTML = groups.map(([source, title]) => {
    const items = faces.filter(face => face.image_source === source);
    if (!items.length) return "";
    return `
      <div class="monitor-face-group">
        <h5>${html(title)}</h5>
        <div class="monitor-face-card-grid">
          ${items.map(face => faceCardHtml(face)).join("")}
        </div>
      </div>
    `;
  }).join("") || '<p class="monitor-muted">暂无逐脸结果</p>';
  els["modal-faces"].querySelectorAll("[data-face-key]").forEach(card => {
    card.addEventListener("click", () => highlightFaceBox(card.dataset.faceKey || ""));
  });
  els["modal-faces"].querySelectorAll("[data-face-crop]").forEach(img => {
    loadImageInto(img.dataset.faceCrop, img, img.closest(".monitor-face-crop"));
  });
}

function faceCardHtml(face) {
  const quality = face.quality || {};
  const gallery = face.gallery || {};
  const cropApi = imageApi(face.crop);
  const galleryTitle = gallery.name
    ? `${gallery.name} · ${roleText(gallery.person_type, gallery.group_name)}`
    : "未命中";
  return `
    <button class="monitor-face-card" data-face-key="${html(face.face_key)}" type="button">
      <div class="monitor-face-crop">
        ${cropApi ? `<img data-face-crop="${html(cropApi)}" alt="逐脸裁剪图">` : '<span>无裁剪图</span>'}
      </div>
      <div class="monitor-face-card-body">
        <strong>${html(text(face.face_key))} · ${html(text(face.position_hint, ""))}</strong>
        <small>${html(label(recheckStatusLabels, face.status))} · ${html(text(face.reason))}</small>
        <small>${html(galleryTitle)} · ${gallery.accepted ? "通过" : "未通过"}</small>
        <small>相似度 ${html(numberText(gallery.similarity))} · 第二名 ${html(numberText(gallery.second_similarity))}</small>
        <small>检测分 ${html(numberText(quality.det_score))} · 正脸 ${html(numberText(quality.frontal_score))}</small>
        <div class="monitor-face-candidates">${html(candidateOneLine(gallery.top5_candidates || []))}</div>
      </div>
    </button>
  `;
}

function candidateOneLine(candidates) {
  if (!candidates.length) return "候选集：无";
  return `候选集：${candidates.slice(0, 5).map((item, idx) => {
    const name = item.name || item.person_id || "未知";
    const score = item.similarity ?? item.score ?? "—";
    return `${idx + 1}. ${name}/${numberText(score)}`;
  }).join("；")}`;
}

function renderBackgroundBoxes(faces) {
  const overlay = els["modal-background-overlay"];
  const img = els["modal-background-img"];
  overlay.innerHTML = "";
  if (img.hidden || !img.naturalWidth || !img.naturalHeight) return;
  const backgroundFaces = faces.filter(face => face.image_source === "background" && Array.isArray(face.bbox) && face.bbox.length >= 4);
  if (!backgroundFaces.length) return;
  const frame = img.closest(".monitor-image-frame");
  const frameRect = frame.getBoundingClientRect();
  const imageAspect = img.naturalWidth / img.naturalHeight;
  const frameAspect = frameRect.width / frameRect.height;
  let renderedWidth = frameRect.width;
  let renderedHeight = frameRect.height;
  let offsetX = 0;
  let offsetY = 0;
  if (frameAspect > imageAspect) {
    renderedWidth = frameRect.height * imageAspect;
    offsetX = (frameRect.width - renderedWidth) / 2;
  } else {
    renderedHeight = frameRect.width / imageAspect;
    offsetY = (frameRect.height - renderedHeight) / 2;
  }
  overlay.innerHTML = backgroundFaces.map((face, index) => {
    const [x1, y1, x2, y2] = face.bbox.map(Number);
    const left = offsetX + (x1 / img.naturalWidth) * renderedWidth;
    const top = offsetY + (y1 / img.naturalHeight) * renderedHeight;
    const width = ((x2 - x1) / img.naturalWidth) * renderedWidth;
    const height = ((y2 - y1) / img.naturalHeight) * renderedHeight;
    const accepted = face.gallery && face.gallery.accepted;
    return `
      <button class="monitor-bbox ${accepted ? "accepted" : ""}" data-box-key="${html(face.face_key)}"
        style="left:${left}px;top:${top}px;width:${width}px;height:${height}px" type="button">
        <span>${index + 1}</span>
      </button>
    `;
  }).join("");
  overlay.querySelectorAll("[data-box-key]").forEach(box => {
    box.addEventListener("click", () => highlightFaceCard(box.dataset.boxKey || ""));
  });
}

function highlightFaceBox(faceKey) {
  document.querySelectorAll(".monitor-bbox").forEach(box => {
    box.classList.toggle("active", box.dataset.boxKey === faceKey);
  });
}

function highlightFaceCard(faceKey) {
  document.querySelectorAll(".monitor-face-card").forEach(card => {
    card.classList.toggle("active", card.dataset.faceKey === faceKey);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initElements();
  initNav();
  initFilters();
  initActions();
  initAutoRefresh();
  loadDashboard();
});
