# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— 原石系统核心逻辑（B13-L1 端口，2026-09-14）。

真源：游戏仓 `game/core/gems.py`（163 行）**逐字端口**。宿主同名文件已改薄壳。

取件（★ B16-W11 收口 · 2026-09-14：宿主 `game/data` 的十张 `GEM_*` 表**全数归包**，本模块零宿主数据句柄）
1. `GEM_TIERS` / `GEM_TIER_NAMES` / `GEM_SOCKETS` / `GEM_LEGENDARY_EFFECTS`
   → 包内门面 `content/catalog_b143.py`（`gems` 域；int 键 + 阶位数值序已还原），逐名 deep-equal（门禁 0 不等）。
2. `GEM_STATS` / `GEM_ITEM_TYPE` / `GEM_REMOVE_COST` / `GEM_DROP_RATE` / `GEM_DROP_TIER` /
   `GEM_BOSS_FIXED` → 包内门面 `content/catalog_rules.py`（包内**无域** ⇒ 值随代码走：
   由 `overnight/w11_dump_gap_names.py` 从宿主真源 dump、非手抄；已登记 `NOT_YET_DOMAINED`，
   建域后改读 `content/data/gems.json`）。
3. `from ..content_rules.panel import STAT_NAMES` → **包内直取** `from .panel import STAT_NAMES`
   （包内 `content/panel.py` 有同名属性，逐值对拍相等）。

正文一字未改：只换「取值来源」（原 `_D.<名>` → 同名门面名）；随机消耗次序 / 分支 / 文案全同。
"""


# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年核心层 - gems.py（v136 原石系统核心逻辑）

原石=怪猎护石式随机属性+伊甸属性绑定：
- roll_gem：随机 1-2 属性 × 随机层数（属性值 = 层数 mult），Boss 可固定属性倾向
- gem_combine：3 同级（同 tier）→ 1 个 tier+1，无失败（调用方负责游戏内校验）
- gem_socket_cost：原石拆卸费 = 500 × max(stats 层数)
- sockets_capacity：孔位表查询（GEM_SOCKETS[quality]）
"""
import random

# ---- 包内门面（B16-W11：十张 `GEM_*` 表全数归包）----
from .catalog_b143 import (GEM_TIERS, GEM_TIER_NAMES, GEM_SOCKETS,
                           GEM_LEGENDARY_EFFECTS)
from .catalog_rules import (GEM_STATS, GEM_ITEM_TYPE, GEM_REMOVE_COST,
                            GEM_DROP_RATE, GEM_DROP_TIER, GEM_BOSS_FIXED)


def _tier_label(tier: int) -> str:
    """阶 → 展示名（如 1 → 碎裂的幸运宝石、10 → 神话的幸运宝石）"""
    return GEM_TIER_NAMES.get(tier, f"阶{tier}")


def _stat_label(stat: str) -> str:
    """属性 ID → 中文名（沿用 engine.STAT_NAMES 语义，延迟 import 防环）"""
    from .panel import STAT_NAMES          # B13-L1：包内直取（逐值相等）
    return STAT_NAMES.get(stat, stat)


def roll_gem(min_tier: int = 1, max_tier: int = 10, boss_fixed: dict | None = None) -> dict:
    """护石式随机原石。

    - 随机 1-2 个属性（从 GEM_STATS 抽），每属性独立随机层数（min_tier..max_tier）
    - stats 值 = 层数 mult（百分比属性为小数，数值属性也是小数比率——引擎直接加）
    - boss_fixed 非 None：固定该属性（如 {"stat": "pene_phys"} → 破甲倾向），
      另一个属性随机（若随机到同属性则改抽一个不同属性）
    - 传说级（tier>=9）带 legend_effect 随机抽 1 个
    """
    lo = max(1, min(min_tier, max_tier))
    hi = max(lo, max_tier)
    n_stats = random.randint(1, 2)
    fixed = None
    if boss_fixed:
        fixed = boss_fixed.get("stat")
        if fixed not in GEM_STATS:
            fixed = None
    pool = list(GEM_STATS)
    if fixed:
        pool.remove(fixed)
    chosen = [fixed] if fixed else []
    while len(chosen) < n_stats:
        if not pool:
            break
        s = random.choice(pool)
        chosen.append(s)
        pool.remove(s)  # 同一颗原石不重复属性
    # 每属性独立随机层数（同属性只存在一次，直接取第一颗的层数）
    stats = {}
    for s in chosen:
        stats[s] = GEM_TIERS[random.randint(lo, hi)]["mult"]
    tier = max(stats.values()) if stats else lo
    # 层数取最高属性对应层（tier 仅用于展示/合成/拆卸分级）
    tier = max(k for k, info in GEM_TIERS.items() if info["mult"] == tier) if stats else lo
    gem = {
        "name": "",
        "type": GEM_ITEM_TYPE,
        "gem": True,
        "stats": stats,
        "tier": tier,
        "icon": "💎",
    }
    if tier >= 9:
        gem["legend_effect"] = random.choice(GEM_LEGENDARY_EFFECTS)
    label = "·".join(f"{_stat_label(s)}+{int(stats[s] * 100)}%" for s in stats)
    gem["name"] = f"{_tier_label(tier)}·{label}"
    return gem


def roll_gem_drop(monster: dict, boss_fixed: dict | None = None) -> dict | None:
    """v136 原石随机掉落：胜利结算消费端调用（野外/副本掉落逻辑统一挂这里）。

    - 按怪物类型查 GEM_DROP_RATE 掉率（normal/elite/field_boss/instance_boss），
      命中返回 1 颗随机原石（roll_gem），未命中返回 None
    - 层数范围查 GEM_DROP_TIER；Boss 专属固定属性倾向：boss_fixed（怪物名 → 属性）优先，
      否则查 GEM_BOSS_FIXED[怪物名]（如 野猪王·裂鬃 → pene_phys 破甲倾向）
    - 怪物类型判定：is_boss + map_area == "instance" → instance_boss（副本 Boss），
      is_boss → field_boss（野外 Boss），is_elite → elite，其余 normal
    - 掉落只吃 1 次 random.random()（命中判定）——测试确定性铁律：不新增多余随机数消耗，
      不破坏存量战斗回归的随机序列；命中后才由 roll_gem 消费随机数
    """
    if not monster:
        return None
    is_boss = bool(monster.get("is_boss"))
    is_elite = bool(monster.get("is_elite"))
    if is_boss:
        if monster.get("map_area") == "instance" or (monster.get("map") or "").find("副本") >= 0:
            key = "instance_boss"
        else:
            key = "field_boss"
    elif is_elite:
        key = "elite"
    else:
        key = "normal"
    rate = GEM_DROP_RATE.get(key, GEM_DROP_RATE["normal"])
    if random.random() >= rate:
        return None
    lo, hi = GEM_DROP_TIER.get(key, GEM_DROP_TIER["normal"])
    fixed = None
    if boss_fixed:
        fixed = boss_fixed.get("stat")
        if fixed not in GEM_STATS:
            fixed = None
    if not fixed:
        fixed = GEM_BOSS_FIXED.get(monster.get("name") or "")
    if fixed and fixed not in GEM_STATS:
        fixed = None
    return roll_gem(lo, hi, {"stat": fixed} if fixed else None)


def gem_combine(gems: list) -> dict:
    """3 个同级（同 tier）→ 1 个 tier+1，无失败（游戏内校验后调）。

    继承 3 颗中最优属性（同属性取最高值），合成后层数 = 原 tier+1。
    """
    if not gems:
        raise ValueError("gem_combine 需要至少 1 颗原石")
    base_tier = gems[0]["tier"]
    if any(g.get("tier") != base_tier for g in gems):
        raise ValueError("gem_combine 要求 3 颗同级原石")
    new_tier = min(base_tier + 1, 10)
    stats = {}
    for g in gems:
        for k, v in (g.get("stats") or {}).items():
            if k not in stats or v > stats[k]:
                stats[k] = v
    # 合成继承后属性层数也可能比合成层低——用合成层 mult 重写（3同级→上级数值对齐表）
    new_mult = GEM_TIERS[new_tier]["mult"]
    stats = {k: new_mult for k in stats}
    gem = {
        "name": "",
        "type": GEM_ITEM_TYPE,
        "gem": True,
        "stats": stats,
        "tier": new_tier,
        "icon": "💎",
    }
    if new_tier >= 9:
        gem["legend_effect"] = random.choice(GEM_LEGENDARY_EFFECTS)
    label = "·".join(f"{_stat_label(s)}+{int(stats[s] * 100)}%" for s in stats)
    gem["name"] = f"{_tier_label(new_tier)}·{label}"
    return gem


def gem_socket_cost(gem: dict) -> int:
    """拆卸费 = 500 × max(stats 层数)（层数 = 属性 mult 对应层）"""
    if not gem or not (gem.get("stats") or {}):
        return 0
    max_mult = max(gem["stats"].values())
    tier = max((k for k, info in GEM_TIERS.items() if info["mult"] == max_mult), default=1)
    return GEM_REMOVE_COST * tier


def sockets_capacity(quality: str) -> dict:
    """孔位表：返回 GEM_SOCKETS[quality]（未知品质返回白装 0 孔）"""
    return GEM_SOCKETS.get(quality, GEM_SOCKETS["white"])
