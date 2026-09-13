# -*- coding: utf-8 -*-
"""B14-E 常量数值族门面 —— 宿主聚合层 `game.content`（`C`）的**包内等价物**（45 个数据名）。

背景
----
宿主 `game/data`（74,707 行 / 87 文件）要删，而全仓 **586 处**引用了这 45 个名字。
本模块把它们从**包内域文件**重建出来，逐个与宿主 `C.<名>` 对拍（含 dict 键插入序）。

边界（B14_BRIEF §3 硬约束）
--------------------------
* 只读包内数据：`content/data|rules/*.json` + 既有读口 `content/tables.py` ·
  `content/constants.py` · `content/skills.py` · `content/stats.py`（全是包内单源，本模块只读、不改）。
* **禁 import 宿主 `game.*`**、**禁 `_HostMod`/`_host_attr`**（宿主表删掉后本模块仍要能活）。
* 零数值改写：本模块只做「取表 / 还原键型 / 还原序 / 建索引」，数值全部来自域文件。

45 个数据名的来源与派生规则
--------------------------
| 分组 | 名字 | 来源 | 处理 |
|---|---|---|---|
| A 面板读口 | `CLASS_NOVICE` `PCT_STATS` `PCT_CAPS` `PENE_PCT_STATS` | `content/tables.py`（解 `rules/panel_rules.json`） | 直接复用 |
| B 常量单源 | `START_MAP/SUBAREA` `MAP_TYPE_*` `SUB_TYPE_TOWN` `ITEM_TYPE_*` `MATERIAL_KIND_TYPES` `DEFAULT_MAX_MP` `EVOLVE_LEVELS/FEES` `RESET_SKILL_COST` `PVP_TIMEOUT_SEC` `OPTIONAL_STATS` `GUILD_EXP_BASE` `RECIPE_LV_TIERS` `*_CHANCE`(9) + `prof_exp_need` | `content/constants.py`（B13-L6 已整块进包） | 直接复用（同为「常量」族，不造第二份） |
| C 配置域 | `MASTERPIECE_CHANCE` `QUALITY_UPGRADE_CHANCE/COST/MASTER_BONUS` | `content/rules/game_config.json` → `battle_config` 组（= 宿主 `game/data/battle_config.py` 的常量组） | 取组内同名键 |
| D 职业/种族 | `CLASSES` `RACES` | `content/data/classes.json` · `races.json` | 还原顶层声明序（域是字典序）+ `evolve_branches` 整数档位键 + `tutor` 元组 |
| E 技能三表 | `PLAYER_SKILLS` `BRANCH_SKILLS` `TUTOR_SKILLS` | `content/skills.py`（三表逆折，源自 `content/data/skills.json`） | 还原职业序 / 档位整数键 / 分支线序 / 表内 lv 序 |
| F 数值函数 | `exp_to_next` `equip_stats` `equip_value` | `content/stats.py`（B13-L6 已进包） | 惰性转发（本模块 import 期不碰宿主） |

序的还原规则（门禁比键序，漂了就报红）
------------------------------------
* `CLASSES` 顶层序 = `("cls_novice",) + tables.JOB_ORDER`（JOB_ORDER 是 `job_guide` 域的
  展示序声明，同库同源；实测 == 宿主 `C.CLASSES` 的插入序）。
* `RACES` 顶层序 = 本模块显式声明 `RACE_ORDER`（域文件键是字典序，序在域里没处存；
  照 `content/tables.py:JOB_ORDER` 的先例「顺序只能显式声明」+ 域里多/少种族即 raise）。
* `PLAYER_SKILLS`/`BRANCH_SKILLS`/`TUTOR_SKILLS`：外层按职业序（JOB_ORDER / 导师表键集声明），
  内层按 **`(低阶纯魔法输出技先, lv, 技能键)` 升序**（`_skill_seq`；实测 53/53 张表与宿主声明序相同：
  玩家 7/7 · 分支 42/42 条线 · 导师 4/4 张表）。这是**经验规则**（域里没存序）→ 建议域侧补序字段（见下）。
* `BRANCH_SKILLS` 分支线序 = `classes.json[cid].evolve_branches["1"]`（实测 7/7 职业、全部档位一致）。

已知缺口（门禁红项，报告 `overnight/W-B14-E.md` 有字段清单）
----------------------------------------------------------
1. `QUALITY`（5 档 {mult,color,name}）**未在本模块暴露**：包内 66 域**没有**这张表
   （实测：全包 JSON 无任何含 `white/green/blue` 键或 `color` 字段的品质表；`content/stats.py`
   的 `QUALITY` 是宿主句柄 `_D.QUALITY`，按硬约束不可用）。宿主真源 = `game/data/equipment.py:13`
   —— 同一个宿主模块的 `EQUIP_SLOTS`/`QUALITY_ORDER`/`WEAPON_FLAVOR` 已被 B 单元登记为「无域」
   （`content/catalog_items.py:50`），所以这是**域侧缺口**，需新域导出（见报告）。
2. **建议（不是红项）**：技能三表的表内序目前靠 `_skill_seq` 经验规则复原。权威做法 = 给
   `content/data/skills.json` 每条补一个**声明序字段**（真源 `game/data/skills.py` 的表内次序），
   门面改成读字段即可；同理 `classes.json` 的 8 职业条目里 `evolve_branches` 的整数档位键、
   `tutor` 元组建议在导出层直接还原（现由本模块还原）。
3. 本单元 `func` 那 10 个函数（`display`/`resolve`/`build_monster`/`roll_blueprint`/
   `generate_equip`/`generate_roster_equip`/`build_monster_group`/`roll_drop_equip`/
   `make_blueprint`/`roll_drop`）**不属于本段**（见报告「待函数单元」）。
4. 依赖登记：`content/constants.py::prof_exp_need` 与 `content/stats.py` 的函数内部仍走宿主句柄
   读 `FORMULA_SKELETON` / 怪物数值表（B13 已登记的缺口），本模块只是转发，不新增宿主依赖。
"""
from __future__ import annotations

import json
import os

from . import constants as _K
from . import skills as _SK
from . import tables as _T

_HERE = os.path.dirname(os.path.abspath(__file__))
_RULES_DIR = os.path.join(_HERE, "rules")


def _read_json(path: str, default):
    """读包内 JSON（缺文件 / 坏 JSON → default，不抛；与 `content/tables.py::_read_json` 同款）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                        # noqa: BLE001
        return default


# ============================================================
# ① 面板读口（A 组）—— 直接复用 `content/tables.py`（解 rules/panel_rules.json）
# ============================================================
CLASS_NOVICE = _T.CLASS_NOVICE            # "cls_novice" 见习兜底
PCT_STATS = _T.PCT_STATS                  # 23 项百分比显示属性（tuple，保序）
PCT_CAPS = _T.PCT_CAPS                    # 23 项百分比上限（dict，插入序 = 真源序）
PENE_PCT_STATS = _T.PENE_PCT_STATS        # 2 项百分比穿透（tuple）

# ============================================================
# ② 常量单源（B 组）—— 直接复用 `content/constants.py`（B13-L6 已整块进包）
# ============================================================
START_MAP = _K.START_MAP
START_SUBAREA = _K.START_SUBAREA
MAP_TYPE_TOWN = _K.MAP_TYPE_TOWN
MAP_TYPE_FIELD = _K.MAP_TYPE_FIELD
MAP_TYPE_INSTANCE = _K.MAP_TYPE_INSTANCE
SUB_TYPE_TOWN = _K.SUB_TYPE_TOWN
ITEM_TYPE_PET_EGG = _K.ITEM_TYPE_PET_EGG
ITEM_TYPE_MOUNT = _K.ITEM_TYPE_MOUNT
MATERIAL_KIND_TYPES = _K.MATERIAL_KIND_TYPES          # frozenset（集合比较，无序）
DEFAULT_MAX_MP = _K.DEFAULT_MAX_MP
EVOLVE_LEVELS = _K.EVOLVE_LEVELS                      # {1:30, 2:60, 3:90}（int 键）
EVOLVE_FEES = _K.EVOLVE_FEES                          # {1:500, 2:2000, 3:5000}
RESET_SKILL_COST = _K.RESET_SKILL_COST
PVP_TIMEOUT_SEC = _K.PVP_TIMEOUT_SEC
OPTIONAL_STATS = _K.OPTIONAL_STATS                    # tuple（23 项，保序）
GUILD_EXP_BASE = _K.GUILD_EXP_BASE
RECIPE_LV_TIERS = _K.RECIPE_LV_TIERS                  # tuple(10,30,50,70,90)
ENCOUNTER_EVENT_CHANCE = _K.ENCOUNTER_EVENT_CHANCE
SA_BOSS_CHANCE = _K.SA_BOSS_CHANCE
PET_EGG_ORANGE_CHANCE = _K.PET_EGG_ORANGE_CHANCE
RARE_MAT_CHANCE = _K.RARE_MAT_CHANCE
PROF5_BONUS_CHANCE = _K.PROF5_BONUS_CHANCE
INST_EVENT_CHANCE = _K.INST_EVENT_CHANCE
TRADER_DEAL_CHANCE = _K.TRADER_DEAL_CHANCE
CHEST_BP_CHANCE = _K.CHEST_BP_CHANCE
INSTANCE_BP_CHANCE = _K.INSTANCE_BP_CHANCE
ELITE_EQ_DROP_CHANCE = _K.ELITE_EQ_DROP_CHANCE
prof_exp_need = _K.prof_exp_need                      # 函数（副业升级经验曲线，读 FORMULA_SKELETON）

# ============================================================
# ③ 配置域常量组（C 组）—— `content/rules/game_config.json` → `battle_config`
# ------------------------------------------------------------
# 该域一条 = 一个宿主源模块的常量组（`{模块名: {常量名: 值}}`，导出器
# `scripts/export_domains/b9_l7_domains.py:derive_game_config`）→ 组内键名与宿主
# `game/data/battle_config.py` 顶层常量名一一对应，取值原样（无换算）。
# ============================================================
_BATTLE_CONFIG: dict = dict((_read_json(os.path.join(_RULES_DIR, "game_config.json"), {})
                             or {}).get("battle_config") or {})


def _bc(name: str, default=None):
    """取 `game_config.battle_config` 组里的常量（缺 → default，绝不猜值）。"""
    return _BATTLE_CONFIG.get(name, default)


MASTERPIECE_CHANCE = _bc("MASTERPIECE_CHANCE")                       # 橙装「杰作」判定
QUALITY_UPGRADE_CHANCE = _bc("QUALITY_UPGRADE_CHANCE")               # 品质提升概率
QUALITY_UPGRADE_MASTER_BONUS = _bc("QUALITY_UPGRADE_MASTER_BONUS")   # 神锻名家加成
QUALITY_UPGRADE_COST = _bc("QUALITY_UPGRADE_COST")                   # {材料 id: 数量}（插入序保真）

# ============================================================
# ④ 职业 / 种族（D 组）—— 还原「声明序 + 键型」
# ------------------------------------------------------------
# 域文件（导出契约 `sort_table`）是**字典序**，真源插入序在域里没处存 → 显式声明；
# 域里多/少职业（种族）就 raise —— 防「加了新职业却静默漏掉 / 顺序漂移」。
# ============================================================
CLASS_ORDER = ("cls_novice",) + tuple(_T.JOB_ORDER)
# 种族展示序（建号选种族 / 种族天赋一览的遍历序）—— 真源 `game/data/races.py` 声明序；
# 域文件键是字典序，序只能显式声明（同 `content/tables.py:JOB_ORDER` 先例）。
RACE_ORDER = ("human", "elf", "dwarf", "orc", "halfling", "dragonborn")


def _restore_class_entry(entry) -> dict:
    """职业条目：还原 `evolve_branches` 的**整数档位键**（JSON 只有字符串键）与 `tutor` 元组。

    实测（对拍宿主 `C.CLASSES`）：8 个职业条目里只有这两处形状差异 ——
      * `evolve_branches` 宿主是 `{1: [...], 2: [...], 3: [...]}`，域里是 `"1"/"2"/"3"`；
      * `tutor` 宿主是 **tuple**（`("导师名", "地点")`），域里是 list。
    其余字段的键与键序与宿主逐字相同（逐职业对拍 0 差异）。
    """
    e = dict(entry)
    eb = e.get("evolve_branches")
    if isinstance(eb, dict):
        e["evolve_branches"] = {(int(k) if str(k).lstrip("-").isdigit() else k): list(v or [])
                                for k, v in eb.items()}
    if isinstance(e.get("tutor"), list):
        e["tutor"] = tuple(e["tutor"])
    return e


CLASSES: dict = {}
for _cid in CLASS_ORDER:
    if _cid in _T.CLASSES:
        CLASSES[_cid] = _restore_class_entry(_T.CLASSES[_cid])
_missing_cls = [c for c in _T.CLASSES if c not in CLASS_ORDER]
if _missing_cls:
    raise ValueError("classes 域出现未声明顺序的职业 %s —— 请同步 content/catalog_core.py:CLASS_ORDER"
                     "（否则该职业在本门面里被静默丢掉）" % _missing_cls)
_missing_cls2 = [c for c in CLASS_ORDER if c not in _T.CLASSES]
if _missing_cls2:
    raise ValueError("classes 域缺职业 %s（真源 C.CLASSES 有）—— 域不完整，拒绝静默少键" % _missing_cls2)

RACES: dict = {}
for _rid in RACE_ORDER:
    if _rid in _T.RACES:
        RACES[_rid] = _T.RACES[_rid]
_missing_race = [r for r in _T.RACES if r not in RACE_ORDER]
if _missing_race:
    raise ValueError("races 域出现未声明顺序的种族 %s —— 请同步 content/catalog_core.py:RACE_ORDER"
                     "（否则该种族在本门面里被静默丢掉）" % _missing_race)

# ============================================================
# ⑤ 技能三表（E 组）—— `content/skills.py` 的逆折结果，只重排**序**
# ------------------------------------------------------------
# 值一律复用 `content/skills.py`（包内单源，逆折自 `content/data/skills.json`）；
# 本模块只做三件事：外层职业序、分支线序、表内 `(lv, 技能键)` 序。
# ============================================================
def _skill_seq(entry) -> int:
    """技能在**表内**的排序桶：0 = 低阶纯魔法输出技（`kind == "魔法"` 且 `lv <= 8`），1 = 其余。

    为什么需要它：真源三表是**声明序**（`game/data/skills.py` 里手写顺序），导出器落盘的
    `skills.json` 是字典序 → 位置信息在域里没处存。实测规律（53/53 张表与宿主声明序逐一相同）：
    牧师/吟游诗人把「基础输出技」写在表首 —— `cls_mu_shi` 圣光弹(lv1)+圣光惩击(lv8)、
    `cls_shi_ren` 锁音(lv1)+破音(lv4)+共振(lv8) 这 5 把是**唯一的** kind=="魔法" 且 lv<=8 的副本；
    其余 5 个职业没有这样的技能（法师的 kind 是 `魔法·火/冰/雷`，不落桶）→ 纯 lv 升序。
    命中率：玩家 7/7 · 分支 42/42 条线 · 导师 4/4 张表（脚本 `overnight/b14_e_probe11.py`）。
    ⚠ 这是**经验规则**（域里没有序字段）：更正的权威做法是给 `skills.json` 每条补声明序字段，
    届时把本函数换成读字段即可 —— 见报告 `overnight/W-B14-E.md` §缺口。
    """
    if not isinstance(entry, dict):
        return 1
    return 0 if (entry.get("kind") == "魔法" and entry.get("lv", 0) <= 8) else 1


def _by_lv(skills: dict) -> dict:
    """表内序 = `(桶, lv, 技能键)` 升序（桶见 `_skill_seq`；同级再按键，ASCII/中文原样比）。"""
    return {k: v for k, v in sorted((skills or {}).items(),
                                    key=lambda kv: (_skill_seq(kv[1]), kv[1].get("lv", 0) if isinstance(kv[1], dict) else 0, kv[0]))}


PLAYER_SKILLS: dict = {}
for _cid in _T.JOB_ORDER:
    _ent = _SK.PLAYER_SKILLS.get(_cid)
    if _ent is None:
        continue
    _e = dict(_ent)
    _e["skills"] = _by_lv(_ent.get("skills"))
    PLAYER_SKILLS[_cid] = _e


def _branch_line_order(cid: str) -> list:
    """分支线序 = `classes.json[cid].evolve_branches["1"]`（实测 7/7 职业、全档位一致）。

    宿主 `BRANCH_SKILLS[cls]["branches"][tier]` 的线键是**一档线名**（如「狂战士」），
    二/三档也用一档名做键（档位差异体现在技能内容上），所以一档名单就是全档位的线序。
    """
    eb = (_T.CLASSES.get(cid) or {}).get("evolve_branches") or {}
    return list(eb.get("1") or [])


BRANCH_SKILLS: dict = {}
for _cid in _T.JOB_ORDER:
    _ent = _SK.BRANCH_SKILLS.get(_cid)
    if _ent is None:
        continue
    _lines = _branch_line_order(_cid)
    _tiers = {}
    for _tier in sorted((_ent.get("branches") or {}), key=lambda t: (isinstance(t, str), t)):
        _host_tiers = _ent["branches"][_tier]
        _ordered = {}
        for _line in _lines:
            if _line in _host_tiers:
                _ordered[_line] = _by_lv(_host_tiers[_line])
        _extra_lines = [l for l in _host_tiers if l not in _lines]
        if _extra_lines:
            raise ValueError("职业 %s 档位 %s 出现未在 evolve_branches['1'] 声明的分支线 %s"
                             " —— 域结构变了，拒绝静默丢线" % (_cid, _tier, _extra_lines))
        _tiers[int(_tier) if str(_tier).lstrip("-").isdigit() else _tier] = _ordered
    _e = dict(_ent)
    _e["branches"] = _tiers
    BRANCH_SKILLS[_cid] = _e

# 导师技表：真源 `game/data/skills.py:4172 TUTOR_SKILLS` 声明 **6 键**
# （`cls_zhan_shi` / `cls_you_xia` 是两张**空表**，吟游诗人 `cls_shi_ren` 没有导师表）
# —— 域里没有这个「表键集声明」（空表在域里无条目，产不出键），故本门面显式声明 + 自检。
TUTOR_TABLE_CLASSES = tuple(c for c in _T.JOB_ORDER if c != "cls_shi_ren")
_extra_tutor = [c for c in _SK.TUTOR_SKILLS if c not in TUTOR_TABLE_CLASSES]
if _extra_tutor:
    raise ValueError("skills 域出现未在 TUTOR_TABLE_CLASSES 声明的导师技职业 %s"
                     " —— 请同步 content/catalog_core.py:TUTOR_TABLE_CLASSES" % _extra_tutor)
TUTOR_SKILLS: dict = {c: _by_lv(_SK.TUTOR_SKILLS.get(c) or {}) for c in TUTOR_TABLE_CLASSES}

# ============================================================
# ⑥ 数值函数（F 组）—— 惰性转发到 `content/stats.py`（B13-L6 已进包的单源）
# ------------------------------------------------------------
# 惰性：本模块 import 期不触碰 stats 模块（后者模块级要解宿主句柄读怪物数值表 —— B13 已登记
# 的缺口），宿主表删掉后「本模块能 import」不受影响；调用方用到函数时才会真正取件。
# ============================================================
def exp_to_next(level, *args, **kwargs):
    """升到下一级所需经验 —— 单源 `content/stats.py::exp_to_next(level)`（逐字搬自 `game/core/stats.py`）。"""
    from .stats import exp_to_next as _f
    return _f(level, *args, **kwargs)


def equip_stats(slot, lv, quality, *args, **kwargs):
    """装备属性公式 —— 单源 `content/stats.py::equip_stats(slot, lv, quality, …)`（签名/语义同真源）。"""
    from .stats import equip_stats as _f
    return _f(slot, lv, quality, *args, **kwargs)


def equip_value(stats, *args, **kwargs):
    """装备估值（价签 / 回收价）—— 单源 `content/stats.py::equip_value(stats)`。"""
    from .stats import equip_value as _f
    return _f(stats, *args, **kwargs)


# 缺口登记（不暴露 = 不猜值；门禁报 `门面缺 1`，报告 `overnight/W-B14-E.md` 给字段清单）
GAP_QUALITY = ("QUALITY：包内无域。需要新域（建议 `quality`，或 game_config 增 `equipment` 组）导出 "
               "宿主 `game/data/equipment.py:13 QUALITY`：5 键 white/green/blue/purple/orange（声明序保鲜）"
               " × {mult(float), color(str 单字符 emoji), name(str 中文)}。")

__all__ = [
    # A 面板读口
    "CLASS_NOVICE", "PCT_STATS", "PCT_CAPS", "PENE_PCT_STATS",
    # B 常量单源
    "START_MAP", "START_SUBAREA", "MAP_TYPE_TOWN", "MAP_TYPE_FIELD", "MAP_TYPE_INSTANCE",
    "SUB_TYPE_TOWN", "ITEM_TYPE_PET_EGG", "ITEM_TYPE_MOUNT", "MATERIAL_KIND_TYPES",
    "DEFAULT_MAX_MP", "EVOLVE_LEVELS", "EVOLVE_FEES", "RESET_SKILL_COST", "PVP_TIMEOUT_SEC",
    "OPTIONAL_STATS", "GUILD_EXP_BASE", "RECIPE_LV_TIERS", "ENCOUNTER_EVENT_CHANCE",
    "SA_BOSS_CHANCE", "PET_EGG_ORANGE_CHANCE", "RARE_MAT_CHANCE", "PROF5_BONUS_CHANCE",
    "INST_EVENT_CHANCE", "TRADER_DEAL_CHANCE", "CHEST_BP_CHANCE", "INSTANCE_BP_CHANCE",
    "ELITE_EQ_DROP_CHANCE", "prof_exp_need",
    # C 配置域常量组
    "MASTERPIECE_CHANCE", "QUALITY_UPGRADE_CHANCE", "QUALITY_UPGRADE_MASTER_BONUS",
    "QUALITY_UPGRADE_COST",
    # D 职业 / 种族
    "CLASSES", "RACES", "CLASS_ORDER", "RACE_ORDER",
    # E 技能三表
    "PLAYER_SKILLS", "BRANCH_SKILLS", "TUTOR_SKILLS", "TUTOR_TABLE_CLASSES",
    # F 数值函数
    "exp_to_next", "equip_stats", "equip_value",
    # 缺口登记
    "GAP_QUALITY",
]
