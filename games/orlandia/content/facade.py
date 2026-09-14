# -*- coding: utf-8 -*-
"""包内聚合门面（`content/facade.py`）—— **取代宿主 `game/content.py` 的包内半边**。

为什么要有它
------------
宿主 `game/content.py` 是**薄聚合层**：`from .core import *`（宿主各级薄壳再导出包内实现）
+ 从包内 `catalog_*` 门面 `setdefault` 落名；包内过去有一批模块（`cmds_social` /
`persistence/*` / `profession` / `settlement` / `event_templates` / `economy_cmds` …）
**通过宿主句柄 `C`**（`_HostMod("content")` / `from .handles import C`）读那些名字 ⇒ 包离不开宿主。
本模块把那只门面**搬进包内**，于是这些读点可以「包 → 包」。

取件时机（**行为的一部分，别改成 import 期**）
--------------------------------------------
旧写法 `_HostMod("content")` 在**属性访问时**才 `import game.content`（惰性）。本模块保持同一时机：
`C` 是惰性聚合句柄 —— 首次属性访问时才 import 各来源模块并聚合。
理由见 `content/_pkgref.py` 的 docstring：`content/persistence/__init__.py` 在 EAGER 窗口里读
`C.MAP_BY_ID`（`schema.py:25`），改成 import 期解析会炸 `partially initialized module`。

聚合口径（`setdefault` = 「先落者胜」，与宿主门面同义）
-----------------------------------------------------
`AGGREGATE_MODULES` 分两段，**顺序就是裁定**：

  ① 索引 + `catalog_*` 门面（数据名的权威落点）—— 先落；
  ② core 层各实现模块（函数名 / 常量 / 公式）—— 后落，只补 ① 没有的名。

★ 为什么 ① 必须在 ② 之前（W2a 探针实测，不是推测）
    `content.achievements` 自建 `ITEMS = _read_domain("items")`、`content.fishing` 自建
    `FISH_POOL` —— 与宿主门面**同值但不同一只对象**（宿主 core 薄壳并不再导出这些数据名；
    数据名一律来自 `catalog_*`）。core 段在前时实测这两名 `is` 判定为 False；
    ① 在前时 71 个 `C.<名>` 读点**全部同一只对象**（证据 `out/probe/c_facade_identity.json`）。
    ★ 「同值不同一只 dict」不是等价：包内有多处**就地改表**（如数值门禁的 `curve_override`
    就地写 `content.stats` 的表），第二只 dict 会让改动看不见 —— 所以按对象同一性裁定。

覆盖层 `_NAME_SRC`（**优先于聚合面**）：显式指名包内真源模块。
**按名解析，不猜** —— 表里每一行都由探针实测（宿主 `getattr(game.content, 名).__module__`
与对象同一性反查），清单见 `overnight/C_NAME_TO_PACKAGE_MAP.md` 与 `out/probe/c_identity.json`。
优先于聚合面的理由（实测）：`content.tables`（同值不同键序的再导出面）也导出
`equip_stats` / `equip_value` / `exp_to_next`，聚合面里它会遮住 `content.stats` 的**宿主同一只**。

注入扇出（`bind_host(**inject)`）
--------------------------------
`game.json` 的 `bind` 指向本模块的 `bind_host`；引擎（`saintess_engine.host.load_package`）
在 import 包命令模块**之前**调用它，把「包运行期要用的宿主对象」一次分发到各模块既有注入槽。
**真·宿主能力只有四类**：

| 类 | inject 键 | 落点 |
|---|---|---|
| 库路径 | `db_path` | `persistence.handles.bind` |
| 时钟 | `clock` | `persistence.handles.bind` |
| 日志与流水 sink | `log` / `tlog` / `flush_log` / `lock` | `obs.bind` / `persistence.handles.bind` |
| 发奖 | `grant_reward` | `flow.weekly_progress` / `talk_actions` / `quests_flow` |

其余注入键（`_shop_svc` / `_ss` / `_sshop` / `_craft_svc` / `_prof_svc` / `C` / `db` /
`item_templates` / `data` / `T` …）**一律自解析到包内模块**（`_PKG_SURFACE`）。
扇出目标 = `_BIND_SLOTS` 穷举表（AST 扫全包 51 个 `def bind_host(` 的取件键 + 宿主壳运行时
录制的注入键取并集，逐键判定归属；证据 `out/probe/bind_keys.json` /
`out/probe/bind_surface.json`）。**没有 `except: pass`、没有按名猜、没有兜底空表** ——
认不出的键会被对应 `bind_host` 自行忽略，而 import / bind 的异常原样上抛（拒绝静默空跑）。

缺口（**显式登记，不用兜底掩盖**）
--------------------------------
* `AstrMessageEvent` / `MessageChain` / `Plain`（astrbot 平台类型，`content/economy_cmds.py:56-58`）
  与 `attach_tlog`（宿主流水 sink 装配器）/ `check_action_keys`（宿主对话动作键防御）/
  `commands.combat`（宿主独有类）—— **不是包内可自解析对象**：只能由宿主 inject 提供，
  否则消费点在取件时 `RuntimeError`（fail-closed）。
* `STAT_NAMES` 在宿主 `game.content` 上**不存在**（它住 `game/content_rules/panel.py`，
  不在 core 聚合面）⇒ 包内门面同样**不导出**它，`hasattr(C, "STAT_NAMES")` 两侧同为 False。
"""
from __future__ import annotations

import importlib

__all__ = ["C", "bind_host", "resolve_name", "AGGREGATE_MODULES"]

# ============================================================
# ① 聚合来源（顺序 = 裁定，别随意改；改前先跑 out/probe/c_facade_identity.py）
# ============================================================
AGGREGATE_MODULES = (
    # ---- ① 索引 + catalog_* 门面（数据名权威落点，先落）----
    "content.index",
    "content.catalog_legacy",
    "content.catalog_b143",
    "content.catalog_core",
    "content.catalog_items",
    "content.catalog_life",
    "content.catalog_quests",
    "content.catalog_rules",
    "content.catalog_space",
    # ---- ② core 层实现模块（函数名 / 常量 / 公式，后落补名）----
    "content.tables",
    "content.constants",
    "content.stats",
    "content.achievements",
    "content.drops",
    "content.runes",
    "content.factions",
    "content.pets",
    "content.time_weather",
    "content.gems",
    "content.worlds",
    "content.mounts",
    "content.fishing",
    "content.craft",
    "content.loot",
    "content.affix",
    "content.dialogue",
    "content.enchant",
    "content.timed_events",
    "content.maps",
)

#: 覆盖层：`C.<名>` → 包内真源模块全名。①② 都取不到时用。
#: 全部由探针实测（对象同一性 + `__module__`），不含未验证的名字。
_NAME_SRC = {
    # ---- 常量 / 表 ----
    "STAMINA_RECOVER_INTERVAL": "content.constants",
    "BOSS_BP_DROP_CHANCE": "content.constants",
    "EQUIP_ROSTER": "content.catalog_items",
    "EQUIP_SLOTS": "content.catalog_b143",
    "AFFIX_AFFINITY_POOLS": "content.catalog_rules",
    # ---- 成就 ----
    "achievement_titles": "content.achievements",
    "check_achievements": "content.achievements",
    # ---- 词条 / 附魔 ----
    "affix_label": "content.affix",
    "random_req": "content.affix",
    "stat_affix_stats": "content.affix",
    "enchant_match_material": "content.enchant",
    "enchant_value": "content.enchant",
    # ---- 掉落 / 装备生成 ----
    "build_monster": "content.drops",
    "generate_equip": "content.drops",
    "generate_roster_equip": "content.drops",
    "make_blueprint": "content.drops",
    "roll_blueprint": "content.drops",
    "roll_drop": "content.drops",
    "roll_drop_equip": "content.drops",
    # ---- 副业 / 生活 ----
    "craft_recipe_make": "content.craft",
    "craft_recipe_search": "content.craft",
    "craft_recipes_by_material": "content.craft",
    "roll_collect_fish": "content.fishing",
    "roll_fish": "content.fishing",
    "roll_fish_size_weight": "content.fishing",
    # ---- 时间 / 天气 ----
    "current_period": "content.time_weather",
    "current_season": "content.time_weather",
    "today_weather": "content.time_weather",
    "get_timed": "content.timed_events",
    # ---- 宠物 / 坐骑 ----
    "make_pet_egg": "content.pets",
    "pct_str": "content.pets",
    "pet_exp_bonus": "content.pets",
    "pet_exp_mult": "content.pets",
    "pet_exp_need": "content.pets",
    "pet_quality_label": "content.pets",
    "pet_skill_label": "content.pets",
    "make_mount_rein": "content.mounts",
    "mount_effects": "content.mounts",
    "roll_mount_drop": "content.mounts",
    # ---- 宝石 / 符文 ----
    "gem_combine": "content.gems",
    "gem_socket_cost": "content.gems",
    "roll_gem": "content.gems",
    "roll_gem_drop": "content.gems",
    "rune_conflict": "content.runes",
    "rune_item": "content.runes",
    "rune_value": "content.runes",
    # ---- 地图 / 对话 / 声望 / 战斗数值 ----
    "map_center": "content.maps",
    "map_entry_subarea": "content.maps",
    "map_exit_subarea": "content.maps",
    "map_route": "content.maps",
    "subarea_links": "content.maps",
    "dialogue_node": "content.dialogue",
    "get_dialogue": "content.dialogue",
    "faction_reputation_tier": "content.factions",
    "get_instance_st": "content.worlds",
    "equip_stats": "content.stats",
    "equip_value": "content.stats",
    "exp_to_next": "content.stats",
}

_NS = None


def _namespace() -> dict:
    """惰性构建聚合命名空间（首次访问时 import + setdefault；之后缓存同一只 dict）。"""
    global _NS
    if _NS is None:
        ns: dict = {}
        for mod_name in AGGREGATE_MODULES:
            mod = importlib.import_module(mod_name)
            # ★ 用模块 `__dict__` 的插入序（`dir()` 会排序）；口径 = `setdefault` 先落者胜，
            #   与宿主 `game/content.py` 的 `globals().setdefault(...)` 同义。
            for name, value in vars(mod).items():
                if name.startswith("__"):
                    continue
                ns.setdefault(name, value)
        _NS = ns
    return _NS


class _Aggregate(object):
    """惰性聚合句柄：`C.<名>` 属性访问时解析（取件时机 = 旧 `_HostMod("content")` 逐字相同）。"""

    __slots__ = ()

    def __getattr__(self, attr):
        # ★ 覆盖层优先：`_NAME_SRC` 每一行都是探针实测的「宿主同一只」，
        #   聚合面里若有同名异对象（`content.tables` 这类同值不同序的再导出面）不应遮住它。
        src = _NAME_SRC.get(attr)
        if src is not None:
            return getattr(importlib.import_module(src), attr)
        ns = _namespace()
        if attr in ns:
            return ns[attr]
        # fail-closed：**不返回 None、不静默兜底**（宿主门面有而包内没有的缺口要显式暴露）
        raise AttributeError(
            "content.facade.C：包内聚合门面里没有 `%s`（宿主门面有而包内没有？"
            "请查 overnight/C_NAME_TO_PACKAGE_MAP.md 并登记缺口，别静默兜底）" % (attr,))

    def __dir__(self):
        return sorted(set(_namespace()) | set(_NAME_SRC))

    def __repr__(self):
        return "<content.facade.C 聚合句柄（%d 名）>" % len(_namespace())


C = _Aggregate()


def resolve_name(name: str):
    """按名取件（动态取名的调用点用；取不到 → AttributeError，**不静默**）。"""
    return getattr(C, name)


# ============================================================
# ② 注入扇出
# ============================================================
#: 包内自解析面：注入键 → 包内落点（模块全名 或 `(模块全名, 属性名)`）。
#: 判据 = 宿主壳注入的是什么对象（运行时探针 `out/probe/bind_surface.json`），**不是名字像什么**。
_PKG_SURFACE = {
    # ---- 模块型（宿主壳注入模块对象）----
    "content": C,                                  # 聚合门面（宿主 `game.content`）
    "C": C,
    "c": C,
    "db": "content.persistence",                   # 宿主 `game.db`（包内同库同实现）
    "data": "content.catalog_legacy",              # 宿主 `game.data`（已删；包内等价物 = 丢名再导出面）
    "T": "content.texts",
    "texts": "content.texts",
    "item_templates": "content.item_templates",
    "timed": "content.timed_events",
    "store_social": "content.persistence.social",
    "quests_svc": "content.persistence.quests",
    "bridge": "content.bridge",
    "services.battle_bridge": "content.bridge",
    "combat": "content.combat_cmds",
    "instance_battle": "content.flow.instance_battle",
    "_shop_svc": "content.shop",                   # 宿主 `game/services/shop.py` 薄壳
    "_sshop": "content.shop_stock",                # ★ 宿主 `game/core/shop_stock.py`（限购面）
    "_ss": "content.smith_stock",                  # 宿主 `game/core/smith_stock.py`（共享货架）
    "_craft_svc": "content.crafting",              # 宿主 `game/services/crafting.py`
    "_prof_svc": "content.profession",             # 宿主 `game/services/profession.py`
    "tlog_setup": "content.obs",                   # 流水控制面（emit/enabled/tlog）的包内等价物
    # ---- 值型（宿主壳注入对象本身）----
    "QUALITY": ("content.catalog_b143", "QUALITY"),
    "quality": ("content.catalog_b143", "QUALITY"),
    "config": ("content.catalog_b143", "GUILD_CONFIG"),
    "ACT_TICK": ("content.constants", "ACT_TICK"),
    "ARMOR_FAMILY_ALIAS": ("content.stats", "ARMOR_FAMILY_ALIAS"),
    "equip_value": ("content.stats", "equip_value"),
    "STAT_NAMES": ("content.panel", "STAT_NAMES"),
    "_set_info": ("content.panel", "_set_info"),
    "player_final_stats": ("content.panel", "player_final_stats"),
    "panel_stats": ("content.panel", "player_final_stats"),
    "race_stats": ("content.panel", "race_stats"),
    "CONDITIONS": ("content.title_conds", "CONDITIONS"),
    "TitleCtx": ("content.title_conds", "TitleCtx"),
    "check_pro_title": ("content.title_conds", "check_pro_title"),
    "_eq_random_desc": ("content.drops", "_eq_random_desc"),
    "_merge_legendary_stats": ("content.drops", "_merge_legendary_stats"),
    "build_monster": ("content.drops", "build_monster"),
    "resolve_drop": ("content.gameplay_rules", "resolve_drop"),
    "rule_fire": ("content.rule_engine", "fire"),
    "rune_item": ("content.runes", "rune_item"),
    "stat_affix_stats": ("content.affix", "stat_affix_stats"),
    "sync_player_from_actor": ("content.bridge", "sync_player_from_actor"),
    "can_translate": ("content.mech.item_use", "can_translate"),
    "make_override": ("content.mech.item_use", "make_override"),
    "_possessed_key": ("content.persistence.inventory", "_possessed_key"),
    "key_to_id": ("content.persistence.inventory", "_key_to_id"),
    "level_up": ("content.gameplay_rules", "check_player_level_up"),
    "levelup": ("content.gameplay_rules", "check_player_level_up"),
    "stat_bonus": ("content.stat_bonus", "stat_bonus"),
    "stat_bonus_fn": ("content.stat_bonus", "stat_bonus"),
    "maps": ("content.catalog_space", "MAP_BY_ID"),
    "house_levels": ("content.catalog_life", "HOUSE_LEVELS"),
    "econ": ("content.catalog_life", "ECON_CONFIG"),
}

#: 存档层能力键（`persistence.handles.bind` 认的形参；**不**进扇出 payload —— 见 `bind_host`）
_HANDLE_KEYS = ("db_path", "clock", "flush_log", "lock", "db")

#: `bind_host` 穷举表：模块 → 该模块 `bind_host` 认的键（AST 取件键 ∪ 宿主壳运行时注入键）。
#: 只喂它认的键（认不出的键被 `**objs` 收下也无害，但显式表让「谁要什么」可审）。
_BIND_SLOTS = (
    # ① 自由键登记处（economy_cmds / shop 的 `_HostRef` 面）—— 必须先于其消费方
    ("content.economy_host", (
        "ARMOR_FAMILY_ALIAS", "C", "CONDITIONS", "QUALITY", "STAT_NAMES", "TitleCtx",
        "_craft_svc", "_eq_random_desc", "_merge_legendary_stats", "_possessed_key",
        "_prof_svc", "_set_info", "_shop_svc", "_ss", "_sshop", "can_translate",
        "check_pro_title", "db", "equip_value", "item_templates", "make_override",
        "player_final_stats", "race_stats", "rune_item", "stat_affix_stats",
        "sync_player_from_actor",
    )),
    # ② 存档层替身口（`content` / `db` 两个键；真能力走 `handles.bind`，见 `bind_host`）
    ("content.persistence.handles", ("content", "db")),
    # ③ 各模块既有注入槽
    ("content.achievement_conds", ()),
    ("content.affix", ()),
    ("content.auction", ("db", "content")),
    ("content.bridge", ()),
    ("content.class_sets", ("data",)),
    ("content.cmds_instance_router", ("c", "build_monster", "instance_battle")),
    ("content.combat_cmds", ("db", "content", "attach_tlog", "commands.combat")),
    ("content.constants", ()),
    ("content.enchant", ()),
    ("content.events", ()),
    ("content.exploration", ("data",)),
    ("content.factions", ("data",)),
    ("content.fishing", ()),
    ("content.gameplay_rules", ()),
    ("content.index", ("data",)),
    ("content.instance_cmds", ("C", "db", "T", "player_final_stats", "resolve_drop", "ACT_TICK")),
    ("content.item_templates", ("content",)),
    ("content.maps", ("data", "db")),
    ("content.misc_cmds", ("db",)),
    ("content.mounts", ("data",)),
    ("content.party", ("db", "c", "content", "panel_stats")),
    ("content.pets", ()),
    ("content.player_cmds", ("db", "content", "combat")),
    ("content.player_events", ("log", "db", "c")),
    ("content.pois", ()),
    ("content.position", ("data",)),
    ("content.profession", ("db", "content", "timed", "log", "expand_pool")),
    ("content.profession_quests", ("db", "content", "texts", "level_up", "stat_bonus")),
    ("content.quests_flow", ("db", "c", "level_up", "stat_bonus_fn", "grant_reward_fn",
                             "quests_svc")),
    ("content.reward", ("db", "content", "log", "tlog", "levelup", "stat_bonus", "key_to_id")),
    ("content.settlement", ("db", "content", "player_final_stats", "race_stats", "resolve_drop",
                            "rule_fire", "stat_bonus")),
    ("content.shop_stock", ()),
    ("content.social_cmds", ("db", "content")),
    ("content.social_guild", ("db", "config", "store_social")),
    ("content.social_pet", ("db", "content", "quality")),
    ("content.social_stall", ("db", "maps", "house_levels", "quality", "econ", "store_social")),
    ("content.stats", ()),
    ("content.talk_actions", ("db", "grant_reward")),
    ("content.timed_events", ()),
    ("content.title_conds", ()),
    ("content.tlog_replay", ("bridge",)),
    ("content.travel", ("db", "c")),
    ("content.wild", ()),
    ("content.world_cmds", ("db", "content", "check_action_keys")),
    ("content.world_event_templates", ("content",)),
    ("content.worlds", ()),
    ("content.flow.instance_battle", ("db", "db_update")),
    ("content.flow.tower_progress", ("db",)),
    ("content.flow.weekly_progress", ("db", "grant_reward")),
)


def _surface_item(item):
    """把 `_PKG_SURFACE` 的一项取成真对象（模块对象 / 属性值）。取不到 → 原样上抛。"""
    if item is C:
        return C
    if isinstance(item, tuple):
        mod_name, attr = item
        return getattr(importlib.import_module(mod_name), attr)
    return importlib.import_module(item)


def bind_host(**inject):
    """**包侧唯一注入扇出**（引擎在 import 包命令模块之前调用；各被调方 `bind_host` 幂等）。

    :param inject: 宿主注入对象。引擎（`load_package(root, inject=…)`）原样转发，键由包解释：

        * 真·宿主能力（四类）：`db_path` / `clock` / `flush_log` / `lock` / `db`（存档层）·
          `log` / `tlog`（观测口 + 各模块日志槽）· `grant_reward`（发奖）
        * 其余键原样并入扇出 payload（宿主注入优先，与包内既有「注入优先」口径一致）

    **不吞异常**：任何被调模块 import 失败 / `bind_host` 抛错，都原样上抛（拒绝静默空跑）。
    """
    # ---- ① 存档层能力：库路径 / 时钟 / 日志 sink（`handles.bind` 的形参面）----
    from .persistence import handles as _handles
    _handles.bind(**{k: inject[k] for k in _HANDLE_KEYS if k in inject})

    # ---- ② 观测口：日志 / 流水 sink（包内唯一取用口）----
    from . import obs as _obs
    _obs.bind(log=inject.get("log"), tlog=inject.get("tlog"))

    # ---- ③ 组装扇出 payload = 包内自解析面 + 宿主注入（宿主注入优先）----
    payload = {key: _surface_item(item) for key, item in _PKG_SURFACE.items()}
    for key, value in inject.items():
        if key in _HANDLE_KEYS:
            continue          # 已由 ① 归口（语义是 `handles.bind` 的形参，不是模块/对象面）
        if value is not None:
            payload[key] = value
    # 发奖：宿主没给 → 包内真源（`content/reward.py::grant_reward`）
    if payload.get("grant_reward") is None:
        payload["grant_reward"] = _surface_item(("content.reward", "grant_reward"))
    if "grant_reward_fn" not in payload:
        payload["grant_reward_fn"] = payload["grant_reward"]

    # ---- ④ 逐个模块扇出（穷举表；只喂它认的键）----
    for mod_name, keys in _BIND_SLOTS:
        mod = importlib.import_module(mod_name)                        # import 失败 → 上抛
        fn = getattr(mod, "bind_host", None)
        if not callable(fn):
            raise RuntimeError("content.facade：扇出表里的 %s 没有 bind_host（表过期了？）"
                               % mod_name)
        fn(**{k: payload[k] for k in keys if k in payload})             # 抛错 → 上抛
