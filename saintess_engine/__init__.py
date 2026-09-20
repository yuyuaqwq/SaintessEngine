# -*- coding: utf-8 -*-
"""saintess_engine —— 通用游戏框架包（多模块并列，依赖自下而上）。

模块布局（全部平级）：

  基础      config      引擎注入面（内容侧装配 hook 的唯一入口）
            domains     引擎默认域集 + 「包声明 ∪ 引擎默认集」合并规则（域元数据合并唯一源：
                        编辑器 `editor/packages.py` 与装载口 `records` 委托同一份）
  战斗域    battle/      CTB 调度 / 行动结算 / 效果叠层 / 落地 / 存档 / AI / 面板公式
  通用原语  expr/        表达式求值器（数值公式自定义）
            gauge/       计量条（累积/衰减/阈值/免疫窗口）
            formation/   站位与目标选择几何
                        （2026-09-13 P4 下沉：中文 kind 词表 kinds/ 已归内容侧，
                          见游戏仓 `game/data/kinds.py`；引擎只留 config.kind_of 注入面）
  运行时    store/       SQLite 骨架（连接/锁/事务/迁移/Repository）
            command/     命令层骨架（声明注册表/路由/分页/守卫/提示）
            text/        文案模板表（输出侧文本：装载/渲染/缺失自检）
            events/      领域事件总线
            clock/       懒计时器
            log/         日志门面（命名 / 可拔插出口 sink / 结构化上下文）
            tlog/        结构化流水（Record / KindTable / sink / 读口 / 重放 / 事件桥）
            space/       空间形状（节点表 + 拓扑 → 邻接 / 深度 / 出入口 / 必经路径 / 审计）
            loot/        随机产出形状（掉落池 / 档位阶梯 / 槽位挂载 / 加权抽取原语）
            container/   容量受限格子容器
            session/     宿主会话适配
            run/         运行形状（准入链 / 进度 / 名单）
            dialogue/    对话树形状（节点 / 选项 / 条件槽 / 会话游标）
            presence/    在场形状（清单判定 / 当天派生 / 保底冷却）
            host/        宿主运行时（包加载 / 会话循环 / 命令通道 / 战斗驱动）
                         ★ 平台三函数（recv/load_player+save_player/say）与可选钩子由**适配器**给；
                           本模块零平台知识、零游戏知识 —— 换包 = 换 package_dir（一个进程一个包）

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
from .battle.schedule import action_time, initial_ct, recover_time, settle_landing
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
    clock, command, container, dialogue, domains, events, expr, formation, gauge, log, loot,
    presence, run, session, space, store, text, tlog,
)
from . import host  # noqa: F401  （宿主运行时：放在最后 import，避免与上面各模块的加载顺序打架）
from .host import Host, load_package  # noqa: F401
# 指令声明 / 文案表（声明驱动：可拔插，未装载 = 零行为）
from .command import CommandRegistry, CommandSpec  # noqa: F401
from .text import TextSpec, TextTable, safe_format  # noqa: F401
# 结构化流水（声明驱动：KindTable 未装载 = 不校验）
from .tlog import KindTable, Record, TLog  # noqa: F401
# 空间形状（节点表 + 拓扑 → 派生；第三方可注册自定义拓扑）
from .space import Space  # noqa: F401
# 随机产出（池 + 策略注册表 / 档位阶梯 / 槽位挂载）
from .loot import LootTable, TierTable  # noqa: F401
# 运行形状（准入链 + 进度 + 名单）
from .run import Admission, Progress, Roster, Rule, Verdict  # noqa: F401
# 对话树形状（节点 / 选项 / 条件槽 / 会话游标）
from .dialogue import Cursor, Dialogue  # noqa: F401

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
    "fire", "action_time", "initial_ct", "recover_time", "settle_landing",
    # 阵营
    "hostile_sides",
    # 行动结算工具
    "heal_amount", "skill_pay_of",
    # 序列化（存档兼容：拆仓方案 §8-R11）
    "from_state", "to_state",
    # 子模块
    "battle", "actions", "actors", "ai", "effect_triggers", "effects", "formulas",
    "landing", "schedule", "serialize", "state_effects",
    "expr", "gauge", "formation",
    "store", "command", "events", "clock", "log", "tlog", "space", "loot", "dialogue", "presence", "container", "session",
    "text",
    # 运行形状（准入链 / 进度 / 名单）
    "run", "Admission", "Rule", "Verdict", "Progress", "Roster",
    # 对话树形状（节点 / 选项 / 条件槽 / 会话游标）
    "Dialogue", "Cursor",
    # 引擎默认域集 + 合并规则（域元数据合并唯一源：编辑器与装载口同看一份）
    "domains",
    # 声明驱动（指令 / 文案 / 流水）
    "CommandRegistry", "CommandSpec", "TextTable", "TextSpec", "safe_format",
    "TLog", "Record", "KindTable",
    # 空间形状（节点表 + 拓扑 → 派生）
    "Space",
    # 随机产出（掉落池 / 档位阶梯）
    "LootTable", "TierTable",
]
