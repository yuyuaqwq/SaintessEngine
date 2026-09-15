# -*- coding: utf-8 -*-
"""《奥兰迪亚》世界 Boss 承伤乘区 + GM 增伤装配 —— worldboss（唯一实现；B10-L4 收口）。

真源：游戏仓 `C:/Users/yuyu/qqbot/data/plugins/dragonfall/game/services/battle_worldboss_procs.py`
（**B10-L4 起该宿主文件 = 委托薄壳**：实现只有本文件这一份，宿主那份从本模块再导出）。

本文件两件都在（一个动作 + 一个装配入口）：
  1. `wb_gm_dmg_mult`（`@register_action`）—— `taken_calc` 承伤乘区 ×factor
     （真源 `:32-48`，P4-D2 逐字搬入：函数体/数值/注释一字未改）
  2. `apply_gm_dmg_mult(actor, mult)` —— 把声明挂到 `actor.triggers["taken_calc"]`
     （真源 `:51-75`，**B10-L4 逐字搬入**：正文逐行相同，证据见 `overnight/B10-L4-cond-food-wb-bridge.md`）

为什么现在搬 `apply_gm_dmg_mult`（P4-D2 当时判「归属待定：内容 or 宿主 GM 层」）：
它是**纯 actor dict 装配**（零宿主耦合：不读 DB / 平台 / 墙上时间），且生产消费者
`commands/combat.py:2392`（`WBP.apply_gm_dmg_mult(actor, mult)`）要的就是它。留在宿主 =
动作与装配分居两地（双源）；搬进包内后宿主那份只剩薄壳，装配面/引擎面同源。
B10-L4 判定依据：宿主 75 行 = 动作 22 行（已搬）+ 装配 25 行（本次搬）+ 文件头 26 行，
无第三处独有语义。
"""

from __future__ import annotations

from saintess_engine.battle.effects import register_action


@register_action("wb_gm_dmg_mult")
def wb_gm_dmg_mult(battle, caster, target, params, logs):
    """taken_calc 承伤乘区 ×factor（worldboss GM 伤害倍率）。

    引擎零知识：只读 params 的数字，不认「世界 Boss」这个概念。
    factor 缺省/无效/等于 1.0 → 无此行为（不写 ctx.mult）。
    """
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    try:
        f = float(params.get("factor", 1.0) or 1.0)
    except (TypeError, ValueError):
        return
    if f == 1.0:
        return
    ctx["mult"] = float(ctx.get("mult", 1.0) or 1.0) * f


def apply_gm_dmg_mult(actor: dict, mult: float) -> bool:
    """把 GM 世界 Boss 伤害倍率挂到 actor 的 taken_calc 乘区。

    幂等（同 actor 重复调用只保留一条声明，值就地更新）；mult 无效或 =1.0 → 不挂并
    返回 False。返回是否挂上。
    """
    if not isinstance(actor, dict):
        return False
    try:
        m = float(mult or 1.0)
    except (TypeError, ValueError):
        return False
    trig = actor.setdefault("triggers", {})
    lst = trig.setdefault("taken_calc", [])
    for e in lst:
        if isinstance(e, dict) and e.get("action") == "wb_gm_dmg_mult":
            if m == 1.0:
                lst.remove(e)          # 倍率被 GM 改回 1 → 撤掉声明
                return False
            e["factor"] = m
            return True
    if m == 1.0:
        return False
    lst.append({"action": "wb_gm_dmg_mult", "factor": m})
    return True


__all__ = ["wb_gm_dmg_mult", "apply_gm_dmg_mult"]
