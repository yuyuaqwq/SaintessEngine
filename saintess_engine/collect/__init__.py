# -*- coding: utf-8 -*-
"""收集形状 —— **N/M 进度** + **档位领取状态机**（引擎零知识）。

**为什么有它**：真实项目里两类「收集」几乎同构 ——
① 一份**条目表** + 一条「这条算不算已有」的判据 → 「已收集 N / 共 M」；
② 一份**档位表** + 「这一档达成了吗 / 领过没有」→ 每档三态（未达成 / 可领 / 已领）。
把内容（条目是什么、判据怎么算、档位有几个）拿掉，只剩两件形状：**计数**、**三态**。

**引擎零知识**：引擎不认「条目 / 档位」是什么，只认不透明字符串标识与调用方给的判据。
判据（`hit` / `reached` / `claimable`）一律由调用方以回调注入；引擎不读表、不落盘、不缓存
—— 每次读现算（同一对象上的重复读不保证同值，因为世界可能已经变了）。

**已领集合由调用方注入**：`claimed` 是一个**可变集合**（引擎只做 `in` 与 `add`），
它可以是内存集合，也可以是存档层给的活集合；引擎不落盘。

**用法**::

    from saintess_engine.collect import CLAIMED, LOCKED, READY, Tally, TierBoard, tier_state

    t = Tally(rows, hit=lambda row: row["key"] in owned)
    t.got, t.total, t.done          # 2, 5, False
    t.progress()                    # (2, 5)

    board = TierBoard(tiers, claimed=claimed_set,
                      key=lambda tier: tier["key"],
                      reached=lambda tier: owned_score >= tier["need"],
                      claimable=lambda tier: bool(tier.get("reward")))
    board.state(tiers[0])           # LOCKED / READY / CLAIMED
    board.ready()                   # 可领档位（**声明序**）
    board.pending()                 # 可领档数
    board.claim(tiers[0])           # READY → True（并记入 claimed_set）；否则 False（幂等）

**口径分歧（有意，不许「顺手统一」）**
--------------------------------------
1. **三态里没有第四态「达成但没东西可领」**：达成、没领过、但**没有可领之物**的档位
   算 `CLAIMED`。理由：这种档位永远不会再有东西可领，若算 `READY`，面板会永久显示「有奖励待领」、
   领取入口每次都给「没有可领的东西」——那是搬运前包内实现已经用「落库成已领」规避掉的坑。
2. **「未达成」优先于「已领」**：达成判据为假、已领集合里却有它（自相矛盾的两份存档输入）时
   算 `LOCKED`，不算 `CLAIMED`。「达成」是关于世界的事实，先判它；这也是搬运前包内实现
   `"✅" if 已解锁 else "⬜"` 的逐字口径（已领集合只用来把 ✅ 改写成 🎁 的条件之一）。
3. **`Tally.done` 对空表为 `True`**（`0 == 0`）：与本形状搬运前的包内判定
   `"✅" if got == total else "⬜"` 逐字同口径（空册 / 空分类显示为已完成）。
   要「非空才算完成」的调用方自己加 `total > 0`。
4. **`ready()` 保声明序**：档位在表里的顺序是展示顺序，本形状不排序、不去重。

**为什么要新造（而不是复用 `run.Progress`）**
--------------------------------------------
`run.Progress` 管的是「有序节点 + 每节点剩余池 + 资源预算 + 当前位置」——
是「一趟有多站、每站还剩什么」的**运行进度**；本形状管的是「一共该收集多少、现在有几个」
与「档位达成了没有、领过没有」，没有节点、没有池、没有预算、没有当前位置。
两者形状不同（`run.Progress.done` 是「所有池都空」，本形状 `done` 是「命中数 == 总数」），
故不合并；`run.Progress` 一字未动。

**有意不做的事**
----------------
* **不落盘**：`claimed` 是调用方给的集合，持久化在存档层。
* **不判「达成」**：`reached` / `hit` / `claimable` 全是注入回调（引擎不认门槛与奖励形态）。
* **不排序 / 不去重 / 不校验档位合法**：引擎只按声明序走一遍。
* **不发号 / 不校验奖励**：领取只做「三态迁移 + 记入集合」，发什么由调用方决定。
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

__all__ = ["CLAIMED", "LOCKED", "READY", "Tally", "TierBoard", "tier_state"]

#: 档位三态（通用英文标识；中文措辞由内容侧映射）
LOCKED = "locked"
READY = "ready"
CLAIMED = "claimed"


def _callable_of(fn: Any, label: str) -> Callable:
    if not callable(fn):
        raise TypeError(f"{label} 必须可调用，收到 {type(fn).__name__}")
    return fn


def _id_of(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} 必须返回字符串标识，收到 {type(value).__name__}：{value!r}")
    if not value.strip():
        raise ValueError(f"{label} 返回空标识 —— 拒绝落到无名档位上")
    return value


# ───────────────────────────────────────────────────────── N/M 进度
class Tally:
    """N/M 进度：一串条目 + 一条「这条算数吗」的判据。**构造即绑定，读时现算**（不缓存）。

    * `total` / `got` / `left` —— 总数 / 命中数 / 未命中数
    * `done` —— `got == total`（空表也算 `done`，见模块头「口径分歧 ②」）
    * `progress()` —— `(got, total)`，便于原样喂给「N/M」渲染
    """

    __slots__ = ("_rows", "_hit")

    def __init__(self, rows: Iterable = (), hit: Callable[[Any], bool] = None) -> None:
        self._hit = _callable_of(hit, "hit（hit(row) -> bool）")
        self._rows = tuple(rows or ())

    @property
    def rows(self) -> tuple:
        return self._rows

    @property
    def total(self) -> int:
        return len(self._rows)

    @property
    def got(self) -> int:
        return sum(1 for row in self._rows if self._hit(row))

    @property
    def left(self) -> int:
        return self.total - self.got

    @property
    def done(self) -> bool:
        return self.got == self.total

    def progress(self) -> tuple:
        """`(已命中数, 总数)`。"""
        return (self.got, self.total)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"Tally({self.got}/{self.total}, done={self.done})"


# ───────────────────────────────────────────────────────── 档位三态
def tier_state(reached: bool, claimed: bool, claimable: bool = True) -> str:
    """档位三态：未达成 → `LOCKED`；已领（或达成但没有可领之物）→ `CLAIMED`；达成待领 → `READY`。

    「达成但没有可领之物」按 `CLAIMED` 算是本形状的**口径选择**，理由见模块头「口径分歧 ①」。
    「未达成」优先于「已领」：两者自相矛盾时（已领集合里有、达成判据为假）按 `LOCKED` 算
    —— 「达成」是关于世界的事实，先判它；见模块头「口径分歧 ②」。
    """
    if not reached:
        return LOCKED
    if claimed:
        return CLAIMED
    return READY if claimable else CLAIMED


class TierBoard:
    """档位领取状态机：档位声明序 + 已领集合 + 三个注入判据。

    * `tiers` —— 档位序列（顺序 = 展示 / 遍历序，引擎不排序）
    * `claimed` —— **可变集合**：已领档位的标识集合（引擎只做 `in` / `add`，不落盘）
    * `key(tier) -> str` —— 档位标识（引擎不认字段名，标识由调用方取）
    * `reached(tier) -> bool` —— 该档是否达成（门槛 / 条件由调用方判）
    * `claimable(tier) -> bool` —— 该档达成后是否有可领之物（缺省恒 True）

    公开面：`state` / `states` / `ready` / `pending` / `counts` / `claim`。
    """

    __slots__ = ("_tiers", "_claimed", "_key", "_reached", "_claimable")

    def __init__(self, tiers: Iterable = (), *, claimed, key: Callable[[Any], str],
                 reached: Callable[[Any], bool],
                 claimable: Callable[[Any], bool] = None) -> None:
        for name in ("__contains__", "add"):
            if not callable(getattr(claimed, name, None)):
                raise TypeError(
                    f"claimed 必须是可变标识集合（缺 {name}）—— 拿不到注入面就 fail-closed，"
                    f"不要传 None/半个壳：{type(claimed).__name__}")
        self._tiers = tuple(tiers or ())
        self._claimed = claimed
        self._key = _callable_of(key, "key（key(tier) -> 档位标识）")
        self._reached = _callable_of(reached, "reached（reached(tier) -> bool）")
        self._claimable = ((lambda tier: True) if claimable is None
                           else _callable_of(claimable, "claimable（claimable(tier) -> bool）"))

    @property
    def tiers(self) -> tuple:
        return self._tiers

    @property
    def claimed(self):
        """已领集合（调用方注入的那一个，活引用）。"""
        return self._claimed

    def id_of(self, tier) -> str:
        """档位标识（校验非空字符串）。"""
        return _id_of(self._key(tier), "key(tier)")

    def state(self, tier) -> str:
        """该档三态（每次现算，不看缓存）。"""
        ident = self.id_of(tier)
        return tier_state(reached=bool(self._reached(tier)),
                          claimed=ident in self._claimed,
                          claimable=bool(self._claimable(tier)))

    def states(self) -> dict:
        """`{档位标识: 三态}`（声明序）。"""
        return {self.id_of(t): self.state(t) for t in self._tiers}

    def ready(self) -> list:
        """可领档位清单（**声明序**）。"""
        return [t for t in self._tiers if self.state(t) == READY]

    def pending(self) -> int:
        """可领档位数（= `len(ready())`）。"""
        return sum(1 for t in self._tiers if self.state(t) == READY)

    def counts(self) -> dict:
        """三态计数 `{locked, ready, claimed}`。"""
        out = {LOCKED: 0, READY: 0, CLAIMED: 0}
        for t in self._tiers:
            out[self.state(t)] += 1
        return out

    def claim(self, tier) -> bool:
        """**幂等领取**：`READY` → 记入 `claimed`（就地在调用方集合上）并返回 `True`。

        其余三态一律 `False` **且不碰 `claimed`**：已领（重领）、未达成（够不着）、
        无物可领（了结）都不会被记成已领 —— 「不可重领」由这一条保证。
        """
        if self.state(tier) != READY:
            return False
        self._claimed.add(self.id_of(tier))
        return True
