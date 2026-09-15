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

⚠️ B8.2 当时**本模块不含首访材料池**（真源 `_FIRST_VISIT_MAT_POOL`，理由：域行须同形状）。
**B13-L7（2026-09-14）已收口**：见文件末「② 到达子区域（首访奖励）」——
`record_visit()` 与材料池逐字搬进本模块（池子是**代码侧常量**，不进域，域行形状未动）。
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


# ============================================================
# ② 到达子区域（首访奖励）—— B13-L7 收口（2026-09-14）
# ------------------------------------------------------------
# 真源：游戏仓 `game/core/exploration.py:39 record_visit` + `:21 _FIRST_VISIT_MAT_POOL`
#       + `:26/:34 _map_by_id/_is_hidden` + `:155-174` 材料三件套 —— **逐字搬**，只换取件：
#
# | 真源取件 | 包内替身 | 说明 |
# |---|---|---|
# | `SUBAREAS.get(map_id)` / `sa.get("hidden")` / `sa.get("id")` | 本模块探索点表（键 `地图:子区域`，字段同源） | 键空间与宿主 `visited_subareas` 逐字相同；628 点 = 628 子区域 |
# | `_map_by_id(map_id).get("lv", 1)` | `content/data/worlds.json`（= 宿主 `MAPS` 条目原样，含 `lv`） | 缺图 → `{}` → lv=1（与真源 `_map_by_id` 返回 `{}` 同义） |
# | `from .. import db` + `db.xxx(...)` | 模块级 `db`（`bind_host` 注入 / `sys.modules` 兜底） | 存储层留宿主（写库、读档、入包全在宿主） |
# | `C.resolve/C.display/C.MATERIALS`（材料名↔id↔价） | `MATERIALS` → **包内门面**（B14-2 L8 已切，`catalog_items`）；`resolve`/`display` 仍走模块级 `C`（宿主 `content` 聚合层句柄） | `MATERIALS` 门禁逐值+键序 OK ✅；`resolve`/`display` 是**函数**（`game/core/index.py`），包内无读口 → 缺口登记 |
#
# 接口不变式：`visited` 那半边（`region_progress(visited)` / `overall_progress(visited)`）签名
# **一字未动**（宿主命令 `game/commands/exploration.py` 与 `game/core/exploration.py` 薄壳都按它调）。
# ============================================================
import random

# v115 隐藏房间首访奖励的随机材料池（固定池）。
# 以材料中文名为池项，运行时用 C.resolve("materials", 名) 取稳定 mat_ 拼音 id 入包。
_FIRST_VISIT_MAT_POOL = ("草药", "铁矿石", "兽肉", "浆果", "蜂蜜")

_WORLDS = _read_json(os.path.join(_DATA_DIR, "worlds.json"), {})

_HOST_PKG = "data.plugins.dragonfall.game"
_HOST_PKG_FALLBACK = "game"
_INJECTED = {}


def bind_host(**objs) -> None:
    """宿主替身注入（幂等）——键 = 模块名（`db` / `content`）。宿主薄壳 import 期调用。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def lazy_module(full_name: str):
    """按**完整模块名**包一个惰性宿主模块句柄 —— 宿主薄壳用它注入自己那棵树的模块：:

        _M.bind_host(data=_M.lazy_module(__package__.rsplit(".", 1)[0] + ".data"))

    为什么必须由薄壳注入全名：同一进程里可能并存 `game.*` 与 `data.plugins.dragonfall.game.*`
    两套模块树（plan §8-R2；`tests/` 两种 import 都有）—— 写目标（`_INDEXES` / `MONSTER_LOCS` /
    派生表）必须落在**调用方那棵树**上，否则另一棵树读到空表。
    """
    import importlib

    class _Mod:
        def __getattr__(self, attr):
            return getattr(importlib.import_module(full_name), attr)

    return _Mod()


def _host_module(name: str):
    """取宿主子模块（注入优先 → `sys.modules` → importlib；**绝不静默空跑**）。"""
    import importlib
    import sys
    if name in _INJECTED:
        return _INJECTED[name]
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        m = sys.modules.get("%s.%s" % (prefix, name))
        if m is not None:
            return m
    last = None
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        try:
            return importlib.import_module("%s.%s" % (prefix, name))
        except Exception as exc:                # noqa: BLE001
            last = exc
    raise RuntimeError("exploration：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (name, last))


class _HostMod:
    """宿主模块替身（`db` / `content`）——正文 `db.xxx(...)` / `C.xxx(...)` 一行未改。"""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return getattr(_host_module(self._name), attr)


from ._pkgref import DB as db, PkgModule
# ★ P4′-W1 A 组：`C.resolve` / `C.display` 实测 `__module__ == "content.index"`（同一只 `_INDEXES`）
C = PkgModule("content.index")

# ★ B14-2 L8（2026-09-14）：`C.MATERIALS`（材料价）→ 包内物品门面直取
#   （门禁 `b14_catalog_gate.py` 逐值+键序 OK；`C` 仍有残余 `resolve`/`display`）
from . import catalog_items as _ci      # noqa: E402


def _map_by_id(map_id: str) -> dict:
    """在 worlds 域（= 宿主 `MAPS` 条目原样）中按 id 定位地图 dict（缺 → `{}`）。"""
    m = _WORLDS.get(map_id)
    return m if isinstance(m, dict) else {}


def _is_hidden(pt: dict) -> bool:
    """子区域是否隐藏房间（v115 新字段 hidden）。"""
    return bool((pt or {}).get("hidden"))


def _map_point(map_id: str, sa_id: str):
    """该图该子区域的探索点行（宿主 `next(s for s in SUBAREAS[map] if s['id']==sa_id)` 的等价物）。"""
    return _TABLE.get("%s:%s" % (map_id, sa_id))


def _map_has_points(map_id: str) -> bool:
    """该图是否有子区域（宿主 `SUBAREAS.get(map_id)` 非空的等价物）。"""
    for _k, v in _ORDERED:
        if v.get("map") == map_id:
            return True
    return False


def record_visit(group_id, qq_id, map_id, sa_id):
    """到达子区域时调用：记录到访 + 首访奖励。

    返回：
      - sa 不存在 / map 无子区域 → None
      - 首访 → {"first": True, "exp": n, "gold": n, "mat": 材料名 or None}
      - 非首访 → {"first": False}
    """
    if not _map_has_points(map_id):
        return None
    pt = _map_point(map_id, sa_id)
    if pt is None:
        return None

    # 判断是否首访（先查集合，命中则非首访）
    visited = db.get_visited_subareas(qq_id)
    key = f"{map_id}:{sa_id}"
    if key in visited:
        return {"first": False}

    # 首访：记录 + 发奖
    db.add_visited_subarea(group_id, qq_id, map_id, sa_id)
    cur = _map_by_id(map_id)
    lv = int(cur.get("lv", 1) or 1)
    exp = lv * 8
    gold = lv * 3

    player = db.get_player(group_id, qq_id)
    if player:
        # v115 §6.2：只加数值，不处理升级（get_player 读档有惰性升级兜底，审计确认无副作用）
        db.update_player(group_id, qq_id,
                         exp=player.get("exp", 0) + exp,
                         gold=player.get("gold", 0) + gold)

    mat = None
    if _is_hidden(pt):
        # 隐藏房间首访额外随机 1 个材料入包
        name = random.choice(_FIRST_VISIT_MAT_POOL)
        mat_id = C_resolve_material(name)
        if mat_id:
            mat_name = C_display_material(mat_id)
            db.add_item(group_id, qq_id, mat_id,
                        {"name": mat_name, "type": "材料", "stackable": True,
                         "price": C_material_price(mat_id)})
            mat = mat_name or name
        else:
            mat = name

    # v115 协作契约：reward 为给命令层拼接展示的友好文案（world.py _subarea_arrive/传送
    # 读取 rv["reward"] → 追加 "🎉 {reward}"）。隐藏房间首访附材料，普通首访仅经验/金币。
    _reward = f"首次探索（{lv} 级区域）！获得经验 +{exp}、金币 +{gold}"
    if mat:
        _reward += f"，并拾得 {mat}"
    return {"first": True, "exp": exp, "gold": gold, "mat": mat, "reward": _reward}


# ---- 材料解析辅助（宿主 `content` 聚合层句柄）----
def C_resolve_material(name):
    """材料中文名 → mat_ 拼音 id（查不到返回原名字，add_item 兜底）。

    ★ R5（静默降级扫描）：删掉 `except Exception: return name` ——「查不到返回原名」本身就是
    `content/index.py::resolve` 的定义（`idx.get(name_or_id, name_or_id)`），那层 except 只会把
    **装配缺陷**（聚合句柄/索引未注入 ⇒ `RuntimeError`）静默降级成「当材料名用」，玩家侧看不出。
    """
    return C.resolve("materials", name)


def C_display_material(mat_id):
    """mat_ id → 显示名。"""
    return C.display("materials", mat_id)


def C_material_price(mat_id):
    """mat_ id → 商店价（无定义给 10）。"""
    try:
        m = _ci.MATERIALS.get(mat_id, {})        # B14-2 L8：包内物品门面（真源 `C.MATERIALS`）
        return m.get("price", 10)
    except Exception:                            # noqa: BLE001
        return 10
