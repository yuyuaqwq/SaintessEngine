# -*- coding: utf-8 -*-
"""生活循环形状 —— 收集计数 / 周期 / 倒计时 / 解锁闸门 —— 扩展包 `ext_life` 的门面。

原在 `saintess_engine/` 里，2026-09-23 包栈重构时抽成扩展包（模块内容未改，只改
了指向引擎的相对导入）。数据包要用：`game.json` 里声明 `"depends": ["ext_life"]`。

本文件把原引擎门面导出的那批符号照原样转出去，外部只需把
`from saintess_engine import X` 改成 `from ext_life import X`。
"""
# ★ 审计 L345（2026-09-30）：`unlock` 已从**门面退役** —— 生产零消费（三仓 + 宿主 grep
#   无 `ext_life.unlock` / `Unlocks` 等引用；唯一消费走子模块路径，且仅本包测试）。
#   子模块本身仍在：要用就 `from ext_life.unlock import Unlocks`（README / 参考页照旧
#   指向子模块路径）。本文件不再转出它的名字，`__all__` 也不再含 `unlock`。
from .collect import (CLAIMED, LOCKED, READY, Tally, TierBoard, tier_state)
from .periodic import (PeriodCounter, PeriodLimitExceeded, PeriodSlot, Streak, Cooldown)
from .timers import (TimerStorageError, Timers)
from . import collect, periodic, timers

__all__ = [
    "collect",
    "periodic",
    "timers",
    "CLAIMED", "LOCKED", "READY", "Tally", "TierBoard", "tier_state",
    "PeriodCounter", "PeriodLimitExceeded", "PeriodSlot", "Streak", "Cooldown", "TimerStorageError",
    "Timers",
]
