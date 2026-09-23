# -*- coding: utf-8 -*-
"""在场形状 —— 谁在这里 / 当天在哪 / 保底与冷却的算术（引擎零知识）。

形状
----
把「谁在场」这件事拆成四件**纯派生 + 装配**，取值与业务语义全部留在调用方：

  ① 日期 → 槽位   `day_slot(seed, size, *, salt)`      （当天在 size 个候选里取第几个）
  ② 日期 → 是否命中 `day_hit(seed, *, salt, rate)`        （裸阈值判据，见「口径分歧」）
  ③ 秒 → 展示分钟  `minutes_left(remain_sec)`           （向上取整，下限 1）
  ④ 连续未中 → 保底 `guarded_roll(miss, *, guarantee, chance, rng)`（含冷却 `cooldown_ok`）

  ⑤ 多表首命中     `Lookup(*tables)`                    （真值链；保序）
  ⑥ 清单装配       `Presence(lookup, *, keep, place_of, key)`（声明序 + 一条注入判据）
  ⑦ 保序合并       `merge_tables(*tables, exclude=())`  （返回**新** dict）

引擎一个**字段名**都不认识：`Lookup`/`Presence` 只拿**不透明的行**；`day` 是调用方给的
整数日序数（引擎**不认识日历**，不 import 任何时间/日期库）；随机只在注入的 `rng` 里。
「在场判据」「当天定位口径」「表名与表数」「盐」全是注入面。

用法::

    from ext_social.presence import (Presence, Lookup, day_slot, day_hit,
                                          minutes_left, guarded_roll, cooldown_ok,
                                          merge_tables)

    # ① 当天在候选桶里取第几个（确定性；同一天全服一致）
    day_slot(739000, len(bucket), salt=row_id)

    # ② 裸阈值判据（逐字：槽位 >= int(rate*100)）
    day_hit(739000, salt=row_id + SUFFIX, rate=0.8)

    # ③ 展示口径
    minutes_left(0)        # 1
    minutes_left(61)       # 2

    # ④ 保底 / 冷却（rng 由调用方给；本模块不 import random）
    hit, miss_after, cleared = guarded_roll(6, guarantee=7, chance=0.2, rng=rng)
    cooldown_ok(last, now, 1800)

    # ⑤⑥ 多表首命中 + 在场清单
    lk = Lookup(town_rows, wild_rows, hidden_rows)
    p = Presence(lk, keep=visible_today, place_of=place_of_today)
    p.rows(ids, place=current_place, day=ordinal)     # [(id, row, 表下标)]，声明序
    p.here(ids, place=current_place, day=ordinal)     # [row]
    slots = p.slots(static_items, timed_items)        # [(序号, "static"|"overlay", 项)]
    p.slot_at(slots, 3)

**为什么有它**：「同一份判定/派生在多个出口各写一遍」是这类系统的常态 —— 当天定位在
两处各算一次哈希、展示分钟在两处各写一次 `ceil`、多表首命中在几十处各写一次 `or` 链、
保底与冷却是散落的 `if`。散着写的代价不是行数，而是**口径会悄悄分叉**（同一个玩家在
不同面板看到不同的世界）。抽成形状后，分叉只能在显式注入的判据里发生，不再藏在算术里。

**有意不做的事**
----------------
* **不认识日历**：不 import 时间/日期库、不读钟；`day` 是调用方给的整数序数。
* **不掷骰**：不 import `random`；随机源一律经注入的 `rng()`，可复现、可测试。
* **不认字段**：不读任何业务行的字段名；判据 / 定位 / 标识全经注入的可调用。
* **不落盘 / 不缓存**：`Presence.rows()` 每次都现算 `keep` / `place_of`（世界可能已变）；
  保底计数与冷却时间戳的**读写由调用方在调用点做**（本模块只回「算完的数」）。
* **不去重 / 不排序**：声明序即展示序；同一 id 出现两次就展示两次。
* **不做数值调参**：`guarantee` / `window` / 盐 / 概率全部由调用方给。

**口径分歧（逐条，故意不统一）**
--------------------------------
1. **确定性 vs 随机性两口径**：`day_slot` / `day_hit` 是**确定性日期派生**（同一天全服一致，
   无状态、无随机）；`guarded_roll` 是**个人运气**（注入 `rng`）。两者**不合并** ——
   合并会出现「同一天同群玩家看到不同世界」或「蹲守刷屏」。
2. **`day_hit` 是裸阈值判据**：逐字 = `day_slot(seed, 100) >= int(rate * 100)`。
   它是「槽位是否命中阈值上界区」的**裸**判定，正用/反用由调用方按自己的语义决定
   （参考实现把它当「今天不出现」的判据）。**不许**化简成 `slot/100 >= rate` 的百分比
   浮点比较：`int(rate*100)` 是整数门槛，浮点比较在边界与进位误差上会漂。
3. **`minutes_left` 向上取整且下限 1**：剩 0 秒也显示「1 分」；负数同样给 1。
   展示「0 分」像 bug，下限 1 是刻意的展示口径。
4. **保底/冷却假值即放行**：`guarded_roll` 的 `chance` 为假值（`0`/`None`）→ **必定命中**
   （不是「永不命中」）；`cooldown_ok` 的 `last` 为假值（没记过）→ **必定可触发**。
5. **命中路径不立即清计数**：`guarded_roll` 在 `rng()` 命中时**原样返回 `miss`**；
   清计数只由 `cleared=True`（保底那一路）表达，落盘由调用方在调用点做。这两条
   **不许顺手统一** —— 否则保底路径的 `cleared` 语义会漂。
6. **真值链而非存在性链**：`Lookup.first` 用「值真不真」判定命中（与手写的
   `a.get(k) or b.get(k)` 同口径），**空 mapping 会穿透**到下一张表；不是
   `is not None` 链。跨表查找因此对「表中有一个空壳值」保持既有行为。
7. **保序 / 不去重 / 不排序**：清单一律声明序；`slots` 静态在前、叠加项**续号**（从 1 起）；
   `slot_at` 是 1-based，越界给 `None`（**不抛**）。
8. **`merge_tables` 后表覆盖前表、`exclude` 只跳过不报错**：同名键按表序后者胜（与
   `{**a, **b}` 同口径）；`exclude` 内的键在**每一张**表里都跳过（跳过的键不占位）。

**四条局部复用评估（为什么不就地复用既有形状）**
------------------------------------------------
* **为什么不复用 `periodic.Cooldown`**：`Cooldown` 的存储键是**它自己拼的**
  `{namespace}:{today}:{key}`，且把「读 → 判 → 写」三件事绑在一个对象上。本形状要顶的
  调用点，时间戳存在调用方自己的**嵌套映射**里（`meta["last"][id]`），不是「一个键一个标量」；
  而且本形状只抽**算术**（`cooldown_ok(last, now, window) -> bool`），落盘留在调用点
  （不变量 J7/J9）。套 `Cooldown` 要多造两个闭包、还要改存档布局，收益为负。
* **为什么不复用 `timers.Timers`**：`Timers` 已经在用 —— 限时在场**就是**一张 `Timers`
  事件表。本形状不重造它：`presence` 只做「把事件表**读出来**并派生展示分钟/保序编号」
  （`Presence.overlay` / `minutes_left`）；过期懒清除与过期回调仍是 `Timers` 的职责
  （不变量 J8）。把 `Timers` 再包一层，只会造出第二套过期语义。
* **为什么不复用 `space.Space`**：定位在本形状里是**一个不透明 id 的相等判定**
  （「当天所在地 == 当前位置」），不是连通性 / 深度 / 必经路径。`Space` 的输入是节点表 +
  拓扑，产出邻接与路径；套过来会要求把「所在地取值」归口成节点 id（= 改内容数据），
  而本形状必须接受调用方**混用**的两套取值口径（不变量 J3 的判据由调用方给）。
* **为什么不复用 `loot` / 加权抽取**：`day_slot` / `day_hit` 是**确定性日期哈希**，
  同一天对所有玩家给出同一答案；`loot` 的池 + 权重 + 档位是**随机抽取**，形状不同
  （一个没有随机源，一个的本质就是随机源）。`guarded_roll` 只是**一次伯努利 + 保底计数**，
  套 `loot` 的池/档位/加权在这里全是空转；且它会诱使把 `rng` 藏进池对象，
  破坏「随机源必须注入、可复现」这条不变量。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

from saintess_engine._validators import callable_of, int_of, number_of

__all__ = ["Lookup", "Presence", "day_slot", "day_hit", "minutes_left",
           "guarded_roll", "cooldown_ok", "merge_tables"]

#: 日期哈希的乘法常量与掩码（逐字 = 包内搬来的那一份；改它 = 换世界）。
_HASH_MULT = 2654435761
_HASH_MASK = 0x7FFFFFFF

#: 阈值判据的槽位总数：`day_hit` 把 [0, 100) 的槽位与百分比门槛比（逐字口径）。
_THRESHOLD_SPAN = 100

#: 展示分钟的一格秒数。
_SECONDS_PER_MINUTE = 60

#: `slots()` 的两类来源标签（**形状标签**，不是业务词）。
_STATIC = "static"
_OVERLAY = "overlay"

#: `overlay()` 的**事件视图契约**：调用方把事件规整成这几个通用键即可。
#:   `key`    事件标识（可选，原样带回）
#:   `row_id` 在场条目 id（可选；缺省回落 `key`）
#:   `place`  所在地（可选，原样带回）
#:   `remain` 剩余秒（给了就直接用）
#:   `expire` 到点时刻（`remain` 没给时，用 `expire - now` 现算剩余秒）
_EV_KEY = "key"
_EV_ROW_ID = "row_id"
_EV_PLACE = "place"
_EV_REMAIN = "remain"
_EV_EXPIRE = "expire"


# ───────────────────────────────────────────────────────── 校验口（fail-closed）
def _str_of(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} 必须是字符串，收到 {type(value).__name__}：{value!r}")
    return value


def _seconds_of(value: Any, label: str = "remain_sec") -> int:
    """剩余秒：整数 / 浮点（截断）/ 十进制整数字符串；其余 → 报错，不静默当 0。"""
    if isinstance(value, bool):
        raise TypeError(f"{label} 必须是秒数，收到 bool：{value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise ValueError(f"{label} 不是十进制整数秒：{value!r}") from exc
    raise TypeError(f"{label} 必须是秒数，收到 {type(value).__name__}：{value!r}")


def _mapping_of(value: Any, label: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} 必须是映射，收到 {type(value).__name__}：{value!r}")
    return value


def _exclude_of(exclude: Any) -> frozenset:
    """`exclude` 的键集合：字符串整体当**一个**键（写成 `"abc"` 是常见笔误，不许拆成字符）。"""
    if exclude is None:
        return frozenset()
    if isinstance(exclude, str):
        return frozenset((exclude,))
    if isinstance(exclude, Mapping):
        return frozenset(exclude.keys())
    try:
        return frozenset(exclude)
    except TypeError as exc:
        raise TypeError(
            f"exclude 必须是键的可迭代，收到 {type(exclude).__name__}：{exclude!r}") from exc


# ───────────────────────────────────────────────────────── 确定性日期派生
def day_slot(seed: int, size: int, *, salt: str = "") -> int:
    """当天在 `size` 个候选里取第几个。

    逐字 = ``((seed*2654435761 + Σord(salt)) & 0x7FFFFFFF) % size``。

    * `seed` —— 调用方给的整数日序数（引擎不认识日历）
    * `salt` —— 内容侧盐（同一天、不同盐 = 不同的独立派生）
    * `size <= 0` → `ValueError`（空候选桶是调用方 bug，**不许**静默返回 0）
    """
    int_of(seed, "seed")
    span = int_of(size, "size", minimum=1)
    s = _str_of(salt, "salt")
    total = seed * _HASH_MULT + (sum(ord(c) for c in s) if s else 0)
    return (total & _HASH_MASK) % span


def day_hit(seed: int, *, salt: str = "", rate: float) -> bool:
    """当天是否命中阈值（**裸判据**）：逐字 = ``day_slot(seed, 100, salt=salt) >= int(rate*100)``。

    ⚠️ **不许「化简」成** ``day_slot(seed, 100) / 100 >= rate`` 的百分比浮点比较：
    门槛是 `int(rate*100)` 这个**整数**，浮点比较会在进位误差与边界槽位上漂。
    正用 / 反用（「命中 = 出现」还是「命中 = 不出现」）是**调用方**的语义，本函数只给裸结果。
    """
    slot = day_slot(seed, _THRESHOLD_SPAN, salt=salt)
    return slot >= int(number_of(rate, "rate") * _THRESHOLD_SPAN)


def minutes_left(remain_sec) -> int:
    """剩余秒 → 展示分钟：``max(1, ceil(remain/60))``。

    0 / 负数 → `1`（**不许返回 0**：展示「剩 0 分」像 bug，下限 1 是刻意口径）。
    """
    seconds = _seconds_of(remain_sec)
    return max(1, -(-seconds // _SECONDS_PER_MINUTE))


# ───────────────────────────────────────────────────────── 保底 / 冷却
def guarded_roll(miss: int, *, guarantee: int, chance, rng) -> tuple:
    """连续未中保底掷骰 → ``(hit, miss_after, cleared)``。

    门序（**先判后写**，逐字照搬包内那一份）：

    1. `chance` 为假值 → ``(True, miss, False)`` —— **不读 `rng`、不动计数**
    2. `miss >= guarantee` → ``(True, 0, True)`` —— 保底必中，`cleared` 叫调用方清计数
    3. `rng() < chance` → ``(True, miss, False)`` —— **命中路径不清计数**
    4. 否则 → ``(False, miss + 1, False)``

    不缓存、不落盘：调用方拿 `miss_after` / `cleared` 在自己的调用点写。
    `rng` 必填（缺失 / 不可调用 → `TypeError`）—— 引擎**不许**悄悄用系统随机。
    """
    callable_of(rng, "rng")
    current = int_of(miss, "miss", minimum=0)
    threshold = int_of(guarantee, "guarantee", minimum=1)
    if not chance:
        return (True, current, False)
    if current >= threshold:
        return (True, 0, True)
    if rng() < chance:
        return (True, current, False)
    return (False, current + 1, False)


def cooldown_ok(last, now, window) -> bool:
    """冷却判据：`last` 为假值（没记过）→ `True`；否则 ``now - last >= window``。

    `last` / `now` / `window` 的原值形态由调用方给（秒 / 整数都行）；本函数不读钟。
    """
    span = number_of(window, "window")
    if not last:
        return True
    return (number_of(now, "now") - number_of(last, "last")) >= span


# ───────────────────────────────────────────────────────── 表合并 / 多表首命中
def merge_tables(*tables, exclude=()) -> dict:
    """保序合并多张表 → **新** dict（不写输入）。

    * 键序 = 表序 × 表内插入序（前表在后，同名键被**后表覆盖**，与 ``{**a, **b}`` 同口径）
    * `exclude` 内的键**跳过**（在每一张表里都跳过；跳过的键不占位）
    """
    skip = _exclude_of(exclude)
    out: dict = {}
    for index, table in enumerate(tables):
        _mapping_of(table, f"tables[{index}]")
        for key, value in table.items():
            if key in skip:
                continue
            out[key] = value
    return out


class Lookup:
    """有序多表首命中。**真值链**（与手写的 ``a.get(k) or b.get(k)`` 同口径）。

    * 每项是一张 `Mapping`，按传入序查
    * `first(key)` → ``(值, 表下标)``；全部落空 → ``(None, None)``。
      **命中但值为假值（`{}` / `0` / `""`）→ 继续**下一张表（空 mapping 会穿透）
    * `rows(ids)` → ``[(id, 值, 表下标)]``，**保序**；缺席 / 全落空 → 丢弃该 id

    不拷贝表、不建索引、不缓存（表变了下次调用立刻可见）。
    """

    __slots__ = ("_tables",)

    def __init__(self, *tables) -> None:
        self._tables = tuple(
            _mapping_of(table, f"tables[{index}]") for index, table in enumerate(tables))

    @property
    def tables(self) -> tuple:
        """参与查找的表（原对象，按序；只读元组）。"""
        return self._tables

    def first(self, key) -> tuple:
        """首个**真值**命中 → ``(值, 表下标)``；全部落空 → ``(None, None)``。"""
        for index, table in enumerate(self._tables):
            value = table.get(key)
            if value:
                return (value, index)
        return (None, None)

    def rows(self, ids) -> list:
        """按 `ids` 声明序给出 ``[(id, 值, 表下标)]``；查不到的 id 丢弃。"""
        out = []
        for row_id in ids:
            value, index = self.first(row_id)
            if index is not None:
                out.append((row_id, value, index))
        return out


class Presence:
    """在场清单：**声明序 + 一条注入判据**；不去重、不排序、不缓存。

    * `lookup` —— 多表首命中口（`Lookup` 或任何有 `rows(ids)` 的对象）
    * `keep(row_id, row) -> bool` —— 唯一在场判据（**内容侧组合**：功能豁免 / 时段 /
      概率 / 解锁 / 硬周期 …全在它里面；引擎只给**顺序与短路**）
    * `place_of(row_id, row, day) -> Any` —— 当天定位口；与 `place` 做**相等判定**
    * `key(row_id, row) -> Any` —— 条目标识投影（缺省 = 传入 id）；本模块判定路径不读它
      （留给调用方按需使用，保持零字段知识）
    """

    __slots__ = ("_lookup", "_keep", "_place_of", "_key")

    def __init__(self, lookup, *, keep, place_of,
                 key: Callable[[Any, Any], Any] = lambda row_id, row: row_id) -> None:
        if not callable(getattr(lookup, "rows", None)):
            raise TypeError(
                f"lookup 必须有可调用的 rows(ids)，收到 {type(lookup).__name__}：{lookup!r}")
        self._lookup = lookup
        self._keep = callable_of(keep, "keep（keep(row_id, row) -> bool）")
        self._place_of = callable_of(place_of, "place_of（place_of(row_id, row, ordinal)）")
        self._key = callable_of(key, "key（key(row_id, row)）")

    @property
    def lookup(self):
        return self._lookup

    @property
    def key_of(self) -> Callable:
        """条目标识投影（注入的那一个；默认 ``lambda row_id, row: row_id``）。"""
        return self._key

    def rows(self, ids, *, place=None, day=None) -> list:
        """``[(row_id, row, 表下标)]``：声明序；`keep` 为假丢弃；给了 `place` 则定位须相等。

        **每次现算** `keep` / `place_of`（世界可能已变，不缓存）；
        `place is None` = 不做定位过滤（不是「定位为空」）。
        """
        out = []
        for row_id, row, table_index in self._lookup.rows(ids):
            if not self._keep(row_id, row):
                continue
            if place is not None and self._place_of(row_id, row, day) != place:
                continue
            out.append((row_id, row, table_index))
        return out

    def here(self, ids, *, place=None, day=None) -> list:
        """`rows` 的**投影**（只回行），仍是声明序。"""
        return [row for _row_id, row, _index in self.rows(ids, place=place, day=day)]

    def slots(self, static: list, overlay: list) -> list:
        """静态清单在前、叠加清单**续号** → ``[(序号, "static"|"overlay", 项)]``（序号从 1 起）。

        纯编号：不合并、不去重、不重排；项的形态原样带出。
        """
        out = []
        number = 0
        for item in static:
            number += 1
            out.append((number, _STATIC, item))
        for item in overlay:
            number += 1
            out.append((number, _OVERLAY, item))
        return out

    def slot_at(self, slots: list, index: int):
        """1-based 取用序号对应的**整条** ``(序号, 来源, 项)``；越界（含 `< 1`）→ `None`（不抛）。"""
        position = int_of(index, "index")
        if position < 1 or position > len(slots):
            return None
        return slots[position - 1]

    def overlay(self, events, *, now, minutes: Callable = minutes_left) -> list:
        """事件视图 → ``[{"key","row_id","place","minutes","raw"}]``（**保有输入序**）。

        每条事件的**剩余秒现算**：给了 `remain` 就用它，否则用 ``expire - now``。
        分钟口径经注入的 `minutes`（缺省 `minutes_left`）。事件本身原样放进 `raw`
        （**不拷贝**）—— 展示口径在引擎，事件内容在调用方。
        """
        at = number_of(now, "now")
        to_minutes = callable_of(minutes, "minutes")
        out = []
        for index, raw in enumerate(events):
            _mapping_of(raw, f"events[{index}]")
            remain = raw.get(_EV_REMAIN)
            if remain is None:
                remain = _seconds_of(raw.get(_EV_EXPIRE, at), "expire") - int(at)
            out.append({
                _EV_KEY: raw.get(_EV_KEY),
                _EV_ROW_ID: raw.get(_EV_ROW_ID, raw.get(_EV_KEY)),
                _EV_PLACE: raw.get(_EV_PLACE),
                "minutes": to_minutes(remain),
                "raw": raw,
            })
        return out
