# -*- coding: utf-8 -*-
"""容器骨架 —— 两种同族的容器形状：

* `Slots` —— 容量受限的**格子列表**（一格一件；仓库 / 邮件附件 / 公会仓库 同形）
* `Stack` —— 同 key 合并的**堆叠表**（件数累加 + 个体记录 FIFO/上限；背包 / 摊位 同形）
"""
from .slots import Slots, make_entry  # noqa: F401
from .stack import Stack, carries_records, merge_records, trim_records  # noqa: F401

__all__ = ["Slots", "make_entry",
           "Stack", "carries_records", "merge_records", "trim_records"]
