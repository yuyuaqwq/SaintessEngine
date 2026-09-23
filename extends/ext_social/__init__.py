# -*- coding: utf-8 -*-
"""成员关系与在场形状 —— 职位/贡献/申请 · 在场清单 —— 扩展包 `ext_social` 的门面。

原在 `saintess_engine/` 里，2026-09-23 包栈重构时抽成扩展包（模块内容未改，只改
了指向引擎的相对导入）。数据包要用：`game.json` 里声明 `"depends": ["ext_social"]`。

本文件把原引擎门面导出的那批符号照原样转出去，外部只需把
`from saintess_engine import X` 改成 `from ext_social import X`。
"""
from .membership import (RoleSlots, RoleNotAllowed, Contribution, Applications, QueueFull)
from .presence import (Lookup, Presence, day_slot, day_hit, minutes_left, guarded_roll, cooldown_ok, merge_tables)
from . import membership, presence

__all__ = [
    "membership",
    "presence",
    "RoleSlots", "RoleNotAllowed", "Contribution", "Applications", "QueueFull", "Lookup",
    "Presence", "day_slot", "day_hit", "minutes_left", "guarded_roll", "cooldown_ok",
    "merge_tables",
]
