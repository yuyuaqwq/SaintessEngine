# -*- coding: utf-8 -*-
"""拓扑视图（编辑器用）—— 用引擎**同一份**派生代码算图，不在前端重写第二遍。

为什么值得为它破一条纪律
------------------------
`editor/packages.py` 写着「编辑器主进程零引擎副作用，不 import `saintess_engine`」——
那条纪律针对的是**会挂 hook / 改全局状态**的战斗域。`ext_world.space` 是**纯计算模块**
（零挂载、零全局副作用，与 `version` 同性质），import 它不产生任何引擎副作用。

换来的东西是硬的：邻接 / 深度 / 出入口 / 审计**只有一份实现** ——
编辑器里看到的图和游戏里跑的是同一段代码；若在前端用 JS 重写一遍，两处迟早漂移，
而且漂移时**没人会发现**（编辑器画得好看，游戏里走不通）。

对外接口
--------
    build(entry) -> dict          # 单条 map 数据 → 视图（含 warnings）
    build_file(data, key) -> dict # 表形态取一条（key 不存在 → {ok: False, error}）
"""
from __future__ import annotations


def _nodes(entry: dict) -> list:
    out = []
    for n in (entry.get("nodes") or []):
        if not isinstance(n, dict) or not n.get("id"):
            continue
        d = dict(n)
        d.setdefault("name", n["id"])
        out.append(d)
    return out


def build(entry: dict) -> dict:
    """把一条 map 数据算成视图：`{ok, view?, warnings, error?}`（view 纯 JSON）。"""
    from ext_world.space import MESH, Space

    if not isinstance(entry, dict):
        return {"ok": False, "error": "数据不是对象", "warnings": []}
    nodes = _nodes(entry)
    if not nodes:
        return {"ok": False, "error": "没有可用节点（每项至少要有一个 id）", "warnings": []}

    links = entry.get("links") or None
    topo = entry.get("topology") or None
    roles = entry.get("roles") or {}
    warnings = []
    if not isinstance(roles, dict):
        return {"ok": False, "error": "roles 必须是「角色名 → 取值」的对象", "warnings": []}
    if links and topo and topo != MESH:
        warnings.append(
            f"数据里同时声明了 topology={topo} 与 links —— **连通表优先**，拓扑名不参与派生"
            f"（视图按显式连通表画）"
        )
    if links is None and topo in (None, ""):
        warnings.append("没写 topology 也没给 links —— 按默认形状 chain（链状）派生")
    if links is None and topo == MESH:
        return {"ok": False, "error": "topology=mesh 表示「显式连通表」，但没有 links",
                "warnings": warnings}

    try:
        sp = Space(nodes=nodes,
                   topology=(MESH if links else topo),
                   roles=roles,
                   links=links,
                   root=entry.get("root") or None,
                   gate=entry.get("gate") or None,
                   label_key="name")
    except (ValueError, KeyError) as e:
        return {"ok": False, "error": str(e), "warnings": warnings}

    view = sp.to_view()
    view["warnings"] = warnings
    # 视图里的角色取值去重（前端配色按「角色取值」分色，不认含义）
    view["role_values"] = sorted({n["role"] for n in view["nodes"] if n.get("role")})
    return {"ok": True, "view": view, "warnings": warnings}


def build_file(data: dict, key: str) -> dict:
    """表形态 `{图id: 图对象}` 里取一条算视图。"""
    if not isinstance(data, dict):
        return {"ok": False, "error": "整表不是对象", "warnings": []}
    entry = data.get(key)
    if entry is None:
        return {"ok": False, "error": f"没有这条图：{key}", "warnings": []}
    out = build(entry)
    out["key"] = key
    return out
