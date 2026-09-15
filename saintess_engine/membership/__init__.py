# -*- coding: utf-8 -*-
"""成员关系形状（membership）—— 名单（`Roster`）之外的三件事：**职位** · **贡献** · **申请**。

**为什么有它**：「谁在里面」由 `saintess_engine.run.roster.Roster` 回答；真实项目还要回答
「谁任什么职」「谁贡献了多少」「谁在等批」。这三件事在实现里各长一坨，却都只是**结构** ——
职位只认「可任表 / 上限 / 互斥 / 重复」，贡献只认「窗口 / 累计 / 排名」，
申请只认「保序 / 去重 / 上限」。把内容（职位叫什么、贡献怎么算、谁够格）拿掉，三件事都照旧成立。

**成员集合只有一个（铁律）**：本模块**不定义成员集合**，只**持有 `Roster` 引用**
（可选注入面；`self.roster is None` 即留痕）。在册判定、名单序、入册一律转发给 `Roster` ——
不复制成员表，也不在名单之外另立一份「谁在里面」。名单当下的事实变了（`join` / `leave` /
`sort_by`），三个形状看到的就跟着变。

**用法**::

    from saintess_engine.run import Roster
    from saintess_engine.membership import Applications, Contribution, RoleSlots

    r = Roster(["1001", "1002"])
    slots = RoleSlots({"lead": 1, "aide": 2}, roster=r, exclusive=True)
    dep = Contribution({}, lambda: "2026-W38", roster=r)
    q = Applications(cap=3, roster=r)

对外三件东西（细节与「有意不做的事」见各自模块）：

| 形状 | 管什么 | 口 |
|---|---|---|
| `RoleSlots` | 可任职位表 + 每职上限 + 一人一职互斥 | `can_appoint` / `appoint` / `demote` / `holders` / `role_of` |
| `Contribution` | 累计值 + 周期窗口 + 排名 | `add` / `of` / `ranking` / `rotate` |
| `Applications` | 保序 + 去重 + 容量上限 | `push` / `approve` / `reject` / `pending` / `cap_of` |

**零知识**：引擎不认任何具体职位名、周期名、申请条件；`role` / `window` / `member` /
`applicant` 的取值全由内容侧给。**边界**：不判权限、不判入会条件、不做成员集合本身
（那三件分别属内容侧、内容侧、`Roster`）。
"""
from __future__ import annotations

from .applications import Applications, QueueFull
from .contribution import Contribution
from .roles import RoleNotAllowed, RoleSlots

__all__ = [
    # 职位
    "RoleSlots", "RoleNotAllowed",
    # 贡献
    "Contribution",
    # 申请
    "Applications", "QueueFull",
]
