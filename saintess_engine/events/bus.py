# -*- coding: utf-8 -*-
"""领域事件总线骨架 —— 「一个事实发生了，多个订阅方各自反应并回填输出」。

与引擎内部事件总线的区别（两者互补，不是重复）
------------------------------------------------
| | `saintess_engine.effect_triggers` | 本模块 |
|---|---|---|
| 层级 | **战斗内**（actor 级，CTB 时序里） | **领域级**（账号/公会/世界级，战斗之外） |
| 时机 | 引擎固定点位 `fire(event, ctx)` | 业务编排点显式发布 |
| 订阅方 | 效果声明（数据） | 代码回调 |

为什么「分段拼接 + 段落空行」也在骨架里：这是**多订阅方各自产出提示行 → 顺序合并
输出**的通用形状（每个游戏都要做这件事），不是某只游戏的排版偏好。
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional, Sequence

from ..log import get_logger
from ..log.warn import WarnMixin

__all__ = ["EventBus"]

_LOG = get_logger("events")


class EventBus(WarnMixin):
    _warn_logger = _LOG                    # 未注入 logger 时的兜底（见 log.warn）
    """注册制领域事件总线。

    参数
    ----
    events:        起始事件名集合（**由使用方声明** —— 框架不预设任何事件名）。
                   「先枚举再扩展」能防拼写漂移：register 一个没声明的事件会被拒。
    strict_register: True（默认）= register 未知事件 `raise ValueError`（防拼写静默失效）；
                    False = 自动 declare 后注册。
    tolerant_fire:  True（默认）= 订阅方抛异常时 log + 跳过（不阻断后续订阅方）。
    blank_line_default: 段落空行的默认策略（单个订阅可用 `blank_line=` 覆盖）。
    logger:        传入 logger；None → 用门面 logger（`<prefix>.events`）。

    典型用法::

        bus = EventBus(("order_paid", "order_refunded"))
        bus.on("order_paid", send_receipt)
        bus.on("order_paid", bump_stats)
        lines = bus.fire("order_paid", {"order": o})
    """

    def __init__(self, events: Iterable[str] = (), *,
                 strict_register: bool = True,
                 tolerant_fire: bool = True,
                 blank_line_default: bool = True,
                 sink_key: str = "lines",
                 logger=None) -> None:
        self._events: list[str] = []
        self._registry: dict[str, list[tuple[Callable, bool]]] = {}
        for ev in events:
            self.declare(ev)
        self.strict_register = strict_register
        self.tolerant_fire = tolerant_fire
        self.blank_line_default = blank_line_default
        self.sink_key = sink_key
        self._logger = logger

    # ------------------------------------------------------------ 事件集
    def declare(self, *names: str) -> None:
        """声明事件名（幂等；声明序被保留，便于诊断与文档）。"""
        for n in names:
            if not n:
                raise ValueError("事件名不得为空")
            if n not in self._registry:
                self._registry[n] = []
                self._events.append(n)

    @property
    def events(self) -> tuple[str, ...]:
        """已声明事件（声明序）。"""
        return tuple(self._events)

    def has(self, event: str) -> bool:
        return event in self._registry

    def subscribers(self, event: str) -> tuple:
        """某事件的订阅方（注册序）—— 诊断/测试用。"""
        return tuple(cb for cb, _b in self._registry.get(event, ()))

    # ------------------------------------------------------------ 订阅
    def on(self, event: str, subscriber: Callable, *,
           blank_line: Optional[bool] = None) -> None:
        """注册订阅方（**注册序 = 执行序 = 输出行序**）。

        subscriber(ctx) -> Sequence[str] | None
        * `ctx` 由发布方构造；总线会补 `ctx["event"]`，并把 `ctx[sink_key]` 当行收集器
        * 返回 None / [] = 本段无输出
        * `blank_line`：该段输出前是否补一个空行（None → 用 `blank_line_default`）
        """
        if event not in self._registry:
            if not self.strict_register:
                self.declare(event)
            else:
                raise ValueError(
                    f"未知事件 {event!r}；已声明：{tuple(self._events)}"
                    f"（先 declare() 或设 strict_register=False）")
        self._registry[event].append(
            (subscriber, self.blank_line_default if blank_line is None else bool(blank_line)))

    # 兼容常见命名（register 与 on 同义）
    register = on

    def unsubscribe(self, event: str, subscriber: Callable) -> int:
        """移除某订阅方（返回移除条数）—— 测试/动态装配用。"""
        subs = self._registry.get(event)
        if not subs:
            return 0
        keep = [(cb, b) for cb, b in subs if cb is not subscriber]
        removed = len(subs) - len(keep)
        self._registry[event] = keep
        return removed

    def clear(self, event: Optional[str] = None) -> None:
        """清空订阅（`event=None` 清全部）。"""
        if event is None:
            for ev in self._registry:
                self._registry[ev] = []
        elif event in self._registry:
            self._registry[event] = []

    # ------------------------------------------------------------ 发布
    def fire(self, event: str, ctx: dict, *,
             tolerant: Optional[bool] = None) -> list:
        """发布事件：按注册序执行订阅方，把各段合并进 `ctx[sink_key]` 并返回它。

        * 未声明事件：log warning + 返回当前收集器（**不 raise** —— 语义扩展期容忍）
        * 订阅方异常：`tolerant` 为真（默认取 `tolerant_fire`）时 log + 跳过该订阅方
        """
        tol = self.tolerant_fire if tolerant is None else bool(tolerant)
        if event not in self._registry:
            self._warn("fire 未知事件 %r，忽略", event)
            return ctx.setdefault(self.sink_key, [])
        lines = ctx.setdefault(self.sink_key, [])
        ctx["event"] = event
        subs = self._registry[event]
        if not subs:
            return lines
        for subscriber, blank in subs:
            try:
                seg = subscriber(ctx)
            except Exception:
                if not tol:
                    raise
                self._warn("订阅方 %r 异常，跳过（事件 %s）",
                           getattr(subscriber, "__name__", subscriber), event)
                continue
            if not seg:
                continue
            if blank and lines and lines[-1] != "":
                lines.append("")
            lines.extend(seg)
        return lines

    # ------------------------------------------------------------ 内部
