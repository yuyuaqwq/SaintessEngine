# -*- coding: utf-8 -*-
"""《奥兰迪亚》元素族 + 敌身条族参数表 —— 逐字搬运物（P4-D2）。

真源 = 游戏仓 `C:/Users/yuyu/qqbot/data/plugins/dragonfall`；每张表写清**真源文件 + 行号**：

| 本文件 | 真源 | 条数 |
|---|---|---|
| `ELEMENT_REACTIONS`              | `game/data/battle_config.py:80-90`   | 4 条 |
| `ELEMENT_MARKS_MAX`              | `game/data/battle_config.py:142`     | 1 值（3） |
| `REACTION_TABLE`                 | `game/data/battle_config.py:147-152` | 4 条 |
| `ELEMENT_SAME_CAST_EXTRA_CHARGE` | `game/data/battle_config.py:154`     | 1 值（1） |
| `MECH_CFG["element"]`            | `game/data/battle_config.py:474-480` | 4 键（= 前 4 项收编） |
| `BAR_INJECT_FIELDS`              | `game/data/battle_rules.py:742-744`  | 1 条 |

`BAR_STATE_PREFIX`（真源 `game/data/battle_rules.py:749`）**不在此重复**：包内已有同一张表
（`content/mech/params.py:123`，同名同值 `"bar:"`；引擎经 `config.bar_prefix()` 取）——
按 D2 任务「若已被其他文件覆盖则不重复」处置。本文件只补尚未进包的那张：
`BAR_INJECT_FIELDS`（真源 `:742`）。

逐字性：键序 = 真源书写序；数值/文案/`min_layers` 门槛全同；`MECH_CFG["element"]` 的 4 个键名
（`reactions` / `reaction_table` / `marks_max` / `same_cast_extra_charge`）与真源 :474-480 一致。
对拍证据 = `overnight/d2_misc_verify.py` A5「ast 扫真源字面量 ↔ 本模块值」逐值比较。

接线状态（诚实标注，勿静默）：
· `ELEMENT_REACTIONS` 由 `content/mech/element_procs.py:_reactions()` 读（真源同款读点）。
· `BAR_INJECT_FIELDS` 的消费者是**装配链**（真源 `apply_bar_procs` → 归 `content/apply.py`，
  属主 agent）——本批动作不读它。
· `MECH_CFG["element"]` / `REACTION_TABLE` / `ELEMENT_MARKS_MAX` 在本批**零读点**
  （真源动作也不读它们：`battle_element_procs` 只读 `ELEMENT_REACTIONS`）——按 D2 要求先逐字
  入库，供装配层/第二波建域接线；引擎 `mech_cfg_fn` 目前仍只喂 `params.MECH_CFG`
  （`content/mech/params.py`，主 agent 拥有，本批不改）。
"""
from __future__ import annotations

# ============================================================
# ① 元素反应（印记反应轴）← game/data/battle_config.py:80-90（4 条，逐字）
#    真源注释随表保留（2026-09-11 修正：冻结原写 ("water","ice_mark") —— 游戏里没有
#    water 元素（三系 fire/ice/thunder），按 v153 §2「冰印 + 雷印 = 冻结」应为 thunder；
#    感电新增 min_layers 门槛（缺省 1 = 有印即反应，感电需雷印满 3 层）。
# ============================================================
ELEMENT_REACTIONS = {
    # 2026-09-11 修正（对齐 CLASS_MECHANICS_v153 §2 :385-388「元素反应」）：
    #   · 冻结原写作 ("water", "ice_mark") —— 游戏里**没有 water 元素**（三系 fire/ice/thunder），
    #     按 §2「冰印 + 雷印 = 冻结」应为 thunder → 已改（否则冻结永不触发）。
    #   · 感电按 §2 需「雷印**满 3 层**」→ 新增 min_layers 门槛（缺省 1 = 有印即反应）。
    ("ice", "fire_mark"):        {"name": "蒸发", "mult": 1.30, "clear": True, "extra": ""},
    ("fire", "thunder_mark"):    {"name": "超载", "mult": 1.00, "clear": True, "extra": "aoe"},
    ("thunder", "ice_mark"):     {"name": "冻结", "mult": 1.00, "clear": True, "extra": "freeze"},
    ("thunder", "thunder_mark"): {"name": "感电", "mult": 1.00, "clear": False,
                                  "extra": "chain", "min_layers": 3},
}

# ② 目标侧三系印记上限（每目标每系独立 0..3）← game/data/battle_config.py:142
ELEMENT_MARKS_MAX = 3

# ③ 引爆反应表：引爆系 × 目标印记系 → 反应结算（法师元素印）← game/data/battle_config.py:147-152
#    mult  ：伤害倍率（蒸发 1.30，其余 1.00 由 extra 效果体现）
#    clear ：反应后清除目标哪系印记（"" = 不清除）
#    extra ：aoe=全体 120% 魔攻伤害 / freeze=冻结 1 刻 / chain=感电连击 +1
REACTION_TABLE = {
    ("fire", "ice"):     {"kind": "vaporize",      "name": "蒸发", "mult": 1.30, "clear": "ice",     "extra": ""},
    ("fire", "thunder"): {"kind": "overload",      "name": "超载", "mult": 1.00, "clear": "thunder", "extra": "aoe"},
    ("ice", "thunder"):  {"kind": "frozen",        "name": "冻结", "mult": 1.00, "clear": "thunder", "extra": "freeze"},
    ("thunder", "ice"):  {"kind": "electro_chain", "name": "感电", "mult": 1.00, "clear": "",        "extra": "chain"},
}

# ④ 同系连发奖励 ← game/data/battle_config.py:154（MECH_CFG["element"] 第 4 键要它）
#    （被动「元素凝聚」重定义自 dump 万象亲和：连续两次同系施放，第二次额外 +1 充能）
ELEMENT_SAME_CAST_EXTRA_CHARGE = 1

# ============================================================
# ⑤ MECH_CFG["element"] —— **单源在 `class_data.py`（全量 15 组）**，本文件不再自带副本
#    ★ 2026-09-13 收敛：本文件原自带一份 `{element: {...}}` 分片，与 `class_data.MECH_CFG["element"]`
#      **逐键相等**（已验），但零消费者（`element_procs` 只 import 本文件的 `ELEMENT_REACTIONS`）。
#      同一张表散成三份（class_data 全量 / element_data 分片 / params 分片且截断）正是
#      "同表多份、值碰巧一致"的温床 → 统一以 class_data 为唯一真源。
#      需要 element 档时：`from .class_data import MECH_CFG` → `MECH_CFG["element"]`
#      （本档的 4 键仍由本文件上面的 ELEMENT_REACTIONS / REACTION_TABLE / ELEMENT_MARKS_MAX /
#       ELEMENT_SAME_CAST_EXTRA_CHARGE 常量构成，class_data 那份已含同样内容）。
# ============================================================

# ============================================================
# ⑥ 技能数据字段 → enemy_bar key 映射 ← game/data/battle_rules.py:742-744（1 条，逐字）
#    真源注释随表保留：
#    key      目标条（条状态存 actor.effects[BAR_STATE_PREFIX + key]）
#    per_hit  字段值是「每段」注入量（v153 §六 分档表：「多段 +3~+5/段」，如连环拳
#             4/段×4、裂岳连击 5/段×3）→ 命中时按技能 hits 段数合并注入
# ============================================================
# ⚠️ **单源在 params.py**（2026-09-13 收敛双源）：本文件原自带一份 `BAR_INJECT_FIELDS`，
#    与 class_data.py:283 的副本并存（bar_procs 读这份、class_mech 读那份）→ 现改为再导出，
#    消费者 import 路径不变（`from .element_data import BAR_INJECT_FIELDS` 照旧可用）。
from .params import BAR_INJECT_FIELDS   # noqa: F401  再导出（单源）
