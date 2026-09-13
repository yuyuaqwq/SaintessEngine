# -*- coding: utf-8 -*-
"""包内位置结构体（`content/position.py`）—— 游戏仓 `game/core/position.py`（140 行）**逐字端口**（B13-L7）。

正文一字未改，只换「宿主取件」（三处，全部**函数内**解析，与真源同位置）：
| 真源取件 | 包内替身 |
|---|---|
| `from ..data import MAP_BY_ID` | 宿主 `data` 句柄 |
| `from ..data import SUBAREAS` | 宿主 `data` 句柄 |
| `from .worlds import get_instance_world` | 宿主 `core.worlds` 句柄（**别线在搬** → 见缺口） |

为什么这两张表没切包内域（**实测依据，不是偷懒**）
--------------------------------------------------
1. `MAP_BY_ID`：`editor/domains.json` **无同名域**；它是 `MAPS` 的派生索引
   （`_assembly.py:145-146` 用 MAPS 重建），且值 = MAPS 条目**含装配期注入的 `subareas` 键**
   （`_assembly.py:137`）。宿主 15+ 处消费点读 `C.MAP_BY_ID.get(...).get("subareas")`
   （base.py / instance.py / item_templates.py …），而包内 `worlds` 域**有意剔除** `subareas`
   （导出插件文件头：那是装配期注入的嵌套列表，与 subareas 域同批对象）→ 换源 = 静默丢键。
2. `SUBAREAS`：同名 `subareas` 域存在且**内容等价**（B13-L7 对拍：628 条逐字段 0 差异、
   逐图列表序相同）。但本模块的返回语义是「返回宿主那份子区域列表/条目」—— 包内域是
   **扁平 + 注入 `map`** 的投影，重建后是**新 dict**（不是宿主行对象身份）。同一份判断在
   `content/maps.py` 里已按「域重建 = 内容等价」切过（那里只读 id/name/type/hidden/reveal，
   不向外抛行对象）；本模块把行对象**抛给调用方**，行对象身份/后续就地改写的语义无法保证 →
   本线按「不确定 → 宿主句柄 + 缺口登记」处理，切点留给 B14（统一裁）。

缺口登记
--------
* `MAP_BY_ID` / `SUBAREAS` 两处读点 = 宿主句柄 → 待 B14（要么给 `maps`/`worlds` 域补 MAPS 序与
  `subareas` 注入语义，要么让消费端改读 `maps`/`subareas` 域拼装）。
* `get_instance_world`（副本大陆实例）= 宿主句柄 → **待 B13-L2（`core/worlds.py` 那条线）落地后**
  切包内直取（本线不许直接 import 别线在搬的模块：会瞬时 ImportError）。
"""
from __future__ import annotations

import importlib
import sys
from typing import Optional

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
    """真源 `from .worlds import get_instance_world`（函数内惰性 import）→ 宿主句柄。"""
    return getattr(_host_module("core.worlds"), "get_instance_world")(world_id)


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

        主大陆 → 宿主 `MAP_BY_ID`；副本实例 → instance_worlds[world_id].maps。
        找不到返回 None（调用方自行兜底，与原 C.MAP_BY_ID.get 语义一致）。
        """
        if self.is_instance():
            inst = _get_instance_world(self.world_id)
            if inst is None:
                return None
            return inst.get("maps", {}).get(self.map_id)
        return _host_module("data").MAP_BY_ID.get(self.map_id)

    def resolve_subareas(self) -> list:
        """当前地图的子区域列表（按世界解析）。"""
        if self.is_instance():
            inst = _get_instance_world(self.world_id)
            if inst is None:
                return []
            return inst.get("subareas", {}).get(self.map_id, [])
        return _host_module("data").SUBAREAS.get(self.map_id, [])

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
