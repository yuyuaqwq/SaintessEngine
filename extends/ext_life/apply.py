# -*- coding: utf-8 -*-
"""`ext_life` 的入口 —— 按包契约提供 `install_engine()`。

本包是**纯形状库**（`Tally` / `TierBoard` / `PeriodCounter` / `Streak` / `Cooldown` /
`Timers` / `Unlocks`），不往引擎任何注册表里塞东西：

* `collect` —— 判据（`hit` / `reached` / `claimable`）与**已领集合**都是调用方注入的
  回调与活集合，模块级只有三个状态字面量（`LOCKED` / `READY` / `CLAIMED`）。
* `periodic` —— `read`/`write` 一对可调用就是全部存储面，模块级零可变状态。
* `timers` —— 「类型注册表」挂在 `Timers` **实例**上（`register` 是实例方法），
  不是模块级全局注册表；`store` / `clock` 同样由调用方注入。
* `unlock` —— 条目表由数据包的 `unlock_kinds` 域声明、条件真源是外部传进来的
  `conditions.Conditions` 实例；本模块不新建判据语言，也不注册任何东西。

所以这里没有「安装动作」—— 入口存在是为了满足包契约（`content/apply.py` 惯例的
扩展包版本：包根 `apply.py`），并且让 `load_stack()` 的加载链对两种包完全同形。

数据包要用它：在 `game.json` 里声明 `"depends": ["ext_life"]`，
然后 `from ext_life.timers import Timers`（或对应子模块）直接取用。
"""
from __future__ import annotations


def install_engine() -> None:
    """本包没有引擎级装配（纯形状库）—— 保留函数体为空且显式说明，不留含糊的空壳。"""
    return None
