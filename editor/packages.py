# -*- coding: utf-8 -*-
"""游戏包（game package）IO —— 框架编辑器的数据层。

一个「游戏包」= 框架侧对一个游戏的完整描述，纯 JSON + 少量 py 装配代码：

    <pkg>/
      game.json                 包清单（manifest）：id/name/desc/engine 要求/域声明
      content/
        data/<域>.json         数据表（技能 / 职业 / 怪物 / 词条 / 物品）
        rules/<域>.json        声明表（effect_rules / passive_proc / mech_cash）
        apply.py               装配入口（内容 → 引擎方向；挂 hook + 规则表）
        mech/actions.py        机制动作（可选；@register_action 回调）

**为什么 JSON 为源**：编辑器要稳定读写；py dict 回写会毁注释与排版（见 EDITOR_SPEC
的方案 A）。`apply.py` 仍然可以是 py —— 那是「代码」，不是「数据」。

本模块**只做文件 IO 与结构校验**，不 import `saintess_engine`（编辑器主进程零引擎副作用；
真正跑战斗在子进程里，见 simulate.py）。
"""
from __future__ import annotations

import json
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FRAMEWORK_ROOT = os.path.dirname(HERE)
DEFAULT_GAMES_DIR = os.path.join(FRAMEWORK_ROOT, "games")

# ---------------- 域注册表：**引擎域内置默认集（回退用，不是真源）** ----------------
# ⚠️ 域的真源是**包自己的** `<pkg>/editor/domains.json`（读法见下面 `_read_package_domains()` /
#    `package_domains()` / `effective_domains()`）—— 所以「加一个域」是**纯包侧动作**：
#    包里写 3 样东西（域声明 + schema + 数据文件），框架一行不改（最小样板见
#    `examples/minimal-game/`）。这份常量**只做两件事**：
#      · 包**没有**可用声明时兜底（第三方包 / 坏包 / 未迁移的老包）—— 让编辑器不至于空白；
#      · 包声明**同名域**时给「没写的字段」补缺省值（写了的字段一律以包为准）。
#    包声明了同名域 → 这份里的那一域**不再参与取值**（见 `effective_domains()` 里
#    「包声明覆盖内置」分支，且必进 warnings）；把这份整体置空，自带声明的包照旧完整可编
#    —— 反证门禁：`tests/test_editor_step3_pkg_first.py`（monkeypatch 置空 + orlandia 全量读写）。
#
# ★ 2026-09-13 B2b：**19 → 8，只留「引擎域」**。口径一句话：
#   **只有引擎侧真有消费端代码的域才内置**（引擎自带一个通用结构件/规则表读它）；
#   **内容域（某个具体游戏才有的域）一律不内置** —— 它们只能由内容包自己声明
#   （`games/orlandia/editor/domains.json` 声明 24 个；内容域那 16 个框架一侧一个字都没有）。
#   移出的 11 个内容域（skills / classes / monsters / affixes / items / loot_vocab /
#   equip_roster / pois / legendary_effects / pets / monster_roster）过去靠这份兜底才能显示，
#   等于「框架里揣着某个具体游戏的域」；现在它们在包里，框架侧零字面量。
#   为什么「引擎域」是这 8 个：每个域在 `saintess_engine/` 里都能指到消费它的代码（逐条见下）。
#   判定时**只认引擎仓内的消费端**：`editor/*_view.py` 之类编辑器侧的读点不算数
#   （否则 `loot_vocab` 也会被留下 —— 它只被 `editor/loot_view.py:load_vocab()` 读，
#   引擎侧一个字没有，取值全是内容词汇：前缀 / 特殊 ref / 去哪个域查）。
#
# kind: "data"（content/data/）| "rules"（content/rules/）
# schema: 文件名（**不是**「框架里的路径」）—— 按 `schema_path()` 解析：
#         <pkg>/schemas/<file> → <pkg>/<file> → 框架 schemas/<file> → None
#         （包自带优先、框架只留回退；orlandia 的 17 份已搬进 games/orlandia/schemas/）
# primary: schema $defs 里「一条数据」的 def 名
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

# 兼容别名 —— 历史调用点（`editor/server.py`、`editor/glossary.py`、若干测试）仍按 `DOMAINS`
# 引用这份**内置默认集**；新代码请走 `builtin_default_domains()` / `effective_domains()`。
DOMAINS = BUILTIN_DEFAULT_DOMAINS


def builtin_default_domains() -> dict:
    """内置默认集（回退用）**副本** —— 别改它：要加域/改域请改包内 `editor/domains.json`。"""
    return {k: dict(v) for k, v in BUILTIN_DEFAULT_DOMAINS.items()}


# ---------------- 包自带的域声明（<pkg>/editor/domains.json） ----------------
# 这是**域的真源**：玩家写的包能加自己的域（天赋树 / 坐骑 / 钓鱼点…）并自带 schema，
# 框架那份**引擎域**常量（`BUILTIN_DEFAULT_DOMAINS`，2026-09-13 B2b 起 = 8 个）只是
# **没声明时的回退**。声明形状与
# 内置默认集逐字段同：
#
#     {"talent_trees": {"label": "天赋树", "kind": "data",
#                       "schema": "schemas/talent_trees.schema.json",
#                       "primary": "talent_tree", "icon": "🌳"}}
#
# 顶层可选开关（**包的域集就这些**，不要内置默认集兜底）：
#
#     {"$builtin": false, "talent_trees": {…}}      # 只认本包声明的域；缺省 true（兜底）
#     （也可写 `{"domains": {…}, "$builtin": false}` —— 包装写法同样认这个开关；
#       非布尔值 → 一条可读 warning + 按 true 处理；关掉且声明为空 → 域表为空 + warning，
#       但**绝不 500**：包概览/域注册表照常 200）
#
# 纪律（与 `loot_vocab` 同一套：坏声明只降级、不 500）：
#   · 缺文件 = 没声明 = 与内置逐字段一致（**不是错误，不告警**）
#   · 坏 JSON / 坏形状 / 非法 kind / 非法域 id → 该条（或整份）忽略 + 一条**可读 warning**
#     （绝不抛异常，也绝不静默 —— 见 `package_domain_warnings()` / `effective_domains()`）
#   · 同名域：**包声明优先**（包可以微调自己那个域的 label / icon / schema），内置那份
#     不再参与取值，但必进 warnings
#   · 域 id 会被拼进文件名 → 用正则卡住（防 `../` 逃出包目录）
DOMAINS_REL = "editor/domains.json"
DOMAIN_KINDS = ("data", "rules")
_DOMAIN_ID_RE = re.compile(r"^[a-z][a-z0-9_\-]{0,40}$")
#: 域的**必填五字段**（内置默认集与包声明同形比较用）
_OVER_FIELDS = ("label", "kind", "schema", "primary", "icon")
#: 域的**可选归属标注**（2026-09-14 起）：`owner` = 形状/模块归属，`tier` = 可迁移等级。
#: 由内容包在 `editor/domains.json` 里声明（orlandia 72 域全标注）；框架**只透传 + 校验取值**，
#: 不赋默认 —— 没写的域输出里就没有这两个键（保证「包声明 == 生效域表」逐字段可比）。
DOMAIN_OWNERS = ("package", "engine")
DOMAIN_TIERS = ("portable", "fixed")

_DOMAINS_CACHE: dict = {}          # 包目录 -> (声明文件签名, {域: meta}, [warning])
_CACHE_MAX = 500


# ---------------- 包清单 ----------------
def manifest_path(pkg_dir: str) -> str:
    return os.path.join(pkg_dir, "game.json")


def domains_decl_path(pkg_dir: str) -> str:
    """包自带域声明的路径（`<pkg>/editor/domains.json`）。"""
    return os.path.join(pkg_dir, DOMAINS_REL)


def _key(pkg_dir) -> str:
    return os.path.normpath(os.path.abspath(str(pkg_dir))) if pkg_dir else ""


def _decl_sig(pkg_dir: str):
    """声明文件签名（mtime_ns + size）；文件不在 = None（签名相同 → 直接复用缓存）。"""
    try:
        st = os.stat(domains_decl_path(pkg_dir))
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _safe_rel_name(name: str) -> bool:
    """相对路径判据（拒绝绝对路径 / 盘符 / `..`）—— 包里声明的东西不许跑出包外。"""
    n = str(name).replace("\\", "/")
    if not n or n.startswith("/") or re.match(r"^[A-Za-z]:", n):
        return False
    parts = [p for p in n.split("/") if p not in ("", ".")]
    return bool(parts) and ".." not in parts


def _read_package_domains(pkg_dir: str) -> tuple:
    """真读一次 `<pkg>/editor/domains.json` → (声明表, [warning], 用不用内置默认集)。**只降级，不抛。**

    两种条目：
      · **新域**（内置没有）—— 必须自带 `kind`（data / rules），label/schema/primary/icon 可省；
      · **同名覆盖**（内置已有）—— 只需写要改的字段（如 `{"label": "天赋"}`），
        没写的字段**继承内置那份**（所以「只调 label」不会把 schema 静默弄丢）。

    第三个返回值 = 该包要不要**内置默认集**（`BUILTIN_DEFAULT_DOMAINS`）兜底：
    声明里写 `"$builtin": false` → 只认本包声明的域（缺省 True，= 历史行为）。
    """
    warns: list = []
    use_builtin = True
    path = domains_decl_path(pkg_dir)
    if not os.path.exists(path):
        return {}, warns, use_builtin         # 没声明 = 与内置一致（正常，不告警）
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return {}, [f"包域声明读不了（{DOMAINS_REL}）：{e} —— 已回退为内置域表"], use_builtin
    if not isinstance(raw, dict):
        return {}, [f"包域声明形状不对（{DOMAINS_REL}）：顶层需为对象 {{域id: {{…}}}}，"
                    f"实为 {type(raw).__name__} —— 已回退为内置域表"], use_builtin
    # 顶层 / 包装层里的 `"$builtin": false`（关掉内置默认集；非布尔 → 告警 + 按 true）
    inner = raw.get("domains") if isinstance(raw.get("domains"), dict) else None
    for holder in ([raw] + ([inner] if inner is not None else [])):
        for opt in ("$builtin", "$builtin_defaults"):
            if opt in holder:
                v = holder.pop(opt)
                if isinstance(v, bool):
                    use_builtin = v
                else:
                    warns.append(f"包域声明：{opt}={v!r} 不是布尔值 —— 按 true 处理"
                                 f"（内置默认集照常兜底）")
    if inner is not None:                      # 容忍 {"domains": {…}} 包装
        raw = inner
    out: dict = {}
    for did, meta in raw.items():
        if not isinstance(did, str) or not _DOMAIN_ID_RE.match(did):
            warns.append(f"包域声明：域 id {did!r} 不合规（小写字母开头，只含小写字母/数字/"
                         f"下划线/连字符，2~41 字符）—— 该条已忽略")
            continue
        if not isinstance(meta, dict):
            warns.append(f"包域声明 {did}：形状不对（需为对象，含 label/kind/schema/primary/icon）"
                         f"—— 该条已忽略")
            continue
        base = dict(BUILTIN_DEFAULT_DOMAINS[did]) if did in BUILTIN_DEFAULT_DOMAINS else {
            "label": did, "kind": None, "schema": None, "primary": None, "icon": ""}
        kind = meta.get("kind", base["kind"])
        if kind not in DOMAIN_KINDS:
            warns.append(f"包域声明 {did}：kind={meta.get('kind')!r} 非法（只能是 data / rules）"
                         f"—— 该条已忽略" if "kind" in meta else
                         f"包域声明 {did}：缺 kind（新域必须声明 data 或 rules）—— 该条已忽略")
            continue
        label, icon = meta.get("label"), meta.get("icon")
        if label is not None and not isinstance(label, str):
            warns.append(f"包域声明 {did}：label 不是字符串 —— 沿用内置值")
            label = None
        if icon is not None and not isinstance(icon, str):
            warns.append(f"包域声明 {did}：icon 不是字符串 —— 沿用内置值")
            icon = None
        schema = meta.get("schema")
        if schema is not None and not isinstance(schema, str):
            warns.append(f"包域声明 {did}：schema 不是字符串 —— 当作「不校验」")
            schema = None
        if schema and not _safe_rel_name(schema):
            warns.append(f"包域声明 {did}：schema={schema!r} 不是安全的相对路径 —— 当作「不校验」")
            schema = None
        primary = meta.get("primary")
        if primary is not None and not isinstance(primary, str):
            warns.append(f"包域声明 {did}：primary 不是字符串 —— 沿用内置值")
            primary = None
        owner, tier = meta.get("owner"), meta.get("tier")
        if owner is not None and owner not in DOMAIN_OWNERS:
            warns.append(f"包域声明 {did}：owner={owner!r} 非法（只能是 {'/'.join(DOMAIN_OWNERS)}）"
                         f"—— 该字段已忽略")
            owner = None
        if tier is not None and tier not in DOMAIN_TIERS:
            warns.append(f"包域声明 {did}：tier={tier!r} 非法（只能是 {'/'.join(DOMAIN_TIERS)}）"
                         f"—— 该字段已忽略")
            tier = None
        entry = {"label": label if label is not None else base["label"],
                 "kind": kind,
                 "schema": schema if schema is not None else base["schema"],
                 "primary": primary if primary is not None else base["primary"],
                 "icon": icon if icon is not None else base["icon"]}
        if owner is not None:            # 可选字段：**只在有值时输出**（没声明 = 没这个键）
            entry["owner"] = owner
        if tier is not None:
            entry["tier"] = tier
        out[did] = entry
    if raw and not out:
        warns.append("包域声明里没有一条可用（形状全部不合）—— 已回退为内置域表"
                     if use_builtin else
                     "包域声明里没有一条可用（形状全部不合），且声明里写了 "
                     "`\"$builtin\": false` —— 该包域表为空（编辑器不会 500，但没有任何域）")
    return out, warns, use_builtin


def _package_domains_cached(pkg_dir) -> tuple:
    """带缓存地读包域声明（按文件签名失效）→ (声明表, [warning], 用不用内置默认集)。"""
    key = _key(pkg_dir)
    if not key:
        return {}, [], True
    sig = _decl_sig(key)
    hit = _DOMAINS_CACHE.get(key)
    if hit is not None and hit[0] == sig:
        return hit[1], list(hit[2]), hit[3]
    decls, warns, use_builtin = _read_package_domains(key)
    if len(_DOMAINS_CACHE) > _CACHE_MAX:
        _DOMAINS_CACHE.clear()
    _DOMAINS_CACHE[key] = (sig, decls, warns, use_builtin)
    return decls, warns, use_builtin


def package_domains(pkg_dir) -> dict:
    """包自带的域声明 → {域id: {label, kind, schema, primary, icon}}（**域的真源就是它**）。

    缺文件 / 坏 JSON / 坏形状 → `{}`（回退内置），并记一条**可读 warning**
    （从 `package_domain_warnings(pkg_dir)` 或 `effective_domains()` 的第二个返回值取）。
    """
    decls, _warns, _ub = _package_domains_cached(pkg_dir)
    return {k: dict(v) for k, v in decls.items()}


def package_domain_warnings(pkg_dir) -> list:
    """读该包域声明时的告警（可读中文串；空 = 没声明或声明没问题）。"""
    return _package_domains_cached(pkg_dir)[1]


def package_uses_builtin_defaults(pkg_dir) -> bool:
    """该包要不要**内置默认集**兜底（缺省 True；声明里写 `"$builtin": false` → False）。"""
    return _package_domains_cached(pkg_dir)[2]


def declared_domain_ids(pkg_dir) -> list:
    """该包**自己声明过**（且声明可用）的域 id —— 域的真源是这份，不是框架常量。

    与 `package_domains()` 同一份数据的键序；缺声明 / 坏声明 → `[]`（`[]` = 「靠内置默认集兜底」）。
    """
    return list(_package_domains_cached(pkg_dir)[0])


def domain_source(pkg_dir, dom: str):
    """该域在「这个包」视角下的来源：

    `"package"` = 由包自己的 `editor/domains.json` 声明（**真源在包**，内置那份不参与）；
    `"builtin"` = 包里没声明，只有框架内置默认集兜着（回退）；
    `None`      = 这个包不认识该域。
    """
    decls, _warns, use_builtin = _package_domains_cached(pkg_dir)
    if dom in decls:
        return "package"
    if use_builtin and dom in BUILTIN_DEFAULT_DOMAINS:
        return "builtin"
    return None


def effective_domains(pkg_dir=None) -> tuple:
    """包声明 ∪（可选的）内置默认集**合并** → (有效域表, [warning])。

    * **真源在包**：`<pkg>/editor/domains.json` 里写的域、以及同名字段，一律以包为准
      （内置那份**不再参与该域的取值**）；包声明里写的域也一定在结果里。
    * **内置默认集只是回退**：包**没**声明时兜底；包声明里有 `"$builtin": false` 时整个不参与
      （于是「这个包的域」= 它自己声明的那几个，不再夹带框架那 19 个）。
    * 同名域**只要真改了东西**就进 warnings（形如「域 skills 被包声明覆盖（label: '技能' → '天赋'）」）。
      逐字段完全相同（= 等值搬迁，如 `games/orlandia/editor/domains.json`）**不算覆盖、不告警** ——
      否则零回归会被一堆「覆盖（字段值相同）」噪声埋掉。
    * 关掉内置默认集且声明为空 → 域表为空 + 一条 warning（**不抛、不 500**）。
    * 合并顺序 = 内置默认集顺序 + 包新增域（追加在末尾），所以既有 tab 的位置不会乱跳。
    """
    decls, warns, use_builtin = _package_domains_cached(pkg_dir)
    merged = builtin_default_domains() if use_builtin else {}
    for did, meta in decls.items():
        if did in merged:
            old = merged[did]
            diff = "；".join(f"{f}: {old.get(f)!r} → {meta.get(f)!r}"
                             for f in _OVER_FIELDS if old.get(f) != meta.get(f))
            if diff:
                warns.append(f"域 {did} 被包声明覆盖（{diff}）—— 该域的 "
                             f"label/kind/schema/primary/icon 一律以包内 {DOMAINS_REL} 为准")
        merged[did] = dict(meta)
    if not use_builtin and not merged:
        warns.append(f"包声明里写了 `\"$builtin\": false`（不启用内置默认集），但一条可用域都没有"
                     f" —— 该包域表为空：请在 {DOMAINS_REL} 里声明自己的域")
    return merged, list(warns)


def domain_meta(pkg_dir, dom: str, domains: dict | None = None):
    """该包视角下某个域的元数据（包声明优先）；未知域 → None。"""
    if domains is None:
        domains, _w = effective_domains(pkg_dir)
    return (domains or {}).get(dom)


def domain_path(pkg_dir: str, dom: str, domains: dict | None = None) -> str:
    """域数据文件路径 —— 落 `content/data` 还是 `content/rules` 由该域 `kind` 决定
    （所以**包新增的域自动落对目录**）。未知域 → KeyError（与旧行为一致）。"""
    d = domain_meta(pkg_dir, dom, domains)
    if d is None:
        raise KeyError(f"未知域：{dom}")
    sub = "rules" if d.get("kind") == "rules" else "data"
    return os.path.join(pkg_dir, "content", sub, f"{dom}.json")


def schema_path(pkg_dir, dom: str, domains: dict | None = None):
    """域 schema 文件路径：**包内优先**（`<pkg>/schemas/<声明值>`，其次 `<pkg>/<声明值>`），
    找不到再回退框架 `schemas/`（第三方包没自带 schema 时命中的是这条）。
    没声明 / 找不到 / 路径不安全 → None（= 该域不校验，编辑器照旧可增删改）。

    顺序为什么是「包优先」：包显式声明了文件名就是显式意图（换一款游戏/自己收紧规则），
    而包自带的那份是**逐字搬来的**（`games/orlandia/schemas/` = 框架 `schemas/` 的
    sha256 相同副本）→ 解析结果与改造前逐字节一致（零回归）；框架那份**不删**，
    作为第三方包 / 坏 schema 的**回退**（读取侧的降级见 `validate._resolve_schema()`）。
    """
    d = domain_meta(pkg_dir, dom, domains)
    if not d:
        return None
    fn = d.get("schema")
    if not fn or not isinstance(fn, str):
        return None
    if pkg_dir and _safe_rel_name(fn):
        for cand in (os.path.join(pkg_dir, "schemas", fn),
                     os.path.join(pkg_dir, fn.replace("\\", "/"))):
            if os.path.isfile(cand):
                return cand
    fw = os.path.join(FRAMEWORK_ROOT, "schemas", fn)
    return fw if os.path.exists(fw) else None


def framework_schema_path(pkg_dir, dom: str, domains: dict | None = None):
    """**框架 `schemas/<声明值>` 那份**（回退副本）→ 路径 | None。

    只看**包声明的 schema 文件名**，不要求「这个域是框架内置域」——
    ★ 2026-09-13 B2b：内容域（skills / items …）现在由包声明，内置集里没有它们；
    若回退仍按「域名 ∈ 内置集」判定，包内 schema 坏了就**降级不到框架那份**了
    （`validate._resolve_schema()` 的坏 schema 降级路径靠它）。
    """
    d = domain_meta(pkg_dir, dom, domains)
    fn = (d or {}).get("schema")
    if not fn or not isinstance(fn, str) or not _safe_rel_name(fn):
        return None
    fw = os.path.join(FRAMEWORK_ROOT, "schemas", fn)
    return fw if os.path.exists(fw) else None


def read_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")
    os.replace(tmp, path)


def sort_table_keys(table: dict) -> dict:
    """域表**外层键重排为升序**（落盘规范：外层键升序）—— **只重排外层**。

    条目内层键序**原样保留**：真源插入序由条目内 `seq` 字段承载（内容侧按它还原），
    编辑器保存不许动内层。新建 / 改名条目不重排的话，新键会追加到尾部 →
    包仓冻结门禁 `tests/test_export_package_sync.py`【6】「外层键非升序」转红
    （改造前实测：`put_entry('boss_phases','aaa_first_alpha')` → 键序尾部追加）。
    """
    return {k: table[k] for k in sorted(table)}                    # 升序 = sorted() 的码位序，与冻结门禁同一判据


def load_manifest(pkg_dir: str) -> dict:
    m = read_json(manifest_path(pkg_dir), None)
    if not isinstance(m, dict):
        return {}
    return m


def save_manifest(pkg_dir: str, m: dict) -> None:
    write_json(manifest_path(pkg_dir), m)


# ---------------- 发现 / 新建 ----------------
def ensure_games_dir(root_dir: str | None = None) -> str:
    """游戏包根目录（参数 > 环境变量 > framework/games/），不存在则创建。"""
    d = root_dir or os.environ.get("FW_GAMES_DIR") or DEFAULT_GAMES_DIR
    os.makedirs(d, exist_ok=True)
    return d


def list_packages(root_dir: str | None = None) -> list:
    root = ensure_games_dir(root_dir)
    out = []
    for name in sorted(os.listdir(root)):
        p = os.path.join(root, name)
        if not os.path.isdir(p) or not os.path.exists(manifest_path(p)):
            continue
        m = load_manifest(p)
        out.append({
            "id": m.get("id") or name,
            "dir": p,
            "name": m.get("name") or name,
            "desc": m.get("desc", ""),
            "engine": m.get("engine", ""),
            # 清单没声明就用**该包的有效域表**（内置 + 包自带声明）
            "domains": m.get("domains") or list(effective_domains(p)[0]),
        })
    return out


def resolve_package(pkg_id: str, games_dir_: str | None = None) -> str | None:
    """按 id 找包目录（也接受绝对路径，便于「打开任意目录」）。"""
    if os.path.isabs(pkg_id) and os.path.exists(manifest_path(pkg_id)):
        return pkg_id
    root = ensure_games_dir(games_dir_)
    p = os.path.join(root, pkg_id)
    if os.path.exists(manifest_path(p)):
        return p
    for m in list_packages(games_dir_):
        if m["id"] == pkg_id:
            return m["dir"]
    return None


_ID_RE = re.compile(r"^[a-z][a-z0-9_\-]{1,40}$")


def _write_domains_decl(pkg_dir: str, doms) -> str:
    """脚手架：把选中的域**写进包自己的 `editor/domains.json`**（逐字段照内置默认集）。

    为什么要写（而不是让它靠框架那份常量）：**域的真源在包** —— 脚手架产出的包不该
    「框架哪天改了内置默认集，我的域集就跟着变」。等值声明不产 warning
    （`effective_domains()` 只对**真改了东西**的同名域告警），所以对既有行为零影响。
    """
    decl = {d: dict(BUILTIN_DEFAULT_DOMAINS[d]) for d in doms if d in BUILTIN_DEFAULT_DOMAINS}
    p = domains_decl_path(pkg_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    write_json(p, decl)
    return p


def create_package(pkg_id: str, name: str, desc: str = "",
                   domains=None, games_dir_: str | None = None) -> dict:
    """脚手架：建一个游戏包（含选中的域 + 域声明 + apply.py + 冒烟测试骨架）。"""
    if not _ID_RE.match(pkg_id or ""):
        raise ValueError("包 id 只能小写字母/数字/下划线/连字符，字母开头，2-41 字符")
    root = ensure_games_dir(games_dir_)
    pkg_dir = os.path.join(root, pkg_id)
    if os.path.exists(pkg_dir):
        raise ValueError(f"目标目录已存在：{pkg_dir}")
    # ★ 2026-09-13 B2b：脚手架只认**内置（引擎）域** —— 内容域的元数据（kind/schema/primary）
    #   归内容包，框架不认识（真源在包）。传进来的未知域不建空壳、也不静默丢：
    #   原样回报 `unknown_domains`，让调用方去写包内 `<pkg>/editor/domains.json`。
    want = list(domains) if domains else list(DOMAINS)
    doms = [d for d in want if d in DOMAINS]
    unknown = [d for d in want if d not in DOMAINS]
    for d in doms:
        write_json(domain_path(pkg_dir, d), {})
    _write_domains_decl(pkg_dir, doms)          # 包自带域声明（真源在包，内置那份只是回退）
    os.makedirs(os.path.join(pkg_dir, "content", "mech"), exist_ok=True)
    write_json(manifest_path(pkg_dir), {
        "id": pkg_id, "name": name or pkg_id, "desc": desc,
        "engine": ">=0.1", "domains": doms,
        "entry": "content/apply.py",
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    _write_apply_scaffold(pkg_dir, pkg_id, name or pkg_id)
    return {"dir": pkg_dir, "id": pkg_id, "domains": doms, "unknown_domains": unknown}


def _write_apply_scaffold(pkg_dir: str, pkg_id: str, name: str) -> None:
    """生成装配入口骨架（内容 → 引擎方向；第三方照这个写自己的挂载）。"""
    body = f'''# -*- coding: utf-8 -*-
"""{name}（{pkg_id}）—— 内容装配入口（由框架编辑器脚手架生成）。

两件事，都幂等：
    install_engine()            全局：把本游戏的公式/面板/技能表/kind 词表/声明表挂进引擎
    apply_game_content(actor)   单个 actor：把资源渠道/机制/被动翻成 triggers

方向只有一个：**内容 → 引擎**。框架不 import 本包，也不认识本包的表。
数据源是 content/data/*.json 与 content/rules/*.json（编辑器直接改这些文件）。
"""
from __future__ import annotations

import json
import os

import saintess_engine.config as config   # 引擎公开注入面

_HERE = os.path.dirname(os.path.abspath(__file__))
_MOUNTED = False


def _load(name: str, rules: bool = False):
    sub = "rules" if rules else "data"
    p = os.path.join(_HERE, sub, f"{{name}}.json")
    if not os.path.exists(p):
        return {{}}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _lazy_mount():
    """引擎首次访问未装配 hook 时的自举（框架只认这一个回调）。"""
    install_engine()


# ---- CTB 时间模型（★ 引擎**不内置**任何行动耗时公式与常量：不挂即 fail-closed）----
# 一次行动耗时 = base × (spd_ref / spd)（linear；spd = spd_ref 时 = base）。
# 换公式形状/参数只改下面这一张表；引擎侧只按 ct 排序推进，不认识速度语义。
_TIME_MODEL = {{"shape": "linear", "spd_ref": 50.0, "spd_cap": None,
               "cast": {{"attack": 1.0, "skill": 1.6, "defend": 0.6, "item": 1.0}}}}


def _time_scale(spd, base) -> float:
    """`time_model_fn` 供体：一次行动耗时（游戏秒）。"""
    s = max(float(spd or 0), 1.0)
    cap = _TIME_MODEL.get("spd_cap")
    if cap:
        s = min(s, float(cap))
    return float(base) * (float(_TIME_MODEL["spd_ref"]) / s)


def _action_base(action: str) -> float:
    """`action_base_fn` 供体：行动类别 → 基准耗时。"""
    return float((_TIME_MODEL["cast"] or {{}}).get(action) or _TIME_MODEL["cast"]["attack"])


def install_engine() -> None:
    """把本游戏配置挂进引擎（幂等）。表为空时挂空表（引擎按零默认值处理）。"""
    global _MOUNTED
    if _MOUNTED:
        return
    import saintess_engine.battle.formulas as formulas

    config.register_hook_provider(_lazy_mount)
    # ⚠️ hook（引擎只认 13 个名字）走 `mount`；**声明表不要走 mount** ——
    # `set_hook` 对不认识的名字是**静默忽略**，写 `mount(effect_rules=…)` 会"看起来装配成功、
    # 实则规则表是空的"（效果全部不生效且不报错）。声明表走 `load_game_rules`。
    config.mount(formulas=formulas,          # 引擎自带通用公式模块
                 time_model_fn=_time_scale,  # ★ CTB 时间模型（不挂即 fail-closed）
                 action_base_fn=_action_base)  # 行动类别 → 基准耗时

    class _Rules:
        pass

    _r = _Rules()
    _r.EFFECT_RULES = _load("effect_rules", True)
    _r.EFFECT_ACTIONS = _load("effect_actions", True)
    config.load_game_rules(_r)
    _MOUNTED = True


def apply_game_content(actor: dict) -> dict:
    """把本游戏内容挂到 actor 上（幂等）。"""
    if not isinstance(actor, dict):
        return actor
    install_engine()
    return actor
'''
    p = os.path.join(pkg_dir, "content", "apply.py")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)


# ---------------- 条目 CRUD ----------------
def list_entries(pkg_dir: str, dom: str, domains: dict | None = None) -> dict:
    """返回 {entries: [{key, name, kind, ...}], count}。

    `domains` 省略 = 按该包的**有效域表**（内置 + 包自带声明）；未知域 → KeyError。
    """
    if domains is None:
        domains, _w = effective_domains(pkg_dir)
    if dom not in domains:
        raise KeyError(dom)
    table = read_json(domain_path(pkg_dir, dom, domains), {})
    if not isinstance(table, dict):
        table = {}
    rows = []
    for k, v in table.items():
        if not isinstance(v, dict):
            continue
        rows.append({
            "key": k,
            "name": v.get("name") or k,
            "kind": v.get("kind") or v.get("type") or "",
            "lv": v.get("lv"),
            "summary": (v.get("desc") or "")[:60],
        })
    rows.sort(key=lambda r: (str(r.get("kind") or ""), str(r["name"])))
    return {"domain": dom, "count": len(rows), "entries": rows}


def get_entry(pkg_dir: str, dom: str, key: str):
    table = read_json(domain_path(pkg_dir, dom), {})
    if not isinstance(table, dict) or key not in table:
        return None
    return table[key]


def put_entry(pkg_dir: str, dom: str, key: str, data: dict) -> None:
    table = read_json(domain_path(pkg_dir, dom), {})
    if not isinstance(table, dict):
        table = {}
    table[key] = data
    # 落盘前仅把**外层键**重排为升序（新建 / 改名的新键不许追加到尾部）——
    # 条目内层键序不动（真源插入序在条目内 `seq`；见 sort_table_keys 注）。
    write_json(domain_path(pkg_dir, dom), sort_table_keys(table))


def delete_entry(pkg_dir: str, dom: str, key: str) -> bool:
    table = read_json(domain_path(pkg_dir, dom), {})
    if not isinstance(table, dict) or key not in table:
        return False
    table.pop(key)
    # 同 put_entry：删除本身不会破坏升序，但顺带归一化（救历史版本追加到尾部的旧文件）
    write_json(domain_path(pkg_dir, dom), sort_table_keys(table))
    return True


def domain_status(pkg_dir: str, dom: str, domains: dict | None = None) -> dict:
    """域概览：条目数 + 校验结果（供 tab 上的徽标）。未知域 → 空概览（不抛）。

    第 2 层（2026-09-13）：该域若被包**声明了引用关系**（`<pkg>/editor/relations.json`），
    校验结果里也带上**引用校验**（`relations.ref_errors`）—— 与 HTTP 侧
    （`server._domain_status`）同一口径。包没声明 ref → 逐项等于改造前。
    """
    st = {"domain": dom, "count": 0, "invalid": [], "ok": True}
    if domains is None:
        domains, _w = effective_domains(pkg_dir)
    if dom not in domains:
        return st
    try:
        st.update({k: v for k, v in list_entries(pkg_dir, dom, domains).items() if k == "count"})
    except KeyError:
        return st
    from . import validate as V          # 同目录模块
    refs = []
    try:
        from . import relations as _REL  # 延迟 import（relations 依赖本模块，避免成环）
        refs = [r for r in (_REL.package_relations(pkg_dir).get(dom) or {}).values() if r.get("ref")]
    except Exception:                    # noqa: BLE001 —— 声明面坏 → 不拖累域状态
        refs = []
    table = read_json(domain_path(pkg_dir, dom, domains), {})
    for k, v in (table or {}).items():
        if not isinstance(v, dict):
            continue
        errs = V.validate_entry(dom, v, pkg_dir)
        if refs:
            errs = errs + _REL.ref_errors(pkg_dir, dom, v)
        if errs:
            st["invalid"].append({"key": k, "errors": errs})
    st["ok"] = not st["invalid"]
    return st


def package_overview(pkg_dir: str) -> dict:
    """包概览（manifest + 各域条目数/校验状态）。域表走**有效域表**（内置 + 包自带声明）。"""
    m = load_manifest(pkg_dir)
    domains, warns = effective_domains(pkg_dir)
    # 第 2 层（2026-09-13）：包声明面的告警也一起回（引用/联动 + 视图；没声明 = 空）。
    # 延迟 import —— `relations` 依赖本模块，模块级互相 import 会成环。
    try:
        from . import relations as _REL
        warns = list(warns) + _REL.all_warnings(pkg_dir)
    except Exception:                                    # noqa: BLE001 —— 声明面坏 → 不拖累概览
        warns = list(warns)
    doms = m.get("domains") or list(domains)
    return {
        "manifest": m,
        "engine_check": engine_check(m),
        "domains": [{"id": d, **{k: domains[d][k] for k in ("label", "icon", "kind")},
                     **domain_status(pkg_dir, d, domains)}
                    for d in doms if d in domains],
        # 包自带域声明的告警（坏声明 / 同名覆盖）—— 前端照此提示，不静默
        "domain_warnings": warns,
        # 该包**自己新增**（内置默认集里没有）的域 id —— 有值 = 纯包侧加出来的域
        # （「包声明过的域」看 `/api/domains` 的 `from_package`，那个是声明口径，不是差值口径）
        "package_domains": [d for d in domains if d not in DOMAINS],
    }


def engine_check(manifest: dict) -> dict:
    """校验 game.json 声明的 `engine` 版本要求（设计约定：不满足要显式报错，不静默降级）。

    框架不在 sys.path 时（例如纯文件操作场景）返回 {ok: None}，不阻断。
    """
    req = str((manifest or {}).get("engine") or "")
    try:
        _root = FRAMEWORK_ROOT
        if _root not in os.sys.path:
            os.sys.path.insert(0, _root)
        from saintess_engine import version as V          # noqa: PLC0415
    except Exception as e:                                # noqa: BLE001
        return {"ok": None, "requirement": req, "version": "", "note": f"未加载框架版本：{e}"}
    ok, note = V.check(req)
    return {"ok": ok, "requirement": req, "version": V.__version__, "note": note}
