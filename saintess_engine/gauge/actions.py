# -*- coding: utf-8 -*-
"""通用件 - gauge/actions（敌身条族通用动词：积蓄 / 时钟结算 / 阶段保留 / 受击反推）。

把「挂敌身资源条」这件事在**事件时机上的消费端**收敛到引擎 —— 机制本体在
`gauge/__init__.py`（`bar_def` / `bar_state` / `bar_gain` / `bar_settle` /
`bar_should_trigger` / `bar_trigger` / `bar_preserve` / `bar_effect_key`），
本模块只做「引擎事件时机 → 机制 API」的转发，**零游戏知识**：

  bar_gain             skill_hit    命中注入积蓄（amount 显式 / 读事件字段 / per_hit 多段）
  bar_time_settle      time_advance 宿主自身所有条结算到当刻 + 触发检查
  bar_phase_preserve   phase        阶段转换保留配置比例积蓄（进度遗产；阶段不清零）
  passive_reflect_bar  on_taken     受击反制：反弹配置比例伤害 + 反推攻击者条

注册：模块顶层 `@register_action(...)`，**import 即注册**（`gauge/__init__.py` 末尾
`from . import actions` 触发）⇒ `import saintess_engine` 即完成注册，内容侧无需再注册一次。
注册名是引擎契约的一部分（内容侧 `triggers` / `EFFECT_ACTIONS` 按名引用），**不得改名**。

数据驱动铁律（同 `gauge/__init__.py`）：
- 引擎不写任何职业/条名/数值特判：阈值 / 衰减 / 保留比例 / 触发效果全从 `bar_def(key)` 读
  （内容侧经 `config.mech_cfg("enemy_bar")` 注入；未装配 = 默认不启用）
- 日志里的条显示名 = `bar_def(key)["name"]`（内容侧提供；缺省回落 bar key）——
  引擎不认识任何具体条名
- 条键前缀经 `_state_prefix()`（内容侧 `config.bar_prefix()` 注入；未装配回落 `"bar:"`）

搬运来源（P4-D2 逐字端口，本批 U1-I1 整块上移引擎）：包内
`games/orlandia/content/mech/bar_procs.py` 的 5 个模块级助手 + 4 个 `@register_action`
（函数体、数值、日志文案、注释逐字保留；只改 import 的相对层级 + 1 处日志条显示名转发）。
包侧只剩装配器 `apply_bar_procs`（它读本游戏的表，属内容侧）。
"""
from __future__ import annotations

from ..battle.effects import register_action


def _now_of(battle) -> float:
    return float(getattr(battle, "_now", 0.0) or 0.0)


def _host_of(caster, target, params) -> dict | None:
    """条宿主：命中目标优先（skill_hit）；无 target 取声明者（时钟事件自结算）。"""
    if isinstance(target, dict):
        return target
    own = params.get("_owner")
    if isinstance(own, dict):
        return own
    return caster if isinstance(caster, dict) else None


def _bar_keys_of(host: dict) -> list:
    """宿主身上所有条键（effects 里带前缀的条目 → 去前缀 bar key）。"""
    from . import _state_prefix
    pfx = _state_prefix()
    out = []
    for k, v in (host.get("effects") or {}).items():
        if isinstance(k, str) and k.startswith(pfx) and isinstance(v, dict):
            out.append(k[len(pfx):])
    return out


def _ensure_tick(host: dict) -> None:
    """自安装订阅（首次挂条时；重复调用幂等）：

    - `time_advance` → `bar_time_settle`：时钟推进按 dt 结息（谁挂过条谁才订阅，零噪音）
    - `phase`        → `bar_phase_preserve`：阶段转换保留部分积蓄（进度遗产，配置定比例）
    """
    trig = host.setdefault("triggers", {})
    lst = trig.setdefault("time_advance", [])
    if not any(isinstance(e, dict) and e.get("action") == "bar_time_settle" for e in lst):
        lst.append({"action": "bar_time_settle"})
    lph = trig.setdefault("phase", [])
    if not any(isinstance(e, dict) and e.get("action") == "bar_phase_preserve" for e in lph):
        lph.append({"action": "bar_phase_preserve"})


def _settle(battle, host: dict, key: str, logs: list) -> bool:
    """阈值检查 → 触发 → 落地 trigger_effect。返回是否触发。"""
    from . import bar_def, bar_should_trigger, bar_trigger
    now = _now_of(battle)
    if not host or not key or not bar_should_trigger(host, key, now):
        return False
    if not bar_trigger(host, key, logs, now):
        return False
    bd = bar_def(key) or {}
    if (bd.get("trigger_effect") or "") == "skip_turn":
        # 控制跳过：effects 容器 mode=skip（saintess_engine 统一控制消费点消费后自清）；
        # expire=None = 无墙钟到期 → 由「下一动」消费
        host.setdefault("effects", {})[f"bar_skip:{key}"] = {
            "mode": "skip", "expire": None}
        logs.append(f"💢 【{host.get('name', '目标')}】被{bd.get('name', key)}震慑，无法行动！")
    return True


@register_action("bar_gain")
def bar_gain_act(battle, caster, target, params, logs):
    """命中注入积蓄。

    amount 显式给则用；否则读事件技能字段 `params["field"]`（如 shaken_gain）——
    无字段/非正数 = 无此行为（静默跳过）。
    """
    key = params.get("key")
    if not key:
        return
    host = _host_of(caster, target, params)
    if not host:
        return
    amount = params.get("amount")
    if amount is None:
        field = params.get("field")
        if not field:
            return
        info = (getattr(battle, "_fire_ctx", None) or {}).get("info") or {}
        amount = info.get(field)
        # per_hit：字段值 = 每段量（v153 §六「多段 +3~+5/段」）→ 按本次施放段数合并
        # （skill_hit 每次施放只 fire 一次，段循环在 fire 之前——等价旧引擎逐段 settle）
        if params.get("per_hit"):
            try:
                amount = int(amount or 0) * int(info.get("hits") or info.get("multi") or 1)
            except Exception:
                pass
    try:
        amount = int(amount or 0)
    except Exception:
        return
    if amount <= 0:
        return
    from . import bar_gain
    bar_gain(host, key, amount, logs, now=_now_of(battle))
    _ensure_tick(host)
    _settle(battle, host, key, logs)


@register_action("bar_time_settle")
def bar_time_settle_act(battle, caster, target, params, logs):
    """time_advance：宿主自身所有条结算到当刻（免疫到期 + 连续衰减）+ 触发检查。"""
    host = params.get("_owner") or _host_of(caster, target, params)
    if not isinstance(host, dict):
        return
    from . import bar_settle
    now = _now_of(battle)
    for key in _bar_keys_of(host):
        bar_settle(host, key, now, logs)
        _settle(battle, host, key, logs)


@register_action("bar_phase_preserve")
def bar_phase_preserve_act(battle, caster, target, params, logs):
    """phase：宿主阶段转换 → 所有条保留配置比例积蓄（进度遗产；阶段不清零）。

    比例 = `ENEMY_BAR_CFG[key].phase_preserve_pct`（缺省 50%）——动作零数值，
    只是「阶段转换」这个通用时机的条侧消费端（事件由上层剧本导演广播）。
    """
    host = params.get("_owner") or _host_of(caster, target, params)
    if not isinstance(host, dict):
        return
    from . import bar_def, bar_preserve, bar_state
    for key in _bar_keys_of(host):
        before = float((bar_state(host, key) or {}).get("val", 0.0) or 0.0)
        if before <= 0:
            continue
        bar_preserve(host, key)
        after = float((bar_state(host, key) or {}).get("val", 0.0) or 0.0)
        bd = bar_def(key) or {}
        pct = int(round(float(bd.get("phase_preserve_pct", 0.5) or 0.5) * 100))
        logs.append(f"💢【{host.get('name', '目标')}】阶段更迭："
                    f"{bd.get('name', key)}积蓄保留 {pct}%（{int(before)} → {int(after)}）")


@register_action("passive_reflect_bar")
def passive_reflect_bar_act(battle, caster, target, params, logs):
    """on_taken：受击反制（反震）——反弹 `reflect_pct` 伤害 + 反推攻击者条。

    - 反制者 = `params["_owner"]`（被动持有者 = 受击者；on_taken 主体过滤已保证）
    - 攻击者 = `_fire_ctx["source"]`；反弹基数 = `_fire_ctx["dmg"]`；
      无来源（DOT/环境伤）不反制（对齐 we_reflect 口径）
    - 反推条 = `params["key"]/["gain"]`（装配器按被动 `bar_field` 解析的技能字段量）
      → bar_gain + 触发检查（与命中注入同一条消费链）
    """
    from ..battle.actors import actor_alive
    from . import bar_gain
    deflector = params.get("_owner") or target
    if not isinstance(deflector, dict) or not actor_alive(deflector):
        return
    ctx = getattr(battle, "_fire_ctx", None) or {}
    attacker = ctx.get("source")
    if not isinstance(attacker, dict) or not actor_alive(attacker):
        return
    pct = float(params.get("reflect_pct", 0) or 0)
    if pct > 0:
        rd = max(1, int(int(ctx.get("dmg", 0) or 0) * pct))
        from ..battle.landing import deal_damage
        deal_damage(battle, deflector, attacker, rd, logs)
        logs.append(f"🪨 反震：反弹 {rd} 点伤害！")
    key = params.get("key")
    gain = int(params.get("gain", 0) or 0)
    if key and gain > 0:
        now = _now_of(battle)
        bar_gain(attacker, key, gain, logs, now=now)
        _ensure_tick(attacker)
        _settle(battle, attacker, key, logs)
