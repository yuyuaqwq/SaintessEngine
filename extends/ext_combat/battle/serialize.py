# -*- coding: utf-8 -*-
"""v181.P4 saintess_engine 引擎——序列化（serialize.py）。

按 docs/archive/REFACTOR_v181P4_FULL_PLAN.md Part 4.2：
- to_state 输出 sides-only JSON 结构（battle_state.state 存）
- from_state 重建 Battle + sides + actors（文案表由恢复方重新注入：`text=`；不落盘）
- actor 全字段可 JSON 化（state/buffs/ext 等）；无循环引用（召唤物 owner 存 uid）

state = {
  "type": ...,
  "now": float,
  "p_acts": int,
  "result": str|None,
  "winner_side": str|None,
  "sides": {side名: [actor, ...]},
  "hostile_map": {...},
  "killed": [...],  # 击杀记录（uid 列表）
  "flags": {...},  # **战斗级跨手标记**（内容侧「每场一次 / 每场几层」那类记账挂这里；
                   #  挂在 Battle 上的临时属性过不了往返 —— 每手重建 ⇒ 每手清零）
}
"""
from __future__ import annotations

import json

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
        "killed": [a.get("uid") for a in battle.killed_actors if a.get("uid")],
        # 战斗级跨手标记（2026-09-27 接上 · 原先写死 `{}` ⇒ 内容侧挂在 Battle 上的记账每手清零）
        "flags": dict(battle.flags or {}),
    }


def _serialize_actor(actor: dict) -> dict:
    """actor → JSON 化 dict（去运行时索引，纯数据）。"""
    out = {k: v for k, v in actor.items() if k not in _STRIP_KEYS}
    return out


def from_state(st: dict, *, text=None) -> Battle:
    """dict → Battle（重建 sides + actors + meta）。

    text: （v186 文案注入）可选文案表（鸭子类型同 `Battle.__init__`）。表实例不可 JSON 化
      ⇒ 不随 `to_state` 落盘，恢复方**每次重新注入**（与 target_picker 一类运行回调同款）；
      不传 = 未注入 ⇒ 战斗日志走调用点兜底模板（逐字节 = 历史内联串）。
    """
    b = Battle(
        btype=st.get("type", "monster"),
        sides={sn: [_deserialize_actor(a) for a in acts]
               for sn, acts in (st.get("sides") or {}).items()},
        hostile_map=st.get("hostile_map") or {},
        # 文案表：不落盘 ⇒ 由恢复方重新注入（未注入 = 兜底模板）
        text=text,
        # N10-B6b：恢复路径不重播初始 ct（actor ct 已随存档反序列化）
        seed_ct=False,
    )
    b._now = float(st.get("now", 0) or 0)
    b._p_acts = int(st.get("p_acts", 0) or 0)
    b.result = st.get("result")
    b.winner_side = st.get("winner_side")
    # 战斗级跨手标记（2026-09-27 接上）：内容侧「每场一次 / 每场几层」那类记账随每一手回来
    b.flags = dict(st.get("flags") or {})
    # 续战（恢复的战斗已在开战事件后）→ 不重复 fire battle_start
    b._started = True
    # 击杀记录（uid → 找 actor；找不到跳过——已从 sides 移除的阵亡单位）
    #
    # ★ 2026-09-29 审计 afix1 第 28 轮：内层 `break` **只跳出最内层循环**，
    #   外层的 `for acts in b.sides.values()` 会带着同一个 uid 继续找下一个 side ⇒
    #   **同一个 uid 出现在两个 side 时被 append 两次**。`killed` 落盘的是 uid 列表，
    #   天然只记一次，所以一条真实击杀在恢复后变成两条。
    #   黑盒复现（`tests/test_killed_restore_once.py`）：落盘 `killed=['m1']` ⇒
    #   还原后 `killed_actors` **2 条**。落点 `games/orlandia/content/combat_cmds.py:1594/1890`
    #   把这份名单当 `extra_kills` 交给 `victory_settle`（经验/金币/掉落）⇒ 重复计数；
    #   复活被动（`class_mech.py:1826/1866`）又按**对象身份** `owner in ka` 判定
    #   ⇒ 名单里混进的另一个 side 的同 uid 对象会让「移除死亡记录」漏掉真死者。
    #   修法 = **取首个匹配即停**（`break` 提到外层，语义 = 一个 uid 对应一个 actor）。
    b.killed_actors = []
    for uid in (st.get("killed") or []):
        for acts in b.sides.values():
            for a in acts:
                if a.get("uid") == uid:
                    b.killed_actors.append(a)
                    break
            else:
                continue
            break
    return b


def _deserialize_actor(data: dict) -> dict:
    """JSON 化 actor dict → actor（重建 _skill_index 空壳，Battle 构造时再索引）。

    v181.M-bonus：旧档 actor（无 bonus 容器、带 stat_bonus/cap_bonus 旧键）一次性
    迁移进 bonus 分域并清旧键（存档数据迁移，非引擎读源回落——引擎读源一律
    bonus 分域 get 兜底；新档 actor 已带 bonus 容器则原样）。
    """
    actor = dict(data)
    actor.setdefault("effects", {})
    actor.setdefault("cooldown", {})
    actor.setdefault("ext", {})
    _bns = actor.get("bonus")
    if not isinstance(_bns, dict) or "panel" not in _bns:
        actor["bonus"] = {
            "panel": dict(actor.get("stat_bonus") or actor.get("title_bonus") or {}),
            "cap": dict(actor.get("cap_bonus") or {}),
            "cost": {},
        }
        actor.pop("stat_bonus", None)
        actor.pop("cap_bonus", None)
        actor.pop("title_bonus", None)
    actor["_skill_index"] = {}
    return actor


# ============================================================
# DB 便捷（命令层用：存/取 battle_state JSON）
# ============================================================

def state_to_json(state: dict) -> str:
    return json.dumps(state, ensure_ascii=False, default=str)


def json_to_state(raw: str) -> dict:
    return json.loads(raw)
