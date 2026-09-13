# -*- coding: utf-8 -*-
"""前端渲染器（schema_form.js）行为测试的**调度器** —— 有 node 就真跑，没有就明确跳过。

为什么要它：控件形态（长文案给大框 / 0~1 给滑杆 / 枚举数组给多选 / **键值行 kv / 行编辑 rows**）
是「用对控件」这件事的唯一证据。用 Node 打桩跑真渲染器，能钉住这些行为，不靠肉眼看点。

跑法：python tests/test_editor_schemaform.py
退出码：0 = 通过（或本机无 node 而显式跳过）；1 = 有断言失败。

两段门禁：
  1. `tests/js/form_widgets_test.js` —— 既有 4 种控件（textarea / lines / pct / chips）的老门禁；
  2. 本文件内嵌的 kv/rows 用例（真跑 schema_form.js）—— 键值行 / 行编辑的增删改、取值 coerce、
     `propertyNames.enum` 出下拉、空对象/空数组加行、键序行序稳定，外加**突变反证**（故意让
     kv 丢键 / rows 丢行 / 空对象写成 `{}` → 断言必须报红，证明闸门不是装饰）。
     （内嵌而不新建 tests/js/*.js：本轮改动范围限定在这三个文件里；要挪出去直接搬字符串即可。）
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
JS_LEGACY = os.path.join(HERE, "js", "form_widgets_test.js")

KVROWS_JS = r"""/* eslint-disable */
/* kv（键值行）/ rows（行编辑）门禁 —— 由 tests/test_editor_schemaform.py 写进临时文件后真跑。
 * 打桩 DOM → 真调 editor/web/schema_form.js → 断言「控件是什么 + 数据被写成了什么」。
 * 末段是**突变反证**：把源码里那几行故意改坏，断言必须报红（否则这门禁就是装饰）。 */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = process.argv[2] || process.cwd();
const SRC = fs.readFileSync(path.join(ROOT, 'editor', 'web', 'schema_form.js'), 'utf8');

/* ───────────────────────── 最小 DOM 打桩 ───────────────────────── */
class CL {
  constructor() { this.set = new Set(); }
  add(...c) { c.forEach((x) => x && this.set.add(x)); }
  remove(...c) { c.forEach((x) => this.set.delete(x)); }
  contains(c) { return this.set.has(c); }
  toggle(c, force) { const on = (force === undefined) ? !this.set.has(c) : !!force; if (on) this.set.add(c); else this.set.delete(c); return on; }
}
class El {
  constructor(tag) {
    this.tagName = String(tag || '').toUpperCase();
    this.children = []; this.dataset = {}; this.style = {}; this._attrs = {}; this._text = '';
    this.classList = new CL(); this.value = ''; this.checked = false; this.type = '';
    this.title = ''; this.disabled = false; this.spellcheck = true; this.rows = 0;
    this._listeners = {}; this.id = '';
  }
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
  remove() {} insertAdjacentHTML() {} scrollIntoView() {} closest() { return null; }
  all(tag) { const out = []; const walk = (n) => n.children.forEach((c) => { if (!tag || c.tagName === tag) out.push(c); walk(c); }); walk(this); return out; }
}
function makeDoc() {
  const DOC = {
    _byId: {}, body: new El('body'),
    createElement: (t) => new El(t),
    createTextNode: (t) => { const e = new El('#text'); e.textContent = t; return e; },
    getElementById: (id) => DOC._byId[id] || null,
    querySelector: () => null, querySelectorAll: () => [],
  };
  const orig = DOC.body.appendChild.bind(DOC.body);
  DOC.body.appendChild = (c) => { if (c.id) DOC._byId[c.id] = c; return orig(c); };
  return DOC;
}
function loadSF(src) {
  const win = {};
  const fn = new Function('window', 'document', src + '\nreturn window.SchemaForm;');
  const SF = fn(win, makeDoc());
  if (!SF) throw new Error('没有导出 window.SchemaForm');
  return SF;
}

/* ───────────────────────── 断言小工具 ───────────────────────── */
const MAIN = { pass: 0, fail: 0, msgs: [] };
let CUR = MAIN;
function check(name, cond, detail) {
  if (cond) { CUR.pass++; console.log('  ✅ ' + name); }
  else { CUR.fail++; CUR.msgs.push(name + ' ' + (detail || '')); console.log('  ❌ ' + name + ' ' + (detail || '')); }
}
function withFresh(src, fn) {           // 在「另一份源码」上跑一段用例，收自己的账
  const box = { pass: 0, fail: 0, msgs: [] };
  const prev = CUR; CUR = box;
  try { fn(loadSF(src)); } catch (e) { box.fail++; box.msgs.push('异常: ' + e.message); }
  CUR = prev;
  return box;
}
/* 渲染一件数据，返回 {host, val} */
function rendered(SF, def, val, opts) {
  const h = SF.render(def, val, Object.assign({ onChange: () => {} }, opts || {}));
  return { host: h.el, val: val };
}
function fieldOf(host, p) {
  return host.all('DIV').find((n) => n.dataset && n.dataset.path === p && n.classList.contains('field')) || null;
}
function named(root, cls, tag) { return root.all(tag || 'DIV').filter((n) => n.classList.contains(cls)); }
function btn(root, re) { return root.all('BUTTON').find((b) => re.test(b.textContent)) || null; }
const kv = {
  rows: (f) => named(f, 'kv-row'),
  key: (r) => r.children[0],
  val: (r) => r.children[1],
  del: (f, i) => named(f, 'kv-row')[i].all('BUTTON').find((b) => b.classList.contains('row-del')),
  add: (f) => btn(f, /加一行/),
};
const rw = {
  rows: (f) => named(f, 'row-item'),
  title: (r) => { const t = r.all('SPAN').find((s) => s.classList.contains('row-title')); return t ? t.textContent : ''; },
  del: (f, i) => named(f, 'row-item')[i].all('BUTTON').find((b) => b.classList.contains('row-del')),
  add: (f) => btn(f, /加一行/),
  subfield: (r, p) => r.all('DIV').find((n) => n.dataset && n.dataset.path === p && n.classList.contains('field')) || null,
  input: (r, p) => { const f = rw.subfield(r, p); return f ? f.all('INPUT')[0] : null; },
};
function typeInp(inp, v, ev) { inp.value = String(v); inp.dispatch(ev || 'input'); }
function fire(node, ev) { node.dispatch(ev); }

console.log('== schema_form.js 行为测试（kv / rows 控件）==');
const SF = loadSF(SRC);

/* ═══════════════ 1. kv：键值行 ═══════════════ */
console.log('\n[1] kv —— 键值行（对象 → 一行一个键）');
{
  const def = { type: 'object', properties: { channels: {
    type: 'object', title: '攒取渠道', 'x-widget': 'kv',
    propertyNames: { type: 'string', description: '键 = 时机名（attack_hit / skill_hit …）' },
    additionalProperties: { type: 'number', minimum: 0 } } } };
  const val = { channels: { attack_hit: 1, skill_hit: 2 } };
  const { host } = rendered(SF, def, val, { suggestKey: (p) => (p === 'channels' ? ['attack_hit', 'skill_hit'] : []) });
  const f = fieldOf(host, 'channels');
  check('x-widget: kv → 出键值行（2 行）', !!f && kv.rows(f).length === 2, kv.rows(f).length + '');
  check('kv 行不再是 JSON 兜底框', !!f && !f.all('TEXTAREA').length);
  check('键是文本输入 + 带 propertyNames 提示', kv.key(kv.rows(f)[0]).tagName === 'INPUT' &&
    kv.key(kv.rows(f)[0]).title.indexOf('时机名') >= 0, kv.key(kv.rows(f)[0]).title);
  const lid = kv.key(kv.rows(f)[0]).getAttribute('list');
  check('键挂了候选 datalist（suggestKey 的候选）', !!lid, String(lid));
  check('值控件按 additionalProperties（number）给', kv.val(kv.rows(f)[0]).tagName === 'INPUT' &&
    kv.val(kv.rows(f)[0]).type === 'number');
  /* 值类型 coerce */
  typeInp(kv.val(kv.rows(f)[0]), '5');
  check('值写回是 number（不是字符串 "5"）',
    val.channels.attack_hit === 5 && typeof val.channels.attack_hit === 'number', JSON.stringify(val.channels));
  /* 键重命名：原位替换，键序不变 */
  const kc = kv.key(kv.rows(f)[0]);
  kc.value = 'attack_miss'; fire(kc, 'change');
  check('重命名键 → 键名换了、键序原位、值跟着走',
    JSON.stringify(Object.keys(val.channels)) === '["attack_miss","skill_hit"]' && val.channels.attack_miss === 5,
    JSON.stringify(val.channels));
  /* 空键/重键 → 退回原名，不静默吞掉 */
  const kc2 = kv.key(kv.rows(f)[0]);
  kc2.value = 'skill_hit'; fire(kc2, 'change');
  check('改成已存在的键 → 退回原名并标 bad（不静默吞）',
    JSON.stringify(Object.keys(val.channels)) === '["attack_miss","skill_hit"]' && kc2.classList.contains('bad'),
    JSON.stringify(Object.keys(val.channels)));
  /* 删除中间一行：只删这一行 */
  kv.del(f, 0).dispatch('click');
  check('删一行 → 只删这一个键（其它键与值不动）',
    JSON.stringify(val.channels) === '{"skill_hit":2}', JSON.stringify(val.channels));
}
{
  /* 空对象加行：不许写成 {}（键必须在） */
  const def = { type: 'object', properties: { roles: {
    type: 'object', 'x-widget': 'kv', additionalProperties: { type: 'string' } } } };
  const val = { roles: {} };
  const { host } = rendered(SF, def, val);
  const f = fieldOf(host, 'roles');
  check('空对象 → 0 行但「+ 加一行」在', kv.rows(f).length === 0 && !!kv.add(f));
  kv.add(f).dispatch('click');
  check('空对象加行 → 对象里有键（不是空 {}）',
    Object.keys(val.roles).length === 1 && JSON.stringify(val.roles) !== '{}', JSON.stringify(val.roles));
  check('加行写的是 string 默认值（additionalProperties 声明）', val.roles[Object.keys(val.roles)[0]] === '');
  kv.add(f).dispatch('click');
  check('再加一行 → 追加在末尾（键序稳定）',
    JSON.stringify(Object.keys(val.roles)) === '["new_key","new_key2"]', JSON.stringify(Object.keys(val.roles)));
  kv.del(f, 0).dispatch('click'); kv.del(f, 0).dispatch('click');
  check('删光 → 该字段键被移除（不留空 {}）', val.roles === undefined, JSON.stringify(val.roles));
}
{
  /* 字段整体缺失时也能加行 */
  const def = { type: 'object', properties: { roles: {
    type: 'object', 'x-widget': 'kv', additionalProperties: { type: 'integer' } } } };
  const val = {};
  const { host } = rendered(SF, def, val);
  const f = fieldOf(host, 'roles');
  kv.add(f).dispatch('click');
  check('字段原本不存在 → 加行后建出来（integer 顶格默认 0）',
    JSON.stringify(val.roles) === '{"new_key":0}', JSON.stringify(val.roles));
}
{
  /* propertyNames.enum → 键出下拉；键用尽后 add 行为 */
  const def = { type: 'object', properties: { res: {
    type: 'object', 'x-widget': 'kv', propertyNames: { enum: ['mp', 'stamina'] },
    additionalProperties: { type: 'integer' } } } };
  const val = { res: { mp: 3 } };
  const { host } = rendered(SF, def, val);
  const f = fieldOf(host, 'res');
  check('propertyNames.enum → 键是 <select>（不是手打）', kv.key(kv.rows(f)[0]).tagName === 'SELECT');
  check('下拉选项 = 枚举全集（2 个）', kv.rows(f)[0].all('OPTION').length === 2);
  kv.add(f).dispatch('click');
  check('加行 → 自动挑还没用过的枚举键（stamina）',
    JSON.stringify(Object.keys(val.res)) === '["mp","stamina"]', JSON.stringify(val.res));
  /* additionalProperties: false + 声明的键都用完 → 不能加 */
  const def2 = { type: 'object', properties: { kv2: {
    type: 'object', 'x-widget': 'kv', properties: { a: { type: 'string' }, b: { type: 'string' } },
    additionalProperties: false } } };
  const v2 = { kv2: { a: 'x', b: 'y' } };
  const h2 = rendered(SF, def2, v2).host;
  const f2 = fieldOf(h2, 'kv2');
  check('声明键全在 + additionalProperties:false → 加行按钮禁用', !!kv.add(f2) && kv.add(f2).disabled === true);
  check('键值行照常出（properties 声明也走 kv）', kv.rows(f2).length === 2);
}
{
  /* 值的形状递归：数组值 → 一行一条；对象值 → 子表单 */
  const def = { type: 'object', properties: { links: {
    type: 'object', 'x-widget': 'kv',
    additionalProperties: { type: 'array', 'x-widget': 'lines', items: { type: 'string' } } } } };
  const val = { links: { plaza: ['east', 'west'] } };
  const { host } = rendered(SF, def, val);
  const f = fieldOf(host, 'links');
  const cell = kv.val(kv.rows(f)[0]);
  const ta = cell.all('TEXTAREA')[0];
  check('值本身是字符串数组（x-widget: lines）→ 值控件里是一行一条的多行框',
    !!ta && ta.classList.contains('lines'), cell.tagName + '/' + (ta ? ta.tagName : '无'));
  typeInp(ta, 'east\nwest\nnorth');
  check('编辑值 → 写回数组（去空行）',
    JSON.stringify(val.links.plaza) === '["east","west","north"]', JSON.stringify(val.links));
  const def2 = { type: 'object', properties: { on_threshold: {
    type: 'object', 'x-widget': 'kv',
    additionalProperties: { type: 'object', properties: { form: { type: 'string' } } } } } };
  const v2 = { on_threshold: { 10: { form: 'fury' } } };
  const h2 = rendered(SF, def2, v2).host;
  const f2 = fieldOf(h2, 'on_threshold');
  const inner = kv.val(kv.rows(f2)[0]);
  check('值本身是对象 → 递归成子卡片（fieldset + 字段）', inner.tagName === 'FIELDSET');
  const inp = inner.all('INPUT')[0];
  typeInp(inp, 'calm');
  check('子卡片编辑 → 写回内层键', v2.on_threshold['10'].form === 'calm', JSON.stringify(v2.on_threshold));
}

/* ═══════════════ 2. rows：行编辑 ═══════════════ */
console.log('\n[2] rows —— 行编辑（数组 → 一行一个 items 子表单）');
{
  const def = { type: 'object', properties: { formula: {
    type: 'array', title: '结构化公式', 'x-widget': 'rows', items: {
      type: 'object', title: '公式行', required: ['stat', 'mult', 'type'],
      properties: { stat: { enum: ['atk', 'matk'] }, mult: { type: 'number' }, type: { type: 'string' } } } } } };
  const val = { formula: [{ stat: 'atk', mult: 1, type: 'phys' }, { stat: 'matk', mult: 2, type: 'magi' }] };
  const { host } = rendered(SF, def, val);
  const f = fieldOf(host, 'formula');
  check('x-widget: rows → 出 2 行（不再是 JSON 兜底）', !!f && rw.rows(f).length === 2 && !f.all('TEXTAREA').length);
  check('行首是可读标题（取 items 里的取值 type）', rw.title(rw.rows(f)[0]) === 'phys', rw.title(rw.rows(f)[0]));
  check('行体是真子表单（行内字段带 items 形状）', !!rw.subfield(rw.rows(f)[0], 'formula.0.mult'));
  check('行内 enum 字段是下拉（stat）', rw.subfield(rw.rows(f)[0], 'formula.0.stat').all('SELECT').length === 1);
  typeInp(rw.input(rw.rows(f)[0], 'formula.0.mult'), '3');
  check('行内编辑 → 写回该行（number coerce）', val.formula[0].mult === 3, JSON.stringify(val.formula[0]));
  check('别的行不受影响（行序稳定）', val.formula[1].mult === 2 && val.formula[1].stat === 'matk');
  /* 改行内标题字段 → 行首标题跟着变 */
  const tf = rw.subfield(rw.rows(f)[0], 'formula.0.type');
  typeInp(tf.all('INPUT')[0], 'magi');
  fire(tf.parent, 'input');
  check('行内改名 → 行首标题同步', rw.title(rw.rows(f)[0]) === 'magi', rw.title(rw.rows(f)[0]));
  /* 删中间一行 */
  rw.del(f, 0).dispatch('click');
  check('删一行 → 只少这一行，剩下的顺序不变',
    val.formula.length === 1 && val.formula[0].mult === 2, JSON.stringify(val.formula));
  /* 加一行（默认值按 required 预填） */
  rw.add(f).dispatch('click');
  check('加一行 → 追加在末尾且原有行还在',
    val.formula.length === 2 && val.formula[0].mult === 2, JSON.stringify(val.formula));
  check('新行按 required 预填（stat/mult/type 都有键）',
    Object.keys(val.formula[1]).join(',') === 'stat,mult,type', JSON.stringify(val.formula[1]));
}
{
  /* 空数组 / 字段缺失都能加行 */
  const def = { type: 'object', properties: { formula: {
    type: 'array', 'x-widget': 'rows', items: { type: 'object', required: ['stat'], properties: { stat: { type: 'string' } } } } } };
  const val = { formula: [] };
  const { host } = rendered(SF, def, val);
  const f = fieldOf(host, 'formula');
  check('空数组 → 0 行但「+ 加一行」在', rw.rows(f).length === 0 && !!rw.add(f));
  rw.add(f).dispatch('click');
  check('空数组加行 → 1 行（不是 JSON 串）', Array.isArray(val.formula) && val.formula.length === 1, JSON.stringify(val.formula));
  const v2 = {};
  const f2 = fieldOf(rendered(SF, def, v2).host, 'formula');
  rw.add(f2).dispatch('click');
  check('字段原本不存在 → 加行后建数组', JSON.stringify(v2.formula) === '[{"stat":""}]', JSON.stringify(v2.formula));
  rw.del(f2, 0).dispatch('click');
  check('删光 → 该字段键被移除（不留空数组）', v2.formula === undefined, JSON.stringify(v2.formula));
}
{
  /* 标量元素 + x-widget: rows（一行一个输入框） */
  const def = { type: 'object', properties: { funcs: {
    type: 'array', 'x-widget': 'rows', items: { type: 'string' } } } };
  const val = { funcs: ['治疗', '商店'] };
  const { host } = rendered(SF, def, val);
  const f = fieldOf(host, 'funcs');
  check('标量数组 + rows → 一行一个输入框（2 行）', rw.rows(f).length === 2);
  typeInp(rw.rows(f)[0].all('INPUT')[0], '锻造');
  check('标量行编辑 → 写回该位置', val.funcs[0] === '锻造', JSON.stringify(val.funcs));
  rw.del(f, 0).dispatch('click');
  check('标量行删除 → 只删这一个', JSON.stringify(val.funcs) === '["商店"]', JSON.stringify(val.funcs));
  rw.add(f).dispatch('click');
  check('标量行追加', JSON.stringify(val.funcs) === '["商店",""]', JSON.stringify(val.funcs));
}
{
  /* items 里的 name 当标题 */
  const def = { type: 'object', properties: { picks: {
    type: 'array', 'x-widget': 'rows', items: { type: 'object', properties: { name: { type: 'string' }, rid: { type: 'string' } } } } } };
  const val = { picks: [{ name: '长剑', rid: 'eq_1' }] };
  const f = fieldOf(rendered(SF, def, val).host, 'picks');
  check('行标题优先取 items 的 name', rw.title(rw.rows(f)[0]) === '长剑', rw.title(rw.rows(f)[0]));
}

/* ═══════════════ 3. 通用化 & 不回归 ═══════════════ */
console.log('\n[3] 对象数组 / $ref / 不回归');
{
  /* 未声明 rows 的对象数组也走行编辑（原先是 JSON 兜底） */
  const def = { type: 'object', properties: { load_tiers: {
    type: 'array', items: { type: 'object', properties: { max: { type: 'integer' }, label: { type: 'string' } } } } } };
  const val = { load_tiers: [{ max: 3, label: '轻载' }] };
  const f = fieldOf(rendered(SF, def, val).host, 'load_tiers');
  check('对象数组（没写 x-widget）→ 也是行编辑', rw.rows(f).length === 1 && !f.all('TEXTAREA').length);
}
{
  /* 联合元素（引用串 | 内联对象）→ 也是行编辑，每行按现值挑分支 */
  const def = { type: 'object', properties: { pois: {
    type: 'array', minItems: 1, items: { anyOf: [
      { type: 'string', minLength: 1 },
      { type: 'object', properties: { id: { type: 'string' }, type: { type: 'string' } } }] } } } };
  const val = { pois: ['poi_lamp', { id: 'p2', type: 'shop' }] };
  const f = fieldOf(rendered(SF, def, val).host, 'pois');
  check('联合元素数组（串 | 对象）→ 行编辑（2 行）', rw.rows(f).length === 2 && !f.all('TEXTAREA').length);
  check('第 1 行按现值挑字符串支（文本框）', rw.rows(f)[0].all('INPUT').length === 1);
  check('第 2 行按现值挑对象支（子表单）', !!rw.subfield(rw.rows(f)[1], 'pois.1.id'));
  typeInp(rw.rows(f)[1].all('INPUT').find((n) => n.value === 'shop'), 'inn');
  check('对象支行内编辑 → 写回该行', val.pois[1].type === 'inn', JSON.stringify(val.pois));
  rw.del(f, 0).dispatch('click');
  check('删第 1 行 → 剩下的内联对象行还在', JSON.stringify(val.pois) === '[{"id":"p2","type":"inn"}]', JSON.stringify(val.pois));
}
{
  /* $ref：传 defs 时能解开 → 行编辑 */
  const doc = { $defs: {
    stage: { type: 'object', title: '一层', properties: { name: { type: 'string' }, monsters: { type: 'array', items: { type: 'string' } } } },
    instance: { type: 'object', properties: { stages: { type: 'array', items: { $ref: '#/$defs/stage' } } } } } };
  const val = { stages: [{ name: '一层', monsters: ['m1'] }] };
  const f = fieldOf(rendered(SF, doc.$defs.instance, val, { defs: doc.$defs }).host, 'stages');
  check('opts.defs → $ref items 解开成行编辑', rw.rows(f).length === 1 && !f.all('TEXTAREA').length);
  check('$ref 解出的行标题能用', rw.title(rw.rows(f)[0]) === '一层', rw.title(rw.rows(f)[0]));
  /* 不给 defs（app.js 现状接线）→ 旧行为：JSON 兜底，不抛 */
  const v2 = { stages: [{ name: '一层' }] };
  const f2 = fieldOf(rendered(SF, doc.$defs.instance, v2).host, 'stages');
  check('不给 defs → 保持旧行为（JSON 兜底，不抛）', !!f2 && f2.all('TEXTAREA').length === 1);
}
{
  /* 不回归：没有 kv 声明的对象仍是分组表单；形状不明的数组仍是 JSON 兜底 */
  const def = { type: 'object', properties: {
    obj: { type: 'object', properties: { a: { type: 'string' } } },
    weird: { type: 'array' } } };
  const val = { obj: { a: 'x' }, weird: [1, 2] };
  const host = rendered(SF, def, val).host;
  check('无 kv 声明的对象 → 仍是分组 fieldset（旧行为）',
    fieldOf(host, 'obj').all('FIELDSET').length === 1);
  const w = fieldOf(host, 'weird');
  check('形状不明的数组 → 仍是 JSON 兜底（不瞎猜）',
    w.all('TEXTAREA').length === 1 && w.all('DIV').some((n) => n.classList.contains('help') && /JSON/.test(n.textContent)));
}

/* ═══════════════ 4. 真实 schema 冒烟 ═══════════════ */
console.log('\n[4] 真实包 schema 冒烟（games/orlandia/schemas）');
{
  const readDoc = (f) => JSON.parse(fs.readFileSync(path.join(ROOT, 'games', 'orlandia', 'schemas', f), 'utf8'));
  const skill = readDoc('skill.schema.json');
  const sval = {
    name: '死神之箭', desc: 'x', kind: '物理', lv: 1, exprs: ['atk*2'],
    formula: [{ stat: 'atk', mult: 1.5, type: 'phys', skill_flat: true }],
    kill: { hunt_full: true, poison: 5, hp_lt: 0.3 },
    passive: { proc: 'x', add: 1 },
  };
  const sHost = rendered(SF, skill.$defs.skill, sval, { defs: skill.$defs }).host;
  const ff = fieldOf(sHost, 'formula');
  check('skills.formula[] → 行编辑（1 行，行内字段是真控件）',
    rw.rows(ff).length === 1 && !!rw.subfield(rw.rows(ff)[0], 'formula.0.skill_flat'), rw.rows(ff).length + '');
  const kf = fieldOf(sHost, 'kill');
  check('skills.kill → 键值行（3 行，值是 bool/number 控件）', kv.rows(kf).length === 3);
  check('skills.kill 的值控件按同名 properties 给（checkbox）', kv.rows(kf)[0].all('INPUT').some((n) => n.type === 'checkbox'));
  const pp = readDoc('passive_proc.schema.json');
  const pval = { name: 'x', event: 'attack_hit', action: 'act_buff', when: [{ judge: { kind: 'res_ge' }, mp_pct: -0.1 }], also: [{ event: 'skill_hit', action: 'act_buff' }] };
  const pHost = rendered(SF, pp.$defs.passive_proc, pval, { defs: pp.$defs }).host;
  const wf = fieldOf(pHost, 'when');
  check('passive_proc.when[] → 行编辑（行内 judge 是真子表单）',
    rw.rows(wf).length === 1 && !!rw.subfield(rw.rows(wf)[0], 'when.0.judge'));
  check('passive_proc.also[] → 行编辑（行内 event 是下拉）',
    rw.subfield(fieldOf(pHost, 'also'), 'also.0.event').all('SELECT').length === 1);
  const mp = readDoc('maps.schema.json');
  const mval = { name: '镇', nodes: [{ id: 'plaza' }], roles: { hub: 'hub' }, links: { plaza: ['east'] } };
  const mHost = rendered(SF, mp.$defs.map, mval, { defs: mp.$defs }).host;
  const lf = fieldOf(mHost, 'links');
  check('maps.links → 键值行，值是「一行一条」的多行框',
    kv.rows(lf).length === 1 && !!kv.val(kv.rows(lf)[0]).all('TEXTAREA')[0]);
  check('maps.roles → 键值行', kv.rows(fieldOf(mHost, 'roles')).length === 1);
}

/* ═══════════════ 5. 突变反证（闸门必须有牙） ═══════════════ */
console.log('\n[5] 突变反证 —— 故意改坏实现，断言必须报红');
{
  const cases = [
    { name: 'kv 丢键（删行时清空整个对象）', from: 'delete cur[k];', to: 'setIn(ctx.root, path, {});',
      run: (SF2) => {
        const def = { type: 'object', properties: { m: { type: 'object', 'x-widget': 'kv', additionalProperties: { type: 'number' } } } };
        const val = { m: { a: 1, b: 2 } };
        const f = fieldOf(rendered(SF2, def, val).host, 'm');
        kv.del(f, 0).dispatch('click');
        check('突变样本（本条应当报红）：删一行只该少一个键', JSON.stringify(val.m) === '{"b":2}', JSON.stringify(val.m));
      } },
    { name: 'kv 空对象写成 {}（键丢了）', from: 'setIn(ctx.root, path.concat([nk]), defaultValue(sub, ctx));',
      to: 'setIn(ctx.root, path, {});',
      run: (SF2) => {
        const def = { type: 'object', properties: { m: { type: 'object', 'x-widget': 'kv', additionalProperties: { type: 'string' } } } };
        const val = { m: {} };
        const f = fieldOf(rendered(SF2, def, val).host, 'm');
        kv.add(f).dispatch('click');
        check('突变样本（本条应当报红）：加一行后对象里得有那个键', Object.keys(val.m).length === 1, JSON.stringify(val.m));
      } },
    { name: 'rows 丢行（加行时把数组清空）', from: 'a.push(defaultValue(rowSchemaOf(items, undefined, ctx), ctx));',
      to: 'a.length = 0; a.push(defaultValue(rowSchemaOf(items, undefined, ctx), ctx));',
      run: (SF2) => {
        const def = { type: 'object', properties: { f: { type: 'array', 'x-widget': 'rows', items: { type: 'object', properties: { n: { type: 'string' } } } } } };
        const val = { f: [{ n: 'a' }, { n: 'b' }] };
        const f = fieldOf(rendered(SF2, def, val).host, 'f');
        rw.add(f).dispatch('click');
        check('突变样本（本条应当报红）：加一行后原有行还在', val.f.length === 3 && val.f[0].n === 'a', JSON.stringify(val.f));
      } },
    { name: 'rows 删错行（删末行而不是这一行）', from: 'a.splice(i, 1);', to: 'a.splice(a.length - 1, 1);',
      run: (SF2) => {
        const def = { type: 'object', properties: { f: { type: 'array', 'x-widget': 'rows', items: { type: 'object', properties: { n: { type: 'string' } } } } } };
        const val = { f: [{ n: 'a' }, { n: 'b' }, { n: 'c' }] };
        const f = fieldOf(rendered(SF2, def, val).host, 'f');
        rw.del(f, 0).dispatch('click');
        check('突变样本（本条应当报红）：删第 1 行 → 留下的是 b、c', JSON.stringify(val.f) === '[{"n":"b"},{"n":"c"}]', JSON.stringify(val.f));
      } },
  ];
  cases.forEach((c) => {
    const hits = SRC.split(c.from).length - 1;
    check('突变「' + c.name + '」的替换点存在', hits > 0, '源码里找不到：' + c.from);
    if (!hits) return;
    const mutated = SRC.split(c.from).join(c.to);
    const r = withFresh(mutated, c.run);
    check('突变「' + c.name + '」→ 断言报红（闸门有牙）', r.fail > 0, '突变后仍全绿 = 闸门是装饰');
  });
}

console.log('\n' + '-'.repeat(46));
console.log('通过 ' + MAIN.pass + ' / 失败 ' + MAIN.fail);
MAIN.msgs.forEach((m) => console.log('  ❌ ' + m));
process.exit(MAIN.fail ? 1 : 0);
"""


def _run_node(node: str, script: str, label: str, extra: list) -> int:
    print(f"\n-- {label} --")
    if not os.path.exists(script):
        print(f"  ❌ 找不到测试脚本：{script}")
        return 1
    pr = subprocess.run([node, script] + list(extra), capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=ROOT, timeout=180,
                        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (pr.stdout or "") + (pr.stderr or "")
    print(out.rstrip())
    if pr.returncode != 0:
        print(f"  ❌ node 退出码 {pr.returncode}（上面有失败断言）")
    return 1 if pr.returncode else 0


def main() -> int:
    print("== 前端渲染器行为测试（schema_form.js · Node 打桩）==")
    node = shutil.which("node")
    if not node:
        print("  ⚠ 本机没有 node —— 跳过（前端行为需人工用浏览器验证；这不影响生成本身）")
        return 0
    rc = _run_node(node, JS_LEGACY, "① 既有门禁（textarea / lines / pct / chips）", [])
    tmpdir = tempfile.mkdtemp(prefix="sf_kvrows_")
    try:
        script = os.path.join(tmpdir, "form_kvrows_test.js")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(KVROWS_JS)
        rc |= _run_node(node, script, "② 新门禁（kv 键值行 / rows 行编辑 + 突变反证）",
                        [ROOT.replace("\\", "/")])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
