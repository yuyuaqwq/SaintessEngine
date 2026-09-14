#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：编辑器扩展**第 3 层 · 批 1** —— **受限渲染树**（声明 → 树 → 前端）。

设计真源：`overnight/layer3-render-design.md` §4（渲染树 / 五种块 / 上限 / 树≠HTML）
          + §9 批 1；`overnight/layer3-render-contracts.md` §2（树字段表）+ §3.2（/view 协议）。

本门禁钉住四件事：

  ① **D0 纯声明**：声明 + 条目数据 → 树；块序 / 字段序 / 插值**逐字**等于声明；
     声明里 `when` 已在服务端求值（树里没有条件）；**派生值一行都不算**（批 2 的事）。
  ② **限额**：块数 64 / 分页 6 / list 200 / 树字节 256 KB / 告警 64 条 —— 超限**截断 + 告警**，
     不报错、不 500、不白屏。
  ③ **降级链**：`?view=` > render 声明 > views.json > 内置默认；声明坏 / `when` 不满足 / 树建不出
     → **仍然 200**，`view` 是第 2 层结果 + `view_warnings` 带 `{stage, message}`。
  ④ **零回归**：包没声明 render 时 `/view` 响应与改造前**逐项一致**；渲染链路**零写盘**
     （前后包目录哈希不变）。

另含：前端白名单渲染器的 Node 门禁调度（`tests/js/render_tree_test.js`，同 graph 布局那条先例）。

跑法：python tests/test_editor_layer3_render_tree.py
退出码：0 = 全过（或本机无 node 而显式跳过前端段）；1 = 有失败。
"""
from __future__ import annotations

import hashlib
import json
import os
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
           "stages": [{"name": "一层", "monsters": ["史莱姆", "哥布林"], "boss": []},
                      {"name": "二层", "monsters": ["炎龙"], "boss": ["炎龙"]}],
           "reward_pool": "pool_a", "note": ""}
GLOSS = {"fields": {"name": {"zh": "名称"}, "lv": {"zh": "需求等级"},
                    "stages": {"zh": "楼层", "note": "每层一行"},
                    "monsters": {"zh": "怪物"}, "boss": {"zh": "Boss"},
                    "reward_pool": {"zh": "奖励池"}, "note": {"zh": "备注"}}}
DECL = {
    "$version": 1, "$extends": "form", "title": "副本 {name}", "icon": "🏯",
    "layout": [
        {"id": "intro", "kind": "text", "label": "说明",
         "text": "**{name}**：{lv} 级，共 {stages} 层。{{字面花括号}}"},
        {"id": "base", "kind": "fields", "label": "基础", "columns": 2, "fields": ["name", "lv"]},
        {"id": "floors", "kind": "list", "label": "楼层", "source": {"field": "stages"},
         "item": {"title": "{name}", "subtitle": "怪：{monsters}",
                  "badges": [{"text": "Boss", "tone": "bad", "when": {"boss": {"exists": True}}},
                             {"text": "普通", "tone": "info", "when": {"boss": {"exists": False}}}],
                  "fields": ["monsters"]}},
        {"id": "meta", "kind": "kv", "label": "其它", "source": {"field": "stages"}},
        {"id": "tb", "kind": "table", "label": "楼层表", "source": {"field": "stages"},
         "item": {"columns": ["name", "monsters"]}},
        {"id": "gone", "kind": "text", "label": "不显示", "text": "x", "when": {"lv": {"gt": 99}}},
    ],
    "fields": {"stages": {"label": "楼层", "note": "每层一行"}, "note": {"widget": "textarea"}},
    "derives": {"层数": {"fn": "count", "args": {"field": "stages"}, "label": "层数"}},
    "readonly": ["lv"],
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


def _write(path, obj, raw=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(obj if raw else json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def make_pkg(root, pid, *, decl=None, domains=None, data=None, views=None, vocab=GLOSS):
    pkg = os.path.join(root, pid)
    for sub in ("content/data", "editor/render", "schemas"):
        os.makedirs(os.path.join(pkg, *sub.split("/")), exist_ok=True)
    _write(os.path.join(pkg, "game.json"),
           {"id": pid, "name": pid, "desc": "第 3 层树门禁", "engine": ">=0.1",
            "domains": list(domains or NEW_DOMS), "entry": "content/apply.py"})
    _write(os.path.join(pkg, "editor/domains.json"), domains if domains is not None else NEW_DOMS)
    _write(os.path.join(pkg, "schemas/my_dungeons.schema.json"), SCHEMA)
    for dom, doc in (data or {"my_dungeons": {"d1": DUNGEON}}).items():
        _write(os.path.join(pkg, "content/data", f"{dom}.json"), doc)
    if vocab is not None:
        _write(os.path.join(pkg, "editor/glossary/my_dungeons.json"), vocab)
    if views is not None:
        _write(os.path.join(pkg, "editor/views.json"), views)
    if decl is not None:
        _write(os.path.join(pkg, "editor/render/my_dungeons.json"), decl, raw=isinstance(decl, str))
    return pkg


def build(pkg, key="d1", data=None, dom="my_dungeons"):
    return R.build(pkg, dom, key, DUNGEON if data is None else data, NEW_DOMS)


def _hash_tree(root):
    """包目录内容哈希（渲染**只读**的门禁判据）。"""
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


# ══════════════════════════════════════════════════════════════════════
def t1_tree_basic():
    print("\n【1】D0 纯声明 → 树（块序 / 插值 / 五种形态）")
    gd = tempfile.mkdtemp(prefix="fw_l3_tree_")
    try:
        pkg = make_pkg(gd, "t_ok", decl=DECL)
        tree = build(pkg)
        check("★ 树顶层字段齐（契约 §2.1）",
              tree["ok"] is True and tree["render_version"] == 1
              and tree["domain"] == "my_dungeons" and tree["key"] == "d1"
              and tree["source"] == "package"
              and set(tree) >= {"ok", "render_version", "domain", "key", "source", "decl_sha",
                                "title", "tabs", "readonly_paths", "field_overrides", "warnings",
                                "elapsed_ms", "truncated"}, str(sorted(tree)))
        check("decl_sha 是 16 位 hex（前端缓存键）",
              len(tree["decl_sha"]) == 16 and all(c in "0123456789abcdef" for c in tree["decl_sha"]))
        check("title 插值 + 图标回退",
              tree["title"] == "副本 试炼场" and tree["icon"] == "🏯")
        check("只读字段并集（readonly + fields.*.readonly）", tree["readonly_paths"] == ["lv"])
        check("field_overrides 只带契约 §2.1 的四个键",
              tree["field_overrides"]["stages"] == {"label": "楼层", "note": "每层一行"}
              and tree["field_overrides"]["note"] == {"widget": "textarea"})
        blocks = tree["tabs"][0]["blocks"]
        check("★ 块序逐条等于声明（6 块中 when 屏蔽 1 块 → 5 块）",
              [b["id"] for b in blocks] == ["intro", "base", "floors", "meta", "tb"],
              str([b["id"] for b in blocks]))
        check("★ 树里没有条件（when 已求值）", all("when" not in b for b in blocks))
        intro = blocks[0]
        check("text 块：插值在服务端算完（含 {{ 字面量转义）",
              intro["text"] == "**试炼场**：12 级，共 [{\"name\": \"一层\", \"monsters\": "
                               "[\"史莱姆\", \"哥布林\"], \"boss\": []}, {\"name\": \"二层\", "
                               "\"monsters\": [\"炎龙\"], \"boss\": [\"炎龙\"]}] 层。{字面花括号}",
              intro["text"])
        miss = make_pkg(gd, "t_missing", decl={"$version": 1, "$extends": "none", "layout": [
            {"id": "m", "kind": "text", "text": "池：{reward_pool}"}]})
        tmiss = build(miss, data={"name": "缺字段", "lv": 1, "stages": []})
        check("插值取不到 → 渲染为空 + 一条可读告警（不静默）",
              tmiss["tabs"][0]["blocks"][0]["text"] == "池："
              and any("reward_pool" in w for w in tmiss["warnings"]), str(tmiss["warnings"]))
        fld = blocks[1]
        check("fields 块：FieldRef 字段齐 + 顺序即版面顺序",
              fld["kind"] == "fields" and fld["columns"] == 2
              and [i["path"] for i in fld["items"]][:2] == ["name", "lv"]
              and set(fld["items"][0]) >= {"path", "label", "widget", "readonly", "required",
                                          "has_value"}, str(fld["items"][0]))
        check("FieldRef：label 取词汇表 / readonly / required / has_value",
              fld["items"][0]["label"] == "名称" and fld["items"][0]["required"] is True
              and fld["items"][0]["has_value"] is True
              and fld["items"][1]["readonly"] is True)
        check("★ 树里**不带字段值**（只有 has_value 元信息，值由前端从条目数据取）",
              "value" not in fld["items"][0] and fld["items"][0].get("has_value") is True)
        lst = blocks[2]
        check("list 块：每项 title/subtitle/row_index",
              lst["kind"] == "list" and len(lst["list"]) == 2
              and lst["list"][0]["title"] == "一层"
              and lst["list"][0]["subtitle"] == "怪：[\"史莱姆\", \"哥布林\"]"
              and lst["list"][1]["row_index"] == 1, str(lst["list"]))
        check("★ 角标按 when 求值 + tone 白名单",
              lst["list"][0]["badges"] == [{"text": "普通", "tone": "info"}]
              and lst["list"][1]["badges"] == [{"text": "Boss", "tone": "bad"}],
              str([i.get("badges") for i in lst["list"]]))
        check("list 项内 fields 也带元信息", lst["list"][0]["fields"][0]["path"] == "monsters")
        kv = blocks[3]
        check("kv 块：rows 是 {label, value} 展示串（键走词汇表）",
              kv["kind"] == "kv" and len(kv["rows"]) == 2
              and isinstance(kv["rows"][0]["value"], str)
              and set(kv["rows"][0]) == {"label", "value"})
        tb = blocks[4]
        check("table 块：表头走词汇表 + 单元格全是展示串",
              tb["kind"] == "table" and tb["headers"] == ["名称", "怪物"]
              and tb["rows"][0]["cells"] == ["一层", "[\"史莱姆\", \"哥布林\"]"]
              and all(isinstance(c, str) for r in tb["rows"] for c in r["cells"]))
        check("★ 协议里没有 html/style/class 字段（H1：出现即丢弃）",
              not any(k in b for b in blocks for k in ("html", "innerHTML", "style", "class", "script")))
        check("elapsed_ms 是整数、truncated=false", isinstance(tree["elapsed_ms"], int)
              and tree["truncated"] is False)
        check("★ 派生值批 1 **一个都不算**（树里没有 derives 结果键）",
              "derives" not in tree
              and R.declarations(pkg, NEW_DOMS)["domains"]["my_dungeons"]["derives"] == ["层数"])
    finally:
        shutil.rmtree(gd, ignore_errors=True)


def t2_when_and_extends():
    print("\n【2】条件求值 / $extends 三态 / 派生来源降级")
    gd = tempfile.mkdtemp(prefix="fw_l3_when_")
    try:
        pkg = make_pkg(gd, "t_when", decl={
            "$version": 1, "$extends": "none", "layout": [
                {"id": "a", "kind": "text", "text": "A", "when": {"lv": {"gt": 5}}},
                {"id": "b", "kind": "text", "text": "B", "when": {"lv": {"gt": 50}}},
            ]})
        tree = build(pkg)
        check("★ 块级 when 命中才进树（A 在、B 不在）",
              [b["id"] for b in tree["tabs"][0]["blocks"]] == ["a"] and tree["ok"] is True)
        pkg2 = make_pkg(gd, "t_when2", decl={
            "$version": 1, "layout": [{"kind": "text", "text": "x"}],
            "when": {"lv": {"gt": 100}}})
        tree2 = build(pkg2)
        check("★ 顶层 when 不满足 → ok=false + stage=decl（调用方整域降级）",
              tree2["ok"] is False and tree2["stage"] == "decl" and "when" in tree2["message"])
        # $extends 三态
        base = {"$version": 1, "layout": [{"id": "b1", "kind": "fields", "fields": ["name"]}]}
        t_form = build(make_pkg(gd, "t_form", decl={**base, "$extends": "form"}))
        t_view = build(make_pkg(gd, "t_view", decl={**base, "$extends": "view"}))
        t_none = build(make_pkg(gd, "t_none", decl={**base, "$extends": "none"}))
        form_paths = [i["path"] for i in t_form["tabs"][0]["blocks"][0]["items"]]
        view_paths = [i["path"] for i in t_view["tabs"][0]["blocks"][0]["items"]]
        check("★ $extends=form：没提到的字段追加到最后一个 fields 块（不丢字段）",
              form_paths[:1] == ["name"] and set(form_paths) >= {"lv", "stages", "reward_pool", "note"}
              and len(form_paths) == 5, str(form_paths))
        check("★ $extends=view / none：只渲染声明里的块（不追加其余字段）",
              view_paths == ["name"] and [i["path"] for i in t_none["tabs"][0]["blocks"][0]["items"]]
              == ["name"])
        # 派生来源 → 批 1 不执行 → 丢块 + 告警
        pkg3 = make_pkg(gd, "t_der", decl={
            "$version": 1, "layout": [{"id": "d", "kind": "list", "source": {"derive": "层数"}}],
            "derives": {"层数": {"fn": "count", "args": {"field": "stages"}}}})
        tree3 = build(pkg3)
        check("★ source={derive:…}：批 1 不执行 → 该块略过 + 可读告警（不是 500）",
              tree3["ok"] is True and tree3["tabs"][0]["blocks"] == []
              and any("批 2" in w and "d" in w for w in tree3["warnings"]))
        pkg4 = make_pkg(gd, "t_der2", decl={
            "$version": 1, "layout": [{"id": "x", "kind": "text", "text": "值={derive:层数}"}],
            "derives": {"层数": {"fn": "count", "args": {"field": "stages"}}}})
        tree4 = build(pkg4)
        check("★ 插值 {derive:…}：渲染为空 + 告警（前端不做模板求值）",
              tree4["tabs"][0]["blocks"][0]["text"] == "值="
              and any("{derive:层数}" in w for w in tree4["warnings"]))
    finally:
        shutil.rmtree(gd, ignore_errors=True)


def t3_zh_and_limits():
    print("\n【3】词汇表插值 / 空数据 / 限额（截断 + 告警，不报错）")
    gd = tempfile.mkdtemp(prefix="fw_l3_lim_")
    try:
        pkg = make_pkg(gd, "t_zh", decl={
            "$version": 1, "$extends": "none", "layout": [
                {"id": "z", "kind": "text", "text": "字段名：{lv|zh}；值：{lv}"}]})
        tree = build(pkg)
        check("★ {路径|zh} 走包词汇表的中文名；{路径} 是值",
              tree["tabs"][0]["blocks"][0]["text"] == "字段名：需求等级；值：12",
              tree["tabs"][0]["blocks"][0]["text"])
        pkg_zh = make_pkg(gd, "t_zh2", decl={
            "$version": 1, "$extends": "none", "layout": [
                {"id": "z", "kind": "text", "text": "{lv|zh}"}]}, vocab=None)
        check("没有词汇表时 {路径|zh} 回落原值（不编译名）",
              build(pkg_zh)["tabs"][0]["blocks"][0]["text"] == "12")
        # 空数据
        empty_pkg = make_pkg(gd, "t_empty", decl={**DECL, "$extends": "none"})
        empty = build(empty_pkg, data={"name": "空的", "lv": 1, "stages": []})
        kinds = {b["id"]: b for b in empty["tabs"][0]["blocks"]}
        check("list 空数据 → list=[] + empty 占位",
              kinds["floors"]["list"] == [] and kinds["floors"]["empty"] == "（空）")
        check("kv/table 空数据也给 empty 占位",
              kinds["meta"].get("empty") == "（空）" and kinds["tb"].get("empty") == "（空）")
        # list 上限 200
        many = [{"name": f"第{i}层", "monsters": [], "boss": []} for i in range(260)]
        big = build(empty_pkg, data={"name": "大", "lv": 1, "stages": many})
        floors = [b for b in big["tabs"][0]["blocks"] if b["id"] == "floors"][0]
        check("★ list 预渲染项 ≤ 200（契约 §4.4）+ truncated 标记 + 告警",
              len(floors["list"]) == 200 and floors["truncated"] is True
              and any("截断" in w for w in big["warnings"]))
        # 分页上限 6
        secs = [{"id": f"s{i}", "label": f"组{i}", "blocks": [{"kind": "text", "text": "x"}]}
                for i in range(9)]
        tsec = build(make_pkg(gd, "t_sec", decl={"$version": 1, "sections": secs}))
        check("★ sections → tabs；分页 ≤ 6（多出的并入最后一个）+ truncated",
              len(tsec["tabs"]) == 6 and tsec["truncated"] is True
              and any("分组数超过" in w for w in tsec["warnings"]))
        # 树字节上限
        cols = ["name", "monsters", "boss"]
        rows = [{"name": "层" * 60, "monsters": ["怪" * 60] * 20, "boss": ["王" * 60]} for _ in range(400)]
        tbl_decl = {"$version": 1, "$extends": "none", "layout": [
            {"id": "t", "kind": "table", "source": {"field": "stages"}, "max_rows": 500,
             "item": {"columns": cols}}]}
        tpkg = make_pkg(gd, "t_bytes", decl=tbl_decl)
        tbig = build(tpkg, data={"name": "x", "lv": 1, "stages": rows})
        size = len(json.dumps(tbig, ensure_ascii=False).encode("utf-8"))
        check("★ 树序列化字节 ≤ 256 KB（超限从末尾丢块 + truncated + 告警）",
              size <= RD.MAX_TREE_BYTES and tbig["truncated"] is True
              and any("256 KB" in w for w in tbig["warnings"]), str(size))
        # 告警条数上限：用 sections（不受 layout 64 上限约束）堆出 > 64 条**互不相同**的告警
        noisy = {"$version": 1, "$extends": "none", "sections": [
            {"id": f"s{i}", "label": f"组{i}", "blocks": [
                {"id": f"n{i}_{j}", "kind": "list", "source": {"field": "stages"}, "max_rows": 1}
                for j in range(3)]} for i in range(30)]}
        tnoisy = build(make_pkg(gd, "t_noisy", decl=noisy),
                       data={"name": "x", "lv": 1, "stages": DUNGEON["stages"]})
        check("★ 告警 ≤ 64 条 + warnings_truncated 标记",
              len(tnoisy["warnings"]) == 64 and tnoisy.get("warnings_truncated") is True,
              str(len(tnoisy["warnings"])))
    finally:
        shutil.rmtree(gd, ignore_errors=True)


def t4_http_and_regress():
    print("\n【4】HTTP 端到端：分派优先级 / 降级 / 零回归 / 零写盘")
    gd = tempfile.mkdtemp(prefix="fw_l3_http_")
    SRV.GAMES_DIR = gd
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), SRV.H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        pkg = make_pkg(gd, "h_ok", decl=DECL)
        make_pkg(gd, "h_plain", decl=None,
                 data={"my_dungeons": {"d1": DUNGEON},
                       "instances": {"i1": {"name": "试炼场", "stages": [{"name": "一层"}]}},
                       "maps": {"m1": {"name": "村", "topology": "chain",
                                       "nodes": [{"id": "a", "name": "甲", "role": "hub"}]}},
                       "drop_pools": {"p1": {"type": "weighted",
                                             "entries": [{"item": "x", "w": 1}]}}})
        make_pkg(gd, "h_bad", decl="{oops",
                 views={"my_dungeons": {"view": "table"}})
        make_pkg(gd, "h_badnoview", decl="{oops")
        make_pkg(gd, "h_badblock", decl={"$version": 1, "layout": [
            {"kind": "script", "text": "x"}, {"kind": "text", "text": "留下的块"}]})
        make_pkg(gd, "h_when", decl={"$version": 1, "when": {"lv": {"gt": 999}},
                                     "layout": [{"kind": "text", "text": "x"}]},
                 views={"my_dungeons": {"view": "table"}})
        make_pkg(gd, "h_views", decl={**DECL, "$extends": "view"},
                 views={"my_dungeons": {"view": "table"}})
        make_pkg(gd, "h_noview", decl=DECL, domains=NEW_DOMS)
        before = _hash_tree(pkg)

        st, j = req(base, "GET", "/api/package/h_ok/d/my_dungeons/d1/view")
        check("★ render 声明生效 → 200 + view_source=package-render",
              st == 200 and j.get("view_source") == "package-render"
              and j.get("view_name") == "package-render", f"{st} {j.get('view_source')}")
        check("响应外壳与既有同构（ok/view_name/view_source/view_warnings + view）",
              set(j) >= {"ok", "view_name", "view_source", "view_warnings", "view"})
        check("view 就是受限渲染树（ok/tabs/decl_sha）",
              j["view"]["ok"] is True and j["view"]["tabs"][0]["blocks"][0]["id"] == "intro"
              and len(j["view"]["decl_sha"]) == 16)
        check("200 且 ok=true（可渲染态）", j["ok"] is True)
        st, j2 = req(base, "GET", "/api/package/h_ok/d/my_dungeons/d1/view?view=table")
        check("★ ?view= 显式指定**最高优先**：绕过 render，走内置视图",
              st == 200 and j2.get("view_source") == "query" and j2.get("view") == "table")
        st, j3 = req(base, "GET", "/api/package/h_ok/d/my_dungeons/d1/view?view=nope")
        check("?view= 未知内置名 → 400（既有语义不变）", st == 400)
        check("★ 渲染链路零写盘（包目录哈希前后一致）", _hash_tree(pkg) == before)

        # 声明坏 → 降级（不是 500、不是白屏）：第 2 层 results + 黄条
        st, jb = req(base, "GET", "/api/package/h_bad/d/my_dungeons/d1/view")
        stages = [w for w in (jb.get("view_warnings") or []) if isinstance(w, dict)]
        check("★ 坏声明 → 200（不是 500）+ 回退第 2 层结果",
              st == 200 and jb.get("view_source") == "package"
              and jb.get("view") == "table", f"{st} {jb.get('view_source')}")
        check("★ view_warnings 带 {stage, message}（契约 §3.2 的降级形状）",
              bool(stages) and stages[-1].get("stage") == "decl" and stages[-1].get("message"),
              str(jb.get("view_warnings")))
        check("降级时仍带可读字符串告警（黄条不静默）",
              any(isinstance(w, str) and "读不了" in w for w in (jb.get("view_warnings") or [])))
        st, jbn = req(base, "GET", "/api/package/h_badnoview/d/my_dungeons/d1/view")
        check("坏声明 + 没有第 2 层视图 → 不是 500（404 带告警，前端有表单兜底）",
              st == 404 and st != 500, str(st))
        # when 不满足 → 降级
        st, jw = req(base, "GET", "/api/package/h_when/d/my_dungeons/d1/view")
        dw = [w for w in (jw.get("view_warnings") or []) if isinstance(w, dict)]
        check("★ 顶层 when 不满足 → 200 + stage=decl（整域回退，不白屏）",
              st == 200 and dw and dw[-1]["stage"] == "decl", f"{st} {jw.get('view_warnings')}")
        # views.json 被 render 覆盖 → info 告警
        st, jv = req(base, "GET", "/api/package/h_views/d/my_dungeons/d1/view")
        check("★ views.json 与 render 同时存在 → render 优先 + 覆盖告警",
              st == 200 and jv.get("view_source") == "package-render"
              and any(isinstance(w, str) and "被 render 声明覆盖" in w
                      for w in (jv.get("view_warnings") or [])), str(jv.get("view_warnings")))

        # 零回归：没声明的包逐项不变
        st, jp = req(base, "GET", "/api/package/h_plain/d/instances/i1/view")
        check("★ 没声明 render：view_source 仍是 builtin（逐项不变）",
              st in (200, 422) and jp.get("view_source") == "builtin"
              and jp.get("view_name") == "instance_view" and "render_stage" not in jp,
              f"{st} {jp.get('view_source')}")
        check("没声明时响应里没有 render 相关新键（render_stage / view dict 都不出现）",
              "render_stage" not in jp and "view" not in jp, str(sorted(jp)))
        st, jp2 = req(base, "GET", "/api/package/h_plain/d/drop_pools/p1/view")
        check("没声明时 drop_pools 仍走 loot_view",
              st == 200 and jp2.get("view_source") == "builtin" and jp2.get("view_name") == "loot_view")
        st, jp3 = req(base, "GET", "/api/package/h_plain/d/maps/m1/view")
        check("没声明时 maps 仍走 space_view",
              st == 200 and jp3.get("view_source") == "builtin" and jp3.get("view_name") == "space_view")
        st, jp4 = req(base, "GET", "/api/package/h_plain/d/plaindom/x/view")
        check("未知域 → 404（照旧语义）", st == 404)
        st, jp5 = req(base, "GET", "/api/package/h_noview/d/my_dungeons/d1/view")
        check("有 render 声明就一定有视图出口（不再是 404）",
              st == 200 and jp5.get("view_source") == "package-render")
        st, jp6 = req(base, "GET", "/api/package/h_plain/d/my_dungeons/d1/view")
        check("域里既没声明也没内置视图 → 404（与改造前一致）", st == 404)
        # 声明级告警（未知块）也要进树 → 前端黄条可见（不许静默）
        st, jw2 = req(base, "GET", "/api/package/h_badblock/d/my_dungeons/d1/view")
        check("★ 声明里有未知块 → 200 + 树里带该告警（前端黄条可见）",
              st == 200 and jw2.get("view_source") == "package-render"
              and any(isinstance(w, str) and "未知块类型" in w
                      for w in (jw2.get("view_warnings") or [])), str(jw2.get("view_warnings")))

        # 写回链不受影响（渲染与写回解耦）
        good = dict(DUNGEON)
        st, js = req(base, "PUT", "/api/package/h_ok/d/my_dungeons/d2", {"data": good})
        check("★ 保存（PUT）照常可用（渲染失败/成功都不影响写回链）", st == 200 and js.get("ok"), str(st))
        st, jg = req(base, "GET", "/api/package/h_ok/d/my_dungeons/d2/view")
        check("新条目也能渲染（树按 key 现算）", st == 200 and jg.get("view_source") == "package-render")
        st, jbad = req(base, "PUT", "/api/package/h_ok/d/my_dungeons/bad", {"data": {"name": "x"}})
        check("校验链照旧（缺必填 → 422）", st == 422)
        # 坏**数据**（不是坏声明）也不许 500：数据文件写成坏 JSON → 读成 {} → 树照建
        dp = os.path.join(pkg, "content/data/my_dungeons.json")
        with open(dp, "w", encoding="utf-8") as f:
            f.write("{oops")
        st, jd = req(base, "GET", "/api/package/h_ok/d/my_dungeons/d1/view")
        check("★ 数据文件坏 JSON → 不是 500（树按空数据渲染 + 告警）",
              st in (200, 422) and st != 500, f"{st} {jd.get('view_source')}")
        _write(dp, {"d1": DUNGEON})
        st, jr = req(base, "GET", "/api/package/h_ok/d/my_dungeons/d1/view")
        check("还原数据后回到 200 + package-render",
              st == 200 and jr.get("view_source") == "package-render")
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(gd, ignore_errors=True)


def t5_js_frontend():
    print("\n【5】前端白名单渲染器（tests/js/render_tree_test.js —— 有 node 就真跑）")
    js = os.path.join(HERE, "js", "render_tree_test.js")
    node = shutil.which("node")
    if not node:
        print("  ⚠ 本机没有 node —— 跳过（前端段需人工用浏览器验证；这不影响后端判据）")
        return
    if not os.path.exists(js):
        check("找得到 tests/js/render_tree_test.js", False, js)
        return
    pr = subprocess.run([node, js], capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=ROOT, timeout=180,
                        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (pr.stdout or "") + (pr.stderr or "")
    tail = [ln for ln in out.splitlines() if ln.startswith("通过 ")]
    check(f"前端渲染器门禁全绿（{tail[-1] if tail else '无摘要'}）", pr.returncode == 0,
          out.strip().splitlines()[-1] if out.strip() else "")
    if pr.returncode != 0:
        print(out[-2500:])


def main() -> int:
    print("== 第 3 层·批 1「受限渲染树」门禁（树构建 / 限额 / 降级 / 零回归 / 前端）==")
    t1_tree_basic()
    t2_when_and_extends()
    t3_zh_and_limits()
    t4_http_and_regress()
    t5_js_frontend()
    print(f"\n===== 结果：通过 {PASS} / {PASS + FAIL} =====")
    for f in FAILURES:
        print("  ❌", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
