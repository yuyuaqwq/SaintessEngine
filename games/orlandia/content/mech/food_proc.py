"""saintess_engine 食物战斗效果装配层（game/services/battle_food_proc.py，N10-B7）。

saintess_engine 包外（引擎零知识——本模块 import 引擎/数据，引擎不 import 本模块）。
职责：把战斗内吃下的效果料理（foodfx:aid,...）→ actor["triggers"] 声明
（N8 事件总线消费）+ effects period 周期声明（schedule 时间驱动每刻跳），
使 17 种战斗料理效果在 saintess_engine 战斗中生效（N10-B7 缺口补完）。

架构对齐 docs/DESIGN_N10B7_food_effects.md + services/battle_equip_proc.py
（affix 迁移先例）：
- 命中/受击/乘区触发类 → actor["triggers"] = {事件: [效果 dict]}，效果 dict
  复用 we_* 扩展动作（we_affix_dot/defdown/bonus/element/counter/reflect/
  dmg_mult_cond/taken_mult_cond/extra_dmg）——名词执行器与 affix 词条同源，
  每动作全项目只写一次。
- 周期恢复类（regen/meditate/dawn_crown）→ actor["effects"][key] period 声明
  （schedule 周期段时间驱动每刻跳，对齐 battle_item_use hot: regen_hot 先例；
  **不是 turn_start 行动帧**——鱼鱼 2026-09-09 追问定稿：描述"每刻回复"=
  时间驱动 1 刻一跳，同旧引擎 tick 卡语义）。
- actor["food_effects"] 容器保留（吃重复去重/图鉴展示仍读它），挂 triggers 幂等。

数值权威 = game/data/food_effect_data.py FOOD_EFFECT_PARAMS（读表零默认值：
缺字段 = 无此行为，不复制硬编码）。安装入口 battle_item_use.translate foodfx
分支（吃料理唯一入口，_instance_router + _restore_battle 全覆盖）。

★ B8 切消费端端口（2026-09-13，包内 `content/mech/food_proc.py`）
----------------------------------------------------------------
本文件 = 游戏仓 `game/services/battle_food_proc.py` 的**逐字端口**。正文一字不改，
唯一改动两处：① `_food_params()` 的读表口从 `..data.food_effect_data.FOOD_EFFECT_PARAMS`
换成包内域文件 `content/data/food_effects.json`（同表；由 `scripts/export_domains/life_growth.py:
derive_food_effects` 单向导出，导出器侧实测 19 条、与真源逐条相等）；② 补 `import os` +
`_HERE`（读包内文件用）。
对拍证据：`overnight/_b8_verify_food.py` —— 19 条效果 × `food_trigger_decls` /
`food_period_decl` / `install_food_fx` 三入口，与宿主真源逐字段 deep-equal（定种子）。
端口后宿主那份由 B8 收口退役（`game/services/battle_food_proc.py` → 移出仓）。
"""
from __future__ import annotations

import os
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))   # <pkg>/content/mech（端口新增：读包内域文件用）

# ============================================================
# 数据表读取（数值权威）
# ============================================================

_FP_TABLE = None


def _food_params() -> dict:
    """读包内域文件 `content/data/food_effects.json`（真源 `game/data/food_effect_data.py`
    `FOOD_EFFECT_PARAMS`，导出器单向产出）。读不到 → 抛，不静默空表（空表 = 吃料理什么都不发生）。"""
    global _FP_TABLE
    if _FP_TABLE is None:
        import json as _json
        with open(os.path.normpath(os.path.join(_HERE, "..", "data", "food_effects.json")),
                  encoding="utf-8") as f:
            _FP_TABLE = _json.load(f)
    return _FP_TABLE


def _fp(key: str, field: str, default=0.0):
    """读食物效果参数（数值权威 food_effect_data.py）。"""
    try:
        return (_food_params().get(key) or {}).get(field, default)
    except Exception:
        return default


# ============================================================
# food aid → 事件映射（old 事件名 → saintess_engine 事件展开，同 equip_proc）
# ============================================================

# hit → 普攻+技能命中（旧 _food_on_hit 在 _skill_finalize 尾部 = 普攻 basic + 技能同管道；
# saintess_engine actions.py 普攻 fire attack_hit / 技能 fire skill_hit——双挂与 affix 词条一致）
_EVENT_MAP = {
    "hit": ("attack_hit", "skill_hit"),
    "taken": ("on_taken",),
    "dmg_calc": ("dmg_calc",),
    "taken_calc": ("taken_calc",),
    "turn_start": ("turn_start",),
}


def _map_event(old_ev: str) -> tuple:
    """旧事件 → saintess_engine 事件；不在表 = 同名直通。"""
    return _EVENT_MAP.get(old_ev, (old_ev,))


# ============================================================
# food aid → triggers 声明翻译（吃入挂载用；数值全读表）
# ============================================================

def _chance_pct(aid: str, field: str = "chance", default=1.0) -> float:
    """触发概率：表缺省恒触发（旧 food 无 chance 字段 = 每次命中都触发）。"""
    return float(_fp(aid, field, default))


def food_trigger_decls(aid: str) -> dict:
    """food aid → {old_event: [效果 dict]}；未知 aid → {}（防拼写漂移静默）。

    声明全部复用 we_* 扩展动作（与 affix 词条同执行器）；参数带数值（读
    FOOD_EFFECT_PARAMS），owner 由挂载函数注入。mode 语义对齐 equip_proc
    同名词条翻译器（bleed/armor_break/element_*/combo/charge/pierce/counter/
    execute 均已迁 affix 管线，此处只换数据源为 food 表）。
    """
    if aid == "lifesteal":
        # 蛇羹：每次攻击回复伤害 8% 生命（we_extra_dmg lifesteal 分支 food_lifesteal 别名）
        return {"hit": [{"type": "we_extra_dmg", "key": "food_lifesteal",
                         "heal_pct": float(_fp("lifesteal", "pct", 0.08))}]}
    if aid == "bleed":
        # 烬火辣椒：20% 使目标流血（affix_bleed 声明 cap3 每刻5% 3刻——复用词条 DOT key）
        return {"hit": [{"type": "we_affix_dot", "key": "food_bleed",
                         "state_key": "affix_bleed",
                         "chance": _chance_pct("bleed", "chance", 0.20),
                         "stacks": int(_fp("bleed", "stacks", 3))}]}
    if aid == "armor_break":
        # 蘑菇汤：25% 降低目标防御 15%（2 刻）
        return {"hit": [{"type": "we_affix_defdown", "key": "food_armor_break",
                         "chance": _chance_pct("armor_break", "chance", 0.25),
                         "pct": float(_fp("armor_break", "pct", 0.15)),
                         "turns": int(_fp("armor_break", "turns", 2))}]}
    if aid == "combo":
        # 鹰蛋：15% 追加一次 50% 伤害（本击 dmg × pct）
        return {"hit": [{"type": "we_affix_bonus", "key": "food_combo",
                         "mode": "dmg_pct",
                         "chance": _chance_pct("combo", "chance", 0.15),
                         "pct": float(_fp("combo", "pct", 0.50)),
                         "tag": "⚡", "name": "连击"}]}
    if aid == "charge":
        # 皇家烤肉：10% 追加 50% 伤害
        return {"hit": [{"type": "we_affix_bonus", "key": "food_charge",
                         "mode": "dmg_pct",
                         "chance": _chance_pct("charge", "chance", 0.10),
                         "pct": float(_fp("charge", "pct", 0.50)),
                         "tag": "💪", "name": "蓄力爆发"}]}
    if aid == "element_fire":
        # 灰烬烤饼：攻击附加 5% 火属性伤害
        return {"hit": [{"type": "we_affix_element", "key": "food_element_fire",
                         "element": "fire", "pct": float(_fp("element_fire", "pct", 0.05)),
                         "name": "火焰附加"}]}
    if aid == "element_ice":
        # 冰霜浆果：攻击附加 5% 冰属性伤害 + 减速
        return {"hit": [{"type": "we_affix_element", "key": "food_element_ice",
                         "element": "ice", "pct": float(_fp("element_ice", "pct", 0.05)),
                         "name": "冰霜附加",
                         "slow": float(_fp("element_ice", "slow", 0.10)),
                         "slow_turns": int(_fp("element_ice", "slow_turns", 2))}]}
    if aid == "pierce":
        # 雪狼肉排：20% 无视防御追加伤害（60% 攻击）
        return {"hit": [{"type": "we_affix_bonus", "key": "food_pierce",
                         "mode": "atk_true",
                         "chance": _chance_pct("pierce", "chance", 0.20),
                         "atk_pct": float(_fp("pierce", "atk_pct", 0.60)),
                         "tag": "🏹", "name": "贯穿"}]}
    if aid == "static":
        # 雷雨藤烤串：静电麻痹——攻击 20% 令敌方减速（2 刻，速度减半对齐旧 SPD_DOWN_MULT）
        return {"hit": [{"type": "we_hit_slow", "key": "food_static",
                         "chance": _chance_pct("static", "chance", 0.20),
                         "slow": float(_fp("static", "slow_pct", 0.5)),
                         "turns": int(_fp("static", "turns", 2))}]}
    if aid == "aurora_guard":
        # 极光花蜜：极光庇护——受击伤害 -15%（taken_calc 乘区，恒生效）
        return {"taken_calc": [{"type": "we_taken_mult_cond", "key": "food_aurora_guard",
                                "cond": "always",
                                "mult": 1.0 - float(_fp("aurora_guard", "pct", 0.15))}]}
    if aid == "counter":
        # 狼肉干：20% 反击 60% 伤害（受击时，攻击方在 ctx.source）
        return {"taken": [{"type": "we_affix_counter", "key": "food_counter",
                           "chance": _chance_pct("counter", "chance", 0.20),
                           "atk_pct": float(_fp("counter", "atk_pct", 0.60))}]}
    if aid == "thorns":
        # 鹿奶干酪：10% 反弹 30% 伤害（基于原始 dmg）
        return {"taken": [{"type": "we_reflect", "key": "food_thorns",
                           "chance": _chance_pct("thorns", "chance", 0.10),
                           "reflect_pct": float(_fp("thorns", "pct", 0.30))}]}
    if aid == "execute":
        # 海盗炖鱼：<30% ×1.3（dmg_calc 乘区）
        return {"dmg_calc": [{"type": "we_dmg_mult_cond", "key": "food_execute",
                              "cond": "hp_target_lt",
                              "threshold": float(_fp("execute", "hp_ratio", 0.30)),
                              "mult": float(_fp("execute", "mult", 1.30)),
                              "tag": "💀处决"}]}
    if aid == "precise":
        # 海鲜浓汤：本场 +10%（dmg_calc 乘区）
        return {"dmg_calc": [{"type": "we_dmg_mult_cond", "key": "food_precise",
                              "cond": "always",
                              "mult": float(_fp("precise", "mult", 1.10)),
                              "tag": "🎯精准"}]}
    if aid == "dragon_tongue":
        # 龙蛋煎饼：攻击叠龙语印记（effects["dragon_mark"] 层，每层 +2% 伤害上限 5）。
        # 叠层走引擎原生 apply op=add（cap 查 EFFECT_RULES.dragon_mark）；
        # 乘区 = stat_scale.dmg_mult 通用通道（同 rage）→ stats 折算 _state_dmg_mult
        # → actions 伤害乘区自动消费，无需扩展动作。
        return {"hit": [{"type": "apply", "key": "dragon_mark", "op": "add",
                         "amount": 1, "on": "caster"}]}
    # 未知/未迁 aid → 空（静默跳过；shield 特判在 battle_item_use 独立处理）
    return {}


# 周期恢复类（不进 triggers——effects period 时间驱动，见模块 docstring）
_PERIOD_FOOD = {
    "regen":      ("food_regen",      "heal_pct", 0.01),
    "meditate":   ("food_meditate",   "mana_pct", 0.01),
    "dawn_crown": ("food_dawn_crown", "heal_pct", 0.02),
}


def food_period_decl(aid: str) -> Optional[dict]:
    """周期恢复类 → effects 条目 period 声明（schedule 每刻跳，无 turns 战斗全程）。

    返回 {"key": ..., "period": {...}} 或 None（非周期类）。对齐 hot: regen_hot
    先例但无 turns 限时（旧效果料理回春 keep=True 常驻到战斗结束）。
    """
    spec = _PERIOD_FOOD.get(aid)
    if not spec:
        return None
    key, pct_field, default_pct = spec
    pct = float(_fp(aid, pct_field, default_pct))
    period = {"dir": "heal", "interval": 1.0, pct_field: pct}
    return {"key": key, "period": period}


# ============================================================
# 挂载入口（battle_item_use.translate foodfx 分支调用）
# ============================================================

def install_food_fx(actor: dict, aids: list, logs: list) -> None:
    """把吃下的料理 aid 列表装配进 actor（幂等：重复 aid 不重复挂）。

    - 命中/受击/乘区类 → actor["triggers"][事件]（we_* 扩展动作执行）
    - 周期恢复类 → actor["effects"][key] period 声明（schedule 周期段消费）
    - 未知 aid → 静默跳过（防拼写漂移；FOOD_EFFECT_NAMES 展示另管）
    """
    if not actor or not aids:
        return
    # ★ 端口差异（唯一一处「不照抄」）：真源在此**运行时**注册 `we_*` 扩展动作
    #   （`from .battle_equip_proc import install_ext_actions`）。包内没有那个模块 ——
    #   因为包内 `content/mech/equip.py` 的动作是 **import 期 `@register_action` 注册**的，
    #   而 `content/apply.py` 已把七族列全（import 即注册）。所以这里**不是**静默 try/except，
    #   而是显式声明「无需运行时注册」。想验证：`from content.mech import equip` 后
    #   `saintess_engine.effects.ACTION_HANDLERS` 里就有 we_* 名词（见端口对拍门禁 §5）。
    tr = actor.setdefault("triggers", {})
    ef = actor.setdefault("effects", {})
    for aid in aids:
        raw = food_trigger_decls(aid)
        for old_ev, effs in raw.items():
            for b2_ev in _map_event(old_ev):
                bucket = tr.setdefault(b2_ev, [])
                for _e in effs:
                    # 幂等：同 aid 同事件同 type 不重复挂（吃重复食物）
                    _dup = any(
                        isinstance(x, dict) and x.get("key") == _e.get("key")
                        for x in bucket
                    )
                    if not _dup:
                        bucket.append(dict(_e, _owner=actor))
        pd = food_period_decl(aid)
        if pd:
            entry = ef.get(pd["key"])
            if not isinstance(entry, dict):
                entry = ef[pd["key"]] = {"stacks": 1}
            entry["period"] = dict(pd["period"])  # 幂等重吃：覆盖同数值声明
