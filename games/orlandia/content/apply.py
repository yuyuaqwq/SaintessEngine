# -*- coding: utf-8 -*-
"""《奥兰迪亚·余烬纪年》包装配入口（P4 机制移植切片）—— 引擎认的唯一回调面。

引擎侧的包契约只有两个函数（`docs/engine-wiki/reference/package-format.md` §七）：

    install_engine()            全局一次、幂等：挂 hook + 规则表 + 注册动作（import 即注册）
    apply_game_content(actor)   单个 actor、幂等：包内声明 → actor["triggers"]

方向只有一个：**内容 → 引擎**（引擎不 import 本包，只在需要时问 `config` 要 hook）。

切片范围（设计稿 `overnight/design-p4-mechanics-port.md` §三 D1）
--------------------------------------------------------------
本文件现在做 **① 引擎配置 + ② 装备装配 + ③/④/⑤/⑤b 机制装配**（骨架抄游戏仓
`game/content_rules/apply.py:22-42` 的同一入口，①→⑥ 一步不少）。仅剩 **⑥ 食物效果**
待搬（它依赖 `FOOD_EFFECT_PARAMS`，且"谁吃料理"本身是宿主事件，第二波再议）：

| 省略的步 | 游戏仓原位置 | 为什么切片不做 |
|---|---|---|
| ② 装备/词条/武器特效 → triggers + `bonus.{panel,cap,cost}` | `services/battle_equip_proc.py:1133 apply_to_actor` | ✅ **已搬**（D2 `equip` 批，逐字 1222 行 → `content/mech/equip.py`） |
| ④ 挂敌身条 | `services/battle_bar_procs.py:203` | 需要 `BAR_INJECT_FIELDS` + `bar_gain` 族动作（D2 `bar_procs` 批） |
| ⑤ 技能条件乘区 | `services/battle_cond_procs.py:156` | 需要 `skill_cond_mult_act`（D2 `cond_procs` 批） |
| ⑤b 元素机制 | `services/battle_element_procs.py:296` | 需要 `REACTION_TABLE` + 元素族动作（D2） |
| ⑥ 食物效果 | `services/battle_food_proc.py:210` | 需要 `FOOD_EFFECT_PARAMS`（宿主事件更合适，第二波再议） |
| ③ 内 mech_cash 兑现段 / faith 负载档位 / melody 旋律 | `services/class_mech_proc.py:2374-2441 / 2331-2341 / 2345-2356` | 需要 `mech_cash_*` / `class_faith_*` / `class_melody_act` 等动作（D2 `class_mech` 批，39 个动作） |

已搬的 ③ 内部片段（逐字搬，见各函数 docstring 的原行号）：
`start_full` 开局满额资源 → `channels` 资源渠道 → `per_core` 每核减伤 → `PASSIVE_PROC` 被动装配。

幂等铁律（**不可谈判**，分析报告 §二 + §五-4）
--------------------------------------------
`apply_game_content` 的幂等标记键**必须**沿用 `_content_applied`：actor 会连标记一起落进
战斗存档 / PVP 状态（引擎 `serialize._STRIP_KEYS` 只剥 `_skill_index`），换键名 → 旧档 actor
判断失效 → **二次装配 → triggers 翻倍**（游戏仓实测过 `battle_equip_proc` 的
`tr[ev].extend(effs)` 非幂等：装配两次 actor 序列化 1828 → 2531）。要换名得先做存档迁移 +
引擎侧 `strip_keys` 能力（分析报告 G9），本切片不做。

数据来源（包内，非游戏仓；包是自包含的）
------------------------------------------
    content/data/classes.json   职业面板 base/growth + basic_skill（切片面板公式用）
    content/data/skills.json    305 条技能（`passive` dict 是被动装配的数值来源）
    content/data/monsters.json  330 条怪技能 ms_*（怪物技能查询）
    content/data/races.json     6 条种族天赋（D3 面板批次）
    content/data/sets.json      92 条套装（D3 面板批次）
    content/data/enhance_table.json  10 行强化乘区（D3 面板批次）
    content/rules/panel_rules.json   7 组面板公式常量（D3 面板批次）
    content/tables.py           上面这些域的唯一读表口（面板门面，含 int 键还原）
    content/panel.py            职业面板**完整版**（逐字搬自游戏仓 `game/content_rules/panel.py`）
    content/rules/effect_rules.json  85 条效果规则（`config.load_game_rules` 消费）
    content/mech/params.py      切片参数表 + 声明表取值（hook 供体）
    content/mech/actions.py     3 个战斗内动词（import 即注册）
"""
from __future__ import annotations

import json
import os

from saintess_engine import config

# ★ import 即注册：每个族的模块顶层都有 @register_action，import 时写进引擎 ACTION_HANDLERS。
#   少 import 一个族 = 那一族的动作在 fire() 里**静默跳过**（引擎对未注册动作不报错），
#   所以这里**必须列全**（D2 七族 + D1 切片那 3 个）。缺哪个用
#   `overnight/p4_d2_audit.py` 一跑就知道（它做集合同源断言 + 注册断言）。
from .mech import bar_procs as _bar_procs        # 敌身条（4）
from .mech import class_mech as _class_mech      # 职业机制兑现（39）
from .mech import cond_procs as _cond_procs      # 技能条件乘区（1）
from .mech import element_procs as _element_procs  # 元素反应/克制/流转（4）
from .mech import equip as _equip                # 装备/词条/武器特效 → triggers + bonus 分域
from .mech import params as P
from .mech import food_proc as _food_proc       # 食物效果装配（B8 端口，真源 game/services/battle_food_proc.py）
from .mech import team_procs as _team_procs      # 团队/面幅（20）
from .mech import we_procs as _we_procs          # 武器/词条特效（27）
from .mech import worldboss as _worldboss        # 世界 Boss GM 增伤（1）
from . import panel as _panel                    # 职业面板**完整版**（D3 面板批次；引擎 panel_fn 的实现）
from . import bridge as _bridge                  # 开战构造半边（D3 bridge 批；宿主构造 actor 用）
from . import skills as _skills                  # 技能查询链 + SKILL_UP（D3 skills 批；引擎 3 个 hook 的实现）

_HERE = os.path.dirname(os.path.abspath(__file__))     # <pkg>/content
_DATA_DIR = os.path.join(_HERE, "data")

# 幂等标记键（沿用游戏仓 `game/content_rules/apply.py:81 _MARK`，见模块 docstring 铁律）
_MARK = "_content_applied"

_MOUNTED = False

# 最近一次装配的失败步（排障用；不写 actor、不进存档）——游戏仓 apply.py:84 LAST_ERRORS 同款
LAST_ERRORS: list = []
_MAX_ERRORS = 16




# ============================================================
# 包内数据（活读 JSON 文件，不 import 数据模块）
# ============================================================

def _read_json(name: str, default):
    """读 content/data/<name>（缺文件/坏 JSON → default，不抛）。"""
    path = os.path.join(_DATA_DIR, name)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                        # noqa: BLE001
        return default


_CLASSES = _read_json("classes.json", {})
_MONSTERS = _read_json("monsters.json", {})
# ★ 技能表不再由本文件读：真源 = 包内 `content/skills.py`（D3 skills 批逐字搬入游戏仓
# `game/content_rules/skills.py` + `game/data/skill_up.py`）。切片期那份 `_SkillTable` /
# `_SKILLS_BY_NAME` 已删（第二份同义实现 = 双源）。


# ============================================================
# 引擎配置装配（install_engine）
# ============================================================

def _lazy_mount() -> None:
    """引擎首次读未装配 hook 时的自举（内容 → 引擎方向；引擎只持回调）。"""
    install_engine()


def install_engine() -> None:
    """把本包配置挂进引擎（幂等）。

    ⚠️ 两张规则表走 **`config.load_game_rules(P)`**（P = `content/mech/params.py`，带
    `EFFECT_RULES` / `EFFECT_ACTIONS` 两个属性）——**不要**写
    `config.mount(effect_rules=…)`：`mount` 只认 `config._HOOKS` 里那 13 个名字，
    表名不在名单里 → **静默丢弃**（分析报告 §1.3 实测复现：`get_effect_rules()` 仍是空表，
    且不报错）。脚手架模板踩的正是这个坑（G2）。
    """
    global _MOUNTED
    if _MOUNTED:
        return
    from saintess_engine import formulas as _formulas

    config.register_hook_provider(_lazy_mount)
    config.mount(
        formulas=_formulas,                    # 引擎自带纯公式模块（引擎侧，非内容）
        kinds=P.KIND_NAMES,                    # 本游戏 kind 词表（5 值）
        # 职业面板**完整版**（D3 搬入）：装备/强化/词条/套装/属性点/种族/转职/分支/被动全在
        # `content/panel.py`（逐字搬，读表走 `content/tables.py`）。签名与引擎 `panel_fn` 一致
        # （saintess_engine/battle/stats.py:101 传 8 个位置参数），返回玩家属性 dict。
        panel_fn=_panel.player_final_stats,
        skill_lookup=_skills,                  # 模块对象即可（引擎按属性取 .skill_info / .skill_by_key）
        monster_skill_fn=monster_skill,        # 怪物技能表（包内 monsters.json）
        basic_skill_fn=basic_skill_of,         # 职业普攻配置（包内 classes.json）
        basic_fallback=P.BASIC_FALLBACK,       # 普攻兜底（内容名，引擎零字面量）
        mech_cfg_fn=P.mech_cfg,                # 机制配置表（单源 = class_data.MECH_CFG 全量 15 组）
        bar_prefix_fn=P.bar_prefix,            # 挂敌身条键前缀
        formula_skeleton_fn=P.formula_skeleton,
        skill_flat_fn=P.skill_flat,
        skill_up_fn=_skills.skill_up,          # 技能成长（包内 skill_up.py 逐字搬入）
        skill_level_of_fn=_skills.skill_level_of,
    )
    # EFFECT_RULES（85 条，单源在 params.py）/ EFFECT_ACTIONS（70 名词，单源在 gameplay.py，P 再导出）
    config.load_game_rules(P)
    _MOUNTED = True


# ============================================================
# 面板（panel_fn）—— **完整版**（D3 面板批次搬入）
# ============================================================
# 实现 = 包内 `content/panel.py`（逐字搬自游戏仓 `game/content_rules/panel.py`，584 行；
# 改动面只有 6 行 import + 一段说明注释，逐字证据 = `overnight/d3_port_panel.py --check`）。
# 它覆盖：装备（强化乘区 / 词条 / 附魔 / 孔位原石 / 怪异炼成）、套装 2/3/4/5 件（含职业折扣）、
# 自由属性点、副业称号、种族天赋、转职档位、分支倾向、已学属性被动 —— 数值全部来自包内域文件
# （`content/data|rules/*.json`；读表口 = `content/tables.py`，含 int 档位键还原）。
# D1 期那个「线性段切片版」`class_panel` 已删：两份同义实现并存 = 双源（同一 actor 两个口径）。


# ============================================================
# 技能 / 怪物技能查询（skill_lookup / monster_skill_fn / basic_skill_fn）
# ============================================================

# ★ 2026-09-13 接线（D3 skills 批）：技能链真源 = 包内 `content/skills.py`（逐字搬运物）。
# 下面两个名字**必须保留为别名**（不能删）：包内 4 处族模块用
#   `from ..apply import _SKILL_LOOKUP as _PKG_SKILLS`（bar_procs:240 / class_mech:2289,2339 /
#   element_procs:299）与 `..., skill_level_of`（cond_procs:156,189）。
# 模块对象满足引擎的按属性访问（`.skill_info(class_name, key)` / `.skill_by_key(key)`）。
_SKILL_LOOKUP = _skills
skill_level_of = _skills.skill_level_of


def monster_skill(skill_key):
    """怪物技能表查询（包内 monsters.json，330 条 ms_*）。"""
    info = _MONSTERS.get(skill_key)
    return info if isinstance(info, dict) else None


def basic_skill_of(class_name):
    """职业普攻配置（包内 classes.json 的 `basic_skill`；缺 → None 回落 basic_fallback）。"""
    cls = _CLASSES.get(class_name or "")
    if not isinstance(cls, dict):
        return None
    bs = cls.get("basic_skill")
    return bs if isinstance(bs, dict) else None


# 切片期的 `skill_up`（恒空 = 无成长）与 `skill_level_of`（恒 1）已删：真源已在包内
# `content/skills.py`。`skill_up` 也保留别名（保持 `from ..apply import skill_up` 这条路可用）。
skill_up = _skills.skill_up


# ============================================================
# 内容装配（apply_game_content）—— 声明 → actor["triggers"]
# ============================================================

def apply_game_content(actor: dict, ctx: dict | None = None) -> dict:
    """**唯一**开战内容装配入口（幂等）。返回 actor（原对象，就地装配）。

    顺序契约 = 游戏仓 `game/content_rules/apply.py:22-42` 的 ①→⑥，**六步已全部到位**
    （B8 2026-09-13 补齐第⑥步食物效果；逐条见下方 `_step` 注释）。

    :param ctx: 可选上下文，与宿主入口同形：``aids``（吃下的料理 aid 列表 → 第⑥步）/
                ``logs``（播报累加）。不吃料理就不传 —— 第⑥步整步跳过（与真源一致）。

    ⚠️ 装配实现全在 `content/mech/` 各机制族模块里（逐字搬运物）：
      · `class_mech.apply_class_mech` / `.apply_class_passives`（③：start_full/channels/每核减伤/
        melody/mech_cash/faith/passives，末尾自带 bar/cond 调用）
      · `equip.apply_to_actor`（②）·
        `bar_procs.apply_bar_procs`（④）· `cond_procs.apply_cond_procs`（⑤）·
        `element_procs.apply_element_procs`（⑤b）
      本文件**不再自带那一套实现**（D1 切片期的 `_assemble_*` 已删——否则同一 actor 会被装配两遍）。

    容错铁律（逐字沿用游戏仓 `game/content_rules/apply.py:131-136`）：每步独立 try/except，
    单步异常**不阻断**后续装配、不上抛（「装配异常不阻断开战」）；失败项记 `LAST_ERRORS`。
    幂等保险丝：`_content_applied`（见模块 docstring）。
    """
    if not isinstance(actor, dict):
        return actor
    if actor.get(_MARK):
        return actor          # 已装配 → 整链跳过（幂等；**不可换键名**，见模块 docstring）

    LAST_ERRORS.clear()

    def _step(name, fn, *args):
        try:
            fn(*args)
        except Exception as e:                               # noqa: BLE001 容错铁律
            if len(LAST_ERRORS) < _MAX_ERRORS:
                LAST_ERRORS.append((name, repr(e)))

    # ---- 顺序契约（对齐游戏仓 `game/content_rules/apply.py:22-42`，一步不少）----
    #   ① 引擎配置（幂等；先于一切内容装配）
    #   ② 装备/词条/武器特效 → triggers + bonus 分域（panel/cap/cost 三域；D2 equip 批已搬）
    #   ③ 职业 mech 兑现（内部顺序：start_full → channels → 每核减伤 → melody → mech_cash →
    #      faith → passives → 末尾调 apply_bar_procs / apply_cond_procs）
    #   ④ 挂敌身条（幂等；③ 已挂时此处为空操作 —— 显式保留以固定顺序契约，便于该步独立演进）
    #   ⑤ 技能条件乘区（幂等同上）
    #   ⑤b 元素机制（两轴反应/克制 + 元素流转挂印转换）
    #   ⑥ 食物效果（B8 补：`content/mech/food_proc.py` 逐字端口自 `game/services/battle_food_proc.py`；
    #      「谁吃料理」是宿主事件 → 由宿主经 ctx["aids"] 传进来，包只管效果装配）
    _step("install", install_engine)
    _step("equip", _equip.apply_to_actor, actor)
    _step("mech", _class_mech.apply_class_mech, actor)
    _step("bar", _bar_procs.apply_bar_procs, actor)
    _step("cond", _cond_procs.apply_cond_procs, actor)
    _step("element", _element_procs.apply_element_procs, actor)
    aids = (ctx or {}).get("aids")
    if aids:
        _step("food", _food_proc.install_food_fx, actor, list(aids),
              (ctx or {}).get("logs") or [])

    actor[_MARK] = True       # 幂等保险丝（装配全部走完才打；中途异常也不阻断 → 仍落标记）
    return actor


__all__ = ["install_engine", "apply_game_content"]
