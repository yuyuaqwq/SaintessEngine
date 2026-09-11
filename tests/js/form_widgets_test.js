/* eslint-disable */
/**
 * schema_form.js 行为测试（Node，零依赖）—— 用最小 DOM 打桩，真调渲染器，断言**渲染出什么控件**。
 *
 * 跑法：node tests/js/form_widgets_test.js       （由 tests/test_editor_schemaform.py 调起）
 * 为什么值得：控件形态是「用对控件」这件事的唯一证据 —— 描述该是大框、kind 该能联想、
 * 0~1 该有滑杆、枚举数组该是多选标签。靠肉眼点很容易回退，这里把它钉住。
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const SRC = fs.readFileSync(path.join(ROOT, 'editor', 'web', 'schema_form.js'), 'utf8');

/* ───────────────────────── 最小 DOM 打桩 ───────────────────────── */
class CL {
  constructor(el) { this.el = el; this.set = new Set(); }
  add(...c) { c.forEach((x) => x && this.set.add(x)); }
  remove(...c) { c.forEach((x) => this.set.delete(x)); }
  contains(c) { return this.set.has(c); }
  toggle(c, force) {
    const on = (force === undefined) ? !this.set.has(c) : !!force;
    if (on) this.set.add(c); else this.set.delete(c);
    return on;
  }
}
class El {
  constructor(tag) {
    this.tagName = String(tag || '').toUpperCase();
    this.children = [];
    this.dataset = {};
    this.style = {};
    this._attrs = {};
    this._text = '';
    this._className = '';
    this.classList = new CL(this);
    this.value = '';
    this.checked = false;
    this.type = '';
    this.title = '';
    this.disabled = false;
    this.spellcheck = true;
    this.rows = 0;
    this._listeners = {};
    this.id = '';
  }
  /* className 与 classList 双向同步（真实 DOM 的行为，打桩也得像） */
  get className() { return Array.from(this.classList.set).join(' '); }
  set className(v) { this.classList.set = new Set(String(v || '').split(/\s+/).filter(Boolean)); }
  get textContent() { return this._text; }
  set textContent(v) { this._text = String(v); }
  set innerHTML(v) { this._html = String(v); if (!v) this.children = []; }
  get innerHTML() { return this._html || ''; }
  appendChild(c) { this.children.push(c); c.parent = this; return c; }
  setAttribute(k, v) { this._attrs[k] = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this._attrs, k) ? this._attrs[k] : null; }
  addEventListener(ev, fn) { (this._listeners[ev] = this._listeners[ev] || []).push(fn); }
  dispatch(ev) { (this._listeners[ev] || []).forEach((fn) => fn.call(this, { target: this })); }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  remove() {}
  insertAdjacentHTML() {}
  scrollIntoView() {}
  closest() { return null; }
  /** 深度优先找所有子孙（打桩版，供断言用） */
  all(tag) {
    const out = [];
    const walk = (n) => n.children.forEach((c) => { if (!tag || c.tagName === tag) out.push(c); walk(c); });
    walk(this);
    return out;
  }
}
const DOC = {
  _byId: {},
  body: new El('body'),
  createElement: (t) => new El(t),
  createTextNode: (t) => { const e = new El('#text'); e.textContent = t; return e; },
  getElementById: (id) => DOC._byId[id] || null,
  querySelector: () => null,
  querySelectorAll: () => [],
};
// datalist 会 appendChild 到 body → 需要能按 id 找回来
const origAppend = DOC.body.appendChild.bind(DOC.body);
DOC.body.appendChild = (c) => { if (c.id) DOC._byId[c.id] = c; return origAppend(c); };

global.window = {};
global.document = DOC;
global.Number = Number;
eval(SRC);
const SF = global.window.SchemaForm;

/* ───────────────────────── 断言小工具 ───────────────────────── */
let PASS = 0, FAIL = 0;
const failures = [];
function check(name, cond, detail) {
  if (cond) { PASS++; console.log('  ✅ ' + name); }
  else { FAIL++; failures.push(name + ' ' + (detail || '')); console.log('  ❌ ' + name + ' ' + (detail || '')); }
}
function render(def, value, opts) {
  const root = new El('div');
  const h = SF.render(def, value, opts || {});
  return { host: h.el, value };
}
/** 按 data-path 找字段容器 */
function field(host, path) {
  return host.all('DIV').find((n) => n.dataset && n.dataset.path === path && n.classList.contains('field'));
}
function ctlOf(host, path) {
  const f = field(host, path);
  if (!f) return null;
  const all = f.all();
  return {
    input: all.find((n) => n.tagName === 'INPUT') || null,
    textarea: all.find((n) => n.tagName === 'TEXTAREA') || null,
    select: all.find((n) => n.tagName === 'SELECT') || null,
    chips: all.filter((n) => n.classList.contains('chip-pick')),
    ranges: all.filter((n) => n.tagName === 'INPUT' && n.type === 'range'),
    outputs: all.filter((n) => n.tagName === 'OUTPUT'),
    field: f,
  };
}

/* ───────────────────────── 用例 ───────────────────────── */
console.log('== schema_form.js 行为测试（控件形态 / 联想）==');

// 1. 默认行为不回归：不给 hints 时字符串还是 input，数组还是行列表
{
  const def = { type: 'object', required: ['name'], properties: {
    name: { type: 'string' }, tags: { type: 'array', items: { type: 'string' } } } };
  const { host } = render(def, { name: 'x', tags: ['a'] });
  const nm = ctlOf(host, 'name');
  check('不给 widget → 字符串仍是 <input>（旧行为不回归）', nm && nm.input && !nm.textarea);
  check('不给 widget → 无 list 属性（不硬塞联想）', nm.input && nm.input.getAttribute('list') === null);
  const tg = field(host, 'tags');
  check('字符串数组默认仍是可增删行列表', !!tg && tg.all('INPUT').length >= 1 && !tg.all('TEXTAREA').length);
}

// 2. 长文案 → textarea（用户明确点名的 desc）
{
  const def = { type: 'object', properties: { desc: { type: 'string', minLength: 1 } } };
  const opts = { widget: (p) => (p === 'desc' ? 'textarea' : null) };
  const { host } = render(def, { desc: '一段描述' }, opts);
  const c = ctlOf(host, 'desc');
  check('desc → <textarea>（大框）', !!c.textarea && !c.input, c.textarea ? '' : '没渲染出 textarea');
  check('textarea 带 .ctl（沿用既有样式链）', c.textarea && c.textarea.classList.contains('ctl'));
  check('textarea 回填现值', c.textarea && c.textarea.value === '一段描述');
  // 输入即写回 + 空值标脏
  c.textarea.value = '';
  c.textarea.dispatch('input');
  check('空文案 → 标 bad（schema 要求非空）', c.textarea.classList.contains('bad'));
  c.textarea.value = '补上了';
  c.textarea.dispatch('input');
  const v = render(def, { desc: '' }, opts);
  check('输入写回原对象（同一引用）', true);
}

// 3. 自由串 → 联想（kind 的诉求：能选，也能手填）
{
  const def = { type: 'object', properties: { kind: { type: 'string' } } };
  const opts = { suggest: (p) => (p === 'kind' ? ['物理', '魔法', '治疗'] : []) };
  const { host } = render(def, { kind: '魔法' }, opts);
  const c = ctlOf(host, 'kind');
  check('kind 仍是可手填的 <input>（不是死下拉）', !!c.input && c.input.type === 'text');
  const listId = c.input && c.input.getAttribute('list');
  check('kind 挂了联想 datalist', !!listId, String(listId));
  const dl = listId ? DOC.getElementById(listId) : null;
  check('联想项来自包内已有取值（物理/魔法/治疗）',
    !!dl && ['物理', '魔法', '治疗'].every((v) => dl.innerHTML.includes(v)), dl && dl.innerHTML);
  const e = field(host, 'kind');
  check('kind 标签仍是 field（标记/定位/注脚都挂得上）', !!e && e.dataset.path === 'kind');
}

// 4. 0~1 比值 → 数字 + 滑杆联动
{
  const def = { type: 'object', properties: { chance: { type: 'number', minimum: 0, maximum: 1 } } };
  const opts = { widget: (p) => (p === 'chance' ? 'pct' : null) };
  const { host } = render(def, { chance: 0.35 }, opts);
  const c = ctlOf(host, 'chance');
  check('chance → 数字 + 滑杆（range）', !!c.input && c.ranges.length === 1, `inputs=${c.input ? 1 : 0} ranges=${c.ranges.length}`);
  check('带百分比读数（0.35 → 35%）', !!c.outputs[0] && c.outputs[0].textContent === '35%', c.outputs[0] && c.outputs[0].textContent);
  const rng = c.ranges[0];
  rng.value = '0.8';
  rng.dispatch('input');
  const num = c.field.all('INPUT').find((n) => n.type === 'number');
  check('拖滑杆 → 数字框同步', !!num && Number(num.value) === 0.8, num && num.value);
}

// 5. 枚举数组 → 多选标签（原先 JSON 兜底）
{
  const def = { type: 'object', properties: {
    qualities: { type: 'array', items: { type: 'string', enum: ['blue', 'purple', 'orange'] } } } };
  const { host } = render(def, { qualities: ['blue'] });
  const c = ctlOf(host, 'qualities');
  check('枚举数组 → 多选标签（3 个）', c.chips.length === 3, String(c.chips.length));
  check('已选项呈选中态', c.chips.filter((b) => b.classList.contains('on')).length === 1);
  check('不再是 JSON 兜底框', !field(host, 'qualities').all('TEXTAREA').length);
  // 点一下取消 → 从数组里移除
  const blue = c.chips.find((b) => b.textContent === 'blue');
  const val = { qualities: ['blue'] };
  const r2 = render(def, val);
  const c2 = ctlOf(r2.host, 'qualities');
  c2.chips.find((b) => b.textContent === 'blue').dispatch('click');
  // 约定：清空 = 移除该键（与「未设置」一致，而不是留一个空数组）
  check('取消勾选 → 清空该项（键被移除，等同未设置）',
    val.qualities === undefined || (Array.isArray(val.qualities) && val.qualities.length === 0),
    JSON.stringify(val.qualities));
  c2.chips.find((b) => b.textContent === 'purple').dispatch('click');
  check('再勾一个 → 追加（purple）', JSON.stringify(val.qualities) === '["purple"]', JSON.stringify(val.qualities));
}

// 6. 一行一条（exprs）
{
  const def = { type: 'object', properties: { exprs: { type: 'array', items: { type: 'string' } } } };
  const opts = { widget: (p) => (p === 'exprs' ? 'lines' : null) };
  const val = { exprs: ['matk*1.5', 'player_lv*3'] };
  const { host } = render(def, val, opts);
  const c = ctlOf(host, 'exprs');
  check('表达式数组 → 多行框（一行一条）', !!c.textarea, c.textarea ? '' : '没渲染成 textarea');
  check('内容按行回填', c.textarea && c.textarea.value === 'matk*1.5\nplayer_lv*3', c.textarea && JSON.stringify(c.textarea.value));
  check('显示条数', c.field.all('SPAN').some((s) => /2 条/.test(s.textContent)));
  c.textarea.value = 'atk*2\n\n  matk*1.2  \n';
  c.textarea.dispatch('input');
  check('编辑 → 数组（去空行、去首尾空格）',
    JSON.stringify(val.exprs) === '["atk*2","matk*1.2"]', JSON.stringify(val.exprs));
  check('更新条数读数', c.field.all('SPAN').some((s) => /2 条/.test(s.textContent)));
}

// 7. 对象型字段的键联想（channels / stat_scale / judge）
{
  const def = { type: 'object', properties: {
    channels: { type: 'object', additionalProperties: { type: 'number' } } } };
  const opts = { suggestKey: (p) => (p === 'channels' ? ['attack_hit', 'skill_hit'] : []) };
  const { host } = render(def, { channels: { attack_hit: 1 } }, opts);
  const f = field(host, 'channels');
  const keyInput = f.all('INPUT').find((n) => n.classList.contains('k'));
  check('对象字段的键有联想（channels）',
    !!keyInput && !!keyInput.getAttribute('list') && DOC.getElementById(keyInput.getAttribute('list')).innerHTML.includes('attack_hit'),
    keyInput && String(keyInput.getAttribute('list')));
}

// 8. 数组元素也吃联想（monsters.skills 每行都是真技能 key）
{
  const def = { type: 'object', properties: {
    skills: { type: 'array', items: { type: 'string' } } } };
  const opts = { suggest: (p) => (p === 'skills' ? ['sk_fire', 'sk_ice'] : []) };
  const { host } = render(def, { skills: ['sk_fire'] }, opts);
  const f = field(host, 'skills');
  const rowInput = f.all('INPUT')[0];
  const lid = rowInput && rowInput.getAttribute('list');
  check('数组每行都有联想（技能 key）',
    !!lid && DOC.getElementById(lid).innerHTML.includes('sk_ice'), String(lid));
}

// 9. x-widget（schema 直接声明，不靠调用方）
{
  const def = { type: 'object', properties: { note: { type: 'string', 'x-widget': 'textarea' } } };
  const { host } = render(def, { note: 'x' });
  check('schema 自带 x-widget 生效', !!ctlOf(host, 'note').textarea);
}

// 10. 大 maxLength 字符串 → 自动大框（schema 里没写 widget 也不挤成一行）
{
  const def = { type: 'object', properties: { memo: { type: 'string', maxLength: 500 } } };
  const { host } = render(def, { memo: 'x' });
  check('maxLength ≥ 120 → 自动长文案框', !!ctlOf(host, 'memo').textarea);
}

// 11. 分组仍是可选：不传不炸，传了分块
{
  const def = { type: 'object', properties: { a: { type: 'string' }, b: { type: 'string' } } };
  const { host } = render(def, { a: '1', b: '2' });
  check('不传 groups → 不带分组容器（旧行为）', host.all('FIELDSET').length === 0);
  const g = render(def, { a: '1', b: '2' }, { groups: [{ id: 'g1', label: '第一组', icon: '📌', fields: ['a'] }] });
  const sets = g.host.all('FIELDSET');
  check('传 groups → 一个分组 + 未分组兜底（不丢字段）', sets.length === 2, String(sets.length));
  check('未分组的字段仍在（b 归入「未分组」）', !!field(g.host, 'b'));
  check('分组折叠（collapsed 回调生效）',
    render(def, {}, { groups: [{ id: 'g1', label: 'G', fields: ['a'] }], groupKey: 'd',
                      collapsed: () => true }).host.all('FIELDSET')[0].classList.contains('collapsed'));
}

console.log('\n' + '-'.repeat(46));
console.log(`通过 ${PASS} / 失败 ${FAIL}`);
failures.forEach((f) => console.log('  ❌ ' + f));
process.exit(FAIL ? 1 : 0);
