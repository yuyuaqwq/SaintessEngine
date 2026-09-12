#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：编辑器扛得住「大包」—— 合成 2000 条物品 + 若干其它域，真起 HTTP 量。

为什么需要它
------------
小样例（1~5 条）跑得飞快，掩盖了两类只会在大包上出现的问题：

  ① **接口把同一份重复劳动做很多遍**：域概览 / 条目列表 / 全包校验都要「每条跑一遍 schema 校验」，
     2000 条物品实测单次 ~160ms（jsonschema），5000 条约 0.4s，且改一条要重算整包。
     优化后按「条目内容」缓存：改一条只重算那一条（见 editor/server.py 的 _VAL_CACHE 一段）。
  ② **前端把整表铺进 DOM**：2000 行一次性 innerHTML，实测光是浏览器布局就 ~1s，
     于是「打开域 / 搜索 / 打开单条 / 保存后刷新」全卡在同一处。
     优化后是定高虚拟滚动（editor/web/app.js 的 lvSlice）。

本门禁钉住四件事（都是「能不能接真数据」的硬门槛）：
  1. 域列表 / 包概览的条目数正确（2000 条不被截断、不被算漏）
  2. 条目列表 / 包概览接口的响应时间有上限（大包下不许退化成秒级）
  3. 搜索 + 虚拟滚动窗口的「算账部分」正确（从 app.js 抠出纯函数，用 node 真跑）
  4. 保存单条后能原样读回，且列表/概览立刻反映新值（校验缓存的失效要正确）

跑法：python tests/test_editor_large_package.py
退出码：0 = 全过（本机无 node 时第 3 项显式跳过）；1 = 有失败。
说明：临时包目录建在系统临时目录、跑完即删；测试服务绑 127.0.0.1:0（随机端口），
      与本机 8766 上正在用的编辑器互不干扰。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from editor import packages as PK          # noqa: E402
from editor import server as SRV           # noqa: E402
from editor import validate as VD          # noqa: E402

ITEMS = 2000                               # 真数据里物品域一次就是 1704 条，这里按 2000 压
MONSTERS = 300
MAPS = 20

# 响应时间上限（毫秒）。实测（本机、服务进程设高优先级、2000 条物品）：
#   优化前：条目列表 178ms 冷 / 187ms 热，包概览 229ms 冷 / 224ms 热
#   优化后：条目列表  85ms 冷 /  31ms 热，包概览 107ms 冷 /  31ms 热
# 阈值留足余量（机器忙、无 jsonschema 走内置最小校验器都会改变数值），
# 目的是挡住「退化成秒级 / 每次全量重算」这类回归，不是卡到毫秒。
MEDIAN_MS = 500
FIRST_MS = 2000

PASS = 0
FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name} {detail}")
        print(f"  ❌ {name} {detail}")


# ---------------- 合成大包 ----------------
QUALITIES = ["white", "green", "blue", "purple", "orange"]
TYPES = ["材料", "消耗品", "装备", "任务物品", "货币"]


def make_items(n: int) -> dict:
    out = {}
    for i in range(n):
        out[f"it_{i:05d}"] = {
            "name": f"物品{i:05d}·试验装备",
            "desc": f"第 {i} 条合成物品，用于压测（描述长度中等，模拟真实文案）。",
            "price": (i * 7) % 9000 + 1,
            "type": TYPES[i % len(TYPES)],
            "quality": QUALITIES[i % len(QUALITIES)],
            "battle_ok": i % 3 == 0,
            "stamina": i % 40,
        }
    return out


def make_monsters(n: int) -> dict:
    return {f"mo_{i:04d}": {"name": f"怪物{i:04d}", "kind": "物理" if i % 2 else "魔法",
                            "desc": f"第 {i} 只合成怪物。", "power": 1.0 + (i % 20) / 10}
            for i in range(n)}


def make_maps(n: int) -> dict:
    out = {}
    for i in range(n):
        out[f"map_{i:03d}"] = {
            "name": f"地图{i:03d}", "topology": "star", "roles": {"hub": "hub", "exit": "exit"},
            "nodes": [{"id": f"m{i}_n{j}", "name": f"节点{j}", "role": "hub" if j == 0 else "exit"}
                      for j in range(12)],
        }
    return out


# ---------------- 整包（13 域一起）：每个域的 schema 校验路径 / 域级缓存都要能扛 ----------------
# 量级取小（测试要快），但**形状**与真数据同源：物品 200 / 技能 100 / 怪物 100 / 文案 100 …
FULL_COUNTS = {
    "items": 200, "skills": 100, "monsters": 100, "affixes": 50, "effect_rules": 20,
    "passive_proc": 20, "commands": 50, "texts": 100, "tlogs": 10, "maps": 5,
    "drop_pools": 20, "instances": 5, "classes": 10,
}


def full_entry(dom: str, i: int) -> dict:
    """各域一条**合法**数据（形状照 schema 的 required / 嵌套引用；测的是校验与缓存路径）。"""
    if dom == "items":
        return {"name": f"物品{i:04d}", "desc": f"第 {i} 条。", "price": i + 1,
                "type": TYPES[i % len(TYPES)], "quality": QUALITIES[i % len(QUALITIES)],
                "effect_data": {"channels": {"on_hit": {"atk": 1.0}}}}
    if dom == "skills":
        return {"name": f"技能{i:04d}", "kind": "物理" if i % 2 else "魔法", "lv": 1, "desc": f"第 {i} 条。",
                "mp": 5, "formula": [{"stat": "atk", "mult": 1.0, "type": "phys"}], "mech": "charge", "mech_val": 1}
    if dom == "monsters":
        return {"name": f"怪物{i:04d}", "kind": "物理", "desc": f"第 {i} 只。", "power": 1.0,
                "formula": [{"stat": "atk", "mult": 1.0, "type": "phys"}]}
    if dom == "affixes":
        return {"name": f"词条{i:04d}", "kind": "attack", "trigger": "on_hit", "desc": f"第 {i} 条。",
                "chance": 0.5, "effect": {"stat": "atk", "value": 1}, "line": "攻击 +1"}
    if dom == "effect_rules":
        return {"name": f"资源{i:04d}", "cap": 100, "panel": {"stat": "atk", "op": "mul", "mult": 1.0},
                "consume": {"mode": "skip"}, "channels": {"on_hit": 1}}
    if dom == "passive_proc":
        return {"event": "attack_hit", "action": f"proc_{i}", "domain": "cap", "res": f"res_{i}"}
    if dom == "commands":
        return {"key": f"cmd_{i:03d}", "patterns": [f"指令{i}"], "desc": f"第 {i} 条。", "category": "战斗"}
    if dom == "texts":
        return {"key": f"txt_{i:04d}", "value": f"第 {i} 条文案 {{player}}", "desc": f"第 {i} 条说明",
                "category": "item", "params": ["player"]}
    if dom == "tlogs":
        return {"kind": f"domain.event_{i:02d}", "fields": ["actor", "amount"], "category": "battle"}
    if dom == "maps":
        return {"name": f"地图{i:03d}", "topology": "star", "roles": {"hub": "hub", "exit": "exit"},
                "nodes": [{"id": f"m{i}_n{j}", "name": f"地点{j}", "role": "hub" if j == 0 else "exit"}
                          for j in range(4)]}
    if dom == "drop_pools":
        return {"type": "weighted", "entries": [{"item": f"ite_{i:05d}", "w": 10}],
                "rolls": [{"pool": f"pool_{i:03d}", "chance": 0.5}]}
    if dom == "instances":
        return {"name": f"副本{i:02d}", "lv": 10, "stages": [{"name": "一层", "monsters": [f"mon_{i:05d}"]}],
                "entry": {"name": "入口"}}
    return {"name": f"职业{i:02d}", "desc": f"第 {i} 个（该域无 schema）。"}


def build_full_pkg(root: str) -> str:
    pkg = os.path.join(root, "full_game")
    PK.create_package("full_game", "整包压测", "13 域", list(PK.DOMAINS), root)
    for dom, n in FULL_COUNTS.items():
        PK.write_json(PK.domain_path(pkg, dom), {f"{dom[:3]}_{i:05d}": full_entry(dom, i) for i in range(n)})
    return pkg


def build_pkg(root: str) -> str:
    pkg = os.path.join(root, "big_game")
    data = {"items": make_items(ITEMS), "monsters": make_monsters(MONSTERS), "maps": make_maps(MAPS)}
    for dom, tbl in data.items():
        PK.write_json(PK.domain_path(pkg, dom), tbl)
    for dom in ("skills", "classes", "affixes", "drop_pools"):
        PK.write_json(PK.domain_path(pkg, dom), {})
    for dom in ("effect_rules", "passive_proc"):
        PK.write_json(PK.domain_path(pkg, dom), {})
    PK.save_manifest(pkg, {
        "id": "big_game", "name": "大包压测", "desc": f"{ITEMS} 条物品",
        "engine": ">=0.1",
        "domains": ["skills", "classes", "monsters", "affixes", "items",
                    "effect_rules", "passive_proc", "maps", "drop_pools"],
        "entry": "content/apply.py", "created": "2026-09-12 12:00:00",
    })
    return pkg


# ---------------- HTTP ----------------
def req(base, method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method,
                               headers={"Content-Type": "application/json"} if data else {})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            raw = resp.read()
            ms = (time.perf_counter() - t0) * 1000
            return resp.status, json.loads(raw.decode("utf-8")), ms
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        ms = (time.perf_counter() - t0) * 1000
        try:
            return e.code, json.loads(raw), ms
        except json.JSONDecodeError:
            return e.code, {"raw": raw}, ms


def timed(base, path, n=5):
    """跑 n 次：返回 (中位数ms, **第一次**调用ms, 最后一次响应)。"""
    ts, last = [], None
    for _ in range(n):
        st, j, ms = req(base, "GET", path)
        ts.append(ms)
        last = (st, j)
    ordered = sorted(ts)
    return ordered[len(ordered) // 2], ts[0], last


# ---------------- 前端纯函数（node 真跑） ----------------
NODE_TEST = r"""
// 从 editor/web/app.js 抠出「列表过滤 / 排序 / 窗口切片」这一段真跑 —— 纯函数，不碰 DOM。
const fs = require('fs');
const path = require('path');
const APP = path.join(process.env.FW_ROOT || '.', 'editor', 'web', 'app.js');
const src = fs.readFileSync(APP, 'utf8');
const B = '/* ##LIST_VIEW_BEGIN## */', E = '/* ##LIST_VIEW_END## */';
const i = src.indexOf(B), j = src.indexOf(E);
if (i < 0 || j < 0) { console.error('❌ 找不到 ##LIST_VIEW_BEGIN/END## 标记'); process.exit(1); }
eval(src.slice(i + B.length, j));

let pass = 0, fail = 0;
const ok = (name, cond, extra) => {
  if (cond) { pass++; console.log('  ✅ ' + name); }
  else { fail++; console.log('  ❌ ' + name + (extra === undefined ? '' : '  ' + JSON.stringify(extra))); }
};

// ---- 合成 2000 条（与 Python 侧同构：key / name / kind） ----
const TYPES = ['材料', '消耗品', '装备', '任务物品', '货币'];
const entries = [];
for (let n = 0; n < 2000; n++) {
  entries.push({ key: 'it_' + String(n).padStart(5, '0'), name: '物品' + String(n).padStart(5, '0') + '·试验装备',
                 kind: TYPES[n % 5], lv: (n % 40) });
}

// ---- ① 搜索：条数与内容 ----
const hit = lvFilter(entries, '物品0150', 'all', new Set(), new Set());
ok('搜索「物品0150」命中 10 条', hit.length === 10, hit.length);
ok('搜索结果内容正确（全含该子串）', hit.every((e) => e.name.includes('物品0150')), hit.map((e) => e.key));
ok('搜索大小写/首尾空格无关', lvFilter(entries, '  物品0150 ', 'all', new Set(), new Set()).length === 10);
ok('搜索 kind 也能命中', lvFilter(entries, '材料', 'all', new Set(), new Set()).length === 400,
   lvFilter(entries, '材料', 'all', new Set(), new Set()).length);
ok('无命中 → 0 条', lvFilter(entries, '不可能存在的词', 'all', new Set(), new Set()).length === 0);
ok('空查询 → 全量（不改入参数组）', lvFilter(entries, '', 'all', new Set(), new Set()).length === 2000
   && entries.length === 2000);

// ---- ② 筛选：待修 / 未保存 ----
const badKeys = new Set(['it_00003', 'it_00007', 'it_01999']);
const dirty = new Set(['it_00001']);
ok('筛选「待修」= 校验问题条数', lvFilter(entries, '', 'bad', badKeys, dirty).length === 3);
ok('筛选「未保存」= 脏条目数', lvFilter(entries, '', 'dirty', badKeys, dirty).length === 1);
ok('搜索 + 待修 可叠加', lvFilter(entries, '物品0000', 'bad', badKeys, dirty).length === 2);

// ---- ③ 排序 ----
const byKey = lvSort(lvFilter(entries, '', 'all', new Set(), new Set()), 'key');
ok('按 key 排序：首尾正确', byKey[0].key === 'it_00000' && byKey[1999].key === 'it_01999',
   [byKey[0].key, byKey[1999].key]);
const byKind = lvSort(lvFilter(entries, '', 'all', new Set(), new Set()), 'kind');
ok('按类别排序：同类相邻（分组前提）', (() => {
  const seen = new Set();
  let last = null;
  for (const e of byKind) {
    if (e.kind !== last) { if (seen.has(e.kind)) return false; seen.add(e.kind); last = e.kind; }
  }
  return true;
})());

// ---- ④ 窗口切片（虚拟滚动核心） ----
const ROW = 38;
const flat = entries.map((e, k) => ({ h: ROW, off: k * ROW }));          // 无分组
const total = flat.length * ROW;
const s0 = lvSlice(flat, 0, 700, ROW * 12);
ok('顶部窗口：从 0 开始', s0.start === 0 && s0.padTop === 0, s0);
ok('顶部窗口：上方无占位、下方留足', s0.padBottom > total - 1400, s0);
const sMid = lvSlice(flat, 38000, 700, ROW * 12);
ok('中部窗口：起止都落在表内且连续', sMid.start > 0 && sMid.end > sMid.start && sMid.end <= flat.length, sMid);
const winH = flat[sMid.end - 1].off + flat[sMid.end - 1].h - flat[sMid.start].off;
ok('中部窗口：上占位 + 窗口内容 + 下占位 = 总高（滚动条比例不变）',
   Math.abs(sMid.padTop + winH + sMid.padBottom - total) < 0.01, {sMid: sMid, winH: winH, total: total});
const sEnd = lvSlice(flat, total, 700, ROW * 12);                        // 越界（滚过头）
ok('越界位置：仍返回合法窗口', sEnd.start < flat.length && sEnd.end === flat.length, sEnd);

// 整表走一遍：每一步窗口连续、且并集覆盖 0..1999（不丢行、不重复错位）
let covered = new Set(), gap = false, overlapBad = false, prevEnd = -1;
for (let top = 0; top <= total; top += 350) {
  const s = lvSlice(flat, top, 700, ROW * 12);
  if (s.end - s.start <= 0) { gap = true; break; }
  for (let k = s.start; k < s.end; k++) covered.add(k);
  if (prevEnd >= 0 && s.start > prevEnd) overlapBad = true;              // 中间空了一段 = 有行看不到
  prevEnd = s.end;
}
ok('逐步滚动：窗口之间不留缝（无「看不到的行」）', !overlapBad && !gap);
ok('逐步滚动：并集覆盖全部 2000 行', covered.size === 2000, covered.size);

// 带分组标题（高度不同）的块表 —— 偏移必须仍然单调
let off = 0;
const mixed = [];
for (let k = 0; k < 600; k++) {
  if (k % 50 === 0) { mixed.push({ h: 29.75, off: off, i: -1 }); off += 29.75; }
  mixed.push({ h: ROW, off: off, i: k }); off += ROW;
}
const sm = lvSlice(mixed, 5000, 700, ROW * 12);
ok('带分组标题：窗口合法且占位自洽',
   sm.start >= 0 && sm.end <= mixed.length && sm.end > sm.start
   && Math.abs(sm.padTop - mixed[sm.start].off) < 0.01
   && Math.abs(sm.padBottom - (off - (mixed[sm.end - 1].off + mixed[sm.end - 1].h))) < 0.01, sm);

// 空表 / 坏输入不许崩
ok('空表 → 全 0', JSON.stringify(lvSlice([], 0, 700, 456)) === JSON.stringify({ start: 0, end: 0, padTop: 0, padBottom: 0 }));
ok('scrollTop 负数 → 从 0 开始', lvSlice(flat, -999, 700, 0).start === 0);
ok('viewport 为 0 也不崩（至少返回一块）', (() => { const s = lvSlice(flat, 1000, 0, 0); return s.end > s.start; })());

console.log('  · 前端纯函数断言：通过 ' + pass + ' / 失败 ' + fail);
process.exit(fail ? 1 : 0);
"""


def run_node_checks() -> bool | None:
    """跑前端纯函数测试（无 node → None = 显式跳过）。"""
    node = shutil.which("node")
    if not node:
        print("  ⚠ 本机没有 node —— 跳过「搜索 / 窗口切片」纯函数断言（不判失败）")
        return None
    fd, js = tempfile.mkstemp(prefix="fw_listview_", suffix=".js")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(NODE_TEST)
        pr = subprocess.run([node, js], capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=120, cwd=ROOT,
                            env={**os.environ, "FW_ROOT": ROOT, "PYTHONIOENCODING": "utf-8"})
        out = ((pr.stdout or "") + (pr.stderr or "")).rstrip()
        print("\n".join("  " + ln for ln in out.splitlines()))
        return pr.returncode == 0
    finally:
        try:
            os.remove(js)
        except OSError:
            pass


def main() -> int:
    gd = tempfile.mkdtemp(prefix="fw_big_pkg_")
    httpd = None
    try:
        SRV.GAMES_DIR = gd
        pkg = build_pkg(gd)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), SRV.H)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        size_kb = os.path.getsize(PK.domain_path(pkg, "items")) / 1024
        print(f"== 编辑器大包门禁（临时包目录 {gd}，物品 {ITEMS} 条 / {size_kb:.0f}KB）==")

        # 1. 域列表 + 条目列表（**先量列表 = 真冷启动**：2000 条都要现算一遍校验）
        st, j, _ = req(base, "GET", "/api/domains")
        check("GET /api/domains 200 且域齐全", st == 200 and len(j.get("domains") or []) >= 9,
              f"{st} / {len(j.get('domains') or [])}")
        med, first, (st, j) = timed(base, "/api/package/big_game/d/items", n=5)
        keys = [e["key"] for e in (j.get("entries") or [])]
        check("条目列表：2000 条一条不少", st == 200 and j.get("count") == ITEMS
              and len(keys) == ITEMS and len(set(keys)) == ITEMS, f"{st} count={j.get('count')}")
        check("条目列表：首条/末条存在且带 name/kind",
              bool(j["entries"][0].get("name")) and bool(j["entries"][-1].get("kind")),
              j["entries"][0])
        check(f"条目列表响应：冷启动首次 {first:.0f}ms < {FIRST_MS}ms", first < FIRST_MS, f"{first:.0f}ms")
        check(f"条目列表响应：5 次中位数 {med:.0f}ms < {MEDIAN_MS}ms", med < MEDIAN_MS, f"{med:.0f}ms")

        # 2. 包概览（此刻 items 的校验已热 → 量的是「缓存命中 + 其余域」那条路）
        med2, first2, (st, j) = timed(base, "/api/package/big_game", n=5)
        doms = {d["id"]: d for d in (j.get("domains") or [])}
        check("包概览可达", st == 200 and j.get("ok"), f"{st}")
        check(f"包概览：items count = {ITEMS}", (doms.get("items") or {}).get("count") == ITEMS,
              (doms.get("items") or {}).get("count"))
        check(f"包概览：monsters count = {MONSTERS}", (doms.get("monsters") or {}).get("count") == MONSTERS)
        check(f"包概览：maps count = {MAPS}", (doms.get("maps") or {}).get("count") == MAPS)
        check("包概览：空域 count = 0 且 ok", (doms.get("skills") or {}).get("count") == 0
              and (doms.get("skills") or {}).get("ok") is True)
        check(f"包概览响应：首次 {first2:.0f}ms < {FIRST_MS}ms", first2 < FIRST_MS, f"{first2:.0f}ms")
        check(f"包概览响应：5 次中位数 {med2:.0f}ms < {MEDIAN_MS}ms", med2 < MEDIAN_MS, f"{med2:.0f}ms")

        # 3. 列表分页（大包不一次吐 1.9MB）：并集 == 全量、边界不崩、旧行为零影响
        base_items = f"/api/package/big_game/d/items"
        seen, off, pages = set(), 0, 0
        while pages < 50:
            st, jp, _ = req(base, "GET", f"{base_items}?offset={off}&limit=500")
            got = jp.get("entries") or []
            if not got:
                break
            off += len(got)
            pages += 1
            seen.update(e["key"] for e in got)
        check(f"分页：{pages} 段并集 = 全量 {ITEMS} 条（不重不漏）",
              pages == 4 and len(seen) == ITEMS, f"pages={pages} keys={len(seen)}")
        st, jp, _ = req(base, "GET", f"{base_items}?limit=500")
        check("分页：本页 500 条，但 count 仍是**该域总数**（前端据此显示 已取/总数）",
              st == 200 and len(jp["entries"]) == 500 and jp["count"] == ITEMS,
              f"{len(jp.get('entries') or [])}/{jp.get('count')}")
        st, jp, _ = req(base, "GET", f"{base_items}?offset={ITEMS + 999}&limit=10")
        check("分页：越界 offset → 空数组且不崩", st == 200 and jp["entries"] == [] and jp["count"] == ITEMS, f"{st}")
        st, jp, _ = req(base, "GET", f"{base_items}?limit=abc&offset=-5")
        check("分页：非法 limit / 负 offset → 退回全量旧行为", len(jp.get("entries") or []) == ITEMS,
              len(jp.get("entries") or []))
        st, jp, _ = req(base, "GET", base_items)
        ref = PK.list_entries(pkg, "items")
        check("分页：不带参数 = 与 PK.list_entries 逐字一致（旧调用方零影响）",
              jp.get("entries") == ref["entries"] and jp.get("count") == ref["count"])

        # 4. 单条读 / 写：保存后能读回，且列表与概览立刻反映（校验缓存失效正确）
        key = "it_01500"
        st, j, _ = req(base, "GET", f"/api/package/big_game/d/items/{key}")
        check("打开单条：返回数据 + schema + 校验结果",
              st == 200 and isinstance(j.get("data"), dict) and isinstance(j.get("schema"), dict)
              and isinstance(j.get("errors"), list), f"{st}")
        data = dict(j["data"])
        data["name"] = "改名后的物品01500"
        data["price"] = 4321
        st, j, _ = req(base, "PUT", f"/api/package/big_game/d/items/{key}", {"data": data})
        check("保存单条 → 200 且返回该域条目数", st == 200 and j.get("ok") and j.get("count") == ITEMS,
              f"{st} {j.get('count')}")
        st, j, _ = req(base, "GET", f"/api/package/big_game/d/items/{key}")
        check("保存后读回：改动的字段真的落盘", j["data"]["name"] == "改名后的物品01500"
              and j["data"]["price"] == 4321, j.get("data", {}).get("name"))
        med3, _, (st, j) = timed(base, "/api/package/big_game/d/items", n=5)
        got = [e for e in (j.get("entries") or []) if e["key"] == key]
        check("改完一条后：列表立刻反映新名字（缓存按内容失效）",
              len(got) == 1 and got[0]["name"] == "改名后的物品01500", got[:1])
        check(f"改完一条后：列表响应仍快（只重算那一条）{med3:.0f}ms < {MEDIAN_MS}ms",
              med3 < MEDIAN_MS, f"{med3:.0f}ms")

        # 4. 校验：坏数据仍被拦（缓存不许把错误结果吃掉）
        st, j, _ = req(base, "PUT", f"/api/package/big_game/d/items/it_bad",
                       {"data": {"name": "缺描述", "price": 1}})
        check("缺必填字段 → 422 且被拦（走同一套校验）", st == 422 and not j.get("ok"), f"{st}")
        st, j, _ = req(base, "GET", "/api/package/big_game/d/items/it_bad")
        check("被拦的条目确实没落盘", st == 404, f"{st}")

        # 5. 整包（13 域一起）：每个域的校验路径 / 域级缓存 / 跨域不互相拖累
        full_dir = build_full_pkg(gd)
        med, first, (st, j) = timed(base, "/api/package/full_game", n=5)
        doms_full = {d["id"]: d for d in (j.get("domains") or [])}
        bad = [d for d, n in FULL_COUNTS.items() if (doms_full.get(d) or {}).get("count") != n]
        check("整包：13 域条目数全对", not bad, bad)
        notok = [d for d in FULL_COUNTS if not (doms_full.get(d) or {}).get("ok")]
        check("整包：13 域全部校验通过（ok=True）", not notok, notok)
        check(f"整包：概览 冷 {first:.0f}ms<{FIRST_MS} / 热中位 {med:.0f}ms<{MEDIAN_MS}",
              first < FIRST_MS and med < MEDIAN_MS, f"{first:.0f}/{med:.0f}")
        slow = []
        for dom in FULL_COUNTS:
            m, f2, _ = timed(base, f"/api/package/full_game/d/{dom}", n=3)
            if m > MEDIAN_MS:
                slow.append((dom, round(m)))
        check("整包：每个域的列表响应都 < 阈值", not slow, slow)
        hmed, hfirst, _ = timed(base, "/api/package/full_game/hints", n=3)
        check(f"整包：hints（扫全包）热中位 {hmed:.0f}ms < {MEDIAN_MS}", hmed < MEDIAN_MS, f"{hfirst:.0f}/{hmed:.0f}")

        # 保存后：该域列表立刻反映新值（域签名缓存失效），概览仍与磁盘一致
        tp = PK.domain_path(full_dir, "texts")
        tbl = PK.read_json(tp, {})
        k0 = sorted(tbl)[0]
        e0 = dict(tbl[k0])
        e0["desc"] = "改过的说明"
        st3, j3, _ = req(base, "PUT", f"/api/package/full_game/d/texts/{k0}", {"data": e0})
        lst = (req(base, "GET", "/api/package/full_game/d/texts")[1].get("entries") or [])
        hit0 = [x for x in lst if x["key"] == k0]
        check("整包：保存后该域列表立刻反映新值（域签名缓存失效）",
              st3 == 200 and bool(hit0) and hit0[0]["summary"].startswith("改过的说明"), hit0[:1])
        _, _, (st4, j4) = timed(base, "/api/package/full_game", n=3)
        d2 = {d["id"]: d for d in (j4.get("domains") or [])}
        check("整包：保存后概览仍与磁盘一致（count 不变 / ok=True）",
              (d2.get("texts") or {}).get("count") == FULL_COUNTS["texts"] and (d2.get("texts") or {}).get("ok") is True,
              d2.get("texts"))

        # 6. 前端纯函数（搜索 + 虚拟滚动窗口）
        ok = run_node_checks()
        if ok is not None:
            check("前端：搜索/排序/窗口切片纯函数全部通过", ok)

        print(f"\n{'-' * 46}\n通过 {PASS} / 失败 {FAIL}")
        for f in FAILURES:
            print("  ❌", f)
        return 1 if FAIL else 0
    finally:
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        shutil.rmtree(gd, ignore_errors=True)
        print(f"  · 临时包目录已清理：{gd}")


if __name__ == "__main__":
    sys.exit(main())
