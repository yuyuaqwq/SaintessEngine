# -*- coding: utf-8 -*-
"""saintess_engine 战斗内道具翻译器（v181.N5b4-5a I2）。

把旧引擎道具 payload（item_templates 模板产物，引擎无关中间语言）翻译成
saintess_engine actor 效果。核心不变式：效果全部落到 saintess_engine actor
（hp/mp/buffs/hot/shields/food_effects），只调 saintess_engine 动词
（landing.heal_actor / effects.apply_effects / actor 容器直写），
引擎零道具名词。

架构（docs/REFACTOR_v181P4_N5B5a_use_item_design.md §1/§2）：
    economy.use() 副本/野外战斗内分支
      → action_override 回调 (battle, action, actor, payload, target)
      → 本模块 translate(battle, actor, payload)
      → 返回 (logs, cast) 或 (None, None)（未覆盖 → 调用方提示不扣道具不占刻）

payload 全谱（对齐旧 battle._do_use_item 解析序）：
    "123"              绝对恢复 HP（半身人 item_effect 加成）
    "mana:N"           回蓝
    "hm:hp,mp"         双恢复
    "buff:k1,k2"       属性增益 3 刻（EFFECT_ACTIONS 查表翻译）
    "special:kind[:json]"  特殊分发（EFFECT_ACTIONS / shield 动词 / 缺口）
    "foodfx:id,id"     食物效果（落 actor["food_effects"] 容器 + shield 特判；
                       词条执行 = 装配层批，见设计 §8）
    "hot:hp%,mp%,turns"  持续恢复（写 actor["hot"]，schedule 周期结算）
    "0"                无数值（stamina 已由 economy 处理）
    ";cast:N" 尾缀     行动耗时（有 → 数字秒；无 → 1.0 对齐旧 CAST_ITEM/FOOD）

数值路径（零硬编码）：buff 族查 EFFECT_ACTIONS（game/data/battle_rules.py，
N7.5b 药水/食物别名已对齐 BUFF_MULT）；shield 族读 payload json 或
potion_effects.DEFAULTS（items.py effect_data 扫描权威）；heal 加成读
engine.race_stats。缺字段 = 无此行为。

★ B8.2 线4 端口（2026-09-13，包内 `content/mech/item_use.py`）
--------------------------------------------------------------
真源（只读，未改一行）：`game/commands/battle_item_use.py`（393 行）。
本文件 = 真源**逐字搬入**，只改「import 层」五处（正文/文案/正则/数值一字未动）：

| 真源写法 | 包内写法 | 说明 |
|---|---|---|
| `from ..content_rules.apply import ensure_engine_configured`（:52） | `from ..apply import install_engine` | 包内装配入口（同一个 `install_engine`，幂等） |
| `from ..core.potion_effects import DEFAULTS`（:58） | `from ..effects.potion_effects import DEFAULTS` | 药水默认表已进包（content/effects/potion_effects.py）；导出器实测 `items.json` effect/effect_data 逐项相等 |
| `from ..services.battle_food_proc import install_food_fx`（:162） | `from .food_proc import install_food_fx` | 食物装配层已进包（content/mech/food_proc.py，B8 端口） |
| `from ..data.food_effect_data import FOOD_EFFECT_PARAMS / FOOD_EFFECT_NAMES`（:170 :181） | `_food_params()`（读包内域 `content/data/food_effects.json`） | 数值/展示名单源；19 条与真源逐项相等（`name` 字段即 FOOD_EFFECT_NAMES） |
| `from ..content_rules.panel import race_stats`（:320） | `from ..panel import race_stats` | 面板已进包（content/panel.py，D3 批次） |

调用方契约不变（宿主命令层 `game/commands/battle_item_use.py` 薄壳再导出）：
    translate(battle, actor, payload[, target]) -> (logs, cast) | None
    can_translate(payload) -> bool
    make_override() -> callable(battle, action, actor, skill_name, target)
对拍证据：`overnight/_l4_snapshot.py`（改包前后逐字节等价）+ `_l4_dep_audit.py`（依赖同源）。
"""
from __future__ import annotations

import json
import re
from typing import Optional

from saintess_engine import config as _b2config
from saintess_engine.battle.landing import heal_actor

# payload 尾部 cast/recovery 剥离（同旧 battle._item_payload_cast 剥离正则）
_CAST_RE = re.compile(r"(?:^|[;&,])\s*(?:cast|recovery):[\d.]+")

# 默认道具耗时（对齐旧引擎 CAST_ITEM=CAST_FOOD=1.0——use_item 走绝对秒，
# 不按 spd 缩放；旧 _after_actor_ct cast_mult 直用）
_DEFAULT_CAST = 1.0


def _food_params() -> dict:
    """食物效果表（包内域 `content/data/food_effects.json`；数值 + `name` 展示名单源）。

    读口复用 `content/mech/food_proc.py` 的 `_food_params()`（同一份 JSON、同一份缓存）——
    不复制第二份读表器。真源此处读 `game/data/food_effect_data.FOOD_EFFECT_PARAMS /
    FOOD_EFFECT_NAMES`（同一张表的两半，导出器单向产出本 JSON）。
    """
    from .food_proc import _food_params as _fp
    return _fp()

def _load_effect_actions():
    """EFFECT_ACTIONS（游戏规则配置，命令层延迟加载）。"""
    from ..apply import install_engine as _eng_cfg; _eng_cfg()
    return _b2config.get_effect_actions()


def _load_potion_defaults():
    """特殊药水默认数值（items.py effect_data 扫描权威）。"""
    from ..effects.potion_effects import DEFAULTS as _D
    return _D


def _find_effect_action_name(table: dict, container_key: str) -> Optional[str]:
    """容器键（actor.buffs 里的 key，如 atk_up/food_atk_up）→ EFFECT_ACTIONS 名词。

    N7.5b 药水别名条目动作的 key 字段即 buffs 容器键（buff_atk → key=atk_up）。
    扫表反查首个命中（首现为准，数值全表一致约定）。
    """
    for name, acts in table.items():
        if not isinstance(acts, list):
            continue
        for a in acts:
            if isinstance(a, dict) and a.get("action") in ("apply", "buff") \
                    and a.get("key") == container_key:
                return name
    return None


# ------------------------------------------------------------
# 主入口
# ------------------------------------------------------------

def make_override():
    """saintess_engine action_override 回调工厂（I3：instance_battle/野外 from_state 后注入）。

    引擎 act() 遇非内置 action（use_item）问回调：签名
    (battle, action, actor, skill_name, target) -> (logs, cast)；
    logs=None → 未消费（回落「未知行动类型」，命令层不占刻不扣道具）。
    翻译器把 payload（经 skill_name 参数透传）→ 引擎动词。
    """
    def _override(battle, action, actor, skill_name, target):
        if action != "use_item":
            return None, None
        return translate(battle, actor, skill_name or "", target)
    return _override


def can_translate(payload: str) -> bool:
    """纯判定 payload 翻译器能否处理（无副作用，不建 battle/actor）。

    供 economy.use() 在 remove_item 前调用：不能翻译（机制型缺口
    summon/trap/phoenix/...）→ 提示「战斗内效果未迁移」且不扣道具不占刻。
    """
    if not payload or not str(payload).strip():
        return False
    _p = str(payload).strip()
    # 剥 cast/recovery 尾缀后判前缀
    _body = re.sub(r"(?:^|[;&,])\s*(?:cast|recovery):[\d.]+", "", _p).rstrip(";,")
    if not _body:
        return True  # 仅 cast（占刻无效果——食物体力类）
    if _body.startswith(("foodfx:", "hot:", "mana:", "hm:", "buff:", "purify:")):
        return True
    if _body.startswith("special:"):
        _k = _body[8:]
        _kind = _k.split(":", 1)[0] if ":" in _k else _k
        if _kind in _EFFECT_ACTION_KEYS or _kind in _SHIELD_KINDS:
            return True
        # 其余机制型 special → 缺口
        return False
    try:
        int(_body or "x")
        return True  # 纯数字 heal
    except ValueError:
        return False


def translate(battle, actor: dict, payload: str,
              target: Optional[dict] = None) -> Optional[tuple]:
    """道具 payload → (logs, cast)。未覆盖（机制型缺口）→ (None, None)。

    调用方（action_override 回调）收到 None → 提示「战斗内效果未迁移，
    请在战斗外使用」，不扣道具不占刻。
    """
    if not payload:
        return None
    logs: list = []
    cast = _DEFAULT_CAST
    # 剥离 cast/recovery（耗时由调用方推进，不污染效果解析）
    _payload = payload.strip()
    _m = re.search(r"(?:^|[;&,])\s*cast:([\d.]+)", _payload)
    if _m:
        cast = float(_m.group(1))
        _payload = _CAST_RE.sub("", _payload).rstrip(";,")
    else:
        _m2 = re.search(r"(?:^|[;&,])\s*recovery:([\d.]+)", _payload)
        if _m2:
            cast = float(_m2.group(1))
            _payload = _CAST_RE.sub("", _payload).rstrip(";,")

    # ---- 1. foodfx（食物效果：本场战斗词条族；落容器 + shield 特判 + N10-B7 装配）----
    if _payload.startswith("foodfx:"):
        aids = [a for a in _payload[7:].split(",") if a]
        if not aids:
            return None
        _fe = actor.setdefault("food_effects", [])
        for a in aids:
            if a not in _fe:
                _fe.append(a)
        # N10-B7：food aid → actor["triggers"] 装配（skill_hit/on_taken/dmg_calc 事件）
        # + effects period 周期声明（回春/冥想/晨曦）——复用 battle_food_proc 翻译表。
        # shield 特判不在此（下方独立处理）；翻译表数值读 food_effect_data 权威表。
        try:
            from .food_proc import install_food_fx
            install_food_fx(actor, aids, logs)
        except Exception:
            pass  # 装配异常不阻断吃料理（效果缺省无，文案照播——缺口可见性由测试保证）
        # shield 特判（对齐旧 _do_use_item：圣餐面包等立即给盾——数值读
        # food_effect_data 权威表）
        if "shield" in aids:
            try:
                _sh = _food_params().get("shield") or {}
                _sh_pct = float(_sh.get("pct", 0.10) or 0.10)
                _sh_turns = int(_sh.get("turns", 3) or 3)
                from saintess_engine.battle.effects import apply_effects
                apply_effects(battle, actor, actor,
                              [{"action": "shield", "key": "food_shield",
                                "pct": _sh_pct, "turns": _sh_turns,
                                "on": "caster"}], logs)
            except Exception:
                pass  # 数据异常不阻断（护盾段可选）
        _names = [(_food_params().get(a) or {}).get("name", a) for a in aids]
        logs.append(f"🍲 你吃下了料理，获得【{'、'.join(_names)}】效果！(本场战斗)")
        return logs, cast

    # ---- 1.5 purify 净化卷轴（I5：模板只判定，清除在翻译器）----
    # 清玩家侧全部存活 actor 的可净化负面（EFFECT_RULES period/on=target/cleanse；
    # sleep 不可净化）。旧模板直改 p_buffs 已随 saintess_engine 失效——负面权威在 actor.effects。
    if _payload == "purify:1":
        from saintess_engine.battle.effects import apply_effects
        _cleaned = []
        _holders = []
        try:
            for _a in (battle.sides_of("player") if hasattr(battle, "sides_of") else []):
                if isinstance(_a, dict) and int(_a.get("hp", 0) or 0) > 0:
                    _holders.append(_a)
        except Exception:
            _holders = []
        if not _holders and isinstance(actor, dict):
            _holders = [actor]
        for _h in _holders:
            _before = set((_h.get("effects") or {}).keys())
            apply_effects(battle, _h, _h, [{"action": "cleanse"}], [])
            _after = set((_h.get("effects") or {}).keys())
            _rem = _before - _after
            if _rem:
                _cleaned.append((_h.get("name", "?"), sorted(_rem)))
        if _cleaned:
            _lines = [f"{_nm}：{'、'.join(_ks)}" for _nm, _ks in _cleaned]
            logs.append(f"✨ 净化卷轴驱散了负面效果！({'; '.join(_lines)})")
        else:
            logs.append("✨ 净化卷轴展开，没有需要驱散的负面效果～")
        return logs, cast

    # ---- 2. hot（持续恢复：effects["regen_hot"] period 声明，schedule 周期结算）----
    if _payload.startswith("hot:"):
        _p = _payload[4:].split(",")
        hpct = float(_p[0]) if _p and _p[0] else 0.0
        mpct = float(_p[1]) if len(_p) > 1 and _p[1] else 0.0
        turns = int(_p[2]) if len(_p) > 2 and _p[2] else 3
        # V 系列：hot = effects["regen_hot"] 条目 + period 声明（动态数值随条目走）
        # 首跳延迟 1s + 每 interval 跳一次，turns 次后到期清（schedule 统一周期段）
        ef = actor.setdefault("effects", {})
        entry = ef.setdefault("regen_hot", {"stacks": 1})
        entry["period"] = {"dir": "heal", "interval": 1.0,
                           "heal_pct": hpct, "mana_pct": mpct,
                           "turns": turns}
        # 到期 = 首跳延迟后跳 turns 次：expire 兜底（schedule 用 dot_next 计数，见周期段）
        _desc = []
        if hpct > 0:
            _desc.append(f"每刻恢复 {int(hpct * 100)}% 生命")
        if mpct > 0:
            _desc.append(f"每刻恢复 {int(mpct * 100)}% 魔力")
        logs.append(f"🍲 你吃下了食物，{('、'.join(_desc))}！({turns} 刻)")
        return logs, cast

    # ---- 3. mana 回蓝 ----
    if _payload.startswith("mana:"):
        mv = int(_payload[5:])
        if mv > 0:
            before = int(actor.get("mp", 0) or 0)
            _mx = int(actor.get("max_mp", before) or before)
            actor["mp"] = min(_mx, before + mv)
            _real = int(actor["mp"]) - before
            logs.append(f"💙 你使用了战斗道具，恢复 {_real} 点魔力！({actor['mp']}/{_mx})")
        return logs, cast

    # ---- 4. hm 双恢复 ----
    if _payload.startswith("hm:"):
        _p = _payload[3:].split(",")
        hv = int(_p[0]) if _p and _p[0] else 0
        mv = int(_p[1]) if len(_p) > 1 and _p[1] else 0
        msgs = []
        if hv > 0:
            before = int(actor.get("hp", 0) or 0)
            heal_actor(battle, actor, hv, logs)
            _real = int(actor.get("hp", 0) or 0) - before
            if _real > 0:
                msgs.append(f"恢复 {_real} 点生命")
        if mv > 0:
            before = int(actor.get("mp", 0) or 0)
            _mx = int(actor.get("max_mp", before) or before)
            actor["mp"] = min(_mx, before + mv)
            _real = int(actor["mp"]) - before
            if _real > 0:
                msgs.append(f"恢复 {_real} 点魔力")
        logs.append(f"💊 你使用了战斗道具，{'、'.join(msgs)}！")
        return logs, cast

    # ---- 5. special 特殊分发 ----
    if _payload.startswith("special:"):
        kind = _payload[8:]
        value = None
        if ":" in kind:
            _k, _, _j = kind.partition(":")
            try:
                _d = json.loads(_j)
                if isinstance(_d, dict) and _d:
                    value = _d
                    kind = _k
            except Exception:
                pass
        return _translate_special(battle, actor, kind, value, logs, cast)

    # ---- 6. buff 属性增益（EFFECT_ACTIONS 查表）----
    if _payload.startswith("buff:"):
        kind = _payload[5:]
        keys = [k for k in kind.split(",") if k]
        if not keys:
            return None
        table = _load_effect_actions()
        # payload key（= buffs 容器键 atk_up/food_atk_up/...）→ EFFECT_ACTIONS
        # 名词（N7.5b 药水别名 buff_atk/... 的动作 key 字段即容器键）——扫表反查
        from saintess_engine.battle.effects import apply_effects
        applied = []
        for _k in keys:
            _name = _find_effect_action_name(table, _k)
            if not _name:
                continue  # 单键未覆盖 → 跳过（整串已覆盖才播报）
            # 3 刻制（对齐旧 buff 持续 3 刻）；turns 由调用方给（映射动作无 turns）
            apply_effects(battle, actor, actor,
                          [{"type": _name, "turns": 3, "on": "caster"}], logs)
            applied.append(_k)
        if not applied:
            return None
        _food = any(k.startswith("food_") for k in applied)
        _nm = "、".join(applied)
        logs.append(f"{'🍖 你吃下了料理' if _food else '🧪 你饮下战斗药水'}，{_nm}大幅提升！(3 刻)")
        return logs, cast

    # ---- 7. 纯数字 heal ----
    try:
        heal = int(_payload or 0)
    except ValueError:
        return None
    if heal > 0:
        # 半身人灵巧双手：消耗品效果 +10%（对齐旧 _do_use_item 4153-4156）
        rr = None
        try:
            from ..panel import race_stats
            rr = race_stats(actor.get("race")).get("item_effect")
        except Exception:
            rr = None
        if rr:
            heal = max(1, int(heal * (1 + rr)))
        before = int(actor.get("hp", 0) or 0)
        heal_actor(battle, actor, heal, logs)
        _real = int(actor.get("hp", 0) or 0) - before
        if _real > 0:
            logs.append(f"💊 你使用了战斗道具，恢复 {_real} 点生命！({actor['hp']}/{actor.get('max_hp', '?')})")
        else:
            logs.append("💊 你使用了战斗道具！")
    else:
        logs.append("💊 你使用了战斗道具！")
    return logs, cast


# ------------------------------------------------------------
# special 分诊
# ------------------------------------------------------------

# EFFECT_ACTIONS 直映射键（N7.5b 药水/食物别名已在规则表；此处命中即通用查表翻译）
_EFFECT_ACTION_KEYS = {
    "next_atk_up", "buff_phys_next", "cc_immune", "purify_immune",
    # 纯属性别名（payload buff: 已覆盖，双保险）
    "buff_atk", "buff_def", "buff_spd", "buff_crit", "buff_matk",
    "buff_atk_big", "buff_atk_small", "buff_atk_food",
    "buff_def_food", "buff_spd_small", "buff_spd_food",
    "buff_crit_small", "buff_crit_big", "buff_crit_food",
    "buff_matk_strong", "buff_matk_food", "food_spd_up_small",
}

# shield 动词族：payload kind → shields 容器 key（数值读 effect_data/DEFAULTS）
_SHIELD_KINDS = {
    "shield_small": "potion_shield",
    "shield_big": "potion_shield",
    "shield": "food_shield",
}


def _translate_special(battle, actor, kind: str, value, logs: list, cast: float):
    """special 分诊：EFFECT_ACTIONS 直映射 / shield 动词 / 缺口 None。"""
    if not kind:
        return None
    # 1. EFFECT_ACTIONS 直映射（next_atk_up 等一次性/免疫——hit/纯状态 buff）
    if kind in _EFFECT_ACTION_KEYS:
        table = _load_effect_actions()
        mapped = table.get(kind)
        if isinstance(mapped, list) and mapped:
            from saintess_engine.battle.effects import apply_effects
            # hit 型 buff 出手消费，expire 仅兜底 → turns 给大（装配层同族惯例），
            # 消费即清；无 turns 的动作（act_buff 要求 turns>0）会不挂
            apply_effects(battle, actor, actor,
                          [{"type": kind, "turns": 999, "on": "caster"}], logs)
            logs.append(f"🧪 你饮下战斗药水，效果就绪！(本场)")
            return logs, cast
    # 2. shield 动词族（value=物品 effect_data 或 DEFAULTS；turns 缺省 3）
    if kind in _SHIELD_KINDS:
        _key = _SHIELD_KINDS[kind]
        _ed = value if isinstance(value, dict) and value else \
            (_load_potion_defaults().get(kind) or {})
        pct = float(_ed.get("pct", 0.0) or 0.0)
        turns = int(_ed.get("turns", 3) or 3)
        if pct <= 0:
            pct = 0.10  # 兜底（无数据声明 = 旧 shield 药默认 10% max_hp）
        from saintess_engine.battle.effects import apply_effects
        apply_effects(battle, actor, actor,
                      [{"action": "shield", "key": _key, "pct": pct,
                        "turns": turns, "on": "caster"}], logs)
        logs.append(f"🛡️ 你饮下药剂，获得护盾！(吸收 {int(pct * 100)}% 最大生命，{turns} 刻)")
        return logs, cast
    # 3. 机制型真缺口（装配层/职业批）→ None：调用方提示不扣道具
    return None
