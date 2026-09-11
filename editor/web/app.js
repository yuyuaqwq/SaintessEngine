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
  actions: [],                   // 机制动作清单（AST 扫源码；引擎内置 + 包内）
  actionByName: {},              // name → 动作
  glossary: { '*': {} },         // 字段词典：域 → {字段: {zh, note, wiki}}
  isNew: false,                  // 当前条目是「新建草稿」（还没落盘）
  friendly: [],                  // 服务端返回的中文可读报错（保存/新建被拦时）
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
  await loadGlossary();
  await loadPackages();
  renderRail();
  await loadWikiTree();
  if (S.pkgs.length) await selectPkg(S.pkgs[0].id);
  else showEmptyPkg();
  routeFromHash();                 // ★ 放在选包之后：selectPkg 会切域（顺手隐藏文档面板），
                                   //   深链 #/wiki/... 若先跑就会被盖掉，刷新后跳不回那一页
}

/* ═══════════════════════════ 字段词典 ═══════════════════════════
   schema 只说类型，说不清「谁读 / 写了会不会静默不生效」。词典把每个字段补成
   中文名 + 注脚 + 文档直链；注脚里带 ⚠ 的（无消费者/未核实）在表单里显式标出来。
   ═══════════════════════════════════════════════════════════════════ */
async function loadGlossary() {
  const r = await api('GET', '/api/glossary');
  S.glossary = (r.json && r.json.domains) || { '*': {} };
}

/* 字段 → 词典条目（域内精确 → 域内叶名 → 通用叶名） */
function gloss(path) {
  const p = String(path || '');
  if (!p) return null;
  const leaf = p.split('.').pop();
  const tbl = S.glossary || {};
  const dom = tbl[S.dom] || {};
  return dom[p] || dom[leaf] || (tbl['*'] || {})[leaf] || null;
}
const glossZh = (k) => { const g = gloss(k); return g && g.zh ? g.zh : ''; };
const glossIsWarn = (g) => !!(g && /无消费者|未核实|不生效/.test(g.note || ''));
/* 词典注脚里带轻量 markdown（**加粗** / `代码`）—— 先转义再转标签，避免把记号当字面量显示 */
function mdInline(s) {
  return esc(s).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
               .replace(/`([^`]+)`/g, '<code>$1</code>');
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
    + `<button class="rail-item ${isWiki() ? 'on' : ''}" data-nav="wiki" title="引擎文档（wiki）">
         <span class="ri-icon">📖</span><span class="ri-label">文档</span></button>`
    + `<button class="rail-item ${isSettings() ? 'on' : ''}" data-nav="settings" title="包设置">
         <span class="ri-icon">⚙</span><span class="ri-label">设置</span></button>`;
  els('#rail .rail-item').forEach((b) => {
    b.onclick = () => {
      if (b.dataset.nav === 'settings') return openSettings();
      if (b.dataset.nav === 'wiki') return openWiki();
      switchDomain(b.dataset.dom);
    };
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
  await loadActions(false);          // 动作清单随包（包内可有 mech/）
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
  $('wiki').classList.add('hidden');
  // ⚠️ 必须走 closeEntry()（它会清 S.entryKey）—— 曾经的 bug：切域只隐藏面板、
  //    不清 entryKey，切回来后点原来那条会被 openEntry 的「同一条」短路掉，毫无反馈。
  closeEntry();
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
  S.isNew = false; S.friendly = [];
  S.validationErrors = [];
  $('editor').classList.add('hidden');
  $('editorEmpty').classList.remove('hidden');
  $('issues').classList.add('hidden');
  $('saveStatus').textContent = '';
  renderList();
}

async function openEntry(key) {
  // ⚠️ 判据必须是「面板真的在显示同一条」——只看 S.entryKey 会在
  //    「切域 / 开设置后再回来」时把点击短路掉（点了没任何反应）。
  if (key === S.entryKey && !$('editor').classList.contains('hidden')) return;
  if (key === S.entryKey && S.isNew) return;      // 新建草稿正在编辑，重新载入会丢输入
  if (S.dirty && !confirmLeave()) return;
  const r = await api('GET', `${dPath(S.dom)}/${encodeURIComponent(key)}`);
  if (!r.ok) { toast((r.json && r.json.message) || '读取条目失败', 'bad'); return; }
  S.entryKey = key;
  S.entryData = r.json.data;
  S.entryOrig = clone(r.json.data);
  S.schema = r.json.schema;
  S.validationErrors = r.json.errors || [];
  S.isNew = false;
  S.friendly = [];
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
    // 帮助文字可能因网格窄而被 clamp → 补 title 提示（schema_form.js 不动）
    els('.help', host).forEach((n) => { if (!n.title) n.title = n.textContent.trim(); });
    enhanceFields();                // 字段词典：中文名 + 注脚 + 文档直链
    enhanceActionFields();          // E4：动作名联想 + 参数提示
    if (S.validationErrors.length) window.SchemaForm.markErrors(host, S.validationErrors);
  } catch (e) {
    host.innerHTML = `<p class="dim" style="padding:16px">表单渲染失败（${esc(e.message)}）—— 请用「JSON」档。</p>`;
  }
}

function primaryOf() {
  const d = S.domains.find((x) => x.id === S.dom);
  return d ? (d.primary || '') : '';
}

/* ═══════════════════════════ 机制动作（E4：动作联表 + 参数提示） ═══════════════════════════
   设计：**用 datalist 增强既有 input，而不是替换元素** —— schema_form.js 的事件链
   （onChange/onRerender）一行不动，联想只是给 input 加 `list` 属性。
   选中动作后，在其下方显示「该动作实际消费的参数」（AST 从实现反推，不会漂移）。
   ══════════════════════════════════════════════════════════════════════════════ */
const FIELD_HINT = {
  action:  '机制动作（动词执行器）—— 从已注册的真实动作里选',
};

async function loadActions(fresh) {
  if (!S.pkgId && !fresh) return;
  const q = `?pkg=${encodeURIComponent(S.pkgId || '')}${fresh ? '&fresh=1' : ''}`;
  const r = await api('GET', '/api/actions' + q);
  const j = r.json || {};
  S.actions = j.actions || [];
  S.actionByName = {};
  S.actions.forEach((a) => { S.actionByName[a.name] = a; });
  if (fresh) toast(`动作清单已刷新（${S.actions.length} 个）`, 'ok');
}

/* 把某个字段的 input 变成「带联想的输入框」（不改元素、不动事件） */
function attachDatalist(fieldEl, listId, values) {
  const inp = fieldEl.querySelector('input.ctl, textarea.ctl');
  if (!inp) return null;
  let dl = document.getElementById(listId);
  if (!dl) {
    dl = document.createElement('datalist');
    dl.id = listId;
    document.body.appendChild(dl);
  }
  dl.innerHTML = values.map((v) => `<option value="${esc(v)}"></option>`).join('');
  inp.setAttribute('list', listId);
  return inp;
}

/* 表单渲染后的「动作字段」增强 */
function enhanceActionFields() {
  const host = $('formHost');
  if (!host || !S.actions.length) return;
  els('.field', host).forEach((f) => {
    const path = f.dataset.path || '';
    const leaf = path.split('.').pop();
    // ① 动作名字段：加联想
    if (leaf === 'action' || leaf === 'actions') {
      const inp = attachDatalist(f, 'fwActionNames', S.actions.map((a) => a.name));
      if (inp) {
        f._lastAction = inp.value.trim();
        renderActionHint(f, inp.value);
        // ⚠️ 只在**动作名真的变了**时重渲染参数区 —— 否则每次按键都重建 DOM 会
        //   打断用户正在参数框里的输入（实测焦点被抢）。参数框输入本身不重渲染。
        inp.addEventListener('input', () => {
          if (f._lastAction === inp.value.trim()) return;
          f._lastAction = inp.value.trim();
          renderActionHint(f, inp.value);
        });
      }
    }
    // ② 其它已知字段：补一条说明
    else if (FIELD_HINT[leaf]) {
      const lab = f.querySelector('.f-label');
      if (lab && !lab.querySelector('.fh-tip')) {
        const tip = document.createElement('span');
        tip.className = 'fh-tip';
        tip.textContent = 'ⓘ ' + FIELD_HINT[leaf];
        lab.appendChild(tip);
      }
    }
  });
}

/* 动作参数区 —— **可直接编辑**（关键：动作参数多数不在 schema 里，
   schema_form 渲染不到它们；若只在提示里列名字，补的键就成了看不见的幽灵数据） */
function renderActionHint(fieldEl, name) {
  let box = fieldEl.querySelector('.action-hint');
  if (!box) {
    box = document.createElement('div');
    box.className = 'action-hint';
    fieldEl.appendChild(box);
  }
  const a = S.actionByName[(name || '').trim()];
  if (!a) {
    box.className = 'action-hint' + (name ? ' miss' : ' empty');
    box.innerHTML = name
      ? `<span class="ah-warn">✕ 未找到动作 <b>${esc(name)}</b> —— 检查拼写，或确认它已在代码里注册</span>`
      : '<span class="ah-dim">从已注册动作里选一个（支持输入过滤）</span>';
    return;
  }
  const ps = a.params || [];
  box.className = 'action-hint ok';
  box.innerHTML = `
    <div class="ah-head">
      <span class="ah-src ${a.source === 'engine' ? 'eng' : 'pkg'}">${a.source === 'engine' ? '框架内置' : '本包动作'}</span>
      <span class="mono dim">${esc(a.file)}:${a.line}</span>
    </div>
    ${a.doc ? `<div class="ah-doc">${esc(a.doc)}</div>` : ''}
    ${ps.length ? `<div class="ah-sub">读这些参数${ps.some((x) => !inSchema(x.key)) ? '（不在 schema 里，下方直接填）' : ''}</div>
      <div class="ah-rows">${ps.map((x) => paramRow(a, x)).join('')}</div>` 
      : '<div class="ah-dim">该动作不读配置参数</div>'}`;

  // 绑定参数输入（写回 entryData）
  els('.ah-input', box).forEach((inp) => {
    inp.addEventListener('input', () => {
      const k = inp.dataset.key;
      const raw = inp.value;
      (S.entryData || {})[k] = coerce(raw, inp.dataset.type);
      markDirty();
      inp.classList.toggle('filled', raw !== '');
    });
    inp.addEventListener('change', () => {
      // 失去焦点时把推断类型的值回显（如 "1.50" → 1.5）
      const k = inp.dataset.key;
      const v = (S.entryData || {})[k];
      if (v !== undefined && v !== '') inp.value = typeof v === 'string' ? v : JSON.stringify(v);
    });
  });
  // 「见上方字段」跳转
  els('.ah-goto', box).forEach((el2) => (el2.onclick = () => {
    const f = el(`#formHost .field[data-path="${el2.dataset.path}"]`);
    if (f) { f.scrollIntoView({ block: 'center', behavior: 'smooth' }); f.style.transition = 'background 400ms'; f.style.background = 'var(--accent-dim)'; setTimeout(() => { f.style.background = ''; }, 900); }
  }));
}

/* 该键是否由 schema 渲染了（是则不在参数区重复给输入框） */
function inSchema(key) {
  return !!el(`#formHost .field[data-path="${String(key).replace(/"/g, '\\"')}"]`);
}

/* 用户输入 → 值（按推断类型收敛；空串保持空串，不猜） */
function coerce(raw, type) {
  if (raw === '') return '';
  if (type === 'number' || type === 'float') { const n = Number(raw); return Number.isFinite(n) ? n : raw; }
  if (type === 'int') { const n = parseInt(raw, 10); return Number.isFinite(n) ? n : raw; }
  if (type === 'bool') return !/^(false|0|no|否)$/i.test(raw.trim());
  if (type === 'array' || type === 'object') {
    try { return JSON.parse(raw); } catch (e) { return raw; }
  }
  return raw;
}

function paramRow(a, x) {
  const has = inSchema(x.key);
  const cur = (S.entryData || {})[x.key];
  const filled = cur !== undefined && cur !== null && cur !== '';
  const show = filled ? (typeof cur === 'string' ? cur : JSON.stringify(cur)) : '';
  const ph = x.default !== null && x.default !== undefined
    ? `默认 ${JSON.stringify(x.default)}` : (x.type === 'unknown' ? '值' : x.type);
  return `<div class="ah-row ${x.required ? 'req' : ''}">
    <span class="ah-key" title="${esc(x.hint || '')}">${esc(x.key)}${x.required ? '<b>*</b>' : ''}</span>
    ${has
      ? `<button class="ah-goto" data-path="${esc(x.key)}" title="该键由上方表单字段编辑">↗ 见上方字段</button>`
      : `<input class="ah-input ${filled ? 'filled' : ''}" data-key="${esc(x.key)}"
              data-type="${esc(x.type)}" value="${esc(show)}" placeholder="${esc(ph)}"
              spellcheck="false" autocomplete="off">`}
    <span class="ah-type">${esc(x.type)}</span>
  </div>`;
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
  // 必填体检实时跟着填：用户补上一个字段，清单里那一行立刻消失
  // （否则「到底还差什么」要等到按保存才知道 —— 这正是原来「不知道什么规则」的来源）
  if (!$('issues').classList.contains('hidden') || computeMissing().length) renderIssues();
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

/* 必填项体检（客户端，**只**按 schema.required + 空值判 —— 不猜业务规则） */
function primaryDefSchema() {
  const primary = (S.schema && S.schema['x-primary']) || primaryOf();
  return (S.schema && S.schema.$defs && S.schema.$defs[primary]) || null;
}
function computeMissing() {
  const def = primaryDefSchema();
  if (!def) return [];
  return (def.required || []).filter((k) => {
    const v = (S.entryData || {})[k];
    return v === undefined || v === null || (typeof v === 'string' && v.trim() === '');
  }).map((k) => ({ k, zh: glossZh(k), g: gloss(k) }));
}

function renderIssues() {
  const box = $('issues');
  const errs = S.validationErrors || [];
  const missing = computeMissing();
  if (!errs.length && !missing.length) { box.classList.add('hidden'); box.innerHTML = ''; return; }
  box.className = 'issues';

  let html = '';
  if (missing.length) {
    html += `<div class="issues-head"><b>⚠ 必填还没填（${missing.length} 项）</b>
      <span class="dim">保存会被拦下 —— 这就是「未通过」的规则</span></div>
      <ul class="issue-list">${missing.map((m) => `<li>
        <button class="btn ghost sm issue-jump" data-path="${esc(m.k)}">定位 ▸</button>
        <code>${esc(m.k)}</code>${m.zh ? ` <span class="gl-zh">${esc(m.zh)}</span>` : ''}
        <span class="issue-note">${m.g && m.g.note ? mdInline(m.g.note) : 'schema 必填项，不能为空'}</span></li>`).join('')}</ul>`;
  }
  if (errs.length) {
    const rows = S.friendly.length
      ? S.friendly
      : errs.map((e) => ({ path: String(e).split(':')[0].trim(), display: String(e) }));
    html += `<div class="issues-head"><b>⚠ schema 报错（${rows.length} 项）</b>
      <span class="dim">保存会被拦下</span></div>
      <ul class="issue-list">${rows.map((r) => `<li>
        ${r.path ? `<button class="btn ghost sm issue-jump" data-path="${esc(r.path)}">定位 ▸</button>` : ''}
        ${esc(r.display || r.raw || '')}
        ${r.wiki ? `<a class="issue-wiki" href="${esc(r.wiki)}" title="打开文档">📖 说明</a>` : ''}</li>`).join('')}</ul>`;
  }
  box.innerHTML = html;
  els('.issue-jump', box).forEach((b) => (b.onclick = () => jumpToPath(b.dataset.path)));
  els('.issue-wiki', box).forEach((a) => (a.onclick = (e) => {
    e.preventDefault(); openWikiRef(a.getAttribute('href'));
  }));
  box.classList.remove('hidden');
}

function jumpToPath(p) {
  if (!p) return;
  if (S.mode !== 'form') { S.mode = 'form'; renderEntry(); }
  const node = el(`.field[data-path="${String(p).replace(/"/g, '\\"')}"]`, $('formHost'));
  if (!node) { toast('该字段没在表单里渲染（可能在「其他字段」折叠区）：' + p, 'warn'); return; }
  node.scrollIntoView({ block: 'center', behavior: 'smooth' });
  node.style.transition = 'background 400ms';
  node.style.background = 'var(--err-dim)';
  setTimeout(() => { node.style.background = ''; }, 900);
  const inp = node.querySelector('input,select,textarea');
  if (inp) inp.focus({ preventScroll: true });
}

function jumpToFirstError() {
  const p = (S.friendly[0] || {}).path
    || String((S.validationErrors[0] || '').split(':')[0] || '').replace(/^\./, '');
  jumpToPath(p);
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
    const v = (r.json || {}).validation || {};
    S.validationErrors = v.errors || [];
    S.friendly = v.friendly || [];            // 服务端翻好的中文（带字段中文名）
    renderIssues();
    if (S.mode === 'form') window.SchemaForm.markErrors($('formHost'), S.validationErrors);
    $('saveStatus').textContent = '校验未通过，未写入';
    $('saveStatus').className = 'save-status bad';
    const first = S.friendly[0] || {};
    toast('未写入 —— ' + (first.display || '校验未通过（看编辑器上方的问题清单）'), 'bad');
    jumpToFirstError();
    return;
  }
  if (!r.ok) {
    $('saveStatus').textContent = '保存失败';
    $('saveStatus').className = 'save-status bad';
    toast((r.json && r.json.message) || '保存失败', 'bad');
    return;
  }
  const wasNew = S.isNew;
  S.dirty = false; S.entryOrig = clone(S.entryData); S.validationErrors = []; S.friendly = [];
  S.isNew = false;
  S.dirtyKeys.delete(S.entryKey);
  $('dirtyFlag').classList.add('hidden');
  $('btnSave').disabled = true;
  $('saveStatus').textContent = '已保存 ' + new Date().toLocaleTimeString('zh-CN', { hour12: false });
  $('saveStatus').className = 'save-status ok';
  renderIssues();
  toast((wasNew ? '已新建 ' : '已保存 ') + S.entryKey, 'ok');
  await refreshPkg(); await loadDomain(S.dom);
}

async function del() {
  if (!S.entryKey) return;
  if (S.isNew) { closeEntry(); toast('已放弃草稿 ' + S.entryKey, ''); return; }   // 草稿没落盘，直接丢
  if (!confirm(`删除条目 ${S.entryKey}？\n此操作直接改 JSON 文件，不可撤销。`)) return;
  const r = await api('DELETE', `${dPath(S.dom)}/${encodeURIComponent(S.entryKey)}`);
  if (!r.ok) { toast('删除失败', 'bad'); return; }
  toast('已删除 ' + S.entryKey, 'ok');
  closeEntry();
  await refreshPkg(); await loadDomain(S.dom);
}

async function add() {
  if (!S.pkgId) { toast('先在左上角选/新建一个游戏包', 'warn'); return; }
  if (S.dirty && !confirmLeave()) return;
  const key = prompt('新条目的 key（英文/下划线，如 sk_fire_ball）：');
  if (!key) return;
  if (S.entries.some((e) => e.key === key)) { toast(`已存在同 key 条目：${key}`, 'bad'); return; }
  const name = prompt('显示名（name）：', key) || key;

  /* ★ 不再「直接写盘」。
     旧做法：PUT 一条 desc:"" 的数据 → schema 的 minLength 把它拦下（422），
     前端却只弹一句「新建失败」，真实原因（desc 不能为空）被吞掉 ——
     用户只知道「一直未通过，不知道什么规则」。实测报错原文：
         desc: '' should be non-empty
     新做法：**草稿模式** —— 先把条目开在编辑器里，必填缺什么当场列出来，
     补全后按 Ctrl+S 才落盘（PUT 本身就是创建）。 */
  const r = await api('GET', `/api/schema/${S.dom}`);
  if (!r.ok) { toast('该域没有 schema，无法新建', 'bad'); return; }
  S.entryKey = key;
  S.entryData = { name, kind: (S.dom === 'skills' ? '物理' : ''), lv: 1, desc: '' };
  S.entryOrig = null;
  S.schema = r.json.schema;
  S.validationErrors = [];
  S.friendly = [];
  S.isNew = true;
  S.mode = 'form';
  $('settings').classList.add('hidden');
  $('wiki').classList.add('hidden');
  $('editorEmpty').classList.add('hidden');
  $('editor').classList.remove('hidden');
  $('entryName').textContent = name;
  $('entryKey').textContent = `${S.dom} · ${key}（新草稿）`;
  const kc = $('entryKind');
  kc.className = 'chip kind ' + kindClass(S.entryData.kind) + (S.entryData.kind ? '' : ' hidden');
  kc.textContent = S.entryData.kind || '';
  markDirty();
  $('saveStatus').textContent = '新建草稿 —— 补全下方必填项后 Ctrl+S 保存';
  $('saveStatus').className = 'save-status';
  renderIssues();
  renderEntry();
  renderList();
  toast('已开草稿：先把必填项补齐，再 Ctrl+S 落盘', '');
}

/* ═══════════════════════════ 包设置 ═══════════════════════════ */
const isSettings = () => !$('settings').classList.contains('hidden');

function openSettings() {
  if (S.dirty && !confirmLeave()) return;
  $('editor').classList.add('hidden');
  $('editorEmpty').classList.add('hidden');
  $('wiki').classList.add('hidden');
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

/* ═══════════════════════════ 字段词典增强（翻译 + 注脚 + 文档直链） ═══════════════════════════
   schema 表单只给「类型 + 一句 description」。这里给每个字段补三样：
     ① 中文名（挂在 label 后）
     ② ⓘ 注脚（谁读这个字段 / 写了会不会静默不生效 / 单位与坑）
     ③ 📖 文档直链（跳到 wiki 对应那处并高亮）
   注脚里带「无消费者 / 未核实」的字段，整块**标黄**：这类字段最坑（声明了不报错、不生效）。
   ══════════════════════════════════════════════════════════════════════════════════════ */
function enhanceFields() {
  const host = $('formHost');
  if (!host) return;
  els('.field', host).forEach((f) => {
    if (f.tagName === 'FIELDSET') return;              // 对象分组不挂
    const path = f.dataset.path || '';
    const g = gloss(path);
    if (!g) return;
    if (glossIsWarn(g)) f.classList.add('gl-warn');
    const lab = f.querySelector('.f-label');
    if (lab && g.zh && !lab.querySelector('.gl-zh')) {
      const s = document.createElement('span');
      s.className = 'gl-zh';
      s.textContent = '· ' + g.zh;
      lab.appendChild(s);
    }
    if (g.note && !f.querySelector('.gl-note')) {
      const tip = document.createElement('button');
      tip.type = 'button';
      tip.className = 'gl-tip';
      tip.textContent = 'ⓘ';
      tip.title = '字段注脚（语义 / 消费者 / 坑）';
      if (lab) lab.appendChild(tip);
      const box = document.createElement('div');
      box.className = 'gl-note hidden';
      box.innerHTML = `<div class="gl-note-text">${mdInline(g.note)}</div>
        ${g.wiki
          ? `<a class="gl-wiki" href="${esc(g.wiki)}">📖 打开文档：${esc((g.wiki.split('#')[0] || '').replace('wiki:', ''))}</a>`
          : '<span class="dim">该字段暂无可引用的文档页（注脚来自 schema / 源码核实）</span>'}`;
      tip.onclick = (e) => { e.preventDefault(); box.classList.toggle('hidden'); };
      f.appendChild(box);
      els('.gl-wiki', box).forEach((a) => (a.onclick = (e) => {
        e.preventDefault(); openWikiRef(a.getAttribute('href'));
      }));
    }
  });
}

/* ═══════════════════════════ 文档（引擎 wiki，编辑器内可读） ═══════════════════════════ */
const isWiki = () => !$('wiki').classList.contains('hidden');
const WIKI = { tree: [], groups: [], cur: null, triedMermaid: false };
const DEFAULT_PAGE = 'README.md';

async function loadWikiTree() {
  const r = await api('GET', '/api/wiki/tree');
  WIKI.tree = (r.json && r.json.pages) || [];
  WIKI.groups = (r.json && r.json.groups) || [];
}

function renderWikiNav() {
  const box = $('wikiNav');
  const q = ($('wikiSearch').value || '').trim();
  if (q.length >= 2) return;                                  // 搜索态由 renderWikiSearch 接管
  let html = '', last = null;
  WIKI.tree.forEach((p) => {
    if (p.group_label !== last) { html += `<div class="wk-group">${esc(p.group_label)}</div>`; last = p.group_label; }
    html += `<button class="wk-page ${p.path === WIKI.cur ? 'on' : ''}" data-path="${esc(p.path)}"
      title="${esc(p.path)}">${esc(p.title)}</button>`;
  });
  box.innerHTML = html;
  els('.wk-page', box).forEach((b) => (b.onclick = () => openWiki(b.dataset.path)));
}

async function renderWikiSearch(q) {
  const r = await api('GET', '/api/wiki/search?q=' + encodeURIComponent(q));
  const hits = (r.json && r.json.hits) || [];
  $('wikiNav').innerHTML = `<div class="wk-group">搜索「${esc(q)}」· ${hits.length} 处命中</div>`
    + (hits.length ? hits.map((h) => `<button class="wk-hit" data-path="${esc(h.path)}" data-line="${h.line}">
        <span class="wk-hit-page">${esc(h.title)}</span>
        <span class="wk-hit-line mono">:${h.line}</span>
        <span class="wk-hit-text mono">${esc(h.text)}</span></button>`).join('')
      : '<div class="wk-empty">没有命中</div>');
  els('.wk-hit', $('wikiNav')).forEach((b) => (b.onclick = async () => {
    await openWiki(b.dataset.path);
    jumpWikiText(q);          // ★ 用**搜索词**定位，不用命中行片段（片段含 markdown 记号，正文里不一定原样存在）
  }));
}

function renderWikiToc(toc) {
  const ps = (toc || []).filter((t) => t.level >= 2 && t.level <= 3);
  $('wikiToc').innerHTML = ps.length
    ? '<div class="wk-toc-title">本页目录</div>' + ps.map((t) =>
        `<a class="wk-toc-l${t.level}" href="#${esc(t.id)}" data-id="${esc(t.id)}">${esc(t.text)}</a>`).join('')
    : '';
  els('#wikiToc a').forEach((a) => (a.onclick = (e) => {
    e.preventDefault();
    const n = document.getElementById(a.dataset.id);
    if (n) n.scrollIntoView({ block: 'start', behavior: 'smooth' });
  }));
}

async function openWiki(path, findTerm) {
  const rel = path || WIKI.cur || DEFAULT_PAGE;
  const r = await api('GET', '/api/wiki/page?path=' + encodeURIComponent(rel));
  if (!r.ok) { toast((r.json && r.json.message) || '文档打开失败', 'bad'); return; }
  const j = r.json;
  WIKI.cur = j.path;
  $('editor').classList.add('hidden');
  $('editorEmpty').classList.add('hidden');
  $('settings').classList.add('hidden');
  $('wiki').classList.remove('hidden');
  $('wikiTitle').textContent = j.title;
  $('wikiPath').textContent = j.path;
  $('wikiGroup').textContent = j.group_label || '';
  $('wikiContent').innerHTML = `<nav class="wk-pager">
      ${j.prev ? `<a data-path="${esc(j.prev)}">‹ ${esc(j.prev_title)}</a>` : '<span></span>'}
      ${j.next ? `<a data-path="${esc(j.next)}" class="wk-next">${esc(j.next_title)} ›</a>` : '<span></span>'}
    </nav>` + j.html;
  renderWikiToc(j.toc);
  renderWikiNav();
  renderRail();
  els('#wikiContent .wk-pager a').forEach((a) => (a.onclick = () => openWiki(a.dataset.path)));
  els('#wikiContent a.wiki-link').forEach((a) => (a.onclick = (e) => {
    const href = a.getAttribute('href') || '';
    if (href.startsWith('#/wiki/')) { e.preventDefault(); openWiki(href.replace('#/wiki/', '')); }
  }));
  els('#wikiContent code.ref-code').forEach((c) => {
    c.onclick = () => openCodeRef(c.dataset.ref);
  });
  const hash = `#/wiki/${j.path}` + (findTerm ? `?find=${encodeURIComponent(findTerm)}` : '');
  if (location.hash !== hash) history.replaceState(null, '', hash);
  $('wikiContent').scrollTop = 0;
  window.scrollTo(0, 0);
  renderMermaid();
  if (findTerm) jumpWikiText(findTerm);
}

/* 在正文里找到第一处包含该词的节点 → 滚动 + 高亮（字段注脚的 deep link 用） */
function jumpWikiText(term) {
  const t = (term || '').trim();
  if (t.length < 2) return;
  const root = $('wikiContent');
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node = null;
  while (walker.nextNode()) {
    const n = walker.currentNode;
    if (n.nodeValue && n.nodeValue.includes(t) && n.parentElement
        && !/^(SCRIPT|STYLE)$/.test(n.parentElement.tagName)) { node = n; break; }
  }
  if (!node) { toast('文档里没找到「' + t + '」（文档可能已改）', 'warn'); return; }
  const host = node.parentElement.closest('td,li,p,tr,h2,h3,h4,pre') || node.parentElement;
  host.classList.add('wk-flash');
  host.scrollIntoView({ block: 'center', behavior: 'smooth' });
  setTimeout(() => host.classList.remove('wk-flash'), 2600);
}

/* mermaid：默认显示源码（离线可用）；能联网取到渲染器就画出来（渐进增强，失败静默回落） */
function renderMermaid() {
  const blocks = els('#wikiContent .mermaid');
  if (!blocks.length) return;
  blocks.forEach((b) => { b.innerHTML = `<pre class="code mermaid-src"><code>${esc(b.dataset.src || '')}</code></pre>`; });
  if (WIKI.triedMermaid) return;
  WIKI.triedMermaid = true;
  const s = document.createElement('script');
  s.src = 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js';
  s.onload = () => {
    try {
      const dark = document.documentElement.getAttribute('data-theme') !== 'light';
      window.mermaid.initialize({ startOnLoad: false, theme: dark ? 'dark' : 'default' });
      els('#wikiContent .mermaid').forEach((b, i) => {
        const src = b.dataset.src || '';
        try {
          window.mermaid.render('wk-mmd-' + i, src).then((out) => { b.innerHTML = out.svg; });
        } catch (e) { /* 回落源码 */ }
      });
      toast('mermaid 图已渲染（联网）', '');
    } catch (e) { /* 回落源码 */ }
  };
  document.head.appendChild(s);
}

/* `file.py:NNN` → 真实源码片段 */
function openCodeRef(ref) {
  const ov = $('codeOverlay');
  $('codeRef').textContent = ref;
  $('codeNote').textContent = '读取中…';
  $('codeBody').innerHTML = '';
  ov.classList.remove('hidden');
  api('GET', '/api/wiki/code?ref=' + encodeURIComponent(ref)).then((r) => {
    const j = r.json || {};
    if (!j.ok) {
      $('codeNote').textContent = '';
      $('codeBody').innerHTML = `<div class="code-miss">读不到源码：${esc(j.reason || '')}</div>`;
      return;
    }
    $('codeRef').textContent = `${j.file}:${j.line}`;
    $('codeNote').textContent = `共 ${j.total} 行 · 显示 ${j.lo}–${j.hi}`;
    $('codeBody').innerHTML = (j.lines || []).map((l) =>
      `<div class="code-line ${l.hit ? 'hit' : ''}"><span class="code-n">${l.n}</span><span class="code-t">${esc(l.t)}</span></div>`).join('');
    const hit = el('.code-line.hit', $('codeBody'));
    if (hit) hit.scrollIntoView({ block: 'center' });
  });
}
const codeOpen = () => !$('codeOverlay').classList.contains('hidden');

/* 「wiki:页#find=词」 → 打开文档并定位（字段注脚 / 报错说明都走它） */
function openWikiRef(href) {
  if (!href) return;
  const s = String(href).replace(/^wiki:/, '');
  const [page, frag] = s.split('#');
  const m = /find=([^&]+)/.exec(frag || '');
  openWiki(decodeURIComponent(page), m ? decodeURIComponent(m[1]) : '');
}

/* #/wiki/<page>?find=<词> 深链（可分享、可刷新保留） */
function routeFromHash() {
  const h = decodeURIComponent(location.hash || '');
  if (!h.startsWith('#/wiki/')) return false;
  const [page, qs] = h.replace('#/wiki/', '').split('?');
  const m = /find=([^&]+)/.exec(qs || '');
  openWiki(page, m ? m[1] : '');
  return true;
}

/* 离开文档 → 回到当前域的条目视图（Esc / 点域栏） */
function closeWiki() {
  $('wiki').classList.add('hidden');
  $('editorEmpty').classList.remove('hidden');
  if ((location.hash || '').startsWith('#/wiki/')) history.replaceState(null, '', location.pathname);
  renderRail();
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
    { ico: '📖', name: '打开引擎文档', meta: 'wiki', run: () => openWiki() },
    { ico: '⚙', name: '打开包设置', meta: 'settings', run: openSettings },
  ];
  const domItems = S.domains.map((d) => ({
    ico: d.icon || '•', name: '切换到 ' + d.label, meta: d.id, run: () => switchDomain(d.id),
  }));
  const entries = S.entries.map((e) => ({
    ico: '·', name: e.name || e.key, meta: `${S.dom} · ${e.key}`,
    html: true, kind: e.kind, run: () => openEntry(e.key),
  }));
  const pages = (WIKI.tree || []).map((p) => ({
    ico: '📖', name: p.title, meta: p.path, run: () => openWiki(p.path),
  }));
  PL.all = [
    { g: '动作', items: acts.filter((a) => !a.need || a.need()) },
    { g: '切换域', items: domItems },
    { g: '条目 · ' + (S.domains.find((d) => d.id === S.dom) || {}).label, items: entries },
    { g: '文档', items: pages },
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
  // 引擎版本：显示框架版本 + 需求，不匹配时标红（设计约定：不静默降级）
  const ec = (S.pkg && S.pkg.engine_check) || {};
  const eng = ((S.pkg && S.pkg.manifest) || {}).engine || '';
  const el2 = $('sbEngine');
  if (ec.ok === false) {
    el2.textContent = `⚠ 引擎 ${ec.version || '?'} 不满足要求 ${eng}`;
    el2.className = 'sb-item bad';
    el2.title = ec.note || '';
  } else if (ec.ok === true) {
    el2.textContent = `引擎 ${ec.version}${eng ? ' · 要求 ' + eng : ''}`;
    el2.className = 'sb-item mono dim';
    el2.title = ec.note || '';
  } else {
    el2.textContent = eng ? `要求 引擎 ${eng}` : '';
    el2.className = 'sb-item mono dim';
  }
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

  renderWallpaper();
}

/* ── 壁纸区渲染 ── */
function renderWallpaper() {
  const T = TH();
  const img = T.wallImage();
  const pv = $('wallPreview');
  pv.classList.toggle('empty', !img);
  pv.style.backgroundImage = img || 'none';
  pv.innerHTML = img ? '' : '<span class="ph">未启用壁纸 —— 上传图片、填网址，或选下面的内置款</span>';

  const size = T.wallSize();
  $('wallInfo').textContent = size ? `占用约 ${(size / 1048576).toFixed(1)}MB（存在本机）` : '';

  // 内置渐变壁纸
  $('wallSwatches').innerHTML = T.WALL_PRESETS.filter((x) => x.id !== 'none').map((x) =>
    `<button class="wall-sw ${T.wall().preset === x.id ? 'on' : ''}" data-wall-preset="${x.id}"
       title="${esc(x.name)}" style="background-image:${x.css}"></button>`).join('');
  els('#wallSwatches .wall-sw').forEach((b) => (b.onclick = () => {
    T.setWall({ preset: b.dataset.wallPreset === T.wall().preset ? 'none' : b.dataset.wallPreset });
    renderWallpaper();
  }));

  // 滑杆
  const w = T.wall();
  const bind = (id, val, out, fmt) => {
    $(id).value = val;
    $(out).textContent = fmt(val);
  };
  bind('wallOp', w.op, 'wallOpV', (v) => Math.round(v * 100) + '%');
  bind('wallBlur', w.blur, 'wallBlurV', (v) => v + 'px');
  bind('wallDim', w.dim, 'wallDimV', (v) => Math.round(v * 100) + '%');
  bind('wallSat', w.sat, 'wallSatV', (v) => Math.round(v * 100) + '%');
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
      if (codeOpen()) return $('codeOverlay').classList.add('hidden');
      if (themeOpen()) return closeTheme();
      if (S.pkgOpen) return closePkgMenu();
      if (simOpen()) return $('simDrawer').classList.add('hidden');
      if (isWiki()) return closeWiki();
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
  // 壁纸
  $('wallFile').onchange = (e) => {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    if (!/^image\//.test(f.type)) { toast('请选择图片文件', 'bad'); return; }
    if (f.size > TH().WALL_MAX * 0.75) {
      toast(`图片 ${(f.size / 1048576).toFixed(1)}MB 偏大（存储上限约 ${(TH().WALL_MAX / 1048576).toFixed(1)}MB）—— 可改用「网址」引用`, 'warn');
    }
    const rd = new FileReader();
    rd.onload = () => {
      const r = TH().setWall({ dataUrl: rd.result });
      if (!r.ok) { toast(r.reason, 'bad'); return; }
      toast('壁纸已应用', 'ok');
      renderWallpaper();
    };
    rd.readAsDataURL(f);
    e.target.value = '';
  };
  $('btnWallUrl').onclick = () => {
    const u = prompt('图片网址（http/https，或本机文件的 file:// 路径）：');
    if (!u) return;
    TH().setWall({ url: u });
    toast('壁纸已应用', 'ok');
    renderWallpaper();
  };
  $('btnWallClear').onclick = () => { TH().setWall({ clear: true }); renderWallpaper(); toast('壁纸已清除', ''); };
  [['wallOp', 'op'], ['wallBlur', 'blur'], ['wallDim', 'dim'], ['wallSat', 'sat']].forEach(([id, key]) => {
    const out = $(id + 'V');
    $(id).oninput = () => {
      const v = +$(id).value;
      out.textContent = key === 'blur' ? v + 'px' : Math.round(v * 100) + '%';
      TH().setWall({ [key]: v });
    };
  });
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

  // 文档（引擎 wiki）
  $('btnCodeClose').onclick = () => $('codeOverlay').classList.add('hidden');
  $('codeOverlay').onclick = (e) => { if (e.target === $('codeOverlay')) $('codeOverlay').classList.add('hidden'); };
  let wkTimer = null;
  $('wikiSearch').oninput = () => {
    const q = $('wikiSearch').value.trim();
    clearTimeout(wkTimer);
    if (q.length < 2) { renderWikiNav(); return; }
    wkTimer = setTimeout(() => renderWikiSearch(q), 220);
  };
  window.addEventListener('hashchange', () => routeFromHash());

  // 命令面板
  $('paletteInput').oninput = () => filterPalette($('paletteInput').value);
  $('paletteOverlay').onclick = (e) => { if (e.target === $('paletteOverlay')) closePalette(); };

  window.addEventListener('beforeunload', (e) => {
    if (S.dirty || S.dirtyKeys.size) { e.preventDefault(); e.returnValue = ''; }
  });

  boot();
});
