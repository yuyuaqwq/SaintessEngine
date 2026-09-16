# -*- coding: utf-8 -*-
"""同 key 合并的「堆叠容器」骨架 —— 背包 / 仓库 / 邮件附件 / 摊位 同形。

形状
----
* 容器 = **键控堆叠表**：每个 `key` 至多一格，格 = `{"key": k, "count": n, "data": {...}}`，
  格序 = 首次出现序（与 `container.Slots` 的有序列表同构，只是同 key 并进同一格）
* 同 key 合并 = **件数相加**；来件携带个体记录时，记录按序拼接（已存的在前），
  超出 `cap` 丢最旧
* 扣件 = **件数相减**；个体记录按 FIFO 从头截断；扣到 0 及以下 → 整格消失
* `data` 里除个体记录外的字段 = **类属性**：合并时以**来件**为准，扣件时原样保留
* 持久化 = 只给 `load` / `dump`（JSON 文本），与 `Slots` 同口径

有意不做的事（与内容侧的边界）
------------------------------
* **个体记录字段名与件数上限由调用方传**：引擎不认识"哪个字段装个体记录"（`marks`），
  也不认识具体上限（`cap`）—— 两者都是内容侧取值，本模块零默认值
* **不做「可堆叠」判定**：`merge=False` 只表示"件数相加、`data` 不动"；
  什么物品不可堆叠是内容侧配置
* **不做物品语义**：`key` / `data` 原样存取，引擎不解释 key 的形态（原型 id / 实例 uuid 同形处理）
* **不做存储 IO / 事务 / 缓存**：`load` / `dump` 只处理字符串 ↔ 结构，事务边界留给使用方
* **不假设一格一件**：与 `container.Slots` 互补 —— `Slots` 一格一件，`Stack` 同 key 合并
"""
from __future__ import annotations

import json
from typing import Any, Callable, Iterable, Optional

__all__ = ["Stack", "carries_records", "merge_records", "trim_records"]


# ---------------------------------------------------------------- 记录代数（纯函数）
def carries_records(data: Any, *, marks: str) -> bool:
    """来件是否携带个体记录 —— **合并分支的唯一判据**。

    `data` 是映射且 `marks` 键存在且值非 `None`（`None` = 明确"没有个体记录"，
    空列表 `[]` = "有记录、只是还没攒到"）。
    """
    return isinstance(data, dict) and data.get(marks) is not None


def _stored_records(stored: Any, marks: str) -> Any:
    """已存一格的个体记录：映射取 `marks`（缺键 → `[]`）；裸序列即记录本身；其它 → `[]`。"""
    if isinstance(stored, dict):
        return stored.get(marks, [])
    if isinstance(stored, list):
        return stored
    return []


def merge_records(stored: Any, incoming: dict, *, marks: str,
                  cap: Optional[int] = None) -> dict:
    """已存一格 `data` ← 来件 `data`（**来件为准**）：非记录字段取来件，记录拼接后截断。

    记录拼接 = `已存 + 来件`（旧在前）；`cap` 非 `None` 时保留**最后** `cap` 条（丢最旧）。
    `incoming` 必须是映射（合并分支的判据见 `carries_records`）。
    """
    out = {k: v for k, v in incoming.items() if k != marks}
    joined = _stored_records(stored, marks) + incoming[marks]
    out[marks] = joined if cap is None else joined[-cap:]
    return out


def trim_records(stored: Any, taken: int, *, marks: str) -> Any:
    """已存一格扣掉 `taken` 件后的 `data`：个体记录按 FIFO **从头**截 `taken` 条。

    - 记录为空（缺键 / `None` / 空表 / 非映射）→ **原对象返回**（不新造字典）
    - 记录截空 → 删掉 `marks` 键（有件数无个体，展示/计价交内容侧按原价兜底）
    - 裸序列（历史落盘形态）→ 截空返回 `{}`，否则返回 `{marks: 余下}`
    """
    records = None
    if isinstance(stored, dict):
        records = stored.get(marks)
    elif isinstance(stored, list):
        records = stored
    if not records:
        return stored
    rest = records[taken:]
    if isinstance(stored, list):
        return {marks: rest} if rest else {}
    out = dict(stored)
    if rest:
        out[marks] = rest
    else:
        out.pop(marks, None)
    return out


# ---------------------------------------------------------------- 容器（不可变）
def _absorb(existing: dict, incoming: dict, *, merge: bool, marks: str,
            cap: Optional[int]) -> dict:
    """把 `incoming` 格并进 `existing` 格：件数相加；合并开启且来件带记录时并记录。

    未合并 → `data` **复用旧对象**（调用方可用 `is` 判定"没动 data"，无需写回）。
    """
    count = existing["count"] + incoming["count"]
    if merge and carries_records(incoming["data"], marks=marks):
        data = merge_records(existing["data"], incoming["data"], marks=marks, cap=cap)
    else:
        data = existing["data"]
    return {"key": existing["key"], "count": count, "data": data}


class Stack:
    """键控堆叠容器（**不可变**：写操作返回新容器，无 setter）。"""

    def __init__(self, entries: Optional[Iterable[Any]] = None, *,
                 marks: str, cap: Optional[int] = None) -> None:
        """`marks` = 个体记录字段名（内容侧协议，**必填**）；`cap` = 记录条数上限（`None` = 不限）。"""
        self.marks = marks
        self.cap = None if cap is None else int(cap)
        self._entries: list[dict] = []
        self._index: dict = {}
        for e in entries or ():
            item = self._normalize(e)
            i = self._index.get(item["key"])
            if i is None:                       # R1：新 key → 追加一格
                self._index[item["key"]] = len(self._entries)
                self._entries.append(item)
            else:                               # 同 key 重复来件 → 按合并规则并入
                self._entries[i] = _absorb(self._entries[i], item, merge=True,
                                           marks=self.marks, cap=self.cap)

    # ------------------------------------------------------------ 构造 / 序列化
    @staticmethod
    def _normalize(e: Any) -> dict:
        """把任意来源的一格规整成 `{key, count, data}`（脏数据不炸；件数照原样不夹紧）。"""
        if not isinstance(e, dict):
            return {"key": e, "count": 1, "data": {}}
        c = e.get("count")
        d = e.get("data")
        return {"key": e.get("key"), "count": 1 if c is None else int(c),
                "data": {} if d is None else d}

    def _spawn(self, entries: list) -> "Stack":
        """派生一个新容器（不可变的落点）。"""
        return Stack(entries, marks=self.marks, cap=self.cap)

    @classmethod
    def load(cls, raw: Any, *, marks: str, cap: Optional[int] = None) -> "Stack":
        """从 JSON 文本 / 列表 / None 载入（**容错**：坏数据 → 空容器）。

        容错是刻意的：这一层读的是历史落盘数据，格式漂移不该让功能崩（与 `Slots.load` 同口径）。
        """
        data = raw
        if isinstance(data, (str, bytes)):
            try:
                data = json.loads(data)
            except (ValueError, TypeError):
                data = None
        if not isinstance(data, list):
            data = []
        return cls(data, marks=marks, cap=cap)

    def dump(self) -> str:
        """序列化为 JSON 文本（`ensure_ascii=False`，与既有落盘格式口径一致）。"""
        return json.dumps(self._entries, ensure_ascii=False)

    # ------------------------------------------------------------ 读
    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self):
        return iter(self._entries)

    def __contains__(self, key: Any) -> bool:
        return key in self._index

    def entries(self) -> list:
        """全部格子（浅拷贝列表；元素为原字典，调用方改元素即改容器）。"""
        return list(self._entries)

    def keys(self) -> list:
        """全部键（格序）。"""
        return [e["key"] for e in self._entries]

    def get(self, key: Any) -> Optional[dict]:
        """看某一格；不存在 → `None`。"""
        i = self._index.get(key)
        return None if i is None else self._entries[i]

    def count_of(self, key: Any) -> int:
        """某一格的件数；不存在 → `0`。"""
        e = self.get(key)
        return 0 if e is None else e["count"]

    def total(self) -> int:
        """全部件数合计。"""
        return sum(e["count"] for e in self._entries)

    def count_where(self, pred: Optional[Callable[[Any, Any], bool]] = None) -> int:
        """按格累计件数：`pred(key, data)` 为真才计；`pred=None` = 全部（= `total()`）。"""
        if pred is None:
            return self.total()
        return sum(e["count"] for e in self._entries if pred(e["key"], e["data"]))

    # ------------------------------------------------------------ 写（返回新容器）
    def add(self, key: Any, count: int = 1, data: Any = None, *,
            merge: bool = True) -> "Stack":
        """加 `count` 件到 `key`：新 key 建格；同 key 件数相加，`merge` 且来件带个体记录时并记录。

        `count` 必须是正整数（0 / 负 是内容侧的业务校验，引擎直接拒绝非法件数）。
        """
        if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            raise ValueError("Stack.add 的件数必须是正整数（拿到 %r）" % (count,))
        incoming = {"key": key, "count": int(count), "data": {} if data is None else data}
        i = self._index.get(key)
        if i is None:                           # R1
            return self._spawn(list(self._entries) + [incoming])
        entries = list(self._entries)
        entries[i] = _absorb(entries[i], incoming, merge=merge,
                             marks=self.marks, cap=self.cap)     # R2 / R3 / R3b
        return self._spawn(entries)

    def take(self, key: Any, count: int = 1) -> tuple:
        """扣 `count` 件：格内不足（含恰好）→ **整格消失**；返回 `(新容器, 是否命中该格)`。

        `count` 必须是正整数（同上）；key 不存在 → `(self, False)`，不抛错。
        """
        if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            raise ValueError("Stack.take 的件数必须是正整数（拿到 %r）" % (count,))
        i = self._index.get(key)
        if i is None:                           # R4 兜底：缺键
            return self, False
        existing = self._entries[i]
        if existing["count"] <= count:          # R4：扣空 → 丢格
            return self._spawn([e for j, e in enumerate(self._entries) if j != i]), True
        entry = {"key": existing["key"], "count": existing["count"] - count,
                 "data": trim_records(existing["data"], count, marks=self.marks)}
        entries = list(self._entries)
        entries[i] = entry
        return self._spawn(entries), True
