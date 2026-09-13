# -*- coding: utf-8 -*-
"""包内空间域（`content/maps.py`）—— 游戏仓 `game/core/maps.py`（229 行）**逐字端口**。

B13-L7（2026-09-14）。宿主 `game/core/maps.py` 已改成薄壳（本模块再导出 + 一行委托）。

搬的边界（**只改「宿主取件」两类**，正文逐字不动）
--------------------------------------------------
| 真源取件 | 包内替身 | 依据 |
|---|---|---|
| `SUBAREAS[map_id]` / `SUBAREA_LINKS_INDEX[map_id]`（形状读） | 包内 `maps` 域（`content/data/maps.json`：`nodes/roles/topology/links`） | 逐项对拍 121 图 **0 差异**（见下「等价证据」） |
| `SUBAREAS[map_id]`（`hidden`/`reveal` 读） | 包内 `subareas` 域（`content/data/subareas.json`，键 = 子区域 id） | 628 条**逐字段**与宿主装配后 `SUBAREAS` 相同、逐图列表序相同（对拍 0 差异） |
| `from .. import db`（`db.xxx`） | 模块级 `db`（`bind_host` 注入 / `sys.modules` 兜底） | 存储层留宿主（平台适配） |
| `MAPS` / `SUBAREAS` / `ENCY_*` / `MONSTER_LOCS`（**仅两个装配钩子**） | 宿主 `data` 句柄（**不切包内**，见下） | 见「未切包内的读点」 |

未切包内的读点（**实测理由，不是偷懒**，B14 统一裁）
----------------------------------------------------
`build_ency()` / `build_monster_locs()` 两个**宿主数据装配钩子**的输入输出全走宿主 `data` 句柄：

1. **`MAPS` 迭代序不可逆**：`maps`/`worlds` 两域的外层键都是**字典序**（导出契约 `sort_table`），
   宿主 `MAPS` 的声明序（首项 `oak_town`）在包里没有落点 → 换源 = `ENCY_MAP_MONSTERS` /
   `MONSTER_LOCS` 的插入序漂移（实测：`maps.json` 首键 `abyss_altar` ≠ 宿主首图 `oak_town`）。
2. **装配时机敏感（实测，最要紧的一条）**：`game/core/maps.py` 在
   `game/data/_assembly.py:9`（`..core.index`）→ `game/core/__init__.py:53` 这一链上被 import，
   而网状房间 `EXTRA_SUBAREAS` 的并入在 `_assembly.py:97`。所以模块级 `_build_monster_locs()`
   读到的是**并入前**的 `SUBAREAS` —— 实测：运行时 `MONSTER_LOCS` 343 条 ≠ 用**最终** SUBAREAS
   现算（2 个怪整体缺失、174 个怪的地点列表不同）。换成包内域（= 最终态 628 条）会**改行为**。
3. `ENCY_*` / `MONSTER_LOCS` 三张派生表**还没有同名域**（`editor/domains.json` 无此名）→ 目标
   只有宿主对象可写（写入经注入句柄，I2 允许）。

等价证据（`overnight/w1213_l7_probe.py`，只读对拍，2026-09-14 实测）
------------------------------------------------------------------
* `maps.json` 键集合 = 宿主 `MAPS` id；`subareas` 域 `map` 集合 = 宿主 `MAPS` id；
* 628 条子区域：宿主 `SUBAREAS[map]`（**列表序**）↔ 包内「`maps.nodes` 序取 `subareas` 行」
  **逐字段 0 差异**（含 `monsters/elite/boss` 六元组）；
* 97 张网状连通表：宿主 `SUBAREA_LINKS_INDEX` ↔ `maps.links` **0 差异**；
* 121 图 `map_space()` 的 邻接 / 深度 / gate / root / topology / audit / route / center /
  `role_of` 标签 **0 差异**（对拍脚本用与宿主同一套构造参数：`nodes` 角色 = `roles` 域值的逆映射、
  `roles=_ROLES`、`gate` 兜底重算）。
"""
from __future__ import annotations

import importlib
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))          # <pkg>/content
_DATA_DIR = os.path.join(_HERE, "data")


def _read_json(name: str, default):
    """读包内 `content/data/<name>`（缺文件 / 坏 JSON → default，不抛 —— 与 `content/tables.py` 同款）。"""
    try:
        with open(os.path.join(_DATA_DIR, name), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                        # noqa: BLE001
        return default


# maps 域（图内形状）：{map_id: {name, roles, nodes:[{id,name,role}], topology, links?}}
_MAPS: dict = _read_json("maps.json", {})
# subareas 域（房间内容）：{subarea_id: 源行原样 + 注入 map}
_SUBS: dict = _read_json("subareas.json", {})

# `roles` 兜底（域里每张图都带 `roles`，实测 121/121 同值 —— 取第一个非空的当兜底，防单图缺键）
_DOM_ROLES: dict = next((e.get("roles") for e in _MAPS.values() if e.get("roles")), {})


# ============================================================
# 宿主替身口（`db` / `data`）—— 正文 `db.xxx(...)` 一行未改
# ============================================================
_HOST_PKG = "data.plugins.dragonfall.game"      # 运行时（main.py 的模块路径）
_HOST_PKG_FALLBACK = "game"                     # 测试/工具按 `game.xxx` 直接 import 时
_INJECTED = {}


def bind_host(**objs):
    """宿主替身注入（幂等）——键 = 模块名（`db` / `data`）。宿主薄壳 import 期调用。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def lazy_host_module(full_name: str):
    """按**完整模块名**包一个惰性宿主模块句柄 —— 宿主薄壳用它注入自己那棵树的模块：:

        _M.bind_host(data=_M.lazy_host_module(__package__.rsplit(".", 1)[0] + ".data"))

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
    raise RuntimeError("maps：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (name, last))


class _HostMod:
    """宿主模块替身（`data`）——`_data().MAPS` 正文不动，属性访问时解析。"""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return getattr(_host_module(self._name), attr)


def _data():
    """宿主 `game.data`（MAPS / SUBAREAS / ENCY_* / MONSTER_LOCS —— 装配钩子的那一份）。"""
    if "data" in _INJECTED:
        return _INJECTED["data"]
    return _host_module("data")


class _HostDB:
    """惰性宿主存储层代理（真源 `from .. import db`）。"""

    def __getattr__(self, name):
        return getattr(_host_module("db"), name)


db = _HostDB()


# ============================================================
# 包内域读口（maps / subareas 域）—— 宿主 `SUBAREAS` / `SUBAREA_LINKS_INDEX` 的等价物
# ============================================================
def _map_entry(map_id: str) -> dict:
    """该图的形状条目（未知图 → 空 dict，与宿主 `SUBAREAS.get(map_id) or []` 同义）。"""
    ent = _MAPS.get(map_id)
    return ent if isinstance(ent, dict) else {}


def _role_by_type(ent: dict) -> dict:
    """子区域 type（域 `nodes[].role` 原样）→ 引擎角色名（= 宿主 `_ROLE_BY_TYPE` 的**逆映射**，
    取值来自域 `roles`，不新增第二处定义）。"""
    return {v: k for k, v in ((ent.get("roles") or _DOM_ROLES) or {}).items()}


def _sa_rows(map_id: str) -> list:
    """该图子区域行（**声明序** = `maps.nodes` 序；行 = `subareas` 域原样）。
    与宿主 `SUBAREAS.get(map_id, [])` 逐字段等价（实测 628 条 0 差异）。"""
    return [row for row in (_SUBS.get(n.get("id")) for n in (_map_entry(map_id).get("nodes") or []))
            if isinstance(row, dict)]


def _subarea_links_index(map_id: str):
    """该图的显式网状连通表（无显式定义 → None，与宿主 `SUBAREA_LINKS_INDEX.get` 同义）。"""
    return _map_entry(map_id).get("links")


# ---- v183 引擎形状适配：本游戏的「角色映射」----------------------------------
# 引擎只认角色名（hub/through/exit），**取值**由内容侧给 —— 这三条映射就是全部内容。
_ROLES = {"hub": "hub", "through": "through", "exit": "exit"}


def map_space(map_id: str):
    """本图的引擎 `Space`（节点 = 子区域，角色 = type 映射；显式连通表优先）。

    不缓存：`SUBAREAS` 运行期可被副本克隆增补（缓存会读到半成品）；构造很便宜
    （每图 ≤ 十余节点），移动路径上的调用量级可接受。
    """
    from saintess_engine.space import MESH, Space
    ent = _map_entry(map_id)
    role_of_type = _role_by_type(ent)
    nodes = [{"id": n["id"], "name": n.get("name"), "role": role_of_type.get(n.get("role"))}
             for n in (ent.get("nodes") or [])]
    mesh = _subarea_links_index(map_id)
    # 旧数据兜底（v87 时期的老图）：城里没有「城镇出口」类型节点时，出入口退回
    # id 以 `_gate` 结尾者。属**内容策略**（引擎不认识 id 命名习惯），故在适配层算好传进去。
    gate_override = None
    if (nodes and nodes[0]["role"] == _ROLES["hub"]
            and not any(n["role"] == _ROLES["exit"] for n in nodes)):
        gate_override = next((n["id"] for n in nodes if str(n["id"]).endswith("_gate")), None)
    if mesh is not None:
        return Space(nodes=nodes, topology=MESH, roles=_ROLES, links=mesh,
                     label_key="name", gate=gate_override)
    topo = "star" if (nodes and nodes[0]["role"] == _ROLES["hub"]) else "chain"
    return Space(nodes=nodes, topology=topo, roles=_ROLES, label_key="name", gate=gate_override)


def map_center(map_id: str) -> str:
    """枢纽节点 id（星形图的中心）；链状/网状图无枢纽 → ""。"""
    sp = map_space(map_id)
    return sp.root if sp.role_of(sp.root) == _ROLES["hub"] else ""


def map_route(map_id: str, src: str, dst: str) -> list:
    """同图必经路径（**含两端**）；同点 → 单元素；任一端未知或不可达 → []。

    用途：把「不能直达，需要先经过 X、Y」这类提示从手算改成问引擎
    （v183 之前该判断在 travel / world 各抄了一份星形链首逻辑）。
    """
    return map_space(map_id).route(src, dst)


def build_ency():
    """宿主派生表构建（`ENCY_MAP_MONSTERS` / `ENCY_MONSTER_MAP` / `ENCY_MATERIAL_SOURCE`）。

    ⚠️ 输入（`MAPS` / `SUBAREAS`）与输出（三张 `ENCY_*`）**都取宿主 `data` 句柄**：
    见文件头「未切包内的读点」1/2/3（MAPS 序不可逆 + 装配时机敏感 + 无同名域）。
    """
    d = _data()
    ency_map_monsters = d.ENCY_MAP_MONSTERS
    ency_monster_map = d.ENCY_MONSTER_MAP
    ency_material_source = d.ENCY_MATERIAL_SOURCE
    subareas = d.SUBAREAS
    for m in d.MAPS:
        mid = m["id"]
        mname_cn = m["name"]  # 地图中文名（显示用）
        entries = []
        sas = subareas.get(mid, [])
        for sa in sas:
            for (mid_m, mname, role, lv, skills, drops) in (sa.get("monsters") or []):
                # v101.29：key/显示统一用中文名——v48 ID 重构后百科查询端
                # 用中文名查 ID-keyed 表恒失效（材料/怪物/地图查询全坏），
                # 且掉落来源显示会泄漏 m_*/map_id 内部 ID
                ency_monster_map.setdefault(mname, []).append((mname_cn, "普通"))
                for dd in drops:
                    ency_material_source.setdefault(dd, []).append((mname_cn, mname))
                entries.append((mname, lv, "普通"))
            if sa.get("elite"):
                (eid, estr, erole, elv, eskl, edrops) = sa["elite"]
                ency_monster_map.setdefault(estr, []).append((mname_cn, "精英"))
                for dd in edrops:
                    ency_material_source.setdefault(dd, []).append((mname_cn, estr))
                entries.append((estr, elv, "精英"))
            if sa.get("boss"):
                (bid, bstr, brole, blv, bskl, bdrops) = sa["boss"]
                ency_monster_map.setdefault(bstr, []).append((mname_cn, "首领"))
                for dd in bdrops:
                    ency_material_source.setdefault(dd, []).append((mname_cn, bstr))
                entries.append((bstr, blv, "首领"))
        ency_map_monsters[mid] = entries
        ency_map_monsters[mname_cn] = entries  # v101.29 双 key：玩家输中文地图名也能查


def build_monster_locs():
    """v130.3 意见#3：怪名 → [(子区域显示名, 地图名, 等级, 类型)] 详细分布（含等级/子区域粒度）。

    ⚠️ 与 `build_ency` 同一条：输入/输出全走宿主 `data` 句柄（装配时机敏感，见文件头）。
    """
    d = _data()
    monster_locs = d.MONSTER_LOCS
    subareas = d.SUBAREAS
    for m in d.MAPS:
        mid, mname_cn = m["id"], m["name"]
        for sa in (subareas.get(mid) or []):
            sa_name = sa.get("name") or sa.get("id", "")
            for (_, mname, _, lv, _, _) in (sa.get("monsters") or []):
                monster_locs.setdefault(mname, []).append((sa_name, mname_cn, lv, "普通"))
            if sa.get("elite"):
                (_, estr, _, elv, _, _) = sa["elite"]
                monster_locs.setdefault(estr, []).append((sa_name, mname_cn, elv, "精英"))
            if sa.get("boss"):
                (_, bstr, _, blv, _, _) = sa["boss"]
                monster_locs.setdefault(bstr, []).append((sa_name, mname_cn, blv, "首领"))


def subarea_links(map_id: str, subarea_id: str) -> list:
    """同图内可直达的子区域 id 列表（v183：派生搬进引擎 `saintess_engine.space`）。

    显式网状连通表（`maps` 域的 `links`）优先；否则按拓扑派生：**城镇星形
    （枢纽 ↔ 场所、通道 ↔ 出口，含无通道时枢纽直连出口的防断链分支）/ 野外线性**。
    结果**包含隐藏房间，不过滤** —— 隐藏房间的可见性由命令层过滤（历史契约不变）。

    注（v141 审计）：副本大陆克隆的 subareas 无命令层消费本函数 —— 保留待动态化；
    命令层副本移动走 SUBAREA_LINKS_INDEX（instance.py _subarea_arrive 直读数据表）。
    """
    return map_space(map_id).links(subarea_id)


def map_exit_subarea(map_id: str) -> str:
    """离开该图必须所在的子区域（v183：= 引擎 `Space.gate()`）。

    城镇：城镇出口子区域；非城镇：首个子区域（入口）。
    ★ 与 `map_entry_subarea` **同义** —— v183 之前这两份实现逐字重复，现已合一
    （两者都问引擎同一个 gate，名字保留只为调用方零改动）。
    """
    return map_space(map_id).gate()


def map_entry_subarea(map_id: str) -> str:
    """跨图进入该图的落点子区域（v183：= 引擎 `Space.gate()`，与 map_exit_subarea 同义）。

    城镇：出口子区域（从野外进城先到镇郊，再经东大街进广场）；非城镇：首个子区域。
    注：注册/传送/回家等「城内直达」场景用 subareas[0]（广场），不走城门。
    """
    return map_space(map_id).gate()


# ---- v115 网状子区域核心 ----

def _explore_count(group_id: str, qq_id: str, map_id: str) -> int:
    """当前探索计数：event_state key = reveal_{map_id}_{qq_id}。"""
    raw = db.get_event_state("reveal_{}_{}".format(map_id, qq_id))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def subarea_depth(map_id: str, sa_id: str) -> int:
    """从该图首个子区域（入口）算的深度（v183：口径由引擎定）。

    - 显式连通表 → 从入口 BFS（网状图没有天然顺序）
    - 否则 → 声明序（子区域列表位置：链状/星形图里顺序本身就是作者给的由近及远）
    """
    return map_space(map_id).depth(sa_id)


def is_hidden_room(map_id: str, sa_id: str) -> bool:
    """查 subareas 域中该子区域条目的 hidden 字段（默认 False）。"""
    for s in _sa_rows(map_id):
        if s.get("id") == sa_id:
            return bool(s.get("hidden"))
    return False


def reveal_met(cond, group_id: str, qq_id: str, map_id: str) -> bool:
    """reveal 条件是否满足。cond 形如：
    - "explore:N"：event_state key=reveal_{map}_{qq} 的探索次数 ≥ N
    - "item:道具名"：db.count_item > 0
    无 cond / 未知格式化 → True（开放）。"""
    if not cond:
        return True
    if cond.startswith("explore:"):
        try:
            need = int(cond.split(":", 1)[1])
        except (TypeError, ValueError):
            return False
        return _explore_count(group_id, qq_id, map_id) >= need
    if cond.startswith("item:"):
        item = cond.split(":", 1)[1]
        return db.count_item(group_id, qq_id, item) > 0
    return True


def reveal_progress(group_id: str, qq_id: str, map_id: str):
    """返回 (cur, need)——当前探索计数 与 本图需探索次数的最大值。
    本图无 explore: 型 reveal 房间 → 返回 (0, 0)。"""
    needs = []
    for s in _sa_rows(map_id):
        cond = s.get("reveal")
        if cond and cond.startswith("explore:"):
            try:
                needs.append(int(cond.split(":", 1)[1]))
            except (TypeError, ValueError):
                pass
    if not needs:
        return (0, 0)
    return _explore_count(group_id, qq_id, map_id), max(needs)


def bump_explore_count(group_id: str, qq_id: str, map_id: str):
    """探索计数 +1（G agent 会在每次野外探索时调用）。
    event_state key = reveal_{map_id}_{qq_id}。"""
    key = "reveal_{}_{}".format(map_id, qq_id)
    db.set_event_state(key, _explore_count(group_id, qq_id, map_id) + 1)


__all__ = [
    "map_space", "map_center", "map_route", "build_ency", "build_monster_locs",
    "subarea_links", "map_exit_subarea", "map_entry_subarea", "subarea_depth",
    "is_hidden_room", "reveal_met", "reveal_progress", "bump_explore_count",
    "bind_host",
]
