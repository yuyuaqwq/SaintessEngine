# -*- coding: utf-8 -*-
"""《铆炉回声》文案表 —— 本包**唯一**的玩家可见措辞真源。

为什么要有它（cue 解耦 B1 / B2 / B3 / B4）
------------------------------------------
引擎不再自己拼句：结算只发「表现事件」（cue），措辞从本表按 key 取。已迁移点位的
模板**已从引擎删掉**（B1 3 条 + B2 14 条 + B3 25 条 + B4 18 条 = **60 条**，
覆盖 `battle.landing.*` / `battle.effects.*` / `battle.core.*` / `battle.schedule.*` /
`battle.actions.*` / `battle.gauge.*`）—— 本表缺一条 ⇒ 那条表现**渲染不出来**
（引擎记诊断 + 出一行可读坏数据），**不会有**任何引擎兜底（回落 = 影子真源，
正是解耦要拆掉的东西）。

key 命名 = 引擎的 cue 名（同名即接口，不造映射表）；`content/cues.py` 的订阅表只写 key。
注入：`content/apply.py::install_engine()` 挂 hook `text_table_fn` ⇒
凡本包进程里构造的 `Battle(...)` 都拿到这张表（显式 `Battle(text=…)` 仍然优先）。
"""
from __future__ import annotations

from saintess_engine.text import TextTable

#: key（= cue 名）→ 逐字模板。★ 从引擎调用点**逐字**搬来（一个字符都不许漂）：
#: 各批都由搬运脚本按原样字符串生成；B3 另有 1 条原先**未键化**的裸 f-string 现补 key
#: （`battle.effects.stack_add`）。
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
    # ★ B5（2026-09-28 状态容器收口第 2 批）：承伤减免读点（引擎第一次真正读 `taken_pct`
    #   这一族 —— 原先只有写、没有读）。措辞是新点位（引擎侧从来没有过模板），
    #   槽位 = 承伤者名 + 实际生效的减免百分比（已按内容侧封顶 clamp）。
    "battle.landing.taken_reduce": "🛡️ {name} 减免了 {pct}% 承伤！",
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


#: 装载好的文案表（同一份数据 → 同一张表；`Battle(text=TEXT)` / hook `text_table_fn`）
TEXT = TextTable(TEMPLATES, name="minimal-game")

__all__ = ["TEMPLATES", "TEXT"]
