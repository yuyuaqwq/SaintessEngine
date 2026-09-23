# -*- coding: utf-8 -*-
"""随机产出形状 —— 掉落池 / 档位阶梯 / 槽位挂载 / 加权抽取原语 —— 扩展包 `ext_loot` 的门面。

原在 `saintess_engine/` 里，2026-09-23 包栈重构时抽成扩展包（模块内容未改，只改
了指向引擎的相对导入）。数据包要用：`game.json` 里声明 `"depends": ["ext_loot"]`。

本文件把原引擎门面导出的那批符号照原样转出去，外部只需把
`from saintess_engine import X` 改成 `from ext_loot import X`。
"""
from .loot import (pick_weighted, pick_many, pick_index, roll_range, weigh, total_weight, LootTable, SimpleCtx, register_strategy, strategy_names, get_strategy, strategy_spec, STRATEGIES, UnknownStrategy, TierTable, count_for, draw_slots, pity_force, pity_advance)
from . import loot

__all__ = [
    "loot",
    "pick_weighted", "pick_many", "pick_index", "roll_range", "weigh", "total_weight",
    "LootTable", "SimpleCtx", "register_strategy", "strategy_names", "get_strategy", "strategy_spec",
    "STRATEGIES", "UnknownStrategy", "TierTable", "count_for", "draw_slots", "pity_force",
    "pity_advance",
]
