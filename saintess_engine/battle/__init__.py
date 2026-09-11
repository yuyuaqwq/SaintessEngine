# -*- coding: utf-8 -*-
"""battle —— 战斗域（CTB 回合制结算）。

并列子模块（依赖自下而上，模块级无环）：

  battle      战斗编排（构造 / act / human_act / actor_auto / 结果判定）
  actions     行动结算链（技能施放判据、命中、伤害注入）
  landing     伤害/治疗落地（闪避 / 格挡 / 护盾 / 免伤 / 元素）
  effects     效果叠层 + 动作注册表（EFFECT_HANDLERS）
  schedule    CTB 时间轴与推进器
  ai          通用怪决策器（条件表 / 权重 utility）
  stats       面板合成（公式经 config 注入）
  formulas    通用数值公式骨架
  actors      Actor 容器 + Sides 集合 + ActCtx
  effect_triggers  战斗内事件总线（fire/register）
  state_effects    规则查表门面（state_def）
  serialize   战斗存档（to_state / from_state）

对外只需 `from saintess_engine import X`（顶层门面）；
需要深路径时用 `from saintess_engine.battle.<模块> import Y`。
"""
from .actors import ActCtx, actor_alive, actor_ext, actor_dead, hostile_sides, make_actor
from .actions import heal_amount, skill_pay_of
from .battle import Battle, now_of
from .effect_triggers import fire
from .effects import act_apply, act_shield, apply_effects, cap_of, norm_stack, register_action
from .landing import deal_damage, heal_actor
from .schedule import action_time, initial_ct
from .serialize import from_state, to_state
from .state_effects import all_state_effects, state_def
from .stats import actor_stats

__all__ = [
    "Battle", "ActCtx", "make_actor", "actor_ext", "actor_alive", "actor_dead",
    "deal_damage", "heal_actor",
    "act_apply", "act_shield", "apply_effects", "register_action", "cap_of", "norm_stack",
    "actor_stats", "state_def", "all_state_effects",
    "fire", "action_time", "initial_ct", "hostile_sides",
    "heal_amount", "skill_pay_of", "from_state", "to_state", "now_of",
]
