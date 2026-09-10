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

from . import config as _cfg


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
    # 效果折算（V 系列统一：遍历 effects 容器，读 EFFECT_RULES 表）
    #   - 面板快照型（buff：条目含 stat/op/mult/value 折算，origin act_buff）
    #   - 叠层声明型（state：EFFECT_RULES[key].panel/stat_scale × stacks）
    _apply_effects(st, actor)
    return st


def _apply_effects(st: dict, actor: dict) -> dict:
    """把 actor.effects 全部条目折算进面板（st 原地改，返回同一 dict）。

    每条目按 EFFECT_RULES[key] 声明折算：
    - panel（静态整体增益）：按 panel.stat/op/mult 快照数值折算
    - stat_scale（每层增益）：stacks × 每层系数（资源/叠层 buff）
    - 无面板声明（纯状态/控制/周期/免疫）不折算面板
    兼容过渡：原 buffs 快照字段（stat/op/mult 直接内嵌条目）也读
    （EFFECT_ACTIONS 迁移前旧动作产物）——见数据表迁移 V5。
    """
    ef = actor.get("effects") or {}
    if not isinstance(ef, dict) or not ef:
        return st
    from .state_effects import state_def
    for key, entry in ef.items():
        if not isinstance(entry, dict):
            continue
        cfg = state_def(key) or {}
        n = int(entry.get("stacks", 0) or 0)
        # ① 叠层声明型（stat_scale：每层面板修正）——需 stacks>0
        if n > 0:
            scale = cfg.get("stat_scale") or {}
            for stat, per in scale.items():
                if stat == "dmg_mult":
                    st["_state_dmg_mult"] = float(st.get("_state_dmg_mult", 1.0)) * (1.0 + n * float(per))
                elif stat == "reduce":
                    st["reduce"] = min(float(st.get("reduce", 0) or 0) + n * float(per), 0.9)
                elif stat in st:
                    st[stat] = int(st.get(stat, 0) * (1.0 + n * float(per)))
        # ② 面板快照型（buff：条目内嵌 stat/op/mult 或声明 panel）——默认 1 层
        entry_stat = entry.get("stat") or (cfg.get("panel") or {}).get("stat")
        entry_mult = entry.get("mult")
        if entry_mult is None:
            entry_mult = (cfg.get("panel") or {}).get("mult")
        if entry_stat and entry_mult is not None:
            _op = entry.get("op") or (cfg.get("panel") or {}).get("op") or "mul"
            if key == "spd_down" or _op == "reduce":
                st[entry_stat] = int(st.get(entry_stat, 0) * (1.0 - min(float(entry_mult), 0.9)))
            elif _op == "add":
                st[entry_stat] = float(st.get(entry_stat, 0) or 0) + float(entry_mult)
            else:
                st[entry_stat] = int(st.get(entry_stat, 0) * float(entry_mult))
    return st


def _player_base_stats(battle, actor: dict) -> dict:
    """玩家/带 class_name 的 actor：走职业面板公式（内容侧 config.panel_fn 注入；
    不传 learned_skills——面板并入被动由内容侧做；战斗侧被动动态处理，传了会双算，
    与旧 _player_stats 同）。

    title_bonus/bonus 容器（v181.M-bonus 统一数值容器；N5b4-4 鱼鱼拍板 per-actor 通用
    容器）：actor 自带 bonus.panel（外部面板数值增幅聚合，core/stat_bonus.py）优先——
    PVP 双方各带各的、随 actor 落盘；
    缺省回落 battle.title_bonus（野外单玩家整场一份，N10 前过渡）。空 dict 回落兜底。
    未装配（无内容）→ strict 抛 EngineNotConfigured，否则空面板（见 R8）。
    """
    _tb = ((actor.get("bonus") or {}).get("panel")
           or getattr(battle, "title_bonus", None) or {})
    fn = _cfg.get_hook("panel_fn")
    if fn is None:
        return _cfg.unconfigured("panel_fn", {})
    return fn(
        actor.get("class_name", ""),
        actor.get("level", 1),
        actor.get("equipment") or {},
        actor.get("class_tier", 0),
        actor.get("attributes"),
        actor.get("evolve_path", 0),
        _tb,
        actor.get("race"),
    )


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


# ============================================================
# 便捷访问
# ============================================================

def actor_max_hp(battle, actor: dict) -> int:
    return int(actor_stats(battle, actor).get("max_hp", actor.get("max_hp", 1)))


def actor_spd(battle, actor: dict) -> int:
    return int(actor_stats(battle, actor).get("spd", actor.get("spd", 0)))


def actor_crit(battle, actor: dict) -> float:
    return float(actor_stats(battle, actor).get("crit", 0.0))
