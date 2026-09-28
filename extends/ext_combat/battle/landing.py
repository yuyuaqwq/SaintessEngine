# -*- coding: utf-8 -*-
"""v181.P4 saintess_engine 引擎——落地接口层（landing.py）。

所有"造成伤害 / 治疗回血"统一收口在这里：
- deal_damage：伤害落地（等级压制 → 防御姿态减伤 → 睡眠/蓄力 → 承伤减免读点 → 护盾 → 扣血 → 死亡）
- heal_actor：治疗落地（禁疗修正 → clamp max_hp）

为什么必须统一收口（鱼鱼架构原则）：伤害/治疗落地是"战斗物理规则"——
打谁/扣多少/护盾先挡/减伤先算/死了判负/治疗 clamp 上限。若每个机制
自己写扣血，会出现旧引擎那种"某技能绕过护盾直接扣血"的 bug。

一切来源（普攻/技能/effect handler/DOT/反伤/上层职业模块）都调本层接口，
永远走同一收口，杜绝绕过护盾/死亡判定。
"""
from __future__ import annotations

from typing import Optional

from . import formulas as _F
from . import attributes as ATTR      # 属性写口（hp 的三个写点收进它）
from .actors import DEFEND_TAG, window_open      # 状态容器：窗口条目查询（收口后唯一真源）
from .diagnostics import diag as _diag   # 阶段/钩子出错的诊断通道（P-44）
from .cues import cue as _cue          # 已迁移点位的唯一出口（措辞 = 内容侧文案表；缺表/缺 key ⇒ 报错）

# ============================================================
# 伤害落地
# ============================================================

def deal_damage(battle, source: Optional[dict], target: dict, amount: int,
                logs: list, dmg_kind: str = "", defend_reduce: Optional[float] = None,
                element: str = "", _no_redirect: bool = False,
                no_dodge: bool = False) -> int:
    """伤害落地主链。返回实际扣血。

    source: 攻击方 actor（等级压制基准；None = 无来源不压制）
    target: 承伤 actor
    amount: 计划伤害（技能公式算好的值）
    dmg_kind: "phys"/"magi"/"true"/""（免伤等按类型消费，后续扩展）
    no_dodge: True = **这一笔没人能闪**（跳过 `_roll_dodge`；缺省 False = 老行为一字不动）。
        ★ 2026-09-27：谁需要它 —— **自己付给自己的那几笔**（内容侧的自伤代价，如破势 8% /
        焚身 35% / 血债）。原先 source=None 照样过闪避那一掷 ⇒ 施放者能「闪开自己砍的这一刀」
        （实测：狂战士自伤偶发不落账 ⇒ 屏上少一行、档上少扣血，判据偶发红）。**不是**改
        「无来源」的通用语义（DoT 跳伤那一支仍旧照老规矩过同一掷 —— 改动面只在这一格开关）。
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
    # N-B8 承伤转移钩子（2026-09-11）：「挡刀」——target 身上的 `guard_uid` 指向保护者，
    # 由他替 target 承受这次伤害。语义位置：**先于一切减免结算**（连乘区/闪避/护盾都算在
    # 保护者身上，与「这一刀砍在谁身上」的一致语义相符）。
    # 引擎零游戏知识：只读字段 + 调内容侧回调（是否转移/反伤由内容侧决定）；
    # `_no_redirect` 保证递归深度 1（不链式、不成环）。
    if not _no_redirect:
        _guid = target.get("guard_uid")
        if _guid:
            try:
                _guard = battle.find_actor(_guid)
            except Exception as _e:
                _diag(battle, "deal_damage", _e)          # 审计 P-44 余量：不再静默（行为不变）
                _guard = None
            if (_guard is not None and _guard is not target
                    and int(_guard.get("hp", 0) or 0) > 0):
                _ok = True
                _hook = getattr(battle, "redirect_hook", None)
                if _hook is not None:
                    try:
                        _ok = bool(_hook(battle, target, _guard, amount, dmg_kind))
                    except Exception as _e:
                        _diag(battle, "deal_damage", _e)          # 审计 P-44 余量：不再静默（行为不变）
                        _ok = False
                if _ok:
                    _cue(battle, logs, "battle.landing.guard_cover",
                         {"guard": _guard.get('name', '守护者'),
                          "target": target.get('name', '目标')})
                    return deal_damage(battle, source, _guard, amount, logs,
                                       dmg_kind=dmg_kind, defend_reduce=defend_reduce,
                                       element=element, _no_redirect=True)
    # 等级压制（v136 双向曲线：低打高削/高打低增；PVP 不压）
    dmg = _lv_pressure(battle, source, target, amount)
    if dmg <= 0:
        return 0
    # N10-B4 元素免疫/弱点表（v178 E5 数据驱动）：target.element_immune 含元素 → 归 0；
    # element_weak[元素] > 1 → ×倍率。引擎零知识：字段/元素名全是数据。
    # N10-B6c 元素抗性（承伤方面板 elem_res/abyss_res）：dark 吃深渊抗、其余吃元素抗，
    # cap 50%——对齐旧 _hostile_mitigate 8423-8458（玩家/怪 actor 通用）。
    if element:
        try:
            _imm = target.get("element_immune") or []
            if isinstance(_imm, (list, tuple)) and element in _imm:
                _cue(battle, logs, "battle.landing.element_immune",
                     {"name": target.get('name', '敌人'), "element": element})
                return 0
            _wk = target.get("element_weak") or {}
            if isinstance(_wk, dict):
                _wm = float(_wk.get(element, 1.0) or 1.0)
                if _wm > 1.0:
                    dmg = max(1, int(dmg * _wm))
                    _cue(battle, logs, "battle.landing.element_weak",
                         {"name": target.get('name', '敌人'), "element": element})
            # 元素抗性减免（承伤方视角；怪打玩家吃玩家词条抗，玩家打怪怪无键=0 无感）
            from . import stats as _S
            _st_t = _S.actor_stats(battle, target)
            _res_key = "abyss_res" if element == "dark" else "elem_res"
            _ar = min(float(_st_t.get(_res_key, 0) or 0), 0.5)
            if _ar > 0 and dmg > 0:
                red = max(1, int(dmg * _ar))
                dmg = max(1, dmg - red)
                _cue(battle, logs, "battle.landing.resist_reduce",
                     {"red": red})
        except Exception as _e:
            _diag(battle, "deal_damage · 免疫/弱点/抗性", _e)          # 审计 P-44：不再静默（行为不变）
            pass  # 免疫/弱点/抗性异常不阻断落地
    # N9.13 数值修正钩子：taken_calc（承伤者视角减伤乘区）——装配层乘区扩展动作
    # 改 battle._fire_ctx["mult"]（沸血全减伤/death_dance 减伤等条件减伤）
    # ★ 2026-09-28 互斥（鱼鱼拍板，机制可预测）：承伤减免**只走一条通道**。同一 actor
    #   身上若既有声明了 `taken_pct` 的容器条目、又有 `taken_calc` 乘区，两条会**相乘**
    #   （0.3 × 0.4 ⇒ 实吃 0.28 伤害，机制不可预测）⇒ **声明优先**：乘区被**跳过**，
    #   并发一条 cue 说清「走了哪条、另一支被跳过」（`_skip_event_mult`）。
    # 为什么只弃**乘区**、不整条事件不 fire：内容侧挂在 `taken_calc` 上的**别的**声明动作
    #   读的是 `_fire_ctx["dmg"]` 而不是 `mult`（例：奥兰迪亚 `passive_overflow_shield`
    #   「溢出承伤转盾」）。连 fire 一起跳过会静默杀掉那些动作 —— 判据钉的是**减免这一个数
    #   只被算一次**，不是「不许任何人监听这个事件」。
    try:
        from .effect_triggers import fire as _fire
        _fctx = {"actor": target, "target": target, "source": source,
                 "dmg": dmg, "mult": 1.0}
        _fire(battle, "taken_calc", _fctx, logs)
        # ⚠️ 不可写 `... or 1.0`（2026-09-11 修）：乘区值 **0.0 是合法值**（完全免伤——
        #   格挡/无敌帧），而 `0.0 or 1.0` 会被吞成 1.0 → 0 乘区永远失效。None 才回落 1.0。
        _raw_m = _fctx.get("mult")   # 读**本次事件的 ctx 对象**（嵌套 fire 不影响它）
        _m = 1.0 if _raw_m is None else float(_raw_m)
        if _m != 1.0 and not _skip_event_mult(battle, target, _m, logs):
            dmg = max(1, int(dmg * _m))
    except Exception as _e:
        _diag(battle, "deal_damage · 修正钩子", _e)          # 审计 P-44：不再静默（行为不变）
        pass  # 修正钩子异常不阻断落地
    # N7.5a 承伤乘区（易伤：被打更疼）——target["_dmg_taken_mult"]>1 生效
    try:
        _dtm = float(target.get("_dmg_taken_mult", 0) or 0)
        if _dtm > 1.0:
            dmg = max(1, int(dmg * _dtm))
    except Exception as _e:
        _diag(battle, "deal_damage", _e)          # 审计 P-44：不再静默（行为不变）
        pass
    # N-B9 状态承伤放大（2026-09-11 接线）：持有者身上**状态声明的「每层承伤 +N%」**——
    #   对称 `stat_scale`（stats.py 那边的每层面板折算，一个改面板、一个改承伤）。
    #   引擎零知识：读通用字段 `EFFECT_RULES[key].debuff_scale.dmg_taken`，逐状态 × stacks
    #   累加成乘区；数值/层数上限全在数据侧（cap 决定最大放大，引擎不另设帽）。
    #   消费场景：对敌标记（猎印/魂印/骨噬诅咒——烙在**敌人**身上，谁打都吃）。
    try:
        from .state_effects import state_def as _sdef
        _bscale = 0.0
        for _k, _e in (target.get("effects") or {}).items():
            if not isinstance(_e, dict):
                continue
            _n = float(_e.get("stacks", 0) or 0)
            if _n <= 0:
                continue
            _sc = ((_sdef(_k) or {}).get("debuff_scale") or {}).get("dmg_taken")
            if _sc:
                _bscale += float(_sc) * _n
        if _bscale > 0:
            dmg = max(1, int(dmg * (1.0 + _bscale)))
    except Exception as _e:
        _diag(battle, "deal_damage · 状态乘区", _e)          # 审计 P-44：不再静默（行为不变）
        pass  # 状态乘区异常不阻断落地
    # N10-B6 闪避（actor 承伤 roll）：dodge 面板值 cap40%，闪避成功 → 本次承伤免伤。
    # 引擎零知识：dodge 是面板数值字段；乘算合成上限与旧 _roll_dodge 对齐。
    # 位置在防御姿态减伤前（对齐旧顺序：闪避 → 防御格挡；闪避免伤不打断蓄力——招被闪开）。
    try:
        if not no_dodge and _roll_dodge(battle, target, logs):
            return 0
    except Exception as _e:
        _diag(battle, "deal_damage · 闪避", _e)          # 审计 P-44：不再静默（行为不变）
        pass  # 闪避异常不阻断战斗
    # 防御姿态减伤（N10-B2 v178 E6 方向性防御：攻击技能自带 defend_reduce 覆盖默认
    # 0.5——如风暴之眼 0.8 = 防御挡 80% 只受 20%）
    # ★ 状态容器收口：姿态**读容器一次**（`effects["defend"]` 窗口条目；裸 bool 兄弟字段已删）
    if window_open(target, DEFEND_TAG):
        _dr = 0.5
        if isinstance(defend_reduce, (int, float)) and 0 <= float(defend_reduce) <= 0.95:
            _dr = float(defend_reduce)
        # int 截断对齐旧 landing 默认 0.5 行为（coverage 87 断言口径）
        dmg = max(1, int(dmg * (1.0 - _dr)))
        _cue(battle, logs, "battle.landing.blocked_amount", {"dmg": dmg})
    # N10-B6 百分比免伤 + 格挡（actor 承伤侧，按 dmg_kind 减免；对齐旧 _damage_actor：
    # 物免/魔免按伤害类型 cap40% → block 格挡减免一半 cap40%）
    if dmg_kind and dmg > 0:
        try:
            dmg = _apply_taken_reductions(battle, target, dmg, dmg_kind, logs)
        except Exception as _e:
            _diag(battle, "deal_damage · 免伤", _e)          # 审计 P-44：不再静默（行为不变）
            pass  # 免伤异常不阻断落地
    # ★ 收口第 2 批（2026-09-28）：**承伤减免读点**（原先这一族只有写、没有读 ——
    #   技能挂的 `reduce` 一直只落容器、伤害路径压根不读它；`reduce_left` 那个影子
    #   字段是同一件事的第二本账）。现在引擎只问内容侧一句「哪些条目声明了
    #   `taken_pct`」，累加它们的 `value`，按**内容侧骨架表** `formulas.reduce_cap()`
    #   封顶后打折。封顶未装配 = 0.0 ⇒ 折到 0 ⇒ **这一段对没声明的包零行为变化**。
    # ★★ 2026-09-28 互斥（鱼鱼拍板）：本段是承伤减免的**唯一真源**，与 `taken_calc`
    #   事件乘区**二选一**（声明优先）——`taken_calc` 那支的跳过判定在
    #   `_skip_event_mult`，两支同时成立时本段生效、乘区被跳过并发 cue 说明。
    #   封顶 `formulas.reduce_cap()` **只封这一支**（声明通道的累加值），**不封乘区** ——
    #   乘区是内容侧自己给的「本次修正」，引擎不替它设帽（口径见 wiki）。
    try:
        _red = state_reduce_of(target)
        if _red > 0:
            dmg = max(1, int(dmg * (1.0 - _red)))
            _cue(battle, logs, "battle.landing.taken_reduce",
                 {"name": target.get('name', '目标'), "pct": int(round(_red * 100))})
    except Exception as _e:
        _diag(battle, "deal_damage · 承伤减免读点", _e)          # 审计 P-44：不再静默（行为不变）
        pass  # 读点异常不阻断落地
    # N-B12 「受击打醒」数据化（2026-09-11 接线）：原实现**硬编码 key="sleep"**
    #   ——游戏名词进了引擎（违反「引擎零内容知识」），而数据侧的 `wake_on_hit: True`
    #   声明**无人读**（死字段）。现改为遍历承伤者 states，读通用字段
    #   `EFFECT_RULES[key].wake_on_hit` → 命中即移除该状态。
    #   引擎只认「布尔字段」不认态名；数据侧缺省（无该键）= 行为与接线前一致。
    try:
        from .state_effects import state_def as _sdef_w
        _ef_wake = target.get("effects")
        if isinstance(_ef_wake, dict):
            for _wk in list(_ef_wake.keys()):
                if isinstance(_ef_wake.get(_wk), dict) and (_sdef_w(_wk) or {}).get("wake_on_hit"):
                    _ef_wake.pop(_wk, None)
                    _cue(battle, logs, "battle.landing.woken", {})
    except Exception as _e:
        _diag(battle, "deal_damage · 打醒", _e)          # 审计 P-44：不再静默（行为不变）
        pass  # 打醒异常不阻断落地
    # 出招窗口的打断**不**由「受到主动伤害」触发（T15 §0 D15 第 2 条）：普通伤害照常
    # 结算，只是不取消前摇；控制类效果由内容侧挂引擎 `interrupt` 动作显式打断
    # （effects.act_interrupt —— 内容侧定「哪些效果算控制」，引擎不认识控制词）。
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
        except Exception as _e:
            _diag(battle, "deal_damage · 事件源", _e)          # 审计 P-44：不再静默（行为不变）
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
    except Exception as _e:
        _diag(battle, "_lv_pressure", _e)          # 审计 P-44：不再静默（行为不变）
        pass
    return dmg


def _roll_dodge(battle, target: dict, logs: list) -> bool:
    """N10-B6：actor 承伤闪避（对齐旧 battle._roll_dodge 基础段）。

    读 S.actor_stats(target) 的 dodge 面板值，上限走**声明表**（`_F.dodge_cap()`，
    默认 0.40 = 原写死值，见 formulas.py 那条注）。
    引擎零知识：dodge 是面板数值字段，闪避是通用承伤规则。
    闪避成功返回 True（调用方中断本次承伤/免伤）。
    """
    try:
        if not target:
            return False
        from . import stats as S
        st = S.actor_stats(battle, target)
        dodge = min(float(st.get("dodge", 0) or 0), _F.dodge_cap())     # 上限 = 声明值（审计 E2）
        if dodge <= 0:
            return False
        import random
        if random.random() < dodge:
            _cue(battle, logs, "battle.landing.dodged", {"name": target.get('name', '目标')})
            return True
    except Exception as _e:
        _diag(battle, "_roll_dodge", _e)          # 审计 P-44：不再静默（行为不变）
        pass
    return False


def _apply_taken_reductions(battle, target: dict, dmg: int, dmg_kind: str,
                            logs: list) -> int:
    """N10-B6：承伤侧百分比免伤 + 格挡（对齐旧 _damage_actor 物免/魔免段 + block 段）。

    按 dmg_kind 消费（phys 段吃物免 / magi 段吃魔免；各 cap 40%），随后 block 格挡
    概率减免一半（cap 40%）。真伤/空 kind 不减免。引擎零知识：减免率是面板数值；
    格挡的两个常量（概率上限 cap / 命中减免比例 reduce）读内容侧骨架表（V4 下沉，
    `formulas.block_cap()/block_reduce()`；未装配 → 0.0 = 不格挡）。
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
                _cue(battle, logs, "battle.landing.phys_immune", {"red": red})
        if "magi" in kd and "true" not in kd:
            mr = min(float(st.get("magic_reduce", 0) or 0), 0.4)
            if mr > 0:
                red = max(1, int(dmg * mr))
                dmg = max(1, dmg - red)
                _cue(battle, logs, "battle.landing.magic_resist", {"red": red})
        if dmg > 0 and "true" not in kd:
            import random
            # V4：0.40（上限）/ 0.5（命中减免）从内容侧骨架表读（原写死字面量）
            bc = min(float(st.get("block", 0) or 0), _F.block_cap())
            if bc > 0 and random.random() < bc:
                red = max(1, int(dmg * _F.block_reduce()))
                dmg = max(1, dmg - red)
                _cue(battle, logs, "battle.landing.block_reduce", {"red": red})
    except Exception as _e:
        _diag(battle, "_apply_taken_reductions", _e)          # 审计 P-44：不再静默（行为不变）
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
        # 保命下限 `max(1,…)` 是**机制行为**（不是引擎内建规则）⇒ 算完再交给写口
        ATTR.set_current(target, "hp", max(1, int(mhp * guard_pct)),
                         reason="death_guard", battle=battle)
        # 额外回血（走 heal_actor 收口——clamp max_hp / on_heal 联动）
        heal_pct = float(cfg.get("heal_pct") or 0.0)
        if heal_pct > 0 and target.get("hp", 0) < mhp:
            heal_actor(battle, target, int(mhp * heal_pct), logs)
        _cue(battle, logs, "battle.landing.death_guard", {"name": target.get('name', '目标')})
        return True
    except Exception as _e:
        _diag(battle, "_apply_death_guard", _e)          # 审计 P-44：不再静默（行为不变）
        return False


def _skip_event_mult(battle, target: dict, mult: float, logs: list) -> bool:
    """**互斥判定**：这一笔该事件乘区要不要被跳过（承伤方同时有 `taken_pct` 声明时跳过）。

    ★ 2026-09-28（鱼鱼拍板）：承伤减免**同一状态只走一条通道**。
      · 通道 A（**声明**）= 容器里声明了 `taken_pct` 的条目累加（`state_reduce_of`）
      · 通道 B（**事件**）= `taken_calc` 乘区（内容侧在 `on_taken`/乘区动作里改 `_fire_ctx["mult"]`）
      两条各自成立时**会相乘**（0.3 × 0.4 ⇒ 实吃 28% 而非 42%）⇒ 机制不可预测。
      ⇒ **声明优先**：通道 A 命中时通道 B 被跳过，并发一条 cue 说清走了哪条、弃了哪条。

    返回 True = 跳过（通道 A 优先）；False = 照常乘。
    「通道 A 命中」的口径 = `state_reduce_of(target) > 0.0`：**已按内容侧封顶折算后的
    生效比例**，不是「有没有声明」。理由：封顶未装配（`reduce_cap` = 0.0）或声明了但
    累加 ≤0 时，通道 A **实际不减伤** —— 那时不构成「两条都在减伤」，放通道 B 过是
    唯一让减伤真发生的选择（否则会出现「两条都声明了、却一次都不减」的死局）。
    封顶后的比例是本函数唯一的判据来源，故**与读点读的是同一个 getter**（不会分叉）。
    """
    if not isinstance(mult, (int, float)) or float(mult) == 1.0:
        return False                       # 没改乘区 = 通道 B 根本没参与，无从互斥
    # ★ 2026-09-28 审计修（台账 L3298-3）：判据**只管减免**（`mult < 1.0`）。
    #   原判据只排除了 `== 1.0`，于是 `mult > 1.0` 的**放大**乘区（易伤 / vuln，
    #   真实内容侧写口 `games/orlandia/content/mech/team_procs.py::timed_vuln_apply`
    #   = `ctx["mult"] *= (1+amp)`）也会被整条互斥路径判**跳过** ⇒ **放大乘区被静默丢弃**：
    #   角色身上同时有 `taken_pct` 声明与易伤时，易伤**完全不生效**（伤害不涨反少）。
    #   判据的口径是「两条**减伤**相乘会让减免不可预测」——放大器**不属减免**，
    #   它与声明通道不冲突，必须照常生效。
    if float(mult) >= 1.0:
        return False                       # 放大乘区：不是减免 ⇒ 不构成互斥，放行
    try:
        from .state_effects import taken_pct_keys
        if not taken_pct_keys(target):
            return False                   # 通道 A 一条都没有 = 无冲突
        declared = state_reduce_of(target)
    except Exception as _e:
        _diag(battle, "_skip_event_mult", _e)   # 审计 P-44：不再静默（行为不变）
        return False
    if declared <= 0.0:
        return False                       # 声明在、但生效比例 0（封顶未装/值 0）⇒ 不算通道 A 参与
    _cue(battle, logs, "battle.landing.taken_mult_skipped",
         {"name": target.get('name', '目标'),
          "pct": int(round(declared * 100)),
          "mult_pct": int(round((1.0 - float(mult)) * 100))})
    return True


def state_reduce_of(actor: dict) -> float:
    """actor 身上**声明了 `taken_pct`** 的条目累加出的承伤减免比例（已封顶）。

    ★ 收口第 2 批（2026-09-28）：这是「带 value 的状态」这一族的**第二个读点**
      （第一个是 `absorb` 吸收型）。引擎零游戏名词：它只问内容侧声明了什么，
      不认「哪个 key 是减伤」——声明不写，这里恒为 0.0 = 不减伤。
    封顶走**内容侧骨架表** `formulas.reduce_cap()`（未装配 → 0.0 ⇒ 折到 0），
    与 `actions._do_buff` 写这一族时用的封顶是**同一个 getter**（读写对称）。
    """
    from .state_effects import taken_pct_keys
    keys = taken_pct_keys(actor)
    if not keys:
        return 0.0
    ef = (actor or {}).get("effects") or {}
    total = 0.0
    for key in keys:
        entry = ef.get(key)
        if not isinstance(entry, dict):
            continue
        try:
            total += float(entry.get("value", 0) or 0)
        except (TypeError, ValueError) as _e:
            _diag(None, "state_reduce_of · 坏 value", _e)      # 审计 P-44：不再静默（行为不变）
    if total <= 0:
        return 0.0
    return min(total, _F.reduce_cap())


def _apply_damage(battle, target: dict, dmg: int, logs: list,
                  source: Optional[dict] = None) -> int:
    """承伤落地：护盾吸收 → hp 扣减 → 死亡判定。返回实际扣血。

    source: 攻击方（击杀事件 on_kill 用；None = DOT/环境无击杀者）
    """
    # ---- 承伤吸收（收口第 2 批：容器里**声明了 `absorb`** 的条目，逐条扣 `value`）----
    #   原先是独立容器 `target["shields"]`（第二本账）⇒ 改走状态容器：
    #   「带 value 的状态」这一族里声明 `absorb` 的那些（`state_effects.absorb_keys`）。
    #   语义逐条不变：按容器顺序逐条扣、每条发一条 cue、扣完 ≤0 即从容器删、
    #   剩余伤害继续往下走（`dmg <= 0` 的早返回与「吸收 → 扣血」先后顺序一字不动）。
    try:
        from .state_effects import absorb_keys
        _abs = absorb_keys(target)
    except Exception as _e:
        _diag(battle, "deal_damage · 吸收族查询", _e)          # 审计 P-44：不再静默（行为不变）
        _abs = []
    if _abs:
        _ef = target.get("effects")
        if not isinstance(_ef, dict):
            _ef = target["effects"] = {}
        remaining = dmg
        for ak in _abs:
            entry = _ef.get(ak)
            if not isinstance(entry, dict):
                continue
            if int(entry.get("value", 0) or 0) <= 0:
                continue
            sv = int(entry["value"])
            absorb = min(sv, remaining)
            entry["value"] = sv - absorb
            remaining -= absorb
            _cue(battle, logs, "battle.landing.shield_absorb",
                 {"name": target.get('name', '目标'), "absorb": absorb})
            if entry["value"] <= 0:
                _ef.pop(ak, None)
            if remaining <= 0:
                break
        dmg = remaining
    if dmg <= 0:
        return 0
    old = int(target.get("hp", 0) or 0)
    new = max(0, old - dmg)
    ATTR.set_current(target, "hp", new, reason="damage", battle=battle)
    _real = old - new
    # ★ 屏上那个数 = **这一击的真伤害**（2026-09-27 修）：原先印 `_real` = 被剩余血**钳过**的数 ——
    #   「5 层垂星印 126」其实是 150+ 被 126 点血截出来的假数（试玩取数会被坑），击杀那一手更明显
    #   （「受到 25 点伤害，倒下了」而实际是一发 152）。扣血 / 返回 / on_kill 的 `dmg` 全不动，
    #   只把呈现用数换成未被血条截断的那一个。
    _shown = int(dmg)
    # 濒死保护（N9.12）：伤害会致死时查 target.state death_guard 层（声明表参数）
    # → 保底不死亡 + 回血 + 层-1。规则通用（引擎零名词——声明表 guard_hp_pct/heal_pct）
    if new <= 0:
        _guarded = _apply_death_guard(battle, target, logs)
        if _guarded:
            new = int(target.get("hp", 0) or 0)
            _real = old - new
    if new <= 0:
        _cue(battle, logs, "battle.landing.down",
             {"name": target.get('name', '目标'), "dmg": _shown})
        if hasattr(battle, "_on_actor_dead"):
            battle._on_actor_dead(target, logs)
        # N8 事件：击杀（主体=击杀者；DOT/环境杀无 on_kill）
        if source is not None:
            try:
                from .effect_triggers import fire as _fire
                _fire(battle, "on_kill", {"actor": source,
                                          "target": target, "dmg": _real}, logs)
            except Exception as _e:
                _diag(battle, "_apply_damage · 事件源", _e)          # 审计 P-44：不再静默（行为不变）
                pass  # 事件源异常不阻断落地
    else:
        _cue(battle, logs, "battle.landing.damage",
             {"name": target.get('name', '目标'), "dmg": _shown})
    return _real


# ============================================================
# 治疗落地
# ============================================================

def heal_actor(battle, target: dict, amount: int, logs: list,
               source: Optional[dict] = None, label: str = "",
               _no_redirect: bool = False) -> int:
    """治疗落地核心（actor-agnostic，统一收口）。

    - 禁疗修正（target.state/buffs 的 heal_down / _anti_heal_pct，后续扩展）
    - clamp max_hp
    返回实际回血量。
    """
    if target is None or amount is None:
        return 0
    if target.get("hp") is None:
        return 0  # 无 hp 容器不可被治疗落地
    # N-B8b 治疗转移钩子（2026-09-11）：`heal_share_uid` 指向的 actor 分担/承受这次治疗
    # （faith_share「治疗伤害分担」）。同 deal_damage 的转移语义：只读字段 + 调内容侧回调。
    if not _no_redirect:
        _sid = target.get("heal_share_uid")
        if _sid:
            try:
                _share = battle.find_actor(_sid)
            except Exception as _e:
                _diag(battle, "heal_actor", _e)          # 审计 P-44 余量：不再静默（行为不变）
                _share = None
            if _share is not None and _share is not target:
                _ok = True
                _hook = getattr(battle, "heal_redirect_hook", None)
                if _hook is not None:
                    try:
                        _ok = bool(_hook(battle, target, _share, amount, label))
                    except Exception as _e:
                        _diag(battle, "heal_actor", _e)          # 审计 P-44 余量：不再静默（行为不变）
                        _ok = False
                if _ok:
                    _cue(battle, logs, "battle.landing.heal_shared",
                         {"name": _share.get('name', '分担者')})
                    return heal_actor(battle, _share, amount, logs, source=source,
                                      label=label, _no_redirect=True)
    heal = max(0, int(amount))
    if heal <= 0:
        return 0
    # 禁疗/重伤修正（target 自身状态）
    heal = _apply_heal_mods(battle, target, heal, logs)
    if heal <= 0:
        return 0
    _before = int(target.get("hp", 0) or 0)
    ATTR.set_current(target, "hp", _before + heal, reason="heal", battle=battle)
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
        except Exception as _e:
            _diag(battle, "heal_actor · 事件源", _e)          # 审计 P-44：不再静默（行为不变）
            pass  # 事件源异常不阻断落地
    return _real


def _apply_heal_mods(battle, target: dict, amount: int, logs: list) -> int:
    """受疗/禁疗修正（target 自身效果）。返回修正后治疗量（未 clamp）。

    ★ 2026-09-27（B2）：本函数原先「拿不到 `battle`」（用只读持有者 `_TextHolder(text)`
    过文案口）。禁疗/重伤两行的措辞已迁进内容侧文案表 ⇒ 表现走 `_cue(battle, …)`
    （同步就地 append），所以这里必须拿到 `battle` 本身（总线 + 文案表都在它身上）——
    `_TextHolder` 随之删除（它的存在理由就是「拿不到 battle」）。
    """
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
        # 禁疗（heal_down 层×每层比例 cap 上限——effects 条目 stacks；V4 两数读内容侧骨架表）
        hd_entry = ef.get("heal_down")
        if isinstance(hd_entry, dict):
            ehd = int(hd_entry.get("stacks", 0) or 0)
            if ehd > 0:
                cut = max(0.0, min(ehd * _F.heal_down_per_stack(), _F.heal_down_cap()))
                heal = max(0, int(heal * (1 - cut)))
                _cue(battle, logs, "battle.landing.heal_forbid", {"pct": int(cut * 100)})
        # 重伤（_anti_heal_pct cap 上限；effects 条目 value 内嵌；V4 上限读内容侧骨架表）
        ah_entry = ef.get("_anti_heal_pct")
        if isinstance(ah_entry, dict):
            aheal = float((ah_entry.get("value") or {}).get("pct", 0) or 0)
            if aheal > 0:
                cut2 = max(0.0, min(aheal, _F.anti_heal_cap()))
                heal = max(0, int(heal * (1 - cut2)))
                _cue(battle, logs, "battle.landing.heal_wound", {"pct": int(cut2 * 100)})
    except Exception as _e:
        # ★ 2026-09-27（B2）：签名改成接 `battle`（表现层要发 cue）⇒ 这里回到正常的
        #   `_diag(battle, …)`（2026-09-25 那版传 None 是因为当时签名里没有 battle）。
        _diag(battle, "_apply_heal_mods", _e)          # 审计 P-44：不再静默（行为不变）
        pass
    return max(0, heal)
