# -*- coding: utf-8 -*-
# ==============================================================================
# 包内实现（唯一真源）· B13-L2（2026-09-14）—— 逐字搬自宿主
#   `qqbot/data/plugins/dragonfall/game/core/daily_events.py`
# 搬运改动面**只有「宿主取件」**一类：`DAILY_MAP_EVENTS` ← 宿主句柄。
# ★ B16-W8（2026-09-14）：该句柄**归包** —— `_daily_map_events()` 改读包内门面
#   `content/catalog_rules.py`（包内无 `daily_events` 域，缺口见 ① 与报告）；宿主面清零。
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


# ============================================================
# ① 包内数据读口（★ B16-W8 · 2026-09-14 宿主句柄归包）
#    真源模块级 `from ..data.daily_events import DAILY_MAP_EVENTS` = 宿主数据表；
#    宿主 `game/data/` 要删，本模块**零 `_HostMod` / 零 `_host_attr`**（import 期不碰宿主）。
#    包内域 `daily_events` **从未被导出器建过**（`content/data/` 无该 JSON，
#    `scripts/export_domains/*` 里也没有 `derive_daily_events`）⇒ 取值来源 =
#    包内门面 `content/catalog_rules.py:DAILY_MAP_EVENTS`（B14 收口建的尾部长尾名门面，
#    值由 `overnight/w2_gen_catalog_rules.py` 从宿主真源 import 后 pprint dump，逐字非手抄）。
#    实测：20 图 / 键序 / 逐值与本模块旧宿主句柄取到的表**全等**。
#    缺口登记（待主 agent 建域）：`DAILY_MAP_EVENTS` 在门面里挂在 `NOT_YET_DOMAINED`，
#    建域后本函数改读 `content/data/daily_events.json` 一行即可（本模块是唯一读口）。
# ============================================================
def _daily_map_events() -> dict:
    """包内表 `DAILY_MAP_EVENTS`（真源模块级 `from ..data.daily_events import …`）。

    延迟 import（调用时解析）⇒ 包加载期零依赖、无循环 import。
    **不准在包内新建第二份表**（同表两份定义必漂移）。
    """
    from .catalog_rules import DAILY_MAP_EVENTS as _tbl
    return _tbl


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
