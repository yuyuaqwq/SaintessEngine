# -*- coding: utf-8 -*-
# ==============================================================================
# 包内实现（唯一真源）· B13-L2（2026-09-14）—— 逐字搬自宿主
#   `qqbot/data/plugins/dragonfall/game/core/daily_events.py`
# 搬运改动面**只有「宿主取件」**一类：`DAILY_MAP_EVENTS` → 宿主句柄 `_host_attr("data.daily_events", …)`
# 宿主同名文件 = 薄壳（指向本模块，见那边的头注）。
# ==============================================================================
"""《奥兰迪亚·余烬纪年》今日奇遇核心（v115）

日期哈希从 DAILY_MAP_EVENTS 中为某张野外图选出"今日奇遇"变体。
同一天全服一致（参考 game/core/wild.py::_day_hash 的 seed×2654435761+salt 设计）。

调用方（v115）：
  - game/commands/combat.py :: explore()——取今日奇遇的 effects 微调探索数值
  - game/commands/world.py :: map_view()——地图面板底部显示今日奇遇行
"""
import datetime
import importlib
import sys


# ============================================================
# ① 宿主替身口（B13-L2 搬包 2026-09-14；正文 `db.xxx(...)` / `C.xxx` 一行未改）
#    写法照抄包内 `content/world_cmds.py`（B9 线2）：注入优先 → sys.modules → importlib，
#    取不到**大声抛**（绝不静默空跑）。
# ============================================================
_HOST_PKG = "data.plugins.dragonfall.game"      # 运行时（main.py 的模块路径）
_HOST_PKG_FALLBACK = "game"                     # 测试/工具按 `game.xxx` 直接 import 时
_INJECTED = {}


def bind_host(**objs):
    """宿主薄壳 import 期注入（幂等）——键 = `_HostMod` 的模块名（`db` / `content`）。"""
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
    raise RuntimeError("B13-L2：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (name, last))


def _host_attr(mod: str, attr: str):
    """宿主模块属性 —— 真源「`from ..<mod> import <attr>`」的同义替身（调用时解析）。"""
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
    """宿主模块替身（`db` / `C`）——`db.xxx` / `C.xxx` 正文一字未改，属性访问时解析。"""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return getattr(_host_module(self._name), attr)


def _daily_map_events() -> dict:
    """宿主数据表 `DAILY_MAP_EVENTS`（真源模块级 `from ..data.daily_events import …`）。

    域未进包（`content/data/` 无 daily_events.json）→ 宿主句柄（缺口登记见报告）；
    **不准在包内新建第二份表**。调用时解析（import 期零宿主接触 = 包可独立加载）。
    """
    return _host_attr("data.daily_events", "DAILY_MAP_EVENTS")


def __getattr__(name):
    """PEP 562：真源顶层名兼容（`DAILY_MAP_EVENTS` 惰性解析）。"""
    if name == "DAILY_MAP_EVENTS":
        return _daily_map_events()
    raise AttributeError(name)


def _day_hash(seed: int, salt: str = "") -> int:
    h = seed * 2654435761 + (sum(ord(c) for c in salt) if salt else 0)
    return h & 0x7FFFFFFF


def today_map_event(map_id, now=None):
    """当前位置地图的今日奇遇（日期哈希选中，同一天全服一致）。

    参数：
      map_id : 地图 id（仅 `野外` 类型迁移图有配置）
      now    : datetime.date / datetime.datetime / None（默认今天）
    返回：
      选中的变体 dict（含 id/name/desc/effects），无配置返回 None。
    """
    variants = _daily_map_events().get(map_id)
    if not variants:
        return None
    _now = now or datetime.date.today()
    if isinstance(_now, datetime.datetime):
        ordinal = _now.date().toordinal()
    else:
        ordinal = _now.toordinal()
    # 用 map_id 作 salt，避免不同图同 seed 顶到同一下标的比例失配
    idx = _day_hash(ordinal, "daily:" + map_id) % len(variants)
    return variants[idx]


def today_event_effects(map_id, now=None):
    """今日奇遇的 effects 合并结果；无奇遇返回 {}。

    供 combat.py explore() 直接 .get 消费；
    注意：请不要直接修改返回 dict（内部持有数据引用）。
    """
    ev = today_map_event(map_id, now)
    if not ev:
        return {}
    return ev.get("effects") or {}
