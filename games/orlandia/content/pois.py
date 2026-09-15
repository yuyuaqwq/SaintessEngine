# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— pois 核心域实现（B13-L5，2026-09-14）。

真源 = 宿主 `game/core/pois.py`（原 55 行）**逐字搬**：函数体一字未改，只换「宿主取件」：

| 真源写法 | 包内 | 依据 |
|---|---|---|
| `from ..data.pois import SUBAREA_POIS` | 包内域读口 `pois`（`content/data/pois.json`） | 域 = 「房间地址 → 挂载 POI 引用」457 行；对拍逐键相等（含行内引用序），`overnight/w1213_l5_probe.py` P5 |
| `from ..data.pois import POIS`（函数内） | ★ **已切包内门面**（W12 收口 2026-09-14）`from .catalog_b143 import POIS` —— POI 类型定义表（83 条）= `rules/game_config.json` 的 `pois` 组（真源 `game/data/pois.py:9`）；`b14_catalog_gate.py --names POIS` → OK |
| `from ..data.props import SUBAREA_PROPS`（函数内） | ★ **已切包内门面**（B16-W11b 收口 2026-09-14）`from .catalog_rules import SUBAREA_PROPS` —— `props` 域是**反投影**（每条 prop 列自己的 `mounts`），同一地点多 prop 的**行内序不复原**（实测 `oak_town:oak_town_4` 键序不同）⇒ 门面按真源原序 dump（315 条，逐键/逐序对拍相等；登记 `NOT_YET_DOMAINED`） |

域行形状与归一
--------------
`pois.json` 里 base/mesh 行是**类型引用串**、dungeon 行是**自带定义的 dict**（导出器刻意
不归一，两种语义不同）→ 本模块按宿主运行期真形（`game/data/_assembly.py` 装配后行里只剩 id）
把 dict 归一成 `x["id"]`，取数形态与真源运行时 `SUBAREA_POIS` 全等（对拍 P5 已证）。

⚠️ 与真源唯一可观察差异：`subarea_pois` 返回**每次新建的 list**（域读口按需构造），真源返回
`SUBAREA_POIS` 里那份**存储列表本体** —— 消费端（`commands/instance.py` 三处、
`tests/test_v104_explore_map.py`）只读不写，值与序逐项相同。

宿主侧：`game/core/pois.py` 现在只剩「加载包 + 模块别名」薄壳，见那边头注。
"""
import importlib
import json
import os
import random
import sys

# ============================================================
# ① 宿主替身口（注入优先 → sys.modules → importlib；**绝不静默空跑**）
#    抄 `content/world_cmds.py` 的同款写法（B9 线2 定的包内标准形状）
# ============================================================
_HOST_PKG = "data.plugins.dragonfall.game"      # 运行时（main.py 的模块路径）
_HOST_PKG_FALLBACK = "game"                     # 测试/工具按 `game.xxx` 直接 import 时
_INJECTED = {}
_MOD = "pois"


def bind_host(**objs):
    """宿主薄壳 import 期注入（幂等）——键 = `_HostMod` 的模块名。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _host_module(name: str):
    """取宿主子模块（`name` 为空 = 宿主 `game` 包本身）。"""
    if name in _INJECTED:
        return _INJECTED[name]
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        m = sys.modules.get(prefix if not name else "%s.%s" % (prefix, name))
        if m is not None:
            return m
    last = None
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        try:
            return importlib.import_module(prefix if not name else "%s.%s" % (prefix, name))
        except Exception as exc:                # noqa: BLE001
            last = exc
    raise RuntimeError("%s：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (_MOD, name, last))


def _host_attr(mod: str, attr: str):
    """宿主模块属性 —— 真源「函数内 `from ..<mod> import <attr>`」的同义替身（调用时解析）。"""
    m = _host_module(mod)
    try:
        return getattr(m, attr)
    except AttributeError:
        for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
            try:
                return importlib.import_module(
                    "%s.%s" % (prefix if not mod else "%s.%s" % (prefix, mod), attr))
            except Exception:                   # noqa: BLE001
                continue
        raise


# ============================================================
# ② 包内域读口 —— POI 挂载表（域 `pois`；真源 = 运行期 `SUBAREA_POIS` 457 行，
#    导出器 = 游戏仓 `scripts/export_game_package.py:derive_pois`）
# ============================================================
_HERE = os.path.dirname(os.path.abspath(__file__))


def _read_domain(domain: str, sub: str = "data", default=None):
    """读包内 `content/<sub>/<domain>.json`（缺文件/坏 JSON → default，不抛，与 tables.py 同款）。"""
    try:
        with open(os.path.join(_HERE, sub, "%s.json" % domain), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                            # noqa: BLE001
        return {} if default is None else default


_POI_ROWS: dict = _read_domain("pois")          # 房间地址 → {map, subarea, pois: [...], source}

# 房间地址 → 挂载的 poi id 列表（dungeon 行的自带定义 dict → 只留 id，与宿主装配后同形）
_MOUNTED: dict = {}
for _k, _row in _POI_ROWS.items():
    _MOUNTED[_k] = [(_x["id"] if isinstance(_x, dict) else _x) for _x in (_row.get("pois") or [])]


def subarea_pois(map_id: str, subarea_id: str) -> list:
    """返回指定子区域挂载的 POI id 列表(无则空)。

    注（v141 审计 2026-08-30）：大陆克隆 subareas 当前无命令层消费，
    保留待动态化——副本内 POI 查询走 instance.py 直读数据表（_map_scene/_enter_stage
    经 C.subarea_pois 以克隆图 id 查询全局 SUBAREA_POIS，非克隆 subareas 字段）。
    """
    key = f"{map_id}:{subarea_id}"
    return list(_MOUNTED.get(key, []))


def subarea_props(map_id: str, subarea_id: str) -> list:
    """返回指定子区域挂载的场景元素 PROPS 列表（无则空）。

    元素为 prop id 字符串，或 (prop_id, 专属名) 元组——元组表示该处
    使用专属名显示/交互（同一 prop 在不同子区域可有不同名字）。
    """
    from .catalog_rules import SUBAREA_PROPS   # ★ B16-W11b：包内门面（props 域是反投影、行内序不可逆）
    key = f"{map_id}:{subarea_id}"
    return SUBAREA_PROPS.get(key, [])


def prop_entry(entry):
    """PROPS 挂载条目 → (prop_id, display_name 或 None)。

    支持 str（用默认名）或 (prop_id, 专属名) 元组（v87.11 专属命名）。
    """
    if isinstance(entry, (tuple, list)) and len(entry) >= 2:
        return entry[0], entry[1]
    return entry, None


def roll_poi(group_id: str, qq_id: str, map_id: str, subarea_id: str, chance: float = 0.15):
    """探索时独立判定：chance 概率触发当前子区域随机 POI。

    返回 (poi_id, poi_dict) 或 None。
    """
    ids = subarea_pois(map_id, subarea_id)
    if not ids:
        return None
    if random.random() >= chance:
        return None
    poi_id = random.choice(ids)
    from .catalog_b143 import POIS   # ★ W12 收口：真源 `from ..data.pois import POIS`（函数内）
    return poi_id, POIS.get(poi_id, {})
