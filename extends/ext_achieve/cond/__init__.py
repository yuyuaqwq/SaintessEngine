# -*- coding: utf-8 -*-
"""条件判定与账本形状 —— 扩展包 `ext_achieve` 的门面。

本包收「条件类」的通用形状（2026-09-24 起从数据包抽入，一个形状一步）：

* `registry` —— 条件注册表：名字 → 判定函数（未知名按默认键兜底 · 声明表整表装配）
* `envs`     —— 环境位图：场地 id × 注入的词表 → `{环境名: bool}`，配 `EnvCtx` 判定上下文

数据包要用它：`game.json` 里声明 `"depends": ["ext_achieve"]`，然后

    from ext_achieve.cond import EnvCtx, Registry, bind_envs, envs_of

本包**零游戏专名**（内容词表一律调用方注入）、**不 import 任何数据包**。
"""
from .envs import EnvCtx, bind_envs, envs_of
from .registry import Registry
from . import envs, registry

__all__ = [
    "registry",
    "envs",
    "Registry",
    "EnvCtx", "bind_envs", "envs_of",
]
