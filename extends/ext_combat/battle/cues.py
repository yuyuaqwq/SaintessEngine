# -*- coding: utf-8 -*-
"""战斗表现层 cue —— **已迁移**的点位表 + 发事件的过渡口。

用法（迁移后的调用点，一行）

    _cue(battle, logs, "battle.landing.dodged", "💨 {name} 闪避了攻击！",
         {"name": target.get("name", "目标")})

    · 总线在（内容侧声明过 `cue_subs_fn`）⇒ 事件交订阅者渲染，**就地在同一个 logs 上 append**；
    · 总线不在（这款游戏还没声明 cue）⇒ **原路** `render_via` + append ——
      过渡期的「不装配 = 不存在」语义，输出与迁移前**逐字节相同**；
    · 收口批（B5）把兜底模板删掉、把 `bus is None` 改成 fail-closed 抛之后，
      「文案单源 = 内容侧」才真正成立。

命名：cue 名**沿用**既有的日志 key（`<域>.<来源>.<动作>`，中性词），不造新词汇 ——
内容侧将来要声明的表键与今天的 key 完全同名，迁移不需要映射表（映射表 = 双源温床）。
"""
from __future__ import annotations

from saintess_engine.config import EngineNotConfigured
from saintess_engine.cues import build_bus
from saintess_engine.text import render_or

from .diagnostics import diag as _diag

__all__ = ["CUE_NAMES", "build_cue_bus", "cue", "cue_of"]

#: **已迁移**的 cue 名（随批次增长）。未迁移的点位**不进**本集合 —— 它们今天压根不发事件。
CUE_NAMES = (
    "battle.landing.dodged",
    "battle.landing.element_immune",
    "battle.landing.resist_reduce",
)


def build_cue_bus(text=None):
    """按 `CUE_NAMES` + 内容侧订阅表建总线（内容侧没声明 ⇒ None）。

    `strict=True`：装配期对账发现问题**当场抛**（缺订阅 / 多订阅 / 同 cue 双 text）。
    """
    return build_bus(CUE_NAMES, table=text, strict=True)


def cue_of(battle):
    """取一场战斗的 cue 总线（没装 = None）。"""
    return getattr(battle, "cues", None)


def cue(battle, logs: list, name: str, default: str = "", payload=None) -> None:
    """发一条表现事件（点位迁移后**唯一**的出口 —— 没有第二条路）。

    口径（单一真源 + fail-closed，不留兼容分支）：

    * **有总线** ⇒ 交订阅者渲染（同步就地 append，顺序 = 声明序）。
    * **没有总线 / 该 cue 没有订阅者** ⇒ 这是**装配缺口**（内容侧该声明 `cue_subs_fn`）：
      记诊断 + 出一行可读的坏数据行。**绝不落回引擎旧路**（那条路 = 双源，
      正是本次迁移要拆掉的东西）；也**绝不静默丢行**。
    * ★ **表现层出什么事都不许改结算**：`emit` 抛（表坏 / 订阅者抛）同样走
      「诊断 + 一行坏数据」。为什么必须这样：已迁移的点位（`deal_damage` 的元素
      免疫/抗性段、`_roll_dodge`）**都住在 `try/except` 里**，异常冒出去会被外层
      `except` 吞掉，**并且跳过紧随其后的 `return 0` / `return True`**
      ⇒ 后果不是「少一行」，而是**免疫/闪避判定被跳过、伤害照常落地**（结算被改）。
      所以「异常要响」在这条路径上的落法 = **诊断通道**（不进玩家可见日志）——
      内容侧探针本来就钉着「整场战斗 diagnostics 必须为空」，响了就有人管。
    """
    bus = cue_of(battle)
    if bus is not None:
        try:
            bus.emit(logs, name, default, payload)
            return
        except Exception as _e:                                # noqa: BLE001
            _diag(battle, "cue().emit", _e)
    else:
        _diag(battle, "cue()", EngineNotConfigured(
            "cue %r 发了但这场战斗没有 cue 总线：内容侧该在 cue_subs_fn 里声明订阅表" % name))
    _cue_broken_line(logs, name)


def _cue_broken_line(logs: list, name: str) -> None:
    """缺口/异常时的可读坏数据行（**不**经过旧模板 —— 那条路已删）。"""
    logs.append(render_or(None, "cue.render_failed",
                          "⚠️ 这条表现没渲染出来（cue 装配/文案缺口，见诊断）", name=name))
