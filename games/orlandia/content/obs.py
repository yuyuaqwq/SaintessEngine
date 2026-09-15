# -*- coding: utf-8 -*-
"""包内观测口 —— 包内拿 **LOG（文本日志）/ tlog（结构化流水）** 的**唯一取用口**。

★ 本文件 = B2-波0 冻结的注入契约（接口表见 `overnight/B2_W0_INTERFACE.md`）。
   本模块**不 import 宿主**（方向只有 内容 → 引擎/标准库），也不 import 包内其它模块 ——
   它只持有「注入进来的句柄」。落地时整文件 `cp` 到 `<pkg>/content/obs.py`，**不改任何现有包内文件**。

契约来源（逐条按**引擎真实代码**，不是设计稿；波0 实测见 `out/W-B2W0.md` §2）
--------------------------------------------------------------------------------
1. 引擎**没有** LOG 注入面：`saintess_engine/host/env.py:16-51` 的 `Env` 字段表里没有日志字段；
   引擎日志只有中性门面 `saintess_engine.log.get_logger(name, prefix=…)`
   （`saintess_engine/log/facade.py:72`，命名前缀**由调用方给**，不配置 = 标准库薄封装）。
   平台日志名 `"astrbot"` 硬编码在宿主 `game/log_setup.py:20-23`（`HOST_LOGGER` / `LOG`）
   ⇒ 包内不许硬编码平台名（`b2_impact.md` U5）⇒ **只能拿注入句柄**。
2. 引擎有 `Env.tlog`（`host/env.py:47` + `env.now_tlog` `:86-92`），但它接的是**适配器
   `on_tlog` 钩子**（`host/runtime.py:155-163` 与 `:217` 的 `tlog=self.tlog_write`），
   钩子不给 = 丢弃（`host/runtime.py:44` `"on_tlog": "丢弃（流水不落库）"`）。
   真源宿主**没有**实现该钩子（`grep -n on_tlog game/**/*.py` = 0 命中）⇒
   对游戏流水而言 `Env.tlog` 是「丢弃」；游戏流水的真源与出口是宿主 `game/tlog_setup.py`。
   `content/tlog_collect.py` 是**另一个东西**（战斗流水采集器 `BattleTLog`，靠引擎观察者通道），
   不提供 `kinds/enable/disable/enabled/tlog/emit` 控制面。
3. 流水「默认关」是宿主白纸黑字的契约：`game/tlog_setup.py:91-104`（`enabled()` / `tlog()` →
   None）+ `:107-124`（`emit()` 未启用直接返回 None，异常也不影响主流程）。

唯一路径 / 注入方 / 时机
------------------------
    包内一切 LOG / tlog 取用 → `content/obs.py`
    唯一注入口 = 本模块 `bind(log=…, tlog=…, host_pkg=…)`
    注入方  = 宿主壳（`game/**`，B2 波2 一次性改口）在 **import 期**调用，与既有
              `bind_host(...)` 同刻同形（实例：`game/reward.py:91` / `game/services/profession.py:57`
              / `game/services/player_event_bus.py:32` / `game/commands/talk_actions.py:42`）。
    测试里怎么给 = 直接 `obs.bind(log=<假 logger>, tlog=<假模块>)`（见 `tests/test_obs.py`）。

解析顺序（三级，**绝不 import 宿主**）
--------------------------------------
    ① `bind(...)` 注入的句柄
    ② `sys.modules` 里**已加载**的宿主模块（`data.plugins.dragonfall.game.log_setup` /
       `game.log_setup`，tlog 同理）—— 过渡期兜底（B2 波1 改读点时宿主侧**一个字节不动**，
       真源宿主必然已加载该模块），与既有包内替身 `_host_module()` 的 sys.modules 口径一致
       （`content/reward.py:66-78` / `content/talk_actions.py:92-99`）。
    ③ fail-closed：抛 `RuntimeError`（**不静默降级**）。

fail-closed 语义（逐条，别搞混「装配缺陷」与「未启用」）
--------------------------------------------------------
    log()      ①/② 都取不到 → **抛 RuntimeError**。**不退回 stdlib logger / 不返回 None**：
               改个名字的 logger 是第二棵日志树 = 静默降级（同 `content/reward.py:78` 原文
               「拒绝静默空跑」）。
    emit()     句柄取不到 → **抛 RuntimeError**（宿主没接上 = 装配缺陷）；
               句柄在、`tlog()` 返 None → **返回 None（零行为）**——这是契约（来源 3），
               不是降级；`emit` 内部异常照宿主口径吞掉（`game/tlog_setup.py:121-124`）。
    enabled()  句柄取不到 → 抛；句柄在 → 转发宿主判定。
"""
from __future__ import annotations

import sys
from typing import Any, Optional

__all__ = ["bind", "unbind", "log", "tlog", "enabled", "emit", "HOST_LOGGER_ATTR"]

#: 宿主 logger 的模块级属性名（`game/log_setup.py:23 LOG`）
HOST_LOGGER_ATTR = "LOG"

#: 宿主模块在 sys.modules 里的两个候选全名（与既有包内替身同口径：
#: `content/reward.py:44-45` / `content/talk_actions.py:75-76`：运行时包路径 + 测试路径）
HOST_PKG = "data.plugins.dragonfall.game"
HOST_PKG_FALLBACK = "game"

#: 注入句柄（`bind()` 写；`None` = 未注入）
_LOG: Any = None
_TLOG: Any = None
_HOST_PKG: Optional[str] = None


def bind(log: Any = None, tlog: Any = None, host_pkg: Optional[str] = None) -> None:
    """注入唯一口（幂等；`None` 忽略，不覆盖已注入值）。

    log     : 文本日志门面（宿主 `game/log_setup.LOG`，或任何有 `.warning/.info/...` 的对象）
    tlog    : 流水句柄 —— 宿主 `game/tlog_setup` **模块**（推荐，控制面全给：`emit/enabled/tlog`）
              或任何有 `.emit(kind, actor=…, **fields)` 的对象
    host_pkg: 覆盖 sys.modules 兜底的宿主包名（缺省见 `HOST_PKG`；测试/换包时可给）
    """
    global _LOG, _TLOG, _HOST_PKG
    if log is not None:
        _LOG = log
    if tlog is not None:
        _TLOG = tlog
    if host_pkg:
        _HOST_PKG = str(host_pkg)


def unbind() -> None:
    """清空注入（**只给测试/诊断**；运行期没人该调它）。"""
    global _LOG, _TLOG, _HOST_PKG
    _LOG = None
    _TLOG = None
    _HOST_PKG = None


def _loaded_host_module(name: str):
    """取**已加载**的宿主子模块（只查 `sys.modules`，**绝不 import 宿主模块树**）。"""
    pkgs = (HOST_PKG if _HOST_PKG is None else _HOST_PKG, HOST_PKG_FALLBACK)
    for prefix in pkgs:
        mod = sys.modules.get("%s.%s" % (prefix, name))
        if mod is not None:
            return mod
    return None


def _fail(what: str, name: str):
    raise RuntimeError(
        "content.obs：%s 取不到（未 bind() 且宿主模块 %s 未加载）—— 拒绝静默空跑" % (what, name))


def log():
    """取文本日志门面（唯一路径；取不到 → 抛，**不退回 stdlib logger**）。"""
    if _LOG is not None:
        return _LOG
    mod = _loaded_host_module("log_setup")
    handle = getattr(mod, HOST_LOGGER_ATTR, None) if mod is not None else None
    if handle is None:
        _fail("LOG", "log_setup")
    return handle


def tlog():
    """取流水实例（唯一路径）。

    返回 `None` = **宿主契约里的「未启用」**（`game/tlog_setup.py:98-104`），零行为；
    **句柄本身取不到**（装配缺陷）→ 抛。
    """
    if _TLOG is not None:
        getter = getattr(_TLOG, "tlog", None)
        return getter() if callable(getter) else _TLOG
    mod = _loaded_host_module("tlog_setup")
    if mod is None:
        _fail("tlog 句柄", "tlog_setup")
    getter = getattr(mod, "tlog", None)
    return getter() if callable(getter) else mod


def enabled() -> bool:
    """流水是否启用（未接上句柄 → 抛；接上 → 转发宿主判定，见 `game/tlog_setup.py:91-95`）。"""
    if _TLOG is not None:
        fn = getattr(_TLOG, "enabled", None)
        if callable(fn):
            return bool(fn())
        return True                      # 裸 TLog 实例：有实例即已启用
    mod = _loaded_host_module("tlog_setup")
    if mod is None:
        _fail("tlog 句柄", "tlog_setup")
    fn = getattr(mod, "enabled", None)
    return bool(fn()) if callable(fn) else True


def emit(kind: str, actor: str = "", **fields):
    """埋点便捷口（与宿主 `game/tlog_setup.emit` 同签名同语义）。

    * 未接上句柄（装配缺陷）→ **抛 RuntimeError**（不静默 no-op）
    * 已接上但未启用（`tlog()` 为 None）→ **返回 None**（契约零行为）
    * 写流水异常 → 吞掉返回 None（`game/tlog_setup.py:121-124`：流水异常绝不影响主流程）
    * 字段名与保留参数（`kind`/`actor`/`tags`）撞名时用 `fields={...}` 包一层
    """
    if _TLOG is not None:
        handle = _TLOG
    else:
        handle = _loaded_host_module("tlog_setup")
        if handle is None:
            _fail("tlog 句柄", "tlog_setup")
    getter = getattr(handle, "tlog", None)
    tl = getter() if callable(getter) else handle
    if tl is None:
        return None
    try:
        return tl.emit(kind, actor=str(actor or ""), **fields)
    except Exception:                                            # noqa: BLE001
        return None
