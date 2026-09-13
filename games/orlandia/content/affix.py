# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年内容包 —— 词条系统核心逻辑（B13-L1 端口，2026-09-14）。

真源：游戏仓 `game/core/affix.py`（159 行）**逐字端口**。宿主同名文件已改薄壳。

搬的边界 / 正文改动面（三类取件）
1. `from ..data import AFFIXES / LEGENDARY_EFFECTS` → **包内域读口**
   `content/data/affixes.json`（76 条）/ `legendary_effects.json`（93 条）—— 与宿主
   `game/data/affixes.py` 两张表**逐条 deep-equal**（B10-L1 已证；本线复核见报告 §3）。
2. `AFFIX_FALLBACK` / `AFFIX_COUNT` / `AFFIX_POOL_BY_QUALITY` / `SERIES_FIXED_AFFIX`
   （4 张表无同名域）→ 宿主数据层惰性替身 `_D = _HostMod("data")`，引用改 `_D.<名>`。
3. `from .stats import equip_stats` → 宿主句柄 `_host_attr("core.stats", "equip_stats")`
   （`core/stats.py` 归 **B13-L6** 线在搬；落地后切包内直取）。

引擎侧不变：`from saintess_engine.loot import count_for, draw_slots`（抽样形状已收口引擎）。

⚠️ 宿主源码级门禁（**本线未改测试**，登记给收口方）：`tests/test_v184_loot_tiers.py:691-692`
要求字面 `count_for(AFFIX_COUNT, quality, extra_chance=0.20, rng=random)` 与
`return draw_slots(pool, n, rng=random)` **出现在 `game/core/affix.py`** —— 薄壳后这两句只在本
文件里（宿主壳只再导出）→ 该测试 2 条断言会红。修法（判据只加强不削弱）：把 `_src()` 的路径
由 `game/core/affix.py` 改为 `framework/games/orlandia/content/affix.py`。同款门禁还钉着
`drops.py` / `smith_stock.py` / `event_templates.py` / `fishing.py` / `commands/misc.py`
（别线文件）→ 建议收口方一次性 retarget。
"""

import importlib
import sys

# ============================================================
# 宿主替身口（`content/index.py` / `content/world_cmds.py` 同款：注入优先 → sys.modules →
# importlib；**绝不静默空跑**）
# ============================================================
_HOST_PKG = "data.plugins.dragonfall.game"      # 运行时（main.py 的模块路径）
_HOST_PKG_FALLBACK = "game"                     # 测试/工具按 `game.xxx` 直接 import 时
_INJECTED = {}


def bind_host(**objs):
    """宿主薄壳 import 期注入（幂等）——键 = 宿主模块名（`data` / `content` / `db`）。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _host_module(name: str):
    """取宿主子模块（`name` 为空 = 宿主 `game` 包本身）。"""
    if name in _INJECTED:
        return _INJECTED[name]
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        m = sys.modules.get("%s.%s" % (prefix, name))
        if m is not None:
            return m
    last = None
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        try:
            return importlib.import_module("%s.%s" % (prefix, name))
        except Exception as exc:                # noqa: BLE001
            last = exc
    raise RuntimeError("%s：宿主模块 %s 取不到（%s）——拒绝静默空跑" % (__name__, name, last))


def _host_attr(mod: str, attr: str):
    """宿主模块属性 —— 真源「函数内 `from ..<mod> import <attr>`」的同义替身（调用时解析）。"""
    m = _host_module(mod)
    try:
        return getattr(m, attr)
    except AttributeError:
        for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
            try:
                return importlib.import_module("%s.%s" % (
                    prefix if not mod else "%s.%s" % (prefix, mod), attr))
            except Exception:                   # noqa: BLE001
                continue
        raise


class _HostMod:
    """宿主模块替身（`C` / `db` / `_D`）——`C.xxx` / `db.xxx` / `_D.xxx` 属性访问时解析。"""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return getattr(_host_module(self._name), attr)

# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年核心层 - affix.py（阶段八重写，2026-08-06）

20 章特色词条系统核心逻辑：
- roll_affixes：按品质随机词条池（武器/防具按部位过滤）→ 返回词条 ID 列表
- fixed_affixes：名册装备固定词条（20 章 3.x 系列主题）
- stat_affix_stats：常驻属性词条折算进装备 stats（crit_up/dodge/hp_up/swift）
- random_req：随机装备的属性需求估算（按部位/武器类型）
- 触发型词条（on_hit/on_taken/turn_start/battle_start/passive）由 battle.py 消费
"""

import random

from saintess_engine.loot import count_for, draw_slots

from .apply import _read_json

# ---- 包内域读口（B10-L1 已证逐条 deep-equal；本线复核见报告 §3）----
AFFIXES: dict = _read_json("affixes.json", {})
LEGENDARY_EFFECTS: dict = _read_json("legendary_effects.json", {})

# ---- 宿主数据层惰性替身（4 张表无同名域 → 报告缺口）----
_D = _HostMod("data")

# 词条触发时机分组（battle 挂点用）
TRIGGER_TYPES = {"stat", "on_hit", "on_taken", "turn_start", "battle_start", "passive"}


def _affix_base_value(slot: str, lv: int, stat: str) -> int:
    """附魔数值兜底：优先部位白板属性，无则用保底模板(旧词条系统遗留，enchant 用)"""
    equip_stats = _host_attr("core.stats", "equip_stats")   # B13-L6 线在搬；落地后切包内直取
    base = equip_stats(slot, lv, "white")
    if base.get(stat, 0) > 0:
        return base[stat]
    fb = _D.AFFIX_FALLBACK.get(stat, (2, 1.0))
    return int(fb[0] + fb[1] * lv)

# 随机装备属性需求估算：按部位/武器类型 → 主属性
_REQ_STAT_BY_SLOT = {
    "weapon": {"sword": "str", "mace": "str", "fist": "str", "spear": "str", "shield": "str",
               "bow": "agi", "dagger": "agi", "staff": "int"},
    "helm": "vit", "armor": "vit", "legs": "vit",
    "boots": "agi", "ring": "agi", "necklace": "int",
}

# 常驻属性词条 → 折算方式（生成时并入装备 stats）
# crit/dodge/precise/pene_phys/pene_magi/tenacity/luck 为小数概率直接加；hp/spd 按装备基础值百分比折算
# v106：pene_flat/pene_mflat 固定穿透按装备等级线性折算（lv_flat 系数 + min_flat 保底）
_STAT_AFFIX_FX = {
    "crit_up": {"stat": "crit", "pct": None, "flat": 0.05},
    "dodge": {"stat": "dodge", "pct": None, "flat": 0.05},
    "hp_up": {"stat": "hp", "pct": 0.05},
    "swift": {"stat": "spd", "pct": 0.05},
    # v130.2c 半活修复：精准词条补折算行（此前只接了 dmg_mult 1.10，命中率 0.10 从未并入
    # 装备 stats → _target_dodge_check 读 _player_stats['precise']（cap 0.60）恒为 0，命中加成失效）
    "precise": {"stat": "precise", "pct": None, "flat": 0.10},
    # v106 穿透/韧性/幸运词条折算
    "pene_phys": {"stat": "pene_phys", "pct": None, "flat": 0.05},
    "pene_magi": {"stat": "pene_magi", "pct": None, "flat": 0.05},
    "tenacity": {"stat": "tenacity", "pct": None, "flat": 0.05},
    "luck": {"stat": "luck", "pct": None, "flat": 0.05},
    "pene_flat": {"stat": "pene_flat", "lv_flat": 0.5, "min_flat": 2},
    "pene_mflat": {"stat": "pene_mflat", "lv_flat": 0.5, "min_flat": 2},
    # v106.1：冷却缩减/成长属性词条 + 元素抗性面板化（旧词条 ID 保留，折算成属性）
    "cdr": {"stat": "cdr", "pct": None, "flat": 0.05},
    "exp_bonus": {"stat": "exp_bonus", "pct": None, "flat": 0.05},
    "gold_bonus": {"stat": "gold_bonus", "pct": None, "flat": 0.05},
    "elem_resist": {"stat": "elem_res", "pct": None, "flat": 0.08},
    "abyss_resist": {"stat": "abyss_res", "pct": None, "flat": 0.10},
    # v106.2：治疗强度/护盾强度词条
    "heal_power": {"stat": "heal_power", "pct": None, "flat": 0.05},
    "shield_power": {"stat": "shield_power", "pct": None, "flat": 0.05},
    # v106.3：吸血/暴击伤害/格挡词条折算（lifesteal/block 由触发特效改属性，crit_dmg 补折算）
    "lifesteal": {"stat": "lifesteal", "pct": None, "flat": 0.08},
    "crit_dmg": {"stat": "crit_dmg", "pct": None, "flat": 0.20},
    "block": {"stat": "block", "pct": None, "flat": 0.15},
    # v106.4：反伤/物魔免/物法吸词条折算（thorns 由触发特效改属性）
    "thorns": {"stat": "thorns", "pct": None, "flat": 0.10},
    "phys_ward": {"stat": "phys_reduce", "pct": None, "flat": 0.05},
    "magic_ward": {"stat": "magic_reduce", "pct": None, "flat": 0.05},
    "thirst_phys": {"stat": "lifesteal_phys", "pct": None, "flat": 0.08},
    "thirst_magi": {"stat": "lifesteal_magi", "pct": None, "flat": 0.08},
}


def roll_affixes(slot: str, lv: int, quality: str) -> list:
    """按品质生成随机词条（20 章 4.2 随机池 + 部位过滤）。

    返回词条 ID 列表；白色 0 条、绿色 1 条、蓝色 2 条、紫色 3 条、
    橙色 3 条（20% 概率 4 条，兑现 AFFIX_COUNT.orange=[3,4]）。
    （名册固定词条不在随机池，由 fixed_affixes 提供。）

    v184：条数/抽样形状改走框架 `saintess_engine.loot`——
    条数 = `count_for`（定值 / `[3,4]` + `extra_chance` 命中上界，未知档位 0 条）；
    抽样 = `draw_slots`（等概率不放回，内部就是 `rng.sample`，与旧 `random.sample`
    同随机流同结果）。`rng` 传标准库 random 模块本体，随机流对齐旧实现。
    """
    # v184：条数（旧：AFFIX_COUNT 取值 + 列表档位 20% 命中上界）
    n = count_for(_D.AFFIX_COUNT, quality, extra_chance=0.20, rng=random)
    if not n:
        return []
    pool = _D.AFFIX_POOL_BY_QUALITY.get(quality, _D.AFFIX_POOL_BY_QUALITY["orange"])
    # 按部位过滤：武器只出攻击词条，防具只出防御词条（kind 归属）
    want_kind = "attack" if slot == "weapon" else "defense"
    pool = [a for a in pool if AFFIXES[a]["kind"] == want_kind]
    if not pool:
        return []
    # v184：不可重复抽样（固定项为空，等价旧 random.sample(pool, min(n, len(pool)))）
    return draw_slots(pool, n, rng=random)


def fixed_affixes(name: str) -> list:
    """名册装备固定词条(20 章 3.x 系列主题，无随机)

    v173.3 意见#171-A（鱼鱼拍板）：固定词条最多保留 1 条（系列主题锚点），
    第 2/3 条释放回随机池——随机空间放大（原 307 件 2 固定=蓝装 0 随机/紫橙仅 1
    随机；现蓝 1 随机/紫 2 随机/橙 2-3 随机），总词条数不变，数值强度不受影响。
    数据层 SERIES_FIXED_AFFIX 保持完整（供回退/参考），此处只截断消费端。
    """
    affs = list(_D.SERIES_FIXED_AFFIX.get(name, []))
    return affs[:1]


def stat_affix_stats(affix_ids: list, slot: str, lv: int) -> dict:
    """常驻属性词条折算成装备 stats 加成（crit/dodge 直接加，hp/spd 按基础值百分比）。

    返回 {属性: 加值}；触发型词条不在这里折算（由 battle 消费）。
    """
    out = {}
    for aid in affix_ids:
        fx = _STAT_AFFIX_FX.get(aid)
        if not fx:
            continue
        stat = fx["stat"]
        if fx.get("lv_flat") is not None:
            # v106：固定穿透按装备等级折算 max(min_flat, int(lv × lv_flat))，直接相加
            add = max(fx.get("min_flat", 2), int(lv * fx["lv_flat"]))
            out[stat] = out.get(stat, 0) + add
        elif fx.get("flat") is not None:
            out[stat] = round(out.get(stat, 0) + fx["flat"], 4)
        else:
            # 按装备基础值百分比折算（生成时已拿到 equip_stats 基础）
            equip_stats = _host_attr("core.stats", "equip_stats")   # B13-L6 线在搬
            base = equip_stats(slot, lv, "white").get(stat, 0)
            add = int(base * fx["pct"]) if base else max(1, lv // 10)
            out[stat] = out.get(stat, 0) + max(1, add)
    return out


def random_req(slot: str, lv: int, weapon_type: str | None = None) -> dict:
    """随机装备（非名册）的属性需求估算：主属性 + 5 + lv//5。

    名册装备用策划案表（EQUIP_ROSTER.req），此函数仅服务随机掉落/奖励装备。
    """
    if slot == "weapon":
        stat = _REQ_STAT_BY_SLOT["weapon"].get(weapon_type or "sword", "str")
    else:
        stat = _REQ_STAT_BY_SLOT.get(slot, "vit")
    return {stat: 5 + lv // 5}


def affix_label(aid: str) -> str:
    """词条显示短名(装备详情/词条表)"""
    info = AFFIXES.get(aid) or LEGENDARY_EFFECTS.get(aid)
    return info["name"] if info else aid
