'use strict';

// 已登录则直接跳转
if (localStorage.getItem('token')) {
  location.href = '/portfolio';
}

const usernameEl = document.getElementById('username');
const passwordEl = document.getElementById('password');
const loginBtn   = document.getElementById('login-btn');
const errorEl    = document.getElementById('login-error');

function showError(msg) {
  errorEl.textContent = msg;
  errorEl.style.display = 'block';
}

async function doLogin() {
  const username = usernameEl.value.trim();
  const password = passwordEl.value;
  if (!username || !password) { showError('请输入用户名和密码'); return; }

  loginBtn.disabled = true;
  loginBtn.textContent = '登录中...';
  errorEl.style.display = 'none';

  try {
    const res = await fetch('/api/auth/login', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ username, password }),
    });

    if (res.ok) {
      const data = await res.json();
      localStorage.setItem('token',    data.token);
      localStorage.setItem('username', data.username);
      location.href = '/portfolio';
    } else {
      const err = await res.json().catch(() => ({}));
      showError(err.detail || '登录失败，请重试');
    }
  } catch {
    showError('网络错误，请检查连接');
  } finally {
    loginBtn.disabled = false;
    loginBtn.textContent = '登 录';
  }
}

loginBtn.addEventListener('click', doLogin);

[usernameEl, passwordEl].forEach(el => {
  el.addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
});

// 自动聚焦用户名输入框
usernameEl.focus();
