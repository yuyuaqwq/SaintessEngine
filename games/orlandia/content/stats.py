# -*- coding: utf-8 -*-
"""《奥兰迪亚·余烬纪年》包内**数值公式层**（逐字搬自游戏仓 `game/core/stats.py`，268 行）。

真源 = 怪物属性公式（`monster_stats`）/ 装备属性公式（`equip_stats`/`equip_value`）/
经验金币（`exp_to_next`/`monster_exp`/`monster_gold`）/ 等级段乘区（`hp_stage_mult`/
`atk_stage_mult`/`_boss_atk_stage`/`_stage_mult`）。**数值一字未改**（数值权威 = 策划案仓
`32_数值设计.md`；本文件搬运不涉及任何数值调整）。宿主 `game/core/stats.py` 现在是薄壳
（全名单再导出，含 17 张数据表名与私有 `_stage_mult`/`_boss_atk_stage`/`_EXP_TABLE`）。

正文改动面（**只有 1 处**：模块级 `from ..data import (…)` 那 17 行取件）：
  真源 `from ..data import (EQUIP_SLOT_BASE, …, ARMOR_FAMILY_ALIAS)`（data 聚合层再导出）
  → 同表同源改走宿主句柄 `_D = _HostMod("data")` + 逐名绑定（行内注释一字不动）。
  绑定是**同一对象**（不是拷贝）→ `scripts/numeric_lib/monster.py` 的 `curve_override`
  就地改表（`S.MONSTER_ROLE_GROWTH[role][attr] = val`）依旧生效。

缺口（报告登记，均为宿主句柄，待 B14 切包内读口）：
  `MONSTER_ROLE_BASE/GROWTH` · `MONSTER_ROLE_MODS` · `MONSTER_EXP_BASE` · `MONSTER_GOLD_BASE` ·
  `QUALITY` · `EQUIP_SLOT_BASE/SCALING` · `WEAPON_DIST` · `ARMOR_FAMILY(_ALIAS)` ·
  `HP_STAGE_MULT/ATK_STAGE_MULT/NORMAL_HP_STAGE_MULT/BOSS_ATK_STAGE_MULT/INSTANCE_BOSS_ATK_STAGE_MULT` ·
  `FORMULA_SKELETON` —— 包内 `content/data|rules/` **没有**这些表的同形域（实测：
  `stats.json` 是面板快照 `lv_N→{level, exp_to_next}`；`monster_mods.json` 是 140 条 Boss 阶段表，
  与 `MONSTER_ROLE_MODS`（role→系数）**不同表**）。
"""

# ============================================================
# ① 宿主替身口（注入优先 → sys.modules → importlib；**绝不静默空跑**）
#    形状逐字抄 `content/world_cmds.py`（B9 线2 定稿）
# ============================================================
import importlib as _importlib
import sys as _sys

_HOST_PKG = "data.plugins.dragonfall.game"      # 运行时（main.py 的模块路径）
_HOST_PKG_FALLBACK = "game"                     # 测试/工具按 `game.xxx` 直接 import 时
_INJECTED = {}


def bind_host(**objs):
    """宿主薄壳 import 期注入（幂等）——键 = `_HostMod` 的模块名（`content` / `db` / `data`）。"""
    for k, v in (objs or {}).items():
        if v is not None:
            _INJECTED[k] = v


def _host_module(name: str):
    """取宿主子模块（`name` 为空 = 宿主 `game` 包本身）。"""
    if name in _INJECTED:
        return _INJECTED[name]
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        m = _sys.modules.get(prefix if not name else "%s.%s" % (prefix, name))
        if m is not None:
            return m
    last = None
    for prefix in (_HOST_PKG, _HOST_PKG_FALLBACK):
        try:
            return _importlib.import_module(prefix if not name else "%s.%s" % (prefix, name))
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
                return _importlib.import_module("%s.%s" % (
                    prefix if not mod else "%s.%s" % (prefix, mod), attr))
            except Exception:                   # noqa: BLE001
                continue
        raise


class _HostMod:
    """宿主模块替身（`C` / `db` / `data`）——`C.xxx` 正文一字未改，属性访问时解析。"""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return getattr(_host_module(self._name), attr)

# -*- coding: utf-8 -*-

# 真源 `from ..data import (…)`（17 张表；表名与行内注释逐字保留）→ 宿主句柄同表同源（头注）。
_D = _HostMod("data")
EQUIP_SLOT_BASE = _D.EQUIP_SLOT_BASE
EQUIP_SLOT_SCALING = _D.EQUIP_SLOT_SCALING
MONSTER_EXP_BASE = _D.MONSTER_EXP_BASE
MONSTER_GOLD_BASE = _D.MONSTER_GOLD_BASE
MONSTER_ROLE_BASE = _D.MONSTER_ROLE_BASE
MONSTER_ROLE_GROWTH = _D.MONSTER_ROLE_GROWTH
QUALITY = _D.QUALITY
NORMAL_HP_STAGE_MULT = _D.NORMAL_HP_STAGE_MULT      # v156 阶段 6 怪物数值修复
BOSS_ATK_STAGE_MULT = _D.BOSS_ATK_STAGE_MULT        # v156 阶段 6 怪物数值修复
INSTANCE_BOSS_ATK_STAGE_MULT = _D.INSTANCE_BOSS_ATK_STAGE_MULT  # v173.1 副本 Boss atk 段乘区（area=instance）
HP_STAGE_MULT = _D.HP_STAGE_MULT        # P2F-2 hp/atk 分段曲线表（v131 收缓/v169.3 正斜率，原函数体数值）
ATK_STAGE_MULT = _D.ATK_STAGE_MULT      # P2F-2 hp/atk 分段曲线表（v131 收缓/v169.3 正斜率，原函数体数值）
MONSTER_ROLE_MODS = _D.MONSTER_ROLE_MODS    # P2F-3 F14 monster_stats 角色修正表（boss/elite 硬编码数值下沉）
FORMULA_SKELETON = _D.FORMULA_SKELETON      # P2F-1 底层公式骨架参数（exp_to_next 兜底 / monster_exp / monster_gold）
WEAPON_DIST = _D.WEAPON_DIST                # P2F-2 v156 装备分系表下沉（data/equipment.py）
ARMOR_FAMILY = _D.ARMOR_FAMILY              # P2F-2 v156 装备分系表下沉（data/equipment.py）
ARMOR_FAMILY_ALIAS = _D.ARMOR_FAMILY_ALIAS  # P2F-2 v156 装备分系表下沉（data/equipment.py）
# v102.5 模板表下沉 data/stat_templates.py


"""奥兰迪亚·余烬纪年数据层 - stats.py"""
# v56.2 怪物等级段曲线（鱼鱼拍板调数值，根治"后期大招乱秒"）
# hp：16 级起渐入放大（30 级 ×2.2 / 60 级 ×3.4 / 90 级 ×4.3），≤15 级完全不变
# v169.3 承伤修复（2026-09-03 鱼鱼拍板，承伤审计 A1/A2）：atk 取消 31 级后负斜率——
#   原 31 级起每级 -0.5%、61 级起每级 -0.4% 会让怪攻击"越高级越弱"（30→100 级
#   怪 atk 只 +2.2 倍，满装玩家 def +5.7 倍）。改为 31+ 平缓正增长（每级 +0.4%，
#   100 级 ×1.28，怪攻击成长不再滞后玩家防御；配合 MONSTER_ROLE_GROWTH atk 上调）
def hp_stage_mult(lv: int) -> float:
    # v131 收缓（2026-08-27）：16-30 段 8%→5%（30 级 1.75）、31-60 段 4%→3%（60 级 2.65）、61+ 3%→2%（100 级 3.45）
    # P2F-2：分段点/斜率 → data/stat_templates.py HP_STAGE_MULT（_stage_mult 同款表语义，
    #   首段末值 1.0；逐 lv 1..200 等值探针 tests/test_numeric_p2f2_curve_tables.py 锁）。
    return _stage_mult(HP_STAGE_MULT, lv)


def atk_stage_mult(lv: int) -> float:
    # v169.3：31 级起每级 +0.4%（原 -0.5% 负斜率让怪 atk 越高级越弱，已废除）——
    # 数值意图：怪物攻击跟随玩家防御成长（配 MONSTER_ROLE_GROWTH atk 上调，攻防比 r 目标 1.0~1.6）。
    # ≤30 级保持 1.0（新手期裸装口径）；31 级起线性微增，100 级 ×1.28，无负斜率。
    # ⚠️ 消费侧：仅普通怪（tank/dps/caster/speedster/healer）与精英乘本函数；boss 走
    #   独立 _boss_atk_stage（旧减速曲线 + 下限 clamp），避免 boss 双重段乘区爆表。
    # P2F-2：分段点/斜率 → data/stat_templates.py ATK_STAGE_MULT（表驱动，等值探针锁）。
    return _stage_mult(ATK_STAGE_MULT, lv)


def _boss_atk_stage(lv: int) -> float:
    """v169.3 boss 专用 atk 等级曲线（保留 v169.2 减速曲线，数值完全一致）：
    31-60 级每级 -0.5%、61+ 每级 -0.4% 并夹 max(0.2, …) 防未来等级上限提升出现负 atk。
    boss 后期 atk 成长由 BOSS_ATK_STAGE_MULT（stat_templates v156 段乘区）承担，
    本曲线只为维持 boss 级内面板与旧版一致（BOSS_ATK_STAGE_MULT 门禁 8~12% 口径不动）。
    P2F-2：段表 + floor → data/formula_skeleton.py FORMULA_SKELETON["boss_atk_legacy"]
      （seg=((30,0),(60,-0.005),(999,-0.004))，floor=0.2；表语义与 _stage_mult 一致：
      ≤30 → 1.0；31-60 → 1.0-(lv-30)×0.005；61+ → 0.85-(lv-60)×0.004，夹 floor）。
    """
    _bal = FORMULA_SKELETON["boss_atk_legacy"]
    return max(_bal["floor"], _stage_mult(_bal["seg"], lv))


def _stage_mult(segments: tuple, lv: int) -> float:
    """等级段乘区表 → 分段线性（每段从上一段末值按斜率增长，与 hp_stage_mult 同风格）。

    segments: [(max_lv, slope_per_lv), ...]——每段 = (该段上限等级, 每级斜率)。
    从 lv=0 起：≤首段 max_lv 时 mult = 首段末值；之后每段按斜率线性增长。
    例：NORMAL_HP_STAGE_MULT = ((15, 0.0), (30, 0.09), (60, 0.005), (999, -0.02))
        Lv10 → 1.0；Lv24 → 1.0+(24-15)×0.09=1.81；Lv45 → 2.35+(45-30)×0.005=2.43；
        Lv95 → 2.50+(95-60)×(-0.02)=1.80 ✓（61+ 段按斜率下降）
    """
    if not segments:
        return 1.0
    # 首段：≤ max_lv 用首段末值（首段斜率 0 = 恒定）
    first_max, first_v = segments[0][0], 1.0
    if lv <= first_max:
        return 1.0
    mult = 1.0
    prev_max = 0
    for max_lv, slope in segments:
        if lv <= max_lv:
            return mult + (lv - prev_max) * slope
        mult += (max_lv - prev_max) * slope
        prev_max = max_lv
    # 超出最后一段：继续按最后一段斜率
    return mult + (lv - prev_max) * segments[-1][1]


def monster_stats(lv: int, role: str, area: str | None = None) -> dict:
    """怪物属性公式：按等级 + 角色模板生成。
    role: tank(血牛) / dps(攻高) / caster(魔攻) / speedster(敏捷) / healer(治疗) / boss(首领) / elite(精英)
    area: 地图 area（'instance'=副本）；None=非副本（野外/模拟）。v156 阶段 6：
          BOSS_ATK_STAGE_MULT 只对非副本 Boss 生效（副本 Boss 走 instances atk_mult + 狂暴机制控难，
          不再叠加——叠加会让 4 人标准队后期承伤轮暴跌扛不住）。
    v56.2：hp 吃等级段放大、atk 后期放缓（见 hp_stage_mult/atk_stage_mult）
    """
    base = MONSTER_ROLE_BASE[role]
    growth = MONSTER_ROLE_GROWTH[role]
    stats = {}
    for k in base:
        # v105：dodge 为百分比属性，round 保留小数（int 会截断成 0）
        # v106：pene_phys/pene_magi 同为百分比属性，同样保留小数
        if k in ("dodge", "pene_phys", "pene_magi"):
            stats[k] = round(base[k] + growth.get(k, 0) * (lv - 1), 3)
        else:
            stats[k] = int(base[k] + growth[k] * (lv - 1))
    # 首领/精英血量系数按等级段放大，保证后期 Boss 有压迫感
    # v118+ 审计（用户拍板）：双层叠加设上限 min(·, 3.0)，抑制高等级 boss 血量 runaway
    # boss 系数达 3.0 于 Lv≥33，elite 系数达 3.0 于 Lv≥50，此后不再随等级增长
    # P2F-3 F14：数值 → data/stat_templates.py MONSTER_ROLE_MODS（读表替换字面量，结构不变）
    if role == "boss":
        stats["hp"] = int(stats["hp"] * min(1 + lv * MONSTER_ROLE_MODS["boss"]["hp_per_lv"], MONSTER_ROLE_MODS["boss"]["hp_cap"]))
    if role == "elite":
        stats["hp"] = int(stats["hp"] * min(1 + lv * MONSTER_ROLE_MODS["elite"]["hp_per_lv"], MONSTER_ROLE_MODS["elite"]["hp_cap"]))
    # v106 穿透体系：Boss 重甲/精英精锐——防御 ×1.25/×1.15（穿透属性的需求端）
    # P2F-3 F14：数值 → MONSTER_ROLE_MODS
    if role == "boss":
        stats["def"] = int(stats["def"] * MONSTER_ROLE_MODS["boss"]["def_mult"])
        stats["mdef"] = int(stats["mdef"] * MONSTER_ROLE_MODS["boss"]["mdef_mult"])
    if role == "elite":
        stats["def"] = int(stats["def"] * MONSTER_ROLE_MODS["elite"]["def_mult"])
        stats["mdef"] = int(stats["mdef"] * MONSTER_ROLE_MODS["elite"]["mdef_mult"])
    # v56.2：全角色模板吃等级段曲线
    stats["hp"] = int(stats["hp"] * hp_stage_mult(lv))
    # v169.3 承伤修复：atk_stage_mult 正斜率（31 级起 +0.4%/级）只对普通怪+精英生效——
    #   boss 不吃（boss 已有独立 BOSS_ATK_STAGE_MULT 段乘区做后期成长，再叠正斜率会双重
    #   段乘区爆表——60 级单发占 HP 35%+ 超 12% 上限）；boss atk 保持原曲线（下方 boss 分支
    #   用 _boss_atk_stage 旧减速曲线，数值与原版完全一致，门禁口径不动）。
    if role != "boss":
        stats["atk"] = int(stats["atk"] * atk_stage_mult(lv))
    # v156 阶段 6 怪物数值修复（2026-09-01 鱼鱼拍板：裸装 4~6 轮只约束前期新手）：
    #   普通怪 HP × NORMAL_HP_STAGE_MULT（tank/dps/caster/speedster/healer）——
    #   中后期怪 HP 上调（满装击杀 1.5~2.6 轮 → 4~6 轮），前期 ≤15 恒 1.0（新手裸装 5.8 轮达标）。
    #   Boss atk × BOSS_ATK_STAGE_MULT——**仅非副本 Boss**（野外 Boss 后期攻击追上玩家防御，
    #   单发占 HP 0.9% → 8~12%）；副本 Boss 不吃（走 instances atk_mult + 狂暴机制控难，叠加会打崩 4 人队）。
    #   精英不吃本表（已有 FIELD_TIER_MULT 分档 + 独立 growth）。
    if role in ("tank", "dps", "caster", "speedster", "healer"):
        stats["hp"] = int(stats["hp"] * _stage_mult(NORMAL_HP_STAGE_MULT, lv))
    elif role == "boss" and area == "instance":
        # v173.1 副本 Boss atk 段乘区（鱼鱼拍板 2026-09-04，治本对齐野外 v156 做法）：
        #   副本 Boss 此前被排除在 BOSS_ATK_STAGE_MULT 外（注释怕打崩 4 人队），但后期
        #   玩家装备 HP/def 涨 ~11 倍、Boss atk 只涨 ~3 倍 → 平砍仅 2-4% 坦克 HP，牧师失业。
        #   本分支给副本 Boss 同款段乘区（INSTANCE_BOSS_ATK_STAGE_MULT），让平砍占 HP
        #   多人 12-15% / 单人 10-12%（单人差异由 instances atk_mult 回调承担）。
        #   乘法位置与野外 boss 分支一致：先乘旧减速曲线再乘段乘区（数值可比），
        #   且不破坏 v169.3 野外门禁口径（area 分支互斥）。
        stats["atk"] = int(int(stats["atk"] * _boss_atk_stage(lv)) * _stage_mult(INSTANCE_BOSS_ATK_STAGE_MULT, lv))
    elif role == "boss" and area != "instance":
        # v169.3 boss 分支：先乘旧 atk 减速曲线（数值与 v169.2 完全一致，不改 boss 强度），
        # 再乘 BOSS_ATK_STAGE_MULT 段乘区（_boss_atk_stage 含下限 clamp 防未来等级上限提升出负 atk）。
        # ⚠️ 保持与原实现相同的逐级 int（int(atk×_boss_atk_stage) 后再 ×段乘区 int），
        # 两级截断与合并一次乘差 ±1，会让 monster_curve 门禁 60 级 boss atk 1217↔1218 红。
        stats["atk"] = int(int(stats["atk"] * _boss_atk_stage(lv)) * _stage_mult(BOSS_ATK_STAGE_MULT, lv))
    # 重构图契约 §4.1：dot_res 异常抗性（结算时乘 (1-dot_res)）——
    # boss/elite 设置抗性，普通怪不设键（缺失=0）。cap 0.95 由结算端约束。
    if role == "boss":
        stats["dot_res"] = MONSTER_ROLE_MODS["boss"]["dot_res"]
    elif role == "elite":
        stats["dot_res"] = MONSTER_ROLE_MODS["elite"]["dot_res"]
    return stats

# v156 装备分系表（P2F-2 下沉 data/equipment.py——纯 dict 零函数；此处仅从 data 聚合再导出，
# 保持 core.stats.ARMOR_FAMILY_ALIAS / WEAPON_DIST 旧引用名可用：drops.py:3 / economy.py:196 直引）
#   武器按 weapon_type 分系（atk/matk 分配），防具按需求属性族分系——数值见 data/equipment.py 注释。
__all__ = []  # 本文件无 __all__ 限制（core/stats 函数均经 core/__init__ 聚合）；占位防误读

def equip_stats(slot: str, lv: int, quality: str,
                weapon_type: str | None = None,
                armor_family: str | None = None) -> dict:
    """装备属性公式：部位 + 装备等级 + 品质 → 属性字典

    v156 装备分系（可选参数，默认 None = 旧行为，36 调用点零破坏）：
      - weapon_type: 武器分系（sword/dagger/fist/bow/spear 物理 atk 主；
                      staff/mace 法系 matk 主；shield 防御向）——表 data/equipment.py WEAPON_DIST
      - armor_family: 防具分系（heavy 重甲 HP高/def高；leather 皮甲 spd高；
                       cloth 布甲 mdef高）——表 data/equipment.py ARMOR_FAMILY
    只有装备生成路径显式传参才生效，其余调用保持原样。
    """
    mult = QUALITY[quality]["mult"]
    base = EQUIP_SLOT_BASE[slot]
    scaling = EQUIP_SLOT_SCALING[slot]
    stats = {}
    for k in base:
        stats[k] = int((base[k] + scaling[k] * lv) * mult)
    # v156 武器分系：按 weapon_type 重分配 atk/matk（保留部位基础总量）
    if slot == "weapon" and weapon_type and weapon_type in WEAPON_DIST:
        dist = WEAPON_DIST[weapon_type]
        total = stats.get("atk", 0) + stats.get("matk", 0)
        stats["atk"] = int(total * dist["atk"])
        stats["matk"] = int(total * dist["matk"])
    # v156 防具分系：按需求属性族调整 HP/def/mdef/spd（保留部位基础）
    if slot in ("helm", "armor", "legs", "boots") and armor_family:
        fam = ARMOR_FAMILY.get(armor_family)
        if fam:
            for k, m in (("hp", fam["hp_mult"]), ("def", fam["def_mult"]),
                         ("mdef", fam["mdef_mult"]), ("spd", fam["spd_mult"])):
                if k in stats:
                    stats[k] = int(stats[k] * m)
    # P2F-2：crit/项链修正系数进 data/formula_skeleton.py（FORMULA_SKELETON["equip_crit"] /
    #   ["necklace_mdef"]；默认=现状字面量，行为零变化）
    #   注意保持原 int 截断序：先 int((base+scaling*lv)*mult) 再逐段 int(×分系乘数)，绝不重排。
    if slot in ("weapon", "ring") and quality in ("blue", "purple", "orange"):
        _ec = FORMULA_SKELETON["equip_crit"]
        stats["crit"] = round((_ec["base"] + _ec["per_lv"] * lv / _ec["per_lv_div"])
                              * (QUALITY[quality]["mult"] - 1), 3)
    if slot == "necklace" and quality in ("blue", "purple", "orange"):
        _nm = FORMULA_SKELETON["necklace_mdef"]
        stats["mdef"] += int(_nm["flat"] * mult)
    return stats


# v101.25h3 装备属性价值权重（定价用）：HP/MP 是"量"不是"质"，1 点 HP 远不值 1 点攻击。
# 曾导致权杖(hp_fix 60) Lv.2 白装卖 560 金币 vs 铁剑 80——HP 被当攻击等价计价。
_EQUIP_VALUE_WEIGHT = {"hp": 0.1, "mp": 0.1}


def equip_value(stats: dict) -> float:
    """装备属性加权总值（定价/推导价用）：atk/matk/def/mdef/spd/crit/dodge 全价，HP/MP 按 0.1 折算"""
    return sum(v * _EQUIP_VALUE_WEIGHT.get(k, 1.0) for k, v in stats.items())

# v169.1 成长模型：升级需求改用 5 级锚点指数插值全表（鱼鱼 2026-09-03 拍板）。
#   锚点 = Lv5 4630 / 10 9409 / 15 15174 / 20 29409 / 25 47569 / 30 69422 / 35 96561 /
#           40 127693 / 45 167354 / 50 213918 / 55 309359 / 60 382253 / 65 462540 /
#           70 553894 / 75 767838 / 80 901590 / 85 1051881 / 90 1219439 / 95 1403343 / 100 1607650
#   中间等级 = 锚点间对数线性(指数)插值后取整百，全表写死 → 纯查表 O(1)。
#   设计意图：5 阶段成长（新手期轻、成长期递增、中后期爬坡、终局放缓），
#   配合怪物经验供给，中活跃度玩家约 9~10 个月满级（旧曲线 40-50 天即满级，太平）。
#   存量兼容：玩家经验按级内进度存储，改需求曲线只影响后续升级，无需动 DB。
_EXP_TABLE = {
    1: 2600,     2: 3000,     3: 3500,     4: 4000,     5: 4630,
    6: 5300,     7: 6100,     8: 7100,     9: 8200,     10: 9409,
    11: 10400,     12: 11400,     13: 12500,     14: 13800,     15: 15174,
    16: 17300,     17: 19800,     18: 22600,     19: 25800,     20: 29409,
    21: 32400,     22: 35600,     23: 39200,     24: 43200,     25: 47569,
    26: 51300,     27: 55300,     28: 59700,     29: 64400,     30: 69422,
    31: 74200,     32: 79200,     33: 84600,     34: 90400,     35: 96561,
    36: 102100,     37: 108000,     38: 114200,     39: 120800,     40: 127693,
    41: 134800,     42: 142300,     43: 150200,     44: 158500,     45: 167354,
    46: 175800,     47: 184600,     48: 193900,     49: 203700,     50: 213918,
    51: 230300,     52: 247900,     53: 266900,     54: 287400,     55: 309359,
    56: 322700,     57: 336700,     58: 351200,     59: 366400,     60: 382253,
    61: 397100,     62: 412500,     63: 428600,     64: 445200,     65: 462540,
    66: 479500,     67: 497100,     68: 515400,     69: 534300,     70: 553894,
    71: 591300,     72: 631200,     73: 673800,     74: 719300,     75: 767838,
    76: 792900,     77: 818800,     78: 845500,     79: 873100,     80: 901590,
    81: 929800,     82: 958900,     83: 989000,     84: 1019900,     85: 1051881,
    86: 1083400,     87: 1115900,     88: 1149400,     89: 1183900,     90: 1219439,
    91: 1254200,     92: 1289900,     93: 1326700,     94: 1364500,     95: 1403343,
    96: 1442000,     97: 1481700,     98: 1522600,     99: 1564500,     100: 1607650,
}


def exp_to_next(level: int) -> int:
    """升到下一级所需经验（v169.1 成长模型：5 级锚点指数插值全表驱动，查表 O(1)。
    中活跃度玩家约 9~10 个月满级；超出 100 级兜底旧公式不崩）
    P2F-1：兜底幂函数系数进 data/formula_skeleton.py（FORMULA_SKELETON["exp_fallback"]）"""
    _fb = FORMULA_SKELETON["exp_fallback"]
    return _EXP_TABLE.get(level, int(_fb["base"] * max(level, 0) ** _fb["power"] + _fb["add"]))

def monster_exp(lv: int, role: str) -> int:
    """怪物经验公式（v28 校准：base 下调，配合等级差惩罚）
    v56.2：怪 hp 变肉后经验同步补偿（×hp_mult^0.7，30 级约 ×1.8）
    v131：战斗拉长补偿 ×1.5（2026-08-27 拍板，27 章附章七同步）
    P2F-1：0.9/1.5/0.7 斜率系数进 data/formula_skeleton.py（FORMULA_SKELETON["monster_exp"]）"""
    _me = FORMULA_SKELETON["monster_exp"]
    base = MONSTER_EXP_BASE[role]
    exp = int(base * (1 + lv * _me["linear_slope"]))
    return int(exp * _me["combat_len_mult"] * (hp_stage_mult(lv) ** _me["hp_pow"]))


def monster_gold(lv: int, role: str) -> int:
    """怪物金币公式(v56.2：同步补偿 ×hp_mult^0.5)
    v131：战斗拉长补偿 ×1.3（2026-08-27 拍板，27 章附章七同步）
    P2F-1：0.6/1.3/0.5 斜率系数进 data/formula_skeleton.py（FORMULA_SKELETON["monster_gold"]）"""
    _mg = FORMULA_SKELETON["monster_gold"]
    base = MONSTER_GOLD_BASE[role]
    gold = int(base * (1 + lv * _mg["linear_slope"]))
    return int(gold * _mg["combat_len_mult"] * (hp_stage_mult(lv) ** _mg["hp_pow"]))

