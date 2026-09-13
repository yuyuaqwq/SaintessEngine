# -*- coding: utf-8 -*-
"""包内流程层（`content/flow/`）—— 「剧本 · 进程 · 准入」三件事的内容侧实现。

三层归属（判据见 `docs/`：通用→引擎 / 内容→包 / 接人→宿主）
------------------------------------------------------------------
| 模块 | 内容 | 来源（真源，逐字搬） | 行数 |
|---|---|---|---|
| `boss_script.py` | Boss 剧本导演：阶段/开场/低血/召唤/连锁/打断/爪牙死亡联动 | `game/commands/boss_script.py` | 737 |
| `instance_run.py` | 副本运行态：名单 / 分层进度 / 房间剩余池 / 资源池 → 引擎 `Roster`/`Progress` | `game/core/instance_run.py` | 308 |
| `instance_gate.py` | 副本准入：钥匙三路匹配 / 通关豁免 / 四条准入链（开本·徒步·加入·恢复） | `game/core/instance_gate.py` | 366 |

引擎侧形状（本包只用、不改）：`saintess_engine.run.Admission` / `Rule` / `Progress` / `Roster`，
`Battle.script_hook` / `Battle.on_event` / `Battle.add_actor`，`saintess_engine.text.TextTable`。

替身接口（宿主耦合 → 调用方传参；逐条对拍见 `overnight/d3-flow-port.md`）
------------------------------------------------------------------
| 宿主耦合（真源） | 包内替身 |
|---|---|
| `game.content.MONSTER_MODS` / `INSTANCES`（宿主内容聚合层） | `data=` 参数；缺省 = 包内 `content/data/monster_roster.json[*].mods` / `instances.json` |
| `game.core.drops.build_monster`（怪物构造，**未进包**） | `build_monster=` 参数；不传 → 真源自带兜底（Boss×0.2） |
| `game.data.boss_phases.merge_phase_config`（阶段模板，**未进包**） | `phase_templates=` 参数；不传 → 真源同分支（无模板） |
| `db.party_members`（组队） | `instance_run.current_members(st, party)` 的 `party` |
| `db.get_inventory` / `db.get_achievements`（存档） | `instance_gate.find_instance_key_item(inventory, …)` / `instance_cleared(achievements, …)` |
| `game.core.texts`（文案表 + 宿主 ERROR 日志） | 包内 `content/data/texts.json` + 引擎 `TextTable`；`instance_gate.set_text_table()` 可换表 |
| 存档 `st["boss_script"]` / `st`（持久化、序列化） | 调用方给的普通 dict（宿主负责落库） |
| `battle.script_hook` / `battle.on_event` 挂载 | 宿主把 `make_script_hook(st)` / `make_script_event(st)` 挂到引擎 `Battle` |

缺口（不在本批范围，逐条见 `overnight/d3-flow-port.md` §4）：Boss 剧本文案无文案槽位（硬编码逐字保留）·
`build_monster` / `boss_phases` 模板表未进包 · 副本指令层的其余 2 万行未搬。

用法::

    from content.flow import instance_gate, instance_run, boss_script
    hook = boss_script.make_script_hook(st)          # st = 调用方的副本存档 dict
    battle.script_hook = hook
"""
from __future__ import annotations

from . import boss_script, instance_gate, instance_run

__all__ = ["boss_script", "instance_run", "instance_gate"]
