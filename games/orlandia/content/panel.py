# -*- coding: utf-8 -*-
"""内容侧玩家面板公式（S5：自 `game/engine.py` 拆出，docs/ENGINE_CONTENT_SPLIT_PLAN.md §6.4）。

读《奥兰迪亚》专属表 / 职业名：
  - `C.CLASSES` / `C.CLASS_NOVICE` / `C.RACES` / `C.SETS` / `C.ENHANCE_TABLE`
  - `C.PCT_CAPS` / `C.PCT_STATS` / `C.PENE_PCT_STATS`（属性上限/百分比域）
  - `data.battle_config.TIER_GROWTH` / `BRANCH_BONUS` / `BRANCH_BONUS_BY_CLASS`
  - `data.base_growth.PLAYER_BASE_GROWTH`（成长结构声明）

判据：**凡读游戏表/职业名 → 内容侧**（引擎只注入 `config.panel_fn` 一个入口，
saintess_engine/stats.py 的 `_player_base_stats` 消费；纯怪路径不经过本模块）。

旧路径 `game.engine.*` 保留 shim re-export（S9 收口时删）。
"""

# ============================================================
# 包内版说明（D3 面板批次，2026-09-13）—— **逐字搬**，只改 import 段
# ============================================================
# 真源：游戏仓 `game/content_rules/panel.py`（584 行）。
# 生成 + 校验：`overnight/d3_port_panel.py --check`（把真源重新推导一遍、与包内那份逐字节比对）。
# 改动面（本块 + 上面那 6 行 import，**其余一字不改**）：
#   · `C` 由游戏仓聚合层换成包内门面 `content/tables.py` —— 同一个名字，正文里的 `C.XXX` 全部原样；
#   · 种族 / 套装 / 强化表 / 面板常量四个域由本批导出进包（`content/data|rules/*.json`，见 tables.py 头注）；
#   · 面板常量里的 **int 档位键**（TIER_GROWTH / BRANCH_BONUS* / ENHANCE_TABLE）由 tables.py 还原 ——
#     不还原 = `.get(1)` 恒 None = 转职/分支/强化三个乘区静默归零。
# 这是引擎 `config.panel_fn` 的**完整版**；包内 `content/apply.py:install_engine()` 挂的就是它
# （D1 期的线性段切片版 `class_panel` 已删：两份同义实现并存 = 双源）。

from saintess_engine.battle.formulas import skill_learn_cost

# ---- 包内来源（原文 6 行 import → 包内等价；本段 + 上面那段说明是**唯一**改动面）----
from . import tables as C          # 原文 `from .. import content as C`（游戏仓聚合层 → 包内门面）
from .mech.kinds import K_PASSIVE  # 原文 `from ..data.kinds import K_PASSIVE`（2026-09-13 下沉进包）
from .tables import (BRANCH_BONUS, BRANCH_BONUS_BY_CLASS, PLAYER_BASE_GROWTH, TIER_GROWTH,
                     skill_info)


# ============================================================
# 角色属性
# ============================================================
# 转职成长加成（tier 0-3 → 0/15%/30%/50%）


def player_base_stats(class_name: str, level: int, tier: int = 0, evolve_path: int = 0, race: str = None) -> dict:
    """职业基础 + 等级成长（含转职成长加成 + v25 分支属性倾向）
    阶段九：race 种族天赋（凡人之躯 growth_mult 只影响基础成长）"""
    class_name = C.resolve("classes", class_name)  # v48：中文或 ID → ID
    cls = C.CLASSES.get(class_name)
    if cls is None:
        # v105 P1(M01#6)：未知/脏 class_name 兜底——脏档/职业迁移改名后全属性链路不崩
        # （原先直接 KeyError，player_base_stats 是面板/战斗/升级的公共入口）
        cls = C.CLASSES.get(C.CLASS_NOVICE)
        if cls is None:
            raise ValueError(f"未知职业 class_name={class_name!r}，且见习兜底职业缺失")
    base = dict(cls["base"])
    growth = cls["growth"]
    mult = TIER_GROWTH.get(tier, 1.0)
    # 阶段九：种族成长倍率（08 章人类凡人之躯 -2%）
    rmult = race_stats(race).get("growth_mult", 1.0) if race else 1.0
    # P2F-3 F6：7 属性循环键集 → data/base_growth.py PLAYER_BASE_GROWTH["linear_stats"]
    #   （int(base + growth×(lv-1)×mult×rmult) 一次 int；tier/race 只作用于成长部分，不进 base）
    for k in PLAYER_BASE_GROWTH["linear_stats"]:
        base[k] = int(base[k] + growth[k] * (level - 1) * mult * rmult)
    # v25 分支属性倾向（选择转职分支后生效）
    # v156 职业×分支差异化：优先用职业表（BRANCH_BONUS_BY_CLASS），未配置职业回退通用档
    # P2F-3 F6：branch 修正模式 → PLAYER_BASE_GROWTH["branch_bonus_mode"]（mode 枚举：
    #   "mul" = int(base×v)；"add" = round(base+加值, round)（crit 百分比加法特例））。
    #   bb 键集权威仍在 BRANCH_BONUS_BY_CLASS/BRANCH_BONUS（声明表只声明"某键若出现怎么修"）。
    if evolve_path:
        bb = BRANCH_BONUS_BY_CLASS.get(class_name, BRANCH_BONUS).get(evolve_path, BRANCH_BONUS.get(evolve_path, {}))
        for k, v in bb.items():
            _bm = PLAYER_BASE_GROWTH["branch_bonus_mode"]
            mode = _bm.get(k, _bm["_default"])["mode"]
            if mode == "add":  # crit 是加法（百分比），round 3 位小数
                base[k] = round(base.get(k, 0) + v, _bm[k]["round"])
            else:  # mul：hp/mp 及其余属性 int 乘法
                base[k] = int(base[k] * v)
    base["max_hp"] = base["hp"]
    base["max_mp"] = base["mp"]
    return base


def race_stats(race: str | None) -> dict:
    """种族天赋表(08 章)。未知/空种族返回空 dict(无天赋，向后兼容)。"""
    if not race:
        return {}
    info = C.RACES.get(race) or {}
    return info.get("talents") or {}


def race_name(race: str | None) -> str:
    """种族显示名(未知返回空串，兼容旧档无 race 字段)"""
    if not race:
        return ""
    return (C.RACES.get(race) or {}).get("name", "")


def player_final_stats(class_name: str, level: int, equipment: dict, tier: int = 0, attributes: dict = None, evolve_path: int = 0, title_bonus: dict = None, race: str = None, learned_skills: list | None = None) -> dict:
    """基础属性 + 装备加成(含强化增幅)+ 自由属性点加成 + 称号加成 + 种族天赋 + 已学属性被动(v110.4 X2)
    传 learned_skills 时并入属性被动(面板)；battle.py _player_stats 不传 → 不含 passive，由战斗侧自理
    """
    st, _ = player_stats_detail(class_name, level, equipment, tier, attributes, evolve_path, title_bonus, race, learned_skills)
    return st


# ---------------- 被动技能（v64） ----------------
# 属性型被动：stat -> 修正属性；返回 dict 与 player_final_stats 相同键（max_hp/max_mp/atk/...）
# 被动 stat → (bonus_key, 操作, 需 cond is None)
# 不在表内的 stat：条件型(rage>=5/battle_start/dual_stat) 与战斗内机制(chi_gain/proc 型) 由 battle.py 结算，面板不处理
# （v109.2：dual_stat 双修精通在 battle.py:1582 按 cond 查，fire 已改 proc fire_bonus）
_PASSIVE_STAT_APPLY = {
    "mp":   ("mp_mult", "mul", True),   # 原代码特判：mp 仅在无 cond 时结算
    "spd":  ("spd_mult", "mul", False),
    "crit": ("crit_add", "add", False),
    # v106.1：冷却缩减被动支持（面板结算 + 战斗内 _set_skill_cd 消费）
    "cdr":  ("cdr_add", "add", False),
    # v106.2：穿透被动支持（战斗内乘算合成，职业特色渠道）
    "pene_phys": ("pene_phys_add", "add", False),
    "pene_magi": ("pene_magi_add", "add", False),
    # v106.3：吸血/暴击伤害/格挡被动支持（面板结算 + 战斗内消费）
    "lifesteal": ("lifesteal_add", "add", False),
    "crit_dmg": ("crit_dmg_add", "add", False),
    "block": ("block_add", "add", False),
    # v106.4：反伤/物魔免/物法吸被动支持
    "thorns": ("thorns_add", "add", False),
    "phys_reduce": ("phys_reduce_add", "add", False),
    "magic_reduce": ("magic_reduce_add", "add", False),
    "lifesteal_phys": ("lifesteal_phys_add", "add", False),
    "lifesteal_magi": ("lifesteal_magi_add", "add", False),
    # v107 隐藏职业专属属性被动支持（面板结算 + 战斗内消费）
    # v109.2 清理：shield_power/abyss_res 无对应被动技能（skills.py 零使用），
    # 保留 elem_res/luck/summon_power（龙魂/星辰之力/万兽之力，P0-2 已实装）
    "elem_res": ("elem_res_add", "add", False),
    "luck": ("luck_add", "add", False),
    "summon_power": ("summon_power_add", "add", False),
    # v113.1 修复：时咒线依赖的 heal_power（牧师一转觉醒被动「圣光祝福」）与
    # dodge（游侠一转觉醒被动「风之加护」）此前无映射 → 觉醒被动完全无效。
    "heal_power": ("heal_power_add", "add", False),
    "dodge": ("dodge_add", "add", False),
    # v134.1 意见#45：速度→暴击转化被动（游侠/刺客"疾风之眼"）——spd_crit 系数含义：
    #   每点速度 +0.001×mult 暴击（mult=0.1 → 每10点速度+1%），受 PCT_CAPS.crit 0.5 约束
    "spd_crit": ("spd_crit_add", "add", False),
}


def player_passive_stats(class_name: str, learned_skills: list | None = None) -> dict:
    """计算已学被动技能的属性加成（v64 被动系统）。

    被动技能 kind="被动"，passive 字段结构：
      {"stat": "atk", "mult": 0.15}             属性百分比加成（atk/def/matk/mdef/spd/mp/crit）
      {"stat": "atk", "cond": "rage>=5", ...}   条件型属性（暂不结算数值，战斗内按条件处理）
      {"stat": "chi_gain", "mult": 1}           气获取 +1（战斗内处理）
      {"stat": "fire", "mult": 0.10}            火系增伤（战斗内处理）
      其他 proc 型被动不在属性结算里，由 battle.py 处理
    返回属性加成 dict（百分比已转成系数 1+mult 形式，由调用方决定如何乘）。
    """
    bonus = {"hp_mult": 1.0, "mp_mult": 1.0, "atk_mult": 1.0, "def_mult": 1.0,
             "matk_mult": 1.0, "mdef_mult": 1.0, "spd_mult": 1.0, "crit_add": 0.0,
             "cdr_add": 0.0,  # v106.1 cdr 被动
             "pene_phys_add": 0.0, "pene_magi_add": 0.0,  # v106.2 穿透被动
             "lifesteal_add": 0.0, "crit_dmg_add": 0.0, "block_add": 0.0,  # v106.3 吸血/暴伤/格挡被动
             "thorns_add": 0.0, "phys_reduce_add": 0.0, "magic_reduce_add": 0.0,
             "lifesteal_phys_add": 0.0, "lifesteal_magi_add": 0.0,
             # v110.4 X2 P1-2：shield_power/abyss_res 无对应被动技能(skills.py 零使用)，
             # 恒 0 死键删除——battle.py:916-918 的读 pb.get(...,0.0) 恒 0 死循环由 X1 处理。
             # v113.1：恢复 heal_power_add/dodge_add（圣光祝福/风之加护 觉醒被动消费）
             "elem_res_add": 0.0, "luck_add": 0.0, "summon_power_add": 0.0,
             "heal_power_add": 0.0, "dodge_add": 0.0,
             "spd_crit_add": 0.0}  # v134.1 意见#45：速度→暴击被动（游侠/刺客"疾风之眼"）
    learned = [C.display("skills", s) for s in (learned_skills or []) if s]
    for name in learned:
        info = skill_info(class_name, name)
        if not info or info.get("kind") != K_PASSIVE:
            continue
        ps = info.get("passive") or {}
        rule = _PASSIVE_STAT_APPLY.get(ps.get("stat"))
        if rule is None:
            continue  # 条件型/战斗内机制 stat 由 battle.py 结算（原 if-elif 无分支，行为一致）
        key, op, need_cond_none = rule
        if need_cond_none and ps.get("cond") is not None:
            continue
        mult = float(ps.get("add", ps.get("mult", 0)))
        if op == "mul":
            bonus[key] *= (1 + mult)
        else:  # add（crit/cdr）
            bonus[key] += mult
    return bonus


def apply_passive_to_stats(st: dict, class_name: str, learned_skills: list | None) -> dict:
    """v110.4 X2 P1-2：把已学属性被动结算进属性 dict。

    与 battle.py:886-920 完全同键同 cap（mp/spd 乘算、crit 加算 cap0.6、
    cdr 加算 cap0.4、穿透乘算 cap0.6、其余加法并入 cap= C.PCT_CAPS），
    保证面板(player_stats_detail) == 战斗(_player_stats) 单一来源。
    条件型被动（cond rage>=5/hp_low_50 等）战斗内动态结算，此处不处理。
    """
    pb = player_passive_stats(class_name, learned_skills)
    if pb.get("mp_mult", 1.0) != 1.0:
        st["max_mp"] = int(st.get("max_mp", 0) * pb["mp_mult"])
        st["mp"] = int(st.get("mp", 0) * pb["mp_mult"])
    if pb.get("spd_mult", 1.0) != 1.0:
        st["spd"] = int(st.get("spd", 0) * pb["spd_mult"])
    if pb.get("crit_add", 0.0):
        # v110 §三：暴击率上限统一 0.5（PCT_CAPS 权威；原 0.6 与 buff 1.0 不一致）
        st["crit"] = min(st.get("crit", 0) + pb["crit_add"], C.PCT_CAPS.get("crit", 0.5))
    # v134.1 意见#45：速度→暴击转化（游侠/刺客"疾风之眼"）——每点速度 +0.001×mult 暴击
    #   mult=0.1 → 每 10 点速度 +1%；须在 spd_mult 应用后折算，受 PCT_CAPS.crit 0.5 约束
    if pb.get("spd_crit_add", 0.0):
        spd_crit = st.get("spd", 0) * 0.001 * pb["spd_crit_add"]
        st["crit"] = min(st.get("crit", 0) + spd_crit, C.PCT_CAPS.get("crit", 0.5))
    if pb.get("cdr_add", 0.0):
        st["cdr"] = min(st.get("cdr", 0) + pb["cdr_add"], 0.4)
    if pb.get("pene_phys_add", 0.0):
        st["pene_phys"] = min(1 - (1 - st.get("pene_phys", 0)) * (1 - pb["pene_phys_add"]), 0.6)
    if pb.get("pene_magi_add", 0.0):
        st["pene_magi"] = min(1 - (1 - st.get("pene_magi", 0)) * (1 - pb["pene_magi_add"]), 0.6)
    for _pk, _pv in (("lifesteal_add", "lifesteal"), ("crit_dmg_add", "crit_dmg"),
                     ("block_add", "block")):
        if pb.get(_pk, 0.0):
            st[_pv] = min(st.get(_pv, 0) + pb[_pk], C.PCT_CAPS.get(_pv, 0.6))
    for _pk, _pv in (("thorns_add", "thorns"), ("phys_reduce_add", "phys_reduce"),
                     ("magic_reduce_add", "magic_reduce"),
                     ("lifesteal_phys_add", "lifesteal_phys"),
                     ("lifesteal_magi_add", "lifesteal_magi")):
        if pb.get(_pk, 0.0):
            st[_pv] = min(st.get(_pv, 0) + pb[_pk], C.PCT_CAPS.get(_pv, 0.6))
    # v107 隐藏职业专属属性被动（龙魂/星辰之力/万兽之力；shield_power/abyss_res 无技能，已删）
    for _pk, _pv in (("elem_res_add", "elem_res"), ("luck_add", "luck"),
                     ("summon_power_add", "summon_power")):
        if pb.get(_pk, 0.0):
            st[_pv] = min(st.get(_pv, 0) + pb[_pk], C.PCT_CAPS.get(_pv, 0.6))
    # v113.1 觉醒被动：heal_power（圣光祝福 /+）与 dodge（风之加护 /+）加法并入，
    # 同 cap 权威（heal_power 0.5，dodge 0.4 见 core/constants.py PCT_CAPS）
    for _pk, _pv in (("heal_power_add", "heal_power"), ("dodge_add", "dodge")):
        if pb.get(_pk, 0.0):
            st[_pv] = min(st.get(_pv, 0) + pb[_pk], C.PCT_CAPS.get(_pv, 0.6))
    return st


def passive_skills_learned(class_name: str, learned_skills: list | None = None) -> list:
    """返回已学被动技能的中文名列表(v64)。battle.py 用它查触发型被动。"""
    learned = [C.display("skills", s) for s in (learned_skills or []) if s]
    out = []
    for name in learned:
        info = skill_info(class_name, name)
        if info and info.get("kind") == K_PASSIVE:
            out.append(name)
    return out


def is_passive_learned(class_name: str, passive_name: str, learned_skills: list | None = None) -> bool:
    """指定被动是否已学(v64)。passive_name 为被动技能中文名。"""
    return passive_name in passive_skills_learned(class_name, learned_skills)


# 属性中文名（面板/来源展示用）
STAT_NAMES = {"hp": "生命", "mp": "魔力", "atk": "攻击", "def": "防御", "matk": "魔攻",
              "mdef": "魔防", "spd": "速度", "crit": "暴击", "dodge": "闪避", "precise": "精准",
              "pene_phys": "物穿", "pene_magi": "法穿", "pene_flat": "固定物穿", "pene_mflat": "固定法穿",
              "tenacity": "韧性", "luck": "幸运",  # v106 穿透/韧性/幸运
              "cdr": "冷却缩减", "elem_res": "元素抗性", "abyss_res": "深渊抗性",
              "exp_bonus": "经验加成", "gold_bonus": "金币加成",  # v106.1 冷却/抗性/成长
              "heal_power": "治疗强度", "shield_power": "护盾强度",
              "lifesteal": "吸血", "crit_dmg": "暴击伤害", "block": "格挡",
              "thorns": "反伤", "phys_reduce": "物免", "magic_reduce": "魔免",
              "lifesteal_phys": "物吸", "lifesteal_magi": "法吸",
              "summon_power": "召唤强化"}  # v106.3/v106.4 + v107 召唤


def player_stats_detail(class_name: str, level: int, equipment: dict, tier: int = 0, attributes: dict = None, evolve_path: int = 0, title_bonus: dict = None, race: str = None, learned_skills: list | None = None) -> tuple:
    """拆解属性来源。返回 (最终属性 dict, 来源明细 list)。

    来源明细每项: {"name": 来源名, "stats": {属性: 加值}}。
    与 player_final_stats 共用同一套计算（最终属性完全一致），保证面板显示和实际战斗一致。
    """
    sources = []
    # 1. 基础（职业 + 等级成长 + 转职加成 + v25 分支倾向 + 种族成长倍率）
    st = player_base_stats(class_name, level, tier, evolve_path, race)
    base_src = {"hp": st["max_hp"], "mp": st["max_mp"]}
    for k in ("atk", "def", "matk", "mdef", "spd"):
        base_src[k] = st[k]
    # v55.1：暴击/闪避基础值也进来源（属性面板显示完整构成）
    base_src["crit"] = st.get("crit", 0)
    base_src["dodge"] = st.get("dodge", 0)
    # v106：穿透/韧性/幸运基础值也进来源（职业天生特色如刺客 10% 物穿）
    base_src["pene_phys"] = st.get("pene_phys", 0)
    base_src["pene_magi"] = st.get("pene_magi", 0)
    base_src["pene_flat"] = st.get("pene_flat", 0)
    base_src["pene_mflat"] = st.get("pene_mflat", 0)
    base_src["tenacity"] = st.get("tenacity", 0)
    base_src["luck"] = st.get("luck", 0)
    # v106.1：冷却缩减/元素抗性/深渊抗性/经验金币加成基础值也进来源（职业天生特色）
    base_src["cdr"] = st.get("cdr", 0)
    base_src["elem_res"] = st.get("elem_res", 0)
    base_src["abyss_res"] = st.get("abyss_res", 0)
    base_src["exp_bonus"] = st.get("exp_bonus", 0)
    base_src["gold_bonus"] = st.get("gold_bonus", 0)
    # v106.2：治疗强度/护盾强度基础值也进来源（职业天生特色）
    base_src["heal_power"] = st.get("heal_power", 0)
    base_src["shield_power"] = st.get("shield_power", 0)
    sources.append({"name": "基础", "stats": base_src})
    # 2. 自由属性点：力量→攻击 敏捷→速度/暴击 智力→魔攻/魔力 耐力→生命
    # v105 P1(M01#7)：attributes 可能是字符串/'null'（脏档）→ 非 dict 一律按空处理
    attr = attributes if isinstance(attributes, dict) else {}
    attr_src = {}
    # v136 数值重构（鱼鱼拍板 C）：属性点转化率回归合理值，降基础属性虚高
    # str→atk 1.2→1.0（1点力量=1攻击）、int→matk 1.2→1.0、vit→hp 8→6
    # 原 1.2 导致裸装主属性堆叠收益高于装备，玩家无脑全投主属性，装备系统失去意义
    attr_src["atk"] = int(attr.get("str", 0) * 1.0)
    attr_src["matk"] = int(attr.get("int", 0) * 1.0)
    attr_src["spd"] = int(attr.get("agi", 0) * 0.8)
    attr_src["crit"] = attr.get("agi", 0) * 0.004
    attr_src["hp"] = int(attr.get("vit", 0) * 6)
    attr_src["mp"] = int(attr.get("int", 0) * 1.5)
    st["atk"] += attr_src["atk"]
    st["matk"] += attr_src["matk"]
    st["spd"] += attr_src["spd"]
    st["crit"] = min(st["crit"] + attr_src["crit"], 0.5)
    st["max_hp"] += attr_src["hp"]
    st["max_mp"] += attr_src["mp"]
    if any(attr_src.values()):
        sources.append({"name": "自由属性点", "stats": {k: v for k, v in attr_src.items() if v}})
    # 3. 装备（含强化增幅 + 词条 + 附魔，按装备逐件列出）
    for slot, item in equipment.items():
        if not item:
            continue
        enh = item.get("enhance", 0)
        mult = 1.0
        if enh > 0:
            info = C.ENHANCE_TABLE.get(enh)
            if info:
                mult = info["mult"]
        item_src = {}
        for k, v in item.get("stats", {}).items():
            if k in STAT_NAMES:
                # v101.21e 修复：PCT_STATS（crit/dodge）保留小数——原代码只特判 crit，
                # dodge 0.05 被 int() 截断成 0，装备闪避加成全部丢失
                # v172 真等级化：升级乘区已移除（装备 lv 提升 → stats 重算），此处仅乘强化
                item_src[k] = item_src.get(k, 0) + (int(v * mult) if k not in C.PCT_STATS else v)
        for af in item.get("affixes", []):
            # 阶段八：词条 v2 是 ID 列表（str），常驻属性已在生成时折算进 stats；
            # 旧结构 [{"stat","value"}] 兼容处理
            if isinstance(af, dict):
                k, v = af.get("stat"), af.get("value", 0)
                if k in STAT_NAMES:
                    item_src[k] = item_src.get(k, 0) + v
        for en in item.get("enchant", []):
            k, v = en.get("stat"), en.get("value", 0)
            if k in STAT_NAMES:
                item_src[k] = item_src.get(k, 0) + v
        # v136 原石系统：孔位里镶嵌的原石属性加成（stats 值=百分比/数值，直接加）
        # sockets: {孔位1: gem_dict, 孔位2: gem_dict, ...}，gem_dict 形如 {"stats": {"atk": 0.01}, ...}
        # 原石 stats 键全在 STAT_NAMES 面板属性内；百分比/数值统一直接加，
        # 后续 PENE_PCT_STATS/PCT_STATS 分支统一处理 cap（见下方汇总循环）
        for _gk, _gv in (item.get("sockets") or {}).items():
            if not isinstance(_gv, dict):
                continue
            for _sk, _sv in (_gv.get("stats") or {}).items():
                if _sk in STAT_NAMES:
                    item_src[_sk] = item_src.get(_sk, 0) + _sv
        # v136 怪异炼成：随机强化属性（calamity_bonus: {属性: 百分比}，每件限 3 次）
        # 与强化/升级乘区独立叠加，走 PCT_STATS cap（≤5% 小数值，机制向取舍）
        for _ck, _cv in (item.get("calamity_bonus") or {}).items():
            if _ck in STAT_NAMES and _cv:
                item_src[_ck] = item_src.get(_ck, 0) + _cv
        if item_src:
            enh_s = f"+{enh}" if enh > 0 else ""
            sources.append({"name": f"{item.get('name', slot)}{enh_s}", "stats": item_src})
    # 汇总装备加成到 st（与 player_final_stats 原逻辑一致；装备键 hp/mp → max_hp/max_mp）
    for src in sources:
        if src["name"] in ("基础", "自由属性点"):
            continue
        for k, v in src["stats"].items():
            if k in C.PENE_PCT_STATS:
                # v106：百分比穿透乘算合成 1-(1-a)(1-b)，不加法（职业/词条/被动多来源）
                st[k] = min(1 - (1 - st.get(k, 0)) * (1 - v), C.PCT_CAPS.get(k, 0.6))
            elif k in C.PCT_STATS:
                st[k] = min(st.get(k, 0) + v, C.PCT_CAPS.get(k, 0.6))
            elif k == "hp":
                st["max_hp"] += v
            elif k == "mp":
                st["max_mp"] += v
            else:
                st[k] = st.get(k, 0) + v
    # 4. 套装 2 件百分比加成（基于基础+属性点+装备的最终值）
    # v136 Phase6：传 class_name 实现职业套装折扣（本职业 100%/非本职业 60%）
    sb2 = set_bonus_2(equipment, class_name)
    if sb2:
        src2 = {}
        for k, v in sb2.items():
            if k in C.PENE_PCT_STATS:
                src2[k] = v
                st[k] = min(1 - (1 - st.get(k, 0)) * (1 - v), C.PCT_CAPS.get(k, 0.6))
            elif k in C.PCT_STATS:
                src2[k] = v
                st[k] = min(st.get(k, 0) + v, C.PCT_CAPS.get(k, 0.6))
            elif k == "hp":
                src2["hp"] = v
                st["max_hp"] = int(st["max_hp"] * (1 + v))
            elif k == "mp":
                src2["mp"] = v
                st["max_mp"] = int(st["max_mp"] * (1 + v))
            else:
                src2[k] = v
                # v110 审计修复：非 STAT 键（如旧圣光套 bonus_2.heal）不参与属性倍率，
                # 静默跳过防 KeyError 崩溃（特殊键由各自消费段读取）
                if k in st:
                    st[k] = int(st[k] * (1 + v))
        names2 = [s for s, c in active_sets(equipment).items() if c >= 2]
        sources.append({"name": f"套装2件({'/'.join(names2)})", "stats": src2, "pct": True})
    # 5. 套装 4 件属性型特效（常驻属性；数值读 sets.py bonus_4.stats，v126 数值下沉）
    # 按已激活(>=4 件)套装逐套应用各自 bonus_4.stats（同 eff 多套叠加语义与旧代码一致；
    # 无 stats 字段的特效型由战斗侧消费）
    eff_src = {}
    for sname, cnt in active_sets(equipment).items():
        if cnt < 4:
            continue
        _b4 = (_set_info(sname) or {}).get("bonus_4") or {}
        for k, v in (_b4.get("stats") or {}).items():
            if k == "mdef":
                eff_src["mdef"] = eff_src.get("mdef", 0) + v
                st["mdef"] = int(st["mdef"] * (1 + v))
            elif k == "crit":
                eff_src["crit"] = eff_src.get("crit", 0) + v
                st["crit"] = min(st["crit"] + v, 0.5)
            elif k == "dodge":
                eff_src["dodge"] = eff_src.get("dodge", 0) + v
                st["dodge"] = min(st["dodge"] + v, 0.4)
            else:
                eff_src[k] = eff_src.get(k, 0) + v
                st[k] = min(st.get(k, 0) + v, C.PCT_CAPS.get(k, 0.6))
    if eff_src:
        names4 = [s for s, c in active_sets(equipment).items() if c >= 4]
        sources.append({"name": f"套装4件({'/'.join(names4)})", "stats": eff_src, "pct": True})
    # 6. 副业大师称号加成（固定数值）
    if title_bonus:
        tb = {k: v for k, v in title_bonus.items() if k in STAT_NAMES and v}
        if tb:
            for k, v in tb.items():
                if k in C.PENE_PCT_STATS:
                    st[k] = min(1 - (1 - st.get(k, 0)) * (1 - v), C.PCT_CAPS.get(k, 0.6))
                elif k in C.PCT_STATS:
                    st[k] = min(st.get(k, 0) + v, C.PCT_CAPS.get(k, 0.6))
                elif k == "hp":
                    st["max_hp"] += int(v)
                elif k == "mp":
                    st["max_mp"] += int(v)
                else:
                    st[k] = st.get(k, 0) + int(v)
            sources.append({"name": "副业称号", "stats": tb})
    # 7. 种族天赋 stat 型（08 章：月缺 HP-5% / 磐石步履先手-5% / 月之优雅暴击+8% / 坚韧体魄 HP+8%）
    rt = race_stats(race)
    if rt:
        race_src = {}
        if rt.get("hp_mult", 1.0) != 1.0:
            race_src["hp"] = rt["hp_mult"]
            st["max_hp"] = int(st["max_hp"] * rt["hp_mult"])
        if rt.get("spd_mult", 1.0) != 1.0:
            race_src["spd"] = rt["spd_mult"]
            st["spd"] = int(st["spd"] * rt["spd_mult"])
        if rt.get("crit_add"):
            race_src["crit"] = rt["crit_add"]
            st["crit"] = min(st["crit"] + rt["crit_add"], 0.5)
        # v106.2：新属性种族天赋（exp_bonus/luck/elem_res/abyss_res/cdr 加法属性）
        for _rk in ("exp_bonus", "luck", "elem_res", "abyss_res", "cdr"):
            if rt.get(_rk):
                race_src[_rk] = rt[_rk]
                st[_rk] = min(st.get(_rk, 0) + rt[_rk], C.PCT_CAPS.get(_rk, 0.6))
        # v106.3：吸血/暴击伤害/格挡种族天赋（矮人岩壁格挡/精灵月华暴伤/兽人嗜血）
        for _rk in ("lifesteal", "crit_dmg", "block"):
            if rt.get(_rk):
                race_src[_rk] = rt[_rk]
                st[_rk] = min(st.get(_rk, 0) + rt[_rk], C.PCT_CAPS.get(_rk, 0.6))
        # v106.4：反伤/物魔免种族天赋（石肤物免/龙鳞魔免/兽人鲁莽魔免负值已存在，统一聚合）
        for _rk in ("thorns", "phys_reduce", "magic_reduce", "lifesteal_phys", "lifesteal_magi"):
            if rt.get(_rk):
                race_src[_rk] = rt[_rk]
                st[_rk] = min(st.get(_rk, 0) + rt[_rk], C.PCT_CAPS.get(_rk, 0.6))
        if race_src:
            sources.append({"name": "种族天赋", "stats": race_src, "pct": True})
    # 8. 已学属性被动（v110.4 X2 P1-2：面板接入永久被动，与 battle.py:886-920 同键同 cap）
    # 条件型被动（cond rage>=5/hp_low_50/battle_start 等）战斗内动态结算，面板不处理
    if learned_skills:
        _before = dict(st)
        apply_passive_to_stats(st, class_name, learned_skills)
        ps = player_passive_stats(class_name, learned_skills)
        p_src = {}
        # mul 型（mp/spd）：以乘数形式进入来源；add 型：记录最终并入值
        if ps.get("mp_mult", 1.0) != 1.0:
            p_src["mp"] = ps["mp_mult"]
        if ps.get("spd_mult", 1.0) != 1.0:
            p_src["spd"] = ps["spd_mult"]
        for st_key in ("crit", "cdr", "pene_phys", "pene_magi", "lifesteal", "crit_dmg",
                       "block", "thorns", "phys_reduce", "magic_reduce", "lifesteal_phys",
                       "lifesteal_magi", "elem_res", "luck", "summon_power"):
            if st.get(st_key, 0) != _before.get(st_key, 0):  # 被动并入或 cap 收敛导致变化 → 记为来源
                p_src[st_key] = st.get(st_key, 0) - _before.get(st_key, 0)
        if p_src:
            sources.append({"name": "被动技能", "stats": p_src, "pct": True})
    return st, sources


# ---------------- v10 套装计算 ----------------
def active_sets(equipment: dict) -> dict:
    """返回 {套装名: 已穿件数}，只含 >=2 件的套装(2 件才有效果)"""
    counts = {}
    for slot, item in (equipment or {}).items():
        if not item:
            continue
        s = item.get("set")
        if s:
            counts[s] = counts.get(s, 0) + 1
    return {s: c for s, c in counts.items() if c >= 2}


def _set_info(set_name: str) -> dict | None:
    """按套装名(装备 set 字段，中文)查 SETS 条目(SETS key 是 set_xxx ID)"""
    if set_name in C.SETS:
        return C.SETS[set_name]
    for info in C.SETS.values():
        if info.get("name") == set_name:
            return info
    return None


def set_bonus_2(equipment: dict, class_name: str | None = None) -> dict:
    """汇总所有激活套装的 2 件百分比加成 {stat: 总和}
    阶段八：>=4 件时叠加 4 件属性加成（bonus_4_stats），>=5 件时叠加 5 件 stat 型效果（bonus_5.crit/dodge，10 章五节橡木/铁港）
    v130.2c 修复 P0：effect 型 bonus_2（资源联动 12 套，键含 effect/res/value/on/desc）不再按 stat 累加
    （旧实现 int+str TypeError 崩点）；整 dict 跳过交由战斗侧 _set_effs 消费，面板 sources 不再混入
    非数值键（P2 污染清理）。仅聚合数值型属性键，兼容 {"spd": 0.15} 旧属性型。
    v136 Phase6：职业套装职业折扣——套装 entry 带 "class" 字段（本职业专用）时，
    非本职业玩家（class_name != entry["class"]）属性加成 ×0.6（鱼鱼拍板：本职业 100%，非本职业 60%）。
    effect 型特效（bonus_4/bonus_5）不打折（机制向非面板向）。"""
    bonus = {}
    for sname, cnt in active_sets(equipment).items():
        info = _set_info(sname)
        if not info:
            continue
        # v136 Phase6 职业折扣：仅影响 stat 型加成（bonus_2/bonus_4_stats/bonus_5 数值键）
        _disc = 1.0
        _cls = info.get("class")
        if _cls and class_name and class_name != _cls:
            _disc = 0.6
        _b2 = info.get("bonus_2") or {}
        if "effect" not in _b2:
            for k, v in _b2.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    bonus[k] = bonus.get(k, 0) + v * _disc
        if cnt >= 3:
            # v136 审计：区域套 3 槽位（armor/legs/boots）只能凑 3 件，bonus_3 让 3 件套生效
            for k, v in info.get("bonus_3_stats", {}).items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    bonus[k] = bonus.get(k, 0) + v * _disc
            for k, v in info.get("bonus_3", {}).items():
                if k not in ("effect", "desc", "chance", "stats") and isinstance(v, (int, float)) and not isinstance(v, bool):
                    bonus[k] = bonus.get(k, 0) + v * _disc
        if cnt >= 4:
            for k, v in info.get("bonus_4_stats", {}).items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    bonus[k] = bonus.get(k, 0) + v * _disc
        if cnt >= 5:
            for k, v in info.get("bonus_5", {}).items():
                # 5 件 stat 型效果（crit/dodge 直接是属性）；desc/effect 型（战斗特效）不在这里结算
                if k in C.PCT_STATS and isinstance(v, (int, float)) and not isinstance(v, bool):
                    bonus[k] = bonus.get(k, 0) + v * _disc
    return bonus


def has_set(equipment: dict, set_name: str) -> bool:
    """装备是否穿戴了指定套装(10 章名册套装按套装名匹配)"""
    for item in (equipment or {}).values():
        if item and item.get("set") == set_name:
            return True
    return False


def set_bonus_4(equipment: dict) -> list:
    """返回已激活套装的 4 件特效效果名列表（v136 审计：区域套 3 槽位用 bonus_3 特效）"""
    effs = []
    for sname, cnt in active_sets(equipment).items():
        info = _set_info(sname)
        if info and cnt >= 4 and info.get("bonus_4", {}).get("effect"):
            effs.append(info["bonus_4"]["effect"])
        elif info and cnt >= 3 and info.get("bonus_3", {}).get("effect"):
            effs.append(info["bonus_3"]["effect"])
    return effs


def skill_learn_cost_for(player: dict, need_lv: int) -> int:
    """v95.7 #36：最终学习成本（含种族折扣）——技能列表/学习提示/扣点必须同源，避免显示不一致
    v134.1 人类天赋重做：learn_discount 已删除（鱼鱼拍板改 first_upgrade_refund），
    本函数保留比例折扣兼容（未来种族若配比例仍生效）"""
    cost = skill_learn_cost(need_lv)
    disc = race_stats(player.get("race")).get("learn_discount")
    if disc:
        cost = max(1, int(cost * (1 - disc)))
    return cost
