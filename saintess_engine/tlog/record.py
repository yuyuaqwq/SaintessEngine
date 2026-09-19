# -*- coding: utf-8 -*-
"""结构化流水的**数据单位**与**声明表**（形状侧）。

`Record` = 一条流水：「谁（`actor`）在什么时候（`ts`）做了/发生了什么（`kind` + `fields`）」。
`kind` 是**点号字符串**（`battle.hit` / `quest.accept`）—— **词汇表由内容侧给**，框架不认任何
具体 kind（与 `command` 的指令名、`text` 的文案 key 同一纪律）。

`KindTable` = 「哪个 kind 有哪些字段」的声明（与 `TextTable` 同规格：装载 / 查询 / 自检 /
`to_data()` 回写给编辑器）。它的用处是**让流水可校验**：写的人和读的人对"这条记录该有哪些
字段"有同一份依据，而不是各自记。

可拔插：不装载 `KindTable` = 不做任何校验（零行为）；`TLog(strict=True)` 才按它拦。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional

__all__ = ["Record", "KindSpec", "KindTable", "is_valid_kind", "KIND_RE"]

# kind 命名：点分标识（`battle.hit` / `a.b.c`），每段字母开头
KIND_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*$")
_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def is_valid_kind(name: str) -> bool:
    return bool(KIND_RE.match(str(name or "")))


@dataclass
class Record:
    """一条流水（**形状**，字段名与取值都由内容侧定义）。

    * `kind`   —— 点号字符串（`battle.hit`）；字典由内容侧给
    * `ts`     —— 事件时刻（秒，float）；由 `TLog` 注入时钟，框架不猜时间
    * `actor`  —— 归属主体（玩家/单位标识字符串）；内容侧决定填什么
    * `fields` —— 结构化字段（dmg / subject / crit …）
    * `tags`   —— 标签（内容侧自定，如 `("pvp",)`）；用于粗筛
    """

    kind: str
    ts: float = 0.0
    actor: str = ""
    fields: dict = field(default_factory=dict)
    tags: tuple = ()

    def __post_init__(self) -> None:
        self.kind = str(self.kind or "")
        self.ts = float(self.ts or 0.0)
        self.actor = "" if self.actor is None else str(self.actor)
        if not isinstance(self.fields, dict):
            self.fields = dict(self.fields or {})
        if not isinstance(self.tags, tuple):
            self.tags = tuple(self.tags or ())

    # ---------------------------------------------------------- 序列化
    def to_dict(self) -> dict:
        """固定键序（kind/ts/actor/fields/tags）—— JSONL 往返逐字节一致的前提。"""
        return {"kind": self.kind, "ts": self.ts, "actor": self.actor,
                "fields": dict(self.fields), "tags": list(self.tags)}

    @classmethod
    def from_dict(cls, data: Mapping) -> "Record":
        if not isinstance(data, Mapping):
            return cls(kind=str(data))
        return cls(kind=data.get("kind", ""), ts=data.get("ts", 0.0),
                   actor=data.get("actor", ""), fields=data.get("fields") or {},
                   tags=data.get("tags") or ())

    def has_tag(self, tag: str) -> bool:
        return tag in self.tags


@dataclass
class KindSpec:
    """一个 kind 的声明（全为通用形状字段）。

    * `kind`     —— 点号字符串标识
    * `fields`   —— 该 kind 携带的字段名列表（读的人按它取）
    * `desc`     —— 说明（编辑器/文档）
    * `category` —— 分类（编辑器分组；取值由内容侧定义）
    * `tags`     —— 该 kind 惯用的标签（约定，不强制）
    """

    kind: str
    fields: tuple = ()
    desc: str = ""
    category: str = ""
    tags: tuple = ()

    @classmethod
    def from_dict(cls, data: Mapping, key: Optional[str] = None) -> "KindSpec":
        if not isinstance(data, Mapping):
            return cls(kind=str(key or data))
        f = data.get("fields", ())
        t = data.get("tags", ())
        return cls(kind=str(key or data.get("kind", data.get("key", ""))),
                   fields=tuple(f or ()), desc=str(data.get("desc", "") or ""),
                   category=str(data.get("category", "") or ""), tags=tuple(t or ()))

    def to_dict(self) -> dict:
        out = {"kind": self.kind}
        if self.fields:
            out["fields"] = list(self.fields)
        for k in ("desc", "category"):
            v = getattr(self, k)
            if v:
                out[k] = v
        if self.tags:
            out["tags"] = list(self.tags)
        return out


class KindTable:
    """kind 声明表：装载 / 查询 / 自检。**不装载 = 不校验（零行为）**。"""

    def __init__(self, entries=None, *, name: str = "") -> None:
        self.name = name
        self._specs: dict = {}
        self._order: list = []
        if entries:
            self.load(entries)

    # ---------------------------------------------------------- 装载
    def register(self, spec, *, replace: bool = False) -> KindSpec:
        if not isinstance(spec, KindSpec):
            spec = KindSpec.from_dict(spec)
        if spec.kind in self._specs and not replace:
            raise ValueError("kind 重复：%r（要覆盖请 replace=True）" % spec.kind)
        if spec.kind not in self._specs:
            self._order.append(spec.kind)
        self._specs[spec.kind] = spec
        return spec

    def extend(self, items: Iterable, *, replace: bool = False) -> "KindTable":
        for it in items or ():
            self.register(it, replace=replace)
        return self

    def load(self, items) -> "KindTable":
        """装载声明；`{kind: {fields: [...]}}` / `{kind: [...]}` / `[{...}]` 都认。"""
        if isinstance(items, Mapping):
            for k, v in items.items():
                if isinstance(v, Mapping):
                    self.register(KindSpec.from_dict(v, key=k))
                elif isinstance(v, (list, tuple)):
                    self.register(KindSpec(kind=str(k), fields=tuple(v)))
                else:
                    self.register(KindSpec(kind=str(k)))
            return self
        return self.extend(items)

    @classmethod
    def from_data(cls, items, **kw) -> "KindTable":
        return cls(items, **kw)

    # ---------------------------------------------------------- 查询
    def keys(self) -> tuple:
        return tuple(self._order)

    def spec(self, kind: str) -> Optional[KindSpec]:
        return self._specs.get(kind)

    def fields_of(self, kind: str) -> tuple:
        s = self._specs.get(kind)
        return s.fields if s is not None else ()

    def has(self, kind: str) -> bool:
        return kind in self._specs

    def by_category(self) -> dict:
        out: dict = {}
        for k in self._order:
            out.setdefault(self._specs[k].category, []).append(self._specs[k])
        return {k: tuple(v) for k, v in out.items()}

    def __len__(self) -> int:
        return len(self._order)

    def __contains__(self, kind) -> bool:
        return kind in self._specs

    def __iter__(self):
        return (self._specs[k] for k in self._order)

    # ---------------------------------------------------------- 校验 / 自检
    def validate(self) -> list:
        """查声明自身问题（kind 命名非法 / 字段名非法 / 重复字段）。**只报告不抛。**"""
        problems = []
        for s in self:
            if not is_valid_kind(s.kind):
                problems.append("kind 命名非法：%r（应形如 battle.hit）" % s.kind)
            seen = set()
            for f in s.fields:
                if not _FIELD_RE.match(str(f or "")):
                    problems.append("%s：字段名非法 %r" % (s.kind, f))
                if f in seen:
                    problems.append("%s：字段重复 %r" % (s.kind, f))
                seen.add(f)
        return problems

    def check_record(self, record: Record) -> list:
        """一条记录与声明的差异（未声明 kind / 未声明字段 / 缺字段）。"""
        spec = self._specs.get(record.kind)
        if spec is None:
            return ["未声明的 kind：%s" % record.kind]
        got, declared = set(record.fields), set(spec.fields)
        out = []
        extra = sorted(got - declared)
        lack = sorted(declared - got)
        if extra:
            out.append("%s：出现未声明字段 %s" % (record.kind, extra))
        if lack:
            out.append("%s：缺少声明字段 %s" % (record.kind, lack))
        return out

    def audit(self, seen_kinds=()) -> dict:
        """自检汇总：声明未发过（疑似死声明）/ 发过但未声明（漏登记）。"""
        seen = list(seen_kinds or ())
        return {
            "total": len(self._order),
            "unused": [k for k in self._order if k not in seen],
            "undeclared": [k for k in seen if k not in self._specs],
            "problems": self.validate(),
        }

    def to_data(self) -> list:
        return [s.to_dict() for s in self]
