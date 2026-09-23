# -*- coding: utf-8 -*-
"""`ext_social` 的入口 —— 按包契约提供 `install_engine()`。

本包是**纯形状库**，没有模块级副作用，也没有要往引擎注册表里塞的东西：

* `presence` 只从引擎取通用守卫（`saintess_engine._validators` 的 `callable_of` /
  `int_of` / `number_of`），不 import 任何游戏形状、不认识任何字段名；
* `membership` 连引擎都不 import —— 名单（`Roster`）是**注入**进来的引用
  （`roster=` 可选注入面），按鸭子类型取用它的口（`is_member` / `members` / `join`），
  本包不持有、不复制成员集合。

所以这里没有「安装动作」—— 入口存在是为了满足包契约（包根 `apply.py`），
并让 `load_stack()` 的加载链对两种包完全同形（与 `ext_quest` 同款）。

数据包要用它：在 `game.json` 里声明 `"depends": ["ext_social"]`，然后
`from ext_social.presence import Presence, Lookup, day_slot, day_hit, guarded_roll` /
`from ext_social.membership import RoleSlots, Contribution, Applications` 直接取用。
"""
from __future__ import annotations


def install_engine() -> None:
    """本包没有引擎级装配（纯形状库）—— 保留函数体为空且显式说明，不留含糊的空壳。"""
    return None
