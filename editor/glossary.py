# -*- coding: utf-8 -*-
"""字段词典（编辑器用）—— 字段的中文翻译、**注脚**（语义/消费者/坑）与 **wiki 直链**。

为什么需要
----------
schema 是给机器看的：`{"type": "string"}` 说得出类型，说不出「这个字段谁读、写了会不会
静默不生效」。编辑器用本词典把任意一个字段渲染成：

    cap  · 叠层上限            ⓘ 引擎消费（effects._cap_of）· 缺声明 = 999999 不设限   📖

三条硬规矩（本文件的所有内容都按它们写）
-----------------------------------------
1. **不发明事实**：`note` 只写能从以下来源核实的语义 —— 同仓 schema 的 description、
   `docs/engine-wiki/` 的对应页、或引擎源码读点。
2. **wiki 链接必须可解析**：`ref` 的 `find` 词必须**真实出现在**该页正文里；
   `tests/test_editor_glossary.py` 逐条断言（找不到 → 门禁红）。
3. **不装懂**：wiki 没记载、也没核实的键，注脚直说「未核实」，不编一个像是真的语义。

对外接口
--------
    lookup(dom, path) -> dict | None     # 单字段（依次回退：dom 精确 → dom 叶名 → 通用叶名）
    all_entries() -> dict                # 给 /api/glossary
    friendly(dom, errors) -> list        # schema 报错 → 中文可读（带字段中文名）
    ref_url(entry) -> str | None         # 词典条目 → 编辑器内 wiki 深链
"""
from __future__ import annotations

import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(HERE)
WIKI_DIR = os.path.join(FW_ROOT, "docs", "engine-wiki")

# ─────────────────────────────────────────────────────────────── 通用（跨域叶名共用）
_COMMON = {
    "name": {"zh": "名称", "note": "显示名。多数表里它也是引擎日志/索引用的标识（技能冷却表即以显示名为 key，改名等于放弃旧冷却条目）。",
             "ref": ("reference/skill-availability.md", "cd")},
    "desc": {"zh": "描述", "note": "展示文案。**必填且不能为空串**（schema minLength=1）—— 新建条目被拦，最常见就是这里。",
             "ref": None},
    "kind": {"zh": "类型 / 门类", "note": "分派用的类型。技能侧它决定走哪条执行链（伤害 / 治疗 / 增益）。",
             "ref": ("concepts/actor-model.md", "kind")},
    "effect": {"zh": "效果名词", "note": "内容侧名词，经 EFFECT_ACTIONS 翻译成**动词**，再由注册的动词执行器落地。",
               "ref": ("concepts/declaration-tables.md", "effect")},
    "mech": {"zh": "机制名词", "note": "内容侧名词，经 MECH_CASH 声明装配成触发器（triggers），引擎 fire() 时执行。",
             "ref": ("concepts/declaration-tables.md", "MECH_CASH")},
    "mech_val": {"zh": "机制数值", "note": "配合 mech 的数值参数；缺省由声明的默认值决定（零默认值铁律：没声明 = 不生效）。",
                 "ref": ("reference/mech-cash.md", "mech_val")},
    "cond": {"zh": "条件块", "note": "条件型释放的判据块（满足才生效）。",
             "ref": ("architecture/boundaries.md", "cond")},
    "element": {"zh": "元素", "note": "伤害元素标记（框架不预设取值）。",
                "ref": ("reference/judges.md", "element")},
    "aoe": {"zh": "群体范围", "note": "群体技的目标范围。",
            "ref": None},
    "formula": {"zh": "结构化公式", "note": "结构化伤害公式（数组）。与 exprs 二选一，内容侧解释。",
                "ref": None},
    "tag": {"zh": "标记", "note": "内容侧标记串。⚠ EFFECT_RULES 层的 `tag` 引擎不读（act_apply 读的是动作 params 的 tag）；技能/怪物侧的 tag 由内容侧使用。",
            "ref": ("reference/effect-rules.md", "tag")},
}

# ───────────────────────────────────────────────────────────────────────── 技能
_SKILLS = {
    "lv": {"zh": "技能等级", "note": "该条技能声明的等级（≥1）。成长曲线按等级算。", "ref": None},
    "mp": {"zh": "魔力消耗", "note": "施放判据之一：折算后的消耗与 mp / 核心资源比对，不足则拦下（不扣费、不写冷却）。",
           "ref": ("reference/skill-availability.md", "mp")},
    "cd": {"zh": "冷却", "note": "单位**刻**（CTB 刻度），存的是**绝对时刻**（写入时 = 当前时刻 + cd），不是「还剩几回合」。0 / 缺省 = 无冷却。",
           "ref": ("reference/skill-availability.md", "cd")},
    "power": {"zh": "威力倍率", "note": "数值倍率基座（实际伤害看 exprs / formula）。", "ref": None},
    "cast": {"zh": "施法时刻", "note": "数值 = 施法耗时（刻）；字符串 \"None\" 是历史哨兵，表示瞬发/被动（51 条沿用）。",
             "ref": ("reference/skill-availability.md", "cast")},
    "exprs": {"zh": "伤害表达式", "note": "表达式串列表（如 matk*1.8 + player_lv*4），由内容侧求值。", "ref": None},
    "heal_formula": {"zh": "治疗公式", "note": "治疗量公式（字符串）。", "ref": None},
    "mech_chance": {"zh": "机制触发概率", "note": "0~1。零默认值铁律：0 = 永不触发（可用来关掉一条机制做对照）。",
                    "ref": ("guides/add-a-passive.md", "chance")},
    "mech2": {"zh": "第二机制名词", "note": "第二条机制的 MECH_CASH 名词。", "ref": ("reference/api.md", "mech2")},
    "mech2_val": {"zh": "第二机制数值", "note": "配合 mech2 的数值参数。", "ref": None},
    "buff_turns": {"zh": "状态持续回合", "note": "状态/增益持续的回合数（内容侧写入效果条目；框架不预设）。",
                   "ref": None},
    "hits": {"zh": "命中次数", "note": "多段攻击段数（≥1）。", "ref": None},
    "target": {"zh": "目标方向", "note": "目标选择方向（back = 后排）。", "ref": None},
    "summon": {"zh": "召唤物", "note": "召唤出的 actor 标识（内容侧语义）。宠物/召唤物在参考实现里一律走 companions actor 字段，引擎无专用路径。",
               "ref": None},
    "team": {"zh": "阵营", "note": "召唤/生成的阵营（框架不预设取值）。", "ref": None},
    "pierce": {"zh": "穿透", "note": "穿透标记（无视部分防御/减伤，由内容侧解释）。", "ref": None},
    "no_mp": {"zh": "不耗魔力", "note": "声明该技能不做魔力判据。", "ref": None},
    "sleep": {"zh": "睡眠", "note": "施加 sleep 效果。⚠「受击打醒」是引擎里对 **key=sleep** 的硬编码判断，与 EFFECT_RULES 的 wake_on_hit 字段无关。",
              "ref": ("reference/effect-rules.md", "wake_on_hit")},
    "accuracy": {"zh": "必中", "note": "命中判定标记。", "ref": ("README.md", "accuracy")},
    "crit": {"zh": "暴击", "note": "暴击结算参与标记（详情见事件总线里的乘区事件）。",
             "ref": ("reference/events.md", "crit")},
    "stance": {"zh": "姿态", "note": "姿态标记（内容侧语义）。", "ref": None},
    "auto": {"zh": "自动行为", "note": "自动出手标记（内容侧语义）。", "ref": None},
    "kind_override": {"zh": "覆盖类型", "note": "覆盖 kind 的分派结果（用于同一技能走另一条链）。", "ref": None},
    "hate_mult": {"zh": "仇恨倍率", "note": "仇恨（威胁）乘区：本次伤害转仇恨的倍率（内容侧实现；参考实现用 4 表示全层仇恨技）。",
                  "ref": None},
    "hate_taunt_mult": {"zh": "嘲讽仇恨倍率", "note": "命中被嘲讽目标时的额外仇恨倍率。", "ref": None},
    "hate_lock_turns": {"zh": "仇恨锁定回合", "note": "强制目标锁定该施法者的回合数。", "ref": None},
    "lifesteal": {"zh": "吸血比例", "note": "0~1，伤害转治疗的占比。", "ref": None},
    "hp_pct": {"zh": "生命比例", "note": "按最大生命取比例的系数。", "ref": None},
    "reduce_all": {"zh": "固定减伤", "note": "固定值减伤（非比例）。", "ref": ("reference/effect-actions.md", "reduce_all")},
    "reduce_pct": {"zh": "减伤比例", "note": "百分比减伤。", "ref": None},
    "charge": {"zh": "蓄力", "note": "蓄力标记（内容侧语义）。", "ref": None},
    "res_cost": {"zh": "核心资源消耗", "note": "{资源 key: 数量}。资源上限走 actor.bonus.cap，消耗折扣走 PASSIVE_PROC 的 domain=cost。",
                 "ref": ("reference/mech-cash.md", "res_cost")},
    "kill": {"zh": "击杀结算", "note": "击杀时的额外结算块（内容侧解释）。", "ref": None},
    "cond.type": {"zh": "条件类型", "note": "条件判据的类型名。", "ref": ("guides/add-a-passive.md", "type")},
    "cond.mult": {"zh": "条件倍率", "note": "条件满足时的倍率乘区。", "ref": ("reference/judges.md", "mult")},
    "cond.stacks": {"zh": "条件层数", "note": "条件要求/消耗的层数。", "ref": ("concepts/effects.md", "stacks")},
    "cond.mech": {"zh": "条件机制名词", "note": "条件里引用的机制名词。", "ref": ("concepts/declaration-tables.md", "mech")},
    "cond.label": {"zh": "条件标签", "note": "条件块的展示标签。", "ref": ("guides/add-a-passive.md", "label")},
    "passive": {"zh": "被动块", "note": "被动数值参数块：**除 proc 外全部并入**装配出的触发器条目（技能数据覆盖声明表）。",
                "ref": ("reference/passive-proc.md", "passive")},
    "passive.proc": {"zh": "被动声明 key", "note": "指向 PASSIVE_PROC 里的一个声明；装配器据此把事件钩子挂进 triggers。",
                     "ref": ("reference/passive-proc.md", "proc")},
    "passive.add": {"zh": "被动增量", "note": "数值增量（domain=cap 时是上限增量，只累加正数）。",
                    "ref": ("reference/passive-proc.md", "add")},
    "passive.mult": {"zh": "被动倍率", "note": "乘区倍率。", "ref": ("reference/judges.md", "mult")},
    "passive.stacks": {"zh": "被动层数", "note": "初始/上限层数。", "ref": ("concepts/effects.md", "stacks")},
    "passive.per_layer": {"zh": "每层系数", "note": "按层缩放系数。", "ref": ("reference/effect-rules.md", "per_layer")},
    "passive.hp_pct": {"zh": "生命比例", "note": "被动里按最大生命取的比例。", "ref": None},
    "passive.reduce": {"zh": "被动减伤", "note": "被动减伤数值。", "ref": ("reference/effect-rules.md", "reduce")},
}

# ───────────────────────────────────────────────────────────────────────── 怪物
_MONSTERS = {
    "power": {"zh": "威力倍率", "note": "怪物招式的数值倍率。", "ref": None},
    "formula.stat": {"zh": "公式取用属性", "note": "atk（物攻）/ matk（魔攻）。", "ref": None},
    "formula.mult": {"zh": "公式倍率", "note": "该段公式的倍率。", "ref": None},
    "formula.type": {"zh": "公式伤害类型", "note": "phys（物理）/ magi（魔法）。", "ref": None},
    "mech_val": {"zh": "机制数值", "note": "配合 mech 的数值参数。", "ref": ("reference/mech-cash.md", "mech_val")},
    "aoe": {"zh": "群体范围", "note": "all = 全体。", "ref": None},
    "summon": {"zh": "召唤数量", "note": "召唤的个体数。", "ref": None},
    "charge": {"zh": "蓄力回合", "note": "蓄力所需回合数。", "ref": None},
    "hits": {"zh": "命中次数", "note": "多段次数。", "ref": None},
    "multi": {"zh": "多段次数", "note": "连击段数（与 hits 的区别以内容侧实现为准）。", "ref": None},
    "hp_pct": {"zh": "生命比例", "note": "按最大生命取比例的系数。", "ref": None},
    "defend_reduce": {"zh": "防御减伤", "note": "防御姿态下的减伤值。", "ref": None},
    "reach": {"zh": "攻击距离", "note": "可打击的行/距离（阵型相关）。", "ref": ("concepts/actor-model.md", "reach")},
    "basic": {"zh": "普攻招式", "note": "标记该条为普攻（AI 回落用）。", "ref": None},
    "cast": {"zh": "施法耗时", "note": "施法/动作耗时（刻）。", "ref": ("reference/channels.md", "cast")},
    "recovery": {"zh": "恢复", "note": "动作后摇/恢复（内容侧语义）。", "ref": None},
    "pdot": {"zh": "周期伤害块", "note": "周期伤害声明块（⚠ 引擎侧 DOT 统一走 EFFECT_RULES.period，这个键由内容侧解释）。",
             "ref": ("reference/effect-rules.md", "period")},
    "id": {"zh": "怪物标识", "note": "怪物 id（AI 权重 / 连招链按它索引）。", "ref": None},
    "role": {"zh": "定位", "note": "elite = 精英（Boss 档另有 is_boss 判定）。", "ref": ("concepts/actor-model.md", "role")},
    "lv_off": {"zh": "等级偏移", "note": "相对基准怪的等级偏移。", "ref": None},
    "skills": {"zh": "技能池", "note": "该怪可用的技能名数组。⚠ Boss 的**身份技 / 常态循环技必须写进 spawn 元组的技能数组**——只放 phases.add_skills 的话，跨阈值前解析不到 = 静默空放。",
               "ref": ("reference/skill-availability.md", "add_skills")},
    "drops": {"zh": "掉落", "note": "掉落表引用。", "ref": ("concepts/actor-model.md", "drops")},
    "gold_mult": {"zh": "金币倍率", "note": "金币掉落倍率。", "ref": None},
    "chance": {"zh": "触发概率", "note": "0~1。零默认值铁律：没写 = 不触发。", "ref": ("guides/add-a-passive.md", "chance")},
    "flavor": {"zh": "风味文案", "note": "展示用的风味描述。", "ref": None},
    "maps": {"zh": "所属地图", "note": "出现的地图/区域 id。", "ref": None},
}

# ───────────────────────────────────────────────────────────────────────── 词条
_AFFIXES = {
    "kind": {"zh": "词条类别", "note": "attack（攻击向）/ defense（防御向）。", "ref": None},
    "trigger": {"zh": "触发时机", "note": "battle_start（开局）/ on_hit（命中）/ on_taken（受击）/ passive（常驻）/ stat（面板）/ turn_start（回合开始）。",
                "ref": ("guides/add-an-affix.md", "trigger")},
    "chance": {"zh": "触发概率", "note": "0~1。零默认值铁律：不写 = 不触发。", "ref": ("guides/add-a-passive.md", "chance")},
    "qualities": {"zh": "可出品质", "note": "允许出现的品质集合（blue/purple/orange）。", "ref": None},
    "unique": {"zh": "唯一", "note": "是否唯一词条（同件装备不重复）。", "ref": None},
    "line": {"zh": "归属线", "note": "词条所属分组/线（内容侧语义）。", "ref": None},
    "effect": {"zh": "效果块", "note": "词条生效的效果声明（结构由内容侧定义）。", "ref": ("concepts/declaration-tables.md", "effect")},
}

# ───────────────────────────────────────────────────────────────────────── 物品
_ITEMS = {
    "price": {"zh": "价格", "note": "基础售价。", "ref": None},
    "type": {"zh": "物品类型", "note": "类别串（框架不预设取值）。", "ref": None},
    "quality": {"zh": "品质", "note": "white/green/blue/purple/orange。", "ref": None},
    "effect": {"zh": "效果名词", "note": "使用时的效果名词（经 EFFECT_ACTIONS 翻译成动词）。", "ref": ("guides/add-a-passive.md", "effect")},
    "effect_data": {"zh": "效果数据", "note": "配合 effect 的参数字典。", "ref": None},
    "food_effect": {"zh": "食物效果", "note": "食物类道具的效果名词。", "ref": None},
    "heal": {"zh": "回血", "note": "回复生命值。", "ref": ("reference/effect-actions.md", "heal")},
    "mana": {"zh": "回魔", "note": "回复魔力值。", "ref": ("concepts/effects.md", "mana")},
    "hot": {"zh": "持续回血", "note": "HoT：每回合回复的生命（配合 hot_turns）。", "ref": ("concepts/effects.md", "hot")},
    "hot_turns": {"zh": "持续回合", "note": "HoT / 增益持续的回合数。", "ref": None},
    "hot_mana": {"zh": "持续回魔", "note": "每回合回复的魔力。", "ref": None},
    "stamina": {"zh": "体力", "note": "回复的行动体力。", "ref": None},
    "cast": {"zh": "使用耗时", "note": "使用该道具的耗时（刻）。", "ref": ("reference/channels.md", "cast")},
    "food": {"zh": "食物", "note": "标记为食物（进食交互用）。", "ref": None},
    "battle_ok": {"zh": "可战中使用", "note": "是否允许在战斗内使用。", "ref": None},
    "key_item": {"zh": "关键道具", "note": "剧情关键道具（不可丢弃/出售）。", "ref": None},
    "blueprint_for": {"zh": "图纸产出", "note": "该图纸能制造的目标 id。", "ref": None},
    "roster_id": {"zh": "图鉴 id", "note": "对应的图鉴条目 id。", "ref": None},
    "learn_skill": {"zh": "学习技能", "note": "使用后学会的技能名。", "ref": None},
    "require_class": {"zh": "限定职业", "note": "只有该职业可用。", "ref": None},
    "rune_pool": {"zh": "符文池", "note": "抽符文用的池 id。", "ref": None},
    "weapon_pick": {"zh": "武器自选", "note": "开启武器自选（配合 pick_options）。", "ref": None},
    "pick_options": {"zh": "自选选项", "note": "自选清单（name/rid/desc 三项一条）。", "ref": None},
    "pick_options.name": {"zh": "选项名", "note": "自选项显示名。", "ref": None},
    "pick_options.rid": {"zh": "选项产出 id", "note": "选中后产出的物品/符文 id。", "ref": None},
    "pick_options.desc": {"zh": "选项说明", "note": "自选项的说明文案。", "ref": None},
}

# ───────────────────────────────────────────────────────────────────── 声明表（EFFECT_RULES）
_EFFECT_RULES = {
    "cap": {"zh": "叠层上限", "note": "✅ 引擎消费（effects._cap_of）。**上限的唯一收敛点**（apply / period gain / 渠道攒取都走它）。**缺声明 = 999999（不设限）**，不是 0。",
            "ref": ("reference/effect-rules.md", "cap")},
    "stat_scale": {"zh": "每层面板修正", "note": "✅ 引擎消费（stats._apply_effects）：st[stat] *= (1 + 层数×系数)。特殊 stat：dmg_mult（伤害乘区）、reduce。",
                   "ref": ("reference/effect-rules.md", "stat_scale")},
    "debuff_scale": {"zh": "每层受击增伤", "note": "✅ 引擎消费（`landing.deal_damage`，2026-09-11 接线）：遍历持有者状态，Σ(每层系数 × stacks) → 伤害 ×(1+Σ)。与 `stat_scale` 对称（一个改面板、一个改承伤）；层数上限由数据侧 `cap` 决定，引擎不另设帽。",
                     "ref": ("reference/effect-rules.md", "debuff_scale")},
    "panel": {"zh": "静态面板增益", "note": "✅ 引擎消费：动作参数缺省时查这张表（op=mul 乘 / add 加）。",
              "ref": ("reference/effect-rules.md", "panel")},
    "panel.stat": {"zh": "面板属性", "note": "被修正的面板键（atk / def / spd …）。", "ref": ("reference/effect-rules.md", "panel")},
    "panel.op": {"zh": "运算方式", "note": "mul（乘算）/ add（加算）。", "ref": ("reference/effect-rules.md", "panel")},
    "panel.mult": {"zh": "修正值", "note": "op 对应的数值。", "ref": ("concepts/effects.md", "mult")},
    "period": {"zh": "周期结算", "note": "✅ 引擎消费（schedule._settle_time_effects）：每 interval 刻结算一次。首次只登记、不立即跳。",
               "ref": ("reference/effect-rules.md", "period")},
    "period.dir": {"zh": "周期方向", "note": "✅ damage（掉血）/ heal（回血）/ mana（回魔）/ gain（加层或减层，负值走衰减）。",
                   "ref": ("reference/effect-rules.md", "dir")},
    "period.interval": {"zh": "周期间隔", "note": "✅ 单位刻（绝对时刻，不是「每 tick」）。", "ref": ("reference/effect-rules.md", "interval")},
    "period.pct_max_hp": {"zh": "每跳最大生命比例", "note": "✅ damage 向：每层每跳按最大生命掉血。", "ref": ("reference/effect-rules.md", "pct_max_hp")},
    "period.pct_cur_hp": {"zh": "每跳当前生命比例", "note": "✅ damage 向：按**当前**生命掉血。", "ref": ("reference/effect-rules.md", "pct_cur_hp")},
    "period.pct_boss": {"zh": "Boss 档比例", "note": "✅ Boss（is_boss / role==\"boss\"）覆盖 pct_max_hp。", "ref": ("reference/effect-rules.md", "pct_boss")},
    "period.pct_cur_boss": {"zh": "Boss 档当前生命比例", "note": "✅ Boss 覆盖 pct_cur_hp。", "ref": ("reference/effect-rules.md", "pct_cur_boss")},
    "period.amount": {"zh": "每跳增减量", "note": "✅ 仅 gain 向：每刻加/减层，负值也走（衰减），下限 clamp 0。", "ref": ("reference/effect-rules.md", "amount")},
    "period.type": {"zh": "周期类型", "note": "⚠ **当前无消费者**（参考实现里 bleed 写了 \"flat\"）。", "ref": ("reference/effect-rules.md", "period.type")},
    "period.atk": {"zh": "周期攻击系数", "note": "✅ 引擎消费（DOT 混合公式，2026-09-11）：乘**施法者强度快照** atk 的系数（快照 = 挂 DOT 那一刻的施法者面板）。", "ref": ("reference/effect-rules.md", "atk")},
    "period.matk": {"zh": "周期魔攻系数", "note": "✅ 引擎消费（同上）：乘施法者快照 matk 的系数。", "ref": ("reference/effect-rules.md", "matk")},
    "period.pct_cap": {"zh": "周期单层上限", "note": "✅ 引擎消费：每层每刻百分比 ≤ 该值（防极端叠层爆炸）。", "ref": ("reference/effect-rules.md", "pct_cap")},
    "period.boss_pct_mult": {"zh": "周期 boss 折扣", "note": "✅ 引擎消费：Boss/精英的百分比段折扣系数（条目级 `pct_boss` 未声明时才用，二者不叠乘）。", "ref": ("reference/effect-rules.md", "boss_pct_mult")},
    "period.double_low_hp_pct": {"zh": "周期低血翻倍", "note": "✅ 引擎消费：目标当前生命 < max_hp×该值 → 本刻伤害 ×2（流血处决线）。", "ref": ("reference/effect-rules.md", "double_low_hp_pct")},
    "period.resist_cap": {"zh": "周期总抗上限", "note": "✅ 引擎消费：声明即启用总抗段，总抗 = min(该值, actor.dot_res + adapt) → 伤害 ×(1−总抗)。", "ref": ("reference/effect-rules.md", "resist_cap")},
    "period.dmg_type": {"zh": "周期伤害类型", "note": "✅ 引擎消费（`schedule` DOT 结算，2026-09-11 接线）：透传为落地 `dmg_kind`。`true` = 真伤（物免/魔免/格挡全跳过）；空值 = 不减免（DOT 旧行为不变）。",
                        "ref": ("reference/effect-rules.md", "dmg_type")},
    "period.per_layer": {"zh": "每层结算", "note": "⚠ **当前无消费者**（参考实现里 bleed 写了 0）。", "ref": ("reference/effect-rules.md", "per_layer")},
    "period.turns": {"zh": "限跳次数", "note": "✅ 跳到次数就清层；0 = 无限。计数器 actor[\"dot_jumps\"]。", "ref": ("reference/effect-rules.md", "turns")},
    "consume": {"zh": "消费模式", "note": "✅ 引擎消费：控制型条目对行动的影响。", "ref": ("reference/effect-rules.md", "consume")},
    "consume.mode": {"zh": "消费方式", "note": "✅ skip（整跳行动，如眩晕）/ no_skill（技能转普攻）。写进表后技能 mech 不必再带 mode 参数。",
                     "ref": ("concepts/effects.md", "skip")},
    "on": {"zh": "默认作用对象", "note": "✅ target = 对敌标记类（净化时按它判方向）。", "ref": ("reference/effect-rules.md", "on")},
    "negative": {"zh": "负面标记", "note": "⚠ 引擎不读；内容侧用它数「负面种数」（target_debuff_kinds 判据）。", "ref": ("reference/effect-rules.md", "negative")},
    "cleanse": {"zh": "可被净化", "note": "✅ 引擎消费（act_cleanse）：True = 可被净化。", "ref": ("reference/effect-rules.md", "cleanse")},
    "tag": {"zh": "标记", "note": "⚠ 引擎不读这张表的 tag（act_apply 读的是动作 params 的 tag，作 key 的兜底）。",
            "ref": ("reference/effect-rules.md", "tag")},
    "cd_mult": {"zh": "冷却倍率", "note": "✅ 引擎消费（actions.do_skill）：0.8 = 冷却 −20%。多态并存**取最小**（最速）。",
                "ref": ("reference/effect-rules.md", "cd_mult")},
    "start_full": {"zh": "开局满额", "note": "⚠ 引擎不读，内容侧装配器读（开局按上限拉满）。", "ref": ("reference/effect-rules.md", "start_full")},
    "start_classes": {"zh": "归属职业", "note": "⚠ 引擎不读，内容侧读。**空列表 = 不设限 = 谁都能装**；通用效果键（shield / melody_def）**不要**写它，否则会被内容侧的乘区装配跳过。",
                      "ref": ("reference/effect-rules.md", "start_classes")},
    "load_tiers": {"zh": "负载档位", "note": "⚠ 引擎不读，内容侧读：[{max, heal_mult, label, overload}]。", "ref": ("reference/effect-rules.md", "load_tiers")},
    "on_threshold": {"zh": "满层触发", "note": "⚠ **当前无消费者**：这张映射表没被读。要满层触发请监听 `threshold` 事件自己实现。",
                     "ref": ("reference/effect-rules.md", "on_threshold")},
    "channels": {"zh": "攒取渠道", "note": "⚠ 引擎不读，内容侧装配器读：{时机: 值}，把事件换成资源层数。",
                 "ref": ("reference/channels.md", "channels")},
    "guard_hp_pct": {"zh": "濒死保底比例", "note": "✅ 引擎消费（landing._apply_death_guard）：触发濒死保护后保底到的最大生命比例，缺省 0.10。",
                     "ref": ("reference/effect-rules.md", "guard_hp_pct")},
    "heal_pct": {"zh": "濒死回复比例", "note": "✅ 同上：触发时额外回复的最大生命比例。", "ref": ("reference/effect-rules.md", "heal_pct")},
    "overload_heal_pct": {"zh": "过载回复比例", "note": "⚠ 引擎不读，内容侧读：过载触发的全队回复比例。", "ref": ("reference/effect-rules.md", "overload_heal_pct")},
    "wake_on_hit": {"zh": "受击打醒", "note": "✅ 引擎消费（`landing.deal_damage`，2026-09-11 接线）：承伤时遍历持有者状态，带该字段的态即被移除。接线前是 landing 内**硬编码 `sleep`**（游戏名词进引擎）——本字段生效后引擎零内容知识。",
                    "ref": ("reference/effect-rules.md", "wake_on_hit")},
}

# ─────────────────────────────────────────────── 被动声明（PASSIVE_PROC，内容侧装配器读）
_PASSIVE_PROC = {
    "domain": {"zh": "静态域", "note": "两种静态域：cap（改资源上限，写 bonus.cap[cap_key]）/ cost（消耗折扣，只读被动块的 mp_mult）。⚠ 声明 domain=cap 时**不 continue** —— 同时写了 event 会继续走事件装配（双通道）。",
               "ref": ("reference/passive-proc.md", "domain")},
    "event": {"zh": "事件时机", "note": "逐字作为 triggers 的键（引擎 fire 的时机名）。空 = 跳过该条。值必须是引擎事件全集里的名字。",
              "ref": ("reference/events.md", "EVENTS")},
    "action": {"zh": "机制动作", "note": "作为触发器条目的 type，**不经名词翻译** —— 必须是代码里 @register_action 注册过的动作（编辑器给联想）。",
               "ref": ("reference/effect-actions.md", "register_action")},
    "judge": {"zh": "判据谓词", "note": "谓词名 → 参数（映射形式），动作里读 params[\"judge\"]。全部谓词见 judges 页。",
              "ref": ("reference/judges.md", "判据")},
    "also": {"zh": "第二事件钩子", "note": "同一动作再挂一个事件。⚠ 可覆盖的键是**硬编码白名单**（ctrl / ctrl_any / res / left_key / left_init / cost_field / buff_key），写别的键不报错也不生效。",
             "ref": ("reference/passive-proc.md", "also")},
    "when": {"zh": "条件门", "note": "条件域用：满足条件时才生效（写进 bonus.cost[\"when\"]）。",
             "ref": ("reference/passive-proc.md", "when")},
    "buff_key": {"zh": "增益 key", "note": "指向的效果 key（装配出的条目按它读写 effects）。", "ref": ("reference/passive-proc.md", "buff_key")},
    "cap_key": {"zh": "上限 key", "note": "domain=cap 时写入 bonus.cap[cap_key]。**缺省 = proc 名本身** —— proc 名 ≠ 资源 key 时必须显式写。",
                "ref": ("reference/passive-proc.md", "cap_key")},
    "used_key": {"zh": "已用计数 key", "note": "⚠ 本仓 wiki 未记载该键语义（装配器是否读取**未核实**）—— 用前先看你的装配器实现。",
                 "ref": None},
    "left_key": {"zh": "剩余计数 key", "note": "计数器初始化：effects[left_key] = {stacks: left_init, expire: None}。",
                 "ref": ("reference/passive-proc.md", "left_key")},
    "cost_field": {"zh": "消耗字段", "note": "从技能字段取消耗数值的字段名（also 白名单里的键之一）。", "ref": ("reference/passive-proc.md", "cost_field")},
    "gain_field": {"zh": "产出字段", "note": "⚠ 本仓 wiki 未记载该键语义（**未核实**）—— 用前先看装配器实现。", "ref": None},
    "bar_field": {"zh": "推条字段", "note": "从技能字段取推条量：经 BAR_INJECT_FIELDS 解析成 {key, gain}，**数值单源 = 技能数据字段**。",
                  "ref": ("reference/passive-proc.md", "bar_field")},
    "mech_prefix": {"zh": "机制前缀", "note": "judge 谓词之一（按机制名前缀匹配）。", "ref": ("reference/judges.md", "mech_prefix")},
    "res": {"zh": "资源 key", "note": "该动作作用的职业资源 key（上限走 cap，消耗走 cost）。",
            "ref": ("reference/passive-proc.md", "res")},
    "agg": {"zh": "聚合族", "note": "同 (event, agg) 的多条归并成一条。⚠ 只有 `counter` 已实现，**其他族会被整族丢弃**。",
            "ref": ("reference/passive-proc.md", "agg")},
    "mode": {"zh": "模式", "note": "动作/声明的模式参数（取值由声明的动作决定）。", "ref": ("reference/mech-cash.md", "mode")},
    "form": {"zh": "形态", "note": "⚠ 本仓 wiki 未记载该键语义（**未核实**）—— 用前先看装配器/动作实现。", "ref": None},
    "left_init": {"zh": "计数初值", "note": "计数器 key 的初始层数。", "ref": ("reference/passive-proc.md", "left_init")},
    "spd_pct": {"zh": "速度百分比", "note": "速度类动作的百分比参数。", "ref": ("reference/passive-proc.md", "spd_pct")},
    "def_pct": {"zh": "防御百分比", "note": "⚠ 本仓 wiki 未记载该键语义（**未核实**）—— 用前先看动作实现。", "ref": None},
    "hold": {"zh": "保持", "note": "⚠ 本仓 wiki 未记载该键语义（**未核实**）—— 用前先看动作实现。", "ref": None},
    "gap": {"zh": "间隔", "note": "间隔参数（judges 页有出现）。", "ref": ("reference/judges.md", "gap")},
    "ctrl_any": {"zh": "任意控制", "note": "判据/参数：任意控制类是否生效（also 白名单里的键之一）。",
                 "ref": ("reference/passive-proc.md", "ctrl_any")},
}

# ───────────────────────────────────────────────────────────────────── 声明驱动：指令 / 文案
_COMMANDS = {
    "key": {"zh": "指令标识", "note": "通常等于宿主 handler 名——漂移自检（CommandRegistry.audit_handlers）按它对齐声明与实际注册。"},
    "patterns": {"zh": "命中正则", "note": "首条为主、其余为别名；行首锚定由内容侧负责。多条时宿主 filter 收合并串 `(?:a)|(?:b)`。"},
    "desc": {"zh": "说明", "note": "帮助/编辑器用；不填则帮助里没有这条。"},
    "category": {"zh": "分类", "note": "帮助分组用；取值由内容侧定义（框架不设枚举）。"},
    "usage": {"zh": "用法", "note": "帮助里展示的用法示例文本。"},
    "guards": {"zh": "守卫", "note": "守卫**名字**列表（如 player/battle）；语义由内容侧实现——框架只记名字，不认「角色」这类概念。"},
    "page_size": {"zh": "每页条数", "note": "该指令列表输出的每页条数；0 = 不适用。"},
    "visible": {"zh": "可见", "note": "是否出现在帮助/目录（默认 true）。"},
    "order": {"zh": "排序", "note": "帮助排序，小在前；同值按注册序。"},
    "extra": {"zh": "附加数据", "note": "内容侧自定义字段（如权限、限流、冷却）；框架不解释、原样带回。"},
}

_TEXTS = {
    "key": {"zh": "文案标识", "note": "支持点分命名（如 battle.hit）；渲染时按它取模板，未定义会计入 missing 自检。"},
    "category": {"zh": "分类", "note": "编辑器分组用；取值由内容侧定义（框架不设枚举）。"},
    "value": {"zh": "模板串", "note": "用 {slot} 占位。未知槽渲染时**原样保留**（不抛），便于发现问题。"},
    "params": {"zh": "占位符声明", "note": "声明的占位符名；缺省由模板自动抽取。声明后会与模板比对（多/少都报）。"},
}

_TLOGS = {
    "kind": {"zh": "流水标识", "note": "点分命名（如 battle.hit）；**表形态里以对象 key 为准**。读的人按它筛（`Reader.iter_records(kind=…)`，`battle.` 这种点结尾写法匹配整族）。"},
    "fields": {"zh": "字段清单", "note": "该 kind 携带的字段名。声明后 `TLog(strict=True)` 会按它拦「多字段 / 少字段」；分析侧按它取数。"},
    "desc": {"zh": "说明", "note": "编辑器/文档用。"},
    "category": {"zh": "分类", "note": "编辑器分组用；取值由内容侧定义（框架不设枚举）。"},
    "tags": {"zh": "惯用标签", "note": "该 kind 常用标签（约定，不强制）；记录里的 tags 用来粗筛。"},
}

_MAPS = {
    "topology": {"zh": "形状名", "note": "邻接怎么来的：`chain`（链状，按声明序相邻）/ `star`（星形：枢纽↔辐条、通道↔出口，含无通道时枢纽直连出口的防断链分支）。形状内置于引擎注册表（第三方可注册自己的）；**给了 links 就不派生**，此处写 `mesh` 或留空即可。",
                 "ref": ("reference/space.md", "star")},
    "roles": {"zh": "角色映射", "note": "「角色名 → 取值」的对象（hub/through/exit）。**取值由内容侧定**（引擎不认含义）；缺哪个角色 = 该角色不存在（零默认值），例如没声明 through 就走「无通道」那条防断链分支。",
              "ref": ("reference/space.md", "roles")},
    "nodes": {"zh": "节点表", "note": "**顺序有意义**：链状/星形的「深度」= 声明序（作者按由近及远排），**首节点 = 入口**。每项至少要一个 id。",
              "ref": ("reference/space.md", "nodes")},
    "links": {"zh": "显式连通表", "note": "`{节点id: [可达节点id…]}`。一给就用它（拓扑不参与派生）；**不必对称** —— 视图会把 a→b 但 b↛a 报出来，但**不自动补边**（补边会掩盖数据错误）。",
              "ref": ("reference/space.md", "links")},
    "root": {"zh": "入口节点", "note": "默认 = 首节点。显式连通表的「深度」从它起算（派生形状的深度是声明序，与此无关）。",
             "ref": ("reference/space.md", "root")},
    "gate": {"zh": "出入口节点", "note": "跨图落点 / 出图点（同一个语义）。不填则按角色规则推：首节点是枢纽角色且有出口角色节点 → 那个出口节点；否则首节点。",
             "ref": ("reference/space.md", "gate")},
    "id": {"zh": "节点标识", "note": "图内唯一。连通表、出入口、root/gate 全按它引用 —— 改 id 等于改所有引用方（编辑器不做批量改名）。",
           "ref": ("reference/space.md", "nodes")},
    "role": {"zh": "角色取值", "note": "这个节点算哪种角色（取值要能在本图 roles 映射里对上）。引擎只按角色算几何，**不认取值含义**。",
             "ref": ("reference/space.md", "roles")},
}

GLOSSARY = {
    "*": _COMMON,
    "commands": _COMMANDS,
    "texts": _TEXTS,
    "tlogs": _TLOGS,
    "maps": _MAPS,
    "skills": _SKILLS,
    "monsters": _MONSTERS,
    "affixes": _AFFIXES,
    "items": _ITEMS,
    "effect_rules": _EFFECT_RULES,
    "passive_proc": _PASSIVE_PROC,
}

# ───────────────────────────────────────────── 表单分组（字段按语义分块，别平铺 56 个）
# 每条：id / label / icon / fields（**顶层字段名**，嵌套对象的子键在它自己的分组里渲染）。
# 硬规矩（`tests/test_editor_glossary.py` 断言）：
#   ① 顶层字段**一个不漏、一个不重**地分到组里（漏了会露出「其他」组 = 分类没做完）
#   ② 组里列的名字必须真在 schema 里（防拼错）
#   ③ 顺序即界面顺序（把最常改的放前面）
GROUPS = {
    "skills": [
        {"id": "base", "label": "基础", "icon": "📌",
         "fields": ["name", "desc", "kind", "kind_override", "lv"]},
        {"id": "cost", "label": "消耗与节奏", "icon": "⚡",
         "fields": ["mp", "no_mp", "cd", "cast", "charge", "res_cost"]},
        {"id": "dmg", "label": "伤害与命中", "icon": "💥",
         "fields": ["power", "exprs", "formula", "hits", "aoe", "target",
                    "pierce", "crit", "accuracy", "element"]},
        {"id": "heal", "label": "治疗与减伤", "icon": "🩹",
         "fields": ["heal_formula", "lifesteal", "hp_pct", "reduce_all", "reduce_pct"]},
        {"id": "mech", "label": "状态与机制", "icon": "🌀",
         "fields": ["effect", "buff_turns", "sleep", "mech", "mech_val", "mech_chance",
                    "mech2", "mech2_val", "summon", "team", "stance", "auto", "kill"]},
        {"id": "hate", "label": "仇恨与嘲讽", "icon": "🎯",
         "fields": ["hate_mult", "hate_taunt_mult", "hate_lock_turns"]},
        {"id": "cond", "label": "条件与被动", "icon": "🔗",
         "fields": ["cond", "passive"]},
    ],
    "monsters": [
        {"id": "base", "label": "基础", "icon": "📌",
         "fields": ["name", "desc", "kind", "id", "role", "lv_off"]},
        {"id": "dmg", "label": "招式与伤害", "icon": "💥",
         "fields": ["power", "formula", "element", "aoe", "hits", "multi",
                    "hp_pct", "defend_reduce", "reach", "basic"]},
        {"id": "mech", "label": "机制与行为", "icon": "🌀",
         "fields": ["effect", "mech", "mech_val", "summon", "charge", "cast",
                    "recovery", "pdot", "cond", "chance"]},
        {"id": "world", "label": "出现与掉落", "icon": "🗺",
         "fields": ["skills", "drops", "gold_mult", "tag", "flavor", "maps"]},
    ],
    "commands": [
        {"id": "base", "label": "基础", "icon": "📌",
         "fields": ["key", "desc", "category", "usage"]},
        {"id": "match", "label": "匹配与守卫", "icon": "🎯",
         "fields": ["patterns", "guards"]},
        {"id": "show", "label": "展示与排序", "icon": "🗂",
         "fields": ["visible", "order", "page_size"]},
        {"id": "ext", "label": "扩展", "icon": "🧩",
         "fields": ["extra"]},
    ],
    "texts": [
        {"id": "base", "label": "基础", "icon": "📌",
         "fields": ["key", "value"]},
        {"id": "doc", "label": "说明与分组", "icon": "🗂",
         "fields": ["desc", "category"]},
        {"id": "slots", "label": "占位符", "icon": "🧩",
         "fields": ["params"]},
    ],
    "tlogs": [
        {"id": "base", "label": "基础", "icon": "📌",
         "fields": ["kind", "desc"]},
        {"id": "data", "label": "字段清单", "icon": "🧩",
         "fields": ["fields"]},
        {"id": "doc", "label": "分类与标签", "icon": "🗂",
         "fields": ["category", "tags"]},
    ],
    "maps": [
        {"id": "base", "label": "基础", "icon": "📌",
         "fields": ["name", "desc"]},
        {"id": "shape", "label": "形状与角色", "icon": "🧭",
         "fields": ["topology", "roles", "root", "gate"]},
        {"id": "graph", "label": "节点与连通", "icon": "🗺",
         "fields": ["nodes", "links", "id", "role"]},
    ],
    "affixes": [
        {"id": "base", "label": "基础", "icon": "📌",
         "fields": ["name", "desc", "kind", "line"]},
        {"id": "trigger", "label": "触发与效果", "icon": "⚡",
         "fields": ["trigger", "chance", "effect"]},
        {"id": "drop", "label": "品质与唯一性", "icon": "💠",
         "fields": ["qualities", "unique"]},
    ],
    "items": [
        {"id": "base", "label": "基础", "icon": "📌",
         "fields": ["name", "desc", "price", "type", "quality"]},
        {"id": "use", "label": "使用效果", "icon": "🧪",
         "fields": ["effect", "effect_data", "food_effect", "heal", "mana", "hot",
                    "hot_turns", "hot_mana", "stamina", "cast", "food", "battle_ok"]},
        {"id": "special", "label": "特殊用途", "icon": "🗝",
         "fields": ["key_item", "blueprint_for", "roster_id", "learn_skill",
                    "require_class", "rune_pool", "weapon_pick", "pick_options"]},
    ],
    "effect_rules": [
        {"id": "base", "label": "基础与归属", "icon": "📌",
         "fields": ["name", "tag", "on", "negative", "cleanse"]},
        {"id": "stack", "label": "叠层与面板", "icon": "🔢",
         "fields": ["cap", "stat_scale", "debuff_scale", "panel"]},
        {"id": "period", "label": "周期结算（DOT / HoT）", "icon": "⏳",
         "fields": ["period"]},
        {"id": "cooldown", "label": "冷却与开局", "icon": "🧊",
         "fields": ["cd_mult", "start_full", "start_classes", "load_tiers"]},
        {"id": "guard", "label": "濒死保护", "icon": "🛡",
         "fields": ["guard_hp_pct", "heal_pct", "overload_heal_pct", "wake_on_hit"]},
        {"id": "ctrl", "label": "控制与渠道", "icon": "🌀",
         "fields": ["consume", "channels", "on_threshold"]},
    ],
    "passive_proc": [
        {"id": "hook", "label": "事件钩子", "icon": "⚡",
         "fields": ["event", "action", "also", "agg"]},
        {"id": "domain", "label": "静态域（上限 / 消耗）", "icon": "🗂",
         "fields": ["domain", "cap_key"]},
        {"id": "judge", "label": "判据与条件", "icon": "🔍",
         "fields": ["judge", "when", "mech_prefix", "ctrl_any", "gap"]},
        {"id": "res", "label": "资源与计数", "icon": "📦",
         "fields": ["res", "buff_key", "left_key", "left_init", "used_key",
                    "cost_field", "gain_field", "bar_field"]},
        {"id": "act", "label": "动作参数", "icon": "🎛",
         "fields": ["mode", "form", "spd_pct", "def_pct", "hold"]},
    ],
}


def groups_for(dom: str) -> list:
    """该域的表单分组（深拷贝，调用方随便改）。"""
    return [dict(g, fields=list(g.get("fields") or [])) for g in GROUPS.get(dom, [])]


def all_groups() -> dict:
    """给前端：{域: [{id,label,icon,fields}]}。"""
    return {d: groups_for(d) for d in GROUPS}


# ───────────────────────────────────────────────────────── 控件形态（用对控件，别全靠文本框）
# 依据：**字段语义**（长文案 / 公式列表 / 百分比 / 跨域引用），不是某个游戏的取值。
# 取值一律不写死：自由串走「包内已有值联想」（editor/hints.py），引用走目标域真 key。
#
#   textarea  长文案（描述/风味/公式串）→ 大输入框
#   lines     字符串数组当「一行一条」编辑（表达式 / 引用名列表）
#   pct       0~1 的比值 → 数字 + 滑杆联动（比裸数字直观）
#   chips     枚举数组 → 可多选标签（原先是 JSON 兜底，最容易被吐槽的那种）
WIDGETS = {
    # 长文案
    "desc": "textarea", "flavor": "textarea", "heal_formula": "textarea",
    "line": "textarea", "food_effect": "textarea", "effect_data": "textarea",
    # 一行一条的字符串数组
    "exprs": "lines", "maps": "lines", "qualities": "chips",
    # 0~1 的比值
    "chance": "pct", "mech_chance": "pct", "lifesteal": "pct",
    "guard_hp_pct": "pct", "heal_pct": "pct", "overload_heal_pct": "pct",
}

# 跨域引用：该字段填的应当是**另一个域的真 key**（编辑器据此给真候选，防拼错）
REF_DOMAINS = {
    "skills": "skills",        # monsters.skills —— 招式池
    "drops": "items",          # monsters.drops —— 掉落
    "blueprint_for": "items",  # items.blueprint_for —— 图纸产出
    "learn_skill": "skills",   # items.learn_skill —— 使用后学会的技能
    "start_classes": "classes",   # effect_rules.start_classes —— 归属职业
    "buff_key": "effect_rules",   # passive_proc.buff_key —— 效果 key
    "cap_key": "effect_rules",    # passive_proc.cap_key —— 资源上限 key
    "res": "effect_rules",        # passive_proc.res —— 资源 key
}

# 引擎面板键（**框架协议**，出自 `saintess_engine/battle/stats.py:117-122` 的 actor 面板读取）
# —— 给 stat_scale / panel.stat 这类字段做候选；与任何具体游戏无关。
PANEL_KEYS = ["atk", "def", "matk", "mdef", "spd", "crit", "dodge", "max_hp", "max_mp",
              "hp", "mp", "dmg_mult", "reduce"]
_PANEL_PATHS = {"stat_scale", "panel.stat", "debuff_scale", "stat"}


def widget_for(dom: str, path: str) -> str | None:
    """字段该用哪种控件（None = 按 schema 类型默认渲染）。"""
    e = (GLOSSARY.get(dom) or {}).get(path) or (GLOSSARY.get(dom) or {}).get(str(path).split(".")[-1])
    if e and e.get("widget"):
        return e["widget"]
    leaf = str(path).split(".")[-1]
    return WIDGETS.get(leaf)


def ref_domain_for(dom: str, path: str) -> str | None:
    """该字段引用哪个域的 key（None = 不是跨域引用）。"""
    leaf = str(path).split(".")[-1]
    if str(path) in ("start_classes", "mask", "cap_key", "buff_key"):
        return REF_DOMAINS.get(str(path))
    return REF_DOMAINS.get(leaf)


def suggest_meta(dom: str, path: str) -> dict:
    """给前端一条「怎么联想」的说明（前端只管取候选）。"""
    key = str(path)
    return {
        "widget": widget_for(dom, path),
        "ref": ref_domain_for(dom, path),
        "panel": key in _PANEL_PATHS,
    }


def all_widgets() -> dict:
    """给前端：{域: {字段: {widget, ref, panel}}}（含叶名回退，前端一次查表）。"""
    out = {}
    for dom in DOMAIN_SCHEMA:
        tbl = {}
        for key in list(GLOSSARY.get(dom, {})) + sorted(WIDGETS) + sorted(REF_DOMAINS):
            meta = suggest_meta(dom, key)
            if meta["widget"] or meta["ref"] or meta["panel"]:
                tbl[key] = meta
        out[dom] = tbl
    return out

# 域 → schema 文件（与 packages.DOMAINS 对应；classes 无 schema）
DOMAIN_SCHEMA = {
    "skills": "skill.schema.json", "monsters": "monster.schema.json",
    "affixes": "affix.schema.json", "items": "item.schema.json",
    "effect_rules": "effect_rules.schema.json", "passive_proc": "passive_proc.schema.json",
    "commands": "command.schema.json", "texts": "text.schema.json",
    "tlogs": "tlog.schema.json",
    "maps": "maps.schema.json",
}

# ───────────────────────────────────────────────────────────────────────── 查询
def lookup(dom: str, path: str):
    """单字段词典条目。依次回退：域内精确 → 通用（叶名）。"""
    if not path:
        return None
    leaf = str(path).split(".")[-1]
    for key in (str(path), leaf):
        e = (GLOSSARY.get(dom) or {}).get(key)
        if e:
            return dict(e, dom=dom, path=path, matched=key)
    e = GLOSSARY["*"].get(leaf)
    if e:
        return dict(e, dom=dom, path=path, matched=leaf, generic=True)
    return None


def all_entries() -> dict:
    """给前端：域 → {字段: {zh, note, wiki}}（只发用得到的字段）。"""
    out = {"*": {}}
    for dom, table in GLOSSARY.items():
        out[dom] = {}
        for k, v in table.items():
            out[dom][k] = {
                "zh": v.get("zh", ""),
                "note": v.get("note", ""),
                "wiki": ref_url(v),
            }
    return out


def ref_url(entry: dict | None):
    """词典条目 → 编辑器内 wiki 深链（`wiki:<page>#find=<词>`）。无来源 = None。"""
    ref = (entry or {}).get("ref")
    if not ref:
        return None
    page, term = ref
    return f"wiki:{page}#find={term}"


def wiki_path(page: str) -> str:
    return os.path.join(WIKI_DIR, *page.split("/"))


# ───────────────────────────────────────────────────────── 报错 → 中文（带字段名）
_MSG_RULES = [
    (r"should be non-empty", "不能为空（schema 要求长度 ≥ 1）"),
    (r"is a required property|必填字段缺失", "必填字段缺失"),
    (r"is not of type '(string|integer|number|boolean|array|object)'", None),
    (r"is not one of \[(.+)\]", None),
    (r"is less than the minimum of ([\d.]+)", None),
    (r"is greater than the maximum of ([\d.]+)", None),
    (r"is not valid under any of the given schemas", "取值不满足任一允许形态（见字段注脚）"),
    (r"Additional properties are not allowed", "存在 schema 未声明的字段"),
    (r"is too short", "长度不足"),
]


def _zh_msg(msg: str) -> str:
    if "should be non-empty" in msg:
        return "不能为空（schema 要求长度 ≥ 1）"
    m = re.search(r"is not of type '(\w+)'", msg)
    if m:
        return {"string": "应为文本", "integer": "应为整数", "number": "应为数值",
                "boolean": "应为是/否", "array": "应为列表", "object": "应为对象"}.get(m.group(1), f"类型应为 {m.group(1)}")
    m = re.search(r"is not one of \[(.+)\]", msg)
    if m:
        return f"取值必须是：{m.group(1)} 之一"
    m = re.search(r"is less than the minimum of ([\d.]+)", msg)
    if m:
        return f"不能小于 {m.group(1)}"
    m = re.search(r"is greater than the maximum of ([\d.]+)", msg)
    if m:
        return f"不能大于 {m.group(1)}"
    if "Additional properties are not allowed" in msg:
        return "存在 schema 未声明的字段（该 schema 不允许）"
    if "is not valid under any of the given schemas" in msg:
        return "取值不满足允许的任一种形态（见字段注脚）"
    if "is a required property" in msg:
        return "必填字段缺失"
    if "必填字段缺失" in msg:
        return "必填字段缺失"
    return msg


def friendly(dom: str, errors) -> list:
    """把 schema 原始报错翻成「字段中文名 + 可读原因」。

    输入两种形态都吃：
      - `["desc: '' should be non-empty"]`（编辑器 validate 的输出）
      - `[{"path": "desc", "message": "..."}]`
    """
    out = []
    for e in errors or []:
        if isinstance(e, dict):
            path = str(e.get("path") or e.get("field") or "")
            raw = str(e.get("message") or "")
        else:
            s = str(e)
            path, _, raw = s.partition(": ") if ": " in s else ("", "", s)
            if not raw:
                path, raw = "", s
        path = path.strip().lstrip(".")
        ent = lookup(dom, path) if path else None
        label = (ent or {}).get("zh") or ""
        out.append({
            "path": path,
            "field": path,
            "label": label,
            "message": _zh_msg(raw),
            "raw": raw,
            "wiki": (ent or {}).get("wiki"),
            "display": (f"{path}（{label}）：{_zh_msg(raw)}" if label else
                        (f"{path}：{_zh_msg(raw)}" if path else _zh_msg(raw))),
        })
    return out


def missing_required(dom: str, data: dict, schema_def: dict) -> list:
    """必填项体检（**只判 schema.required + 空值**，不猜业务规则）。"""
    data = data or {}
    out = []
    for k in (schema_def or {}).get("required", []) or []:
        v = data.get(k, None)
        bad = (k not in data) or v is None or (isinstance(v, str) and v.strip() == "")
        if bad:
            ent = lookup(dom, k) or {}
            out.append({"path": k, "label": ent.get("zh") or "",
                        "note": ent.get("note") or "", "wiki": ent.get("wiki"),
                        "display": f"{k}（{ent.get('zh')}）" if ent.get("zh") else k})
    return out
