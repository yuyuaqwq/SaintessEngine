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
**内容侧（各包的 `apply.py::install_engine()`）把公式/面板/技能查询/kind 常量 mount 进来**，
引擎自身零内容 import（门禁：tests/test_engine_purity.py）。
"""
from __future__ import annotations

import time

from .log import get_logger

# 装配失败必须留痕（见 `_lazy_bootstrap`）：静默吞掉 = 线上「技能打不动」零线索。
# ★ logger 名走门面（门禁 `tests/test_log.py` 判据 7：引擎业务模块零硬编码 logger 名）
#   —— 与 `clock.timer._LOG` 同一来源。
_HOOK_ERROR_LOG = get_logger("config")


class EngineNotConfigured(RuntimeError):
    """引擎求解所需的游戏挂载缺失（strict=True 模式下抛出，见 R8）。"""


class UnknownHook(ValueError):
    """装配了引擎不认识的 hook 名 —— 拼错，或内容侧走错了取件口。

    为什么要抛：静默丢弃会让「装配看似成功、实则没装」一路走到线上。
    报错带**相近名建议**（`difflib` 最近匹配）—— 拼错的形态绝大多数是手滑。
    """

    def __init__(self, name: str, known) -> None:
        import difflib                                   # 仅在报错路径用到
        near = difflib.get_close_matches(str(name), list(known), n=3, cutoff=0.6)
        hint = f"；你是不是想写：{' / '.join(near)}" if near else ""
        super().__init__(
            f"引擎不认识的 hook 名 {name!r}（注入面共 {len(known)} 个）{hint}。"
            f"★ 声明表（effect_rules / effect_actions / passive_proc 等）不走 mount，"
            f"走 `game_config.load_game_rules(...)`；完整名单见 `config._HOOKS`。"
        )


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
    #                     evolve_path, panel_bonus, race) -> dict
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
    # ---- 标签机制（battle/tags.py）：引擎固定词汇表的**槽位 → tag 名**声明 ----
    # fn() -> {槽位: tag}；缺省见 `battle/tags.DEFAULT_SLOTS`（如 immune_control → cc_immune）。
    # 内容侧要换名/挂层级（如 `immune.control`）就挂这个；引擎只按槽位取名字，不认游戏名词。
    "tag_slots_fn": None,
    # ---- 属性写口（battle/attributes.py）：唯一写入口的两个钩子 ----
    # 预改钩子 fn(actor, key, value, ctx) -> float | None（返回变换后的值；None = 交回内建边界）
    "attr_pre_fn": None,
    # 后改钩子 fn(actor, key, old, new, ctx) -> None（只在值真变了时调用；异常上抛）
    "attr_post_fn": None,
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
    # ★ fxmech（2026-09-26）「出手前的**通用**否决口」：`actions._skill_usable` 在扣费前问一次
    #   「这一手放不放」—— 与上面那条 mp 门槛**同形状、同一位置**，只是不分资源种类：
    #   引擎不知道「血 < 12% 时这一手不可用」「一场战斗最多一次」这类规则 —— 判据与回话
    #   全在内容侧 hook 里（引擎零数值、零玩家文案）。
    #   形状 = fn(battle, actor, info) -> str | 序列[str] | None：
    #     · `None`         ⇒ **放行**；
    #     · 非空 str / 序列 ⇒ **拦下**（技能不放），这一段逐字作为回话；
    #     · 空串 / 空序列 / 别的类型 ⇒ 抛 `EngineNotConfigured`（不许静默放过，
    #       也不由引擎替它编一句兜底）。
    #   ★ 读口同样走 `optional_hook`：不配 = 这款游戏没有通用否决 ⇒ 这一整段不存在
    #     （不拦、不回，与接线前逐字节相同）。
    "skill_gate_fn": None,
    # ★ P-11（2026-09-27）：**内置守卫**（`player` / `battle`）拦截句的读口 —— 那一句
    #   原先由宿主直接写在 `Host(register_hint=…, battle_hint=…)` 上（宿主面因此带着游戏词）。
    #   形状 = fn(key: str) -> str | None；`key` = 引擎给的**中性键名**（全集在
    #   `host/runtime.py::GUARD_KEYS`：`guard.register_missing` / `guard.battle_missing`），
    #   句子由内容侧按自己的文案表渲染（例：texts 槽位）。
    #   · 装了本口：宿主传的那两个值**当键**用（宿主只传键 ⇒ 宿主面零游戏词）；
    #     键不在中性全集里 ⇒ 抛；答不上来（None / 空 / 非 str）⇒ 抛。
    #   · 没装：值当**字面量**（旧口径 —— 与接线前逐字节相同，示例宿主 / 合成包不受影响）；
    #     但值恰好是引擎自带的中性键 ⇒ 抛（「给的是键却没人配句子」= 装漏了，
    #     绝不把键名当玩家文案投出去）。
    #   ★ 读口走 `optional_hook`（**不**受 strict 影响）：fail-closed 由 `Host` 那三态自己负责。
    "guard_text_fn": None,
    # ★ cue（2026-09-27）：**表现层订阅表**读口 —— 结算只发事实（cue），
    #   「这一条给玩家看什么」由内容侧订阅者渲染。
    #   形状 = fn() -> Mapping[cue 名, 订阅者...] | None：
    #     · `None`                   ⇒ 这款游戏还没接 cue（引擎连问都不问，
    #                                  已迁移点位 ⇒ 诊断 + 一行可读坏数据，见 cues.py）；
    #     · 映射                     ⇒ 引擎按自己的 `CUE_NAMES` 做**装配期对账**
    #                                  （缺订阅 / 多订阅 / 同一 cue 声明 ≥2 个 text ⇒ 抛）。
    #   订阅者最小形状：`{"kind": "text", "key": "<文案表 key>"}`（措辞留在内容侧文案表）
    #   或 `{"kind": "call", "handler": <callable>, "emits_lines": bool}`。
    #   形状与三条硬规矩（同步就地 / 只读契约 / fail-closed 三层）见 `saintess_engine/cues.py`。
    #   ★ 读口走 `optional_hook`：不配 = 不用 cue（合法状态），不是配置错误。
    "cue_subs_fn": None,
    # ★ B2（2026-09-27）「文案表供体」：内容侧把它**玩家可见措辞表**交出来
    #   （鸭子类型同 `text.TextTable`：`render_or(key, default, **slots)` + `__contains__`）。
    #   形状 = fn() -> 表 | None。
    #   `Battle(text=…)` **没显式给表**时问它一次（给了就听调用方的，不做合并）；
    #   不配 = 这款游戏没有表（引擎连问都不问）⇒ 未迁移点位走调用点兜底模板（与接线前
    #   逐字节相同），已迁移点位（模板**已从引擎删掉**）**报错**（诊断 + 一行坏数据）。
    #   ★ 引擎不内置任何表，也不预置任何一次调用点模板：这里只是「问内容侧要表」的口，
    #     答案（措辞）全在内容侧 —— 这就是「文案单源」的注入面。
    "text_table_fn": None,
}

# R8：无挂载静默降级开关。
#   False（默认）= 与引擎历史行为一致：未装配 → 中性兜底（数值 0 / 空表），不炸；
#   True         = 未装配即抛 EngineNotConfigured（防测试假绿 / 线上静默失效）。
# 测试环境默认 False（避免已装配路径之外的既有用例集体报错）；生产接入点应显式
# 调用内容侧 `apply.install_engine()` 后可按需打开。
strict = False

# 内容侧注册的"惰性装配器"：首次访问未装配 hook 时自动完成装配（见 get_hook）。
# 引擎只持有回调，不认识内容 —— 内容 → 引擎方向注入。
# 注意：这只是**惰性兜底**。引擎不得提供「加载本游戏默认配置」这类**游戏概念** API
# （S8 拆仓前的 `load_game_defaults()` 即此类 shim，已删 —— 游戏的配置装配是游戏
#  自己的入口，框架不认识「默认配置」是什么）。
_hook_provider = None
_hook_provider_running = False
# ★ 真幂等标志（2026-09-28 审计 L1571）：原注释两处宣称惰性装配器「一次，幂等」，
# 实跑反证 5 次未命中读口 → provider 被调 **5/5** 次（每次未命中都重问一遍）。
# 这里记「已问过」而不是靠 provider 自身幂等 —— 引擎不该假定内容侧的代价：
# provider 若重建整表 / 落标 / 打日志，就是 N 倍开销且不报错。
_hook_provider_done = False
# 「别人正装配、我等它」的上限（秒）。给上限是为了 provider 真死锁时读口不跟着挂死；
# 正常装配是微秒~毫秒级，0.5s 足够，超时会**记 error**（不是静默）。
_HOOK_BOOTSTRAP_WAIT = 0.5


def set_config(kind: str, table) -> None:
    """挂载一张配置表 —— **表名由调用方定，引擎不认识任何具体表名**。

    （2026-09-23 第 7 批：原先这里只认 `effect_actions` / `effect_rules` 两个白名单，
      那等于把游戏侧的词汇写进了引擎。改成任何 kind 都能挂。）

    `table=None` 表示「这张表已卸载」—— **原样存 None**，不与「空表」合并成一个态；
    取值回落由 `get_config` 的 `default` 负责（表形状真源在装载口，set 侧不猜）。
    """
    _LOADED[kind] = table


def get_config(kind: str, default=None):
    """读一张配置表（未挂载 → `default`）。与 `set_config` 配对的**泛型口**。

    游戏侧的专用取件（`get_effect_rules` / `state_def` / `skill_*` …）
    由扩展包在这上面包一层，引擎侧不再出现它们的名字。
    """
    return _LOADED.get(kind, default)


def register_hook_provider(fn) -> None:
    """内容侧注册「hook 惰性装配器」：首次访问未装配 hook 时调用**一次**。

    换 provider 会重置「已问过」标志（新装配器还有机会装上东西）。
    """
    global _hook_provider, _hook_provider_done
    _hook_provider = fn
    _hook_provider_done = False


# ============================================================
# S1 注入面（hook）读写
# ============================================================

def set_hook(name: str, value) -> None:
    """内容侧挂载单个 hook。**未知名抛 `UnknownHook`**（不再静默丢弃）。

    ★ `_HOOKS` 的名单是**注入面契约**（引擎声明它认识哪些 hook 名），不是
      「引擎里的游戏词」—— 第 7 批一度把它清空，两个门禁立刻红：
      `test_engine_purity.py` 正面断言「注入面含 hook X」、
      `test_engine_neutral_fallback.py` 断言「_HOOKS 认识两个第二段 hook 名」。
      名单留着；被搬走的是**取件函数**（get_effect_rules / skill_by_key …）。

    ★ 为什么未知名要抛（2026-09-28 审计 L1574）：旧写法 `if name in _HOOKS`
      静默丢弃 ⇒ 拼错一个字母（`mount(pannel_fn=…)`）时**装配看起来成功、
      实则那个 hook 根本没装**，等到线上表现为「效果不生效 / 伤害恒 0」才现形，
      且全程零信号。仓内实证：`games/my_game/content/apply.py:52-54` 传的
      `effect_rules` / `effect_actions` / `passive_proc` **三个都不在名单**
      （声明表该走 `game_config.load_game_rules`，见 `editor/packages.py:668`）
      —— 静默丢弃帮它掩盖了「这三条走错了口」这件事。
    """
    if name not in _HOOKS:
        raise UnknownHook(name, sorted(_HOOKS))
    _HOOKS[name] = value


def mount(**hooks) -> None:
    """内容侧批量挂载 hook（幂等）。**未知名抛 `UnknownHook`**，不静默丢弃。

    ★ 整批先校验、后落盘（2026-09-29 审计 afix1 第 27 轮）：旧写法是
      `for name, value in hooks.items(): set_hook(name, value)` —— **逐个**抛。
      于是一个**拼错的名字会把这一批前面那些合法的 hook 留在已装状态**：
      实跑 `mount(action_base_fn=..., pannel_fn=...)` ⇒ `UnknownHook` 抛了，
      而 `action_base_fn` 已装上 ⇒ 注入面停在**半装**的中途状态。
      这恰好是 `set_hook` 上面那段取证想防的那一类（拼错一个字母 ⇒
      装配看起来成功、实则注入面残缺），只是从「整条没装」换成了「装了一半」。
      对更危险的是它**不留任何痕迹**：抛错之后没人知道前面那几个已经落盘了。

    口径 = **要么全装、要么一个都不装**（事务性）：先把整批名字过一遍 `set_hook`
      的名单校验，任何一个不认识就在**动任何 `_HOOKS` 之前**抛 `UnknownHook`。
      逐字对齐 `set_hook` 的报错内容（`UnknownHook(name, sorted(_HOOKS))`），
      不另造第二份错误措辞。
    """
    for name in hooks:                                   # 先整批校验，未动任何 _HOOKS
        if name not in _HOOKS:
            raise UnknownHook(name, sorted(_HOOKS))
    for name, value in hooks.items():                    # 全装
        _HOOKS[name] = value


def _resolved(name: str):
    """取一个 hook 的值，**含「装配在途就等它装完」**这一层（两个读口共用）。

    为什么要有这一层（2026-09-28 审计 L1579）：`config` 是**进程级全局单例**，
    多线程读是现实场景。旧写法里 `_lazy_bootstrap()` 只防重入、不让**等**：
    线程 A 正在跑 provider（装配中），线程 B~H 看到 `_hook_provider_running`
    为真就直接返回，拿到的是**尚未装配的空槽**（静默中性兜底，strict=False
    下零信号）。实测 8 线程并发 ⇒ 7 个拿到 `None`；加了一次性标志位后
    更极端：**8 个全部 `None`**（没装上的那 7 个连重试机会都没有）。
    ⇒ 读口在这里等装配那一轮结束，再读一次。
    """
    value = _HOOKS.get(name)
    if value is None and _hook_provider is not None:
        _lazy_bootstrap()
        value = _HOOKS.get(name)
    if value is None and _hook_provider_running:
        _wait_lazy_bootstrap()
        value = _HOOKS.get(name)
    return value


def get_hook(name: str):
    """读单个 hook。

    未装配 → 先问内容侧惰性装配器（**全进程只问一次**，见 `_hook_provider_done`），
    并在别人正装时**等它装完**；仍未装配：strict=True → 抛 EngineNotConfigured，
    否则 None。
    """
    value = _resolved(name)
    if value is None and strict:
        raise EngineNotConfigured(
            f"引擎未装配：缺少 hook {name!r}（content 侧应调 apply.install_engine()）"
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
    return _resolved(name)


def _wait_lazy_bootstrap() -> None:
    """等**别的线程**那一轮惰性装配结束（超时上限保护，见 `_HOOK_BOOTSTRAP_WAIT`）。

    只等「在途」这一轮，不自己触发 provider（触发权归第一个读口），免得每个读口
    都去问一遍。返回后调用方重读一次。
    """
    deadline = time.monotonic() + _HOOK_BOOTSTRAP_WAIT
    while _hook_provider_running and time.monotonic() < deadline:
        time.sleep(0.005)
    if _hook_provider_running:
        _HOOK_ERROR_LOG.error(
            "等 hook 惰性装配完成超时（%.1fs）—— 读口按未装配处理；"
            "若这是常驻卡死，请查 provider 内部是否阻塞", _HOOK_BOOTSTRAP_WAIT)


def _lazy_bootstrap() -> None:
    """触发内容侧惰性装配（防重入 · **真幂等** · 失败可诊断）。

    * **防重入**：provider 自己回头读 hook 时不会无限递归。
    * **真幂等**：`provider_done` 在调用**前**置位 —— 无论成功还是抛错都只问一次。
      （旧写法每次未命中都重问，注释却写「一次，幂等」；provider 若重建整表 / 落盘 /
      打日志就是 N 倍开销且不报错。见审计 L1571。）
    * **失败不静默**：旧写法 `except Exception: pass` 让内容侧装配崩掉后
      `get_hook` 一路返回 `None`、**零日志零异常** ⇒ 线上表现是「技能打不动、
      伤害恒 0」而没有任何线索。现在打一条 error 日志，异常照样不外抛
      （`strict` 的 fail-closed 由两个读口自己判，不在这一层）。
    """
    global _hook_provider_running, _hook_provider_done
    if _hook_provider_running or _hook_provider_done:
        return
    _hook_provider_done = True
    _hook_provider_running = True
    try:
        _hook_provider()
    except Exception:                                    # noqa: BLE001
        _HOOK_ERROR_LOG.exception("hook 惰性装配器抛错：本次挂载视为未完成"
                                  "（strict=True 时由读口抛 EngineNotConfigured）")
    finally:
        _hook_provider_running = False


def unconfigured(name: str, default):
    """未装配兜底值：strict=True → 抛；否则返回 default（R8 静默降级语义）。"""
    get_hook(name)  # strict 检查
    return default


# 效果规则 / 公式 / 技能表 / 机制配置 / 条前缀 这一批游戏词取件，已搬进
# `ext_combat.battle.game_config`（第 7 批）。引擎侧只留上面的通用件：
# set_config / get_config / set_hook / mount / get_hook / unconfigured。
