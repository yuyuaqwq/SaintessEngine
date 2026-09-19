# -*- coding: utf-8 -*-
"""参数校验的共用底座 —— 六个形状模块原先各自抄了一份的「同款入参守卫」。

为什么有它
----------
`produce` / `timers` / `periodic` / `presence` / `collect` / `trade` 各自抄了同一套守卫：
`_now` ×2（逐字相同）· `_callable_of` ×3 · `_number_of` ×2 · `_n_of` / `_cap_of` /
`_positive_int_of` / `_check_n` / `_check_cap` 各一份。它们是**同一条纪律**：

  · `bool` 不算整数 / 数值 —— 它是 `int` 的子类，混进来会静默变成 0/1；
  · 坏值一律**抛**（不静默当 0：计数键上出现非数字 = 存档被外部写坏，
    当成 0 会让玩家白拿一次额度）；
  · 时钟必须给整数秒。

收成单点后纪律只有一处可改；**取值语义仍留在调用方**（本模块不认识任何字段名，
只认「值 + 标签 + 下界」三样东西）。
"""
from __future__ import annotations

from typing import Any, Callable, Optional

__all__ = ["callable_of", "clock_now", "int_of", "number_of"]


def int_of(value: Any, label: str, *, minimum: Optional[int] = None) -> int:
    """整数校验（`bool` 不算整数）；`minimum` 给了就同时判下界。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} 必须是整数，收到 {type(value).__name__}：{value!r}")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} 必须 >= {minimum}，收到 {value!r}")
    return value


def number_of(value: Any, label: str) -> float:
    """数值校验（`bool` 不算数值）→ `float`。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} 必须是数值，收到 {type(value).__name__}：{value!r}")
    return float(value)


def callable_of(fn: Any, label: str) -> Callable:
    """可调用校验（原样返回，供装配期一次性绑定）。"""
    if not callable(fn):
        raise TypeError(f"{label} 必须可调用，收到 {type(fn).__name__}：{fn!r}")
    return fn


def clock_now(clock: Callable[[], Any], now: Optional[int]) -> int:
    """时钟取值：`now is None` → 现取 `clock()`；一律要求整数秒（`bool` 不算）。"""
    value = clock() if now is None else now
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"时钟必须给整数秒，收到 {type(value).__name__}：{value!r}")
    return int(value)
