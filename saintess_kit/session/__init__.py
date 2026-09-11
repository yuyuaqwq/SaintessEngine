# -*- coding: utf-8 -*-
"""会话骨架 —— 宿主事件契约、参考实现与「会话标识」适配点。

「换宿主」的接口就在 `adapter` 里：宿主适配器只需把宿主事件翻译成
契约方法（`get_message_str` / `get_group_id` / `get_sender_id` /
`plain_result` / `stop_event`），命令层骨架即可直接工作。
"""
from .adapter import PlainEvent, PlainResult, SessionAdapter  # noqa: F401

__all__ = ["PlainEvent", "PlainResult", "SessionAdapter"]
