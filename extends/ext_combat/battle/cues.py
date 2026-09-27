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

from saintess_engine.cues import build_bus
from saintess_engine.text import render_via

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
    """发一条表现事件（点位迁移后唯一的出口）。"""
    bus = cue_of(battle)
    if bus is None:
        # 过渡态：内容侧还没声明 cue ⇒ 走原路，逐字节等于迁移前的内联渲染
        logs.append(render_via(battle, name, default, **(payload or {})))
        return
    bus.emit(logs, name, default, payload)
