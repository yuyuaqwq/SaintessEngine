# -*- coding: utf-8 -*-
"""计数保底（pity）—— 连续 N 次未命中「高档」→ 下一次强制命中。

**零知识**：引擎只认 `streak`（连续未中次数）与 `threshold`（保底阈值）；
**阈值取值与「什么算命中」全由内容侧给**（同 `count_for` 的 `extra_chance` 口径：
引擎只算数，取值不留引擎）。

形状::

    from saintess_engine.loot import pity_force, pity_advance

    if pity_force(streak, 3):              # 连续 3 次未中 → 本次保底
        ...                                # 保底那一项怎么挑，仍由调用方的 rng 决定
    streak = pity_advance(streak, hit)     # 命中归零 / 未中 +1

`streak` 由**调用方持有**（存档 / 条目个体字段是内容侧的形状），本模块只两个纯函数，
**不引入随机数、不持有状态** —— 所以它既能跑在命令层，也能跑在结算层。
"""
from __future__ import annotations

__all__ = ["pity_force", "pity_advance"]


def pity_force(streak: int, threshold: int) -> bool:
    """连续 `streak` 次未命中，且 `streak >= threshold` → 本次应强制命中。"""
    return int(streak) >= int(threshold)


def pity_advance(streak: int, hit: bool) -> int:
    """保底计数推进：命中 → 归零；未命中 → +1。"""
    return 0 if hit else int(streak) + 1
