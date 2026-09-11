# -*- coding: utf-8 -*-
"""《我的游戏》——本游戏的机制动作（`@register_action`）。

引擎只给「能做什么」（8 个内置动词 + `register_action` 任意扩展），
这里示范**内容侧自己写动词**的最小形态。

四条铁律（见框架 wiki `guides/write-a-mechanic.md`）：

  1. **落地一定走 landing** —— 伤害 `deal_damage` / 治疗 `heal_actor`，
     不要自己扣 `hp`（否则绕过护盾/免伤/死亡结算与事件广播）。
  2. **缺字段 = 无此行为（零默认值）** —— `params.get(...)` 判空就 `return`，
     不写兜底默认值，否则「配置忘了填」会静默变成一个错误的行为。
  3. **不抛异常** —— 引擎会吞掉异常并跳过本动作，静默失败最难排查。
  4. **日志就是** `logs.append(...)`。

只用引擎公开 API：`register_action` / `deal_damage` / `actor_stats` 等，
全部在 `saintess_engine.__all__` 里（引擎不 import 内容，方向单向）。
"""
from __future__ import annotations

from saintess_engine import actor_stats, deal_damage, register_action


def _stacks(actor, key) -> int:
    """读某个效果条目的层数（不存在 = 0）。"""
    entry = (actor.get("effects") or {}).get(key) if actor else None
    return int(entry.get("stacks", 0) or 0) if isinstance(entry, dict) else 0


@register_action("demo_echo")
def demo_echo(battle, caster, target, params, logs):
    """示例动作：受击后按概率反击（`chance` 触发概率，`pct` 反击伤害比例）。

    演示三种参数形态（编辑器会从本函数体反推出参数清单）：
      - `chance`：可选，有默认值 `0.25` → 数值型
      - `pct`：可选，有默认值 `0.5` → 数值型
      - `tag`：可选，无默认值 → 字符串型
    落地走 `deal_damage`（不是自己扣血），保证护盾/免伤/事件都正常。
    """
    if not target:
        return
    chance = float(params.get("chance", 0.25) or 0)
    if chance <= 0:
        return                                  # 缺字段/非法 = 无此行为
    import random
    if random.random() >= chance:
        return
    pct = float(params.get("pct", 0.5) or 0)
    if pct <= 0:
        return
    atk = float((actor_stats(battle, caster) or {}).get("atk", 0) or 0)
    dmg = max(1, int(atk * pct))
    deal_damage(battle, caster, target, dmg, logs, dmg_kind="phys")
    tag = params.get("tag") or ""
    logs.append(f"⚡ 回响反击{'·' + tag if tag else ''}：{dmg} 点伤害！")


@register_action("demo_mark")
def demo_mark(battle, caster, target, params, logs):
    """示例动作：给目标挂标记（`mark_key` 标记名必填，`stacks` 层数默认 1）。

    演示「必填参数」形态：`params["mark_key"]` 直接下标 → 编辑器按必填提示。
    """
    if not target:
        return
    mark_key = params["mark_key"]                # 直接下标 = 必填
    stacks = int(params.get("stacks", 1) or 1)
    if stacks <= 0:
        return
    holder = target.setdefault("effects", {})
    entry = holder.setdefault(mark_key, {"stacks": 0})
    if not isinstance(entry, dict):
        return
    entry["stacks"] = int(entry.get("stacks", 0) or 0) + stacks
    logs.append(f"🔖 标记 {mark_key} ×{stacks}（当前 {entry['stacks']} 层）")
