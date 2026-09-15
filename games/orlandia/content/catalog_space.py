# -*- coding: utf-8 -*-
"""包内空间族门面（`content/catalog_space.py`）—— 游戏仓聚合层 `C` 的 **21 个空间族名字**的包内等价物。

为什么需要它
------------
宿主 `game/data`（74,707 行 / 87 文件）要删，而它的 87 张表通过聚合层 `C` 被包内代码引用了
1,510 处 / 248 个名字。本模块 = 空间族的「内容聚合门面」：把宿主 `C.<名>` 从**包内域 JSON**
重建出来，逐个对拍相等（含键序）。本模块**只读包内域**（`content/data/<域>.json`），
`import` 不碰宿主 `game.*`、不用 `_HostMod`/`_host_attr` —— 宿主表删掉之后它照样能活（I1/I2）。

名字 → 来源（逐条；实测见报告 `overnight/W-B14-A.md`）
------------------------------------------------------
| 名字 | 来源 | 派生规则 |
|---|---|---|
| `MAPS` / `MAP_BY_ID` / `SUBAREAS` | `worlds` · `subareas` · `exploration` 三域 | 序取 `exploration.order`；行 = 子区域域行去 `map` 键；`MAP_BY_ID` = `MAPS` 按 id 建索引 |
| `INSTANCES` | `instances` 域 | 槽位 id 还原：`monsters`/`elite`/`boss` ← `*_data`、`pois` ← `poi_data`；丢导出专用键 `boss_data`/`boss_equip_drop` |
| `INVESTIGATION_POINTS` | `instance_investigation` 域 | 按 `instance` 分组、组内按点 id 序；行去 `instance` 键 |
| `ENCY_MAP_MONSTERS` / `ENCY_MONSTER_MAP` / `ENCY_MATERIAL_SOURCE` | `worlds` + `subareas`（**全 628 条**） | 照抄宿主 `core/maps.build_ency()` 口径 |
| `MONSTER_LOCS` | `worlds` + `subareas`（**只基础 430 条**） | 照抄宿主 `core/maps.build_monster_locs()` 口径；「装配时机」见下 |
| `PORTALS` | `portals` 域 | 内容原样；键序显式声明（见 `_PORTAL_ORDER`） |

键序（导出契约 `sort_table` 把域外层键排成字典序，宿主是声明序）
----------------------------------------------------------------
* **`MAPS` / `SUBAREAS` / `MAP_BY_ID` / `ENCY_*` / `MONSTER_LOCS` 的序不用声明** ——
  `exploration` 域的 `order` 字段是**全局 0..627 唯一序**（实测：按它排序后的「图首现序」
  与「子区域全局序」和宿主 `MAPS` / `SUBAREAS` **逐项相同**）。这是本单元最大的一条发现：
  B13-L7 头注写「`MAPS` 迭代序不可逆」，那是**没看 `exploration.order`** —— 有了它就可逆。
* **三条序域里没有落点，本模块显式声明 + 漂移守卫**（与既有 `content/tables.py:JOB_ORDER` 同款）：
  `INSTANCES`（27）· `INVESTIGATION_POINTS`（22 组）· `PORTALS`（11）。声明序多一个/少一个
  → `raise`（防「加副本忘了改这里」= 静默漏条目 / 一览顺序漂移）。
  ⚠️ 这是 **I3（形状可逆）的现存违反**：域里缺 `seq`/`order` 字段，序只能靠包内声明兜住；
  建议导出器给这三个域补序字段（报告里已登记）。

装配时机（`MONSTER_LOCS` 与 `ENCY_*` **不同源**，实测数字）
---------------------------------------------------------
宿主 `game/core/maps.py` 在 `game/data/_assembly.py:9` 这一链上被 import，而网状房间
`EXTRA_SUBAREAS` 的并入在 `:97` —— 所以：

* `_build_monster_locs()`（＝本模块 `MONSTER_LOCS`）用的是**并入前**的 `SUBAREAS`（**430 条基础房间**）；
* `_build_ency()`（＝本模块三张 `ENCY_*`）在 `:126` 跑，用的是**并入后**的全量（**628 条**）。

包内怎么分辨「基础房间 vs 网状房间」：实测导出物里**网状房间一律带 `hidden`/`reveal` 键**
（160 + 38 = 198 条，无例外），**基础房间 430 条一律不带** —— 430 + 198 = 628 恰好对上。
判据用 `"hidden" in row`（域里唯一可用的 pre-merge 标记；建议将来在域里补 `mesh: true`）。
用错一边的实测后果：`MONSTER_LOCS` 会变 345 条（多 `噬根藤精` / `腐牙萨满·嚎骨`）、
174 个怪的地点列表不同 —— 所以这一层不许「顺手统一」。
"""
from __future__ import annotations

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))          # <pkg>/content


def _read(sub: str, name: str, default):
    """读包内 `content/<sub>/<name>.json`（缺文件 / 坏 JSON → default，不抛 —— 与 `content/tables.py` 同款）。"""
    try:
        with open(os.path.join(_HERE, sub, name), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                        # noqa: BLE001
        return default


# ============================================================
# ① 域（全是包内 JSON，零宿主依赖）
# ============================================================
_MAPS_DOM: dict = _read("data", "maps.json", {})                  # 形状：nodes/roles/topology/links
_SUBS_DOM: dict = _read("data", "subareas.json", {})              # 子区域行（含注入的 `map` 键）
_WORLDS_DOM: dict = _read("data", "worlds.json", {})              # 地图元数据（宿主 MAPS 行的 16 个字段）
_EXPL_DOM: dict = _read("data", "exploration.json", {})           # {map:subarea} → {map, region, hidden, order}
_PORTALS_DOM: dict = _read("data", "portals.json", {})            # 方碑：图 id → {name, icon}
_INST_DOM: dict = _read("data", "instances.json", {})             # 副本（槽位拆成 id + *_data）
_INV_DOM: dict = _read("data", "instance_investigation.json", {})  # 副本调查点（扁平 + `instance` 键）

# ============================================================
# ② 顺序真源：`exploration.order`（全局 0..627 唯一）
# ============================================================
def _explore_seq():
    """`exploration` 域的 `order` → (图序, {图: [子区域 id 声明序]})。

    `order` 是全局唯一整数（实测 0..627 无重复），按它排序即得宿主 `SUBAREAS` 的
    「图内子区域声明序」与「图的声明序」（= 宿主 `MAPS` 序）。两张宿主表都靠它可逆。
    """
    rows = []
    for key, ent in (_EXPL_DOM or {}).items():
        mid, _, sid = str(key).partition(":")
        rows.append((ent.get("order"), mid, sid or key))
    rows.sort(key=lambda t: (t[0] is None, t[0]))
    order, per_map = [], {}
    for _, mid, sid in rows:
        if mid not in per_map:
            per_map[mid] = []
            order.append(mid)
        per_map[mid].append(sid)
    return order, per_map


MAP_ORDER: list = []            # 图的声明序（宿主 MAPS 序）
_SUB_ORDER: dict = {}           # {图 id: [子区域 id 声明序]}


def _rows_of(mid: str) -> list:
    """该图的子区域域行（声明序；缺行静默跳过，与宿主 `SUBAREAS.get(mid) or []` 同义）。"""
    return [_SUBS_DOM[sid] for sid in _SUB_ORDER.get(mid, ()) if isinstance(_SUBS_DOM.get(sid), dict)]


def _sub_row(row: dict) -> dict:
    """域行 → 宿主行：只去掉导出注入的 `map` 键（**其余键与顺序原样**，含 `hidden`/`reveal`）。"""
    return {k: v for k, v in row.items() if k != "map"}


def _declared_order(order, present, what: str) -> list:
    """按**声明序**取键：`present` 里出现未声明的键 → `raise`（防静默漏条目 / 顺序漂移）。

    用在域外层键是字典序、而宿主是声明序、且域里没有序字段的三处（`subareas`/`instances`/
    `portals`/`instance_investigation`）—— 与既有 `content/tables.py:JOB_ORDER` 同款：
    加了一条内容忘了改声明序 → 大声报错，而不是悄悄少一条。
    """
    extra = [k for k in present if k not in order]
    if extra:
        raise ValueError("%s 域出现未声明顺序的键 %r —— 请同步 content/catalog_space.py 的声明序"
                         "（否则该条目被静默丢掉 / 顺序漂移）" % (what, extra))
    return [k for k in order if k in present]


MAP_ORDER, _SUB_ORDER = _explore_seq()

# ============================================================
# ②b `SUBAREAS` 的外层键序（**与 `MAPS` 序不是同一序**，实测）
# ============================================================
# 实测：宿主 `SUBAREAS` 的键序**按区域分块**（南境→中域→西境→北境→东境→翡翠海→无尽海→幽暗→风翼，
# 再跟 v6/v83 后加的零散块），而 `MAPS` 的序按章节推进 —— 两表从第 7 个键起就分叉
# （`SUBAREAS[7]='hill_mine'` vs `MAPS[7]='rust_dock'`）。包内 71 个域**没有一个**按这个序存储
# （已实测全库遍历序搜索：0 命中），所以只能显式声明（121 键，逐键抄录宿主 `game/data/subareas.py:4`）。
# ⚠️ 序**有行为**：宿主 `game/data/_assembly.py:235` 用 `for _sas in SUBAREAS.values()` 建怪物索引
# （同名怪取第一个 id）—— 换序 = 索引结果可能变。
# ⚠️ I3 违反登记（同 `_INSTANCE_ORDER`）：建议导出器给 `subareas` 域补 `seq`/图序字段；多/少一个图 `raise`。
_SUBAREAS_MAP_ORDER = (
    "oak_town", "oak_plain", "white_deer_forest", "white_deer", "emerald_forest", "misty_swamp",
    "goblin_camp", "hill_mine", "ironharbor", "harbor_docks", "sea_cave", "silver_brook",
    "silver_valley", "windmill_plain", "deer_fort", "maple_village", "rockfall_gorge", "boar_ridge",
    "dawn_city", "dawn_cathedral", "gold_plain", "white_abbey", "old_king_tomb", "border_castle",
    "silver_river", "secret_crypt", "knight_yard", "king_road", "holy_trial", "ironshield_town",
    "ironshield_hills", "old_battlefield", "moon_gate", "silverwood", "starlake", "moon_court",
    "elven_ruins", "ancient_tree", "star_song", "moon_glade", "emerald_valley", "moon_temple",
    "windvale", "moonshadow_wood", "frost_horn", "frost_field", "anvil_fort", "forge_valley",
    "black_forest", "cinder_mountain", "ash_temple", "abyss_gate", "frost_fang", "cold_ridge",
    "winter_lake", "frost_throne", "aurora_town", "permafrost_field", "frostwhisper_canyon",
    "dragon_pass", "dragon_ridge", "dragon_roost", "ancient_battlefield", "dragon_tomb",
    "dragon_kin", "bone_wild", "storm_cliff", "storm_throne", "redridge_plateau",
    "dragonsfall_valley", "jade_port", "shell_town", "coral_reef", "sunset_isle", "storm_strait",
    "mermaid_bay", "sunken_ship", "siren_nest", "nameless_harbor", "pearl_city", "mist_trench",
    "whale_domain", "shipwreck_graveyard", "storm_sea", "sea_god_temple", "deep_dragon_palace",
    "deep_tunnel", "under_market", "fungus_forest", "deep_lake", "molten_abyss", "gray_dwarf",
    "under_dragon", "ember_camp", "lava_bed", "abyss_altar", "abyss_throne", "wind_city",
    "cloud_sea", "storm_plateau", "eye_of_storm", "rainbow_cloud", "starlight_terrace",
    "cloud_sanctum", "lost_library", "ember_corridor", "silver_wind_road", "west_ridge_wilds",
    "dusk_ridge_road", "mist_tide_passage", "black_tide_strait", "dwarf_long_gallery",
    "cold_spine_snow_trail", "dragon_ridge_old_road", "dragonborn_valley_trail", "sky_ladder_path",
    "rust_dock", "candle_crypt", "thunder_mine", "whirl_arena", "blacktide_opera",
)

# ============================================================
# ③ SUBAREAS / MAPS / MAP_BY_ID
# ============================================================
# 宿主 `game/data/subareas.py:4` SUBAREAS（121 图 / 628 条；行 = 源行原样）
SUBAREAS: dict = {mid: [_sub_row(r) for r in _rows_of(mid)]
                  for mid in _declared_order(_SUBAREAS_MAP_ORDER, _SUB_ORDER, "subareas")}

# 宿主 `game/data/maps.py:3` MAPS（121 条；`_assembly.py:137` 注入 `subareas` 键 = 第 17 个字段）
MAPS: list = []
for _mid in MAP_ORDER:
    _ent = dict(_WORLDS_DOM.get(_mid) or {})
    _ent["subareas"] = SUBAREAS[_mid]
    MAPS.append(_ent)

# 宿主 `game/data/maps.py:2349` MAP_BY_ID（`_assembly.py:143-146` 用 MAPS 重建 → 键序 = MAPS 序）
MAP_BY_ID: dict = {m["id"]: m for m in MAPS}

# ============================================================
# ④ INSTANCES（槽位还原）
# ============================================================
# 声明序（= 宿主 `game/data/instances.py:44 INSTANCES` 的插入序，逐键抄录；域外层键是字典序）。
# ⚠️ I3 违反登记：`instances` 域没有序字段 → 序只能在这儿声明；域里多一个副本 `raise`。
# ⚠️ 这是**顺序声明**（不是数值/文案）：值全部来自 `instances` 域；声明只为「迭代序 = 宿主」。
_INSTANCE_ORDER = (
    "inst_goblin_camp", "inst_sea_cave", "inst_old_king_tomb", "inst_secret_crypt",
    "inst_elven_ruins", "inst_ash_temple", "inst_abyss_gate", "inst_dragon_tomb",
    "inst_deer_fort", "inst_holy_trial", "inst_moon_temple", "inst_frost_throne",
    "inst_storm_throne", "inst_sunken_ship", "inst_siren_nest", "inst_sea_god_temple",
    "inst_deep_dragon_palace", "inst_gray_dwarf", "inst_under_dragon", "inst_eye_of_storm",
    "inst_abyss_throne", "inst_cloud_sanctum", "inst_rust_dock", "inst_candle_crypt",
    "inst_thunder_mine", "inst_whirl_arena", "inst_blacktide_opera",
)
# 导出专用键（宿主 `INSTANCES` 没有）：槽位 id 的落地副本，只给编辑器读
_EXPORT_ONLY = ("boss_data", "boss_equip_drop")
# 层内导出专用键（宿主 stage 从来没有 `npc` 这个键，实测 6 层带它）
_STAGE_EXPORT_ONLY = ("npc",)
# 域把「**显式 None 的空槽位**」整个删掉了（导出器只写有值的槽位）。实测 81 层里有 20 处：
# 这 10 个副本的 层0 → `elite`+`boss` 为 None、层1 → `boss` 为 None、层2 → `elite` 为 None（规律一致）。
# ⚠️ I3 违反登记：域里看不出「有键且值为 None」与「没有这个键」的区别 → 只能显式声明。
#   正解 = 导出器保留 `elite: null`（一行）；真那么改之后下面的守卫会立刻报错，提醒删掉本表。
_NULL_SLOT_INSTANCES = (
    "inst_deer_fort", "inst_holy_trial", "inst_moon_temple", "inst_frost_throne",
    "inst_storm_throne", "inst_rust_dock", "inst_candle_crypt", "inst_thunder_mine",
    "inst_whirl_arena", "inst_blacktide_opera",
)
_NULL_SLOT_BY_STAGE = {0: ("elite", "boss"), 1: ("boss",), 2: ("elite",)}
_SLOT_KEYS = ("monsters", "elite", "boss")


def _slot_entry(src: dict, null_slots=()) -> dict:
    """通用槽位还原：域把「id 列表」与「落地数据」拆成 `k` / `k_data`（`pois` 的落地键名是 `poi_data`）。

    * 键序 = 域序去掉 `*_data`/`npc`（实测与宿主逐键同序）；有 `*_data` 就用它（宿主侧形态）。
    * `monsters`/`elite`/`boss` 三个槽位在宿主里是**连着**的（`name` 之后、`desc` 之前）；
      域里被删掉的空槽位（`null_slots`）在**首个出现的槽位处**按 `monsters→elite→boss` 补齐为 `None`。
    * 声明表与域冲突（域里已有该键）→ `raise`（说明导出器已改成保留 null，本表该删了）。
    """
    for s in null_slots:
        if s in src or (s + "_data") in src:
            raise ValueError("副本层 %r 在域里已有 `%s` 键 —— 导出器已保留空槽位，请删除 "
                             "content/catalog_space.py 的 _NULL_SLOT_* 声明表" % (src.get("name"), s))
    out: dict = {}
    placed = False
    for k, v in src.items():
        if k in _STAGE_EXPORT_ONLY or k.endswith("_data"):
            continue
        if k in _SLOT_KEYS:
            if not placed:                       # 三槽位一处在宿主里连着，插在首个出现的槽位处
                placed = True
                for s in _SLOT_KEYS:
                    if s in src:
                        data = src.get(s + "_data")
                        out[s] = data if data is not None else src[s]
                    elif s in null_slots:
                        out[s] = None
            continue
        data = src.get("poi_data") if k == "pois" else src.get(k + "_data")
        out[k] = data if data is not None else v
    return out


def _instance_entry(iid: str, src: dict) -> dict:
    """副本条目 → 宿主条目（丢导出专用键，`boss` 还原成 6 元组，层内槽位还原）。"""
    out: dict = {}
    for k, v in src.items():
        if k in _EXPORT_ONLY:
            continue
        if k == "stages":
            stages = [s for s in (v or []) if isinstance(s, dict)]
            if iid in _NULL_SLOT_INSTANCES and len(stages) > max(_NULL_SLOT_BY_STAGE) + 1:
                raise ValueError("%s 的层数 %d 超出 _NULL_SLOT_BY_STAGE 模板（%r）—— 请同步 "
                                 "content/catalog_space.py" % (iid, len(stages), _NULL_SLOT_BY_STAGE))
            ns = _NULL_SLOT_BY_STAGE if iid in _NULL_SLOT_INSTANCES else {}
            out[k] = [_slot_entry(s, ns.get(i, ())) for i, s in enumerate(stages)]
        elif k == "boss":
            out[k] = src.get("boss_data", v)
        else:
            out[k] = v
    return out


INSTANCES: dict = {iid: _instance_entry(iid, _INST_DOM[iid])
                   for iid in _declared_order(_INSTANCE_ORDER, _INST_DOM, "instances")}

# ============================================================
# ⑤ INVESTIGATION_POINTS（扁平域 → 按副本分组）
# ============================================================
# 声明序（= 宿主 `game/data/instance_investigation.py:60 INVESTIGATION_POINTS` 的插入序，逐键抄录；
# ⚠️ 同上：顺序声明，值与点序全部来自 `instance_investigation` 域）
_INVESTIGATION_ORDER = (
    "inst_goblin_camp", "inst_sea_cave", "inst_old_king_tomb", "inst_secret_crypt",
    "inst_elven_ruins", "inst_ash_temple", "inst_abyss_gate", "inst_dragon_tomb",
    "inst_deer_fort", "inst_holy_trial", "inst_moon_temple", "inst_frost_throne",
    "inst_storm_throne", "inst_sunken_ship", "inst_siren_nest", "inst_sea_god_temple",
    "inst_deep_dragon_palace", "inst_gray_dwarf", "inst_under_dragon", "inst_eye_of_storm",
    "inst_abyss_throne", "inst_cloud_sanctum",
)


def _investigation_points() -> dict:
    """`{副本 id: [ {id,name,hint,materials}… ]}` —— 组内按点 id 序（= 宿主列表序，实测 22 组 0 差异）。"""
    by_inst: dict = {}
    for row in (_INV_DOM or {}).values():
        if isinstance(row, dict) and row.get("instance"):
            by_inst.setdefault(row["instance"], []).append(row)
    out: dict = {}
    for iid in _declared_order(_INVESTIGATION_ORDER, by_inst, "instance_investigation"):
        out[iid] = [{k: v for k, v in r.items() if k != "instance"}
                    for r in sorted(by_inst[iid], key=lambda r: str(r.get("id")))]
    return out


INVESTIGATION_POINTS: dict = _investigation_points()

# ============================================================
# ⑥ PORTALS（内容在域里，键序显式声明）
# ============================================================
# 声明序（= 宿主 `game/data/portals.py:3 PORTALS` 的插入序：按区域分组，非字典序、也非图序）。
# ⚠️ I3 违反登记：`portals` 域没有序字段 → 序只能在这儿声明；域里多一个方碑 `raise`。
_PORTAL_ORDER = (
    "oak_town", "white_deer", "silver_brook", "dawn_city", "ironshield_town",
    "jade_port", "nameless_harbor", "frost_horn", "under_market", "dragon_pass", "wind_city",
)
PORTALS: dict = {k: _PORTALS_DOM[k] for k in _declared_order(_PORTAL_ORDER, _PORTALS_DOM, "portals")}

# ============================================================
# ⑦ 百科派生表（口径照抄宿主 `game/core/maps.py:218/:259`）
# ============================================================
_ENCY_MAP_MONSTERS: dict = {}
_ENCY_MONSTER_MAP: dict = {}
_ENCY_MATERIAL_SOURCE: dict = {}
MONSTER_LOCS: dict = {}


def _base_only(rows: list) -> list:
    """并入前的基础房间：域里**不带 `hidden` 键**的行（网状房间一律带 → 见文件头「装配时机」）。"""
    return [r for r in rows if "hidden" not in r]


def build_ency():
    """`ENCY_MAP_MONSTERS` / `ENCY_MONSTER_MAP` / `ENCY_MATERIAL_SOURCE` —— 用**全量 628 条**（宿主 `_assembly.py:126` 时机）。"""
    d_map_monsters = _ENCY_MAP_MONSTERS
    d_monster_map = _ENCY_MONSTER_MAP
    d_material_source = _ENCY_MATERIAL_SOURCE
    for mid in MAP_ORDER:
        mname_cn = (_WORLDS_DOM.get(mid) or {}).get("name")
        entries = []
        for sa in SUBAREAS.get(mid, []):
            for (_, mname, _role, lv, _sk, drops) in (sa.get("monsters") or []):
                d_monster_map.setdefault(mname, []).append((mname_cn, "普通"))
                for dd in drops:
                    d_material_source.setdefault(dd, []).append((mname_cn, mname))
                entries.append((mname, lv, "普通"))
            if sa.get("elite"):
                (_, estr, _r, elv, _s, edrops) = sa["elite"]
                d_monster_map.setdefault(estr, []).append((mname_cn, "精英"))
                for dd in edrops:
                    d_material_source.setdefault(dd, []).append((mname_cn, estr))
                entries.append((estr, elv, "精英"))
            if sa.get("boss"):
                (_, bstr, _r, blv, _s, bdrops) = sa["boss"]
                d_monster_map.setdefault(bstr, []).append((mname_cn, "首领"))
                for dd in bdrops:
                    d_material_source.setdefault(dd, []).append((mname_cn, bstr))
                entries.append((bstr, blv, "首领"))
        d_map_monsters[mid] = entries
        d_map_monsters[mname_cn] = entries          # 双 key：玩家输中文地图名也能查


def build_monster_locs():
    """`MONSTER_LOCS` —— 用**并入前的基础 430 条**（宿主 `core/maps.py:47` 的 import 期时机）。"""
    for mid in MAP_ORDER:
        mname_cn = (_WORLDS_DOM.get(mid) or {}).get("name")
        for sa in _base_only(SUBAREAS.get(mid, [])):
            sa_name = sa.get("name") or sa.get("id", "")
            for (_, mname, _r, lv, _s, _d) in (sa.get("monsters") or []):
                MONSTER_LOCS.setdefault(mname, []).append((sa_name, mname_cn, lv, "普通"))
            if sa.get("elite"):
                (_, estr, _r, elv, _s, _d) = sa["elite"]
                MONSTER_LOCS.setdefault(estr, []).append((sa_name, mname_cn, elv, "精英"))
            if sa.get("boss"):
                (_, bstr, _r, blv, _s, _d) = sa["boss"]
                MONSTER_LOCS.setdefault(bstr, []).append((sa_name, mname_cn, blv, "首领"))


build_ency()
build_monster_locs()

ENCY_MAP_MONSTERS = _ENCY_MAP_MONSTERS
ENCY_MONSTER_MAP = _ENCY_MONSTER_MAP
ENCY_MATERIAL_SOURCE = _ENCY_MATERIAL_SOURCE


# 缺口（域里没有真源 → 本模块**不造第二份表**；详见报告 `overnight/W-B14-A.md`）
GAPS: tuple = (
    "MAP_CONNECTIONS", "POIS", "LEGACY_MAP_ALIAS", "HIDDEN_MAP_UNLOCK",
    "WORLD_EVENT_POOL", "AUCTION_POOL", "WORLD_BOSS_POOL",
    "WISH_POOL", "CAMPFIRE_FOOD_POOL", "HERB_POOL", "INVESTIGATE_COLLECT_SAMPLES",
)

__all__ = [
    "MAPS", "MAP_BY_ID", "SUBAREAS", "INSTANCES", "INVESTIGATION_POINTS", "PORTALS",
    "ENCY_MAP_MONSTERS", "ENCY_MONSTER_MAP", "ENCY_MATERIAL_SOURCE", "MONSTER_LOCS",
    "MAP_ORDER", "build_ency", "build_monster_locs", "GAPS",
]
