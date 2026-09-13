# -*- coding: utf-8 -*-
"""《奥兰迪亚·余烬纪年》包内**共享效果动作**（逐字搬自游戏仓 `game/core/effect_actions.py`，186 行）。

真源 = 「效果动作」（成功触发后做什么）的共享实现：装备词条 affix / 食物 food / 药剂 potion
各自保留触发判断，动作只此一份。**本文件正文与真源逐字相同**（一字未改）——它零宿主依赖
（包外依赖只有 `saintess_engine.battle.formulas.calc_damage`，方向合法：内容 → 引擎）。

宿主 `game/core/effect_actions.py` 现在是薄壳（全名单再导出），消费者 1 处
（`game/core/potion_effects.py:136` 函数内 `from .effect_actions import action_def_down`）名字/签名不变。

缺口（报告登记）：包内 `content/effects/potion_effects.py:208` 走的是 `battle.action_def_down`
替身口（B8 期写法），**未**消费本模块 → 收口时二选一（改调本模块 / 保留引擎接口），本线不动别线文件。
"""
# -*- coding: utf-8 -*-
"""奥兰迪亚·余烬纪年核心层 - effect_actions.py（v180-D P2：共享效果动作 / v180-G B6：朝向参数化）

效果系统统一（鱼鱼 2026-09-06 拍板）——把"效果动作"（成功触发后做什么）
抽成共享函数，来源域（装备词条 affix / 食物 food）各自保留触发判断，但动作
只此一份，不再 affix/food 复制粘贴。

铁律：
- 本文件函数只做"动作"，不判来源、不查来源数据表
- 数值由调用方传入（affix 读 AFFIXES 表、food 从声明读）——动作不存数值
- 返回 None（改 battle/player 状态 + 追加 logs）

v180-G B6（动作收口到 effect_actions 全量适配）：
- "攻击目标向"动作（action_dot/action_def_down/action_bonus_pct/action_element_dmg/
  action_pierce_dmg/action_counter 及 _bonus_dmg_apply 底座）统一加关键字参数
  target=None：传入目标 actor dict 则对其生效（debuffs/buffs 写目标自身 dict、
  附加伤害 _deal_damage 显式打 target）；None → 回落主目标 battle._hit_tgt()
  （旧语义 = 玩家打当前主敌）。调用方（affix_effects/food_effects/potion_effects）
  已显式传 battle._hit_tgt()，不再依赖本文件写死 enemy。
- 对"施法者自身"作用（action_regen_hp/regen_mp/mark/lifesteal 回血回蓝/叠印记/
  吸血）目标天然是 player 自身，不加 target。
- 伤害落地统一走 battle._deal_damage(..., target=...) 与 battle._boss_dmg_filter
  （v104 M02 P1-5 统一：附加伤害过 Boss 护盾过滤）。
"""
import random as _random


def _ea_tgt(battle, target):
    """目标解析：显式传目标 actor → 用之；None → 主目标（旧语义 battle._hit_tgt()）。"""
    if isinstance(target, dict):
        return target
    return getattr(battle, "enemy", None) or {}


def action_regen_hp(battle, player, logs, *, pct=0.01, label="回春"):
    """回复 玩家 max_hp × pct 生命（原 affix regen / food 树蜜糖）。自身向，无 target。"""
    if player.get("hp", 0) < player.get("max_hp", 1):
        heal = int(player.get("max_hp", player.get("hp", 1)) * float(pct))
        battle._heal_actor(player, heal, logs)  # v180E 统一落地
        logs.append(f"🌿 {label}生效，回复 {heal} 点生命！")


def action_regen_mp(battle, player, logs, *, pct=0.01, label="冥想"):
    """回复 玩家 max_mp × pct 魔力（原 affix meditate / food 月光饼）。自身向，无 target。"""
    if player.get("mp", 0) < player.get("max_mp", 1):
        heal = int(player.get("max_mp", player.get("mp", 1)) * float(pct))
        player["mp"] = min(player.get("max_mp", player.get("mp", 1)), player.get("mp", 0) + heal)
        logs.append(f"🧘 {label}生效，回复 {heal} 点魔力！")


def action_dot(battle, logs, *, key="bleed", stacks=3, max_n=None, label="流血", target=None):
    """目标级持续伤害：叠 target.debuffs[key] 层（原 affix bleed / food 烬火辣椒）。

    stacks=每次触发叠层数（兼上限，除非 max_n 指定）；max_n=None 用 stacks。
    target=None → 主目标 battle._hit_tgt()（调用方应显式传目标 actor）。
    """
    tgt = _ea_tgt(battle, target)
    deb = tgt.setdefault("debuffs", {})
    cur = deb.get(key) or {"n": 0, "mult": 1.0}
    cap = int(max_n if max_n is not None else stacks)
    cur["n"] = min(cap, int(cur.get("n", 0) or 0) + int(stacks))
    deb[key] = cur
    logs.append(f"🩸 {label}！{tgt.get('name', '敌人')}伤口裂开，将持续失血！")


def action_def_down(battle, logs, *, turns=2, pct=0.15, label="破甲", target=None):
    """目标防御削减：target.buffs def_down 刻数 + _armor_break_pct（原 affix armor_break / food 蘑菇汤）。

    target=None → 主目标 battle._hit_tgt()（调用方应显式传目标 actor）。
    """
    tgt = _ea_tgt(battle, target)
    eb = tgt.setdefault("buffs", {})
    eb["def_down"] = max(int(eb.get("def_down", 0) or 0), int(turns))
    eb["_armor_break_pct"] = float(pct)
    logs.append(f"🛡️ {label}！{tgt.get('name', '敌人')}防御下降 {int(pct * 100)}%！")


def action_mark(battle, player, logs, *, key="dragon_mark", max_n=5, label="龙语印记",
                mark_pct=None):
    """玩家叠印记层（原 affix dragon_tongue / food 龙蛋煎饼）。自身向，无 target。

    mark_pct 仅供文案；层数上限 max_n。
    """
    player.setdefault('stacks', {})[key] = min(int(max_n), int(player.setdefault('stacks', {}).get(key, 0) or 0) + 1)
    logs.append(f"🐉 {label}叠加！({player.setdefault('stacks', {})[key]} 层"
                + (f"，每层＋{int(mark_pct * 100)}% 伤害)" if mark_pct else ")"))


# ============================================================
# 追加伤害类（combo/charge/element/pierce 共用底座）
# ============================================================
def _bonus_dmg_apply(battle, player, cd, logs, tag, name, target=None):
    """追加伤害落地：Boss 护盾过滤 → 对 target 主结算（v104 M02 P1-5 统一）。

    food 侧原实现有此过滤、affix 侧漏了（词条 combo/charge 附加伤害绕过 Boss
    护盾 = bug）——统一收口到本动作后两侧一致。
    target=None → 主目标 battle._hit_tgt()；显式传目标则打该 actor。
    """
    if cd <= 0:
        return 0
    tgt = _ea_tgt(battle, target)
    try:
        cd = battle._boss_dmg_filter(cd, player, logs)
    except Exception:
        pass
    battle._deal_damage(cd, logs, target=tgt)
    logs.append(f"{tag} {name}！对【{tgt.get('name', '敌人')}】追加 {cd} 点伤害！")
    return cd


def action_bonus_pct(battle, player, dmg, logs, *, pct=0.50, tag="⚡", name="连击", target=None):
    """按本次伤害 dmg × pct 追加一次伤害（原 affix combo/charge / food 鹰蛋/皇家烤肉）。

    combo(连击)与 charge(蓄力爆发)动作同构，仅文案/标签不同——统一本动作。
    target=None → 主目标 battle._hit_tgt()。
    """
    if dmg <= 0:
        return 0
    cd = int(dmg * float(pct))
    return _bonus_dmg_apply(battle, player, cd, logs, tag, name, target=target)


def action_element_dmg(battle, player, dmg, logs, *, pct=0.05, tag="🔥", name="火焰附加",
                       slow_turns=0, label="减速", target=None):
    """攻击附加 dmg × pct 元素伤害（原 affix/food element_fire / element_ice）。

    slow_turns>0 时额外对 target 挂减速（冰）。target=None → 主目标 battle._hit_tgt()。
    """
    if dmg <= 0:
        return 0
    tgt = _ea_tgt(battle, target)
    ed = max(1, int(dmg * float(pct)))
    _bonus_dmg_apply(battle, player, ed, logs, tag, name, target=tgt)
    if slow_turns > 0:
        eb = tgt.setdefault("buffs", {})
        eb["spd_down"] = max(int(eb.get("spd_down", 0) or 0), int(slow_turns))
        logs.append(f"❄️ {label}！")
    return ed


def action_pierce_dmg(battle, player, logs, *, atk_pct=0.60, tag="🏹", name="贯穿", target=None):
    """无视防御追加伤害（原 affix/food pierce）。

    按玩家 atk × atk_pct 计算，防御=0 直伤（无视防御语义）。
    target=None → 主目标 battle._hit_tgt()。
    """
    from saintess_engine.battle.formulas import calc_damage
    pst = battle._player_stats(player)
    pd = calc_damage(int(pst.get("atk", 0) * float(atk_pct)), 0)
    if pd <= 0:
        return 0
    return _bonus_dmg_apply(battle, player, pd, logs, tag, name, target=target)


def action_counter(battle, player, logs, *, atk_pct=0.60, tag="⚔️", name="反击", target=None):
    """受击反击：按玩家 atk × atk_pct 反打目标（原 affix/food counter）。

    触发条件（目标存活/概率）由来源 handler 判定；此处只做反击动作。
    target=None → 主目标 battle._hit_tgt()（反击方向 = 打攻击方，当前引擎主目标即玩家视野的敌人）。
    """
    tgt = _ea_tgt(battle, target)
    if not tgt.get("hp", 0) or tgt.get("hp", 0) <= 0:
        return 0
    from saintess_engine.battle.formulas import calc_damage
    pst = battle._player_stats(player)
    est = battle._enemy_stats(tgt)
    cd = calc_damage(int(pst.get("atk", 0) * float(atk_pct)), est.get("def", 0))
    if cd <= 0:
        return 0
    try:
        cd = battle._boss_dmg_filter(cd, player, logs)
    except Exception:
        pass
    battle._deal_damage(cd, logs, target=tgt)
    logs.append(f"{tag} {name}！对【{tgt.get('name', '敌人')}】造成 {cd} 点伤害！")
    return cd


def action_lifesteal(battle, player, dmg, logs, *, heal_pct=0.08, label="吸血"):
    """攻击吸血：回复 dmg × heal_pct 生命（原 food lifesteal / 词条吸血通用）。自身向，无 target。"""
    if dmg <= 0:
        return 0
    heal = max(1, int(dmg * float(heal_pct)))
    battle._heal_actor(player, heal, logs)  # v180E 统一落地
    logs.append(f"🩸 {label}：回复 {heal} 点生命！")
    return heal
