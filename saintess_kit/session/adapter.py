# -*- coding: utf-8 -*-
"""会话契约 + 参考实现 —— 让「换宿主」有明确的接口可依。

背景
----
命令层骨架（`saintess_kit.command`）一直**鸭子类型**地用宿主事件：
`event.get_message_str()` / `event.plain_result(text)` / `event.get_group_id()` …
契约是隐式的 —— 新宿主实现者只能去读框架源码反推。本模块把它**显式化**：

* `EventLike` / `ResultLike`：契约说明（Protocol 文档，不强制继承）
* `PlainEvent` / `PlainResult`：**参考实现**（纯标准库）——
  测试、CLI、非 AstrBot 宿主都能直接用
* `SessionAdapter`：把「从事件取会话标识」这一步收拢成一处可替换的适配点

宿主适配器的职责就只有这个：**把宿主事件翻译成契约**。
"""
from __future__ import annotations

from typing import Any, Callable, Optional

__all__ = ["PlainResult", "PlainEvent", "SessionAdapter"]


class PlainResult:
    """最简「回复」：只带文本。"""

    __slots__ = ("text",)

    def __init__(self, text: str = "") -> None:
        self.text = str(text)

    def __repr__(self) -> str:
        return f"PlainResult({self.text!r})"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, PlainResult) and other.text == self.text

    def __str__(self) -> str:
        return self.text


class PlainEvent:
    """最简「事件」参考实现 —— 满足命令层骨架用到的全部访问点。

    契约（命令层骨架只依赖这些）：

    | 方法 | 用途 |
    |---|---|
    | `get_message_str() -> str` | 取消息文本（剥指令/取参数） |
    | `get_group_id() -> str \\| None` | 取会话/群标识（None → 适配器给兜底） |
    | `get_sender_id() -> str \\| None` | 取发送者标识 |
    | `plain_result(text)` | 造一条文本回复 |
    | `stop_event()`（可选） | 停止事件传播 |

    `message_str` 是可写属性 —— 快捷转发会临时改写它再恢复。
    """

    def __init__(self, message: str = "", *, group_id: Optional[str] = None,
                 sender_id: Optional[str] = None) -> None:
        self.message_str = message
        self._group_id = group_id
        self._sender_id = sender_id
        self.stopped = False

    # ---- 契约：读 ----
    def get_message_str(self) -> str:
        return self.message_str or ""

    def get_group_id(self):
        return self._group_id

    def get_sender_id(self):
        return self._sender_id

    # ---- 契约：写 ----
    def plain_result(self, text) -> PlainResult:
        return PlainResult(text)

    def stop_event(self) -> None:
        self.stopped = True

    def __repr__(self) -> str:
        return f"PlainEvent({self.message_str!r}, group={self._group_id!r}, sender={self._sender_id!r})"


class SessionAdapter:
    """把「宿主事件」翻译成「会话标识」的适配点。

    * `private_fallback`：宿主不给 group_id 时用的占位（私聊场景）
    * `unknown_fallback`：宿主不给 sender_id 时用的占位
    * `resolve_uid`：把原始发送者标识换成**稳定用户标识**的回调
      （如「平台 openid → 账号 id」的映射；默认原样返回）

    命令层不该关心「群号怎么来」「openid 怎么翻译」——
    把这两件事收在这里，换宿主只需换这一个对象。
    """

    def __init__(self, *, private_fallback: str = "private",
                 unknown_fallback: str = "unknown",
                 resolve_uid: Optional[Callable[[str], str]] = None) -> None:
        self.private_fallback = private_fallback
        self.unknown_fallback = unknown_fallback
        self._resolve_uid = resolve_uid

    def resolve(self, raw: str) -> str:
        """原始标识 → 稳定标识（默认原样返回）。"""
        if self._resolve_uid is None:
            return raw
        try:
            return self._resolve_uid(raw) or raw
        except Exception:
            return raw

    def uid(self, event) -> tuple:
        """返回 `(group_id, user_id)`。"""
        group_id = event.get_group_id() or self.private_fallback
        sender_id = event.get_sender_id() or self.unknown_fallback
        return str(group_id), str(self.resolve(sender_id))
