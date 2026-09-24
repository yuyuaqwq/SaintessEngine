# -*- coding: utf-8 -*-
"""规则触发形状 —— `ext_achieve.rule` 的门面。

* `engine.bind`       注入七个句柄（规则表 / 时段 / 计数读写 / 背包持有数 / 对白旗标 / 模板执行）
* `engine.match_cond` 一条规则的条件字典逐字段判定（字段名 = 形状契约）
* `engine.fire`       触发器入口：按表序取第一条命中的规则，交调用方执行

数据包要用它：`game.json` 里声明 `"depends": ["ext_achieve"]`，然后

    from ext_achieve.rule import bind, fire
    bind(rules=lambda: _rules(), is_time=…, counter_get=…, counter_set=…,
         count_item=…, talk_flag=…, fire_event=…)

本包**零游戏专名**（规则表、时段语义、存档读写、模板执行一律调用方给）、**不 import 任何数据包**。
"""
from .engine import bind, fire, match_cond
from . import engine

__all__ = [
    "engine",
    "bind", "fire", "match_cond",
]
