# -*- coding: utf-8 -*-
"""交易形状 —— 每日限购 / 成交结算 / 折价换算（引擎零知识）。

**为什么有它**：交易类实现在真实项目里常把三件通用的事和内容焊在一起 ——
「今天已经拿了几次」「这一次成交实收多少」「按折价率换算出的单价是多少」。
把内容（key 代表什么、定价怎么算、日限配几个）拿掉，只剩三件形状：
**计数**、**结算**、**换算**。

**用法**::

    from ext_economy.trade import DailyLimit, DailyLimitExceeded, apply_rate, settle_sale

    state = {}                                        # 存档层给的映射（引擎不落盘）
    limit = DailyLimit(state, today=lambda: "2026-01-01", namespace="limit")
    limit.used("k")                                   # 0（没记过 = 0）
    limit.consume("k", 2, cap=3)                      # 2（当日已计数，返回新的已用数）
    limit.remaining("k", 3)                           # 1
    try:
        limit.consume("k", 2, cap=3)                  # 超上限 → 抛，且 state 不改
    except DailyLimitExceeded:
        pass
    limit.reset()                                     # 跨日清理（幂等，返回清掉几条）

    unit = apply_rate(100, rate=0.85, discount=1.0)   # 85 = round(100×0.85×1.0)，不低于 floor
    low = apply_rate(7, rate=0.85, mode="trunc", floor=None)   # 5 = int(7×0.85)，不设下界
    r = settle_sale(3, unit, tax=0.0, floor=0, on_change=wallet.add)
    r.gross, r.tax, r.net                             # 255, 0, 255

**零知识**：引擎不认「什么 key」「今天是哪天」「限几个」「折多少」——
`state` 映射、`today` 回调、`key`、`cap`、比率与下限全部由内容侧给；
本模块不认商品、不写钱包与背包、不落盘。

**有意不做的事**
----------------
* **不碰钱包/背包**：结算只算数并回调一次 `on_change(net)`，谁收款、谁扣件是内容的事。
* **不发号、不生成实例标识**：`key` 由内容侧给（引擎只把它拼进当日计数键）。
* **不判「今天」**：日历日由注入的 `today()` 决定（同一天怎么算，是内容/宿主的事）。
* **不做定价**：折价率、折扣、取整方式与下界由调用方给；本模块只做一次乘算与一次取整。
* **不落盘**：`state` 是调用方给的映射，持久化在存档层。
* **不留旧口径别名**：语义只有一种（超上限抛 `DailyLimitExceeded`）。
"""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import NamedTuple

from saintess_engine._validators import int_of

__all__ = ["DailyLimit", "DailyLimitExceeded", "SaleResult", "apply_rate", "settle_sale"]


# ───────────────────────────────────────────────────────── 每日限购计数
class DailyLimitExceeded(RuntimeError):
    """当日计数超出上限（`cap`）。"""


class DailyLimit:
    """按「当日标识 + key」计数；**跨日自动归零**（当日标识写在键里）。

    计数表形如 ``{f"{namespace}:{today}:{key}": n}`` —— 键由本类拼，值恒为非负整数。
    取「今天」只经注入的 `today()` 回调；引擎不认识日历日，也不认识 key 是什么。

    * `used(key)`          当日已计数（没记过 = 0）
    * `remaining(key, cap)` 当日剩余额度（不足 0 时给 0）
    * `consume(key, n=1, cap=…)` 记一笔；超 `cap` → `DailyLimitExceeded`（**不改 state**）；
      不传 `cap` 不判上限（「不限购」= 调用方不传上限）
    * `reset(key=None)`     跨日清理（幂等）：`key=None` 清掉**非今日**的残留；
      给了 `key` 则清该 key 的全部计数（含旧日残留）
    """

    __slots__ = ("_state", "_today", "_namespace")

    def __init__(self, state: MutableMapping, today, *, namespace="limit") -> None:
        if not isinstance(namespace, str) or not namespace:
            raise ValueError(f"namespace 必须是非空字符串，收到 {namespace!r}")
        if ":" in namespace:
            raise ValueError(f"namespace 不能含冒号（键结构是 namespace:today:key）：{namespace!r}")
        if not callable(today):
            raise TypeError("today 必须可调用（返回当日标识字符串），引擎不自己取日历日")
        if not isinstance(state, MutableMapping):
            raise TypeError(f"state 必须是可变映射（MutableMapping），收到 {type(state).__name__}")
        self._state = state
        self._today = today
        self._namespace = namespace

    # ------------------------------------------------------------ 读
    @property
    def namespace(self) -> str:
        return self._namespace

    def _today_id(self) -> str:
        """当日标识：非空、不含冒号的字符串（否则当日计数键有歧义 → 显式报错）。"""
        day = self._today()
        if not isinstance(day, str) or not day or ":" in day:
            raise ValueError(f"today() 必须返回不含冒号的非空字符串，收到 {day!r}")
        return day

    def key_of(self, key) -> str:
        """当日计数键：``{namespace}:{today}:{key}``（key 里允许出现冒号）。"""
        return self._store_key(key)

    def _store_key(self, key) -> str:
        return f"{self._namespace}:{self._today_id()}:{key}"

    @staticmethod
    def _as_count(raw, store_key: str) -> int:
        """计数读口：缺项 = 0；非整数/负数 = 存档坏了 → 显式报错（不静默当 0）。"""
        if raw is None:
            return 0
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ValueError(f"当日计数不是整数：{raw!r}")
        if raw < 0:
            raise ValueError(f"当日计数为负：{raw!r}")
        return raw

    def _used_at(self, store_key: str) -> int:
        return self._as_count(self._state.get(store_key), store_key)

    def used(self, key) -> int:
        """当日该 key 已计数（没记过 = 0）。"""
        return self._used_at(self._store_key(key))

    def remaining(self, key, cap: int) -> int:
        """当日剩余额度 = max(0, cap - used)。"""
        return max(0, int_of(cap, "cap", minimum=0) - self.used(key))

    # ------------------------------------------------------------ 写
    def consume(self, key, n: int = 1, *, cap=None) -> int:
        """记一笔 `n`，返回记完后的当日已用数。

        * 传了 `cap` 且 `已用 + n > cap` → `DailyLimitExceeded`（**先判后写**，state 不变）
        * 不传 `cap` → 不判上限
        """
        n = int_of(n, "n", minimum=1)
        limit = None if cap is None else int_of(cap, "cap", minimum=0)
        store_key = self._store_key(key)          # 当日标识只取一次（中途不换日）
        used = self._used_at(store_key)
        if limit is not None and used + n > limit:
            raise DailyLimitExceeded(
                f"当日上限 {limit}：已用 {used}，本次 {n}（key={key!r}）")
        self._state[store_key] = used + n
        return used + n

    def reset(self, key=None) -> int:
        """跨日清理（幂等），返回清掉几条。

        * `key=None`：删掉本命名空间里所有**不属于今日**的计数（今日计数保留）
        * 给了 `key`：删掉该 key 的计数（含旧日残留）—— 「把这一项重来」

        本命名空间里键结构不合规（不是 `namespace:today:key`）→ 显式报错。
        """
        prefix = self._namespace + ":"
        today = self._today_id()
        want = None if key is None else str(key)
        removed = 0
        for store_key in list(self._state):
            if not isinstance(store_key, str) or not store_key.startswith(prefix):
                continue
            day, sep, rest = store_key[len(prefix):].partition(":")
            if not sep or not day:
                raise ValueError(
                    f"state 里有本命名空间的坏键：{store_key!r}"
                    f"（应为 {{namespace}}:{{today}}:{{key}}）")
            if (want is None and day != today) or (want is not None and rest == want):
                del self._state[store_key]
                removed += 1
        return removed


# ───────────────────────────────────────────────────────── 成交结算
class SaleResult(NamedTuple):
    """一次成交的明细（引擎只算数，不收付款）。"""

    qty: int
    unit_price: int
    gross: int
    tax: int
    net: int


def settle_sale(qty, unit_price, *, tax=0.0, floor=0, on_change=None) -> SaleResult:
    """一次成交的形状：算毛额 → 扣税 → 调回调 → 返回明细。

    * `gross = qty × unit_price`；`tax` 是**比率**（0.05 = 5%），税额 = `round(gross × tax)`
    * `net = max(floor, gross - 税额)`；`floor` 是净额下限（默认 0）
    * `on_change(net)` **恰好调一次**（在明细返回之前；本函数不碰钱包/背包）
    * `qty <= 0` → `ValueError`；`net <= 0` = 无成交（与「单价为 0/负」同判据），
      调用方据此不放款 —— 引擎不替内容侧决定要不要提示

    取整约定：税额与本模块 `apply_rate` 同一口径（`round`，即四舍六入五成双）。
    """
    if isinstance(qty, bool) or not isinstance(qty, int):
        raise TypeError(f"qty 必须是整数，收到 {qty!r}")
    if qty <= 0:
        raise ValueError(f"qty 必须为正，收到 {qty!r}")
    if isinstance(unit_price, bool) or not isinstance(unit_price, int):
        raise TypeError(f"unit_price 必须是整数，收到 {unit_price!r}")
    if isinstance(floor, bool) or not isinstance(floor, int):
        raise TypeError(f"floor 必须是整数，收到 {floor!r}")
    if floor < 0:
        raise ValueError(f"floor 不能为负，收到 {floor!r}")
    if isinstance(tax, bool) or not isinstance(tax, (int, float)):
        raise TypeError(f"tax 必须是数值（比率，0.05 = 5%），收到 {tax!r}")
    tax_rate = float(tax)
    if tax_rate < 0:
        raise ValueError(f"tax 不能为负，收到 {tax!r}")

    gross = qty * unit_price
    tax_amount = int(round(gross * tax_rate))
    net = max(floor, gross - tax_amount)
    if on_change is not None:
        if not callable(on_change):
            raise TypeError("on_change 必须可调用：on_change(net)")
        on_change(net)
    return SaleResult(qty, unit_price, gross, tax_amount, net)


# ───────────────────────────────────────────────────────── 折价换算
def apply_rate(price, *, rate=1.0, discount=1.0, floor=1, mode="round") -> int:
    """折价/折扣换算：`price × rate × discount` 按 `mode` 取整，不低于 `floor`。

    `rate`（折价率）与 `discount`（折扣）都是乘性系数，分开放是为了让调用处读得懂
    「回收折价」和「活动折扣」是两件事；引擎不规定它们的来源与取值范围。

    * `mode="round"`（默认）：四舍六入五成双（同本模块 `settle_sale` 的税额口径）
    * `mode="trunc"`：向零截断（等价 `int(price × rate × discount)`；负值也向零）
    * `floor`：整数下界，默认 1（小额条目不被折成 0）；显式传 `None` = **不施加下界**，
      返回值可能就是 0 或负，怎么处理由调用方定
    """
    if isinstance(price, bool) or not isinstance(price, int):
        raise TypeError(f"price 必须是整数，收到 {price!r}")
    if floor is not None:
        if isinstance(floor, bool) or not isinstance(floor, int):
            raise TypeError(f"floor 必须是整数，收到 {floor!r}")
        if floor < 0:
            raise ValueError(f"floor 不能为负，收到 {floor!r}")
    if mode not in ("round", "trunc"):
        raise ValueError(f"mode 必须是 'round' 或 'trunc'，收到 {mode!r}")
    scaled = price * float(rate) * float(discount)
    value = int(round(scaled)) if mode == "round" else int(scaled)
    if floor is None:
        return value
    return max(floor, value)
