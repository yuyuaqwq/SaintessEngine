# -*- coding: utf-8 -*-
"""《奥兰迪亚》职业机制兑现族 class_mech —— 39 个战斗内动作（**逐字搬运物**）。

来源 = 游戏仓 `C:/Users/yuyu/qqbot/data/plugins/dragonfall/game/services/class_mech_proc.py`
（v181.M，2446 行）。动作集中在该文件 `install()` 闭包内 **:100-1866**（39 个
`@register_action("…")`），被用到的模块级助手在 **:1868-2260**（本文件只搬动作 transitively
用到的 5 个：`_learned_proc` / `_learned_proc_param` / `_res_ge_ok` / `_has_effect_ok` /
`_when_ok`）。

结构改写清单（**仅此 4 项**；函数体、数值、`logs.append` 文案、注释一字未改）
----------------------------------------------------------------------------
1. **闭包 → 模块顶级**：原 39 个动作定义在 `install()` 内（缩进 4），依赖同闭包的
   13 个闭包助手 + 8 个旋律闭包常量。搬运 = 去 `def install()`/`_registered`，把动作与
   被它们用到的闭包助手/常量**同样缩进层级**提到模块级，动作加顶层
   `@register_action("<原名>")` 装饰器（引擎 import 即注册）。
   · 被提升的闭包助手（13 个，逐字）：`_key_list` `_stacks_float` `_add_mark` `_act_target`
     `_holder` `_clear_actor` `_faith_tiers` `_melody_pct_of` `_melody_side_actors`
     `_melody_write_aura` `_melody_ensure_tick` `_melody_ctrl_apply` `_melody_finale`
   · 被提升的闭包常量（8 个，逐字）：`_MELODY_AURA_MAP` `_MELODY_FIN_MAP`
     `_MELODY_ENEMY_AURA_MAP` `_MELODY_ENEMY_FIN_MAP` `_MELODY_FIN_CTRL_MAP`
     `_MELODY_SILENCE_TICK` `_MELODY_ALL_AURA_KEYS` `_MELODY_MAX_STACK`
2. **原模块级助手逐字搬**（5 个，无改写）：`_learned_proc`(`:1977`) /
   `_learned_proc_param`(`:2001`) / `_res_ge_ok`(`:2164`) / `_has_effect_ok`(`:2181`) /
   `_when_ok`(`:2195`)。
3. **游戏仓相对 import → 包内/引擎单源**（**唯一**被改的代码行，3 处、同一条语句）：
   原 `from ..content_rules.skills import skill_info`（`:381` 于 `class_faith_overload`、
   `:1989` 于 `_learned_proc`、`:2014` 于 `_learned_proc_param`）
   → `from saintess_engine.config import skill_info_of as skill_info`
   （引擎 hook `skill_lookup.skill_info` 的公开入口，语义 = 包内 `content/data/skills.json`
   经 `content/apply.py:_SKILL_LOOKUP` 查表；函数体其余部分逐字未动，名字保持 `skill_info`）。
   另：原 39 个动作**没有一个**直接 import `MECH_CASH/MECH_CFG/BAR_*`（这些表由装配层读），
   故 `from .class_data import …` 只作为包内单源 seam 置于文件顶（见下）。
4. **参数表单源**：`from .class_data import MECH_CASH, MECH_CFG, BAR_INJECT_FIELDS,
   BAR_STATE_PREFIX`（原表真源 = `game/data/battle_rules.py:624/742/749` +
   `game/data/battle_config.py:455`；本族动作经装配层消费它们）。

依赖 battle 私有槽（动作读 `getattr(battle, …)`，与游戏仓同款；包侧引擎需提供）
------------------------------------------------------------------------------
`battle._fire_ctx`（所有 dmg/heal/taken/act_cast/threshold 类动作的上下文：`info`/`actor`/
`target`/`mult`/`key`/`value`/`dt`）、`battle._now`（条结算/过载帧/控制到期）、
`battle.sides`（阵营遍历：旋律光环/过载回血/挽歌 tick）。另有动作改写宿主身上的
`_faith_overload_at` / `effects["melody_state"]["_silence_at"]` 等私有字段（游戏仓同款）。

过渡期铁律（设计稿 §五-3）：**包版是搬运物**，游戏仓 `class_mech_proc.py` 同名实现继续
存在；两者语义必须逐字一致（否则同一 actor 走不同装配路径会得到不同数值）。

动作清单（39 个；真源 `@register_action` 装饰器行号）
-----------------------------------------------------
  :100   mech_cash_finisher_crit
  :132   mech_cash_dmg_mult
  :157   mech_cash_clear
  :180   mech_cash_per_system_mult
  :211   class_res_channel_gain
  :291   class_faith_load_tier
  :333   class_faith_overload
  :556   class_melody_act
  :611   passive_melody_duet
  :642   class_melody_dirge_tick
  :674   passive_ctrl_extend
  :734   passive_dmg_mult
  :852   passive_bar_extend
  :887   passive_kill_gain
  :906   passive_counter
  :936   passive_cond_crit
  :995   passive_taken_reduce
  :1038  passive_cc_clear
  :1062  passive_cc_break
  :1102  passive_lifesteal_buff
  :1131  passive_heal_overflow_shield
  :1176  mech_cash_fury_enter
  :1208  passive_dot_mult
  :1233  passive_poison_weaken
  :1278  class_shadow_dance_enter
  :1301  class_stance_guard_enter
  :1329  class_stance_counter
  :1359  class_guard_stance_enter
  :1402  passive_low_hp_core
  :1441  passive_overflow_shield
  :1489  passive_shadow_buff
  :1513  passive_res_gain_turn
  :1544  passive_revive_guard
  :1579  passive_revive_berserk
  :1618  passive_mark_enhance
  :1669  passive_element_core_crit
  :1710  passive_bar_decay_half
  :1759  passive_lian_duan_soft
  :1809  passive_poison_spread
"""
from __future__ import annotations

from saintess_engine.battle.effects import register_action

# 包内参数表单源（真源见 class_data.py 头注）。本族 39 个动作不直接读这些表（由装配层
# 消费），此处 import = 保持「表 → 装配层 → 动作」的包内单源缝，并为后续接线预置。
from .class_data import (  # noqa: F401
    BAR_INJECT_FIELDS,
    BAR_STATE_PREFIX,
    MECH_CASH,
    MECH_CFG,
)


# ============================================================
# 模块级助手（原 class_mech_proc.py 模块级，逐字搬）
# ============================================================


def _learned_proc(actor: dict, proc: str) -> bool:
    """actor 已学技能中是否带指定 passive.proc（链舞 finisher_up 等挂在主动技上）。

    装配器 apply_class_passives 只扫 kind=被动——主动技上的 proc 不装配 triggers，
    但可作为 MECH_CASH.upgrade 的"学到即升级"判据（扫 learned_skills 全表）。
    """
    if not actor or not proc:
        return False
    cn = actor.get("class_name") or ""
    names = actor.get("learned_skills") or []
    if not cn or not names:
        return False
    from saintess_engine.config import skill_info_of as skill_info
    for s in names:
        try:
            info = skill_info(cn, s)
        except Exception:
            info = None
        if info and isinstance(info.get("passive"), dict) \
                and (info.get("passive") or {}).get("proc") == proc:
            return True
    return False


def _learned_proc_param(actor: dict, proc: str, key: str, default=None):
    """读已学技能上 `passive.proc == proc` 的那个 passive dict 的某个参数值。

    `_learned_proc` 的带参版（旁路通道专用）：装配器只扫 kind=被动，而这类参数
    （如影舞·无间 shadow_dance_ease.threshold）由装配层动作按需读取。
    找不到 proc / 无该参数 / 解析异常 → 返回 default（缺字段 = 用默认，零默认值铁律）。
    """
    if not actor or not proc:
        return default
    cn = actor.get("class_name") or ""
    names = actor.get("learned_skills") or []
    if not cn or not names:
        return default
    from saintess_engine.config import skill_info_of as skill_info
    for s in names:
        try:
            info = skill_info(cn, s)
        except Exception:
            info = None
        ps = info.get("passive") if isinstance(info, dict) else None
        if isinstance(ps, dict) and ps.get("proc") == proc and key in ps:
            return ps.get(key)
    return default


def _res_ge_ok(actor: dict, judge: dict, params: dict) -> bool:
    """资源层数门槛判定（res_ge judge 通用）：effects[res].stacks ≥ 阈值。

    judge: {kind: res_ge, res, ge_field}; 阈值读 params[ge_field]（passive dict 并入）。
    """
    if not actor:
        return False
    res = (judge or {}).get("res") or ""
    ge_field = (judge or {}).get("ge_field") or ""
    need = float((params or {}).get(ge_field) or 0)
    if not res or need <= 0:
        return False
    _entry = ((actor.get("effects") or {})).get(res)
    cur = float(_entry.get("stacks", 0) or 0) if isinstance(_entry, dict) else 0.0
    return cur >= need


def _has_effect_ok(actor: dict, judge: dict) -> bool:
    """效果在位判定（has_effect judge）：actor.effects 含指定 key。

    过期由引擎结算删除（schedule.py 时钟推进 ef.pop），故「在位 = 生效」——
    与 class_stance_counter 的判法同口径。零默认值铁律：judge 无 key 声明 = False。
    """
    if not actor:
        return False
    key = (judge or {}).get("key") or ""
    if not key:
        return False
    return isinstance((actor.get("effects") or {}).get(key), dict)


def _when_ok(actor: dict, params: dict) -> bool:
    """动作 when 条件门（通用谓词派发）——全部满足才 True；无声明 = True。

    when: [{"judge": {...}}, ...]，谓词按 judge.kind 派发（与动作侧 judge 同族）：
      - has_effect  态在位（守护姿态/形态等：资源按姿态攒取）
      - res_ge      资源层数门槛（阈值读同条目的 ge_field）
    未知 kind → False（fail-closed）：渠道条件写错时宁可漏攒，不可静默攒错
    （数值膨胀无声无息，比漏攒危险得多）。
    """
    when = (params or {}).get("when")
    if not when:
        return True
    if not isinstance(when, (list, tuple)):
        return False
    for w in when:
        if not isinstance(w, dict):
            return False
        j = w.get("judge") or {}
        kind = j.get("kind") or ""
        if kind == "has_effect":
            if not _has_effect_ok(actor, j):
                return False
        elif kind == "res_ge":
            if not _res_ge_ok(actor, j, w):
                return False
        else:
            return False
    return True

# ============================================================
# 谓词/工具助手（原 install() 闭包 → 模块级，逐字）
# ============================================================


def _key_list(key):
    """声明 key 归一为列表（str → [str]；None → []）。"""
    if isinstance(key, (list, tuple)):
        return list(key)
    return [key] if key else []


def _stacks_float(effects, key) -> float:
    """effects 层数（float 保真）：多印记 key 各 stacks 之和。

    v181 磐核经「守御姿态下每刻 +0.4」渠道产生小数层（如 3.4 枚）；burst 乘区
    折算需保真——int 截断会低估 ×(1+0.7n)（3.4 → 3.0）。mech_cash_dmg_mult 走本函数。
    """
    total = 0.0
    for k in _key_list(key):
        ef = (effects or {}).get(k)
        total += float(ef.get("stacks", 0) or 0) if isinstance(ef, dict) else 0.0
    return total


def _add_mark(tgt: dict, mech: str, n: int) -> None:
    """target effects 印记层 +n（挂印增强用——基础段 apply 前先加，总 = 1+n）。"""
    if tgt is None or n <= 0:
        return
    ef = tgt.setdefault("effects", {})
    en = ef.get(mech)
    if not isinstance(en, dict):
        en = ef[mech] = {}
    en["stacks"] = int(en.get("stacks", 0) or 0) + n


def _act_target(battle, ctx, actor, target):
    """act_cast 动作目标解析：act_cast fire 在 do_skill 目标解析之前（ctx.target=None）
    → 回落敌对存活首目标（同 actions._default_target 语义）。"""
    tgt = ctx.get("target") or target
    if tgt is not None:
        return tgt
    try:
        from saintess_engine.battle.actors import hostile_sides, actor_alive as _alive
        for _sn in hostile_sides(battle, actor.get("side", "")):
            for _a in (battle.sides.get(_sn) or []):
                if _alive(_a):
                    return _a
    except Exception:
        pass
    return None


def _holder(owner, ctx, caster, target):
    """owner 方向选 actor：owner=target → ctx.target（fire ctx 优先）；缺省 caster。"""
    if (owner or "caster") == "target":
        return ctx.get("target") or target
    return ctx.get("actor") or caster


def _clear_actor(actor, key, logs):
    """把 actor.effects 的 key（str/列表）stacks 置 0。"""
    for k in _key_list(key):
        entry = (actor.get("effects") or {}).get(k)
        if isinstance(entry, dict):
            entry["stacks"] = 0
    logs.append(f"🔗 {'、'.join(_key_list(key))} 归零")


def _faith_tiers() -> list:
    """EFFECT_RULES faith 条目 load_tiers 档位表（缺省 []——零默认值铁律）。"""
    try:
        from saintess_engine.battle.state_effects import state_def
        _t = (state_def("faith") or {}).get("load_tiers")
        return _t if isinstance(_t, list) else []
    except Exception:
        return []

# ============================================================
# 旋律（melody）常量与助手（原 install() 闭包 → 模块级，逐字）
# ============================================================


# ---- v181.M-melody：诗人旋律驻留（唱新歌/吟唱叠层/满层终章 + 全队光环广播）----
# 数据源 = 技能 dict：melody 字段（kind: atk/def/spd/atk_matk）+ melody_pct（基础%）
# + finale（终章 kind: crit/atk）+ melody_fin_pct/buff_turns。状态存施法者
# effects["melody_state"]（无 EFFECT_RULES 声明 → 零折算纯状态，随 actor 序列化）；
# 光环广播全员 effects["melody_<kind>"]（stat_scale per=0.01，stacks=目标%）。
# 数值公式：效果% = pct × (1 + 0.25×(stacks-1))（1 层=desc 值，5 层=×2=+100%；
# 公式与分支 e_ 减益系/终章触发细节标待 v153 重做确认——本次目的=机制载体）。
_MELODY_AURA_MAP = {
    "atk": "melody_atk", "def": "melody_def",
    "spd": "melody_spd", "atk_matk": "melody_atk_matk",
}


_MELODY_FIN_MAP = {"atk": "melody_finale_atk", "crit": "melody_finale_crit"}


# v181.G1 挽歌者 e_ 减益旋律（敌方向）——docs/CLASS_MECHANICS_v153.md §七 B 线
# 「吟游诗人 — 驻留旋律」挽歌者 › 安魂歌者 › 镇魂挽者；旧语义源 =
# game/core/battle_mech.py._melody_apply_e_buffs/_m_melody_finale（git 379a792^，
# 该文件随 N10 删除，只读对齐）。旧引擎经 e_buffs（mon_atk_down/spd_down/def_down +
# _weaken_val/_spd_down_pct/_armor_break_pct 通道）表达；saintess_engine 敌方面板无这些通道，
# 收口为 EFFECT_RULES 的 stat_scale 负值条目（层数 = 目标 %，与增益驻留同折算口径）。
#   kind → 敌方 effects 条目 key；None = 无面板条目（周期控制，走时钟 tick）
_MELODY_ENEMY_AURA_MAP = {
    "e_atk": "melody_e_atk",          # 挽歌 驻留：敌方全体攻击 −N%
    "e_spd": "melody_e_spd",          # 镇魂歌 驻留：敌方全体速度 −N%
    "e_spd_hit": "melody_e_spd_hit",  # 挽歌·沉 驻留：速度 −N%（命中段缺通道）
    "e_all": "melody_e_all",          # 终焉挽歌 驻留：攻/速 −N%（命中段缺通道）
    "e_silence": None,                # 沉默之歌 驻留：封印技能（每 4 刻 1 次，时钟 tick）
}


# 挽歌系终章（敌方向，限时 debuff；层数 = 终章 %，expire = now + fin_turns）
_MELODY_ENEMY_FIN_MAP = {
    "e_atk": "melody_e_fin_atk",      # 挽歌 终章：敌方全体攻击 −40% 8 刻
    "e_spd": "melody_e_fin_spd",      # 镇魂歌 终章：敌方全体速度 −35% 8 刻
    "e_all": "melody_e_fin_all",      # 终焉挽歌 终章：敌方全体全属性 −50% 10 刻
}


# 终章控制（敌方向）：finale token → 引擎控制 key（走 EFFECT_ACTIONS 名词路径）
_MELODY_FIN_CTRL_MAP = {"silence": "silence", "stun": "stun"}


# 时钟驱动型减益旋律（无面板条目：驻留期间按节流周期对敌施控）
_MELODY_SILENCE_TICK = 4.0    # 沉默之歌「每 4 刻至多 1 次」（v153 B 线表 / 技能 desc）


_MELODY_ALL_AURA_KEYS = set(_MELODY_AURA_MAP.values()) | \
    {_v for _v in _MELODY_ENEMY_AURA_MAP.values() if _v}


_MELODY_MAX_STACK = 5   # 旋律强度上限（1 层=desc 值；满层吟唱→终章/巅峰）


def _melody_pct_of(state) -> float:
    pct = float(state.get("pct") or 0)
    stack = int(state.get("stacks") or 1)
    return pct * (1.0 + 0.25 * max(0, stack - 1))


def _melody_side_actors(battle, actor, enemy_dir: bool):
    """驻留光环作用阵营：enemy_dir=True → 施法者对立阵营（挽歌者减益旋律打敌方），
    否则己方阵营（增益旋律全队光环）——阵营关系由 battle.sides 键判定，零职业名。"""
    side = actor.get("side") or "player"
    for _sn, _lst in (getattr(battle, "sides", None) or {}).items():
        if (_sn != side) != bool(enemy_dir):
            continue
        for _a in _lst or []:
            if isinstance(_a, dict):
                yield _a


def _melody_write_aura(battle, actor, logs):
    """按施法者 melody_state 写驻留光环（先清旧驻留条目，finale/终章条目不清）。

    增益系（atk/def/spd/atk_matk）→ 己方阵营 effects[melody_*]；
    挽歌者 e_ 系列 → 敌方阵营 effects[melody_e_*]（EFFECT_RULES stat_scale 负值）。
    旧驻留清点 = 全阵营全表清（换歌跨方向也必须清干净：增益歌切挽歌歌时敌方旧减益
    不能残留，反之亦然）。
    """
    state = ((actor.get("effects") or {}).get("melody_state") or {})
    kind = state.get("kind") or ""
    key = _MELODY_AURA_MAP.get(kind) or _MELODY_ENEMY_AURA_MAP.get(kind)
    enemy_dir = kind in _MELODY_ENEMY_AURA_MAP
    for _lst in (getattr(battle, "sides", None) or {}).values():
        for _a in _lst or []:
            if not isinstance(_a, dict):
                continue
            ef = _a.setdefault("effects", {})
            for _k in list(ef):
                if _k in _MELODY_ALL_AURA_KEYS:
                    ef.pop(_k, None)  # 旧驻留全清（换歌/换方向/叠层重写）
    if not key:
        return
    for _a in _melody_side_actors(battle, actor, enemy_dir):
        _a.setdefault("effects", {})[key] = {"stacks": _melody_pct_of(state),
                                             "expire": None}


def _melody_ensure_tick(actor, kind: str) -> None:
    """时钟驱动型减益旋律自安装订阅（首次唱响时挂，幂等——同破绽条
    battle_bar_procs._ensure_tick 惯例，零噪音）：time_advance →
    class_melody_dirge_tick（按节流周期对敌施控）。

    面板类减益旋律（e_atk/e_spd/e_spd_hit/e_all）由驻留条目本身生效 → 不挂。
    """
    if _MELODY_ENEMY_AURA_MAP.get(kind) is not None:
        return
    lst = actor.setdefault("triggers", {}).setdefault("time_advance", [])
    if not any(isinstance(e, dict) and e.get("action") == "class_melody_dirge_tick"
               for e in lst):
        lst.append({"action": "class_melody_dirge_tick"})


def _melody_ctrl_apply(battle, actor, foe, ckey: str, turns: float, logs) -> None:
    """对敌施加控制：走引擎 apply 动词（EFFECT_RULES[key].consume.mode 语义 +
    Boss 控制减半天然生效，不自造控制通道）。turns 由引擎 int 化（半刻不支持）。"""
    _t = max(1, int(turns or 0))
    from saintess_engine.battle.effects import act_apply
    act_apply(battle, actor, foe, {"key": ckey, "on": "target", "turns": _t}, logs)


def _melody_finale(battle, actor, state, logs):
    """终章：满强度一次性爆发，强度归 1（驻留继续）。

    增益系（atk/crit）→ 全员 finale buff（expire 后消散，叠加在驻留上）；
    挽歌系（e_atk/e_spd/e_all）→ 敌方限时 debuff（EFFECT_RULES melody_e_fin_*）；
    控制系（silence/stun）→ 敌方全体控制（引擎 apply 动词）。
    """
    fin = state.get("fin_kind") or ""
    try:
        _now = float(getattr(battle, "_now", 0) or 0)
    except Exception:
        _now = 0.0
    # ---- 增益系终章：全员爆发 buff（expire 后消散，叠加在驻留上）----
    fkey = _MELODY_FIN_MAP.get(fin)
    if fkey:
        _turns = max(1, int(state.get("fin_turns") or 8))
        for _a in _melody_side_actors(battle, actor, False):
            _a.setdefault("effects", {})[fkey] = {
                "stacks": float(state.get("fin_pct") or 0), "expire": _now + _turns}
        logs.append(f"💥 终章！全队获得爆发增益（{_turns} 刻）！")
        return
    # ---- 挽歌系终章：敌方限时减益 ----
    ekey = _MELODY_ENEMY_FIN_MAP.get(fin)
    if ekey:
        _turns = max(1, int(state.get("fin_turns") or 8))
        _pct = float(state.get("fin_pct") or 0)
        if _pct <= 0:
            return  # 缺字段 = 无此行为（零默认值铁律）
        for _foe in _melody_side_actors(battle, actor, True):
            if _foe.get("effects") is None:
                _foe["effects"] = {}
            _of = _foe["effects"].get(ekey)
            _oexp = float(_of.get("expire", 0) or 0) if isinstance(_of, dict) else 0.0
            _foe["effects"][ekey] = {"stacks": _pct,
                                     "expire": max(_oexp, _now + _turns)}
        logs.append(f"💥 终章！敌方全体受到减益（{int(_pct)}%，{_turns} 刻）！")
        return
    # ---- 控制系终章：敌方全体控制 ----
    ckey = _MELODY_FIN_CTRL_MAP.get(fin)
    if ckey:
        _turns = float(state.get("fin_ctrl") or 0)
        if _turns <= 0:
            return  # 缺字段 = 无此行为（零默认值铁律）
        for _foe in _melody_side_actors(battle, actor, True):
            _melody_ctrl_apply(battle, actor, _foe, ckey, _turns, logs)
        logs.append(f"💥 终章！敌方全体被【{ckey}】{int(_turns)} 刻！")

# ============================================================
# 39 个战斗内动作（原 install() 闭包 → 模块级 + @register_action，逐字）
# ============================================================


@register_action("mech_cash_finisher_crit")
def mech_cash_finisher_crit(battle, caster, target, params, logs):
    """`act_cast`：终结技「连段 ≥ 阈值 → 本次必定暴击」（MECH_CASH.finisher.crit_at）。

    引擎零知识：写的是通用**出手态**（`hit: {guaranteed_crit: True}`，与潜行必暴同一通道，
    由 actions._consume_hit_buffs 在出手时消费）；阈值/资源 key 全部来自声明表。

    时序：act_cast 在伤害管线之前 → 出手态就绪后才 roll 暴击（先查后打）。
    一次性：`turns=1` 到期自动清（未命中/无伤害管线时也不残留）。
    """
    ctx = getattr(battle, "_fire_ctx", None) or {}
    info = ctx.get("info") or {}
    if info.get("mech") != params.get("mech"):
        return
    actor = caster if isinstance(caster, dict) else None
    if actor is None:
        return
    key = params.get("key") or ""
    need = float(params.get("crit_at") or 0)
    if not key or need <= 0:
        return
    _e = (actor.get("effects") or {}).get(key)
    cur = float(_e.get("stacks", 0) or 0) if isinstance(_e, dict) else 0.0
    if cur < need:
        return
    from saintess_engine.battle.effects import apply_action
    hit_key = params.get("hit_key") or "finisher_crit_ready"
    apply_action(battle, actor, actor, "apply",
                 {"key": hit_key, "turns": 1, "on": "caster",
                  "hit": {"guaranteed_crit": True}}, logs)
    logs.append(f"🔪 连段达 {int(cur)} 段 → 终结技必定暴击！")


@register_action("mech_cash_dmg_mult")
def mech_cash_dmg_mult(battle, caster, target, params, logs):
    """dmg_calc：按持有层数加成伤害乘区（模式 dmg_mult_clear* 的伤害段）。

    参数见模块 docstring；mult = 1 + per_layer × 层数（多印记 key = 各 key 之和）。
    """
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    info = ctx.get("info") or {}
    if info.get("mech") != params.get("mech"):
        return
    actor = _holder(params.get("owner"), ctx, caster, target)
    n = _stacks_float(actor.get("effects"), params.get("key"))
    per = float(params.get("per_layer") or 0)
    # 技能级覆盖：info.per_stack（链舞被动给后续终结技 +6%/段）优先于声明缺省
    per = float(info.get("per_stack") or per)
    mult = 1.0 + per * n
    ctx["mult"] = float(ctx.get("mult", 1.0) or 1.0) * mult
    label = params.get("label") or params.get("mech") or ""
    icon = params.get("icon") or "💥"
    layer_label = params.get("layer_label") or "、".join(_key_list(params.get("key")))
    unit = params.get("unit") or "层"
    logs.append(f"{icon} {label}！{layer_label} {n:g} {unit}，伤害 ×{mult:.2f}")


@register_action("mech_cash_clear")
def mech_cash_clear(battle, caster, target, params, logs):
    """skill_hit：兑现后清层（模式 dmg_mult_clear* 的清层段）。

    主清 params.key（owner 方向 actor）；clear_extra 并列清层（可另一 owner）；
    info.keep_on_kill = 本次不清（技能级覆盖，主清与 extra 一并跳过）。
    """
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    info = ctx.get("info") or {}
    if info.get("mech") != params.get("mech"):
        return
    if info.get("keep_on_kill"):
        return
    actor = _holder(params.get("owner"), ctx, caster, target)
    _clear_actor(actor, params.get("key"), logs)
    for ex in params.get("clear_extra") or []:
        if not isinstance(ex, dict):
            continue
        xactor = _holder(ex.get("owner"), ctx, caster, target)
        _clear_actor(xactor, ex.get("key"), logs)


@register_action("mech_cash_per_system_mult")
def mech_cash_per_system_mult(battle, caster, target, params, logs):
    """dmg_calc：每系独立乘区（模式 per_system_clear——element_burst_3 元素裁决）。

    对 key 列表里每个 stacks≥1 的系各 ×(1+per_system)（层数不累加，有层就乘）：
    desc 元素裁决：结算三系印记，每系 ×1.2（火/冰/雷各挂过印才触发对应系）。
    """
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    info = ctx.get("info") or {}
    if info.get("mech") != params.get("mech"):
        return
    actor = _holder(params.get("owner"), ctx, caster, target)
    effects = actor.get("effects") or {}
    ps = float(params.get("per_system") or 0)
    factor = 1.0
    hit_systems = []
    for k in _key_list(params.get("key")):
        ef = effects.get(k)
        n = int(ef.get("stacks", 0) or 0) if isinstance(ef, dict) else 0
        if n > 0:
            factor *= 1.0 + ps
            hit_systems.append(k)
    if not hit_systems:
        return
    ctx["mult"] = float(ctx.get("mult", 1.0) or 1.0) * factor
    label = params.get("label") or params.get("mech") or ""
    icon = params.get("icon") or "💥"
    logs.append(f"{icon} {label}！结算 {'、'.join(hit_systems)}，伤害 ×{factor:.2f}")


@register_action("class_res_channel_gain")
def class_res_channel_gain(battle, caster, target, params, logs):
    """职业资源渠道 gain（v181.M-R2d）：owner.effects[res].stacks += gain。

    装配层从 EFFECT_RULES 条目 channels 声明生成（归属职业 start_classes 已过滤）：
    - res/gain/label 全由声明写入，动作零资源 key 硬编码
    - kind / not_basic 事件过滤（heal_cast 时机只认 kind=治疗 行动——普攻/攻击技能
      施放不触发，防误攒；参数由装配时从渠道时机映射写入）
    - per_dt（tick 渠道）：gain × ctx["dt"]（每刻量按 dt 缩放——time_advance 的
      推进步长可能 ≠1.0 刻）
    - cap clamp 查 _cap_of（v181.M-R2e 方案 A 收敛：EFFECT_RULES 基础 + actor
      bonus.cap 动态（v181.M-bonus 分域）——faith 上限词条 divine_radiance/holy_heart 生效）；
      stacks float 读/写归一（B3——衰减后 3.9 +2 → 5.9 精度保真）
    - 写后广播 threshold（v181.M-R2e B2：渠道攒到满 cap 的当次触发——过载钩子
      依赖；对齐 effects.apply op=add 的 threshold 广播口径）
    """
    from saintess_engine.battle.actors import actor_alive
    from saintess_engine.battle.effects import cap_of as _cap_fn, norm_stack as _ns
    owner = params.get("_owner") or caster
    if owner is None or not actor_alive(owner):
        return
    # when 条件门（渠道声明 rc["when"]）：不满足 → 本次不攒。
    # 零默认值铁律：无 when 声明恒放行（旧渠道声明零影响）。
    if not _when_ok(owner, params):
        return
    ctx = getattr(battle, "_fire_ctx", None) or {}
    info = ctx.get("info") or {}
    kind = params.get("kind")
    if kind and (info.get("kind") or "") != kind:
        return
    if params.get("not_basic") and info.get("_basic"):
        return
    res = params.get("res") or ""
    gain = float(params.get("gain") or 0)
    # per_dt（tick 渠道声明）：每刻量按事件 dt 缩放——time_advance 的 dt 可能非
    # 1.0 刻（大盘跳步），恒量直加会错。缺 dt 视作 1.0（引擎 time_advance ctx 恒带 dt）。
    if params.get("per_dt"):
        gain *= float(ctx.get("dt", 1.0) or 1.0)
    if not res or gain <= 0:
        return
    cap = _cap_fn(owner, res)
    ef = owner.setdefault("effects", {})
    entry = ef.get(res)
    cur = float(entry.get("stacks", 0) or 0) if isinstance(entry, dict) else 0.0
    if cur >= cap:
        return
    n = max(0.0, min(float(cap), cur + gain))
    if abs(n - cur) < 1e-9:
        return
    if not isinstance(entry, dict):
        entry = ef[res] = {}
    entry["stacks"] = _ns(n)
    cap_txt = f"/{cap}" if cap < 999999 else ""
    logs.append(f"{params.get('icon') or '✦'} {params.get('label') or res} "
                f"+{_ns(gain):g}（{_ns(n)}{cap_txt}）")
    # v181.M-R2e B2：叠层变化后广播 threshold（过载/阈值机制同一口径）。
    # v181 磐核：嵌套 fire 会覆写 battle._fire_ctx —— 广播前存、广播后还原，
    # 否则同一事件批次里**排在渠道后的动作**（如 guard_core_burst 的 skill_hit
    # 清层 mech_cash_clear 读 info.mech）会读到 threshold ctx 而静默失效。
    try:
        from saintess_engine.battle.effect_triggers import fire as _fire
        _prev_ctx = getattr(battle, "_fire_ctx", None)
        _fire(battle, "threshold", {"actor": owner, "key": res, "value": n}, logs)
        battle._fire_ctx = _prev_ctx
    except Exception:
        pass


@register_action("class_faith_load_tier")
def class_faith_load_tier(battle, caster, target, params, logs):
    """heal_calc：牧师信仰负载档位治疗乘区（v181.M-R2e B2）。

    施法者（_owner）查自身 effects[faith].stacks（float 保真——衰减 9.3 也准）→
    load_tiers 档位（max 升序，取首个 stacks<=max 的档：0-3 清醒 / 4-7 专注 ×1.25 /
    8-9 透支 ×1.5 / 10 过载 ×1.0）→ heal_mult 累乘进 ctx.mult。无条目/0 层 →
    清醒档 ×1.0（零行为）；超过末档 max（bonus.cap 抬 cap 超高瞬态）→ 末档兜底。
    """
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    owner = params.get("_owner") or caster
    if owner is None:
        return
    tiers = _faith_tiers()
    if not tiers:
        return
    entry = (owner.get("effects") or {}).get("faith")
    cur = float(entry.get("stacks", 0) or 0) if isinstance(entry, dict) else 0.0
    mult = 1.0
    label = ""
    for t in tiers:
        if not isinstance(t, dict):
            continue
        mx = float(t.get("max", 0) or 0)
        if mx < 0:
            continue
        if cur <= mx:
            mult = float(t.get("heal_mult", 1.0) or 1.0)
            label = str(t.get("label") or "")
            break
    else:
        # 超过末档 max（bonus.cap 抬 cap 后 10+ 层瞬态）：取最后一档声明
        _last = tiers[-1] if tiers else {}
        if isinstance(_last, dict):
            mult = float(_last.get("heal_mult", 1.0) or 1.0)
            label = str(_last.get("label") or "")
    if mult != 1.0:
        ctx["mult"] = float(ctx.get("mult", 1.0) or 1.0) * mult
        logs.append(f"✨ 信仰{label or '专注'}！治疗 ×{mult:.2f}（{cur:g} 层）")


@register_action("class_faith_overload")
def class_faith_overload(battle, caster, target, params, logs):
    """threshold：信仰叠到满 cap 的当次 → 过载（v181.M-R2e B2）。

    - 触发点 = 叠层 clamp 后 threshold 事件（effects.apply op=add/set 与渠道
      gain 均广播，subject=叠层者自己——只处理自己声明）
    - 判据：ctx.key==faith 且 ctx.value 达 _cap_of 满额（叠到 cap 当次）
    - 效果：faith 清零 + 我方全员回复 max_hp × overload_heal_pct（v130 旧值
      0.015；圣化被动 faith_overload_heal 属旧被动域，saintess_engine 未接——不乘）
    - 防重复：满层后的再次 clamp（已满 +n 仍广播 value=cap）不再触发——过载帧
      标记 _faith_overload_at（近 0.5 刻内只一次）；触发即清零自然离开满层，
      下次重新攒满才再次过载。
    """
    ctx = getattr(battle, "_fire_ctx", None) or {}
    if ctx.get("key") != "faith":
        return
    owner = params.get("_owner") or caster
    if owner is None:
        return
    try:
        from saintess_engine.battle.effects import cap_of as _cap_fn
        cap = _cap_fn(owner, "faith")
    except Exception:
        return
    val = float(ctx.get("value", 0) or 0)
    if val + 1e-9 < cap:
        return  # 未满 cap 不触发（threshold 每层变化都广播）
    now = float(getattr(battle, "_now", 0.0) or 0.0)
    last = float(owner.get("_faith_overload_at", -99.0) or -99.0)
    if now - last < 0.5:
        return  # 过载帧标记：同刻/近帧已过载（满后再次 clamp 广播不重复触发）
    owner["_faith_overload_at"] = now
    # 清零 + 全队回复（同 side 存活成员）
    ef = owner.setdefault("effects", {})
    fentry = ef.get("faith")
    if isinstance(fentry, dict):
        fentry["stacks"] = 0
    pct = 0.015
    try:
        from saintess_engine.battle.state_effects import state_def
        pct = float((state_def("faith") or {}).get("overload_heal_pct", 0.015) or 0.015)
    except Exception:
        pct = 0.015
    # 信念·圣化（faith_overload_heal：过载回血 ×(1+heal_up)——R2e 原注释待接，
    # 现被动装配就绪：学过圣化的牧师过载回血提升 heal_up（desc「过载时不再力竭，
    # 改为全队回血+30%」→ 全队回血量 ×1.3；数值读技能 passive dict 零硬编码）
    if _learned_proc(owner, "faith_overload_heal"):
        try:
            from saintess_engine.config import skill_info_of as skill_info
            for _s in (owner.get("learned_skills") or []):
                _i = skill_info(owner.get("class_name") or "", _s) or {}
                if isinstance(_i.get("passive"), dict) \
                        and (_i.get("passive") or {}).get("proc") == "faith_overload_heal":
                    _up = float((_i.get("passive") or {}).get("heal_up", 0) or 0)
                    if _up > 0:
                        pct = pct * (1.0 + _up)
                    break
        except Exception:
            pass  # 圣化增强异常不阻断过载（容错铁律）
    from saintess_engine.battle.actors import actor_alive
    from saintess_engine.battle.landing import heal_actor
    healed = 0
    side = owner.get("side") or "player"
    for _a in (getattr(battle, "sides", None) or {}).get(side, []) or []:
        if not actor_alive(_a):
            continue
        _val = max(1, int((_a.get("max_hp", 1) or 1) * pct))
        _real = heal_actor(battle, _a, _val, logs)
        if _real > 0:
            healed += _real
    logs.append(f"⚡ 信仰过载！圣光迸发，全员回复 {healed} 点生命！"
                if healed > 0 else "⚡ 信仰过载！信念归零（全员生命已满）！")


@register_action("class_melody_act")
def class_melody_act(battle, caster, target, params, logs):
    """act_cast：mech=melody（唱新歌/换歌）| mech=melody_chant（吟唱叠层）。"""
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    actor = ctx.get("actor") or caster
    info = ctx.get("info") or {}
    mech = info.get("mech")
    if mech not in ("melody", "melody_chant"):
        return
    ef = actor.setdefault("effects", {})
    if mech == "melody":
        kind = info.get("melody") or ""
        if kind not in _MELODY_AURA_MAP and kind not in _MELODY_ENEMY_AURA_MAP:
            logs.append("🎵 这首曲式（" + str(kind) + "）尚未谱成……")
            return
        enemy_dir = kind in _MELODY_ENEMY_AURA_MAP
        ef["melody_state"] = {
            "stacks": 1, "kind": kind,
            "pct": float(info.get("melody_pct") or 0),
            "name": info.get("name") or "",
            "fin_kind": info.get("finale") or "",
            "fin_pct": float(info.get("melody_fin_pct") or 0),
            "fin_turns": int(info.get("buff_turns") or 8),
            # 挽歌系终章控制刻数（finale=silence/stun——desc 权威「沉默 3.0 刻 /
            # 定身 3.5 刻」；引擎控制 turns 走 int 化，半刻向下取整）
            "fin_ctrl": float(info.get("melody_fin_turns") or 0),
        }
        _melody_ensure_tick(actor, kind)
        _melody_write_aura(battle, actor, logs)
        logs.append(f"🎵 奏响【{ef['melody_state']['name']}】！旋律驻留，"
                    + ("敌方全体受挫！" if enemy_dir else "全队获得光环！"))
        return
    state = ef.get("melody_state")
    if not isinstance(state, dict) or not state.get("kind"):
        logs.append("🎵 尚无旋律奏响——先唱一首歌吧！（战歌/守歌/疾歌）")
        return
    stack = int(state.get("stacks") or 1)
    _fin_tok = state.get("fin_kind") or ""
    _fin_known = (_fin_tok in _MELODY_FIN_MAP or _fin_tok in _MELODY_ENEMY_FIN_MAP
                  or _fin_tok in _MELODY_FIN_CTRL_MAP)
    if stack >= _MELODY_MAX_STACK:
        if _fin_known:
            _melody_finale(battle, actor, state, logs)
            state["stacks"] = 1
            _melody_write_aura(battle, actor, logs)
        else:
            logs.append(f"🎵 旋律已至巅峰（{_MELODY_MAX_STACK} 层）——此曲无终章，保持最强音吧")
        return
    state["stacks"] = stack + 1
    _melody_write_aura(battle, actor, logs)
    logs.append(f"🎵 吟唱回旋，【{state.get('name')}】强度 +1"
                f"（{state['stacks']}/{_MELODY_MAX_STACK}）！")


@register_action("passive_melody_duet")
def passive_melody_duet(battle, caster, target, params, logs):
    """act_cast：吟唱后旋律强度额外 +add（二重唱，v169.7）。

    语义源 = 旧 battle.py `_skill_buff` 吟唱段 + `flag_set_cond` melody_duet 分支逐字：
    外层 mech == melody_chant 守卫 → 已有旋律驻留（name 非空且强度 >0）→ 强度
    min(上限, 当前+add)（旧 MELODY_CFG.max_stack=5）→ 驻留光环按新强度重写；
    日志「二重唱，旋律强度额外 +1！（N/5）」原样。数值 add 读被动 dict（零硬编码）。
    顺序契约：`class_melody_act` 排 act_cast 首位（基础叠层先完成，本段才读得到新强度）。
    """
    ctx = getattr(battle, "_fire_ctx", None) or {}
    judge = params.get("judge") or {}
    info = ctx.get("info") or {}
    if (info.get("mech") or "") != (judge.get("mech") or "melody_chant"):
        return
    actor = ctx.get("actor") or caster
    try:
        add = int(params.get("add", 0) or 0)
    except Exception:
        add = 0
    if actor is None or add <= 0:
        return
    state = (actor.get("effects") or {}).get("melody_state")
    if not isinstance(state, dict) or not state.get("name") \
            or int(state.get("stacks", 0) or 0) <= 0:
        return
    state["stacks"] = min(_MELODY_MAX_STACK, int(state.get("stacks", 0) or 0) + add)
    _melody_write_aura(battle, actor, logs)
    logs.append(f"🎶 {params.get('label') or '二重唱'}：二重唱，旋律强度额外 +{add}！"
                f"（{state['stacks']}/{_MELODY_MAX_STACK}）")


@register_action("class_melody_dirge_tick")
def class_melody_dirge_tick(battle, caster, target, params, logs):
    """time_advance：时钟驱动的挽歌驻留旋律（沉默之歌 e_silence）对敌封印技能。

    语义源 = 旧 battle_mech._melody_apply_e_buffs 的 e_silence 段（写
    melody_silence_lock，消费点在旧 battle.py 敌方出手段「距上次封印 ≥4 刻则沉默 1 刻」）
    —— saintess_engine 敌方出手段随 N10 删除，收口为 time_advance 时钟 tick：驻留期间每
    ≥4 刻（_MELODY_SILENCE_TICK，desc「每 4 刻至多 1 次」）对敌方全体施 1 次封印
    （时长 = 节流间隔：驻留期间持续封印、每 4 刻刷新）。

    宿主 = 声明者自身（_owner，fire 注入）；无驻留 / 非 e_silence → 零行为。
    """
    host = params.get("_owner") or caster
    if not isinstance(host, dict):
        return
    state = (host.get("effects") or {}).get("melody_state")
    if not isinstance(state, dict) or state.get("kind") != "e_silence" \
            or int(state.get("stacks", 0) or 0) <= 0:
        return
    try:
        now = float(getattr(battle, "_now", 0) or 0)
    except Exception:
        now = 0.0
    last = state.get("_silence_at")
    if last is not None and now - float(last) < _MELODY_SILENCE_TICK:
        return
    state["_silence_at"] = now
    for _foe in _melody_side_actors(battle, host, True):
        _melody_ctrl_apply(battle, host, _foe, "silence",
                           int(_MELODY_SILENCE_TICK), logs)
    logs.append("🎵 挽歌低沉：敌方技能被封（每 4 刻至多 1 次）！")


@register_action("passive_ctrl_extend")
def passive_ctrl_extend(battle, caster, target, params, logs):
    """skill_hit / act_cast：挽歌系控制对敌施加后时长 +add 刻（镇魂安魂 dirge_ctrl_up）。

    语义源 = 旧 battle.py 挂点18 `_skill_hit_settle` 控制延长段逐字（game/core/
    passive_procs.py `_h_flag_set_cond::dirge_ctrl_up`）：本技能施控（mech/mech2/cc
    ∈ 控制键，或旋律 finale 产出控制）→ 遍历控制键找首个生效键 → +add 刻 + 日志
    （首条）；半刻不支持（add 数据已向下取整：desc +1.5 → add=1）。
    saintess_engine 控制条目 = effects[key].expire（刻制：延长 = expire += add）。
    """
    ctx = getattr(battle, "_fire_ctx", None) or {}
    judge = params.get("judge") or {}
    owner = params.get("_owner") or ctx.get("actor") or caster
    if owner is None:
        return
    try:
        add = float(params.get("add", 0) or 0)
    except Exception:
        add = 0.0
    if add <= 0:
        return  # 缺字段 = 无此行为（零默认值铁律）
    ctrl_keys = judge.get("ctrl_keys") or ("stun", "freeze", "silence", "sleep", "spd_down")
    info = ctx.get("info") or {}
    # 门：本次技能确为施控技（旧引擎同门：mech/mech2/cc ∈ 控制键；挽歌旋律终章的
    # 控制在 act_cast 落，finale token 视同施控）
    _declared = {info.get("mech") or "", info.get("mech2") or "", info.get("cc") or ""}
    if (info.get("mech") or "") == "melody":
        _declared.add(info.get("finale") or "")
    if not (_declared & set(ctrl_keys)):
        return
    # 宿主（控制落点）：命中目标优先（skill_hit 路径），否则扫对立阵营
    hosts = []
    _tg = ctx.get("target")
    if isinstance(_tg, dict):
        hosts.append(_tg)
    for _foe in _melody_side_actors(battle, owner, True):
        if _foe is not _tg:
            hosts.append(_foe)
    try:
        now = float(getattr(battle, "_now", 0) or 0)
    except Exception:
        now = 0.0
    for _ck in ctrl_keys:
        for host in hosts:
            entry = (host.get("effects") or {}).get(_ck)
            if not isinstance(entry, dict):
                continue
            exp = entry.get("expire")
            if exp is None or float(exp) <= now:
                continue  # 无到期/已过期 → 非生效控制
            entry["expire"] = float(exp) + add
            logs.append(f"🎵 {params.get('label') or '镇魂安魂'}："
                        f"挽歌延长【{_ck}】控制 +{int(add)} 刻！")
            return


@register_action("passive_dmg_mult")
def passive_dmg_mult(battle, caster, target, params, logs):
    """dmg_calc 条件乘区：judge 命中 → ctx.mult ×(1+mult)（对齐 N9.7d 词条乘区）。

    judge kind（谓词扩展 P2）：
    - mech_eq          本次技能 mech == judge.mech → mult 参数
    - mech_prefix      本次技能 mech 以 judge.mech 开头（poison_burst 覆盖毒爆两种技）
    - target_marks_all_ge  目标多印记都 ≥layers → mult 参数
    - target_mark_any  目标带标记（层数>0）→ mult = per_layer × 层数（标记额外增伤，
                      旧挂点14 增量并入语义——基础段 EFFECT_RULES debuff_scale 天然处理）
    """
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    judge = params.get("judge") or {}
    kind = judge.get("kind") or ""
    actor = ctx.get("actor") or caster
    tg = ctx.get("target") or target
    info = ctx.get("info") or {}
    mult = 0.0
    ok = False
    if kind == "mech_eq":
        ok = (info.get("mech") or "") == judge.get("mech")
        if ok:
            mult = float(params.get("mult") or params.get("dmg_add") or 0)
    elif kind == "mech_prefix":
        _pre = judge.get("mech") or ""
        ok = bool(_pre) and (info.get("mech") or "").startswith(str(_pre))
        if ok:
            mult = float(params.get("mult") or params.get("dmg_add") or 0)
    elif kind == "target_marks_all_ge":
        layers = float(params.get("layers") or judge.get("layers") or 1)
        if tg is not None:
            ef = tg.get("effects") or {}
            ok = all(
                float((ef.get(m) or {}).get("stacks", 0) or 0) >= layers
                for m in (judge.get("marks") or []))
            if ok:
                mult = float(params.get("mult") or 0)
    elif kind == "target_mark_any":
        # 标记额外增伤：目标带标记（层>0）→ ×(1 + per_layer×层)
        mark = judge.get("mark") or ""
        if tg is not None and mark:
            _entry = (tg.get("effects") or {}).get(mark)
            _n = int(_entry.get("stacks", 0) or 0) if isinstance(_entry, dict) else 0
            if _n > 0:
                ok = True
                mult = float(params.get("per_layer") or 0) * _n
    elif kind == "target_debuff_kinds":
        # 挽歌·极 dirge_debuff_dmg：目标负面「种数」→ ×(1 + min(per_debuff×种数, cap))
        # 旧语义源 = game/core/passive_procs.py 挂点14 dirge_debuffs handler 逐字：
        #   pct = min(ps.per_debuff × battle._enemy_debuff_kind_count(), ps.cap)
        # （旧引擎数 debuffs 容器种数 + e_buffs 控制/减益键；saintess_engine 单容器 effects →
        #  种数口径 = 声明 negative=True 或 on=target 的条目：控制/减益旋律/减益/
        #  DOT/挂敌身印记，与旧清单等价、数据驱动零硬编码）。
        # 数值 per_debuff/cap 来自技能 passive dict（0.04 / 0.40，desc 权威）。
        _per = float(params.get("per_debuff") or 0)
        _cap = float(params.get("cap") or 0)
        if tg is not None and _per > 0 and _cap > 0:
            from saintess_engine.battle.state_effects import state_def as _sd
            _kinds = 0
            for _k, _v in (tg.get("effects") or {}).items():
                if not isinstance(_v, dict):
                    continue
                _cfg_k = _sd(_k)
                if _cfg_k.get("negative") or _cfg_k.get("on") == "target":
                    _kinds += 1
            _pct_d = min(_per * _kinds, _cap)
            if _pct_d > 0:
                ok = True
                mult = _pct_d
    elif kind == "speed_ratio_ge":
        # 速度比 ≥ ratio_field → ×(1+dmg_add)（疾风·极；旧挂点4 语义：
        # 敌方无速度按 0 防御性跳过——速度比恒 ≥2 不触发）
        try:
            from saintess_engine.battle.stats import actor_stats as _as
            _spd_a = float((_as(battle, actor) or {}).get("spd", 0) or 0)
            _spd_t = float((_as(battle, tg) or {}).get("spd", 0) or 0) if tg is not None else 0.0
        except Exception:
            _spd_a = _spd_t = 0.0
        _ratio = float(params.get("ratio") or judge.get("ratio") or 0)
        if _ratio > 0 and _spd_t > 0 and _spd_a >= _ratio * _spd_t:
            ok = True
            mult = float(params.get("dmg_add") or params.get("mult") or 0)
    elif kind in ("target_bar_ge", "target_bar_broken"):
        # 挂敌身条（actor.effects[BAR_STATE_PREFIX+bar] = {val, threshold,
        # trigger_count, immune_until, _at}）消费：
        # - target_bar_ge     条积蓄 ≥ 门槛（气力之心：破绽 ≥15 → ×1.2；门槛读
        #                     params[ge_field]，默认 bar_at——数值全来自被动 dict）
        # - target_bar_broken 条处于破防态（trigger_count>0 且在免疫窗口内；
        #                     破绽·极乘区段 ×1.5，倍率读 params.broken_mult）
        # （推条/触发/衰减由 core/battle_bars + battle_bar_procs 负责，本判定
        #   只把条结算到当刻再读——引擎零名词。）
        _bar = judge.get("bar") or params.get("bar") or ""
        _bs_j = None
        if tg is not None and _bar:
            from saintess_engine.gauge import bar_settle, bar_effect_key
            _now_j = float(getattr(battle, "_now", 0.0) or 0.0)
            bar_settle(tg, _bar, _now_j)
            _bs_j = (tg.get("effects") or {}).get(bar_effect_key(_bar))
        if isinstance(_bs_j, dict):
            if kind == "target_bar_ge":
                _need = float(params.get(judge.get("ge_field") or "bar_at") or 0)
                if _need > 0 and float(_bs_j.get("val", 0.0) or 0.0) >= _need:
                    ok = True
                    mult = float(params.get("mult") or params.get("dmg_add") or 0)
            else:
                _imm = float(_bs_j.get("immune_until", 0.0) or 0.0)
                if int(_bs_j.get("trigger_count", 0) or 0) > 0 \
                        and _imm > float(getattr(battle, "_now", 0.0) or 0.0):
                    ok = True
                    mult = float(params.get("broken_mult") or params.get("mult")
                                 or params.get("dmg_add") or 0)
    if not ok or mult <= 0:
        return
    ctx["mult"] = float(ctx.get("mult", 1.0) or 1.0) * (1.0 + mult)
    logs.append(f"✨ 被动生效：伤害 ×{1.0 + mult:.2f}！")


@register_action("passive_bar_extend")
def passive_bar_extend(battle, caster, target, params, logs):
    """skill_hit 触发后置：目标挂条处于破防态 → 免疫窗口 +extend 刻（破绽·极）。

    语义源 = 旧 battle.py `_skill_hit_settle` bar_trigger 后 shaken 段逐字：本次
    命中刚触发（trigger_count>0）且仍在免疫窗口内 → 免疫截止时刻 +extend
    （v169.7 注：半刻不支持 → 数据向下取整取 1）。
    参数：judge.bar（条名）/ params.extend（刻数，来自被动 dict）。
    装配顺序依赖：挂条动词（bar_gain）须先于本段执行（见 battle_bar_procs
    apply_bar_procs 头部 insert 注释）。
    """
    ctx = getattr(battle, "_fire_ctx", None) or {}
    judge = params.get("judge") or {}
    host = ctx.get("target")
    if not isinstance(host, dict):
        host = target
    bar = judge.get("bar") or params.get("bar") or ""
    try:
        ext = float(params.get("extend", 0) or 0)
    except Exception:
        ext = 0.0
    if not bar or ext <= 0 or not isinstance(host, dict):
        return
    from saintess_engine.gauge import bar_effect_key
    bs = (host.get("effects") or {}).get(bar_effect_key(bar))
    if not isinstance(bs, dict):
        return
    if int(bs.get("trigger_count", 0) or 0) <= 0:
        return
    _now = float(getattr(battle, "_now", 0.0) or 0.0)
    if float(bs.get("immune_until", 0.0) or 0.0) <= _now:
        return
    bs["immune_until"] = float(bs.get("immune_until", 0.0) or 0.0) + ext
    logs.append(f"✨ {params.get('label') or '被动'}：破防持续 +{int(ext)} 刻！")


@register_action("passive_kill_gain")
def passive_kill_gain(battle, caster, target, params, logs):
    """on_kill 资源回满：击杀者 effects[key] 置 cap（追风：专注回满）。"""
    ctx = getattr(battle, "_fire_ctx", None) or {}
    actor = ctx.get("actor") or caster
    if actor is None:
        return
    key = params.get("key") or "energy"
    from saintess_engine.battle.effects import cap_of as _cap_fn
    cap = _cap_fn(actor, key)
    if cap <= 0:
        return
    ef = actor.setdefault("effects", {})
    if not isinstance(ef.get(key), dict):
        ef[key] = {}
    ef[key]["stacks"] = float(cap)
    ef[key]["expire"] = None
    logs.append(f"✨ {params.get('label') or '被动'}:{'资源回满！'}")


@register_action("passive_counter")
def passive_counter(battle, caster, target, params, logs):
    """on_taken 受击反击（聚合族装配后终值单条）：roll chance → atk×atk_pct 反打攻击方。

    语义 = 旧挂点13 聚合收口 + we_affix_counter 落地动作（反击方向=攻击方，
    on_taken ctx.source；伤害 = 攻击者面板 atk × atk_pct 直伤打防御）。
    """
    owner = params.get("_owner") or caster
    if owner is None:
        return
    ctx = getattr(battle, "_fire_ctx", None) or {}
    attacker = ctx.get("source")  # on_taken 攻击方
    from saintess_engine.battle.actors import actor_alive
    if attacker is None or not actor_alive(attacker):
        return
    import random as _r
    chance = float(params.get("chance") or 0)
    if chance <= 0 or _r.random() >= chance:
        return
    try:
        from saintess_engine.battle.landing import deal_damage
        from saintess_engine.battle.stats import actor_stats as _as
        st = _as(battle, owner) or {}
        dmg = max(1, int(float(st.get("atk", 0) or 0)
                           * float(params.get("atk_pct") or 0.80)))
        deal_damage(battle, owner, attacker, dmg, logs)
        logs.append(f"⚔️ 反击！对【{attacker.get('name', '敌人')}】造成 {dmg} 点伤害！")
    except Exception:
        pass  # 反击异常不阻断受击落地


@register_action("passive_cond_crit")
def passive_cond_crit(battle, caster, target, params, logs):
    """act_cast 条件暴击：资源 ≥ 阈值（+技能系/非普攻门槛）→ 本次行动暴击加算 buff。

    语义 = 旧挂点1 _passive_crit_bonus（crit_cond_add）逐字：资源层数（战意/奥术/精力）
    ≥ 阈值 → 暴击率 +add（绝对点）。实现 = effects buff 快照型条目
    {stat: crit, mult: add, op: add}（stats._apply_effects 兼容路径，无需 EFFECT_RULES
    声明）——act_cast 在 crit 判定前 fire（扣费后、伤害管线前），buff 覆盖整个行动；
    下次行动动作重写/清除，无残留。
    judge 参数：res（资源 key）/ ge_field（passive dict 阈值字段名）/ mech（可选技能系
    过滤）/ not_basic（普攻不吃）。add 来自 passive dict。
    """
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    actor = ctx.get("actor") or caster
    if actor is None:
        return
    info = ctx.get("info") or {}
    judge = params.get("judge") or {}
    buff_key = params.get("buff_key") or ""
    if not buff_key:
        return
    ef = actor.setdefault("effects", {})
    # 普攻排除（desc「下次技能暴击」）：basic 行动直接清旧残留并跳过
    if judge.get("not_basic") and info.get("_basic"):
        ef.pop(buff_key, None)
        return
    # 技能系过滤（desc「奥术暴击」）：info.mech 不匹配 → 清残留跳过
    mech = judge.get("mech")
    if mech and (info.get("mech") or "") != mech:
        ef.pop(buff_key, None)
        return
    res = judge.get("res") or ""
    ge_field = judge.get("ge_field") or ""
    need = float(params.get(ge_field) or 0)
    add = float(params.get("add") or 0)
    if not res or need <= 0 or add <= 0:
        ef.pop(buff_key, None)  # 缺字段 = 无此行为
        return
    _entry = ef.get(res)
    cur = float(_entry.get("stacks", 0) or 0) if isinstance(_entry, dict) else 0.0
    # 施放前快照还原（旧挂点 _pre_cost_res 语义）：act_cast 在 _spend_skill_cost
    # 之后 fire——若本技能 res_cost 扣了该资源，施放前结余 = 当前 + 已扣额
    # （疾风之心 desc「结余 ≥40」= 施放前判定，非扣费后）
    _rc = (info.get("res_cost") or {})
    if isinstance(_rc, dict) and res in _rc:
        try:
            cur += float(_rc.get(res, 0) or 0)
        except Exception:
            pass
    if cur >= need:
        # 命中 → 重写 buff（防多次行动叠加/陈旧值）
        ef[buff_key] = {"stacks": 1, "stat": "crit", "mult": add,
                        "op": "add", "expire": None}
        logs.append(f"✨ 被动生效：暴击 +{int(add * 100)}%！")
    else:
        ef.pop(buff_key, None)


@register_action("passive_taken_reduce")
def passive_taken_reduce(battle, caster, target, params, logs):
    """taken_calc 条件减伤：judge 谓词命中 → ctx.mult ×(1-reduce)（承伤者视角）。

    语义 = 旧挂点11 dr_cond 逐字；judge.kind 分派（缺字段=无此行为 / 未知 kind=fail-closed）：
      - res_ge     资源 ≥ 阈值：reduce 读 passive dict（坚城之姿 战意满 10 / 磐石之躯 磐核满 5）
      - has_effect 效果在位：守御姿态减伤 / 不动如山一次性 flag 常驻段
      - per_core   每核减伤：reduce = per_core × effects[judge.res].stacks（float 保真）
                   ——磐核基础 +3%（guard_core 声明）/ 大地之肤额外 +2%（旧 _h_dr_cond per_core 段）
    乘区模式对齐 we_taken_mult_cond（mult <1 = 减免）。reduce 来自 passive dict。
    """
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    owner = params.get("_owner") or ctx.get("actor") or caster
    if owner is None:
        return
    judge = params.get("judge") or {}
    kind = judge.get("kind") or "res_ge"
    if kind == "per_core":
        # 每核减伤：reduce = per_core × 持有层数（float 读——小数核保真）
        per = float(params.get("per_core") or 0)
        res = judge.get("res") or ""
        entry = (owner.get("effects") or {}).get(res) if res else None
        n = float(entry.get("stacks", 0) or 0) if isinstance(entry, dict) else 0.0
        if per <= 0 or n <= 0:
            return  # 缺字段/无核 = 无此行为
        reduce_v = per * n
    else:
        reduce_v = float(params.get("reduce") or 0)
        if reduce_v <= 0:
            return  # 缺字段 = 无此行为
        if kind == "has_effect":
            if not _has_effect_ok(owner, judge):
                return
        elif kind == "res_ge":
            if not _res_ge_ok(owner, judge, params):
                return
        else:
            return  # 未知 judge kind = fail-closed
    ctx["mult"] = float(ctx.get("mult", 1.0) or 1.0) * (1.0 - min(reduce_v, 0.9))
    logs.append(f"🛡️ {params.get('label') or '被动'}：减伤 {int(reduce_v * 100)}% 生效！")


@register_action("passive_cc_clear")
def passive_cc_clear(battle, caster, target, params, logs):
    """turn_start 免控清除：资源 ≥ 阈值 → 移除指定控制条目（免疫眩晕等）。

    语义 = 旧挂点10 stun_clear 段逐字（战意满 → 移除 stun——回合开始检查早于
    控制消费，等效免疫；被晕时下回合开始即被清，控制不生效）。
    """
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    owner = params.get("_owner") or ctx.get("actor") or caster
    if owner is None:
        return
    if not _res_ge_ok(owner, params.get("judge") or {}, params):
        return
    ctrl = params.get("ctrl") or ""
    if not ctrl:
        return
    ef = owner.get("effects") or {}
    entry = ef.get(ctrl)
    if isinstance(entry, dict) and entry.get("mode") == "skip":
        ef.pop(ctrl, None)
        logs.append(f"🛡️ {params.get('label') or '被动'}：免疫【{ctrl}】！")


@register_action("passive_cc_break")
def passive_cc_break(battle, caster, target, params, logs):
    """turn_start 消耗挣脱：被控（mode=skip）→ 资源 ≥cost + 次数余 → 扣资源挣脱。

    语义 = 旧 _tenacity_try_break 逐字：战意 ≥cost（默认2）且剩余次数>0 → 扣
    战意 + 次数-1（effects[left_key]，装配时 init=3 每场重置）→ 移除控制照常行动。
    """
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    owner = params.get("_owner") or ctx.get("actor") or caster
    if owner is None:
        return
    ef = owner.get("effects") or {}
    # 找 skip 控制（stun/freeze/sleep…mode=skip 一律可挣脱）
    hit_ctrl = None
    for _k, _e in ef.items():
        if isinstance(_e, dict) and _e.get("mode") == "skip":
            hit_ctrl = _k
            break
    if hit_ctrl is None:
        return
    res = params.get("res") or ""
    cost = float(params.get(params.get("cost_field") or "cost") or 0)
    if not res or cost <= 0:
        return  # 缺字段 = 无此行为
    _entry = ef.get(res)
    cur = float(_entry.get("stacks", 0) or 0) if isinstance(_entry, dict) else 0.0
    left_key = params.get("left_key") or ""
    _le = ef.get(left_key) if left_key else None
    left = float(_le.get("stacks", 0) or 0) if isinstance(_le, dict) else 0.0
    if cur < cost or left <= 0:
        return
    # 扣战意 + 次数-1 + 移除控制（旧 _tenacity_try_break 顺序）
    _entry["stacks"] = max(0, cur - cost)
    if left_key and isinstance(_le, dict):
        _le["stacks"] = left - 1
    ef.pop(hit_ctrl, None)
    logs.append(f"🛡️ {params.get('label') or '被动'}：消耗 {int(cost)} 层战意挣脱控制！")


@register_action("passive_lifesteal_buff")
def passive_lifesteal_buff(battle, caster, target, params, logs):
    """act_cast 吸血 buff：每层资源 → 面板 lifesteal 加算（淬血 1.5%/层战意）。

    语义 = 旧挂点5 _settle_lifesteal 吸血率加算（每层战意 +per_layer，cap 30% 引擎保留）
    ——buff 快照条 {stat: lifesteal, mult: per_layer×层, op: add}，行动内 _settle_lifesteal
    读面板吃到；下次行动重写/清除。
    """
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    actor = ctx.get("actor") or caster
    if actor is None:
        return
    res = params.get("res") or "zhan_yi"
    per = float(params.get("per_layer") or 0)
    buff_key = params.get("buff_key") or ""
    if per <= 0 or not buff_key:
        return  # 缺字段 = 无此行为
    ef = actor.setdefault("effects", {})
    _entry = ef.get(res)
    cur = float(_entry.get("stacks", 0) or 0) if isinstance(_entry, dict) else 0.0
    value = per * cur
    if value > 0:
        ef[buff_key] = {"stacks": 1, "stat": "lifesteal", "mult": value,
                        "op": "add", "expire": None}
    else:
        ef.pop(buff_key, None)


@register_action("passive_heal_overflow_shield")
def passive_heal_overflow_shield(battle, caster, target, params, logs):
    """heal_calc 治疗溢出转盾：计划治疗超出目标缺口部分 ×pct → 护盾（给被治疗者）。

    语义（NO_OLD，desc 权威）：圣光回响「治疗溢出量的 50% 转为护盾」——heal_calc
    在落地前（缺口未填充），溢出 = heal - 当前缺口。护盾结构对齐引擎 shield 动词
    （shields[key]={value, expire_at, halve}；转盾默认 3 刻）。
    """
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    owner = ctx.get("actor") or caster
    if owner is None:
        return
    tgt = ctx.get("target") or target
    if tgt is None:
        return
    heal = float(ctx.get("heal") or 0)
    pct = float(params.get("pct") or 0)
    if heal <= 0 or pct <= 0:
        return
    _mx = int(tgt.get("max_hp", 1) or 1)
    _cur_hp = int(tgt.get("hp", 0) or 0)
    gap = max(0, _mx - _cur_hp)
    overflow = max(0, int(heal) - gap)
    if overflow <= 0:
        return
    val = max(1, int(overflow * pct))
    try:
        from saintess_engine.battle import now_of
        now = now_of(battle)
    except Exception:
        now = 0.0
    sh = tgt.setdefault("shields", {})
    key = "heal_overflow"
    expire = now + 3  # 转盾默认 3 刻（shield 动词缺省 turns=3）
    cur = sh.get(key)
    if isinstance(cur, dict):
        cur["value"] = int(cur.get("value", 0) or 0) + val
        if cur.get("expire_at") is not None:
            cur["expire_at"] = max(float(cur.get("expire_at", 0) or 0), expire)
    else:
        sh[key] = {"value": val, "expire_at": expire, "halve": False}
    logs.append(f"🛡️ {params.get('label') or '被动'}：治疗溢出 {overflow}，转化护盾 {val} 点！")


@register_action("mech_cash_fury_enter")
def mech_cash_fury_enter(battle, caster, target, params, logs):
    """act_cast 狂暴进入（血祭 zhan_yi_fury 兑现）：花 res 层战意 → effects[fury]。

    语义（v153 CLASS_MECHANICS_v153 战士血怒线）：血祭花 4 层战意（无视 10 层
    门槛）立即进入狂暴。fury 条目声明 EFFECT_RULES stat_scale atk +20%。
    战意不足 → 不进入（技能无 res_cost 前置，兑现兜底判）。
    """
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    owner = params.get("_owner") or ctx.get("actor") or caster
    if owner is None:
        return
    info = ctx.get("info") or {}
    mech = info.get("mech") or ""
    if mech != "zhan_yi_fury":
        return
    res = params.get("res") or "zhan_yi"
    cost = int(info.get(params.get("mech_val_field") or "mech_val") or 0)
    if cost <= 0:
        return  # 缺字段 = 无此行为
    ef = owner.get("effects") or {}
    _entry = ef.get(res)
    cur = float(_entry.get("stacks", 0) or 0) if isinstance(_entry, dict) else 0.0
    if cur < cost:
        logs.append(f"🔥 战意不足（{int(cur)}/{cost}），无法进入狂暴！")
        return
    _entry["stacks"] = max(0, cur - cost)
    owner.setdefault("effects", {})["fury"] = {"stacks": 1, "expire": None}
    logs.append(f"🔥 {params.get('label') or '狂暴'}！战士进入狂暴状态，攻击 +20%！")


@register_action("passive_dot_mult")
def passive_dot_mult(battle, caster, target, params, logs):
    """dot_calc DOT 乘区：dot_key 匹配 → ctx.mult ×(1+mult)（施毒者被动万毒归宗）。

    语义 = 旧挂点 DOT 伤害结算处毒伤乘区（所有毒层伤害 +mult）。dot_calc 是
    broadcast 事件（施毒者在施放方、承伤者在 target——subject 过滤会挡住），
    owner=_owner（fire 注入声明者）自查归属；dot_key 过滤只加成指定 DOT。
    """
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    owner = params.get("_owner") or caster
    if owner is None:
        return
    dot_key = ctx.get("dot_key") or ""
    judge = params.get("judge") or {}
    allow = judge.get("dot_key") or ""
    if allow and dot_key != allow:
        return
    mult = float(params.get("mult") or params.get("dmg_add") or 0)
    if mult <= 0:
        return  # 缺字段 = 无此行为
    ctx["mult"] = float(ctx.get("mult", 1.0) or 1.0) * (1.0 + mult)
    logs.append(f"☠️ {params.get('label') or '被动'}：DOT 伤害 ×{1.0 + mult:.2f}！")


@register_action("passive_poison_weaken")
def passive_poison_weaken(battle, caster, target, params, logs):
    """dot_calc 毒层条件 debuff：目标毒 ≥layers → 减速降防（剧毒之触，desc 权威）。

    语义（NO_OLD desc）：目标毒层 ≥5 时减速 30%、降防 20%——dot_calc 每跳广播时
    检查承伤者毒层（效果持续 = 每跳续期 hold 刻，毒止跳后 debuff 自然到期消散）。
    effects 快照条目折算对齐现网 we_ 减速/降防（stat spd/def op mul）。
    """
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    owner = params.get("_owner") or caster
    if owner is None:
        return
    dot_key = ctx.get("dot_key") or ""
    judge = params.get("judge") or {}
    if judge.get("dot_key") and dot_key != judge.get("dot_key"):
        return
    tgt = ctx.get("target")
    if tgt is None:
        return
    _pe = (tgt.get("effects") or {}).get("poison")
    n = int(_pe.get("stacks", 0) or 0) if isinstance(_pe, dict) else 0
    layers_field = judge.get("layers_field") or ""
    need = float(params.get(layers_field) or 0)
    if need <= 0 or n < need:
        return  # 毒层不足 = 无此行为
    spd_pct = float(params.get("spd_pct") or 0)
    def_pct = float(params.get("def_pct") or 0)
    if spd_pct <= 0 and def_pct <= 0:
        return
    try:
        from saintess_engine.battle import now_of
        exp = now_of(battle) + float(params.get("hold") or 2.0)
    except Exception:
        exp = None
    ef = tgt.setdefault("effects", {})
    if spd_pct > 0:
        ef["spd_down"] = {"stat": "spd", "op": "mul", "mult": 1.0 - spd_pct,
                          "expire": exp}
    if def_pct > 0:
        ef["def_down"] = {"stat": "def", "op": "mul", "mult": 1.0 - def_pct,
                          "expire": exp}
    logs.append(f"🐍 {params.get('label') or '被动'}：剧毒缠身，目标减速降防！")


@register_action("class_shadow_dance_enter")
def class_shadow_dance_enter(battle, caster, target, params, logs):
    """增益技 effect=shadow_dance（暗影步）：连段 ≥5 → 进入影舞态。

    语义（v153 影舞者线）：暗影步「连段满 5 → 进入影舞态」——effects[shadow_dance]
    1 层（cd_mult 0.8 态内 CD−20% 引擎通用修正）。连段不足 → 提示不进入。
    """
    actor = caster if caster is not None else target
    if actor is None:
        return
    ef = actor.get("effects") or {}
    _le = ef.get("lian_duan")
    n = float(_le.get("stacks", 0) or 0) if isinstance(_le, dict) else 0.0
    # v2026-09-11 裁定：入场门槛 = 5，学过「影舞·无间」（proc shadow_dance_ease，
    #   threshold 参数）后降为 3。原实现的门槛 5 写死；原 proc shadow_dance_cd
    #   （态内 CD −20%）与影舞态自带 cd_mult 0.8 重复，已改词为门槛放宽。
    _req = int(_learned_proc_param(actor, "shadow_dance_ease", "threshold", 5) or 5)
    if n < _req:
        logs.append(f"🌫️ 连段不足（{int(n)}/{_req}），无法进入影舞态！")
        return
    actor.setdefault("effects", {})["shadow_dance"] = {"stacks": 1, "expire": None}
    logs.append("🌫️ 踏入影舞之境！技能 CD −20%，如影随形！")


@register_action("class_stance_guard_enter")
def class_stance_guard_enter(battle, caster, target, params, logs):
    """增益技 effect=stance_guard（守护姿态 v153 铁誓线）：写守护姿态态 + 挂反击。

    语义：守护姿态「受击反击 40%、每刻积攒 0.2 战意」——effects[stance_guard]
    持续 turns 刻（技能 buff_turns）；反击 = on_taken trigger（class_stance_counter，
    态在才反击 40%，防重复挂）；每刻 +0.2 战意需 tick 装配点标缺口。
    """
    actor = caster if caster is not None else target
    if actor is None:
        return
    try:
        from saintess_engine.battle import now_of
        now = now_of(battle)
    except Exception:
        now = 0.0
    turns = max(1, int(params.get("turns") or 0) or 8)
    actor.setdefault("effects", {})["stance_guard"] = {
        "stacks": 1, "expire": now + turns}
    # 挂受击反击 trigger（幂等——同 key 不重复挂）
    trig = actor.setdefault("triggers", {})
    lst = trig.setdefault("on_taken", [])
    if not any(isinstance(t, dict) and t.get("type") == "class_stance_counter"
               for t in lst):
        lst.append({"type": "class_stance_counter", "chance": 0.40,
                    "atk_pct": 1.0, "label": "守护姿态"})
    logs.append(f"🛡️ 进入守护姿态：受击反击 40%（{turns} 刻）！")


@register_action("class_stance_counter")
def class_stance_counter(battle, caster, target, params, logs):
    """on_taken 守护姿态反击：态在 → 40% 反打攻击者 atk×100%（普攻全额）。"""
    ctx = getattr(battle, "_fire_ctx", None) or {}
    owner = params.get("_owner") or ctx.get("actor") or caster
    if owner is None:
        return
    if not isinstance((owner.get("effects") or {}).get("stance_guard"), dict):
        return  # 姿态已过期 → 不反击
    attacker = ctx.get("source")
    from saintess_engine.battle.actors import actor_alive
    if attacker is None or not actor_alive(attacker):
        return
    import random as _r
    chance = float(params.get("chance") or 0)
    if chance <= 0 or _r.random() >= chance:
        return
    try:
        from saintess_engine.battle.landing import deal_damage
        from saintess_engine.battle.stats import actor_stats as _as
        st = _as(battle, owner) or {}
        dmg = max(1, int(float(st.get("atk", 0) or 0)
                           * float(params.get("atk_pct") or 1.0)))
        deal_damage(battle, owner, attacker, dmg, logs)
        logs.append(f"🛡️ 守护反击！对【{attacker.get('name', '敌人')}】造成 {dmg} 点伤害！")
    except Exception:
        pass


@register_action("class_guard_stance_enter")
def class_guard_stance_enter(battle, caster, target, params, logs):
    """增益技 effect=guard_stance（守御姿态 v153 L992）：写姿态态 + 挂受击减伤乘区。

    语义（v153 L992）：「姿态：受伤 −25%，但推条值 −30%」
    - 受伤 −25%：数值单源 = EFFECT_RULES[guard_stance].stat_scale.reduce——saintess_engine
      伤害路径不消费 st["reduce"]（stats 只写、instance 仅展示），故装配时挂
      taken_calc 乘区钩子（passive_taken_reduce has_effect 段；形态同 warrior
      class_stance_guard_enter「写态 + 挂 trigger」）。
    - ⚠️ 推条值 −30%：推条注入端（battle_bar_procs.bar_gain）直读技能 shaken_gain，
      无按姿态的乘区通道 → 未落地（缺口）。
    态持续 turns 刻（技能 buff_turns，经 actions._do_buff 注入 params.turns）。
    """
    owner = caster if isinstance(caster, dict) else target
    if owner is None:
        return
    key = params.get("type") or ""
    if not key:
        return
    try:
        turns = int(params.get("turns") or 0)
    except Exception:
        turns = 0
    if turns <= 0:
        return  # 缺字段 = 无此行为（零默认值铁律）
    from saintess_engine.battle.state_effects import state_def
    cfg = state_def(key) or {}
    reduce_v = float((cfg.get("stat_scale") or {}).get("reduce") or 0)
    try:
        from saintess_engine.battle import now_of
        now = now_of(battle)
    except Exception:
        now = 0.0
    owner.setdefault("effects", {})[key] = {"stacks": 1, "expire": now + turns}
    if reduce_v > 0:
        lst = owner.setdefault("triggers", {}).setdefault("taken_calc", [])
        if not any(isinstance(t, dict)
                   and (t.get("judge") or {}).get("key") == key for t in lst):
            lst.append({"type": "passive_taken_reduce",
                        "judge": {"kind": "has_effect", "key": key},
                        "reduce": reduce_v, "label": cfg.get("name") or key})
    logs.append(f"🪨 进入{cfg.get('name') or key}：受伤 −{int(reduce_v * 100)}%（{turns} 刻）！")


@register_action("passive_low_hp_core")
def passive_low_hp_core(battle, caster, target, params, logs):
    """on_taken 低血量补磐核（不动如山 v153 L1016）：生命 <hp_lt×max_hp 且本场未触发
    → 获得 cores 枚磐核（clamp cap）+ 置一次性 flag（effects[used_key]，每场 1 次）。

    ⚠️ 缺口：设计触发时机为「生命 <30%」（任意掉血源），但引擎无低血量事件
    （player_low 无 fire 点位——见 saintess_engine/effect_triggers.py 头注）→ 本动作以
    on_taken（真实承伤后）为观测点：受击后跌破阈值即补；DOT/环境掉血须等下一次受击。
    参数：hp_lt/cores（技能 passive dict）/ res/used_key（声明表）；缺字段=无此行为。
    """
    ctx = getattr(battle, "_fire_ctx", None) or {}
    owner = params.get("_owner") or ctx.get("actor") or caster
    from saintess_engine.battle.actors import actor_alive
    if owner is None or not actor_alive(owner):
        return
    res = params.get("res") or ""
    used_key = params.get("used_key") or ""
    hp_lt = float(params.get("hp_lt") or 0)
    cores = float(params.get("cores") or 0)
    if not res or not used_key or hp_lt <= 0 or cores <= 0:
        return  # 缺字段 = 无此行为
    ef = owner.setdefault("effects", {})
    if isinstance(ef.get(used_key), dict):
        return  # 每场 1 次（一次性 flag 已置位）
    mhp = int(owner.get("max_hp", 1) or 1)
    if int(owner.get("hp", 0) or 0) >= int(mhp * hp_lt):
        return  # 未跌破阈值
    from saintess_engine.battle.effects import cap_of as _cap_fn, norm_stack as _ns
    cap = _cap_fn(owner, res)
    entry = ef.get(res)
    cur = float(entry.get("stacks", 0) or 0) if isinstance(entry, dict) else 0.0
    n = max(0.0, min(float(cap), cur + cores))
    if not isinstance(entry, dict):
        entry = ef[res] = {}
    entry["stacks"] = _ns(n)
    ef[used_key] = {"stacks": 1, "expire": None}
    logs.append(f"🪨 {params.get('label') or '不动如山'}：绝境补磐核 +{_ns(cores):g}"
                f"（{_ns(n)}/{cap}）！")


@register_action("passive_overflow_shield")
def passive_overflow_shield(battle, caster, target, params, logs):
    """taken_calc 溢出承伤转护盾（磐石之心 v153 L1002）：磐核 ≥stacks → 本次承伤
    ×shield_pct 转为护盾（turns 刻）。

    语义源 = 旧 passive_procs._h_dr_cond overflow_shield 段逐字
    （_add_shield('core_overflow', dmg × shield_pct, turns)——纯副作用，无乘区）。
    ⚠️ 设计原文「溢出承伤转为护盾」未给折算比例（v153 表零数值）——shield_pct/turns
    取技能 passive dict（旧引擎 D0 回填 0.80/3，非自创）。护盾结构对齐引擎 shield
    动词（shields[key] = {value, expire_at, halve}）。
    """
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    owner = params.get("_owner") or ctx.get("actor") or caster
    if owner is None:
        return
    judge = params.get("judge") or {}
    res = params.get("res") or judge.get("res") or ""
    pct = float(params.get("shield_pct") or 0)
    try:
        turns = int(params.get("turns") or 0)
    except Exception:
        turns = 0
    if not res or pct <= 0 or turns <= 0:
        return  # 缺字段 = 无此行为
    if not _res_ge_ok(owner, judge, params):
        return
    dmg = int(ctx.get("dmg") or 0)
    val = int(dmg * pct)
    if val <= 0:
        return
    try:
        from saintess_engine.battle import now_of
        now = now_of(battle)
    except Exception:
        now = 0.0
    sh = owner.setdefault("shields", {})
    key = f"{res}_overflow"
    cur = sh.get(key)
    if isinstance(cur, dict):
        cur["value"] = int(cur.get("value", 0) or 0) + val
        if cur.get("expire_at") is not None:
            cur["expire_at"] = max(float(cur.get("expire_at", 0) or 0), now + turns)
    else:
        sh[key] = {"value": val, "expire_at": now + turns, "halve": False}
    logs.append(f"🪨 {params.get('label') or '磐石之心'}：承伤转化 {val} 点护盾！")


@register_action("passive_shadow_buff")
def passive_shadow_buff(battle, caster, target, params, logs):
    """act_cast 影舞态强化 buff：态内 → 面板 spd ×(1+spd_add)（暗影步·极）。

    语义（v153）：暗影步·极「影舞态中速度 +25%、暴伤 +20%」——spd 走 buff 快照
    （stat spd op mul）；暴伤无面板通道（crit_dmg 非面板字段）→ 标缺口待引擎通道。
    """
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    actor = ctx.get("actor") or caster
    if actor is None:
        return
    ef = actor.setdefault("effects", {})
    buff_key = params.get("buff_key") or "_shadow_spd"
    if not isinstance(ef.get("shadow_dance"), dict):
        ef.pop(buff_key, None)  # 非影舞态 → 清残留
        return
    spd_add = float(params.get("spd_add") or 0)
    if spd_add <= 0:
        return
    ef[buff_key] = {"stacks": 1, "stat": "spd", "mult": 1.0 + spd_add,
                    "op": "mul", "expire": None}


@register_action("passive_res_gain_turn")
def passive_res_gain_turn(battle, caster, target, params, logs):
    """turn_start 资源自动回复：effects[res] += gain（奥术直觉每行动回充能）。

    语义（v153 法师奥术线）：奥术直觉「每刻自动回复 1 点奥术充能」——回合制近似
    turn_start 每次行动回 gain（冥想中 +2 需冥想态标缺口）。cap clamp 同 apply。
    """
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    actor = ctx.get("actor") or caster
    if actor is None:
        return
    res = params.get("res") or ""
    gain = float(params.get(params.get("gain_field") or "gain") or 0)
    if not res or gain <= 0:
        return  # 缺字段 = 无此行为
    ef = actor.setdefault("effects", {})
    entry = ef.get(res)
    if not isinstance(entry, dict):
        entry = ef[res] = {}
    from saintess_engine.battle.effects import cap_of as _cap_fn
    cap = _cap_fn(actor, res)
    if cap <= 0:
        return
    cur = float(entry.get("stacks", 0) or 0)
    n = min(float(cap), cur + gain)
    if n > cur:
        entry["stacks"] = n
        logs.append(f"🔮 {params.get('label') or '被动'}：奥术充能自动回复 {int(gain)}（{n:g}/{cap}）")


@register_action("passive_revive_guard")
def passive_revive_guard(battle, caster, target, params, logs):
    """on_death 守护姿态致命免疫（铁誓·不动）：姿态下首次致命伤 → 回满 + 清空战意。

    语义（v153 desc）：守护姿态下首次致命伤害免疫，清空全部战意——hp_pct 1.0
    （满血复活=致命免疫）；一次性 used_key；姿态保留（守护姿态是 buff 不随战意）。
    """
    ctx = getattr(battle, "_fire_ctx", None) or {}
    owner = ctx.get("actor") or caster
    if owner is None:
        return
    form = params.get("form") or "stance_guard"
    used_key = params.get("used_key") or "_stance_immortal_used"
    ef = owner.setdefault("effects", {})
    if (ef.get(used_key) or {}).get("stacks"):
        return  # 已用（一次性）
    if not isinstance(ef.get(form), dict):
        return  # 非守护姿态
    hp_pct = float(params.get("hp_pct") or 0)
    if hp_pct <= 0:
        return
    mhp = int(owner.get("max_hp", 1) or 1)
    owner["hp"] = max(1, int(mhp * hp_pct))
    zy = ef.get("zhan_yi")
    if isinstance(zy, dict):
        zy["stacks"] = 0
    ef[used_key] = {"stacks": 1, "expire": None}
    try:
        ka = getattr(battle, "killed_actors", None)
        if isinstance(ka, list) and owner in ka:
            ka.remove(owner)
    except Exception:
        pass
    logs.append(f"🛡️ {params.get('label') or '铁誓·不动'}：铁誓加身，致命伤被免疫！")


@register_action("passive_revive_berserk")
def passive_revive_berserk(battle, caster, target, params, logs):
    """on_death 狂暴中复活（血怒·不灭）：狂暴中首次死亡 → 清空战意复活回 hp_pct。

    语义（v153 desc 权威 + 旧挂点12 revive_cond 逐字）：狂暴中生命首次归零 →
    清空战意复活回 30%（hp_pct）。一次性（used_key 标记）；复活从 battle.killed_actors
    移除（_on_actor_dead 只记录，胜负/掉落判定后置——复活后照常行动）。
    """
    ctx = getattr(battle, "_fire_ctx", None) or {}
    owner = ctx.get("actor") or caster
    if owner is None:
        return
    form = params.get("form") or "fury"
    used_key = params.get("used_key") or "_berserk_revive_used"
    ef = owner.setdefault("effects", {})
    if (ef.get(used_key) or {}).get("stacks"):
        return  # 已用（一次性）
    if not isinstance(ef.get(form), dict):
        return  # 非狂暴中（条件不满足 = 不复活）
    hp_pct = float(params.get("hp_pct") or 0)
    if hp_pct <= 0:
        return  # 缺字段 = 无此行为
    mhp = int(owner.get("max_hp", 1) or 1)
    owner["hp"] = max(1, int(mhp * hp_pct))
    # 清空战意 + 移除狂暴 + 标记已用（v153：复活清空战意）
    zy = ef.get("zhan_yi")
    if isinstance(zy, dict):
        zy["stacks"] = 0
    ef.pop(form, None)
    ef[used_key] = {"stacks": 1, "expire": None}
    # 从死亡记录移除（胜负/击杀判定后置——复活后不被算作已死）
    try:
        ka = getattr(battle, "killed_actors", None)
        if isinstance(ka, list) and owner in ka:
            ka.remove(owner)
    except Exception:
        pass
    logs.append(f"🔥 {params.get('label') or '血怒·不灭'}：怒意未熄，战士复活！回复 {int(mhp * hp_pct)} 生命")


@register_action("passive_mark_enhance")
def passive_mark_enhance(battle, caster, target, params, logs):
    """act_cast 元素印记增强：亲和（引爆后下次挂印+1）/ 同调（连续同系二次挂印+1）。

    语义（desc 权威）：
    - affinity：施放引爆技（mech 前缀 element_burst）→ 置待增强标记；下次挂印技
      （mech=fire/ice/thunder_mark）→ target 对应印记 +1（效果段基础 apply 再 +1 = 总 2）
    - sync：挂印技记录施法系，连续两次同系 → 第二次挂印 +1；非元素施法断连清记录
    多印记技（element_multi_mark 双系）语义复杂不增强（保底基础行为）。
    """
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    actor = ctx.get("actor") or caster
    if actor is None:
        return
    info = ctx.get("info") or {}
    mech = info.get("mech") or ""
    mode = params.get("mode") or ""
    _MARKS = {"fire_mark": "fire", "ice_mark": "ice", "thunder_mark": "thunder"}
    is_mark = mech in _MARKS
    is_burst = str(mech).startswith("element_burst")
    if mode == "affinity":
        if is_burst:
            actor.setdefault("effects", {})["_elem_affinity_ready"] = {"stacks": 1}
            return
        if not is_mark:
            return
        ef = actor.get("effects") or {}
        if "_elem_affinity_ready" not in ef:
            return  # 无引爆后待增强标记
        ef.pop("_elem_affinity_ready", None)
        tgt = _act_target(battle, ctx, actor, target)
        if tgt is None:
            return
        _add_mark(tgt, mech, 1)
        logs.append(f"✨ {params.get('label') or '被动'}：元素亲和，挂印 +1 层！")
        return
    if mode == "sync":
        if is_mark:
            ef = actor.setdefault("effects", {})
            last = (ef.get("_elem_last_mark") or {}).get("kind")
            ef["_elem_last_mark"] = {"kind": mech}
            tgt = _act_target(battle, ctx, actor, target)
            if last == mech and tgt is not None:
                _add_mark(tgt, mech, 1)
                logs.append(f"✨ {params.get('label') or '被动'}：元素同调，挂印 +1 层！")
        elif not is_burst:
            # 非元素施法（普攻/其他系）打断连续记录
            (actor.get("effects") or {}).pop("_elem_last_mark", None)


@register_action("passive_element_core_crit")
def passive_element_core_crit(battle, caster, target, params, logs):
    """act_cast 元素之核：结算技时目标单系印记 ≥3 → 本次结算暴击 +20%。

    语义（desc 权威）：单系印记满 3 时该系结算暴击 +20%——引擎暴击整次技能单 roll，
    无法分系 → 目标有任意单系 ≥3 即整次结算暴击 +20%（近似 desc，buff 快照条
    crit 加算，覆盖整个结算技行动）。
    """
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    actor = ctx.get("actor") or caster
    if actor is None:
        return
    info = ctx.get("info") or {}
    mech = info.get("mech") or ""
    if not str(mech).startswith("element_burst"):
        return  # 仅结算技（元素迸发/裁决/万象风暴）
    tgt = _act_target(battle, ctx, actor, target)
    if tgt is None:
        return
    add = float(params.get("add") or 0)
    if add <= 0:
        return  # 缺字段 = 无此行为
    _ef = tgt.get("effects") or {}
    hit = False
    for _mk in ("fire_mark", "ice_mark", "thunder_mark"):
        _en = _ef.get(_mk)
        if int(_en.get("stacks", 0) or 0) >= 3 if isinstance(_en, dict) else False:
            hit = True
            break
    if not hit:
        return
    buff_key = "passive_crit_element_core"
    actor.setdefault("effects", {})[buff_key] = {"stacks": 1, "stat": "crit",
                                                 "mult": add, "op": "add",
                                                 "expire": None}
    logs.append(f"✨ {params.get('label') or '被动'}：元素核心，结算暴击 +{int(add * 100)}%！")


@register_action("passive_bar_decay_half")
def passive_bar_decay_half(battle, caster, target, params, logs):
    """time_advance：破绽条衰减减半（破绽感知）。

    语义源 = 技能 desc「破绽衰减减半（−1.7/s → −0.85/s）」+ v153 §六（每刻 −1.7）。
    实现：内容层把声明者**敌对侧**宿主身上该条结算到当刻（bar_settle 全量衰减）后
    回补本次衰减量的**一半**（净效果 = 半衰）。float 保真——修掉旧引擎
    `int(decay/2)` 截断空转（shaken 1.7 → int(0.85)=0，物理无效果）。
    条名由声明给（judge.bar）/ 宿主范围 = side 关系；宿主自带的 bar_time_settle
    同事件后行时条 `_at` 已归零（幂等），故与订阅顺序无关。
    """
    ctx = getattr(battle, "_fire_ctx", None) or {}
    judge = params.get("judge") or {}
    bar = judge.get("bar") or params.get("bar") or ""
    owner = params.get("_owner") or caster
    if not isinstance(owner, dict) or not bar:
        return
    try:
        from saintess_engine.battle.actors import hostile_sides
        from saintess_engine.gauge import bar_def, bar_effect_key, bar_settle
    except Exception:
        return
    bd = bar_def(bar) or {}
    if not bd:
        return  # 无条配置 = 无此行为（零默认值铁律）
    now = float(ctx.get("now", getattr(battle, "_now", 0.0)) or 0.0)
    cap = float(bd.get("max", 0) or 0)
    # 同刻去重（战斗级瞬态）：两名持有者不叠加成 ×0.75 衰（属性随战斗对象，不落盘）
    _tick = getattr(battle, "_bar_decay_half_tick", None)
    if not isinstance(_tick, dict):
        _tick = battle._bar_decay_half_tick = {}
    for _sn in hostile_sides(battle, owner.get("side") or ""):
        for host in ((getattr(battle, "sides", None) or {}).get(_sn) or []):
            bs = (host.get("effects") or {}).get(bar_effect_key(bar))
            if not isinstance(bs, dict):
                continue  # 没挂过条 = 不触发（零噪音）
            before = float(bs.get("val", 0.0) or 0.0)
            if before <= 0 or _tick.get(id(host)) == now:
                continue
            bar_settle(host, bar, now)
            refund = (before - float(bs.get("val", 0.0) or 0.0)) * 0.5
            if refund <= 0:
                continue
            _tick[id(host)] = now
            nv = float(bs.get("val", 0.0) or 0.0) + refund
            bs["val"] = min(cap, nv) if cap > 0 else nv
            logs.append(f"🎯 {params.get('label') or '破绽感知'}：破绽衰减减半"
                        f"（{before:g} → {bs['val']:g}）")


@register_action("passive_lian_duan_soft")
def passive_lian_duan_soft(battle, caster, target, params, logs):
    """暗影之心（lian_duan_soft）：断连时只损失 lose 段连击（而非减半）。

    语义源 = 技能 desc「断连时只损失 1 段连击（而非减半）」+ passive dict（lose=1）
    + v153 §五（连段 0-5；「1.5 刻内未命中 → 连段减半」= 断连窗权威）。
    saintess_engine 无基础断连载体（旧 battle.py `_combo_break` 随 N10 删除、未迁），
    故内容层自管（引擎零改动，同 recon 路线）：
      skill_hit / attack_hit  记「最后命中时刻」（effects._lian_duan_last_hit）
      time_advance            now − 最后命中 ≥ gap 且连段 > 0 → 连段 −lose（并重开窗）
    参数 res / gap / lose 全由声明给；缺 gap / 缺 lose / 无命中记录 / 连段 0 → 不动作
    （零默认值铁律：缺字段 = 无此行为）。
    """
    ctx = getattr(battle, "_fire_ctx", None) or {}
    owner = params.get("_owner") or caster
    if not isinstance(owner, dict):
        return
    ev = ctx.get("_event") or ""
    ef = owner.setdefault("effects", {})
    rec_key = "_lian_duan_last_hit"
    if ev in ("skill_hit", "attack_hit"):
        ef[rec_key] = {"t": float(getattr(battle, "_now", 0.0) or 0.0)}
        return
    if ev != "time_advance":
        return
    res = params.get("res") or ""
    try:
        gap = float(params.get("gap") or 0)
        lose = float(params.get("lose") or 0)
    except Exception:
        return
    if not res or gap <= 0 or lose <= 0:
        return  # 缺字段 = 无此行为
    rec = ef.get(rec_key)
    if not isinstance(rec, dict) or rec.get("t") is None:
        return  # 从未命中 → 无断连判据（不臆造起点）
    now = float(ctx.get("now", getattr(battle, "_now", 0.0)) or 0.0)
    if now - float(rec.get("t")) < gap:
        return  # 窗内仍有命中 → 连段未断
    entry = ef.get(res)
    cur = float(entry.get("stacks", 0) or 0) if isinstance(entry, dict) else 0.0
    if cur <= 0:
        return
    from saintess_engine.battle.effects import norm_stack
    nv = norm_stack(max(0.0, cur - lose))
    entry["stacks"] = nv
    ef[rec_key] = {"t": now}   # 断连已结算 → 重开窗（防每刻连续掉段）
    logs.append(f"🌑 {params.get('label') or '暗影之心'}：断连只损 {int(lose)} 段"
                f"（{int(cur)} → {int(nv)}）")


@register_action("passive_poison_spread")
def passive_poison_spread(battle, caster, target, params, logs):
    """毒刃·共鸣（poison_spread）：毒爆击杀目标时，毒层扩散至相邻敌人。

    语义源 = 技能 desc「毒爆击杀目标时，毒层扩散至相邻敌人」+ v153 §五 B 线。
    同一动作按事件名分派（on_kill ctx 无技能信息 → 内容层自管本次施放记录）：
      act_cast  记本次施放技能 mech（effects._poison_spread_mech）
      on_kill   声明者击杀 + 记录 mech 前缀匹配（desc「毒爆击杀」）+ 死者带毒层
                → 死者毒层按其**当前层数**扩散给相邻（同 side 列表前后各一）存活敌人
      act_done  清记录（作用域 = 单次行动）
    「相邻」= battle.sides_of(死者 side) 列表内前后邻居（内容层可读）；扩散层数 =
    死者现毒层数（desc 未给系数 → 不臆造常量，用现网单源）。落地走引擎 apply 动词
    （cap 收敛 / threshold 广播与技能施毒同口径）。
    """
    ctx = getattr(battle, "_fire_ctx", None) or {}
    owner = params.get("_owner") or caster
    if not isinstance(owner, dict):
        return
    ev = ctx.get("_event") or ""
    judge = params.get("judge") or {}
    key = judge.get("key") or params.get("key") or ""
    ef = owner.setdefault("effects", {})
    rec_key = "_poison_spread_mech"
    if ev == "act_cast":
        ef[rec_key] = {"mech": (ctx.get("info") or {}).get("mech") or ""}
        return
    if ev == "act_done":
        ef.pop(rec_key, None)
        return
    if ev != "on_kill" or not key:
        return
    prefix = str(params.get("mech_prefix") or "")
    _rec = ef.get(rec_key)
    mech = str(_rec.get("mech") or "") if isinstance(_rec, dict) else ""
    if prefix and not mech.startswith(prefix):
        return  # 非毒爆击杀（desc 限定）→ 不扩散
    dead = ctx.get("target")
    if not isinstance(dead, dict):
        return
    n = int(((dead.get("effects") or {}).get(key) or {}).get("stacks", 0) or 0)
    if n <= 0:
        return  # 死者无毒层 = 无此行为
    from saintess_engine.battle.actors import actor_alive
    lst = battle.sides_of(dead.get("side") or "")
    idx = next((i for i, a in enumerate(lst) if a is dead), None)
    if idx is None:
        return
    from saintess_engine.battle.effects import act_apply
    spread = 0
    for i in (idx - 1, idx + 1):
        if not 0 <= i < len(lst) or not actor_alive(lst[i]):
            continue
        act_apply(battle, owner, lst[i],
                  {"key": key, "op": "add", "amount": n, "on": "target"}, logs)
        spread += 1
    if spread > 0:
        logs.append(f"☠️ {params.get('label') or '毒刃·共鸣'}：毒层扩散至 "
                    f"{spread} 名相邻敌人（{n} 层）！")

__all__ = [
    "mech_cash_finisher_crit",
    "mech_cash_dmg_mult",
    "mech_cash_clear",
    "mech_cash_per_system_mult",
    "class_res_channel_gain",
    "class_faith_load_tier",
    "class_faith_overload",
    "class_melody_act",
    "passive_melody_duet",
    "class_melody_dirge_tick",
    "passive_ctrl_extend",
    "passive_dmg_mult",
    "passive_bar_extend",
    "passive_kill_gain",
    "passive_counter",
    "passive_cond_crit",
    "passive_taken_reduce",
    "passive_cc_clear",
    "passive_cc_break",
    "passive_lifesteal_buff",
    "passive_heal_overflow_shield",
    "mech_cash_fury_enter",
    "passive_dot_mult",
    "passive_poison_weaken",
    "class_shadow_dance_enter",
    "class_stance_guard_enter",
    "class_stance_counter",
    "class_guard_stance_enter",
    "passive_low_hp_core",
    "passive_overflow_shield",
    "passive_shadow_buff",
    "passive_res_gain_turn",
    "passive_revive_guard",
    "passive_revive_berserk",
    "passive_mark_enhance",
    "passive_element_core_crit",
    "passive_bar_decay_half",
    "passive_lian_duan_soft",
    "passive_poison_spread",
]


# ============================================================
# 装配侧（P4-D2c 追加：真源 `class_mech_proc.py:1868-2260` + `:2262-2443`，逐字搬运）
# ============================================================
# 本块**追加在 `__all__` 之后** —— 既有逐字对拍（`d2_misc_verify.py` A4 的比对区间 =
# 「`from __future__` → `__all__` 前」）不受影响。真源 = 游戏仓
# `game/services/class_mech_proc.py`：
#   `_mech_cash_rules`(:1871-1877) / `_effect_rules`(:1880-1886) /
#   `_CHANNEL_EVENTS`(:1897-1904) / `apply_class_channels`(:1907-1956) /
#   `_learned_mech_skills`(:1959-1974) / `_passive_proc_rules`(:2026-2032) /
#   `apply_class_passives`(:2035-2161) / `_merge_agg_entry`(:2225-2259) /
#   `apply_class_mech`(:2262-2443)。
# 函数体 / 数值 / 日志文案 / 注释**一字未改**；改动**仅四类**：
#   ① import 路径（真源 `..data.battle_rules` → 包内单源，全部**惰性 import 留在函数体内**
#      → 与 `content/apply.py` 不形成导入环）：
#        · `MECH_CASH` / `BAR_INJECT_FIELDS` → `from .class_data import …`（包内参数表）
#        · 技能表 `..content_rules.skills.skill_info` → `from ..apply import _SKILL_LOOKUP as
#          _PKG_SKILLS` + `skill_info = _PKG_SKILLS.skill_info`（同 `bar_procs.py` 装配段写法）
#        · `PASSIVE_PROC` → 本文件 `_passive_proc_rules()` **直读包内**
#          `content/rules/passive_proc.json`（D2 收口：不再转发 `..apply`，那份已随切片退役）
#          `content/rules/passive_proc.json`，42 条）
#   ② 去 `install()` 调用（真源 :2049 / :2273）：包版动作 **import 即注册**（`content/apply.py`
#      顶部的 `from .mech import class_mech` 已完成注册），无需再 install；
#      `apply_class_mech` 里 `install()` 的位置换成 `LAST_ERRORS.clear()`（「最近一次装配的
#      失败步」语义，同 `content/apply.py:284`）。
#   ③ bar / cond 装配入口改包内模块，**缺件不静默**：真源
#      `from .battle_bar_procs import apply_bar_procs` → `from .bar_procs import apply_bar_procs`
#      （同 `.cond_procs`）；包内**没有**该函数时 try/except 记 `LAST_ERRORS`（照实记录，
#      不静默、不伪造）；其余装配异常仍按真源「容错铁律」静默续走。
#   ④ `_learned_proc` / `_learned_proc_param` / `_res_ge_ok` / `_has_effect_ok` / `_when_ok`
#      已在本文件动作段逐字搬过（:108-215），本块不重复搬运。
# ============================================================

# 最近一次装配的失败步（排障用；不写 actor、不进存档）——`content/apply.py:76 LAST_ERRORS` 同款
LAST_ERRORS: list = []
_MAX_ERRORS = 16


def _note_error(name: str, exc: BaseException) -> None:
    """包侧新增（真源无，见本块头注 ③）：装配缺件记入 LAST_ERRORS，不静默。"""
    if len(LAST_ERRORS) < _MAX_ERRORS:
        LAST_ERRORS.append((name, repr(exc)))


def _mech_cash_rules() -> dict:
    """当前挂载的兑现声明表（缺省空——装配层不崩）。"""
    try:
        from .class_data import MECH_CASH
        return MECH_CASH or {}
    except Exception:
        return {}


def _effect_rules() -> dict:
    """当前 EFFECT_RULES（缺省空）。"""
    try:
        from saintess_engine.config import get_effect_rules
        return get_effect_rules() or {}
    except Exception:
        return {}


# ============================================================
# v181.M-R2d：职业资源攒取渠道（事件型）——装配与动作
# ============================================================
# 渠道时机名 → (saintess_engine 事件, 附加过滤参数)。语义源 = EFFECT_RULES 资源条目 channels
# 声明 + docs/REFACTOR_v181_CLASS_MECH_ASSEMBLY.md『M-R2d 渠道装配设计』§2.2：
#   heal_cast 治疗「施放」与「命中」同刻 → act_cast + kind=治疗（同 R4 holy_echo 折中；
#   每技能施放 fire 1 次，无多目标重复）；普攻（basic 经 do_skill）也 fire act_cast 但
#   kind=物理 → kind 过滤天然排除，不会误攒。
_CHANNEL_EVENTS = {
    "attack_hit": ("attack_hit", {}),            # 普攻命中
    "skill_hit": ("skill_hit", {}),              # 技能命中
    "heal_cast": ("act_cast", {"kind": "治疗"}),  # 治疗施放
    "taken": ("on_taken", {}),                   # 受击（真实承伤后，subject=受击者）
    "cast": ("act_cast", {"not_basic": True}),   # （预留）技能施放（未装配用）
    "tick": ("time_advance", {}),                 # 每刻时钟推进（schedule 广播，ctx 带 dt/now）
}


def apply_class_channels(actor: dict, rules: dict) -> None:
    """EFFECT_RULES 资源条目 channels 声明 → actor.triggers 事件钩子（并入 apply_class_mech）。

    对每个声明了 channels 的资源条目（归属职业 start_classes 命中才装——防白拿）：
    时机名 → saintess_engine 事件 → 挂 class_res_channel_gain 生产动作（gain 值由声明给，
    cap clamp 动作侧查 EFFECT_RULES）。未映射时机名静默跳过（版本漂移保护，同
    affix 翻译器缺口词条行为）。装配器零资源 key 硬编码——渠道全由声明驱动。

    渠道值形态：`时机: 2`（无条件简写）或 `时机: {"gain": 1, "when": [judge...]}`
    （条件攒取——when 谓词在动作入口求值，见 _when_ok）。
    """
    if not actor:
        return
    cn = actor.get("class_name") or ""
    trig = actor.setdefault("triggers", {})
    for rk, rc in (rules or {}).items():
        if not isinstance(rc, dict):
            continue
        ch = rc.get("channels")
        if not isinstance(ch, dict) or not ch:
            continue  # 无渠道声明 = 无此行为（零默认值铁律）
        sc = rc.get("start_classes") or []
        if sc and cn not in sc:
            continue
        name = rc.get("name") or rk
        for chan, cv in ch.items():
            # 渠道值两形态：简写 int/float = 无条件的 gain；dict = {gain, when[...]}（条件攒取）。
            # 条件按渠道声明而非资源条目——同一资源不同来源条件不同（磐核：受击/每刻看姿态，
            # 守线技能命中无条件）。
            if isinstance(cv, dict):
                gain = cv.get("gain")
                when = cv.get("when")
                per_dt = cv.get("per_dt")
            else:
                gain, when, per_dt = cv, None, None
            if not chan or not isinstance(gain, (int, float)) or float(gain) <= 0:
                continue
            ev, extra = _CHANNEL_EVENTS.get(chan, (None, None))
            if ev is None:
                continue
            d = {"type": "class_res_channel_gain", "res": rk, "gain": float(gain),
                 "label": name, "icon": "✦"}
            d.update(extra)
            # 条件透传：动作入口按谓词求值（_when_ok）。无声明不写键（零默认值）。
            if when:
                d["when"] = when
            # per_dt 透传（tick 渠道：gain 按事件 dt 缩放——见 class_res_channel_gain）
            if per_dt:
                d["per_dt"] = True
            trig.setdefault(ev, []).append(d)


def _learned_mech_skills(actor: dict) -> list:
    """actor 已学技能中含 mech 的技能 [(中文名, info)]（查技能定义表）。"""
    cn = actor.get("class_name") or ""
    names = actor.get("learned_skills") or []
    if not cn or not names:
        return []
    from ..apply import _SKILL_LOOKUP as _PKG_SKILLS
    skill_info = _PKG_SKILLS.skill_info
    out = []
    for s in names:
        try:
            info = skill_info(cn, s)
        except Exception:
            info = None
        if info and info.get("mech"):
            out.append((s, info))
    return out


def _passive_proc_rules() -> dict:
    """PASSIVE_PROC 声明表（包内 `content/rules/passive_proc.json`，42 条；缺省空——装配器不崩）。

    ⚠️ **直读包内 JSON**（不经 `..apply`）：D2 收口后 `apply.py` 只保留「入口 + 顺序契约」，
    装配实现全在各族模块里。早前版本转发给 `..apply._passive_proc_rules`（D1 期产物）——
    那份被删后这里会**静默返回 {}**，症状 = 被动一条都不装配（实测：`taken_calc` 里只剩
    EFFECT_RULES 派生的每核减伤，`core_full`/`core_reduce` 全丢，而 `LAST_ERRORS` 为空）。
    """
    try:
        import json as _json
        import os as _os
        _p = _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),  # .../content
            "rules", "passive_proc.json")
        with open(_p, encoding="utf-8") as f:
            return _json.load(f) or {}
    except Exception:                                        # noqa: BLE001
        return {}


def apply_class_passives(actor: dict) -> None:
    """被动 proc 装配（v181.M-passive P1 插件样板）：扫已学 kind=被动 + passive.proc
    → 查 PASSIVE_PROC 声明表 → 参数化挂 actor.triggers[event]。学什么挂什么防白拿；
    表未声明 proc → 跳过（记缺口，不硬做）。
    domain 域（不进 triggers 的静态修正）：cap → 写 actor.bonus.cap[key] += add
    （资源上限被动：毒/猎印/魂标 cap——引擎 _cap_of 动态收敛已支持 bonus.cap）；
    cost → 写 actor.bonus.cost（消耗折扣：mp_pct/mp_flat/res——引擎 _skill_pay_of 折算）。
    """
    if not actor:
        return
    cn = actor.get("class_name") or ""
    names = actor.get("learned_skills") or []
    if not cn or not names:
        return
    rules = _passive_proc_rules()
    if not rules:
        return
    from ..apply import _SKILL_LOOKUP as _PKG_SKILLS
    skill_info = _PKG_SKILLS.skill_info
    trig = actor.setdefault("triggers", {})
    _pending: dict = {}  # (event, agg) -> [(proc, entry)] 聚合族暂存（循环后归并单条）
    for s in names:
        try:
            info = skill_info(cn, s)
        except Exception:
            info = None
        if not info or info.get("kind") != "被动":
            continue
        p = info.get("passive") or {}
        proc = p.get("proc") or ""
        cfg = rules.get(proc)
        if not isinstance(cfg, dict):
            continue  # 表未声明 → 记缺口跳过（不硬做）
        domain = cfg.get("domain") or ""
        if domain == "cap":
            # 资源上限被动：bonus.cap[key] += add（cap 修正容器，_cap_of 动态读）
            key = cfg.get("cap_key") or proc
            try:
                add = int(p.get("add", cfg.get("add", 0)) or 0)
            except Exception:
                add = 0
            if add > 0:
                bonus = actor.setdefault("bonus", {})
                bonus.setdefault("cap", {})[key] = \
                    int((bonus.get("cap") or {}).get(key, 0) or 0) + add
            # 双通道声明（cap + event，如 soul_mark_cap/poison_cap_up 乘区段）→ 不 continue，fall through
        if domain == "cost":
            # 消耗折扣被动：bonus.cost（引擎 _skill_pay_of 折算）。mp_mult（如
            # 奥术恒常 mp_mult 0.5 = 奥术技能耗蓝-50%）→ 有 cfg.when 判据则放 when
            # 子条目（限定技能），无 when 才放顶层（无条件全技能）。
            pct = float(p.get("mp_mult", 0) or 0)
            when = cfg.get("when")
            bonus = actor.setdefault("bonus", {})
            _c = bonus.setdefault("cost", {})
            if when:
                _w = dict(when[0]) if isinstance(when, list) and when else {}
                _w["mp_pct"] = float(_w.get("mp_pct", 0) or 0) + pct
                _c.setdefault("when", []).append(_w)
            elif pct > 0:
                _c["mp_pct"] = float(_c.get("mp_pct", 0) or 0) + pct
            # cost 域声明无 event → 下方 d.type 空自然 continue
        d = {"type": cfg.get("action") or "", "judge": cfg.get("judge") or {}}
        # cfg 声明表非结构字段并入（buff_key 等动作参数——domain 消费过的键除外）
        for k, v in cfg.items():
            if k in ("event", "action", "judge", "agg", "domain",
                     "cap_key", "when", "add", "also"):
                continue
            d[k] = v
        # 被动参数并入（mult 归一 mult/dmg_add/per_layer；label 用技能名）
        for k, v in p.items():
            if k in ("proc",):
                continue
            d[k] = v
        d.setdefault("label", info.get("name") or proc)
        # bar_field：被动自身携带的推条字段（如反震 shaken_gain: 3）→ 装配时解析成
        # {key, gain}（字段 → bar key 映射 = BAR_INJECT_FIELDS；数值单源 = 技能数据字段，
        # 不在被动 dict 重填）。缺字段/非正数 = 只做动作其余段（零默认值铁律）。
        _bf = cfg.get("bar_field")
        if _bf and not d.get("gain"):
            try:
                from .class_data import BAR_INJECT_FIELDS
                _spec = (BAR_INJECT_FIELDS or {}).get(_bf) or {}
                _bk = _spec.get("key")
                _bg = int(info.get(_bf) or 0)
                if _bk and _bg > 0:
                    d["key"] = _bk
                    d["gain"] = _bg
            except Exception:
                pass
        if not d.get("type"):
            continue
        ev = cfg.get("event") or ""
        if not ev:
            continue
        # 聚合族（agg：counter 等——多条目合成一条，旧挂点聚合语义）暂存，循环后归并
        if cfg.get("agg"):
            _pending.setdefault((ev, cfg.get("agg")), []).append((proc, d))
        else:
            trig.setdefault(ev, []).append(d)
        # also 段：同被动第二条事件钩子（如坚城之姿 taken_calc 减伤 + turn_start 免晕）——
        # 复用 d 的参数，覆盖 action/judge/额外字段
        for _also in (cfg.get("also") or []):
            if not isinstance(_also, dict):
                continue
            _d2 = dict(d)
            _d2["type"] = _also.get("action") or d.get("type")
            if _also.get("judge"):
                _d2["judge"] = _also["judge"]
            for _k in ("ctrl", "ctrl_any", "res", "left_key", "left_init",
                       "cost_field", "buff_key"):
                if _also.get(_k) is not None:
                    _d2[_k] = _also[_k]
            _ev2 = _also.get("event") or ev
            if cfg.get("agg"):
                _pending.setdefault((_ev2, cfg.get("agg")), []).append((proc, _d2))
            else:
                trig.setdefault(_ev2, []).append(_d2)
        # 计数初始化（tenacity 每场 3 次：effects[left_key] = left_init——装配=开战时机）
        _le = cfg.get("left_key")
        if _le and cfg.get("left_init") is not None:
            actor.setdefault("effects", {})[_le] = {"stacks": int(cfg.get("left_init")),
                                                    "expire": None}
    # ---- 族级聚合（旧 passive_procs 聚合族语义逐字：多条目 → 单条终值）----
    for (ev, agg), entries in _pending.items():
        merged = _merge_agg_entry(agg, entries)
        if merged is not None:
            trig.setdefault(ev, []).append(merged)


def _merge_agg_entry(agg: str, entries: list) -> dict:
    """聚合族归并：多条装配条目 → 单条终值 dict（返回 None = 无有效终值）。

    语义源 = 旧 passive_procs._h_* 聚合族 handler 逐字（挂点13 counter）：
    - counter_chance：chance 取 max、mult 取 min（以守为攻 35% ×80% 普攻档）
    - counter_up：chance += chance_add、mult ×= (1+dmg_add)（反击之王只首条加成）
    终值 atk_pct = mult（反击伤害 = 普攻 × mult，对齐 we_affix_counter 的 atk×atk_pct 直伤）。
    """
    if not entries:
        return None
    if agg == "counter":
        chance = 0.0
        mult = 1.0
        labels = []
        for proc, d in entries:
            labels.append(d.get("label") or proc)
            if proc == "counter_chance":
                _ch = float(d.get("chance", 0.0) or 0.0)
                _mu = float(d.get("mult", 0.0) or 0.0)
                if _ch <= 0 or _mu <= 0:
                    continue  # 缺字段 = 无此行为（零默认值铁律）
                chance = max(chance, _ch)
                mult = min(mult, _mu)
            elif proc == "counter_up":
                _ca = float(d.get("chance_add", 0.0) or 0.0)
                _da = float(d.get("dmg_add", 0.0) or 0.0)
                if _ca <= 0 or _da <= 0:
                    continue  # 缺字段 = 无此行为
                chance += _ca
                mult *= (1.0 + _da)
        if chance <= 0 or mult <= 0:
            return None
        return {"type": "passive_counter", "chance": min(chance, 0.9),
                "atk_pct": mult, "label": "+".join(dict.fromkeys(labels))}
    return None


def apply_class_mech(actor: dict) -> None:
    """技能 mech 兑现装配（幂等；命令层开战仪式与 equip_proc 并列调用）。

    对 actor 技能集里每个"声明过兑现"的 mech，按声明参数化挂事件钩子：
    - dmg_calc（伤害前乘区修正）
    - skill_hit（命中后清层）
    mode=dmg_mult_clear_target 的条目装配时向效果 dict 写 owner=target（读/清
    fire ctx 的 target effects）；dmg_mult_clear 缺省 owner=caster（finisher 兼容）。
    """
    if not actor:
        return
    LAST_ERRORS.clear()
    try:
        rules = _mech_cash_rules()
        if not rules:
            return
        trig = actor.setdefault("triggers", {})
        # v181.M-R2：start_full 资源开局满额（读 EFFECT_RULES 条目 start_full 声明，
        # 源 core_resources.cls_you_xia v176（原表随 v181.M-R2c 退役，现单源 EFFECT_RULES energy.start_full）
        # 游侠精力开局满——装配层初始化 effects 条目）
        try:
            _full_rules = _effect_rules()
            _cn = actor.get("class_name") or ""
            for _rk, _rc in (_full_rules or {}).items():
                if not (isinstance(_rc, dict) and _rc.get("start_full")):
                    continue
                # 开局满额归属职业（start_classes 声明，空 = 不装配）——防非游侠白拿 energy
                _sc = _rc.get("start_classes") or []
                if _sc and _cn not in _sc:
                    continue
                _cap = int(_rc.get("cap", 0) or 0)
                if _cap > 0:
                    actor.setdefault("effects", {})[_rk] = {
                        "stacks": _cap, "expire": 999999.0}
        except Exception:
            pass
        # v181.M-R2d：职业资源攒取渠道（事件型）——EFFECT_RULES 条目 channels 声明 → 事件钩子。
        # 核实结论（docs『M-R2d 渠道装配设计』§1）：现网仅牧师 faith 活 key 缺攒端（卸负消费 +
        # 治疗/受击渠道），rage/cp/chi/element 技能域死 key 不接（EFFECT_RULES 条目注释标注）。
        try:
            apply_class_channels(actor, _effect_rules())
        except Exception:
            pass  # 渠道装配异常不阻断开战（容错铁律）
        # v181 磐核：职业资源固有「每核减伤」（EFFECT_RULES[res].stat_scale.reduce 声明）
        # → taken_calc 承伤乘区（passive_taken_reduce per_core 段）。原因：saintess_engine 伤害
        # 路径只消费 taken_calc 乘区——stat_scale.reduce 仅由 stats 写入 st["reduce"]
        # （无消费方，instance 仅展示）。数值单源 = 声明；归属过滤 = start_classes
        # （**必须**声明 start_classes 才装配——无归属声明的通用效果键如 shield/melody_def
        # 不接，防误加），零职业名硬编码。
        try:
            _cn_r = actor.get("class_name") or ""
            for _rk, _rc in (_effect_rules() or {}).items():
                if not isinstance(_rc, dict):
                    continue
                _per = float((_rc.get("stat_scale") or {}).get("reduce") or 0)
                _sc_r = _rc.get("start_classes") or []
                if _per <= 0 or not _sc_r or _cn_r not in _sc_r:
                    continue
                trig.setdefault("taken_calc", []).append(
                    {"type": "passive_taken_reduce",
                     "judge": {"kind": "per_core", "res": _rk},
                     "per_core": _per, "label": _rc.get("name") or _rk})
        except Exception:
            pass  # 资源减伤装配异常不阻断开战（容错铁律）
        # v181.M-R2e B2：牧师信仰负载制装配——faith 条目声明 load_tiers（有档位表才挂，
        # 零默认值铁律）+ start_classes 归属过滤（非牧师不挂，防白拿 heal_calc 乘区）：
        #   heal_calc  → 施法时按自身 faith 层查档位 heal_mult 乘入（档位乘区）
        #   threshold  → 叠层到满 cap 的当次触发过载（清零 + 全队回复）
        try:
            _fc = (_effect_rules() or {}).get("faith") or {}
            if isinstance(_fc.get("load_tiers"), list) and _fc.get("load_tiers"):
                _fsc = _fc.get("start_classes") or []
                _cn2 = actor.get("class_name") or ""
                if not _fsc or _cn2 in _fsc:
                    trig.setdefault("heal_calc", []).append(
                        {"type": "class_faith_load_tier", "res": "faith"})
                    trig.setdefault("threshold", []).append(
                        {"type": "class_faith_overload", "res": "faith"})
        except Exception:
            pass  # 负载制装配异常不阻断开战（容错铁律）
        # v181.M-melody：诗人旋律装配——class=cls_shi_ren 且学了 melody/melody_chant
        # 系技能才挂 act_cast 触发器（学什么挂什么，零噪音；非诗人不挂）。
        try:
            _has_melody = any(
                (info.get("mech") in ("melody", "melody_chant"))
                for _s, info in _learned_mech_skills(actor))
            if _has_melody:
                _lst_mel = trig.setdefault("act_cast", [])
                if not any(isinstance(e, dict) and e.get("type") == "class_melody_act"
                           for e in _lst_mel):
                    # ⚠️ 顺序契约：基础叠层排 act_cast 首位——被动族吟唱后置段
                    # （二重唱 passive_melody_duet 读叠层后的强度）依赖先叠完基础层
                    _lst_mel.insert(0, {"type": "class_melody_act"})
        except Exception:
            pass  # melody 装配异常不阻断开战（容错铁律）
        # v181.M-passive P1：被动 proc 装配（扫已学 kind=被动 → PASSIVE_PROC 表挂 triggers）
        try:
            apply_class_passives(actor)
        except Exception:
            pass  # 被动装配异常不阻断开战（容错铁律）
        # v181 破绽接线：挂敌身条注入装配（BAR_INJECT_FIELDS 声明表 → skill_hit 触发器）
        try:
            from .bar_procs import apply_bar_procs
            apply_bar_procs(actor)
        except ImportError as _e:
            _note_error("bar_procs", _e)  # 包内缺件 → 不静默（见本块头注 ③）
        except Exception:
            pass  # 挂条装配异常不阻断开战（容错铁律）
        # v181 cond 接线：技能条件倍率装配（info.cond → dmg_calc/heal_calc 乘区）
        try:
            from .cond_procs import apply_cond_procs
            apply_cond_procs(actor)
        except ImportError as _e:
            _note_error("cond_procs", _e)  # 包内缺件 → 不静默（见本块头注 ③）
        except Exception:
            pass  # 条件乘区装配异常不阻断开战（容错铁律）
        mechs = {info.get("mech") for _s, info in _learned_mech_skills(actor)}
        for mech in mechs:
            cash = rules.get(mech)
            if not cash:
                continue
            mode = cash.get("mode") or ""
            # owner 方向由 mode 推断（*_target → target，其余 caster）
            owner = "target" if mode.endswith("_target") else "caster"
            if mode.startswith("per_system_clear"):
                # element_burst_3 元素裁决：每系独立乘区（per_system）
                dm = {"action": "mech_cash_per_system_mult", "mech": mech,
                      "key": cash.get("key") or mech,
                      "per_system": cash.get("per_system") or 0.0,
                      "label": cash.get("name") or mech}
                for _k in ("layer_label", "unit", "icon"):
                    if cash.get(_k):
                        dm[_k] = cash[_k]
                if owner == "target":
                    dm["owner"] = "target"
                trig.setdefault("dmg_calc", []).append(dm)
                if cash.get("clear"):
                    cl = {"action": "mech_cash_clear", "mech": mech,
                          "key": cash.get("key") or mech}
                    if owner == "target":
                        cl["owner"] = "target"
                    trig.setdefault("skill_hit", []).append(cl)
                continue
            if mode == "fury_enter":
                # 血祭：施放时花 res 层战意 → 进入狂暴（mech_val = 消耗层，技能数据）
                dm = {"action": "mech_cash_fury_enter", "mech": mech,
                      "res": cash.get("res") or "zhan_yi",
                      "mech_val_field": "mech_val",
                      "label": cash.get("label") or cash.get("name") or mech}
                if cash.get("icon"):
                    dm["icon"] = cash["icon"]
                trig.setdefault("act_cast", []).append(dm)
                continue
            if mode not in ("dmg_mult_clear", "dmg_mult_clear_target"):
                continue
            key = cash.get("key") or mech
            _per = float(cash.get("per_layer") or 0.0)
            # mech 升级（MECH_CASH.upgrade：学某 proc 被动 → 数值增强——链舞 finisher_up
            # 使终结技每段 10%→16%。proc 挂在 kind=物理 主动技上，装配器不装配，这里查学到）
            _up = cash.get("upgrade") or {}
            if isinstance(_up, dict) and _up.get("proc") and _learned_proc(actor, _up["proc"]):
                _per += float(_up.get("per_layer_add") or 0.0)
            dm = {"action": "mech_cash_dmg_mult", "mech": mech, "key": key,
                  "per_layer": _per,
                  "label": cash.get("name") or mech}
            for _k in ("layer_label", "unit", "icon"):
                if cash.get(_k):
                    dm[_k] = cash[_k]
            if owner == "target":
                dm["owner"] = "target"
            trig.setdefault("dmg_calc", []).append(dm)
            # 连段阈值必暴（cash.crit_at）：act_cast 写一次性出手态（先于伤害管线）
            if cash.get("crit_at"):
                trig.setdefault("act_cast", []).append(
                    {"action": "mech_cash_finisher_crit", "mech": mech, "key": key,
                     "crit_at": float(cash.get("crit_at") or 0),
                     "hit_key": "finisher_crit_ready"})
            if cash.get("clear"):
                cl = {"action": "mech_cash_clear", "mech": mech, "key": key}
                if owner == "target":
                    cl["owner"] = "target"
                if cash.get("clear_extra"):
                    cl["clear_extra"] = cash["clear_extra"]
                trig.setdefault("skill_hit", []).append(cl)
    except Exception:
        pass  # 技能机制装配异常不阻断开战（容错铁律）


__all__ += ["apply_class_channels", "apply_class_passives", "apply_class_mech"]
