# -*- coding: utf-8 -*-
"""包内 **效果层**（`content/effects/`）—— POI 交互效果 + 药水效果（P4 进包批 D3）。

两层都是「真源逐字搬入 + 宿主耦合改调用方接口」（做法与 `content/bridge.py` 同款；
逐条改动白名单 = `overnight/_d3_effects_whitelist.json`，验收 = `overnight/d3_effects_verify.py`）：

| 模块 | 真源（游戏仓，只读） | 真源行数 | 注册表 | 入口 |
|---|---|---|---|---|
| `poi_effects.py` | `game/core/poi_effects.py` | 469 | `POI_EFFECTS`（9 世界 + 7 副本 = 16 键） | `execute_poi(effect_name, ctx)`；`ctx = PoiContext(...)` |
| `potion_effects.py` | `game/core/potion_effects.py` | 719 | `POTION_EFFECTS`（36 键） | `POTION_EFFECTS.get(effect)(battle, player, value)`（未注册 → `None`，调用方跳过） |

调用方要给的三个接口（替换清单逐条见各模块文件头；验收脚本 C 段用假回调对拍参数）
------------------------------------------------------------------------------
1. `PoiContext(..., host=…)` —— **宿主写库替身**（真源 = 宿主 `game.db`）：
   `update_player(gid, qid, **fields)` / `add_item(gid, qid, iid, item, count=1)` /
   `set_event_state(k, v)` / `get_event_state(k)` / `set_talk_flag(gid, qid, flag, action)`。
2. `PoiContext(..., dom=…)` —— **内容域访问替身**（真源 = 宿主 `game.content` 薄聚合层 C
   + `game.data.pois` 文案池 + `game.core.instance_run` 名单视图）：
   `MATERIALS` / `CAMPFIRE_FOOD_POOL` / `HERB_POOL` / `pools(name)` / `resolve` /
   `display` / `roll_blueprint(lv)` / `generate_equip(slot, lv, quality)` /
   `living_members(st)` / `set_alive(st, key, value)`。
3. 药水侧 `battle=…` —— **战斗替身接口**（真源 = 旧引擎 `Battle` 实例）。逐 handler 的
   回调清单见 `potion_effects.py` 文件头 ③；`player` dict 与 `value`（`effect_data`）
   仍由调用方给，handler 原地写回 `player`。

方向：**内容 → 引擎**。本层零 import 宿主仓、零 import 引擎；引擎侧零游戏知识。
"""
from __future__ import annotations

from .poi_effects import POI_EFFECTS, PoiContext, execute_poi, register
from .potion_effects import DEFAULTS as POTION_DEFAULTS, POTION_EFFECTS

__all__ = [
    "POI_EFFECTS", "PoiContext", "execute_poi", "register",
    "POTION_EFFECTS", "POTION_DEFAULTS",
]
