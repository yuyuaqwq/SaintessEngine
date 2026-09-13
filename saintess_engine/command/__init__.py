# -*- coding: utf-8 -*-
"""命令层骨架 —— 路由 / 分页 / 文本 / 守卫 / 提示 / 命令基类 / 指令声明注册表。

与宿主的边界：本包**不 import 任何宿主**（AstrBot 等）。宿主差异经钩子注入
（见 `base.CommandBase` 的「钩子」一节，以及 `router` 的宿主探测函数）。
"""
from .base import CommandBase  # noqa: F401
from .guards import require_battle, require_player  # noqa: F401
from .paging import page_items, parse_page  # noqa: F401
from .registry import CommandRegistry, CommandSpec, combine_patterns  # noqa: F401
from .spec import (  # noqa: F401
    CommandSpecSource, build_registry, catalog_of, load_table, pattern_map_from_table,
)
from .router import HandlerHit, PatternSet, find_static, matches_any, run_shortcut  # noqa: F401
from .text import strip_at_prefix, strip_command  # noqa: F401
from .tips import pick_tip  # noqa: F401

__all__ = [
    "CommandBase",
    "HandlerHit", "PatternSet", "find_static", "matches_any", "run_shortcut",
    "page_items", "parse_page",
    # 指令声明注册表（声明驱动：装载/查询/匹配/派生/漂移自检）
    "CommandRegistry", "CommandSpec", "combine_patterns",
    # 指令声明表装载形状（表在哪由宿主给；派生/校验/fail-closed 收在引擎）
    "CommandSpecSource", "load_table", "build_registry", "pattern_map_from_table", "catalog_of",
    "require_player", "require_battle",
    "strip_at_prefix", "strip_command",
    "pick_tip",
]
