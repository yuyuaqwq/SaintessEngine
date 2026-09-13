# -*- coding: utf-8 -*-
"""包内「任务剧情族」内容聚合门面（`content/catalog_quests.py`）。

这是宿主聚合层 `C`（游戏仓 `game/content.py` → `from .data import *`）在本单元 21 个
数据名上的**包内等价物**：宿主 `game/data/` 74.7k 行删掉之后，包内模块照旧能读到这些名字。
只读**包内域数据**（`content/data|rules/<域>.json`），不 import 宿主任何模块（`game.*`）——
本模块的存在意义就是「宿主表删掉之后仍能活」。

覆盖的 21 个名字（== `overnight/B14_单元表.json` 的 `C-任务剧情族`）
------------------------------------------------------------------
    名字                 来源（包内域 / 规则）                                    还原规则
    -------------------  ------------------------------------------------------  ------------------------------------------
    NPCS                 `npcs` 域 `source=='town'`（362）                         去注入字段 `source`（+ 序表）
    WILD_NPCS            `npcs` 域 `source=='wild'`（47）                          去 `source`（+ 序表）
    HIDDEN_NPCS          `npcs` 域 `source=='hidden'`（22）                        去 `source`/`inst_stage`（+ 序表）
    DIALOGUES            `dialogues` 域全量（39 棵对话树）                          原样（+ 序表）
    ACHIEVEMENTS         `achievements` 域全量（119）                              原样，按序表还原成 list
    MAIN_QUESTS          `quests` 域 `source=='main'`（70）                        去 `source`（+ 序表）
    SIDE_QUESTS          `quests` 域 `source=='side'`（144）                       去 `source`（+ 序表）
    DAILY_QUESTS         `quests` 域 `source=='daily'`（24）                       去 `source`（+ 序表；键=name）
    EXPLORE_EVENTS       `events` 域 `source=='explore'`（100）                    去 `source`（+ 序表）
    EXPLORE_EGG_EVENTS   `events` 域 `source=='egg'`（46）                         去 `source`（+ 序表）
    MONSTER_SKILLS       `monsters` 域全量（330，怪技能表）                          原样（+ 序表）
    MONSTER_MODS         `monster_mods` 域全量（140）                              原样（+ 序表）
    ELITE_EQUIP_DROP     `monster_roster` 的 `elite_equip_drop`（20 条 → 18 个名）    {精英中文名: 装备 id}（同名同值去重 + 序表）
    TITLES               `titles` 域全量（68）                                     去注入字段 `seq`，按 `seq` 还原源序
    WEEKLY_QUESTS        `weekly_quests` 域全量（12）                              去 `seq`，按 `seq` 还原源序
    TRIAL_FLOORS         `trial_floors` 域全量（30）                               按 `floor` 1..30 还原源序
    TRIAL_DAILY_LIMIT    `rules/game_config.json` 的 `trial_tower`（3）            原样标量
    TRIAL_MAX_FLOOR      `rules/game_config.json` 的 `trial_tower`（30）           原样标量
    BUILDS               `rules/game_config.json` 的 `builds.BUILDS`（7 职业）      原样（域内层键序 = 源序，未丢）

**缺口（本单元做不到的 2 个名字，详见 `overnight/W-B14-C.md`）**：`HIDDEN_MONSTERS`、
`CHAPTER_PACK` —— 包内 66 域里没有等价数据源，见文件末尾 `PENDING_NAMES`。

⚠️ 为什么带「序表」（`_*_ORDER`，共 13 张 / 1,461 个键）
--------------------------------------------------------
包内域 JSON 的**外层键按导出契约字典序落盘**（宿主 `scripts/export_domains/_helpers.py:37
sort_table`，幂等优先），源迭代序（随机取 / 遍历 / 掉落序的语义）在域里没有落点。
宿主真源是一张张**有序**表（dict 字面量插入序 / list 顺序），门禁逐名比对**含键序**
（`b14_catalog_gate.py:82`），所以序必须显式记下来 —— I3（规划 §9.2）对此的口径是
「不许改迭代序，**除非显式记「单向派生」**」，本文件就是那条显式记录：
序表由 `overnight/_b14c_order_gen.py`（一次性取证工具，不进包）从宿主运行时表导出、
固化在此，导入期守卫 `_ordered()` 断言「域键集 == 序表键集」，漂移立刻 raise（不静默漏项）。

★ 长期解（登记给主 agent）：把序补回**域**里（导出器注入 `seq`/`order` —— 与 `titles` /
`weekly_quests` / `collection_books` / `exploration` 四个域的既有手法一致），本文件即可
缩成「按 seq 排序」。那属于宿主 `scripts/export_domains/*`（别线的文件，本单元禁改）+ 重新导出。

域来源与读者（真源 = 游戏仓；单向导出器 = 游戏仓 `scripts/`）
------------------------------------------------------------
    content/data/npcs.json          ← derive_npcs             431 = town 362 + wild 47 + hidden 22
    content/data/quests.json        ← derive_quests           238 = main 70 + side 144 + daily 24
    content/data/events.json        ← derive_events           146 = explore 100 + egg 46
    content/data/dialogues.json     ← derive_dialogues        39 棵对话树（键 = NPC id）
    content/data/achievements.json  ← derive_achievements     119
    content/data/titles.json        ← derive_titles           68（自带 seq）
    content/data/weekly_quests.json ← derive_weekly_quests    12（自带 seq）
    content/data/trial_floors.json  ← derive_trial_floors     30（floor 1..30）
    content/data/monsters.json      ← derive_monsters         330 怪技能（= 宿主 MONSTER_SKILLS）
    content/data/monster_mods.json  ← derive_monster_mods     140
    content/data/monster_roster.json← derive_monster_roster   380（elite_equip_drop 20 条）
    content/rules/game_config.json  ← derive_game_config      builds / trial_tower 两组常量

不改形状：本模块只做「取值 / 去注入字段 / 还原序 / 建表」，零默认值、零数值改写
（数值与文案全在域里）。
"""
from __future__ import annotations

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))          # <pkg>/content


def _read(sub: str, domain: str, default):
    """读包内 `content/<sub>/<domain>.json`（缺文件 / 坏 JSON → default，不抛）。"""
    try:
        with open(os.path.join(_HERE, sub, domain + ".json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                        # noqa: BLE001
        return default


def _drop(ent: dict, *keys) -> dict:
    """去掉导出期**注入**的字段（`source` / `inst_stage` / `seq`），其余字段顺序原样。

    注入字段在条目末尾，去掉它 = 还原宿主原条目（字段顺序也随之还原）。
    """
    if not isinstance(ent, dict):
        return ent
    return {k: v for k, v in ent.items() if k not in keys}


def _ordered(tbl: dict, order: tuple, where: str) -> dict:
    """域表 → 按**源迭代序**重排的 dict；键集不等 → raise（漂移防线，不许静默漏项）。"""
    got, want = set(tbl), set(order)
    if got != want:
        raise ValueError(
            "%s：域键集与序表不一致（域多 %s / 序表多 %s）—— 域或序表变了，"
            "请同步 content/catalog_quests.py 的 _*_ORDER（生成器 overnight/_b14c_order_gen.py）"
            % (where, sorted(got - want)[:5], sorted(want - got)[:5]))
    return {k: tbl[k] for k in order}


def _by_source(dom: dict, source: str, drop=("source",)) -> dict:
    """域表按注入字段 `source` 拆表（`derive_npcs` / `derive_quests` / `derive_events` 的逆运算）。"""
    return {k: _drop(v, *drop) for k, v in dom.items() if isinstance(v, dict)
            and v.get("source") == source}


# =============================================================================
# ① 序表（13 张 / 1,461 键；生成自宿主运行时表，见模块头注「为什么带序表」）
# =============================================================================
# npcs 域 source=='town'（362 项）
_NPCS_ORDER = (
    'npc_mayor', 'npc_blacksmith', 'npc_innkeeper', 'npc_guild_clerks', 'npc_baron',
    'npc_blacksmith2', 'npc_tavern_owner', 'npc_priest', 'npc_doctor', 'npc_guildmaster',
    'npc_citylord', 'npc_auctioneer', 'npc_bard', 'npc_oak_elder', 'npc_hunter_gray',
    'npc_inn_tess', 'npc_king', 'npc_pope', 'npc_cardinal', 'npc_knight_commander',
    'npc_saintess', 'npc_ironshield_mayor', 'npc_ironshield_smith', 'npc_ironshield_scout',
    'npc_abbess', 'npc_elf_queen', 'npc_elf_guardian', 'npc_elf_sage', 'npc_north_chief',
    'npc_garrison', 'npc_field_priest', 'npc_dwarf_elder', 'npc_rune_master',
    'npc_warrior_tutor', 'npc_mage_tutor', 'npc_ranger_tutor', 'npc_priest_tutor',
    'npc_assassin_tutor', 'npc_monk_tutor', 'npc_bard_tutor', 'npc_herb_master',
    'npc_mine_master', 'npc_fish_master', 'npc_cook_master', 'npc_alchemy_master',
    'npc_craft_master', 'npc_enhance_master', 'npc_aurora_mayor', 'npc_frost_blade',
    'npc_warm_stove', 'npc_harbor_master', 'npc_captain_maelian', 'npc_sea_gull_tim',
    'npc_pearl_lord', 'npc_coral_auctioneer', 'npc_old_whale', 'npc_ember_camp_leader',
    'npc_under_guide', 'npc_ember_merchant', 'npc_dragon_elder', 'npc_goblin_merchant',
    'npc_fallen_chief', 'npc_demon_priestess', 'npc_tavern_burnkettle', 'npc_wind_elder',
    'npc_elf_poet', 'npc_north_hunter', 'npc_pilgrim', 'npc_war_scholar', 'npc_druid_oakheart',
    'npc_eter', 'npc_spellblade_ghost', 'npc_caravan_leader', 'npc_border_patrol',
    'npc_old_sailor', 'npc_dwarf_engineer', 'npc_grave_keeper', 'npc_dragonborn_elder',
    'npc_silver_fisher', 'npc_silver_washer', 'npc_silver_apprentice', 'npc_silver_peddler',
    'npc_moongate_guard', 'npc_moongate_astronomer', 'npc_moongate_silk',
    'npc_starsong_bardling', 'npc_starsong_baker', 'npc_starsong_drunkard', 'npc_jade_docker',
    'npc_jade_carver', 'npc_jade_helmsman', 'npc_shell_picker', 'npc_shell_netter',
    'npc_shell_gatherer', 'npc_cold_hunter', 'npc_cold_herder', 'npc_cold_firekeeper',
    'npc_dragonkin_youth', 'npc_dragonkin_elder', 'npc_dragonkin_smith', 'npc_tunnel_miner',
    'npc_tunnel_lamp', 'npc_tunnel_carter', 'npc_under_trader', 'npc_under_guard',
    'npc_under_whisper', 'npc_maple_woodcutter', 'npc_deer_newsboy', 'npc_harbor_rope',
    'npc_harbor_fishwife', 'npc_harbor_watchman', 'npc_dawn_gardener', 'npc_dawn_squire',
    'npc_shield_watch', 'npc_elf_gardener', 'npc_elf_rabbit', 'npc_frost_hunter',
    'npc_frost_weaver', 'npc_anvil_brewer', 'npc_aurora_scribe', 'npc_pass_stationmaster',
    'npc_pearl_diver', 'npc_pearl_shuttler', 'npc_nameless_catwoman', 'npc_ember_cook',
    'npc_ember_scout', 'npc_wind_kitemaker', 'npc_road_peddler', 'npc_wild_herbalist',
    'npc_mist_fisher', 'npc_strait_ferryman', 'npc_gallery_mule', 'npc_snow_hunter',
    'npc_ridge_bonecollector', 'npc_valley_pilgrim', 'npc_sky_monk', 'npc_dusk_caravan',
    'npc_oak_shepherd', 'npc_deer_forester', 'npc_emerald_hunter', 'npc_swamp_fisher',
    'npc_mine_miner', 'npc_dock_foreman', 'npc_valley_fisher', 'npc_windmill_miller',
    'npc_gorge_stonecutter', 'npc_boar_hunter', 'npc_cathedral_deacon', 'npc_gold_farmchief',
    'npc_border_quartermaster', 'npc_river_ferryman', 'npc_knight_instructor',
    'npc_kingroad_gravekeeper', 'npc_hills_scout', 'npc_battlefield_veteran',
    'npc_silverwood_ranger', 'npc_moonglade_moonpriest', 'npc_emeraldvalley_deerherd',
    'npc_windvale_whisperer', 'npc_moonshadow_hunter', 'npc_frostfield_hunter',
    'npc_forge_miner', 'npc_frostfang_hunter', 'npc_winterlake_fisher',
    'npc_permafrost_sledder', 'npc_frostwhisper_mountaineer', 'npc_dragonridge_guide',
    'npc_dragonroost_dragonspeaker', 'npc_bonewild_scavenger', 'npc_stormcliff_watcher',
    'npc_redridge_dragonherd', 'npc_dragonsfall_scholar', 'npc_coral_pearldiver',
    'npc_sunset_islander', 'npc_stormstrait_navigator', 'npc_mermaidbay_fishergirl',
    'npc_misttrench_diver', 'npc_whale_watcher', 'npc_shipwreck_salvager',
    'npc_stormsea_observer', 'npc_fungus_farmer', 'npc_deeplake_fisher', 'npc_molten_scout',
    'npc_lavabed_miner', 'npc_abyssaltar_whisperer', 'npc_cloudsea_boatman',
    'npc_stormplateau_lightning', 'npc_rainbow_herder', 'npc_starlight_stargazer',
    'npc_oak_street_vendor', 'npc_oak_outskirts_farmer', 'npc_white_deer_gate_guard',
    'npc_ironharbor_gate_guard', 'npc_silver_brook_gate_guard', 'npc_maple_village_gate_guard',
    'npc_dawn_city_gate_guard', 'npc_ironshield_town_gate_guard', 'npc_moon_gate_gate_guard',
    'npc_moon_court_gate_guard', 'npc_star_song_gate_guard', 'npc_frost_horn_gate_guard',
    'npc_anvil_fort_gate_guard', 'npc_cold_ridge_gate_guard', 'npc_aurora_town_gate_guard',
    'npc_dragon_pass_gate_guard', 'npc_dragon_kin_gate_guard', 'npc_jade_port_gate_guard',
    'npc_shell_town_gate_guard', 'npc_nameless_harbor_gate_guard', 'npc_pearl_city_gate_guard',
    'npc_deep_tunnel_gate_guard', 'npc_under_market_gate_guard', 'npc_ember_camp_gate_guard',
    'npc_wind_city_gate_guard', 'npc_chrono_warden', 'npc_shadow_master', 'npc_dragon_veteran',
    'npc_astrologer', 'npc_wusheng_monk', 'npc_grave_watcher', 'npc_oak_candy',
    'npc_oak_novice', 'npc_oak_oldman', 'npc_oak_kid', 'npc_oak_clerk',
    'npc_oak_apprentice_smith', 'npc_oak_bellboy', 'npc_oak_herb_girl', 'npc_oak_vegwife',
    'npc_oak_farmer', 'npc_deer_guard', 'npc_deer_bard', 'npc_deer_scribe',
    'npc_deer_blacksmith_h', 'npc_deer_nun', 'npc_deer_drunk', 'npc_deer_nurse',
    'npc_deer_cook', 'npc_deer_enchanter', 'npc_deer_gatekeeper', 'npc_harbor_sailor',
    'npc_harbor_mule', 'npc_harbor_trader', 'npc_harbor_auction', 'npc_harbor_bartender',
    'npc_harbor_ledger', 'npc_harbor_miner_old', 'npc_harbor_clerk', 'npc_harbor_fisher',
    'npc_harbor_forge_app', 'npc_harbor_alchemist', 'npc_harbor_gate', 'npc_dawn_guard',
    'npc_dawn_herald', 'npc_dawn_chancellor', 'npc_dawn_deacon', 'npc_dawn_stableboy',
    'npc_dawn_alchemist', 'npc_dawn_gate', 'npc_silver_miller', 'npc_silver_inn',
    'npc_silver_granny', 'npc_maple_granny', 'npc_maple_child', 'npc_maple_hunter_w',
    'npc_maple_innkeep', 'npc_shield_smith', 'npc_shield_scout', 'npc_shield_townfolk',
    'npc_shield_sentry', 'npc_moongate_traveler', 'npc_moongate_inn', 'npc_moongate_spice',
    'npc_starsong_acrobat', 'npc_starsong_florist', 'npc_starsong_waiter', 'npc_frost_leather',
    'npc_frost_elder', 'npc_frost_drinker', 'npc_frost_armorer', 'npc_anvil_apprentice',
    'npc_anvil_clerk', 'npc_anvil_runeapp', 'npc_anvil_mule', 'npc_aurora_lantern',
    'npc_aurora_butler', 'npc_aurora_reindeer', 'npc_aurora_innkeep2', 'npc_aurora_sled',
    'npc_dragonkin_child', 'npc_dragonkin_priestess', 'npc_dragonkin_cook', 'npc_jade_sailor',
    'npc_jade_spice', 'npc_jade_waiter', 'npc_shell_coral', 'npc_shell_fisher',
    'npc_shell_helper', 'npc_shell_kelp', 'npc_nameless_sellsword', 'npc_nameless_clerk',
    'npc_nameless_deckhand', 'npc_nameless_pilot', 'npc_pearl_crafter', 'npc_pearl_lady',
    'npc_pearl_auction2', 'npc_pearl_merchant', 'npc_pearl_fishwife', 'npc_tunnel_foreman',
    'npc_tunnel_engineer', 'npc_tunnel_cook', 'npc_tunnel_trackman', 'npc_under_herbalist',
    'npc_under_broker', 'npc_under_helper', 'npc_under_farmer', 'npc_ember_weaponsmith',
    'npc_ember_adjutant', 'npc_ember_mapper', 'npc_ember_storeman', 'npc_wind_cloudmerchant',
    'npc_wind_scribe', 'npc_wind_guard2', 'npc_elf_poet2', 'npc_elf_maid', 'npc_elf_trainee',
    'npc_elf_librarian', 'npc_elf_gateguard2', 'npc_cold_skinner', 'npc_cold_oldherder',
    'npc_cold_bowyer', 'npc_cold_patrol', 'npc_pass_caravan', 'npc_pass_attendant',
    'npc_pass_sentinel', 'npc_violet_maid', 'npc_junk_murdoch', 'npc_courier_morton',
    'npc_trader_logan', 'npc_chef_cedric', 'npc_alchemist_serine', 'npc_old_alchemist_oldric',
    'npc_antique_oldoak', 'npc_pet_shop_xumao', 'npc_trade_blade', 'npc_merchant_greybanner',
    'npc_museum_curator', 'npc_shadow_cat', 'npc_apprentice_milo', 'npc_ironmask',
    'npc_rosalind', 'npc_apprentice_gray', 'npc_apprentice_luna', 'npc_dwarf_forgemaster',
    'npc_postmaster', 'npc_molly', 'npc_ironheart', 'npc_florist_tami', 'npc_old_florist',
    'npc_irine_homesail', 'npc_tide_reader_foam', 'npc_scale_keeper',
)

# npcs 域 source=='wild'（47 项）
_WILD_NPCS_ORDER = (
    'w_old_trader', 'w_forest_girl', 'w_sage_ryder', 'w_lost_knight', 'w_gravekeeper',
    'w_fisherman', 'w_paladin_exile', 'w_lore_master', 'w_grave_digger', 'w_temple_hermit',
    'w_war_ghost', 'w_elf_wanderer', 'w_druid_old', 'w_bard_roaming', 'w_silent_hunter',
    'w_elf_poet', 'w_frost_shaman', 'w_trapper', 'w_abyss_watcher', 'w_snow_traveler',
    'w_volcano_hermit', 'w_north_hunter', 'w_pilgrim', 'w_dragon_whisper', 'w_bone_collector',
    'w_war_scholar', 'w_storm_chaser', 'w_ancient_guardian', 'w_lighthouse_old',
    'w_pearl_diver', 'w_shipwreck_ghost', 'w_whale_whisper', 'npc_dock_coroner',
    'npc_seal_jonah', 'npc_abyss_witness', 'npc_captain_ghost_edmund',
    'npc_retired_collector_heron', 'npc_elven_ranger_yuelu', 'npc_dusk_shadow', 'npc_scalenote',
    'npc_hunter_birch', 'npc_fang_shaman', 'npc_forest_keeper_moss', 'npc_leafwhisper',
    'npc_starlake_elder', 'npc_brook_whisper', 'npc_fisher_buoy',
)

# npcs 域 source=='hidden'（22 项）
_HIDDEN_NPCS_ORDER = (
    'h_owl', 'h_mystery_merchant', 'h_grave_king', 'h_moon_wolf_king', 'h_ancient_druid',
    'h_ice_spirit', 'h_sea_dragon_king', 'h_abyss_whisper', 'h_storm_herald', 'h_timeless',
    'h_gravekeeper', 'h_librarian', 'h_night_trader', 'w_night_merchant', 'npc_gravedigger',
    'npc_letter_bird', 'npc_trial_veteran', 'npc_ghost_sailor', 'npc_tide_priest',
    'npc_dwarf_prisoner', 'npc_abyss_seer', 'npc_cloud_guardian',
)

# dialogues 域全量（39 项）
_DIALOGUES_ORDER = (
    'npc_mayor', 'npc_blacksmith', 'npc_innkeeper', 'npc_bard', 'npc_dwarf_elder',
    'npc_herb_master', 'npc_mine_master', 'npc_fish_master', 'npc_cook_master',
    'npc_alchemy_master', 'npc_craft_master', 'npc_enhance_master', 'npc_rune_master',
    'npc_spellblade_ghost', 'w_sage_ryder', 'npc_guild_clerks', 'npc_warrior_tutor',
    'npc_mage_tutor', 'npc_ranger_tutor', 'npc_priest_tutor', 'npc_bard_tutor',
    'npc_assassin_tutor', 'npc_monk_tutor', 'npc_eter', 'npc_baron', 'npc_doctor',
    'npc_tavern_owner', 'npc_guildmaster', 'npc_citylord', 'npc_auctioneer', 'npc_abbess',
    'npc_king', 'npc_knight_commander', 'npc_pope', 'npc_saintess', 'npc_elf_queen',
    'npc_elf_guardian', 'npc_elf_sage', 'npc_north_chief',
)

# achievements 域全量（119 项）
_ACHIEVEMENTS_ORDER = (
    'ach_first_fight', 'ach_kill10', 'ach_kill100', 'ach_kill500', 'ach_kill2000', 'ach_elite5',
    'ach_elite20', 'ach_boss1', 'ach_boss5', 'ach_slime100', 'ach_goblin100', 'ach_undead100',
    'ach_demon100', 'ach_dragon50', 'ach_inst1', 'ach_inst10', 'ach_inst_all8', 'ach_flawless',
    'ach_worldboss', 'ach_abyss_clear', 'ach_register', 'ach_lv10', 'ach_lv20', 'ach_lv30',
    'ach_lv40', 'ach_lv50', 'ach_lv60', 'ach_lv100', 'ach_evolve1', 'ach_evolve2',
    'ach_evolve3', 'ach_learn10', 'ach_learn30', 'ach_learn_all', 'ach_prof10', 'ach_area2',
    'ach_area10', 'ach_area_all', 'ach_hidden3', 'ach_gather10', 'ach_gather100', 'ach_mine100',
    'ach_fish10', 'ach_fish100', 'ach_fish_king', 'ach_bestiary50', 'ach_bestiary_all',
    'ach_alchemy10', 'ach_craft10', 'ach_craft100', 'ach_apprentice1', 'ach_apprentice4',
    'ach_apprentice8', 'ach_pro_gather3', 'ach_pro_gather6', 'ach_pro_gather10',
    'ach_pro_mining3', 'ach_pro_mining6', 'ach_pro_mining10', 'ach_pro_fishing3',
    'ach_pro_fishing6', 'ach_pro_fishing10', 'ach_pro_alchemy3', 'ach_pro_alchemy6',
    'ach_pro_alchemy10', 'ach_pro_craft3', 'ach_pro_craft6', 'ach_pro_craft10',
    'ach_pro_cooking3', 'ach_pro_cooking6', 'ach_pro_cooking10', 'ach_pro_enhance3',
    'ach_pro_enhance6', 'ach_pro_enhance10', 'ach_pro_enhance50', 'ach_pro_enchant3',
    'ach_pro_enchant6', 'ach_pro_enchant10', 'ach_party1', 'ach_party10', 'ach_party50',
    'ach_guild1', 'ach_guild3', 'ach_guild5', 'ach_faction1', 'ach_faction_top', 'ach_event10',
    'ach_faction_rank1', 'ach_bard_all', 'ach_truth', 'ach_saint_save', 'ach_main12',
    'ach_mythril', 'ach_goblin_friend', 'ach_dragon_skill', 'ach_lore_all', 'ach_no_death',
    'ach_event_all', 'ach_collect_rainbow', 'ach_wish_met', 'ach_collect_moon',
    'ach_collect_star', 'ach_h3_ember', 'ach_h4_library', 'ach_stardust_set',
    'ach_hidden_hunter', 'ach_starfall_sword', 'ach_gather500', 'ach_mine500', 'ach_fish500',
    'ach_elite50', 'ach_boss10', 'ach_inst5', 'ach_alchemy50', 'ach_cook50', 'ach_enhance100',
    'ach_bp20', 'ach_quest100', 'ach_chest50',
)

# quests 域 source=='main'（70 项）
_MAIN_QUESTS_ORDER = (
    'q1_1', 'q1_2', 'q1_3', 'q1_4', 'q1_5', 'q1_6', 'q2_1', 'q2_2', 'q2_3', 'q2_4', 'q2_5',
    'q3_1', 'q3_2', 'q3_3', 'q3_4', 'q3_5', 'q3_6', 'q4_1', 'q4_2', 'q4_3', 'q4_4', 'q4_5',
    'q5_1', 'q5_2', 'q5_3', 'q5_4', 'q5_5', 'q5_6', 'q6_1', 'q6_2', 'q6_3', 'q6_4', 'q6_5',
    'q6_6', 'q7_1', 'q7_2', 'q7_3', 'q7_4', 'q7_5', 'q7_6', 'q8_1', 'q8_2', 'q8_3', 'q8_4',
    'q8_5', 'q8_6', 'q9_1', 'q9_2', 'q9_3', 'q9_4', 'q9_5', 'q9_6', 'q10_1', 'q10_2', 'q10_3',
    'q10_4', 'q10_5', 'q10_6', 'q11_1', 'q11_2', 'q11_3', 'q11_4', 'q11_5', 'q11_6', 'q12_1',
    'q12_2', 'q12_3', 'q12_4', 'q12_5', 'q12_6',
)

# quests 域 source=='side'（144 项）
_SIDE_QUESTS_ORDER = (
    's1', 's2', 's3', 's4', 's5', 's6', 's7', 's8', 's9', 's10', 's11', 's12', 's13', 's14',
    's15', 's16', 's17', 's18', 's19', 's20', 's21', 's22', 's23', 's24', 's25', 's26', 's27',
    's28', 's29', 's30', 's31', 's32', 's33', 's34', 's36', 's37', 's38', 's39', 's40', 's41',
    's42', 's43', 's44', 's45', 's35', 's46', 's47', 's48', 's49', 's50', 's51', 's52', 's53',
    's54', 's55', 's56', 's57', 's58', 's59', 's60', 's61', 's62', 's63', 's64', 's65', 's66',
    's67', 's68', 's69', 's70', 's71', 's72', 's73', 's74', 's75', 's76', 's77', 's78', 's79',
    's80', 's81', 's82', 's83', 's84', 's85', 's86', 's87', 's88', 's89', 's107', 's108',
    's109', 's110', 's111', 's112', 's113', 's114', 's115', 's116', 's117', 's118', 's119',
    's120', 's121', 's90', 's91', 's92', 's93', 's94', 's95', 's96', 's97', 's98', 's99',
    's100', 's101', 's102', 's103', 's104', 's105', 's106', 'hq5_1', 'hq5_2', 'hq5_3', 'hq6_1',
    'hq6_2', 'hq6_3', 'hq7_1', 'hq7_2', 'hq7_3', 'hq8_1', 'hq8_2', 'hq8_3', 'hq8_4',
    's_hidden_ember', 's_hidden_library', 's_caravan_escort', 's_bandit_clear', 's_lighthouse',
    's_tunnel_repair', 's_dragon_bone', 's_dragon_blood', 's_board_cat', 's_tide_shells',
)

# quests 域 source=='daily'（24 项）
_DAILY_QUESTS_ORDER = (
    '日常讨伐', '大扫除', '清理兽患', '行会委托', '采集任务', '猎杀领主', '清剿盗匪', '护送商队', '讨伐精英', '踏平兽巢', '铲除祸首',
    '猎杀头目', '深渊勘察', '边境巡逻', '猎杀古兽', '剿灭魔裔', '讨伐领主', '深渊守望', '龙裔讨伐', '异界裂缝', '屠龙令', '裂境镇压',
    '邪龙残党', '裂界清剿',
)

# events 域 source=='explore'（100 项）
_EXPLORE_EVENTS_ORDER = (
    'treasure', 'merchant', 'spring', 'trap', 'omen', 'herb', 'windfall', 'wandering',
    'lost_camp', 'meteor', 'animal', 'rain', 'firefly', 'old_well', 'windmill', 'hunter_hut',
    'beehive', 'floating_bridge', 'old_tree_hollow', 'stone_tablet', 'cart_wreck', 'night_owl',
    'spider_web', 'frost_flower', 'old_boot', 'mushroom_ring', 'echo_cave', 'campfire_ashes',
    'drifting_bottle', 'abandoned_minecart', 'south_scarecrow', 'south_gold_panning',
    'south_beehive', 'mid_king_tomb', 'mid_holy_butterfly', 'mid_knight_target',
    'west_silver_leaf', 'west_tree_hollow', 'west_wind_chime', 'north_aurora_shard',
    'north_frozen_cave', 'north_wolf_howl', 'east_dragon_scale', 'east_dragon_bone_echo',
    'sea_tide_beacon', 'gen_tree_rings', 'gen_whiskey_keg', 'gen_cliff_eagle_nest',
    'gen_stone_bridge', 'gen_abandoned_trench', 'south_swamp_old_tree',
    'south_swamp_night_glow', 'south_mine_cave_echo', 'south_mine_pickaxe',
    'south_docks_sea_fog', 'south_docks_net_salvage', 'south_gorge_wind_runes',
    'south_ridge_hunter_trap', 'south_ridge_mud_pond', 'south_wind_road_shrine',
    'mid_border_flag', 'mid_border_patrol', 'mid_border_mess', 'mid_river_fisher',
    'mid_river_lantern', 'mid_river_heron', 'mid_old_tomb', 'mid_old_wisp', 'mid_west_station',
    'mid_west_hunter', 'north_forge_slag', 'north_forge_anvil_echo', 'north_cinder_pilgrim',
    'north_cinder_geyser', 'north_gallery_relief', 'north_gallery_rune_wind',
    'east_storm_lighthouse', 'east_storm_thunder_rock', 'east_dragonborn_fossil',
    'east_dragonborn_altar', 'deep_spore_cloud', 'deep_lake_echo', 'deep_molten_ember',
    'deep_altar_whisper', 'sea_whale_song', 'sea_black_wreck', 'isle_lighthouse_dusk',
    'sea_mist_reef', 'sky_cloud_drift', 'sky_storm_charge', 'sky_rainbow_dew',
    'sky_starlight_ladder', 'gen_rainbow', 'gen_fog_bell', 'gen_boot_note', 'gen_old_message',
    'gen_creek_song', 'gen_lost_pup', 'gen_roadside_keg', 'gen_dried_herbs',
)

# events 域 source=='egg'（46 项）
_EXPLORE_EGG_EVENTS_ORDER = (
    'shooting_star', 'mystery_chest', 'night_visitor', 'old_map', 'gold_slime',
    'egg_oak_whisper', 'egg_white_deer', 'egg_iron_ghost', 'egg_moon_doll',
    'egg_cathedral_choir', 'egg_harbor_siren', 'egg_ash_phoenix', 'egg_royal_fox',
    'egg_swamp_wisp', 'egg_frost_spirit', 'egg_elf_spring', 'egg_dragon_scale',
    'egg_under_king', 'egg_cloud_whale', 'egg_pearl_goddess', 'egg_blacksmith_ghost',
    'egg_time_traveler', 'egg_mimic_chest', 'egg_twin_moon', 'egg_star_fall', 'egg_rainbow_koi',
    'egg_lucky_clover', 'egg_moon_rabbit', 'egg_old_chest', 'egg_whispering_wind',
    'egg_jumping_scarecrow', 'egg_dove_messenger', 'egg_sleigh_ghost', 'egg_dragon_shadow',
    'egg_lost_mimic_cub', 'egg_sunrise_gold', 'egg_tree_echo', 'egg_stained_light',
    'egg_moon_glade', 'egg_mirage_fleet', 'egg_glow_school', 'egg_aurora_veil',
    'egg_rainbow_end', 'egg_meteor_shower', 'egg_fairy_dance', 'egg_goblin_caravan',
)

# monsters 域全量（330 项）
_MONSTER_SKILLS_ORDER = (
    'ms_basic_attack', 'ms_ai_hao', 'ms_an_ying_dan', 'ms_an_ying_jian', 'ms_an_ying_zhan',
    'ms_an_ying_zhao', 'ms_an_ying_zhi_liao', 'ms_bao_dan', 'ms_bao_zi_bao', 'ms_bao_zi_du',
    'ms_bao_zi_pen_she', 'ms_bing_dan', 'ms_bing_dong', 'ms_bing_hou', 'ms_bing_ji',
    'ms_bing_shuang_zhu_fu', 'ms_bing_xi', 'ms_bing_ya', 'ms_cai_guang', 'ms_cai_hong_zhan',
    'ms_cai_xi', 'ms_cha_ji', 'ms_chan_rao', 'ms_chong_zhuang', 'ms_chuan_shen', 'ms_di_lie',
    'ms_di_yu_huo', 'ms_ding_zhuang', 'ms_dong_jie', 'ms_du_ci', 'ms_du_wu', 'ms_du_ya',
    'ms_duan_dao', 'ms_duan_jian', 'ms_dun_ji', 'ms_feng_bao', 'ms_feng_bao_zhi_nu',
    'ms_feng_bao_zhi_yan', 'ms_feng_ren', 'ms_fu_chong', 'ms_fu_hua', 'ms_fu_ji', 'ms_fu_shi',
    'ms_fu_shi_ling_yu', 'ms_fu_shi_shu', 'ms_fu_wen_chong_ji', 'ms_gan_ran', 'ms_gao_ji',
    'ms_gen_xu', 'ms_gen_xu_chan_rao', 'ms_gu_long_wei_ya', 'ms_gu_xi', 'ms_hai_chao',
    'ms_hai_chao_zhu_fu', 'ms_hao_jiao', 'ms_hei_an_qi_dao', 'ms_hei_an_yi_shi',
    'ms_hei_an_zhi_liao', 'ms_hu_zai', 'ms_huo_dan', 'ms_huo_pao', 'ms_huo_qiang', 'ms_huo_yan',
    'ms_ji_chi', 'ms_ji_guang_shan', 'ms_ji_pao', 'ms_jia_ji', 'ms_jian_ji', 'ms_jian_ta',
    'ms_jian_xiao', 'ms_jiao_sha', 'ms_jing_hua_zhi_chao', 'ms_jing_ji_chan_rao',
    'ms_jing_ling_jian_shu', 'ms_ju_lang', 'ms_ken_yao', 'ms_lei_bao', 'ms_lei_ji',
    'ms_lei_jian', 'ms_lei_yu', 'ms_lian_zhan', 'ms_lie_yan_zhao', 'ms_lin_fen',
    'ms_long_jian_shu', 'ms_long_lin_chong_ji', 'ms_long_wei', 'ms_long_wei_190', 'ms_long_xi',
    'ms_long_yu_ai_hao', 'ms_long_zhao', 'ms_mei_huo', 'ms_mei_huo_zhi_ge', 'ms_mo_zhi',
    'ms_ni_jiang', 'ms_nian_ye', 'ms_nu_hou', 'ms_pai_ji', 'ms_peng_zhang', 'ms_pi_kan',
    'ms_piao_fu', 'ms_pu_ji', 'ms_qian_ji', 'ms_qian_xing', 'ms_rong_yan_dan', 'ms_san_cha_ji',
    'ms_shan_dian_lian', 'ms_shan_hu_hu_dun', 'ms_shan_shuo', 'ms_shen_pan_zhi_yan',
    'ms_shen_yuan_zhi_nu', 'ms_sheng_guang', 'ms_sheng_guang_dan',
    'ms_sheng_guang_zhan_bei_wu_ran', 'ms_shi_xi', 'ms_shuai_wei', 'ms_shui_dan', 'ms_shui_xi',
    'ms_si_yao', 'ms_suan_xi', 'ms_suo_lian', 'ms_teng_bian', 'ms_tie_bi', 'ms_tie_pi',
    'ms_tou_qie', 'ms_tou_shi', 'ms_tun_shi', 'ms_wan_dao', 'ms_wang_wei', 'ms_wei_feng_zhu_fu',
    'ms_wei_ya', 'ms_xi_xue', 'ms_xing_hui_dan', 'ms_xing_hui_zhan', 'ms_xing_xi',
    'ms_xiong_zhang', 'ms_xiu_jian', 'ms_xiu_li', 'ms_xuan_wo', 'ms_yan_wu', 'ms_yao_sui',
    'ms_ying_guang_shan', 'ms_ying_hua', 'ms_yue_guang_zhan', 'ms_yun_dan', 'ms_yun_dun',
    'ms_yun_shi', 'ms_zai_sheng', 'ms_zhan_chui', 'ms_zhan_hou', 'ms_zhang_jian',
    'ms_zhao_huan', 'ms_zhao_huan_chu_shou', 'ms_zhao_huan_e_mo',
    'ms_zhao_huan_feng_yu_jing_ling', 'ms_zhao_huan_gong_cheng_shou', 'ms_zhao_huan_gu_chong',
    'ms_zhao_huan_gu_long', 'ms_zhao_huan_hai_shou', 'ms_zhao_huan_ku_lou',
    'ms_zhao_huan_lei_niao', 'ms_zhao_huan_lie_quan', 'ms_zhao_huan_lie_ying',
    'ms_zhao_huan_long_zai', 'ms_zhao_huan_ru_chong', 'ms_zhao_huan_sha_yu',
    'ms_zhao_huan_shen_yuan', 'ms_zhao_huan_shu_ren', 'ms_zhao_huan_shui_gui',
    'ms_zhao_huan_shui_jing_ling', 'ms_zhao_huan_shui_ling', 'ms_zhao_huan_shui_mu',
    'ms_zhao_huan_shui_shou', 'ms_zhao_huan_xian_ling', 'ms_zhao_huan_xing_ling',
    'ms_zhao_huan_xue_lang', 'ms_zhao_huan_ying_bao', 'ms_zhao_huan_you_hun',
    'ms_zhao_huan_you_jing', 'ms_zhao_huan_you_ling', 'ms_zhao_huan_you_long',
    'ms_zhao_huan_yue_lu', 'ms_zhao_huan_yun_wei', 'ms_zhao_huan_zhen_jun_shou', 'ms_zhao_ji',
    'ms_zhi_hui', 'ms_zhi_liao', 'ms_zhi_mang', 'ms_zhi_wang', 'ms_zhi_yu', 'ms_zhong_ji',
    'ms_zhu_fu', 'ms_zhuang_ji', 'ms_zhuo_shao', 'ms_zu_zhou', 'ms_zuan_di',
    'ms_sheng_guang_zhui_bing', 'ms_sheng_guang_jian_zhen', 'ms_xuan_yun_zhong_ji',
    'ms_chen_mo_jian_xiao', 'ms_han_bing_tu_xi', 'ms_kuang_bao', 'ms_you_ling', 'ms_zhen_ji',
    'ms_an_ying', 'ms_xu_kong', 'ms_hai_yao', 'ms_an_ying_qin_shi', 'ms_bing_feng_li_zhao',
    'ms_bing_xi_lord', 'ms_chao_xi_yi_shi', 'ms_chao_yong_ling_yu', 'ms_chen_chuan_mei_ying',
    'ms_chi_re_bu_dao', 'ms_chu_xing_xuan_du', 'ms_di_di_li_zhao', 'ms_di_yin_wei_mu',
    'ms_dian_hu_jian_she', 'ms_dun_ji_shi_lian', 'ms_f6_an_ying_jian_yu',
    'ms_f6_chuan_cheng_he_fu_huo', 'ms_f6_fen_shen_huo_lang', 'ms_f6_feng_bao_feng_yan',
    'ms_f6_fu_shi_wa_di', 'ms_f6_hun_yan_xi', 'ms_f6_jing_dian_jie_dian',
    'ms_f6_lei_bao_feng_yan', 'ms_f6_lei_bao_tian_xiang', 'ms_f6_lei_ji_tian_xiang',
    'ms_f6_lei_ting_shen_pan', 'ms_f6_lian_lei', 'ms_f6_ling_hun_bo_li', 'ms_f6_mo_yu_kong_xi',
    'ms_f6_ni_zhao_jia_shen', 'ms_f6_shen_han', 'ms_f6_sheng_guang_ling_yu',
    'ms_f6_sheng_guang_tan', 'ms_f6_sheng_yu', 'ms_f6_yan_zhi_nu_fan_pu',
    'ms_f6_yu_wei_zhao_huan', 'ms_f6_zhao_huan_ku_long', 'ms_fu_shi_tu_xi_heng_sao',
    'ms_gao_yin_gong_ming', 'ms_gen_xu_chan_rao_x', 'ms_ha_er_lian', 'ms_ha_huan_dan',
    'ms_ha_huo_qiang_qi', 'ms_ha_shuang_fa', 'ms_he_sheng_zhao_huan', 'ms_hei_an_yi_shi_helga',
    'ms_heng_sao_xiu', 'ms_ji_han_feng_bao', 'ms_ji_huo_guang_zhu', 'ms_ji_huo_jing_mian',
    'ms_ji_huo_sheng_dun', 'ms_ju_lang_blue', 'ms_ju_qian_heng_sao', 'ms_lang_chao_dot',
    'ms_lang_yong_pai_ji', 'ms_lei_jing_ning_ju', 'ms_lei_jing_sui_xie',
    'ms_lei_jing_zhong_chui', 'ms_lei_ting_jian_ta', 'ms_lei_ting_zha_lie',
    'ms_long_wei_ji_tui', 'ms_luo_shi_po_qiao', 'ms_lve_duo_h_ling', 'ms_lve_er_zhang',
    'ms_lve_h_ling_cheng', 'ms_lve_jie_huan_zhua', 'ms_lve_za_jiu_tan', 'ms_mei_huo_ge_blue',
    'ms_nu_chao', 'ms_qian_jia_lie_shi', 'ms_rong_lu_bao_fa', 'ms_shen_shui_ya',
    'ms_shen_yuan_zhi_yan', 'ms_sheng_guang_cai_jue', 'ms_sheng_guang_fan_shi',
    'ms_sheng_guang_qi_yuan', 'ms_sheng_mu_ge_ying', 'ms_shi_gu_shen_tun', 'ms_shi_gu_si_yao',
    'ms_shi_lin_suan_shi', 'ms_shi_zi_zhan', 'ms_shui_dan_chong_ji', 'ms_shui_ren_lange',
    'ms_shui_xi_aolan', 'ms_suan_xi_under', 'ms_suo_lian_ding_zui', 'ms_suo_qiao_xi',
    'ms_wan_dao_an_ying', 'ms_wang_chao_zu_zhou', 'ms_wang_yu_huan_hun', 'ms_wang_zhe_zhi_nu',
    'ms_xi_deng', 'ms_xie_mu_qu', 'ms_xiu_qiao', 'ms_xuan_wo_la_che', 'ms_yin_chao_hui_chun',
    'ms_yong_tan_lang_yong', 'ms_you_ai_hao', 'ms_you_fu_shen', 'ms_you_hui_hui_chang',
    'ms_you_jun_qi', 'ms_you_kang_bao', 'ms_you_lan_hui_xiang', 'ms_you_sheng_guang_chu_ji',
    'ms_you_xiang_ji', 'ms_yuan_ling_jian_xiao', 'ms_yue_guang_cai_jue', 'ms_yue_guang_xin',
    'ms_yue_guang_ying', 'ms_yue_hua_lian_shan', 'ms_yue_shi_jiang_lin', 'ms_yue_zhi_qi_yuan',
    'ms_zhan_chui_lord', 'ms_zhao_bing_yuan_su_lord', 'ms_zhao_chu_shou_blue',
    'ms_zhao_huan_e_mo_helga', 'ms_zhao_ji_zhen_kui_lei', 'ms_zhao_ku_lou_mi',
    'ms_zhao_sha_yu_lange', 'ms_zhao_shu_ren_dawn', 'ms_zhao_xiu_li_kui_lei',
    'ms_zhao_you_long_under', 'ms_zhao_zhu_hun', 'ms_zhao_zi_bao_kui_lei',
    'ms_zhong_chui_lian_da', 'ms_zhong_qian_xiu', 'ms_zhu_huo_zhu',
)

# monster_mods 域全量（140 项）
_MONSTER_MODS_ORDER = (
    'm_wild_dog', 'm_giant_rat', 'e_bandit_leader', 'm_forest_wolf', 'e_wolf_alpha',
    'm_giant_spider', 'm_valley_faerie', 'e_tree_lord', 'e_white_stag', 'm_goblin_warrior',
    'm_cave_bat', 'm_snake', 'm_goblin_shaman', 'b_goblin_chief', 'm_zombie', 'm_ghost',
    'e_bone_lord', 'e_fungus_lord', 'm_orc_raider', 'm_steppe_wolf', 'e_orc_warrior',
    'm_skeleton', 'm_rot_orc', 'e_grave_lord', 'm_lava_elemental', 'e_lava_lord',
    'm_frost_troll', 'm_ice_elemental', 'm_valley_eagle', 'e_storm_cliff_lord', 'm_abyss_demon',
    'm_void_hound', 'm_meteor_golem', 'e_rune_golem', 'm_temple_guard', 'm_light_priest',
    'e_elf_sentinel', 'm_shadow_panther', 'm_red_wyvern', 'm_dragonkin', 'b_moro',
    'b_om_shadow', 'b_cardinal', 'b_king_odric', 'b_eter', 'm_magma_worm', 'm_obsidian_golem',
    'e_gold_slime', 'e_fortune_fox', 'e_glimmer_fish', 'e_iron_bull', 'e_swamp_croc',
    'e_forest_wolf_king', 'e_moon_wolf', 'e_frost_bear', 'e_fungus_king', 'e_mine_troll',
    'e_abbey_guardian', 'e_ash_salamander', 'e_sea_serpent', 'e_storm_eagle', 'e_cloud_serpent',
    'e_deep_angler', 'e_dragon_hatchling', 'e_ghost_knight', 'e_lava_golem', 'e_royal_guard',
    'e_shadow_stalker', 'e_siren', 'e_great_boar', 'e_gorge_troll', 'e_boar_king',
    'e_valley_troll', 'e_swamp_king', 'e_plain_wolf', 'e_cave_troll', 'e_pirate_lieutenant',
    'e_river_dragon_lord', 'e_inquisitor', 'e_hill_wolf_king', 'e_knight_instructor',
    'e_battle_lord', 'e_reef_king', 'e_island_tiger', 'e_siren_lord', 'e_valley_lord',
    'e_moon_wolf_alpha', 'e_storm_leviathan', 'e_lake_king', 'e_wind_king', 'e_archive_warden',
    'e_moon_lord', 'e_moonshadow_lord', 'e_trench_leviathan', 'e_whale_king',
    'e_graveyard_lord', 'e_ice_fang_lord', 'e_frost_troll_lord', 'e_storm_dragon',
    'e_frost_mammoth', 'e_lake_lord', 'e_dark_leech', 'e_rot_chief_guard', 'e_glacier_wyrm',
    'e_demon_warrior', 'e_molten_lord', 'e_ash_champion', 'e_cloud_lord', 'e_red_dragon_lord',
    'e_magma_king', 'e_altar_guardian', 'e_dragon_lord_ghost', 'e_dragon_roost_king',
    'e_rainbow_dragon', 'e_storm_lord', 'e_star_dragon', 'b_ember_lord', 'b_lost_archivist',
    'b_fort_ghost', 'b_jack_pirate', 'b_trial_knight', 'b_ghost_captain', 'b_marcus',
    'b_rust_crab', 'b_candle_bishop', 'b_thunder_golem', 'b_whirl_turtle', 'b_opera_siren',
    'b_siren_queen', 'b_dawn_elf', 'b_moon_guard', 'b_lange', 'b_aolan', 'b_frost_lord',
    'b_gray_lord', 'b_helga', 'b_under_dragon', 'b_storm_king', 'b_storm_master', 'b_ola',
)

# monster_roster 的 elite_equip_drop 落点（键=精英中文名）（18 项）
_ELITE_EQUIP_DROP_ORDER = (
    '峡谷巨魔', '野猪王·裂鬃', '狼王·灰影', '沼泽巨鳄', '丘陵狼王·铁牙', '盗贼头目·黑鸦', '珊瑚礁主·红棘', '海妖领主·潮汐', '月狼王·银鬃',
    '风语王·岚歌', '古树领主', '霜巨魔王', '熔岩领主', '冰川龙·霜牙', '骨龙领主·骸王', '深渊骑士', '雷暴领主·雷霆', '星龙·辰光',
)


# =============================================================================
# ② 域读入（全在包内；缺文件 → {} → 下面 _ordered 立刻 raise，不静默变空表）
# =============================================================================
_NPCS_DOM = _read("data", "npcs", {})
_QUEST_DOM = _read("data", "quests", {})
_EVENT_DOM = _read("data", "events", {})
_DLG_DOM = _read("data", "dialogues", {})
_ACH_DOM = _read("data", "achievements", {})
_TITLE_DOM = _read("data", "titles", {})
_WEEKLY_DOM = _read("data", "weekly_quests", {})
_TRIAL_DOM = _read("data", "trial_floors", {})
_MODS_DOM = _read("data", "monster_mods", {})
_MSKILL_DOM = _read("data", "monsters", {})
_ROSTER_DOM = _read("data", "monster_roster", {})
_CFG = _read("rules", "game_config", {})


# =============================================================================
# ③ 21 个数据名（宿主 `C.<名>` 的等价物）
# =============================================================================
# --- NPC 三表（`derive_npcs` 折了 town/wild/hidden 三张真源表，注入 `source` 表达归属）---
NPCS: dict = _ordered(_by_source(_NPCS_DOM, "town"), _NPCS_ORDER, "npcs(town)")
WILD_NPCS: dict = _ordered(_by_source(_NPCS_DOM, "wild"), _WILD_NPCS_ORDER, "npcs(wild)")
# hidden 里 6 条副本层内 NPC 多一个注入字段 `inst_stage`（`derive_npcs` 注入），一并去掉
HIDDEN_NPCS: dict = _ordered(_by_source(_NPCS_DOM, "hidden", ("source", "inst_stage")),
                             _HIDDEN_NPCS_ORDER, "npcs(hidden)")

# --- 对话树（键 = NPC id；39 棵，节点/选项顺序是语义，域内已原样）---
DIALOGUES: dict = _ordered(_DLG_DOM, _DIALOGUES_ORDER, "dialogues")

# --- 任务三表（`derive_quests` 合表 + 注入 `source`；DAILY 的键是 name，源侧没有 id）---
MAIN_QUESTS: list = [_drop(_QUEST_DOM[k], "source") for k in _MAIN_QUESTS_ORDER]
SIDE_QUESTS: list = [_drop(_QUEST_DOM[k], "source") for k in _SIDE_QUESTS_ORDER]
DAILY_QUESTS: list = [_drop(_QUEST_DOM[k], "source") for k in _DAILY_QUESTS_ORDER]

# --- 探索事件两池（`derive_events` 合表 + 注入 `source`）---
EXPLORE_EVENTS: list = [_drop(_EVENT_DOM[k], "source") for k in _EXPLORE_EVENTS_ORDER]
EXPLORE_EGG_EVENTS: list = [_drop(_EVENT_DOM[k], "source") for k in _EXPLORE_EGG_EVENTS_ORDER]

# --- 成就 / 称号 / 周常 ---
ACHIEVEMENTS: list = [_ACH_DOM[k] for k in _ACHIEVEMENTS_ORDER]
# 称号 / 周常：域自带 `seq`（导出器注入 1 基源序），按它还原源序、再把 `seq` 去掉
TITLES: list = [_drop(v, "seq") for v in
                sorted(_TITLE_DOM.values(), key=lambda e: e["seq"])]
WEEKLY_QUESTS: list = [_drop(v, "seq") for v in
                       sorted(_WEEKLY_DOM.values(), key=lambda e: e["seq"])]

# --- 怪技能 / 个体改造 ---
MONSTER_SKILLS: dict = _ordered(_MSKILL_DOM, _MONSTER_SKILLS_ORDER, "monsters")
MONSTER_MODS: dict = _ordered(_MODS_DOM, _MONSTER_MODS_ORDER, "monster_mods")

# --- 精英专属装备掉落（宿主 `ELITE_EQUIP_DROP`：键 = 精英怪**中文名** → 名册装备 id）---
def _elite_equip_drop() -> dict:
    """从 `monster_roster` 的 `elite_equip_drop` 字段还原（键 = 条目的 `name`）。

    实测名册 20 条落点 ↔ 宿主表 18 键：两个名字（深渊骑士 / 沼泽巨鳄）在名册里各出现
    两次且**值相同**（`derive_monster_roster` 的多行摆放投影），故按「同名同值去重」——
    同名**值不同** → raise（那才是真冲突，不能静默挑一个）。
    """
    m: dict = {}
    for mid, ent in _ROSTER_DOM.items():
        v = ent.get("elite_equip_drop") if isinstance(ent, dict) else None
        if v is None:
            continue
        nm = ent.get("name")
        if nm in m and m[nm] != v:
            raise ValueError("elite_equip_drop：%r 在名册里有两个不同值（%r / %r）—— 拒绝静默挑一个"
                             % (nm, m[nm], v))
        m[nm] = v
    return _ordered(m, _ELITE_EQUIP_DROP_ORDER, "monster_roster(elite_equip_drop)")


ELITE_EQUIP_DROP: dict = _elite_equip_drop()

# --- 试炼塔：层表 + 两个标量（常量与层表同在 game_config 域，但分属两个子表）---
_TRIAL_CFG = _CFG.get("trial_tower") or {}
TRIAL_DAILY_LIMIT: int = _TRIAL_CFG["TRIAL_DAILY_LIMIT"]
TRIAL_MAX_FLOOR: int = _TRIAL_CFG["TRIAL_MAX_FLOOR"]
# 层表按 floor 1..TRIAL_MAX_FLOOR 还原源序（域键是字符串 "1"/"10"/…，字面序会乱）
TRIAL_FLOORS: list = [_TRIAL_DOM[str(i)] for i in range(1, TRIAL_MAX_FLOOR + 1)]

# --- 职业流派（rules 域的 builds 子表：内层键序 = 源序，未被 sort_table 折叠）---
BUILDS: dict = dict((_CFG.get("builds") or {}).get("BUILDS") or {})


# =============================================================================
# ④ 缺口的两个名字（不在此处定义 —— 定义成空值会让门禁把「缺口」当成「值不等」）
# =============================================================================
# 这两个名字在包内 66 域里**没有**等价数据源，故本单元不提供：
#   HIDDEN_MONSTERS  ← 宿主 game/data/hidden_monsters.py:18（25 条隐藏怪行）
#                      包内 `monster_roster` 有 `hidden` 子块（lv_off/gold_mult/cond/
#                      chance/tag/flavor 六字段，25/25 对得上），但它的 `name`/`skills`/
#                      `drops` 是**五处摆放表求并集**的投影（实测 19/25 与隐藏怪行不同），
#                      还原不了隐藏怪行原文 → 需新域 `hidden_monsters`（字段见报告）。
#   CHAPTER_PACK     ← 宿主 game/data/quest_add_v140.py:106（10 档章节礼包 list）
#                      包内无任何域含这批数据 → 需新域 `chapter_pack`（字段见报告）。
PENDING_NAMES = ("HIDDEN_MONSTERS", "CHAPTER_PACK")

# 本模块真要用到的包内域（缺一个 = 门面变空/import 期 raise）—— 便于验收脚本点名核对
REQUIRED_DOMAINS = ("npcs", "quests", "events", "dialogues", "achievements", "titles",
                    "weekly_quests", "trial_floors", "monsters", "monster_mods",
                    "monster_roster", "game_config")


def missing_domains() -> list:
    """缺哪张域（文件不在 / 坏 JSON / 空表）—— 「静默变白板」比报错难查。"""
    out = []
    for dom, tbl in (("npcs", _NPCS_DOM), ("quests", _QUEST_DOM), ("events", _EVENT_DOM),
                     ("dialogues", _DLG_DOM), ("achievements", _ACH_DOM),
                     ("titles", _TITLE_DOM), ("weekly_quests", _WEEKLY_DOM),
                     ("trial_floors", _TRIAL_DOM), ("monsters", _MSKILL_DOM),
                     ("monster_mods", _MODS_DOM), ("monster_roster", _ROSTER_DOM),
                     ("game_config", _CFG)):
        if not isinstance(tbl, dict) or not tbl:
            out.append(dom)
    return out


__all__ = [
    "NPCS", "WILD_NPCS", "HIDDEN_NPCS", "DIALOGUES",
    "MAIN_QUESTS", "SIDE_QUESTS", "DAILY_QUESTS",
    "EXPLORE_EVENTS", "EXPLORE_EGG_EVENTS",
    "ACHIEVEMENTS", "TITLES", "WEEKLY_QUESTS",
    "MONSTER_SKILLS", "MONSTER_MODS", "ELITE_EQUIP_DROP",
    "TRIAL_FLOORS", "TRIAL_DAILY_LIMIT", "TRIAL_MAX_FLOOR", "BUILDS",
    "PENDING_NAMES", "REQUIRED_DOMAINS", "missing_domains",
]
