# -*- coding: utf-8 -*-
"""v181.P4 新战斗引擎包（battle2）——按 REFACTOR_v181P4_FULL_PLAN.md 实现。

旧 battle.py（11000+ 行，v100+ 补丁叠加）保留可跑；本包独立实现，
完成后切换 import 并删旧。

包结构：
- actors.py    Actor/Sides/ActCtx 模型 + 序列化
- battle.py    Battle 主类（行动入口 act/human_act/actor_auto）
- actions.py   行动结算链（_do_skill/_do_attack/_deal_hit/_damage_actor）
- effects.py   效果系统（EFFECT_HANDLERS 单表 + handler 注册）
- stats.py     面板计算（_actor_stats_of 替代 _player_stats/_enemy_stats）
- schedule.py  CTB 时间轴/事件队列
"""
