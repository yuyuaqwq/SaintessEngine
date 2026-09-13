# -*- coding: utf-8 -*-
"""《奥兰迪亚》武器/词条特效族战斗内动作 —— we_procs（P4-D2 搬运物，逐字保真）。

真源：游戏仓 `C:/Users/yuyu/qqbot/data/plugins/dragonfall/game/services/battle_we_procs.py`
      **`:24-1468`**（模块级助手 + 27 个 `@register_action` 动作；真源共 1484 行）。
本文件 = 真源 `:24-1468` 的**逐字拷贝**：函数体、数值、`logs.append` 文案、
注释/分节 banner 一字未改（`.format()` 占位、缺省值、RNG 调用顺序全同）。

结构改写清单（只有 3 类，均在「注册方式 / import 路径」层，零行为变化）
----------------------------------------------------------------------
1. **去装配入口**：删真源尾部 `:1471-1485`（`_INSTALLED = False` + `ensure_registered()`）。
   不需要：引擎 `register_action` 顶层装饰器 **import 即注册**（真源那句注释自己写明
   「装饰器已随模块 import 注册（register_action 模块级执行）——本函数仅做幂等标记」）；
   本包由 `content/apply.py` / 验收脚本 import 本模块触发注册。
   ★ **B10-L1（2026-09-13）反转**：宿主 `battle_we_procs.py` 已薄壳化（双源收口），
   但薄壳仍按名调 `ensure_registered()` → 该入口**逐字搬回本文件末尾**
   （见文末「逐字端口回填」段），全仓仍只有这一份实现。
2. **import 头**：真源 `:20` `from saintess_engine.battle.effects import register_action` 与
   `:21` `from saintess_engine.battle.actors import actor_alive` **原样保留**（未新增
   模块级 import——ACT_TICK 按第 3 类在各函数体内就地取，与真源形状一致）。函数体内其余
   `from saintess_engine...` 惰性 import **原地一字未动**。
3. **游戏仓相对 import → 包内来源**：真源 5 处 `from ..core.constants import ACT_TICK`
   （`:251 / :341 / :517 / :692 / :730`）→ `from .we_data import ACT_TICK`
   （值 1.0 逐字抄自 `game/core/constants.py:156`，见 `we_data.py` 头注）。
   真源 `:251` 所在函数体（`we_shield_taken` 的 cd 折算）等**除法/乘法表达式未动**。

动作清单（27 个，真源装饰器行号 → 真源 `def` 行号）
-----------------------------------------------------
  :99    we_dot                 (def we_dot，体 100-116)
  :132   we_reflect             (def we_reflect，体 133-188)
  :191   we_hit_slow            (def we_hit_slow，体 192-203)
  :216   we_shield_taken        (def we_shield_taken，体 217-253)
  :261   we_guardian_will       (def we_guardian_will，体 262-279)
  :304   we_shield_cond         (def we_shield_cond，体 305-370)
  :388   we_abyss               (def we_abyss，体 389-403)
  :449   we_extra_dmg           (def we_extra_dmg，体 450-560)
  :568   we_mana_once           (def we_mana_once，体 569-580)
  :643   we_control             (def we_control，体 644-726)
  :747   we_dmg_mult_cond       (def we_dmg_mult_cond，体 748-824)
  :827   we_taken_mult_cond     (def we_taken_mult_cond，体 828-872)
  :888   we_stack_prod          (def we_stack_prod，体 889-925)
  :928   we_amp_consume         (def we_amp_consume，体 929-963)
  :983   we_combo_stack         (def we_combo_stack，体 984-1013)
  :1016  we_combo_end           (def we_combo_end，体 1017-1041)
  :1056  we_death_pool_add      (def we_death_pool_add，体 1057-1069)
  :1073  we_death_pool_pay      (def we_death_pool_pay，体 1074-1088)
  :1105  we_act_done_slow       (def we_act_done_slow，体 1106-1134)
  :1150  we_affix_dot           (def we_affix_dot，体 1151-1168)
  :1171  we_affix_defdown       (def we_affix_defdown，体 1172-1186)
  :1189  we_affix_element       (def we_affix_element，体 1190-1223)
  :1226  we_affix_bonus         (def we_affix_bonus，体 1227-1256)
  :1272  we_affix_counter       (def we_affix_counter，体 1273-1290)
  :1293  we_affix_tenacity      (def we_affix_tenacity，体 1294-1313)
  :1326  we_affix_res_gain      (def we_affix_res_gain，体 1327-1372)
  :1436  we_affix_purify        (def we_affix_purify，体 1437-1468)

⚠️ 过渡期铁律（设计稿 §五-3）：包版是**搬运物**——游戏仓 `battle_we_procs.py` 里的同名实现
继续存在（宿主仍在用），两者语义必须逐字一致，旧路径删除排在 D2 全部族搬完之后。
未搬/半接线项见 `overnight/d2-we_procs.md`（本批 27 个动作**全部已搬**；无未搬动作）。
"""
from __future__ import annotations

import random

from saintess_engine.battle.effects import register_action
from saintess_engine.battle.actors import actor_alive


def _roll(chance) -> bool:
    """概率判定：chance None（无字段）= 恒触发；0 不触发。"""
    if chance is None:
        return True
    try:
        if float(chance) <= 0:
            return False
        return random.random() < float(chance)
    except Exception:
        return True


def _hit_target(battle, target):
    """受击目标：params 无显式 target 时用 fire ctx 的 target（扩展动作兜底）。"""
    if target is not None and actor_alive(target):
        return target
    try:
        t = (battle._fire_ctx or {}).get("target")
        if t is not None and actor_alive(t):
            return t
    except Exception:
        pass
    return None


def _is_boss(actor) -> bool:
    return bool(actor and (actor.get("is_boss") or actor.get("role") == "boss"))


def _add_stacks(actor, key: str, amount: int, cap: int | None = None,
                battle=None, caster=None) -> int:
    """扩展动作内部叠层加值（V 系列：写 actor.effects[key].stacks）。

    仅本文件内部使用（不进引擎公共 API）；cap 缺省查 EFFECT_RULES 表。
    返回加后值。与引擎 act_state_add 语义一致（cap/下限）。
    """
    if actor is None or amount == 0:
        return 0
    ef = actor.setdefault("effects", {})
    entry = ef.get(key)
    if not isinstance(entry, dict):
        entry = ef[key] = {}
    if cap is None:
        # v181.M-affixtail cap 收敛：缺省 cap 走引擎 _cap_of（EFFECT_RULES 基础 +
        # actor.bonus.cap 动态（v181.M-bonus 分域——上限词条 full_pack/rage_forge 等
        # 抬 cap 后，本文件
        # 附赠通道（we_affix_res_gain 等）与主渠道同口径可攒满；无 bonus.cap 时与
        # 旧静态 state_def 读等价（行为零变化）。调用方显式传 cap 的（dot/defdown 等
        # 数值型叠层）语义不动。
        from saintess_engine.battle.effects import cap_of
        cap = cap_of(actor, key)
    cur = int(entry.get("stacks", 0) or 0)
    entry["stacks"] = max(0, min(cap, cur + int(amount)))
    # v181 批D：DOT 强度快照（数据声明了 period.atk/matk 才写）——
    #   伤害跟「挂毒的人」，tick 端读条目 src（引擎 note_dot_source 统一实现）
    try:
        from saintess_engine.battle.effects import note_dot_source
        note_dot_source(battle, actor, key, caster)
    except Exception:
        pass  # 快照失败不阻断施加
    return entry["stacks"]


# ============================================================
# proc_dot（4 key：命中挂限时 DOT）
# ============================================================

_DOT_LOG = {
    "smith_blaze_wound": "🔥 裂伤：目标每刻损失生命（{turns} 刻）！",
    "rong_lu_yu_wen": "🔥 熔炉余温：目标每刻灼烧（{turns} 刻）！",
    "ember_burn": "🔥 烬燃：目标每刻燃烧（{turns} 刻）！",
    "blood_trace": "🩸 败血：目标 {turns} 刻内每刻损失当前生命！",
}


@register_action("we_dot")
def we_dot(battle, caster, target, params, logs):
    """命中挂 DOT（proc_dot）：chance → target 挂 state dot 层（数值/限时由
    STATE_EFFECTS dot 声明表；层 cap 声明）。同 key 重复命中叠层（cap 内）。"""
    tgt = _hit_target(battle, target)
    if not tgt:
        return
    if not _roll(params.get("chance")):
        return
    dot_key = params.get("dot_key")
    if not dot_key:
        return  # 缺字段 = 无此行为
    from saintess_engine.battle.state_effects import state_def
    cap = int((state_def(dot_key) or {}).get("cap") or 1)
    _add_stacks(tgt, dot_key, int(params.get("amount", 1) or 1), cap=cap,
                battle=battle, caster=caster)   # v181 批D：施法者快照（DOT 公式 atk/matk 段）
    turns = int(params.get("turns") or 0) or 3
    logs.append(_DOT_LOG.get(params.get("key"), f"🔥 {dot_key}：目标持续掉血（{turns} 刻）！"))


# ============================================================
# proc_reflect（5 key：受击反弹；纯反伤 2 + 附赠 3）
# ============================================================

_REFLECT_LOG = {
    "thorn_armor": "🌵 荆棘缠绕：反弹 {rd} 点伤害！",
    "retribution_ring": "⚔️ 复仇之环：反弹 {rd} 点伤害！",
    "iron_echo": "🪨 铁壁回响：反弹 {rd} 点伤害，并回复少量生命！",
    "dragon_spine_mail": "🐉 龙脊反噬：反弹 {rd} 点伤害，并施加重伤！",
    "ember_bulwark": "🔥 烬火燎原：反伤 {rd} 点并叠加灼烧！",
}


@register_action("we_reflect")
def we_reflect(battle, caster, target, params, logs):
    """受击反弹（proc_reflect，on_taken 事件）。事件主体过滤已保证只处理受击者自身
    声明 → 反射者 = _owner/受击者（target）；反弹对象 = _fire_ctx["source"]（攻击者）；
    反弹值基于 _fire_ctx["dmg"]。无攻击者（DOT/环境伤）不反射。

    key 语义：
    - thorn_armor 无条件 ×15%；retribution_ring chance ×30%
    - iron_echo chance ×40% + 反射者回 maxhp×heal_pct
    - dragon_spine_mail chance ×25% + 攻击者 heal_down（state 层，N9 收编）
    - ember_bulwark 整场首触发：max_hp_pct 反伤 + 攻击者 burn 叠层
    反射伤害 source = 反射者（受击者），target = 攻击者（等级压制/击杀归属正确）。
    """
    if target is None:
        return  # 无反射者（受击者）
    key = params.get("key") or ""
    deflector = params.get("_owner") or target   # 装备持有者 = 反射者
    if not actor_alive(deflector):
        return
    if not _roll(params.get("chance")):
        return
    ctx = getattr(battle, "_fire_ctx", None) or {}
    attacker = ctx.get("source")
    if attacker is None or not actor_alive(attacker):
        return  # 无攻击来源（DOT/环境伤）不反射
    rd = 0
    if key == "ember_bulwark":
        # 整场一次（ext 自管标记）
        eff = deflector.setdefault("ext", {}).setdefault("we_proc", {})
        if eff.get("ember_bulwark_used"):
            return
        eff["ember_bulwark_used"] = True
        rd = max(1, int(deflector.get("max_hp", 100) * float(params.get("max_hp_pct", 0.05))))
        if rd > 0:
            from saintess_engine.battle.landing import deal_damage
            deal_damage(battle, deflector, attacker, rd, logs)
            from saintess_engine.battle.state_effects import state_def
            cap = int((state_def("burn") or {}).get("cap") or 5)
            _add_stacks(attacker, "burn", int(params.get("burn_stack", 1) or 1), cap=cap,
                        battle=battle, caster=deflector)   # 挂毒者=反弹方（快照语义）
        logs.append(_REFLECT_LOG.get(key, "").format(rd=rd))
        return
    if params.get("reflect_pct") is not None:
        dmg = int(ctx.get("dmg", 0) or 0)
        rd = max(1, int(dmg * float(params.get("reflect_pct", 0))))
    if rd > 0:
        from saintess_engine.battle.landing import deal_damage
        deal_damage(battle, deflector, attacker, rd, logs)
        if key == "iron_echo":
            hpv = float(params.get("heal_pct", 0.02) or 0)
            from saintess_engine.battle.landing import heal_actor
            heal_actor(battle, deflector, int(deflector.get("max_hp", 100) * hpv), logs)
        elif key == "dragon_spine_mail":
            from saintess_engine.battle.state_effects import state_def
            cap = int((state_def("heal_down") or {}).get("cap") or 5)
            _add_stacks(attacker, "heal_down", int(params.get("heal_down", 2) or 2), cap=cap)
    logs.append(_REFLECT_LOG.get(key, "").format(rd=rd))


@register_action("we_hit_slow")
def we_hit_slow(battle, caster, target, params, logs):
    """命中减速（hit/skill_hit）：chance → 目标 spd_down（mult 减幅语义：
    slow 0.5 = 速度减半剩 50%，对齐旧 SPD_DOWN_MULT 0.5 / affix slow 值语义）。
    food static 静电麻痹 + 未来词条通用。"""
    tgt = _hit_target(battle, target)
    if not tgt:
        return
    if not _roll(params.get("chance")):
        return
    _slow(battle, caster, tgt, int(params.get("turns") or 2),
          float(params.get("slow") or 0.5), logs)
    logs.append("⚡ 静电麻痹！目标速度下降！")


# ============================================================
# proc_shield taken 概率盾（sentinel/deeprock：chance + cd 冷却）
# ============================================================

_SHIELD_TAKEN_LOG = {
    "sentinel_aegis": "🛡️ 哨兵壁垒：获得 {shield} 点护盾！（3 刻）",
    "deeprock_aegis": "🪨 深岩壁垒：获得护盾！（吸收 8% 最大生命）",
}


@register_action("we_shield_taken")
def we_shield_taken(battle, caster, target, params, logs):
    """受击概率盾（proc_shield taken，on_taken）：cd 冷却 → chance → 上盾。

    owner = _owner/受击者；盾值 sentinel = base+per_lv×lv，deeprock = shield_pct×maxhp；
    cd 存 owner.ext.we_proc（cd_key → ready_at 绝对时刻，ACT_TICK 折算）。
    """
    owner = params.get("_owner") or target
    if owner is None or not actor_alive(owner):
        return
    cd_key = params.get("cd_key")
    now = float(getattr(battle, "_now", 0) or 0)
    st = owner.setdefault("ext", {}).setdefault("we_proc", {})
    if cd_key:
        if float(st.get(cd_key, 0) or 0) > now:
            return  # cd 中
    if not _roll(params.get("chance")):
        return
    # 盾值
    if params.get("base") is not None or params.get("per_lv") is not None:
        lv = int(owner.get("level", 1) or 1)
        value = int(float(params.get("base") or 0) + float(params.get("per_lv") or 0) * lv)
    elif params.get("shield_pct") is not None:
        value = int(owner.get("max_hp", 100) * float(params["shield_pct"]))
    else:
        return
    if value <= 0:
        return
    key = params.get("shield_key") or "we_sentinel"
    turns = int(params.get("turns") or 3)
    from saintess_engine.battle.effects import act_shield
    act_shield(battle, owner, owner,
               {"type": "shield", "key": key, "value": value, "turns": turns, "on": "caster"},
               logs)
    if cd_key:
        from .we_data import ACT_TICK
        st[cd_key] = now + int(params.get("cd") or 1) * ACT_TICK
    logs.append(_SHIELD_TAKEN_LOG.get(params.get("key") or "", f"🛡️ 获得护盾 {value} 点！").format(shield=value))


# ============================================================
# proc_retort_mark guardian_will（受击给攻击者挂减攻）
# ============================================================


@register_action("we_guardian_will")
def we_guardian_will(battle, caster, target, params, logs):
    """卫士信念：受击 chance → 攻击者下一次攻击伤害 -weaken%（攻方 buff atk mul 0.75）。"""
    owner = params.get("_owner") or target
    if owner is None or not actor_alive(owner):
        return
    if not _roll(params.get("chance")):
        return
    ctx = getattr(battle, "_fire_ctx", None) or {}
    attacker = ctx.get("source")
    if attacker is None or not actor_alive(attacker):
        return
    weaken = float(params.get("weaken", 0.25) or 0.25)
    from saintess_engine.battle.effects import act_apply
    act_apply(battle, attacker, attacker,
             {"type": "apply", "key": params.get("debuff_key") or "mon_atk_down",
              "stat": "atk", "op": "mul", "mult": 1.0 - weaken,
              "turns": int(params.get("turns", 1) or 1), "on": "caster"}, logs)
    logs.append("🛡️ 卫士信念：敌人下一次攻击伤害 -25%！")


# ============================================================
# proc_shield 条件盾（threshold 低保 3 + heal 溢出 2 + crit 1）
# ============================================================

_SHIELD_COND_LOG = {
    "bedrock_crown": "🪨 磐石守护：生命垂危，获得 {shield} 点护盾！（4 刻）",
    "firmament_crown": "🌌 苍穹庇护：获得 {shield} 点护盾！",
    "gargoyle_heart": "💎 石像鬼之心：获得 {shield} 点护盾并回复 {heal} 点生命！",
    "echo_bless": "🌿 回响祝福：治疗溢出转化为 {shield} 点护盾！",
    "atonement_shield": "⚖️ 赎罪之盾：治疗溢出转化为 {shield} 点护盾！",
    "endless_radiance": "🌟 无尽辉光：暴击获得 {shield} 点护盾！",
}


def _add_owner_shield(battle, owner, params, value, logs):
    from saintess_engine.battle.effects import act_shield
    act_shield(battle, owner, owner,
               {"type": "shield", "key": params.get("shield_key") or "we_shield",
                "value": value, "turns": int(params.get("turns") or 3), "on": "caster"},
               logs)


@register_action("we_shield_cond")
def we_shield_cond(battle, caster, target, params, logs):
    """条件护盾（proc_shield 条件型）——事件由装配层挂载，执行器按 key 语义：

    - bedrock/gargoyle（on_taken 后自查）：hp 低于 threshold → 整场一次低保盾
      （gargoyle 附回血）
    - firmament（on_taken 后自查）：hp 低于 threshold → 限 per_battle 次低保盾
    - echo_bless/atonement（on_heal）：治疗溢出转盾（_fire_ctx.overflow）
    - endless_radiance（crit）：暴击 + cd → 盾
    状态（used/次数/cd）存 owner.ext.we_proc。
    """
    owner = params.get("_owner") or target
    if owner is None or not actor_alive(owner):
        return
    key = params.get("key") or ""
    st = owner.setdefault("ext", {}).setdefault("we_proc", {})
    ctx = getattr(battle, "_fire_ctx", None) or {}
    now = float(getattr(battle, "_now", 0) or 0)
    # ---- heal 溢出转盾 ----
    if key in ("echo_bless", "atonement_shield"):
        overflow = int(ctx.get("overflow", 0) or 0)
        if overflow <= 0:
            return
        cap = int(owner.get("max_hp", 100) * float(params.get("cap_hp_pct") or 0.10))
        if key == "echo_bless":
            shield = min(cap, int(overflow * float(params.get("overflow_pct") or 0.30)))
        else:
            shield = min(cap, overflow)
        if shield > 0:
            _add_owner_shield(battle, owner, params, shield, logs)
            logs.append(_SHIELD_COND_LOG.get(key, "").format(shield=shield))
        return
    # ---- crit 盾（endless_radiance：装配层挂 crit 事件 → 到达即暴击）----
    if key == "endless_radiance":
        if float(st.get(params.get("cd_key"), 0) or 0) > now:
            return
        shield = int(owner.get("max_hp", 100) * float(params.get("shield_hp_pct") or 0.05))
        from .we_data import ACT_TICK
        _add_owner_shield(battle, owner, params, shield, logs)
        st[params.get("cd_key") or "we_radiance_cd"] = now + int(params.get("cd") or 3) * ACT_TICK
        logs.append(_SHIELD_COND_LOG.get(key, "").format(shield=shield))
        return
    # ---- threshold 低保盾（bedrock/gargoyle/firmament）----
    used_key = params.get("used_key")
    if key == "firmament_crown":
        n = int(st.get(used_key, 0) or 0)
        if n >= int(params.get("per_battle") or 2):
            return
    else:
        if st.get(used_key):
            return
    ratio = float(owner.get("hp", 0)) / max(1, owner.get("max_hp", 1) or 1)
    if ratio >= float(params.get("threshold") or 0.30):
        return  # 血量未到阈值
    if key == "firmament_crown":
        st[used_key] = int(st.get(used_key, 0) or 0) + 1
    else:
        st[used_key] = True
    shield = int(owner.get("max_hp", 100) * float(params.get("shield_hp_pct") or 0.2))
    _add_owner_shield(battle, owner, params, shield, logs)
    if key == "gargoyle_heart":
        heal = int(owner.get("max_hp", 100) * float(params.get("heal_pct") or 0.1))
        from saintess_engine.battle.landing import heal_actor
        heal_actor(battle, owner, heal, logs)
        logs.append(_SHIELD_COND_LOG.get(key, "").format(shield=shield, heal=heal))
    else:
        logs.append(_SHIELD_COND_LOG.get(key, "").format(shield=shield))


def _crit_flag(ctx: dict) -> bool:
    """crit 事件判定兜底：crit 事件 ctx 无 is_crit 键（事件本身即暴击）——
    由装配层区分：endless_radiance 挂 crit 事件时恒为暴击 → ctx 带 is_crit=True 由
    fire 暂存补充不了，这里约定 crit 事件挂载的 effect 直接视为暴击。
    """
    # fire crit 事件 ctx 不设 is_crit；on_hit 类也不该挂 endless_radiance——
    # 装配层把 endless_radiance 挂 crit 事件 → 到达执行器即暴击。
    return True


# ============================================================
# proc_buff abyss_barrier（battle_start 永久最大生命加成）
# ============================================================


@register_action("we_abyss")
def we_abyss(battle, caster, target, params, logs):
    """深渊屏障（proc_buff abyss_barrier，battle_start 整场一次）：
    最大生命 +max_hp_pct×当前 maxhp，hp 同步等量增加。ext 标记防重复。"""
    owner = params.get("_owner") or caster
    if owner is None:
        return
    st = owner.setdefault("ext", {}).setdefault("we_proc", {})
    if st.get("abyss_used"):
        return
    st["abyss_used"] = True
    bonus = int(owner.get("max_hp", 100) * float(params.get("max_hp_pct") or 0.08))
    if bonus > 0:
        owner["max_hp"] = owner.get("max_hp", 100) + bonus
        owner["hp"] = min(owner["max_hp"], owner.get("hp", 0) + bonus)
        logs.append(params.get("log") or f"🌑 深渊屏障：最大生命 +{bonus}！（持续整场）")


# ============================================================
# proc_extra_dmg（11 key：命中追击直伤/真伤/吸血）
# ============================================================

_EXTRA_LOG = {
    "afterglow_splash": "🌅 余波 溅射 {dmg} 点奥术伤害！",
    "spellblade_echo": "🔮 咒刃 溅射 {dmg} 点奥术伤害！",
    "annihilation_echo": "💥 湮灭回响 溅射 {dmg} 点奥术伤害！",
    "wind_split": "🌪️ 裂风矢 追加 {dmg} 点伤害！",
    "endless_blade": "⚔️ 无尽锋芒 追加 {dmg} 点伤害！",
    "hunter_open": "🗡️ 破绽 造成 {dmg} 点真实伤害！",
    "siren_fang": "🧜 海妖猎杀 造成 {dmg} 点真实伤害！",
    "star_pierce": "☄️ 穿星 造成 {dmg} 点真实伤害！",
}


def _owner_stats(battle, owner):
    from saintess_engine import stats as S
    try:
        return S.actor_stats(battle, owner)
    except Exception:
        return dict(owner)


def _target_def_stats(battle, target):
    from saintess_engine import stats as S
    try:
        return S.actor_stats(battle, target)
    except Exception:
        return dict(target)


def _calc(battle, atk_val, def_val, dmg_type="phys", pene_pct=0.0):
    from saintess_engine.battle.formulas import calc_damage
    try:
        if dmg_type == "true":
            return max(1, calc_damage(int(atk_val), 0, False, dmg_type="true"))
        return max(1, calc_damage(int(atk_val), int(def_val), False,
                                    pene_pct=pene_pct, dmg_type=dmg_type))
    except Exception:
        return max(1, int(atk_val))


@register_action("we_extra_dmg")
def we_extra_dmg(battle, caster, target, params, logs):
    """命中追击（proc_extra_dmg，hit/skill_hit 事件，主体=攻击者即 owner）。
    mode 分派（表字段权威；RNG 在 chance/计数保底处各消耗一次，同旧语义）：
    - splash_magi（afterglow/spellblade_echo/annihilation）：matk×pct vs mdef 溅射
    - extra_phys（wind_split）：atk×pct vs def
    - extra_phys_pene（phantom_barrage）：计数 + chance/保底 → atk×pct vs def×(1-pene)
    - extra_phys_oncrit（endless_blade）：crit 事件 + cd 1 刻 → atk×pct 追加
    - true_dmg_nth（hunter/siren/star）：计数到 count → atk×pct 真伤（star 加已损 bonus cap）
    - curhp_dmg_heal（soul_eater）：敌当前 hp×pct（cap atk）伤 + 回等量
    - lifesteal（novice_lifesteal）：hit dmg×heal_pct 回血
    计数/CD 存 owner.ext.we_proc。
    """
    owner = params.get("_owner") or caster
    if owner is None or not actor_alive(owner):
        return
    ctx = getattr(battle, "_fire_ctx", None) or {}
    tgt = ctx.get("target") or target
    if tgt is None or not actor_alive(tgt):
        return
    key = params.get("key") or ""
    mode = params.get("mode") or ""
    st = owner.setdefault("ext", {}).setdefault("we_proc", {})
    # ---- lifesteal：本击伤害回血（novice_lifesteal 装备词条 + food_lifesteal 料理蛇羹）----
    if key in ("novice_lifesteal", "food_lifesteal"):
        dmg = int(ctx.get("dmg", 0) or 0)
        if dmg <= 0:
            os_ = _owner_stats(battle, owner)
            dmg = int(os_.get("atk", 0) or 0)
        heal = int(dmg * float(params.get("heal_pct") or 0.05))
        if heal > 0:
            from saintess_engine.battle.landing import heal_actor
            heal_actor(battle, owner, heal, logs)
        return
    # ---- 概率前置（溅射/裂风）----
    if mode in ("splash_magi", "extra_phys", "extra_phys_pene"):
        if not _roll(params.get("chance")):
            return
    os_ = _owner_stats(battle, owner)
    es_ = _target_def_stats(battle, tgt)
    # ---- extra_phys_pene（phantom：计数保底）----
    if key == "phantom_barrage":
        sk = params.get("stack_key") or "phantom_cnt"
        n = int(st.get(sk, 0) or 0) + 1
        st[sk] = n
        if n < int(params.get("guarantee") or 5) and random.random() >= float(params.get("chance") or 0.2):
            return
        st[sk] = 0
        dmg = _calc(battle, int(os_.get("atk", 0)) * float(params.get("atk_pct") or 0.3),
                    es_.get("def", 0), pene_pct=float(params.get("pene_pct") or 0.5))
        from saintess_engine.battle.landing import deal_damage
        deal_damage(battle, owner, tgt, dmg, logs)
        logs.append(params.get("log") or f"🌪️ 幻影连射！无视 50% 防御造成 {dmg} 点伤害！")
        return
    # ---- splash_magi（matk 溅射）----
    if mode == "splash_magi":
        dmg = _calc(battle, int(os_.get("matk", 0)) * float(params.get("atk_pct") or 0.15),
                    es_.get("mdef", 0), dmg_type="magi")
        from saintess_engine.battle.landing import deal_damage
        deal_damage(battle, owner, tgt, dmg, logs)
        logs.append(_EXTRA_LOG.get(key, "🔮 溅射 {dmg} 点奥术伤害！").format(dmg=dmg))
        return
    # ---- extra_phys_oncrit（endless_blade：crit + cd 1 刻限 1）----
    if key == "endless_blade":
        now = float(getattr(battle, "_now", 0) or 0)
        cd_key = params.get("used_key") or "we_blade_cd"
        if float(st.get(cd_key, 0) or 0) > now:
            return
        from .we_data import ACT_TICK
        st[cd_key] = now + ACT_TICK  # 1 刻冷却（"每刻限 1"）
        dmg = _calc(battle, int(os_.get("atk", 0)) * float(params.get("atk_pct") or 0.2),
                    es_.get("def", 0))
        from saintess_engine.battle.landing import deal_damage
        deal_damage(battle, owner, tgt, dmg, logs)
        logs.append(_EXTRA_LOG.get(key, "⚔️ 追加 {dmg} 点伤害！").format(dmg=dmg))
        return
    # ---- extra_phys（wind_split）----
    if mode == "extra_phys":
        dmg = _calc(battle, int(os_.get("atk", 0)) * float(params.get("atk_pct") or 0.5),
                    es_.get("def", 0))
        from saintess_engine.battle.landing import deal_damage
        deal_damage(battle, owner, tgt, dmg, logs)
        logs.append(_EXTRA_LOG.get(key, "💥 追加 {dmg} 点伤害！").format(dmg=dmg))
        return
    # ---- true_dmg_nth（hunter/siren/star 计数真伤）----
    if mode == "true_dmg_nth":
        sk = params.get("stack_key") or key + "_cnt"
        n = int(st.get(sk, 0) or 0) + 1
        st[sk] = n
        if n < int(params.get("count") or 3):
            return
        st[sk] = 0
        base = int(os_.get("atk", 0)) * float(params.get("atk_pct") or 0.2)
        if key == "star_pierce":
            lost = int((tgt.get("max_hp", 0) - tgt.get("hp", 0)) * float(params.get("lost_hp_pct") or 0.03))
            cap = int(tgt.get("max_hp", 1) * float(params.get("cap_pct") or 0.05))
            base = base + min(lost, cap)
        dmg = _calc(battle, base, 0, dmg_type="true")
        from saintess_engine.battle.landing import deal_damage
        deal_damage(battle, owner, tgt, dmg, logs)
        logs.append(_EXTRA_LOG.get(key, "✨ 造成 {dmg} 点真实伤害！").format(dmg=dmg))
        return
    # ---- curhp_dmg_heal（soul_eater）----
    if key == "soul_eater":
        cap = max(1, int(os_.get("atk", 0) or 0))
        bonus = min(cap, max(1, int(tgt.get("hp", 0) * float(params.get("cur_hp_pct") or 0.02))))
        if bonus > 0:
            from saintess_engine.battle.landing import deal_damage, heal_actor
            deal_damage(battle, owner, tgt, bonus, logs)
            healed = heal_actor(battle, owner, bonus, logs)
            logs.append("💜 破败之吻：额外 {bonus} 点伤害，回复 {healed} 点生命！".format(bonus=bonus, healed=healed))
        return


# ============================================================
# proc_aux novice_dawn_mana（施法首次回蓝）
# ============================================================


@register_action("we_mana_once")
def we_mana_once(battle, caster, target, params, logs):
    """晨星回蓝（novice_dawn_mana，skill_cast 事件）：整场首次施法回蓝。"""
    owner = params.get("_owner") or caster
    if owner is None:
        return
    st = owner.setdefault("ext", {}).setdefault("we_proc", {})
    if st.get("dawn_mana_used"):
        return
    st["dawn_mana_used"] = True
    mp = int(params.get("mp") or 10)
    owner["mp"] = min(int(owner.get("max_mp", 999) or 999), int(owner.get("mp", 0) or 0) + mp)
    logs.append(params.get("log") or f"🌅 晨星：回复 {mp} 点魔力！")


# ============================================================
# proc_control（9 key 敌方控制：7 可迁 + randuin/ice_vein 依赖 enemy_act 事件
# ——saintess_engine 无"敌人行动后"事件点位，留缺口记录（见 docs/N9 施工文档 §1.3））
# ============================================================

_CONTROL_LOG = {
    "frost_ring": "🧊 霜环：目标被冻结 {turns} 刻！",
    "holy_judgment_field": "⚖️ 圣裁领域：目标受治疗 -30%（2 刻）！",
    "everfrost_domain": "🧊 永冻领域：目标被冻结 {turns} 刻！",
    "everfrost_scepter": "🧊 永霜禁锢：目标被冻结 {turns} 刻！",
    "frost_crown": "🧊 寒霜凝视：目标被冻结 {turns} 刻！",
    "holy_word_bind": "✨ 圣言禁锢：目标被冻结 {turns} 刻！",
    "time_freeze": "⏳ 时光凝滞！敌人被定身，跳过一次行动！",
}


def _control_target(battle, target, params) -> dict:
    """控制作用目标（owner = 装备者）：
    - hit/skill_hit 事件：被打者（ctx.target，非 owner）
    - taken 事件：攻击者 ctx.source（受击反冻——不控自己）
    - heal 事件：敌对首选存活（治疗控场）
    目标非 owner 自己时优先 target（hit 被打者）。
    """
    ctx = getattr(battle, "_fire_ctx", None) or {}
    ev = ctx.get("_event") or ""
    owner = params.get("_owner")
    if ev in ("taken",):
        t = ctx.get("source")
        if t is not None and actor_alive(t):
            return t
    if target is not None and target is not owner and actor_alive(target):
        return target
    if ev in ("heal",):
        pass  # fallthrough 敌对首选
    t = ctx.get("source")
    if t is not None and t is not owner and actor_alive(t):
        return t
    # 兜底：敌对首个存活
    for acts in battle.sides.values():
        for a in acts:
            if a is not owner and actor_alive(a) and not a.get("human_controlled"):
                return a
    return None


def _freeze(battle, owner, tgt, turns, params, logs):
    """冻结（Boss 减半沿用引擎 act_control 定稿语义，不迁旧免疫退化特例）。"""
    from saintess_engine.battle.effects import act_apply
    act_apply(battle, owner, tgt,
                {"type": "apply", "key": "freeze", "turns": turns, "mode": "skip", "on": "target"}, logs)


def _slow(battle, owner, tgt, turns, pct, logs):
    """减速：敌 spd×（1-pct）buff（saintess_engine buff 快照折算）。"""
    from saintess_engine.battle.effects import act_apply
    act_apply(battle, owner, tgt,
             {"type": "apply", "key": "spd_down", "stat": "spd", "op": "mul",
              "mult": 1.0 - float(pct), "turns": turns, "on": "target"}, logs)


@register_action("we_control")
def we_control(battle, caster, target, params, logs):
    """敌方控制（proc_control）：mode 分派。目标 = hit/skill_hit 被打者 /
    taken 攻击者 / heal 敌对首选。状态（次数/cd/used）存 owner.ext.we_proc。"""
    owner = params.get("_owner") or caster
    if owner is None or not actor_alive(owner):
        return
    key = params.get("key") or ""
    mode = params.get("mode") or "freeze"
    tgt = _control_target(battle, target, params)
    if tgt is None or not actor_alive(tgt):
        return
    st = owner.setdefault("ext", {}).setdefault("we_proc", {})
    ctx = getattr(battle, "_fire_ctx", None) or {}
    now = float(getattr(battle, "_now", 0) or 0)
    # ---- 前置：cd（everfrost_domain）----
    cd_key = params.get("cd_key")
    if cd_key and float(st.get(cd_key, 0) or 0) > now:
        return
    # ---- 前置：限次（frost_crown 每场 max_per_battle）----
    used_key = params.get("used_key")
    limit = int(params.get("max_per_battle") or 0) if params.get("max_per_battle") is not None else 0
    if limit > 0 and int(st.get(used_key, 0) or 0) >= limit:
        return
    # ---- chance ----
    if not _roll(params.get("chance")):
        return
    src_turns = int(params.get("freeze_turns") or params.get("turns") or 1)
    if mode == "slow_or_freeze":
        # frost_ring：已减速 → 冻结；否则减速（V 系列：效果条目在 effects）
        if (tgt.get("effects") or {}).get("spd_down"):
            _freeze(battle, owner, tgt, src_turns, params, logs)
            _bump_control_state(st, cd_key, used_key, params, now)
            logs.append(_CONTROL_LOG.get(key, "🧊 冻结！").format(turns=src_turns))
        else:
            _slow(battle, owner, tgt, int(params.get("slow_turns") or 2),
                  float(params.get("slow_pct") or 0.4), logs)
        return
    if mode == "slow_heal_down":
        _slow(battle, owner, tgt, int(params.get("slow_turns") or 2),
              float(params.get("slow_pct") or 0.3), logs)
        from saintess_engine.battle.state_effects import state_def
        cap = int((state_def("heal_down") or {}).get("cap") or 5)
        _add_stacks(tgt, "heal_down", int(params.get("heal_down") or 2), cap=cap)
        logs.append(_CONTROL_LOG.get(key, "⚖️ 圣裁领域！").format(turns=0))
        return
    if mode == "freeze_cd":
        _freeze(battle, owner, tgt, src_turns, params, logs)
        if cd_key:
            from .we_data import ACT_TICK
            st[cd_key] = now + int(params.get("cd") or 1) * ACT_TICK
        logs.append(_CONTROL_LOG.get(key, "🧊 永冻！").format(turns=src_turns))
        return
    if mode == "freeze":
        _freeze(battle, owner, tgt, src_turns, params, logs)
        logs.append(_CONTROL_LOG.get(key, "🧊 冻结！").format(turns=src_turns))
        return
    if mode == "freeze_taken_limited":
        # frost_crown：受击冻结限次（先计数后冻结）
        if used_key:
            st[used_key] = int(st.get(used_key, 0) or 0) + 1
        _freeze(battle, owner, tgt, src_turns, params, logs)
        logs.append(_CONTROL_LOG.get(key, "🧊 冻结！").format(turns=src_turns))
        return
    if mode == "freeze_heal":
        if ctx.get("overflow"):
            return
        _freeze(battle, owner, tgt, src_turns, params, logs)
        logs.append(_CONTROL_LOG.get(key, "✨ 禁锢！").format(turns=src_turns))
        return
    if mode == "threshold_stun":
        # time_freeze：玩家 hp 低阈值（挂 on_taken 自查）每场一次
        if st.get(used_key):
            return
        ratio = float(owner.get("hp", 0)) / max(1, owner.get("max_hp", 1) or 1)
        if ratio >= float(params.get("threshold") or 0.30):
            return
        st[used_key] = True
        from saintess_engine.battle.effects import act_apply
        act_apply(battle, owner, tgt,
                    {"type": "apply", "key": "stun", "turns": 1, "mode": "skip", "on": "target"}, logs)
        logs.append(_CONTROL_LOG.get(key, "⏳ 时光凝滞！"))
        return
    return  # 未知 mode 静默


def _bump_control_state(st, cd_key, used_key, params, now):
    from .we_data import ACT_TICK
    if cd_key:
        st[cd_key] = now + int(params.get("cd") or 1) * ACT_TICK


# ============================================================
# 乘区修正动作（N9.13：dmg_calc/taken_calc 事件消费）
# ============================================================

_MULT_TAG = {
    "hp_target_lt": "💀处决",
    "hp_self_lt": "🔥残血",
    "target_marked": "🎯追猎",
    "always": "🛡️",
}


@register_action("we_dmg_mult_cond")
def we_dmg_mult_cond(battle, caster, target, params, logs):
    """条件增伤乘区（dmg_calc 事件，攻击者视角）：cond 命中 → _fire_ctx.mult ×= 值。
    条件谓词全在扩展动作（引擎零知识）：
    - hp_target_lt：目标生命低于阈值（处决 execute：<30% ×1.3）
    - hp_self_lt：自己生命低于阈值（残血增伤）
    - always：无条件（叠层放大器常驻段等）"""
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    owner = params.get("_owner") or caster
    tgt = ctx.get("target") or target
    cond = params.get("cond") or "always"
    mult = float(params.get("mult") or 0)
    if mult <= 0:
        return
    hit = False
    try:
        if cond == "hp_target_lt":
            if tgt is not None and actor_alive(tgt) and tgt.get("hp") is not None:
                hit = (float(tgt.get("hp", 0)) / max(1, float(tgt.get("max_hp", 1) or 1))
                       < float(params.get("threshold") or 0.30))
        elif cond == "hp_target_gt":
            # 弑星：目标高血量 >70% ×1.15
            if tgt is not None and actor_alive(tgt) and tgt.get("hp") is not None:
                hit = (float(tgt.get("hp", 0)) / max(1, float(tgt.get("max_hp", 1) or 1))
                       > float(params.get("threshold") or 0.70))
        elif cond == "hp_self_lt":
            if owner is not None and owner.get("hp") is not None:
                hit = (float(owner.get("hp", 0)) / max(1, float(owner.get("max_hp", 1) or 1))
                       < float(params.get("threshold") or 0.30))
        elif cond == "kind_magic":
            # 奥术苍穹：仅魔法技（info.kind == 魔法）×1.1
            info = ctx.get("info") or {}
            hit = (info.get("kind") == "魔法")
        elif cond == "hp_self_gt":
            # 王狮之心：自己生命 >70% 时增伤
            if owner is not None and owner.get("hp") is not None:
                hit = (float(owner.get("hp", 0)) / max(1, float(owner.get("max_hp", 1) or 1))
                       > float(params.get("threshold") or 0.70))
        elif cond == "name_contains":
            # 龙威：目标名包含关键词（enemy_contains 列表任一命中）
            if tgt is not None:
                _nm = str(tgt.get("name", ""))
                kw = params.get("keywords") or []
                hit = any(k in _nm for k in kw)
        elif cond == "role_caster":
            # 破魔：目标 role=caster/法系（is_caster/role 标签）
            if tgt is not None:
                hit = bool(tgt.get("is_caster") or tgt.get("role") == "caster"
                           or tgt.get("kind") == "caster")
        elif cond == "enemy_marked":
            # 追猎：目标带猎印（effects hunt_mark 层 >0 或 mark 条目）
            if tgt is not None:
                ef = tgt.get("effects") or {}
                hm = ef.get("hunt_mark")
                mk = ef.get("mark")
                hit = (int(hm.get("stacks", 0) or 0) > 0 if isinstance(hm, dict) else False) \
                    or bool(mk)
        elif cond == "mech_any":
            # v181.M-bonus finisher：本击施放技能 mech 命中任一 或 显示名含任一
            # （终结技词条：mech=finisher 的终结·割喉/处决/暗影绞杀；毒爆
            # poison_burst_finisher 名不含终结 → 不算，词条 desc 终结技限定）
            info = ctx.get("info") or {}
            _m = str(info.get("mech") or "")
            hit = any(_m == str(x) for x in (params.get("mechs") or []))
            if not hit:
                _nm = str(info.get("name") or "")
                hit = any(k and k in _nm for k in (params.get("names_any") or []))
        else:
            hit = True
    except Exception:
        hit = False
    if hit:
        ctx["mult"] = float(ctx.get("mult", 1.0) or 1.0) * mult
        tag = params.get("tag") or _MULT_TAG.get(cond, "")
        if tag:
            ctx["tags"] = list(ctx.get("tags") or []) + [f"{tag}x{mult:.2f}"]


@register_action("we_taken_mult_cond")
def we_taken_mult_cond(battle, caster, target, params, logs):
    """条件减伤乘区（taken_calc 事件，承伤者视角）：cond 命中 → _fire_ctx.mult ×= 值
    （值 <1 = 减伤：death_dance 8% → 0.92；沸血怒气满全减伤 0.92）。
    谓词：always / hp_self_lt / state_full（state 满层：rage_full 怒气满）"""
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    owner = params.get("_owner") or target
    cond = params.get("cond") or "always"
    mult = float(params.get("mult") or 0)
    if mult <= 0:
        return
    hit = False
    try:
        if cond == "hp_self_lt":
            if owner is not None and owner.get("hp") is not None:
                hit = (float(owner.get("hp", 0)) / max(1, float(owner.get("max_hp", 1) or 1))
                       < float(params.get("threshold") or 0.30))
        elif cond == "first_turn":
            # 首刻守御：整场首次受击减伤（used 标记消耗一次）
            if owner is not None:
                st = owner.setdefault("ext", {}).setdefault("we_proc", {})
                uk = params.get("used_key")
                if uk and st.get(uk):
                    return  # 已用过
                if uk:
                    st[uk] = True
                hit = True
        elif cond.startswith("state_full"):
            sk = params.get("state_key") or ""
            if owner is not None and sk:
                ef = owner.get("effects") or {}
                entry = ef.get(sk)
                cap = int((_state_cap(sk) or 0))
                hit = cap > 0 and int(entry.get("stacks", 0) or 0) >= cap \
                    if isinstance(entry, dict) else False
        else:
            hit = True
    except Exception:
        hit = False
    if hit:
        ctx["mult"] = float(ctx.get("mult", 1.0) or 1.0) * mult
        tag = params.get("tag") or ""
        if tag:
            ctx["tags"] = list(ctx.get("tags") or []) + [f"{tag}x{mult:.2f}"]


def _state_cap(key: str) -> int:
    try:
        from saintess_engine.battle.state_effects import state_def
        return int((state_def(key) or {}).get("cap") or 0)
    except Exception:
        return 0


# ============================================================
# proc_stack 叠层放大器（N9.14：生产叠层 + dmg_calc 消费乘区）
# ============================================================


@register_action("we_stack_prod")
def we_stack_prod(battle, caster, target, params, logs):
    """叠层生产（proc_stack）：普通 = effects[key].stacks +1（cap 声明表）；
    sage = 满 need 置 charge；thunder_weave = 满 cap 清层置 charge。"""
    owner = params.get("_owner") or caster
    if owner is None or not actor_alive(owner):
        return
    key = params.get("key") or ""
    sk = params.get("stack_key") or key
    from saintess_engine.battle.state_effects import state_def
    cfg = state_def(sk) or {}
    cap = int(cfg.get("cap") or 999)
    ef = owner.setdefault("effects", {})
    if key == "sage_amp":
        need = int(params.get("need") or 2)
        cur_entry = ef.get(sk)
        n = int(cur_entry.get("stacks", 0) or 0) if isinstance(cur_entry, dict) else 0
        n += 1
        if n >= need:
            ef[sk] = {"stacks": 0}
            owner.setdefault("ext", {}).setdefault("we_proc", {})[params.get("charge_key") or "we_sage_charge"] = float(params.get("charge_pct") or 0.25)
            logs.append("📚 秘典充能就绪！下一技能伤害 +25%")
        else:
            ef[sk] = {"stacks": n}
        return
    # 普通叠层（cap 声明封顶）
    entry = ef.get(sk)
    if not isinstance(entry, dict):
        entry = ef[sk] = {}
    cur = int(entry.get("stacks", 0) or 0)
    entry["stacks"] = max(0, min(cap, cur + 1))
    cur = entry["stacks"]
    if key == "thunder_weave" and cur >= cap:
        ef[sk] = {"stacks": 0}
        owner.setdefault("ext", {}).setdefault("we_proc", {})[params.get("charge_key") or "we_thunder_charge"] = float(params.get("charge_pct") or 0.20)
        logs.append("⚡ 雷纹充盈！下一次攻击 +20%")
    elif key in ("rune_amp", "eternal_codex", "time_staff"):
        logs.append(f"✦ {sk} 叠层 {cur}/{cap}")


@register_action("we_amp_consume")
def we_amp_consume(battle, caster, target, params, logs):
    """叠层消费乘区（dmg_calc）：按 key 语义乘进 _fire_ctx.mult：
    - rune_amp：×(1+per×层) 后清层（"下一技能"消耗）
    - eternal_codex/time_staff：×(1+per×层) 不清层（常驻放大器）
    - sage_amp/thunder_weave：charge 就绪 → ×charge_pct 一次并清
    """
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    owner = params.get("_owner") or caster
    if owner is None:
        return
    key = params.get("key") or ""
    sk = params.get("stack_key") or key
    st = owner.setdefault("ext", {}).setdefault("we_proc", {})
    ef = owner.setdefault("effects", {})
    mult = 1.0
    if key == "rune_amp":
        entry = ef.pop(sk, None)
        n = int(entry.get("stacks", 0) or 0) if isinstance(entry, dict) else 0
        if n > 0:
            mult = 1.0 + float(params.get("per_pct") or 0.02) * n
    elif key in ("eternal_codex", "time_staff"):
        entry = ef.get(sk)
        n = int(entry.get("stacks", 0) or 0) if isinstance(entry, dict) else 0
        if n > 0:
            mult = 1.0 + float(params.get("per_pct") or 0.015) * n
    elif key in ("sage_amp", "thunder_weave"):
        ck = params.get("charge_key") or ("we_sage_charge" if key == "sage_amp" else "we_thunder_charge")
        cp = st.pop(ck, None)
        if cp:
            mult = float(cp)
    if mult != 1.0:
        ctx["mult"] = float(ctx.get("mult", 1.0) or 1.0) * mult
        ctx["tags"] = list(ctx.get("tags") or []) + [f"📈x{mult:.2f}"]


# ============================================================
# combo 系武器特效（M-W2s：novice_hunt_combo 暴击叠层 + combo_end 连段暴伤）
# ============================================================
# 旧语义（REFACTOR_v181P4_N9A_weapon_gap_plan.md §4.1，_we_executors 388-395 +
# battle.py 2586-2631）：
#   novice_hunt_combo（猎影之牙）：暴击命中 → stacks[novice_combo] +1（cap 5），
#     每层连击率 +8%——消费点在连击判定（直读叠层，非本执行器）
#   combo_end（夜枭双匕）：本刻连段 ≥3 时本次攻击暴伤 +40%（触发：被动判定）
# saintess_engine 表达：
#   - 生产段挂 crit 事件（暴击命中后）；叠层 cap/per_stack 数值权威 = 数据表
#     （novice_combo 无 STATE_EFFECTS 声明行 → cap 缺省读数据 max_stack）
#   - combo_end 的「本刻连段」= 连段资源当前层（effects[lian_duan].stacks，刺客
#     攻线命中计数）；「被动判定」= 本击暴击 → 挂 dmg_calc 钩子（ctx.is_crit 即
#     本击被动判定结果；saintess_engine 无旧 passive 点位，dmg_calc 语义最近且不误伤——
#     只在暴击且连段达标时乘入本次伤害，条件不满足 = 零效果零日志）。


@register_action("we_combo_stack")
def we_combo_stack(battle, caster, target, params, logs):
    """暴击叠层生产（proc_stack crit 事件——novice_hunt_combo 猎影之牙）：
    暴击命中 → effects[stack_key].stacks +1。cap = 数据表 max_stack 权威
    （该叠层不进 STATE_EFFECTS 声明表，state_def 无行时以数据 max_stack 封顶，
    再兜底 5）；每层 = 连击率 +per_stack（消费点=连击判定直读叠层，连击系统
    就绪后接消费；本动作管生产段 + 玩家可见叠层文案，与装备 desc 逐字一致）。"""
    owner = params.get("_owner") or caster
    if owner is None or not actor_alive(owner):
        return
    sk = params.get("stack_key") or params.get("key") or ""
    if not sk:
        return
    cap = int(params.get("max_stack") or 0)
    if cap <= 0:
        from saintess_engine.battle.state_effects import state_def
        try:
            cap = int((state_def(sk) or {}).get("cap") or 0)
        except Exception:
            cap = 0
    if cap <= 0:
        cap = 5  # 缺数据声明兜底（novice_combo 无状态表行，cap 恒走 max_stack）
    ef = owner.setdefault("effects", {})
    entry = ef.get(sk)
    if not isinstance(entry, dict):
        entry = ef[sk] = {}
    cur = int(entry.get("stacks", 0) or 0)
    entry["stacks"] = max(0, min(cap, cur + 1))
    n = entry["stacks"]
    pct = int(float(params.get("per_stack") or 0.08) * 100)
    logs.append(f"🎯 猎影：暴击叠层！（{n}/{cap} 层，每层连击率 +{pct}%）")


@register_action("we_combo_end")
def we_combo_end(battle, caster, target, params, logs):
    """连击终点（proc_passive_mult combo_end 夜枭双匕，dmg_calc 钩子）：
    本刻连段（effects[lian_duan].stacks——连段资源当前层）≥ combo_need 且本击
    暴击（_fire_ctx.is_crit）→ 本次攻击伤害 ×(1+crit_dmg)（暴伤 +40%）。
    条件任一不满足（连段 <combo_need / 未暴击）= 本次不触发（零效果零日志）。"""
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    owner = params.get("_owner") or caster
    if owner is None or not actor_alive(owner):
        return
    if not ctx.get("is_crit"):
        return  # 未暴击：本次攻击无暴击伤害可加成
    need = int(params.get("combo_need") or 3)
    cd = float(params.get("crit_dmg") or 0)
    if cd <= 0:
        return  # 缺字段 = 无此行为（读表零默认值铁律）
    ef = owner.get("effects") or {}
    entry = ef.get(params.get("combo_key") or "lian_duan")
    n = int(entry.get("stacks", 0) or 0) if isinstance(entry, dict) else 0
    if n < need:
        return  # 本刻连段不足：不触发
    ctx["mult"] = float(ctx.get("mult", 1.0) or 1.0) * (1.0 + cd)
    ctx["tags"] = list(ctx.get("tags") or []) + [f"💢连击终点x{1.0 + cd:.2f}"]
    logs.append(f"💢 连击终点：连段≥{need} 暴击，本次暴击伤害 +{int(cd * 100)}%！")


# ============================================================
# proc_special death_dance（缓伤池：受击收 35% → turn_start 结算 10%）
# ============================================================
# 旧语义（battle.py _post_hp_lethal 10955-10958 + _we_executors 871-895）：
#   battle_start  : eff[we_death_pool] = float(现值 or 0)（惰性建键）
#   受击          : eff[we_death_pool] += dmg × pool_pct(0.35)（dmg = 盾后实扣）
#   turn_start    : pool>0 → pay = max(1, int(pool×pay_pct(0.10)))
#                   hp = max(0, hp-pay); pool = max(0, pool-pay)
# 池存 owner.ext.we_proc[pool_key]（float；serialize 全量保留）。直接改 hp
# （自伤不走 landing——缓伤池结算不该被盾/减伤二次拦截；pay 只会 1 起扣不致死）。


@register_action("we_death_pool_add")
def we_death_pool_add(battle, caster, target, params, logs):
    """缓伤池收池（on_taken 事件）：pool += 承伤实值 × pool_pct。"""
    owner = params.get("_owner") or caster
    if owner is None:
        return
    pool_key = params.get("pool_key") or "we_death_pool"
    ctx = getattr(battle, "_fire_ctx", None) or {}
    dmg = float(ctx.get("dmg", 0) or 0)
    if dmg <= 0:
        return  # 无实伤不收池（护盾全吸收/免疫）
    pool_pct = float(params.get("pool_pct") or 0.35)
    st = owner.setdefault("ext", {}).setdefault("we_proc", {})
    st[pool_key] = float(st.get(pool_key, 0) or 0) + dmg * pool_pct
    # 不写日志——旧版收池静默（日志只在 turn_start 结算时）


@register_action("we_death_pool_pay")
def we_death_pool_pay(battle, caster, target, params, logs):
    """缓伤池结算（turn_start 事件）：pool>0 → pay = max(1, pool×pay_pct) 扣血递减。"""
    owner = params.get("_owner") or caster
    if owner is None or not actor_alive(owner):
        return
    pool_key = params.get("pool_key") or "we_death_pool"
    st = owner.setdefault("ext", {}).setdefault("we_proc", {})
    pool = float(st.get(pool_key, 0) or 0)
    if pool <= 0:
        return
    pay_pct = float(params.get("pay_pct") or 0.10)
    pay = max(1, int(pool * pay_pct))
    owner["hp"] = max(0, int(owner.get("hp", 0) or 0) - pay)
    st[pool_key] = max(0.0, pool - pay)
    logs.append(f"💀 死亡之舞：缓伤池结算，损失 {pay} 点生命！（剩余 {st[pool_key]:.0f}）")


# ============================================================
# N9A-2 act_done 通用广播监听（randuin_weary/ice_vein：敌行动叠减速层）
# ============================================================
# 事件语义（鱼鱼 2026-09-08 拍板）：act_done = 全员广播，任何阵营 actor 行动完成都
# fire（不带 ctx.actor 键 → subject=None 全员查声明）。监听者自己 if 敌我判断：
#   ctx["acted"] = 刚行动的 actor；owner 声明者查 hostile_sides(battle, owner.side)
#   是否包含 acted.side → 是才给 acted 叠层（state + stat_scale 负值折算减速）。

_ACT_DONE_SLOW_LOG = {
    "randuin_weary": "🛡️ 兰顿倦意：敌人速度 -{pct}%（{n}/{ms} 层）！",
    "ice_vein": "❄️ 冰脉寒流：敌人速度 -{pct}%（{n}/{ms} 层）！",
}


@register_action("we_act_done_slow")
def we_act_done_slow(battle, caster, target, params, logs):
    """敌对 actor 行动完成 → 给它叠减速层（act_done 广播监听）。"""
    owner = params.get("_owner") or caster
    if owner is None or not actor_alive(owner):
        return
    ctx = getattr(battle, "_fire_ctx", None) or {}
    acted = ctx.get("acted")
    if acted is None or not actor_alive(acted):
        return
    if acted is owner:
        return  # 自己行动不叠
    # 敌我判断（引擎零知识，装配层效果侧 if）：acted 是否 owner 敌对阵营
    try:
        from saintess_engine.battle.actors import hostile_sides
        own_side = owner.get("side") or ""
        acted_side = acted.get("side") or ""
        if acted_side not in hostile_sides(battle, own_side):
            return  # 非敌对（友方/中立）行动不响应
    except Exception:
        return  # 阵营判定失败不叠（安全）
    key = params.get("key") or ""
    ms = int(params.get("max_stack") or 3)
    sp = float(params.get("spd_down_pct") or 0.06)
    sk = params.get("stack_key") or key
    from saintess_engine.battle.state_effects import state_def
    cap = int((state_def(sk) or {}).get("cap") or ms)
    n = _add_stacks(acted, sk, 1, cap=cap)
    logs.append(_ACT_DONE_SLOW_LOG.get(
        key, "🌊 减速叠层！").format(pct=int(sp * 100 * n), n=n, ms=ms))


# ============================================================
# N9.7b affix 词条 on_hit 族扩展动作（bleed/armor_break/element/pierce/charge）
# ============================================================
# 带 chance 的命中词条在扩展动作层 roll（纯动词无 chance 概念）；读 _fire_ctx.dmg
# 做"本击百分比"类附加。affix 词条 = 通用伤害词条（非职业专属），装配层按 AFFIXES
# 表翻译后挂 hit（展开 attack_hit+skill_hit）。

_AFFIX_HIT_LOG = {
    "bleed": "🩸 流血！{tgt} 伤口裂开，将持续失血！",
    "armor_break": "🛡️ 破甲！{tgt} 防御下降 {pct}%！",
}


@register_action("we_affix_dot")
def we_affix_dot(battle, caster, target, params, logs):
    """affix 命中流血（bleed）：chance → 目标挂 affix_bleed state 层（每刻 pct 生命，
    限时 turns 跳，cap 由 STATE_EFFECTS 声明）。"""
    tgt = _hit_target(battle, target)
    if not tgt:
        return
    if not _roll(params.get("chance")):
        return
    sk = params.get("state_key") or params.get("dot_key")
    if not sk:
        return
    from saintess_engine.battle.state_effects import state_def
    cap = int((state_def(sk) or {}).get("cap") or 3)
    n = _add_stacks(tgt, sk, int(params.get("stacks") or 1), cap=cap,
                    battle=battle, caster=caster)   # v181 批D：施法者快照
    logs.append(_AFFIX_HIT_LOG.get(params.get("key"), "🩸 目标流血了！").format(
        tgt=tgt.get("name", "目标")))
    return n


@register_action("we_affix_defdown")
def we_affix_defdown(battle, caster, target, params, logs):
    """affix 破甲（armor_break）：chance → 目标 def ×（1-pct）buff 持续刻。"""
    tgt = _hit_target(battle, target)
    if not tgt:
        return
    if not _roll(params.get("chance")):
        return
    from saintess_engine.battle.effects import act_apply
    act_apply(battle, caster, tgt,
             {"type": "apply", "key": "def_down", "stat": "def", "op": "mul",
              "mult": 1.0 - float(params.get("pct") or 0.15),
              "turns": int(params.get("turns") or 2), "on": "target"}, logs)
    logs.append(_AFFIX_HIT_LOG.get(params.get("key"), "🛡️ 目标防御下降！").format(
        tgt=tgt.get("name", "目标"),
        pct=int(float(params.get("pct") or 0.15) * 100)))


@register_action("we_affix_element")
def we_affix_element(battle, caster, target, params, logs):
    """affix 元素附加（element_fire/ice/thunder）：本击 dmg × pct 附加元素伤害。
    - fire：恒触发
    - ice：恒触发 + 减速（敌速减半 2 刻）
    - thunder：恒触发 + chance 追加 thunder_bonus 小爆
    附加伤害走 landing.deal_damage（等级压制/护盾统一收口）。
    """
    tgt = _hit_target(battle, target)
    if not tgt:
        return
    ctx = getattr(battle, "_fire_ctx", None) or {}
    base = float(ctx.get("dmg", 0) or 0)
    if base <= 0:
        return
    key = params.get("key") or ""
    element = params.get("element") or "fire"
    pct = float(params.get("pct") or 0.05)
    dmg = max(1, int(base * pct))
    from saintess_engine.battle.landing import deal_damage
    deal_damage(battle, caster, tgt, dmg, logs)
    _tag = {"fire": "🔥", "ice": "❄️", "thunder": "⚡"}.get(element, "✨")
    logs.append(f"{_tag} {params.get('name') or '元素附加'}！造成 {dmg} 点{ {'fire':'火','ice':'冰','thunder':'雷'}.get(element, element) }属性伤害！")
    # ice 附带减速（spd_down mult = 减幅语义：slow 0.10 → spd×0.9）
    if element == "ice" and params.get("slow") is not None:
        from saintess_engine.battle.effects import act_apply
        act_apply(battle, caster, tgt,
                 {"type": "apply", "key": "spd_down", "stat": "spd", "op": "mul",
                  "mult": float(params.get("slow") or 0.10),
                  "turns": int(params.get("slow_turns") or 2), "on": "target"}, logs)
    # thunder 概率小爆
    if element == "thunder" and _roll(params.get("chance")):
        sd = max(1, int(base * float(params.get("thunder_bonus") or 0.20)))
        deal_damage(battle, caster, tgt, sd, logs)
        logs.append(f"⚡⚡ 感电连跳！追加 {sd} 点雷系伤害！")


@register_action("we_affix_bonus")
def we_affix_bonus(battle, caster, target, params, logs):
    """affix 追加伤害（combo/charge/pierce）：chance → 追加 dmg×pct（本击）或
    atk×pct（无视防御，pierce 语义）。mode 分派：
    - dmg_pct（combo/charge）：本击 dmg × pct 追加
    - atk_true（pierce）：玩家 atk × pct 无视防御（真伤）
    """
    tgt = _hit_target(battle, target)
    if not tgt:
        return
    if not _roll(params.get("chance")):
        return
    mode = params.get("mode") or "dmg_pct"
    dmg = 0
    if mode == "atk_true":
        from saintess_engine.battle.landing import deal_damage as _dd2
        from saintess_engine.battle.stats import actor_stats as _as2
        st = _as2(battle, caster) or {}
        dmg = max(1, int(float(st.get("atk", 0) or 0) * float(params.get("atk_pct") or 0.60)))
        _dd2(battle, caster, tgt, dmg, logs)
    else:
        ctx = getattr(battle, "_fire_ctx", None) or {}
        base = float(ctx.get("dmg", 0) or 0)
        if base <= 0:
            return
        from saintess_engine.battle.landing import deal_damage as _dd3
        dmg = max(1, int(base * float(params.get("pct") or 0.50)))
        _dd3(battle, caster, tgt, dmg, logs)
    tag = params.get("tag") or "⚡"
    name = params.get("name") or "追加"
    logs.append(f"{tag} {name}！对【{tgt.get('name', '敌人')}】追加 {dmg} 点伤害！")


# ============================================================
# N9.7c affix on_taken 族（counter/tenacity_cc）+ dmg_reduce 减伤
# ============================================================
# counter：受击 20% 反击攻击方 atk×60%（on_taken，攻击方在 ctx.source）
# tenacity_cc：受击 20% 免疫/清除自身负面（spd_down/atk_down/def_down）+ 回 3% maxhp
# dmg_reduce：常驻全减伤 3%（taken_calc 乘区——装配层直接挂 we_taken_mult_cond）

_AFFIX_TAKEN_LOG = {
    "counter": "⚔️ 反击！对【{tgt}】造成 {dmg} 点伤害！",
    "tenacity_cc": "💪 坚韧！免疫了负面效果，回复 {heal} 点生命",
}


@register_action("we_affix_counter")
def we_affix_counter(battle, caster, target, params, logs):
    """affix 反击（counter）：受击后 chance → 按玩家 atk×atk_pct 反击攻击方。"""
    owner = params.get("_owner") or caster
    if owner is None or not actor_alive(owner):
        return
    ctx = getattr(battle, "_fire_ctx", None) or {}
    attacker = ctx.get("source")  # on_taken 攻击方
    if attacker is None or not actor_alive(attacker):
        return
    if not _roll(params.get("chance")):
        return
    from saintess_engine.battle.landing import deal_damage
    from saintess_engine.battle.stats import actor_stats as _as
    st = _as(battle, owner) or {}
    dmg = max(1, int(float(st.get("atk", 0) or 0) * float(params.get("atk_pct") or 0.60)))
    deal_damage(battle, owner, attacker, dmg, logs)
    logs.append(_AFFIX_TAKEN_LOG.get(params.get("key"), "⚔️ 反击！").format(
        tgt=attacker.get("name", "敌人"), dmg=dmg))


@register_action("we_affix_tenacity")
def we_affix_tenacity(battle, caster, target, params, logs):
    """affix 坚韧（tenacity_cc）：受击后 chance → 免疫/清除自身负面 + 回 3% maxhp。
    负面 = effects 中带减益语义的条目（op=reduce/mul<1 的属性减成）。"""
    owner = params.get("_owner") or caster
    if owner is None or not actor_alive(owner):
        return
    if not _roll(params.get("chance")):
        return
    bf = owner.get("effects") or {}
    neg = [k for k, e in bf.items() if isinstance(e, dict) and e.get("stat")
           and ((e.get("op") == "reduce") or
                (e.get("op") == "mul" and float(e.get("mult", 1) or 1) < 1.0))]
    if not neg:
        return
    import random as _r
    bf.pop(_r.choice(neg), None)
    from saintess_engine.battle.landing import heal_actor
    heal = max(1, int(owner.get("max_hp", 1) * float(params.get("heal_pct") or 0.03)))
    heal_actor(battle, owner, heal, logs)
    logs.append(_AFFIX_TAKEN_LOG.get(params.get("key"), "💪 坚韧！").format(heal=heal))


# ============================================================
# N9.7e affix 资源 gain 型词条（R4：effect {res, gain, on} → 事件时机叠资源）
# ============================================================
# 语义：词条在装配层翻译成「事件 → 给 owner.effects[res].stacks += gain」；
# 事件全选 subject=owner 自己（或 battle_start 一次性广播）的点位 → 天然不重复。
# 动作参数化零 affix 硬编码：res/gain/chance/kind/label 全由装配层从 AFFIXES
# 表翻译写入（tiers 档位已在装配层折算）。cap clamp 查 EFFECT_RULES[res].cap
# （_add_stacks 缺省查 state_def；rage/chi/energy/faith/cp/element 均有声明）。


@register_action("we_affix_res_gain")
def we_affix_res_gain(battle, caster, target, params, logs):
    """affix 资源 gain：owner.effects[res].stacks += gain（EFFECT_RULES cap clamp）。

    - res    资源 key（rage/energy/faith/cp/chi/element）
    - gain   加值（tiers 档位已由装配层折算）
    - chance 概率（crit_return 等带概率词条；缺省 None = 恒触发）
    - kind   技能类别过滤（act_cast 事件用：kind=治疗/增益 才触发——warcry_echo
             增益技 / holy_echo 治疗施放 折中挂点）
    - not_basic 排除普攻施放（on_cast 词条：saintess_engine 普攻经 do_skill 也 fire
             act_cast 且 info._basic=True——元素/奥术技能施放不该吃普攻）
    - cond_hp_lt 血量门槛（ember_brand 残血灼薪：owner.hp/max_hp < cond_hp_lt 才回；
             缺省 None = 无条件）
    - label/icon 日志文案（装配层读 AFFIXES.name 写入，动作零硬编码）
    """
    owner = params.get("_owner") or caster
    if owner is None or not actor_alive(owner):
        return
    ctx = getattr(battle, "_fire_ctx", None) or {}
    info = ctx.get("info") or {}
    kind = params.get("kind")
    if kind and (info.get("kind") or "") != kind:
        return  # 技能类别过滤不命中（buff_skill/治疗词条只认对应 kind 技能行动）
    if params.get("not_basic") and info.get("_basic"):
        return  # on_cast 语义 = 技能施放，普攻（basic 经 do_skill）不触发
    if not _roll(params.get("chance")):
        return
    # v181.M-affixtail cond 门槛（swift_tailwind 疾风余韵：data cond=energy_ge_80
    # 由装配层折算成 cond_key/cond_ge 参数——当前不足门槛 → 静默跳过不回复；
    # 参数缺省 = 无条件，旧词条语义零变化）
    ck = params.get("cond_key")
    if ck and params.get("cond_ge") is not None:
        _e = (owner.get("effects") or {}).get(ck)
        _cur = float(_e.get("stacks", 0) or 0) if isinstance(_e, dict) else 0.0
        if _cur < float(params.get("cond_ge") or 0):
            return
    # D3 cond 门槛（ember_brand 残血灼薪：data cond=hp_lt_30 由装配层折算成 cond_hp_lt
    # 参数——当前血量不在阈值内 → 静默跳过不回复；参数缺省 = 无条件，旧词条语义零变化。
    # 同门先例：class_mech `passive_low_hp_core` 读 hp_lt 判残血）
    hl = params.get("cond_hp_lt")
    if hl is not None and float(hl) > 0:
        _mhp = float(owner.get("max_hp", 1) or 1)
        if float(owner.get("hp", 0) or 0) >= _mhp * float(hl):
            return
    res = params.get("res") or ""
    gain = int(params.get("gain") or 0)
    if not res or gain <= 0:
        return
    n = _add_stacks(owner, res, gain)
    if n <= 0:
        return
    # cap 展示走引擎 _cap_of（与 clamp 收敛点同源——上限词条抬 cap 后日志同口径）
    from saintess_engine.battle.effects import cap_of
    cap = cap_of(owner, res)
    cap_txt = f"/{cap}" if cap < 999999 else ""
    logs.append(f"{params.get('icon') or '✦'} {params.get('label') or res} "
                f"+{gain}（{n}{cap_txt}）")


# ============================================================
# N9.7 收尾（m_affixtail）：purify 净化（命中驱散敌方增益 + 圣洁削弱）
# ============================================================
# 语义（旧 affix_effects._h_purify，v135 增强版）：命中 15%（数据表 chance）驱散
# 目标 1 层增益（judgment_chain 专属 25% 驱散 2 层——传说词条，同族语义后续接线）；
# 驱散成功 → 圣洁：敌人攻击 -10%（1 刻）。
# saintess_engine buffs 并入 effects 无旧 mon_ 前缀概念 → N9_7 定稿的「增益」判定（查
# EFFECT_RULES + 条目内嵌快照，引擎零名词）：
#   - 面板快照型：op=mul 且 mult>1 / op=add 且 mult>0（正增益；op 缺省按 mul）
#   - 叠层声明型：stat_scale 正系数（stacks>0 才有折算）
#   - 周期自愈/回能型：period dir∈(heal/mana/gain)
#   - value 型减伤（reduce）、负标记（negative）、控制（mode）、DOT 不属增益
# 参数（装配层从 AFFIXES 表翻译）：purge_n（effect.purge）/holy_weaken_pct
# （effect.holy_weaken）/chance（表 chance）。动作零词条硬编码。


def _target_gain_keys(actor: dict) -> list:
    """actor.effects 中按上述判据为「增益」的 key 列表（有序去重，无则 []）。"""
    from saintess_engine.battle.state_effects import all_state_effects
    ef = (actor or {}).get("effects") or {}
    if not isinstance(ef, dict) or not ef:
        return []
    table = all_state_effects()
    out = []
    for key, entry in ef.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("mode"):
            continue  # 控制条目（stun/freeze…）不是增益
        cfg = table.get(key) or {}
        if cfg.get("negative"):
            continue  # 显式负效果（虚弱/易伤类）不入驱散候选
        # ① 面板快照（条目内嵌 stat/op/mult 或声明 panel）→ 正增益判定
        stat = entry.get("stat") or (cfg.get("panel") or {}).get("stat")
        mult = entry.get("mult")
        if mult is None:
            mult = (cfg.get("panel") or {}).get("mult")
        if stat and mult is not None:
            op = entry.get("op") or (cfg.get("panel") or {}).get("op") or "mul"
            try:
                mv = float(mult)
            except Exception:
                mv = 0.0
            if (str(op) == "add" and mv > 0.0) or (str(op) != "add" and mv > 1.0):
                out.append(key)
                continue
        # ② 叠层 stat_scale 正系数（每层增益；stacks>0）
        n = int(entry.get("stacks", 0) or 0)
        scale = cfg.get("stat_scale") or {}
        if n > 0 and scale and all(
                isinstance(v, (int, float)) and float(v) >= 0 for v in scale.values())\
                and any(float(v) > 0 for v in scale.values()):
            out.append(key)
            continue
        # ③ 周期自愈/回能（dir=heal/mana/gain 的 period 声明）
        period = cfg.get("period")
        if isinstance(period, dict) and str(period.get("dir") or "") in ("heal", "mana", "gain"):
            out.append(key)
    return out


@register_action("we_affix_purify")
def we_affix_purify(battle, caster, target, params, logs):
    """affix 净化（purify）：命中 chance → 驱散目标 purge_n 层增益；成功附加圣洁
    （敌攻 -holy_weaken_pct × 1 刻，面板 atk mul 快照——engine act_apply 语义）。"""
    tgt = _hit_target(battle, target)
    if not tgt or not actor_alive(tgt):
        return
    if not _roll(params.get("chance")):
        return
    purge_n = int(params.get("purge_n") or 0)
    if purge_n <= 0:
        return
    gains = _target_gain_keys(tgt)
    if not gains:
        return
    removed = 0
    for _ in range(purge_n):
        if not gains:
            break
        k = gains.pop(random.randrange(len(gains)))
        (tgt.get("effects") or {}).pop(k, None)
        removed += 1
    if removed <= 0:
        return
    logs.append(f"✨ 净化！驱散了【{tgt.get('name', '目标')}】的 {removed} 层增益！")
    wk = float(params.get("holy_weaken_pct") or 0)
    if wk > 0:
        from saintess_engine.battle.effects import act_apply
        act_apply(battle, caster, tgt,
                  {"type": "apply", "key": "holy_weaken", "stat": "atk", "op": "mul",
                   "mult": 1.0 - wk, "turns": 1, "on": "target"}, logs)
        logs.append("😇 圣洁之力！净化后敌人攻击下降 "
                    f"{int(wk * 100)}%（1 刻）！")


# ★ B10-L1（2026-09-13）**逐字端口回填**：下面这一段（banner + `_INSTALLED` +
#   `ensure_registered()`）抄自游戏仓 `game/services/battle_we_procs.py:1481-1494`，
#   与真源**逐字相同**（函数体/文案/注释一字未改）。
#   背景：D2 搬运时按「import 即注册」口径删掉了它；B10 把宿主 `battle_we_procs.py`
#   薄壳化后，宿主仍按名调用 `ensure_registered()`（宿主 `battle_equip_proc` 旧入口 /
#   本包 `equip.install_ext_actions`）——该语义必须有唯一归宿，故原样搬回包内。
#   行为零变化：本函数自身不注册动作（注册由上面的模块级装饰器在 import 时完成），
#   只置幂等标记；`True/False` 语义与真源一致。
# ============================================================
# 注册入口（装配层 install_ext_actions 调，幂等）
# ============================================================

_INSTALLED = False


def ensure_registered() -> None:
    """注册全部族扩展动作（battle_equip_proc.apply_to_actor 前调一次）。"""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    # 装饰器已随模块 import 注册（register_action 模块级执行）——本函数仅做幂等标记
