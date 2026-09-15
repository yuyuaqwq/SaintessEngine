# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— 存档层**注入面**（B17，2026-09-14）。

「宿主零逻辑」的落点：包内 `content/persistence/*` 只吃**注入句柄**，绝不 import 宿主模块；
宿主只负责「连接怎么来」—— 四个注入点：

| 句柄 | 谁给 | 包内怎么用 | 默认 |
|---|---|---|---|
| `db_path` | 宿主工厂（env `GWEN_GAME_DB` / 插件目录 `game_data.db`） | 建引擎 `Database(db_path, timeout=10)` | 无（未注入即抛，**拒绝静默空跑**） |
| `clock` | 宿主工厂（`time.time`） | 旧 `time.time()` 调用点全改 `clock()` | `time.time` |
| `flush_log` | 宿主工厂（日志 sink；默认静默） | 装配诊断（`schema.install`）单点 | no-op |
| `lock` | 引擎 `Database.lock`（RLock，可重入） | `_lock`（代理，`with _lock:` 逐语义等价） | 注入值 → 否则 Database 的 RLock |

注入方式 = 模块级 `bind(**handles)`（与包内既有 `bind_host` 约定同形，不另发明第三套）。
`_host_attr` / `_host_attrs` / `_HostMod` 沿用包内既有「宿主替身口」写法（`content/auction.py` 起）。

★ W2a 改指（2026-09-15）：`C` 与 `_host_content()` 不再指向**宿主** `game.content`，
改指**包内聚合门面** `content/facade.py::C`（`from ..facade import C`）。
等价性 = 探针逐名对象同一性（71 名 / 298 处，`out/probe/c_facade_identity.log` BAD=0）
+ 取件时机不变（两侧都是属性访问时解析）。`_host_module` / `_host_attr` / `_host_attrs` /
`_HostMod` **保留**（`cmds_gm` / `persistence/players` / `persistence/battle_state` 仍在用）。
"""
from __future__ import annotations

import importlib
import sys
import time as _time

# ★ W2a 改指：包内内容聚合门面（原 `C = _HostMod("content")` → 宿主 `game.content`）。
#   `content.facade` 零 import 依赖（只 import importlib）⇒ 放在 import 期不会把 EAGER 窗口
#   拖进半初始化；`C.<名>` 的取件时机仍是**属性访问时**（facade.C 是惰性句柄），逐字同旧。
from ..facade import C  # noqa: F401

_DEFAULT_TIMEOUT = 10.0
_H = {"db_path": None, "clock": None, "flush_log": None, "lock": None, "db": None}


def bind(db_path=None, clock=None, flush_log=None, lock=None, db=None):
    """注入句柄（幂等；`None` = 不改）。返回本模块便于链式调用。"""
    for k, v in (("db_path", db_path), ("clock", clock), ("flush_log", flush_log),
                 ("lock", lock), ("db", db)):
        if v is not None:
            _H[k] = v
    return _H


def db_path():
    """库路径句柄（必须由宿主注入 —— 包不知道部署在哪）。"""
    p = _H["db_path"]
    if not p:
        raise RuntimeError("content.persistence：db_path 句柄未注入（宿主工厂 store_factory 负责注入）")
    return p


def clock():
    """时钟句柄 —— **当前时间戳**（`bind(clock=<零参可调用>)`；默认 stdlib `time.time`）。"""
    return (_H["clock"] or _time.time)()


def flush_log(msg):
    """日志 sink 句柄（默认静默 = 行为与改造前零差异）。"""
    fn = _H["flush_log"]
    if fn is not None:
        fn(msg)


def get_db():
    """引擎连接骨架（`saintess_engine.store.Database`）—— 按注入路径**惰性**建一次。"""
    db = _H["db"]
    if db is None:
        from saintess_engine.store import Database
        from . import schema
        db = Database(db_path(), timeout=_DEFAULT_TIMEOUT)
        schema.install(db)
        _H["db"] = db
    return db


def set_db(db):
    """测试/工具替换连接骨架（重置缓存；不注册 schema）。"""
    _H["db"] = db
    return db


def lock():
    """进程内单锁句柄（引擎 `Database.lock` = RLock；可被 `bind(lock=…)` 覆盖）。"""
    return _H["lock"] or get_db().lock


def connect():
    return get_db().connect()


def atomic():
    return get_db().atomic()


def init_db():
    return get_db().init()


class _LockProxy:
    """`_lock` 句柄代理：`with _lock:` / `acquire` / `release` 逐语义委托给真锁。"""

    def __enter__(self):
        return lock().__enter__()

    def __exit__(self, *exc):
        return lock().__exit__(*exc)

    def acquire(self, *a, **k):
        return lock().acquire(*a, **k)

    def release(self):
        return lock().release()

    def __getattr__(self, item):
        return getattr(lock(), item)


_lock = _LockProxy()
_connect = connect


# ============================================================
# 宿主替身口（与包内既有约定同形：注入优先 → sys.modules → importlib；绝不静默空跑）
# ============================================================
_HOST_PKG = "data.plugins.dragonfall.game"
_HOST_PKG_FALLBACK = "game"
_INJECTED = {}


def bind_host(**objs):
    """宿主薄壳 import 期注入（幂等）——键 = `_HostMod` 的模块名（`content` / `db`）。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _host_module(name: str):
    if name in _INJECTED:
        return _INJECTED[name]
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        full = prefix if not name else "%s.%s" % (prefix, name)
        m = sys.modules.get(full)
        if m is not None:
            return m
    last = None
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        try:
            return importlib.import_module(prefix if not name else "%s.%s" % (prefix, name))
        except Exception as exc:                    # noqa: BLE001
            last = exc
    raise RuntimeError("%s：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (__name__, name, last))


def _host_content():
    """内容聚合面句柄 —— **包内聚合门面** `content/facade.py::C`（★ W2a 改指，2026-09-15）。

    改前：返回**宿主** `game.content` 模块本体（注入槽 → `sys.modules` → importlib → 抛）。
    改后：返回**包内**聚合门面句柄（同一个 `C`，属性访问时解析；facade 模块零 import 依赖）。

    为什么能改（等价性证据，不是推测）
    ----------------------------------
    门面的聚合口径 = 宿主 `game/content.py`（`from .core import *` + `catalog_*` 逐名
    `setdefault`）。探针实测：包内全部 `C.<名>` 读点（71 个名 / 298 处）取到的对象与宿主
    `game.content.<名>` **逐名同一只**（`out/probe/c_facade_identity.log`，BAD=0）。
    取件时机也一致：旧 `_HostMod("content")` 与门面 `C` 都是**属性访问时**才解析，
    故 EAGER 窗口（`content/persistence/__init__.py` → `schema.py:25` 读 `C.MAP_BY_ID`）行为不变。

    为什么住这里（B2-INTFIX 落点裁定，完整理由见 `out/W-INTFIX.md` §1）
    ------------------------------------------------------------------
      · 本模块就是包内既有的**宿主面解析区**（`_host_module` / `_host_attr` / `_host_attrs` /
        `_HostMod` 全在这），4 个消费者的调用写法已按「函数体内惰性 import」定死；
      · 本批只换**返回对象**，函数名 / 签名 / 调用点一字不改（W2b 才改消费者读点）。

    ⚠️ 调用点必须**惰性 import**（函数体内 `from .persistence.handles import _host_content`）：
    本模块经 `content/persistence/__init__.py`（EAGER 窗口）暴露，在 `game/core/__init__`
    装配链上不能 import 期取。

    缺口登记（两侧一致，不是本批引入）：门面**不含** `STAT_NAMES` —— 宿主 `game.content` 同样
    没有它（它住 `game/content_rules/panel.py`，不在 core 聚合面），故 `getattr(C, "STAT_NAMES",
    None)` 两侧同为 `None`。
    """
    from ..facade import C as _facade_C
    return _facade_C


def _host_attr(mod: str, attr: str):
    """宿主模块属性 —— 真源「函数内 `from ..<mod> import <attr>`」的同义替身（调用时解析）。"""
    m = _host_module(mod)
    try:
        return getattr(m, attr)
    except AttributeError:
        for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
            try:
                return importlib.import_module("%s.%s" % (
                    prefix if not mod else "%s.%s" % (prefix, mod), attr))
            except Exception:                       # noqa: BLE001
                continue
        raise


def _host_attrs(mod: str, *attrs):
    """多符号版 `_host_attr` —— 真源「`from ..<mod> import a, b, c`」的同位置一行替身。"""
    return tuple(_host_attr(mod, a) for a in attrs)


class _HostMod:
    """宿主模块替身 ——`X.xxx` 正文一字未改，属性访问时解析。

    ★ W2a 起 `C` **不再**用本类（改指包内门面 `content/facade.py::C`）；本类保留是因为
    `content/cmds_gm.py` 仍 `from .persistence.handles import _HostMod`，且它是包内其他
    宿主面替身（如各模块自带的 `_HostMod("db")`）的同形样板。
    """

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return getattr(_host_module(self._name), attr)


#: 包内内容聚合门面句柄（真源 模块级 `from .. import content as C`）——见文件头「W2a 改指」。
#: `C` 已在本文件 import 期从 `..facade` 绑定（见顶部 import 注释）。
