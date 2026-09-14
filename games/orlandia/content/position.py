# -*- coding: utf-8 -*-
"""包内位置结构体（`content/position.py`）—— 游戏仓 `game/core/position.py`（140 行）**逐字端口**（B13-L7）。

正文一字未改，只换「宿主取件」（三处）：
| 真源取件 | 包内替身（★ W12 收口 2026-09-14） |
|---|---|
| `from ..data import MAP_BY_ID` | ★ **已切包内门面** `_cs.MAP_BY_ID`（`catalog_space`，值/键序对拍 OK） |
| `from ..data import SUBAREAS` | ★ **已切包内门面** `_cs.SUBAREAS`（同上） |
| `from .worlds import get_instance_world` | ★ **已切包内直取**（`from .worlds import get_instance_world`，函数内惰性）|

★ W12 收口（2026-09-14）：两张表切门面。**身份语义的落点与验证**
--------------------------------------------------------------
* B14 第一段门面 `content/catalog_space.py` 值与键序逐项相等（`b14_catalog_gate.py` OK；
  `MAP_BY_ID` 值含装配期注入的 `subareas`，门面同款重建 ⇒ 无旧注的「静默丢键」）。
* 宿主 `tests/test_v141_instance_world.py:128/133/192` 按**对象身份**断言
  （`rm is C.MAP_BY_ID.get("oak_town")` / `sa is C.SUBAREAS.get("oak_town")`）。
  **当前宿主 `game/content.py` 还是旧形（`from .data import *`）⇒ `C.MAP_BY_ID` 是宿主那份**，
  与本模块读到的门面对象「值等而身份不等」→ 该 2 条断言在**收口前**必红（实测见
  `overnight/_w12_identity_report.log`，这是**已知且预期**的中间态）。
  收口步（`overnight/_b14_close_new_content_py.py` 把 `game/content.py` 改成再导出包内门面）生效后
  `C.MAP_BY_ID is catalog_space.MAP_BY_ID` ⇒ 两句断言恢复真值（收口模拟 probe
  `overnight/_w12_identity_probe.py` 末行 + `_w12_v141_sim.py` 全绿）。
* `get_instance_world`：宿主 `game/core/worlds.py` 已是薄壳（`sys.modules[__name__] = content.worlds`）
  → 切包内直取是**零行为变更**（B14-2 L8 已实测，函数同一）。

缺口登记（交主 agent 收口）
--------
* 本模块已无宿主 `data` 读点；**身份断言的最后一环 = `game/content.py` 改再导出**（同上）。
* 同款身份断言还有 `content/worlds.py:355`（`resolve_map_for`，测试 `:192`）—— 该文件**不在本线
  范围**，须同期切门面，否则收口后 `:192` 变 RuntimeError。
"""
from __future__ import annotations

import importlib
import sys
from typing import Optional

# ---- 包内门面读口（W12 收口：真源 `from ..data import MAP_BY_ID / SUBAREAS`）----
from . import catalog_space as _cs       # noqa: E402  MAP_BY_ID / SUBAREAS（值 + 键序对拍 OK）

_HOST_PKG = "data.plugins.dragonfall.game"
_HOST_PKG_FALLBACK = "game"
_INJECTED = {}


def bind_host(**objs):
    """宿主替身注入（幂等）——键 = 模块名（`data` / `core.worlds`）。"""
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
    raise RuntimeError("position：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (name, last))


def _get_instance_world(world_id):
    """真源 `from .worlds import get_instance_world`（函数内惰性 import）→ **包内直取**（B14-2 L8）。

    宿主 `game/core/worlds.py` 是薄壳（`sys.modules[__name__] = content.worlds`，实测
    `game.core.worlds is content.worlds` 且函数同一）⇒ 与原宿主句柄取到的是**同一个函数对象**，
    零行为变更（实测 `overnight/_b14_2_L8_idprobe.py` ④）。
    """
    from .worlds import get_instance_world
    return get_instance_world(world_id)


class Position:
    """玩家位置。大陆 id + 地图 id + 子区域 id 三元组。"""

    __slots__ = ("world_id", "map_id", "subarea_id")

    def __init__(self, world_id: str, map_id: str, subarea_id: str = ""):
        self.world_id = world_id or "mainland"
        self.map_id = map_id
        self.subarea_id = subarea_id

    # ---- 构造 ----

    @classmethod
    def from_player(cls, player: dict) -> "Position":
        """从玩家存档解析位置。world_id 缺省 = 主大陆（兼容旧存档）。"""
        w = player.get("world_id") or "mainland"
        return cls(w, player.get("cur_map", "") or "", player.get("cur_subarea", "") or "")

    @classmethod
    def from_db(cls, world_id: Optional[str], map_id: str, subarea_id: str = "") -> "Position":
        """从数据库行/字段构造。world_id 缺省 = 主大陆。"""
        return cls(world_id or "mainland", map_id or "", subarea_id or "")

    # ---- 序列化 ----

    def key(self) -> str:
        """落库键：'mainland:goblin_camp:goblin_camp_1'"""
        return f"{self.world_id}:{self.map_id}:{self.subarea_id}"

    def to_db(self) -> tuple:
        """(cur_map, cur_subarea, world_id) —— 兼容 update_player 调用"""
        return self.map_id, self.subarea_id, self.world_id

    # ---- 判定 ----

    def is_instance(self) -> bool:
        """是否在副本大陆实例里。"""
        return self.world_id.startswith("inst:")

    def is_mainland(self) -> bool:
        """是否在主大陆。"""
        return self.world_id == "mainland"

    # ---- 解析 ----

    def resolve_map(self) -> Optional[dict]:
        """按世界解析地图 dict——唯一入口，替换全游戏 C.MAP_BY_ID.get(map_id)。

        主大陆 → 包内门面 `catalog_space.MAP_BY_ID`（收口后 `C.MAP_BY_ID` 即同一对象）；
        副本实例 → instance_worlds[world_id].maps。
        找不到返回 None（调用方自行兜底，与原 C.MAP_BY_ID.get 语义一致）。
        """
        if self.is_instance():
            inst = _get_instance_world(self.world_id)
            if inst is None:
                return None
            return inst.get("maps", {}).get(self.map_id)
        return _cs.MAP_BY_ID.get(self.map_id)

    def resolve_subareas(self) -> list:
        """当前地图的子区域列表（按世界解析）。"""
        if self.is_instance():
            inst = _get_instance_world(self.world_id)
            if inst is None:
                return []
            return inst.get("subareas", {}).get(self.map_id, [])
        return _cs.SUBAREAS.get(self.map_id, [])

    # ---- 复制 ----

    def with_map(self, map_id: str, subarea_id: str = "") -> "Position":
        """同世界换地图（用于移动落点）。"""
        return Position(self.world_id, map_id, subarea_id or self.subarea_id)

    def with_subarea(self, subarea_id: str) -> "Position":
        """同世界同地图换子区域。"""
        return Position(self.world_id, self.map_id, subarea_id)

    def as_mainland(self) -> "Position":
        """回到主大陆（位置字段保留，world_id 重置）。"""
        return Position("mainland", self.map_id, self.subarea_id)

    # ---- 展示 ----

    def __repr__(self):
        return f"<Position {self.world_id}:{self.map_id}:{self.subarea_id}>"


# ============================================================
# 适配层（v141 Phase 1：零行为变更）
# ------------------------------------------------------------
# 命令层新增代码统一走以下入口；旧代码不动（读到的还是主大陆结果，
# 因为默认 world=mainland）。热路径替换在 Phase 2 逐步进行。
# ============================================================


def cur_map_obj(player: dict) -> Optional[dict]:
    """按玩家位置解析当前地图 dict（唯一入口）。"""
    return Position.from_player(player).resolve_map()


def cur_subareas(player: dict) -> list:
    """当前地图的子区域列表（按世界解析）。"""
    return Position.from_player(player).resolve_subareas()


def player_position(player: dict) -> Position:
    """快捷：从玩家存档取 Position（适配层统一入口）。"""
    return Position.from_player(player)


def position_to_db(pos: Position) -> dict:
    """把 Position 转成 update_player 字段 dict（Phase 3 用）。"""
    return {
        "cur_map": pos.map_id,
        "cur_subarea": pos.subarea_id,
        "world_id": pos.world_id,
    }


__all__ = ["Position", "cur_map_obj", "cur_subareas", "player_position", "position_to_db",
           "bind_host"]
