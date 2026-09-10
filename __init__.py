# -*- coding: utf-8 -*-
"""v181.P4 新战斗引擎包（battle2）—— 公开 API 门面（S2 固化）。

旧 battle.py（11000+ 行，v100+ 补丁叠加）保留可跑；本包独立实现，完成后切换 import 并删旧。

S2（docs/ENGINE_CONTENT_SPLIT_PLAN.md §5 / §7-S2）：把内容层实际消费的符号
**全量 re-export**，内容层不再依赖引擎内部结构（submodule 化前的必要固化）：
- 25（实为 26）个被消费符号：deal_damage / state_def / heal_actor / Battle /
  actor_alive / act_apply / cap_of / actor_stats / apply_effects / now_of /
  stats / register_action / config / fire / all_state_effects / action_time /
  initial_ct / hostile_sides / act_shield / norm_stack / effects / heal_amount /
  skill_pay_of / make_actor / get_effect_rules / get_effect_actions
- 5 个下划线私有符号已提升为公开（cap_of / now_of / norm_stack / heal_amount /
  skill_pay_of），**旧下划线名保留为别名**（内容层/测试仍在用，不得删）
- 存档兼容（§8-R11）：`Battle.from_state` / `Battle.to_state`（类方法）与模块级
  `serialize.from_state` / `to_state` 都在本 API 面内

引擎零内容 import（门禁 tests/test_engine_no_content.py）。

包结构：
- actors.py    Actor 模型/工厂 + Sides 容器 + ActCtx + actor 序列化
- battle.py    Battle 主类（构造、act/human_act/actor_auto、结果判定）
- actions.py   行动结算链（_do_skill/_do_attack/_deal_hit/_damage_actor）
- effects.py   效果系统（EFFECT_HANDLERS 单表 + handler 注册）——N3
- stats.py     面板计算（薄封装，公式走 config 注入面，不重写公式）
- schedule.py  CTB 时间轴/事件队列——N4
- serialize.py to_state/from_state（sides-only）——N5
- config.py    配置/hook 挂载点（引擎零游戏知识；S1 断链后唯一注入面）
"""
from .actors import ActCtx, actor_alive, actor_ext, hostile_sides, make_actor
from .actions import heal_amount, skill_pay_of
from .battle import Battle, now_of
from .config import get_effect_actions, get_effect_rules
from .effect_triggers import fire
from .effects import act_apply, act_shield, apply_effects, cap_of, norm_stack, register_action
from .landing import deal_damage, heal_actor
from .schedule import action_time, initial_ct
from .serialize import from_state, to_state
from .state_effects import all_state_effects, state_def
from .stats import actor_stats

# 模块级符号（内容层以 `from game.battle2 import stats` 形态消费）
from . import config, effects, stats  # noqa: F401

__all__ = [
    # Actor / 战斗主体
    "Battle", "ActCtx", "make_actor", "actor_ext", "actor_alive",
    # 伤害落地 / 治疗
    "deal_damage", "heal_actor",
    # 效果系统
    "act_apply", "act_shield", "apply_effects", "register_action",
    "cap_of", "norm_stack",
    # 面板
    "actor_stats", "stats",
    # 规则 / 配置
    "state_def", "all_state_effects", "get_effect_actions", "get_effect_rules",
    "config",
    # 事件 / 时间轴
    "fire", "action_time", "initial_ct",
    # 阵营
    "hostile_sides",
    # 行动结算工具
    "heal_amount", "skill_pay_of",
    # 序列化（存档兼容：§8-R11）
    "from_state", "to_state",
]
