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
                logs: list, dmg_kind: str = "", defend_reduce: Optional[float] = None,
                element: str = "") -> int:
    """伤害落地主链。返回实际扣血。

    source: 攻击方 actor（等级压制基准；None = 无来源不压制）
    target: 承伤 actor
    amount: 计划伤害（技能公式算好的值）
    dmg_kind: "phys"/"magi"/"true"/""（免伤等按类型消费，后续扩展）
    defend_reduce: 攻击技能自带方向性防御挡伤比例（v178 E6：如风暴之眼 0.8 =
        玩家防御该技能挡 80% 只受 20%）；None/缺省 = 0.5 旧行为（防御伤害减半）。
        引擎零知识：只是读技能数据字段的数字，非名词判断。
    element: 攻击技能元素标签（"fire"/"ice"/"thunder"/"dark"/"holy"…；"" = 无元素）——
        N10-B4 承伤方免疫/弱点表消费（v178 E5 数据驱动）：target.element_immune 含该
        元素 → 伤害归 0；target.element_weak[element] > 1 → 伤害 × 倍率。引擎零知识：
        元素名是数据字段值，免疫/弱点是 target 上的数据表。
    """
    if not target or amount <= 0:
        return 0
    # 等级压制（v136 双向曲线：低打高削/高打低增；PVP 不压）
    dmg = _lv_pressure(battle, source, target, amount)
    if dmg <= 0:
        return 0
    # N10-B4 元素免疫/弱点表（v178 E5 数据驱动）：target.element_immune 含元素 → 归 0；
    # element_weak[元素] > 1 → ×倍率。引擎零知识：字段/元素名全是数据。
    if element:
        try:
            _imm = target.get("element_immune") or []
            if isinstance(_imm, (list, tuple)) and element in _imm:
                logs.append(f"💠 免疫！【{target.get('name', '敌人')}】免疫{element}伤害！")
                return 0
            _wk = target.get("element_weak") or {}
            if isinstance(_wk, dict):
                _wm = float(_wk.get(element, 1.0) or 1.0)
                if _wm > 1.0:
                    dmg = max(1, int(dmg * _wm))
                    logs.append(f"⚡ 弱点！【{target.get('name', '敌人')}】弱{element}，受到额外伤害！")
        except Exception:
            pass  # 免疫/弱点异常不阻断落地
    # N9.13 数值修正钩子：taken_calc（承伤者视角减伤乘区）——装配层乘区扩展动作
    # 改 battle._fire_ctx["mult"]（沸血全减伤/death_dance 减伤等条件减伤）
    try:
        from .effect_triggers import fire as _fire
        _fctx = {"actor": target, "target": target, "source": source,
                 "dmg": dmg, "mult": 1.0}
        _fire(battle, "taken_calc", _fctx, logs)
        _m = float((getattr(battle, "_fire_ctx", {}) or {}).get("mult", 1.0) or 1.0)
        if _m != 1.0:
            dmg = max(1, int(dmg * _m))
    except Exception:
        pass  # 修正钩子异常不阻断落地
    # N7.5a 承伤乘区（vulnerable 破绽：被打更疼）——target["_dmg_taken_mult"]>1 生效
    try:
        _dtm = float(target.get("_dmg_taken_mult", 0) or 0)
        if _dtm > 1.0:
            dmg = max(1, int(dmg * _dtm))
    except Exception:
        pass
    # N10-B6 闪避（actor 承伤 roll）：dodge 面板值 cap40%，闪避成功 → 本次承伤免伤。
    # 引擎零知识：dodge 是面板数值字段；乘算合成上限与旧 _roll_dodge 对齐。
    # 位置在 defending 前（对齐旧顺序：闪避 → 防御格挡；闪避免伤不打断蓄力——招被闪开）。
    try:
        if _roll_dodge(battle, target, logs):
            return 0
    except Exception:
        pass  # 闪避异常不阻断战斗
    # defending 减伤（防御姿态；N10-B2 v178 E6 方向性防御：攻击技能自带 defend_reduce
    # 覆盖默认 0.5——如风暴之眼 0.8 = 防御挡 80% 只受 20%）
    if target.get("defending"):
        _dr = 0.5
        if isinstance(defend_reduce, (int, float)) and 0 <= float(defend_reduce) <= 0.95:
            _dr = float(defend_reduce)
        # int 截断对齐旧 landing 默认 0.5 行为（coverage 87 断言口径）
        dmg = max(1, int(dmg * (1.0 - _dr)))
        logs.append(f"(格挡后 {dmg} 点伤害)")
    # N10-B6 百分比免伤 + 格挡（actor 承伤侧，按 dmg_kind 减免；对齐旧 _damage_actor：
    # 物免/魔免按伤害类型 cap40% → block 格挡减免一半 cap40%）
    if dmg_kind and dmg > 0:
        try:
            dmg = _apply_taken_reductions(battle, target, dmg, dmg_kind, logs)
        except Exception:
            pass  # 免伤异常不阻断落地
    # 睡眠被打醒（主动伤害打醒睡眠；sleep 效果条目在 effects 容器）
    if target.get("effects", {}).get("sleep"):
        target["effects"].pop("sleep", None)
        logs.append("💥 目标被攻击惊醒！")
    # 蓄力打断（主动伤害打断读条；DOT wake_sleep=False 不打）
    if target.get("charging") and target["charging"].get("skill"):
        target["charging"] = None
        logs.append(f"🔨 {target.get('name', '目标')} 的蓄力被打破了！")
        # N5B5c P5：打断事件（on_interrupt 剧本联动：Boss 读条被断 → 反噬/破绽）
        try:
            from .effect_triggers import fire as _fire
            _fire(battle, "interrupt", {"actor": target, "target": target,
                                        "source": source}, logs)
        except Exception:
            pass
    # 承伤落地（护盾吸收 → 扣血 → 死亡）
    real = _apply_damage(battle, target, dmg, logs, source)
    # N8 事件：受击（承伤后）——主体=受击者；死者走 on_death/on_kill 不再触发。
    # 攻击方放 ctx["source"]（fire caster 缺省=受击者本体，on=caster 效果作用自己；
    # 反伤等需要攻击者的扩展动作读 _fire_ctx["source"]）
    if target.get("hp", 0) > 0:
        try:
            from .effect_triggers import fire as _fire
            _fire(battle, "on_taken", {"actor": target, "target": target,
                                       "source": source, "dmg": real}, logs)
        except Exception:
            pass  # 事件源异常不阻断落地
    return real


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


def _roll_dodge(battle, target: dict, logs: list) -> bool:
    """N10-B6：actor 承伤闪避（对齐旧 battle._roll_dodge 基础段）。

    读 S.actor_stats(target) 的 dodge 面板值（cap 40%——与旧上限一致）。
    引擎零知识：dodge 是面板数值字段，闪避是通用承伤规则。
    闪避成功返回 True（调用方中断本次承伤/免伤）。
    """
    try:
        if not target:
            return False
        from . import stats as S
        st = S.actor_stats(battle, target)
        dodge = min(float(st.get("dodge", 0) or 0), 0.40)
        if dodge <= 0:
            return False
        import random
        if random.random() < dodge:
            logs.append(f"💨 {target.get('name', '目标')} 闪避了攻击！")
            return True
    except Exception:
        pass
    return False


def _apply_taken_reductions(battle, target: dict, dmg: int, dmg_kind: str,
                            logs: list) -> int:
    """N10-B6：承伤侧百分比免伤 + 格挡（对齐旧 _damage_actor 物免/魔免段 + block 段）。

    按 dmg_kind 消费（phys 段吃物免 / magi 段吃魔免；各 cap 40%），随后 block 格挡
    概率减免一半（cap 40%）。真伤/空 kind 不减免。引擎零知识：减免率是面板数值。
    """
    try:
        from . import stats as S
        st = S.actor_stats(battle, target)
        kd = str(dmg_kind or "")
        if "phys" in kd and "true" not in kd:
            pr = min(float(st.get("phys_reduce", 0) or 0), 0.4)
            if pr > 0:
                red = max(1, int(dmg * pr))
                dmg = max(1, dmg - red)
                logs.append(f"🪨 物理免伤，减免 {red} 点物理伤害！")
        if "magi" in kd and "true" not in kd:
            mr = min(float(st.get("magic_reduce", 0) or 0), 0.4)
            if mr > 0:
                red = max(1, int(dmg * mr))
                dmg = max(1, dmg - red)
                logs.append(f"🛡️ 魔法抗性，减免 {red} 点魔法伤害！")
        if dmg > 0 and "true" not in kd:
            import random
            bc = min(float(st.get("block", 0) or 0), 0.40)
            if bc > 0 and random.random() < bc:
                red = max(1, int(dmg * 0.5))
                dmg = max(1, dmg - red)
                logs.append(f"🛡️ 格挡！减免 {red} 点伤害！")
    except Exception:
        pass
    return max(1, dmg)


def _apply_death_guard(battle, target: dict, logs: list) -> bool:
    """濒死保护（N9.12）：target.state death_guard 层 >0 且命中会致死 → 保命。

    触发后：hp 拉回 max_hp×guard_hp_pct（至少 1），额外回 max_hp×heal_pct
    （走 heal_actor——禁疗/on_heal 联动正常），层 -1。返回是否触发。
    声明参数读 state_effects（引擎不认识具体 key 语义，纯规则消费）。
    """
    try:
        ef = target.get("effects") or {}
        entry = ef.get("death_guard")
        n = int(entry.get("stacks", 0) or 0) if isinstance(entry, dict) else 0
        if n <= 0:
            return False
        from .state_effects import state_def
        cfg = state_def("death_guard") or {}
        mhp = int(target.get("max_hp", 1) or 1)
        # 层 -1（保留条目——资源耗尽后由调用方清；这里只减层）
        entry["stacks"] = max(0, n - 1)
        if entry.get("stacks", 0) <= 0 and not entry.get("expire"):
            ef.pop("death_guard", None)
        # 保底
        guard_pct = float(cfg.get("guard_hp_pct") or 0.10)
        target["hp"] = max(1, int(mhp * guard_pct))
        # 额外回血（走 heal_actor 收口——clamp max_hp / on_heal 联动）
        heal_pct = float(cfg.get("heal_pct") or 0.0)
        if heal_pct > 0 and target.get("hp", 0) < mhp:
            heal_actor(battle, target, int(mhp * heal_pct), logs)
        logs.append(f"✨ {target.get('name', '目标')} 濒死意志触发，保住了性命！")
        return True
    except Exception:
        return False


def _apply_damage(battle, target: dict, dmg: int, logs: list,
                  source: Optional[dict] = None) -> int:
    """承伤落地：护盾吸收 → hp 扣减 → 死亡判定。返回实际扣血。

    source: 攻击方（击杀事件 on_kill 用；None = DOT/环境无击杀者）
    """
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
    # 濒死保护（N9.12）：伤害会致死时查 target.state death_guard 层（声明表参数）
    # → 保底不死亡 + 回血 + 层-1。规则通用（引擎零名词——声明表 guard_hp_pct/heal_pct）
    if new <= 0:
        _guarded = _apply_death_guard(battle, target, logs)
        if _guarded:
            new = int(target.get("hp", 0) or 0)
            _real = old - new
    if new <= 0:
        logs.append(f"💥 {target.get('name', '目标')} 受到 {_real} 点伤害，倒下了！")
        if hasattr(battle, "_on_actor_dead"):
            battle._on_actor_dead(target, logs)
        # N8 事件：击杀（主体=击杀者；DOT/环境杀无 on_kill）
        if source is not None:
            try:
                from .effect_triggers import fire as _fire
                _fire(battle, "on_kill", {"actor": source,
                                          "target": target, "dmg": _real}, logs)
            except Exception:
                pass  # 事件源异常不阻断落地
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
    # N8 事件：治疗生效（主体=被治疗者；实际回血 >0；治疗者放 source；
    # overflow = 计划治疗超出 max_hp 的浪费量——溢出转盾类效果消费）
    if _real > 0:
        _overflow = max(0, heal - _real)
        try:
            from .effect_triggers import fire as _fire
            _fire(battle, "on_heal", {"actor": target, "target": target,
                                      "source": source, "amount": _real,
                                      "overflow": _overflow}, logs)
        except Exception:
            pass  # 事件源异常不阻断落地
    return _real


def _apply_heal_mods(target: dict, amount: int, logs: list) -> int:
    """受疗/禁疗修正（target 自身效果）。返回修正后治疗量（未 clamp）。"""
    heal = amount
    try:
        ef = target.get("effects") or {}
        # 受疗增幅（heal_amp_pct：装配层把 proc_heal amp 装备折算进 effects 条目 stacks/value）
        amp_entry = ef.get("heal_amp_pct")
        if isinstance(amp_entry, dict):
            # 两种形态：stacks 计数（装配层旧写法）/ value.amp 数值
            amp_pct = float(amp_entry.get("value", {}).get("amp", 0) or 0) \
                if isinstance(amp_entry.get("value"), dict) \
                else float(amp_entry.get("stacks", 0) or 0)
            if amp_pct > 0:
                heal = int(round(heal * (1 + min(amp_pct, 1.0))))
        # 禁疗（heal_down 层×10% cap50%——effects 条目 stacks；声明表 cap）
        hd_entry = ef.get("heal_down")
        if isinstance(hd_entry, dict):
            ehd = int(hd_entry.get("stacks", 0) or 0)
            if ehd > 0:
                cut = min(ehd * 0.10, 0.50)
                heal = max(0, int(heal * (1 - cut)))
                logs.append(f"🩸 禁疗：治疗量 -{int(cut * 100)}%！")
        # 重伤（_anti_heal_pct cap80%；effects 条目 value 内嵌）
        ah_entry = ef.get("_anti_heal_pct")
        if isinstance(ah_entry, dict):
            aheal = float((ah_entry.get("value") or {}).get("pct", 0) or 0)
            if aheal > 0:
                cut2 = min(aheal, 0.80)
                heal = max(0, int(heal * (1 - cut2)))
                logs.append(f"🩸 重伤：治疗量 -{int(cut2 * 100)}%！")
    except Exception:
        pass
    return max(0, heal)
