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

# ============================================================
# ②b job_guide 域（『职业』速查读口）—— 2026-09-13 B8.2 线5
# ------------------------------------------------------------
# 真源 = 游戏仓 `game/data/job_guide.py`（`_build_guide()` 产物 JOB_GUIDE + 注入
# `JOB_ALIASES`→`aliases` / `EXTRA_RESOURCES`+`EXTRA_RESOURCE_GUIDE`→`extra_resources`），
# 由 `scripts/export_domains/life_growth.py:derive_job_guide` 单向导出。
# 消费者：命令层『职业』/『职业 <名称>』（`game/commands/job_guide.py` 薄壳）。
#
# ⚠️ 两个坑（都是「JSON 只有字符串键」+「导出按字典序」造成，与 ENHANCE_TABLE 同族）：
#   ① `tiers` / `tier_levels` 的键真源是 **int 档位**、落盘后是 "1"/"2"/"3" —— 不还原
#      = 原文 `.get(int(t), 30)` 恒取缺省 → 档位路线全显示 Lv.30（逐字节对不上真源）；
#   ② 域文件外层键是**字典序**（导出契约 `sort_table`，幂等优先），真源插入序
#      （= 职业展示序）在域里没处存 → 在本模块显式声明 `JOB_ORDER`：多了/少了职业就
#      `raise`（防「加职业忘了改这里」= 静默漏职业 / 一览顺序漂移）。
# ============================================================
_JOB_RAW: dict = _read_domain("job_guide", "data", {})


def _job_int_tiers(tbl) -> dict:
    """档位键 "1"/"2"/"3" → int（与 `_int_keys` 同口径：非整数键原样保留、不静默丢）。"""
    return _int_keys(tbl)


def _job_guide_load(raw) -> dict:
    """域条目 → 真源同形的内存表（只做键型还原，零默认值、零改写）。"""
    out: dict = {}
    for cid, ent in (raw or {}).items():
        e = dict(ent)
        e["tiers"] = {k: list(v or []) for k, v in _job_int_tiers(ent.get("tiers")).items()}
        e["tier_levels"] = _job_int_tiers(ent.get("tier_levels"))
        out[cid] = e
    return out


JOB_GUIDE: dict = _job_guide_load(_JOB_RAW)

# 职业展示顺序（一览 / 多命中候选 / 隐藏传承的遍历序）—— 源 = 真源 JOB_GUIDE 插入序
# （= 游戏仓 `game/data/classes.py` 的 CLASSES 声明序；域文件键是字典序，顺序只能显式声明）。
JOB_ORDER = ("cls_zhan_shi", "cls_fa_shi", "cls_you_xia", "cls_mu_shi",
             "cls_ci_ke", "cls_wu_seng", "cls_shi_ren")


def job_order() -> list:
    """JOB_ORDER ∩ 域内存在的职业；域里出现未声明顺序的职业 → raise（静默漏职业防线）。"""
    ids = [cid for cid in JOB_ORDER if cid in JOB_GUIDE]
    extra = [cid for cid in JOB_GUIDE if cid not in JOB_ORDER]
    if extra:
        raise ValueError(
            f"job_guide 域出现未声明展示顺序的职业 {extra} —— 请同步 content/tables.py:JOB_ORDER"
            "（否则该职业在一览里被静默丢掉）")
    return ids


def job_base_order() -> list:
    """基础职业展示序（真源 `BASE_ORDER`）。"""
    return [cid for cid in job_order() if not JOB_GUIDE[cid].get("hidden")]


def job_hidden_order() -> list:
    """隐藏职业展示序（真源 `HIDDEN_ORDER`；本轮实测为空）。"""
    return [cid for cid in job_order() if JOB_GUIDE[cid].get("hidden")]


def job_hidden_successors() -> dict:
    """`{基础职业 id: [隐藏职业 id…]}`（真源 `HIDDEN_SUCCESSORS`；本轮实测为空）。"""
    succ: dict = {}
    for cid in job_order():
        g = JOB_GUIDE[cid]
        if g.get("hidden") and g.get("src_base"):
            succ.setdefault(g["src_base"], []).append(cid)
    return succ


# 别名表（名字 → 职业 id）：域条目 `aliases` 按**声明序**展开。跨职业重复名**首个赢**
# （真源 `JOB_ALIASES` 建表用 `setdefault`；实测 44 名分 7 职业零重复，两条口径同结果）。
def _job_alias_index() -> dict:
    idx: dict = {}
    for cid in JOB_ORDER:
        if cid not in JOB_GUIDE:
            continue
        for a in (JOB_GUIDE[cid].get("aliases") or []):
            idx.setdefault(a, cid)
    return idx


JOB_ALIAS: dict = _job_alias_index()


def resolve_job(raw):
    """职业名 → 职业 id。**与真源 `game/data/job_guide.py:192 resolve_job` 逐行同义**：

      1) 职业 id；2) 显示名；3) 别名（`aliases`：转职分支名 + 兼容名 歌者）；
      4) 模糊子串（≥2 字，双向 contains）：命中 1 个 → id、多个 → list、0 个 → None。
    """
    if not raw:
        return None
    raw = str(raw).strip()
    if raw in JOB_GUIDE:
        return raw
    for cid in job_order():
        if JOB_GUIDE[cid].get("name") == raw:
            return cid
    if raw in JOB_ALIAS:
        return JOB_ALIAS[raw]
    if len(raw) >= 2:
        hit = []
        for cid in job_order():
            names = [JOB_GUIDE[cid].get("name")] + [a for a, c in JOB_ALIAS.items() if c == cid]
            if any(raw in n for n in names) or any(n in raw for n in names):
                hit.append(cid)
        if hit:
            return hit[0] if len(hit) == 1 else hit
    return None

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
# ②c boss_phases 域（Boss 阶段模板）—— 2026-09-13 B8.2 线5
# ------------------------------------------------------------
# 真源 = 游戏仓 `game/data/boss_phases.py:26 BOSS_PHASE_TEMPLATES`（4 条四阶段模板），
# 由 `scripts/export_domains/b82_l5.py:derive_boss_phases` 单向导出。
# 消费者：包内 Boss 剧本导演 `content/flow/boss_script.py`（宿主 `game/commands/boss_script.py`
# 已移出仓）—— 端口把 `merge_phase_config` 改成**调用方传参** `phase_templates=`，
# 宿主 `game/commands/instance_battle.py` 传的就是下面这个函数。
# 语义与真源逐行同义（`phase_template` 未知 id 回落 normal；`merge_phase_config` 模板为底、
# overrides 逐键覆盖，含 `None` 值 —— `null` 是源侧合法值，不许改写成 0/""）。
# ============================================================
BOSS_PHASE_TEMPLATES: dict = _read_domain("boss_phases", "data", {})


def phase_template(phase_id: str) -> dict:
    """取阶段模板（带缺省兜底，未知 id 返回常态模板）—— 真源 `boss_phases.py:95` 同义
    （`normal` 缺失时与真源一样 `KeyError`，不静默回落空 dict）。"""
    return BOSS_PHASE_TEMPLATES.get(phase_id) or BOSS_PHASE_TEMPLATES["normal"]


def merge_phase_config(phase_id: str, overrides: dict = None) -> dict:
    """模板 + Boss 内联覆盖合并：模板为底，overrides 逐键覆盖 —— 真源 `:100` 同义。"""
    base = dict(phase_template(phase_id))
    if overrides:
        for k, v in overrides.items():
            base[k] = v
    return base


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
    """名字或 id → id（找不到**原样返回**）—— `game/core/index.py:47` 同义。

    例外：`"job_guide"` 走 `resolve_job()`（真源 `game/data/job_guide.py:192` 同义）——
    它的返回值是**三态**（命中 → 职业 id / 多命中 → id 列表 / 找不到 → `None`），
    因为『职业』命令要区分「查到」「匹到多个」「没有」三种提示（原样返回一个不存在的
    字符串会让命令误判成命中）。
    """
    if table_name == "classes":
        return _CLASSES_BY_NAME.get(name_or_id, name_or_id)
    if table_name == "skills":
        return _SKILLS_BY_NAME.get(name_or_id, name_or_id)
    if table_name == "job_guide":
        return resolve_job(name_or_id)
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
    "JOB_GUIDE", "JOB_ORDER", "JOB_ALIAS", "job_order", "job_base_order",
    "job_hidden_order", "job_hidden_successors", "resolve_job",
    "BOSS_PHASE_TEMPLATES", "phase_template", "merge_phase_config",
]
