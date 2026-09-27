# -*- coding: utf-8 -*-
"""效果规则查询（薄封装）——数据来自本包 `battle/game_config.py` 挂载的游戏规则。

V 系列统一：规则表 = EFFECT_RULES（cap/panel/stat_scale/period/consume/cleanse 全声明）。
引擎不内置规则表；游戏层经 `game_config` 的 `load_game_rules()` 注入。
这里只保留查询接口（cap/折算），表内容在游戏层。
"""
from __future__ import annotations

from .game_config import get_effect_rules


def state_def(key: str) -> dict:
    """查效果规则（无规则 = 空 dict = 纯数值）。

    ★ 2026-09-28（标签机制）：**层级继承** —— 精确声明优先；没有就逐级往父级找
    （`control.stun` 没单独声明 ⇒ 用 `control` 的声明）。这就是 GAS 那边「前缀带行为」的
    落法：一族 tag 的共同行为在父级声明一次，子级只写差异。全都没有 ⇒ `{}`（零兜底）。
    """
    from . import tags as _tags
    return _tags.rule_of(key, table=get_effect_rules())[0]


def stat_scale_of(key: str, value: int, stat: str) -> float:
    """折算：effect key 每 value 点对 stat 的加成系数（1 + n×系数）。"""
    cfg = state_def(key)
    scale = (cfg.get("stat_scale") or {}).get(stat)
    if not scale:
        return 1.0
    return 1.0 + int(value or 0) * float(scale)


def all_state_effects() -> dict:
    """当前挂载的全部效果规则表（引擎遍历/审计用）。"""
    return get_effect_rules()


# ============================================================
# 状态容器收口第 2 批（2026-09-28）：两个**薄查询**（声明驱动的读点）
#
# 为什么是「声明」而不是「键名」：引擎零游戏名词 —— 它不认识「护盾」「减伤」这些名字，
# 只问内容侧在 `EFFECT_RULES[key]` 里**声明了什么**。于是
#   · `absorb`      —— 「我这条带 value 的条目要吸收伤害」这一族的共同声明
#   · `taken_pct`   —— 「我这条带 value 的条目是承伤减免比例」这一族的共同声明
# 落在**父级 tag** 上就是一族（`shield.*` / `buff.ward` 都自动继承），这就是本模块
# 走 `state_def`（= `tags.rule_of`，含层级继承）而不是 `all_state_effects().get(key)`
# 的原因：查父级即可拿到子级的声明。

def _keys_where(actor: dict, decl: str) -> list:
    """容器里**声明了 `decl`** 的条目 key（按容器顺序）—— 唯一的判定口径。

    `decl` 的值不参与判定：声明写了就是这一族（真值语义与 `cleanse` / `wake_on_hit`
    等既有声明键一致）。空容器 / 读不到声明表 ⇒ 空名单（**不声明 = 任何人不适用**）。
    """
    ef = (actor or {}).get("effects")
    if not isinstance(ef, dict) or not ef:
        return []
    out = []
    for key, entry in ef.items():
        if not isinstance(entry, dict):
            continue
        if (state_def(key) or {}).get(decl):
            out.append(key)
    return out


def absorb_keys(actor: dict) -> list:
    """身上**声明了 `absorb`** 的容器条目 key —— 承伤落地时逐条扣 `entry["value"]`。

    护盾不再是独立容器，而是这一族里的一员（收口第 2 批）：内容侧想加第二种吸收资源
    （元素吸收 / 反伤护罩）只要再写一条带 `absorb` 的声明，引擎这里**不用动**。
    """
    return _keys_where(actor, "absorb")


def taken_pct_keys(actor: dict) -> list:
    """身上**声明了 `taken_pct`** 的容器条目 key —— `deal_damage` 承伤减免读点用。

    累加各条的 `value`（比例），封顶读内容侧骨架表 `formulas.reduce_cap()`
    （未装配 = 0.0 ⇒ 封到 0 = 不减伤 ⇒ 这一段对未声明上线的包**零行为变化**）。
    """
    return _keys_where(actor, "taken_pct")
