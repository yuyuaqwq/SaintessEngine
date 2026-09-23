# -*- coding: utf-8 -*-
"""交易与产出形状 —— 限购 / 货架 / 计时生产 —— 扩展包 `ext_economy` 的门面。

原在 `saintess_engine/` 里，2026-09-23 包栈重构时抽成扩展包（模块内容未改，只改
了指向引擎的相对导入）。数据包要用：`game.json` 里声明 `"depends": ["ext_economy"]`。

本文件把原引擎门面导出的那批符号照原样转出去，外部只需把
`from saintess_engine import X` 改成 `from ext_economy import X`。
"""
from .trade import (DailyLimit, DailyLimitExceeded, SaleResult, apply_rate, settle_sale)
from .shelf import (Shelf, ShelfFillError, ShelfStateError)
from .produce import (AlreadyBusy, Job, Jobs, ProduceStorageError)
from . import trade, shelf, produce

__all__ = [
    "trade",
    "shelf",
    "produce",
    "DailyLimit", "DailyLimitExceeded", "SaleResult", "apply_rate", "settle_sale", "Shelf",
    "ShelfFillError", "ShelfStateError", "AlreadyBusy", "Job", "Jobs", "ProduceStorageError",
]
