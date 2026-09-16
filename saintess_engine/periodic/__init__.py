# -*- coding: utf-8 -*-
"""周期形状 —— 周期键上的计数 / 上限 / 首次触达 / 连续段 / 冷却（引擎零知识）。

**为什么有它**：同一套「周期」语义在真实项目里常被手写好几遍 —— 限额键一套、状态键一套、
末次触达时间戳又一套：键怎么拼、上限怎么判、跨周期怎么归零、断了怎么重数，
散在多个文件里各写各的。把内容（周期怎么算、键长什么样、限几个、冷却多久）拿掉，
只剩四件形状：**计数**、**首次触达**、**连续段**、**冷却**。

**引擎不认识日历**：「现在是哪个周期」「紧邻的上一个周期是哪个」都由调用方以
**周期键字符串**注入 —— 本模块不 import 任何时间/日期库，也不读钟（`now` 一律由调用方传）。
键格式（前缀、分隔符、大小写）**完全由调用方拼**，引擎只当不透明字符串：
于是「把同一套周期语义抽进引擎」不会改动任何一处存档键。

**存储由调用方注入**：`read(key) -> 原始值` 与 `write(key, value) -> None` 一对可调用
就是全部存储面（文本列 / 字典 / 事件状态表都行）。引擎不落盘、不缓存 —— 每次都现读现算；
「换周期」= 换键，新键天然为空，**没有跨周期清理这回事**。

**用法**::

    from saintess_engine.periodic import PeriodCounter, PeriodSlot, Streak, Cooldown

    n = PeriodCounter(state.get, state.__setitem__, "limit:2026-01-01:k")
    n.first_touch()               # True（本周期还没记过）
    n.consume(cap=1)              # 1
    n.remaining(cap=1)            # 0
    n.used()                      # 1

    slot = PeriodSlot(read, write, "state:2026-W03")
    slot.write('{"n": 1}'); slot.read()          # '{"n": 1}'

    s = Streak()
    s.is_new("2026-01-01", "2026-01-02")                  # True（本周期没记过）
    s.next_value("2026-01-01", "2026-01-02", "2026-01-01", 6)     # 7（紧接上一周期）
    s.next_value("2025-12-20", "2026-01-02", "2026-01-01", 6)     # 1（断了）
    s.claim_terms()                                       # (1, 1)

    cd = Cooldown(read, write, "cd:42", window=30)
    cd.ready(now)                 # now - 上次触达 >= 30
    cd.touch(now)                 # 记下本次触达

**为什么不复用 `trade.DailyLimit` / `timers`**（就地复用评估结论）
---------------------------------------------------------------
* `trade.DailyLimit` 的存储键是**它自己拼的** `{namespace}:{today}:{key}`。本模块要顶的
  调用点，键是**内容侧早已写在存档里的**（前缀 / 分隔符 / 大小写各异，且都带冒号以外的结构）。
  换成 `DailyLimit` 的键模板 = 改存档键 = 老档「本周期已记过」当场丢失（玩家可见），
  因此不能就地复用；本模块把「键怎么拼」整条交还调用方，计数/上限/首次触达的规则照旧。
* `timers.Timers` 管的是「**每个主体一张事件表**（值是 `{type,data,expire}` 映射）+ 懒过期 +
  过期回调」；本模块要顶的调用点值是**一个扁平标量**（计数文本 / 状态文本 / 末次触达时间戳），
  套进 `Timers` 会同时改存档布局与清理时机（读路径不得绕过）。故不就地复用。
* 两者都保留：`trade` 是「映射 + 命名空间键」那一支的原型，`timers` 是「事件表 + 懒过期」那一支；
  本模块是「**键由调用方拼 + 值形态由调用方定**」这一支，不重造上面两支已有的东西
  （不读钟、不注册回调、不做过期清理）。

**有意不做的事**
----------------
* **不认日历**：不 import 时间/日期库、不读钟；周期键与 `now` 全部由调用方给。
* **不拼键**：键格式是内容/宿主口径，引擎只当不透明字符串（搬运前后存档键逐字节相同）。
* **不管存档后端**：只经注入的 `read` / `write`；不落盘、不缓存、不做跨周期清理。
* **不认「限几个」「冷却多久」**：`cap` / `window` 由调用方给。
* **不发号**：本模块不生成周期键，也不猜「上一周期」（那是日历知识）。
"""
from __future__ import annotations

from typing import Any, Callable, Optional

__all__ = ["PeriodCounter", "PeriodLimitExceeded", "PeriodSlot", "Streak", "Cooldown"]


# ───────────────────────────────────────────────────────── 校验口（fail-closed）
def _key_of(period_key: Any) -> str:
    """周期键：非空字符串（调用方拼；引擎不解释它的结构）。"""
    if not isinstance(period_key, str):
        raise TypeError(
            f"period_key 必须是字符串（键由调用方拼），"
            f"收到 {type(period_key).__name__}：{period_key!r}")
    if not period_key.strip():
        raise ValueError("period_key 必须是非空字符串（键由调用方拼）")
    return period_key


def _callable_of(fn: Any, label: str) -> Callable:
    if not callable(fn):
        raise TypeError(f"{label} 必须可调用，收到 {type(fn).__name__}")
    return fn


def _as_count(raw: Any, key: str) -> int:
    """计数读口：缺项 / 空串 = 0；整数与十进制整数字符串按数值算；其余 = 存档坏了 → 显式报错。

    与「静默当 0」的区别：坏值一律抛（计数键上出现非数字 = 存档被外部写坏，
    当成 0 会让玩家白拿一次额度）。
    """
    if raw is None or raw == "":
        return 0
    if isinstance(raw, bool):
        raise ValueError(f"周期计数不是整数（key={key!r}）：{raw!r}")
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, str):
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"周期计数不是十进制整数（key={key!r}）：{raw!r}") from exc
    else:
        raise ValueError(
            f"周期计数不是整数（key={key!r}）：{type(raw).__name__}={raw!r}")
    if value < 0:
        raise ValueError(f"周期计数为负（key={key!r}）：{raw!r}")
    return value


def _n_of(n: Any) -> int:
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError(f"n 必须是整数，收到 {n!r}")
    if n <= 0:
        raise ValueError(f"n 必须为正，收到 {n!r}")
    return n


def _cap_of(cap: Any) -> int:
    if isinstance(cap, bool) or not isinstance(cap, int):
        raise TypeError(f"cap 必须是整数，收到 {cap!r}")
    if cap < 0:
        raise ValueError(f"cap 不能为负，收到 {cap!r}")
    return cap


def _positive_int_of(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} 必须是整数，收到 {value!r}")
    if value <= 0:
        raise ValueError(f"{label} 必须为正，收到 {value!r}")
    return value


def _number_of(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} 必须是数值，收到 {value!r}")
    return float(value)


# ───────────────────────────────────────────────────────── 周期键 → 一格值
class PeriodSlot:
    """周期键 → **一格值**：读 / 写 / 判在场。值形态由调用方定，引擎原样搬运。

    * `read(key)`  —— 取该键的原始值（缺失给 `None`）；坏后端自己抛
    * `write(key, value)` —— 写该键（覆盖）
    * `period_key` —— **完整存储键**（调用方按自己的周期口径与键格式拼）

    引擎不缓存：每次 `read()` 都问一次后端（同一调用里现读现算，跨周期不会有残留）。
    """

    __slots__ = ("_read", "_write", "_key")

    def __init__(self, read: Callable[[str], Any], write: Callable[[str, Any], None],
                 period_key: str) -> None:
        self._read = _callable_of(read, "read（read(key) -> 原始值）")
        self._write = _callable_of(write, "write（write(key, value)）")
        self._key = _key_of(period_key)

    @property
    def key(self) -> str:
        """本格子的存储键（原样透传，引擎不解释它的结构）。"""
        return self._key

    def present(self) -> bool:
        """该周期键下**已有记录**（空串按「没有」算 —— 与本模块搬运前的包内判定同口径）。"""
        raw = self._read(self._key)
        return not (raw is None or raw == "")

    def read(self, default=None):
        """读该格的值；缺失 → `default`。"""
        raw = self._read(self._key)
        return default if raw is None else raw

    def write(self, value) -> None:
        """写该格（覆盖）。值形态原样交给后端。"""
        self._write(self._key, value)


class PeriodLimitExceeded(RuntimeError):
    """周期计数超出上限。"""


# ───────────────────────────────────────────────────────── 周期键 → 计数/上限
class PeriodCounter(PeriodSlot):
    """周期键 → **计数 / 上限 / 首次触达**（跨周期归零 = 换键，不需要清理）。

    * `used()`          本周期已计数（没记过 = 0）
    * `first_touch()`   本周期**还没记过**任何东西（键不存在 / 值为空串）
    * `remaining(cap)`  本周期剩余额度（不足 0 时给 0）
    * `consume(n=1, cap=…)` 记一笔并返回记完后的计数；超 `cap` → `PeriodLimitExceeded`
      （**先判后写**：存储一个字节都不动）；不传 `cap` 不判上限
    """

    __slots__ = ()

    def used(self) -> int:
        """本周期该键的计数（没记过 = 0）。"""
        return _as_count(self._read(self._key), self._key)

    def first_touch(self) -> bool:
        """本周期**还没有任何记录**（键缺失 / 值为空串）。

        与 `used() == 0` 的唯一差别：存档里若出现字面量 `"0"`，本方法判「已触达」——
        与本模块搬运前的包内判定（「值非空即为已领」）**逐字同口径**。
        正常存档（只由 `consume` 从 0 往上记）两者等价。
        """
        return not self.present()

    def remaining(self, cap: int) -> int:
        """本周期剩余额度 = `max(0, cap - used)`。"""
        return max(0, _cap_of(cap) - self.used())

    def consume(self, n: int = 1, *, cap: Optional[int] = None) -> int:
        """记一笔 `n`，返回记完后的本周期计数；超上限 → `PeriodLimitExceeded`（且不写）。"""
        n = _n_of(n)
        limit = None if cap is None else _cap_of(cap)
        used = self.used()
        if limit is not None and used + n > limit:
            raise PeriodLimitExceeded(
                f"周期上限 {limit}：已计 {used}，本次 {n}（key={self._key!r}）")
        self.write(used + n)
        return used + n


# ───────────────────────────────────────────────────────── 连续段
class Streak:
    """连续段规则：**同一周期不重领**；紧接上一周期 → 段长 +`step`；否则断段归 `reset_to`。

    「上一周期」由调用方给（引擎不认识日历）—— 调用方只要算出「紧邻的上一个周期键」。
    本类**不落盘**：段值的持久化在调用方（存档层写自己的列 / 自己的键）。
    """

    __slots__ = ("_step", "_reset_to")

    def __init__(self, *, step: int = 1, reset_to: int = 1) -> None:
        self._step = _positive_int_of(step, "step")
        self._reset_to = _positive_int_of(reset_to, "reset_to")

    @property
    def step(self) -> int:
        return self._step

    @property
    def reset_to(self) -> int:
        return self._reset_to

    def is_new(self, last_period, period) -> bool:
        """本周期还没认领过（`last_period != period`）。**不可重领**的判据。"""
        return last_period != period

    def follows(self, last_period, prev_period) -> bool:
        """紧接上一周期（连续段得以延长）。"""
        return last_period == prev_period

    def next_value(self, last_period, period, prev_period, value) -> int:
        """认领一次后的段值：连续 → `value + step`；否则 → `reset_to`。

        `last_period == period`（本周期已认领）→ `ValueError`（同一周期不得重领）。
        """
        if not self.is_new(last_period, period):
            raise ValueError(
                f"本周期已认领（last={last_period!r} period={period!r}）—— 不可重领")
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"value 必须是整数（当前段值），收到 {value!r}")
        if value < 0:
            raise ValueError(f"value 不能为负，收到 {value!r}")
        return value + self._step if self.follows(last_period, prev_period) else self._reset_to

    def claim_terms(self) -> tuple:
        """条件写的**规则项** `(extend_by, reset_to)` —— 本类规则的单一数值出口。

        调用方按自己的方言渲染，例：`CASE WHEN <last>=? THEN <value>+? ELSE ? END`
        依次绑 `(prev_period, extend_by, reset_to)`；引擎不认识 SQL/表达式方言，
        只交出规则里的两个数（`step` 与 `reset_to`）。
        """
        return (self._step, self._reset_to)


# ───────────────────────────────────────────────────────── 冷却
class Cooldown:
    """同一个键上的**末次触达时刻 + 窗口**判定（`now` 由调用方给，引擎不读钟）。

    * `last(default=0.0)`   上次触达时刻；没记过 / 坏值 → `default`（本模块搬运前的宽容口径）
    * `remaining(now)`      距可再次触达还剩多久（不足 0 时给 0）
    * `ready(now)`          现在可以触达了吗（`now - last >= window`）
    * `touch(now)`          记下本次触达（写 `now`；值形态交给后端）
    """

    __slots__ = ("_read", "_write", "_key", "_window")

    def __init__(self, read: Callable[[str], Any], write: Callable[[str, Any], None],
                 key: str, *, window) -> None:
        self._read = _callable_of(read, "read（read(key) -> 原始值）")
        self._write = _callable_of(write, "write（write(key, value)）")
        self._key = _key_of(key)
        win = _number_of(window, "window")
        if win < 0:
            raise ValueError(f"window 不能为负，收到 {window!r}")
        self._window = win

    @property
    def key(self) -> str:
        return self._key

    @property
    def window(self) -> float:
        return self._window

    def last(self, default: float = 0.0) -> float:
        """上次触达时刻；没记过 / 空串 / 坏值 → `default`（不静默改成别的数）。"""
        raw = self._read(self._key)
        if raw is None or raw == "":
            return float(default)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return float(default)

    def remaining(self, now) -> float:
        """距可再次触达还剩多久（`now - last >= window` → 0）。"""
        return max(0.0, self._window - (_number_of(now, "now") - self.last()))

    def ready(self, now) -> bool:
        """现在可以触达（距上次触达已满一个窗口）。"""
        return (_number_of(now, "now") - self.last()) >= self._window

    def touch(self, now) -> None:
        """记下本次触达（写 `now`）。"""
        self._write(self._key, now)
