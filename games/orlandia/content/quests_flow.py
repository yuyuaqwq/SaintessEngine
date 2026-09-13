# -*- coding: utf-8 -*-
"""包内任务流域（`content/quests_flow.py`）—— 真源 `game/services/quests_flow.py`（831 行）**逐字端口**。

★ B9 L5（2026-09-13）：宿主 `game/services/quests_flow.py` 薄壳化 = **只留「加载包 + 注入宿主替身 +
同名 re-export」**，命令/战斗/经济三层的调用点与调用签名**一字不变**（`world.py:1935/2289/2295/2301/
2681/2733/3379/3452/3458/3758/3764/3770/3776/3889/3895`、`combat.py`、`economy.py`、
`services/player_event_subscribers.py:25`、`tests/test_commands_world.py:16`、`tests/test_v104_quests.py:21`）。

只改两类东西（与 `content/flow/weekly_progress.py` / `content/talk_actions.py` 同款）
------------------------------------------------------------------------------------------
| 真源写法 | 包内写法 | 说明 |
|---|---|---|
| 函数体内 `from .. import db` + `db.xxx(...)` | 模块级 `db` = **惰性宿主代理** `_HostDB` | 正文里 `db.xxx(...)` **一行未改**；宿主由 `bind_host(db)` 注入，或按 `sys.modules` 找**已加载**的宿主模块（绝不 import，防在包侧另起一份宿主模块树） |
| 函数体内 `from .. import content as C` + `C.XXX` | 模块级 `C = _Dom()`（读**包内域 JSON**；未进包的符号 `__getattr__` 转注入的宿主聚合层） | 逐符号归属见下表 |
| 函数体内 `from ..content_rules.gameplay import check_player_level_up` | 模块级同名包装 `check_player_level_up(...)` | 升级结算写库 = 宿主；正文调用点不动 |
| 函数体内 `from ..core.stat_bonus import stat_bonus` | 模块级同名包装 `stat_bonus(...)` | 外部增幅聚合 = 宿主（读称号/成就/收藏册） |
| 函数体内 `from ..reward import grant_reward` | 模块级同名包装 `grant_reward(*a, **k)` | 发放实现 = 宿主 `game/reward.py` |
| 函数体内 `from .quests import bump_daily_progress as _bump_daily_progress` | 模块级同名包装 `_bump_daily_progress(...)` | 每日委托计数 = 宿主 `game/services/quests.py`（**同级服务，本批未搬**） |
| 函数体内 `from ..services.quests import DAILY_META_KEYS, settle_daily_quest` | `DAILY_META_KEYS` = `_HostAttr("services.quests", …)`（支持 `in`）；`settle_daily_quest` = 同名包装 | 同上；`DAILY_META_KEYS` 只被 `if dkey in DAILY_META_KEYS` 用 ⇒ 用带 `__contains__` 的惰性对象，正文那一行不动 |

★ 逐符号归属（`C.XXX` → 包内域 / 宿主）
--------------------------------------
| 符号 | 包内来源 | 实测口径 |
|---|---|---|
| `C.MAIN_QUESTS`（70） | `content/data/quests.json` 的 `source=="main"` | 全 70 条逐字段 == 真源置 `source`；**消费端全是按 id 取**（`next(... id == X)`）⇒ 无顺序语义，dict 值序即可 |
| `C.SIDE_QUESTS`（144，**有序**） | 同域 `source=="side"` + 本模块 `SIDE_QUEST_ORDER` 还原**源列表插入序** | `available_quest_list` / `side_available_list` / `offer_side_quests` 的输出行序 = 遍历序 ⇒ 序不能丢（见下） |
| `C.NPCS`（362） | `npcs.json` 的 `source=="town"` | 键集/逐字段与真源相等（去注入的 `source` 后），与 `content/talk_actions.py:_Dom` 同口径 |
| `C.ALL_WILD`（63） | `npcs.json` 的 `source=="wild"` ∪ (`source=="hidden"` 且无 `inst_stage`) | 真源 `core/wild.py:26 ALL_WILD = {**WILD_NPCS, **HIDDEN_NPCS}` 在 `core.wild` import 期求值（**不含**装配期后并入的 6 条层内 NPC）—— 实测 63 条 |
| `C.DIALOGUES`（39） | `dialogues.json` | 逐键逐值 == 真源 |
| `C.RACES`（6） | `races.json` | 同上 |
| `C.CLASSES`（8） | `classes.json` | **只用到 `name` / `tier_levels` 两个字段**（实测两者与真源逐条相等；`tutor` / `evolve_branches` 另有出处、本模块不读 ⇒ 包内那份的差异不构成本模块的行为差异） |
| `C.MAP_BY_ID` | `worlds.json` | **只用到 `.get(...).get("name")` / `.get("area")`**（对象在 `obj_text` / `quest_reputation` / `_rule_fire` 的 `cur_map` 参数位）——消费者只读 `id`/`name`/`area`/`type`，`worlds` 域全有 |
| `C.TITLES` | **宿主**（`game/data/titles.py`）—— 缺口 | 称号名册未进包（`titles` 域是别的线声明的**条件子集**，不是名册全量）⇒ 经注入的宿主聚合层读 |
| `C.FACTIONS` / `C.AREA_FACTION` | **宿主**（`game/data/factions.py`）—— 缺口 | 按 B9「常量模块归 L7」铁律本线不建域 |
| `C.resolve("materials", …)` | **宿主** | 材料名→id 的**权威索引在宿主**（`materials`(598) ⊊ `items`(900)，且 `build_index` 是装配期产物）——包内 `content/tables.py:resolve` 对 `materials` 是**原样返回**，直接改用它会静默错（`db.count_item` 拿到中文名）⇒ 必须走宿主 |

★ 顺序声明 `SIDE_QUEST_ORDER` —— 为什么必须有
--------------------------------------------
域文件外层键是**字典序**（导出契约 `sort_table`：幂等优先），而真源 `SIDE_QUESTS` 是有序 list：
`available_quest_list`（『接取』无参列表）/ `side_available_list`（对话菜单序号）/ `offer_side_quests`
（逐条接取/拒绝提示）**都按遍历序产出玩家可见行**。少一份顺序声明 → 行序变（逐字节不等）。
导出域**没有** `seq`/`order` 字段可还原（`derive_quests` 只注入 `source`）⇒ 本模块显式声明真源插入序
（与 `content/event_menu.py:MAP_ORDER` / `content/tables.py:JOB_ORDER` 同一手法），并**带集合守卫**：
域内多一条/少一条就 `raise`（防「加了支线忘了改这里」= 静默改序）。顺序字面量由
`overnight/b9_l5_quests_travel_snap.py --dump-side-order` 从真源生成（本文件不手抄）。

用法::

    from content import quests_flow as QF
    QF.bind_host(db, c)                     # 宿主薄壳注入（游戏仓 game/services/quests_flow.py）
    lines = QF.take_main_quest(group_id, qq_id, npc_id, npc)
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))          # <pkg>/content


def _read_domain(domain: str, sub: str = "data", default=None):
    """读包内 `content/<sub>/<domain>.json`（缺文件 / 坏 JSON → default，不抛；与包内口径同）。"""
    try:
        with open(os.path.join(_HERE, sub, "%s.json" % domain), encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                        # noqa: BLE001
        return {} if default is None else default


# ============================================================
# 顺序声明（真源 `game/data/quests.py:939 SIDE_QUESTS` 的列表插入序）
# ============================================================
SIDE_QUEST_ORDER = """s1 s2 s3 s4 s5 s6
s7 s8 s9 s10 s11 s12
s13 s14 s15 s16 s17 s18
s19 s20 s21 s22 s23 s24
s25 s26 s27 s28 s29 s30
s31 s32 s33 s34 s36 s37
s38 s39 s40 s41 s42 s43
s44 s45 s35 s46 s47 s48
s49 s50 s51 s52 s53 s54
s55 s56 s57 s58 s59 s60
s61 s62 s63 s64 s65 s66
s67 s68 s69 s70 s71 s72
s73 s74 s75 s76 s77 s78
s79 s80 s81 s82 s83 s84
s85 s86 s87 s88 s89 s107
s108 s109 s110 s111 s112 s113
s114 s115 s116 s117 s118 s119
s120 s121 s90 s91 s92 s93
s94 s95 s96 s97 s98 s99
s100 s101 s102 s103 s104 s105
s106 hq5_1 hq5_2 hq5_3 hq6_1 hq6_2
hq6_3 hq7_1 hq7_2 hq7_3 hq8_1 hq8_2
hq8_3 hq8_4 s_hidden_ember s_hidden_library s_caravan_escort s_bandit_clear
s_lighthouse s_tunnel_repair s_dragon_bone s_dragon_blood s_board_cat s_tide_shells""".split()


def _side_quests(raw: dict) -> list:
    """按声明的真源序还原支线表；集合不一致 → **raise**（绝不静默改序）。"""
    rows = {k: v for k, v in (raw or {}).items()
            if isinstance(v, dict) and v.get("source") == "side"}
    have = set(SIDE_QUEST_ORDER)
    if have != set(rows):
        raise ValueError(
            "quests_flow：SIDE_QUEST_ORDER 与 quests 域的 side 条目不一致"
            "（域 %d 条 / 声明 %d 条；域多出 %s；声明多出 %s）"
            "—— 请用 overnight/b9_l5_quests_travel_snap.py --dump-side-order 重生成"
            % (len(rows), len(SIDE_QUEST_ORDER), sorted(set(rows) - have)[:5],
               sorted(have - set(rows))[:5]))
    if len(SIDE_QUEST_ORDER) != len(have):
        raise ValueError("quests_flow：SIDE_QUEST_ORDER 里有重复 id（%d 条 vs 集合 %d）"
                         % (len(SIDE_QUEST_ORDER), len(have)))
    return [rows[k] for k in SIDE_QUEST_ORDER]


# ============================================================
# 宿主替身口（存储层 / 内容聚合层 / 同级服务 / 发放与结算）
# ============================================================
_HOST_DB = None            # 宿主存储层（真源 `from .. import db`）
_HOST_C = None             # 宿主内容聚合层（真源 `from .. import content as C`）—— 只喂**未进包**的符号
_HOST_LEVEL_UP = None      # `game.content_rules.gameplay.check_player_level_up`
_HOST_STAT_BONUS = None    # `game.core.stat_bonus.stat_bonus`
_HOST_GRANT = None         # `game.reward.grant_reward`
_HOST_QUESTS_SVC = None    # `game.services.quests`（每日委托：bump_daily_progress / settle_daily_quest / DAILY_META_KEYS）

# 宿主模块名（运行时 `main.py` 的模块路径 = `data.plugins.dragonfall`；测试同样）—— 与
# `content/flow/weekly_progress.py` / `content/talk_actions.py` 同口径（B8.2 线1 立的规矩）
_HOST_PKG = "data.plugins.dragonfall.game"
_HOST_PKG_FALLBACK = "game"

# `C` 上**未进包**的符号 → 转宿主聚合层（其余符号本模块自己从包内域文件给）
_HOST_FALLBACK = ("TITLES", "FACTIONS", "AREA_FACTION")


def bind_host(db=None, c=None, level_up=None, stat_bonus_fn=None,
              grant_reward_fn=None, quests_svc=None) -> None:
    """宿主替身注入（幂等；宿主薄壳在 import 期调用）。"""
    global _HOST_DB, _HOST_C, _HOST_LEVEL_UP, _HOST_STAT_BONUS, _HOST_GRANT, _HOST_QUESTS_SVC
    if db is not None:
        _HOST_DB = db
    if c is not None:
        _HOST_C = c
    if level_up is not None:
        _HOST_LEVEL_UP = level_up
    if stat_bonus_fn is not None:
        _HOST_STAT_BONUS = stat_bonus_fn
    if grant_reward_fn is not None:
        _HOST_GRANT = grant_reward_fn
    if quests_svc is not None:
        _HOST_QUESTS_SVC = quests_svc


def _resolve_host(mod: str):
    """取宿主子模块：注入优先 → 已加载的宿主模块（`sys.modules`，**不 import**）。"""
    for name in ("%s.%s" % (_HOST_PKG, mod), "%s.%s" % (_HOST_PKG_FALLBACK, mod)):
        m = sys.modules.get(name)
        if m is not None:
            return m
    raise RuntimeError(
        "quests_flow：宿主模块 %s 不可用（未 bind_host 且未加载）—— 拒绝静默空跑" % mod)


class _HostDB:
    """惰性宿主存储层代理（真源 `from .. import db`）——`db.xxx` 正文不动，属性访问时解析。"""

    def __getattr__(self, name):
        return getattr(_HOST_DB if _HOST_DB is not None else _resolve_host("db"), name)


db = _HostDB()


def _host_c():
    """宿主内容聚合层（真源 `from .. import content as C`）。"""
    return _HOST_C if _HOST_C is not None else _resolve_host("content")


class _HostAttr:
    """惰性宿主模块属性（正文里当普通常量用；只实现 `in` / 迭代 / 取值）。"""

    def __init__(self, mod: str, attr: str):
        self._mod, self._attr = mod, attr

    def _v(self):
        m = _HOST_QUESTS_SVC if self._mod == "services.quests" and _HOST_QUESTS_SVC is not None \
            else _resolve_host(self._mod)
        return getattr(m, self._attr)

    def __contains__(self, item):
        return item in self._v()

    def __iter__(self):
        return iter(self._v())

    def __len__(self):
        return len(self._v())

    def __repr__(self):
        return repr(self._v())


DAILY_META_KEYS = _HostAttr("services.quests", "DAILY_META_KEYS")


def check_player_level_up(group_id, qq_id, player):
    """升级结算（真源 函数体内 `from ..content_rules.gameplay import check_player_level_up`）。"""
    fn = _HOST_LEVEL_UP if _HOST_LEVEL_UP is not None \
        else getattr(_resolve_host("content_rules.gameplay"), "check_player_level_up")
    return fn(group_id, qq_id, player)


def stat_bonus(group_id, qq_id, player):
    """外部面板增幅聚合（真源 函数体内 `from ..core.stat_bonus import stat_bonus`）。"""
    fn = _HOST_STAT_BONUS if _HOST_STAT_BONUS is not None \
        else getattr(_resolve_host("core.stat_bonus"), "stat_bonus")
    return fn(group_id, qq_id, player)


def grant_reward(*args, **kwargs):
    """发放（真源 函数体内 `from ..reward import grant_reward`）。"""
    fn = _HOST_GRANT if _HOST_GRANT is not None \
        else getattr(_resolve_host("reward"), "grant_reward")
    return fn(*args, **kwargs)


def _bump_daily_progress(*args, **kwargs):
    """行会每日委托计数（真源 函数体内 `from .quests import bump_daily_progress`）。"""
    fn = getattr(_HOST_QUESTS_SVC, "bump_daily_progress") if _HOST_QUESTS_SVC is not None \
        else getattr(_resolve_host("services.quests"), "bump_daily_progress")
    return fn(*args, **kwargs)


def settle_daily_quest(*args, **kwargs):
    """每日委托达标结算单点（真源 函数体内 `from ..services.quests import settle_daily_quest`）。"""
    fn = getattr(_HOST_QUESTS_SVC, "settle_daily_quest") if _HOST_QUESTS_SVC is not None \
        else getattr(_resolve_host("services.quests"), "settle_daily_quest")
    return fn(*args, **kwargs)


# ============================================================
# 域门面（替身：宿主薄聚合层 `C`）—— 包内域直读，未进包的符号下沉宿主
# ============================================================
class _Dom:
    """`C.MAIN_QUESTS` / `C.SIDE_QUESTS` / `C.NPCS` / `C.ALL_WILD` / `C.DIALOGUES` /
    `C.CLASSES` / `C.RACES` / `C.MAP_BY_ID` 从**包内域**给；`TITLES` / `FACTIONS` /
    `AREA_FACTION` / `resolve` 转宿主聚合层（见模块 docstring 的逐符号归属表）。"""

    def __init__(self):
        raw_q = _read_domain("quests")
        raw_n = _read_domain("npcs")
        self.MAP_BY_ID = _read_domain("worlds")
        self.DIALOGUES = _read_domain("dialogues")
        self.CLASSES = _read_domain("classes")
        self.RACES = _read_domain("races")
        # C.NPCS = 城镇/据点 NPC（真源 npcs 域 source=="town"，362 条）
        self.NPCS = {k: v for k, v in raw_n.items() if v.get("source") == "town"}
        # C.ALL_WILD = 野外 ∪ 隐藏（**不含**装配期并入的 6 条层内 NPC —— 见 docstring）
        self.ALL_WILD = {k: v for k, v in raw_n.items()
                         if v.get("source") == "wild"
                         or (v.get("source") == "hidden" and not v.get("inst_stage"))}
        # C.MAIN_QUESTS：消费端全部按 id 取 ⇒ 无顺序语义
        self.MAIN_QUESTS = [v for v in raw_q.values() if v.get("source") == "main"]
        # C.SIDE_QUESTS：**有序**（顺序声明 + 集合守卫）
        self.SIDE_QUESTS = _side_quests(raw_q)

    def __getattr__(self, name):
        """未进包的符号 → 宿主聚合层（`__getattr__` 只在常规找不到时才走）。"""
        if name in _HOST_FALLBACK:
            return getattr(_host_c(), name)
        raise AttributeError(name)

    @staticmethod
    def resolve(table_name: str, name_or_id: str):
        """`game/core/index.py:47 resolve` —— **委托宿主**（materials 的权威索引在装配期的宿主侧）。"""
        return _host_c().resolve(table_name, name_or_id)


C = _Dom()


def obj_text(obj):
    if obj.get("kill"):
        return f"击败 {obj['kill']} ×{obj['count']}"
    if obj.get("collect"):
        # v125.1 P2：s64 等 collect_count 无 count 的复合目标不再 KeyError
        return f"收集 {obj['collect']} ×{obj.get('collect_count') or obj.get('count', 1)}"
    if obj.get("explore"):
        return f"前往 {C.MAP_BY_ID.get(obj['explore'], {}).get('name', '？')}"
    if obj.get("find"):
        # v97.1 告示委托：在指定地图探索概率找到目标
        return f"在 {C.MAP_BY_ID.get(obj.get('map', ''), {}).get('name', '？')} 寻找 {obj['find']}(探索有概率遇到)"
    if obj.get("use"):
        # v124 use 目标：使用指定物品达成
        return f"使用 {obj['use']}"
    if obj.get("talk"):
        npc = C.NPCS.get(obj["talk"], {})
        return f"与 {npc.get('name', '？')} 交谈"
    return "？"


def sq_unlocked(quests, sq):
    """v124 链式支线：unlock 前置解锁检查。unlock 支持单条或列表（全部满足）。
    格式：{"side": "s5"} 或 {"main": "q2_3"}（兼容 {"type":"side","id":"s5"} 写法）。
    无 unlock=天然解锁。"""
    u = sq.get("unlock")
    if not u:
        return True
    us = u if isinstance(u, list) else [u]
    for x in us:
        if not isinstance(x, dict):
            continue
        _typ = x.get("type") or ("side" if x.get("side") else "main" if x.get("main") else None)
        _tid = x.get("id") or x.get("side") or x.get("main") or ""
        if _typ == "side":
            # 支线完成 = side dict 中该任务 status==done
            _sq = (quests.get("side") or {}).get(_tid) or {}
            if _sq.get("status") != "done":
                return False
        elif _typ == "main":
            _cm = quests.get("completed_main") or []
            if _tid not in _cm and quests.get("main_quest") != _tid:
                return False
    return True

def sq_stats_met(player, sq):
    """v124 隐藏线/副业线：require_stats 动作计数门槛。达标才可接取。
    stats 表以 qq_id 为主键，group_id 参数为兼容占位。"""
    rs = sq.get("require_stats")
    if not rs:
        return True
    _qq = player.get("qq_id") or player.get("id", "")
    if not _qq:
        return False
    _st = db.get_stats("", _qq) or {}
    for k, v in rs.items():
        if int(_st.get(k, 0) or 0) < int(v):
            return False
    return True

def available_quest_list(player, quests, mq) -> list:
    """当前地图可接取任务列表（v123d 抽出，供『接取』无参渲染与『接取 <序号>』映射共用）。

    返回 [{"name": 任务名, "line": 渲染行（不含 📜 前缀）}, ...]——主线 pending 在前，
    支线按 C.SIDE_QUESTS 顺序；告示委托（board）不在此列（须去告示板指名接取）。
    """
    available = []
    if mq and quests.get("main_status") == "pending":
        giver = C.NPCS.get(mq["giver"]) or C.ALL_WILD.get(mq["giver"]) or {}
        if giver.get("map") == player["cur_map"]:
            available.append({
                "name": mq["name"],
                "line": f"主线『{mq['name']}』（{giver.get('name', '？')}发布）",
            })
    for sq in C.SIDE_QUESTS:
        if sq["id"] in (quests.get("side") or {}):
            continue
        # v124 链式支线：unlock 前置未满足不出现在可接列表
        if not sq_unlocked(quests, sq):
            continue
        # v124 隐藏线：require_stats 计数门槛未达不出现在可接列表
        if not sq_stats_met(player, sq):
            continue
        # v104 M20 P2：告示委托（board: true）只在告示板子区域指名接取，
        # 列入普通列表会误导玩家（点名接取被 world.py 告示板拦截逻辑挡下）
        if sq.get("board"):
            continue
        npc = C.NPCS.get(sq["giver"]) or C.ALL_WILD.get(sq["giver"]) or {}
        if npc.get("map") == player["cur_map"]:
            # v104 M19：接取列表显示支线等级门槛
            _lv = f"Lv.{sq['min_level']}+ " if sq.get("min_level") else ""
            available.append({
                "name": sq["name"],
                "line": f"支线『{sq['name']}』{_lv}（{npc.get('name', '？')}发布）",
            })
    return available


# v116 §3.4：放弃进行中的支线/每日任务（释放接取位）。主线不可放弃。

def update_explore_quests(group_id, qq_id, map_id):
    """到达子区域时检查 explore 型任务(主线和支线)"""
    lines = []
    quests = db.get_quests(group_id, qq_id)
    changed = False
    # 主线 explore（v105：仅已接取(active)时触发——pending 未接取到达目标图不得自动完成+发奖）
    main_id = quests.get("main_quest")
    if main_id and quests.get("main_status") == "active":
        mq = next((q for q in C.MAIN_QUESTS if q["id"] == main_id), None)
        if mq and mq["objective"].get("explore") == map_id:
            # v124.3：奖励统一走 _grant_quest_rewards（exp/gold/升级 + reward_item 全格式
            # + reward_pet/reward_mount/unlock_class）——此前 explore 自动完成只有
            # reward_item 单值，reward_pet 配了也静默不发
            grant_quest_rewards(group_id, qq_id, mq, lines)
            completed = list(quests.get("completed_main", []))
            completed.append(main_id)
            quests["completed_main"] = completed
            quests["main_quest"] = mq["next"]
            # v105 M19 P1：explore 自动完成必须重置 main_status=pending（与 _take_main_quest
            # 交付分支一致）——此前遗留 "active" 导致任务面板显示"进行中"而非"未接取"、
            # 对话树 quest_pending 接取入口不亮（q1_5 完成后 q1_6 需 3-4 轮对话才兜底接取）
            quests["main_status"] = "pending"
            quests["main_progress"] = {}
            changed = True
            lines.append(f"📜 主线『{mq['name']}』达成！奖励：经验 +{mq['reward_exp']} 金币 +{mq['reward_gold']}")
            # v105 M19 P2：explore 自动完成补发声望（奖励本体已并入 _grant_quest_rewards）
            _rep = quest_reputation(group_id, qq_id, mq["giver"])
            if _rep:
                lines.append(f"  {_rep}")
            if mq["next"]:
                nq = next((q for q in C.MAIN_QUESTS if q["id"] == mq["next"]), None)
                if nq:
                    lines.append(f"📜 新主线：『{nq['name']}』{nq['desc']}")
            else:
                lines.append("🎊 恭喜！你完成了全部主线任务，成为奥兰迪亚的传说！")
    # 支线 explore
    side = dict(quests.get("side", {}))
    for sid, sq in list(side.items()):
        if sq.get("status") == "active":
            sqd = next((q for q in C.SIDE_QUESTS if q["id"] == sid), None)
            if sqd and sqd["objective"].get("explore") == map_id:
                sq["status"] = "ready"
                changed = True
                _g = C.NPCS.get(sqd["giver"]) or C.ALL_WILD.get(sqd["giver"]) or {}
                lines.append(f"📜 支线『{sqd['name']}』目标达成！回去找 {_g.get('name', '？')} {deliver_hint(sqd['giver'])}吧～")
    if changed:
        quests["side"] = side
        db.save_quests(group_id, qq_id, quests)
    return lines

def take_main_quest(group_id, qq_id, npc_id, npc):
    """从 NPC 接主线任务；返回通知行列表"""
    lines = []
    player = db.get_player(group_id, qq_id)
    quests = db.get_quests(group_id, qq_id)
    main_id = quests.get("main_quest")
    if not main_id:
        lines.append("🎊 主线任务已全部完成，你已是奥兰迪亚的传说！")
        return lines
    mq = next((q for q in C.MAIN_QUESTS if q["id"] == main_id), None)
    # 存档容错：main_quest 指向已不存在的任务（旧存档/主线数据变更）→ 重置回主线起点
    if not mq and main_id:
        quests["main_quest"] = "q1_1"
        quests["main_status"] = "pending"
        quests["main_progress"] = {}
        main_id = "q1_1"
        mq = next((q for q in C.MAIN_QUESTS if q["id"] == main_id), None)
    if not mq or mq["giver"] != npc_id:
        # 不是这个 NPC 的任务
        need_npc = C.NPCS.get(mq["giver"], {}).get("name", "？") if mq else "？"
        lines.append(f"【{npc['name']}】我现在没有任务交给你。镇长/各地首领或许有安排……")
        if mq:
            lines.append(f"📜 当前主线『{mq['name']}』由 {need_npc} 发布。")
        return lines
    st = quests.get("main_status", "pending")
    # v105 P0：collect 型主线（q5_5 圣光百合）——背包材料足够即置 ready
    # （对齐支线逻辑 talk_actions.py:111-113 实时数背包；交付时再扣材料）
    # 放在状态分发前：pending 接取时材料已齐 → 直接可交付；active 回来找 NPC → 置 ready
    obj0 = mq["objective"]
    if obj0.get("collect") and st != "ready" and db.count_item(group_id, qq_id, obj0["collect"]) >= obj0.get("count", 1):
        quests["main_status"] = "ready"
        quests["main_progress"] = {obj0["collect"]: obj0.get("count", 1)}
        db.save_quests(group_id, qq_id, quests)
        st = "ready"
    if st == "pending":
        # v169.1：主线 min_level 硬门槛（高经验主线防跨级接取；suggest_lv 仅软提示保留）
        if mq.get("min_level") and player["level"] < mq["min_level"]:
            return lines + [f"🛡️ 『{mq['name']}』需要 Lv.{mq['min_level']} 才能接取！（你当前 Lv.{player['level']}）先去提升实力吧～"]
        quests["main_status"] = "active"
        quests["main_progress"] = {}
        # talk 型任务：与发布 NPC 交谈即达成目标（对话即完成）
        obj = mq["objective"]
        if obj.get("talk") and obj["talk"] == npc_id:
            quests["main_status"] = "ready"
            quests["main_progress"] = {obj["talk"]: 1}
        # v105 P2：explore 型主线接取时已在目标地图 → 直接置 ready（免出图重进）
        if obj.get("explore") and player.get("cur_map") == obj["explore"]:
            quests["main_status"] = "ready"
            quests["main_progress"] = {obj["explore"]: 1}
        db.save_quests(group_id, qq_id, quests)
        lines.append(f"📜 【接取任务】『{mq['name']}』")
        if mq.get("story"):
            lines.append(f"  📖 {mq['story']}")
        lines.append(f"  🎯 目标：{obj_text(mq['objective'])}")
        lines.append(f"  奖励：经验 +{mq['reward_exp']} 金币 +{mq['reward_gold']}")
        # v95.25 #138：主线等级建议（软提示，不拦截接取）——suggest_lv 在 quests.py 数据里
        if mq.get("suggest_lv") and player["level"] < mq["suggest_lv"]:
            lines.append(f"  ⚠️ 建议等级 Lv.{mq['suggest_lv']}，你才 Lv.{player['level']}——可以先练练级再挑战！")
        if quests["main_status"] == "ready":
            lines.append("  ✨ 交谈完成！再与这位 NPC 对话即可交付任务。")
    elif st == "ready":
        # 交任务领奖
        obj = mq.get("objective") or {}
        # v105 P0：collect 型主线交付时扣材料（先复核背包，材料被消耗则回到进行中）
        if obj.get("collect"):
            need = obj.get("count", 1)
            if db.count_item(group_id, qq_id, obj["collect"]) < need:
                quests["main_status"] = "active"
                quests["main_progress"] = {}
                db.save_quests(group_id, qq_id, quests)
                lines.append(f"📜 交付『{mq['name']}』需要 {obj['collect']} ×{need}，你背包里不够了，先去凑齐吧～")
                return lines
            db.remove_item(group_id, qq_id, obj["collect"], need)
            # v126.2：鱼获个体属性在 item_data.tags，remove_item 自动截断，无需额外同步
            lines.append(f"🎒 交出 {obj['collect']} ×{need}")
        # v124.3：奖励统一走 _grant_quest_rewards（exp/gold/升级 + reward_item 全格式
        # + reward_pet/reward_mount/unlock_class）——此前主线交付只支持 reward_item
        # 单值 + reward_pet，eq:/list 随机/坐骑/隐藏职业配了不发
        grant_quest_rewards(group_id, qq_id, mq, lines)
        completed = list(quests.get("completed_main", []))
        completed.append(main_id)
        quests["completed_main"] = completed
        quests["main_quest"] = mq["next"]
        quests["main_status"] = "pending"
        quests["main_progress"] = {}
        db.save_quests(group_id, qq_id, quests)
        lines.append(f"✅ 【任务完成】『{mq['name']}』！")
        if mq.get("ending"):
            # v105 M19 P1：主线抉择结局变体——q10_5 等任务按对话树选择的 flag 输出不同结尾
            _ending = mq["ending"]
            _endings = mq.get("endings") or {}
            if _endings:
                try:
                    _flags = db.get_talk_flags(group_id, qq_id, mq["giver"]) or []
                except Exception:
                    _flags = []
                for _fk, _fv in _endings.items():
                    if _fk in _flags:
                        _ending = _fv
                        break
            lines.append(f"  📖 {_ending}")
        lines.append(f"  奖励：经验 +{mq['reward_exp']} 金币 +{mq['reward_gold']}")
        rep_line = quest_reputation(group_id, qq_id, mq["giver"])
        if rep_line:
            lines.append(f"  {rep_line}")
        if mq["next"]:
            nq = next((q for q in C.MAIN_QUESTS if q["id"] == mq["next"]), None)
            if nq:
                lines.append(f"📜 新主线：『{nq['name']}』{nq['desc']}")
                lines.append(f"  🎯 去找 {C.NPCS[nq['giver']]['name']} 接取新任务")
        else:
            lines.append("🎊 恭喜！你完成了全部主线任务，成为奥兰迪亚的传说！")
    else:
        lines.append(f"📜 你已接取『{mq['name']}』：{mq['desc']}")
    return lines

def quest_reputation(group_id, qq_id, npc_id):
    """完成任务时给对应势力加声望，返回提示行(如有)"""
    npc = C.NPCS.get(npc_id)
    if not npc:
        return ""
    m = C.MAP_BY_ID.get(npc["map"], {})
    area_key = m.get("area", npc["map"])
    faction = C.AREA_FACTION.get(area_key)
    if not faction:
        return ""
    db.add_reputation(group_id, qq_id, faction, 10)
    return f"🏛️ {C.FACTIONS[faction]['icon']} 声望＋10"

def deliver_hint(npc_id):
    """交付方式提示（v95.16 #75）：有对话树 NPC 走对话交付，无对话树 NPC 用『交付任务』"""
    if C.DIALOGUES.get(npc_id):
        return "对话交付"
    return "『交付任务』交付"

def side_available_list(group_id, qq_id, npc_id, npc) -> list:
    """v127.6：该 NPC 名下当前"可接"的支线清单（对话菜单/预告/全接三处同源过滤）。

    过滤条件与旧 _offer_side_quests 全部一致：giver == npc_id、非告示板委托(board)、
    未接取（不在 side）、_sq_unlocked 链式前置、_sq_stats_met 计数门槛、
    min_level 等级门槛、require_race 种族限制。每项返回
    {sid, name, desc, objective_text, reward_exp, reward_gold}，按 SIDE_QUESTS 定义顺序
    （保证对话菜单序号稳定）。npc 参数保留以与 _offer_side_quests 签名一致（此处未用到）。
    """
    player = db.get_player(group_id, qq_id) or {}
    quests = db.get_quests(group_id, qq_id)
    side = quests.get("side", {}) or {}
    out = []
    for sq in C.SIDE_QUESTS:
        if sq["giver"] != npc_id:
            continue
        if sq.get("board"):  # v95r65 #295：告示板委托只能在告示板接取，NPC 不自动发
            continue
        if sq["id"] in side:
            continue
        # v124 链式支线：unlock 前置未满足不自动发（如剧情线第二步等第一步完成）
        if not sq_unlocked(quests, sq):
            continue
        # v124 隐藏线/副业线：require_stats 计数门槛未达不自动发（如 H7 需垂钓 10 次）
        if not sq_stats_met(player, sq):
            continue
        # v101.30d #O52：支线等级门槛（min_level 字段）——等级不够不算可接
        if sq.get("min_level") and (player.get("level") or 0) < sq["min_level"]:
            continue
        # v113 种族限制：require_race 指定血脉（隐藏线试炼）——非该种族不算可接
        if sq.get("require_race"):
            _cur = player.get("race") or "human"
            if _cur != sq["require_race"]:
                continue
        out.append({
            "sid": sq["id"],
            "name": sq["name"],
            "desc": sq.get("desc", ""),
            "objective_text": obj_text(sq.get("objective") or {}),
            "reward_exp": sq.get("reward_exp", 0),
            "reward_gold": sq.get("reward_gold", 0),
        })
    return out

def offer_side_quest(group_id, qq_id, npc_id, sid) -> list:
    """v127.6：单条支线接取（对话 side_menu 子选项 action: side_take_one）。

    校验 sid 必须在 _side_available_list 当前可接清单内才接（防越权/已接/等级不足），
    否则返回 [] 不落地。返回该任务的接取通知行列表。
    """
    item = next((a for a in side_available_list(group_id, qq_id, npc_id, None)
                 if a["sid"] == sid), None)
    if not item:
        return []
    sq = next((q for q in C.SIDE_QUESTS if q["id"] == sid), None)
    if not sq:
        return []
    quests = db.get_quests(group_id, qq_id)
    side = dict(quests.get("side", {}))
    side[sid] = {"status": "active", "progress": {}}
    quests["side"] = side
    db.save_quests(group_id, qq_id, quests)
    return [
        f"📜 【支线】『{sq['name']}』{sq['desc']}",
        f"  奖励：经验 +{sq['reward_exp']} 金币 +{sq['reward_gold']}",
        f"  🎯 目标：{item['objective_text']}",
    ]

def offer_side_quests(group_id, qq_id, npc_id, npc):
    """NPC 有未接的支线任务时自动接取，返回通知行列表

    v127.6 重构：可接清单统一走 _side_available_list（与对话 side_menu 菜单/预告同源过滤），
    逐条复用 _offer_side_quest 接取；不可接（min_level/require_race 被过滤掉）的
    原拒绝提示按 SIDE_QUESTS 顺序保留，全接+完成提示行为不变（旧 side_offer action 兼容，
    单支线 NPC 无感）。
    """
    player = db.get_player(group_id, qq_id) or {}
    lines = []
    quests = db.get_quests(group_id, qq_id)
    side = dict(quests.get("side", {}))
    available = side_available_list(group_id, qq_id, npc_id, npc)
    av_ids = {a["sid"] for a in available}
    changed = False
    for sq in C.SIDE_QUESTS:
        if sq["giver"] != npc_id or sq.get("board"):
            continue
        if sq["id"] in side:
            continue
        if sq["id"] in av_ids:
            side[sq["id"]] = {"status": "active", "progress": {}}
            changed = True
            lines.append(f"📜 【支线】『{sq['name']}』{sq['desc']}")
            lines.append(f"  奖励：经验 +{sq['reward_exp']} 金币 +{sq['reward_gold']}")
            lines.append(f"  🎯 目标：{obj_text(sq['objective'])}")
            continue
        # 不可接但符合其余条件的拒绝提示（与原始行为文案一致）
        if not sq_unlocked(quests, sq):
            continue
        if not sq_stats_met(player, sq):
            continue
        # v101.30d #O52：支线等级门槛——等级不够不自动接
        if sq.get("min_level") and (player.get("level") or 0) < sq["min_level"]:
            lines.append(
                f"🛡️ {npc.get('name', '对方')}打量了你一眼：这活得有 Lv.{sq['min_level']}+ 的本事，你再去练练吧。"
            )
            continue
        # v113 种族限制：require_race 指定血脉——非该种族导师直接拒绝
        if sq.get("require_race"):
            _rr = sq["require_race"]
            _cur = player.get("race") or "human"
            if _cur != _rr:
                _rcn = (C.RACES.get(_rr) or {}).get("name", "对应血脉")
                lines.append(
                    f"⛔ {npc.get('name', '对方')}凝视着你，缓缓摇头：『这份传承只属于{_rcn}的血脉。"
                    f"你体内流淌的{(C.RACES.get(_cur) or {}).get('name', '血脉')}之血，与它无缘。』"
                )
                continue
    if changed:
        quests["side"] = side
        db.save_quests(group_id, qq_id, quests)
    # v95.4：该 NPC 有已完成支线 → 提示交付入口（反馈：可交任务找不到交付方式）
    # v95.15 #73：代词按 NPC 性别（迷路骑士等男性 NPC 用"他"）
    # v95.16 #75：按是否有对话树区分交付引导（无对话树 NPC 的『对话』没有交付选项）
    _ta = "她" if npc.get("gender") == "女" else "他"
    for sid, sq in list(quests.get("side", {}).items()):
        sqd = next((q for q in C.SIDE_QUESTS if q["id"] == sid), None)
        if sqd and sqd["giver"] == npc_id and sq.get("status") == "ready":
            if C.DIALOGUES.get(npc_id):
                lines.append(f"✅ 『{sqd['name']}』已完成！与{_ta}对话即可交付～")
            else:
                lines.append(f"✅ 『{sqd['name']}』已完成！输入『交付任务』即可交付～")
            break
    return lines

# v104 M24 P2-2：『交任务』无命中（策划案 23 章:182 主指令）→ 补别名

def grant_quest_rewards(group_id, qq_id, qdef, lines):
    """v124.3 统一任务奖励发放（主线 explore 自动完成 / 主线交付 / 支线交付三处共用）。

    基准：支线 _complete_side_quest 原实现（v104 M20 + v124 全奖励类型）——
    reward_exp/reward_gold 入角色并结算升级；reward_item 支持单值 / 列表随机 /
    eq: 装备名册；reward_pet 宠物蛋 / reward_mount 坐骑缰绳入包；unlock_class
    解锁隐藏职业。声望 / 分支 flag / 每日计数等任务特有处理不入此函数，调用方各自保留。
    返回结算后的 player（调用方后续需要时使用，如 _complete_side_quest 的 _rule_fire）。"""
    import random
    player = db.get_player(group_id, qq_id)
    player["exp"] += qdef.get("reward_exp", 0)
    player["gold"] += qdef.get("reward_gold", 0)
    player["_title_bonus"] = stat_bonus(group_id, qq_id, player)
    lv_logs, player = check_player_level_up(group_id, qq_id, player)
    db.update_player(group_id, qq_id, exp=player["exp"], gold=player["gold"], level=player["level"], hp=player["hp"], mp=player["mp"], max_hp=player["max_hp"], max_mp=player["max_mp"], skills=player["skills"], attr_pts=player.get("attr_pts", 0), skill_points=player.get("skill_points", 0), learned_skills=player.get("learned_skills", []))
    if lv_logs:
        if lines:
            lines.append("")
        lines += lv_logs
    # v104 M20 P1：列表型奖励（如 s17 随机符文）→ 随机抽一个发放
    # v174 统一抽象：item/eq/pet/mount/title 发放走 game.reward.grant_reward
    # （只传物品类，exp/gold 已在上方原逻辑结算且要 return 更新后 player）
    ri = qdef.get("reward_item")
    _reward_items = []
    if ri:
        if isinstance(ri, list):
            ri = random.choice(ri)
        # eq: 前缀保留（grant_reward 支持 eq:rid 按名册名解析）
        _reward_items.append({"item": ri, "n": 1})
    _rew = {}
    if _reward_items:
        _rew["items"] = _reward_items
    rp = qdef.get("reward_pet")
    if rp:
        _rew["pets"] = [rp] if isinstance(rp, str) else list(rp)
    rm = qdef.get("reward_mount")
    if rm:
        _rew["mounts"] = [rm] if isinstance(rm, str) else list(rm)
    _tid = qdef.get("title")
    if _tid:
        _rew["title"] = _tid
    if _rew:
        try:
            grant_reward(_rew, group_id, qq_id, player=player, lines=lines)
        except Exception:
            pass
    # v87 隐藏职业：交任务解锁（unlock_class 写入 hidden_class_unlock）
    uc = qdef.get("unlock_class")
    if uc:
        player_now = db.get_player(group_id, qq_id)
        unlocks = list(player_now.get("hidden_class_unlock", []) or [])
        if uc not in unlocks:
            unlocks.append(uc)
            db.update_player(group_id, qq_id, hidden_class_unlock=unlocks)
            lines.append(f"  ⚔️ 传承达成！隐藏职业「{C.CLASSES.get(uc, {}).get('name', uc)}」已解锁！")
            # v112：档位门槛统一读 CLASSES["tier_levels"]（缺省 T1=40），删除 60/30 特例
            _need = (C.CLASSES.get(uc, {}).get("tier_levels") or {1: 40, 2: 60, 3: 90})[1]
            _cname = C.CLASSES.get(uc, {}).get("name", uc)
            lines.append(f"  💡 达到 {_need} 级后输入『转职 {_cname}』接受传承！")
    # v140 波3.6：任务奖励称号（title 字段 = titles.py id 或中文名；称号系统条件判定自动拥有，
    # 这里仅播报解锁——条件满足即生效，不满足也不阻塞任务完成）
    _tid = qdef.get("title")
    if _tid:
        _tinfo = next((t for t in C.TITLES if t.get("id") == _tid), None)
        if not _tinfo:
            # 兼容支线旧字段用中文名（如 "北境的恩人" → north_benefactor）
            _tinfo = next((t for t in C.TITLES if t.get("name") == _tid), None)
        if _tinfo:
            lines.append(f"  🏅 获得称号：「{_tinfo.get('name', _tid)}」！")
        else:
            print(f"[dragonfall][v140] 任务『{qdef.get('name', '')}』称号 id 缺失：{_tid}（titles.py 未登记），已跳过")
    return player

def complete_side_quest(group_id, qq_id, sid, branch_choice=None, hooks=None):
    """交支线任务，返回通知行列表
    v124：支持 branch 分支交付（第一次输出选项并置 branch_wait，玩家回复数字后执行）+
    deliver_text 交付剧情文本。

    hooks：命令层注入 {"tip": callable(cat)->str, "rule_fire": callable(trigger,...)->str}
    （_tip/_rule_fire 是命令层 I/O 面板能力，P4-2 按 §5.2 以 hooks 回调接入）；
    缺省（None）时 _tip 返回空串、_rule_fire 返回空串——service 直测不依赖命令层。"""
    _tip = (hooks or {}).get("tip")
    _rule_fire = (hooks or {}).get("rule_fire")
    lines = []
    quests = db.get_quests(group_id, qq_id)
    sqd = next((q for q in C.SIDE_QUESTS if q["id"] == sid), None)
    if not sqd:
        return ["未知支线任务。"]
    sq = quests.get("side", {}).get(sid)
    if not sq:
        return ["这个任务还没完成呢。"]
    obj = sqd["objective"]
    # 收集型：实时检查背包材料（不依赖 ready 状态）
    if obj.get("collect"):
        # v87 复合目标：kill+collect（魔剑士试炼），collect_count 独立于 kill count
        need = obj.get("collect_count") or obj.get("count", 1)  # v125.1 P2：s64 等 collect_count 无 count 不再 KeyError
        _ckey = C.resolve("materials", obj["collect"])
        have = db.count_item(group_id, qq_id, _ckey)
        if have < need:
            return [f"材料不够！需要 {obj['collect']} ×{need}，你只有 {have} 个。"]
        # v87 复合目标：同时存在 kill 目标时，击杀进度也要满足
        if obj.get("kill"):
            kp = (sq.get("progress") or {}).get(obj["kill"], 0)
            if kp < obj["count"]:
                return [f"还要击败 {obj['kill']} ×{obj['count'] - kp}(当前 {kp}/{obj['count']})！"]
    elif sq.get("status") != "ready":
        return ["这个任务还没完成呢。"]
    # v124 分支任务：第一次交付输出选项，等待玩家回复数字
    br = sqd.get("branch")
    if br and not branch_choice:
        opts = br.get("options") or []
        if sq.get("branch_wait"):
            return [f"{br.get('prompt', '')}\n{_tip('quest_branch')}\n" + "\n".join(
                f"  {o.get('key', str(i + 1))}. {o.get('label', '')}" for i, o in enumerate(opts))]
        quests["side"][sid] = {**sq, "status": "ready", "branch_wait": True}
        db.save_quests(group_id, qq_id, quests)
        _o = [f"  {o.get('key', str(i + 1))}. {o.get('label', '')}" for i, o in enumerate(opts)]
        return [f"{br.get('prompt', '')}\n{_tip('quest_branch')}\n" + "\n".join(_o)]
    # v124 分支选择执行
    if br and branch_choice:
        opts = br.get("options") or []
        chosen = None
        if isinstance(branch_choice, str):
            for o in opts:
                if branch_choice in (o.get("key"), o.get("label")):
                    chosen = o
                    break
        if chosen is None:
            return [f"没有这个选项～{br.get('prompt', '')}\n{_tip('quest_branch')}\n" + "\n".join(
                f"  {o.get('key', str(i + 1))}. {o.get('label', '')}" for i, o in enumerate(opts))]
        # 用分支选项覆盖奖励（顶层 reward 为 0 时以选项为准）
        lines.append(f"  📖 {chosen.get('text', '')}")
        sqd = {**sqd,
               "reward_exp": chosen.get("reward_exp", sqd.get("reward_exp", 0)),
               "reward_gold": chosen.get("reward_gold", sqd.get("reward_gold", 0)),
               "reward_item": chosen.get("reward_item", sqd.get("reward_item"))}
        # v124 分支 flag：写入 giver NPC 的 flag 桶（称号/后续任务判定用）
        _cf = chosen.get("flag")
        if _cf:
            db.set_talk_flag(group_id, qq_id, sqd.get("giver", ""), _cf)
    # 收集类：扣除材料
    if obj.get("collect"):
        need = obj.get("collect_count") or obj.get("count", 1)  # v125.1 P2：s64 等 collect_count 无 count 不再 KeyError
        for _ in range(need):
            db.remove_item(group_id, qq_id, _ckey)
        # v126.2：鱼获个体属性在 item_data.tags，remove_item 自动截断，无需额外同步
    # v124 交付剧情文本（无分支时）
    dt = sqd.get("deliver_text")
    if dt and not br:
        lines.append(f"  📖 {dt}")
    # v124.3：奖励统一走 _grant_quest_rewards（exp/gold/升级 + reward_item 全格式 +
    # reward_pet/reward_mount/unlock_class）——逻辑与支线原实现完全一致（列表随机 /
    # eq: 名册 / items→materials 顺序），返回结算后 player 供下方 _rule_fire 使用
    player = grant_quest_rewards(group_id, qq_id, sqd, lines)
    # v95.12：交付后保留条目标记 done（无 completed_side 列），防止 _offer_side_quests 自动重接
    quests["side"][sid] = {"status": "done"}
    db.save_quests(group_id, qq_id, quests)
    # v104 M20：行会委托每日（complete_side）——支线交付完成 +1，达标发奖
    _bump_daily_progress(group_id, qq_id, "complete_side", lines)
    lines.append(f"✅ 【支线完成】『{sqd['name']}』！")
    lines.append(f"  奖励：经验 +{sqd['reward_exp']} 金币 +{sqd['reward_gold']}")
    rep_line = quest_reputation(group_id, qq_id, sqd["giver"])
    if rep_line:
        lines.append(f"  {rep_line}")
    # v97.5 行为彩蛋规则：任务交付后
    _rule_txt = _rule_fire("quest_deliver", group_id, qq_id, player,
                           C.MAP_BY_ID.get(player.get("cur_map"), {}))
    if _rule_txt:
        lines.append(f"  {_rule_txt}")
    return lines

def talk_quest_progress(group_id, qq_id, npc_id) -> list:
    """v95.11：talk 型主线与目标 NPC 对话即达成（active 空进度遗留态 → ready）。
    覆盖 v95.9 对话化之前接取、或接取瞬间未置 ready 的存量档，返回通知行。
    v105 P0/P2：collect 型主线对话时实时数背包（材料足够 → ready）；
    explore 型主线已在目标地图 → ready（免出图重进）。"""
    quests = db.get_quests(group_id, qq_id)
    if quests.get("main_status") != "active":
        return []
    mid = quests.get("main_quest")
    if not mid:
        return []
    mq = next((q for q in C.MAIN_QUESTS if q["id"] == mid), None)
    if not mq:
        return []
    obj = mq.get("objective", {})
    if obj.get("talk") == npc_id:
        quests["main_status"] = "ready"
        quests["main_progress"] = {npc_id: 1}
        db.save_quests(group_id, qq_id, quests)
        return ["✨ 交谈完成！再与这位 NPC 对话即可交付任务。"]
    if obj.get("collect") and mq.get("giver") == npc_id:
        need = obj.get("count", 1)
        if db.count_item(group_id, qq_id, obj["collect"]) >= need:
            quests["main_status"] = "ready"
            quests["main_progress"] = {obj["collect"]: need}
            db.save_quests(group_id, qq_id, quests)
            return [f"✨ 材料已齐（{obj['collect']} ×{need}）！再与这位 NPC 对话即可交付任务。"]
    if obj.get("explore") and mq.get("giver") == npc_id:
        player = db.get_player(group_id, qq_id)
        if player.get("cur_map") == obj["explore"]:
            quests["main_status"] = "ready"
            quests["main_progress"] = {obj["explore"]: 1}
            db.save_quests(group_id, qq_id, quests)
            return ["✨ 目标地点已到达！再与这位 NPC 对话即可交付任务。"]
    return []

# ---------------- v95.23 职业就职 / 导师转职 ----------------

def update_use_quests(group_id, qq_id, item_name):
    """v124 use 目标支线：使用指定物品后支线置 ready（如 递麦酒/用月鳞/交信物）。
    v124.2 防跨图白嫖：objective.map 或任务自身 map 配置时，须玩家当前地图一致才推进；
    objective 无 map 且任务无 map 的保持原行为（不校验直接推进）。"""
    if not item_name:
        return ""
    quests = db.get_quests(group_id, qq_id)
    side = quests.get("side") or {}
    lines = []
    changed = False
    for sid, sq in list(side.items()):
        if sq.get("status") != "active":
            continue
        sqd = next((q for q in C.SIDE_QUESTS if q["id"] == sid), None)
        if not sqd:
            continue
        obj = sqd.get("objective") or {}
        if obj.get("use") and obj["use"] == item_name:
            _need_map = obj.get("map") or sqd.get("map")
            if _need_map:
                _pm = db.get_player(group_id, qq_id) or {}
                if _pm.get("cur_map") != _need_map:
                    continue
            side[sid] = {"status": "ready", "progress": {"use": item_name}}
            changed = True
            giver = C.NPCS.get(sqd["giver"]) or C.ALL_WILD.get(sqd["giver"]) or {}
            lines.append(f"✨ 『{sqd['name']}』目标达成！回去找 {giver.get('name', '发布人')} 交付吧～")
    if changed:
        quests["side"] = side
        db.save_quests(group_id, qq_id, quests)
    return "\n".join(lines)

def branch_wait_sid(group_id, qq_id):
    """v124：查找处于分支等待状态的支线 sid（ready + branch_wait）。"""
    quests = db.get_quests(group_id, qq_id)
    for sid, sq in (quests.get("side") or {}).items():
        if sq.get("status") == "ready" and sq.get("branch_wait"):
            return sid
    return None

def quest_kill_progress(group_id, qq_id, monster):
    """战斗后更新任务进度（主线/支线/每日击杀型），返回通知行——combat._update_quests 击杀段原样随迁。

    v181 P4-2：combat._update_quests 的 quest 段（主线/支线 kill/kill_any + 每日 kill_any/elite/boss）
    收敛本函数，combat 只留调用壳；周常悬赏 weekly_bump_kill 属 weekly 域不随迁（调用方自行追加）。
    匹配规则 v105 M19 P2 前缀精确（== 或 「目标·」开头）；每日结算走 services.quests.settle_daily_quest
    （P4-1 试点已收敛单点）。kill_any 支线用 progress.any（v95.13 防卡死）。
    """
    lines = []
    quests = db.get_quests(group_id, qq_id)
    changed = False
    # 主线（仅处理已接且进行中的任务；击杀达到目标则变为可交状态）
    main_id = quests.get("main_quest")
    if main_id:
        mq = next((q for q in C.MAIN_QUESTS if q["id"] == main_id), None)
        if mq and quests.get("main_status") == "active":
            prog = dict(quests.get("main_progress", {}))
            obj = mq["objective"]
            if obj.get("kill") and (monster["name"] == obj["kill"] or monster["name"].startswith(obj["kill"] + "·")):
                # v95.7 #33：精英/头目变体名包含目标怪名（如『野猪』←『野猪·首领』）也计入任务进度
                # v105 M19 P2：进度 key 统一记 obj['kill']（此前记 monster['name']，杀精英变体时
                # 计数入账但面板按 obj['kill'] 读 → 显示 0/N；现精英击杀也计入基础怪 key）
                # v104 M20 P2：in 后缀包含误伤面过大（『野猪』命中巨型野猪/风车野猪/铁甲野猪/
                # 岛野猪，『霜巨魔』顶 3 只霜巨魔王），改前缀精确：== 或 「目标·」开头，仅命中
                # 同名怪与「·」后缀精英/Boss 变体
                prog[obj["kill"]] = prog.get(obj["kill"], 0) + 1
                quests["main_progress"] = prog
                changed = True
                if prog.get(obj["kill"], 0) >= obj["count"]:
                    quests["main_status"] = "ready"
                    _g = C.NPCS.get(mq["giver"]) or C.ALL_WILD.get(mq["giver"]) or {}
                    lines.append(f"📜 主线『{mq['name']}』目标达成！回去找 {_g.get('name', '？')} {deliver_hint(mq['giver'])}吧～")
                else:
                    lines.append(f"📜 主线『{mq['name']}』：{prog[obj['kill']]}/{obj['count']}")
    # 每日
    # v94：先清跨天任务（daily 里 _date 不是今天 → 清空），避免旧任务残留
    if db.expire_daily(quests):
        changed = True
    daily = dict(quests.get("daily", {}))
    # v125.1 P0 修复：跳过全部元数据键（_date/_completed/_repeat）——原只跳过 _date，
    # _completed(int)/_repeat(dict) 被 dq["objective"] 下标 → TypeError 每日首战必崩
    for dkey, dq in list(daily.items()):
        if dkey in DAILY_META_KEYS:  # 跨天/计数元数据，不是任务
            continue
        dobj = dq["objective"]
        prog = dq.get("progress", 0)
        if dobj.get("kill_any"):
            prog += 1
        elif dobj.get("kill_elite") and monster.get("is_elite"):
            prog += 1
        elif dobj.get("kill_boss") and monster.get("is_boss"):
            prog += 1
        dq["progress"] = prog
        changed = True
        if prog >= dobj.get("kill_any", dobj.get("kill_elite", dobj.get("kill_boss", 99))):
            # v125.1 P2：发奖结算统一走 settle_daily_quest（与 world 非击杀 bump 同单点；
            # 击杀型每日在此接线，防刷上限/衰减对击杀型同样生效）
            settle_daily_quest(group_id, qq_id, daily, dq, lines)
            del daily[dkey]
    # 无条件写回：即使全部完成（daily 为空）也要清空 quests，否则任务残留会无限重复发奖励
    quests["daily"] = daily
    # 支线（击杀型）
    side = dict(quests.get("side", {}))
    for sid, sq in list(side.items()):
        if sq.get("status") != "active":
            continue
        sqd = next((q for q in C.SIDE_QUESTS if q["id"] == sid), None)
        if not sqd:
            continue
        obj = sqd["objective"]
        if obj.get("kill_any"):
            # v95.13 修复：kill_any 支线（护送商货等）此前无计数分支，任务永久卡死
            prog = dict(sq.get("progress", {}))
            prog["any"] = prog.get("any", 0) + 1
            sq["progress"] = prog
            changed = True
            if prog["any"] >= obj["kill_any"]:
                sq["status"] = "ready"
                _g = C.NPCS.get(sqd["giver"]) or C.ALL_WILD.get(sqd["giver"]) or {}
                lines.append(f"📜 支线『{sqd['name']}』目标达成！回去找 {_g.get('name', '？')} {deliver_hint(sqd['giver'])}吧～")
            else:
                lines.append(f"📜 支线『{sqd['name']}』：{prog['any']}/{obj['kill_any']}")
        elif obj.get("kill") and (monster["name"] == obj["kill"] or monster["name"].startswith(obj["kill"] + "·")):
            # v105 M19 P2：进度 key 统一记 obj['kill']（与主线一致、与面板/交付校验读取一致）
            # v104 补测发现：支线此前只精确 ==（杀精英变体不推进），现与主线同款前缀精确匹配
            # v104 M20 P2：in 后缀包含误伤面过大（『盗贼』命中盗贼头目·黑鸦、『霜巨魔』顶 3 只
            # 霜巨魔王、『月狼』命中月狼王·银鬃），改前缀精确：== 或 「目标·」开头
            prog = dict(sq.get("progress", {}))
            # v105 M19 P2：进度 key 统一记 obj['kill']（与主线一致、与面板/交付校验读取一致）
            prog[obj["kill"]] = prog.get(obj["kill"], 0) + 1
            sq["progress"] = prog
            changed = True
            if prog.get(obj["kill"], 0) >= obj["count"]:
                sq["status"] = "ready"
                _g = C.NPCS.get(sqd["giver"]) or C.ALL_WILD.get(sqd["giver"]) or {}
                lines.append(f"📜 支线『{sqd['name']}』目标达成！回去找 {_g.get('name', '？')} {deliver_hint(sqd['giver'])}吧～")
            else:
                lines.append(f"📜 支线『{sqd['name']}』：{prog[obj['kill']]}/{obj['count']}")
    if side:
        quests["side"] = side
    if changed:
        db.save_quests(group_id, qq_id, quests)
    return lines
