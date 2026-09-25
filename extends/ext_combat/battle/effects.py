# -*- coding: utf-8 -*-
"""v181.P4 saintess_engine 引擎——效果执行器（effects.py，动词版）。

框架/配置分离（鱼鱼拍板：换一套配置 = 新游戏）：
- 引擎只提供【动词执行器】——能力，不含任何游戏内容判断
- 游戏【名词效果】→ 动词动作序列 的映射在 config 挂载的游戏规则里
  （game/data/battle_rules.py EFFECT_ACTIONS）
- 名词效果先经配置翻译成动词动作，再执行

动词（引擎注册，全部通用；V4 收敛 8 个）：
  apply     : 统一效果写入（写 actor.effects[key]，按参数分流：mode=控制 /
              op=add|set=叠层 / value=值型 / stat+mult=增益快照 / hit=出手消费 / 纯状态）
  consume   : 主动扣叠层（effects[key].stacks -= amount）
  shield    : 护盾（独立 shields 容器，value/halve 由数据给）
  cleanse   : 清减益（DOT/标记/控制，遍历 effects 查表）
  heal / damage / interrupt : 落地接口（landing）薄包装
旧动词 control/buff/state_add/state_spend/state_set 已并入 apply/consume（V4 收敛，
装配层/EFFECT_ACTIONS 同步改发 apply/consume——勿再引用旧注册名）。

签名：fn(battle, caster, target, params, logs)
  caster = 施法者 actor；target = 作用目标；params = 动作参数
"""
from __future__ import annotations

from typing import Callable, Optional

from .state_effects import state_def
from . import traits                    # 内容侧标签判定（引擎不认标签叫什么 · 审计 E3）
from .diagnostics import diag as _diag   # 阶段/钩子出错的诊断通道（P-44）
from saintess_engine.text import render_via

# ============================================================
# stacks 数值口径（v181.M-R2e B3：effects float 通用层）
# ============================================================
# 引擎零语义：stacks 允许 float（增量能力：内容侧每刻 -0.7 这类小数衰减），
# 但 int 资源保持 int 观感——写回统一走 _norm_stack 归一（整值落 int）。
# 消费/展示侧审计：读 stacks 的点用 float() 保真或 int() floor（见各处注释）。


def _fmt_stack(v):
    """stacks 文案/日志显示：整值去 .0（float 为增量能力，玩家整数观感）。"""
    try:
        f = float(v)
    except Exception as _e:
        _diag(None, "_fmt_stack", _e)          # 审计 P-44 余量：不再静默（行为不变）
        return v
    return int(f) if f.is_integer() else f


def _norm_stack(v):
    """stacks 写回归一：整值 → int（int 资源保持 int）；小数 → round 6 位（清 0.7 衰减
    二进制定点尾差，如 10-0.7 → 9.3）。"""
    try:
        f = float(v)
    except Exception as _e:
        _diag(None, "_norm_stack", _e)          # 审计 P-44 余量：不再静默（行为不变）
        return v
    if f.is_integer():
        return int(f)
    return round(f, 6)


def _cap_of(actor, key: str) -> int:
    """叠层 cap 读取收敛点（v181.M-R2e 方案 A：affix 动态 cap；v181.M-bonus 分域）。

    所有读 EFFECT_RULES[key].cap 做 clamp 的引擎点（effects 叠层 clamp /
    schedule period gain clamp / 装配层渠道 gain clamp）统一走本函数：
    cap = EFFECT_RULES 基础 cap + actor.bonus.cap[key]（纯 flat int 增量，
    bonus 容器平行哲学——引擎零语义，装配层开战写入）。actor 缺省/无
    bonus.cap → 基础 cap。基础 cap 无声明（0）→ 999999 不设限（增量无意义）。
    """
    base = int(state_def(key).get("cap") or 0) or 999999
    if base >= 999999:
        return base
    try:
        cb = ((actor or {}).get("bonus") or {}).get("cap") or {}
        bonus = int(cb.get(key, 0) or 0)
    except Exception as _e:
        _diag(None, "_cap_of", _e)          # 审计 P-44 余量：不再静默（行为不变）
        bonus = 0
    return base + max(0, bonus)


# S2 公开 API 面（docs/archive/ENGINE_CONTENT_SPLIT_PLAN.md §5）：私有符号提升为公开，
# **旧下划线名保留为别名**（内容层/测试仍在用，不得删）。
norm_stack = _norm_stack
cap_of = _cap_of

# ============================================================
# 动词注册表
# ============================================================

ACTION_HANDLERS: dict = {}

# 签名：fn(battle, caster, target, params, logs)
ActionHandler = Callable


def register_action(key):
    """装饰器：注册动词执行器。

    注册是**覆盖式**（同名后注册者胜）—— 包在开发/热重载时会反复 import，覆盖是有意的。
    但"覆盖"也意味着**写错名字不会报错**：你会静默多出一个谁也没引用的动作，而声明表引用的
    那个动作在 `fire()` 里被静默跳过（`effects.py` 的 `ACTION_HANDLERS.get(...)` 不命中就 return）。
    所以这里把「覆盖」记进 `REGISTERED_OVERWRITES`（只做诊断、不改行为），
    另提供 `action_names()` / `missing_actions(declared)` 给加载器与门禁做**启动自检**：
    「声明里引用的动作都注册了吗」应该是加载期能回答的问题，而不是等它静默不触发。
    """
    def deco(fn):
        if key in ACTION_HANDLERS:
            REGISTERED_OVERWRITES.append(str(key))
        ACTION_HANDLERS[key] = fn
        return fn
    return deco


# 被重复注册（覆盖）过的动作名，按注册顺序追加（诊断用；见 register_action 的说明）
REGISTERED_OVERWRITES: list = []


def action_names() -> list:
    """已注册的动作名（含引擎内置 8 个），排序。"""
    return sorted(ACTION_HANDLERS)


def missing_actions(declared) -> list:
    """`declared`（声明表里引用的动作名，可迭代）里**没有注册实现**的那些，排序返回。

    用法（加载器/门禁）：为空 = 「声明了没实现」不存在；非空 = 列出来的名字在战斗中会被静默跳过。
    """
    have = set(ACTION_HANDLERS)
    return sorted({str(n) for n in (declared or ()) if str(n) not in have})


# ============================================================
# 分发
# ============================================================

def resolve_actions(name: str) -> list:
    """名词效果名 → 动词动作列表（查游戏配置 EFFECT_ACTIONS）。

    找不到映射时按"本身就是动词"处理（动作名直通执行器）。
    """
    from .game_config import get_effect_actions
    table = get_effect_actions()
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
    import random as _rr
    for eff in effects:
        if not isinstance(eff, dict):
            continue
        etype = eff.get("type") or eff.get("action")
        if not etype:
            continue
        # 通用概率 roll（eff.chance：技能 mech_chance / 装配层概率效果统一消费；
        # None = 恒触发零影响）
        _ch = eff.get("chance")
        if _ch is not None:
            try:
                if _rr.random() >= float(_ch):
                    continue
            except Exception as _e:
                _diag(battle, "apply_effects", _e)          # 审计 P-44：不再静默（行为不变）
                pass
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
                except Exception as _e:
                    _diag(battle, "apply_effects", _e)   # 审计 P-44：不再静默（行为不变）
                    # 单个 handler 异常不阻断后续（引擎容错）
                    continue


# ============================================================
# 兼容层：技能 mech/effect 字段 → 动作/状态列表
# ============================================================

def effects_from_skill(info: dict, lv: int, caster_side_is_player: bool = True) -> list:
    """从技能 dict 的 mech/effect 字段生成统一 effects 列表（迁移期兼容层）。

    mech 分派（查 state_effects 声明表，引擎不硬编码 key）：
    - key 在 state 规则表（含 on=target/dot 声明）→ 通用 apply(op=add) 动作
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
    """单个 mech key → effect dict（查 state 规则表分派）。

    分派判据（V5② 精确化——防控制/增益 key 被当叠层资源劫持）：
    - cfg 是「叠层资源型」（有 stat_scale/debuff_scale/period/dot/on_threshold/
      guard_hp_pct 数值字段，或 cap>1 纯计数）→ apply op=add 叠层（层数=mech_val）
    - cfg 仅效果声明（consume/panel/tag/cleanse 等，无叠层数值）→ 非叠层资源，
      保留名词 type 由 EFFECT_ACTIONS 翻译（控制走 mode 语义，与入表前行为一致）
    - cfg 空（控制/盾/未入表名词）→ 名词路径（同现状）
    """
    cfg = state_def(mech)
    if _is_stack_resource(cfg):
        on_target = bool(cfg.get("on") == "target")
        return {"type": "apply", "op": "add", "key": mech, "amount": mval,
                "on": "target" if on_target else "caster",
                "info": info}
    # 名词（控制/盾/效果型）→ 保留 type，由 EFFECT_ACTIONS 配置翻译
    _eff = {"type": mech, "stacks": mval, "mech": mech, "info": info}
    # 技能显式 cc_turns 才带 turns（覆盖 EFFECT_ACTIONS 默认刻数）；缺省不写
    # turns —— 否则恒 turns=0 覆盖默认致控制 0 刻不施加（盾击·誓"眩晕 1 刻"bug）
    _ct = int(info.get("cc_turns", 0) or 0)
    if _ct > 0:
        _eff["turns"] = _ct
    # mech_chance（技能数据概率：盾击·誓 40% 眩晕）→ apply_effects 通用 chance roll
    _ch = info.get("mech_chance")
    if _ch is not None:
        try:
            _eff["chance"] = float(_ch)
        except Exception as _e:
            _diag(None, "_mech_to_effect", _e)          # 审计 P-44：不再静默（行为不变）
            pass
    return _eff


def _is_stack_resource(cfg: dict) -> bool:
    """判据：cfg 是否「叠层资源型」效果（技能 mech 按层数叠）。

    叠层资源 = 有每层/每层数值字段（stat_scale/debuff_scale/period/dot/
    on_threshold/guard_hp_pct）或 cap>1 纯计数层。控制（consume）、静态增益
    （panel）、纯净化标记（tag/cleanse）不是叠层资源 → 走 EFFECT_ACTIONS 名词。
    """
    if not cfg:
        return False
    for f in ("stat_scale", "debuff_scale", "period", "dot",
              "on_threshold", "guard_hp_pct"):
        if cfg.get(f):
            return True
    if int(cfg.get("cap") or 0) > 1:
        return True
    return False


# ============================================================
# 动词执行器
# ============================================================

# ---- apply：统一效果写入动词（V4 收敛：吸收 control/buff/state_add/state_set）----
# 行为全由 EFFECT_RULES[key] 声明 + 参数决定，引擎零名词：
#   mode 存在  → 控制型（写 effects[key] = {expire, mode}，消费调度层按 mode 执行）
#   op=add     → 叠层加（stacks += amount，cap 查 EFFECT_RULES）
#   op=set     → 叠层置（stacks = amount，cap 查 EFFECT_RULES）
#   否则快照型 → 写 effects[key] = {stacks, expire, ...数值快照}（value 型/stat 增益/纯状态/hit）

def note_dot_source(battle, holder, key: str, caster) -> None:
    """记录「持续伤害强度快照」：把**施法者面板**存进条目 `src`（引擎通用）。

    权威语义（旧引擎 `_apply_dot`）：「伤害跟挂毒的人，不跟当前谁在结算」——
    每层每刻的 atk/matk 段取**挂上那一刻**的施法者面板。

    引擎零知识：仅当数据（EFFECT_RULES[key].period）声明了 atk / matk 系数时才记录
    （否则**不写**任何字段，条目形态与接线前逐字一致）；atk / matk 是通用 actor 面板键。
    holder 缺省不写；caster 缺失或取面板失败 → 不写（tick 端按 0 处理，纯百分比 DOT 不受影响）。
    """
    if not isinstance(holder, dict) or not key:
        return
    try:
        per = (state_def(key) or {}).get("period")
        if not isinstance(per, dict):
            return
        if not (float(per.get("atk", 0) or 0) or float(per.get("matk", 0) or 0)):
            return
        entry = (holder.get("effects") or {}).get(key)
        if not isinstance(entry, dict) or not caster:
            return
        from . import stats as _S
        st = _S.actor_stats(battle, caster) if battle is not None else (caster or {})
        entry["src"] = {"atk": int(st.get("atk", 0) or 0),
                        "matk": int(st.get("matk", 0) or 0)}
    except Exception as _e:
        _diag(battle, "note_dot_source · 快照失败", _e)          # 审计 P-44：不再静默（行为不变）
        pass  # 快照失败不阻断施加（tick 端按 0 段处理）


@register_action("apply")
def act_apply(battle, caster, target, params, logs):
    """统一效果写入动词（V4 动词收敛——旧 control/buff/state_add/state_set 合流）。

    apply = 往 actor.effects[key] 写条目。写什么形态由参数判定（引擎零名词）：
      - mode 存在：控制型。effects[key] = {expire, mode, stacks:1}；target 打 boss 减半。
        消费（跳过行动/禁技）由调度层按 mode 执行：skip 整跳 / no_skill 技能转普攻。
      - op == "add"：叠层加。effects[key].stacks += amount（cap 查 EFFECT_RULES[key]）。
      - op == "set"：叠层置。effects[key].stacks = amount（覆盖/刷新）。
      - value/pct_from_mech_val：值型。effects[key] = {stacks, expire, v: float}。
      - stat + mult：面板增益快照。effects[key] = {stacks, expire, stat, op, mult}。
      - hit dict：出手消费型。effects[key] = {stacks, expire, hit}。
      - 其余：纯状态（免疫/标记/一次性），只记到期。
    on=caster(缺省)/target 决定作用对象；turns 决定到期（快照型需要，叠层型忽略）。
    key 由 params.key 提供（V4 后统一 key；旧 tag/mech 回落已删——无 key 即 no-op）。
    """
    from .battle import _now_of
    on = params.get("on", "caster")
    key = params.get("key")
    if not key:
        return
    # ---------- 控制型（原 act_control：固定打 target，不回落 caster）----------
    # V5②：mode 优先动作参数（装配层/翻译器直传覆盖），缺省查 EFFECT_RULES[key].consume.mode
    mode = params.get("mode")
    if mode is None:
        _mcfg = (state_def(key) or {}).get("consume")
        if isinstance(_mcfg, dict):
            mode = _mcfg.get("mode")
    if mode is not None:
        if not target:
            return
        holder = caster if str(on) == "caster" else target
        turns = int(params.get("turns", 0) or 0)
        if turns <= 0:
            return
        # N-B7 免疫控制查询点（2026-09-11 接线）：控制类效果（mode != None）落地前
        # 先查持有者是否带免疫态 —— 引擎只读**态名**（`cc_immune`，属引擎固定词汇表
        # 契约，不是游戏名词），不认「哪个技能给的免疫」。内容侧写态（含刻数，
        # 引擎按 expire 自动清理）；态在 = 本次控制不施加（不消耗、不叠层）。
        _im = (holder.get("effects") or {}).get("cc_immune")
        if isinstance(_im, dict) and float(_im.get("expire", 0) or 0) > _now_of(battle):
            logs.append(render_via(battle, "battle.effects.immune_control", "🛡️ {name} 免疫控制：{key} 未生效",
                                name=holder.get('name', '目标'),
                                key=key))
            return
        # 控制时长对**带某些标签的目标**减半：标签名单由该状态的规则声明
        #   （`state_def(key)["ctrl_half_traits"]`），引擎不认标签叫什么（审计 E3）。
        _half = (state_def(key) or {}).get("ctrl_half_traits") or ()
        if traits.has_any(holder, _half):
            turns = max(1, turns // 2)
        now = _now_of(battle)
        ef = holder.setdefault("effects", {})
        old = ef.get(key)
        old_exp = float(old.get("expire", 0) or 0) if isinstance(old, dict) else 0.0
        ef[key] = {"expire": max(old_exp, now + turns), "mode": mode, "stacks": 1}
        logs.append(render_via(battle, "battle.effects.stack_applied", "💫 {name} 被【{key}】{turns} 刻！",
                            name=holder.get('name', '目标'),
                            key=key,
                            turns=turns))
        return
    # 叠层型 / 快照型（原 act_state_add/set/buff）：holder 按 on 定位
    holder = caster if on == "caster" else (target or caster)
    if not holder:
        return
    # N-B11 异常免疫查询点（2026-09-11 接线）：DOT 类状态（EFFECT_RULES[key].period.dir
    #   == "damage"）落地前先查持有者的免疫名单 —— 与上方 `cc_immune` 同款「读态名不认
    #   来源」：引擎只读**类型名**列表（`immune_dots: ["burn"]`，属引擎固定词汇表契约，
    #   不是游戏名词），不认「哪个怪天生免毒」。名单在 = 本次不施加（不叠层、不消耗）。
    #   数据侧缺省（无 immune_dots 键）→ 空名单 → 行为与接线前完全一致。
    try:
        _per = (state_def(key) or {}).get("period")
        if isinstance(_per, dict) and str(_per.get("dir") or "") == "damage":
            _imm = holder.get("immune_dots")
            if _imm is None:
                _imm = getattr(battle, "immune_dots", None)
            if _imm and key in list(_imm):
                logs.append(render_via(battle, "battle.effects.immune_debuff", "🚫 {name} 免疫【{key}】，异常未生效",
                                    name=holder.get('name', '目标'),
                                    key=key))
                return
    except Exception as _e:
        _diag(battle, "act_apply · 免疫查询", _e)          # 审计 P-44：不再静默（行为不变）
        pass  # 免疫查询异常不阻断施加
    ef = holder.setdefault("effects", {})
    now = _now_of(battle)
    # ---------- 叠层加/置（原 act_state_add/state_set；op 字段仅在无 stat 时是叠层操作，
    # 面板增益的 op 是 mul/add 面板算子且必带 stat，走快照分支）----------
    op = params.get("op")
    if op in ("add", "set") and not params.get("stat"):
        # DOT 强度快照（数据声明了 period.atk/matk 才写；见 note_dot_source）
        # v181.M-R2e B3：amount/cur float 读（stacks 允许小数刻度——小数衰减等）；
        # cap 收敛 _cap_of（方案 A：EFFECT_RULES 基础 cap + actor.bonus.cap 动态，
        # v181.M-bonus 分域——旧 actor cap_bonus 键已全清）。
        # amount<=0 仍不加（负向消费走 consume / schedule period，apply 只增/置）。
        amount = float(params.get("amount", params.get("value", params.get("stacks", 0))) or 0)
        cap = _cap_of(holder, key)
        cur = float((ef.get(key) or {}).get("stacks", 0) or 0) if isinstance(ef.get(key), dict) else 0.0
        if op == "add":
            if amount <= 0:
                return
            n = max(0.0, min(float(cap), cur + amount))
        else:
            n = max(0.0, min(float(cap), amount))
        entry = ef.get(key)
        if not isinstance(entry, dict):
            entry = ef[key] = {}
        entry["stacks"] = _norm_stack(n)
        note_dot_source(battle, holder, key, caster)
        if op == "add":
            cap_txt = f"/{cap}" if cap < 999999 else ""
            logs.append(f"✦ {key} {_fmt_stack(n)}{cap_txt}（+{_fmt_stack(amount)}）")
        else:
            logs.append(render_via(battle, "battle.effects.stack_set", "✦ {key} 置为 {n}",
                                key=key,
                                n=_fmt_stack(n)))
        # N8 事件：状态阈值（层数变化后广播——"某资源满 10 → 触发某形态"由上层声明匹配）
        try:
            from .effect_triggers import fire as _fire
            _fire(battle, "threshold", {"actor": holder, "key": key, "value": n}, logs)
        except Exception as _e:
            _diag(battle, "act_apply", _e)          # 审计 P-44：不再静默（行为不变）
            pass
        return
    # ---------- 快照型（原 act_buff）----------
    turns = int(params.get("turns", 0) or 0)
    if turns <= 0:
        return
    expire = now + turns
    # value 型（如 reduce=0.45）：存 {stacks, expire, v}——纯状态/减伤独立计时
    value = params.get("value")
    if params.get("pct_from_mech_val"):
        mv = float(params.get("mech_val") or 0)
        value = (mv / 100.0) if mv > 1 else mv  # 45→0.45；0.45→0.45
    if value is not None:
        old = ef.get(key)
        old_v = float(old.get("v", 0)) if isinstance(old, dict) else 0.0
        ef[key] = {"stacks": 1,
                   "expire": max(float(old.get("expire", 0) or 0) if isinstance(old, dict) else expire, expire),
                   "v": max(old_v, float(value))}
        if key == "reduce":
            holder["reduce_left"] = max(int(holder.get("reduce_left", 0) or 0), turns)
        logs.append(render_via(battle, "battle.effects.shield_pct", "🛡️ {key} {value::.0%}（持续 {turns} 刻）",
                            key=key,
                            value=float(value),
                            turns=turns))
        return
    # 增益：参数 stat/op/mult（EFFECT_ACTIONS 静态配置已入 EFFECT_RULES[key].panel，
    # V5 后动作瘦身 key-only——参数缺省查表；动态装配层仍参数直传覆盖）→ 快照进条目
    cfg = state_def(key) or {}
    panel = cfg.get("panel") or {}
    stat = params.get("stat") or panel.get("stat")
    o = params.get("op") or panel.get("op")
    mult = params.get("mult")
    if mult is None and "mult" in panel:
        mult = panel.get("mult")
    if stat and mult is not None:
        old = ef.get(key)
        old_exp = float(old.get("expire", 0) or 0) if isinstance(old, dict) else 0.0
        ef[key] = {"stacks": 1,
                   "expire": max(old_exp, expire),
                   "stat": stat, "op": o or "mul", "mult": float(mult)}
        logs.append(render_via(battle, "battle.effects.buff_boost", "✦ {key} 提升（{op}×{mult}，持续 {turns} 刻）",
                            key=key,
                            op=o or 'mul',
                            mult=mult,
                            turns=turns))
        return
    # 无 stat 的纯状态 buff（免疫/一次性/标记等）：只记录到期，不折算面板
    note_dot_source(battle, holder, key, caster)
    hit_params = params.get("hit")
    old = ef.get(key)
    old_exp = float(old.get("expire", 0) or 0) if isinstance(old, dict) else 0.0
    entry = {"stacks": 1, "expire": max(old_exp, expire)}
    # N7.3 出手消费型：hit 子键声明出手效果（dmg_mult 增伤 / guaranteed_crit 必暴）
    if isinstance(hit_params, dict):
        entry["hit"] = dict(hit_params)
        logs.append(render_via(battle, "battle.effects.on_hit_ready", "✦ {key} 出手效果就绪（{turns} 刻内生效）",
                            key=key,
                            turns=turns))
    else:
        logs.append(render_via(battle, "battle.effects.stack_active", "✦ {key}（持续 {turns} 刻）",
                            key=key,
                            turns=turns))
    ef[key] = entry


# ---- consume：主动扣叠层（V4 收敛：吸收 state_spend）----

@register_action("consume")
def act_consume(battle, caster, target, params, logs):
    """通用叠层消费（V4：旧 state_spend）：actor.effects[key].stacks 扣 amount（下限 0）。

    不足拦截（需足额才扣，缺额提示不扣）。cap 无意义（只减不增）。
    """
    on = params.get("on", "caster")
    holder = caster if on == "caster" else (target or caster)
    if not holder:
        return
    key = params.get("key")
    # v181.M-R2e B3：cur float 读（消费 float 层保真——小数衰减后 9.3 扣 3 → 6.3）
    amount = float(params.get("amount", params.get("stacks", 0)) or 0)
    if not key or amount <= 0:
        return
    ef = holder.setdefault("effects", {})
    entry = ef.get(key)
    cur = float(entry.get("stacks", 0) or 0) if isinstance(entry, dict) else 0.0
    if cur < amount:
        logs.append(render_via(battle, "battle.effects.stack_short", "⚠️ {key} 不足（需 {amount}，当前 {cur}）",
                            key=key,
                            amount=_fmt_stack(amount),
                            cur=_fmt_stack(cur)))
        return
    if not isinstance(entry, dict):
        entry = ef[key] = {}
    entry["stacks"] = _norm_stack(max(0.0, cur - amount))
    logs.append(render_via(battle, "battle.effects.stack_spent", "✦ 消耗 {amount} 点 {key}（剩余 {left}）",
                        amount=_fmt_stack(amount),
                        key=key,
                        left=_fmt_stack(cur - amount)))


@register_action("shield")
def act_shield(battle, caster, target, params, logs):
    """护盾：写 actor.shields[key]（v181.N7.2 补 expire_at + 同源叠厚）。

    结构：shields[key] = {"value": 盾值, "expire_at": now+turns, "halve": bool}
    - 同源（同 key）：value 累加（叠厚）+ expire_at 取 max（对齐旧 _add_shield）
    - 异源并存各计各的时长
    - turns=0/缺省 → 3 刻；turns>=999 → 永久（expire_at=None，不到期删）
    value/halve/turns 由数据给；value 与 pct 都没有时兜底比例读内容侧骨架表
    （V4 下沉：`formulas.shield_default_pct()`，未装配 → 0.0 = 不产盾）。
    """
    from .battle import _now_of
    holder = caster if params.get("on", "caster") == "caster" else (target or caster)
    if not holder:
        return
    info = params.get("info") or {}
    key = params.get("key") or "buff"
    value = int(params.get("value") or params.get("mech_val") or 0)
    pct = float(params.get("pct", info.get("shield_pct", 0)) or 0)
    if value <= 0 and pct > 0:
        value = int(holder.get("max_hp", 1) * pct)
    if value <= 0:
        # V4：兜底比例从内容侧骨架表读（原写死 0.20；未装配 → 0.0 = 不产盾不崩）
        from . import formulas as _F
        value = int(holder.get("max_hp", 1) * _F.shield_default_pct())
    turns = int(params.get("turns", 0) or 0) or 3
    halve = bool(params.get("halve", False))
    now = _now_of(battle)
    # 永久盾（turns>=999 或显式 forever）
    if params.get("forever") or turns >= 999:
        expire = None
    else:
        expire = now + max(1, turns)
    sh = holder.setdefault("shields", {})
    cur = sh.get(key)
    if cur and isinstance(cur, dict):
        cur["value"] = int(cur.get("value", 0) or 0) + value          # 同源叠厚（累加）
        if cur.get("expire_at") is not None:
            if expire is None:
                cur["expire_at"] = None                                # 新永久 → 永久
            else:
                cur["expire_at"] = max(float(cur.get("expire_at", 0) or 0), expire)
    else:
        sh[key] = {"value": value, "expire_at": expire, "halve": halve}
    logs.append(render_via(battle, "battle.effects.shield_gain", "🛡️ {name} 获得护盾 {value} 点！",
                        name=holder.get('name', '目标'),
                        value=value))


# ---- cleanse：净化 ----

@register_action("cleanse")
def act_cleanse(battle, caster, target, params, logs):
    """净化：移除目标身上的 DOT/标记/控制（V5④ 全查表，无 CLEANSE_TAGS 白名单）。

    遍历 effects 条目，查 EFFECT_RULES[key]：
    - period（周期 DOT/负面）→ 清；**`dir="gain"` 的资源回除外**（不是减益，2026-09-18）
    - on == target（对敌标记）→ 清
    - cleanse == True（显式可净化声明：控制键/减伤——原 CLEANSE_TAGS 成员表化）→ 清
    - 其余（无负面/不可净化声明）不清
    """
    from .state_effects import all_state_effects
    actor = target or caster
    if not actor:
        return
    rem = []
    ef = actor.setdefault("effects", {})
    state_table = all_state_effects()
    for k in list(ef.keys()):
        cfg = state_table.get(k) or {}
        _per = cfg.get("period")
        # 2026-09-18 修：周期声明按方向过滤——`dir="gain"`（资源自然回/衰减）不是减益，
        #   净化不得清（旧判据「有 period 即清」会把职业资源条目吞掉 → 资源整场停回、
        #   依赖它的技能白放）。其余方向与畸形声明保持旧口径（有 period 即视为可净化）。
        _gain = isinstance(_per, dict) and str(_per.get("dir", "damage") or "damage") == "gain"
        if (_per and not _gain) or cfg.get("on") == "target" or cfg.get("cleanse"):
            rem.append(k)
            ef.pop(k, None)
    if rem:
        logs.append(render_via(battle, "battle.effects.cleansed", "✨ 净化了 {names}！",
                            names='、'.join(rem)))
    else:
        logs.append(render_via(battle, "battle.effects.cleanse_none", "✨ 净化（无减益可解）"))


@register_action("cleanse_all")
def act_cleanse_all(battle, caster, target, params, logs):
    """全体净化：施法者自身全部减益（副本广播在命令层）。"""
    act_cleanse(battle, caster, target or caster, params, logs)


# ---- heal：治疗（landing 薄包装）----

@register_action("heal")
def act_heal(battle, caster, target, params, logs):
    """治疗动词（N7.5a）：落地走 landing.heal_actor 统一收口。

    参数（引擎零公式知识）：
    - pct：按目标 max_hp 百分比治疗（如 heal_pct 0.15 → 15%）
    - missing_pct：按目标已损生命百分比治疗（如 0.02 → 回 2% 缺口）
      —— v2 通用治疗基准（regen 型装备：每刻回复已损/最大生命 %）
    - expr：表达式（由数据给；暂不 eval——治疗技能走 actions._do_heal 公式链）
    - value：固定治疗量
    on=target 时治疗 target；缺省治疗 caster。
    """
    from .landing import heal_actor
    holder = caster if params.get("on", "caster") == "caster" else (target or caster)
    if not holder:
        return
    if holder.get("hp") is None:
        return
    info = params.get("info") or {}
    pct = float(params.get("pct", 0) or 0)
    if pct <= 0:
        pct = float(info.get("hp_pct", 0) or 0)   # 怪 heal_self/heal_pct 数据 hp_pct
    value = int(params.get("value", 0) or 0)
    missing_pct = float(params.get("missing_pct", 0) or 0)
    if pct > 0:
        value = int((holder.get("max_hp", 1) or 1) * pct)
    elif missing_pct > 0:
        _mx = int(holder.get("max_hp", 1) or 1)
        value = int(max(0, _mx - int(holder.get("hp", 0) or 0)) * missing_pct)
        value = max(1, value) if int(holder.get("hp", 0) or 0) < _mx else 0
    if value <= 0:
        return
    real = heal_actor(battle, holder, value, logs)
    if real > 0:
        logs.append(render_via(battle, "battle.effects.healed", "✨ {name} 恢复了 {heal} 点生命！",
                            name=holder.get('name', '目标'),
                            heal=real))


@register_action("interrupt")
def act_interrupt(battle, caster, target, params, logs):
    """打断出招窗口（N7.5a / T15）：清 target 的待发行动 ⇒ 该手**不出伤**。

    「哪些效果算控制」全在内容侧（挂本动作即可）；引擎只读槽内通用布尔
    `unstoppable`（出招窗口霸体：真 ⇒ 拒绝打断），不认识任何控制/技能名词。
    """
    actor = target or caster
    if not actor:
        return
    slot = actor.get("charging")
    if not isinstance(slot, dict):
        return
    if slot.get("unstoppable"):
        return
    actor["charging"] = None
    logs.append(render_via(battle, "battle.effects.cast_broken", "💥 {name} 的出招被打断了！",
                        name=actor.get('name', '目标')))
    # N5B5c P5：打断事件（on_interrupt 剧本联动：出招被断 → 反噬/易伤）
    try:
        from .effect_triggers import fire as _fire
        _fire(battle, "interrupt", {"actor": actor, "target": actor,
                                    "source": caster}, logs)
    except Exception as _e:
        _diag(battle, "act_interrupt", _e)          # 审计 P-44：不再静默（行为不变）
        pass


@register_action("damage")
def act_damage(battle, caster, target, params, logs):
    """直接伤害动词（N9）：落地统一走 landing.deal_damage（N8 事件随之广播）。

    参数（引擎零公式知识）：
    - value : 固定伤害量
    - pct   : 按目标 max_hp 百分比（pct_max_hp 别名；与 DOT 同语义）
    - kind  : phys/magi/true/""（透传 landing dmg_kind，免伤等按类型扩展）
    目标语义：
    - on=target（缺省）：对 ctx.target 造成伤害（技能/命中附加/溅射）
    - on=caster：对施放方造成伤害（反伤打攻击者/血祭自伤——反伤时 fire 的
      ctx.caster = 攻击方，正好是被打对象；source 仍记 caster 参数）
    无 target 容器（hp 为 None）不执行；伤害全部经 landing 收口（护盾/死亡判定）。
    """
    from .landing import deal_damage
    holder = caster if params.get("on", "target") == "caster" else (target or caster)
    if not holder or holder.get("hp") is None:
        return
    value = int(params.get("value", 0) or 0)
    pct = float(params.get("pct", params.get("pct_max_hp", 0)) or 0)
    if pct > 0:
        value = int((holder.get("max_hp", 1) or 1) * pct)
    if value <= 0:
        return
    dmg_kind = str(params.get("kind", "") or "")
    real = deal_damage(battle, caster, holder, value, logs, dmg_kind=dmg_kind)
    if real > 0:
        logs.append(render_via(battle, "battle.effects.damaged", "💥 {name} 受到 {dmg} 点伤害！",
                            name=holder.get('name', '目标'),
                            dmg=real))
