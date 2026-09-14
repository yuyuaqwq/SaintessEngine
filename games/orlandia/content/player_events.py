# -*- coding: utf-8 -*-
"""《奥兰迪亚》包内**玩家级事件总线 + 订阅方**（`content/player_events.py`）
—— 逐字搬自游戏仓 `game/services/player_event_bus.py`（71 行，L3-P1）
   + `game/services/player_event_subscribers.py`（170 行，L3-P2）。

★ B12-L4（2026-09-14）：宿主两文件薄壳化 =「加载包 + 注入宿主替身 + 同名 re-export」，
调用点与调用签名**一字不变**：
    命令层 `game/commands/instance.py:2520-2521/2998-2999`（`fire` + `import 订阅方` 触发注册）
    包内   `content/combat_cmds.py:2296-2304/2615-2628`（`_host_attr("services.player_event_bus","fire")`）
    测试   `tests/test_player_event_bus.py:16`（EVENTS/register/fire/clear_registry）·
           `tests/test_l3_player_events.py:18-19/100`（fire + 订阅方 + `_sub_levelup`）

只改两类东西（与 `content/quests_flow.py` / `content/world_cmds.py` 同款）
----------------------------------------------------------------------
| 真源写法 | 包内写法 | 说明 |
|---|---|---|
| 总线 `_bus = EventBus(EVENTS, logger=LOG)`（宿主 `log_setup.LOG`） | `_get_bus()` 惰性建总线，logger 由注入给出 | 保证宿主薄壳**先注入 logger 再首次使用**；未注入 → 引擎门面 logger（同默认值） |
| 订阅方模块级 `from .. import db` / `from .. import content as C` | 模块级惰性代理 `db`；`C.HIDDEN_MONSTERS` → **包内门面** `content/catalog_b143.py`（W4，2026-09-14） | 正文 `db.xxx` 一字未改；`HIDDEN_MONSTERS` 门禁逐键逐值（含键序）相等 ⇒ 取值来源换、行为不变，`C` 替身随之删除 |
| 订阅方模块级 `from ..core.achievements import check_achievements` 等 8 个宿主函数 | 同名 `_HostFn("core.achievements","check_achievements")` | **调用时解析**（别线并行搬模块期间不会瞬时 ImportError，见 BRIEF §3-B-5） |

⚠️ 结构差异（唯一一处，**行为等价**）：真源 `player_event_subscribers.py` 末尾在 import 期自动
   `ensure_registered()`；包内**不自动注册** —— 改由宿主薄壳 `game/services/player_event_subscribers.py`
   import 时「先 `bind_host(log=…)` 再 `ensure_registered()`」（注册时机仍是「该模块被 import 时」，
   与真源逐字同义；同时保证总线 logger 来自宿主而非回退值）。

⚠️ 缺口（报告同步登记）：
  · `db.get_event_state` / `db.set_event_state`（隐藏怪击杀累计）= 存档层原语 ⇒ 留宿主。
  · 订阅方体内 8 个宿主函数**均属别线正在搬的模块**（`core.achievements`/`core.stat_bonus`/
    `core.wild_king`=B13-L2 · `services.guild`/`services.quests_flow`/`services.tower_progress`/
    `services.weekly_progress`=B12-L5 · `content_rules.gameplay` 升级结算）⇒ 本线一律走宿主句柄，
    待对应线落地后切包内直取。
  · `C.HIDDEN_MONSTERS`（隐藏怪 id 集）→ ★ W4（2026-09-14）已切包内门面
    `content/catalog_b143.py:HIDDEN_MONSTERS`（`game_config.hidden_monsters` 组），逐键逐值+键序相等。

真源模块 docstring（逐字保留）
------------------------------
'''
奥兰迪亚·余烬纪年 服务层 - player_event_bus（L3 玩家级事件总线，v181 L3-P1）

战斗之外、玩家账号级的领域事件同步总线（DDD 领域事件语义，非 QFramework EventSystem）：
一次战斗胜利/失败/击杀是「已经发生的事实」，发布时订阅方按注册顺序反应并回填结算文案。
战斗引擎（saintess_engine）零游戏知识、不 import 本文件；fire 入口收拢在命令层/结算层编排点。

设计文档：docs/DESIGN_v181_L3_player_event_bus.md（权威思想）
字段级任务书：docs/REFACTOR_v181_L3_P0_task.md（ctx schema/订阅注册表/行序对照，P0 侦察修订）

三层事件全景：
- L1 战斗内效果总线 saintess_engine/effect_triggers.py fire() 23 时机（actor 级，N8 已落地）
- L2 战斗级观察者 battle.on_event 注入钩子（N5b4-5E/5c 已落地）
- L3 本文件：玩家级（任务/成就/公会/野王/塔卫），一次战斗只几类事件

总线规则（北极星对齐，全部为显式决策）：
- EVENTS 起步全集固定元组；register 未知事件 raise ValueError（防拼写静默失效）；
  fire 未知事件 log warning 后不 raise（返回当前行收集器；ctx 未预置 lines 时即 []）。
- 订阅方按注册顺序执行；段间空行规则由 blank_line 参数统一实现（对齐原手写
  `if lines: lines.append("")` 语义）：blank=True 且上一行非空才补一个 ""。
- 异常订阅不阻断（log + continue，对齐各命令层 try/except 宽容铁律）；
  返回 None 与 [] 等价（无行=跳过）。
- ctx 是唯一上下文（见 P0 任务书 §4）：订阅方可原地改 dict（ctx["player"] 重绑等），
  总线不解释 ctx["side_effects"]（非文案副作用，fire 返回后由命令层消费）。
- 显式 import 触发注册（game/services/player_event_subscribers.py），不做 import 魔法。

【骨架归属（2026-09-11，M3）】总线的**机制**（注册表 / 注册序执行 / 段落空行 /
未知事件策略 / 异常容忍）来自框架 `saintess_engine.events.EventBus`；本文件只留
**本游戏的内容**：事件集 `EVENTS`、对外 API 名、日志器。

'''
"""

from __future__ import annotations

import sys

from saintess_engine.events import EventBus

# ★ W4（2026-09-14）：`C.HIDDEN_MONSTERS` → 包内门面（真源 `game/data/hidden_monsters.py:18`）
from . import catalog_b143 as _cat_b143

# ============================================================
# ① 宿主替身口（注入优先 → sys.modules → importlib；**绝不静默空跑**）
# ============================================================
_HOST_PKG = "data.plugins.dragonfall.game"      # 运行时（main.py 的模块路径）
_HOST_PKG_FALLBACK = "game"                     # 测试/工具按 `game.xxx` 直接 import 时
_INJECTED = {}


def bind_host(**objs):
    """宿主薄壳 import 期注入（幂等）——键 = `_HostMod` 的模块名（`db` / `content`）/ `log`。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _host_module(name: str):
    """取宿主子模块（`name` 为空 = 宿主 `game` 包本身，真源 `from .. import X` 那一类）。"""
    if name in _INJECTED:
        return _INJECTED[name]
    import importlib
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
    raise RuntimeError("player_events：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (name, last))


def _host_attr(mod: str, attr: str):
    """宿主模块属性 —— 真源「模块级 `from ..<mod> import <attr>`」的同义替身（调用时解析）。"""
    return getattr(_host_module(mod), attr)


class _HostMod:
    """宿主模块替身（`db` / `C`）——`db.xxx` / `C.xxx` 正文一字未改，属性访问时解析。"""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return _host_attr(self._name, attr)


class _HostFn:
    """宿主函数替身 —— 真源模块级 `from ..<mod> import <fn>` 的同义物（调用时解析）。"""

    def __init__(self, mod, attr):
        self._mod, self._attr = mod, attr

    def __call__(self, *a, **k):
        return _host_attr(self._mod, self._attr)(*a, **k)

    def __repr__(self):
        return "<host fn %s.%s>" % (self._mod, self._attr)


db = _HostMod("db")

# 订阅方真源模块级 import 的 8 个宿主函数（逐名同义替身；调用时解析）
check_player_level_up = _HostFn("content_rules.gameplay", "check_player_level_up")
check_achievements = _HostFn("core.achievements", "check_achievements")
stat_bonus = _HostFn("core.stat_bonus", "stat_bonus")
wild_king_on_kill = _HostFn("core.wild_king", "wild_king_on_kill")
guild_kill_progress = _HostFn("services.guild", "guild_kill_progress")
quest_kill_progress = _HostFn("services.quests_flow", "quest_kill_progress")
tower_guard_on_kill = _HostFn("services.tower_progress", "tower_guard_on_kill")
weekly_bump_kill = _HostFn("services.weekly_progress", "weekly_bump_kill")


# ============================================================
# ② 总线（真源 `game/services/player_event_bus.py` 逐字；仅 logger/建实例一处改动）
# ============================================================

# 起步全集（**本游戏的事件名**；框架不预设任何事件名）
# 扩展靠 data/声明不靠加 if——但事件本体先枚举，防止拼写漂移
EVENTS = ("battle_victory", "battle_defeat", "monster_killed")


def _logger():
    """宿主 logger（真源 `from ..log_setup import LOG`；注入优先）——未注入 → None（引擎门面 logger，同默认）。"""
    if "log" in _INJECTED:
        return _INJECTED["log"]
    try:
        return _host_attr("log_setup", "LOG")
    except Exception:                          # noqa: BLE001
        return None


_bus = None


def _get_bus():
    """惰性建总线（首次使用时）——策略与改造前的手写实现逐条一致（正是框架的默认值）：
    register 未知事件 → raise；fire 未知事件 → warn 后返回行收集器；订阅方异常 → 跳过。"""
    global _bus
    if _bus is None:
        _bus = EventBus(EVENTS, logger=_logger())
    return _bus


def register(event: str, subscriber, blank_line: bool = True) -> None:
    """注册订阅方。

    subscriber(ctx: dict) -> list[str] | None：接收 ctx，返回要回填进结算日志的行组
    （不含段落分隔空行——由 blank_line 统一处理）。返回 None/[] = 本段无行。
    同事件重复注册 = 追加（各模块 import 一次天然单次，不查重）。
    """
    _get_bus().on(event, subscriber, blank_line=blank_line)


def fire(event: str, ctx: dict) -> list:
    """发布事件：按注册顺序执行订阅方，收集回填行（含 blank 空行），返回行列表。

    ctx 至少含 P0 任务书 §4 固定字段（event 自动补，其余由 fire 点构造）；
    ctx.setdefault("lines", []) 作为行收集器（若调用方预置内容则在其后追加）。
    订阅方抛异常：log warning + 跳过该订阅方（不阻断后续，容错铁律）。
    """
    return _get_bus().fire(event, ctx)


def clear_registry() -> None:
    """清空全部订阅（仅测试用）。生产代码不得调用。"""
    _get_bus().clear()


# ============================================================
# ③ 订阅方（真源 `game/services/player_event_subscribers.py` 逐字；模块级 import 区换成上面替身）
# ============================================================
_registered = False


# ---------------------------------------------------------------------------
# 订阅方 1：公会每日击杀任务（每场胜利 +1）——原 combat L2034-2055 内联段
# ---------------------------------------------------------------------------
def _sub_guild_daily(ctx):
    g = db.guild_get_by_member(ctx["qq_id"])
    if not g:
        return []
    lines, _rewarded = guild_kill_progress(ctx["group_id"], ctx["qq_id"], g)
    return lines


# ---------------------------------------------------------------------------
# 订阅方 2：升级（title_bonus 注入 + check_player_level_up）——原 combat L2056-2063
# 经验落库后重读 player（v105 M18 P2：rule_fire 彩蛋金币已在库）→ 注入 stat_bonus
# → 升级检查 → 升级时写回 db 字段并重绑 ctx["player"]（后续订阅方拿最新 dict）。
# 🔴 kind 守卫：仅 field 升级——副本战斗内不做升级检查（_instance_kill_reward
# docstring：check_player_level_up 回满 hp 会破坏连续战斗节奏，经验攒到出副本统一
# 结算）；世界Boss 参与奖励现状也不升级。任务达标发奖内部的升级（settle_daily_quest
# 单点）不在此列——那属发奖机制，全局一致。
# ---------------------------------------------------------------------------
def _sub_levelup(ctx):
    if ctx.get("kind") != "field":
        return []
    player = db.get_player(ctx["group_id"], ctx["qq_id"]) or {}
    player["_title_bonus"] = stat_bonus(ctx["group_id"], ctx["qq_id"], player)
    lv_logs, player2 = check_player_level_up(ctx["group_id"], ctx["qq_id"], player)
    if not lv_logs:
        return []
    ctx["player"] = player2
    db.update_player(ctx["group_id"], ctx["qq_id"],
                     level=player2["level"], exp=player2["exp"],
                     hp=player2["hp"], mp=player2["mp"],
                     max_hp=player2["max_hp"], max_mp=player2["max_mp"],
                     skills=player2["skills"],
                     attr_pts=player2.get("attr_pts", 0),
                     skill_points=player2.get("skill_points", 0),
                     learned_skills=player2.get("learned_skills", []))
    return lv_logs


# ---------------------------------------------------------------------------
# 订阅方 3：任务（主线/每日/支线）+ 周常——原 combat L2064-2075 quest 循环
# （_update_quests 壳 = quest_kill_progress + weekly_bump_kill 每只怪）
# 全 kind 推（语义决策 09-09：任何击杀都算数；quest_kill_progress 内部按怪属性/名
# 匹配，instance/worldboss 的怪名字对得上就推——取代副本 _instance_main_kill_progress）
# ---------------------------------------------------------------------------
def _sub_quests(ctx):
    lines = []
    for k in ctx.get("killed") or []:
        lines += (quest_kill_progress(ctx["group_id"], ctx["qq_id"], k) or [])
        lines += (weekly_bump_kill(ctx["group_id"], ctx["qq_id"], k) or [])
    return lines


# ---------------------------------------------------------------------------
# 订阅方 4：野王击杀（主怪 id b_guard_ 前缀）——原 combat L2076-2089
# 返回行组 + side_effects 广播（命令层 fire 点负责 _broadcast）
# ---------------------------------------------------------------------------
def _sub_wild_king(ctx):
    monster = ctx.get("monster") or {}
    if not (monster and str(monster.get("id", "")).startswith("b_guard_")):
        return []
    _wk_lines = wild_king_on_kill(ctx["group_id"], ctx["qq_id"], monster)
    if _wk_lines:
        ctx["side_effects"].append({"type": "broadcast", "text": "\n".join(_wk_lines)})
    return _wk_lines


# ---------------------------------------------------------------------------
# 订阅方 5：塔卫击杀（主怪 id tower_ 前缀）——原 combat L2090-2099
# ---------------------------------------------------------------------------
def _sub_tower_guard(ctx):
    monster = ctx.get("monster") or {}
    if not (monster and str(monster.get("id", "")).startswith("tower_")):
        return []
    return tower_guard_on_kill(ctx["group_id"], ctx["qq_id"], monster)


# ---------------------------------------------------------------------------
# 订阅方 6：成就（按 kind 组装 extra）——field 原 combat L2100-2118 / instance 原
# _instance_victory L3187(inst_id+flawless) / worldboss 原 _worldboss_act L2432
# kind 分支只此一处（P0 任务书 §9）：场景决定 extra，解锁判定全局一致。
# ---------------------------------------------------------------------------
def _ach_lines(achs) -> list:
    lines = []
    for a in achs or []:
        rw_txt = f"\n      🎁 {a['_reward_txt']}" if a.get("_reward_txt") else ""
        lines.append(f"🏆 成就解锁：{a['name']}！({a['desc']}){rw_txt}")
    return lines


def _sub_achievements(ctx):
    kind = ctx.get("kind", "field")
    if kind == "instance":
        meta = ctx.get("meta") or {}
        extra = {"inst_id": meta.get("inst_id")}
        if meta.get("flawless"):
            extra["flawless"] = True
        return _ach_lines(check_achievements(ctx["group_id"], ctx["qq_id"],
                                             ctx.get("player"), extra))
    if kind == "worldboss":
        return _ach_lines(check_achievements(ctx["group_id"], ctx["qq_id"],
                                             ctx.get("player"), {"worldboss": 1}))
    # field：v87 隐藏怪击杀累计（成就·传说猎人）
    monster = ctx.get("monster") or {}
    hm_defeated = set()
    try:
        _hm_st = db.get_event_state(f"hm_defeated_{ctx['group_id']}_{ctx['qq_id']}")
        if _hm_st:
            hm_defeated = set(_hm_st.split(",")) if _hm_st else set()
        if monster.get("id") in _cat_b143.HIDDEN_MONSTERS:
            hm_defeated.add(monster["id"])
            db.set_event_state(f"hm_defeated_{ctx['group_id']}_{ctx['qq_id']}", ",".join(sorted(hm_defeated)))
    except Exception:
        pass
    return _ach_lines(check_achievements(ctx["group_id"], ctx["qq_id"], ctx.get("player"),
                                         {"defeated_hidden_monsters": hm_defeated}))


def ensure_registered() -> None:
    """注册 6 个 field 订阅方（幂等：模块只注册一次）。

    命令层 fire 点显式调用本函数（或 import 本模块触发底部调用）。
    """
    global _registered
    if _registered:
        return
    # 注册序 = 原壳行序（回填顺序对照表 §5/§6）：
    # guild(无空行) → levelup → quests+weekly → wild_king → tower_guard → achievements
    register("battle_victory", _sub_guild_daily, blank_line=False)
    register("battle_victory", _sub_levelup, blank_line=True)
    register("battle_victory", _sub_quests, blank_line=True)
    register("battle_victory", _sub_wild_king, blank_line=True)
    register("battle_victory", _sub_tower_guard, blank_line=True)
    register("battle_victory", _sub_achievements, blank_line=True)
    _registered = True
