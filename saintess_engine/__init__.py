# -*- coding: utf-8 -*-
"""saintess_engine —— 通用文字游戏框架（多模块并列，依赖自下而上）。

模块布局（全部平级）：

  基础      config      引擎注入面（内容侧装配 hook 的唯一入口）
            domains     引擎默认域集 + 「包声明 ∪ 引擎默认集」合并规则
                        （域元数据合并唯一源：编辑器 `editor/packages.py` 与装载口
                          `records` 委托同一份）
            package     包栈加载器（数据包 + 扩展包：依赖解析 / 拓扑加载 / 域分层）
  通用原语  expr/       表达式求值器（数值公式自定义）
            formula/    声明式公式表（换个游戏只写 JSON）
  运行时    store/      SQLite 骨架（连接/锁/事务/迁移/Repository）
            command/    命令层骨架（声明注册表/路由/分页/守卫/提示）
            text/       文案模板表（输出侧文本：装载/渲染/缺失自检）
            events/     领域事件总线
            clock/      懒计时器
            log/        日志门面（命名 / 可拔插出口 sink / 结构化上下文）
            tlog/       结构化流水（Record / KindTable / sink / 读口 / 重放 / 事件桥）
            space/      空间形状（节点表 + 拓扑 → 邻接 / 深度 / 出入口 / 必经路径 / 审计）
            loot/       随机产出形状（掉落池 / 档位阶梯 / 槽位挂载 / 加权抽取原语）
            container/  容量受限格子容器
            session/    宿主会话适配
            records/    资料表读口（域 JSON → 只读资料表 + 索引 + 查询原语）
            run/        运行形状（准入链 / 进度 / 名单）
            dialogue/   对话树形状（节点 / 选项 / 条件槽 / 会话游标）
            quest 形状   ★ 已移出引擎 → 扩展包 `ext_quest`（2026-09-23）
            presence/   在场形状（清单判定 / 当天派生 / 保底冷却）
            timers/     倒计时事件    periodic/  周期形状    unlock/  解锁闸门
            bonus/      数值修正容器  grant/     奖励发放    conditions/ 条件注册表
            gauge/      计量条        ★ 已移出引擎 → 扩展包 `ext_combat`
            formation/  站位几何      ★ 已移出引擎 → 扩展包 `ext_combat`
            shelf/ trade/ produce/ collect/ membership/  ★ 游戏级形状，见下
            host/       宿主运行时（包加载 / 会话循环 / 命令通道 / 落档）
                        ★ 平台三函数（recv/load_player+save_player/say）与可选钩子由**适配器**给；
                          本模块零平台知识、零游戏知识 —— 换包 = 换 package_dir
                          （**一个进程一个数据包**；扩展包可装多个，见 `package.py`）

★ 游戏级「能力」在**扩展包**里，不在引擎里（2026-09-23 起）：

      extends/ext_combat   回合制战斗（CTB 调度 / 行动结算 / 效果叠层 / 落地 / AI /
                          面板公式 / 计量条 / 站位几何）—— 声明 `provides.battle`
      extends/ext_quest    任务账本 + 目标类型注册表

  数据包要哪个能力就在 `game.json` 里 `"depends": ["ext_combat"]`；
  不装战斗包时引擎照样能加载数据包、跑文字流程 —— 战斗是**可插拔**的，不是内置的。

本文件是**包门面**：外部只需 `from saintess_engine import X`。
包内模块一律相对导入，不反向依赖门面（纯度门禁 tests/test_engine_purity.py）。
"""
# ---- 规则 / 配置 ----
from .config import get_effect_actions, get_effect_rules

# ---- 版本 / 兼容性 ----
from .version import __version__, VERSION_INFO  # noqa: F401
from . import version  # noqa: F401

# ---- 子模块（`from saintess_engine import <模块>` 形态消费）----
from . import config  # noqa: F401
from . import (  # noqa: F401
    clock, command, container, dialogue, domains, events, expr, log, loot,
    presence, run, session, space, store, text, tlog,
)
from . import host  # noqa: F401  （宿主运行时：放在最后 import，避免与上面各模块的加载顺序打架）
from .host import Host  # noqa: F401
# 包栈加载器（唯一入口：数据包 + 扩展包）
from .package import Package, PackageError, PackageStack, load_stack, probe_stack  # noqa: F401
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
    # 包栈（数据包 + 扩展包）
    "Package", "PackageError", "PackageStack", "load_stack", "probe_stack",
    # 规则 / 配置
    "get_effect_actions", "get_effect_rules", "config",
    # 宿主
    "Host",
    # 子模块
    "store", "command", "events", "clock", "log", "tlog", "space", "loot", "dialogue",
    "presence", "container", "session", "text", "expr", "domains", "host",
    # 运行形状（准入链 / 进度 / 名单）
    "run", "Admission", "Rule", "Verdict", "Progress", "Roster",
    # 对话树形状（节点 / 选项 / 条件槽 / 会话游标）
    "Dialogue", "Cursor",
    # 声明驱动（指令 / 文案 / 流水）
    "CommandRegistry", "CommandSpec", "TextTable", "TextSpec", "safe_format",
    "TLog", "Record", "KindTable",
    # 空间形状（节点表 + 拓扑 → 派生）
    "Space",
    # 随机产出（掉落池 / 档位阶梯）
    "LootTable", "TierTable",
]
