# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— 称号获得条件注册表（B13-L4，2026-09-14）。

真源：游戏仓 `game/core/title_conds.py`（350 行 / v98.3 起）。本模块 = 那份文件的
**实现本体**（逐字搬：50 个称号条件注册 + `TitleCtx` + `check_pro_title` + 两个辅助
`_side_done` / `_has_flag`）。宿主 `game/core/title_conds.py` 现在只剩「加载包 + 同名单
re-export」（`CONDITIONS` / `register` / `TitleCtx` / `check_pro_title` / 各 `_t_*`），
消费者 `game/commands/economy.py:26` 与 `game/core/stat_bonus.py:87` 的 import 点零改动。

正文改动面（只有两类，替换表见 `overnight/w1213_b13l4_port.py`，每条断言出现次数）
--------------------------------------------------------------------------------------
1. 宿主取件 → 惰性替身：`TitleCtx._db()` 里函数内 `from .. import db` → 模块级
   `db = _HostMod("db")`（`_db()` 仍返回该句柄，调用点 `ctx._db().xxx()` 一行未改）；
   函数内 `from .. import content as C`（rep_honor / rep_legend / hidden 三处）删除；
   `_has_flag` 的 `from .. import content as _C` → ★ W4 切包内读口 `content/wild.py`（原 `_C = C`）。
2. 读点（B14-2，L7 线已切三名包内门面）：`C.MAPS` → `content/catalog_space.py:MAPS` ·
   `C.NPCS` / `C.HIDDEN_NPCS` → `content/catalog_quests.py`（门禁逐名 OK · 不等 0，含键序；
   MAPS 实测保留 `hidden`/`type`，NPCS=362 / HIDDEN_NPCS=22 与宿主同值同序 —— B13-L4 时期
   「maps 域是投影 / npcs 域是超集」的判断已随 B14-A/C 重造失效）。
   ★ W4（2026-09-14）：原「仍走宿主句柄」的两名已切门面 —— `C.HIDDEN_MAP_UNLOCK` →
   `content/catalog_b143.py`（B14-3 建 `game_config.maps` 组，门禁含键序不等 0）；
   `C.ALL_WILD` → 包内读口 `content/wild.py`（B13-L2 已落地；派生口径与宿主 `C.ALL_WILD`
   一致）。仍走宿主句柄的只剩**函数**：`C.faction_reputation_tier`（`core/factions.py`）。

真源原文头注（逐字保留）
------------------------
    奥兰迪亚·余烬纪年核心层 - title_conds.py（v98.3：称号获得条件注册表）
    
    消灭 commands/economy.py _earned_titles() 里的 if-elif 硬编码：
    称号数据只声明 id，判定统一走本模块注册表。
    
    扩展方式：
    - 加称号：data/titles.py 加一条 dict（id 唯一）+ 本文件 register 一个条件函数
    - 函数签名：fn(ctx) -> bool
    - ctx 为 TitleCtx（group_id/qq_id/player/stats/rep/quests/hooks）"""

from __future__ import annotations

import importlib
import sys


# ============================================================
# 宿主替身口（**惰性**：属性访问时才解析宿主模块；绝不 import 宿主模块树、绝不静默空跑）
# 真源写法 → 包内替身：`from .. import content as C` → `C = _HostMod("content")`；
# `from .. import db` → `db = _HostMod("db")`。函数内那几行 import 已按原位置删除，
# 所有调用点 `C.xxx` / `db.xxx` **一行未改**（与 `content/world_cmds.py` / `talk_actions.py` 同款）。
# ============================================================
_HOST_PKG = "data.plugins.dragonfall.game"      # 运行时（main.py 的模块路径）
_HOST_PKG_FALLBACK = "game"                     # 测试/工具按 `game.xxx` 直接 import 时
_INJECTED = {}


def bind_host(**objs):
    """宿主薄壳 import 期注入（幂等）——键 = `_HostMod` 的模块名（`content` / `db`）。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _host_module(name: str):
    """取宿主子模块（`name` 为空 = 宿主 `game` 包本身，真源 `from .. import X` 那一类）。"""
    if name in _INJECTED:
        return _INJECTED[name]
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        full = prefix if not name else "%s.%s" % (prefix, name)
        m = sys.modules.get(full)
        if m is not None:
            return m
    last = None
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        try:
            return importlib.import_module(prefix if not name else "%s.%s" % (prefix, name))
        except Exception as exc:                # noqa: BLE001
            last = exc
    raise RuntimeError("%s：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (__name__, name, last))


def _host_attr(mod: str, attr: str):
    """宿主模块属性 —— 真源「函数内 `from ..<mod> import <attr>`」的同义替身（调用时解析）。"""
    m = _host_module(mod)
    try:
        return getattr(m, attr)
    except AttributeError:
        for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
            try:
                return importlib.import_module("%s.%s" % (
                    prefix if not mod else "%s.%s" % (prefix, mod), attr))
            except Exception:                   # noqa: BLE001
                continue
        raise


class _HostMod:
    """宿主模块替身（`C` / `db`）——`C.xxx` / `db.xxx` 正文一字未改，属性访问时解析。"""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return getattr(_host_module(self._name), attr)


C = _HostMod("content")     # 真源 `from .. import content as C`
from ._pkgref import DB as db

# B14-2（L7 线）：数据名读点切包内门面 —— 原 `C.<名>` / `_C.<名>` 直取换成门面同名绑定
from .catalog_quests import HIDDEN_NPCS, NPCS   # 真源 `C.HIDDEN_NPCS` / `C.NPCS`
from .catalog_space import MAPS                 # 真源 `C.MAPS`
# ★ W4（2026-09-14）：缺口两名切包内 —— `HIDDEN_MAP_UNLOCK` → `catalog_b143`；`ALL_WILD` → `wild`
from . import catalog_b143 as _cb143            # 真源 `C.HIDDEN_MAP_UNLOCK`（`game/data/maps.py:4343`）
from . import wild as _wild                     # 真源 `C.ALL_WILD`（`core/wild.py:26` 派生式）

import re

CONDITIONS = {}


def register(tid):
    """条件注册装饰器。"""
    def deco(fn):
        CONDITIONS[tid] = fn
        return fn
    return deco


class TitleCtx:
    """称号条件判定上下文。hooks 注入命令层专属能力（has_enhanced/visited_maps）。"""

    def __init__(self, group_id, qq_id, player, stats, rep, quests, hooks=None):
        self.group_id = group_id
        self.qq_id = qq_id
        self._focus = player or {}
        self.stats = stats or {}
        self.rep = rep or {}
        self.quests = quests or {}
        self.hooks = hooks or {}

    def _db(self):
        # B13-L4：真源「函数内 from .. import db」→ 宿主 db 模块本体
        # （`_host_module("db")` 返回的**就是宿主 db 模块对象**：类型/身份与真源一致；
        #   调用点 `ctx._db().xxx()` 一字未改）
        return db    # B1：包内直取（`content.persistence`；原 `_host_module("db")`）

    def hook(self, name, *args, **kwargs):
        fn = self.hooks.get(name)
        if fn:
            return fn(*args, **kwargs)
        return None


# ================= 条件实现 =================

@register("novice")
def _t_novice(ctx):
    return True


@register("lv10")
def _t_lv10(ctx):
    return ctx._focus.get("level", 0) >= 10


@register("lv20")
def _t_lv20(ctx):
    return ctx._focus.get("level", 0) >= 20


@register("lv30")
def _t_lv30(ctx):
    return ctx._focus.get("level", 0) >= 30


@register("kill10")
def _t_kill10(ctx):
    return ctx.stats.get("kills", 0) >= 10


@register("kill100")
def _t_kill100(ctx):
    return ctx.stats.get("kills", 0) >= 100


@register("kill500")
def _t_kill500(ctx):
    return ctx.stats.get("kills", 0) >= 500


@register("elite5")
def _t_elite5(ctx):
    return ctx.stats.get("elite_kills", 0) >= 5


@register("boss1")
def _t_boss1(ctx):
    return ctx.stats.get("boss_kills", 0) >= 1


@register("boss3")
def _t_boss3(ctx):
    return ctx.stats.get("boss_kills", 0) >= 3


@register("rep_honor")
def _t_rep_honor(ctx):
    return any(C.faction_reputation_tier(v) in ("崇敬", "崇拜") for v in ctx.rep.values())


@register("rep_legend")
def _t_rep_legend(ctx):
    return any(C.faction_reputation_tier(v) == "崇拜" for v in ctx.rep.values())


@register("quest10")
def _t_quest10(ctx):
    return len(ctx.quests.get("completed_main", [])) >= 10


@register("wealthy")
def _t_wealthy(ctx):
    return ctx._focus.get("gold", 0) >= 5000


@register("explorer")
def _t_explorer(ctx):
    return ctx._db().get_visited_count(ctx.group_id, ctx.qq_id) >= 10


@register("fish10")
def _t_fish10(ctx):
    return ctx._db().get_fishing_total(ctx.group_id, ctx.qq_id) >= 10


@register("enhance5")
def _t_enhance5(ctx):
    return bool(ctx.hook("has_enhanced", ctx.group_id, ctx.qq_id, 5))


@register("enhance9")
def _t_enhance9(ctx):
    return bool(ctx.hook("has_enhanced", ctx.group_id, ctx.qq_id, 9))


@register("hidden")
def _t_hidden(ctx):
    # v124 修复：mithril_hall 已删除（v104 P2 清理死条目）→ 改判真实隐藏区域，
    # 与成就 ach_mythril（hidden_area≥1，achievement_conds.py 已修复）同语义：
    # 到访任一隐藏区域即达成（lost_library / ember_corridor，或 hidden=True 地图）
    visited = ctx.hook("visited_maps", ctx.group_id, ctx.qq_id) or []
    hidden = set(_cb143.HIDDEN_MAP_UNLOCK or {})
    for m in (MAPS or []):
        if m.get("hidden") or m.get("type") == "隐藏区域":
            hidden.add(m["id"])
    if not hidden:
        return False
    return any(v in hidden for v in visited)


@register("final")
def _t_final(ctx):
    return ctx.quests.get("main_quest") is None and len(ctx.quests.get("completed_main", [])) >= 10


@register("iron_adventurer")
def _t_iron_adventurer(ctx):
    """铁牌冒险者（v140 q1_6 主线奖励）：完成第一杯麦酒（q1_6 在 completed_main）。"""
    return "q1_6" in (ctx.quests.get("completed_main") or [])


@register("fish_king")
def _t_fish_king(ctx):
    return ctx._db().get_fish_king(ctx.group_id, ctx.qq_id) >= 1


@register("pvp_hero")
def _t_pvp_hero(ctx):
    # 数据源：荣誉商店兑换勋章（26 章 3.3，combat.py _honor_buy 写
    # event_state key = f"honor_{reward['title_id']}_{qq}"，honor_shop.py
    # 第 1 件商品 title_id="medal" → 键 honor_medal_{qq}，与本行读取键一致）
    return int(ctx._db().get_event_state(f"honor_medal_{ctx.qq_id}") or 0) >= 1


# ================= v124 剧情线称号（side 完成判定）=================
def _side_done(ctx, sid):
    """支线完成 = quests.side[sid].status == done"""
    return (ctx.quests.get("side") or {}).get(sid, {}).get("status") == "done"


def _has_flag(ctx, flag):
    """任意 NPC flag 桶含指定 flag（扫描全桶，同 wild.py unlock_met flag: 先例）"""
    _AW = _wild.ALL_WILD                # 真源 `from .. import content as _C` 的 `_C.ALL_WILD`（★ W4 切包内读口）
    db = ctx._db()
    for nid in list(NPCS.keys()) + list(_AW.keys()) + list(HIDDEN_NPCS.keys()):
        if flag in db.get_talk_flags(ctx.group_id, ctx.qq_id, nid):
            return True
    return False


@register("north_benefactor")
def _t_north_benefactor(ctx):
    return _side_done(ctx, "s18") and _has_flag(ctx, "s18_branch_light")


@register("nightwalker")
def _t_nightwalker(ctx):
    return _side_done(ctx, "s18") and _has_flag(ctx, "s18_branch_dark")


@register("guifan_seal")
def _t_guifan_seal(ctx):
    return _side_done(ctx, "s27")


@register("dragon_warden")
def _t_dragon_warden(ctx):
    return _side_done(ctx, "s33")


@register("gourmet")
def _t_gourmet(ctx):
    return _side_done(ctx, "s56")


@register("herb_friend")
def _t_herb_friend(ctx):
    return _side_done(ctx, "s60")


@register("treasure_hunter")
def _t_treasure_hunter(ctx):
    return _side_done(ctx, "s64")


@register("furry_friend")
def _t_furry_friend(ctx):
    return _side_done(ctx, "s69")


@register("merchant_friend")
def _t_merchant_friend(ctx):
    return _side_done(ctx, "s74")


@register("just_enforcer")
def _t_just_enforcer(ctx):
    return _side_done(ctx, "s78") and _has_flag(ctx, "s78_branch_justice")


@register("shadow_friend")
def _t_shadow_friend(ctx):
    return _side_done(ctx, "s78") and _has_flag(ctx, "s78_branch_mercy")


@register("dusk_detective")
def _t_dusk_detective(ctx):
    return _side_done(ctx, "s79")


@register("peacemaker")
def _t_peacemaker(ctx):
    return _side_done(ctx, "s84")


@register("guide")
def _t_guide(ctx):
    return _side_done(ctx, "s89")


@register("night_rain")
def _t_night_rain(ctx):
    return _side_done(ctx, "hq5_3")


@register("goose_messenger")
def _t_goose_messenger(ctx):
    return _side_done(ctx, "hq7_3")


@register("forge_son")
def _t_forge_son(ctx):
    return _side_done(ctx, "hq8_4")


@register("graveyard_warden")
def _t_graveyard_warden(ctx):
    return _side_done(ctx, "hq6_3")


@register("fishing_legend")
def _t_fishing_legend(ctx):
    return _side_done(ctx, "s95")


@register("late_messenger")
def _t_late_messenger(ctx):
    return _side_done(ctx, "s100")


@register("season_gardener")
def _t_season_gardener(ctx):
    return _side_done(ctx, "s106")


def check_pro_title(tid: str, ctx) -> bool:
    """副业称号：pro_<prof><lv>（如 pro_gather3）→ 副业等级达标。"""
    m = re.match(r"^pro_([a-z]+)(\d+)$", tid)
    if not m:
        return False
    prof_key, need_lv = m.group(1), int(m.group(2))
    if prof_key in ("gather", "mining", "fishing", "alchemy", "craft", "cooking"):
        return ctx._db().get_prof_level(ctx.group_id, ctx.qq_id, prof_key) >= need_lv
    return False


# ================= v140 波3.6：资源向称号条件（方案 3.9，6 个） =================
# 条件口径与 achievements.py prof_count 一致（stats 计数），效果消费点见 titles.py effect 字段

@register("res_forge_master")
def _t_res_forge_master(ctx):
    """锻造大师（锻造体力-1）：锻造 ≥100 件装备。"""
    return ctx.stats.get("craft_count", 0) >= 100


@register("res_gather_expert")
def _t_res_gather_expert(ctx):
    """采集高手（采集品质+10%）：累计采集 ≥500 次。"""
    return ctx.stats.get("gather_count", 0) >= 500


@register("res_treasure_hunter")
def _t_res_treasure_hunter(ctx):
    """寻宝猎人（宝藏发现率+2%）：开启 ≥50 个宝箱。"""
    return ctx.stats.get("chests_opened", 0) >= 50


@register("res_fishing_legend")
def _t_res_fishing_legend(ctx):
    """垂钓传说·资源（稀有鱼+5%）：累计垂钓 ≥500 次。"""
    return ctx.stats.get("fish_count", 0) >= 500


@register("res_alchemy_master")
def _t_res_alchemy_master(ctx):
    """炼金大师（炼金产物+1）：累计炼金 ≥50 次。"""
    return ctx.stats.get("alchemy_count", 0) >= 50


@register("res_food_king")
def _t_res_food_king(ctx):
    """美食之王（食物效果+10%）：累计烹饪 ≥50 次。"""
    return ctx.stats.get("cook_count", 0) >= 50
