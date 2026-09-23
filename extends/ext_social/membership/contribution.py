# -*- coding: utf-8 -*-
"""贡献账本（Contribution）—— 成员 → 累计值 + 周期窗口（日 / 周，`period_key` 由内容给）。

**形状在哪**：把「谁贡献了多少」拆成两件通用的事 —— **按窗口记账** 与 **按窗口排名**。
窗口是日是周、值是什么单位、怎么算出来的，全由内容侧给。

**窗口怎么分**：唯一的法定窗口名是 `total`（终身累计，**永不换桶**）。其余窗口名都由内容侧起
（`"day"` / `"week"` / `"season"` …），每个窗口**按 `period_key()` 分桶** —— `period_key()` 一换，
读到的就是新桶，旧值仍留在账本里等 `rotate()` 清。所以「跨窗口归零」**由 `period_key()` 决定**，
不会因为忘了调 `rotate()` 而失效（忘调只影响旧数据的清理，不影响读数的正确性）。

账本形状（**内容侧注入的 `MutableMapping`**，长这样）::

    {
      "total": {"1001": 12},                     # 终身累计：{成员: 值}
      "week":  {"2026-W38": {"1001": 4}},        # 周期窗口：{period_key: {成员: 值}}
    }

**成员集合只有一个**：本形状**不持有成员**，只持有 `Roster` 引用（可选注入面，`self.roster` 即留痕）：

* 注入了名单 → `ranking()` 的**同分顺序按名单顺序**；
* 未注入 → 同分按账本序（正是「名单为空」时那条规则的自然结果，不是另一套语义）。

两种情形都**不复制成员表**；名单外成员的账**不丢**，只是排在名单内成员之后。

**用法**::

    from ext_social.membership import Contribution

    dep = {}
    week = {"k": "2026-W38"}
    c = Contribution(dep, lambda: week["k"])
    c.add("1001", 3)                  # total += 3 → 3
    c.add("1001", 2, window="week")   # 本周 += 2 → 2
    c.of("1001")                      # 3（total）
    c.of("1001", window="week")       # 2
    c.ranking(window="week")          # [('1001', 2)]，值降序；同分按名单序
    week["k"] = "2026-W39"
    c.of("1001", window="week")       # 0 ★ 换周期即换桶（total 仍是 3）
    c.rotate()                        # 清掉非当前周期的旧桶（幂等）

**有意不做的事**
----------------
* **不算贡献**：值怎么来（做了几次、做了什么）属内容侧 —— 本形状只管记账与排名。
* **不判成员身份**：`add` 不查在册 —— 账本记的是「发生过的事」，身份由名单回答。
* **不保留历史**：`rotate()` 把旧周期的桶**清掉**，不提供「上周第几」的查询口 ——
  要留历史，请在 `rotate()` 之前自己把旧桶读走（引擎不猜你想留多久）。
* **不定义周期**：日 / 周 / 月 / 季全由 `period_key()` 的返回值说话，引擎不认日历。
"""
from __future__ import annotations

from collections.abc import Callable, MutableMapping
from typing import Optional

__all__ = ["Contribution"]

#: 终身累计窗口名：永不换桶，也是默认窗口
TOTAL = "total"


class Contribution:
    """成员 → 累计值 + 周期窗口。**可变**（值存在内容侧注入的账本里）。

    `ledger`     : 账本（可写映射，形状见模块 docstring）
    `period_key` : 当前周期标识 `() -> str`（日 / 周由内容侧定）
    `roster`     : `Roster` 引用（可选注入面；只影响 `ranking()` 的同分序）
    """

    __slots__ = ("ledger", "period_key", "roster")

    def __init__(self, ledger: MutableMapping, period_key: Callable[[], str], *,
                 roster=None) -> None:
        if not isinstance(ledger, MutableMapping):
            raise TypeError(f"ledger 必须是可写映射：{ledger!r}")
        if not callable(period_key):
            raise TypeError(f"period_key 必须是可调用对象：() -> str，收到 {period_key!r}")
        self.ledger = ledger
        self.period_key = period_key
        self.roster = roster           # 名单引用；None = 未注入（显式可查）

    # ---------------------------------------------------------------- 内部
    @staticmethod
    def _as_map(value, what: str) -> MutableMapping:
        if not isinstance(value, MutableMapping):
            raise TypeError(
                f"账本形状不符：{what} 应该是可写映射，收到 {type(value).__name__}"
                f"（拒绝静默当空账）")
        return value

    def _now(self) -> str:
        """当前周期标识。取不到 / 不是非空字符串 → 报错（不静默归零）。"""
        key = self.period_key()
        if not isinstance(key, str) or not key:
            raise TypeError(f"period_key() 必须返回非空字符串，收到 {key!r}（拒绝静默归零）")
        return key

    def _bucket(self, window: str, *, create: bool = False) -> MutableMapping:
        """取某窗口**当前周期**的桶（`total` = 终身桶）。"""
        if not isinstance(window, str) or not window:
            raise TypeError(f"window 必须是非空字符串：{window!r}")
        if window == TOTAL:
            if create:
                return self._as_map(self.ledger.setdefault(TOTAL, {}), TOTAL)
            return self._as_map(self.ledger.get(TOTAL) or {}, TOTAL)
        key = self._now()
        if create:
            periods = self._as_map(self.ledger.setdefault(window, {}), window)
            return self._as_map(periods.setdefault(key, {}), f"{window}/{key}")
        periods = self._as_map(self.ledger.get(window) or {}, window)
        return self._as_map(periods.get(key) or {}, f"{window}/{key}")

    def _roster_index(self) -> dict:
        """名单序（**实时**读 `Roster.members`，不缓存）。未注入名单 → 空表。"""
        r = self.roster
        if r is None:
            return {}
        return {m: i for i, m in enumerate(r.members)}

    # ---------------------------------------------------------------- 读写
    def add(self, member, n, *, window: str = TOTAL) -> int:
        """记一笔（可为负）。返回**加后**该窗口该成员的累计值。"""
        if isinstance(n, bool) or not isinstance(n, int):
            raise TypeError(f"n 必须是整数：{n!r}")
        member = str(member)
        bucket = self._bucket(window, create=True)
        bucket[member] = int(bucket.get(member, 0)) + n
        return bucket[member]

    def of(self, member, *, window: str = TOTAL) -> int:
        """某窗口**当前周期**的累计值（该窗口 / 该周期 / 该成员都没有 → 0）。"""
        return int(self._bucket(window).get(str(member), 0))

    def ranking(self, *, window: str = TOTAL, top: Optional[int] = None) -> list:
        """`[(成员, 值)]`，值**降序**；同分按名单序（未注入名单 → 按账本序）。`top=N` 取前 N。"""
        if top is not None:
            if isinstance(top, bool) or not isinstance(top, int):
                raise TypeError(f"top 必须是整数或 None：{top!r}")
            if top < 0:
                raise ValueError(f"top 不能为负：{top}")
        bucket = self._bucket(window)
        order = {m: i for i, m in enumerate(bucket)}      # 账本序（同分时的兜底）
        rank = self._roster_index()
        missing = len(rank)                               # 名单外成员统一排在名单内之后
        members = sorted(bucket, key=lambda m: (-int(bucket[m]), rank.get(m, missing), order[m]))
        if top is not None:
            members = members[:top]
        return [(m, int(bucket[m])) for m in members]

    def rotate(self) -> None:
        """**归档**：清掉所有非 `total` 窗口里不属于当前周期的桶（幂等；旧值不并入 total）。"""
        now = self._now()
        for window in list(self.ledger):
            if window == TOTAL:
                continue
            periods = self._as_map(self.ledger.get(window) or {}, window)
            for period in [p for p in periods if p != now]:
                periods.pop(period, None)
