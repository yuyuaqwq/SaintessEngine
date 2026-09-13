# -*- coding: utf-8 -*-
"""《奥兰迪亚·余烬纪年》战斗结算策略进包（`content/settlement.py`）

真源（游戏仓 `dragonfall/`，**只读**，本批零改动）
--------------------------------------------------
| 真源 | 行数 | 本批搬什么 |
|---|---:|---|
| `game/services/battle_settlement.py` | 795 | **策略半边**：经验曲线 / 六类加成 / 掉落 roll / 材料折算 / 结算编排（回放计划） |
| `game/reward.py`（原 `game/core/reward.py`） | 225 | **不搬**：整文件是「确定奖励发放」编排（`db.get_player` → `check_player_level_up` → `db.update_player` → `db.add_item`），策略含量为零。只把它的 **REWARD dict 契约**登记成调用方接口（见 §四），本模块产出 `grants` 供其消费 |

归属判据（`engine-package-host-split` §0）：**通用的进引擎 / 内容性的进包 / 接人的留宿主**。
本模块全在判据 2：经验曲线、加成链、掉落 roll、材料折算，换个游戏就得整段重写。

搬了什么（逐字搬 `battle_settlement.py` 正文，只动宿主耦合处）
--------------------------------------------------------------
1. 纯公式（原文一字未改，仅函数名去 `_` / 参数去 `self`）：
   `exp_curve`(:50) · `rune_income`(:387) · `lucky_charm`(:403) · `know_exp_bonus`(:473) ·
   `next_step_hint`(:518) · `nearest_town`(:544 BFS) · `red_until`(:566) · `is_redname`(:574) ·
   外加逐字小工具 `pct_str`（`game/data/pets.py:214`，`pet_exp_gain` 的文案依赖它）。
2. 宿主耦合处 → **调用方传 dict / 回调**（真源 `db.*` 读 + `C.<表>` 取值的替身，见 §二）：
   `party_exp_bonus`(:73) · `guild_exp_bonus`(:86) · `pet_exp_gain`(:99) · `mount_exp_bonus`(:139) ·
   `world_event_bonus`(:150) · `fortune_bonus`(:179) · `plan_kill_stats`(:201) ·
   `roll_blueprint_drop`(:225) · `roll_equip_drop`(:263) · `roll_pet_egg`(:296) ·
   `roll_mount_drop`(:321) · `roll_rune_drop`(:333) · `roll_gem_drop`(:368) · `material_fold`(:412)
3. 编排（原文 `victory_settle`(:598) / `defeat_settle`(:710) 的**段序原样**，但**只回放计划**）：
   `victory_settle_plan` / `defeat_settle_plan` —— 段 1..21 / 全同步段照原顺序串联，
   返回结构化 dict（exp / gold / lines / grants / 目标城镇 / 复活状态）；
   **落库与发放全不做**（谁发多少 = plan，怎么发 = 调用方）。

不搬（宿主边界，逐条给理由）
----------------------------
| 真源 | 为什么不搬 |
|---|---|
| `grant_player_exp`(:493) | `db.update_player` + `db.get_player` 重读 + max_hp/max_mp 实时化 = 存档读写，属宿主 |
| `bump_kill_stats`(:201) 的 db 半边 | `init_stats/bump_stats/bump_bestiary/add_reputation` 全为落库；**数值决策**已搬成 `plan_kill_stats` |
| `world_event_bonus` 的 `db.bump_stats(world_events=1)`(:160-164) | 世界事件参与统计落库 |
| `grant_worldboss_drop`(:578) | `db.add_item` + `C.make_mount_rein`（世界 Boss 发放链，掉落引擎未进包） |
| `pet_exp_gain` 的 `db.pet_update`（饱食度 -2 / exp / level） | 落库；**升级循环 / 封顶 / 加成算术**已搬（返回 `pet_after`） |
| `victory_settle` 段 20 的 `rule_fire`、段 9-14 的 `db.add_item` | 引擎 hook 触发 / 入包落库 —— 计划里以 `rule_trigger` / `grants` 表达 |
| `defeat_settle` 的 `db.update_player` / `set_event_state(revive_choice…)` / `count_item` | 落库 / 存档；`feather_count` 由调用方传入 |
| `reward.py` 全文件（225 行） | 纯发放编排（见上） |

§二 替身接口（`io` / `ctx` dict 的键 = 宿主耦合点的归档清单）
------------------------------------------------------------
**宿主读**（一次读一个，语义 = 真源 `db.*` 的等价物；包内只接 dict / 标量）：
```
party_members    db.party_members(group_id, qq_id)     → [qq_id, …]（含自己）
guild            db.guild_get_by_member(qq_id)         → {"level": int, …} | None
pet              db.pet_decay_satiety(db.pet_get(qq_id)) → pet dict | None（**宿主先衰减**）
world_event      db.get_world_event()                  → {"etype": …, "data": {…}} | None
fortune_state    db.get_event_state(f"daily_fortune_{g}_{q}") → 原始字符串 | None
red_state        db.get_event_state(f"red_{qq}")        → 原始字符串 | None
feather_count    db.count_item(group_id, qq_id, "i_fu_huo_yu_mao") → int
final_stats      content/panel.player_final_stats(…)   → luck/gold_bonus/exp_bonus（本包 panel.py）
mount_effects    C.mount_effects(player)               → {"exp_mult": …}（坐骑域未进包）
now / today      time.time() / date.today().isoformat()（墙上时间 = 宿主）
```
**内容表**（已进包的域直接读 `content/data|rules/*.json`；**未进包**的本批由调用方传，缺口见 §三）：
```
guild_config · world_event_pool · area_faction · factions · materials · items · resolve_drop ·
display · egg_rules · rune_drop · runes · rune_item · rune_value · pet_cfg · exp_to_next ·
elite_equip_drop · elite_eq_drop_chance · maps
```
**掉落引擎回调**（`game/drop_engine.py` + `game/core/{drops,runes,pets,mounts}.py` 未进包 → 调用方注入）：
```
roll_drop · roll_drop_equip · roll_gem_drop · roll_mount_drop ·
make_pet_egg · make_mount_rein · generate_roster_equip · race_stats
```

§三 已知缺口（本批**发现**、未解决，附证据）
--------------------------------------------
1. **`pets.json` 丢了 `PET_EGG_ROLL` 的规则顺序**（真源 `game/data/pets.py:112` 是
   `[pet_wolf, pet_salamander, pet_fox, pet_cat, pet_panther, pet_bat, pet_armadillo, pet_drake,
   pet_thunderbird, pet_griffin]`；包内 10 条 `egg_roll` 按 **key 字典序**落盘）。
   `roll_pet_egg` 命中序敏感（先命中先 break，且**只有条件满足才掷一次 random**）→
   顺序漂 = 掉落漂。本批以 `egg_rules` 传参绕开，并把「导出器补一条有序规则表」登记为缺口。
2. 掉落引擎（`roll_drop` / `roll_drop_equip` / `roll_gem_drop` / `roll_mount_drop`）、符文域
   （`RUNES` / `RUNE_DROP` / `rune_item`）、材料域（`MATERIALS` / `resolve_drop` / `display`）、
   宠物成长表（`pet_exp_need` / `pet_exp_mult` / `pet_exp_bonus`）、公会表、世界事件池、
   地图拓扑（`MAP_BY_ID` / `MAP_CONNECTIONS`）、名册装备生成 —— 均**未进包**（属后续批），
   本批一律走 §二 的替身接口。

§四 预算口径（与真源逐字一致处）
--------------------------------
* 加法/乘法/取整顺序、`int()` 截断方向、封顶值、文案 emoji 与空格，逐字照抄（`int()` 处**不改成 round**）。
* 随机数消费**顺序与次数**照抄：`roll_rune_drop`（1 次 `random()` → `choice` → `randint`）、
  过滤后才掷的 `roll_pet_egg`、`material_fold` 的 `sample`、`roll_equip_drop` 的专属判定。
* `reward.py` 的 REWARD dict 契约（调用方发放入口，本模块只产出 `grants` 列表）：
  `{"exp": int, "gold": int, "items": [{"item": key, "n": count}]}`。
"""
from __future__ import annotations

import json
import uuid


# ============================================================================
# §一 纯策略单点（真源正文逐字；宿主耦合处换参数）
# ============================================================================

def pct_str(x: float) -> str:
    """百分比显示：0.5 → '0.5'，5.0 → '5'（去尾零）。逐字 `game/data/pets.py:214`。"""
    s = f"{x * 100:.1f}"
    return s[:-2] if s.endswith(".0") else s


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


def party_exp_bonus(exp, party_members):
    """组队经验 +10%（队长队员同样生效，design 29 章 2.1 表）
    v95.29 #270：队伍行按 (group_id, leader) 记，队员反查必须同一 group_id——
    曾误写成全局查导致"群聊组队后私聊也吃加成"（#52 关联反馈）；同群组队本就有群内限制。

    真源 :73 `_pm = db.party_members(group_id, qq_id)` → 调用方传 `party_members`（含自己）。"""
    _pm = party_members or []
    party_bonus_line = ""
    if _pm:
        exp = int(exp * 1.1)
        party_bonus_line = f"\n🤝 组队加成：经验 +10%（与 {len(_pm) - 1} 名队友同行）"
    return exp, party_bonus_line


def guild_exp_bonus(exp, guild, guild_config):
    """公会经验加成（等级越高加成越多，上限 20%）

    真源 :86 `g = db.guild_get_by_member(qq_id)` → 调用方传 `guild` dict；
    `C.GUILD_CONFIG` → 调用方传 `guild_config`（公会域未进包，见 §三.2）。"""
    guild_bonus = []
    g = guild
    if g:
        gb = min(g["level"] * guild_config["exp_bonus_per_level"], guild_config["max_bonus"])
        if gb > 0:
            exp = int(exp * (1 + gb))
            guild_bonus.append(f"🏰 公会加成：经验 +{int(gb*100)}%")
    return exp, guild_bonus


def pet_exp_gain(exp, pet, monster, pet_cfg):
    """宠物经验加成（24 章五 v133.2 品质分级：等级×品质每级加成，cap 5~30%；饱食度 >0 全额，=0 减半）

    真源 :99 的宿主耦合三处 → 替身：
      `db.pet_decay_satiety(db.pet_get(qq_id))` → 调用方传**已衰减**的 pet dict
      `C.pet_exp_bonus / pet_exp_need / pet_exp_mult / PET_MAX_LEVEL / PET_SKILL_UNLOCK_LV`
        → `pet_cfg = {"max_level", "skill_unlock_lv", "exp_bonus"(pet), "exp_need"(lv), "exp_mult"(plv, mlv)}`
      `db.pet_update(…)` → 返回 `pet_after`（satiety -2 / exp / level），**调用方落库**
    返回 (exp, pet_bonus 行, pet_after|None)。"""
    pet_bonus = []
    pet_after = None
    if pet:
        pb = pet_cfg["exp_bonus"](pet)
        if pet["satiety"] <= 0:
            pb = pb / 2  # 饱食度 =0：经验加成减半
        if pb > 0:
            exp = int(exp * (1 + pb))
            ptag = "🐾 陪伴(饱食度归零，加成减半)" if pet["satiety"] <= 0 else "🐾 陪伴"
            pet_bonus.append(f"{ptag}：经验 +{pct_str(pb)}%")
        # v104 M17 P3：亲密度≥50 → 战斗经验 +5%（bond 消费方，面板见 social.py pet_view）
        if pet.get("bond", 0) >= 50:
            exp = int(exp * 1.05)
            pet_bonus.append("💕 羁绊(亲密度≥50)：经验 +5%")
        # 战斗消耗饱食度 -2（先自然衰减再扣战斗消耗）→ pet_after（调用方落库）
        # v105 M17 P3-5 设计说明：仅胜利路径扣除。24 章四"每场战斗 -2"字面含败北/逃跑，
        # 但当前为对玩家的宽容设计——败北已有金币惩罚+回城，逃跑无惩罚，不再叠加扣粮；改动需策划拍板
        # 宠物分得经验（24 章四：击杀怪宠物分得经验，取怪物基础经验 20%）
        # v173.2：加等级差乘区（宠物 vs 怪，复用玩家非线性曲线），封顶 Lv.50→PET_MAX_LEVEL
        p_gain = max(1, int(monster["exp"] * 0.2 * pet_cfg["exp_mult"](int(pet.get("level", 1) or 1), monster["lv"])))
        p_exp = pet["exp"] + p_gain
        p_lv = pet["level"]
        p_lvup = False
        while p_lv < pet_cfg["max_level"] and p_exp >= pet_cfg["exp_need"](p_lv):
            p_exp -= pet_cfg["exp_need"](p_lv)
            p_lv += 1
            p_lvup = True
        if p_lv >= pet_cfg["max_level"]:
            p_exp = min(p_exp, pet_cfg["exp_need"](pet_cfg["max_level"]) - 1)  # 封顶溢出封存
        pet_after = dict(pet, satiety=max(0, pet["satiety"] - 2),
                         last_sat_time=pet["last_sat_time"], exp=p_exp, level=p_lv)
        if p_lvup:
            pet_bonus.append(f"🎉 宠物升到 Lv.{p_lv}！(Lv.{int(pet_cfg['skill_unlock_lv'])} 解锁宠物技能)"
                             if p_lv == int(pet_cfg["skill_unlock_lv"])
                             else (f"🎉 宠物升到 Lv.{p_lv}！(已满级)"
                                   if p_lv >= pet_cfg["max_level"] else f"🎉 宠物升到 Lv.{p_lv}！"))
    return exp, pet_bonus, pet_after


def mount_exp_bonus(exp, mount_effects):
    """v101.13 坐骑 exp_mult：骑乘加成类坐骑战斗经验加成（幽灵马/狮鹫/炎蹄战马）

    真源 :139 `C.mount_effects(player)` → 调用方传 `mount_effects` dict（坐骑域未进包）。"""
    mount_bonus = []
    meff = mount_effects or {}
    em = float(meff.get("exp_mult", 0) or 0)
    if em > 0:
        exp = int(exp * (1 + em))
        mount_bonus.append(f"🐎 坐骑疾驰：经验 +{int(em*100)}%")
    return exp, mount_bonus


def world_event_bonus(exp, gold, world_event, world_event_pool):
    """世界事件加成（effects 数据驱动：按 etype 查 WORLD_EVENT_POOL 定义拿 effects，
    db 的 world_event 仅存 etype/ends_at/data；查不到 = 无加成）

    真源 :150 `db.get_world_event()` → 调用方传 `world_event`；`:160-164` 的
    `db.init_stats / db.bump_stats(world_events=1)` 是**落库**（未搬，调用方按需自理）。"""
    evt_bonus = []
    evt_effects = {}
    cur_evt = world_event
    if cur_evt:
        evt_def = next((e for e in world_event_pool if e["type"] == cur_evt["etype"]), None)
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


def fortune_bonus(exp, gold, fortune_state, today):
    """v87 02 章 7.6：每日运势加成（大吉 经验+10% / 小凶 金币-10%）

    真源 :179 `db.get_event_state(f"daily_fortune_{group_id}_{qq_id}")` + `date.today()`
      → 调用方传 `fortune_state`（原始字符串）与 `today`（ISO 日期串）。"""
    fortune_line = ""
    try:
        _fstate = fortune_state
        if _fstate:
            _f = json.loads(_fstate)
            if _f.get("date") == today:
                if _f.get("fortune") == "大吉":
                    exp = int(exp * 1.10)
                    fortune_line = "🌟 今日大吉：经验 +10%！"
                elif _f.get("fortune") == "小凶":
                    gold = int(gold * 0.90)
                    fortune_line = "🌧️ 今日小凶：掉落价值 -10%……"
    except Exception:
        pass
    return exp, gold, fortune_line


def plan_kill_stats(monster, evt_effects, area_faction, factions):
    """任务统计 + 图鉴 + 势力声望 —— **只回放计划**（真源 `bump_kill_stats` :201 的数值决策半边）。

    真源原文把 5 类落库混在一条链上（init_stats / bump_stats×N / bump_bestiary / add_reputation）；
    本函数只算「给谁加多少」，返回：
      {"stats": {kills/elite_kills/boss_kills/day_kills: +1}, "bestiary": 怪名|None,
       "reputation": {"faction": f, "gain": g}|None, "lines": [声望播报行]}
    声誉**必须无条件回放**（真源 gain<=1 也照发，只是不播报）。"""
    stat_deltas = {}
    if monster.get("is_boss"):
        stat_deltas["boss_kills"] = 1
    elif monster.get("is_elite"):
        stat_deltas["elite_kills"] = 1
    stat_deltas["kills"] = 1
    stat_deltas["day_kills"] = 1
    rep_lines = []
    reputation = None
    area_key = monster.get("map_area")
    if area_key and area_key in area_faction:
        faction = area_faction[area_key]
        rep_gain = 5 if monster.get("is_boss") else (3 if monster.get("is_elite") else 1)
        # 世界事件声望加成（effects 数据驱动：rep_mult，如兽潮声望双倍）
        rep_gain = int(rep_gain * evt_effects.get("rep_mult", 1))
        reputation = {"faction": faction, "gain": rep_gain}
        if rep_gain > 1:
            rep_lines.append(f"🏛️ {factions[faction]['icon']} 声望 +{rep_gain}")
    return {"stats": stat_deltas, "bestiary": monster.get("name") or None,
            "reputation": reputation, "lines": rep_lines}


# ============================================================================
# §二 掉落 roll（随机数消费顺序照抄；入包/落库 → grants 计划）
# ============================================================================

def roll_blueprint_drop(player, monster, gold, stats, roll_drop, race_stats):
    """掉落（v93 经济改革：怪物永不掉装备——装备走铁匠铺购买 + 图纸锻造）
    v106 幸运：Boss 图纸惊喜掉率 ×(1+luck)（luck 上限 50%，roll_drop 内部 cap）

    真源 :225 三处宿主耦合 → 替身：`player_final_stats(...)` 的产物由调用方算好传入（`stats`，
    包内 = `content/panel.player_final_stats`）；`C.roll_drop` / `race_stats` = 掉落引擎回调；
    `db.add_item` → `grants`（图纸残页 / 掉落的图纸实例）。
    返回 (drop_equip, drop_lines, gold, grants)。"""
    _luck_bp = 0.0
    try:
        _lst_bp = stats
        _luck_bp = min(float(_lst_bp.get("luck", 0) or 0), 0.5)
    except Exception:
        _luck_bp = 0.0
    drop_equip, drop_bp, _drop_gold, _drop_exp = roll_drop(monster["lv"], monster["role"], _luck_bp)
    # 阶段九：半身人幸运儿——金币掉落 +15%
    if race_stats(player.get("race")).get("gold_bonus"):
        gold = int(gold * (1 + race_stats(player.get("race"))["gold_bonus"]))
    drop_lines = []
    grants = []
    if drop_bp:
        # v94 图纸经济：已学过的图纸自动折算图纸残页（普通1/优秀1/稀有2/史诗4/传说6）
        _learned = player.get("learned_blueprints") or []
        if drop_bp.get("blueprint_for") in _learned:
            _bpq = drop_bp.get("quality", "white")
            _pages = {"white": 1, "green": 1, "blue": 2, "purple": 4, "orange": 6}.get(_bpq, 1)
            grants.append({"key": "mat_tu_zhi_can_ye", "count": _pages,
                           "data": {"name": "图纸残页", "type": "材料", "stackable": True, "price": 10}})
            drop_lines.append(f"📜 图纸已学会，化作 {_pages} 张图纸残页（『出售 图纸残页』变现）")
        else:
            bp_key = f"eq_{uuid.uuid4().hex[:8]}"
            grants.append({"key": bp_key, "count": 1, "data": drop_bp})
            # v56.4：掉落提示只显示名字，不把 desc 整段塞进括号（曾漏内部 ID）
            drop_lines.append(f"📜 掉落图纸：{drop_bp['name']}")
    return drop_equip, drop_lines, gold, grants


def roll_equip_drop(monster, drop_equip, drop_lines, elite_equip_drop, elite_eq_drop_chance,
                    roll_drop_equip, generate_roster_equip, rng):
    """v140 装备掉落（鱼鱼拍板：打破 v93 铁律，精英/Boss 掉装备；普通怪仍不掉）
    精英=蓝/紫、Boss=紫/橙；与图纸 10% 独立判定共存
    v174 修复（精英专属死数据）：role=elite 且怪名命中 ELITE_EQUIP_DROP →
    走专属判定（专属紫装，15% 基础率，与旧精英掉率一致）；未命中走原通用池

    真源 :263 → `C.ELITE_EQUIP_DROP` / `C.ELITE_EQ_DROP_CHANCE` / `C.roll_drop_equip` /
    `C.generate_roster_equip` 由调用方传；`random.random()` → `rng.random()`（**只在专属判定
    分支消费 1 次**，与真源同序）；`db.add_item` → `grants`。
    返回 (drop_lines, drop_equip, grants)。"""
    grants = []
    if drop_equip is None and monster.get("role") in ("elite", "boss"):
        _elite_rid = None
        if monster.get("role") == "elite":
            _elite_rid = elite_equip_drop.get(monster.get("name", ""))
        if _elite_rid:
            # 专属判定：15% 基础率（与 roll_drop_equip elite 档一致，不吃幸运防叠加膨胀）
            if rng.random() < elite_eq_drop_chance:
                try:
                    drop_equip = generate_roster_equip(_elite_rid)
                except Exception:
                    drop_equip = None
        if drop_equip is None:
            drop_equip = roll_drop_equip(monster.get("lv", 0), monster.get("role"))
    if drop_equip:
        eq_key = f"eq_{uuid.uuid4().hex[:8]}"
        grants.append({"key": eq_key, "count": 1, "data": drop_equip})
        _qname = drop_equip.get("name", "")
        _qmark = {"green": "🟢", "blue": "🔵", "purple": "✨🟣", "orange": "🌟🟠"}.get(
            drop_equip.get("quality", ""), "")
        if drop_equip.get("quality") in ("purple", "orange"):
            drop_lines.append(f"{_qmark} 紫光流转，你拾起了【{_qname}】！(✦史诗·已收入背包)" if drop_equip.get("quality")=="purple" else f"{_qmark} 一道耀眼的金光冲天而起！【{_qname}】现世了！这件传说中的宝物，已收入你的背包！")
        else:
            drop_lines.append(f"{_qmark} 一道蓝光闪过，你拾起了【{_qname}】！" if drop_equip.get("quality")=="blue" else f"🎒 你拾起了【{_qname}】")
    return drop_lines, drop_equip, grants


def roll_pet_egg(monster, egg_rules, make_pet_egg, rng):
    """v101.11 蛋掉落表数据化（data/pets.py PET_EGG_ROLL，加宠物/改概率不动代码）

    真源 :296 → `C.PET_EGG_ROLL` 由调用方传（⚠️ 包内 `pets.json` 的 `egg_roll` 按 key
    字典序落盘、**丢了真源规则顺序** → 见模块 §三.1，必须按真源顺序传）；
    `random.random()` → `rng.random()`（**条件全满足才掷**，与真源同序）；`db.add_item` → `grants`。
    返回 (pet_egg_line, grants)。"""
    pet_egg_line = ""
    egg_key = None
    grants = []
    for rule in egg_rules:
        ok = True
        if rule.get("role") and monster.get("role") != rule["role"]:
            ok = False
        if ok and rule.get("is_elite") and not monster.get("is_elite"):
            ok = False
        if ok and rule.get("is_boss") and not monster.get("is_boss"):
            ok = False
        if ok and rule.get("name_kw") and not any(k in monster.get("name", "") for k in rule["name_kw"]):
            ok = False
        if ok and rng.random() < rule.get("rate", 0):
            egg_key = rule["key"]
            break
    if egg_key:
        egg = make_pet_egg(egg_key)
        grants.append({"key": f"petegg_{egg_key}", "count": 1, "data": egg})
        pet_egg_line = f"🥚 【{egg['name']}】从怪物身上掉下来了！『使用 宠物蛋』孵化！"  # v113.5 O97：去掉调试感"咦？"，改正式掉落文案
    return pet_egg_line, grants


def roll_mount_drop(monster, roll_mount_drop, make_mount_rein):
    """v39 坐骑缰绳掉落（精英/Boss 概率，背包『使用』解锁坐骑）

    真源 :321 → `C.roll_mount_drop`（内部消费全局 random）/ `C.make_mount_rein` 由调用方传；
    `db.add_item` → `grants`。返回 (mount_line, grants)。"""
    mount_line = ""
    grants = []
    mk = roll_mount_drop(monster.get("role", ""))
    if mk:
        rein = make_mount_rein(mk)
        grants.append({"key": f"mountrein_{mk}", "count": 1, "data": rein})
        mount_line = f"🐾 战利品里有【{rein['name']}】！『使用 缰绳』驯服坐骑！"
    return mount_line, grants


def roll_rune_drop(monster, rune_drop, runes, rune_item, rng):
    """v34 符文掉落（精英/Boss 概率 x3，品质越高越稀有，等级随品质浮动）
    v101.25i5 分层：普通怪只掉稀有；史诗/传说仅精英/Boss（鱼鱼：低级怪爆传说 III 不合理）

    真源 :333 → `C.RUNE_DROP` / `C.RUNES` / `C.rune_item` 由调用方传（符文域未进包）；
    `random.random()` → `rng.random()`、`random.choice` → `rng.choice`、`random.randint` →
    `rng.randint`（**消费顺序/次数与真源一致**）；`db.add_item` → `grants`。
    返回 (rune_line, grants)。"""
    rune_line = ""
    grants = []
    roll = rng.random()
    rune_quality = None
    is_elite_boss = monster.get("is_boss") or monster.get("is_elite")
    if is_elite_boss:
        for rq, w in sorted(rune_drop.items(), key=lambda x: -x[1]):
            if roll < w * 3:
                rune_quality = rq
                break
            roll -= w * 3
    else:
        if roll < rune_drop["blue"]:
            rune_quality = "blue"
    if rune_quality:
        cand_runes = [n for n, r in runes.items() if r["quality"] == rune_quality]
        if cand_runes:
            rname = rng.choice(cand_runes)
            r_def = runes[rname]
            # 等级：稀有 1-2 级，史诗 1-3 级，传说 2-3 级（高等级更稀有）
            if rune_quality == "blue":
                r_lvl = rng.randint(1, 2)
            elif rune_quality == "purple":
                r_lvl = rng.randint(1, 3)
            else:
                r_lvl = rng.randint(2, 3)
            rune_data = rune_item(r_def["effect"], r_lvl)
            grants.append({"key": f"rune_{r_def['effect']}_{r_lvl}", "count": 1, "data": rune_data})
            rune_line = f"💎 掉落了【{rune_data['name']}】！({rune_data['desc']})『附魔 <装备> {rune_data['name']}』使用"
    return rune_line, grants


def roll_gem_drop(monster, roll_gem_drop):
    """v136 原石随机掉落（Phase 2 定稿：普通 2% / 精英 5% / 野外 Boss 15% / 副本 Boss 20%）。
    命中 1 颗随机原石（layer 范围按怪档查 GEM_DROP_TIER；Boss 专属固定属性倾向查
    GEM_BOSS_FIXED[怪物名]——裂鬃=pene_phys 破甲等）。掉落只吃 1 次 random.random()
    （roll_gem_drop 内部命中判定），不破坏存量战斗回归的随机序列（v103 确定性铁律）。
    不掉 999 上限：与材料/图纸同逻辑，正常随机 1 颗入包（key gem_<uuid8>）。

    真源 :368 → `C.roll_gem_drop`（掉落引擎，内部消费全局 random）由调用方传；
    `db.add_item` → `grants`。返回 (gem_line, grants)。"""
    gem_line = ""
    grants = []
    try:
        _gem = roll_gem_drop(monster)
        if _gem:
            grants.append({"key": f"gem_{uuid.uuid4().hex[:8]}", "count": 1, "data": _gem})
            gem_line = f"💎 获得幸运宝石：{_gem['name']}！(『原石』镶嵌到装备孔位)"
    except Exception:
        gem_line = ""  # 掉落挂接失败不阻塞胜利结算（老档/数据缺失兜底）
    return gem_line, grants


def material_fold(player, monster, gold, lucky_line, stats, materials, items, resolve_drop, display, rng):
    """v93 经济改革：金币不再入账，按 原金币×1.5 折算成 1-2 种可卖材料（怪物掉落池优先，通用池兜底）
    v106 幸运属性：掉落收益 ×(1+luck)（上限 50%），与幸运护符（+50%）独立叠加
    v106.1 聚宝属性：金币收益 ×(1+gold_bonus)（上限 50%），与幸运独立叠加
    注意：lucky_line 由段16 幸运护符产出后传入本函数续写（原实现同变量同位置）——
    _luck 命中且无护符行 → 幸运属性行；_gold_bonus 命中 → 聚宝行追加。

    真源 :412 → `player_final_stats(...)`产物 `stats`、`C.MATERIALS`/`C.ITEMS`/`C.display`/
    `resolve_drop` 由调用方传；`random.sample` → `rng.sample`；`db.add_item` → `grants`。
    返回 (lucky_line, drop_lines, grants)。"""
    _luck = 0.0
    _gold_bonus = 0.0
    try:
        _lst = stats
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
    grants = []
    if mat_value > 0:
        drop_pool = [m for m in (monster.get("drops") or []) if m and "图纸" not in str(m)]
        if not drop_pool:
            drop_pool = list(("兽肉", "狼皮", "蛇皮", "野猪牙"))
        is_hi = monster.get("is_elite") or monster.get("is_boss")
        picks = rng.sample(drop_pool, min(2 if is_hi else 1, len(drop_pool)))
        per_val = mat_value / len(picks)
        for mat_name in picks:
            mid = resolve_drop(mat_name)
            if mid is None:
                continue
            if mid in materials:
                mprice = materials[mid].get("price", 0)
                if mprice <= 0:
                    continue
                # q7-5 审计：向下取整（原 round 会 ±1 抖动，低阶怪刷低价材料可能白拿）
                # v165 经济校准（2026-09-02 鱼鱼拍板）：材料按产出级涨价后数量已收敛，
                # cap 仅防 99 击穿/极端爆量：普通怪单种≤10、精英/Boss 单种≤20
                # （允许 5-15 个合理波动；材料涨价前 Lv52 月鹿掉 38 个、Boss 掉 99 才是问题）
                _n_cap = 20 if is_hi else 10
                n = max(1, min(_n_cap, int(per_val / mprice)))
                grants.append({"key": mid, "count": n,
                               "data": {"name": display("materials", mid), "type": "材料",
                                        "stackable": True, "price": mprice}})
                drop_lines.append(f"🎒 拾取材料：{display('materials', mid)} ×{n}（可到城镇商店/铁匠铺出售）")
            else:
                # v110 审计修复：掉落结算支持消耗品（副本钥匙 i_key_* 等，29 章发放链补全）
                _it = items.get(mid, {})
                grants.append({"key": mid, "count": 1,
                               "data": {"name": _it.get("name", mat_name),
                                        "type": _it.get("type", "消耗品"),
                                        "stackable": True, "price": _it.get("price", 0)}})
                drop_lines.append(f"🎒 拾取：{_it.get('name', mat_name)}×1（副本入场钥匙）")
    return lucky_line, drop_lines, grants


def know_exp_bonus(exp, stats):
    """经验/金币（v93：只入经验，金币已折算成材料）
    v106.1 求知属性：战斗经验 ×(1+exp_bonus)（上限 50%），叠加在全部既有加成之后

    真源 :473 → `player_final_stats(...)` 产物由调用方传（`stats`）。"""
    try:
        _exp_bonus = min(float(stats.get("exp_bonus", 0) or 0), 0.5)
    except Exception:
        _exp_bonus = 0.0
    if _exp_bonus > 0:
        exp = int(exp * (1 + _exp_bonus))
        exp_bonus_line = f"\n📚 求知属性：经验 +{int(_exp_bonus*100)}%！"
    else:
        exp_bonus_line = ""
    return exp, exp_bonus_line


def rune_income(player, exp, gold, rune_value):
    """v34 符文收益：拾荒(金币+%) / 睿智(经验+%)——直接从已装备读符文

    真源 :387 → `C.rune_value` 由调用方传（符文域未进包）。"""
    _rune_effs = {}
    for _slot, _it in (player.get("equipment") or {}).items():
        if _it:
            for _en in _it.get("enchant", []):
                if _en.get("effect"):
                    _lvl = int(_en.get("lvl", 1) or 1)
                    _rune_effs[_en["effect"]] = max(_rune_effs.get(_en["effect"], 0), _lvl)
    if _rune_effs.get("scavenger"):
        gold = int(gold * (1 + rune_value("scavenger", _rune_effs["scavenger"])))
    if _rune_effs.get("exp_bless"):
        exp = int(exp * (1 + rune_value("exp_bless", _rune_effs["exp_bless"])))
    return exp, gold


def lucky_charm(gold, player, now):
    """v54 幸运护符：10 分钟内打怪掉落价值 +50%（v93：金币改折算材料后，加成落在材料价值上）

    真源 :403 → `now` 由调用方传（墙上时间 = 宿主）。"""
    lucky_line = ""
    if int(player.get("lucky_until") or 0) > int(now):
        gold = int(gold * 1.5)
        lucky_line = "\n🍀 幸运护符生效：掉落价值 +50%！"
    return gold, lucky_line


def next_step_hint(player, exp_to_next):
    """v138.3 结算卡·下一步指引（峰终定律）：战斗胜利后给一条养成方向的短指引。

    优先级：可升级 → 装备可强化 → 日常未完成 → 探索继续。全部不满足则提示回城休整。
    数据驱动：读玩家等级/经验/金币，不写死数值；文案贴合奥兰迪亚西幻世界观。

    真源 :518 → `C.exp_to_next` 由调用方传（`exp_to_next(lv) -> int | None`）。"""
    try:
        if not player:
            return ""
        lv = int(player.get("level", 1) or 1)
        exp = int(player.get("exp", 0) or 0)
        need = exp_to_next(lv) if exp_to_next else 0
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


def nearest_town(cur_map, maps):
    """BFS 找离当前地图最近的城镇（战败回城用；与回城卷轴 economy._nearest_town 同逻辑，M22 P3）。

    真源 :544 → `C.MAP_BY_ID` / `C.MAP_CONNECTIONS` / `C.MAP_TYPE_TOWN` / `C.START_MAP`
    由调用方以 `maps = {"by_id", "connections", "town_type", "start_map"}` 传入（地图域未进包）。"""
    from collections import deque
    if cur_map in maps["by_id"] and maps["by_id"][cur_map].get("type") == maps["town_type"]:
        return cur_map
    q = deque([(cur_map, 0)])
    seen = {cur_map}
    while q:
        m, d = q.popleft()
        if d >= 6:
            continue
        for nxt in maps["connections"].get(m, []):
            if nxt in seen:
                continue
            seen.add(nxt)
            mm = maps["by_id"].get(nxt, {})
            if mm.get("type") == maps["town_type"]:
                return nxt
            q.append((nxt, d + 1))
    return maps["start_map"]


def red_until(red_state):
    """真源 :566 `red_until(qq_id)`：`int(db.get_event_state(f"red_{qq_id}") or 0)`。
    替身：调用方传该 event_state 的**原始字符串**（None = 无记录 → 0）。"""
    try:
        return int(red_state or 0)
    except (ValueError, TypeError):
        return 0


def is_redname(red_state, now):
    """真源 :574 `is_redname(qq_id)` = `time.time() < red_until(qq_id)`。
    替身：`now` 由调用方传（墙上时间 = 宿主）。"""
    return now < red_until(red_state)


# ============================================================================
# §三 结算编排（返回「计划」，不落库 / 不发放）
# ============================================================================

def victory_settle_plan(player, monster, result, io):
    """方案 A 主段编排：原 `_handle_victory` 1803–2201 段的**策略半边**（加成+掉落 roll+exp 结算
    +面板行骨架），按原顺序逐段串起；`victory_settle` :598 的落库/发放/rule_fire 全部不做。

    与真源 :598 的差异（白名单，逐条可对照）：
      · 段 2/3/4/5/6/7 的 `db.*` 读 → `io[...]`（见模块 §二）
      · 段 8 图鉴/声望落库 → `plan_kill_stats`（计划）
      · 段 9-14 的 `db.add_item` → `grants`
      · 段 19 `grant_player_exp` → 只回放 `exp_after`（调用方落库）
      · 段 20 `rule_fire("battle_win")` → 计划里以 `rule_trigger` 表达（引擎 hook 由调用方触发）

    io 键（宿主读 + 内容表 + 掉落引擎回调）：见模块 §二；`io["final_stats"]` = 调用方用
    `content/panel.player_final_stats(...)` 算好的面板（luck/gold_bonus/exp_bonus）。
    返回 dict：
      lines（完整面板行，真源 `lines_pre`）、player（结算后 dict）、exp（本场经验）、
      exp_after（player.exp + exp，**调用方落库**）、gold（折材料前的最终金币）、
      grants（入包计划：key/count/data）、pet_after、kill_stats（统计/图鉴/声望计划）、
      rule_trigger（{"player","cur_map","trigger":"battle_win","event":"win","enemy"}）
    """
    # v155 防御（2026-09-01 玩家实战抓包）：_mon 可能来自旧存档恢复的残缺敌人
    # （enemies=[] 只有 enemy 兼容键 → _origin_enemy 缺 exp/gold）——.get 兜底防 KeyError
    exp = monster.get("exp", 0)
    gold = monster.get("gold", 0)
    stats = io.get("final_stats") or {}
    # ---- 段1 等级差曲线 ----
    exp, _exp_note = exp_curve(exp, monster["lv"], player["level"])
    # ---- 段2 组队 ----
    exp, party_bonus_line = party_exp_bonus(exp, io.get("party_members"))
    # ---- 段3 公会 ----
    exp, guild_bonus = guild_exp_bonus(exp, io.get("guild"), io["guild_config"])
    # ---- 段4 宠物 ----
    exp, pet_bonus, pet_after = pet_exp_gain(exp, io.get("pet"), monster, io["pet_cfg"])
    # ---- 段5 坐骑 ----
    exp, mount_bonus = mount_exp_bonus(exp, io.get("mount_effects"))
    # ---- 段6 世界事件 ----
    exp, gold, evt_bonus, evt_effects = world_event_bonus(
        exp, gold, io.get("world_event"), io["world_event_pool"])
    # ---- 段7 每日运势 ----
    exp, gold, fortune_line = fortune_bonus(exp, gold, io.get("fortune_state"), io["today"])
    if fortune_line:
        evt_bonus.append(fortune_line)
    # ---- 段8 任务统计/图鉴/声望（落库 → 计划） ----
    kill_stats = plan_kill_stats(monster, evt_effects, io["area_faction"], io["factions"])
    rep_lines = kill_stats["lines"]
    # ---- 段9 图纸掉落 ----
    drop_equip, drop_lines, gold, grants = roll_blueprint_drop(
        player, monster, gold, stats, io["roll_drop"], io["race_stats"])
    # ---- 段10 装备掉落 ----
    drop_lines, _drop_equip, _g = roll_equip_drop(
        monster, drop_equip, drop_lines, io["elite_equip_drop"], io["elite_eq_drop_chance"],
        io["roll_drop_equip"], io["generate_roster_equip"], io["rng"])
    grants += _g
    # ---- 段11 宠物蛋 ----
    pet_egg_line, _g = roll_pet_egg(monster, io["egg_rules"], io["make_pet_egg"], io["rng"])
    grants += _g
    # ---- 段12 坐骑缰绳 ----
    mount_line, _g = roll_mount_drop(monster, io["roll_mount_drop"], io["make_mount_rein"])
    grants += _g
    # ---- 段13 符文 ----
    rune_line, _g = roll_rune_drop(monster, io["rune_drop"], io["runes"], io["rune_item"], io["rng"])
    grants += _g
    # ---- 段14 原石 ----
    gem_line, _g = roll_gem_drop(monster, io["roll_gem_drop"])
    grants += _g
    # ---- 段15 符文收益 ----
    exp, gold = rune_income(player, exp, gold, io["rune_value"])
    # ---- 段16 幸运护符 ----
    gold, lucky_line = lucky_charm(gold, player, io["now"])
    # ---- 段17 材料折算（drop_lines 与段9 图纸/段10 装备同一列表——原实现同变量，
    # 折算追加在掉落行末尾，随后一起进面板 lines += drop_lines） ----
    lucky_line, _mat_lines, _g = material_fold(
        player, monster, gold, lucky_line, stats, io["materials"], io["items"],
        io["resolve_drop"], io["display"], io["rng"])
    drop_lines += _mat_lines
    grants += _g
    # ---- 段18 求知 ----
    exp, exp_bonus_line = know_exp_bonus(exp, stats)
    # ---- 段19 exp 落库/重读 → 只回放 exp_after（调用方落库 + 重读 player） ----
    exp_after = int(player.get("exp", 0)) + exp
    # ---- 段20 rule_fire（原 L2167 位置：进度条前）→ 计划 ----
    rule_trigger = {"player": player, "cur_map": io.get("cur_map_obj") or {},
                    "trigger": "battle_win", "event": {"event": "win", "enemy": monster}}
    # ---- 段21 面板行骨架 ----
    need = io["exp_to_next"](player["level"])
    exp_pct = min(100, int(exp_after / need * 100)) if need else 0
    lines = [result, f"🎉 你击败了【{monster['name']}】！",
             f"✨ 经验 +{exp}",
             f"📈 经验进度 {exp_after}/{need} ({exp_pct}%)"]
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
        "lines": lines,
        "player": dict(player, exp=exp_after),
        "exp": exp,
        "exp_after": exp_after,
        "gold": gold,
        "grants": grants,
        "pet_after": pet_after,
        "kill_stats": kill_stats,
        "rule_trigger": rule_trigger,
    }


def defeat_settle_plan(player, monster, result, io):
    """战败：扣金币/回城（不扣宠物饱食度——宽容设计，见胜利路径 1475 注释）
    原 `_handle_defeat` 2347–2411 的**决策半边**：unlock/clear（引擎侧）/stats/扣金/红名/
    nearest_town/羽毛挂起/落库 —— 本函数只算「扣多少 / 回哪座城 / 走哪条文案」，
    落库（`db.update_player` / `set_event_state`）与 `rule_fire` 全由调用方做。

    io 键：`maps`（地图拓扑）、`red_state`、`feather_count`、`now`。
    返回 dict：lines / gold_new / lost / extra / town_id / town_subarea / revive_state|None /
    stats（deaths+1 计划）/ rule_trigger / player（hp/mp 目标值已回满、cur_map/cur_subarea 已落城镇）。
    """
    stat_plan = {"deaths": 1}
    lost = int(player["gold"] * 0.1)
    new_gold = max(0, player["gold"] - lost)
    lines = [f"{result}", f"💀 你倒下了……被【{monster['name']}】击败。"]
    # v84 红名死亡惩罚（26 章三 第二档）：红名期间死亡额外掉 10%（上限 2000）
    extra = 0
    if is_redname(io.get("red_state"), io.get("now")):
        extra = min(int(player["gold"] * 0.1), 2000)
        new_gold = max(0, new_gold - extra)
    # 回城并满血（新手保护；v86 子区域：落中心广场）
    # v95.19: max_hp/max_mp 同步实时值（player 已由 Battle 刷新），DB 字段不再过时
    # M22 P3 修复：战败回最近城镇（原固定回橡木镇 START_MAP——Lv.60+ 也被送回 Lv.1 图），
    # 落该城中心广场（subareas[0]，与方碑传送/回城卷轴同款落点）
    _town_id = nearest_town(player.get("cur_map", ""), io["maps"])
    _town_sas = io["maps"]["by_id"].get(_town_id, {}).get("subareas") or []
    _town_sa = _town_sas[0]["id"] if _town_sas else ""
    _town_name = io["maps"]["by_id"].get(_town_id, {}).get("name", "城镇")
    _town_sa_name = _town_sas[0]["name"] if _town_sas else "广场"
    # O119 复活羽毛：背包有复活羽毛 → 战败结算提示『消耗复活羽毛？或损失金币』。
    # 先回城满血（玩家已阵亡不能滞留），金币扣款挂起到 revive_confirm 二段回复
    # （回复『使用复活羽毛』免扣，『放弃复活』按原损失结算；超时按损失兜底）。
    feather_n = 0
    try:
        feather_n = int(io.get("feather_count") or 0)
    except Exception:
        feather_n = 0
    _target_player = dict(player, hp=player["max_hp"], mp=player["max_mp"],
                          max_hp=player["max_hp"], max_mp=player["max_mp"],
                          cur_map=_town_id, cur_subarea=_town_sa)
    rule_trigger = {"player": player, "cur_map": io.get("cur_map_obj") or {},
                    "trigger": "battle_win", "event": {"event": "lose"}}
    if feather_n > 0:
        _pen = f"{lost} 金币" + (f"(红名额外 {extra})" if extra else "")
        lines.append(
            f"🪶 背包里的复活羽毛泛起微光！回复『使用复活羽毛』消耗 1 根，免于损失 {_pen}；"
            f"或回复『放弃复活』损失 {_pen}。\n"
            f"你已被送回{_town_name}·{_town_sa_name}，休息后满血复活。"
        )
        return {"lines": lines, "gold_new": player["gold"], "lost": lost, "extra": extra,
                "town_id": _town_id, "town_subarea": _town_sa, "stats": stat_plan,
                "revive_state": {"lost": lost, "extra": extra,
                                 "monster": monster.get("name", "?")},
                "rule_trigger": rule_trigger, "player": _target_player}
    if extra:
        lines.append(f"☠️ 红名期间死亡：额外损失 {extra} 金币(上限 2000)！")
    lines.append(
        f"你丢失了 {lost} 金币（战败损失 10% 金币），被好心人送回了{_town_name}·{_town_sa_name}。\n"
        f"休息后满血复活！下次要小心啊，冒险者。"
    )
    return {"lines": lines, "gold_new": new_gold, "lost": lost, "extra": extra,
            "town_id": _town_id, "town_subarea": _town_sa, "stats": stat_plan,
            "revive_state": None, "rule_trigger": rule_trigger, "player": _target_player}
