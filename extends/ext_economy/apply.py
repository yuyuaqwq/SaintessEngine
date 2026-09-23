# -*- coding: utf-8 -*-
"""`ext_economy` 的入口 —— 按包契约提供 `install_engine()`。

交易 / 货架 / 计时生产都是**纯形状库**（`DailyLimit` / `Shelf` / `Jobs` …），
不往引擎任何注册表里塞东西，也不声明 `provides`：装不装这个包，引擎其它部分行为一致。
所以这里没有「安装动作」—— 入口存在是为了满足包契约（`content/apply.py` 惯例的
扩展包版本：包根 `apply.py`），并且让 `load_stack()` 的加载链对两种包完全同形。

数据包要用它：在 `game.json` 里声明 `"depends": ["ext_economy"]`，
然后 `from ext_economy.trade import DailyLimit, apply_rate, settle_sale`、
`from ext_economy.shelf import Shelf`、`from ext_economy.produce import Job, Jobs` 直接取用。
"""
from __future__ import annotations


def install_engine() -> None:
    """本包没有引擎级装配（纯形状库）—— 保留函数体为空且显式说明，不留含糊的空壳。"""
    return None
