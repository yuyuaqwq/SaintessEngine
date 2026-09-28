# -*- coding: utf-8 -*-
"""出口（sink）的共用底座 —— `log` 与 `tlog` 两套出口的同一套报告口径与文件生命周期。

为什么有它
----------
`saintess_engine/log/sinks.py` 与 `saintess_engine/tlog/sinks.py` 是**同一心智模型的
两个实例**（两边的模块 docstring 都写明「同一套纪律」），却各自抄了一份：

  · sink 自身出错时的报告口径 —— 直接写 stderr、**不经日志系统**（sink 坏了再走日志会递归）；
  · 文件出口的生命周期 —— 懒开（父目录自建）· `flush()` · `close()`。

收成单点后，纪律只有一处可改：「两套出口口径一致」不再靠注释互相提醒，而是同一份代码。

**协议层仍各自定义**（`Sink` / `dispatch`）：两侧的记录形状与批/单语义本就不同 ——
日志是 `emit(record)` 单条、流水是 `write(records)` 整批，合并会同时污染两侧的形状。
"""
from __future__ import annotations

import os
import sys
import threading

__all__ = ["FileSinkBase", "sink_error", "set_sink_reporter", "sink_error_stats",
           "SINK_ERROR_ESCALATE"]

#: 出口写失败**默认出声**（审计 L2730）—— 本模块自己的纪律，不看 `logging` 的全局。
_MUTE = False

#: 累计失败多少次打一条**摘要**（第一次仍带完整 traceback）。
#: 节流是为了别把 stderr 刷爆，**不是**为了把证据丢掉。
SINK_ERROR_ESCALATE = 50

#: 本进程内的失败累计（`sink_error_stats()` 的真源）。
_STATS = {"errors": 0, "kinds": {}, "first": ""}


def sink_error(sink, exc, what: str = "写入", detail: str = "") -> None:
    """sink 自身出错时的统一报告口径 —— 与标准库 `Handler.handleError` 同一纪律。

    直接写 stderr，**不经过 logging**（否则 sink 坏了会递归触发自己）。

    ★ 审计 L2730：**不再拿 `logging.raiseExceptions` 当自己的开关**。
      那是标准库的**全局**，而「出口写失败」这件事归属本模块（`log` 与 `tlog`
      两套出口共用这一个报告口）⇒ 原先的耦合方向是反的：任何一个第三方库调一下
      那个全局，`log` 与 `tlog` 两侧**唯一的错误信号就没了** ——
      实测（`%TEMP%/afix3r21/probe_r21.py`）：造一个写不进去的出口，
      stderr **一个字都没有**、记录真丢、`dispatch` 返回 0。
      「直接写 stderr」是本模块的**纪律**（不递归），不是「写失败也静默」的许可。
      tlog 侧本来就另有 `JSONLSink.bad_lines` 那样**自有的**丢失记录位 ⇒ 同一形状。

    现在的口径（**只加强、不放宽**）：

    1. **默认出声** —— 写失败就往 stderr 报一次（带 traceback），除非**显式**关掉。
    2. **自有开关** `set_sink_reporter(off=True)` —— 想静默由**本模块的调用方**
       自己决定，而不是被别的包的全局顺带关掉；静默时**计数照记**。
    3. **升级为硬告警** —— 累计失败到 `SINK_ERROR_ESCALATE` 的整数倍时打一条
       **摘要**（累计数 / 分项 / 首次异常），其余次数节流（防刷爆，不是丢证据）。
    4. **计数器可读** `sink_error_stats()` —— 让「丢了多少」是**可查的事实**，
       而不是「stderr 空了 = 丢了」。
    """
    global _STATS
    _STATS["errors"] += 1
    kinds = _STATS["kinds"]                    # what -> 次数（**跨所有出口**）
    kinds[what] = kinds.get(what, 0) + 1
    # 每个出口各留一条最近一次 —— 摘要行报的是「**这一批里谁坏了**」，
    # 而不只是第一次那个（否则只修好前一个出口时，摘要仍指向旧的那个）。
    _STATS.setdefault("last", {})[repr(sink)] = "%s: %s: %s" % (what, type(exc).__name__, exc)
    if not _STATS["first"]:
        _STATS["first"] = "%s %r: %s: %s" % (what, sink, type(exc).__name__, exc)
    if _MUTE:
        return
    n = _STATS["errors"]
    if n > 1 and (n - 1) % SINK_ERROR_ESCALATE:
        return                                          # 节流：摘要之间静默
    try:
        if n == 1:
            sys.stderr.write(f"--- sink {what}失败 {sink!r}{detail} ---\n")
            import traceback
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
        else:
            sys.stderr.write(
                "--- sink 累计 %d 次失败（每 %d 次一条摘要）%s · 各出口最近一次 %s ---\n"
                % (n, SINK_ERROR_ESCALATE, kinds, _STATS["last"]))
    except Exception:                                             # pragma: no cover
        pass                # stderr 本身坏了再报就是递归（合法容错，见判据 2）


def set_sink_reporter(off: bool = False) -> None:
    """本模块**自有**的报告开关（审计 L2730）—— 不再借 `logging` 的全局。

    `off=True` = 静默（**显式**选择，由调用方自己决定；计数**照记**，
    `sink_error_stats()` 仍能查出丢了多少）。恢复出声用 `set_sink_reporter(False)`。
    """
    global _MUTE
    _MUTE = bool(off)


def sink_error_stats() -> dict:
    """本进程内出口写失败的**累计事实**（审计 L2730）：
    `{"errors": N, "kinds": {what: n, ...}, "first": "..."}`。

    「丢了多少」应当是可查的数字，而不是「stderr 空了就是丢了」。
    """
    return {"errors": _STATS["errors"], "kinds": dict(_STATS["kinds"]),
            "first": _STATS["first"], "last": dict(_STATS.get("last", {}))}



class FileSinkBase:
    """文件出口的共用生命周期：懒开（父目录自动建）· 刷 · 关。

    子类负责给定 `self.path` / `self.encoding`，并按需覆写 `_open_mode()` 与 `_newline`；
    `self._fh` / `self._lock` 由本类初始化（子类 `__init__` 记得 `super().__init__()`）。
    """

    _newline = None                     # 文本翻译口径（None = 跟随平台）

    def __init__(self) -> None:
        self._fh = None
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        """★ 2026-09-28（审计 L2734-2）：出口报错误里带**路径**，不只给内存地址。

        `sink_error` 的文案是 `f"... {sink!r} ..."`；此前 `log/*` / `tlog/*` / 本文件
        **全仓零 `__repr__` / `__str__` 定义** ⇒ 排障时 stderr 只给
        `<...FileSink object at 0x...>`，**哪个文件写失败要先猜**。
        路径就在 `self.path`（子类 `__init__` 落点），取不到就退回默认 repr（诊断本身不抛）。
        """
        path = getattr(self, "path", None)
        if not path:
            return object.__repr__(self)
        return "%s(path=%s)" % (type(self).__name__, path)

    # ------------------------------------------------------------ 内部
    def _open_mode(self) -> str:
        return "a"

    def _open(self):
        if self._fh is None or self._fh.closed:
            parent = os.path.dirname(os.path.abspath(self.path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            self._fh = open(self.path, self._open_mode(), encoding=self.encoding,
                            newline=self._newline)
        return self._fh

    # ------------------------------------------------------------ 对外
    def flush(self) -> None:
        with self._lock:
            if self._fh is not None and not self._fh.closed:
                self._fh.flush()

    def close(self) -> None:
        """关掉当前句柄。**不是终态关窗** —— `self._fh` **不置 None**（审计 L2739）。

        `close()` 之后 `self._fh.closed is True`；紧接着任何一次 `write()` 会走
        `_open()` 的 `or self._fh.closed` 分支**自动重开**同一个文件（append 续写）。

        判据：这是标准库 handler 的同一语义（关闭后仍可复用），**不是 bug**；
        写在这里是为了让下一个人读 `close()` 时不会把它当「此后再写会抛」。
        """
        with self._lock:
            if self._fh is not None and not self._fh.closed:
                self._fh.flush()
                self._fh.close()
