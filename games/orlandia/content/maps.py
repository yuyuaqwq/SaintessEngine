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
| `MAPS` / `SUBAREAS`（两个装配钩子的**输入**） | 包内 `worlds` / `subareas` + 序真源 `exploration.order`（`content/catalog_space.py`） | 逐条对拍 0 差异（见下「等价证据」） |
| `ENCY_*` / `MONSTER_LOCS`（两个装配钩子的**产出**） | **包内本模块的 4 只模块级 dict**（宿主只留兼容镜像） | B15-W9，见下 |

派生表落点（B15-W9，2026-09-14）
--------------------------------------------------
`build_ency()` / `build_monster_locs()` 产出的 4 张表（`ENCY_MAP_MONSTERS` / `ENCY_MONSTER_MAP` /
`ENCY_MATERIAL_SOURCE` / `MONSTER_LOCS`）**落点已搬进本模块**（模块级 dict，`__all__` 里可见）：

* **改前**：写/读宿主 `game.data` 上那 4 只空 dict —— 宿主 `game/data/maps.py:4364` 只是给它们一个
  落点；删掉宿主 `game/data`，落点消失 → `AttributeError: no attribute 'MONSTER_LOCS'`（沙盒探针
  `overnight/w2_sandbox_delete_data.py` 实测「通过 3 · 失败 11」，11 条全归因本模块）。
  改后同口径复跑：**通过 5 · 失败 9，本模块致因 0 条**；剩下 9 条全在 `content/pets.py`
  （B13-L7 薄壳，真源仍在宿主 `game/data/pets.py`，属别线/B14 —— 改前被本模块的失败挡在后面看不见）。
  取证：`overnight/_w9_sandbox_layers.py`（层归因 + `--maps-old` 换回改前版反证）。
* **改后**：产出只写**包内 4 只 dict**；宿主那 4 只 dict 只做**兼容镜像**（能取到就 `clear()+update()`
  进**同一只对象**，取不到就跳过）—— 与 `content/index.py::_mirror_to_host` 的「同一只子 dict」同义：
  宿主侧读者（`from .data import *` / `C.MONSTER_LOCS`）拿到的引用不变、内容逐条相同。
* **输入**：改用包内域行（`content/catalog_space.py` 的 `MAP_ORDER` / `SUBAREAS`）。
  `base_only=True` = 域里**不带 `hidden` 键**的 430 条「并入前」基础房间；`False` = 全量 628 条。
  两条口径与宿主 `d.MAPS` / `d.SUBAREAS` 在对应时机**读取的同一份内容逐条相等**（实测 4 表
  键集 / 键序 / 逐条值 0 差异，见下「等价证据」）。
* **时机不变**：仍照旧由宿主壳 `game/core/maps.py:47` 在 import 期调一次（那一行未改）。
  「并入前 430 条」现在由 `base_only` 判据表达，不再靠 import 时机兑现 —— 但**结果逐条不变**：
  `MONSTER_LOCS` 仍是 **343 条**（用全量 628 条现算会变 345 条：多 `噬根藤精` / `腐牙萨满·嚎骨`，
  且 174 个怪的地点列表不同）。⚠️ 判据 `"hidden" not in row` 是域里唯一可用的「并入前」标记；
  将来若某个**基础**房间也带 `hidden`，这条等价会破 —— 正解见 `content/catalog_space.py` 头注
  （建议域里补 `mesh: true`）。

等价证据（`overnight/w1213_l7_probe.py`，只读对拍，2026-09-14 实测）
------------------------------------------------------------------
* `maps.json` 键集合 = 宿主 `MAPS` id；`subareas` 域 `map` 集合 = 宿主 `MAPS` id；
* 628 条子区域：宿主 `SUBAREAS[map]`（**列表序**）↔ 包内「`maps.nodes` 序取 `subareas` 行」
  **逐字段 0 差异**（含 `monsters/elite/boss` 六元组）；
* 97 张网状连通表：宿主 `SUBAREA_LINKS_INDEX` ↔ `maps.links` **0 差异**；
* 121 图 `map_space()` 的 邻接 / 深度 / gate / root / topology / audit / route / center /
  `role_of` 标签 **0 差异**（对拍脚本用与宿主同一套构造参数：`nodes` 角色 = `roles` 域值的逆映射、
  `roles=_ROLES`、`gate` 兜底重算）。

等价证据（B15-W9：4 张派生表跨源对拍，2026-09-14 实测）
--------------------------------------------------------
脚本 `overnight/_w9_dump_tables.py`（导出宿主 `C.<名>` 与包内 `catalog_space.<名>` 各一份）+
`overnight/_w9_cmp_tables.py`（键集 + 键序 + 逐条值）：
**4 表全部 0 差异** —— `MONSTER_LOCS` 343 键（= 430 基础房间）/ `ENCY_MAP_MONSTERS` 242 /
`ENCY_MONSTER_MAP` 345 / `ENCY_MATERIAL_SOURCE` 374，键序同、逐条值同
（改后同一脚本再对拍：换源后逐条仍 0 差异；末行见报告）。
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


def _data_mod():
    """宿主 `data` 模块句柄（决策项 U1；接口表第 9 行冻结机制 = 注入名 `data`）。

    注入优先（宿主薄壳 `game/core/maps.py:29`）→ `sys.modules` 已加载的宿主 `data`
    （**不 import 宿主模块树**）→ 抛；调用处吞掉（镜像跳过），不影响包内真源。
    """
    if "data" in _INJECTED:
        return _INJECTED["data"]
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        m = sys.modules.get("%s.data" % prefix)
        if m is not None:
            return m
    raise RuntimeError("maps：宿主 `data` 句柄未注入（宿主薄壳 bind_host(data=…) 负责）——拒绝静默空跑")


def _data():
    """兼容别名（`_mirror_to_host` 用）：= `_data_mod()`。"""
    return _data_mod()


class _HostDB:
    """惰性宿主存储层代理（真源 `from .. import db`）。"""

    def __getattr__(self, name):
        from ._pkgref import DB as _pdb   # B1：包内直取（原宿主 db 句柄）
        return getattr(_pdb, name)


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


# ============================================================
# 装配期派生表（落点 = 包内；B15-W9）
# ============================================================
# 4 只模块级 dict = 真源；宿主 `game.data` 上那 4 只（`game/data/maps.py:4364`）只做兼容镜像。
MONSTER_LOCS: dict = {}
ENCY_MAP_MONSTERS: dict = {}
ENCY_MONSTER_MAP: dict = {}
ENCY_MATERIAL_SOURCE: dict = {}


def _assembly_input(base_only: bool):
    """装配期派生表的输入 → `(maps 序列, {图 id: 行列表})`。

    真源 = 包内域：`content/catalog_space.py` 的 `MAP_ORDER`（序真源 = `exploration.order`，实测与
    宿主 `MAPS` 声明序逐项相同）+ `SUBAREAS`（行 = `subareas` 域行去掉导出注入的 `map` 键）。
    `base_only=True` 取**并入前**的 430 条基础房间（域里不带 `hidden` 键；网状房间 198 条一律带），
    `False` 取全量 628 条 —— 分别对应宿主两个钩子的**读取时机**（`core/maps.py:47` 并入前 /
    `_assembly.py:126` 并入后）。

    `maps` 序列每项形如 `{"id", "name"}`（与宿主 `MAPS` 行被取用的字段同名），所以下面两个 build
    的正文**逐字未改**。与宿主 `d.MAPS` / `d.SUBAREAS` 的对应版本逐条相等，见文件头「派生表落点」
    与报告 `overnight/_w9_maps_derived_to_pkg.md`。
    """
    from . import catalog_space as _cs
    order = list(_cs.MAP_ORDER)
    rows = {}
    for mid in order:
        r = _cs.SUBAREAS.get(mid) or []
        rows[mid] = _cs._base_only(r) if base_only else list(r)
    return [{"id": mid, "name": (_cs._WORLDS_DOM.get(mid) or {}).get("name")} for mid in order], rows


def _mirror_to_host(name: str, table: dict) -> None:
    """宿主兼容镜像（写入方向；宿主不在就跳过）—— 为什么必须**同一只对象**：

    宿主 `game/data/__init__.py:12` 把 `game/data/maps.py:4364` 的 4 只空 dict 绑进 `game.data`，
    再被 `game.content` 的 `from .data import *` / 测试的 `C.<名>` 读；**改前派生表就写在这些对象上**。
    所以这里写入的是**同一只 dict**（先 `clear()` 再 `update()`，对象身份不变 → 宿主侧读者手头的
    引用照旧有效、内容逐条相同），而不是把宿主名重绑成包内对象（那会让 `game.data` 与
    `game.content` 已绑定的名字分叉）。

    取不到宿主（`game/data` 已删 / 未注入 / 该表不在）→ 静默跳过：包内那份 = 真源，读者不再依赖它。
    """
    try:
        dst = getattr(_data(), name, None)
    except Exception:                                        # noqa: BLE001
        return
    if isinstance(dst, dict):
        dst.clear()
        dst.update(table)


def build_ency():
    """派生表构建（`ENCY_MAP_MONSTERS` / `ENCY_MONSTER_MAP` / `ENCY_MATERIAL_SOURCE`）。

    落点 = 包内 3 只 dict；输入 = 包内域行**全量 628 条**（= 宿主 `_assembly.py:126` 时机，
    网状房间并入之后）。`clear()` 只为重复调用幂等（单次调用的结果与改前逐条相同）。
    """
    maps, subs = _assembly_input(base_only=False)
    ency_map_monsters = ENCY_MAP_MONSTERS
    ency_monster_map = ENCY_MONSTER_MAP
    ency_material_source = ENCY_MATERIAL_SOURCE
    ency_map_monsters.clear()
    ency_monster_map.clear()
    ency_material_source.clear()
    for m in maps:
        mid = m["id"]
        mname_cn = m["name"]  # 地图中文名（显示用）
        entries = []
        sas = subs.get(mid, [])
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
    _mirror_to_host("ENCY_MAP_MONSTERS", ency_map_monsters)
    _mirror_to_host("ENCY_MONSTER_MAP", ency_monster_map)
    _mirror_to_host("ENCY_MATERIAL_SOURCE", ency_material_source)


def build_monster_locs():
    """v130.3 意见#3：怪名 → [(子区域显示名, 地图名, 等级, 类型)] 详细分布（含等级/子区域粒度）。

    落点 = 包内 `MONSTER_LOCS`；输入 = 包内域行**并入前的基础 430 条**（`base_only=True`，
    = 宿主 `core/maps.py:47` 的 import 期时机）。`clear()` 只为重复调用幂等。
    """
    maps, subs = _assembly_input(base_only=True)
    monster_locs = MONSTER_LOCS
    monster_locs.clear()
    for m in maps:
        mid, mname_cn = m["id"], m["name"]
        for sa in (subs.get(mid) or []):
            sa_name = sa.get("name") or sa.get("id", "")
            for (_, mname, _, lv, _, _) in (sa.get("monsters") or []):
                monster_locs.setdefault(mname, []).append((sa_name, mname_cn, lv, "普通"))
            if sa.get("elite"):
                (_, estr, _, elv, _, _) = sa["elite"]
                monster_locs.setdefault(estr, []).append((sa_name, mname_cn, elv, "精英"))
            if sa.get("boss"):
                (_, bstr, _, blv, _, _) = sa["boss"]
                monster_locs.setdefault(bstr, []).append((sa_name, mname_cn, blv, "首领"))
    _mirror_to_host("MONSTER_LOCS", monster_locs)


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
    # B15-W9：4 张装配期派生表（落点 = 包内本模块；宿主同名对象只做兼容镜像）
    "MONSTER_LOCS", "ENCY_MAP_MONSTERS", "ENCY_MONSTER_MAP", "ENCY_MATERIAL_SOURCE",
]
