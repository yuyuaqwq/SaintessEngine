# -*- coding: utf-8 -*-
"""《奥兰迪亚·余烬纪年》战斗结算（`content/settlement.py`）—— B9 线 L6 宿主薄壳化落点

真源（游戏仓 `dragonfall/`，**只读，本批零改动**）
--------------------------------------------------
| 真源 | 行数 | 本批搬什么 |
|---|---:|---|
| `game/services/battle_settlement.py` | 795 | **全部正文**：经验曲线 / 六类加成 / 掉落 roll / 材料折算 / 胜利·战败全同步编排（含落库副作用） |

本文件 = 真源正文**逐字搬入**，只动「宿主服务取件」一类（正文/文案 emoji/数值/概率/
random 调用顺序/落库顺序**一字未改**）：

| 真源写法 | 包内写法 | 说明 |
|---|---|---|
| `from .. import db`（函数体内惰性 import） | `db = host.db` | 宿主存储层（调用方注入） |
| `from .. import content as C` | `C = host.C` | 宿主内容聚合层（材料/符文/地图/宠物/公会/世界事件表**未进包**，仍走宿主真源） |
| `from ..core.rule_engine import fire as _rule_fire`（函数体内） | `host.rule_fire` | 行为彩蛋引擎（宿主 `game/core/rule_engine.py`，游戏名词） |
| `from ..core.stat_bonus import stat_bonus as _stat_bonus` | `host.stat_bonus` | 称号/成就动态属性（宿主 `game/core/stat_bonus.py`） |
| `from ..content_rules.panel import player_final_stats, race_stats` | `host.player_final_stats` / `host.race_stats` | 面板公式（宿主 `game/content_rules/panel.py`） |
| `from ..content_rules.gameplay import resolve_drop` | `host.resolve_drop` | 掉落名解析（**MATERIALS 域未进包**，见缺口 §） |
| 函数签名（`self` 早已去掉） | 首参 `host` | 宿主服务句柄；`db`/`C` 在函数体首行绑定 |

宿主侧薄壳 = `game/services/battle_settlement.py`（注册面零变化：25 个名字逐名再导出，
`game/services/__init__.py` / `game/commands/combat.py` 的 import 点与签名一行都不用改）。

⚠️ 内部传递链（与真源逐字一致，勿动顺序）：
  - 段6 world_event_bonus 产出 evt_effects → 段8 bump_kill_stats 消费 rep_mult
  - 段16 幸运护符 lucky_line → 段17 材料折算按 _luck/_gold_bonus 条件续写同一变量
    （"if _luck > 0 and not lucky_line" / 追加聚宝行），顺序敏感
  - 段19 grant_player_exp 落库后 `db.get_player` **重读**（读档惰性升级在此结算）→
    段21 的 need/exp_pct 用重读后的 player（这是「计划半边」做不到逐字节等价的原因）
"""
import random
import time

# ---- B14-2 L5：数据名读点切包内门面（`C.<数据名>` → 门面直取；函数名/缺口名仍留 `C.<名>`）----
from . import catalog_core as _cc     # 常量/职业/种族/面板公式
from . import catalog_items as _ci    # 物品/材料/符文/装备名册
from . import catalog_life as _cl     # 生活/副业/商店/宠物/经济配置
from . import catalog_quests as _cq   # 任务/剧情族
from . import catalog_space as _sp    # 地图/子区域
from . import catalog_b143 as _b143   # B14-3 收口名（宠物/公会/势力/符文掉落/地图连边/世界事件表）
# ---- B14-3（2026-09-14）读点切换 ----
# 上一段留下的 8 个「域缺口名」（GUILD_CONFIG/PET_MAX_LEVEL/PET_SKILL_UNLOCK_LV/WORLD_EVENT_POOL/
# AREA_FACTION/FACTIONS/MAP_CONNECTIONS/RUNE_DROP）已由 `catalog_b143` 提供 → 本段 15 处切 `_b143`；
# 仍留 `C.<名>` 的只剩宿主**函数**（pet_exp_bonus/roll_drop/display/…）。见 overnight/_w3_cut_economy_side.md。


# ============ 胜利结算主段小函数（combat._handle_victory 原段顺序 1803–2201） ============

def exp_curve(exp, monster_lv, player_level):
    """v28→v173.2 经验等级差非线性曲线（2026-09-04 鱼鱼拍板，32 章 11.6 同步）
    v173.2a 压制（鱼鱼：给太慷慨）：系数 0.02→0.015，封顶 ×2.0(+100%)
      diff > 0（越级打高级怪）→ 指数奖励 mult = 1 + 0.015×diff²，封顶 ×2.0
      diff ∈ [-3, 0]（同级±3 正常练级）→ 无惩罚
      diff < -3（打低级怪）→ 指数衰减 mult = 0.85^(-diff-3)，最低 15%（杜绝刷低级）
    防无脑越级刷怪不靠经验惩罚：越级伤害压制(低打高 ×0.95/×0.90 削伤)仍在，
    高 11+ 级怪打不动自然刷不了；+100% 封顶防极端。"""
    diff = monster_lv - player_level
    _exp_note = ""
    if diff > 0:
        mult = 1.0 + 0.015 * diff * diff
        if mult > 2.0:
            mult = 2.0
        exp = int(exp * mult)
        _exp_note = f"⚔️ 越级挑战：经验 ×{mult:.2f}"
    elif diff < -3:
        mult = max(0.15, 0.85 ** (-diff - 3))
        exp = int(exp * mult)
        _exp_note = f"📉 碾压低阶怪：经验 ×{mult:.2f}"
    return exp, _exp_note


def party_exp_bonus(host, group_id, qq_id, exp):
    """组队经验 +10%（队长队员同样生效，design 29 章 2.1 表）
    v95.29 #270：队伍行按 (group_id, leader) 记，队员反查必须同一 group_id——
    曾误写成全局查导致"群聊组队后私聊也吃加成"（#52 关联反馈）；同群组队本就有群内限制。"""
    db = host.db
    _pm = db.party_members(group_id, qq_id)
    party_bonus_line = ""
    if _pm:
        exp = int(exp * 1.1)
        party_bonus_line = f"\n🤝 组队加成：经验 +10%（与 {len(_pm) - 1} 名队友同行）"
    return exp, party_bonus_line


def guild_exp_bonus(host, qq_id, exp):
    """公会经验加成（等级越高加成越多，上限 20%）"""
    db, C = host.db, host.C
    guild_bonus = []
    g = db.guild_get_by_member(qq_id)
    if g:
        gb = min(g["level"] * _b143.GUILD_CONFIG["exp_bonus_per_level"], _b143.GUILD_CONFIG["max_bonus"])
        if gb > 0:
            exp = int(exp * (1 + gb))
            guild_bonus.append(f"🏰 公会加成：经验 +{int(gb*100)}%")
    return exp, guild_bonus


def pet_exp_gain(host, qq_id, exp, monster):
    """宠物经验加成（24 章五 v133.2 品质分级：等级×品质每级加成，cap 5~30%；饱食度 >0 全额，=0 减半）"""
    db, C = host.db, host.C
    pet_bonus = []
    pet = db.pet_get(qq_id)
    pet = db.pet_decay_satiety(pet)
    if pet:
        pb = C.pet_exp_bonus(pet)
        if pet["satiety"] <= 0:
            pb = pb / 2  # 饱食度 =0：经验加成减半
        if pb > 0:
            exp = int(exp * (1 + pb))
            ptag = "🐾 陪伴(饱食度归零，加成减半)" if pet["satiety"] <= 0 else "🐾 陪伴"
            pet_bonus.append(f"{ptag}：经验 +{C.pct_str(pb)}%")
        # v104 M17 P3：亲密度≥50 → 战斗经验 +5%（bond 消费方，面板见 social.py pet_view）
        if pet.get("bond", 0) >= 50:
            exp = int(exp * 1.05)
            pet_bonus.append("💕 羁绊(亲密度≥50)：经验 +5%")
        # 战斗消耗饱食度 -2（先自然衰减再扣战斗消耗）
        # v105 M17 P3-5 设计说明：仅胜利路径扣除。24 章四"每场战斗 -2"字面含败北/逃跑，
        # 但当前为对玩家的宽容设计——败北已有金币惩罚+回城，逃跑无惩罚，不再叠加扣粮；改动需策划拍板
        db.pet_update(qq_id, satiety=max(0, pet["satiety"] - 2), last_sat_time=pet["last_sat_time"])
        # 宠物分得经验（24 章四：击杀怪宠物分得经验，取怪物基础经验 20%）
        # v173.2：加等级差乘区（宠物 vs 怪，复用玩家非线性曲线），封顶 Lv.50
        p_gain = max(1, int(monster["exp"] * 0.2 * C.pet_exp_mult(int(pet.get("level", 1) or 1), _mon_lv(monster))))
        p_exp = pet["exp"] + p_gain
        p_lv = pet["level"]
        p_lvup = False
        while p_lv < _b143.PET_MAX_LEVEL and p_exp >= C.pet_exp_need(p_lv):
            p_exp -= C.pet_exp_need(p_lv)
            p_lv += 1
            p_lvup = True
        if p_lv >= _b143.PET_MAX_LEVEL:
            p_exp = min(p_exp, C.pet_exp_need(_b143.PET_MAX_LEVEL) - 1)  # 封顶溢出封存
        db.pet_update(qq_id, exp=p_exp, level=p_lv)
        if p_lvup:
            pet_bonus.append(f"🎉 宠物升到 Lv.{p_lv}！(Lv.{int(_b143.PET_SKILL_UNLOCK_LV)} 解锁宠物技能)" if p_lv == int(_b143.PET_SKILL_UNLOCK_LV) else (f"🎉 宠物升到 Lv.{p_lv}！(已满级)" if p_lv >= _b143.PET_MAX_LEVEL else f"🎉 宠物升到 Lv.{p_lv}！"))
    return exp, pet_bonus


def mount_exp_bonus(host, player, exp):
    """v101.13 坐骑 exp_mult：骑乘加成类坐骑战斗经验加成（幽灵马/狮鹫/炎蹄战马）"""
    C = host.C
    mount_bonus = []
    meff = C.mount_effects(player)
    em = float(meff.get("exp_mult", 0) or 0)
    if em > 0:
        exp = int(exp * (1 + em))
        mount_bonus.append(f"🐎 坐骑疾驰：经验 +{int(em*100)}%")
    return exp, mount_bonus


def world_event_bonus(host, group_id, qq_id, exp, gold):
    """世界事件加成（effects 数据驱动：按 etype 查 WORLD_EVENT_POOL 定义拿 effects，
    db 的 world_event 仅存 etype/ends_at/data；查不到 = 无加成）"""
    db, C = host.db, host.C
    evt_bonus = []
    evt_effects = {}
    cur_evt = db.get_world_event()
    if cur_evt:
        # v105 M18 P1-5：世界事件期间参与战斗 → world_events 统计
        #（stats.world_events 原无任何写入点 → ach_event10 国战勇士/ach_event_all 死锁；现每次事件中战斗结算 +1）
        try:
            db.init_stats(group_id, qq_id)
            db.bump_stats(group_id, qq_id, world_events=1)
        except Exception:
            pass
        evt_def = next((e for e in _b143.WORLD_EVENT_POOL if e["type"] == cur_evt["etype"]), None)
        if evt_def:
            evt_effects = evt_def.get("effects") or {}
            _em = evt_effects.get("exp_mult")
            _gm = evt_effects.get("gold_mult")
            if _em:
                exp = int(exp * _em)
                evt_bonus.append(f"{evt_def['icon']} {evt_def['name']}：经验 +{int(round((_em - 1) * 100))}%")
            if _gm:
                gold = int(gold * _gm)
                evt_bonus.append(f"{evt_def['icon']} {evt_def['name']}：金币 +{int(round((_gm - 1) * 100))}%")
    return exp, gold, evt_bonus, evt_effects


def fortune_bonus(host, group_id, qq_id, exp, gold):
    """v87 02 章 7.6：每日运势加成（大吉 经验+10% / 小凶 金币-10%）"""
    db = host.db
    fortune_line = ""
    try:
        import json as _j
        _fstate = db.get_event_state(f"daily_fortune_{group_id}_{qq_id}")
        if _fstate:
            _f = _j.loads(_fstate)
            import datetime as _dt
            if _f.get("date") == _dt.date.today().isoformat():
                if _f.get("fortune") == "大吉":
                    exp = int(exp * 1.10)
                    fortune_line = "🌟 今日大吉：经验 +10%！"
                elif _f.get("fortune") == "小凶":
                    gold = int(gold * 0.90)
                    fortune_line = "🌧️ 今日小凶：掉落价值 -10%……"
    except Exception:
        pass
    return exp, gold, fortune_line


def bump_kill_stats(host, group_id, qq_id, monster, evt_effects):
    """任务统计（evt_effects 由段6 world_event_bonus 产出，供声望 rep_mult 消费）"""
    db, C = host.db, host.C
    db.init_stats(group_id, qq_id)
    if monster.get("is_boss"):
        db.bump_stats(group_id, qq_id, boss_kills=1)
    elif monster.get("is_elite"):
        db.bump_stats(group_id, qq_id, elite_kills=1)
    db.bump_stats(group_id, qq_id, kills=1, day_kills=1)
    # 图鉴记录 + 击杀对应势力声望
    db.bump_bestiary(group_id, qq_id, monster["name"])
    rep_lines = []
    area_key = monster.get("map_area")
    if area_key and area_key in _b143.AREA_FACTION:
        faction = _b143.AREA_FACTION[area_key]
        rep_gain = 5 if monster.get("is_boss") else (3 if monster.get("is_elite") else 1)
        # 世界事件声望加成（effects 数据驱动：rep_mult，如兽潮声望双倍）
        rep_gain = int(rep_gain * evt_effects.get("rep_mult", 1))
        db.add_reputation(group_id, qq_id, faction, rep_gain)
        if rep_gain > 1:
            rep_lines.append(f"🏛️ {_b143.FACTIONS[faction]['icon']} 声望 +{rep_gain}")
    return rep_lines


def roll_blueprint_drop(host, group_id, qq_id, player, monster, gold):
    """掉落（v93 经济改革：怪物永不掉装备——装备走铁匠铺购买 + 图纸锻造）
    v106 幸运：Boss 图纸惊喜掉率 ×(1+luck)（luck 上限 50%，roll_drop 内部 cap）"""
    db, C = host.db, host.C
    _luck_bp = 0.0
    try:
        _lst_bp = host.player_final_stats(player["class_name"], player["level"], player.get("equipment", {}),
                                          player.get("class_tier", 0), player.get("attributes"),
                                          player.get("evolve_path", 0), player.get("_title_bonus") or {}, player.get("race"))
        _luck_bp = min(float(_lst_bp.get("luck", 0) or 0), 0.5)
    except Exception:
        _luck_bp = 0.0
    drop_equip, drop_bp, _drop_gold, _drop_exp = C.roll_drop(_mon_lv(monster), monster["role"], _luck_bp)
    # 阶段九：半身人幸运儿——金币掉落 +15%
    if host.race_stats(player.get("race")).get("gold_bonus"):
        gold = int(gold * (1 + host.race_stats(player.get("race"))["gold_bonus"]))
    drop_lines = []
    if drop_bp:
        # v94 图纸经济：已学过的图纸自动折算图纸残页（普通1/优秀1/稀有2/史诗4/传说6）
        _learned = player.get("learned_blueprints") or []
        if drop_bp.get("blueprint_for") in _learned:
            _bpq = drop_bp.get("quality", "white")
            _pages = {"white": 1, "green": 1, "blue": 2, "purple": 4, "orange": 6}.get(_bpq, 1)
            db.add_item(group_id, qq_id, "mat_tu_zhi_can_ye",
                        {"name": "图纸残页", "type": "材料", "stackable": True, "price": 10},
                        count=_pages)
            drop_lines.append(f"📜 图纸已学会，化作 {_pages} 张图纸残页（『出售 图纸残页』变现）")
        else:
            import uuid
            bp_key = f"eq_{uuid.uuid4().hex[:8]}"
            db.add_item(group_id, qq_id, bp_key, drop_bp)
            # v56.4：掉落提示只显示名字，不把 desc 整段塞进括号（曾漏内部 ID）
            drop_lines.append(f"📜 掉落图纸：{drop_bp['name']}")
    return drop_equip, drop_lines, gold


def roll_equip_drop(host, group_id, qq_id, monster, drop_equip, drop_lines):
    """v140 装备掉落（鱼鱼拍板：打破 v93 铁律，精英/Boss 掉装备；普通怪仍不掉）
    精英=蓝/紫、Boss=紫/橙；与图纸 10% 独立判定共存
    v174 修复（精英专属死数据）：role=elite 且怪名命中 ELITE_EQUIP_DROP →
    走专属判定（专属紫装，15% 基础率，与旧精英掉率一致）；未命中走原通用池"""
    db, C = host.db, host.C
    if drop_equip is None and monster.get("role") in ("elite", "boss"):
        _elite_rid = None
        if monster.get("role") == "elite":
            _elite_rid = _cq.ELITE_EQUIP_DROP.get(monster.get("name", ""))
        if _elite_rid:
            # 专属判定：15% 基础率（与 roll_drop_equip elite 档一致，不吃幸运防叠加膨胀）
            if random.random() < _cc.ELITE_EQ_DROP_CHANCE:
                try:
                    drop_equip = C.generate_roster_equip(_elite_rid)
                except Exception:
                    drop_equip = None
        if drop_equip is None:
            drop_equip = C.roll_drop_equip(monster.get("lv", 0), monster.get("role"))
    if drop_equip:
        import uuid as _uuid2
        eq_key = f"eq_{_uuid2.uuid4().hex[:8]}"
        db.add_item(group_id, qq_id, eq_key, drop_equip)
        _qname = drop_equip.get("name", "")
        _qmark = {"green": "🟢", "blue": "🔵", "purple": "✨🟣", "orange": "🌟🟠"}.get(
            drop_equip.get("quality", ""), "")
        if drop_equip.get("quality") in ("purple", "orange"):
            drop_lines.append(f"{_qmark} 紫光流转，你拾起了【{_qname}】！(✦史诗·已收入背包)" if drop_equip.get("quality")=="purple" else f"{_qmark} 一道耀眼的金光冲天而起！【{_qname}】现世了！这件传说中的宝物，已收入你的背包！")
        else:
            drop_lines.append(f"{_qmark} 一道蓝光闪过，你拾起了【{_qname}】！" if drop_equip.get("quality")=="blue" else f"🎒 你拾起了【{_qname}】")
    return drop_lines


def roll_pet_egg(host, group_id, qq_id, monster):
    """v101.11 蛋掉落表数据化（data/pets.py PET_EGG_ROLL，加宠物/改概率不动代码）"""
    db, C = host.db, host.C
    pet_egg_line = ""
    egg_key = None
    for rule in _cl.PET_EGG_ROLL:
        ok = True
        if rule.get("role") and monster.get("role") != rule["role"]:
            ok = False
        if ok and rule.get("is_elite") and not monster.get("is_elite"):
            ok = False
        if ok and rule.get("is_boss") and not monster.get("is_boss"):
            ok = False
        if ok and rule.get("name_kw") and not any(k in monster.get("name", "") for k in rule["name_kw"]):
            ok = False
        if ok and random.random() < rule.get("rate", 0):
            egg_key = rule["key"]
            break
    if egg_key:
        egg = C.make_pet_egg(egg_key)
        db.add_item(group_id, qq_id, f"petegg_{egg_key}", egg)
        pet_egg_line = f"🥚 【{egg['name']}】从怪物身上掉下来了！『使用 宠物蛋』孵化！"  # v113.5 O97：去掉调试感"咦？"，改正式掉落文案
    return pet_egg_line


def roll_mount_drop(host, group_id, qq_id, monster):
    """v39 坐骑缰绳掉落（精英/Boss 概率，背包『使用』解锁坐骑）"""
    db, C = host.db, host.C
    mount_line = ""
    mk = C.roll_mount_drop(monster.get("role", ""))
    if mk:
        rein = C.make_mount_rein(mk)
        db.add_item(group_id, qq_id, f"mountrein_{mk}", rein)
        mount_line = f"🐾 战利品里有【{rein['name']}】！『使用 缰绳』驯服坐骑！"
    return mount_line


def roll_rune_drop(host, group_id, qq_id, monster):
    """v34 符文掉落（精英/Boss 概率 x3，品质越高越稀有，等级随品质浮动）
    v101.25i5 分层：普通怪只掉稀有；史诗/传说仅精英/Boss（鱼鱼：低级怪爆传说 III 不合理）"""
    db, C = host.db, host.C
    rune_line = ""
    roll = random.random()
    rune_quality = None
    is_elite_boss = monster.get("is_boss") or monster.get("is_elite")
    if is_elite_boss:
        for rq, w in sorted(_b143.RUNE_DROP.items(), key=lambda x: -x[1]):
            if roll < w * 3:
                rune_quality = rq
                break
            roll -= w * 3
    else:
        if roll < _b143.RUNE_DROP["blue"]:
            rune_quality = "blue"
    if rune_quality:
        cand_runes = [n for n, r in _ci.RUNES.items() if r["quality"] == rune_quality]
        if cand_runes:
            rname = random.choice(cand_runes)
            r_def = _ci.RUNES[rname]
            # 等级：稀有 1-2 级，史诗 1-3 级，传说 2-3 级（高等级更稀有）
            if rune_quality == "blue":
                r_lvl = random.randint(1, 2)
            elif rune_quality == "purple":
                r_lvl = random.randint(1, 3)
            else:
                r_lvl = random.randint(2, 3)
            rune_data = C.rune_item(r_def["effect"], r_lvl)
            db.add_item(group_id, qq_id, f"rune_{r_def['effect']}_{r_lvl}", rune_data)
            rune_line = f"💎 掉落了【{rune_data['name']}】！({rune_data['desc']})『附魔 <装备> {rune_data['name']}』使用"
    return rune_line


def roll_gem_drop(host, group_id, qq_id, monster):
    """v136 原石随机掉落（Phase 2 定稿：普通 2% / 精英 5% / 野外 Boss 15% / 副本 Boss 20%）。
    命中 1 颗随机原石（layer 范围按怪档查 GEM_DROP_TIER；Boss 专属固定属性倾向查
    GEM_BOSS_FIXED[怪物名]——裂鬃=pene_phys 破甲等）。掉落只吃 1 次 random.random()
    （roll_gem_drop 内部命中判定），不破坏存量战斗回归的随机序列（v103 确定性铁律）。
    不掉 999 上限：与材料/图纸同逻辑，正常随机 1 颗入包（key gem_<uuid8>）。"""
    db, C = host.db, host.C
    import uuid
    gem_line = ""
    try:
        _gem = C.roll_gem_drop(monster)
        if _gem:
            db.add_item(group_id, qq_id, f"gem_{uuid.uuid4().hex[:8]}", _gem)
            gem_line = f"💎 获得幸运宝石：{_gem['name']}！(『原石』镶嵌到装备孔位)"
    except Exception:
        gem_line = ""  # 掉落挂接失败不阻塞胜利结算（老档/数据缺失兜底）
    return gem_line


def rune_income(host, group_id, qq_id, player, exp, gold):
    """v34 符文收益：拾荒(金币+%) / 睿智(经验+%)——直接从已装备读符文"""
    C = host.C
    _rune_effs = {}
    for _slot, _it in (player.get("equipment") or {}).items():
        if _it:
            for _en in _it.get("enchant", []):
                if _en.get("effect"):
                    _lvl = int(_en.get("lvl", 1) or 1)
                    _rune_effs[_en["effect"]] = max(_rune_effs.get(_en["effect"], 0), _lvl)
    if _rune_effs.get("scavenger"):
        gold = int(gold * (1 + C.rune_value("scavenger", _rune_effs["scavenger"])))
    if _rune_effs.get("exp_bless"):
        exp = int(exp * (1 + C.rune_value("exp_bless", _rune_effs["exp_bless"])))
    return exp, gold


def lucky_charm(gold, player, now):
    """v54 幸运护符：10 分钟内打怪掉落价值 +50%（v93：金币改折算材料后，加成落在材料价值上）"""
    lucky_line = ""
    if int(player.get("lucky_until") or 0) > int(now):
        gold = int(gold * 1.5)
        lucky_line = "\n🍀 幸运护符生效：掉落价值 +50%！"
    return gold, lucky_line


def material_fold(host, group_id, qq_id, player, monster, gold, lucky_line):
    """v93 经济改革：金币不再入账，按 原金币×1.5 折算成 1-2 种可卖材料（怪物掉落池优先，通用池兜底）
    v106 幸运属性：掉落收益 ×(1+luck)（上限 50%），与幸运护符（+50%）独立叠加
    v106.1 聚宝属性：金币收益 ×(1+gold_bonus)（上限 50%），与幸运独立叠加
    注意：lucky_line 由段16 幸运护符产出后传入本函数续写（原实现同变量同位置）——
    _luck 命中且无护符行 → 幸运属性行；_gold_bonus 命中 → 聚宝行追加。"""
    db, C = host.db, host.C
    _luck = 0.0
    _gold_bonus = 0.0
    try:
        _lst = host.player_final_stats(player["class_name"], player["level"], player.get("equipment", {}),
                                       player.get("class_tier", 0), player.get("attributes"),
                                       player.get("evolve_path", 0), player.get("_title_bonus") or {}, player.get("race"))
        _luck = min(float(_lst.get("luck", 0) or 0), 0.5)
        _gold_bonus = min(float(_lst.get("gold_bonus", 0) or 0), 0.5)
    except Exception:
        _luck = 0.0
        _gold_bonus = 0.0
    mat_value = int(gold * 1.5 * (1 + _luck) * (1 + _gold_bonus))
    if _luck > 0 and not lucky_line:
        lucky_line = f"\n🍀 幸运属性：掉落收益 +{int(_luck*100)}%！"
    if _gold_bonus > 0:
        lucky_line = (lucky_line or "") + f"\n💰 聚宝属性：金币收益 +{int(_gold_bonus*100)}%！"
    drop_lines = []
    if mat_value > 0:
        drop_pool = [m for m in (monster.get("drops") or []) if m and "图纸" not in str(m)]
        if not drop_pool:
            drop_pool = list(("兽肉", "狼皮", "蛇皮", "野猪牙"))
        is_hi = monster.get("is_elite") or monster.get("is_boss")
        picks = random.sample(drop_pool, min(2 if is_hi else 1, len(drop_pool)))
        per_val = mat_value / len(picks)
        for mat_name in picks:
            mid = host.resolve_drop(mat_name)
            if mid is None:
                continue
            if mid in _ci.MATERIALS:
                mprice = _ci.MATERIALS[mid].get("price", 0)
                if mprice <= 0:
                    continue
                # q7-5 审计：向下取整（原 round 会 ±1 抖动，低阶怪刷低价材料可能白拿）
                # v165 经济校准（2026-09-02 鱼鱼拍板）：材料按产出级涨价后数量已收敛，
                # cap 仅防 99 击穿/极端爆量：普通怪单种≤10、精英/Boss 单种≤20
                # （允许 5-15 个合理波动；材料涨价前 Lv52 月鹿掉 38 个、Boss 掉 99 才是问题）
                _n_cap = 20 if is_hi else 10
                n = max(1, min(_n_cap, int(per_val / mprice)))
                db.add_item(group_id, qq_id, mid,
                            {"name": C.display("materials", mid), "type": "材料",
                             "stackable": True, "price": mprice}, n)
                drop_lines.append(f"🎒 拾取材料：{C.display('materials', mid)} ×{n}（可到城镇商店/铁匠铺出售）")
            else:
                # v110 审计修复：掉落结算支持消耗品（副本钥匙 i_key_* 等，29 章发放链补全）
                _it = _ci.ITEMS.get(mid, {})
                db.add_item(group_id, qq_id, mid,
                            {"name": _it.get("name", mat_name), "type": _it.get("type", "消耗品"),
                             "stackable": True, "price": _it.get("price", 0)}, 1)
                drop_lines.append(f"🎒 拾取：{_it.get('name', mat_name)}×1（副本入场钥匙）")
    return lucky_line, drop_lines


def know_exp_bonus(host, group_id, qq_id, player, exp):
    """经验/金币（v93：只入经验，金币已折算成材料）
    v106.1 求知属性：战斗经验 ×(1+exp_bonus)（上限 50%），叠加在全部既有加成之后"""
    try:
        _lst_exp = host.player_final_stats(player["class_name"], player["level"], player.get("equipment", {}),
                                           player.get("class_tier", 0), player.get("attributes"),
                                           player.get("evolve_path", 0), player.get("_title_bonus") or {}, player.get("race"))
        _exp_bonus = min(float(_lst_exp.get("exp_bonus", 0) or 0), 0.5)
    except Exception:
        _exp_bonus = 0.0
    if _exp_bonus > 0:
        exp = int(exp * (1 + _exp_bonus))
        exp_bonus_line = f"\n📚 求知属性：经验 +{int(_exp_bonus*100)}%！"
    else:
        exp_bonus_line = ""
    return exp, exp_bonus_line


def grant_player_exp(host, group_id, qq_id, player, exp):
    """v95.19: 顺带同步 DB max_hp/max_mp 实时值（player 已由 Battle 刷新，防 get_player clamp 误伤）
    #262: 先更新 player dict 再落库——此前直接写库导致进度条显示旧值、
          _rule_fire 的 exp_gain 在旧基数上覆盖 DB（三连胜经验延迟到下一场才入账）
    重读点（等价替换 combat self._player）：db.get_player 落库后重读"""
    db = host.db
    player["exp"] = int(player.get("exp", 0)) + exp
    db.update_player(group_id, qq_id, exp=player["exp"], max_hp=player["max_hp"], max_mp=player["max_mp"])
    player = db.get_player(group_id, qq_id)
    # v95.19: 结算面板与战斗内口径一致（DB max_hp/max_mp 是注册/升级快照，换装备后过时）
    try:
        _st = host.player_final_stats(player["class_name"], player["level"], player.get("equipment", {}),
                                      player.get("class_tier", 0), player.get("attributes"),
                                      player.get("evolve_path", 0), player.get("_title_bonus") or {}, player.get("race"))
        player["max_hp"] = int(_st.get("max_hp", player.get("max_hp", 100)))
        player["max_mp"] = int(_st.get("max_mp", player.get("max_mp", _cc.DEFAULT_MAX_MP)))
    except Exception:
        pass
    return player


# ============ 纯渲染/判定单点（原样搬） ============

def next_step_hint(host, group_id, qq_id, player, monster) -> str:
    """v138.3 结算卡·下一步指引（峰终定律）：战斗胜利后给一条养成方向的短指引。

    优先级：可升级 → 装备可强化 → 日常未完成 → 探索继续。全部不满足则提示回城休整。
    数据驱动：读玩家等级/经验/金币，不写死数值；文案贴合奥兰迪亚西幻世界观。
    """
    C = host.C
    try:
        if not player:
            return ""
        lv = int(player.get("level", 1) or 1)
        exp = int(player.get("exp", 0) or 0)
        need = C.exp_to_next(lv) if hasattr(C, "exp_to_next") else 0
        if need and exp >= need:
            return f"✨ 经验已满——去『加点』突破吧，实力还能再进一步！"
        gold = int(player.get("gold", 0) or 0)
        if gold >= 500:
            return f"🛠️ 攒了点金币——回城去『铁匠铺』强化装备，讨伐更顺手！"
        # 探索引导：当前地图还有未探索区域
        cur_map = player.get("cur_map") or ""
        if cur_map:
            return f"🗺️ 继续『探索』{cur_map}，还有未知的角落等着你——"
        return f"⚔️ 继续讨伐，下一个猎物已在路上——"
    except Exception:
        return ""


def nearest_town(host, cur_map: str) -> str:
    """BFS 找离当前地图最近的城镇（战败回城用；与回城卷轴 economy._nearest_town 同逻辑，M22 P3）。"""
    from collections import deque
    C = host.C
    if cur_map in _sp.MAP_BY_ID and _sp.MAP_BY_ID[cur_map].get("type") == _cc.MAP_TYPE_TOWN:
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
            mm = _sp.MAP_BY_ID.get(nxt, {})
            if mm.get("type") == _cc.MAP_TYPE_TOWN:
                return nxt
            q.append((nxt, d + 1))
    return _cc.START_MAP


def red_until(host, qq_id) -> int:
    try:
        db = host.db
        return int(db.get_event_state(f"red_{qq_id}") or 0)
    except (ValueError, TypeError):
        return 0


def is_redname(host, qq_id) -> bool:
    return time.time() < red_until(host, qq_id)


def grant_worldboss_drop(host, group_id, qq_id, key):
    """v104 M06 P2-3：发放世界 Boss 特殊掉落（材料直接入库/缰绳生成坐骑道具）。返回物品中文名或 None"""
    db, C = host.db, host.C
    try:
        if key.startswith("mount_"):
            rein = C.make_mount_rein(key)
            db.add_item(group_id, qq_id, f"mountrein_{key}", rein)
            return rein["name"]
        if key in _ci.MATERIALS:
            db.add_item(group_id, qq_id, key,
                        {"name": C.display("materials", key), "type": "材料",
                         "stackable": True, "price": _ci.MATERIALS[key]["price"]})
            return C.display("materials", key)
    except Exception:
        return None
    return None


# ============ 大编排（命令层壳调用）：完整同步结算，返回结构化结果 ============

def _mon_lv(monster) -> int:
    """怪等级读口：**actor dict（引擎口径 `level`）与原始怪 dict（`lv`）都认**。

    ★ 2026-09-13 P0 修复（B10 收口后独立发现，**改前既有**）：命令层胜利结算传进来的是
      **actor dict**（`bridge.monster_to_actor` 把 `lv → level` 且**不透传 lv`），本文件
      原来 3 处直接 `monster["lv"]` → 每次击杀在结算段抛 `KeyError: 'lv'`
      （玩家拿不到经验/金币/掉落/胜利面板）。修复后同一用例出正常结算面板；
      原始怪 dict（`lv` 在位）逐字同前。
    """
    if not isinstance(monster, dict):
        return 1
    return int(monster.get("lv") or monster.get("level") or 1)


def victory_settle(host, group_id, qq_id, player, monster, result, extra_kills=None):
    """方案 A 主段编排：原 _handle_victory 1803–2201 段（加成+掉落+exp 结算+面板行骨架）
    按原顺序逐段原样串起；2202–2297 段（公会任务/升级/quest/野王/塔卫/成就/rule/
    _next_step/收尾）由命令层壳续做。

    #262: 行为规则(三连胜等)提前到进度条显示前触发——exp_gain 模板会同步 player["exp"]，
    进度条与公告口径一致（此前公告在面板之后才写库，玩家感知为经验延迟到下一场）

    返回 dict（供壳拼 lines 后 yield）。v181 L3-P4 收口：仅保留壳实际消费的 3 键——
    其余段中间量（exp/gold/各类 bonus/rep_lines……）已全部内联进 lines_pre 面板行，
    dict 键全仓零消费者，属死字段清理（玩家可见输出零变化）：
      lines_pre（完整面板行：进度条骨架 + 加成/掉落/图鉴声望/奖励各段行） /
      player（结算后重读 dict）/
      rule_txt（rule_fire("battle_win", win) 返回值——壳在 L2288 原位置追加）"""
    db, C = host.db, host.C
    _rule_fire = host.rule_fire

    # v155 防御（2026-09-01 玩家实战抓包）：_mon 可能来自旧存档恢复的残缺敌人
    # （enemies=[] 只有 enemy 兼容键 → _origin_enemy 缺 exp/gold）——.get 兜底防 KeyError
    exp = monster.get("exp", 0)
    gold = monster.get("gold", 0)
    # ---- 段1 等级差曲线 ----
    exp, _exp_note = exp_curve(exp, _mon_lv(monster), player["level"])
    # ---- 段2 组队 ----
    exp, party_bonus_line = party_exp_bonus(host, group_id, qq_id, exp)
    # ---- 段3 公会 ----
    exp, guild_bonus = guild_exp_bonus(host, qq_id, exp)
    # ---- 段4 宠物 ----
    exp, pet_bonus = pet_exp_gain(host, qq_id, exp, monster)
    # ---- 段5 坐骑 ----
    exp, mount_bonus = mount_exp_bonus(host, player, exp)
    # ---- 段6 世界事件 ----
    exp, gold, evt_bonus, evt_effects = world_event_bonus(host, group_id, qq_id, exp, gold)
    # ---- 段7 每日运势 ----
    exp, gold, fortune_line = fortune_bonus(host, group_id, qq_id, exp, gold)
    if fortune_line:
        evt_bonus.append(fortune_line)
    # ---- 段8 任务统计/图鉴/声望 ----
    rep_lines = bump_kill_stats(host, group_id, qq_id, monster, evt_effects)
    # ---- 段9 图纸掉落 ----
    drop_equip, drop_lines, gold = roll_blueprint_drop(host, group_id, qq_id, player, monster, gold)
    # ---- 段10 装备掉落 ----
    drop_lines = roll_equip_drop(host, group_id, qq_id, monster, drop_equip, drop_lines)
    # ---- 段11 宠物蛋 ----
    pet_egg_line = roll_pet_egg(host, group_id, qq_id, monster)
    # ---- 段12 坐骑缰绳 ----
    mount_line = roll_mount_drop(host, group_id, qq_id, monster)
    # ---- 段13 符文 ----
    rune_line = roll_rune_drop(host, group_id, qq_id, monster)
    # ---- 段14 原石 ----
    gem_line = roll_gem_drop(host, group_id, qq_id, monster)
    # ---- 段15 符文收益 ----
    exp, gold = rune_income(host, group_id, qq_id, player, exp, gold)
    # ---- 段16 幸运护符 ----
    gold, lucky_line = lucky_charm(gold, player, time.time())
    # ---- 段17 材料折算（drop_lines 与段9 图纸/段10 装备同一列表——原实现同变量，
    # 折算追加在掉落行末尾，随后一起进面板 lines += drop_lines） ----
    lucky_line, _mat_lines = material_fold(host, group_id, qq_id, player, monster, gold, lucky_line)
    drop_lines += _mat_lines
    # ---- 段18 求知 ----
    exp, exp_bonus_line = know_exp_bonus(host, group_id, qq_id, player, exp)
    # ---- 段19 exp 落库/重读 ----
    player = grant_player_exp(host, group_id, qq_id, player, exp)
    # ---- 段20 rule_fire（原 L2167 位置：进度条前） ----
    # 签名照抄 base._rule_fire：fire(group_id, qq_id, player, cur_map, trigger, evt, hooks)
    _rule_txt = _rule_fire(group_id, qq_id, player,
                           _sp.MAP_BY_ID.get(player.get("cur_map"), {}),
                           "battle_win",
                           {"event": "win", "enemy": monster},
                           hooks={"title_bonus": lambda q: host.stat_bonus(group_id, q, db.get_player(group_id, q) or {})})
    # ---- 段21 面板行骨架 ----
    need = C.exp_to_next(player["level"])
    exp_pct = min(100, int(player["exp"] / need * 100)) if need else 0
    lines = [result, f"🎉 你击败了【{monster['name']}】！",
             f"✨ 经验 +{exp}",
             f"📈 经验进度 {player['exp']}/{need} ({exp_pct}%)"]
    if _exp_note:
        lines.insert(3, _exp_note)
    if lucky_line:
        lines.append(lucky_line.strip())
    if exp_bonus_line:
        lines.append(exp_bonus_line.strip())
    if party_bonus_line:
        lines.append(party_bonus_line.strip())
    lines += drop_lines
    if gem_line:
        lines.append(gem_line)
    if rune_line:
        lines.append(rune_line)
    if pet_egg_line:
        lines.append(pet_egg_line)
    if mount_line:
        lines.append(mount_line)
    if rep_lines:
        lines += rep_lines
    if guild_bonus:
        lines += guild_bonus
    if pet_bonus:
        lines += pet_bonus
    if mount_bonus:
        lines += mount_bonus
    if evt_bonus:
        lines += evt_bonus
    return {
        # v181 L3-P4 收口：16 个无消费者返回键已删（全仓仅壳消费 lines_pre/player/rule_txt）
        "lines_pre": lines,
        "player": player,
        "rule_txt": _rule_txt,
    }


def defeat_settle(host, group_id, qq_id, player, monster, result):
    """战败：扣金币/回城（不扣宠物饱食度——宽容设计，见胜利路径 1475 注释）
    全同步编排（原 _handle_defeat 2347–2411）：
    unlock/clear/stats/扣金/红名/nearest_town/羽毛挂起/落库 全在此完成；
    rule_fire(lose) 触发点原样（L2394/L2409 在 yield 前）；
    yield 由壳根据 revive_state 走对应文案分支。

    返回 dict：
      lines（复羽毛/普通两分支完整文案行——壳 "\\n".join 后 yield）
      revive_state：复活羽毛分支写 revive_choice_{gid}_{qid} 时非 None（dict），
                    否则 None（普通分支）
      player：结算后 dict（hp/mp 已回满、cur_map/cur_subarea 已落城镇）"""
    db, C = host.db, host.C
    _rule_fire = host.rule_fire

    db.init_stats(group_id, qq_id)
    db.bump_stats(group_id, qq_id, deaths=1)
    lost = int(player["gold"] * 0.1)
    new_gold = max(0, player["gold"] - lost)
    lines = [f"{result}", f"💀 你倒下了……被【{monster['name']}】击败。"]
    # v84 红名死亡惩罚（26 章三 第二档）：红名期间死亡额外掉 10%（上限 2000）
    extra = 0
    if is_redname(host, qq_id):
        extra = min(int(player["gold"] * 0.1), 2000)
        new_gold = max(0, new_gold - extra)
    # 回城并满血（新手保护；v86 子区域：落中心广场）
    # v95.19: max_hp/max_mp 同步实时值（player 已由 Battle 刷新），DB 字段不再过时
    # M22 P3 修复：战败回最近城镇（原固定回橡木镇 START_MAP——Lv.60+ 也被送回 Lv.1 图），
    # 落该城中心广场（subareas[0]，与方碑传送/回城卷轴同款落点）
    _town_id = nearest_town(host, player.get("cur_map", ""))
    _town_sas = _sp.MAP_BY_ID.get(_town_id, {}).get("subareas") or []
    _town_sa = _town_sas[0]["id"] if _town_sas else ""
    _town_name = _sp.MAP_BY_ID.get(_town_id, {}).get("name", "城镇")
    _town_sa_name = _town_sas[0]["name"] if _town_sas else "广场"
    # O119 复活羽毛：背包有复活羽毛 → 战败结算提示『消耗复活羽毛？或损失金币』。
    # 先回城满血（玩家已阵亡不能滞留），金币扣款挂起到 revive_confirm 二段回复
    # （回复『使用复活羽毛』免扣，『放弃复活』按原损失结算；超时按损失兜底）。
    feather_n = 0
    try:
        feather_n = int(db.count_item(group_id, qq_id, "i_fu_huo_yu_mao") or 0)
    except Exception:
        feather_n = 0
    if feather_n > 0:
        import json as _json
        import time as _time
        db.set_event_state(f"revive_choice_{group_id}_{qq_id}", _json.dumps({
            "ts": _time.time(),
            "lost": lost,
            "extra": extra,
            "monster": monster.get("name", "?"),
        }, ensure_ascii=False))
        db.update_player(group_id, qq_id, hp=player["max_hp"], mp=player["max_mp"],
                         max_hp=player["max_hp"], max_mp=player["max_mp"],
                         cur_map=_town_id, cur_subarea=_town_sa)
        _pen = f"{lost} 金币" + (f"(红名额外 {extra})" if extra else "")
        lines.append(
            f"🪶 背包里的复活羽毛泛起微光！回复『使用复活羽毛』消耗 1 根，免于损失 {_pen}；"
            f"或回复『放弃复活』损失 {_pen}。\n"
            f"你已被送回{_town_name}·{_town_sa_name}，休息后满血复活。"
        )
        # v97.5 行为彩蛋规则：战败（用于清零连胜等计数，不产出彩蛋）
        # 签名照抄 base._rule_fire：fire(group_id, qq_id, player, cur_map, trigger, evt, hooks)
        _rule_fire("battle_win", group_id, qq_id, player,
                   _sp.MAP_BY_ID.get(player.get("cur_map"), {}),
                   {"event": "lose"},
                   hooks={"title_bonus": lambda q: host.stat_bonus(group_id, q, db.get_player(group_id, q) or {})})
        return {"lines": lines, "revive_state": {"lost": lost, "extra": extra,
                                                 "monster": monster.get("name", "?")},
                "player": player}
    if extra:
        lines.append(f"☠️ 红名期间死亡：额外损失 {extra} 金币(上限 2000)！")
    db.update_player(group_id, qq_id, gold=new_gold, hp=player["max_hp"], mp=player["max_mp"],
                     max_hp=player["max_hp"], max_mp=player["max_mp"],
                     cur_map=_town_id, cur_subarea=_town_sa)
    lines.append(
        f"你丢失了 {lost} 金币（战败损失 10% 金币），被好心人送回了{_town_name}·{_town_sa_name}。\n"
        f"休息后满血复活！下次要小心啊，冒险者。"
    )
    # v97.5 行为彩蛋规则：战败（用于清零连胜等计数，不产出彩蛋）
    # 签名照抄 base._rule_fire：fire(group_id, qq_id, player, cur_map, trigger, evt, hooks)
    _rule_fire("battle_win", group_id, qq_id, player,
               _sp.MAP_BY_ID.get(player.get("cur_map"), {}),
               {"event": "lose"},
               hooks={"title_bonus": lambda q: host.stat_bonus(group_id, q, db.get_player(group_id, q) or {})})
    return {"lines": lines, "revive_state": None, "player": player}
