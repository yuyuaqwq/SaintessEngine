# -*- coding: utf-8 -*-
"""《铆炉回声》文案表 —— 本包**唯一**的玩家可见措辞真源。

为什么要有它（cue 解耦 B1 / B2）
--------------------------------
引擎不再自己拼句：结算只发「表现事件」（cue），措辞从本表按 key 取。已迁移点位的
模板**已从引擎删掉**（B1 的 3 条 + B2 的 14 条 = 落地接口层的 17 条 `battle.landing.*`）
—— 本表缺一条 ⇒ 那条表现**渲染不出来**（引擎记诊断 + 出一行可读坏数据），
**不会有**任何引擎兜底（回落 = 影子真源，正是解耦要拆掉的东西）。

key 命名 = 引擎的 cue 名（同名即接口，不造映射表）；`content/cues.py` 的订阅表只写 key。
注入：`content/apply.py::install_engine()` 挂 hook `text_table_fn` ⇒
凡本包进程里构造的 `Battle(...)` 都拿到这张表（显式 `Battle(text=…)` 仍然优先）。
"""
from __future__ import annotations

from saintess_engine.text import TextTable

#: key（= cue 名）→ 逐字模板。★ 从引擎调用点**逐字**搬来（一个字符都不许漂）：
#: 搬运脚本按 `battle.landing.*` 的原样字符串生成，不手抄。
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
}


#: 装载好的文案表（同一份数据 → 同一张表；`Battle(text=TEXT)` / hook `text_table_fn`）
TEXT = TextTable(TEMPLATES, name="minimal-game")

__all__ = ["TEMPLATES", "TEXT"]
