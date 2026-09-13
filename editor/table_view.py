# -*- coding: utf-8 -*-
"""通用表格视图（编辑器用）—— 第 2 层视图分派的**内置兜底视图**之一（`view: "table"`）。

为什么有这个
------------
第 2 层让包用 `editor/views.json` 把某个域接到**内置**视图上（`loot_view` / `instance_view` /
`space_view` / `table` / `graph`）。前三个各自绑死一种语义（掉落池 / 副本进度 / 地图拓扑），
包的新域用不上；`table` 是**语义中立**的那一个：把表当表看 —— 一行一条、列 = 表里出现过的
顶层字段，多一条/少一条都不会崩（不认识的形态一律原样展示，不装懂）。

它**不做**的事：不解析引用、不猜字段含义、不校验（校验有 schema）。所以它对任何域、
任何数据都只做一件事：把 JSON 摊成行列。引擎零知识（不 import `saintess_engine`）。

对外接口
--------
    build_file(data, key="") -> dict    # 表形态取整表 / 取一条（纯 JSON，可直接发前端）
"""
from __future__ import annotations

_MAX_CELL = 80          # 单元格里的容器截断长度（表格是速览，不是编辑器）
_MAX_ROWS = 500         # 行数上限（防超大表把响应撑爆）


def _short(v):
    """单元格取值：标量原样；容器转成短串（不展开嵌套，免得行高失控）。"""
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, str):
        return v if len(v) <= _MAX_CELL else v[:_MAX_CELL] + "…"
    import json
    try:
        s = json.dumps(v, ensure_ascii=False)
    except (TypeError, ValueError):
        s = repr(v)
    return s if len(s) <= _MAX_CELL else s[:_MAX_CELL] + "…"


def _fail(msg: str) -> dict:
    return {"ok": False, "error": msg, "warnings": []}


def build_file(data, key="") -> dict:
    """`{条目key: 条目}` 取一条（给了 key）或整表（不给）→ `{ok, view:"table", …}`。"""
    if not isinstance(data, dict):
        return _fail("数据不是对象（表形态需为 {条目: {…}}）")
    if key:
        e = data.get(key)
        if not isinstance(e, dict):
            return _fail(f"条目不存在：{key}")
        rows = [{"字段": k, "值": _short(v)} for k, v in e.items()]
        return {"ok": True, "view": "table", "scope": "entry", "entry": key,
                "columns": ["字段", "值"], "rows": rows, "warnings": []}
    cols: list = []
    for e in data.values():
        if isinstance(e, dict):
            for k in e:
                if k not in cols:
                    cols.append(k)
    keys = [k for k in data if isinstance(data[k], dict)][:_MAX_ROWS]
    rows = []
    for k in keys:
        e = data[k] or {}
        rows.append({"key": k, **{c: _short(e.get(c)) for c in cols}})
    warn = [] if len(keys) == len(data) else [f"表里条目超过 {_MAX_ROWS} 条，只展示前 {_MAX_ROWS} 条"]
    return {"ok": True, "view": "table", "scope": "domain", "columns": ["key"] + cols,
            "rows": rows, "count": len(rows), "total": len(data), "warnings": warn}
