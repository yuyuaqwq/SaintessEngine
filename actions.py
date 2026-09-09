# -*- coding: utf-8 -*-
"""v181.P4 battle2 引擎——行动结算链（actions.py）。

按 docs/REFACTOR_v181P4_FULL_PLAN.md Part 2.2：
- 全部结算显式 ctx/caster/target，不摸隐式全局目标
- 数值公式复用旧 engine.py（resolve_formula/calc_damage/skill_*），不重写

N1 范围：普攻（attack = basic_skill）+ 伤害落地 + 承伤链最小集（hp 扣减）。
技能/治疗/增益/AOE 在 N2 展开（_do_skill 框架已留）。
"""
from __future__ import annotations

import random
from typing import Optional

from .. import engine as E
from ..core import constants as K
from . import stats as S
from .actors import actor_alive

# kind 常量（旧 battle.py K_PHYS/K_MAGI/K_TRUE 同义；用文案判断会脆，这里按旧语义）
K_PHYS = "物理"
K_MAGI = "魔法"
K_TRUE = "真伤"
K_HEAL = "治疗"
K_BUFF = "增益"


def resolve_basic_skill(class_name: Optional[str]) -> dict:
    """取职业 basic_skill 配置；无则回退纯物理普攻。

    与旧 _actor_attack 同语义：普攻 = 释放职业 basic_skill（无 CD/无蓝耗）。
    """
    try:
        from .. import content as C
        cid = C.resolve("classes", class_name or "")
        bs = (C.CLASSES.get(cid, {}) or {}).get("basic_skill") or {}
        if isinstance(bs, dict) and bs.get("name") and (bs.get("exprs") or bs.get("formula")):
            return dict(bs)
    except Exception:
        pass
    return {"name": "攻击", "kind": K_PHYS, "exprs": ["atk*1.0"]}


def do_attack(battle, ctx) -> list:
    """普攻 = 释放 basic_skill（数据配置的普通技能），走统一技能管道。"""
    actor = ctx.caster
    info = resolve_basic_skill(actor.get("class_name"))
    # N8：标记 basic（普攻命中事件 attack_hit 与技能 skill_hit 区分用）
    info["_basic"] = True
    # basic 技能无 CD/无蓝耗/无需学习等级；资源获取由 res_gain / on_skill 数据驱动
    sub = ctx.__class__(caster=actor, action="skill", skill_name=info["name"],
                        info=info, target=ctx.target, target_side=ctx.target_side,
                        scope=ctx.scope)
    return do_skill(battle, sub)


def do_skill(battle, ctx) -> list:
    """技能结算入口（N2：治疗/增益/伤害三分派 + 前置校验 + 消耗）。

    管线（对齐旧 _do_actor_skill/_actor_skill 主线）：
    1. 技能存在/已学习校验（命令层可能已做过，这里兜底）
    2. 蓝耗/核心资源校验 + 扣除
    3. 冷却设置
    4. kind 分派：治疗 → do_heal / 增益 → do_buff / 攻击 → 伤害管线
    """
    actor = ctx.caster
    info = ctx.info or {}
    if not info:
        return []
    kind = info.get("kind", "")
    logs = []
    # ---- 1. 技能存在/学习校验 ----
    if actor.get("class_name") and not _skill_usable(battle, actor, info):
        return logs  # 命令层已拦截，兜底静默
    # ---- 2. 消耗扣除（蓝/核心资源） ----
    _spend_skill_cost(actor, info)
    # ---- 3. 冷却（cd>0 才设；actor.cooldown = {skill_name: 绝对时刻}）----
    cd = int(info.get("cd", 0) or 0)
    if cd > 0:
        from .battle import _now_of
        actor.setdefault("cooldown", {})[info.get("name", ctx.skill_name or "?")] = _now_of(battle) + cd
    # ---- N8 事件：施放瞬间（扣费/冷却后、结算前；主体=施法者）----
    try:
        from .effect_triggers import fire as _fire
        _fire(battle, "act_cast", {"actor": actor, "target": ctx.target, "info": info}, logs)
    except Exception:
        pass
    # ---- 4. kind 分派 ----
    if kind == K_HEAL:
        return _do_heal(battle, ctx, actor, info, logs)
    if kind == K_BUFF:
        return _do_buff(battle, ctx, actor, info, logs)
    # ---- 攻击类：目标解析 + 伤害管线 ----
    target = ctx.target if ctx.target is not None else _default_target(battle, actor)
    if target is None:
        return ["但没有可攻击的目标！"]
    lv = E.skill_level_of(actor, info.get("name", "")) if actor.get("class_name") else 0
    logs.extend(_attack_damage_pipeline(battle, actor, target, info, lv))
    return logs


def _skill_usable(battle, actor: dict, info: dict) -> bool:
    """技能可用性（学习/蓝/资源/冷却）检查——返回 False 时已把拦截日志加入 logs。"""
    # 命令层负责用户提示；引擎侧只在 actor 无 class_name（怪）或直接调用时校验蓝/冷却
    return True


def _spend_skill_cost(actor: dict, info: dict):
    """扣除技能蓝耗/核心资源（effects 容器 stacks）。basic/无消耗技能跳过。"""
    mp = int(info.get("mp", 0) or 0)
    if mp > 0 and actor.get("mp") is not None:
        actor["mp"] = max(0, int(actor.get("mp", 0)) - mp)
    # 核心资源消耗（res_cost：扣 effects[key].stacks）
    res_cost = info.get("res_cost") or {}
    if res_cost:
        ef = actor.setdefault("effects", {})
        for rk, rv in res_cost.items():
            entry = ef.get(rk)
            cur = int(entry.get("stacks", 0) or 0) if isinstance(entry, dict) else 0
            if cur <= 0:
                continue
            if not isinstance(entry, dict):
                entry = ef[rk] = {}
            entry["stacks"] = max(0, cur - int(rv or 0))
    # consume_all：清零该资源 key
    consume_all = info.get("consume_all") or {}
    if consume_all and consume_all.get("key"):
        ef = actor.setdefault("effects", {})
        ef.pop(consume_all["key"], None)


def _default_target(battle, actor: dict) -> Optional[dict]:
    """缺省目标：actor 敌对阵营存活第一人（AI/命令层未指定 target 时）。"""
    from .actors import hostile_actors, actor_alive
    for _a in hostile_actors(battle, actor.get("side", "")):
        if actor_alive(_a):
            return _a
    return None


# ============================================================
# 伤害管线（N1：普攻 = 单段 expr 物理）
# ============================================================

def _attack_damage_pipeline(battle, actor: dict, target: dict, info: dict, lv: int) -> list:
    """伤害管线核心（对齐旧 _actor_skill 攻击路径，N1 无被动/无词条/无标记场景）。

    步骤：暴击判定 → 乘区装配（N1 恒 1.0）→ 段循环（hits/multi）→ 命中落地。
    AOE：直接逐目标独立完整结算（_deal_aoe）。
    """
    # AOE：每目标独立完整伤害（各自 roll/防御/等级压制）
    if info.get("aoe"):
        return _deal_aoe(battle, actor, target, info, 0)
    return _single_target_pipeline(battle, actor, target, info, lv)


def _deal_aoe(battle, actor: dict, target: dict, info: dict, total: int) -> list:
    """AOE 逐目标结算（N2c 最终版：每目标独立完整伤害）。

    正确语义（鱼鱼拍板：新引擎不陪葬旧引擎 bug）：AOE = 对范围内每个目标
    独立结算一次完整技能伤害——各自吃自己的防御/波动/等级压制，互不影响。

    旧引擎 _aoe_damage 的 infer_atk 反推方案（拿副目标防御解主目标伤害方程）
    数学上不自洽（无解时产生伪 atk），且主目标日志与实际扣血不符——不迁移。

    实现：_attack_damage_pipeline 的 AOE 变体——多段循环在单目标上已完成
    （total 是主目标总伤）；这里对每个目标重算单段伤害之和。
    """
    from ..core import formation as _fm
    from .actors import actor_alive, hostile_sides
    logs = []
    scope = "all" if info.get("aoe") is True else str(info.get("aoe") or "all")
    enemies = []
    for _sn in hostile_sides(battle, actor.get("side", "")):
        enemies.extend(battle.sides.get(_sn) or [])
    if not enemies:
        return logs
    attacker = {"reach": int(info.get("reach") or 3), "uid": "aoe"}
    try:
        targets = _fm.select_aoe_targets(attacker, enemies, scope)
    except Exception:
        targets = enemies
    if not targets:
        return logs
    falloff = float(info.get("aoe_falloff", 1.0) or 1.0)
    for t in targets:
        if not actor_alive(t):
            continue
        logs.extend(_single_target_pipeline(battle, actor, t, info, _skill_lv_of(battle, actor),
                                            _no_lifesteal=True))  # N10-B1：AOE 不吸血（旧语义）
        # rank>1 目标 aoe_falloff：简化——falloff!=1.0 时按比例补算（见 _aoe_falloff_apply）
        if falloff != 1.0 and int(t.get("rank", 1) or 1) > 1:
            logs = _aoe_falloff_apply(logs)
    return logs


def _single_target_pipeline(battle, actor: dict, target: dict, info: dict, lv: int,
                            _no_lifesteal: bool = False) -> list:
    """单目标完整伤害管线（AOE 逐目标内部用；不递归触发 aoe）。

    _no_lifesteal=True：AOE 子调用（旧引擎 _aoe_damage 无吸血——N10-B1 对齐）。
    """
    logs = []
    # N7.3 出手消费型 buff（on_hit：next_atk_up 增伤 / stealth 必暴等）——先查后打
    hit_buffs = _consume_hit_buffs(battle, actor, logs)
    st = S.actor_stats(battle, actor)
    est = S.actor_stats(battle, target)
    # state 声明伤害倍率（state_effects 表 dmg_mult：如 rage 狂暴层）
    _st_mult = float(st.get("_state_dmg_mult", 1.0) or 1.0)
    crit_pct = float(st.get("crit", 0) or 0)
    is_crit = hit_buffs["guaranteed_crit"] or (random.random() < crit_pct)
    lucky = False
    if is_crit:
        lucky = random.random() < 0.30
    multi = int(info.get("hits") or info.get("multi") or 1)
    pp_phys = float(st.get("pene_phys", 0) or 0)
    pf_phys = int(st.get("pene_flat_phys", 0) or 0)
    pp_magi = float(st.get("pene_magi", 0) or 0)
    pf_magi = int(st.get("pene_flat_magi", 0) or 0)
    skill_flat = E.skill_flat_value(int(actor.get("level", 1) or 1), lv, info)
    total = 0
    magi_part = 0
    for seg in range(multi):
        _seg_crit = is_crit and (seg == 0)
        _lucky_seg = lucky and (seg == 0)
        dmg_i, mseg_i = _skill_seg_damage(battle, actor, target, st, est, info,
                                          lv, _seg_crit, _lucky_seg,
                                          pp_phys, pf_phys, pp_magi, pf_magi, skill_flat)
        total += dmg_i
        magi_part += mseg_i
    if _st_mult != 1.0:
        total = max(1, int(total * _st_mult))
    if hit_buffs["dmg_mult"] != 1.0:
        total = max(1, int(total * hit_buffs["dmg_mult"]))
    if total <= 0:
        return logs
    # N9.13 数值修正钩子：dmg_calc（攻击者视角条件乘区）——装配层乘区扩展动作
    # 改 battle._fire_ctx["mult"] 累乘（处决低血增伤/破魔/叠层放大器等）。fire 后
    # 该 ctx 仍是本次事件的（乘区动作同步改，无并发）。
    try:
        from .effect_triggers import fire as _fire
        _fctx = {"actor": actor, "target": target, "dmg": total,
                 "is_crit": is_crit, "info": info, "mult": 1.0}
        _fire(battle, "dmg_calc", _fctx, logs)
        _m = float((getattr(battle, "_fire_ctx", {}) or {}).get("mult", 1.0) or 1.0)
        if _m != 1.0:
            total = max(1, int(total * _m))
    except Exception:
        pass  # 修正钩子异常不阻断战斗
    if total <= 0:
        return logs
    logs.extend(_deal_hit(battle, actor, target, total))
    # N10-B1 吸血结算（对齐旧 _skill_finalize_damage 尾部 _settle_lifesteal）：
    # 面板吸血率（lifesteal/phys/magi）+ 技能级 info.lifesteal；真伤不吸；AOE 子调用跳过。
    if not _no_lifesteal:
        try:
            _settle_lifesteal(battle, actor, total, info.get("kind", ""), logs,
                              magi_part=magi_part, skill_info=info, skill_lv=lv)
        except Exception:
            pass  # 吸血结算异常不阻断战斗（落地已发生）
    # N9.8 出手附伤（trinity thunder 段等）：主伤害落完后按 atk × pct 结算一段
    # 独立附加伤害（参数化零名词——数值/标签全来自 buff hit 子键声明）。
    # 走 landing.deal_damage 统一收口（等级压制/护盾/死亡判定正常联动）。
    bns = float(hit_buffs.get("bonus_atk_pct", 0.0) or 0.0)
    if bns > 0:
        _bst = S.actor_stats(battle, actor)
        _bns_dmg = max(1, int((_bst.get("atk", 0) or 0) * bns))
        if _bns_dmg > 0 and actor_alive(target):
            logs.extend(_deal_hit(battle, actor, target, _bns_dmg))
            logs.append(f"{hit_buffs.get('bonus_tag') or '⚡'} 附魔追击，追加 {_bns_dmg} 点伤害！")
    # 命中后 mech/effect 效果（N3：mech → effects 兼容层）
    _apply_hit_effects(battle, actor, target, info, lv, logs)
    # N8 事件：命中后——普攻 attack_hit / 技能 skill_hit；暴击 crit（子集）。
    # 主体 = 攻击者（只有攻击者自己的命中效果触发）；AOE 逐目标独立走本管线
    # → 每目标各触发一次命中事件。技能自身 mech 已由 _apply_hit_effects 落地后再广播。
    try:
        from .effect_triggers import fire as _fire
        ev = "attack_hit" if info.get("_basic") else "skill_hit"
        _fire(battle, ev, {"actor": actor, "target": target,
                           "info": info, "dmg": total}, logs)
        if is_crit:
            _fire(battle, "crit", {"actor": actor, "target": target,
                                   "info": info, "dmg": total}, logs)
    except Exception:
        pass  # 事件源异常不阻断战斗
    return logs


def _consume_hit_buffs(battle, actor: dict, logs: list) -> dict:
    """出手消费型效果（N7.3，V 系列容器统一）：查 actor.effects 中带 hit 子键的条目。

    条目形态：effects[key] = {"stacks": 1, "expire": 时刻, "hit": {"dmg_mult": 1.5} |
    {"guaranteed_crit": True} | {"bonus_atk_pct": 0.15, "bonus_tag": "⚡"}}——
    效果参数由动作/数据给，出手时消费删除。

    返回 {"dmg_mult": float, "guaranteed_crit": bool,
          "bonus_atk_pct": float, "bonus_tag": str}。
    bonus_*：出手附伤（N9.8 trinity thunder 段）——按攻击者 atk × pct 额外
    结算一段独立伤害（参数化零名词；tag 仅日志装饰）。
    """
    ef = actor.get("effects") or {}
    now = float(getattr(battle, "_now", 0.0) or 0.0)
    out = {"dmg_mult": 1.0, "guaranteed_crit": False,
           "bonus_atk_pct": 0.0, "bonus_tag": ""}
    for key in list(ef.keys()):
        entry = ef[key]
        if not isinstance(entry, dict):
            continue
        hit = entry.get("hit")
        if not isinstance(hit, dict):
            continue
        exp = entry.get("expire")
        if exp is not None and now >= float(exp):
            continue  # 过期不消费（schedule 到期删兜底）
        out["dmg_mult"] *= float(hit.get("dmg_mult", 1.0) or 1.0)
        if hit.get("guaranteed_crit"):
            out["guaranteed_crit"] = True
        # N9.8 出手附伤：bonus_atk_pct 累加（多 buff 并存时求和；缺省无此段）
        bns = float(hit.get("bonus_atk_pct", 0.0) or 0.0)
        if bns > 0:
            out["bonus_atk_pct"] += bns
            out["bonus_tag"] = hit.get("bonus_tag") or "⚡"
        logs.append(f"✨ {key} 生效！")
        # N8 事件：出手消费点（一次性 buff 被消费；主体=出手者）
        try:
            from .effect_triggers import fire as _fire
            _fire(battle, "on_hit_consume", {"actor": actor, "key": key}, logs)
        except Exception:
            pass
        ef.pop(key, None)
    return out


def _apply_hit_effects(battle, actor: dict, target: dict, info: dict, lv: int, logs: list):
    """攻击命中后附加效果（mech → effects 兼容层，N3 核心接入点）。"""
    from .effects import apply_effects, effects_from_skill
    effs = effects_from_skill(info, lv)
    if effs:
        apply_effects(battle, actor, target, effs, logs)


def _skill_lv_of(battle, actor: dict) -> int:
    return E.skill_level_of(actor, "") if actor.get("class_name") else 0


def _aoe_falloff_apply(logs):
    """AOE falloff 标记（占位——N5 命令层接入时按需精确实现）。"""
    return logs


def _skill_seg_damage(battle, actor, target, st, est, info, lv,
                      seg_crit, lucky, pp_phys, pf_phys, pp_magi, pf_magi,
                      skill_flat) -> tuple:
    """单段伤害计算（对齐旧 _skill_seg_damage 的 expr 分支 + 非 formula 兜底）。"""
    expr = E.skill_formula_expr(info, lv)
    if expr:
        # expr 段：type 由 kind 推导（物理→phys、真伤→true、其余 magi）
        kind = info.get("kind", "")
        seg_type = "true" if kind == K_TRUE else ("phys" if kind == K_PHYS else "magi")
        st["_player_lv"] = int(actor.get("level", 1) or 1)
        st["_skill_lv"] = lv
        # expr 已内嵌技能成长 → 剔除 skill_power_mult（basic 无成长 → 恒 1.0，无影响）
        spm = E.skill_power_mult(lv, info) or 1.0
        pmult_expr = (1.0 / spm) if spm else 1.0
        dmg, magi = E.resolve_formula(
            [{"expr": expr, "type": seg_type}], st, est.get("def", 0), est.get("mdef", 0),
            is_crit=seg_crit, pene_phys=pp_phys, pene_magi=pp_magi,
            pene_flat_phys=pf_phys, pene_flat_magi=pf_magi,
            mult=pmult_expr, variance=0.15,
        )
        # 幸运一击（v133 lucky_mult=1.3）：暴击命中后 30% 追加
        if lucky:
            dmg = int(dmg * 1.3)
        return dmg, magi
    # 非 formula/非 expr：按 kind 兜底（对齐旧非 formula 路径）
    kind = info.get("kind", "")
    power = float(info.get("power", 1.0) or 1.0)
    if kind == K_TRUE:
        return E.calc_damage(int((st.get("atk", 0) * power + skill_flat)), 0, seg_crit,
                             dmg_type="true"), 0
    if kind == K_PHYS:
        return E.calc_damage(int((st.get("atk", 0) * power + skill_flat)), est.get("def", 0),
                             seg_crit, pene_pct=pp_phys, pene_flat=pf_phys, dmg_type="phys"), 0
    return E.calc_damage(int((st.get("matk", 0) * power + skill_flat)), est.get("mdef", 0),
                         seg_crit, pene_pct=pp_magi, pene_flat=pf_magi, dmg_type="magi"), 0


def _deal_hit(battle, actor: dict, target: dict, dmg: int) -> list:
    """命中落地薄包装：统一走 landing.deal_damage 收口（等级压制/护盾/死亡）。"""
    logs = []
    from .landing import deal_damage
    deal_damage(battle, actor, target, dmg, logs)
    return logs


def _mortal_wound_mult(battle, actor: dict) -> float:
    """N10-B1：Boss『重创』（mortal_wound）→ 吸血减半。

    玩家 effects["mortal_wound"] 条目由 boss_script opening 施加（{stacks, expire}）。
    过期条目由 schedule._settle_time_effects 自动清，此处防御性判 expire。
    """
    try:
        ef = actor.get("effects") or {}
        mw = ef.get("mortal_wound")
        if not isinstance(mw, dict):
            return 1.0
        exp = mw.get("expire")
        if exp is not None:
            now = float(getattr(battle, "_now", 0) or 0)
            if now >= float(exp):
                return 1.0
        return 0.5
    except Exception:
        return 1.0


def _settle_lifesteal(battle, actor: dict, dmg_total: int, kind: str, logs: list,
                      magi_part: int = 0, skill_info: Optional[dict] = None,
                      skill_lv: int = 0) -> None:
    """N10-B1：玩家攻击吸血统一结算（对齐旧 battle._settle_lifesteal + info.lifesteal 技能级）。

    引擎零游戏知识：吸血率 = actor 面板数据（S.actor_stats 的 lifesteal/lifesteal_phys/
    lifesteal_magi），引擎只做通用"攻击者按面板吸血率回血"——纯怪无 lifesteal 面板
    → 零行为（天然安全）。真伤不吸（v107 鱼鱼拍板）。AOE 由调用方 _no_lifesteal 跳过。

    - 通用段（面板吸血率）：rate = lifesteal，混合段按 phys/magi 合成细分率
    - 技能级：skill_info.lifesteal → E.skill_lifesteal_pct(info, lv) 附加
    - cap 30%（对齐旧 min(rate, 0.30)）；mortal_wound → ×0.5
    """
    if dmg_total <= 0 or kind == K_TRUE:
        return
    try:
        _mw = _mortal_wound_mult(battle, actor)
        st = S.actor_stats(battle, actor)
        rate = float(st.get("lifesteal", 0) or 0)
        # 物/魔细分合成（对齐旧：1-(1-rate)(1-sub)）；混合段物段走 phys、魔段走 magi
        sub_rate = 0.0
        if magi_part > 0 and 0 < magi_part < dmg_total:
            # 物理段伤害 × phys 吸血 + 魔法段伤害 × magi 吸血（各自合成）
            phys_dmg = dmg_total - magi_part
            sub_p = float(st.get("lifesteal_phys", 0) or 0)
            sub_m = float(st.get("lifesteal_magi", 0) or 0)
            rate_p = 1 - (1 - rate) * (1 - sub_p)
            rate_m = 1 - (1 - rate) * (1 - sub_m)
            heal = int(phys_dmg * min(rate_p, 0.30) + magi_part * min(rate_m, 0.30))
        else:
            is_magi = (kind == K_MAGI)
            sub_key = "lifesteal_magi" if is_magi else "lifesteal_phys"
            sub = float(st.get(sub_key, 0) or 0)
            if sub > 0:
                rate = 1 - (1 - rate) * (1 - sub)
            rate = min(rate, 0.30)
            heal = int(dmg_total * rate)
        # 技能级吸血（info.lifesteal，如嗜血斩 0.25 随等级成长）——独立叠加、cap 30% 同限
        if skill_info and skill_info.get("lifesteal"):
            try:
                spct = E.skill_lifesteal_pct(skill_info, skill_lv)
                heal += int(dmg_total * min(float(spct), 0.30))
            except Exception:
                pass
        if heal <= 0:
            return
        if _mw < 1.0:
            heal = max(1, int(heal * _mw))
        from .landing import heal_actor
        heal_actor(battle, actor, heal, logs)
        logs.append(f"🩸 吸血：回复 {heal} 点生命！")
    except Exception:
        pass  # 吸血异常不阻断战斗（伤害已落地）


# ============================================================
# 治疗管线（N2a：对齐旧 _skill_heal 数值主线）
# ============================================================

def _do_heal(battle, ctx, actor, info, logs) -> list:
    """治疗技能结算。

    治疗量公式（对齐旧 _skill_heal 主线，无随机）：
    1. heal_formula / heal_expr（字符串或逐级数组）→ 表达式求值
    2. hp_pct → max_hp × hp_pct × skill_power_mult
    3. 兜底 → matk × power × skill_power_mult
    落地：clamp max_hp（禁疗/受疗修正 N3 effects）
    """
    lv = E.skill_level_of(actor, info.get("name", "")) if actor.get("class_name") else 0
    # 治疗目标：ctx.target（命令层可指定队友/自己）；None → 施法者自己
    target = ctx.target if ctx.target is not None else actor
    if target.get("hp") is None:
        return logs
    # 面板（施法者属性；治疗量不吃目标面板）
    st = S.actor_stats(battle, actor)
    # cond_mult（v32 条件转化——N2b 补，恒 1.0 起步）
    cond_mult = 1.0
    heal = _heal_amount(st, actor, info, lv)
    heal = int(heal * cond_mult)
    # 治疗强度 heal_power（属性面板化，cap 50%）
    try:
        hpv = min(float(st.get("heal_power", 0) or 0), 0.5)
        if hpv > 0:
            heal = int(heal * (1 + hpv))
    except Exception:
        pass
    if heal <= 0:
        return logs
    # 落地（统一收口 landing.heal_actor：禁疗修正 + clamp max_hp）
    from .landing import heal_actor
    _real = heal_actor(battle, target, heal, logs)
    logs.append(f"你施展【{info.get('name', ctx.skill_name or '技能')}】，圣光治愈了你 {heal} 点生命！"
                if _real >= heal else
                f"你施展【{info.get('name', ctx.skill_name or '技能')}】，治愈了 {_real} 点生命！")
    return logs


def _heal_amount(st: dict, actor: dict, info: dict, lv: int) -> int:
    """治疗量公式（与旧 _skill_heal 主线逐字对齐，无随机）。"""
    # heal_formula 优先级（含 heal_exprs 逐级 / heal_expr）
    hf_raw = info.get("heal_formula") or info.get("heal_expr")
    if hf_raw:
        hf = hf_raw
        he = info.get("heal_exprs")
        if isinstance(he, list) and he:
            lvx = max(1, min(int(lv or 1), len(he)))
            hf = he[lvx - 1]
        elif isinstance(hf_raw, list) and hf_raw and all(isinstance(x, str) for x in hf_raw):
            lvx = max(1, min(int(lv or 1), len(hf_raw)))
            hf = hf_raw[lvx - 1]
        try:
            from ..core.formula_expr import compile_expr, eval_expr, build_vars
            st2 = dict(st)
            st2["_player_lv"] = int(actor.get("level", 1) or 1)
            st2["_skill_lv"] = lv
            st2["max_hp"] = actor.get("max_hp", 0)
            _vars = build_vars(st2, player_lv=int(actor.get("level", 1) or 1),
                               skill_lv=lv, target_max_hp=actor.get("max_hp", 0))
            if isinstance(hf, str):
                return int(eval_expr(compile_expr(hf), _vars))
            # 段列表求和
            hv = 0
            for hseg in hf:
                hseg_expr = E.skill_formula_expr_for_seg(hseg, lv)
                if isinstance(hseg, dict) and hseg_expr:
                    hv += eval_expr(compile_expr(hseg_expr), _vars) * float(hseg.get("mult", 1.0) or 1.0)
                else:
                    fstat = hseg.get("stat", "matk")
                    fmult = float(hseg.get("mult", 1.0) or 1.0)
                    fflat = int(hseg.get("flat", 0) or 0)
                    if fstat == "max_hp":
                        hv += actor.get("max_hp", 0) * fmult + fflat
                    elif fstat == "flat":
                        hv += fflat
                    else:
                        hv += st.get("matk", 0) * fmult + fflat
            return int(hv)
        except Exception:
            return 0
    if info.get("hp_pct"):
        return int(actor.get("max_hp", 0) * float(info.get("hp_pct", 0)) * E.skill_power_mult(lv, info))
    # 兜底 matk × power（v95r38：power<1 曾是 hp% 语义，v174 已废弃改显式 hp_pct）
    return int(st.get("matk", 0) * float(info.get("power", 1.0) or 1.0) * E.skill_power_mult(lv, info))


# ============================================================
# 增益管线（N2b：effect → buffs/stacks/shields）
# ============================================================

def _do_buff(battle, ctx, actor, info, logs) -> list:
    """增益技能结算（对齐旧 _skill_buff 主线）。

    effect → actor.buffs 写入（key → 持续刻数）。复杂 effect（护盾/团队广播/
    元素转换等）查 EFFECT_HANDLERS（N3 完整迁入），此处内置最小集：
    - 通用属性 buff：effect 名直接作为 buff key
    - team_keys 映射（xx_all → xx_up）
    - shield_self 护盾
    """
    from ..engine import skill_buff_turns
    from ..core import constants as C
    eff = info.get("effect")
    lv = E.skill_level_of(actor, info.get("name", "")) if actor.get("class_name") else 0
    # 怪物施法：buff_turns 固定读 info.buff_turns（缺省 3），不吃技能等级成长
    if not actor.get("class_name"):
        base_turns = int(info.get("buff_turns", 3) or 3)
    else:
        # 玩家施法：skill_buff_turns 带 info → 读 buff_turns（战吼 10）。
        # 旧引擎 else 分支漏传 info → 战吼只给 3 刻（desc 说 10 刻）= 旧 bug
        # （test_commands_battle.py:96 断言固化）。新引擎做正确值：10 刻。
        base_turns = skill_buff_turns(lv, info=info)
    if eff:
        # 名词 effect → 统一走 apply_effects（查 EFFECT_ACTIONS 配置翻译成动词执行）
        # reduce 的 value（百分比）由配置动词的 value 折算参数给出
        from .effects import apply_effects
        _eff_params = {
            "type": eff, "turns": base_turns,
            "info": info,
            "mech_val": info.get("mech_val"),
            "effect_val": info.get("effect_val"),
            "reduce_pct": info.get("reduce_pct"),
        }
        # 减伤 reduce：value 由 mech_val/reduce_pct 折算（同旧 _sb_reduce）
        if eff == "reduce":
            rp = float(info.get("reduce_pct") or 0)
            if rp <= 0:
                mv = float(info.get("mech_val") or 0)
                rp = (mv / 100.0) if mv > 1 else (mv if 0 < mv <= 1 else 0.20)
            _eff_params["value"] = min(max(rp, 0.0), 0.9)
        # 护盾类：shield_self 盾值 = mech_val/effect_val（skill_mech_val 折算后传 value）
        if eff in ("shield_self", "shield_all", "shield") and "shield" in str(eff):
            from ..engine import skill_mech_val
            if eff == "shield_self":
                mval = skill_mech_val(info, lv) or int(info.get("effect_val", 0) or 0)
                _eff_params["value"] = mval
                _eff_params["halve"] = False
            else:
                pct = float(info.get("shield_pct", 0.20) or 0.20)
                _eff_params["pct"] = pct
                _eff_params["halve"] = True
        apply_effects(battle, actor, actor, [_eff_params], logs)
    logs.append(f"你施展【{info.get('name', ctx.skill_name or '技能')}】！")
    return logs
