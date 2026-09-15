# -*- coding: utf-8 -*-
"""《奥兰迪亚》技能条件乘区 —— cond_procs（P4-D2 搬运物，逐字保真）。

真源：游戏仓 `C:/Users/yuyu/qqbot/data/plugins/dragonfall/game/services/battle_cond_procs.py`
      **`:21-153`**（谓词表 `COND_PREDICATES` + 5 个谓词 + 1 个 `@register_action` 动作；
      真源共 180 行）。
本文件 = 真源 `:21-153` 的**逐字拷贝**：函数体、数值、`logs.append` 文案、注释一字未改
（唯一函数内改动 = 1 行 import 拆成 2 行，见下；对拍见 `overnight/d2_misc_verify.py` A4）。

动作清单（1 个）
  :120   `skill_cond_mult`  (def skill_cond_mult_act → 本文件 def :133)
谓词表（真源模块级，逐字抄）：`_DEBUFF_KEYS`(`:26`) / `_DOT_KEYS`(`:28`) /
`_MELODY_BUFF_KINDS`(`:30`) / `COND_PREDICATES`(`:32`) / `register_cond`(`:35`) / `_spd_of`(`:43`) +
5 个谓词：`player_first`(`:54`) / `enemy_debuff`(`:60`) / `enemy_broken`(`:78`) /
`melody_buff`(`:97`) / `melody_stacks`(`:110`)。

结构改写清单（只有 2 类，零行为变化）
1. **去装配入口**：删真源 `:156-180 apply_cond_procs(actor)`（装配链归
   `content/apply.py`，P4 设计稿 §二）。
2. **技能表相对 import → 包内来源**（唯一一处）：真源 `:144`
   `from ..content_rules.skills import skill_info, skill_level_of`
   → `from ..apply import _SKILL_LOOKUP as _PKG_SKILLS, skill_level_of` +
     `skill_info = _PKG_SKILLS.skill_info`。
   理由：包内没有 `content_rules/` 命名空间；技能表只有一处权威实现 =
   `content/apply.py:_SkillTable`（读包内 `content/data/skills.json`，签名
   `skill_info(class_name, skill_key)` 与真源 `game/content_rules/skills.py:104` **同形**；
   `skill_level_of` 是 apply.py 的模块级函数，签名同真源 `skills.py:209`）。
   **惰性 import 位置不变**（仍在函数体内，与真源同点）→ 不与 `apply.py` 形成导入环。
   其余 import（`:23` register_action、`:47` `from saintess_engine import stats as S`）一字未动
   （`saintess_engine.stats` 在框架仓与游戏仓子模块里**都不存在** → 真源 `_spd_of` 实际一直走
   `except` 分支读 `actor["spd"]`；逐字搬运 = 行为一致，见 `overnight/d2-misc_procs.md` 备注）。
"""
from __future__ import annotations

from saintess_engine.battle.effects import register_action

# 敌方减益键（控制/属性降）；DOT/印记类走 effects 层数判定
_DEBUFF_KEYS = ("def_down", "spd_down", "mon_atk_down", "atk_down",
                "stun", "freeze", "silence")
_DOT_KEYS = ("poison", "burn", "bleed", "mark")
# 旋律增益系（咏叹调 desc「当前旋律为增益系时 ×1.3」）
_MELODY_BUFF_KINDS = ("atk", "def", "spd", "atk_matk", "all")

COND_PREDICATES: dict = {}


def register_cond(key):
    """条件类型注册（加类型 = 加一行；未注册 type 静默不生效）。"""
    def deco(fn):
        COND_PREDICATES[key] = fn
        return fn
    return deco


def _spd_of(battle, actor) -> float:
    if not isinstance(actor, dict):
        return 0.0
    try:
        from saintess_engine import stats as S
        st = S.actor_stats(battle, actor) or {}
        return float(st.get("spd", 0) or 0)
    except Exception:
        return float(actor.get("spd", 0) or 0)


@register_cond("player_first")
def _p_player_first(battle, actor, target, cond) -> bool:
    """先手：速度高于目标（v2.0）。"""
    return _spd_of(battle, actor) > _spd_of(battle, target)


@register_cond("enemy_debuff")
def _p_enemy_debuff(battle, actor, target, cond) -> bool:
    """敌方有减益（控制/属性降 + 目标级 DOT/印记层）。"""
    if not isinstance(target, dict):
        return False
    ef = target.get("effects") or {}
    if any(k in ef for k in _DEBUFF_KEYS):
        return True
    for k in _DOT_KEYS:
        e = ef.get(k)
        if isinstance(e, dict) and int(e.get("stacks", 0) or 0) > 0:
            return True
        if e:  # 无 stacks 结构的条目存在即算减益（控制型）
            return True
    deb = target.get("debuffs") or {}
    return any(int((deb.get(k) or {}).get("n", 0) or 0) > 0 for k in _DOT_KEYS)


@register_cond("enemy_broken")
def _p_enemy_broken(battle, actor, target, cond) -> bool:
    """敌方被破防/震慑中（破绽条触发态）——与 bar_trigger 后状态同源。

    条状态载体 = 目标 effects[BAR_STATE_PREFIX+shaken]；读取前先结算到当刻
    （衰减时间制：不结算会读到过期值）。
    """
    if not isinstance(target, dict):
        return False
    from saintess_engine.gauge import bar_settle, bar_effect_key
    _now = float(getattr(battle, "_now", 0.0) or 0.0)
    bar_settle(target, "shaken", _now)
    bs = (target.get("effects") or {}).get(bar_effect_key("shaken"))
    if not isinstance(bs, dict):
        return False
    return (int(bs.get("trigger_count", 0) or 0) > 0
            and float(bs.get("immune_until", 0.0) or 0.0) > _now)


@register_cond("melody_buff")
def _p_melody_buff(battle, actor, target, cond) -> bool:
    """施法者当前旋律为增益系（读 effects.melody_state.kind）。

    注意：旧 battle_conds 读 `battle._melody["kind"]`（旧引擎载体，saintess_engine 无写入方）；
    saintess_engine 真实载体 = 施法者 `effects["melody_state"]`（class_mech_proc.class_melody_act 写）。
    """
    if not isinstance(actor, dict):
        return False
    st = (actor.get("effects") or {}).get("melody_state") or {}
    return st.get("kind") in _MELODY_BUFF_KINDS


@register_cond("melody_stacks")
def _p_melody_stacks(battle, actor, target, cond) -> bool:
    """施法者旋律强度 ≥ stacks（旧读 `_melody["stack"]`，saintess_engine 实键为 `stacks`）。"""
    if not isinstance(actor, dict):
        return False
    st = (actor.get("effects") or {}).get("melody_state") or {}
    need = int(cond.get("stacks", 4) or 4)
    return int(st.get("stacks", 0) or 0) >= need


@register_action("skill_cond_mult")
def skill_cond_mult_act(battle, caster, target, params, logs):
    """dmg_calc / heal_calc：技能 cond 条件倍率 → 累乘 battle._fire_ctx["mult"]。"""
    ctx = getattr(battle, "_fire_ctx", None)
    if not isinstance(ctx, dict):
        return
    info = ctx.get("info") or {}
    cond = info.get("cond")
    if not isinstance(cond, dict):
        return  # 无字段 = 不启用
    fn = COND_PREDICATES.get(cond.get("type"))
    if fn is None:
        return  # 未注册类型：静默不生效（不给断言/不崩）
    actor = ctx.get("actor") or caster
    tgt = ctx.get("target")
    if tgt is None:
        tgt = target
    try:
        if not fn(battle, actor, tgt, cond):
            return
    except Exception:
        return  # 判定异常不阻断战斗
    try:
        from saintess_engine.battle.formulas import skill_cond_mult
        from ..apply import _SKILL_LOOKUP as _PKG_SKILLS, skill_level_of
        skill_info = _PKG_SKILLS.skill_info
        name = info.get("name") or ""
        lv = skill_level_of(actor, name) if (actor or {}).get("class_name") else 1
        mult = float(skill_cond_mult(cond, max(1, int(lv or 1)), info) or 1.0)
    except Exception:
        mult = float(cond.get("mult", 1.0) or 1.0)
    if mult == 1.0:
        return
    ctx["mult"] = float(ctx.get("mult", 1.0) or 1.0) * mult
    logs.append(f"✨ 条件达成【{cond.get('type')}】×{mult:g}")


__all__ = ["skill_cond_mult_act", "COND_PREDICATES", "register_cond", "apply_cond_procs"]


# ============================================================
# 装配入口（P4-D2b 追加：真源 `battle_cond_procs.py:156-180 apply_cond_procs`）
#   逐字搬运，唯一改动 = 1 处 import 路径（其余函数体/数值/注释/文案一字未改）：
#     · 真源 `from ..content_rules.skills import skill_info, skill_level_of`
#       → 包内 `from ..apply import _SKILL_LOOKUP as _PKG_SKILLS, skill_level_of` +
#         `skill_info = _PKG_SKILLS.skill_info`
#       （与同文件动作段 :156-157 的改写**逐字一致**；`skill_cond_mult` 那行是
#         真源里的未使用 import，原样保留不删）
#   本块**追加在 `__all__` 之后** → 既有逐字对拍（`d2_misc_verify.py` A4）不受影响。
# ============================================================
def apply_cond_procs(actor: dict) -> None:
    """装配：扫已学技能 → 存在带 cond 的技能才挂 dmg_calc/heal_calc 条件乘区。"""
    cn = actor.get("class_name") or ""
    names = actor.get("learned_skills") or []
    if not cn or not names:
        return
    from saintess_engine.battle.formulas import skill_cond_mult
    from ..apply import _SKILL_LOOKUP as _PKG_SKILLS, skill_level_of
    skill_info = _PKG_SKILLS.skill_info
    has_cond = False
    for s in names:
        try:
            info = skill_info(cn, s)
        except Exception:
            info = None
        if info and isinstance(info.get("cond"), dict):
            has_cond = True
            break
    if not has_cond:
        return
    trig = actor.setdefault("triggers", {})
    for ev in ("dmg_calc", "heal_calc"):
        lst = trig.setdefault(ev, [])
        if not any(isinstance(e, dict) and e.get("action") == "skill_cond_mult"
                   for e in lst):
            lst.append({"action": "skill_cond_mult"})
