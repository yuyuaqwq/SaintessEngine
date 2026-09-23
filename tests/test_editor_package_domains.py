#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：**包自带的域声明**（`<pkg>/editor/domains.json`）。

为什么需要它：引擎/编辑器过去只认框架里硬编码的那 19 个域 —— 玩家写包想加自己的域
（天赋树 / 坐骑 / 钓鱼点…）只能来改框架。本门禁钉住五件事：

  1. 包能**新增自己的域**：能被枚举、能读能写、落点按 `kind` 正确（data / rules）
  2. 包能**同名覆盖**内置域（改 label/icon…）：覆盖生效 + 有可读 warning
  3. **坏声明不炸**：坏 JSON / 缺 kind / kind 非法 / 顶层形状不对 / 域 id 非法
     → 可读 warning + 回退内置（不抛、不静默）
  4. **现有包零回归**：`games/orlandia` 的 24 域里属于内置那份的逐字段相等（数量按声明口径比 / 0 告警）
  5. **反证「真源在包」**（★ 2026-09-13 B2b）：框架内置集只剩 8 个**引擎域**
     （每个都能在 `saintess_engine/` 指到消费端）；**内容域**只由包声明 ——
     把包里那份声明拿掉，那些域就**真的没有了**（不是换个来源，是没有）。

并且**真起 HTTP 端到端**：新域在「域注册表 / 包概览 / 条目列表 / 单条读写 / 只校验 /
  schema / 各类域级视图」每条路上都要通 —— 漏一处就会出现「列表里有它、点开 500」。

★ B2b 口径：内置默认集 19 → 8（引擎域：effect_rules / passive_proc / commands / texts /
  tlogs / maps / drop_pools / instances）；被移出的 11 个内容域改由包声明，框架侧零字面量。
  本文件里凡是 `FX.all_domains()` 的地方都按**动态数量**比（不写死 19/8）—— 下次再增减也不假红。

跑法：python tests/test_editor_package_domains.py
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
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from editor import packages as PK          # noqa: E402
from editor import server as SRV           # noqa: E402
from editor import validate as VD          # noqa: E402
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


# 包内自带的 schema（新域自己带校验规则）——`<pkg>/schemas/talent_trees.schema.json`
TALENT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "talent_trees",
    "$defs": {"talent_tree": {
        "type": "object", "required": ["name", "nodes"],
        "properties": {"name": {"type": "string", "minLength": 1},
                       "nodes": {"type": "array", "minItems": 1,
                                 "items": {"type": "object", "required": ["id"],
                                           "properties": {"id": {"type": "string"}}}}},
        "additionalProperties": True}},
}

GOOD_TALENT = {"name": "火焰天赋", "nodes": [{"id": "n1"}]}
BAD_TALENT = {"nodes": []}


def make_pkg(root, pid, decl, *, domains=None, schemas=None):
    """建一个最小包；`decl` 为 str 时按原始字节写（喂坏 JSON 用）。"""
    pkg = os.path.join(root, pid)
    for sub in ("content/data", "content/rules"):
        os.makedirs(os.path.join(pkg, *sub.split("/")), exist_ok=True)
    PK.save_manifest(pkg, {"id": pid, "name": pid, "desc": "域声明门禁",
                           "engine": ">=0.1",
                           "domains": domains if domains is not None else list(PK.DOMAINS),
                           "entry": "content/apply.py", "created": "2026-09-13 00:00:00"})
    if decl is not None:
        os.makedirs(os.path.join(pkg, "editor"), exist_ok=True)
        with open(PK.domains_decl_path(pkg), "w", encoding="utf-8", newline="\n") as f:
            f.write(decl if isinstance(decl, str)
                    else json.dumps(decl, ensure_ascii=False, indent=2) + "\n")
    for name, doc in (schemas or {}).items():
        os.makedirs(os.path.join(pkg, "schemas"), exist_ok=True)
        with open(os.path.join(pkg, "schemas", name), "w", encoding="utf-8", newline="\n") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
    return pkg


def main():
    gd = tempfile.mkdtemp(prefix="fw_pkg_domains_")
    SRV.GAMES_DIR = gd
    print(f"== 包自带域声明门禁（临时包目录 {gd}）==")

    # ── 造包：① 新域（data + rules + 自带 schema）② 同名覆盖 ③ 坏声明各种花样
    new_doms = {"talent_trees": {"label": "天赋树", "kind": "data", "icon": "🌳",
                                 "schema": "schemas/talent_trees.schema.json",
                                 "primary": "talent_tree"},
                "lake_spots": {"label": "钓鱼点", "kind": "rules", "icon": "🎣"}}
    pkg_new = make_pkg(gd, "pkg_new", new_doms,
                       domains=list(PK.DOMAINS) + ["talent_trees", "lake_spots"],
                       schemas={"talent_trees.schema.json": TALENT_SCHEMA})
    # 同名覆盖：**内置（引擎）域**只写要改的字段即可 —— 没写的字段继承内置那份。
    # （内容域不在内置集里，包要自己写全 kind/schema/…；那是「新域」那条路，见 pkg_new。）
    pkg_over = make_pkg(gd, "pkg_over", {"commands": {"label": "指令表", "icon": "🌳"}})
    pkg_bad = make_pkg(gd, "pkg_bad", "{oops")                       # 坏 JSON
    pkg_nokind = make_pkg(gd, "pkg_nokind", {"talent_trees": {"label": "缺 kind"}})
    pkg_badkind = make_pkg(gd, "pkg_badkind", {"talent_trees": {"kind": "weird"}})
    pkg_badshape = make_pkg(gd, "pkg_badshape", ["nope"])            # 顶层是数组
    pkg_badid = make_pkg(gd, "pkg_badid", {"../escape": {"kind": "data"}})
    pkg_plain = make_pkg(gd, "pkg_plain", None)                      # 没有声明文件
    # orlandia 的副本（HTTP 侧按 id 访问；真仓那份下面用库级断言，不写盘）
    shutil.copytree(REAL_ORLANDIA, os.path.join(gd, "orlandia"))

    # ── 1. 新域：合并 + 落点
    print("\n【1. 包新增自己的域：合并 / 落点 / 读写】")
    decl = PK.package_domains(pkg_new)
    check("package_domains() 读出包内两个新域", set(decl) == {"talent_trees", "lake_spots"},
          sorted(decl))
    eff, warns_new = PK.effective_domains(pkg_new)
    check(f"有效域表 = 内置 {len(PK.DOMAINS)}（引擎域）+ 包自带 2",
          len(eff) == len(PK.DOMAINS) + 2, len(eff))
    check(f"内置 {len(PK.DOMAINS)} 域逐字段没被动过",
          all(eff[d] == PK.DOMAINS[d] for d in PK.DOMAINS))
    check("无同名覆盖 → 0 告警", warns_new == [], warns_new)
    check("新域落 content/data（kind=data）",
          os.path.normpath(PK.domain_path(pkg_new, "talent_trees"))
          == os.path.normpath(os.path.join(pkg_new, "content", "data", "talent_trees.json")),
          PK.domain_path(pkg_new, "talent_trees"))
    check("新域落 content/rules（kind=rules）",
          os.path.normpath(PK.domain_path(pkg_new, "lake_spots"))
          == os.path.normpath(os.path.join(pkg_new, "content", "rules", "lake_spots.json")),
          PK.domain_path(pkg_new, "lake_spots"))
    check("内置域落点零变化（commands → content/data）",
          os.path.normpath(PK.domain_path(pkg_new, "commands"))
          == os.path.normpath(os.path.join(pkg_new, "content", "data", "commands.json")))
    check("effect_rules（rules）落点零变化",
          os.path.normpath(PK.domain_path(pkg_new, "effect_rules"))
          == os.path.normpath(os.path.join(pkg_new, "content", "rules", "effect_rules.json")))
    check("未知域仍然 KeyError（旧行为）", _raises_keyerror(pkg_new))
    check("没有声明文件的包：有效域表 == 内置、0 告警（零变化）",
          PK.effective_domains(pkg_plain) == (dict(PK.DOMAINS), []))

    PK.put_entry(pkg_new, "talent_trees", "tt_1", GOOD_TALENT)
    check("能写新域（内容真的是 JSON 文件）",
          os.path.isfile(os.path.join(pkg_new, "content", "data", "talent_trees.json")))
    check("能读回新域条目", PK.get_entry(pkg_new, "talent_trees", "tt_1") == GOOD_TALENT)
    check("新域能列条目", PK.list_entries(pkg_new, "talent_trees")["count"] == 1)
    check("新域域状态 ok（包自带 schema 通过）",
          PK.domain_status(pkg_new, "talent_trees")["ok"] is True)
    PK.put_entry(pkg_new, "talent_trees", "tt_bad", BAD_TALENT)
    st_bad = PK.domain_status(pkg_new, "talent_trees")
    check("新域坏条目被包自带 schema 抓住（不是静默放过）",
          st_bad["ok"] is False and any(x["key"] == "tt_bad" for x in st_bad["invalid"]), st_bad)
    PK.delete_entry(pkg_new, "talent_trees", "tt_bad")
    check("包自带 schema 被认到（VD.load_schema(dom, pkg) 非空）",
          bool(VD.load_schema("talent_trees", pkg_new)))
    check("不给包目录时它仍是「框架不认识的域」（不校验）",
          VD.load_schema("talent_trees") is None)
    check("schema 路径逃逸被拦（../ → 当作不校验 + 告警）",
          _unsafe_schema_ok(gd))

    # 包 schemas/ 与框架 schemas/ 同名文件时：**包内优先**（给「schema 搬进包」留出路）
    pkg_sk = make_pkg(gd, "pkg_sk", {"commands": {"schema": "command.schema.json"}},
                      schemas={"command.schema.json": {"$defs": {"command": {
                          "type": "object", "required": ["name"],
                          "properties": {"name": {"type": "string"}}}}}})
    sp = PK.schema_path(pkg_sk, "commands")
    check("包 schemas/ 同名文件优先于框架 schemas/（包显式声明说了算）",
          os.path.normpath(sp or "") == os.path.normpath(
              os.path.join(pkg_sk, "schemas", "command.schema.json")), sp)
    check("校验确实走包内那份（框架那份不再生效）",
          VD.validate_entry("commands", {"name": "x"}, pkg_sk) == []
          and VD.validate_entry("commands", {"kind": "魔法"}, pkg_sk) != [],
          VD.validate_entry("commands", {"kind": "魔法"}, pkg_sk))
    check("同一个域在别的包（无包内 schema）仍走框架那份",
          VD.validate_entry("commands", {"kind": "魔法"}, pkg_plain) != [])

    # ── 2. 同名覆盖（包声明优先 + warning）
    print("\n【2. 同名覆盖：包声明优先，且必进 warnings】")
    eff_o, warns_o = PK.effective_domains(pkg_over)
    check("覆盖生效（commands.label = 指令表）", eff_o["commands"]["label"] == "指令表",
          eff_o["commands"])
    check("只改 label/icon，其余字段继承内置（schema/primary/kind 没被弄丢）",
          eff_o["commands"]["kind"] == PK.DOMAINS["commands"]["kind"]
          and eff_o["commands"]["schema"] == PK.DOMAINS["commands"]["schema"]
          and eff_o["commands"]["primary"] == PK.DOMAINS["commands"]["primary"],
          eff_o["commands"])
    check("覆盖产生 warning（含域名 + 「覆盖」 + 改了哪个字段）",
          len(warns_o) == 1 and "commands" in warns_o[0] and "覆盖" in warns_o[0]
          and "label" in warns_o[0], warns_o)
    check("内置 DOMAINS 那份**没被改**（框架自己的表还在）",
          FX.all_domains()["commands"]["label"] == "指令")
    check("覆盖后 schema 仍可取（继承来的）",
          bool(VD.load_schema("commands", pkg_over)))
    check("覆盖不影响别的包（pkg_plain 看到的还是内置 label）",
          PK.effective_domains(pkg_plain)[0]["commands"]["label"] == "指令")

    # ── 3. 坏声明不炸
    print("\n【3. 坏声明：不炸、可读 warning、回退内置】")
    e_bad, w_bad = PK.effective_domains(pkg_bad)
    check("坏 JSON → 回退内置（域表与内置逐字段相等）", e_bad == PK.DOMAINS)
    check("坏 JSON → warning 可读（点名文件 + 说已回退）",
          len(w_bad) == 1 and "domains.json" in w_bad[0] and "回退" in w_bad[0], w_bad)
    check("坏 JSON → package_domains() 返回 {}",
          PK.package_domains(pkg_bad) == {})
    check("坏 JSON → 域路径仍可用（编辑器不 500）",
          PK.domain_path(pkg_bad, "commands").endswith(
              os.path.join("content", "data", "commands.json")))
    e_nk, w_nk = PK.effective_domains(pkg_nokind)
    check("新域缺 kind → 不进表 + warning 点名缺 kind",
          "talent_trees" not in e_nk and any("kind" in w for w in w_nk), w_nk)
    e_bk, w_bk = PK.effective_domains(pkg_badkind)
    check("kind 非法 → 不进表 + warning 说清合法取值",
          "talent_trees" not in e_bk and any("kind" in w and "data / rules" in w for w in w_bk),
          w_bk)
    e_sh, w_sh = PK.effective_domains(pkg_badshape)
    check("顶层形状不对（数组）→ 回退内置 + warning",
          e_sh == PK.DOMAINS and any("形状" in w for w in w_sh), w_sh)
    e_id, w_id = PK.effective_domains(pkg_badid)
    check("域 id 非法（../ 逃逸）→ 不进表 + warning（不写包外）",
          e_id == PK.DOMAINS and any("不合规" in w for w in w_id), w_id)

    # ── 4. 现有包零回归（库级：直接读真仓那份）
    print("\n【4. 现有包零回归：games/orlandia 的等值搬迁】")
    e_o, w_o = PK.effective_domains(REAL_ORLANDIA)
    # 数量按**声明口径**比，别写死 19：orlandia 继续往包里加自己的域时，这条要守的是
    # 「等值搬迁 + 不去不看」，不是某个历史数字。
    # ★ 2026-09-13 B2b：内置默认集只剩 **8 个引擎域**；其余 16 个（11 个内容域 +
    #   D3 面板 4 个 races/sets/enhance_table/panel_rules + 收口批 npcs）真源**只在包侧**
    #   （框架里塞某个具体游戏的域 = 不该有）。口径 = 内置那份 ∪ 包声明的：24 个。
    PKG_ONLY_DOMAINS = set(e_o) - set(PK.DOMAINS)
    # 域数**不写死**（2026-09-13 起包侧域会持续增长：B3–B7 一轮 +26 域）。这条守的是
    # 「有效域表 == 内置那份 ∪ 包声明那份」这个集合关系，不是某个历史数字。
    check(f"orlandia 有效域表 = 内置 {len(PK.DOMAINS)}（引擎域）+ 包声明 {len(PKG_ONLY_DOMAINS)}"
          f" = {len(e_o)}",
          len(e_o) == len(PK.DOMAINS) + len(PKG_ONLY_DOMAINS)
          and set(e_o) == set(PK.DOMAINS) | PKG_ONLY_DOMAINS,
          len(e_o))
    # ★ 2026-09-14 B15a：包可以**额外**声明可选归属标注 `owner`/`tier`（框架只透传 + 校验取值，
    #   不赋默认）→ 本判据只比**必填五字段**（「内容不变的搬迁」= 这五个不变），
    #   并**追加**一条「可选标注取值合法」的检查（判据只加强，不削弱）。
    _OVER = ("label", "kind", "schema", "primary", "icon")
    _pkg_over = {k: {f: v.get(f) for f in _OVER} for k, v in e_o.items() if k in PK.DOMAINS}
    _built_over = {k: {f: v.get(f) for f in _OVER} for k, v in PK.DOMAINS.items()}
    check(f"orlandia 里属于内置那份的 {len(PK.DOMAINS)} 域**必填五字段**逐字段等于内置（内容不变的搬迁）",
          _pkg_over == _built_over,
          {k: (PK.DOMAINS.get(k), e_o.get(k)) for k in set(PK.DOMAINS) | set(e_o)
           if k in FX.all_domains() and _pkg_over.get(k) != _built_over.get(k)})
    _bad_opt = {k: {f: v.get(f) for f in ("owner", "tier") if f in v}
                for k, v in e_o.items() if k in PK.DOMAINS
                and (v.get("owner") not in (None, "package", "engine")
                     or v.get("tier") not in (None, "portable", "fixed"))}
    check("包内那 8 域的可选标注 owner/tier 取值合法（声明了才查）", not _bad_opt, _bad_opt)
    check(f"{len(PKG_ONLY_DOMAINS)} 个包声明域**只**在包侧声明（内置默认集里没有 —— 真源归包）",
          PKG_ONLY_DOMAINS <= set(e_o) and not (PKG_ONLY_DOMAINS & set(PK.DOMAINS)),
          sorted(PKG_ONLY_DOMAINS & set(PK.DOMAINS)))
    _with_schema = {d for d in PKG_ONLY_DOMAINS if e_o[d].get("schema")}
    check(f"包声明域里带 schema 的 {len(_with_schema)} 个都在包内各有 schema 文件（schema 随包走）",
          all(os.path.isfile(os.path.join(REAL_ORLANDIA, "schemas", e_o[d]["schema"]))
              for d in _with_schema), sorted(_with_schema))
    check("orlandia 等值声明不算「覆盖」→ 0 告警（别拿噪声埋掉零回归）", w_o == [], w_o)
    check("orlandia 包内确有这份声明文件", os.path.isfile(PK.domains_decl_path(REAL_ORLANDIA)))
    # D3 步 2 起：orlandia **自带** schema（17 份搬进 `games/orlandia/schemas/`，本批有演进），
    # 解析结果因此是「包内那份」——框架 `schemas/` 只留回退。包侧与框架回退的**基线对照**
    # 门禁在 `tests/test_editor_package_schemas.py`（框架 17 份 sha 冻结 + 只许加不许丢字段）。
    check("orlandia 有包内 schema → 解析到包内那份（不是框架那份）",
          os.path.normpath(PK.schema_path(REAL_ORLANDIA, "skills"))
          == os.path.normpath(os.path.join(REAL_ORLANDIA, "schemas", "skill.schema.json")),
          PK.schema_path(REAL_ORLANDIA, "skills"))
    # ★ B2b：skills 是**内容域** —— 「框架那份」得靠一个「只声明域、不带 schemas/」的包才解析得到
    #   （真源在包）。对照的是框架 `schemas/skill.schema.json` 回退副本。
    _fw_pkg = os.path.join(gd, "fw_fallback")
    FX.declare(_fw_pkg, "skills")
    _clear_caches()
    check("包内那份 vs 框架回退那份：同一坏条目的校验结论一致（零回归口径）",
          VD.validate_entry("skills", {"kind": "魔法"}, REAL_ORLANDIA)
          == VD.validate_entry("skills", {"kind": "魔法"}, _fw_pkg) != [],
          VD.validate_entry("skills", {"kind": "魔法"}, REAL_ORLANDIA))

    # ── 4b. ★ 反证「内容域的真源只在包」（B2b）：框架侧零字面量 + 拿掉声明就真没有
    print("\n【4b. 反证：内置集 == 8 引擎域；内容域只在包里（拿掉声明就真没有）】")
    # ★ 2026-09-23 第 4 批：只剩通用件自己的三张表（其余随消费端搬进扩展包）
    ENGINE_DOMAINS = {"commands", "texts", "tlogs"}
    check(f"内置集逐名 == 3 个引擎域（防悄悄塞回内容域 / 游戏级形状）",
          set(PK.DOMAINS) == ENGINE_DOMAINS, sorted(set(PK.DOMAINS) ^ ENGINE_DOMAINS))
    # 每个引擎域都要能**指到引擎侧消费端代码**（源码里真实存在的符号）——
    # 判定表见 packages.py 的逐条注释；这里做的是「证据仍在那」的机器复核。
    _ENGINE_EVIDENCE = {
        # 只有**通用件自己**的表留在引擎默认集里；每个都要能指到引擎侧消费端代码。
        # （effect_rules / passive_proc / maps / drop_pools / instances 的证据现在在扩展包里 ——
        #  消费端搬哪儿，域跟到哪儿，2026-09-23 第 4 批）
        "commands": ("saintess_engine/command/registry.py", "class CommandRegistry"),
        "texts": ("saintess_engine/text/template.py", "class TextTable"),
        "tlogs": ("saintess_engine/tlog/record.py", "class KindTable"),
    }
    _miss = [(d, f, sym) for d, (f, sym) in _ENGINE_EVIDENCE.items()
             if sym not in open(os.path.join(ROOT, f), encoding="utf-8").read()]
    check(f"{len(_ENGINE_EVIDENCE)} 个内置域逐个都指得到引擎侧消费端代码（证据仍在）",
          not _miss, _miss)
    check("engine 侧消费端表与内置集一一对应（不多不少）",
          set(_ENGINE_EVIDENCE) == set(PK.DOMAINS), sorted(set(_ENGINE_EVIDENCE) ^ set(PK.DOMAINS)))
    _content = {"skills", "classes", "monsters", "affixes", "items", "loot_vocab",
                "equip_roster", "pois", "legendary_effects", "pets", "monster_roster"}
    check("11 个内容域一个都不在内置集里（框架侧零字面量）",
          not (_content & set(PK.DOMAINS)), sorted(_content & set(PK.DOMAINS)))
    # 反证：在**副本**上把包内声明拿掉 → 内容域真的没有了（不是回退、不是换个来源）
    _copy = os.path.join(gd, "orlandia_nodecl")
    shutil.copytree(REAL_ORLANDIA, _copy,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    _decl_path, _decl_text = PK.domains_decl_path(_copy), ""
    with open(_decl_path, encoding="utf-8") as f:
        _decl_text = f.read()
    os.remove(_decl_path)
    _clear_caches()
    try:
        e_nd, w_nd = PK.effective_domains(_copy)
        # ★ 2026-09-23 第 4 批：orlandia 的 game.json 里 depends 了扩展包 ⇒ 即使拿掉它自己的声明，
        #   那 5 个「跟消费端走」的域仍由**扩展包**带来（这正是分层要的效果）。
        _expect_nd = set(PK.DOMAINS) | set(FX.EXT_DOMAINS)
        check(f"拿掉包内 domains.json → 有效域表 == 引擎默认集 {len(PK.DOMAINS)} + 扩展包域 {len(FX.EXT_DOMAINS)}",
              set(e_nd) == _expect_nd,
              f"{len(e_nd)} {sorted(set(e_nd) ^ _expect_nd)}")
        check("内容域在拿掉声明后**真的没有了**（不是换了个来源）",
              not (_content & set(e_nd)) and not (_content & set(PK.DOMAINS)))
        check("拿掉声明后 items / skills 谁都不认识（domain_path → KeyError，不 500）",
              _dom_keyerror(_copy, "items") and _dom_keyerror(_copy, "skills"))
        check("拿掉声明 → 0 告警（缺文件不是错误，是「本包没声明」）", w_nd == [], w_nd)
    finally:
        with open(_decl_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(_decl_text)
        _clear_caches()
    check(f"声明写回后 orlandia 仍是 {len(e_o)} 域（反证可逆，不污染真仓）",
          len(PK.effective_domains(REAL_ORLANDIA)[0]) == len(e_o))

    # ── 5. HTTP 端到端
    print("\n【5. HTTP 端到端：新域每条路都通（不能有 500）】")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), SRV.H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        st, j = req(base, "GET", "/api/domains")
        ids0 = [d["id"] for d in (j.get("domains") or [])]
        check(f"不带包 → /api/domains == 内置 {len(PK.DOMAINS)} 个引擎域（口径随内置集收窄）",
              st == 200 and ids0 == list(PK.DOMAINS), f"{st} {len(ids0)}")

        st, j = req(base, "GET", "/api/domains?pkg=pkg_new")
        doms = {d["id"]: d for d in (j.get("domains") or [])}
        check("带包 → 域注册表含包自带的新域（from_package=True）",
              st == 200 and "talent_trees" in doms and doms["talent_trees"]["from_package"] is True,
              f"{st} {sorted(doms)}")
        check("新域带 label/icon/kind/primary（tab 画得出来）",
              doms.get("talent_trees", {}).get("label") == "天赋树"
              and doms["talent_trees"].get("icon") == "🌳"
              and doms["talent_trees"].get("kind") == "data"
              and doms["talent_trees"].get("primary") == "talent_tree")
        check("新域 has_schema=True（包内 schema 被认到）",
              doms["talent_trees"].get("has_schema") is True)
        # ★ 2026-09-23 第 4 批：拿真正的**引擎默认域**举例（drop_pools 已随消费端搬进 ext_loot，
        #   它现在是扩展包带来的域，不再是「内置回退」）。
        check("域注册表里内置（引擎）域仍在，且标 from_package=False（是回退/内置，不是包声明）",
              doms["texts"]["label"] == "文案"
              and doms["texts"]["from_package"] is False
              and doms["texts"]["has_schema"] is True)

        st, j = req(base, "GET", "/api/domains?pkg=pkg_over")
        doms2 = {d["id"]: d for d in (j.get("domains") or [])}
        check("同名覆盖走 HTTP 也生效（commands.label = 指令表）",
              st == 200 and doms2["commands"]["label"] == "指令表", f"{st} {doms2.get('commands')}")
        check("同名覆盖的 warning 送到前端（不再静默）",
              any("覆盖" in w for w in (j.get("warnings") or [])), j.get("warnings"))

        st, j = req(base, "GET", "/api/domains?pkg=orlandia")
        o_ids = [d["id"] for d in (j.get("domains") or [])]
        check("orlandia 走 HTTP 域表 == 有效域表（内置 ∪ 包声明；集合口径，顺序以包声明为准）",
              st == 200 and set(o_ids) == set(e_o), f"{st} {len(o_ids)} vs {len(e_o)}")
        check("orlandia 的等值声明在 HTTP 侧也不产告警", (j.get("warnings") or []) == [],
              j.get("warnings"))

        st, j = req(base, "GET", "/api/package/pkg_new")
        od = {d["id"]: d for d in (j.get("domains") or [])}
        check("包概览含新域（count/ok 齐全）",
              st == 200 and j.get("ok") and "talent_trees" in od
              and od["talent_trees"].get("ok") is True and od["talent_trees"].get("label") == "天赋树",
              f"{st} {sorted(od)[-3:]}")
        check("包概览把「包自带域」单列出来（package_domains）",
              set(j.get("package_domains") or []) == {"talent_trees", "lake_spots"},
              j.get("package_domains"))

        # 条目列表 / 分页
        st, j = req(base, "GET", "/api/package/pkg_new/d/talent_trees?limit=1")
        check("新域条目列表可达（200，不是 404/500）",
              st == 200 and j.get("count") == 1 and len(j.get("entries") or []) == 1, f"{st} {j}")
        check("新域列表的 status 也给（tab 徽标）", (j.get("status") or {}).get("ok") is True)

        # 单条读（含包内 schema）
        st, j = req(base, "GET", "/api/package/pkg_new/d/talent_trees/tt_1")
        check("新域单条读回 + 带 schema（表单能渲染）",
              st == 200 and (j.get("data") or {}).get("name") == "火焰天赋"
              and bool((j.get("schema") or {}).get("$defs")), f"{st}")

        # 写：合法 / 非法
        st, j = req(base, "PUT", "/api/package/pkg_new/d/talent_trees/tt_2", {"data": GOOD_TALENT})
        check("新域 PUT 合法条目 → 200", st == 200 and j.get("ok"), f"{st} {j.get('message')}")
        st, j = req(base, "PUT", "/api/package/pkg_new/d/talent_trees/tt_bad", {"data": BAD_TALENT})
        check("新域 PUT 非法条目 → 422（包自带 schema 真的在拦）",
              st == 422 and not j.get("ok")
              and bool((j.get("validation") or {}).get("errors")), f"{st}")
        st, j = req(base, "GET", "/api/package/pkg_new/d/talent_trees/tt_bad")
        check("被拦的条目没落盘", st == 404, f"{st}")

        # 只校验不写盘 + schema 端点
        st, j = req(base, "POST", "/api/package/pkg_new/d/talent_trees/tt_9/check",
                    {"data": BAD_TALENT})
        check("新域 check 接口可达且拦住坏草稿",
              st == 200 and not j.get("ok") and bool(j.get("errors")), f"{st} {j}")
        st, j = req(base, "GET", "/api/schema/talent_trees?pkg=pkg_new")
        check("GET /api/schema/<新域>?pkg= 给出包内 schema",
              st == 200 and j.get("ok") and bool((j.get("schema") or {}).get("$defs")), f"{st}")
        st, j = req(base, "GET", "/api/schema/talent_trees")
        check("不带包时框架仍不认识它（旧行为）", st == 200 and not j.get("ok"), f"{st}")

        # 域级视图：不该 500（它们各自有 404/422 的正当语义）
        for tail, why in (("tt_1/graph", "拓扑视图"),
                          ("tt_1/preview", "池预览"),
                          ("tt_1/run", "进度视图")):
            st, j = req(base, "GET", f"/api/package/pkg_new/d/talent_trees/{tail}")
            check(f"新域的{why}路由不 500（走的是有效域表）", st != 500, f"{st} {j.get('message')}")

        # 全包校验覆盖新域
        st, j = req(base, "POST", "/api/package/pkg_new/validate")
        check("全包校验（含新域）可达且 ok", st == 200 and j.get("ok") is True, f"{st} {j}")

        # hints（联想）覆盖新域
        st, j = req(base, "GET", "/api/package/pkg_new/hints")
        check("hints 覆盖新域（新域也有联想，不是空白）",
              st == 200 and "talent_trees" in (j.get("refs") or {}), f"{st}")

        # 坏声明的包：HTTP 不许炸
        st, j = req(base, "GET", "/api/package/pkg_bad")
        check("坏声明的包 → 概览 200（降级不 500）", st == 200 and j.get("ok"), f"{st}")
        check(f"坏声明的包 → 域数仍是内置 {len(PK.DOMAINS)}",
              len(j.get("domains") or []) == len(PK.DOMAINS),
              len(j.get("domains") or []))
        check("坏声明的包 → 警告送到前端",
              bool(j.get("domain_warnings")), j.get("domain_warnings"))
        st, j = req(base, "GET", "/api/domains?pkg=pkg_bad")
        check("坏声明的包 → 域注册表 200 且回退内置",
              st == 200 and [d["id"] for d in (j.get("domains") or [])] == list(PK.DOMAINS),
              f"{st}")

        # 真包（副本）走一遍重路径：条目列表 + 概览
        st, j = req(base, "GET", "/api/package/orlandia/d/pets")
        check("orlandia 普通域列表仍 200（零回归）", st == 200 and j.get("count", 0) > 0,
              f"{st} {j.get('count')}")
        st, j = req(base, "GET", "/api/package/orlandia")
        od2 = {d["id"]: d for d in (j.get("domains") or [])}
        check("orlandia 包概览域表齐全且逐域有 status",
              st == 200 and len(od2) == len(PK.effective_domains(REAL_ORLANDIA)[0])
              and all("ok" in v for v in od2.values()),
              f"{st} {len(od2)}")

        # 删除
        st, j = req(base, "DELETE", "/api/package/pkg_new/d/talent_trees/tt_2")
        check("新域条目能删", st == 200 and j.get("ok"), f"{st}")
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(gd, ignore_errors=True)

    print(f"\n===== 结果：通过 {PASS} / {PASS + FAIL} =====")
    for f in FAILURES:
        print("  ❌", f)
    return 1 if FAIL else 0


def _raises_keyerror(pkg):
    try:
        PK.domain_path(pkg, "no_such_domain_zz")
    except KeyError:
        return True
    except Exception:                                    # noqa: BLE001
        return False
    return False


def _dom_keyerror(pkg, dom):
    """该包视角下这个域不认识 → `domain_path()` 抛 KeyError（编辑器侧另有 404 兜底）。"""
    try:
        PK.domain_path(pkg, dom)
    except KeyError:
        return True
    except Exception:                                    # noqa: BLE001
        return False
    return False


def _clear_caches():
    """域声明 / schema 解析的各级缓存（反证里增删声明文件后必须清）。"""
    try:
        PK._DOMAINS_CACHE.clear()
    except Exception:                                    # noqa: BLE001
        pass
    try:
        VD._cache.clear()
    except Exception:                                    # noqa: BLE001
        pass


def _unsafe_schema_ok(gd):
    """声明 `schema: "../evil.schema.json"` → warning + 当作不校验（不读包外文件）。"""
    pkg = make_pkg(gd, "pkg_evil_schema",
                   {"talent_trees": {"kind": "data", "schema": "../evil.schema.json"}})
    eff, warns = PK.effective_domains(pkg)
    ok_warn = any("schema" in w and "相对路径" in w for w in warns)
    return ok_warn and PK.schema_path(pkg, "talent_trees") is None \
        and "talent_trees" in eff


if __name__ == "__main__":
    sys.exit(main())
