# -*- coding: utf-8 -*-
"""《铆炉回声》最小示例 —— 第三方内容包的公开入口。

外部只需要认识两个名字：

    apply_game_content(actor)   把本游戏内容挂到一个 actor 上（幂等）
    install_engine()            把本游戏的公式/面板/技能表/kind 词表/声明表挂进引擎

本模块在 import 时立刻调一次 install_engine()（与参考实现 game/bootstrap.py
的 install() 同款时机）：这样「import content」就等于「接管引擎配置」，
不给 game 包登记的那套惰性装配器任何抢跑机会。
"""
from .apply import apply_game_content, install_engine

install_engine()  # import 即接管（幂等）

__all__ = ["apply_game_content", "install_engine"]
