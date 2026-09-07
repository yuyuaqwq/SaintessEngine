# -*- coding: utf-8 -*-
"""battle2 状态声明表（纯数据，无逻辑）——引擎查表折算，不认识 key 语义。

每个状态 key 声明"这个数值如何影响战斗"。引擎只做通用动作：
- cap：叠加上限
- stat_scale：每点 → 面板属性系数（atk+4%/层 = {"atk": 0.04}）
- dot：持续伤害（每刻按什么掉血，N4 schedule 消费）
- turns：带时效（N4 递减）
- on_threshold：层数达标触发动作（N4/上层模块消费）

⚠️ 表是"数据"不是"程序"——只声明固定几种规则类型，不写任意代码。
   新规则类型 = 引擎先补通用执行器，再在表里声明。
"""
from __future__ import annotations

# 结构示例（全部 key 以实际迁移为准逐步补）：
# "zhan_yi":   {"cap": 10, "stat_scale": {"atk": 0.04},
#               "on_threshold": {10: {"form": "fury"}}},
# "lian_duan": {"cap": 10},
# "rage":      {"cap": 10, "stat_scale": {"dmg_mult": 0.12}},
# "hunt_mark": {"cap": 3, "debuff_scale": {"dmg_taken": 0.08}},
# "burn":      {"cap": 5, "dot": {"pct_max_hp": 0.03}},

STATE_EFFECTS: dict = {
    # ============ 通用叠层/资源（玩家侧） ============
    "zhan_yi": {
        "cap": 10,
        "stat_scale": {"atk": 0.04},          # 每层攻击 +4%（持有即生效）
        "on_threshold": {10: {"form": "fury"}},  # 满 10 进狂暴（上层模块消费）
    },
    "lian_duan": {
        "cap": 10,
    },
    "rage": {
        "cap": 10,
        "stat_scale": {"dmg_mult": 0.12},     # 每层伤害 +12%（狂暴）
    },
    "chi": {
        "cap": 10,
    },
    "arcane": {
        "cap": 10,
    },
    "shield": {
        "cap": 10,
        "stat_scale": {"reduce": 0.03},       # 每层减伤
    },
    # ============ 对敌标记（挂 target，谁打都吃；on=target 表明作用对象） ============
    "hunt_mark": {
        "cap": 3,
        "on": "target",
        "debuff_scale": {"dmg_taken": 0.08},  # 每层承伤 +8%
    },
    "soul_mark": {
        "cap": 3,
        "on": "target",
        "debuff_scale": {"dmg_taken": 0.06},  # 每层承伤 +6%
    },
    # ============ 持续伤害 DOT（on=target） ============
    "burn": {
        "cap": 5,
        "on": "target",
        "dot": {"pct_max_hp": 0.03},          # 每层每刻掉 3% 生命
    },
    "bleed": {
        "cap": 10,
        "on": "target",
        "dot": {"type": "flat", "per_layer": 0},  # 固定伤害（数值由施法者攻击定，见 effects）
    },
    "poison": {
        "cap": 5,
        "on": "target",
        "dot": {"pct_max_hp": 0.02},
    },
    "corros": {
        "cap": 5,
        "on": "target",
        "dot": {"pct_max_hp": 0.02, "dmg_type": "true"},  # 真伤 DOT
    },
    # ============ 元素印记（on=target，元素反应 N4/上层消费） ============
    "fire_mark": {
        "cap": 5,
        "on": "target",
    },
    "ice_mark": {
        "cap": 5,
        "on": "target",
    },
    "thunder_mark": {
        "cap": 5,
        "on": "target",
    },
}

# 面板属性 → 是否允许 stat_scale 折算（白名单，防脏 key）
SCALEABLE_STATS = {"atk", "matk", "def", "mdef", "spd", "crit", "dodge",
                   "crit_dmg", "luck", "max_hp", "max_mp", "reduce", "dmg_mult"}


def state_def(key: str) -> dict:
    """查状态定义（无则空 dict = 无规则纯数值）。"""
    return STATE_EFFECTS.get(key) or {}


def stat_scale_of(key: str, value: int, stat: str) -> float:
    """折算：state key 每 value 点对 stat 的加成系数（1 + n×系数）。"""
    cfg = STATE_EFFECTS.get(key) or {}
    scale = (cfg.get("stat_scale") or {}).get(stat)
    if not scale:
        return 1.0
    return 1.0 + int(value or 0) * float(scale)
