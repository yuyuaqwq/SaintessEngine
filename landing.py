# -*- coding: utf-8 -*-
"""v181.P4 battle2 引擎——落地接口层（landing.py）。

所有"造成伤害 / 治疗回血"统一收口在这里：
- deal_damage：伤害落地（等级压制 → defending 减伤 → 睡眠/蓄力 → 护盾 → 扣血 → 死亡）
- heal_actor：治疗落地（禁疗修正 → clamp max_hp）

为什么必须统一收口（鱼鱼架构原则）：伤害/治疗落地是"战斗物理规则"——
打谁/扣多少/护盾先挡/减伤先算/死了判负/治疗 clamp 上限。若每个机制
自己写扣血，会出现旧引擎那种"某技能绕过护盾直接扣血"的 bug。

一切来源（普攻/技能/effect handler/DOT/反伤/上层职业模块）都调本层接口，
永远走同一收口，杜绝绕过护盾/死亡判定。
"""
from __future__ import annotations

from typing import Optional

# ============================================================
# 伤害落地
# ============================================================

def deal_damage(battle, source: Optional[dict], target: dict, amount: int,
                logs: list, dmg_kind: str = "") -> int:
    """伤害落地主链。返回实际扣血。

    source: 攻击方 actor（等级压制基准；None = 无来源不压制）
    target: 承伤 actor
    amount: 计划伤害（技能公式算好的值）
    dmg_kind: "phys"/"magi"/"true"/""（免伤等按类型消费，后续扩展）
    """
    if not target or amount <= 0:
        return 0
    # 等级压制（v136 双向曲线：低打高削/高打低增；PVP 不压）
    dmg = _lv_pressure(battle, source, target, amount)
    if dmg <= 0:
        return 0
    # defending 减伤（防御姿态伤害减半）
    if target.get("defending"):
        dmg = max(1, int(dmg * 0.5))
        logs.append(f"(格挡后 {dmg} 点伤害)")
    # 睡眠被打醒（主动伤害打醒睡眠）
    if target.get("buffs", {}).get("sleep"):
        target["buffs"].pop("sleep", None)
        logs.append("💥 目标被攻击惊醒！")
    # 蓄力打断（主动伤害打断读条；DOT wake_sleep=False 不打）
    if target.get("charging") and target["charging"].get("skill"):
        target["charging"] = None
        logs.append(f"🔨 {target.get('name', '目标')} 的蓄力被打破了！")
    # 承伤落地（护盾吸收 → 扣血 → 死亡）
    return _apply_damage(battle, target, dmg, logs)


def _lv_pressure(battle, source: Optional[dict], target: dict, dmg: int) -> int:
    """v136 双向等级压制曲线（与旧 _deal_damage 逐字对齐）。

    低打高：低 1-3 级 ×0.95/级，低 4+ 级 ×0.90/级（指数，封顶 ×0.30）
    高打低：每高 1 级 ×1.02 连乘（指数，不封顶）
    PVP 不压；攻击方/目标无 level 不压。

    ⚠️ actor 全同构：统一用 level 字段（旧数据层怪用 lv，入口翻译掉）。
    """
    if battle.btype == "pvp":
        return dmg
    if not source:
        return dmg
    atk_lv = source.get("level")
    tgt_lv = target.get("level")
    if not atk_lv or not tgt_lv:
        return dmg
    try:
        plv = int(atk_lv)
        diff = int(tgt_lv) - plv
        if diff > 0:
            mult = 1.0
            for i in range(min(diff, 10)):
                mult *= (0.95 if i < 3 else 0.90)
            return max(1, int(dmg * max(0.30, mult)))
        elif diff < 0:
            return max(1, int(dmg * (1.02 ** min(-diff, 50))))
    except Exception:
        pass
    return dmg


def _apply_damage(battle, target: dict, dmg: int, logs: list) -> int:
    """承伤落地：护盾吸收 → hp 扣减 → 死亡判定。返回实际扣血。"""
    # 护盾吸收（shields = {key: {value, halve, expire_at}}）
    shields = target.get("shields") or {}
    if shields:
        remaining = dmg
        for sk in list(shields.keys()):
            sh = shields[sk]
            if not isinstance(sh, dict) or int(sh.get("value", 0) or 0) <= 0:
                continue
            sv = int(sh["value"])
            absorb = min(sv, remaining)
            sh["value"] = sv - absorb
            remaining -= absorb
            logs.append(f"🛡️ {target.get('name', '目标')} 的护盾吸收了 {absorb} 点伤害！")
            if sh["value"] <= 0:
                shields.pop(sk, None)
            if remaining <= 0:
                break
        dmg = remaining
    if dmg <= 0:
        return 0
    old = int(target.get("hp", 0) or 0)
    new = max(0, old - dmg)
    target["hp"] = new
    _real = old - new
    if new <= 0:
        logs.append(f"💥 {target.get('name', '目标')} 受到 {_real} 点伤害，倒下了！")
        if hasattr(battle, "_on_actor_dead"):
            battle._on_actor_dead(target)
    else:
        logs.append(f"💥 {target.get('name', '目标')} 受到 {_real} 点伤害！")
    return _real


# ============================================================
# 治疗落地
# ============================================================

def heal_actor(battle, target: dict, amount: int, logs: list,
               source: Optional[dict] = None, label: str = "") -> int:
    """治疗落地核心（actor-agnostic，统一收口）。

    - 禁疗修正（target.state/buffs 的 heal_down / _anti_heal_pct，后续扩展）
    - clamp max_hp
    返回实际回血量。
    """
    if target is None or amount is None:
        return 0
    if target.get("hp") is None:
        return 0  # 无 hp 容器不可被治疗落地
    heal = max(0, int(amount))
    if heal <= 0:
        return 0
    # 禁疗/重伤修正（target 自身状态）
    heal = _apply_heal_mods(target, heal, logs)
    if heal <= 0:
        return 0
    _mx = target.get("max_hp", target.get("hp", 1)) or 1
    _before = int(target.get("hp", 0) or 0)
    target["hp"] = min(_mx, _before + heal)
    _real = int(target["hp"]) - _before
    if _real > 0 and label:
        logs.append(label.format(_real=_real, _planned=heal))
    return _real


def _apply_heal_mods(target: dict, amount: int, logs: list) -> int:
    """受疗/禁疗修正（target 自身状态）。返回修正后治疗量（未 clamp）。"""
    heal = amount
    try:
        # 禁疗（heal_down 层×10% cap50%）
        bf = target.get("buffs") or {}
        ehd = int(bf.get("heal_down", 0) or 0)
        if ehd > 0:
            cut = min(ehd * 0.10, 0.50)
            heal = max(0, int(heal * (1 - cut)))
            logs.append(f"🩸 禁疗：治疗量 -{int(cut * 100)}%！")
        # 重伤（_anti_heal_pct cap80%）
        aheal = float(bf.get("_anti_heal_pct", 0) or 0)
        if aheal > 0:
            cut2 = min(aheal, 0.80)
            heal = max(0, int(heal * (1 - cut2)))
            logs.append(f"🩸 重伤：治疗量 -{int(cut2 * 100)}%！")
    except Exception:
        pass
    return max(0, heal)
