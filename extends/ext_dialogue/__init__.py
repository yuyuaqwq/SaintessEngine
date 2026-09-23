# -*- coding: utf-8 -*-
"""对话树与会话游标形状 —— 扩展包 `ext_dialogue` 的门面。

原在 `saintess_engine/` 里，2026-09-23 包栈重构时抽成扩展包（模块内容未改，只改
了指向引擎的相对导入）。数据包要用：`game.json` 里声明 `"depends": ["ext_dialogue"]`。

本文件把原引擎门面导出的那批符号照原样转出去，外部只需把
`from saintess_engine import X` 改成 `from ext_dialogue import X`。
"""
from .dialogue import (Dialogue, Cursor, END_KEY)
from . import dialogue

__all__ = [
    "dialogue",
    "Dialogue", "Cursor", "END_KEY",
]
