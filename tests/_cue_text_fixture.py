# -*- coding: utf-8 -*-
"""★ 门禁夹具（**不是真源**）—— 引擎门禁自用的最小文案表 + cue 订阅表。

为什么放在 `tests/` 下
----------------------
引擎门禁大量用「**合成 Battle**」（不接任何内容包）验证引擎行为。B2 起「已迁移点位」的
措辞真源在**内容侧文案表**（引擎侧模板已删）⇒ 这些用例必须自己注入一张表，
否则碰到那些行拿到的是「一行坏数据 + 一条诊断」，断言文案的用例会集体变红。

**真源**是各游戏包自己的文案表（如 `examples/minimal-game/content/texts.py`）——
本文件这 60 条是它们的**副本**，只服务于引擎门禁（不让引擎门禁依赖某个具体内容包的措辞）。
两份串必须逐字相同（`tests/test_cues_shape.py` 逐字对拍两者）。

跑法：不单独跑 —— 被门禁 import（`from _cue_text_fixture import TEXT, SUBS, install`）。
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_ROOT, os.path.join(_ROOT, "extends")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ext_combat.battle.cues import CUE_NAMES                          # noqa: E402
from saintess_engine.text import TextTable                            # noqa: E402

#: 已迁移点位的逐字文案（key = cue 名 = 文案表 key）
TEMPLATES = {
    "battle.landing.dodged": "💨 {name} 闪避了攻击！",
    "battle.landing.element_immune": "💠 免疫！【{name}】免疫{element}伤害！",
    "battle.landing.resist_reduce": "🛡️ 元素抗性减免 {red} 点伤害！",
    "battle.landing.damage": "💥 {name} 受到 {dmg} 点伤害！",
    "battle.landing.down": "💥 {name} 受到 {dmg} 点伤害，倒下了！",
    "battle.landing.shield_absorb": "🛡️ {name} 的护盾吸收了 {absorb} 点伤害！",
    "battle.landing.blocked_amount": "(格挡后 {dmg} 点伤害)",
    "battle.landing.block_reduce": "🛡️ 格挡！减免 {red} 点伤害！",
    "battle.landing.phys_immune": "🪨 物理免伤，减免 {red} 点物理伤害！",
    "battle.landing.magic_resist": "🛡️ 魔法抗性，减免 {red} 点魔法伤害！",
    "battle.landing.element_weak": "⚡ 弱点！【{name}】弱{element}，受到额外伤害！",
    "battle.landing.woken": "💥 目标被攻击惊醒！",
    "battle.landing.guard_cover": "🛡️ 【{guard}】替【{target}】挡下了这一击！",
    "battle.landing.death_guard": "✨ {name} 濒死意志触发，保住了性命！",
    "battle.landing.heal_shared": "✨ 治疗由【{name}】分担",
    "battle.landing.heal_forbid": "🩸 禁疗：治疗量 -{pct}%！",
    "battle.landing.heal_wound": "🩸 重伤：治疗量 -{pct}%！",
    "battle.core.no_actor": "没有可行动的玩家！",
    "battle.core.finished": "战斗已结束！",
    "battle.core.silenced": "🤐 {name} 被沉默，无法使用技能！(只能普攻/防御)",
    "battle.core.controlled": "💫 {name} 被【{tag}】控制，无法行动！",
    "battle.core.unknown_action": "未知行动类型：{action}",
    "battle.schedule.cast_begin": "🌀 {name} 开始出招…",
    "battle.core.defend": "🛡 {name} 摆出防御姿态，受到的伤害减半！",
    "battle.core.fled": "💨 {name} 逃跑了！",
    "battle.effects.immune_control": "🛡️ {name} 免疫控制：{key} 未生效",
    "battle.effects.stack_applied": "💫 {name} 被【{key}】{turns} 刻！",
    "battle.effects.immune_debuff": "🚫 {name} 免疫【{key}】，异常未生效",
    "battle.effects.stack_set": "✦ {key} 置为 {n}",
    "battle.effects.shield_pct": "🛡️ {value:.0%}（持续 {turns} 刻）",
    "battle.effects.buff_boost": "✦ {key} 提升（{op}×{mult}，持续 {turns} 刻）",
    "battle.effects.on_hit_ready": "✦ {key} 出手效果就绪（{turns} 刻内生效）",
    "battle.effects.stack_active": "✦ {key}（持续 {turns} 刻）",
    "battle.effects.stack_short": "⚠️ {key} 不足（需 {amount}，当前 {cur}）",
    "battle.effects.stack_spent": "✦ 消耗 {amount} 点 {key}（剩余 {left}）",
    "battle.effects.shield_gain": "🛡️ {name} 获得护盾 {value} 点！",
    "battle.effects.cleansed": "✨ 净化了 {names}！",
    "battle.effects.cleanse_none": "✨ 净化（无减益可解）",
    "battle.effects.healed": "✨ {name} 恢复了 {heal} 点生命！",
    "battle.effects.cast_broken": "💥 {name} 的出招被打断了！",
    "battle.effects.damaged": "💥 {name} 受到 {dmg} 点伤害！",
    "battle.effects.stack_add": "✦ {key} {n}{cap}（+{amount}）",
    "battle.actions.no_target": "但没有可攻击的目标！",
    "battle.actions.skill_cd": "⏳ 【{name}】冷却中：还需 {left:.1f} 刻！",
    "battle.actions.resource_lack": "⚡ 核心资源不足：需要 {rv:g} {rk}，当前 {cur:g}！",
    "battle.actions.enchant_followup": "{tag} 附魔追击，追加 {dmg} 点伤害！",
    "battle.actions.effect_on": "✨ {key} 生效！",
    "battle.actions.lifesteal": "🩸 吸血：回复 {heal} 点生命！",
    "battle.actions.skill_heal_full": "你施展【{name}】，圣光治愈了你 {heal} 点生命！",
    "battle.actions.skill_heal": "你施展【{name}】，治愈了 {heal} 点生命！",
    "battle.actions.skill_cast": "你施展【{name}】！",
    "battle.schedule.actor_turn": "—— {name} 行动 ——",
    "battle.schedule.dot_tick": "🔥 {name} 受 {key} {n} 层影响，损失 {dmg} 生命",
    "battle.schedule.regen_hp": "🍲 {name} 持续恢复，恢复 {heal} 点生命！",
    "battle.schedule.regen_mp": "🍲 {name} 持续恢复，恢复 {heal} 点魔力！",
    "battle.gauge.gain": "💥 {bar} 积蓄 +{add}（{val}/{maxcap}）",
    "battle.gauge.trigger": "💢 【{bar}】触发！(第 {count} 次)",
    "battle.gauge.shaken": "💢 【{name}】被{bar}震慑，无法行动！",
    "battle.gauge.phase_preserve": "💢【{name}】阶段更迭：{bar}积蓄保留 {pct}%（{before} → {after}）",
    "battle.gauge.reflect": "🪨 反震：反弹 {dmg} 点伤害！",

}

_MISSING = sorted(set(CUE_NAMES) - set(TEMPLATES))
if _MISSING:
    raise AssertionError("夹具文案表缺已迁移点位：%s（迁移新点位时同批补这里）" % _MISSING)

#: 夹具文案表（`Battle(text=TEXT)`）
TEXT = TextTable(TEMPLATES, name="tests-fixture")


def subs(names=None) -> dict:
    """`cue_subs_fn` 供体形状：每个 cue 名一条 `kind=text`（key = cue 名）。"""
    return {n: ({"kind": "text", "key": n},) for n in (names or CUE_NAMES)}


#: 覆盖全部已迁移点位的订阅表
SUBS = subs()


def install(names=None):
    """把夹具订阅表挂进 `config._HOOKS["cue_subs_fn"]`；返回**还原函数**（用完请调）。"""
    from saintess_engine import config as CFG

    saved = CFG._HOOKS.get("cue_subs_fn")
    CFG._HOOKS["cue_subs_fn"] = lambda: subs(names)

    def _restore():
        CFG._HOOKS["cue_subs_fn"] = saved

    return _restore


__all__ = ["SUBS", "TEMPLATES", "TEXT", "install", "subs"]
