# -*- coding: utf-8 -*-
"""包内探索域门面（`content/exploration.py`）—— 探索进度聚合 + 首访材料池。

服务对象：宿主命令 `game/commands/exploration.py`（『探索进度』，B8.2 薄壳化：
命令只留「注册 / 解析参数 / 取玩家 / 调包 / 拼文案」）。

数据（包内，自包含；真源 = 游戏仓，单向导出 = `scripts/export_domains/collection_exploration.py`）
---------------------------------------------------------------------------------------------------
    content/data/exploration.json  ← `MAPS × SUBAREAS` 的**探索点投影**（628 点）
    形状：{"地图id:子区域id": {map, region, hidden, order}}
      · 点键与宿主 `visited_subareas` 表 / `db.get_visited_subareas(qq_id)` 的键空间**逐字相同**
        （`f"{map_id}:{sa_id}"`）；
      · `order` = `MAPS` 顺序 × 子区域顺序的全局序号（导出期注入：聚合返回序靠它，见下）。

聚合（逐字取自游戏仓 `game/core/exploration.py:96 region_progress` / `:137 overall_progress`）
----------------------------------------------------------------------------------------------
唯一接口替换：真源读 `db.get_visited_subareas(qq_id)` 拿集合 → 本模块改为**调用方传 visited 集合**
（包内不读宿主 DB，与 `content/bridge.py` 同款替身接口）。

    region_progress(visited) -> [{region, total, visited, hidden_total, hidden_found}, …]
      · 返回序 = 点 `order` 序里 region 的**首次出现序**（= 真源 `MAPS` 的 region 顺序，**不是**字典序）
      · total / visited       该境**非隐藏**子区域的 总数 / 已到访数
      · hidden_total / found   该境隐藏房间 总数 / 已到访数
      · 「图无子区域 → 跳过」：点表里本就没有它的点，故与真源 `if not sas: continue` **等价**
    overall_progress(visited) -> {visited, total, hidden_found, hidden_total, pct}
      · `pct = int(round(visited * 100.0 / total)) if total else 0`（含 round 的银行家舍入，
        与真源逐字一致 —— 不要改成 `//` 或 `int*100//total`）。

⚠️ **本模块不含首访材料池**（真源 `_FIRST_VISIT_MAT_POOL`）：它是 `exploration.py` 唯一的模块级
静态表，但消费端是宿主 `record_visit()`（隐藏房间首访随机入包，本次 B8.2 未接线），且「一个域的
所有行同形状」是框架门禁硬要求（见导出插件文件头 ②）→ 材料池**有意未进包**，留在宿主侧。
"""
from __future__ import annotations

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))          # <pkg>/content
_DATA_DIR = os.path.join(_HERE, "data")


def _read_json(path: str, default):
    """读一个 JSON 文件（缺文件 / 坏 JSON / 权限 → default，不抛 —— 与 `content/tables.py` 同款）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                        # noqa: BLE001
        return default


# ============================================================
# ① 探索点表（content/data/exploration.json）
# ============================================================
_TABLE = _read_json(os.path.join(_DATA_DIR, "exploration.json"), {})

# 点行，按 `order` 还原真源遍历序；连**点键**（"地图:子区域"）一起拿着
# —— 键就是宿主 `visited_subareas` 的键，聚合时直接用它判到访，不从 `order` 反推。
_ORDERED = sorted(((k, v) for k, v in (_TABLE or {}).items() if isinstance(v, dict)),
                  key=lambda kv: kv[1].get("order", 0))


def points() -> list:
    """全部探索点（**真源顺序**）：`[{"key": "地图:子区域", map, region, hidden, order}, …]`。

    `key` 是注入的（表键本身）；读不到表 → 空列表。
    """
    return [dict(v, key=k) for k, v in _ORDERED]


def _keys(visited) -> set:
    """到访键集合（调用方给 set / list / tuple 都行；缺省 `None` = 空）。"""
    if isinstance(visited, (set, frozenset)):
        return visited
    try:
        return set(visited or ())
    except TypeError:
        return set()


def region_progress(visited) -> list:
    """按 `region` 聚合的探索进度（返回序 = 真源 MAPS 的 region 首次出现序）。"""
    keys = _keys(visited)
    agg: dict = {}
    order: list = []
    for key, p in _ORDERED:
        region = p.get("region") or ""
        if region not in agg:
            agg[region] = {"region": region, "total": 0, "visited": 0,
                           "hidden_total": 0, "hidden_found": 0}
            order.append(region)
        st = agg[region]
        hit = key in keys
        if p.get("hidden"):
            st["hidden_total"] += 1
            if hit:
                st["hidden_found"] += 1
        else:
            st["total"] += 1
            if hit:
                st["visited"] += 1
    return [agg[r] for r in order]


def overall_progress(visited) -> dict:
    """全大陆探索度：`{visited, total, hidden_found, hidden_total, pct}`（真源逐字公式）。"""
    agg = region_progress(visited)
    visited_n = sum(r["visited"] for r in agg)
    total = sum(r["total"] for r in agg)
    hidden_found = sum(r["hidden_found"] for r in agg)
    hidden_total = sum(r["hidden_total"] for r in agg)
    pct = int(round(visited_n * 100.0 / total)) if total else 0
    return {"visited": visited_n, "total": total,
            "hidden_found": hidden_found, "hidden_total": hidden_total, "pct": pct}
