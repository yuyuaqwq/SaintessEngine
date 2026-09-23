# -*- coding: utf-8 -*-
"""条件判定形状 —— 扩展包 `ext_achieve` 的门面。

本包收「条件类」的通用形状（2026-09-24 起从数据包抽入，一个形状一步）：

* `cond.registry` —— 条件注册表：名字 → 判定函数（未知名按默认键兜底 · 声明表整表装配）
* `cond.envs`     —— 环境位图：场地 id × 注入的词表 → `{环境名: bool}`，配 `EnvCtx` 判定上下文

数据包要用它：`game.json` 里声明 `"depends": ["ext_achieve"]`，然后

    from ext_achieve.cond import EnvCtx, Registry, bind_envs, envs_of

本包**零游戏专名**（词表与判定函数一律由调用方给）、**不 import 任何数据包**。
"""
from .cond import EnvCtx, Registry, bind_envs, envs_of
from . import cond

__all__ = [
    "cond",
    "Registry",
    "EnvCtx", "bind_envs", "envs_of",
]
