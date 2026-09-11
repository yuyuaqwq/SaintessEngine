# -*- coding: utf-8 -*-
"""指令文本骨架 —— 从宿主消息里剥前缀、取参数。

宿主消息常带平台注入的前缀（`@某人` / `[引用消息…]` 之类），
以及要剥掉的指令词本身；这些形状与具体游戏无关，
**别名表**由使用方给（框架不预设任何指令名）。
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional

__all__ = ["strip_at_prefix", "strip_command", "AT_PREFIX_PATTERNS"]

# 平台注入前缀（顺序即应用顺序；均为行首锚定）
AT_PREFIX_PATTERNS = (
    r"^\[At:[^\]]*\]\s*",          # [At:某人] —— 含 [At:全体成员]
    r"^\[引用消息[^\]]*\]\s*",      # [引用消息…]
)


def strip_at_prefix(msg: str) -> str:
    """剥掉行首的平台注入前缀（At / 引用），返回剩余文本。"""
    msg = (msg or "").strip()
    for pat in AT_PREFIX_PATTERNS:
        msg = re.sub(pat, "", msg)
    return msg


def strip_command(msg: str, cmd: str, aliases: Iterable[str] = ()) -> str:
    """剥掉行首的 `cmd`（或任一 `alias`），返回剩余参数。

    * 先剥平台前缀，再剥指令词
    * `alias == cmd` 时跳过（避免自己剥自己）
    * 都不命中 → 原样返回（不做猜测）
    """
    msg = strip_at_prefix(msg)
    if cmd and msg.startswith(cmd):
        return msg[len(cmd):].strip()
    for alias in aliases:
        if alias and alias != cmd and msg.startswith(alias):
            return msg[len(alias):].strip()
    return msg
