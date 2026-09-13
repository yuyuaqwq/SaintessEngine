# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— 探索事件抽签实现（B13 线3，2026-09-14）。

真源：游戏仓 `game/core/events.py`（77 行：`roll_explore_event` / `roll_explore_egg`）。
本模块 = 那个模块的**实现本体**（两个函数逐字搬）；宿主 `game/core/events.py` 只剩
再导出（`roll_explore_event` / `roll_explore_egg` / `current_season` / 五个宿主数据符号）。

正文改动面（**只有一类**：函数体里的宿主取件）
----------------------------------------------
| 真源写法 | 包内替身 | 说明 |
|---|---|---|
| `from ..data import EVENT_WEIGHT_SUM, EXPLORE_EVENTS, EXPLORE_EGG_CHANCE, EXPLORE_EGG_EVENTS, EXPLORE_EGG_SUM` | 经宿主薄壳同名再导出解析：`_src("EXPLORE_EVENTS")` … | **不是**包内域读口，理由见下（顺序不可逆） |
| `from .time_weather import current_season`（B13 线2 落点） | `_src("current_season")()` | 同样经宿主命名空间：`tests/test_v116_explore_season.py:31` 直接给**宿主模块属性**打桩（`EV.current_season = lambda …`），真源语义就是「调用时查本模块全局名」——替身照抄这个语义 |

★ 为什么**不用**包内 `events` 域读口（缺口登记，不是偷懒）
--------------------------------------------------------
包内 `content/data/events.json`（146 条）是宿主两个池的**合表派生**：
`scripts/export_domains/npc_story.py:307` 走 `sort_table()` = **外层键按字典序重排** +
注入 `source` 字段。而 `roll_explore_event` / `roll_explore_egg` 的**抽签顺序**就是行为：
`total = sum(weight)` 后 `acc += w; if r <= acc` 逐条累加 ⇒ 同样的随机数在不同顺序下命中不同事件。
实测：`EXPLORE_EVENTS`（100 条）与域内 `source=="explore"` 的键序**100/100 位置全不同**，
`EXPLORE_EGG_EVENTS`（46 条）同样不同（见报告 §1 核实表）。
⇒ 顺序不可逆（I3 不满足）→ 本线按 BRIEF §5 口径**用宿主句柄 + 缺口登记**：
待 `events` 域补 `order` 字段（或改保序导出）后，再切包内读口。

★ 另一处缺口：`EVENT_WEIGHT_SUM` / `EXPLORE_EGG_SUM` 是**派生标量**（`sum(...)`），
导出器明写「不是表 → 不进本域」（`npc_story.py:247`），包内无读口 → 同走宿主再导出。

等价证据：`overnight/w1213_b13l3_snap.py`（124 用例含「季节打桩 / 蛋概率打桩 / 兜底不空池」）
· `overnight/W-B13-L3-events-dialogue.md`。
"""
from __future__ import annotations

import importlib
import random
import sys


# ============================================================
# ① 宿主取件口（注入优先 → sys.modules → importlib；**绝不静默空跑**）
# ============================================================
_HOST_PKG = "data.plugins.dragonfall.game"
_HOST_PKG_FALLBACK = "game"
_INJECTED = {}


def bind_host(**objs):
    """宿主薄壳 import 期注入（幂等）——本模块只用 `core.events` 命名空间，注入位备用。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _host_module(name: str):
    if name in _INJECTED:
        return _INJECTED[name]
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        m = sys.modules.get("%s.%s" % (prefix, name))
        if m is not None:
            return m
    last = None
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        try:
            return importlib.import_module("%s.%s" % (prefix, name))
        except Exception as exc:                # noqa: BLE001
            last = exc
    raise RuntimeError("events：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (name, last))


def _host_attr(mod: str, attr: str):
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


def _src(name: str):
    """真源本模块的**全局名** → 宿主薄壳同名再导出（`core.events.<name>`）。

    ⚠️ 必须是**调用时**解析（每次读宿主模块命名空间），这样 `EV.<name> = …` 这类
    打桩（真源语义：函数体查本模块全局）在薄壳化之后仍然生效。
    """
    return _host_attr("core.events", name)


# v116 季节渗透：探索事件随季节变化（借鉴垂钓，见 core/fishing.py）
# - 事件 season 硬限定：非当季不触发；season_boost 偏好：当季权重 ×1.5
# - 季节码与 time_weather.current_season 对齐（spring/summer/autumn/winter）
# （真源此处 `from .time_weather import current_season` —— B13 线2 落点；本模块经
#   `_src("current_season")` 取自宿主薄壳再导出，保住 `EV.current_season = …` 打桩语义）

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
