# -*- coding: utf-8 -*-
"""v181.P4 battle2 引擎——CTB 时间轴调度（schedule.py）。

按 docs/REFACTOR_v181P4_FULL_PLAN.md Part 7 schedule.py + 旧引擎 v154 语义：

- 行动耗时 = 基准耗时 × sqrt(SPD_REF / spd)（CAST_* 基准 @spd=50）
- actor.ct = 下次能行动的时刻（绝对时刻）；谁 ct 小谁先动
- 命令层驱动：玩家出手 → advance() 推进到下一个决策点（途中自动 actor 自动行动）
- 1 刻 = 1 时刻 = 1 游戏秒（ACT_TICK=1）

引擎只有"时刻/速度/行动耗时"，不认识阵营/职业。
"""
from __future__ import annotations

import math
from typing import Optional

from .actors import ActCtx, actor_alive

# 行动基准耗时（与 core.constants 对齐，引擎固有刻度常量）
CAST_ATK = 1.0
CAST_SKILL = 1.6
CAST_DEFEND = 0.6
CAST_ITEM = 1.0
SPD_REF = 50.0


def action_time(spd: int, base: float = CAST_ATK) -> float:
    """一次行动耗时 = 基准耗时 × sqrt(SPD_REF/spd)（速度 50 = 基准值）。"""
    try:
        eff = max(float(spd or 0), 1.0)
    except Exception:
        eff = 1.0
    return float(base) * math.sqrt(SPD_REF / eff)


def initial_ct(spd: int, base: float = CAST_ATK) -> float:
    """单位初始行动等待（战斗开始第一动也按速度排）。"""
    return action_time(spd, base)


def next_ct(battle, actor: dict, base: float = CAST_ATK) -> float:
    """actor 行动后推进的 ct（绝对时刻）。"""
    spd = int((actor.get("stats_spd") or 0) or actor.get("spd", 0) or 0)
    # 用聚合面板速度（buffs 修正）
    try:
        from . import stats as S
        spd = S.actor_spd(battle, actor)
    except Exception:
        pass
    return float(battle._now) + action_time(spd, base)


def action_base_of(action: str) -> float:
    """行动类型 → 基准耗时。"""
    if action == "defend":
        return CAST_DEFEND
    if action == "skill":
        return CAST_SKILL
    return CAST_ATK


# ============================================================
# 推进（命令层驱动）
# ============================================================

def advance(battle, logs: list, max_steps: int = 200) -> tuple:
    """推进战斗：自动 actor 行动 + DOT/时效结算，直到遇到人控决策点或结束。

    返回 ("player", 决策 actor) | ("over", None)。
    语义（对齐旧引擎标准 CTB）：
    - 下一玩家行动点 vs 下一自动 actor 行动点：谁先到处理谁
    - 玩家到点 → 返回玩家决策（推进暂停，等真人输入）
    - 自动 actor 到点 → 行动 → 继续
    - 无存活人控（auto_run）→ 所有自动 actor 行动直到结束
    """
    guard = 0
    while battle.result is None and guard < max_steps:
        guard += 1
        # 玩家决策点（所有 human_controlled 存活 actor 中 ct 最小者）
        fp = _next_player_due(battle)
        # 自动 actor 行动点（ct 最小）
        auto = _next_auto_due(battle)
        if fp is None and auto is None:
            return ("over", None)
        if fp is not None and (auto is None or fp[1] <= auto[1] + 1e-9):
            # 玩家先到点 → 推进到玩家时刻，返回玩家决策
            t = fp[1]
            if t > battle._now:
                _advance_time(battle, t - battle._now, logs)
            if battle.result:
                return ("over", None)
            return ("player", fp[0])
        # 自动 actor 先到点 → 推进并行动
        actor, t = auto
        if t > battle._now:
            _advance_time(battle, t - battle._now, logs)
        if battle.result:
            return ("over", None)
        if actor_alive(actor) and not actor.get("human_controlled"):
            logs.append(f"—— {actor.get('name', '敌人')} 行动 ——")
            sub_logs, ended = battle.actor_auto(actor)
            logs.extend(sub_logs)
            if ended or battle.result:
                return ("over", None)
    return ("over", None)


def _next_player_due(battle):
    """ct 最小的存活人控 actor。返回 (actor, ct)。无则 None。"""
    best = None
    best_t = None
    for acts in battle.sides.values():
        for a in acts:
            if not actor_alive(a) or not a.get("human_controlled"):
                continue
            t = float(a.get("ct", 0) or 0)
            if best_t is None or t < best_t:
                best_t = t
                best = a
    return (best, best_t) if best else None


def _next_auto_due(battle):
    """ct 最小的存活自动 actor。返回 (actor, ct)。无则 None。"""
    best = None
    best_t = None
    for acts in battle.sides.values():
        for a in acts:
            if not actor_alive(a) or a.get("human_controlled"):
                continue
            t = float(a.get("ct", 0) or 0)
            if best_t is None or t < best_t:
                best_t = t
                best = a
    return (best, best_t) if best else None


def _after_act(battle, actor: dict, action: str):
    """行动后推进 actor.ct（行动耗时 + 固定推进）。"""
    base = action_base_of(action)
    actor["ct"] = float(battle._now) + action_time(int(actor.get("spd", 0)), base)


def _advance_time(battle, dt: float, logs: list):
    """推进全局时刻 dt（期间结算到期事件：DOT/时效）。"""
    if dt <= 0:
        return
    battle._now += dt
    # N4：DOT/时效结算（state_effects dot 规则 + buff 到期）接入点
    _settle_time_effects(battle, logs)


def _settle_time_effects(battle, logs: list):
    """时刻推进后的持续效果结算（DOT/时效）。

    N4 最小集：查 state_effects 的 dot 规则，对带 dot 的 state key 结算。
    每 actor 每结算 tick 掉一次（简化：每次推进都跳——N4 后期按 interval）。
    """
    from .state_effects import all_state_effects
    table = all_state_effects()
    for acts in battle.sides.values():
        for a in acts:
            if not actor_alive(a):
                continue
            st = a.get("state") or {}
            if not st:
                continue
            for key, val in list(st.items()):
                cfg = table.get(key) or {}
                dot = cfg.get("dot")
                n = int(val or 0)
                if not dot or n <= 0 or cfg.get("on") != "target":
                    continue
                # 每层每刻扣（简化 tick：每推进一次结算一跳；interval 字段预留）
                pct = float(dot.get("pct_max_hp", 0) or 0)
                if pct > 0:
                    dmg = max(1, int(a.get("max_hp", 1) * pct * n))
                else:
                    dmg = max(1, n)
                from .landing import deal_damage
                deal_damage(battle, None, a, dmg, logs)
                logs.append(f"🔥 {a.get('name', '目标')} 受 {key} {n} 层影响，损失 {dmg} 生命")
