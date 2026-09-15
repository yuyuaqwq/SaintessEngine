# -*- coding: utf-8 -*-
"""B14-3 收口门面（`content/catalog_b143.py`）—— 42 个「缺口名」的**包内等价物**。

背景
----
B14-3_BRIEF §1 列的 46 个缺口名（42 个数据名 + 派生名 `ALL_WILD` + `PERIOD_CN` + 文档占位
`X`/`XXX`）过去「包内既无门面也无域可依」＝ 删 `game/data` 的前置阻塞项。本线把它们逐个安家：

* 新域 6 个：`equipment` · `factions` · `enchant` · `poi_pools` · `chapters` · `gems`
  （`scripts/export_domains/b14_3_gaps.py`，表组形状「一条 = 一个源模块的常量组」）；
* 扩既有域 2 个：`guild` 加一行 `config`（`GUILD_CONFIG`）· `shop` 加一行 `honor_shop`
  （`HONOR_SHOP`，行内 `ranks` 装编号表）；
* 扩既有域 `game_config` 9 组常量：pets / maps / world / runes / affixes / fishing / pois /
  hidden_monsters / instance_investigation（判据见 `schemas/game_config.schema.json` 逐组说明）。
* 剩下 4 个不是数据缺口：`ALL_WILD`（派生式，真源 `game/core/wild.py:26`，包内已有
  `content/wild.py:_ALL_WILD()`）· `PERIOD_CN`（真源就是**包内** `content/time_weather.py:27`）·
  `X` / `XXX`（`content/economy_host.py:65` / `quests_flow.py:14` / `travel.py:15` 的**文档占位**，
  不是读点）。

本模块的纪律
------------
* 只读包内域文件（`content/{data,rules}/*.json`），**不 import 宿主**、不用 `_HostMod`。
* 域读不到（缺文件/坏 JSON/空表）→ 返回 `{}` **不抛**（空表会在门禁上以「不等」现形）；
  域在、但键集与序声明不符 → `raise`（防「源改了、门面静默改序」）。
* **两处类型还原**（不做 = 静默错值）：
  ① **外层键序**：域 JSON 是字典序，真源是插入序（`_ORDER_*` 由
     `overnight/b143_gen_facade.py` 从宿主源码导出，不手抄）；
  ② **int 键**：`GEM_TIERS` / `GEM_TIER_NAMES` / `RUNE_LEVEL_ROMAN` / `HONOR_SHOP` 的键源侧是
     int，JSON 只有字符串键 → 不还原 = `.get(3)` 恒 None、`sorted()` 乱序、`tier + 1` 取不到。

逐名台账（名 → 域 → 宿主真源）
------------------------------
| 名字 | 域（落点） | 宿主真源 |
|---|---|---|
| `QUALITY` `EQUIP_SLOTS` `WEAPON_FLAVOR` `QUALITY_ORDER` | `equipment`（data） | `game/data/equipment.py:13/3/127/41` |
| `FACTIONS` `FACTION_ORDER` `AREA_FACTION` `CHRONICLES` `REPUTATION_TIERS` | `factions`（data） | `game/data/factions.py:8/18/123/165/20` |
| `ENCHANT_RECIPES` `ENCHANT_SLOTS` `ENCHANT_CRIT_CHANCE` | `enchant`（data） | `game/data/enchant.py:9/3/134` |
| `WISH_POOL` `CAMPFIRE_FOOD_POOL` `HERB_POOL` | `poi_pools`（data） | `game/data/poi_pools.py:10/15/18` |
| `CHAPTER_PACK` | `chapters`（data） | `game/data/quest_add_v140.py:106` |
| `GEM_TIERS` `GEM_TIER_NAMES` `GEM_SOCKETS` `GEM_DRILL` `GEM_LEGENDARY_EFFECTS` `RUNE_REMOVE_COST` | `gems`（data） | `game/data/gems.py:7/19/25/33/42/40` |
| `PET_MAX_LEVEL` `PET_SKILL_UNLOCK_LV` | `game_config.pets` | `game/data/pets.py:190/192` |
| `MAP_CONNECTIONS` `LEGACY_MAP_ALIAS` `HIDDEN_MAP_UNLOCK` | `game_config.maps` | `game/data/maps.py:4224/4352/4343` |
| `WORLD_EVENT_POOL` `AUCTION_POOL` `WORLD_BOSS_POOL` | `game_config.world` | `game/data/world.py:8/110/123` |
| `RUNE_CRAFT_SHARDS` `RUNE_DROP` `RUNE_LEVEL_ROMAN` | `game_config.runes` | `game/data/runes.py:304/247/272` |
| `AFFIX_AFFINITY_CN` `AFFIX_POOL_BY_QUALITY` | `game_config.affixes` | `game/data/affixes.py:540/487` |
| `FISH_COLLECT` `FISH_EXP` | `game_config.fishing` | `game/data/fishing.py:193/83` |
| `POIS` | `game_config.pois` | `game/data/pois.py:9`（83 条**定义**；落点表在 `pois` 域） |
| `HIDDEN_MONSTERS` | `game_config.hidden_monsters` | `game/data/hidden_monsters.py:18` |
| `INVESTIGATE_COLLECT_SAMPLES` | `game_config.instance_investigation` | `game/data/instance_investigation.py:47` |
| `GUILD_CONFIG` | `guild.config` | `game/data/guild.py:3` |
| `HONOR_SHOP` | `shop.honor_shop.ranks` | `game/data/honor_shop.py:11`（**int 键**） |

**本文件是新增文件**（既有 `catalog_{space,items,quests,life,core}.py` 一行未改）—— 并行期
把「42 个名字」的交付面收在一个文件里，避免与 B14-2 八条线抢共享文件。谁切读点谁 import：
`from . import catalog_b143 as _b143`（或 `from .catalog_b143 import QUALITY, EQUIP_SLOTS`）。
"""
from __future__ import annotations

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_HERE, "data")
_RULES_DIR = os.path.join(_HERE, "rules")


def _read_json(path: str, default):
    """读包内 JSON（缺文件 / 坏 JSON → default，不抛；与 `content/tables.py::_read_json` 同款）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _read_domain(domain: str, sub: str, default):
    return _read_json(os.path.join(_HERE, sub, f"{domain}.json"), default)


def _read_group(domain: str, sub: str, group: str, default=None):
    """取某域里**一个常量组**（表组域的成员；缺组 → default）。"""
    dom = _read_domain(domain, sub, None)
    if not isinstance(dom, dict):
        return default
    grp = dom.get(group)
    return grp if isinstance(grp, dict) else default


def _read_path(domain: str, sub: str, path: str, default=None):
    """按 `a.b.c` 取域内嵌套键（用于 `shop.honor_shop.ranks` 这种保留行）。"""
    cur = _read_domain(domain, sub, None)
    for seg in path.split("."):
        if not isinstance(cur, dict) or seg not in cur:
            return default
        cur = cur[seg]
    return cur


def _missing(table) -> bool:
    return not isinstance(table, dict) or not table


def _int_keys(tbl) -> dict:
    """字符串键 → int 键（非整数键**原样保留**，不静默丢）。"""
    out: dict = {}
    for k, v in (tbl or {}).items():
        try:
            out[int(k)] = v
        except (TypeError, ValueError):
            out[k] = v
    return out


def _num_sorted(tbl) -> dict:
    """int 键表 → 按**数值升序**（JSON 是字典序：`"10" < "2"` ⇒ 不排序 = 阶位/等级乱序）。"""
    ints = {k: v for k, v in (tbl or {}).items() if isinstance(k, int) and not isinstance(k, bool)}
    rest = {k: v for k, v in (tbl or {}).items() if k not in ints}
    return {**{k: ints[k] for k in sorted(ints)}, **rest}


def _ordered(tbl, order, where: str):
    """按**声明序**排外层键（域是字典序，真源是插入序）。域读不到 → `{}` 不抛；
    域在但键集与声明不一致 → `raise`（防「源改了、门面静默改序」）。"""
    if _missing(tbl):
        return {}
    keys = list(order)
    if len(set(keys)) != len(keys):
        raise ValueError(f"catalog_b143：{where} 的序声明有重复键 —— 拒绝静默取首个")
    have = set(tbl)
    miss = [k for k in keys if k not in have]
    extra = [k for k in have if k not in set(keys)]
    if miss or extra:
        raise ValueError(
            "catalog_b143：%s 域与序声明不一致（域缺 %d / 声明缺 %d）—— 请重跑 "
            "overnight/b143_gen_facade.py 同步序声明。域缺 %s … 未声明 %s …"
            % (where, len(miss), len(extra), miss[:5], sorted(extra)[:5]))
    return {k: tbl[k] for k in keys}


def missing_domains() -> list:
    """本模块要用的域里，哪几张读不到（缺文件 / 坏 JSON / 空表）。"""
    out = []
    for name, sub, path in _REQUIRED:
        if not _read_path(name, sub, path, None):
            out.append(f"{sub}/{name}:{path}")
    return out


def _tupled_rows(rows):
    """`list[tuple]` 还原：源侧是 **tuple 的行**（如 `REPUTATION_TIERS` 的 `(下限, 档名)`），
    JSON 只有 array ⇒ 不还原 = 与真源 `type` 不等（B14 门禁 `cmp_val` 报「类型不同 list vs tuple」）。
    消费端 `for _t, _n in …` 对两种都成立，但**判等/入集合**需要 tuple。"""
    if not isinstance(rows, list):
        return rows
    return [tuple(x) if isinstance(x, list) else x for x in rows]


# ============================================================
# ① 序声明（真源插入序，由 overnight/b143_gen_facade.py 从宿主源码导出）
# ============================================================

_ORDER_MAP_CONNECTIONS = ["abyss_altar", "abyss_gate", "abyss_throne", "ancient_battlefield", "ancient_tree", "anvil_fort", "ash_temple", "aurora_town", "black_forest", "black_tide_strait", "boar_ridge", "bone_wild", "border_castle", "cinder_mountain", "cloud_sanctum", "cloud_sea", "cold_ridge", "cold_spine_snow_trail", "coral_reef", "dawn_cathedral", "dawn_city", "deep_dragon_palace", "deep_lake", "deep_tunnel", "deer_fort", "dragon_kin", "dragon_pass", "dragon_ridge", "dragon_ridge_old_road", "dragon_roost", "dragon_tomb", "dragonborn_valley_trail", "dragonsfall_valley", "dusk_ridge_road", "dwarf_long_gallery", "elven_ruins", "ember_camp", "ember_corridor", "emerald_forest", "emerald_valley", "eye_of_storm", "forge_valley", "frost_fang", "frost_field", "frost_horn", "frost_throne", "frostwhisper_canyon", "fungus_forest", "goblin_camp", "gold_plain", "gray_dwarf", "harbor_docks", "hill_mine", "holy_trial", "ironharbor", "ironshield_hills", "ironshield_town", "jade_port", "king_road", "knight_yard", "lava_bed", "lost_library", "maple_village", "mermaid_bay", "mist_tide_passage", "mist_trench", "misty_swamp", "molten_abyss", "moon_court", "moon_gate", "moon_glade", "moon_temple", "moonshadow_wood", "nameless_harbor", "white_deer_forest", "oak_plain", "oak_town", "old_battlefield", "old_king_tomb", "pearl_city", "permafrost_field", "rainbow_cloud", "redridge_plateau", "rockfall_gorge", "sea_cave", "sea_god_temple", "secret_crypt", "shell_town", "shipwreck_graveyard", "silver_brook", "silver_river", "silver_valley", "silver_wind_road", "silverwood", "siren_nest", "sky_ladder_path", "star_song", "starlake", "starlight_terrace", "storm_cliff", "storm_plateau", "storm_sea", "storm_strait", "storm_throne", "sunken_ship", "sunset_isle", "under_dragon", "under_market", "west_ridge_wilds", "whale_domain", "white_abbey", "white_deer", "wind_city", "windmill_plain", "windvale", "winter_lake"]
_ORDER_LEGACY_MAP_ALIAS = ["vila", "维拉镇", "白鹿城", "翡翠森林", "铁港城", "晨曦城", "月冠王庭", "霜角堡", "铁砧要塞", "龙脊山口", "橡木镇", "橡木草地", "橡木林"]
_ORDER_HIDDEN_MAP_UNLOCK = ["lost_library", "ember_corridor"]
_ORDER_RUNE_CRAFT_SHARDS = ["blue", "purple", "orange"]
_ORDER_RUNE_DROP = ["blue", "purple", "orange"]
_ORDER_RUNE_LEVEL_ROMAN = [1, 2, 3]
_ORDER_AFFIX_AFFINITY_CN = ["攻击", "输出", "防御", "防", "生存", "元素", "元素伤害", "机动", "速度", "灵活", "穿透", "破甲"]
_ORDER_AFFIX_POOL_BY_QUALITY = ["blue", "purple", "orange"]
_ORDER_FISH_EXP = ["white", "green", "blue", "purple", "orange"]
_ORDER_POIS = ["campfire", "shrine", "herb_patch", "loot_pile", "rune_stone", "fishing_spot", "note", "scenic_view", "ancient_tree_sight", "star_gazing", "merchant_camp", "ancient_altar", "bird_nest", "ice_sculpture", "dragon_bone", "shipwreck", "traveler_grave", "goblin_camp_0_chest_1", "goblin_camp_0_fire_1", "goblin_camp_1_chest_2", "goblin_camp_1_fire_2", "goblin_camp_2_corpse_1", "sea_cave_0_corpse_1", "sea_cave_0_trap_1", "sea_cave_1_chest_1", "old_king_tomb_0_rune_1", "old_king_tomb_0_trap_1", "old_king_tomb_1_rune_2", "old_king_tomb_2_mech_1", "old_king_tomb_2_chest_1", "secret_crypt_0_trap_1", "secret_crypt_0_rune_1", "secret_crypt_1_supply_1", "secret_crypt_2_chest_1", "elven_ruins_0_fire_1", "elven_ruins_1_mech_1", "elven_ruins_1_corpse_1", "ash_temple_0_fire_1", "ash_temple_1_supply_1", "ash_temple_1_trap_1", "ash_temple_2_rune_1", "abyss_gate_0_corpse_1", "abyss_gate_1_rune_1", "dragon_tomb_0_rune_1", "dragon_tomb_1_corpse_1", "dragon_tomb_2_mech_1", "deer_fort_0_mech_1", "deer_fort_0_corpse_1", "deer_fort_1_supply_1", "deer_fort_2_chest_1", "holy_trial_0_rune_1", "holy_trial_1_chest_1", "moon_temple_0_supply_1", "moon_temple_0_rune_1", "moon_temple_1_chest_1", "frost_throne_0_fire_1", "frost_throne_1_mech_1", "frost_throne_2_fire_2", "storm_throne_0_rune_1", "storm_throne_1_trap_1", "sunken_ship_0_corpse_1", "sunken_ship_1_chest_1", "sunken_ship_2_chest_2", "siren_nest_0_mech_1", "siren_nest_1_supply_1", "siren_nest_2_chest_1", "sea_god_temple_0_rune_1", "sea_god_temple_1_shell_1", "sea_god_temple_1_shell_2", "sea_god_temple_2_chest_1", "deep_dragon_palace_0_corpse_1", "deep_dragon_palace_1_chest_1", "gray_dwarf_0_corpse_1", "gray_dwarf_1_chest_1", "gray_dwarf_2_fire_1", "under_dragon_0_mech_1", "under_dragon_1_corpse_1", "eye_of_storm_0_rune_1", "eye_of_storm_1_chest_1", "abyss_throne_0_rune_1", "abyss_throne_1_trap_1", "cloud_sanctum_0_fire_1", "cloud_sanctum_1_mech_1"]
_ORDER_HIDDEN_MONSTERS = ["e_gold_slime", "e_white_stag", "e_glimmer_fish", "e_rune_golem", "e_shadow_stalker", "e_fortune_fox", "e_forest_wolf_king", "e_swamp_croc", "e_mine_troll", "e_abbey_guardian", "e_royal_guard", "e_moon_wolf", "e_elf_sentinel", "e_frost_bear", "e_ash_salamander", "e_dragon_hatchling", "e_storm_eagle", "e_sea_serpent", "e_siren", "e_deep_angler", "e_fungus_king", "e_lava_golem", "e_ghost_knight", "e_cloud_serpent", "e_iron_bull"]
_ORDER_QUALITY = ["white", "green", "blue", "purple", "orange"]
_ORDER_EQUIP_SLOTS = ["weapon", "helm", "armor", "legs", "boots", "ring", "necklace"]
_ORDER_WEAPON_FLAVOR = ["sword", "staff", "bow", "mace", "dagger", "fist", "spear", "shield"]
_ORDER_FACTIONS = ["guild", "kingdom", "church", "elves", "dwarves", "north", "dragons"]
_ORDER_AREA_FACTION = ["oak", "white_deer", "emerald", "misty", "goblin", "hill", "ironharbor", "seacave", "silver", "windmill", "deerfort", "maple", "dawn", "gold", "abbey", "oldtomb", "border", "silverriver", "crypt", "knight", "kingroad", "holytrial", "ironshield", "oldbattle", "moongate", "silverwood", "starlake", "mooncourt", "elvenruins", "ancienttree", "starsong", "moonglade", "emeraldvalley", "moontemple", "windvale", "moonshadow", "frosthorn", "frostfield", "anvilfort", "forgevalley", "blackforest", "cinder", "ashtemple", "abyssgate", "frostfang", "coldridge", "winterlake", "frostthrone", "aurora", "permafrost", "frostwhisper", "dragonpass", "dragonridge", "dragonroost", "ancientbattle", "dragontomb", "dragonkin", "bonewild", "stormcliff", "stormthrone", "redridge", "dragonsfall", "jade", "shell", "coral", "sunset", "stormstrait", "mermaid", "sunkenship", "siren", "nameless", "pearl", "misttrench", "whale", "shipwreck", "stormsea", "seagod", "deepdragon", "windcity", "cloudsea", "stormplateau", "eyeofstorm", "rainbow", "starlight", "cloudsanctum"]
_ORDER_ENCHANT_RECIPES = ["atk", "matk", "def", "mdef", "hp", "spd", "crit"]
_ORDER_ENCHANT_SLOTS = ["blue", "purple", "orange"]
_ORDER_GEM_TIERS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
_ORDER_GEM_TIER_NAMES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
_ORDER_GEM_SOCKETS = ["white", "green", "blue", "purple", "orange"]
_ORDER_GEM_DRILL = ["blue", "purple", "orange"]
_ORDER_GUILD_CONFIG = ["create_cost", "create_level", "sign_exp", "sign_contribute", "sign_gold", "task_exp", "task_contribute", "task_gold", "kill_task", "donate_items", "exp_bonus_per_level", "max_bonus", "vice_leader_level", "elite_level"]
_ORDER_HONOR_SHOP = [1, 2, 3, 4, 5, 6]


# ============================================================
# ② 42 个名字（域 → 值；含两处类型还原）
# ============================================================
_CFG = _read_domain("game_config", "rules", {}) or {}


def _grp(group: str) -> dict:
    """`game_config` 的一组常量（缺组 → `{}`）。"""
    g = _CFG.get(group)
    return g if isinstance(g, dict) else {}

PET_MAX_LEVEL = _grp("pets").get("PET_MAX_LEVEL")
PET_SKILL_UNLOCK_LV = _grp("pets").get("PET_SKILL_UNLOCK_LV")
MAP_CONNECTIONS = _ordered((_grp("maps").get("MAP_CONNECTIONS") if isinstance(_grp("maps").get("MAP_CONNECTIONS"), dict) else {}), _ORDER_MAP_CONNECTIONS, "game_config.maps")
LEGACY_MAP_ALIAS = _ordered((_grp("maps").get("LEGACY_MAP_ALIAS") if isinstance(_grp("maps").get("LEGACY_MAP_ALIAS"), dict) else {}), _ORDER_LEGACY_MAP_ALIAS, "game_config.maps")
HIDDEN_MAP_UNLOCK = _ordered((_grp("maps").get("HIDDEN_MAP_UNLOCK") if isinstance(_grp("maps").get("HIDDEN_MAP_UNLOCK"), dict) else {}), _ORDER_HIDDEN_MAP_UNLOCK, "game_config.maps")
WORLD_EVENT_POOL = _grp("world").get("WORLD_EVENT_POOL")
AUCTION_POOL = _grp("world").get("AUCTION_POOL")
WORLD_BOSS_POOL = _grp("world").get("WORLD_BOSS_POOL")
RUNE_CRAFT_SHARDS = _ordered((_grp("runes").get("RUNE_CRAFT_SHARDS") if isinstance(_grp("runes").get("RUNE_CRAFT_SHARDS"), dict) else {}), _ORDER_RUNE_CRAFT_SHARDS, "game_config.runes")
RUNE_DROP = _ordered((_grp("runes").get("RUNE_DROP") if isinstance(_grp("runes").get("RUNE_DROP"), dict) else {}), _ORDER_RUNE_DROP, "game_config.runes")
RUNE_LEVEL_ROMAN = _num_sorted(_ordered(_int_keys((_grp("runes").get("RUNE_LEVEL_ROMAN") if isinstance(_grp("runes").get("RUNE_LEVEL_ROMAN"), dict) else {})), _ORDER_RUNE_LEVEL_ROMAN, "game_config.runes"))
AFFIX_AFFINITY_CN = _ordered((_grp("affixes").get("AFFIX_AFFINITY_CN") if isinstance(_grp("affixes").get("AFFIX_AFFINITY_CN"), dict) else {}), _ORDER_AFFIX_AFFINITY_CN, "game_config.affixes")
AFFIX_POOL_BY_QUALITY = _ordered((_grp("affixes").get("AFFIX_POOL_BY_QUALITY") if isinstance(_grp("affixes").get("AFFIX_POOL_BY_QUALITY"), dict) else {}), _ORDER_AFFIX_POOL_BY_QUALITY, "game_config.affixes")
FISH_COLLECT = _grp("fishing").get("FISH_COLLECT")
FISH_EXP = _ordered((_grp("fishing").get("FISH_EXP") if isinstance(_grp("fishing").get("FISH_EXP"), dict) else {}), _ORDER_FISH_EXP, "game_config.fishing")
POIS = _ordered((_grp("pois").get("POIS") if isinstance(_grp("pois").get("POIS"), dict) else {}), _ORDER_POIS, "game_config.pois")
HIDDEN_MONSTERS = _ordered((_grp("hidden_monsters").get("HIDDEN_MONSTERS") if isinstance(_grp("hidden_monsters").get("HIDDEN_MONSTERS"), dict) else {}), _ORDER_HIDDEN_MONSTERS, "game_config.hidden_monsters")
INVESTIGATE_COLLECT_SAMPLES = _grp("instance_investigation").get("INVESTIGATE_COLLECT_SAMPLES")
QUALITY = _ordered((_read_group("equipment", "data", "equipment", {}).get("QUALITY") if isinstance(_read_group("equipment", "data", "equipment", {}).get("QUALITY"), dict) else {}), _ORDER_QUALITY, "equipment")
EQUIP_SLOTS = _ordered((_read_group("equipment", "data", "equipment", {}).get("EQUIP_SLOTS") if isinstance(_read_group("equipment", "data", "equipment", {}).get("EQUIP_SLOTS"), dict) else {}), _ORDER_EQUIP_SLOTS, "equipment")
WEAPON_FLAVOR = _ordered((_read_group("equipment", "data", "equipment", {}).get("WEAPON_FLAVOR") if isinstance(_read_group("equipment", "data", "equipment", {}).get("WEAPON_FLAVOR"), dict) else {}), _ORDER_WEAPON_FLAVOR, "equipment")
QUALITY_ORDER = _read_group("equipment", "data", "equipment", {}).get("QUALITY_ORDER")
FACTIONS = _ordered((_read_group("factions", "data", "factions", {}).get("FACTIONS") if isinstance(_read_group("factions", "data", "factions", {}).get("FACTIONS"), dict) else {}), _ORDER_FACTIONS, "factions")
FACTION_ORDER = _read_group("factions", "data", "factions", {}).get("FACTION_ORDER")
AREA_FACTION = _ordered((_read_group("factions", "data", "factions", {}).get("AREA_FACTION") if isinstance(_read_group("factions", "data", "factions", {}).get("AREA_FACTION"), dict) else {}), _ORDER_AREA_FACTION, "factions")
CHRONICLES = _read_group("factions", "data", "factions", {}).get("CHRONICLES")
REPUTATION_TIERS = _tupled_rows(_read_group("factions", "data", "factions", {}).get("REPUTATION_TIERS"))
ENCHANT_RECIPES = _ordered((_read_group("enchant", "data", "enchant", {}).get("ENCHANT_RECIPES") if isinstance(_read_group("enchant", "data", "enchant", {}).get("ENCHANT_RECIPES"), dict) else {}), _ORDER_ENCHANT_RECIPES, "enchant")
ENCHANT_SLOTS = _ordered((_read_group("enchant", "data", "enchant", {}).get("ENCHANT_SLOTS") if isinstance(_read_group("enchant", "data", "enchant", {}).get("ENCHANT_SLOTS"), dict) else {}), _ORDER_ENCHANT_SLOTS, "enchant")
ENCHANT_CRIT_CHANCE = _read_group("enchant", "data", "enchant", {}).get("ENCHANT_CRIT_CHANCE")
WISH_POOL = _read_group("poi_pools", "data", "poi_pools", {}).get("WISH_POOL")
CAMPFIRE_FOOD_POOL = _read_group("poi_pools", "data", "poi_pools", {}).get("CAMPFIRE_FOOD_POOL")
HERB_POOL = _read_group("poi_pools", "data", "poi_pools", {}).get("HERB_POOL")
CHAPTER_PACK = _read_group("chapters", "data", "quest_add_v140", {}).get("CHAPTER_PACK")
GEM_TIERS = _num_sorted(_ordered(_int_keys((_read_group("gems", "data", "gems", {}).get("GEM_TIERS") if isinstance(_read_group("gems", "data", "gems", {}).get("GEM_TIERS"), dict) else {})), _ORDER_GEM_TIERS, "gems"))
GEM_TIER_NAMES = _num_sorted(_ordered(_int_keys((_read_group("gems", "data", "gems", {}).get("GEM_TIER_NAMES") if isinstance(_read_group("gems", "data", "gems", {}).get("GEM_TIER_NAMES"), dict) else {})), _ORDER_GEM_TIER_NAMES, "gems"))
GEM_SOCKETS = _ordered((_read_group("gems", "data", "gems", {}).get("GEM_SOCKETS") if isinstance(_read_group("gems", "data", "gems", {}).get("GEM_SOCKETS"), dict) else {}), _ORDER_GEM_SOCKETS, "gems")
GEM_DRILL = _ordered((_read_group("gems", "data", "gems", {}).get("GEM_DRILL") if isinstance(_read_group("gems", "data", "gems", {}).get("GEM_DRILL"), dict) else {}), _ORDER_GEM_DRILL, "gems")
GEM_LEGENDARY_EFFECTS = _read_group("gems", "data", "gems", {}).get("GEM_LEGENDARY_EFFECTS")
RUNE_REMOVE_COST = _read_group("gems", "data", "gems", {}).get("RUNE_REMOVE_COST")
GUILD_CONFIG = _ordered((_read_group("guild", "data", "config", {}) if isinstance(_read_group("guild", "data", "config", {}), dict) else {}), _ORDER_GUILD_CONFIG, "guild")
HONOR_SHOP = _num_sorted(_ordered(_int_keys((_read_path("shop", "data", "honor_shop.ranks", {}) if isinstance(_read_path("shop", "data", "honor_shop.ranks", {}), dict) else {})), _ORDER_HONOR_SHOP, "shop"))


_REQUIRED = (
    ("game_config", "rules", "pets"), ("game_config", "rules", "maps"),
    ("game_config", "rules", "world"), ("game_config", "rules", "runes"),
    ("game_config", "rules", "affixes"), ("game_config", "rules", "fishing"),
    ("game_config", "rules", "pois"), ("game_config", "rules", "hidden_monsters"),
    ("game_config", "rules", "instance_investigation"),
    ("equipment", "data", "equipment"), ("factions", "data", "factions"),
    ("enchant", "data", "enchant"), ("poi_pools", "data", "poi_pools"),
    ("chapters", "data", "quest_add_v140"), ("gems", "data", "gems"),
    ("guild", "data", "config"), ("shop", "data", "honor_shop"),
)

# =============================================================================
# B14 收口追加（主 agent 2026-09-14）：equipment 域 5 键
#   `WT_CN`/`QUALITY_CN` → `content/index_build.py` 的 `weapon_types`/`quality` 索引表
#   `WEAPON_DIST`/`ARMOR_FAMILY`/`ARMOR_FAMILY_ALIAS` → `content/stats.py:103-105` 模块级取件
# =============================================================================
WT_CN = (_read_group("equipment", "data", "equipment", {}).get("WT_CN") or {})
QUALITY_CN = (_read_group("equipment", "data", "equipment", {}).get("QUALITY_CN") or {})
WEAPON_DIST = (_read_group("equipment", "data", "equipment", {}).get("WEAPON_DIST") or {})
ARMOR_FAMILY = (_read_group("equipment", "data", "equipment", {}).get("ARMOR_FAMILY") or {})
ARMOR_FAMILY_ALIAS = (_read_group("equipment", "data", "equipment", {}).get("ARMOR_FAMILY_ALIAS") or {})


# =============================================================================
# B14 收口追加（W12 世界/杂项线 2026-09-14）：`game_config` 的 `rules` / `mounts` 两组
#   `RULES` ← 真源 `game/data/rules.py:8`（20 条；list ⇒ JSON 数组自带序，不需要序声明）
#   `MOUNT_DROP_BOSS` / `MOUNT_DROP_ELITE` ← 真源 `game/data/mounts.py:71/70`
#     └ **序有行为**：`content/mounts.py:roll_mount_drop` 按 `.items()` 累计区间抽签 ⇒ 序声明 + 守卫
#   消费点：`content/rule_engine.py:_rules()` · `content/mounts.py:_tables()`
#   逐值 + 键序对拍（对**真源模块**，非 `C`：宿主聚合层未导出这两个名，
#   `b14_catalog_gate.py` 判「门面缺」）→ `overnight/_w12_precheck_sources.py` A/B/C/D 全 OK。
# =============================================================================
_ORDER_MOUNT_DROP_BOSS = ['mount_wolf', 'mount_ghost', 'mount_warhorse', 'mount_griffin']
_ORDER_MOUNT_DROP_ELITE = ['mount_steed']

RULES = _grp("rules").get("RULES")
MOUNT_DROP_BOSS = _ordered((_grp("mounts").get("MOUNT_DROP_BOSS") if isinstance(_grp("mounts").get("MOUNT_DROP_BOSS"), dict) else {}), _ORDER_MOUNT_DROP_BOSS, "game_config.mounts")
MOUNT_DROP_ELITE = _ordered((_grp("mounts").get("MOUNT_DROP_ELITE") if isinstance(_grp("mounts").get("MOUNT_DROP_ELITE"), dict) else {}), _ORDER_MOUNT_DROP_ELITE, "game_config.mounts")


__all__ = [
    "QUALITY", "EQUIP_SLOTS", "WEAPON_FLAVOR", "QUALITY_ORDER",
    "FACTIONS", "FACTION_ORDER", "AREA_FACTION", "CHRONICLES", "REPUTATION_TIERS",
    "ENCHANT_RECIPES", "ENCHANT_SLOTS", "ENCHANT_CRIT_CHANCE",
    "WISH_POOL", "CAMPFIRE_FOOD_POOL", "HERB_POOL",
    "CHAPTER_PACK",
    "GEM_TIERS", "GEM_TIER_NAMES", "GEM_SOCKETS", "GEM_DRILL",
    "GEM_LEGENDARY_EFFECTS", "RUNE_REMOVE_COST",
    "PET_MAX_LEVEL", "PET_SKILL_UNLOCK_LV",
    "MAP_CONNECTIONS", "LEGACY_MAP_ALIAS", "HIDDEN_MAP_UNLOCK",
    "WORLD_EVENT_POOL", "AUCTION_POOL", "WORLD_BOSS_POOL",
    "RUNE_CRAFT_SHARDS", "RUNE_DROP", "RUNE_LEVEL_ROMAN",
    "AFFIX_AFFINITY_CN", "AFFIX_POOL_BY_QUALITY",
    "FISH_COLLECT", "FISH_EXP", "POIS", "HIDDEN_MONSTERS",
    "INVESTIGATE_COLLECT_SAMPLES",
    "GUILD_CONFIG", "HONOR_SHOP",
    "missing_domains",
    # ---- B14 收口追加（主 agent 2026-09-14）----
    "WT_CN",
    "QUALITY_CN",
    "WEAPON_DIST",
    "ARMOR_FAMILY",
    "ARMOR_FAMILY_ALIAS",
    # ---- B14 收口追加（W12 世界/杂项线 2026-09-14）----
    "RULES",
    "MOUNT_DROP_BOSS",
    "MOUNT_DROP_ELITE",
]

