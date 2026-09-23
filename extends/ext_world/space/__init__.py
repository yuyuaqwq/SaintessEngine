# -*- coding: utf-8 -*-
"""空间形状 —— 节点表 + 拓扑 → 邻接 / 深度 / 出入口 / 必经路径 / 结构审计。

**零知识**：角色名（`hub` / `through` / `exit`）只是**名字**，取值由内容侧给
（引擎不认「城镇」这类具体取值，也不 import 宿主）。

对外两件东西::

    from ext_world.space import Space, register_topology

    sp = Space(nodes=[...], topology="star", roles={"hub": "…", "exit": "…"})
    sp.links("a"); sp.depth("b"); sp.gate(); sp.route("a", "b"); sp.audit(); sp.to_view()

    register_topology("ring", fn)     # 第三方自定义形状

细节见 `graph.Space` 与 `topology` 的模块文档；形状判据见 `docs/engine-wiki/reference/space.md`。
"""
from __future__ import annotations

from .graph import Space
from .topology import (MESH, TOPOLOGIES, get_topology, register_topology,
                       topology_doc, topology_names)

__all__ = [
    "Space",
    # 拓扑注册表（第三方扩展点）
    "MESH", "TOPOLOGIES", "register_topology", "get_topology", "topology_names", "topology_doc",
]
