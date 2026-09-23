# -*- coding: utf-8 -*-
"""ext_combat 的「游戏配置取件面」—— 引擎 `config.py` 里那批带游戏词的取件的家。

（2026-09-23 包栈重构第 7 批）

为什么在这儿
------------
引擎的门槛是**零游戏词**。可 `saintess_engine/config.py` 长期住着 11 个名字里就带游戏语义的
取件（`get_effect_rules` · `skill_by_key` · `monster_skill_of` · `mech_cfg` · `bar_prefix` …）
和一张 10 个方法的 `_NullFormulas`（`calc_damage` · `skill_power_mult` · `skill_lifesteal_pct` …），
外加 `_LOADED` 预置的 `effect_rules` / `effect_actions` 两个表名。

它们的**值**本来就不是引擎给的（全部经注入面从内容侧取），引擎只是提供了一层薄包装。
按「谁调用谁带走」点了一遍：`state_def` 21 处、`mech_cfg`/`bar_prefix`/`skill_info_of`/
`monster_skill_of` 各若干，**全在本包**；引擎内部真正用它们的**一处都没有**。

所以它们搬到这儿，引擎那边只剩零游戏词的通用件：
`set_config` / `get_config` / `set_hook` / `mount` / `get_hook` / `unconfigured`。

本模块只做两件事
----------------
1. 从引擎的通用口取值（`saintess_engine.config.get_config` / `get_hook`）—— 不自己存状态；
2. 把「读不到时的中性兜底」定死在这儿（`_NullFormulas` 那套零效应语义归本包）。
"""
from __future__ import annotations

from saintess_engine import config as _cfg

#: 表名（走引擎的通用表容器）
_T_EFFECT_ACTIONS = "effect_actions"
_T_EFFECT_RULES = "effect_rules"

#: 注入面 hook 名（走引擎的通用注入面）
_H_FORMULAS = "formulas"
_H_SKILL_LOOKUP = "skill_lookup"
_H_MONSTER_SKILL = "monster_skill_fn"
_H_KINDS = "kinds"
_H_MECH_CFG = "mech_cfg_fn"
_H_BAR_PREFIX = "bar_prefix_fn"


# ── 表：效果规则 / 效果动作 ────────────────────────────────────────

def load_game_rules(module) -> None:
    """从游戏规则模块加载约定字段（`EFFECT_ACTIONS` / `EFFECT_RULES`）。"""
    _cfg.set_config(_T_EFFECT_ACTIONS, getattr(module, "EFFECT_ACTIONS", {}))
    _cfg.set_config(_T_EFFECT_RULES, getattr(module, "EFFECT_RULES", {}))


def get_effect_actions() -> dict:
    """当前挂载的名词→动词动作表（默认空）。"""
    return _cfg.get_config(_T_EFFECT_ACTIONS) or {}


def get_effect_rules() -> dict:
    """当前挂载的统一效果规则表（V 系列；EFFECT_RULES 字段全谱见设计文档）。"""
    return _cfg.get_config(_T_EFFECT_RULES) or {}


# ⚠ `state_def(key)` 不在这里 —— 本包 `battle/state_effects.py` 已有一个（实现逐字相同）。
#   第 7 批搬配置取件时发现「引擎 `config.py` 的 `state_def` / 本包 `state_effects.state_def`」是两份
#   一样的实现，不再制造第三份：留 `state_effects.state_def`，让它改调本模块的
#   `get_effect_rules()`。


# ── 注入面取件：公式 / 技能表 / 怪物技能 / 机制配置 / 条前缀 / kind ──

class _NullFormulas:
    """未装配时的中性公式兜底（strict=True 时 `formulas()` 改为抛异常）。

    返回值全部为「零效应」：伤害 0 / 成长倍率 1.0 / 等级 0 / 无表达式。
    据此不炸，但也不产生任何数值 —— 这正是 R8 提醒的「静默空放」，
    生产接入点必须显式装配（内容侧 `load_engine_config()`）。
    """

    @staticmethod
    def calc_damage(atk, def_, is_crit=False, variance=0.15, pierce=False,
                    pene_pct=0.0, pene_flat=0, dmg_type="phys"):
        return 0

    @staticmethod
    def resolve_formula(formula, stats, target_def, target_mdef, **kwargs):
        return 0, 0

    @staticmethod
    def skill_formula_expr(info, level=1):
        return None

    @staticmethod
    def skill_formula_expr_for_seg(seg, level=1):
        return None

    @staticmethod
    def skill_power_mult(level, info=None):
        return 1.0

    @staticmethod
    def skill_flat_value(player_lv, skill_lv, info=None):
        return 0

    @staticmethod
    def skill_level_of(player, skill_name):
        return 0

    @staticmethod
    def skill_lifesteal_pct(info, level):
        return 0.0

    @staticmethod
    def skill_buff_turns(level, base=3, info=None):
        return base

    @staticmethod
    def skill_mech_val(info, level):
        return 0


_NULL_FORMULAS = _NullFormulas()


def formulas():
    """数值公式对象（内容侧注入）。

    未装配：strict=True → 抛 `EngineNotConfigured`；否则返回中性兜底对象
    （`_NullFormulas`，全零效应，见 R8）。
    """
    value = _cfg.get_hook(_H_FORMULAS)
    return value if value is not None else _NULL_FORMULAS


def kind_of(name: str) -> str:
    """kind 语义值（内容侧注入；未装配 → ""）。

    引擎不内置任何 kind 字面量（旧写法曾写死「物理 / 魔法 / 真伤 / 治疗 / 增益」）。
    """
    return (_cfg.get_hook(_H_KINDS) or {}).get(name, "")


def skill_info_of(class_name: str, skill_key: str):
    """技能表查询（玩家侧）：内容侧 `skill_lookup.skill_info`。"""
    lookup = _cfg.get_hook(_H_SKILL_LOOKUP)
    if lookup is None:
        return None
    return lookup.skill_info(class_name, skill_key)


def skill_by_key(skill_key: str):
    """技能表查询（key 侧）：内容侧 `skill_lookup.skill_by_key`。"""
    lookup = _cfg.get_hook(_H_SKILL_LOOKUP)
    if lookup is None:
        return None
    return lookup.skill_by_key(skill_key)


def monster_skill_of(skill_key: str):
    """怪物技能表查询：内容侧 `monster_skill_fn`（未装配 → None）。"""
    fn = _cfg.get_hook(_H_MONSTER_SKILL)
    if fn is None:
        return None
    return fn(skill_key)


def mech_cfg(name: str) -> dict:
    """机制配置表查询（内容侧 `mech_cfg_fn`；未装配 → {}）。"""
    fn = _cfg.get_hook(_H_MECH_CFG)
    if fn is None:
        return {}
    return fn(name) or {}


def bar_prefix() -> str:
    """挂敌身条键前缀（内容侧 `bar_prefix_fn`；未装配 → ""）。"""
    fn = _cfg.get_hook(_H_BAR_PREFIX)
    if fn is None:
        return ""
    return fn() or ""


__all__ = [
    "load_game_rules", "get_effect_actions", "get_effect_rules",
    "formulas", "kind_of", "skill_info_of", "skill_by_key", "monster_skill_of",
    "mech_cfg", "bar_prefix",
]
