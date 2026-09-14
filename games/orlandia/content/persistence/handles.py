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
`C` / `_host_attr` / `_host_attrs` 沿用包内既有「宿主替身口」写法（`content/auction.py` 起）。
"""
from __future__ import annotations

import importlib
import sys
import time as _time

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
    """宿主模块替身（`C`）——`C.xxx` 正文一字未改，属性访问时解析。"""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return getattr(_host_module(self._name), attr)


C = _HostMod("content")     # 真源 模块级 `from .. import content as C`
