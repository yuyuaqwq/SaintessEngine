# -*- coding: utf-8 -*-
"""《铆炉回声》——本游戏的声明表（引擎只查表，不认识表里的任何字）。

四张表的边界（照 wiki：concepts/declaration-tables.md）：

    EFFECT_ACTIONS   引擎读 —— 游戏名词 → 引擎动词序列
    EFFECT_RULES     引擎读 —— key 的行为规则（cap / stat_scale / panel / period / consume）
    MECH_CASH        引擎不读 —— 本游戏用 res_cost + heat_vent 表达，故留空
    PASSIVE_PROC     引擎不读 —— 由本游戏的装配器（apply.py）翻成 actor["triggers"]

另外两张「公式参数表」是本游戏给引擎 formulas 模块的参数（S5 注入面）：
FORMULA_SKELETON / SKILL_FLAT。数值全是本示例自己编的，与任何游戏包无关。

CTB 时间轴（行动耗时）也是引擎的注入面（`time_model_fn` / `action_base_fn`）：
本示例用**线性**形状（`base × spd_ref/spd`）而不是参考实现的 sqrt —— 这正是
「换一款游戏 = 换一套节奏，引擎一行不改」的演示。见下方 `TIME_MODEL`。
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

# ============================================================
# CTB 时间模型（喂给引擎 schedule 的注入面：time_model_fn / action_base_fn /
# recover_model_fn / recover_base_fn —— 两段：`cast` 出招 + `recover` 收招）
# ============================================================
# 引擎只留机制（谁 ct 小谁先动、行动后 ct = now + 本次耗时），形状与数值由本游戏给。
# 本游戏选 **linear**：一次行动耗时 = base × (spd_ref / max(spd, 1))；spd_cap=None 不截断。
# `cast` 的键就是引擎的动作类别通用键（attack/skill/defend/item…）；
# 引擎对未声明类别回落 `schedule.DEFAULT_ACTION`（= "attack"）。
# ★ 两段：`cast` = 第一段（出招），`recover` = 第二段（收招）。两段各按形状折算后相加。
#   本示例 `recover` 全 0 ⇒ 行为与「只有一段」逐字节相同（先落能力，数值按需再配）。
TIME_MODEL = {
    "shape": "linear",
    "spd_ref": 50.0,
    "cast": {"attack": 1.0, "skill": 1.6, "defend": 0.6, "item": 1.0},
    "recover": {"attack": 0.0, "skill": 0.0, "defend": 0.0, "item": 0.0},
    "spd_cap": None,
}
