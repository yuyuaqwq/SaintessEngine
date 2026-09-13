# -*- coding: utf-8 -*-
"""《奥兰迪亚·余烬纪年》战斗内动词包（P4 机制移植）。

本目录 = 引擎 `fire()` / `apply_effects()` 按名字直调的**动作实现**（动词）。
引擎只认「注册名 + 签名」，不认内容：动作在**模块顶层**用

    @register_action("<动词名>")
    def <fn>(battle, caster, target, params, logs): ...

注册 —— **import 即注册**（由 `content/apply.py` 顶部 `from .mech import …` 触发；
包加载器 `saintess_engine.package.load()` 以「包」的方式导入 `content`，故这里的相对导入可用）。

族清单（D2 全量 96 个动作 + D1 切片 3 个 = 99 个装饰器 / 96 个唯一动词）

| 文件 | 机制族 | 动作数 | 真源（游戏仓 `game/services/`） |
|---|---|---:|---|
| `actions.py` | D1 切片样板 | 3 | `class_mech_proc.py`（与 class_mech 同名同义，后注册者胜） |
| `class_mech.py` | 职业机制兑现 | 39 | `class_mech_proc.py` |
| `we_procs.py` | 武器/词条特效 | 27 | `battle_we_procs.py` |
| `team_procs.py` | 团队/面幅 | 20 | `battle_team_procs.py` |
| `bar_procs.py` | 敌身条 | 4 | `battle_bar_procs.py` |
| `element_procs.py` | 元素反应/克制/流转 | 4 | `battle_element_procs.py` |
| `cond_procs.py` | 技能条件乘区 | 1 | `battle_cond_procs.py` |
| `worldboss.py` | 世界 Boss GM 增伤 | 1 | `battle_worldboss_procs.py` |

参数表（切片期随代码走；第二波建域）：
* `params.py` —— 引擎 hook 供体 + 声明表载体（`EFFECT_RULES` / `EFFECT_ACTIONS` / kinds / 公式骨架）
  ＋**挂敌身条两张表 `BAR_INJECT_FIELDS` / `BAR_STATE_PREFIX` 的唯一真源**（2026-09-13 双源收敛）
* `class_data.py` —— `MECH_CASH` / `MECH_CFG`（`BAR_*` 已改为从 `params` 再导出）
* `we_data.py` —— `WEAPON_EFFECT_DATA` / `ACT_TICK`
* `element_data.py` —— `REACTION_TABLE` / `ELEMENT_REACTIONS` / `ELEMENT_MARKS_MAX`（`BAR_INJECT_FIELDS` 同为再导出）

验收工具（workspace，不入仓）：`overnight/p4_d2_audit.py` —— AST 集合同源断言（包内动作表 == 游戏仓动作表）
+ 注册断言 + 依赖缺口扫描；`editor.actions.declared_missing(pkg)` 是进度条（当前 缺 0）。
"""
