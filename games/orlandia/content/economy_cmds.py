# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年 · 交易区/经济命令实现（B9 线 L1 端口，2026-09-13）

真源 = 宿主 `game/commands/economy.py`（6,849 行）**逐字端口**：模块级常量 / 物品详情渲染器
与 `EconomyCmds` 的 131 个方法整体搬入本模块（类名改 `EconomyImpl`），**只动 import 层**：

  · 宿主面（`C` / `db` / `_ss` / `_sshop` / `_shop_svc` / `_craft_svc` / `_prof_svc` /
    `STAT_NAMES` / 平台类型 …）：`from ..x import y` → 本包 `content/economy_host.py` 的
    惰性引用（`_HostRef`）或取件器 `_h("键")`（同语义、缺件 fail-closed）。
  · `@declared(...)` / `@require_player()`：包内 = **no-op 替身**（真实注册留在宿主壳
    `game/commands/economy.py`；装饰器带 AstrBot 注册副作用，包内触发会让同一指令注册两遍）。
  · `class EconomyCmds(CommandBase)` → `class EconomyImpl(CommandBase)`（包内 `CommandBase` 为占位
    基类；宿主壳 = `class EconomyCmds(_E.EconomyImpl, CommandBase)`，MRO 与重构前逐位等价）。

除 import 层外**一行未改**（含全部注释与文案字面量）。宿主壳一行转发 + 真装饰器，行为
逐字节等价（证据：`overnight/B9-L1-economy.md`，288 例快照 before ≡ after）。
"""
import asyncio
import functools
import inspect
import json
import random
import re
import time

from .economy_host import _HostRef, _h  # noqa: F401

# ---- 包内门面（B14-2 L1：宿主聚合层 `C` 的包内等价物；宿主 `game/data` 删掉后仍可取值）----
# 453 处 `C.<名>` 读点 → 308 处切门面/读口；余下 = 21 个缺口名 + `C` 的函数名句柄
# + 1 处「宿主 C 上的 STAT_NAMES 探测」（实测宿主 `C` 无此属性，恒 `{}`，切了会改文案 → 原样保留），见 W-B14-2-L1.md
# ★ B14-3（2026-09-14）：那 21 个缺口名已由 `catalog_b143` 补上 → 本文件 140 处再切
#   （`_b143` 138 处 + `ALL_WILD` 2 处走包内派生读口 `content/wild`）。余下只有 `C` 的宿主
#   **函数名**句柄 + 上面那处 STAT_NAMES 探测；见 overnight/_w3_cut_economy_side.md。
from . import catalog_core as _ccore
from . import catalog_items as _cit
from . import catalog_life as _clife
from . import catalog_quests as _cquest
from . import catalog_space as _cspace
from . import catalog_b143 as _b143  # B14-3 收口名（装备品质/宝石/附魔/词条/钓鱼/世界事件表）
from . import wild as _wild          # B14-3：`ALL_WILD` 派生读口（content/wild，PEP 562）
from .panel import STAT_NAMES  # 既有读口（原 `_HostRef("STAT_NAMES")`，门禁证明与宿主面同值同序）
from .prof_config import gather_map_min_lv  # ★ B15b：宿主函数进包（原 `C.gather_map_min_lv`，宿主已无对象）

# ---- 宿主面（宿主壳 bind_host() 注入；顺序铁律见 economy_host 模块头）----
C = _HostRef("C")
db = _HostRef("db")
_set_info = _HostRef("_set_info")
player_final_stats = _HostRef("player_final_stats")
race_stats = _HostRef("race_stats")
_eq_random_desc = _HostRef("_eq_random_desc")
_ss = _HostRef("_ss")
_sshop = _HostRef("_sshop")
_shop_svc = _HostRef("_shop_svc")
_craft_svc = _HostRef("_craft_svc")
_prof_svc = _HostRef("_prof_svc")
AstrMessageEvent = _HostRef("AstrMessageEvent")
MessageChain = _HostRef("MessageChain")
Plain = _HostRef("Plain")


# ---- 注册装饰器替身（真实注册在宿主壳；此处只让类体能定义出来）----
def declared(*_a, **_k):
    """`@declared("key")` 替身：包内不注册（注册是宿主壳的职责）。"""
    def _deco(fn):
        return fn
    return _deco


def require_player(*_a, **_k):
    """`@require_player()` 替身：包内不拦截（宿主壳转发器上挂真装饰器）。"""
    def _deco(fn):
        return fn
    return _deco


class CommandBase:  # noqa: D101
    """占位基类：`EconomyImpl` 的宿主基（原 `class EconomyCmds(CommandBase)`）。

    本类不提供任何实现 —— 宿主壳把 `EconomyImpl` 与真 `CommandBase` 混入同一个类，
    `self` 面（`_uid` / `_player` / `_strip_cmd` / `_tip` / `_at_shop` / `_at_smith` …）
    与重构前逐位一致。
    """


# v127.5 等待型副业（垂钓/采集/挖掘）收编进通用懒计时引擎：
# 存储走 timed_events.set_timed/get_timed/remove_timed（内部 key "prof_wait"）。
# v181.P4-7：状态机/结算/彩蛋已迁 services/profession.py（timed_events 引擎 on_expire 注册
# prof_wait_expire_cb 随迁 service 模块顶层）——命令层只留解析 + 守卫 + yield 壳。
# （兼容断言指针：_prof_wait_expire_cb → services.profession.prof_wait_expire_cb，见上）


# v101.25e 商店装备价格系数（鱼鱼拍板数值方案：商店价 = 确定性推导价 × 品质系数）
# v101.25h3 鱼鱼：品质价格差距调大——原白2.0/绿1.7/蓝1.5/紫1.3/橙1.2 递减系数把品质属性倍率抵消，
# 最终橙/白价格只差 1.2 倍（橙装属性 2 倍但价格几乎没差）。改为递增系数：
# 最终价格比（属性倍率×价格系数）：白2.0 / 绿3.12 / 蓝4.80 / 紫7.20 / 橙11.0（橙≈白 5.5 倍）
# v167.2 图纸合成"有配方"白名单：CRAFT_RECIPES 中所有带 roster_id 的配方对应的名册装备
# ID 集合（与 core/drops.py 的 _BLUEPRINT_RECIPE_RIDS 同源判据，roll_blueprint 同池）。
# bp_craft 图纸合成只允许合成有锻造配方的装备，杜绝"合成出来没配方/学不了"的死图纸。
_RECIPE_ROSTER_IDS = frozenset(
    rec.get("roster_id") for rec in _clife.CRAFT_RECIPES.values() if rec.get("roster_id")
)

# v181.P4-3：SHOP_EQUIP_PRICE_MULT 定义与随迁注释已迁 services/shop.py（P4-3 交易区服务化）。
# v181.P4-3：SHOP_EQUIP_PRICE_MULT / _SHOP_EQUIP_PRICE_OVERRIDE / _MAT_FACILITY / _MAT_FACILITY_HINT
# 已随迁 services/shop.py（P4-3 交易区服务化）；本地删除。
# （bp 合成 _RECIPE_ROSTER_IDS 留在本文件——v167.2 图纸合成可合成池过滤，bp_craft 命令区非交易区）

# v181.P4-3：sell 命令壳提示文案仍引用品类分店常量 → 自 services.shop 别名（单一数据源，逐字符等价）
_MAT_FACILITY = _shop_svc._MAT_FACILITY
_MAT_FACILITY_HINT = _shop_svc._MAT_FACILITY_HINT
# v126.3 材料大类归并：配置 type 细分为 18 种（兽材/矿石/草药/精华/宝石/织物/木材/食材/
# 杂物/图纸/鱼/材料/垃圾/宝物/鱼王/收藏/传说/任务道具），v126.3 水合后 data['type'] 是
# 配置真实值——『背包 材料』筛选/使用兜底按大类归并，否则兽材/矿石等全部漏筛。
def _item_kind_type(t):
    """材料大类归并：采集/掉落可堆叠材料（C.MATERIAL_KIND_TYPES）→ '材料'；
    图纸/鱼/收藏/传说/宝物/鱼王/消耗品/符文/宠物蛋/坐骑 等保留各自 type（专属筛选类别）。"""
    if t in _ccore.MATERIAL_KIND_TYPES:
        return "材料"
    return t

# v181.P4-7：挖掘疲劳常量（MINING_FATIGUE_THRESHOLD/RECOVER）已随迁 services/profession.py
# （mining_fatigue_state/tick/fatigued 一并迁走）；本文件 use 命令壳经 _prof_svc 别名引用。


# ================= 物品详情渲染器（v101.6） =================
# 原 item_detail 内 6 分支 if-elif 硬编码：加新物品类型 = 注册一个渲染函数
# v89 汉化补全：与 engine.STAT_NAMES 同源全量属性名（原表仅 9 键 → 打造/掉落装备
# 的 precise/lifesteal/crit_dmg/物魔免等属性键英文泄漏「属性 · precise + 10%」）
_STAT_NAMES = {"atk": "攻击", "def": "防御", "matk": "魔攻", "mdef": "魔防",
              "hp": "生命", "mp": "魔力", "spd": "速度", "crit": "暴击", "dodge": "闪避",
              "precise": "精准", "pene_phys": "物穿", "pene_magi": "法穿",
              "pene_flat": "固定物穿", "pene_mflat": "固定法穿",
              "tenacity": "韧性", "luck": "幸运",
              "cdr": "冷却缩减", "elem_res": "元素抗性", "abyss_res": "深渊抗性",
              "exp_bonus": "经验加成", "gold_bonus": "金币加成",
              "heal_power": "治疗强度", "shield_power": "护盾强度",
              "lifesteal": "吸血", "crit_dmg": "暴击伤害", "block": "格挡",
              "thorns": "反伤", "phys_reduce": "物免", "magic_reduce": "魔免",
              "lifesteal_phys": "物吸", "lifesteal_magi": "法吸",
              "summon_power": "召唤强化"}
_REQ_NAMES = {"str": "力量", "agi": "敏捷", "int": "智力", "vit": "耐力"}



# v135 装备特色增强：词条特色标签（装备详情面板展示）
# 按词条 trigger/effect 关键词归类，让玩家一眼看出这件装备的战斗性格
_AFFIX_FEATURE_RULES = [
    ("吸血", ("lifesteal", "lifesteal_phys", "lifesteal_magi", "thirst_phys", "thirst_magi", "血")),
    ("破甲", ("armor_break", "pierce", "pene_", "破")),
    ("连击", ("combo", "charge", "连")),
    ("元素", ("element_", "元素", "冰", "雷", "火")),
    ("护盾", ("shield", "护盾", "坚盾")),
    ("减速", ("slow", "减速", "冰")),
    ("暴击", ("crit", "暴击")),
    ("闪避", ("dodge", "闪避")),
    ("格挡", ("block", "格挡")),
    ("反伤", ("thorns", "反伤")),
    ("吸血", ("lifesteal", "血")),
    ("回春", ("regen", "回春")),
    ("冥想", ("meditate", "冥想")),
    ("韧性", ("tenacity", "韧性")),
    ("迅捷", ("swift", "迅捷", "速度")),
    ("减伤", ("dmg_reduce", "phys_reduce", "magic_reduce", "减伤", "免伤")),
    ("处决", ("execute", "处决")),
    ("追猎", ("hunt", "追猎", "标记")),
    ("破魔", ("break_magic", "破魔")),
    ("龙威", ("dragon_aw", "龙威")),
    ("成长", ("exp_bonus", "gold_bonus", "luck", "求知", "聚宝", "幸运")),
]


def _equip_affix_features(d: dict) -> list:
    """词条特色标签：按 affixes + legendary 的 name/effect 关键词归类（去重保序）。"""
    names = []
    for af in d.get("affixes", []):
        info = _cit.AFFIXES.get(af) if isinstance(af, str) else None
        if info:
            names.append(info.get("name", ""))
    lg = d.get("legendary")
    if lg:
        lgi = _cit.LEGENDARY_EFFECTS.get(lg)
        if lgi:
            names.append(lgi.get("name", ""))
    features = []
    for label, keys in _AFFIX_FEATURE_RULES:
        for k in keys:
            if any(k in n for n in names):
                features.append(label)
                break
    return features


def _upgrade_recalc_equip(d: dict, new_lv: int) -> dict:
    """v172 真等级化：装备升到 new_lv 后按生成公式重算 stats 并同步 price。

    - 保留 affixes/enchant/sockets/calamity_bonus/req/desc/flavor/set/legendary/
      craft_cost 等全部个体字段——只重算基础 stats 与 price（升级不动词条/附魔/宝石）。
    - 武器/防具按原 weapon_type/req 族传分系参数（与 drops.generate_roster_equip 同口径）：
      weapon → equip_stats(slot, lv, quality, weapon_type=weapon_type)
      防具（helm/armor/legs/boots）→ 按 req 首属性族推 armor_family
    - v29 武器类型特色（WEAPON_FLAVOR 固定加成，如剑微暴击/法杖魔攻）在生成时并入 stats，
      升级重算需同步重挂（否则分系武器升 lv 后特色加成丢失）；flavor_stats 字段同口径刷新。
    - 词条常驻属性（stat_affix_stats 按新 lv 折算 pene_flat 等）原并入 stats，重算后同样补挂
      （旧词条 ID 列表保留，仅重算其折算值，避免固定穿透等随 lv 变化的词条掉档）。
    - 橙装传说专属 stat 型效果（_merge_legendary_stats 按 lv 折算 hp_pct）同样补挂。
    """
    slot = d.get("slot", "")
    quality = d.get("quality", "white")
    stats = C.equip_stats(slot, new_lv, quality)
    weapon_type = d.get("weapon_type")
    # v156 装备分系（名册路径同款）
    if slot == "weapon" and weapon_type:
        stats = C.equip_stats(slot, new_lv, quality, weapon_type=weapon_type)
    elif slot in ("helm", "armor", "legs", "boots"):
        ARMOR_FAMILY_ALIAS = _h('ARMOR_FAMILY_ALIAS')  # ← from ..core.stats import ARMOR_FAMILY_ALIAS  # C 聚合未导出该别名，core 直引
        _req = d.get("req") or {}
        _fam = ARMOR_FAMILY_ALIAS.get(next(iter(_req), ""), None)
        if _fam:
            stats = C.equip_stats(slot, new_lv, quality, armor_family=_fam)
    # v29 武器类型特色（生成时并入 stats，升级后同口径重挂；非武器无 flavor）
    if slot == "weapon" and weapon_type:
        flavor = _b143.WEAPON_FLAVOR.get(weapon_type, {})
        flavor_stats = {}
        if flavor:
            for fk, fv in flavor.items():
                if fk == "desc" or not isinstance(fv, (int, float)):
                    continue
                if fk == "crit":
                    stats["crit"] = round(stats.get("crit", 0) + fv, 3)
                    flavor_stats["crit"] = fv
                elif fk == "spd_fix":
                    stats["spd"] = stats.get("spd", 0) + int(fv)
                    flavor_stats["spd"] = int(fv)
                elif fk == "hp_fix":
                    stats["hp"] = stats.get("hp", 0) + int(fv)
                    flavor_stats["hp"] = int(fv)
                else:
                    add = int(stats.get(fk, 0) * fv)
                    stats[fk] = stats.get(fk, 0) + add
                    flavor_stats[fk] = add
        if flavor_stats:
            d["flavor"] = flavor_stats
        else:
            d.pop("flavor", None)
    # 词条常驻属性折算（按新 lv；触发型词条不进 stats，battle 消费，不动）
    stat_affix_stats = _h('stat_affix_stats')  # ← from ..core.affix import stat_affix_stats
    for k, v in stat_affix_stats([a for a in (d.get("affixes") or []) if isinstance(a, str)],
                                 slot, new_lv).items():
        if k in _ccore.PCT_STATS:
            stats[k] = round(stats.get(k, 0) + v, 4)
        else:
            stats[k] = stats.get(k, 0) + int(v)
    # v125 名册专属 stat 型效果（hp_pct 按新 lv 白板折算）
    if d.get("legendary"):
        _merge_legendary_stats = _h('_merge_legendary_stats')  # ← from ..core.drops import _merge_legendary_stats
        _merge_legendary_stats(stats, d["legendary"], slot, new_lv)
    d["lv"] = new_lv
    d["stats"] = stats
    # 同步 price（生成公式：equip_value(stats) × (3 + lv×0.5) × 品质倍率）
    equip_value = _h('equip_value')  # ← from ..core.stats import equip_value
    d["price"] = int(equip_value(stats) * (3 + new_lv * 0.5) * _b143.QUALITY[quality]["mult"])
    return d


def _render_equip(d, lines, equipped):
    """装备详情"""
    # ===== 装备 =====
    q = _b143.QUALITY[d["quality"]]
    enh = d.get("enhance", 0)
    enh_str = f" +{enh}" if enh > 0 else ""
    equip_state = "(已装备)" if equipped else ""
    lines.append(f"{q['color']}【{d['name']}{enh_str}】({_b143.EQUIP_SLOTS[d['slot']]}){equip_state}")
    lines.append("━━━━━━━━━━━━")
    lines.append(f"品质：{q['name']} ｜ 需求等级：Lv.{d['lv']}")
    if d.get("weapon_type"):
        # 阶段八：武器不锁职业，只显示类型（20 章装备只限属性）
        lines.append(f"类型：{C.display('weapon_types', d['weapon_type'])}")
        flavor_desc = _b143.WEAPON_FLAVOR.get(d["weapon_type"], {}).get("desc", "")
        if flavor_desc:
            lines.append(f"✦ {flavor_desc}")
    st = d.get("stats", {})
    stat_names = _STAT_NAMES
    stat_lines = []
    for k, v in st.items():
        if v:
            label = stat_names.get(k, k)
            stat_lines.append(f"{label} + {int(v * 100)}%" if k in _ccore.PCT_STATS else f"{label} + {v}")
    if stat_lines:
        # v101.21 排版：属性每项单独一行（鱼鱼：属性+两边空格+换行，别挤一行）
        lines.append("属性：")
        for s in stat_lines:
            lines.append(f"  · {s}")
    # 阶段八：特效词条 v2（ID 列表 → 名称+描述）+ 传说专属
    aff_lines = []
    for af in d.get("affixes", []):
        if isinstance(af, dict):  # 旧结构兼容
            k, v = af.get("stat"), af.get("value", 0)
            label = stat_names.get(k, k)
            aff_lines.append(f"{label} + {int(v * 100)}%" if k in _ccore.PCT_STATS else f"{label} + {v}")
            continue
        info = _cit.AFFIXES.get(af)
        if info:
            # v101.21 词条排版：『名称：描述』（类似属性面板的力量/智力每行一项）
            aff_lines.append(f"{info['name']}：{info['desc']}" if info.get("desc") else info["name"])
    if aff_lines:
        lines.append("✨ 词条：")
        for a in aff_lines:
            lines.append(f"  · {a}")
    # v135 词条特色展示：词条标签 → 这件装备的『性格』（攻击型/防御型/元素/机动/成长）
    feat = _equip_affix_features(d)
    if feat:
        lines.append(f"⭐ 词条特色：{'｜'.join(feat)}")
    if d.get("legendary"):
        lg = _cit.LEGENDARY_EFFECTS.get(d["legendary"])
        if lg:
            lines.append(f"✨ 专属·{lg['name']}：{lg['desc']}")
    # 阶段八：属性需求（不锁职业，只锁力量/智力/敏捷/耐力）
    req = d.get("req")
    if req:
        req_names = _REQ_NAMES
        req_str = " + ".join(f"{req_names.get(k, k)} {v}" for k, v in req.items())
        lines.append(f"需求：{req_str}")
    # v10：附魔（v34：符文效果词条，带等级）
    # v104R3 M11 P3-5：属性附魔与符文效果分开标签（此前属性附魔也被叫"符文"）
    # v104R3 M11 P3-8：补附魔槽位占用显示（ENCHANT_SLOTS 按品质：蓝 1/紫 2/橙 2）
    rune_lines = []
    ench_lines = []
    for en in d.get("enchant", []):
        if en.get("effect"):
            eff_name = _cit.RUNE_EFFECT_NAMES.get(en["effect"], en["effect"])
            lvl = int(en.get("lvl", 1) or 1)
            roman = _b143.RUNE_LEVEL_ROMAN.get(lvl, "")
            rune_lines.append(f"『{eff_name}{roman}』")
        else:
            k, v = en.get("stat"), en.get("value", 0)
            label = stat_names.get(k, k)
            ench_lines.append(f"{label} + {int(v * 100)}%" if k in _ccore.PCT_STATS else f"{label} + {v}")
    _slots = _b143.ENCHANT_SLOTS.get(d.get("quality", ""), 0)
    if _slots:
        lines.append(f"🔮 附魔槽：{len(d.get('enchant', []))}/{_slots}")
    if rune_lines:
        lines.append("🔮 符文： " + "  ".join(rune_lines))
    if ench_lines:
        lines.append("✨ 附魔： " + "  ".join(ench_lines))
    # v10：套装归属
    if d.get("set"):
        sinfo = _cit.SETS.get(d["set"])
        if sinfo:
            # v105 M07 P3-3：新套 4 件效果在 bonus_4_stats（旧套在 bonus_4.desc），
            # 拼装展示，杜绝「🌳橡木套()」空括号
            b4_parts = [f"{_STAT_NAMES.get(k, k)}+{int(v * 100)}%"
                        for k, v in sinfo.get("bonus_4_stats", {}).items()]
            b4d = sinfo.get("bonus_4", {}).get("desc", "")
            if b4d:
                b4_parts.append(b4d)
            b4_str = "  ".join(b4_parts)
            lines.append(f"🎴 套装：{sinfo['icon']}{d['set']}" + (f"(4件:{b4_str})" if b4_str else ""))
    if enh > 0:
        info = _cit.ENHANCE_TABLE.get(enh)
        # v104R3 M11 P3-6：括号前补空格（数值+两侧空格排版），× 倍率防误读为 +136%
        lines.append(f"强化：+{enh} (属性 ×{info['mult']})" if info else f"强化：+{enh}")
    # v136 原石孔位展示
    _socks = d.get("sockets") or {}
    if _socks:
        _sock_lines = []
        for _sk, _sv in _socks.items():
            if _sv:
                _sock_lines.append(f"{_sk}:💎{_sv.get('name','')}")
            else:
                _sock_lines.append(f"{_sk}:空")
        lines.append("💎 幸运宝石： " + "  ".join(_sock_lines))
    if d.get("desc"):
        lines.append(f"描述：{d['desc']}")
    else:
        # v101.25g：存量背包装备可能无 desc 字段 → 名册兜底 / 按部位生成
        rid_list = _cit.EQUIP_ROSTER_BY_NAME.get(d["name"], [])
        rdesc = _cit.EQUIP_ROSTER[rid_list[0]].get("desc") if rid_list else None
        lines.append(f"描述：{rdesc or _eq_random_desc(d['name'], d.get('slot', 'armor'), d.get('weapon_type'))}")
    lines.append("")
    # v104R3 P3：装备详情"出售价"误导——实收 = 推导价×0.5（_sell_one 铁匠铺回收，v101.27 鱼鱼拍板），
    # 且坐骑 sell_bonus/锻造 craft_cost 上限会再浮动 → 改标实收口径并加"约"
    _pawn = int(d.get("price", 0) * 0.5)
    lines.append(f"💡 『装备 {d['name']}』穿上它 ｜ 铁匠铺回收约 {_pawn} 金币")


def _render_material(d, lines, equipped):
    """材料详情"""
    # ===== 材料 =====
    # v101.25g：MATERIALS 的 key 是 mat_ ID，按名查必须用 MATERIALS_BY_NAME（原 MATERIALS.get 恒空）
    mat = _cit.MATERIALS_BY_NAME.get(d["name"])
    q = _b143.QUALITY.get((mat or {}).get("quality", "white"), {})
    mtype = (mat or {}).get("type", "材料")
    lines.append(f"🧪 【{d['name']}】")
    lines.append("━━━━━━━━━━━━")
    lines.append(f"类型：{mtype} ｜ 品质：{q.get('color', '')}{q.get('name', '普通')}")
    desc = (mat or {}).get("desc") or d.get("desc")
    if desc:
        lines.append(f"描述：{desc}")
    lines.append("")
    # v104R3 P3：材料详情"出售价"误导——实收按店铺 8~9 折（矿石/兽材→铁匠铺 0.9、
    # 草药/精华→炼金铺 0.9、食材/织物/杂物→商店 0.8；收藏鱼 1.0 原价）
    lines.append(f"💡 回收参考价 {d.get('price', 0)} 金币(实收按店铺 8~9 折) ｜ 『出售 {d['name']}』变现 ｜ 『喂养 {d['name']}』喂宠物")


def _render_fish(d, lines, equipped):
    """鱼详情（v126.4 拍板项 3：鱼专属渲染器，替代默认消耗品 📦 样式）"""
    # ===== 鱼 =====
    fish = next((f for f in _clife.FISH_POOL if f["name"] == d.get("name", "")), None)
    q = _b143.QUALITY.get(d.get("quality") or (fish or {}).get("quality", "white"), {})
    lines.append(f"🐟 【{d['name']}】")
    lines.append("━━━━━━━━━━━━")
    lines.append(f"类型：鱼 ｜ 品质：{q.get('color', '')}{q.get('name', '普通')}")
    desc = (fish or {}).get("desc") or d.get("desc")
    if desc:
        lines.append(f"描述：{desc}")
    lines.append("")
    # v126.1 大鱼卖更贵：实收按个体重量加权（0.5~1.5×），底价仅为参考
    lines.append(f"💡 出售参考价 {d.get('price', 0)} 金币（大鱼按重量加价） ｜ 『出售 {d['name']}』变现 ｜ 『喂养 {d['name']}』喂宠物")


def _render_rune(d, lines, equipped):
    """符文详情"""
    # ===== 符文（v34） =====
    lines.append(f"💎 【{d['name']}】")
    lines.append("━━━━━━━━━━━━")
    # v104R3 M11 P3-1：品质显示中文名+颜色（此前直出英文 ID "purple"，与图鉴/名称不一致）
    _rq = _b143.QUALITY.get(d.get("quality", ""), {})
    lines.append(f"类型：符文 ｜ 品质：{_rq.get('color', '')}{_rq.get('name', '')} ｜ 等级：{_b143.RUNE_LEVEL_ROMAN.get(int(d.get('lvl', 1) or 1), '')}")
    if d.get("desc"):
        lines.append(f"效果：{d['desc']}")
    lines.append("")
    lines.append(f"💡 『附魔 <装备名> {d['name']}』刻印到装备 ｜ 出售价 {d.get('price', 0)} 金币")


def _render_encyclopedia_equip(r):
    """v169.x 意见#88：未拥有装备图鉴预览——复用百科 v167.1 装备单查渲染风格
    （⚔️ 名称(部位·Lv·品质) + 系列/需求/来源/套装/特效/描述 + 图鉴提示）。
    r 为名册条目（无随机词条/强化；属性见 desc，与商店/掉落生成的同原型装备一致）。"""
    _q = _b143.QUALITY.get(r.get("quality", "white"), {})
    _slot_nm = _b143.EQUIP_SLOTS.get(r.get("slot", ""), r.get("slot", "?"))
    _attr_cn = {"str": "力量", "agi": "敏捷", "int": "智力", "vit": "耐力"}
    _req = r.get("req") or {}
    _req_s = "、".join(f"{_attr_cn.get(k, k)}{v}" for k, v in _req.items()) if _req else "无需求"
    el = [f"⚔️ {_q.get('color', '')}【{r['name']}】({_slot_nm}·Lv.{r.get('lv', '?')}·{_q.get('name', r.get('quality'))})",
          "━━━━━━━━━━━━"]
    if r.get("series"):
        el.append(f"系列：{r['series']}")
    el.append(f"需求：{_req_s}")
    if r.get("source"):
        el.append(f"来源：{r['source']}")
    if r.get("set"):
        el.append(f"套装：{r['set']}")
    if r.get("special"):
        el.append(f"特效：{r['special']}")
    if r.get("desc"):
        el.append(f"{r['desc']}")
    el.append("")
    el.append(f"💡 图鉴预览（未拥有）——『百科装备 {_slot_nm}』看{_slot_nm}全部装备")
    return "\n".join(el)


def _roster_gen_equip(r: dict):
    """按名册条目生成一件标准装备用于百科展示。rid 不在条目内 → 用名册名反查
    EQUIP_ROSTER_BY_NAME（与掉落/商店生成同源）；失败返回 None（安全降级为无属性视图）。"""
    try:
        _rids = _cit.EQUIP_ROSTER_BY_NAME.get(r.get("name", "")) or [
            _k for _k, _rr in _cit.EQUIP_ROSTER.items() if _rr.get("name") == r.get("name")]
        if not _rids:
            return None
        return C.generate_roster_equip(_rids[0])
    except Exception:
        return None


def _render_blueprint(d, lines, equipped):
    """图纸详情"""
    # ===== 图纸（v41 毕业套锻造材料） =====
    # v101.28l #434：原模板抄的"阶段/职业"字段图纸根本没有（空显示），改用名册真实字段
    q = _b143.QUALITY.get(d.get("quality", ""), {})
    r = _cit.EQUIP_ROSTER.get(d.get("roster_id", ""), {}) if d.get("roster_id") else {}
    slot_cn = _b143.EQUIP_SLOTS.get(r.get("slot", ""), "") if r else ""
    series = r.get("series", "") if r else ""
    _parts = [f"类型：图纸", f"品质：{q.get('name', '')}"]
    if series:
        _parts.append(f"系列：{series}")
    if slot_cn:
        _parts.append(f"部位：{slot_cn}")
    lines.append(f"📜 【{d['name']}】")
    lines.append("━━━━━━━━━━━━")
    lines.append(" ｜ ".join(_parts))
    if d.get("desc"):
        lines.append(f"描述：{d['desc']}")
    lines.append("")
    lines.append(f"💡 到铁匠铺『锻造 {d.get('blueprint_for', '')}』系列装备 ｜ 出售价 {d.get('price', 0)} 金币")


def _render_pet_egg(d, lines, equipped):
    """宠物蛋详情"""
    # ===== 宠物蛋 =====
    lines.append(f"🥚 【{d['name']}】")
    lines.append("━━━━━━━━━━━━")
    pdef = next((p for p in _clife.PET_POOL if p["key"] == d.get("pet_key")), None)
    if pdef:
        # v101.14 品质标签
        ql = C.pet_quality_label(pdef["key"])
        lines.append(f"可孵化：{ql} {pdef['icon']}{pdef['name']}（{pdef.get('source', '怪物掉落')}）")
        lines.append(f"描述：{pdef['desc']}")
        lines.append(f"🎯 技能：{C.pet_skill_label(pdef['key'])}")
    else:
        lines.append("神秘的蛋，『使用 宠物蛋』孵化试试？")
    lines.append("")
    lines.append(f"💡 『使用 {d['name']}』孵化 ｜ 出售价 {d.get('price', 0)} 金币")


def _render_mount(d, lines, equipped):
    """坐骑缰绳详情（v101.14 品质+效果展示）"""
    # ===== 坐骑 =====
    lines.append(f"🐎 【{d['name']}】")
    lines.append("━━━━━━━━━━━━")
    mk = d.get("mount_key")
    mdef = _clife.MOUNT_BY_KEY.get(mk) if mk else None
    if mdef:
        _Q = _b143.QUALITY  # ← from ..data.equipment import QUALITY as _Q（B14-3：宿主 data 取件切包内门面）
        q = _Q.get(mdef.get("quality", "white"), {})
        ql = f"{q.get('color', '⚪')}{q.get('name', '普通')}"
        lines.append(f"坐骑：{ql} {mdef['icon']}{mdef['name']}（Lv.{mdef['lv']} 可骑乘）")
        lines.append(f"效果：{mdef['desc']}")
    else:
        lines.append("缰绳上残留着野兽的气息……")
    lines.append("")
    lines.append(f"💡 『使用 {d['name']}』驯服 ｜ 出售价 {d.get('price', 0)} 金币")


def _render_consumable(d, lines, equipped):
    """消耗品/道具详情"""
    # ===== 消耗品/道具 =====
    lines.append(f"📦 【{d['name']}】")
    lines.append("━━━━━━━━━━━━")
    if d.get("type"):
        lines.append(f"类型：{d['type']}")
    if d.get("desc"):
        lines.append(f"效果：{d['desc']}")
    elif d.get("hot") or d.get("hot_mana"):
        # v104 M08 P2-5：食物持续恢复渲染（无 desc 兜底时不再只显示空白）
        _t = d.get("hot_turns", 3)
        parts = []
        if d.get("hot"):
            parts.append(f"战斗中每刻回复 {int(d['hot'] * 100)}% 生命（{_t} 刻）")
        if d.get("hot_mana"):
            parts.append(f"战斗中每刻回复 {int(d['hot_mana'] * 100)}% 魔力（{_t} 刻）")
        if d.get("heal"):
            h = d["heal"]
            parts.append(f"恢复 {int(h * 100)}% 生命" if h < 1 else f"恢复 {h} 点生命")
        if d.get("mana"):
            m = d["mana"]
            parts.append(f"恢复 {int(m * 100)}% 魔力" if m < 1 else f"恢复 {m} 点魔力")
        if d.get("stamina"):
            parts.append(f"{d['stamina']} 体力")
        lines.append("效果：" + "、".join(parts))
    elif d.get("food_effect"):
        # v104 M08 P2-5：效果料理渲染
        lines.append(f"效果：战斗中获得【{d['food_effect']}】")
    elif d.get("affix"):
        # v104 M08 P2-5：词条渲染（装备词条兜底，正常情况下装备走 _render_equip）
        lines.append(f"效果：{d['affix']}")
    elif d.get("heal") or d.get("mana"):
        # v95.17 #147：heal<1 是百分比（v54 战斗外回复），详情直接显示原始小数误导 → 换算百分比
        parts = []
        if d.get("heal"):
            h = d["heal"]
            parts.append(f"恢复 {int(h * 100)}% 生命" if h < 1 else f"恢复 {h} 点生命")
        if d.get("mana"):
            m = d["mana"]
            parts.append(f"恢复 {int(m * 100)}% 魔力" if m < 1 else f"恢复 {m} 点魔力")
        if d.get("stamina"):
            parts.append(f"{d['stamina']} 体力")
        lines.append("效果：" + " + ".join(parts))
    lines.append("")
    if d.get("price"):
        lines.append(f"💡 出售价 {d['price']} 金币")
    lines.append(f"💡 『使用 {d['name']}』使用它")


# 大类 → 渲染器（key 与 _item_category 返回值一致）；未知大类走默认消耗品
_ITEM_DETAIL_RENDERERS = {
    "装备": _render_equip,
    "材料": _render_material,
    "符文": _render_rune,
    "图纸": _render_blueprint,
    "宠物蛋": _render_pet_egg,
    "坐骑": _render_mount,
    "鱼": _render_fish,  # v126.4 拍板项 3：鱼专属（🐟 + 品质色 + 描述 + 大鱼加价提示）
    "__default__": _render_consumable,
}


def item_detail_render(d, lines, equipped):
    """按物品大类分发到渲染器（v101.6：加新类型 = 注册表加一行 + _item_category 加一类）。
    大类判断与 EconomyCmds._item_category 一致（装备→slot；材料大类归并→type/其他）。"""
    kind = "装备" if d.get("slot") else (_item_kind_type(d.get("type")) or "其他")
    fn = _ITEM_DETAIL_RENDERERS.get(kind) or _ITEM_DETAIL_RENDERERS["__default__"]
    fn(d, lines, equipped)
    # v126.4 个体属性（tags）通用渲染：主体渲染后统一追加（数据驱动 ITEM_TAG_DISPLAY）
    _render_item_tags(d, lines)


def _render_item_tags(d, lines):
    """v126.4 个体属性（tags）通用渲染——数据驱动 ITEM_TAG_DISPLAY 按物品大类配置行模板。

    堆叠个体物（垂钓渔获等）入包带 tag（{...}）存 item_data.tags；『物品详情』统一在
    主体渲染后追加个体区。加新 tag 显示 = 数据表加一行（key=物品 type 大类）：
    - line: 每条 tag 渲染行模板（str.format 填充 tag 字段，支持列表=一条 tag 多行）
    - max_lines: 单次渲染行数上限（防囤鱼刷屏），超出用 omit 省略行
    模板字段与 tag 不匹配 → 单条跳过（数据缺失不炸详情）；未命中配置 → 不显示。
    """
    tags = d.get("tags")
    if not tags or not isinstance(tags, list):
        return
    kind = _item_kind_type(d.get("type")) or ""
    cfg = (getattr(C, "ITEM_TAG_DISPLAY", None) or {}).get(kind)
    if not cfg:
        cfg = (getattr(C, "ITEM_TAG_DISPLAY", None) or {}).get("*")
    if not cfg or not cfg.get("line"):
        return
    max_lines = int(cfg.get("max_lines") or 20)
    shown = tags[:max_lines]
    out = []
    for t in shown:
        if not isinstance(t, dict):
            continue
        tmpls = cfg["line"] if isinstance(cfg["line"], list) else [cfg["line"]]
        for tmpl in tmpls:
            try:
                out.append("  · " + tmpl.format(**t))
            except (KeyError, TypeError, ValueError):
                continue  # 模板字段缺失/类型不符 → 跳过这条（数据行容忍缺字段）
    if not out:
        return
    lines.append("")
    lines.append("个体：")
    lines.extend(out)
    left = len(tags) - len(shown)
    if left > 0:
        omit = cfg.get("omit", "……还有 {left} 条")
        try:
            lines.append(omit.format(left=left))
        except (KeyError, TypeError, ValueError):
            lines.append(f"……还有 {left} 条")


# v181.P4-7：采集限定条件词注册表 _GATHER_COND_CHECKERS + v125.2 启动校验
# 已随迁 services/profession.py（gather_roll/gather_cond_roll 一并迁走）——
# 命令层不再持有定义；保留下划线别名供存量测试/工具 import（单一数据源）
_GATHER_COND_CHECKERS = _prof_svc._GATHER_COND_CHECKERS
_prof_svc.validate_gather_cond()  # v125.2 fail-fast：economy 模块 import/reload 同样触发（P4-7 迁走后保持原行为）


class EconomyImpl(CommandBase):
    """背包/装备/锻造/强化/商店/采集/垂钓/炼金"""



    def _nearest_town(self, cur_map: str) -> str:
        """BFS 找离当前地图最近的城镇（回城卷轴用）。cur_map 本身是城镇则原地。"""
        from collections import deque
        if cur_map in _cspace.MAP_BY_ID and _cspace.MAP_BY_ID[cur_map].get("type") == _ccore.MAP_TYPE_TOWN:
            return cur_map
        q = deque([(cur_map, 0)])
        seen = {cur_map}
        while q:
            m, d = q.popleft()
            if d >= 6:
                continue
            for nxt in _b143.MAP_CONNECTIONS.get(m, []):
                if nxt in seen:
                    continue
                seen.add(nxt)
                mm = _cspace.MAP_BY_ID.get(nxt, {})
                if mm.get("type") == _ccore.MAP_TYPE_TOWN:
                    return nxt
                q.append((nxt, d + 1))
        return _ccore.START_MAP


    @declared("gather")
    @require_player()

    async def gather(self, event: AstrMessageEvent):
        group_id, qq_id = self._uid(event)
        player = self._player(group_id, qq_id)
        ok, act_msg = self._prof_active_check(group_id, qq_id, "gather", require_apprentice=True)
        if not ok:
            yield event.plain_result(act_msg)
            return
        cur_map = _cspace.MAP_BY_ID.get(player["cur_map"], {})
        if cur_map.get("type") == _ccore.MAP_TYPE_TOWN:
            yield event.plain_result("城镇里没有可采集的野生物资，去野外吧（『前往 <地图名>』）！")
            return
        # v104 R3 M14 P1-2：副本内采集白嫖强化石/怪物专属材料（副本怪掉落专属材料应走战斗获取）
        if cur_map.get("type") == _ccore.MAP_TYPE_INSTANCE:
            yield event.plain_result("副本里没有可采集的野生物资，专心闯关吧！（怪物会掉落专属材料）")
            return
        # v173 采集副业等级门禁：采集图按池最高料价分档（采集 Lv.1→9），
        # 等级不足不能跨级白嫖高等级图稀有料（鱼鱼 2026-09 拍板：按副业等级卡、分阶段，
        # 对齐垂钓钓点 min_lv 模型 + 19 章"采集等级解锁更多采集点/高品质产出"）。
        # 顺序：先 _prof_wait_flow（含旧轮惰性结算，v127.5「奖励不丢」铁律）——
        #   旧轮结算保留；若 flow 已开新轮（_ok=True），清掉新轮再拦（防高图留计时白嫖）。
        _gather_lv = db.get_prof_level(group_id, qq_id, "gather")
        _need_gather = int(gather_map_min_lv(int(cur_map.get("lv") or 0)))
        if _gather_lv < _need_gather:
            text, _ok = self._prof_wait_flow(
                event, group_id, qq_id, "gather",
                extra={"spot_map": player["cur_map"]},
                begin_text=f"🌿 你俯身开始采集【{cur_map.get('name', '？')}】的野生物资……预计 ",
            )
            if _ok:
                # flow 已挂新轮引擎 → 清掉（防到点自动结算绕过门禁）
                self._prof_wait_clear(group_id, qq_id)
                if text:
                    yield event.plain_result(act_msg + text + "\n" +
                        f"🌿 但【{cur_map.get('name')}】的植物太珍稀（需采集 Lv.{_need_gather}，你 Lv.{_gather_lv}）——"
                        "先在低等级区域练练采集吧！")
                    return
                yield event.plain_result(act_msg + text)
                return
            yield event.plain_result(act_msg + text)
            return
        # v55 等待制（原 60 秒 CD 改为随机等待，自动入包，等级减时）
        # v105R3 M13 P1-1：先走等待流再扣体力——等待中重复『采集』直接提示剩余秒数，
        # 不再白扣 5 体力（v104 复验 3 处同病：采集/挖掘/垂钓，体力对齐疲劳计数只计新轮）
        text, _ok = self._prof_wait_flow(
            event, group_id, qq_id, "gather",
            # v105R3 M13 P2-4：extra 带 spot_map，重启后旧等待按原地图结算（防串到当前地图采集池）
            extra={"spot_map": player["cur_map"]},
            begin_text=f"🌿 你俯身开始采集【{cur_map.get('name', '？')}】的野生物资……预计 ",
        )
        if not _ok:
            yield event.plain_result(act_msg + text)
            return
        # v94 体力：采集消耗 5 体力（确认开启新轮后才扣；体力不足回滚新轮等待，防白等）
        _ok, _st = self._spend_stamina(group_id, qq_id, _clife.PROF_STAMINA_COST["gather"], player, "采集")
        if not _ok:
            self._prof_wait_clear(group_id, qq_id)
            # v126.4 拍板项 4：体力不足也要带上旧轮结算播报（否则收获入包了玩家却毫不知情）
            yield event.plain_result((text + "\n" + _st) if text else _st)
            return
        yield event.plain_result(act_msg + text)

    @declared("mining")
    @require_player()

    async def mining(self, event: AstrMessageEvent):
        group_id, qq_id = self._uid(event)
        player = self._player(group_id, qq_id)
        ok, act_msg = self._prof_active_check(group_id, qq_id, "mining", require_apprentice=True)
        if not ok:
            yield event.plain_result(act_msg)
            return
        cur_map = _cspace.MAP_BY_ID.get(player["cur_map"], {})
        # v104 R3 M14 P2-3：城镇安全区拦挖掘（与采集规则一致，防城镇无风险挖高价值矿）
        if cur_map.get("type") == _ccore.MAP_TYPE_TOWN:
            yield event.plain_result("城镇里没有矿脉，去野外矿点吧（『前往 <地图名>』）！")
            return
        # 矿脉点（v13：明确配置，地图上显示⛏️；v173 dict 化含 min_lv）
        _mine = _clife.MINE_SPOTS.get(cur_map.get("id"))
        if not _mine:
            yield event.plain_result("这里没有矿脉！地图上会显示⛏️矿脉的位置，去那边『挖掘』吧～")
            return
        # v173 挖掘副业等级门禁：矿脉分阶段（挖掘 Lv.1→9），等级不足不能挖高级矿脉
        # （对齐垂钓钓点 min_lv 模型 + 19 章"挖掘等级解锁更高品质矿脉"）
        _need = int(_mine.get("min_lv", 1)) if isinstance(_mine, dict) else 1
        _prof_lv = db.get_prof_level(group_id, qq_id, "mining")
        if _prof_lv < _need:
            yield event.plain_result(
                f"⛏️ 【{_mine.get('name', '矿脉') if isinstance(_mine, dict) else _mine}】需要挖掘 Lv.{_need}，"
                f"你才 Lv.{_prof_lv}——先在低阶矿脉练练手吧！"
            )
            return
        # v55 等待制（原 90 秒 CD 改为随机等待，自动入包，等级减时）
        # v105R3 M13 P1-1：先走等待流再扣体力——等待中重复『挖掘』不再白扣 5 体力；
        # P2-4：extra 带 spot_map，重启后旧等待按原地图结算（防串到当前地图矿池）
        text, _ok = self._prof_wait_flow(
            event, group_id, qq_id, "mining",
            extra={"spot_map": player["cur_map"]},
            begin_text=f"⛏️ 你举起镐子凿向【{cur_map.get('name', '？')}】的矿脉……预计 ",
        )
        if not _ok:
            yield event.plain_result(act_msg + text)
            return
        # v94 体力：挖掘消耗 5 体力（确认开启新轮后才扣；体力不足回滚新轮等待，防白等）
        _ok, _st = self._spend_stamina(group_id, qq_id, _clife.PROF_STAMINA_COST["mining"], player, "挖掘")
        if not _ok:
            self._prof_wait_clear(group_id, qq_id)
            # v126.4 拍板项 4：体力不足也要带上旧轮结算播报
            yield event.plain_result((text + "\n" + _st) if text else _st)
            return
        yield event.plain_result(act_msg + text)

    @declared("alchemy")
    @require_player()

    async def alchemy(self, event: AstrMessageEvent):
        group_id, qq_id = self._uid(event)
        player = self._player(group_id, qq_id)
        raw = self._strip_cmd(event, "炼金").strip()
        # v116 提纯分支：『炼金 提纯 [页]』仅列出提纯配方（purify=True，3 份低档 → 1 份高档）
        purify_only = "提纯" in raw
        if purify_only:
            raw = raw.replace("提纯", "").strip()
        page = int(raw) if raw.isdigit() else 1
        prof_lv = db.get_prof_level(group_id, qq_id, "alchemy")
        # purify_only False → 只列普通配方；True → 只列提纯配方
        recs = [(k, r) for k, r in _clife.ALCHEMY_RECIPES.items()
                if (r.get("purify") is True) == purify_only]
        recs.sort(key=lambda x: x[1].get("min_lv", 1))
        page_items, pages, page = self._page_items(recs, page, per_page=5)
        title = "🧪 【炼金工坊·提纯】(3 份低档 → 1 份高档)材料提纯配方：" if purify_only else f"🧪 【炼金工坊】(炼金 Lv.{prof_lv})材料合成配方："
        lines = [title, "━━━━━━━━━━━━"]
        base = (page - 1) * 5
        for i, (rname, r) in enumerate(page_items, 1):
            def _mname(k):
                return C.display("materials", k) if k.startswith("mat_") else C.display("items", k)
            cost = " + ".join(f"{_mname(m)}×{c}" for m, c in r["cost"].items())
            pname = next(iter(r["product"]))
            pname2 = _mname(pname)
            need = r.get("min_lv", 1)
            mark = "✅" if prof_lv >= need else "🔒"
            # v124 图纸学习制：带 blueprint 的配方未学习时标注（合成时拦截）
            if r.get("blueprint") and r["blueprint"] not in (player.get("learned_blueprints") or []):
                mark += " 📜未学"
            lines.append(f"{base + i:>2}. {mark} {C.display('alchemy', rname)}：{cost} → {pname2}  [炼金Lv.{need}]")
            lines.append(f"    {r['desc']}")
        lines.append("━━━━━━━━━━━━")
        nxt = ""
        if page < pages:
            nxt = f"｜『炼金 提纯 {page + 1}』下一页" if purify_only else f"｜『炼金 {page + 1}』下一页"
        lines.append(f"📄 第 {page}/{pages} 页{nxt}")
        self._record_list_state(qq_id, "炼金 提纯" if purify_only else "炼金", page, pages)
        lines.append(self._tip("alchemy"))
        yield event.plain_result("\n".join(lines))

    @declared("alchemy_craft")
    @require_player()

    async def alchemy_craft(self, event: AstrMessageEvent):
        group_id, qq_id = self._uid(event)
        player = self._player(group_id, qq_id)
        ok, act_msg = self._prof_active_check(group_id, qq_id, "alchemy", require_apprentice=True)
        if not ok:
            yield event.plain_result(act_msg)
            return
        rname = self._strip_cmd(event, "合成").strip()
        if not rname:
            yield event.plain_result("格式：合成 <配方名>！『炼金』查看全部配方～")
            return
        # v130.7 意见#30：『合成 <序号>』= 『炼金』面板第 N 个配方（取数列表与面板同源：非提纯 + min_lv 排序）
        if rname.isdigit():
            idx = int(rname)
            _recs = [(k, r) for k, r in _clife.ALCHEMY_RECIPES.items() if r.get("purify") is not True]
            _recs.sort(key=lambda x: x[1].get("min_lv", 1))
            if idx < 1 or idx > len(_recs):
                yield event.plain_result(f"没有第 {idx} 个炼金配方(共 {len(_recs)} 个)！『炼金』查看～")
                return
            rname = _recs[idx - 1][0]
        # v48：配方 key 已是 ID，用户输入中文名需 resolve
        rkey = C.resolve("alchemy", rname)
        r = _clife.ALCHEMY_RECIPES.get(rkey)
        if not r:
            yield event.plain_result(f"没有『{rname}』这个配方！『炼金』查看全部～")
            return
        # v54 副业等级限制
        prof_lv = db.get_prof_level(group_id, qq_id, "alchemy")
        need = r.get("min_lv", 1)
        if prof_lv < need:
            yield event.plain_result(
                f"【{C.display('alchemy', rkey)}】需要炼金 Lv.{need}，你才 Lv.{prof_lv}！多合成低级配方升级炼金吧～"
            )
            return
        # v124 图纸学习制：带 blueprint 的炼金配方需先『学习』（与锻造一致）
        if r.get("blueprint"):
            bp_name = r["blueprint"]
            if bp_name not in (player.get("learned_blueprints") or []):
                have_bp = db.count_item(group_id, qq_id, bp_name)
                if have_bp >= 1:
                    yield event.plain_result(
                        f"你背包里有『{bp_name}』！输入『学习 {bp_name}』解锁配方后就能永久合成了～"
                    )
                else:
                    yield event.plain_result(
                        f"【{C.display('alchemy', rkey)}】需要先学习配方『{bp_name}』(支线奖励获取)！『学习 <图纸名>』永久解锁。"
                    )
                return
        items = db.get_inventory(group_id, qq_id)
        # 检查材料是否够（背包 data.name 存中文，r.cost key 是 ID）
        # v105R3 M13 P1-2：材料校验在扣体力之前——材料不足不再白扣 10 体力
        #（与锻造/强化/附魔对齐：所有校验通过后才扣，v104 只修了 3/8 条）
        for mat, cnt in r["cost"].items():
            mname = C.display("materials", mat)
            have = sum(it["count"] for it in items if it["data"].get("name") == mname)
            if have < cnt:
                yield event.plain_result(f"材料不足！需要 {mname}×{cnt}(你有 {have})")
                return
        # v94 体力：炼金合成消耗 10 体力（材料校验通过后才扣）
        _ok, _st = self._spend_stamina(group_id, qq_id, _clife.PROF_STAMINA_COST["alchemy"], player, "炼金")
        if not _ok:
            yield event.plain_result(_st)
            return
        # 扣除材料
        for mat, cnt in r["cost"].items():
            mname = C.display("materials", mat)
            remain = cnt
            for it in items:
                if remain <= 0:
                    break
                if it["data"].get("name") == mname:
                    take = min(it["count"], remain)
                    db.remove_item(group_id, qq_id, it["key"], take)
                    remain -= take
        # 发放产物（v48：product key 已是 ID，直接按 ID 入库）
        # G0-A1：注入 craft_cost=材料总成本，使 _sell_one 卖店封顶（售价≤成本），堵炼金→卖店净正收益；
        # 产物售价数据高于成本时下调注入价至 ≤0.9×成本（仅影响卖店回收，不改产物效果/正常消耗）
        _cc = sum(_cit.MATERIALS.get(m, {}).get("price", 0) * cnt for m, cnt in r["cost"].items())
        _cc_price_floor = round(0.9 * _cc) if _cc > 0 else None
        lines = []
        for pkey, pcnt in r["product"].items():
            if pkey.startswith("mat_"):
                mname = C.display("materials", pkey)
                # v125.2 B3：产物价格兜底读 prof_config.RARE_MATERIAL_PRICE（原字面量 150，行为等价）
                _mprice = _cit.MATERIALS.get(pkey, {}).get("price", _clife.RARE_MATERIAL_PRICE)
                db.add_item(group_id, qq_id, pkey, {"name": mname, "type": _cit.MATERIALS.get(pkey, {}).get("type", "材料"), "stackable": True, "price": _mprice if _cc_price_floor is None or _mprice <= _cc_price_floor else _cc_price_floor, "craft_cost": _cc})
                lines.append(f"  🎒 获得材料：{mname} ×{pcnt}")
            else:
                itdef = _cit.ITEMS.get(pkey, {})
                _iprice = itdef.get("price", 100)
                if _cc_price_floor is not None and _iprice > _cc_price_floor:
                    _iprice = _cc_price_floor
                # v104 M08 P2-9：产物全字段拷贝（原只拷 heal/mana/effect/stamina 四字段，
                # 未来配方加 hot/food_effect/affix 等即静默丢失——与 M09-P0 商店路径同类坑）
                db.add_item(group_id, qq_id, pkey, {"name": itdef.get("name", pkey), "type": "消耗品", "stackable": True,
                                                    "price": _iprice, "craft_cost": _cc,
                                                    **{k: v for k, v in itdef.items() if k not in ("name", "price")}},
                               count=pcnt)
                lines.append(f"  🎒 获得：{itdef.get('name', pkey)} ×{pcnt}")
        # 副业经验（炼金成功 +1）
        new_lv, leveled = db.add_prof_exp(group_id, qq_id, "alchemy", 1)
        lv_msg = ""
        if leveled:
            lv_msg = f"\n🌟 炼金等级提升到 Lv.{new_lv}！"
        # 每日任务推进
        _done, _msg = self._daily_prof_bump(group_id, qq_id, "alchemy")
        lv_msg += _msg
        # 阶段九：炼金次数 + 成就判定
        db.bump_stats(group_id, qq_id, alchemy_count=1)
        C.check_achievements(group_id, qq_id, player)
        # v97.5 行为彩蛋规则：炼金成功后
        _rule_txt = self._rule_fire("craft_done", group_id, qq_id, player,
                                    _cspace.MAP_BY_ID.get(player["cur_map"], {}))
        # v116 提纯：purify 配方用『提纯成功』专属提示（凑 3 份低档 → 1 份高档）
        if r.get("purify"):
            _cost_txt = " + ".join(f"{C.display('materials', cm)}×{cc}" for cm, cc in r["cost"].items())
            _prod_txt = " + ".join(f"{C.display('materials', pm)}×{pc}" for pm, pc in r["product"].items())
            success_head = f"🧪 提纯成功！{_cost_txt} → {_prod_txt}【{C.display('alchemy', rkey)}】"
        else:
            success_head = f"🧪 【炼金成功】合成了【{C.display('alchemy', rkey)}】！"
        yield event.plain_result(act_msg + success_head + "\n" + "\n".join(lines) + lv_msg
                                 + (f"\n{_rule_txt}" if _rule_txt else ""))

    @declared("cooking_list")
    @require_player()

    async def cooking_list(self, event: AstrMessageEvent):
        """烹饪配方列表(按烹饪等级解锁，v101.30 加翻页)"""
        group_id, qq_id = self._uid(event)
        player = self._player(group_id, qq_id)
        cook_lv = db.get_prof_level(group_id, qq_id, "cooking")
        raw = self._strip_cmd(event, "烹饪列表").strip()
        page = int(raw) if raw.isdigit() else 1
        recs = list(_clife.COOKING_RECIPES.items())
        page_items, pages, page = self._page_items(recs, page, per_page=5)
        lines = ["🍳 【烹饪灶台】料理配方：", "━━━━━━━━━━━━"]
        base = (page - 1) * 5
        for i, (rkey, r) in enumerate(page_items, 1):
            lock = "" if cook_lv >= r["min_lv"] else " 🔒"
            # v124 图纸学习制：带 blueprint 的食谱未学习时标注（烹饪时拦截）
            if r.get("blueprint") and r["blueprint"] not in (player.get("learned_blueprints") or []):
                lock += " 📜未学"
            def _mname(k):
                # v105R3 M16 P3-1：全部 cost 已 mat_ ID 化（v48），fish 分支死——
                # 改 items 兜底（i_ 前缀材料如强化石也能正确显示）
                return C.display("materials", k) if k.startswith("mat_") else C.display("items", k)
            cost = " + ".join(f"{_mname(m)}×{c}" for m, c in r["cost"].items())
            lines.append(f"{base + i:>2}. {r['name']}(烹饪Lv.{r['min_lv']}){lock}")
            lines.append(f"    {cost} → {C.display('items', next(iter(r['product'])))}")
        lines.append("")
        lines.append(f"📄 第 {page}/{pages} 页" + (f"｜『烹饪列表 {page + 1}』下一页" if page < pages else ""))
        self._record_list_state(qq_id, "烹饪列表", page, pages)
        lines.append(self._tip("cooking"))
        lines.append("💡 烹饪等级：采集植物 + 垂钓 → 料理，成功制作＋1 经验")
        yield event.plain_result("\n".join(lines))

    @declared("cooking")
    @require_player()

    async def cooking(self, event: AstrMessageEvent):
        group_id, qq_id = self._uid(event)
        player = self._player(group_id, qq_id)
        ok, act_msg = self._prof_active_check(group_id, qq_id, "cooking", require_apprentice=True)
        if not ok:
            yield event.plain_result(act_msg)
            return
        raw = self._strip_cmd(event, "烹饪").strip()
        if not raw or raw == "列表":
            yield event.plain_result("发『烹饪列表』查看全部料理配方～(如：烹饪 蛇羹)")
            return
        # v130.7 意见#30：『烹饪 <序号>』= 『烹饪列表』面板第 N 道料理（取数列表与面板同源：COOKING_RECIPES 插入序）
        if raw.isdigit():
            idx = int(raw)
            _recs = list(_clife.COOKING_RECIPES.items())
            if idx < 1 or idx > len(_recs):
                yield event.plain_result(f"没有第 {idx} 道料理(共 {len(_recs)} 道)！『烹饪列表』查看～")
                return
            raw = _recs[idx - 1][0]
        rkey = C.resolve("cooking", raw)
        r = _clife.COOKING_RECIPES.get(rkey)
        if not r:
            # v113.5 O86：自制料理带"(自制)"后缀（如『烤肉串(自制)』），输入基础名
            # 『烹饪 烤肉串』解析不到——失败提示列出带后缀的完整名，引导正确指令
            full = list(dict.fromkeys(
                rec["name"] for rec in _clife.COOKING_RECIPES.values()
                if rec.get("name") == raw + "(自制)" or rec.get("name", "").startswith(raw + "(")))
            if full:
                yield event.plain_result(
                    f"没有『{raw}』这道料理！你是不是想烹饪『{full[0]}』？发『烹饪 {full[0]}』试试～")
            else:
                yield event.plain_result(f"没有『{raw}』这道料理！『烹饪列表』查看全部～")
            return
        cook_lv = db.get_prof_level(group_id, qq_id, "cooking")
        if cook_lv < r["min_lv"]:
            yield event.plain_result(f"【{r['name']}】需要烹饪 Lv.{r['min_lv']}，你才 Lv.{cook_lv}。多做简单料理提升吧！")
            return
        # v124 图纸学习制：带 blueprint 的食谱需先『学习』（与锻造一致）
        if r.get("blueprint"):
            bp_name = r["blueprint"]
            if bp_name not in (player.get("learned_blueprints") or []):
                have_bp = db.count_item(group_id, qq_id, bp_name)
                if have_bp >= 1:
                    yield event.plain_result(
                        f"你背包里有『{bp_name}』！输入『学习 {bp_name}』解锁食谱后就能永久烹饪了～"
                    )
                else:
                    yield event.plain_result(
                        f"【{r['name']}】需要先学习食谱『{bp_name}』(支线奖励获取)！『学习 <图纸名>』永久解锁。"
                    )
                return
        # 检查材料（v48 起全部 cost 已是 mat_/i_ ID，无 fish_ 中文 key）
        # v105R3 M13 P1-2：食材校验在扣体力之前——食材不足不再白扣 5 体力
        #（与锻造/强化/附魔对齐：所有校验通过后才扣，v104 只修了 3/8 条）
        lack = []
        for m, cnt in r["cost"].items():
            have = db.count_item(group_id, qq_id, m)
            if have < cnt:
                mname = C.display("materials", m) if m.startswith("mat_") else C.display("items", m)
                lack.append(f"{mname}×{cnt}(你有{have})")
        if lack:
            yield event.plain_result(f"食材不足！做【{r['name']}】还缺：{'、'.join(lack)}。垂钓/采集收集食材～")
            return
        # v101.30 体力：烹饪消耗 5 体力（食材校验通过后才扣；制造副业半价，亲民入口）
        _ok, _st = self._spend_stamina(group_id, qq_id, _clife.PROF_STAMINA_COST["cooking"], player, "烹饪")
        if not _ok:
            yield event.plain_result(_st)
            return
        # 扣食材：v104 P2-5 修复——对齐炼金用 remain 循环跨堆扣取。
        # 旧逻辑只扣第一匹配堆（count<=需求时 remove_item 整行 DELETE 且剩余不扣），
        # 同种材料跨 key/重复堆存在时白嫖材料；remove_item 失败（如旧档中文 key 行
        # 归一化后查不到）不计数，最后不足则整次制作失败并回滚已扣。
        items = db.get_inventory(group_id, qq_id)
        deducted = []
        for m, cnt in r["cost"].items():
            mname = C.display("materials", m) if m.startswith("mat_") else C.display("items", m)
            remain = cnt
            # v104R3 P1-2：先按 key 精确扣取（同名消耗品如『圣水』i_holy_water 不得
            # 顶替材料 mat_sheng_shui——校验按 key 通过后按名扣会错扣堆），key 不足再按名兜底
            # v104R3 M08 P2-3：i_holy_water_drink 已改名『圣堂净水』，不再与材料重名
            for it in items:
                if remain <= 0:
                    break
                if it["key"] != m:
                    continue
                take = min(it["count"], remain)
                if db.remove_item(group_id, qq_id, it["key"], take):
                    deducted.append((it["key"], it["data"], take))
                    remain -= take
            for it in items:
                if remain <= 0:
                    break
                if it["key"] == m or it["data"].get("name") != mname:
                    continue
                take = min(it["count"], remain)
                if db.remove_item(group_id, qq_id, it["key"], take):
                    deducted.append((it["key"], it["data"], take))
                    remain -= take
            if remain > 0:
                # 防御分支（正常不可达：上方 count_item 已校验总量）：回滚已扣，整次失败
                for rkey, rdata, rcnt in deducted:
                    db.add_item(group_id, qq_id, rkey, rdata, count=rcnt)
                yield event.plain_result(f"食材不足！做【{r['name']}】还缺：{mname}×{remain}，已回滚扣除。垂钓/采集收集食材～")
                return
        # 发料理（读 ITEMS 定义；v101.28i 修复：必须带全效果字段 food_effect/hot/hot_turns/hot_mana，
        # 否则烹饪出的词条料理在战斗里没有特殊效果）
        pkey = next(iter(r["product"]))
        itdef = _cit.ITEMS.get(pkey, {})
        # G0-A1：注入 craft_cost=食材总成本（食材可为 mat_ 材料或 i_ 道具），使 _sell_one 卖店
        # 封顶（售价≤成本），堵烹饪→卖店净正收益；产物售价数据高于成本时下调注入价至 ≤0.9×成本
        _cc = 0
        for _m, _cnt in r["cost"].items():
            if _m.startswith("mat_"):
                _cc += _cit.MATERIALS.get(_m, {}).get("price", 0) * _cnt
            else:
                _cc += _cit.ITEMS.get(_m, {}).get("price", 0) * _cnt
        _cc_price_floor = round(0.9 * _cc) if _cc > 0 else None
        _iprice = itdef.get("price", 10)
        if _cc_price_floor is not None and _iprice > _cc_price_floor:
            _iprice = _cc_price_floor
        # v104R3 M16 P2-4：入库带 desc——自制词条料理的【吸血】【护盾】【回春】等
        # 战斗效果在背包详情可见（原只拷效果字段无 desc，渲染器兜底只能算 heal/mana）
        _fx_fields = ("heal", "mana", "effect", "stamina", "hot", "hot_turns", "hot_mana", "food_effect", "desc")
        _item_kwargs = {k: v for k, v in itdef.items() if k in _fx_fields}
        # v101.30b Lv.10 食神：完美料理 10%（恢复/持续强度 ×1.5，效果类不变；时长不变）
        _perfect_line = ""
        if cook_lv >= 10 and random.random() < 0.10:
            for _fk in ("heal", "mana", "hot", "hot_mana"):
                if _fk in _item_kwargs:
                    _item_kwargs[_fk] = round(_item_kwargs[_fk] * 1.5, 3)
            # v105R3 M16 P3-4：完美料理 desc 追加 ×1.5 标注——播报与背包详情
            # 不再显示未增强旧数值误导（效果字段已 ×1.5，desc 原文数值脱节）
            _item_kwargs["desc"] = itdef.get("desc", "") + "（完美料理：上述效果 ×1.5）"
            _perfect_line = " ✨完美料理！效果提升 50%！"
        db.add_item(group_id, qq_id, pkey, {"name": itdef.get("name", pkey), "type": "消耗品", "stackable": True, "price": _iprice, "craft_cost": _cc, **_item_kwargs})
        # 副业经验
        new_lv, leveled = db.add_prof_exp(group_id, qq_id, "cooking", 1)
        lv_msg = ""
        if leveled:
            lv_msg = f"\n🌟 烹饪等级提升到 Lv.{new_lv}！"
        # 每日任务推进
        _done, _msg = self._daily_prof_bump(group_id, qq_id, "cooking")
        lv_msg += _msg
        # 阶段九：烹饪次数 + 成就判定
        db.bump_stats(group_id, qq_id, cook_count=1)
        C.check_achievements(group_id, qq_id, player)
        # v97.5 行为彩蛋规则：烹饪成功后
        _rule_txt = self._rule_fire("craft_done", group_id, qq_id, player,
                                    _cspace.MAP_BY_ID.get(player["cur_map"], {}))
        yield event.plain_result(act_msg + f"🍳 灶火升腾，香气四溢……\n"
            f"✅ 烹饪成功！【{itdef.get('name', pkey)}】({_item_kwargs.get('desc', '')})已放入背包！{_perfect_line}{lv_msg}"
            + (f"\n{_rule_txt}" if _rule_txt else "")
        )

    @declared("bp_craft")
    @require_player()

    async def bp_craft(self, event: AstrMessageEvent):
        """v135 图纸残页合成：『图纸合成 <装备名>』——消耗 10 张图纸残页，
        定向合成 1 张指定装备的图纸（玩家可定向获取图纸，残页走经济闭环）。
        v167.2：可合成池按"配方存在"硬过滤（rid ∈ _RECIPE_ROSTER_IDS），只列出
        有 CRAFT_RECIPES 锻造配方的装备——杜绝合成出无配方/学不了的死图纸。

        支持：
        - 『图纸合成』无参 → 列出可合成的图纸池（名册 source=图纸/boss 且有锻造配方）
        - 『图纸合成 <装备名>』 → 消耗 10 张图纸残页，获得该装备图纸（未学整张入包）
        只允许名册 source=图纸/boss 且配方存在（roll_blueprint 同池）的装备，商店/锻造/支线装备不可定向合成。
        """
        group_id, qq_id = self._uid(event)
        player = self._player(group_id, qq_id)
        raw = self._strip_cmd(event, "图纸合成").strip()
        items = db.get_inventory(group_id, qq_id)
        # 图纸残页库存（key=mat_tu_zhi_can_ye 或按名兜底）
        _shard_key = "mat_tu_zhi_can_ye"
        _shards = sum(it["count"] for it in items
                      if it["key"] == _shard_key or it["data"].get("name") == "图纸残页")
        # 可合成图纸池：名册 source=图纸/boss 且配方存在（rid ∈ _RECIPE_ROSTER_IDS，
        # v167.2 硬过滤——杜绝合成出无 CRAFT_RECIPES 配方的死图纸；
        # 原 'rid in EQUIP_ROSTER_BY_NAME[name]' 恒真（rid 必在自己 by_name 列表里）已废弃）
        _cands = [(rid, r) for rid, r in _cit.EQUIP_ROSTER.items()
                  if r["source"] in ("图纸", "boss") and rid in _RECIPE_ROSTER_IDS]
        _cands.sort(key=lambda x: x[1]["lv"])
        if not raw:
            page = 1
            page_items, pages, page = self._page_items(_cands, page, per_page=5)
            lines = [f"📜 【图纸残页合成】(图纸残页×{_shards}/10)", "━━━━━━━━━━━━"]
            for i, (rid, r) in enumerate(page_items, 1):
                q = _b143.QUALITY.get(r["quality"], {})
                lines.append(f"{(page - 1) * 5 + i:>2}. {q.get('color', '')}【{r['name']}】Lv.{r['lv']} {_b143.EQUIP_SLOTS.get(r['slot'], r['slot'])}")
            lines.append("━━━━━━━━━━━━")
            lines.append(f"📄 第 {page}/{pages} 页" + (f"｜『图纸合成 {page + 1}』下一页" if page < pages else ""))
            lines.append(f"💡 『图纸合成 <装备名>』消耗 10 张图纸残页，定向获得 1 张指定图纸（只列出有锻造配方的装备）")
            if _shards < 10:
                lines.append(f"🈳 图纸残页不足(你有 {_shards}/10)——Boss/宝箱/垂钓/副本掉落或已学图纸折算")
            yield event.plain_result("\n".join(lines))
            return
        # 数字 → 面板第 N 件
        if raw.isdigit():
            idx = int(raw)
            if idx < 1 or idx > len(_cands):
                yield event.plain_result(f"没有第 {idx} 件可合成装备(共 {len(_cands)} 件)！『图纸合成』查看～")
                return
            raw = _cands[idx - 1][1]["name"]
        # 解析装备：名册名精确/包含匹配（限制 source=图纸/boss）
        _hit = [rid for rid, r in _cands if r["name"] == raw]
        if not _hit:
            _hit = [rid for rid, r in _cands if raw in r["name"]]
        if not _hit:
            yield event.plain_result(
                f"没有『{raw}』这个可合成的装备图纸！『图纸合成』查看全部可合成图纸（仅图纸/Boss 来源装备可定向合成）～")
            return
        rid = _hit[0]
        r = _cit.EQUIP_ROSTER[rid]
        if _shards < 10:
            yield event.plain_result(f"图纸残页不足！合成【{r['name']}图纸】需要 10 张图纸残页，你有 {_shards} 张。"
                                     f"Boss/宝箱/垂钓/副本掉落，或已学图纸自动折算～")
            return
        # 扣 10 张残页（跨堆扣取，key 优先 + 名字兜底）
        remain = 10
        for it in items:
            if remain <= 0:
                break
            if it["key"] == _shard_key:
                take = min(it["count"], remain)
                if db.remove_item(group_id, qq_id, it["key"], take):
                    remain -= take
        for it in items:
            if remain <= 0:
                break
            if it["key"] == _shard_key or it["data"].get("name") != "图纸残页":
                continue
            take = min(it["count"], remain)
            if db.remove_item(group_id, qq_id, it["key"], take):
                remain -= take
        if remain > 0:
            yield event.plain_result(f"图纸残页不足！需要 10 张，你有 {_shards} 张。")
            return
        bp = C.make_blueprint(rid)
        import uuid
        db.add_item(group_id, qq_id, f"bp_{uuid.uuid4().hex[:8]}", bp)
        q = _b143.QUALITY.get(r["quality"], {})
        yield event.plain_result(
            f"📜 10 张图纸残页在掌中拼合，微光闪过——\n"
            f"✅ 合成成功！获得【{bp['name']}】({q.get('name', '')}·Lv.{r['lv']})\n"
            f"💡 『学习 {bp['name']}』永久解锁锻造配方！"
        )

    # ---------------- 等待型副业（v181.P4-7：业务迁 services/profession.py，本区只留薄转发） ----------------
    # v127.5 前方法名保留为命令层兼容壳（gather/mining/fishing/prof_forget/use 等命令直接调 self._xxx）；
    # 函数体 = 一行转调 _prof_svc.<同名>（每日任务推进/tips/彩蛋/广播等命令层能力以注入参数传入）。

    # v181.P4-7：垂钓惊喜概率表/档位边界（v168.2，原类属性）已随迁 services/profession.py
    # （FISHING_SURPRISE_*，单一数据源）；此处保留等价类属性，兼容 test_v135_bp_drop
    # 源码结构断言（值逐字符等价，行为零变化）
    _FISHING_SURPRISE_TRIGGER = _prof_svc.FISHING_SURPRISE_TRIGGER
    _FISHING_SURPRISE_BP = 0.30
    _FISHING_SURPRISE_EQ = 0.55
    _FISHING_SURPRISE_RUNE = 0.75
    _FISHING_SURPRISE_GEM = 0.90

    def _gather_roll(self, level: int, prof_lv: int = 1, cur_map: str = "") -> list:
        """v181.P4-7：转发 services.profession.gather_roll（economy 本地定义已随迁）"""
        return _prof_svc.gather_roll(level, prof_lv, cur_map)

    def _gather_cond_roll(self, cur_map: str):
        """v181.P4-7：转发 services.profession.gather_cond_roll（economy 本地定义已随迁）"""
        return _prof_svc.gather_cond_roll(cur_map)

    def _prof_wait_key(self, group_id, qq_id):
        """v181.P4-7：转发 services.profession.prof_wait_key"""
        return _prof_svc.prof_wait_key(group_id, qq_id)

    @staticmethod
    def _prof_wait_ev_name(qq_id):
        """v181.P4-7：转发 services.profession.prof_wait_ev_name"""
        return _prof_svc.prof_wait_ev_name(qq_id)

    @staticmethod
    def _prof_wait_compat(ev):
        """v181.P4-7：转发 services.profession.prof_wait_compat"""
        return _prof_svc.prof_wait_compat(ev)

    def _prof_wait_residual(self, group_id, qq_id):
        """v181.P4-7：转发 services.profession.prof_wait_residual"""
        return _prof_svc.prof_wait_residual(group_id, qq_id)

    def _prof_wait_state(self, group_id, qq_id):
        """v181.P4-7：转发 services.profession.prof_wait_state"""
        return _prof_svc.prof_wait_state(group_id, qq_id)

    def _prof_wait_clear(self, group_id, qq_id):
        """v181.P4-7：转发 services.profession.prof_wait_clear"""
        return _prof_svc.prof_wait_clear(group_id, qq_id)

    def _prof_wait_duration(self, prof_type, prof_lv):
        """v181.P4-7：转发 services.profession.prof_wait_duration"""
        return _prof_svc.prof_wait_duration(prof_type, prof_lv)

    def _prof_wait_begin(self, event, group_id, qq_id, prof_type, extra=None):
        """v181.P4-7：转发 services.profession.prof_wait_begin（延迟推送注入 = 命令层 async 壳）。

        原实现：try 拿 event loop → create_task(self._prof_delayed_push(...))；无 loop 静默。
        service 版：delayed_push 注入 = lambda 包 create_task（等位逻辑，见 _prof_delayed_push 壳）。
        """
        _ps = _h('_prof_svc')  # ← from ..services import profession as _ps
        def _dp(gid, qid, st, wait):
            try:
                asyncio.create_task(self._prof_delayed_push(event, gid, qid, st, wait))
            except Exception:
                pass  # 无事件循环/任务创建失败 → 惰性结算兜底（与原实现等价）
        return _ps.prof_wait_begin(
            group_id, qq_id, prof_type, extra,
            delayed_push=_dp,
            duration=lambda pt, lv: self._prof_wait_duration(pt, lv),
        )

    async def _prof_delayed_push(self, event, group_id, qq_id, st, wait):
        """v181.P4-7：转发 services.profession.prof_delayed_push（event.send 推送壳）。

        延迟结算并主动推送结果(尽力而为；进程重启/推送失败由惰性结算兜底)。
        v127.5：到点后引擎已 lazy 清除事件，结算数据从 residual（引擎存储残留）取。
        send 注入 = event.send(MessageChain([Plain(text)]))（原 _prof_delayed_push 推送 I/O）。
        """
        _ps = _h('_prof_svc')  # ← from ..services import profession as _ps
        async def _settle_fn(gid, qid, cur):
            return self._prof_settle(gid, qid, cur)
        async def _send_fn(text):
            await event.send(MessageChain([Plain(text)]))
        await _ps.prof_delayed_push(group_id, qq_id, st, wait,
                                    settle=_settle_fn, send=_send_fn)

    def _prof_settle(self, group_id, qq_id, st):
        """v181.P4-7：转发 services.profession.prof_settle（rule_fire 彩蛋 + 分型结算注入）。

        原 _rule_fire("gather_done",...) 命令层行为彩蛋：service 收 rule_fire 注入。
        """
        _ps = _h('_prof_svc')  # ← from ..services import profession as _ps
        def _rf(trigger, gid, qid, p, cm, evt):
            return self._rule_fire(trigger, gid, qid, p, cm, evt)
        return _ps.prof_settle(
            group_id, qq_id, st,
            rule_fire=_rf,
            settle_fishing=self._settle_fishing,
            settle_gather=self._settle_gather,
            settle_mining=self._settle_mining,
            clear=self._prof_wait_clear,
        )

    def _fish_legend_broadcast(self, group_id, qq_id, player, fname, spot):
        """v181.P4-7：settle_fishing hooks["legend"] 注入源（原 economy._fish_legend_broadcast 本体）。

        v104 R3 M15 P2-1：传说档全服广播（13 章 2.6：鱼王 + 古代鱼骨；史诗静默防刷屏）。
        settle_fishing 为同步函数（惰性结算/延迟推送两条路径都可能触发），广播用
        fire-and-forget：有事件循环则 create_task，无（测试环境）静默跳过。
        """
        try:
            asyncio.get_running_loop()
            pname = (player or {}).get("name") or str(qq_id)
            asyncio.create_task(self._broadcast(
                f"📢 【传说】玩家 {pname} 在{spot}钓上了【{fname}】！！全服为之震动！"
            ))
        except Exception:
            pass

    def _settle_fishing(self, group_id, qq_id, st):
        """v181.P4-7：转发 services.profession.settle_fishing（hooks.legend 广播注入）"""
        _ps = _h('_prof_svc')  # ← from ..services import profession as _ps
        return _ps.settle_fishing(
            group_id, qq_id, st,
            hooks={"legend": self._fish_legend_broadcast},
            daily_prof_bump=self._daily_prof_bump,
        )

    def _fishing_surprise(self, group_id, qq_id, player, fish, force_legend=False):
        """v181.P4-7：转发 services.profession.fishing_surprise_fn"""
        return _prof_svc.fishing_surprise_fn(group_id, qq_id, player, fish, force_legend)

    def _collect_bonus_line(self, group_id, qq_id, player, cf):
        """v181.P4-7：转发 services.profession.collect_bonus_line"""
        return _prof_svc.collect_bonus_line(group_id, qq_id, player, cf)

    def _settle_gather(self, group_id, qq_id, st):
        """v181.P4-7：转发 services.profession.settle_gather（collect_any/tip/daily 注入）"""
        _ps = _h('_prof_svc')  # ← from ..services import profession as _ps
        return _ps.settle_gather(
            group_id, qq_id, st,
            daily_prof_bump=self._daily_prof_bump,
            collect_any_bump=self._bump_daily_progress,
            tip=self._tip,
        )

    def _mining_fatigue_state(self, group_id, qq_id):
        """v181.P4-7：转发 services.profession.mining_fatigue_state"""
        return _prof_svc.mining_fatigue_state(group_id, qq_id)

    def _mining_fatigue_tick(self, group_id, qq_id):
        """v181.P4-7：转发 services.profession.mining_fatigue_tick"""
        return _prof_svc.mining_fatigue_tick(group_id, qq_id)

    def _mining_fatigued(self, group_id, qq_id):
        """v181.P4-7：转发 services.profession.mining_fatigued"""
        return _prof_svc.mining_fatigued(group_id, qq_id)

    def _settle_mining(self, group_id, qq_id, st):
        """v181.P4-7：转发 services.profession.settle_mining（daily 注入）"""
        _ps = _h('_prof_svc')  # ← from ..services import profession as _ps
        return _ps.settle_mining(group_id, qq_id, st, daily_prof_bump=self._daily_prof_bump)

    def _prof_wait_flow(self, event, group_id, qq_id, prof_type, extra=None, begin_text=""):
        """v181.P4-7：转发 services.profession.prof_wait_flow（settle/begin 注入=命令层壳）"""
        _ps = _h('_prof_svc')  # ← from ..services import profession as _ps
        return _ps.prof_wait_flow(
            group_id, qq_id, prof_type, extra, begin_text,
            settle=lambda g, q, s: self._prof_settle(g, q, s),
            begin=lambda g, q, pt, ex: self._prof_wait_begin(event, g, q, pt, ex),
        )

    def _prof_active_check(self, group_id, qq_id, key, require_apprentice=False):
        """v167 副业解除数量上限：动作前检查副业是否激活。

        未激活 → 直接自动激活（永不因数量拦截；可无限学/无限发展副业）。
        老玩家兼容：已有等级（>1）未激活 → 自动激活无感迁移。
        v95.22：require_apprentice=True（副业动作）时，未拜师 → 拦截并引导找导师，
        副业必须先找导师 NPC 拜师学习（对话 unlock_prof）才解锁。
        返回 (ok, 提示消息)
        """
        lst = db.get_activated_profs(group_id, qq_id)
        if key in lst:
            return True, ""
        # v167：原 v67 位满拦截分支（len(lst) >= MAX_ACTIVE_PROFS 时 return False）已删除——
        # 副业不再限制激活数量，未激活一律自动激活；拜师门槛见下方 require_apprentice 检查。
        # 老玩家兼容：已有等级（>1）未激活 → 自动激活无感迁移
        lv = db.get_prof_level(group_id, qq_id, key)
        if lv > 1:
            db.activate_prof(group_id, qq_id, key)
            return True, ""
        # v95.22 副业动作需先拜师：未拜师 → 引导找导师学习（已拜师则正常激活）
        if require_apprentice:
            player = self._player(group_id, qq_id) or {}
            if key not in (player.get("apprentices") or []):
                tname, tmap = _clife.PROF_TUTORS.get(key, ("对应导师", "对应城市"))
                return False, (
                    f"🔒 副业「{db.PROF_FIELDS.get(key, key)}」还没解锁！\n"
                    f"先去 {tmap} 找 {tname} 拜师学习吧～(『对话 {tname}』)"
                )
        db.activate_prof(group_id, qq_id, key)
        new_lst = db.get_activated_profs(group_id, qq_id)
        return True, f"\n🔓 你选择了「{db.PROF_FIELDS.get(key, key)}」作为副业(当前已激活 {len(new_lst)} 条)！"

    @declared("profession_view")
    @require_player()

    async def profession_view(self, event: AstrMessageEvent):
        group_id, qq_id = self._uid(event)
        player = self._player(group_id, qq_id)
        raw = self._strip_cmd(event, "副业").strip()
        if "排行" in raw:
            yield event.plain_result(self._prof_rank_text(group_id))
            return
        profs = db.get_professions(group_id, qq_id)
        activated = db.get_activated_profs(group_id, qq_id)
        lines = [f"🧵 【副业面板】(当前已激活 {len(activated)} 条)", "━━━━━━━━━━━━"]
        icons = {"gather": "🌿", "mining": "⛏️", "fishing": "🎣", "alchemy": "🧪", "craft": "🔨", "cooking": "🍳", "enhance": "⚒️", "enchant": "✨"}
        total = 0
        for key, p in profs.items():
            if key not in activated:
                # v105R3 M13 P3-4 修订（v113.5 T1）：按鱼鱼要求，副业面板不显示未激活副业——
                # 原设计"显示：已激活/未激活/等级"(19 章 §4.2)取消，面板只列已解锁副业，
                # 未激活副业静默跳过（不再打印 🔒未激活 行）
                continue
            total += p["lv"]  # v113.6：总分只计已激活副业（未激活不计分，与排行同口径）
            if p["lv"] >= 10:
                # v104 P2 修复：满级不画经验条（lv>=10 时 exp 恒 0，旧版显示空条 0/200）
                lines.append(f"{icons.get(key, '·')} {p['name']}：Lv.{p['lv']} 已满级 ✅")
                continue
            need = C.prof_exp_need(p["lv"])
            bar_len = min(10, p["exp"] // (need // 10 + 1))
            bar = "█" * bar_len + "░" * (10 - bar_len)
            lines.append(f"{icons.get(key, '·')} {p['name']}：Lv.{p['lv']}  {bar} {p['exp']}/{need} 经验 ✅")
        if not activated:
            lines.append("还没有解锁任何副业！去城里找对应导师拜师学习吧～")
        lines.append("")
        # v113.6：副业总分只计已激活副业（与『副业 排行』prof_top 同口径，未激活不计分）——
        # v113.5 曾统一为 8 条之和，但未激活也是 Lv.1 导致人人默认 8 分，鱼鱼拍板不计分
        lines.append(f"📊 副业总分：{total}(已激活副业等级之和，与『副业 排行』同口径)")
        # v130.7 意见#14：3 条固定 💡（2条上限+遗忘/拜师解锁/稀有采集兔蛋）已收敛进 tips.py
        # profession 随机池（含新条目共 12 条），面板只留 1 条随机提示（v130.5 意见#8 同标准）
        lines.append(self._tip("profession"))
        yield event.plain_result("\n".join(lines))

    @declared("prof_forget")
    @require_player()
    async def prof_forget(self, event: AstrMessageEvent):
        group_id, qq_id = self._uid(event)
        player = self._player(group_id, qq_id)
        raw = self._strip_cmd(event, "遗忘副业").strip()
        if not raw:
            yield event.plain_result("格式：遗忘副业 <名称>，如『遗忘副业 采集』(等级清零，请慎重！)")
            return
        key = None
        for k, name in db.PROF_FIELDS.items():
            if raw in name or raw in k:
                key = k
                break
        if not key:
            yield event.plain_result(f"没有『{raw}』这个副业！可选：{'、'.join(db.PROF_FIELDS.values())}")
            return
        # v105R3 M13 P2-9：遗忘前先结算已到期未结算的等待（finish<=now）——
        # 防"等待已到期但推送失败/重启过、遗忘即丢已付体力的产出"；
        # 未到期等待直接清（主动遗忘 = 放弃等待，符合遗忘语义）
        # v103.0 修复（round103 小红抓包）：遗忘副业必须清等待状态——否则遗留的
        # 挖掘/垂钓结算会在下次做其他等待型副业时串台（"采集"输出"矿脉敲开"）
        # v104 P1 修复：仅当进行中的等待型副业 == 被遗忘副业时才清——
        # 否则垂钓等待中遗忘炼金会把垂钓状态误清（白等 + 结算丢失）
        _wait_st = self._prof_wait_state(group_id, qq_id)
        if _wait_st is None:
            # v127.5 惰性结算兜底：到点事件已被引擎惰性清 → 残留存根仍可结算
            _wait_st = self._prof_wait_residual(group_id, qq_id)
        _settle_text = ""
        if _wait_st and _wait_st.get("type") == key:
            if int(_wait_st.get("finish", 0)) <= int(time.time()):
                _settle_text = self._prof_settle(group_id, qq_id, _wait_st) or ""
            else:
                self._prof_wait_clear(group_id, qq_id)
        old_lv = db.forget_prof(group_id, qq_id, key)
        if old_lv is None:
            yield event.plain_result(f"{db.PROF_FIELDS[key]} 本来就没激活，不用遗忘～")
            return
        yield event.plain_result(
            f"📦 你遗忘了「{db.PROF_FIELDS[key]}」(原 Lv.{old_lv}，已清零)！\n"
            f"副业随时可以重新拜师学习，放心去探索其他生活职业吧～"
            + (f"\n{_settle_text}" if _settle_text else "")
        )

    def _prof_rank_text(self, group_id):
        tops = db.prof_top(group_id, 10)
        if not tops:
            return "🏆 【副业排行】\n━━━━━━━━━━━━\n还没有人练副业，快来当第一名！"
        lines = ["🏆 【副业排行】(总分 = 已激活副业等级之和)", "━━━━━━━━━━━━"]
        names = {}
        for t in tops:
            p = self._player(group_id, t["qq_id"])
            names[t["qq_id"]] = p["name"] if p else t["qq_id"]
        for i, t in enumerate(tops, 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, "  ")
            lines.append(f"{medal} {i:>2}. {names.get(t['qq_id'], t['qq_id'])}：{t['total']} 分")
        lines.append("")
        lines.append(self._tip("profession"))
        return "\n".join(lines)

    # ---------------- 每日副业任务 ----------------

    def _daily_prof_key(self, qq_id):
        # v105R3 M13 P2-1：key 去掉 group_id——每日任务按玩家口径（19 章 §4.3
        # "每天随机 1 个任务"），旧 key 含群号导致同一天在 N 个群各领 1 份
        # 50 金+50 经验（激活副业是玩家级数据，跨群共享）；等待型 key 早已全局，此处对齐
        today = time.strftime("%Y-%m-%d")
        return f"prof_daily_{qq_id}_{today}"

    def _daily_prof_state(self, group_id, qq_id):
        """返回 (task_key, name, need, reward_gold, done_count, claimed)"""
        raw = db.get_event_state(self._daily_prof_key(qq_id))
        if raw:
            parts = raw.split("|")
            if len(parts) >= 5:
                claimed = len(parts) >= 6 and parts[5] == "1"
                activated = db.get_activated_profs(group_id, qq_id)
                # v104 P1 修复：锁定任务对应副业已不激活（如遗忘副业）且未领奖 →
                # 从当前激活副业重新抽取，否则任务永久废掉；已领奖任务保留（防重复发奖）；
                # 完全没有激活副业时保留原任务（无重抽对象，避免每次查询任务都变）
                if (claimed or parts[0] in activated
                        or not any(k in activated for k in _clife.DAILY_PROF_TASKS)):
                    return parts[0], parts[1], int(parts[2]), int(parts[3]), int(parts[4]), claimed
        # v167：副业已解除数量上限（可无限学/无限发展），任务只从已激活副业抽取（做得了），
        # 未激活任何副业才全随机（做不了 → 拜师引导，见 daily_prof 视图）
        import random as _rnd
        activated = db.get_activated_profs(group_id, qq_id)
        cand = [k for k in _clife.DAILY_PROF_TASKS if k in activated] or list(_clife.DAILY_PROF_TASKS.keys())
        tkey = _rnd.choice(cand)
        name, need, gold = _clife.DAILY_PROF_TASKS[tkey]
        db.set_event_state(self._daily_prof_key(qq_id), f"{tkey}|{name}|{need}|{gold}|0|0")
        return tkey, name, need, gold, 0, False

    def _daily_prof_bump(self, group_id, qq_id, tkey):
        """副业动作推进每日任务，返回 (完成了吗, 消息)"""
        # v104 P1 修复：bump 前校验激活——任务对应副业已遗忘时不推进不发奖（防御加固，
        # 玩家下次查『副业任务』会重 roll 到新任务，旧任务自然作废）
        if tkey not in db.get_activated_profs(group_id, qq_id):
            return False, ""
        tkey2, name, need, gold, cnt, claimed = self._daily_prof_state(group_id, qq_id)
        if tkey2 != tkey or claimed:
            return False, ""
        cnt += 1
        done = cnt >= need
        db.set_event_state(self._daily_prof_key(qq_id), f"{tkey2}|{name}|{need}|{gold}|{cnt}|{1 if done else 0}")
        if done:
            player = self._player(group_id, qq_id)
            if player:
                db.update_player(group_id, qq_id, gold=player["gold"] + gold)
            # v101.30: 副业经验奖励（主奖励，练级加速；金币为成本零头补贴）
            # v125.2 B3：每日副业奖励经验数据下沉 prof_config.DAILY_PROF_EXP（原字面量 50）
            _nl, _lvl2 = db.add_prof_exp(group_id, qq_id, tkey2, _clife.DAILY_PROF_EXP)
            _lvl2_msg = f"→ Lv.{_nl}！" if _lvl2 else ""
            return True, f"\n🎯 今日副业任务完成！【{name}×{need}】奖励 {gold} 金币 + {_clife.DAILY_PROF_EXP} 副业经验{_lvl2_msg}！"
        return False, ""

    # v104 M24 P2-1：『每日副业/今日副业』别名（19 章旧称呼，策划案 §六统一为『副业任务』）
    @declared("daily_prof")
    @require_player()

    async def daily_prof(self, event: AstrMessageEvent):
        group_id, qq_id = self._uid(event)
        player = self._player(group_id, qq_id)
        tkey, name, need, gold, cnt, claimed = self._daily_prof_state(group_id, qq_id)
        mark = "✅" if claimed else f"({cnt}/{need})"
        lines = [
            "🎯 【今日副业任务】",
            "━━━━━━━━━━━━",
            f"目标：{name} ×{need} {mark}",
            f"奖励：{gold} 金币 + {_clife.DAILY_PROF_EXP} 副业经验",
            "",
            "💡 完成对应副业动作自动推进，明天刷新新任务！",
        ]
        # v105R3 M13 P3-5：无激活副业时任务随机指向未解锁副业（做不了）→ 明确拜师引导
        if not db.get_activated_profs(group_id, qq_id):
            lines.append("🔒 你还没解锁任何副业，任务做不了！先去城里找对应导师拜师学习吧～")
        if claimed:
            lines.append("✨ 今日任务已完成，明天再来～")
        yield event.plain_result("\n".join(lines))

    @declared("fishing")
    @require_player()

    async def fishing(self, event: AstrMessageEvent):
        group_id, qq_id = self._uid(event)
        player = self._player(group_id, qq_id)
        ok, act_msg = self._prof_active_check(group_id, qq_id, "fishing", require_apprentice=True)
        if not ok:
            yield event.plain_result(act_msg)
            return
        if self._in_battle(group_id, qq_id):
            yield event.plain_result("你正在战斗中！先解决眼前的敌人(攻击/逃跑)")
            return
        cur = player["cur_map"]
        spot_info = _clife.FISHING_SPOTS.get(cur)
        if not spot_info:
            # v105R3 M13 P3-1：钓点提示动态取自 FISHING_SPOTS 全量（11 个），
            # 旧版硬编码 6 个，迷雾海沟/龙鲸海域/风暴之海/深渊湖/彩虹云谷缺失
            _spots = "、".join(
                s["name"] if isinstance(s, dict) else str(s) for s in _clife.FISHING_SPOTS.values()
            )
            yield event.plain_result(f"这里没有水域！找有水的地方垂钓：{_spots}")
            return
        # v87.17 子区域绑定：钓点在指定子区域，不在那边没钓位
        _want_sa = spot_info.get("subarea", "") if isinstance(spot_info, dict) else ""
        if _want_sa and player.get("cur_subarea") != _want_sa:
            _sa_name = ""
            for _s in (_cspace.MAP_BY_ID.get(cur, {}).get("subareas") or []):
                if _s["id"] == _want_sa:
                    _sa_name = _s.get("name", "")
                    break
            yield event.plain_result(
                f"🎣 {spot_info.get('name', '水域')}在{_sa_name or _want_sa}那边，这里没有好钓位！（『前往 {_sa_name or _want_sa}』）"
            )
            return
        spot = spot_info["name"] if isinstance(spot_info, dict) else spot_info
        # 垂钓点分级：副业等级不足不能去高级水域
        prof_lv = db.get_prof_level(group_id, qq_id, "fishing")
        need = spot_info.get("min_lv", 1) if isinstance(spot_info, dict) else 1
        if prof_lv < need:
            yield event.plain_result(f"🌊 {spot}是高级水域(需垂钓 Lv.{need}，你 Lv.{prof_lv})……先在低阶水域练练吧！")
            return
        # v104 M23 消费契约（combat.py 探索 POI「鱼群聚集」写入，key poi_fish_{gid}_{qid}，
        # payload json {"ts": float, "window": 1800}）：ts 在 1800s 窗口内 →
        # 免费垂钓一次（不扣体力/免冷却，立即结算入包）并删除该 key
        free_cast = False
        try:
            _fraw = db.get_event_state(f"poi_fish_{group_id}_{qq_id}")
            if _fraw:
                _fst = json.loads(_fraw) if isinstance(_fraw, str) else _fraw
                if isinstance(_fst, dict) and time.time() - float(_fst.get("ts", 0)) <= float(_fst.get("window", 1800)):
                    free_cast = True
        except (ValueError, TypeError):
            free_cast = False
        if free_cast:
            # 鱼群聚集：免体力/免冷却，直接结算一次并删除 key（不干扰进行中的等待副业）
            db.delete_event_state(f"poi_fish_{group_id}_{qq_id}")
            text = self._settle_fishing(group_id, qq_id, {"type": "fishing", "spot": spot, "spot_map": cur})
            yield event.plain_result(act_msg + f"🐟 鱼群聚集！{text}")
            return
        # v55 等待制（原 60 秒 CD 改为随机等待，自动入包，等级减时；spot 存状态供结算消息用）
        # 9.3：extra 带 spot_map 供 roll_fish 钓点差异化（禁出档位 + 品种限定水域）
        # v105R3 M13 P1-1：先走等待流再扣体力——等待中重复『垂钓』不再白扣 5 体力
        text, _ok = self._prof_wait_flow(
            event, group_id, qq_id, "fishing",
            extra={"spot": spot, "spot_map": cur},
            begin_text=f"🎣 你在{spot}抛出鱼竿，开始垂钓……预计 ",
        )
        if not _ok:
            yield event.plain_result(act_msg + text)
            return
        # v94 体力：垂钓消耗 5 体力（确认开启新轮后才扣；体力不足回滚新轮等待，防白等）
        _ok, _st = self._spend_stamina(group_id, qq_id, _clife.PROF_STAMINA_COST["fishing"], player, "垂钓")
        if not _ok:
            self._prof_wait_clear(group_id, qq_id)
            # v126.4 拍板项 4：体力不足也要带上旧轮结算播报（T3 审计：鱼已入包玩家却只看到体力不足）
            yield event.plain_result((text + "\n" + _st) if text else _st)
            return
        yield event.plain_result(act_msg + text)

    # O80 修复：v82『打造』改名『锻造』后旧指令无别名 → 零回复（playtest 洛洛/血牙复现）。
    # 注册『打造』为『锻造』别名（23 章指令表兼容旧称呼），handler 内双前缀剥离
    @declared("craft")
    @require_player()

    async def craft(self, event: AstrMessageEvent):
        """锻造装备：消耗材料 + 金币 → 获得指定装备（铁匠铺）
        v41：按职业分组展示；套装图纸 Boss 掉落/宝箱/垂钓/商店获得
        O80：『打造』=『锻造』别名（v82 改名前的旧指令）"""
        group_id, qq_id = self._uid(event)
        raw = self._strip_cmd(event, "锻造")
        if raw.startswith("打造"):  # O80：旧指令『打造 <参数>』剥离别名（_strip_cmd 只认『锻造』）
            raw = raw[len("打造"):].strip()
        player = self._player(group_id, qq_id)
        ok, act_msg = self._prof_active_check(group_id, qq_id, "craft", require_apprentice=True)
        if not ok:
            yield event.plain_result(act_msg)
            return
        if not self._at_smith(player):
            yield event.plain_result("需要到铁匠铺/锻造坊才能锻造装备！(先『地图』移动到铁匠铺)")
            return
        text = raw.strip()
        # 『锻造列表 [N]』：列表指令（翻页），与『锻造 N』锻造序号分离
        # #261: 支持『锻造列表 <职业>』按职业过滤（此前非数字参数被静默当页码吞掉）
        if text.startswith("列表"):
            t2 = text[2:].strip()
            if not t2:
                yield event.plain_result(self._craft_list_available(player, 1))
                return
            if t2.isdigit():
                yield event.plain_result(self._craft_list_available(player, int(t2)))
                return
            cls = C.resolve("classes", t2)
            if cls in _ccore.CLASSES:
                yield event.plain_result(self._craft_list_class(player, cls, 1))
                return
            yield event.plain_result(f"未识别的职业『{t2}』！『锻造列表』或『锻造列表 <页码>』查看～")
            return
        # 『锻造 N』：锻造可锻造列表第 N 个配方（序号与列表显示一致，1-based）
        if text.isdigit():
            idx = int(text)
            recs = self._craft_recs_filtered(player)
            if idx < 1 or idx > len(recs):
                yield event.plain_result(f"没有第 {idx} 个可锻造配方(当前可锻造 {len(recs)} 件)！『锻造列表』查看～")
                return
            text = recs[idx - 1][0]
        # 无参数：只列当前可锻造的配方（无需图纸 + 已学习图纸），翻页用『锻造列表 N』
        if not text:
            yield event.plain_result(self._craft_list_available(player, 1))
            return
        # 『锻造 全部 [N]』：全部配方（未达标标记），翻页
        if text.startswith("全部"):
            t2 = text[2:].strip()
            page = int(t2) if t2.isdigit() else 1
            yield event.plain_result(self._craft_list_all(player, page))
            return
        # 『锻造 <职业> [N]』：该职业可锻造列表（翻页：『锻造 <职业> <页码>』）
        cls_page = 1
        cls_text = text
        _cls_parts = text.split()
        if len(_cls_parts) >= 2 and _cls_parts[-1].isdigit():
            cls_page = int(_cls_parts[-1])
            cls_text = " ".join(_cls_parts[:-1])
        cls = C.resolve("classes", cls_text)
        if cls not in _ccore.CLASSES:
            # M10 P2：支持『锻造 战士2』免空格粘页码（与『锻造列表2』『锻造全部2』对齐）
            _i = len(cls_text)
            while _i > 0 and cls_text[_i - 1].isdigit():
                _i -= 1
            if 0 < _i < len(cls_text):
                _cls2 = C.resolve("classes", cls_text[:_i])
                if _cls2 in _ccore.CLASSES:
                    cls = _cls2
                    cls_page = int(cls_text[_i:])
        if cls in _ccore.CLASSES:
            yield event.plain_result(self._craft_list_class(player, cls, cls_page))
            return
        # 锻造指定装备（20 章 4.3：『锻造 <装备名> <词条倾向>』指定词条池）
        affinity = None
        parts = text.split()
        if len(parts) >= 2:
            last = parts[-1]
            if last in _b143.AFFIX_AFFINITY_CN:
                affinity = _b143.AFFIX_AFFINITY_CN[last]
                text = " ".join(parts[:-1])
        rec_name = C.craft_recipe_search(text)
        if rec_name and rec_name not in _clife.CRAFT_RECIPES:
            # 旧别名指向已删除配方：直接提示未找到（防 CRAFT_RECIPES[rec_name] KeyError 崩溃）
            # M10 P2 死别名引导：旧版本已移除的配方给出明确提示
            if any(text in al for als in _clife.CRAFT_RECIPE_ALIASES.values() for al in als):
                yield event.plain_result(f"『{text}』是旧版本已移除的配方！『锻造』查看当前可锻造配方～")
            else:
                yield event.plain_result(f"没有找到『{text}』的锻造配方！『锻造』看职业分组，『锻造 配方 <装备名>』看详情～")
            return
        if not rec_name:
            # 可能是查看配方详情
            if text.startswith("配方") or text.startswith("详情"):
                t2 = text[2:].strip()
                # M10 P2 空参拦截：『锻造 配方』无参不再误中首个配方（空串包含匹配恒 True）
                if not t2:
                    yield event.plain_result("格式：『锻造 配方 <装备名>』看配方详情，如『锻造 配方 铁剑』～")
                    return
                rn = C.craft_recipe_search(t2)
                if rn and rn in _clife.CRAFT_RECIPES:  # 旧别名指向已删除配方 → 不展示详情
                    yield event.plain_result(self._recipe_detail(rn))
                    return
                # M10 P2：『锻造 配方 <旧名>』死别名引导（与锻造/代工/配方主入口一致）
                if any(t2 in al for als in _clife.CRAFT_RECIPE_ALIASES.values() for al in als):
                    yield event.plain_result(f"『{t2}』是旧版本已移除的配方！『锻造』查看当前可锻造配方～")
                    return
            # #24 材料关键词联想：没找到配方名 → 按材料名联想
            mat_recs = C.craft_recipes_by_material(text)
            if mat_recs:
                lines = [f"🔍 没找到『{text}』配方，但按材料联想到了 {len(mat_recs)} 个：", ""]
                for name, rec in mat_recs:
                    q = _b143.QUALITY[rec["quality"]]
                    bp = " 📜" if rec.get("blueprint") else ""
                    mats_show = " + ".join("%s×%s" % (C.display("materials", m), n) for m, n in rec["mats"].items())
                    if rec.get("blueprint"):
                        mats_show += " + %s×1" % rec["blueprint"]
                    lines.append(f"{q['color']}【{C.display('recipes', name)}】Lv.{rec['lv']} {_b143.EQUIP_SLOTS[rec['slot']]}{bp}｜{mats_show}｜{rec['gold']}金")
                lines.append("")
                lines.append(self._tip("forge"))
                yield event.plain_result("\n".join(lines))
                return
            yield event.plain_result(f"没有找到『{text}』的锻造配方！『锻造』看职业分组，『锻造 配方 <装备名>』看详情～")
            return
        rec = _clife.CRAFT_RECIPES[rec_name]
        rec_disp = C.display("recipes", rec_name)
        # 检查等级门槛（装备等级比玩家高太多不能锻造）
        if rec["lv"] > player["level"] + 6:
            yield event.plain_result(f"【{rec_disp}】是 Lv.{rec['lv']} 的装备，你才 Lv.{player['level']}，等级再高些才能驾驭！")
            return
        # v54 副业等级限制
        prof_lv = db.get_prof_level(group_id, qq_id, "craft")
        need_prof = self._craft_prof_need(rec["lv"])
        if prof_lv < need_prof:
            yield event.plain_result(
                f"【{rec_disp}】需要锻造副业 Lv.{need_prof}，你才 Lv.{prof_lv}！多锻造装备升级副业吧～\n"
                + self._tip("forge")
            )
            return
        # v54 图纸学习制：需图纸配方必须已学习（不再每件消耗图纸）
        if rec.get("blueprint"):
            bp_name = rec["blueprint"]
            if bp_name not in (player.get("learned_blueprints") or []):
                # 懒迁移：背包有图纸 → 提示先学习
                have_bp = db.count_item(group_id, qq_id, bp_name)
                if have_bp >= 1:
                    yield event.plain_result(
                        f"你背包里有『{bp_name}』！输入『学习 {bp_name}』解锁配方后就能永久锻造了～"
                    )
                else:
                    yield event.plain_result(
                        f"【{rec_disp}】需要先学习图纸『{bp_name}』(Boss 掉落/宝箱/垂钓/商店获得)！『学习 <图纸名>』永久解锁。"
                    )
                return
        # 检查材料（毕业套图纸已学习，无需再检查图纸）
        lack = []
        for m, n in rec["mats"].items():
            have = db.count_item(group_id, qq_id, m)
            if have < n:
                lack.append(f"{C.display('materials', m)}×{n}(你有{have})")
        if lack:
            yield event.plain_result(f"材料不足！锻造【{rec_disp}】还缺：{'、'.join(lack)}。材料可通过打怪/垂钓/挖掘/商店获得！")
            return
        # 20 章 4.3：词条倾向额外消耗（+50% 金币）
        gold_need = rec["gold"]
        if affinity:
            gold_need = int(gold_need * 1.5)
        # v101.30b Lv.10 神锻名家：锻造费用 9 折（v110.2 更名，原"神锻宗师"）
        if prof_lv >= 10:
            gold_need = int(gold_need * 0.9)
        if player["gold"] < gold_need:
            yield event.plain_result(f"金币不足！锻造【{rec_disp}】需要 {gold_need} 金币，你只有 {player['gold']}。")
            return
        # v94 体力：锻造消耗 10 体力（所有前置校验通过后再扣，材料/金币不足不白扣）
        _ok, _st = self._spend_stamina(group_id, qq_id, _clife.PROF_STAMINA_COST["craft"], player, "锻造")
        if not _ok:
            yield event.plain_result(_st)
            return
        # 扣材料 + 扣金币 + 发装备（v48：背包 data.name 存中文，mats key 是 ID）
        # v104R3 P1-2：先按 key 精确扣取再按名兜底 + remain 循环跨堆（对齐烹饪 v104 修复；
        # 原实现只按名字匹配第一堆，同名消耗品/装备可顶替材料错扣）
        items = db.get_inventory(group_id, qq_id)
        for m, n in rec["mats"].items():
            mname = C.display("materials", m)
            remain = n
            for it in items:
                if remain <= 0:
                    break
                if it["key"] != m:
                    continue
                if db.remove_item(group_id, qq_id, it["key"], min(it["count"], remain)):
                    remain -= min(it["count"], remain)
            for it in items:
                if remain <= 0:
                    break
                if it["key"] == m or it["data"].get("name") != mname:
                    continue
                if db.remove_item(group_id, qq_id, it["key"], min(it["count"], remain)):
                    remain -= min(it["count"], remain)
        db.update_player(group_id, qq_id, gold=player["gold"] - gold_need)
        equip = C.craft_recipe_make(rec_name, affinity)
        # v135 锻造品质随机（19 章实装；品质提升额外消耗 精金锭+深海水晶，背包没有则跳过提升）：
        #   蓝→紫 5%（神锻名家锻造 Lv.10 +2% → 7%）、紫→橙 5%（+2%）、橙不变；
        #   品质提升后重算 stats（equip_stats 按新品质）+ 品质色前缀
        quality_msg = ""
        if equip.get("quality") in ("blue", "purple"):
            _bonus = _ccore.QUALITY_UPGRADE_MASTER_BONUS if (prof_lv >= 10) else 0.0  # 神锻名家
            if random.random() < _ccore.QUALITY_UPGRADE_CHANCE + _bonus:
                _cost = _ccore.QUALITY_UPGRADE_COST
                _has_all = True
                for _mk, _mn in _cost.items():
                    if db.count_item(group_id, qq_id, _mk) < _mn:
                        _has_all = False
                        break
                if _has_all:
                    for _mk, _mn in _cost.items():
                        db.remove_item(group_id, qq_id, _mk, _mn)
                    _new_q = "purple" if equip["quality"] == "blue" else "orange"
                    equip["quality"] = _new_q
                    # 重算 stats（equip_stats 按新品质）+ 品质色前缀（沿用名册锻造命名规范）
                    _new_stats = C.equip_stats(equip["slot"], equip["lv"], _new_q)
                    for k in equip.get("stats", {}):
                        if k in _new_stats:
                            equip["stats"][k] = _new_stats[k]
                    equip["name"] = f"{_b143.QUALITY[_new_q]['color']}·{equip['name']}"
                    quality_msg = "✨ 品质升华！蓝装锻出了紫装！" if _new_q == "purple" else "✨ 品质升华！紫装锻出了橙装！"
        # v135 橙装 2% 精良前缀（属性 ×1.15）
        if equip.get("quality") == "orange" and random.random() < _ccore.MASTERPIECE_CHANCE:
            equip["masterpiece"] = True
            for _k in equip.get("stats", {}):
                equip["stats"][_k] = int(equip["stats"][_k] * 1.15)
            equip["name"] = f"精良·{equip['name']}"
            quality_msg = "🌟 精良作品！属性大幅提升！"
        import uuid
        key = f"eq_{uuid.uuid4().hex[:8]}"
        db.add_item(group_id, qq_id, key, equip)
        q = _b143.QUALITY[equip["quality"]]
        afs = equip.get("affixes", [])
        af_str = ""
        if afs:
            parts = [C.affix_label(a) for a in afs if isinstance(a, str)]
            if parts:
                af_str = f"\n    ✨ 词条：{'  '.join(parts)}"
        if equip.get("legendary"):
            lg = _cit.LEGENDARY_EFFECTS[equip["legendary"]]
            af_str += f"\n    ✨ 专属：{lg['name']}"
        set_str = ""
        if equip.get("set"):
            set_str = f"\n    🎴 套装：{equip['set']}"
        # 副业经验（锻造成功 +1；阶段九：矮人熔炉之心——锻造经验 +10%，向上取整
        # （与全知全能加成同款整数算法；基础 1 点 → ceil(1.1)=2 点，保证加成可见）。
        # v105 M01#5：策划案文字为"成功率+10%"但锻造流程无失败机制，统一为经验语义
        # （races.py 注释/race_talent_display 展示/本实现三处收敛一致）。
        prof_gain = 1
        if race_stats(player.get("race")).get("craft_bonus"):
            prof_gain = (prof_gain * 11 + 9) // 10  # ceil(prof_gain * 1.10)
        new_lv, leveled = db.add_prof_exp(group_id, qq_id, "craft", prof_gain)
        lv_msg = ""
        if leveled:
            lv_msg = f"\n🌟 锻造等级提升到 Lv.{new_lv}！"
        # 每日任务推进
        _done, _msg = self._daily_prof_bump(group_id, qq_id, "craft")
        lv_msg += _msg
        # 阶段九：锻造次数 + 成就判定
        db.bump_stats(group_id, qq_id, craft_count=1)
        C.check_achievements(group_id, qq_id, player)
        # v97.5 行为彩蛋规则：锻造成功后
        _rule_txt = self._rule_fire("craft_done", group_id, qq_id, player,
                                    _cspace.MAP_BY_ID.get(player["cur_map"], {}))
        affinity_str = f"({affinity}倾向)" if affinity else ""
        _msg_parts = [act_msg + f"🔨 铁匠挥锤敲打，火星四溅……\n"
            f"✅ 锻造成功！{q['color']}【{equip['name']}】({_b143.EQUIP_SLOTS[equip['slot']]}) Lv.{equip['lv']} {affinity_str}"
            f"{af_str}{set_str}\n"]
        if quality_msg:
            _msg_parts.append(f"{quality_msg}\n")
        _msg_parts.append(
            # v113.5 O120：成功提示补副业经验反馈（原只报装备入包，玩家看不到经验增长）
            f"💰 消耗 {gold_need} 金币，装备已放入背包！(副业经验 +{prof_gain}){lv_msg}"
            + (f"\n{_rule_txt}" if _rule_txt else "")
        )
        yield event.plain_result("".join(_msg_parts))

    @declared("craft_commission")
    @require_player()
    async def craft_commission(self, event: AstrMessageEvent):
        """铁匠代工：材料＋3倍金币 → 装备(v166 去图纸化；v67 单人补偿，不受锻造等级限制)"""
        group_id, qq_id = self._uid(event)
        player = self._player(group_id, qq_id)
        if not self._at_smith(player):
            yield event.plain_result("需要到铁匠铺/锻造坊才能找铁匠代工！(先『地图』移动到铁匠铺)")
            return
        text = self._strip_cmd(event, "代工").strip()
        if not text:
            yield event.plain_result(
                "格式：代工 <装备名>，如『代工 铁皮长剑』\n"
                "铁匠代工 = 材料＋3倍金币，不受锻造等级/图纸限制(单人玩家也能拿高级装备)"
            )
            return
        # v130.7 意见#30：『代工 <序号>』= 『代工』面板第 N 个可代工配方
        # v166：改按代工口径 _commission_recs（免图纸免副业，只看等级）
        if text.isdigit():
            idx = int(text)
            _recs = self._commission_recs(player)
            if idx < 1 or idx > len(_recs):
                yield event.plain_result(f"没有第 {idx} 个可代工配方(当前可代工 {len(_recs)} 件)！『锻造 全部』查看全部配方～")
                return
            text = _recs[idx - 1][0]
        rec_name = C.craft_recipe_search(text)
        if not rec_name or rec_name not in _clife.CRAFT_RECIPES:  # 旧别名指向已删除配方 → 视作未找到
            # M10 P2 死别名引导：旧版本已移除的配方给出明确提示
            if any(text in al for als in _clife.CRAFT_RECIPE_ALIASES.values() for al in als):
                yield event.plain_result(f"『{text}』是旧版本已移除的配方！『锻造』查看当前可锻造配方～")
            else:
                yield event.plain_result(f"没有找到『{text}』的锻造配方！『锻造 配方 <装备名>』查看详情～")
            return
        rec = _clife.CRAFT_RECIPES[rec_name]
        rec_disp = C.display("recipes", rec_name)
        if rec["lv"] > player["level"] + 6:
            yield event.plain_result(f"【{rec_disp}】是 Lv.{rec['lv']} 的装备，你才 Lv.{player['level']}，等级再高些才能驾驭！")
            return
        # v166 代工去图纸：不再校验 learned_blueprints/背包图纸——材料+3倍金币直出
        # （锻造 craft 命令仍保留图纸学习制，图纸线/掉率不变）
        # 材料检查
        lack = []
        for m, n in rec["mats"].items():
            have = db.count_item(group_id, qq_id, m)
            if have < n:
                lack.append(f"{C.display('materials', m)}×{n}(你有{have})")
        if lack:
            yield event.plain_result(f"材料不足！代工【{rec_disp}】还缺：{'、'.join(lack)}。材料可通过打怪/垂钓/挖掘/商店获得！")
            return
        cost = rec["gold"] * 3
        if player["gold"] < cost:
            yield event.plain_result(f"金币不足！铁匠代工【{rec_disp}】要 {cost} 金币(锻造价×3)，你只有 {player['gold']}。")
            return
        # 扣材料 + 扣金币 + 发装备
        # v104R3 P1-2：先按 key 精确扣取再按名兜底 + remain 循环（与锻造同构修复）
        items = db.get_inventory(group_id, qq_id)
        for m, n in rec["mats"].items():
            mname = C.display("materials", m)
            remain = n
            for it in items:
                if remain <= 0:
                    break
                if it["key"] != m:
                    continue
                if db.remove_item(group_id, qq_id, it["key"], min(it["count"], remain)):
                    remain -= min(it["count"], remain)
            for it in items:
                if remain <= 0:
                    break
                if it["key"] == m or it["data"].get("name") != mname:
                    continue
                if db.remove_item(group_id, qq_id, it["key"], min(it["count"], remain)):
                    remain -= min(it["count"], remain)
        db.update_player(group_id, qq_id, gold=player["gold"] - cost)
        equip = C.craft_recipe_make(rec_name)
        import uuid
        key = f"eq_{uuid.uuid4().hex[:8]}"
        db.add_item(group_id, qq_id, key, equip)
        q = _b143.QUALITY[equip["quality"]]
        yield event.plain_result(
            f"🔨 铁匠接过材料，替你挥锤……\n"
            f"✅ 代工完成！{q['color']}【{equip['name']}】({_b143.EQUIP_SLOTS[equip['slot']]}) Lv.{equip['lv']}\n"
            f"💰 代工费 {cost} 金币(锻造价×3)，装备已放入背包！"
        )

    @declared("learn")
    @require_player()

    async def learn(self, event: AstrMessageEvent):
        """『学习 <图纸名>』：消耗 1 张图纸，永久解锁对应套装配方(v54 图纸学习制)"""
        group_id, qq_id = self._uid(event)
        player = self._player(group_id, qq_id)
        bp_name = self._strip_cmd(event, "学习").strip()
        # v95r62 宽容『学习图纸 X』：玩家把"图纸"当命令词时剥掉前缀（物品名本身含"图纸"后缀）
        if bp_name.startswith("图纸"):
            bp_name = bp_name[2:].strip()
        if not bp_name:
            yield event.plain_result("格式：『学习 <图纸名>』，如『学习 铁皮图纸』！图纸由 Boss 掉落或宝箱/垂钓/商店获得。")
            return
        # 背包找图纸（type=图纸）
        items = db.get_inventory(group_id, qq_id)
        # v130.7 意见#30：『学习 <序号>』= 『背包 图纸』面板第 N 张图纸（取数列表与面板同源 _item_category 过滤，序号跨页连续）
        if bp_name.isdigit():
            idx = int(bp_name)
            _bps = [it for it in items if self._item_category(it["data"]) == "图纸"]
            if idx < 1 or idx > len(_bps):
                yield event.plain_result(f"背包里没有第 {idx} 张图纸(共 {len(_bps)} 张)！『背包 图纸』查看～")
                return
            bp_name = _bps[idx - 1]["data"].get("name", "")
        target = next((it for it in items if self._item_category(it["data"]) == "图纸" and bp_name in it["data"].get("name", "")), None)
        if not target:
            yield event.plain_result(f"背包里没有『{bp_name}』图纸！Boss 掉落/宝箱/垂钓/商店获得，『背包 图纸』查看～")
            return
        bp_disp = target["data"].get("name")
        learned = list(player.get("learned_blueprints") or [])
        if bp_disp in learned:
            yield event.plain_result(f"『{bp_disp}』你已经学会了，不需要重复学习～")
            return
        # M10 P2 学习废图纸白扣修复：先统计解锁配方数，0 个则不消耗图纸也不记录
        # v124：烹饪/炼金配方同样走图纸学习制（rec.blueprint=图纸名，与锻造一致）
        unlocked = [rk for rk, rec in _clife.CRAFT_RECIPES.items() if rec.get("blueprint") == bp_disp]
        unlocked += [rk for rk, rec in _clife.COOKING_RECIPES.items() if rec.get("blueprint") == bp_disp]
        unlocked += [rk for rk, rec in _clife.ALCHEMY_RECIPES.items() if rec.get("blueprint") == bp_disp]
        if not unlocked:
            # v164 图纸经济修正：蓝绿直锻装备（名册 source=锻造，配方无 blueprint）不再掉图纸，
            # 但玩家背包可能残留旧图纸。识别"图纸名 = 直锻配方名 + 图纸"→ 给明确出路（直接锻造/出售），
            # 而不是笼统的"旧版本残留"。
            _eq_name = bp_disp[:-2] if bp_disp.endswith("图纸") else bp_disp
            _direct_rec = next((r for r in _clife.CRAFT_RECIPES.values()
                                if r.get("name") == _eq_name and not r.get("blueprint")), None)
            if _direct_rec:
                yield event.plain_result(
                    f"💡 『{bp_disp}』对应装备【{_eq_name}】可以直接在铁匠铺『锻造 {_eq_name}』制作，不需要学习图纸！\n"
                    f"这张图纸已不再掉落（旧版本遗留），可『出售 {bp_disp}』换成金币～"
                )
            else:
                yield event.plain_result(f"『{bp_disp}』没有对应的锻造/烹饪/炼金配方(旧版本残留图纸)，图纸未消耗，可自行出售～")
            return
        # 消耗图纸 + 记录
        db.remove_item(group_id, qq_id, target["key"], 1)
        learned.append(bp_disp)
        db.update_player(group_id, qq_id, learned_blueprints=learned)
        lines = [
            f"📜 你研读了【{bp_disp}】，图纸化作点点光芒融入记忆！",
            f"🧠 永久解锁 {len(unlocked)} 个配方(制作时不再消耗图纸)！",
            "━━━━━━━━━━━━",
        ]
        _craft_recs = {rk: _clife.CRAFT_RECIPES[rk] for rk in unlocked if rk in _clife.CRAFT_RECIPES}
        _other_recs = [rk for rk in unlocked if rk not in _clife.CRAFT_RECIPES]
        for rk in sorted(_craft_recs, key=lambda x: _craft_recs[x]["slot"]):
            rec = _craft_recs[rk]
            lines.append(f"  {_b143.QUALITY[rec['quality']]['color']}【{rec['name']}】Lv.{rec['lv']} {_b143.EQUIP_SLOTS[rec['slot']]}")
        for rk in _other_recs:
            rec = _clife.COOKING_RECIPES.get(rk) or _clife.ALCHEMY_RECIPES.get(rk)
            lines.append(f"  📜【{rec['name']}】")
        lines.append("━━━━━━━━━━━━")
        lines.append(self._tip("blueprint"))
        yield event.plain_result("\n".join(lines))

    def _craft_prof_need(self, rec_lv: int) -> int:
        """锻造配方副业等级门槛(v54：按装备等级折算)"""
        tiers = _ccore.RECIPE_LV_TIERS
        for i, t in enumerate(tiers, 1):
            if rec_lv <= t:
                return i
        return len(tiers) + 1

    def _rec_learned(self, player, rec) -> bool:
        """图纸是否已学习(v54 图纸学习制：无图纸配方恒 True)"""
        bp = rec.get("blueprint")
        if not bp:
            return True
        return bp in (player.get("learned_blueprints") or [])

    def _learned_blueprint_list(self, player) -> str:
        """v134.1 意见#39：『图纸列表』——当前玩家已学会的全部图纸一览。

        数据源：player.learned_blueprints（learn 命令永久记录，图纸名=配方 blueprint 字段）。
        按配方反查类型（锻造/烹饪/炼金）+ 等级/职业要求；无配方引用的残留图纸（旧版本遗留）
        也列出（标注"已失效"提示可出售）。"""
        learned = list(player.get("learned_blueprints") or [])
        if not learned:
            return ("📜 你还没有学会任何图纸！\n"
                    "💡 图纸由 Boss 掉落/宝箱/垂钓/商店获得，背包里有图纸时发『学习 <图纸名>』永久解锁～")
        rows = []
        for bp in learned:
            rec = None
            kind = "锻造"
            for rk, r in _clife.CRAFT_RECIPES.items():
                if r.get("blueprint") == bp:
                    rec = r
                    break
            if not rec:
                for rk, r in _clife.COOKING_RECIPES.items():
                    if r.get("blueprint") == bp:
                        rec = r
                        kind = "烹饪"
                        break
            if not rec:
                for rk, r in _clife.ALCHEMY_RECIPES.items():
                    if r.get("blueprint") == bp:
                        rec = r
                        kind = "炼金"
                        break
            if not rec:
                rows.append(f"📜【{bp}】（已失效/旧版本残留，可出售）")
                continue
            name = rec.get("name", bp)
            q = _b143.QUALITY.get(rec.get("quality", ""), {})
            lv = rec.get("lv", 0)
            cls = rec.get("class", "")
            wt = rec.get("weapon_type", "")
            cls_part = ""
            if cls and cls in _ccore.CLASSES:
                cls_part = f" {C.display('classes', cls)}"
            elif wt:
                _names = [C.display("classes", ck) for ck, cv in _ccore.CLASSES.items()
                          if cv.get("weapon_type") == wt and ck != "cls_novice"]
                if _names:
                    cls_part = f" {'、'.join(_names)}"
            rows.append(f"{q.get('color', '')}【{name}】{kind}·Lv.{lv}{cls_part}")
        head = f"📜 【已学图纸】共 {len(learned)} 张"
        lines = [head, "━━━━━━━━━━━━"] + rows + ["", "💡 已学图纸锻造/烹饪/炼金不再消耗图纸 ｜ 背包里新图纸发『学习 <图纸名>』解锁"]
        return "\n".join(lines)

    def _craft_mats_str(self, rec) -> str:
        mats_str = " + ".join(f"{C.display('materials', m)}×{n}" for m, n in rec["mats"].items())
        return mats_str

    def _smith_town_lv(self, player) -> int | None:
        """v168 锻造按城镇分阶段：返回当前玩家所在铁匠铺城镇的推荐等级（窗口中心）。

        cur_map 命中 _SMITH_TOWN_LEVELS（11 个铁匠铺城镇）才返回城镇等级；
        不在表内（cur_map 缺失等异常）返回 None → 调用方不做窗口过滤（回退现状）。
        """
        cur_map = player.get("cur_map", "") or ""
        if cur_map in _ss._SMITH_TOWN_LEVELS:
            return _ss.town_level(cur_map)
        return None

    def _craft_recs_filtered(self, player) -> list:
        """当前玩家可锻造的配方列表(玩家等级 + 副业等级 + 图纸已学 + 城镇窗口)

        v168：锻造按城镇分阶段——每个铁匠铺城镇只能锻造 [城镇等级-8, 城镇等级+8]
        的配方（橡木镇 Lv.4 → Lv.1-12；铁港 Lv.18 → Lv.10-26；低阶配方回低级城锻）。
        玩家 cur_map 不在铁匠铺城镇表（town_lv 取不到）→ 不限制窗口（回退现状）。
        """
        town_lv = self._smith_town_lv(player)
        prof_lv = db.get_prof_level(player.get("group_id", ""), player.get("qq_id"), "craft")
        out = []
        for rk, rec in _clife.CRAFT_RECIPES.items():
            if rec["lv"] > player["level"] + 6:
                continue
            if town_lv is not None and abs(rec["lv"] - town_lv) > 8:
                continue
            if self._craft_prof_need(rec["lv"]) > prof_lv:
                continue
            if not self._rec_learned(player, rec):
                continue
            out.append((rk, rec))
        out.sort(key=lambda x: (x[1]["lv"], x[1]["slot"]))
        return out

    def _commission_recs(self, player) -> list:
        """v166 代工可选单：按代工口径过滤——只需等级门槛（免副业等级 + 免图纸），
        材料在结算时检查（与『代工』免图纸定位一致：材料+3倍金币直出）。

        v168 备注：代工保持原样不做城镇窗口分阶段——代工=花 3 倍金币跳过锻造
        副业/图纸门槛的"特权直出"通道（鱼鱼未要求代工分阶段），且代工单本身
        只看玩家等级（玩家 cur_map 都在主城铁匠铺，若加窗口会把代工逼去
        低级城反而反直觉）；锻造（_craft_recs_filtered）才按城镇分阶段。
        """
        out = []
        for rk, rec in _clife.CRAFT_RECIPES.items():
            if rec["lv"] > player["level"] + 6:
                continue
            out.append((rk, rec))
        out.sort(key=lambda x: (x[1]["lv"], x[1]["slot"]))
        return out

    def _craft_line(self, rec, idx: int) -> str:
        q = _b143.QUALITY[rec["quality"]]
        bp = " 📜" if rec.get("blueprint") else ""
        return (f"{idx}. {q['color']}【{rec['name']}】Lv.{rec['lv']} {_b143.EQUIP_SLOTS[rec['slot']]}"
                f" 锻造Lv.{self._craft_prof_need(rec['lv'])}{bp}\n"
                f"    {self._craft_mats_str(rec)}｜{rec['gold']}金")

    def _craft_town_hint(self, player) -> str:
        """v168 锻造分阶段：当前城镇窗口提示文本（如『橡木镇锻造 Lv.1-12』）。

        cur_map 命中 9 主城铁匠铺 → 返回 '｜{城镇名}锻造 Lv.{lo}-{hi}'；
        不在表内（铁盾镇/铁砧要塞等）→ 返回空串（无窗口限制，不展示）。
        """
        town_lv = self._smith_town_lv(player)
        if town_lv is None:
            return ""
        cur_map = player.get("cur_map", "") or ""
        tname = (_cspace.MAP_BY_ID.get(cur_map, {}).get("name")) or cur_map
        return f"｜{tname}锻造 Lv.{max(1, town_lv - 8)}-{town_lv + 8}"

    def _craft_list_available(self, player, page: int = 1) -> str:
        """『锻造』：只列当前可锻造的配方(翻页 5/页，v168 按城镇窗口分阶段)"""
        recs = self._craft_recs_filtered(player)
        town_hint = self._craft_town_hint(player)
        page_items, pages, page = self._page_items(recs, page, per_page=5)
        lines = [f"🔨 铁匠铺·当前可锻造(共 {len(recs)} 件){town_hint}", "━━━━━━━━━━━━"]
        base = (page - 1) * 5
        if not page_items:
            lines.append("此城镇可锻造的配方有限，去更高等级城镇的铁匠铺看看～")
        for i, (rk, rec) in enumerate(page_items, 1):
            lines.append(self._craft_line(rec, base + i))
        lines.append("━━━━━━━━━━━━")
        lines.append(f"📄 第 {page}/{pages} 页" + (f"｜『锻造列表 {page + 1}』下一页" if page < pages else ""))
        lines.append(self._tip("forge"))
        lines.append(self._tip("blueprint"))
        self._record_list_state(player.get("qq_id"), "锻造列表", page, pages)
        return "\n".join(lines)

    def _craft_list_all(self, player, page: int = 1) -> str:
        """『锻造 全部』：全部配方（未达标标记；v168 超本城窗口配方加 🔒城镇）"""
        prof_lv = db.get_prof_level(player.get("group_id", ""), player.get("qq_id"), "craft")
        town_lv = self._smith_town_lv(player)
        town_hint = self._craft_town_hint(player)
        recs = []
        for rk, rec in _clife.CRAFT_RECIPES.items():
            marks = []
            if rec["lv"] > player["level"] + 6:
                marks.append("🔒等级")
            if town_lv is not None and abs(rec["lv"] - town_lv) > 8:
                marks.append("🔒城镇")
            if self._craft_prof_need(rec["lv"]) > prof_lv:
                marks.append(f"🛠️锻造Lv.{self._craft_prof_need(rec['lv'])}")  # v101.28l #425：补缺的数字
            if not self._rec_learned(player, rec):
                marks.append("📜未学")
            recs.append((rk, rec, marks))
        recs.sort(key=lambda x: (x[1]["lv"], x[1]["slot"]))
        page_items, pages, page = self._page_items(recs, page, per_page=5)
        lines = [f"🔨 铁匠铺·全部配方(共 {len(recs)} 件){town_hint}", "━━━━━━━━━━━━"]
        base = (page - 1) * 5
        for i, (rk, rec, marks) in enumerate(page_items, 1):
            q = _b143.QUALITY[rec["quality"]]
            mark_str = " ".join(marks) if marks else "✅"
            lines.append(f"{base + i}. {q['color']}【{rec['name']}】Lv.{rec['lv']} {_b143.EQUIP_SLOTS[rec['slot']]} {mark_str}")
            lines.append(f"    {self._craft_mats_str(rec)}｜{rec['gold']}金")
        lines.append("━━━━━━━━━━━━")
        lines.append(f"📄 第 {page}/{pages} 页" + (f"｜『锻造 全部 {page + 1}』下一页" if page < pages else ""))
        lines.append("💡 未达标的配方：🔒等级不够 ｜ 🛠️锻造副业等级不够 ｜ 📜图纸未学习 ｜ 🔒城镇需到对应等级城镇的铁匠铺")
        lines.append(self._tip("forge"))
        self._record_list_state(player.get("qq_id"), "锻造 全部", page, pages)
        return "\n".join(lines)

    def _craft_list_class(self, player, cls: str, page: int = 1) -> str:
        """『锻造 <职业>』：该职业可锻造列表"""
        cls_name = C.display("classes", cls)
        wt = _ccore.CLASSES[cls].get("weapon_type", "sword")
        # M10 P2：防具/饰品（slot≠weapon）全职业可锻，不再被武器过滤挡在列表外
        recs = [(rk, rec) for rk, rec in self._craft_recs_filtered(player)
                if rec.get("class") == cls or rec.get("weapon_type") == wt or rec.get("slot") != "weapon"]
        page_items, pages, page = self._page_items(recs, page, per_page=5)
        lines = [f"{_ccore.CLASSES[cls].get('icon', '⚔️')} 【{cls_name}】当前可锻造({len(recs)} 件)", "━━━━━━━━━━━━"]
        base = (page - 1) * 5
        for i, (rk, rec) in enumerate(page_items, 1):
            lines.append(self._craft_line(rec, base + i))
        lines.append("━━━━━━━━━━━━")
        lines.append(f"📄 第 {page}/{pages} 页" + (f"｜『锻造 {cls_name} {page + 1}』下一页" if page < pages else ""))
        lines.append(self._tip("forge"))
        self._record_list_state(player.get("qq_id"), f"锻造 {cls_name}", page, pages)
        return "\n".join(lines)

    def _recipe_detail(self, rec_name: str) -> str:
        """配方详情文本(v41 供锻造/配方命令复用)"""
        rec = _clife.CRAFT_RECIPES[rec_name]
        q = _b143.QUALITY[rec["quality"]]
        rec_disp = C.display("recipes", rec_name)
        mats_str = "、".join(f"{C.display('materials', m)}×{n}" for m, n in rec["mats"].items())
        if rec.get("blueprint"):
            mats_str += f"、{rec['blueprint']}×1"
        lines = [
            f"📜 配方：{q['color']}【{rec_disp}】",
            f"🏷️ 类型：{_b143.EQUIP_SLOTS[rec['slot']]}  Lv.{rec['lv']}  {q['name']}",
            f"🧰 材料：{mats_str}",
            f"💰 费用：{rec['gold']} 金币",
        ]
        # M10 P3-4：114 配方全无 class 字段，原『职业/套装』行死代码永不显示；
        # 改为按 weapon_type 反查适用职业（与『锻造 <职业>』过滤口径一致），套装独立展示
        _wt = rec.get("weapon_type")
        if _wt:
            _cls_names = [C.display("classes", ck) for ck, cv in _ccore.CLASSES.items()
                          if cv.get("weapon_type") == _wt and ck != "cls_novice"]
            if _cls_names:
                lines.append(f"🎭 适用职业：{'、'.join(_cls_names)}")
        if rec.get("set"):
            lines.append(f"🎴 套装：{rec['set']}")
        if rec.get("blueprint"):
            lines.append(f"📜 需要图纸：{rec['blueprint']}(Boss 掉落/宝箱/垂钓/商店获得)")
        if rec.get("desc"):
            lines.append(f"📖 {rec['desc']}")
        lines.append("")
        lines.append(self._tip("forge"))
        return "\n".join(lines)

    @declared("recipe_list")
    @require_player()

    async def recipe_list(self, event: AstrMessageEvent):
        group_id, qq_id = self._uid(event)
        # v134.1 意见#39：『图纸列表』直接命中（不走『配方 图纸列表』绕路）
        if event.get_message_str().strip().startswith("图纸列表"):
            yield event.plain_result(self._learned_blueprint_list(self._player(group_id, qq_id)))
            return
        raw = self._strip_cmd(event, "配方")
        player = self._player(group_id, qq_id)
        text = raw.strip()
        # v134.1 意见#39：『图纸列表』= 已学图纸一览（独立指令，与『配方』全量列表区分）
        if text in ("图纸", "图纸列表", "列表 图纸", "已学"):
            yield event.plain_result(self._learned_blueprint_list(player))
            return
        # 无参数：按职业分组列出全部配方
        if not text or text == "列表":
            lines = ["📜 铁匠锻造配方(『锻造 <职业>』看该职业，『锻造 配方 <装备名>』看详情)：", ""]
            for cls in _ccore.CLASSES:
                icon = _ccore.CLASSES[cls].get("icon", "⚔️")
                cls_recs = [(n, r) for n, r in _clife.CRAFT_RECIPES.items()
                            if r.get("class") == cls or r.get("weapon_type") == _ccore.CLASSES[cls].get("weapon_type")
                            or r.get("slot") != "weapon"]  # M10 P2：防具/饰品全职业可锻，不再只在武器过滤下不可见
                lines.append(f"{icon} {C.display('classes', cls)}：{'、'.join(C.display('recipes', n) for n, _ in sorted(cls_recs, key=lambda x: x[1]['lv']))}")
            lines.append("")
            lines.append(self._tip("forge"))
            yield event.plain_result("\n".join(lines))
            return
        # 带参数：查看指定配方详情
        rec_name = C.craft_recipe_search(text)
        if not rec_name or rec_name not in _clife.CRAFT_RECIPES:  # 旧别名指向已删除配方 → 视作未找到
            # M10 P2 死别名引导：旧版本已移除的配方给出明确提示
            if any(text in al for als in _clife.CRAFT_RECIPE_ALIASES.values() for al in als):
                yield event.plain_result(f"『{text}』是旧版本已移除的配方！『配方』查看当前全部配方～")
            else:
                yield event.plain_result(f"没有找到『{text}』的配方！")
            return
        yield event.plain_result(self._recipe_detail(rec_name))

    @declared("enhance")
    @require_player()

    async def enhance(self, event: AstrMessageEvent):
        group_id, qq_id = self._uid(event)
        item_name = self._strip_cmd(event, "强化")
        player = self._player(group_id, qq_id)
        if not self._at_smith(player):
            yield event.plain_result("需要到铁匠铺/锻造坊才能强化装备！(先『地图』移动到铁匠铺)")
            return
        item_name = item_name.strip()
        if not item_name:
            yield event.plain_result("强化哪件装备？输入『强化 <装备名>』或『强化 <背包序号>』(如：强化 铁剑 / 强化 3)")
            return
        items = db.get_inventory(group_id, qq_id)
        target = None
        # 序号强化：『强化 3』→ 背包第 3 件（与『物品详情 3』同语义，全背包连续编号）
        if item_name.isdigit():
            idx = int(item_name)
            if idx < 1 or idx > len(items):
                yield event.plain_result(f"背包里没有第 {idx} 件物品(共 {len(items)} 件)！『背包』查看全部～")
                return
            target = items[idx - 1]
            if not target["data"].get("slot"):
                yield event.plain_result(f"背包第 {idx} 件『{target['data']['name']}』不是装备，不能强化！『背包』看装备序号～")
                return
        else:
            for it in items:
                d = it["data"]
                if d.get("slot") and item_name in d["name"]:
                    target = it
                    break
            if not target:
                # v101.25 #329：已装备的武器/装备无法直接强化（playtest round68 影刃抓包：
                # 『强化 弯刀』报背包里没有）。已装备物品在 equipment 槽位，补查并支持就地强化。
                eq = player.get("equipment") or {}
                for slot, ed in eq.items():
                    if item_name in (ed.get("name", "") if isinstance(ed, dict) else ""):
                        target = {"key": f"eq_equipped_{slot}", "data": ed, "_equipped": slot}
                        break
            if not target:
                yield event.plain_result(f"背包里没有叫『{item_name}』的装备！(已装备的武器也可以直接『强化 <武器名>』)")
                return
        d = target["data"]
        cur_enh = d.get("enhance", 0)
        if cur_enh >= _cit.MAX_ENHANCE:
            yield event.plain_result(f"【{d['name']}】已经强化到极限 +{cur_enh} 了！")
            return
        info = _cit.ENHANCE_TABLE[cur_enh]
        # v67 强化归位锻造 → 导师进修后强化为独立副业（19 章第八章）：强化 +N 需要强化副业 Lv.N
        ok, act_msg = self._prof_active_check(group_id, qq_id, "enhance", require_apprentice=True)
        if not ok:
            yield event.plain_result(act_msg)
            return
        prof_lv = db.get_prof_level(group_id, qq_id, "enhance")
        need = min(cur_enh + 1, 10)
        if prof_lv < need:
            yield event.plain_result(
                f"强化 +{cur_enh} → +{cur_enh+1} 需要强化副业 Lv.{need}(你 Lv.{prof_lv})！多强化装备升级吧～"
            )
            return
        if player["gold"] < info["cost"]:
            yield event.plain_result(f"强化 +{cur_enh} → +{cur_enh+1} 需要 {info['cost']} 金币，你只有 {player['gold']}。")
            return
        # v94 体力：强化消耗 10 体力（v104 M11：金币/副业等校验全通过后才扣，防白扣）
        _ok, _st = self._spend_stamina(group_id, qq_id, _clife.PROF_STAMINA_COST["enhance"], player, "强化")
        if not _ok:
            yield event.plain_result(_st)
            return
        db.update_player(group_id, qq_id, gold=player["gold"] - info["cost"])
        # v102.3 星铁强化剂：使用后下一次强化必定成功（一次性，成功后清除）
        _boost = db.get_event_state(f"enhance_boost_{qq_id}")
        if _boost:
            db.set_event_state(f"enhance_boost_{qq_id}", "")
        # v101.30 炼金强化材料接入：精炼强化石 = 成功率 +25%（自动消耗）；强化石 = 失败保护（失败不掉级）
        # v181.P4-4：成功率/强化石叠加纯规则下沉 services.crafting.compute_enhance_rate（结构化结果），
        # 扣料与文案行按结果在命令层执行/拼装（逐字符等价原内联段）
        _cr = _craft_svc.compute_enhance_rate(
            info["rate"], prof_lv, boost=_boost,
            has_refine=db.count_item(group_id, qq_id, _craft_svc.ENHANCE_STONE_REFINE) >= 1,
            has_blessed=db.count_item(group_id, qq_id, _craft_svc.ENHANCE_STONE_BLESSED) >= 1,
        )
        _rate = _cr["rate"]
        _craft_line = _cr["craft_line"]  # O108 修复：手艺加成行单独存（_craft_line），升级当次重算后再拼回
        _stone_line = _craft_line
        for _sk in _cr["stones_used"]:  # 等价原内联扣料+文案行（消耗顺序：精炼→祝福，与判定顺序一致）
            if _sk == _craft_svc.ENHANCE_STONE_REFINE:
                db.remove_item(group_id, qq_id, _craft_svc.ENHANCE_STONE_REFINE, 1)
                _stone_line += "\n✨ 精炼强化石淬入火中，成功率提升了！"
            elif _sk == _craft_svc.ENHANCE_STONE_BLESSED:
                db.remove_item(group_id, qq_id, _craft_svc.ENHANCE_STONE_BLESSED, 1)
                _stone_line += "\n✨ 祝福符石泛起微光，成功率提升了！"
        _protect_have = db.count_item(group_id, qq_id, _craft_svc.ENHANCE_STONE_PROTECT)
        # 掷强化
        if _boost or random.random() < _rate:
            d["enhance"] = cur_enh + 1
            if target.get("_equipped"):
                # v101.25 #329：已装备武器强化成功 → 写回装备槽位（属性实时生效）
                eq = dict(player.get("equipment") or {})
                eq[target["_equipped"]] = d
                db.update_player(group_id, qq_id, equipment=eq)
            else:
                # F1 P0-1：背包格原子写回（替代 remove+add 两步非原子替换）
                db.update_item_data(group_id, qq_id, target["key"], d)
            # O93 修复：成功文案补金币消耗显示（实际扣款在上方 db.update_player(gold=...)）
            lines = [f"🔨 强化成功！【{d['name']}】+{cur_enh} → +{cur_enh+1}！(消耗 {info['cost']} 金币)"]
            # v101.30 强化经验按段位：+0→+1 给 1 …… +8→+9 给 9（高段强化是升级主路径，
            # 刷必成的 +0→+1 只能拿 1 经验/50 金，成长极慢——赌得越高练得越快）
            new_lv, leveled = db.add_prof_exp(group_id, qq_id, "enhance", cur_enh + 1)
            if leveled:
                lines.append(f"🌟 强化副业提升到 Lv.{new_lv}！")
                # O108 修复：升级当次即按新等级重算手艺加成（原 _stone_line 仍用升级前旧等级，
                # 导致当次提示 Lv.3 +1.5%、下次才 Lv.4 +2.0%）
                if _craft_line:
                    _new_bonus = min(new_lv, 10) * 0.005
                    _new_craft = f"\n🛠️ 强化师 Lv.{new_lv} 的手艺：成功率 +{_new_bonus*100:.1f}%！"
                    _stone_line = _stone_line.replace(_craft_line, _new_craft)
            _done, _msg = self._daily_prof_bump(group_id, qq_id, "enhance")
            if _msg:
                lines.append(_msg.strip())
            # 阶段九：强化次数 + 成就判定
            db.bump_stats(group_id, qq_id, enhance_count=1)
            C.check_achievements(group_id, qq_id, player)
            if cur_enh + 1 == 5:
                lines.append("⚡ 装备绽放出耀眼的光芒！")
            elif cur_enh + 1 == 9:
                lines.append("🌟 传说级的光芒冲天而起！你听见了铁匠们的惊叹！")
            if _stone_line:
                lines.append(_stone_line)
            yield event.plain_result("\n".join(lines))
        else:
            # v181.P4-4：失败保级/降级纯规则下沉 services.crafting.enhance_fail_floor（结构化结果），
            # 保护石消耗按结果执行（逐字符等价原内联失败分支）
            _new_enh, _protect_used = _craft_svc.enhance_fail_floor(
                cur_enh, has_protect=_protect_have >= 1)
            new_enh = _new_enh
            if _protect_used:
                # v101.30 强化石失败保护：消耗 1 个，不掉级
                db.remove_item(group_id, qq_id, _craft_svc.ENHANCE_STONE_PROTECT, 1)
                yield event.plain_result(
                    f"💥 强化失败！但强化石轰然炸开挡住了冲击，【{d['name']}】保住了等级(+{cur_enh})！\n"
                    # O93 修复：失败文案补金币消耗显示（强化石×1 之外同时列出金币）
                    f"(消耗强化石×1 + {info['cost']} 金币{_stone_line})"
                )
                return
            if new_enh != cur_enh:
                d["enhance"] = new_enh
                if target.get("_equipped"):
                    # v101.25 #329：已装备武器强化失败降级 → 同步写回装备槽位
                    eq = dict(player.get("equipment") or {})
                    eq[target["_equipped"]] = d
                    db.update_player(group_id, qq_id, equipment=eq)
                else:
                    # F1 P0-1：背包格原子写回（替代 remove+add 两步非原子替换）
                    db.update_item_data(group_id, qq_id, target["key"], d)
                # O93 修复：失败(降级)文案补金币消耗显示
                yield event.plain_result(f"💥 强化失败！【{d['name']}】降级到 +{new_enh}。铁匠摇摇头：『下次一定行！』(消耗 {info['cost']} 金币)")
            else:
                # O93 修复：失败(保级)文案补金币消耗显示
                yield event.plain_result(f"💥 强化失败！好在【{d['name']}】保住了等级(+{new_enh})。再试一次？(消耗 {info['cost']} 金币)")

    @declared("equip_upgrade")
    @require_player()

    async def equip_upgrade(self, event: AstrMessageEvent):
        """v172 装备升级（真等级化，原 v135 倍率层）：装备 lv → lv+1，属性随 equip_stats 重算。

        定位：强化=赌（运气掉级）、升级=养（稳定保底）、附魔=快（一次成型）。
        真等级化：每次升级装备 lv +1（上限 = 玩家当前等级，追平即止，不许超前）；
        属性按生成公式重算（词条/附魔/宝石全保留，只重算基础 stats 并同步 price）。
        副业门复用强化副业等级；材料每级 1 精炼强化石；金币按 UPGRADE_TABLE 目标级阶梯。
        """
        group_id, qq_id = self._uid(event)
        item_name = self._strip_cmd(event, "升级")
        player = self._player(group_id, qq_id)
        if not self._at_smith(player):
            yield event.plain_result("需要到铁匠铺/锻造坊才能升级装备！(先『地图』移动到铁匠铺)")
            return
        item_name = item_name.strip()
        if not item_name:
            yield event.plain_result("升级哪件装备？输入『升级 <装备名>』或『升级 <背包序号>』(如：升级 铁剑 / 升级 3)")
            return
        items = db.get_inventory(group_id, qq_id)
        target = None
        # 序号升级：『升级 3』→ 背包第 3 件（与强化同语义）
        if item_name.isdigit():
            idx = int(item_name)
            if idx < 1 or idx > len(items):
                yield event.plain_result(f"背包里没有第 {idx} 件物品(共 {len(items)} 件)！『背包』查看全部～")
                return
            target = items[idx - 1]
            if not target["data"].get("slot"):
                yield event.plain_result(f"背包第 {idx} 件『{target['data']['name']}』不是装备，不能升级！『背包』看装备序号～")
                return
        else:
            for it in items:
                d = it["data"]
                if d.get("slot") and item_name in d["name"]:
                    target = it
                    break
            if not target:
                # 已装备的装备补查并支持就地升级（与强化同款）
                eq = player.get("equipment") or {}
                for slot, ed in eq.items():
                    if item_name in (ed.get("name", "") if isinstance(ed, dict) else ""):
                        target = {"key": f"eq_equipped_{slot}", "data": ed, "_equipped": slot}
                        break
            if not target:
                yield event.plain_result(f"背包里没有叫『{item_name}』的装备！(已装备的装备也可以直接『升级 <装备名>』)")
                return
        d = target["data"]
        # v172 真等级化：升级 = 装备 lv +1（上限追平玩家等级，不许超前——穿装门槛按 d['lv'] 判）
        cur_lv = d.get("lv", 0) or 0
        next_lv = cur_lv + 1
        if next_lv > (player.get("level") or 1):
            yield event.plain_result(f"【{d['name']}】已是 Lv.{cur_lv}，再升需要你 Lv.{next_lv}（你 Lv.{player.get('level')}）！"
                                     f"升级追平玩家等级就到顶，先练级再来～")
            return
        # 金币：UPGRADE_TABLE cost 阶梯按装备当前级取（Lv.3→4 花 3 级档 675；超过 10 级封顶
        # 用 10 级档 11524——表只到 10，真等级化后高等级装备每 +1 级消耗表末档）
        upg_tbl = _cit.UPGRADE_TABLE or {}
        info = upg_tbl.get(min(cur_lv, 10)) or upg_tbl.get(next_lv) or {"cost": 300}
        # 副业门：升级等级 ≤ 强化副业等级（与强化同门槛，形成强化→升级进阶路径）
        ok, act_msg = self._prof_active_check(group_id, qq_id, "enhance", require_apprentice=True)
        if not ok:
            yield event.plain_result(act_msg)
            return
        prof_lv = db.get_prof_level(group_id, qq_id, "enhance")
        need = min(next_lv, 10)
        if prof_lv < need:
            yield event.plain_result(
                f"升级 Lv.{cur_lv} → Lv.{next_lv} 需要强化副业 Lv.{need}(你 Lv.{prof_lv})！"
                f"强化与升级共修，多强化装备升级副业吧～"
            )
            return
        if player["gold"] < info["cost"]:
            yield event.plain_result(f"升级 Lv.{cur_lv} → Lv.{next_lv} 需要 {info['cost']} 金币，你只有 {player['gold']}。")
            return
        # 材料：每级 1 精炼强化石
        if db.count_item(group_id, qq_id, _cit.UPGRADE_STONE) < 1:
            yield event.plain_result(f"升级 Lv.{cur_lv} → Lv.{next_lv} 需要 1 个{_cit.UPGRADE_MATERIAL_CN}！"
                                     f"(铁匠铺/炼金可得，『背包』查看～)")
            return
        # 体力：升级消耗 10（全校验通过后才扣，防白扣）
        _ok, _st = self._spend_stamina(group_id, qq_id, _cit.UPGRADE_STAMINA, player, "升级")
        if not _ok:
            yield event.plain_result(_st)
            return
        db.update_player(group_id, qq_id, gold=player["gold"] - info["cost"])
        db.remove_item(group_id, qq_id, _cit.UPGRADE_STONE, 1)
        # 升级必定成功（与强化差异化：稳定保底）——真等级化：lv +1 + 属性按生成公式重算
        _upgrade_recalc_equip(d, next_lv)
        if target.get("_equipped"):
            eq = dict(player.get("equipment") or {})
            eq[target["_equipped"]] = d
            db.update_player(group_id, qq_id, equipment=eq)
        else:
            db.update_item_data(group_id, qq_id, target["key"], d)
        lines = [f"🔧 装备升级成功！【{d['name']}】Lv.{cur_lv} → Lv.{next_lv}"
                 f" ｜ 属性随等级重算(消耗 {info['cost']} 金币 + {_cit.UPGRADE_MATERIAL_CN}×1)"]
        # 升级也给强化副业少量经验（高段多给，与强化同思路：养得越深练得越快）
        new_lv, leveled = db.add_prof_exp(group_id, qq_id, "enhance", max(1, next_lv))
        if leveled:
            lines.append(f"🌟 强化副业提升到 Lv.{new_lv}！")
        _done, _msg = self._daily_prof_bump(group_id, qq_id, "enhance")
        if _msg:
            lines.append(_msg.strip())
        db.bump_stats(group_id, qq_id, enhance_count=1)  # 升级并入强化养成计数（stats 白名单）
        C.check_achievements(group_id, qq_id, player)
        yield event.plain_result("\n".join(lines))

    # ================= v136 原石系统：打孔/镶嵌/拆卸/合成/查看 =================

    def _gem_find_equip(self, group_id, qq_id, player, item_name):
        """查找装备目标（背包连续编号 + 背包名匹配 + 已装备槽位，与强化/升级同语义）。

        返回 (target, err)：
        - target: {"key","data","_equipped"?}，err 为空串
        - 失败：target=None，err=提示文案（非装备/未找到/序号越界等）
        """
        item_name = (item_name or "").strip()
        items = db.get_inventory(group_id, qq_id)
        if item_name.isdigit():
            idx = int(item_name)
            if idx < 1 or idx > len(items):
                return None, f"背包里没有第 {idx} 件物品(共 {len(items)} 件)！『背包』查看全部～"
            target = items[idx - 1]
            if not target["data"].get("slot"):
                return None, f"背包第 {idx} 件『{target['data']['name']}』不是装备，不能操作！『背包』看装备序号～"
            return target, ""
        for it in items:
            d = it["data"]
            if d.get("slot") and item_name in d["name"]:
                return it, ""
        eq = player.get("equipment") or {}
        for slot, ed in eq.items():
            if item_name in (ed.get("name", "") if isinstance(ed, dict) else ""):
                return {"key": f"eq_equipped_{slot}", "data": ed, "_equipped": slot}, ""
        return None, f"背包里没有叫『{item_name}』的装备！(已装备的装备也可以直接操作，如『打孔 铁剑』)"

    def _gem_find_gem(self, group_id, qq_id, raw):
        """按 名称子串/背包序号 找背包里的原石（type=原石 或 gem=True）。

        返回 (gem_item, err)：gem_item 含 key/data/count，失败时 (None, 提示)。
        """
        raw = (raw or "").strip()
        if not raw:
            return None, "哪颗幸运宝石？输入『原石』查看背包里的幸运宝石～"
        gems = [it for it in db.get_inventory(group_id, qq_id)
                if it["data"].get("gem") or it["data"].get("type") in ("原石", "幸运宝石")]
        if raw.isdigit():
            idx = int(raw)
            if idx < 1 or idx > len(gems):
                return None, f"背包里没有第 {idx} 颗幸运宝石(共 {len(gems)} 颗)！『原石』查看～"
            return gems[idx - 1], ""
        for it in gems:
            if raw in it["data"].get("name", ""):
                return it, ""
        return None, f"背包里没有『{raw}』！『原石』查看背包里的幸运宝石～"

    @declared("gem_drill")
    @require_player()

    async def gem_drill(self, event: AstrMessageEvent):
        """v136 原石系统：『打孔 <装备名/序号>』——铁匠铺为蓝/紫/橙装打出 S1/S2/S3 孔位。

        费用+锻造副业门槛查 GEM_DRILL（蓝 500 金/锻造 Lv.1，紫 1500/Lv.3，橙 4000/Lv.5）；
        白/绿装无孔位；已有孔位无需再打（防重复扣费）。
        """
        group_id, qq_id = self._uid(event)
        item_name = self._strip_cmd(event, "打孔")
        player = self._player(group_id, qq_id)
        if not self._at_smith(player):
            yield event.plain_result("需要到铁匠铺/锻造坊才能打孔！(先『地图』移动到铁匠铺)")
            return
        item_name = item_name.strip()
        if not item_name:
            yield event.plain_result("给哪件装备打孔？输入『打孔 <装备名>』或『打孔 <背包序号>』(如：打孔 铁剑 / 打孔 3)")
            return
        target, err = self._gem_find_equip(group_id, qq_id, player, item_name)
        if not target:
            yield event.plain_result(err)
            return
        d = target["data"]
        quality = d.get("quality", "white")
        qinfo = _b143.GEM_SOCKETS.get(quality)
        if not qinfo or qinfo.get("count", 0) <= 0:
            yield event.plain_result(
                f"【{d['name']}】({_b143.QUALITY.get(quality, {}).get('name', '')})没有孔位可打，只有蓝/紫/橙装备可以打孔！")
            return
        if d.get("sockets"):
            yield event.plain_result(f"【{d['name']}】已经有 {len(d['sockets'])} 个孔位了，不用再打～")
            return
        info = _b143.GEM_DRILL.get(quality)
        if not info:
            yield event.plain_result(f"【{d['name']}】的品质不支持打孔！")
            return
        # 副业门槛：锻造副业等级（v95.22 拜师校验同款）
        ok, act_msg = self._prof_active_check(group_id, qq_id, "craft", require_apprentice=True)
        if not ok:
            yield event.plain_result(act_msg)
            return
        prof_lv = db.get_prof_level(group_id, qq_id, "craft")
        if prof_lv < info["craft_lv"]:
            yield event.plain_result(
                f"打孔需要锻造副业 Lv.{info['craft_lv']}(你 Lv.{prof_lv})！多锻造装备升级吧～")
            return
        if player["gold"] < info["cost"]:
            yield event.plain_result(f"打孔需要 {info['cost']} 金币，你只有 {player['gold']}。")
            return
        # 体力：打孔消耗 10（全校验通过后才扣，防白扣）
        _ok, _st = self._spend_stamina(group_id, qq_id, _clife.PROF_STAMINA_COST["craft"], player, "打孔")
        if not _ok:
            yield event.plain_result(_st)
            return
        count = qinfo["count"]
        slots = {f"S{i}": None for i in range(1, count + 1)}
        d["sockets"] = slots
        if target.get("_equipped"):
            eq = dict(player.get("equipment") or {})
            eq[target["_equipped"]] = d
            db.update_player(group_id, qq_id, equipment=eq)
        else:
            db.update_item_data(group_id, qq_id, target["key"], d)
        db.update_player(group_id, qq_id, gold=player["gold"] - info["cost"])
        names = "/".join(slots.keys())
        yield event.plain_result(
            f"🔨 打孔成功！【{d['name']}】现在有 {count} 个孔位({names})！"
            f"『镶嵌 {d['name']} <原石>』放入幸运宝石～")

    @declared("gem_socket")
    @require_player()

    async def gem_socket(self, event: AstrMessageEvent):
        """v136 原石系统：『镶嵌 <装备名> <原石名/序号> [孔位]』——把原石镶入装备孔位。

        孔位可选（默认第一个空孔）；原石层数须在孔位层数范围（GEM_SOCKETS[quality]）；
        孔位已占/无空孔/层数超范围均拦截。原石扣出背包，写 sockets[孔位]=原石 dict。
        """
        group_id, qq_id = self._uid(event)
        raw = self._strip_cmd(event, "镶嵌")
        player = self._player(group_id, qq_id)
        if not self._at_smith(player):
            yield event.plain_result("需要到铁匠铺/锻造坊才能镶嵌原石！(先『地图』移动到铁匠铺)")
            return
        parts = raw.strip().split()
        if len(parts) < 2:
            yield event.plain_result(
                "镶嵌哪颗幸运宝石到哪件装备？输入『镶嵌 <装备名> <原石名/序号> [孔位]』\n"
                "如：『镶嵌 铁剑 碎裂的幸运宝石』『镶嵌 铁剑 1』『镶嵌 铁剑 碎裂 S2』(孔位默认第一个空孔)")
            return
        item_name, gem_raw = parts[0], parts[1]
        slot_arg = parts[2] if len(parts) > 2 else ""
        target, err = self._gem_find_equip(group_id, qq_id, player, item_name)
        if not target:
            yield event.plain_result(err)
            return
        d = target["data"]
        socks = d.get("sockets")
        if not socks:
            yield event.plain_result(
                f"【{d['name']}】还没有孔位！先『打孔 {d['name']}』打出孔位再镶嵌～")
            return
        gem_item, err = self._gem_find_gem(group_id, qq_id, gem_raw)
        if not gem_item:
            yield event.plain_result(err)
            return
        gd = gem_item["data"]
        quality = d.get("quality", "white")
        cap = _b143.GEM_SOCKETS.get(quality)
        min_t = (cap or {}).get("min_tier", 0)
        max_t = (cap or {}).get("max_tier", 0)
        if not (min_t <= gd.get("tier", 0) <= max_t):
            yield event.plain_result(
                f"【{d['name']}】({_b143.QUALITY.get(quality, {}).get('name', '')})的孔位只能镶 "
                f"{_b143.GEM_TIER_NAMES.get(min_t, min_t)}~{_b143.GEM_TIER_NAMES.get(max_t, max_t)} 的幸运宝石"
                f"(你选的是 {gd['name']})！")
            return
        # 孔位解析：显式孔位（S1/S2/S3）→ 校验存在且空；未给 → 第一个空孔
        target_slot = ""
        if slot_arg:
            slot_arg = slot_arg.strip().upper()
            if slot_arg not in socks:
                yield event.plain_result(
                    f"【{d['name']}】没有 {slot_arg} 这个孔位(孔位：{'/'.join(socks)})！")
                return
            if socks[slot_arg] is not None:
                yield event.plain_result(
                    f"【{d['name']}】的 {slot_arg} 已经镶了『{socks[slot_arg].get('name', '')}』！"
                    f"『拆卸 {d['name']} {slot_arg}』先拆下来～")
                return
            target_slot = slot_arg
        else:
            for sk, sv in socks.items():
                if sv is None:
                    target_slot = sk
                    break
            if not target_slot:
                yield event.plain_result(
                    f"【{d['name']}】的 {len(socks)} 个孔位都满了，没有空孔！"
                    f"『拆卸 <装备名> <孔位>』拆一颗再镶～")
                return
        db.remove_item(group_id, qq_id, gem_item["key"], 1)
        socks[target_slot] = dict(gd)
        if target.get("_equipped"):
            eq = dict(player.get("equipment") or {})
            eq[target["_equipped"]] = d
            db.update_player(group_id, qq_id, equipment=eq)
        else:
            db.update_item_data(group_id, qq_id, target["key"], d)
        yield event.plain_result(
            f"💎 镶嵌成功！【{d['name']}】{target_slot} 镶入 {gd['name']}！"
            f"『原石』查看背包剩余幸运宝石～")

    @declared("gem_remove")
    @require_player()

    async def gem_remove(self, event: AstrMessageEvent):
        """v136 原石系统：『拆卸 <装备名> <孔位>』——铁匠铺拆下孔位里的原石。

        拆卸费 500×原石层数（GEM_REMOVE_COST × tier）；原石回背包（key=gem_<uuid8>）。
        """
        group_id, qq_id = self._uid(event)
        raw = self._strip_cmd(event, "拆卸")
        player = self._player(group_id, qq_id)
        if not self._at_smith(player):
            yield event.plain_result("需要到铁匠铺/锻造坊才能拆卸原石！(先『地图』移动到铁匠铺)")
            return
        parts = raw.strip().split()
        if len(parts) < 2:
            yield event.plain_result(
                "拆卸哪个孔位的幸运宝石？输入『拆卸 <装备名> <孔位>』(如：拆卸 铁剑 S1)")
            return
        item_name, slot_arg = parts[0], parts[1].strip().upper()
        target, err = self._gem_find_equip(group_id, qq_id, player, item_name)
        if not target:
            yield event.plain_result(err)
            return
        d = target["data"]
        socks = d.get("sockets") or {}
        if slot_arg not in socks:
            yield event.plain_result(
                f"【{d['name']}】没有 {slot_arg} 这个孔位(孔位：{'/'.join(socks) or '无'})！")
            return
        if socks[slot_arg] is None:
            yield event.plain_result(f"【{d['name']}】的 {slot_arg} 是空孔，没有幸运宝石可拆～")
            return
        gd = socks[slot_arg]
        cost = C.gem_socket_cost(gd)
        if player["gold"] < cost:
            yield event.plain_result(f"拆卸需要 {cost} 金币(500×层数)，你只有 {player['gold']}。")
            return
        db.update_player(group_id, qq_id, gold=player["gold"] - cost)
        import uuid
        db.add_item(group_id, qq_id, f"gem_{uuid.uuid4().hex[:8]}", dict(gd))
        socks[slot_arg] = None
        if target.get("_equipped"):
            eq = dict(player.get("equipment") or {})
            eq[target["_equipped"]] = d
            db.update_player(group_id, qq_id, equipment=eq)
        else:
            db.update_item_data(group_id, qq_id, target["key"], d)
        yield event.plain_result(
            f"🔧 拆卸成功！取回 {gd['name']}，花费 {cost} 金币"
            f"(已放回背包，『原石』查看～)")

    @declared("gem_combine")
    @require_player()

    async def gem_combine(self, event: AstrMessageEvent):
        """v136 原石系统：『原石合成 [原石名/序号]』——3 个同级原石 → 1 个上级。

        无参 → 列出背包里可合成的原石（按 tier 分组）；带参 → 消耗 3 个同名同级原石合成；
        传说II(tier=10) 无法再合成。
        """
        group_id, qq_id = self._uid(event)
        raw = self._strip_cmd(event, "原石合成")
        player = self._player(group_id, qq_id)
        if not self._at_smith(player):
            yield event.plain_result("需要到铁匠铺/锻造坊才能合成原石！(先『地图』移动到铁匠铺)")
            return
        items = db.get_inventory(group_id, qq_id)
        gems = [it for it in items
                if it["data"].get("gem") or it["data"].get("type") in ("原石", "幸运宝石")]
        if not raw:
            # 无参：列出可合成原石（按 tier 分组，≥3 颗可合成）
            by_tier = {}
            for it in gems:
                by_tier.setdefault(it["data"].get("tier", 0), []).append(it)
            lines = ["💎 【原石合成】3 个同级原石 → 1 个上级，无失败！", "━━━━━━━━━━━━"]
            shown = 0
            for tier in sorted(by_tier):
                if tier >= 10:
                    continue
                gd = by_tier[tier][0]["data"]
                cnt = sum(it["count"] for it in by_tier[tier])
                ok = "✅" if cnt >= 3 else "❌"
                lines.append(f"{ok} {gd['name']} ×{cnt}/3  →  {_b143.GEM_TIER_NAMES.get(tier + 1, '?')}")
                shown += 1
            if shown == 0:
                lines.append("背包里还没有可合成的幸运宝石！打怪有概率掉落幸运宝石～")
            lines.append("━━━━━━━━━━━━")
            lines.append("💡 『原石合成 <原石名/序号>』消耗 3 颗同级幸运宝石合成 1 颗上级(神话 不可再合成)")
            yield event.plain_result("\n".join(lines))
            return
        if not gems:
            yield event.plain_result("背包里还没有幸运宝石！打怪有概率掉落幸运宝石～")
            return
        gem_item, err = self._gem_find_gem(group_id, qq_id, raw)
        if not gem_item:
            yield event.plain_result(err)
            return
        gd = gem_item["data"]
        tier = gd.get("tier", 0)
        if tier >= 10:
            yield event.plain_result(f"{gd['name']} 已是传说II，无法再合成了！")
            return
        # 统计同 tier 全部原石数量（跨堆）
        same_tier = [it for it in gems if it["data"].get("tier") == tier]
        total = sum(it["count"] for it in same_tier)
        if total < 3:
            yield event.plain_result(
                f"合成需要 3 颗 {_b143.GEM_TIER_NAMES.get(tier, tier)}，你有 {total} 颗！")
            return
        # 扣 3 颗同 tier（跨堆扣取，key 优先）
        remain = 3
        for it in same_tier:
            if remain <= 0:
                break
            take = min(it["count"], remain)
            if db.remove_item(group_id, qq_id, it["key"], take):
                remain -= take
        new_gem = C.gem_combine([gd, gd, gd])
        db.add_item(group_id, qq_id, f"gem_{__import__('uuid').uuid4().hex[:8]}", new_gem)
        yield event.plain_result(
            f"✨ 三颗 {gd['name']} 光芒交织，合成了更纯粹的幸运宝石！\n"
            f"✅ 合成成功！获得 {new_gem['name']}(消耗 3 颗，无失败)")

    @declared("gem_view")
    @require_player()

    async def gem_view(self, event: AstrMessageEvent):
        """v136 原石系统：『原石』——查看背包全部原石（名称/层数/属性/孔位需求）。"""
        group_id, qq_id = self._uid(event)
        items = db.get_inventory(group_id, qq_id)
        gems = [it for it in items
                if it["data"].get("gem") or it["data"].get("type") in ("原石", "幸运宝石")]
        if not gems:
            yield event.plain_result(
                "💎 背包里还没有幸运宝石！打怪有概率掉落幸运宝石～\n"
                "💡 『打孔 <装备>』给蓝/紫/橙装开孔，『镶嵌 <装备> <原石>』镶入获得属性！")
            return
        lines = [f"💎 【幸运宝石】(共 {sum(it['count'] for it in gems)} 颗)", "━━━━━━━━━━━━"]
        _SNAMES = C.STAT_NAMES if hasattr(C, "STAT_NAMES") else {}
        for it in gems:
            gd = it["data"]
            stats_str = "、".join(
                f"{_SNAMES.get(k, k)}+{int(v * 100)}%" for k, v in (gd.get("stats") or {}).items())
            need = "蓝孔" if gd.get("tier", 1) <= 2 else ("紫孔" if gd.get("tier", 1) <= 4 else "橙孔")
            lines.append(f"💎 {gd['name']} ×{it['count']} ｜ 阶{gd.get('tier', '?')} ｜ {stats_str} ｜ {need}")
        lines.append("━━━━━━━━━━━━")
        lines.append("💡 『镶嵌 <装备> <原石>』镶入装备 ｜ 『原石合成 <原石>』3 合 1 升级 ｜ 『拆卸 <装备> <孔位>』取下")
        yield event.plain_result("\n".join(lines))

    # ================= v136 符文制作 / 符文拆卸（Phase 3：掉落 → 掉落+可制作） =================

    def _rune_craft_panel(self, player):
        """符文制作面板（无参时展示全部配方：素材+碎片+制作费）。"""
        lines = ["🔮 【符文制作】掉落之外，铁匠铺可用怪物素材+符文碎片合成符文(1 级)！",
                 "━━━━━━━━━━━━"]
        for rkey, r in _cit.RUNES.items():
            cfg = _cit.RUNE_CRAFT.get(rkey)
            if not cfg:
                continue
            mname = C.display("materials", cfg["mat"])
            shards = _b143.RUNE_CRAFT_SHARDS.get(r["quality"], 3)
            fee = r.get("cost", 0) // 2
            lines.append(f"{_b143.QUALITY[r['quality']]['color']}符文·{r.get('name', rkey)}"
                         f"：{mname}×{cfg['count']}+符文碎片×{shards}+{fee}金")
        lines.append("━━━━━━━━━━━━")
        lines.append("💡 『符文制作 <符文名>』消耗素材+符文碎片+金币，获得 1 级符文"
                     "(符文碎片=拆卸符文回收，隐藏怪「符文魔像」也掉落)")
        return "\n".join(lines)

    @declared("rune_craft")
    @require_player()

    async def rune_craft(self, event: AstrMessageEvent):
        """v136 符文制作：『符文制作 <符文名>』——铁匠铺用怪物素材+符文碎片+金币合成 1 级符文。

        配方表 _cit.RUNE_CRAFT（素材按品质 2/3/4 个）+ C.RUNE_CRAFT_SHARDS（碎片 3/4/6 个）；
        制作费 = 符文 cost 的一半（rune_item price 同源）；体力 10（全校验通过后才扣）。
        产出 C.rune_item(effect, 1)，key=rune_<effect>_1（与掉落同 key，可堆叠）。
        """
        group_id, qq_id = self._uid(event)
        player = self._player(group_id, qq_id)
        if not self._at_smith(player):
            yield event.plain_result("需要到铁匠铺/锻造坊才能制作符文！(先『地图』移动到铁匠铺)")
            return
        raw = self._strip_cmd(event, "符文制作").strip()
        if not raw:
            yield event.plain_result(self._rune_craft_panel(player))
            return
        # 解析符文：ID / 中文名 / 子串
        rkey = None
        if raw in _cit.RUNES:
            rkey = raw
        else:
            rkey = C.resolve("runes", raw)
            if rkey not in _cit.RUNES:
                hits = [k for k, r in _cit.RUNES.items() if raw in r.get("name", "")]
                rkey = hits[0] if hits else rkey
        if rkey not in _cit.RUNES:
            yield event.plain_result(
                f"没有『{raw}』这个符文！『符文制作』查看全部可制作符文～")
            return
        r = _cit.RUNES[rkey]
        cfg = _cit.RUNE_CRAFT.get(rkey)
        if not cfg:
            yield event.plain_result(f"『{r.get('name', rkey)}』暂时不能制作，只能靠打怪掉落～")
            return
        # 体力：所有校验通过后才扣（防白扣，与炼金/附魔对齐）
        _ok, _st = self._spend_stamina(group_id, qq_id, _clife.PROF_STAMINA_COST["craft"], player, "符文制作")
        if not _ok:
            yield event.plain_result(_st)
            return
        # 材料校验
        items = db.get_inventory(group_id, qq_id)
        mname = C.display("materials", cfg["mat"])
        have_mat = sum(it["count"] for it in items if it["data"].get("name") == mname)
        if have_mat < cfg["count"]:
            yield event.plain_result(f"材料不足！制作【{r.get('name', rkey)}】需要 {mname}×{cfg['count']}(你有 {have_mat})")
            return
        shards = _b143.RUNE_CRAFT_SHARDS.get(r["quality"], 3)
        have_shard = db.count_item(group_id, qq_id, "符文碎片")
        if have_shard < shards:
            yield event.plain_result(f"符文碎片不足！制作【{r.get('name', rkey)}】需要 符文碎片×{shards}(你有 {have_shard})"
                                     f"(拆卸符文回收，或隐藏怪「符文魔像」掉落)")
            return
        fee = r.get("cost", 0) // 2
        if player["gold"] < fee:
            yield event.plain_result(f"制作【{r.get('name', rkey)}】需要 {fee} 金币，你只有 {player['gold']}。")
            return
        # 扣素材（跨堆）+ 碎片 + 金币
        remain = cfg["count"]
        for it in items:
            if remain <= 0:
                break
            if it["data"].get("name") == mname:
                take = min(it["count"], remain)
                if db.remove_item(group_id, qq_id, it["key"], take):
                    remain -= take
        remain = shards
        for it in items:
            if remain <= 0:
                break
            if it["data"].get("name") == "符文碎片":
                take = min(it["count"], remain)
                if db.remove_item(group_id, qq_id, it["key"], take):
                    remain -= take
        db.update_player(group_id, qq_id, gold=player["gold"] - fee)
        # 产出 1 级符文（key=rune_<effect>_1，与掉落同 key 可堆叠）
        rune_data = C.rune_item(r["effect"], 1)
        db.add_item(group_id, qq_id, f"rune_{r['effect']}_1", rune_data)
        # 副业经验（锻造 +1，与炼金/烹饪同思路）
        new_lv, leveled = db.add_prof_exp(group_id, qq_id, "craft", 1)
        _lv_msg = f"\n🌟 锻造副业提升到 Lv.{new_lv}！" if leveled else ""
        _done, _msg = self._daily_prof_bump(group_id, qq_id, "craft")
        if _msg:
            _lv_msg += "\n" + _msg.strip()
        db.bump_stats(group_id, qq_id, craft_count=1)
        C.check_achievements(group_id, qq_id, player)
        yield event.plain_result(
            f"🔮 【符文制作成功】获得了【{rune_data['name']}】！({rune_data['desc']})\n"
            f"(消耗 {mname}×{cfg['count']}+符文碎片×{shards}+{fee}金币)\n"
            f"💡 『附魔 <装备> {rune_data['name']}』刻印到装备上！{_lv_msg}")

    @declared("rune_remove")
    @require_player()

    async def rune_remove(self, event: AstrMessageEvent):
        """v136 符文拆卸：『符文拆卸 <装备名> <孔位>』——铁匠铺从装备附魔槽拆下符文。

        附魔槽 enchant 列表里 effect 项即符文（与属性附魔 stat 项区分）：
        按 装备名(序号/子串/已装备) 匹配装备 → 拆最后一段符文（默认）或 <孔位> 指定第 N 个符文效果。
        手续费 1000×符文等级（C.RUNE_REMOVE_COST × lvl）；回收 符文碎片×等级。
        （原石走『拆卸 <装备> <孔位>』500×层数，两命令并行不冲突。）
        """
        group_id, qq_id = self._uid(event)
        raw = self._strip_cmd(event, "符文拆卸")
        player = self._player(group_id, qq_id)
        if not self._at_smith(player):
            yield event.plain_result("需要到铁匠铺/锻造坊才能拆卸符文！(先『地图』移动到铁匠铺)")
            return
        parts = raw.strip().split()
        if not parts:
            yield event.plain_result(
                "拆卸哪个装备上的符文？输入『符文拆卸 <装备名> [孔位]』(如：符文拆卸 铁剑 / 符文拆卸 铁剑 2)")
            return
        item_name = parts[0]
        slot_arg = parts[1] if len(parts) > 1 else ""
        # 找装备：背包（序号/子串）+ 已装备槽位（与强化/升级/附魔同语义）
        items = db.get_inventory(group_id, qq_id)
        target = None
        if item_name.isdigit():
            idx = int(item_name)
            if idx < 1 or idx > len(items):
                yield event.plain_result(f"背包里没有第 {idx} 件物品(共 {len(items)} 件)！『背包』查看全部～")
                return
            target = items[idx - 1]
            if not target["data"].get("slot"):
                yield event.plain_result(f"背包第 {idx} 件『{target['data']['name']}』不是装备，不能拆符文！")
                return
        else:
            for it in items:
                d = it["data"]
                if d.get("slot") and item_name in d["name"]:
                    target = it
                    break
            if not target:
                eq = player.get("equipment") or {}
                for slot, ed in eq.items():
                    if item_name in (ed.get("name", "") if isinstance(ed, dict) else ""):
                        target = {"key": f"eq_equipped_{slot}", "data": ed, "_equipped": slot}
                        break
            if not target:
                yield event.plain_result(f"背包里没有叫『{item_name}』的装备！(已装备的也可以直接『符文拆卸 <装备名>』)")
                return
        d = target["data"]
        orig = d.get("enchant") or []
        # 符文 = enchant 里带 effect 的项（与属性附魔 stat 项区分）
        rune_pos = [(i, e) for i, e in enumerate(orig)
                    if e and isinstance(e, dict) and e.get("effect")]
        if not rune_pos:
            yield event.plain_result(f"【{d['name']}】没有刻印任何符文～(『附魔 <装备> <符文>』刻印)")
            return
        # 孔位：默认拆最后一个符文；显式 <n> 指定第 n 个符文效果（1 起）
        idx = 0
        if slot_arg:
            if not slot_arg.isdigit():
                yield event.plain_result(f"『{slot_arg}』不是有效孔位！输入『符文拆卸 <装备名> <孔位序号>』，如：符文拆卸 铁剑 1")
                return
            n = int(slot_arg)
            if n < 1 or n > len(rune_pos):
                yield event.plain_result(f"【{d['name']}】只有 {len(rune_pos)} 个符文(孔位 1~{len(rune_pos)})，没有第 {n} 个！")
                return
            idx = n - 1
        else:
            idx = len(rune_pos) - 1
        orig_pos, en = rune_pos[idx]
        eff = en.get("effect")
        lvl = int(en.get("lvl", 1) or 1)
        cost = _b143.RUNE_REMOVE_COST * lvl
        if player["gold"] < cost:
            yield event.plain_result(f"拆卸 Lv.{lvl} 符文需要 {cost} 金币(1000×等级)，你只有 {player['gold']}。")
            return
        # 回收符文碎片×等级（可堆叠，key=mat_fu_wen_sui_pian 已有定义）
        db.update_player(group_id, qq_id, gold=player["gold"] - cost)
        shard_name = C.display("materials", _cit.RUNE_SHARD_KEY)
        db.add_item(group_id, qq_id, _cit.RUNE_SHARD_KEY,
                    {"name": shard_name, "type": "材料", "stackable": True,
                     "price": _cit.MATERIALS.get(_cit.RUNE_SHARD_KEY, {}).get("price", 100)},
                    lvl)
        # 从 enchant 移除该符文（保留属性附魔 stat 项）
        d["enchant"] = [e for i, e in enumerate(orig) if i != orig_pos]
        if target.get("_equipped"):
            eq = dict(player.get("equipment") or {})
            eq[target["_equipped"]] = d
            db.update_player(group_id, qq_id, equipment=eq)
        else:
            db.update_item_data(group_id, qq_id, target["key"], d)
        eff_name = _cit.RUNE_EFFECT_NAMES.get(eff, eff)
        yield event.plain_result(
            f"🔧 符文拆卸成功！【{d['name']}】拆下了『{eff_name}』(Lv.{lvl})，"
            f"花费 {cost} 金币\n"
            f"🎒 回收 符文碎片×{lvl}（『附魔 <装备> <符文>』可重新刻印）")

    @declared("refine_equip")
    @require_player()

    async def refine_equip(self, event: AstrMessageEvent):
        """v172 装备重锻（怪猎派生树，原 v136 装备进化）：『装备重锻 <装备名>』——同系列旧武器→高阶武器。

        消耗稀有素材+金钱 → 新装备入包，继承旧装备强化/升级等级（inherit=half 折半向下取整）。
        旧装备被消耗（投资不沉没：强化/升级等级带到新装备）。
        """
        group_id, qq_id = self._uid(event)
        raw = self._strip_cmd(event, "装备重锻").strip()
        player = self._player(group_id, qq_id)
        if not self._at_smith(player):
            yield event.plain_result("需要到铁匠铺/锻造坊才能重锻装备！(先『地图』移动到铁匠铺)")
            return
        if not raw:
            # 无参：列出全部可重锻配方（含路B 重锻专属——REFINE_EXCLUSIVE_RECIPES 以名册 rid 为目标）
            _src_rows = []
            for _src, _cfg in _cit.REFINE_RECIPES.items():
                _tgt_rec = _clife.CRAFT_RECIPES.get(_cfg["target"]) or {}
                _tgt_nm = _tgt_rec.get("name") or C.display("recipes", _cfg["target"])
                _tgt_nm = _tgt_nm or _cit.EQUIP_ROSTER.get(_cfg["target"], {}).get("name", _cfg["target"])
                _src_rows.append((_src, _tgt_nm, _cfg.get("mats", {}), _cfg.get("gold", 0)))
            _ref_excl = getattr(C, "REFINE_EXCLUSIVE_RECIPES", None) or {}
            for _src, _cfg in _ref_excl.items():
                _rid = _cfg.get("target", "")
                _tgt_nm = _cit.EQUIP_ROSTER.get(_rid, {}).get("name", _rid)
                _src_rows.append((_src, _tgt_nm, _cfg.get("mats", {}), _cfg.get("gold", 0)))
            lines = ["🔀 【装备重锻】（怪猎派生树：旧→新，继承一半强化/升级）", ""]
            for _src, _tgt_nm, _mats, _gold in _src_rows:
                _mats_s = " + ".join(f"{C.display('materials', m)}×{n}" for m, n in _mats.items())
                lines.append(f"  {_src} → {_tgt_nm}｜{_mats_s} + {_gold}金")
            lines.append("")
            lines.append("💡 『装备重锻 <装备名>』重锻你的装备，继承一半强化/升级！")
            yield event.plain_result("\n".join(lines))
            return
        target, err = self._gem_find_equip(group_id, qq_id, player, raw)
        if not target:
            yield event.plain_result(err)
            return
        d = target["data"]
        src_name = d.get("name", "")
        # 名字可能带品质色前缀（如 🔵·弯刀），用 in 匹配配方 key
        rec = None
        for _src, _cfg in _cit.REFINE_RECIPES.items():
            if _src in src_name:
                rec = _cfg
                break
        if not rec:
            yield event.plain_result(f"【{src_name}】没有重锻配方！『装备重锻』看可重锻列表～")
            return
        # v172 路B：重锻专属（REFINE_EXCLUSIVE_RECIPES，target = 名册 rid，无锻造配方）——
        # 命中时走 generate_roster_equip(rid) 精确生成；目标等级门槛从名册条目取。
        _ref_excl = getattr(C, "REFINE_EXCLUSIVE_RECIPES", None) or {}
        _excl_src = None
        for _src_k, _cfg in _ref_excl.items():
            if _src_k in src_name:
                _excl_src = _src_k
                break
        _is_exclusive = _excl_src is not None
        tgt_rec = _clife.CRAFT_RECIPES.get(rec["target"]) if not _is_exclusive else None
        if not _is_exclusive and not tgt_rec:
            yield event.plain_result(f"【{src_name}】的重锻目标不存在(配置缺失)！")
            return
        # 校验等级门槛
        _tgt_lv = tgt_rec["lv"] if tgt_rec else _cit.EQUIP_ROSTER.get(rec["target"], {}).get("lv", 0)
        if _tgt_lv > player["level"] + 6:
            yield event.plain_result(f"重锻目标【{_cit.EQUIP_ROSTER.get(rec['target'], {}).get('name', tgt_rec['name'] if tgt_rec else rec['target'])}】是 Lv.{_tgt_lv}，你才 Lv.{player['level']}，等级再高些才能驾驭！")
            return
        # 校验材料
        lack = []
        for m, n in rec["mats"].items():
            have = db.count_item(group_id, qq_id, m)
            if have < n:
                lack.append(f"{C.display('materials', m)}×{n}(你有{have})")
        if lack:
            yield event.plain_result(f"重锻材料不足！还缺：{'、'.join(lack)}。Boss 掉落稀有素材～")
            return
        # 校验金币
        if player["gold"] < rec["gold"]:
            yield event.plain_result(f"金币不足！重锻需要 {rec['gold']} 金币，你只有 {player['gold']}。")
            return
        # 扣材料 + 扣金币 + 扣旧装备
        for m, n in rec["mats"].items():
            db.remove_item(group_id, qq_id, m, n)
        db.update_player(group_id, qq_id, gold=player["gold"] - rec["gold"])
        if target.get("_equipped"):
            eq = dict(player.get("equipment") or {})
            eq[target["_equipped"]] = None
            db.update_player(group_id, qq_id, equipment=eq)
        else:
            db.remove_item(group_id, qq_id, target["key"], 1)
        # 造新装备 + 继承强化/升级（half 折半向下取整）
        # v172 真等级化：升级投资 = 旧装备真实 lv 超出其名册基础 lv 的部分（升级层数）；
        # full=全额继承、half=折半向下取整。旧装备 lv 基础（本身含 base_lv）不重复折算——
        # 目标装备基础 lv 通常高于旧装备，直接用 lv 差会恒为 0/负（升级投资被吞），
        # 用「真实 lv - 名册 base_lv」才是玩家花的升级层数（旧 upgrade_lv 同口径）。
        if _is_exclusive:
            # 重锻专属：无锻造配方，走名册精确生成（generation 同款词条/套装/专属）
            new_equip = C.generate_roster_equip(rec["target"])
        else:
            new_equip = C.craft_recipe_make(rec["target"])
        _inh = rec.get("inherit", "half")
        # 旧装备名册基础 lv（按名反查名册；查不到兜底用当前 lv 当已含全部升级 → 不继承）
        _base_lv = d.get("lv", 0) or 0
        try:
            for _rid in _cit.EQUIP_ROSTER_BY_NAME.get(src_name, []):
                _base_lv = _cit.EQUIP_ROSTER[_rid].get("lv", _base_lv)
                break
        except Exception:
            pass
        _upg_boost = max(0, ((d.get("lv", 0) or 0) - _base_lv))
        if _inh == "full":
            new_equip["enhance"] = d.get("enhance", 0)
            new_equip["lv"] = new_equip.get("lv", 0) + _upg_boost
        else:  # half
            new_equip["enhance"] = (d.get("enhance", 0) or 0) // 2
            new_equip["lv"] = new_equip.get("lv", 0) + _upg_boost // 2
        # 原石/炼成不继承（新装备重新追求）
        import uuid
        key = f"eq_{uuid.uuid4().hex[:8]}"
        db.add_item(group_id, qq_id, key, new_equip)
        _eh = new_equip["enhance"]
        _lv_boost = _upg_boost // 2 if _inh != "full" else _upg_boost
        _inh_str = f"继承强化+{_eh}" if _eh else ""
        if _lv_boost > 0:
            _inh_str = (_inh_str + " / " if _inh_str else "") + f"升级继承 Lv.{_lv_boost}"
        _inh_str = _inh_str or "（新装备）"
        yield event.plain_result(
            f"🔀 【装备重锻成功】{src_name} 淬炼成 {_b143.QUALITY[new_equip['quality']]['color']}【{new_equip['name']}】！\n"
            f"🎯 {_inh_str}——旧装备的强化/升级投资不沉没！\n"
            f"💰 消耗 {rec['gold']} 金币 + 稀有素材")

    @declared("calamity_forge")
    @require_player()

    async def calamity_forge(self, event: AstrMessageEvent):
        """v136 怪异炼成（怪猎曙光怪异化）：『炼成 <装备名>』——稀有素材随机强化装备属性。

        每件限 3 次（calamity_count）；90% 正面 +3% / 10% 负面 -1%（取舍）。
        消耗：2000 金 + 余烬核心×1（CALAMITY_COST）。
        """
        group_id, qq_id = self._uid(event)
        raw = self._strip_cmd(event, "炼成").strip()
        player = self._player(group_id, qq_id)
        if not self._at_smith(player):
            yield event.plain_result("需要到铁匠铺/锻造坊才能怪异炼成！(先『地图』移动到铁匠铺)")
            return
        if not raw:
            yield event.plain_result("炼成哪件装备？输入『炼成 <装备名>』(如：炼成 铁剑)——每件限 3 次，随机强化属性(90%+3%/10%-1%)")
            return
        target, err = self._gem_find_equip(group_id, qq_id, player, raw)
        if not target:
            yield event.plain_result(err)
            return
        d = target["data"]
        cnt = d.get("calamity_count", 0) or 0
        if cnt >= _clife.CALAMITY_MAX:
            yield event.plain_result(f"【{d['name']}】已经炼成 {cnt}/{_clife.CALAMITY_MAX} 次，到极限了！换装备继续炼吧～")
            return
        # 校验材料/金币
        lack = []
        for m, n in _clife.CALAMITY_COST["mats"].items():
            have = db.count_item(group_id, qq_id, m)
            if have < n:
                lack.append(f"{C.display('materials', m)}×{n}(你有{have})")
        if lack:
            yield event.plain_result(f"炼成材料不足！还缺：{'、'.join(lack)}。Boss 掉落稀有素材～")
            return
        if player["gold"] < _clife.CALAMITY_COST["gold"]:
            yield event.plain_result(f"金币不足！怪异炼成需要 {_clife.CALAMITY_COST['gold']} 金币，你只有 {player['gold']}。")
            return
        # 扣材料/金币
        for m, n in _clife.CALAMITY_COST["mats"].items():
            db.remove_item(group_id, qq_id, m, n)
        db.update_player(group_id, qq_id, gold=player["gold"] - _clife.CALAMITY_COST["gold"])
        # 随机强化：90% 正面 +3% / 10% 负面 -1%
        import random as _rnd
        _stat = _rnd.choice(_clife.CALAMITY_STATS)
        _pos = _rnd.random() < _clife.CALAMITY_POSITIVE_CHANCE
        _val = _clife.CALAMITY_BONUS if _pos else -_clife.CALAMITY_MALUS
        cb = dict(d.get("calamity_bonus") or {})
        cb[_stat] = round(cb.get(_stat, 0) + _val, 4)
        d["calamity_bonus"] = cb
        d["calamity_count"] = cnt + 1
        _stat_cn = STAT_NAMES.get(_stat, _stat) if STAT_NAMES else _stat
        if target.get("_equipped"):
            eq = dict(player.get("equipment") or {})
            eq[target["_equipped"]] = d
            db.update_player(group_id, qq_id, equipment=eq)
        else:
            db.update_item_data(group_id, qq_id, target["key"], d)
        _arrow = "✨ 炼成成功！" if _pos else "🌪️ 炼成波动……"
        _sgn = "+" if _val > 0 else ""
        yield event.plain_result(
            f"{_arrow}【{d['name']}】{_stat_cn}{_sgn}{int(_val * 100)}%！"
            f"({d.get('calamity_count', 1)}/{_clife.CALAMITY_MAX} 次)\n"
            f"💰 消耗 {_clife.CALAMITY_COST['gold']} 金币 + 稀有素材")

    @declared("enchant")
    @require_player()

    async def enchant(self, event: AstrMessageEvent):
        group_id, qq_id = self._uid(event)
        raw = self._strip_cmd(event, "附魔")
        player = self._player(group_id, qq_id)
        if not self._at_smith(player):
            yield event.plain_result("需要到铁匠铺/锻造坊才能附魔装备！(先『地图』移动到铁匠铺)")
            return
        parts = raw.strip().split()
        if not parts:
            # v104R3 M11 P3-2：符文名带品质前缀，与背包掉落名（rune_item 构造）一致，
            # 例『史诗符文·残忍』（用户输入名或子串均能匹配）
            _rune_list = "、".join(
                f"{_b143.QUALITY[r.get('quality', 'white')]['name']}符文·{r.get('name', k)}"
                for k, r in _cit.RUNES.items()
            )
            yield event.plain_result(
                "附魔哪件装备？输入『附魔 <装备名> <属性/符文>』\n"
                f"属性附魔：{'、'.join(r['label'] for r in _b143.ENCHANT_RECIPES.values())}\n"
                f"符文(MC 式，独特效果+等级)：{_rune_list}\n"
                "例：『附魔 烈焰之刃 攻击』『附魔 烈焰之刃 史诗符文·残忍 II』\n"
                + self._tip("enchant")
            )
            return
        item_name = parts[0]
        stat_label = parts[1] if len(parts) > 1 else ""
        # v94 体力：附魔消耗 10 体力（v105 P1：扣体力移到所有校验通过、最终消耗前——
        # 原实现在命令开头先扣，未拜师/Lv.1/属性名无效/无装备/槽满/符文冲突/材料不足等失败路径白扣 10 体力）
        # v67 附魔归位炼金 → 导师进修后附魔为独立副业（19 章第八章）：附魔需要附魔副业 Lv.2
        ok, act_msg = self._prof_active_check(group_id, qq_id, "enchant", require_apprentice=True)
        if not ok:
            yield event.plain_result(act_msg)
            return
        prof_lv = db.get_prof_level(group_id, qq_id, "enchant")
        if prof_lv < 2:
            yield event.plain_result(
                f"附魔需要附魔副业 Lv.2(你 Lv.{prof_lv})！多附魔升级吧～"
            )
            return
        # v130.7 意见#30：『附魔 <序号> <属性/符文>』——装备名支持序号（取数列表与『背包』面板同源 db.get_inventory 全局序号）
        if item_name.isdigit():
            _items = db.get_inventory(group_id, qq_id)
            idx = int(item_name)
            if idx < 1 or idx > len(_items):
                yield event.plain_result(f"背包里没有第 {idx} 件物品(共 {len(_items)} 件)！『背包』查看～")
                return
            if not _items[idx - 1]["data"].get("slot"):
                yield event.plain_result(f"背包第 {idx} 件『{_items[idx-1]['data']['name']}』不是装备，不能附魔！『背包』查看～")
                return
            item_name = _items[idx - 1]["data"]["name"]
        # ---- v34 符文路径：第二参数含"符文"则走符文附魔 ----
        if "符文" in stat_label:
            items = db.get_inventory(group_id, qq_id)
            rune = None
            for it in items:
                dd = it["data"]
                if dd.get("type") == "符文" and stat_label in dd.get("name", ""):
                    rune = it
                    break
            if not rune:
                yield event.plain_result(f"背包里没有『{stat_label}』！打怪有概率掉落符文～")
                return
            rd = rune["data"]
            target = None
            for it in items:
                d = it["data"]
                if d.get("slot") and item_name in d["name"]:
                    target = it
                    break
            if not target:
                # v105 M11 P2：与强化(v101.25 #329)对齐——补查已装备槽位，支持就地刻印
                eq = player.get("equipment") or {}
                for slot, ed in eq.items():
                    if item_name in (ed.get("name", "") if isinstance(ed, dict) else ""):
                        target = {"key": f"eq_equipped_{slot}", "data": ed, "_equipped": slot}
                        break
            if not target:
                yield event.plain_result(f"背包里没有叫『{item_name}』的装备！(已装备的也可以直接『附魔 <装备名> <属性/符文>』)")
                return
            d = target["data"]
            slots = _b143.ENCHANT_SLOTS.get(d.get("quality", ""), 0)
            # v101.30/30b 附魔槽：Lv.7 史诗工艺（紫装 3 槽）/ Lv.8 传说工艺（橙装 3 槽）
            # v125.2 B3：槽位等级门数据下沉 prof_config.ENCHANT_SLOT_UNLOCK（原双处拷贝收敛单点读表）
            if prof_lv >= _clife.ENCHANT_SLOT_UNLOCK.get(d.get("quality", ""), 99):
                slots += 1
            if slots <= 0:
                yield event.plain_result(f"【{d['name']}】({_b143.QUALITY[d['quality']]['name']})没有附魔槽，只有蓝/紫/橙装备可以附魔！")
                return
            enchanted = d.get("enchant", [])
            if len(enchanted) >= slots:
                yield event.plain_result(f"【{d['name']}】的 {slots} 个附魔槽已满！先『卸下』旧装备换新的吧～")
                return
            # v34 冲突检查：新符文与已有效果冲突则拒绝
            conflict_hit = None
            for en in enchanted:
                if en.get("effect") and C.rune_conflict(rd["effect"], en["effect"]):
                    conflict_hit = _cit.RUNE_EFFECT_NAMES.get(en["effect"], en["effect"])
                    break
            if conflict_hit:
                yield event.plain_result(f"符文冲突！『{rd['name']}』与『{conflict_hit}』效果相斥，不能共存于同一件装备～")
                return
            if rd.get("effect") in [e.get("effect") for e in enchanted]:
                yield event.plain_result(f"【{d['name']}】已经有『{rd['name']}』的效果了！")
                return
            # v101.28i 符文等级解锁：附魔 Lv.2 刻 lvl.1、Lv.4 刻 lvl.2、Lv.6 刻 lvl.3（附魔等级不再是摆设）
            # v125.2 B3：符文等级门数据下沉 prof_config.RUNE_LEVEL_GATE（原 {1:2, 2:4, 3:6} 硬编码）
            _rune_lv = rd.get("lvl", 1)
            _need_lv = _clife.RUNE_LEVEL_GATE.get(_rune_lv, 2)
            if prof_lv < _need_lv:
                yield event.plain_result(
                    f"『{rd['name']}』是 {_rune_lv} 级符文，需要附魔副业 Lv.{_need_lv}(你 Lv.{prof_lv})！多附魔练练手艺吧～"
                )
                return
            # v94 体力：附魔消耗 10 体力（v105 P1：移到此处——符文/装备/槽位/冲突/等级校验全过后才扣，防白扣）
            _ok, _st = self._spend_stamina(group_id, qq_id, _clife.PROF_STAMINA_COST["enchant"], player, "附魔")
            if not _ok:
                yield event.plain_result(_st)
                return
            # 消耗符文（无需金币，符文本身就是价值）
            db.remove_item(group_id, qq_id, rune["key"], 1)
            enchanted.append({"effect": rd["effect"], "lvl": rd.get("lvl", 1)})
            d["enchant"] = enchanted
            if target.get("_equipped"):
                # v105 M11 P2：已装备装备刻印成功 → 写回装备槽位（属性实时生效）
                eq = dict(player.get("equipment") or {})
                eq[target["_equipped"]] = d
                db.update_player(group_id, qq_id, equipment=eq)
            else:
                # F1 P0-1：背包格原子写回（替代 remove+add 两步非原子替换）
                db.update_item_data(group_id, qq_id, target["key"], d)
            # v105 M11 P2：符文刻印补次数统计 + 成就判定（与属性附魔路径一致——
            # 此前 enchant_count 无符文路径消费端，『附魔师』等次数成就永远不可解锁）
            db.bump_stats(group_id, qq_id, enchant_count=1)
            C.check_achievements(group_id, qq_id, player)
            # v101.28i 附魔经验：成功 +1（符文刻印与属性附魔同）
            _lv_msg = ""
            new_lv, leveled = db.add_prof_exp(group_id, qq_id, "enchant", 1)
            if leveled:
                _lv_msg = f"\n🌟 附魔副业提升到 Lv.{new_lv}！"
            _done, _msg = self._daily_prof_bump(group_id, qq_id, "enchant")
            if _msg:
                _lv_msg += "\n" + _msg.strip()
            yield event.plain_result(
                f"💎 符文刻印成功！【{d['name']}】获得『{rd['name']}』({rd['desc']})\n"
                f"(已用 {len(enchanted)}/{slots} 槽){_lv_msg}"
            )
            return
        # ---- 原属性附魔路径（v10） ----
        # 属性标签 → stat 键
        stat_key = None
        for k, r in _b143.ENCHANT_RECIPES.items():
            if r["label"] == stat_label:
                stat_key = k
                break
        if not stat_key:
            yield event.plain_result(f"没有『{stat_label}』这个附魔属性！可用：{'、'.join(r['label'] for r in _b143.ENCHANT_RECIPES.values())}")
            return
        items = db.get_inventory(group_id, qq_id)
        target = None
        for it in items:
            d = it["data"]
            if d.get("slot") and item_name in d["name"]:
                target = it
                break
        if not target:
            # v105 M11 P2：与强化(v101.25 #329)对齐——补查已装备槽位，支持就地附魔
            eq = player.get("equipment") or {}
            for slot, ed in eq.items():
                if item_name in (ed.get("name", "") if isinstance(ed, dict) else ""):
                    target = {"key": f"eq_equipped_{slot}", "data": ed, "_equipped": slot}
                    break
        if not target:
            yield event.plain_result(f"背包里没有叫『{item_name}』的装备！(已装备的也可以直接『附魔 <装备名> <属性/符文>』)")
            return
        d = target["data"]
        slots = _b143.ENCHANT_SLOTS.get(d.get("quality", ""), 0)
        # v101.30/30b 附魔槽：Lv.7 史诗工艺（紫装 3 槽）/ Lv.8 传说工艺（橙装 3 槽）
        # v125.2 B3：槽位等级门数据下沉 prof_config.ENCHANT_SLOT_UNLOCK（原双处拷贝收敛单点读表）
        if prof_lv >= _clife.ENCHANT_SLOT_UNLOCK.get(d.get("quality", ""), 99):
            slots += 1
        if slots <= 0:
            yield event.plain_result(f"【{d['name']}】({_b143.QUALITY[d['quality']]['name']})没有附魔槽，只有蓝/紫/橙装备可以附魔！")
            return
        enchanted = d.get("enchant", [])
        if len(enchanted) >= slots:
            yield event.plain_result(f"【{d['name']}】的 {slots} 个附魔槽已满！先『出售』旧装备，或等新装备吧～")
            return
        rec = _b143.ENCHANT_RECIPES[stat_key]
        # v105 M11 P1：同属性附魔去重——符文路径有去重(2041-2043)而属性路径没有，
        # 同武器『附魔 攻击』×3 可叠白板攻击 ×54%（atk ratio 0.18×3），实现不一致且明显失衡
        if stat_key in [e.get("stat") for e in enchanted]:
            yield event.plain_result(
                f"【{d['name']}】已经附魔过『{rec['label']}』了，同一属性不能重复附魔！(换新装备再附魔吧)"
            )
            return
        mat_name = C.enchant_match_material(stat_key, items)
        if not mat_name:
            yield event.plain_result(
                f"背包里没有{rec['label']}系材料(需要含有：{'/'.join(rec['mats'])}的材料)！打怪掉落材料～"
            )
            return
        if player["gold"] < rec["cost"]:
            yield event.plain_result(f"附魔需要 {rec['cost']} 金币，你只有 {player['gold']}。")
            return
        # v94 体力：附魔消耗 10 体力（v105 P1：移到此处——属性名/装备/槽位/材料/金币校验全过后才扣，防白扣）
        _ok, _st = self._spend_stamina(group_id, qq_id, _clife.PROF_STAMINA_COST["enchant"], player, "附魔")
        if not _ok:
            yield event.plain_result(_st)
            return
        # 消耗材料 + 金币
        # v105R3 M13 P2-6：对齐烹饪/锻造 remain 模式——remove 失败（旧档混合 key 行
        # 归一化后查不到）继续找下一同名堆，不再"只删第一匹配堆"后静默漏扣/白嫖材料
        for it in items:
            dd = it["data"]
            if dd.get("name") != mat_name:
                continue
            if db.remove_item(group_id, qq_id, it["key"], 1):
                break
        db.update_player(group_id, qq_id, gold=player["gold"] - rec["cost"])
        # 附魔：5% 大成功 1.5x（v101.30 Lv.10 大师手艺 → 10%）
        _crit = 0.10 if prof_lv >= 10 else _b143.ENCHANT_CRIT_CHANCE
        big = random.random() < _crit
        v = C.enchant_value(d["slot"], d["lv"], stat_key, big=big)
        enchanted.append({"stat": stat_key, "value": v})
        d["enchant"] = enchanted
        if target.get("_equipped"):
            # v105 M11 P2：已装备装备附魔成功 → 写回装备槽位（属性实时生效）
            eq = dict(player.get("equipment") or {})
            eq[target["_equipped"]] = d
            db.update_player(group_id, qq_id, equipment=eq)
        else:
            # F1 P0-1：背包格原子写回（替代 remove+add 两步非原子替换）
            db.update_item_data(group_id, qq_id, target["key"], d)
        sn = {"atk": "攻击", "matk": "魔攻", "def": "防御", "mdef": "魔防", "hp": "生命", "spd": "速度", "crit": "暴击"}
        val_str = f"+{int(v * 100)}%" if stat_key in _ccore.PCT_STATS else f"+{v}"
        big_str = "🌟 大成功！" if big else ""
        # 阶段九：附魔次数 + 成就判定
        db.bump_stats(group_id, qq_id, enchant_count=1)
        C.check_achievements(group_id, qq_id, player)
        # v101.28i 附魔经验：成功 +1
        _lv_msg = ""
        new_lv, leveled = db.add_prof_exp(group_id, qq_id, "enchant", 1)
        if leveled:
            _lv_msg = f"\n🌟 附魔副业提升到 Lv.{new_lv}！"
        _done, _msg = self._daily_prof_bump(group_id, qq_id, "enchant")
        if _msg:
            _lv_msg += "\n" + _msg.strip()
        yield event.plain_result(
            f"🔮 附魔成功！【{d['name']}】获得 {sn.get(stat_key, stat_key)} {val_str}{big_str}\n"
            f"(消耗 {mat_name} x1 + {rec['cost']} 金币；已用 {len(enchanted)}/{slots} 槽){_lv_msg}"
        )

    @declared("set_view")
    @require_player()

    async def set_view(self, event: AstrMessageEvent):
        group_id, qq_id = self._uid(event)
        player = self._player(group_id, qq_id)
        equipment = player.get("equipment") or {}
        counts = {}
        for slot, item in equipment.items():
            if item and item.get("set"):
                counts[item["set"]] = counts.get(item["set"], 0) + 1
        if not counts:
            yield event.plain_result("你还没有穿戴任何套装部件！名册装备/商店/锻造获得的装备自带系列套装(同系列 = 同套装)，穿 2 件起生效～")
            return
        lines = ["🎴 【套装状态】", "━━━━━━━━━━━━"]
        any_active = False
        for sname, cnt in counts.items():
            info = _set_info(sname)
            if not info:
                continue
            b2_raw = info.get("bonus_2", {}) or {}
            if isinstance(b2_raw, dict) and b2_raw.get("effect"):
                # v130.2e 修复（审计 P0）：effect 型 bonus_2（资源套装）取 desc 展示，不再逐键 int(v*100) 崩溃
                b2 = b2_raw.get("desc", "") or ""
            else:
                b2 = "  ".join(
                    f"{sn} +{int(v * 100)}%"
                    for k, v in b2_raw.items()
                    if isinstance(v, (int, float)) and not isinstance(v, bool)
                    for sn in [{"atk": "攻击", "def": "防御", "matk": "魔攻", "mdef": "魔防", "hp": "生命", "spd": "速度", "crit": "暴击", "dodge": "闪避", "heal": "治疗"}.get(k, k)]
                )
            # 阶段八：4 件效果 = 属性加成（bonus_4_stats）或特效（bonus_4.effect）
            b4_parts = []
            for k, v in info.get("bonus_4_stats", {}).items():
                sn = {"atk": "攻击", "def": "防御", "matk": "魔攻", "mdef": "魔防", "hp": "生命", "spd": "速度", "crit": "暴击", "dodge": "闪避"}.get(k, k)
                b4_parts.append(f"{sn} +{int(v * 100)}%")
            b4_desc = info.get("bonus_4", {}).get("desc", "")
            if b4_desc:
                b4_parts.append(b4_desc)
            b4 = "  ".join(b4_parts) or "(待解锁)"
            # 阶段八：5 件效果（数据先行）
            b5 = info.get("bonus_5", {}).get("desc", "")
            active_2 = cnt >= 2
            active_4 = cnt >= 4
            active_5 = cnt >= 5
            if active_2 or active_4 or active_5:
                any_active = True
            lines.append(
                f"{info['icon']}{sname}({min(cnt, 5)}/5 件)"
                + (" ✅" if active_2 else "")
                + (" ⭐" if active_4 else "")
                + (" 👑" if active_5 else "")
            )
            lines.append(f"  2件：{b2}" + ("(已激活)" if active_2 else ""))
            lines.append(f"  4件：{b4}" + ("(已激活)" if active_4 else ""))
            if b5:
                lines.append(f"  5件：{b5}" + ("(已激活)" if active_5 else ""))
        if not any_active:
            lines.append("穿满 2 件同套装即激活 2 件效果，4 件激活 4 件效果！继续收集吧～")
        lines.append("━━━━━━━━━━━━")
        lines.append("💡 套装部件：名册装备/商店/锻造获得的装备自带系列套装(如『橡木』『圣光』『银铃』)，穿 2 件起生效")
        yield event.plain_result("\n".join(lines))

    @declared("monster")
    @require_player()

    async def monster(self, event: AstrMessageEvent):
        """v130.3 意见#3：『怪物 <名称>』查刷新点（等级/子区域/类型；比百科更细）"""
        group_id, qq_id = self._uid(event)
        raw = self._strip_cmd(event, "怪物").strip()
        if not raw:
            yield event.plain_result(
                "👹 想找怪物？发『怪物 <名称>』查刷新地点（例：『怪物 森林狼』『怪物 狼王·灰影』）。\n"
                "💡 也可以用『百科 <名称>』查材料掉落/地图怪物~"
            )
            return
        locs = _cspace.MONSTER_LOCS.get(raw)
        if not locs:
            fuzzy = [k for k in _cspace.MONSTER_LOCS if raw in k][:5]
            if fuzzy:
                yield event.plain_result(
                    f"👹 没有叫『{raw}』的怪物，你是不是想找：{' / '.join(fuzzy)}？\n发『怪物 <完整名字>』即可~"
                )
            else:
                yield event.plain_result(f"👹 未收录『{raw}』……试试『百科 {raw}』或先『图鉴』看看怪物列表？")
            return
        lines = [f"👹 【{raw}】出现地点（共 {len(locs)} 处）：", "━━━━━━━━━━━━"]
        for sa_name, mname, lv, mtype in locs:
            lines.append(f"  {mtype}·Lv.{lv} {sa_name}（{mname}）")
        lines.append("💡 前往对应地图后按区域探索/战斗即有机会遭遇；首领/精英带稀有掉落~")
        yield event.plain_result("\n".join(lines))

    @declared("adventure_book")
    @require_player()

    async def adventure_book(self, event: AstrMessageEvent):
        """v168 冒险手册：冒险者自己的传记总入口。
        『冒险手册』总览 / 『冒险手册 区域』(足迹) / 『冒险手册 怪物』 /
        『冒险手册 物品』(曾拥有) / 『冒险手册 收藏』 / 『冒险手册 垂钓』。
        """
        group_id, qq_id = self._uid(event)
        raw = self._strip_cmd(event, "冒险手册").strip()
        # 子分类路由
        if raw:
            if any(k in raw for k in ("区域", "足迹", "地图")):
                yield event.plain_result(self._footprint_view(group_id, qq_id))
                return
            if any(k in raw for k in ("怪物", "魔物", "全部")):
                yield event.plain_result(self._monster_view(group_id, qq_id, ""))
                return
            if any(k in raw for k in ("物品", "曾拥有", "拥有")):
                yield event.plain_result(self._possessed_view(group_id, qq_id, raw))
                return
            if any(k in raw for k in ("收藏", "收藏品", "纪念")):
                yield event.plain_result(self._collect_items_bestiary(group_id, qq_id))
                return
            if any(k in raw for k in ("宠物", "伙伴")):
                yield event.plain_result(self._pet_dex_view(group_id, qq_id))
                return
            if any(k in raw for k in ("垂钓", "钓鱼", "鱼")):
                yield event.plain_result(self._collect_fish_bestiary(group_id, qq_id))
                return
            yield event.plain_result(
                "📖 『冒险手册』子分类：区域/怪物/物品/收藏/垂钓（例：『冒险手册 物品』『足迹』）。\n"
                "💡 也可以直接发『足迹』看区域足迹、『图鉴』看怪物。"
            )
            return
        # 总览
        yield event.plain_result(self._adventure_overview(group_id, qq_id))

    @declared("footprint")
    @require_player()

    async def footprint(self, event: AstrMessageEvent):
        """v168 『足迹』：我去过的城镇/子区域明细（冒险手册 区域 同款）。"""
        group_id, qq_id = self._uid(event)
        yield event.plain_result(self._footprint_view(group_id, qq_id))

    # ---------------- v168 冒险手册内部 ----------------

    def _adventure_overview(self, group_id, qq_id) -> str:
        """冒险手册总览卡片：足迹/怪物/物品/收藏 四维进度。"""
        try:
            # 足迹（剔副本，与足迹面板同口径）
            vis = tot = 0
            try:
                _visited = db.get_visited_subareas(qq_id)
                for _m in _cspace.MAPS:
                    if _m.get("type") in ("副本", "隐藏区域"):
                        continue
                    for _sa in ((_cspace.SUBAREAS or {}).get(_m["id"]) or []):
                        tot += 1
                        if f"{_m['id']}:{_sa['id']}" in _visited:
                            vis += 1
            except Exception:
                pass
            best = db.get_bestiary(group_id, qq_id)
            best_total = len(getattr(C, "_INDEXES", {}).get("monsters", {}).get("name_to_id", {}) or {})
            poss = db.count_possessed(qq_id)
            inv_keys = set()
            for it in db.get_inventory(group_id, qq_id):
                _pk = self._norm_item_key(it["key"], it.get("data") or {})
                if _pk:
                    inv_keys.add(_pk)
            # 收藏品/彩蛋鱼计数复用 helper 逻辑（轻量：数已收集）
            fish_n = 0
            try:
                _inv0 = {it["key"]: it["count"] for it in db.get_inventory(group_id, qq_id)}
                _ach = {r["ach_key"] for r in db.get_achievements(group_id, qq_id)}
                _fish_ach = {(_a.get("cond") or {}).get("key"): _a["id"] for _a in _cquest.ACHIEVEMENTS
                             if (_a.get("cond") or {}).get("type") == "collect_fish"}
                fish_n = len([cf for cf in _b143.FISH_COLLECT
                              if cf["id"] in _inv0 or _fish_ach.get(cf["id"]) in _ach])
            except Exception:
                pass
            # 收藏品 defs（type=收藏 非鱼，去重；与 _collect_items_bestiary 同源）
            _defs = 0
            try:
                _fish_names = {cf["name"] for cf in _b143.FISH_COLLECT}
                _def_names = set()
                for _k, _v in (_cit.MATERIALS or {}).items():
                    if isinstance(_v, dict) and _v.get("type") == "收藏" \
                            and _v.get("name") not in _fish_names:
                        _def_names.add(_v.get("name", _k))
                for _k, _v in (_cit.ITEMS or {}).items():
                    if isinstance(_v, dict) and _v.get("type") == "收藏" \
                            and _v.get("name") not in _fish_names:
                        _def_names.add(_v.get("name", _k))
                _defs = len(_def_names)
            except Exception:
                pass
            _kill = sum(r["kills"] for r in best)
            # v173.3 意见#125：宠物维度（pet_dex 孵化记录）
            _pet_dex = db.pet_dex_get(qq_id)
            _pet_total = len(_clife.PET_POOL)
            lines = [
                "📖 【冒险手册】",
                "━━━━━━━━━━━━",
                f"📍 足迹 {vis}/{tot} 子区域",
                f"👹 怪物 {len(best)}/{best_total} 种 · 累计击杀 {_kill}",
                f"🎒 物品 {poss} 种曾拥有 · 当前持有 {len(inv_keys)} 种",
                f"🎣 收藏 鱼 {fish_n}/{len(_b143.FISH_COLLECT)} ｜ 收藏品 {0}/{_defs}",
                f"🐾 宠物 {len(_pet_dex)}/{_pet_total} 种（孵过）",
                "━━━━━━━━━━━━",
                "💡 『足迹』区域 ｜ 『冒险手册 怪物/物品/收藏/垂钓/宠物』看明细",
            ]
            return "\n".join(lines)
        except Exception as e:
            return f"📖 冒险手册加载失败（{e}），请联系管理～"

    def _footprint_view(self, group_id, qq_id) -> str:
        """足迹：按大区分组展示到访明细（紧凑版——只展开有到访的大区，避免刷屏）。
        已到访地图 ✅全清/🟡部分/❌未去；有到访的地图下列出已到访子区域（含首访日期）。
        副本/隐藏区域不参与足迹（副本不记 visited_subareas）。"""
        try:
            visited = db.get_visited_subareas(qq_id)
            # 子区域首访时间 {map:sa: ts}
            _first = {}
            try:
                for r in db.get_visited_subareas_rows(qq_id):
                    _first[f"{r['map_id']}:{r['sa_id']}"] = r["first_at"]
            except Exception:
                pass
            # 只统计城镇/野外（副本/隐藏不进足迹）
            by_reg = {}
            order = []
            for _m in _cspace.MAPS:
                if _m.get("type") in ("副本", "隐藏区域"):
                    continue
                reg = _m.get("region") or "?"
                if reg not in by_reg:
                    by_reg[reg] = []
                    order.append(reg)
                by_reg[reg].append(_m)
            lines = ["📍 【我的足迹】", "━━━━━━━━━━━━"]
            any_visit = False
            ov_vis = 0
            ov_tot = 0
            # 先算全量剔副本总数（分母固定，不因折叠变化）
            for reg0 in order:
                for _m0 in by_reg[reg0]:
                    ov_tot += len((_cspace.SUBAREAS or {}).get(_m0["id"]) or [])
            for reg in order:
                maps = by_reg[reg]
                reg_vis = reg_tot = 0
                rows = []
                for _m in maps:
                    sas = (_cspace.SUBAREAS or {}).get(_m["id"]) or []
                    if not sas:
                        continue
                    mv = 0
                    vis_sas = []
                    for sa in sas:
                        k = f"{_m['id']}:{sa['id']}"
                        if k in visited:
                            mv += 1
                            vis_sas.append((sa.get("name") or sa["id"], _first.get(k) or 0))
                    reg_tot += len(sas)
                    reg_vis += mv
                    if mv == len(sas):
                        rows.append(("✅", _m["name"], vis_sas))
                    elif mv > 0:
                        rows.append(("🟡", _m["name"], vis_sas))
                    # mv==0 未去地图不逐行列（避免 ❌ 刷屏）
                if reg_vis == 0:
                    continue  # 整大区没去过 → 折叠不展示
                any_visit = True
                ov_vis += reg_vis
                pct = int(round(reg_vis * 100.0 / reg_tot)) if reg_tot else 0
                lines.append(f"◈ {reg}（{reg_vis}/{reg_tot} · {pct}%）")
                for mark, nm, vis_sas in rows:
                    _subs = []
                    for _sn, _ts in vis_sas[:6]:
                        _d = ""
                        if _ts:
                            try:
                                _d = time.strftime("%m-%d", time.localtime(int(_ts)))
                            except Exception:
                                _d = ""
                        _subs.append(f"{_sn}" + (f"({_d})" if _d else ""))
                    more = f" 等{len(vis_sas)}处" if len(vis_sas) > 6 else ""
                    lines.append(f"  {mark} {nm}" + (f"：{'、'.join(_subs[:6])}{more}" if vis_sas else ""))
            if not any_visit:
                return "📍 还没去过任何地方……快去『探索』冒险吧！"
            lines.append("━━━━━━━━━━━━")
            lines.append(f"探索足迹 {ov_vis}/{ov_tot}（城镇与野外）")
            lines.append("💡 ✅=全到访 🟡=部分 ❌=未去 ｜ （MM-DD）=首访日期 ｜ 『探索』补全足迹")
            return "\n".join(lines)
        except Exception as e:
            return f"📍 足迹加载失败（{e}）～"

    def _monster_view(self, group_id, qq_id, raw) -> str:
        """怪物视图（沿用原『图鉴』怪物列表，含分页）。"""
        page = self._parse_page(raw)
        rows = db.get_bestiary(group_id, qq_id)
        if not rows:
            return "📖 图鉴还是空的……去『探索』击败怪物，或『垂钓』邂逅彩蛋收藏鱼吧！" \
                   + self._collect_fish_bestiary(group_id, qq_id)
        total = sum(r["kills"] for r in rows)
        page_items, pages, page = self._page_items(rows, page, per_page=5)
        lines = [f"📖 【怪物图鉴】已收录 {len(rows)} 种 · 累计击杀 {total}(第 {page}/{pages} 页)", "━━━━━━━━━━━━"]
        for i, r in enumerate(page_items, (page - 1) * 5 + 1):
            lines.append(f"{i:>2}. {r['name']} ×{r['kills']}")
        lines.append("")
        if pages > 1 and page < pages:
            lines.append(self._tip("bestiary"))
        lines.append("💡 击败新怪物自动收录 ｜ 『冒险手册 物品/收藏』看收集")
        self._record_list_state(qq_id, "冒险手册 怪物", page, pages)
        return "\n".join(lines)

    def _possessed_view(self, group_id, qq_id, raw) -> str:
        """『冒险手册 物品』：曾拥有物品图鉴（✅=拥有过 ×N=现持有；❌=未获得）。
        按物品大类分组，已拥有排前；支持分页与『冒险手册 物品 <大类>』过滤。"""
        try:
            poss = db.get_possessed(qq_id)
            inv = db.get_inventory(group_id, qq_id)
            # 当前持有 key→count（含背包内装备实例 uuid → 归一化原型）
            inv_cnt = {}
            for it in inv:
                k = it["key"]
                _pk = self._norm_item_key(k, it.get("data") or {})
                if _pk:
                    inv_cnt[_pk] = inv_cnt.get(_pk, 0) + int(it["count"] or 1)
            # 组装物品定义：材料 + 物品 + 装备原型
            # 结构 {大类: [(display名, key, 是否曾拥有, 当前持有), ...]}
            cat_items = {}
            try:
                for _k, _v in (_cit.MATERIALS or {}).items():
                    _nm = _v.get("name") or _k
                    _cat = self._item_cat(_v)
                    if _cat is None:
                        continue
                    cat_items.setdefault(_cat, []).append(
                        (_nm, _k, _k in poss, inv_cnt.get(_k, 0)))
                for _k, _v in (_cit.ITEMS or {}).items():
                    if _k in (_cit.MATERIALS or {}):
                        continue
                    if not isinstance(_v, dict):
                        continue
                    _nm = _v.get("name") or _k
                    _cat = self._item_cat(_v)
                    if _cat is None:
                        continue
                    cat_items.setdefault(_cat, []).append(
                        (_nm, _k, _k in poss, inv_cnt.get(_k, 0)))
                for _k, _v in (getattr(C, "EQUIP_ROSTER", None) or {}).items():
                    _nm = _v.get("name") or _k
                    _cat = self._item_cat(_v)  # 装备 v 带 slot → 归装备
                    cat_items.setdefault(_cat, []).append(
                        (_nm, _k, _k in poss, inv_cnt.get(_k, 0)))
            except Exception:
                pass
            if not cat_items:
                return "🎒 物品图鉴加载失败或暂无数据～"
            # 大类过滤
            cat_filter = None
            if raw:
                for _cand in raw.replace("物品", "").replace("冒险手册", "").strip().split():
                    for _cat in cat_items:
                        if _cand in _cat or _cat in _cand:
                            cat_filter = _cat
                            break
                    if cat_filter:
                        break
            if cat_filter:
                cat_items = {cat_filter: cat_items[cat_filter]}
            # 大类顺序：玩家最关心的收集维度在前（装备/收藏品/消耗品/图纸…），材质次之
            order = ["装备", "收藏品", "消耗品", "图纸", "鱼", "矿石", "草药", "木材",
                     "兽材", "织物", "食材", "精华", "宝石", "杂物", "任务道具", "其他"]
            cats_sorted = sorted(cat_items.keys(),
                                 key=lambda c: (order.index(c) if c in order else 99, c))
            # 默认只展示已拥有 ≥1 的大类（紧凑）；未收集大类折叠提示，可『冒险手册 物品 <大类>』直达
            if not cat_filter:
                owned_cats = [c for c in cats_sorted
                              if any(it[2] for it in cat_items[c])]
                hidden_cats = [c for c in cats_sorted if c not in owned_cats]
            else:
                owned_cats = cats_sorted
                hidden_cats = []
            cats_sorted = owned_cats
            total_poss = len(poss)
            total_all = sum(len(v) for v in cat_items.values())
            # 大类内条目截断（超长类如装备 632 种只显示前 20，避免刷屏）
            _MAX_PER_CAT = 20
            # 分页：每页展示 1-2 个大类（保证可读性）
            page = self._parse_page(raw)
            per_page_cats = 2
            total_pages = max(1, (len(cats_sorted) + per_page_cats - 1) // per_page_cats)
            if page < 1:
                page = 1
            if page > total_pages:
                page = total_pages
            cat_page = cats_sorted[(page - 1) * per_page_cats:page * per_page_cats]
            lines = [
                f"🎒 【曾拥有物品】已拥有 {total_poss} · 全量 {total_all}（第 {page}/{total_pages} 页）",
                "━━━━━━━━━━━━",
            ]
            for cat in cat_page:
                items = cat_items[cat]
                owned_n = sum(1 for it in items if it[2])
                # 已拥有在前
                items_sorted = sorted(items, key=lambda it: (0 if it[2] else 1, it[0]))
                lines.append(f"{cat}（已拥有 {owned_n}/{len(items)}）")
                shown = items_sorted[:_MAX_PER_CAT]
                # 每行 4 个
                row_parts = []
                for nm, k, owned, cnt in shown:
                    if owned:
                        row_parts.append(f"✅{nm}" + (f"×{cnt}" if cnt > 1 else ""))
                    else:
                        row_parts.append(f"❌{nm}")
                for i in range(0, len(row_parts), 4):
                    lines.append("  " + "　".join(row_parts[i:i + 4]))
                if len(items_sorted) > _MAX_PER_CAT:
                    lines.append(f"  …还有 {len(items_sorted) - _MAX_PER_CAT} 种：『冒险手册 物品 {cat}』看更多")
            if hidden_cats:
                lines.append(f"🗂 未收集大类：{'、'.join(hidden_cats[:6])}" +
                             (" 等" if len(hidden_cats) > 6 else "") +
                             "（『冒险手册 物品 <大类>』查看）")
            lines.append("━━━━━━━━━━━━")
            lines.append("💡 ✅=曾拥有 ×N=现持有 ｜ ❌=还没拿过 ｜ 『冒险手册 物品 <大类>』只看某类 ｜ 『+』翻页")
            self._record_list_state(qq_id, "冒险手册 物品", page, total_pages)
            return "\n".join(lines)
        except Exception as e:
            return f"🎒 物品图鉴加载失败（{e}）～"

    def _item_cat(self, v: dict):
        """物品大类归一（材料 type → 显示大类；装备/收藏品特殊；无 type 按结构特征推断）。"""
        t = (v or {}).get("type") or ""
        if t == "装备":
            return "装备"
        if t in ("收藏", "收藏品"):
            return "收藏品"
        if t in ("消耗品", "食物", "药品"):
            return "消耗品"
        if t in ("任务道具", "任务物品"):
            return "任务道具"
        if t in ("图纸",):
            return "图纸"
        if t in ("杂物", "垃圾"):
            return "杂物"
        if t:
            return t
        # 无 type：按结构特征推断（i_ 消耗品/食物定义不带 type）
        if isinstance(v, dict):
            if v.get("food"):
                return "消耗品"
            if v.get("heal") is not None or v.get("mana") is not None or v.get("effect"):
                return "消耗品"
            if v.get("slot") or v.get("equip"):
                return "装备"
        return "其他"

    def _norm_item_key(self, k, data):
        """展示用：把背包 key 归一化（装备 uuid → 原型 eq_）。复用 store 层解析。"""
        try:
            _possessed_key = _h('_possessed_key')  # ← from ..store.inventory import _possessed_key
            return _possessed_key(k, data)
        except Exception:
            return k

    @declared("bestiary")
    @require_player()

    async def bestiary(self, event: AstrMessageEvent):
        """『图鉴』=『冒险手册 怪物』别名（v168 保留兼容，老玩家习惯）。"""
        group_id, qq_id = self._uid(event)
        raw = self._strip_cmd(event, "图鉴").strip()
        # 子分类路由保留（垂钓/收藏），怪物=默认
        if raw and not raw.isdigit():
            sub = raw.strip()
            if sub in ("垂钓", "钓鱼", "鱼"):
                yield event.plain_result(self._collect_fish_bestiary(group_id, qq_id))
                return
            if sub in ("收藏", "收藏品", "纪念品"):
                yield event.plain_result(self._collect_items_bestiary(group_id, qq_id))
                return
            if sub in ("怪物", "图鉴", "全部", "所有"):
                raw = ""
        yield event.plain_result(self._monster_view(group_id, qq_id, raw))

    def _collect_fish_bestiary(self, group_id, qq_id):
        """v104 M15 修复：彩蛋收藏鱼收集进度展示（已收藏 X/3 + 各鱼钓获次数 + catch_collect 累计计数）
        v104 R3 M15 P2-3：收藏状态永久化——钓获即解锁的隐藏成就(collect_fish)为永久记录，
        出售收藏鱼后图鉴不回退（与怪物图鉴永久收录语义一致）；背包仍有存货时附 ×N 数量。
        v134.1 意见#41：头部加子分类提示（'图鉴 垂钓' 直达，怪物页尾部也有入口）。"""
        inv = {it["key"]: it["count"] for it in db.get_inventory(group_id, qq_id)}
        _ach_unlocked = set()
        try:
            _ach_unlocked = {r["ach_key"] for r in db.get_achievements(group_id, qq_id)}
        except Exception:
            pass
        _fish_ach = {}
        for _a in _cquest.ACHIEVEMENTS:
            _c = _a.get("cond") or {}
            if _c.get("type") == "collect_fish":
                _fish_ach[_c.get("key")] = _a["id"]
        owned = [cf for cf in _b143.FISH_COLLECT
                 if cf["id"] in inv or _fish_ach.get(cf["id"]) in _ach_unlocked]
        owned_ids = {cf["id"] for cf in owned}
        _stats = db.get_stats(group_id, qq_id) or {}
        _total = int(_stats.get("catch_collect", 0) or 0)
        lines = ["", "🌈 【彩蛋收藏鱼】已收藏 {}/{} · 累计钓获 {} 次".format(
            len(owned), len(_b143.FISH_COLLECT), _total), "━━━━━━━━━━━━"]
        for cf in _b143.FISH_COLLECT:
            if cf["id"] in owned_ids:
                _cnt = f" ×{inv[cf['id']]}" if cf["id"] in inv else ""
                lines.append(f"  ✅ {cf['name']}{_cnt}")
            elif cf.get("time") == "night":
                lines.append("  ❌ ??? （夜晚垂钓有极低概率邂逅）")
            else:
                lines.append("  ❌ ??? （垂钓时有极低概率邂逅）")
        lines.append("💡 彩蛋收藏鱼钓到自动收进图鉴；对应成就见『成就 隐藏』")
        return "\n".join(lines)

    def _pet_dex_view(self, group_id, qq_id) -> str:
        """v173.3 意见#125：『冒险手册 宠物』——孵过的宠物图鉴。

        pet_dex 记录孵化历史（含放生后仍保留），当前宠物（db.pet_get）标注'在队'。
        未孵过的宠物灰色占位展示（玩家知道还有哪些可收集）。
        """
        try:
            dex = db.pet_dex_get(qq_id)
            cur_pet = db.pet_get(qq_id)
            cur_key = (cur_pet or {}).get("key") if isinstance(cur_pet, dict) else None
            q_map = _b143.QUALITY
            rows = []
            for pd in _clife.PET_POOL:
                key = pd.get("key") or ""
                owned = key in dex
                q = q_map.get(pd.get("quality", ""), {})
                tag = "🐾在队" if key == cur_key else ("✅孵过" if owned else "❌未得")
                rows.append((owned, f"{q.get('color', '')}{pd.get('icon', '')}{pd.get('name', key)}{q.get('name', '')} · {tag}"))
            # 已孵过排前
            rows.sort(key=lambda x: (not x[0]))
            lines = [f"🐾 【宠物图鉴】({len(dex)}/{len(_clife.PET_POOL)})", "━━━━━━━━━━━━"]
            lines += [f"  {r[1]}" for r in rows]
            lines.append("━━━━━━━━━━━━")
            lines.append("💡 宠物蛋『使用』孵化即收录；放生后仍留图鉴；当前跟随标🐾")
            return "\n".join(lines)
        except Exception as e:
            return f"🐾 宠物图鉴加载失败（{e}），请联系管理～"

    def _collect_items_bestiary(self, group_id, qq_id):
        """v134.1 意见#41：『图鉴 收藏』特殊收藏品一览——type=收藏 的物品（不含彩蛋收藏鱼，
        鱼走『图鉴 垂钓』）。判据与批量出售保护同源（MATERIALS_BY_NAME/ITEMS 定义兜底，
        背包 data.type 可能被发放路径写死为"材料"）。已持有=背包有货；未持有=灰色占位（
        只列定义全量，让玩家知道有哪些可收集）。"""
        inv = {it["data"].get("name", ""): it["count"] for it in db.get_inventory(group_id, qq_id)}
        _defs = {}
        for _k, _v in _cit.MATERIALS_BY_NAME.items():
            if isinstance(_v, dict) and _v.get("type") == "收藏":
                _defs[_v.get("name", _k)] = _v
        for _k, _v in (_cit.ITEMS or {}).items():
            if isinstance(_v, dict) and _v.get("type") == "收藏":
                _defs[_v.get("name", _k)] = _v
        # 彩蛋收藏鱼单独走『图鉴 垂钓』（3 条 FISH_COLLECT 在 MATERIALS 里也是 type=收藏，剔除）
        _fish_names = {cf["name"] for cf in _b143.FISH_COLLECT}
        _defs = {n: v for n, v in _defs.items() if n not in _fish_names}
        owned = [n for n in _defs if n in inv]
        lines = [f"🏺 【收藏品图鉴】已收藏 {len(owned)}/{len(_defs)} 件", "━━━━━━━━━━━━"]
        if not _defs:
            lines.append("（暂无收藏品条目）")
        for n in sorted(_defs):
            _v = _defs[n]
            if n in inv:
                _cnt = f" ×{inv[n]}" if inv[n] > 1 else ""
                lines.append(f"  ✅ {n}{_cnt}")
            else:
                _d = (_v or {}).get("desc", "")
                _hint = f"（{_d[:30]}…）" if _d else ""
                lines.append(f"  ❌ ??? {_hint}")
        lines.append("")
        lines.append("💡 收藏品来自支线/隐藏任务奖励与纪念品，『图鉴 垂钓』看彩蛋收藏鱼，『图鉴』看怪物")
        return "\n".join(lines)

    @declared("encyclopedia")
    @require_player()

    async def encyclopedia(self, event: AstrMessageEvent):
        """百科：查材料掉落来源 / 怪物分布 / 地图怪物(v33)

        扩展分类浏览（v167）：『百科 副本』『百科 装备』『百科 材料』——
        raw 为分类关键词时走 _ency_browse_* 摘要浏览，具体名称仍走老逻辑单查。
        """
        group_id, qq_id = self._uid(event)
        player = self._player(group_id, qq_id)
        raw = self._strip_cmd(event, "百科").strip()
        if not raw:
            lines = [
                "📚 【世界百科】想知道什么？输入『百科 <名称>』",
                "━━━━━━━━━━━━",
                "🔍 可查询：装备 / 材料 / 怪物 / 地图 / 副本 / 符文",
                "🌐 分类浏览：『百科 副本』看全部副本 · 『百科 材料』按分类看材料 · 『百科 世界』看全大陆区域",
                "⚔️ 装备：『百科 <装备名>』看单件（含属性/词条/专属）· 『百科 装备』总览",
                "　　『百科装备 <部位>』列出该部位全部装备（部位：武器/头盔/胸甲/护腿/靴子/戒指/项链）",
                "✨ 词条：『百科 词条』看全部 76 词条 · 『百科 词条 <关键词>』查单个（如『百科 词条 破甲』）",
                "💎 宝石：『百科 宝石』看幸运宝石 10 阶（碎裂→神话）· 『百科 宝石 <阶名>』查单个",
                "　　『百科 符文』看全部符文 · 『百科 符文 <名>』查单个（如『百科 符文 残忍』）",
                "例：『百科 铁皮头盔』→ 装备详情｜『百科装备 头盔 2』→ 头盔第2页",
                "　　『百科 狼皮』→ 材料｜『百科 光耀狼』→ 怪物",
                self._tip("rune"),
            ]
            yield event.plain_result("\n".join(lines))
            return
        # 0. 分类浏览（v167）：具体名称仍走下方老逻辑，这里只收分类关键词
        if raw == "副本":
            yield event.plain_result(self._ency_browse_instances())
            return
        if raw == "装备" or raw.startswith("装备 "):
            yield event.plain_result(self._ency_browse_equips(raw, qq_id))
            return
        if raw == "材料":
            yield event.plain_result(self._ency_browse_materials())
            return
        if raw in ("世界", "大陆"):
            yield event.plain_result(self._ency_browse_world())
            return
        # 0.1 词条/宝石分类浏览与单查（v172：全量编目 + 名称关键词命中）
        if raw == "词条" or raw.startswith("词条 ") or raw == "词缀" or raw.startswith("词缀 "):
            yield event.plain_result(self._ency_browse_affixes(raw, qq_id))
            return
        if raw == "宝石" or raw.startswith("宝石 ") or raw == "幸运宝石" or raw.startswith("幸运宝石 "):
            yield event.plain_result(self._ency_browse_gems(raw, qq_id))
            return
        # 裸『符文』/『符文 N』→ 全量分页浏览；『符文 <名>』下方老逻辑单查兜底
        if re.match(r"^符文(?:\s+\d+)?\s*$", raw):
            yield event.plain_result(self._ency_browse_runes(raw, qq_id))
            return
        # 1. 符文查询（#135 模板汉化：原代码把 rn_xxx 内部 key 直接拼进标题/使用行 →
        # 「史诗符文·rn_brutal」；desc 模板 {v}/{v1} 未填值 → 效果行出现「攻击 {v}% 概率」
        # 原始占位符。查询按 中文名/效果key/掉落物品名 三路匹配）
        stone_name = None
        _rune_by_key = {k: r for k, r in _cit.RUNES.items()}
        for _rk, _rr in _rune_by_key.items():
            # 匹配：中文名子串 / 内部 key 子串（玩家查 rn_brutal 时给详情而非报错）
            if _rr.get("name") and _rr["name"] in raw:
                stone_name = _rk
                break
            if _rk in raw or f"符文·{_rk}" in raw:
                stone_name = _rk
                break
        if stone_name or "符文" in raw:
            if stone_name:
                st = _rune_by_key[stone_name]
                st_name = st.get("name", stone_name)
                q_name = _b143.QUALITY[st["quality"]]["name"]
                # 效果按等级 I/II/III 填 {v}/{v1}/{v2}（与掉落物品 rune_item 同源换算，等级 I 起步）
                _mk_rune_item = _h('rune_item')  # ← from ..core.runes import rune_item as _mk_rune_item
                _ri = _mk_rune_item(st["effect"], 1) or {}
                st_desc = _ri.get("desc") or st["desc"]
                # 冲突符文名（同 effect 池内互斥项，按冲突对把 effect → 中文名）
                _conf_names = []
                for _x, _y in _cit.RUNE_CONFLICTS:
                    _pair = None
                    if _x == st["effect"]:
                        _pair = _y
                    elif _y == st["effect"]:
                        _pair = _x
                    if _pair is not None:
                        _cn = _cit.RUNE_EFFECT_NAMES.get(_pair, _pair)
                        if _cn not in _conf_names:
                            _conf_names.append(_cn)
                _conf_txt = "、".join(_conf_names) + "(不能共存)" if _conf_names else "无"
                lines = [
                    f"💎 【{q_name}符文·{st_name}】",
                    "━━━━━━━━━━━━",
                    f"效果：{st_desc}",
                    f"品质：{q_name}",
                    f"等级：I / II / III(等级越高效果越强，高等级更稀有)",
                    f"冲突：{_conf_txt}",
                    f"获取：打怪概率掉落(精英/Boss 概率更高)",
                    f"使用：『附魔 <装备名> {q_name}符文·{st_name}』",
                ]
                yield event.plain_result("\n".join(lines))
                return
            # 无命中但带「符文」关键词 → 列出全部（中文名 + desc 填等级 I 数值，同 rune_item 换算）
            _rune_lines = []
            for _rn, _rs in _cit.RUNES.items():
                _mk_rune_item2 = _h('rune_item')  # ← from ..core.runes import rune_item as _mk_rune_item2
                _ri2 = _mk_rune_item2(_rs["effect"], 1) or {}
                _rune_lines.append(
                    f"  💎 {_b143.QUALITY[_rs['quality']]['name']}符文·{_rs.get('name', _rn)}"
                    f"({_ri2.get('desc') or _rs['desc']})"
                )
            yield event.plain_result("没找到这颗符文！可用：\n" + "\n".join(_rune_lines))
            return
        # 2. 材料查询（含词条材料来源）
        # v101.29：MATERIALS 的 key 是 mat_ ID（v48 后），按中文名查必须用 MATERIALS_BY_NAME
        # （旧代码 raw in C.MATERIALS 恒 False → 所有材料百科查询全部失效）
        mats_byname = _cit.MATERIALS_BY_NAME
        # 2.1 装备名册精确命中优先于材料模糊（v167.1：『百科 龙鳞头盔』应查装备，
        #    不被材料『龙鳞』的模糊子串抢先；材料精确 raw in mats_byname 仍最先）
        _roster_exact = [r for r in _cit.EQUIP_ROSTER.values() if r.get("name") == raw]
        if raw not in mats_byname and _roster_exact:
            # 重名多件 → 逐件列出（同名牌不同品质/Lv 是合法数据）
            if len(_roster_exact) > 1:
                elines = [f"⚔️ 找到 {len(_roster_exact)} 件同名装备『{raw}』：", "━━━━━━━━━━━━"]
                _attr_cn0 = {"str": "力量", "agi": "敏捷", "int": "智力", "vit": "耐力"}
                for _ri, _rx in enumerate(sorted(_roster_exact, key=lambda r: (r.get("lv", 0), r.get("quality", ""))), 1):
                    _qx = _b143.QUALITY.get(_rx.get("quality", "white"), {})
                    _sx = _b143.EQUIP_SLOTS.get(_rx.get("slot", ""), "?")
                    _reqx = _rx.get("req") or {}
                    _reqsx = "、".join(f"{_attr_cn0.get(k, k)}{v}" for k, v in _reqx.items()) if _reqx else "无需求"
                    elines.append(f"{_ri}. {_qx.get('color', '')}【{_rx['name']}】({_sx}·Lv.{_rx.get('lv', '?')}·{_qx.get('name', '')})｜{_reqsx}｜{_rx.get('source', '?')}")
                elines.append("━━━━━━━━━━━━")
                elines.append("💡 『百科装备 <部位>』按部位浏览可区分")
                yield event.plain_result("\n".join(elines))
                return
            _r = _roster_exact[0]
            # v172 百科详情：名册只有基础字段，先按名册生成一件标准装备（确定性统计词条
            # 池随机与真实生成同源）再渲染完整属性/词条/专属——与『物品详情』同源口径。
            _eq = _roster_gen_equip(_r)
            # 该件在 CRAFT_RECIPES 中是否有锻造配方（获取链提示用；rid 与生成路径同源）
            _rid_s = ""
            try:
                _rids0 = _cit.EQUIP_ROSTER_BY_NAME.get(_r.get("name", "")) or [
                    _k for _k, _rr in _cit.EQUIP_ROSTER.items() if _rr.get("name") == _r.get("name")]
                _rid_s = _rids0[0] if _rids0 else ""
            except Exception:
                _rid_s = ""
            _q = _b143.QUALITY.get(_r.get("quality", "white"), {})
            _slot_nm = _b143.EQUIP_SLOTS.get(_r.get("slot", ""), _r.get("slot", "?"))
            _attr_cn = {"str": "力量", "agi": "敏捷", "int": "智力", "vit": "耐力"}
            _req = _r.get("req") or {}
            _req_s = "、".join(f"{_attr_cn.get(k, k)}{v}" for k, v in _req.items()) if _req else "无需求"
            elines = [f"⚔️ {_q.get('color', '')}【{_r['name']}】({_slot_nm}·Lv.{_r.get('lv', '?')}·{_q.get('name', _r.get('quality'))})",
                     "━━━━━━━━━━━━"]
            # ---- 属性值 / 词条 / 专属：与真实生成（generate_roster_equip）同口径 ----
            if _eq:
                if _r.get("weapon_type"):
                    _wt_nm = C.display("weapon_types", _r["weapon_type"])
                    elines.append(f"类型：{_wt_nm}")
                    _fl = _b143.WEAPON_FLAVOR.get(_r["weapon_type"], {}).get("desc", "")
                    if _fl:
                        elines.append(f"✦ {_fl}")
                _stat_lines = []
                for _k, _v in (_eq.get("stats") or {}).items():
                    if _v:
                        _lb = _STAT_NAMES.get(_k, _k)
                        _stat_lines.append(f"{_lb} + {int(_v * 100)}%" if _k in _ccore.PCT_STATS else f"{_lb} + {_v}")
                if _stat_lines:
                    elines.append("属性：")
                    for _s in _stat_lines:
                        elines.append(f"  · {_s}")
                _aff_lines = []
                for _af in _eq.get("affixes") or []:
                    if isinstance(_af, dict):  # 旧结构兼容
                        _k, _v = _af.get("stat"), _af.get("value", 0)
                        _lb = _STAT_NAMES.get(_k, _k)
                        _aff_lines.append(f"{_lb} + {int(_v * 100)}%" if _k in _ccore.PCT_STATS else f"{_lb} + {_v}")
                        continue
                    _ai = _cit.AFFIXES.get(_af)
                    if _ai:
                        _aff_lines.append(f"{_ai.get('name', _af)}：{_ai.get('desc', '')}" if _ai.get("desc") else _ai.get("name", _af))
                if _aff_lines:
                    elines.append("✨ 词条：")
                    for _a in _aff_lines:
                        elines.append(f"  · {_a}")
                _feat = _equip_affix_features(_eq)
                if _feat:
                    elines.append(f"⭐ 词条特色：{'｜'.join(_feat)}")
                if _eq.get("legendary"):
                    _lg = _cit.LEGENDARY_EFFECTS.get(_eq["legendary"])
                    if _lg:
                        elines.append(f"✨ 专属·{_lg.get('name', '')}：{_lg.get('desc', '')}")
            if _r.get("series"):
                elines.append(f"系列：{_r['series']}")
            elines.append(f"需求：{_req_s}")
            if _r.get("source"):
                elines.append(f"来源：{_r['source']}")
            if _r.get("set"):
                elines.append(f"套装：{_r['set']}")
            if _r.get("special"):
                elines.append(f"特效：{_r['special']}")
            if _r.get("desc"):
                elines.append(f"{_r['desc']}")
            # ---- 获取链提示：锻造可得 / 可作重锻源 / 可由重锻获得（v172）----
            _has_craft = any((rec.get("roster_id") == _rid_s and _rid_s) for rec in _clife.CRAFT_RECIPES.values() if rec.get("roster_id"))
            if _has_craft:
                elines.append("🔨 获取：锻造可得（铁匠铺『锻造』）")
            # 重锻配方两张表兜底（v172 改名进行时：REFINE_RECIPES / REFINE_EXCLUSIVE_RECIPES）
            _ref_tbl = getattr(C, "REFINE_RECIPES", None) or getattr(C, "REFINE_EXCLUSIVE_RECIPES", None) or {}
            _as_src = [(_src_k, _rc) for _src_k, _rc in _ref_tbl.items() if _src_k in _r.get("name", "")]
            _refine_hints = []
            for _src_k, _rc in _as_src:
                _tgt_rec = _clife.CRAFT_RECIPES.get(_rc.get("target")) or {}
                _tgt_nm = _tgt_rec.get("name") or (C.display("recipes", _rc.get("target")) if _rc.get("target") else "?")
                _refine_hints.append(f"可重锻为 {_tgt_nm}")
            if _refine_hints:
                elines.append("🔀 " + "；".join(_refine_hints) + "（重锻继承一半强化/升级）")
            _as_tgt_names = []
            for _src_k, _rc in _ref_tbl.items():
                _tn = _clife.CRAFT_RECIPES.get(_rc.get("target")) or {}
                if _tn.get("name") == _r.get("name") or (_tn.get("roster_id") == _rid_s and _rid_s):
                    _as_tgt_names.append(_src_k)
            if _as_tgt_names:
                elines.append("🔀 " + "、".join(_as_tgt_names) + " 可重锻得到（在铁匠铺『装备重锻 <旧装备>』）")
            elines.append(f"💡 『百科装备 {_slot_nm}』看{_slot_nm}全部装备")
            yield event.plain_result("\n".join(elines))
            return
        if raw in mats_byname or any(kw in raw for kw in mats_byname):
            # 材料模糊子串命中前，先看是否更像装备名（v167.1：『龙鳞头』≠材料『龙鳞』）
            # 装备名包含 raw 前缀（raw 短 + 匹配装备名头）才优先——粗略判据：raw 含部位词尾或
            # 装备名以 raw 开头。这里只防明显误伤：raw 以部位词结尾（头/甲/腿/靴/戒/链/杖/剑…）
            _equip_like = bool(re.search(r"(头盔|头|胸甲|甲|护腿|腿|战靴|靴子|靴|戒指|戒|项链|链|杖|剑|弓|锤|枪|匕首|拳套|袍|衣|披风|斗篷|帽)$", raw))
            if _equip_like:
                _efuzzy = [r for r in _cit.EQUIP_ROSTER.values() if raw in r.get("name", "")][:8]
                if _efuzzy:
                    _attr_cn2 = {"str": "力量", "agi": "敏捷", "int": "智力", "vit": "耐力"}
                    flines = [f"❓ 找到 {len(_efuzzy)} 件装备名含『{raw}』，用全名查询（或『百科装备 <部位>』浏览）："]
                    for _i, _r in enumerate(_efuzzy, 1):
                        _q = _b143.QUALITY.get(_r.get("quality", "white"), {})
                        _snm = _b143.EQUIP_SLOTS.get(_r.get("slot", ""), "?")
                        _req = _r.get("req") or {}
                        _reqs = "、".join(f"{_attr_cn2.get(k, k)}{v}" for k, v in _req.items()) if _req else "无需求"
                        flines.append(f"  {_i}. {_q.get('color', '')}【{_r['name']}】({_snm}·Lv.{_r.get('lv', '?')})｜{_reqs}")
                    yield event.plain_result("\n".join(flines))
                    return
            # 精确匹配优先
            mat = mats_byname.get(raw) or next((m for k, m in mats_byname.items() if k in raw), None)
            if mat:
                mat_key = mat["name"]
                srcs = _cspace.ENCY_MATERIAL_SOURCE.get(mat_key, [])
                lines = [f"🧪 【{mat_key}】", "━━━━━━━━━━━━"]
                if mat.get("desc"):
                    lines.append(f"描述：{mat['desc']}")
                if srcs:
                    lines.append("掉落来源：")
                    for mname, mstr in srcs:
                        lines.append(f"  🗺️ {mname} → {mstr}")
                else:
                    lines.append("掉落来源：暂无(可能是任务/NPC 奖励)")
                lines.append("")
                lines.append(f"💡 出售价 {mat['price']} 金币")
                yield event.plain_result("\n".join(l for l in lines if l))
                return
        # 2.25 装备单查（v167.1）：按名册精确/模糊匹配——此前『百科 <装备名>』查不到装备
        _roster_hits = [r for r in _cit.EQUIP_ROSTER.values() if r.get("name") == raw]
        if not _roster_hits:
            _roster_hits = [r for r in _cit.EQUIP_ROSTER.values() if raw in r.get("name", "")][:8]
        if _roster_hits:
            if len(_roster_hits) == 1:
                _r = _roster_hits[0]
                _slot_nm = _b143.EQUIP_SLOTS.get(_r.get("slot", ""), _r.get("slot", "?"))
                # v172 百科详情：名册只有基础字段，先按名册生成一件标准装备（确定性统计词条
                # 池随机与真实生成同源）再渲染完整属性/词条/专属——与『物品详情』同源口径。
                _eq = _roster_gen_equip(_r)
                # 该件在 CRAFT_RECIPES 中是否有锻造配方（获取链提示用；rid 与生成路径同源）
                _gen_rid = ""
                try:
                    _rids0 = _cit.EQUIP_ROSTER_BY_NAME.get(_r.get("name", "")) or [
                        _k for _k, _rr in _cit.EQUIP_ROSTER.items() if _rr.get("name") == _r.get("name")]
                    _gen_rid = _rids0[0] if _rids0 else ""
                except Exception:
                    _gen_rid = ""
                _q = _b143.QUALITY.get(_r.get("quality", "white"), {})
                _attr_cn = {"str": "力量", "agi": "敏捷", "int": "智力", "vit": "耐力"}
                _req = _r.get("req") or {}
                _req_s = "、".join(f"{_attr_cn.get(k, k)}{v}" for k, v in _req.items()) if _req else "无需求"
                lines = [f"⚔️ {_q.get('color', '')}【{_r['name']}】({_slot_nm}·Lv.{_r.get('lv', '?')}·{_q.get('name', _r.get('quality'))})",
                         "━━━━━━━━━━━━"]
                # ---- 属性值 / 词条 / 专属：与真实生成（generate_roster_equip）同口径 ----
                if _eq:
                    _st = _eq.get("stats") or {}
                    if _r.get("weapon_type"):
                        _wt_nm = C.display("weapon_types", _r["weapon_type"])
                        lines.append(f"类型：{_wt_nm}")
                        _fl = _b143.WEAPON_FLAVOR.get(_r["weapon_type"], {}).get("desc", "")
                        if _fl:
                            lines.append(f"✦ {_fl}")
                    _stat_lines = []
                    for _k, _v in _st.items():
                        if _v:
                            _lb = _STAT_NAMES.get(_k, _k)
                            _stat_lines.append(f"{_lb} + {int(_v * 100)}%" if _k in _ccore.PCT_STATS else f"{_lb} + {_v}")
                    if _stat_lines:
                        lines.append("属性：")
                        for _s in _stat_lines:
                            lines.append(f"  · {_s}")
                    _aff_lines = []
                    for _af in _eq.get("affixes") or []:
                        if isinstance(_af, dict):  # 旧结构兼容
                            _k, _v = _af.get("stat"), _af.get("value", 0)
                            _lb = _STAT_NAMES.get(_k, _k)
                            _aff_lines.append(f"{_lb} + {int(_v * 100)}%" if _k in _ccore.PCT_STATS else f"{_lb} + {_v}")
                            continue
                        _ai = _cit.AFFIXES.get(_af)
                        if _ai:
                            _aff_lines.append(f"{_ai.get('name', _af)}：{_ai.get('desc', '')}" if _ai.get("desc") else _ai.get("name", _af))
                    if _aff_lines:
                        lines.append("✨ 词条：")
                        for _a in _aff_lines:
                            lines.append(f"  · {_a}")
                    _feat = _equip_affix_features(_eq)
                    if _feat:
                        lines.append(f"⭐ 词条特色：{'｜'.join(_feat)}")
                    if _eq.get("legendary"):
                        _lg = _cit.LEGENDARY_EFFECTS.get(_eq["legendary"])
                        if _lg:
                            lines.append(f"✨ 专属·{_lg.get('name', '')}：{_lg.get('desc', '')}")
                if _r.get("series"):
                    lines.append(f"系列：{_r['series']}")
                lines.append(f"需求：{_req_s}")
                if _r.get("source"):
                    lines.append(f"来源：{_r['source']}")
                if _r.get("set"):
                    lines.append(f"套装：{_r['set']}")
                if _r.get("special"):
                    lines.append(f"特效：{_r['special']}")
                if _r.get("desc"):
                    lines.append(f"{_r['desc']}")
                # ---- 获取链提示：锻造可得 / 可作重锻源 / 可由重锻获得（v172）----
                # 锻造配方按 名册名→rid 反查（名册条目本身无 rid 键，与生成路径同源）
                _has_craft = any(
                    (rec.get("roster_id") == _gen_rid)
                    for rec in _clife.CRAFT_RECIPES.values() if rec.get("roster_id"))
                if _has_craft:
                    lines.append("🔨 获取：锻造可得（铁匠铺『锻造』）")
                # 重锻配方两张表兜底（v172 改名进行时：REFINE_RECIPES / REFINE_EXCLUSIVE_RECIPES）
                _ref_tbl = getattr(C, "REFINE_RECIPES", None) or getattr(C, "REFINE_EXCLUSIVE_RECIPES", None) or {}
                _as_src = [(_src_k, _rc) for _src_k, _rc in _ref_tbl.items() if _src_k in _r.get("name", "")]
                _refine_hints = []
                for _src_k, _rc in _as_src:
                    _tgt_rec = _clife.CRAFT_RECIPES.get(_rc.get("target")) or {}
                    _tgt_nm = _tgt_rec.get("name") or (C.display("recipes", _rc.get("target")) if _rc.get("target") else "?")
                    _refine_hints.append(f"可重锻为 {_tgt_nm}")
                if _refine_hints:
                    lines.append("🔀 " + "；".join(_refine_hints) + "（重锻继承一半强化/升级）")
                # 作为重锻目标（其他名册装备能重锻成它）：按目标装备名反向查
                _as_tgt_names = []
                for _src_k, _rc in _ref_tbl.items():
                    _tn = _clife.CRAFT_RECIPES.get(_rc.get("target")) or {}
                    if _tn.get("name") == _r.get("name") or (_tn.get("roster_id") == _gen_rid and _gen_rid):
                        _as_tgt_names.append(_src_k)
                if _as_tgt_names:
                    lines.append("🔀 " + "、".join(_as_tgt_names) + " 可重锻得到（在铁匠铺『装备重锻 <旧装备>』）")
                lines.append(f"💡 『百科装备 {_slot_nm}』看{_slot_nm}全部装备")
                yield event.plain_result("\n".join(lines))
                return
            # 模糊多个 → 列候选
            flines = [f"❓ 找到 {len(_roster_hits)} 件名字含『{raw}』的装备，用全名查询："]
            for _i, _r in enumerate(_roster_hits, 1):
                _q = _b143.QUALITY.get(_r.get("quality", "white"), {})
                _snm = _b143.EQUIP_SLOTS.get(_r.get("slot", ""), "?")
                flines.append(f"  {_i}. {_q.get('color', '')}【{_r['name']}】({_snm}·Lv.{_r.get('lv', '?')})")
            yield event.plain_result("\n".join(flines))
            return
        # 2.5 副本钥匙/信物查询（v134 意见#36：玩家打副本卡主线不知道钥匙哪掉 → 通用百科）
        #   双向：『百科 王陵钥匙』→ 哪个副本要它 + 获取途径；『百科 旧王陵』→ 副本要什么钥匙 + 途径。
        #   数据源 INSTANCES.key_item / key_source（20 本带钥匙副本），与副本列表引导同源。
        _key_hits = [inst for inst in _cspace.INSTANCES.values() if inst.get("key_item")]
        _inst_by_key = {inst["key_item"]: inst for inst in _key_hits if inst.get("key_item")}
        if raw in _inst_by_key:
            inst = _inst_by_key[raw]
            lines = [f"🔑 【{raw}】", "━━━━━━━━━━━━"]
            lines.append(f"用途：『{inst['name']}』入场钥匙")
            lines.append(f"获取：{inst.get('key_source', '？？？')}")
            lines.append(f"副本：{inst['name']}（Lv.{inst.get('lv', '?')}+ · {inst.get('desc', '')[:40]}")
            lines.append("💡 『副本』看全部副本列表；已通关该副本可免钥匙入场")
            yield event.plain_result("\n".join(lines))
            return
        # v134.2 修复：副本名匹配覆盖全部副本（不只带钥匙的）——
        # 哥布林营地等无钥匙副本此前落进「地图查询」只显怪物，等级/人数/进入条件全漏
        _inst_by_name = {inst["name"]: inst for inst in _cspace.INSTANCES.values()}
        if raw in _inst_by_name:
            inst = _inst_by_name[raw]
            lines = [f"🏰 【{inst['name']}】", "━━━━━━━━━━━━"]
            if inst.get("desc"):
                lines.append(f"{inst['desc']}")
            # 进入条件：等级 / 人数
            _lv = inst.get("lv", "?")
            _min_p = inst.get("min_players", 1)
            _max_p = inst.get("max_players", _min_p)
            _ppl = f"{_min_p}-{_max_p} 人" if _max_p != _min_p else f"{_min_p} 人"
            lines.append(f"⚔️ 推荐等级 Lv.{_lv}+ · {_ppl} · {inst.get('icon', '🏰')}")
            # 钥匙需求（有钥匙才显示；无钥匙副本显示免钥匙）
            ki = inst.get("key_item")
            if ki:
                lines.append(f"🔑 入场需要『{ki}』：{inst.get('key_source', '？？？')}")
            else:
                lines.append("🔑 无需钥匙，直接进入")
            lines.append(f"💡 『副本 {inst['name']}』开启挑战；『百科 <钥匙名>』看钥匙获取（若需）")
            yield event.plain_result("\n".join(lines))
            return
        # 3. 地图查询
        if raw in _cspace.ENCY_MAP_MONSTERS:
            entries = _cspace.ENCY_MAP_MONSTERS[raw]
            mdef = next((m for m in _cspace.MAPS if m["name"] == raw), None)
            lines = [f"🗺️ 【{raw}】", "━━━━━━━━━━━━"]
            if mdef and mdef.get("desc"):
                lines.append(f"{mdef['desc']}")
            if entries:
                lines.append("怪物：")
                for mstr, lv, mtype in entries:
                    lines.append(f"  {mtype}·Lv.{lv} {mstr}")
            yield event.plain_result("\n".join(lines))
            return
        # 4. 怪物查询
        if raw in _cspace.ENCY_MONSTER_MAP:
            locs = _cspace.ENCY_MONSTER_MAP[raw]
            lines = [f"👹 【{raw}】", "━━━━━━━━━━━━"]
            lines.append("出现地点：")
            for mname, mtype in locs:
                lines.append(f"  {mtype} · {mname}")
            yield event.plain_result("\n".join(lines))
            return
        # 5. 怪物名模糊匹配
        fuzzy = [k for k in _cspace.ENCY_MONSTER_MAP if raw in k][:5]
        if fuzzy:
            yield event.plain_result(f"你是不是要找：{'、'.join(fuzzy)}？输入『百科 <完整名>』查看～")
            return
        yield event.plain_result(f"百科里没有『{raw}』！试试查材料(如『百科 狼皮』)、怪物(如『百科 光耀狼』)或地图(如『百科 远境草甸』)～")

    # ================= v167 百科分类浏览（三种摘要，数据源与单查一致） =================
    def _ency_browse_instances(self) -> str:
        """『百科 副本』：全部副本一览（含等级/人数/钥匙/主线章）——比『副本』指令的
        开本列表更全（那是按玩家等级上锁的玩法引导），这里是百科向完整编目。"""
        lines = ["🏰 【副本百科】共 {} 个副本".format(len(_cspace.INSTANCES)), "━━━━━━━━━━━━"]
        for _i, (_kid, inst) in enumerate(_cspace.INSTANCES.items(), 1):
            _lv = inst.get("lv", "?")
            _mn = inst.get("min_players", 1)
            _mx = inst.get("max_players", _mn)
            if _mx <= 1:
                _ppl = "单人"
            elif _mn == _mx:
                _ppl = f"{_mn}人"
            else:
                _ppl = f"{_mn}-{_mx}人"
            _line = f"{_i}. {inst.get('icon', '🏰')} {inst['name']}（Lv.{_lv}+ · {_ppl}）"
            # 主线章（desc 里的（主线第 N 章））——与单查 desc 同源
            _ch = ""
            _m = re.search(r"主线第\s*([^）)章]+)\s*章", inst.get("desc", "") or "")
            if _m:
                _ch = f" · 主线第{_m.group(1)}章"
            _line += _ch
            # 钥匙需求并入标题行（有钥匙的副本才占一格）
            _ki = inst.get("key_item")
            if _ki:
                _line += f" · 🔑需『{_ki}』"
            lines.append(_line)
            # 主题（desc 前 40 字，剥掉括号里的主线章标注）
            _theme = (inst.get("desc") or "").split("（主线")[0].split("(")[0].strip()
            lines.append(f"　📖 {_theme[:40]}")
        lines.append("━━━━━━━━━━━━")
        lines.append("💡 想了解某副本详情？『百科 <副本名>』（如『百科 旧王陵』）")
        return "\n".join(lines)

    def _ency_browse_equips(self, raw: str = "", qq_id: str = "") -> str:
        """『百科 装备』：装备名册浏览。

        无参数 → 按部位×品质总览（每品质代表）；
        『百科 装备 <部位> [页]』/『百科装备 <部位> [页]』→ 列出该部位全部装备（分页 12 件/页），
        每件一行：品质色【名】(Lv.X) + 需求 + 来源。部位词=武器/头盔/胸甲/护腿/靴子/戒指/项链。
        v167.1：记录 last_list 状态，支持通用翻页快捷键 +/−/=（cmd='百科装备 <部位>'）。
        """
        _roster = _cit.EQUIP_ROSTER
        _slot_cn = _b143.EQUIP_SLOTS
        # 尝试解析部位 + 页码
        _parts = (raw or "").split()
        _slot = None
        _page = 1
        if len(_parts) >= 2:
            _slot_word = _parts[1]
            # 部位别名（含"装备 头盔"里用户可能带"部"字等）
            _slot_map = {v: k for k, v in _slot_cn.items()}
            _slot_map.update({"武器": "weapon", "头盔": "helm", "帽子": "helm", "头": "helm",
                              "胸甲": "armor", "护甲": "armor", "衣服": "armor", "衣": "armor",
                              "护腿": "legs", "腿": "legs", "靴子": "boots", "鞋": "boots", "靴": "boots",
                              "戒指": "ring", "戒": "ring", "项链": "necklace", "链": "necklace"})
            _slot = _slot_map.get(_slot_word)
            if len(_parts) >= 3 and _parts[2].isdigit():
                _page = max(1, int(_parts[2]))
        # ---- 部位浏览（有部位词）----
        if _slot:
            _items = sorted((r for r in _roster.values() if r.get("slot") == _slot),
                            key=lambda r: (r.get("lv", 0), r.get("name", "")))
            if not _items:
                return f"装备名册里没有『{_parts[1]}』部位……试试 武器/头盔/胸甲/护腿/靴子/戒指/项链"
            _per = 12
            _pages = (len(_items) + _per - 1) // _per
            _page = min(_page, _pages)
            _view = _items[(_page - 1) * _per: _page * _per]
            _nm = _slot_cn.get(_slot, _parts[1])
            lines = [f"⚔️ 【{_nm}】共 {len(_items)} 件 · 第{_page}/{_pages}页", "━━━━━━━━━━━━"]
            for _ri, _r in enumerate(_view, (_page - 1) * _per + 1):
                _q = _b143.QUALITY.get(_r.get("quality", "white"), {})
                _lv = _r.get("lv", "?")
                _src = _r.get("source", "")
                _req = _r.get("req") or {}
                _attr_cn = {"str": "力量", "agi": "敏捷", "int": "智力", "vit": "耐力"}
                _req_s = "、".join(f"{_attr_cn.get(k, k)}{v}" for k, v in _req.items()) if _req else "无需求"
                _set = f" {_r.get('set', '')}" if _r.get("set") else ""
                lines.append(f"{_ri:>2}. {_q.get('color', '')}【{_r['name']}】(Lv.{_lv}){_set}｜{_req_s}｜{_src or '?'}")
            lines.append("━━━━━━━━━━━━")
            lines.append(f"💡 『查看 <序号>』看单件详情；『+』下页｜『百科装备 {_parts[1]} {_page+1}』下一页" if _page < _pages
                         else f"💡 『查看 <序号>』看单件详情；『-』回上页｜『百科 装备』回总览")
            # v167.1：记录列表状态 → +/-/= 通用翻页可用（cmd 用 '百科装备 <部位>' 可被百科正则重建）
            if qq_id:
                self._record_list_state(qq_id, f"百科装备 {_slot_word}", _page, _pages)
            return "\n".join(lines)
        # ---- 总览（无部位词）----
        lines = ["⚔️ 【装备名册】共 {} 件 · 按部位/品质速览".format(len(_roster)), "━━━━━━━━━━━━"]
        for _slot_k in _slot_cn:
            _items = [r for r in _roster.values() if r.get("slot") == _slot_k]
            if not _items:
                continue
            _nm = _slot_cn[_slot_k]
            _cnt = len(_items)
            _qcnt = {q: 0 for q in _b143.QUALITY_ORDER}
            for _r in _items:
                _q = _r.get("quality")
                if _q in _qcnt:
                    _qcnt[_q] += 1
            _qb = " ".join("{}{}".format(_b143.QUALITY[q]["color"], _qcnt[q]) for q in _b143.QUALITY_ORDER if _qcnt[q])
            _reps = []
            for _q in _b143.QUALITY_ORDER:
                _pool = sorted((r for r in _items if r.get("quality") == _q), key=lambda r: -r.get("lv", 0))
                if not _pool:
                    continue
                _top = _pool[0]
                _src = _top.get("source", "?")
                _src_icon = {"图纸": "📜", "锻造": "🔨", "商店": "💰", "boss": "👹",
                             "副本Boss": "👹", "精英": "⚡", "精英专属": "⚡",
                             "legend": "🌟", "任务": "📕", "支线": "📕", "宝藏": "🗝️"}.get(_src, "·")
                _reps.append("{}{} {}(Lv.{})".format(_src_icon, _b143.QUALITY[_q]["name"], _top["name"], _top.get("lv", "?")))
            lines.append("")
            lines.append(f"◈ {_nm} ×{_cnt}　{_qb}")
            lines.append("　代表：" + "　".join(_reps))
        lines.append("━━━━━━━━━━━━")
        lines.append("💡 『百科装备 <部位>』列出该部位全部装备（武器/头盔/胸甲/护腿/靴子/戒指/项链）；"
                     "『百科 <装备名>』看单件详情")
        return "\n".join(lines)

    def _ency_browse_materials(self) -> str:
        """『百科 材料』：材料按分类（type 字段）分组摘要——每类数量 + 代表性材料名。
        新材料（v167 等）只要进 MATERIALS 即自动带出，无硬编码名单。"""
        _by_type = {}
        for _k, _m in _cit.MATERIALS.items():
            _t = _m.get("type") or "杂物"
            _by_type.setdefault(_t, []).append(_m.get("name", _k))
        # 显示顺序：craft 原料大分类在前，任务/杂物/收藏垫底；未收录分类自动追加
        _order = ["兽材", "矿石", "木材", "织物", "草药", "宝石", "精华",
                  "食材", "材料", "鱼", "鱼王", "图纸", "传说", "元素", "符文", "工具",
                  "宝物", "垃圾", "任务道具", "收藏", "杂物"]
        _order = [t for t in _order if t in _by_type]
        _rest = sorted(t for t in _by_type if t not in _order)
        _order += _rest
        lines = ["🧪 【材料百科】共 {} 种材料 · 按分类速览".format(len(_cit.MATERIALS)), "━━━━━━━━━━━━"]
        for _t in _order:
            _names = _by_type[_t]
            _cnt = len(_names)
            # 单件/双件分类（鱼王/元素/宝物/工具等）：名字列全
            if _cnt <= 2:
                lines.append(f"{_t} ×{_cnt}　{'、'.join(_names)}")
                continue
            # 大分类：数量 + 每类代表性 3 个（价格降序即稀有度观感，稳定且不随插入序漂移）
            _rep = sorted(_names, key=lambda n: -int(_cit.MATERIALS_BY_NAME[n].get("price", 0)))[:3]
            lines.append(f"{_t} ×{_cnt}　例：{'、'.join(_rep)}")
        lines.append("━━━━━━━━━━━━")
        lines.append("💡 输入『百科 <材料名>』看掉落来源；『图鉴』看收藏品")
        return "\n".join(lines)

    def _ency_browse_world(self) -> str:
        """『百科 世界』：全大陆区域总览——按大区(region)分组，
        每组：等级范围 + 城镇列表 + 代表野外/副本。数据读 MAPS，无硬编码。"""
        _by_reg = {}
        for _m in _cspace.MAPS:
            _reg = _m.get("region") or "未划分区域"
            _by_reg.setdefault(_reg, []).append(_m)
        _total = len(_cspace.MAPS)
        lines = [f"🗺️ 【奥兰迪亚大陆】{len(_by_reg)} 大区域 · {_total} 地点",
                 "━━━━━━━━━━━━"]
        # 大区排序：按区内最低等级（新手区在前，符合探索顺序）
        _regs = sorted(_by_reg.items(), key=lambda kv: min((m.get("lv") or 0) for m in kv[1]))
        for _reg, _ms in _regs:
            _lvs = [m.get("lv") for m in _ms if m.get("lv")]
            _lv_s = f"Lv.{min(_lvs)}-{max(_lvs)}" if _lvs else ""
            # 城镇 = type 城镇区域 的 area_name（去重保序）
            _towns = []
            for _m in _ms:
                if _m.get("type") == "城镇区域":
                    _tn = _m.get("area_name") or _m.get("name")
                    if _tn and _tn not in _towns:
                        _towns.append(_tn)
            _wilds = [_m.get("name") for _m in _ms
                      if _m.get("type") not in ("城镇区域", "副本") and _m.get("name")]
            _duns = [_m.get("name") for _m in _ms if _m.get("type") == "副本" and _m.get("name")]
            lines.append("")
            lines.append(f"◈ {_reg}（{_lv_s}）")
            if _towns:
                lines.append("　🏘 " + "、".join(_towns))
            if _wilds:
                # 野外多 → 只列前 4 个 + 省略号
                _w_s = "、".join(_wilds[:4]) + (" 等" if len(_wilds) > 4 else "")
                lines.append(f"　○ {_w_s}")
            if _duns:
                _d_s = "、".join(_duns[:3]) + (" 等" if len(_duns) > 3 else "")
                lines.append(f"　⛩ {_d_s}")
        lines.append("━━━━━━━━━━━━")
        lines.append("💡 『区域』看当前可前往｜『寻路 <地名>』算最短路径｜『百科 <地名>』看单区详情")
        return "\n".join(lines)

    # ================= v172 百科分类浏览：词条 / 宝石 / 符文 =================
    @staticmethod
    def _affix_q_label(ak: str) -> str:
        """词条适用品质标签：qualities 显式字段 > 池归属推导（blue/purple/orange/legendary 稀有度）。"""
        _av = _cit.AFFIXES.get(ak) or {}
        _qs = _av.get("qualities")
        if _qs:
            _qn = {"blue": "稀有", "purple": "史诗", "orange": "传说"}.get(_qs[0], str(_qs[0]))
            return f"{_qn}+" if len(_qs) > 1 else _qn
        for _pool_q in ("blue", "purple", "orange"):
            if ak in _b143.AFFIX_POOL_BY_QUALITY.get(_pool_q, []):
                return {"blue": "稀有", "purple": "史诗", "orange": "传说"}.get(_pool_q, _pool_q)
        return "传说"

    def _ency_browse_affixes(self, raw: str = "", qq_id: str = "") -> str:
        """『百科 词条 [关键词|页码]』：全部词条编目（AFFIXES，76 个）。

        无参 → 全量分页（12 个/页，记录 last_list 供 +/-/= 通用翻页）；
        带关键词 → 名称/ID/效果子串命中单个词条详情（含 trigger/品质归属）。
        """
        _parts = (raw or "").split()
        _q_word = _parts[1] if len(_parts) >= 2 else ""
        # ---- 单个词条查询：名称/ID/关键词 命中（精确名 > 子串）----
        _hits = []
        if _q_word:
            for _ak, _av in _cit.AFFIXES.items():
                _nm = _av.get("name", "")
                if _q_word == _nm or _ak == _q_word or (_q_word and (_q_word in _nm or _q_word in _ak or _q_word in (_av.get("desc", "") or ""))):
                    _hits.append((_ak, _av))
            # 精确名命中 → 过滤掉纯子串命中的歧义项（『破甲』应直接给 破甲 而不是 破甲/破甲刃 二选一）
            _exact = [h for h in _hits if h[1].get("name") == _q_word or h[0] == _q_word]
            if len(_exact) == 1:
                _hits = _exact
            if _hits:
                if len(_hits) > 1:
                    _lk = [f"  · {_cit.AFFIXES[h[0]].get('name', h[0])}（{self._affix_q_label(h[0])}）" for h in _hits[:10]]
                    return "🔍 词条『{}』命中 {} 个：\n{}\n━━━━━━━━━━━━\n💡 用完整词条名查单个（如『百科 词条 破甲』）".format(
                        _q_word, len(_hits), "\n".join(_lk))
                _ak, _av = _hits[0]
                _qname = self._affix_q_label(_ak)
                _kind = "武器" if _av.get("kind") == "attack" else ("防具" if _av.get("kind") == "defense" else str(_av.get("kind", "?")))
                _trig_cn = {"stat": "常驻属性", "on_hit": "攻击命中后", "on_taken": "受击时",
                            "turn_start": "每刻开始", "battle_start": "战斗开始", "passive": "被动判定"}.get(
                    _av.get("trigger"), str(_av.get("trigger", "?")))
                _eff = _av.get("effect") or {}
                lines = [f"✨ 【{_av.get('name', _ak)}】", "━━━━━━━━━━━━"]
                lines.append(f"归属：{_kind}词条 · {_qname}")
                if _av.get("line"):
                    lines.append(f"线：{_av['line']}")
                lines.append(f"触发：{_trig_cn}" + (f"（概率 {int(_av['chance'] * 100)}%）" if _av.get("chance") else ""))
                if _av.get("desc"):
                    lines.append(f"效果：{_av['desc']}")
                if _eff and not _av.get("desc"):
                    # 无玩家向 desc 才展示原始 effect 参数（全部 76 词条都有 desc，兜底防空）
                    lines.append(f"参数：{_eff}")
                if _av.get("unique"):
                    lines.append("唯一：同名词条全服不可叠加")
                lines.append("")
                lines.append(f"💡 出现在装备『✨ 词条』栏；『百科 词条』看全部")
                return "\n".join(lines)
        # ---- 全量分页 ----
        _items = sorted(_cit.AFFIXES.items(), key=lambda kv: (0 if kv[1].get("kind") == "attack" else 1, kv[1].get("name", kv[0])))
        _per = 12
        _pages = (len(_items) + _per - 1) // _per
        _page = 1
        if _q_word and _q_word.isdigit():
            _page = max(1, min(int(_q_word), _pages))
        _view = _items[(_page - 1) * _per: _page * _per]
        lines = [f"✨ 【词条百科】共 {len(_cit.AFFIXES)} 个 · 第{_page}/{_pages}页", "━━━━━━━━━━━━"]
        for _i, (_ak2, _av2) in enumerate(_view, (_page - 1) * _per + 1):
            _qcn = self._affix_q_label(_ak2)
            _desc = _av2.get("desc", "")
            if len(_desc) > 24:
                _desc = _desc[:24] + "…"
            lines.append(f"{_i:>2}. {_av2.get('name', _ak2)}（{_qcn}）{_desc}")
        lines.append("━━━━━━━━━━━━")
        lines.append(f"💡 『+』下页｜『-』回上页｜『百科 词条 <关键词>』查单个（如『百科 词条 破甲』）" if _page < _pages
                     else "💡 『-』回上页｜『百科 词条 <关键词>』查单个（如『百科 词条 破甲』）")
        if qq_id:
            self._record_list_state(qq_id, "百科 词条", _page, _pages)
        return "\n".join(lines)

    def _ency_browse_gems(self, raw: str = "", qq_id: str = "") -> str:
        """『百科 宝石 [阶名|页码]』：幸运宝石 10 阶编目（碎裂→神话）。

        每阶：全名 + 随机属性加成倍率（GEM_TIERS.mult）+ 合成链/可插孔位说明。
        带阶名/关键词 → 单阶详情（附传说特效与掉落来源）。
        """
        _parts = (raw or "").split()
        _q_word = next((p for p in _parts[1:] if not p.isdigit()), "")
        # ---- 单阶查询：阶名关键词命中（GEM_TIER_NAMES / GEM_TIERS.name）----
        if _q_word:
            _hit_t = None
            for _t, _tn in _b143.GEM_TIER_NAMES.items():
                if _q_word in _tn or (_q_word in (_b143.GEM_TIERS.get(_t, {}).get("name", ""))):
                    _hit_t = _t
                    break
            if _hit_t is not None:
                return self._gem_tier_detail(_hit_t)
        # ---- 全量 10 阶 ----
        _lines = [f"💎 【幸运宝石百科】共 {len(_b143.GEM_TIERS)} 阶 · 碎裂 → 神话", "━━━━━━━━━━━━"]
        for _t in sorted(_b143.GEM_TIERS):
            _g = _b143.GEM_TIERS[_t]
            _nm = _b143.GEM_TIER_NAMES.get(_t, str(_t))
            _pct = int(_g.get("mult", 0) * 100)
            _lines.append(f"{_t:>2}. {_nm}：随机属性 ×{_pct}%")
        _lines.append("")
        _lines.append("🔗 合成链：3 颗同级 → 1 颗上级（碎裂→黯淡→…→神话）")
        _lines.append("🔩 打孔镶嵌：稀有装 1 孔（碎裂-普通）· 史诗装 2 孔（普通-无瑕）· 传说装 3 孔（无瑕-神话）")
        _lines.append("━━━━━━━━━━━━")
        _lines.append("💡 『百科 宝石 <阶名>』看单阶详情（如『百科 宝石 碎裂』）｜『原石』看你背包的宝石")
        return "\n".join(_lines)

    def _gem_tier_detail(self, tier: int) -> str:
        """幸运宝石单阶详情（wiki 展示口径）"""
        _g = _b143.GEM_TIERS.get(tier) or {}
        _nm = _b143.GEM_TIER_NAMES.get(tier, str(tier))
        _pct = int(_g.get("mult", 0) * 100)
        _lines = [f"💎 【{_nm}】", "━━━━━━━━━━━━"]
        _lines.append(f"阶位：{tier}/10 ｜ 效果：镶嵌后随机属性 ×{_pct}%")
        _up = tier + 1
        _up_nm = _b143.GEM_TIER_NAMES.get(_up)
        if _up_nm:
            _lines.append(f"合成：3 颗『{_nm}』→ 1 颗『{_up_nm}』（『原石合成』）")
        else:
            _lines.append("已是最高阶，无法再合成！")
        _lines.append("获取：打怪概率掉落（普通怪碎裂-无瑕 · 精英更高 · Boss 可出传说/神话）")
        if tier >= 8:
            _lines.append(f"🌟 传说级特效：{' / '.join(_b143.GEM_LEGENDARY_EFFECTS)}（仅传说阶触发）")
        _lines.append("")
        _lines.append(f"💡 『镶嵌 <装备名> <幸运宝石>』塞进装备孔位｜『百科 宝石』看全部 10 阶")
        return "\n".join(_lines)

    def _ency_browse_runes(self, raw: str = "", qq_id: str = "") -> str:
        """『百科 符文 [页码]』：全部符文编目（RUNES，16 个，每页 12）。

        效果 desc 用 rune_item 换算等级 I 数值（与掉落/单查同源）。
        """
        _mk_rune = _h('rune_item')  # ← from ..core.runes import rune_item as _mk_rune
        _parts = (raw or "").split()
        _page = int(_parts[1]) if len(_parts) >= 2 and _parts[1].isdigit() else 1
        _items = sorted(_cit.RUNES.items(), key=lambda kv: kv[1].get("name", kv[0]))
        _per = 12
        _pages = max(1, (len(_items) + _per - 1) // _per)
        _page = max(1, min(_page, _pages))
        _view = _items[(_page - 1) * _per: _page * _per]
        lines = [f"💎 【符文百科】共 {len(_cit.RUNES)} 个 · 第{_page}/{_pages}页", "━━━━━━━━━━━━"]
        for _i, (_rk, _rs) in enumerate(_view, (_page - 1) * _per + 1):
            _q = _b143.QUALITY.get(_rs.get("quality", ""), {})
            _ri = _mk_rune(_rs.get("effect"), 1) or {}
            _d = _ri.get("desc") or _rs.get("desc", "")
            if len(_d) > 30:
                _d = _d[:30] + "…"
            lines.append(f"{_i:>2}. {_q.get('color', '')}【{_rs.get('name', _rk)}】{_q.get('name', '')} · {_d}")
        lines.append("━━━━━━━━━━━━")
        lines.append(f"💡 『+』下页｜『-』回上页｜『百科 符文 <名>』查单个（如『百科 符文 残忍』）" if _page < _pages
                     else "💡 『-』回上页｜『百科 符文 <名>』查单个（如『百科 符文 残忍』）")
        if qq_id:
            self._record_list_state(qq_id, "百科 符文", _page, _pages)
        return "\n".join(lines)

    def _earned_titles(self, group_id, qq_id, player):
        """计算已获得的称号，返回 (已获列表, 未获列表)
        v98.3：条件判定全数据化 → core/title_conds.py CONDITIONS 注册表"""
        TitleCtx = _h('TitleCtx')  # ← from ..core.title_conds import TitleCtx, CONDITIONS, check_pro_title
        CONDITIONS = _h('CONDITIONS')  # ← from ..core.title_conds import TitleCtx, CONDITIONS, check_pro_title
        check_pro_title = _h('check_pro_title')  # ← from ..core.title_conds import TitleCtx, CONDITIONS, check_pro_title
        stats = db.get_stats(group_id, qq_id) or {}
        rep = db.get_reputation(group_id, qq_id)
        quests = db.get_quests(group_id, qq_id)
        ctx = TitleCtx(group_id, qq_id, player, stats, rep, quests, hooks={
            "has_enhanced": self._has_enhanced,
            "visited_maps": self._visited_maps,
        })
        earned = []
        for t in _cquest.TITLES:
            tid = t["id"]
            fn = CONDITIONS.get(tid)
            if fn is not None:
                ok = fn(ctx)
            elif tid.startswith("pro_"):
                ok = check_pro_title(tid, ctx)
            else:
                ok = False  # 未知称号 id：不获得（数据错误时安全降级）
            earned.append(ok)
        return earned

    def _visited_maps(self, group_id, qq_id):
        import sqlite3
        try:
            conn = sqlite3.connect(db.DB_PATH)
            rows = conn.execute("SELECT map_id FROM visited WHERE qq_id=?", (qq_id,)).fetchall()
            conn.close()
            return [r[0] for r in rows]
        except Exception:
            return []

    def _has_enhanced(self, group_id, qq_id, level):
        items = db.get_inventory(group_id, qq_id)
        for it in items:
            if it["data"].get("enhance", 0) >= level:
                return True
        # v105 M18 P2：并查已装备槽——强化过的装备穿在身上也算
        # （此前只查背包，『锻造新星』『神匠之手』会漏计装备槽中的 +5/+9 武器）
        p = self._player(group_id, qq_id)
        if p:
            for _slot, _it in (p.get("equipment") or {}).items():
                if _it and _it.get("enhance", 0) >= level:
                    return True
        return False

    @declared("titles")
    @require_player()

    async def titles(self, event: AstrMessageEvent):
        group_id, qq_id = self._uid(event)
        player = self._player(group_id, qq_id)
        raw = self._strip_cmd(event, "称号").strip()
        # 装备/卸下称号
        if raw.startswith("装备") or raw.startswith("佩戴"):
            tname = raw[2:].strip()
            async for r in self._equip_title(event, group_id, qq_id, player, tname):
                yield r
            return
        if raw in ("卸下", "取消"):
            db.update_player(group_id, qq_id, equipped_title="")
            yield event.plain_result("🏅 已卸下称号。")
            return
        earned = self._earned_titles(group_id, qq_id, player)
        got = [_cquest.TITLES[i]["name"] for i in range(len(_cquest.TITLES)) if earned[i]]
        # 阶段九：成就称号合并（14 章：达成成就自动获得称号）
        try:
            got += C.achievement_titles(qq_id)
        except Exception:
            pass
        got = list(dict.fromkeys(got))  # 去重保序
        cur = player.get("equipped_title") or ""
        if not got:
            yield event.plain_result("🏅 【称号】\n━━━━━━━━━━━━\n还没有称号……提升等级、击杀怪物、解锁成就可以获得！")
            return
        if raw and raw.isdigit():
            page = int(raw)
        else:
            page = 1
        page_items, pages, page = self._page_items(got, page, per_page=8)
        lines = [f"🏅 【称号】已获得 {len(got)} 个(第 {page}/{pages} 页)", "━━━━━━━━━━━━"]
        for i, n in enumerate(page_items, (page - 1) * 8 + 1):
            mark = "👑" if n == cur else "  "
            lines.append(f"{mark}{i:>2}. {n}")
        lines.append("")
        self._record_list_state(qq_id, "称号", page, pages)
        lines.append(self._tip("title"))
        if not cur:
            lines.append("💡 当前未佩戴称号")
        yield event.plain_result("\n".join(lines))

    async def _equip_title(self, event, group_id, qq_id, player, tname):
        """装备称号(必须是已获得称号)"""
        if not tname:
            yield event.plain_result("格式：『称号 装备 <称号名>』～")
            return
        earned = self._earned_titles(group_id, qq_id, player)
        got = [_cquest.TITLES[i]["name"] for i in range(len(_cquest.TITLES)) if earned[i]]
        try:
            got += C.achievement_titles(qq_id)
        except Exception:
            pass
        got = list(dict.fromkeys(got))
        hit = next((n for n in got if tname in n), None)
        if not hit:
            yield event.plain_result(f"还没获得称号『{tname}』！『称号』查看已获得列表～")
            return
        db.update_player(group_id, qq_id, equipped_title=hit)
        yield event.plain_result(f"👑 你佩戴上了称号【{hit}】！现在别人会称你为 [{hit}] 冒险者～")

    @staticmethod
    def _item_category(d: dict) -> str:
        """物品大类：装备(有 slot)→ 装备；其余按 type 归并（材料大类→『材料』）"""
        if d.get("slot"):
            return "装备"
        return _item_kind_type(d.get("type")) or "其他"

    @staticmethod
    def _parse_bag_filter(text: str):
        """解析背包筛选参数：返回 (category, page)
        支持带空格（『材料 2』）与无空格（『材料2』）两种形式"""
        category = None
        page = 1
        text = (text or "").strip()
        # 带空格形式：『材料』『材料 2』『2』
        for p in text.split():
            if p in _clife.BAG_FILTER_TYPES:
                category = p
            elif p.isdigit():
                page = int(p)
        # 无空格形式：『材料2』『2』
        if category is None:
            for t in _clife.BAG_FILTER_TYPES:
                if text.startswith(t):
                    category = t
                    rest = text[len(t):].strip()
                    if rest.isdigit():
                        page = int(rest)
                    break
            else:
                if text.isdigit():
                    page = int(text)
        return category, page

    @declared("inventory")
    @require_player()

    async def inventory(self, event: AstrMessageEvent):
        group_id, qq_id = self._uid(event)
        player = self._player(group_id, qq_id)
        raw = self._strip_cmd(event, "背包")
        result = self._bag_view(group_id, qq_id, raw)
        yield event.plain_result(result)

    @declared("bag_filter")
    @require_player()

    async def bag_filter(self, event: AstrMessageEvent):
        group_id, qq_id = self._uid(event)
        player = self._player(group_id, qq_id)
        raw = self._strip_cmd(event, "背包筛选")
        result = self._bag_view(group_id, qq_id, raw, filter_only=True)
        yield event.plain_result(result)

    def _bag_view(self, group_id, qq_id, raw, filter_only: bool = False) -> str:
        """背包列表渲染（v42：inventory 与背包筛选共用）
        filter_only=True 时无筛选参数给出提示而不是显示全部"""
        raw = (raw or "").strip()
        category, page = self._parse_bag_filter(raw)
        # v104 M24 P2-3：『背包 上一页/下一页』相对翻页（策划案 23 章:229 模板）。
        # 旧行为：非数字参数被 _parse_bag_filter 忽略 → 静默回第 1 页；
        # 现以 event_state 记录上次视图(分类+页码)，关键词按上次位置 ±1 翻页（越界 clamp）。
        step = 0
        if "上一页" in raw:
            step = -1
        elif "下一页" in raw:
            step = 1
        if step:
            saved = {}
            try:
                saved = json.loads(db.get_event_state(f"bag_page_{group_id}_{qq_id}") or "{}")
            except (ValueError, TypeError):
                saved = {}
            if category is None:
                category = saved.get("cat") or None
            page = (saved.get("page") or 1) + step
            if page < 1:
                page = 1
        if filter_only and category is None and not step:
            return "🎒 背包筛选：『背包筛选 <类型>』，如『背包筛选 材料』『筛选装备』\n" \
                   "类型：装备/材料/消耗品/符文/宠物蛋/坐骑/图纸/鱼；支持翻页『背包筛选 材料 2』"
        items = db.get_inventory(group_id, qq_id)
        if category:
            items = [it for it in items if self._item_category(it["data"]) == category]
            if not items:
                return f"背包里没有『{category}』类物品～『背包』看全部"
        if not items:
            # v134.6：空背包也记录列表状态（否则『查看 <数字>』会沿用上一列表的技能上下文）
            self._record_list_state(qq_id, f"背包 {category}" if category else "背包", 1, 1)
            return "你的背包空空如也……去『探索』打点东西吧！"
        page_items, pages, page = self._page_items(items, page, per_page=10)  # v127.2 背包每页 10 件
        # 记录当前视图(分类+页码)，供『上一页/下一页』相对翻页
        try:
            db.set_event_state(f"bag_page_{group_id}_{qq_id}",
                               json.dumps({"cat": category or "", "page": page}, ensure_ascii=False))
        except Exception:
            pass
        # v123 通用列表状态：翻页快捷键 +/−/= 恢复本列表（保留上方旧相对翻页状态，两者并存）
        self._record_list_state(qq_id, f"背包 {category}" if category else "背包", page, pages)
        title = f"🎒 【背包·{category}】" if category else "🎒 【背包】"
        lines = [title, "━━━━━━━━━━━━"]  # 玩家意见 #5 zerc：页数/翻页提示移到列表底部（见下方 📄 行）
        for i, it in enumerate(page_items, (page - 1) * 10 + 1):  # v130.3 序号起点随 per_page=10 同步（原 5 错位）
            d = it["data"]
            if _item_kind_type(d.get("type")) == "材料":
                # v101.25e 材料品质色 + 类型标签（鱼鱼拍板：材料也要品质；v101.25f 去掉"可出售"尾巴）
                # v126.3：type 为配置细分值（兽材/矿石/…）→ 按大类归并后命中本分支
                _mm = _cit.MATERIALS_BY_NAME.get(d["name"])
                if _mm and _mm.get("quality") in _b143.QUALITY:
                    lines.append(f"{i:>2}. {_b143.QUALITY[_mm['quality']]['color']}{d['name']} ×{it['count']} ({_mm.get('type', '杂物')})")
                else:
                    lines.append(f"{i:>2}. {d['name']} ×{it['count']} (材料)")
            elif d.get("type") == "图纸":
                # v101.25 #326：图纸标注——玩家学完才能用（playtest round67 小蓝抓包海风长弓图纸误导）
                # v101.30d #O47：措辞修正——"需解锁锻造副业"误导（实际学到即可在铁匠铺锻造，
                # 小白实测珍珠项链图纸与行为矛盾），改为动作指引
                lines.append(f"{i:>2}. 📜 {d['name']} ×{it['count']} (图纸：学习后到铁匠铺锻造)")
            elif d.get("slot"):
                q = _b143.QUALITY[d["quality"]]
                enh = d.get("enhance", 0)
                enh_str = f" +{enh}" if enh > 0 else ""
                lines.append(f"{i:>2}. {q['color']}【{d['name']}{enh_str}】({_b143.EQUIP_SLOTS[d['slot']]}) Lv.{d['lv']}")
            else:
                # v101.27：符文等带品质字段的物品也显示品质 emoji——v101.25i6 品质统一后
                # 新符文 quality=blue/purple/orange，但存量背包符文是旧格式中文(稀有/史诗/传说)
                _q = d.get("quality")
                _q = {"稀有": "blue", "史诗": "purple", "传说": "orange"}.get(_q, _q)
                if _q and _q in _b143.QUALITY and _q != "white":
                    lines.append(f"{i:>2}. {_b143.QUALITY[_q]['color']}{d['name']} ×{it['count']}")
                else:
                    lines.append(f"{i:>2}. {d['name']} ×{it['count']}")
        lines.append("━━━━━━━━━━━━")  # v127.2 提示区上方分隔
        # 玩家意见 #5（zerc）：页数/翻页提示从标题移到底部，
        # 与炼金/烹饪/锻造/技能列表的底部页数风格统一（📄 行）
        _flip = f"｜『背包筛选 {category} {page + 1}』下一页" if (category and page < pages) \
            else (f"｜『背包 {page + 1}』下一页" if page < pages else "")
        lines.append(f"📄 第 {page}/{pages} 页 · 共 {len(items)} 件{_flip}")
        # v127.4.1 移除物品列表与分隔线之间的空行——分隔线本身即视觉间隔，空行多余（鱼鱼反馈）
        # v127.1 每面板只抽 1 条随机提示；筛选序号警告(防卖错)仅筛选视图显示
        lines.append(self._tip("bag"))
        if category:
            lines.append("💡 筛选视图序号与全局背包不同，『出售 <序号>』按全局序号——出售/装备请用物品名称（#234）")
        return "\n".join(lines)

    @declared("item_view_mode_cmd", priority=50)
    @require_player()

    async def item_view_mode_cmd(self, event: AstrMessageEvent):
        """v105 M24 P3-4：物品查看模式开关——『物品详情开始』开启后裸数字=查看物品详情，『物品详情结束』退出。"""
        group_id, qq_id = self._uid(event)
        msg = event.get_message_str().strip()
        msg = re.sub(r"^\[At:[^\]]*\]\s*", "", msg)
        if "结束" in msg:
            db.set_event_state(f"item_view_mode:{qq_id}", "")
            yield event.plain_result("🔍 物品查看模式已关闭，回复数字不再自动查物品～")
            self._stop_event_safe(event)
            return
        db.set_event_state(f"item_view_mode:{qq_id}", "1")
        yield event.plain_result(
            "🔍 物品查看模式已开启！直接回复背包序号即可查看物品详情；\n"
            "『物品详情结束』退出，『物品详情 <名称>』照常使用。"
        )
        self._stop_event_safe(event)

    @declared("item_detail")
    @require_player()

    async def item_detail(self, event: AstrMessageEvent):
        """v105 M24 P3-4：查看物品详细信息：装备属性/材料/消耗品/宠物蛋
        v134：『查看 <名称/序号>』别名（意见#37，玩家习惯用『查看』而非『物品详情』）"""
        group_id, qq_id = self._uid(event)
        msg = event.get_message_str().strip()
        # v134 别名：『查看』前缀同样剥掉
        if msg.startswith("查看"):
            item_name = self._strip_cmd(event, "查看")
        else:
            item_name = self._strip_cmd(event, "物品详情")
        player = self._player(group_id, qq_id)
        item_name = item_name.strip()
        if not item_name:
            yield event.plain_result(
                "格式：物品详情 <名称/序号>，如『物品详情 雷霆之锤』、『查看 1』或『查看 雷霆之锤』\n"
                + self._tip("item_detail")
            )
            return
        items = db.get_inventory(group_id, qq_id)
        target = None
        equipped = False
        # v134.6 通用查看：『查看 <序号>』按 last_list 上下文路由——
        # 刚看过『技能列表』→ 数字=技能序号(技能详情)；否则=背包序号(物品详情)。
        # 与背包/技能列表的 _record_list_state 联动，改一处即可扩展更多列表。
        if item_name.isdigit():
            try:
                _lst = json.loads(db.get_event_state(f"last_list_{qq_id}") or "{}")
            except Exception:
                _lst = {}
            if _lst.get("cmd") == "技能列表":
                _msg = self._skill_detail_message(player, item_name)
                if _msg:
                    yield event.plain_result(_msg)
                    return
            # v167.1：百科装备 <部位> 列表 → 数字=该部位该页第 N 件装备详情
            _lst_cmd = _lst.get("cmd") or ""
            if _lst_cmd.startswith("百科装备 "):
                _parts_cmd = _lst_cmd.split()
                if len(_parts_cmd) >= 2:
                    _slot_map_c = {v: k for k, v in _b143.EQUIP_SLOTS.items()}
                    _slot_map_c.update({"武器": "weapon", "头盔": "helm", "帽子": "helm", "头": "helm",
                                        "胸甲": "armor", "护甲": "armor", "衣服": "armor", "衣": "armor",
                                        "护腿": "legs", "腿": "legs", "靴子": "boots", "鞋": "boots", "靴": "boots",
                                        "戒指": "ring", "戒": "ring", "项链": "necklace", "链": "necklace"})
                    _slot_c = _slot_map_c.get(_parts_cmd[1])
                    _attr_cn3 = {"str": "力量", "agi": "敏捷", "int": "智力", "vit": "耐力"}
                    if _slot_c:
                        _items_c = sorted((r for r in _cit.EQUIP_ROSTER.values() if r.get("slot") == _slot_c),
                                          key=lambda r: (r.get("lv", 0), r.get("name", "")))
                        _idx_c = int(item_name)
                        # 行号=全局序号（列表每页行号连续 1..N），直接定位
                        _pos = _idx_c - 1
                        if 0 <= _pos < len(_items_c):
                            _r = _items_c[_pos]
                            _q = _b143.QUALITY.get(_r.get("quality", "white"), {})
                            _snm = _b143.EQUIP_SLOTS.get(_r.get("slot", ""), "?")
                            _req = _r.get("req") or {}
                            _reqs = "、".join(f"{_attr_cn3.get(k, k)}{v}" for k, v in _req.items()) if _req else "无需求"
                            el = [f"⚔️ {_q.get('color', '')}【{_r['name']}】({_snm}·Lv.{_r.get('lv', '?')}·{_q.get('name', _r.get('quality'))})",
                                  "━━━━━━━━━━━━"]
                            if _r.get("series"):
                                el.append(f"系列：{_r['series']}")
                            el.append(f"需求：{_reqs}")
                            if _r.get("source"):
                                el.append(f"来源：{_r['source']}")
                            if _r.get("set"):
                                el.append(f"套装：{_r['set']}")
                            if _r.get("special"):
                                el.append(f"特效：{_r['special']}")
                            if _r.get("desc"):
                                el.append(f"{_r['desc']}")
                            yield event.plain_result("\n".join(el))
                            return
                        yield event.plain_result(f"没有第 {_idx_c} 件装备（{_parts_cmd[1]}共 {len(_items_c)} 件）！『百科装备 {_parts_cmd[1]}』看列表～")
                        return
            idx = int(item_name)
            if idx < 1 or idx > len(items):
                yield event.plain_result(f"背包里没有第 {idx} 件物品(共 {len(items)} 件)！『背包』查看全部～")
                return
            target = items[idx - 1]
        else:
            # v173.3 意见#144：部位词查询（『物品详情 项链』= 查身上穿的）优先于背包——
            # 原实现部位词检查在背包查找之后，注释说"优先"实际不优先（背包有同名项链先背包命中）。
            # 玩家意图：部位词=看身上装备；背包同名物品用『背包』列表序号或全名查。
            if not item_name.isdigit():
                _slot_map0 = {v: k for k, v in _b143.EQUIP_SLOTS.items()}
                _slot_map0.update({"武器": "weapon", "头盔": "helm", "帽子": "helm", "头": "helm",
                                   "胸甲": "armor", "护甲": "armor", "衣服": "armor", "衣": "armor",
                                   "护腿": "legs", "腿": "legs", "靴子": "boots", "鞋": "boots", "靴": "boots",
                                   "戒指": "ring", "戒": "ring", "项链": "necklace", "链": "necklace"})
                _slot_key0 = _slot_map0.get(item_name)
                if _slot_key0:
                    _worn0 = (player.get("equipment") or {}).get(_slot_key0)
                    if _worn0:
                        target = {"data": _worn0}
                        equipped = True
                    else:
                        yield event.plain_result(f"{_b143.EQUIP_SLOTS[_slot_key0]}部位未穿戴装备！『我的装备』查看穿戴情况～")
                        return
            if not target:
                # v101.28l #420：名称查找装备优先于图纸（同名图纸不再抢占命中）
                for it in items:
                    d = it["data"]
                    if item_name in d["name"] and d.get("type") != "图纸":
                        target = it
                        break
            if not target:
                for it in items:
                    d = it["data"]
                    if item_name in d["name"]:
                        target = it
                        break
        # 背包没有 → 查已装备的（仅名称查找时）
        if not target and not item_name.isdigit():
            for slot, item in (player.get("equipment") or {}).items():
                if item and item_name in item["name"]:
                    target = {"data": item}
                    equipped = True
                    break
        # v169.x 意见#88：背包/已装备都没有 → 装备名册按名查（未拥有装备图鉴预览）
        if not target and not item_name.isdigit():
            _rids = _cit.EQUIP_ROSTER_BY_NAME.get(item_name, [])
            if not _rids:
                _hit_r = [r for r in _cit.EQUIP_ROSTER.values() if item_name in r.get("name", "")]
                if len(_hit_r) == 1:
                    yield event.plain_result(_render_encyclopedia_equip(_hit_r[0]))
                    return
                if len(_hit_r) > 1:
                    fl = [f"❓ 找到 {len(_hit_r)} 件名字含『{item_name}』的装备（未拥有），用全名查询："]
                    for _i, _r in enumerate(_hit_r[:8], 1):
                        _q = _b143.QUALITY.get(_r.get("quality", "white"), {})
                        _snm = _b143.EQUIP_SLOTS.get(_r.get("slot", ""), "?")
                        fl.append(f"  {_i}. {_q.get('color', '')}【{_r['name']}】({_snm}·Lv.{_r.get('lv', '?')})")
                    fl.append("💡 『百科装备 <部位>』按部位浏览全部装备")
                    yield event.plain_result("\n".join(fl))
                    return
            else:
                _rids = _rids[:1]
            if _rids:
                yield event.plain_result(_render_encyclopedia_equip(_cit.EQUIP_ROSTER[_rids[0]]))
                return
        if not target:
            yield event.plain_result(f"背包里没有叫『{item_name}』的物品！『背包』查看全部～")
            return
        d = target["data"]
        lines = []
        # v101.6：物品类型分发数据化 → item_detail_render（加新类型 = 注册表加一行）
        item_detail_render(d, lines, equipped)
        yield event.plain_result("\n".join(lines))

    def _my_equipment_view(self, group_id, qq_id, player) -> str:
        """v134.1 意见#43：『我的装备』/『装备 状态』——当前穿戴一览（部位/名称/品质/强化/属性）。

        数据源：player.equipment（槽位 dict，值=装备对象，与 get_inventory 水合同构）。
        属性渲染复用 _render_equip 同款行式（属性每项一行）；空槽显示 未穿戴。
        """
        eq = player.get("equipment") or {}
        lines = ["⚔️ 【当前穿戴】", "━━━━━━━━━━━━"]
        worn = 0
        for slot in _b143.EQUIP_SLOTS:
            item = eq.get(slot)
            if not item:
                lines.append(f"  {_b143.EQUIP_SLOTS[slot]}：未穿戴")
                continue
            worn += 1
            q = _b143.QUALITY.get(item.get("quality", ""), {})
            enh = item.get("enhance", 0)
            enh_str = f" +{enh}" if enh > 0 else ""
            lines.append(f"  {_b143.EQUIP_SLOTS[slot]}：{q.get('color', '')}【{item.get('name', '?')}{enh_str}】{q.get('name', '')}")
            st = item.get("stats") or {}
            _stat_names = _STAT_NAMES
            for k, v in st.items():
                if v:
                    label = _stat_names.get(k, k)
                    if k in _ccore.PCT_STATS:
                        lines.append(f"      · {label} + {int(v * 100)}%")
                    else:
                        lines.append(f"      · {label} + {v}")
            for af in item.get("affixes") or []:
                if isinstance(af, dict):
                    k, v = af.get("stat"), af.get("value", 0)
                    label = _stat_names.get(k, k)
                    lines.append(f"      · {label} + {int(v * 100)}%" if k in _ccore.PCT_STATS else f"      · {label} + {v}")
                    continue
                info = _cit.AFFIXES.get(af)
                if info:
                    lines.append(f"      · {info.get('name', af)}：{info.get('desc', '')}" if info.get("desc") else f"      · {info.get('name', af)}")
        lines.append("━━━━━━━━━━━━")
        lines.append(f"已穿戴 {worn}/{len(_b143.EQUIP_SLOTS)} 件 ｜ 『装备 <序号>』换装 ｜ 『卸下 <部位>』脱下 ｜ 『物品详情 <名称>』看详情")
        return "\n".join(lines)

    def _req_check(self, player: dict, d: dict):
        """阶段八：装备属性需求检查。返回 (通过, 提示文本, 缺失属性名列表)。

        v101.21g 鱼鱼拍板：不豁免任何装备（无兼容包袱）——名册已去需求的
        旧存量快照由数据修正清理 req 字段（见 game/data/equip_roster.py:30-32，
        商店新手装不再写 req），代码层不搞特例。
        v101.25 #321：返回缺失属性名列表，调用方按实际缺失属性生成加点引导
        （不再写死『加点 力量 N』）。
        """
        req = d.get("req")
        if not req:
            return True, "", []
        attr = player.get("attributes") or {}
        names = {"str": "力量", "agi": "敏捷", "int": "智力", "vit": "耐力"}
        missing = []
        missing_keys = []
        for k, need in req.items():
            cur = attr.get(k, 0)
            if cur < need:
                missing.append(f"{names.get(k, k)} {cur}/{need}")
                missing_keys.append(k)
        if missing:
            req_str = "、".join(f"{names.get(k, k)} {v}" for k, v in req.items())
            return False, f"需求：{req_str}(你当前 {'、'.join(missing)})", missing_keys
        return True, "", []

    def _req_label(self, r: dict) -> str:
        """v181.P4-3：转发 services.shop.req_label（economy 本地定义已随迁，见 services/shop.py）"""
        return _shop_svc.req_label(r)

    def _shop_equip_price(self, slot: str, lv: int, quality: str, weapon_type: str | None = None,
                              rid: str | None = None) -> int:
        """v181.P4-3：转发 services.shop.equip_price（economy 本地定义已随迁）"""
        return _shop_svc.equip_price(slot, lv, quality, weapon_type, rid)

    def _shop_equip_roster(self, player: dict, equip_items: list) -> list:
        """v181.P4-3：转发 services.shop.equip_roster（economy 本地定义已随迁）"""
        return _shop_svc.equip_roster(player, equip_items)

    def _buy_weapon(self, wname: str, wtype: str, wlv: int, wq: str) -> dict:
        """v181.P4-3：转发 services.shop.buy_weapon（economy 本地定义已随迁）"""
        return _shop_svc.buy_weapon(wname, wtype, wlv, wq)

    @declared("my_equipment")
    @require_player()

    async def my_equipment(self, event: AstrMessageEvent):
        """v173.3 意见#167：『我的装备』查看当前穿戴一览（v134.1 意见#43 语义）——
        v172 加『装备重锻』负向断言后『我的装备』丢失入口（equip 正则只匹配『装备』开头），
        独立注册恢复。『装备 我的/状态』仍走 equip handler。"""
        group_id, qq_id = self._uid(event)
        yield event.plain_result(self._my_equipment_view(group_id, qq_id, self._player(group_id, qq_id)))

    @declared("equip")
    @require_player()

    async def equip(self, event: AstrMessageEvent):
        group_id, qq_id = self._uid(event)
        # v134.1 意见#43：『我的装备』直接命中（不走『装备 我的』绕路）
        if event.get_message_str().strip().startswith("我的装备"):
            yield event.plain_result(self._my_equipment_view(group_id, qq_id, self._player(group_id, qq_id)))
            return
        item_name = self._strip_cmd(event, "装备")
        player = self._player(group_id, qq_id)
        if self._in_battle(group_id, qq_id):
            yield event.plain_result("战斗中不能更换装备！先解决眼前的敌人吧～")
            return
        item_name = item_name.strip()
        # v134.1 意见#43：『我的装备』/『装备 状态』= 查看当前穿戴一览（与『装备 <序号>』穿戴语义不冲突）
        if item_name in ("状态", "我的", "查看", "一览", "我的装备"):
            yield event.plain_result(self._my_equipment_view(group_id, qq_id, player))
            return
        if not item_name:
            yield event.plain_result("要穿哪件？『装备 <名称>』或『装备 <背包序号>』（『背包』看序号）；『我的装备』查看当前穿戴～")
            return
        items = db.get_inventory(group_id, qq_id)
        # 找装备
        target = None
        if item_name.isdigit():
            # 序号装备：『装备 1』→ 背包第 1 件物品（须为装备，与『背包』序号一致）
            idx = int(item_name)
            if idx < 1 or idx > len(items):
                yield event.plain_result(f"背包里没有第 {idx} 件物品(共 {len(items)} 件)！『背包』查看～")
                return
            if not items[idx - 1]["data"].get("slot"):
                yield event.plain_result(f"背包第 {idx} 件『{items[idx-1]['data']['name']}』不是装备！『背包』查看～")
                return
            target = items[idx - 1]
        else:
            # 名字查找：收集所有同名/包含名字的装备，多个时提示用序号精确选择
            # v101.29.1：支持『装备 <名称> <n>』——同名多件时按清单序号指定第 n 件
            name_part, idx_part = item_name, None
            m = re.match(r"^(?P<name>.+?)\s+(?P<idx>\d+)$", item_name)
            if m and len(m.group("name")) >= 1:
                name_part, idx_part = m.group("name"), int(m.group("idx"))
            matches = []
            for it in items:
                d = it["data"]
                if d.get("slot") and (name_part in d["name"]):
                    matches.append(it)
            if len(matches) > 1 and idx_part is not None and 1 <= idx_part <= len(matches):
                # 明确指定第 n 件同名装备
                target = matches[idx_part - 1]
            elif len(matches) > 1:
                lines = [f"❓ 找到 {len(matches)} 件『{name_part}』，用序号指定穿哪件："]
                for i, it in enumerate(matches, 1):
                    d = it["data"]
                    q = _b143.QUALITY[d["quality"]]
                    enh = d.get("enhance", 0)
                    enh_str = f" +{enh}" if enh > 0 else ""
                    lines.append(f"  {i}. {q['color']}【{d['name']}{enh_str}】({_b143.EQUIP_SLOTS[d['slot']]}) Lv.{d['lv']}")
                lines.append(self._tip("equip"))
                yield event.plain_result("\n".join(lines))
                return
            if matches:
                target = matches[0]
        if not target:
            yield event.plain_result(f"背包里没有叫『{item_name}』的装备！")
            return
        d = target["data"]
        # 阶段八：武器不锁职业（20 章），改为属性需求检查（力量/智力/敏捷/耐力）
        ok_req, req_msg, miss_keys = self._req_check(player, d)
        if not ok_req:
            # v101.25 #321：按实际缺失属性生成加点引导（缺耐力引导『加点 耐力』，
            # 不再写死『加点 力量 N』误导玩家）
            first_miss = {"str": "力量", "agi": "敏捷", "int": "智力", "vit": "耐力"}.get(miss_keys[0], "力量") if miss_keys else "力量"
            yield event.plain_result(f"属性不够，穿不上【{d['name']}】！{req_msg}\n加点后属性达标才能装备(『属性』查看、『加点 {first_miss} N』加点)")
            return
        # 等级限制
        if player["level"] < d["lv"]:
            yield event.plain_result(f"需要 Lv.{d['lv']} 才能装备【{d['name']}】，你才 Lv.{player['level']}")
            return
        equipment = dict(player["equipment"])
        old = equipment.get(d["slot"])
        # v95.7 #28：无论槽位是否有旧装备都计算穿前属性——空槽穿第一件时 old 为 None，
        # 旧代码 old_stats 保持 None 导致 diff 显示"(无变化)"；title_bonus 与穿后一致
        old_stats = player_final_stats(player["class_name"], player["level"], equipment,
                                         player.get("class_tier", 0), player.get("attributes"), player.get("evolve_path", 0), self._title_bonus(group_id, qq_id), player.get("race"))
        # 卸下旧装备回背包
        if old:
            import uuid
            db.add_item(group_id, qq_id, f"eq_{uuid.uuid4().hex[:8]}", old)
        equipment[d["slot"]] = d
        db.update_player(group_id, qq_id, equipment=equipment)
        db.remove_item(group_id, qq_id, target["key"])
        q = _b143.QUALITY[d["quality"]]
        st = player_final_stats(player["class_name"], player["level"], equipment, player.get("class_tier", 0), player.get("attributes"), player.get("evolve_path", 0), self._title_bonus(group_id, qq_id), player.get("race"))
        # v16：属性变化对比（对比穿上前后的差值——旧装备属性已含在穿前快照里，
        # 即"卸下旧装备再穿上新装备"的净变化；空槽穿第一件=新装备全加成）
        diff_parts = []
        if old_stats is not None:
            keys = [("atk", "攻击"), ("def", "防御"), ("matk", "魔攻"), ("mdef", "魔防"),
                    ("spd", "速度"), ("max_hp", "生命"), ("max_mp", "魔力"), ("crit", "暴击"), ("dodge", "闪避")]
            for k, label in keys:
                diff = st[k] - old_stats[k]
                if abs(diff) >= 1e-9:
                    if k in _ccore.PCT_STATS:
                        diff_parts.append(f"{label} {'+' if diff > 0 else '-'} {abs(int(diff*100))}%")
                    else:
                        diff_parts.append(f"{label} {'+' if diff > 0 else '-'} {abs(int(diff))}")
        # v101.21b 排版：每项一行 + 两侧空格，不显示当前属性
        lines = [f"✅ 你装备了 {q['color']}【{d['name']}】！", "📊 属性变化："]
        if diff_parts:
            for p in diff_parts:
                lines.append(f"  · {p}")
        else:
            lines.append("  · (无变化)")
        yield event.plain_result("\n".join(lines))

    @declared("unequip")
    @require_player()

    async def unequip(self, event: AstrMessageEvent):
        """卸下装备回背包(v33)"""
        group_id, qq_id = self._uid(event)
        raw = self._strip_cmd(event, "卸下").strip()
        player = self._player(group_id, qq_id)
        if self._in_battle(group_id, qq_id):
            yield event.plain_result("战斗中不能更换装备！先解决眼前的敌人吧～")
            return
        equipment = dict(player["equipment"])
        # 匹配部位：中文部位名或装备名
        slot = None
        slot_by_name = {v: k for k, v in _b143.EQUIP_SLOTS.items()}
        if raw in slot_by_name:
            slot = slot_by_name[raw]
        else:
            for s, item in equipment.items():
                if item and raw and raw in item.get("name", ""):
                    slot = s
                    break
        if not slot:
            yield event.plain_result(
                f"没找到『{raw}』对应装备！用『卸下 <部位/装备名>』，如『卸下 头盔』『卸下 烈焰之刃』。\n"
                f"部位：{'、'.join(_b143.EQUIP_SLOTS.values())}"
            )
            return
        item = equipment.get(slot)
        if not item:
            yield event.plain_result(f"{_b143.EQUIP_SLOTS[slot]}位置没有装备！")
            return
        # 属性变化对比（复用 equip 逻辑；v95.7 #28：title_bonus 与卸后一致）
        old_stats = player_final_stats(player["class_name"], player["level"], equipment,
                                         player.get("class_tier", 0), player.get("attributes"), player.get("evolve_path", 0), self._title_bonus(group_id, qq_id), player.get("race"))
        import uuid
        db.add_item(group_id, qq_id, f"eq_{uuid.uuid4().hex[:8]}", item)
        equipment[slot] = None
        db.update_player(group_id, qq_id, equipment=equipment)
        st = player_final_stats(player["class_name"], player["level"], equipment, player.get("class_tier", 0), player.get("attributes"), player.get("evolve_path", 0), self._title_bonus(group_id, qq_id), player.get("race"))
        diff_parts = []
        keys = [("atk", "攻击"), ("def", "防御"), ("matk", "魔攻"), ("mdef", "魔防"),
                ("spd", "速度"), ("max_hp", "生命"), ("max_mp", "魔力"), ("crit", "暴击"), ("dodge", "闪避")]
        for k, label in keys:
            diff = st[k] - old_stats[k]
            if abs(diff) >= 1e-9:
                if k in _ccore.PCT_STATS:
                    diff_parts.append(f"{label} {'+' if diff > 0 else '-'} {abs(int(diff*100))}%")
                else:
                    diff_parts.append(f"{label} {'+' if diff > 0 else '-'} {abs(int(diff))}")
        q = _b143.QUALITY[item["quality"]]
        enh = item.get("enhance", 0)
        enh_str = f" +{enh}" if enh > 0 else ""
        # v101.21b 排版：每项一行 + 两侧空格，不显示当前属性
        lines = [f"✅ 你卸下了 {q['color']}【{item['name']}{enh_str}】({_b143.EQUIP_SLOTS[slot]})", "📊 属性变化："]
        if diff_parts:
            for p in diff_parts:
                lines.append(f"  · {p}")
        else:
            lines.append("  · (无变化)")
        yield event.plain_result("\n".join(lines))

    @declared("use")
    @require_player()

    async def use(self, event: AstrMessageEvent):
        group_id, qq_id = self._uid(event)
        item_name = self._strip_cmd(event, "使用")
        player = self._player(group_id, qq_id)
        item_name = item_name.strip()
        # v130.4 玩家意见#11：批量使用『使用 <名/序号>*<数量>』（星号）与
        #   『使用 <名/序号> <数量>』（空格）两种格式（对齐『购买』批量语义，
        #   如『使用 治疗药水*10』、『使用 2 3』）；数量校验显式报错不静默钳制。
        qty = 1
        _qty_raw = None

        def _is_qty_token(tok: str) -> bool:
            return tok.isdecimal() or (tok.startswith("-") and len(tok) > 1 and tok[1:].isdecimal())

        _it_parts = item_name.split()
        if len(_it_parts) >= 2 and _is_qty_token(_it_parts[-1]):
            _qty_raw = _it_parts[-1]
            item_name = " ".join(_it_parts[:-1])
        elif "*" in item_name:
            _head, _, _tail = item_name.rpartition("*")
            _tail = _tail.strip()
            if _is_qty_token(_tail):
                _qty_raw = _tail
                item_name = _head.strip()
            else:
                yield event.plain_result(
                    "数量格式不对！例：『使用 治疗药水*5』或『使用 治疗药水 5』；『背包』查看物品～"
                )
                return
        if _qty_raw is not None:
            try:
                qty = int(_qty_raw)
            except ValueError:
                yield event.plain_result("数量不合法！请输入正整数，如『使用 治疗药水 5』～")
                return
            if qty < 1:
                yield event.plain_result("数量至少 1 个！大批量使用用『使用 <物品> 数量』或『使用 <物品>*数量』～")
                return
        items = db.get_inventory(group_id, qq_id)
        target = None
        if item_name.isdigit():
            # 序号使用：『使用 1』→ 背包第 1 件物品（须非装备，与『背包』序号一致）
            idx = int(item_name)
            if idx < 1 or idx > len(items):
                yield event.plain_result(f"背包里没有第 {idx} 件物品(共 {len(items)} 件)！『背包』查看～")
                return
            if items[idx - 1]["data"].get("slot"):
                yield event.plain_result(f"背包第 {idx} 件是装备，用『装备 {idx}』穿上！")
                return
            target = items[idx - 1]
        else:
            target = None
            for it in items:
                d = it["data"]
                if not d.get("slot") and (item_name in d["name"]):
                    # v95r75 #380：同名材料/消耗品并存（如材料版『麦酒』mat_mai_jiu vs
                    # 消耗品版 i_ale）——优先选有效果的消耗品，否则材料版劫持『使用』
                    # 静默失效（格温 Boss 战实锤：显示"你使用了战斗道具！"但无效果不消耗）
                    if d.get("heal") or d.get("mana") or d.get("stamina") is not None or d.get("effect"):
                        target = it
                        break
                    if target is None:
                        target = it
        if not target:
            # v173.3 意见#170：『使用 <装备名>』——名称命中的是装备时给穿戴引导，
            # 原提示"背包里没有"误导（装备确实在但被 slot 排除）
            _eq_hit = [it for it in items if it["data"].get("slot") and item_name in it["data"]["name"]]
            if _eq_hit:
                _d0 = _eq_hit[0]["data"]
                yield event.plain_result(f"『{_d0['name']}』是装备，用『装备 {_d0['name']}』穿上，或『物品详情 {_d0['name']}』查看属性～")
                return
            yield event.plain_result(f"背包里没有『{item_name}』！")
            return
        d = target["data"]
        # v130.4 玩家意见#11：批量数量超过持有 → 显式报错（对齐购买超上限语义，不静默钳制）
        if qty > 1 and qty > target.get("count", 1):
            yield event.plain_result(f"你只有 {target.get('count', 1)} 个『{d['name']}』，用不了这么多～")
            return
        # ---- v97.7 道具效果模板引擎分发（消灭 if-elif 硬编码，行为与旧实现逐条对齐）----
        IT = _h('item_templates')  # ← from ..core import item_templates as IT
        tpl_name = IT.infer_template(d)
        meta = IT.META.get(tpl_name, {"battle_ok": False})
        hooks = self._item_use_hooks(group_id, qq_id, target, player)
        inst_row = self._instance_battle_for(group_id, qq_id)
        # v95r73 #352：inst_battling 只看是否在副本中，不能要求 boss 存在——
        # 层肃清后(boss=None, mode=map)仍算在副本中，若此时 inst_battling=False 会走
        # 普通战斗分支 BT.Battle.from_state + save_battle(b.to_state()) 把 leader 名下
        # 完整副本上下文覆盖成战斗引擎残缺状态 → 『深入』报"没有分层结构" 全指令死锁
        inst_battling = inst_row is not None
        if self._in_battle(group_id, qq_id) or inst_battling:
            # v130.4 玩家意见#11：战斗中一次只能使用 1 个道具（批量留战斗结束）
            if qty > 1:
                yield event.plain_result("战斗中一次只能使用 1 个道具！剩下的留到战斗结束再用～")
                return
            # 副本战斗优先（v95r55 #269 补充：队员视角——副本 battle 存队长名下，
            # _instance_battle_for 先查自己再查队长，与 combat.py 攻击/技能分流一致）
            if inst_battling:
                battle = inst_row
                if battle["state"].get("type") != "instance":
                    yield event.plain_result("你不在战斗中！")
                    return
                # v95r75 #380：层肃清后(boss=None, 地图模式)使用道具走战斗外路径——
                # 旧代码仍按战斗内处理：先执行模板+扣道具，再调 _instance_act 被
                # "当前区域的敌人已被肃清"引导 return → 道具白扣且无效果播报
                # （格温实测：治疗药水(中)×1 消失、炖菜×3→×2 均静默）
                if not battle["state"].get("boss"):
                    # R3 P2-1：副本内（层肃清/地图模式）禁用传送类卷轴——return_vila/
                    # teleport_portal 只改 cur_map 不清 instance battle（锁残留+_in_battle
                    # 悬挂，实测回城后移动/传送全被拦，须『离开副本』手动解除）
                    if tpl_name in ("return_vila", "teleport_portal"):
                        yield event.plain_result("副本内无法使用传送类卷轴！『撤退』可保留进度离开副本～")
                        return
                    ctx = IT.ItemContext(group_id, qq_id, player, d, battle=None, hooks=hooks)
                    r = IT.TEMPLATES[tpl_name](ctx)
                    # 战斗外路径模板自行扣除（tpl_heal/mana 内 ctx.hook("remove_item")），
                    # 与普通战斗外分支一致；consume=False（满血拦截等）则不扣
                    yield event.plain_result(r.text)
                    return
                # v95r75 #380：副本战斗内道具必须 battle_ok（对齐普通战斗分支）——
                # 旧代码漏检查，材料类道具（如材料版『麦酒』）被当战斗道具执行
                # none 模板 → 显示"你使用了战斗道具！"但无效果不消耗，误导玩家
                if not meta["battle_ok"]:
                    yield event.plain_result("战斗中只能使用恢复类道具或战斗药水！战斗结束才能用其他物品～")
                    return
                # 副本战斗：道具走副本轮流刻（v95.29 #269——此前漏掉 instance 分流，
                # 走普通分支会 BT.Battle.from_state + save_battle 把 leader 名下的
                # 副本上下文覆盖成战斗引擎状态，后续副本指令全 KeyError 软锁）
                # #418: 非本刻使用道具 → 先校验刻（此前模板执行+扣道具后才进
                # _instance_act 被发现刻不对，道具白扣——playtest 代码审查发现）
                st0 = battle["state"]
                _mk = st0.get("members") or []
                _ti = st0.get("turn", 0)
                _tk = str(_mk[_ti]) if _mk and _ti < len(_mk) else str(qq_id)
                if str(qq_id) != _tk:
                    _tn = (self._player(group_id, _tk) or {}).get("name", _tk)
                    yield event.plain_result(f"⏳ 现在是 {_tn} 的刻，等待 TA 行动～")
                    return
                ctx = IT.ItemContext(group_id, qq_id, player, d, battle=battle["state"], hooks=hooks)
                r = IT.TEMPLATES[tpl_name](ctx)
                if not r.consume:
                    # v104 M02 P1-5：满血/满蓝拦截——不扣道具、不消耗刻（敌方不动）
                    yield event.plain_result(r.text)
                    return
                # I5：机制型缺口（special summon/trap/... 翻译器不覆盖）→ 提示不扣道具
                _b2u_can = _h('can_translate')  # ← from .battle_item_use import can_translate as _b2u_can
                _pl0 = r.payload if r.payload is not None else "0"
                _it_cast0 = d.get("cast")
                if _it_cast0:
                    _pl0 = f"{_pl0};cast:{_it_cast0}" if _pl0 else f"cast:{_it_cast0}"
                if not _b2u_can(_pl0):
                    yield event.plain_result("⚠️ 该道具的战斗内效果尚未迁移，请在战斗外使用～")
                    return
                if r.consume:
                    db.remove_item(group_id, qq_id, target["key"])
                if d.get("stamina"):
                    self._add_stamina(group_id, qq_id, int(d["stamina"]), player)
                # v101.27 #416 延续：mana 药水回蓝统一由 _do_use_item 应用（payload="mana:N"，
                # 快照 st[players] 即 player_turn 传入的 player），模板不再直接改快照
                payload = r.payload if r.payload is not None else "0"
                # v152 数据驱动动作时长：道具 cast 内嵌 payload（_item_payload_cast 解析）
                _it_cast = d.get("cast")
                if _it_cast:
                    payload = f"{payload};cast:{_it_cast}" if payload else f"cast:{_it_cast}"
                # I3：副本战斗 use_item 走 saintess_engine router（action_override 翻译器），
                # 不再调旧 _instance_act（其 BT.from_state 对 saintess_engine state 失效——
                # 道具效果静默不生效，I 系列文档 §0.2）
                async for _r in self._instance_router(event, group_id, qq_id, player, battle["state"], "use_item", payload):
                    yield _r
                return
            # 战斗中：只允许恢复类 + 战斗药水（模板 meta battle_ok），且算一刻（敌方会行动）
            if not meta["battle_ok"]:
                yield event.plain_result("战斗中只能使用恢复类道具或战斗药水！战斗结束才能用其他物品～")
                return
            battle = db.get_battle(group_id, qq_id)
            if not battle:
                yield event.plain_result("你不在战斗中！")
                return
            if battle["state"].get("type") == "pvp":
                yield event.plain_result("PVP 战斗无法使用道具！")
                return
            b = self._restore_battle(battle["state"])
            if b is None:
                # 旧格式存档作废：清档重开（N5b 约定不迁移）
                db.clear_battle(group_id, qq_id)
                self._unlock_battle(group_id, qq_id)
                yield event.plain_result("⏳ 旧存档已失效，重新探索开始新的战斗吧！")
                return
            # I4：from_state 后注入道具行动回调（action_override 不可序列化）
            try:
                make_override = _h('make_override')  # ← from .battle_item_use import make_override
                b.action_override = make_override()
            except Exception:
                b.action_override = None
            ctx = IT.ItemContext(group_id, qq_id, player, d, battle=battle["state"], hooks=hooks)
            r = IT.TEMPLATES[tpl_name](ctx)
            if not r.consume:
                # v104 M02 P1-5：满血/满蓝拦截——不扣道具、不消耗刻（敌方不动）
                yield event.plain_result(r.text)
                return
            # I5：机制型缺口（special summon/trap/... 翻译器不覆盖）→ 提示不扣道具
            _b2u_can = _h('can_translate')  # ← from .battle_item_use import can_translate as _b2u_can
            _pl0 = r.payload if r.payload is not None else "0"
            _it_cast0 = d.get("cast")
            if _it_cast0:
                _pl0 = f"{_pl0};cast:{_it_cast0}" if _pl0 else f"cast:{_it_cast0}"
            if not _b2u_can(_pl0):
                yield event.plain_result("⚠️ 该道具的战斗内效果尚未迁移，请在战斗外使用～")
                return
            if r.consume:
                db.remove_item(group_id, qq_id, target["key"])
            # v94 体力：战斗中使用食物恢复体力（不占刻结算显示）
            st_msg = ""
            if d.get("stamina"):
                st_gain = self._add_stamina(group_id, qq_id, int(d["stamina"]), player)
                if st_gain > 0:
                    st_msg = f"⚡ 恢复 {st_gain} 点体力({self._stamina(player)}/{self._stamina_max(player)})\n"
            # 战斗内 mana 由模板算 payload（"mana:N"/"hm:hp,mp"）交 battle.player_turn
            # 的 _do_use_item 应用（v101.27/v104R3 M16 P2-3），模板不再直接改快照
            payload = r.payload if r.payload is not None else "0"
            # v152 数据驱动动作时长：道具 cast 内嵌 payload（_item_payload_cast 解析）
            _it_cast = d.get("cast")
            if _it_cast:
                payload = f"{payload};cast:{_it_cast}" if payload else f"cast:{_it_cast}"
            # saintess_engine 玩家 actor 定位（saintess_engine 引擎只吃 actor dict；sides player 首 actor）
            _my = b.focus() if hasattr(b, "focus") else None
            if _my is None:
                for _a in b.sides_of("player"):
                    if str(_a.get("qq_id") or "") == str(qq_id):
                        _my = _a
                        break
            if _my is None:
                yield event.plain_result("你不在战斗中（状态异常）！")
                return
            logs, ended, _who = b.human_act("use_item", payload, _my)
            # saintess_engine 行动后回写 player dict（副本 actor 改动不自动落回）
            try:
                sync_player_from_actor = _h('sync_player_from_actor')  # ← from ..services.battle_bridge import sync_player_from_actor
                sync_player_from_actor(player, _my)
            except Exception:
                pass
            db.update_player(group_id, qq_id, hp=player["hp"], mp=player["mp"],
                             max_hp=player["max_hp"], max_mp=player["max_mp"])
            if ended:
                # saintess_engine 胜负按 actor 存活判定（结果视角固定 player side）
                _enemies = [u for u in b.sides_of("enemy") if (u.get("hp") or 0) > 0]
                _mon = _enemies[0] if _enemies else (b.sides_of("enemy") or [{}])[0]
                if b.result == "victory":
                    # v126.7 胜利结算用原主怪引用（死亡不移除，读 sides 存活/首怪）
                    for _r in self._handle_victory(event, group_id, qq_id, player, _mon, "\n".join(logs)):
                        yield _r
                    return
                if b.result == "defeat":
                    for _r in self._handle_defeat(event, group_id, qq_id, player, _mon, "\n".join(logs)):
                        yield _r
                    return
            db.save_battle(group_id, qq_id, b.to_state())
            log_str = "\n".join(logs)
            # v95.16 #76：满血时吃食物显示"恢复 0 点生命"误导——有体力恢复时改为体力为主文案
            if "恢复 0 点生命" in log_str and st_msg:
                log_str = log_str.replace("💊 你使用了战斗道具，恢复 0 点生命！", "🍖 你吃下了食物，恢复了体力！")
            yield event.plain_result(
                f"{log_str}\n{st_msg}━━━━━━━━━━━━\n"
                f"❤️ HP {player['hp']}/{player['max_hp']}  💙 MP {player['mp']}/{player['max_mp']}\n"
                f"你的行动：『攻击』『技能 <名称>』『防御』『逃跑』"
            )
            return
        # 战斗外：模板直接执行副作用并返回展示文本
        # v130.4 玩家意见#11：支持批量循环（『使用 <名> <数量>』/『使用 <名>*<数量>』）；
        # 每次重读 player（模板已落库 HP/MP），满血/满蓝拦截 (consume=False) 即停止。
        use_count = 0
        _parts = []
        _fat_line = ""
        _use_q_line = ""
        for _k in range(qty):
            _p_cur = self._player(group_id, qq_id) if _k else player
            ctx = IT.ItemContext(group_id, qq_id, _p_cur, d, battle=None, hooks=hooks)
            r = IT.TEMPLATES[tpl_name](ctx)
            if r.consume:
                use_count += 1
                _parts.append(r.text)
            else:
                # 满血/满蓝拦截提示也展示（首轮或中途停止都让玩家看到原因）
                if _k == 0 or use_count > 0:
                    _parts.append(r.text)
                # v105R3 M13 P2-8：吃料理解除挖掘疲劳（19 章 §2.2 第二条恢复途径）——
                # 食用含体力/持续效果的食物且实际消耗成功时，清除疲劳计数（批量仅首轮判定）
                # v124 use 目标支线：使用物品后推进 use objective（如 递麦酒/用月鳞/交信物）。
                # v124.2 条件放宽：none 模板=使用动作成立（含收藏品等，如 s74 商会股份凭证），
                # 按名精确匹配 active use 目标即推进，无匹配空操作无副作用；任务道具 tpl_none
                # consume=False 不消耗语义不变；满血拦截等 consume=False 走 heal 等模板不受影响。
                if tpl_name == "none" and _k == 0:
                    if d.get("stamina") or d.get("food_effect"):
                        _fst = self._mining_fatigue_state(group_id, qq_id)
                        if _fst and int(time.time()) - _fst.get("ts", 0) <= _prof_svc.MINING_FATIGUE_RECOVER:
                            db.set_event_state(f"mining_fatigue_{qq_id}", "")
                            _fat_line = "\n🍖 吃饱喝足，疲劳一扫而空！(挖掘稀有矿脉概率恢复)"
                    _use_q_line = self._update_use_quests(group_id, qq_id, d.get("name", ""))
                break
            if use_count == 1:
                # v105R3 M13 P2-8：吃料理解除挖掘疲劳（19 章 §2.2 第二条恢复途径）——
                # 食用含体力/持续效果的食物且实际消耗成功时，清除疲劳计数（批量仅首轮判定）
                if d.get("stamina") or d.get("food_effect"):
                    _fst = self._mining_fatigue_state(group_id, qq_id)
                    if _fst and int(time.time()) - _fst.get("ts", 0) <= _prof_svc.MINING_FATIGUE_RECOVER:
                        db.set_event_state(f"mining_fatigue_{qq_id}", "")
                        _fat_line = "\n🍖 吃饱喝足，疲劳一扫而空！(挖掘稀有矿脉概率恢复)"
                # v124 use 目标支线：批量只推进一次
                _use_q_line = self._update_use_quests(group_id, qq_id, d.get("name", ""))
        _text = "\n".join(_parts)
        if qty > 1 and use_count > 0:
            if use_count == qty:
                _text += f"\n━━━━━━━━━━━━\n✅ 已使用 {use_count} 个『{d.get('name')}』"
            else:
                _text += f"\n━━━━━━━━━━━━\n✅ 已使用 {use_count}/{qty} 个『{d.get('name')}』（状态已满，剩余保留）"
        yield event.plain_result(_text + _fat_line + _use_q_line)

    def _item_use_hooks(self, group_id, qq_id, target, player):
        """v97.7：道具模板引擎的命令层回调（体力/回城/红名等专属逻辑注入）。"""
        d = target["data"]

        def rm():
            db.remove_item(group_id, qq_id, target["key"])

        def stamina_msg(gid, qid, p):
            if not d.get("stamina"):
                return ""
            st_gain = self._add_stamina(gid, qid, int(d["stamina"]), p)
            if st_gain > 0:
                _p3 = self._player(gid, qid)
                return f"\n⚡ 恢复 {st_gain} 点体力({self._stamina(_p3)}/{self._stamina_max(_p3)})"
            return ""

        return {
            "remove_item": rm,
            "add_stamina": self._add_stamina,
            "stamina_msg": stamina_msg,
            "get_player": lambda: self._player(group_id, qq_id),
            "stamina_cur": self._stamina,
            "stamina_max": self._stamina_max,
            "nearest_town": self._nearest_town,
            "is_redname": self._is_redname,
        }

    def _cur_subarea(self, player: dict) -> dict:
        """v181.P4-3：转发 services.shop.cur_subarea（economy 本地定义已随迁）"""
        return _shop_svc.cur_subarea(player)

    def _is_smith_shop(self, player: dict) -> bool:
        """v181.P4-3：转发 services.shop.is_smith_shop（economy 本地定义已随迁）"""
        return _shop_svc.is_smith_shop(player)

    def _item_fits_shop(self, it: dict, sa_kind: str | None) -> bool:
        """v101.25h 消耗品是否适合当前子区域类型出售：
        herb（草药/炼金）→ 只卖药剂类；
        tavern（酒馆/旅店）→ 只卖食物类；
        general（普通商店/集市/商行）→ 卷轴/杂物类；
        smith/None（行商货摊等）→ 全量。
        """
        if sa_kind not in ("herb", "tavern", "general"):
            return True
        name = it.get("name", "")
        kind = "food"
        # 食物判据：有 stamina 或典型食物词
        if it.get("stamina") or any(k in name for k in ("面包", "肉", "酒", "果", "炖", "盛宴", "果冻", "汤", "饼")):
            kind = "food"
        elif any(k in name for k in ("药水", "药剂", "圣水", "草药", "绷带", "露", "泪", "卷轴", "护符")):
            kind = "potion" if "卷轴" not in name and "护符" not in name else "scroll"
        else:
            kind = "misc"
        if sa_kind == "herb":
            return kind == "potion"
        if sa_kind == "tavern":
            return kind == "food"
        # general：卷轴/杂物（+武器走独立分支）
        return kind in ("scroll", "misc")

    def _pawn_rate(self, player: dict, d: dict):
        """v181.P4-3：转发 services.shop.pawn_rate（economy 本地定义已随迁，含 F1 P1-5 消耗品 0.85 档）"""
        return _shop_svc.pawn_rate(player, d,
                                   is_smith_shop_=self._is_smith_shop,
                                   at_shop=self._at_shop)

    def _is_quest_item(self, d: dict) -> bool:
        """v181.P4-3：转发 services.shop.is_quest_item（economy 本地定义已随迁）"""
        return _shop_svc.is_quest_item(d)

    def _fish_weight_max(self, d: dict):
        """v181.P4-3：转发 services.shop.fish_weight_max（economy 本地定义已随迁）"""
        return _shop_svc.fish_weight_max(d)

    def _sell_one(self, group_id, qq_id, player, it, rate):
        """v181.P4-3：转发 services.shop.sell_one（economy 本地定义已随迁，F1 P0-2 原子出售）"""
        return _shop_svc.sell_one(group_id, qq_id, player, it, rate,
                                  is_smith_shop_=self._is_smith_shop,
                                  at_shop=self._at_shop)

    def _apprentice_protect_mats(self, group_id, qq_id) -> dict:
        """v181.P4-3：转发 services.shop.apprentice_protect_mats（economy 本地定义已随迁）"""
        return _shop_svc.apprentice_protect_mats(group_id, qq_id)

    @declared("sell")
    @require_player()

    async def sell(self, event: AstrMessageEvent):
        group_id, qq_id = self._uid(event)
        item_name = self._strip_cmd(event, "出售")
        player = self._player(group_id, qq_id)
        item_name = item_name.strip()
        items = db.get_inventory(group_id, qq_id)
        # 批量出售模式：『出售 全部』/『出售 材料』/『出售 装备』
        if item_name in ("全部", "所有", "全部物品"):
            mode = "all"
        elif item_name in ("材料", "材料 全部", "全部材料"):
            mode = "mat"
        elif item_name in ("装备", "装备 全部", "全部装备"):
            mode = "equip"
        else:
            mode = None
        # v134.1 玩家意见#40：批量出售指定数量『出售 <名>*<数量>』/『出售 <名> <数量>』
        # （对齐『购买/使用』批量语义；超持有/0/负显式报错不静默钳制）
        qty = 1
        _qty_raw = None
        if not mode:

            def _is_qty_token(tok: str) -> bool:
                return tok.isdecimal() or (tok.startswith("-") and len(tok) > 1 and tok[1:].isdecimal())

            _parts = item_name.split()
            if len(_parts) >= 2 and _is_qty_token(_parts[-1]):
                _qty_raw = _parts[-1]
                item_name = " ".join(_parts[:-1])
            elif "*" in item_name:
                _head, _, _tail = item_name.rpartition("*")
                _tail = _tail.strip()
                if _is_qty_token(_tail):
                    _qty_raw = _tail
                    item_name = _head.strip()
                else:
                    yield event.plain_result(
                        "数量格式不对！例：『出售 狼皮*5』或『出售 狼皮 5』；『背包』查看物品～"
                    )
                    return
        if _qty_raw is not None:
            try:
                qty = int(_qty_raw)
            except ValueError:
                yield event.plain_result("数量不合法！请输入正整数，如『出售 狼皮 5』～")
                return
            if qty < 1:
                yield event.plain_result("数量至少 1 个！大批量出售用『出售 <物品> 数量』或『出售 <物品>*数量』～")
                return
        if mode:
            # v134.1 意见#40：『出售 全部 N』/『出售 材料 N』等批量模式不支持数量参数（批量=全清语义）
            if qty > 1:
                yield event.plain_result("『出售 全部/材料/装备』是批量模式，不支持数量；指定数量请用『出售 <物品> <数量>』～")
                return
            blocked = 0
            total = 0
            sold = []
            # v101.25 #305：拜师考验材料保护——批量出售跳过考验所需材料
            protect = self._apprentice_protect_mats(group_id, qq_id)
            protected = []
            # v104 M08 P1-1：任务道具保护——批量出售一律跳过（烬火信标被卖后
            # 主线交付卡死；星尘沙漏/灰烬之核等是隐藏套锻造核心，卖了造不了）
            # v104 M08 P0-1：判据双保险——背包 data.type 可能被发放路径写死为"材料"，
            # 按名查 MATERIALS_BY_NAME 定义兜底（历史错误数据也能拦住）
            quest_protected = []
            for it in items:
                d = it["data"]
                if self._is_quest_item(d):
                    quest_protected.append(f"{d['name']}×{it['count']}")
                    continue
                if mode == "mat" and d.get("type", "") != "材料":
                    continue
                if mode == "equip" and not d.get("slot"):
                    continue
                if protect and d.get("name") in protect:
                    protected.append(f"{d['name']}×{it['count']}")
                    continue
                rate = self._pawn_rate(player, d)
                if rate is None:
                    blocked += 1
                    continue
                r = self._sell_one(group_id, qq_id, player, it, rate)
                if r:
                    sold.append(f"{r[0]} ×{r[1]}（{r[2]} 金）")
                    total += r[2]
                    player = self._player(group_id, qq_id)
            if not sold:
                # q7-8：完整品类分店提示（装备→铁匠铺；材料见 _MAT_FACILITY_HINT）
                tip = f"（装备要去铁匠铺；{_MAT_FACILITY_HINT}）" if blocked else ""
                if quest_protected:
                    tip += f"；{'、'.join(quest_protected)} 是任务道具，已帮你留着"
                if protected:
                    tip += f"；{ '、'.join(protected) } 是拜师考验材料，已帮你留着"
                yield event.plain_result(f"没有可出售的物品！{tip}")
                return
            head = "全部" if mode == "all" else ("材料" if mode == "mat" else "装备")
            lines = [f"💰 批量出售{head}完成，共 {len(sold)} 种物品，获得 {total} 金币！"]
            for s in sold[:8]:
                lines.append(f"  · {s}")
            if len(sold) > 8:
                lines.append(f"  · ……等 {len(sold)} 种")
            if blocked:
                # q7-8：完整品类分店提示（装备→铁匠铺；材料见 _MAT_FACILITY_HINT）
                lines.append(f"💡 有 {blocked} 种物品要对应店铺出售（装备要去铁匠铺；{_MAT_FACILITY_HINT}）～")
            if quest_protected:
                lines.append(f"🛡️ 已跳过 { '、'.join(quest_protected) }（任务道具，主线/隐藏任务要用）")
            if protected:
                lines.append(f"🛡️ 已跳过 { '、'.join(protected) }（拜师考验材料，导师要验收）")
            yield event.plain_result("\n".join(lines))
            return
        target = None
        # v134.1 意见#40：空格数量格式『出售 <名称> <数量>』——数量 token 已在 qty 解析阶段从
        # item_name 剥离（『出售 狼皮 5』→ item_name='狼皮'），此处 item_name 已是纯名称/序号
        if item_name.isdigit():
            # 序号出售：『出售 1』→ 背包第 1 件物品（与『背包』序号一致）
            idx = int(item_name)
            if idx < 1 or idx > len(items):
                yield event.plain_result(f"背包里没有第 {idx} 件物品（共 {len(items)} 件）！『背包』查看～")
                return
            target = items[idx - 1]
        else:
            # v101.25 #306：精确名优先——『出售 狼皮』不再被"星狼皮"抢跑
            # （playtest round68 抓包：模糊匹配先卖星狼皮）。精确名无 → 模糊收集
            # 候选，多个时列出让玩家精确选择。
            # v101.29.1：支持『出售 <名称> <n>』——同名多件时按清单序号指定第 n 件
            name_part, idx_part = item_name, None
            m = re.match(r"^(?P<name>.+?)\s+(?P<idx>\d+)$", item_name)
            if m and len(m.group("name")) >= 1:
                name_part, idx_part = m.group("name"), int(m.group("idx"))
            # v104 M09 P2 修复：精确同名多件时支持『出售 <名称> <序号>』（原精确分支忽略 idx，
            #   两件同名迷雾兜帽『出售 迷雾兜帽 2』会卖成第 1 件；与装备命令 idx 处理对齐）
            # v134.1 意见#40：空格数量格式『出售 <名称> <数量>』优先于序号格式——数量剥离发生在
            #   精确名查找之前（见上方 qty 解析），到达此处时 item_name 已只剩纯名称，
            #   idx_part 仅当『出售 <名称> <序号>』（未带数量）时才有值；若同时指定了数量，
            #   后面两个空格 token 是数量，不会误进此分支（数量 token 已被 qty 解析吞掉）
            exact = [it for it in items if it["data"]["name"] == name_part]
            if exact:
                if len(exact) > 1 and idx_part is not None:
                    if 1 <= idx_part <= len(exact):
                        # v134.1 意见#40：同名多件 + 数量 → 数量优先（『出售 迷雾兜帽 2 5』=卖第 2 件×5）
                        target = exact[idx_part - 1]
                        if qty > 1:
                            idx_part = None
                    else:
                        yield event.plain_result(f"『{name_part}』只有 {len(exact)} 件，没有第 {idx_part} 件！『背包』查看序号～")
                        return
                else:
                    target = exact[0]
            if not target:
                fuzzy = [it for it in items if name_part in it["data"]["name"]]
                if len(fuzzy) > 1 and idx_part is not None and 1 <= idx_part <= len(fuzzy):
                    target = fuzzy[idx_part - 1]
                elif len(fuzzy) > 1:
                    flines = [f"❓ 找到 {len(fuzzy)} 件名字含『{name_part}』的物品，用全名指定卖哪件："]
                    for i, it in enumerate(fuzzy, 1):
                        fd = it["data"]
                        fq = _b143.QUALITY[fd["quality"]] if fd.get("quality") and fd.get("slot") else None
                        fname_s = f"{fq['color']}【{fd['name']}】" if fq else fd["name"]
                        flines.append(f"  {i}. {fname_s} ×{it['count']}（出售价 {self._pawn_rate(player, fd) or '需对应店铺'}）")
                    flines.append(self._tip("sell"))
                    yield event.plain_result("\n".join(flines))
                    return
                if len(fuzzy) == 1:
                    target = fuzzy[0]
        if not target:
            yield event.plain_result(f"背包里没有『{item_name}』！")
            return
        d = target["data"]
        # v104 M08 P2-2：单件出售同样拦截任务道具（『出售 烬火信标』此前走
        # MATERIALS_BY_NAME type=任务道具 → _MAT_FACILITY=shop → 0.8 折卖掉卡 H7）
        if self._is_quest_item(d):
            yield event.plain_result(f"『{d['name']}』是任务道具，主线/隐藏任务要用，不能出售！")
            return
        # v134.1 意见#40：指定数量超持有 → 显式报错（对齐『使用』批量语义，不静默钳制）
        if qty > 1 and qty > target.get("count", 1):
            yield event.plain_result(f"你只有 {target.get('count', 1)} 个『{d['name']}』，卖不了这么多～")
            return
        rate = self._pawn_rate(player, d)
        if rate is None:
            if d.get("slot"):
                hint = self._facility_hint(player, "craft")
                yield event.plain_result(
                    f"『{d['name']}』是装备，要到铁匠铺（锻造台）才能回收成金币～"
                    + (f"({hint})" if hint else "")
                )
            else:
                _mm = _cit.MATERIALS_BY_NAME.get(d.get("name", "")) or {}
                _need = _MAT_FACILITY.get(_mm.get("type", "杂物"), "shop")
                _hint_map = {"smith": "铁匠铺（矿石/兽材/木材/宝石）", "alchemy": "草药铺/炼金工坊（草药/精华）", "shop": "商店（食材/织物/杂物）"}
                # q7-8：单件提示到具体柜台，并附完整分店品类说明帮新手不跑错柜台（纯文案）
                yield event.plain_result(
                    f"『{d['name']}』是材料，要到{_hint_map.get(_need, '对应店铺')}才能回收成金币～\n"
                    f"💡 {_MAT_FACILITY_HINT}。"
                )
            return
        # v134.1 意见#40：指定数量出售——复用 _sell_one 全部计价逻辑（品质折价/锻造回本/鱼重/坐骑加成），
        #   仅把出售份数限定为 qty（sell_item_atomic 按 count 原子扣包，剩余自动保留）；
        #   必须先于单件 _sell_one 调用（否则先全卖再补扣，背包空后 sell_item_atomic 静默失败）
        if qty > 1:
            it2 = dict(target)
            it2["count"] = qty
            r2 = self._sell_one(group_id, qq_id, player, it2, rate)
            if not r2:
                yield event.plain_result(f"『{d['name']}』不能出售。")
                return
            name, cnt, gold = r2
            yield event.plain_result(f"💰 你出售了 {name} ×{cnt}，获得 {gold} 金币！（回收价 {int(rate * 100)}%）")
            return
        r = self._sell_one(group_id, qq_id, player, target, rate)
        if not r:
            yield event.plain_result(f"『{d['name']}』不能出售。")
            return
        name, cnt, gold = r
        # v105 M09 P3-10：100% 原价回收也提示（此前 rate>=1.0 静默，玩家不知药水零损耗规则）
        tip = f"（回收价 {int(rate * 100)}%）"
        yield event.plain_result(f"💰 你出售了 {name} ×{cnt}，获得 {gold} 金币！{tip}")

    @declared("shop")
    @require_player()

    async def shop(self, event: AstrMessageEvent):
        group_id, qq_id = self._uid(event)
        player = self._player(group_id, qq_id)
        if self._is_redname(qq_id):
            yield event.plain_result("☠️ 你是红名！商店老板把你轰了出来……（等红名消退再来）")
            return
        cur = player["cur_map"]
        cur_map = _cspace.MAP_BY_ID.get(cur, {})
        if not self._at_shop(player, group_id, qq_id):
            hint = self._facility_hint(player, "shop")
            yield event.plain_result(
                f"这里没有商店！到有商店的地方（如 {hint}）再输入『商店』吧～" if hint else "这里没有商店！去城镇里找找商铺吧～"
            )
            return
        area_id = cur_map.get("area", cur)
        is_smith = self._is_smith_shop(player)
        # v130.7 意见#23：sa_kind 提到函数级（铁匠分支原不计算该变量；坐骑块/武器块共用）
        sa_kind = self._sa_shop_kind(player)
        subarea = self._cur_subarea(player)
        shop_title = (subarea.get("name") or cur_map.get("name") or cur)
        lines = []
        entries = []

        # v101.30d #O41/O34：商店已拥有标注（playtest 5 角色复现重复购买）
        def _owned(name):
            n = db.count_item(group_id, qq_id, name)
            for _d in (player.get("equipment") or {}).values():
                if _d and _d.get("name") == name:
                    n += 1
            # v104 M09 P2 修复：已拥有统计含家中仓库（此前仓库存货不计数，玩家可能重复囤货）
            try:
                _hs = json.loads(db.get_event_state(f"home_storage_{group_id}_{qq_id}") or "[]")
                for _it in _hs:
                    if (_it.get("data") or {}).get("name") == name:
                        n += _it.get("count", 1)
            except (ValueError, TypeError):
                pass
            return f"（已拥有 ×{n}）" if n else ""

        if is_smith:
            # 铁匠类商店：武器 + 锻造材料 + 全套装备 + 图纸（v101.25h 追加子区域军需补给如强化石）
            sa_id = player.get("cur_subarea") or ""
            sa_items = _clife.SHOP_SUBAREA_ITEMS.get(sa_id)
            for iid in sa_items or []:
                it = _cit.ITEMS[iid]
                _lim = self._shop_limit_label(sa_id, f"item:{iid}")  # v166 限购标注
                entries.append((iid, f"{it['name']}{_owned(it['name'])} —— {it['price']} 金币（{it['desc']}）{_lim}"))
            materials = _clife.SHOP_SMITH_MATERIALS.get(cur) or _clife.SHOP_SMITH_MATERIALS.get(area_id, [])
            for mid in materials:
                mt = _cit.MATERIALS[mid]
                _lim = self._shop_limit_label(sa_id, f"mat:{mid}")  # v166 限购标注
                entries.append((mid, f"{mt['name']}{_owned(mt['name'])} —— {mt['price']} 金币（锻造材料）{_lim}"))
            # v94 图纸经济：铁匠铺兜底卖图纸（随机一张，价格 = 图纸价×3 = (lv×3+20)×3）
            bp_price = int((max(1, player["level"]) * _clife.ECON_CONFIG["bp_price_per_lv"]
                            + _clife.ECON_CONFIG["bp_price_base"]) * _clife.ECON_CONFIG["bp_smith_mult"])
            entries.append(("bp:rand", f"📜 神秘锻造图纸（随机一张）—— {bp_price} 金币"))
            equip_items = self._shop_equip_roster(player, _clife.SHOP_EQUIP.get(cur) or _clife.SHOP_EQUIP.get(area_id, []))
            for rid in equip_items:
                r = _cit.EQUIP_ROSTER[rid]
                q = _b143.QUALITY[r["quality"]]
                _lim = self._shop_limit_label(sa_id, f"equip:{rid}")  # v166 限购标注
                entries.append((f"e:{rid}", f"{q['color']}{r['name']}{_owned(r['name'])}（{_b143.EQUIP_SLOTS[r['slot']]}）Lv.{r['lv']}{' · ' + self._req_label(r) if self._req_label(r) else ''} —— {self._shop_equip_price(r['slot'], r['lv'], r['quality'], r.get('weapon_type'), rid)} 金币{_lim}"))
            weapons = _clife.SHOP_WEAPONS.get(cur) or _clife.SHOP_WEAPONS.get(area_id, [])
            for wname, wtype, wlv, wq in weapons:
                q = _b143.QUALITY[wq]
                _ids = _cit.EQUIP_ROSTER_BY_NAME.get(wname, [])
                _r = _cit.EQUIP_ROSTER.get(_ids[0], {}) if _ids else {}
                # v104 M09 P2 修复：非名册武器需求按 random_req 确定性推导标注（与 _buy_weapon 生成同源）
                if not _r:
                    _r = {"req": C.random_req("weapon", wlv, wtype)}
                _lim = self._shop_limit_label(sa_id, f"weapon:{wname}")  # v166 限购标注
                entries.append((f"w:{wname}", f"{q['color']}{wname}{_owned(wname)}（{C.display('weapon_types', wtype)}）Lv.{wlv}{' · ' + self._req_label(_r) if self._req_label(_r) else ''} —— {self._shop_equip_price('weapon', wlv, wq, wtype)} 金币{_lim}"))
            # v135 铁匠铺货架（全服共享，NPC 作品）：2 武器 + 1 防具 + 1 饰品，每日 0 点换货 + 6h 补货
            town_lv = _ss.town_level(cur)
            smith_items = _ss.get_smith_stock(cur, town_lv)
            _npc = _ss.SMITH_NPC_NAMES.get(cur, "铁匠")
            for _sit in smith_items:
                _rid = _sit["rid"]
                _r = _cit.EQUIP_ROSTER[_rid]
                _q = _b143.QUALITY[_r["quality"]]
                _sl = _r["slot"]
                _slot_cn = _b143.EQUIP_SLOTS[_sl] if _sl in _b143.EQUIP_SLOTS else (C.display('weapon_types', _r.get('weapon_type')) or _sl)
                _n = f"{_r['name']}（{_npc}的作品）"
                _price = int(_ss.smith_stock_price(_rid, _sit["price_mult"]))
                entries.append((f"s:{_rid}", f"{_q['color']}{_n}{_owned(_r['name'])}（{_slot_cn}）Lv.{_r['lv']}{' · ' + self._req_label(_r) if self._req_label(_r) else ''} ×{_sit['qty']} —— {_price} 金币"))
        else:
            # 普通商店：消耗品 + 武器（v101.28g：只挂子区域配货，无城镇级兜底）
            sa_kind = self._sa_shop_kind(player)
            sa_id = player.get("cur_subarea") or ""
            sa_items = _clife.SHOP_SUBAREA_ITEMS.get(sa_id)
            shop_items = sa_items if sa_items is not None else []
            trader = self._wild_trader_here(player, group_id, qq_id)
            if not shop_items and trader:
                shop_items = _clife.SHOP_WILD_TRADE  # v95.4：野外行商货物
                tname = _cquest.WILD_NPCS.get(trader, {}).get("name", "行商")
                shop_title = f"🧭 {tname}的货摊"  # #151：标题跟随实际在场的交易 NPC
            # 意见#130（2026-09-03 白云白云狸雾理云/鱼神）：铁港码头栈桥(harbor_docks_1)挂着
            # 行商(NPC 夜钓翁·老竿 map=harbor_docks 整图 roam)，本子区域没有商店也没有货摊，
            # 却在『地图』里被 _wild_trader_here 判定为可交易 → 显示错配的「行商货摊」。
            # 修复：交易放行条件收紧为「当前子区域是无 shop 的野外落点 OR 在场限时 NPC 事件已触发」
            # （限时事件 = 探索偶遇后 set_timed 的 wild:{nid}，见 roll_wild_encounter；
            #  _wild_trader_here 原本只按 NPC 静态 map 判定，夜钓翁 map=harbor_docks 全图放行）。
            _here_trader_ok = False
            if trader:
                _tr_npc = _wild.ALL_WILD.get(trader, {})
                _tr_roam = _tr_npc.get("roam")
                _tr_timed = bool(C.get_timed(group_id, qq_id, f"wild:{trader}"))
                # 无 roam 的 NPC 若 map 命中当前整图但未偶遇（无线时事件）→ 不在场，不显示行商
                _here_trader_ok = bool(_tr_timed) if not _tr_roam else True
            if not shop_items and _here_trader_ok:
                shop_items = _clife.SHOP_WILD_TRADE  # v95.4：野外行商货物
                tname = _cquest.WILD_NPCS.get(trader, {}).get("name", "行商")
                shop_title = f"🧭 {tname}的货摊"  # #151：标题跟随实际在场的交易 NPC
            for iid in shop_items:
                it = _cit.ITEMS[iid]
                _lim = self._shop_limit_label(sa_id, f"item:{iid}")  # v166 限购标注
                entries.append((iid, f"{it['name']}{_owned(it['name'])} —— {it['price']} 金币（{it['desc']}）{_lim}"))
            # 武器：铁匠/锻造类 + 普通商店（集市/商行/码头）可卖；草药铺/酒馆不卖
            if sa_kind in ("smith", "general"):
                weapons = _clife.SHOP_WEAPONS.get(cur) or _clife.SHOP_WEAPONS.get(area_id, [])
                for wname, wtype, wlv, wq in weapons:
                    q = _b143.QUALITY[wq]
                    _ids = _cit.EQUIP_ROSTER_BY_NAME.get(wname, [])
                    _r = _cit.EQUIP_ROSTER.get(_ids[0], {}) if _ids else {}
                    # v104 M09 P2 修复：非名册武器需求按 random_req 确定性推导标注（与 _buy_weapon 生成同源）
                    if not _r:
                        _r = {"req": C.random_req("weapon", wlv, wtype)}
                    _lim = self._shop_limit_label(sa_id, f"weapon:{wname}")  # v166 限购标注
                    entries.append((f"w:{wname}", f"{q['color']}{wname}{_owned(wname)}（{C.display('weapon_types', wtype)}）Lv.{wlv}{' · ' + self._req_label(_r) if self._req_label(_r) else ''} —— {self._shop_equip_price('weapon', wlv, wq, wtype)} 金币{_lim}"))
        # v104 修 M17-P2：橡木镇（新手村）商店面板列出可购坐骑（price>0 的老马/小毛驴），并入序号购买
        # v130.7 意见#23：坐骑只挂 smith/general 贸易场所（草药铺 herb/酒馆 tavern 不再隔空卖坐骑，口径同武器块）
        if area_id == "oak" and cur == _ccore.START_MAP and sa_kind in ("smith", "general"):
            _mount_owned = set((player.get("mounts") or {}).get("owned") or [])
            for mdef in _clife.MOUNT_POOL:
                if (mdef.get("price") or 0) > 0:
                    _mo = "（已拥有）" if mdef["key"] in _mount_owned else ""
                    entries.append((f"mount:{mdef['key']}",
                                    f"{mdef['icon']}{mdef['name']}{_mo}（坐骑 Lv.{mdef['lv']} 商店直购）—— {mdef['price']} 金币"))
        # v104 M09 P2 修复：世界事件商店折扣期面板标注（effects 数据驱动：shop_discount，0.8 = 8 折）
        cur_evt = db.get_world_event()
        _discount_tip = ""
        if cur_evt:
            _evt_def = next((e for e in _b143.WORLD_EVENT_POOL if e["type"] == cur_evt["etype"]), None)
            _sd = (_evt_def.get("effects") or {}).get("shop_discount") if _evt_def else None
            if _sd:
                _discount_tip = f"（{_evt_def['name']} {int(round(_sd * 10))} 折！）"
        raw = self._strip_cmd(event, "商店")
        page = self._parse_page(raw)
        page_items, pages, page = self._page_items(entries, page, per_page=5)
        lines = [f"🏪 【{shop_title} 商店】{_discount_tip}（第 {page}/{pages} 页 · 共 {len(entries)} 件）", "━━━━━━━━━━━━"]
        for i, (key, row) in enumerate(page_items, (page - 1) * 5 + 1):
            lines.append(f"{i:>2}. {row}")
        if is_smith:
            # v135 铁匠铺货架提示（不占序号，显示在商品列表后）
            lines.append("💡 全服共享货架，售罄等补货；每日 0 点换新")
        lines.append("")
        self._record_list_state(qq_id, "商店", page, pages)
        lines.append(f"💰 你的金币：{player['gold']}")
        lines.append(self._tip("shop"))
        yield event.plain_result("\n".join(lines))

    @declared("buy")
    @require_player()

    async def buy(self, event: AstrMessageEvent):
        group_id, qq_id = self._uid(event)
        item_name = self._strip_cmd(event, "购买")
        player = self._player(group_id, qq_id)
        _ec = _clife.ECON_CONFIG
        if self._is_redname(qq_id):
            yield event.plain_result("☠️ 你是红名！商店老板不敢卖你东西……（等红名消退再来）")
            return
        cur = player["cur_map"]
        cur_map = _cspace.MAP_BY_ID.get(cur, {})
        if not self._at_shop(player, group_id, qq_id):
            hint = self._facility_hint(player, "shop")
            yield event.plain_result(
                f"这里没有商店！到有商店的地方（如 {hint}）再输入『商店』吧～" if hint else "这里没有商店！去城镇里找找商铺吧～"
            )
            return
        area_id = cur_map.get("area", cur)
        is_smith = self._is_smith_shop(player)
        sa_kind = self._sa_shop_kind(player)
        sa_id = player.get("cur_subarea") or ""
        sa_items = _clife.SHOP_SUBAREA_ITEMS.get(sa_id)
        # v101.28g：子区域独立配货（无城镇级兜底）；smith 分支无配货则空
        if sa_items is not None:
            shop_items = sa_items
        else:
            shop_items = []
        if not shop_items and not is_smith and self._wild_trader_here(player, group_id, qq_id):
            # 意见#130 同源修复（与 shop 面板一致）：未偶遇的静态野外行商不隔空放行——夜钓翁
            # map=harbor_docks 但没探索偶遇时，玩家在码头任何子区域都会被判定可买它的货
            _trader = self._wild_trader_here(player, group_id, qq_id)
            _tr_npc = _wild.ALL_WILD.get(_trader, {}) if _trader else {}
            _tr_timed = bool(C.get_timed(group_id, qq_id, f"wild:{_trader}")) if _trader else False
            if _trader and (_tr_npc.get("roam") or _tr_timed):
                shop_items = _clife.SHOP_WILD_TRADE  # v95.4：野外行商货物
        materials = (_clife.SHOP_SMITH_MATERIALS.get(cur) or _clife.SHOP_SMITH_MATERIALS.get(area_id, [])) if is_smith else []
        item_name = item_name.strip()
        # F2-2：『购买 』空参静默买第一件（空串是任意名称的子串恒 True，report_18 P1-1）
        #   ——显式格式提示（与『加点 』空参提示风格一致），不执行购买
        if not item_name:
            yield event.plain_result(
                "格式：购买 <商品名/序号> [数量]，如『购买 治疗药水(小) 5』；『商店』查看商品列表～"
            )
            return
# v95.25 #127 + 玩家意见#2（zerc）：支持『购买 <名称/序号> <数量>』（空格）与
        #   『购买 <名称>*<数量>』（星号）两种批量格式（如『购买 治疗药水(中) 6』、『购买 治疗药水*10』、『购买 1*5』）；
        #   数量校验显式报错：0/负/非数字/超 buy_qty_max 不再静默钳制（此前 0/负被钳成 1、超限被钳到上限，
        #   用户感知为"买少了/买错了"；isdigit 误吞 ²/³ 等上标会在 int() 抛 ValueError，一并改为 isdecimal 加固）
        qty = 1
        _qty_raw = None
        # 尾部数量 token 判定：十进制数字或带负号的数字（负号/0 走下方 qty<1 显式报错，
        # 而不是被当成商品名的一部分去搜索——「商店里没有『治疗药水 -3』」不友好）
        def _is_qty_token(tok: str) -> bool:
            return tok.isdecimal() or (tok.startswith("-") and len(tok) > 1 and tok[1:].isdecimal())

        _parts = item_name.split()
        if len(_parts) >= 2 and _is_qty_token(_parts[-1]):
            _qty_raw = _parts[-1]
            item_name = " ".join(_parts[:-1])
        elif "*" in item_name:
            _head, _, _tail = item_name.rpartition("*")
            _tail = _tail.strip()
            if _is_qty_token(_tail):
                _qty_raw = _tail
                item_name = _head.strip()
            else:
                yield event.plain_result(
                    "数量格式不对！例：『购买 治疗药水*5』或『购买 治疗药水 5』；『商店』查看商品列表～"
                )
                return
        if _qty_raw is not None:
            try:
                qty = int(_qty_raw)
            except ValueError:
                yield event.plain_result("数量不合法！请输入正整数，如『购买 治疗药水 5』～")
                return
            if qty < 1:
                yield event.plain_result("数量至少 1 个！大批量购买用『购买 <商品> 数量』或『购买 <商品>*数量』～")
                return
            if qty > _ec["buy_qty_max"]:
                yield event.plain_result(f"单次最多购买 {_ec['buy_qty_max']} 个！需要更多请分批购买～")
                return
        # 星号/数量剥离后无商品名（如『购买 *5』）→ 显式格式提示，防空名称静默买第一件（F2-2 同款兜底）
        if not item_name:
            yield event.plain_result(
                "格式：购买 <商品名/序号> [数量]，如『购买 治疗药水(小) 5』；『商店』查看商品列表～"
            )
            return
        # 全角括号容错：『购买 治疗药水（中）』→ 半角『治疗药水(中)』
        item_name = item_name.replace("（", "(").replace("）", ")")
        # 世界事件商店折扣（effects 数据驱动：shop_discount，0.8 = 8 折）
        discount = 1.0
        _evt_tip = ""
        cur_evt = db.get_world_event()
        if cur_evt:
            _evt_def = next((e for e in _b143.WORLD_EVENT_POOL if e["type"] == cur_evt["etype"]), None)
            _sd = (_evt_def.get("effects") or {}).get("shop_discount") if _evt_def else None
            if _sd:
                discount = float(_sd)
                _evt_tip = f"（{_evt_def['name']} {int(round(_sd * 10))} 折！）"
        weapons = _clife.SHOP_WEAPONS.get(cur) or _clife.SHOP_WEAPONS.get(area_id, [])
        # v101.25h：武器/名册装备只在 smith/general 卖（草药铺/酒馆不卖）
        # v101.28o：is_smith 也放行——craft+alchemy 双职能店（如晨曦药剂坊 dawn_city_5）
        #   面板 is_smith 分支会列出武器，购买侧若按 herb 过滤则"看得到买不到"（#445）
        can_sell_weapons = is_smith or sa_kind in ("smith", "general")
        if not can_sell_weapons:
            weapons = []
        equip_items = self._shop_equip_roster(player, _clife.SHOP_EQUIP.get(cur) or _clife.SHOP_EQUIP.get(area_id, []))
        # v104 M09 P1 修复：装备只在 is_smith（铁匠类）面板列出——general 商店序号列表与面板严格同源
        #   （此前 general 序号含 e: 名册装备，『购买 4』实测买到面板未显示的翡翠皮甲）
        if not is_smith:
            equip_items = []
        # v135 铁匠铺货架（全服共享）：town_lv 供序号/名称购买共用（面板第 6 块同源）
        smith_items = _ss.get_smith_stock(cur, _ss.town_level(cur)) if is_smith else []
        # 序号购买：『购买 3』→ 与商店列表一致的第 3 件商品（顺序：材料→装备→武器，与 shop 面板一致）
        if item_name.isdigit():
            entries = list(shop_items) + [f"m:{m}" for m in materials] + (["bp:rand"] if is_smith else []) + [f"e:{rid}" for rid in equip_items] + [f"w:{w[0]}" for w in weapons]
            # v135 铁匠铺货架（全服共享）：序号与商店面板第 6 块同源（材料→装备→武器→货架→坐骑）
            if is_smith:
                entries += [f"s:{sit['rid']}" for sit in smith_items]
            # v104 修 M17-P2：橡木镇序号购买含坐骑（与商店面板顺序一致，追加在末尾）
            # v130.7 意见#23：序号购买与面板同口径（草药铺/酒馆序号不挂坐骑）
            if area_id == "oak" and cur == _ccore.START_MAP and sa_kind in ("smith", "general"):
                entries += [f"mount:{m['key']}" for m in _clife.MOUNT_POOL if (m.get("price") or 0) > 0]
            idx = int(item_name)
            if idx < 1 or idx > len(entries):
                yield event.plain_result(f"没有第 {idx} 号商品！『商店』查看商品列表。")
                return
            key = entries[idx - 1]
            # ============ v181.P4-3：序号购买 key 分派（bp/m/w/mount/e/s/消耗品）业务下沉 services.shop ============
            _buy_res, _buy_msg = _shop_svc.buy_index_dispatch(
                key, group_id, qq_id, player, qty, discount,
                shop_items=shop_items, materials=materials, weapons=weapons,
                equip_items=equip_items, smith_items=smith_items,
                sa_id=sa_id, area_id=area_id, cur=cur, is_smith=is_smith,
                evt_tip=_evt_tip,
                limit_guard=self._shop_limit_buy_guard,
                at_shop=self._at_shop,
                smith_stock=_ss, buy_weapon=self._buy_weapon,
            )
            if _buy_msg is not None:
                yield event.plain_result(_buy_msg)
                return
            # （分派完成：msg None = 命中并完成成交分支——序号 key 分派穷尽终结，
            #   所有 key 都落 bp:/m:/w:/mount:/e:/s:/消耗品 之一，原实现各分支均 return）
            return
        # 找铁匠铺随机图纸（按名称）：『购买 神秘锻造图纸』→ bp:rand（序号分支 v94 已支持，名称分支补上）
        if is_smith and item_name in ("神秘锻造图纸", "锻造图纸", "图纸", "神秘图纸"):
            bp_price = int((max(1, player["level"]) * _ec["bp_price_per_lv"]
                            + _ec["bp_price_base"]) * _ec["bp_smith_mult"] * discount)
            # v105 M09 P3-9：图纸单件商品
            if qty > 1:
                yield event.plain_result("神秘锻造图纸只能买 1 张！想再买一张就再输一次～")
                return
            if player["gold"] < bp_price:
                yield event.plain_result(f"金币不足！需要 {bp_price} 金币。")
                return
            db.update_player(group_id, qq_id, gold=player["gold"] - bp_price)
            bp = C.roll_blueprint(max(1, player["level"]))
            import uuid
            db.add_item(group_id, qq_id, f"eq_{uuid.uuid4().hex[:8]}", bp)
            tip = _evt_tip
            yield event.plain_result(f"✅ 你买到一张【{bp['name']}】！{tip}")
            return
        # 找补给品（按名称）
        for iid in shop_items:
            it = _cit.ITEMS[iid]
            if item_name in it["name"] or (item_name and item_name in it["name"].replace("(", "").replace(")", "")):
                price = int(it["price"] * discount)
                total = price * qty
                if player["gold"] < total:
                    yield event.plain_result(f"金币不足！需要 {total} 金币。")
                    return
                # v166 商店限购：消耗品（店内共享库存+每日个人限购）
                _l_ok, _l_msg = self._shop_limit_buy_guard(group_id, qq_id, sa_id, f"item:{iid}", qty)
                if not _l_ok:
                    yield event.plain_result(_l_msg)
                    return
                db.update_player(group_id, qq_id, gold=player["gold"] - total)
                # v21 防刷钱：消耗品卖出价 = 实际支付价（商队 8 折时不能原价卖出套利）
                # v104 修 M09-P0：全量拷贝 ITEMS 定义字段（hot/hot_turns/hot_mana/food_effect/effect），
                #   否则 9 种店售食物丢 hot 字段 → infer_template 判为药水，战斗内持续恢复失效
                db.add_item(group_id, qq_id, iid, {**it, "type": "消耗品", "stackable": True, "price": price}, count=qty)
                tip = _evt_tip
                qty_str = f" ×{qty}"  # #254: 单件购买也回显数量（此前 qty=1 无回显）
                yield event.plain_result(f"✅ 你购买了【{it['name']}】{qty_str}！{tip}")
                return
        # 找材料（按名称）
        for mid in materials:
            mt = _cit.MATERIALS[mid]
            if item_name in mt["name"]:
                price = int(mt["price"] * discount)
                total = price * qty
                if player["gold"] < total:
                    yield event.plain_result(f"金币不足！需要 {total} 金币。")
                    return
                # v166 商店限购：材料（店内共享库存+每日个人限购）
                _l_ok, _l_msg = self._shop_limit_buy_guard(group_id, qq_id, sa_id, f"mat:{mid}", qty)
                if not _l_ok:
                    yield event.plain_result(_l_msg)
                    return
                db.update_player(group_id, qq_id, gold=player["gold"] - total)
                # v104 修 M09-P3：材料购买全量拷贝定义字段（补 quality 等），不再丢字段
                db.add_item(group_id, qq_id, mid, {**mt, "type": "材料", "stackable": True, "price": price}, count=qty)
                tip = _evt_tip
                qty_str = f" ×{qty}"  # #254: 单件购买也回显数量（此前 qty=1 无回显）
                yield event.plain_result(f"✅ 你购买了【{mt['name']}】{qty_str}！{tip}")
                return
        # 找武器（按名称）
        for wname, wtype, wlv, wq in weapons:
            if item_name in wname:
                # v95.34：价格与显示/序号购买同源（v101.25e _shop_equip_price），修 #414 名称购买走旧公式低价漏洞
                price = int(self._shop_equip_price("weapon", wlv, wq, wtype) * discount)
                # v105 M09 P3-9：武器单件商品（此前『购买 铁剑 3』静默只买 1 把）
                if qty > 1:
                    yield event.plain_result(f"『{wname}』是武器，只能单件购买！需要几把就再买几次～")
                    return
                if player["gold"] < price:
                    yield event.plain_result(f"金币不足！需要 {price} 金币。")
                    return
                # v166 商店限购：商店武器（店内共享库存+每日个人限购）
                _l_ok, _l_msg = self._shop_limit_buy_guard(group_id, qq_id, sa_id, f"weapon:{wname}", 1)
                if not _l_ok:
                    yield event.plain_result(_l_msg)
                    return
                # 阶段八：武器不锁职业（20 章），名册名走名册精确生成
                db.update_player(group_id, qq_id, gold=player["gold"] - price)
                equip_item = self._buy_weapon(wname, wtype, wlv, wq)
                # v21 防刷钱：商店装备卖出价 = 买入价一半
                equip_item["price"] = int(price * _ec["equip_resale_rate"])
                import uuid
                db.add_item(group_id, qq_id, f"eq_{uuid.uuid4().hex[:8]}", equip_item)
                yield event.plain_result(f"✅ 你购买了【{wname}】！放到背包了，输入『装备 {wname}』使用。")
                return
        # 找装备（按名称）
        for rid in equip_items:
            r = _cit.EQUIP_ROSTER[rid]
            if item_name in r["name"]:
                # v95.34：价格与显示/序号购买同源（v101.25e _shop_equip_price），修 #414 名称购买走旧公式低价漏洞
                price = int(self._shop_equip_price(r["slot"], r["lv"], r["quality"], r.get("weapon_type"), rid) * discount)
                # v105 M09 P3-9：装备单件商品（数量参数不适用）
                if qty > 1:
                    yield event.plain_result(f"『{r['name']}』是装备，只能单件购买！需要几件就再买几次～")
                    return
                if player["gold"] < price:
                    yield event.plain_result(f"金币不足！需要 {price} 金币。")
                    return
                # v166 商店限购：名册装备（店内共享库存+每日个人限购）
                _l_ok, _l_msg = self._shop_limit_buy_guard(group_id, qq_id, sa_id, f"equip:{rid}", 1)
                if not _l_ok:
                    yield event.plain_result(_l_msg)
                    return
                db.update_player(group_id, qq_id, gold=player["gold"] - price)
                equip_item = C.generate_roster_equip(rid)
                equip_item["price"] = int(price * _ec["equip_resale_rate"])
                import uuid
                db.add_item(group_id, qq_id, f"eq_{uuid.uuid4().hex[:8]}", equip_item)
                yield event.plain_result(f"✅ 你购买了【{r['name']}】！放到背包了，输入『装备 {r['name']}』使用。")
                return
        # v135 铁匠铺货架（全服共享）按名称购买（NPC 作品，如『购买 汉斯的精铁长剑』）
        # 前置判定：带「作品」字样或命中本城铁匠名 → 只查货架（防误吞普通装备名）
        if is_smith:
            _npc = _ss.SMITH_NPC_NAMES.get(cur, "铁匠")
            _want_stock = ("作品" in item_name) or (_npc in item_name)
            for _sit in smith_items:
                _r = _cit.EQUIP_ROSTER[_sit["rid"]]
                if _want_stock and (item_name in _r["name"] or _r["name"] in item_name):
                    ok, item_data, price = _ss.buy_stock_item(cur, _ss.town_level(cur), _sit["rid"])
                    if not ok:
                        yield event.plain_result("😢 这件作品已被别的冒险者买走了，售罄等补货吧～")
                        return
                    if qty > 1:
                        yield event.plain_result("铁匠的作品是孤品，只能单件购买！")
                        return
                    if player["gold"] < price:
                        yield event.plain_result(f"金币不足！需要 {price} 金币。")
                        return
                    db.update_player(group_id, qq_id, gold=player["gold"] - price)
                    item_data["price"] = int(price * _ec["equip_resale_rate"])
                    import uuid
                    db.add_item(group_id, qq_id, f"eq_{uuid.uuid4().hex[:8]}", item_data)
                    yield event.plain_result(f"✅ 你买下了【{item_data['name']}】！铁匠的手艺交到你手里，输入『装备』查看。")
                    return
        # v39/v101.15 坐骑：橡木镇马厩购买（老马/小毛驴等 price>0 的坐骑）
        shop_mounts = [m for m in _clife.MOUNT_POOL if (m.get("price") or 0) > 0]
        for mdef in shop_mounts:
            if item_name in mdef["name"] or item_name.strip() == mdef["key"]:
                # v130.7 意见#23：名称购买同口径（草药铺/酒馆『购买 老马』同样拦截）
                if area_id != "oak" or cur != _ccore.START_MAP or sa_kind not in ("smith", "general"):
                    yield event.plain_result(f"橡木镇的商人才能买到{mdef['name']}！去橡木镇『商店』看看～")
                    return
                mounts = player.get("mounts") or {}
                if mdef["key"] in (mounts.get("owned") or []):
                    yield event.plain_result(f"你已经拥有{mdef['name']}了！")
                    return
                # v104 M17 P2-1：名称购买坐骑同样校验骑乘等级（与序号购买同口径）
                if player["level"] < mdef["lv"]:
                    yield event.plain_result(f"『{mdef['name']}』需要 Lv.{mdef['lv']} 才能骑乘，你才 Lv.{player['level']}！先升级再来买吧～")
                    return
                price = int(mdef["price"] * discount)
                if player["gold"] < price:
                    yield event.plain_result(f"金币不足！{mdef['name']}要 {price} 金币。")
                    return
                db.update_player(group_id, qq_id, gold=player["gold"] - price)
                mounts = dict(player.get("mounts") or {})
                owned = list(mounts.get("owned") or [])
                owned.append(mdef["key"])
                mounts["owned"] = owned
                db.update_player(group_id, qq_id, mounts=mounts)
                yield event.plain_result(
                    f"{mdef['icon']} 你买了{mdef['name']}！缰绳交到你手里，它打了个响鼻。\n"
                    f"💡 『骑乘 {mdef['name']}』骑上它，『坐骑』查看全部！")
                return
        yield event.plain_result(f"商店里没有『{item_name}』！输入『商店』查看商品。")

    # ============ v166 商店限购（店内共享库存 + 每日个人限购，数据驱动） ============
    def _shop_limit_buy_guard(self, group_id: str, qq_id: str, sa_id: str, key: str, qty: int):
        """v181.P4-3：转发 services.shop.limit_buy_guard（economy 本地定义已随迁，core.shop_stock 薄转发）"""
        return _shop_svc.limit_buy_guard(group_id, qq_id, sa_id, key, qty)

    def _shop_limit_label(self, sa_id: str, key: str) -> str:
        """v181.P4-3：转发 services.shop.limit_label（economy 本地定义已随迁）"""
        return _shop_svc.limit_label(sa_id, key)
