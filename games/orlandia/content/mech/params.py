# -*- coding: utf-8 -*-
"""《奥兰迪亚》机制参数表 —— P4 切片**子集**（数值全部抄自游戏仓真源，此处零自编）。

设计定位（设计稿 §二 + 分析报告 §3-G1）
--------------------------------------
8 张参数表（`FORMULA_SKELETON` / `SKILL_*` / `MECH_CFG` / `MECH_CASH` / `REACTION_TABLE` /
`WEAPON_EFFECT_DATA` / `FOOD_EFFECT_PARAMS` / `BAR_*`）在**切片期随代码走**（本文件），
第二波才给它们建域（编辑器可改）。本文件**只做取值，不改形状** —— 键名/嵌套与游戏仓
真源逐字一致，将来建域时整块搬到 `<域>.json` 即可。

本文件同时充当 `config.load_game_rules(module)` 的**规则模块**（`EFFECT_RULES` /
`EFFECT_ACTIONS` 两个属性）—— 见 `content/apply.py: install_engine()`。
其中 `EFFECT_ACTIONS`（名词→动词表）**不在这里定义**：2026-09-13 单源归位后真源 = 包内
`content/gameplay.py`（逐字搬自游戏仓），本文件只做 `from ..gameplay import EFFECT_ACTIONS`
**再导出**（`is` 同一对象；消费者 import 路径不变）。

真源对照表（游戏仓 `C:/Users/yuyu/qqbot/data/plugins/dragonfall`）
----------------------------------------------------------------
| 本文件 | 真源 | 是否全量 |
|---|---|---|
| `KIND_NAMES`          | `game/bootstrap.py:117 _kinds()`（值 = `saintess_engine.kinds.K_*`） | 全量（5 值，引擎词表就 5 个） |
| `BASIC_FALLBACK`      | `game/bootstrap.py:123 _basic_fallback()` | 全量 |
| `FORMULA_SKELETON`    | `game/data/formula_skeleton.py:FORMULA_SKELETON` | **子集**：只留引擎 `saintess_engine/battle/formulas.py` 读的两段（`skill_growth` / `skill_learn_cost`）；其余段（exp_fallback / monster_exp / monster_gold / prof_exp_need / equip_crit / necklace_mdef / boss_atk_legacy）由宿主结算读，切片不搬 |
| `SKILL_FLAT`          | `game/data/skill_up.py:SKILL_FLAT_BASE/_PER_PLAYER_LV/_PER_SKILL_LV` | 全量（3 常量） |
| `TIER_GROWTH`         | `game/data/battle_config.py:379` | 全量（4 个档位；切片面板公式用） |
| `LINEAR_STATS`        | `game/data/base_growth.py:PLAYER_BASE_GROWTH["linear_stats"]` | 全量（7 键） |
| `MECH_CFG`            | `game/data/battle_config.py:455 MECH_CFG` | **子集**：只留 `enemy_bar`（`saintess_engine/gauge` 的条机制读它；切片 3 个动作用到的 `target_bar_*` judge 依赖 `enemy_bar.shaken`）。`enemy_bar` 内只留 `shaken`（`curse` 属 D2 敌身条族，随 `bar_procs.py` 一起搬） |
| `MECH_CASH`           | `game/data/battle_rules.py:624 MECH_CASH` | **空**：切片 3 个动作都不读它（读它的是 `mech_cash_*` 兑现执行器族，属 D2）。留空 = 明确"本切片不采用"，不是忘了搬 |
| `BAR_STATE_PREFIX`    | `game/data/battle_rules.py:749` | 全量 |
| `EFFECT_RULES`        | 包内 `content/rules/effect_rules.json`（85 条，导出物） | 全量（本包自己的声明表） |
| `EFFECT_ACTIONS`      | `game/data/battle_rules.py:468-596` | **全量再导出**（2026-09-13 单源归位）：70 名词 / 82 动作条目 / 22 动词；真源 = 包内 `content/gameplay.py`（逐字，`--check` 复核），本文件只 `from ..gameplay import EFFECT_ACTIONS`，不再自带定义 |
"""
from __future__ import annotations

import json
import os

from ..gameplay import EFFECT_ACTIONS                      # 名词→动词表单源（content/gameplay.py）
from .kinds import K_BUFF, K_HEAL, K_MAGI, K_PHYS, K_TRUE   # kind 词表单源（下沉自引擎，见 kinds.py）

_HERE = os.path.dirname(os.path.abspath(__file__))          # <pkg>/content/mech
_CONTENT = os.path.dirname(_HERE)                           # <pkg>/content
_RULES_DIR = os.path.join(_CONTENT, "rules")


def _read_json(name: str, default):
    """读包内 content/rules/<name>（缺文件/坏 JSON → default，不抛）。"""
    path = os.path.join(_RULES_DIR, name)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                        # noqa: BLE001
        return default


# ============================================================
# ① kind 语义词表（引擎零 kind 字面量：只用 config.kind_of(name) 查这张表）
#    ← 单源 = 本目录 `kinds.py`（2026-09-13 自 `saintess_engine/kinds/` 下沉到内容侧；
#      与游戏仓 `game/data/kinds.py` 同源。此处只做**取名**，不再自带字面量 — 防双源）
# ============================================================
KIND_NAMES = {
    "phys": K_PHYS,
    "magi": K_MAGI,
    "true": K_TRUE,
    "heal": K_HEAL,
    "buff": K_BUFF,
}

# ② 普攻兜底配置（无职业 basic_skill 时用）← game/bootstrap.py `_basic_fallback()`
BASIC_FALLBACK = {"name": "攻击", "kind": KIND_NAMES["phys"], "exprs": ["atk*1.0"]}

# ============================================================
# ③ 公式骨架参数表（引擎 saintess_engine/battle/formulas.py 的读点）
#    ← game/data/formula_skeleton.py（只搬引擎读的两段；见文件头真源对照表）
# ============================================================
FORMULA_SKELETON = {
    "skill_growth": {
        "power_per_lv_divisor": 100,      # F7 skill_power_mult: 1 + (p/divisor)*(lv-1)
        "cond_default": 0.05,             # F9 skill_cond_mult 未配 c 默认每级 +0.05
        "mech_default_div": 2,            # F9 skill_mech_val 未配 m 默认每 2 级 +1 层
        "buff_turns_base": 3,             # F9 skill_buff_turns 默认 base 3 刻
        "buff_turns_per_lv": 1,           # F9 skill_buff_turns 每级 +1 刻
        "lifesteal_default": 0.20,        # F9 skill_lifesteal_pct 未配 lifesteal 默认 20%
        "lifesteal_per_lv_divisor": 100,  # F9 l 配值单位 %：l/100 每级
    },
    "skill_learn_cost": {"divisor": 6, "base": 2},   # F15 技能点定价 cost = need_lv//divisor + base
}

# ④ 技能基础值常量 ← game/data/skill_up.py（v156 保底伤害模型）
SKILL_FLAT = {
    "SKILL_FLAT_BASE": 12,           # 基础值基数（Lv1 玩家）
    "SKILL_FLAT_PER_PLAYER_LV": 1,   # 每玩家等级 +1
    "SKILL_FLAT_PER_SKILL_LV": 2,    # 每技能等级 +2
}

# ⑤ 转职成长档位 ← game/data/battle_config.py:379（面板切片用；tier 0 = 未转职）
TIER_GROWTH = {0: 1.0, 1: 1.15, 2: 1.30, 3: 1.50}

# ⑥ 线性成长键集（吃 tier_mult 的 7 个属性）← game/data/base_growth.py
LINEAR_STATS = ("hp", "mp", "atk", "def", "matk", "mdef", "spd")

# ============================================================
# ⑦ 机制配置表 MECH_CFG / ⑧ 兑现声明表 MECH_CASH —— **单源在 `class_data.py`**
#    ★ 2026-09-13 收敛（本次修掉一个真 bug）：
#      原状：MECH_CFG **三份**（class_data 全量 15 组 = 逐键等于真源 ✅ /
#            element_data 仅 `element` 一档（零消费者）/ 本文件仅 `enemy_bar` 一档**且截断**：
#            真源 battle_config.py:284 的 ENEMY_BAR_CFG 是 `{curse, shaken}`，本文件只抄了 `shaken`）。
#      后果：本文件那份挂在引擎 hook `mech_cfg_fn` 上（`saintess_engine/gauge/__init__.py:51`
#            `config.mech_cfg(name)`）→ 走 gauge 的敌身条读到的配置**缺 curse**（静默少一档），
#            而走 class_data 的装配层读到的是完整的 —— 同一机制名、两条入口、两套值。
#      MECH_CASH 两份：class_data 9 条 ✅ / 本文件空 `{}`（零消费者，切片遗留）。
#      现统一以 `class_data.py` 为唯一真源（已验：与 `battle_config.MECH_CFG` /
#      `battle_rules.MECH_CASH` **全量 deep-equal**）；本文件不再自带副本。
#      ⚠️ 不能在模块顶层 `from .class_data import …` —— `class_data` 顶层 import 本文件的
#      `BAR_INJECT_FIELDS`，会成环。故 hook 供体在**函数内延迟导入**（见下方 `mech_cfg()`）。
# ============================================================

# ⑨ 挂敌身条键前缀 ← game/data/battle_rules.py:749
BAR_STATE_PREFIX = "bar:"

# ⑨b 挂敌身条注入声明表（技能字段 → bar key）← game/data/battle_rules.py:742-744
#    ★ 单源（2026-09-13 收敛）：原先 `class_data.py:283` 与 `element_data.py:92` **各存一份**
#      （分别被 class_mech 与 bar_procs 消费）—— 值当时一致，但那是「碰巧一致」，改一处就漂。
#      现统一放这里；那两个文件改为 `from .params import …` 再导出（消费者 import 路径不变）。
BAR_INJECT_FIELDS: dict = {
    "shaken_gain": {"key": "shaken", "per_hit": True},   # 拳师破绽：技能命中推条
}

# ============================================================
# ⑩ 声明表（`config.load_game_rules(本模块)` 读这两个属性）
# ============================================================
EFFECT_RULES = _read_json("effect_rules.json", {})   # 85 条（包内 rules/effect_rules.json）
# EFFECT_ACTIONS：**不再自带定义** —— 归位后由文件头 `from ..gameplay import` 再导出
# （属性必须存在：`content/apply.py:153` 经 `load_game_rules(P)` 读它）。


# ============================================================
# hook 供体函数（config.mount(...) 用；形态与游戏仓 bootstrap.py 同）
# ============================================================

def formula_skeleton() -> dict:
    """`formula_skeleton_fn` 供体（活读本模块表；缺省 {})。"""
    return FORMULA_SKELETON


def skill_flat() -> dict:
    """`skill_flat_fn` 供体。"""
    return SKILL_FLAT


def mech_cfg(name: str) -> dict:
    """`mech_cfg_fn` 供体（引擎 `config.mech_cfg(name)` 语义：查不到 → {}）。

    ★ 单源 = `class_data.MECH_CFG`（全量 15 组，逐键等于真源 `battle_config.py:455`）。
    延迟导入是为了避开 `class_data → params`（BAR_*）与本函数的环。
    """
    from .class_data import MECH_CFG          # noqa: PLC0415  函数内导入：避免模块级环
    return MECH_CFG.get(name, {}) or {}


def bar_prefix() -> str:
    """`bar_prefix_fn` 供体。"""
    return BAR_STATE_PREFIX
