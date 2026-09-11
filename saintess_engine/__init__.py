# -*- coding: utf-8 -*-
"""saintess_engine —— 通用游戏框架包（多模块并列，依赖自下而上）。

模块布局（全部平级）：

  基础      config      引擎注入面（内容侧装配 hook 的唯一入口）
  战斗域    battle/      CTB 调度 / 行动结算 / 效果叠层 / 落地 / 存档 / AI / 面板公式
  通用原语  expr/        表达式求值器（数值公式自定义）
            gauge/       计量条（累积/衰减/阈值/免疫窗口）
            formation/   站位与目标选择几何
            kinds/       技能 / 伤害类别域
  运行时    store/       SQLite 骨架（连接/锁/事务/迁移/Repository）
            command/     命令层骨架（注册/路由/分页/守卫/提示）
            events/      领域事件总线
            clock/       懒计时器
            container/   容量受限格子容器
            session/     宿主会话适配

本文件是**包门面**：外部只需 `from saintess_engine import X`。
包内模块一律相对导入，不反向依赖门面（纯度门禁 tests/test_engine_purity.py）。
"""
# ---- 战斗域公开符号（门面转出，外部零改动）----
from .battle.actors import ActCtx, actor_alive, actor_ext, hostile_sides, make_actor
from .battle.actions import heal_amount, skill_pay_of
from .battle.battle import Battle, now_of
from .config import get_effect_actions, get_effect_rules
from .battle.effect_triggers import fire
from .battle.effects import act_apply, act_shield, apply_effects, cap_of, norm_stack, register_action
from .battle.landing import deal_damage, heal_actor
from .battle.schedule import action_time, initial_ct
from .battle.serialize import from_state, to_state
from .battle.state_effects import all_state_effects, state_def
from .battle.stats import actor_stats

# ---- 子模块（`from saintess_engine import <模块>` 形态消费）----
from . import config  # noqa: F401
from .battle import (  # noqa: F401
    actions, actors, ai, effect_triggers, effects, formulas,
    landing, schedule, serialize, state_effects, stats,
)
from . import (  # noqa: F401
    clock, command, container, events, expr, formation, gauge, kinds, session, store,
)

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
    # 序列化（存档兼容：拆仓方案 §8-R11）
    "from_state", "to_state",
    # 子模块
    "battle", "actions", "actors", "ai", "effect_triggers", "effects", "formulas",
    "landing", "schedule", "serialize", "state_effects",
    "expr", "gauge", "formation", "kinds",
    "store", "command", "events", "clock", "container", "session",
]
