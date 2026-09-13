# -*- coding: utf-8 -*-
"""《奥兰迪亚》世界 Boss 承伤乘区 —— worldboss（P4-D2 搬运物，逐字保真）。

真源：游戏仓 `C:/Users/yuyu/qqbot/data/plugins/dragonfall/game/services/battle_worldboss_procs.py`
      **`:27-48`**（1 个 `@register_action` 动作；真源共 75 行）。
本文件 = 真源 `:27-48` 的**逐字拷贝**：函数体、数值、注释一字未改（本动作无 `logs.append`；
对拍见 `overnight/d2_misc_verify.py` A4：逐行 diff 为空）。

动作清单（1 个）
  :32    `wb_gm_dmg_mult`  (def wb_gm_dmg_mult → 本文件 def :27)
         语义 = GM `gm_伤害 <倍率>` 的 worldboss 承伤乘区（`taken_calc` ×factor；
         factor 缺省/无效/==1.0 → 零行为）。归属见 P4 设计稿 §四-3（动作已在内容侧 mech/，
         `apply_gm_dmg_mult` 的落点由主 agent 拍板）。

结构改写清单（只有 1 类，零行为变化）
1. **去装配入口**：删真源 `:51-75 apply_gm_dmg_mult(actor, mult)`（把声明挂到
   `actor.triggers["taken_calc"]`；属装配/宿主 GM 层，P4 设计稿 §三 D2 表注明
   「worldboss(1，归属待定：内容 or 宿主 GM 层)」）。
   import 头（`:27-29` register_action）一字未动；本文件**无**游戏仓相对 import。
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


__all__ = ["wb_gm_dmg_mult"]
