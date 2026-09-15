# -*- coding: utf-8 -*-
"""B14 收口·W13：**legacy 再导出 / 读口**（`content/catalog_legacy.py`）。

背景
----
`game/content.py` 由 `from .data import *` 改成「包内门面再导出」后，`C` 公开面（基线 578 名）
会丢名。本模块专治「改后丢名里**有人在读**的那批」——逐个把名字从**包内已有的家**显式再导出：

    门面/模块属性 → 域读口（`content/{data,rules}/*.json`）→ 序/类型还原读口

铁律：**数值/文案/顺序/类型逐字不变，只换「取值来源」**。不造数据、不编值：
* 每个名字都由 `overnight/_w13_gen_legacy.py` 与宿主现表（旧 `game.content` = `game/data/*` 聚合）
  逐名深比较（值 / 类型 / dict 键序 / list-tuple 长度 / float repr）后**才**写入本文件；
* `_ORDER_*` 序声明由生成器从**宿主真源**机械导出（与 `overnight/b143_gen_facade.py` 同法），不手抄；
* 逐名台账（名 → 家 → 手段）见 `overnight/_w13_catalog_legacy.md`。

形状约定（与 `content/catalog_b143.py` 一致）
--------------------------------------------
* 域读不到（缺文件 / 坏 JSON / 空表）→ 容器回 `{}`/`[]`、标量回 `None`，**不抛**；
* 域在、但键集与 `_ORDER_*` 声明不符 → `raise`（防「源改了、门面静默改序」）；
* `missing_domains()` / `missing_names()` 供报告与门禁列出没解析到的名字。

缺口（本模块**不覆盖**，需建域或改读点）
----------------------------------------
见 `GAPS` / `overnight/_w13_catalog_legacy.md`
"""
from __future__ import annotations

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))


def _read_json(path, default):
    """读包内 JSON（缺文件 / 坏 JSON / 权限 → default，不抛；与 `content/tables.py` 同款）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _read_group(domain, sub, group, default=None):
    """取某域的**一个常量组**（缺组 → default）。"""
    dom = _read_json(os.path.join(_HERE, sub, "%s.json" % domain), None)
    if not isinstance(dom, dict):
        return default
    grp = dom.get(group)
    return grp if isinstance(grp, dict) else default


def _missing(tbl) -> bool:
    return not isinstance(tbl, dict) or not tbl


def _ordered(tbl, order, where):
    """按**声明序**排外层键（域是字典序，真源是插入序）。域读不到 → `{}` 不抛；
    域在但键集与声明不一致 → `raise`（防「源改了、门面静默改序」）。"""
    if _missing(tbl):
        return {}
    keys = list(order)
    if len(set(keys)) != len(keys):
        raise ValueError("catalog_legacy：%s 的序声明有重复键 —— 拒绝静默取首个" % where)
    have = set(tbl)
    miss = [k for k in keys if k not in have]
    extra = [k for k in have if k not in set(keys)]
    if miss or extra:
        raise ValueError(
            "catalog_legacy：%s 与序声明不一致（表缺 %d / 声明缺 %d）—— 请重跑 "
            "overnight/_w13_gen_legacy.py 同步序声明。表缺 %s … 未声明 %s …"
            % (where, len(miss), len(extra), miss[:5], sorted(extra)[:5]))
    return {k: tbl[k] for k in keys}


# ============================================================
# ① 包内模块家（直取再导出；对拍全等）
# ============================================================
from content.mech.element_data import ELEMENT_REACTIONS as ELEMENT_REACTIONS  # noqa: F401
from content.mech.class_data import MECH_CFG as MECH_CFG  # noqa: F401
from content.mech.we_data import WEAPON_EFFECT_DATA as WEAPON_EFFECT_DATA  # noqa: F401
from content.skills import SKILL_UP as SKILL_UP  # noqa: F401
from content.item_templates import TIPS as TIPS  # noqa: F401
from content.config import TRIAL_MIN_LV as TRIAL_MIN_LV  # noqa: F401
from content.config import WEEKLY_MIN_LV as WEEKLY_MIN_LV  # noqa: F401
from content.config import WEEKLY_PICK as WEEKLY_PICK  # noqa: F401
from content.instance_cmds import INVESTIGATE_BP_CHANCE as INVESTIGATE_BP_CHANCE  # noqa: F401
from content.instance_cmds import INVESTIGATE_COLLECT_CHANCE as INVESTIGATE_COLLECT_CHANCE  # noqa: F401
from content.instance_cmds import INVESTIGATE_RUNE_CHANCE as INVESTIGATE_RUNE_CHANCE  # noqa: F401
from content.mech.params import mech_cfg as mech_cfg  # noqa: F401  包内模块家（函数）
from content.tables import resolve_job as resolve_job  # noqa: F401  包内模块家（函数）

# ============================================================
# ② 包内域读口（content/rules/game_config.json 各组；对拍全等）
# ============================================================
# ---- game_config.battle_config（14 名）
BOSS_ATTACK_MULTS = _read_group("game_config", "rules", "battle_config", {}).get("BOSS_ATTACK_MULTS") or {}
CONTROL_MECHS = _read_group("game_config", "rules", "battle_config", {}).get("CONTROL_MECHS") or ()
DOT_ADAPT_DECAY_STEP = _read_group("game_config", "rules", "battle_config", {}).get("DOT_ADAPT_DECAY_STEP")
DOT_BLEED_DOUBLE_HP_PCT = _read_group("game_config", "rules", "battle_config", {}).get("DOT_BLEED_DOUBLE_HP_PCT")
DOT_DEFS = _read_group("game_config", "rules", "battle_config", {}).get("DOT_DEFS") or {}
DOT_RESIST_CAP = _read_group("game_config", "rules", "battle_config", {}).get("DOT_RESIST_CAP")
MECH_COMBO_STACKS = _read_group("game_config", "rules", "battle_config", {}).get("MECH_COMBO_STACKS") or ()
MECH_FROZEN_MULT = _read_group("game_config", "rules", "battle_config", {}).get("MECH_FROZEN_MULT") or {}
MECH_FULL_HP_CRIT = _read_group("game_config", "rules", "battle_config", {}).get("MECH_FULL_HP_CRIT") or ()
MECH_PROC_GROUPS = _read_group("game_config", "rules", "battle_config", {}).get("MECH_PROC_GROUPS") or {}
MECH_STACK_BONUS = _read_group("game_config", "rules", "battle_config", {}).get("MECH_STACK_BONUS") or {}
MECH_STACK_WHITELIST = _read_group("game_config", "rules", "battle_config", {}).get("MECH_STACK_WHITELIST") or ()
MECH_STAT_PASSIVES = _read_group("game_config", "rules", "battle_config", {}).get("MECH_STAT_PASSIVES") or {}
SKILL_CC_WHITELIST = _read_group("game_config", "rules", "battle_config", {}).get("SKILL_CC_WHITELIST") or ()

# ---- game_config.gather_pools（3 名）
GATHER_MAP_POOLS = _read_group("game_config", "rules", "gather_pools", {}).get("GATHER_MAP_POOLS") or {}
GATHER_COND_POOLS = _read_group("game_config", "rules", "gather_pools", {}).get("GATHER_COND_POOLS") or {}
MINING_DEEP_POOLS = _read_group("game_config", "rules", "gather_pools", {}).get("MINING_DEEP_POOLS") or {}

# ---- game_config.prof_config（2 名）
PRICE_BAND = _read_group("game_config", "rules", "prof_config", {}).get("PRICE_BAND") or {}
GATHER_MAP_MIN_LV = _read_group("game_config", "rules", "prof_config", {}).get("GATHER_MAP_MIN_LV") or []

# ---- game_config.item_tag_display（1 名）
ITEM_TAG_DISPLAY = _read_group("game_config", "rules", "item_tag_display", {}).get("ITEM_TAG_DISPLAY") or {}

# ---- game_config.mounts（2 名）
MOUNT_DROP_BOSS = _read_group("game_config", "rules", "mounts", {}).get("MOUNT_DROP_BOSS") or {}
MOUNT_DROP_ELITE = _read_group("game_config", "rules", "mounts", {}).get("MOUNT_DROP_ELITE") or {}

# ---- game_config.signin_config（1 名）
SIGNIN_CONFIG = _read_group("game_config", "rules", "signin_config", {}).get("SIGNIN_CONFIG") or {}

# ============================================================
# ③ 序/类型还原读口（域落盘字典序 → 真源插入序；注入键剥离/反折叠）
# ============================================================
# 商店限购配置 35 条（真源 game/data/shop_limit.py:39；域落盘是字典序 → 按真源插入序还原）
_ORDER_SHOP_LIMIT = ['item:i_stone_upgrade',
 'item:i_stone_refine',
 'item:i_stone_blessed',
 'item:i_def_potion',
 'item:i_spd_potion',
 'item:i_str_potion',
 'item:i_dragon_scale_potion',
 'item:i_shuang_bei_jin_bi_fu',
 'item:i_fu_huo_yu_mao',
 'item:i_holy_charm',
 'item:i_scroll_purify',
 'item:i_phoenix_tear',
 'item:i_life_elixir',
 'item:i_treat_holy',
 'item:i_treat_l',
 'item:i_mana_l',
 'item:i_scroll_escape',
 'item:i_scroll_teleport',
 'mat:mat_tie_kuang_shi',
 'mat:mat_jing_tie',
 'mat:mat_mi_yin',
 'mat:mat_jing_jin',
 'mat:mat_bing_jing',
 'equip:eq_pi_jia',
 'equip:eq_jiu_pi_xue',
 'equip:eq_xiang_mu_hu_tui',
 'equip:eq_mao_pi_mao',
 'equip:eq_xiang_mu_jie_zhi',
 'equip:eq_xiang_mu_xiang_lian',
 'equip:eq_bai_lu_pi_mao',
 'equip:eq_bai_lu_xiong_jia',
 'equip:eq_bai_lu_hu_tui',
 'equip:eq_bai_lu_pi_xue',
 'equip:eq_bai_lu_zhi_jie',
 'equip:eq_bai_lu_diao_zhu']
from content.shop_stock import SHOP_LIMIT as _SHOP_LIMIT_RAW  # noqa: E402
SHOP_LIMIT = _ordered(_SHOP_LIMIT_RAW, _ORDER_SHOP_LIMIT, "shop_stock.SHOP_LIMIT")

# 职业速查 7 条（真源 game/data/job_guide.py:172；域落盘字典序 + 导出器注入 `aliases`/`extra_resources`
# → 剥注入键后按真源插入序还原）
_ORDER_JOB_GUIDE = ['cls_zhan_shi', 'cls_fa_shi', 'cls_you_xia', 'cls_mu_shi', 'cls_ci_ke', 'cls_wu_seng', 'cls_shi_ren']
from content.tables import JOB_GUIDE as _JOB_GUIDE_RAW  # noqa: E402
_JOB_GUIDE_STRIPPED = {_cid: {_k: _v for _k, _v in _e.items()
                       if _k not in ("aliases", "extra_resources")}
                       for _cid, _e in _JOB_GUIDE_RAW.items()}
JOB_GUIDE = _ordered(_JOB_GUIDE_STRIPPED, _ORDER_JOB_GUIDE, "content.tables.JOB_GUIDE")

# 职业查询别名 44 条（真源 game/data/job_guide.py:180 JOB_ALIASES；导出器把它折叠进
# 每职业的 `aliases` 列表 → 反折叠回 `{查询名: 职业 id}` 并按真源插入序还原）
_ORDER_JOB_ALIASES = ['狂战士',
 '盾卫士',
 '狂战统领',
 '坚盾卫士',
 '战争领主',
 '坚城统帅',
 '元素使',
 '奥术学者',
 '元素术士',
 '奥术大师',
 '元素贤者',
 '奥秘主宰',
 '森语者',
 '风行者',
 '自然守望者',
 '疾风射手',
 '万木之灵',
 '狂风之猎',
 '神谕者',
 '死灵祭司',
 '大主教',
 '亡魂引渡者',
 '圣光先知',
 '黯灵君主',
 '影舞者',
 '毒刃者',
 '暗影之刃',
 '淬毒师',
 '无影之刃',
 '蚀骨者',
 '格斗士',
 '磐石行者',
 '拳术师',
 '铁壁行者',
 '破晓者',
 '不破之壁',
 '咏叹者',
 '挽歌者',
 '晨曦歌者',
 '安魂歌者',
 '天籁颂者',
 '镇魂挽者',
 '歌者',
 '歌者线']
_JOB_ALIASES_FOLDED = {}
for _cid, _e in _JOB_GUIDE_RAW.items():
    for _a in (_e.get("aliases") or []):
        _JOB_ALIASES_FOLDED.setdefault(_a, _cid)
JOB_ALIASES = _ordered(_JOB_ALIASES_FOLDED, _ORDER_JOB_ALIASES, "game/data/job_guide.py:JOB_ALIASES")

# 次要资源（真源 game/data/job_guide.py:58 EXTRA_RESOURCES；导出器把 EXTRA_RESOURCES +
# EXTRA_RESOURCE_GUIDE 合并成每职业的 `extra_resources` 列表 → 反折叠回 `{职业: [资源 key]}`）
EXTRA_RESOURCES = {_cid: [_e2["key"] for _e2 in (_e.get("extra_resources") or [])]
                   for _cid, _e in _JOB_GUIDE_RAW.items() if _e.get("extra_resources")}

# 次要资源展示元数据（真源 game/data/job_guide.py:99 EXTRA_RESOURCE_GUIDE；被导出器并进
# 每职业 `extra_resources` 的每条（多了 `key`）→ 反折叠回 `{资源 key: {name,max,desc}}`）
EXTRA_RESOURCE_GUIDE = {}
for _cid, _e in _JOB_GUIDE_RAW.items():
    for _e2 in (_e.get("extra_resources") or []):
        EXTRA_RESOURCE_GUIDE[_e2["key"]] = {_k: _v for _k, _v in _e2.items()
                                            if _k != "key"}

# 基础七职业顺序（真源 game/data/job_guide.py `BASE_ORDER`；与包内 `tables.JOB_ORDER` 同值）
from content.tables import JOB_ORDER as BASE_ORDER  # noqa: E402

# 宝石名基底（真源 game/data/gems.py `GEM_BASE_NAME`；与包内 `GEM_ITEM_TYPE` 同值）
from content.catalog_rules import GEM_ITEM_TYPE as GEM_BASE_NAME  # noqa: E402

# 垂钓档位序（真源 game/data/__init__.py:30：`FISH_QUALITY_ORDER = QUALITY_ORDER`）
from content.catalog_b143 import QUALITY_ORDER as _QUALITY_ORDER  # noqa: E402
FISH_QUALITY_ORDER = _QUALITY_ORDER

# 冒险者收藏册 5 册（真源 game/data/collection_book.py:20；域每册被注入 `order`（列表序）
# → 剥掉后逐册全等，册序由 `books()` 按源列表序给出）
from content.collection import books as _collection_books  # noqa: E402
COLLECTION_BOOKS = [dict((_k, _v) for _k, _v in _b.items() if _k != "order")
                    for _b in _collection_books()]

# 野外王 8 条（真源 game/data/wild_king_data.py；域落盘字典序 → 按真源插入序还原）
_ORDER_WILD_KINGS = ['b_guard_cang_mang',
 'b_guard_ye_ge',
 'b_guard_jin_sui',
 'b_guard_lin_feng',
 'b_guard_shuang_ya',
 'b_guard_yan_yan',
 'b_guard_long_gu',
 'b_guard_lei_ting']
from content.wild_king import WILD_KINGS as _WILD_KINGS_RAW  # noqa: E402
WILD_KINGS = _ordered(_WILD_KINGS_RAW, _ORDER_WILD_KINGS, "content/wild_king.WILD_KINGS")

# 网状连通表 97 图（真源 game/data/_assembly.py 装配；= maps 域每图的 `links`，
# 无 links 的图不在真源表里；域按字典序落盘 → 按真源插入序还原）
_ORDER_SUBAREA_LINKS_INDEX = ['oak_plain',
 'white_deer_forest',
 'emerald_forest',
 'misty_swamp',
 'hill_mine',
 'harbor_docks',
 'silver_valley',
 'windmill_plain',
 'rockfall_gorge',
 'boar_ridge',
 'silver_wind_road',
 'silver_river',
 'gold_plain',
 'white_abbey',
 'ironshield_hills',
 'old_battlefield',
 'border_castle',
 'west_ridge_wilds',
 'dusk_ridge_road',
 'king_road',
 'dawn_cathedral',
 'knight_yard',
 'silverwood',
 'starlake',
 'moon_glade',
 'emerald_valley',
 'windvale',
 'moonshadow_wood',
 'ancient_tree',
 'frost_field',
 'forge_valley',
 'black_forest',
 'cinder_mountain',
 'frost_fang',
 'winter_lake',
 'permafrost_field',
 'frostwhisper_canyon',
 'cold_spine_snow_trail',
 'dragon_ridge_old_road',
 'dragon_ridge',
 'dragon_roost',
 'bone_wild',
 'ancient_battlefield',
 'storm_cliff',
 'redridge_plateau',
 'dragonsfall_valley',
 'dragonborn_valley_trail',
 'coral_reef',
 'sunset_isle',
 'storm_strait',
 'mermaid_bay',
 'mist_trench',
 'whale_domain',
 'shipwreck_graveyard',
 'storm_sea',
 'mist_tide_passage',
 'black_tide_strait',
 'fungus_forest',
 'deep_lake',
 'molten_abyss',
 'lava_bed',
 'dwarf_long_gallery',
 'abyss_altar',
 'sky_ladder_path',
 'cloud_sea',
 'storm_plateau',
 'rainbow_cloud',
 'starlight_terrace',
 'lost_library',
 'ember_corridor',
 'goblin_camp',
 'sea_cave',
 'deer_fort',
 'old_king_tomb',
 'secret_crypt',
 'holy_trial',
 'elven_ruins',
 'moon_temple',
 'sunken_ship',
 'siren_nest',
 'sea_god_temple',
 'deep_dragon_palace',
 'ash_temple',
 'frost_throne',
 'under_dragon',
 'gray_dwarf',
 'storm_throne',
 'abyss_throne',
 'abyss_gate',
 'dragon_tomb',
 'eye_of_storm',
 'cloud_sanctum',
 'rust_dock',
 'candle_crypt',
 'thunder_mine',
 'whirl_arena',
 'blacktide_opera']
_MAPS_DOM = _read_json(os.path.join(_HERE, "data", "maps.json"), {}) or {}
_LINKS_BUILT = {_mid: _e["links"] for _mid, _e in _MAPS_DOM.items()
                if isinstance(_e, dict) and isinstance(_e.get("links"), dict)}
SUBAREA_LINKS_INDEX = _ordered(_LINKS_BUILT, _ORDER_SUBAREA_LINKS_INDEX,
                               "data/maps.json:links")

# POI 挂载表 457 行（真源 game/data/pois.py；dungeon 行的自带定义 dict → 只留 id，
# 与 content/pois.py 的 `_MOUNTED` 同款归一；域按字典序落盘 → 按真源插入序还原）
_ORDER_SUBAREA_POIS = ['oak_town:oak_town_1',
 'white_deer:white_deer_1',
 'white_deer:white_deer_5',
 'ironharbor:ironharbor_1',
 'ironharbor:ironharbor_5',
 'dawn_city:dawn_city_3',
 'dawn_city:dawn_city_1',
 'moon_court:moon_court_1',
 'oak_plain:oak_plain_3',
 'white_deer_forest:white_deer_forest_3',
 'emerald_forest:emerald_forest_3',
 'misty_swamp:misty_swamp_3',
 'hill_mine:hill_mine_3',
 'silver_river:silver_river_2',
 'old_battlefield:old_battlefield_3',
 'dawn_cathedral:dawn_cathedral_3',
 'silverwood:silverwood_3',
 'starlake:starlake_3',
 'frost_field:frost_field_3',
 'cinder_mountain:cinder_mountain_3',
 'black_forest:black_forest_3',
 'dragon_ridge:dragon_ridge_3',
 'coral_reef:coral_reef_3',
 'molten_abyss:molten_abyss_3',
 'abyss_altar:abyss_altar_3',
 'silver_wind_road:silver_wind_road_1',
 'silver_wind_road:silver_wind_road_2',
 'west_ridge_wilds:west_ridge_wilds_1',
 'mist_tide_passage:mist_tide_passage_2',
 'dwarf_long_gallery:dwarf_long_gallery_2',
 'cold_spine_snow_trail:cold_spine_snow_trail_1',
 'sky_ladder_path:sky_ladder_path_3',
 'sky_ladder_path:sky_ladder_path_1',
 'dragon_ridge_old_road:dragon_ridge_old_road_3',
 'west_ridge_wilds:west_ridge_wilds_3',
 'oak_plain:oak_plain_1',
 'white_deer_forest:white_deer_forest_1',
 'white_deer_forest:white_deer_forest_2',
 'emerald_forest:emerald_forest_1',
 'misty_swamp:misty_swamp_2',
 'hill_mine:hill_mine_1',
 'hill_mine:hill_mine_2',
 'harbor_docks:harbor_docks_1',
 'harbor_docks:harbor_docks_2',
 'harbor_docks:harbor_docks_3',
 'silver_valley:silver_valley_1',
 'silver_valley:silver_valley_2',
 'silver_valley:silver_valley_3',
 'windmill_plain:windmill_plain_1',
 'windmill_plain:windmill_plain_2',
 'windmill_plain:windmill_plain_3',
 'rockfall_gorge:rockfall_gorge_1',
 'rockfall_gorge:rockfall_gorge_2',
 'rockfall_gorge:rockfall_gorge_3',
 'boar_ridge:boar_ridge_1',
 'boar_ridge:boar_ridge_2',
 'boar_ridge:boar_ridge_3',
 'dawn_cathedral:dawn_cathedral_1',
 'dawn_cathedral:dawn_cathedral_2',
 'gold_plain:gold_plain_1',
 'white_abbey:white_abbey_1',
 'white_abbey:white_abbey_2',
 'white_abbey:white_abbey_3',
 'border_castle:border_castle_1',
 'border_castle:border_castle_2',
 'border_castle:border_castle_3',
 'silver_river:silver_river_1',
 'silver_river:silver_river_3',
 'knight_yard:knight_yard_1',
 'knight_yard:knight_yard_2',
 'knight_yard:knight_yard_3',
 'king_road:king_road_1',
 'king_road:king_road_2',
 'king_road:king_road_3',
 'ironshield_hills:ironshield_hills_1',
 'ironshield_hills:ironshield_hills_2',
 'ironshield_hills:ironshield_hills_3',
 'old_battlefield:old_battlefield_1',
 'old_battlefield:old_battlefield_2',
 'silverwood:silverwood_1',
 'starlake:starlake_1',
 'ancient_tree:ancient_tree_1',
 'ancient_tree:ancient_tree_2',
 'moon_glade:moon_glade_1',
 'moon_glade:moon_glade_2',
 'moon_glade:moon_glade_3',
 'emerald_valley:emerald_valley_1',
 'emerald_valley:emerald_valley_2',
 'emerald_valley:emerald_valley_3',
 'windvale:windvale_1',
 'windvale:windvale_2',
 'windvale:windvale_3',
 'moonshadow_wood:moonshadow_wood_1',
 'moonshadow_wood:moonshadow_wood_2',
 'moonshadow_wood:moonshadow_wood_3',
 'forge_valley:forge_valley_1',
 'forge_valley:forge_valley_2',
 'forge_valley:forge_valley_3',
 'black_forest:black_forest_1',
 'black_forest:black_forest_2',
 'cinder_mountain:cinder_mountain_1',
 'cinder_mountain:cinder_mountain_2',
 'frost_fang:frost_fang_1',
 'frost_fang:frost_fang_2',
 'frost_fang:frost_fang_3',
 'winter_lake:winter_lake_1',
 'winter_lake:winter_lake_2',
 'winter_lake:winter_lake_3',
 'permafrost_field:permafrost_field_1',
 'permafrost_field:permafrost_field_3',
 'frostwhisper_canyon:frostwhisper_canyon_1',
 'frostwhisper_canyon:frostwhisper_canyon_2',
 'frostwhisper_canyon:frostwhisper_canyon_3',
 'dragon_ridge:dragon_ridge_2',
 'dragon_roost:dragon_roost_1',
 'dragon_roost:dragon_roost_2',
 'dragon_roost:dragon_roost_3',
 'ancient_battlefield:ancient_battlefield_1',
 'ancient_battlefield:ancient_battlefield_2',
 'bone_wild:bone_wild_1',
 'bone_wild:bone_wild_3',
 'storm_cliff:storm_cliff_1',
 'storm_cliff:storm_cliff_2',
 'storm_cliff:storm_cliff_3',
 'redridge_plateau:redridge_plateau_1',
 'redridge_plateau:redridge_plateau_2',
 'redridge_plateau:redridge_plateau_3',
 'dragonsfall_valley:dragonsfall_valley_1',
 'dragonsfall_valley:dragonsfall_valley_2',
 'dragonsfall_valley:dragonsfall_valley_3',
 'coral_reef:coral_reef_2',
 'sunset_isle:sunset_isle_1',
 'sunset_isle:sunset_isle_2',
 'sunset_isle:sunset_isle_3',
 'storm_strait:storm_strait_1',
 'storm_strait:storm_strait_2',
 'storm_strait:storm_strait_3',
 'mermaid_bay:mermaid_bay_1',
 'mermaid_bay:mermaid_bay_2',
 'mermaid_bay:mermaid_bay_3',
 'mist_trench:mist_trench_1',
 'mist_trench:mist_trench_2',
 'mist_trench:mist_trench_3',
 'whale_domain:whale_domain_1',
 'whale_domain:whale_domain_2',
 'whale_domain:whale_domain_3',
 'shipwreck_graveyard:shipwreck_graveyard_1',
 'shipwreck_graveyard:shipwreck_graveyard_2',
 'shipwreck_graveyard:shipwreck_graveyard_3',
 'storm_sea:storm_sea_1',
 'fungus_forest:fungus_forest_1',
 'fungus_forest:fungus_forest_2',
 'fungus_forest:fungus_forest_3',
 'deep_lake:deep_lake_1',
 'deep_lake:deep_lake_3',
 'molten_abyss:molten_abyss_2',
 'lava_bed:lava_bed_1',
 'lava_bed:lava_bed_2',
 'lava_bed:lava_bed_3',
 'abyss_altar:abyss_altar_1',
 'abyss_altar:abyss_altar_2',
 'cloud_sea:cloud_sea_1',
 'cloud_sea:cloud_sea_2',
 'cloud_sea:cloud_sea_3',
 'storm_plateau:storm_plateau_1',
 'storm_plateau:storm_plateau_2',
 'storm_plateau:storm_plateau_3',
 'rainbow_cloud:rainbow_cloud_1',
 'rainbow_cloud:rainbow_cloud_2',
 'rainbow_cloud:rainbow_cloud_3',
 'starlight_terrace:starlight_terrace_1',
 'starlight_terrace:starlight_terrace_2',
 'starlight_terrace:starlight_terrace_3',
 'west_ridge_wilds:west_ridge_wilds_2',
 'dusk_ridge_road:dusk_ridge_road_1',
 'dusk_ridge_road:dusk_ridge_road_3',
 'mist_tide_passage:mist_tide_passage_1',
 'mist_tide_passage:mist_tide_passage_3',
 'black_tide_strait:black_tide_strait_1',
 'black_tide_strait:black_tide_strait_2',
 'dwarf_long_gallery:dwarf_long_gallery_1',
 'dwarf_long_gallery:dwarf_long_gallery_3',
 'cold_spine_snow_trail:cold_spine_snow_trail_2',
 'cold_spine_snow_trail:cold_spine_snow_trail_3',
 'dragon_ridge_old_road:dragon_ridge_old_road_1',
 'dragonborn_valley_trail:dragonborn_valley_trail_1',
 'dragonborn_valley_trail:dragonborn_valley_trail_2',
 'dragonborn_valley_trail:dragonborn_valley_trail_3',
 'sky_ladder_path:sky_ladder_path_2',
 'oak_plain:oak_plain_2',
 'gold_plain:gold_plain_3',
 'gold_plain:gold_plain_2',
 'deep_lake:deep_lake_2',
 'silverwood:silverwood_2',
 'starlake:starlake_2',
 'emerald_forest:emerald_forest_2',
 'frost_field:frost_field_1',
 'frost_field:frost_field_2',
 'permafrost_field:permafrost_field_2',
 'dragon_ridge:dragon_ridge_1',
 'bone_wild:bone_wild_2',
 'coral_reef:coral_reef_1',
 'storm_sea:storm_sea_2',
 'misty_swamp:misty_swamp_1',
 'molten_abyss:molten_abyss_1',
 'oak_plain:oak_plain_4',
 'oak_plain:oak_plain_5',
 'oak_plain:oak_plain_6',
 'white_deer_forest:white_deer_forest_4',
 'white_deer_forest:white_deer_forest_5',
 'white_deer_forest:white_deer_forest_6',
 'emerald_forest:emerald_forest_4',
 'emerald_forest:emerald_forest_5',
 'emerald_forest:emerald_forest_6',
 'misty_swamp:misty_swamp_4',
 'misty_swamp:misty_swamp_5',
 'misty_swamp:misty_swamp_6',
 'hill_mine:hill_mine_4',
 'hill_mine:hill_mine_5',
 'hill_mine:hill_mine_6',
 'harbor_docks:harbor_docks_4',
 'harbor_docks:harbor_docks_5',
 'harbor_docks:harbor_docks_6',
 'silver_valley:silver_valley_4',
 'silver_valley:silver_valley_5',
 'silver_valley:silver_valley_6',
 'windmill_plain:windmill_plain_4',
 'windmill_plain:windmill_plain_5',
 'windmill_plain:windmill_plain_6',
 'rockfall_gorge:rockfall_gorge_4',
 'rockfall_gorge:rockfall_gorge_5',
 'rockfall_gorge:rockfall_gorge_6',
 'boar_ridge:boar_ridge_4',
 'boar_ridge:boar_ridge_5',
 'boar_ridge:boar_ridge_6',
 'silver_wind_road:silver_wind_road_3',
 'silver_wind_road:silver_wind_road_4',
 'silver_river:silver_river_4',
 'silver_river:silver_river_5',
 'silver_river:silver_river_6',
 'gold_plain:gold_plain_4',
 'gold_plain:gold_plain_5',
 'gold_plain:gold_plain_6',
 'white_abbey:white_abbey_4',
 'white_abbey:white_abbey_5',
 'white_abbey:white_abbey_6',
 'ironshield_hills:ironshield_hills_4',
 'ironshield_hills:ironshield_hills_5',
 'ironshield_hills:ironshield_hills_6',
 'old_battlefield:old_battlefield_4',
 'old_battlefield:old_battlefield_5',
 'old_battlefield:old_battlefield_6',
 'border_castle:border_castle_4',
 'border_castle:border_castle_5',
 'border_castle:border_castle_6',
 'west_ridge_wilds:west_ridge_wilds_4',
 'west_ridge_wilds:west_ridge_wilds_5',
 'west_ridge_wilds:west_ridge_wilds_6',
 'dusk_ridge_road:dusk_ridge_road_4',
 'dusk_ridge_road:dusk_ridge_road_5',
 'dusk_ridge_road:dusk_ridge_road_6',
 'king_road:king_road_4',
 'king_road:king_road_5',
 'king_road:king_road_6',
 'dawn_cathedral:dawn_cathedral_4',
 'dawn_cathedral:dawn_cathedral_5',
 'dawn_cathedral:dawn_cathedral_6',
 'knight_yard:knight_yard_4',
 'knight_yard:knight_yard_5',
 'knight_yard:knight_yard_6',
 'silverwood:silverwood_4',
 'silverwood:silverwood_5',
 'silverwood:silverwood_6',
 'starlake:starlake_4',
 'starlake:starlake_5',
 'moon_glade:moon_glade_4',
 'moon_glade:moon_glade_5',
 'moon_glade:moon_glade_6',
 'emerald_valley:emerald_valley_4',
 'emerald_valley:emerald_valley_5',
 'windvale:windvale_4',
 'windvale:windvale_5',
 'moonshadow_wood:moonshadow_wood_4',
 'moonshadow_wood:moonshadow_wood_5',
 'moonshadow_wood:moonshadow_wood_6',
 'ancient_tree:ancient_tree_4',
 'ancient_tree:ancient_tree_5',
 'frost_field:frost_field_4',
 'frost_field:frost_field_5',
 'frost_field:frost_field_6',
 'forge_valley:forge_valley_4',
 'forge_valley:forge_valley_5',
 'black_forest:black_forest_4',
 'black_forest:black_forest_5',
 'black_forest:black_forest_6',
 'cinder_mountain:cinder_mountain_4',
 'cinder_mountain:cinder_mountain_5',
 'frost_fang:frost_fang_4',
 'frost_fang:frost_fang_5',
 'winter_lake:winter_lake_4',
 'winter_lake:winter_lake_5',
 'permafrost_field:permafrost_field_4',
 'permafrost_field:permafrost_field_5',
 'permafrost_field:permafrost_field_6',
 'frostwhisper_canyon:frostwhisper_canyon_4',
 'frostwhisper_canyon:frostwhisper_canyon_5',
 'cold_spine_snow_trail:cold_spine_snow_trail_4',
 'cold_spine_snow_trail:cold_spine_snow_trail_5',
 'dragon_ridge_old_road:dragon_ridge_old_road_4',
 'dragon_ridge_old_road:dragon_ridge_old_road_5',
 'dragon_ridge_old_road:dragon_ridge_old_road_6',
 'dragon_ridge:dragon_ridge_4',
 'dragon_ridge:dragon_ridge_5',
 'dragon_ridge:dragon_ridge_6',
 'dragon_roost:dragon_roost_4',
 'dragon_roost:dragon_roost_5',
 'dragon_roost:dragon_roost_6',
 'bone_wild:bone_wild_4',
 'bone_wild:bone_wild_5',
 'bone_wild:bone_wild_6',
 'ancient_battlefield:ancient_battlefield_4',
 'ancient_battlefield:ancient_battlefield_5',
 'ancient_battlefield:ancient_battlefield_6',
 'storm_cliff:storm_cliff_4',
 'storm_cliff:storm_cliff_5',
 'storm_cliff:storm_cliff_6',
 'redridge_plateau:redridge_plateau_4',
 'redridge_plateau:redridge_plateau_5',
 'redridge_plateau:redridge_plateau_6',
 'dragonsfall_valley:dragonsfall_valley_4',
 'dragonsfall_valley:dragonsfall_valley_5',
 'dragonsfall_valley:dragonsfall_valley_6',
 'dragonborn_valley_trail:dragonborn_valley_trail_4',
 'dragonborn_valley_trail:dragonborn_valley_trail_5',
 'dragonborn_valley_trail:dragonborn_valley_trail_6',
 'coral_reef:coral_reef_4',
 'coral_reef:coral_reef_5',
 'coral_reef:coral_reef_6',
 'sunset_isle:sunset_isle_4',
 'sunset_isle:sunset_isle_5',
 'sunset_isle:sunset_isle_6',
 'storm_strait:storm_strait_4',
 'storm_strait:storm_strait_5',
 'storm_strait:storm_strait_6',
 'mermaid_bay:mermaid_bay_4',
 'mermaid_bay:mermaid_bay_5',
 'mermaid_bay:mermaid_bay_6',
 'mist_trench:mist_trench_4',
 'mist_trench:mist_trench_5',
 'mist_trench:mist_trench_6',
 'whale_domain:whale_domain_4',
 'whale_domain:whale_domain_5',
 'whale_domain:whale_domain_6',
 'shipwreck_graveyard:shipwreck_graveyard_4',
 'shipwreck_graveyard:shipwreck_graveyard_5',
 'shipwreck_graveyard:shipwreck_graveyard_6',
 'storm_sea:storm_sea_4',
 'storm_sea:storm_sea_5',
 'storm_sea:storm_sea_6',
 'mist_tide_passage:mist_tide_passage_4',
 'mist_tide_passage:mist_tide_passage_5',
 'mist_tide_passage:mist_tide_passage_6',
 'black_tide_strait:black_tide_strait_4',
 'black_tide_strait:black_tide_strait_5',
 'black_tide_strait:black_tide_strait_6',
 'fungus_forest:fungus_forest_4',
 'fungus_forest:fungus_forest_5',
 'fungus_forest:fungus_forest_6',
 'deep_lake:deep_lake_4',
 'deep_lake:deep_lake_5',
 'deep_lake:deep_lake_6',
 'molten_abyss:molten_abyss_4',
 'molten_abyss:molten_abyss_5',
 'molten_abyss:molten_abyss_6',
 'lava_bed:lava_bed_4',
 'lava_bed:lava_bed_5',
 'lava_bed:lava_bed_6',
 'dwarf_long_gallery:dwarf_long_gallery_4',
 'dwarf_long_gallery:dwarf_long_gallery_5',
 'dwarf_long_gallery:dwarf_long_gallery_6',
 'abyss_altar:abyss_altar_4',
 'abyss_altar:abyss_altar_5',
 'abyss_altar:abyss_altar_6',
 'sky_ladder_path:sky_ladder_path_4',
 'sky_ladder_path:sky_ladder_path_5',
 'sky_ladder_path:sky_ladder_path_6',
 'cloud_sea:cloud_sea_4',
 'cloud_sea:cloud_sea_5',
 'cloud_sea:cloud_sea_6',
 'storm_plateau:storm_plateau_4',
 'storm_plateau:storm_plateau_5',
 'storm_plateau:storm_plateau_6',
 'rainbow_cloud:rainbow_cloud_4',
 'rainbow_cloud:rainbow_cloud_5',
 'rainbow_cloud:rainbow_cloud_6',
 'starlight_terrace:starlight_terrace_4',
 'starlight_terrace:starlight_terrace_5',
 'starlight_terrace:starlight_terrace_6',
 'lost_library:lost_library_2',
 'lost_library:lost_library_3',
 'ember_corridor:ember_corridor_2',
 'ember_corridor:ember_corridor_3',
 'goblin_camp:goblin_camp_1',
 'goblin_camp:goblin_camp_2',
 'goblin_camp:goblin_camp_3',
 'sea_cave:sea_cave_1',
 'sea_cave:sea_cave_2',
 'old_king_tomb:old_king_tomb_1',
 'old_king_tomb:old_king_tomb_2',
 'old_king_tomb:old_king_tomb_3',
 'secret_crypt:secret_crypt_1',
 'secret_crypt:secret_crypt_2',
 'secret_crypt:secret_crypt_3',
 'elven_ruins:elven_ruins_1',
 'elven_ruins:elven_ruins_2',
 'ash_temple:ash_temple_1',
 'ash_temple:ash_temple_2',
 'ash_temple:ash_temple_3',
 'abyss_gate:abyss_gate_1',
 'abyss_gate:abyss_gate_2',
 'dragon_tomb:dragon_tomb_1',
 'dragon_tomb:dragon_tomb_2',
 'dragon_tomb:dragon_tomb_3',
 'deer_fort:deer_fort_1',
 'deer_fort:deer_fort_2',
 'deer_fort:deer_fort_3',
 'holy_trial:holy_trial_1',
 'holy_trial:holy_trial_2',
 'moon_temple:moon_temple_1',
 'moon_temple:moon_temple_2',
 'frost_throne:frost_throne_1',
 'frost_throne:frost_throne_2',
 'frost_throne:frost_throne_3',
 'storm_throne:storm_throne_1',
 'storm_throne:storm_throne_2',
 'sunken_ship:sunken_ship_1',
 'sunken_ship:sunken_ship_2',
 'sunken_ship:sunken_ship_3',
 'siren_nest:siren_nest_1',
 'siren_nest:siren_nest_2',
 'siren_nest:siren_nest_3',
 'sea_god_temple:sea_god_temple_1',
 'sea_god_temple:sea_god_temple_2',
 'sea_god_temple:sea_god_temple_3',
 'deep_dragon_palace:deep_dragon_palace_1',
 'deep_dragon_palace:deep_dragon_palace_2',
 'gray_dwarf:gray_dwarf_1',
 'gray_dwarf:gray_dwarf_2',
 'gray_dwarf:gray_dwarf_3',
 'under_dragon:under_dragon_1',
 'under_dragon:under_dragon_2',
 'eye_of_storm:eye_of_storm_1',
 'eye_of_storm:eye_of_storm_2',
 'abyss_throne:abyss_throne_1',
 'abyss_throne:abyss_throne_2',
 'cloud_sanctum:cloud_sanctum_1',
 'cloud_sanctum:cloud_sanctum_2']
_POIS_DOM = _read_json(os.path.join(_HERE, "data", "pois.json"), {}) or {}
SUBAREA_POIS = _ordered(
    {_k: [(_x["id"] if isinstance(_x, dict) else _x) for _x in (_r.get("pois") or [])]
     for _k, _r in _POIS_DOM.items()},
    _ORDER_SUBAREA_POIS, "data/pois.json")

# ============================================================
# ④ 台账（供报告 / 门禁）
# ============================================================
COVERED: tuple = ("BASE_ORDER", "BOSS_ATTACK_MULTS", "COLLECTION_BOOKS", "CONTROL_MECHS", "DOT_ADAPT_DECAY_STEP", "DOT_BLEED_DOUBLE_HP_PCT", "DOT_DEFS", "DOT_RESIST_CAP", "ELEMENT_REACTIONS", "EXTRA_RESOURCES", "EXTRA_RESOURCE_GUIDE", "FISH_QUALITY_ORDER", "GATHER_COND_POOLS", "GATHER_MAP_MIN_LV", "GATHER_MAP_POOLS", "GEM_BASE_NAME", "INVESTIGATE_BP_CHANCE", "INVESTIGATE_COLLECT_CHANCE", "INVESTIGATE_RUNE_CHANCE", "ITEM_TAG_DISPLAY", "JOB_ALIASES", "JOB_GUIDE", "MECH_CFG", "MECH_COMBO_STACKS", "MECH_FROZEN_MULT", "MECH_FULL_HP_CRIT", "MECH_PROC_GROUPS", "MECH_STACK_BONUS", "MECH_STACK_WHITELIST", "MECH_STAT_PASSIVES", "MINING_DEEP_POOLS", "MOUNT_DROP_BOSS", "MOUNT_DROP_ELITE", "PRICE_BAND", "SHOP_LIMIT", "SIGNIN_CONFIG", "SKILL_CC_WHITELIST", "SKILL_UP", "SUBAREA_LINKS_INDEX", "SUBAREA_POIS", "TIPS", "TRIAL_MIN_LV", "WEAPON_EFFECT_DATA", "WEEKLY_MIN_LV", "WEEKLY_PICK", "WILD_KINGS", "mech_cfg", "resolve_job")

#: 本模块**不覆盖**的丢名（包内无源 → 需建域或改读点；见报告「缺口」逐条）
GAPS: tuple = ("AFFIX_AFFINITY_POOLS", "AFFIX_KIND", "BRANCH_KEY_DISPLAY", "CLASS_SET_STAGES", "CLASS_SET_THEMES", "CORE_RESOURCE_GUIDE", "EXTRA_ALIASES", "FACTION_SHOP", "HIDDEN_ORDER", "HIDDEN_SUCCESSORS", "INSTANCE_BOSS_EQUIP_DROP", "QUEST_ADD", "QUEST_MAT", "REFINE_EXCLUSIVE_RECIPES", "SUBAREA_BY_MAP", "SUBAREA_INDEX", "SUBAREA_PROPS", "WILD_KING_CHEST_TIERS", "WILD_KING_GLOBAL_LIMIT", "WILD_KING_LIFETIME_SEC", "WILD_KING_LOOT_PRIORITY_SEC", "WILD_KING_MAPS", "WILD_KING_NO_KILL_EXTRA", "WILD_KING_PERIODS", "WILD_KING_PER_DAY_LIMIT", "WILD_KING_PER_PERIOD_LIMIT", "WILD_KING_PITY_PERIODS", "WILD_KING_SPAWN_HOURS", "affixes", "alchemy", "base_growth", "battle_config", "battle_rules", "builds", "calamity", "classes", "collection_book", "cooking", "dialogues", "dungeon_links", "dungeon_pois", "econ_config", "enhance", "equip_roster", "equipment", "formula_skeleton", "gather", "gather_map_min_lv", "gather_pools", "guild", "hidden_monsters", "honor_shop", "housing", "instance_investigation", "instance_stage_maps", "instances", "item_tag_display", "items", "job_guide", "merge_into", "mesh_rooms_east_abyss", "mesh_rooms_south", "mesh_rooms_west_north", "monster_mods", "monsters", "npcs", "poi_pools", "price_band", "prof_config", "props", "quest_add_v140", "quests", "races", "refine", "refine_exclusive", "set_bonus_data", "sets", "shop", "shop_limit", "signin_config", "skill_up", "skills", "stat_templates", "subareas", "tips", "titles", "trial_tower", "upgrade", "weapon_effect_data", "weekly_quests", "wild_king_data", "wild_npcs", "world")

#: 真源在宿主 `game/data/*`、包内既无门面也无域的名字（缺域 / 缺实现）
GAP_REASON: dict = {
    '宿主函数（包内无实现）': ['price_band', 'gather_map_min_lv', 'merge_into'],
    '宿主 data 子模块句柄（随 data 消失；实测无真读点）': ['affixes', 'alchemy', 'base_growth', 'battle_config', 'battle_rules', 'builds', 'calamity', 'classes', 'collection_book', 'cooking', 'dialogues', 'dungeon_links', 'dungeon_pois', 'econ_config', 'enhance', 'equip_roster', 'equipment', 'formula_skeleton', 'gather', 'gather_pools', 'guild', 'hidden_monsters', 'honor_shop', 'housing', 'instance_investigation', 'instance_stage_maps', 'instances', 'item_tag_display', 'items', 'job_guide', 'mesh_rooms_east_abyss', 'mesh_rooms_south', 'mesh_rooms_west_north', 'monster_mods', 'monsters', 'npcs', 'poi_pools', 'prof_config', 'props', 'quest_add_v140', 'quests', 'races', 'refine', 'refine_exclusive', 'set_bonus_data', 'sets', 'shop', 'shop_limit', 'signin_config', 'skill_up', 'skills', 'stat_templates', 'subareas', 'tips', 'titles', 'trial_tower', 'upgrade', 'weapon_effect_data', 'weekly_quests', 'wild_king_data', 'wild_npcs', 'world'],
    # ---- B15b 追加（2026-09-14 · 只追加，不改上面两格的既有取值）----
    # 上面『宿主函数（包内无实现）』那三个名 + `GAPS` 里的 `REFINE_EXCLUSIVE_RECIPES` **已进包**：
    #   price_band / gather_map_min_lv → `content/prof_config.py`（逐字端口；常量走 content/config.py）
    #   merge_into                     → `content/refine_exclusive.py`（逐字端口；常量走 catalog_items）
    #   三门面再导出由 `content/catalog_rules.py` 尾部长尾门面负责 ⇒ 宿主 `C.<名>` 自动收回，宿主零改动。
    #   `REFINE_EXCLUSIVE_RECIPES` 的域 = `content/rules/game_config.json` 新组 `refine_exclusive`
    #   （由 `overnight/b15b_port_domain.py` 从备份真源 dump，非手抄）。
    # 故 `GAPS` / 上面那格是**历史台账**，勿再按「缺口」派活；等价性证据见 `overnight/W-B15b.md`。
    'B15b 已进包（历史名，勿再按缺口处理）': ['price_band', 'gather_map_min_lv', 'merge_into', 'REFINE_EXCLUSIVE_RECIPES'],
}


def missing_domains() -> list:
    """本模块**读不到**的域（缺文件 / 坏 JSON / 空表）—— 空 = 全部读通。"""
    out = []
    for grp in ("battle_config", "gather_pools", "prof_config", "item_tag_display",
                "mounts", "signin_config"):
        if not _read_group("game_config", "rules", grp, None):
            out.append("rules/game_config.json:%s" % grp)
    for sub, dom in (("data", "maps"), ("data", "pois")):
        if not _read_json(os.path.join(_HERE, sub, "%s.json" % dom), None):
            out.append("%s/%s.json" % (sub, dom))
    return out


def missing_names() -> list:
    """本模块**声明要导出、但取值解析不到**的名字（容器空 / 标量为 None）。"""
    out = []
    for n in __all__:
        v = globals().get(n)
        if v is None or (isinstance(v, (dict, list, tuple)) and not v):
            out.append(n)
    return out


__all__ = [
    "BASE_ORDER",
    "BOSS_ATTACK_MULTS",
    "COLLECTION_BOOKS",
    "CONTROL_MECHS",
    "DOT_ADAPT_DECAY_STEP",
    "DOT_BLEED_DOUBLE_HP_PCT",
    "DOT_DEFS",
    "DOT_RESIST_CAP",
    "ELEMENT_REACTIONS",
    "EXTRA_RESOURCES",
    "EXTRA_RESOURCE_GUIDE",
    "FISH_QUALITY_ORDER",
    "GATHER_COND_POOLS",
    "GATHER_MAP_MIN_LV",
    "GATHER_MAP_POOLS",
    "GEM_BASE_NAME",
    "INVESTIGATE_BP_CHANCE",
    "INVESTIGATE_COLLECT_CHANCE",
    "INVESTIGATE_RUNE_CHANCE",
    "ITEM_TAG_DISPLAY",
    "JOB_ALIASES",
    "JOB_GUIDE",
    "MECH_CFG",
    "MECH_COMBO_STACKS",
    "MECH_FROZEN_MULT",
    "MECH_FULL_HP_CRIT",
    "MECH_PROC_GROUPS",
    "MECH_STACK_BONUS",
    "MECH_STACK_WHITELIST",
    "MECH_STAT_PASSIVES",
    "MINING_DEEP_POOLS",
    "MOUNT_DROP_BOSS",
    "MOUNT_DROP_ELITE",
    "PRICE_BAND",
    "SHOP_LIMIT",
    "SIGNIN_CONFIG",
    "SKILL_CC_WHITELIST",
    "SKILL_UP",
    "SUBAREA_LINKS_INDEX",
    "SUBAREA_POIS",
    "TIPS",
    "TRIAL_MIN_LV",
    "WEAPON_EFFECT_DATA",
    "WEEKLY_MIN_LV",
    "WEEKLY_PICK",
    "WILD_KINGS",
    "mech_cfg",
    "resolve_job",
    "COVERED",
    "GAPS",
    "GAP_REASON",
    "missing_domains",
    "missing_names",
]
