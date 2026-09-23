# -*- coding: utf-8 -*-
"""`ext_combat` —— 回合制战斗（CTB）扩展包。

**包门面**：数据包/宿主只需 `from ext_combat import Battle, make_actor, …`（与它当年
在引擎里时的 `from saintess_engine import …` 同形）。包内模块一律相对导入。

内容：CTB 调度 · 行动结算 · 效果叠层 · 落地 · 存档 · 通用怪 AI · 面板公式 ·
计量条（gauge）· 站位几何（formation）· 面板栈（panel）。

边界
----
* **零游戏知识**：职业 / 技能 / 怪物 / 数值全是数据包的取值 —— 本包只提供「怎么算」。
* 引擎通用件（config / text / expr / formula / records / store …）由 `saintess_engine` 提供，
  本包只消费（绝对导入，不改引擎）。
* 装法：数据包 `game.json` 里 `"depends": ["ext_combat"]`；宿主想要的战斗类由
  `provides.battle` 声明给出（见 `game.json`）。
"""
from .battle.actors import ActCtx, actor_alive, actor_ext, hostile_sides, make_actor
from .battle.actions import heal_amount, skill_pay_of
from .battle.battle import Battle, now_of
from .battle.effect_triggers import fire
from .battle.effects import act_apply, act_shield, apply_effects, cap_of, norm_stack, register_action
from .battle.landing import deal_damage, heal_actor
from .battle.schedule import action_time, initial_ct, recover_time, settle_landing
from .battle.serialize import from_state, to_state
from .battle.state_effects import all_state_effects, state_def
from .battle.stats import actor_stats

# 子模块形态（`from ext_combat import battle` / `ext_combat.battle.effects`）
from . import battle, formation, gauge, panel  # noqa: F401
from .battle import (  # noqa: F401
    actions, actors, ai, effect_triggers, effects, formulas,
    landing, schedule, serialize, state_effects, stats,
)

__all__ = [
    # Actor / 战斗主体
    "Battle", "ActCtx", "make_actor", "actor_ext", "actor_alive",
    # 伤害落地 / 治疗
    "deal_damage", "heal_actor",
    # 效果系统
    "act_apply", "act_shield", "apply_effects", "register_action", "cap_of", "norm_stack",
    # 面板
    "actor_stats",
    # 规则
    "state_def", "all_state_effects",
    # 事件 / 时间轴
    "fire", "action_time", "initial_ct", "recover_time", "settle_landing", "now_of",
    # 阵营
    "hostile_sides",
    # 行动结算工具
    "heal_amount", "skill_pay_of",
    # 序列化（存档兼容）
    "from_state", "to_state",
    # 子模块
    "battle", "actions", "actors", "ai", "effect_triggers", "effects", "formulas",
    "landing", "schedule", "serialize", "state_effects", "stats",
    "gauge", "formation", "panel",
]
