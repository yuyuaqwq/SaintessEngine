# -*- coding: utf-8 -*-
"""B1 切读点：**包内**惰性模块句柄（`content/_pkgref.py`）。

为什么要它（实测，不是推测）
--------------------------
B1 要把「包 → 宿主薄壳 → 包」拍平成「包 → 包」。但**取件时机本身是行为的一部分**：
旧写法 `db = _HostMod("db")` 是**属性访问时**才解析（才 import `game.db`），
而 `from . import persistence as db` 是 **import 期**解析。二者不等价 —— 实测直接炸：

    import game.content
      → game/core/__init__.py:61      from . import smith_stock
      → content/smith_stock.py        from . import persistence as db          ← EAGER
      → content/persistence/__init__.py:11  from .schema import C_MAP_IDS
      → content/persistence/schema.py:30    C_MAP_IDS = _map_ids()
      → content/persistence/schema.py:25    set(C.MAP_BY_ID.keys())            ← C = 宿主 game.content
      → AttributeError: partially initialized module
                        'data.plugins.dragonfall.game.content' has no attribute 'MAP_BY_ID'

根因：`content/persistence/__init__.py` 在 import 期要读宿主 `game.content`
（`C_MAP_IDS = _map_ids()`），所以它是 EAGER 装配窗口里的**危险目标**；凡在窗口内
被 import 的包内文件（`game/core/__init__.py` 那条链上的）都**只能惰性**取它。

本模块把「惰性取包内模块」做成零依赖小对象，取件时机与旧 `_HostMod` **逐字相同**
（每次属性访问解析一次）⇒ 行为面不变，同时不再往返宿主。本模块自身零 import 依赖，
可以安全地出现在任何 EAGER 窗口里。
"""
from __future__ import annotations

import importlib
import sys

#: 宿主存档层**部署适配件**（唯一装配点：读 `GWEN_GAME_DB`/插件目录 → `handles.bind(db_path=…)`）。
#: 不在本批 35 个纯薄壳里；包内文档明写「库路径是部署信息，由宿主 store_factory 注入」。
#:
#: ★ REPOINT-PKG（2026-09-15，B4R B 组第 5/6 项）口径裁定 —— **「宿主薄壳已删」对本项不适用**：
#:   `game/store/store_factory.py`（37 行）**不是薄壳**，是宿主对包内 `content.persistence` 的
#:   **唯一装配点**（零 SQL / 零业务分支，只算 `DB_PATH = $GWEN_GAME_DB | <插件目录>/game_data.db`
#:   并 `handles.bind(db_path=…, clock=…, flush_log=…)`）。库路径是**部署信息**，包内算不出
#:   （包侧 `__file__` 在框架仓，默认路径会变成另一个文件），故**不可包内化**。
#:   实测证据：把本块改成不 import 宿主 → 只 `import game.content` 的入口拿不到 db_path 注入
#:   → `handles.db_path()` 抛 → 数值门禁红 1/18（原因写在 `_warm_host_store` docstring）。
#:   ⇒ B 组第 5 项（`game.store`）：包内真正的 code 级消费者只有 `store.social` 取件两处，
#:     本批已改包内直取（`content/social_guild.py` / `content/social_stall.py`）；
#:     第 6 项（`game.store.store_factory`）**归宿主侧线**（部署适配件迁移/改名时同步本元组）。
#:   ★ 本条 import 是**已加载优先**（在册即返回）⇒ 宿主侧删壳后此处自动静默降级，不炸。
_HOST_FACTORY = (
    "data.plugins.dragonfall.game.store.store_factory",
    "game.store.store_factory",
)
_warmed = False


def _warm_host_store():
    """**一次性**确保宿主工厂已把 `db_path` 句柄注入 `content/persistence/handles`。

    为什么必须有这一步（实测，不是推测）
    ----------------------------------
    旧写法 `db = _HostMod("db")` 在**首次属性访问**时 `import game.db` → `game.store`
    → `store_factory`，顺带完成注入；只 `import game.content` 的入口
    （`tests/test_numeric_drop_unify.py`）也靠这个副作用拿到库路径。惰性包内句柄不再触发它
    → `handles.db_path()` 抛「句柄未注入」→ 实测 numeric 门禁红 1/18。
    本步把这条**本来就存在**的依赖从「隐式」变「显式」：仅当宿主工厂尚未在 `sys.modules`
    时才 import 一次（已在册 → 直接返回，绝不覆盖宿主已注入/已重绑的句柄）。
    纯包场景（无宿主）import 失败 → 静默返回，交给 `db_path()` 自己按原样抛。
    """
    global _warmed
    if _warmed:
        return
    _warmed = True
    for name in _HOST_FACTORY:
        if name in sys.modules:
            return
    for name in _HOST_FACTORY:
        try:
            importlib.import_module(name)
            return
        except Exception:                       # noqa: BLE001  纯包场景：无宿主可注入
            continue


class PkgModule(object):
    """包内模块句柄：`X.attr` 时 import 目标包内模块再取属性（= 旧 `_HostMod(name)` 的包内版）。"""

    __slots__ = ("_name", "_warm")

    def __init__(self, name, warm=None):
        self._name = name
        self._warm = warm

    def __getattr__(self, attr):
        if self._warm is not None:
            self._warm()
        return getattr(importlib.import_module(self._name), attr)

    def __repr__(self):
        return "<PkgModule %s>" % (self._name)


#: 包内 `db` 句柄（旧 `_HostMod("db")` / `_host_module("db")` 的包内等价物）
DB = PkgModule("content.persistence", warm=_warm_host_store)
#: 存档层注入面（旧 `_host_attr("store.connection", …)`）
HANDLES = PkgModule("content.persistence.handles")
#: 存档层 world 域（旧 `_host_attr("store.world", …)`）
WORLD = PkgModule("content.persistence.world")
#: 存档层 inventory 域（旧 `_host_attr("store.inventory", …)`）
INVENTORY = PkgModule("content.persistence.inventory")
#: 存档层 social 域（旧 `_host_attr("store.social", …)`）
SOCIAL = PkgModule("content.persistence.social")
