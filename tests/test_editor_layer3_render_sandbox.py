#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：编辑器扩展**第 3 层 · 批 2** —— **白名单派生 + 沙箱子进程**（执行面；仍不跑包代码）。

设计真源：`overnight/layer3-render-design.md` §5.1/§5.2（方案 A 子进程 + 能力收窄清单）
          + §7.2/§7.3（对策矩阵 + 诚实残留）+ §9「批 2 · 派生值」；
          `overnight/layer3-render-contracts.md` §1.9（派生白名单）+ §4（沙箱协议）+ §2.1（树的 derives）。

本门禁钉住六件事（对应作业书 §3 的硬判据）：

  ① **零执行面 / 那条边界只有一个文件**：`editor/render.py`、`render_decl.py` 里
     `subprocess|eval(|exec(` 计数 = **0**（父侧起进程的调用**只**在 `render_worker.py`）；
     `import editor.render` **不会**把 worker 拉进 `sys.modules`（惰性 import）；
     干净解释器里 `editor.render` / `editor.render_worker` 都不带进 `saintess_engine*`。
  ② **白名单派生逐值对拍**：13 个 `derives`（覆盖 12 个白名单函数）—— 子进程算的值
     与**父侧独立参考实现**逐一相等；同输入跑两次同输出。
  ③ **逃逸尝试被拦**（①②③：`__import__` via builtins / `object.__subclasses__` / `getattr` 链）：
     `fn` 只走白名单 dict 查表（表外无路可走）；受限 builtins 里没有 IO/反射名字；
     import 闸对白名单外模块根一律 `ImportError`（**且已摘 `sys.modules` 缓存**，
     所以「命中缓存绕过闸」也不成立）。`object.__subclasses__` 的**语言层可达**如实报告为
     **已知残留**（设计 §7.3），不当成「已解决」。
  ④ **三类边界**：超时 / 崩溃 / 巨输出 —— 都有明确 `stage` 与可读文案，主进程存活，
     HTTP 侧**仍然 200**（降级 + 黄条），**绝不 500、绝不白屏**。
  ⑤ **代码档（`render/<域>.py`）已砍**：本批**明确忽略 + 告警**，**绝不执行** ——
     含**反证**：同一份 `.py` 单独跑会留 marker，而渲染链路跑完 marker 不存在。
  ⑥ **协议与 payload 收窄**：payload 里没有本机绝对路径；子进程 env 里没有
     `PYTHONPATH`/`PYTHONSTARTUP`/`PYTHONHOME`；cwd = 空临时目录且请求结束即删；
     stdout 上限 / stderr 尾 2000 字 / 非 marker 行忽略。

跑法：python tests/test_editor_layer3_render_sandbox.py
退出码：0 = 全过；1 = 有失败。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import statistics
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

from editor import render as R          # noqa: E402
from editor import render_decl as RD    # noqa: E402
from editor import render_worker as RW  # noqa: E402
from editor import server as SRV        # noqa: E402

# ══════════════════════════════════════════════════════════════════════════
# 假包素材（与 tree 门禁同形，字段扩到覆盖 12 个白名单函数）
# ══════════════════════════════════════════════════════════════════════════
SCHEMA = {"$schema": "https://json-schema.org/draft/2020-12/schema", "x-primary": "my_dungeon",
          "$defs": {
              "stage": {"type": "object", "properties": {"name": {"type": "string"},
                                                         "monsters": {"type": "array"},
                                                         "boss": {"type": "array"}}},
              "entry": {"type": "object", "properties": {"item": {"type": "string"},
                                                         "w": {"type": "number"},
                                                         "kind": {"type": "string"}}},
              "drop_pool": {"type": "object", "properties": {"name": {"type": "string"}}},
              "my_dungeon": {"type": "object", "required": ["name", "stages"], "properties": {
                  "name": {"type": "string"}, "lv": {"type": "integer"},
                  "stages": {"type": "array", "items": {"$ref": "#/$defs/stage"}},
                  "entries": {"type": "array", "items": {"$ref": "#/$defs/entry"}},
                  "rolls": {"type": "array"}, "tags": {"type": "array"},
                  "reward_pool": {"type": "string"}, "note": {"type": "string"},
                  "at": {"type": "integer"}}, "additionalProperties": True}}}
POOL_SCHEMA = {"$schema": "https://json-schema.org/draft/2020-12/schema", "x-primary": "drop_pool",
               "$defs": {"drop_pool": {"type": "object", "properties": {
                   "name": {"type": "string"}, "type": {"type": "string"}},
                   "additionalProperties": True}}}
DOMS = {"my_dungeons": {"label": "副本", "kind": "data", "schema": "my_dungeons.schema.json",
                        "primary": "my_dungeon", "icon": "🏯"},
        "drop_pools": {"label": "掉落池", "kind": "data", "schema": "drop_pools.schema.json",
                       "primary": "drop_pool", "icon": "🎁"}}
DATA = {"name": "试炼场", "lv": 12,
        "stages": [{"name": "一层", "monsters": ["史莱姆", "哥布林"], "boss": []},
                   {"name": "二层", "monsters": ["炎龙"], "boss": ["炎龙"]}],
        "entries": [{"item": "a", "w": 2, "kind": "eq"}, {"item": "b", "w": 3, "kind": "eq"},
                    {"item": "c", "w": 1, "kind": "mat"}],
        "rolls": [5, 3, 9, 3], "tags": ["火", "冰", "雷"], "reward_pool": "pool_a",
        "note": "", "at": 1700000000}
POOLS = {"pool_a": {"name": "A池", "type": "weighted"},
         "pool_b": {"name": "B池", "type": "weighted"}}
GLOSS = {"fields": {"name": {"zh": "名称"}, "lv": {"zh": "需求等级"}, "stages": {"zh": "楼层"},
                    "entries": {"zh": "掉落条目"}, "tags": {"zh": "标签"},
                    "reward_pool": {"zh": "奖励池"}}}
#: 13 个派生 = 12 个白名单函数（`count` 用两次）
DERIVES = {
    "层数": {"fn": "count", "args": {"field": "stages"}, "label": "层数"},
    "条目数": {"fn": "count", "args": {"field": "entries"}},
    "权重和": {"fn": "sum", "args": {"field": "entries", "of": "w"}, "format": "number"},
    "均权": {"fn": "avg", "args": {"field": "entries", "of": "w"}, "format": "number"},
    "最小": {"fn": "min", "args": {"field": "rolls"}},
    "最大": {"fn": "max", "args": {"field": "rolls"}},
    "比值": {"fn": "ratio", "args": {"num": {"field": "lv"}, "den": 4, "scale": 2},
             "format": "number"},
    "占比": {"fn": "percent_share", "args": {"field": "entries", "of": "w", "total": 8},
             "format": "percent", "tone": "ok"},
    "总权重": {"fn": "weighted_total", "args": {"field": "entries", "weight": "w"}},
    "分组": {"fn": "group_count", "args": {"field": "entries", "by": "kind"}},
    "奖池名": {"fn": "lookup_label", "args": {"ref": "pool_a", "domain": "drop_pools", "by": "name"}},
    "标签": {"fn": "join_text", "args": {"field": "tags", "sep": "/", "limit": 2}},
    "等级": {"fn": "fmt_number", "args": {"value": {"field": "lv"}, "digits": 2,
                                          "thousands": True}},
}
DECL = {
    "$version": 1, "$extends": "none", "title": "副本 {name}", "icon": "🏯",
    "layout": [
        {"id": "intro", "kind": "text", "label": "说明",
         "text": "{name}（{lv} 级）共 {derive:层数} 层，占比 {derive:占比}"},
        {"id": "base", "kind": "fields", "label": "基础", "fields": ["name", "lv"]},
        {"id": "grp", "kind": "kv", "label": "分组", "source": {"derive": "分组"}},
        {"id": "lst", "kind": "list", "label": "条目", "source": {"derive": "分组"},
         "item": {"title": "{name}：{value}", "badges": [{"text": "{value}", "tone": "info"}]}},
        {"id": "pool", "kind": "kv", "label": "奖池", "source": {"derive": "奖池名"}},
    ],
    "derives": DERIVES,
}
#: 父侧**手算**的期望值（逐值对拍的第一支）
EXPECT = {"层数": 2, "条目数": 3, "权重和": 6, "均权": 2.0, "最小": 3, "最大": 9,
          "比值": 6.0, "占比": 0.75, "总权重": 6, "分组": {"eq": 2, "mat": 1},
          "奖池名": "A池", "标签": "火/冰", "等级": "12.00"}
#: `fn` 白名单外的逃逸尝试（①②③ + 其它经典面）
ESCAPE_FNS = ("__import__", "object.__subclasses__", "getattr", "eval", "exec", "open",
              "compile", "globals", "locals", "type", "os.system", "io.open",
              "subprocess.Popen", "importlib.import_module", "pickle.loads")

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


def note(text):
    print(f"   · {text}")


def req(base, method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method,
                               headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(r, timeout=90) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw}


def _write(path, obj, raw=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(obj if raw else json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def make_pkg(root, pid, *, decl=None, domains=None, data=None, extra=None, vocab=GLOSS):
    pkg = os.path.join(root, pid)
    for sub in ("content/data", "editor/render", "schemas"):
        os.makedirs(os.path.join(pkg, *sub.split("/")), exist_ok=True)
    _write(os.path.join(pkg, "game.json"),
           {"id": pid, "name": pid, "desc": "第 3 层沙箱门禁", "engine": ">=0.1",
            "domains": list(domains or DOMS), "entry": "content/apply.py"})
    _write(os.path.join(pkg, "editor/domains.json"), domains if domains is not None else DOMS)
    _write(os.path.join(pkg, "schemas/my_dungeons.schema.json"), SCHEMA)
    _write(os.path.join(pkg, "schemas/drop_pools.schema.json"), POOL_SCHEMA)
    for dom, doc in (data or {"my_dungeons": {"d1": DATA}, "drop_pools": POOLS}).items():
        _write(os.path.join(pkg, "content/data", f"{dom}.json"), doc)
    if vocab is not None:
        _write(os.path.join(pkg, "editor/glossary/my_dungeons.json"), vocab)
    if decl is not None:
        _write(os.path.join(pkg, "editor/render/my_dungeons.json"), decl,
               raw=isinstance(decl, str))
    for rel, body in (extra or {}).items():
        _write(os.path.join(pkg, *rel.split("/")), body, raw=isinstance(body, str))
    return pkg


def _hash_tree(root):
    h = hashlib.sha256()
    for base, dirs, files in os.walk(root):
        dirs.sort()
        for fn in sorted(files):
            if fn.endswith(".pyc"):
                continue
            p = os.path.join(base, fn)
            h.update(os.path.relpath(p, root).replace("\\", "/").encode("utf-8"))
            try:
                with open(p, "rb") as f:
                    h.update(f.read())
            except OSError:
                pass
    return h.hexdigest()


def _src(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _same(a, b):
    """逐值对拍：数字容差 1e-9（其余严格相等）。"""
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 1e-9
    return a == b


# ══════════════════════════════════════════════════════════════════════════
# 0 · 零执行面 / 那条边界只有一个文件
# ══════════════════════════════════════════════════════════════════════════
def t0_boundary():
    print("\n【0】零执行面：父侧零起进程调用 / worker 是唯一那条边界 / 零引擎 import")
    r_src, d_src, w_src = _src("editor/render.py"), _src("editor/render_decl.py"), \
        _src("editor/render_worker.py")
    for rel, src in (("editor/render.py", r_src), ("editor/render_decl.py", d_src)):
        hits = re.findall(r"subprocess|eval\(|exec\(", src)
        check(f"★ 硬判据⑥ {rel}：subprocess / eval( / exec( 计数 = 0", hits == [], str(hits))
    check("★ 硬判据⑥ 起进程的调用**只**在 render_worker.py（它就是那条边界）",
          re.search(r"subprocess", w_src) is not None)
    check("worker 只被**惰性 import**（`from . import render_worker` 在函数体里缩进）",
          re.search(r"\n\s+from \. import render_worker", r_src) is not None
          and re.search(r"\nfrom \. import render_worker", r_src) is None)
    code = ("import sys, json\n"
            f"sys.path.insert(0, {ROOT!r})\n"
            "import editor.render as R\n"
            "import editor.render_decl as D\n"
            "print(json.dumps({'bad': sorted(m for m in sys.modules"
            " if m.startswith('saintess_engine')),\n"
            "                  'pkgs': 'editor.packages' in sys.modules,\n"
            "                  'rel': 'editor.relations' in sys.modules,\n"
            "                  'worker': sorted(m for m in sys.modules if 'render_worker' in m),"
            " 'derived': hasattr(R, 'derived')}))\n")
    pr = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=180,
                        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    got = {}
    try:
        got = json.loads((pr.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        got = {}
    check("★ 干净解释器 import editor.render → sys.modules 无 saintess_engine*",
          pr.returncode == 0 and got.get("bad") == [],
          f"rc={pr.returncode} {got} {(pr.stderr or '')[-300:]}")
    check("干净解释器里也没有 editor.packages / editor.relations（都不级联引擎）",
          got.get("pkgs") is False and got.get("rel") is False, str(got))
    check("★ 惰性 import：import editor.render **不**把 render_worker 拉进内存",
          got.get("worker") == [] and got.get("derived") is True, str(got))

    code2 = ("import sys, json\n"
             f"sys.path.insert(0, {ROOT!r})\n"
             "import editor.render_worker as W\n"
             "print(json.dumps({'bad': sorted(m for m in sys.modules"
             " if m.startswith('saintess_engine')),\n"
             "                  'caps': W.CAPS, 'allow_code': W.ALLOW_CODE,\n"
             "                  'marker': W.MARKER}))\n")
    pr2 = subprocess.run([sys.executable, "-c", code2], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=180,
                         env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    got2 = {}
    try:
        got2 = json.loads((pr2.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        got2 = {}
    check("worker 模块本身零引擎 import", pr2.returncode == 0 and got2.get("bad") == [], str(got2))
    check("★ 协议 marker = __FW_RENDER__（契约 §4.2）", got2.get("marker") == "__FW_RENDER__")
    check("★ 能力档只有 decl+derive（**没有** code：批 3 已砍）",
          got2.get("caps") == ["decl", "derive"] and got2.get("allow_code") is False, str(got2))
    check("★ worker 源码里没有**开文件**的调用（子进程零文件 IO：只读 stdin / 只写 stdout）",
          re.search(r"(?<![\w.])open\(", w_src) is None
          and re.search(r"(?<![\w.])(read_text|write_text|read_bytes)\(", w_src) is None,
          str(re.findall(r"(?<![\w.])open\(", w_src)))
    check("worker 不 import importlib / ctypes / inspect（反射面）",
          not re.search(r"^\s*(import|from)\s+(importlib|ctypes|inspect)\b", w_src, re.M))
    check("worker 不 import 引擎（零 `saintess_engine` 字样）", "saintess_engine" not in w_src)


# ══════════════════════════════════════════════════════════════════════════
# 1 · 白名单派生：逐值对拍
# ══════════════════════════════════════════════════════════════════════════
def _ref_child(data):
    """★ **父侧独立参考实现**（不共享 worker 的代码）—— 与子进程逐值对拍的第二支。"""
    ent = data["entries"]
    ws = [e["w"] for e in ent]
    rolls = data["rolls"]
    grp = {}
    for e in ent:
        grp[e["kind"]] = grp.get(e["kind"], 0) + 1
    return {
        "层数": len(data["stages"]),
        "条目数": len(ent),
        "权重和": sum(ws),
        "均权": statistics.fmean(ws),
        "最小": min(rolls),
        "最大": max(rolls),
        "比值": (data["lv"] / 4) * 2,
        "占比": sum(ws) / 8,
        "总权重": sum(ws),
        "分组": grp,
        "奖池名": "A池",
        "标签": "/".join(data["tags"][:2]),
        "等级": f"{data['lv']:,.2f}",
    }


def t1_derive_values(gd):
    print("\n【1】白名单派生：子进程算 vs 父侧参考（逐值对拍）+ 落树")
    pkg = make_pkg(gd, "p4_ok", decl=DECL)
    decl, _w = R.declared(pkg, "my_dungeons", DOMS)
    check("声明解析出 13 个派生（覆盖 12 个白名单函数）",
          decl is not None and len(decl["derives"]) == 13, str(sorted((decl or {}).get("derives", {}))))
    t0 = time.monotonic()
    dv = R.derived(pkg, "my_dungeons", "d1", DATA, DOMS, ref_values={"pool_a": ["A池"]})
    wall = (time.monotonic() - t0) * 1000
    check("★ derived() 成功（stage=done）且回了 13 个值",
          dv.get("ok") is True and dv.get("stage") == "done" and len(dv["values"]) == 13,
          json.dumps(dv, ensure_ascii=False)[:400])
    check("elapsed_ms 是整数（子进程耗时，契约 §2.1）",
          isinstance(dv.get("elapsed_ms"), int) and dv["elapsed_ms"] >= 0, str(dv.get("elapsed_ms")))
    note(f"一次派生的墙钟（含冷启动）= {wall:.0f} ms（U4：接受一次性进程的冷启动）")
    for name, want in EXPECT.items():
        got = dv["values"].get(name, "<缺>")
        check(f"逐值对拍 · {name} = {want!r}", _same(got, want), f"实得 {got!r}")
    ref = _ref_child(DATA)
    check("★ 与**父侧独立参考实现**逐值对拍（13/13）",
          all(_same(dv["values"].get(k), v) for k, v in ref.items()),
          json.dumps({k: (v, dv["values"].get(k)) for k, v in ref.items()
                      if not _same(dv["values"].get(k), v)}, ensure_ascii=False))
    dv2 = R.derived(pkg, "my_dungeons", "d1", DATA, DOMS, ref_values={"pool_a": ["A池"]})
    check("★ 同输入同输出（确定性：跑两次结果逐字节相同）",
          json.dumps(dv["values"], sort_keys=True, ensure_ascii=False)
          == json.dumps(dv2["values"], sort_keys=True, ensure_ascii=False))
    check("沙箱报告说 builtins 白名单与设计 §5.2 同源（22 个名字）",
          len((dv.get("sandbox") or {}).get("builtins_allowed") or []) == 22,
          str((dv.get("sandbox") or {}).get("builtins_allowed")))
    check("payload 里没有本机绝对路径（契约 §4.1）",
          (dv.get("echo") or {}).get("abs_paths") == [], str((dv.get("echo") or {}).get("abs_paths")))
    check("payload 键就是契约那套（pkg_id/dom/key/data/decl/schema_digest/glossary/"
          "ref_values/limits/caps/allow_code + 本批的 compute）",
          set((dv.get("echo") or {}).get("keys") or []) == {
              "pkg_id", "dom", "key", "data", "decl", "schema_digest", "glossary",
              "ref_values", "limits", "caps", "allow_code", "compute"},
          str((dv.get("echo") or {}).get("keys")))
    env = (dv.get("echo") or {}).get("env") or {}
    check("★ 子进程 env 被清干净（无 PYTHONPATH/PYTHONSTARTUP/PYTHONHOME、无任何包根注入）",
          env.get("has_pythonpath") is False and env.get("has_pythonstartup") is False
          and env.get("has_pythonhome") is False and env.get("framework_env_keys") == [],
          json.dumps(env, ensure_ascii=False))
    check("★ cwd = 空临时目录，且请求结束即删（契约 §4.3）",
          bool(env.get("cwd")) and not os.path.isdir(env["cwd"]), str(env.get("cwd")))
    spath = (dv.get("echo") or {}).get("sys_path") or []
    check("★ 子进程 sys.path 里没有包目录 / 仓根（harden_path；只留 stdlib + site-packages）",
          bool(spath) and not any(("p4_ok" in p or p == ROOT or p == HERE
                                   or "framework-engine" in p) for p in spath), str(spath))

    # 落树
    tree = R.build(pkg, "my_dungeons", "d1", DATA, DOMS, derived=dv["values"])
    check("★ 树里出现 derives（名字: {label, value 展示串}）",
          isinstance(tree.get("derives"), dict) and len(tree["derives"]) == 13
          and tree["derives"]["层数"] == {"label": "层数", "value": "2"},
          json.dumps(tree.get("derives"), ensure_ascii=False)[:300])
    check("展示格式：number / percent / plain 各按声明走",
          tree["derives"]["均权"]["value"] == "2"
          and tree["derives"]["占比"]["value"] == "75.0%"
          and tree["derives"]["占比"].get("tone") == "ok"
          and tree["derives"]["等级"]["value"] == "12.00"
          and tree["derives"]["分组"]["value"] == '{"eq": 2, "mat": 1}',
          json.dumps(tree["derives"], ensure_ascii=False))
    blocks = {b["id"]: b for b in tree["tabs"][0]["blocks"]}
    check("★ `{derive:名}` 插值在服务端算完（不再是空的）",
          blocks["intro"]["text"] == "试炼场（12 级）共 2 层，占比 75.0%",
          blocks["intro"]["text"])
    check("★ `source:{derive:名}` 落成 kv 行（分组）",
          blocks["grp"]["rows"] == [{"label": "eq", "value": "2"}, {"label": "mat", "value": "1"}],
          json.dumps(blocks["grp"].get("rows"), ensure_ascii=False))
    check("★ `source:{derive:名}` 落成 list 项（含 item 模板插值）",
          [i["title"] for i in blocks["lst"]["list"]] == ["eq：2", "mat：1"],
          json.dumps(blocks["lst"].get("list"), ensure_ascii=False))
    check("标量派生 → kv 单行", blocks["pool"]["rows"] == [{"label": "奖池名", "value": "A池"}],
          json.dumps(blocks["pool"].get("rows"), ensure_ascii=False))
    check("树里仍然没有 html/style/script 字段（H1 不破）",
          "html" not in json.dumps(tree, ensure_ascii=False).lower())
    check("★ 父侧**树校验**：真树 0 问题（禁用键 / tabs 形状 / 块类型白名单）",
          R.tree_problems(tree) == [], str(R.tree_problems(tree)))
    _bad_tree = {"ok": True, "tabs": [{"id": "m", "blocks": [
        {"kind": "text", "text": "x", "html": "<b>x</b>"}]}],
        "derives": {"a": {"label": "a", "value": "v", "style": "color:red"}}}
    _probs = R.tree_problems(_bad_tree)
    check("★ 父侧树校验：塞进 html/style → 逐条报出（不静默、不当没看见）",
          any("html" in p for p in _probs) and any("style" in p for p in _probs), str(_probs))
    check("父侧树校验：形状退化也报（tabs 空 / 块类型不在白名单）",
          R.tree_problems({"ok": True, "tabs": []}) != []
          and R.tree_problems({"ok": True, "tabs": [{"id": "m", "blocks": [
              {"kind": "script"}]}]}) != [])

    # 不给 derived = 批 1 的 D0 语义（既有门禁 61/61 就靠这条）
    d0 = R.build(pkg, "my_dungeons", "d1", DATA, DOMS)
    check("★ 不传 derived → D0 语义（树里没有 derives、{derive:} 仍渲染为空 + 告警）",
          "derives" not in d0 and d0["tabs"][0]["blocks"][0]["text"].endswith("占比 ")
          and any("批 2" in w for w in d0["warnings"]), str(d0["tabs"][0]["blocks"][0]["text"]))
    d0b = R.derived(make_pkg(gd, "p4_noder", decl={"$version": 1, "layout": []}),
                    "my_dungeons", "d1", DATA, DOMS)
    check("没有派生声明 → 不起子进程（skipped=True、elapsed 0）",
          d0b.get("ok") is True and d0b.get("skipped") is True and d0b.get("values") == {})

    # 父侧回程硬判（不信子进程：类型/长度/深度/声明外名字）
    orig = RW.invoke
    deep = {"a": {"b": {"c": {"d": {"e": {"f": {"g": 1}}}}}}}
    RW.invoke = lambda payload, **kw: {
        "ok": True, "stage": "done", "elapsed_ms": 1, "sandbox": {}, "warnings": [],
        "values": {"层数": 7, "声明外": 1, "坏数": float("nan"), "深": deep, "长": "x" * 500,
                   "幽灵": "回程里冒出来的名字"}}
    try:
        declx = {"version": 1, "extends": "none", "allow_code": False, "when": None,
                 "layout": [], "sections": [], "fields": {}, "slots": {}, "hooks": {},
                 "readonly": [], "fields_known": sorted(DATA),
                 "derives": {n: {"fn": "count", "args": {"field": "stages"}, "format": "plain",
                                 "tone": "info", "when": None}
                             for n in ("层数", "声明外", "坏数", "深", "长")}}
        dvx = R.derived(pkg, "my_dungeons", "d1", DATA, DOMS, decl=declx)
    finally:
        RW.invoke = orig
    check("★ 回程校验：**声明外**的名字丢弃 + 告警（绝不透传）",
          "幽灵" not in dvx["values"] and any("幽灵" in w for w in dvx["warnings"])
          and "声明外" in dvx["values"], json.dumps(dvx, ensure_ascii=False)[:300])
    check("★ 回程校验：NaN/Inf 丢弃 + 告警", "坏数" not in dvx["values"]
          and any("非有限" in w for w in dvx["warnings"]), str(dvx["warnings"]))
    check("★ 回程校验：嵌套 > 6 层丢弃 + 告警", "深" not in dvx["values"]
          and any("嵌套" in w for w in dvx["warnings"]), str(dvx["warnings"]))
    check("★ 回程校验：超长串截断到 200 字 + 告警（巨输出 → 截断且有告警）",
          len(dvx["values"].get("长") or "") == 200
          and any("截断" in w for w in dvx["warnings"]), str(dvx["warnings"]))
    check("合法值原样保留（层数=7）", dvx["values"].get("层数") == 7)


# ══════════════════════════════════════════════════════════════════════════
# 2 · 逃逸尝试 ①②③
# ══════════════════════════════════════════════════════════════════════════
def t2_escape(gd):
    print("\n【2】逃逸尝试 ①②③（__import__ via builtins / object.__subclasses__ / getattr 链）")
    pkg = make_pkg(gd, "p4_esc", decl=DECL)
    # ① 声明层：白名单外的 fn 一律**被拒 + 告警**（不是静默返回空）
    bad = {"$version": 1, "layout": [], "derives": {
        "逃逸1": {"fn": "__import__", "args": {"name": "os"}},
        "逃逸2": {"fn": "object.__subclasses__", "args": {}},
        "逃逸3": {"fn": "getattr", "args": {"o": {"field": "name"}, "n": "__class__"}}}}
    nd, nw = RD.norm_decl(bad, "my_dungeons", set(DATA))
    check("★ 反证⑤：白名单外的 fn 塞进声明 → **被拒**（derives 空）",
          nd is not None and nd["derives"] == {}, str((nd or {}).get("derives")))
    check("★ 反证⑤：而且**有可读告警**（不是静默返回空）",
          len(nw) >= 3 and all("白名单" in w for w in nw if "派生" in w), str(nw))
    check("反证⑤：还原成白名单函数后照常解析（还原复绿）",
          RD.norm_decl({"$version": 1, "layout": [],
                        "derives": {"ok": {"fn": "count", "args": {"field": "stages"}}}},
                       "my_dungeons", set(DATA))[0]["derives"].get("ok", {}).get("fn") == "count")
    # 绕过声明层：直接把逃逸 fn 交给沙箱（父侧不查、子进程必须自己挡住）
    esc_decl = {"version": 1, "extends": "none", "allow_code": False, "when": None,
                "layout": [], "sections": [], "fields": {}, "slots": {}, "hooks": {},
                "readonly": [], "fields_known": sorted(DATA),
                "derives": {f"E{i}": {"fn": fn, "args": {"field": "name"}, "format": "plain",
                                      "tone": "info", "when": None}
                            for i, fn in enumerate(ESCAPE_FNS)}}
    dv = R.derived(pkg, "my_dungeons", "d1", DATA, DOMS, decl=esc_decl)
    check(f"★ ① 子进程只认 dict 查表：{len(ESCAPE_FNS)} 个逃逸名**一个都没算出值**",
          dv.get("ok") is True and dv["values"] == {}, json.dumps(dv.get("values"), ensure_ascii=False))
    check("★ ① 每个逃逸名都有一条可读告警（不静默）",
          sum(1 for w in dv["warnings"] if "不在白名单" in w) == len(ESCAPE_FNS),
          str(dv["warnings"][:3]))
    sb = dv.get("sandbox") or {}
    check("★ ① 派发探针：逃逸名在白名单表里**取不到任何可调用对象**",
          sb.get("escape_dispatch") and not any(sb["escape_dispatch"].values()),
          json.dumps(sb.get("escape_dispatch"), ensure_ascii=False))
    check("★ ② 受限 builtins 里没有 open/eval/exec/compile/__import__/getattr/setattr/"
          "globals/locals/type/object（逐条 False）",
          sb.get("escape_builtins") and not any(sb["escape_builtins"].values()),
          json.dumps(sb.get("escape_builtins"), ensure_ascii=False))
    check("受限 builtins 与设计 §5.2 **逐名同源**（22 个；没有 IO / 反射 / 进程面）",
          sb.get("builtins_allowed") == sorted([
              "len", "range", "str", "int", "float", "bool", "list", "dict", "set", "tuple",
              "sorted", "min", "max", "sum", "abs", "round", "enumerate", "zip", "any", "all",
              "isinstance", "print"]) and "open" not in sb.get("builtins_allowed", []),
          str(sb.get("builtins_allowed")))
    probe = sb.get("imports_probe") or {}
    check("★ ③ import 闸：白名单外模块根**一律 ImportError**（策略层）",
          probe and all(v["policy_denied"] for v in probe.values()),
          json.dumps(probe, ensure_ascii=False))
    check("★ ③ 且**已摘 sys.modules 缓存**（命中缓存绕过闸的路也堵了）",
          probe and not any(v["already_loaded"] for v in probe.values()),
          json.dumps(probe, ensure_ascii=False))
    check("白名单 import 只剩设计 §5.2 那 10 个",
          sb.get("imports_allowed") == list(RW.IMPORT_WHITELIST)
          and len(sb["imports_allowed"]) == 10, str(sb.get("imports_allowed")))
    check("★ 诚实残留如实报告：`object.__subclasses__` 在**语言层可达**（不粉饰成已解决）",
          sb.get("subclasses_walk") is True)
    note("已知残留（设计 §7.3）：纯 Python 里 (1).__class__.__mro__[1].__subclasses__() 总能拿到；"
         "本批的防线是「没有包代码入口」+「fn 只走 dict 查表」，不是「语言层堵死」")
    check("★ 本批**没有包代码入口**：逃逸探针全部 False + caps 无 code + allow_code False",
          not any((sb.get("escape_dispatch") or {}).values())
          and sb.get("caps") == ["decl", "derive"] and sb.get("allow_code") is False)
    # 路径逃逸（T7 / G4-④）：声明里的 `../` 路径在**声明层**就被拒
    t7, w7 = RD.norm_decl({"$version": 1, "layout": [
        {"id": "x", "kind": "text", "text": "读：{../../game.json}"},
        {"id": "y", "kind": "list", "source": {"field": "../../etc/passwd"}}]},
        "my_dungeons", set(DATA))
    check("★ 路径逃逸（../../）在声明层被拒 + 告警（读不出任何东西）",
          t7 is not None and t7["layout"] == [] and len(w7) >= 2, str(w7))


# ══════════════════════════════════════════════════════════════════════════
# 3 · 边界：超时 / 崩溃 / 巨输出
# ══════════════════════════════════════════════════════════════════════════
def t3_limits(gd):
    print("\n【3】三类边界：超时 / 崩溃 / 巨输出（父侧掐死 + 明确 stage + 主进程存活）")
    fake = tempfile.mkdtemp(prefix="fw_l3b2_fake_")
    paths = {}
    bodies = {
        "sleep": "import time\ntime.sleep(30)\n",
        "crash": "import sys\nsys.stderr.write('BOOM')\nsys.exit(3)\n",
        "flood": "import sys\nsys.stdout.write('x' * 3000000)\nsys.stdout.flush()\n",
        "noise": ("import sys, json\nprint('noise')\nprint('__FW_RENDER__{not json')\n"
                  "print('__FW_RENDER__' + json.dumps({'t':'derive','name':'x','value':1}))\n"
                  "sys.stdout.flush()\n"
                  "print('__FW_RENDER__' + json.dumps({'t':'done','stage':'done','ok':True,"
                  "'values':{'x':1},'warnings':[]}))\n"),
        "stderr": "import sys\nsys.stderr.write('E' * 20000)\nsys.stderr.flush()\n",
    }
    for k, body in bodies.items():
        paths[k] = os.path.join(fake, f"{k}.py")
        with open(paths[k], "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
    orig = RW.RUNNER
    pkg = make_pkg(gd, "p4_lim", decl=DECL)

    def with_runner(script, payload, **kw):
        RW.RUNNER = script
        try:
            return RW.invoke(payload, **kw)
        finally:
            RW.RUNNER = orig

    try:
        t0 = time.monotonic()
        r = with_runner(paths["sleep"], {"x": 1}, timeout_ms=800)
        dt = (time.monotonic() - t0) * 1000
        check("★ 超时：到点掐死 + stage=timeout + 可读文案（不挂死调用方）",
              r["ok"] is False and r["stage"] == "timeout" and "超时" in r["message"]
              and dt < 8000, f"{r['stage']} dt={dt:.0f}ms {r['message'][:60]}")
        r = with_runner(paths["crash"], {"x": 1})
        check("★ 崩溃：没有末行 → stage=crash + stderr 尾（不抛）",
              r["ok"] is False and r["stage"] == "crash" and "BOOM" in r["stderr_tail"],
              f"{r['stage']} {r['stderr_tail']!r}")
        r = with_runner(paths["flood"], {"x": 1}, max_output_bytes=65536)
        check("★ 巨输出：超上限即掐死 + stage=limit",
              r["ok"] is False and r["stage"] == "limit" and "输出超过上限" in r["message"]
              and r["stdout_bytes"] <= 65536 * 2, f"{r['stage']} {r['stdout_bytes']}")
        r = with_runner(paths["stderr"], {"x": 1})
        check("stderr 只留尾部 2000 字符（契约 §4.2）", len(r["stderr_tail"]) == 2000,
              str(len(r["stderr_tail"])))
        r = with_runner(paths["noise"], {"x": 1})
        check("★ 非 marker 行 / 坏 JSON 行**一律忽略**；派生行与末行都能读回",
              r["ok"] is True and r["values"] == {"x": 1}, json.dumps(r)[:200])
        t0 = time.monotonic()
        r = RW.invoke(["not-a-dict"])
        check("★ 真子进程崩溃也有明确报错（畸形 payload → stage=crash + 异常名）",
              r["ok"] is False and r["stage"] == "crash" and "payload" in r["message"],
              f"{r['stage']} {r['message'][:80]}")
        note(f"畸形 payload 的崩溃判定耗时 {(time.monotonic() - t0) * 1000:.0f} ms")
        # 真 worker 的输出上限 / 超时（不靠假 worker）
        many = {"decl": {"derives": {"g": {"fn": "group_count",
                                           "args": {"field": "items", "by": "k"}}}},
                "compute": ["g"], "limits": {}, "caps": ["decl", "derive"],
                "allow_code": False,
                "data": {"items": [{"k": "k%04d" % i} for i in range(2000)]}}
        r = RW.invoke(many, max_output_bytes=2048)
        check("★ 真 worker + 2 KB 上限 → stage=limit（父子两端的硬判同源）",
              r["stage"] == "limit" and r["ok"] is False, f"{r['stage']} {r['stdout_bytes']}")
        r = RW.invoke(many, timeout_ms=1)
        check("★ 真 worker + 1 ms 墙钟 → stage=timeout", r["stage"] == "timeout",
              f"{r['stage']} {r['message'][:60]}")
        r = RW.invoke(many)
        check("同一 payload 放宽限额 → 正常 done（证明上面两条是**限额**而非 bug）",
              r["ok"] is True, str(r["values"])[:80])
        check("★ 子侧**双保险**：2000 键的 group_count 在子进程里就被截到 200 + 告警"
              "（契约 §4.1「与父侧硬判一致」）",
              len(r["values"].get("g") or {}) == 200
              and any("沙箱上限" in w for w in r["warnings"]), json.dumps(r["warnings"])[:160])
        # 元素上限：不杀进程，只把该项显示成「—」+ 告警
        p2 = {"decl": {"derives": {"s": {"fn": "sum", "args": {"field": "items"}}}},
              "compute": ["s"], "limits": {}, "caps": ["decl", "derive"], "allow_code": False,
              "data": {"items": list(range(60000))}}
        dv2 = R.derived(pkg, "my_dungeons", "d1", DATA, DOMS, decl={
            "version": 1, "extends": "none", "when": None, "fields_known": sorted(DATA),
            "derives": {"s": {"fn": "sum", "args": {"field": "rolls"}, "format": "plain",
                              "tone": "info", "when": None}}})
        check("正常规模不触发元素上限（对照）", dv2["values"].get("s") == 20, str(dv2["values"]))
        r = RW.invoke(p2)
        check("★ 单次派生遍历 > 50,000 元素 → 该项「—」+ 告警（不杀进程，契约 §1.9）",
              r["ok"] is True and "s" not in r["values"]
              and any("50000" in w for w in r["warnings"]), str(r["warnings"]))
        # 假数据兜底/除零
        dvz = R.derived(pkg, "my_dungeons", "d1", {"name": "空", "lv": 0},
                        DOMS, ref_values={})
        check("数据取不到 → 各派生不算（树里显示「—」+ 告警，不炸）",
              dvz["ok"] is True and dvz["values"].get("均权") is None
              and dvz["values"].get("占比") is None, json.dumps(dvz["values"], ensure_ascii=False))
    finally:
        RW.RUNNER = orig
        shutil.rmtree(fake, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════
# 4 · 代码档（批 3 已砍）：忽略 + 告警 + 绝不执行（含反证）
# ══════════════════════════════════════════════════════════════════════════
CODE_PY = """# -*- coding: utf-8 -*-
# 包自带代码档（批 3）—— 本批**必须**被忽略；若被执行，会留下 marker 并报错
import os
_p = os.environ.get("FW_L3B2_MARKER", "")
if _p:
    with open(_p, "w", encoding="utf-8") as f:
        f.write("EXECUTED-PACKAGE-CODE")


def derive(item, ctx):
    return "pwned"


raise RuntimeError("包代码被执行了 —— 批 3 不该在本批跑")
"""


def t4_code_file(gd):
    print("\n【4】代码档 `render/<域>.py`：本批**忽略 + 告警 + 绝不执行**（反证）")
    marker = os.path.join(gd, "marker_code.txt")
    if os.path.exists(marker):
        os.remove(marker)
    pkg = make_pkg(gd, "p4_code", decl={**DECL, "$allow_code": True},
                   extra={"editor/render/my_dungeons.py": CODE_PY})
    os.environ["FW_L3B2_MARKER"] = marker
    try:
        decl = R.declarations(pkg, DOMS)
        info = decl["domains"]["my_dungeons"]
        check("代码档只被**数存在性**（has_code=True，内容不读）",
              info["has_code"] is True and decl["code_enabled"] is True)
        ws = R.render_warnings(pkg, DOMS)
        check("★ 明确**告警**：`render/my_dungeons.py` 存在 → 忽略 + 绝不执行",
              any("my_dungeons.py" in w and "已砍" in w and "绝不执行" in w for w in ws), str(ws))
        check("★ `$allow_code:true` 也**只记存在性**并发告警（本批不发车）",
              any("$allow_code" in w and "已砍" in w for w in ws), str(ws))
        dv = R.derived(pkg, "my_dungeons", "d1", DATA, DOMS, ref_values={"pool_a": ["A池"]})
        check("★ 代码档在场也**照常只跑白名单派生**（13 值、值全对）",
              dv["ok"] is True and len(dv["values"]) == 13
              and _same(dv["values"].get("层数"), 2), json.dumps(dv.get("values"), ensure_ascii=False))
        check("★ payload 的 allow_code **恒 False**（声明写 true 也不发车）",
              (dv.get("echo") or {}).get("allow_code") is False
              and (dv.get("sandbox") or {}).get("allow_code") is False)
        tree = R.build(pkg, "my_dungeons", "d1", DATA, DOMS, derived=dv["values"])
        check("树照常构建、没有包代码的产物（没有 pwned）",
              tree["ok"] is True and "pwned" not in json.dumps(tree, ensure_ascii=False))
        check("★ **反证**：marker 不存在 —— 渲染链路**没有**执行那份 .py",
              not os.path.exists(marker), marker)
        # marker 机制本身有效（否则上面的「不存在」没意义）
        pr = subprocess.run([sys.executable, os.path.join(pkg, "editor/render/my_dungeons.py")],
                            capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=60, env={**os.environ, "FW_L3B2_MARKER": marker,
                                             "PYTHONIOENCODING": "utf-8"})
        check("★ 反证有效：同一份 .py 单独跑**确实会**留 marker（证明上面那条不是空断言）",
              os.path.exists(marker) and "EXECUTED-PACKAGE-CODE" in open(
                  marker, encoding="utf-8").read() and pr.returncode != 0)
        os.remove(marker)
        # 再跑一遍渲染：marker 仍不该出现
        R.derived(pkg, "my_dungeons", "d1", DATA, DOMS)
        check("★ 再跑一遍渲染：marker 依然不存在（稳定不执行）", not os.path.exists(marker))
        check("worker 源码里没有任何「按路径执行/加载包文件」的入口（无路径拼接执行面）",
              not re.search(r"(spec_from_file|SourceFileLoader|load_module|runpy|marshal\.loads)",
                            _src("editor/render_worker.py")))
    finally:
        os.environ.pop("FW_L3B2_MARKER", None)
        if os.path.exists(marker):
            os.remove(marker)


# ══════════════════════════════════════════════════════════════════════════
# 5 · HTTP 端到端：派生上树 / 降级 / 零写盘
# ══════════════════════════════════════════════════════════════════════════
def t5_http(gd):
    print("\n【5】HTTP 端到端：派生落树 / 三类边界降级仍 200 / 零写盘")
    SRV.GAMES_DIR = gd
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), SRV.H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    fake = tempfile.mkdtemp(prefix="fw_l3b2_httpfake_")
    crash_py = os.path.join(fake, "crash.py")
    with open(crash_py, "w", encoding="utf-8", newline="\n") as f:
        f.write("import sys\nsys.stderr.write('HTTP-BOOM')\nsys.exit(4)\n")
    orig_runner = RW.RUNNER
    try:
        pkg = make_pkg(gd, "h4_ok", decl=DECL)
        make_pkg(gd, "h4_noder", decl={"$version": 1, "title": "无派生 {name}",
                                       "layout": [{"id": "t", "kind": "text", "text": "静态 {lv}"}]})
        make_pkg(gd, "h4_views", decl=DECL, extra={
            "editor/views.json": json.dumps({"my_dungeons": {"view": "table"}})})
        before = _hash_tree(pkg)
        st, j = req(base, "GET", "/api/package/h4_ok/d/my_dungeons/d1/view")
        check("★ 200 + view_source=package-render（派生值已落树）",
              st == 200 and j.get("view_source") == "package-render", f"{st} {j.get('view_source')}")
        tree = j.get("view") or {}
        check("★ 树里 derives 13 值 + {derive:} 插值 + source:{derive} 三处都生效",
              len(tree.get("derives") or {}) == 13
              and tree["tabs"][0]["blocks"][0]["text"] == "试炼场（12 级）共 2 层，占比 75.0%"
              and tree["tabs"][0]["blocks"][2]["rows"][0]["label"] == "eq",
              json.dumps(tree.get("derives"), ensure_ascii=False)[:200])
        check("响应带 derive_elapsed_ms（性能观测，契约 §2.1 的 elapsed_ms）",
              isinstance(tree.get("derive_elapsed_ms"), int))
        check("★ 端到端树校验干净（响应告警里没有「渲染树校验：」条目）",
              not any(isinstance(w, str) and "渲染树校验：" in w
                      for w in (j.get("view_warnings") or [])), str(j.get("view_warnings"))[:200])
        check("★ 渲染链路零写盘（包目录哈希前后一致）", _hash_tree(pkg) == before)
        st, j2 = req(base, "GET", "/api/package/h4_noder/d/my_dungeons/d1/view")
        check("没派生声明的包：不走子进程，行为与批 1 一致（package-render + 无 derives 键）",
              st == 200 and j2.get("view_source") == "package-render"
              and "derives" not in (j2.get("view") or {}), f"{st} {json.dumps(j2)[:200]}")
        st, j3 = req(base, "GET", "/api/package/h4_views/d/my_dungeons/d1/view")
        check("派生照跑 + views.json 被覆盖的告警照旧",
              st == 200 and j3.get("view_source") == "package-render"
              and any(isinstance(w, str) and "被 render 声明覆盖" in w
                      for w in (j3.get("view_warnings") or [])))

        # ① 超时 → 仍然 200 + stage=timeout + 回退第 2 层
        os.environ["FW_RENDER_TIMEOUT"] = "1"
        try:
            st, jt = req(base, "GET", "/api/package/h4_views/d/my_dungeons/d1/view")
        finally:
            os.environ.pop("FW_RENDER_TIMEOUT", None)
        stages = [w for w in (jt.get("view_warnings") or []) if isinstance(w, dict)]
        check("★ 超时 → **仍然是 200**（不是 500/504）+ stage=timeout + 回退第 2 层视图",
              st == 200 and stages and stages[-1]["stage"] == "timeout"
              and jt.get("view_source") == "package", f"{st} {jt.get('view_warnings')}")
        check("超时文案可读（含「超时」与毫秒）",
              "超时" in (stages[-1].get("message") or ""), str(stages[-1].get("message"))[:80])
        # ② 崩溃 → 仍然 200 + stage=crash
        RW.RUNNER = crash_py
        try:
            st, jc = req(base, "GET", "/api/package/h4_views/d/my_dungeons/d1/view")
        finally:
            RW.RUNNER = orig_runner
        stages = [w for w in (jc.get("view_warnings") or []) if isinstance(w, dict)]
        check("★ 崩溃（子进程非零退出/无末行）→ 200 + stage=crash + 回退",
              st == 200 and stages and stages[-1]["stage"] == "crash"
              and jc.get("view_source") == "package", f"{st} {jc.get('view_warnings')}")
        # ③ 巨输出 → 仍然 200 + stage=limit
        os.environ["FW_RENDER_MAX_OUTPUT"] = "64"
        try:
            st, jl = req(base, "GET", "/api/package/h4_views/d/my_dungeons/d1/view")
        finally:
            os.environ.pop("FW_RENDER_MAX_OUTPUT", None)
        stages = [w for w in (jl.get("view_warnings") or []) if isinstance(w, dict)]
        check("★ 巨输出（输出上限 64 B）→ 200 + stage=limit + 回退",
              st == 200 and stages and stages[-1]["stage"] == "limit", f"{st} {jl.get('view_warnings')}")
        check("★ 三类边界都**不是 500**（G3 硬纪律）", st != 500 and st == 200)
        # 恢复后照常
        st, jr = req(base, "GET", "/api/package/h4_ok/d/my_dungeons/d1/view")
        check("限额恢复正常后回到 200 + package-render（还原复绿）",
              st == 200 and jr.get("view_source") == "package-render")
        check("渲染链路**始终**零写盘（含降级那几次）", _hash_tree(pkg) == before)
        # 主进程存活（没被子进程拖死）
        st, jz = req(base, "GET", "/api/package/h4_ok/d/my_dungeons/d1/view")
        check("★ 主进程存活（超时/崩溃之后仍能继续服务）", st == 200)
        # 写回链不受影响
        st, js = req(base, "PUT", "/api/package/h4_ok/d/my_dungeons/d2", {"data": dict(DATA)})
        check("★ 渲染与写回解耦：PUT 照常 200", st == 200 and js.get("ok"), str(st))
    finally:
        RW.RUNNER = orig_runner
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(fake, ignore_errors=True)


def main():
    print("== 第 3 层·批 2「白名单派生 + 沙箱子进程」门禁（协议/对拍/逃逸/边界/代码档/HTTP）==")
    gd = tempfile.mkdtemp(prefix="fw_l3_sandbox_")
    try:
        t0_boundary()
        t1_derive_values(gd)
        t2_escape(gd)
        t3_limits(gd)
        t4_code_file(gd)
        t5_http(gd)
    finally:
        shutil.rmtree(gd, ignore_errors=True)
    print(f"\n===== 结果：通过 {PASS} / {PASS + FAIL} =====")
    for f in FAILURES:
        print("  ❌", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
