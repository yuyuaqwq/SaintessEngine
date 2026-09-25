# -*- coding: utf-8 -*-
"""v181.P4 saintess_engine 引擎——CTB 时间轴调度（schedule.py）。

按 docs/archive/REFACTOR_v181P4_FULL_PLAN.md Part 7 schedule.py + 旧引擎 v154 语义：

- **机制（归引擎）**：actor.ct = 下次能行动的时刻（绝对时刻）；谁 ct 小谁先动；
  行动后 `ct = now + 第一段耗时 + 第二段耗时`；1 刻 = 1 时刻 = 1 游戏秒（ACT_TICK=1）。
- **一次行动耗时多少（归内容侧）**：引擎**不内置**任何时间公式形状与基准耗时数值，
  一律向注入面取 —— 见下方 `_time_model_fn()` / `action_time()` / `action_base_of()`；
  第二段（收招）同口径：`_recover_fn()` / `recover_time()` / `recover_base_of()`。
  引擎不叫它「出招/收招」，只做「两段相加」——业务词归内容侧。
- 命令层驱动：玩家出手 → advance() 推进到下一个决策点（途中自动 actor 自动行动）

注入面（内容侧装配；与 `battle/formulas.py` 同款 `saintess_engine.config` hook 面）：

    time_model_fn   hook 名，值 = `fn(spd, base) -> float`（一次行动耗时，单位 = 游戏秒）
    action_base_fn  hook 名，值 = `fn(action) -> float`（行动类别 → 基准耗时；
                    未声明的类别由引擎回落到内容侧基准表的 `DEFAULT_ACTION` 项）
    recover_model_fn  hook 名，值 = `fn(spd, base) -> float`（**第二段**耗时，单位 = 游戏秒）
    recover_base_fn   hook 名，值 = `fn(action) -> float`（行动类别 → 第二段基准耗时）

**未装配 → fail-closed**：直接抛 `config.EngineNotConfigured`（点名 hook 名）。
引擎不提供任何"中性/默认公式"——那是编出来的数，本仓口径禁止静默降级。

引擎只有"时刻/速度/行动耗时/行动类别"，不认识阵营/职业/游戏名。
"""
from __future__ import annotations

from typing import Optional

from saintess_engine import config as _cfg
from .diagnostics import diag as _diag   # 阶段/钩子出错的诊断通道（P-44）
from .actors import actor_alive
from . import traits                    # 内容侧标签判定（引擎不认标签叫什么 · 审计 E3）
from .effects import _cap_of as _stack_cap_of
from saintess_engine.text import render_via

#: 内容侧「行动类别 → 基准耗时」表里，未知/未声明类别回落到哪个类别（通用键名，非游戏词）
DEFAULT_ACTION = "attack"


def _time_model_fn():
    """内容侧时间模型（一次行动耗时）——未装配即抛 `EngineNotConfigured`（fail-closed）。"""
    fn = _cfg.get_hook("time_model_fn")
    if fn is None:
        raise _cfg.EngineNotConfigured(
            "时间模型未装配：引擎不内置行动耗时公式（形状与参数归内容侧）。"
            "内容侧应把 `time_model_fn` 挂进 saintess_engine.config"
            "（见 content/mech/time_model.py + content/apply.py::install_engine）"
        )
    return fn


def _base_fn():
    """内容侧「行动类别 → 基准耗时」表——未装配即抛 `EngineNotConfigured`（fail-closed）。"""
    fn = _cfg.get_hook("action_base_fn")
    if fn is None:
        raise _cfg.EngineNotConfigured(
            "行动基准耗时表未装配：引擎不内置动作基准数值。"
            "内容侧应把 `action_base_fn` 挂进 saintess_engine.config"
            "（见 content/mech/time_model.py + content/apply.py::install_engine）"
        )
    return fn


def _recover_fn():
    """内容侧第二段时间模型（收招）——未装配即抛 `EngineNotConfigured`（fail-closed）。

    ★ 「没有第二段」由内容侧**显式声明 0** 表达，不由引擎兜底（引擎不内置默认值）。
    """
    fn = _cfg.get_hook("recover_model_fn")
    if fn is None:
        raise _cfg.EngineNotConfigured(
            "第二段耗时模型未装配：引擎不内置耗时公式（形状与参数归内容侧）。"
            "内容侧应把 `recover_model_fn` 挂进 saintess_engine.config"
            "（见 content/mech/time_model.py + content/apply.py::install_engine）；"
            "「无第二段」= 内容侧显式声明 0"
        )
    return fn


def _recover_base_fn():
    """内容侧「行动类别 → 第二段基准耗时」表——未装配即抛 `EngineNotConfigured`。"""
    fn = _cfg.get_hook("recover_base_fn")
    if fn is None:
        raise _cfg.EngineNotConfigured(
            "第二段基准耗时表未装配：引擎不内置数值。"
            "内容侧应把 `recover_base_fn` 挂进 saintess_engine.config"
            "（见 content/mech/time_model.py + content/apply.py::install_engine）"
        )
    return fn


def action_time(spd: int, base: Optional[float] = None) -> float:
    """一次行动耗时（游戏秒）= 内容侧时间模型 `fn(spd, base)`。

    `base=None` → 取内容侧「默认行动类别」（`DEFAULT_ACTION`）的基准耗时。
    公式形状与参数（开方/线性/平推、基准速度、速度截断…）全部由内容侧装配。
    """
    if base is None:
        base = action_base_of(DEFAULT_ACTION)
    return float(_time_model_fn()(spd, base))


def initial_ct(spd: int, base: Optional[float] = None) -> float:
    """单位初始行动等待（战斗开始第一动也按速度排）。"""
    return action_time(spd, base)


def next_ct(battle, actor: dict, base: Optional[float] = None) -> float:
    """actor 行动后推进的 ct（绝对时刻）。"""
    # 用聚合面板速度（buffs 修正）——与 _after_act / 待发槽同一口径
    spd = _spd_of(battle, actor)
    return float(battle._now) + action_time(spd, base) + recover_time(spd, recover_base_of(DEFAULT_ACTION))


def action_base_of(action: str) -> float:
    """行动类别 → 基准耗时（内容侧基准表的查表转发）。

    引擎只认「动作类别」这个通用键；类别名集合与对应数值都在内容侧基准表里
    （未声明的类别 → 回落到 `DEFAULT_ACTION` 项；表里连它都没有 → KeyError 现形）。
    """
    return float(_base_fn()(action or DEFAULT_ACTION))


def recover_base_of(action: str) -> float:
    """行动类别 → **第二段**基准耗时（内容侧第二段基准表的查表转发）。

    与 `action_base_of` 同口径；「没有第二段」由内容侧显式声明 0.0 表达。
    """
    return float(_recover_base_fn()(action or DEFAULT_ACTION))


def recover_time(spd: int, base: Optional[float] = None) -> float:
    """一次行动的**第二段**耗时（游戏秒）= 内容侧第二段模型 `fn(spd, base)`。

    `base=None` → 取内容侧「默认行动类别」（`DEFAULT_ACTION`）的第二段基准。
    形状与参数（含「第二段不吃速度」这类独立形状）全部由内容侧装配。
    """
    if base is None:
        base = recover_base_of(DEFAULT_ACTION)
    return float(_recover_fn()(spd, base))

# ============================================================
# 在飞行动（前摇窗口）—— 待发行动的登记 / 查询 / 结算
# ============================================================
# 时序：T0 登记待发（`pending_begin`）→ T0+第一段 落地（`_resolve_due_pending`）
#      → T0+第一段+第二段 可再动（ct 公式照旧）。
# 引擎只做「登记 / 到点结算」，不认识技能/蓄力/读条任何一个游戏词。

def _spd_of(battle, actor: dict) -> int:
    """聚合面板速度（buffs 修正）；聚合不可用 → 裸 spd 字段。

    唯一口径：`next_ct` / `_after_act` / 待发槽三处共用（玩家面板由
    stats.actor_stats 从 class/equip 聚合，actor 裸 spd 可能是 0）。
    """
    try:
        from . import stats as S
        return int(S.actor_spd(battle, actor))
    except Exception:
        return int(actor.get("spd", 0) or 0)


def _segment_seconds(battle, actor: dict, decl) -> float:
    """一段耗时（游戏秒）——`decl` = str（行动类别，过内容侧形状）/ 数字（绝对秒）。"""
    if isinstance(decl, str) or decl is None:
        return action_time(_spd_of(battle, actor), action_base_of(decl or DEFAULT_ACTION))
    return max(0.0, float(decl))


def pending_of(actor) -> Optional[dict]:
    """在飞行槽（前摇窗口内的待发行动）；非 dict 一律 None（未登记 / 坏档）。"""
    s = actor.get("charging") if isinstance(actor, dict) else None
    return s if isinstance(s, dict) else None


def pending_left(actor, now: float) -> float:
    """待发行动剩余秒（展示用；无待发 = 0.0）。"""
    s = pending_of(actor)
    if not s:
        return 0.0
    return max(0.0, float(s.get("cast_done_at", 0.0) or 0.0) - float(now or 0.0))

def pending_begin(battle, ctx, cast=None, recover=None, pre_logs=None) -> dict:
    """登记待发行动（T0）：写槽 `actor["charging"]`，落地时刻 = 登记时刻 + 第一段耗时。

    cast / recover：两段耗时声明 —— str = 行动类别（过内容侧形状）· 数字 = 绝对秒 ·
      None = 第一段按 `ctx.action` 类别、第二段按内容侧基准表（形状与数值全在内容侧）。
    pre_logs：内容层自定义动作在 T0 的回执日志（B 段原样吐出 ⇒ 回调只调一次）。
    info：T0 登记时 `ActCtx` 身上的**动作配置**（技能 dict）—— 必须随槽带上，
      否则 B 段重建 `ActCtx` 时只能按 `actor._skill_index` 反查，调用方**内联传入**的
      配置被静默丢弃（登记的动作 ≠ 落地的动作）。
    槽内全字段 JSON 安全 ⇒ 待发随存档往返（serialize / 宿主回写面零改动）。
    """
    actor = ctx.caster
    slot = {
        "action": str(ctx.action or DEFAULT_ACTION),
        "skill": ctx.skill_name,
        "target_uid": (ctx.target or {}).get("uid"),
        "target_side": ctx.target_side,
        "scope": ctx.scope,
        "info": ctx.info,
        "cast_done_at": float(battle._now) + _segment_seconds(battle, actor, cast),
        "cast_base": cast,
        "recover_base": recover,
        "unstoppable": bool(getattr(ctx, "unstoppable", False)),
        "pre_logs": pre_logs,
    }
    actor["charging"] = slot
    return slot

def _next_pending_at(battle) -> Optional[float]:
    """全场最小的待发落地时刻（含已到点的；无待发 = None）。"""
    best = None
    for acts in battle.sides.values():
        for a in acts:
            s = pending_of(a)
            if not s or not actor_alive(a):
                continue
            t = float(s.get("cast_done_at", 0.0) or 0.0)
            if best is None or t < best:
                best = t
    return best


def _resolve_due_pending(battle, logs: list):
    """结算所有已到点的待发行动（升序 · 同刻按 sides 序稳定）。

    倒地者的待发直接作废（与死亡清理同口径：前摇中被打死 ⇒ 这一手不出伤）。
    清槽先于落地 —— 落地过程可能再登记 / 打断 / 死亡，不留二次结算路径。
    """
    due = []
    for si, acts in enumerate(battle.sides.values()):
        for ai, a in enumerate(acts):
            s = pending_of(a)
            if not s:
                continue
            if not actor_alive(a):
                a["charging"] = None
                continue
            t = float(s.get("cast_done_at", 0.0) or 0.0)
            if t <= float(battle._now) + 1e-9:
                due.append((t, si, ai, a))
    if not due:
        return
    due.sort(key=lambda x: (x[0], x[1], x[2]))
    for _t, _si, _ai, a in due:
        s = pending_of(a)
        if not s:
            continue
        a["charging"] = None
        battle._dispatch_pending(a, s, logs)

def settle_landing(battle, logs: list, actor=None) -> Optional[float]:
    """把**已登记**的待发行动推进到落地并结算（驱动方口径：一次出手 = 落地后返回）。

    与 `advance()` 的区别：`advance()` 会一路跑到**下一个决策点**（真人轮流制下那个决策点
    可能就在当刻 ⇒ 一步不推时钟 ⇒ 本次落地被挂起到对手那一回合）；本函数只推时钟到
    **待发落地时刻**并结算，**不驱动任何 actor 决策**。

    `actor=None` ⇒ 取全场最早的那个待发；给了 actor ⇒ 锚定**它**这一手落地（早于它的
    其它待发由 `_advance_time` 按时刻顺路结算，口径与 `advance()` 一致）。
    无待发 / 该 actor 无待发 ⇒ 返回 None（零行为）。返回结算后的战斗时刻。
    """
    if actor is not None:
        slot = pending_of(actor) if actor_alive(actor) else None
        at = float(slot.get("cast_done_at", 0.0) or 0.0) if slot else None
    else:
        at = _next_pending_at(battle)
    if at is None:
        return None
    dt = at - float(battle._now)
    if dt > 0:
        _advance_time(battle, dt, logs)
    else:
        _resolve_due_pending(battle, logs)
    return float(battle._now)


# ============================================================
# 推进（命令层驱动）
# ============================================================

def advance(battle, logs: list, max_steps: int = 200) -> tuple:
    """推进战斗：自动 actor 行动 + DOT/时效结算，直到遇到人控决策点或结束。

    返回 ("player", 决策 actor) | ("over", None)。
    语义（对齐旧引擎标准 CTB）：
    - 下一玩家行动点 vs 下一自动 actor 行动点：谁先到处理谁
    - 玩家到点 → 返回玩家决策（推进暂停，等真人输入）
    - 自动 actor 到点 → 行动 → 继续
    - 无存活人控（auto_run）→ 所有自动 actor 行动直到结束
    """
    guard = 0
    while battle.result is None and guard < max_steps:
        guard += 1
        # 已到点的待发行动先落地（同刻优先级；也覆盖「推进步长为 0」的时刻边界）
        _resolve_due_pending(battle, logs)
        if battle.result:
            return ("over", None)
        # 玩家决策点（所有 human_controlled 存活 actor 中 ct 最小者）
        fp = _next_player_due(battle)
        # 自动 actor 行动点（ct 最小）
        auto = _next_auto_due(battle)
        if fp is None and auto is None:
            return ("over", None)
        if fp is not None and (auto is None or fp[1] <= auto[1] + 1e-9):
            # 玩家先到点 → 推进到玩家时刻，返回玩家决策
            t = fp[1]
            if t > battle._now:
                _advance_time(battle, t - battle._now, logs)
            if battle.result:
                return ("over", None)
            return ("player", fp[0])
        # 自动 actor 先到点 → 推进并行动
        actor, t = auto
        if t > battle._now:
            _advance_time(battle, t - battle._now, logs)
        if battle.result:
            return ("over", None)
        if actor_alive(actor) and not actor.get("human_controlled"):
            logs.append(render_via(battle, "battle.schedule.actor_turn", "—— {name} 行动 ——",
                                name=actor.get('name', '敌人')))
            sub_logs, ended = battle.actor_auto(actor)
            logs.extend(sub_logs)
            if ended or battle.result:
                return ("over", None)
    return ("over", None)


def _next_player_due(battle):
    """ct 最小的存活人控 actor。返回 (actor, ct)。无则 None。"""
    best = None
    best_t = None
    for acts in battle.sides.values():
        for a in acts:
            if not actor_alive(a) or not a.get("human_controlled"):
                continue
            t = float(a.get("ct", 0) or 0)
            if best_t is None or t < best_t:
                best_t = t
                best = a
    return (best, best_t) if best else None


def _next_auto_due(battle):
    """ct 最小的存活自动 actor。返回 (actor, ct)。无则 None。"""
    best = None
    best_t = None
    for acts in battle.sides.values():
        for a in acts:
            if not actor_alive(a) or a.get("human_controlled"):
                continue
            t = float(a.get("ct", 0) or 0)
            if best_t is None or t < best_t:
                best_t = t
                best = a
    return (best, best_t) if best else None


def _after_act(battle, actor: dict, action: str, recover_base: Optional[float] = None):
    """行动后推进 actor.ct（第一段耗时 + 第二段耗时 + 固定推进）。

    `recover_base=None` → 第二段基准走内容侧基准表（`action` 那一项）；
    给了值 → 用它（由 `battle.action_override` 回执的第二段透传，单位与基准表一致）。
    """
    base = action_base_of(action)
    _rb = recover_base_of(action) if recover_base is None else float(recover_base)
    # 用聚合面板速度（buffs 修正）——actor 裸 spd 字段可能是 0（玩家面板由
    # stats.actor_stats 从 class/equip 聚合），与 next_ct / 待发槽同一口径。
    spd = _spd_of(battle, actor)
    actor["ct"] = float(battle._now) + action_time(spd, base) + recover_time(spd, _rb)


def _advance_time(battle, dt: float, logs: list):
    """推进全局时刻 dt（期间结算到期事件：DOT/时效 + 时钟事件广播）。

    N4：DOT/时效结算（state_effects dot 规则 + buff 到期）接入点。
    v181 资源条时间化：尾部广播 time_advance（通用「时钟推进」事件）——挂敌身条等
    按刻连续结算的内容层声明订阅此事件，读点永远拿到当刻值（不再「谁读谁记得结算」）。
    """
    if dt <= 0:
        return
    target = float(battle._now) + float(dt)
    guard = 0
    while True:
        guard += 1
        if guard > 64:
            # fail-closed：待发落地应逐段收敛；不收敛 = 状态机坏了，不静默兜底
            raise RuntimeError(
                "推进子片超限：待发行动结算未收敛（{} → {}）".format(battle._now, target))
        # 1) 先结算「已到点」的待发行动 —— 同刻优先级：待发落地先于该刻到点者行动
        _resolve_due_pending(battle, logs)
        nxt = _next_pending_at(battle)
        # 2) 推进到「下一个待发落地时刻」与「目标时刻」中较近的那个
        if nxt is None or nxt >= target - 1e-9:
            step = target - float(battle._now)
        else:
            step = nxt - float(battle._now)
        if step > 0:
            battle._now += step
            _settle_time_effects(battle, logs)
            continue  # 推进后重来一轮：先把落到这一时刻的待发结算掉
        break
    # 整段广播**一次**（内容侧「按刻连续结算」的监听节奏零变化：不按子片重复广播）
    try:
        from .effect_triggers import fire as _fire
        _fire(battle, "time_advance", {"dt": float(dt), "now": float(battle._now)}, logs)
    except Exception as _e:
        _diag(battle, "_advance_time · 时钟事件", _e)          # 审计 P-44：不再静默（行为不变）
        pass  # 时钟事件异常不阻断推进（容错铁律）


def _settle_time_effects(battle, logs: list):
    """时刻推进后的持续效果结算（V 系列统一：遍历 effects 容器）。

    N7.2 收口（对齐旧 _decay_buff_table/_advance_time 的到期语义）+ V 系列合并：
    - effects 到期：条目 expire <= now → 删（None=常驻/纯叠层；控制 on_act/
      一次性 on_hit 由消费点清除，这里只做时间兜底）
    - shields 到期：expire_at <= now → 删（None = 永久不删；独立容器）
    - 周期跳（统一方向分流，DOT/HOT 同构）：
      * 表声明 dot（EFFECT_RULES[key].dot，旧 damage 规则，静态每层数值）
      * 条目自带 period（effects[key]["period"]，动态声明——食物 HOT 的
        dir=heal/mana + value 数值随条目走，EFFECT_RULES 零名词）
      按 interval 绝对时刻循环补跳；turns 限跳清层（旧 dot.turns 语义）
    """
    from .state_effects import all_state_effects
    now = float(getattr(battle, "_now", 0.0) or 0.0)
    table = all_state_effects()
    for acts in battle.sides.values():
        for a in acts:
            if not actor_alive(a):
                continue
            ef = a.get("effects")
            # ---------- 1) effects 到期（buff/控制/免疫/一次性）----------
            if isinstance(ef, dict) and ef:
                for key in list(ef.keys()):
                    entry = ef[key]
                    if not isinstance(entry, dict):
                        continue
                    exp = entry.get("expire")
                    if exp is None:
                        continue  # 永久/无到期（纯叠层/资源）
                    if now >= float(exp):
                        ef.pop(key, None)
                        # N8 事件：效果到期钩子（原 buff_expire，保留事件名兼容）
                        try:
                            from .effect_triggers import fire as _fire
                            _fire(battle, "buff_expire", {"actor": a, "target": a,
                                                          "key": key}, logs)
                        except Exception as _e:
                            _diag(battle, "_settle_time_effects · 事件源", _e)          # 审计 P-44：不再静默（行为不变）
                            pass  # 事件源异常不阻断结算
            # ---------- 2) shields 到期（独立容器）----------
            sh = a.get("shields")
            if isinstance(sh, dict) and sh:
                for key in list(sh.keys()):
                    s = sh[key]
                    if not isinstance(s, dict):
                        continue
                    exp = s.get("expire_at")
                    if exp is None:
                        continue  # 永久盾
                    if now >= float(exp):
                        sh.pop(key, None)
            # ---------- 3) 周期跳（effects 条目：dot/period 声明）----------
            if isinstance(ef, dict) and ef:
                dnext = a.setdefault("dot_next", {})
                djump = a.setdefault("dot_jumps", {})
                for key, entry in list(ef.items()):
                    if not isinstance(entry, dict):
                        continue
                    # 到期条目本轮已删；这里只处理未到期的周期声明
                    exp = entry.get("expire")
                    if exp is not None and now >= float(exp):
                        continue
                    # 声明源：条目自带 period（动态）优先；回落表 period（V5 统一声明，
                    # 含 dir/interval/数值字段——表内已无旧 dot 字段）
                    period = entry.get("period")
                    if not isinstance(period, dict):
                        cfg = table.get(key) or {}
                        period = cfg.get("period")
                    if not isinstance(period, dict):
                        continue
                    n = int(entry.get("stacks", 0) or 0)
                    direction = str(period.get("dir", "damage") or "damage")
                    # v181.M-R2：dir=gain（资源自然回）不依赖现有层数——0 层也要回
                    # （游侠 energy 耗到 0 若被 n<=0 拦截将永远回不了，卡死）
                    if n <= 0 and direction != "gain":
                        continue
                    interval = float(period.get("interval", 1.0) or 1.0)
                    turns = int(period.get("turns", 0) or 0)
                    # 首次挂：登记下一跳（对齐旧 DOT/事件卡首跳延迟）
                    nx = dnext.get(key)
                    if nx is None:
                        dnext[key] = now + interval
                        continue
                    if now < float(nx):
                        continue  # 未到下一跳
                    guard = 0
                    while now >= float(dnext[key]) and guard < 20:
                        guard += 1
                        if direction == "damage":
                            pct = float(period.get("pct_max_hp", 0) or 0)
                            pct_cur = float(period.get("pct_cur_hp", 0) or 0)
                            # 条目级覆盖（旧引擎语义：数据显式写 entry["pct"] 时**替代**表的 hp 系数，
                            #   如「灼烧每刻 1.5%」类词条改写）——无条件生效，即使表里 pct=0
                            _dpct = entry.get("pct")
                            if _dpct is not None:
                                pct = float(_dpct)
                            # 目标身上带哪些标签才吃这档折扣：名单由该周期的声明给
                            #   （`period["trait_tags"]`），引擎不认标签叫什么（审计 E3）
                            _trait_like = traits.has_any(a, period.get("trait_tags") or ())
                            # ★ N-B13 DOT 混合公式系数（先读，供下方兜底分支判断）
                            _atk_c = float(period.get("atk", 0) or 0)
                            _matk_c = float(period.get("matk", 0) or 0)
                            if pct > 0:
                                # boss 档：条目级 `pct_boss`（精确值）优先；否则用数据给的
                                #   `boss_pct_mult`（折扣系数）——两者取一，**不叠乘**（防双重折扣）
                                if _trait_like and period.get("pct_boss"):
                                    pct = float(period["pct_boss"])
                                elif _trait_like and period.get("boss_pct_mult"):
                                    pct = pct * float(period["boss_pct_mult"])
                                # 单层上限：每层每刻 ≤ max_hp × pct_cap（防极端叠层爆炸）
                                _cap = float(period.get("pct_cap", 0) or 0)
                                if _cap > 0:
                                    pct = min(pct, _cap)
                                dmg = max(1, int(a.get("max_hp", 1) * pct * n))
                            elif pct_cur > 0:
                                if _boss_like and period.get("pct_cur_boss"):
                                    pct_cur = float(period["pct_cur_boss"])
                                dmg = max(1, int(a.get("hp", 0) * pct_cur * n))
                            else:
                                # 兜底：系数型 DOT（如毒=atk×0.8 flat，无 pct 段）基线为 0，
                                #   伤害完全来自系数段；纯百分比/无系数条目维持旧兜底 max(1, n)
                                dmg = 0 if (_atk_c or _matk_c) else max(1, n)
                            # ★ N-B13 DOT 混合公式（2026-09-11 接线，权威 = 游戏仓
                            #   `design/new_world/32_数值设计.md` §DOT_DEFS / 27 章 §七）：
                            #     每层每刻 = (atk×a + matk×m + max_hp×h×boss折扣) × 层数 × mult × (1−总抗)
                            #   引擎零知识：只读数据给的两个系数（period.atk / period.matk）
                            #   乘**施法者强度快照**（挂 DOT 时由 `note_dot_source` 记录在条目 `src`；
                            #   旧引擎语义「伤害跟挂毒的人，不跟当前谁在结算」）。
                            #   系数缺省 0 / 快照缺失 → 本段恒为 0 → 既有纯百分比 DOT 行为逐字不变。
                            if _atk_c or _matk_c:
                                _src = entry.get("src") or {}
                                _flat = (float(_src.get("atk", 0) or 0) * _atk_c
                                         + float(_src.get("matk", 0) or 0) * _matk_c)
                                if _flat > 0:
                                    dmg = max(1, dmg + int(_flat * n))
                            # ★ 低血翻倍（旧引擎「放血」：目标当前生命 < max_hp×阈值 → ×2）
                            #   数据给的 `double_low_hp_pct`（如流血 0.30 处决线）
                            _dl = float(period.get("double_low_hp_pct", 0) or 0)
                            if _dl > 0 and int(a.get("hp", 0) or 0) < int(a.get("max_hp", 1) or 1) * _dl:
                                dmg = max(1, dmg * 2)
                            # ★ 总抗（权威公式的 (1−总抗)）：总抗 = min(数据给的 resist_cap,
                            #   actor.dot_res + actor.adapt[key])。引擎零知识：两个都是承伤方
                            #   的数值字段；未声明 resist_cap → 本段跳过（行为不变）。
                            _rcap = period.get("resist_cap")
                            if _rcap is not None:
                                try:
                                    _res = float(a.get("dot_res", 0) or 0)
                                    _adapt = a.get("adapt") or {}
                                    if isinstance(_adapt, dict):
                                        _res += float(_adapt.get(key, 0) or 0)
                                    _res = min(float(_rcap), _res)
                                except Exception:
                                    _res = 0.0
                                if _res > 0:
                                    dmg = max(1, int(dmg * (1.0 - _res)))
                            if dmg <= 0:
                                # 无伤害来源（系数型 DOT 且无施法者快照）→ 本刻不落地、不出日志，
                                #   循环推进照常（dnext 在分支末尾自增，不能 continue 否则卡死）
                                dmg = 0
                            from .landing import deal_damage
                            # N9.14 dot_calc：DOT 伤害落地前乘区钩子（对齐 dmg_calc 模式）。
                            # broadcast（无 actor 主体键）——施毒者被动（万毒归宗等）在施放方
                            # 不在承伤者身上，subject 过滤会挡住；ctx.dot_key 供效果侧过滤。
                            try:
                                from .effect_triggers import fire as _fire
                                _dc = {"target": a, "dot_key": key, "dmg": dmg,
                                       "mult": 1.0}
                                _fire(battle, "dot_calc", _dc, logs)
                                # ⚠️ 不可写 `... or 1.0`（2026-09-18 修）：乘区值 **0.0 是合法值**，
                                #   而 `0.0 or 1.0` 会被吞成 1.0 → 0 乘区失效（完全免伤类无效）。
                                #   读**本次事件的 ctx 对象**（不依赖共享 `battle._fire_ctx`）——
                                #   与 actions/landing 三处读取点口径一致（四胞胎唯一漏改处）。
                                _raw_m = _dc.get("mult")
                                _m = 1.0 if _raw_m is None else float(_raw_m)
                                if _m != 1.0:
                                    dmg = max(1, int(dmg * _m))
                            except Exception as _e:
                                _diag(battle, "_settle_time_effects · 修正钩子", _e)          # 审计 P-44：不再静默（行为不变）
                                pass  # 修正钩子异常不阻断 DOT 落地
                            # N-B10 伤害类型透传（2026-09-11 接线）：period.dmg_type 原先是
                            #   死字段（声明了没人读）——真伤 DOT 与普通 DOT 落地完全同路。
                            #   透传给 landed 的 dmg_kind 后，`_apply_taken_reductions` 的
                            #   `"true" not in kd` 守卫使真伤**不减免**（物免/魔免/格挡全跳过），
                            #   与旧行为一致；非真伤 DOT 仍是空 kind（同样不减免）。
                            #   收益：类型免伤轴对 DOT 通道不再缺失，数据声明即语义。
                            if dmg > 0:
                                deal_damage(battle, None, a, dmg, logs,
                                            dmg_kind=str(period.get("dmg_type") or ""))
                                logs.append(render_via(battle, "battle.schedule.dot_tick", "🔥 {name} 受 {key} {n} 层影响，损失 {dmg} 生命",
                                                    name=a.get('name', '目标'),
                                                    key=key,
                                                    n=n,
                                                    dmg=dmg))
                            # N8 事件：DOT 每跳
                            try:
                                from .effect_triggers import fire as _fire
                                _fire(battle, "dot_tick", {"actor": a, "target": a,
                                                           "key": key, "dmg": dmg}, logs)
                            except Exception as _e:
                                _diag(battle, "_settle_time_effects", _e)          # 审计 P-44：不再静默（行为不变）
                                pass
                        elif direction == "heal":
                            from .landing import heal_actor as _heal_actor
                            _mx_hp = a.get("max_hp", a.get("hp", 1)) or 1
                            _hpct = float(period.get("heal_pct", entry.get("heal", 0)) or 0)
                            if _hpct > 0 and int(a.get("hp", 0) or 0) < _mx_hp:
                                _gain = max(1, int(_mx_hp * _hpct))
                                _real = _heal_actor(battle, a, _gain, logs)
                                if _real > 0:
                                    logs.append(render_via(battle, "battle.schedule.regen_hp", "🍲 {name} 持续恢复，恢复 {heal} 点生命！",
                                                        name=a.get('name', '目标'),
                                                        heal=_real))
                            # 持续恢复双资源：dir=heal 同时处理 mana_pct（食物 hot 回血回蓝同刻）
                            _mpct = float(period.get("mana_pct", entry.get("mana", 0)) or 0)
                            if _mpct > 0:
                                _mx_mp = a.get("max_mp", a.get("mp", 1)) or 1
                                if int(a.get("mp", 0) or 0) < _mx_mp:
                                    _gain = max(1, int(_mx_mp * _mpct))
                                    _before = int(a.get("mp", 0) or 0)
                                    a["mp"] = min(_mx_mp, _before + _gain)
                                    _real = int(a["mp"]) - _before
                                    if _real > 0:
                                        logs.append(render_via(battle, "battle.schedule.regen_mp", "🍲 {name} 持续恢复，恢复 {heal} 点魔力！",
                                                            name=a.get('name', '目标'),
                                                            heal=_real))
                        elif direction == "mana":
                            _mx_mp = a.get("max_mp", a.get("mp", 1)) or 1
                            _mpct = float(period.get("mana_pct", entry.get("mana", 0)) or 0)
                            if _mpct > 0 and int(a.get("mp", 0) or 0) < _mx_mp:
                                _gain = max(1, int(_mx_mp * _mpct))
                                _before = int(a.get("mp", 0) or 0)
                                a["mp"] = min(_mx_mp, _before + _gain)
                                _real = int(a["mp"]) - _before
                                if _real > 0:
                                    logs.append(render_via(battle, "battle.schedule.regen_mp", "🍲 {name} 持续恢复，恢复 {heal} 点魔力！",
                                                        name=a.get('name', '目标'),
                                                        heal=_real))
                        elif direction == "gain":
                            # v181.M-R2e：资源自然回/衰减（声明级，引擎零职业知识）——
                            # 给自身 effects[key] 加/减层 clamp [0, cap]（游侠 energy 每刻
                            # +18 专注流量制；内容侧「每刻 -0.7 慢衰减」的资源 = B3 float 通用层，
                            # amount 负值也走，clamp 下限 0 不归负）。cap 取 period.cap 或
                            # _stack_cap_of（方案 A 收敛：EFFECT_RULES 基础 + actor.bonus.cap
                            # 动态——v181.M-bonus 分域，旧 actor cap_bonus 键已全清）。
                            # 静默（资源跳不刷战斗日志）；写回经 _norm_stack 归一（int 资源
                            # 保持 int 观感，float 保留 6 位精度——10-0.7 → 9.3）。
                            _amt = float(period.get("amount", 0) or 0)
                            _cap = int(period.get("cap", 0) or 0)
                            if _cap <= 0:
                                _cap = _stack_cap_of(a, key)
                            if _amt != 0:
                                _cur = float(entry.get("stacks", 0) or 0)
                                _new = round(_cur + _amt, 6)
                                _new = max(0.0, min(float(_cap), _new))
                                if abs(_new - _cur) > 1e-9:
                                    from .effects import _norm_stack as _ns
                                    entry["stacks"] = _ns(_new)
                        # 限时周期：跳够 turns 次 → 清层（到期自然消失）
                        if turns > 0:
                            c = int(djump.get(key, 0) or 0) + 1
                            djump[key] = c
                            if c >= turns:
                                ef.pop(key, None)
                                dnext.pop(key, None)
                                djump.pop(key, None)
                                break
                        dnext[key] = float(dnext[key]) + interval
                    if not actor_alive(a):
                        break
