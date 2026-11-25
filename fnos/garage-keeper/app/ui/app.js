'use strict';

/* ================================================================ 工具函数 */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const ESC_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const esc = (v) => String(v === null || v === undefined ? '' : v).replace(/[&<>"']/g, (c) => ESC_MAP[c]);

const VTYPE = { ev: '纯电动车', ice: '燃油车', phev: '插电混动' };
const RTYPE = { maintenance: '保养', repair: '维修', expense: '其他开销' };
const KIND = { fuel: '加油', charge: '充电' };

function nf(value, digits = 0) {
  if (value === null || value === undefined || value === '' || Number.isNaN(Number(value))) return '—';
  return Number(value).toLocaleString('zh-CN', {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  });
}

function money(value, digits = 2) {
  if (value === null || value === undefined || value === '' || Number.isNaN(Number(value))) return '—';
  const sym = (State.settings && State.settings.currency) || '¥';
  const n = Number(value);
  return sym + n.toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: digits });
}

function qty(value, unit) {
  if (value === null || value === undefined) return '—';
  return `${nf(value, 1)} ${unit}`;
}

function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function fmtDate(v) { return v ? String(v).slice(0, 10) : '—'; }

function daysLeftText(n) {
  if (n === null || n === undefined) return '';
  if (n < 0) return `已逾期 ${Math.abs(n)} 天`;
  if (n === 0) return '今天到期';
  return `还有 ${n} 天`;
}

function kmLeftText(n) {
  if (n === null || n === undefined) return '';
  if (n < 0) return `已超 ${nf(Math.abs(n))} km`;
  return `还有 ${nf(n)} km`;
}

function levelLabel(level) {
  return level === 'overdue' ? '已逾期' : level === 'soon' ? '即将到期' : '计划中';
}

function levelClass(level) {
  return level === 'overdue' ? 'danger' : level === 'soon' ? 'warn' : 'neutral';
}

function consumptionText(summary, vtype) {
  if (vtype === 'ev') {
    return summary.charge_consumption === null || summary.charge_consumption === undefined
      ? '—' : `${nf(summary.charge_consumption, 2)} kWh/100km`;
  }
  return summary.fuel_consumption === null || summary.fuel_consumption === undefined
    ? '—' : `${nf(summary.fuel_consumption, 2)} L/100km`;
}

function debounce(fn, wait = 260) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), wait); };
}

/* ================================================================ 图标 */
const ICONS = {
  gauge: '<path d="M12 14l3.6-3.6"/><path d="M20.5 16.5a9 9 0 1 0-17 0"/><circle cx="12" cy="14" r="1.3"/>',
  car: '<path d="M5 16h14M6.5 16V9.5l2-3.5h7l2 3.5V16"/><path d="M6.5 11.5h11"/><circle cx="8.5" cy="16.6" r="1.5"/><circle cx="15.5" cy="16.6" r="1.5"/>',
  bolt: '<path d="M13 3 5 13h6l-1 8 8-10h-6l1-8Z"/>',
  wrench: '<path d="M14.6 6.4a4 4 0 0 0 5 5l1.4-1.4-1-4-4-1-1.4 1.4Z"/><path d="m14.4 7.6-8 8a2.1 2.1 0 1 0 3 3l8-8"/>',
  bell: '<path d="M18 8a6 6 0 1 0-12 0c0 5-2 6-2 6h16s-2-1-2-6"/><path d="M10.4 19.5a2 2 0 0 0 3.2 0"/>',
  sparkles: '<path d="M12 3v4M12 17v4M4.5 12h4M15.5 12h4M6.4 6.4l2.7 2.7M14.9 14.9l2.7 2.7M17.6 6.4l-2.7 2.7M9.1 14.9l-2.7 2.7"/>',
  database: '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6"/><path d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 7 19.4l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.7 1.7 0 0 0 3 13.7H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 7L4.5 7a2 2 0 1 1 2.8-2.8l.1.1A1.7 1.7 0 0 0 10 3V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 2.9 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9v.1a1.7 1.7 0 0 0 1.6 1h.1a2 2 0 1 1 0 4H21a1.7 1.7 0 0 0-1.6 1Z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
  trash: '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/>',
  download: '<path d="M12 3v12"/><path d="m7 11 5 5 5-5"/><path d="M4 20h16"/>',
  upload: '<path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M4 20h16"/>',
  check: '<path d="m5 13 4 4L19 7"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 5v6h-6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M14 3v5h5"/>',
  shield: '<path d="M12 3 5 6v5c0 5 3 8 7 10 4-2 7-5 7-10V6Z"/><path d="m9 12 2 2 4-4"/>',
  logout: '<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/><path d="m9 8-4 4 4 4"/><path d="M5 12h10"/>',
  user: '<circle cx="12" cy="8" r="3.6"/><path d="M4.5 20a7.5 7.5 0 0 1 15 0"/>',
};

function icon(name, cls = '') {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" class="${cls}" aria-hidden="true">${ICONS[name] || ''}</svg>`;
}

/* ================================================================ 请求 */
function authHeaders(extra = {}) {
  // 会话由 HttpOnly Cookie 承载，前端不接触任何凭据
  return Object.assign({}, extra);
}

async function api(path, options = {}) {
  const opts = Object.assign({}, options);
  opts.headers = authHeaders(options.headers || {});
  if (opts.body && !(opts.body instanceof FormData)) {
    opts.headers['Content-Type'] = 'application/json';
    if (typeof opts.body !== 'string') opts.body = JSON.stringify(opts.body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (err) {
    throw new Error('网络请求失败，请确认服务是否运行');
  }
  if (res.status === 401 && !path.startsWith('/api/auth/')) {
    showLogin('登录状态已失效，请重新登录');
    throw new Error('登录状态已失效');
  }
  const ct = res.headers.get('content-type') || '';
  let payload = null;
  if (ct.includes('application/json')) payload = await res.json().catch(() => null);
  else payload = await res.text().catch(() => '');
  if (!res.ok) {
    let detail = payload && payload.detail ? payload.detail : payload;
    if (Array.isArray(detail)) detail = detail.map((d) => d.msg || JSON.stringify(d)).join('；');
    throw new Error(typeof detail === 'string' && detail ? detail : `请求失败（${res.status}）`);
  }
  return payload;
}

async function download(path, fallbackName) {
  const res = await fetch(path, { headers: authHeaders() });
  if (!res.ok) throw new Error('下载失败');
  const blob = await res.blob();
  const cd = res.headers.get('content-disposition') || '';
  const m = /filename="?([^";]+)"?/.exec(cd);
  const name = m ? m[1] : fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

/* ================================================================ 状态 */
const State = {
  meta: null,
  route: { name: 'overview', id: null },
  vehicles: [],
  settings: {},
  reminders: [],
  reminderCount: 0,
  overview: null,
  detail: null,
  detailTab: 'all',
  energyItems: [],
  serviceItems: [],
  energyFilter: { vehicle_id: '', kind: '', from: '', to: '' },
  serviceFilter: { vehicle_id: '', rtype: '', from: '', to: '' },
  ai: null,
  csvTable: 'energy',
  user: null,
  authCfg: {},
  accounts: [],
  modalLocked: false,
};

const NAV = [
  { key: 'overview', label: '总览', icon: 'gauge' },
  { group: '车库' },
  { key: 'vehicles', label: '车辆档案', icon: 'car' },
  { key: 'energy', label: '能耗记录', icon: 'bolt' },
  { key: 'service', label: '保养维修', icon: 'wrench' },
  { key: 'reminders', label: '提醒', icon: 'bell' },
  { group: '工具' },
  { key: 'ai', label: '智能录入', icon: 'sparkles' },
  { key: 'data', label: '数据与备份', icon: 'database' },
  { key: 'settings', label: '设置', icon: 'settings' },
];

function currentRoute() {
  const raw = (location.hash || '').replace(/^#\/?/, '');
  if (!raw) return { name: 'overview', id: null };
  const parts = raw.split('/');
  return { name: parts[0] || 'overview', id: parts[1] ? Number(parts[1]) : null };
}

function renderNav() {
  const route = State.route;
  $('#nav').innerHTML = NAV.map((item) => {
    if (item.group) return `<div class="nav-group">${item.group}</div>`;
    const active = route.name === item.key || (item.key === 'vehicles' && route.name === 'vehicle');
    const count = item.key === 'reminders' && State.reminderCount
      ? `<span class="count warn">${State.reminderCount}</span>` : '';
    return `<a href="#/${item.key}" class="${active ? 'active' : ''}" data-nav>${icon(item.icon)}<span>${item.label}</span>${count}</a>`;
  }).join('');
}

function renderFoot() {
  const last = State.settings.last_backup_at
    ? String(State.settings.last_backup_at).slice(0, 16).replace('T', ' ') : '尚未备份';
  const u = State.user || {};
  const name = u.display_name || u.username || '未登录';
  const initial = String(name).trim().slice(0, 1) || '?';
  const isAdmin = u.role === 'admin';
  $('#sidebarFoot').innerHTML = `
    <div class="row"><span>版本</span><b>v${esc(State.meta ? State.meta.version : '—')}</b></div>
    <div class="row"><span>上次备份</span><b>${esc(last)}</b></div>
    <div class="user-chip">
      <div class="user-avatar">${esc(initial)}</div>
      <div class="user-meta">
        <b>${esc(name)}</b>
        <span>${esc(u.username || '')}${isAdmin ? ' · 管理员' : ' · 成员'}${u.legacy ? ' · 令牌' : ''}</span>
      </div>
      <button class="icon-btn" data-action="logout" title="退出登录" aria-label="退出登录">${icon('logout')}</button>
    </div>`;
}

function pageHead(title, sub, actions = '') {
  $('#pageTitle').textContent = title;
  $('#pageSub').textContent = sub || '';
  $('#topbarActions').innerHTML = actions;
}

async function refreshCore() {
  const [v, s, r] = await Promise.all([
    api('/api/vehicles'), api('/api/settings'), api('/api/reminders'),
  ]);
  State.vehicles = v.items || [];
  State.settings = s || {};
  State.reminders = r.items || [];
  State.reminderCount = State.reminders.filter((x) => x.level !== 'ok').length;
  renderNav();
  renderFoot();
}

/* ================================================================ 弹窗 / 表单 */
function closeModal(force = false) {
  if (State.modalLocked && !force) return;
  State.modalLocked = false;
  $('#modalRoot').innerHTML = '';
  document.body.style.overflow = '';
}

function toast(message, type = 'ok', ms = 3200) {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerHTML = `${icon(type === 'err' ? 'x' : type === 'warn' ? 'clock' : 'check')}<span>${esc(message)}</span>`;
  $('#toastRoot').appendChild(el);
  setTimeout(() => {
    el.style.transition = 'opacity .2s, transform .2s';
    el.style.opacity = '0';
    el.style.transform = 'translateY(6px)';
    setTimeout(() => el.remove(), 220);
  }, ms);
}

function confirmDialog({ title, message, confirmText = '确认', danger = false }) {
  return new Promise((resolve) => {
    const html = `
      <div class="modal-backdrop" data-backdrop>
        <div class="modal narrow">
          <div class="modal-head">
            <div><h3>${esc(title)}</h3></div>
            <button class="icon-btn" data-action="close-modal">${icon('x')}</button>
          </div>
          <div class="modal-body"><div class="small" style="color:var(--muted);line-height:1.75">${message}</div></div>
          <div class="modal-foot">
            <button class="btn" data-confirm="0">取消</button>
            <button class="btn ${danger ? 'danger' : 'primary'}" data-confirm="1">${esc(confirmText)}</button>
          </div>
        </div>
      </div>`;
    $('#modalRoot').innerHTML = html;
    document.body.style.overflow = 'hidden';
    $('#modalRoot').addEventListener('click', (e) => {
      const btn = e.target.closest('[data-confirm]');
      if (btn) {
        closeModal();
        resolve(btn.dataset.confirm === '1');
      }
    });
  });
}

function fieldHtml(f, values) {
  const raw = values[f.name] !== undefined ? values[f.name] : (f.value !== undefined ? f.value : '');
  const value = raw === null || raw === undefined ? '' : raw;
  const span = f.span === 2 ? ' span-2' : '';
  const hint = f.hint ? `<div class="hint">${esc(f.hint)}</div>` : '';
  const req = f.required ? 'required' : '';
  if (f.type === 'check') {
    return `<div class="field check${span}">
      <input type="checkbox" name="${f.name}" id="f-${f.name}" ${value ? 'checked' : ''}>
      <label for="f-${f.name}">${esc(f.label)}</label>${hint}</div>`;
  }
  let control = '';
  if (f.type === 'select') {
    control = `<select name="${f.name}" id="f-${f.name}" ${req}>${(f.options || []).map((o) => {
      const [v, label] = Array.isArray(o) ? o : [o.value, o.label];
      return `<option value="${esc(v)}" ${String(v) === String(value) ? 'selected' : ''}>${esc(label)}</option>`;
    }).join('')}</select>`;
  } else if (f.type === 'textarea') {
    control = `<textarea name="${f.name}" id="f-${f.name}" ${req} placeholder="${esc(f.placeholder || '')}">${esc(value)}</textarea>`;
  } else {
    const step = f.type === 'number' ? 'step="any"' : '';
    control = `<input type="${f.type || 'text'}" name="${f.name}" id="f-${f.name}" value="${esc(value)}"
      ${step} ${req} placeholder="${esc(f.placeholder || '')}" ${f.type === 'number' ? 'inputmode="decimal"' : ''}>`;
  }
  return `<div class="field${span}"><label for="f-${f.name}">${esc(f.label)}${f.required ? ' <span style="color:var(--danger)">*</span>' : ''}</label>${control}${hint}</div>`;
}

function openForm(cfg) {
  const fields = cfg.fields || [];
  const values = cfg.values || {};
  const body = fields.map((f) => (f.section
    ? `<div class="form-section">${esc(f.section)}</div>` : fieldHtml(f, values))).join('');
  $('#modalRoot').innerHTML = `
    <div class="modal-backdrop" data-backdrop>
      <div class="modal ${cfg.wide ? 'wide' : ''} ${cfg.narrow ? 'narrow' : ''}" role="dialog" aria-modal="true">
        <div class="modal-head">
          <div><h3>${esc(cfg.title)}</h3>${cfg.subtitle ? `<p>${esc(cfg.subtitle)}</p>` : ''}</div>
          ${cfg.lock ? '' : `<button class="icon-btn" data-action="close-modal">${icon('x')}</button>`}
        </div>
        <form id="modalForm" novalidate>
          <div class="modal-body"><div class="form-grid">${body}</div>${cfg.after || ''}</div>
          <div class="modal-foot">
            ${cfg.footerLeft || ''}
            ${cfg.hideCancel ? '' : `<button type="button" class="btn" data-action="close-modal">取消</button>`}
            <button type="submit" class="btn primary" id="modalSubmit">${esc(cfg.submitText || '保存')}</button>
          </div>
        </form>
      </div>
    </div>`;
  document.body.style.overflow = 'hidden';
  State.modalLocked = Boolean(cfg.lock);
  const form = $('#modalForm');
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const out = {};
    for (const f of fields) {
      if (f.section) continue;
      const el = form.elements[f.name];
      if (!el) continue;
      if (f.type === 'check') out[f.name] = el.checked ? 1 : 0;
      else if (f.type === 'number') out[f.name] = el.value === '' ? null : Number(el.value);
      else out[f.name] = el.value === '' ? null : el.value;
      if (f.required && (out[f.name] === null || out[f.name] === '')) {
        toast(`请填写「${f.label}」`, 'err');
        el.focus();
        return;
      }
    }
    const btn = $('#modalSubmit');
    btn.disabled = true;
    try {
      await cfg.onSubmit(out);
      closeModal(Boolean(cfg.lock));
    } catch (err) {
      toast(err.message || '保存失败', 'err');
    } finally {
      btn.disabled = false;
    }
  });
  setTimeout(() => {
    const first = form.querySelector('input:not([type=checkbox]), select, textarea');
    if (first) first.focus();
  }, 60);
}

/* ================================================================ 登录与账号 */
let authMode = 'login';
let authBusy = false;

function hideBoot() {
  const boot = $('#bootScreen');
  if (boot) boot.hidden = true;
}

function authError(message) {
  const box = $('#authError');
  if (!box) return;
  box.hidden = !message;
  box.textContent = message || '';
}

function setAuthMode(mode) {
  authMode = mode;
  const setup = mode === 'setup';
  $('#authScreen').dataset.mode = mode;
  $('#authTitle').textContent = setup ? '创建管理员账号' : '登录';
  $('#authSub').textContent = setup
    ? '首次使用，请先设置管理员账号与密码，之后用它登录管理后台'
    : '请输入账号与密码以进入车库管家';
  $('#authConfirmField').hidden = !setup;
  $('#authNameField').hidden = !setup;
  $('#authRemember').hidden = setup;
  $('#authSubmit').textContent = setup ? '创建并进入' : '登录';
  $('#authFoot').hidden = setup;
  $('#authPass').setAttribute('autocomplete', setup ? 'new-password' : 'current-password');
}

function showLogin(message) {
  State.meta = null;
  State.modalLocked = false;
  $('#modalRoot').innerHTML = '';
  document.body.style.overflow = '';
  $('#app').hidden = true;
  $('#authScreen').hidden = false;
  setAuthMode(State.authCfg && State.authCfg.setup_needed ? 'setup' : 'login');
  authError(message || '');
  const input = $('#authUser');
  if (input) setTimeout(() => input.focus(), 60);
}

async function submitAuth(event) {
  event.preventDefault();
  if (authBusy) return;

  const username = $('#authUser').value.trim();
  const password = $('#authPass').value;
  const setup = authMode === 'setup';
  const minLength = (State.authCfg && State.authCfg.min_password) || 6;

  if (!username || !password) { authError('请输入账号与密码'); return; }
  if (setup) {
    if (password.length < minLength) { authError(`密码至少 ${minLength} 位`); return; }
    if (password !== $('#authConfirm').value) { authError('两次输入的密码不一致'); return; }
  }

  const btn = $('#authSubmit');
  const label = btn.textContent;
  authBusy = true;
  btn.disabled = true;
  btn.textContent = setup ? '创建中…' : '登录中…';
  authError('');

  try {
    const path = setup ? '/api/auth/setup' : '/api/auth/login';
    const body = setup
      ? { username, password, display_name: $('#authName').value.trim() || username }
      : { username, password, remember: $('#authRememberBox').checked };
    const res = await api(path, { method: 'POST', body });
    State.user = res.user;
    State.authCfg = Object.assign({}, State.authCfg, { setup_needed: false, logged_in: true });
    $('#authPass').value = '';
    if ($('#authConfirm')) $('#authConfirm').value = '';
    await startApp();
    if (State.user && State.user.must_change) openPasswordForm(true);
  } catch (err) {
    authError(err.message || '登录失败，请重试');
  } finally {
    authBusy = false;
    btn.disabled = false;
    btn.textContent = label;
  }
}

async function startApp() {
  hideBoot();
  try {
    State.meta = await api('/api/meta');
    State.user = State.meta.user || State.user;
    $('#authScreen').hidden = true;
    $('#app').hidden = false;
    await refreshCore();
  } catch (err) {
    showLogin(err.message || '无法连接服务');
    return;
  }
  State.route = currentRoute();
  renderNav();
  navigate();
}

async function doLogout() {
  try {
    await api('/api/auth/logout', { method: 'POST' });
  } catch (err) {
    /* 忽略：本地状态照常清理 */
  }
  State.user = null;
  showLogin('已退出登录');
  toast('已退出登录');
}

function openPasswordForm(force = false) {
  const name = State.user ? (State.user.display_name || State.user.username) : '';
  openForm({
    title: force ? '请修改初始密码' : '修改密码',
    subtitle: force
      ? '当前账号仍在使用初始密码，为安全起见请设置新密码后继续使用'
      : `当前账号：${name}`,
    lock: force,
    hideCancel: force,
    submitText: force ? '设置新密码' : '保存新密码',
    after: '<div class="hint">新密码至少 6 位，建议包含字母与数字。</div>',
    fields: [
      { name: 'old_password', label: '原密码', type: 'password', required: true, span: 2 },
      { name: 'new_password', label: '新密码', type: 'password', required: true },
      { name: 'confirm_password', label: '确认新密码', type: 'password', required: true },
    ],
    onSubmit: async (v) => {
      if (String(v.new_password).length < 6) throw new Error('新密码至少 6 位');
      if (v.new_password !== v.confirm_password) throw new Error('两次输入的新密码不一致');
      await api('/api/auth/password', {
        method: 'POST',
        body: { old_password: v.old_password, new_password: v.new_password },
      });
      if (State.user) State.user.must_change = 0;
      toast('密码已更新');
    },
  });
}

function openAccountForm() {
  openForm({
    title: '新增账号',
    subtitle: '成员可记录与查看全部车辆数据，管理员额外可管理账号与恢复备份',
    submitText: '创建账号',
    fields: [
      { name: 'username', label: '登录账号', required: true, placeholder: '2-32 位字母、数字、下划线' },
      { name: 'display_name', label: '显示名称', placeholder: '如：林雨' },
      { name: 'password', label: '初始密码', type: 'password', required: true, hint: '至少 6 位，首次登录后会提示修改' },
      { name: 'role', label: '角色', type: 'select', options: [['member', '成员'], ['admin', '管理员']] },
    ],
    values: { role: 'member' },
    onSubmit: async (v) => {
      await api('/api/auth/users', { method: 'POST', body: v });
      toast('账号已创建');
      await refreshAccounts();
      navigate();
    },
  });
}

function openResetPasswordForm(account) {
  openForm({
    title: '重置密码',
    subtitle: `账号：${account.username}`,
    submitText: '重置',
    fields: [
      { name: 'password', label: '新密码', type: 'password', required: true, hint: '至少 6 位，该账号下次登录须修改' },
    ],
    onSubmit: async (v) => {
      await api(`/api/auth/users/${account.id}/password`, { method: 'POST', body: v });
      toast('密码已重置');
    },
  });
}

async function refreshAccounts() {
  if (!State.user || State.user.role !== 'admin') { State.accounts = []; return []; }
  const data = await api('/api/auth/users');
  State.accounts = data.items || [];
  return State.accounts;
}

function accountsTable() {
  const me = State.user ? State.user.id : null;
  const rows = State.accounts.map((a) => {
    const self = a.id === me;
    return `
      <tr>
        <td>
          <div class="acct-name">
            <div class="user-avatar">${esc(String(a.display_name || a.username).slice(0, 1))}</div>
            <div>
              <b>${esc(a.display_name || a.username)}</b>
              <div class="small muted mono">${esc(a.username)}</div>
            </div>
          </div>
        </td>
        <td><span class="badge ${a.role === 'admin' ? 'ok' : 'neutral'}">${a.role === 'admin' ? '管理员' : '成员'}</span></td>
        <td>${a.disabled ? '<span class="badge danger">已停用</span>' : '<span class="badge ok">正常</span>'}</td>
        <td class="small muted">${esc(a.last_login ? String(a.last_login).slice(0, 16).replace('T', ' ') : '从未登录')}</td>
        <td>
          <div class="row-actions">
            <button class="btn sm" data-action="reset-account" data-id="${a.id}">重置密码</button>
            ${self ? '<span class="small muted">当前账号</span>' : `
              <button class="btn sm" data-action="toggle-account" data-id="${a.id}" data-disabled="${a.disabled}">${a.disabled ? '启用' : '停用'}</button>
              <button class="btn sm danger" data-action="del-account" data-id="${a.id}" data-name="${esc(a.username)}">${icon('trash')}</button>`}
          </div>
        </td>
      </tr>`;
  }).join('');

  return `<div class="table-wrap">
    <table class="acct-table">
      <thead><tr><th>账号</th><th>角色</th><th>状态</th><th>最近登录</th><th style="text-align:right">操作</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

/* ================================================================ 图表 */
function niceCeil(v) {
  if (!v || v <= 0) return 1;
  const exp = Math.floor(Math.log10(v));
  const base = Math.pow(10, exp);
  const n = v / base;
  const m = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return m * base;
}

function monthlyChart(rows) {
  const width = 720, height = 210;
  const pad = { t: 12, r: 8, b: 26, l: 46 };
  const innerW = width - pad.l - pad.r;
  const innerH = height - pad.t - pad.b;
  const max = niceCeil(Math.max(1, ...rows.map((r) => r.total)));
  const slot = innerW / Math.max(1, rows.length);
  const barW = Math.min(30, slot * 0.52);

  const grid = [0, 0.25, 0.5, 0.75, 1].map((p) => {
    const y = pad.t + innerH - innerH * p;
    const label = p === 0 ? '0' : nf(max * p, 0);
    return `<line x1="${pad.l}" y1="${y}" x2="${width - pad.r}" y2="${y}" stroke="#eef1f6" stroke-width="1"/>
      <text x="${pad.l - 8}" y="${y + 3.5}" text-anchor="end" font-size="10" fill="#98a2b3">${label}</text>`;
  }).join('');

  const bars = rows.map((r, i) => {
    const x = pad.l + slot * i + (slot - barW) / 2;
    const hTotal = (r.total / max) * innerH;
    const hEnergy = (r.energy / max) * innerH;
    const hService = (r.service / max) * innerH;
    const yTotal = pad.t + innerH - hTotal;
    const showLabel = rows.length <= 8 || i % 2 === 0;
    return `
      <g>
        ${hTotal > 0 ? `<rect x="${x}" y="${yTotal}" width="${barW}" height="${Math.max(hTotal, 1)}" rx="2" fill="#e7edf9"/>` : ''}
        ${hEnergy > 0 ? `<rect x="${x}" y="${pad.t + innerH - hEnergy}" width="${barW}" height="${Math.max(hEnergy, 1)}" rx="2" fill="#1d4ed8" opacity=".85"/>` : ''}
        ${hService > 0 ? `<rect x="${x}" y="${pad.t + innerH - hEnergy - hService}" width="${barW}" height="${Math.max(hService, 1)}" rx="2" fill="#14b8a6" opacity=".9"/>` : ''}
        ${showLabel ? `<text x="${x + barW / 2}" y="${height - 8}" text-anchor="middle" font-size="10" fill="#98a2b3">${esc(r.label)}</text>` : ''}
      </g>`;
  }).join('');

  return `<div class="chart-wrap"><svg viewBox="0 0 ${width} ${height}" role="img">
    ${grid}${bars}
  </svg></div>`;
}

function lineChart(points, unit, emptyText = '') {
  if (!points || !points.length) {
    return `<div class="empty" style="padding:28px 10px">${icon('gauge')}
      <p>${esc(emptyText || '至少需要两条「加满 / 充满」且里程递增的记录，才能计算真实能耗。')}</p></div>`;
  }
  const width = 720, height = 190;
  const pad = { t: 16, r: 12, b: 26, l: 46 };
  const innerW = width - pad.l - pad.r;
  const innerH = height - pad.t - pad.b;
  const values = points.map((p) => Number(p.value));
  let min = Math.min(...values), max = Math.max(...values);
  if (max === min) { max += 1; min = Math.max(0, min - 1); }
  const span = max - min;
  const xOf = (i) => (points.length === 1
    ? pad.l + innerW / 2
    : pad.l + (innerW * i) / (points.length - 1));
  const yOf = (v) => pad.t + innerH - ((v - min) / span) * innerH;

  const coords = points.map((p, i) => [xOf(i), yOf(Number(p.value))]);
  const path = coords.map((c, i) => `${i === 0 ? 'M' : 'L'}${c[0].toFixed(1)},${c[1].toFixed(1)}`).join(' ');
  const area = `${path} L${coords[coords.length - 1][0].toFixed(1)},${pad.t + innerH} L${coords[0][0].toFixed(1)},${pad.t + innerH} Z`;

  const grid = [0, 0.5, 1].map((p) => {
    const y = pad.t + innerH - innerH * p;
    return `<line x1="${pad.l}" y1="${y}" x2="${width - pad.r}" y2="${y}" stroke="#eef1f6"/>
      <text x="${pad.l - 8}" y="${y + 3.5}" text-anchor="end" font-size="10" fill="#98a2b3">${nf(min + span * p, 1)}</text>`;
  }).join('');

  const dots = coords.map((c, i) => `<circle cx="${c[0].toFixed(1)}" cy="${c[1].toFixed(1)}" r="3" fill="#fff" stroke="#1d4ed8" stroke-width="1.8">
    <title>${esc(points[i].date)} · ${nf(points[i].value, 2)} ${esc(unit)}</title></circle>`).join('');

  const xLabels = points.length === 1
    ? `<text x="${(pad.l + innerW / 2).toFixed(1)}" y="${height - 8}" text-anchor="middle" font-size="10" fill="#98a2b3">${esc(fmtDate(points[0].date))}</text>`
    : `<text x="${pad.l}" y="${height - 8}" font-size="10" fill="#98a2b3">${esc(fmtDate(points[0].date))}</text>
    <text x="${width - pad.r}" y="${height - 8}" text-anchor="end" font-size="10" fill="#98a2b3">${esc(fmtDate(points[points.length - 1].date))}</text>`;

  return `<div class="chart-wrap"><svg viewBox="0 0 ${width} ${height}" role="img">
    ${grid}
    <path d="${area}" fill="#1d4ed8" opacity=".06"/>
    <path d="${path}" fill="none" stroke="#1d4ed8" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
    ${dots}
    ${xLabels}
  </svg></div>${points.length === 1
    ? `<div class="small muted" style="padding:2px 4px 0">目前只有 1 个完整区间，再记录一次满${unit.includes('kWh') ? '充' : '箱'}即可连成走势。</div>`
    : ''}`;
}

/* ================================================================ 通用片段 */
function emptyState({ title, text, action = '', iconName = 'car' }) {
  return `<div class="empty">${icon(iconName)}<h4>${esc(title)}</h4><p>${esc(text)}</p>${action}</div>`;
}

function vehicleBadge(vtype) {
  return `<span class="badge ${vtype}">${esc(VTYPE[vtype] || vtype)}</span>`;
}

function reminderRow(r, compact = false, hideAction = false) {
  const left = [];
  if (r.days_left !== null && r.days_left !== undefined) left.push(daysLeftText(r.days_left));
  if (r.km_left !== null && r.km_left !== undefined) left.push(kmLeftText(r.km_left));
  let actions = '';
  if (r.editable) {
    actions = `<div class="row-actions">
        <button class="btn sm" data-action="reminder-done" data-id="${r.id}">标记完成</button>
        <button class="btn sm danger" data-action="reminder-del" data-id="${r.id}">${icon('trash')}</button>
      </div>`;
  } else if (!hideAction) {
    actions = `<button class="btn sm ghost" data-action="goto" data-hash="#/vehicle/${r.vehicle_id}">查看车辆</button>`;
  }
  return `<div class="reminder ${r.level}">
    <span class="dot"></span>
    <div class="rm-main">
      <div class="rm-title">${esc(r.title)} <span class="badge ${levelClass(r.level)}">${levelLabel(r.level)}</span>
        ${compact ? '' : `<span class="muted small">${esc(r.vehicle_name)}${r.plate ? ' · ' + esc(r.plate) : ''}</span>`}</div>
      <div class="rm-sub">${r.due_date ? '到期日 ' + esc(r.due_date) : ''}${r.due_odometer ? (r.due_date ? ' · ' : '') + '到期里程 ' + nf(r.due_odometer) + ' km' : ''}${r.note ? ' · ' + esc(r.note) : ''}</div>
    </div>
    <div class="rm-left">${left.map((t) => `<div><b>${esc(t)}</b></div>`).join('') || '<span class="muted">—</span>'}</div>
    ${actions}
  </div>`;
}

/* ================================================================ 路由 */
async function navigate() {
  const route = currentRoute();
  State.route = route;
  renderNav();
  window.scrollTo(0, 0);
  const view = $('#view');
  if (!State.vehicles.length && route.name !== 'vehicles' && route.name !== 'data') {
    // 首次使用引导（除车辆页与数据页）
    if (route.name === 'overview') {
      await renderOverview();
      return;
    }
  }
  view.innerHTML = '<div class="skeleton"></div><div class="skeleton" style="height:150px"></div>';
  try {
    if (route.name === 'overview') await renderOverview();
    else if (route.name === 'vehicles') await renderVehicles();
    else if (route.name === 'vehicle') await renderVehicleDetail(route.id);
    else if (route.name === 'energy') await renderEnergy();
    else if (route.name === 'service') await renderService();
    else if (route.name === 'reminders') await renderReminders();
    else if (route.name === 'ai') await renderAI();
    else if (route.name === 'data') await renderData();
    else if (route.name === 'settings') await renderSettings();
    else await renderOverview();
  } catch (err) {
    view.innerHTML = `<div class="card"><div class="card-body">${emptyState({
      title: '页面加载失败', text: err.message || '未知错误', iconName: 'x',
      action: '<button class="btn" data-action="reload">重新加载</button>',
    })}</div></div>`;
  }
}

/* ================================================================ 总览 */
async function renderOverview() {
  const d = await api('/api/overview');
  State.overview = d;
  State.reminderCount = d.reminder_count || 0;
  renderNav();
  pageHead('总览', `今日 ${todayIsoText()} · 全部数据保存在你自己的 NAS 上`,
    `<button class="btn" data-action="add-energy">${icon('bolt')}记录能耗</button>
     <button class="btn primary" data-action="add-service">${icon('wrench')}记录保养</button>`);

  if (!d.vehicle_count) {
    $('#view').innerHTML = `<div class="card"><div class="card-body">
      ${emptyState({
        title: '还没有车辆档案', iconName: 'car',
        text: '先建立车辆档案，之后加油、充电、保养的记录与提醒都会自动挂到对应车辆上。',
        action: `<button class="btn primary" data-action="add-vehicle">新增车辆</button>`,
      })}
    </div></div>`;
    return;
  }

  const next = d.next_reminder;
  const nextHtml = next ? `
    <div class="next-card">
      <div class="next-title">${icon('bell')} ${esc(next.title)}
        <span class="badge ${levelClass(next.level)}">${levelLabel(next.level)}</span></div>
      <div class="next-meta">
        <span>${esc(next.vehicle_name)}${next.plate ? ' · ' + esc(next.plate) : ''}</span>
        ${next.days_left !== null ? `<span>${daysLeftText(next.days_left)}</span>` : ''}
        ${next.km_left !== null ? `<span>${kmLeftText(next.km_left)}</span>` : ''}
      </div>
      <div class="next-note">${next.due_date ? '到期日 ' + esc(next.due_date) : ''}${next.due_odometer ? ' · 到期里程 ' + nf(next.due_odometer) + ' km' : ''}</div>
    </div>` : `
    <div class="next-card">
      <div class="next-title">${icon('check')} 暂无待办提醒</div>
      <div class="next-note">在车辆档案中填写保险、年检日期，或为保养设置下次周期，系统会按日期与里程双条件提醒。</div>
    </div>`;

  const vehicleRows = d.vehicles.map((s) => {
    const v = s.vehicle;
    return `<div class="vehicle-card" style="padding:14px">
      <div class="vc-head">
        <div class="vc-title"><strong>${esc(v.name)}</strong><span class="plate">${esc(v.plate || '未填车牌')}</span></div>
        <div style="margin-left:auto">${vehicleBadge(v.vtype)}</div>
      </div>
      <div class="vc-metrics">
        <div><span>当前里程</span><b>${nf(s.current_odometer)}<small class="muted" style="font-size:11px;font-weight:400"> km</small></b></div>
        <div><span>平均能耗</span><b style="font-size:12.5px">${consumptionText(s, v.vtype)}</b></div>
        <div><span>本月支出</span><b>${money(s.month_cost)}</b></div>
      </div>
      <div class="vc-foot">
        <span>累计 ${money(s.total_cost)}</span>
        <a href="#/vehicle/${v.id}" style="margin-left:auto;font-size:12px">车辆详情 ${icon('arrow')}</a>
      </div>
    </div>`;
  }).join('');

  const recent = d.recent.length ? `
    <table class="data">
      <thead><tr><th>日期</th><th>车辆</th><th>事项</th><th>里程</th><th class="num">金额</th></tr></thead>
      <tbody>${d.recent.map((r) => `<tr>
        <td class="mono nowrap">${esc(fmtDate(r.date))}</td>
        <td>${esc(r.vehicle_name)}</td>
        <td><span class="badge ${r.record_type === 'energy' ? 'neutral' : 'phev'}">${esc(r.title)}</span> <span class="muted small">${esc(r.detail || '')}</span></td>
        <td class="mono">${r.odometer ? nf(r.odometer) + ' km' : '—'}</td>
        <td class="num">${money(r.cost)}</td>
      </tr>`).join('')}</tbody>
    </table>` : emptyState({ title: '暂无记录', text: '从右上角「记录能耗」开始，或用智能录入一次性补齐历史。' });

  $('#view').innerHTML = `
    <div class="hero">
      <div class="hero-main">
        <div class="hero-label">本月养车支出</div>
        <div class="hero-value">${money(d.month_cost)}<small>共 ${d.vehicle_count} 台车</small></div>
        <div class="hero-meta">
          <span>累计支出 <b>${money(d.total_cost)}</b></span>
          <span>累计里程 <b>${nf(d.total_distance)} km</b></span>
          <span>能耗占 <b>${d.total_cost ? Math.round((d.energy_cost / d.total_cost) * 100) : 0}%</b></span>
        </div>
      </div>
      <div class="hero-side">${nextHtml}
        ${d.reminder_count ? `<div class="small muted">${d.reminder_count} 项提醒需要关注 · <a href="#/reminders">全部提醒</a></div>` : ''}
      </div>
    </div>

    <div class="stat-grid">
      <div class="stat"><div class="label">${icon('car')} 在册车辆</div><div class="value">${d.vehicle_count}<small>台</small></div><div class="foot">含燃油 / 纯电 / 插混</div></div>
      <div class="stat"><div class="label">${icon('gauge')} 累计里程</div><div class="value">${nf(d.total_distance)}<small>km</small></div><div class="foot">自建档以来累计</div></div>
      <div class="stat"><div class="label">${icon('bolt')} 平均油耗</div><div class="value">${d.consumption.fuel === null
        ? '—' : nf(d.consumption.fuel, 2) + '<small>L/100km</small>'}</div><div class="foot">${d.consumption.fuel === null
        ? '暂无满箱区间，需连续两次加满' : '满箱到满箱实测'}</div></div>
      <div class="stat"><div class="label">${icon('bolt')} 平均电耗</div><div class="value">${d.consumption.charge === null
        ? '—' : nf(d.consumption.charge, 2) + '<small>kWh/100km</small>'}</div><div class="foot">${d.consumption.charge === null
        ? '暂无满充区间，需连续两次充满' : '满充到满充实测'}</div></div>
    </div>

    <div class="grid-2">
      <section class="card">
        <div class="card-head"><h3>月度支出</h3><span class="sub">近 12 个月</span>
          <div class="spacer"></div>
          <div class="chart-legend"><span><i style="background:#1d4ed8"></i>能耗</span><span><i style="background:#14b8a6"></i>保养维修</span></div>
        </div>
        <div class="card-body">${monthlyChart(d.monthly)}</div>
      </section>
      <section class="card">
        <div class="card-head"><h3>我的车库</h3><span class="sub">${d.vehicle_count} 台</span>
          <div class="spacer"></div><a href="#/vehicles" class="small">管理 ${icon('arrow')}</a></div>
        <div class="card-body" style="display:flex;flex-direction:column;gap:10px">${vehicleRows}</div>
      </section>
    </div>

    <section class="card">
      <div class="card-head"><h3>最近记录</h3><span class="sub">最新 10 条</span>
        <div class="spacer"></div><a href="#/energy" class="small">能耗记录 · </a><a href="#/service" class="small">保养维修</a></div>
      <div class="table-wrap">${recent}</div>
    </section>`;
}

function todayIsoText() {
  const d = new Date();
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`;
}

/* ================================================================ 车辆列表 */
async function renderVehicles() {
  pageHead('车辆档案', `${State.vehicles.length} 台车 · 档案、容量与证照信息统一管理`,
    `<button class="btn primary" data-action="add-vehicle">${icon('plus')}新增车辆</button>`);

  if (!State.vehicles.length) {
    $('#view').innerHTML = `<div class="card"><div class="card-body">
      ${emptyState({
        title: '建立第一台车', iconName: 'car',
        text: '动力类型决定可记录的能耗种类：纯电记录充电，燃油记录加油，插混两者皆可。',
        action: `<button class="btn primary" data-action="add-vehicle">新增车辆</button>`,
      })}
    </div></div>`;
    return;
  }

  const cards = State.vehicles.map((v) => {
    const s = v.summary || {};
    return `<div class="vehicle-card">
      <div class="vc-head">
        <div class="vc-title">
          <strong>${esc(v.name)}</strong>
          <span class="plate">${esc(v.plate || '未填车牌')}</span>
        </div>
        <div style="margin-left:auto;display:flex;gap:4px;align-items:center">
          ${vehicleBadge(v.vtype)}
        </div>
      </div>
      <div class="vc-metrics">
        <div><span>当前里程</span><b>${nf(s.current_odometer)}<small class="muted" style="font-size:11px;font-weight:400"> km</small></b></div>
        <div><span>累计支出</span><b>${money(s.total_cost)}</b></div>
        <div><span>每公里成本</span><b>${s.cost_per_km === null || s.cost_per_km === undefined ? '—' : money(s.cost_per_km, 3)}</b></div>
      </div>
      <div class="small muted" style="display:flex;gap:12px;flex-wrap:wrap;border-top:1px dashed var(--line);padding-top:10px">
        <span>保险 ${esc(v.insurance_due || '—')}</span>
        <span>年检 ${esc(v.inspect_due || '—')}</span>
        <span>车船税 ${esc(v.tax_due || '—')}</span>
      </div>
      <div class="vc-foot" style="flex-wrap:wrap;gap:6px">
        <span>${consumptionText(s, v.vtype)}</span>
        <span>· ${s.record_count || 0} 条记录</span>
        <span style="margin-left:auto;display:flex;gap:4px">
          <button class="btn sm" data-action="edit-vehicle" data-id="${v.id}">${icon('edit')}编辑</button>
          <a class="btn sm" href="#/vehicle/${v.id}">详情</a>
        </span>
      </div>
    </div>`;
  }).join('');

  $('#view').innerHTML = `<div class="grid-3">${cards}</div>
    <div class="hint-box">提示：在车辆档案中填写保险到期、年检到期、车船税日期后，系统会把它们并入提醒引擎，与保养的「日期 + 里程」双条件一起计算。</div>`;
}

/* ================================================================ 车辆详情 */
async function renderVehicleDetail(id) {
  if (!id) { location.hash = '#/vehicles'; return; }
  const data = await api(`/api/vehicles/${id}`);
  const [en, se] = await Promise.all([
    api(`/api/energy?vehicle_id=${id}&limit=500`),
    api(`/api/service?vehicle_id=${id}&limit=500`),
  ]);
  const v = data.vehicle, s = data.summary;
  State.detail = { v, s, energy: en.items, service: se.items, reminders: data.reminders };
  State.energyItems = en.items;
  State.serviceItems = se.items;

  pageHead(v.name, `${v.plate || '未填车牌'} · ${VTYPE[v.vtype] || v.vtype} · ${s.record_count} 条记录`,
    `<button class="btn" data-action="add-energy" data-vid="${v.id}">${icon('bolt')}记录能耗</button>
     <button class="btn" data-action="add-service" data-vid="${v.id}">${icon('wrench')}记录保养</button>
     <button class="btn" data-action="edit-vehicle" data-id="${v.id}">${icon('edit')}编辑</button>
     <button class="icon-btn" data-action="del-vehicle" data-id="${v.id}" title="删除车辆">${icon('trash')}</button>`);

  const isEv = v.vtype === 'ev';
  const consPoints = isEv || (v.vtype === 'phev' && !s.fuel_points.length) ? s.charge_points : s.fuel_points;
  const consUnit = isEv ? 'kWh/100km' : 'L/100km';

  const info = [
    ['品牌车型', [v.brand, v.model].filter(Boolean).join(' ') || '—'],
    ['年款 / 颜色', [v.year ? v.year + ' 款' : '', v.color].filter(Boolean).join(' · ') || '—'],
    ['车架号', v.vin ? `<span class="mono">${esc(v.vin)}</span>` : '—'],
    ['购置日期', v.register_date || '—'],
    [v.vtype === 'ev' ? '电池容量' : '油箱容积', v.vtype === 'ev'
      ? (v.battery_capacity ? `${nf(v.battery_capacity, 1)} kWh` : '—')
      : (v.tank_capacity ? `${nf(v.tank_capacity, 1)} L` : '—')],
    ['轮胎规格', v.tire_spec || '—'],
    ['保险公司', v.insurer || '—'],
    ['保单号', v.policy_no ? `<span class="mono">${esc(v.policy_no)}</span>` : '—'],
    ['保险到期', v.insurance_due || '—'],
    ['年检到期', v.inspect_due || '—'],
    ['车船税', v.tax_due || '—'],
    ['备注', v.note ? esc(v.note) : '—'],
  ].map(([k, val]) => `<dt>${esc(k)}</dt><dd>${val}</dd>`).join('');

  const reminders = data.reminders.length
    ? data.reminders.map((r) => reminderRow(r, true, true)).join('')
    : `<div class="empty" style="padding:26px 10px">${icon('check')}<p>没有待办提醒。填写证照日期或为保养设置下次周期即可自动生成。</p></div>`;

  const merged = [
    ...en.items.map((r) => Object.assign({}, r, { _type: 'energy' })),
    ...se.items.map((r) => Object.assign({}, r, { _type: 'service' })),
  ].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : b.id - a.id));

  const tab = State.detailTab;
  const rows = merged.filter((r) => tab === 'all' || r._type === tab);
  const tableHtml = rows.length ? `<div class="table-wrap"><table class="data">
    <thead><tr><th>日期</th><th>类型</th><th>项目 / 站点</th><th class="num">里程</th><th class="num">数量</th><th class="num">金额</th><th></th></tr></thead>
    <tbody>${rows.map((r) => r._type === 'energy' ? `<tr>
      <td class="mono nowrap">${esc(fmtDate(r.date))}</td>
      <td><span class="badge ${r.kind === 'charge' ? 'ev' : 'ice'}">${KIND[r.kind] || r.kind}</span></td>
      <td>${esc(r.station || '—')}${r.note ? `<div class="small muted">${esc(r.note)}</div>` : ''}</td>
      <td class="mono">${r.odometer ? nf(r.odometer) + ' km' : '—'}</td>
      <td class="num">${qty(r.quantity, r.kind === 'charge' ? 'kWh' : 'L')}</td>
      <td class="num">${money(r.cost)}</td>
      <td><div class="row-actions">
        <button class="btn sm ghost" data-action="edit-energy" data-id="${r.id}">${icon('edit')}</button>
        <button class="btn sm ghost" data-action="del-energy" data-id="${r.id}">${icon('trash')}</button>
      </div></td></tr>` : `<tr>
      <td class="mono nowrap">${esc(fmtDate(r.date))}</td>
      <td><span class="badge ${r.rtype === 'repair' ? 'warn' : r.rtype === 'expense' ? 'neutral' : 'phev'}">${RTYPE[r.rtype] || r.rtype}</span></td>
      <td>${esc(r.items)}${r.shop ? `<div class="small muted">${esc(r.shop)}</div>` : ''}</td>
      <td class="mono">${r.odometer ? nf(r.odometer) + ' km' : '—'}</td>
      <td class="num">—</td>
      <td class="num">${money(r.cost)}</td>
      <td><div class="row-actions">
        <button class="btn sm ghost" data-action="edit-service" data-id="${r.id}">${icon('edit')}</button>
        <button class="btn sm ghost" data-action="del-service" data-id="${r.id}">${icon('trash')}</button>
      </div></td></tr>`).join('')}</tbody></table></div>`
    : emptyState({ title: '暂无记录', text: '点击右上角按钮添加第一条能耗或保养记录。' });

  $('#view').innerHTML = `
    <div class="hero">
      <div class="hero-main">
        <div class="hero-label">当前里程</div>
        <div class="hero-value">${nf(s.current_odometer)}<small>km</small></div>
        <div class="hero-meta">
          <span>建档后行驶 <b>${nf(s.total_distance)} km</b></span>
          <span>累计支出 <b>${money(s.total_cost)}</b></span>
          <span>每公里 <b>${s.cost_per_km === null ? '—' : money(s.cost_per_km, 3)}</b></span>
        </div>
      </div>
      <div class="hero-side">
        <div class="next-card">
          <div class="next-title">${icon('bolt')} ${isEv ? '平均电耗' : '平均油耗'}
            <span class="badge neutral">${esc(consUnit)}</span></div>
          <div class="hero-value" style="font-size:28px">${isEv
            ? (s.charge_consumption === null ? '—' : nf(s.charge_consumption, 2))
            : (s.fuel_consumption === null ? '—' : nf(s.fuel_consumption, 2))}</div>
          <div class="next-note">按满${isEv ? '充' : '箱'}区间实测${isEv ? ` · 累计充电 ${nf(s.charge_total_kwh, 1)} kWh` : ` · 累计加油 ${nf(s.fuel_total_l, 1)} L`}</div>
        </div>
      </div>
    </div>

    <div class="grid-2">
      <section class="card">
        <div class="card-head"><h3>车辆档案</h3><span class="sub">手套箱</span></div>
        <div class="card-body"><dl class="kv">${info}</dl></div>
      </section>
      <section class="card">
        <div class="card-head"><h3>提醒</h3><span class="sub">日期 + 里程双条件</span>
          <div class="spacer"></div>
          <button class="btn sm" data-action="add-reminder" data-vid="${v.id}">${icon('plus')}自定义</button></div>
        <div class="card-body flush">${reminders}</div>
      </section>
    </div>

    <div class="grid-2">
      <section class="card">
        <div class="card-head"><h3>${isEv ? '电耗' : '油耗'}走势</h3><span class="sub">${esc(consUnit)}</span></div>
        <div class="card-body">${lineChart(consPoints, consUnit,
          `还没有可计算的区间：先记录一次满${isEv ? '充' : '箱'}作为起点，之后再次满${isEv ? '充' : '箱'}且里程递增，即可算出${isEv ? '电耗' : '油耗'}。`)}</div>
      </section>
      <section class="card">
        <div class="card-head"><h3>月度支出</h3><span class="sub">近 12 个月</span>
          <div class="spacer"></div>
          <div class="chart-legend"><span><i style="background:#1d4ed8"></i>能耗</span><span><i style="background:#14b8a6"></i>保养</span></div>
        </div>
        <div class="card-body">${monthlyChart(s.monthly)}</div>
      </section>
    </div>

    <section class="card">
      <div class="tabs">
        <button data-action="detail-tab" data-tab="all" class="${tab === 'all' ? 'active' : ''}">全部 ${merged.length}</button>
        <button data-action="detail-tab" data-tab="energy" class="${tab === 'energy' ? 'active' : ''}">能耗 ${en.items.length}</button>
        <button data-action="detail-tab" data-tab="service" class="${tab === 'service' ? 'active' : ''}">保养维修 ${se.items.length}</button>
      </div>
      ${tableHtml}
    </section>`;
}

/* ================================================================ 能耗记录 */
async function renderEnergy() {
  pageHead('能耗记录', '加油与充电明细，真实油耗/电耗由满箱（满充）区间自动计算',
    `<button class="btn primary" data-action="add-energy">${icon('plus')}新增记录</button>`);

  const f = State.energyFilter;
  const qs = new URLSearchParams();
  if (f.vehicle_id) qs.set('vehicle_id', f.vehicle_id);
  if (f.kind) qs.set('kind', f.kind);
  if (f.from) qs.set('from', f.from);
  if (f.to) qs.set('to', f.to);
  const data = await api(`/api/energy?${qs.toString()}`);
  State.energyItems = data.items;

  const vehicleOptions = State.vehicles.map((v) => `<option value="${v.id}" ${String(f.vehicle_id) === String(v.id) ? 'selected' : ''}>${esc(v.name)}</option>`).join('');

  const rows = data.items.map((r) => `<tr>
    <td class="mono nowrap">${esc(fmtDate(r.date))}</td>
    <td>${esc(r.vehicle_name)} <span class="badge ${r.kind === 'charge' ? 'ev' : 'ice'}">${KIND[r.kind] || r.kind}</span></td>
    <td class="mono">${r.odometer ? nf(r.odometer) + ' km' : '—'}</td>
    <td class="num">${qty(r.quantity, r.kind === 'charge' ? 'kWh' : 'L')}</td>
    <td class="num">${r.unit_price ? money(r.unit_price, 3) : '—'}</td>
    <td class="num">${money(r.cost)}</td>
    <td>${esc(r.station || '—')}</td>
    <td class="small muted">${esc(r.note || '')}${r.kind === 'charge' && r.soc_start !== null ? ` ${nf(r.soc_start, 0)}%→${nf(r.soc_end, 0)}%` : ''}</td>
    <td><div class="row-actions">
      <button class="btn sm ghost" data-action="edit-energy" data-id="${r.id}">${icon('edit')}</button>
      <button class="btn sm ghost" data-action="del-energy" data-id="${r.id}">${icon('trash')}</button>
    </div></td>
  </tr>`).join('');

  $('#view').innerHTML = `
    <section class="card">
      <div class="card-body">
        <div class="toolbar">
          <div class="field" style="width:150px"><label>车辆</label>
            <select id="energyVehicle"><option value="">全部车辆</option>${vehicleOptions}</select></div>
          <div class="field" style="width:120px"><label>类型</label>
            <select id="energyKind">
              <option value="">全部</option>
              <option value="fuel" ${f.kind === 'fuel' ? 'selected' : ''}>加油</option>
              <option value="charge" ${f.kind === 'charge' ? 'selected' : ''}>充电</option>
            </select></div>
          <div class="field" style="width:150px"><label>起始日期</label><input type="date" id="energyFrom" value="${esc(f.from)}"></div>
          <div class="field" style="width:150px"><label>截止日期</label><input type="date" id="energyTo" value="${esc(f.to)}"></div>
          <button class="btn ghost" data-action="reset-energy-filter" style="margin-top:20px">${icon('refresh')}重置</button>
          <div class="spacer"></div>
          <div class="chip-row" style="margin-top:20px">
            <span class="badge neutral">${data.totals.count} 条</span>
            <span class="badge neutral">合计 ${nf(data.totals.quantity, 1)}</span>
            <span class="badge neutral">${money(data.totals.cost)}</span>
          </div>
        </div>
      </div>
    </section>
    <section class="card">
      ${data.items.length ? `<div class="table-wrap"><table class="data">
        <thead><tr><th>日期</th><th>车辆 / 类型</th><th class="num">里程</th><th class="num">数量</th><th class="num">单价</th><th class="num">金额</th><th>站点</th><th>备注</th><th></th></tr></thead>
        <tbody>${rows}</tbody></table></div>`
      : emptyState({
        title: '没有符合条件的能耗记录', iconName: 'bolt',
        text: '调整筛选条件，或直接新增一条加油 / 充电记录。',
        action: '<button class="btn primary" data-action="add-energy">新增记录</button>',
      })}
    </section>`;

  $('#energyVehicle').addEventListener('change', (e) => { f.vehicle_id = e.target.value; renderEnergy(); });
  $('#energyKind').addEventListener('change', (e) => { f.kind = e.target.value; renderEnergy(); });
  $('#energyFrom').addEventListener('change', (e) => { f.from = e.target.value; renderEnergy(); });
  $('#energyTo').addEventListener('change', (e) => { f.to = e.target.value; renderEnergy(); });
}

/* ================================================================ 保养维修 */
async function renderService() {
  pageHead('保养维修', '保养、维修与其他用车开销，含门店与下次保养周期',
    `<button class="btn primary" data-action="add-service">${icon('plus')}新增记录</button>`);

  const f = State.serviceFilter;
  const qs = new URLSearchParams();
  if (f.vehicle_id) qs.set('vehicle_id', f.vehicle_id);
  if (f.rtype) qs.set('rtype', f.rtype);
  if (f.from) qs.set('from', f.from);
  if (f.to) qs.set('to', f.to);
  const data = await api(`/api/service?${qs.toString()}`);
  State.serviceItems = data.items;

  const vehicleOptions = State.vehicles.map((v) => `<option value="${v.id}" ${String(f.vehicle_id) === String(v.id) ? 'selected' : ''}>${esc(v.name)}</option>`).join('');

  const rows = data.items.map((r) => `<tr>
    <td class="mono nowrap">${esc(fmtDate(r.date))}</td>
    <td>${esc(r.vehicle_name)} <span class="badge ${r.rtype === 'repair' ? 'warn' : r.rtype === 'expense' ? 'neutral' : 'phev'}">${RTYPE[r.rtype] || r.rtype}</span></td>
    <td class="mono">${r.odometer ? nf(r.odometer) + ' km' : '—'}</td>
    <td>${esc(r.items)}${r.note ? `<div class="small muted">${esc(r.note)}</div>` : ''}</td>
    <td>${esc(r.shop || '—')}</td>
    <td class="num">${money(r.cost)}</td>
    <td class="small muted">${r.next_date || r.next_odometer ? `${esc(r.next_date || '')}${r.next_odometer ? ' / ' + nf(r.next_odometer) + ' km' : ''}` : '—'}</td>
    <td><div class="row-actions">
      <button class="btn sm ghost" data-action="edit-service" data-id="${r.id}">${icon('edit')}</button>
      <button class="btn sm ghost" data-action="del-service" data-id="${r.id}">${icon('trash')}</button>
    </div></td>
  </tr>`).join('');

  $('#view').innerHTML = `
    <section class="card">
      <div class="card-body">
        <div class="toolbar">
          <div class="field" style="width:150px"><label>车辆</label>
            <select id="serviceVehicle"><option value="">全部车辆</option>${vehicleOptions}</select></div>
          <div class="field" style="width:130px"><label>类型</label>
            <select id="serviceRtype">
              <option value="">全部</option>
              <option value="maintenance" ${f.rtype === 'maintenance' ? 'selected' : ''}>保养</option>
              <option value="repair" ${f.rtype === 'repair' ? 'selected' : ''}>维修</option>
              <option value="expense" ${f.rtype === 'expense' ? 'selected' : ''}>其他开销</option>
            </select></div>
          <div class="field" style="width:150px"><label>起始日期</label><input type="date" id="serviceFrom" value="${esc(f.from)}"></div>
          <div class="field" style="width:150px"><label>截止日期</label><input type="date" id="serviceTo" value="${esc(f.to)}"></div>
          <button class="btn ghost" data-action="reset-service-filter" style="margin-top:20px">${icon('refresh')}重置</button>
          <div class="spacer"></div>
          <div class="chip-row" style="margin-top:20px">
            <span class="badge neutral">${data.totals.count} 条</span>
            <span class="badge neutral">${money(data.totals.cost)}</span>
          </div>
        </div>
      </div>
    </section>
    <section class="card">
      ${data.items.length ? `<div class="table-wrap"><table class="data">
        <thead><tr><th>日期</th><th>车辆 / 类型</th><th class="num">里程</th><th>项目</th><th>门店</th><th class="num">金额</th><th>下次保养</th><th></th></tr></thead>
        <tbody>${rows}</tbody></table></div>`
      : emptyState({
        title: '没有符合条件的保养记录', iconName: 'wrench',
        text: '保养记录支持填写下次保养日期与里程，保存后会自动进入提醒引擎。',
        action: '<button class="btn primary" data-action="add-service">新增记录</button>',
      })}
    </section>`;

  $('#serviceVehicle').addEventListener('change', (e) => { f.vehicle_id = e.target.value; renderService(); });
  $('#serviceRtype').addEventListener('change', (e) => { f.rtype = e.target.value; renderService(); });
  $('#serviceFrom').addEventListener('change', (e) => { f.from = e.target.value; renderService(); });
  $('#serviceTo').addEventListener('change', (e) => { f.to = e.target.value; renderService(); });
}

/* ================================================================ 提醒 */
async function renderReminders() {
  const data = await api('/api/reminders');
  State.reminders = data.items;
  State.reminderCount = data.items.filter((x) => x.level !== 'ok').length;
  renderNav();

  pageHead('提醒', '保养按「日期 + 里程」双条件，先到者优先',
    `<button class="btn primary" data-action="add-reminder">${icon('plus')}新增提醒</button>`);

  const groups = [
    ['overdue', '已逾期'],
    ['soon', '即将到期（30 天内 / 1000 km 内）'],
    ['ok', '计划中'],
  ];

  const body = data.items.length ? groups.map(([level, title]) => {
    const items = data.items.filter((r) => r.level === level);
    if (!items.length) return '';
    return `<section class="card">
      <div class="card-head"><h3>${title}</h3><span class="sub">${items.length} 项</span></div>
      <div class="card-body flush">${items.map((r) => reminderRow(r)).join('')}</div>
    </section>`;
  }).join('') : `<div class="card"><div class="card-body">${emptyState({
    title: '暂无提醒', iconName: 'bell',
    text: '填写车辆保险/年检日期，或在保养记录中设定下次保养周期，提醒会自动出现在这里。',
  })}</div></div>`;

  $('#view').innerHTML = body + `<div class="hint-box">
    提醒规则：日期剩余 ≤ 30 天、里程剩余 ≤ 1000 km 视为「即将到期」；任一条件为负即「已逾期」。
    自定义提醒可标记完成或删除；法定日期与保养周期类的提醒请修改对应车辆/记录。
  </div>`;
}

/* ================================================================ 智能录入 */
async function renderAI() {
  pageHead('智能录入', '用一句话记录，由 Hermes 解析为结构化数据',
    `<a class="btn" href="#/settings">${icon('settings')}Hermes 配置</a>`);

  const defVid = String(State.settings.default_vehicle_id || '');
  const vehicleOptions = `<option value="">自动识别（按车牌 / 名称）</option>` + State.vehicles.map((v) =>
    `<option value="${v.id}" ${String(v.id) === defVid ? 'selected' : ''}>${esc(v.name)}${v.plate ? ' · ' + esc(v.plate) : ''}</option>`).join('');
  const examples = [
    '昨天在壳牌加满 45 升 95 号，里程 45230，一共花了 342 元',
    '今天充电 42 度，从 20% 充到 90%，花了 60 元，里程 32100',
    '在 4S 店做保养，换了机油机滤，里程 46000，花了 680，一万公里后再来',
    '前天补胎花了 80，里程 46500，门店是路边修车铺',
  ];

  $('#view').innerHTML = `
    <div class="ai-layout">
      <div style="display:flex;flex-direction:column;gap:16px">
        <section class="card">
          <div class="card-head"><h3>输入记录</h3><span class="sub">支持一次输入多条，换行分隔</span></div>
          <div class="card-body" style="display:flex;flex-direction:column;gap:12px">
            <div class="field ai-textarea">
              <textarea id="aiText" placeholder="例如：昨天在壳牌加满 45 升，里程 45230，花了 342 元；今天去 4S 店保养，换了机油机滤，里程 46000，花了 680">${esc(State.ai && State.ai.text ? State.ai.text : '')}</textarea>
            </div>
            <div class="ai-examples">${examples.map((t) => `<button class="ai-example" data-action="ai-example" data-text="${esc(t)}">${esc(t.length > 26 ? t.slice(0, 26) + '…' : t)}</button>`).join('')}</div>
            <div class="toolbar" style="align-items:flex-end">
              <div class="field" style="width:210px"><label>默认车辆</label>
                <select id="aiVehicle">${vehicleOptions}</select></div>
              <div class="spacer"></div>
              <button class="btn ghost" data-action="ai-reset">清空</button>
              <button class="btn primary" id="aiParseBtn" data-action="ai-parse">${icon('sparkles')}解析</button>
            </div>
          </div>
        </section>
        <div id="aiResult">${State.ai ? '' : `<div class="hint-box">
          解析流程：输入自然语言 → Hermes 输出结构化 JSON → 你在下方核对并可直接修改 → 确认后写入数据库。
          若 Hermes 未配置或不可用，系统会自动降级为本地规则引擎，并在结果上方标注来源。
        </div>`}</div>
      </div>
      <aside style="display:flex;flex-direction:column;gap:16px">
        <section class="card">
          <div class="card-head"><h3>识别字段</h3></div>
          <div class="card-body small muted" style="line-height:1.9">
            <b>能耗：</b>日期、里程、加油量/充电量、单价、金额、站点、是否加满、续航增加、起止电量<br>
            <b>保养维修：</b>日期、里程、项目、金额、门店、备注、下次保养日期与里程<br>
            <b>车辆：</b>可按车牌或名称识别，未指定时使用左侧默认车辆
          </div>
        </section>
        <section class="card">
          <div class="card-head"><h3>当前解析引擎</h3></div>
          <div class="card-body small">
            <div class="kv" style="grid-template-columns:78px 1fr">
              <dt>状态</dt><dd>${State.settings.ai_enabled === '1' ? '<span class="badge ok">已启用</span>' : '<span class="badge warning">已停用</span>'}</dd>
              <dt>模型</dt><dd class="mono">${esc(State.settings.ai_model || '—')}</dd>
              <dt>地址</dt><dd class="mono" style="word-break:break-all;font-size:12px">${esc(State.settings.ai_base_url || '—')}</dd>
            </div>
          </div>
        </section>
      </aside>
    </div>`;

  if (State.ai) renderAIResult();
}

function renderAIResult() {
  const box = $('#aiResult');
  if (!box) return;
  const res = State.ai;
  if (!res) { box.innerHTML = ''; return; }
  const sourceLabel = res.source === 'hermes'
    ? `<span class="source-tag">${icon('sparkles')} 解析来源 <b>Hermes · ${esc(res.model || '')}</b></span>`
    : `<span class="source-tag">${icon('shield')} 解析来源 <b>本地规则引擎</b>（Hermes 不可用）</span>`;

  const items = res.items || [];
  const validCount = items.filter((i) => i.valid !== false).length;
  const cards = items.map((item, idx) => aiItemCard(item, idx)).join('');

  box.innerHTML = `<section class="card">
    <div class="card-head">
      <h3>解析结果</h3>
      <span class="sub">${items.length} 条 · 可保存 ${validCount} 条</span>
      <div class="spacer"></div>${sourceLabel}
    </div>
    <div class="card-body" style="display:flex;flex-direction:column;gap:12px">
      ${res.fallback_reason ? `<div class="ai-warn">${esc(res.fallback_reason)}</div>` : ''}
      ${cards || emptyState({ title: '未识别到记录', text: '请补充日期、里程、金额或「加油 / 充电 / 保养」等关键词。', iconName: 'sparkles' })}
    </div>
    <div class="modal-foot" style="border-radius:0 0 12px 12px">
      <span class="left small muted">保存后可在对应车辆与记录列表中编辑</span>
      <button class="btn" data-action="ai-reset">放弃</button>
      <button class="btn primary" data-action="ai-save" ${validCount ? '' : 'disabled'}>${icon('check')}保存 ${validCount} 条记录</button>
    </div>
  </section>`;
}

function aiItemCard(item, idx) {
  const isEnergy = item.record_type === 'energy';
  const vehicleOptions = State.vehicles.map((v) => `<option value="${v.id}" ${v.id === item.vehicle_id ? 'selected' : ''}>${esc(v.name)}</option>`).join('');
  const v = State.vehicles.find((x) => x.id === item.vehicle_id);
  const warnings = (item.warnings || []).map((w) => `<div class="ai-warn">${esc(w)}</div>`).join('');

  const fields = [
    `<div class="field"><label>车辆</label><select data-idx="${idx}" data-field="vehicle_id">${vehicleOptions}</select></div>`,
    `<div class="field"><label>日期</label><input type="date" data-idx="${idx}" data-field="date" value="${esc(item.date || '')}"></div>`,
    `<div class="field"><label>里程 (km)</label><input type="number" step="any" data-idx="${idx}" data-field="odometer" value="${item.odometer === null ? '' : item.odometer}"></div>`,
  ];

  if (isEnergy) {
    fields.push(`<div class="field"><label>类型</label><select data-idx="${idx}" data-field="kind">
      <option value="fuel" ${item.kind === 'fuel' ? 'selected' : ''}>加油</option>
      <option value="charge" ${item.kind === 'charge' ? 'selected' : ''}>充电</option></select></div>`);
    fields.push(`<div class="field"><label>数量 (${item.kind === 'charge' ? 'kWh' : 'L'})</label>
      <input type="number" step="any" data-idx="${idx}" data-field="quantity" value="${item.quantity === null ? '' : item.quantity}"></div>`);
    fields.push(`<div class="field"><label>单价 (元)</label><input type="number" step="any" data-idx="${idx}" data-field="unit_price" value="${item.unit_price === null ? '' : item.unit_price}"></div>`);
    fields.push(`<div class="field"><label>金额 (元)</label><input type="number" step="any" data-idx="${idx}" data-field="cost" value="${item.cost === null ? '' : item.cost}"></div>`);
    fields.push(`<div class="field"><label>站点</label><input data-idx="${idx}" data-field="station" value="${esc(item.station || '')}"></div>`);
    if (item.kind === 'charge') {
      fields.push(`<div class="field"><label>起始电量 %</label><input type="number" step="any" data-idx="${idx}" data-field="soc_start" value="${item.soc_start === null ? '' : item.soc_start}"></div>`);
      fields.push(`<div class="field"><label>结束电量 %</label><input type="number" step="any" data-idx="${idx}" data-field="soc_end" value="${item.soc_end === null ? '' : item.soc_end}"></div>`);
      fields.push(`<div class="field"><label>续航增加 (km)</label><input type="number" step="any" data-idx="${idx}" data-field="range_delta" value="${item.range_delta === null ? '' : item.range_delta}"></div>`);
    }
  } else {
    fields.push(`<div class="field"><label>类别</label><select data-idx="${idx}" data-field="rtype">
      <option value="maintenance" ${item.rtype === 'maintenance' ? 'selected' : ''}>保养</option>
      <option value="repair" ${item.rtype === 'repair' ? 'selected' : ''}>维修</option>
      <option value="expense" ${item.rtype === 'expense' ? 'selected' : ''}>其他开销</option></select></div>`);
    fields.push(`<div class="field" style="grid-column:span 2"><label>项目</label><input data-idx="${idx}" data-field="items" value="${esc(item.items || '')}"></div>`);
    fields.push(`<div class="field"><label>金额 (元)</label><input type="number" step="any" data-idx="${idx}" data-field="cost" value="${item.cost === null ? '' : item.cost}"></div>`);
    fields.push(`<div class="field"><label>门店</label><input data-idx="${idx}" data-field="shop" value="${esc(item.shop || '')}"></div>`);
  }
  fields.push(`<div class="field" style="grid-column:1/-1"><label>备注</label><input data-idx="${idx}" data-field="note" value="${esc(item.note || '')}"></div>`);

  return `<div class="ai-item ${item.valid === false ? 'invalid' : ''}">
    <div class="ai-item-head">
      <span class="badge ${isEnergy ? (item.kind === 'charge' ? 'ev' : 'ice') : 'phev'}">
        ${isEnergy ? (KIND[item.kind] || '能耗') : (RTYPE[item.rtype] || '保养')}
      </span>
      <span class="small muted">${esc(item.vehicle_name || (v ? v.name : ''))} · 置信度 ${Math.round((item.confidence || 0) * 100)}%</span>
      <span class="spacer"></span>
      <button class="btn sm ghost" data-action="ai-remove" data-idx="${idx}">${icon('x')}移除</button>
    </div>
    ${warnings}
    <div class="ai-fields">${fields.join('')}</div>
    <div class="small muted" style="border-top:1px dashed var(--line);padding-top:8px">原文：${esc(item.raw_text || '')}</div>
  </div>`;
}

/* ================================================================ 数据与备份 */
async function renderData() {
  const d = await api('/api/overview');
  const energyCount = d.vehicles.reduce((acc, s) => acc + (s.energy_count || 0), 0);
  const serviceCount = d.vehicles.reduce((acc, s) => acc + (s.service_count || 0), 0);
  const lastBackup = State.settings.last_backup_at
    ? String(State.settings.last_backup_at).slice(0, 16).replace('T', ' ') : '尚未备份';
  State.importMode = State.importMode || 'merge';

  pageHead('数据与备份', '全量 JSON 备份、CSV 导出、一键恢复 · 数据只落在你自己的 NAS 上');

  $('#view').innerHTML = `
    <div class="grid-2">
      <section class="card">
        <div class="card-head"><h3>数据概况</h3><span class="sub">当前库内记录</span>
          <div class="spacer"></div><span class="badge neutral">SQLite</span></div>
        <div class="card-body">
          <dl class="kv" style="grid-template-columns:110px 1fr">
            <dt>车辆档案</dt><dd>${d.vehicle_count} 台</dd>
            <dt>能耗记录</dt><dd>${energyCount} 条（加油 / 充电）</dd>
            <dt>保养维修</dt><dd>${serviceCount} 条（含其他开销）</dd>
            <dt>自定义提醒</dt><dd>${State.reminders.filter((r) => r.editable).length} 条</dd>
            <dt>上次备份</dt><dd>${esc(lastBackup)}</dd>
            <dt>存储位置</dt><dd class="mono small" style="word-break:break-all">${esc((State.meta && State.meta.db_path) || '—')}</dd>
          </dl>
          <div class="hint-box" style="margin-top:14px">
            数据库为 SQLite 单文件，位于应用数据目录（飞牛「应用文件」中可见）。备份文件为可读 JSON，
            包含车辆档案、全部明细与自定义提醒，可在任意设备恢复；建议把数据目录纳入 NAS 快照或云端备份计划。
          </div>
        </div>
      </section>

      <section class="card">
        <div class="card-head"><h3>导出与备份</h3><span class="sub">随时导出，不锁定格式</span></div>
        <div class="card-body" style="display:flex;flex-direction:column;gap:14px">
          <div class="toolbar">
            <button class="btn primary" data-action="export" data-kind="json">${icon('download')}JSON 完整备份</button>
            <button class="btn" data-action="export" data-kind="csv" data-table="energy">${icon('file')}CSV · 能耗</button>
            <button class="btn" data-action="export" data-kind="csv" data-table="service">${icon('file')}CSV · 保养维修</button>
            <button class="btn" data-action="export" data-kind="csv" data-table="vehicles">${icon('file')}CSV · 车辆</button>
          </div>
          <div class="hint-box">
            CSV 使用 UTF-8 BOM 编码，Excel 可直接打开；列名同时兼容中文与英文字段，便于交给修理厂或做二次分析。
          </div>
        </div>
      </section>
    </div>

    <div class="grid-2">
      <section class="card">
        <div class="card-head"><h3>从备份恢复</h3><span class="sub">仅接受本应用导出的 JSON</span></div>
        <div class="card-body" style="display:flex;flex-direction:column;gap:12px">
          <div class="dropzone" id="dropZone">
            ${icon('upload')}
            <div style="margin-top:6px">点击选择备份文件，或把 .json 拖到这里</div>
            <input type="file" id="importFile" accept=".json,application/json" hidden>
          </div>
          <div class="seg" id="importModeSeg">
            <button data-action="import-mode" data-mode="merge" class="${State.importMode === 'merge' ? 'active' : ''}">合并（跳过重复）</button>
            <button data-action="import-mode" data-mode="replace" class="${State.importMode === 'replace' ? 'active' : ''}">覆盖（清空后恢复）</button>
          </div>
          <div class="small muted">当前模式：<b>${State.importMode === 'merge' ? '合并' : '覆盖'}</b> · ${State.importMode === 'merge'
            ? '保留现有记录，按车辆 + 日期 + 数量/项目 + 金额去重。'
            : '清空全部车辆与记录后写入备份内容，适合迁移到新机器。'}</div>
        </div>
      </section>

      <section class="card">
        <div class="card-head"><h3>CSV 导入</h3><span class="sub">把旧表格搬进来</span></div>
        <div class="card-body" style="display:flex;flex-direction:column;gap:12px">
          <div class="toolbar">
            <button class="btn" data-action="csv-import" data-table="energy">${icon('upload')}导入能耗 CSV</button>
            <button class="btn" data-action="csv-import" data-table="service">${icon('upload')}导入保养 CSV</button>
            <input type="file" id="csvFile" accept=".csv" hidden>
          </div>
          <div class="hint-box">
            建议先导出一份同类型 CSV 作为模板：表头需包含「日期」「车辆ID 或 车辆名称」，其余列缺失会自动留空。
            导入按合并处理，不会清空现有数据。
          </div>
        </div>
      </section>
    </div>

    <section class="card">
      <div class="card-head"><h3>维护</h3><span class="sub">不可逆操作需二次确认</span></div>
      <div class="card-body toolbar">
        <span class="small muted">全部车辆、能耗、保养与提醒记录均为本机录入，可随时导出 JSON 备份。</span>
        <div class="spacer"></div>
        <button class="btn danger" data-action="clear-data">${icon('trash')}清空全部数据</button>
      </div>
    </section>`;

  const dz = $('#dropZone');
  dz.addEventListener('click', () => $('#importFile').click());
  dz.addEventListener('dragover', (e) => { e.preventDefault(); dz.classList.add('drag'); });
  dz.addEventListener('dragleave', () => dz.classList.remove('drag'));
  dz.addEventListener('drop', (e) => {
    e.preventDefault();
    dz.classList.remove('drag');
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) handleImportFile(file);
  });
}

/* ================================================================ 设置 */
async function renderSettings() {
  const s = State.settings;
  const isAdmin = Boolean(State.user && State.user.role === 'admin');
  if (isAdmin) {
    try { await refreshAccounts(); } catch (err) { State.accounts = []; }
  }
  pageHead('设置', '账号安全、Hermes 推理服务与显示偏好');

  const vehicleOptions = ['<option value="">跟随记录选择</option>'].concat(
    State.vehicles.map((v) => `<option value="${v.id}" ${String(s.default_vehicle_id) === String(v.id) ? 'selected' : ''}>${esc(v.name)}</option>`),
  ).join('');

  $('#view').innerHTML = `
    <div class="grid-2">
      <section class="card">
        <div class="card-head"><h3>Hermes 推理服务</h3><span class="sub">OpenAI 兼容 /chat/completions</span>
          <div class="spacer"></div><span class="badge ${s.ai_enabled === '1' ? 'ok' : 'neutral'}">${s.ai_enabled === '1' ? '已启用' : '已停用'}</span>
        </div>
        <div class="card-body">
          <div class="form-grid">
            <div class="field check span-2">
              <input type="checkbox" id="setEnabled" ${s.ai_enabled === '1' ? 'checked' : ''}>
              <label for="setEnabled">启用 Hermes 自然语言解析（关闭后仅使用本地规则引擎）</label>
            </div>
            <div class="field span-2">
              <label>服务地址（Base URL）</label>
              <input id="setBaseUrl" value="${esc(s.ai_base_url || '')}" placeholder="http://127.0.0.1:11434/v1">
              <div class="hint">Ollama 本机默认 <span class="mono">http://127.0.0.1:11434/v1</span>；Hermes 部署在其它设备时填 <span class="mono">http://192.168.x.x:11434/v1</span>；也支持 vLLM、LM Studio 等 OpenAI 兼容网关。</div>
            </div>
            <div class="field"><label>模型名称</label><input id="setModel" value="${esc(s.ai_model || '')}" placeholder="hermes3:8b"></div>
            <div class="field"><label>API Key（可选）</label><input id="setKey" type="password" value="${esc(s.ai_api_key || '')}" placeholder="本地 Ollama 无需填写"></div>
            <div class="field"><label>超时（秒）</label><input id="setTimeout" type="number" min="5" max="300" value="${esc(s.ai_timeout || '60')}"></div>
            <div class="field"><label>温度（0-1）</label><input id="setTemp" type="number" step="0.1" min="0" max="1" value="${esc(s.ai_temperature || '0.1')}"></div>
          </div>
        </div>
        <div class="modal-foot" style="border-radius:0 0 12px 12px;justify-content:flex-end">
          <span class="left small muted" id="aiTestResult"></span>
          <button class="btn" data-action="test-ai">${icon('refresh')}测试连接</button>
          <button class="btn primary" data-action="save-settings">保存设置</button>
        </div>
      </section>

      <div style="display:flex;flex-direction:column;gap:16px">
        <section class="card">
          <div class="card-head"><h3>显示与默认值</h3></div>
          <div class="card-body">
            <div class="form-grid">
              <div class="field"><label>货币符号</label><input id="setCurrency" value="${esc(s.currency || '¥')}" maxlength="4"></div>
              <div class="field"><label>默认车辆</label><select id="setDefaultVehicle">${vehicleOptions}</select></div>
            </div>
          </div>
        </section>
        <section class="card">
          <div class="card-head"><h3>部署与数据</h3></div>
          <div class="card-body small muted" style="line-height:1.85">
            应用版本 <b>v${esc(State.meta ? State.meta.version : '')}</b>，作为飞牛原生应用运行，数据库为 SQLite 单文件。<br>
            数据目录 <span class="mono" style="word-break:break-all">${esc((State.meta && State.meta.data_dir) || '—')}</span>，
            由应用中心统一管理，升级时保留、卸载时默认保留。<br>
            Web 端口可在「应用中心 → 车库管家 → 设置 → 配置」中修改，保存后自动重启生效。<br>
            Hermes 模型推荐在 Ollama 中拉取 <span class="mono">hermes3:8b</span>（约 4.7 GB，8 GB 内存可运行）。
          </div>
        </section>
      </div>
    </div>

    <section class="card">
      <div class="card-head">
        <h3>账号与安全</h3>
        <span class="sub">${isAdmin ? '成员可读写车辆数据，管理员可管理账号与恢复备份' : '如需新增账号或重置密码，请联系管理员'}</span>
        <div class="spacer"></div>
        <button class="btn sm" data-action="change-password">${icon('shield')}修改密码</button>
        ${isAdmin ? `<button class="btn sm primary" data-action="add-account">${icon('plus')}新增账号</button>` : ''}
      </div>
      <div class="card-body">
        <div class="toolbar" style="margin-bottom:14px">
          <div class="user-chip" style="border-top:0;padding-top:0;margin-top:0">
            <div class="user-avatar">${esc(String((State.user && (State.user.display_name || State.user.username)) || '?').slice(0, 1))}</div>
            <div class="user-meta">
              <b>${esc((State.user && (State.user.display_name || State.user.username)) || '—')}</b>
              <span>${State.user && State.user.role === 'admin' ? '管理员' : '成员'} · 账号 ${esc((State.user && State.user.username) || '—')}</span>
            </div>
          </div>
          <div class="spacer"></div>
          <span class="small muted">上次登录：${esc(State.user && State.user.last_login ? String(State.user.last_login).slice(0, 16).replace('T', ' ') : '本次为首次登录')}</span>
        </div>
        ${isAdmin ? accountsTable() : ''}
      </div>
    </section>`;
}

/* ================================================================ 表单：车辆 */
function openVehicleForm(vehicle) {
  const isEdit = !!vehicle;
  openForm({
    title: isEdit ? '编辑车辆' : '新增车辆',
    subtitle: '动力类型决定可记录的能耗种类',
    wide: true,
    values: vehicle || { vtype: 'ice', init_odometer: 0 },
    submitText: isEdit ? '保存修改' : '创建车辆',
    fields: [
      { section: '基本信息' },
      { name: 'name', label: '车辆名称', required: true, placeholder: '如：小鹏 G6 / 途观 L' },
      { name: 'plate', label: '车牌号', placeholder: '京A·12345' },
      { name: 'vtype', label: '动力类型', type: 'select', options: [['ice', '燃油车'], ['ev', '纯电动车'], ['phev', '插电混动']] },
      { name: 'brand', label: '品牌', placeholder: '小鹏 / 大众' },
      { name: 'model', label: '车型', placeholder: 'G6 755 Max' },
      { name: 'year', label: '年款', type: 'number', placeholder: '2024' },
      { name: 'color', label: '颜色' },
      { name: 'vin', label: '车架号 VIN', span: 2, placeholder: '17 位车架号' },
      { section: '里程与容量' },
      { name: 'init_odometer', label: '初始里程 (km)', type: 'number', hint: '建档时的里程表读数，用于计算累计里程' },
      { name: 'tank_capacity', label: '油箱容积 (L)', type: 'number', hint: '燃油 / 插混填写' },
      { name: 'battery_capacity', label: '电池容量 (kWh)', type: 'number', hint: '纯电 / 插混填写' },
      { name: 'tire_spec', label: '轮胎规格', placeholder: '235/50 R19' },
      { section: '证照与提醒' },
      { name: 'insurer', label: '保险公司' },
      { name: 'policy_no', label: '保单号' },
      { name: 'insurance_due', label: '保险到期', type: 'date' },
      { name: 'inspect_due', label: '年检到期', type: 'date' },
      { name: 'tax_due', label: '车船税到期', type: 'date' },
      { name: 'register_date', label: '购置日期', type: 'date' },
      { name: 'note', label: '备注', type: 'textarea', span: 2 },
    ],
    onSubmit: async (values) => {
      if (isEdit) {
        await api(`/api/vehicles/${vehicle.id}`, { method: 'PUT', body: values });
        await refreshCore();
        toast('车辆档案已更新');
        navigate();
      } else {
        const res = await api('/api/vehicles', { method: 'POST', body: values });
        await refreshCore();
        toast('车辆已创建');
        location.hash = `#/vehicle/${res.id}`;
      }
    },
  });
}

/* ================================================================ 表单：能耗 */
function openEnergyForm(record, presetVid) {
  if (!State.vehicles.length) { toast('请先新增车辆', 'warn'); return; }
  const vid = (record && record.vehicle_id) || presetVid
    || Number(State.settings.default_vehicle_id || 0) || State.vehicles[0].id;
  const vehicle = State.vehicles.find((v) => v.id === vid) || State.vehicles[0];
  const isEv = vehicle.vtype === 'ev';
  const isPhev = vehicle.vtype === 'phev';
  const kindDefault = record ? record.kind : (isEv ? 'charge' : 'fuel');
  const quantityLabel = isEv || (isPhev && kindDefault === 'charge')
    ? '充电量 (kWh)' : '加油量 (L)';

  const fields = [
    { section: '记录信息' },
    {
      name: 'vehicle_id', label: '车辆', type: 'select', required: true,
      options: State.vehicles.map((v) => [v.id, `${v.name}${v.plate ? ' · ' + v.plate : ''}`]),
    },
    { name: 'date', label: '日期', type: 'date', required: true },
    { name: 'odometer', label: '里程 (km)', type: 'number', hint: '仪表总里程，用于能耗计算' },
  ];
  if (isPhev) {
    fields.push({
      name: 'kind', label: '补能类型', type: 'select',
      options: [['fuel', '加油'], ['charge', '充电']],
    });
  }
  fields.push(
    { section: '补能明细' },
    { name: 'quantity', label: quantityLabel, type: 'number', required: true },
    { name: 'unit_price', label: '单价 (元/L 或 元/kWh)', type: 'number' },
    { name: 'cost', label: '金额 (元)', type: 'number', hint: '与单价二选一，留空会自动推算' },
    { name: 'station', label: '加油站 / 充电站' },
    { name: 'is_full', label: '本次加满 / 充满', type: 'check', hint: '真实油耗只统计满箱区间' },
  );
  if (!isEv) {
    fields.push({ name: 'range_delta', label: '续航增加 (km)', type: 'number', hint: '仅充电时填写' });
  } else {
    fields.push(
      { name: 'soc_start', label: '起始电量 (%)', type: 'number' },
      { name: 'soc_end', label: '结束电量 (%)', type: 'number' },
      { name: 'range_delta', label: '续航增加 (km)', type: 'number' },
    );
  }
  fields.push({ name: 'note', label: '备注', type: 'textarea', span: 2 });

  openForm({
    title: record ? '编辑能耗记录' : '新增能耗记录',
    subtitle: `${vehicle.name} · ${VTYPE[vehicle.vtype]}${isPhev ? ' · 可记录加油与充电' : ''}`,
    values: record || { vehicle_id: vid, date: todayStr(), kind: kindDefault, is_full: 1 },
    submitText: record ? '保存修改' : '保存记录',
    fields,
    onSubmit: async (values) => {
      if (isPhev && !values.kind) values.kind = 'fuel';
      if (record) await api(`/api/energy/${record.id}`, { method: 'PUT', body: values });
      else await api('/api/energy', { method: 'POST', body: values });
      await refreshCore();
      toast(record ? '记录已更新' : '记录已保存');
      navigate();
    },
  });
}

/* ================================================================ 表单：保养 */
function openServiceForm(record, presetVid) {
  if (!State.vehicles.length) { toast('请先新增车辆', 'warn'); return; }
  const vid = (record && record.vehicle_id) || presetVid
    || Number(State.settings.default_vehicle_id || 0) || State.vehicles[0].id;

  openForm({
    title: record ? '编辑保养记录' : '新增保养 / 维修记录',
    subtitle: '填写下次保养日期或里程，系统会自动生成提醒',
    values: record || { vehicle_id: vid, rtype: 'maintenance', date: todayStr() },
    submitText: record ? '保存修改' : '保存记录',
    fields: [
      { section: '记录信息' },
      {
        name: 'vehicle_id', label: '车辆', type: 'select', required: true,
        options: State.vehicles.map((v) => [v.id, `${v.name}${v.plate ? ' · ' + v.plate : ''}`]),
      },
      { name: 'rtype', label: '类别', type: 'select', options: [['maintenance', '保养'], ['repair', '维修'], ['expense', '其他开销']] },
      { name: 'date', label: '日期', type: 'date', required: true },
      { name: 'odometer', label: '里程 (km)', type: 'number' },
      { section: '作业明细' },
      { name: 'items', label: '项目', required: true, span: 2, placeholder: '如：更换机油机滤（全合成 5W-30）' },
      { name: 'cost', label: '费用 (元)', type: 'number' },
      { name: 'shop', label: '门店 / 修理厂' },
      { section: '下次保养' },
      { name: 'next_date', label: '下次日期', type: 'date' },
      { name: 'next_odometer', label: '下次里程 (km)', type: 'number' },
      { name: 'note', label: '备注', type: 'textarea', span: 2 },
    ],
    onSubmit: async (values) => {
      if (record) await api(`/api/service/${record.id}`, { method: 'PUT', body: values });
      else await api('/api/service', { method: 'POST', body: values });
      await refreshCore();
      toast(record ? '记录已更新' : '记录已保存');
      navigate();
    },
  });
}

/* ================================================================ 表单：提醒 */
function openReminderForm(presetVid) {
  if (!State.vehicles.length) { toast('请先新增车辆', 'warn'); return; }
  const vid = presetVid || Number(State.settings.default_vehicle_id || 0) || State.vehicles[0].id;
  openForm({
    title: '新增自定义提醒',
    subtitle: '日期与里程可只填一项，两者都填时按先到者提醒',
    values: { vehicle_id: vid },
    submitText: '创建提醒',
    fields: [
      {
        name: 'vehicle_id', label: '车辆', type: 'select', required: true,
        options: State.vehicles.map((v) => [v.id, `${v.name}${v.plate ? ' · ' + v.plate : ''}`]),
      },
      { name: 'title', label: '提醒事项', required: true, span: 2, placeholder: '如：轮胎换位 / 更换空调滤芯' },
      { name: 'due_date', label: '到期日期', type: 'date' },
      { name: 'due_odometer', label: '到期里程 (km)', type: 'number' },
      { name: 'note', label: '说明', type: 'textarea', span: 2 },
    ],
    onSubmit: async (values) => {
      await api('/api/reminders', { method: 'POST', body: values });
      await refreshCore();
      toast('提醒已创建');
      navigate();
    },
  });
}

/* ================================================================ 导入导出 */
async function handleImportFile(file) {
  try {
    const text = await file.text();
    let data;
    try { data = JSON.parse(text); } catch (e) { throw new Error('文件不是有效的 JSON 备份'); }
    const vCount = (data.vehicles || []).length;
    const eCount = (data.energy_records || []).length;
    const sCount = (data.service_records || []).length;
    const mode = State.importMode || 'merge';
    const ok = await confirmDialog({
      title: '确认恢复备份',
      message: `文件：${esc(file.name)}<br>包含 ${vCount} 台车辆、${eCount} 条能耗、${sCount} 条保养记录。<br><br>`
        + (mode === 'replace'
          ? '<b style="color:#dc2626">覆盖模式会先清空当前全部数据</b>，再写入备份内容，请确认已另行备份。'
          : '合并模式会保留现有数据，并按「车辆 + 日期 + 数量/项目 + 金额」跳过重复记录。'),
      confirmText: mode === 'replace' ? '清空并恢复' : '开始合并',
      danger: mode === 'replace',
    });
    if (!ok) return;
    const res = await api('/api/import', { method: 'POST', body: { mode, data } });
    toast(`恢复完成：车辆 ${res.imported.vehicles}，能耗 ${res.imported.energy}，保养 ${res.imported.service}，跳过 ${res.skipped}`);
    await refreshCore();
    navigate();
  } catch (err) {
    toast(err.message || '恢复失败', 'err', 5000);
  }
}

async function handleCsvImport(file, table) {
  try {
    const fd = new FormData();
    fd.append('file', file);
    const res = await api(`/api/import/csv?table=${encodeURIComponent(table)}&mode=merge`, { method: 'POST', body: fd });
    toast(`CSV 导入完成：成功 ${res.imported} 条，跳过 ${res.skipped} 条`);
    await refreshCore();
    navigate();
  } catch (err) {
    toast(err.message || 'CSV 导入失败', 'err', 5000);
  }
}

async function saveSettings() {
  const payload = {
    ai_enabled: $('#setEnabled').checked ? '1' : '0',
    ai_base_url: $('#setBaseUrl').value.trim(),
    ai_model: $('#setModel').value.trim(),
    ai_api_key: $('#setKey').value,
    ai_timeout: $('#setTimeout').value || '60',
    ai_temperature: $('#setTemp').value || '0.1',
    currency: $('#setCurrency').value.trim() || '¥',
    default_vehicle_id: $('#setDefaultVehicle').value || '',
  };
  await api('/api/settings', { method: 'PUT', body: payload });
  State.settings = await api('/api/settings');
  renderFoot();
  toast('设置已保存');
  navigate();
}

/* ================================================================ 动作分发 */
async function handleAction(el) {
  const action = el.dataset.action;
  const id = el.dataset.id ? Number(el.dataset.id) : null;

  switch (action) {
    case 'close-modal':
      closeModal();
      return;
    case 'reload':
      location.reload();
      return;
    case 'logout':
      await doLogout();
      return;
    case 'change-password':
      openPasswordForm(false);
      return;
    case 'add-account':
      openAccountForm();
      return;
    case 'reset-account': {
      const acc = State.accounts.find((x) => x.id === id);
      if (acc) openResetPasswordForm(acc);
      return;
    }
    case 'toggle-account': {
      const acc = State.accounts.find((x) => x.id === id);
      if (!acc) return;
      const disable = el.dataset.disabled === '0';
      await api(`/api/auth/users/${id}`, { method: 'PUT', body: { disabled: disable ? 1 : 0 } });
      toast(disable ? `已停用「${acc.username}」` : `已启用「${acc.username}」`);
      await refreshAccounts();
      navigate();
      return;
    }
    case 'del-account': {
      const acc = State.accounts.find((x) => x.id === id);
      const name = el.dataset.name || (acc && acc.username) || '';
      const ok = await confirmDialog({
        title: '删除账号',
        message: `确定删除账号「${esc(name)}」？<br>该账号的登录会话会立即失效。<br><br>
          车辆、能耗与保养数据为全体账号共享，<b>不会</b>随之删除。`,
        confirmText: '删除账号',
        danger: true,
      });
      if (!ok) return;
      await api(`/api/auth/users/${id}`, { method: 'DELETE' });
      toast('账号已删除', 'warn');
      await refreshAccounts();
      navigate();
      return;
    }
    case 'goto':
      location.hash = el.dataset.hash;
      return;
    case 'add-vehicle':
      openVehicleForm();
      return;
    case 'edit-vehicle': {
      const v = (State.detail && State.detail.v && State.detail.v.id === id)
        ? State.detail.v : State.vehicles.find((x) => x.id === id);
      if (v) openVehicleForm(v);
      return;
    }
    case 'del-vehicle': {
      const v = State.vehicles.find((x) => x.id === id);
      const s = v && v.summary ? v.summary : {};
      const ok = await confirmDialog({
        title: '删除车辆',
        message: `确定删除「${esc(v ? v.name : '该车辆')}」？<br>将同时删除其 ${s.record_count || 0} 条能耗与保养记录，且不可撤销。<br><br>
          建议先在「数据与备份」导出一份 JSON 备份。`,
        confirmText: '删除车辆',
        danger: true,
      });
      if (!ok) return;
      await api(`/api/vehicles/${id}`, { method: 'DELETE' });
      await refreshCore();
      toast('车辆已删除', 'warn');
      if (State.route.name === 'vehicle') location.hash = '#/vehicles';
      else navigate();
      return;
    }
    case 'add-energy':
      openEnergyForm(null, el.dataset.vid ? Number(el.dataset.vid) : null);
      return;
    case 'edit-energy': {
      const rec = State.energyItems.find((x) => x.id === id);
      if (rec) openEnergyForm(rec);
      else toast('记录已失效，请刷新页面', 'warn');
      return;
    }
    case 'del-energy': {
      const ok = await confirmDialog({
        title: '删除能耗记录', message: '删除后不可撤销，相关油耗/电耗会重新计算。',
        confirmText: '删除', danger: true,
      });
      if (!ok) return;
      await api(`/api/energy/${id}`, { method: 'DELETE' });
      await refreshCore();
      toast('记录已删除', 'warn');
      navigate();
      return;
    }
    case 'add-service':
      openServiceForm(null, el.dataset.vid ? Number(el.dataset.vid) : null);
      return;
    case 'edit-service': {
      const rec = State.serviceItems.find((x) => x.id === id);
      if (rec) openServiceForm(rec);
      else toast('记录已失效，请刷新页面', 'warn');
      return;
    }
    case 'del-service': {
      const ok = await confirmDialog({
        title: '删除保养记录', message: '删除后不可撤销，相关提醒可能随之变化。',
        confirmText: '删除', danger: true,
      });
      if (!ok) return;
      await api(`/api/service/${id}`, { method: 'DELETE' });
      await refreshCore();
      toast('记录已删除', 'warn');
      navigate();
      return;
    }
    case 'add-reminder':
      openReminderForm(el.dataset.vid ? Number(el.dataset.vid) : null);
      return;
    case 'reminder-done':
      await api(`/api/reminders/${id}/done`, { method: 'POST' });
      await refreshCore();
      toast('已标记完成');
      navigate();
      return;
    case 'reminder-del': {
      const ok = await confirmDialog({
        title: '删除提醒', message: '删除后不可恢复。', confirmText: '删除', danger: true,
      });
      if (!ok) return;
      await api(`/api/reminders/${id}`, { method: 'DELETE' });
      await refreshCore();
      toast('提醒已删除', 'warn');
      navigate();
      return;
    }
    case 'detail-tab':
      State.detailTab = el.dataset.tab;
      await renderVehicleDetail(State.route.id);
      return;
    case 'reset-energy-filter':
      State.energyFilter = { vehicle_id: '', kind: '', from: '', to: '' };
      await renderEnergy();
      return;
    case 'reset-service-filter':
      State.serviceFilter = { vehicle_id: '', rtype: '', from: '', to: '' };
      await renderService();
      return;
    case 'ai-example': {
      const ta = $('#aiText');
      ta.value = el.dataset.text || '';
      ta.focus();
      return;
    }
    case 'ai-parse':
      await aiParse();
      return;
    case 'ai-remove':
      if (State.ai) {
        State.ai.items.splice(Number(el.dataset.idx), 1);
        renderAIResult();
      }
      return;
    case 'ai-reset':
      State.ai = null;
      await renderAI();
      return;
    case 'ai-save':
      await aiSave();
      return;
    case 'export': {
      const kind = el.dataset.kind;
      if (kind === 'json') await download('/api/export/json', 'garage-backup.json');
      else await download(`/api/export/csv?table=${el.dataset.table || 'energy'}`, `${el.dataset.table || 'energy'}.csv`);
      toast('导出已开始下载');
      return;
    }
    case 'csv-import':
      State.csvTable = el.dataset.table || 'energy';
      $('#csvFile').click();
      return;
    case 'import-mode':
      State.importMode = el.dataset.mode;
      await renderData();
      return;
    case 'clear-data': {
      const ok = await confirmDialog({
        title: '清空全部数据',
        message: '<b style="color:#dc2626">该操作会删除所有车辆、能耗、保养与提醒记录，且无法撤销。</b><br><br>请先导出 JSON 备份，再执行清空。',
        confirmText: '我已备份，确认清空', danger: true,
      });
      if (!ok) return;
      await api('/api/data?confirm=DELETE', { method: 'DELETE' });
      State.detail = null;
      await refreshCore();
      toast('数据已清空', 'warn');
      location.hash = '#/overview';
      navigate();
      return;
    }
    case 'save-settings':
      try { await saveSettings(); } catch (err) { toast(err.message, 'err'); }
      return;
    case 'test-ai': {
      const box = $('#aiTestResult');
      if (box) box.textContent = '正在测试…';
      try {
        const res = await api('/api/ai/test', { method: 'POST' });
        if (box) box.textContent = res.message;
        toast(res.message, res.ok ? 'ok' : 'err', 4200);
      } catch (err) {
        if (box) box.textContent = err.message;
        toast(err.message, 'err');
      }
      return;
    }
    default:
      return;
  }
}

/* ================================================================ 智能录入动作 */
async function aiParse() {
  const ta = $('#aiText');
  const text = ta.value.trim();
  if (!text) { toast('请先输入记录内容', 'warn'); ta.focus(); return; }
  const btn = $('#aiParseBtn');
  const original = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = '解析中…';
  try {
    const res = await api('/api/ai/parse', {
      method: 'POST',
      body: { text, vehicle_id: $('#aiVehicle').value ? Number($('#aiVehicle').value) : null },
    });
    State.ai = res;
    State.ai.text = text;
    renderAIResult();
    if (res.source === 'rule') toast('Hermes 不可用，已使用本地规则解析', 'warn', 4000);
  } catch (err) {
    toast(err.message, 'err', 5000);
  } finally {
    btn.disabled = false;
    btn.innerHTML = original;
  }
}

async function aiSave() {
  if (!State.ai || !State.ai.items) return;
  const items = State.ai.items.filter((i) => i.valid !== false);
  if (!items.length) { toast('没有可保存的记录', 'warn'); return; }
  const payload = items.map((i) => {
    const base = {
      record_type: i.record_type, vehicle_id: i.vehicle_id, date: i.date,
      odometer: i.odometer, cost: i.cost, note: i.note,
    };
    if (i.record_type === 'energy') {
      return Object.assign(base, {
        kind: i.kind, quantity: i.quantity, unit_price: i.unit_price, station: i.station,
        is_full: i.is_full, range_delta: i.range_delta, soc_start: i.soc_start, soc_end: i.soc_end,
      });
    }
    return Object.assign(base, {
      rtype: i.rtype, items: i.items, shop: i.shop, next_date: i.next_date, next_odometer: i.next_odometer,
    });
  });
  try {
    const res = await api('/api/ai/commit', { method: 'POST', body: payload });
    if (res.errors && res.errors.length) {
      toast(`部分保存失败：${res.errors.join('；')}`, 'err', 6000);
    } else {
      toast(`已写入 ${res.created.length} 条记录`);
    }
    State.ai = null;
    await refreshCore();
    navigate();
  } catch (err) {
    toast(err.message, 'err', 5000);
  }
}

/* ================================================================ 事件绑定 */
function onInput(e) {
  const t = e.target;
  if (!t.dataset || t.dataset.idx === undefined || !t.dataset.field || !State.ai) return;
  const idx = Number(t.dataset.idx);
  const field = t.dataset.field;
  const item = State.ai.items[idx];
  if (!item) return;
  let value = t.value;
  if (field === 'vehicle_id') {
    value = Number(value);
    const v = State.vehicles.find((x) => x.id === value);
    if (v) item.vehicle_name = v.name;
  } else if (['odometer', 'quantity', 'unit_price', 'cost', 'soc_start', 'soc_end', 'range_delta', 'next_odometer'].includes(field)) {
    value = value === '' ? null : Number(value);
  } else if (value === '') {
    value = null;
  }
  item[field] = value;
  if (field === 'kind') renderAIResult();
}

function onClick(e) {
  const backdrop = e.target.closest('[data-backdrop]');
  if (backdrop && e.target === backdrop) { closeModal(); return; }
  const el = e.target.closest('[data-action]');
  if (!el) {
    if (e.target.closest('[data-nav]')) $('#app').classList.remove('nav-open');
    return;
  }
  e.preventDefault();
  if (e.target.closest('[data-nav]')) $('#app').classList.remove('nav-open');
  Promise.resolve(handleAction(el)).catch((err) => toast(err.message || '操作失败', 'err'));
}

function onChange(e) {
  const t = e.target;
  if (t.id === 'importFile' && t.files && t.files[0]) {
    const file = t.files[0];
    t.value = '';
    handleImportFile(file);
  }
  if (t.id === 'csvFile' && t.files && t.files[0]) {
    const file = t.files[0];
    t.value = '';
    handleCsvImport(file, State.csvTable || 'energy');
  }
}

function bindGlobal() {
  document.addEventListener('click', onClick);
  document.addEventListener('input', onInput);
  document.addEventListener('change', onChange);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });
  const menuBtn = $('#menuBtn');
  if (menuBtn) menuBtn.addEventListener('click', () => $('#app').classList.toggle('nav-open'));
  window.addEventListener('hashchange', () => {
    $('#app').classList.remove('nav-open');
    if (State.meta) navigate();
  });
}

/* ================================================================ 启动 */
document.addEventListener('DOMContentLoaded', async () => {
  bindGlobal();
  const form = $('#authForm');
  if (form) form.addEventListener('submit', submitAuth);

  try {
    const state = await api('/api/auth/state');
    State.authCfg = state;
    if ($('#authVersion')) $('#authVersion').textContent = state.version ? `v${state.version}` : '';
    if (state.logged_in && state.user) {
      State.user = state.user;
      await startApp();
      if (State.user && State.user.must_change) openPasswordForm(true);
      return;
    }
    hideBoot();
    showLogin('');
  } catch (err) {
    hideBoot();
    showLogin(err.message || '无法连接服务，请确认应用已启动');
  }
});
