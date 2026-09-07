# -*- coding: utf-8 -*-
"""v181.P4 battle2 引擎——面板计算（薄封装旧 engine.py 数值函数，不重写公式）。

按 docs/REFACTOR_v181P4_FULL_PLAN.md 7.3 stats.py：
- actor 有 class_name → E.player_final_stats（玩家职业公式：装备/等级/转职全算）
- 纯怪（无 class_name）→ 直接读 actor 字段 + 简单 buff 修正（对齐旧 _enemy_stats）
- 战斗内聚合面板 = 基础 + buffs 修正（buffs 键 → 属性加成）

⚠️ 旧 _player_stats 有极多战斗侧被动/符文/条件消费（v64 被动/词条/旋律等）。
   N1 只做无被动场景对齐；被动/条件消费随 N2/N3 逐步迁移（每个消费点单独对齐）。
"""
from __future__ import annotations

from typing import Optional

from .. import engine as E

# 战斗 buff 键 → 面板属性映射（N3 效果系统前先支持普攻相关最小集）
# 与旧 battle._apply_buffs 对齐（仅迁移普攻/N1 需要的键，后续补）
_BUFF_STAT_KEYS = {
    "atk_up": "atk",
    "def_up": "def",
    "matk_up": "matk",
    "mdef_up": "mdef",
    "spd_up": "spd",
    "spd_down": "spd",  # 乘 0.8（SPD_DOWN_MULT）
}

# 减速乘数（旧 battle.py SPD_DOWN_MULT）
SPD_DOWN_MULT = 0.8


def actor_stats(battle, actor: dict) -> dict:
    """任意 actor 的聚合面板（伤害/防御公式输入）。

    内部：
    - actor 有 class_name → E.player_final_stats + title_bonus + buffs 修正
    - 纯怪（无 class_name）→ 直接读 actor 字段 + buffs 修正（对齐旧 _enemy_stats）
    """
    if actor is None:
        return {}
    st = {}
    if actor.get("class_name"):
        st = _player_base_stats(battle, actor)
    else:
        st = _monster_base_stats(actor)
    # buffs 修正（战斗内 buffs dict → 面板属性）
    _apply_buffs(st, actor_buffs_of(actor))
    return st


def actor_buffs_of(actor: dict) -> dict:
    """惰性读取 actor.buffs（不写回播种——纯读）。"""
    b = actor.get("buffs") or {}
    return b if isinstance(b, dict) else {}


def _player_base_stats(battle, actor: dict) -> dict:
    """玩家/带 class_name 的 actor：走职业面板公式（不传 learned_skills——
    面板并入被动由 engine 做；战斗侧被动动态处理，传了会双算，与旧 _player_stats 同）。"""
    st = E.player_final_stats(
        actor.get("class_name", "战士"),
        actor.get("level", 1),
        actor.get("equipment") or {},
        actor.get("class_tier", 0),
        actor.get("attributes"),
        actor.get("evolve_path", 0),
        getattr(battle, "title_bonus", None) or {},
        actor.get("race"),
    )
    return st


def _monster_base_stats(actor: dict) -> dict:
    """纯怪（无 class_name）：直接读字段（对齐旧 _enemy_stats 基础段）。"""
    return {
        "max_hp": actor.get("max_hp", actor.get("hp", 1)),
        "atk": actor.get("atk", 0),
        "def": actor.get("def", 0),
        "matk": actor.get("matk", 0),
        "mdef": actor.get("mdef", 0),
        "spd": actor.get("spd", 0),
        "crit": actor.get("crit", 0.05),
        "tenacity": actor.get("tenacity", 0) or 0,
        "block": actor.get("block", 0) or 0,
        "dodge": actor.get("dodge", 0) or 0,
        "phys_reduce": actor.get("phys_reduce", 0) or 0,
        "magic_reduce": actor.get("magic_reduce", 0) or 0,
        "elem_res": actor.get("elem_res", 0) or 0,
    }


def _apply_buffs(st: dict, buffs: dict) -> dict:
    """把 buffs dict 的属性加成应用到面板（st 原地改，返回同一 dict）。

    N1 最小集（与旧 battle._apply_buffs 逐键对齐，后续 N3 补全）：
    - atk_up/def_up/matk_up/mdef_up/spd_up: ×(1 + 层数×0.10)（ATK_UP_MULT 语义按层）
    - spd_down: ×0.8
    值可为 int 层数或 dict {n, mult, ...}（debuff 池结构）。
    """
    if not buffs:
        return st
    for key, attr in _BUFF_STAT_KEYS.items():
        if key not in buffs:
            continue
        val = buffs[key]
        # 兼容 dict 结构（debuffs {n: 层数, mult: 系数}）
        if isinstance(val, dict):
            n = int(val.get("n", val.get("stacks", 1)) or 1)
            mult = float(val.get("mult", 0.10) or 0.10)
        else:
            n = int(val or 1)
            mult = 0.10
        if key == "spd_down":
            st[attr] = int(st.get(attr, 0) * SPD_DOWN_MULT)
        else:
            st[attr] = int(st.get(attr, 0) * (1 + n * mult))
    return st


# ============================================================
# 便捷访问
# ============================================================

def actor_max_hp(battle, actor: dict) -> int:
    return int(actor_stats(battle, actor).get("max_hp", actor.get("max_hp", 1)))


def actor_spd(battle, actor: dict) -> int:
    return int(actor_stats(battle, actor).get("spd", actor.get("spd", 0)))


def actor_crit(battle, actor: dict) -> float:
    return float(actor_stats(battle, actor).get("crit", 0.0))
