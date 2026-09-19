# -*- coding: utf-8 -*-
"""引擎默认域集 + **唯一一份**「包声明 ∪ 引擎默认集」合并规则。

为什么它在引擎层
----------------
引擎自己的装载口（`records.read_domain_decl` / `resolve_domain` / `set_from_domains`）
必须与编辑器看到**同一份**有效域表。否则「域的声明搬到引擎（上移成引擎内置）」之后，
编辑器还能编，装载口却读不到（2026-09-20 T1 双向迁移演习实测：搬迁后 `records_from_domain`
报 `RecordsDeclarationError`）。合并规则因此只有这一份 ——
`editor/packages.py::effective_domains()` 只**委托**它，装载口用**同一份**结果兜底。
设计 + 干跑证据：`overnight/T1_DUAL_MIGRATION_DRILL.md` §六。

零游戏词汇
----------
下面 8 个域都是**引擎侧真有消费端代码**的形状（每个域在 `saintess_engine/` 里都能指到
消费它的模块，逐条见下）；某个具体游戏的内容域（技能 / 职业 / 怪物 / 词条 / 物品 …）
**一个都不在这里** —— 那只能由内容包自己声明。

字段（与包声明同形）
--------------------
    label    展示名（编辑器用）
    kind     `"data"`（内容数据表）| `"rules"`（声明表）；落点子目录由调用方映射
    schema   schema 文件名（**不是**路径；由调用方的 `schema_path()` 解析）
    primary  schema `$defs` 里「一条数据」的 def 名
    icon     展示图标
    owner / tier  可选的归属标注（`owner` = 形状/模块归属，`tier` = 可迁移等级）；
                  **只由包侧声明** —— 引擎默认集里不写（保证「包声明 == 生效域表」逐字段可比）

★ 这份常量是**回退默认集，不是真源**：域的真源永远是内容包自己的
  `<pkg>/editor/domains.json`。包声明了同名域 → 这份里的那一域不再参与取值。
"""

BUILTIN_DEFAULT_DOMAINS = {
    # ── ① effect_rules「声明表」：引擎的效果规则表。消费端
    #    `battle/state_effects.py:13-15` state_def(key) → `config.get_effect_rules()`；
    #    装配面 `config.py:26-28`（_LOADED["effect_rules"]）/ `:88-91` load_game_rules /
    #    `:105-107` get_effect_rules。读点遍布引擎：effects.py:67(cap)/:245/:310(period)/
    #    :351(consume)/:458(panel)、stats.py:57(stat_scale)、landing.py:128/173/312-313、
    #    schedule.py:235-243(period)、actions.py:89-97(cd_mult)。不填 = 纯数值无规则（零行为）。
    "effect_rules": {"label": "声明表", "kind": "rules", "schema": "effect_rules.schema.json",
                     "primary": "effect_rule", "icon": "📜"},
    # ── ② passive_proc「被动声明」：**引擎事件总线/动作注册面**上的声明形状。消费端不是
    #    「读这张表」（读它的是内容侧装配器），而是引擎的既有面：事件全集
    #    `battle/effect_triggers.py:52` EVENTS（26 个 = 引擎协议）+ `:61` fire(battle,event,ctx,logs)
    #    消费 `actor["triggers"][事件]`；动作经 `battle/effects.py:95` register_action / `:135`
    #    resolve_actions 注册执行（triggers 里的 `action` 直通 handler，见 effects.py:197-201）。
    #    声明里的键/取值全是**引擎协议词**（event ∈ EVENTS、action = 引擎动词、domain=cap/cost
    #    = 引擎概念），没有任何游戏专有名词 —— 所以是引擎域，不是内容域。
    "passive_proc": {"label": "被动声明", "kind": "rules",
                     "schema": "passive_proc.schema.json", "primary": "passive_proc",
                     "icon": "🌀"},
    # ── ③ commands「指令」：引擎通用命令注册表。消费端 `command/registry.py:164`
    #    class CommandRegistry（`:206` from_data 直接吃这张表）；配套泛用件 `command/router.py`
    #    / `command/guards.py` / `command/text.py`。不填 = 无指令（零行为）。
    "commands": {"label": "指令", "kind": "data", "schema": "command.schema.json",
                 "primary": "command", "icon": "⌨️"},
    # ── ④ texts「文案」：引擎通用文案表。消费端 `text/template.py:129` class TextTable
    #    （`:176` from_data）+ `safe_format` / `extract_params`（同文件）。不填 = 零行为。
    "texts": {"label": "文案", "kind": "data", "schema": "text.schema.json",
              "primary": "text_entry", "icon": "💬"},
    # ── ⑤ tlogs「流水声明」：引擎结构化流水。「哪个 kind 有哪些字段」的声明表。
    #    消费端 `tlog/record.py:115` class KindTable（`tlog/core.py:34` 再导出、
    #    `:47`/`:53` 由 TLog(kinds=KindTable) 吃）。不填 = 不做校验（零行为）。
    "tlogs": {"label": "流水声明", "kind": "data", "schema": "tlog.schema.json",
              "primary": "tlog_entry", "icon": "🧾"},
    # ── ⑥ maps「地图」：引擎空间结构件。消费端 `space/graph.py:42` class Space
    #    （节点表 + topology → 邻接/深度/出入口/必经路径，`:45` __init__(nodes, topology…)）；
    #    配套 `space/topology.py`。不给数据 = 不影响任何东西。
    "maps": {"label": "地图", "kind": "data", "schema": "maps.schema.json",
             "primary": "map", "icon": "🗺"},
    # ── ⑦ drop_pools「掉落池」：引擎随机产出结构件。消费端 `loot/pool.py:200` class LootTable
    #    （`loot/__init__.py` 导出；策略注册 `pool.py:47` register_strategy / STRATEGIES）。
    #    引擎零知识：策略名是自由串，引用前缀/具体产出全在内容侧。
    "drop_pools": {"label": "掉落池", "kind": "data", "schema": "drop_pools.schema.json",
                   "primary": "pool", "icon": "🎁"},
    # ── ⑧ instances「副本」：引擎运行结构件。消费端 `run/progress.py:49` class Progress、
    #    `run/roster.py:37` class Roster、`run/admission.py:131` class Admission（`run/__init__.py`
    #    统一导出）。一条 = 一个副本：stages 顺序即进度节点序。
    "instances": {"label": "副本", "kind": "data", "schema": "instances.schema.json",
                  "primary": "instance", "icon": "🏯"},
    # 注：以下 11 个是**内容域**（曾内置，2026-09-13 B2b 移出）—— 引擎侧指不到消费端，
    #     取值/结构都是某个具体游戏的词汇；现在只能由内容包声明（orlandia 在
    #     `games/orlandia/editor/domains.json` 里声明它们，schema 随包走）：
    #     skills · classes · monsters · affixes · items · loot_vocab · equip_roster ·
    #     pois · legendary_effects · pets · monster_roster
}


def builtin_default_domains() -> dict:
    """引擎默认集（回退用）**副本** —— 别改它：要加域/改域请改内容包自己的声明表。"""
    return {k: dict(v) for k, v in BUILTIN_DEFAULT_DOMAINS.items()}


def merge_decls(decls, *, builtin=None, use_builtin: bool = True) -> dict:
    """「包声明 ∪ 引擎默认集」的**唯一一份**合并规则 → 有效域表。

    * `use_builtin=False` ⇒ 只用 `decls`（对应包声明里写的 `"$builtin": false`）。
    * 同名域**整体以 `decls` 为准**（不做字段级补缺 —— 逐字段补缺是编辑器
      `_read_package_domains()` 的活：它要在**读声明时**就能报「哪个字段写坏了」）。
    * 顺序 = 引擎默认集序 + 包新增域（追加在末尾）⇒ 编辑器 tab 位置不跳。
    * `builtin` 是注入点（缺省 = 本模块那份）：编辑器把它传成**自己模块里的那个名字**，
      好让「把内置默认集整体置空」的反证门禁照旧生效。

    只做合并与拷贝，**不校验、不产 warning**（校验口径与告警文案归各自的调用方）。
    """
    base = BUILTIN_DEFAULT_DOMAINS if builtin is None else builtin
    out: dict = {}
    if use_builtin:
        for did, meta in base.items():
            out[did] = dict(meta) if isinstance(meta, dict) else meta
    for did, meta in (decls or {}).items():
        out[did] = dict(meta) if isinstance(meta, dict) else meta
    return out


def decl_switch(raw) -> tuple:
    """拆一份**包域声明** → `(声明表, 用不用引擎默认集)`。

    容忍两种写法（与编辑器 `_read_package_domains()` 同一口径）：

        {"域": {...}, "$builtin": false}
        {"domains": {"域": {...}}, "$builtin": false}      # 包装层同样认

    开关名 `$builtin` / `$builtin_defaults`（顶层与包装层都认；非布尔 ⇒ 按 `True`，
    编辑器侧对非布尔另发一条 warning —— 这里只认口径，不产告警）。
    开关键**从结果里剥掉**（它不是域，不许漏进域表）。
    """
    if not isinstance(raw, dict):
        return {}, True
    raw = dict(raw)                                    # 纯函数：不改入参
    holds = [raw]
    inner = raw.get("domains")
    if isinstance(inner, dict):
        inner = dict(inner)
        raw["domains"] = inner
        holds.append(inner)
    use_builtin = True
    for holder in holds:
        for opt in ("$builtin", "$builtin_defaults"):
            if opt in holder:
                v = holder.pop(opt)
                if isinstance(v, bool):
                    use_builtin = v
    return (inner if inner is not None else raw), use_builtin
