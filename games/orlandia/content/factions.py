# -*- coding: utf-8 -*-
"""包内阵营声望（`content/factions.py`）—— 游戏仓 `game/core/factions.py`（14 行）**逐字端口**（B13-L7）。

正文一字未改，只换一处「宿主取件」：
    `from ..data import REPUTATION_TIERS`  →  宿主 `data` 句柄（`game/data/factions.py:20`，
    装配后由 `game/data/__init__.py:56` 挂到 `game.data` 上）

为什么没切包内域：`editor/domains.json` **无 factions/reputation 域**、包内无对应 JSON
（实测 66 域清单里没有它）→ 按 BRIEF §5 口径「无同名域 → 宿主句柄 + 缺口登记」。
缺口：`REPUTATION_TIERS`（及 FACTIONS / FACTION_ORDER / AREA_FACTION / CHRONICLES）仍未进包，
待 B14 建域后切包内读口。
"""
from __future__ import annotations

import importlib
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
    raise RuntimeError("factions：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (name, last))


def faction_reputation_tier(points: int) -> str:
    """声望点数 → 等级名"""
    name = "陌生"
    for th, n in _host_module("data").REPUTATION_TIERS:
        if points >= th:
            name = n
    return name


__all__ = ["faction_reputation_tier", "bind_host"]
