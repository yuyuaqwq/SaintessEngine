# -*- coding: utf-8 -*-
"""《奥兰迪亚》玩法效果表：名词 → 引擎动词（包内单源）—— P4 进包批 2（D3）。

真源 = 游戏仓 `C:/Users/yuyu/qqbot/data/plugins/dragonfall`（只读）。本文件 = 生成物：
    PYTHONIOENCODING=utf-8 python overnight/d3_port_gameplay.py            # 生成
    PYTHONIOENCODING=utf-8 python overnight/d3_port_gameplay.py --check    # 复核（逐字节）

真源对照表
----------
| 本文件 | 真源 | 条数 | 是否全量 |
|---|---|---|---|
| `EFFECT_ACTIONS` | `game/data/battle_rules.py:468-596`（段头 :468-471 + 表体 :472-596） | 70 名词 / 82 动作条目 / 22 个动词 | 全量（真源**唯一**一份） |

⚠️ 核实结论：**计划稿的真源归属有误**。`overnight/package-final-shape.md:73` 与
`overnight/BACKLOG-工期.md:28` 写「`content/gameplay.py` ← `content_rules/gameplay.py` 158 行
（`EFFECT_ACTIONS` 名词→动词表 + 玩法规则表）」。实测：那 158 行里 `EFFECT_ACTIONS` 的**定义数 = 0**
（`grep -rn "EFFECT_ACTIONS" <游戏仓>/game/` 全仓唯一赋值处 = `game/data/battle_rules.py:472`）。
158 行文件的真实内容 = 元素常量 / 元素反应 / 叠层 / 升级结算 / 掉落名解析 —— 逐条处置见下表。

真源 158 行文件（`game/content_rules/gameplay.py`）逐条归位：**搬了什么、没搬的都写明理由**
--------------------------------------------------------------------------------------------
| 真源行 | 内容 | 处置（理由） |
|---|---|---|
| :25 `ELEMENT_OPTIONS` | 三系可切换列表 | **不搬** —— 真源 0 消费方（grep 全仓仅该文件自己）= 死数据 |
| :26 `ELEMENT_CN` | 三系中文名 | **不搬** —— 同上（0 消费方） |
| :28 `ELEMENT_MARKS` | 系 → 印记 key | **不搬** —— 包内已有单源 `content/mech/element_procs.py:35`（逐字搬自 `game/services/battle_element_procs.py:40`）。真源这一份是**游戏仓内部重复定义**（两处同值同文）；搬进来 = 在包里造一个新双源 |
| :37 `element_reaction` | 名词式元素反应判定 | **不搬** —— 真源 0 调用方（`game/services/battle_element_procs.py:9` 自述「全仓零调用方」）；包内等价实现 = `content/mech/element_procs.py:elem_reaction`（D2 批，另加 `min_layers` 门槛） |
| :51 `element_mark_apply` | 挂元素印（带上限） | **不搬** —— 真源 0 消费方（死数据） |
| :65 `mech_stack_gain` | 机制叠层（带上限） | **不搬（缺口）** —— 真源 0 消费方；且读 `MECH_CFG["mech_stack"]["max"]`，包内 `content/mech/params.py` 的 `MECH_CFG` 无该档（`mech_stack` 属「参数表建域」批） |
| :75 `check_player_level_up` | 升级结算（写 `db.event_state` / `store.inventory` / 章节礼包） | **不搬（宿主边界）** —— 写库 + 写背包 + 读 `C.exp_to_next`/`C.CHAPTER_PACK`，按三层判据属「接人性」；真源 12 处消费者全在宿主（`commands/combat.py:21`、`reward.py:165`、`store/players.py:226` …） |
| :146 `resolve_drop` | 掉落名解析（MATERIALS 优先 → ITEMS） | **不搬（宿主 + 域缺口）** —— 消费者全在宿主（`services/battle_settlement.py:229/419/476/499`、`commands/instance.py:32`）；且 `MATERIALS` 域**未进包**（`content/data/` 无 materials.json） |

逐字性 / 单源
-------------
· 表体**逐字**（真源注释、键序、缩进一字不改；本文件只在前面加了 docstring 与段头注释）。
  `--check` = 重算全文件 sha256 与盘上逐字节比较。
· **单源归位**：本文件 = 「名词 → 动词」表的**包内唯一真源**；`content/mech/params.py` 由
  「空占位 `{}`」改为 `from ..gameplay import EFFECT_ACTIONS` **再导出**（`is` 同一对象）。
  消费者 `config.load_game_rules(P)`（`content/apply.py:153`）**零改动**。
· 为什么落在**包**（而不是宿主 / 不是 params.py 里就地定义）：表是**内容**（换个游戏就得整张重写），
  引擎经 `config.get_effect_actions()` 取它 —— 判据 2「内容性」→ 包；落点沿用计划稿指定的
  `content/gameplay.py`，params.py 是**参数表载体**（`MECH_CFG`/`SKILL_FLAT`/`FORMULA_SKELETON` …），
  声明表列在它那里会让「声明表 vs 参数表」两族混居，且它已被游戏仓保真门禁登记为 BAR_* 的单源。
"""

# ============================================================
# 名词效果 → 引擎动词动作序列
# （技能数据/怪物模板里的 effect/mech 名词，经这里翻译成引擎动词）
# ============================================================
EFFECT_ACTIONS: dict = {
    # ---- 控制类（写 target.effects[tag]；V5②：mode 语义已入 EFFECT_RULES[key].consume，
    #      stun/freeze/sleep/silence 瘦身 key-only 查表——spd_down 双语义保留动作参数）----
    # mode=skip 整跳（行动级消费：轮到行动跳过+清）；mode=no_skill 禁技（技能转普攻）
    "stun":      [{"action": "apply", "key": "stun", "on": "target", "turns": 1}],
    "freeze":    [{"action": "apply", "key": "freeze", "on": "target", "turns": 1}],
    "sleep":     [{"action": "apply", "key": "sleep", "on": "target", "turns": 1}],
    "silence":   [{"action": "apply", "key": "silence", "on": "target", "turns": 2}],
    "slow":      [{"action": "apply", "key": "spd_down", "on": "target", "turns": 2, "mode": "skip"}],
    "spd_down":  [{"action": "apply", "key": "spd_down", "on": "target", "turns": 2, "mode": "skip"}],
    # ---- 属性增益（写 caster.effects[key]；数值 V5 已入 EFFECT_RULES[key].panel，
    #      动作瘦身 key-only——apply 参数缺省查表快照进条目；单源查表）----
    # 数值参考旧 battle_config.BUFF_MULT（N7.1 全新填：desc/策划案为准，旧表对照）：
    #   atk_up=×1.30 / matk_up=×1.50 / matk_up_strong=×1.80 / def_up=×1.45 /
    #   spd_up=×1.40 / crit_up=+0.20 / magic_resist=+0.15 / mon_atk_down=×0.70
    # panel 声明见上方 EFFECT_RULES（V5 静态增益入表段，数值与旧动作参数逐条核验一致）。
    "atk_up":    [{"action": "apply", "key": "atk_up"}],
    "dodge_buff":  [{"action": "apply", "key": "dodge_up"}],
    "spd_buff":    [{"action": "apply", "key": "spd_up"}],
    "crit_hit_buff": [{"action": "apply", "key": "crit_up"}],
    "cc_immune":    [{"action": "apply", "key": "cc_immune"}],   # 无面板折算（纯免疫状态）
    "purify_immune": [{"action": "apply", "key": "cc_immune"}],  # 净化免疫药（I5 映射 cc_immune）
    # 刺客影舞态（暗影步 v153：连段满 5 → 进入影舞态）——装配层动作查条件写态条目
    "shadow_dance": [{"action": "class_shadow_dance_enter"}],
    # 战士守护姿态（v153 铁誓线：受击反击 40%）——装配层动作写态 + 挂反击 trigger
    "stance_guard": [{"action": "class_stance_guard_enter"}],
    # 拳师守御姿态（v153 L992：受伤 −25%/推条 −30%）——装配层动作写态 + 挂减伤乘区
    "guard_stance": [{"action": "class_guard_stance_enter"}],
    # ---- v2026-09-11 团队/全队效果 ----
    # 面幅（遍历同侧存活）走内容侧 game/services/battle_team_procs.py；数值全部读技能数据
    # （`_do_buff` 把 info 注入 params），本表只声明「哪个名词 → 哪一族动作」。
    # 历史 bug：此前 `*_all` 一律映射到引擎 `apply`，而 `apply` 只作用于施法者自己
    # （单人时代「全队=自己」无感）→ 多人副本/PVP 下描述承诺与行为不符。已修。
    "atk_all":      [{"action": "team_apply", "key": "atk_up"}],
    "def_all":      [{"action": "team_apply", "key": "def_up"}],
    # v2026-09-11 缺口修复：`effect='def_up'`（磐石之体 lv10「防御＋45% 持续 2 刻」）此前
    #   只在 EFFECT_RULES 有面板声明、**EFFECT_ACTIONS 无映射** → resolve_actions 返回 [] →
    #   技能整条静默 no-op。补上与 def_all 同源的映射（面板数值复用 EFFECT_RULES["def_up"]）。
    "def_up":    [{"action": "apply", "key": "def_up"}],
    "matk_all":     [{"action": "team_apply", "key": "matk_up_strong"}],
    "crit_all":     [{"action": "team_apply", "key": "crit_up"}],
    "spd_all":      [{"action": "team_apply", "key": "spd_up"}],
    "atk_matk_all": [{"action": "team_apply", "key": "atk_up"},
                     {"action": "team_apply", "key": "matk_up"}],
    # 全队全属性 + 免疫控制（永恒赞歌 lv98「全队全属性 +30%、免疫控制」）
    "all_stat_cc":  [{"action": "team_apply", "key": "all_up_atk"},
                     {"action": "team_apply", "key": "all_up_def"},
                     {"action": "team_apply", "key": "all_up_matk"},
                     {"action": "team_apply", "key": "all_up_spd"},
                     {"action": "team_apply", "key": "all_up_crit"},
                     {"action": "team_cc_immune"}],
    # ---- 护盾族（盾值三形态：shield_pct / shield_per_stack+shield_res_key / shield_value）----
    "shield_all":        [{"action": "team_shield", "halve": True}],
    "shield_block":      [{"action": "self_shield", "key": "shield_self"},
                          {"action": "apply", "key": "block_up"}],
    "shield_all_reduce": [{"action": "team_shield", "halve": True},
                          {"action": "team_taken_reduce"}],
    "reduce_shield_all": [{"action": "team_taken_reduce"},
                          {"action": "team_shield", "halve": True}],
    "arcane_shield":     [{"action": "self_shield", "key": "arcane_shield"}],
    # ---- 减伤族（乘算叠加；数值读技能数据 reduce/reduce_pct）----
    "reduce_all":        [{"action": "team_taken_reduce"}],
    "dodge_reduce_all":  [{"action": "team_apply", "key": "dodge_up_big"},
                          {"action": "team_taken_reduce"}],
    # ---- 全队伤害乘区（条件读技能数据 aura_kind / aura_mark / aura_lock）----
    "arcane_matrix": [{"action": "team_dmg_aura"}],
    "hunt_team_dmg": [{"action": "team_dmg_aura"}],
    "star_lock":     [{"action": "target_lock_mark"}, {"action": "team_dmg_aura"}],
    # ---- 目标易伤（带刻数自动过期；数值读 vuln_amp）----
    "vuln":          [{"action": "timed_vuln"}],
    # ---- 潜行 + 免疫控制（影遁 lv85）----
    "stealth_cc":    [{"action": "apply", "key": "stealth", "hit": {"guaranteed_crit": True}},
                      {"action": "self_cc_immune"}],
    # ---- 脱战 + 全队闪避（烟雾弹 lv20；「脱离战斗」由命令层处理，本表只做闪避段）----
    "disengage_dodge": [{"action": "team_apply", "key": "dodge_up"}],
    # ---- 挡刀（誓约之盾 85 / 守护誓言 90）：写 guard_uid + 反伤；引擎承伤转移钩子落地 ----
    "protect":       [{"action": "team_guard"}],
    # ---- 格挡 1 次 + 反伤（铁山靠 58）----
    "block_reflect": [{"action": "block_once"}],
    # ---- 元素流转（法师，切换当前主系）----
    "element_switch": [{"action": "class_element_switch"}],
    # ---- 奥术力场（法师：护盾档落地；利刃档待交互设计）----
    "arcane_field":  [{"action": "arcane_field"}],
    # 注：`taunt`（嘲讽）**不在本表** —— 其语义（仇恨 ×N + 强制锁 N 刻）由命令层
    #   game/commands/instance_router.py 直读技能配置（hate_taunt_mult / hate_lock_turns）
    #   实现，不走 EFFECT_ACTIONS（2026-09-11 取证：此前被误列为"静默 no-op"）。
    # ---- N7.5b 药水/食物纯属性别名（items.py effect → EFFECT_RULES panel；special:* 类 N8 事件）----
    "buff_atk":    [{"action": "apply", "key": "atk_up"}],
    "buff_atk_big":[{"action": "apply", "key": "atk_up_big"}],
    "buff_atk_small":[{"action": "apply", "key": "atk_up_small"}],
    "buff_atk_food":[{"action": "apply", "key": "food_atk_up"}],
    "buff_def":    [{"action": "apply", "key": "def_up"}],
    "buff_def_food":[{"action": "apply", "key": "food_def_up"}],
    "buff_spd":    [{"action": "apply", "key": "spd_up"}],
    "buff_spd_small":[{"action": "apply", "key": "spd_up_small"}],
    "buff_spd_food":[{"action": "apply", "key": "food_spd_up"}],
    "buff_crit":   [{"action": "apply", "key": "crit_up"}],
    "buff_crit_small":[{"action": "apply", "key": "crit_up_small"}],
    "buff_crit_big":[{"action": "apply", "key": "crit_up_big"}],
    "buff_crit_food":[{"action": "apply", "key": "food_crit_up"}],
    "buff_matk":   [{"action": "apply", "key": "matk_up_pot"}],
    "buff_matk_strong":[{"action": "apply", "key": "matk_up_strong"}],
    "buff_matk_food":[{"action": "apply", "key": "food_matk_up"}],
    "food_spd_up_small":[{"action": "apply", "key": "food_spd_up_small"}],
    # ---- 一次性出手消费（hit 子键：出手增伤 / 必暴；效果参数可被调用方 effect_data 覆盖）----
    "next_atk_up":   [{"action": "apply", "key": "next_atk_up",   "hit": {"dmg_mult": 1.50}}],
    "buff_phys_next":[{"action": "apply", "key": "buff_phys_next","hit": {"dmg_mult": 1.40}}],
    "stealth":       [{"action": "apply", "key": "stealth",       "hit": {"guaranteed_crit": True}}],
    # ---- N7.5a 战斗核心：治疗/叠层置值/打断（怪 heal_self/heal_pct、on_interrupt 族）----
    # vulnerable 易伤：完整语义（写 target 承伤乘区 + 持续刻）属 N8 事件总线接入，
    # 不在词表假映射——landing 已支持 _dmg_taken_mult 字段（上层直写即生效）
    "heal_self":   [{"action": "heal", "on": "caster"}],
    "heal_pct":    [{"action": "heal", "on": "caster"}],
    "regen":       [{"action": "heal", "on": "caster"}],     # 持续回复族（regen 单发）
    "stacks_set":  [{"action": "apply", "op": "set", "on": "target"}],
    "interrupt":   [{"action": "interrupt"}],
    # ---- 减伤（value 型 buff：mech_val 折算百分比 45→0.45）----
    "reduce":    [{"action": "apply", "key": "reduce", "pct_from_mech_val": True}],
    # ---- 护盾 ----
    "shield_self": [{"action": "shield", "halve": False}],
    "shield":      [{"action": "shield", "halve": True}],
    # ---- 净化 ----
    "cleanse":     [{"action": "cleanse"}],
    "cleanse_all": [{"action": "cleanse_all"}],
}
