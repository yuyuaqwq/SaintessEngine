# -*- coding: utf-8 -*-
"""「注入 logger 优先、否则模块 logger」的告警口 —— 三处近全同的一份实现。

为什么有它
----------
`clock.LazyTimers` / `events.EventBus` / `timers.Timers` 都接受**可注入 logger**
（`logger=None` ⇒ 落到各模块自己的 `get_logger("<模块名>")`），于是各自抄了一份同样的
`_warn()`（6 行同体 ×3）。收成 mixin 后只有一处实现：口径（`is not None` 而非真值判断）
与调用方式都不再依赖三处各写一遍。

用法（子类需要两个前提）::

    class X(WarnMixin):
        _warn_logger = _LOG          # 模块级 logger 兜底
        # 并且 self._logger 已就位（注入的 logger，可为 None）
"""
from __future__ import annotations

__all__ = ["WarnMixin"]


class WarnMixin:
    """统一告警口：注入的 `self._logger` 优先，为 `None` 时用 `_warn_logger`。"""

    _warn_logger = None                     # 子类必须给：模块级 logger

    def _warn(self, msg: str, *args, **kwargs) -> None:
        logger = self._logger if self._logger is not None else self._warn_logger
        logger.warning(msg, *args, **kwargs)
