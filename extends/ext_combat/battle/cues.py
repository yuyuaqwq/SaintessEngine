# -*- coding: utf-8 -*-
"""战斗表现层 cue —— **已迁移**的点位表 + 发事件的唯一出口。

用法（迁移后的调用点，一行）

    _cue(battle, logs, "battle.landing.dodged", {"name": target.get("name", "目标")})

三条口径（单一真源 + fail-closed，**不留兼容分支**）

* **有总线** ⇒ 交订阅者渲染（同步就地 append，顺序 = 声明序）。措辞来自
  `Battle(text=…)` 注入的内容侧文案表；`kind=text` 的渲染是「**必须命中**」口
  （`render_required`）—— 表里没有该 key ⇒ 报错（诊断 + 一行可读坏数据）。
  引擎**没有任何模板可回落**：这个点位的措辞已随迁移从引擎删掉（★ 2026-09-27 B2）。
* **没有总线 / 该 cue 没有订阅者** ⇒ 这是**装配缺口**（内容侧该在 `cue_subs_fn`
  里声明订阅表）：记诊断 + 出一行可读的坏数据行。**绝不落回引擎旧路**（那条路 = 双源，
  正是本次迁移要拆掉的东西）；也**绝不静默丢行**。
* ★ **表现层出什么事都不许改结算**：`emit` 抛（表缺 key / 订阅者抛）同样走
  「诊断 + 一行坏数据」。为什么必须这样：已迁移的点位（`deal_damage` 的元素
  免疫/抗性段、`_roll_dodge`）**都住在 `try/except` 里**，异常冒出去会被外层
  `except` 吞掉，**并且跳过紧随其后的 `return 0` / `return True`**
  ⇒ 后果不是「少一行」，而是**免疫/闪避判定被跳过、伤害照常落地**（结算被改）。
  所以「异常要响」在这条路径上的落法 = **诊断通道**（不进玩家可见日志）——
  内容侧探针本来就钉着「整场战斗 diagnostics 必须为空」，响了就有人管。

命名：cue 名**沿用**既有的日志 key（`<域>.<来源>.<动作>`，中性词），不造新词汇 ——
内容侧将来要声明的表键与今天的 key 完全同名，迁移不需要映射表（映射表 = 双源温床）。
"""
from __future__ import annotations

from saintess_engine.config import EngineNotConfigured
from saintess_engine.cues import MISS_LINE, build_bus
from saintess_engine.text import render_or

from .diagnostics import diag as _diag

__all__ = ["CUE_NAMES", "build_cue_bus", "cue", "cue_of"]

#: **已迁移**的 cue 名（随批次增长）。未迁移的点位**不进**本集合 —— 它们今天压根不发事件。
#: ★ B2（2026-09-27）：landing 核心 14 点位同批迁移（B1 的 3 条不动）。
CUE_NAMES = (
    # ---- B1（3 条 · 最小切片）----
    "battle.landing.dodged",
    "battle.landing.element_immune",
    "battle.landing.resist_reduce",
    # ---- B2（14 条 · landing 核心）----
    "battle.landing.damage",
    "battle.landing.down",
    "battle.landing.shield_absorb",
    "battle.landing.blocked_amount",
    "battle.landing.block_reduce",
    "battle.landing.phys_immune",
    "battle.landing.magic_resist",
    "battle.landing.element_weak",
    "battle.landing.woken",
    "battle.landing.guard_cover",
    "battle.landing.death_guard",
    "battle.landing.heal_shared",
    "battle.landing.heal_forbid",
    "battle.landing.heal_wound",
)


def build_cue_bus(text=None):
    """按 `CUE_NAMES` + 内容侧订阅表建总线（内容侧没声明 ⇒ None）。

    `strict=True`：装配期对账发现问题**当场抛**（缺订阅 / 多订阅 / 同 cue 双 text）。
    """
    return build_bus(CUE_NAMES, table=text, strict=True)


def cue_of(battle):
    """取一场战斗的 cue 总线（没装 = None）。"""
    return getattr(battle, "cues", None)


def cue(battle, logs: list, name: str, payload=None) -> None:
    """发一条表现事件（点位迁移后**唯一**的出口 —— 没有第二条路，也没有 `default`）。

    ★ 没有 `default` 参数（2026-09-27 B2）：已迁移点位的模板**已从引擎删掉** ⇒
    措辞真源只剩内容侧文案表；调用点只给 cue 名 + 槽位，不再给任何兜底串。
    """
    bus = cue_of(battle)
    if bus is not None:
        try:
            bus.emit(logs, name, payload)
            return
        except Exception as _e:                                # noqa: BLE001
            _diag(battle, "cue().emit", _e)
    else:
        _diag(battle, "cue()", EngineNotConfigured(
            "cue %r 发了但这场战斗没有 cue 总线：内容侧该在 cue_subs_fn 里声明订阅表" % name))
    _cue_broken_line(logs, name)


def _cue_broken_line(logs: list, name: str) -> None:
    """缺口/异常时的可读坏数据行（**不**经过旧模板 —— 那条路已删）。

    措辞与 `saintess_engine.cues.MISS_LINE` **同一份**（一个字符串常量）：
    两条路（引擎诊断面 / 本层兜底）在玩家眼里必须是同一句话。
    """
    logs.append(render_or(None, "cue.render_failed", MISS_LINE, name=name))
