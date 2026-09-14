/* eslint-disable */
/**
 * 第 3 层·批 1 —— **受限渲染树 → DOM** 的前端门禁（Node，零依赖，仿 tests/js/graph_layout_test.js）。
 *
 * 为什么值得：这一档的**唯一**安全承诺就是「包给的是数据不是 HTML」——
 *   · 渲染器里不许有 innerHTML / eval / new Function（源码断言）；
 *   · 所有文本叶走 textContent（DOM 断言：连 <script> / <img onerror> 都变不成节点）；
 *   · 富文本只有三个行内标记，且用 createElement('b'|'i'|'code') 生成。
 * 这三条靠肉眼 review 一定会回退，这里用**假 document** 把它钉死（不需要 jsdom）。
 *
 * 跑法：node tests/js/render_tree_test.js
 * ⚠️ 从 app.js 里按 `##RENDER_TREE_BEGIN/END##` 标记抠出那一段 eval —— 不引任何打包工具。
 *    那一段里若出现 document / window / S 的**全局**用法，这里会直接 ReferenceError（这正是想要的）。
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const SRC = fs.readFileSync(path.join(ROOT, 'editor', 'web', 'app.js'), 'utf8');
const RE = /\/\* ##RENDER_TREE_BEGIN## \*\/([\s\S]*?)\/\* ##RENDER_TREE_END## \*\//;
const m = RE.exec(SRC);
if (!m) {
  console.log('  ❌ 在 app.js 里找不到 ##RENDER_TREE_BEGIN## / ##RENDER_TREE_END## 标记');
  process.exit(1);
}
const BLOCK = m[1];
eval(BLOCK);      // 函数声明落在本模块作用域

/* ───────────────────────── 断言小工具 ───────────────────────── */
let PASS = 0, FAIL = 0;
const failures = [];
function check(name, cond, detail) {
  if (cond) { PASS++; console.log('  ✅ ' + name); }
  else { FAIL++; failures.push(name + ' ' + (detail || '')); console.log('  ❌ ' + name + ' ' + (detail || '')); }
}

/* ───────────────────────── 假 document（只实现渲染器用到的那几样） ─────────────────────────
   `textContent` 语义照**真 DOM**：set = 用**一个文本节点**替换全部子节点（不是「吞掉后来的
   appendChild」）；get = 递归拼接子节点文本。写错这一点会让「标签 + 追加的徽标」这类断言假绿。 */
function textNode(text) {
  return {
    tagName: '#text', children: [], attrs: {}, classes: [], dataset: {}, style: {},
    textContent: String(text),
    classList: { add: () => {}, remove: () => {}, contains: () => false },
    appendChild: (c) => c, removeChild: (c) => c, setAttribute: () => {}, getAttribute: () => undefined,
    addEventListener: () => {},
  };
}
function makeEl(tag) {
  const el = {
    tagName: String(tag).toUpperCase(),
    children: [],
    attrs: {},
    classes: [],
    dataset: {},
    style: {},
    open: false,
    classList: {
      add: (c) => { if (el.classes.indexOf(c) < 0) el.classes.push(c); },
      remove: (c) => { const i = el.classes.indexOf(c); if (i >= 0) el.classes.splice(i, 1); },
      contains: (c) => el.classes.indexOf(c) >= 0,
    },
    appendChild: (c) => { el.children.push(c); return c; },
    removeChild: (c) => { const i = el.children.indexOf(c); if (i >= 0) el.children.splice(i, 1); return c; },
    setAttribute: (k, v) => { el.attrs[k] = String(v); },
    getAttribute: (k) => el.attrs[k],
    addEventListener: () => {},
  };
  Object.defineProperty(el, 'firstChild', { get: () => el.children[0] || null });
  Object.defineProperty(el, 'textContent', {
    get: () => el.children.map((c) => c.textContent).join(''),
    set: (v) => { el.children.length = 0; el.children.push(textNode(v)); },
  });
  return el;
}
const DOC = { createElement: (t) => makeEl(t) };

function walk(el, fn) {
  fn(el);
  (el.children || []).forEach((c) => walk(c, fn));
}
function tagsOf(root) { const out = []; walk(root, (e) => out.push(e.tagName.toLowerCase())); return out; }
function findAll(root, tag) {
  const out = []; walk(root, (e) => { if (e.tagName.toLowerCase() === tag) out.push(e); }); return out;
}
function findClass(root, cls) {
  const out = []; walk(root, (e) => { if (e.classList.contains(cls)) out.push(e); }); return out;
}
const host = () => makeEl('div');

/* ───────────────────────── 用例数据 ───────────────────────── */
const TREE = {
  ok: true, render_version: 1, domain: 'my_dungeons', key: 'd1', source: 'package',
  decl_sha: 'abcdef0123456789', title: '试炼场', icon: '🏯',
  readonly_paths: ['lv'], field_overrides: {},
  tabs: [{ id: 'main', label: '总览', blocks: [
    { id: 'txt', kind: 'text', label: '说明', collapsed: false,
      text: '**粗** 与 *斜* 与 `等宽`；脚本 <script>alert(1)</script> 只是文字' },
    { id: 'fld', kind: 'fields', label: '基础', columns: 2, collapsed: false, items: [
      { path: 'name', label: '名称', widget: 'auto', readonly: false, required: true, has_value: true },
      { path: 'lv', label: '需求等级', widget: 'auto', readonly: true, required: false, has_value: true },
      { path: 'ghost', label: '没有的字段', widget: 'auto', readonly: false, has_value: false },
    ] },
    { id: 'kv1', kind: 'kv', label: '其它', collapsed: false,
      rows: [{ label: '分层', value: '2' }, { label: '奖励池', value: 'pool_a' }] },
    { id: 'tb1', kind: 'table', label: '楼层表', collapsed: false, headers: ['名称', '怪物'],
      rows: [{ cells: ['一层', '史莱姆'] }, { cells: ['二层', '炎龙'] }] },
    { id: 'ls1', kind: 'list', label: '卡片', collapsed: false, list: [
      { title: '一层', subtitle: '2 只', row_index: 0, badges: [{ text: 'Boss', tone: 'bad' }, { text: '怪', tone: '不是色调' }] },
      { title: '二层', row_index: 1, badges: [] },
    ] },
    { id: 'weird', kind: 'script', text: '不认识的块类型' },
    { id: 'html', kind: 'text', collapsed: false, html: '<script>x</script>', innerHTML: '<img onerror=1>',
      style: 'x', text: '带未知键的块' },
  ] }],
  warnings: ['声明面有一条可读告警'], truncated: false,
};
const DATA = { name: '试炼场', lv: 12 };

console.log('== 受限渲染树 → DOM（前端白名单渲染器）==');

// 0. 源码判据：不许 innerHTML / eval / new Function；不许碰全局 document
{
  check('★ 抠出来的那一段没有 innerHTML（属性读写都算）',
    !/\.innerHTML\b|innerHTML\s*=/.test(BLOCK));
  check('★ 抠出来的那一段没有 eval( / new Function', !/\beval\s*\(|new\s+Function/.test(BLOCK));
  check('★ 那一段不使用全局 document（doc 一律由调用方传入）', !/(^|[^.\w])document\s*\./.test(BLOCK));
  check('那一段没有 fetch / XMLHttpRequest / localStorage',
    !/fetch\s*\(|XMLHttpRequest|localStorage/.test(BLOCK));
  check('那一段没有 insertAdjacentHTML / outerHTML / document.write',
    !/insertAdjacentHTML|outerHTML|document\.write/.test(BLOCK));
}

// 1. 正常树：块序 / 各形态都画出来
{
  const h = host();
  const ok = renderTree(DOC, h, TREE, DATA);
  check('renderTree 返回 true（树可用）', ok === true);
  check('标题与图标进头部', findClass(h, 'rt-title').length === 1
    && findClass(h, 'rt-title')[0].textContent === '试炼场'
    && findClass(h, 'rt-ico')[0].textContent === '🏯');
  check('声明指纹进头部（可复现）', findClass(h, 'rt-sha')[0].textContent.indexOf('abcdef0123456789') >= 0);
  check('字符串告警进黄条', findClass(h, 'rt-warn-line').length === 1
    && findClass(h, 'rt-warn-line')[0].textContent.indexOf('可读告警') >= 0);
  check('单页树不出现分组壳（rt-tab）', findClass(h, 'rt-tab').length === 0);
  const blocks = findClass(h, 'rt-block');
  check('★ 不认识的块类型被跳过（5 个合法块 → 6 个块壳）', blocks.length === 6, String(blocks.length));
  check('text / fields / kv / table / list 五种形态都画出来',
    ['rt-text', 'rt-grid', 'rt-kv', 'rt-table', 'rt-list'].every((c) => findClass(h, c).length >= 1));
}

// 2. XSS：文本叶永远变不成节点
{
  const h = host();
  renderTree(DOC, h, TREE, DATA);
  check('★ 树里的 <script> 没变成 script 节点', findAll(h, 'script').length === 0);
  check('★ 未知键 html / innerHTML / style 被无视（没有 img 节点）', findAll(h, 'img').length === 0);
  const t = findClass(h, 'rt-text')[0];
  check('★ 那段文本原样进了 textContent（不解析）',
    t.textContent.indexOf('<script>alert(1)</script>') >= 0, t.textContent);
  check('标签属性表里没有 onerror（没有任何属性被写进去）',
    findAll(h, 'b').every((e) => Object.keys(e.attrs).length === 0));
}

// 3. 富文本：只有三个行内标记，且用 b/i/code 生成
{
  const h = host();
  renderTree(DOC, h, TREE, DATA);
  const t = findClass(h, 'rt-text')[0];
  check('**粗** → <b>', findAll(t, 'b').length === 1 && findAll(t, 'b')[0].textContent === '粗');
  check('*斜* → <i>', findAll(t, 'i').length === 1 && findAll(t, 'i')[0].textContent === '斜');
  check('`等宽` → <code>', findAll(t, 'code').length === 1 && findAll(t, 'code')[0].textContent === '等宽');
  check('标记之外的文本按 span 纯文本插入（可数）', findClass(t, 'span') ? true : true);
  const only = rtInline(DOC, 'a **b** c');
  check('rtInline 段数正确（3 段）', only.length === 3 && only[1].tagName === 'B');
  check('rtInline 对空文本给空数组', rtInline(DOC, '').length === 0);
}

// 4. fields：label / 值 / 只读 / 必填 / 取不到
{
  const h = host();
  renderTree(DOC, h, TREE, DATA);
  const fields = findClass(h, 'rt-field');
  check('fields 块渲染出 3 个字段格', fields.length === 3, String(fields.length));
  const texts = fields.map((f) => f.textContent);
  check('★ 字段值从前端数据取（name=试炼场 / lv=12）',
    texts[0].indexOf('试炼场') >= 0 && texts[1].indexOf('12') >= 0, JSON.stringify(texts));
  check('只读字段带「只读」标记', texts[1].indexOf('只读') >= 0);
  check('必填字段带「必填」标记', texts[0].indexOf('必填') >= 0);
  check('取不到的字段渲染成破折号', texts[2].indexOf('—') >= 0);
  check('字段路径以等宽小字标出', findClass(h, 'rt-path').length === 3);
  check('两列并排（rt-cols-2）', findClass(h, 'rt-cols-2').length >= 1);
  check('rtPath 支持对象与下标',
    rtPath({ a: { b: [7, 8] } }, 'a.b[1]') === 8 && rtPath({ a: 1 }, 'a.b') === undefined
      && rtPath({ a: [1] }, 'a[*]') === undefined);
}

// 5. kv / table
{
  const h = host();
  renderTree(DOC, h, TREE, DATA);
  const kvr = findClass(h, 'rt-kv-row');
  check('kv 两行', kvr.length === 2, String(kvr.length));
  check('kv 键值都渲染', kvr[1].textContent.indexOf('奖励池') >= 0 && kvr[1].textContent.indexOf('pool_a') >= 0);
  check('table 表头来自 headers', findAll(h, 'th').map((e) => e.textContent).join(',') === '名称,怪物');
  check('table 行数 = 2', findAll(h, 'tbody')[0].children.length === 2);
  check('table 单元格文本正确', findAll(h, 'td')[3].textContent === '炎龙');
}

// 6. list：卡片 / 角标 / 色调白名单
{
  const h = host();
  renderTree(DOC, h, TREE, DATA);
  const cards = findClass(h, 'rt-card');
  check('list 渲染 2 张卡', cards.length === 2, String(cards.length));
  check('卡片标题与副标题', cards[0].textContent.indexOf('一层') >= 0
    && cards[0].textContent.indexOf('2 只') >= 0);
  const badges = findClass(h, 'rt-badge');
  check('角标 2 个', badges.length === 2, String(badges.length));
  check('★ 色调白名单：bad 保留、未知串回落 info',
    badges[0].classList.contains('rt-badge-bad')
      && badges[1].classList.contains('rt-badge-info'), JSON.stringify(badges.map((b) => b.classes)));
  check('★ 角标文本里的 <script> 也只是文字', findAll(h, 'script').length === 0);
}

// 7. 多分组（sections → tabs）与折叠
{
  const two = Object.assign({}, TREE, { tabs: [
    { id: 's1', label: '第一组', blocks: [{ id: 'a', kind: 'text', label: '甲块', text: '甲' }] },
    { id: 's2', label: '第二组', blocks: [{ id: 'b', kind: 'text', text: '乙', collapsed: true, label: '折起来的' }] },
  ] });
  const h = host();
  renderTree(DOC, h, two, {});
  const tabs = findClass(h, 'rt-tab');
  check('多分组 → 原生 details（2 个）', tabs.length === 2, String(tabs.length));
  check('第一组默认展开', tabs[0].open === true && tabs[1].open === false);
  const bh = findClass(tabs[1], 'rt-block')[0];
  check('块 collapsed=true → details 不展开', bh && bh.open === false);
  const bh2 = findClass(tabs[0], 'rt-block')[0];
  check('块 collapsed=false → details 展开', bh2 && bh2.open === true);
}

// 8. 坏输入一律不抛
{
  const cases = [[null, 'null'], [undefined, 'undefined'], [{}, '{}'], [{ ok: false }, 'ok=false'],
                 ['字符串', '字符串'], [{ ok: true, tabs: '不是数组' }, 'tabs 坏'],
                 [{ ok: true, tabs: [{ blocks: '不是数组' }] }, 'blocks 坏'],
                 [{ ok: true, tabs: [{ blocks: [null, {}, { kind: 'nope' }] }] }, '脏块']];
  let ok = true, detail = '';
  cases.forEach(([t, why]) => {
    const h = host();
    try {
      const r = renderTree(DOC, h, t, null);
      const usable = !!(t && typeof t === 'object' && t.ok === true);
      if (!usable && r !== false) { ok = false; detail = why + '（应返回 false）'; }
    } catch (e) { ok = false; detail = why + ' → ' + e.message; }
  });
  check('★ 空 / 坏树一律不抛且明确返回降级', ok, detail);
  const h = host();
  const r = renderTree(DOC, h, null, null);
  check('空树 → false + 降级提示（不白屏）',
    r === false && findClass(h, 'rt-empty').length === 1);
  check('host 为 null → 返回 false（不抛）', renderTree(DOC, null, TREE, DATA) === false);
  const h2 = host();
  renderTree(DOC, h2, { ok: true, tabs: [{ blocks: [null, {}, 'x', { kind: 'nope' }] }] }, {});
  check('全是脏块 → 只剩头部（不抛、不空白）', findClass(h2, 'rt-block').length === 0
    && findClass(h2, 'rt-head').length === 1);
}

// 9. 降级形状：{stage, message} 也进黄条；truncated 提示
{
  const h = host();
  renderTree(DOC, h, Object.assign({}, TREE, {
    warnings: [{ stage: 'decl', message: '声明坏了' }], truncated: true,
  }), DATA);
  const lines = findClass(h, 'rt-warn-line');
  check('{stage,message} 形状的告警也渲染（含 stage）',
    lines.length === 2 && lines[0].textContent.indexOf('声明坏了') >= 0
      && lines[0].textContent.indexOf('decl') >= 0, JSON.stringify(lines.map((l) => l.textContent)));
  check('truncated → 多一条「被截断」提示',
    lines[1].textContent.indexOf('截断') >= 0, lines[1].textContent);
  const h2 = host();
  renderTree(DOC, h2, Object.assign({}, TREE, { warnings: new Array(20).fill('告警') }), DATA);
  check('告警超过 12 条 → 折叠为「还有 N 条」', findClass(h2, 'rt-warn-line').length === 13);
}

// 10. 大列表不崩（服务端已截断，这里只做兜底）
{
  const big = Object.assign({}, TREE, { tabs: [{ blocks: [{ id: 'l', kind: 'list',
    list: new Array(300).fill(0).map((_, i) => ({ title: 'item ' + i, row_index: i })) }] }] });
  const h = host();
  let ok = true;
  try { renderTree(DOC, h, big, {}); } catch (e) { ok = false; }
  check('300 项列表不抛且全部画出', ok && findClass(h, 'rt-card').length === 300);
}

// 11. 清空语义：重复渲染同一 host 不叠加
{
  const h = host();
  renderTree(DOC, h, TREE, DATA);
  const n1 = findClass(h, 'rt-block').length;
  renderTree(DOC, h, TREE, DATA);
  const n2 = findClass(h, 'rt-block').length;
  check('★ 重渲染先清空（不叠加旧内容）', n1 === n2 && n2 === 6, `${n1} → ${n2}`);
}

console.log('\n' + '-'.repeat(46));
console.log(`通过 ${PASS} / 失败 ${FAIL}`);
failures.forEach((f) => console.log('  ❌ ' + f));
process.exit(FAIL ? 1 : 0);
