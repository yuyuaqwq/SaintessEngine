# -*- coding: utf-8 -*-
"""《铆炉回声》——技能表（玩家技能 / 普攻 / 怪物技能）。

技能 dict 的字段是**引擎协议**：name / kind / exprs / cd / res_cost / mech /
mech_val / cc_turns / aoe / hits…（见 wiki reference/api.md 与 concept/formulas 用法）。
kind 的值是本游戏的词（"冲击"/"灼热"/…），引擎只拿它去 config.kind_of() 比对。

本模块整体作为引擎的 `skill_lookup` hook 使用 —— 只需要两个静态方法：
    skill_info(class_name, skill_key)  玩家侧查询
    skill_by_key(skill_key)            通用查询（怪物技能也走这里）
"""
from __future__ import annotations

# 普攻（职业 basic_skill；引擎 basic_skill_fn hook 的返回）
BASIC_SKILLS = {
    "cls_kiln": {"name": "铆锤敲击", "kind": "冲击", "exprs": ["atk*1.15"]},
    "cls_whistle": {"name": "哨音穿刺", "kind": "灼热", "exprs": ["matk*1.15"]},
}

# 玩家技能（按职业分组；key 是本游戏自定的 skill id）
PLAYER_SKILLS = {
    "cls_kiln": {
        "sk_rivet": {
            "name": "过载铆钉",
            "kind": "冲击",
            "exprs": ["atk*1.75"],
            "cd": 2,
            "res_cost": {"kiln": 2},      # 引擎原生消费 effects["kiln"].stacks
        },
    },
    "cls_whistle": {
        "sk_pulse": {
            "name": "共鸣脉冲",
            "kind": "灼热",
            "exprs": ["matk*1.7"],
            "cd": 2,
            "res_cost": {"echo": 2},
        },
    },
}

# 怪物技能（无职业归属；引擎 monster_skill_fn hook 的返回）
MONSTER_SKILLS = {
    # mech=rust → 命中后按 mech_val 层给目标叠「锈蚀」（EFFECT_RULES 声明 DOT）
    "ms_rustspit": {
        "name": "锈钉喷射",
        "kind": "冲击",
        "exprs": ["atk*1.1"],
        "mech": "rust",
        "mech_val": 2,
    },
    # mech=clamp → 名词路径（EFFECT_ACTIONS 翻成 apply mode=skip）；cc_turns 给控制刻数
    "ms_clamp": {
        "name": "铁钳拘束",
        "kind": "冲击",
        "exprs": ["atk*0.75"],
        "mech": "clamp",
        "mech_val": 1,
        "cc_turns": 1,
    },
}


def _find(table: dict, skill_key: str):
    if not skill_key:
        return None
    info = table.get(skill_key)
    if info is not None:
        return dict(info)
    for v in table.values():
        if v.get("name") == skill_key:
            return dict(v)
    return None


# ---- 引擎 skill_lookup hook 需要的接口 ----

def skill_info(class_name: str, skill_key: str):
    """玩家技能查询（class_name + key/显示名 双路解析；查不到 → None）。"""
    return _find(PLAYER_SKILLS.get(class_name or "") or {}, skill_key)


def skill_by_key(skill_key: str):
    """通用技能查询（先玩家表后怪物表 —— 引擎对无 class_name 的 actor 走这里）。"""
    for table in list(PLAYER_SKILLS.values()) + [MONSTER_SKILLS]:
        info = _find(table, skill_key)
        if info is not None:
            return info
    return None


# ---- 引擎 basic_skill_fn / monster_skill_fn hook 需要的接口 ----

def basic_skill(class_name: str):
    """职业普攻配置（引擎 resolve_basic_skill 用；返回 None → 回落 basic_fallback）。"""
    info = BASIC_SKILLS.get(class_name or "")
    return dict(info) if info else None


def monster_skill(skill_key: str):
    """怪物技能查询（引擎 _index_one_actor 用）。"""
    return _find(MONSTER_SKILLS, skill_key)
