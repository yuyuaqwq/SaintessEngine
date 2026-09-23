# -*- coding: utf-8 -*-
"""测试脚手架：给**合成包**声明「内容域」（真源在包 —— 框架不再内置内容域）。

背景（2026-09-13 B2b）
----------------------
`editor/packages.py` 的内置默认集**只留 8 个引擎域**（effect_rules / passive_proc /
commands / texts / tlogs / maps / drop_pools / instances —— 每个都能在 `saintess_engine/`
里指到消费端）。**内容域**（skills / classes / monsters / affixes / items / loot_vocab /
equip_roster / pois / legendary_effects / pets / monster_roster）不再内置：它们只能由
内容包自己的 `editor/domains.json` 声明（真包样例：`games/orlandia/editor/domains.json`，24 域）。

本模块把那 11 个内容域的元数据（label / kind / schema / primary / icon —— 就是 B2b 之前
内置默认集里那几条，`schema` 指向框架 `schemas/<file>` 的**回退副本**）收在一处，供框架侧
测试**给合成包写一份声明**，模拟「内容包自己声明内容域」。这样既有测试的行为（落点 /
schema 解析 / 校验）逐项不变，又不把内容域塞回框架。

用法
----
    sys.path.insert(0, HERE)                      # 测试都在 tests/ 下，HERE 已进 path
    import _domain_fixtures as FX
    FX.declare(pkg_dir, "skills", "items")        # 写 <pkg>/editor/domains.json
    FX.fw_schema("items")                         # 框架 schemas/item.schema.json（回退副本）

⚠ 这是**测试脚手架**：不许被 `editor/` 或 `saintess_engine/` 引用。
"""
from __future__ import annotations

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
_REAL_ORLANDIA = os.path.join(FW_ROOT, "games", "orlandia")

# 11 个「内容域」的元数据（B2b 从内置默认集移出的那批；原样保留，测试零行为变化）
CONTENT_DOMAINS = {
    "skills": {"label": "技能", "kind": "data", "schema": "skill.schema.json",
               "primary": "skill", "icon": "⚔️"},
    "classes": {"label": "职业", "kind": "data", "schema": None, "primary": None,
                "icon": "🧙"},
    "monsters": {"label": "怪物", "kind": "data", "schema": "monster.schema.json",
                 "primary": "monster_skill", "icon": "🐺"},
    "affixes": {"label": "词条", "kind": "data", "schema": "affix.schema.json",
                "primary": "affix", "icon": "💠"},
    "items": {"label": "物品", "kind": "data", "schema": "item.schema.json",
              "primary": "item", "icon": "🎒"},
    "loot_vocab": {"label": "引用词汇", "kind": "rules", "schema": None,
                   "primary": None, "icon": "🔤"},
    "equip_roster": {"label": "装备名册", "kind": "data", "schema": "equip_roster.schema.json",
                     "primary": "equip", "icon": "🛡"},
    "pois": {"label": "交互点", "kind": "data", "schema": "pois.schema.json",
             "primary": "poi_mount", "icon": "📍"},
    "legendary_effects": {"label": "传说特效", "kind": "data",
                          "schema": "legendary_effects.schema.json",
                          "primary": "legendary_effect", "icon": "✨"},
    "pets": {"label": "宠物", "kind": "data", "schema": "pets.schema.json",
             "primary": "pet", "icon": "🐾"},
    "monster_roster": {"label": "怪物名册", "kind": "data",
                       "schema": "monster_roster.schema.json",
                       "primary": "monster", "icon": "🐺"},
}


def orlandia_decl() -> dict:
    """真内容包 `games/orlandia/editor/domains.json` 的原始声明（含 `races` 等包新增域）。"""
    with open(os.path.join(_REAL_ORLANDIA, "editor", "domains.json"), encoding="utf-8") as f:
        return json.load(f)


# 5 个「随消费端搬进扩展包」的域（2026-09-23 第 4 批：域跟消费端走）
# effect_rules / passive_proc → ext_combat   maps / instances → ext_world   drop_pools → ext_loot
# 引擎默认集已不含它们；合成包要它们时同样**由包自己声明**（schema 仍走框架 schemas/ 的回退副本）。
EXT_DOMAINS = {
    "effect_rules": {"label": "声明表", "kind": "rules", "schema": "effect_rules.schema.json",
                     "primary": "effect_rule", "icon": "📜"},
    "passive_proc": {"label": "被动声明", "kind": "rules", "schema": "passive_proc.schema.json",
                     "primary": "passive_proc", "icon": "🌀"},
    "maps": {"label": "地图", "kind": "data", "schema": "maps.schema.json",
             "primary": "map", "icon": "🗺"},
    "instances": {"label": "副本", "kind": "data", "schema": "instances.schema.json",
                  "primary": "instance", "icon": "🏯"},
    "drop_pools": {"label": "掉落池", "kind": "data", "schema": "drop_pools.schema.json",
                   "primary": "pool", "icon": "🎁"},
}


def meta_of(dom: str) -> dict:
    """域元数据：内容域 → **扩展包域** → 真包声明 → 内置引擎域。未知域 → KeyError。"""
    if dom in CONTENT_DOMAINS:
        return dict(CONTENT_DOMAINS[dom])
    if dom in EXT_DOMAINS:
        return dict(EXT_DOMAINS[dom])
    decl = orlandia_decl()
    if dom in decl:
        return dict(decl[dom])
    from editor import packages as PK
    if dom in PK.DOMAINS:
        return dict(PK.DOMAINS[dom])
    raise KeyError(f"未知域：{dom}（不在内容域表 / 扩展包域表 / 真包声明 / 内置引擎域里）")


def all_domains() -> dict:
    """**框架侧域表全貌**：引擎默认集（通用件 3 个）+ 扩展包域（5 个）+ 内容域（11 个）。

    测试造包与断言用它 —— `PK.DOMAINS` 是**引擎默认集**（第 4 批后只剩命令/文案/流水 3 个），
    真实有效域表看 `PK.effective_domains(pkg)`（引擎默认集 → 扩展包 → 数据包）。
    """
    from editor import packages as PK
    return {**PK.builtin_default_domains(), **EXT_DOMAINS, **CONTENT_DOMAINS}


def declare(pkg_dir: str, *doms, extra: dict | None = None) -> dict:
    """把请求的域写进 `<pkg>/editor/domains.json`（= 内容包自己声明域这件事）。

    返回写入的声明表（{域: meta}）。`extra` 可加/覆盖（喂坏声明用）。
    """
    decl = {d: meta_of(d) for d in doms}
    if extra:
        decl.update(extra)
    if pkg_dir:
        from editor import packages as PK
        p = PK.domains_decl_path(pkg_dir)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            json.dump(decl, f, ensure_ascii=False, indent=2)
            f.write("\n")
    return decl


def merge_decl(*metas: dict) -> dict:
    """合并若干声明表（后者覆盖前者）—— 给「已有一份 decl + 再补内容域」的场合。"""
    out: dict = {}
    for m in metas:
        out.update(m)
    return out


def fw_schema(dom: str) -> dict | None:
    """该域在**框架 schemas/** 里的那份（回退副本）；没有 → None。"""
    meta = meta_of(dom)
    fn = meta.get("schema")
    if not fn:
        return None
    p = os.path.join(FW_ROOT, "schemas", fn)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)
