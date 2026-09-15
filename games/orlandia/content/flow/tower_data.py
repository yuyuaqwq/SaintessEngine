# -*- coding: utf-8 -*-
"""包内修炼塔塔表读口（`content/flow/tower_data.py`）—— **域投影**，不再是逐字端口。

B9-L7（2026-09-13）之前：本文件是 `game/data/trial_tower.py` **整文件逐字**搬进包的副本
（B8.2 线1 的临时落法，注释里写明「待域声明后由导出器接管」）。

B9-L7 之后（本版）：塔表与三条常量都改成**读域**，包内不再有第二份副本
（BRIEF §6「不许半搬」：同一语义留两份 = 新双源）。

| 名字 | 真源 | 域（导出器产出） |
|---|---|---|
| `TRIAL_FLOORS` | `game/data/trial_tower.py:112`（生成式，30 条） | `content/data/trial_floors.json` ← `derive_trial_floors` |
| `TRIAL_DAILY_LIMIT` | `game/data/trial_tower.py:24`（=3） | `content/rules/game_config.json:trial_tower` |
| `TRIAL_MIN_LV` | `game/data/trial_tower.py:27`（=70） | 同上 |
| `TRIAL_MAX_FLOOR` | `game/data/trial_tower.py:30`（=30） | 同上 |

★ 真源里**没进包**的部分（不是数据，是生成这张表的代码）：`_floor_lv` / `_hp_mult` /
`_atk_mult` 三个函数与 `_EXP` / `_GOLD` / `_ROLES` / `_FLOOR_NAMES` / `_FLOOR_DESC` /
`_GUARD_NAMES` 六张私有中间表 —— 成品 `TRIAL_FLOORS` 已进域，重复导它们 = 同一语义两份。

消费方（一行未改，仍按同名读）
- `content/flow/tower_progress.py`：`_TD.TRIAL_FLOORS`（`_floor_def` 线性查找时按 1 基层号匹配）、
  `_TD.TRIAL_DAILY_LIMIT` / `_TD.TRIAL_MAX_FLOOR`（当日剩余层数 / 登顶判定），并把这三个名字
  re-export 给宿主命令薄壳。
- 宿主 `game/commands/tower.py`：`_TP.TRIAL_MIN_LV`（公告门槛）——
  传的是 `content/flow/tower_progress.py` 的 re-export（= 本模块的值）。

口径：本模块**只做名字绑定**，值一律来自 `content/config.py`（域文件，导出器单向产出）；
键型还原（`"1"` → `1`）与顺序还原（按 floor 排回源 list 序）在 `content/config.py:trial_floors()`
里做 —— 少了任何一步，塔的层序与「下一层」推导都会漂（渲染文案逐字变）。
"""
from __future__ import annotations

from .. import config as _CFG

# 塔表（list，下标 = 层号 - 1，与真源 `TRIAL_FLOORS` 逐条等价）
TRIAL_FLOORS: list = _CFG.trial_floors()

# 三条常量（真源行号见模块 docstring 的表）
TRIAL_DAILY_LIMIT: int = _CFG.TRIAL_DAILY_LIMIT
TRIAL_MIN_LV: int = _CFG.TRIAL_MIN_LV
TRIAL_MAX_FLOOR: int = _CFG.TRIAL_MAX_FLOOR

__all__ = ["TRIAL_FLOORS", "TRIAL_DAILY_LIMIT", "TRIAL_MIN_LV", "TRIAL_MAX_FLOOR"]
