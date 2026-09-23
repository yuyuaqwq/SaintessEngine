# -*- coding: utf-8 -*-
"""`ext_combat` 的入口 —— 按包契约提供 `install_engine()`。

战斗域在**被 import 的那一刻**就完成了自己的注册（`battle/effects.py` 的动词注册表、
`effect_triggers` 的事件全集都是模块级副作用），所以这里没有额外动作：
真正需要「装配」的是**数值与规则**（公式骨架 / 行动耗时表 / 技能 schema），
那些属数据包（内容取值），由数据包在它自己的 `install_engine()` 里挂进
`saintess_engine.config` 的注入面。

保留这个函数（而不是省掉入口）是为了让包栈的加载链对两种包完全同形，
并且给将来「战斗包需要引擎级注册」留一个**明确**的落点，而不是靠猜 import 顺序。
"""
from __future__ import annotations


def install_engine() -> None:
    return None
