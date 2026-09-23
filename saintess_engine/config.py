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


# 挂载的游戏配置表（引擎只调接口，不认识内容）
# 结构见各字段 docstring；由游戏层 set_config / 直接赋值 注入
_LOADED = {
    "effect_actions": {},  # 游戏名词效果 → 引擎动词动作序列
    "effect_rules": {},    # 统一效果规则表（V 系列：cap/panel/stat_scale/period/consume/cleanse…）
}

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


def load_game_rules(module) -> None:
    """从游戏规则模块加载约定字段。"""
    set_config("effect_actions", getattr(module, "EFFECT_ACTIONS", {}))
    set_config("effect_rules", getattr(module, "EFFECT_RULES", {}))


def register_hook_provider(fn) -> None:
    """内容侧注册「hook 惰性装配器」：首次访问未装配 hook 时调用一次。"""
    global _hook_provider
    _hook_provider = fn


def get_effect_actions() -> dict:
    """当前挂载的名词→动词动作表（默认空）。"""
    return _LOADED["effect_actions"]


def get_effect_rules() -> dict:
    """当前挂载的统一效果规则表（V 系列；EFFECT_RULES 字段全谱见设计文档）。"""
    return _LOADED.get("effect_rules") or {}


def state_def(key: str) -> dict:
    """查效果规则（无挂载/无条目 = 空 dict = 纯数值无规则）。

    V 系列直切：规则统一查 EFFECT_RULES 单表（数据层已把 STATE_EFFECTS
    内容并入 EFFECT_RULES，引擎不感知双表）。
    """
    return get_effect_rules().get(key) or {}


# ============================================================
# S1 注入面（hook）读写
# ============================================================

def set_hook(name: str, value) -> None:
    """内容侧挂载单个 hook（未知名忽略——引擎只认 _HOOKS 名单）。"""
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


class _NullFormulas:
    """未装配时的中性公式兜底（strict=True 时 config.formulas() 改为抛异常）。

    返回值全部为"零效应"：伤害 0 / 成长倍率 1.0 / 等级 0 / 无表达式。
    引擎据此不炸，但也不产生任何数值 —— 这正是 R8 提醒的"静默空放"，
    生产接入点必须显式装配（game.bootstrap.load_engine_config()）。
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
    """引擎数值公式对象（内容侧注入）。

    未装配：strict=True → 抛 EngineNotConfigured；否则返回中性兜底对象
    （_NullFormulas，全零效应，见 R8）。
    """
    value = get_hook("formulas")
    return value if value is not None else _NULL_FORMULAS


def kind_of(name: str) -> str:
    """kind 语义值（内容侧注入；未装配 → ""）。

    引擎不内置任何 kind 字面量（旧 actions.py 写死"物理/魔法/真伤/治疗/增益"）。
    """
    return (_HOOKS.get("kinds") or {}).get(name, "")


def skill_info_of(class_name: str, skill_key: str):
    """技能表查询（玩家侧）：内容侧 skill_lookup.skill_info。"""
    lookup = get_hook("skill_lookup")
    if lookup is None:
        return None
    return lookup.skill_info(class_name, skill_key)


def skill_by_key(skill_key: str):
    """技能表查询（key 侧）：内容侧 skill_lookup.skill_by_key。"""
    lookup = get_hook("skill_lookup")
    if lookup is None:
        return None
    return lookup.skill_by_key(skill_key)


def monster_skill_of(skill_key: str):
    """怪物技能表查询：内容侧 monster_skill_fn（未装配 → None）。"""
    fn = get_hook("monster_skill_fn")
    if fn is None:
        return None
    return fn(skill_key)


def mech_cfg(name: str) -> dict:
    """机制配置表查询（内容侧 mech_cfg_fn；未装配 → {}）。"""
    fn = get_hook("mech_cfg_fn")
    if fn is None:
        return {}
    return fn(name) or {}


def bar_prefix() -> str:
    """挂敌身条键前缀（内容侧 bar_prefix_fn；未装配 → ""）。"""
    fn = get_hook("bar_prefix_fn")
    if fn is None:
        return ""
    return fn() or ""
