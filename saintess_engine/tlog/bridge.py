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

from typing import Iterable, Mapping, Optional

from .core import TLog

__all__ = ["EventLogBridge"]

#: `TLog.emit` 的保留参数名 —— 不得再作为流水字段名传进 `emit(**fields)`。
#: 传进来的 ctx 里本来就带 `actor`（`actor_keys` 的第一个键）。
#: 同名键直接传过去会报 ``TypeError: got multiple values for keyword argument``，
#: 而总线默认 `tolerant_fire` 只记一句 warning 就跳过 ⇒ **流水无声丢失**。
_RESERVED_FIELDS = frozenset({"kind", "actor", "tags", "fields"})


class EventLogBridge:
    """把总线事件翻译成流水记录。

    参数
    ----
    tlog:       目标流水
    mapping:    `{事件名: kind}` 或 `{事件名: {"kind":..., "fields":[...], "tags":[...]}}`
    actor_keys: 从 ctx 里按顺序找"归属主体"的键名（找不到则 actor 留空）
    drop:       不进 fields 的内部键（总线自己的行收集器/事件名）。
                `kind`/`actor`/`tags`/`fields` 是 emit 保留名，**永远不进 fields**，不受此参数影响
    strict:     True 时未在映射表里的事件**抛错**（联调用）；False（默认）跳过并记入 missed
    """

    def __init__(self, tlog: TLog, mapping: Mapping, *,
                 actor_keys: Iterable[str] = ("actor", "qq_id", "uid", "player"),
                 drop: Iterable[str] = ("lines", "event"), strict: bool = False) -> None:
        self.tlog = tlog
        self.mapping = dict(mapping or {})
        self.actor_keys = tuple(actor_keys)
        self.drop = set(drop) | set(_RESERVED_FIELDS)   # 保留名永远不进 fields（见 _RESERVED_FIELDS）
        self.strict = bool(strict)
        self.missed: list = []            # 未映射但被订阅到的事件
        # ★ 记「事件 + 当初挂上去的那个订阅方对象」：`bus.unsubscribe` 按 `is`
        #   比身份，而 `subscriber(ev)` 每调一次就新造一个闭包 ⇒ 只存事件名
        #   的话撤不回来（`is not` 恒真 ⇒ 移除 0 条，还得靠 clear() 连别人的一起清）。
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
            sub = self.subscriber(ev)
            bus.on(ev, sub)
            self._attached.append((ev, sub))
            n += 1
        return n

    def detach(self, bus) -> int:
        """撤掉**自己**挂的订阅。返回真撤掉的事件数。

        ★ 只撤本桥挂上去的那几个回调（`bus.unsubscribe` 按对象身份逐个摘）——
        原实现走 `bus.clear(ev)`，那是「清空该事件的**全部**订阅方」：
        同一事件上别人的订阅（内容侧、别的扩展包）会被一起抹掉，事件从此静默失联
        （实测：detach 后别人的订阅方调用次数 0，detach 还照样返回成功数）。
        挂过、却摘不到（已被人提前撤掉）**不静默当成功** —— 那是状态对不上，抛。
        本桥从未 attach / 已撤干净时挂表为空 ⇒ 返回 0（无动作的幂等空转）。
        """
        n = 0
        for ev, sub in list(self._attached):
            if not bus.unsubscribe(ev, sub):
                raise RuntimeError(
                    "桥未挂在该事件上，detach 无从撤起（可能已被人提前撤掉）：%r" % ev)
            n += 1
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
            if k in self.drop or k in _RESERVED_FIELDS:
                continue
            if allow and k not in allow:
                continue
            if isinstance(v, (str, int, float, bool)) or v is None:
                out[str(k)] = v
            else:
                out[str(k)] = str(v)          # 非标量转文本：保证流水可 JSON 落盘
        return out
