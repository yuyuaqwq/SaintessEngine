# -*- coding: utf-8 -*-
"""表现事件（cue）—— 「结算只发事实，表现由订阅方渲染」的**有序总线**。

与事件总线（`effect_triggers.EVENTS` / `fire`）的分工
--------------------------------------------------
两者**并行、不合并**，因为协议面和消费者面都不同：

    fire()   = **效果触发**协议：有主体过滤、订阅者会改 actor 状态（26 个事件）；
    cue      = **表现**协议：无主体过滤、订阅者**只读**、同步**就地** append 到同一个 logs。

为什么要有它：结算函数里原先「算值 → 选模板 → 填槽位 → 决定顺序」写在同一条语句里，
于是「玩家看到什么」无法与「算了什么」分开验证（也无法让别的消费者——流水/面板/音效——
在不改结算的前提下接上）。本模块只提供**形状**：一条有序订阅表 + 一个同步 emit。

三条硬规矩（形状即可判、不靠自觉）
--------------------------------
1. **同步 + 就地**：`emit` 逐条 append 到调用方给的 `logs` 列表，**无队列/无异步/无合并/无排序**。
2. **只读契约**：订阅者拿到的 `payload` 只读（不许改 actor / 不许写盘 / 不许读时钟）。
   `kind="call"` 的订阅者默认**不许**产出日志行；要产出行必须显式声明 `emits_lines: True`。
3. **fail-closed 四层**（`strict=True`）：
   * **装配期对账**（`audit_subs`）：已声明的 cue 名缺订阅 / 订阅表里有引擎不认的名字 /
     同一 cue 声明 ≥2 个 `kind="text"` ⇒ 抛，并一次列全问题；
   * **运行期**：`emit` 时该 cue 没有任何订阅者 ⇒ 抛 `EngineNotConfigured`（**不静默丢行、
     不由引擎替它编一句兜底**）；
   * **文案必须命中**（★ 2026-09-27 B2）：`kind="text"` 的渲染走 `render_required`
     ⇒ **表不在 / 表里没这个 key 就抛**。「已迁移」点位的模板**已从引擎删掉**，
     引擎手里没有任何措辞可回落 —— 缺表/缺 key 就是内容侧漏声明，不许静默补齐；
   * **诊断面**（`strict=False`）：以上各条都不崩 —— 问题记进 `bus.problems`，
     缺订阅 / 缺 key 时就地写一条可读的「坏数据」行（**不是**措辞兜底）。

订阅表形状（内容侧声明，引擎**只转述不解释**）
--------------------------------------------
    {cue 名: (订阅者, ...)}

    {"kind": "text", "key": "<文案表 key>"}          # 措辞留在内容侧文案表；引擎给槽位
    {"kind": "call", "handler": <callable>,          # 已由内容侧装配层解析成可调用对象
     "emits_lines": False}                           # True 才允许它产出日志行

装载口：`saintess_engine.config` 的 hook `cue_subs_fn`（`fn() -> Mapping | None`）；
措辞走 `Battle(text=…)` 注入的内容侧文案表（`render_or` / `__contains__` 鸭子类型）。
**不装配 = 这款游戏不用 cue**（引擎连问都不问，返回 `None`）。
"""
from __future__ import annotations

from typing import Callable, Mapping, Optional, Sequence

from .config import EngineNotConfigured, optional_hook
from .text import render_required

__all__ = ["MISS_LINE", "CueContractError", "CueBus", "audit_subs", "build_bus",
           "normalize_subs"]

#: 缺口/异常时的**可读坏数据行** —— 它说的是「这条表现没渲染出来（见诊断）」，
#: 而**不是**「原本该显示的那句话」：引擎不再持有任何措辞，所以这里也不许有兜底文案。
MISS_LINE = "⚠️ 这条表现没渲染出来（cue 装配/文案缺口，见诊断）"


class CueContractError(RuntimeError):
    """cue 声明/回执不合契约（装配期对账、订阅者回执形状、只读契约）。"""


_KINDS = ("text", "call")


def normalize_subs(raw) -> dict:
    """把内容侧给的订阅表规范化成 `{cue 名: tuple[dict, ...]}`（形状不对 ⇒ 抛）。"""
    if not isinstance(raw, Mapping):
        raise CueContractError(
            "cue_subs_fn 的回执要一张映射（{cue 名: 订阅者…}），拿到 %s" % type(raw).__name__)
    out: dict = {}
    for name, subs in raw.items():
        _name = str(name or "")
        if not _name:
            raise CueContractError("cue 订阅表里有空名字")
        if isinstance(subs, Mapping):
            subs = (subs,)
        if not isinstance(subs, (list, tuple)) or not subs:
            raise CueContractError("cue %r 的订阅者要是非空的 订阅者/序列" % _name)
        norm = []
        for sub in subs:
            if not isinstance(sub, Mapping):
                raise CueContractError(
                    "cue %r 的订阅者要是映射（含 kind），拿到 %s" % (_name, type(sub).__name__))
            kind = str(sub.get("kind") or "")
            if kind not in _KINDS:
                raise CueContractError(
                    "cue %r 的订阅者 kind 只能是 %s 之一，拿到 %r" % (_name, "/".join(_KINDS), kind))
            if kind == "text" and not str(sub.get("key") or ""):
                raise CueContractError("cue %r 的 text 订阅者缺 key（文案表 key 不能省）" % _name)
            if kind == "call" and not callable(sub.get("handler")):
                raise CueContractError(
                    "cue %r 的 call 订阅者 handler 必须是可调用对象（字符串请由内容侧装配层"
                    "先解析成 callable）" % _name)
            norm.append(dict(sub))
        out[_name] = tuple(norm)
    return out


def audit_subs(names: Sequence[str], subs: Mapping) -> list:
    """装配期对账 —— 返回**可读问题清单**（空 = 合格）。

    * 声明里有、订阅表里没有 ⇒ 玩家会丢行；
    * 订阅表里有、声明里没有 ⇒ 拼写漂移 / 引擎不认的名字；
    * 同一 cue 声明 ≥2 个 `kind="text"` ⇒ 行数会凭空变多（有意差异必须走另一条路）。
    """
    probs: list = []
    want = [str(n) for n in names]
    have = set(subs)
    missing = [n for n in want if n not in have]
    if missing:
        probs.append("缺订阅的 cue：%s（共 %d 条）" % (", ".join(missing), len(missing)))
    extra = sorted(have - set(want))
    if extra:
        probs.append("订阅表里有引擎不认的 cue：%s（拼写漂移 / 已废弃）" % ", ".join(extra))
    for name, subs_ in subs.items():
        n_text = sum(1 for s in subs_ if str(s.get("kind")) == "text")
        if n_text >= 2:
            probs.append("cue %r 声明了 %d 个 kind=text 订阅者（一行会变成多行）" % (name, n_text))
    return probs


class CueBus:
    """有序订阅表 + 同步 emit（唯一的对外用法：`bus.emit(logs, name, payload)`）。"""

    def __init__(self, subs: Mapping, table=None, strict: bool = True,
                 problems: Optional[list] = None) -> None:
        self.subs = dict(subs)
        self.table = table          # 内容侧文案表（鸭子类型同 `text.render_or`）
        self.strict = bool(strict)
        self.problems = list(problems or [])

    def subs_of(self, name: str) -> tuple:
        return self.subs.get(str(name)) or ()

    def emit(self, logs: list, name: str, payload=None) -> None:
        """把一条表现事件渲染出来并**就地** append 到 `logs`（顺序 = 订阅者声明序）。

        ★ 没有 `default` 参数（2026-09-27 B2）：措辞真源在内容侧文案表，
        引擎手里没有模板可传 ⇒ `kind="text"` 的渲染走「必须命中」口（见 `_render`）。
        """
        subs = self.subs_of(name)
        if not subs:
            if self.strict:
                raise EngineNotConfigured(
                    "cue %r 没有任何订阅者：装配缺口（内容侧该在 cue_subs_fn 里声明它）"
                    % (name,))
            logs.append("%s 无订阅者（装配缺口）" % name)
            return
        slots = dict(payload or {})
        # ★ 先全部渲染、再一次 append。原先逐行 append：中途某个订阅者抛
        #   `CueContractError` 时，前面订阅者已写进 `logs` 的**真行留了下来**
        #   （实测 `['第一行:7']` 残留在抛错后的 logs 里）⇒ 一次 cue 半渲染 =
        #   半条真行 + 一条坏数据行，与本模块头注「同步就地、无合并」和
        #   `MISS_LINE` 的「不静默丢行」自相矛盾。
        out: list = []
        for sub in subs:
            out.extend(self._render(sub, str(name), slots))
        logs.extend(out)

    def _render(self, sub: Mapping, name: str, slots: dict) -> list:
        if str(sub.get("kind")) == "text":
            key = str(sub.get("key") or name)
            try:
                line = render_required(self.table, key, **slots)
            except KeyError as _e:
                # ★ 引擎手里没有措辞可回落（该点位的模板已随迁移删掉）⇒ **现形**：
                #   strict 抛；诊断面记问题 + 就地一行可读坏数据（绝不静默丢行）。
                prob = "cue %r 的文案 key %r 没命中内容侧文案表（%s）" % (name, key, _e)
                if self.strict:
                    raise CueContractError(prob) from _e
                if prob not in self.problems:
                    self.problems.append(prob)
                return [MISS_LINE]
            return [line] if line else []
        fn = sub.get("handler")
        if not callable(fn):
            raise CueContractError("cue %r 的 call 订阅者不可调用：%r" % (name, fn))
        got = fn(dict(slots))
        if got is None:
            return []
        if isinstance(got, str):
            out = [got] if got else []
        elif isinstance(got, (list, tuple, set, frozenset)):
            out = [str(x) for x in got if x not in (None, "")]
        else:
            raise CueContractError(
                "cue %r 的 call 订阅者回执形状不对：要 None / str / 序列[str]，拿到 %s"
                % (name, type(got).__name__))
        if out and not sub.get("emits_lines"):
            raise CueContractError(
                "cue %r 的 call 订阅者产出了日志行却没声明 emits_lines=True（只读契约："
                "要出行必须显式声明，否则「谁的行排在哪」不可推）" % (name,))
        return out


def build_bus(names: Sequence[str], table=None, strict: bool = True,
              hook: str = "cue_subs_fn") -> Optional[CueBus]:
    """按引擎声明的 cue 名集合 + 内容侧订阅表建总线。

    * 内容侧**没装配** `cue_subs_fn` ⇒ `None`（这款游戏不用 cue，引擎连问都不问）；
    * 装了 ⇒ 规范化 + 装配期对账（`strict=True` 时有问题就抛，一次列全）。
    """
    fn: Optional[Callable] = optional_hook(hook)
    if fn is None:
        return None
    subs = normalize_subs(fn())
    probs = audit_subs(names, subs)
    if probs and strict:
        raise CueContractError("cue 装配期对账失败：\n  - " + "\n  - ".join(probs))
    return CueBus(subs, table=table, strict=strict, problems=probs)
