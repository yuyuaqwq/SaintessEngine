# -*- coding: utf-8 -*-
"""《铆炉回声》——怪物模板。

怪物 = 无 class_name 的 actor：面板直接读 actor 字段（引擎 stats._monster_base_stats），
所以这里给的就是裸数值。AI 用引擎 ai.py 的谓词表（round_mod / 空 when 恒真）。
"""
from __future__ import annotations

MONSTERS = {
    "rustmite": {
        "name": "锈苔爬虫",
        "level": 4,
        "hp": 74, "atk": 15, "def": 4, "mdef": 3, "spd": 46, "crit": 0.05,
        "skills": ["ms_rustspit"],
        "ai": {
            "select": "priority",
            "fallback": {"type": "attack"},
            "moves": [{"when": {}, "then": {"type": "skill", "skill": "ms_rustspit"}}],
        },
    },
    "ironbuoy": {
        "name": "铆壳浮标",
        "level": 5,
        "hp": 112, "atk": 13, "def": 7, "mdef": 4, "spd": 34, "crit": 0.05,
        "skills": ["ms_clamp"],
        "ai": {
            "select": "priority",
            "fallback": {"type": "attack"},
            "moves": [
                {"when": {"round_mod": [3, 0]}, "then": {"type": "skill", "skill": "ms_clamp"}},
                {"when": {}, "then": {"type": "attack"}},
            ],
        },
    },
}

# 透传给 make_actor 的面板字段（引擎 _monster_base_stats 读这些）
_STAT_FIELDS = ("hp", "max_hp", "atk", "matk", "def", "mdef", "spd", "crit", "dodge")


def build_monster(key, uid, side="enemy"):
    """造一个怪物 actor（不挂内容装配 —— 由调用方显式 apply_game_content）。"""
    from saintess_engine import make_actor

    m = MONSTERS.get(key)
    if not m:
        raise KeyError(f"未知怪物：{key!r}")
    stats = {k: m[k] for k in _STAT_FIELDS if k in m}
    return make_actor(
        uid, m["name"], side, kind="monster", level=m.get("level", 1),
        skills=list(m.get("skills") or []), ai=m.get("ai"),
        **stats,
    )
