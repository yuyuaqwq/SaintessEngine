// 能力开关的渲染回归：node + 最小 DOM 打桩，真调 app.js 里的渲染器。
// 用法：node node/test_capabilities.js
// 无 node 时由 Python 侧显式跳过（见 tests/test_editor_capabilities.py）。
'use strict';

/* ── 最小 DOM 打桩（只够渲染器跑）────────────────────────────────
   ★ className 与 classList 必须双向同步 —— 真实 DOM 里 el.className='a b'
     之后 el.classList.contains('b') 为真。各存一份会让测试假绿/假红。 */
function makeEl(tag) {
  const el = {
    tagName: (tag || 'div').toUpperCase(),
    children: [], dataset: {}, style: {}, attributes: {},
    _cls: new Set(), _html: '', textContent: '', value: '', checked: false,
    get className() { return Array.from(this._cls).join(' '); },
    set className(v) { this._cls = new Set(String(v || '').split(/\s+/).filter(Boolean)); },
    get classList() {
      const self = this;
      return {
        contains(c) { return self._cls.has(c); },
        add(c) { self._cls.add(c); },
        remove(c) { self._cls.delete(c); },
        toggle(c, force) {
          const on = force === undefined ? !self._cls.has(c) : !!force;
          if (on) self._cls.add(c); else self._cls.delete(c);
          return on;
        },
      };
    },
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = String(v); },
    appendChild(c) { this.children.push(c); return c; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    closest() { return makeEl('label'); },
    addEventListener() {},
    remove() {},
  };
  return el;
}

const REG = {};
function stubEl(id) {
  if (!REG[id]) REG[id] = makeEl('div');
  return REG[id];
}
global.document = {
  createElement: makeEl,
  getElementById: (id) => REG[id] || null,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener() {},
  documentElement: makeEl('html'),
  body: makeEl('body'),
  hidden: false,
};
global.window = { devicePixelRatio: 1.5, addEventListener() {}, matchMedia: () => ({ matches: false, addEventListener() {} }) };
global.localStorage = { _d: {}, getItem(k) { return this._d[k] || null; }, setItem(k, v) { this._d[k] = String(v); }, removeItem(k) { delete this._d[k]; } };
global.requestAnimationFrame = (f) => setTimeout(f, 0);
global.setTimeout = global.setTimeout || ((f) => f());
global.location = { hash: '', search: '', pathname: '/' };

let PASS = 0, FAIL = 0;
function check(name, cond, extra) {
  if (cond) { PASS++; console.log('  ok   ' + name); }
  else { FAIL++; console.log('  FAIL ' + name + (extra === undefined ? '' : '  ' + JSON.stringify(extra))); }
}

/* ── 抠出被测的三段（与 app.js 逐字一致，靠标记切）──────────────── */
const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, '..', 'editor', 'web', 'app.js'), 'utf8');

const iRef = src.indexOf('function refClass(');   // 渲染器那段从它开始
const iCap = src.indexOf('async function renderCapabilities(');
const iEnd = src.indexOf('async function savePkg(');
if (iRef < 0 || iCap < 0 || iEnd < 0) {
  console.log('  FAIL 抠不出被测函数（标记找不到）'); process.exit(1);
}
// ★ 切片起点取两者中**更早**的那个 —— 文件里 refClass 排在 renderCapabilities 之后，
//   只按 iRef 切会把渲染器整段漏掉（第一次就是这么红的）。
const code = src.slice(Math.min(iRef, iCap), iEnd);

// 造一个受控环境：给渲染器它要的 $ / api / S / esc
const S = { pkgId: 'orlandia' };
const elements = { capList: stubEl('capList'), capSum: stubEl('capSum'), capTrial: stubEl('capTrial'),
                   capDetail: stubEl('capDetail') };   // ★ 2026-09-24：详情面板容器
// ★ 打桩要够真：真实 DOM 里 innerHTML 设完之后 querySelectorAll('.cap-cb') 查得到那些
//   复选框。恒返回 [] 会让 capSummary 永远算成「装了 0 / N」—— 那是打桩的假红。
elements.capList.querySelectorAll = (sel) => {
  if (sel !== '.cap-cb') return [];
  const out = [];
  const re = /<input type="checkbox" class="cap-cb" data-ext="([^"]+)"( checked)?>/g;
  let m;
  while ((m = re.exec(elements.capList.innerHTML)) !== null) {
    out.push({ checked: !!m[2], dataset: { ext: m[1] },
               closest: () => makeEl('label'), addEventListener() {} });
  }
  return out;
};
global.S = S;
global.$ = (id) => elements[id] || stubEl(id);
global.esc = (s) => String(s === undefined || s === null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
global.FAKE = null;
global.api = async () => ({ ok: true, json: global.FAKE });

const sandbox = { S, $: global.$, esc: global.esc, api: global.api, CAP: null, CAP_SEL: null, capTimer: null };
const factory = new Function('S', '$', 'esc', 'api', 'CAP', 'CAP_SEL',
  code + '\n; return {refClass, renderCapabilities, capSelect, capChecked, capSummary, capTrial,'
       + ' get CAP(){return CAP;}, get SEL(){return CAP_SEL;}};');
const M = factory(S, global.$, global.esc, global.api, sandbox.CAP, sandbox.CAP_SEL);

console.log('【1. refClass 分档】');
check('0 处 → ok 档', M.refClass(0) === 'ok', M.refClass(0));
check('3 处 → 无标注', M.refClass(3) === '', M.refClass(3));
check('8 处 → warn', M.refClass(8) === 'warn', M.refClass(8));
check('492 处 → bad', M.refClass(492) === 'bad', M.refClass(492));

console.log('【2. renderCapabilities 真渲染】');
global.FAKE = {
  ok: true,
  enabled: ['ext_combat', 'ext_loot'],
  trial: { domains_before: 106, domains_after: 106, loses_domains: [], refs_cut: 0, ref_files_cut: [] },
  extensions: [
    { id: 'ext_combat', name: '战斗', desc: 'CTB 骨架', version: '0.1.0', author: '鱼鱼', kind: 'extension', engine: '>=0.1', entry: 'apply.py', created: '2026-09-23', modules: ['battle', 'gauge'], lines: 1, domains: ['effect_rules'], provides: ['battle'], depends: [], enabled: true, refs: 492, ref_files: [['content/combat_cmds.py', [12, 34]]], ref_all: [], loses_domains: ['effect_rules', 'passive_proc'] },
    { id: 'ext_loot', name: '掉落', desc: '', modules: ['loot'], lines: 1, domains: ['drop_pools'], provides: [], depends: [], enabled: true, refs: 7, ref_files: [], ref_all: [], loses_domains: ['drop_pools'] },
    { id: 'ext_dialogue', name: '对话', desc: '', modules: ['dialogue'], lines: 1, domains: [], provides: [], depends: [], enabled: false, refs: 4, ref_files: [], ref_all: [], loses_domains: [] },
  ],
};
(async () => {
  await M.renderCapabilities();
  const html = elements.capList.innerHTML;
  check('渲染出 3 行', (html.match(/<div class="cap-row/g) || []).length === 3);
  check('ext_combat 行有 492 处引用且标 bad', html.includes('492 处引用') && html.includes('cap-refs bad'));
  check('未装的 ext_dialogue 复选框不勾', /data-ext="ext_dialogue"[^>]*>/.test(html) && !/data-ext="ext_dialogue"[^>]*checked/.test(html));
  check('已装的 ext_combat 复选框勾上', /data-ext="ext_combat"[^>]*checked/.test(html));
  check('provides 出 chip', html.includes('>battle</span>'));
  check('关掉会失去的域写进行里', html.includes('失去 effect_rules'));
  check('汇总条给出「装了 N / M」与域数', /装了 2 \/ 3/.test(elements.capSum.textContent) && /有效域 106/.test(elements.capSum.textContent));

  console.log('【2b. 可选中 + 详情面板（2026-09-24）】');
  check('行是可选中的 div（不是 label，避免点行就改勾选）',
        /<div class="cap-row/.test(html) && !/<label class="cap-row/.test(html));
  check('行给键盘焦点（tabindex=0）', /class="cap-row[^"]*"\s+data-ext="ext_combat" tabindex="0"/.test(html));
  check('行显示显示名 + id + 版本', html.includes('>战斗</span>') && html.includes('>ext_combat</span>')
        && html.includes('v0.1.0'));
  check('默认选中第一个已装包', M.SEL === 'ext_combat', M.SEL);
  check('选中行带 selected', /class="cap-row selected"/.test(html), html.slice(0, 80));
  const det = () => elements.capDetail.innerHTML;
  check('详情给出 版本 / 作者 / 描述', det().includes('v0.1.0') && det().includes('鱼鱼')
        && det().includes('CTB 骨架'), det().slice(0, 120));
  check('详情给出 id / 类型 / 入口 / 建档', det().includes('ext_combat') && det().includes('extension')
        && det().includes('apply.py') && det().includes('2026-09-23'));
  check('详情标「已装」', det().includes('已装'));
  check('详情列出提供的域与能力', det().includes('effect_rules') && det().includes('battle'));
  check('详情可展开引用位置', det().includes('content/combat_cmds.py'));
  M.capSelect('ext_dialogue');
  check('切换选中：状态跟着走', M.SEL === 'ext_dialogue', M.SEL);
  check('切换选中：未装包标「未装」', det().includes('未装'), det().slice(0, 90));
  check('切换选中：资料换成了新的包', det().includes('ext_dialogue') && !det().includes('CTB 骨架'));

  console.log('【3. capChecked 读得到勾选状态】');
  elements.capList.querySelectorAll = () => ([
    { checked: true, dataset: { ext: 'ext_combat' }, closest: () => makeEl('label') },
    { checked: false, dataset: { ext: 'ext_loot' }, closest: () => makeEl('label') },
  ]);
  check('只返回勾上的', JSON.stringify(M.capChecked()) === '["ext_combat"]', M.capChecked());

  console.log('\n===== 结果：PASS=' + PASS + ' FAIL=' + FAIL + ' =====');
  process.exit(FAIL ? 1 : 0);
})();
