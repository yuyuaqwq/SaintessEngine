/* ══════════════════════════════════════════════════════════════════════════
   SaintessEngine 工作室 —— 编辑器前端逻辑（原生 JS，零构建）

   设计稿   editor/UI_DESIGN.md
   后端     editor/server.py（**本文件不改后端 API**）

   布局     域栏（rail） + 条目列表（list） + 编辑器（editor） + 试跑抽屉（drawer）
   键盘     Ctrl+K 面板 · Ctrl+S 保存 · / 搜索 · ↑↓ 移动 · Alt+↑↓ 换域 · Esc 关闭
   ══════════════════════════════════════════════════════════════════════════ */
'use strict';

/* ───────────────────────── 工具 ───────────────────────── */
const $ = (id) => document.getElementById(id);
const el = (sel, root) => (root || document).querySelector(sel);
const els = (sel, root) => Array.from((root || document).querySelectorAll(sel));
const esc = (s) => String(s == null ? '' : s)
  .replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const clone = (o) => JSON.parse(JSON.stringify(o == null ? null : o));
const isObj = (v) => v && typeof v === 'object' && !Array.isArray(v);

/* ───────────────────────── 状态 ───────────────────────── */
const S = {
  domains: [], pkgs: [], pkgId: null, pkg: null,
  dom: 'skills', entries: [], status: { invalid: [] },
  entryKey: null, entryData: null, entryOrig: null, schema: null, validationErrors: [],
  mode: 'form', filter: 'all', sort: 'kind',
  dirtyKeys: new Set(),          // 有未保存改动的条目 key（当前域）
  kb: -1,                        // 键盘焦点索引
  pkgOpen: false,
};

/* ───────────────────────── API ───────────────────────── */
async function api(method, path, body) {
  const r = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  let j = null;
  try { j = await r.json(); } catch (e) { /* 非 JSON */ }
  return { status: r.status, ok: r.ok, json: j };
}
const dPath = (dom) => `/api/package/${encodeURIComponent(S.pkgId)}/d/${dom}`;

/* ───────────────────────── toast ───────────────────────── */
function toast(msg, kind) {
  const k = kind === true ? 'ok' : (kind || '');       // 兼容旧调用 toast(msg, true)
  const ico = { ok: '✓', bad: '✕', warn: '⚠', '': 'ℹ' }[k] || 'ℹ';
  const box = document.createElement('div');
  box.className = 'toast ' + k;
  box.innerHTML = `<span class="toast-ico">${ico}</span><span class="toast-msg">${esc(msg)}</span>`;
  const off = () => { box.style.opacity = '0'; setTimeout(() => box.remove(), 150); };
  box.onclick = off;
  $('toasts').appendChild(box);
  while ($('toasts').children.length > 3) $('toasts').firstChild.remove();
  setTimeout(off, 4200);
}

/* ═══════════════════════════ 启动 ═══════════════════════════ */
async function boot() {
  TH().apply();
  refreshThemeIcon();
  restoreLayout();
  const d = await api('GET', '/api/domains');
  S.domains = (d.json && d.json.domains) || [];
  S.dom = (S.domains[0] || {}).id || 'skills';
  await loadPackages();
  renderRail();
  if (S.pkgs.length) await selectPkg(S.pkgs[0].id);
  else showEmptyPkg();
}

/* ═══════════════════════════ 域栏 ═══════════════════════════ */
function renderRail() {
  const domOf = (id) => (S.pkg && (S.pkg.domains || []).find((x) => x.id === id)) || {};
  const items = S.domains.map((d) => {
    const st = domOf(d.id);
    const bad = st.ok === false;
    return `<button class="rail-item ${S.dom === d.id && !isSettings() ? 'on' : ''}" data-dom="${esc(d.id)}"
      title="${esc(d.label)}">
      <span class="ri-icon">${d.icon || '•'}</span>
      <span class="ri-label">${esc(d.label)}</span>
      <span class="ri-count ${bad ? 'bad' : ''}">${bad ? '!' : (st.count || 0)}</span>
    </button>`;
  }).join('');
  $('rail').innerHTML = items
    + '<div class="rail-sep"></div>'
    + `<button class="rail-item ${isSettings() ? 'on' : ''}" data-nav="settings" title="包设置">
         <span class="ri-icon">⚙</span><span class="ri-label">设置</span></button>`;
  els('#rail .rail-item').forEach((b) => {
    b.onclick = () => (b.dataset.nav === 'settings' ? openSettings() : switchDomain(b.dataset.dom));
  });
}

/* ═══════════════════════════ 包 ═══════════════════════════ */
async function loadPackages() {
  const r = await api('GET', '/api/packages');
  S.pkgs = (r.json && r.json.packages) || [];
  $('sbPath').textContent = (r.json && r.json.games_dir) || '';
  renderPkgMenu();
}

function renderPkgMenu() {
  const cur = S.pkgs.find((p) => p.id === S.pkgId) || {};
  $('pkgName').textContent = cur.name || (S.pkgs.length ? '—' : '（没有游戏包）');
  $('pkgIdLabel').textContent = cur.id ? `· ${cur.id}` : '';
  $('pkgMenu').innerHTML = S.pkgs.map((p) =>
    `<div class="pm-item ${p.id === S.pkgId ? 'on' : ''}" data-pkg="${esc(p.id)}">
       <span class="pl-ico">📦</span><span>${esc(p.name || p.id)}</span>
       <span class="pm-id">${esc(p.id)}</span></div>`).join('')
    + '<div class="pm-sep"></div>'
    + '<div class="pm-item pm-new" data-new="1"><span class="pl-ico">＋</span><span>新建游戏包…</span></div>';
  els('#pkgMenu [data-pkg]').forEach((n) => (n.onclick = () => {
    closePkgMenu(); selectPkg(n.dataset.pkg);
  }));
  el('#pkgMenu [data-new]').onclick = () => { closePkgMenu(); newPackage(); };
}

const openPkgMenu = () => { S.pkgOpen = true; $('pkgMenu').classList.remove('hidden'); };
const closePkgMenu = () => { S.pkgOpen = false; $('pkgMenu').classList.add('hidden'); };

async function selectPkg(id) {
  if (!id) return;
  S.pkgId = id;
  const r = await api('GET', '/api/package/' + encodeURIComponent(id));
  if (!r.ok) { toast((r.json && r.json.message) || '打开包失败', 'bad'); return; }
  S.pkg = r.json;
  S.dirtyKeys.clear();
  renderPkgMenu(); renderRail(); renderSettingsForm(); updateStatusbar();
  closeEntry();
  await loadDomain(S.dom);
}

async function refreshPkg() {
  const r = await api('GET', '/api/package/' + encodeURIComponent(S.pkgId));
  if (r.ok) { S.pkg = r.json; renderRail(); renderPkgMenu(); updateStatusbar(); }
}

async function newPackage() {
  const id = prompt('新游戏包 id（小写字母/数字/下划线，如 my_game）：');
  if (!id) return;
  const name = prompt('显示名：', id) || id;
  const r = await api('POST', '/api/packages', { id, name });
  if (!r.ok) { toast((r.json && r.json.message) || '创建失败', 'bad'); return; }
  toast('已创建 ' + id, 'ok');
  await loadPackages(); await selectPkg(id);
}

function showEmptyPkg() {
  $('entryList').innerHTML = '<div class="list-empty">还没有游戏包<br>点左上角包名 → 新建游戏包</div>';
  $('listCount').textContent = '0';
}

/* ═══════════════════════════ 域切换 ═══════════════════════════ */
async function switchDomain(dom) {
  if (dom === S.dom && !isSettings()) return;
  if (S.dirty && !confirmLeave()) return;
  S.dom = dom;
  $('settings').classList.add('hidden');
  $('editor').classList.add('hidden');
  $('editorEmpty').classList.remove('hidden');
  renderRail();
  const d = S.domains.find((x) => x.id === dom) || {};
  $('listTitle').textContent = d.label || dom;
  S.filter = 'all'; S.kb = -1;
  els('#filterRow .chip').forEach((c) => c.classList.toggle('on', c.dataset.filter === 'all'));
  await loadDomain(dom);
}

/* ═══════════════════════════ 条目列表 ═══════════════════════════ */
async function loadDomain(dom) {
  if (!S.pkgId) return;
  const r = await api('GET', dPath(dom));
  if (!r.ok) { toast((r.json && r.json.message) || '读取域失败', 'bad'); return; }
  S.entries = (r.json.entries || []);
  S.status = r.json.status || { invalid: [] };
  renderList();
}

function kindClass(k) {
  const s = String(k || '');
  if (s.startsWith('魔法·')) return 'k-魔法';
  return s ? 'k-' + s : '';
}
function isBad(key) { return (S.status.invalid || []).some((x) => x.key === key); }

function visibleEntries() {
  const q = ($('search').value || '').trim().toLowerCase();
  let rows = S.entries.slice();
  if (q) rows = rows.filter((e) => (e.key + ' ' + e.name + ' ' + (e.kind || '')).toLowerCase().includes(q));
  if (S.filter === 'bad') rows = rows.filter((e) => isBad(e.key));
  if (S.filter === 'dirty') rows = rows.filter((e) => S.dirtyKeys.has(e.key));
  const sorters = {
    kind: (a, b) => String(a.kind || '').localeCompare(String(b.kind || ''), 'zh') || String(a.name).localeCompare(String(b.name), 'zh'),
    name: (a, b) => String(a.name).localeCompare(String(b.name), 'zh'),
    key: (a, b) => String(a.key).localeCompare(String(b.key)),
  };
  rows.sort(sorters[S.sort] || sorters.kind);
  return rows;
}

function renderList() {
  const rows = visibleEntries();
  const bad = (S.status.invalid || []).length;

  // 筛选 chip 计数
  els('#filterRow .chip').forEach((c) => {
    const f = c.dataset.filter;
    const n = f === 'all' ? S.entries.length : f === 'bad' ? bad : S.dirtyKeys.size;
    c.textContent = { all: '全部', bad: '⚠ 待修', dirty: '● 未保存' }[f] + (n ? ` ${n}` : '');
  });

  $('listCount').textContent = rows.length === S.entries.length
    ? `${S.entries.length} 条`
    : `${rows.length} / ${S.entries.length} 条`;

  if (!rows.length) {
    $('entryList').innerHTML = `<div class="list-empty">${
      S.entries.length ? '没有匹配的条目' : '这个域还没有条目<br>点下面「新建条目」开始'}</div>`;
    return;
  }

  // 分组（按 kind，仅当排序=kind 且条目数 > 12）
  const grouped = S.sort === 'kind' && rows.length > 12;
  let html = '', lastKind = null;
  rows.forEach((e, i) => {
    if (grouped && e.kind !== lastKind) {
      html += `<div class="entry-group">${esc(e.kind || '未分类')}</div>`;
      lastKind = e.kind;
    }
    html += `<div class="entry-row ${e.key === S.entryKey ? 'on' : ''} ${isBad(e.key) ? 'is-bad' : ''} ${i === S.kb ? 'kb-focus' : ''}"
      data-key="${esc(e.key)}" data-idx="${i}">
      <div class="er-main">
        <div class="er-name">${esc(e.name)}</div>
        <div class="er-key">${esc(e.key)}</div>
      </div>
      <div class="er-tail">
        ${e.kind ? `<span class="chip kind ${kindClass(e.kind)}">${esc(e.kind)}</span>` : ''}
        ${isBad(e.key) ? '<span class="er-bad" title="有校验问题"></span>' : ''}
        ${S.dirtyKeys.has(e.key) ? '<span class="er-dirty" title="有未保存改动"></span>' : ''}
      </div>
    </div>`;
  });
  $('entryList').innerHTML = html;
  els('#entryList .entry-row').forEach((n) => (n.onclick = () => openEntry(n.dataset.key)));
  const cur = el('#entryList .entry-row.on');
  if (cur) cur.scrollIntoView({ block: 'nearest' });
}

/* ═══════════════════════════ 打开 / 关闭条目 ═══════════════════════════ */
function confirmLeave() {
  if (!S.dirty) return true;
  return confirm('当前条目有未保存改动，确认丢弃？');
}

function closeEntry() {
  S.entryKey = null; S.entryData = null; S.entryOrig = null; S.dirty = false;
  S.validationErrors = [];
  $('editor').classList.add('hidden');
  $('editorEmpty').classList.remove('hidden');
  $('issues').classList.add('hidden');
  $('saveStatus').textContent = '';
  renderList();
}

async function openEntry(key) {
  if (key === S.entryKey) return;
  if (S.dirty && !confirmLeave()) return;
  const r = await api('GET', `${dPath(S.dom)}/${encodeURIComponent(key)}`);
  if (!r.ok) { toast((r.json && r.json.message) || '读取条目失败', 'bad'); return; }
  S.entryKey = key;
  S.entryData = r.json.data;
  S.entryOrig = clone(r.json.data);
  S.schema = r.json.schema;
  S.validationErrors = r.json.errors || [];
  S.dirty = false;

  $('editorEmpty').classList.add('hidden');
  $('editor').classList.remove('hidden');
  const d = S.entryData || {};
  $('entryName').textContent = d.name || key;
  $('entryKey').textContent = `${S.dom} · ${key}`;
  const kc = $('entryKind');
  kc.className = 'chip kind ' + kindClass(d.kind) + (d.kind ? '' : ' hidden');
  kc.textContent = d.kind || '';
  $('saveStatus').textContent = '';
  renderIssues();
  renderEntry();
  renderList();
  updateStatusbar();
}

/* ═══════════════════════════ 条目渲染（三档） ═══════════════════════════ */
function renderEntry() {
  els('#modeSwitch button').forEach((b) => b.classList.toggle('on', b.dataset.mode === S.mode));
  const isForm = S.mode === 'form', isJson = S.mode === 'json';
  $('formHost').classList.toggle('hidden', !isForm);
  $('jsonHost').classList.toggle('hidden', !isJson);
  $('diffHost').classList.toggle('hidden', isForm || isJson);

  if (isJson) { $('jsonHost').value = JSON.stringify(S.entryData, null, 2); return; }
  if (S.mode === 'diff') { renderDiff(); return; }
  renderForm();
}

function renderForm() {
  const host = $('formHost');
  const primary = (S.schema && S.schema['x-primary']) || primaryOf();
  const def = S.schema && S.schema.$defs && S.schema.$defs[primary];
  if (!def || !window.SchemaForm) {
    host.innerHTML = '<p class="dim" style="padding:16px">该域没有可用 schema —— 请用「JSON」档编辑。</p>';
    return;
  }
  host.innerHTML = '';
  try {
    const h = window.SchemaForm.render(def, S.entryData, {
      onChange: () => markDirty(),
      onRerender: () => renderEntry(),
    });
    host.appendChild(h.el);
    if (S.validationErrors.length) window.SchemaForm.markErrors(host, S.validationErrors);
  } catch (e) {
    host.innerHTML = `<p class="dim" style="padding:16px">表单渲染失败（${esc(e.message)}）—— 请用「JSON」档。</p>`;
  }
}

function primaryOf() {
  const d = S.domains.find((x) => x.id === S.dom);
  return d ? (d.primary || '') : '';
}

/* ═══════════════════════════ 变更预览（客户端 diff） ═══════════════════════════ */
function flatten(v, path, out) {
  out = out || {};
  if (isObj(v)) {
    const keys = Object.keys(v);
    if (!keys.length) out[path] = '{}';
    keys.forEach((k) => flatten(v[k], path ? `${path}.${k}` : k, out));
  } else if (Array.isArray(v)) {
    if (!v.length) out[path] = '[]';
    v.forEach((x, i) => flatten(x, `${path}[${i}]`, out));
  } else {
    out[path] = v;
  }
  return out;
}
const fmtV = (v) => (v === undefined ? '—' : typeof v === 'string' ? v : JSON.stringify(v));

function diffRows() {
  const a = flatten(S.entryOrig || {}, ''), b = flatten(S.entryData || {}, '');
  const keys = Array.from(new Set([...Object.keys(a), ...Object.keys(b)])).sort();
  return keys.filter((k) => JSON.stringify(a[k]) !== JSON.stringify(b[k]))
    .map((k) => ({ path: k || '(根)', before: a[k], after: b[k] }));
}

function renderDiff() {
  const rows = diffRows();
  if (!rows.length) {
    $('diffHost').innerHTML = '<div class="diff-none">没有改动 —— 与磁盘上的内容一致</div>';
    return;
  }
  const MAX = 400;
  const body = rows.slice(0, MAX).map((r) => `<tr>
      <td class="d-path">${esc(r.path)}</td>
      <td class="d-before">${esc(fmtV(r.before))}</td>
      <td class="d-after">${esc(fmtV(r.after))}</td>
    </tr>`).join('');
  $('diffHost').innerHTML = `
    <div class="sim-sec" style="margin-top:0">${rows.length} 处改动</div>
    <table class="diff"><thead><tr><th>字段</th><th>原值</th><th>新值</th></tr></thead>
    <tbody>${body}</tbody></table>
    ${rows.length > MAX ? `<div class="diff-more">… 还有 ${rows.length - MAX} 处未显示</div>` : ''}`;
}

/* ═══════════════════════════ 脏标记 / 校验问题 ═══════════════════════════ */
function markDirty() {
  S.dirty = true;
  if (S.entryKey) S.dirtyKeys.add(S.entryKey);
  $('dirtyFlag').classList.remove('hidden');
  $('btnSave').disabled = false;
  refreshDirtyUI();
}

/* 轻量刷新「未保存」相关 UI（不做整表重渲染，避免大列表逐键卡顿） */
function refreshDirtyUI() {
  const row = el(`#entryList .entry-row[data-key="${(S.entryKey || '').replace(/"/g, '\\"')}"]`);
  if (row) {
    const tail = row.querySelector('.er-tail');
    const has = !!tail.querySelector('.er-dirty');
    if (S.entryKey && S.dirtyKeys.has(S.entryKey) && !has) {
      tail.insertAdjacentHTML('beforeend', '<span class="er-dirty" title="有未保存改动"></span>');
    } else if ((!S.entryKey || !S.dirtyKeys.has(S.entryKey)) && has) {
      tail.querySelector('.er-dirty').remove();
    }
  }
  const chip = el('#filterRow .chip[data-filter="dirty"]');
  if (chip) chip.textContent = '● 未保存' + (S.dirtyKeys.size ? ` ${S.dirtyKeys.size}` : '');
  updateStatusbar();
}

function renderIssues() {
  const box = $('issues');
  const errs = S.validationErrors || [];
  if (!errs.length) { box.classList.add('hidden'); box.innerHTML = ''; return; }
  box.className = 'issues';
  box.innerHTML = `
    <div class="issues-head">
      <b>⚠ ${errs.length} 个校验问题</b>
      <span class="dim">保存会被拦下</span>
      <button class="btn ghost sm" id="btnFixFirst">定位到第一个 ▸</button>
    </div>
    <ul>${errs.map((e) => `<li>${esc(e)}</li>`).join('')}</ul>`;
  box.classList.remove('hidden');
  $('btnFixFirst').onclick = jumpToFirstError;
}

function jumpToFirstError() {
  if (S.mode !== 'form') { S.mode = 'form'; renderEntry(); }
  const p = String((S.validationErrors[0] || '').split(':')[0] || '').replace(/^\./, '');
  if (!p) return;
  const node = el(`.field[data-path="${p.replace(/"/g, '\\"')}"]`, $('formHost'));
  if (node) {
    node.scrollIntoView({ block: 'center', behavior: 'smooth' });
    node.style.transition = 'background 400ms';
    node.style.background = 'var(--err-dim)';
    setTimeout(() => { node.style.background = ''; }, 900);
  } else {
    toast('该字段未在表单中渲染，请用 JSON 档检查：' + p, 'warn');
  }
}

/* ═══════════════════════════ 保存 / 删除 / 新建 ═══════════════════════════ */
async function save() {
  if (!S.entryKey) return;
  if (S.mode === 'json') {
    try { S.entryData = JSON.parse($('jsonHost').value); }
    catch (e) { toast('JSON 语法错误：' + e.message, 'bad'); return; }
  }
  $('saveStatus').textContent = '保存中…';
  const r = await api('PUT', `${dPath(S.dom)}/${encodeURIComponent(S.entryKey)}`, { data: S.entryData });
  if (r.status === 422) {
    S.validationErrors = ((r.json.validation || {}).errors) || [];
    renderIssues();
    if (S.mode === 'form') window.SchemaForm.markErrors($('formHost'), S.validationErrors);
    $('saveStatus').textContent = '校验未通过，未写入';
    $('saveStatus').className = 'save-status bad';
    toast('校验未通过，未写入', 'bad');
    return;
  }
  if (!r.ok) {
    $('saveStatus').textContent = '保存失败';
    $('saveStatus').className = 'save-status bad';
    toast((r.json && r.json.message) || '保存失败', 'bad');
    return;
  }
  S.dirty = false; S.entryOrig = clone(S.entryData); S.validationErrors = [];
  S.dirtyKeys.delete(S.entryKey);
  $('dirtyFlag').classList.add('hidden');
  $('btnSave').disabled = true;
  $('saveStatus').textContent = '已保存 ' + new Date().toLocaleTimeString('zh-CN', { hour12: false });
  $('saveStatus').className = 'save-status ok';
  renderIssues();
  toast('已保存 ' + S.entryKey, 'ok');
  await refreshPkg(); await loadDomain(S.dom);
}

async function del() {
  if (!S.entryKey) return;
  if (!confirm(`删除条目 ${S.entryKey}？\n此操作直接改 JSON 文件，不可撤销。`)) return;
  const r = await api('DELETE', `${dPath(S.dom)}/${encodeURIComponent(S.entryKey)}`);
  if (!r.ok) { toast('删除失败', 'bad'); return; }
  toast('已删除 ' + S.entryKey, 'ok');
  closeEntry();
  await refreshPkg(); await loadDomain(S.dom);
}

async function add() {
  const key = prompt('新条目的 key（英文/下划线，如 sk_fire_ball）：');
  if (!key) return;
  const name = prompt('显示名（name）：', key) || key;
  const data = { name, kind: (S.dom === 'skills' ? '物理' : ''), lv: 1, desc: '' };
  const r = await api('PUT', `${dPath(S.dom)}/${encodeURIComponent(key)}`, { data });
  if (!r.ok) {
    S.validationErrors = ((r.json || {}).validation || {}).errors || [];
    toast('新建失败：' + ((r.json || {}).message || ''), 'bad');
    return;
  }
  toast('已新建 ' + key, 'ok');
  await refreshPkg(); await loadDomain(S.dom); await openEntry(key);
}

/* ═══════════════════════════ 包设置 ═══════════════════════════ */
const isSettings = () => !$('settings').classList.contains('hidden');

function openSettings() {
  if (S.dirty && !confirmLeave()) return;
  $('editor').classList.add('hidden');
  $('editorEmpty').classList.add('hidden');
  $('settings').classList.remove('hidden');
  renderSettingsForm();
  renderRail();
}

function renderSettingsForm() {
  const m = (S.pkg && S.pkg.manifest) || {};
  $('pkgDir').textContent = (S.pkg && S.pkg.dir) || '';
  $('pkgForm').innerHTML = `
    <label>包 id（目录名，创建后不可改）<input value="${esc(m.id || '')}" disabled></label>
    <label>显示名<input id="pkName" value="${esc(m.name || '')}"></label>
    <label>简介<input id="pkDesc" value="${esc(m.desc || '')}"></label>
    <label>引擎版本要求<input id="pkEngine" value="${esc(m.engine || '')}"></label>`;
}

async function savePkg() {
  const m = Object.assign({}, (S.pkg && S.pkg.manifest) || {}, {
    name: $('pkName').value, desc: $('pkDesc').value, engine: $('pkEngine').value,
  });
  const r = await api('PUT', `/api/package/${encodeURIComponent(S.pkgId)}/manifest`, { manifest: m });
  if (!r.ok) { toast('保存包清单失败', 'bad'); return; }
  toast('包清单已保存', 'ok');
  await refreshPkg(); await loadPackages();
}

/* ═══════════════════════════ 试跑抽屉 ═══════════════════════════ */
const simOpen = () => !$('simDrawer').classList.contains('hidden');

async function openSim() {
  $('simDrawer').classList.remove('hidden');
  const sel = $('simDomain');
  sel.innerHTML = S.domains.map((d) => `<option value="${esc(d.id)}">${d.icon} ${esc(d.label)}</option>`).join('');
  sel.value = S.dom;
  sel.onchange = fillSimSkills;
  await fillSimSkills();
  if (S.entryKey) $('simSkill').value = S.entryKey;
  $('simSub').textContent = S.entryKey ? `${S.dom} · ${S.entryKey}` : '';
}

async function fillSimSkills() {
  const dom = $('simDomain').value;
  const r = await api('GET', dPath(dom));
  const list = (r.json && r.json.entries) || [];
  $('simSkill').innerHTML = list.map((e) => `<option value="${esc(e.key)}">${esc(e.name)}</option>`).join('')
    || '<option value="">（该域没有条目）</option>';
}

async function runSim() {
  const dom = $('simDomain').value, key = $('simSkill').value;
  if (!key) { toast('先选一个条目', 'warn'); return; }
  // 当前条目（含未保存改动）直接送过去，看的就是手上这份
  let skill = null;
  if (dom === S.dom && key === S.entryKey && S.entryData) skill = S.entryData;
  else {
    const gr = await api('GET', `${dPath(dom)}/${encodeURIComponent(key)}`);
    skill = gr.json && gr.json.data;
  }
  $('simOut').innerHTML = '<div class="sim-idle">跑动中…<br><span class="dim">子进程起引擎 + 本游戏包</span></div>';
  $('btnRunSim').disabled = true;
  const r = await api('POST', `/api/package/${encodeURIComponent(S.pkgId)}/simulate`, {
    skill, skill_lv: +$('simSkillLv').value, seed: +$('simSeed').value,
    attacker: { class_name: $('simClass').value, level: +$('simLevel').value },
    defender: { def: +$('simDef').value, mdef: +$('simMdef').value, hp: +$('simHp').value },
  });
  $('btnRunSim').disabled = false;
  const j = r.json || {};
  if (!j.ok) { renderSimError(j); return; }

  const dmg = j.damage != null ? Number(j.damage).toLocaleString('zh-CN') : '—';
  const hp = j.hp || {};
  const logs = j.logs || [];
  const events = j.events || [];
  $('simOut').innerHTML = `
    <div class="sim-hero">
      <div class="sim-dmg">${esc(dmg)}</div>
      <div class="sim-dmg-cap">对目标造成伤害</div>
      ${j.heal ? `<div class="sim-heal">＋ 治疗 ${esc(j.heal)}</div>` : ''}
    </div>
    <div class="sim-grid">
      <div class="sim-k">目标血量</div>
      <div class="sim-v">${esc(Number(hp.target_before).toLocaleString('zh-CN'))} → ${esc(Number(hp.target_after).toLocaleString('zh-CN'))}</div>
      <div class="sim-k">施法者</div><div class="sim-v">${esc(JSON.stringify(j.attacker || {}))}</div>
    </div>
    <div class="sim-sec">事件流</div>
    <div class="ev-chips">${events.length
      ? events.map((e) => `<span class="ev-chip" title="${esc(JSON.stringify(e.ctx || {}))}">${esc(e.event)}</span>`).join('')
      : '<span class="dim">（无）</span>'}</div>
    <div class="sim-sec">日志 ${logs.length ? `(${logs.length})` : ''}</div>
    <div class="sim-logs">${logs.length
      ? logs.map((l) => `<div class="sim-log ${/伤害|倒下|💥/.test(l) ? 'hl' : ''}">${esc(l)}</div>`).join('')
      : '<span class="dim">（无）</span>'}</div>`;
}

function renderSimError(j) {
  const tb = j.traceback || j.stdout || '';
  $('simOut').innerHTML = `
    <div class="sim-err">
      <div class="sim-err-msg">✕ 试跑失败${j.stage ? `<span class="sim-err-stage">${esc(j.stage)}</span>` : ''}</div>
      <div class="mono" style="font-size:11.5px;color:var(--fg-1)">${esc(j.message || '')}</div>
      ${tb ? `<details class="extra" open><summary>堆栈 / 输出</summary><div class="sim-tb">${esc(tb)}</div></details>` : ''}
    </div>`;
}

/* ═══════════════════════════ 命令面板 ═══════════════════════════ */
let PL = { items: [], sel: 0 };

function openPalette() {
  $('paletteOverlay').classList.remove('hidden');
  $('paletteInput').value = '';
  buildPalette();
  $('paletteInput').focus();
}
function closePalette() { $('paletteOverlay').classList.add('hidden'); }
const paletteOpen = () => !$('paletteOverlay').classList.contains('hidden');

function buildPalette() {
  const acts = [
    { ico: '💾', name: '保存当前条目', meta: 'Ctrl+S', run: save, need: () => !!S.entryKey && S.dirty },
    { ico: '✓', name: '全包校验', meta: 'validate', run: validateAll },
    { ico: '＋', name: '新建条目', meta: S.dom, run: add },
    { ico: '⚔', name: '试跑当前条目', meta: 'simulate', run: () => openSim().then(() => S.entryKey && ($('simSkill').value = S.entryKey)) },
    { ico: '↻', name: '重新读取当前域', meta: S.dom, run: () => loadDomain(S.dom) },
    { ico: '⚙', name: '打开包设置', meta: 'settings', run: openSettings },
  ];
  const domItems = S.domains.map((d) => ({
    ico: d.icon || '•', name: '切换到 ' + d.label, meta: d.id, run: () => switchDomain(d.id),
  }));
  const entries = S.entries.map((e) => ({
    ico: '·', name: e.name || e.key, meta: `${S.dom} · ${e.key}`,
    html: true, kind: e.kind, run: () => openEntry(e.key),
  }));
  PL.all = [
    { g: '动作', items: acts.filter((a) => !a.need || a.need()) },
    { g: '切换域', items: domItems },
    { g: '条目 · ' + (S.domains.find((d) => d.id === S.dom) || {}).label, items: entries },
  ];
  filterPalette('');
}

function filterPalette(q) {
  const ql = q.trim().toLowerCase();
  PL.items = [];
  PL.all.forEach((grp) => {
    const hit = grp.items.filter((it) => !ql
      || (it.name + ' ' + (it.meta || '')).toLowerCase().includes(ql));
    hit.slice(0, ql ? 40 : 8).forEach((it) => PL.items.push({ ...it, g: grp.g }));
  });
  PL.sel = 0;
  renderPalette(ql);
}

function renderPalette(q) {
  if (!PL.items.length) {
    $('paletteList').innerHTML = '<div class="pl-empty">没有匹配项</div>';
    return;
  }
  let html = '', lastG = null;
  PL.items.forEach((it, i) => {
    if (it.g !== lastG) { html += `<div class="pl-group">${esc(it.g)}</div>`; lastG = it.g; }
    const nm = q ? esc(it.name).replace(new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'ig'), '<mark>$1</mark>') : esc(it.name);
    html += `<div class="pl-item ${i === PL.sel ? 'on' : ''}" data-i="${i}">
      <span class="pl-ico">${it.ico || '·'}</span>
      <span class="pl-name">${nm}${it.kind ? ` <span class="chip kind ${kindClass(it.kind)}">${esc(it.kind)}</span>` : ''}</span>
      <span class="pl-meta">${esc(it.meta || '')}</span></div>`;
  });
  $('paletteList').innerHTML = html;
  els('#paletteList .pl-item').forEach((n) => {
    n.onmouseenter = () => { PL.sel = +n.dataset.i; renderPalette(q); };
    n.onclick = () => runPalette();
  });
  const cur = el('#paletteList .pl-item.on');
  if (cur) cur.scrollIntoView({ block: 'nearest' });
}

function runPalette() {
  const it = PL.items[PL.sel];
  if (!it) return;
  closePalette();
  setTimeout(() => it.run(), 0);
}

/* ═══════════════════════════ 校验 / 状态栏 ═══════════════════════════ */
async function validateAll() {
  if (!S.pkgId) return;
  toast('校验中…', '');
  const r = await api('POST', `/api/package/${encodeURIComponent(S.pkgId)}/validate`);
  const j = r.json || {};
  if (j.ok) { toast('全包校验通过 ✓', 'ok'); await refreshPkg(); return; }
  const n = (j.problems || []).reduce((a, p) => a + p.invalid.length, 0);
  toast(`全包校验：${n} 个条目有问题（域栏角标会标 !）`, 'bad');
  await refreshPkg();
  await loadDomain(S.dom);
}

function updateStatusbar() {
  const bad = (S.status.invalid || []).length;
  const dn = S.dirtyKeys.size;
  $('sbDirty').textContent = dn ? `● ${dn} 条有未保存改动` : '';
  $('sbDirty').className = 'sb-item' + (dn ? ' warn' : '');
  $('sbBad').textContent = bad ? `⚠ ${bad} 条待修` : '';
  $('sbBad').className = 'sb-item' + (bad ? ' bad' : '');
  const eng = ((S.pkg && S.pkg.manifest) || {}).engine || '';
  $('sbEngine').textContent = eng ? `引擎 ${eng}` : '';
  $('sbPath').textContent = (S.pkg && S.pkg.dir) || $('sbPath').textContent;
}

/* ═══════════════════════════ 外观（主题系统，实现在 theme.js） ═══════════════════════════ */
const TH = () => window.SETheme;

const themeOpen = () => !$('themeOverlay').classList.contains('hidden');
const closeTheme = () => $('themeOverlay').classList.add('hidden');
function openTheme() { closePkgMenu(); renderThemeDialog(); $('themeOverlay').classList.remove('hidden'); }

/* 单个预设卡（色块条预览 + 名称 + 模式标签） */
function presetCard(pr, curId) {
  const base = TH().MODE_BASE[pr.mode];
  const t = Object.assign({}, base, pr.tokens);
  const sw = [t.bg1, t.bg3, t.accent, t.fg1, t.err].map((c) => `<i style="background:${c}"></i>`).join('');
  const custom = pr.id === 'custom';
  const on = curId === pr.id;
  const label = custom ? `${pr.name}` : pr.name;
  const tags = custom ? '你自己的' : (pr.tags || '');
  return `<div class="preset-card ${on ? 'on' : ''}" data-preset="${esc(pr.id)}" title="${esc(tags)}">
      <div class="preset-swatches">${sw}</div>
      <div class="preset-name">${esc(label)}<span class="preset-mode">${custom ? '✎' : (pr.mode === 'light' ? '☀' : '🌙')}</span></div>
    </div>`;
}

function renderThemeDialog() {
  const st = TH().state();
  const dark = TH().PRESETS.filter((p) => p.mode === 'dark');
  const light = TH().PRESETS.filter((p) => p.mode === 'light');

  // 模式 seg
  els('#themeModeSwitch button').forEach((b) => {
    const on = b.dataset.follow ? st.follow : (!st.follow && (b.dataset.mode === st.modePref));
    b.classList.toggle('on', !!on);
  });

  // 预设卡（每个模式一组，末尾各放一张「自定义」）
  $('presetDark').innerHTML = dark.map((p) => presetCard(p, st.presetDark)).join('')
    + presetCard({ id: 'custom', name: '自定义', mode: 'dark' }, st.presetDark);
  $('presetLight').innerHTML = light.map((p) => presetCard(p, st.presetLight)).join('')
    + presetCard({ id: 'custom', name: '自定义', mode: 'light' }, st.presetLight);
  els('#presetDark .preset-card').forEach((n) => n.onclick = () => { TH().update({ presetId: n.dataset.preset }); renderThemeDialog(); });
  els('#presetLight .preset-card').forEach((n) => n.onclick = () => { TH().update({ presetId: n.dataset.preset }); renderThemeDialog(); });

  // 强调色快选
  const acc = TH().ACCENT_CHOICES;
  $('accentPicker').innerHTML =
    `<button class="chip ${st.accent === 'preset' ? 'on' : ''}" data-accent="preset" title="用当前预设自带的强调色">随主题</button>`
    + Object.keys(acc).map((k) =>
      `<button class="ap-dot ${st.accent === k ? 'on' : ''}" data-accent="${k}" title="${esc(acc[k].name)}"
         style="--dot:${acc[k][st.mode]}"></button>`).join('');
  els('#accentPicker [data-accent]').forEach((d) => d.onclick = () => {
    TH().update({ accent: d.dataset.accent }); renderThemeDialog();
  });
  $('accentColor').value = TH().normHex(st.accentHex) || TH().normHex(TH().tokens().accent);

  // 自定义字段（当前生效值）
  const tk = TH().tokens();
  $('customGrid').innerHTML = TH().EDITABLE.map((f) =>
    `<div class="th-field"><span title="${esc(f.label)}">${esc(f.label)}</span>
      <input type="color" data-token="${f.k}" value="${TH().normHex(tk[f.k]) || '#000000'}"></div>`).join('');
  els('#customGrid input[data-token]').forEach((inp) => {
    inp.oninput = () => TH().update({ token: { k: inp.dataset.token, v: inp.value } });
    inp.onchange = () => renderThemeDialog();
  });

  // 标题 / 提示
  const p = TH().PRESETS.find((x) => x.id === st.presetId);
  const pname = st.presetId === 'custom' ? '自定义' : (p ? p.name : st.presetId);
  $('themeNow').textContent = `${st.mode === 'light' ? '浅色' : '深色'} · ${pname}${st.follow ? ' · 跟随系统' : ''}`;
  $('themeHint').textContent = st.follow
    ? `跟随系统：当前系统为${TH().sysLight() ? '浅色' : '深色'}`
    : `配色保存在本机浏览器（localStorage），换设备不跟随`;
  $('themeIco').textContent = st.mode === 'light' ? '☀️' : '🌙';
}

/* 主题按钮图标随系统变化（跟随模式下） */
function refreshThemeIcon() {
  const st = TH().state();
  const ico = $('themeIco');
  if (ico) ico.textContent = st.mode === 'light' ? '☀️' : '🌙';
}

/* ═══════════════════════════ 可拖拽分栏 ═══════════════════════════ */
function restoreLayout() {
  const w = +localStorage.getItem('fe.listW');
  if (w >= 220 && w <= 520) document.documentElement.style.setProperty('--list-w', w + 'px');
  const d = +localStorage.getItem('fe.drawerW');
  if (d >= 320 && d <= 720) document.documentElement.style.setProperty('--drawer-w', d + 'px');
}

function initSplitters() {
  const bind = (node, varName, key, min, max, fromRight) => {
    node.onmousedown = (ev) => {
      ev.preventDefault();
      node.classList.add('dragging');
      const startX = ev.clientX;
      const cur = parseInt(getComputedStyle(document.documentElement).getPropertyValue(varName)) || 0;
      const move = (e) => {
        const delta = fromRight ? startX - e.clientX : e.clientX - startX;
        const v = Math.max(min, Math.min(max, cur + delta));
        document.documentElement.style.setProperty(varName, v + 'px');
      };
      const up = () => {
        node.classList.remove('dragging');
        document.removeEventListener('mousemove', move);
        document.removeEventListener('mouseup', up);
        localStorage.setItem(key, parseInt(getComputedStyle(document.documentElement).getPropertyValue(varName)));
      };
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', up);
    };
  };
  bind($('sp1'), '--list-w', 'fe.listW', 220, 520, false);
  // sp2 在列表与编辑器之间；抽屉宽度用右侧分隔（此处复用列表右边界）
  $('sp2').onmousedown = null;
}

/* ═══════════════════════════ 键盘 ═══════════════════════════ */
function moveKb(delta) {
  const rows = visibleEntries();
  if (!rows.length) return;
  S.kb = Math.max(0, Math.min(rows.length - 1, (S.kb < 0 ? 0 : S.kb + delta)));
  const key = rows[S.kb].key;
  if (key !== S.entryKey) openEntry(key);
  renderList();
}

function initKeys() {
  document.addEventListener('keydown', (e) => {
    const mod = e.ctrlKey || e.metaKey;
    const inField = /^(INPUT|TEXTAREA|SELECT)$/.test((e.target.tagName || ''));

    if (mod && e.key.toLowerCase() === 'k') { e.preventDefault(); paletteOpen() ? closePalette() : openPalette(); return; }
    if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); if (S.entryKey && S.dirty) save(); return; }
    if (mod && e.key === 'Enter') { e.preventDefault(); openSim(); return; }
    if (e.key === 'Escape') {
      if (paletteOpen()) return closePalette();
      if (themeOpen()) return closeTheme();
      if (S.pkgOpen) return closePkgMenu();
      if (simOpen()) return $('simDrawer').classList.add('hidden');
      if (inField) return e.target.blur();
      return;
    }
    if (paletteOpen()) {
      if (e.key === 'ArrowDown') { e.preventDefault(); PL.sel = Math.min(PL.items.length - 1, PL.sel + 1); renderPalette($('paletteInput').value.trim().toLowerCase()); }
      if (e.key === 'ArrowUp') { e.preventDefault(); PL.sel = Math.max(0, PL.sel - 1); renderPalette($('paletteInput').value.trim().toLowerCase()); }
      if (e.key === 'Enter') { e.preventDefault(); runPalette(); }
      return;
    }
    if (e.altKey && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      e.preventDefault();
      const i = S.domains.findIndex((d) => d.id === S.dom);
      const n = S.domains.length;
      if (n) switchDomain(S.domains[(i + (e.key === 'ArrowDown' ? 1 : -1) + n) % n].id);
      return;
    }
    if (!inField && e.key === '/') { e.preventDefault(); $('search').focus(); return; }
    if (!inField && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      e.preventDefault(); moveKb(e.key === 'ArrowDown' ? 1 : -1); return;
    }
    if (!inField && e.key === 'Enter' && S.entryKey) { e.preventDefault(); openSim(); }
  });
}

/* ═══════════════════════════ 事件绑定 ═══════════════════════════ */
window.addEventListener('DOMContentLoaded', () => {
  initSplitters();
  initKeys();

  // 顶栏
  $('btnPkgMenu').onclick = (e) => { e.stopPropagation(); S.pkgOpen ? closePkgMenu() : openPkgMenu(); };
  document.addEventListener('click', (e) => {
    if (S.pkgOpen && !e.target.closest('.pkg-switch')) closePkgMenu();
  });
  $('btnPalette').onclick = openPalette;
  $('btnValidate').onclick = validateAll;
  $('btnSettings').onclick = openSettings;

  // 外观（主题系统）
  $('btnAppearance').onclick = openTheme;
  $('btnThemeClose').onclick = closeTheme;
  $('themeOverlay').onclick = (e) => { if (e.target === $('themeOverlay')) closeTheme(); };
  els('#themeModeSwitch button').forEach((b) => (b.onclick = () => {
    if (b.dataset.follow) TH().update({ follow: true });
    else TH().update({ follow: false, modePref: b.dataset.mode });
    renderThemeDialog();
  }));
  $('accentColor').oninput = () => TH().update({ accentHex: $('accentColor').value });
  $('accentColor').onchange = () => renderThemeDialog();
  $('btnResetCustom').onclick = () => {
    TH().update({ resetCustom: true, presetId: TH().state().mode === 'light' ? 'latte' : 'mocha' });
    renderThemeDialog();
    toast('已恢复该模式的预设配色', 'ok');
  };
  $('btnResetAll').onclick = () => {
    TH().update({ resetAll: true });
    renderThemeDialog();
    toast('已恢复默认外观', 'ok');
  };

  // 列表
  $('search').oninput = () => { S.kb = -1; renderList(); };
  $('btnSort').onclick = () => {
    S.sort = { kind: 'name', name: 'key', key: 'kind' }[S.sort];
    toast('排序：' + { kind: '按类别', name: '按名称', key: '按 key' }[S.sort], '');
    renderList();
  };
  $('btnAdd').onclick = add;
  els('#filterRow .chip').forEach((c) => (c.onclick = () => {
    S.filter = c.dataset.filter;
    els('#filterRow .chip').forEach((x) => x.classList.toggle('on', x === c));
    renderList();
  }));

  // 编辑器
  els('#modeSwitch button').forEach((b) => (b.onclick = () => {
    if (S.mode === 'json' && b.dataset.mode !== 'json' && $('jsonHost').value && S.entryData) {
      try { S.entryData = JSON.parse($('jsonHost').value); } catch (e) { toast('JSON 有误，未同步到表单', 'bad'); }
    }
    S.mode = b.dataset.mode;
    renderEntry();
  }));
  $('jsonHost').oninput = markDirty;
  $('btnSave').onclick = save;
  $('btnDel').onclick = del;
  $('btnSim').onclick = openSim;
  $('btnRunSim').onclick = runSim;
  $('btnSimClose').onclick = () => $('simDrawer').classList.add('hidden');
  $('btnSavePkg').onclick = savePkg;

  // 命令面板
  $('paletteInput').oninput = () => filterPalette($('paletteInput').value);
  $('paletteOverlay').onclick = (e) => { if (e.target === $('paletteOverlay')) closePalette(); };

  window.addEventListener('beforeunload', (e) => {
    if (S.dirty || S.dirtyKeys.size) { e.preventDefault(); e.returnValue = ''; }
  });

  boot();
});
