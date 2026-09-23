# -*- coding: utf-8 -*-
"""`ext_effect.effects` —— **场景交互效果层**（POI）。

**本层零包内依赖**：不 import 数据包（`content.*`）也不 import 其它扩展包。
它只要求调用方在 `PoiContext` 上给三组注入句柄：

| 注入 | 是什么 | 真源（数据包侧） |
|---|---|---|
| `ctx.host` | 写库五动词对象（`update_player` / `add_item` / `set_event_state` / `get_event_state` / `set_talk_flag`） | 宿主的库 |
| `ctx.dom` | 内容域访问（`MATERIALS` · `CAMPFIRE_FOOD_POOL` · `HERB_POOL` · `pools(name)` · `resolve` · `display` · `roll_blueprint` · `generate_equip` · `living_members` · `set_alive`） | 数据包的域 / 门面 |
| `ctx.text` / `ctx.static` | 文案渲染（带槽位 / 不带槽位） | 数据包的文案表 |

不传 = `AttributeError`（fail-loud）：这三组是这层仅有的「读」出口，缺了必须当场报出来。

**药水效果半边**（`potion_effects.py`）仍在数据包内 —— 它的 handler 签名没有 ctx
（`(battle, player, value)`），要先给它做一个**模块级注入口**才能搬（登记为 B7b）。
"""
from __future__ import annotations

from .poi_effects import POI_EFFECTS, PoiContext, execute_poi, register

__all__ = [
    "POI_EFFECTS", "PoiContext", "execute_poi", "register",
]
