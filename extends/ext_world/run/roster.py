# -*- coding: utf-8 -*-
"""名单（Roster）—— 有序成员 + 队长 + 存活表 + 过滤/排序。

**为什么有它**：一个「谁在里面」的集合，在真实项目里表现为散落在各处的
`members` / `alive` 两个字段，被反复读、反复过滤（在场吗 / 还活着吗 / 谁先动），
而「队长」又暗中决定了很多分支。把成员是什么人拿掉，只剩四件通用的事 ——
**保序**、**队长**、**存活**、**过滤与排序**。

**用法**::

    from ext_world.run import Roster

    r = Roster(["1001", "1002"], leader="1001")
    r.members                 # ['1001', '1002']（顺序 = 行动序，由内容侧定）
    r.leader                  # '1001'
    r.alive("1002")           # True（未登记的成员视为存活）
    r.mark_dead("1002"); r.living()            # ['1001']
    r.keep(lambda m: m in party)               # 在场过滤（保序）
    r.only(["1002", "1001"])                   # 取子集（按 members 原序）
    r.sort_by(lambda m: spd[m], reverse=True)  # 原位重排
    r.join("1003"); r.leave("1001")            # 追加（幂等）/ 移除
    r.to_dict(); Roster.from_dict(d)

**零知识**：引擎不认「队伍」「队长」「玩家」，只认 `member` / `leader` / `alive`；
成员 key、顺序依据、在场判据全由内容侧给（谓词/函数）。

**顺序是内容**：`sort_by` 只负责「按你给的键重排」，键（速度？等级？加入时间？）
是内容侧的事；本形状不猜。
"""
from __future__ import annotations

from typing import Callable, Iterable

__all__ = ["Roster"]


class Roster:
    """有序成员 + 队长 + 存活表。**可变**。"""

    __slots__ = ("members", "leader", "_alive", "_default_alive")

    def __init__(self, members: Iterable = (), *, leader=None, alive=None,
                 default_alive: bool = True) -> None:
        self.members = [str(m) for m in (members or ())]
        self.leader = str(leader) if leader is not None else (self.members[0] if self.members else None)
        self._default_alive = bool(default_alive)
        self._alive = {str(k): bool(v) for k, v in dict(alive or {}).items()}

    # ---------------------------------------------------------------- 基本
    def __len__(self) -> int:
        return len(self.members)

    def __iter__(self):
        return iter(self.members)

    def __contains__(self, k) -> bool:
        return str(k) in self.members

    def is_member(self, k) -> bool:
        return str(k) in self.members

    def index_of(self, k) -> int:
        """成员位置；不在名单 → -1。"""
        k = str(k)
        try:
            return self.members.index(k)
        except ValueError:
            return -1

    # ---------------------------------------------------------------- 存活
    def alive(self, k) -> bool:
        """是否存活；**未登记 = 存活**（缺字段不是死亡）。"""
        return bool(self._alive.get(str(k), self._default_alive))

    def set_alive(self, k, value: bool = True) -> bool:
        self._alive[str(k)] = bool(value)
        return bool(value)

    def mark_dead(self, k) -> bool:
        return self.set_alive(k, False)

    def revive(self, k) -> bool:
        return self.set_alive(k, True)

    @property
    def alive_map(self) -> dict:
        return {k: self.alive(k) for k in self.members}

    def any_alive(self) -> bool:
        return any(self.alive(k) for k in self.members)

    # ---------------------------------------------------------------- 过滤
    def living(self) -> list:
        """存活成员（保序）。"""
        return [k for k in self.members if self.alive(k)]

    def keep(self, pred: Callable) -> list:
        """按谓词过滤（保序）→ 新列表。谓词收 `member`。"""
        return [k for k in self.members if pred(k)]

    def only(self, keys: Iterable) -> list:
        """取子集（**按 members 原序**，不是传入序）—— 与「过滤当前仍在场者」同语义。"""
        want = {str(k) for k in (keys or ())}
        return [k for k in self.members if k in want]

    def sort_by(self, keyfunc: Callable, *, reverse: bool = True) -> "Roster":
        """按内容侧给的键**原位**重排；返回 self（便于链式）。"""
        self.members.sort(key=keyfunc, reverse=reverse)
        return self

    # ---------------------------------------------------------------- 增删
    def join(self, k) -> bool:
        """追加成员（已在 → False，幂等）。"""
        k = str(k)
        if k in self.members:
            return False
        self.members.append(k)
        return True

    def leave(self, k) -> bool:
        """移除成员（不在 → False）。队长离队 → 队长顺位给剩下第一个（空名单 → None）。"""
        k = str(k)
        if k not in self.members:
            return False
        self.members.remove(k)
        self._alive.pop(k, None)
        if self.leader == k:
            self.leader = self.members[0] if self.members else None
        return True

    # ---------------------------------------------------------------- 往返
    def to_dict(self) -> dict:
        return {"members": list(self.members), "leader": self.leader,
                "alive": {k: v for k, v in self._alive.items()}}

    @classmethod
    def from_dict(cls, data, **kw) -> "Roster":
        d = dict(data or {})
        return cls(d.get("members") or (), leader=d.get("leader"), alive=d.get("alive"), **kw)

    # ---------------------------------------------------------------- 审计
    def audit(self):
        """结构自检 → 问题列表（空列表 = 干净）。只报不改。"""
        problems = []
        if len(set(self.members)) != len(self.members):
            problems.append("成员重复")
        if self.members and self.leader is None:
            problems.append("有成员但没有队长")
        if self.leader is not None and self.leader not in self.members:
            problems.append(f"队长不在名单里：{self.leader}")
        for k in self._alive:
            if k not in self.members:
                problems.append(f"存活表里有名单外成员：{k}")
        return problems

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"Roster(members={len(self.members)}, leader={self.leader!r}, alive={len(self.living())})"
