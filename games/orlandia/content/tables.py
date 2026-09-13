# -*- coding: utf-8 -*-
"""包内面板表门面（`content/tables.py`）—— 游戏仓 `game/content.py`（聚合层 `C`）的包内等价物。

为什么需要它
------------
包内 `content/panel.py` 是从游戏仓 `game/content_rules/panel.py`（584 行）**逐字**搬来的，
原文读 `C.CLASSES` / `C.RACES` / `C.SETS` / `C.ENHANCE_TABLE` / `C.PCT_STATS` / `C.PCT_CAPS` /
`C.PENE_PCT_STATS`，以及 `C.resolve("classes", …)` / `C.display("skills", …)`
（= 游戏仓 `game/content.py` 那个薄聚合层）。包内没有那层（数据是 JSON 域文件），
本模块就是它 —— **面板唯一的读表口**，只做三件事：

  1. 读包内域文件（`content/data|rules/<域>.json`；缺文件/坏 JSON → `{}`，不抛 ——
     与包内 `apply.py` 的 `_read_json` 同款；「读不到就空」的分支游戏仓本来也有）；
  2. **还原 int 键**（`ENHANCE_TABLE` / `TIER_GROWTH` / `BRANCH_BONUS(_BY_CLASS)`）：
     JSON 只有字符串键，而面板原文写的是 `.get(enh)` / `.get(evolve_path)`（int 入参）——
     不还原 = 恒定 `None` = **强化 / 转职 / 分支三个乘区静默归零**（本批最容易踩的坑；
     导出器 `derive_enhance_table` / `derive_panel_rules` 的 docstring 各写了一遍）；
  3. `resolve` / `display` / `skill_info` 三个查询，语义照抄游戏仓
     `game/core/index.py:47`（resolve/display）与 `game/content_rules/skills.py:104`
     （skill_info）。包内 `skills.json` 是三张玩家技能表（基础/分支/导师）**扁平化**的产物，
     条目自带 `owner_class` —— 「不归本职业 → 查不到」靠它，不再按职业分表。

域来源（真源 = 游戏仓；单向导出器 = 游戏仓 `scripts/export_game_package.py`）
----------------------------------------------------------------------------
    content/data/classes.json         ← `derive_classes`       职业 base/growth/evolve_branches…
    content/data/skills.json          ← `derive_skills`        305 条技能（owner_class / kind / passive）
    content/data/races.json           ← `derive_races`         6 条种族天赋
    content/data/sets.json            ← `derive_sets`          92 条套装（区域套 + 职业套）
    content/data/enhance_table.json   ← `derive_enhance_table` 10 行强化乘区（键 = 强化等级）
    content/rules/panel_rules.json    ← `derive_panel_rules`   7 组面板公式常量（档位/分支/成长/百分比域）

**不改形状**：本模块只做「取值 / 还原键型 / 建索引」，零默认值、零数值改写（数值全在导出物里）。
"""
from __future__ import annotations

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))          # <pkg>/content
_DATA_DIR = os.path.join(_HERE, "data")
_RULES_DIR = os.path.join(_HERE, "rules")

# 见习兜底职业 id（游戏仓 `game/core/constants.py:84 CLASS_NOVICE`；包内 classes 域里就是这把键）
# 未知/脏 class_name 时面板兜底用它（见 panel.py:player_base_stats 的 v105 P1 兜底）。
CLASS_NOVICE = "cls_novice"


def _read_json(path: str, default):
    """读一个 JSON 文件（缺文件 / 坏 JSON / 权限 → default，不抛）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                        # noqa: BLE001
        return default


def _read_domain(domain: str, sub: str, default):
    """读包内 `content/<sub>/<domain>.json`（`sub` = data|rules）。"""
    return _read_json(os.path.join(_HERE, sub, f"{domain}.json"), default)


# ============================================================
# ① 已进包的域（D1/D2 就在包里，面板与战斗共用）
# ============================================================
CLASSES: dict = _read_domain("classes", "data", {})
SKILLS: dict = _read_domain("skills", "data", {})

# ============================================================
# ② 本批新域（D3 面板批次：职业面板完整版依赖的四族数据）
# ============================================================
RACES: dict = _read_domain("races", "data", {})
SETS: dict = _read_domain("sets", "data", {})
_ENHANCE_RAW: dict = _read_domain("enhance_table", "data", {})
_PANEL_RULES: dict = _read_domain("panel_rules", "rules", {})


def _int_keys(tbl) -> dict:
    """字符串键 → int 键（JSON 只有 str 键；非整数键**原样保留**，不静默丢）。"""
    out: dict = {}
    for k, v in (tbl or {}).items():
        try:
            out[int(k)] = v
        except (TypeError, ValueError):
            out[k] = v
    return out


# 强化等级 → {rate, cost, mult}（面板读 [k]["mult"]；原文是 .get(int)）
ENHANCE_TABLE: dict = _int_keys(_ENHANCE_RAW)
# 转职档位 → 成长倍率（原文 .get(tier, 1.0)）
TIER_GROWTH: dict = _int_keys(_PANEL_RULES.get("tier_growth"))
# 分支档位 → 属性倍率（通用回退档 + 职业×分支权威表，原文都按 int 档位查）
BRANCH_BONUS: dict = _int_keys(_PANEL_RULES.get("branch_bonus"))
BRANCH_BONUS_BY_CLASS: dict = {
    cls: _int_keys(m)
    for cls, m in (_PANEL_RULES.get("branch_bonus_by_class") or {}).items()
}
# 成长结构声明（键集 / 分支修正模式 / 输出别名）—— 原样带出，形状与游戏仓 `PLAYER_BASE_GROWTH` 同
PLAYER_BASE_GROWTH: dict = dict(_PANEL_RULES.get("base_growth") or {})
# 百分比域（原文用 `in` / `.get(k, 默认)`；tuple 保序、语义与源表一致）
PCT_CAPS: dict = dict(_PANEL_RULES.get("pct_caps") or {})
PCT_STATS: tuple = tuple((_PANEL_RULES.get("pct_stats") or {}).get("stats") or ())
PENE_PCT_STATS: tuple = tuple((_PANEL_RULES.get("pene_pct_stats") or {}).get("stats") or ())

# 「面板真正要用的域」清单 —— `missing_domains()` 与验收脚本按它点名核对（缺表 = 面板变白板）
REQUIRED_DOMAINS = ("classes", "skills", "races", "sets", "enhance_table", "panel_rules")


def missing_domains() -> list:
    """缺哪张面板表（文件不在 / 坏 JSON / 空表）。空表**不抛**（沿用包内 `_read_json` 口径），
    但要有地方能点出来 —— 「静默变白板」比报错难查得多。"""
    out = []
    for dom, sub, tbl in (("classes", "data", CLASSES), ("skills", "data", SKILLS),
                          ("races", "data", RACES), ("sets", "data", SETS),
                          ("enhance_table", "data", _ENHANCE_RAW),
                          ("panel_rules", "rules", _PANEL_RULES)):
        if not isinstance(tbl, dict) or not tbl:
            out.append(dom)
    return out


# ============================================================
# ③ 查询（名字 ↔ id ↔ 条目）—— 语义照抄游戏仓，零自创
# ============================================================
def _name_index(table: dict) -> dict:
    """名字 → key 索引（`game/core/index.py:19 build_index(name_field="name")` 的等价物）。"""
    idx: dict = {}
    for k, v in (table or {}).items():
        nm = v.get("name") if isinstance(v, dict) else None
        if nm and nm not in idx:      # 首个赢（与 build_index 一致）
            idx[nm] = k
    return idx


def _id_index(table: dict) -> dict:
    """key → 名字索引（显示名；条目没 name 字段时回落 key）。"""
    return {k: (v.get("name") if isinstance(v, dict) and v.get("name") else k)
            for k, v in (table or {}).items()}


_CLASSES_BY_NAME = _name_index(CLASSES)
_CLASSES_BY_ID = _id_index(CLASSES)
_SKILLS_BY_NAME = _name_index(SKILLS)
_SKILLS_BY_ID = _id_index(SKILLS)


def resolve(table_name: str, name_or_id: str):
    """名字或 id → id（找不到**原样返回**）—— `game/core/index.py:47` 同义。"""
    if table_name == "classes":
        return _CLASSES_BY_NAME.get(name_or_id, name_or_id)
    if table_name == "skills":
        return _SKILLS_BY_NAME.get(name_or_id, name_or_id)
    return name_or_id


def display(table_name: str, entity_id: str):
    """id → 显示名（找不到**原样返回**）—— `game/core/index.py:52` 同义。"""
    if table_name == "classes":
        return _CLASSES_BY_ID.get(entity_id, entity_id)
    if table_name == "skills":
        return _SKILLS_BY_ID.get(entity_id, entity_id)
    return entity_id


def skill_info(class_name: str, skill_name: str):
    """技能详情（`game/content_rules/skills.py:104 skill_info` 的包内等价）。

    包内 `skills.json` 是基础/分支/导师三张表的**扁平化**产物（条目带 `owner_class`），
    所以「先查基础职业表、再查分支表、再查导师表」这条链退化成「一次查表 + 归属校验」。
    ⚠️ `class_name` 要先 `resolve` 成职业 id 再比 `owner_class`：真源每一处查表都先
    `C.resolve("classes", class_name)`（`_sk_table` 内部就带），所以**中文职业名**在真源里
    是能命中的；包内若拿中文名直接比 id，会恒不命中 → 被动段静默归零（实测：本条是
    `d3_panel_verify.py` 抓出来的端口差异，别把 resolve 删了）。
    查不到 / 不归本职业 → `None`（与真源同义：调用方本来就 if not info 跳过）。
    """
    info = SKILLS.get(resolve("skills", skill_name))
    if info is None:
        info = SKILLS.get(skill_name)
    if not isinstance(info, dict):
        return None
    cls_id = resolve("classes", class_name) if class_name else class_name
    owner = info.get("owner_class")
    if cls_id and owner and owner != cls_id:
        return None
    return info


def skill_by_key(skill_key: str):
    """按 key（id 或中文名）全局查技能条目 —— `game/content_rules/skills.py:70 skill_by_key` 同义。"""
    info = SKILLS.get(skill_key)
    if info is None:
        info = SKILLS.get(resolve("skills", skill_key))
    return info if isinstance(info, dict) else None


__all__ = [
    "CLASSES", "SKILLS", "RACES", "SETS", "ENHANCE_TABLE", "TIER_GROWTH",
    "BRANCH_BONUS", "BRANCH_BONUS_BY_CLASS", "PLAYER_BASE_GROWTH",
    "PCT_CAPS", "PCT_STATS", "PENE_PCT_STATS", "CLASS_NOVICE", "REQUIRED_DOMAINS",
    "missing_domains", "resolve", "display", "skill_info", "skill_by_key",
]
