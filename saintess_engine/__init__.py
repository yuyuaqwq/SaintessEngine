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
            command/     命令层骨架（声明注册表/路由/分页/守卫/提示）
            text/        文案模板表（输出侧文本：装载/渲染/缺失自检）
            events/      领域事件总线
            clock/       懒计时器
            log/         日志门面（命名 / 可拔插出口 sink / 结构化上下文）
            tlog/        结构化流水（Record / KindTable / sink / 读口 / 重放 / 事件桥）
            space/       空间形状（节点表 + 拓扑 → 邻接 / 深度 / 出入口 / 必经路径 / 审计）
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

# ---- 版本 / 兼容性 ----
from .version import __version__, VERSION_INFO  # noqa: F401
from . import version  # noqa: F401

# ---- 子模块（`from saintess_engine import <模块>` 形态消费）----
from . import config  # noqa: F401
from .battle import (  # noqa: F401
    actions, actors, ai, effect_triggers, effects, formulas,
    landing, schedule, serialize, state_effects, stats,
)
from . import (  # noqa: F401
    clock, command, container, events, expr, formation, gauge, kinds, log, session, space, store,
    text, tlog,
)
# 指令声明 / 文案表（声明驱动：可拔插，未装载 = 零行为）
from .command import CommandRegistry, CommandSpec  # noqa: F401
from .text import TextSpec, TextTable, safe_format  # noqa: F401
# 结构化流水（声明驱动：KindTable 未装载 = 不校验）
from .tlog import KindTable, Record, TLog  # noqa: F401
# 空间形状（节点表 + 拓扑 → 派生；第三方可注册自定义拓扑）
from .space import Space  # noqa: F401

__all__ = [
    # 版本
    "__version__", "VERSION_INFO", "version",
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
    "store", "command", "events", "clock", "log", "tlog", "space", "container", "session", "text",
    # 声明驱动（指令 / 文案 / 流水）
    "CommandRegistry", "CommandSpec", "TextTable", "TextSpec", "safe_format",
    "TLog", "Record", "KindTable",
    # 空间形状（节点表 + 拓扑 → 派生）
    "Space",
]
