# -*- coding: utf-8 -*-
"""v181.P4 battle2 引擎——actor 模型层（纯数据，无逻辑）。

按 docs/REFACTOR_v181P4_FULL_PLAN.md Part 1/2 实现：
- actor = 全同构 dict（无身份逻辑；class_name 只选面板公式，side 只分组）
- sides = {side名: [actor, ...]}（唯一容器）
- ActCtx = 每次行动上下文（显式 caster/target/scope，消灭隐式全局目标）
- 引擎逻辑只用字段值，不按字段猜身份
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# ============================================================
# ActCtx：行动上下文（每次行动新建）
# ============================================================

@dataclass
class ActCtx:
    """一次行动的全部上下文。命令层/AI 先决定 ctx（选目标），再交给 Battle.act()。"""
    caster: dict                          # 施法者 actor（谁在行动）
    action: str = "attack"                # attack|skill|defend|flee|use_item|auto
    skill_name: Optional[str] = None      # 技能名（action=skill 时）
    info: Optional[dict] = None           # 技能/动作配置（技能 dict）
    target: Optional[dict] = None         # 单目标 actor（伤害/debuff 对象）
    target_side: Optional[str] = None     # 范围目标（AOE 打哪个 side；"all"=敌对全阵营）
    scope: str = "single"                 # single|all|front|side:<name>|self

    def __post_init__(self):
        # 信息冗余防御：action=skill 但 info 为空时尝试从 caster.skills 索引
        # （数据桥在 Battle 构造时把技能 dict 挂到 actor["_skill_index"]）
        if self.action == "skill" and self.info is None and self.skill_name:
            _idx = (self.caster or {}).get("_skill_index") or {}
            self.info = _idx.get(self.skill_name) or {}
        # scope 缺省推导：有 target_side / scope=all 语义保留；纯单目标默认 single
        if self.scope == "single" and self.target_side:
            self.scope = self.target_side if self.target_side != "all" else "all"


# ============================================================
# actor 构造
# ============================================================

# 播种的战斗可变状态键（全部 actor 同构）
_MUTABLE_KEYS = {
    "buffs": dict,
    "debuffs": dict,
    "stacks": dict,
    "resources": dict,
    "shields": dict,
    "cooldown": dict,
    "hot": dict,
    "defending": bool,
    "charging": None,
}


def make_actor(
    uid: str,
    name: str,
    side: str,
    kind: str = "monster",
    human_controlled: bool = False,
    class_name: Optional[str] = None,
    level: int = 1,
    equipment: Optional[dict] = None,
    skills: Optional[list] = None,
    learned_skills: Optional[list] = None,
    auto_act: Optional[dict] = None,
    **stats,
) -> dict:
    """构造一个全同构 actor dict。

    - 播种全部战斗可变状态键（buffs/debuffs/stacks/resources/shields/cooldown/hot/...）
    - 玩家面板字段（hp/mp/atk/def/spd/crit/...）由调用方按需传入（make_player 之类工厂）；
      引擎不在构造时做玩家面板聚合（那是 stats.py actor_stats 的活）。
    - 普通怪（无 class_name）：stats 里直接给 atk/def/matk/mdef/spd/crit/... 字段。
    - 玩家（有 class_name）：stats 给基础字段；聚合面板用 actor_stats()（stats.py）。
    """
    actor: dict = {
        # ① 身份/数据标签
        "uid": uid,
        "name": name,
        "side": side,
        "kind": kind,
        "human_controlled": bool(human_controlled),
        # ② 面板基础字段（实时 hp/mp 直接读写；聚合见 stats.actor_stats）
        "hp": int(stats.get("hp", stats.get("max_hp", 1))),
        "max_hp": int(stats.get("max_hp", 1)),
        "mp": int(stats.get("mp", 0)),
        "max_mp": int(stats.get("max_mp", 0)),
        "atk": int(stats.get("atk", 0)),
        "matk": int(stats.get("matk", 0)),
        "def": int(stats.get("def", 0)),
        "mdef": int(stats.get("mdef", 0)),
        "spd": int(stats.get("spd", 0)),
        "crit": float(stats.get("crit", 0.0)),
        "dodge": float(stats.get("dodge", 0.0)),
        "crit_dmg": float(stats.get("crit_dmg", 0.0)),
        "luck": float(stats.get("luck", 0.0)),
        "tenacity": float(stats.get("tenacity", 0.0)),
        "block": float(stats.get("block", 0.0)),
        "pene": float(stats.get("pene", 0.0)),
        "race": stats.get("race"),
        # ③ 战斗可变状态（播种）
        "buffs": dict(stats.get("buffs") or {}),
        "debuffs": dict(stats.get("debuffs") or {}),
        "stacks": dict(stats.get("stacks") or {}),
        "resources": dict(stats.get("resources") or {}),
        "shields": dict(stats.get("shields") or {}),
        "cooldown": dict(stats.get("cooldown") or {}),
        "hot": dict(stats.get("hot") or {}),
        "charging": stats.get("charging"),
        "defending": bool(stats.get("defending", False)),
        "ct": float(stats.get("ct", 0.0)),
        "poi_buff": stats.get("poi_buff"),
        # ④ 配置/能力
        "class_name": class_name,
        "level": int(stats.get("level", level)),
        "equipment": dict(equipment or stats.get("equipment") or {}),
        "skills": list(skills or stats.get("skills") or []),
        "learned_skills": list(learned_skills or stats.get("learned_skills") or []),
        "auto_act": auto_act or stats.get("auto_act"),
        # 技能索引（Battle 构造时灌入：技能名 → 技能 dict）
        "_skill_index": {},
        # 外部扩展区（引擎绝不读；职业/机制自定义状态放这里，命名空间自管）
        "ext": {},
    }
    # 携带的额外字段（rank/reach/role/is_boss/exp/gold/drops 等数据标签或旧怪字段）
    for k, v in stats.items():
        if k not in actor:
            actor[k] = v
    # 面板配置透传（旧玩家 dict 字段：evolve_path/class_tier/attributes 供 stats 重算用）
    for k in ("evolve_path", "class_tier", "attributes"):
        if k in stats and k not in actor:
            actor[k] = stats[k]
    return actor


# ============================================================
# 纯 helper（读 actor 状态）
# ============================================================

def actor_alive(actor: dict) -> bool:
    """actor 存活判定：hp > 0。"""
    return bool(actor) and int(actor.get("hp", 0) or 0) > 0


def actor_dead(actor: dict) -> bool:
    return not actor_alive(actor)


def actor_buffs(actor: dict) -> dict:
    """任意 actor 的 buffs（惰性播种）。"""
    if actor is None:
        return {}
    b = actor.get("buffs")
    if b is None:
        b = actor["buffs"] = {}
    return b


def actor_debuffs(actor: dict) -> dict:
    """任意 actor 的 debuffs（持续减益池）。"""
    if actor is None:
        return {}
    d = actor.get("debuffs")
    if d is None:
        d = actor["debuffs"] = {}
    return d


def actor_stacks(actor: dict) -> dict:
    """任意 actor 的职业叠层。"""
    if actor is None:
        return {}
    s = actor.get("stacks")
    if s is None:
        s = actor["stacks"] = {}
    return s


def actor_resources(actor: dict) -> dict:
    """任意 actor 的核心资源。"""
    if actor is None:
        return {}
    r = actor.get("resources")
    if r is None:
        r = actor["resources"] = {}
    return r


def actor_ext(actor: dict) -> dict:
    """actor 外部扩展区（惰性播种）。职业/机制自定义状态写这里，引擎不读。"""
    if actor is None:
        return {}
    e = actor.get("ext")
    if not isinstance(e, dict):
        e = actor["ext"] = {}
    return e


def actor_side_of(battle, actor: dict) -> Optional[str]:
    """查 actor 属于哪个阵营（以 battle.sides 权威；actor.side 兜底）。"""
    if actor is None:
        return None
    sid = actor.get("side")
    if sid and sid in getattr(battle, "sides", {}):
        return sid
    # 找不到（actor 不在 sides 或没带 side）→ 按引用扫描一次
    for _sn, _acts in (getattr(battle, "sides", {}) or {}).items():
        for _a in _acts:
            if _a is actor or _a.get("uid") == actor.get("uid"):
                return _sn
    return sid  # 兜底 actor.side（无 sides 上下文时）


def hostile_sides(battle, side: str) -> list:
    """side 的敌对阵营名列表。

    简化规则（按 side 名推导，数据可在 Battle 构造时覆盖 hostile_map）：
    - 引擎不预设玩家/怪身份 → 敌对关系由 Battle.hostile_map 显式定义
    - 默认：除自己外的全部阵营
    """
    hm = getattr(battle, "hostile_map", None)
    if hm and side in hm:
        return list(hm[side])
    return [s for s in (battle.sides or {}).keys() if s != side]


def hostile_actors(battle, side: str) -> list:
    """side 的敌对阵营存活 actor 列表（AI 选目标用）。"""
    out = []
    for _sn in hostile_sides(battle, side):
        for _a in (battle.sides or {}).get(_sn, []):
            if actor_alive(_a):
                out.append(_a)
    return out
