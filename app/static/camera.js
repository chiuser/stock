"use strict";

function getToken() { return localStorage.getItem("token"); }
function getUsername() { return localStorage.getItem("username"); }

function logout() {
  localStorage.removeItem("token");
  localStorage.removeItem("username");
  location.href = "/login";
}

function authHeaders() {
  const token = getToken();
  if (!token) { logout(); throw new Error("no token"); }
  return { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" };
}

async function apiFetch(url, opts = {}) {
  opts.headers = { ...authHeaders(), ...(opts.headers || {}) };
  const res = await fetch(url, opts);
  if (res.status === 401) { logout(); throw new Error("401"); }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
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

function asText(value) {
  return JSON.stringify(value, null, 2);
}

function kvHtml(rows) {
  return rows.map(([k, v]) => `
    <div class="camera-kv-row">
      <span>${k}</span>
      <strong>${v === undefined || v === null || v === "" ? "—" : v}</strong>
    </div>
  `).join("");
}

async function loadStatus() {
  const data = await apiFetch("/api/camera/status");
  renderStatus(data);
}

function renderStatus(data) {
  const camera = data.camera;
  const faces = data.faces;
  const events = data.events;
  const feishu = data.feishu;
  document.getElementById("camera-summary").textContent =
    `${camera.configured ? "摄像头已配置" : "摄像头未配置"} · 本地头像 ${faces.count} 张`;

  document.getElementById("camera-config").innerHTML = kvHtml([
    ["摄像头地址", camera.base_url],
    ["账号", camera.username],
    ["密码", camera.password_mode === "blank" ? "空密码" : (camera.has_password ? "已配置" : "未配置")],
    ["Owner", camera.has_owner ? "已配置" : "未配置"],
    ["脸库 ID", camera.face_group_id],
    ["脸库名称", camera.face_group_name],
    ["上传模板", camera.has_custom_person_xml_template ? "自定义" : "默认"],
  ]);

  const endpoint = events.has_secret
    ? "/api/p6s/events/<P6S_EVENT_SECRET>"
    : "/api/p6s/events";
  document.getElementById("event-config").innerHTML = kvHtml([
    ["事件路径", endpoint],
    ["鉴权", events.has_secret ? "已启用" : "未启用"],
    ["事件目录", events.dir],
    ["已存事件", events.count],
    ["公网地址", events.public_base_url || "未配置 PUBLIC_BASE_URL"],
  ]);

  document.getElementById("face-summary").innerHTML = kvHtml([
    ["头像目录", faces.dir],
    ["头像数量", faces.count],
  ]);
  renderFaceList(faces.sample || []);

  document.getElementById("feishu-config").innerHTML = kvHtml([
    ["Webhook", feishu.has_webhook ? "已配置" : "未配置"],
    ["应用 ID", feishu.has_app_id ? "已配置" : "未配置"],
    ["应用密钥", feishu.has_app_secret ? "已配置" : "未配置"],
    ["可发图片", feishu.can_upload_image ? "是" : "否"],
  ]);
}

function renderFaceList(items) {
  const wrap = document.getElementById("face-list");
  if (!items.length) {
    wrap.innerHTML = '<p class="camera-desc">暂无头像样本</p>';
    return;
  }
  wrap.innerHTML = items.map(item => `
    <div class="camera-face-row">
      <span>${item.member_id}</span>
      <small>${item.bytes} bytes</small>
    </div>
  `).join("");
}

async function runAction(button, resultEl, action) {
  const oldText = button.textContent;
  button.disabled = true;
  button.textContent = "执行中…";
  resultEl.textContent = "执行中…";
  try {
    const data = await action();
    resultEl.textContent = asText(data);
    showToast("操作完成", data.ok === false ? "error" : "success");
    await loadStatus();
  } catch (err) {
    resultEl.textContent = err.message || String(err);
    showToast(err.message || "操作失败", "error");
  } finally {
    button.disabled = false;
    button.textContent = oldText;
  }
}

function initNav() {
  document.getElementById("nav-username").textContent = getUsername() || "";
  document.getElementById("nav-logout").addEventListener("click", logout);
}

function initActions() {
  document.getElementById("btn-refresh").addEventListener("click", loadStatus);

  document.getElementById("btn-test-camera").addEventListener("click", e => {
    runAction(e.target, document.getElementById("camera-test-result"), () =>
      apiFetch("/api/camera/test-connection", { method: "POST" })
    );
  });

  document.getElementById("btn-set-owner").addEventListener("click", e => {
    const owner = document.getElementById("owner-input").value.trim() || null;
    runAction(e.target, document.getElementById("owner-result"), () =>
      apiFetch("/api/camera/owner", {
        method: "POST",
        body: JSON.stringify({ owner }),
      })
    );
  });

  document.getElementById("btn-create-group").addEventListener("click", e => {
    const thresholdRaw = document.getElementById("group-threshold").value.trim();
    const body = {
      group_id: document.getElementById("group-id").value.trim() || null,
      group_name: document.getElementById("group-name").value.trim() || null,
      threshold: thresholdRaw ? Number(thresholdRaw) : null,
    };
    runAction(e.target, document.getElementById("group-result"), () =>
      apiFetch("/api/camera/face-group", {
        method: "POST",
        body: JSON.stringify(body),
      })
    );
  });

  document.getElementById("btn-upload-one").addEventListener("click", e => {
    const memberId = document.getElementById("member-id").value.trim();
    if (!memberId) {
      showToast("请先输入会员 ID", "error");
      return;
    }
    runAction(e.target, document.getElementById("upload-result"), () =>
      apiFetch("/api/camera/faces/upload", {
        method: "POST",
        body: JSON.stringify({ member_id: memberId }),
      })
    );
  });

  document.getElementById("btn-upload-batch").addEventListener("click", e => {
    const raw = document.getElementById("batch-limit").value.trim();
    const limit = raw ? Number(raw) : 1;
    runAction(e.target, document.getElementById("upload-result"), () =>
      apiFetch("/api/camera/faces/upload-batch", {
        method: "POST",
        body: JSON.stringify({ limit }),
      })
    );
  });

  document.getElementById("btn-test-feishu").addEventListener("click", e => {
    runAction(e.target, document.getElementById("feishu-result"), () =>
      apiFetch("/api/camera/feishu/test", { method: "POST" })
    );
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  initNav();
  initActions();
  try {
    await loadStatus();
  } catch (err) {
    showToast(err.message || "加载失败", "error");
  }
});
