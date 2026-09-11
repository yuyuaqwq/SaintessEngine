# -*- coding: utf-8 -*-
"""分页骨架 —— 「一页几条、第几页、共几页」的纯函数。

列表类输出到处都要做这件事，与游戏无关。
"""
from __future__ import annotations

from typing import Any, Sequence

__all__ = ["page_items", "parse_page"]


def page_items(items: Sequence[Any], page: int, per_page: int = 5) -> tuple:
    """通用翻页：返回 `(当前页条目, 总页数, 已夹取的页码)`。

    * 页码越界自动夹到 `[1, pages]`（不抛错 —— 调用方多为玩家输入）
    * 空列表 → `pages = 1`（保证「第 1/1 页」这种可用显示）
    """
    total = len(items)
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(int(page or 1), pages))
    start = (page - 1) * per_page
    return list(items[start:start + per_page]), pages, page


def parse_page(raw: Any) -> int:
    """解析参数里的页码：纯数字 → 该页；否则 1。"""
    raw = ("" if raw is None else str(raw)).strip()
    if raw.isdigit():
        return int(raw)
    return 1
