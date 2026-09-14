# -*- coding: utf-8 -*-
"""包内聚合门面（`content/facade.py`）—— **取代宿主 `game/content.py` 的包内半边**。

为什么要有它
------------
宿主 `game/content.py` 是**薄聚合层**：`from .core import *` + 从包内 `catalog_*` 门面 `setdefault` 落名；
包内过去有一批模块（`cmds_social` / `persistence/*` / `profession` / `settlement` / `event_templates` …）
**通过宿主句柄 `C`**（`_HostMod("content")` / `from .handles import C`）读那些名字 ⇒ 包离不开宿主。
本模块把那只门面**搬进包内**，于是这些读点可以「包 → 包」。

取件时机（**行为的一部分，别改成 import 期**）
--------------------------------------------
旧写法 `_HostMod("content")` 在**属性访问时**才 `import game.content`（惰性）。本模块保持同一时机：
`C` 是惰性聚合句柄 —— 首次属性访问时才 import 各 `catalog_*` 并聚合。
理由见 `content/_pkgref.py` 的 docstring：`content/persistence/__init__.py` 在 EAGER 窗口里读
`C.MAP_BY_ID`（`schema.py:25`），改成 import 期解析会炸 `partially initialized module`。

聚合口径（与宿主门面**同序**）
------------------------------
宿主门面先落 `.core`（`pindex/index` 面），再按 `catalog_*` 逐个 `setdefault`（同名时先落者胜）。
本模块用同一顺序 + `setdefault`，故 `C.<名>` 的解析结果与旧门面**同一只对象**（探针实测口径见
`overnight/C_NAME_TO_PACKAGE_MAP.md`）。

注入扇出（`bind_host`）
-----------------------
`game.json` 的 `bind` 指向本模块的 `bind_host(**inject)`；引擎在 import 包命令模块**之前**调用它，
把「包运行期要用的宿主对象」一次分发到各模块既有注入槽。
**真·宿主能力只有四类**：库路径 / 时钟 / 日志与流水 sink / （发奖实现已在包内 `content/reward.py`）。
其余注入键（`_shop_svc` / `_ss` / `_craft_svc` / `_prof_svc` / `C` / `db` / `item_templates` / `texts` …）
**一律自解析到包内模块**。

★ 本文件是**主线预置的可用种子**（W2b 依赖它编解码；W2a 负责补全/复核并把 `game.json` 的 bind 接上）。
"""
from __future__ import annotations

import importlib

__all__ = ["C", "bind_host", "resolve_name", "AGGREGATE_MODULES"]

#: 聚合来源（顺序 = 宿主 `game/content.py` 的口径：先 `.core` 那一层，再 catalog_* 逐个 setdefault）
#: ★ 宿主门面的两个半边 —— ① `from .core import *`（= 包内 core 层模块）② `catalog_*` 门面。
#:   包内门面必须两半都有，否则 `C.check_achievements` / `C.generate_equip` / `C.rune_item` 这类
#:   **函数名**取不到（它们住在 core 层各模块里，不在 catalog_* 里）。
AGGREGATE_MODULES = (
    # ① core 层（顺序与宿主 `game/core/__init__.py` 的再导出面一致：先 index/tables 这类索引面）
    "content.index",
    "content.tables",
    "content.constants",
    "content.stats",
    "content.achievements",
    "content.drops",
    "content.runes",
    "content.factions",
    "content.pets",
    "content.mounts",
    "content.fishing",
    "content.time_weather",
    "content.craft",
    "content.loot",
    # ② catalog_* 门面（数据名）
    "content.catalog_legacy",
    "content.catalog_b143",
    "content.catalog_core",
    "content.catalog_items",
    "content.catalog_life",
    "content.catalog_quests",
    "content.catalog_rules",
    "content.catalog_space",
)

_NS = None


def _namespace() -> dict:
    """惰性构建聚合命名空间（首次访问时 import + setdefault；之后缓存）。"""
    global _NS
    if _NS is None:
        ns: dict = {}
        for mod_name in AGGREGATE_MODULES:
            mod = importlib.import_module(mod_name)
            # ★ 同一件事的第二实现：`dir()` 顺序不稳定 → 用模块 `__dict__` 的插入序
            #   （宿主门面用 `dir(_m)` + setdefault；两者在「同名谁胜」上等价：先落者胜）
            for name, value in vars(mod).items():
                if name.startswith("__"):
                    continue
                ns.setdefault(name, value)
        _NS = ns
    return _NS


class _Aggregate(object):
    """惰性聚合句柄：`C.<名>` 首次访问时解析（取件时机 = 旧 `_HostMod("content")`）。"""

    __slots__ = ()

    def __getattr__(self, attr):
        try:
            return _namespace()[attr]
        except KeyError:
            raise AttributeError(
                "content.facade.C：包内聚合门面里没有 `%s`（宿主门面有而包内没有？"
                "请查 overnight/C_NAME_TO_PACKAGE_MAP.md 并登记缺口，别静默兜底）" % (attr,))

    def __dir__(self):
        return sorted(_namespace())

    def __repr__(self):
        return "<content.facade.C 聚合句柄（%d 名）>" % len(_namespace())


C = _Aggregate()


def resolve_name(name: str):
    """按名取件（给需要动态取名的调用点用；取不到 → KeyError，**不静默**）。"""
    return _namespace()[name]


# ============================================================
# 注入扇出
# ============================================================
#: 包内自解析键 → 包内模块（宿主**不用**给这几个）
SELF_KEYS = {
    "_shop_svc": "content.shop",
    "_sshop": "content.shop",
    "_ss": "content.smith_stock",
    "_craft_svc": "content.craft",
    "_prof_svc": "content.profession",
    "item_templates": "content.item_templates",
    "texts": "content.texts",
    "db": "content.persistence",
    "data": "content.catalog_legacy",
    "content": None,          # None = 用聚合句柄 C
    "C": None,
    "tlog_setup": "content.obs",
    "log": "content.obs",
}

_BOUND = False


def bind_host(**inject):
    """**包侧唯一注入扇出**（幂等）。

    `inject` 由宿主给（引擎在 import 包命令模块之前调用本函数）：
      · 真·宿主能力：`db_path` / `clock` / `flush_log` / `log` / `tlog`（键名按宿主注入面）
      · 其余键一律按 `SELF_KEYS` **自解析到包内模块**（宿主不必知道这些名字）
    """
    global _BOUND
    # ① 存档层注入面（库路径 / 时钟 / 日志 sink）
    try:
        from .persistence import handles
        handles.bind(db_path=inject.get("db_path"), clock=inject.get("clock"),
                     flush_log=inject.get("flush_log"))
    except Exception:                                  # noqa: BLE001  纯包场景：无 deploy 句柄
        pass
    # ② 观测口（日志 / 流水 sink）—— 包内唯一取用口
    try:
        from . import obs
        obs.bind(log=inject.get("log"), tlog=inject.get("tlog"))
    except Exception:                                  # noqa: BLE001
        pass
    # ③ 自解析键 + 真·宿主键 → 分发给所有认这些键的模块
    payload = {}
    for key, mod_name in SELF_KEYS.items():
        payload[key] = C if mod_name is None else _lazy(mod_name)
    for key in ("db_path", "clock", "flush_log", "log", "tlog", "grant_reward", "reward"):
        if key in inject:
            payload[key] = inject[key]
    _fanout(payload)
    _BOUND = True
    return payload


def _lazy(mod_name: str):
    """惰性包内模块句柄（与 `content/_pkgref.PkgModule` 同形，零依赖）。"""
    class _M(object):
        __slots__ = ()

        def __getattr__(self, attr):
            return getattr(importlib.import_module(mod_name), attr)

        def __repr__(self):
            return "<facade.lazy %s>" % mod_name
    return _M()


def _fanout(payload: dict):
    """把 payload 喂给包内所有 `bind_host(**kw)`（认不出的键由被调方自己忽略/报错）。"""
    import pkgutil
    import content as _c
    for mi in pkgutil.walk_packages(_c.__path__, "content."):
        try:
            mod = importlib.import_module(mi.name)
        except Exception:                              # noqa: BLE001  import 期还需注入的模块跳过
            continue
        fn = getattr(mod, "bind_host", None)
        if not callable(fn):
            continue
        try:
            fn(**payload)
        except TypeError:
            continue                                   # 形参不匹配的模块自己忽略
        except Exception:                              # noqa: BLE001
            continue
