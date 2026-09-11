# -*- coding: utf-8 -*-
"""《铆炉回声》——本游戏的声明表（引擎只查表，不认识表里的任何字）。

四张表的边界（照 wiki：concepts/declaration-tables.md）：

    EFFECT_ACTIONS   引擎读 —— 游戏名词 → 引擎动词序列
    EFFECT_RULES     引擎读 —— key 的行为规则（cap / stat_scale / panel / period / consume）
    MECH_CASH        引擎不读 —— 本游戏用 res_cost + heat_vent 表达，故留空
    PASSIVE_PROC     引擎不读 —— 由本游戏的装配器（apply.py）翻成 actor["triggers"]

另外两张「公式参数表」是本游戏给引擎 formulas 模块的参数（S5 注入面）：
FORMULA_SKELETON / SKILL_FLAT。数值全是本游戏自己编的，与奥兰迪亚无关。
"""
from __future__ import annotations

# kind 语义词表（引擎零 kind 字面量：它只用 config.kind_of(name) 查这张表）
KIND_NAMES = {
    "phys": "冲击",
    "magi": "灼热",
    "true": "贯穿",
    "heal": "充能",
    "buff": "调律",
}

# ============================================================
# EFFECT_RULES —— key 的行为规则（引擎消费）
# ============================================================
EFFECT_RULES = {
    # 职业资源：炉温。cap 6；每层 +2% 攻击（stat_scale 由 stats.py 直接折进面板）
    # channels 是本平台的「攒取渠道」声明 —— 引擎不读，由本包装配器翻译成 triggers
    "kiln": {
        "name": "炉温",
        "cap": 6,
        "start_classes": ["cls_kiln"],
        "stat_scale": {"atk": 0.02},
        "channels": {
            "attack_hit": 1,                                   # 普攻命中 +1
            "taken": {"gain": 1,                               # 被拘束时受击 +1
                      "when": [{"judge": {"kind": "has_effect", "key": "clamp"}}]},
        },
    },
    # 职业资源：回声。cap 4；技能命中 +1
    "echo": {
        "name": "回声",
        "cap": 4,
        "start_classes": ["cls_whistle"],
        "channels": {"skill_hit": 1},
    },
    # DOT：锈蚀。挂在目标身上，每刻按最大生命 1.5% × 层数掉血，跳 3 次后消失
    "rust": {
        "name": "锈蚀",
        "cap": 2,
        "on": "target",
        "period": {"dir": "damage", "interval": 1.0, "pct_max_hp": 0.015, "turns": 3},
    },
    # 控制：铁钳拘束。mode=skip → 被拘束者整个行动被跳过（引擎 battle.act 消费）
    "clamp": {
        "name": "铁钳拘束",
        "consume": {"mode": "skip"},
    },
}

# ============================================================
# EFFECT_ACTIONS —— 名词 → 动词（引擎消费）
# ============================================================
EFFECT_ACTIONS = {
    # 「铁钳拘束」这个名词翻成 apply 动词。
    # ⚠️ 坑①（见 README）：两条都得显式写 ——
    #    "key"：apply 从 params.key/tag/mech 取要写的容器键，裸触发器 {"type": "clamp"}
    #           不带这三个字段 → act_apply 直接 return（静默 no-op）；
    #    "on": "target"：apply 的 on 缺省是 "caster"，漏写会把「拘束」挂到自己身上。
    "clamp": [{"action": "apply", "key": "clamp", "on": "target", "turns": 1}],
}

# ============================================================
# MECH_CASH / PASSIVE_PROC —— 内容侧约定，引擎不读
# ============================================================
# 本游戏的机制「按层增伤 + 耗层」直接写在技能 res_cost + heat_vent 动词里，
# 所以不需要 MECH_CASH 这套兑现约定（留空 = 明确表示「不采用」）。
MECH_CASH = {}

# 被动 proc：受击后按自身攻击力 5% 反击来源
PASSIVE_PROC = {
    "backdraft": {
        "name": "回火",
        "event": "on_taken",
        "action": "backdraft",
        "params": {"pct": 0.35},
        "start_classes": ["cls_kiln"],
    },
}

# ============================================================
# 公式参数表（喂给引擎 formulas 模块的 S5 注入面）
# ============================================================
FORMULA_SKELETON = {
    "skill_growth": {
        "power_per_lv_divisor": 100,
        "buff_turns_base": 3,
        "buff_turns_per_lv": 1,
        "cond_default": 0.05,
        "mech_default_div": 2,
        "lifesteal_default": 0.2,
        "lifesteal_per_lv_divisor": 100,
    },
    "skill_learn_cost": {"divisor": 6, "base": 2},
}

# 技能基础值：flat = BASE + 玩家等级×PER_PLAYER_LV + 技能等级×PER_SKILL_LV
SKILL_FLAT = {
    "SKILL_FLAT_BASE": 8,
    "SKILL_FLAT_PER_PLAYER_LV": 1,
    "SKILL_FLAT_PER_SKILL_LV": 2,
}
