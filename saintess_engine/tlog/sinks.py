# -*- coding: utf-8 -*-
"""流水的**出口**（sink）—— 分发纪律 + 两个随包实现。

**Sink 协议**（结构化鸭子类型，**不强制继承**）::

    class MySink:
        def write(self, records: Iterable[Record]) -> None: ...
        def flush(self) -> None: ...     # 可选
        def close(self) -> None: ...     # 可选

**三条纪律**（与 `saintess_engine.log` 的出口同一套，日志与流水共用一套心智模型）：

1. **逐个隔离**：一个 sink 抛异常不牵连同批其他 sink（只报 stderr）
2. **零 sink = 零行为**：`TLog(sinks=())` 什么都不写（零 IO、零依赖）
3. **Record 本体交给 sink**：门面不做格式化 —— 所以 `MemorySink` 能当结构化查询口，
   `JSONLSink` 能落成「可直读、可 grep、可被外部工具吃」的行式文件

**可读出口**（`read_records()`）是分析脚本与回放的资料来源；`Reader` 在它之上做筛选。
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any, Iterable, Iterator, Optional, Protocol, Sequence

from .._sinkbase import FileSinkBase, sink_error
from .record import Record

__all__ = ["Sink", "ReadableSink", "JSONLSink", "MemorySink", "dispatch"]


class Sink(Protocol):
    """出口协议：`write(records)` 必须；`flush()` / `close()` 可选。"""

    def write(self, records: Iterable[Record]) -> None:
        ...

    def flush(self) -> None:
        ...


class ReadableSink(Protocol):
    """可读出口：供 `Reader` 取原始记录（筛选在 Reader 里做）。"""

    def read_records(self) -> Iterator[Record]:
        ...


def dispatch(sinks: Sequence[Any], records: Iterable[Record]) -> int:
    """把一批记录逐个发给 sink，返回**成功数**（异常隔离）。空 sinks → 0 且不做事。"""
    batch = list(records)
    if not batch:
        return 0
    ok = 0
    for s in sinks:
        try:
            s.write(batch)
            ok += 1
        except Exception as exc:                                  # noqa: BLE001
            sink_error(s, exc, what="写入")
    return ok


# ---------------------------------------------------------------- 出口实现
class JSONLSink(FileSinkBase):
    """行式 JSON 落盘（一行一条记录）—— 可直读、可 grep、可被外部工具吃。

    * `path`：目标文件（父目录自动建）；`append=True`（默认）追加，False 截断重写
    * 写入即 flush（流水是事后证据，别留在缓冲区里）
    * `read_records()`：把文件读回（坏行**跳过并记 `bad_lines`**，不整文件失败）
    """

    def __init__(self, path, *, append: bool = True, encoding: str = "utf-8") -> None:
        self.path = os.fspath(path)
        self.append = bool(append)
        self.encoding = encoding
        self.bad_lines: list = []
        super().__init__()

    # -------------------------------------------------- 内部
    _newline = "\n"                     # 行式文件：换行不做平台翻译

    def _open_mode(self) -> str:
        return "a" if self.append else "w"

    def _open(self):
        if self._fh is None or self._fh.closed:
            super()._open()
            self.append = True          # 只截断一次（口径同原实现）
        return self._fh

    # -------------------------------------------------- 写
    def write(self, records: Iterable[Record]) -> None:
        lines = [json.dumps(r.to_dict(), ensure_ascii=False) for r in records]
        if not lines:
            return
        with self._lock:
            fh = self._open()
            fh.write("\n".join(lines) + "\n")
            fh.flush()

    # -------------------------------------------------- 读
    def read_records(self) -> Iterator[Record]:
        """逐行读回（坏行跳过并记入 `bad_lines`）。"""
        if not os.path.exists(self.path):
            return iter(())
        out = []
        with open(self.path, encoding=self.encoding) as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(Record.from_dict(json.loads(line)))
                except Exception:                                 # noqa: BLE001
                    self.bad_lines.append((i, line[:120]))
        return iter(out)


class MemorySink:
    """收进内存（测试 / 一次性现场快照）。`limit` 给定时只留最近 N 条。"""

    def __init__(self, limit: Optional[int] = None) -> None:
        self.records: list = []
        self.limit = int(limit) if limit else None
        self._lock = threading.RLock()

    def write(self, records: Iterable[Record]) -> None:
        with self._lock:
            self.records.extend(records)
            if self.limit is not None and len(self.records) > self.limit:
                del self.records[:len(self.records) - self.limit]

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass

    def clear(self) -> None:
        with self._lock:
            self.records.clear()

    def read_records(self) -> Iterator[Record]:
        return iter(tuple(self.records))

    def kinds(self) -> tuple:
        """出现过的 kind（去重保序）。"""
        out = []
        for r in self.records:
            if r.kind not in out:
                out.append(r.kind)
        return tuple(out)

    def of_kind(self, kind: str) -> list:
        return [r for r in self.records if r.kind == kind]
