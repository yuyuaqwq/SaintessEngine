# -*- coding: utf-8 -*-
"""《奥兰迪亚》装备/词条/武器特效装配层 —— equip（P4-D2 搬运物，逐字保真）。

真源：游戏仓 `C:/Users/yuyu/qqbot/data/plugins/dragonfall/game/services/battle_equip_proc.py`
      **全文件 1174 行**（模块 docstring :2-19 + 正文 :20-1174）。
本文件 = 真源 `:20-1174` 的**逐字拷贝**：函数体、数值、`logs`/效果 dict 文案、注释一字未改
（对拍见 `overnight/d2_equip_verify.py` A1：真源正文 ↔ 本文件正文 逐行 diff 只剩白名单 3 处）。

★ B10-L1（2026-09-13）**宿主薄壳化**：游戏仓 `game/services/battle_equip_proc.py` 与
  `game/services/battle_we_procs.py` 已改成**薄壳**（包加载口 + 全量再导出 + 入口一行委托），
  本文件 = 这两族的**唯一实现**（双源收口）。宿主薄壳 ↔ 原宿主正文的行为等价证据 =
  `overnight/b10_l1_snap.py`（1756 例逐字节快照：返回值 + actor/battle 全量副作用 + 渲染文案，
  改前改后同 sha256 `cffef69fdaf9ad9bca834342ca1f12ed6a4e8d8089e10d15dd01e7438db9adbd`）。

入口（对外，真源同名）
  `apply_to_actor(actor)`（真源 :1133）—— 命令层开战前调用（幂等口径见下 §幂等）：
      0) `_apply_bonus_domains` → `actor["bonus"]["cap"]`（上限词条 max_bonus）/`["cost"]`
         （消耗修正词条），panel 由开战仪式播种、此处不动
      1) `weapon_triggers` + `affix_triggers` → `actor["triggers"]`（事件型效果声明）
      2) proc_heal amp 4 key → `actor["effects"]["heal_amp_pct"]["value"]["amp"]`
  其余对外函数同名同义：`map_event` / `equipped_weapon_keys` / `equipped_affix_ids` /
  `triggers_for_key` / `affix_triggers_for_key` / `weapon_triggers` / `affix_triggers` /
  `install_ext_actions`。

结构改写清单（只有 4 处，全在「import 路径 / 去 install」层，零行为变化）
1. **:65 数据表来源**（`_we_data()` 内，惰性）：`from ..data import weapon_effect_data as W`
   → `from . import we_data as W`（包内 `content/mech/we_data.py:WEAPON_EFFECT_DATA`，79 条，
   与游戏仓 `game/data/weapon_effect_data.py` 逐条相等——见验收 A1 的对拍）。
2. **:129 词条表来源**（`_affix_data()` 内，惰性）：`from ..data import affixes as _A` +
   `getattr(_A, "AFFIXES", {})` → `from ..apply import _read_json` +
   `_read_json("affixes.json", {})`（包内 `content/data/affixes.json`，76 条，
   与游戏仓 `game/data/affixes.py:AFFIXES` 逐条相等）。**同一张表、同一形状**，仅换载体。
3. **:1089 去扩展动作注册调用**（`install_ext_actions()` 内）：真源
   `from .import battle_we_procs as _WEP` + `_WEP.ensure_registered()` → 包内
   `from . import we_procs as _WEP`（族模块 import 即注册）。真源 `ensure_registered()`
   自己写明「装饰器已随模块 import 注册——本函数仅做幂等标记」，故删调用不丢注册。
4. **传说专属表来源**（`_legendary_data()` 内，惰性，D3 传说装配批新增）：真源
   `from ..data import affixes as _A` + `getattr(_A, "LEGENDARY_EFFECTS", {})` →
   `from ..apply import _read_json` + `_read_json("legendary_effects.json", {})`
   （包内 `content/data/legendary_effects.json`，93 条，与游戏仓
   `game/data/affixes.py:LEGENDARY_EFFECTS` **逐条 deep-equal**——见
   `overnight/d3_legendary_verify.py` A2 的对拍）。**同一张表、同一形状**，仅换载体。

幂等（**真源语义，如实标注，勿当成本文件缺陷**）
  `apply_to_actor` 裸调**不幂等**：`tr.setdefault(ev, []).extend(effs)` 会让 triggers 条目翻倍
  （真源 docstring 自称「幂等」，但那是**入口 `_content_applied` 保险丝**的口径 —— 游戏仓
  `game/content_rules/apply.py` 装配前先判该标记；本包同口径，保险丝在 `content/apply.py`，
  不在本文件）。`bonus.cap` / `bonus.cost` 是**覆盖写**，裸调天然幂等（卸装后重装配回落）。
  实测见 `overnight/d2_equip_verify.py` A3。

真源模块 docstring（逐字保留）
------------------------------
'''saintess_engine 装备特效/词条装配层（game/services/battle_equip_proc.py，N9）。

saintess_engine 包外（引擎零知识——引擎不 import 本模块，本模块 import 引擎/数据）。
职责：把玩家装备的 weapon_effect / affix 数据 → actor["triggers"] 声明
（N8 事件总线消费），使装备特效在 saintess_engine 战斗中生效。

架构（docs/REFACTOR_v181P4_N9_migration.md §2）：
- 效果源 = actor["triggers"] = {事件: [效果 dict]}，效果 dict 两种形态：
  ① 纯动词（引擎原生能力）：shield/buff/state_add/control/heal/...
  ② 族扩展动作（复杂机制，ACTION_HANDLERS 扩展注册）：type="we_xxx"
- 事件映射：旧 proc 事件集 → saintess_engine 19 事件（hit→attack_hit+skill_hit 展开等）
- 数值权威：weapon_effect_data.WEAPON_EFFECT_DATA + 装备行 we_data 覆盖层
  （读表零默认值铁律：缺字段 = 无此行为）

N9 批次：第一批 = battle_start 起手类纯动词 key（proc_shield 起手 2 +
proc_buff 起手 6），验证「读表 → 事件映射 → triggers 装配 → 引擎 fire」管线。
后续批按 docs/REFACTOR_v181P4_N9_migration.md §3 铺开。
'''

包内依赖（全部包内份）
  · `content/mech/we_data.py` WEAPON_EFFECT_DATA（82 = 79 + D3 增量 3）+ ACT_TICK
  · `content/data/affixes.json` AFFIXES（76）· `equip_roster.json` EQUIP_ROSTER（687）
  · `content/data/legendary_effects.json` LEGENDARY_EFFECTS（93，D3 传说装配批接入）
  · `content/mech/we_procs.py` 27 个 we_* 族扩展动作（本层翻译出的 `type="we_*"` 由它执行）

D3 增量（2026-09-13，与真源同一 hunk 逐字镜像；对拍见 `overnight/d3_gap_fix_verify.py`）
  · 武器翻译器 +2：`_translate_legend_mult`（3 个「放错表」键 = 只在 LEGENDARY_EFFECTS
    却被 roster 当 weapon_effect 引用）、`_translate_first_turn_dodge`（首刻闪避）
  · 词条翻译器 +2：`_af_ember_brand`（cond_hp_lt 门槛）、`_af_combo_ward`（受击概率回补连段）
  · `_AFFIX_RES_GAIN_ON` +`"combo_skill": ("skill_hit", {})`；`_AFFIX_RES_GAIN_IDS`
    +`combo_recover`；`we_procs.we_affix_res_gain` +`cond_hp_lt` 门槛（镜像真源同函数）
  · 文件头「真源 :1174 行」等旧行号为各批交付时快照，本次改动后真源行号整体下移，未重排。
  · D3 传说装配批（同批第二 hunk）：`item["legendary"]` 并入 id 流
    （`_LEGENDARY_TRANSLATORS` / `legendary_triggers_for_key` / `legendary_triggers` /
    `_UNSUPPORTED_LEGENDARY`，只对 trigger!="stat" 生效）；对拍见
    `overnight/d3_legendary_verify.py`（逐字镜像 + 修前/修后条数 + 四项回归）。
"""
from __future__ import annotations

import logging

from typing import Optional

# ============================================================
# 旧事件集 → saintess_engine 19 事件映射
# ============================================================

# 旧 weapon proc 事件集（weapon_effects._WE_KEY_EVENTS 的 key）
_EVENT_MAP = {
    "battle_start": ("battle_start",),
    "hit": ("attack_hit", "skill_hit"),   # 普攻+技能通用命中
    "skill_hit": ("skill_hit",),
    "skill_cast": ("act_cast",),
    "taken": ("on_taken",),
    "heal": ("on_heal",),
    "turn_start": ("turn_start",),
    "threshold": ("threshold",),
    "crit": ("crit",),
    "kill": ("on_kill",),
    # N9A-2：旧 enemy_act（敌方行动后）→ 通用 act_done 广播（全员触发，效果侧
    # 自己 if 敌我判断——randuin/ice_vein 敌对判断在 we_act_done_slow 扩展动作内）
    "enemy_act": ("act_done",),
    # 以下旧时机 saintess_engine 无 1:1 点位，第一批不迁（后续批次/上层处理）：
    # taken_after / turn_end / passive（这三个名字**全仓无消费者**，属死名）；
    # dot_taken 于 2026-09-13 补映射 → "dot_tick"（对齐 docs/REFACTOR_v181P4_N9_migration.md:61 的
    # N9 迁移表；当前无数据使用，零行为影响，防将来补数据时又变成"装了不生效"）。
    "dot_taken": ("dot_tick",),
}

# 引擎事件全集（权威 = `saintess_engine/battle/effect_triggers.py` 的 EVENTS 常量）
# ★ 2026-09-13 反静默失效：`fire()` 对**不在 EVENTS 全集**的事件名**静默 return**，
#   于是"翻译器/数据写了个拼错或过期的时机名"= 触发器装上了却永不触发、且没有任何痕迹。
#   这里把"直通但引擎不认"的名字收集起来（去重）+ 告警一条，供门禁与自检读取。
_UNKNOWN_EVENTS: list = []

# ★ D3 2026-09-13 反静默失效（同款做法，另一处）：装备行 `item["legendary"]`（传说专属特效
#   id）若在本装配层**没有翻译器**（= 详情页有承诺、实战无行为 = 玩家可见缺口），进本清单
#   （去重）+ `logging.warning` 一条，供门禁/自检读取；装配口径见下方「传说专属特效装配条目」。
_UNSUPPORTED_LEGENDARY: list = []


def _known_engine_events() -> frozenset:
    """引擎事件全集；**取不到就返回空集 = 不告警**（告警本身不允许成为新的故障点）。"""
    try:
        from saintess_engine.battle.effect_triggers import EVENTS as _E
        return frozenset(_E)
    except Exception:      # noqa: BLE001
        return frozenset()


# 每个旧事件映射后的 saintess_engine 事件（返回 tuple）
def map_event(old_ev: str) -> tuple:
    """旧事件 → saintess_engine 事件展开；不在表 = 假定已是 saintess_engine 原生事件名，同名直通
    （dmg_calc/taken_calc/battle_start 等装配层可直接用 saintess_engine 事件名）。

    ★ 2026-09-13 反静默失效：直通的名字若不在引擎 EVENTS 全集里，`fire()` 会静默忽略 →
    触发器永不生效且无痕迹。此处**只告警不改行为**（仍直通返回，语义与改造前逐字一致），
    未知名去重缓存（装配器每场战斗都装，不去重会刷屏）。
    """
    got = _EVENT_MAP.get(old_ev)
    if got is not None:
        return got
    _known = _known_engine_events()
    if _known and old_ev not in _known and old_ev not in _UNKNOWN_EVENTS:
        _UNKNOWN_EVENTS.append(old_ev)
        logging.getLogger(__name__).warning(
            "装配层事件名 %r 不在引擎事件全集里（fire 会静默忽略 → 该触发器永不生效）", old_ev)
    return (old_ev,)


# ============================================================
# 数据表读取（数值权威）
# ============================================================

_WE_TABLE = None


def _we_data() -> dict:
    """武器特效数据表（包内 `mech/we_data.py` 唯一真源）。

    ★ R5（静默降级扫描）：删掉 `try/except Exception: _WE_TABLE = {}` —— 它把
    「数据模块缺失 / 属性名写错」静默降级成**空表 = 所有武器特效全部失效**（玩家侧零提示）。
    这是装配缺陷，取不到就抛。
    """
    global _WE_TABLE
    if _WE_TABLE is None:
        from . import we_data as W
        _WE_TABLE = W.WEAPON_EFFECT_DATA
    return _WE_TABLE


def _we_config(key: str, actor: Optional[dict] = None) -> dict:
    """key 的生效参数：数据表权威 + 装备行 we_data 覆盖（同旧 effect_data 语义）。"""
    cfg = dict((_we_data() or {}).get(key) or {})
    if actor:
        for item in (actor.get("equipment") or {}).values():
            if not isinstance(item, dict):
                continue
            if item.get("weapon_effect") == key and isinstance(item.get("we_data"), dict):
                cfg.update(item["we_data"])
    return cfg


def equipped_weapon_keys(actor: dict) -> list:
    """actor 已装备的 weapon_effect key 列表（各槽位，去重保序）。"""
    out = []
    for item in (actor.get("equipment") or {}).values():
        if not isinstance(item, dict):
            continue
        we = item.get("weapon_effect")
        if we and we not in out:
            out.append(we)
    return out


# ============================================================
# affix 词条装配（N9.7：AFFIXES 76 → 分档）
# ============================================================
# 分档结论（docs/REFACTOR_v181P4_N9_7_affix_migration.md）：
# - A1 stat 型 26：装备生成时已折算进 item.stats → saintess_engine 面板自动含，装配层跳过
# - B 事件型：trigger 映射 saintess_engine 事件 → 翻译成效果声明（此文件翻译器）
# - 资源型 R4（N9.7e）：res+gain+on 事件 gain 型 10 条已装（we_affix_res_gain）
#   + boiling_blood 怒气满减伤（taken_calc state_full）；rage/chi/energy/faith/cp/
#   element 资源容器 cap 已由 EFFECT_RULES 声明（EFFECT_RULES 无行=装配即无限攒，
#   行已补全）
# - 上限型 max_bonus（rage_forge/divine_radiance/holy_heart/rhythm_badge/chi_limit/
#   full_pack）v181.M-R2e 方案 A 已装：装配写 actor["bonus"]["cap"]（_apply_cap_bonus，
#   覆盖写幂等），引擎 _cap_of 收敛点（effects 叠层 clamp/schedule period gain/渠道
#   gain clamp）读动态 cap = EFFECT_RULES 基准 + bonus.cap。cost_reduce 型
#   （energy_blade/arcane_focus/sigil_blessing 消耗修正）v181.M-bonus 已装：
#   装配写 actor["bonus"]["cost"]（_apply_cost_bonus 分域，覆盖写幂等），引擎
#   actions._skill_pay_of 折算（预检/扣费同源、floor 取整、保底 1）；cond 修正型
#   ember_brand（D3 已装：数据 cond → 动作参数 cond_hp_lt 门槛 + 命中/受击观测点）、
#   combo_recover（D3 已装：combo_skill → skill_hit）见下；
#   regen 型 energy_tide/swift_tailwind（每刻回能 turn_start）与 purify（驱散）
#   v181.M-affixtail 已装（翻译器见下；cap clamp 全收敛 _cap_of）。
# finisher（终结技伤害乘区）v181.M-bonus 已装（dmg_calc mech_any 谓词，见 _af_finisher）。
# tier 语义（旧 _affix_effs）：effect.tiers[装备品质] 覆盖主数值键（如能量上限
# full_pack purple 10/orange 20）；装配时按 item.quality 取档。

_AFFIX_TABLE = None


def _affix_data() -> dict:
    """AFFIXES 表（数值权威，惰性读）。"""
    global _AFFIX_TABLE
    if _AFFIX_TABLE is None:
        try:
            from ..apply import _read_json
            _AFFIX_TABLE = _read_json("affixes.json", {})
        except Exception:
            _AFFIX_TABLE = {}
    return _AFFIX_TABLE


def equipped_affix_ids(actor: dict) -> list:
    """actor 已装备的全部 affix id（各槽位 affixes 列表，去重保序）。"""
    out = []
    for item in (actor.get("equipment") or {}).values():
        if not isinstance(item, dict):
            continue
        for aid in (item.get("affixes") or []):
            if aid and aid not in out:
                out.append(aid)
    return out


def _apply_cap_bonus(actor: dict) -> dict:
    """上限词条装配（v181.M-R2e 方案 A：affix 动态 cap）——写 actor["bonus"]["cap"]。

    扫当前装备全部 affixes：effect 含 {res, max_bonus} → bonus.cap[res] += N
    （多件/多词条同资源累加）。数值权威 = AFFIXES 表（_affix_effect_final 已按装备
    品质取 tiers 档：full_pack purple 10 / orange 20）。energy_blade 现行数据为
    cost_reduce 型（无 max_bonus）→ 零贡献自动跳过（版本漂移，非上限词条）。
    纯 flat int 容器（bonus 容器平行哲学——引擎零语义，effects._cap_of clamp 时
    读取）。覆盖写幂等：每次 apply_to_actor 按当前装备重算 → 卸装后重装配自然回落。
    """
    out: dict = {}
    for aid in equipped_affix_ids(actor):
        try:
            eff = _affix_effect_final(aid, actor, None)
            res = eff.get("res")
            mb = eff.get("max_bonus")
            if not res or not isinstance(mb, (int, float)) or float(mb) <= 0:
                continue
            out[res] = int(out.get(res, 0) + float(mb))
        except Exception:
            continue  # 单词条解析异常不阻断其余（容错铁律）
    return out


# ============================================================
# v181.M-bonus cost 域装配（消耗修正词条 → actor["bonus"]["cost"]）
# ============================================================
# 形态：actor["bonus"]["cost"] = {
#     "mp_pct": float,   # 无条件全技能魔力折扣（% 值，0.10 = -10%）
#     "mp_flat": int,    # 无条件魔力平减（固定减点）
#     "res": {res: pct}, # 无条件该资源消耗折扣（energy_blade 0.05 = 精力消耗 -5%）
#     "when": [{"mp_pct"/"mp_flat": ..., "judge": {...}}],  # 有条件条目（施放点按技能判）
# }
# judge 谓词（引擎施放点判，任一命中即生效——字段间 OR）：
#   {"element": True}                          → 技能 info.element 非空（元素系）
#   {"mech_prefix": ["arcane", ...]}           → info.mech startswith 任一
#   {"name_contains": ["神迹"]}                → 技能显示名含任一子串
# 引擎折算见 saintess_engine/actions.py _skill_pay_of（预检/扣费同源、保底 1、floor 取整）。

# 元素/奥术判据（arcane_focus desc：元素/奥术技能 魔力消耗 -10%——法师技能数据
# element 字段只标元素系 7 技、奥术系走 mech=arcane/arcane_burst、部分大招仅名字
# 含"元素/奥术"（万象风暴等无标记记缺口）→ 三路 OR 覆盖 desc 语义）
_JUDGE_ARCANE = {
    "element": True,
    "mech_prefix": ["fire", "ice", "thunder", "element", "arcane"],
    "name_contains": ["元素", "奥术"],
}


def _apply_cost_bonus(actor: dict) -> dict:
    """消耗修正词条装配（v181.M-bonus）——扫 affixes，产 bonus.cost 分域 dict。

    识别（_affix_effect_final 已按品质取 tiers 档）：
    - energy_blade   effect {res, cost_reduce}      → res[res] += 折扣%（该资源消耗技
      能才受影响 → 无条件即天然过滤）
    - arcane_focus   effect {mp_cost_reduce: 0.10}  → when 条目 mp_pct + 元素/奥术判据
      （float 值 = 比例折扣）
    - sigil_blessing effect {mp_cost_reduce: 5, on: miracle} → when 条目 mp_flat + 神迹
      判据（int 值 = 平减；神迹技 = 技能名含"神迹"，牧师树神迹/神迹·重生）
    覆盖写幂等：按当前装备全量重算 → 卸装后重装配自然回落。
    """
    cost: dict = {}
    _whens = []
    for aid in equipped_affix_ids(actor):
        try:
            eff = _affix_effect_final(aid, actor, None)
            if not eff:
                continue
            # ① res 折扣型（energy_blade）：该资源消耗 -cost_reduce%
            _res = eff.get("res")
            _cr = eff.get("cost_reduce")
            if _res and isinstance(_cr, (int, float)) and float(_cr) > 0:
                resm = cost.setdefault("res", {})
                resm[_res] = float(resm.get(_res, 0.0) or 0.0) + float(_cr)
            # ② mp 折扣型（arcane_focus / sigil_blessing）
            _mcr = eff.get("mp_cost_reduce")
            if isinstance(_mcr, (int, float)) and float(_mcr) > 0:
                if isinstance(_mcr, float):
                    # 比例折扣（0.10 = -10%）：元素/奥术技能判据
                    _whens.append({"mp_pct": float(_mcr), "judge": dict(_JUDGE_ARCANE)})
                else:
                    # int 平减：sigil_blessing 限神迹技（on: miracle → 技能名含神迹）
                    if eff.get("on") == "miracle":
                        _whens.append({"mp_flat": int(_mcr),
                                       "judge": {"name_contains": ["神迹"]}})
                    else:
                        cost["mp_flat"] = int(cost.get("mp_flat", 0) or 0) + int(_mcr)
        except Exception:
            continue  # 单词条解析异常不阻断其余（容错铁律）
    if _whens:
        cost["when"] = _whens
    return cost


def _apply_bonus_domains(actor: dict) -> None:
    """装备词条 → bonus 容器分域（v181.M-bonus；cap/cost 覆盖写，panel 不动）。

    apply_to_actor 第 0 步调用。actor 无 bonus 容器（未走开战仪式播种的直调路径）
    → 补建空容器（panel {}），cap/cost 照常装配。
    """
    b = actor.setdefault("bonus", {"panel": {}, "cap": {}, "cost": {}})
    b["cap"] = _apply_cap_bonus(actor)
    b["cost"] = _apply_cost_bonus(actor)


def _tier_value(eff: dict, quality: str):
    """effect.tiers[quality] 取档覆盖（旧 _affix_effs 语义）；无 tiers → None。"""
    tiers = eff.get("tiers")
    if not isinstance(tiers, dict):
        return None
    return tiers.get(quality or "")


# tier 档位作用键（缺省 = effect 首个数值键）。crit_return 的 effect 首数值键是
# gain=1，但 tiers {blue:0.15, purple:0.25, orange:0.40} 是 chance 档位（desc：
# 暴击 15% 概率得点，史诗 25%/传说 40%）→ 显式声明 tier 作用到 chance 防错档。
_AFFIX_TIER_KEY = {
    "crit_return": "chance",
}


def _affix_effect_final(aid: str, actor: dict, tier_key: str = None) -> dict:
    """词条 effect + tier 覆盖（读 AFFIXES 表；未找到 = {} → 缺字段无行为）。

    tier_key 给定时档位覆盖该字段（_AFFIX_TIER_KEY）；缺省 = 首个数值键
    （主数值键 = 排除辅助键（cond/on/desc）外的第一个数值键）。"""
    info = (_affix_data() or {}).get(aid) or {}
    eff = dict(info.get("effect") or {})
    tiers = eff.get("tiers")
    if isinstance(tiers, dict):
        # 找该词条所在装备的品质（同名词条多件品质不同 → 取最高档）
        tv = None
        for item in (actor.get("equipment") or {}).values():
            if isinstance(item, dict) and aid in (item.get("affixes") or []):
                q = item.get("quality", "")
                if q in tiers:
                    cand = tiers[q]
                    if tv is None or (isinstance(cand, (int, float))
                                      and cand > tv):
                        tv = cand
        eff.pop("tiers", None)
        if tv is not None:
            if tier_key and isinstance(eff.get(tier_key), (int, float)):
                eff[tier_key] = tv
                return eff
            for k, v in eff.items():
                if isinstance(v, (int, float)) and k not in ("cond",):
                    eff[k] = tv
                    break
    return eff


# ============================================================
# affix → 效果声明翻译器（按 aid 注册；chance 数据表权威）
# ============================================================

# 已支持 affix key 清单 → 翻译器（函数签名 (aid, actor, eff) -> {old_event: [效果]})
_AFFIX_TRANSLATORS: dict = {}


def _register_affix(aid: str):
    """affix 翻译器注册装饰器。"""
    def deco(fn):
        _AFFIX_TRANSLATORS[aid] = fn
        return fn
    return deco


def _affix_chance_of(aid: str) -> float:
    """词条触发概率（AFFIXES 表 chance；缺省 None = 恒触发——旧语义）。"""
    return (_affix_data() or {}).get(aid, {}).get("chance")


def _affix_hit_ev(eff: dict) -> str:
    """词条命中挂点：数据表自定义事件（如 soul_devourer skill_hit）缺省 hit
    （装配层 map_event 展开 attack_hit+skill_hit）。"""
    return eff.get("event") or "hit"


@_register_affix("shield")
def _af_shield(aid, actor, eff):
    """护盾：battle_start 10% maxhp 盾（3 刻）。（无 chance → 纯动词可直接走）"""
    return {"battle_start": [{"type": "shield", "key": "affix_shield",
                              "pct": float(eff.get("shield_hp_pct") or 0.10),
                              "turns": int(eff.get("turns") or 3), "on": "caster"}]}


@_register_affix("regen")
def _af_regen(aid, actor, eff):
    """回春：turn_start 回 1% 最大生命。"""
    return {"turn_start": [{"type": "heal", "pct": float(eff.get("pct") or 0.01),
                            "on": "caster"}]}


@_register_affix("meditate")
def _af_meditate(aid, actor, eff):
    """冥想：turn_start 回 1% 最大生命（法师词条，同 regen 语义）。"""
    return {"turn_start": [{"type": "heal", "pct": float(eff.get("pct") or 0.01),
                            "on": "caster"}]}


# ============ N9.7b on_hit 族（带 chance/附加伤害 → 扩展动作层） ============

@_register_affix("bleed")
def _af_bleed(aid, actor, eff):
    """流血：20% 使目标流血（每刻 dot_pct 生命，3 刻）。"""
    return {"hit": [{"type": "we_affix_dot", "key": aid, "aid": aid,
                     "state_key": "affix_bleed", "chance": _affix_chance_of(aid),
                     "stacks": eff.get("stacks") or 3}]}


@_register_affix("armor_break")
def _af_armor_break(aid, actor, eff):
    """破甲：25% 降低目标防御 15%（2 刻）。"""
    return {"hit": [{"type": "we_affix_defdown", "key": aid, "aid": aid,
                     "chance": _affix_chance_of(aid),
                     "pct": eff.get("pct") or 0.15,
                     "turns": eff.get("turns") or 2}]}


@_register_affix("element_fire")
def _af_element_fire(aid, actor, eff):
    """元素附加·火：5% 属性伤害（恒触发）。"""
    return {"hit": [{"type": "we_affix_element", "key": aid, "aid": aid,
                     "element": eff.get("element") or "fire",
                     "pct": eff.get("pct") or 0.05, "name": "火焰附加"}]}


@_register_affix("element_ice")
def _af_element_ice(aid, actor, eff):
    """元素附加·冰：5% 属性伤害 + 减速。"""
    return {"hit": [{"type": "we_affix_element", "key": aid, "aid": aid,
                     "element": eff.get("element") or "ice",
                     "pct": eff.get("pct") or 0.05, "name": "冰霜附加",
                     "slow": eff.get("slow") or 0.10,
                     "slow_turns": eff.get("slow_turns") or 2}]}


@_register_affix("element_thunder")
def _af_element_thunder(aid, actor, eff):
    """元素附加·雷：5% 属性伤害 + chance 20% 小爆。"""
    return {"hit": [{"type": "we_affix_element", "key": aid, "aid": aid,
                     "element": eff.get("element") or "thunder",
                     "pct": eff.get("pct") or 0.05, "name": "雷光附加",
                     "chance": _affix_chance_of(aid),
                     "thunder_bonus": eff.get("thunder_bonus") or 0.20}]}


@_register_affix("combo")
def _af_combo(aid, actor, eff):
    """连击：15% 追加一次 50% 伤害（本击 dmg × extra_atk）。"""
    return {"hit": [{"type": "we_affix_bonus", "key": aid, "aid": aid,
                     "mode": "dmg_pct", "chance": _affix_chance_of(aid),
                     "pct": eff.get("extra_atk") or 0.50,
                     "tag": "⚡", "name": "连击"}]}


@_register_affix("charge")
def _af_charge(aid, actor, eff):
    """蓄力：10% 追加 50% 伤害（本击 dmg × dmg_pct）。"""
    return {"hit": [{"type": "we_affix_bonus", "key": aid, "aid": aid,
                     "mode": "dmg_pct", "chance": _affix_chance_of(aid),
                     "pct": eff.get("dmg_pct") or 0.50,
                     "tag": "💪", "name": "蓄力爆发"}]}


@_register_affix("pierce")
def _af_pierce(aid, actor, eff):
    """贯穿：20% 无视防御追加伤害（玩家 atk × atk_pct 真伤）。"""
    return {"hit": [{"type": "we_affix_bonus", "key": aid, "aid": aid,
                     "mode": "atk_true", "chance": _affix_chance_of(aid),
                     "atk_pct": eff.get("atk_pct") or 0.60,
                     "tag": "🏹", "name": "贯穿"}]}


# ============ N9.7c on_taken 族 + dmg_reduce ============

@_register_affix("counter")
def _af_counter(aid, actor, eff):
    """反击：受击 20% 反击攻击方 atk×60%（on_taken，攻击方在 ctx.source）。"""
    return {"on_taken": [{"type": "we_affix_counter", "key": aid, "aid": aid,
                          "chance": _affix_chance_of(aid),
                          "atk_pct": eff.get("pct") or 0.60}]}


@_register_affix("tenacity_cc")
def _af_tenacity_cc(aid, actor, eff):
    """坚韧：受击 20% 免疫/清除自身负面 + 回 3% maxhp。"""
    return {"on_taken": [{"type": "we_affix_tenacity", "key": aid, "aid": aid,
                          "chance": _affix_chance_of(aid),
                          "heal_pct": eff.get("heal_pct") or 0.03}]}


@_register_affix("dmg_reduce")
def _af_dmg_reduce(aid, actor, eff):
    """全减伤（常驻 3%）：taken_calc 乘区 ×（1-0.03）。stat trigger 但实际是
    受击减伤（旧 TAKEN_EFFECTS reduce 段），装配成 taken_calc 乘区。"""
    return {"taken_calc": [{"type": "we_taken_mult_cond", "key": aid, "cond": "always",
                            "mult": 1.0 - float(eff.get("dmg_reduce") or 0.03),
                            "tag": "🛡️减伤"}]}


# ============ N9.7d 条件乘区（passive → dmg_calc 钩子） ============

@_register_affix("execute")
def _af_execute(aid, actor, eff):
    """处决：目标生命 <30% ×1.3（dmg_calc hp_target_lt）。"""
    return {"dmg_calc": [{"type": "we_dmg_mult_cond", "key": aid,
                          "cond": "hp_target_lt",
                          "threshold": eff.get("execute_threshold") or 0.30,
                          "mult": eff.get("dmg_mult") or 1.30,
                          "tag": eff.get("tag") or "💀处决"}]}


@_register_affix("hunt")
def _af_hunt(aid, actor, eff):
    """追猎：目标带猎印 ×1.2（dmg_calc enemy_marked）。"""
    return {"dmg_calc": [{"type": "we_dmg_mult_cond", "key": aid,
                          "cond": "enemy_marked",
                          "mult": eff.get("dmg_mult") or 1.20,
                          "tag": eff.get("tag") or "🎯追猎"}]}


@_register_affix("break_magic")
def _af_break_magic(aid, actor, eff):
    """破魔：目标为法系 ×1.25（dmg_calc role_caster）。"""
    return {"dmg_calc": [{"type": "we_dmg_mult_cond", "key": aid,
                          "cond": "role_caster",
                          "mult": eff.get("dmg_mult") or 1.25,
                          "tag": eff.get("tag") or "🔮破魔"}]}


@_register_affix("dragon_aw")
def _af_dragon_aw(aid, actor, eff):
    """龙威：目标名含龙 ×1.25（dmg_calc name_contains）。"""
    return {"dmg_calc": [{"type": "we_dmg_mult_cond", "key": aid,
                          "cond": "name_contains",
                          "keywords": eff.get("enemy_contains") or ["龙"],
                          "mult": eff.get("dmg_mult") or 1.25,
                          "tag": eff.get("tag") or "🐉龙威"}]}


# ============ N9.7e 资源 gain 型（R4：effect {res, gain, on} → 事件叠资源） ============
# 统一规则：词条 effect 含 res+gain+on（事件时机）→ actor.triggers[对应 saintess_engine 事件]
# 挂 we_affix_res_gain 叠层生产动作（cap clamp 查 EFFECT_RULES[res].cap，动作侧）。
# 事件选型（与词条语义最近且不重复触发——全部 subject=owner 自己，或 battle_start
# 开战一次性，无广播误触发/无双事件重复）：
#   on_attack   普攻行动触发 → attack_hit：普攻命中后（saintess_engine 唯一 self-subject 的
#               普攻点位——普攻经 do_skill 结算但 ev 按 _basic 标 attack_hit）。
#               未命中（闪避/0 伤早退不 fire）该次不触发：引擎无「普攻行动」级独立
#               事件，act_done 全员广播且 ctx 无行动类型（无法区分普攻/技能/防御），
#               act_begin 同样无类型 → 命中事件是语义最近且不误触发的挂点。
#   on_skill    技能行动触发 → skill_hit：技能命中后（heal/buff 类技能无命中事件 →
#               天然只覆盖攻击技能，与「攻击/技能」攒怒语义一致；同上不选 act_done）
#   on_cast     施法触发（充能语义）→ act_cast + not_basic：施放瞬间 subject=自己；
#               saintess_engine 普攻经 do_skill 也会 fire act_cast（info._basic）→ 装配附
#               not_basic 过滤（元素/奥术技能施放不吃普攻）。
#   on_crit     暴击命中 → crit：crit = 命中子集的独立事件（与 attack_hit/skill_hit
#               分开 fire，不重复；同一次暴击只加一次）。
#   on_taken    受击 → on_taken：承伤后 subject=受击者自己。
#   on_heal     治疗命中 → act_cast + kind=治疗（折中）：saintess_engine on_heal 事件
#               subject=被治疗者（治疗者只出现在 ctx.source），词条受益人是施法者
#               （牧师）→ 挂 on_heal 只在自疗时触发、治疗队友全漏；治疗行动上
#               「施放」与「命中」同刻发生 → 挂 act_cast+kind 过滤，全员治疗都触发。
#   battle_start 开局 → battle_start：开战一次性（subject=None 全员触发一次）。
#   buff_skill  增益技能 → act_cast + kind=增益（同 kind 过滤判据）。
# 未映射（on 无对应语义点位/需额外判据）：**无**（D3 2026-09-13 收口：combo_skill 已挂
#   skill_hit——数据无「连招技」kind/mech/名标记，取语义最近且 subject=自己 的技能命中点，
#   实装面宽于 desc 承诺、不产生假承诺；ember_brand 走 _af_ember_brand（cond_hp_lt 门槛））。

_AFFIX_RES_GAIN_ON = {
    # on 时机 → (saintess_engine 事件, 动作附加参数)
    "on_attack": ("attack_hit", {}),
    "on_skill": ("skill_hit", {}),
    "on_cast": ("act_cast", {"not_basic": True}),
    "on_crit": ("crit", {}),
    "on_taken": ("on_taken", {}),
    "on_heal": ("act_cast", {"kind": "治疗"}),
    "battle_start": ("battle_start", {}),
    "buff_skill": ("act_cast", {"kind": "增益"}),
    # combo_skill 连招技（拳师连段，combo_recover）→ skill_hit：见上方 D3 注释
    "combo_skill": ("skill_hit", {}),
}

# R4 已装配的 res+gain+on 词条（AFFIXES 表 effect 结构核对一致；其余资源型见缺口注释）
_AFFIX_RES_GAIN_IDS = (
    "war_spirit",      # 战意：普攻/技能命中怒+1（on=[on_attack,on_skill]）
    "warcry_echo",     # 战吼回响：增益技能怒+1
    "blood_bath",      # 浴血：受击怒+1
    "arcana_flux",     # 充能汲引：技能施放 element+1
    "crit_charge",     # 暴击蓄能：暴击 energy+3
    "holy_echo",       # 圣辉回响：治疗施放 faith+1（tiers 档位取 gain）
    "crit_return",     # 暴击回点：暴击 chance 概率 cp+1（tiers 档位取 chance）
    "pious_charm",     # 虔诚护符：受击 faith+1
    "rock_rest",       # 磐息：受击 chi+1
    "opening_stance",  # 起手之势：开战 chi+1
    "combo_recover",   # 连段回收：连招技命中 chi+1（D3：combo_skill → skill_hit）
)


def _translate_affix_res_gain(aid: str, actor: dict, eff: dict) -> dict:
    """通用 res+gain+on 翻译：on（str/list）→ 事件映射 → we_affix_res_gain。"""
    on = eff.get("on")
    if isinstance(on, str):
        on = [on]
    if not isinstance(on, list) or not on:
        return {}
    res = eff.get("res")
    gain = eff.get("gain")
    if not res or gain is None:
        return {}
    info = (_affix_data() or {}).get(aid) or {}
    out: dict = {}
    for t in on:
        ev, extra = _AFFIX_RES_GAIN_ON.get(t, (None, None))
        if ev is None:
            continue  # 未映射时机（数据表写了 _AFFIX_RES_GAIN_ON 之外的 on）：静默跳过
        d = {"type": "we_affix_res_gain", "key": aid, "res": res, "gain": gain,
             "label": info.get("name") or aid}
        if eff.get("chance") is not None:
            d["chance"] = eff["chance"]
        d.update(extra)
        out.setdefault(ev, []).append(d)
    return out


for _aid in _AFFIX_RES_GAIN_IDS:
    _AFFIX_TRANSLATORS[_aid] = _translate_affix_res_gain


@_register_affix("boiling_blood")
def _af_boiling_blood(aid, actor, eff):
    """沸血浇筑：怒气全满（rage 叠层满 cap，rage_full 语义）全减伤 8%。

    taken_calc 承伤乘区 cond=state_full state_key=rage（现成谓词——state_full 的
    key 参数名 = state_key，读 effects[state_key].stacks >= EFFECT_RULES cap）。
    怒气来源 = 战士怒词条装配（war_spirit/blood_bath/warcry_echo 攒层）。"""
    return {"taken_calc": [{"type": "we_taken_mult_cond", "key": aid,
                            "cond": "state_full", "state_key": "rage",
                            "mult": 1.0 - float(eff.get("dmg_reduce") or 0.08),
                            "tag": eff.get("tag") or "🛡️沸血"}]}


# ============ N9.7 收尾（m_affixtail）：regen 型 + purify ============
# regen 型（energy_tide/swift_tailwind）：effect {res, regen}（非 gain）→
# turn_start 每刻回能（saintess_engine「每刻」= 每行动，regen/meditate 同口径）；cap clamp
# 走 we_affix_res_gain → _add_stacks → _cap_of（上限词条抬 cap 同源可攒满）。
# 与 R4 gain 型同规则不按职业过滤（词条发放通用；资源归属职业由消耗端决定——
# crit_charge/war_spirit R4 已发货行为一致，无职业判据零噪音）。


@_register_affix("energy_tide")
def _af_energy_tide(aid, actor, eff):
    """精力潮汐：每刻 精力回复 +5（史诗 +5 / 传说 +10，tiers 取档）。"""
    return {"turn_start": [{"type": "we_affix_res_gain", "key": aid,
                            "res": "energy", "gain": int(eff.get("regen") or 5),
                            "label": "🌊精力潮汐"}]}


@_register_affix("swift_tailwind")
def _af_swift_tailwind(aid, actor, eff):
    """疾风余韵：刻末精力 ≥80 → 下刻 精力回复 +10（saintess_engine turn_start 判定当前
    精力 ≥80 即回，持续维持线 ≈ 旧跨刻口径；cond=energy_ge_80 → cond_key/cond_ge
    参数，动作侧静默跳过不满足）。"""
    return {"turn_start": [{"type": "we_affix_res_gain", "key": aid,
                            "res": "energy", "gain": int(eff.get("regen") or 10),
                            "cond_key": "energy", "cond_ge": 80,
                            "label": "🍃疾风余韵"}]}


@_register_affix("purify")
def _af_purify(aid, actor, eff):
    """净化：命中 15% 驱散目标 1 层增益；成功 → 敌攻 -10%（1 刻）。

    增益判定（N9_7 定稿）在动作侧 we_affix_purify：EFFECT_RULES/条目内嵌快照
    查 op mul>1|add>0 / stat_scale 正层 / 自愈回能 period（saintess_engine effects 无
    旧 mon_ 前缀概念）。purge_n/holy_weaken_pct 从 effect 取。"""
    return {"hit": [{"type": "we_affix_purify", "key": aid, "aid": aid,
                     "chance": _affix_chance_of(aid),
                     "purge_n": int(eff.get("purge") or 1),
                     "holy_weaken_pct": float(eff.get("holy_weaken") or 0.10)}]}


@_register_affix("finisher")
def _af_finisher(aid, actor, eff):
    """终结之技：终结技伤害 +tier%（v181.M-bonus 装配）。

    dmg_calc 乘区 cond=mech_any（新谓词见 battle_we_procs.we_dmg_mult_cond）：
    本击技能 mech=finisher 或显示名含「终结」（终结·割喉/处决/暗影绞杀等刺客终结技；
    毒爆 mech=poison_burst_finisher 名不含终结 → 不算——desc「终结技」限定）。
    数值权威 = AFFIXES effect.finisher_dmg（tiers 已折入：blue 0.10/purple 0.15/
    orange 0.20）。"""
    return {"dmg_calc": [{"type": "we_dmg_mult_cond", "key": aid,
                          "cond": "mech_any", "mechs": ["finisher"],
                          "names_any": ["终结"],
                          "mult": 1.0 + float(eff.get("finisher_dmg") or 0.10),
                          "tag": "🗡️终结技"}]}


@_register_affix("ember_brand")
def _af_ember_brand(aid, actor, eff):
    """残血灼薪（D3 补）：生命 <30% 时 怒气获取 +1（effect {res, gain, cond: hp_lt_30}）。

    引擎无「资源获取」事件、`player_low` 无 fire 点位（effect_triggers.py 头注）→ 按
    content 侧同款先例（class_mech `passive_low_hp_core`：以真实承伤为观测点）把「怒气来源
    事件」当观测点：命中（普攻/技能）与受击各判一次，动作侧 `cond_hp_lt` 门槛决定是否
    +gain（残血才加）。数据 `cond` 由装配层折算成动作参数（动作零词条硬编码）。
    """
    res = eff.get("res")
    gain = eff.get("gain")
    if not res or gain is None or float(gain) <= 0:
        return {}
    thr = 0.30 if str(eff.get("cond") or "") == "hp_lt_30" else 0.0
    if thr <= 0:
        return {}
    info = (_affix_data() or {}).get(aid) or {}
    d = {"type": "we_affix_res_gain", "key": aid, "res": res, "gain": gain,
         "cond_hp_lt": thr, "label": info.get("name") or aid}
    return {"hit": [dict(d)], "taken": [dict(d)]}


@_register_affix("combo_ward")
def _af_combo_ward(aid, actor, eff):
    """连段护持（D3 补）：受击时 combo_keep_chance 概率「连段不因受击回退」。

    ⚠️ 基础「受击回退」在 saintess_engine/内容侧**均无载体**（旧 battle.py `_combo_break`
    随 N10 删除未迁；class_mech `passive_lian_duan_soft` 只管「断连 gap」语义）→
    「不因受击回退」无回退可抵消 → 落地为「受击时概率回补 1 段连段」（lian_duan 叠层，
    cap 走 `_add_stacks` → 引擎 `cap_of` clamp）。chance 即 combo_keep_chance（tiers 已按
    装备品质由 `_affix_effect_final` 折入）。取舍见 overnight/d3-gap-fix.md。
    """
    ch = eff.get("combo_keep_chance")
    if ch is None or float(ch) <= 0:
        return {}
    info = (_affix_data() or {}).get(aid) or {}
    return {"taken": [{"type": "we_affix_res_gain", "key": aid, "res": "lian_duan",
                       "gain": 1, "chance": float(ch),
                       "label": info.get("name") or aid}]}


def affix_triggers_for_key(aid: str, actor: dict) -> dict:
    """单个 affix → {old_event: [效果 dict]}（未支持 key → {}）。"""
    fn = _AFFIX_TRANSLATORS.get(aid)
    if fn is None:
        return {}
    eff = _affix_effect_final(aid, actor, _AFFIX_TIER_KEY.get(aid))
    if not eff and aid not in _AFFIX_TRANSLATORS:
        return {}
    return fn(aid, actor, eff)


# ============================================================
# key → 效果声明翻译（第一批：纯动词 battle_start 起手类）
# ============================================================
# 返回 {old_event(字符串): [效果 dict]}（装配时 map_event 把旧事件展开成 saintess_engine 事件）

def _translate_shield_start(key: str, wd: dict) -> dict:
    """proc_shield battle_start 起手盾：盾值 = shield_hp_pct×maxhp / shield_pct×maxhp /
    base+per_lv×lv（sentinel 型后续批），turns 由数据给。"""
    turns = int(wd.get("turns") or 3)
    eff = {"type": "shield", "key": wd.get("shield_key") or ("we_" + key),
           "turns": turns, "on": "caster"}
    if wd.get("base") is not None or wd.get("per_lv") is not None:
        # 固定值形态（value 按 level 由装配时算不了 level 依赖——走 pct 或交给扩展动作）
        return {}  # 第一批不含该形态（sentinel/deeprock 属 taken 概率盾，后续批）
    if wd.get("shield_pct") is not None:
        eff["pct"] = float(wd["shield_pct"])
    else:
        eff["pct"] = float(wd.get("shield_hp_pct") or 0.10)
    return {"battle_start": [eff]}


def _translate_buff_start(key: str, wd: dict) -> dict:
    """proc_buff battle_start 起手 buff：spd_pct → buff 动词（spd mul 1+pct，turns 数据给）。"""
    if wd.get("spd_pct") is None:
        return {}
    eff = {"type": "apply", "key": wd.get("buff_key") or key,
           "stat": "spd", "op": "mul", "mult": 1.0 + float(wd["spd_pct"]),
           "turns": int(wd.get("turns") or 3), "on": "caster"}
    return {"battle_start": [eff]}


def _translate_shield_abyss(key: str, wd: dict) -> dict:
    """abyss_barrier：深渊屏障 = battle_start 永久最大生命加成（we_abyss 扩展动作）。"""
    eff = {"type": "we_abyss", "key": key}
    if wd.get("max_hp_pct") is not None:
        eff["max_hp_pct"] = wd["max_hp_pct"]
    if wd.get("log") is not None:
        eff["log"] = wd["log"]
    return {"battle_start": [eff]}


def _translate_regen_turn_start(key: str, wd: dict) -> dict:
    """proc_aux regen 型：每刻（turn_start）回复。guard_regen = 已损生命%；
    dawn_regen/undying_band = 最大生命%（heal 动词 missing_pct/pct，N9.4 引擎扩展）。"""
    pct = float(wd.get("pct") or 0.02)
    if key == "guard_regen":
        eff = {"type": "heal", "missing_pct": pct, "on": "caster"}
    else:
        eff = {"type": "heal", "pct": pct, "on": "caster"}
    return {"turn_start": [eff]}


def _translate_stack_hit(key: str, wd: dict) -> dict:
    """proc_stack 纯叠层型（wind_mark）：每次命中 +1 层（cap/stat_scale 由 STATE_EFFECTS
    声明，面板折算读 state；命中 = 普攻+技能双事件展开）。"""
    eff = {"type": "apply", "op": "add", "key": key, "amount": 1, "on": "caster"}
    return {"hit": [eff]}


def _translate_we(key: str, wd: dict, action: str, old_ev: str, fields: tuple) -> dict:
    """通用族扩展动作翻译：type=action + key + 指定字段透传，挂 old_ev 事件。"""
    eff = {"type": action, "key": key}
    for f in fields:
        if wd.get(f) is not None:
            eff[f] = wd[f]
    return {old_ev: [eff]}


def _translate_dot_hit(key: str, wd: dict) -> dict:
    """proc_dot 命中挂 DOT：族扩展动作 we_dot（chance 概率 + 挂 state dot 层）。
    smith/rong/blood = hit 双事件；ember_burn = skill_hit。"""
    ev = "skill_hit" if key == "ember_burn" else "hit"
    eff = {"type": "we_dot", "key": key}
    for f in ("dot_key", "chance", "turns"):
        if wd.get(f) is not None:
            eff[f] = wd[f]
    return {ev: [eff]}


def _translate_reflect_taken(key: str, wd: dict) -> dict:
    """proc_reflect 受击反弹：族扩展动作 we_reflect（on_taken；攻击者=caster 反弹对象）。
    参数全带（chance/reflect_pct/heal_pct/heal_down/max_hp_pct/burn_stack——缺省执行器兜底无此段）。"""
    eff = {"type": "we_reflect", "key": key}
    for f in ("chance", "reflect_pct", "heal_pct", "heal_down", "max_hp_pct", "burn_stack"):
        if wd.get(f) is not None:
            eff[f] = wd[f]
    return {"taken": [eff]}


def _translate_buff_hit_self(key: str, wd: dict, old_ev: str) -> dict:
    """通用：事件后自身 buff（属性提升——buff 动词 stat/op/mult 快照）。"""
    stat = wd.get("stat") or "spd"
    op = wd.get("op") or "mul"
    mult = float(wd.get("spd_pct") or 0)
    if mult <= 0:
        return {}
    eff = {"type": "apply", "key": wd.get("buff_key") or key, "stat": stat, "op": op,
           "mult": 1.0 + mult, "turns": int(wd.get("turns") or 3), "on": "caster"}
    return {old_ev: [eff]}


def _translate_next_atk_mark(key: str, wd: dict) -> dict:
    """proc_next_atk_mark：命中后给自身挂「下次出手强化」buff（引擎 N7.3 hit 子键
    天然支持：出手时消费 dmg_mult）。mountain/oath = skill_hit；spark = skill_cast。
    （dusk 的 stealth 段后续扩展动作补；trinity 走 _translate_trinity 含附雷段）"""
    old_ev = "skill_cast" if key == "novice_spark_followup" else "skill_hit"
    pct = float(wd.get("atk_pct") or 0)
    if pct <= 0:
        return {}
    eff = {"type": "apply", "key": wd.get("mark_key") or ("we_" + key),
           "turns": 999, "hit": {"dmg_mult": 1.0 + pct}, "on": "caster"}
    return {old_ev: [eff]}


def _translate_trinity(key: str, wd: dict) -> dict:
    """proc_next_atk_mark trinity_rhythm（奔雷大剑）：技能后下一次出手 +30% 伤害
    **并附带 atk×thunder_pct 雷属性伤害**（N9.8 补 thunder 段）。

    - atk_pct 段：buff hit 子键 dmg_mult（引擎 N7.3 出手消费，同族通用）；
    - thunder 段：buff hit 子键 bonus_atk_pct —— 引擎 _consume_hit_buffs 返回
      附伤参数 → actions 主伤害落地后按 atk×pct 追一段独立伤害（走 landing
      统一收口）。数值全读 wd 表（零硬编码）；无 thunder_pct → 纯 atk 段
      （读表零默认值：缺字段 = 无此行为）。
    """
    pct = float(wd.get("atk_pct") or 0)
    if pct <= 0:
        return {}
    hit = {"dmg_mult": 1.0 + pct}
    tp = float(wd.get("thunder_pct") or 0)
    if tp > 0:
        hit["bonus_atk_pct"] = tp
        hit["bonus_tag"] = wd.get("bonus_tag") or "⚡"
    eff = {"type": "apply", "key": wd.get("mark_key") or ("we_" + key),
           "turns": 999, "hit": hit, "on": "caster"}
    return {"skill_hit": [eff]}


def _translate_retort_mark(key: str, wd: dict) -> dict:
    """proc_retort_mark：受击后自身挂「下次出手强化」buff（反击势能，同 hit 子键消费）。
    gargoyle/titan/ranger 共用 we_retort 键（同源刷新，各取 next_atk_pct）。"""
    pct = float(wd.get("next_atk_pct") or 0)
    if pct <= 0:
        return {}
    eff = {"type": "apply", "key": wd.get("mark_key") or "we_retort",
           "turns": 999, "hit": {"dmg_mult": 1.0 + pct}, "on": "caster"}
    return {"taken": [eff]}


def _translate_shield_taken_cd(key: str, wd: dict) -> dict:
    """proc_shield taken 概率盾（sentinel/deeprock）：族扩展动作 we_shield_taken
    （chance + cd 判定 → 上盾）。base+per_lv×lv / shield_pct×maxhp。"""
    eff = {"type": "we_shield_taken", "key": key}
    for f in ("chance", "base", "per_lv", "shield_pct", "turns", "cd", "shield_key", "cd_key"):
        if wd.get(f) is not None:
            eff[f] = wd[f]
    return {"taken": [eff]}


def _translate_shield_cond(key: str, wd: dict, old_ev: str) -> dict:
    """proc_shield 条件型：族扩展动作 we_shield_cond。
    threshold 低保盾（bedrock/gargoyle/firmament）挂 on_taken（受击后自查 hp 阈值）；
    heal 溢出（echo_bless/atonement）挂 heal；crit 盾（endless_radiance）挂 crit。"""
    eff = {"type": "we_shield_cond", "key": key}
    for f in ("threshold", "shield_hp_pct", "heal_pct", "turns", "per_battle",
              "overflow_pct", "cap_hp_pct", "shield_key", "used_key", "active_key",
              "cd_key", "cd", "shield_turns"):
        if wd.get(f) is not None:
            eff[f] = wd[f]
    return {old_ev: [eff]}


def _translate_control(key: str, wd: dict, old_ev: str) -> dict:
    """proc_control 敌方控制：we_control 扩展动作。字段全带（mode/chance/cd/限次/
    slow/freeze 参数——执行器按 mode 分派，缺省无此段）。"""
    eff = {"type": "we_control", "key": key}
    for f in ("mode", "chance", "slow_turns", "slow_pct", "freeze_turns", "heal_down",
              "cd", "cd_key", "used_key", "max_per_battle", "threshold", "turns", "source", "log"):
        if wd.get(f) is not None:
            eff[f] = wd[f]
    return {old_ev: [eff]}


def _translate_death_dance(key: str, wd: dict) -> dict:
    """proc_special death_dance 缓伤池：on_taken 收池（dmg×pool_pct）+ turn_start 结算
    （pay = pool×pay_pct 扣血）。池存 actor.ext.we_proc[pool_key]（扩展动作自管）。
    battle_start 惰性建键由执行器 .get 天然缺省 0，无需事件。"""
    pool_key = wd.get("pool_key") or "we_death_pool"
    return {
        "on_taken": [{"type": "we_death_pool_add", "key": key, "pool_key": pool_key,
                      "pool_pct": float(wd.get("pool_pct") or 0.35)}],
        "turn_start": [{"type": "we_death_pool_pay", "key": key, "pool_key": pool_key,
                        "pay_pct": float(wd.get("pay_pct") or 0.10)}],
    }


def _translate_act_done_slow(key: str, wd: dict) -> dict:
    """proc_control spd_down_stack（randuin/ice_vein）：敌对 actor 行动完成 → 给它
    叠减速层。挂 enemy_act → act_done（全员广播）；敌我判断在扩展动作
    we_act_done_slow 内（hostile_sides 查 owner vs acted）。
    ⚠️ state key 用效果 key（randuin_weary/ice_vein）而非数据表 stack_key
    （_randuin_stack/_ice_vein_stack——那是旧 e_buffs 内部键）——saintess_engine 的
    STATE_EFFECTS 面板折算/层 cap 以注册 key 为权威。"""
    eff = {"type": "we_act_done_slow", "key": key, "stack_key": key,
           "max_stack": wd.get("max_stack"),
           "spd_down_pct": wd.get("spd_down_pct")}
    return {"enemy_act": [eff]}


def _translate_extra_dmg(key: str, wd: dict) -> dict:
    """proc_extra_dmg 命中追击：we_extra_dmg 扩展动作。事件 = 数据表注册事件
    （skill_hit 4：afterglow/spellblade/annihilation/endless_blade；其余 hit）。"""
    ev = "skill_hit" if key in ("afterglow_splash", "spellblade_echo",
                                "annihilation_echo", "endless_blade") else "hit"
    eff = {"type": "we_extra_dmg", "key": key}
    for f in ("mode", "chance", "atk_pct", "pene_pct", "guarantee", "count",
              "lost_hp_pct", "cap_pct", "cur_hp_pct", "heal_pct", "stack_key",
              "used_key", "log"):
        if wd.get(f) is not None:
            eff[f] = wd[f]
    return {ev: [eff]}


def _translate_dusk_blade(key: str, wd: dict) -> dict:
    """proc_next_atk_mark dusk_blade（kill）：击杀后潜行（必暴）+ 下次攻击 +30%。"""
    effs = []
    spd_pct = float(wd.get("next_atk_pct") or 0)
    if spd_pct > 0:
        effs.append({"type": "apply", "key": wd.get("mark_key") or "we_dusk",
                     "turns": 999, "hit": {"dmg_mult": 1.0 + spd_pct}, "on": "caster"})
    effs.append({"type": "apply", "key": wd.get("buff_key") or "stealth",
                 "turns": 999, "hit": {"guaranteed_crit": True}, "on": "caster"})
    return {"kill": effs}


def _translate_legend_mult(key: str, wd: dict) -> dict:
    """传说专属乘区（D3：3 个 roster `weapon_effect` 键曾「放错表」= 只在 LEGENDARY_EFFECTS）。

    形状 = 真源 affixes.py LEGENDARY_EFFECTS 条目 effect（trigger:"passive"）：
    {dmg_mult, enemy_contains|execute_threshold, tag} → dmg_calc 乘区（we_dmg_mult_cond）：
    - execute_threshold → cond=hp_target_lt（对残血目标，同 execute/twilight_execute）；
    - enemy_contains    → cond=name_contains + keywords（对龙/深渊系，同 dragon_aw）。
    读表零默认值：dmg_mult 缺失 = 无此行为。
    """
    mult = float(wd.get("dmg_mult") or 0)
    if mult <= 0:
        return {}
    eff = {"type": "we_dmg_mult_cond", "key": key, "mult": mult,
           "tag": wd.get("tag") or ""}
    if wd.get("execute_threshold") is not None:
        eff["cond"] = "hp_target_lt"
        eff["threshold"] = float(wd["execute_threshold"])
    elif wd.get("enemy_contains"):
        eff["cond"] = "name_contains"
        eff["keywords"] = list(wd["enemy_contains"])
    else:
        return {}
    return {"dmg_calc": [eff]}


def _translate_first_turn_dodge(key: str, wd: dict) -> dict:
    """proc_special novice_first_turn_dodge 首刻闪避（D3 补）：battle_start 给自身
    dodge +dodge_pct（面板快照 op=add 浮点加，`apply` 动词——同族 novice_first_turn_guard
    的「首刻后失效」口径：turns=1 刻，过期由引擎 effects expire 自动清理）。"""
    pct = float(wd.get("dodge_pct") or 0)
    if pct <= 0:
        return {}
    return {"battle_start": [{"type": "apply",
                              "key": wd.get("mark_key") or ("we_" + key),
                              "stat": "dodge", "op": "add", "mult": pct,
                              "turns": int(wd.get("turns") or 1), "on": "caster"}]}


def _cond_mult(old_ev: str, cond: str, threshold: float, mult: float, tag: str = "") -> dict:
    """条件乘区翻译（dmg_calc/taken_calc → we_*_mult_cond 扩展动作）。"""
    return {old_ev: [{"type": "we_dmg_mult_cond", "cond": cond, "threshold": threshold,
                      "mult": mult, "tag": tag}]}


def _star_slayer(wd: dict) -> dict:
    """弑星：目标 hp>70% ×1.15（dmg_calc）+ 暴伤 +30% 面板（battle_start buff）。"""
    out = {"dmg_calc": [{"type": "we_dmg_mult_cond", "cond": "hp_target_gt",
                         "threshold": float(wd.get("threshold") or 0.70),
                         "mult": float(wd.get("dmg_mult") or 1.15), "tag": "⭐弑星"}]}
    cd = float(wd.get("crit_dmg") or 0)
    if cd > 0:
        out["battle_start"] = [{"type": "apply", "key": "we_star_slayer_cd",
                                "stat": "crit_dmg", "op": "add", "mult": cd,
                                "turns": 999, "on": "caster"}]
    return out


def _arcane_firmament(wd: dict) -> dict:
    """奥术苍穹：魔攻 +15% 面板（battle_start buff）+ 魔法技 ×1.1（dmg_calc kind_magic）。"""
    return {
        "battle_start": [{"type": "apply", "key": "we_arcane_matk", "stat": "matk",
                          "op": "mul", "mult": 1.0 + float(wd.get("matk_pct") or 0.15),
                          "turns": 999, "on": "caster"}],
        "dmg_calc": [{"type": "we_dmg_mult_cond", "cond": "kind_magic",
                      "mult": 1.0 + float(wd.get("skill_dmg_pct") or 0.10), "tag": "✨奥术苍穹"}],
    }


def _stack_pair(key: str, wd: dict, prod_old_ev: str) -> dict:
    """叠层放大器翻译：生产事件 → we_stack_prod；dmg_calc → we_amp_consume。"""
    return {
        prod_old_ev: [{"type": "we_stack_prod", "key": key,
                       "stack_key": wd.get("stack_key") or key,
                       "need": wd.get("need"), "charge_key": wd.get("charge_key"),
                       "charge_pct": wd.get("charge_pct")}],
        "dmg_calc": [{"type": "we_amp_consume", "key": key,
                      "stack_key": wd.get("stack_key") or key,
                      "per_pct": wd.get("per_pct") or wd.get("dmg_pct_per"),
                      "charge_key": wd.get("charge_key")}],
    }


# 第一批支持 key 清单（key → 翻译器）
# proc_heal amp 被动常驻 4 key（不走 triggers——装配 state heal_amp_pct）
_HEAL_AMP_KEYS = ("vital_band", "holy_radiance_mail", "echo_band", "novice_regen_heal")

_START_TRANSLATORS = {
    # proc_shield battle_start 起手盾
    "starlight_bulwark": _translate_shield_start,
    "eclipse_crown": _translate_shield_start,
    # proc_buff battle_start 起手速度 buff
    "gale_step": _translate_buff_start,
    "swift_boots": _translate_buff_start,
    "deadman_stride": _translate_buff_start,
    "temple_stride": _translate_buff_start,
    "void_stride": _translate_buff_start,
    # 深渊屏障（单独形态：max_hp_pct 起手盾）
    "abyss_barrier": _translate_shield_abyss,
    # proc_aux regen 型（每刻回复）
    "guard_regen": _translate_regen_turn_start,
    "dawn_regen": _translate_regen_turn_start,
    "undying_band": _translate_regen_turn_start,
    # proc_stack 纯叠层型（命中叠层 + state_effects 面板折算）
    "wind_mark": _translate_stack_hit,
    # proc_dot 命中挂 DOT（族扩展动作）
    "smith_blaze_wound": _translate_dot_hit,
    "rong_lu_yu_wen": _translate_dot_hit,
    "ember_burn": _translate_dot_hit,
    "blood_trace": _translate_dot_hit,
    # proc_reflect 受击反弹（族扩展动作）
    "thorn_armor": _translate_reflect_taken,
    "retribution_ring": _translate_reflect_taken,
    "iron_echo": _translate_reflect_taken,
    "dragon_spine_mail": _translate_reflect_taken,
    "ember_bulwark": _translate_reflect_taken,
    # proc_buff hit 型（自身速度 buff）
    "novice_wind_spd": lambda k, wd: _translate_buff_hit_self(k, wd, "hit"),
    # proc_next_atk_mark（下次出手强化 buff，引擎 hit 子键消费）
    "mountain_break": _translate_next_atk_mark,
    "oath_blade": _translate_next_atk_mark,
    "novice_spark_followup": _translate_next_atk_mark,
    "dusk_blade": _translate_dusk_blade,
    "trinity_rhythm": _translate_trinity,   # atk_pct + thunder_pct 双段（N9.8 收口）
    # proc_retort_mark（受击反击势能）
    "gargoyle_retort": _translate_retort_mark,
    "titan_retort": _translate_retort_mark,
    "ranger_retort": _translate_retort_mark,
    "guardian_will": lambda k, wd: _translate_we(k, wd, "we_guardian_will", "taken",
                                                 ("chance", "weaken", "debuff_key", "turns")),
    # proc_shield taken 概率盾（族扩展动作带 cd）
    "sentinel_aegis": _translate_shield_taken_cd,
    "deeprock_aegis": _translate_shield_taken_cd,
    # proc_shield 条件盾（threshold 低保 / heal 溢出 / crit）
    "bedrock_crown": lambda k, wd: _translate_shield_cond(k, wd, "taken"),
    "firmament_crown": lambda k, wd: _translate_shield_cond(k, wd, "taken"),
    "gargoyle_heart": lambda k, wd: _translate_shield_cond(k, wd, "taken"),
    "echo_bless": lambda k, wd: _translate_shield_cond(k, wd, "heal"),
    "atonement_shield": lambda k, wd: _translate_shield_cond(k, wd, "heal"),
    "endless_radiance": lambda k, wd: _translate_shield_cond(k, wd, "crit"),
    # proc_extra_dmg 命中追击（族扩展动作多 mode）
    "afterglow_splash": _translate_extra_dmg,
    "spellblade_echo": _translate_extra_dmg,
    "annihilation_echo": _translate_extra_dmg,
    "wind_split": _translate_extra_dmg,
    "phantom_barrage": _translate_extra_dmg,
    "endless_blade": _translate_extra_dmg,
    "hunter_open": _translate_extra_dmg,
    "siren_fang": _translate_extra_dmg,
    "star_pierce": _translate_extra_dmg,
    "soul_eater": _translate_extra_dmg,
    "novice_lifesteal": _translate_extra_dmg,
    # proc_control 敌方控制（randuin_weary/ice_vein 依赖 enemy_act 事件暂缺）
    "frost_ring": lambda k, wd: _translate_control(k, wd, "hit"),
    "holy_judgment_field": lambda k, wd: _translate_control(k, wd, "hit"),
    "everfrost_domain": lambda k, wd: _translate_control(k, wd, "skill_hit"),
    "everfrost_scepter": lambda k, wd: _translate_control(k, wd, "skill_hit"),
    "frost_crown": lambda k, wd: _translate_control(k, wd, "taken"),
    "holy_word_bind": lambda k, wd: _translate_control(k, wd, "heal"),
    "time_freeze": lambda k, wd: _translate_control(k, wd, "taken"),
    # proc_aux novice_dawn_mana（施法首次回蓝——we_mana_once 扩展动作）
    "novice_dawn_mana": lambda k, wd: _translate_we(k, wd, "we_mana_once", "skill_cast",
                                                    ("mp", "log")),
    # proc_dr_revive undying_will（battle_start 挂濒死保护层——landing 致死保底）
    "undying_will": lambda k, wd: {
        "battle_start": [{"type": "apply", "op": "add", "key": "death_guard", "amount": 1,
                          "on": "caster", "log": wd.get("log")}],
    },
    # proc_passive_mult 条件乘区（dmg_calc/taken_calc 通道）
    "twilight_execute": lambda k, wd: _cond_mult("dmg_calc", "hp_target_lt",
                                                 float(wd.get("threshold") or 0.40),
                                                 float(wd.get("dmg_mult") or 1.25), "🌆暮光处决"),
    "star_slayer_edge": lambda k, wd: _star_slayer(wd),
    "arcane_firmament": lambda k, wd: _arcane_firmament(wd),
    # proc_dr_revive death_dance_armor（受击减伤 8%——taken_calc 通道；复活段缺口）
    "death_dance_armor": lambda k, wd: {
        "taken_calc": [{"type": "we_taken_mult_cond", "key": k, "cond": "always",
                        "mult": 1.0 - float(wd.get("taken_reduce_pct") or 0.08)}],
    },
    # proc_special 首刻守御（taken_calc first_turn 一次）
    "novice_first_turn_guard": lambda k, wd: {
        "taken_calc": [{"type": "we_taken_mult_cond", "key": k, "cond": "first_turn",
                        "mult": 1.0 - float(wd.get("reduce_pct") or 0.10),
                        "used_key": wd.get("mark_key") or "novice_guard_used"}],
    },
    # proc_special 首刻闪避（D3：battle_start apply dodge +pct，1 刻后失效）
    "novice_first_turn_dodge": _translate_first_turn_dodge,
    # D3：3 个 roster `weapon_effect` 键（数据原只在 LEGENDARY_EFFECTS = 放错表）——
    # 数据已抄进 WEAPON_EFFECT_DATA（weapon_effect_data.py 尾），乘区翻译器共用
    "divine_execution": _translate_legend_mult,
    "dragon_annihilation": _translate_legend_mult,
    "star_destruction": _translate_legend_mult,
    # proc_stack 叠层放大器（生产事件 + dmg_calc 消费）
    "rune_amp": lambda k, wd: _stack_pair(k, wd, "skill_cast"),
    "sage_amp": lambda k, wd: _stack_pair(k, wd, "skill_cast"),
    "eternal_codex": lambda k, wd: _stack_pair(k, wd, "skill_cast"),
    "time_staff": lambda k, wd: _stack_pair(k, wd, "turn_start"),
    "thunder_weave": lambda k, wd: _stack_pair(k, wd, "hit"),
    # proc_control 敌方控制（randuin_weary/ice_vein = act_done 叠减速层）
    "randuin_weary": _translate_act_done_slow,
    "ice_vein": _translate_act_done_slow,
    # proc_special death_dance 缓伤池（受击收池 + 每刻结算）
    "death_dance": _translate_death_dance,
    # proc_stack crit 叠层（novice_hunt_combo：暴击 → 连击率叠层，cap/per_stack
    # 数据权威——novice_combo 无 STATE_EFFECTS 行，we_combo_stack 读 max_stack）
    "novice_hunt_combo": lambda k, wd: {
        "crit": [{"type": "we_combo_stack", "key": k,
                  "stack_key": wd.get("stack_key") or k,
                  "max_stack": wd.get("max_stack"),
                  "per_stack": wd.get("per_stack")}],
    },
    # proc_passive_mult combo_end（连击终点：本刻连段≥combo_need 且暴击 → 本次
    # 暴伤乘区。saintess_engine 无旧 passive 点位 → 挂 dmg_calc（ctx.is_crit = 本击被动
    # 判定结果，we_combo_end 内判连段条件）；combo_key 缺省 lian_duan 连段资源）
    "combo_end": lambda k, wd: {
        "dmg_calc": [{"type": "we_combo_end", "key": k,
                      "combo_need": wd.get("combo_need"),
                      "crit_dmg": wd.get("crit_dmg"),
                      "mark_key": wd.get("mark_key"),
                      "combo_key": wd.get("combo_key")}],
    },
}


def triggers_for_key(key: str, actor: Optional[dict] = None) -> dict:
    """单个 weapon key → {old_event: [效果 dict]}（未支持 key → {}）。"""
    if key not in _START_TRANSLATORS:
        return {}
    wd = _we_config(key, actor)
    fn = _START_TRANSLATORS[key]
    return fn(key, wd)


# ============================================================
# 传说专属特效装配条目（D3 2026-09-13 补：item["legendary"] → id 流）
# ============================================================
# 缺口（定性见 overnight/d3-gap-triage.md）：93 条 LEGENDARY_EFFECTS 里 50 条非 stat 条目
# 全无装配入口——装备行 `item["legendary"]` 在开战构造层**一次都没被读**（本文件旧版
# grep 'legendary' = 0 行），只有**生成期** drops._merge_legendary_stats 收 stat 型 →
# 60/93 条「展示有（详情页印 desc 承诺）、实战不生效」。本段把 legendary id 并进 id 流。
#
# 装配口径（四条）：
# 1. **只对 `trigger != "stat"` 生效**：stat 型条目已在生成期折算进 `item.stats`
#    （game/core/drops.py:27-42 `_merge_legendary_stats`），装配层再读 = 同一数值算两遍。
# 2. **不重复并入**：`item["legendary"]` 与 `item["weapon_effect"]`/`item["affixes"]` 可能
#    填同一个 id（名册 145 件传说里 15 件两字段同值）→ id 已在本 actor 的 weapon_effect /
#    affix 流里出现过就跳过（否则同一条特效被装两遍）。
# 3. **无翻译器不静默**：进 `_UNSUPPORTED_LEGENDARY` 去重清单 + `logging.warning`（**只登记
#    不改行为**；门禁/自检读该清单，卡「有没有新的死条目」）。
# 4. **翻译器全部复用已有的**（本批不新增动作/机制）：传说条目的 `effect` 形状与
#    weapon_effect_data 同族，直接喂已有翻译器，零新动作、零数值默认值。
#
# 数值权威 = affixes.LEGENDARY_EFFECTS[id]（形状 = {name, kind, trigger, effect, desc}
# [+ 顶层 chance]，与 AFFIXES 条目一致）。名册 `legendary` 字段另有 29 行填的不是传说专属
# id（15 件 weapon_effect 同值回显、4 件词条键、10 件两表皆无）→ 回显件由 step 0 去重、
# 词条键走词条 id 流（step 3），两流都认不出才登记「未实装」。

_LEGENDARY_TABLE = None


def _legendary_data() -> dict:
    """LEGENDARY_EFFECTS 表（数值权威，惰性读）。"""
    global _LEGENDARY_TABLE
    if _LEGENDARY_TABLE is None:
        try:
            from ..apply import _read_json
            _LEGENDARY_TABLE = _read_json("legendary_effects.json", {})
        except Exception:
            _LEGENDARY_TABLE = {}
    return _LEGENDARY_TABLE


def equipped_legendary_ids(actor: dict) -> list:
    """actor 已装备的全部传说专属 id（各槽位 item["legendary"]，去重保序）。"""
    out = []
    for item in (actor.get("equipment") or {}).values():
        if not isinstance(item, dict):
            continue
        lid = item.get("legendary")
        if lid and lid not in out:
            out.append(lid)
    return out


def _note_unsupported_legendary(lid: str, trigger: str) -> None:
    """未实装传说条目登记 + 告警（**只登记不改行为**；去重——装配器每场战斗都跑）。"""
    if lid in _UNSUPPORTED_LEGENDARY:
        return
    _UNSUPPORTED_LEGENDARY.append(lid)
    logging.getLogger(__name__).warning(
        "传说专属特效 %r（trigger=%s）在装配层没有翻译器（详情页有承诺、实战不生效）",
        lid, trigger)


# 传说专属 id → 翻译器（**全部复用已有翻译器**；签名同武器翻译器 (key, cfg)，cfg =
# LEGENDARY_EFFECTS[id]["effect"] + 顶层 chance 注入。每条注释 = 数据 desc 逐字核对）
_LEGENDARY_TRANSLATORS = {
    # —— passive 条件乘区（复用 _translate_legend_mult：残血处决 / 对某系敌人）——
    "jack_hook": _translate_legend_mult,            # 处决狂潮：对生命 <30% 目标额外＋80%
    "ancient_king": _translate_legend_mult,         # 王权处决：对生命 <30% 目标＋35%
    "executioner": _translate_legend_mult,          # 处刑者：对生命 <30% 目标＋40%
    "divine_execution": _translate_legend_mult,     # 神罚处决：对生命 <30% 目标额外＋60%
    "dawn_light": _translate_legend_mult,           # 黎明破晓：对深渊系敌人＋50%
    "giant_slayer": _translate_legend_mult,         # 巨人屠戮：对巨人系敌人＋25%
    "star_destruction": _translate_legend_mult,     # 星陨湮灭：对深渊系敌人＋30%
    "dragon_annihilation": _translate_legend_mult,  # 灭龙：对龙系敌人＋25%
    # —— turn_start 每刻回血（复用 _translate_regen_turn_start；morning_dew 的 pct 是
    #    「回魔力」，语义不同 → 本批不装）——
    "dawn_crown": _translate_regen_turn_start,      # 晨曦祝福：每刻回复 2% 生命
    "life_spring": _translate_regen_turn_start,     # 生命泉涌：每刻回复 3% 生命
    "night_prayer": _translate_regen_turn_start,    # 夜祷：每刻回复 3% 生命
    # —— battle_start 起手盾（复用 _translate_shield_start）——
    "arcane_ward": _translate_shield_start,         # 奥术屏障：开局 15% 最大生命护盾 3 刻
}


def legendary_triggers_for_key(lid: str, actor: dict) -> dict:
    """单个传说专属 id → {old_event: [效果 dict]}；装不出 → {}（未实装则登记 + 告警）。"""
    # 0) 不重复并入：同 id 已由 weapon_effect / affix 入口装过（名册两字段同值 / 同 id 词条）
    if lid in equipped_weapon_keys(actor) or lid in equipped_affix_ids(actor):
        return {}
    info = (_legendary_data() or {}).get(lid)
    trigger = (info or {}).get("trigger")
    if trigger == "stat":
        return {}   # 生成期已折算进 item.stats —— 再装 = 双算
    if info:
        fn = _LEGENDARY_TRANSLATORS.get(lid)
        if fn is not None:
            cfg = dict(info.get("effect") or {})
            if info.get("chance") is not None:
                cfg.setdefault("chance", info["chance"])
            raw = fn(lid, cfg)
            if raw:
                return raw
    else:
        # 非传说专属 id（名册 legendary 字段混装的 weapon_effect / 词条键）→ 各自 id 流
        raw = triggers_for_key(lid, actor)
        if raw:
            return raw
        raw = affix_triggers_for_key(lid, actor)
        if raw:
            return raw
    _note_unsupported_legendary(lid, trigger or "unknown")
    return {}


def legendary_triggers(actor: dict) -> dict:
    """actor 全部传说专属特效 → {saintess_engine事件: [效果 dict]}（同武器/词条两流口径）。"""
    out: dict = {}
    for lid in equipped_legendary_ids(actor):
        raw = legendary_triggers_for_key(lid, actor)
        if not raw:
            continue
        for old_ev, effs in raw.items():
            for b2_ev in map_event(old_ev):
                out.setdefault(b2_ev, []).extend(list(effs))
    return out


# ============================================================
# 装配入口
# ============================================================

_EXT_LOADED = False


def install_ext_actions() -> None:
    """注册族扩展动作（形态 2）——import 时 register_action 装饰器即注册，幂等。"""
    global _EXT_LOADED
    if _EXT_LOADED:
        return
    _EXT_LOADED = True
    # 包内改写（import 层）：真源 `from .import battle_we_procs as _WEP` + `_WEP.ensure_registered()`
    # → 包内族模块 `content/mech/we_procs.py`（27 个 we_* 动作，import 即注册）。真源
    # `ensure_registered()` 自身不注册动作、只置幂等标记（见其 docstring 自述），故此处只保留
    # 「import 族模块」这一步 —— 与 D2 其余各族（class_mech/team_procs/…）同口径。
    from . import we_procs as _WEP   # noqa: F401  import 即注册（27 个 we_* 动作）


def weapon_triggers(actor: dict) -> dict:
    """actor 全部已装备武器特效 → {saintess_engine事件: [效果 dict]}。

    内部先把 key 翻译成 {old_event: [效果]}，再把 old_event 映射展开到
    saintess_engine 事件（hit → attack_hit + skill_hit 双事件注册）。
    """
    out: dict = {}
    for key in equipped_weapon_keys(actor):
        raw = triggers_for_key(key, actor)
        if not raw:
            continue  # 未支持 key：静默跳过（范围外）
        for old_ev, effs in raw.items():
            for b2_ev in map_event(old_ev):
                out.setdefault(b2_ev, []).extend(list(effs))
    return out


def affix_triggers(actor: dict) -> dict:
    """actor 全部已装备词条（事件型）→ {saintess_engine事件: [效果 dict]}。

    - stat 型词条（生成时已折算进 item.stats）不产生 triggers（面板自动含）
    - 事件型走翻译器 + 事件映射展开（hit → attack_hit + skill_hit）
    - 资源型：R4 已装事件 gain 型 10 + boiling_blood；上限型 max_bonus 走
      _apply_bonus_domains（actor.bonus cap/cost 分域容器，非事件——apply_to_actor 第
      0 步；面板外部增幅 bonus.panel 由开战仪式播种，装配不动）；
      m_affixtail 已装 regen 型 2（energy_tide/swift_tailwind turn_start 回能）+
      purify（命中驱散）；D3 已装 3 条事件型词条（combo_recover/combo_ward/ember_brand
      ——取舍见 overnight/d3-gap-fix.md）；其余 cond 修正型/职业机制词条翻译器未注册
      → 静默跳过（缺口清单见模块头注释与 affixes.py）
    """
    out: dict = {}
    for aid in equipped_affix_ids(actor):
        raw = affix_triggers_for_key(aid, actor)
        if not raw:
            continue
        for old_ev, effs in raw.items():
            for b2_ev in map_event(old_ev):
                out.setdefault(b2_ev, []).extend(list(effs))
    return out


def apply_to_actor(actor: dict) -> None:
    """把装备特效+词条装配进 actor（幂等；命令层开战前调用）：
    0. bonus 容器分域（v181.M-bonus：cap 上限词条 max_bonus → bonus.cap；
       cost 消耗修正词条 energy_blade/arcane_focus/sigil_blessing → bonus.cost；
       panel 外部增幅由开战仪式播种，此处不动）
    1. 事件型效果 → actor["triggers"]（武器特效 + 词条事件型 + 传说专属特效合并）
    2. 被动常驻型（proc_heal amp：受疗增幅）→ actor.state.heal_amp_pct（landing 折算）"""
    if not actor:
        return
    install_ext_actions()
    # 0) bonus 容器（cap/cost——先于渠道装配；覆盖写幂等，卸装后重装配回落）
    try:
        _apply_bonus_domains(actor)
    except Exception:
        pass  # 词条 bonus 装配异常不阻断其余（容错铁律）
    # 1) 事件型（武器特效 + affix 词条 + 传说专属特效）
    merged = weapon_triggers(actor)
    try:
        _afx = affix_triggers(actor)
        for ev, effs in _afx.items():
            merged.setdefault(ev, []).extend(effs)
    except Exception:
        pass  # 词条装配异常不阻断武器装配（容错）
    try:
        _leg = legendary_triggers(actor)
        for ev, effs in _leg.items():
            merged.setdefault(ev, []).extend(effs)
    except Exception:
        pass  # 传说专属装配异常不阻断其余（容错铁律）
    tr = actor.setdefault("triggers", {})
    for ev, effs in merged.items():
        tr.setdefault(ev, []).extend(effs)
    # 2) 被动常驻：heal amp（vital_band 等 proc_heal amp 4 key）→ effects["heal_amp_pct"] 条目
    amp = 0.0
    for key in equipped_weapon_keys(actor):
        wd = _we_config(key, actor)
        if (wd.get("family") == "proc_heal" and wd.get("heal_pct") is not None
                and key in _HEAL_AMP_KEYS):
            pct = float(wd.get("heal_pct") or 0)
            if pct > 0:
                amp = 1.0 - (1.0 - amp) * (1.0 - pct)  # 多件叠乘转加和
    if amp > 0:
        ef = actor.setdefault("effects", {})
        entry = ef.get("heal_amp_pct")
        if not isinstance(entry, dict):
            entry = ef["heal_amp_pct"] = {}
        cur_v = float((entry.get("value") or {}).get("amp", 0) or 0)
        entry.setdefault("value", {})["amp"] = max(cur_v, amp)
