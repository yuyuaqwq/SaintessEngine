# -*- coding: utf-8 -*-
"""v181.P4 battle2 引擎——效果系统（effects.py）。

按 docs/REFACTOR_v181P4_FULL_PLAN.md Part 3：
- EFFECT_HANDLERS 单表（替代旧 MECH_EFFECTS / SKILL_BUFF_EFFECTS 双表 + 死表）
- handler 统一签名：fn(battle, caster, target, params, logs) -> None
  caster = 施法者 actor（自我增益作用对象）
  target = 作用目标（对敌效果/治疗目标；None=无对象）
  params = 效果参数字典（stacks/turns/pct/value/... 由技能 mech/effect 字段转来）
- 引擎逻辑只用显式 caster/target，不猜隐式全局目标

⚠️ 迁移原则（鱼鱼拍板：不陪葬旧 bug）：
- 旧 handler 与 battle 内部状态强耦合（_hit_tgt/_passive_map/_tick_no），
  新 handler 重写为纯 actor 字段读写，不 import 旧 battle_mech
- 效果语义按 desc/设计对齐；旧引擎里被测试固化的 bug 不跟随
"""
from __future__ import annotations

from typing import Callable, Optional

from .actors import state_add, state_get, state_spend
from .state_effects import state_def

# ============================================================
# 注册表
# ============================================================

EFFECT_HANDLERS: dict = {}

# 签名：fn(battle, caster, target, params, logs)
EffectHandler = Callable


def register_effect(key):
    """装饰器：注册效果 handler。"""
    def deco(fn):
        EFFECT_HANDLERS[key] = fn
        return fn
    return deco


def apply_effects(battle, caster: dict, target: Optional[dict],
                  effects: list, logs: list) -> None:
    """执行效果列表。

    effects = [{"type": "bleed", "stacks": 2, ...}, ...]（技能数据 effects 字段，
    或由 mech/effect 兼容层转出）。按 type 查 EFFECT_HANDLERS 执行。
    """
    if not effects:
        return
    for eff in effects:
        if not isinstance(eff, dict):
            continue
        etype = eff.get("type")
        handler = EFFECT_HANDLERS.get(etype)
        if handler:
            try:
                handler(battle, caster, target, eff, logs)
            except Exception:
                # 单个 handler 异常不阻断后续（引擎容错）
                continue


def effects_from_skill(info: dict, lv: int, caster_side_is_player: bool = True) -> list:
    """从技能 dict 的 mech/effect 字段生成统一 effects 列表（兼容层）。

    迁移期用：技能数据还是旧格式（mech/effect 字段），
    N3 后数据层迁移成 effects 列表，本函数可删。

    mech 分派（查 state_effects 声明表，引擎不硬编码 key）：
    - key 声明为状态叠层（stat_scale/dot 在表里，无 on=target）→ 通用 state_add
    - 否则按原 type 走 EFFECT_HANDLERS（控制/盾等真·动作效果）
    """
    effects = []
    # mech → 状态/效果
    mech = info.get("mech") or ""
    mval = int(info.get("mech_val", 0) or 0)
    if mech and mval:
        effects.append(_mech_to_effect(mech, mval, info))
    # mech2（第二 mech）
    mech2 = info.get("mech2") or ""
    if mech2:
        m2v = int(info.get("mech2_val", 0) or 0)
        effects.append(_mech_to_effect(mech2, m2v, info))
    return effects


def _mech_to_effect(mech: str, mval: int, info: dict) -> dict:
    """单个 mech key → effect dict（查 state_effects 声明表分派）。"""
    cfg = state_def(mech)
    on_target = bool(cfg.get("on") == "target")
    # 声明表里的叠层/资源/dot 类 → 统一 state_add（引擎不认识 key 语义）
    if cfg:
        return {"type": "state_add", "key": mech, "amount": mval,
                "on": "target" if on_target else "caster",
                "info": info}
    # 真·动作效果（控制/盾等，EFFECT_HANDLERS 注册）
    return {"type": mech, "stacks": mval,
            "turns": int(info.get("cc_turns", 0) or 0),
            "mech": mech, "info": info}


def _cc_turns_of(info: dict, lv: int) -> int:
    """控制/减益持续刻数（cc 字段优先，缺省按技能等级成长）。"""
    cc = info.get("cc") or {}
    if isinstance(cc, dict):
        t = int(cc.get("turns", 0) or 0)
        if t > 0:
            return t
    return int(info.get("cc_turns", 0) or 0) or max(1, min(lv, 3))


# ============================================================
# 对敌标记/DOT 已声明化（state_effects 表 on=target + dot 规则），
# 由通用 state_add 写入 actor.state，N4 schedule 通用 dot 结算消费。
# 引擎不注册 burn/bleed/poison/hunt_mark/元素印记 专用 handler。
# ============================================================

# ============================================================
# 控制类（写 target.buffs 一次性控制标记）
# ============================================================

@register_effect("stun")
def eff_stun(battle, caster, target, params, logs):
    """眩晕：持续 N 刻（写 target.buffs["stun"]=刻数）。"""
    if not target:
        return
    turns = int(params.get("turns", 0) or 0) or 1
    # Boss 控制减半（对齐旧 _boss_ctrl_dur）
    if target.get("is_boss") or target.get("role") == "boss":
        turns = max(1, turns // 2)
    target.setdefault("buffs", {})["stun"] = max(int(target.get("buffs", {}).get("stun", 0) or 0), turns)
    logs.append(f"💫 敌人被眩晕 {turns} 刻！")


@register_effect("freeze")
def eff_freeze(battle, caster, target, params, logs):
    """冻结：持续 1 刻（跳过一次行动）。"""
    if not target:
        return
    target.setdefault("buffs", {})["freeze"] = 1
    logs.append("❄️ 敌人被冻结，跳过下刻！")


@register_effect("silence")
def eff_silence(battle, caster, target, params, logs):
    """沉默：持续 N 刻（不能放技能）。"""
    if not target:
        return
    turns = int(params.get("turns", 0) or 0) or 1
    target.setdefault("buffs", {})["silence"] = max(int(target.get("buffs", {}).get("silence", 0) or 0), turns)
    logs.append(f"🤐 敌人被沉默 {turns} 刻！")


@register_effect("slow")
def eff_slow(battle, caster, target, params, logs):
    """减速（弱）：速度下降。写 target.buffs["spd_down"]。"""
    if not target:
        return
    turns = int(params.get("turns", 0) or 0) or 2
    target.setdefault("buffs", {})["spd_down"] = max(int(target.get("buffs", {}).get("spd_down", 0) or 0), turns)
    logs.append(f"🐌 敌人被减速 {turns} 刻！")


@register_effect("spd_down")
def eff_spd_down(battle, caster, target, params, logs):
    """减速（强）：速度大幅下降。写 target.buffs["spd_down"]。"""
    eff_slow(battle, caster, target, params, logs)


@register_effect("sleep")
def eff_sleep(battle, caster, target, params, logs):
    """睡眠：被攻击打醒。写 target.buffs["sleep"]。"""
    if not target:
        return
    turns = int(params.get("turns", 0) or 0) or 1
    target.setdefault("buffs", {})["sleep"] = max(int(target.get("buffs", {}).get("sleep", 0) or 0), turns)
    logs.append("😴 敌人陷入沉睡！（受到攻击会醒来）")


# ============================================================
# 状态数值（统一 state 容器；引擎零职业语义，key 全数据驱动）
# ============================================================

@register_effect("state_add")
def eff_state_add(battle, caster, target, params, logs):
    """通用状态加值：给 actor.state[key] 加 amount（cap 查声明表）。

    effect type 单一入口；具体加什么 key、影响什么由数据声明，
    引擎不 care key 语义。mech 兼容层把 mech key 原样传到这里。
    """
    actor = params.get("on", "caster")
    holder = caster if actor == "caster" else (target or caster)
    if not holder:
        return
    key = params.get("key") or params.get("mech")
    amount = int(params.get("amount", params.get("stacks", 0)) or 0)
    if not key or amount <= 0:
        return
    n = state_add(holder, key, amount)
    cap = int(state_def(key).get("cap") or 0)
    cap_txt = f"/{cap}" if cap else ""
    logs.append(f"✦ {key} {n}{cap_txt}（+{amount}）")


@register_effect("state_spend")
def eff_state_spend(battle, caster, target, params, logs):
    """通用状态消费：actor.state[key] 扣 amount（下限 0）。

    技能要"花 N 层 X 换效果" = state_spend + 后续 effect 组合。
    """
    actor = params.get("on", "caster")
    holder = caster if actor == "caster" else (target or caster)
    if not holder:
        return
    key = params.get("key") or params.get("mech")
    amount = int(params.get("amount", params.get("stacks", 0)) or 0)
    if not key or amount <= 0:
        return
    cur = state_get(holder, key)
    if cur < amount:
        logs.append(f"⚠️ {key} 不足（需 {amount}，当前 {cur}）")
        return
    state_spend(holder, key, amount)
    logs.append(f"✦ 消耗 {amount} 点 {key}（剩余 {cur - amount}）")


# ============================================================
# 技能 effect（增益类，SKILL_BUFF_EFFECTS 迁入子集）
# ============================================================

@register_effect("atk_up")
def eff_atk_up(battle, caster, target, params, logs):
    """攻击上升：写 caster.buffs["atk_up"]=刻数。"""
    if not caster:
        return
    turns = int(params.get("turns", 0) or 0) or 3
    caster.setdefault("buffs", {})["atk_up"] = max(int(caster.get("buffs", {}).get("atk_up", 0) or 0), turns)
    logs.append(f"⚔️ 攻击提升！（持续 {turns} 刻）")


# 团队/全员增益 effect → 自身有效键（旧 MECH_CFG['buff']['team_keys'] 同语义）
_TEAM_KEYS = {
    "atk_all": "atk_up", "def_all": "def_up", "matk_all": "matk_up_strong",
    "crit_all": "crit_up", "spd_all": "spd_up",
}

for _team_eff, _self_key in _TEAM_KEYS.items():
    def _mk_team_buff(battle, caster, target, params, logs, _k=_team_eff, _sk=_self_key):
        if not caster:
            return
        turns = int(params.get("turns", 0) or 0) or 3
        caster.setdefault("buffs", {})[_sk] = max(int(caster.get("buffs", {}).get(_sk, 0) or 0), turns)
        logs.append(f"✨ 全队增益（自身 {_sk} 提升，持续 {turns} 刻）")
    EFFECT_HANDLERS[_team_eff] = _mk_team_buff


@register_effect("reduce")
def eff_reduce(battle, caster, target, params, logs):
    """减伤（单人）：buffs["reduce"]=百分比 + reduce_left 剩余刻。
    值优先 info.reduce_pct，回落 mech_val（45=45% 或 0.45），默认 0.20。"""
    if not caster:
        return
    info = params.get("info") or {}
    rp = float(info.get("reduce_pct") or 0)
    if rp <= 0:
        mv = float(params.get("mech_val") or info.get("mech_val") or 0)
        rp = (mv / 100.0) if mv > 1 else (mv if 0 < mv <= 1 else 0.20)
    rp = min(max(rp, 0.0), 0.9)
    turns = max(1, int(params.get("turns", 0) or 0) or 3)
    caster.setdefault("buffs", {})["reduce"] = rp
    caster["reduce_left"] = max(int(caster.get("reduce_left", 0) or 0), turns)
    logs.append(f"🛡️ 减伤 {int(rp*100)}%（持续 {caster['reduce_left']} 刻）")


@register_effect("shield_self")
def eff_shield_self(battle, caster, target, params, logs):
    """自护盾：写 caster.shields["buff"]={value, halve:False}。盾值 mech_val/effect_val。"""
    if not caster:
        return
    info = params.get("info") or {}
    mv = int(params.get("mech_val") or 0) or int(info.get("mech_val", 0) or 0) \
        or int(info.get("effect_val", 0) or 0)
    if mv <= 0:
        # 无明确盾值 → max_hp×shield_pct（默认 20%）
        pct = float(info.get("shield_pct", 0.20) or 0.20)
        mv = int(caster.get("max_hp", 1) * pct)
    caster.setdefault("shields", {})["buff"] = {"value": int(mv), "halve": False}
    logs.append(f"🛡️ 获得护盾 {int(mv)} 点！")


@register_effect("shield")
def eff_shield(battle, caster, target, params, logs):
    """怪护盾：写施法者 shields（halve=True 受伤减半）。盾值 = max_hp×20%。"""
    actor = caster or target
    if not actor:
        return
    info = params.get("info") or {}
    pct = float(info.get("shield_pct", 0.20) or 0.20)
    val = int(actor.get("max_hp", 1) * pct)
    actor.setdefault("shields", {})["buff"] = {"value": val, "halve": True}
    logs.append(f"🛡️ 【{actor.get('name', '怪物')}】周身浮现一层护盾(受伤减半)！")


@register_effect("dodge_buff")
def eff_dodge_buff(battle, caster, target, params, logs):
    """闪避增益：写 caster.buffs["dodge_up"]=刻数。"""
    if not caster:
        return
    turns = int(params.get("turns", 0) or 0) or 3
    caster.setdefault("buffs", {})["dodge_up"] = max(int(caster.get("buffs", {}).get("dodge_up", 0) or 0), turns)
    logs.append(f"💨 闪避提升！（持续 {turns} 刻）")


@register_effect("spd_buff")
def eff_spd_buff(battle, caster, target, params, logs):
    """速度增益：写 caster.buffs["spd_up"]=刻数。"""
    if not caster:
        return
    turns = int(params.get("turns", 0) or 0) or 3
    caster.setdefault("buffs", {})["spd_up"] = max(int(caster.get("buffs", {}).get("spd_up", 0) or 0), turns)
    logs.append(f"💨 速度提升！（持续 {turns} 刻）")


@register_effect("crit_hit_buff")
def eff_crit_buff(battle, caster, target, params, logs):
    """暴击增益：写 caster.buffs["crit_up"]=刻数。"""
    if not caster:
        return
    turns = int(params.get("turns", 0) or 0) or 3
    caster.setdefault("buffs", {})["crit_up"] = max(int(caster.get("buffs", {}).get("crit_up", 0) or 0), turns)
    logs.append(f"🎯 暴击提升！（持续 {turns} 刻）")


@register_effect("cc_immune")
def eff_cc_immune(battle, caster, target, params, logs):
    """控制免疫：写 caster.buffs["cc_immune"]=刻数。"""
    if not caster:
        return
    turns = int(params.get("turns", 0) or 0) or 3
    caster.setdefault("buffs", {})["cc_immune"] = max(int(caster.get("buffs", {}).get("cc_immune", 0) or 0), turns)
    logs.append(f"🛡️ 免疫控制！（持续 {turns} 刻）")


@register_effect("cleanse")
def eff_cleanse(battle, caster, target, params, logs):
    """净化：移除目标身上的 DOT/标记/控制。

    - DOT/标记（state 容器）：查 state_effects 表里 dot/on=target 的 key 动态清理
      （引擎不认识具体 key，全表驱动）
    - 控制（buffs 容器）：stun/silence/freeze/spd_down/reduce 等
    """
    from .state_effects import STATE_EFFECTS
    actor = target or caster
    if not actor:
        return
    rem = []
    st = actor.setdefault("state", {})
    for k in list(st.keys()):
        cfg = STATE_EFFECTS.get(k) or {}
        if cfg.get("dot") or cfg.get("on") == "target":
            rem.append(k)
            st.pop(k, None)
    for k in ("stun", "silence", "freeze", "spd_down", "reduce"):
        bf = actor.setdefault("buffs", {})
        if k in bf:
            rem.append(k)
            bf.pop(k, None)
    if rem:
        logs.append(f"✨ 净化了 {'、'.join(rem)}！")
    else:
        logs.append("✨ 净化（无减益可解）")


@register_effect("cleanse_all")
def eff_cleanse_all(battle, caster, target, params, logs):
    """全体净化：移除施法者自身全部减益（副本广播在命令层）。"""
    eff_cleanse(battle, caster, target or caster, params, logs)
