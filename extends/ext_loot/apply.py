# -*- coding: utf-8 -*-
"""`ext_loot` 的入口 —— 按包契约提供 `install_engine()`。

随机产出是**纯形状库**（`pick` / `pool` / `tier` / `mount` / `pity`）：
它只认 `key` / `w` / `n` / `ref` / `tier` / `count` 这些**结构字段**，
不认「掉落」「品质」「词条」这些取值 —— 池数据、档位取值、引用前缀、
随机源一律由数据包给。所以这里没有「安装动作」：装不装这个包，
引擎其它部分行为一致。

本包唯一的模块级状态在**包内部**：`pool.STRATEGIES`（四个内置策略
`weighted` / `fixed` / `table` / `table_choice`，加内容侧用
`register_strategy()` 注册的自定义策略）。它不挂进 `saintess_engine.config`
的任何 hook 面、不改全局 —— 因此安装期无事可做，也不该做事。

保留这个函数（而不是省掉入口）是为了满足包契约：包根 `apply.py` 让
`load_stack()` 的加载链对「形状包」与「能力包」完全同形，并给将来真出现
「需要引擎级注册」的需求留一个明确的落点，而不是靠猜 import 顺序。

数据包要用它：在 `game.json` 里声明 `"depends": ["ext_loot"]`，然后
`from ext_loot.loot import LootTable, TierTable, draw_slots` 直接取用。

★ 本包**不**声明 `provides`：引擎没有任何「随机产出」能力键可查。
宿主运行时取「掉什么」是从**数据包**入口同级的可选半边 `content/loot.py`
（`optional_submodule("loot")`）取的，不是从本包按能力键取件 ——
本包只提供形状，不持有任何游戏的池数据。
"""
from __future__ import annotations


def install_engine() -> None:
    """本包没有引擎级装配（纯形状库 + 包内策略注册表）—— 显式留空并说明理由。"""
    return None
