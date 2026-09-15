# -*- coding: utf-8 -*-
"""《奥兰迪亚·余烬纪年》包内**掉落/怪物构造核心域**（逐字搬自游戏仓 `game/core/drops.py`，573 行）。

真源与范围
----------
真源 = 宿主 `game/core/drops.py`（573 行）**实现本体**：8 个模块级真函数
（`make_blueprint` / `roll_blueprint` / `roll_drop` / `roll_drop_equip` / `generate_equip` /
`generate_roster_equip` / `build_monster` / `build_monster_group`）+ 2 个被宿主消费者按名读取的
私有名（`_merge_legendary_stats` ← `game/commands/economy.py:53`、`_eq_random_desc` ←
`game/services/shop.py:13`）+ 2 个纯内部助手（`_scale_monster` / `_scale_main_copy`）。
B2-C2 把这一份整体搬进包内（落点 = `overnight/B2_W0_INTERFACE.md` §1 第 5 行：☆ `content/drops.py`，
**不并入 `content/loot.py`** —— loot.py 是另一个宿主单元 `game/drop_engine.py` 的端口，
其 4 个同名符号是替代桩 `content/loot.py:113-133`）；宿主那份留到波 2 原子改口成薄壳。

搬的是什么、一行没动什么
------------------------
正文从真源 `:22`（`_BLUEPRINT_RECIPE_RIDS` 注释起）到 EOF **逐字节未改**（脚本搬运 + 断言，
见 `out/evidence/drops_move_verify.txt`）。只换「宿主取件」：
  ① `from .stats import …` / `from .affix import …`（真源相对宿主 `game/core/*`）
     → 包内同名模块（`content/stats.py` / `content/affix.py`；宿主那两个是薄壳 → 同一批对象）
  ② `from .. import content as C`（真源读宿主聚合层）→ 下方 `C = _PkgContent()` 包内等价面
     （只 6 个消费名：PCT_STATS / EQUIP_ROSTER / EQUIP_SLOTS / BOSS_BP_DROP_CHANCE /
      MONSTER_MODS / AFFIX_AFFINITY_POOLS；逐名 = 包内门面同源，惰性解析时机与真源一致）
  ③ `from content.catalog_* import …`（真源已直取包内门面）→ 相对 import 同一批门面
  ④ 唯一包外依赖 = 引擎 `saintess_engine.loot`（真源 `:7` 原样）

`C` 消费名 → 包内落点（对拍依据 = `game/content.py:29-36` 的门面装配序 + W0 接口表第 5 行）
| 真源 `C.<名>` | 包内落点 | 依据 |
|---|---|---|
| `PCT_STATS` | `content/catalog_core.py:81` | 接口表第 5 行 |
| `EQUIP_ROSTER` | `content/catalog_items.py` | 同款切法见 `content/smith_stock.py:147`（B16-W11d） |
| `EQUIP_SLOTS` | `content/catalog_b143.py:218` | 接口表第 5 行 |
| `BOSS_BP_DROP_CHANCE` | `content/constants.py:129` | 接口表第 5 行 |
| `MONSTER_MODS` | `content/catalog_quests.py:526` | 接口表第 5 行 |
| `AFFIX_AFFINITY_POOLS` | `content/catalog_rules.py:2441` | 接口表第 5 行 |

方向：内容 → 引擎（本文件只 `import saintess_engine`；**不 import 宿主任何模块**）。
"""
import importlib
import random

from saintess_engine.loot import count_for, draw_slots

from .affix import fixed_affixes, random_req, roll_affixes, stat_affix_stats
from .stats import (ARMOR_FAMILY_ALIAS, equip_stats, equip_value, monster_exp,
                    monster_gold, monster_stats)

# 真源模块级 `from content.catalog_* import …`（原样直取包内门面；此处改相对 import）
from .catalog_b143 import AFFIX_POOL_BY_QUALITY, QUALITY, WEAPON_FLAVOR
from .catalog_items import AFFIXES, LEGENDARY_EFFECTS
from .catalog_life import CRAFT_RECIPES
from .catalog_rules import (EQUIP_NAME_PREFIX, EQUIP_NAME_SUFFIX, EQUIP_PREFIX_FLAVOR,
                            FIELD_TIER_MULT, SERIES_SETS, SET_CHANCE, SET_THEMES,
                            WEAPON_NAME_SUFFIX, WEAPON_TYPES)


# ============================================================
# 搬运头：真源 `from .. import content as C` 的**包内等价面**（非真源正文）
#   只覆盖真源正文实际用到的 6 个名（`C.` 全量扫描见 out/evidence/drops_move_verify.txt）：
#   惰性直取包内门面 —— 取件时机与宿主聚合层 `C.<名>` 一致（每次属性访问解析一次），
#   且本模块 import 期不拉这些门面（不引入新的 import 期表面）。
# ============================================================
_PKG_CONTENT_API = {
    "PCT_STATS": ("content.catalog_core", "PCT_STATS"),
    "EQUIP_ROSTER": ("content.catalog_items", "EQUIP_ROSTER"),
    "EQUIP_SLOTS": ("content.catalog_b143", "EQUIP_SLOTS"),
    "BOSS_BP_DROP_CHANCE": ("content.constants", "BOSS_BP_DROP_CHANCE"),
    "MONSTER_MODS": ("content.catalog_quests", "MONSTER_MODS"),
    "AFFIX_AFFINITY_POOLS": ("content.catalog_rules", "AFFIX_AFFINITY_POOLS"),
}


class _PkgContent:
    """包内内容面（真源 `from .. import content as C` 的同义替身）。"""

    __slots__ = ()

    def __getattr__(self, name):
        target = _PKG_CONTENT_API.get(name)
        if target is None:
            raise AttributeError("content.drops：包内内容面没有 %r" % (name,))
        mod, attr = target
        return getattr(importlib.import_module(mod), attr)


C = _PkgContent()


# v104 修复 P1（M07 审计）：图纸池只保留有 CRAFT_RECIPES 配方的名册装备，
# 剔除星尘/灰烬守卫等无配方隐藏线装备（11 张废图纸不再混入随机池）。
_BLUEPRINT_RECIPE_RIDS = frozenset(
    rec.get("roster_id") for rec in CRAFT_RECIPES.values() if rec.get("roster_id")
)




def _merge_legendary_stats(stats: dict, legendary: str, slot: str, lv: int) -> None:
    """v125 修复：传说专属 stat 型效果并入装备 stats（生成处折算一次，engine 属性聚合只读
    stats、battle 只按 affix ids 消费元素/触发型，防双算）。
    PCT_STATS 键（crit/crit_dmg/luck 等）直接加；hp_pct 按白板基础生命百分比折算
    （与词条 hp_up 折算口径一致）；元素型（ice_dmg/thunder_dmg）与战斗触发型
    （dmg_reduce 等）不并入——保持 battle.py 原有消费不动。"""
    info = LEGENDARY_EFFECTS.get(legendary)
    if not info or info.get("trigger") != "stat":
        return
    for k, v in (info.get("effect") or {}).items():
        if k == "hp_pct":
            base_hp = equip_stats(slot, lv, "white").get("hp", 0)
            stats["hp"] = stats.get("hp", 0) + max(1, int(base_hp * v))
        elif k in C.PCT_STATS:
            stats[k] = round(stats.get(k, 0) + v, 4)


def _eq_random_desc(name: str, slot: str, weapon_type: str | None = None) -> str:
    """随机装备描述（v101.25g）：按部位/武器类型模板生成，避免与名册描述撞车"""
    if slot == "weapon":
        wt = weapon_type or "sword"
        wt_map = {
            "sword": "长剑", "dagger": "短刃", "staff": "法杖", "bow": "长弓",
            "mace": "战锤", "fist": "拳套", "shield": "盾牌", "spear": "长枪", "axe": "战斧",
        }
        base = f"这是一件{wt_map.get(wt, '武器')}，刃口打磨精细，握感趁手"
    elif slot == "helm":
        base = "这是一顶头盔，护住要害，透气不闷"
    elif slot == "armor":
        base = "这是一件护甲，版型合体，活动自如"
    elif slot == "legs":
        base = "这是一副护腿，膝盖处加厚，耐磨耐打"
    elif slot == "boots":
        base = "这是一双靴子，鞋底防滑，走山路也稳当"
    elif slot == "ring":
        base = "这是一枚戒指，戒面光滑，做工精致"
    elif slot == "necklace":
        base = "这是一条项链，链坠做工精细，贴身佩戴"
    else:
        base = "这是一件装备，做工扎实"
    return f"{base}。{name}——冒险途中得来，成色不错。"

def make_blueprint(rid: str) -> dict:
    """按名册 ID 精确构造图纸物品（v94：商店『购买 图纸』用）。

    与 roll_blueprint 同一构造逻辑，保证显示与入包一致。
    """
    r = C.EQUIP_ROSTER[rid]
    q = QUALITY[r["quality"]]
    return {
        "name": f"{r['name']}图纸", "type": "图纸", "stackable": True,
        "price": int(r["lv"] * 3 + 20), "blueprint_for": r["name"], "roster_id": rid,
        "quality": r["quality"],
        # v56.4：玩家语言描述——不含内部 ID
        "desc": f"{q['name']}级图纸：{r['name']}({C.EQUIP_SLOTS[r['slot']]})",
    }

def roll_blueprint(monster_lv: int):
    """按等级就近从名册抽一张图纸（阶段八：名册图纸化）。

    候选 = 10 章名册中需要图纸的装备（source = 图纸/boss），
    返回图纸物品 data（type=图纸，blueprint_for=装备名，roster_id=名册 ID），
    学习后解锁对应名册配方（craft.py『学习』）。
    v94 起图纸不再靠战斗掉落（改走宝箱/垂钓/商店），此函数供探索宝箱/垂钓/商店使用。
    """
    cands = []
    for rid, r in C.EQUIP_ROSTER.items():
        # v104 修复 P1：候选必须有名册配方（CRAFT_RECIPES 有对应 roster_id），
        # 无配方的隐藏线装备（星尘/灰烬守卫）不出图纸
        if r["source"] in ("图纸", "boss") and rid in _BLUEPRINT_RECIPE_RIDS:
            cands.append((rid, r))
    if not cands:
        return None
    # 等级就近：优先 |lv - monster_lv| <= 15；
    # v104 修复 P1：就近为空时按等级距离取最近 3 张（此前回退全池随机——
    # Lv.1-17 的怪会掉 60-90 级用不上的图纸，占图纸池 60%+）
    near = [c for c in cands if abs(c[1]["lv"] - monster_lv) <= 15]
    if not near:
        near = sorted(cands, key=lambda c: abs(c[1]["lv"] - monster_lv))[:3]
    rid, _r = random.choice(near)
    return make_blueprint(rid)

def roll_drop(monster_lv: int, role: str, luck: float = 0.0):
    """怪物死亡掉落（v94 图纸经济改革，2026-08-09）：返回 (装备 or None, 图纸 or None, 金币, 经验)

    v93 改革（鱼鱼拍板）：怪物**永不掉装备**——装备走铁匠铺购买 + 图纸锻造进阶；
    v94（鱼鱼拍板）：图纸**退出战斗掉落**——普通怪/精英不再掉图纸（防止泛滥），
    图纸改走探索宝箱/垂钓宝物/商店购买；仅 Boss 保留惊喜掉率。
    材料掉落由消费端 _handle_victory 按 monster['drops'] 处理。
    消费端（_handle_victory）只入包图纸，装备位恒为 None。
    v106 幸运：Boss 图纸惊喜掉率 × (1+幸运)（幸运上限 50%）
    v135（鱼鱼拍板）：基础掉率 5% → 10%（constants.BOSS_BP_DROP_CHANCE），
    幸运 50% 时最高 10% × 1.5 = 15%。
    """
    if role == "boss":
        chance = C.BOSS_BP_DROP_CHANCE * (1.0 + min(max(float(luck), 0.0), 0.5))
        if random.random() < chance:  # v101.5 常量
            return None, roll_blueprint(monster_lv), 0, 0
        return None, None, 0, 0
    # 普通怪 / 精英：不掉图纸（v94）
    return None, None, 0, 0

def roll_drop_equip(monster_lv: int, role: str) -> dict | None:
    """v140 装备掉落引擎（鱼鱼拍板：打破 v93 怪不掉装备铁律，但普通怪仍不掉）。

    精英：蓝装 90% / 紫装 10%，基础掉率 15%（不吃幸运，防与图纸叠加膨胀；v170 12%→15%）
    野外/副本 Boss：紫装 70% / 橙装 30%，基础掉率 35%（图纸 10% 独立判定共存）
    普通怪：不掉（v93 保留，控总量防海量刷）
    装备 = 从名册按等级就近抽（|名册lv - 怪lv| <= 15 优先 → ±30 → 兜底随机生成）
    返回装备 dict（名册精确生成）或 None。词条生成走 generate_roster_equip / generate_equip。
    """
    if role == "elite":
        if random.random() >= 0.15:
            return None
        quality = "purple" if random.random() < 0.10 else "blue"
    elif role == "boss":
        if random.random() >= 0.35:
            return None
        quality = "orange" if random.random() < 0.30 else "purple"
    else:
        # 普通怪不掉装备（v93 铁律保留）
        return None

    # 从名册按等级就近抽（优先 ±15，再 ±30，兜底随机生成）
    # v172 路B：source=重锻 装备（仅『装备重锻』可得）不进精英/Boss 掉落池
    # v173 路A（问题A修复）：候选源白名单 = {boss, legend}——图纸/任务/支线/锻造/商店/
    #   宝藏/精英专属 等"非掉落可得"源全排除，杜绝 Boss/精英掉出图纸源装备、
    #   或低级 Boss 掉出另一 Boss 专属（如 Lv.15 咕噜掉 Lv.98 摩罗之冠）的越权掉落。
    #   名册 source 分布（v172 审计）：图纸194/锻造184/商店127/boss61/副本Boss26/重锻24/
    #   legend22/精英专属18/任务9/支线9/宝藏6/精英2。白名单仅 boss61+legend22=83 件可掉。
    #   （副本 Boss 走 INSTANCE_BOSS_EQUIP_DROP 主题池 + 主专属白名单，不经本函数。）
    _DROP_SOURCE_OK = ("boss", "legend")
    roster = C.EQUIP_ROSTER
    candidates_15 = [rid for rid, r in roster.items()
                     if r.get("source") in _DROP_SOURCE_OK
                     and r.get("quality") == quality and abs(r.get("lv", 0) - monster_lv) <= 15]
    if candidates_15:
        rid = random.choice(candidates_15)
        return generate_roster_equip(rid)
    candidates_30 = [rid for rid, r in roster.items()
                     if r.get("source") in _DROP_SOURCE_OK
                     and r.get("quality") == quality and abs(r.get("lv", 0) - monster_lv) <= 30]
    if candidates_30:
        rid = random.choice(candidates_30)
        return generate_roster_equip(rid)
    # 兜底：随机生成
    slot = random.choice(["weapon", "helm", "armor", "legs", "boots", "ring", "necklace"])
    return generate_equip(slot, monster_lv, quality)


def generate_equip(slot: str, lv: int, quality: str, weapon_type: str | None = None):
    """生成一件随机装备（名称 + 属性 + 词条 v2 + 属性需求）。

    阶段八（2026-08-06）：词条从旧属性词条 [{'stat','value'}] 改为 20 章特效词条 ID 列表；
    常驻属性词条（暴击强化/闪避/生命强化/迅捷）折算进 stats；橙装随机挂 1 个传说专属；
    全部装备带属性需求（力量/智力/敏捷/耐力，不锁职业）。
    """
    set_name = None
    flavor_prefix = ""
    if slot == "weapon":
        if not weapon_type:
            weapon_type = random.choice(list(WEAPON_TYPES.keys()))
        base_name = EQUIP_NAME_PREFIX[quality][random.randrange(len(EQUIP_NAME_PREFIX[quality]))]
        flavor_prefix = base_name
        # v29：后缀从该武器类型的专属命名池取（杜绝"之弓"配剑）
        suffix = random.choice(WEAPON_NAME_SUFFIX[weapon_type])
        name = f"{base_name}{suffix}"
        if quality == "orange":
            name = f"传说·{base_name}{suffix}"
    else:
        prefix = EQUIP_NAME_PREFIX[quality][random.randrange(len(EQUIP_NAME_PREFIX[quality]))]
        flavor_prefix = prefix
        suffix = random.choice(EQUIP_NAME_SUFFIX[slot])
        name = f"{prefix}{suffix}"
    # v10：套装归属（蓝以上按品质概率，主题前缀即套装名）
    if quality in SET_THEMES and random.random() < SET_CHANCE.get(quality, 0):
        set_name = random.choice(SET_THEMES[quality])
        flavor_prefix = set_name  # v58：套装属性倾向跟随套装主题名
        if slot == "weapon":
            # v29：套装武器也用类型专属后缀
            suffix = random.choice(WEAPON_NAME_SUFFIX[weapon_type])
            name = f"{set_name}{suffix}"
        else:
            suffix = random.choice(EQUIP_NAME_SUFFIX[slot])
            name = f"{set_name}{suffix}"
    stats = equip_stats(slot, lv, quality)
    # v156 装备分系：武器按 weapon_type 分系、防具按需求属性族分系（随机装备路径）
    if slot == "weapon":
        stats = equip_stats(slot, lv, quality, weapon_type=weapon_type)
    elif slot in ("helm", "armor", "legs", "boots"):
        _req = random_req(slot, lv, weapon_type)
        _fam = ARMOR_FAMILY_ALIAS.get(next(iter(_req), ""), None)
        if _fam:
            stats = equip_stats(slot, lv, quality, armor_family=_fam)
    # v58：前缀属性倾向（名字风格真实影响手感）
    prefix_flavor = EQUIP_PREFIX_FLAVOR.get(flavor_prefix, {})
    if prefix_flavor:
        for fk, fv in prefix_flavor.items():
            if fk in C.PCT_STATS:
                stats[fk] = round(stats.get(fk, 0) + fv, 3)
            else:
                stats[fk] = max(0, stats.get(fk, 0) + int(fv))
    # v29：武器类型特色加成（剑微暴击/法杖魔攻/弓速度暴击/匕首暴击/拳套攻击等）
    flavor = WEAPON_FLAVOR.get(weapon_type, {}) if slot == "weapon" else {}
    flavor_stats = {}
    if flavor:
        for fk, fv in flavor.items():
            if fk == "desc" or not isinstance(fv, (int, float)):
                continue
            if fk == "crit":
                stats["crit"] = round(stats.get("crit", 0) + fv, 3)
                flavor_stats["crit"] = fv
            elif fk == "spd_fix":
                stats["spd"] = stats.get("spd", 0) + int(fv)
                flavor_stats["spd"] = int(fv)
            elif fk == "hp_fix":
                stats["hp"] = stats.get("hp", 0) + int(fv)
                flavor_stats["hp"] = int(fv)
            else:
                add = int(stats.get(fk, 0) * fv)
                stats[fk] = stats.get(fk, 0) + add
                flavor_stats[fk] = add
    # 阶段八：特效词条 v2（随机池 + 常驻属性折算）
    affix_ids = roll_affixes(slot, lv, quality)
    for k, v in stat_affix_stats(affix_ids, slot, lv).items():
        if k in C.PCT_STATS:
            stats[k] = round(stats.get(k, 0) + v, 4)
        else:
            stats[k] = stats.get(k, 0) + int(v)
    equip = {
        "name": name,
        "slot": slot,
        "quality": quality,
        "lv": lv,
        "weapon_type": weapon_type if slot == "weapon" else None,
        "stats": stats,
        "price": int(equip_value(stats) * (3 + lv * 0.5) * QUALITY[quality]["mult"]),
        # 阶段八：属性需求（不锁职业，只锁力量/智力/敏捷/耐力）
        "req": random_req(slot, lv, weapon_type),
    }
    if flavor_stats:
        equip["flavor"] = flavor_stats
    if affix_ids:
        equip["affixes"] = affix_ids
    # 阶段八：随机橙装挂 1 个传说专属
    if quality == "orange":
        equip["legendary"] = random.choice(list(LEGENDARY_EFFECTS.keys()))
        # v125：随机橙装专属 stat 型效果同样并入 stats（与名册口径一致，价格重算）
        _merge_legendary_stats(equip["stats"], equip["legendary"], slot, lv)
        equip["price"] = int(equip_value(equip["stats"]) * (3 + lv * 0.5) * QUALITY[quality]["mult"])
    if set_name:
        equip["set"] = set_name
    # v101.25g：随机装备描述（无名册 → 按部位/武器类型生成）
    equip["desc"] = _eq_random_desc(name, slot, weapon_type)
    return equip


def generate_roster_equip(rid: str, affinity: str | None = None) -> dict:
    """按 10 章名册精确生成一件装备（锻造/图纸/Boss 掉落/商店主推）。

    装备名 = 名册名（确定性）；词条 = 系列固定词条（20 章 3.x）+ 按品质随机补足；
    橙装挂名册专属；需求用名册 req；套装归属 = 系列套装名（10 章五节）。
    品质词条数：白 0 / 蓝 2（固定+随机补足）/ 紫 3 / 橙 3 + 专属。
    affinity（20 章 4.3 锻造词条倾向）：攻击/防御/元素/机动——随机补足从倾向池抽。
    """
    r = C.EQUIP_ROSTER[rid]
    slot, lv, quality = r["slot"], r["lv"], r["quality"]
    weapon_type = r.get("weapon_type")
    stats = equip_stats(slot, lv, quality)
    # v156 装备分系：武器按 weapon_type、防具按名册 req 推导属性族（名册装备路径）
    if slot == "weapon":
        stats = equip_stats(slot, lv, quality, weapon_type=weapon_type)
    elif slot in ("helm", "armor", "legs", "boots"):
        _req = r.get("req") or {}
        _fam = ARMOR_FAMILY_ALIAS.get(next(iter(_req), ""), None)
        if _fam:
            stats = equip_stats(slot, lv, quality, armor_family=_fam)
    # v29 武器类型特色（名册武器同样吃类型风味）
    flavor = WEAPON_FLAVOR.get(weapon_type, {}) if slot == "weapon" else {}
    flavor_stats = {}
    if flavor:
        for fk, fv in flavor.items():
            if fk == "desc" or not isinstance(fv, (int, float)):
                continue
            if fk == "crit":
                stats["crit"] = round(stats.get("crit", 0) + fv, 3)
                flavor_stats["crit"] = fv
            elif fk == "spd_fix":
                stats["spd"] = stats.get("spd", 0) + int(fv)
                flavor_stats["spd"] = int(fv)
            elif fk == "hp_fix":
                stats["hp"] = stats.get("hp", 0) + int(fv)
                flavor_stats["hp"] = int(fv)
            else:
                add = int(stats.get(fk, 0) * fv)
                stats[fk] = stats.get(fk, 0) + add
                flavor_stats[fk] = add
    # 词条：系列固定 + 随机补足到品质标准数（蓝 2 / 紫 3 / 橙 3）
    fixed = fixed_affixes(r["name"])
    # v184：条数规则走框架 count_for（橙装 [3,4] + 20% 命中上界；白/绿/未声明 → 0 条，
    # 与旧「target_n 字面表 + orange 20% 掷」同随机流：仅列表档位消费一次 random）。
    target_n = count_for({"blue": 2, "purple": 3, "orange": [3, 4]}, quality,
                         extra_chance=0.20, rng=random)
    pool = [a for a in AFFIX_POOL_BY_QUALITY.get(quality, AFFIX_POOL_BY_QUALITY["orange"])
            if a not in fixed]
    want_kind = "attack" if slot == "weapon" else "defense"
    pool = [a for a in pool if AFFIXES[a]["kind"] == want_kind]
    # 20 章 4.3：词条倾向 → 倾向池直接作为候选（过滤部位类型 + 固定词条）
    # 比品质随机池宽（如蓝装也能出元素词条），玩家主动指定合理
    if affinity:
        aff_pool = C.AFFIX_AFFINITY_POOLS.get(affinity, [])
        aff_pool = [a for a in aff_pool
                    if AFFIXES[a]["kind"] == want_kind and a not in fixed]
        if aff_pool:
            pool = aff_pool
    # v184：挂载形状走框架 draw_slots —— 固定（系列锚点，最多 1 条）在前、去重、
    # 随机补足到 target_n、池子不足给尽；随机部分等概率不放回（内部 rng.sample，
    # 与旧 `random.sample(pool, min(random_n, len(pool)))` 同随机流同结果）。
    affix_ids = draw_slots(pool, target_n, fixed=fixed, rng=random)
    for k, v in stat_affix_stats(affix_ids, slot, lv).items():
        if k in C.PCT_STATS:
            stats[k] = round(stats.get(k, 0) + v, 4)
        else:
            stats[k] = stats.get(k, 0) + int(v)
    # v125：名册专属 stat 型效果并入 stats（生成处折算，防 engine/battle 双算）
    if r.get("legendary"):
        _merge_legendary_stats(stats, r["legendary"], slot, lv)
    equip = {
        "name": r["name"],
        "slot": slot,
        "quality": quality,
        "lv": lv,
        "weapon_type": weapon_type if slot == "weapon" else None,
        "stats": stats,
        "price": int(equip_value(stats) * (3 + lv * 0.5) * QUALITY[quality]["mult"]),
        "req": dict(r.get("req") or {}),
        "series": r["series"],
    }
    # v180E 阶段4 fix：weapon_effect/we_data 从名册带进装备实例（此前丢失导致
    # 特效装备实际不触发——generate_roster_equip 只带 legendary/set/desc 漏了武器特效）
    if r.get("weapon_effect"):
        equip["weapon_effect"] = r["weapon_effect"]
        if r.get("we_data"):
            equip["we_data"] = dict(r["we_data"])
    if flavor_stats:
        equip["flavor"] = flavor_stats
    if affix_ids:
        equip["affixes"] = affix_ids
    if r.get("legendary"):
        equip["legendary"] = r["legendary"]
    # 阶段八：名册装备挂系列套装（v104 修复 P1：白装成员同样挂 set——
    # 橡木套 15 件中 11 件白装此前无 set，新手凑不齐 2 件效果）
    # v130.2c：优先名册显式 set 字段（资源联动套装=套装全名，非系列映射）
    if r.get("set"):
        equip["set"] = r["set"]
    elif r["series"] in SERIES_SETS:
        equip["set"] = SERIES_SETS[r["series"]]
    # v101.25g：名册装备描述（EQUIP_ROSTER 已注入 desc）
    if r.get("desc"):
        equip["desc"] = r["desc"]
    return equip

def build_monster(monster_def: tuple, map_obj: dict, lv_jitter: int = 0):
    """将地图怪物配置展开为完整怪物字典
    v58：应用 MONSTER_MODS 个体修正（同 role 同等级不同怪数值错开）
    v101.25c：lv_jitter>0 时普通怪等级 ±jitter 随机（同图同怪等级有波动，
    鱼鱼抓"橡木平原写 1-3 级结果只有 1 级史莱姆"）——精英/Boss 不参与波动。
    v130.8 意见#32：野外普通怪波动增强为 ±2（±1 感知弱），保底 Lv.1 不变。"""
    mid, name, role, lv, skills, drops = monster_def
    # 等级波动（仅普通怪，保底 Lv.1）
    if lv_jitter > 0 and role not in ("elite", "boss"):
        lv = max(1, lv + random.randint(-lv_jitter, lv_jitter))
    stats = monster_stats(lv, role, area=map_obj.get("area"))
    mod = C.MONSTER_MODS.get(mid, {})
    if mod:
        for k, mult in (("hp", "hp_mult"), ("atk", "atk_mult"), ("def", "def_mult"),
                        ("matk", "matk_mult"), ("mdef", "mdef_mult"), ("spd", "spd_mult")):
            if mult in mod:
                stats[k] = max(1, int(stats[k] * mod[mult]))
    # v131 野外首领/精英难度分档（FIELD_TIER_MULT，2026-08-27 鱼鱼拍板）：
    #   野外战斗无组队血量缩放 → 野外精英（蓝+5 单刷 20~35 轮）/ 野外 Boss（蓝+5 单刷 45~80 轮可过）
    #   副本（area=instance）不消费本表（副本 Boss 走 instances.hp_mult）；与 MONSTER_MODS 叠乘。
    if role in ("elite", "boss") and map_obj.get("area") != "instance":
        for _cap, _mult in FIELD_TIER_MULT.get(role, ()):
            if lv <= _cap:
                stats["hp"] = max(1, int(stats["hp"] * _mult))
                break
    is_boss = role == "boss"
    is_elite = role == "elite"
    # v27b 多对多站位引擎：按 role 推导站位层/射程（§9.3 数据层规格）
    # v2 审计（P2）：boss 也计入后排——caster/healer/boss → rank 2，其余（普通/精英物理近战）→ 1
    # v173.6 站位数据化（鱼鱼拍板 2026-09-04）：monster_mods 可配 rank/reach 覆盖
    #   role 推导（如近战 Boss 站前排、远程小怪站后排、长射程弓手）——不改 6 元组格式。
    rank = int(mod.get("rank", 2 if role in ("caster", "healer", "boss") else 1))
    reach = int(mod.get("reach", rank))  # 缺省 reach = rank
    return {
        "id": mid,
        "uid": "e_{}-{}".format(mid, lv),  # 确定性 uid（名字+序号，不引入随机）
        "name": name,
        "lv": lv,
        "role": role,
        "rank": rank,             # v27b 站位层（caster/healer/boss → 2，其余 → 1）
        "reach": reach,           # v27b 攻击范围（同 rank）
        "defending": False,       # v27b 本刻防御
        "charging": None,         # v27b 蓄力状态
        "hp": stats["hp"],
        "max_hp": stats["hp"],
        "atk": stats["atk"],
        "def": stats["def"],
        "matk": stats["matk"],
        "mdef": stats["mdef"],
        "spd": stats["spd"],
        "exp": monster_exp(lv, role),
        "gold": monster_gold(lv, role),
        "skills": skills,
        "drops": drops,
        "map": map_obj["name"],
        "map_area": map_obj.get("area", map_obj["id"]),
        "is_boss": is_boss,
        "is_elite": is_elite,
        "mech": mod.get("mech", ""),
        "mod": mod.get("desc", ""),
        # v176 敌方 AI 配置（MONSTER_MODS 可配 ai: {skill_chance/weights}；无则引擎回落全局——见 _enemy_turn）
        "ai": mod.get("ai") if mod.get("ai") else None,
        # v177 actor-agnostic：怪物防御/承伤扩展字段透传（引擎 _enemy_mitigate/_target_dodge_check 已支持读，
        # 此前 build_monster 未透传导致 MONSTER_MODS 配了不生效；on_taken 为受击钩子，见 _deal_damage）
        "dodge": float(mod.get("dodge", 0) or 0),
        "block": float(mod.get("block", 0) or 0),
        "phys_reduce": float(mod.get("phys_reduce", 0) or 0),
        "magic_reduce": float(mod.get("magic_reduce", 0) or 0),
        "elem_res": float(mod.get("elem_res", 0) or 0),
        "abyss_res": float(mod.get("abyss_res", 0) or 0),
        "on_taken": mod.get("on_taken"),
        # v177 actor 资源（Boss 改造）：怪物可配 resource_def（内联定义；引用 key 时语义同
        # EFFECT_RULES/job_guide 展示表——原 CORE_RESOURCES 注册表已随 v181.M-R2c 退役）
        "resource_def": mod.get("resource_def"),
        # v178 E5/E10：元素免疫/弱点表 + 阶段承伤乘区静态配置透传（引擎 _enemy_mitigate /
        # _boss_dmg_filter 已支持读 enemy dict 字段——此前不透传导致 MONSTER_MODS 配了不生效）
        "element_immune": list(mod.get("element_immune") or []),
        "element_weak": dict(mod.get("element_weak") or {}),
        # v181 批B（§9.2）：异常免疫名单透传 —— 引擎 effects.act_apply 前置查询点消费
        #（DOT 类状态 period.dir=damage 落地前查名单）。此前不在白名单 → MONSTER_MODS 配了
        # 也传不到实例（「接了引擎、数据仍进不来」的多通道坑）。
        "immune_dots": list(mod.get("immune_dots") or []),
        "dmg_taken_mult": float(mod.get("dmg_taken_mult", 1.0) or 1.0),
        # v180-B actor 化（怪扮职业/新 actor 扩展）：MONSTER_MODS 可配
        #   class_name（职业 id，如 cls_mu_shi——面板走玩家全公式，吃被动/资源/装备）
        #   equipment（装备 dict）、learned_skills（被动技能名列表）、race、skill_levels
        #   side（默认 enemy；玩家侧 actor 用 player）
        "class_name": mod.get("class_name"),
        "equipment": mod.get("equipment") or {},
        "learned_skills": mod.get("learned_skills"),
        "race": mod.get("race"),
        "skill_levels": mod.get("skill_levels"),
        "side": mod.get("side", "enemy"),
    }

# ============ v27b 多对多站位引擎 —— 怪物队伍构建（§8.1 / §9.3 数据层）============
# 说明：本函数不在函数内调用 random.random()——多怪与否的随机分支（60/40）
# 由命令层调用方在已 roll 完成后通过 `double` 参数传入（见契约 §8.1 优先方案）。
# 只做确定性派生，不改变既有 random 调用顺序，不破坏存量测试。


def _scale_monster(m: dict, mult: float, uid: str, name: str, rank: int, reach: int):
    """按倍率复制主怪的战斗属性，生成一只站位独立的新单位（沿用 skills/drops）。"""
    copy = dict(m)
    for k in ("hp", "max_hp", "atk", "def", "matk", "mdef", "spd"):
        if isinstance(copy.get(k), (int, float)):
            copy[k] = max(0, int(copy[k] * mult))
    copy["uid"] = uid
    copy["name"] = name
    copy["rank"] = rank
    copy["reach"] = reach
    copy["defending"] = False
    copy["charging"] = None
    # 爪牙/幼崽不属于首领/精英本体（身份/奖励判定走主怪）
    copy["is_boss"] = False
    copy["is_elite"] = False
    return copy


def build_monster_group(monster: dict, map_obj: dict, player: dict = None,
                        double: bool = False, scale_main: bool = True) -> list:
    """将单只怪物构建为敌方阵列（v27b §8.1）。

    参数:
      monster : build_monster 产出的单怪 dict（含 rank/reach/uid/buffs/stacks/defending/charging）
      map_obj : 地图对象（透传，仅用于产物一致）
      player  : 玩家 dict（透传，预留；当前不参与派生）
      double  : 仅对普通怪生效的分支开关——True 生成"主怪 + 幼崽"双只，False 单只。
                （60/40 随机由命令层 roll 完后再传入；本函数不引入随机）
      scale_main : 多怪场景（双只/精英爪牙/Boss 爪牙）是否把主怪战斗属性 ×0.7（契约 §8.1
                "每只=原单怪×0.7，副怪相对主怪×0.6"，否则主怪×1.0 总强度达 1.5-2.0 倍）。
                仅多怪分支生效，单只场景不缩放。世界 Boss 由事件配置数值 → 调用方传 False。

    返回: list[dict] 敌方阵列单位列表（按站位可含多只）。
    """
    is_boss = monster.get("is_boss", False)
    is_elite = monster.get("is_elite", False)
    base_uid = monster.get("uid", "e_0")
    base_name = monster.get("name", "怪物")

    # scale_main 时主怪战斗属性 ×0.7（新 dict，不改动传入 monster 的 uid/name/rank 等身份字段）
    main = monster
    if scale_main:
        main = _scale_main_copy(monster, 0.7)

    # 普通怪：单只 或 命令层传入 double=True → 主怪(rank1) + 副怪幼崽(rank2，×0.6)
    if not is_elite and not is_boss:
        if double:
            cub_uid = "{}-cub".format(base_uid)
            cub = _scale_monster(main, 0.6, cub_uid,
                                 "{}{}".format(base_name, "·幼崽"), 2, 2)
            return [main, cub]
        return [monster]

    # 精英：单只（v134.1 鱼鱼反馈"被精英小怪连击/群殴"——旧精英 rank1 + 1 爪牙 2 打 1，
    #   与 Boss 群殴设计混淆且蓝+5 标定(8~15轮)按单只算 → 精英改为单只不缩放，掉宝价值保留）
    if is_elite and not is_boss:
        return [monster]

    # Boss：Boss(rank 按 build_monster 已由 role 推导，caster/healer/boss → 2 其余 → 1) + 2 爪牙(rank1，×0.5)
    minions = []
    for i in (1, 2):
        min_uid = "{}-minion{}".format(base_uid, i)
        minions.append(_scale_monster(main, 0.5, min_uid,
                                      "{}的爪牙{}".format(base_name, i), 1, 1))
    return [main] + minions


def _scale_main_copy(m: dict, mult: float) -> dict:
    """复制主怪并把战斗属性 ×mult（保持 uid/name/rank/reach/身份/技能/掉落不变，仅改数值）。

    用于多怪场景（双只/精英/Boss 爪牙）下主怪 ×0.7（契约 §8.1），不原地修改调用方传入的
    monster dict，避免命令层引用不一致。数值属性仅当为 int/float 时缩放。"""
    copy = dict(m)
    for k in ("hp", "max_hp", "atk", "def", "matk", "mdef", "spd"):
        if isinstance(copy.get(k), (int, float)):
            copy[k] = max(0, int(copy[k] * mult))
    return copy




__all__ = [
    "make_blueprint", "roll_blueprint", "roll_drop", "roll_drop_equip",
    "generate_equip", "generate_roster_equip", "build_monster", "build_monster_group",
    "_merge_legendary_stats", "_eq_random_desc",
]
