# -*- coding: utf-8 -*-
"""包内「地图随机事件菜单」数据口（`content/event_menu.py`）—— B8.2 线3（2026-09-13）。

用途：宿主命令层 `game/commands/event_menu.py`（『今日事件』『事件 <地图名>』『领取补给箱』）
薄壳化后的**唯一读表口**。本模块只做「读包内域 JSON + 还原真源形状/顺序 + 一条纯逻辑」，
**不含渲染**（拼串一字未改地留在命令层 —— 与 B8.2 线5 `commands/job_guide.py` 同款口径）。

真源 → 包内域（单向导出：游戏仓 `scripts/export_game_package.py` + `scripts/export_domains/`）
------------------------------------------------------------------------------------------
| 命令层原来读 | 包内域 | 本模块提供 | 备注 |
|---|---|---|---|
| `C.MAPS`（121，**list**，源序） | `worlds` | `MAPS`（按 `MAP_ORDER` 还原源序）/ `MAP_BY_ID` | 地图扁平表（`game/data/maps.py` 的 `MAPS`/`MAP_BY_ID`） |
| `C.MAP_BY_ID` | 同左 | `MAP_BY_ID` | 渲染只用 `.get("name")` |
| `C.EXPLORE_EVENTS`（100，源序） | `events`（`source=="explore"`） | `EXPLORE_EVENTS` | 档位 top6 并列时**靠源序**决胜 |
| `C.EXPLORE_EGG_EVENTS`（46，源序） | `events`（`source=="egg"`） | `EXPLORE_EGG_EVENTS` | 传闻取 `[:3]`/`[:2]` → 硬依赖源序 |
| `C.ITEMS` / `C.resolve("items",…)` | `items` | `ITEMS` / `resolve_item()` | 补给箱发放 |
| `game/core/texts.py`（文案表门面） | `texts` | **不搬**（调用点必须留命令层，见 §④） | `supply.*` 7 条由宿主文案表门禁对账 |

★ 顺序声明（`MAP_ORDER` / `EXPLORE_EVENT_ORDER` / `EGG_EVENT_ORDER`）——为什么必须有
----------------------------------------------------------------------------------
域文件外层键是**字典序**（导出契约 `sort_table`：幂等优先），而这三张表的真源是
**有序 list**：① 地图 `next(... name in …)` 子串匹配要按源序取首个命中（『事件 橡木』
命中橡木镇还是橡木平原，由源序决定）；② 探索档位 `sorted(..., key=-weight)[:6]` 是稳定排序，
并列时按源序；③ 彩蛋传闻取前 3/前 2 条。少一份顺序声明 → 玩家看到的行会变（逐字变）。
导出域**没有** `ord`/`seq` 字段可还原（`derive_events` 只注入 `source`）→ 本模块显式声明
真源插入序（与 `content/tables.py` 的 `JOB_ORDER` 同一手法），并**带集合守卫**：
域里多一条/少一条就 `raise`（防「加了地图/事件忘了改这里」= 静默改序）。
（`weekly_quests` 域是导出期注入 `seq` 的另一条路；`events`/`worlds` 是既有域，
本批不动别人的导出器 —— 缺口见报告 §缺口。）

未进包（保留宿主直读，报告 §缺口）
----------------------------------
`DAILY_MAP_EVENTS`（`game/data/daily_events.py:18`，20 图）、`WORLD_EVENT_POOL`
（`game/data/world.py:8`，14 条）、`SUPPLY_BOX`（`game/data/quest_add_v140.py:121`，3 档）
—— 三个域都**未预声明**（B8.2 父任务：不许新建未预声明的域）。它们的表由命令层注入，
**只有纯逻辑 `daily_event_for()` 在本模块**（逐字搬 `game/core/daily_events.py:21 today_map_event`）。
"""
from __future__ import annotations

import datetime
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))          # <pkg>/content
_DATA_DIR = os.path.join(_HERE, "data")


def _read_domain(domain: str, sub: str = "data", default=None):
    """读包内 `content/<sub>/<domain>.json`（缺文件 / 坏 JSON → default，不抛；同包内口径）。"""
    try:
        with open(os.path.join(_HERE, sub, "%s.json" % domain), encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                       # noqa: BLE001
        return {} if default is None else default


# ============================================================
# ① 地图（worlds 域 = 扁平地图表）
# ============================================================
WORLDS: dict = _read_domain("worlds")
MAP_BY_ID: dict = WORLDS

# ★ 真源 `game/data/maps.py:3 MAPS` 的**列表插入序**（121 条；见文件头「顺序声明」）。
#   块由 `overnight/_b82_L3_gen_orders.py` 从真源生成（本文件不手抄）。
MAP_ORDER = """oak_town oak_plain white_deer_forest white_deer emerald_forest misty_swamp goblin_camp rust_dock
candle_crypt thunder_mine whirl_arena blacktide_opera hill_mine ironharbor harbor_docks sea_cave
silver_brook silver_valley windmill_plain deer_fort maple_village rockfall_gorge boar_ridge dawn_city
dawn_cathedral gold_plain white_abbey old_king_tomb border_castle silver_river secret_crypt knight_yard
king_road holy_trial ironshield_town ironshield_hills old_battlefield moon_gate silverwood starlake
moon_court elven_ruins ancient_tree star_song moon_glade emerald_valley moon_temple windvale
moonshadow_wood frost_horn frost_field anvil_fort forge_valley black_forest cinder_mountain ash_temple
abyss_gate frost_fang cold_ridge winter_lake frost_throne aurora_town permafrost_field
frostwhisper_canyon dragon_pass dragon_ridge dragon_roost ancient_battlefield dragon_tomb dragon_kin
bone_wild storm_cliff storm_throne redridge_plateau dragonsfall_valley jade_port shell_town coral_reef
sunset_isle storm_strait mermaid_bay sunken_ship siren_nest nameless_harbor pearl_city mist_trench
whale_domain shipwreck_graveyard storm_sea sea_god_temple deep_dragon_palace deep_tunnel under_market
fungus_forest deep_lake molten_abyss gray_dwarf under_dragon ember_camp lava_bed abyss_altar
abyss_throne wind_city cloud_sea storm_plateau eye_of_storm rainbow_cloud starlight_terrace
cloud_sanctum lost_library ember_corridor silver_wind_road west_ridge_wilds dusk_ridge_road
mist_tide_passage black_tide_strait dwarf_long_gallery cold_spine_snow_trail dragon_ridge_old_road
dragonborn_valley_trail sky_ladder_path""".split()

# ============================================================
# ② 事件池（events 域 = 探索池 + 彩蛋池，条目带 source）
# ============================================================
_EVENTS_RAW: dict = _read_domain("events")
EXPLORE_EVENT_ORDER = """treasure merchant spring trap omen herb windfall wandering lost_camp meteor animal rain firefly old_well
windmill hunter_hut beehive floating_bridge old_tree_hollow stone_tablet cart_wreck night_owl spider_web
frost_flower old_boot mushroom_ring echo_cave campfire_ashes drifting_bottle abandoned_minecart
south_scarecrow south_gold_panning south_beehive mid_king_tomb mid_holy_butterfly mid_knight_target
west_silver_leaf west_tree_hollow west_wind_chime north_aurora_shard north_frozen_cave north_wolf_howl
east_dragon_scale east_dragon_bone_echo sea_tide_beacon gen_tree_rings gen_whiskey_keg
gen_cliff_eagle_nest gen_stone_bridge gen_abandoned_trench south_swamp_old_tree south_swamp_night_glow
south_mine_cave_echo south_mine_pickaxe south_docks_sea_fog south_docks_net_salvage
south_gorge_wind_runes south_ridge_hunter_trap south_ridge_mud_pond south_wind_road_shrine
mid_border_flag mid_border_patrol mid_border_mess mid_river_fisher mid_river_lantern mid_river_heron
mid_old_tomb mid_old_wisp mid_west_station mid_west_hunter north_forge_slag north_forge_anvil_echo
north_cinder_pilgrim north_cinder_geyser north_gallery_relief north_gallery_rune_wind
east_storm_lighthouse east_storm_thunder_rock east_dragonborn_fossil east_dragonborn_altar
deep_spore_cloud deep_lake_echo deep_molten_ember deep_altar_whisper sea_whale_song sea_black_wreck
isle_lighthouse_dusk sea_mist_reef sky_cloud_drift sky_storm_charge sky_rainbow_dew sky_starlight_ladder
gen_rainbow gen_fog_bell gen_boot_note gen_old_message gen_creek_song gen_lost_pup gen_roadside_keg
gen_dried_herbs""".split()
EGG_EVENT_ORDER = """shooting_star mystery_chest night_visitor old_map gold_slime egg_oak_whisper egg_white_deer
egg_iron_ghost egg_moon_doll egg_cathedral_choir egg_harbor_siren egg_ash_phoenix egg_royal_fox
egg_swamp_wisp egg_frost_spirit egg_elf_spring egg_dragon_scale egg_under_king egg_cloud_whale
egg_pearl_goddess egg_blacksmith_ghost egg_time_traveler egg_mimic_chest egg_twin_moon egg_star_fall
egg_rainbow_koi egg_lucky_clover egg_moon_rabbit egg_old_chest egg_whispering_wind egg_jumping_scarecrow
egg_dove_messenger egg_sleigh_ghost egg_dragon_shadow egg_lost_mimic_cub egg_sunrise_gold egg_tree_echo
egg_stained_light egg_moon_glade egg_mirage_fleet egg_glow_school egg_aurora_veil egg_rainbow_end
egg_meteor_shower egg_fairy_dance egg_goblin_caravan""".split()


def _ordered(raw: dict, order, source: str, what: str) -> list:
    """按声明的真源序还原一个有序条目表；集合不一致 → **raise**（绝不静默改序）。"""
    keys = {k for k, v in raw.items() if isinstance(v, dict) and v.get("source") == source}
    have = set(order)
    if have != keys:
        raise ValueError(
            "%s：顺序声明与域内条目不一致（域 %d 条 / 声明 %d 条；"
            "域多出 %s；声明多出 %s）—— 请用 scripts/export_domains 的重量纲重生成顺序声明"
            % (what, len(keys), len(order), sorted(keys - have)[:5], sorted(have - keys)[:5]))
    if len(order) != len(have):
        raise ValueError("%s：顺序声明里有重复 id（%d 条 vs 集合 %d）" % (what, len(order), len(have)))
    return [raw[k] for k in order]


EXPLORE_EVENTS: list = _ordered(_EVENTS_RAW, EXPLORE_EVENT_ORDER, "explore", "explore 事件池")
EXPLORE_EGG_EVENTS: list = _ordered(_EVENTS_RAW, EGG_EVENT_ORDER, "egg", "彩蛋事件池")


def _maps_ordered() -> list:
    """地图列表（源序）；集合守卫同 `_ordered`。"""
    have, keys = set(MAP_ORDER), set(WORLDS)
    if have != keys:
        raise ValueError(
            "地图顺序声明与 worlds 域 key 不一致（域 %d / 声明 %d；域多出 %s；声明多出 %s）"
            "—— 用 overnight/_b82_L3_gen_orders.py 重生成" %
            (len(keys), len(MAP_ORDER), sorted(keys - have)[:5], sorted(have - keys)[:5]))
    if len(MAP_ORDER) != len(have):
        raise ValueError("地图顺序声明里有重复 id（%d 条 vs 集合 %d）" % (len(MAP_ORDER), len(have)))
    return [WORLDS[k] for k in MAP_ORDER]


MAPS: list = _maps_ordered()

# ============================================================
# ③ 物品（items 域 = MATERIALS ∪ CONSUMABLES ∪ 追加条目的合表 900）
# ============================================================
ITEMS: dict = _read_domain("items")

# 名字 → id（`game/core/index.py:19 build_index` 同口径；**实测 900 条名字零重名**
# —— 所以「首/末次命中赢」这个差别不存在；仍按源顺序赋值，行为与真源一致）。
_ITEM_BY_NAME = {}
for _k, _v in ITEMS.items():
    if isinstance(_v, dict) and _v.get("name"):
        _ITEM_BY_NAME[_v["name"]] = _k

# ★ 材料域**未进包**（`content/data/` 无 materials.json；`MATERIALS`(598) ⊊ `ITEMS`(900)）。
#   真源 `_grant_items` 的「材料兜底」分支在真源数据下**结构性不可达**：
#   两张名字索引都建于同一批表（`game/data/_assembly.py:179` materials / `:183` items），
#   而 `ITEMS = dict(MATERIALS); ITEMS.update(...)`（`items.py:3057-3058`）⇒ 任何材料名都在
#   items 索引里，且解析出的 id 必然 ∈ ITEMS ⇒ 永远走第一分支。实测：SUPPLY_BOX 三档
#   9/9 物品名全部命中 ITEMS 分支。故此处给空表 + 保留分支形状（不静默造假表）。
MATERIALS: dict = {}


def resolve_item(name_or_id: str):
    """物品名 → id（找不到**原样返回**；`game/core/index.py:47 resolve("items",…)` 同义）。"""
    return _ITEM_BY_NAME.get(name_or_id, name_or_id)


def resolve_material(name_or_id: str):
    """材料名 → id（真源 `resolve("materials",…)` 的包内替身；表未进包 ⇒ 只知道 id 原样返回）。"""
    return name_or_id


def display_material(entity_id: str) -> str:
    """材料 id → 显示名（真源 `display("materials",…)`；表未进包 ⇒ 原样返回 id）。"""
    return entity_id


# ============================================================
# ④ 文案（texts 域）—— **本模块不提供读口**
# ------------------------------------------------------------
# 补给箱那 7 条 `supply.*` 文案的 `T.static/T.text` 调用点**必须留在命令层**：
# `tests/test_texts_table.py:81 WIRED` 把 `game/commands/event_menu.py` 当「补给箱」域的
# 调用点真源，`t2` 双向对账（声明↔调用点）—— 调用点搬进包 ⇒ 表里 7 条立刻变「死文案」，
# 门禁红。故文案表口径不动（与 B8.2 线1 `commands/weekly.py` 同款：渲染留宿主）。
# ============================================================


# ============================================================
# ⑤ 今日奇遇（纯逻辑；`game/core/daily_events.py:21 today_map_event` 逐字搬）
# ============================================================
def _day_hash(seed: int, salt: str = "") -> int:
    h = seed * 2654435761 + (sum(ord(c) for c in salt) if salt else 0)
    return h & 0x7FFFFFFF


def daily_event_for(map_id, daily_map, now=None):
    """今日奇遇（日期哈希选中，同一天全服一致）。

    真源 `game/core/daily_events.py:21 today_map_event(map_id, now=None)`；本包版把
    `DAILY_MAP_EVENTS` 表改为**调用方传入**（该域未进包，见文件头）。返回选中的变体 dict
    （含 id/name/desc/effects），无配置返回 None —— 与真源逐字同义。
    """
    variants = (daily_map or {}).get(map_id)
    if not variants:
        return None
    _now = now or datetime.date.today()
    if isinstance(_now, datetime.datetime):
        ordinal = _now.date().toordinal()
    else:
        ordinal = _now.toordinal()
    # 用 map_id 作 salt，避免不同图同 seed 顶到同一下标的比例失配
    idx = _day_hash(ordinal, "daily:" + map_id) % len(variants)
    return variants[idx]
