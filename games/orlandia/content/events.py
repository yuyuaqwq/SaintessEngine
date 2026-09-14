# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— 探索事件抽签实现（B13 线3，2026-09-14）。

真源：游戏仓 `game/core/events.py`（77 行：`roll_explore_event` / `roll_explore_egg`）。
本模块 = 那个模块的**实现本体**（两个函数逐字搬）；宿主 `game/core/events.py` 只剩
再导出（`roll_explore_event` / `roll_explore_egg` / `current_season` / 五个宿主数据符号）。

正文改动面（**只有一类**：函数体里的宿主取件）
----------------------------------------------
| 真源写法 | 包内替身 | 说明 |
|---|---|---|
| `from ..data import EVENT_WEIGHT_SUM, EXPLORE_EVENTS, EXPLORE_EGG_CHANCE, EXPLORE_EGG_EVENTS, EXPLORE_EGG_SUM` | 本模块顶层再导出同 6 名 + `_src(name)` 读**本模块全局** | ★ W2b 起**不再回宿主**：名从包内真源再导出（见下），`_src` = `globals()[name]`，与真源「函数体查本模块全局」逐字同义 |
| `from .time_weather import current_season`（B13 线2 落点） | 同上（`current_season` 在顶层再导出） | 真源语义就是「调用时查本模块全局名」⇒ `content.events.current_season = …` 打桩**照旧生效**（`tests/test_v116_explore_season.py` / `overnight/w1213_b13l3_snap.py` 已同步把打桩目标改到 `content.events`） |

★ W2b 去宿主（2026-09-15）
--------------------------
六个名字（`EXPLORE_EVENTS` / `EXPLORE_EGG_EVENTS` / `EXPLORE_EGG_CHANCE` / `EXPLORE_EGG_SUM` /
`EVENT_WEIGHT_SUM` / `current_season`）从**包内真源**再导出：
`content/catalog_quests`（两个池）· `content/catalog_rules`（三个派生/常量）·
`content/time_weather`（当前季节）。`_src(name)` = `globals()[name]`（取不到 → 大声抛，
不静默兜底）。宿主薄壳 `game/core/events.py` 的 `from content.catalog_quests import …` 仍取同样的对象，
故 `game.core.events` 的同名面**数值/对象一字不变**。

★ 为什么**不用**包内 `events` 域读口（**历史缺口登记**；W2b 起读的是 catalog 门面，不是该域）
--------------------------------------------------------------------------------------------
包内 `content/data/events.json`（146 条）是宿主两个池的**合表派生**：
`scripts/export_domains/npc_story.py:307` 走 `sort_table()` = **外层键按字典序重排** +
注入 `source` 字段。而 `roll_explore_event` / `roll_explore_egg` 的**抽签顺序**就是行为：
`total = sum(weight)` 后 `acc += w; if r <= acc` 逐条累加 ⇒ 同样的随机数在不同顺序下命中不同事件。
实测：`EXPLORE_EVENTS`（100 条）与域内 `source=="explore"` 的键序**100/100 位置全不同**，
`EXPLORE_EGG_EVENTS`（46 条）同样不同（见报告 §1 核实表）。
⇒ 顺序不可逆（I3 不满足）→ **该 JSON 域读口不可用**。W2b 改读的是**保序的包内门面**
`content/catalog_quests.EXPLORE_EVENTS/EXPLORE_EGG_EVENTS`（与宿主旧面**同一对象**，实测 `is` 为真）。

★ 另一处历史缺口（W2b 已解）：`EVENT_WEIGHT_SUM` / `EXPLORE_EGG_SUM` 是**派生标量**（`sum(...)`），
导出器明写「不是表 → 不进本域」（`npc_story.py:247`）——但它们**在 `content/catalog_rules.py:256-257`
是真的**（与宿主旧面同一对象），本模块顶层再导出即得。

等价证据：`overnight/w1213_b13l3_snap.py`（124 用例含「季节打桩 / 蛋概率打桩 / 兜底不空池」）
· `overnight/W-B13-L3-events-dialogue.md`。
"""
from __future__ import annotations

import random

# ============================================================
# ① 包内真源再导出（★ W2b：不再回宿主取件）
# ------------------------------------------------------------
# 真源那 6 个名字**住在包内**：两个探索池在 catalog_quests、三个派生/常量在 catalog_rules、
# 当前季节在 time_weather。本模块顶层再导出，使 `_src(name)` 有全局可读；
# 且 `content.events.<名> = …` 打桩与真源「函数体查本模块全局」语义逐字一致。
# ============================================================
from .catalog_quests import EXPLORE_EVENTS, EXPLORE_EGG_EVENTS   # noqa: F401
from .catalog_rules import (EVENT_WEIGHT_SUM, EXPLORE_EGG_CHANCE,  # noqa: F401
                            EXPLORE_EGG_SUM)
from .time_weather import current_season                          # noqa: F401


def bind_host(**objs):
    """宿主注入位（历史接口）：本模块已**零宿主取件**，形参保留只为旧宿主壳照旧传参。"""
    return None


def _src(name: str):
    """真源本模块的**全局名** —— 直接读本模块全局（★ W2b：不再经宿主薄壳转一手）。

    ⚠️ 必须是**调用时**解析（每次读本模块 `__dict__`），这样 `content.events.<name> = …`
    这类打桩（真源语义：函数体查本模块全局）照旧生效。
    取不到 → **大声抛**（绝不静默兜底）。
    """
    try:
        return globals()[name]
    except KeyError:
        raise RuntimeError("events：本模块全局没有 %r —— 拒绝静默空跑" % (name,))


# v116 季节渗透：探索事件随季节变化（借鉴垂钓，见 core/fishing.py）
# - 事件 season 硬限定：非当季不触发；season_boost 偏好：当季权重 ×1.5
# - 季节码与 time_weather.current_season 对齐（spring/summer/autumn/winter）
# （真源此处 `from .time_weather import current_season` —— B13 线2 落点；W2b 起本模块顶层
#   直接再导出 `current_season`，`_src("current_season")` 读本模块全局 ⇒
#   `content.events.current_season = …` 打桩照旧生效）

# v116 季节感前缀：命中限定/偏好事件时附加给返回事件（浅拷贝，不污染数据池）
_SEASON_PREFIX = {"spring": "🌸", "summer": "☀️", "autumn": "🍂", "winter": "❄️"}


"""奥兰迪亚·余烬纪年数据层 - events.py"""
def roll_explore_event(exclude=()):
    """掷一个随机事件，返回事件 dict

    v101.30d #O22/O42：支持排除列表——同一玩家最近触发的常规事件不重复
    （短间隔去重，策划案 02 章 7.6）。排除后按剩余事件权重重掷。
    v116 季节渗透：season 硬限定（非当季剔除）、season_boost（当季权重 ×1.5）；
    若当前季节把池子过滤空则放宽季节限制重试，避免探索无事件。
    """
    EXPLORE_EVENTS = _src("EXPLORE_EVENTS")     # 真源 `from ..data import EXPLORE_EVENTS`
    # v116 当前季节
    season = _src("current_season")()

    def _season_ok(e):
        # 硬限定事件仅当季节匹配才触发；无 season 字段 = 全年可触发
        return not e.get("season") or e["season"] == season

    # 第一步：排除列表 + 季节硬限定 双重过滤
    if exclude:
        pool = [e for e in EXPLORE_EVENTS if e["id"] not in exclude and _season_ok(e)]
    else:
        pool = [e for e in EXPLORE_EVENTS if _season_ok(e)]
    if not pool:
        # 兜底：排除列表导致的例外，或当季硬限定事件占满池子 → 放宽季节限制重试
        pool = [e for e in EXPLORE_EVENTS if e["id"] not in exclude] if exclude else list(EXPLORE_EVENTS)
    if not pool:
        pool = list(EXPLORE_EVENTS)
    # v116 季节偏好：season_boost 匹配当前季节的事件权重 ×1.5（非限定，仅概率上升）
    total = sum(e["weight"] * (1.5 if e.get("season_boost") == season else 1) for e in pool)
    r = random.random() * total
    acc = 0
    for e in pool:
        w = e["weight"] * (1.5 if e.get("season_boost") == season else 1)
        acc += w
        if r <= acc:
            # v116 季节感输出：命中限定/偏好事件时附加前缀标记（浅拷贝，不污染数据池）
            if e.get("season") == season or e.get("season_boost") == season:
                pick = dict(e)
                pick["_season_prefix"] = _SEASON_PREFIX[season]
                return pick
            return e
    return pool[0]

def roll_explore_egg(cur_map_id=None):
    """探索彩蛋判定(02 章 7.5)：常规事件之外独立判定，命中返回蛋事件 dict。

    v97.6 区域彩蛋：事件带 maps（地图 id 列表）时仅对应地图可触发；
    无 maps 字段 = 全局彩蛋。命中后按"当前地图可触发的池子"权重分配。
    """
    EXPLORE_EGG_CHANCE = _src("EXPLORE_EGG_CHANCE")     # 真源 `from ..data import EXPLORE_EGG_CHANCE`
    EXPLORE_EGG_EVENTS = _src("EXPLORE_EGG_EVENTS")     # 真源 `from ..data import EXPLORE_EGG_EVENTS`
    if random.random() >= EXPLORE_EGG_CHANCE:
        return None
    pool = [e for e in EXPLORE_EGG_EVENTS
            if not e.get("maps") or (cur_map_id and cur_map_id in e["maps"])]
    if not pool:
        return None
    total = sum(e["weight"] for e in pool)
    r = random.random() * total
    acc = 0
    for e in pool:
        acc += e["weight"]
        if r <= acc:
            return e
    return pool[0]
