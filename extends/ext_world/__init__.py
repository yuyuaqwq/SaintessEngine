# -*- coding: utf-8 -*-
"""空间与运行形状 —— 地图节点/拓扑，以及准入链/进度/名单 —— 扩展包 `ext_world` 的门面。

原在 `saintess_engine/` 里，2026-09-23 包栈重构时抽成扩展包（模块内容未改，只改
了指向引擎的相对导入）。数据包要用：`game.json` 里声明 `"depends": ["ext_world"]`。

本文件把原引擎门面导出的那批符号照原样转出去，外部只需把
`from saintess_engine import X` 改成 `from ext_world import X`。
"""
from .space import (Space, MESH, TOPOLOGIES, register_topology, get_topology, topology_names, topology_doc)
from .run import (Admission, Rule, Verdict, PASS, DENY, SKIP, Progress, Roster)
from . import space, run

__all__ = [
    "space",
    "run",
    "Space", "MESH", "TOPOLOGIES", "register_topology", "get_topology", "topology_names",
    "topology_doc", "Admission", "Rule", "Verdict", "PASS", "DENY",
    "SKIP", "Progress", "Roster",
]
