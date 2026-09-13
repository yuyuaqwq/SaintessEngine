# -*- coding: utf-8 -*-
"""包内坐骑逻辑（`content/mounts.py`）—— 游戏仓 `game/core/mounts.py`（47 行）**逐字端口**（B13-L7）。

正文一字未改，只换一处「宿主取件」：
    `from ..data import MOUNT_BY_KEY, MOUNT_DROP_BOSS, MOUNT_DROP_ELITE`
      →  宿主 `data` 句柄（函数内解析，取到的是**宿主那三张表对象**，只读）

为什么没切包内域：`editor/domains.json` **无 mounts 域**、包内无 `content/data/mounts.json`
（实测 66 域清单里没有它）→ 按 BRIEF §5 口径「不确定 / 无同名域 → 宿主句柄 + 缺口登记」。
缺口：MOUNT_POOL / MOUNT_BY_KEY / MOUNT_DROP_ELITE / MOUNT_DROP_BOSS 四张表仍未进包，
待 B14 建域（导出器 `derive_*`）后切包内读口。
"""
from __future__ import annotations

import importlib
import random
import sys

_HOST_PKG = "data.plugins.dragonfall.game"
_HOST_PKG_FALLBACK = "game"
_INJECTED = {}


def bind_host(**objs):
    """宿主替身注入（幂等）——键 = 模块名（`data`）。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def lazy_host_module(full_name: str):
    """按**完整模块名**包一个惰性宿主模块句柄 —— 宿主薄壳用它注入自己那棵树的模块：:

        _M.bind_host(data=_M.lazy_host_module(__package__.rsplit(".", 1)[0] + ".data"))

    为什么必须由薄壳注入全名：同一进程里可能并存 `game.*` 与 `data.plugins.dragonfall.game.*`
    两套模块树（plan §8-R2；`tests/` 两种 import 都有）—— 写目标（`_INDEXES` / `MONSTER_LOCS` /
    派生表）必须落在**调用方那棵树**上，否则另一棵树读到空表。
    """
    import importlib

    class _Mod:
        def __getattr__(self, attr):
            return getattr(importlib.import_module(full_name), attr)

    return _Mod()


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
    raise RuntimeError("mounts：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (name, last))


def _tables():
    """宿主 `game.data` 的坐骑表（真源 `from ..data import MOUNT_*`）。"""
    d = _host_module("data")
    return d.MOUNT_BY_KEY, d.MOUNT_DROP_BOSS, d.MOUNT_DROP_ELITE


def make_mount_rein(mount_key):
    MOUNT_BY_KEY, _drop_boss, _drop_elite = _tables()
    m = MOUNT_BY_KEY[mount_key]
    return {"name": f"{m['name']}缰绳", "type": "坐骑", "mount_key": mount_key, "stackable": True,
            "price": 300, "desc": f"使用后可获得坐骑『{m['name']}』"}


def roll_mount_drop(role: str):
    """战斗胜利按怪物角色掷坐骑缰绳掉落，返回 mount_key 或 None。
    q7-3：单次分档随机（cumulative 区间法）替代链式独立伯努利——原 for 循环若前项命中
    即 return，后项名义概率被前项截流（如狮鹫名义 1% → 有效 ≈0.84%）。现一次 random.random()
    按权重归一化取一根，保持各坐骑名义概率 = 实际概率。"""
    _by_key, MOUNT_DROP_BOSS, MOUNT_DROP_ELITE = _tables()
    tbl = MOUNT_DROP_BOSS if role == "boss" else (MOUNT_DROP_ELITE if role == "elite" else None)
    if not tbl:
        return None
    total = sum(p for p in tbl.values())
    # 一次 uniform 抽签：r ∈ [0, total) 命中（掉落总概率=total）；≥total 则不掉落。
    # 命中分支按累计区间分摊，各坐骑实际概率 = 名义概率，且不改变总掉落率（非必中）。
    r = random.random()
    if r >= total:
        return None
    acc = 0.0
    for mk, prob in tbl.items():
        acc += prob
        if r < acc:
            return mk
    return None


# 坐骑效果字段（v101.11 新增效果统一入口；加效果 = 数据层加字段 + 本函数加 key + 消费点调用）
_MOUNT_EFFECT_KEYS = ("discount", "elite_bonus", "stamina_reduce", "sell_bonus",
                      "collect_bonus", "fish_bonus", "exp_mult")


def mount_effects(player: dict) -> dict:
    """活跃坐骑效果汇总：{discount, elite_bonus, stamina_reduce, sell_bonus,
    collect_bonus, fish_bonus, exp_mult}。未骑乘/未知坐骑返回空 dict。"""
    MOUNT_BY_KEY, _drop_boss, _drop_elite = _tables()
    mounts = (player or {}).get("mounts") or {}
    active_mk = mounts.get("active")
    if not active_mk or active_mk not in MOUNT_BY_KEY:
        return {}
    m = MOUNT_BY_KEY[active_mk]
    return {k: m.get(k, 0) for k in _MOUNT_EFFECT_KEYS}


__all__ = ["make_mount_rein", "roll_mount_drop", "mount_effects", "bind_host"]
