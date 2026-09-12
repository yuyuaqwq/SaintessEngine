# -*- coding: utf-8 -*-
"""拓扑形状注册表 —— 节点表 → 邻接 + 出入口。

一个「拓扑」就是一个纯函数::

    fn(nodes, *, roles, role_key, root) -> {"links": {id: [id…]}, "gate": id}

    nodes      已规范化的节点视图（保持声明序；每项 {"id": str, "role": str | None}）
    roles      角色名 → 取值 的映射（如 {"hub": "中心"}）；缺角色 = 该角色不存在
    role_key   内容侧节点里承载角色的字段名（引擎只是知道有个字段，不认取值）
    root       首节点 id（内容侧可显式指定）

★ `links` **不必对称**：`Space.audit()` 会把不对称**报出来**，但不替内容侧补边
（补边是内容决策，引擎擅自补会掩盖数据错误）。

内置两种派生形状（`mesh` 不是派生形状，它是「不派生、显式给连通表」的保留名）:

| 名字 | 形状 | 规则 |
|---|---|---|
| `chain` | 链状 / 线性 | 按声明序相邻（i ↔ i+1）；出入口 = 首节点 |
| `star` | 星形 | 枢纽 ↔ 辐条；通道 ↔ 出口；含两条防断链分支（见 `_star` 文档） |

第三方要环形 / 网格 / 迷宫，`register_topology("ring", fn)` 即可 —— 引擎不预设形状集合。
"""
from __future__ import annotations

# `mesh`：保留名 —— 表示邻接由内容侧显式给出（Space 收到 links 时生效），引擎不做派生。
MESH = "mesh"

# 注册表：name -> {"fn": callable, "doc": str}
TOPOLOGIES: dict = {}


def register_topology(name: str, fn, *, doc: str = "", replace: bool = False):
    """注册一个拓扑形状。名字是**内容侧命名空间**（引擎不占名字）。返回 fn 便于装饰器用法。

    重名默认报错（防静默覆盖）；确实要覆盖时显式 `replace=True`。
    """
    if not isinstance(name, str) or not name:
        raise ValueError("拓扑名必须是非空字符串")
    if name == MESH:
        raise ValueError(f"`{MESH}` 是保留名（显式连通表），不能注册为该名字")
    if name in TOPOLOGIES and not replace:
        raise ValueError(f"拓扑已注册：{name}（要覆盖请显式 replace=True）")
    if not callable(fn):
        raise TypeError("拓扑必须可调用：fn(nodes, *, roles, role_key, root) -> {'links':…, 'gate':…}")
    TOPOLOGIES[name] = {"fn": fn, "doc": doc}
    return fn


def topology_names() -> tuple:
    """已注册的**派生**形状名（不含保留名 `mesh`）。"""
    return tuple(sorted(TOPOLOGIES))


def get_topology(name: str):
    """取拓扑函数；未注册 → KeyError（由 Space 翻成带可用名字的 ValueError）。"""
    return TOPOLOGIES[name]["fn"]


def topology_doc(name: str) -> str:
    return TOPOLOGIES.get(name, {}).get("doc", "")


# ─────────────────────────────────────────────────────────── 内置形状

def _ids_of(nodes):
    return [n["id"] for n in nodes]


def _with_role(nodes, roles, role_name):
    """角色值为 None 时该角色视为不存在（返回空表）—— 内容侧没声明 = 不生效（零默认值铁律）。"""
    val = roles.get(role_name)
    if val is None:
        return []
    return [n["id"] for n in nodes if n["role"] == val]


def _chain(nodes, *, roles, role_key, root):
    """链状（线性）：按声明序相邻；出入口 = 首节点。"""
    ids = _ids_of(nodes)
    links = {}
    for i, nid in enumerate(ids):
        nb = []
        if i > 0:
            nb.append(ids[i - 1])
        if i < len(ids) - 1:
            nb.append(ids[i + 1])
        links[nid] = nb
    return {"links": links, "gate": root}


def _star(nodes, *, roles, role_key, root):
    """星形：枢纽 ↔ 辐条、通道 ↔ 出口；出入口 = 出口角色节点（无则首节点）。

    规则逐条（`hub` / `through` / `exit` 三个角色名，取值由内容侧给）:

    ```
    枢纽    → 全部非 exit 节点；★ 若无 through 节点，枢纽额外直连 exit
    通道    → 全部 exit 节点 + 枢纽
    出口    → 全部 through 节点；若无 through，直连枢纽
    其他    → 枢纽
    出入口  → 第一个 exit 节点；无 exit 则首节点
    ```

    ★ 两条「无 through 时直连」是**防断链**分支：没有通道层时若不补边，枢纽到出口
    不可达（真实现场：两个城镇缺通道定义 → 「先去出口」提示指向自己 → 玩家出不了城）。
    """
    ids = _ids_of(nodes)
    hub_role = roles.get("hub")
    through_role = roles.get("through")
    exit_role = roles.get("exit")
    hub = next((n["id"] for n in nodes if n["role"] == hub_role), None) if hub_role is not None else None
    if hub is None:
        hub = root
    exits = _with_role(nodes, roles, "exit")
    throughs = _with_role(nodes, roles, "through")
    links = {}
    for n in nodes:
        nid, role = n["id"], n["role"]
        if nid == hub:
            nb = [x for x in ids if x != hub and x not in exits]
            if not throughs:
                nb = nb + list(exits)
            links[nid] = nb
        elif through_role is not None and role == through_role:
            links[nid] = list(exits) + [hub]
        elif exit_role is not None and role == exit_role:
            links[nid] = list(throughs) if throughs else [hub]
        else:
            links[nid] = [hub]
    return {"links": links, "gate": exits[0] if exits else root}


register_topology("chain", _chain, doc="链状（线性）：按声明序相邻；出入口 = 首节点")
register_topology("star", _star,
                 doc="星形：枢纽↔辐条、通道↔出口（含无通道时枢纽直连出口的防断链分支）；出入口 = 出口角色节点")
