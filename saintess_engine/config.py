# -*- coding: utf-8 -*-
"""saintess_engine 引擎——配置挂载点（引擎零游戏知识）。

引擎不内置任何游戏名词/数值规则。游戏层启动时把配置表挂进来：
    from saintess_engine import config
    config.state_effects = {...}   # 或 config.load_game_rules(module)

引擎内部所有"查表"都走 config 提供的接口，自身不认识表内容。
换一套配置 = 换挂载的表 = 新游戏（引擎代码零改动）。

S1 断链（docs/archive/ENGINE_CONTENT_SPLIT_PLAN.md §3.2 / §7）：
本包历史上直接 import `game.engine` / `game.content` / `game.data`（15 条
「引擎 → 内容」反向边）。现全部改走本模块的注入面 —— 方向反过来：
**内容侧（game/bootstrap.py）把公式/面板/技能查询/kind 常量 mount 进来**，
引擎自身零内容 import（门禁：tests/test_engine_no_content.py）。
"""
from __future__ import annotations


class EngineNotConfigured(RuntimeError):
    """引擎求解所需的游戏挂载缺失（strict=True 模式下抛出，见 R8）。"""


# 挂载的配置表容器（引擎只存不认 —— 表名由调用方定，见 set_config / get_config）。
# ⚠ 这里**不许**预置任何具体表名：预置 = 把游戏侧的词汇写进引擎（第 7 批清掉的那批）。
_LOADED: dict = {}

# S1 注入面：hook 名 → 内容侧装配件（默认 None = 未装配）。
# ⚠️ 引擎不得自行实现这些 hook 的内容语义（那就是反向依赖）。
_HOOKS = {
    # 数值公式对象：calc_damage / resolve_formula / skill_formula_expr /
    # skill_formula_expr_for_seg / skill_power_mult / skill_flat_value /
    # skill_level_of / skill_lifesteal_pct / skill_buff_turns / skill_mech_val
    "formulas": None,
    # 玩家职业面板函数：fn(class_name, level, equipment, tier, attributes,
    #                     evolve_path, title_bonus, race) -> dict
    "panel_fn": None,
    # 技能表查询对象：.skill_info(class_name, skill_key) / .skill_by_key(key)
    "skill_lookup": None,
    # 怪物技能表查询：fn(key) -> dict|None
    "monster_skill_fn": None,
    # 职业普攻 basic_skill 配置查询：fn(class_name) -> dict|None
    "basic_skill_fn": None,
    # 普攻兜底配置（dict：name/kind/exprs）——内容名由内容侧给，引擎零字面量
    "basic_fallback": None,
    # kind 语义常量（dict：phys/magi/true/heal/buff → 内容语义值）
    "kinds": None,
    # S3 通用件（battle_bars）：机制配置表读取 fn(name) -> dict（内容侧 MECH_CFG）
    "mech_cfg_fn": None,
    # S3 通用件（battle_bars）：挂敌身条键前缀 fn() -> str（内容侧 BAR_STATE_PREFIX）
    "bar_prefix_fn": None,
    # ---- S5 注入面：saintess_engine/formulas.py 的表读点（引擎零内容 import）----
    # 公式骨架参数表 fn() -> dict（内容侧 FORMULA_SKELETON）
    "formula_skeleton_fn": None,
    # 技能基础值常量表 fn() -> dict（内容侧 SKILL_FLAT_BASE / _PER_PLAYER_LV / _PER_SKILL_LV）
    "skill_flat_fn": None,
    # 技能升级配置查询 fn(info) -> dict（内容侧 SKILL_UP，见 content_rules.skills._skill_up）
    "skill_up_fn": None,
    # 技能等级查询 fn(player, skill_name) -> int（内容侧 content_rules.skills.skill_level_of）
    "skill_level_of_fn": None,
    # ---- CTB 时间模型注入面：`battle/schedule.py` 的读点（引擎零公式/零数值）----
    # 时间模型 fn(spd, base) -> float（一次行动耗时，游戏秒；形状与参数全在内容侧）
    "time_model_fn": None,
    # ★ E1（2026-09-21）：声明式公式表供体（`saintess_engine.formula.FormulaTable`）。
    #   不配 = 不存在 ⇒ 既有 20 处 `_cfg.formulas()` 调用点全部走原路，行为逐字节不变。
    "formula_table_fn": None,
    # ★ E1b（2026-09-21）：**语义槽位 → 声明 id** 的绑定表，形状 = fn(slot: str) -> str | None。
    #   引擎按**中性槽位名**问（"damage" / "miss" / "crit_pct" / "act_time" / …），
    #   包按自己的命名回答声明 id；答 None = 本槽位不声明 ⇒ 引擎走原路。
    #   ★ 为什么需要它：声明被有意做成"原子"的（每条只吃自己的输入），
    #     「level+敌防 → 伤害」要串 4 条；若让引擎自己串，引擎里就得出现内容 id（R2 明禁）。
    #   不配 = 不存在 ⇒ 所有读口一字不动。
    "formula_bindings_fn": None,
    # ★ E2（2026-09-21）：面板栈供体（`ext_combat.panel.PanelStack`），形状 = fn(stack_id) -> dict | None。
    #   不配 = 不存在 ⇒ `battle/stats.py` 原路调 `panel_fn`，既有包行为逐字节不变。
    "panel_layers_fn": None,
    # ★ E5（2026-09-21）：两段耗时的**声明供体**，形状 = fn(actor, action, entry) -> dict | None。
    #   回执 {"cast": <decl>, "recover": <decl>}；None = 本次不声明。
    #   不配 = 不存在 ⇒ 引擎**连问都不问**，落回既有「行动类别基准」路径。
    "segment_plan_fn": None,
    # 行动类别 → 基准耗时 fn(action) -> float（内容侧基准表；未声明类别引擎回落 DEFAULT_ACTION）
    "action_base_fn": None,
    # ---- 第二段（收招）注入面：与上面两条同形，只多一段耗时槽 ----
    # 第二段耗时 fn(spd, base) -> float（游戏秒；形状与参数全在内容侧）
    "recover_model_fn": None,
    # 行动类别 → 第二段基准耗时 fn(action) -> float（「无第二段」= 内容侧显式声明 0.0）
    "recover_base_fn": None,
}

# R8：无挂载静默降级开关。
#   False（默认）= 与引擎历史行为一致：未装配 → 中性兜底（数值 0 / 空表），不炸；
#   True         = 未装配即抛 EngineNotConfigured（防测试假绿 / 线上静默失效）。
# 测试环境默认 False（避免已装配路径之外的既有用例集体报错）；生产接入点应显式
# 调用 game.bootstrap.load_engine_config() 后可按需打开。
strict = False

# 内容侧注册的"惰性装配器"：首次访问未装配 hook 时自动完成装配（见 get_hook）。
# 引擎只持有回调，不认识内容 —— 内容 → 引擎方向注入。
# 注意：这只是**惰性兜底**。引擎不得提供「加载本游戏默认配置」这类**游戏概念** API
# （S8 拆仓前的 `load_game_defaults()` 即此类 shim，已删 —— 游戏的配置装配是游戏
#  自己的入口，框架不认识「默认配置」是什么）。
_hook_provider = None
_hook_provider_running = False


def set_config(kind: str, table) -> None:
    """挂载一张配置表 —— **表名由调用方定，引擎不认识任何具体表名**。

    （2026-09-23 第 7 批：原先这里只认 `effect_actions` / `effect_rules` 两个白名单，
      那等于把游戏侧的词汇写进了引擎。改成任何 kind 都能挂。）
    """
    _LOADED[kind] = table if table is not None else {}


def get_config(kind: str, default=None):
    """读一张配置表（未挂载 → `default`）。与 `set_config` 配对的**泛型口**。

    游戏侧的专用取件（`get_effect_rules` / `state_def` / `skill_*` …）
    由扩展包在这上面包一层，引擎侧不再出现它们的名字。
    """
    return _LOADED.get(kind, default)


def register_hook_provider(fn) -> None:
    """内容侧注册「hook 惰性装配器」：首次访问未装配 hook 时调用一次。"""
    global _hook_provider
    _hook_provider = fn


# ============================================================
# S1 注入面（hook）读写
# ============================================================

def set_hook(name: str, value) -> None:
    """内容侧挂载单个 hook（未知名忽略 —— 引擎只认 `_HOOKS` 名单）。

    ★ `_HOOKS` 的名单是**注入面契约**（引擎声明它认识哪些 hook 名），不是
      「引擎里的游戏词」—— 第 7 批一度把它清空，两个门禁立刻红：
      `test_engine_purity.py` 正面断言「注入面含 hook X」、
      `test_engine_neutral_fallback.py` 断言「_HOOKS 认识两个第二段 hook 名」。
      名单留着；被搬走的是**取件函数**（get_effect_rules / skill_by_key …）。
    """
    if name in _HOOKS:
        _HOOKS[name] = value


def mount(**hooks) -> None:
    """内容侧批量挂载 hook（幂等；未知名忽略）。"""
    for name, value in hooks.items():
        set_hook(name, value)


def get_hook(name: str):
    """读单个 hook。

    未装配 → 先问内容侧惰性装配器（一次，幂等）；仍未装配：strict=True →
    抛 EngineNotConfigured，否则 None。
    """
    value = _HOOKS.get(name)
    if value is None and _hook_provider is not None:
        _lazy_bootstrap()
        value = _HOOKS.get(name)
    if value is None and strict:
        raise EngineNotConfigured(
            f"引擎未装配：缺少 hook {name!r}（content 侧应调 game.bootstrap.load_engine_config()）"
        )
    return value


def _lazy_bootstrap() -> None:
    """触发内容侧惰性装配（防重入；装配失败静默，交由 strict/兜底决定）。"""
    global _hook_provider_running
    if _hook_provider_running:
        return
    _hook_provider_running = True
    try:
        _hook_provider()
    except Exception:
        pass
    finally:
        _hook_provider_running = False


def unconfigured(name: str, default):
    """未装配兜底值：strict=True → 抛；否则返回 default（R8 静默降级语义）。"""
    get_hook(name)  # strict 检查
    return default


# 效果规则 / 公式 / 技能表 / 机制配置 / 条前缀 这一批游戏词取件，已搬进
# `ext_combat.battle.game_config`（第 7 批）。引擎侧只留上面的通用件：
# set_config / get_config / set_hook / mount / get_hook / unconfigured。
