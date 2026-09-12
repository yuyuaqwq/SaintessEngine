# -*- coding: utf-8 -*-
"""读口与重放 —— 「一段流水怎么被查、被复用、被脱敏」。

* `Reader`：分析脚本与回放**共用同一个读口**（`iter_records(...)` 一套筛选口径）
* `Replay`：把一段流水当**事件序列**重演 —— 支撑「同一场战斗复现」与「匿名化审计」

两者都只吃 `Record` 序列，不认识任何具体 kind（词汇表由内容侧给）。
"""
from __future__ import annotations

from typing import Iterable, Iterator, Optional, Sequence

from .record import Record

__all__ = ["Reader", "Replay"]


def _kind_match(actual: str, pattern: str) -> bool:
    """kind 匹配：全等，或以 `battle.` 这种**点结尾前缀**匹配整族。"""
    p = str(pattern or "")
    if not p:
        return False
    if p.endswith("."):
        return str(actual).startswith(p)
    return actual == p


class Reader:
    """读口：从**可读出口**（实现 `read_records()` 的 sink）取记录并筛选。

    筛选口径（全部可选、可组合）：
        kind    字符串或列表；`"battle."` 这种点结尾写法 = 前缀匹配整族
        actor   归属主体（精确匹配）
        tag     含该标签
        since / until  时间窗（左闭右开：`since <= ts < until`）
    """

    def __init__(self, sinks: Iterable) -> None:
        self._sources = [s for s in sinks or ()
                         if callable(getattr(s, "read_records", None))]

    def sources(self) -> tuple:
        return tuple(self._sources)

    def all(self) -> list:
        out: list = []
        for s in self._sources:
            out.extend(s.read_records())
        return out

    def iter_records(self, *, kind=None, actor: Optional[str] = None,
                     tag: Optional[str] = None, since: Optional[float] = None,
                     until: Optional[float] = None) -> Iterator[Record]:
        pats: list = []
        if kind is not None:
            pats = [str(kind)] if isinstance(kind, str) else [str(k) for k in kind]
        for r in self.all():
            if pats and not any(_kind_match(r.kind, p) for p in pats):
                continue
            if actor is not None and r.actor != actor:
                continue
            if tag is not None and not r.has_tag(tag):
                continue
            if since is not None and r.ts < float(since):
                continue
            if until is not None and r.ts >= float(until):
                continue
            yield r

    def count(self, **filters) -> int:
        return sum(1 for _ in self.iter_records(**filters))

    def first(self, **filters) -> Optional[Record]:
        for r in self.iter_records(**filters):
            return r
        return None

    def kinds(self) -> tuple:
        out: list = []
        for r in self.all():
            if r.kind not in out:
                out.append(r.kind)
        return tuple(out)

    def replay(self, **filters) -> "Replay":
        return Replay(list(self.iter_records(**filters)))


class Replay:
    """按序重放一段流水（时间稳定排序；同刻保持写入序）。

    三个用途：
    * **复现**：`steps()` 顺序重演，逐条核对"这一场是不是同一场"
    * **审计**：`by_kind()` / `actors()` / `span()` 出概览
    * **脱敏**：`anonymize()` 把 actor 换成假名后交给分析侧（原始记录不变）
    """

    def __init__(self, records: Iterable[Record], *, name: str = "") -> None:
        self.name = name
        self._raw: list = [r for r in (records or ())]
        self._sorted: Optional[list] = None

    def __len__(self) -> int:
        return len(self._raw)

    def records(self) -> tuple:
        """按 `(ts, 写入序)` 稳定排序后的记录（首次调用时排序并缓存）。"""
        if self._sorted is None:
            self._sorted = sorted(self._raw, key=lambda r: r.ts)
        return tuple(self._sorted)

    def steps(self) -> Iterator[Record]:
        return iter(self.records())

    def kinds(self) -> tuple:
        out: list = []
        for r in self.records():
            if r.kind not in out:
                out.append(r.kind)
        return tuple(out)

    def by_kind(self) -> dict:
        out: dict = {}
        for r in self.records():
            out.setdefault(r.kind, []).append(r)
        return {k: tuple(v) for k, v in out.items()}

    def actors(self) -> tuple:
        out: list = []
        for r in self.records():
            if r.actor and r.actor not in out:
                out.append(r.actor)
        return tuple(out)

    def span(self) -> tuple:
        rs = self.records()
        return (rs[0].ts, rs[-1].ts) if rs else (0.0, 0.0)

    def anonymize(self, mapping: Optional[dict] = None, *, prefix: str = "u") -> "Replay":
        """actor 脱敏 → 新 `Replay`（原对象不变）。

        `mapping` 给定 = 按它替换（未覆盖的 actor 自动补号）；不给 = 全自动编号（按出现序）。
        """
        auto: dict = dict(mapping or {})
        for r in self.records():
            if r.actor and r.actor not in auto:
                auto[r.actor] = f"{prefix}{len(auto) + 1}"
        out = []
        for r in self._raw:
            if r.actor and r.actor in auto:
                out.append(Record(kind=r.kind, ts=r.ts, actor=auto[r.actor],
                                  fields=dict(r.fields), tags=tuple(r.tags)))
            else:
                out.append(r)
        return Replay(out, name=self.name)

    def to_dicts(self) -> list:
        return [r.to_dict() for r in self.records()]

    def summary(self) -> dict:
        k = self.by_kind()
        return {"name": self.name, "count": len(self._raw), "kinds": self.kinds(),
                "actors": self.actors(), "span": self.span(),
                "per_kind": {name: len(v) for name, v in k.items()}}
