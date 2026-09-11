# -*- coding: utf-8 -*-
"""《铆炉回声》——本游戏的机制动作（@register_action）。

引擎只给「能做什么」（8 个内置动词 + register_action 任意扩展），
本文件是内容侧自己写的 3 个动词。铁律（wiki guides/write-a-mechanic.md）：

  1. 落地一定走 landing：伤害 deal_damage / 治疗 heal_actor（不要自己扣 hp）
  2. 缺字段 = 无行为（零默认值）：params.get(...) 判 <=0 就 return
  3. 不抛异常（引擎会吞掉并跳过本动作）
  4. 日志就是 logs.append(...)

只用引擎公开 API：register_action / apply_effects / deal_damage /
actor_alive / actor_stats（都在 saintess_engine.__all__ 里）。
"""
from __future__ import annotations

from saintess_engine import (
    actor_alive, actor_stats, apply_effects, deal_damage, register_action,
)


def _holder_of(caster, params):
    """效果宿主：事件总线会给声明者注入 params["_owner"]（谁带的这个声明）。"""
    return params.get("_owner") or caster


def _stacks(actor, key) -> int:
    entry = (actor.get("effects") or {}).get(key) if actor else None
    return int(entry.get("stacks", 0) or 0) if isinstance(entry, dict) else 0


def _when_ok(actor, when) -> bool:
    """渠道条件求值：全部满足才为真；未知 kind → False（fail-closed）。"""
    for cond in (when or []):
        judge = (cond or {}).get("judge") or {}
        kind = judge.get("kind")
        if kind == "has_effect":
            if not isinstance((actor.get("effects") or {}).get(judge.get("key")), dict):
                return False
        elif kind == "res_ge":
            need = int(judge.get(judge.get("ge_field") or "stacks", 0) or 0)
            if _stacks(actor, judge.get("res")) < need:
                return False
        else:
            return False
    return True


@register_action("res_gain")
def res_gain(battle, caster, target, params, logs):
    """资源攒取渠道：把 EFFECT_RULES[key]["channels"] 的声明落成一次叠层 +N。

    参数：key / gain / when[] / per_dt（时钟事件按 dt 缩放，防跨刻漏攒）。
    """
    holder = _holder_of(caster, params)
    key = params.get("key")
    gain = float(params.get("gain") or 0)
    if holder is None or not key or gain <= 0:
        return
    if not _when_ok(holder, params.get("when")):
        return
    if params.get("per_dt"):
        ctx = getattr(battle, "_fire_ctx", None) or {}
        try:
            gain *= float(ctx.get("dt") or 1.0)
        except Exception:
            gain = 0.0
    if gain <= 0:
        return
    apply_effects(battle, holder, holder,
                  [{"action": "apply", "op": "add", "key": key,
                    "amount": gain, "on": "caster"}], logs)


@register_action("heat_vent")
def heat_vent(battle, caster, target, params, logs):
    """★ 本游戏的核心机制：普攻命中后，按「炉温」层数追加一段贯穿伤害并耗层。

    参数：key（资源 key）/ per_layer（每层伤害）/ min_layers（起步层数）/ spend（消耗层数）
    """
    holder = _holder_of(caster, params)
    res = params.get("key")
    per_layer = float(params.get("per_layer") or 0)
    need = int(params.get("min_layers") or 0)
    spend = int(params.get("spend") or 0)
    if holder is None or not res or per_layer <= 0 or target is None:
        return
    n = _stacks(holder, res)
    if n <= 0 or n < need or not actor_alive(target):
        return
    dmg = max(1, int(n * per_layer))
    real = deal_damage(battle, holder, target, dmg, logs)
    if real > 0:
        logs.append(f"♨️ 炉温喷涌：{n} 层炉温追加 {real} 点贯穿伤害！")
    if spend > 0:
        apply_effects(battle, holder, holder,
                      [{"action": "consume", "key": res,
                        "amount": spend, "on": "caster"}], logs)


@register_action("backdraft")
def backdraft(battle, caster, target, params, logs):
    """被动 proc（PASSIVE_PROC 装配）：受击后按自身攻击力比例反击伤害来源。

    事件数值不在 params 里，在 battle._fire_ctx（单槽覆盖式）——必须**同步读完**。
    """
    ctx = getattr(battle, "_fire_ctx", None) or {}
    source = ctx.get("source")          # ← 先读，后面对账会再次 fire 覆盖本槽
    holder = _holder_of(caster, params)
    pct = float(params.get("pct") or 0)
    if holder is None or pct <= 0 or source is None or not actor_alive(source):
        return
    atk = int(actor_stats(battle, holder).get("atk", 0) or 0)
    dmg = max(1, int(atk * pct))
    real = deal_damage(battle, holder, source, dmg, logs)
    if real > 0:
        logs.append(f"🔥 回火：{holder.get('name')} 反击 {source.get('name')} {real} 点伤害！")
