# -*- coding: utf-8 -*-
"""职位槽（RoleSlots）—— 可任职位表 + 每职人数上限 + 一人一职互斥开关。

**形状在哪**：真实项目里「谁任什么职」通常长成一个散在各处的 `role` 字段，再配几处
`if 人数 < 上限` 的手写判断。把**职位叫什么**拿掉，只剩四件通用的事 ——
**可任表**（哪些职位存在、各几人）、**上限**、**互斥**（一人能否兼多职）、**在册**（人得先在里面）。

**成员集合只有一个**：本形状**不持有成员**，只持有 `Roster` 引用（`roster`）。
「在册」问 `Roster.is_member`，「谁先谁后」问 `Roster.members` 的**现序** —— 不复制、不缓存成员表。
`roster` 是**可选注入面**（与 `LootTable(resolver=None)` 同惯例），`self.roster is None` 即留痕：

* 注入了名单 → 在册 / 占槽 / `holders()` 顺序，一律以**名单当下的事实**为准；
* 未注入 → 退化成**纯槽位表**（不判在册、`holders()` 按任命序）。这一退化是**显式**的
  （`self.roster` 可查），不是把错吞掉。

**用法**::

    from saintess_engine.run import Roster
    from saintess_engine.membership import RoleNotAllowed, RoleSlots

    r = Roster(["1001", "1002"])
    slots = RoleSlots({"lead": 1, "aide": 2}, roster=r, exclusive=True)
    slots.can_appoint("1001", "lead", r)      # True：在册 / 未满 / 不互斥 / 未任该职
    slots.appoint("1001", "lead")
    slots.appoint("1002", "aide")
    slots.role_of("1001")                     # 'lead'
    slots.holders("aide")                     # ['1002']（按名单顺序）
    slots.appoint("1002", "lead")             # → RoleNotAllowed（exclusive：已在任 aide）
    slots.appoint("1001", "lead")             # 幂等：已是该职，不抛、不重复计
    slots.demote("1001"); slots.role_of("1001")   # None

**有意不做的事**
----------------
* **不判「能不能任」**：条件与权限（够不够格、谁有权批）属内容侧 ——
  本形状只判四件结构事：可任表 / 上限 / 互斥 / 重复。
* **不定义职位**：职位名与每职人数全由内容侧给，引擎里没有一个内置职位名。
* **不订阅名单变更**：成员 `leave()` 不会自动撤其任命；离册者**不再占槽**、也不出现在
  `holders()`（占槽与顺序都按名单实时算），但任命记录仍在 —— 要清就 `demote()`。
* **不做「换届 / 免职 / 辞职」的区分**：`demote()` 只有一件事 —— 清掉该成员当前的职位（幂等）。
"""
from __future__ import annotations

from typing import Mapping, Optional

__all__ = ["RoleNotAllowed", "RoleSlots"]


class RoleNotAllowed(RuntimeError):
    """任命不合规：不在可任表 / 不在册 / 该职已满 / 与在任职位互斥。"""


class RoleSlots:
    """可任职位表 + 每职人数上限 + 互斥开关。**可变**。

    `roles` : `{职位: 人数上限}`（上限 0 = 该职谁都不能任）
    `roster`: `Roster` 引用（可选注入面；不复制成员，见模块 docstring）
    `exclusive`: `True` = 一人至多一职（已在任其它职位时不能再任）
    """

    __slots__ = ("_caps", "_assign", "exclusive", "roster")

    def __init__(self, roles: Mapping[str, int], *, roster=None, exclusive: bool = False) -> None:
        caps: dict = {}
        for role, cap in dict(roles or {}).items():
            if not isinstance(role, str) or not role:
                raise ValueError(f"职位名必须是非空字符串：{role!r}")
            if isinstance(cap, bool) or not isinstance(cap, int):
                raise TypeError(f"职位 {role!r} 的人数上限必须是整数：{cap!r}")
            if cap < 0:
                raise ValueError(f"职位 {role!r} 的人数上限不能为负：{cap}")
            caps[role] = cap
        self._caps = caps
        self._assign: dict = {}        # 成员 → 职位（只是任命记录，不是成员集合）
        self.roster = roster           # 名单引用；None = 未注入（显式可查，见模块 docstring）
        self.exclusive = bool(exclusive)

    # ---------------------------------------------------------------- 内部
    def _roster_of(self, roster=None):
        """本次判定用哪份名单：显式传入 > 构造时绑定 > None（未注入 = 不判在册）。"""
        return roster if roster is not None else self.roster

    def _holders_of(self, role: str, roster) -> list:
        """任该职的人：注入了名单按**名单序**，否则按任命序。"""
        if roster is None:
            return [m for m, r in self._assign.items() if r == role]
        return [m for m in roster.members if self._assign.get(m) == role]

    # ---------------------------------------------------------------- 判定
    def can_appoint(self, member, role, roster=None) -> bool:
        """能不能任命：**在可任表** + **未满** + **不互斥** + **不是已任该职**。

        * `roster` 给了就用它，否则用构造时绑定的那份；两份都没有 = 不判在册（纯槽位表）
        * **已是该职 → False**（不把「重复任命」算成「可以再任一次」）；`appoint` 对此是幂等空操作
        * 未知职位 → False（可任表之外没有职位）
        """
        member, role = str(member), str(role)
        if role not in self._caps:
            return False
        use = self._roster_of(roster)
        if use is not None and not use.is_member(member):
            return False
        holding = self._assign.get(member)
        if holding == role:
            return False
        if holding is not None and self.exclusive:
            return False
        return len(self._holders_of(role, use)) < self._caps[role]

    # ---------------------------------------------------------------- 变更
    def appoint(self, member, role) -> None:
        """任命。不合规 → `RoleNotAllowed`；**已是该职 → 幂等**（不抛、不重复计）。"""
        member, role = str(member), str(role)
        if self._assign.get(member) == role:
            return
        if not self.can_appoint(member, role):
            raise RoleNotAllowed(
                f"不能任命：成员 {member!r} → 职位 {role!r}"
                f"（可任表={sorted(self._caps)}，在册={self.roster is not None}，互斥={self.exclusive}）")
        self._assign[member] = role

    def demote(self, member) -> None:
        """清掉该成员当前的职位（本就不任任何职 → 空操作，幂等）。"""
        self._assign.pop(str(member), None)

    # ---------------------------------------------------------------- 查询
    def holders(self, role) -> list:
        """任该职的成员（**按名单顺序**；未注入名单 → 按任命序）。未知职位 → []。"""
        role = str(role)
        if role not in self._caps:
            return []
        return self._holders_of(role, self.roster)

    def role_of(self, member) -> Optional[str]:
        """该成员当前的职位；不任任何职 / 不在任命记录里 → None。"""
        return self._assign.get(str(member))
