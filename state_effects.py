# -*- coding: utf-8 -*-
"""battle2 状态规则查询（薄封装）——数据来自 config 挂载的游戏配置。

引擎不内置规则表；游戏层通过 config.load_game_rules() 注入。
这里只保留查询接口（cap/stat_scale 折算），表内容在游戏层。
"""
from __future__ import annotations

from . import config


def state_def(key: str) -> dict:
    """查状态定义（无规则 = 空 dict = 纯数值）。"""
    return config.state_def(key)


def stat_scale_of(key: str, value: int, stat: str) -> float:
    """折算：state key 每 value 点对 stat 的加成系数（1 + n×系数）。"""
    cfg = config.get_state_effects().get(key) or {}
    scale = (cfg.get("stat_scale") or {}).get(stat)
    if not scale:
        return 1.0
    return 1.0 + int(value or 0) * float(scale)


def all_state_effects() -> dict:
    """当前挂载的全部 state 规则表（引擎遍历/审计用）。"""
    return config.get_state_effects()
