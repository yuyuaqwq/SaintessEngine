# -*- coding: utf-8 -*-
"""时间骨架 —— 两个不同的问题，两个不同出口：

* `timer.LazyTimers`：**时长**（多久之后过期），不跑后台定时器
* `wall`：**墙上时间**（现在几点 / 今天是哪天），钟源可注入（宿主传系统钟，测试传假钟）
"""
from . import wall  # noqa: F401
from .timer import LazyTimers  # noqa: F401

__all__ = ["LazyTimers", "wall"]
