# -*- coding: utf-8 -*-
"""B15b：重锻专属配方**逻辑**进包（`content/refine_exclusive.py`）。

真源（**只读**；原文备份 `overnight/../_w11d_backup/data_py/refine_exclusive.py`）
------------------------------------------------------------------------------
| 本文件 | 真源 | 逐字范围 |
|---|---|---|
| `merge_into` | `game/data/refine_exclusive.py:160`（v172 路 B） | 函数体 + docstring 一字未改 |

依赖的常量**不重抄**：`REFINE_EXCLUSIVE_RECIPES`（真源 `refine_exclusive.py:18` · 12 条）
走包内域读口 —— `content/rules/game_config.json` 的**新组** `refine_exclusive`
（组名 = 真源模块名，与 `refine` 组同款口径）→ `content/catalog_items.py` 再导出。
该组由 `overnight/b15b_port_domain.py` 从备份真源 import 后 dump（非手抄），
dump 前做过「既有域 load→dump 往返逐字节同」自证 ⇒ 只追加、不动旧数据。

消费点
------
实测**全树零调用**（包内 + 宿主）：`content/economy_cmds.py` 三处派生自并查
`REFINE_RECIPES` / `REFINE_EXCLUSIVE_RECIPES` 两张表，没走本函数。端口它的意义 =
① 「宿主函数读点清零」（`catalog_legacy.GAPS` 的『宿主函数（包内无实现）』那格可撤）；
② 名字面恢复 —— 宿主老聚合层有 `C.merge_into`，开关后没了，本文件 + `catalog_rules`
再导出把它补回（宿主侧零改动）。
"""
from __future__ import annotations

from .catalog_items import REFINE_EXCLUSIVE_RECIPES  # 域读口（game_config · refine_exclusive 组）


def merge_into(refine_recipes: dict) -> dict:
    """把 REFINE_EXCLUSIVE_RECIPES 并入既有重锻配方表（REFINE_RECIPES），返回新表。

    供命令层查找池合并用（不改动原表）：若路 A 已在 economy.py 直接并查两张表，
    则无需调用本函数。target 为名册 rid（无锻造配方）——命令层须以
    generate_roster_equip(rid) 生成，而不是 craft_recipe_make(配方 key)。
    """
    merged = dict(refine_recipes or {})
    for _src, _cfg in REFINE_EXCLUSIVE_RECIPES.items():
        merged.setdefault(_src, _cfg)
    return merged
