# -*- coding: utf-8 -*-
"""我的游戏（my_game）—— 内容装配入口（由框架编辑器脚手架生成）。

两件事，都幂等：
    install_engine()            全局：把本游戏的公式/面板/技能表/kind 词表/声明表挂进引擎
    apply_game_content(actor)   单个 actor：把资源渠道/机制/被动翻成 triggers

方向只有一个：**内容 → 引擎**。框架不 import 本包，也不认识本包的表。
数据源是 content/data/*.json 与 content/rules/*.json（编辑器直接改这些文件）。
"""
from __future__ import annotations

import json
import os

import saintess_engine.config as config   # 引擎公开注入面

_HERE = os.path.dirname(os.path.abspath(__file__))
_MOUNTED = False


def _load(name: str, rules: bool = False):
    sub = "rules" if rules else "data"
    p = os.path.join(_HERE, sub, f"{name}.json")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _lazy_mount():
    """引擎首次访问未装配 hook 时的自举（框架只认这一个回调）。"""
    install_engine()


def install_engine() -> None:
    """把本游戏配置挂进引擎（幂等）。表为空时挂空表（引擎按零默认值处理）。"""
    global _MOUNTED
    if _MOUNTED:
        return
    import saintess_engine.battle.formulas as formulas

    # 本游戏的机制动作：**import 即注册**（@register_action 在 import 期执行）。
    # 不 import 就等于动作不存在 —— 声明表里写了也跑不起来（静默无行为）。
    try:
        from .mech import actions as _actions          # noqa: F401
    except ImportError:
        pass                                          # 本包没写动作也不该失败

    config.register_hook_provider(_lazy_mount)
    config.mount(
        formulas=formulas,                    # 引擎自带通用公式模块
        effect_rules=_load("effect_rules", True),   # 状态/资源声明表
        effect_actions=_load("effect_actions", True),
        passive_proc=_load("passive_proc", True),
    )
    _MOUNTED = True


def apply_game_content(actor: dict) -> dict:
    """把本游戏内容挂到 actor 上（幂等）。"""
    if not isinstance(actor, dict):
        return actor
    install_engine()
    return actor
