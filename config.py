# -*- coding: utf-8 -*-
"""battle2 引擎——配置挂载点（引擎零游戏知识）。

引擎不内置任何游戏名词/数值规则。游戏层启动时把配置表挂进来：
    from game.battle2 import config
    config.state_effects = {...}   # 或 config.load_game_rules(module)

引擎内部所有"查表"都走 config 提供的接口，自身不认识表内容。
换一套配置 = 换挂载的表 = 新游戏（引擎代码零改动）。

S1 断链（docs/ENGINE_CONTENT_SPLIT_PLAN.md §3.2 / §7）：
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
    # ---- S5 注入面：game/battle2/formulas.py 的表读点（引擎零内容 import）----
    # 公式骨架参数表 fn() -> dict（内容侧 FORMULA_SKELETON）
    "formula_skeleton_fn": None,
    # 技能基础值常量表 fn() -> dict（内容侧 SKILL_FLAT_BASE / _PER_PLAYER_LV / _PER_SKILL_LV）
    "skill_flat_fn": None,
    # 技能升级配置查询 fn(info) -> dict（内容侧 SKILL_UP，见 content_rules.skills._skill_up）
    "skill_up_fn": None,
    # 技能等级查询 fn(player, skill_name) -> int（内容侧 content_rules.skills.skill_level_of）
    "skill_level_of_fn": None,
}

# R8：无挂载静默降级开关。
#   False（默认）= 与引擎历史行为一致：未装配 → 中性兜底（数值 0 / 空表），不炸；
#   True         = 未装配即抛 EngineNotConfigured（防测试假绿 / 线上静默失效）。
# 测试环境默认 False（避免已装配路径之外的既有用例集体报错）；生产接入点应显式
# 调用 game.bootstrap.load_engine_config() 后可按需打开。
strict = False

# 内容侧注册的"本游戏默认配置"装载器（旧 load_game_defaults 的实体）。
# 引擎只持有回调，不认识内容 —— 内容 → 引擎方向注入。
_defaults_loader = None
# 内容侧注册的"惰性装配器"：首次访问未装配 hook 时自动完成装配（见 get_hook）。
# 必要性：本仓库并存两种 import 路径（`game.*` 与 `data.plugins.dragonfall.game.*`
# = 同一份文件的两个模块树，plan §8-R2）——每个模块树各自装配自己的 config。
_hook_provider = None
_hook_provider_running = False


def set_config(kind: str, table) -> None:
    """游戏层挂载配置表。kind: effect_actions/effect_rules。"""
    if kind in _LOADED:
        _LOADED[kind] = table if table is not None else {}


def load_game_rules(module) -> None:
    """从游戏规则模块加载约定字段。"""
    set_config("effect_actions", getattr(module, "EFFECT_ACTIONS", {}))
    set_config("effect_rules", getattr(module, "EFFECT_RULES", {}))


def register_defaults_loader(fn) -> None:
    """内容侧注册「本游戏默认配置装载器」（引擎只存回调，不认识内容）。"""
    global _defaults_loader
    _defaults_loader = fn


def register_hook_provider(fn) -> None:
    """内容侧注册「hook 惰性装配器」：首次访问未装配 hook 时调用一次。"""
    global _hook_provider
    _hook_provider = fn


def load_game_defaults() -> None:
    """加载本游戏默认配置 —— **兼容 shim**（旧名/旧位置保留，52 个测试调用点）。

    S1 前本体在引擎包内（`from game.data import battle2_rules` = 反向边）；
    现委托给内容侧注册的装载器 `game.bootstrap.load_engine_config`
    （装配规则表 + 公式/面板/技能查询/kind hook，幂等）。
    未注册装载器时（纯引擎、无内容场景）静默为空。
    """
    if _defaults_loader is not None:
        _defaults_loader()


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
