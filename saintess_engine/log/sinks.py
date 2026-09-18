# -*- coding: utf-8 -*-
"""日志出口（sink）—— 分发纪律 + 三个随包实现。

**Sink 协议**（结构化鸭子类型，**不强制继承**）::

    class MySink:
        def emit(self, record: logging.LogRecord) -> None: ...
        def flush(self) -> None: ...     # 可选
        def close(self) -> None: ...     # 可选

**三条分发纪律**（后续的结构化流水 `tlog` 复用同一形状）：

1. 一个 sink 抛异常**不牵连同批其他 sink**（逐个隔离，只报 stderr）—— 日志不该把主流程带崩。
2. **零 sink = 零行为**：`sinks=()` 时门面不装出口，`dispatch` 也不做事（零 IO、零依赖）。
3. record **本体**交给 sink（门面不做格式化）—— 于是 `MemorySink` 能按字段查
   （`record.actor` / `record.duration`），文本类 sink 自己决定怎么排版。

`saintess_engine.log.configure(sinks=[...])` 用 `SinkHandler` 把标准库 record 桥接给这些
sink；同一个 sink 对象也可以由宿主手动 `logger.addHandler(SinkHandler(sink))`。
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from typing import Any, Optional, Protocol, Sequence

__all__ = [
    "Sink", "SinkHandler", "StreamSink", "FileSink", "MemorySink",
    "DEFAULT_FMT", "format_record", "dispatch",
]

# 文本 sink 的默认排版（显式给 `fmt=` 或用 `configure(fmt=...)` 覆盖）
DEFAULT_FMT = "%(asctime)s %(levelname)s %(name)s %(message)s"


class Sink(Protocol):
    """出口协议：`emit(record)` 必须；`flush()` / `close()` 可选。

    结构化协议 —— 实现方**不需要** import 本模块或继承任何基类，只要方法在。
    """

    def emit(self, record: logging.LogRecord) -> None:
        ...

    def flush(self) -> None:
        ...

    def close(self) -> None:
        ...


def format_record(record: logging.LogRecord, fmt: str = DEFAULT_FMT) -> str:
    """把 record 文本化（无副作用：不改 record，用局部 Formatter）。"""
    return logging.Formatter(fmt).format(record)


def _sink_error(sink: Any, record: logging.LogRecord, exc: BaseException) -> None:
    """sink 自身出错时的报告口径 —— 与标准库 `Handler.handleError` 同一纪律。

    直接写 stderr，**不经过 logging**（否则 sink 坏了会递归触发自己）。
    `logging.raiseExceptions = False` 时静默（生产环境的常规选择）。
    """
    if not logging.raiseExceptions:
        return
    try:
        sys.stderr.write(f"--- 日志 sink 处理失败 {sink!r}（record.levelname="
                         f"{getattr(record, 'levelname', '?')}）---\n")
        import traceback
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    except Exception:                                             # pragma: no cover
        pass


def dispatch(sinks: Sequence[Any], record: logging.LogRecord) -> int:
    """把 record 逐个发给 sink，返回**成功数**（异常被隔离，纪律 1）。

    空 `sinks` → 返回 0 且什么都不做（纪律 2）。
    """
    ok = 0
    for s in sinks:
        try:
            s.emit(record)
            ok += 1
        except Exception as exc:                                  # noqa: BLE001
            _sink_error(s, record, exc)
    return ok


def _flush_sinks(sinks: Sequence[Any]) -> None:
    for s in sinks:
        try:
            fn = getattr(s, "flush", None)
            if callable(fn):
                fn()
        except Exception as exc:                                  # noqa: BLE001
            _sink_error(s, logging.LogRecord("", 0, "", 0, "", (), None), exc)


# ---------------------------------------------------------------- 出口实现
class StreamSink:
    """写到文本流（默认 `sys.stderr` —— 与标准库 lastResort 去向一致）。

    每行写完即 flush（日志要及时；这也是标准库 `StreamHandler` 的口径）。
    """

    def __init__(self, stream=None, fmt: str = DEFAULT_FMT) -> None:
        self._stream = stream
        self.fmt = fmt
        self._lock = threading.RLock()

    @property
    def stream(self):
        return self._stream if self._stream is not None else sys.stderr

    def set_format(self, fmt: str) -> "StreamSink":
        """改排版（`configure(fmt=...)` 正是调它，鸭子类型）。"""
        self.fmt = fmt
        return self

    def emit(self, record: logging.LogRecord) -> None:
        line = format_record(record, self.fmt) + "\n"
        with self._lock:
            self.stream.write(line)
            try:
                self.stream.flush()
            except Exception:                                     # pragma: no cover
                pass

    def flush(self) -> None:
        with self._lock:
            try:
                self.stream.flush()
            except Exception:                                     # pragma: no cover
                pass


class FileSink:
    """追加写文件；`rotate` 给定时按大小轮转（`path` → `path.1` → `path.2` …）。

    参数
    ----
    path:      目标文件（父目录不存在会自动建）
    fmt:       每行排版
    rotate:    `None` 不轮转｜`"size"` 按 `max_bytes` 轮转｜`int` = 按该字节数轮转
    max_bytes: 单文件上限（达线即轮转，把 `path` 挪成 `path.1`）
    backups:   保留的历史份数（`path.1` … `path.N`；更老的丢弃）
    encoding:  文本编码（默认 utf-8）
    """

    def __init__(self, path, *, fmt: str = DEFAULT_FMT, rotate=None,
                 max_bytes: int = 1_000_000, backups: int = 3,
                 encoding: str = "utf-8") -> None:
        self.path = os.fspath(path)
        self.fmt = fmt
        self.encoding = encoding
        self.max_bytes = int(max_bytes)
        self.backups = max(1, int(backups))
        if rotate is None:
            self.rotate_mode: Optional[str] = None
        elif isinstance(rotate, bool):
            raise TypeError("rotate 只接受 None / 'size' / 字节数")
        elif isinstance(rotate, int):
            self.rotate_mode = "size"
            self.max_bytes = int(rotate)
        elif str(rotate) == "size":
            self.rotate_mode = "size"
        else:
            raise ValueError(f"未知的 rotate 取值：{rotate!r}（只支持 None / 'size' / 字节数）")
        self._fh = None
        self._lock = threading.RLock()

    def set_format(self, fmt: str) -> "FileSink":
        self.fmt = fmt
        return self

    # ------------------------------------------------------------ 内部
    def _open(self):
        if self._fh is None or self._fh.closed:
            parent = os.path.dirname(os.path.abspath(self.path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            self._fh = open(self.path, "a", encoding=self.encoding)
        return self._fh

    def _rotate_files(self) -> None:
        if self._fh is not None and not self._fh.closed:
            self._fh.close()
        self._fh = None
        oldest = f"{self.path}.{self.backups}"
        if os.path.exists(oldest):
            os.remove(oldest)
        for i in range(self.backups - 1, 0, -1):
            src, dst = f"{self.path}.{i}", f"{self.path}.{i + 1}"
            if os.path.exists(src):
                os.replace(src, dst)
        if os.path.exists(self.path):
            os.replace(self.path, f"{self.path}.1")

    # ------------------------------------------------------------ 对外
    def emit(self, record: logging.LogRecord) -> None:
        line = format_record(record, self.fmt) + "\n"
        with self._lock:
            fh = self._open()
            if self.rotate_mode == "size":
                try:
                    size = os.path.getsize(self.path)
                except OSError:                                   # pragma: no cover
                    size = fh.tell()
                if size + len(line.encode(self.encoding)) > self.max_bytes:
                    self._rotate_files()
                    fh = self._open()
            fh.write(line)
            fh.flush()

    def flush(self) -> None:
        with self._lock:
            if self._fh is not None and not self._fh.closed:
                self._fh.flush()

    def close(self) -> None:
        with self._lock:
            if self._fh is not None and not self._fh.closed:
                self._fh.flush()
                self._fh.close()


class MemorySink:
    """把 record 收进内存列表（测试 / 诊断 / 一次性的现场快照）。

    `limit` 给定时只保留**最近** N 条（丢最旧）。
    """

    def __init__(self, limit: Optional[int] = None) -> None:
        self.records: list[logging.LogRecord] = []
        self.limit = int(limit) if limit else None
        self._lock = threading.RLock()

    def emit(self, record: logging.LogRecord) -> None:
        with self._lock:
            self.records.append(record)
            if self.limit is not None and len(self.records) > self.limit:
                del self.records[:len(self.records) - self.limit]

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass

    def clear(self) -> None:
        with self._lock:
            self.records.clear()

    # 便利查询（分析/断言用）
    def messages(self, fmt: str = "%(message)s") -> list:
        """全部消息文本（不传 fmt 时只取正文）。"""
        return [format_record(r, fmt) for r in self.records]

    def find(self, level: Optional[str] = None, contains: Optional[str] = None) -> list:
        """按级别名 / 正文包含关系筛选 record。"""
        out = []
        for r in self.records:
            if level is not None and str(r.levelname).upper() != str(level).upper():
                continue
            if contains is not None and contains not in str(r.getMessage()):
                continue
            out.append(r)
        return out


class SinkHandler(logging.Handler):
    """把标准库 record 转交给一串 Sink —— 门面 `configure(sinks=…)` 的桥接件。

    ⚠️ **不做格式化**：record 原样进 sink（纪律 3），故 `setFormatter` 对本 handler 无效；
    排版由 sink 自己负责（文本类 sink 用 `fmt=` / `set_format()`）。
    """

    def __init__(self, sinks: Sequence[Any], level: int = logging.NOTSET) -> None:
        super().__init__(level)
        self._sinks: list = list(sinks)

    @property
    def sinks(self) -> tuple:
        return tuple(self._sinks)

    def add_sink(self, sink: Any) -> None:
        self._sinks.append(sink)

    def remove_sink(self, sink: Any) -> int:
        before = len(self._sinks)
        self._sinks = [s for s in self._sinks if s is not sink]
        return before - len(self._sinks)

    def emit(self, record: logging.LogRecord) -> None:
        dispatch(self._sinks, record)

    def flush(self) -> None:
        _flush_sinks(self._sinks)

    def close(self) -> None:
        try:
            _flush_sinks(self._sinks)
        finally:
            super().close()
