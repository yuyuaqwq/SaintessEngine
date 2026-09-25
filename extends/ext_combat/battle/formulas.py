# -*- coding: utf-8 -*-
"""引擎侧通用数值公式（S5：自 `game/engine.py` 拆出，docs/archive/ENGINE_CONTENT_SPLIT_PLAN.md §6.4）。

本模块**零游戏知识**（门禁 tests/test_engine_no_content.py）：不含任何游戏表名/职业名，
也不 import `game.data` / `game.content` / `game.core`。

拆分前这些函数住在 `game/engine.py`，直接读 `data/formula_skeleton.py`、
`data/skill_up.py` 与内容侧 `SKILL_UP` 表 / 技能等级 —— 那是「引擎 → 内容」反向依赖。
现一律走 `saintess_engine/config` 的注入面（S1 建立的 hook 面，方向：内容 → 引擎）：

    formula_skeleton_fn() -> dict            FORMULA_SKELETON（公式骨架参数表）
    skill_flat_fn()       -> dict            SKILL_FLAT_BASE / _PER_PLAYER_LV / _PER_SKILL_LV
    skill_up_fn(info)     -> dict            技能升级配置（内容侧 SKILL_UP 查询）
    skill_level_of_fn(player, skill_name) -> int   技能等级查询（内容侧技能 id resolve）

装配方见 `game/bootstrap.py: mount_engine_hooks()`；未装配时各 getter 返回中性值
（{} / 1 级兜底），与 `config._NullFormulas` 的「零效应」语义一致（plan §8-R8）。

公式结构（分支/截断序/随机）逐字自原 `game/engine.py` 搬运，**行为零变化**。

V4（2026-09-16）—— 最后 7 处「写死在引擎的游戏数值」下沉到内容侧同一注入面
----------------------------------------------------------------------------
`shield_default_pct` / `block`（cap·reduce）/ `heal_down`（per_stack·cap）/
`anti_heal`（cap）/ `reduce`（default_pct·cap）/ `gauge`（default_max）/ `skill_max_level`
—— 数值全部进内容侧 `FORMULA_SKELETON`，**不新开第二张表/第二套注入面**。
读点 = 本模块的具名 getter（`shield_default_pct()` / `block_cap()` / … ），下游
`battle/effects.py` / `battle/landing.py` / `battle/actions.py` / `gauge/__init__.py` 只调它们；
未装配 → `_NEUTRAL_SKELETON` 的同语义中性值（零效应，不崩）。装配后内容侧声明值 = 原写死值
⇒ 玩家可见行为一字不变（正证与极端值反证见 `out/LANDING.md`）。
"""
import random

from saintess_engine import config as _cfg
from .diagnostics import diag as _diag   # 阶段/钩子出错的诊断通道（P-44）


# 未装配时的中性骨架参数（与 _NullFormulas 同语义：零效应，不产生额外数值）。
# 为何需要：本模块 docstring 承诺「未装配时各 getter 返回中性值（{} / 1 级兜底）…不炸」，
# 但下游直接索引 _skeleton()["skill_growth"] / float(_flat.get(...)) —— 空 dict 会
# KeyError / float(None) TypeError，使第三方接入（只挂部分 hook）首战即崩。
# 与 config.get_hook 的关系：strict=True 时 get_hook 先抛 EngineNotConfigured（配置错误
# 可被严格模式捕获），strict=False（默认）下落到此中性表 —— 两级语义互补。
# 生产路径（游戏侧 game/bootstrap.py 已挂 formula_skeleton_fn/skill_flat_fn）取值完全不变。
#
# V4（2026-09-16）：最后 7 处「写死在引擎的游戏数值」下沉到内容侧骨架表（同一注入面，
# 不新开第二张表）。这里给出**同语义中性值** —— 未装配时各分支「不产生数值」：
#   护盾兜底 0.0（不产盾）/ 格挡 cap 0.0（不格挡）/ 禁疗 per_stack+cap 0.0（不减疗）/
#   重伤 cap 0.0（不减疗）/ 减伤 default 0.0 + cap 0.0（不减伤）/ 条 max 0 → 调用处回落
#   100.0（历史兜底值，见 gauge）/ 技能满级 5（= 原 SKILL_MAX_LEVEL，技能等级兜底语义
#   不变：growth 的零效应另由 skill_growth 的 divisor=1 + 级 1 兜底保证）。
# ⚠️ 与**已装配**路径的区别：装配后内容侧声明值 = 老写死值 ⇒ 玩家可见行为零变化。
_NEUTRAL_SKELETON = {
    "skill_growth": {
        "power_per_lv_divisor": 1,      # p 缺省 0 → 0/1 = 0 → 倍率恒 1.0（无成长）
        "buff_turns_base": 3,           # 与 skill_buff_turns 签名默认一致
        "buff_turns_per_lv": 1,         # 每级 +1 刻（模块 doc 口径）
        "cond_default": 0,              # 条件倍率无成长（保持 cond.mult）
        "mech_default_div": 2,          # 默认每 2 级 +1 层；兼防除零
        "lifesteal_default": 0.0,       # 无吸血
        "lifesteal_per_lv_divisor": 1,  # 兼防除零（l 缺省 0 → 无成长）
    },
    "skill_learn_cost": {"divisor": 1, "base": 0},
    # ★ 2026-09-25（审计 E2）：闪避上限原先**硬编码在 landing**（`min(dodge, 0.40)`）——
    #   平衡数值不该住在引擎里。注意这条**不在「零效应中性段」里**：它的默认值取原写死值
    #   （0.40，与旧 `_roll_dodge` 上限逐字一致），因为闪避是已装内容依赖的通用承伤规则。
    #   内容侧要改就声明 `FORMULA_SKELETON["dodge"]["cap"]`（读点 `dodge_cap()`）。
    "dodge": {"cap": 0.40},
    # ---- V4 中性段（零效应；语义见上）----
    "shield_default_pct": 0.0,
    "block": {"cap": 0.0, "reduce": 0.0},
    "heal_down": {"per_stack": 0.0, "cap": 0.0},
    "anti_heal": {"cap": 0.0},
    "reduce": {"default_pct": 0.0, "cap": 0.0},
    "gauge": {"default_max": 0},
    "skill_max_level": 5,
}


# ============================================================
# 注入面读取（内容侧装配；未装配 → 中性值）
# ============================================================

def _skeleton() -> dict:
    """公式骨架参数表（内容侧注入 `formula_skeleton_fn`；未装配 → 中性骨架）。

    中性骨架保证下游 `_skeleton()["skill_growth"][...]` 索引可用（见 _NEUTRAL_SKELETON）。
    """
    fn = _cfg.get_hook("formula_skeleton_fn")
    return (fn() if fn is not None else None) or _NEUTRAL_SKELETON


def _skill_flat_cfg() -> dict:
    """技能基础值常量表（内容侧注入 `skill_flat_fn`；未装配 → {}）。"""
    fn = _cfg.get_hook("skill_flat_fn")
    return (fn() if fn is not None else None) or {}


def _skill_up(info: dict | None) -> dict:
    """技能升级配置查询（内容侧注入 `skill_up_fn`；未装配 → {}）。

    「零默认值」：无挂载 → 空 dict = 无成长配置（与 S5 前 `C.SKILL_UP` 查不到同语义）。
    """
    fn = _cfg.get_hook("skill_up_fn")
    if fn is None:
        return {}
    return fn(info) or {}


# ============================================================
# 战斗落地常量读取（V4：原写死在引擎的字面量 → 内容侧骨架表同一注入面）
#
# 为什么集中在本模块：`_skeleton()` 是骨架表的**唯一**读口（内容侧 `formula_skeleton_fn`），
# 本批不新开第二张表/第二套注入面。下游（effects / landing / actions / gauge）只调这里
# 的具名 getter；未装配 → 各自返回 `_NEUTRAL_SKELETON` 的同语义中性值（零效应，不崩）。
# 取数纪律：`float(...)`/`int(...)` + `or 默认` 兜脏值（NaN/None/字符串坏配置不炸）。
# ============================================================

def _skel_num(key: str, default: float) -> float:
    """骨架表**顶层**数值读取（缺键/坏值 → default）。"""
    try:
        return float(_skeleton().get(key, default))
    except Exception:                                        # noqa: BLE001
        return float(default)


def _skel_sub_num(group: str, key: str, default: float) -> float:
    """骨架表**子组**数值读取（组/键缺、坏值 → default）。"""
    try:
        grp = _skeleton().get(group) or {}
        return float(grp.get(key, default))
    except Exception:                                        # noqa: BLE001
        return float(default)


def shield_default_pct() -> float:
    """护盾兜底比例（无 value / 无 pct 的 shield 动作 → int(max_hp×pct)）。

    内容侧 `FORMULA_SKELETON["shield_default_pct"]`；未装配 → 0.0（不产盾）。
    两个读点同键：effects.py `act_shield` 的兜底 / actions.py `_do_buff` 的 `shield_pct` 缺省。
    """
    return _skel_num("shield_default_pct", 0.0)


def block_cap() -> float:
    """格挡**概率上限**（承伤侧 `bc = min(block, cap)`）。未装配 → 0.0（不格挡）。"""
    return _skel_sub_num("block", "cap", 0.0)


def block_reduce() -> float:
    """格挡**命中后减免比例**（`red = max(1, int(dmg × reduce))`）。未装配 → 0.0。"""
    return _skel_sub_num("block", "reduce", 0.0)


def dodge_cap() -> float:
    """闪避**上限**（承伤侧 `min(dodge, cap)`）。

    ★ 2026-09-25（审计 E2）：这个数原先**硬编码在 `landing._roll_dodge`**（`min(dodge, 0.40)`）。
    搬进声明表之后，内容侧要改自己的闪避上限只需声明 `FORMULA_SKELETON["dodge"]["cap"]`，
    不必动引擎。默认值 = 原写死值 0.40（未装配时也逐字一致）。
    """
    return _skel_sub_num("dodge", "cap", 0.40)


def heal_down_per_stack() -> float:
    """禁疗**每层**比例（`cut = min(stacks × per_stack, cap)`）。未装配 → 0.0。"""
    return _skel_sub_num("heal_down", "per_stack", 0.0)


def heal_down_cap() -> float:
    """禁疗**上限**。未装配 → 0.0（不减疗）。"""
    return _skel_sub_num("heal_down", "cap", 0.0)


def anti_heal_cap() -> float:
    """重伤（_anti_heal_pct）**上限**。未装配 → 0.0（不减疗）。"""
    return _skel_sub_num("anti_heal", "cap", 0.0)


def reduce_default_pct() -> float:
    """减伤兜底比例（技能未配 reduce_pct / mech_val 时）。未装配 → 0.0（不减伤）。"""
    return _skel_sub_num("reduce", "default_pct", 0.0)


def reduce_cap() -> float:
    """减伤 clamp **上限**。未装配 → 0.0（clamp 到 0 = 不减伤，不崩）。"""
    return _skel_sub_num("reduce", "cap", 0.0)


def gauge_default_max() -> float:
    """敌身条 `max` 缺省上限（gauge `bar_gain` 的封顶兜底）。

    未装配 → 0.0；调用方按「<=0 → 历史兜底 100」处理（见 `ext_combat.gauge`）。
    """
    return _skel_sub_num("gauge", "default_max", 0.0)


def skill_max_level_default() -> int:
    """技能满级默认值（内容侧 `FORMULA_SKELETON["skill_max_level"]`；未装配 → 5）。

    未装配的 5 是**既有中性语义**（原 `SKILL_MAX_LEVEL = 5`）：技能满级 = 5 是引擎的
    「等级兜底」而非「游戏数值」，故中性表保留 5；成长本身由 skill_growth 的零效应关掉。
    """
    try:
        return int(_skel_num("skill_max_level", 5))
    except Exception:                                        # noqa: BLE001
        return 5


# ============================================================
# 技能数值公式
# ============================================================

def skill_formula_expr(info: dict | None, level: int = 1):
    """v160 逐级公式选择器：技能配 exprs（每级一条公式）时按技能等级取公式。

    优先级：
    1. exprs 数组 → exprs[clamp(level-1, 0, len-1)]（越界取最后一条，防配置失误）
    2. expr 单条字符串 → 原样返回（skill_lv 变量在公式内自行成长）
    3. 都没有 → None（调用方回退旧 stat/mult/flat 逻辑）

    formula 段/治疗 heal_formula 共用（段元素也可能是 dict 带 exprs 键）。
    """
    if not info:
        return None
    _exprs = info.get("exprs")
    if _exprs:
        if isinstance(_exprs, str):
            return _exprs
        _list = list(_exprs or [])
        if _list:
            _lv = max(1, min(int(level or 1), len(_list)))
            return _list[_lv - 1]
    return info.get("expr") or None


def skill_formula_expr_for_seg(seg: dict | None, level: int = 1):
    """公式段级逐级选择：段带 exprs/expr 时按技能等级取（exprs 优先）。"""
    if not seg:
        return None
    _exprs = seg.get("exprs")
    if _exprs:
        if isinstance(_exprs, str):
            return _exprs
        _list = list(_exprs or [])
        if _list:
            _lv = max(1, min(int(level or 1), len(_list)))
            return _list[_lv - 1]
    return seg.get("expr") or None


def skill_max_level(info: dict | None = None) -> int:
    """技能独立满级(v56.4)：SKILL_UP 配了 max 用配置，否则默认读骨架表（V4 前 = 常量 5）"""
    default_max = skill_max_level_default()
    if not info:
        return default_max
    return int(_skill_up(info).get("max", default_max))


def skill_power_mult(level: int, info: dict | None = None) -> float:
    """技能等级对 power 的倍率（v180 鱼鱼：没配 p = 无成长，删默认兜底——默认每级+10% 曾
    误伤无 SKILL_UP 配置的怪物技能：按折算等级白吃成长 ×1.4。现配了 p 才成长，没配恒 1.0）
    P2F-1：/100 系数进 data/formula_skeleton.py（FORMULA_SKELETON["skill_growth"]["power_per_lv_divisor"]）"""
    lv = max(1, min(level, skill_max_level(info)))
    p = int(_skill_up(info).get("p", 0) or 0)
    return 1.0 + (p / _skeleton()["skill_growth"]["power_per_lv_divisor"]) * (lv - 1)


def skill_flat_value(player_lv: int, skill_lv: int, info: dict | None = None) -> int:
    """v156 技能基础值（保底伤害）：flat = BASE + player_lv×PER_LV + skill_lv×PER_SKILL_LV。

    - 随玩家等级成长（等级越高基础越高，低攻不刮痧）
    - 随技能等级成长（技能升级基础值也涨）
    - 高等级时百分比主导（基础值占比稀释，不膨胀）
    数值常量在 game/data/skill_up.py（SKILL_FLAT_*），工具集/引擎共用同一口径。
    v158：支持每技能独立配置（SKILL_UP 条目可选字段）：
      flat_base      基础值基数（缺省 SKILL_FLAT_BASE=12）
      flat_per_lv    每玩家等级成长（缺省 1）
      flat_per_skill 每技能等级成长（缺省 2）
    未配置的技能完全回退全局常量（行为不变）。
    """
    _flat = _skill_flat_cfg()
    lv = max(1, min(skill_lv, skill_max_level(info)))
    up = _skill_up(info)
    # 中性兜底：未装配 skill_flat_fn 时 _flat 为 {} → .get(...) 得 None → float(None) 崩。
    # 与 _skeleton()/_NullFormulas 同语义（零效应），且 strict=True 时 get_hook 已先行抛错。
    base = float(up.get("flat_base", _flat.get("SKILL_FLAT_BASE")) or 0)
    per_lv = float(up.get("flat_per_lv", _flat.get("SKILL_FLAT_PER_PLAYER_LV")) or 0)
    per_skill = float(up.get("flat_per_skill", _flat.get("SKILL_FLAT_PER_SKILL_LV")) or 0)
    return int(base + player_lv * per_lv + lv * per_skill)


def skill_buff_turns(level: int, base: int = 3, info: dict | None = None) -> int:
    """增益技能升级：每级持续刻＋1。

    v162：info 配了 buff_turns 时用它做 base（每个增益技能 desc 的持续各不相同——
    铁壁 8 / 战吼 10 / 冥想 6），否则默认 3（Lv.1=3，Lv.5=7）。
    P2F-1：默认 base/每级成长进 data/formula_skeleton.py（FORMULA_SKELETON["skill_growth"]）"""
    _sg = _skeleton()["skill_growth"]
    if base is None or base == 3:
        base = int(_sg["buff_turns_base"])
    lv = max(1, min(level, skill_max_level(info)))
    if info is not None:
        _bt = info.get("buff_turns")
        if _bt:
            base = int(_bt)
    return base + (lv - 1) * int(_sg["buff_turns_per_lv"])


def skill_cond_mult(cond: dict | None, level: int, info: dict | None = None) -> float:
    """条件转化倍率随等级成长。info 配了 c 时按该技能成长，否则默认每级＋0.05
    P2F-1：默认每级成长进 data/formula_skeleton.py（FORMULA_SKELETON["skill_growth"]["cond_default"]）"""
    if not cond:
        return 1.0
    lv = max(1, min(level, skill_max_level(info)))
    c = _skill_up(info).get("c", _skeleton()["skill_growth"]["cond_default"])
    return cond.get("mult", 1.0) + c * (lv - 1)


def skill_mech_val(info: dict, level: int) -> int:
    """机制叠层随等级成长。info 配了 m 时按该技能间隔，否则默认每 2 级＋1 层
    P2F-1：默认间隔进 data/formula_skeleton.py（FORMULA_SKELETON["skill_growth"]["mech_default_div"]）"""
    _sg = _skeleton()["skill_growth"]
    base = int(info.get("mech_val", 0) or 0)
    lv = max(1, min(level, skill_max_level(info)))
    m = max(1, int(_skill_up(info).get("m", _sg["mech_default_div"]) or 0))  # v109.2 防御：m≤0 时按默认 2（防除零）
    return base + (lv - 1) // m


def skill_lifesteal_pct(info: dict | None, level: int) -> float:
    """吸血比例随等级成长：基础读技能 lifesteal 字段（如嗜血斩 0.25），未配置默认 20%；配了 l 时每级＋2%
    v104 R3 P2-10 修复：原固定 0.20 基础不读 lifesteal 字段 → 嗜血斩 desc 承诺 25% 实机 20%
    P2F-1：默认 base/每级除数进 data/formula_skeleton.py（FORMULA_SKELETON["skill_growth"]）"""
    _sg = _skeleton()["skill_growth"]
    lv = max(1, min(level, skill_max_level(info)))
    base = float((info or {}).get("lifesteal", 0) or 0) or _sg["lifesteal_default"]
    return base + _skill_up(info).get("l", 0) / _sg["lifesteal_per_lv_divisor"] * (lv - 1)


def skill_learn_cost(need_lv: int) -> int:
    """学习技能消耗的技能点(v12：按技能等级定价，等级越高越贵)
    v104 R3 P2-17：删除未使用的 level 死参数（原签名 level, need_lv 但成本只与 need_lv 挂钩）
    P2F-1：定价参数进 data/formula_skeleton.py（FORMULA_SKELETON["skill_learn_cost"]，//6+2）"""
    _c = _skeleton()["skill_learn_cost"]
    return need_lv // _c["divisor"] + _c["base"]


def skill_level_of(player: dict, skill_name: str) -> int:
    """技能等级查询（内容侧注入 `skill_level_of_fn`）。

    引擎侧只保留签名/转发位（引擎 `.actions` 经本包 `battle/game_config.py` 的 `formulas()` 转发消费）；实体在
    `game/content_rules/skills.py: skill_level_of`（读 player.skill_levels + 技能 id resolve）。
    未装配 → 1（未升级 Lv.1 兜底，与原「查不到按未升级 Lv.1」一致）。
    """
    fn = _cfg.get_hook("skill_level_of_fn")
    if fn is None:
        return 1
    return int(fn(player, skill_name) or 1)


def skill_expr_preview(info: dict | None, level: int, stats: dict | None = None) -> float:
    """v160 表达式技能数值预览：按技能等级取公式，代入玩家当前属性求值。

    用于技能详情『数值成长』展示（未乘外部乘区/未过防御的期望基础值）：
    - 伤害 expr：skill_formula_expr(info, lv) → eval_expr
    - 治疗 heal_formula/heal_expr：同语义（返回治疗量期望）
    - 无表达式：返回 0.0（调用方回退旧 power×mult 百分比展示）

    stats 缺省时只给 level（表达式里不含玩家属性也能算）；含 atk/matk/max_hp 等时按实际属性代入。
    """
    if not info:
        return 0.0
    lv = max(1, min(int(level or 1), skill_max_level(info)))
    from saintess_engine.expr import compile_expr, eval_expr, build_vars
    _expr = skill_formula_expr(info, lv)
    if not _expr:
        # 治疗逐级（heal_formula 字符串数组 / heal_exprs）
        _hf = info.get("heal_formula") or info.get("heal_expr")
        _he = info.get("heal_exprs")
        if isinstance(_he, list) and _he:
            _lvx = max(1, min(lv, len(_he)))
            _expr = _he[_lvx - 1]
        elif isinstance(_hf, list) and _hf and all(isinstance(_x, str) for _x in _hf):
            _lvx = max(1, min(lv, len(_hf)))
            _expr = _hf[_lvx - 1]
        elif isinstance(_hf, str):
            _expr = _hf
        elif isinstance(_hf, list):
            # 段列表：逐段取 expr 求和（与 battle 治疗结算一致）
            _vars = build_vars(stats or {}, skill_lv=lv)
            _total = 0.0
            for _seg in _hf:
                if isinstance(_seg, dict):
                    _se = skill_formula_expr_for_seg(_seg, lv)
                    if _se:
                        try:
                            _total += eval_expr(compile_expr(_se), _vars) * float(_seg.get("mult", 1.0) or 1.0)
                        except Exception as _e:
                            # ★ 2026-09-25（E1 修）：本函数是**纯计算 helper**（参数里没有 battle），
                            #   原先写 `_diag(battle, …)` ⇒ 作用域里没有 `battle` ⇒ 走到这里抛
                            #   NameError（把「不再静默」变成「炸在诊断上」）。diag 的契约允许
                            #   `battle=None`（只落引擎日志，不进某一场的诊断表）—— 这正是它的用途。
                            _diag(None, "skill_expr_preview", _e)          # 审计 P-44：不再静默（行为不变）
                            pass
            return _total
        if not _expr:
            return 0.0
    try:
        _vars = build_vars(stats or {}, player_lv=int((stats or {}).get("level", 0) or 0),
                           skill_lv=lv)
        return float(eval_expr(compile_expr(_expr), _vars))
    except Exception:
        return 0.0


# ============================================================
# 战斗
# ============================================================

def _damage_binding():
    """E1b：槽位 `damage` 绑了哪条声明？未装配 / 未绑 ⇒ None（调用方走原路）。"""
    from saintess_engine import config
    from saintess_engine.formula import FormulaDeclError, binding_of
    if config.get_hook("formula_bindings_fn") is None:
        return None, None
    tab_hook = config.get_hook("formula_table_fn")
    tbl = tab_hook() if tab_hook is not None else None
    if tbl is None:
        raise FormulaDeclError(
            "槽位 'damage' 有绑定但 `formula_table_fn` 未装配（或返回 None）——"
            "绑定表与公式表必须同时给")
    return binding_of("damage", table=tbl), tbl


def calc_damage(atk, def_, is_crit=False, variance=0.15, pierce=False, pene_pct=0.0, pene_flat=0, dmg_type="phys", *, level=None):
    """伤害公式(v22 非线性减伤)：dmg = atk²/(atk+def)，防御收益递减，杜绝物理免疫
    v106 穿透：有效防御 = max(0, int(def × (1-pene_pct)) - pene_flat)（先百分比后固定，下限 0）
    v107 伤害类型四层架构（鱼鱼拍板）：dmg_type = phys/magi/true
    - true 真伤：绕过全部减伤（无防御公式，dmg = atk 直伤），与 pierce 语义区分——
      pierce 仅无视防御公式、调用方仍可能叠加免伤段；true 为纯真伤（不吸/不反/全无视）
    - 真伤同样吃波动与暴击（暴击倍率由调用方 crit_dmg 段统一追加）

    ★ E1b（2026-09-21）：槽位 `damage` 被绑定时走**声明**；不配绑定表 ⇒ 下面一字不动。
      声明链的输入映射（足量、无静默兜底）：
        base=atk · def=def_（真伤/穿透 ⇒ 0，等价于"绕过减伤"）
        crit_mult = 1.5 / 1.0 · variance=variance · pene_* 原样
        level ⇒ 算 k_def 用（**没给就抛**，不猜）
      ★ 两处**有意**的语义差异（新游戏的声明是设计真源，旧路径只服务未绑定的包）：
        1. 旧：先波动后暴击（两次取整）；声明：先暴击后波动（一次取整）
        2. 旧：非线性减伤 atk²/(atk+def)；声明：def/(def+k_def) 双曲线
      ⇒ 未绑定的包（含旧包）行为逐字节不变；这是 R1「不配 = 不存在」的判据。
    """
    _did, _tbl = _damage_binding()
    if _did is not None:
        if level is None:
            from saintess_engine.formula import FormulaDeclError       # 局部导入：避开可能的循环导入
            raise FormulaDeclError(
                "槽位 'damage' 已绑定声明，但调用方没给 level（算 k_def 要用）——"
                "★ 不许拿默认等级兜底：那会把『少传参数』变成静默错值")
        _zero_dr = bool(pierce) or dmg_type == "true"
        _v = {
            "level": float(level),
            "def": 0.0 if _zero_dr else float(def_),
            "base": float(atk),
            "mult_skill": 1.0, "amp": 0.0, "mitigation": 0.0,
            "crit_mult": 1.5 if is_crit else 1.0, "elem_mult": 1.0,
            "variance": float(variance),
            "pene_pct": 0.0 if _zero_dr else float(pene_pct or 0.0),
            "pene_flat": 0.0 if _zero_dr else float(pene_flat or 0),
        }
        return max(1, int(_tbl.run(_did, _v)[0]))

    if dmg_type == "true" or pierce:
        dmg = atk
    else:
        # v106：穿透削减有效防御（百分比上限 0.6 由聚合层 cap，这里兜底防脏值）
        eff_def = def_
        try:
            pct = min(max(float(pene_pct), 0.0), 0.6)
            flat = max(int(pene_flat), 0)
            if pct > 0 or flat > 0:
                eff_def = max(0, int(def_ * (1 - pct)) - flat)
        except Exception:
            eff_def = def_
        # v104 M02 P2：atk+def_ 为 0 时直接返回伤害下限 1，防 ZeroDivisionError
        if atk + eff_def <= 0:
            return 1
        # 非线性减伤：防御越高收益越低，但不会完全免疫
        dmg = atk * atk / (atk + eff_def)
    dmg = max(1, dmg)
    dmg = int(dmg * (1 + random.uniform(-variance, variance)))
    if is_crit:
        dmg = int(dmg * 1.5)
    return max(1, dmg)


def resolve_formula(formula, stats, target_def, target_mdef, is_crit=False,
                    pene_phys=0.0, pene_magi=0.0, pene_flat_phys=0, pene_flat_magi=0,
                    variance=0.15, mult=1.0, target_max_hp=None, randomize=True):
    """v156 通用公式解释器——所有伤害来源（技能/装备/食物/宠物/敌方）共用。

    formula 每段：
      {"stat": "atk"|"matk"|"max_hp"|"flat",   # 属性来源（flat=纯固定值）
       "mult": 1.2,                            # 百分比系数（乘以 stat）
       "flat": 50,                             # 固定值（基础值；可选，默认 0）
       "type": "phys"|"magi"|"true",           # 伤害类型（吃 def/mdef/无视）
       "chance": 0.5}                          # 触发概率（可选；缺省 100%）

    stats: 攻击方面板（atk/matk/max_hp 等）
    target_def/target_mdef: 目标防御
    mult: 外部乘区（技能 power 成长/条件/叠层等，由调用方算好）
    target_max_hp: 目标 max_hp（stat=max_hp 时用；缺省用 stats.max_hp）

    返回 (总伤害, 魔法段伤害) —— magi 段单独返回供吸血/魔免分账。
    """
    # ★ E1b：槽位 `damage` 的声明链要用 level 算 k_def。等级真源 = stats["level"]
    #   （`stats.actor_stats` 统一从 actor 取，玩家与怪一视同仁；缺键 ⇒ 0，未绑定时无人读它）。
    _lv = int((stats or {}).get("level", 0) or 0)
    total = 0
    magi_part = 0
    if not formula:
        return 0, 0
    import random as _r
    for seg in formula:
        # 触发概率
        chance = float(seg.get("chance", 1.0))
        if chance != 1.0:
            chance = float(seg.get("chance", 1.0) or 0.0)
        if randomize and chance < 1.0 and _r.random() > chance:
            continue
        ftype = seg.get("type", "phys")
        # v159 表达式段：expr 字符串 → 求值（预编译缓存），替代 stat/mult/flat
        # v160 逐级：段带 exprs 数组时按技能等级取公式（越界取最后）
        _expr = skill_formula_expr_for_seg(seg, int(stats.get("_skill_lv", 1) or 1))
        if _expr:
            try:
                from saintess_engine.expr import compile_expr, eval_expr, build_vars
                _vars = build_vars(stats, player_lv=int(stats.get("level", 0) or 0),
                                   skill_lv=int(stats.get("_skill_lv", 0) or 0),
                                   target_max_hp=target_max_hp,
                                   base=float(seg.get("flat", 0) or 0))
                _code = compile_expr(_expr)
                _val = eval_expr(_code, _vars) * mult
                base = int(_val)
            except Exception:
                base = 0
        else:
            fstat = seg.get("stat", "atk")
            fmult = float(seg.get("mult", 1.0) or 1.0) * mult
            fflat = int(seg.get("flat", 0) or 0)
            # 属性来源
            if fstat == "matk":
                base = int(stats.get("matk", 0) * fmult) + fflat
            elif fstat == "max_hp":
                _mh = target_max_hp if target_max_hp is not None else stats.get("max_hp", 0)
                base = int(_mh * fmult) + fflat
            elif fstat == "flat":
                base = fflat
            else:  # atk
                base = int(stats.get("atk", 0) * fmult) + fflat
        # 伤害类型 → 防御/穿透
        if ftype == "true":
            dmg = calc_damage(base, 0, is_crit, variance=variance, dmg_type="true", level=_lv)
        elif ftype == "magi":
            dmg = calc_damage(base, target_mdef, is_crit, variance=variance, level=_lv,
                              pene_pct=pene_magi, pene_flat=pene_flat_magi, dmg_type="magi")
            magi_part += dmg
        else:
            # v157 formula 段级 pierce：seg 带 "pierce": true → 绕过防御公式
            # （与非 formula 物理 pierce 技能 calc_damage(pierce=True) 等价）
            if seg.get("pierce"):
                dmg = calc_damage(base, 0, is_crit, variance=variance, pierce=True, dmg_type="phys", level=_lv)
            else:
                dmg = calc_damage(base, target_def, is_crit, variance=variance, level=_lv,
                                  pene_pct=pene_phys, pene_flat=pene_flat_phys, dmg_type="phys")
        total += dmg
    return total, magi_part


# ============================================================
# 技能 mp 消耗薄封装（命令层预检同源）
# ============================================================

def skill_mp_pay_of(actor_or_player: dict, info: dict) -> int:
    """技能实际 mp 消耗（命令层施放预检同源折算，v181.M-smallfix 薄封装）。

    与 saintess_engine 引擎 actions._skill_pay_of 同一折算点：actor bonus.cost 域
    （mp_pct/mp_flat + when 判据 element/mech_prefix/name_contains）折扣 →
    floor 取整 + 保底 1（玩家受益方向）——即引擎施放时实际会扣的 mp 值。
    dict 无 bonus.cost 容器/域 → 声明费直通（读源兜底铁律，与引擎行为一致）。
    命令层不便直接 import saintess_engine 引擎内部函数 → 引擎层薄封装，saintess_engine 核心零改动。
    """
    try:
        from .actions import skill_pay_of
        return int(skill_pay_of(actor_or_player or {}, info or {}).get("mp") or 0)
    except Exception:
        return int((info or {}).get("mp", 0) or 0)
