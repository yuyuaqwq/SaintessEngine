# -*- coding: utf-8 -*-
"""事件总线 → 流水（桥）。

**为什么要有桥**：领域事件是「实时」的（订阅方各自反应），流水是「可查/可回放」的。
两者互补而不是重复：总线管"发生即分发"，流水管"事后能查"。

**映射表由内容侧给**（框架不认任何事件名）：:

    bridge = EventLogBridge(tlog, {
        "order_paid":   "shop.paid",                                  # 简写：事件名 → kind
        "battle_end":   {"kind": "battle.end", "fields": ["win", "rounds"], "tags": ["battle"]},
    })
    bridge.attach(bus)

订阅方**不产出提示行**（返回 None）—— 它是旁路，不改变既有输出。
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from .core import TLog

__all__ = ["EventLogBridge"]


class EventLogBridge:
    """把总线事件翻译成流水记录。

    参数
    ----
    tlog:       目标流水
    mapping:    `{事件名: kind}` 或 `{事件名: {"kind":..., "fields":[...], "tags":[...]}}`
    actor_keys: 从 ctx 里按顺序找"归属主体"的键名（找不到则 actor 留空）
    drop:       不进 fields 的内部键（总线自己的行收集器/事件名）
    strict:     True 时未在映射表里的事件**抛错**（联调用）；False（默认）跳过并记入 missed
    """

    def __init__(self, tlog: TLog, mapping: Mapping, *,
                 actor_keys: Iterable[str] = ("actor", "qq_id", "uid", "player"),
                 drop: Iterable[str] = ("lines", "event"), strict: bool = False) -> None:
        self.tlog = tlog
        self.mapping = dict(mapping or {})
        self.actor_keys = tuple(actor_keys)
        self.drop = set(drop)
        self.strict = bool(strict)
        self.missed: list = []            # 未映射但被订阅到的事件
        self._attached: list = []

    # ---------------------------------------------------------- 配置
    def cfg_of(self, event: str) -> Optional[dict]:
        raw = self.mapping.get(event)
        if raw is None:
            return None
        if isinstance(raw, Mapping):
            return {"kind": str(raw.get("kind", event)),
                    "fields": tuple(raw.get("fields") or ()),
                    "tags": tuple(raw.get("tags") or ())}
        return {"kind": str(raw), "fields": (), "tags": ()}

    def kind_of(self, event: str) -> Optional[str]:
        c = self.cfg_of(event)
        return c["kind"] if c else None

    # ---------------------------------------------------------- 订阅
    def subscriber(self, event: str):
        """造一个订阅方（总线按注册序调用它）；未映射事件按 `strict` 处理。"""
        def _sub(ctx: dict):
            c = self.cfg_of(event)
            if c is None:
                if self.strict:
                    raise KeyError("事件未映射到流水 kind：%r" % event)
                if event not in self.missed:
                    self.missed.append(event)
                return None
            self.tlog.emit(c["kind"], actor=self._actor_of(ctx or {}),
                           tags=c["tags"], **self._fields_of(ctx or {}, c))
            return None                                   # 旁路：不产出提示行
        return _sub

    def attach(self, bus, events: Optional[Iterable[str]] = None) -> int:
        """挂到总线上（`events` 省略 = 映射表的键 ∩ 总线已声明事件）；返回订阅数。"""
        if events is None:
            declared = set(bus.events)
            events = [e for e in self.mapping if e in declared]
        n = 0
        for ev in events:
            bus.on(ev, self.subscriber(ev))
            self._attached.append(ev)
            n += 1
        return n

    def detach(self, bus) -> int:
        """撤掉自己挂的订阅（按事件清空该事件的订阅方）。返回清掉的事件数。"""
        n = 0
        for ev in list(self._attached):
            try:
                bus.clear(ev)
                n += 1
            except Exception:                                 # noqa: BLE001
                pass
        self._attached = []
        return n

    # ---------------------------------------------------------- 内部
    def _actor_of(self, ctx: dict) -> str:
        for k in self.actor_keys:
            v = ctx.get(k)
            if v not in (None, ""):
                return str(v)
        return ""

    def _fields_of(self, ctx: dict, cfg: dict) -> dict:
        allow = set(cfg["fields"])
        out: dict = {}
        for k, v in ctx.items():
            if k in self.drop:
                continue
            if allow and k not in allow:
                continue
            if isinstance(v, (str, int, float, bool)) or v is None:
                out[str(k)] = v
            else:
                out[str(k)] = str(v)          # 非标量转文本：保证流水可 JSON 落盘
        return out
