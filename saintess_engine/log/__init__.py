# -*- coding: utf-8 -*-
"""日志骨架 —— 统一命名 + 可拔插出口 + 结构化上下文。

**不配置 = 不存在**：不调 `configure()` 时只是标准库 `logging` 的薄封装，
宿主原有日志行为逐字不变（详见 `facade`）。

    from saintess_engine.log import get_logger, configure, FileSink, bind

`Sink` 协议与分发纪律在 `sinks` —— 后续的结构化流水（`tlog`）复用同一形状。
其中**报错口径**与**文件出口生命周期**是同一份代码（`saintess_engine/_sinkbase.py`），
两侧不再各抄一份。
"""
from .facade import (  # noqa: F401
    DEFAULT_FMT, DEFAULT_PREFIX, RESERVED_KEYS,
    ContextAdapter, bind, configure, get_logger, logger_name, remove_sinks,
)
from .sinks import (  # noqa: F401
    FileSink, MemorySink, Sink, SinkHandler, StreamSink, dispatch, format_record,
)

__all__ = [
    "get_logger", "configure", "bind", "logger_name", "remove_sinks",
    "ContextAdapter", "DEFAULT_PREFIX", "RESERVED_KEYS",
    "Sink", "SinkHandler", "StreamSink", "FileSink", "MemorySink",
    "dispatch", "format_record", "DEFAULT_FMT",
]
