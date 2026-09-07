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
    """
    effects = []
    # mech → 对敌效果（命中后附加）
    mech = info.get("mech") or ""
    mval = int(info.get("mech_val", 0) or 0)
    if mech and mval:
        effects.append({"type": mech, "stacks": mval,
                        "turns": int(info.get("cc_turns", 0) or 0),
                        "mech": mech, "info": info})
    # mech2（第二 mech）
    mech2 = info.get("mech2") or ""
    if mech2:
        m2v = int(info.get("mech2_val", 0) or 0)
        effects.append({"type": mech2, "stacks": m2v,
                        "turns": int(info.get("cc_turns", 0) or 0),
                        "mech": mech2, "info": info})
    return effects


def _cc_turns_of(info: dict, lv: int) -> int:
    """控制/减益持续刻数（cc 字段优先，缺省按技能等级成长）。"""
    cc = info.get("cc") or {}
    if isinstance(cc, dict):
        t = int(cc.get("turns", 0) or 0)
        if t > 0:
            return t
    return int(info.get("cc_turns", 0) or 0) or max(1, min(lv, 3))


# ============================================================
# 对敌 debuff 叠层类（写 target.debuffs）
# ============================================================

@register_effect("burn")
def eff_burn(battle, caster, target, params, logs):
    """灼烧：叠层（每层每刻掉 3% 生命，cap 5 层）。写 target.debuffs["burn"]={n, mult}。"""
    if not target:
        return
    if "burn" in (target.get("immune_dots") or []):
        logs.append("🛡️ 敌人免疫灼烧！")
        return
    stacks = int(params.get("stacks", 0) or 0)
    if stacks <= 0:
        return
    deb = target.setdefault("debuffs", {})
    cur = deb.get("burn") or {"n": 0, "mult": 1.0}
    cur["mult"] = float(cur.get("mult", 1.0) or 1.0)
    cur["n"] = min(5, int(cur.get("n", 0) or 0) + stacks)
    deb["burn"] = cur
    logs.append(f"🔥 灼烧层数 {cur['n']}(每刻 {cur['n'] * 3}% 生命)")


@register_effect("bleed")
def eff_bleed(battle, caster, target, params, logs):
    """流血：叠层（每层每刻固定伤害，cap 按数据）。写 target.debuffs["bleed"]。"""
    if not target:
        return
    stacks = int(params.get("stacks", 0) or 0)
    if stacks <= 0:
        return
    deb = target.setdefault("debuffs", {})
    cur = deb.get("bleed") or {"n": 0, "mult": 1.0}
    cur["n"] = min(10, int(cur.get("n", 0) or 0) + stacks)
    deb["bleed"] = cur
    logs.append(f"🩸 流血层数 {cur['n']}")


@register_effect("poison")
def eff_poison(battle, caster, target, params, logs):
    """中毒：叠层（每层每刻伤害）。写 target.debuffs["poison"]={n, mult}。"""
    if not target:
        return
    if "poison" in (target.get("immune_dots") or []):
        logs.append("🛡️ 敌人免疫中毒！")
        return
    stacks = int(params.get("stacks", 0) or 0)
    if stacks <= 0:
        return
    deb = target.setdefault("debuffs", {})
    cur = deb.get("poison") or {"n": 0, "mult": 1.0}
    cur["n"] = min(5, int(cur.get("n", 0) or 0) + stacks)
    deb["poison"] = cur
    logs.append(f"☠️ 中毒层数 {cur['n']}")


@register_effect("hunt_mark")
def eff_hunt_mark(battle, caster, target, params, logs):
    """猎印：叠层（目标易伤，每层 +8% 承伤，cap 默认 3）。"""
    if not target:
        return
    stacks = int(params.get("stacks", 0) or 0)
    if stacks <= 0:
        return
    deb = target.setdefault("debuffs", {})
    deb["hunt_mark"] = min(3, int(deb.get("hunt_mark", 0) or 0) + stacks)
    logs.append(f"🎯 猎印 {deb['hunt_mark']} 层（承伤 +{8 * deb['hunt_mark']}%）")


@register_effect("soul_mark")
def eff_soul_mark(battle, caster, target, params, logs):
    """魂标：叠层（每层 +6% 承伤，cap 默认 3）。"""
    if not target:
        return
    stacks = int(params.get("stacks", 0) or 0)
    if stacks <= 0:
        return
    deb = target.setdefault("debuffs", {})
    deb["soul_mark"] = min(3, int(deb.get("soul_mark", 0) or 0) + stacks)
    logs.append(f"💀 魂标 {deb['soul_mark']} 层（承伤 +{6 * deb['soul_mark']}%）")


# 元素印记（fire_mark/ice_mark/thunder_mark）→ debuffs 标记（元素反应 N3b 用）
for _mk_key, _mk_name, _mk_mult in (("fire_mark", "火印", 0.15),
                                    ("ice_mark", "冰印", 0.15),
                                    ("thunder_mark", "雷印", 0.15)):
    def _mk_handler(battle, caster, target, params, logs, _k=_mk_key, _n=_mk_name, _m=_mk_mult):
        if not target:
            return
        stacks = int(params.get("stacks", 0) or 0)
        if stacks <= 0:
            return
        deb = target.setdefault("debuffs", {})
        deb[_k] = min(5, int(deb.get(_k, 0) or 0) + stacks)
        logs.append(f"🪷 {_n} {deb[_k]} 层")
    EFFECT_HANDLERS[_mk_key] = _mk_handler


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
# 叠层类（写 caster.stacks / caster.resources）
# ============================================================

def _stack_gain(actor: dict, key: str, amount: int, cap: int) -> int:
    """叠层（写 actor.stacks[key]，封顶）。返回叠后层数。"""
    stacks = actor.setdefault("stacks", {})
    cur = int(stacks.get(key, 0) or 0)
    stacks[key] = min(cap, cur + amount)
    return stacks[key]


@register_effect("zhan_yi")
def eff_zhan_yi(battle, caster, target, params, logs):
    """战意：叠层（0-10，每层 +4% 攻击，持有即生效）。写 caster.stacks["zhan_yi"]。"""
    if not caster:
        return
    amount = int(params.get("stacks", 0) or 0)
    if amount <= 0:
        return
    n = _stack_gain(caster, "zhan_yi", amount, 10)
    logs.append(f"⚔️ 战意 {n}(每层攻击＋4%，满 10 进入狂暴)")


@register_effect("zhan_yi_cash")
def eff_zhan_yi_cash(battle, caster, target, params, logs):
    """战意消耗：花 N 层战意换效果（写 caster.stacks["zhan_yi"] 扣减）。"""
    if not caster:
        return
    amount = int(params.get("stacks", 0) or 0)
    if amount <= 0:
        return
    stacks = caster.setdefault("stacks", {})
    cur = int(stacks.get("zhan_yi", 0) or 0)
    stacks["zhan_yi"] = max(0, cur - amount)
    logs.append(f"⚔️ 消耗 {amount} 层战意（剩余 {stacks['zhan_yi']}）")


@register_effect("lian_duan")
def eff_lian_duan(battle, caster, target, params, logs):
    """连段：叠层（计数型，断连归零）。写 caster.stacks["lian_duan"]。"""
    if not caster:
        return
    amount = int(params.get("stacks", 0) or 0)
    if amount <= 0:
        return
    n = _stack_gain(caster, "lian_duan", amount, 10)
    logs.append(f"🔗 连段 {n}(计数型，断连归零)")


@register_effect("rage")
def eff_rage(battle, caster, target, params, logs):
    """怒气：叠层（战士通用资源，rage 0-10）。写 caster.resources["rage"]。"""
    if not caster:
        return
    amount = int(params.get("stacks", 0) or 0)
    if amount <= 0:
        return
    res = caster.setdefault("resources", {})
    cur = int(res.get("rage", 0) or 0)
    res["rage"] = min(10, cur + amount)
    logs.append(f"🔥 怒气 +{amount}（当前 {res['rage']}）")


@register_effect("chi")
def eff_chi(battle, caster, target, params, logs):
    """气：叠层（拳师资源）。写 caster.resources["chi"]。"""
    if not caster:
        return
    amount = int(params.get("stacks", 0) or 0)
    if amount <= 0:
        return
    res = caster.setdefault("resources", {})
    cur = int(res.get("chi", 0) or 0)
    res["chi"] = min(10, cur + amount)
    logs.append(f"🥋 气 +{amount}（当前 {res['chi']}）")


@register_effect("arcane")
def eff_arcane(battle, caster, target, params, logs):
    """奥术充能：叠层（法师资源）。写 caster.resources["arcane"]。"""
    if not caster:
        return
    amount = int(params.get("stacks", 0) or 0)
    if amount <= 0:
        return
    res = caster.setdefault("resources", {})
    cur = int(res.get("arcane", 0) or 0)
    res["arcane"] = min(10, cur + amount)
    logs.append(f"🔮 奥术充能 +{amount}（当前 {res['arcane']}）")


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
    """净化：移除 caster 自身一个减益（对敌 debuffs 读 target）。"""
    actor = target or caster
    if not actor:
        return
    rem = []
    deb = actor.setdefault("debuffs", {})
    for k in ("burn", "bleed", "poison", "spd_down", "stun", "silence", "freeze"):
        if k in deb:
            rem.append(k)
            deb.pop(k, None)
    for k in ("stun", "silence", "freeze", "spd_down", "reduce"):
        actor.setdefault("buffs", {}).pop(k, None)
    if rem:
        logs.append(f"✨ 净化了 {'、'.join(rem)}！")
    else:
        logs.append("✨ 净化（无减益可解）")


@register_effect("cleanse_all")
def eff_cleanse_all(battle, caster, target, params, logs):
    """全体净化：移除施法者自身全部减益（副本广播在命令层）。"""
    eff_cleanse(battle, caster, target or caster, params, logs)
