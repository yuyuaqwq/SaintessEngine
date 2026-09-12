# -*- coding: utf-8 -*-
"""结构化流水骨架 —— 「发生过什么，能不能复现」。

    from saintess_engine.tlog import TLog, JSONLSink, KindTable

    tl = TLog(sinks=[JSONLSink("run/tlog.jsonl")])       # 0 sink = 零行为
    tl.emit("battle.hit", actor="p1", subject="e1", dmg=34)
    tl.reader().iter_records(kind="battle.", actor="p1", since=t0)
    tl.replay(kind="battle.").anonymize()                 # 脱敏后交分析侧

模块分工：

  record.py  `Record`（一条流水）+ `KindTable`（「哪个 kind 有哪些字段」的声明表）
  sinks.py   `Sink` 协议 + `JSONLSink` / `MemorySink`（分发纪律与 log 同一套）
  core.py    `TLog` 门面（emit / reader / audit / 生命周期）
  reader.py  `Reader`（筛选读口）+ `Replay`（按序重放 / 脱敏）
  bridge.py  `EventLogBridge`（事件总线 → 流水；映射表由内容侧给）

零知识：不认任何具体 kind、不认数据库。落地方式（表结构 / 索引 / 匿名化视图）全在内容侧。
"""
from .bridge import EventLogBridge  # noqa: F401
from .core import TLog  # noqa: F401
from .reader import Reader, Replay  # noqa: F401
from .record import KIND_RE, KindSpec, KindTable, Record, is_valid_kind  # noqa: F401
from .sinks import JSONLSink, MemorySink, Sink, dispatch  # noqa: F401

__all__ = [
    "TLog", "Record", "KindSpec", "KindTable", "KIND_RE", "is_valid_kind",
    "Sink", "JSONLSink", "MemorySink", "dispatch",
    "Reader", "Replay", "EventLogBridge",
]
