# -*- coding: utf-8 -*-
"""《奥兰迪亚》武器/词条特效族（we_procs）参数表 —— 逐字搬运物（P4-D2）。

真源：游戏仓 `C:/Users/yuyu/qqbot/data/plugins/dragonfall/game/data/weapon_effect_data.py:27`
      → `WEAPON_EFFECT_DATA`（82 条 = 79 + D3 增量 3；本文件用 `python -c` import 真源模块后 dump 成字面量，
      键序/数值/文案**逐字未改**，未经人手誊抄）。
      D3 增量 3 条（divine_execution / dragon_annihilation / star_destruction）为 2026-09-13
      手工加在真源与本文件**尾部同一位置、逐字相同**（对拍见 `overnight/d3_gap_fix_verify.py` A5）。

另：`ACT_TICK` 逐字抄自 `game/core/constants.py:156`
    （`ACT_TICK = 1.0        # 1 刻 = 1.0 时刻 = 1 游戏秒（鱼鱼拍板对齐秒）`；
    真源 `battle_we_procs.py:251/341/517/692/730` 的 `from ..core.constants import ACT_TICK`
    → 本包 `from .we_data import ACT_TICK`。引擎侧 `schedule.py` 同口径：1 刻 = 1 时刻 = 1 游戏秒。）

接线状态（诚实标注，勿静默）：本批 27 个动作**没有**任何一处直接 import `WEAPON_EFFECT_DATA`
（真源 `battle_we_procs.py` 同样不 import 它——动作全部参数化，数值由装配层
`battle_equip_proc` 从数据表翻译后写进 params）。本表按 P4-D2 要求先逐字入库，供装配层接线。
"""
from __future__ import annotations

# 1 刻 = 1.0 时刻 = 1 游戏秒（真源 game/core/constants.py:156，逐字）
ACT_TICK = 1.0

WEAPON_EFFECT_DATA = {
    "starlight_bulwark": {"family": "proc_shield", "shield_hp_pct": 0.1, "turns": 3, "refresh_turns": 5, "shield_key": "we_starlight", "next_key": "we_starlight_next", "log": "✨ 星辉壁垒：战斗开始获得 10% 最大生命护盾！"},
    "gale_step": {"family": "proc_buff", "stacks": 1, "spd_pct": 0.15, "turns": 3, "buff_key": "gale_step", "buff_pct_key": "gale_step_pct", "log": "🌪️ 疾风步：速度 +15%（3 刻）！"},
    "swift_boots": {"family": "proc_buff", "stacks": 1, "spd_pct": 0.2, "turns": 3, "buff_key": "gale_step", "buff_pct_key": "gale_step_pct", "log": "🌪️ 迅捷如风：速度 +20%（3 刻）！"},
    "deadman_stride": {"family": "proc_buff", "stacks": 2, "spd_pct": 0.15, "turns": 4, "buff_key": "gale_step", "buff_pct_key": "gale_step_pct", "log": "🌪️ 亡者疾行：速度 +15%（4 刻）！"},
    "temple_stride": {"family": "proc_buff", "stacks": 2, "spd_pct": 0.2, "turns": 4, "buff_key": "gale_step", "buff_pct_key": "gale_step_pct", "log": "🌪️ 圣殿疾行：速度 +20%（4 刻）！"},
    "void_stride": {"family": "proc_buff", "stacks": 2, "spd_pct": 0.25, "turns": 4, "buff_key": "gale_step", "buff_pct_key": "gale_step_pct", "log": "🌪️ 虚空疾行：速度 +25%（4 刻）！"},
    "abyss_barrier": {"family": "proc_buff", "max_hp_pct": 0.08, "stat_key": "max_hp", "log": "🌑 深渊屏障：最大生命 +{bonus}！（持续整场）"},
    "eclipse_crown": {"family": "proc_shield", "shield_hp_pct": 0.15, "spd_pct": 0.1, "next_atk_pct": 0.15, "turns": 99, "shield_key": "we_eclipse", "active_key": "we_eclipse_active", "log": "🌒 蚀月之蚀：获得 15% 最大生命护盾！"},
    "arcane_firmament": {"family": "proc_passive_mult", "event": ["battle_start", "passive"], "matk_pct": 0.15, "skill_dmg_pct": 0.1, "mark_key": "we_arcane_firmament", "log": "✨ 奥术苍穹：魔攻 +15%，技能伤害 +10%！"},
    "undying_will": {"family": "proc_dr_revive", "event": ["battle_start", "threshold"], "hp_pct": 0.1, "threshold": 0.2, "heal_pct": 0.1, "used_key": "we_undying_used", "immune_key": "we_undying_immune", "log": "✨ 不灭意志：免疫致死伤害！"},
    "wind_mark": {"family": "proc_stack", "max_stack": 4, "spd_pct_per": 0.02, "stack_key": "wind_mark", "log": "🌬️ 风痕叠加！({n}/4 层，每层速度 +2%)"},
    "hunter_open": {"family": "proc_extra_dmg", "mode": "true_dmg_nth", "count": 3, "atk_pct": 0.12, "stack_key": "hunter_cnt"},
    "smith_blaze_wound": {"family": "proc_dot", "chance": 0.2, "dot_pct": 0.015, "dot_pct_boss": 0.01, "turns": 3, "dot_key": "blaze"},
    "rong_lu_yu_wen": {"family": "proc_dot", "chance": 0.2, "dot_pct": 0.03, "dot_pct_boss": 0.015, "turns": 2, "dot_key": "burn"},
    "frost_ring": {"family": "proc_control", "mode": "slow_or_freeze", "chance": 0.25, "slow_turns": 2, "slow_pct": 0.4, "freeze_turns": 1, "boss_slow": 2, "source": "🧊 霜环"},
    "blood_trace": {"family": "proc_dot", "chance": 0.25, "pct": 0.02, "pct_boss": 0.015, "turns": 4, "dot_key": "blood_trace", "log": "🩸 败血：目标 4 刻内每刻损失当前生命！（对败血目标 +10% 伤害）"},
    "wind_split": {"family": "proc_extra_dmg", "mode": "extra_phys", "chance": 0.25, "atk_pct": 0.5},
    "holy_judgment_field": {"family": "proc_control", "mode": "slow_heal_down", "chance": 0.3, "slow_turns": 2, "slow_pct": 0.3, "heal_down": 2, "source": "⚖️ 圣裁领域", "log": "⚖️ 圣裁领域：目标受治疗 -30%（2 刻）！"},
    "thunder_weave": {"family": "proc_stack", "event": ["hit", "passive"], "max_stack": 5, "spd_pct_per": 0.02, "atk_pct_per": 0.01, "charge_pct": 0.2, "stack_key": "thunder_weave", "charge_key": "we_thunder_charge", "log": "⚡ 雷纹连打！({n}/5 层，每层速度+2% 攻击+1%)"},
    "phantom_barrage": {"family": "proc_extra_dmg", "mode": "extra_phys_pene", "chance": 0.2, "atk_pct": 0.3, "pene_pct": 0.5, "guarantee": 5, "stack_key": "phantom_cnt", "log": "🌪️ 幻影连射！无视 50% 防御造成 {dmg} 点伤害！"},
    "siren_fang": {"family": "proc_extra_dmg", "mode": "true_dmg_nth", "count": 3, "atk_pct": 0.4, "stack_key": "siren_cnt"},
    "soul_eater": {"family": "proc_extra_dmg", "mode": "curhp_dmg_heal", "cur_hp_pct": 0.02, "log": "💜 破败之吻：额外 {bonus} 点伤害，回复 {healed} 点生命！"},
    "star_pierce": {"family": "proc_extra_dmg", "mode": "true_dmg_nth", "count": 4, "atk_pct": 0.2, "lost_hp_pct": 0.03, "cap_pct": 0.05, "stack_key": "star_cnt"},
    "combo_end": {"family": "proc_passive_mult", "event": ["hit", "passive"], "combo_need": 3, "crit_dmg": 0.4, "mark_key": "we_combo_end"},
    "novice_lifesteal": {"family": "proc_extra_dmg", "mode": "lifesteal", "heal_pct": 0.05},
    "novice_hunt_combo": {"family": "proc_stack", "per_stack": 0.08, "max_stack": 5, "stack_key": "novice_combo", "log": "🎯 猎影：暴击叠层！（{n}/5 层，每层连击率 +{int(float(wd.get('per_stack', 0.08)) * 100)}%）"},
    "novice_wind_spd": {"family": "proc_buff", "spd_pct": 0.05, "turns": 2, "buff_key": "novice_wind_spd", "log": "🌪️ 翠风：自身速度 +5%（2 刻）！"},
    "afterglow_splash": {"family": "proc_extra_dmg", "mode": "splash_magi", "chance": 0.3, "atk_pct": 0.15},
    "spellblade_echo": {"family": "proc_extra_dmg", "mode": "splash_magi", "atk_pct": 0.25},
    "annihilation_echo": {"family": "proc_extra_dmg", "mode": "splash_magi", "chance": 0.35, "atk_pct": 0.3},
    "ember_burn": {"family": "proc_dot", "chance": 0.3, "dot_pct": 0.015, "dot_pct_boss": 0.01, "turns": 3, "dot_key": "ember"},
    "everfrost_domain": {"family": "proc_control", "mode": "freeze_cd", "chance": 0.3, "freeze_turns": 1, "boss_slow": 2, "cd": 3, "cd_key": "we_everfrost_cd", "source": "🧊 永冻领域"},
    "everfrost_scepter": {"family": "proc_control", "mode": "freeze", "chance": 0.2, "freeze_turns": 1, "boss_slow": 2, "source": "🧊 永霜禁锢"},
    "trinity_rhythm": {"family": "proc_next_atk_mark", "event": ["skill_hit", "passive"], "atk_pct": 0.3, "thunder_pct": 0.15, "mark_key": "we_trinity", "extra_key": "we_trinity_thunder"},
    "mountain_break": {"family": "proc_next_atk_mark", "event": ["skill_hit", "passive"], "atk_pct": 0.25, "mark_key": "we_mountain"},
    "oath_blade": {"family": "proc_next_atk_mark", "event": ["skill_hit", "passive"], "atk_pct": 0.25, "mark_key": "we_oath"},
    "endless_radiance": {"family": "proc_shield", "crit_dmg_pct": 0.25, "shield_hp_pct": 0.05, "shield_turns": 2, "cd": 3, "shield_key": "we_radiance", "cd_key": "we_radiance_cd", "log": "🌟 无尽辉光：暴击获得 5% 最大生命护盾！"},
    "endless_blade": {"family": "proc_extra_dmg", "mode": "extra_phys_oncrit", "atk_pct": 0.2, "used_key": "we_blade_used"},
    "rune_amp": {"family": "proc_stack", "event": ["skill_cast", "passive"], "max_stack": 5, "dmg_pct_per": 0.02, "per_pct": 0.02, "stack_key": "rune_amp", "log": "📜 铭文增幅！({n}/5 层，下一技能 +{int(n * float(wd.get('dmg_pct_per', 0.02)) * 100)}%)"},
    "sage_amp": {"family": "proc_stack", "event": ["skill_cast", "passive"], "need": 2, "charge_pct": 0.25, "stack_key": "sage_amp", "charge_key": "we_sage_charge"},
    "eternal_codex": {"family": "proc_stack", "event": ["skill_cast", "passive"], "max_stack": 8, "dmg_pct_per": 0.015, "per_pct": 0.015, "stack_key": "eternal_codex", "log": "📖 永恒契约！({n}/{_cap8} 层，每层技能伤害 +{float(wd.get('dmg_pct_per', 0.015)) * 100:.1f}%)"},
    "sentinel_aegis": {"family": "proc_shield", "chance": 0.15, "base": 6, "per_lv": 0.5, "turns": 3, "cd": 1, "shield_key": "we_sentinel", "cd_key": "we_sentinel_cd", "log": "🛡️ 哨兵壁垒：获得 {shield} 点护盾！（3 刻）"},
    "iron_echo": {"family": "proc_reflect", "chance": 0.2, "reflect_pct": 0.4, "heal_pct": 0.02},
    "frost_crown": {"family": "proc_control", "mode": "freeze_taken_limited", "chance": 0.1, "max_per_battle": 2, "freeze_turns": 1, "boss_slow": 2, "used_key": "we_frost_crown_cnt", "source": "🧊 寒霜凝视"},
    "thorn_armor": {"family": "proc_reflect", "reflect_pct": 0.15, "log": "🌵 荆棘缠绕：反弹 {rd} 点伤害！"},
    "guardian_will": {"family": "proc_retort_mark", "chance": 0.08, "weaken": 0.25, "debuff_key": "mon_atk_down", "log": "🛡️ 卫士信念：敌人下一次攻击伤害 -25%！"},
    "deeprock_aegis": {"family": "proc_shield", "chance": 0.1, "shield_pct": 0.08, "turns": 3, "cd": 2, "shield_key": "we_deeprock", "cd_key": "we_deeprock_cd", "log": "🪨 深岩壁垒：获得护盾！（吸收 8% 最大生命）"},
    "gargoyle_retort": {"family": "proc_retort_mark", "event": ["taken", "passive"], "next_atk_pct": 0.3, "fallback_pct": 0.2, "mark_key": "we_retort"},
    "titan_retort": {"family": "proc_retort_mark", "event": ["taken", "passive"], "next_atk_pct": 0.4, "fallback_pct": 0.2, "mark_key": "we_retort"},
    "ranger_retort": {"family": "proc_retort_mark", "event": ["taken", "passive"], "next_atk_pct": 0.2, "fallback_pct": 0.2, "mark_key": "we_retort"},
    "dragon_spine_mail": {"family": "proc_reflect", "chance": 0.15, "reflect_pct": 0.25, "heal_down": 2, "log": "🐉 龙脊反噬：反弹 {rd} 点伤害，并施加重伤！"},
    "retribution_ring": {"family": "proc_reflect", "chance": 0.2, "reflect_pct": 0.3, "log": "⚔️ 复仇之环：反弹 {rd} 点伤害！"},
    "ember_bulwark": {"family": "proc_reflect", "max_hp_pct": 0.05, "burn_stack": 1, "burn_cap": 5, "dot_key": "burn", "log": "🔥 烬火燎原：反伤 {dmg} 点并叠加灼烧！"},
    "vital_band": {"family": "proc_heal", "heal_pct": 0.15},
    "holy_radiance_mail": {"family": "proc_heal", "heal_pct": 0.2},
    "echo_band": {"family": "proc_heal", "heal_pct": 0.25},
    "echo_bless": {"family": "proc_shield", "overflow_pct": 0.3, "cap_hp_pct": 0.1, "turns": 3, "shield_key": "we_echo_bless", "log": "🌿 回响祝福：治疗溢出转化为 {shield} 点护盾！"},
    "atonement_shield": {"family": "proc_shield", "cap_hp_pct": 0.15, "turns": 3, "shield_key": "we_atonement", "active_key": "we_atonement_active", "log": "⚖️ 赎罪之盾：治疗溢出转化为 {shield} 点护盾！"},
    "holy_word_bind": {"family": "proc_control", "mode": "freeze_heal", "chance": 0.2, "freeze_turns": 1, "boss_slow": 2, "source": "✨ 圣言禁锢"},
    "novice_regen_heal": {"family": "proc_heal", "heal_pct": 0.1},
    "guard_regen": {"family": "proc_heal", "pct": 0.02},
    "dawn_regen": {"family": "proc_heal", "pct": 0.02},
    "undying_band": {"family": "proc_heal", "pct": 0.015},
    "death_dance": {"family": "proc_special", "event": ["battle_start", "turn_start"], "pool_pct": 0.35, "pay_pct": 0.1, "max_turns": 10, "pool_key": "we_death_pool", "log": "💀 死亡之舞：缓伤池结算，损失 {pay} 点生命！（剩余 {player.setdefault('eff', {})['we_death_pool']:.0f}）"},
    "time_staff": {"family": "proc_stack", "event": ["turn_start", "passive"], "per_pct": 0.015, "max_stack": 10, "stack_key": "time_staff", "log": "⏳ 岁月流转叠层！({n}/10 层，攻击 +{int(n * float(wd.get('per_pct', 0.015)) * 100)}%)"},
    "randuin_weary": {"family": "proc_control", "mode": "spd_down_stack", "max_stack": 3, "spd_down_pct": 0.06, "stack_key": "_randuin_stack", "log": "🛡️ 兰顿倦意：敌人速度 -{int(_sp * 100 * n)}%（{n}/{_ms} 层）！"},
    "ice_vein": {"family": "proc_control", "mode": "spd_down_stack", "max_stack": 3, "spd_down_pct": 0.08, "stack_key": "_ice_vein_stack", "log": "❄️ 冰脉寒流：敌人速度 -{int(_sp * 100 * n)}%（{n}/{_ms} 层）！"},
    "time_freeze": {"family": "proc_control", "mode": "threshold_stun", "threshold": 0.3, "per_battle": 1, "used_key": "we_time_freeze_used", "source": "⏳ 时光凝滞", "log": "⏳ 时光凝滞！敌人被定身，跳过一次行动！"},
    "bedrock_crown": {"family": "proc_shield", "threshold": 0.25, "shield_hp_pct": 0.2, "turns": 4, "shield_key": "we_bedrock", "used_key": "we_bedrock_used", "log": "🪨 磐石守护：生命垂危，获得 {shield} 点护盾！（4 刻）"},
    "firmament_crown": {"family": "proc_shield", "threshold": 0.3, "shield_hp_pct": 0.12, "turns": 3, "per_battle": 2, "shield_key": "we_firmament", "used_key": "we_firmament_cnt", "log": "🌌 苍穹庇护：获得 {shield} 点护盾！（{player.setdefault('eff', {})['we_firmament_cnt']}/2 次）"},
    "gargoyle_heart": {"family": "proc_shield", "threshold": 0.3, "shield_hp_pct": 0.25, "turns": 4, "heal_pct": 0.1, "shield_key": "we_gargoyle", "used_key": "we_gargoyle_used", "log": "💎 石像鬼之心：获得 {shield} 点护盾并回复 {heal} 点生命！"},
    "dusk_blade": {"family": "proc_next_atk_mark", "event": ["kill", "passive"], "next_atk_pct": 0.3, "atk_pct": 0.3, "mark_key": "we_dusk_dmg", "buff_key": "stealth", "used_key": "we_dusk_used", "log": "🌒 暮裂潜行：击杀后遁入暗影，下一次攻击 +30% 且无视闪避！"},
    "twilight_execute": {"family": "proc_passive_mult", "threshold": 0.4, "dmg_mult": 1.25},
    "star_slayer_edge": {"family": "proc_passive_mult", "threshold": 0.7, "dmg_mult": 1.15, "crit_dmg": 0.3},
    "death_dance_armor": {"family": "proc_dr_revive", "taken_reduce_pct": 0.08, "revive_hp_pct": 0.12},
    "novice_first_turn_guard": {"family": "proc_special", "reduce_pct": 0.1, "mark_key": "novice_guard_active", "log": "🛡️ 守御：首刻受击伤害 -10%！"},
    "novice_spark_followup": {"family": "proc_next_atk_mark", "atk_pct": 0.1, "stack_key": "novice_spark", "log": "✨ 星火：下次普攻伤害 +10%！"},
    "novice_first_turn_dodge": {"family": "proc_special", "dodge_pct": 0.05, "mark_key": "novice_dodge_active", "log": "💨 远行：首刻闪避率 +5%！"},
    "novice_dawn_mana": {"family": "proc_heal", "mp": 10, "used_key": "novice_mana_used", "log": "🌅 晨星：回复 10 点魔力！"},
    # ---- D3 增量（2026-09-13）：3 个「放错表」的 roster `weapon_effect` 键 ----
    # 真源形状在 affixes.py LEGENDARY_EFFECTS（:981 star_destruction / :986 dragon_annihilation
    # / :991 divine_execution，trigger:"passive"，effect {dmg_mult, enemy_contains|
    # execute_threshold, tag}）；roster 当 `weapon_effect` 引用（equip_roster.py:966/983/985）
    # → `_we_config` 只读本表 → cfg 恒 `{}` → 静默跳过（配置有、翻译器缺）。
    # 修法：抄进本表（family/event 对齐 proc_passive_mult），翻译器 = battle_equip_proc
    # `_translate_legend_mult`（dmg_calc 乘区）。LEGENDARY_EFFECTS 原条目**保留**：
    # 生成期 `drops._merge_legendary_stats` 只收 trigger=="stat" 条目 → 非 stat 条目零行为；
    # 删它要动包内 `legendary_effects.json`（不在本次改动面内）。
    "divine_execution": {"family": "proc_passive_mult", "event": ["passive"], "dmg_mult": 1.6, "execute_threshold": 0.3, "tag": "⚡神罚处决"},
    "dragon_annihilation": {"family": "proc_passive_mult", "event": ["passive"], "dmg_mult": 1.25, "enemy_contains": ["龙"], "tag": "🐉灭龙"},
    "star_destruction": {"family": "proc_passive_mult", "event": ["passive"], "dmg_mult": 1.3, "enemy_contains": ["深渊"], "tag": "☄️星陨湮灭"},
}
