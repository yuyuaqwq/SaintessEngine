# -*- coding: utf-8 -*-
"""v181.P4 battle2 引擎——效果执行器（effects.py，动词版）。

框架/配置分离（鱼鱼拍板：换一套配置 = 新游戏）：
- 引擎只提供【动词执行器】——能力，不含任何游戏内容判断
- 游戏【名词效果】→ 动词动作序列 的映射在 config 挂载的游戏规则里
  （game/data/battle2_rules.py EFFECT_ACTIONS）
- 名词效果先经配置翻译成动词动作，再执行

动词（引擎注册，全部通用）：
  control   : 让目标 N 刻不能行动（tag: 控制类型由数据给）
  buff      : 给 actor 挂属性/减伤 buff（key/value/turns 由数据给）
  shield    : 护盾（value/halve 由数据给）
  cleanse   : 清减益（DOT/标记/控制，查 state 表驱动）
  state_add / state_spend : 统一 state 数值容器增减
  heal / damage          : 落地接口（landing）薄包装

签名：fn(battle, caster, target, params, logs)
  caster = 施法者 actor；target = 作用目标；params = 动作参数
"""
from __future__ import annotations

from typing import Callable, Optional

from .actors import state_add, state_get, state_spend
from .state_effects import state_def

# ============================================================
# 动词注册表
# ============================================================

ACTION_HANDLERS: dict = {}
# 兼容旧名（迁移期 EFFECT_HANDLERS 仍可用，指向同一表）
EFFECT_HANDLERS: dict = ACTION_HANDLERS

# 签名：fn(battle, caster, target, params, logs)
ActionHandler = Callable


def register_action(key):
    """装饰器：注册动词执行器。"""
    def deco(fn):
        ACTION_HANDLERS[key] = fn
        return fn
    return deco


# ============================================================
# 分发
# ============================================================

def resolve_actions(name: str) -> list:
    """名词效果名 → 动词动作列表（查游戏配置 EFFECT_ACTIONS）。

    找不到映射时按"本身就是动词"处理（动作名直通执行器）。
    """
    from . import config
    table = config.get_effect_actions()
    mapped = table.get(name)
    if isinstance(mapped, list):
        return mapped
    if isinstance(mapped, dict):
        return [dict(mapped)]
    # 未配置名词映射：若引擎有该动词直接执行器，按动词处理
    if name in ACTION_HANDLERS:
        return [{"action": name}]
    return []


def _merge_params(eff: dict, act: dict) -> dict:
    """调用方参数与映射动作参数合并：调用方显式参数优先（turns/值 由技能决定）。"""
    params = dict(eff)
    for k, v in act.items():
        if k == "action":
            continue
        # 调用方已显式给该参数 → 尊重调用方；否则用映射默认
        if k not in params or params[k] is None:
            params[k] = v
    return params


def apply_effects(battle, caster: dict, target: Optional[dict],
                  effects: list, logs: list) -> None:
    """执行效果/动作列表。

    effects = [{"type": 名词 或 动词, ...}, ...]。
    名词先查配置翻译成动词；动词直通执行器。
    """
    if not effects:
        return
    for eff in effects:
        if not isinstance(eff, dict):
            continue
        etype = eff.get("type") or eff.get("action")
        if not etype:
            continue
        actions = resolve_actions(etype)
        if not actions and etype not in ACTION_HANDLERS:
            continue  # 未知名词/动词：跳过（引擎容错）
        for act in actions:
            if isinstance(act, str):
                act = {"action": act}
            params = _merge_params(eff, act)
            act_name = act.get("action") or etype
            handler = ACTION_HANDLERS.get(act_name)
            if handler:
                try:
                    handler(battle, caster, target, params, logs)
                except Exception:
                    # 单个 handler 异常不阻断后续（引擎容错）
                    continue


# 兼容便捷名（旧代码/测试仍可用）
def apply_action(battle, caster, target, action, params, logs) -> None:
    apply_effects(battle, caster, target, [dict(action=action, **params)], logs)


# ============================================================
# 兼容层：技能 mech/effect 字段 → 动作/状态列表
# ============================================================

def effects_from_skill(info: dict, lv: int, caster_side_is_player: bool = True) -> list:
    """从技能 dict 的 mech/effect 字段生成统一 effects 列表（迁移期兼容层）。

    mech 分派（查 state_effects 声明表，引擎不硬编码 key）：
    - key 在 state 规则表（含 on=target/dot 声明）→ 通用 state_add 动作
    - 否则保留名词 type，由 EFFECT_ACTIONS 配置翻译成动词
    """
    effects = []
    mech = info.get("mech") or ""
    mval = int(info.get("mech_val", 0) or 0)
    if mech and mval:
        effects.append(_mech_to_effect(mech, mval, info))
    mech2 = info.get("mech2") or ""
    if mech2:
        m2v = int(info.get("mech2_val", 0) or 0)
        effects.append(_mech_to_effect(mech2, m2v, info))
    return effects


def _mech_to_effect(mech: str, mval: int, info: dict) -> dict:
    """单个 mech key → effect dict（查 state 规则表分派）。"""
    cfg = state_def(mech)
    on_target = bool(cfg.get("on") == "target")
    if cfg:
        return {"type": "state_add", "key": mech, "amount": mval,
                "on": "target" if on_target else "caster",
                "info": info}
    # 名词（控制/盾等）→ 保留 type，由 EFFECT_ACTIONS 配置翻译
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
# 动词执行器
# ============================================================

# ---- control：让目标 N 刻不能行动 ----

@register_action("control")
def act_control(battle, caster, target, params, logs):
    """控制：写 target.buffs[tag]=刻数。tag/turns 由数据给。

    引擎不认"眩晕/冻结/沉默"——只执行"目标被标记为 tag 持续 N 刻"，
    消费（跳过行动/禁技能）由调度层按 tag 查配置。
    """
    if not target:
        return
    tag = params.get("tag") or params.get("key")
    turns = int(params.get("turns", 0) or 0)
    if not tag or turns <= 0:
        return
    # Boss 控制减半（对齐旧 _boss_ctrl_dur）
    if target.get("is_boss") or target.get("role") == "boss":
        turns = max(1, turns // 2)
    bf = target.setdefault("buffs", {})
    bf[tag] = max(int(bf.get(tag, 0) or 0), turns)
    logs.append(f"💫 {target.get('name', '目标')} 被【{tag}】{turns} 刻！")


# ---- buff：给 actor 挂属性/减伤/免疫 buff ----

@register_action("buff")
def act_buff(battle, caster, target, params, logs):
    """通用 buff：写 actor.buffs[key]=刻数（或 value 型）。

    key/turns/value 由数据给。引擎只执行"buff key 挂 N 刻"，
    属性乘区消费在 stats（读 buffs + 游戏规则折算）。

    value 型（如减伤百分比）：params["value"] 或
    pct_from_mech_val=true（配置声明 value 从 mech_val 折算：45→0.45）。
    """
    holder = caster if params.get("on", "caster") == "caster" else (target or caster)
    if not holder:
        return
    key = params.get("key") or params.get("tag")
    turns = int(params.get("turns", 0) or 0)
    if not key or turns <= 0:
        return
    bf = holder.setdefault("buffs", {})
    # value 型（如 reduce=0.45）：直接存值（浮点百分比）
    value = params.get("value")
    if params.get("pct_from_mech_val"):
        mv = float(params.get("mech_val") or 0)
        value = (mv / 100.0) if mv > 1 else mv  # 45→0.45；0.45→0.45
    if value is not None:
        bf[key] = max(float(bf.get(key, 0) or 0), float(value))
        if key == "reduce":
            holder["reduce_left"] = max(int(holder.get("reduce_left", 0) or 0), turns)
        logs.append(f"🛡️ {key} {float(value):.0%}（持续 {turns} 刻）")
        return
    bf[key] = max(int(bf.get(key, 0) or 0), turns)
    logs.append(f"✦ {key} 提升（持续 {turns} 刻）")


# ---- shield：护盾 ----

@register_action("shield")
def act_shield(battle, caster, target, params, logs):
    """护盾：写 actor.shields["buff"]={value, halve}。value/halve 由数据给。"""
    holder = caster if params.get("on", "caster") == "caster" else (target or caster)
    if not holder:
        return
    info = params.get("info") or {}
    value = int(params.get("value") or params.get("mech_val") or 0)
    pct = float(params.get("pct", info.get("shield_pct", 0)) or 0)
    if value <= 0 and pct > 0:
        value = int(holder.get("max_hp", 1) * pct)
    if value <= 0:
        value = int(holder.get("max_hp", 1) * 0.20)
    halve = bool(params.get("halve", False))
    holder.setdefault("shields", {})["buff"] = {"value": value, "halve": halve}
    logs.append(f"🛡️ {holder.get('name', '目标')} 获得护盾 {value} 点！")


# ---- cleanse：净化 ----

@register_action("cleanse")
def act_cleanse(battle, caster, target, params, logs):
    """净化：移除目标身上的 DOT/标记/控制。

    - DOT/标记（state 容器）：查 state 规则表 dot/on=target 的 key 动态清理
    - 控制（buffs 容器）：按 control_tags 配置清（引擎查配置）
    """
    from . import config
    from .state_effects import all_state_effects
    actor = target or caster
    if not actor:
        return
    rem = []
    st = actor.setdefault("state", {})
    state_table = all_state_effects()
    for k in list(st.keys()):
        cfg = state_table.get(k) or {}
        if cfg.get("dot") or cfg.get("on") == "target":
            rem.append(k)
            st.pop(k, None)
    # 控制 tag 清理（配置声明的控制键；缺省常见集）
    ctrl_tags = config.get_cleanse_tags()
    bf = actor.setdefault("buffs", {})
    for k in ctrl_tags:
        if k in bf:
            rem.append(k)
            bf.pop(k, None)
    if rem:
        logs.append(f"✨ 净化了 {'、'.join(rem)}！")
    else:
        logs.append("✨ 净化（无减益可解）")


@register_action("cleanse_all")
def act_cleanse_all(battle, caster, target, params, logs):
    """全体净化：施法者自身全部减益（副本广播在命令层）。"""
    act_cleanse(battle, caster, target or caster, params, logs)


# ---- state 数值（统一 state 容器） ----

@register_action("state_add")
def act_state_add(battle, caster, target, params, logs):
    """通用状态加值：actor.state[key] 加 amount（cap 查规则表）。"""
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


@register_action("state_spend")
def act_state_spend(battle, caster, target, params, logs):
    """通用状态消费：actor.state[key] 扣 amount（下限 0）。"""
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
