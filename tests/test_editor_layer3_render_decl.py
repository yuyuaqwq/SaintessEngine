#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：编辑器扩展**第 3 层 · 批 1「声明面」** —— 包侧渲染声明 `editor/render/<域>.json`。

设计真源：`overnight/layer3-render-design.md` §9「批 1 · 声明面」+ §3（字段级）+ §6（降级）
          `overnight/layer3-render-contracts.md` §0（寻址/上限）+ §1（字段表）+ §3.1（HTTP）。

本批的边界（**验收就是这几条**）：

  ① **不执行任何包代码**：`editor/render.py` / `editor/render_decl.py` 里零 `subprocess`、
     零 `eval(`/`exec(`；`import editor.render` 后 `sys.modules` 里没有 `saintess_engine*`，
     也没有 `editor.packages`（后者会级联 `install_engine()`）—— 同 `test_editor_play.py` 的写法。
  ② **声明 schema 与白名单**：5 种块 / 5 个槽位 / 6 个钩子 / 12 个派生名 / 路径文法 / 条件文法 / 上限。
  ③ **寻址与兼容**：每域一文件（字典序）/ 有效域表 / `$version` / `$schema.json` 跳过 /
     `editor/render.json` 弃用但仍读 / 同名域以每域文件为准 / 256 KB 与 128 文件上限。
  ④ **坏声明只降级**：坏 JSON / 未知域 / 未知版本 / 未知键 / 未知块 / 未知槽位 / 循环引用
     → 忽略该项（或整份）+ **可读告警**，**永不 500**。
  ⑤ **HTTP 面**：`GET /api/package/<id>/render` 的字段与 `limits`；`/views` 的 `render` 小节；
     包**没声明** render 时两者都逐项不变（零回归）。

跑法：python tests/test_editor_layer3_render_decl.py
退出码：0 = 全过；1 = 有失败。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from editor import render as R          # noqa: E402
from editor import render_decl as RD    # noqa: E402
from editor import server as SRV        # noqa: E402

SCHEMA = {"$schema": "https://json-schema.org/draft/2020-12/schema", "x-primary": "my_dungeon",
          "$defs": {"stage": {"type": "object", "properties": {
              "name": {"type": "string"}, "monsters": {"type": "array"},
              "boss": {"type": "array"}}},
              "my_dungeon": {"type": "object", "required": ["name", "stages"],
                             "properties": {"name": {"type": "string"}, "lv": {"type": "integer"},
                                            "stages": {"type": "array", "items": {"$ref": "#/$defs/stage"}},
                                            "reward_pool": {"type": "string"},
                                            "note": {"type": "string"}},
                             "additionalProperties": True}}}
DUNGEON = {"name": "试炼场", "lv": 12,
           "stages": [{"name": "一层", "monsters": ["史莱姆"], "boss": []},
                      {"name": "二层", "monsters": ["炎龙"], "boss": ["炎龙"]}],
           "reward_pool": "pool_a", "note": ""}
GOOD_DECL = {
    "$version": 1, "$extends": "form", "title": "副本 {name}", "icon": "🏯",
    "layout": [
        {"id": "intro", "kind": "text", "label": "说明", "text": "**{name}**，{lv} 级，共 {stages} 层。"},
        {"id": "base", "kind": "fields", "label": "基础", "fields": ["name", "lv", "note"], "columns": 2},
        {"id": "floors", "kind": "list", "label": "楼层", "source": {"field": "stages"},
         "item": {"title": "{name}", "subtitle": "怪 {monsters}",
                  "badges": [{"text": "Boss", "tone": "bad", "when": {"boss": {"exists": True}}}]}},
        {"id": "meta", "kind": "kv", "label": "其它", "source": {"field": "stages"}},
        {"id": "tb", "kind": "table", "label": "楼层表", "source": {"field": "stages"},
         "item": {"columns": ["name", "monsters"]}},
    ],
    "fields": {"stages": {"label": "楼层", "note": "每层一行"},
               "note": {"widget": "textarea", "hidden": True}},
    "slots": {"list_editor": {"field": "stages", "item_fields": ["name", "monsters"]}},
    "derives": {"层数": {"fn": "count", "args": {"field": "stages"}, "label": "层数"}},
    "hooks": {"not_blank": "not_blank"},
    "readonly": ["lv"],
    "$notes": "包作者备注",
}
NEW_DOMS = {"my_dungeons": {"label": "副本", "kind": "data", "schema": "my_dungeons.schema.json",
                            "primary": "my_dungeon", "icon": "🏯"}}

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


def req(base, method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method,
                               headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw}


def make_pkg(root, pid, *, decl=None, domains=None, data=None, schemas=None,
             extra_files=None, vocab=None):
    """建一个最小包。`decl` 为 str 时按原始字节写（喂坏 JSON / 超大文件用）。"""
    pkg = os.path.join(root, pid)
    for sub in ("content/data", "editor/render", "schemas"):
        os.makedirs(os.path.join(pkg, *sub.split("/")), exist_ok=True)
    _write(os.path.join(pkg, "game.json"),
           {"id": pid, "name": pid, "desc": "第 3 层门禁", "engine": ">=0.1",
            "domains": list(domains or NEW_DOMS), "entry": "content/apply.py"})
    _write(os.path.join(pkg, "editor/domains.json"), domains if domains is not None else NEW_DOMS)
    for name, doc in (schemas or {"my_dungeons.schema.json": SCHEMA}).items():
        _write(os.path.join(pkg, "schemas", name), doc)
    for dom, doc in (data or {"my_dungeons": {"d1": DUNGEON}}).items():
        _write(os.path.join(pkg, "content/data", f"{dom}.json"), doc)
    if vocab is not None:
        _write(os.path.join(pkg, "editor/glossary/my_dungeons.json"), vocab)
    if decl is not None:
        p = os.path.join(pkg, "editor/render/my_dungeons.json")
        _write_raw(p, decl)
    for rel, doc in (extra_files or {}).items():
        _write_raw(os.path.join(pkg, *rel.split("/")), doc)
    return pkg


def _write(path, obj):
    _write_raw(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def _write_raw(path, raw):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False, indent=2))


def norm(raw, fields=None, sub_fields=None, dom="my_dungeons"):
    return RD.norm_decl(raw, dom, fields, sub_fields=sub_fields)


# ══════════════════════════════════════════════════════════════════════
def _runtime_refs(src):
    """AST 层判据：import 了谁 / 有没有 install_engine 这类运行时引用（注释与文档串不算）。"""
    import ast
    out = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Name) and node.id in ("install_engine", "saintess_engine"):
            out.append(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in ("install_engine",):
            out.append(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = ([node.module or ""] if isinstance(node, ast.ImportFrom) else []) \
                + [a.name for a in node.names]
            out += [m for m in mods if m.startswith("saintess_engine") or m.endswith("packages")]
    return out


def t0_zero_execution():
    print("\n【0】零执行面 / 零引擎 import（硬断言）")
    srcs = {}
    for rel in ("editor/render.py", "editor/render_decl.py"):
        with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
            srcs[rel] = f.read()
    for rel, src in srcs.items():
        hits = re.findall(r"subprocess|eval\(|exec\(", src)
        check(f"{rel}：subprocess / eval( / exec( 计数 = 0", hits == [], str(hits))
        check(f"{rel}：AST 层不 import saintess_engine / editor.packages、不引用 install_engine",
              _runtime_refs(src) == [], str(_runtime_refs(src)))
        check(f"{rel}：不 import json 之外的第三方（零依赖）",
              not re.search(r"^\s*import\s+(?!json|os|re|hashlib|time|sys)\w+", src, re.M))
    code = ("import sys, json\n"
            f"sys.path.insert(0, {ROOT!r})\n"
            "import editor.render as R\n"
            "import editor.render_decl as D\n"
            "bad = sorted(m for m in sys.modules if m.startswith('saintess_engine'))\n"
            "print(json.dumps({'bad': bad, 'pkgs': 'editor.packages' in sys.modules,\n"
            "                  'worker': [m for m in sys.modules if 'render_worker' in m]}))\n")
    pr = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=120)
    got = {}
    try:
        got = json.loads((pr.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        got = {}
    check("★ 干净解释器 import editor.render 后 sys.modules 无 saintess_engine*",
          pr.returncode == 0 and got.get("bad") == [],
          f"rc={pr.returncode} {got} {(pr.stderr or '')[-300:]}")
    check("★ 干净解释器里也没有拉进 editor.packages（会级联 install_engine）",
          got.get("pkgs") is False, str(got))
    check("批 1 里没有 render_worker（子进程是批 2 的事）", got.get("worker") == [])
    check("批 1 的模块只有声明面 + 树构建（RENDER.check 不存在）",
          not hasattr(R, "check_escape") and not hasattr(R, "run_worker"))


def t1_whitelists():
    print("\n【1】白名单表与上限（与契约同源）")
    check("★ 块类型白名单**只有 5 种**", RD.KINDS == ("fields", "text", "list", "table", "kv"),
          str(RD.KINDS))
    check("$extends 三态", RD.EXTENDS == ("form", "view", "none"))
    check("受控槽位 5 个", sorted(RD.SLOT_KEYS) == sorted(
        ["list_editor", "ref_picker", "code_editor", "preview_panel", "diff_view"]))
    check("校验钩子 6 个（只许点名）", len(RD.HOOKS) == 6 and "regex" in RD.HOOKS)
    check("派生函数白名单 12 个", len(RD.DERIVE_FNS) == 12 and "weighted_total" in RD.DERIVE_FNS)
    check("控件白名单含 auto/json", "auto" in RD.WIDGETS and "json" in RD.WIDGETS)
    check("色调白名单 info/ok/warn/bad", RD.TONES == ("info", "ok", "warn", "bad"))
    check("比较运算符白名单（无脚本、无函数调用）",
          set(RD.OPS) >= {"gt", "ge", "lt", "le", "eq", "ne", "in", "truthy", "exists"}
          and not any(o in RD.OPS for o in ("+", "call", "fn")))
    check("限额与契约同源（树 256KB / 块 64 / list 200 / 插值 8 / 深度 6）",
          RD.MAX_TREE_BYTES == 262144 and RD.MAX_TREE_BLOCKS == 64
          and RD.MAX_LIST_ITEMS == 200 and RD.MAX_INTERP == 8 and RD.MAX_PATH_DEPTH == 6)


def t2_paths_and_conditions():
    print("\n【2】路径文法 / 条件文法（刻意极小）")
    for p in ("name", "a.b", "a.b[0]", "a[*].b", "stages[2].monsters[0]"):
        check(f"合法路径 {p}", RD.valid_path(p))
    for p in ("../etc/passwd", "a/../b", "a\\b", "{name}", "", "a..b", "1abc", "a[-1]"):
        check(f"★ 非法路径被拒 {p!r}", not RD.valid_path(p))
    check("根字段 / 深度", RD.root_field("stages[0].monsters") == "stages"
          and RD.path_depth("a.b[0].c") == 4 and RD.path_depth("name") == 1)
    check("path_get：数组下标与缺值",
          RD.path_get({"a": {"b": [1, 2]}}, "a.b[1]") == 2
          and RD.path_get({"a": 1}, "a.b") is None and RD.path_get({}, "x") is None)
    check("path_get：[*] 命中列表", RD.path_get({"a": [1, 2]}, "a[*]") == [1, 2])
    data = {"lv": 12, "locked": True, "kind": "物理", "name": "", "stages": [{"boss": ["x"]}]}
    cases = [({"lv": 12}, True), ({"lv": {"gt": 10}}, True), ({"lv": {"le": 10}}, False),
             ({"kind": {"in": ["物理", "魔法"]}}, True), ({"locked": {"truthy": True}}, True),
             ({"name": {"exists": True}}, False), ({"lv": {"ne": 13}}, True),
             ({"stages[*].boss": {"exists": True}}, True),
             ({"all": [{"lv": {"gt": 1}}, {"locked": True}]}, True),
             ({"any": [{"lv": {"lt": 1}}, {"locked": True}]}, True),
             ({"all": [{"lv": {"gt": 1}}, {"locked": False}]}, False)]
    for cond, want in cases:
        norm_c, _w = norm({"layout": [], "when": cond})
        check(f"条件求值 {cond} → {want}", RD.cond_ok((norm_c or {}).get("when"), data) is want)
    check("空条件 = 显示", RD.cond_ok(None, data) is True and RD.cond_ok({}, data) is True)
    d, w = norm({"layout": [], "when": {"lv": {"bad_op": 1}}})
    check("未知运算符 → 条件忽略 + 告警", d["when"] is None and any("运算符" in x for x in w))
    d, w = norm({"layout": [], "when": {"all": [{"lv": {"gt": 1}}] * 9}})
    check("all 分支超限 → 只取前 4 + 告警",
          len(d["when"]["all"]) == 4 and any("分支超过" in x for x in w))
    d, w = norm({"layout": [], "when": {"all": [{"all": [{"all": [{"all": [{"lv": 1}]}]}]}]}})
    check("条件深度 > 4 → 该层忽略（整条随之消失）+ 告警",
          d["when"] is None and any("嵌套超过" in x for x in w), f"{d['when']} {w}")
    d, w = norm({"layout": [], "when": {"a": {"gt": 1}, "b": {"gt": 2}}})
    check("一个条件对象里两个字段 → 整条忽略 + 告警",
          d["when"] is None and any("只支持" in x for x in w))


def t3_norm_good():
    print("\n【3】正常声明的规范化（字段级）")
    fields = set(SCHEMA["$defs"]["my_dungeon"]["properties"])
    subs = {"stages": set(SCHEMA["$defs"]["stage"]["properties"])}
    d, w = norm(GOOD_DECL, fields, subs)
    check("★ 好声明 0 告警", w == [], str(w[:3]))
    check("版本 / 继承 / 备注", d["version"] == 1 and d["extends"] == "form"
          and d["notes"] == "包作者备注")
    check("块序与块 id 逐条保序", [b["id"] for b in d["layout"]]
          == ["intro", "base", "floors", "meta", "tb"])
    check("fields 块：字段序 + columns", d["layout"][1]["fields"] == ["name", "lv", "note"]
          and d["layout"][1]["columns"] == 2)
    check("list 块：source / item / 缺省 max_rows=200",
          d["layout"][2]["source"] == {"field": "stages"}
          and d["layout"][2]["max_rows"] == 200
          and d["layout"][2]["item"]["title"] == "{name}")
    check("★ 单项模板里的相对路径按**单项 schema** 校验（monsters 合法）",
          d["layout"][2]["item"]["subtitle"] == "怪 {monsters}")
    check("table 块：columns 表头保留（相对路径）",
          d["layout"][4]["item"]["columns"] == ["name", "monsters"])
    check("字段覆盖：label/note/widget/hidden", d["fields"]["stages"]["label"] == "楼层"
          and d["fields"]["note"]["widget"] == "textarea" and d["fields"]["note"]["hidden"] is True)
    check("槽位规范化（list_editor 缺省补全）",
          d["slots"]["list_editor"]["allow_add"] is True
          and d["slots"]["list_editor"]["item_fields"] == ["name", "monsters"])
    check("派生只校验名字（批 1 不执行）", d["derives"]["层数"]["fn"] == "count")
    check("钩子只许点名", d["hooks"] == {"not_blank": "not_blank"})
    check("只读字段", d["readonly"] == ["lv"])
    # 缺省值
    d2, _ = norm({"layout": [{"fields": ["name"]}]}, fields)
    b = d2["layout"][0]
    check("块缺省：id=b1 / kind=fields / columns=1 / collapsed=false",
          b["id"] == "b1" and b["kind"] == "fields" and b["columns"] == 1
          and b["collapsed"] is False)
    d3, w3 = norm({"layout": [], "sections": [{"label": "组", "blocks": [{"fields": ["name"]}]}]}, fields)
    check("分组缺省：id=s1 / collapsed=true（分组默认折起来）",
          d3["sections"][0]["id"] == "s1" and d3["sections"][0]["collapsed"] is True and w3 == [])
    d4, w4 = norm({"layout": [{"fields": ["name"]}], "sections": [{"label": "组", "blocks": []}]}, fields)
    check("layout 与 sections 同时给 → layout 优先 + 告警",
          d4["layout"] and d4["sections"] == [] and any("layout 优先" in x for x in w4))
    check("顶层未知键 → 丢弃 + 告警（绝不透传）",
          norm({"layout": [], "script": "alert(1)"})[1][0].find("未知键") >= 0
          and "script" not in norm({"layout": [], "script": "alert(1)"})[0])
    check("块内未知键 → 丢弃 + 告警",
          any("未知键" in x for x in norm({"layout": [{"fields": ["name"], "onclick": "x"}]},
                                          fields)[1]))
    d5, _ = norm({"layout": [], "readonly": ["lv", "name"]})
    check("readonly 规范化保序", d5["readonly"] == ["lv", "name"])


def t4_bad_decls():
    print("\n【4】坏声明逐条降级（忽略该项 + 可读告警，永不抛）")
    fields = set(SCHEMA["$defs"]["my_dungeon"]["properties"])
    subs = {"stages": set(SCHEMA["$defs"]["stage"]["properties"])}
    d, w = norm(["不是对象"], fields)
    check("顶层非对象 → 整份忽略 + 告警", d is None and w and "已回退第 2 层视图" in w[0])
    d, w = norm({"$version": 99, "layout": []}, fields)
    check("$version 未知 → 整份忽略（不猜语义）", d is None and "$version" in w[0])
    d, w = norm({"$extends": "weird", "layout": []}, fields)
    check("$extends 非法 → 按 form + 告警", d["extends"] == "form" and any("非法" in x for x in w))
    d, w = norm({"layout": [{"kind": "script", "text": "x"}, {"fields": ["name"]}]}, fields)
    check("★ 未知块类型 → 丢弃该块 + 告警，其余照渲染",
          len(d["layout"]) == 1 and d["layout"][0]["kind"] == "fields"
          and any("未知块类型" in x for x in w))
    d, w = norm({"layout": [{"kind": "fields", "fields": []}]}, fields)
    check("kind=fields 但 fields 空 → 跳过空块 + 告警",
          d["layout"] == [] and any("空块" in x for x in w))
    d, w = norm({"layout": [{"kind": "fields", "fields": ["zzz"]}]}, fields)
    check("★ R3：根字段不在 schema → 忽略该项 + 告警",
          d["layout"] == [] and any("不在该域 schema" in x for x in w))
    d, w = norm({"layout": [{"fields": ["../etc/passwd"]}]}, fields)
    check("★ 路径逃逸 ../ → 忽略 + 告警", d["layout"] == [] and any("不合规" in x for x in w))
    d, w = norm({"layout": [{"kind": "fields", "fields": ["stages.name"]}]}, fields)
    check("深层路径（根字段合法）放行", len(d["layout"]) == 1)
    d, w = norm({"layout": [{"kind": "list", "source": {"field": "stages"}}]}, fields, subs)
    check("list 无 item 模板 → 放行（前端用兜底标题）", len(d["layout"]) == 1)
    d, w = norm({"layout": [{"kind": "table", "source": {"field": "stages"}}]}, fields, subs)
    check("table 无 item.columns → 该块忽略 + 告警",
          d["layout"] == [] and any("columns" in x for x in w))
    d, w = norm({"layout": [{"kind": "list", "source": {"field": "nope"}}]}, fields)
    check("source.field 不在 schema → 该块忽略 + 告警", d["layout"] == [])
    d, w = norm({"layout": [{"kind": "list", "source": {"derive": "层数"}}]}, fields)
    check("source.derive 合法（批 1 不执行，树构建时再告警）",
          d["layout"] and d["layout"][0]["source"] == {"derive": "层数"})
    d, w = norm({"layout": [{"kind": "list", "source": {"nope": 1}}]}, fields)
    check("source 形状坏 → 该块忽略 + 告警", d["layout"] == [])
    d, w = norm({"layout": [{"kind": "text", "text": ""}]}, fields)
    check("kind=text 空正文 → 忽略 + 告警", d["layout"] == [])
    d, w = norm({"layout": [{"kind": "text", "text": "x" * 5000}]}, fields)
    check("超长正文被截断到 2000", len(d["layout"][0]["text"]) == RD.MAX_TEXT)
    d, w = norm({"layout": [], "slots": {"weird": {"field": "name"}}}, fields)
    check("未知槽位 → 丢弃 + 告警（绝不当透传）",
          d["slots"] == {} and any("未知槽位" in x for x in w))
    d, w = norm({"layout": [], "slots": {"list_editor": {"field": "stages",
                                                        "item_fields": ["name"], "onclick": "x"}}},
                fields, subs)
    check("槽位里未知键 → 丢弃 + 告警，槽位本身保留",
          "list_editor" in d["slots"] and any("不允许键" in x for x in w))
    d, w = norm({"layout": [], "slots": {"ref_picker": {"field": "name"}}}, fields)
    check("ref_picker 缺必填 domain → 该槽位忽略 + 告警", d["slots"] == {})
    d, w = norm({"layout": [], "hooks": {"nope": "nope"}}, fields)
    check("未知钩子 → 丢弃 + 告警", d["hooks"] == {} and any("未知校验钩子" in x for x in w))
    d, w = norm({"layout": [], "hooks": {"regex": "包自带正则"}}, fields)
    check("钩子值与名不一致 → 也丢弃（只许点名）", d["hooks"] == {})
    d, w = norm({"layout": [], "derives": {"x": {"fn": "shell_exec", "args": {}}}}, fields)
    check("未知派生函数 → 忽略 + 告警", d["derives"] == {} and any("白名单" in x for x in w))
    d, w = norm({"layout": [], "derives": {
        "a": {"fn": "sum", "args": {"field": "lv", "other": {"derive": "b"}}},
        "b": {"fn": "sum", "args": {"field": "lv", "other": {"derive": "a"}}}}}, fields)
    check("★ 派生**循环引用** → 两个都忽略 + 告警",
          d["derives"] == {} and any("循环引用" in x for x in w), str(d["derives"]))
    d, w = norm({"layout": [], "derives": {"a": {"fn": "sum", "args": {"field": "lv", "o": {"x": 1}}}}},
                fields)
    check("派生参数形状坏 → 忽略该参数 + 告警",
          "a" in d["derives"] and d["derives"]["a"]["args"] == {"field": "lv"}
          and any("args.o" in x for x in w), str(d["derives"]))
    bad_tpl = {"layout": [{"kind": "text", "text": " ".join("{lv}" for _ in range(9))}]}
    d, w = norm(bad_tpl, fields)
    check("插值点 > 8 → 该项忽略 + 告警", d["layout"] == [] and any("插值点超过" in x for x in w))
    d, w = norm({"layout": [{"kind": "text", "text": "{nope}"}]}, fields)
    check("插值根字段不在 schema → 忽略 + 告警", d["layout"] == [])
    d, w = norm({"layout": [{"kind": "text", "text": "{stages[*].name}"}]}, fields, subs)
    check("插值含 [*] → 忽略该项（与服务端插值口径一致）",
          d["layout"] == [] and any("[*]" in x for x in w))
    d, w = norm({"layout": [], "icon": "abcd"}, fields)
    check("icon 超 2 码点 → 忽略 + 告警", d["icon"] is None and any("码点" in x for x in w))
    d, w = norm({"layout": [], "fields": {"name": {"widget": "iframe"}}}, fields)
    check("未知控件 → 按 auto + 告警", d["fields"]["name"]["widget"] == "auto")
    d, w = norm({"layout": [], "fields": {"name": {"options": 123}}}, fields)
    check("options 形状坏 → 忽略 + 告警", "options" not in d["fields"]["name"])
    d, w = norm({"layout": [], "fields": {"name": {"options": {"ref": {"domain": "other"}}}}}, fields)
    check("options.ref 规范化（by 缺省 key）",
          d["fields"]["name"]["options"] == {"ref": {"domain": "other", "by": "key"}})
    d, w = norm({"layout": [], "fields": {"name": {"checks": ["not_blank", "nope"]}}}, fields)
    check("checks 里的未知钩子被剔除、合法保留",
          d["fields"]["name"]["checks"] == ["not_blank"])
    d, w = norm({"layout": [], "$allow_code": "yes"}, fields)
    check("$allow_code 非布尔 → 按 false + 告警", d["allow_code"] is False)
    d, w = norm({"layout": [], "title": "x" * 200}, fields)
    check("超长 title 截断到 80", len(d["title"]) == RD.MAX_TITLE)
    big = {"layout": [{"id": f"b{i}", "kind": "text", "text": "x"} for i in range(70)]}
    d, w = norm(big, fields)
    check("★ 超限：layout 65+ → 只取前 64 + 告警（truncated）",
          len(d["layout"]) == 64 and any("超过 64" in x for x in w))
    d, w = norm({"layout": [], "readonly": ["nope"]}, fields)
    check("readonly 里的非法字段被剔除 + 告警", d["readonly"] == [])


def t5_files_and_addressing():
    print("\n【5】寻址 / 兼容 / 文件级降级（R1-R6）")
    gd = tempfile.mkdtemp(prefix="fw_l3_decl_")
    try:
        ok = make_pkg(gd, "decl_ok", decl=GOOD_DECL)
        plain = make_pkg(gd, "decl_plain", decl=None)
        bad = make_pkg(gd, "decl_bad", decl="{oops")
        v99 = make_pkg(gd, "decl_v99", decl={"$version": 2, "layout": []})
        olddom = make_pkg(gd, "decl_olddom",
                          extra_files={"editor/render/nosuchdom.json": json.dumps({"layout": []})})
        huge = make_pkg(gd, "decl_huge", decl=None,
                        extra_files={"editor/render/my_dungeons.json":
                                     json.dumps({"layout": [{"kind": "text", "text": "x"}]})
                                     + " " * (RD.MAX_FILE_BYTES + 10)})
        legacy = make_pkg(gd, "decl_legacy", decl=None,
                          extra_files={"editor/render.json": json.dumps(
                              {"$version": 1, "my_dungeons": GOOD_DECL})})
        conflict = make_pkg(gd, "decl_conflict",
                            decl={"layout": [{"kind": "text", "text": "每域文件赢"}]},
                            extra_files={"editor/render.json": json.dumps(
                                {"my_dungeons": {"layout": [{"kind": "text", "text": "单文件"}]}})})
        legacy_bad = make_pkg(gd, "decl_legacybad", decl=None,
                              extra_files={"editor/render.json": "{oops"})
        schema_meta = make_pkg(gd, "decl_meta", decl=GOOD_DECL,
                               extra_files={"editor/render/$schema.json": json.dumps(
                                   {"title": "render 声明元 schema（包自带，批 4 才用）"})})
        code = make_pkg(gd, "decl_code", decl=GOOD_DECL,
                        extra_files={"editor/render/my_dungeons.py": "# 批 3 才跑\n",
                                     "editor/render/my_dungeons.html.js": "/* 批 5 */\n"})

        check("★ 正常声明：declared + active",
              R.declarations(ok, NEW_DOMS)["domains"]["my_dungeons"]["active"] is True)
        check("★ 无声明：什么都不报（零回归）",
              R.declarations(plain, NEW_DOMS)["domains"] == {}
              and R.render_warnings(plain, NEW_DOMS) == []
              and R.active(plain, "my_dungeons", NEW_DOMS) is False)
        check("声明目录都没有也不炸", R.declarations(os.path.join(gd, "nope"), NEW_DOMS)["domains"] == {})
        info = R.declarations(ok, NEW_DOMS)["domains"]["my_dungeons"]
        check("DomainRenderInfo 字段齐（契约 §3.1）",
              set(info) == {"file", "version", "extends", "active", "has_code", "has_iframe",
                            "blocks", "slots", "derives", "warnings"}, str(sorted(info)))
        check("info.file 是相对路径", info["file"] == "editor/render/my_dungeons.json")
        check("info.blocks 数对（5 块）", info["blocks"] == 5)
        check("★ 坏 JSON → active=false + 可读告警（不抛、不 500）",
              R.declarations(bad, NEW_DOMS)["domains"]["my_dungeons"]["active"] is False
              and any("读不了" in x for x in R.render_warnings(bad, NEW_DOMS)))
        check("$version 不认识 → active=false + 告警",
              R.declarations(v99, NEW_DOMS)["domains"]["my_dungeons"]["active"] is False
              and any("$version" in x for x in R.render_warnings(v99, NEW_DOMS)))
        check("★ 域不在有效域表 → 该文件忽略 + 告警（R2）",
              "nosuchdom" in R.declarations(olddom, NEW_DOMS)["domains"]
              and R.declarations(olddom, NEW_DOMS)["domains"]["nosuchdom"]["active"] is False
              and any("有效域表" in x for x in R.render_warnings(olddom, NEW_DOMS)))
        check("★ 单文件 > 256 KB → 忽略 + 告警（R5）",
              R.declarations(huge, NEW_DOMS)["domains"] == {}
              and any("256 KB" in x or "KB" in x for x in R.render_warnings(huge, NEW_DOMS)))
        check("★ 弃用形态 editor/render.json 仍能读 + 一条弃用告警（R6）",
              R.declarations(legacy, NEW_DOMS)["domains"]["my_dungeons"]["active"] is True
              and any("已弃用" in x for x in R.render_warnings(legacy, NEW_DOMS)))
        check("★ 同名域冲突 → 以每域文件为准 + 告警",
              any("以每域文件为准" in x for x in R.render_warnings(conflict, NEW_DOMS)))
        w = R.render_warnings(conflict, NEW_DOMS)
        check("冲突时读到的仍是每域那份", any("每域文件" in x for x in w))
        check("弃用文件坏了 → 忽略 + 告警（不炸）",
              R.declarations(legacy_bad, NEW_DOMS)["domains"] == {}
              and any("已弃用" in x for x in R.render_warnings(legacy_bad, NEW_DOMS)))
        check("$schema.json 不是域声明（跳过）",
              "$schema" not in R.declarations(schema_meta, NEW_DOMS)["domains"])
        dcode = R.declarations(code, NEW_DOMS)
        check("★ .py / .html.js 只**数存在性** → has_code / has_iframe / code_enabled",
              dcode["domains"]["my_dungeons"]["has_code"] is True
              and dcode["domains"]["my_dungeons"]["has_iframe"] is True
              and dcode["code_enabled"] is True)
        check("$allow_code:true 也算 code_enabled",
              R.declarations(make_pkg(gd, "decl_allow",
                                      decl={**GOOD_DECL, "$allow_code": True}),
                             NEW_DOMS)["code_enabled"] is True)
        check("limits 小节四键齐（契约 §3.1）",
              set(R.declarations(ok, NEW_DOMS)["limits"])
              == {"max_tree_bytes", "max_blocks", "max_list_items", "timeout_ms"})
        # 缓存：改文件后重新解析
        p = os.path.join(ok, "editor/render/my_dungeons.json")
        _write(p, {"$version": 1, "layout": [], "zzz": 1})
        check("★ 声明签名缓存会失效（改了文件就重解析）",
              any("未知键" in x for x in R.render_warnings(ok, NEW_DOMS)))
        _write(p, GOOD_DECL)
        check("还原后 0 告警", R.render_warnings(ok, NEW_DOMS) == [])
        check("declared() 直接给规范化声明", R.declared(ok, "my_dungeons", NEW_DOMS)[0] is not None)
    finally:
        shutil.rmtree(gd, ignore_errors=True)


def t6_http_render_endpoint():
    print("\n【6】HTTP：GET /api/package/<id>/render")
    gd = tempfile.mkdtemp(prefix="fw_l3_render_http_")
    SRV.GAMES_DIR = gd
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), SRV.H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        make_pkg(gd, "p3_ok", decl=GOOD_DECL)
        make_pkg(gd, "p3_plain")
        make_pkg(gd, "p3_bad", decl="{oops")
        make_pkg(gd, "p3_code", decl={**GOOD_DECL, "$allow_code": True},
                 extra_files={"editor/render/my_dungeons.html.js": "/* x */\n"})
        # 一个「有 views.json 但没有 render」的包：effective.source 应为 views/builtin
        make_pkg(gd, "p3_views", extra_files={
            "editor/views.json": json.dumps({"my_dungeons": {"view": "table"}})})

        st, j = req(base, "GET", "/api/package/p3_ok/render")
        check("200 + 契约字段齐（ok/package/code_enabled/domains/effective/limits/warnings）",
              st == 200 and j.get("ok") is True and j.get("package") == "p3_ok"
              and set(j) >= {"ok", "package", "code_enabled", "domains", "effective", "limits",
                             "warnings"}, f"{st} {sorted(j)}")
        check("★ domains.my_dungeons.active = true", j["domains"]["my_dungeons"]["active"] is True)
        check("effective.my_dungeons：render/extends/active/source",
              j["effective"]["my_dungeons"]["source"] == "render"
              and j["effective"]["my_dungeons"]["render"] is True
              and j["effective"]["my_dungeons"]["extends"] == "form")
        check("未声明域仍是既有分派（instances → builtin / texts → none）",
              j["effective"]["instances"]["source"] == "builtin"
              and j["effective"]["texts"]["source"] == "none")
        check("limits 四键 + 超时缺省 1500ms", j["limits"]["timeout_ms"] == 1500)
        st2, j2 = req(base, "GET", "/api/package/p3_plain/render")
        check("★ 没声明的包：declared 空 + 0 告警 + code_enabled False（零回归）",
              st2 == 200 and j2["domains"] == {} and j2["warnings"] == []
              and j2["code_enabled"] is False)
        check("没声明的包 effective 全是 views/builtin/none",
              all(v["source"] in ("views", "builtin", "none") and v["render"] is False
                  for v in j2["effective"].values()))
        st3, j3 = req(base, "GET", "/api/package/p3_bad/render")
        check("★ 坏声明 → 200（不是 500）+ active=false + 可读告警",
              st3 == 200 and j3["domains"]["my_dungeons"]["active"] is False
              and any("读不了" in w for w in j3["warnings"]), f"{st3} {j3.get('warnings')}")
        st4, j4 = req(base, "GET", "/api/package/p3_code/render")
        check("★ code_enabled=true（$allow_code 或 .html.js）",
              st4 == 200 and j4["code_enabled"] is True
              and j4["domains"]["my_dungeons"]["has_iframe"] is True)
        st5, j5 = req(base, "GET", "/api/package/p3_views/render")
        check("有 views.json 的域：source=views", j5["effective"]["my_dungeons"]["source"] == "views")
        st6, j6 = req(base, "GET", "/api/package/nosuchpkg/render")
        check("未知包 → 404（照旧语义）", st6 == 404 and j6.get("ok") is False)
        raw_len = len(json.dumps(j, ensure_ascii=False).encode("utf-8"))
        check("响应 ≤ 64 KB（契约 §3.1 的接口约束）", raw_len <= 64 * 1024, str(raw_len))
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(gd, ignore_errors=True)


def t7_views_subsection():
    print("\n【7】HTTP：/api/package/<id>/views 的 render 小节（既有键一个不动）")
    gd = tempfile.mkdtemp(prefix="fw_l3_views_")
    SRV.GAMES_DIR = gd
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), SRV.H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        make_pkg(gd, "v3_ok", decl=GOOD_DECL)
        make_pkg(gd, "v3_plain")
        st, j = req(base, "GET", "/api/package/v3_ok/views")
        check("200 + render 小节四键",
              st == 200 and set(j["render"]) == {"declared", "active", "code_enabled", "warnings"},
              str(sorted(j.get("render") or {})))
        check("declared / active 都点名该域",
              j["render"]["declared"] == ["my_dungeons"] and j["render"]["active"] == ["my_dungeons"])
        check("既有键原样在（views / effective / builtin / names / warnings）",
              set(j) >= {"ok", "views", "effective", "builtin", "names", "warnings"})
        st2, j2 = req(base, "GET", "/api/package/v3_plain/views")
        check("★ 没声明：render.declared 空、warnings 空（零回归）",
              st2 == 200 and j2["render"]["declared"] == [] and j2["render"]["warnings"] == [])
        check("没声明时既有键逐项还是老样子",
              j2["views"] == {} and j2["warnings"] == []
              and set(j2["effective"]) == {"maps", "drop_pools", "instances"})
        st3, j3 = req(base, "GET", "/api/package/v3_plain")
        check("包概览的 domain_warnings 仍为空（无声明 = 不新增噪声）",
              st3 == 200 and j3.get("domain_warnings") == [], str(j3.get("domain_warnings")))
        st4, j4 = req(base, "GET", "/api/package/v3_ok")
        check("★ 有声明时概览的告警出口含渲染告警（设计 §3.9 的三处出口复用）",
              st4 == 200 and isinstance(j4.get("domain_warnings"), list))
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(gd, ignore_errors=True)


def main() -> int:
    print("== 第 3 层·批 1「声明面」门禁（声明 schema / 白名单 / 寻址 / 降级 / HTTP）==")
    t0_zero_execution()
    t1_whitelists()
    t2_paths_and_conditions()
    t3_norm_good()
    t4_bad_decls()
    t5_files_and_addressing()
    t6_http_render_endpoint()
    t7_views_subsection()
    print(f"\n===== 结果：通过 {PASS} / {PASS + FAIL} =====")
    for f in FAILURES:
        print("  ❌", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
