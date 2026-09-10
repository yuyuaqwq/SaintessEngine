# -*- coding: utf-8 -*-
"""技能/伤害类型域（v176 去魔法字符串重构）。

背景：battle.py 里 `kind == "物理"` 中文字符串散落 30+ 处——
- 拼写错难查（运行时才炸）
- 加新伤害类型要全局 grep 改
- 类型属性（伤害通道/抗性/暴击/吸血/段类型）散在各函数各自 if

本模块集中定义类型域，提供：
  SkillKind   枚举：物理/魔法/魔法·元素/治疗/增益/被动/召唤/真伤/嘲讽
  KIND_*      常量别名（避免 enum 成员比较啰嗦，兼容 == 语义）
  kind_meta() 类型元数据表（段类型 phys/magi/true、是否伤害、吸血通道…）
  kind_is()   前缀/包含匹配（魔法·火 → 魔法）

用法（渐进式替换 battle.py / engine.py / combat.py 的中文比较）：
  if SKIND.is_kind(kind, SKIND.MAGI):        # 魔法 或 魔法·火 都 True
  if kind == SKIND.PHYS:                     # 精确物理
  meta = SKIND.meta(kind)                     # {"seg": "phys", "dmg": True, ...}
"""
from __future__ import annotations

from enum import Enum


class SkillKind(str, Enum):
    """技能类型（与 skills.py 数据 kind 字段同值；元素魔法用 '魔法·X' 子串）。"""
    PHYS = "物理"
    MAGI = "魔法"
    HEAL = "治疗"
    BUFF = "增益"
    PASSIVE = "被动"
    SUMMON = "召唤"
    TRUE = "真伤"
    TAUNT = "嘲讽"

    @property
    def seg(self) -> str:
        """伤害段类型：phys/magi/true（engine.calc_damage dmg_type 用）。"""
        return _KIND_META[self]["seg"]

    @property
    def is_damage(self) -> bool:
        return _KIND_META[self]["damage"]

    @property
    def lifesteal_channel(self) -> str:
        """吸血通道：phys/magi/true（battle._settle_lifesteal 用）。"""
        return _KIND_META[self]["lifesteal"]


# 便捷常量（字符串值，与数据/旧代码天然兼容）
K_PHYS = SkillKind.PHYS.value
K_MAGI = SkillKind.MAGI.value
K_HEAL = SkillKind.HEAL.value
K_BUFF = SkillKind.BUFF.value
K_PASSIVE = SkillKind.PASSIVE.value
K_SUMMON = SkillKind.SUMMON.value
K_TRUE = SkillKind.TRUE.value
K_TAUNT = SkillKind.TAUNT.value

# 类型元数据（集中定义类型行为，杜绝各函数散落 if）
_KIND_META = {
    SkillKind.PHYS:    {"seg": "phys", "damage": True,  "lifesteal": "phys"},
    SkillKind.MAGI:    {"seg": "magi", "damage": True,  "lifesteal": "magi"},
    SkillKind.HEAL:    {"seg": "magi", "damage": False, "lifesteal": ""},
    SkillKind.BUFF:    {"seg": "magi", "damage": False, "lifesteal": ""},
    SkillKind.PASSIVE: {"seg": "magi", "damage": False, "lifesteal": ""},
    SkillKind.SUMMON:  {"seg": "magi", "damage": False, "lifesteal": ""},
    SkillKind.TRUE:    {"seg": "true", "damage": True,  "lifesteal": "true"},
    SkillKind.TAUNT:   {"seg": "magi", "damage": False, "lifesteal": ""},
}

# 伤害型 kind（物理/魔法/魔法·X/真伤）
_DMG_KINDS = {SkillKind.PHYS, SkillKind.MAGI, SkillKind.TRUE}


def is_damage_kind(kind: str) -> bool:
    """kind 是否为伤害类型（含元素魔法前缀 魔法·火 等）。"""
    if not kind:
        return False
    base = kind.split("·")[0] if "·" in kind else kind
    try:
        return SkillKind(base) in _DMG_KINDS
    except ValueError:
        return False


def is_kind(kind: str, target: SkillKind) -> bool:
    """kind 是否为目标类型（魔法·火 也算 魔法；精确类型 == 同值）。"""
    if not kind:
        return False
    if "·" in kind and target is SkillKind.MAGI:
        return kind.startswith(SkillKind.MAGI.value)
    return kind == target.value


def seg_of(kind: str) -> str:
    """段类型（phys/magi/true）。元素魔法/治疗/增益 → magi；真伤 → true。未知 kind → magi 保守。"""
    if not kind:
        return "magi"
    if "·" in kind:
        return "magi"
    try:
        return _KIND_META[SkillKind(kind)]["seg"]
    except ValueError:
        # 未知 kind：若以 魔法 开头（未来元素）按 magi；否则保守 magi
        return "magi"


def lifesteal_channel_of(kind: str) -> str:
    """吸血通道（phys/magi/true/空=不吸血）。"""
    if not kind or "·" in kind:
        # 元素魔法 → magi 通道
        return "magi" if kind and "·" in kind else ""
    try:
        return _KIND_META[SkillKind(kind)]["lifesteal"]
    except ValueError:
        return ""
