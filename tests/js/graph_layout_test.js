/* eslint-disable */
/**
 * graphLayout() 纯函数测试（Node，零依赖）—— 从 editor/web/app.js 里抠出「拓扑布局」那一段真跑。
 *
 * 跑法：node tests/js/graph_layout_test.js
 * 为什么值得：布局是最容易「画歪了却没人发现」的一段 —— 同一 depth 必须落在同一列、
 * 每条边的两端必须落在节点框上、空/坏数据不许抛异常。靠肉眼点很容易回退，这里把它钉死。
 *
 * ⚠️ app.js 是**浏览器脚本**（不是 module、不导出任何东西），所以这里用 BEGIN/END 标记
 *    把纯函数那一段抠出来 eval —— 不引入任何打包工具。若那段里出现 document / window / S，
 *    这里会直接 ReferenceError（这正是想要的门禁）。
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const SRC = fs.readFileSync(path.join(ROOT, 'editor', 'web', 'app.js'), 'utf8');
const RE = /\/\* ##GRAPH_LAYOUT_BEGIN## \*\/([\s\S]*?)\/\* ##GRAPH_LAYOUT_END## \*\//;
const m = RE.exec(SRC);
if (!m) {
  console.log('  ❌ 在 app.js 里找不到 ##GRAPH_LAYOUT_BEGIN## / ##GRAPH_LAYOUT_END## 标记');
  process.exit(1);
}
eval(m[1]);      // 直接 eval：函数声明落在本模块作用域，下面直接用

/* ───────────────────────── 断言小工具 ───────────────────────── */
let PASS = 0, FAIL = 0;
const failures = [];
function check(name, cond, detail) {
  if (cond) { PASS++; console.log('  ✅ ' + name); }
  else { FAIL++; failures.push(name + ' ' + (detail || '')); console.log('  ❌ ' + name + ' ' + (detail || '')); }
}
const byId = (L, id) => L.nodes.find((n) => n.id === id);
/** 点是否落在该节点框的边界上（横边：左右框边；竖边：上下框边）；容差 0.01 */
function onBorder(n, x, y) {
  const eps = 0.01;
  const inY = y >= n.y - eps && y <= n.y + n.h + eps;
  const inX = x >= n.x - eps && x <= n.x + n.w + eps;
  return ((Math.abs(x - n.x) < eps || Math.abs(x - (n.x + n.w)) < eps) && inY)
      || ((Math.abs(y - n.y) < eps || Math.abs(y - (n.y + n.h)) < eps) && inX);
}

/* ── 用例数据 ──
   形状取自引擎 star 拓扑的真实产出（hub 连全部非 exit；through 连 exit+hub；exit 连 hub），
   深度 = 声明序（0/1/2/3），带一条悬空边与一条不对称边。 */
const STAR = {
  topology: 'star', explicit: false, root: 'plaza', gate: 'gate',
  role_values: ['exit', 'hub', 'through'],
  nodes: [
    { id: 'plaza', role: 'hub', depth: 0, label: '中央广场' },
    { id: 'forge', role: 'through', depth: 1, label: '铁匠铺' },
    { id: 'guild', role: 'through', depth: 2, label: '冒险者公会' },
    { id: 'gate', role: 'exit', depth: 3, label: '北门' },
  ],
  edges: [['plaza', 'forge'], ['plaza', 'guild'], ['forge', 'gate'], ['guild', 'gate'], ['gate', 'plaza']],
  audit: { ok: true, dangling: [], asymmetric: [], isolated: [], unreachable: [], no_gate: false },
};

console.log('== graphLayout() 分层布局（纯函数）==');

// 1. 同深度一列、列序随 depth 升序、同列按声明序排开
{
  const L = graphLayout(STAR);
  check('节点数与输入一致（4）', L.nodes.length === 4, String(L.nodes.length));
  check('每个 depth 一列（cols=4）', L.cols === 4, String(L.cols));
  const xs = ['plaza', 'forge', 'guild', 'gate'].map((id) => byId(L, id).x);
  check('★ 不同 depth 落在不同列（x 互不相同）', new Set(xs).size === 4, JSON.stringify(xs));
  check('★ depth 越大 x 越靠右（严格递增）',
    xs[0] < xs[1] && xs[1] < xs[2] && xs[2] < xs[3], JSON.stringify(xs));
  const two = graphLayout({ nodes: [{ id: 'p', depth: 0 }, { id: 'q', depth: 0 }, { id: 'r', depth: 1 }] });
  check('同一 depth 列内 x 相同、按声明序上下排开（y 递增）',
    byId(two, 'p').x === byId(two, 'q').x && byId(two, 'q').y > byId(two, 'p').y
      && byId(two, 'r').x > byId(two, 'p').x,
    JSON.stringify(two.nodes.map((n) => [n.id, n.x, n.y])));
  check('depth 跳号也不留空列（0,2 → 两列）',
    graphLayout({ nodes: [{ id: 'a', depth: 0 }, { id: 'b', depth: 2 }] }).cols === 2);
  check('画布尺寸覆盖所有节点（含右下角）',
    L.nodes.every((n) => n.x >= 0 && n.y >= 0 && n.x + n.w <= L.width && n.y + n.h <= L.height),
    `${L.width}x${L.height}`);
}

// 2. 边：端点必须落在两端节点框的边界上
{
  const L = graphLayout(STAR);
  check('边数与输入一致（5）', L.edges.length === 5, String(L.edges.length));
  let allOn = true, bad = '';
  L.edges.forEach((e) => {
    const a = byId(L, e.from), b = byId(L, e.to);
    if (!a || !b) { allOn = false; bad = `缺节点 ${e.from}→${e.to}`; return; }
    if (!onBorder(a, e.x1, e.y1)) { allOn = false; bad = `${e.from} 起点 (${e.x1},${e.y1})`; }
    if (!onBorder(b, e.x2, e.y2)) { allOn = false; bad = `${e.to} 终点 (${e.x2},${e.y2})`; }
  });
  check('★ 每条边两端都落在节点框边界上', allOn, bad);
  const e0 = L.edges[0];
  check('目标在右 → 右出左入',
    byId(L, e0.to).x > byId(L, e0.from).x
      && e0.x1 === byId(L, e0.from).x + byId(L, e0.from).w && e0.x2 === byId(L, e0.to).x,
    JSON.stringify(e0));
  const back = L.edges.find((e) => e.from === 'gate' && e.to === 'plaza');
  check('目标在左 → 左出右入（回边不穿过节点）',
    !!back && back.x1 === byId(L, 'gate').x && back.x2 === byId(L, 'plaza').x + byId(L, 'plaza').w,
    JSON.stringify(back));
  // 同列（同一 depth）的边 → 上下出上下入
  const sameCol = graphLayout({
    nodes: [{ id: 'a', depth: 0 }, { id: 'b', depth: 0 }], edges: [['a', 'b']],
  });
  const se = sameCol.edges[0];
  check('同一列 → 竖连线（dir=v），端点仍贴框边',
    se.dir === 'v' && onBorder(byId(sameCol, 'a'), se.x1, se.y1) && onBorder(byId(sameCol, 'b'), se.x2, se.y2),
    JSON.stringify(se));
}

// 3. 悬空边 → 造虚影节点（红虚线 + 带问号），并计入画布尺寸
{
  const V = Object.assign({}, STAR, {
    edges: [['plaza', 'ghost_town'], ['forge', 'guild']],
    audit: { ok: false, dangling: [['plaza', 'ghost_town']], asymmetric: [], isolated: [], unreachable: [], no_gate: false },
  });
  const L = graphLayout(V);
  const g = byId(L, 'ghost_town');
  check('★ 悬空目标被画成虚影节点（ghost=true）', !!g && g.ghost === true, JSON.stringify(g));
  check('虚影标题带问号', !!g && / \?$/.test(g.text), g && g.text);
  check('hasGhost 标记为真', L.hasGhost === true);
  check('虚影落在真实列右侧（不压住真节点）',
    !!g && L.nodes.filter((n) => !n.ghost).every((n) => n.x + n.w <= g.x), g && String(g.x));
  check('画布比不带虚影时更宽',
    L.width > graphLayout(Object.assign({}, V, { edges: [['forge', 'guild']], audit: {} })).width,
    `${L.width} vs ${graphLayout(Object.assign({}, V, { edges: [['forge', 'guild']], audit: {} })).width}`);
  check('悬空边 kind=dangling', L.edges[0].kind === 'dangling', JSON.stringify(L.edges[0]));
  check('同一个不存在的 id 只造一个虚影（两条边指向它）',
    graphLayout(Object.assign({}, V, { edges: [['plaza', 'ghost_town'], ['forge', 'ghost_town']] }))
      .nodes.filter((n) => n.ghost).length === 1);
  check('起点不存在 → 该边直接丢弃（不抛异常）',
    graphLayout(Object.assign({}, V, { edges: [['none', 'plaza']], audit: {} })).edges.length === 0);
}

// 4. 不对称边 → kind=asym；不可达/孤立 → 置灰
{
  const V = Object.assign({}, STAR, {
    edges: [['plaza', 'forge'], ['forge', 'plaza']],
    audit: { ok: false, dangling: [], asymmetric: [['plaza', 'forge']], isolated: ['lonely'], unreachable: ['far'], no_gate: false },
    nodes: STAR.nodes.concat([{ id: 'lonely', role: '', depth: 4, label: '孤岛' },
                              { id: 'far', role: 'through', depth: 4, label: '远方' }]),
  });
  const L = graphLayout(V);
  check('不对称边 kind=asym', L.edges[0].kind === 'asym', JSON.stringify(L.edges[0]));
  check('不对称边旁边那条（有回边）仍是 ok', L.edges[1].kind === 'ok', JSON.stringify(L.edges[1]));
  check('不可达节点置灰（grey=true）', byId(L, 'far').grey === true);
  check('孤立节点置灰（grey=true）', byId(L, 'lonely').grey === true);
  check('正常节点不置灰', byId(L, 'plaza').grey === false);
}

// 5. 入口 / 出入口标记；角色取值 → 色板序号
{
  const L = graphLayout(STAR);
  check('root 标记在入口节点上', byId(L, 'plaza').isRoot === true && byId(L, 'gate').isRoot === false);
  check('gate 标记在出入口节点上', byId(L, 'gate').isGate === true && byId(L, 'plaza').isGate === false);
  check('角色色板序号按 role_values 顺序分配',
    byId(L, 'gate').roleIndex === 0 && byId(L, 'plaza').roleIndex === 1 && byId(L, 'forge').roleIndex === 2,
    `${byId(L, 'gate').roleIndex}/${byId(L, 'plaza').roleIndex}/${byId(L, 'forge').roleIndex}`);
  check('role_values 缺省时从节点里现推（配色自洽）',
    JSON.stringify(graphLayout({ nodes: [{ id: 'a', role: 'x' }, { id: 'b', role: 'y' }] }).roleValues) === '["x","y"]');
  check('没有角色的节点不给配色类（roleIndex=-1）',
    graphLayout({ nodes: [{ id: 'a' }, { id: 'b', role: 'r' }] }).nodes[0].roleIndex === -1);
  check('超长标题被截断（SVG 没有 text-overflow）',
    graphLayout({ nodes: [{ id: 'a', label: '一二三四五六七八九十十一十二十三' }] }).nodes[0].text.length === 12);
  check('未给 label 时回落到 id', graphLayout({ nodes: [{ id: 'only_id' }] }).nodes[0].text === 'only_id');
}

// 6. 空 / 坏输入不许崩
{
  const cases = [[null, 'null'], [undefined, 'undefined'], [{}, '{}'], [{ nodes: [] }, '空 nodes'],
                 [{ nodes: null, edges: null }, 'nodes=null'], [{ nodes: [null, {}] }, '脏节点'],
                 [{ nodes: [{ id: 'a' }], edges: [null, [], ['a']] }, '脏边'], ['字符串', '字符串']];
  let ok = true, detail = '';
  cases.forEach(([v, why]) => {
    try {
      const L = graphLayout(v);
      if (!Array.isArray(L.nodes) || !Array.isArray(L.edges) || typeof L.width !== 'number') {
        ok = false; detail = why + ' → ' + JSON.stringify(L);
      }
    } catch (e) { ok = false; detail = why + ' → ' + e.message; }
  });
  check('★ 空 / 坏输入一律不抛异常且结构完整', ok, detail);
  const E = graphLayout(null);
  check('空输入 → 空图（0 节点 / 0 边 / 0x0）',
    E.nodes.length === 0 && E.edges.length === 0 && E.width === 0 && E.height === 0,
    JSON.stringify(E));
}

console.log('\n' + '-'.repeat(46));
console.log(`通过 ${PASS} / 失败 ${FAIL}`);
failures.forEach((f) => console.log('  ❌ ' + f));
process.exit(FAIL ? 1 : 0);
