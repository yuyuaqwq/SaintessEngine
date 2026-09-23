# -*- coding: utf-8 -*-
"""《奥兰迪亚》包内 **药水效果层**（逐字搬自游戏仓 `game/core/potion_effects.py`，719 行）。

真源 `:16-719` 正文（`POTION_EFFECTS = {}` → 末尾 `vuln`，704 行）**逐字**搬入，只改三类东西：
  ① **数据源（包内单源）**：`DEFAULTS` 扫描表 `from ..data.items import ITEMS` →
     `content/data/items.json`（同一个 900 条域；门禁 B0 实测 keys / `effect` /
     `effect_data` **逐项相等**）；两处 `from ..data.battle_rules import EFFECT_RULES` →
     `content/rules/effect_rules.json`（门禁 B0 实测 85 条 name/cap/start_classes 逐项相等）
  ② **战斗对象**：真源的 `battle` 是旧引擎 `Battle` 实例 → 包内 = **调用方传入的战斗替身接口**
     （本包不搬引擎；handler 里每个 `battle.*` 调用都是一次回调，清单见 ③）
  ③ **共享效果动作**：`from .effect_actions import action_def_down` → `battle.action_def_down(...)`
     （`game/core/effect_actions.py` 未进包；该动作本体就是「改敌方 actor 状态」，属接口侧）

**逐字保真**：36 个 handler 的正文除上述三类改动外**一字未改**（含注释、emoji、文案、
`setdefault` 链、缺省数值）。签名保持 `fn(battle, player, value) -> str`：
    `player` = 调用方给的玩家 dict（战斗内快照；属性/刻数变更**原地写回这个 dict**）
    `value`  = 物品级 `effect_data`（取自 `content/data/items.json`）；`None` → 回退 `DEFAULTS`
    返回     = 日志行（`None` = 不追加日志；未注册效果由调用方 `POTION_EFFECTS.get(kind)` 判空跳过）

③ 替身回调清单（handler → `battle` 接口调用；门禁 C 段用假回调逐次记录参数与真源对拍）
| handler | 接口调用（真源写法逐字相同的调用点） |
|---|---|
| `def_down` / `trap` / `steal_buff` / `dot_amp` / `vuln` | `battle._hit_tgt()` |
| `shield_small` / `shield_big` | `battle._add_shield("potion", gain, turns)` |
| `restore_resource` / `restore_resource_full` / `battle_start_resource` / `resource_charge` | `battle._res_gain(player, key, amount)` |
| `restore_resource` / `resource_amp` / `battle_start_resource` | `battle._branch_keys(player)`（职业分支资源位） |
| `full_tension` | `battle._is_branch_of(player, "风行者", "疾风射手", "疾风猎手")` |
| `apply_mark` | `battle._elem_mark_apply(mark, layers=stacks, player=player)` + `battle._elem_reaction_boost`（读后写） |
| `def_down` | `battle.action_def_down(logs, turns=…, pct=…, target=battle._hit_tgt())` |
| `dot_amp` / `vuln` / `trap` / `steal_buff` | 目标 actor dict 的 `debuffs` / `buffs`（经 `_hit_tgt()` 取） |
| `reaction` | `battle._elem_marks()` / `_reaction_table_resolve` / `_player_stats` / `_deal_damage` |

⚠️ 缺口（**真源既有缺陷，本批不修**——逐字保真；门禁 C 段断言「两侧同名同错」）：
   1. `eff_trap` 的 Boss 数值分支用 `random.random()`，但真源文件**从未 `import random`**
      → 该分支 `NameError`（普通怪分支不碰它，正常跑）。
   2. `eff_reaction` 引用 `REACTION_TABLE`，真源**从未导入**（全仓唯一赋值处 =
      `game/data/battle_config.py:147`，无注入点）→ 调用即 `NameError`。
   3. 真源自述 `POTION_EFFECTS 现无消费端`（旧引擎 `battle.py` 的 `_apply_potion_special`
      随 N10 删除；唯一调用方在 `_archive_unused/retired_old_engine_20260911/`）——
      本层当前**无 live 消费端**，进包后等 saintess_engine 战斗消耗品线接线。
"""

import json
import os

# ============================================================
# ★ 2026-09-24 B7b：本文件**不再 import 数据包**（抽包进 `extends/ext_effect/` 的前置）
#   三样读口全部改成**调用方注入**（模块级 `bind()`，装配期一次）：
#
#     _T.text / _T.static   ← 文案渲染（真源 = 数据包 `content/texts.py`）
#     _items_domain()       ← items 域（真源 = `content/data/items.json`，单一权威）
#     _effect_rules()       ← EFFECT_RULES（真源 = `content/rules/effect_rules.json`）
#     _purify_neg_keys()    ← 净化负面键清单（真源 = `content/data/purify_neg_keys.json`）
#
#   为什么是模块级而不是 ctx：本层 handler 签名是 `(battle, player, value)`（没有 ctx），
#   73 个渲染点分散在 36 个 handler 里 ⇒ 挂模块级句柄才能**让 73 个调用点一字不改**。
#   包内同款先例：`content/obs.py` 的 `bind(log=…)`。
#   未绑定就取用 = **当场报错**（fail-loud，绝不静默给空表/空串）。
# ============================================================

#: 注入面：`{"text","static","items","rules","neg_keys"}`（getter 形态，首次取用即缓存）
_INJ: dict | None = None


class _TextProxy:
    """文案句柄代理：绑定前**任何取用都报错**（fail-loud，不静默给空串）。

    绑定后按名字转给注入的函数（`_INJ["text"]` / `_INJ["static"]`）；
    代理是**同一个对象**（不重新绑定 `_T`），所以 73 个 `_T.text(...)` 调用点零改动。
    """

    def __getattr__(self, name):
        if name not in ("text", "static"):
            raise AttributeError(name)
        if _INJ is None:
            raise RuntimeError(
                "potion 文案注入面缺失：装配期需 `potion_effects.bind(text=…, static=…)`"
                "（数据包侧装配点见 `content/effects/__init__.py::bind_effects`）")
        return _INJ[name]()

    def __repr__(self):
        return "<potion_effects._T %s>" % ("未绑定" if _INJ is None else "已绑定")


_T = _TextProxy()


def _as_getter(value):
    """dict 或 callable 都收：callable = 「首次使用时取一次」并缓存（与搬前同款惰性）。"""
    if callable(value):
        cache = {}

        def _get():
            if "v" not in cache:
                cache["v"] = value()
            return cache["v"]
        return _get
    return lambda: value


def _inj(key: str):
    if _INJ is None:
        raise RuntimeError(
            "potion 注入面未装配：先 `potion_effects.bind(text=…, static=…, items=…,"
            " rules=…, neg_keys=…)`（数据包装配点 `content/effects/__init__.py::bind_effects`）")
    return _INJ[key]()


def bind(*, text, static, items, rules, neg_keys):
    """装配期由数据包调用一次（幂等）：把文案渲染与三张表交进来。

    * `text` / `static`：文案渲染函数（真源 = 数据包文案表）。
    * `items` / `rules` / `neg_keys`：域表，**dict 或 callable 都收**
      （callable = 首次使用时取并缓存 —— 与搬前「惰性读盘一次」同语义）。
    * `neg_keys` 在 bind 时就**读一次并校验形状**（搬前是 import 期校验 ⇒ 保持 fail-fast）。
    * `DEFAULTS` **就地刷新**（`clear()+update()`）：消费方 `from … import DEFAULTS` 拿到的
      是同一个 dict 对象，bind 之后立刻可见（不重新绑定名字，避免留下旧对象）。
    """
    global _INJ
    _INJ = {"text": lambda: text, "static": lambda: static,
            "items": _as_getter(items), "rules": _as_getter(rules),
            "neg_keys": _as_getter(neg_keys)}
    _purify_neg_keys()                      # 形状校验在装配期发生（fail-fast）
    DEFAULTS.clear()
    DEFAULTS.update(_scan_defaults())


def _items_domain() -> dict:
    """items 域（真源 = `content/data/items.json`，**由调用方注入**）—— 药水 `effect_data` 的单一权威。"""
    return _inj("items")


def _effect_rules() -> dict:
    """EFFECT_RULES（真源 = `content/rules/effect_rules.json`，**由调用方注入**）——
    资源位 `name` / `cap` / `start_classes`。"""
    return _inj("rules")


def _purify_neg_keys() -> tuple:
    """净化负面键清单（真源 = `content/data/purify_neg_keys.json`，**由调用方注入**）。

    形状校验与搬前逐字同款（缺 / 空 / 键型不符 ⇒ 抛，拒绝静默空表）；序 = 表内序
    （净化回显按此序 join）。
    """
    tbl = _inj("neg_keys")
    ent = tbl.get("purify_neg_keys") if isinstance(tbl, dict) else None
    if not isinstance(ent, dict) or not isinstance(ent.get("keys"), list) or not ent["keys"]:
        raise RuntimeError(
            "purify_neg_keys 域缺 / 空 / 键型不符（应注入 {\"purify_neg_keys\":"
            " {\"keys\": [...]}}）—— 拒绝静默空表")
    return tuple(ent["keys"])


POTION_EFFECTS = {}


def register(name):
    """效果注册装饰器。"""
    def deco(fn):
        POTION_EFFECTS[name] = fn
        return fn
    return deco


# effect → 注册表 kind 别名（与 core/item_templates.py _BUFF_KEYS special 映射同口径；
# 3 个物品 effect 名 ≠ 注册表键名，扫描默认值时需对齐）
_EFFECT_KIND = {
    "armor_break_pot": "def_down",
    "rock_shield": "shield_small",
    "holy_shield": "shield_big",
}


def _scan_defaults():
    """从包内 items 域药水 effect_data 扫描各效果默认数值（items 域 = 数值单一权威）。
    同 effect 多物品共用一套数值（数据约定一致），首个命中为准。

    ⚠️ 真源 `from ..data.items import ITEMS`（宿主数据域 Python 表）→ 包内单源 =
    `content/data/items.json`（导出物；门禁 B0 实测 900 条 keys 与 `effect` /
    `effect_data` 逐项相等）。读不到 / 坏 JSON → `{}`（与真源「扫描不到」同语义）。
    """
    ITEMS = _items_domain()
    out = {}
    for _d in ITEMS.values():
        ed = _d.get("effect_data")
        if not isinstance(ed, dict) or not ed:
            continue
        kind = _EFFECT_KIND.get(_d.get("effect"), _d.get("effect"))
        if kind and kind not in out:
            out[kind] = ed
    return out


#: 药水默认表（**bind() 时就地刷新**；未装配时为空 dict，取用处 `_resolve()` 会 fail-loud）
DEFAULTS: dict = {}


def _resolve(value, kind):
    """value（物品级 effect_data）缺省回退 DEFAULTS[kind]。

    ★ B7b：未装配（`DEFAULTS` 还是空表）时**报错**，不静默返回空 —— 空表会让「药水没效果」
    变成静默失效（最难查的一类）。
    """
    if _INJ is None:
        raise RuntimeError("potion 注入面未装配：DEFAULTS 尚不可用（见 potion_effects.bind）")
    if isinstance(value, dict) and value:
        return value
    return DEFAULTS.get(kind, {}) or {}


# ================= 效果实现 =================

@register("next_atk_up")
def eff_next_atk_up(battle, player, value):
    """狂怒药剂/月露精华/彩虹药剂/黑羽箭：下一次攻击 +50%（一次性，普攻/技能消费）。"""
    v = _resolve(value, "next_atk_up")
    pct = float(v.get("pct", 0.5))
    player.setdefault('buffs', {})["next_atk_up"] = int(v.get("turns", 1))
    return _T.text("potion.next_atk_up", pct=int(pct * 100))


@register("heal_up")
def eff_heal_up(battle, player, value):
    """圣光药剂：治疗技能效果 +20%（3 刻）。"""
    v = _resolve(value, "heal_up")
    pct = float(v.get("pct", 0.2))
    player.setdefault('buffs', {})["heal_up"] = int(v.get("turns", 3))
    return _T.text("potion.heal_up", pct=int(pct * 100))


@register("magic_resist")
def eff_magic_resist(battle, player, value):
    """龙鳞药剂/深渊药剂：受到魔法伤害 －15%（3 刻）。"""
    v = _resolve(value, "magic_resist")
    pct = float(v.get("pct", 0.15))
    player.setdefault('buffs', {})["magic_resist"] = int(v.get("turns", 3))
    return _T.text("potion.magic_resist", pct=int(pct * 100))


@register("thorns_pot")
def eff_thorns_pot(battle, player, value):
    """荆棘药剂：受击反弹 30% 伤害（3 刻）。"""
    v = _resolve(value, "thorns_pot")
    pct = float(v.get("pct", 0.30))
    player.setdefault('buffs', {})["thorns_pot"] = int(v.get("turns", 3))
    return _T.text("potion.thorns_pot", pct=int(pct * 100))


@register("dodge_pot")
def eff_dodge_pot(battle, player, value):
    """影步药剂：15% 概率闪避攻击（3 刻，乘算并入闪避结算）。"""
    v = _resolve(value, "dodge_pot")
    pct = float(v.get("pct", 0.15))
    player.setdefault('buffs', {})["dodge_pot"] = int(v.get("turns", 3))
    return _T.text("potion.dodge_pot", pct=int(pct * 100))


@register("cc_immune")
def eff_cc_immune(battle, player, value):
    """不动药剂：免疫眩晕/冻结/减速（3 刻）。"""
    v = _resolve(value, "cc_immune")
    player.setdefault('buffs', {})["cc_immune"] = int(v.get("turns", 3))
    return _T.static("potion.cc_immune")


@register("execute_pot")
def eff_execute_pot(battle, player, value):
    """死神药剂：对生命<30% 的敌人 +30% 伤害（3 刻）。"""
    v = _resolve(value, "execute_pot")
    pct = float(v.get("pct", 0.30))
    th = float(v.get("hp_threshold", 0.30))
    player.setdefault('buffs', {})["execute_pot"] = int(v.get("turns", 3))
    return _T.text("potion.execute_pot", hp_th=int(th * 100), pct=int(pct * 100))


@register("def_down")
def eff_def_down(battle, player, value):
    """破甲药剂：敌人防御下降 15%（2 刻，_armor_break_pct 供防御结算）。

    v180-D P3：动作收敛到共享 effect_actions.action_def_down（原 potion 自写一份
    与 affix/food 同语义实现——统一一套效果动作代码）。
    """
    v = _resolve(value, "def_down")
    pct = float(v.get("pct", 0.15))
    turns = int(v.get("turns", 2))
    # 真源 `from .effect_actions import action_def_down`（共享效果动作，改敌方 actor 状态）→
    # 包内该模块未进包，改走调用方传入的战斗替身接口 battle.action_def_down（见文件头 ③）
    _scratch = []
    battle.action_def_down(_scratch, turns=turns, pct=pct, target=battle._hit_tgt())
    return _T.text("potion.def_down", pct=int(pct * 100), turns=turns)


@register("pene_pot")
def eff_pene_pot(battle, player, value):
    """穿甲药剂：物穿 +15%（3 刻，与属性乘算）。"""
    v = _resolve(value, "pene_pot")
    pct = float(v.get("pct", 0.15))
    player.setdefault('buffs', {})["pene_pot"] = int(v.get("turns", 3))
    return _T.text("potion.pene_pot", pct=int(pct * 100))


@register("pene_magi_pot")
def eff_pene_magi_pot(battle, player, value):
    """破法药剂：法穿 +15%（3 刻，与属性乘算）。"""
    v = _resolve(value, "pene_magi_pot")
    pct = float(v.get("pct", 0.15))
    player.setdefault('buffs', {})["pene_magi_pot"] = int(v.get("turns", 3))
    return _T.text("potion.pene_magi_pot", pct=int(pct * 100))


@register("lifesteal_pot")
def eff_lifesteal_pot(battle, player, value):
    """嗜血药剂：吸血 +15%（3 刻，乘算并入 _settle_lifesteal）。"""
    v = _resolve(value, "lifesteal_pot")
    pct = float(v.get("pct", 0.15))
    player.setdefault('buffs', {})["lifesteal_pot"] = int(v.get("turns", 3))
    return _T.text("potion.lifesteal_pot", pct=int(pct * 100))


@register("crit_dmg_pot")
def eff_crit_dmg_pot(battle, player, value):
    """狂暴药剂：暴击伤害 +25%（3 刻，乘算并入暴击结算）。"""
    v = _resolve(value, "crit_dmg_pot")
    pct = float(v.get("pct", 0.25))
    player.setdefault('buffs', {})["crit_dmg_pot"] = int(v.get("turns", 3))
    return _T.text("potion.crit_dmg_pot", pct=int(pct * 100))


@register("block_pot")
def eff_block_pot(battle, player, value):
    """岩壁药剂：格挡 +15%（3 刻，乘算并入受击格挡）。"""
    v = _resolve(value, "block_pot")
    pct = float(v.get("pct", 0.15))
    player.setdefault('buffs', {})["block_pot"] = int(v.get("turns", 3))
    return _T.text("potion.block_pot", pct=int(pct * 100))


@register("shield_small")
def eff_shield_small(battle, player, value):
    """岩盾药剂：获得 max_hp × 10% 护盾（3 刻）。"""
    v = _resolve(value, "shield_small")
    pct = float(v.get("pct", 0.10))
    gain = int(player.get("max_hp", 100) * pct)
    battle._add_shield("potion", gain, int(v.get("turns", 3)))
    return _T.text("potion.shield_small", gain=gain)


@register("shield_big")
def eff_shield_big(battle, player, value):
    """圣盾药剂：获得 max_hp × 15% 护盾（3 刻）。"""
    v = _resolve(value, "shield_big")
    pct = float(v.get("pct", 0.15))
    gain = int(player.get("max_hp", 100) * pct)
    battle._add_shield("potion", gain, int(v.get("turns", 3)))
    return _T.text("potion.shield_big", gain=gain)


# ================= v130.2 资源联动消耗品（7 类新 effect handler） =================
# 消费端：items.py 尾部 19 件资源联动消耗品（i_rage_draught ~ i_surging_brew）。
# handler 签名统一 fn(battle, player, value)：battle=Battle 实例、player=玩家 dict、
# value=物品级 effect_data（由 item_templates 注入 special payload；旧特殊药水无数据 → None 走 DEFAULTS）。
# 资源值/刻类效果挂 p_buffs + p_eff{battle}（持久数据），引擎侧触发点消费。
# 职业校验统一走 battle._branch_keys（B1 分支级 resource_override，v130.2）。


def _item_res_def(key: str) -> dict:
    """按资源 key 查资源定义（v181.M-R2b：单源 = EFFECT_RULES 条目 name/cap；
    旧 core_resource_def_by_key（core_resources.py 表，文件本体已随 v181.M-R2c 退役）退役迁移。未注册 key → {}，与旧兜底同）。"""
    try:
        _ER = _effect_rules()          # 真源 `from ..data.battle_rules import EFFECT_RULES`
        _r = _ER.get(key) or {}
        if not _r:
            return {}
        return {"key": key, "name": _r.get("name") or key,
                "max": int(_r.get("cap", 0) or 0)}  # cap ↔ 旧 max（怒气 10/精力 100/… 同值）
    except Exception:
        return {}


def _res_mine(battle, player, key: str) -> bool:
    """玩家职业/转职分支是否持有该资源位（如时之沙仅时咒法师、怒气仅战士）。"""
    return bool(key) and key in battle._branch_keys(player)


@register("restore_resource")
def eff_restore_resource(battle, player, value):
    """v130.2 回资源类消耗品：立即回复核心资源。
    effect_data {key, amount, cooldown?, once_per_battle?, next_heal_pct?}
    支持：cooldown（叠加冷却，圣辉药剂 2 刻）/ once_per_battle（瞬步结晶每场限 1 次）/
    next_heal_pct（信仰结晶：下个治疗增强，_skill_heal 消费一次）。
    职业不符（如非时咒法师用时之沙漏）→ 无效无消耗。"""
    v = _resolve(value, "restore_resource")
    key = v.get("key", "")
    amount = int(v.get("amount", 0) or 0)
    if not key or amount <= 0:
        return _T.static("potion.cfg_error")
    if not _res_mine(battle, player, key):
        return _T.static("potion.wrong_class_potion")
    # once_per_battle：每场限 1 次（战斗内资源 key 作标记，key 唯一性保证不重复）
    once = bool(v.get("once_per_battle"))
    if once:
        _used = player.setdefault('eff', {}).setdefault("once_restore", [])
        if key in _used:
            return _T.static("potion.once_used_potion")
    # cooldown：叠加冷却（同资源位独占）
    cd = int(v.get("cooldown", 0) or 0)
    _cdk = "item_cd_" + key
    if cd > 0 and int(player.setdefault('cooldown', {}).get(_cdk, 0) or 0) > 0:
        return _T.text("potion.cd_waiting", left=int(player.setdefault('cooldown', {}).get(_cdk, 0) or 0))
    rd = _item_res_def(key)
    new = battle._res_gain(player, key, amount)
    if once:
        player.setdefault('eff', {}).setdefault("once_restore", []).append(key)
    if cd > 0:
        player.setdefault('cooldown', {})[_cdk] = cd
    msg = _T.text("potion.res_gain", name=rd.get('name', key), amount=amount, cur=new,
              cap=rd.get('max', '?'))
    nh = v.get("next_heal_pct")
    if nh:
        pn = float(nh)
        player.setdefault('eff', {})["next_heal_up"] = pn
        msg += _T.text("potion.next_heal_up", pct=int(pn * 100))
    return msg


@register("restore_resource_full")
def eff_restore_resource_full(battle, player, value):
    """v130.2 熔核之心：立即充满核心资源 + 战损代价（penalty_pct% 全减伤，penalty_turns 刻）。
    effect_data {key, penalty_pct, penalty_turns}——全减伤负值 = 受击 +X%（battle.py reduce_all 槽消费）。"""
    v = _resolve(value, "restore_resource_full")
    key = v.get("key", "")
    if not _res_mine(battle, player, key):
        return _T.static("potion.wrong_class_supply")
    rd = _item_res_def(key)
    cap = int(rd.get("max", 0))
    battle._res_gain(player, key, cap)  # 充满到 max（_res_gain 自带封顶）
    penalty = float(v.get("penalty_pct", 0.0) or 0)
    turns = max(1, int(v.get("penalty_turns", v.get("turns", 2)) or 2))
    if penalty > 0:
        # 战损交易：全减伤 -penalty%（负值 reduce_all → _damage_actor 受击 +X%）
        player.setdefault('buffs', {})["reduce_all"] = -penalty
        player['reduce_all_left'] = turns
        return (_T.text("potion.nucleus_full_cost", name=rd.get('name', key), cur=cap, cap=cap, turns=turns,
                    pct=int(penalty * 100)))
    return _T.text("potion.nucleus_full", name=rd.get('name', key), cur=cap, cap=cap)


@register("resource_amp")
def eff_resource_amp(battle, player, value):
    """v130.2 资源增幅：特定触发下每次额外 +amount 资源（持续 turns 刻或 hits 次出手）。
    effect_data {key, amount, turns/hits, trigger}
    trigger ∈ {on_hit 受击 / 出手命中(hits 制) / on_heal 治疗 / regen 自然回复}，
    引擎侧触发点消费（battle.py _amp_resource 各站点；战斗外待用经 _init_resources 挂载）。
    沸血战血 turns+on_hit(受击)、影袭药水 hits+on_hit(出手命中)、迅捷之核 turns+regen、
    香薰圣烛 turns+on_heal（战斗外点燃 → 战前待用队列）。"""
    v = _resolve(value, "resource_amp")
    key = v.get("key", "")
    amount = int(v.get("amount", 0) or 0)
    trigger = v.get("trigger", "")
    turns = int(v.get("turns", 0) or 0)
    hits = int(v.get("hits", 0) or 0)
    if not key or amount <= 0 or not trigger:
        return _T.static("potion.cfg_error")
    if not _res_mine(battle, player, key):
        return _T.static("potion.wrong_class_potion")
    amps = player.setdefault('eff', {}).setdefault("amps", {})
    prev = amps.get(key) or {}
    amps[key] = {
        "key": key, "amount": amount, "trigger": trigger,
        "turns_left": max(int(prev.get("turns_left", 0) or 0), turns),
        "hits_left": max(int(prev.get("hits_left", 0) or 0), hits),
    }
    rd = _item_res_def(key)
    _tcn = {"on_hit": "受击/出手", "on_heal": "治疗", "regen": "自然回复"}.get(trigger, trigger)
    if hits:
        return _T.text("potion.amp_hits", hits=hits, name=rd.get('name', key), amount=amount)
    return _T.text("potion.amp_turns", turns=turns, trigger=_tcn, name=rd.get('name', key), amount=amount)


@register("mana_cost_down")
def eff_mana_cost_down(battle, player, value):
    """v130.2 元素亲和药剂：技能魔力消耗 ×(1-pct) 持续 turns 刻（基础法师纯蓝减耗）。
    effect_data {pct, turns}——p_buffs 刻计数 + p_eff 存 pct，battle.py 技能耗蓝结算消费。"""
    v = _resolve(value, "mana_cost_down")
    pct = float(v.get("pct", 0.0) or 0)
    turns = int(v.get("turns", 3) or 3)
    if pct <= 0:
        return _T.static("potion.cfg_error")
    player.setdefault('buffs', {})["mana_cost_down"] = max(int(player.setdefault('buffs', {}).get("mana_cost_down", 0) or 0), turns)
    player.setdefault('eff', {})["mana_cost_down"] = pct
    return _T.text("potion.mana_cost_down", pct=int(pct * 100), turns=turns)


@register("buff_phys_next")
def eff_buff_phys_next(battle, player, value):
    """v130.2 引气精华：下一次物理/气力技 伤害 +pct%（一次性，物理技能伤害结算消费）。
    effect_data {pct}——p_buffs 一次性标记 + p_eff 存 pct（同 next_atk_up 豁免刻递减）。"""
    v = _resolve(value, "buff_phys_next")
    pct = float(v.get("pct", 0.0) or 0)
    if pct <= 0:
        return _T.static("potion.cfg_error")
    player.setdefault('buffs', {})["buff_phys_next"] = 1
    player.setdefault('eff', {})["buff_phys_next"] = pct
    return _T.text("potion.buff_phys_next", pct=int(pct * 100))


@register("full_tension")
def eff_full_tension(battle, player, value):
    """v130.2 满弦烈酒：立即进入满弦状态 turns 刻（精力≥80 阈值视为已满足）。
    effect_data {turns}——守线·风行者系专属（风行者/疾风射手/疾风猎手），其余职业无效。
    p_buffs[\"full_tension\"] 供 _energy_high_crit 满弦判定短路。"""
    v = _resolve(value, "full_tension")
    turns = int(v.get("turns", 1) or 1)
    if not battle._is_branch_of(player, "风行者", "疾风射手", "疾风猎手"):
        return _T.static("potion.full_tension_wrong_class")
    player.setdefault('buffs', {})["full_tension"] = max(int(player.setdefault('buffs', {}).get("full_tension", 0) or 0), turns)
    return _T.text("potion.full_tension", turns=turns)


@register("battle_start_resource")
def eff_battle_start_resource(battle, player, value):
    """v130.2 战前资源预充（战前猛火餐/夜枭茶/澎湃烈酒）：战斗开始时预充资源。
    effect_data {key, amount, buff?{kind, pct, turns}}
    大宗走战前待用队列（item_templates 战斗外使用 → event_state prebattle_{qq_id} ，
    _init_resources 战斗初始化段注入）；此处为战斗内兜底分发（战斗中饮用按同口径立即预充）。"""
    v = _resolve(value, "battle_start_resource")
    key = v.get("key", "")
    amount = int(v.get("amount", 0) or 0)
    if not key or amount < 0:
        return _T.static("potion.cfg_error_short")
    if not _res_mine(battle, player, key):
        return _T.static("potion.wrong_class_drink")
    msgs = []
    if amount > 0:
        rd = _item_res_def(key)
        new = battle._res_gain(player, key, amount)
        msgs.append(f"{rd.get('name', key)} +{amount}({new}/{rd.get('max', '?')})")
    bf = v.get("buff")
    if isinstance(bf, dict) and bf.get("kind") == "phys_up":
        _pct = float(bf.get("pct", 0.05) or 0)
        _t = int(bf.get("turns", 3) or 3)
        player.setdefault('buffs', {})["phys_up"] = max(int(player.setdefault('buffs', {}).get("phys_up", 0) or 0), _t)
        player.setdefault('eff', {})["phys_up"] = max(float(player.setdefault('eff', {}).get("phys_up", 0) or 0), _pct)
        msgs.append(_T.text("potion.phys_up_buff", pct=int(_pct * 100), turns=_t))
    if not msgs:
        return _T.static("potion.no_effect")
    return _T.static("potion.prebattle_ok") + "、".join(msgs) + "！"


# ================= v140 战斗机制道具（20 件）效果 handler =================
# 消费端：items.py 尾部 20 件战斗机制道具（i_jin_ling_xiang_lu ~ i_ruo_dian_ji_po_shi，
# 方案 3.6：召唤/陷阱控制/资源节奏/特殊机制/组合爆发五类）。
# handler 签名统一 fn(battle, player, value)：battle=Battle 实例、player=玩家 dict、
# value=物品级 effect_data（由 item_templates 注入 special:<kind>:<json> payload）。
# 复用优先：冻结/沉默/眩晕走 CONTROL_MECHS（enemy buffs 由 _enemy_turn 消费）、
# 护盾走 _add_shield、减伤走 reduce_all、持续回血走 p_hot（_apply_hot 消费）、
# 破防走 mon_atk_down（_enemy_stats 消费）、反应倍率走 _elem_reaction_boost
# （_reaction_table_resolve 消费）、印记走 _elem_mark_apply（引爆技反应表消费）。
# 无消费点的纯标记效果（phoenix/invuln/morph 等）按 v140 收口约定先挂 p_eff/p_buffs
# 标记（后续引擎消费端接线），确保『使用』不落 tpl_none 死数据。

@register("summon")
def eff_summon(battle, player, value):
    """v140 召唤类消耗品（烬灵香炉/圣徽替身像/荆棘傀儡种/战地医者魔偶）。

    ⚠️ 未接入战斗结算（显式拒绝，非静默兜底）：召唤实体装配需要随从 actor
    工厂 + auto_act/guard 一套；旧装配函数随 N10 删旧 battle.py 一并消失，
    saintess_engine 侧尚无随从装配（Battle.add_actor 只做注册/索引/排程，不含随从
    属性缩放与守卫装配）。本 handler 在 saintess_engine 下不可达——战斗内 summon 类
    在 commands/battle_item_use.can_translate 白名单外，使用前即被拦并提示
    「战斗内效果未迁移」。复活路径见 docs/archive/REFACTOR_v181_GAP_CLOSURE_PLAN.md
    §2（随从线）与 §5（收尾项）。
    """
    return _T.static("potion.summon_unimpl")


@register("trap")
def eff_trap(battle, player, value):
    """v140 陷阱/控制类消耗品（霜寒捕兽夹/沉默封咒蜡/缴械绳网/魅惑魔粉）：
    ctrl 控制写入敌方 buffs（freeze/stun/silence 由 _enemy_turn 行动级消费，
    与 CONTROL_MECHS 白名单同口径）；Boss 降级/缴械/魅惑自伤走既有敌方攻击
    减益槽（mon_atk_down + _weaken_val 由 _enemy_stats 消费）。"""
    v = _resolve(value, "trap")
    ctrl = v.get("ctrl", "")
    turns = max(1, int(v.get("turns", 1) or 1))
    if ctrl not in ("stun", "freeze", "silence"):
        return _T.static("potion.trap_cfg_error")
    e = battle._hit_tgt() or {}
    is_boss = bool(e.get("is_boss") or e.get("role") == "boss")
    eb = e.setdefault("buffs", {})
    msgs = []
    # 魅惑魔粉：Boss 免疫（降级为降攻 boss_downgrade）；普通怪按原控制生效
    if ctrl == "charm":
        return _T.static("potion.charm_unimpl")
    if is_boss:
        dg = v.get("boss_downgrade")
        if isinstance(dg, str):  # 霜寒捕兽夹：Boss 冻结降级为减速
            eb["spd_down"] = max(int(eb.get("spd_down", 0) or 0), turns)
            msgs.append(_T.text("potion.trap_boss_downgrade", turns=turns))
        elif isinstance(dg, (int, float)):  # 沉默封咒蜡/魅惑：Boss 成功率
            if random.random() < float(dg):
                eb[ctrl] = max(int(eb.get(ctrl, 0) or 0), turns)
                msgs.append(_T.text("potion.trap_ctrl_ok", who='冻结' if ctrl == 'freeze' else '沉默', turns=turns))
            else:
                msgs.append(_T.text("potion.trap_boss_resist", pct=int(float(dg) * 100)))
        else:
            eb[ctrl] = max(int(eb.get(ctrl, 0) or 0), turns)
            msgs.append(_T.static("potion.trap_ctrl_plain"))
    else:
        eb[ctrl] = max(int(eb.get(ctrl, 0) or 0), turns)
        msgs.append(_T.text("potion.trap_enemy_ctrl",
                        who='冻结' if ctrl == 'freeze' else '眩晕' if ctrl == 'stun' else '沉默',
                        turns=turns))
    # 缴械绳网：普攻伤害 -atk_reduce%（mon_atk_down 槽 + _weaken_val 数值）
    ar = float(v.get("atk_reduce", 0) or 0)
    if ar > 0:
        eb["mon_atk_down"] = max(int(eb.get("mon_atk_down", 0) or 0), 1)
        eb["_weaken_val"] = min(0.9, ar)
        msgs.append(_T.text("potion.trap_disarm", pct=int(ar * 100)))
    if not msgs:
        return _T.static("potion.trap_no_effect")
    return "⚔️ " + "，".join(msgs)


@register("mana_restore")
def eff_mana_restore(battle, player, value):
    """v140 圣泉源泉瓶：回复 mana_pct% 最大法力（直接改 player 快照，与 mana 模板同源）
    + 技能消耗 -cost_reduce% 持续 turns 刻（mana_cost_down 由技能施放结算消费）。"""
    v = _resolve(value, "mana_restore")
    mp_pct = float(v.get("mana_pct", 0.25) or 0)
    gain = int(player.get("max_mp", 0) * mp_pct)
    before = player.get("mp", 0)
    player["mp"] = min(player.get("max_mp", player["mp"]), before + gain)
    msgs = [_T.text("potion.mana_gain", gain=player['mp'] - before, cur=player['mp'],
                cap=player.get('max_mp', '?'))]
    cr = float(v.get("cost_reduce", 0) or 0)
    if cr > 0:
        turns = max(1, int(v.get("turns", 2) or 2))
        player.setdefault('buffs', {})["mana_cost_down"] = max(int(player.setdefault('buffs', {}).get("mana_cost_down", 0) or 0), turns)
        player.setdefault('eff', {})["mana_cost_down"] = max(float(player.setdefault('eff', {}).get("mana_cost_down", 0) or 0), cr)
        msgs.append(_T.text("potion.mana_cost_line", pct=int(cr * 100), turns=turns))
    return "💙 " + "，".join(msgs)


@register("resource_charge")
def eff_resource_charge(battle, player, value):
    """v140 充能蒸馏器：核心资源 +res_gain（按玩家职业核心资源 key，_res_gain 带上限），
    且全部技能冷却 -cd_reduce 刻（cooldown 表直接减，_tick_cooldowns 次日递减）。"""
    v = _resolve(value, "resource_charge")
    gain = int(v.get("res_gain", 0) or 0)
    cd = int(v.get("cd_reduce", 0) or 0)
    # v181.M-R2b：旧 class→主资源单表（engine.core_resource_def）已退役——EFFECT_RULES 无
    # class→key 维度，主资源判定 = 条目 start_classes 归属（R2a energy 先例：cls_you_xia）。
    # legacy handler（v130.2/v140 旧战斗消耗品，POTION_EFFECTS 现无消费端）：按职业归属取首条
    # 资源；未归属 → 沿用旧「你的职业没有核心资源」兜底。
    _cls = player.get("class_name", "")
    rd = {}
    if _cls:
        try:
            _ER2 = _effect_rules()      # 真源 `from ..data.battle_rules import EFFECT_RULES`
            for _rk, _ru in _ER2.items():
                if _cls in ((_ru or {}).get("start_classes") or []):
                    rd = {"key": _rk, "name": (_ru.get("name") or _rk),
                          "max": int(_ru.get("cap", 0) or 0)}
                    break
        except Exception:
            rd = {}
    msgs = []
    if rd and gain > 0:
        key = rd["key"]
        new = battle._res_gain(player, key, gain)
        msgs.append(f"{rd['name']} +{gain}({new}/{rd.get('max', '?')})")
    if cd > 0 and player.setdefault('cooldown', {}):
        for k in list(player.setdefault('cooldown', {})):
            player.setdefault('cooldown', {})[k] = max(0, int(player.setdefault('cooldown', {})[k] or 0) - cd)
        msgs.append(_T.text("potion.cd_reduce", cd=cd))
    if not msgs:
        return _T.static("potion.no_core_resource")
    return "⚡ " + "，".join(msgs) + "！"


@register("steal_buff")
def eff_steal_buff(battle, player, value):
    """v140 汲魂水晶：偷取敌方 1 个增益转给自己（敌方 buffs 键 → p_buffs 同刻数）。
    敌方无增益时按 effect_data no_target_no_consume 语义不消耗（模板层已拦截）。"""
    v = _resolve(value, "steal_buff")
    e = battle._hit_tgt() or {}
    eb = e.get("buffs") or {}
    # 敌方增益候选：正向乘区/控制标记以外的 buff 键
    cand = [k for k in eb if k not in ("stun", "freeze", "silence", "sleep")
            and int(eb.get(k, 0) or 0) > 0]
    if not cand:
        return _T.static("potion.steal_none")
    k = cand[0]
    turns = max(1, int(v.get("turns", 2) or 2))
    t = eb.pop(k)
    player.setdefault('buffs', {})[k] = max(int(player.setdefault('buffs', {}).get(k, 0) or 0), int(t or turns))
    return _T.text("potion.steal_ok", buff=k, turns=int(t or turns))


@register("buff_extend")
def eff_buff_extend(battle, player, value):
    """v140 时之延香：自身全部增益时长 +extend_turns 刻（p_buffs 逐个顺延，
    _end_round 刻递减消费；一次性标记类键豁免）。"""
    v = _resolve(value, "buff_extend")
    ext = max(1, int(v.get("extend_turns", 2) or 2))
    n = 0
    for k in list(player.setdefault('buffs', {})):
        if k in ("next_atk_up", "buff_phys_next", "stealth", "reduce_all", "stun", "freeze"):
            continue
        player.setdefault('buffs', {})[k] = int(player.setdefault('buffs', {}).get(k, 0) or 0) + ext
        n += 1
    return _T.text("potion.buff_extend", n=n, turns=ext)


@register("phoenix")
def eff_phoenix(battle, player, value):
    """v140 不死鸟之羽：设置复活标记（被击倒后以 revive_hp% 生命复活 1 次，
    复活后 turns 刻减伤 dmg_reduce%——标记存 p_eff 由战斗引擎死亡结算消费；
    本版按 v140 收口先挂标记，消费端接线属引擎批次）。"""
    v = _resolve(value, "phoenix")
    if player.setdefault('eff', {}).get("phoenix_used"):
        return _T.static("potion.phoenix_used")
    player.setdefault('eff', {})["phoenix_used"] = True
    player.setdefault('eff', {})["phoenix_revive"] = {
        "hp": float(v.get("revive_hp", 0.30) or 0.30),
        "dmg_reduce": float(v.get("dmg_reduce", 0.20) or 0.20),
        "turns": max(1, int(v.get("turns", 3) or 3)),
    }
    return _T.text("potion.phoenix", pct=int(float(v.get('revive_hp', 0.30)) * 100))


@register("purify_immune")
def eff_purify_immune(battle, player, value):
    """v140 圣光净水：净化全部负面状态（p_buffs 负向键清除，与净化卷轴同口径）
    + turns 刻免疫 silence/stun（cc_immune 免疫槽，供引擎控制结算消费）。"""
    v = _resolve(value, "purify_immune")
    turns = max(1, int(v.get("turns", 3) or 3))
    neg = _purify_neg_keys()   # ★ D9/B7b：键清单 = 调用方注入的 purify_neg_keys 域
    cleared = [k for k in neg if k in player.setdefault('buffs', {})]
    for k in cleared:
        player.setdefault('buffs', {}).pop(k, None)
    if "reduce_all" in cleared:
        player['reduce_all_left'] = 0
    player.setdefault('buffs', {})["cc_immune"] = max(int(player.setdefault('buffs', {}).get("cc_immune", 0) or 0), turns)
    msg = _T.static("potion.purify_head") + ("、".join(cleared) + _T.static("potion.purify_done") if cleared else _T.static("potion.purify_none"))
    return msg + _T.text("potion.purify_immune_suffix", turns=turns)


@register("morph")
def eff_morph(battle, player, value):
    """v140 龙血变身药剂：变身 turns 刻攻/魔攻 +30%（atk_up/matk_up_pot 既有 buff 槽），
    受击伤害 +15%（dmg_taken_up 标记存 p_eff，引擎受击结算消费）。"""
    v = _resolve(value, "morph")
    turns = max(1, int(v.get("turns", 3) or 3))
    if player.setdefault('eff', {}).get("morph_used"):
        return _T.static("potion.morph_used")
    player.setdefault('eff', {})["morph_used"] = True
    player.setdefault('buffs', {})["atk_up"] = max(int(player.setdefault('buffs', {}).get("atk_up", 0) or 0), turns)
    player.setdefault('buffs', {})["matk_up_pot"] = max(int(player.setdefault('buffs', {}).get("matk_up_pot", 0) or 0), turns)
    player.setdefault('eff', {})["morph_dmg_taken"] = float(v.get("dmg_taken_up", 0.15) or 0.15)
    return _T.text("potion.morph", turns=turns, pct=int(float(v.get('dmg_taken_up', 0.15)) * 100))


@register("invuln")
def eff_invuln(battle, player, value):
    """v140 次元门扉符：无敌 1 刻免疫一切伤害（invuln 标记存 p_eff，引擎受击结算消费；
    下刻无法行动僵直 stun_after 一并登记）。"""
    v = _resolve(value, "invuln")
    if player.setdefault('eff', {}).get("invuln_used"):
        return _T.static("potion.invuln_used")
    player.setdefault('eff', {})["invuln_used"] = True
    player.setdefault('eff', {})["invuln"] = {"turns": max(1, int(v.get("turns", 1) or 1)),
                              "stun_after": int(v.get("stun_after", 1) or 1)}
    return _T.static("potion.invuln")


@register("apply_mark")
def eff_apply_mark(battle, player, value):
    """v140 元素引爆剂：对目标施加 stacks 层元素印记（_elem_mark_apply 写目标
    element_marks，引爆技反应表 REACTION_TABLE 消费），并提升下次元素反应
    倍率 ×react_bonus（_elem_reaction_boost 由 _reaction_table_resolve 消费）。"""
    v = _resolve(value, "apply_mark")
    mark = v.get("mark", "")
    stacks = max(1, int(v.get("stacks", 1) or 1))
    if mark not in ("fire", "ice", "thunder"):
        return _T.static("potion.mark_cfg_error")
    new = battle._elem_mark_apply(mark, layers=stacks, player=player)
    rb = float(v.get("react_bonus", 0) or 0)
    if rb > 0:
        battle._elem_reaction_boost = max(float(getattr(battle, "_elem_reaction_boost", 1.0) or 1.0), rb)
    cn = {"fire": "火", "ice": "冰", "thunder": "雷"}[mark]
    msg = _T.text("potion.mark_apply", stacks=stacks, elem=cn, cur=new)
    if rb > 0:
        msg += _T.text("potion.mark_react_bonus", mult=rb)
    return msg


@register("dot_amp")
def eff_dot_amp(battle, player, value):
    """v140 连携增幅墨：turns 刻内每次命中使目标毒/灼烧/流血层数 +layer_per_hit
    （标记存 p_eff，命中叠层消费端属引擎批次；当前刻直接为目标已有点 dot 各 +1 层）。"""
    v = _resolve(value, "dot_amp")
    turns = max(1, int(v.get("turns", 2) or 2))
    per = max(1, int(v.get("layer_per_hit", 1) or 1))
    player.setdefault('eff', {})["dot_amp"] = {"turns_left": turns, "layer_per_hit": per}
    e = battle._hit_tgt() or {}
    deb = e.setdefault("debuffs", {})
    n = 0
    for k in ("poison", "burn", "bleed"):
        if deb.get(k, {}).get("n", 0):
            d = deb.setdefault(k, {"n": 0, "mult": 1.0})
            d["n"] = int(d.get("n", 0) or 0) + per
            n += 1
    msg = _T.text("potion.dot_amp", turns=turns, per=per)
    if n:
        msg += _T.text("potion.dot_amp_layers", n=n, per=per)
    return msg + "！"


@register("reaction")
def eff_reaction(battle, player, value):
    """v140 元素共鸣石：直接引爆目标印记触发元素反应（遍历目标 element_marks，
    按 REACTION_TABLE 任一组可反应组合结算——蒸发/超载/冻结/感电，含倍率/清印/特效）；
    无印记则造成 fallback_matk% 魔攻伤害（_deal_damage 直接结算）。"""
    v = _resolve(value, "reaction")
    marks = battle._elem_marks()
    hit = None
    for cast_el, mark_el in REACTION_TABLE:
        if int(marks.get(mark_el, 0) or 0) > 0:
            hit = (cast_el, mark_el)
            break
    if hit is not None:
        rr = battle._reaction_table_resolve(player, hit[0], battle._player_stats(player), [])
        if rr is not None:
            rmult, rlog, chain = rr
            msg = _T.text("potion.reaction_boom", log=rlog)
            if chain:
                msg += _T.static("potion.reaction_chain")
            return msg
    fb = float(v.get("fallback_matk", 0.90) or 0.90)
    st = battle._player_stats(player)
    dmg = max(1, int(st.get("matk", 0) * fb))
    battle._deal_damage(dmg, [])
    return _T.text("potion.reaction_fallback", pct=int(fb * 100), dmg=dmg)


@register("vuln")
def eff_vuln(battle, player, value):
    """v140 弱点击破石：目标每有 1 种负面状态，你对其伤害 +per_debuff%（上限
    max_debuff 种 +max_bonus%），持续 turns 刻——按当前敌方负面数即时结算并
    挂 p_eff 标记（引擎后续攻击结算消费持续效果）。"""
    v = _resolve(value, "vuln")
    turns = max(1, int(v.get("turns", 3) or 3))
    per = float(v.get("per_debuff", 0.12) or 0.12)
    mdb = max(1, int(v.get("max_debuff", 3) or 3))
    cap = float(v.get("max_bonus", 0.36) or 0.36)
    e = battle._hit_tgt() or {}
    neg = 0
    eb = e.get("buffs") or {}
    for k in ("freeze", "stun", "silence", "spd_down", "def_down", "mon_atk_down", "sleep"):
        if int(eb.get(k, 0) or 0) > 0:
            neg += 1
    deb = e.get("debuffs") or {}
    for k in ("poison", "burn", "bleed", "corros", "mark"):
        if int((deb.get(k) or {}).get("n", 0) or 0) > 0:
            neg += 1
    cnt = min(neg, mdb)
    bonus = min(cap, per * cnt)
    player.setdefault('eff', {})["vuln"] = {"per_debuff": per, "count": cnt, "bonus": bonus, "turns_left": turns}
    player.setdefault('buffs', {})["vuln"] = max(int(player.setdefault('buffs', {}).get("vuln", 0) or 0), turns)
    return _T.text("potion.vuln", neg=neg, pct=int(bonus * 100), turns=turns)

