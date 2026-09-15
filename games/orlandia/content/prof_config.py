# -*- coding: utf-8 -*-
"""B15b：副业配置**逻辑**进包（`content/prof_config.py`）。

为什么有这个文件
----------------
宿主 `game/data/*.py`（87 个）已于 2026-09-14 删除 ⇒ 原先住在 `game/data/prof_config.py`
里的两个**函数**跟着消失，而包内仍有 4 处 `C.gather_map_min_lv(...)` / `C.price_band(...)` 读点
（宿主聚合层 `C.<名>` 已无对象 → 运行期 `AttributeError`；红测试
`tests/test_v87_14_spatial_links.py`）。本文件把这两个函数**逐字端口进包**，消费点改为直取本模块。

真源（**只读**；原文备份 `overnight/../_w11d_backup/data_py/prof_config.py`）
--------------------------------------------------------------------------
| 本文件 | 真源 | 逐字范围 |
|---|---|---|
| `price_band` | `game/data/prof_config.py:86`（v125.2 B3） | 函数体 + docstring 一字未改 |
| `gather_map_min_lv` | `game/data/prof_config.py:108`（v173） | 同上 |

依赖的常量**不重抄**，走包内**常量域唯一读口**（禁第二份数据）
------------------------------------------------------------
| 常量 | 真源行 | 包内读口 |
|---|---:|---|
| `PRICE_BAND` | `prof_config.py:80` | `content/config.py:const("prof_config", …)` ← `content/rules/game_config.json` · `prof_config` 组 |
| `GATHER_MAP_MIN_LV`（分档表，别的消费端用） | `prof_config.py:102` | 同域同组（`const_group("prof_config")`），本模块不取 |

⚠ 两条刻意的选择：
1. **用 `content/config.py` 而不是 `content/catalog_legacy.py`**：后者是宿主聚合层 `C` 的
   「丢名再导出面」，而 `catalog_legacy` → `catalog_rules` → 本模块 是一条 module 级 import 链，
   反过来 `本模块 → catalog_legacy` 会成环（实测 `ImportError: partially initialized module
   'content.prof_config'`）。`content/config.py` 只依赖 json/os，是无环的**真读口**，且同域同键。
2. **`gather_map_min_lv()` 的函数体本来就不读那张分档表**（真源是 `1 + (lv-1)//10` 的等价值），
   故此处也不读 —— 照抄原文优先于「看起来更整齐」。

消费点（B15b 由 `C.<名>` 切为**直取本模块**）
--------------------------------------------
`content/economy_cmds.py`（野地采集等级门）· `content/world_cmds.py`（野地采集点 🔒 显示）·
`content/profession.py` ×2（采集/挖掘兜底价格带）

名字面：本模块的函数由 `content/catalog_rules.py` 再导出 ⇒ 宿主 `game/content.py` 的
`catalog_*` 聚合循环自动把 `C.gather_map_min_lv` / `C.price_band` 收回（宿主侧零改动）。
"""
from __future__ import annotations

from .config import const  # 常量域唯一读口（content/config.py —— 无环，缺域会 raise 不静默）

PRICE_BAND: dict = const("prof_config", "PRICE_BAND")  # 真源 game/data/prof_config.py:80


def price_band(map_lv: int) -> tuple:
    """地图等级 → 价格区间 (低, 高)：3+lv*4 ≤ price ≤ 20+lv*12（v97.2 兜底公式）"""
    _pb = PRICE_BAND
    return _pb["lo_base"] + _pb["lo_per_lv"] * map_lv, _pb["hi_base"] + _pb["hi_per_lv"] * map_lv


def gather_map_min_lv(map_lv: int) -> int:
    """地图等级 → 所需采集副业等级（每 10 级图 ≈ 1 级副业）。"""
    return 1 + int(map_lv - 1) // 10 if map_lv > 0 else 1
