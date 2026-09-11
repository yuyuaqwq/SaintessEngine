# -*- coding: utf-8 -*-
"""命令层骨架 —— 路由 / 分页 / 文本 / 守卫 / 提示 / 命令基类 / 指令声明注册表。

与宿主的边界：本包**不 import 任何宿主**（AstrBot 等）。宿主差异经钩子注入
（见 `base.CommandBase` 的「钩子」一节，以及 `router` 的宿主探测函数）。
"""
from .base import CommandBase  # noqa: F401
from .guards import require_battle, require_player  # noqa: F401
from .paging import page_items, parse_page  # noqa: F401
from .registry import CommandRegistry, CommandSpec, combine_patterns  # noqa: F401
from .router import HandlerHit, PatternSet, find_static, matches_any, run_shortcut  # noqa: F401
from .text import strip_at_prefix, strip_command  # noqa: F401
from .tips import pick_tip  # noqa: F401

__all__ = [
    "CommandBase",
    "HandlerHit", "PatternSet", "find_static", "matches_any", "run_shortcut",
    "page_items", "parse_page",
    # 指令声明注册表（声明驱动：装载/查询/匹配/派生/漂移自检）
    "CommandRegistry", "CommandSpec", "combine_patterns",
    "require_player", "require_battle",
    "strip_at_prefix", "strip_command",
    "pick_tip",
]
