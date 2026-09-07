# -*- coding: utf-8 -*-
"""v181.P4 新战斗引擎包（battle2）——按 REFACTOR_v181P4_FULL_PLAN.md 实现。

旧 battle.py（11000+ 行，v100+ 补丁叠加）保留可跑；本包独立实现，
完成后切换 import 并删旧。

包结构：
- actors.py    Actor 模型/工厂 + Sides 容器 + ActCtx + actor 序列化
- battle.py    Battle 主类（构造、act/human_act/actor_auto、结果判定）
- actions.py   行动结算链（_do_skill/_do_attack/_deal_hit/_damage_actor）
- effects.py   效果系统（EFFECT_HANDLERS 单表 + handler 注册）——N3
- stats.py     面板计算（薄封装 engine.py 数值函数，不重写公式）
- schedule.py  CTB 时间轴/事件队列——N4
- serialize.py to_state/from_state（sides-only）——N5
- data_bridge.py 读旧数据层适配——N1 起（技能表）
"""
from .actors import ActCtx, make_actor
from .battle import Battle

__all__ = ["Battle", "ActCtx", "make_actor"]
