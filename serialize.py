# -*- coding: utf-8 -*-
"""v181.P4 battle2 引擎——序列化（serialize.py）。

按 docs/REFACTOR_v181P4_FULL_PLAN.md Part 4.2：
- to_state 输出 sides-only JSON 结构（battle_state.state 存）
- from_state 重建 Battle + sides + actors
- actor 全字段可 JSON 化（state/buffs/ext 等）；无循环引用（召唤物 owner 存 uid）

state = {
  "type": ...,
  "now": float,
  "p_acts": int,
  "result": str|None,
  "winner_side": str|None,
  "sides": {side名: [actor, ...]},
  "hostile_map": {...},
  "title_bonus": {...},
  "killed": [...],  # 击杀记录（uid 列表）
  "battle_flags": {...},  # 战斗级一次性标记（后续扩展）
}
"""
from __future__ import annotations

import json
from typing import Optional

from .actors import ActCtx, make_actor
from .battle import Battle


# actor 序列化字段白名单（引擎字段全集；ext/state/buffs 内嵌序列化）
# make_actor 播种的引擎字段 + 额外透传字段（数据标签）全部保留
_STRIP_KEYS = {"_skill_index"}  # 运行时索引不落盘（恢复时重建）


def to_state(battle: Battle) -> dict:
    """Battle → 可 JSON 化 dict（battle_state.state 存）。"""
    return {
        "type": battle.btype,
        "now": float(battle._now),
        "p_acts": int(battle._p_acts),
        "result": battle.result,
        "winner_side": battle.winner_side,
        "sides": {sn: [_serialize_actor(a) for a in acts]
                  for sn, acts in battle.sides.items()},
        "hostile_map": dict(battle.hostile_map or {}),
        "title_bonus": dict(battle.title_bonus or {}),
        "killed": [a.get("uid") for a in battle.killed_actors if a.get("uid")],
        "flags": {},
    }


def _serialize_actor(actor: dict) -> dict:
    """actor → JSON 化 dict（去运行时索引，纯数据）。"""
    out = {k: v for k, v in actor.items() if k not in _STRIP_KEYS}
    return out


def from_state(st: dict) -> Battle:
    """dict → Battle（重建 sides + actors + meta）。"""
    b = Battle(
        btype=st.get("type", "monster"),
        sides={sn: [_deserialize_actor(a) for a in acts]
               for sn, acts in (st.get("sides") or {}).items()},
        title_bonus=st.get("title_bonus") or {},
        hostile_map=st.get("hostile_map") or {},
    )
    b._now = float(st.get("now", 0) or 0)
    b._p_acts = int(st.get("p_acts", 0) or 0)
    b.result = st.get("result")
    b.winner_side = st.get("winner_side")
    # 续战（恢复的战斗已在开战事件后）→ 不重复 fire battle_start
    b._started = True
    # 击杀记录（uid → 找 actor；找不到跳过——已从 sides 移除的阵亡单位）
    b.killed_actors = []
    for uid in (st.get("killed") or []):
        for acts in b.sides.values():
            for a in acts:
                if a.get("uid") == uid:
                    b.killed_actors.append(a)
                    break
    return b


def _deserialize_actor(data: dict) -> dict:
    """JSON 化 actor dict → actor（重建 _skill_index 空壳，Battle 构造时再索引）。"""
    actor = dict(data)
    actor.setdefault("ext", {})
    actor.setdefault("state", {})
    actor.setdefault("buffs", {})
    actor.setdefault("debuffs", {})
    actor.setdefault("shields", {})
    actor["_skill_index"] = {}
    return actor


# ============================================================
# DB 便捷（命令层用：存/取 battle_state JSON）
# ============================================================

def state_to_json(state: dict) -> str:
    return json.dumps(state, ensure_ascii=False, default=str)


def json_to_state(raw: str) -> dict:
    return json.loads(raw)
