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
from .effects import _cap_of as _stack_cap_of

# 行动基准耗时（与 core.constants 对齐，引擎固有刻度常量）
CAST_ATK = 1.0
CAST_SKILL = 1.6
CAST_DEFEND = 0.6
CAST_ITEM = 1.0
SPD_REF = 50.0
# hot 周期恢复间隔（对齐旧引擎 ACT_TICK=1 游戏秒一拍；正向持续恢复的墙钟节奏，
# 与 actor 出手快慢无关——v179 P3 拍板语义：N 刻 = N 秒）
HOT_INTERVAL = 1.0


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
    """推进全局时刻 dt（期间结算到期事件：DOT/时效 + 时钟事件广播）。

    N4：DOT/时效结算（state_effects dot 规则 + buff 到期）接入点。
    v181 破绽时间化：尾部广播 time_advance（通用「时钟推进」事件）——挂敌身条等
    按刻连续结算的内容层声明订阅此事件，读点永远拿到当刻值（不再「谁读谁记得结算」）。
    """
    if dt <= 0:
        return
    battle._now += dt
    # N4：DOT/时效结算（state_effects dot 规则 + buff 到期）接入点
    _settle_time_effects(battle, logs)
    try:
        from .effect_triggers import fire as _fire
        _fire(battle, "time_advance", {"dt": float(dt), "now": float(battle._now)}, logs)
    except Exception:
        pass  # 时钟事件异常不阻断推进（容错铁律）


def _settle_time_effects(battle, logs: list):
    """时刻推进后的持续效果结算（V 系列统一：遍历 effects 容器）。

    N7.2 收口（对齐旧 _decay_buff_table/_advance_time 的到期语义）+ V 系列合并：
    - effects 到期：条目 expire <= now → 删（None=常驻/纯叠层；控制 on_act/
      一次性 on_hit 由消费点清除，这里只做时间兜底）
    - shields 到期：expire_at <= now → 删（None = 永久不删；独立容器）
    - 周期跳（统一方向分流，DOT/HOT 同构）：
      * 表声明 dot（EFFECT_RULES[key].dot，旧 damage 规则，静态每层数值）
      * 条目自带 period（effects[key]["period"]，动态声明——食物 HOT 的
        dir=heal/mana + value 数值随条目走，EFFECT_RULES 零名词）
      按 interval 绝对时刻循环补跳；turns 限跳清层（旧 dot.turns 语义）
    """
    from .state_effects import all_state_effects
    now = float(getattr(battle, "_now", 0.0) or 0.0)
    table = all_state_effects()
    for acts in battle.sides.values():
        for a in acts:
            if not actor_alive(a):
                continue
            ef = a.get("effects")
            # ---------- 1) effects 到期（buff/控制/免疫/一次性）----------
            if isinstance(ef, dict) and ef:
                for key in list(ef.keys()):
                    entry = ef[key]
                    if not isinstance(entry, dict):
                        continue
                    exp = entry.get("expire")
                    if exp is None:
                        continue  # 永久/无到期（纯叠层/资源）
                    if now >= float(exp):
                        ef.pop(key, None)
                        # N8 事件：效果到期钩子（原 buff_expire，保留事件名兼容）
                        try:
                            from .effect_triggers import fire as _fire
                            _fire(battle, "buff_expire", {"actor": a, "target": a,
                                                          "key": key}, logs)
                        except Exception:
                            pass  # 事件源异常不阻断结算
            # ---------- 2) shields 到期（独立容器）----------
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
            # ---------- 3) 周期跳（effects 条目：dot/period 声明）----------
            if isinstance(ef, dict) and ef:
                dnext = a.setdefault("dot_next", {})
                djump = a.setdefault("dot_jumps", {})
                for key, entry in list(ef.items()):
                    if not isinstance(entry, dict):
                        continue
                    # 到期条目本轮已删；这里只处理未到期的周期声明
                    exp = entry.get("expire")
                    if exp is not None and now >= float(exp):
                        continue
                    # 声明源：条目自带 period（动态）优先；回落表 period（V5 统一声明，
                    # 含 dir/interval/数值字段——表内已无旧 dot 字段）
                    period = entry.get("period")
                    if not isinstance(period, dict):
                        cfg = table.get(key) or {}
                        period = cfg.get("period")
                    if not isinstance(period, dict):
                        continue
                    n = int(entry.get("stacks", 0) or 0)
                    direction = str(period.get("dir", "damage") or "damage")
                    # v181.M-R2：dir=gain（资源自然回）不依赖现有层数——0 层也要回
                    # （游侠 energy 耗到 0 若被 n<=0 拦截将永远回不了，卡死）
                    if n <= 0 and direction != "gain":
                        continue
                    interval = float(period.get("interval", 1.0) or 1.0)
                    turns = int(period.get("turns", 0) or 0)
                    # 首次挂：登记下一跳（对齐旧 DOT/事件卡首跳延迟）
                    nx = dnext.get(key)
                    if nx is None:
                        dnext[key] = now + interval
                        continue
                    if now < float(nx):
                        continue  # 未到下一跳
                    guard = 0
                    while now >= float(dnext[key]) and guard < 20:
                        guard += 1
                        if direction == "damage":
                            pct = float(period.get("pct_max_hp", 0) or 0)
                            pct_cur = float(period.get("pct_cur_hp", 0) or 0)
                            if pct > 0:
                                # boss 档（数据标签 is_boss/role 选 pct_boss）
                                if (a.get("is_boss") or a.get("role") == "boss") and period.get("pct_boss"):
                                    pct = float(period["pct_boss"])
                                dmg = max(1, int(a.get("max_hp", 1) * pct * n))
                            elif pct_cur > 0:
                                if (a.get("is_boss") or a.get("role") == "boss") and period.get("pct_cur_boss"):
                                    pct_cur = float(period["pct_cur_boss"])
                                dmg = max(1, int(a.get("hp", 0) * pct_cur * n))
                            else:
                                dmg = max(1, n)
                            from .landing import deal_damage
                            # N9.14 dot_calc：DOT 伤害落地前乘区钩子（对齐 dmg_calc 模式）。
                            # broadcast（无 actor 主体键）——施毒者被动（万毒归宗等）在施放方
                            # 不在承伤者身上，subject 过滤会挡住；ctx.dot_key 供效果侧过滤。
                            try:
                                from .effect_triggers import fire as _fire
                                _dc = {"target": a, "dot_key": key, "dmg": dmg,
                                       "mult": 1.0}
                                _fire(battle, "dot_calc", _dc, logs)
                                _m = float((getattr(battle, "_fire_ctx", {}) or {})
                                           .get("mult", 1.0) or 1.0)
                                if _m != 1.0:
                                    dmg = max(1, int(dmg * _m))
                            except Exception:
                                pass  # 修正钩子异常不阻断 DOT 落地
                            deal_damage(battle, None, a, dmg, logs)
                            logs.append(f"🔥 {a.get('name', '目标')} 受 {key} {n} 层影响，损失 {dmg} 生命")
                            # N8 事件：DOT 每跳
                            try:
                                from .effect_triggers import fire as _fire
                                _fire(battle, "dot_tick", {"actor": a, "target": a,
                                                           "key": key, "dmg": dmg}, logs)
                            except Exception:
                                pass
                        elif direction == "heal":
                            from .landing import heal_actor as _heal_actor
                            _mx_hp = a.get("max_hp", a.get("hp", 1)) or 1
                            _hpct = float(period.get("heal_pct", entry.get("heal", 0)) or 0)
                            if _hpct > 0 and int(a.get("hp", 0) or 0) < _mx_hp:
                                _gain = max(1, int(_mx_hp * _hpct))
                                _real = _heal_actor(battle, a, _gain, logs)
                                if _real > 0:
                                    logs.append(f"🍲 {a.get('name', '目标')} 持续恢复，恢复 {_real} 点生命！")
                            # 持续恢复双资源：dir=heal 同时处理 mana_pct（食物 hot 回血回蓝同刻）
                            _mpct = float(period.get("mana_pct", entry.get("mana", 0)) or 0)
                            if _mpct > 0:
                                _mx_mp = a.get("max_mp", a.get("mp", 1)) or 1
                                if int(a.get("mp", 0) or 0) < _mx_mp:
                                    _gain = max(1, int(_mx_mp * _mpct))
                                    _before = int(a.get("mp", 0) or 0)
                                    a["mp"] = min(_mx_mp, _before + _gain)
                                    _real = int(a["mp"]) - _before
                                    if _real > 0:
                                        logs.append(f"🍲 {a.get('name', '目标')} 持续恢复，恢复 {_real} 点魔力！")
                        elif direction == "mana":
                            _mx_mp = a.get("max_mp", a.get("mp", 1)) or 1
                            _mpct = float(period.get("mana_pct", entry.get("mana", 0)) or 0)
                            if _mpct > 0 and int(a.get("mp", 0) or 0) < _mx_mp:
                                _gain = max(1, int(_mx_mp * _mpct))
                                _before = int(a.get("mp", 0) or 0)
                                a["mp"] = min(_mx_mp, _before + _gain)
                                _real = int(a["mp"]) - _before
                                if _real > 0:
                                    logs.append(f"🍲 {a.get('name', '目标')} 持续恢复，恢复 {_real} 点魔力！")
                        elif direction == "gain":
                            # v181.M-R2e：资源自然回/衰减（声明级，引擎零职业知识）——
                            # 给自身 effects[key] 加/减层 clamp [0, cap]（游侠 energy 每刻
                            # +18 专注流量制；牧师 faith 每刻 -0.7 慢衰减 = B3 float 通用层，
                            # amount 负值也走，clamp 下限 0 不归负）。cap 取 period.cap 或
                            # _stack_cap_of（方案 A 收敛：EFFECT_RULES 基础 + actor.bonus.cap
                            # 动态——v181.M-bonus 分域，旧 actor cap_bonus 键已全清）。
                            # 静默（资源跳不刷战斗日志）；写回经 _norm_stack 归一（int 资源
                            # 保持 int 观感，float 保留 6 位精度——10-0.7 → 9.3）。
                            _amt = float(period.get("amount", 0) or 0)
                            _cap = int(period.get("cap", 0) or 0)
                            if _cap <= 0:
                                _cap = _stack_cap_of(a, key)
                            if _amt != 0:
                                _cur = float(entry.get("stacks", 0) or 0)
                                _new = round(_cur + _amt, 6)
                                _new = max(0.0, min(float(_cap), _new))
                                if abs(_new - _cur) > 1e-9:
                                    from .effects import _norm_stack as _ns
                                    entry["stacks"] = _ns(_new)
                        # 限时周期：跳够 turns 次 → 清层（到期自然消失）
                        if turns > 0:
                            c = int(djump.get(key, 0) or 0) + 1
                            djump[key] = c
                            if c >= turns:
                                ef.pop(key, None)
                                dnext.pop(key, None)
                                djump.pop(key, None)
                                break
                        dnext[key] = float(dnext[key]) + interval
                    if not actor_alive(a):
                        break
