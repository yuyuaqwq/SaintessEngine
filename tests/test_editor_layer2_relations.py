#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：编辑器扩展**第 2 层** —— 包侧声明面 `editor/relations.json` + `editor/views.json`。

设计稿：`overnight/editor-extension-design.md` §二「第 2 层：半动态」。
一句话：把过去**写死在框架侧**的三样东西改成 **两层 = 包声明 > 框架默认**：

  1. **字段↔域引用**（`glossary.REF_DOMAINS` 那份降级为默认值）→ 包声明即「下拉 + 引用校验」
  2. **表单联动/只读**（框架原本没有 → 默认集为空）→ 纯声明，服务端照实回传
  3. **域专属视图分派**（`server.py` 里 `dom != "drop_pools"` / `dom != "instances"` 写死）
     → `BUILTIN_DEFAULT_VIEWS` 默认值 + `editor/views.json` 声明，**分派到内置视图**

本门禁钉住四件事（与任务书 (a)(b)(c)(d) 一一对应）：

  (a) 包声明的引用 → 接口回传**可选值**（下拉候选）+ **校验报错**（保存/草稿被拦）
  (b) 包声明的 views → 路由**命中内置视图**（通用 /view 路由 + 既有 preview/run 路由）
  (c) **坏声明不炸**：坏 JSON / 未知 view 名 / 未知域 / 形状不对 → 可读告警 + 降级默认，**不 500**
  (d) **现有包零回归**：包不声明时，每一面的行为**逐项等于改造前**（含 HTTP）

跑法：python tests/test_editor_layer2_relations.py
退出码：0 = 全过；1 = 有失败。
"""
from __future__ import annotations

import json
import os
import shutil
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

from editor import glossary as GL          # noqa: E402
from editor import hints as HN             # noqa: E402
from editor import packages as PK          # noqa: E402
from editor import relations as REL        # noqa: E402
from editor import server as SRV           # noqa: E402
import _domain_fixtures as FX              # noqa: E402  （内容域只能由包声明：B2b）

REAL_ORLANDIA = os.path.join(ROOT, "games", "orlandia")

PASS = 0
FAIL = 0
FAILURES = []


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "PASS", "FAIL", "FAILURES")


def req(base, method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method,
                               headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(r, timeout=180) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw}


# ───────────────────────── 测试用包 ─────────────────────────
QUEST_SCHEMA = {"$schema": "https://json-schema.org/draft/2020-12/schema",
                "title": "my_quests",
                "$defs": {"my_quest": {
                    "type": "object", "required": ["name"],
                    "properties": {"name": {"type": "string", "minLength": 1},
                                   "reward_pool": {"type": "string"},
                                   "giver": {"type": "string"}},
                    "additionalProperties": True}}}

NEW_DOMS = {"my_pools": {"label": "自定池", "kind": "rules", "icon": "🎁"},
            "my_quests": {"label": "任务", "kind": "data", "icon": "📜",
                          "schema": "schemas/my_quests.schema.json", "primary": "my_quest"},
            "my_dungeons": {"label": "副本", "kind": "data", "icon": "🏯"}}

DECLARED_REL = {
    "$version": 1,
    "my_quests": {
        "reward_pool": {"ref": {"domain": "my_pools"}},
        "giver": {"ref": {"domain": "equip_roster", "by": "name"}},
        "locked": {"when": {"done": True}, "readonly": ["desc"]},
    },
    "*": {"when": {"frozen": True}, "readonly": ["name"]},
}
DECLARED_VIEWS = {"my_pools": {"view": "loot_view"},
                  "my_quests": {"view": "table"},
                  "my_dungeons": {"view": "instance_view"}}

POOL_A = {"type": "weighted", "entries": [{"item": "mat_a", "w": 3}, {"item": "mat_b", "w": 1}]}
QUEST_OK = {"name": "讨伐", "reward_pool": "pool_a", "giver": "炎龙剑"}
DUNGEON = {"name": "试炼场", "stages": [{"name": "一层", "monsters": ["m1"]}]}


def make_pkg(root, pid, *, decl=None, relations=None, views=None, data=None,
             schemas=None, domains=None):
    """建一个最小包；`decl`/`relations`/`views` 为 str 时按原始字节写（喂坏 JSON 用）。"""
    pkg = os.path.join(root, pid)
    for sub in ("content/data", "content/rules"):
        os.makedirs(os.path.join(pkg, *sub.split("/")), exist_ok=True)
    # ★ B2b：内容域（skills / items / monsters / equip_roster）只能由包声明 ——
    #   本门禁的域名（skills/items/monsters/equip_roster）正是内容域，给每个包都声明上。
    content_decl = FX.declare(None, "skills", "items", "monsters", "equip_roster")
    if isinstance(decl, str):
        decl_out = decl                                  # 原始字节（坏 JSON 用例）
    else:
        decl_out = {**content_decl, **(decl or {})}
    PK.save_manifest(pkg, {"id": pid, "name": pid, "desc": "第 2 层门禁", "engine": ">=0.1",
                           "domains": domains if domains is not None else
                           list(PK.DOMAINS) + list(NEW_DOMS) + list(content_decl),
                           "entry": "content/apply.py", "created": "2026-09-13 00:00:00"})
    for sub, obj in (("editor/domains.json", decl_out), ("editor/relations.json", relations),
                     ("editor/views.json", views)):
        if obj is None:
            continue
        p = os.path.join(pkg, *sub.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(obj if isinstance(obj, str)
                    else json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    for name, doc in (schemas or {}).items():
        os.makedirs(os.path.join(pkg, "schemas"), exist_ok=True)
        with open(os.path.join(pkg, "schemas", name), "w", encoding="utf-8", newline="\n") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
    for dom, doc in (data or {}).items():
        kind = (NEW_DOMS.get(dom) or PK.DOMAINS.get(dom) or content_decl.get(dom)
                or {}).get("kind") or "data"
        sub = "rules" if kind == "rules" else "data"
        PK.write_json(os.path.join(pkg, "content", sub, f"{dom}.json"), doc)
    return pkg


def main() -> int:
    gd = tempfile.mkdtemp(prefix="fw_l2_rel_")
    SRV.GAMES_DIR = gd
    print(f"== 第 2 层（包声明面）门禁（临时包目录 {gd}）==")

    pkg = make_pkg(gd, "l2_pkg", decl=NEW_DOMS, relations=DECLARED_REL, views=DECLARED_VIEWS,
                   schemas={"my_quests.schema.json": QUEST_SCHEMA},
                   data={"my_pools": {"pool_a": POOL_A},
                         "my_quests": {"q1": QUEST_OK},
                         "my_dungeons": {"d1": DUNGEON},
                         "equip_roster": {"eq_dragon": {"name": "炎龙剑"}}})
    plain = make_pkg(gd, "l2_plain", data={"drop_pools": {"p1": POOL_A},
                                           "instances": {"i1": DUNGEON},
                                           "maps": {"m1": {"nodes": [{"id": "n1"}]}}})
    bad_json = make_pkg(gd, "l2_badrel", relations="{oops",
                        views={"skills": {"view": "nope_view"}, "zzz_no_domain": {"view": "table"}})
    bad_view_json = make_pkg(gd, "l2_badview", views="{oops")
    bad_shape = make_pkg(gd, "l2_badshape", relations=["nope"],
                         views={"skills": {"view": 123}})
    bad_rule = make_pkg(gd, "l2_badrule", relations={
        "zzz_no_domain": {"f": {"ref": {"domain": "my_pools"}}},      # 未知域 → 整段忽略
        "skills": {
            "kind": {"ref": "不是对象"},                                # ref 坏
            "element": {"ref": {"domain": "zzz_nope"}},                 # 目标域不认识 → 引用忽略
            "mech": {"ref": {"domain": "items", "by": "weird"}},        # by 非法 → 按 key
            "desc": {"when": "不是对象"},                                # when 坏 → 忽略条件
            "icon": {"show": "不是数组"},                                # show 坏 → 忽略
        }})

    # ═══════════ (a) 包声明的引用 → 下拉候选 + 校验报错 ═══════════
    print("\n【(a) 包声明的引用：候选 + 校验】")
    rel = REL.package_relations(pkg)
    check("读得出包声明（$version 被剥掉，域/字段在）",
          "$version" not in rel and set(rel) == {"my_quests", "*"}, sorted(rel))
    check("ref 规范化：by 缺省 = key",
          rel["my_quests"]["reward_pool"]["ref"] == {"domain": "my_pools", "by": "key"},
          rel["my_quests"].get("reward_pool"))
    check("ref 规范化：by=name 保留",
          rel["my_quests"]["giver"]["ref"] == {"domain": "equip_roster", "by": "name"})
    check("联动规范化：when/show/readonly",
          rel["my_quests"]["locked"]["when"] == {"done": True}
          and rel["my_quests"]["locked"]["readonly"] == ["desc"])
    check("全局 '*' 联动（对所有域生效）",
          rel["*"]["*"]["when"] == {"frozen": True}
          and rel["*"]["*"]["readonly"] == ["name"])
    check("声明的包 → 0 告警", REL.relation_warnings(pkg) == [], REL.relation_warnings(pkg))

    check("declared_ref 只认包声明（by=key）",
          REL.declared_ref(pkg, "my_quests", "reward_pool") == {"domain": "my_pools", "by": "key"})
    check("declared_ref 支持叶名回退（嵌套路径也命中）",
          REL.declared_ref(pkg, "my_quests", "x.reward_pool") == {"domain": "my_pools", "by": "key"})
    check("框架默认的字段不是 declared_ref（它只给候选、不校验）",
          REL.declared_ref(pkg, "monsters", "skills") is None)
    check("联动按域合并（全局 + 域内同现）",
          set(REL.linkage_for(pkg, "my_quests")) == {"*", "locked"}
          and REL.linkage_for(pkg, "skills") != {})

    check("候选（by=key）= 目标域真 key", REL.ref_candidates(pkg, "my_pools") == ["pool_a"],
          REL.ref_candidates(pkg, "my_pools"))
    check("候选（by=name）= 目标域条目的 name",
          REL.ref_candidates(pkg, "equip_roster", "name") == ["炎龙剑"],
          REL.ref_candidates(pkg, "equip_roster", "name"))
    check("目标域不存在 → 候选空表（不抛）", REL.ref_candidates(pkg, "zzz_nope") == [])
    check("引用校验：合法值通过",
          REL.ref_errors(pkg, "my_quests", QUEST_OK) == [])
    e_bad = REL.ref_errors(pkg, "my_quests", {"name": "x", "reward_pool": "nope_pool"})
    check("引用校验：by=key 填错 → 报错（点名字段 + 目标域 + 坏值）",
          len(e_bad) == 1 and "reward_pool" in e_bad[0] and "my_pools" in e_bad[0]
          and "nope_pool" in e_bad[0], e_bad)
    e_name = REL.ref_errors(pkg, "my_quests", {"name": "x", "giver": "假名字"})
    check("引用校验：by=name 比的是名字（不是 key）",
          len(e_name) == 1 and "giver" in e_name[0] and "equip_roster" in e_name[0], e_name)
    check("引用校验：字段没填 → 不报错（无值可查）",
          REL.ref_errors(pkg, "my_quests", {"name": "x"}) == [])
    check("引用校验：目标域是空表 → 不判红（宁放过不假红）",
          _empty_target_ok(gd))

    # ═══════════ (b) 包声明的 views → 路由命中内置视图 ═══════════
    print("\n【(b) 包声明的视图：分派到内置视图】")
    v_pkg, v_src, v_w = REL.resolve_view(pkg, "my_pools")
    check("声明的域 → 视图来自包（source=package）",
          (v_pkg, v_src, v_w) == ("loot_view", "package", []), (v_pkg, v_src, v_w))
    check("未声明的内置域 → 视图来自框架默认（source=builtin）",
          REL.resolve_view(pkg, "drop_pools") == ("loot_view", "builtin", [])
          and REL.resolve_view(pkg, "instances") == ("instance_view", "builtin", [])
          and REL.resolve_view(pkg, "maps") == ("space_view", "builtin", []))
    check("没有专属视图的域 → (None, None, [])",
          REL.resolve_view(pkg, "skills") == (None, None, []))
    check("graph 是 space_view 的别名",
          REL.resolved_name("graph") == "space_view")
    check("包 views → 0 告警", REL.view_warnings(pkg) == [], REL.view_warnings(pkg))

    # ═══════════ (c) 坏声明不炸 ═══════════
    print("\n【(c) 坏声明：降级 + 可读告警，绝不 500】")
    check("坏 JSON（relations）→ 空声明 + warning 点名文件与回退",
          REL.package_relations(bad_json) == {}
          and len(REL.relation_warnings(bad_json)) == 1
          and "relations.json" in REL.relation_warnings(bad_json)[0]
          and "回退" in REL.relation_warnings(bad_json)[0], REL.relation_warnings(bad_json))
    check("坏 JSON → 引用校验恒空（不因声明坏就乱判）",
          REL.ref_errors(bad_json, "skills", {"kind": "x"}) == [])
    w_vw = REL.view_warnings(bad_json)
    check("未知 view 名 → warning（说清合法取值）",
          any("view" in w and "nope_view" in w and "loot_view" in w for w in w_vw), w_vw)
    check("声明里未知域 → warning + 该条忽略",
          any("zzz_no_domain" in w for w in w_vw) and REL.package_views(bad_json) == {}, w_vw)
    check("未知 view 名 → 降级框架默认（skills 无默认 → None；别域不受影响）",
          REL.resolve_view(bad_json, "skills")[0] is None
          and REL.resolve_view(bad_json, "drop_pools") == ("loot_view", "builtin", []))
    check("顶层形状不对（数组）→ 整份忽略 + warning",
          REL.package_relations(bad_shape) == {}
          and any("形状" in w for w in REL.relation_warnings(bad_shape)),
          REL.relation_warnings(bad_shape))
    check("views 顶层形状对但 view 不是字符串 → warning + 降级",
          REL.package_views(bad_shape) == {}
          and any("123" in w for w in REL.view_warnings(bad_shape)),
          REL.view_warnings(bad_shape))
    check("views 坏 JSON → 空声明 + warning，默认分派照旧",
          REL.package_views(bad_view_json) == {}
          and REL.view_warnings(bad_view_json)
          and REL.resolve_view(bad_view_json, "instances") == ("instance_view", "builtin", []))
    wr = REL.relation_warnings(bad_rule)
    check("字段规则坏形态逐条降级：未知域 / ref 坏 / 目标域不认识 / by 非法 / when 坏 / show 坏",
          all(any(k in w for w in wr) for k in
              ("zzz_no_domain", "ref", "zzz_nope", "by", "when", "show")), wr)
    br = REL.package_relations(bad_rule)
    check("坏形态只丢坏的部分：by 非法 → 按 key 收下（不是整条丢）",
          br["skills"]["mech"]["ref"] == {"domain": "items", "by": "key"},
          br.get("skills", {}).get("mech"))
    check("只有坏 ref 的规则整条丢掉（不存在「半条声明」）",
          "element" not in br["skills"] and "kind" not in br["skills"]
          and sorted(br["skills"]) == ["mech"], sorted(br.get("skills") or {}))
    check("坏掉的联动不冒充存在（skills 无联动）", REL.linkage_for(bad_rule, "skills") == {})
    check("任何坏声明都不抛（all_warnings 可读、永不为 None）",
          isinstance(REL.all_warnings(bad_rule), list) and isinstance(REL.all_warnings(bad_json), list))

    # ═══════════ (d) 现有包零回归 ═══════════
    print("\n【(d) 零回归：不声明时逐项等于改造前】")
    check("不声明 → 三份表全空、0 告警",
          REL.package_relations(plain) == {} and REL.package_views(plain) == {}
          and REL.all_warnings(plain) == [] and REL.ref_errors(plain, "skills", {}) == [])
    check("视图分派零变化（maps→space_view / drop_pools→loot_view / instances→instance_view）",
          REL.resolve_view(plain, "maps") == ("space_view", "builtin", [])
          and REL.resolve_view(plain, "drop_pools") == ("loot_view", "builtin", [])
          and REL.resolve_view(plain, "instances") == ("instance_view", "builtin", []))
    check("框架默认的引用（glossary.REF_DOMAINS）照旧出候选：monsters.skills → skills",
          GL.suggest_meta("monsters", "skills", plain)["ref"] == "skills"
          and GL.suggest_meta("monsters", "skills", plain)["ref_source"] == "builtin")
    check("框架默认的引用**不**进校验（既有包不会被新校验判红）",
          REL.ref_errors(plain, "monsters", {"skills": ["绝不存在的技能zzz"]}) == [])
    # ★ B2b：控件表按**有效域表**铺 —— plain 声明了内容域，所以它比「不带包」多出那些键；
    #   零回归要守的是**框架默认层**逐域相等（多出来的键是包声明带出来的，不算回归）。
    _fw_all, _pk_all = GL.all_widgets(), GL.all_widgets(plain)
    check("glossary 控件表：框架默认层逐项相等（包新域多出的键不算回归）",
          all(_pk_all.get(d) == _fw_all.get(d) for d in _fw_all))
    check("suggest_meta 不给包 = 旧行为（ref 仍是框架默认那份）",
          GL.suggest_meta("monsters", "skills")["ref"] == "skills"
          and GL.suggest_meta("monsters", "skills")["ref"] is not None)
    check("hints 三类口径不变（refs/values/keys 结构原样；ref_names 是新增的第 4 类）",
          set(HN.build(plain)) == {"refs", "values", "keys", "ref_names"}
          and set(HN.flatten_for_ui(HN.build(plain))) == {"fields", "refs", "ref_names"}
          and HN.build(plain)["refs"]["drop_pools"] == ["p1"]
          and HN.build(plain)["ref_names"]["instances"] == ["试炼场"])
    check("PK.package_overview 零回归（不声明 → 无声明面告警）",
          PK.package_overview(plain)["domain_warnings"] == [],
          PK.package_overview(plain)["domain_warnings"])
    def _empty_decl(_p):
        """声明文件「无有效声明」= 不存在 / 空 / 只有 `{}`/`null`。

        ★ 2026-09-15（B16 拆仓后）：原实现按 `os.path.isfile()` 判「未声明」，
        而包仓里可能留着一个 **0 字节**的 `editor/relations.json`（编辑器写过空声明/散落文件），
        语义上它等于「没声明」（解析结果 `{}`，下一条断言正是这么判的）—— 按文件存在性判会让这条
        零回归门槛被一个空文件绊红（引擎门禁 53/54 的那条红就是这么来的）。改成按**内容**判，
        有真声明（哪怕只有一条）照样红。
        """
        if not os.path.isfile(_p):
            return True
        try:
            with open(_p, "r", encoding="utf-8") as _fh:
                return _fh.read().strip() in ("", "{}", "null")
        except Exception:                                  # noqa: BLE001
            return False

    check("旗舰包 games/orlandia 当前未声明第 2 层面（可选面；声明了才是行为变更）",
          _empty_decl(REL.relations_decl_path(REAL_ORLANDIA))
          and _empty_decl(REL.views_decl_path(REAL_ORLANDIA)))
    check("orlandia 的引用/联动/视图声明为空 + 视图分派走默认",
          REL.package_relations(REAL_ORLANDIA) == {} and REL.package_views(REAL_ORLANDIA) == {}
          and REL.resolve_view(REAL_ORLANDIA, "drop_pools") == ("loot_view", "builtin", []))
    # ★ 2026-09-13 收口：orlandia 现已**声明包侧词汇表**（`<pkg>/editor/glossary/<域>.json`，
    #   第 3 层能力：字段中文名/分组/控件随包走）—— 那些字段的 widget/ref **本来就该**与框架默认
    #   不同。所以本条的守点收窄成「**框架默认层**逐项未被改动」：包词汇表声明过的字段豁免，
    #   其余字段仍必须逐项等于改造前；另加一条**非空豁免**反证 —— 包词汇表得真的生效，
    #   否则上面那条豁免就是空的（门禁变装饰）。
    _pk_decl = GL.package_glossary(REAL_ORLANDIA)
    _exempt = {d: set((_pk_decl.get(d) or {}).get("fields") or {}) for d in GL.DOMAIN_SCHEMA}
    _w_pkg, _w_def = GL.all_widgets(REAL_ORLANDIA), GL.all_widgets()
    _drift = {d: {k: (_w_def[d].get(k), _w_pkg.get(d, {}).get(k)) for k in _w_def[d]
                  if k not in _exempt.get(d, set())
                  and _w_pkg.get(d, {}).get(k) != _w_def[d].get(k)}
              for d in GL.DOMAIN_SCHEMA}
    check("orlandia 控件表：框架默认层逐项等于改造前（包词汇表声明过的字段除外）",
          all(not v for v in _drift.values()), {d: v for d, v in _drift.items() if v})
    check("orlandia 包侧词汇表真的生效（至少 1 个字段的控件来自包，反证上面的豁免非空）",
          any(_w_pkg.get(d, {}).get(k) != _w_def.get(d, {}).get(k)
              for d in GL.DOMAIN_SCHEMA for k in _w_pkg.get(d, {})),
          "包词汇表没生效 → 上一条豁免是空的")

    # ═══════════ HTTP 端到端 ═══════════
    print("\n【HTTP：(a)(b)(c)(d) 每条路都通（不能有 500）】")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), SRV.H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        # (a) 声明面端点 + 候选 + 校验
        st, j = req(base, "GET", "/api/package/l2_pkg/relations")
        check("GET /relations → 200 且回声明 + 候选（by=key 给真 key）",
              st == 200 and j.get("ok")
              and j["candidates"]["my_quests.reward_pool"]["candidates"] == ["pool_a"],
              f"{st} {j.get('candidates')}")
        check("/relations 候选：by=name 给名字",
              (j["candidates"]["my_quests.giver"] or {}).get("by") == "name"
              and (j["candidates"]["my_quests.giver"] or {}).get("candidates") == ["炎龙剑"],
              j.get("candidates"))
        check("/relations 联动（域内 + 全局）都回传",
              j["linkage"]["my_quests"]["locked"]["readonly"] == ["desc"]
              and j["linkage"]["skills"]["*"]["when"] == {"frozen": True},
              j.get("linkage"))
        check("/relations 声明没问题 → warnings 空", j.get("warnings") == [], j.get("warnings"))

        st, j = req(base, "GET", "/api/glossary?pkg=l2_pkg")
        wq = ((j.get("widgets") or {}).get("my_quests") or {})
        check("GET /glossary?pkg= → 包声明的引用进控件表（ref_source=package）",
              st == 200 and wq.get("reward_pool", {}).get("ref") == "my_pools"
              and wq["reward_pool"].get("ref_source") == "package", f"{st} {wq.get('reward_pool')}")
        check("/glossary?pkg= → by=name 一起回（前端按名字给候选）",
              wq.get("giver", {}).get("ref_by") == "name", wq.get("giver"))
        check("/glossary?pkg= → 框架默认仍在（monsters.skills，ref_source=builtin）",
              ((j.get("widgets") or {}).get("monsters") or {}).get("skills", {}).get("ref") == "skills")
        check("/glossary?pkg= → 包自带新域也有控件表",
              "my_quests" in (j.get("widgets") or {}))

        st, j = req(base, "GET", "/api/package/l2_pkg/hints")
        check("GET /hints → 目标域真 key 做候选（my_pools/pool_a）",
              st == 200 and "pool_a" in ((j.get("refs") or {}).get("my_pools") or []),
              f"{st} {(j.get('refs') or {}).get('my_pools')}")
        check("/hints → ref_names 给名字候选（by=name 用）",
              "炎龙剑" in ((j.get("ref_names") or {}).get("equip_roster") or []),
              (j.get("ref_names") or {}).get("equip_roster"))

        st, j = req(base, "PUT", "/api/package/l2_pkg/d/my_quests/q1", {"data": QUEST_OK})
        check("PUT 引用合法 → 200 落盘", st == 200 and j.get("ok"), f"{st} {j.get('message')}")
        st, j = req(base, "PUT", "/api/package/l2_pkg/d/my_quests/q2",
                    {"data": {"name": "坏引用", "reward_pool": "nope_pool"}})
        errs = ((j.get("validation") or {}).get("errors") or [])
        check("PUT 引用填错 → 422 且报错点名（引用校验真的在拦）",
              st == 422 and any("引用" in e and "nope_pool" in e for e in errs), f"{st} {errs}")
        st, j = req(base, "GET", "/api/package/l2_pkg/d/my_quests/q2")
        check("被拦的条目没落盘", st == 404, f"{st}")
        st, j = req(base, "POST", "/api/package/l2_pkg/d/my_quests/q9/check",
                    {"data": {"name": "草稿", "giver": "假名字"}})
        check("POST check 只校验不写盘 → 拦住 by=name 的坏引用",
              st == 200 and not j.get("ok") and any("引用" in e for e in (j.get("errors") or [])),
              f"{st} {j.get('errors')}")

        PK.put_entry(pkg, "my_quests", "q_bad", {"name": "表里就有坏引用", "reward_pool": "xxx"})
        st, j = req(base, "GET", "/api/package/l2_pkg")
        od = {d["id"]: d for d in (j.get("domains") or [])}
        invalid_keys = [x["key"] for x in (od.get("my_quests", {}).get("invalid") or [])]
        check("域徽标/概览把引用错算进去（my_quests 不 ok 且点名坏条）",
              st == 200 and od.get("my_quests", {}).get("ok") is False and "q_bad" in invalid_keys,
              f"{st} {invalid_keys}")
        st, j = req(base, "POST", "/api/package/l2_pkg/validate")
        check("全包校验也把引用错算进去", st == 200 and j.get("ok") is False, f"{st}")

        # (b) 视图分派
        st, j = req(base, "GET", "/api/package/l2_pkg/views")
        check("GET /views → 200；声明的域 source=package + route 对得上",
              st == 200 and j.get("ok")
              and j["effective"]["my_pools"] == {"view": "loot_view", "source": "package",
                                                 "route": "preview"}
              and j["effective"]["my_dungeons"]["route"] == "run",
              f"{st} {(j.get('effective') or {}).get('my_pools')}")
        check("/views → 默认分派也在（maps/drop_pools/instances，source=builtin）",
              j["effective"]["maps"]["source"] == "builtin"
              and j["effective"]["instances"]["view"] == "instance_view"
              and (j.get("builtin") or {}).get("drop_pools") == "loot_view")
        check("/views → warnings 空（声明没问题）", j.get("warnings") == [])

        st, j = req(base, "GET", "/api/package/l2_pkg/d/my_pools/pool_a/view")
        check("通用 /view → 命中内置 loot_view（声明的域）",
              st == 200 and j.get("view_name") == "loot_view" and j.get("view_source") == "package"
              and "entries" in j and "rolls" in j, f"{st} {list(j)[:8]}")
        st, j = req(base, "GET", "/api/package/l2_pkg/d/my_pools/pool_a/preview")
        check("既有 /preview 路由改为按**视图分派**放行（声明 loot_view 的域不再 404）",
              st == 200 and j.get("ok"), f"{st}")
        st, j = req(base, "GET", "/api/package/l2_pkg/d/my_dungeons/d1/run")
        check("既有 /run 路由按视图分派放行（声明 instance_view 的域不再 404）",
              st == 200 and j.get("ok") and j.get("stages"), f"{st} {j.get('error')}")
        st, j = req(base, "GET", "/api/package/l2_pkg/d/my_quests/q1/view")
        check("通用 /view → 命中内置 table（整条摊成行列）",
              st == 200 and j.get("view_name") == "table" and j.get("scope") == "entry"
              and any(r.get("字段") == "name" for r in (j.get("rows") or [])),
              f"{st} {j.get('view_name')}")
        st, j = req(base, "GET", "/api/package/l2_pkg/d/my_quests/q1/view?view=space_view")
        check("?view= 临时指定内置视图（graph 别名解析成 space_view）",
              st in (200, 422) and j.get("view_name") == "space_view", f"{st} {j.get('view_name')}")
        st, j = req(base, "GET", "/api/package/l2_pkg/d/my_quests/q1/view?view=nope")
        check("?view= 未知视图 → 400（列内置名字，不 500）", st == 400, f"{st}")

        # (c) 坏声明：HTTP 不许炸
        for pid in ("l2_badrel", "l2_badview", "l2_badshape", "l2_badrule"):
            st1, j1 = req(base, "GET", f"/api/package/{pid}")
            st2, j2 = req(base, "GET", f"/api/package/{pid}/relations")
            st3, j3 = req(base, "GET", f"/api/package/{pid}/views")
            ok_warn = bool(j1.get("domain_warnings")) and (bool(j2.get("warnings"))
                                                           or bool(j3.get("warnings")))
            check(f"{pid}：概览/声明面 200 + 告警送到前端（不 500）",
                  st1 == 200 and j1.get("ok") and st2 == 200 and st3 == 200 and ok_warn,
                  f"{st1}/{st2}/{st3} warn={j1.get('domain_warnings')}")
            st4, j4 = req(base, "GET", f"/api/package/{pid}/d/skills")
            check(f"{pid}：普通域列表仍 200（声明坏不拖累编辑）", st4 == 200, f"{st4}")
        st, j = req(base, "POST", "/api/package/l2_badrule/d/skills/sk_ok/check",
                    {"data": {"name": "x", "kind": "物理"}})
        check("坏声明包：草稿校验仍可用（不会因为声明坏就全拦）", st == 200, f"{st}")

        # (d) 零回归：HTTP 面逐项等于改造前
        st, j = req(base, "GET", "/api/glossary?pkg=l2_plain")
        st0, j0 = req(base, "GET", "/api/glossary")
        _wp, _wf = (j.get("widgets") or {}), (j0.get("widgets") or {})
        check("包不声明词汇/引用 → 控件表**框架默认层**逐项等于不带包那份（零回归）",
              st == 200 and st0 == 200 and bool(_wf)
              and all(_wp.get(d) == _wf.get(d) for d in _wf),
              f"{st}/{st0}")
        check("不给声明的包 → /glossary?pkg= 无声明面告警", (j.get("warnings") or []) == [])
        st, j = req(base, "GET", "/api/package/l2_plain/relations")
        check("不声明 → /relations 空且 0 告警",
              st == 200 and j.get("relations") == {} and j.get("candidates") == {}
              and j.get("linkage") == {} and j.get("warnings") == [], f"{st} {j}")
        st, j = req(base, "GET", "/api/package/l2_plain/views")
        check("不声明 → /views 空 + 有效分派只剩三条框架默认",
              st == 200 and j.get("views") == {}
              and set(j.get("effective") or {}) == {"maps", "drop_pools", "instances"}
              and all(v["source"] == "builtin" for v in (j.get("effective") or {}).values()),
              f"{st} {j.get('effective')}")
        # 门槛逐项：有默认视图的域照旧放行，没有的域照旧 404（真实判断走响应码）
        for dom, key, route, why in (("drop_pools", "p1", "preview", "drop_pools 默认 loot_view"),
                                     ("instances", "i1", "run", "instances 默认 instance_view"),
                                     ("maps", "m1", "graph", "maps 默认 space_view")):
            st, j = req(base, "GET", f"/api/package/l2_plain/d/{dom}/{key}/{route}")
            check(f"零回归门槛：{dom}/{route} 不 404（{why}）", st != 404, f"{st}")
        for dom, route, why in (("skills", "preview", "skills 没有池预览"),
                                ("skills", "run", "skills 没有进度视图"),
                                ("skills", "view", "skills 没有声明视图")):
            st, j = req(base, "GET", f"/api/package/l2_plain/d/{dom}/k1/{route}")
            check(f"零回归门槛：{dom}/{route} → 404（与改造前一致：{why}）", st == 404, f"{st}")
        st, j = req(base, "GET", "/api/package/l2_plain/d/skills/sk1/view?view=table")
        check("?view= 在未声明的域也能临时用（内置 table 语义中立）",
              st in (200, 404, 422) and st != 500, f"{st}")
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(gd, ignore_errors=True)

    print(f"\n===== 结果：通过 {PASS} / {PASS + FAIL} =====")
    for f in FAILURES:
        print("  ❌", f)
    return 1 if FAIL else 0


def _empty_target_ok(gd) -> bool:
    """目标域的表是空的（候选拿不到）→ 不判红（否则一填就被拦，比漏报更糟）。"""
    pkg = make_pkg(gd, "l2_emptytarget", decl=NEW_DOMS,
                   relations={"my_quests": {"reward_pool": {"ref": {"domain": "my_pools"}}}},
                   schemas={"my_quests.schema.json": QUEST_SCHEMA},
                   data={"my_quests": {"q": QUEST_OK}})       # my_pools 表不存在 → 空
    return REL.ref_errors(pkg, "my_quests", QUEST_OK) == []


if __name__ == "__main__":
    sys.exit(main())
