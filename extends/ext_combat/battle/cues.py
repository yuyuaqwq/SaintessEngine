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

__all__ = ["CUE_NAMES", "TIME_SLOT", "build_cue_bus", "cue", "cue_of", "with_now"]

#: ★ payload 里「绝对时刻」这一格的键名（2026-09-28）。
#:
#: 形状：**每**一条 cue 的 payload 都带这一格，一个都不例外（`with_now` 是唯一补它的地方）。
#: 为什么必须「每条都给」而不是「用到才给」：内容侧的渲染口是 `safe_format`
#: （`saintess_engine/text/template.py`）—— 缺槽位**不抛**，而是把字面量
#: ``{t}`` 原样吐到玩家屏上。那是一种只在真机上、且只在没走到那条分支时才显形的问题。
#: 缺格还会在包侧文案表里留下一个「看起来能用的假槽位」，让缺口更难被看见。
#:
#: 为什么是 `t`：中性词，只声明「这是时间轴上的一个位置」，不声明单位、不声明怎么显示 ——
#: 单位与呈现全归内容侧（引擎不内置任何措辞，见本模块头注「引擎没有任何模板可回落」）。
#: 全仓核过：`t` 在引擎侧没有任何同名槽位/占位符占用。
TIME_SLOT = "t"

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
    # ---- B5（1 条 · 状态容器收口第 2 批：承伤减免读点）----
    "battle.landing.taken_reduce",
    # ---- B6（1 条 · 承伤减免两条通道互斥：声明通道优先，乘区被跳过时说清走了哪条）----
    "battle.landing.taken_mult_skipped",
    # ---- B3（25 条 · effects 16 + battle.py 9）----
    "battle.core.no_actor",
    "battle.core.finished",
    "battle.core.silenced",
    "battle.core.controlled",
    "battle.core.unknown_action",
    "battle.schedule.cast_begin",
    "battle.core.defend",
    "battle.core.fled",
    "battle.effects.immune_control",
    "battle.effects.stack_applied",
    "battle.effects.immune_debuff",
    "battle.effects.stack_set",
    "battle.effects.shield_pct",
    "battle.effects.buff_boost",
    "battle.effects.on_hit_ready",
    "battle.effects.stack_active",
    "battle.effects.stack_short",
    "battle.effects.stack_spent",
    "battle.effects.shield_gain",
    "battle.effects.cleansed",
    "battle.effects.cleanse_none",
    "battle.effects.healed",
    "battle.effects.cast_broken",
    "battle.effects.damaged",
    "battle.effects.stack_add",
    # ---- B4（18 条 · actions 9 + schedule 4 + gauge 5；`regen_mp` 两处同 key）----
    "battle.actions.no_target",
    "battle.actions.skill_cd",
    "battle.actions.resource_lack",
    "battle.actions.enchant_followup",
    "battle.actions.effect_on",
    "battle.actions.lifesteal",
    "battle.actions.skill_heal_full",
    "battle.actions.skill_heal",
    "battle.actions.skill_cast",
    "battle.schedule.actor_turn",
    "battle.schedule.dot_tick",
    "battle.schedule.regen_hp",
    "battle.schedule.regen_mp",
    "battle.gauge.gain",
    "battle.gauge.trigger",
    "battle.gauge.shaken",
    "battle.gauge.phase_preserve",
    "battle.gauge.reflect",
)


def build_cue_bus(text=None):
    """按 `CUE_NAMES` + 内容侧订阅表建总线（内容侧没声明 ⇒ None）。

    `strict=True`：装配期对账发现问题**当场抛**（缺订阅 / 多订阅 / 同 cue 双 text）。
    """
    return build_bus(CUE_NAMES, table=text, strict=True)


def cue_of(battle):
    """取一场战斗的 cue 总线（没装 = None）。"""
    return getattr(battle, "cues", None)


def now_of(battle) -> float:
    """取一场战斗的**绝对时刻**（秒；战斗未推进时 = 0）。

    ★ 不新增钟源：直接读引擎内部那一个（`Battle._now`，绝对时刻制 v152 起）。
    重复实现一份「怎么取时刻」= 第二个钟源，日后必然与真钟漂移。
    这里只做**形状收口**，不重新定义时间。

    ★ 为什么收口必须是 **给 0 但不出静默兜底**：`now_of` 在 `cue()` 的 `try` **之内**被求值
    （`bus.emit(logs, name, with_now(...))`）—— 若这里抛，异常会被转成「诊断 + 一行坏数据」，
    于是**一个脏时钟就能让整条表现事件消失**（住在 `try/except` 里的已迁移点位连结算判定
    一起被跳过）。所以给 0（一个诚实的时刻），不抛。

    ★ 但「给 0」**不等于**可以悄悄给 0：脏时钟意味着时间轴算错了（后面每一次 CD / 状态
    过期都会跟着错），那是**别人要处理**的事 ⇒ 走诊断通道（`diag`），不是静默吞掉。
    门禁 `tests/test_no_silent_fallback.py` 钉的正是这条（`except` 要么记诊断、要么显式抛）。
    """
    # 函数内 import：`battle.py` 也在本包内，模块顶层互相 import 会成环。
    from .battle import _now_of
    try:
        return float(_now_of(battle) or 0.0)
    except (TypeError, ValueError) as _e:
        # 记诊断（内容侧探针钉着「整场 diagnostics 必须为空」⇒ 脏时钟当场有人管），
        # 然后给 0：表现事件照发，玩家少看到的是时刻，不是整行。
        _diag(battle, "cue().now_of", _e)
        return 0.0


def with_now(battle, payload=None) -> dict:
    """给任意 payload 补上「绝对时刻」那一格（`TIME_SLOT`），返回**新** dict。

    这是补时刻的**唯一**实现（唯一出口 `cue()` 走它）—— 门禁 `tests/test_cues_shape.py` §8
    钉住「每条 cue 的 payload 必含 `TIME_SLOT`」，所以新加 cue 名不需要在这里补任何一行。

    三条口径：

    1. **调用点已有的 `t` 不被覆盖**（调用点赢）—— 时刻由**发出那一刻**的 `Battle._now` 决定，
       不是由调用点自己编的数决定。真的会有调用点想覆盖时，门禁会当场红。
    2. **给不了就 0，不静默缺格**：`battle` 为 None / 没有 `_now` / 值非法 ⇒ 0。
       0 是「此刻确实在开战前」的合法取值（见下），所以它不与「没给」混淆 ——
       **没给**才是要杜绝的状态。
    3. **不写进调用点传进来的那个 dict**（`emit` 只读契约：订阅者拿到的必须是副本，
       原件也不能被我们偷偷改掉）。
    """
    out = dict(payload or {})
    if TIME_SLOT in out:
        return out
    out[TIME_SLOT] = now_of(battle)
    return out


def cue(battle, logs: list, name: str, payload=None) -> None:
    """发一条表现事件（点位迁移后**唯一**的出口 —— 没有第二条路，也没有 `default`）。

    ★ 没有 `default` 参数（2026-09-27 B2）：已迁移点位的模板**已从引擎删掉** ⇒
    措辞真源只剩内容侧文案表；调用点只给 cue 名 + 槽位，不再给任何兜底串。

    ★ 出口职责（2026-09-28）：**在这里**给 payload 补上「绝对时刻」那一格。
    补在这一个地方而不是补在 62 个调用点里，是因为这层是「一条 cue 要不要发」的唯一决策点
    —— 补在上面就自动覆盖将来新增的点位，不会漏（漏了 ⇒ 包侧把字面量 `{t}` 打到玩家屏上）。
    """
    bus = cue_of(battle)
    if bus is not None:
        try:
            bus.emit(logs, name, with_now(battle, payload))
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
    ★ 这一行**不**带时刻：它不是一次表现事件（没有订阅者渲染过），是诊断行。
    时刻由 `MISS_LINE` 自己的措辞决定要不要报 —— 归内容侧，引擎不编。
    """
    logs.append(render_or(None, "cue.render_failed", MISS_LINE, name=name))
