# -*- coding: utf-8 -*-
"""随机产出形状 —— 掉落池 / 档位阶梯 / 槽位挂载。

**零知识**：引擎不知道「掉落」「品质」「词条」这些词，只认 `pool` / `entry` / `ref` /
`tier` / `count`；**池里的内容、档位的取值、引用的前缀**全由内容侧给。

四件东西::

    from saintess_engine.loot import LootTable, TierTable, SimpleCtx
    from saintess_engine.loot import pick_weighted, pick_many, roll_range, draw_slots, count_for

    # 池 + 策略（内容侧把池数据 / 引用解析 / 自定义策略挂进来）
    t = LootTable(pools, resolver=my_resolver, strategies={"fish": my_fish},
                  inline_prefixes=("gold:", "item:"), pool_key_prefixes=("weighted:",))
    t.roll("gather:oak_plain", ctx, qty=2); t.expand("chest:wild_low"); t.audit()

    # 档位阶梯（品质那一类）
    T = TierTable(["white", "green", "blue", "purple", "orange"], info={...},
                  weights_by_level={1: [...], 3: [...], 9: [...]}, aliases={"white": "白"})
    T.weights_at(4); T.pick(level=4, exclude=("orange")); T.upgrade("blue", chance=0.05)

    # 随机原语 / 挂载 / 条数
    pick_weighted(entries); pick_many(ids, 3, weighted=True)
    draw_slots(pool_ids, 3, fixed=("series_mark",))
    count_for({"orange": [3, 4]}, "orange", extra_chance=0.20)

**rng 注入**：所有随机都走传入的 `rng`（默认标准库 `random`）—— 这是「可复现 + 可逐格比对」的前提。
细节与形状判据见 `docs/engine-wiki/reference/loot.md`。
"""
from __future__ import annotations

from .mount import draw_slots
from .pick import pick_index, pick_many, pick_weighted, roll_range, total_weight, weigh
from .pity import pity_advance, pity_force
from .pool import (STRATEGIES, LootTable, SimpleCtx, get_strategy, register_strategy,
                   strategy_names, strategy_spec)
from .tier import TierTable, count_for

__all__ = [
    # 原语
    "pick_weighted", "pick_many", "pick_index", "roll_range", "weigh", "total_weight",
    # 池
    "LootTable", "SimpleCtx", "register_strategy", "strategy_names", "get_strategy",
    "strategy_spec", "STRATEGIES",
    # 档位 / 挂载
    "TierTable", "count_for", "draw_slots",
    # 计数保底
    "pity_force", "pity_advance",
]
