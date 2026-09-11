# -*- coding: utf-8 -*-
"""容量受限的「格子列表」骨架 —— 仓库 / 邮件附件 / 公会仓库 / 背包格 同形。

形状
----
* 容器 = **有序格子列表**，每格一件：`{"key": 物品标识, "data": {...}, "count": n}`
* 容量 = `max_slots`（`None` = 不限）
* 操作 = 加一件（满则拒绝）/ 按下标取（1-based，越界拒绝）/ 读全部
* 持久化 = 由使用方决定；本类只给 `load` / `dump`（JSON 文本）两个纯函数式入口

有意不做的事
------------
* **不做存储 IO**：`load`/`dump` 只处理字符串 ↔ 结构，事务边界留给使用方
  （仓库存仓要「读 → 判容量 → 写回 → 扣背包」在**同一事务**内，见游戏侧实现）
* **不做堆叠合并**：同 key 多件是否并成一格是**策略**，不是骨架职责 ——
  实际在用的仓库是「一格一件」（`count` 恒 1），故框架不预设合并语义
* **不做物品语义**：`key`/`data` 原样存取，框架不解释
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Optional

__all__ = ["Slots", "make_entry"]


def make_entry(key: Any, data: Optional[dict] = None, count: int = 1) -> dict:
    """构造一格（`count` 至少 1）。"""
    return {"key": key, "data": dict(data or {}), "count": max(1, int(count or 1))}


class Slots:
    """容量受限的格子列表。"""

    def __init__(self, max_slots: Optional[int] = None,
                 entries: Optional[Iterable[dict]] = None) -> None:
        self.max_slots = None if max_slots is None else int(max_slots)
        self._entries: list[dict] = []
        for e in entries or ():
            self._entries.append(self._normalize(e))

    # ------------------------------------------------------------ 构造 / 序列化
    @staticmethod
    def _normalize(e: Any) -> dict:
        """把任意来源的一格规整成 `{key, data, count}`（脏数据不炸）。"""
        if not isinstance(e, dict):
            return make_entry(e, {}, 1)
        return make_entry(e.get("key"), e.get("data") or {}, e.get("count") or 1)

    @classmethod
    def load(cls, raw: Any, max_slots: Optional[int] = None) -> "Slots":
        """从 JSON 文本 / 列表 / None 载入（**容错**：坏数据 → 空容器）。

        容错是刻意的：这一层读的是历史落盘数据，格式漂移不该让功能崩。
        """
        data = raw
        if isinstance(data, (str, bytes)):
            try:
                data = json.loads(data)
            except (ValueError, TypeError):
                data = None
        if not isinstance(data, list):
            data = []
        return cls(max_slots=max_slots, entries=data)

    def dump(self) -> str:
        """序列化为 JSON 文本（`ensure_ascii=False`，与既有落盘格式一致）。"""
        return json.dumps(self._entries, ensure_ascii=False)

    # ------------------------------------------------------------ 读
    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self):
        return iter(self._entries)

    def entries(self) -> list[dict]:
        """全部格子（浅拷贝列表；元素为原字典，调用方改元素即改容器）。"""
        return list(self._entries)

    def is_full(self) -> bool:
        """是否已满（`max_slots=None` 恒不满）。"""
        return self.max_slots is not None and len(self._entries) >= self.max_slots

    def free(self) -> Optional[int]:
        """剩余格数（不限容量 → None）。"""
        return None if self.max_slots is None else max(0, self.max_slots - len(self._entries))

    def peek_at(self, idx: int) -> Optional[dict]:
        """看第 `idx` 格（**1-based**）；越界 → None。"""
        if idx < 1 or idx > len(self._entries):
            return None
        return self._entries[idx - 1]

    # ------------------------------------------------------------ 写
    def add(self, key: Any = None, data: Optional[dict] = None, count: int = 1,
            *, entry: Optional[dict] = None) -> bool:
        """加一格；**满了返回 False**（不抛错 —— 调用方按业务提示）。

        两种用法二选一：`add(key, data, count)` 或 `add(entry={...})`。
        """
        if self.is_full():
            return False
        self._entries.append(make_entry(key, data, count) if entry is None
                             else self._normalize(entry))
        return True

    def take_at(self, idx: int) -> Optional[dict]:
        """取走第 `idx` 格（1-based）并返回它；越界 → None。"""
        if idx < 1 or idx > len(self._entries):
            return None
        return self._entries.pop(idx - 1)

    def remove_at(self, idx: int) -> bool:
        """丢弃第 `idx` 格（1-based）；越界 → False。"""
        if idx < 1 or idx > len(self._entries):
            return False
        self._entries.pop(idx - 1)
        return True

    def clear(self) -> None:
        self._entries.clear()
