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

import logging
import os
import sys
import threading

__all__ = ["FileSinkBase", "sink_error"]


def sink_error(sink, exc, what: str = "写入", detail: str = "") -> None:
    """sink 自身出错时的统一报告口径 —— 与标准库 `Handler.handleError` 同一纪律。

    直接写 stderr，**不经过 logging**（否则 sink 坏了会递归触发自己）。
    `logging.raiseExceptions = False` 时静默（生产环境的常规选择）。
    """
    if not logging.raiseExceptions:
        return
    try:
        sys.stderr.write(f"--- sink {what}失败 {sink!r}{detail} ---\n")
        import traceback
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    except Exception:                                             # pragma: no cover
        pass


class FileSinkBase:
    """文件出口的共用生命周期：懒开（父目录自动建）· 刷 · 关。

    子类负责给定 `self.path` / `self.encoding`，并按需覆写 `_open_mode()` 与 `_newline`；
    `self._fh` / `self._lock` 由本类初始化（子类 `__init__` 记得 `super().__init__()`）。
    """

    _newline = None                     # 文本翻译口径（None = 跟随平台）

    def __init__(self) -> None:
        self._fh = None
        self._lock = threading.RLock()

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
        with self._lock:
            if self._fh is not None and not self._fh.closed:
                self._fh.flush()
                self._fh.close()
