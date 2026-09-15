# -*- coding: utf-8 -*-
"""待批队列（Applications）—— 保序 + 去重 + 容量上限。

**形状在哪**：把「谁在等批」做成一个**保序、去重、有上限**的队列。申请要什么条件、
批了之后要通知谁、文案怎么写，全属内容侧。

**成员集合只有一个**：队列里的**申请人不是成员**（申请的本义就是「还不是」），所以本形状
不维护任何成员表；`approve()` 通过时，若注入了 `Roster` 引用（`roster=`），就调
`roster.join()` 把成员身份**交给名单**。`roster` 是**可选注入面**（`self.roster is None` 即留痕）：

* 注入了名单 → `approve()` 出队并**入册**（成员身份只有名单一个来源）；
* 未注入 → `approve()` 只出队（成员册由内容侧自己处理）。这一退化是**显式**的（可查 `self.roster`）。

**用法**::

    from saintess_engine.run import Roster
    from saintess_engine.membership import Applications, QueueFull

    r = Roster([])
    q = Applications(cap=2, roster=r)
    q.push("1001")                   # True
    q.push("1001")                   # False（已在队列 → 幂等）
    q.push("1002")                   # True
    q.push("1003")                   # → QueueFull（cap=2）
    q.pending()                      # ['1001', '1002']（保序；返回拷贝）
    q.reject("1002")                 # True（出队，不入册）
    q.approve("1001")                # True（出队 + 入册：r.members == ['1001']）
    q.approve("1001")                # False（已不在队列）
    q.cap_of()                       # 2

**有意不做的事**
----------------
* **不判入会条件**：够不够格、谁有权批属内容侧 —— 本形状只管「排着 / 出队」。
* **不判重复申请**：已在册者能不能再申请由内容侧决定（本形状只去重**队列内部**的重复）。
* **不通知**：通过 / 拒绝之后的回执、文案、流水全在内容侧。
* **不做超时**：队列不会自己过期 —— 什么时候清由内容侧决定（`approve()` / `reject()`）。
"""
from __future__ import annotations

from typing import Optional

__all__ = ["Applications", "QueueFull"]


class QueueFull(RuntimeError):
    """队列已满（`cap` 上限；`cap=0` 时任何入队都会撞上它）。"""


class Applications:
    """待批队列：保序 + 去重 + 容量上限。**可变**。

    `cap`   : 容量上限（`None` = 不限；`0` = 一个都不收）
    `roster`: `Roster` 引用（可选注入面；`approve()` 通过时入册，见模块 docstring）
    """

    __slots__ = ("_queue", "_cap", "roster")

    def __init__(self, cap: Optional[int] = None, *, roster=None) -> None:
        if cap is not None:
            if isinstance(cap, bool) or not isinstance(cap, int):
                raise TypeError(f"cap 必须是整数或 None：{cap!r}")
            if cap < 0:
                raise ValueError(f"cap 不能为负：{cap}")
        self._cap = cap
        self._queue: list = []         # 保序的待批清单（不是成员集合）
        self.roster = roster           # 名单引用；None = 未注入（显式可查，见模块 docstring）

    # ---------------------------------------------------------------- 查询
    def cap_of(self) -> Optional[int]:
        """容量上限（`None` = 不限）。"""
        return self._cap

    def pending(self) -> list:
        """待批清单（**保序**）。返回**拷贝** —— 改它不影响队列。"""
        return list(self._queue)

    # ---------------------------------------------------------------- 变更
    def push(self, applicant) -> bool:
        """入队：**已在队列 → False**（幂等）；**满 → `QueueFull`**。"""
        a = str(applicant)
        if a in self._queue:
            return False
        if self._cap is not None and len(self._queue) >= self._cap:
            raise QueueFull(f"待批队列已满（cap={self._cap}，在队 {len(self._queue)}）")
        self._queue.append(a)
        return True

    def approve(self, applicant) -> bool:
        """通过：出队（注入了名单则同时 `roster.join()` 入册）。**不在队列 → False**。"""
        a = str(applicant)
        if a not in self._queue:
            return False
        self._queue.remove(a)
        if self.roster is not None:
            self.roster.join(a)
        return True

    def reject(self, applicant) -> bool:
        """拒绝：出队（**不入册**）。**不在队列 → False**。"""
        a = str(applicant)
        if a not in self._queue:
            return False
        self._queue.remove(a)
        return True
