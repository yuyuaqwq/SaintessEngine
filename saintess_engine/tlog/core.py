# -*- coding: utf-8 -*-
"""结构化流水门面 —— 「发生过什么，能不能复现」。

与 `saintess_engine.log` 的分工
------------------------------
| | `log` | `tlog`（本模块） |
|---|---|---|
| 问题 | 此刻出什么事了（运维视角） | 发生过什么、能不能复现（业务视角） |
| 单位 | `LogRecord`（级别 + 消息文本） | `Record`（kind + 结构化字段） |
| 出口 | 3 个随包 sink（文本） | `JSONLSink`（落盘可直读）/ `MemorySink` |

两者共用同一套 **Sink 心智模型与分发纪律**（逐个隔离 / 零出口零行为 / record 本体交给出口）。

典型用法::

    from saintess_engine.tlog import TLog, JSONLSink

    tl = TLog(sinks=[JSONLSink("run/tlog.jsonl")], kinds=KT)
    tl.emit("battle.hit", actor="p1", subject="e1", dmg=34, kind="phys")
    for r in tl.reader().iter_records(kind="battle.hit", actor="p1", since=t0):
        print(r.ts, r.fields["dmg"])

**0 sink = 零行为**：不配 sink 时 `emit` 只构造并返回 Record，不做任何 IO。
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Iterable, Optional

from ..log import get_logger

from . import sinks as _sinks
from .record import KindTable, Record

_LOG = get_logger("tlog")   # 引擎内 logger 名只此一源（走门面，见 tests/test_log.py）

__all__ = ["TLog"]


class TLog:
    """流水门面：装载出口、发记录、开读口、自检。

    参数
    ----
    sinks:  出口序列（`JSONLSink` / `MemorySink` / 自定义）；**空 = 零行为**
    kinds:  `KindTable` 声明表（None = 不校验，零行为）
    strict: True 时"记录与声明不符"直接抛（CI/联调用）；False（默认）只在 `on_undeclared` 上报
    clock:  取时间戳的函数（默认 `time.time`）—— **可注入**，测试可控
    name:   本流水名（诊断用）
    """

    def __init__(self, sinks: Iterable = (), *, kinds: Optional[KindTable] = None,
                 strict: bool = False, clock: Optional[Callable[[], float]] = None,
                 name: str = "", on_undeclared: Optional[Callable[[list], None]] = None
                 ) -> None:
        self.sinks: list = list(sinks or ())
        self.kinds = kinds
        self.strict = bool(strict)
        self.name = name
        self.on_undeclared = on_undeclared
        self._clock = clock or time.time
        self._seen: list = []
        self._problems: list = []
        self._lock = threading.RLock()

    # ============================================================ 写
    def emit(self, kind: str, actor: str = "", tags: Iterable = (),
             fields: Optional[dict] = None, **kw) -> Record:
        """记一条流水：`emit("battle.hit", actor="p1", dmg=34)`。

        0 sink → 只返回 Record（零 IO）。声明表存在时按它比对（见 `strict`）。

        ⚠️ **字段名与保留参数冲突时用 `fields=` 显式传**（`kind` / `actor` / `tags` /
        `fields` 是保留参数名）。例：要记一个叫 `kind` 的字段（伤害类别）::

            tl.emit("battle.hit", actor="p1", fields={"kind": "phys"}, dmg=34)
        """
        all_fields = dict(fields or {})
        all_fields.update(kw)
        rec = Record(kind=kind, ts=float(self._clock()), actor=actor,
                     fields=all_fields, tags=tuple(tags or ()))
        with self._lock:
            if rec.kind not in self._seen:
                self._seen.append(rec.kind)
        if self.kinds is not None:
            problems = self.kinds.check_record(rec)
            if problems:
                self._problems.extend(problems)
                if self.strict:
                    raise ValueError("流水与声明不符：" + "；".join(problems))
                if self.on_undeclared is not None:
                    try:
                        self.on_undeclared(problems)
                    except Exception:                             # noqa: BLE001
                        pass
        if not self.sinks:
            return rec                                            # ★ 零 sink = 零行为
        _sinks.dispatch(self.sinks, [rec])
        return rec

    def write_many(self, records: Iterable[Record]) -> int:
        """批量写（分析/回灌场景）；返回成功写入的 sink 数。"""
        batch = list(records)
        for r in batch:
            if r.kind not in self._seen:
                self._seen.append(r.kind)
        if not self.sinks:
            return 0
        return _sinks.dispatch(self.sinks, batch)

    # ============================================================ 读
    def reader(self):
        """开一个读口（从本流水**可读的**出口取记录）。"""
        from .reader import Reader
        return Reader(self.sinks)

    def replay(self, **filters):
        """直接拿一段重放器（等价 `reader().replay(**filters)`）。"""
        return self.reader().replay(**filters)

    # ============================================================ 自检 / 生命周期
    def kinds_seen(self) -> tuple:
        """实际发过的 kind（去重保序）。"""
        return tuple(self._seen)

    def audit(self) -> dict:
        """自检汇总：出口数 / 发过的 kind / 声明表比对 / 累计问题。"""
        out = {"name": self.name, "sinks": len(self.sinks),
               "kinds_seen": list(self._seen), "problems": list(self._problems)}
        if self.kinds is not None:
            out["kinds"] = self.kinds.audit(self._seen)
        return out

    def reset_stats(self) -> None:
        """清空记账（长驻进程按轮次统计）。"""
        with self._lock:
            self._seen = []
            self._problems = []

    def flush(self) -> None:
        for s in self.sinks:
            try:
                fn = getattr(s, "flush", None)
                if callable(fn):
                    fn()
            except Exception:                                     # noqa: BLE001
                _LOG.warning("sink flush 失败（已忽略）", exc_info=True)

    def close(self) -> None:
        """flush + 关闭全部出口（进程退出/轮转时调）。"""
        for s in self.sinks:
            try:
                fn = getattr(s, "close", None)
                if callable(fn):
                    fn()
            except Exception:                                     # noqa: BLE001
                _LOG.warning("sink close 失败（已忽略）", exc_info=True)

    def add_sink(self, sink) -> None:
        self.sinks.append(sink)

    def remove_sink(self, sink) -> int:
        before = len(self.sinks)
        self.sinks = [s for s in self.sinks if s is not sink]
        return before - len(self.sinks)
