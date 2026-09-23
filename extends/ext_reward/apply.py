# -*- coding: utf-8 -*-
"""`ext_reward` 的入口 —— 按包契约提供 `install_engine()`。

本包当前是**纯形状库**（流水采集器 `BattleTLog` + 事件 kind 映射表 `EVENT_KINDS` +
复现键 `REPRO_KEYS`）：不往引擎任何注册表里塞东西 —— 装不装这个包，引擎其它部分行为一致。
所以这里没有「安装动作」；入口存在是为了满足包契约（扩展包版 `apply.py`，惯例在包根），
并让 `load_stack()` 的加载链对两种包完全同形。

数据包要用它：在 `game.json` 里声明 `"depends": ["ext_reward"]`，然后

    from ext_reward.tlog import BattleTLog, EVENT_KINDS, REPRO_KEYS

★ 可拔插红线（逐字继承自原地 `content/tlog_collect.py`）：`BattleTLog(tlog=None)` 时
**全部方法零行为** —— 不链观察者、不包 `human_act`、不写一个字段。
"""
from __future__ import annotations


def install_engine() -> None:
    """本包没有引擎级装配（纯形状库）—— 保留函数体为空且显式说明，不留含糊的空壳。"""
    return None
