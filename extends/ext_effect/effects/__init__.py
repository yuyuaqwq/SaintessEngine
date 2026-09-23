# -*- coding: utf-8 -*-
"""`ext_effect.effects` —— **场景交互效果层（POI）+ 药水效果层**。

**本层零包内依赖**：不 import 数据包（`content.*`）也不 import 其它扩展包。
它需要的一切都由调用方**注入**：

| 半边 | 注入面 | 真源（数据包侧） |
|---|---|---|
| POI（`poi_effects.py`） | `PoiContext(host=…, dom=…, text=…, static=…)`（**逐次**注入，ctx 随调用走） | 宿主的库 / 数据包域门面 / 文案表 |
| 药水（`potion_effects.py`） | `potion_effects.bind(text=…, static=…, items=…, rules=…, neg_keys=…)`（**装配期一次**，模块级句柄） | 文案表 · `items` 域 · `effect_rules` 域 · `purify_neg_keys` 域 |

为什么药水侧只能挂模块级：它的 handler 签名是 `(battle, player, value)`（没有 ctx），
73 个渲染点分散在 36 个 handler 里 —— 模块级句柄才能让那 73 个调用点**一字不改**
（包内同款先例 = 数据包的 `content/obs.py::bind(log=…)`）。

不注入就取用 = **当场报错**（fail-loud：文案句柄 `_T` 是未绑定代理；`DEFAULTS` 走 `_resolve()`
时校验），绝不静默给空串 / 空表。

装配点（唯一）：数据包 `content/apply.py::install_engine()` →
`content/effects/__init__.py::bind_effects()`。
"""
from __future__ import annotations

from .poi_effects import POI_EFFECTS, PoiContext, execute_poi, register
from .potion_effects import DEFAULTS as POTION_DEFAULTS, POTION_EFFECTS

__all__ = [
    "POI_EFFECTS", "PoiContext", "execute_poi", "register",
    "POTION_EFFECTS", "POTION_DEFAULTS",
]
