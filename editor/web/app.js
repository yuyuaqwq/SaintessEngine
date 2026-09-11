/* 框架编辑器 —— 前端逻辑（原生 JS，零构建）
 *
 * 模型：一个「游戏包」+ 一排选项卡（一个模块一个 tab）。
 * 每个域 tab = 左条目列表 + 右编辑区（表单 / JSON / 试跑 / 删除 / 保存）。
 * 保存前先让后端校验（422 = 拦下）。
 */
'use strict';

const S = {
  domains: [],            // [{id,label,icon,kind,has_schema}]
  pkgs: [], pkgId: null, pkg: null,
  tab: 'skills',
  entries: [], entryKey: null, entryData: null, entrySchema: null,
  mode: 'form', dirty: false,
};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function toast(msg, ok = true) {
  const t = $('toast');
  t.textContent = msg; t.className = 'toast ' + (ok ? 'ok' : 'bad');
  clearTimeout(t._h); t._h = setTimeout(() => t.className = 'toast hidden', 3200);
}

async function api(method, path, body) {
  const r = await fetch(path, {
    method, headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  let j = null;
  try { j = await r.json(); } catch (e) { /* 非 JSON */ }
  return { status: r.status, ok: r.ok, json: j };
}

/* ---------------- 启动 ---------------- */
async function boot() {
  const d = await api('GET', '/api/domains');
  S.domains = (d.json && d.json.domains) || [];
  await loadPackages();
  renderTabs();
  if (S.pkgs.length) { await selectPkg(S.pkgs[0].id); }
  else { showEmpty(); }
}

async function loadPackages() {
  const r = await api('GET', '/api/packages');
  S.pkgs = (r.json && r.json.packages) || [];
  const sel = $('pkgSelect');
  sel.innerHTML = S.pkgs.map(p => `<option value="${esc(p.id)}">${esc(p.name)} (${esc(p.id)})</option>`).join('')
    || '<option value="">（还没有游戏包）</option>';
  $('pkgInfo').textContent = r.json && r.json.games_dir ? r.json.games_dir : '';
}

async function selectPkg(id) {
  if (!id) return;
  S.pkgId = id; $('pkgSelect').value = id;
  const r = await api('GET', '/api/package/' + encodeURIComponent(id));
  if (!r.ok) { toast(r.json && r.json.message || '打开包失败', false); return; }
  S.pkg = r.json;
  renderTabs();
  renderPkgForm();
  if (isDomainTab(S.tab)) await loadDomain(S.tab);
}

/* ---------------- 选项卡 ---------------- */
const SPECIAL = [{ id: 'pkg', label: '包设置', icon: '📦' }, { id: 'sim', label: '试跑', icon: '⚔' }];
const isDomainTab = (t) => S.domains.some(d => d.id === t);

function renderTabs() {
  const tabs = [];
  tabs.push(...S.domains.map(d => {
    const st = S.pkg && (S.pkg.domains || []).find(x => x.id === d.id);
    const n = st ? st.count : 0;
    const bad = st && !st.ok;
    return `<button data-tab="${d.id}" class="${S.tab === d.id ? 'active' : ''}">`
      + `${d.icon} ${esc(d.label)}<span class="badge ${bad ? 'bad' : ''}">${bad ? '!' : n}</span></button>`;
  }));
  tabs.push(...SPECIAL.map(t => `<button data-tab="${t.id}" class="${S.tab === t.id ? 'active' : ''}">${t.icon} ${t.label}</button>`));
  $('tabs').innerHTML = tabs.join('');
  $('tabs').querySelectorAll('button').forEach(b => b.onclick = () => switchTab(b.dataset.tab));
}

async function switchTab(id) {
  S.tab = id; renderTabs();
  $('view-domain').classList.toggle('hidden', !isDomainTab(id));
  $('view-sim').classList.toggle('hidden', id !== 'sim');
  $('view-pkg').classList.toggle('hidden', id !== 'pkg');
  if (isDomainTab(id)) { await loadDomain(id); }
  else if (id === 'sim') { await fillSimSelectors(); }
}

/* ---------------- 域：条目列表 ---------------- */
async function loadDomain(dom) {
  if (!S.pkgId) return;
  const r = await api('GET', `/api/package/${encodeURIComponent(S.pkgId)}/d/${dom}`);
  if (!r.ok) { toast(r.json && r.json.message || '读取域失败', false); return; }
  S.entries = r.json.entries || [];
  S.currentStatus = r.json.status || { invalid: [] };
  renderEntryList();
  if (S.entryKey && !S.entries.some(e => e.key === S.entryKey)) closeEntry();
  else if (S.entryKey) await openEntry(S.entryKey);
}

function renderEntryList() {
  const q = ($('search').value || '').trim().toLowerCase();
  const bad = new Set(((S.currentStatus || {}).invalid || []).map(x => x.key));
  const rows = S.entries.filter(e => !q || (e.key + ' ' + e.name + ' ' + (e.kind || '')).toLowerCase().includes(q));
  $('entryList').innerHTML = rows.map(e => `
    <div class="row ${e.key === S.entryKey ? 'active' : ''}" data-key="${esc(e.key)}">
      <div>
        <div class="k">${esc(e.name)}</div>
        <div class="m">${esc(e.key)}</div>
      </div>
      <div class="m">${esc(e.kind || '')}</div>
      ${bad.has(e.key) ? '<div class="err">✗</div>' : ''}
    </div>`).join('') || '<div class="row"><span class="muted">（空）</span></div>';
  $('entryList').querySelectorAll('.row[data-key]').forEach(el => el.onclick = () => openEntry(el.dataset.key));
}

/* ---------------- 条目编辑 ---------------- */
function closeEntry() {
  S.entryKey = null; S.entryData = null; S.dirty = false;
  $('entryHead').innerHTML = '<span class="muted">← 选一个条目开始编辑</span>';
  $('formHost').innerHTML = ''; $('jsonHost').value = '';
  $('errors').classList.add('hidden');
}

async function openEntry(key) {
  const dom = S.tab;
  const r = await api('GET', `/api/package/${encodeURIComponent(S.pkgId)}/d/${dom}/${encodeURIComponent(key)}`);
  if (!r.ok) { toast(r.json && r.json.message || '读取条目失败', false); return; }
  S.entryKey = key; S.entryData = r.json.data; S.entrySchema = r.json.schema;
  S.dirty = false;
  $('entryHead').innerHTML = `${esc(S.entryData.name || key)}<span class="key">${esc(dom)} · ${esc(key)}</span>`;
  showErrors(r.json.errors || []);
  renderEntry(); renderEntryList();
}

function renderEntry() {
  if (S.mode === 'json') {
    $('jsonHost').value = JSON.stringify(S.entryData, null, 2);
    $('jsonHost').classList.remove('hidden'); $('formHost').classList.add('hidden');
    return;
  }
  $('jsonHost').classList.add('hidden');
  const host = $('formHost');
  host.classList.remove('hidden');
  const primary = (S.entrySchema && S.entrySchema['x-primary']) || primaryOf();
  const def = S.entrySchema && S.entrySchema.$defs && S.entrySchema.$defs[primary];
  if (!def || !window.SchemaForm) {
    host.innerHTML = '<p class="muted">该域没有可用 schema —— 请用「原始 JSON」编辑。</p>';
    return;
  }
  host.innerHTML = '';
  try {
    const h = window.SchemaForm.render(def, S.entryData, {
      onChange: () => { S.dirty = true; },
      onRerender: () => renderEntry(),
    });
    host.appendChild(h.el);
  } catch (e) {
    host.innerHTML = '<p class="muted">表单渲染失败（' + esc(e.message) + '）—— 请用「原始 JSON」。</p>';
  }
  document.querySelectorAll('.viewtabs [data-mode]').forEach(b =>
    b.classList.toggle('active', b.dataset.mode === S.mode));
}

function primaryOf() {
  const d = S.domains.find(x => x.id === S.tab);
  return d ? (d.primary || '') : '';
}

function showErrors(errs) {
  const el = $('errors');
  if (!errs || !errs.length) { el.classList.add('hidden'); return; }
  el.innerHTML = `<b>${errs.length} 个校验问题（保存会被拦下）</b><br>` + errs.map(esc).join('<br>');
  el.classList.remove('hidden');
}

/* ---------------- 保存 / 删除 / 新建 ---------------- */
async function save() {
  if (!S.entryKey) return;
  if (S.mode === 'json') {
    try { S.entryData = JSON.parse($('jsonHost').value); }
    catch (e) { toast('JSON 语法错误：' + e.message, false); return; }
  }
  const r = await api('PUT', `/api/package/${encodeURIComponent(S.pkgId)}/d/${S.tab}/${encodeURIComponent(S.entryKey)}`,
    { data: S.entryData });
  if (r.status === 422) { showErrors(((r.json.validation || {}).errors) || []); toast('校验未通过，未写入', false); return; }
  if (!r.ok) { toast(r.json && r.json.message || '保存失败', false); return; }
  S.dirty = false; toast('已保存 ' + S.entryKey);
  await refreshPkg(); await loadDomain(S.tab);
}

async function del() {
  if (!S.entryKey) return;
  if (!confirm('删除条目 ' + S.entryKey + '？此操作直接改 JSON 文件。')) return;
  const r = await api('DELETE', `/api/package/${encodeURIComponent(S.pkgId)}/d/${S.tab}/${encodeURIComponent(S.entryKey)}`);
  if (!r.ok) { toast('删除失败', false); return; }
  toast('已删除 ' + S.entryKey); closeEntry();
  await refreshPkg(); await loadDomain(S.tab);
}

async function add() {
  const key = prompt('新条目的 key（英文/下划线，如 sk_fire_ball）：');
  if (!key) return;
  const name = prompt('显示名（name）：', key) || key;
  const data = { name, kind: (S.tab === 'skills' ? '物理' : ''), lv: 1, desc: '' };
  const r = await api('PUT', `/api/package/${encodeURIComponent(S.pkgId)}/d/${S.tab}/${encodeURIComponent(key)}`, { data });
  if (!r.ok) {
    showErrors(((r.json || {}).validation || {}).errors || []);
    toast('新建失败：' + ((r.json || {}).message || ''), false); return;
  }
  toast('已新建 ' + key);
  await refreshPkg(); await loadDomain(S.tab); await openEntry(key);
}

/* ---------------- 包 ---------------- */
function renderPkgForm() {
  const m = (S.pkg && S.pkg.manifest) || {};
  $('pkgForm').innerHTML = `
    <label>包 id（目录名，创建后不可改）<input value="${esc(m.id || '')}" disabled></label>
    <label>显示名 <input id="pkName" value="${esc(m.name || '')}"></label>
    <label>简介 <input id="pkDesc" value="${esc(m.desc || '')}"></label>
    <label>引擎版本要求 <input id="pkEngine" value="${esc(m.engine || '')}"></label>`;
  $('pkgPath').textContent = S.pkg && S.pkg.dir ? '目录：' + S.pkg.dir : '';
}

async function savePkg() {
  const m = Object.assign({}, (S.pkg && S.pkg.manifest) || {}, {
    name: $('pkName').value, desc: $('pkDesc').value, engine: $('pkEngine').value,
  });
  const r = await api('PUT', `/api/package/${encodeURIComponent(S.pkgId)}/manifest`, { manifest: m });
  if (!r.ok) { toast('保存包清单失败', false); return; }
  toast('包清单已保存'); await refreshPkg(); await loadPackages();
}

async function refreshPkg() {
  const r = await api('GET', '/api/package/' + encodeURIComponent(S.pkgId));
  if (r.ok) { S.pkg = r.json; renderTabs(); }
}

function showEmpty() {
  $('entryList').innerHTML = '<div class="row"><span class="muted">还没有游戏包 → 点右上角「＋ 新建包」</span></div>';
  $('entryHead').innerHTML = '<span class="muted">先建一个游戏包吧</span>';
}

/* ---------------- 试跑 ---------------- */
async function fillSimSelectors() {
  const sel = $('simDomain');
  sel.innerHTML = S.domains.map(d => `<option value="${d.id}">${d.icon} ${esc(d.label)}</option>`).join('');
  sel.value = isDomainTab(S.tab) ? S.tab : (S.domains[0] || {}).id;
  sel.onchange = fillSimSkills;
  await fillSimSkills();
}

async function fillSimSkills() {
  const dom = $('simDomain').value;
  const r = await api('GET', `/api/package/${encodeURIComponent(S.pkgId)}/d/${dom}`);
  const list = (r.json && r.json.entries) || [];
  $('simSkill').innerHTML = list.map(e => `<option value="${esc(e.key)}">${esc(e.name)}</option>`).join('')
    || '<option value="">（该域没有条目）</option>';
}

async function runSim() {
  const dom = $('simDomain').value, key = $('simSkill').value;
  if (!key) { toast('先选一个技能', false); return; }
  const gr = await api('GET', `/api/package/${encodeURIComponent(S.pkgId)}/d/${dom}/${encodeURIComponent(key)}`);
  const skill = gr.json && gr.json.data;
  $('simOut').textContent = '跑动中…（子进程起引擎）';
  const r = await api('POST', `/api/package/${encodeURIComponent(S.pkgId)}/simulate`, {
    skill, skill_lv: +$('simSkillLv').value, seed: +$('simSeed').value,
    attacker: { class_name: $('simClass').value, level: +$('simLevel').value },
    defender: { def: +$('simDef').value, mdef: +$('simMdef').value, hp: +$('simHp').value },
  });
  const j = r.json || {};
  if (!j.ok) {
    $('simOut').textContent = `❌ 失败（stage=${j.stage}）\n${j.message || ''}\n\n${j.traceback || j.stdout || ''}`;
    return;
  }
  $('simOut').textContent = [
    `✅ 伤害 ${j.damage} ｜ 目标血量 ${j.hp.target_before} → ${j.hp.target_after}`,
    `施法者 ${JSON.stringify(j.attacker)}`,
    '', '—— 日志 ——', ...(j.logs || []),
    '', '—— 事件 ——', ...((j.events || []).map(e => `${e.event}  ${JSON.stringify(e.ctx)}`)),
  ].join('\n');
}

/* ---------------- 事件绑定 ---------------- */
window.addEventListener('DOMContentLoaded', () => {
  $('pkgSelect').onchange = () => selectPkg($('pkgSelect').value);
  $('search').oninput = renderEntryList;
  $('btnAdd').onclick = add;
  $('btnSave').onclick = save;
  $('btnDel').onclick = del;
  $('btnValidate').onclick = async () => {
    const r = await api('POST', `/api/package/${encodeURIComponent(S.pkgId)}/validate`);
    const j = r.json || {};
    if (j.ok) { toast('全包校验通过 ✅'); return; }
    const n = (j.problems || []).reduce((a, p) => a + p.invalid.length, 0);
    toast(`全包校验：${n} 个条目有问题（tab 上会标 !）`, false);
    await refreshPkg();
  };
  $('btnNew').onclick = async () => {
    const id = prompt('新游戏包 id（小写字母/数字/下划线，如 my_game）：');
    if (!id) return;
    const name = prompt('显示名：', id) || id;
    const r = await api('POST', '/api/packages', { id, name });
    if (!r.ok) { toast((r.json || {}).message || '创建失败', false); return; }
    toast('已创建 ' + id); await loadPackages(); await selectPkg(id);
  };
  document.querySelectorAll('.viewtabs [data-mode]').forEach(b => b.onclick = async () => {
    S.mode = b.dataset.mode;
    if (S.mode === 'form' && $('jsonHost').value && S.entryData) {
      try { S.entryData = JSON.parse($('jsonHost').value); } catch (e) { toast('JSON 有错，未同步到表单', false); }
    }
    renderEntry();
  });
  $('btnSim').onclick = async () => {
    await switchTab('sim');
    if (isDomainTab('skills')) { $('simDomain').value = 'skills'; }
    if (S.entryKey) { await fillSimSkills(); $('simSkill').value = S.entryKey; }
  };
  $('btnRunSim').onclick = runSim;
  $('btnSavePkg').onclick = savePkg;
  window.addEventListener('beforeunload', (e) => { if (S.dirty) { e.preventDefault(); e.returnValue = ''; } });
  boot();
});
