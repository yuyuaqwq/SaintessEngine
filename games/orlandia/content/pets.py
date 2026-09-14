# -*- coding: utf-8 -*-
"""包内宠物模块（`content/pets.py`）—— 游戏仓 `game/data/pets.py`（252 行）**实现 + 常量全量进包**
（B16-W11c · 2026-09-14）。

真源结构：宿主 `game/core/pets.py`（9 行）本身没有实现，只是一行 re-export
（`from ..data.pets import …`，注释「24 章宠物系统：统一从数据层 re-export」）→ B13-L7 把它搬成
薄壳，本模块是**唯一实现**；原先只有 4 个纯数据名（W12 收口）+ 8 个实现名**惰性转发宿主**
`game/data/pets.py` —— 后者是「删宿主 `game/data`」的**最后一个 import 期阻塞**
（沙盒实测 9/14 宿主模块同因失败：`pets：宿主模块 data.pets 取不到`）。本线把实现整体搬进包。

取值来源（全在包内；宿主 `game/data` 删掉后仍活）
* `PET_POOL` / `PET_EGG_ROLL` ← `content/catalog_life.py`（域 `pets`，`content/data/pets.json`；真源 `game/data/pets.py:19/112`）
* `PET_MAX_LEVEL` / `PET_SKILL_UNLOCK_LV` ← `content/catalog_b143.py`（`game_config.pets`；真源 `pets.py:190/192`）
* `QUALITY` ← `content/catalog_b143.py`（域 `equipment`；真源 `game/data/equipment.py:13`）
* `_PET_EGG_PRICE` / `PET_EXP_GRADE` ← `content/catalog_rules.py`（包内**无域** ⇒ 值由
  `overnight/w11c_dump_pet_tables.py` 从宿主真源 dump、非手抄；登记 `NOT_YET_DOMAINED`）
* `_PET_SKILL_DESC`（8 个展示模板 lambda）属**实现**，随本模块代码走（非数据表）

`bind_host` / `lazy_host_module` **保留**：宿主薄壳 `game/core/pets.py:26` 仍调它们注入句柄
（导入期不得抛；句柄在本模块已无消费点，留着即向后兼容）。
"""
from __future__ import annotations

import importlib
import sys

_HOST_PKG = "data.plugins.dragonfall.game"
_HOST_PKG_FALLBACK = "game"
_HOST_PETS = None                    # 宿主 `game.data.pets` 模块（注入优先；本模块已不消费，留兼容）


def bind_host(pets=None):
    """宿主 `game.data.pets` 注入（幂等）。"""
    global _HOST_PETS
    if pets is not None:
        _HOST_PETS = pets


def lazy_host_module(full_name: str):
    """按**完整模块名**包一个惰性宿主模块句柄 —— 宿主薄壳用它注入自己那棵树的模块。

    宿主侧调用形如（见 `game/core/pets.py`）：宿主包名 + 数据层子模块名 ⇒ 本模块的句柄名。
    为什么必须由薄壳注入全名：同一进程可能并存 `game.*` 与 `data.plugins.dragonfall.game.*`
    两套模块树（plan §8-R2；`tests/` 两种 import 都有）。
    """
    import importlib

    class _Mod:
        def __getattr__(self, attr):
            return getattr(importlib.import_module(full_name), attr)

    return _Mod()


# ============================================================
# ① 包内取件（门面 / 域读口）—— 本模块的全部数据来源
# ============================================================
from . import catalog_life as _cl                                          # noqa: E402
from .catalog_b143 import (PET_MAX_LEVEL, PET_SKILL_UNLOCK_LV,             # noqa: E402
                           QUALITY)
from .catalog_rules import _PET_EGG_PRICE, PET_EXP_GRADE                   # noqa: E402

PET_POOL = _cl.PET_POOL              # 域 `pets`（16 品种，插入序 = 真源）—— 不复制，同一对象
PET_EGG_ROLL = _cl.PET_EGG_ROLL      # 蛋掉落表（11 行）


# ============================================================
# ② 实现（逐字端口 `game/data/pets.py:136-252`，只换「数据取件」）
# ============================================================
def make_pet_egg(pet_key):
    """构造宠物蛋物品(入包用)。pet_key 不存在时兜底为狼崽蛋。"""
    p = next((x for x in PET_POOL if x["key"] == pet_key), PET_POOL[0])
    q = p.get("quality", "white")
    qname = _quality_name(q)
    return {"name": f"{p['name']}蛋", "type": "宠物蛋", "pet_key": p["key"], "stackable": True,
            "price": _PET_EGG_PRICE.get(q, 100), "quality": q,
            "desc": f"{qname}宠物蛋，使用后可孵化出『{p['name']}』"}


def _quality_name(q):
    """品质显示名：普通/优秀/稀有/史诗/传说（复用 equipment.QUALITY，无则白板）"""
    return QUALITY.get(q, {}).get("name", "普通")


def pet_quality_label(pet_key):
    """宠物品质标签：🟣史诗（面板/详情用）"""
    p = next((x for x in PET_POOL if x["key"] == pet_key), None)
    if not p:
        return ""
    q = QUALITY.get(p.get("quality", "white"), {})
    return f"{q.get('color', '⚪')}{q.get('name', '普通')}"


# 宠物技能类型 → 描述模板（v101.3：加新技能类型 = 加一行，改文案不动逻辑）
_PET_SKILL_DESC = {
    "atk_pct":  lambda p, iv: f"每 {iv} 刻 {int(p['skill_value']*100)}% 攻击伤害",
    "matk_pct": lambda p, iv: f"每 {iv} 刻 {int(p['skill_value']*100)}% 魔攻伤害",
    "heal_pct": lambda p, iv: f"每 {iv} 刻回复 {int(p['skill_value']*100)}% 生命",
    "block":    lambda p, iv: f"每 {iv} 刻 {int(p['skill_value']*100)}% 概率挡一次攻击",
    "lifesteal": lambda p, iv: f"每 {iv} 刻 {int(p['skill_value']*100)}% 攻击伤害并吸血回复一半",
    "pierce":   lambda p, iv: f"每 {iv} 刻 {int(p['skill_value']*100)}% 攻击伤害并破防 2 刻",
    "buff_atk": lambda p, iv: f"每 {iv} 刻为 {int(p['skill_value']*100)}% 攻击加成(2 刻)",
    "crit_up":  lambda p, iv: f"每 {iv} 刻为 {int(p['skill_value']*100)}% 暴击加成(2 刻)",
}


def pet_skill_label(pet_key):
    """宠物技能一句话描述(面板用)，如「撕咬(每 3 刻 40% 攻击伤害)」"""
    p = next((x for x in PET_POOL if x["key"] == pet_key), None)
    if not p:
        return ""
    detail = _PET_SKILL_DESC.get(p["skill_type"], lambda p, iv: "")(p, p["skill_interval"])
    return f"{p['skill_name']}({detail})"


def pet_exp_bonus(pet) -> float:
    """宠物等级经验加成系数（0~0.3）；按品质查表，未知品质按白。
    v133.2：per_lv 品质分级（每级加成 × 等级，cap 封顶）。
    v173.2 fix：去掉 int() 截断——per_lv 是小数系数(0.001~0.01)，
    int(level×per_lv) 恒为 0（v133.2 起宠物经验加成实际从未生效的 bug）；
    改 float 精确累加，30 级满品质 cap。"""
    p = next((x for x in PET_POOL if x["key"] == (pet or {}).get("pet_key")), None)
    g = PET_EXP_GRADE.get((p or {}).get("quality", "white"), PET_EXP_GRADE["white"])
    return min(max(float((pet or {}).get("level", 0) or 0) * g["per_lv"], 0.0), g["cap"])


def pct_str(x: float) -> str:
    """百分比显示：0.5 → '0.5'，5.0 → '5'（去尾零，宠物品质分级小数值用）。"""
    s = f"{x * 100:.1f}"
    return s[:-2] if s.endswith(".0") else s


def pet_line(pet_key):
    """宠物随机战斗台词（无则返回空串；v101.11 活人感）"""
    import random
    p = next((x for x in PET_POOL if x["key"] == pet_key), None)
    if not p:
        return ""
    lines = p.get("lines") or []
    return random.choice(lines) if lines else ""


def pet_exp_need(level):
    """升级所需经验（v173.2 非线性拉长，封顶 Lv.30 配套）：
    lv × 35 × (1 + lv/30)——1→10 累计约 1900（略慢于旧的 2750 的直觉，但 10 级前逐级 35-45
    很轻松），30 级满累计约 2.7 万 ≈ 主人打 250~460 只 30+ 级怪（约主人 45-50 级自然满）。
    旧（v118）：level×50 线性，40-80 只怪就 10 级满，宠物节奏远快于主人。"""
    return int(level * 35 * (1 + level / 30))


def pet_exp_mult(pet_lv: int, monster_lv: int) -> float:
    """宠物获得经验的等级差乘区（v173.2 鱼鱼拍板：复用玩家同款非线性曲线）。
    宠物等级 vs 怪等级差 diff = 怪lv - 宠lv：
      diff > 0（宠越级打高级怪）→ 奖励 1 + 0.015×diff²，封顶 ×2.0
      diff ∈ [-3, 0]（同级±3）→ 无惩罚 ×1.0
      diff < -3（宠碾压低级怪）→ 衰减 0.85^(-diff-3)，最低 15%
    与 combat.py 玩家经验曲线同一公式（v173.2a 压制同步 0.02→0.015/2.5→2.0），防两套口径。"""
    diff = monster_lv - pet_lv
    if diff > 0:
        mult = 1.0 + 0.015 * diff * diff
        return mult if mult < 2.0 else 2.0
    if diff < -3:
        mult = 0.85 ** (-diff - 3)
        return mult if mult > 0.15 else 0.15
    return 1.0


# 真源 re-export 的 11 个名字（现在全部由本模块**自带实现/取件**，不再转发宿主）
__all__ = [
    "PET_POOL", "PET_EGG_ROLL", "PET_MAX_LEVEL",
    "make_pet_egg", "pet_exp_need", "pet_exp_mult", "pet_skill_label",
    "pet_quality_label", "pet_line", "pet_exp_bonus", "pct_str",
    "bind_host",
]
