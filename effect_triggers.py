# -*- coding: utf-8 -*-
"""v181.P4 battle2 引擎——事件总线（effect_triggers.py，N8）。

按 docs/DESIGN_effect_system_v2.md Part 3.3/4：
- 效果系统 v2 提供统一触发总线：所有"事件匹配触发"型效果声明何时触发，
  引擎在固定点 fire(event, ctx)，不再为某个具体效果手写 if 分支。
- 效果源 = actor["triggers"] = {事件名: [效果名词 dict, ...]}：
  actor 全同构，任何 actor 都能声明（装备特效/词条/套装/被动/Boss 机制
  由数据桥/上层在构造 actor 时翻译成 triggers 挂上——引擎不认名词内容，
  只分发：fire 匹配声明 → effects.apply_effects 名词→动词翻译执行）。
- 引擎零游戏知识：事件名是引擎协议（本文件 EVENTS），效果内容是游戏名词
  （走 EFFECT_ACTIONS 翻译）。换一套配置 = 新游戏，引擎零改动。

ctx 语义（插桩点统一约定）：
    caster : 效果的施放方（skill_hit=攻击者；on_kill=击杀者；battle_start=None）
    target : 效果的作用目标（skill_hit=被打者；on_taken=受击者；on_heal=被治疗者）
    actor  : 事件主体（on_death=死者；dot_tick=受跳者；buff_expire=buff 持有者）
    info   : 技能 dict（可选）
    dmg/amount/real : 伤害/治疗数值（可选）

执行语义：对每个存活 actor，查自身 triggers[event] → 以 ctx.caster/ctx.target
为默认施放方/目标执行（effect dict 可带 on 覆盖作用对象）。

# 事件全集（DESIGN_effect_system_v2.md §3.3 19 时机 + N9.13 dmg_calc/taken_calc + act_done）：
#    battle_start 开战（词条/套装/仪式）   turn_start actor 回合开始
#    act_begin 行动前（读条前）            act_cast 行动施放瞬间（耗蓝/读条后）
#    skill_hit 技能命中后                  attack_hit 普攻命中后
#    crit 暴击命中（命中子集）             on_taken 受击（承伤后）
#    on_heal 治疗生效                      on_kill 击杀敌人
#    on_death 死亡                         dot_tick DOT 每跳
#    on_act_consume 行动级消费点（控制跳过） on_hit_consume 出手消费点（一次性）
#    buff_expire buff 到期钩子             threshold 状态阈值（层数变化后）
#    dmg_calc 伤害算出后（攻击方乘区）      taken_calc 承伤修正（承伤方乘区）
#    act_done 行动完成（全员广播——效果侧自判敌我，randuin/ice_vein 用）
#    phase Boss 阶段转换（N9 上层）        player_low 玩家低血量（N9 上层）
#    pv_broken 破防（N9 上层）

N9 起：phase/player_low/pv_broken 无引擎自然点位（Boss 机制上层驱动），
由上层按需调 fire()（EVENTS 已声明全集）。引擎已插桩自然点位 = 除
phase/player_low/pv_broken 外 16 个（battle/actions/landing/schedule/effects）。
"""
from __future__ import annotations

from .actors import actor_alive

# 19 时机事件全集（必须单行定义——cov 按行 trace，多行续行会永久漏记；
# 中文语义见模块 docstring）
EVENTS = ("battle_start", "turn_start", "act_begin", "act_cast", "skill_hit", "attack_hit", "crit", "on_taken", "on_heal", "on_kill", "on_death", "dot_tick", "dot_calc", "on_act_consume", "on_hit_consume", "buff_expire", "threshold", "dmg_calc", "taken_calc", "heal_calc", "act_done", "phase", "player_low", "pv_broken", "interrupt")

# N9.13 数值修正钩子（伤害/承伤乘区——装配层乘区扩展动作改 _fire_ctx["mult"] 累乘）：
#   dmg_calc  = 伤害算出后落地前（攻击者视角条件乘区：处决低血增伤/破魔/叠层放大器）
#   taken_calc = 承伤修正（承伤者视角减伤乘区：沸血全减伤/death_dance 减伤）
#   heal_calc = 治疗算出后落地前（施法者视角乘区——v181.M-R2e B2：faith 负载档位
#               heal_mult；subject=施法者，只处理施法者自己声明的 triggers）


def fire(battle, event: str, ctx: dict, logs: list) -> None:
    """事件总线唯一入口：匹配声明 → 翻译执行。引擎各点调用。

    - event 不在 EVENTS 全集 → 静默忽略（防拼写漂移；引擎不抛）
    - 遍历全部阵营存活 actor：actor.triggers[event] → apply_effects
    - 执行异常不阻断（与 effects.apply_effects 容错一致）
    """
    if not event or event not in EVENTS:
        return
    if logs is None or not getattr(battle, "sides", None):
        # logs 必须显式传（可为空列表）；无 sides = 非战斗上下文空转安全
        return
    ctx = dict(ctx or {})
    # caster 缺省 = 声明者自己（battle_start 起手效果/受击自我强化等无显式
    # 施放方的场景）；target 保持事件目标（可由插桩点显式给）。
    caster = ctx.get("caster")
    target = ctx.get("target")
    # 事件主体过滤（N9 修正）：ctx.actor = 该事件的主体 actor（谁回合/谁施法/谁受击/
    # 谁被治疗...）——只处理主体 actor 自己声明的 triggers，避免旁观者（同阵营其他
    # 带装备 actor）效果被全局广播误触发。None = 无主体事件（battle_start：全体触发）。
    subject = ctx.get("actor")
    # 事件上下文暂存（游戏侧扩展动作读：dmg/heal/amount/is_crit/overflow/source...）——
    # 引擎动词不读；这是装配层族动作（ACTION_HANDLERS 扩展注册）拿事件数值的通道。
    # 单线程战斗同步 fire，下一 fire 覆盖；不落盘。
    ctx.setdefault("_event", event)
    battle._fire_ctx = ctx
    for acts in battle.sides.values():
        for a in acts:
            # 主体事件只处理主体 actor；主体死亡例外（on_death 死者自己的效果由
            # 引擎动词执行，fire 允许 subject=dead 的声明执行——如死亡遗言类）
            if subject is not None and a is not subject:
                continue
            if not actor_alive(a) and a is not subject:
                continue
            effs = (a.get("triggers") or {}).get(event)
            if not effs:
                continue
            try:
                from .effects import apply_effects
                # 声明者（owner）随副本注入 params（扩展动作自查归属用）
                eff_list = []
                for _e in effs:
                    if isinstance(_e, dict):
                        _e2 = dict(_e)
                        _e2.setdefault("_owner", a)
                        eff_list.append(_e2)
                    else:
                        eff_list.append(_e)
                apply_effects(battle, caster if caster is not None else a,
                              target, eff_list, logs)
            except Exception:
                # 单个源异常不阻断其他源/战斗（引擎容错）
                continue
    # 战斗级观察者（N5b4-5E）：fire 尾部通知外部（命令层记账/团队广播/存活同步）。
    # 只读 ctx 或调引擎动词改状态，不返回影响结算；异常不阻断（观察者容错）。
    _obs = getattr(battle, "on_event", None)
    if _obs is not None:
        try:
            _obs(battle, event, ctx, logs)
        except Exception:
            pass
