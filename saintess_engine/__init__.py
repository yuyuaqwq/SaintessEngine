# -*- coding: utf-8 -*-
"""saintess_engine —— 通用文字游戏框架（多模块并列，依赖自下而上）。

模块布局（全部平级）：

  基础      config      引擎注入面（内容侧装配 hook 的唯一入口）
            domains     引擎默认域集 + 「包声明 ∪ 引擎默认集」合并规则
            package     包栈加载器（数据包 + 扩展包 · 依赖解析 / 拓扑加载 / 域分层）
  通用原语  expr/       表达式求值器（数值公式自定义）
            formula/    声明式公式表
            conditions/ 条件形状    bonus/ grant/ gates/ wire/ _validators/
  运行时    store/      玩家与世界的存储    command/  指令注册与路由
            events/     事件总线           clock/     时钟    container/ 容器
            text/       文案表（代码只传槽位）  session/ 会话    log/ tlog/  日志与流水
            records/    声明式记录读取
  宿主      host/       宿主运行时（包加载 / 会话循环 / 命令通道 / 战斗驱动半边）

★ 游戏级能力在**扩展包**里，不在引擎里（2026-09-23 起，见 extends/）：
  战斗    ext_combat     CTB / 结算 / 效果 / 面板 / 计量条 / 站位  （声明 provides.battle）
  任务    ext_quest      任务账本 + 目标类型
  空间    ext_world      地图节点与拓扑 · 准入链与进度名单
  生活    ext_life       收集计数 / 周期 / 倒计时 / 解锁闸门
  经济    ext_economy    交易限购 / 货架 / 计时生产
  社交    ext_social     成员职位与贡献 / 在场清单
  产出    ext_loot       掉落池 / 档位阶梯 / 槽位挂载
  对话    ext_dialogue   对话树与会话游标

  引擎只留「任何文字游戏都要的那一层」。数据包要哪块能力，就在自己的 `game.json` 里
  声明 `"depends": ["ext_combat", ...]` —— 包栈会按拓扑序装好。

本文件是**包门面**：外部只需 `from saintess_engine import X`。
包内模块一律相对导入，不反向依赖门面（纯度门禁 tests/test_engine_purity.py）。
"""
# ---- 规则 / 配置 ----
# ---- 版本 ----
from .version import __version__, VERSION_INFO             # noqa: F401
from . import version                                       # noqa: F401
# ---- 子模块 ----
from . import config                                        # noqa: F401
from . import (clock, command, container, domains, events, expr, log,     # noqa: F401
               session, store, text, tlog)
from . import host                                          # noqa: F401
from .host import Host                                      # noqa: F401
from .package import Package, PackageError, PackageStack, load_stack   # noqa: F401
from .command import CommandRegistry, CommandSpec           # noqa: F401
from .text import TextSpec, TextTable, safe_format          # noqa: F401
from .tlog import KindTable, Record, TLog                   # noqa: F401

__all__ = [
    "__version__", "VERSION_INFO", "version",
    # 子模块
    "config", "clock", "command", "container", "domains", "events", "expr", "log",
    "session", "store", "text", "tlog", "host",
    # 门面直接转出的名字
    "Host", "Package", "PackageError", "PackageStack", "load_stack",
    "CommandRegistry", "CommandSpec",
    "TextSpec", "TextTable", "safe_format",
    "KindTable", "Record", "TLog",
]
