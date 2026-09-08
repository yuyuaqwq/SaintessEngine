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
    # 用聚合面板速度（buffs 修正）——actor 裸 spd 字段可能是 0（玩家面板由
    # stats.actor_stats 从 class/equip 聚合），与 next_ct 保持一致口径。
    try:
        from . import stats as S
        spd = S.actor_spd(battle, actor)
    except Exception:
        spd = int(actor.get("spd", 0) or 0)
    actor["ct"] = float(battle._now) + action_time(spd, base)


def _advance_time(battle, dt: float, logs: list):
    """推进全局时刻 dt（期间结算到期事件：DOT/时效）。"""
    if dt <= 0:
        return
    battle._now += dt
    # N4：DOT/时效结算（state_effects dot 规则 + buff 到期）接入点
    _settle_time_effects(battle, logs)


def _settle_time_effects(battle, logs: list):
    """时刻推进后的持续效果结算（DOT/时效）。

    N7.2 收口（对齐旧 _decay_buff_table/_advance_time 的到期语义）：
    - buffs 到期：时间型条目 expire <= now → 删（控制 on_act/一次性 on_hit 由
      消费点清除，这里只做时间兜底：expire 到点自然消失）
    - shields 到期：expire_at <= now → 删（None = 永久不删）
    - DOT：查 state_effects 的 dot 规则，对带 dot 的 state key 结算（每推进一跳；
      interval 字段 N7.4 补）
    """
    from .state_effects import all_state_effects
    now = float(getattr(battle, "_now", 0.0) or 0.0)
    for acts in battle.sides.values():
        for a in acts:
            if not actor_alive(a):
                continue
            # buffs 时间到期（快照条目形态）
            bf = a.get("buffs")
            if isinstance(bf, dict) and bf:
                for key in list(bf.keys()):
                    entry = bf[key]
                    if not isinstance(entry, dict):
                        continue
                    exp = entry.get("expire")
                    if exp is None:
                        continue  # 永久/无到期
                    if now >= float(exp):
                        bf.pop(key, None)
                        # N8 事件：buff 到期钩子
                        try:
                            from .effect_triggers import fire as _fire
                            _fire(battle, "buff_expire", {"actor": a, "target": a,
                                                          "key": key}, logs)
                        except Exception:
                            pass  # 事件源异常不阻断结算
            # shields 到期
            sh = a.get("shields")
            if isinstance(sh, dict) and sh:
                for key in list(sh.keys()):
                    s = sh[key]
                    if not isinstance(s, dict):
                        continue
                    exp = s.get("expire_at")
                    if exp is None:
                        continue  # 永久盾
                    if now >= float(exp):
                        sh.pop(key, None)
            # DOT（state 声明 dot 规则，N7.4：按 interval 绝对时刻跳，跨多刻跳多次）
            st = a.get("state") or {}
            if not st:
                continue
            table = all_state_effects()
            dnext = a.setdefault("dot_next", {})
            for key, val in list(st.items()):
                cfg = table.get(key) or {}
                dot = cfg.get("dot")
                n = int(val or 0)
                if not dot or n <= 0 or cfg.get("on") != "target":
                    continue
                interval = float(dot.get("interval", 1.0) or 1.0)
                # 首次挂 DOT：下一跳 = now + interval（对齐旧事件卡首跳延迟）
                nx = dnext.get(key)
                if nx is None:
                    dnext[key] = now + interval
                    continue
                if now < float(nx):
                    continue  # 未到下一跳
                # 到点跳一次（可能跨多刻 → 循环补跳）
                guard = 0
                while now >= float(dnext[key]) and guard < 20:
                    guard += 1
                    pct = float(dot.get("pct_max_hp", 0) or 0)
                    if pct > 0:
                        dmg = max(1, int(a.get("max_hp", 1) * pct * n))
                    else:
                        dmg = max(1, n)
                    from .landing import deal_damage
                    deal_damage(battle, None, a, dmg, logs)
                    logs.append(f"🔥 {a.get('name', '目标')} 受 {key} {n} 层影响，损失 {dmg} 生命")
                    # N8 事件：DOT 每跳
                    try:
                        from .effect_triggers import fire as _fire
                        _fire(battle, "dot_tick", {"actor": a, "target": a,
                                                   "key": key, "dmg": dmg}, logs)
                    except Exception:
                        pass  # 事件源异常不阻断结算
                    dnext[key] = float(dnext[key]) + interval
                if not actor_alive(a):
                    break
