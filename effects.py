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


# ============================================================
# 动词执行器
# ============================================================

# ---- control：让目标 N 刻不能行动 ----

@register_action("control")
def act_control(battle, caster, target, params, logs):
    """控制：写 target.effects[tag] = 控制快照（v181.N7.2，V 系列容器统一）。

    引擎不认"眩晕/冻结/沉默"——只执行"目标被标记 tag 持续 N 刻"，
    消费（跳过行动/禁技能）由调度层按 mode 执行：
      mode=skip（整跳）：轮到该 actor 行动 → 跳过 + 清除（stun/freeze/sleep）
      mode=no_skill（禁技）：行动时技能转普攻（silence）
    缺省 mode=skip。tag/turns/mode 由数据给（引擎零名词知识）。
    条目：effects[tag] = {"expire": 绝对时刻, "mode": mode, "stacks": 1}
    """
    from .battle import _now_of
    if not target:
        return
    tag = params.get("tag") or params.get("key")
    turns = int(params.get("turns", 0) or 0)
    if not tag or turns <= 0:
        return
    # Boss 控制减半（对齐旧 _boss_ctrl_dur）
    if target.get("is_boss") or target.get("role") == "boss":
        turns = max(1, turns // 2)
    mode = params.get("mode", "skip")
    now = _now_of(battle)
    ef = target.setdefault("effects", {})
    old = ef.get(tag)
    old_exp = float(old.get("expire", 0) or 0) if isinstance(old, dict) else 0.0
    ef[tag] = {"expire": max(old_exp, now + turns), "mode": mode, "stacks": 1}
    logs.append(f"💫 {target.get('name', '目标')} 被【{tag}】{turns} 刻！")


# ---- buff：给 actor 挂属性/减伤/免疫 buff ----

@register_action("buff")
def act_buff(battle, caster, target, params, logs):
    """通用 buff：写 actor.effects[key] = 状态快照（v181.N7.1，V 系列容器统一）。

    形态（增益）：{"stacks": 1, "expire": now+turns, "stat": 面板键, "op": "mul"|"add",
                  "mult": 倍率/加值}——数值由动作参数（EFFECT_ACTIONS）给出并快照进条目，
    面板折算读条目（stats._apply_effects），引擎不查任何名字表。

    形态（value 型，如 reduce 减伤百分比）：{"stacks", "expire", "v": float, "hits"}——
    无面板乘区，纯状态（消费由规则表）。兼容旧 pct_from_mech_val 参数折算。

    on=target 时作用于 target（对敌减益型 buff）。
    """
    from .battle import _now_of
    holder = caster if params.get("on", "caster") == "caster" else (target or caster)
    if not holder:
        return
    key = params.get("key") or params.get("tag")
    turns = int(params.get("turns", 0) or 0)
    if not key or turns <= 0:
        return
    now = _now_of(battle)
    expire = now + turns
    ef = holder.setdefault("effects", {})
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
        logs.append(f"🛡️ {key} {float(value):.0%}（持续 {turns} 刻）")
        return
    # 增益：动作参数 stat/op/mult（EFFECT_ACTIONS 配置给）→ 快照进条目
    stat = params.get("stat")
    op = params.get("op")
    mult = params.get("mult")
    if stat and mult is not None:
        old = ef.get(key)
        old_exp = float(old.get("expire", 0) or 0) if isinstance(old, dict) else 0.0
        ef[key] = {"stacks": 1,
                   "expire": max(old_exp, expire),
                   "stat": stat, "op": op or "mul", "mult": float(mult)}
        logs.append(f"✦ {key} 提升（{op or 'mul'}×{mult}，持续 {turns} 刻）")
        return
    # 无 stat 的纯状态 buff（免疫/一次性/标记等）：只记录到期，不折算面板
    hit_params = params.get("hit")
    old = ef.get(key)
    old_exp = float(old.get("expire", 0) or 0) if isinstance(old, dict) else 0.0
    entry = {"stacks": 1, "expire": max(old_exp, expire)}
    # N7.3 出手消费型：hit 子键声明出手效果（dmg_mult 增伤 / guaranteed_crit 必暴）
    if isinstance(hit_params, dict):
        entry["hit"] = dict(hit_params)
        logs.append(f"✦ {key} 出手效果就绪（{turns} 刻内生效）")
    else:
        logs.append(f"✦ {key}（持续 {turns} 刻）")
    ef[key] = entry


# ---- shield：护盾 ----

@register_action("shield")
def act_shield(battle, caster, target, params, logs):
    """护盾：写 actor.shields[key]（v181.N7.2 补 expire_at + 同源叠厚）。

    结构：shields[key] = {"value": 盾值, "expire_at": now+turns, "halve": bool}
    - 同源（同 key）：value 累加（叠厚）+ expire_at 取 max（对齐旧 _add_shield）
    - 异源并存各计各的时长
    - turns=0/缺省 → 3 刻；turns>=999 → 永久（expire_at=None，不到期删）
    value/halve/turns 由数据给。
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
        value = int(holder.get("max_hp", 1) * 0.20)
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
    logs.append(f"🛡️ {holder.get('name', '目标')} 获得护盾 {value} 点！")


# ---- cleanse：净化 ----

@register_action("cleanse")
def act_cleanse(battle, caster, target, params, logs):
    """净化：移除目标身上的 DOT/标记/控制。

    - DOT/标记（effects 条目）：查 EFFECT_RULES 表 dot/on=target 的 key 动态清理
    - 控制（effects 条目 mode）：按 control_tags 配置清（引擎查配置）
    """
    from . import config
    from .state_effects import all_state_effects
    actor = target or caster
    if not actor:
        return
    rem = []
    ef = actor.setdefault("effects", {})
    state_table = all_state_effects()
    for k in list(ef.keys()):
        cfg = state_table.get(k) or {}
        if cfg.get("dot") or cfg.get("on") == "target":
            rem.append(k)
            ef.pop(k, None)
    # 控制 tag 清理（配置声明的控制键；缺省常见集）
    ctrl_tags = config.get_cleanse_tags()
    for k in ctrl_tags:
        if k in ef:
            rem.append(k)
            ef.pop(k, None)
    if rem:
        logs.append(f"✨ 净化了 {'、'.join(rem)}！")
    else:
        logs.append("✨ 净化（无减益可解）")


@register_action("cleanse_all")
def act_cleanse_all(battle, caster, target, params, logs):
    """全体净化：施法者自身全部减益（副本广播在命令层）。"""
    act_cleanse(battle, caster, target or caster, params, logs)


# ---- effects 叠层（统一效果容器；V 系列：原 state 语义） ----

@register_action("state_add")
def act_state_add(battle, caster, target, params, logs):
    """通用叠层加值：actor.effects[key].stacks 加 amount（cap 查规则表）。"""
    on = params.get("on", "caster")
    holder = caster if on == "caster" else (target or caster)
    if not holder:
        return
    key = params.get("key") or params.get("mech")
    amount = int(params.get("amount", params.get("stacks", 0)) or 0)
    if not key or amount <= 0:
        return
    ef = holder.setdefault("effects", {})
    entry = ef.get(key)
    if not isinstance(entry, dict):
        entry = ef[key] = {}
    cap = int(state_def(key).get("cap") or 0) or 999999
    cur = int(entry.get("stacks", 0) or 0)
    entry["stacks"] = max(0, min(cap, cur + int(amount)))
    n = entry["stacks"]
    cap_txt = f"/{cap}" if cap < 999999 else ""
    logs.append(f"✦ {key} {n}{cap_txt}（+{amount}）")
    # N8 事件：状态阈值（层数变化后——主体=层数持有者；"战意满 10 → 狂暴"由上层声明匹配）
    try:
        from .effect_triggers import fire as _fire
        _fire(battle, "threshold", {"actor": holder, "key": key, "value": n}, logs)
    except Exception:
        pass


@register_action("state_spend")
def act_state_spend(battle, caster, target, params, logs):
    """通用叠层消费：actor.effects[key].stacks 扣 amount（下限 0）。"""
    on = params.get("on", "caster")
    holder = caster if on == "caster" else (target or caster)
    if not holder:
        return
    key = params.get("key") or params.get("mech")
    amount = int(params.get("amount", params.get("stacks", 0)) or 0)
    if not key or amount <= 0:
        return
    ef = holder.setdefault("effects", {})
    entry = ef.get(key)
    cur = int(entry.get("stacks", 0) or 0) if isinstance(entry, dict) else 0
    if cur < amount:
        logs.append(f"⚠️ {key} 不足（需 {amount}，当前 {cur}）")
        return
    if not isinstance(entry, dict):
        entry = ef[key] = {}
    entry["stacks"] = max(0, cur - int(amount))
    logs.append(f"✦ 消耗 {amount} 点 {key}（剩余 {cur - amount}）")


# ============================================================
# N7.5a 补战斗动词：heal / state_set / interrupt
# ============================================================

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
        logs.append(f"✨ {holder.get('name', '目标')} 恢复了 {real} 点生命！")


@register_action("state_set")
def act_state_set(battle, caster, target, params, logs):
    """层数置值（N7.5a，stacks_set 语义）：actor.effects[key].stacks 直接置 amount。

    与 state_add 区别：add 是叠加，set 是覆盖（如 Boss 断过载 → 充能回 3）。
    """
    holder = caster if params.get("on", "caster") == "caster" else (target or caster)
    if not holder:
        return
    key = params.get("key") or params.get("mech")
    amount = int(params.get("amount", params.get("value", 0)) or 0)
    if not key:
        return
    cap = int(state_def(key).get("cap") or 0) or 999999
    val = max(0, min(cap, amount))
    ef = holder.setdefault("effects", {})
    entry = ef.get(key)
    if not isinstance(entry, dict):
        entry = ef[key] = {}
    entry["stacks"] = val
    logs.append(f"✦ {key} 置为 {val}")
    # N8 事件：状态阈值（置值也广播——主体=层数持有者；Boss 充能断点/回充场景）
    try:
        from .effect_triggers import fire as _fire
        _fire(battle, "threshold", {"actor": holder, "key": key, "value": val}, logs)
    except Exception:
        pass


@register_action("interrupt")
def act_interrupt(battle, caster, target, params, logs):
    """打断读条（N7.5a）：清 target.charging（蓄力技被打断）。"""
    actor = target or caster
    if not actor:
        return
    if actor.get("charging") and actor["charging"].get("skill"):
        actor["charging"] = None
        logs.append(f"🔨 {actor.get('name', '目标')} 的蓄力被打破了！")


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
        logs.append(f"💥 {holder.get('name', '目标')} 受到 {real} 点伤害！")
