# -*- coding: utf-8 -*-
"""限量货架形状 —— `Shelf`（N 个格子 + 每格库存 + 两类周期：换货 / 补货）。

**为什么有它**：真实项目里「一柜子东西、每格有份数、卖完下架、过一阵换一批 / 补一批」
被写了两遍（一边是全服共享的限量柜、一边是逐件限购的柜台），两边的机制完全同构：
**一组格子 + 每格剩余份数 + 两类周期 + 售罄下架 + 先到先得**。把「摆的是什么」拿掉之后，
剩下的只有三件通用的事：**格子**（同时摆几件）、**周期**（换一批 / 补一批，到点才动）、
**取用**（够才扣、扣完下架）。本模块只做这三件，且**不跑定时器**：到点与否由外部时钟判，
由调用方在读的时候调 `ensure` 推进。

**用法**::

    from ext_economy.shelf import Shelf

    shelf = Shelf(slots=3, clock=clock, rotate_every=3600, restock_every=600,
                  fill=lambda: [{"payload": p, "stock": 2} for p in draw()])
    shelf.ensure(state)             # 读前调一次：惰性换货 / 补货（幂等）
    shelf.items(state)              # 当前在架：[{slot, left, stock, payload}, ...]
    shelf.take(state, 0, 1)         # 从 0 号格子扣 1 份；不够 → False 且不改状态
    shelf.sold_out(state)           # 已售罄（left == 0）的格子
    shelf.next_restock_at(state)    # 下次「重新变满」的时刻（秒）；不配周期 → None

**绑定由内容给**（引擎不猜）::

    * `clock() -> int` —— 外部时钟（整数秒）。引擎不读系统时间、不起线程、不注册定时器。
    * `fill() -> list` —— 生成一批新品，每个元素 `{"payload": <任意>, "stock": <非负整数>}`：
      载荷是内容侧的（引擎原样深拷贝进簿记，不解析）；`stock` 是该格子的**满额份数**
      （新上架时剩余份数 = 满额份数）。空列表 = 这次什么也没生成，引擎不替内容造东西。
    * `slots` —— 格子数；`slot` 一律是**下标**（0 起，与 `fill()` 返回列表的位置一致）。
    * `rotate_every` / `restock_every` / `keep_unsold` —— 周期与保留口径（见下）。

两类周期（都到点 → 换货优先，因为换货本身就补满）
------------------------------------------------
* **换货周期**到 → **全量重生成**：不管还没卖完的，整柜换成 `fill()` 的新品。
* **补货周期**到 → **保留未售罄 + 补满**：没售罄的格子**载荷与位置不变**、份数补回满额；
  售罄 / 空位用 `fill()` 的新品补上（按格子下标升序，取 `fill()` 返回列表的前几项，多余的忽略）。
  `keep_unsold=False` 时补货等同换货（整柜重来，换货时钟也一并推进）。
* 惰性：`ensure` 只在**到点的那一次**动作，并把时刻写成当前秒 ⇒ **同一 tick 连调两次不会重复生成**
  （不补发、不叠加）。错过的多个周期合并成一次（不追赶、不按周期次数结算）。
* 引擎**不做后台定时器**：到点判据只有 `now - 上次时刻 >= 周期`，推进只发生在 `ensure` 被调用时。

存储布局（引擎**不解析载荷、不裁剪**：读不出来就报错，不猜、不兜底）
---------------------------------------------------
`state` 是调用方给的 `MutableMapping`；引擎只在**一个键**下写自己的簿记::

    state["shelf"] = {
        "size": <格子数>,                       # 与构造时的 slots 不一致 → 报错
        "rotated_at": <秒>, "restocked_at": <秒>,
        "slots": [ {"slot": 0, "left": 1, "stock": 2, "payload": ...}, None, ... ],
    }

* 键不在（从没 `ensure` 过）—— `ensure` 就地建立；`items` / `sold_out` / `next_restock_at`
  读不到 → **fail-closed 抛 `ShelfStateError`**，绝不静默当空货架（静默 = 把「没有货架」谎报成「卖光了」）。
* 键在但取不出这份簿记（不是映射 / 缺字段 / 格子数不符 / 格子错位 / 份数为负 / 剩余大于满额）
  → `ShelfStateError`，点名位置。
* `fill()` 的产出不合契约（不是列表 / 元素不是映射 / 缺 `payload` / `stock` 非法）
  → `ShelfFillError`，点名第几个新品。
* 时钟不是整数秒 → `TypeError`；时钟倒退（`now` 早于簿记时刻）→ `ShelfStateError`。
* 格子是 `None` = **空位**（新品不够填满时会有），空位不算售罄、不占库存。

先到先得（并发口径）
--------------------
同一 `Shelf` 实例上的 `take` 由实例自带的 `threading.RLock` 串行化，「读—判—写」整段在锁内，
且 `ensure`（补货）与扣减用同一把锁 ⇒ **进程内不会超卖**、也不会与补货交错。
`take` 会先 `ensure` 到当前 tick（写入前先推进，避免拿过期货架扣库存）。
跨实例 / 跨进程共写同一份 `state` 时，引擎不假装自己是事务：**由调用方保证**
（DB 行锁 / 版本号 / 单写者）。

有意不做的事
------------
* **不认摆的是什么**：载荷对引擎是不透明对象，只做深拷贝与搬运。
* **不生成内容**：新品长什么样、几份、什么时候该有什么，全由 `fill` 给。
* **不落库、不选后端**：只读写传进来的 `state`。
* **不做定时器 / 后台任务**：到点靠 `ensure` 被调用；没有 `ensure` 就没有推进。
* **不做部分成交**：`n` 超过剩余份数 → `False` 且**一个字节都不改**（不做「先扣能扣的」）。
"""
from __future__ import annotations

import copy
import threading
from collections.abc import Mapping, MutableMapping
from typing import Callable, Optional

__all__ = ["Shelf", "ShelfFillError", "ShelfStateError"]

#: 「键不在簿记里」的哨兵 —— 与「键在但值是 None」区分开（后者是坏数据，要报错）。
_MISSING = object()

#: 引擎占用的 state 键与簿记字段名（通用名；载荷本身由内容侧定名）。
_KEY = "shelf"
_F_SIZE = "size"
_F_ROTATED = "rotated_at"
_F_RESTOCKED = "restocked_at"
_F_SLOTS = "slots"
_F_SLOT = "slot"
_F_LEFT = "left"
_F_STOCK = "stock"
_F_PAYLOAD = "payload"


class ShelfStateError(RuntimeError):
    """货架簿记读不出来 / 形态不对 —— fail-closed，绝不静默当空货架。"""


class ShelfFillError(RuntimeError):
    """`fill()` 的产出不合契约（新品列表取不出来）—— fail-closed，不猜、不降级。"""


def _is_count(value) -> bool:
    """非负整数（布尔不算 —— `True` 是 `int` 但不是份数）。"""
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0


class Shelf:
    """限量货架：N 个格子 + 每格库存 + 两类周期（换货 / 补货）。引擎不认「摆的是什么」。

    存储（`state`）与时钟（`clock`）都由内容侧注入；周期与新品生成规则也由内容侧给。
    每个格子的份数是「剩余 `left` / 满额 `stock`」两栏：`take` 扣 `left`，补货把 `left` 补回 `stock`。
    """

    def __init__(self, slots: int, *, clock: Callable[[], int],
                 rotate_every: Optional[int] = None,
                 restock_every: Optional[int] = None,
                 fill: Optional[Callable[[], list]] = None,
                 keep_unsold: bool = True) -> None:
        if isinstance(slots, bool) or not isinstance(slots, int):
            raise TypeError(f"slots 必须是整数，收到 {type(slots).__name__}：{slots!r}")
        if slots < 1:
            raise ValueError(f"slots 至少为 1，收到 {slots!r}")
        if not callable(clock):
            raise TypeError("clock 必须是可调用（收无参、返回整数秒）")
        if fill is not None and not callable(fill):
            raise TypeError(
                f"fill 必须是可调用（收无参、返回新品列表）或 None，收到 {type(fill).__name__}")
        if not isinstance(keep_unsold, bool):
            raise TypeError(f"keep_unsold 必须是 bool，收到 {type(keep_unsold).__name__}")
        self.rotate_every = self._period(rotate_every, "rotate_every")
        self.restock_every = self._period(restock_every, "restock_every")
        if fill is None and (self.rotate_every is not None or self.restock_every is not None):
            raise ValueError(
                "配了换货 / 补货周期就必须给 fill —— 到点要生成新品，引擎不替内容造东西")
        self.slots = int(slots)
        self.clock = clock
        self.fill = fill
        self.keep_unsold = keep_unsold
        self._lock = threading.RLock()
        self._now()          # 探一次：时钟取不到整数秒 → 装配即报错（不拖到第一次调用）

    # ---------------------------------------------------------------- 读
    def items(self, state: MutableMapping) -> list:
        """当前**在架**的格子快照（`left > 0`，按格子下标升序；空位与售罄都不在里面）。

        每项是 `{"slot": 下标, "left": 剩余, "stock": 满额, "payload": 载荷}` 的**深拷贝** ——
        改返回值不影响簿记。只读：**不推进周期**（推进点是 `ensure`）。
        这份 `state` 还没有货架簿记 → `ShelfStateError`（不谎报空货架）。
        """
        with self._lock:
            book = self._book(state, self._now(), missing_ok=False)
            return [copy.deepcopy(e) for e in book[_F_SLOTS]
                    if e is not None and e[_F_LEFT] > 0]

    def sold_out(self, state: MutableMapping) -> list:
        """已售罄（`left == 0`）的格子快照 —— 同样的四栏、同样按格子下标升序。

        售罄格**不在** `items` 里（下架），但仍留在簿记中直到被换货 / 补货替换。
        空位（`None`）**不算**售罄（从没上过架 ≠ 卖光了）。只读，不推进周期。
        """
        with self._lock:
            book = self._book(state, self._now(), missing_ok=False)
            return [copy.deepcopy(e) for e in book[_F_SLOTS]
                    if e is not None and e[_F_LEFT] == 0]

    def next_restock_at(self, state: MutableMapping) -> Optional[int]:
        """下一次「货架重新变满」的整数秒；一个周期都没配 → `None`。

        = 最近的一个到点时刻：补货周期配了算 `restocked_at + restock_every`，
        换货周期配了算 `rotated_at + rotate_every`（换货也是整柜变满），取二者最小。
        只读、**不代推进**：若已经到点但还没 `ensure`，返回的是那个**已过去**的时刻（不撒谎）。
        """
        with self._lock:
            book = self._book(state, self._now(), missing_ok=False)
            due = []
            if self.restock_every is not None:
                due.append(book[_F_RESTOCKED] + self.restock_every)
            if self.rotate_every is not None:
                due.append(book[_F_ROTATED] + self.rotate_every)
            return min(due) if due else None

    # ---------------------------------------------------------------- 惰性推进
    def ensure(self, state: MutableMapping) -> MutableMapping:
        """惰性校验并补货 / 换货（读时调用即可，不需要后台定时器）。返回当前货架 `state`。

        * 簿记不在 → 就地建立并按 `fill()` 上架（初始剩余 = 满额）。
        * 换货周期到 → 全量重生成（未售罄的也换掉）。
        * 否则补货周期到 → 保留未售罄 + 补满（`keep_unsold=False` 时整柜重来）。
        * 都没到点 → **一个字节都不改**（同 tick 连调两次不重复生成）。
        """
        with self._lock:
            now = self._now()
            book = self._book(state, now, missing_ok=True)
            if book is None:
                self._write(state, self._rebuilt(now))
                return state
            if self.rotate_every is not None and now - book[_F_ROTATED] >= self.rotate_every:
                self._write(state, self._rebuilt(now))
                return state
            if (self.restock_every is not None and self.keep_unsold
                    and now - book[_F_RESTOCKED] >= self.restock_every):
                self._write(state, self._restocked(book, now))
                return state
            if (self.restock_every is not None and not self.keep_unsold
                    and now - book[_F_RESTOCKED] >= self.restock_every):
                self._write(state, self._rebuilt(now))
            return state

    # ---------------------------------------------------------------- 写
    def take(self, state: MutableMapping, slot: int, n: int = 1) -> bool:
        """从 `slot` 号格子扣 `n` 份，够 → 扣掉并返回 `True`；不够 / 空位 / 已售罄 → `False` **且不改簿记**。

        扣到 `left == 0` 即**售罄下架**（从 `items` 消失，进 `sold_out`）。
        先 `ensure` 到当前 tick（写入前推进，避免拿过期货架扣库存）。
        `slot` 越界 / 非整数下标 → 报错（不静默返回 False —— 那会把「调用方传错格子」混成「没货」）；
        `n` 非整数 → `TypeError`，`n < 1` → `ValueError`。
        同一实例上的并发 `take` 由实例锁串行化（见模块头注「先到先得」）。
        """
        index = self._slot_index(slot)
        if isinstance(n, bool) or not isinstance(n, int):
            raise TypeError(f"n 必须是整数份数，收到 {type(n).__name__}：{n!r}")
        if n < 1:
            raise ValueError(f"n 至少为 1，收到 {n!r}")
        with self._lock:
            self.ensure(state)
            book = self._book(state, self._now(), missing_ok=False)
            entry = book[_F_SLOTS][index]
            if entry is None or entry[_F_LEFT] < n:
                return False
            entry[_F_LEFT] = entry[_F_LEFT] - n
            self._write(state, book)
            return True

    # ---------------------------------------------------------------- 内部：装配
    def _period(self, value, name: str) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} 必须是正整数秒或 None，收到 {type(value).__name__}：{value!r}")
        if value < 1:
            raise ValueError(f"{name} 至少为 1 秒或 None，收到 {value!r}")
        return int(value)

    def _now(self) -> int:
        value = self.clock()
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"时钟必须给整数秒，收到 {type(value).__name__}：{value!r}")
        return int(value)

    def _slot_index(self, slot) -> int:
        if isinstance(slot, bool) or not isinstance(slot, int):
            raise TypeError(
                f"slot 必须是格子下标（整数，0 起），收到 {type(slot).__name__}：{slot!r}")
        if not 0 <= slot < self.slots:
            raise ValueError(
                f"slot 越界：{slot!r}（本货架 {self.slots} 个格子，下标 0..{self.slots - 1}）")
        return int(slot)

    # ---------------------------------------------------------------- 内部：簿记
    def _book(self, state: MutableMapping, now: int, *, missing_ok: bool):
        """取出并校验簿记。`missing_ok=True` 时「键不在」返回 None，其余读出问题一律报错。"""
        if not isinstance(state, MutableMapping):
            raise TypeError(
                f"state 必须是可读写映射（get / __getitem__ / __setitem__），"
                f"收到 {type(state).__name__}")
        raw = state.get(_KEY, _MISSING)
        if raw is _MISSING:
            if missing_ok:
                return None
            raise ShelfStateError(
                f"这份 state 里没有货架簿记（键 {_KEY!r} 不在）—— 先 ensure(state) 建立货架，"
                f"拒绝把「没有货架」静默当成空货架")
        return self._read_book(raw, now)

    def _read_book(self, raw, now: int) -> dict:
        if not isinstance(raw, Mapping):
            raise ShelfStateError(f"货架簿记不是映射：{type(raw).__name__}")
        for field in (_F_SIZE, _F_ROTATED, _F_RESTOCKED, _F_SLOTS):
            if field not in raw:
                raise ShelfStateError(f"货架簿记缺字段 {field!r}")
        size = raw[_F_SIZE]
        if isinstance(size, bool) or not isinstance(size, int) or size != self.slots:
            raise ShelfStateError(
                f"簿记格子数 {size!r} 与这个货架的 slots={self.slots} 不一致"
                f"（拒绝把已有簿记按另一个 slots 重解释）")
        rotated = self._stamp(raw[_F_ROTATED], _F_ROTATED)
        restocked = self._stamp(raw[_F_RESTOCKED], _F_RESTOCKED)
        if now < rotated or now < restocked:
            raise ShelfStateError(
                f"时钟倒退：当前 {now} 早于簿记时刻（rotated_at={rotated}, "
                f"restocked_at={restocked}）—— 拒绝按错乱的时刻判周期")
        raw_slots = raw[_F_SLOTS]
        if isinstance(raw_slots, (str, bytes, bytearray)) or not isinstance(raw_slots, (list, tuple)):
            raise ShelfStateError(f"{_F_SLOTS} 必须是列表，收到 {type(raw_slots).__name__}")
        if len(raw_slots) != size:
            raise ShelfStateError(
                f"{_F_SLOTS} 长度 {len(raw_slots)} 与 size {size} 不符（簿记自相矛盾）")
        slots = [self._read_entry(entry, i) for i, entry in enumerate(raw_slots)]
        return {_F_SIZE: size, _F_ROTATED: rotated, _F_RESTOCKED: restocked, _F_SLOTS: slots}

    def _read_entry(self, entry, index: int):
        if entry is None:
            return None                       # 空位：合法（新品不够填满时会有）
        if not isinstance(entry, Mapping):
            raise ShelfStateError(f"{_F_SLOTS}[{index}] 不是映射：{type(entry).__name__}")
        for field in (_F_SLOT, _F_LEFT, _F_STOCK, _F_PAYLOAD):
            if field not in entry:
                raise ShelfStateError(f"{_F_SLOTS}[{index}] 缺字段 {field!r}")
        if entry[_F_SLOT] != index:
            raise ShelfStateError(
                f"{_F_SLOTS}[{index}] 的 slot={entry[_F_SLOT]!r} 与位置错位")
        left, stock = entry[_F_LEFT], entry[_F_STOCK]
        if not _is_count(left):
            raise ShelfStateError(f"{_F_SLOTS}[{index}].{_F_LEFT} 不是非负整数：{left!r}")
        if not _is_count(stock):
            raise ShelfStateError(f"{_F_SLOTS}[{index}].{_F_STOCK} 不是非负整数：{stock!r}")
        if left > stock:
            raise ShelfStateError(
                f"{_F_SLOTS}[{index}] 剩余 {left} > 满额 {stock}（簿记自相矛盾）")
        return {_F_SLOT: index, _F_LEFT: int(left), _F_STOCK: int(stock),
                _F_PAYLOAD: entry[_F_PAYLOAD]}

    def _stamp(self, value, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ShelfStateError(f"簿记 {name} 必须是整数秒，收到 {type(value).__name__}：{value!r}")
        return int(value)

    def _write(self, state: MutableMapping, book: dict) -> None:
        state[_KEY] = {
            _F_SIZE: book[_F_SIZE],
            _F_ROTATED: book[_F_ROTATED],
            _F_RESTOCKED: book[_F_RESTOCKED],
            _F_SLOTS: [None if e is None else dict(e) for e in book[_F_SLOTS]],
        }

    # ---------------------------------------------------------------- 内部：上架
    def _gather(self, want: int) -> list:
        """向 `fill()` 要一批新品，取前 `want` 个（已深拷贝载荷）；产出不合契约 → `ShelfFillError`。"""
        if want <= 0 or self.fill is None:
            return []
        items = self.fill()
        if isinstance(items, (str, bytes, bytearray)) or not isinstance(items, (list, tuple)):
            raise ShelfFillError(f"fill() 必须返回新品列表，收到 {type(items).__name__}")
        out = []
        for i, fresh in enumerate(items[:want]):
            if not isinstance(fresh, Mapping):
                raise ShelfFillError(f"fill() 第 {i} 个新品不是映射：{type(fresh).__name__}")
            if _F_PAYLOAD not in fresh:
                raise ShelfFillError(f"fill() 第 {i} 个新品缺 {_F_PAYLOAD!r}")
            stock = fresh.get(_F_STOCK, _MISSING)
            if stock is _MISSING:
                raise ShelfFillError(
                    f"fill() 第 {i} 个新品缺 {_F_STOCK!r}（满额份数由内容给，引擎不猜）")
            if not _is_count(stock):
                raise ShelfFillError(
                    f"fill() 第 {i} 个新品的 {_F_STOCK} 不是非负整数：{stock!r}")
            out.append({_F_SLOT: -1, _F_LEFT: int(stock), _F_STOCK: int(stock),
                        _F_PAYLOAD: copy.deepcopy(fresh[_F_PAYLOAD])})
        return out

    def _rebuilt(self, now: int) -> dict:
        """全量重生成：整柜换成新品（换货，或 `keep_unsold=False` 的补货）。"""
        fresh = self._gather(self.slots)
        slots = list(fresh) + [None] * (self.slots - len(fresh))
        for i, entry in enumerate(slots):
            if entry is not None:
                entry[_F_SLOT] = i
        return {_F_SIZE: self.slots, _F_ROTATED: now, _F_RESTOCKED: now, _F_SLOTS: slots}

    def _restocked(self, book: dict, now: int) -> dict:
        """补货：未售罄的格子位置与载荷不变、份数补回满额；空位与售罄格用新品补上。"""
        slots = [None] * self.slots
        for i, entry in enumerate(book[_F_SLOTS]):
            if entry is not None and entry[_F_LEFT] > 0:      # 售罄的算空位 → 换新品
                slots[i] = {_F_SLOT: i, _F_LEFT: entry[_F_STOCK],
                            _F_STOCK: entry[_F_STOCK], _F_PAYLOAD: entry[_F_PAYLOAD]}
        empty = [i for i, entry in enumerate(slots) if entry is None]
        for i, entry in zip(empty, self._gather(len(empty))):
            entry[_F_SLOT] = i
            slots[i] = entry
        return {_F_SIZE: self.slots, _F_ROTATED: book[_F_ROTATED],
                _F_RESTOCKED: now, _F_SLOTS: slots}
