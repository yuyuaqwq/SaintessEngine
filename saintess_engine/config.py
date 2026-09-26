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
    # ★ E4（2026-09-25）：表达式**变量表**供体（`saintess_engine.expr`）。
    #   形状 = fn() -> dict；键 = 变量名（表达式里直接写的名字），值 = 一条声明
    #   {"label": 显示名（可省）, "source": 取值来源}；来源三类通用原语：
    #   stat（属性快照）/ input（`build_vars` 的具名入参，可带 else 回落）/ const。
    #   不配 = 不存在 ⇒ 引擎沿用自带默认表（= 历史那一份，逐条相同）⇒ 行为一字不变。
    #   ★ 配了却给不出可用表（None/空/条目缺 source）⇒ 抛 EngineNotConfigured，
    #     不静默退回默认表（写错的声明不许无声无息）。
    "expr_vars_fn": None,
    # ★ P-54（2026-09-26）：宿主路由**未命中**任何包内声明时的回话。
    #   形状 = fn(text: str, prefix: str) -> str | list[str] | tuple[str, ...]。
    #   原先引擎在 `host/runtime.py` 里内置一句中文（还引用了宿主命令 `<prefix>help`）——
    #   引擎自带玩家可见文案，且引用了本服可能不存在的命令名。现改为**必须由内容侧声明**：
    #   不装配（或装了却给不出文本）⇒ `Host.route()` 抛 `EngineNotConfigured`（fail-closed），
    #   绝不静默给一句引擎自己编的玩家文案（与 guards / tips 的处置同一条规矩）。
    #   ★ 本口走 `optional_hook`（**不**受 `strict` 影响）：fail-closed 由宿主读口自己负责，
    #     否则 strict=False 的默认态就会退回「静默兜底」。
    "route_miss_text_fn": None,
    # ★ P-51（2026-09-26）「基础回复入口」：按刻（每次时间推进结算）问内容侧
    #   「这个 actor 这一拍回多少 mp」—— 引擎**零数值、零节奏、零玩家文案**。
    #   形状 = fn(battle, actor) -> dict | None：
    #     · `None`                     ⇒ 本拍不回复（引擎什么都不做）；
    #     · `{"mp": <数>, "text": …}`  ⇒ 回这么多（引擎只做 clamp 到 max_mp 与写回），
    #       `text`（可省）= 这一拍的回话（str / 序列），逐字进日志。
    #     · 别的形状 ⇒ 抛 `EngineNotConfigured`（声明了就要给得出可判读的回执）。
    #   ★ 读口走 `optional_hook`（**不**受 strict 影响）：不配 = 这款游戏没有基础回复
    #     （引擎连问都不问），不是配置错误。引擎不内置任何回复率 —— 那是编出来的数。
    "mp_regen_fn": None,
    # ★ P-51（2026-09-26）「mp 门槛入口」：`actions._skill_usable` 在扣费前问一次
    #   「这一手放不放」—— 同一条规矩：**引擎不认识任何数值**（多少算不够、比不比，
    #   全在内容侧），也不带玩家文案。
    #   形状 = fn(battle, actor, info, need_mp) -> str | 序列[str] | None：
    #     · `None`         ⇒ **放行**（不拦、不回）；
    #     · 非空 str / 序列 ⇒ **拦下**（技能不放），这一段逐字作为回话；
    #     · 空串 / 空序列 / 别的类型 ⇒ 抛 `EngineNotConfigured`（不许静默放过，
    #       也不由引擎替它编一句兜底）。
    #   `need_mp` = 内容侧技能表 `mp` 字段经引擎折算（`actions._skill_pay_of`：含
    #   `bonus.cost` 折扣、floor + 保底 1）后的值 —— 引擎只是转述，不参与判定。
    #   ★ 读口同样走 `optional_hook`：不配 = 这款游戏不拦 mp（引擎连问都不问）。
    "mp_gate_fn": None,
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


def optional_hook(name: str):
    """读一个**可选** hook：不配 ⇒ `None`（**不问** `strict`）。

    ★ 与 `get_hook` 的分工（E6 · 2026-09-25 新增）：
      · `get_hook` = **必需**通道 —— strict 模式下没装配要当场现形（点名缺哪个 hook）；
      · `optional_hook` = **可选**通道 —— 「不配」是合法状态（这款游戏不用这条声明，
        引擎连问都不问、不记日志、不抛），例如 `segment_plan_fn`：
        不配 = 不声明「两段耗时」，落回既有行动类别基准路径。
      可选通道若也走 strict，strict 模式（开发/测试建议开）就会因为「没用到的可选件」
      到处抛 —— 那是把「可选」当「必需」判。故本读口**只看存不存在**。
    """
    value = _HOOKS.get(name)
    if value is None and _hook_provider is not None:
        _lazy_bootstrap()
        value = _HOOKS.get(name)
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
