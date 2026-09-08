# -*- coding: utf-8 -*-
"""battle2 引擎——配置挂载点（引擎零游戏知识）。

引擎不内置任何游戏名词/数值规则。游戏层启动时把配置表挂进来：
    from game.battle2 import config
    config.state_effects = {...}   # 或 config.load_game_rules(module)

引擎内部所有"查表"都走 config 提供的接口，自身不认识表内容。
换一套配置 = 换挂载的表 = 新游戏（引擎代码零改动）。
"""
from __future__ import annotations

# 挂载的游戏配置（引擎只调接口，不认识内容）
# 结构见各字段 docstring；由游戏层 set_config / 直接赋值 注入
_LOADED = {
    "state_effects": {},   # state key → 规则（cap/stat_scale/dot/on/threshold）
    "effect_actions": {},  # 游戏名词效果 → 引擎动词动作序列
    "cleanse_tags": [],    # 净化清的控制键
}


def set_config(kind: str, table) -> None:
    """游戏层挂载配置表。kind: state_effects/effect_actions/cleanse_tags。"""
    if kind in _LOADED:
        _LOADED[kind] = table if table is not None else ([] if kind in ("cleanse_tags",) else {})


def load_game_rules(module) -> None:
    """从游戏规则模块加载约定字段。"""
    set_config("state_effects", getattr(module, "STATE_EFFECTS", {}))
    set_config("effect_actions", getattr(module, "EFFECT_ACTIONS", {}))
    set_config("cleanse_tags", getattr(module, "CLEANSE_TAGS", []))


def load_game_defaults() -> None:
    """加载本游戏默认规则（游戏层/测试启动时调用；引擎自身不调用）。

    引用 game.data.battle2_rules —— 这是游戏侧装配，不是引擎内置。
    """
    from game.data import battle2_rules
    load_game_rules(battle2_rules)


def get_state_effects() -> dict:
    """当前挂载的 state 规则表（默认空 = 引擎无内置规则）。"""
    return _LOADED["state_effects"]


def get_effect_actions() -> dict:
    """当前挂载的名词→动词动作表（默认空）。"""
    return _LOADED["effect_actions"]


def get_cleanse_tags() -> list:
    """净化应清的控制键（游戏配置声明；无 = 不清理 buff 容器控制键）。"""
    tags = _LOADED.get("cleanse_tags")
    return tags if isinstance(tags, list) else []


def state_def(key: str) -> dict:
    """查 state key 规则（无挂载/无条目 = 空 dict = 纯数值无规则）。"""
    return get_state_effects().get(key) or {}
