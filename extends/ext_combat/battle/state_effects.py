# -*- coding: utf-8 -*-
"""效果规则查询（薄封装）——数据来自本包 `battle/game_config.py` 挂载的游戏规则。

V 系列统一：规则表 = EFFECT_RULES（cap/panel/stat_scale/period/consume/cleanse 全声明）。
引擎不内置规则表；游戏层经 `game_config` 的 `load_game_rules()` 注入。
这里只保留查询接口（cap/折算），表内容在游戏层。
"""
from __future__ import annotations

from .game_config import get_effect_rules


def state_def(key: str) -> dict:
    """查效果规则（无规则 = 空 dict = 纯数值）。"""
    return get_effect_rules().get(key) or {}


def stat_scale_of(key: str, value: int, stat: str) -> float:
    """折算：effect key 每 value 点对 stat 的加成系数（1 + n×系数）。"""
    cfg = state_def(key)
    scale = (cfg.get("stat_scale") or {}).get(stat)
    if not scale:
        return 1.0
    return 1.0 + int(value or 0) * float(scale)


def all_state_effects() -> dict:
    """当前挂载的全部效果规则表（引擎遍历/审计用）。"""
    return get_effect_rules()
