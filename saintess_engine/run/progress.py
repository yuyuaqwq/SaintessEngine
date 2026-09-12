# -*- coding: utf-8 -*-
"""进度（Progress）—— 有序节点 + 每节点具名剩余池 + 资源预算 + 当前位置。

**为什么有它**：任何「一趟有多站、每站有剩余、走完一站进下一站」的东西
（关卡分层、房间清怪、地图探索、任务章节…）都有同一套操作：
**现在在哪一站**、**这一站还剩什么**、**能不能推进**、**是不是最后一站**、
以及「总量有限的资源按需扣、不足只给剩余」。把站里的内容拿掉，逻辑照旧成立。

**用法**::

    from saintess_engine.run import Progress

    p = Progress([{"key": "l1", "label": "营地前哨"}, {"key": "l2", "label": "酋长帐篷"}])
    p.push("l1", "units", mon_a); p.push("l1", "units", mon_b)
    p.take("l1", "units")        # → mon_a（空池 → None）
    p.left("l1", "units")        # → 1
    p.node_cleared("l1")         # 该节点所有池都空
    p.is_last()                  # False
    p.advance()                  # → True（推进一站；末站返回 False 且不动）
    p.goto("l1")                 # 也可以直接跳（连通性不归本形状管）

    p.set_budget("coin", 500); p.spend("coin", 300)      # → 300
    p.set_budget("mats", {"iron": 2}); p.spend_one("mats", "iron")   # → True
    p.spend("coin", 900)         # → 200（不足只给剩余，不抛错）
    p.to_dict(); Progress.from_dict(d)

**零知识**：引擎不认「层」「房间」「关卡」，只认 `node` / `pool` / `budget`；
节点 key 与池名都是内容侧给的字符串（本引擎不解释它们）。

**两个自由度**：`order` 只是「声明序」的默认含义（`advance` = 下一站）；
网状连通、必经路径、出入口属空间形状（`saintess_engine.space`），本形状不重复实现。
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

__all__ = ["Progress"]


def _norm_node(raw, i: int, key: str, label: str) -> dict:
    if isinstance(raw, dict):
        k = raw.get(key, None)
        k = str(k) if k is not None else str(i)
        lab = raw.get(label, None)
        return {"key": k, "label": "" if lab is None else str(lab), "raw": raw}
    return {"key": str(raw), "label": str(raw), "raw": raw}


class Progress:
    """有序节点 + 剩余池 + 预算。**可变**（推进/取用就地改）。"""

    __slots__ = ("nodes", "index", "_pools", "_budgets")

    def __init__(self, nodes: Iterable = (), *, key: str = "key", label: str = "label",
                 index: int = 0, pools=None, budgets=None) -> None:
        self.nodes = tuple(_norm_node(n, i, key, label) for i, n in enumerate(nodes or ()))
        self.index = int(index or 0)
        self._pools = {k: {p: list(v) for p, v in dict(m or {}).items()}
                       for k, m in dict(pools or {}).items()}
        self._budgets = {k: (dict(v) if isinstance(v, dict) else (list(v) if isinstance(v, list) else v))
                         for k, v in dict(budgets or {}).items()}

    # ---------------------------------------------------------------- 节点
    @property
    def keys(self):
        return tuple(n["key"] for n in self.nodes)

    @property
    def current_key(self) -> Optional[str]:
        return self.nodes[self.index]["key"] if self.nodes else None

    @property
    def current(self) -> Optional[dict]:
        return self.nodes[self.index]["raw"] if self.nodes else None

    def index_of(self, key) -> int:
        """节点位置；不存在 → -1。"""
        k = str(key)
        for i, n in enumerate(self.nodes):
            if n["key"] == k:
                return i
        return -1

    def has(self, key) -> bool:
        return self.index_of(key) >= 0

    def node(self, key) -> Optional[dict]:
        i = self.index_of(key)
        return self.nodes[i]["raw"] if i >= 0 else None

    def label_of(self, key) -> str:
        i = self.index_of(key)
        return self.nodes[i]["label"] if i >= 0 else ""

    def is_last(self) -> bool:
        return bool(self.nodes) and self.index >= len(self.nodes) - 1

    def next_key(self) -> Optional[str]:
        return None if self.is_last() else self.nodes[self.index + 1]["key"]

    def set_index(self, i: int) -> bool:
        """按**下标**定位（越界返回 False，不动）。"""
        if not self.nodes or not (0 <= int(i) < len(self.nodes)):
            return False
        self.index = int(i)
        return True

    def goto(self, key) -> bool:
        """按**节点 key** 定位（不存在返回 False，不动）。"""
        return self.set_index(self.index_of(key))

    def advance(self) -> bool:
        """推进一站；已是末站 → False（且不越界）。"""
        if self.is_last():
            return False
        self.index += 1
        return True

    # ---------------------------------------------------------------- 剩余池
    def _pool_of(self, key, pool, create: bool = False) -> Optional[list]:
        k = self.current_key if key is None else str(key)
        if k is None:
            return None
        per = self._pools.get(k)
        if per is None:
            if not create:
                return None
            per = self._pools[k] = {}
        name = "" if pool is None else str(pool)
        if name not in per:
            if not create:
                return None
            per[name] = []
        return per[name]

    def push(self, key, pool, item):
        """入池（尾插）。返回 item。"""
        self._pool_of(key, pool, create=True).append(item)
        return item

    def push_many(self, key, pool, items) -> int:
        """批量入池（保序）。返回入池条数。"""
        p = self._pool_of(key, pool, create=True)
        n = 0
        for it in (items or ()):
            p.append(it)
            n += 1
        return n

    def take(self, key=None, pool=None):
        """弹出一个（**首项**，与「先放先出」的既有序一致）；空池 → None。"""
        p = self._pool_of(key, pool)
        return p.pop(0) if p else None

    def drop(self, key, pool, item) -> bool:
        """按值移除一个；不在池里 → False（不抛错）。"""
        p = self._pool_of(key, pool)
        if not p:
            return False
        try:
            p.remove(item)
        except ValueError:
            return False
        return True

    def items(self, key=None, pool=None) -> list:
        """池内容的**副本**（读取用；改动请走 push/take/drop）。"""
        p = self._pool_of(key, pool)
        return list(p) if p else []

    def left(self, key=None, pool=None) -> int:
        p = self._pool_of(key, pool)
        return len(p) if p else 0

    def pools_of(self, key) -> dict:
        """某节点的具名池 → 剩余条数（副本）。"""
        k = self.current_key if key is None else str(key)
        return {name: len(v) for name, v in (self._pools.get(k) or {}).items()}

    def node_cleared(self, key) -> bool:
        """该节点**所有**已知池都空（未创建的池视为空）。"""
        k = str(key)
        if not self.has(k):
            return False
        return all(not v for v in (self._pools.get(k) or {}).values())

    def total_left(self) -> int:
        """全节点全池剩余总数。"""
        return sum(len(v) for per in self._pools.values() for v in per.values())

    @property
    def done(self) -> bool:
        """所有节点都清空（空节点表 → False）。"""
        return bool(self.nodes) and all(self.node_cleared(n["key"]) for n in self.nodes)

    # ---------------------------------------------------------------- 预算
    def set_budget(self, name, value):
        """设/换一份预算：`int` 计数 · `dict[str, int]` 计数表 · `list` 清单。"""
        self._budgets[str(name)] = (dict(value) if isinstance(value, dict)
                                    else (list(value) if isinstance(value, list) else value))
        return self._budgets[str(name)]

    def budget(self, name, default=0):
        return self._budgets.get(str(name), default)

    def spend(self, name, want=1) -> int:
        """**计数**预算扣减 → 实得量（不足只给剩余；不抛错）。"""
        k = str(name)
        cur = self._budgets.get(k, 0)
        if not isinstance(cur, (int, float)):
            raise TypeError(f"预算 {k!r} 不是计数（{type(cur).__name__}），要用 spend_one")
        take = max(0, min(int(want or 0), int(cur or 0)))
        self._budgets[k] = cur - take
        return take

    def spend_one(self, name, item=None) -> bool:
        """**计数表 / 清单**预算扣一件：够则扣（返回 True），不够 → False。"""
        k = str(name)
        cur = self._budgets.get(k)
        if isinstance(cur, dict):
            have = int(cur.get(item, 0) or 0)
            if have <= 0:
                return False
            cur[item] = have - 1
            return True
        if isinstance(cur, list):
            try:
                cur.remove(item)
            except ValueError:
                return False
            return True
        raise TypeError(f"预算 {k!r} 不是计数表/清单（{type(cur).__name__}），要用 spend")

    # ---------------------------------------------------------------- 往返
    def to_dict(self) -> dict:
        return {
            "nodes": [{"key": n["key"], "label": n["label"]} for n in self.nodes],
            "index": self.index,
            "pools": {k: {p: list(v) for p, v in per.items()} for k, per in self._pools.items()},
            "budgets": {k: (dict(v) if isinstance(v, dict) else (list(v) if isinstance(v, list) else v))
                        for k, v in self._budgets.items()},
        }

    @classmethod
    def from_dict(cls, data, **kw) -> "Progress":
        d = dict(data or {})
        nodes = [{"key": n.get("key"), "label": n.get("label", "")} for n in (d.get("nodes") or [])]
        return cls(nodes, index=d.get("index", 0), pools=d.get("pools"), budgets=d.get("budgets"), **kw)

    # ---------------------------------------------------------------- 审计
    def audit(self):
        """结构自检 → 问题列表（空列表 = 干净）。只报不改。"""
        problems = []
        seen = set()
        for n in self.nodes:
            if n["key"] in seen:
                problems.append(f"节点 key 重复：{n['key']}")
            seen.add(n["key"])
        if self.nodes and not (0 <= self.index < len(self.nodes)):
            problems.append(f"当前位置越界：index={self.index}（节点数 {len(self.nodes)}）")
        for k in self._pools:
            if k not in seen:
                problems.append(f"池挂在不存在的节点上：{k}")
        return problems

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return (f"Progress(nodes={len(self.nodes)}, at={self.current_key!r}, "
                f"left={self.total_left()}, done={self.done})")
