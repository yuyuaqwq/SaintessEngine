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

包自带词汇表（**包声明 > 框架默认**，与第 2 层 `editor/relations.json` 同一套纪律）
-------------------------------------------------------------------------------
本文件的 `GLOSSARY` / `GROUPS` / `WIDGETS` 是**框架默认值（回退）**，不是真源：游戏专属词汇
（字段叫什么、分几组、哪些字段是长文案）住在框架里 = 「加一个域就得改框架」。真源改为**包侧
每域一个文件** `<pkg>/editor/glossary/<域>.json`（缺目录 = 没声明）：

    {
      "fields": {
        "name":                {"zh": "名称", "note": "…", "group": "base"},
        "effect_data":         {"zh": "效果参数", "widget": "textarea"},
        "rid":                 {"zh": "产出 id", "ref": {"domain": "equip_roster", "by": "key"}}
      },
      "groups": [{"id": "base", "label": "基础", "icon": "📌", "fields": ["name", "desc"]}]
    }

* **fields**：查字段**先问包**（精确路径 → 叶名），命中即用包那条（`source="package"`）；
  没命中才回退框架 `GLOSSARY`（域内精确 → 域内叶名 → 通用叶名）。**条目整条替换，不做
  字段级合并**（包写了 zh 没写 note = 这条没注脚，不拿框架注脚来补，免得注脚半包半框架）。
* **groups**：包给了就是**该域的完整分组表**（整表替换，不合并）；包没给用框架 `GROUPS`。
* `widget` 取本层控件词表 `PKG_WIDGETS`（textarea / lines / pct / chips / rows / kv / select）；
  不在词表 → 丢该属性 + 一条 warning。前端目前只实现前 4 种，其余按 schema 类型默认渲染
  （`web/schema_form.js` 的分派对未知形态不报错）。
* `ref` = 跨域引用（`{"domain": …, "by": "key|name"}`）→ **只喂下拉候选**
  （`ref_source="package_vocab"`）；**引用校验面归 `relations.json`**（同一件事两处声明会打架）。
* `wiki`（可选，本层超出冻结约定的扩展键）= `["页.md", "页内词"]` → 编辑器内文档深链；
  别的实现忽略它即可（不冲突）。
* **坏声明只降级、绝不抛**（坏 JSON / 顶层非对象 / 未知域 / 元非对象 / widget 不在词表 /
  ref 形状不对 / 组形状不对）→ 丢那部分 + 一条可读 warning，其余照用；告警从
  `glossary_warnings(pkg_dir)` 取（`/api/glossary` 与包概览带回前端，不静默）。

对外接口
--------
    lookup(dom, path, pkg_dir=None) -> dict | None   # 包词汇表 → dom 精确 → 通用叶名
    all_entries(pkg_dir=None) -> dict                # 给 /api/glossary
    groups_for(dom, pkg_dir=None) / all_groups(pkg_dir=None)
    widget_for(dom, path, pkg_dir=None) / all_widgets(pkg_dir=None)
    friendly(dom, errors, pkg_dir=None) -> list      # schema 报错 → 中文（带字段中文名）
    missing_required(dom, data, schema_def, pkg_dir=None) -> list
    ref_url(entry, pkg_dir=None) -> str | None       # 词典条目 → 编辑器内 wiki 深链
    wiki_path(page, pkg_dir=None) -> str             # 页名 → 文件路径（包内优先 → 框架兜底）
    package_glossary(pkg_dir) -> dict                # 规范化后的包词汇表
    glossary_warnings(pkg_dir) -> [可读告警]
    declared_vocab(pkg_dir, dom, path) -> dict | None  # **只认包声明**
"""
from __future__ import annotations

import json
import os
import re

from editor import packages as PK      # 域注册表（DOMAIN_SCHEMA 从它派生；packages 不 import glossary，无环）
from editor import wiki as WK          # 页面解析（wiki 不 import glossary，无环；真源在 wiki.py）

HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(HERE)
WIKI_DIR = os.path.join(FW_ROOT, "docs", "engine-wiki")
# 包内 wiki 目录（**单一真源在 `editor/wiki.py`**，这里只是别名，免得两处各写一份路径）
PKG_WIKI_REL = WK.PKG_WIKI_REL

# ─────────────────────────────────────────────────────────────── 通用（跨域叶名共用）
_COMMON = {
    "name": {"zh": "名称", "note": "显示名。多数表里它也是引擎日志/索引用的标识（技能冷却表即以显示名为 key，改名等于放弃旧冷却条目）。",
             "ref": ("reference/skill-availability.md", "cd")},
    "desc": {"zh": "描述", "note": "展示文案。**是否必填以该域 schema 为准**：物品/技能等域是「必填且非空」（minLength=1，新建被拦最常见就是这里）；名册/挂载类域（如装备名册、交互点、宠物）**允许无描述** —— 那些域在上面的域注脚里各自写明，覆盖本条。",
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
# 注脚的核实口径（2026-09-12 全字段审计）：逐键统计参考实现 items.py 的 ITEMS/MATERIALS/
# CONSUMABLES 三张表（25 个字段，1 304 条条目），再到内容侧的消费点逐键搜读取处。
# 凡「逐键搜索未发现读取点」的字段，注脚写「疑似死字段」而不是编一个语义。
_ITEMS = {
    "price": {"zh": "价格", "note": "基础售价（货币单位与折扣口径内容侧定）。消费点：出售 / 商店 / 合成抵扣；实测 0~6000 整数。", "ref": None},
    "type": {"zh": "物品类型", "note": "内容侧分类串，内容侧按它分派（品种识别 / 任务道具判定 / 图纸归类）。实测 23 个中文取值 —— **不能改成 enum**：schema 的门禁禁止非 ASCII 枚举值，历史上正是把物品分类抄进 enum 出过事故。", "ref": None},
    "quality": {"zh": "品质", "note": "框架模板的 5 档品质（white/green/blue/purple/orange），实测取值与 enum 完全一致；内容侧按它查品质表算价 / 掉落 / 收藏。", "ref": None},
    "effect": {"zh": "效果名词", "note": "决定走哪条执行链：内容侧先用它命中的**模板名**分发，未命中才回落通用处理。名词→行为由内容侧声明，框架不预设。", "ref": ("concepts/declaration-tables.md", "effect")},
    "effect_data": {"zh": "效果参数", "note": "配合 effect 的自由参数字典（实测 51 种形状 / 87 个子键，各模板数值不同），内容侧把整块随 payload 传下去。表单对自由结构走 **JSON 兜底**，所以这里的键不会因为渲染而丢。", "ref": None},
    "food_effect": {"zh": "食物效果", "note": "战斗内获得的食物效果名词（本场有效）；内容侧有专职模板读它并把效果装成触发器。", "ref": None},
    "heal": {"zh": "回血", "note": "回复量**双形态**（分档由内容侧消费点做）：≤1 = 按最大生命比例，>1 = 固定点数（旧式配方）。实测 0.1~1.0 走比例、150/300/500 走固定值。", "ref": ("reference/effect-actions.md", "heal")},
    "mana": {"zh": "回魔", "note": "回复量，与回血同规则：≤1 = 按最大魔力比例，>1 = 固定点数。实测取值 0.1~1.0，只用了比例形态。", "ref": ("concepts/effects.md", "mana")},
    "hot": {"zh": "持续回血", "note": "战斗内**每刻**回复的最大生命比例（HoT），持续刻数看 hot_turns；实测 0.03~0.1。有没有 hot / hot_mana 也是内容侧判定「食物」的依据之一。", "ref": ("concepts/effects.md", "hot")},
    "hot_turns": {"zh": "持续刻数", "note": "HoT / 持续效果结算的刻数；内容侧缺省 3，实测 3~5。", "ref": None},
    "hot_mana": {"zh": "持续回魔", "note": "战斗内每刻回复的最大魔力比例；实测 0.04~0.12。只有 hot_mana 没有 hot 的条目同样算食物（内容侧为此专门修过那条推断）。", "ref": None},
    "stamina": {"zh": "体力", "note": "回复的行动体力**点数**（绝对值，实测 15~60）；体力满时不消耗道具（内容侧消费点拦截）。", "ref": None},
    "cast": {"zh": "使用耗时", "note": "使用该道具的行动耗时（刻，实测 0.3~2.5）；战斗中会内嵌进该次行动作为时长。注意与技能侧 cast 的历史哨兵 \"None\" 不同：物品侧实测全是数值。", "ref": ("reference/channels.md", "cast")},
    "food": {"zh": "食物", "note": "食物标记：内容侧的进食 / 喂养白名单按它筛（与「鱼」类并列）。", "ref": None},
    "battle_ok": {"zh": "可战中使用", "note": "⚠ 内容侧实际读的是**模板级**开关（模板注册表的 battle_ok），逐键搜索未发现读取物品本字段的点 —— 数据里 20 条声明疑似冗余 / 死字段（用前看装配器）。", "ref": None},
    "key_item": {"zh": "关键道具", "note": "⚠ 数据里 16 条为 True。内容侧所有 key_item 读取点都落在**副本数据**上（按名字三路匹配背包），逐键搜索未发现读物品本字段的点 → 疑似死字段（用前看装配器）。", "ref": None},
    "blueprint_for": {"zh": "图纸产出", "note": "该图纸能制造的目标（装备名 / 名册项）；内容侧用它做「已学图纸」比对与锻造引导。", "ref": None},
    "roster_id": {"zh": "名册 id", "note": "关联的名册装备 id（eq_ 前缀，schema 带 pattern）。内容侧按它查名册、建合成配方 —— 与 blueprint_for 一起构成「图纸↔装备」的双向锚点。", "ref": None},
    "learn_skill": {"zh": "学习技能", "note": "使用后学会的技能名（指向技能域的 key，按名解析）；内容侧优先于通用 effect 判定（技能书类模板）。", "ref": None},
    "require_class": {"zh": "限定职业", "note": "只有该职业可用（内容侧取值，可空 = 全职业）；与 learn_skill 走同一条校验链。**取值是内容侧职业 id，框架不预设也不列举**。", "ref": None},
    "rune_pool": {"zh": "符文池", "note": "⚠ **当前无消费者**：逐键搜索全仓只有 2 处定义、0 处读取（抽符文的池由内容侧另一张表管）。数据留着它，但改它不会改变任何行为。", "ref": None},
    "weapon_pick": {"zh": "武器自选", "note": "开启自选（配合 pick_options）：使用后弹职业选项，按玩家回填的数字发放对应装备。", "ref": None},
    "pick_options": {"zh": "自选选项", "note": "自选清单，每项 name / rid / desc；实测只有 1 条数据带它（6 个选项）。", "ref": None},
    "pick_options.name": {"zh": "选项名", "note": "自选项的显示名（含图标与提示的展示文案）。", "ref": None},
    "pick_options.rid": {"zh": "选项产出 id", "note": "选中后产出的名册装备 id（eq_ 前缀，内容侧按它发装备）。", "ref": None},
    "pick_options.desc": {"zh": "选项说明", "note": "自选项的说明文案（展示用）。", "ref": None},
}

# ───────────────────────────────────────────────────────────────────── 装备名册
# 注脚核实口径（2026-09-13）：逐键统计包内 `games/orlandia/content/data/equip_roster.json`（687 条）的字段
# 分布，再到内容侧消费点逐键搜读取处（穿戴门槛 / 商店与锻造 / 掉落白名单 / 装备生成 / 面板与图鉴 / 武器特效）。
# 凡「逐键搜索未发现读取点」的字段（如 series_set），注脚直说它不驱动行为；本仓 wiki 没有名册页 → ref 一律 None。
_EQUIP_ROSTER = {
    "name": {"zh": "名称", "note": "装备显示名（内容侧词汇）。它同时是本表的**跨表连接锚点** —— 导出期按名把「装备名 → 固定词条」源表接进 fixed_affixes，改名会断开这条连接。⚠ 实测 687 条里有 1 处重名（同名对应 2 个不同 key）：按名连接落在重名上时导出器直接报错，不静默选一条。", "ref": None},
    "slot": {"zh": "部位", "note": "装配槽位名（取值由内容侧定，框架不枚举 —— 枚举会把「加一个部位」变成改框架 schema）。内容侧按它选槽、算基础属性与价格、判两件装备是否互斥。实测 7 种取值。", "ref": None},
    "weapon_type": {"zh": "武器类型", "note": "武器细分类型名（内容侧词汇，框架不枚举）。只写在武器部位条目上（实测 241 条，241/241 都是 slot=weapon，非武器 0 条带它）。内容侧按它判职业能否使用、查武器风味文案、算价格。", "ref": None},
    "quality": {"zh": "品质", "note": "品质档名（取值由内容侧定，框架不枚举；**不能改成 enum** —— 门禁禁止非 ASCII 枚举值，历史上正是把内容侧分类抄进 enum 出过事故）。内容侧按它算价格倍率、筛掉落与收藏。实测 5 档。", "ref": None},
    "lv": {"zh": "等级", "note": "装备等级档（整数 ≥ 1，schema minimum=1）。内容侧的穿戴准入、掉落等级窗口、图纸/锻造等级都按它比。实测 2~100。", "ref": None},
    "series": {"zh": "系列", "note": "归属系列名（内容侧的**显示名**，不是 key）。它是 series_set 派生字段的连接键，也是「同系列可成套」的判据。实测 221 个系列名，只有 38 个能在「系列 → 套装名」表里查到 —— 查不到属正常（缺省 = 无套装名，不是坏数据）。", "ref": None},
    "series_set": {"zh": "系列套装名（派生）", "note": "导出期按 series 查「系列 → 套装名」源表连接进来的派生字段；没有该映射的系列**不写这个字段**（缺省 ≠ 空串）。⚠ 逐键搜索内容侧没有读取点：运行时是在**生成装备时按 series 查源表**拿套装名（写进实例的 set），所以改这里的值不改变任何行为 —— 它给编辑器/审计看，且与条目自带的 set 可能取值不同。", "ref": None},
    "set": {"zh": "套装名（条目自带）", "note": "条目自带的套装名（内容侧词汇）。⚠ 与 series_set **来源不同**：这是源条目里的字段，series_set 是导出期连接的派生字段，两者的取值属于不同名称空间（实测 set 仅 12 个取值、series_set 38 个）。内容侧的套装件数统计与套装说明读的是运行期写下的实例字段，不是名册里的这一列。", "ref": None},
    "source": {"zh": "来源（获取途径）", "note": "获取途径名（内容侧词汇）。⚠ 它**不是纯展示字段**：内容侧按它做掉落白名单、商店/锻造进货过滤（把特定来源的装备排除出货架）与图纸配方筛选 —— 改它会改变发放结果。实测 12 个取值。", "ref": None},
    "req": {"zh": "属性需求", "note": "`{属性名: 需求值}`。属性名是内容侧词汇（框架不枚举，schema 也**故意不写 properties** —— 写了就会长出一份框架侧属性表）；值为非负整数。**缺该字段 = 无门槛**（不是 0）。内容侧在穿戴/购买时逐项比对并拦下不达标的操作。实测 581 条带它、4 种属性名。", "ref": None},
    "desc": {"zh": "描述", "note": "展示文案。⚠ 本域**允许无描述**（schema 不给 minLength，实测 639/687 有）—— 与物品域「必填且非空」不同，编辑器别按物品域的口径去催。", "ref": None},
    "special": {"zh": "专属说明", "note": "该装备专属效果的**说明文本**（内容侧词汇，展示用）。机器可读的那一半在 legendary / weapon_effect；改这里的文字只改玩家看到的说明，不改变行为。实测 151 条。", "ref": None},
    "legendary": {"zh": "传说专属特效 id", "note": "指向内容侧「传说专属特效」表的 id（内容侧按它取效果）。实测 145 条 / 107 个 distinct。⚠ 该表**未进包**（框架没有对应域）→ 包内这条引用目前解析不到目标，是已知缺口。", "ref": None},
    "weapon_effect": {"zh": "武器特效 id", "note": "指向内容侧武器特效实现的 id —— 实现是代码，不属于任何数据域，引擎不认识它。与 we_data 配对：内容侧按 id 找处理器、把 we_data 并进配置。实测 99 条。", "ref": None},
    "we_data": {"zh": "武器特效参数", "note": "配合 weapon_effect 的**自由参数字典**（各特效形状不同，实测仅 9 条带它）。结构与键名由内容侧解释；表单对自由结构走 JSON 兜底，键不会因为渲染而丢。", "ref": None},
    "affix": {"zh": "固定词条 id（单值旧形态）", "note": "单值的固定词条引用（**旧形态**，与 affixes 并存，实测仅 10 条）。内容侧把它当**展示文案**用（列表里的「效果：…」一行），不做词条解析。", "ref": None},
    "affixes": {"zh": "固定词条 id 列表", "note": "该装备的固定词条引用表（列表，实测 42 条、每件 1~2 条）。内容侧生成装备实例、装配触发器、面板统计与副本掉落筛选都读它。⚠ 与 fixed_affixes **来源不同**（这是条目自带，那是导出期按名连接的），别把两者当同一份。", "ref": None},
    "fixed_affixes": {"zh": "系列固定词条 id 列表（派生）", "note": "导出期按 name 把「装备名 → 固定词条 id 列表」源表连接进来的派生字段（实测 622 条，其中 11 条是**空列表** —— 源表显式的「无固定词条」标记，与「源表里没有这个名字」是两回事）。⚠ 内容侧消费端读源表并**只取第 1 条**（数据层保留完整供回退），所以这里看到 2 条以上并不代表实战全部生效。", "ref": None},
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
    "period.pct_boss": {"zh": "Boss 档比例", "note": "✅ 标签档覆盖 pct_max_hp：目标带该周期声明的 `trait_tags` 里任一标签时才生效（引擎不认「Boss」，只问 traits.has_any；名单为空 ⇒ 一律不生效）。pct_boss / boss_pct_mult / pct_cur_boss 是这张声明表自己的字段名。", "ref": ("reference/effect-rules.md", "pct_boss")},
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
    # 域内精确控件：文案模板是**多行**的（实测最长 126 字、11 条含换行，如面板/日志的分段排版串），
    # 单行 input 编辑会把换行挤掉。这里按域内路径命中，不会波及其它域的 `value`（`widget_for` 域内精确优先于叶名）。
    "value": {"widget": "textarea", "zh": "模板串",
              "note": "模板串，用 {slot} 占位。未知槽渲染时**原样保留**（不抛），便于发现问题。多行输入 —— 面板/日志类文案常自带换行排版（实测最长 126 字、11 条含换行）。"},
    # params 是**字符串数组**（占位符名清单）—— 与 WIDGETS 里 `lines`（一行一条的字符串数组）同一语义。
    "params": {"widget": "lines", "zh": "占位符声明", "note": "声明的占位符名；缺省由模板自动抽取。声明后会与模板比对（多/少都报）。"},
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

# ───────────────────────────────────────────────────────────────────── 掉落池（随机产出形状）
# 语义出处：`docs/engine-wiki/reference/loot.md`（引擎侧 `LootTable` 的池 / 策略 / 展开 / 审计）。
# 注意：本域**不做引用解析**（resolver 由内容侧给）—— 注脚凡是涉及「这条产出是什么」的地方，
# 都只说「内容侧解释」，不替它编答案。
_DROP_POOLS = {
    "type": {"zh": "策略名", "note": "怎么从这个池里取：内置 `weighted`（按 w 抽样）/ `fixed`（全给）/ `table`（每行独立判定 chance）/ `table_choice`（互斥档 cutoff）。**自由串，不设枚举** —— 内容侧可 `register_strategy` 注册自己的策略名（如按内容做的专属策略）；未注册的名字引擎按 `weighted` 兜底，编辑器预览会就此给警告。",
             "ref": ("reference/loot.md", "register_strategy")},
    "entries": {"zh": "条目表", "note": "条目表（`weighted` / `fixed` 型池用）：每项 {item, w, n, min_lv, max_lv}。`weighted` 按 w 加权抽；`fixed` 是必掉清单，全给。",
                "ref": ("reference/loot.md", "entries[{item,w,n,min_lv,max_lv}]")},
    "rolls": {"zh": "抽行表", "note": "抽行表（`table` / `table_choice` 型池用）：每行 {pool, chance, cutoff, n, fallback, fallback_n}。行里的 pool 指向**子池**（递归走它自己的策略）或内容侧引用。",
              "ref": ("reference/loot.md", "rolls")},
    "fallback": {"zh": "兜底产出", "note": "抽空时的兜底：条目表型池在候选被等级窗口滤空时调 `ctx.fallback_roll` 钩子；roll 行在子池/引用抽空时改抽这一条的 fallback（份数用 fallback_n）。**没声明 = 抽空就是空**（零默认值）。",
                 "ref": ("reference/loot.md", "fallback")},
    "desc": {"zh": "说明", "note": "说明（编辑器/文档用）。本域 schema 不强制长度，可留空。", "ref": None},
    "item": {"zh": "产出引用", "note": "产出引用串：**写法由内容侧定**（前缀、id 形态都是内容词汇）。引擎不认识它 —— `resolver(ref, ctx)` 由内容侧提供；编辑器预览只显示结构与权重，**不假装知道这是哪件物品**。",
             "ref": ("reference/loot.md", "item")},
    "w": {"zh": "权重", "note": "相对权重（**不是**概率）。`weighted` 型按它对条目加权抽样；缺省 1。占比 = 本行 w ÷ 池内权重和（预览里的 share）。**权重和 ≤ 0 = 谁都抽不到**（审计报「空池」）。",
          "ref": ("reference/loot.md", "weight")},
    "n": {"zh": "份数", "note": "出多少份：整数，或 `[min,max]` 闭区间（区间取随机 —— 由 `roll_range` 解释，随机源可注入所以可复现）。缺省 1。",
          "ref": ("reference/loot.md", "roll_range")},
    "min_lv": {"zh": "等级下限", "note": "等级窗口下限：上下文等级（`player_level` / `monster_lv`）低于它 → 该条**不进候选**。上下文等级为 0（未给）视为不做窗口判断。⚠ 预览没有上下文，占比是按全量权重算的。",
               "ref": ("reference/loot.md", "min_lv")},
    "max_lv": {"zh": "等级上限", "note": "等级窗口上限：上下文等级高于它 → 该条不进候选。其余与 min_lv 同。",
               "ref": ("reference/loot.md", "max_lv")},
    "pool": {"zh": "子池 / 引用", "note": "子池 key（本域数据里的另一个池）**或**内容侧引用串。是子池 → 递归走它自己的策略；否则交给内容侧 resolver。两侧都不是 → 审计报「断链」。",
             "ref": ("reference/loot.md", "子池")},
    "chance": {"zh": "命中概率", "note": "0~1。`table`：每行独立判定，不中即跳过。`table_choice`：整表**没有任何 cutoff** 时，按声明序取首个命中的行；全不中 → 空。",
               "ref": ("reference/loot.md", "chance")},
    "cutoff": {"zh": "累计档边", "note": "0~1 的**累计**概率档边。整表只要出现任一 cutoff，就整体走互斥档语义：按声明序累加，首个 acc > roll 者中选，**一次只进一档**；末档会在累计不足 1.0 时容错兜底（引擎不为小瑕疵吞奖励）。",
               "ref": ("reference/loot.md", "cutoff")},
    "fallback_n": {"zh": "兜底份数", "note": "走 `fallback` 时的份数；缺省 = 本行 `n` 的份数。",
                   "ref": ("reference/loot.md", "fallback_n")},
}

_INSTANCES = {
    "name": {"zh": "名称（副本名 / 层名）", "note": "叶名 `name`：副本对象上是**副本名**、层对象上是**层名**（都是内容侧词汇）—— 玩家输入的命令文本会用到它，措辞表在内容侧。留空会被视图当坏数据报出来。", "ref": None},
    "lv": {"zh": "需求等级", "note": "需求等级（准入链的一关；判定与拒绝措辞都在内容侧，视图只显示数值）。", "ref": None},
    "icon": {"zh": "图标", "note": "面板图标（内容侧自选；空则界面用默认）。", "ref": None},
    "min_players": {"zh": "最少人数", "note": "最少人数。`1` 且 max_players 也为 `1` = 纯单人副本（无队也能开）。", "ref": None},
    "max_players": {"zh": "最多人数", "note": "最多人数。`min_players ≤ 1 < max_players` = 弹性副本（无队按单人开）。min_players > max_players 是坏数据，视图直接报错。", "ref": None},
    "key_item": {"zh": "钥匙物品", "note": "钥匙物品引用（内容侧词汇；空 = 本副本不要钥匙）。「怎么算持有钥匙」的三路匹配口径属于内容侧规则，视图不判。", "ref": None},
    "key_source": {"zh": "钥匙获取途径", "note": "钥匙获取途径的取值（内容侧词汇）—— 只用来拼提示里「获取途径」那一句的槽位。", "ref": None},
    "entry": {"zh": "入口", "note": "入口位置（地图 + 子区域，都是内容侧词汇）。「人得站在入口才能开本」这类红线是内容侧规则。", "ref": None},
    "map": {"zh": "入口地图", "note": "入口所在地图引用（内容侧词汇）。", "ref": None},
    "subarea": {"zh": "入口子区域", "note": "入口所在子区域引用（内容侧词汇）。留空时内容侧可回退到 id —— 回退口径由内容侧定，视图不替它选。", "ref": None},
    "boss": {"zh": "Boss（终局 / 本层）", "note": "叶名 `boss`：副本对象上 = **终局 Boss**（空 = 不设）、层对象上 = **本层 Boss 表**（内容侧词汇）。注意这里是**副本级**的 Boss，和层内的 `stages.boss` 不是一回事。", "ref": None},
    "hp_mult": {"zh": "血量倍率", "note": "副本内怪物血量倍率（`1.0` = 不调）。≤ 0 是坏数据，视图直接报错。", "ref": None},
    "atk_mult": {"zh": "攻击倍率", "note": "副本内怪物攻击倍率（`1.0` = 不调）。≤ 0 是坏数据，视图直接报错。", "ref": None},
    "stages": {"zh": "层表", "note": "层表：**顺序即推进顺序**（引擎 `Progress` 的节点序，`is_last` 就是末层判定）。层空（没有怪/精英/Boss）= 坏数据，视图如实报错不伪装；Boss 放非末层同样报错。", "ref": None},
    "monsters": {"zh": "普通怪", "note": "本层普通怪引用表（内容侧词汇）。视图把它们折算成本层要清的单位数（剩余池 `units`）。", "ref": None},
    "elite": {"zh": "精英怪", "note": "本层精英怪引用表（内容侧词汇）。与普通怪一样计入本层单位数。", "ref": None},
    "pois": {"zh": "兴趣点", "note": "本层兴趣点引用表（内容侧词汇）。只展示，不计入进度单位。", "ref": None},
    "secret": {"zh": "隐藏房间", "note": "本层隐藏房间/暗格引用（内容侧词汇；空 = 本层没有）。", "ref": None},
    "npc": {"zh": "本层 NPC", "note": "本层 NPC 引用（内容侧词汇；空 = 本层没有）。", "ref": None},
    "gold": {"zh": "通关金币", "note": "通关金币（发奖口径属于内容侧；视图只显示数值）。", "ref": None},
    "exp": {"zh": "通关经验", "note": "通关经验（同上）。", "ref": None},
    "materials": {"zh": "通关材料", "note": "通关材料引用表（内容侧词汇）。", "ref": None},
    "desc": {"zh": "说明", "note": "说明（编辑器/文档用）。本域 schema 不强制长度，可留空。", "ref": None},
}

# ───────────────────────────────────────────────────────────────────── 交互点（POI）
# 注脚核实口径（2026-09-13）：逐键统计包内 `games/orlandia/content/data/pois.json`（457 条挂载 / 855 条引用，
# 其中内联点 66 条）的字段分布，再到内容侧消费点（副本交互处理链 `_handle_poi` / 运行时合并表）逐键搜读取处。
# 本域是「一条 = 一个房间的挂载」；内联点的 id/type/name/hint 等只在对象形态里出现 —— 注脚区分了这两层。
# 本仓 wiki 没有 POI 页 → ref 一律 None。
_POIS = {
    "map": {"zh": "地图", "note": "房间所在地图（内容侧词汇；与 maps 域的表键同源，编辑器据此可跳过去）。⚠ 框架**不做跨域校验**：「这张图是否真在 maps 里」不会在 schema 层被拦（实测 457 条全部对得上，97 张图，属内容侧自觉）。", "ref": None},
    "subarea": {"zh": "子区域（房间）", "note": "房间引用（内容侧词汇；与 maps 域那张图的 `nodes[].id` 同源）。表键 = 「地图id:子区域id」，两段都不能含空白 —— 键里不带冒号就没法对回地图。", "ref": None},
    "pois": {"zh": "挂载的交互点表", "note": "本房间挂载的交互点：**声明顺序即展示顺序**。两种写法混用合法 —— 字符串 = 类型引用（沿用内容侧对该类型的定义，实测 789 条）、对象 = 本点自带 id/type 与产出（实测 66 条）。⚠ 不挂点的房间请**删键**：schema 要求 minItems=1，空数组会被两条校验路径（jsonschema / 内置 mini）都拦下。", "ref": None},
    "source": {"zh": "挂载来源", "note": "出处标记（自由串，schema 不枚举）。⚠ 它是**导出器**填的、内容侧源表里没有这个词：三张同形表在装配期被并进同一张运行时表，出处只能在这一层保留（实测 world 205 / mesh 197 / dungeon 55）。改它只影响编辑器分组与审计口径，不影响运行时读到的挂载。", "ref": None},
    "id": {"zh": "交互点 id", "note": "本点在表内的唯一标识（**只有内联对象形态才有**）。内容侧按它记录「这点已经交互过」的状态 → **改 id 等于丢状态**。跨表唯一与否由内容侧负责（实测内容侧的做法是 id 前缀 = 地图 + 层号，66/66 唯一）。", "ref": None},
    "type": {"zh": "交互点类型", "note": "交互点类型（内容侧词汇）：决定怎么触发、走哪条处理链（副本侧的处理链在内容侧命令层）。框架不预设任何类型名，也**不校验**这里的取值是否真被内容侧定义过 —— 拼错不会报错，只会静默不生效。", "ref": None},
    "name": {"zh": "名称", "note": "内联交互点的展示名（内容侧词汇，可留空 —— 留空时界面按 id 显示）。⚠ 挂载条目本身没有 name，编辑器列表显示的是表键（「地图id:子区域id」）。", "ref": None},
    "hint": {"zh": "探索提示", "note": "展示给玩家的探索提示文案（内容侧词汇，可留空）。实测 66 个内联点全部带它。", "ref": None},
    "loot": {"zh": "产出块", "note": "该点的产出（货币 / 材料 / 装备…）：**结构与键名全由内容侧解释**，框架不预设（schema 只要求它是非空对象；表单对自由结构走 JSON 兜底，键不会因为渲染而丢）。实测 66 个内联点里 32 条带它。", "ref": None},
    "effect": {"zh": "机制效果块", "note": "交互触发后对场景/流程的作用（开锁 / 开门 / 跳怪…）：结构与键名由内容侧解释，框架不预设；**指向别的交互点的引用写法也在内容侧**（框架不做引用解析）。实测 13 条带它。", "ref": None},
    "need": {"zh": "交互前置块", "note": "能触发本点的前置条件（如先读过某个点）：结构与键名由内容侧解释，框架不预设。实测 4 条带它 —— 带前置的点在条件不满足时是「不可交互」，不是报错。", "ref": None},
    "lore": {"zh": "长文本", "note": "碑文 / 铭文 / 日志类的长文本（内容侧词汇，可留空）。实测 12 条都是整段碑文，适合按长文案编辑。", "ref": None},
    "desc": {"zh": "说明", "note": "触发后展示的说明文案（内联形态；挂载条目上则是编辑器/文档用的一句话说明）。本域**不强制非空**：实测 457 条挂载里 0 条写它、66 个内联点里 8 条写它 —— 只给机制型交互点或备注写。", "ref": None},
}

# ───────────────────────────────────────────────────────────────────── 传说专属特效
# 注脚核实口径（2026-09-13）：逐键统计包内 `games/orlandia/content/data/legendary_effects.json`（93 条）的
# 字段与取值分布，再到内容侧消费点逐键搜读取处（装备生成的 stat 折算 / 装备详情与图鉴展示 / 词条短名回退 /
# 战斗侧按 id 注册的词条翻译器表）。凡「逐键搜索未发现读取点」的字段，注脚直说它当前不进结算；
# 本仓 wiki 没有对应页 → ref 一律 None（不编空链接）。
_LEGENDARY_EFFECTS = {
    "kind": {"zh": "类别", "note": "该条特效的类别名（内容侧词汇，框架不枚举 —— 枚举会把「加一类」变成改框架 schema）。实测 93 条只有 2 种取值；⚠ 逐键搜索内容侧**没有**读本域 kind 的行为分派（按 kind 分派的是词条域的表）→ 当前它是展示 / 分类字段。", "ref": None},
    "trigger": {"zh": "触发时机", "note": "触发时机名（内容侧词汇，框架不枚举 —— 合法词表由内容侧声明，框架不复制第二份）。实测内容侧只有一处按它分派：装备生成时**只对写 `stat` 的条目**做面板折算（`game/core/drops.py:33-41`，非 stat 直接早退）；其它时机值的行为挂点不在战斗侧按 id 注册的词条翻译器表里（实测该表与 93 个特效 id 的交集为 0，但内容侧可能还有别的落点，未全量核实）。⚠ 由此框架**不会拦住「写了没有挂点的时机」**，本包实测有 1 条这样的数据。", "ref": None},
    "chance": {"zh": "触发概率", "note": "0~1 的比值（**形状约束，不是取值词汇**）。实测 93 条里 27 条写它，只用了 7 个档位（0.05~1.0）。**缺该字段 = 概率语义交给内容侧**（参考实现里「不写」= 不定概率的常驻 / 恒触发形态），框架**不补默认值**。⚠ 实测内容侧的概率读取函数查的是**词条域**的表（`game/services/battle_equip_proc.py:316-318`）→ 本域的 chance 进包后是给编辑器 / 审计看的。", "ref": None},
    "effect": {"zh": "效果参数", "note": "效果参数块（**内部结构由内容侧定义**）。实测 93/93 都是非空对象（条内 1~6 个子键，合计 57 个不同子键），子值有数值 / 字符串 / 布尔 / 字符串列表四种形态；schema **故意不写子键**（写了就是在框架里长出第二份内容侧词汇表，且子值类型并不统一）。内容侧读它只在一处：`stat` 型条目逐个子键折算进面板（`game/core/drops.py:33-41`，只认固定几个键名）。⚠ 改子键名要同步改内容侧解释器，否则**静默不生效**。", "ref": None},
}

# ───────────────────────────────────────────────────────────────────── 宠物
# 注脚核实口径（2026-09-13）：逐键统计包内 `games/orlandia/content/data/pets.json`（16 条）的字段分布，
# 再到内容侧消费点逐键搜读取处（打怪掷蛋 / 垂钓与任务奖励 / 孵化与图鉴 / 面板与蛋详情 / 台词）。
# 凡「逐键搜索未发现读取点」的字段，注脚直说数据层保留、当前不驱动行为；
# 本仓 wiki 没有宠物页 → ref 一律 None（不编空链接）。
_PETS = {
    "key": {"zh": "品种 id", "note": "表键，也是条目自带的 `key`（schema 对三处用同一串 pattern：条目字段、规则行字段、整表键名）。实测内容侧全按它做跨表引用与持久化：掉落池写 `petegg:<key>`（`game/drop_engine.py:141-146`）、孵化的蛋物品存它、孵化时进玩家宠物行与图鉴主键（`game/store/social.py:798`）。⚠ 改 key = 断引用 + 丢玩家已有的该品种记录；实测 16 个键全匹配 `^pet_[a-z0-9_]+$`，0 重复。", "ref": None},
    "name": {"zh": "名称", "note": "品种显示名（内容侧词汇）。孵化时被**抄进**玩家宠物行（`game/core/item_templates.py:717`）→ 改名只影响**新**孵化的，已有记录仍是旧名。实测 16 个名字 0 重名（按名找品种会变歧义）。", "ref": None},
    "icon": {"zh": "图标", "note": "展示用字形（内容侧词汇，可以是任意字符）。实测面板 / 孵化文案 / 蛋详情三处把它直接拼进玩家可见文案（`game/commands/social.py:919`、`game/core/item_templates.py:722`、`game/commands/economy.py:449`）。schema **不强制存在**（缺该字段时界面回退通用图标）；实测 16/16 都有。", "ref": None},
    "quality": {"zh": "品质档", "note": "品质档名（内容侧词汇，框架不枚举 —— 不同内容侧档数与命名不同）。内容侧按它查三处按品质索引的表：蛋价 `game/data/pets.py:133`、成长加成档 `game/data/pets.py:194`、品质标签 `game/data/pets.py:152-159`。实测 5 档（紫 5 / 绿 3 / 蓝 3 / 橙 3 / 白 2）。⚠ 实测**未知品质有兜底**（查不到按默认档走，`game/data/pets.py:136/212`）→ 拼错不会报错，只会静默降档。", "ref": None},
    "focus": {"zh": "定位词", "note": "内容侧的定位 / 分类词（描述这个品种偏向什么）。⚠ 实测逐键搜索**没有**内容侧读取它的代码（同名 `focus` 的读取点都是引擎 / 面板侧的方法，与本字段无关）→ 展示与分类字段，不驱动数值。实测 5 个取值。", "ref": None},
    "skill_name": {"zh": "技能名", "note": "该品种技能的显示名（内容侧词汇）。实测只被内容侧文案函数 `pet_skill_label`（`game/data/pets.py:175-181`）拼成一行展示（面板 `game/commands/social.py:931`、蛋详情 `game/commands/economy.py:453`）。", "ref": None},
    "skill_interval": {"zh": "触发间隔", "note": "每隔这么多个「时间单位」触发一次技能（整数 ≥ 1）——「时间单位」是内容侧叫法与语义，框架不解释、不换算。⚠ 实测当前**没有按它出手的执行端**：它只被技能描述拼接读（`game/data/pets.py:181`），宠物参战依赖随从装配（新引擎仓全仓 0 处宠物相关标识）。实测只有 2 个档位（3 刻 9 条 / 4 刻 7 条）。", "ref": None},
    "skill_type": {"zh": "技能类型", "note": "内容侧技能类型词 —— 决定这条技能**怎么算**（伤害 / 治疗 / 概率挡一次…）。框架不预设任何类型名，也**不校验**它是否真被内容侧实现过：拼错不报错，只会静默不生效。实测内容侧只在**文案模板**表里按它取描述（`game/data/pets.py:163-172`，8 个 key），数据层之外的代码 0 处读它 → 当前无执行消费者。实测 8 个取值。", "ref": None},
    "skill_value": {"zh": "技能数值", "note": "配合 `skill_type` 的系数（内容侧按百分比显示：`int(value*100)`，`game/data/pets.py:164-171`）。schema **不设上限**：倍率型技能的系数可能 > 1，加上限等于替内容侧做决定。实测 0.08~0.70。", "ref": None},
    "spd": {"zh": "速度", "note": "该品种的速度值（整数 ≥ 1）。⚠ 实测逐键搜索**没有**内容侧读取它的点（代码里读 `spd` 的都是玩家 / 怪的战斗面板属性，与品种本字段无关）→ 数据层保留字段，改它不改变行为。实测 13 个不同取值，30~75。", "ref": None},
    "source": {"zh": "获取渠道", "note": "获取渠道的**说明文本**（自由串，不是引用）。实测面板与蛋详情直接显示（`game/commands/social.py:945`、`game/commands/economy.py:449`）；真实渠道在别处（怪掉落掷蛋 / 垂钓 / 任务奖励）。⚠ 改这段文字**不改变**发放结果。实测 16/16 都有。", "ref": None},
    "desc": {"zh": "描述", "note": "展示文案（蛋详情逐字显示，`game/commands/economy.py:450`）。本域**不强制非空、也不强制存在**（schema 不给 minLength）—— 与物品、特效两域的「必填且非空」口径**不同**。实测 16/16 都有。", "ref": None},
    "lines": {"zh": "随机台词池", "note": "该品种的随机台词池（至少 1 条 —— 空数组是坏数据，要表达「没有台词」请**删字段**）。⚠ 实测取用它的内容侧函数 `pet_line`（`game/data/pets.py:220-227`）全仓**只有定义与 re-export、没有任何调用点** → 数据层保留，接上才生效。实测 16/16 都是 3 条。", "ref": None},
    "egg_roll": {"zh": "蛋掉落规则（派生）", "note": "导出期把内容侧「蛋掉落规则」源表**按品种 id 连接**进条目的派生字段 —— **不是**品种源行自带的字段（同 `equip_roster` 的 series_set / fixed_affixes 做法）。整行原样照搬（含它自己的 `key`；导出期断言 `egg_roll.key` == 表键）。**没有规则的品种不写此字段**：实测 16 条里 10 条有、其余 6 个品种的渠道在内容侧别的系统里 → 缺省 = 不走「打怪掷蛋」这条渠道，与「有一行空规则」是两回事。", "ref": None},
    "rate": {"zh": "掷中概率", "note": "该规则的其它条件**全部**满足后掷中的概率（0~1 的比值）。实测消费端逐行判定并即时掷一次（`game/services/battle_settlement.py:296-317`）。实测 10 行取值 0.015~0.12。", "ref": None},
    "role": {"zh": "限定怪物定位", "note": "只对「怪物定位 == 这个值」的怪生效（内容侧词汇，框架不枚举）。消费端拿怪物的定位逐字比对，不等即跳过本行。**缺字段 = 不限定位**（实测 10 行里只有 1 行写它）。", "ref": None},
    "name_kw": {"zh": "限定怪物名关键词", "note": "怪物**名含其中任一**关键词才生效（内容侧词汇；与同一行的其它条件之间是「与」，数组内部是「或」）。⚠ 这是**按名**的弱引用，指向别处的怪物名册（不是本域的键，框架不解析）。**缺字段 = 不限名字**（实测 3 行写它）。", "ref": None},
    "is_elite": {"zh": "仅精英怪", "note": "true = 只对精英怪生效。消费端逐行判 `is_elite`。**缺字段 = 不判精英**（实测 4 行为 true）。", "ref": None},
    "is_boss": {"zh": "仅首领", "note": "true = 只对首领怪生效。消费端逐行判 `is_boss`。**缺字段 = 不判首领**（实测 3 行为 true）。", "ref": None},
}

# ───────────────────────────────────────────────────────────────────── 怪物名册
# 注脚核实口径（2026-09-13）：① 逐键读本域 schema（`schemas/monster_roster.schema.json` 的 5 个 `$defs`，
# 字段语义与约束以它为准）；② 逐键统计包内 `games/orlandia/content/data/monster_roster.json`（380 条）
# 的字段分布与取值档数（下表脚注里的「实测 N 条 / N 种取值」都是这份数据的真实计数）。
# ⚠ 本域设计口径（写进 lv / lv_rule / lv_variants / spawns 四条）：名册是**投影不是真源**；
#   跨来源冲突**不静默选一个** —— 条目层的 `lv`/`role` 等只是「基准值」，每一处现场在
#   `lv_variants`（等级）与 `spawns`（位置 + 行号）里，规则写在 `lv_rule`。
# 本仓 wiki 没有名册页 → ref 一律 None（不编空链接）。
_MONSTER_ROSTER = {
    # ⚠ 本域 `name` / `desc` 由通用词条（`_COMMON`）覆盖，**不在此重复定义**（重复定义 = 第二份单源）。
    "aliases": {"zh": "跨表别名",
                "note": "同一只怪在**另一张来源表**里用的显示名（与 name_variants 的区别：后者是**同一批来源表内部**的另一种写法）。按名引用解析时与 name 一起查；命中的名字都要能反查回本表键。**没有别名就不写此字段**（实测 380 条里只有 1 条带它）。",
                "ref": None},
    "name_variants": {"zh": "名称异写",
                      "note": "**同一批来源表内部**给这只怪写过的其它显示名（名册按纪律取多数值作 name、其余写法进这里）。只有一个名字时不写此字段（实测只有 1 条带它）。⚠ 按名引用解析要查 **name ∪ aliases ∪ name_variants 三处** —— 只看前两者会漏掉只写在异写里的那个写法。",
                      "ref": None},
    "name_dup": {"zh": "显示名重复",
                 "note": "true = 本条 name 在名册里**还对应别的 id**（按名查不能唯一确定落点）。名册不替内容侧选一条：两个 id 都保留、各自挂 name_peers，让编辑器/审计一眼看出歧义。实测 28 条（= 14 个重名 × 2）。",
                 "ref": None},
    "name_peers": {"zh": "同名兄弟 id",
                   "note": "与本条共用同一个显示名的**其它**怪 id（不含自己）；name_dup=true 时必写。按名引用要消歧时拿它去问内容侧，框架不裁决（实测 28 条、每条 1 个兄弟）。",
                   "ref": None},
    "role": {"zh": "站位 / 职能",
             "note": "站位/职能取值（内容侧词汇，框架不枚举）。同一只怪在不同处被写成不同职能时取**多数值**，其余写法进 role_variants。只有辅助表条目（没有任何摆放记录）的怪允许为 null —— 实测 1 条为 null。",
             "ref": None},
    "role_variants": {"zh": "站位异写",
                      "note": "该怪被写过的其它站位/职能取值。只有一种时不写此字段（实测只有 1 条带它）。⚠ 它们是**证据**不是偏好：多数值只说明来源里写得更多，不代表哪个更好 —— 每一处现场用哪个职能要回源看（名册不逐处对照职能）。",
                      "ref": None},
    "kind_class": {"zh": "类别",
                   "note": "该怪的类别，由内容侧从 id 前缀派生（精英/首领因此成为**显式字段**，不再靠前缀猜）。取值是内容侧词汇，框架不枚举（实测 3 种取值）。",
                   "ref": None},
    "kind_tags": {"zh": "派生标记",
                  "note": "派生标记列表（内容侧词汇，框架不枚举）：例如「只在隐藏怪表里」「只在爪牙槽出现」「只出现在副本里」「只有个体补正条目」。没有可标的东西就**不写此字段**（与空数组表达同一件事）。实测 27 条带它、4 种取值。",
                  "ref": None},
    "skills": {"zh": "技能 id 列表",
               "note": "该怪会用的技能 id 列表（指向技能域的表键；编辑器给真候选）。同一只怪多处摆放且技能不同时取**并集**（只多不少）；空数组是合法的「没有技能」（实测只有 2 条空）。⚠ 并集是「各处记录的合集」，不代表某一只怪在某一处真会用全部 —— 逐处技能**没有**对照字段（本域未实现），要精确到一处得回源看 spawns[].line。",
               "ref": None},
    "drops": {"zh": "掉落物名（显示名）",
              "note": "该怪掉落物的**显示名**列表（内容侧词汇）—— ⚠ 实测是物名不是物品 id，所以编辑器按物品域的 key 给候选会**对不上**（同 monsters.drops 的既有语义）。多处摆放掉落不同时取**并集**（只多不少）；空数组是合法的「不掉东西」。",
              "ref": None},
    "mods": {"zh": "个体属性补正",
             "note": "该怪的个体化补正（倍率 / 机制 / 站位策略 / 说明…**形状由内容侧定，原样内联**）。**不写 = 没有补正条目**（与写一个空对象是两回事）。表单对自由结构走 JSON 兜底，键不会因为渲染而丢。实测 140 条带它，条内 1~22 个子键。",
             "ref": None},
    "lv": {"zh": "基准等级",
           "note": "该怪的**基准**等级（整数 ≥ 1，也允许 null）。⚠ **基准 vs 场景覆盖**：名册是**投影不是真源** —— `lv` 只是「一处摆放值的投影」，**不是**这只怪的唯一/真实等级；同一只怪在不同场景被摆成不同等级是**正常设计**（副本里比野外强），不该被名册抹平。⚠ **跨来源冲突不静默选一个**：每一处现场的等级在 `lv_variants` 里、位置与行号在 `spawns` 里，取哪条的规则写在 `lv_rule`；只有辅助表条目（没有任何摆放记录）才允许为 null（实测 25 条）。",
           "ref": None},
    "lv_rule": {"zh": "基准等级规则",
                "note": "`lv` 是**按哪条规则**取出来的（内容侧词汇，框架不枚举；实测只有 3 种取值：有摆放记录的取野外摆放最小值 / 只有隐藏怪表条目 / 只有个体补正条目）。作用是把「为什么是这个值」写进数据 —— 它说明 `lv` 是**基准值而不是唯一值**。⚠ 基准 vs 场景覆盖：真实逐处等级看 `lv_variants`；推翻规则时只需改这一处常量与 `lv`，`lv_variants`/`spawns` 的证据链不用动。",
                "ref": None},
    "lv_variants": {"zh": "等级对照表",
                    "note": "该怪在各处摆放时的等级**全量对照**（一条 = 某个作用域下的一处摆放，按 `scope` 归并去重）。⚠ 这是「**不静默选一个**」的落地：任何被压成单个基准 `lv` 的事实，都要能在这里查回去；有摆放记录就**必须有**它（实测 355 条 = 全部有摆放记录的怪，合计 792 行）。⚠ 基准 vs 场景覆盖：条目层的 `lv` 给基准、这里给现场覆盖 —— 副本比野外更强（甚至个别比基准更低）都**如实留着**，不是坏数据。",
                    "ref": None},
    "scope": {"zh": "作用域",
              "note": "这处摆放属于哪个场合：**野外**摆放置地图 id、**副本**摆放置副本 id（内容侧词汇）。⚠ **不要用文件行号或文件路径当 scope**（它们随上游编辑漂移）；要定位到具体一处请配合 `spawns[].line`。实测 792 行里 128 行落在副本上。",
              "ref": None},
    "subarea": {"zh": "子区域（房间）",
                "note": "子区域/房间 id（内容侧词汇；与地图域里该图的节点 id 同源）。两处出现：`spawns[]` 里标这处摆放在哪个房间（实测野外摆放绝大多数带它）、`lv_variants[]` 里同一 `scope` 内还要分房间时才有（实测 792 行里 664 行带它）。",
                "ref": None},
    "spawns": {"zh": "摆放证据链",
               "note": "这只怪被摆在哪些地方（一条 = 一处摆放，**保留源文件行号**）。⚠ 基准 vs 场景覆盖：它是「**名册是投影、不是真源**」的**证据链**，也是 `lv_variants` 的出处 —— 等级/职能被压成一个基准值时，每一处现场靠它回查。⚠ **不要为了省体积省掉它**（实测 907 条；一条 = 来源 + 场合 + 槽位 + 行号）。只有辅助表条目的怪可以是空数组（实测 1 条）。",
               "ref": None},
    "source": {"zh": "来源",
               "note": "这条摆放是从哪张**源表**集出来的（内容侧词汇，框架不枚举；实测 6 种取值）。⚠ 它是**导出器**填的出处标记、内容侧源表里没有这个词 —— 改它只影响编辑器分组与审计口径，不影响运行时读到的摆放。",
               "ref": None},
    "slot": {"zh": "槽位",
             "note": "摆在该场景的哪个槽位（内容侧词汇，框架不枚举）：普通怪池 / 精英槽 / 首领槽 / 爪牙槽 / 隐藏…。实测 8 种取值，其中副本层内层的槽位带 `stages[]` 前缀以区分层级（同名字符串不是同一个槽）。",
             "ref": None},
    "map": {"zh": "地图",
            "note": "地图 id（内容侧词汇）——**野外/房间**摆放才有，与 `instance` **互斥**（同一处摆放只属于一种场合）。与 `lv_variants[].scope` 在野外侧同源（那里填的就是地图 id）。实测野外各来源的摆放都带它。",
            "ref": None},
    "instance": {"zh": "副本",
                 "note": "副本 id（内容侧词汇）——**副本**侧摆放才有，与 `map` **互斥**。实测副本来源的 170 处摆放带它。",
                 "ref": None},
    "stage": {"zh": "层名",
              "note": "副本内的层（阶段）名（内容侧词汇）——副本侧摆放且层有名字时才有。⚠ 层名**可能重复**，要唯一定位一层用 `stage_index`。",
              "ref": None},
    "stage_index": {"zh": "层序号",
                    "note": "副本内的层序号（整数 ≥ 0，= 声明序）。层名可能重复、序号**不会** —— 判定「是不是同一层」用它与 `stage` 组合。实测只出现 0/1/2 三个档。",
                    "ref": None},
    "line": {"zh": "源文件行号",
             "note": "该摆放写在源文件的第几行（1 起，实测 19~13189）。⚠ 行号会随上游编辑**漂移** —— 它的用途是「回查那一处」，**不是稳定 id**；也不要拿它当 `scope`。",
             "ref": None},
    "hidden": {"zh": "隐藏怪条目",
               "note": "隐藏怪表里同一 id 的那一条，**原样内联**。⚠ 它的等级是**相对值**（`lv_off` = 所在地图等级 + 偏移），与条目层 `lv` 的绝对语义**不同** —— 所以带隐藏块的条目 `lv` 允许为 null、由 `lv_rule` 说明该怎么读。实测 25 条带它。",
               "ref": None},
    "lv_off": {"zh": "等级偏移（相对值）",
               "note": "⚠ **相对值**：等级 = 所在地图的等级 + 这个偏移（可为负）。这就是带隐藏块条目的 `lv` 只能为 null 的原因 —— 它没有绝对等级可写（实测 25 条取正的小档）。",
               "ref": None},
    "gold_mult": {"zh": "金币倍率",
                  "note": "该隐藏怪的金币产出倍率（内容侧数值语义，框架不解释档位）。实测只出现在隐藏怪条目里（25/25 都带）。",
                  "ref": None},
    "chance": {"zh": "出现概率",
               "note": "每次判定的出现概率（0~1 的比值，schema 上下限为 0 / 1 → 编辑器给滑杆）。实测只出现在隐藏怪条目里（25/25 都带），且都是很低的档。**缺该字段 = 概率语义交给内容侧**（框架不补默认值）。",
               "ref": None},
    "flavor": {"zh": "风味文案",
               "note": "出现时的风味描述（展示长文本 → 编辑器给大输入框）。实测只出现在隐藏怪条目里（25/25 都带）。",
               "ref": None},
    "maps": {"zh": "限定地图",
             "note": "限定只在哪些地图出现的地图 id 列表（编辑器给「一行一条」）。**不写此字段 = 不按地图过滤**（与空数组是两回事，所以**不要写空数组**）。实测 25 条隐藏怪里 19 条带它。",
             "ref": None},
    "elite_equip_drop": {"zh": "精英专属装备",
                         "note": "该怪按名连接到的专属装备 id（内容侧词汇；通常指向装备名册域的表键 → 编辑器给真候选）。它由内容侧「怪名 → 装备 id」表在**导出期按 `name` 连接**而来，**不是**源条目自带的字段；没有该映射的怪**不写此字段**。实测 20 条连接（18 个名字里有 2 个各命中 2 个 id）—— 这是忠于「运行期按名查」的语义：按名查的两个落点都会掉。",
                         "ref": None},
}

GLOSSARY = {
    "*": _COMMON,
    "commands": _COMMANDS,
    "texts": _TEXTS,
    "tlogs": _TLOGS,
    "maps": _MAPS,
    "drop_pools": _DROP_POOLS,
    "instances": _INSTANCES,
    "equip_roster": _EQUIP_ROSTER,
    "pois": _POIS,
    "skills": _SKILLS,
    "monsters": _MONSTERS,
    "affixes": _AFFIXES,
    "items": _ITEMS,
    "effect_rules": _EFFECT_RULES,
    "passive_proc": _PASSIVE_PROC,
    "legendary_effects": _LEGENDARY_EFFECTS,
    "pets": _PETS,
    "monster_roster": _MONSTER_ROSTER,
}

# ───────────────────────────────────────────── 表单分组（字段按语义分块，别平铺 56 个）
# 每条：id / label / icon / fields（**顶层字段名**，嵌套对象的子键在它自己的分组里渲染）。
# 硬规矩（`tests/test_editor_glossary.py` 断言）：
#   ① 顶层字段**一个不漏、一个不重**地分到组里（漏了会露出「其他」组 = 分类没做完）
#   ② 组里列的名字必须真在 schema 里（防拼错）
#   ③ 顺序即界面顺序（把最常改的放前面）
GROUPS = {
    "instances": [
        {"id": "base", "label": "基础", "icon": "📌",
         "fields": ["name", "lv", "icon", "desc"]},
        {"id": "team", "label": "人数", "icon": "👥",
         "fields": ["min_players", "max_players"]},
        {"id": "gate", "label": "入口与钥匙", "icon": "🔑",
         "fields": ["entry", "map", "subarea", "key_item", "key_source"]},
        {"id": "scale", "label": "强度", "icon": "⚔️",
         "fields": ["boss", "hp_mult", "atk_mult"]},
        {"id": "stages", "label": "层与推进", "icon": "🪜",
         "fields": ["stages", "monsters", "elite", "pois", "secret", "npc"]},
        {"id": "reward", "label": "通关奖励", "icon": "🎁",
         "fields": ["gold", "exp", "materials"]},
    ],
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
    "drop_pools": [
        {"id": "base", "label": "池与策略", "icon": "📌",
         "fields": ["type", "desc", "fallback"]},
        {"id": "entries", "label": "条目表（按权重 / 必掉）", "icon": "🎲",
         "fields": ["entries", "item", "w", "n"]},
        {"id": "rolls", "label": "抽行表（多层 / 互斥档）", "icon": "🎯",
         "fields": ["rolls", "pool", "chance", "cutoff", "fallback_n"]},
        {"id": "window", "label": "等级窗口", "icon": "🪜",
         "fields": ["min_lv", "max_lv"]},
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
    # 装备名册：按「先认一件装备（基础）→ 它在哪条系列/从哪来 → 词条 → 特效 → 门槛」的阅读顺序排。
    # 两个「套装」字段特意分在同一组里并排展示（set 是条目自带、series_set 是导出期派生的，最容易被当成同一个东西）。
    "equip_roster": [
        {"id": "base", "label": "基础", "icon": "📌",
         "fields": ["name", "desc", "slot", "weapon_type", "quality", "lv"]},
        {"id": "series", "label": "系列与来源", "icon": "🧵",
         "fields": ["series", "series_set", "set", "source"]},
        {"id": "affix", "label": "固定词条", "icon": "💠",
         "fields": ["fixed_affixes", "affixes", "affix"]},
        {"id": "effect", "label": "专属特效", "icon": "✨",
         "fields": ["special", "legendary", "weapon_effect", "we_data"]},
        {"id": "req", "label": "属性需求", "icon": "🔢",
         "fields": ["req"]},
    ],
    # 交互点：一条 = 一个房间的挂载，所以先给「房间在哪」，再给「挂了什么」，
    # 最后是只在内联对象形态里出现的「点本体」子键；source 单独一组（它是导出器的出处标记，不是玩法字段）。
    "pois": [
        {"id": "loc", "label": "房间位置", "icon": "🗺",
         "fields": ["map", "subarea"]},
        {"id": "mount", "label": "挂载", "icon": "🔎",
         "fields": ["pois"]},
        {"id": "poi", "label": "交互点本体（内联形态）", "icon": "📦",
         "fields": ["id", "type", "name", "hint", "desc", "loot", "effect", "need", "lore"]},
        {"id": "meta", "label": "来源标注", "icon": "🧩",
         "fields": ["source"]},
    ],
    # 传说专属特效：一条 = 一件装备能挂的一个专属特效。阅读顺序「先认这条是什么 → 什么时候触发 → 生效什么」。
    "legendary_effects": [
        {"id": "base", "label": "基础", "icon": "📌",
         "fields": ["name", "kind", "desc"]},
        {"id": "trigger", "label": "触发", "icon": "⚡",
         "fields": ["trigger", "chance"]},
        {"id": "effect", "label": "效果", "icon": "✨",
         "fields": ["effect"]},
    ],
    # 宠物：一条 = 一个品种。先「这是个什么品种」，再「它的技能」，再「打怪掷蛋的派生规则」，
    # 最后单独的台词池（长文案，单独一组便于编辑）。
    # ⚠ rate/role/name_kw/is_elite/is_boss 这 5 个只出现在派生字段 egg_roll 里（门禁的字段路径会走
    #   所有 $defs 的 properties，所以它们必须进组，否则报「未分组」）。
    "pets": [
        {"id": "base", "label": "基础", "icon": "📌",
         "fields": ["key", "name", "icon", "quality", "focus", "desc", "spd", "source"]},
        {"id": "skill", "label": "技能", "icon": "⚔️",
         "fields": ["skill_name", "skill_interval", "skill_type", "skill_value"]},
        {"id": "egg", "label": "蛋掉落规则（派生字段）", "icon": "🥚",
         "fields": ["egg_roll", "rate", "role", "name_kw", "is_elite", "is_boss"]},
        {"id": "flavor", "label": "台词", "icon": "💬",
         "fields": ["lines"]},
    ],
    # 怪物名册：一条 = 一只怪（表键 = 怪 id）。阅读顺序「先认这只怪是谁 → 它怎么打 →
    # 它是几级（基准 + 逐处对照）→ 辅助表那几块（个体补正 / 隐藏怪 / 精英装备）→ 它被摆在哪」。
    # ⚠ 等级那组特意把 lv / lv_rule / lv_variants / scope 并排放：本域最容易被误读的就是
    #   「lv 是基准、场景等级在 lv_variants」（名册是投影不是真源，冲突不静默选一个）。
    # ⚠ `cond` / `tag` / `flavor` 这三个只出现在 hidden 块里、`chance` 也是 —— 它们必须进组，
    #   否则门禁报「未分组」（字段路径会走遍所有 $defs 的 properties）。
    "monster_roster": [
        {"id": "base", "label": "身份", "icon": "📌",
         "fields": ["name", "name_variants", "name_dup", "name_peers", "aliases", "desc"]},
        {"id": "combat", "label": "战斗身份", "icon": "⚔️",
         "fields": ["role", "role_variants", "kind_class", "kind_tags", "skills", "drops"]},
        {"id": "lv", "label": "等级（基准 + 对照）", "icon": "📈",
         "fields": ["lv", "lv_rule", "lv_variants", "scope"]},
        {"id": "aux", "label": "辅助表（个体补正 / 隐藏怪 / 精英装备）", "icon": "🧩",
         "fields": ["mods", "hidden", "elite_equip_drop", "lv_off", "gold_mult", "cond",
                    "chance", "tag", "flavor", "maps"]},
        {"id": "spawn", "label": "摆放证据链", "icon": "📍",
         "fields": ["spawns", "source", "map", "subarea", "instance", "stage",
                    "stage_index", "slot", "line"]},
    ],
}


# ───────────────────────────────────────────────────── 包自带词汇表（真源在包）
# 读法见文件头「包自带词汇表」。**只降级、绝不抛**：坏 JSON / 坏形状 → 当该域没声明 + 一条
# 可读 warning（`glossary_warnings`），其余照用。缺目录 = 没声明（正常，不告警）。
PKG_GLOSSARY_REL = ("editor", "glossary")        # 包内相对路径（**目录**，每域一个文件）
# 控件词表（本层约定）：前端 `web/schema_form.js` 目前实现前 4 种，其余按 schema 类型默认渲染
PKG_WIDGETS = ("textarea", "lines", "pct", "chips", "rows", "kv", "select")
_PKG_REF_BYS = ("key", "name")
_ENTRY_STR_KEYS = ("zh", "note", "group")
_PKG_CACHE: dict = {}                            # 包目录 -> (目录签名, 声明, 告警)
_PKG_CACHE_MAX = 500


def _pkg_key(pkg_dir) -> str:
    return os.path.normpath(os.path.abspath(str(pkg_dir))) if pkg_dir else ""


def pkg_glossary_dir(pkg_dir: str) -> str:
    """`<pkg>/editor/glossary/`（可能不存在 —— 那就是没声明）。"""
    return os.path.join(pkg_dir, *PKG_GLOSSARY_REL)


def _pkg_dir_sig(d: str):
    """目录签名 = (目录, ((文件名, mtime_ns, size), …))。目录不在 → None（= 没声明）。"""
    try:
        entries = sorted(os.scandir(d), key=lambda e: e.name)
    except OSError:
        return None
    out = []
    for e in entries:
        try:
            st = e.stat()
        except OSError:
            continue
        out.append((e.name, st.st_mtime_ns, st.st_size))
    return (d, tuple(out))


def _pkg_json_files(d: str) -> list:
    """目录下的声明文件：`*.json`，且**跳过 `_` / `.` 开头的**（示例 / 临时文件不算声明）。"""
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    return [n for n in names
            if n.endswith(".json") and not n.startswith(("_", "."))
            and os.path.isfile(os.path.join(d, n))]


def _norm_pkg_entry(dom: str, field: str, meta, warns: list, domains: dict):
    """规范化一条包词汇条目 → `{zh, note, widget, group, ref, wiki}`（**坏的部分只丢它自己**）。"""
    where = f"词汇表 {dom}.{field}"
    if not isinstance(meta, dict):
        warns.append(f"{where}：形状不对（需为对象，可含 zh/note/widget/group/ref）"
                     f"（实为 {type(meta).__name__}）—— 该条已忽略")
        return None
    out = {"zh": "", "note": "", "widget": None, "group": None, "ref": None, "wiki": None}
    for k in _ENTRY_STR_KEYS:
        v = meta.get(k)
        if v is None:
            continue
        if isinstance(v, str):
            out[k] = v
        else:
            warns.append(f"{where}：{k} 需为字符串（实为 {v!r}）—— 已忽略该属性")
    w = meta.get("widget")
    if w is not None:
        if isinstance(w, str) and w in PKG_WIDGETS:
            out["widget"] = w
        else:
            warns.append(f"{where}：widget={w!r} 不在控件词表"
                         f"（{' / '.join(PKG_WIDGETS)}）—— 已忽略该属性")
    ref = meta.get("ref")
    if ref is not None:
        if not isinstance(ref, dict) or not isinstance(ref.get("domain"), str) or not ref["domain"]:
            warns.append(f"{where}：ref 需为 {{\"domain\": \"…\", \"by\": \"key|name\"}}"
                         f"（实为 {ref!r}）—— 该引用已忽略")
        else:
            tdom, by = ref["domain"], ref.get("by", "key")
            if by not in _PKG_REF_BYS:
                warns.append(f"{where}：by={by!r} 非法（只能是 key / name）—— 按 key 处理")
                by = "key"
            if tdom not in domains:
                warns.append(f"{where}：ref 的目标域 {tdom!r} 不在该包的有效域表里"
                             " —— 该引用已忽略（仍可选，但不会有下拉与校验）")
            else:
                out["ref"] = {"domain": tdom, "by": by}
    wiki = meta.get("wiki")
    if wiki is not None:
        if (isinstance(wiki, list) and len(wiki) == 2
                and all(isinstance(x, str) and x for x in wiki)):
            out["wiki"] = (wiki[0], wiki[1])
        else:
            warns.append(f"{where}：wiki 需为 [\"页.md\", \"页内词\"]（两个非空字符串，实为 {wiki!r}）"
                         " —— 已忽略该属性")
    if not any((out["zh"], out["note"], out["widget"], out["group"], out["ref"], out["wiki"])):
        return None
    return out


def _norm_pkg_groups(dom: str, groups, warns: list):
    """规范化包的 `groups` → `[{id,label,icon,fields}]`；**整段坏 → None**（该域回退框架 GROUPS）。"""
    if groups is None:
        return None
    if not isinstance(groups, list):
        warns.append(f"词汇表 {dom}.groups：形状不对（需为数组，实为 {type(groups).__name__}）"
                     " —— 该域分组回退框架默认")
        return None
    out, seen, used = [], set(), {}
    for i, g in enumerate(groups):
        where = f"词汇表 {dom}.groups[{i}]"
        if not isinstance(g, dict):
            warns.append(f"{where}：形状不对（需为对象，可含 id/label/icon/fields）—— 该组已忽略")
            continue
        gid = g.get("id")
        if not isinstance(gid, str) or not gid:
            warns.append(f"{where}：缺 id（需为非空字符串）—— 该组已忽略")
            continue
        if gid in seen:
            warns.append(f"{where}：id {gid!r} 与前面的组重复 —— 该组已忽略")
            continue
        fields = g.get("fields")
        if not isinstance(fields, list) or not fields or not all(isinstance(x, str) and x for x in fields):
            warns.append(f"{where}（{gid}）：fields 需为非空字符串数组（实为 {fields!r}）"
                         " —— 该组已忽略")
            continue
        label, icon = g.get("label"), g.get("icon")
        seen.add(gid)
        out.append({"id": gid,
                    "label": label if isinstance(label, str) and label else gid,
                    "icon": icon if isinstance(icon, str) else "",
                    "fields": list(fields)})
        for f in fields:
            used.setdefault(f, []).append(gid)
    if not out:
        warns.append(f"词汇表 {dom}.groups：一组都没收下 —— 该域分组回退框架默认")
        return None
    dup = [f"{f}（{'、'.join(gids)}）" for f, gids in used.items() if len(gids) > 1]
    if dup:
        warns.append(f"词汇表 {dom}.groups：字段同时出现在多个组里：{'；'.join(sorted(dup))}"
                     " —— 分组表原样保留（请自行确认是否手误）")
    return out


def _read_pkg_glossary(pkg_dir: str, domains: dict):
    """真读一次 `<pkg>/editor/glossary/*.json` → ({域: {fields, groups}}, [可读告警])。"""
    d = pkg_glossary_dir(pkg_dir)
    decl: dict = {}
    warns: list = []
    for name in _pkg_json_files(d):
        dom = name[:-5]
        where = f"词汇表 {name}"
        if dom not in domains:
            warns.append(f"{where}：域 {dom!r} 不在该包的有效域表里 —— 该文件已忽略")
            continue
        try:
            with open(os.path.join(d, name), encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            warns.append(f"{where}：读不了（{e}）—— 该域当作没声明（回退框架默认）")
            continue
        except ValueError as e:                                  # 极端坏字节
            warns.append(f"{where}：读不了（{e}）—— 该域当作没声明（回退框架默认）")
            continue
        if not isinstance(raw, dict):
            warns.append(f"{where}：顶层需为对象（可含 fields / groups，实为 "
                         f"{type(raw).__name__}）—— 该域当作没声明（回退框架默认）")
            continue
        table: dict = {}
        fields = raw.get("fields")
        if fields is not None:
            if not isinstance(fields, dict):
                warns.append(f"{where}：fields 需为 {{\"字段\": {{…}}}}（实为 "
                             f"{type(fields).__name__}）—— 该域字段表已忽略")
            else:
                kept = {}
                for field, meta in fields.items():
                    e = _norm_pkg_entry(dom, str(field), meta, warns, domains)
                    if e:
                        kept[str(field)] = e
                if kept:
                    table["fields"] = kept
        groups = _norm_pkg_groups(dom, raw.get("groups"), warns)
        if groups:
            table["groups"] = groups
        if table:
            decl[dom] = table
    return decl, warns


def _pkg_vocab_cached(pkg_dir) -> tuple:
    """`(规范化包词汇表, 告警)` —— 按**目录签名**（文件增删改）失效。"""
    key = _pkg_key(pkg_dir)
    if not key:
        return {}, []
    if len(_PKG_CACHE) > _PKG_CACHE_MAX:
        _PKG_CACHE.clear()
    sig = _pkg_dir_sig(pkg_glossary_dir(key))
    hit = _PKG_CACHE.get(key)
    if hit is not None and hit[0] == sig:
        return hit[1], list(hit[2])
    domains = PK.effective_domains(key)[0]
    decl, warns = _read_pkg_glossary(key, domains)
    _PKG_CACHE[key] = (sig, decl, warns)
    return decl, list(warns)


def _pkg_fields(pkg_dir, dom: str) -> dict:
    """包在该域声明的字段表（未声明 → 空表）。"""
    if not pkg_dir:
        return {}
    return (_pkg_vocab_cached(pkg_dir)[0].get(dom) or {}).get("fields") or {}


def declared_vocab(pkg_dir, dom: str, path: str):
    """**只认包声明**的词汇条目（`fields` 精确路径 → 叶名）→ dict | None。

    框架默认那三份（`GLOSSARY` / `GROUPS` / `WIDGETS`）**不在这里** —— 它们是"默认值"，
    由调用方在包没声明时兜底。
    """
    if not pkg_dir or path is None:
        return None
    try:
        tbl = _pkg_fields(pkg_dir, dom)
    except Exception:                                            # noqa: BLE001 —— 包声明坏 → 当没声明
        return None
    key = str(path)
    e = tbl.get(key) or tbl.get(key.split(".")[-1])
    return dict(e) if e else None


def package_glossary(pkg_dir) -> dict:
    """包自带的词汇表（规范化后，深拷贝）。缺目录 / 全坏 → `{}`。

    形状与声明文件一致：只带**声明过的**那半边（`fields` / `groups`），不凭空补空表。
    """
    decl, _w = _pkg_vocab_cached(pkg_dir)
    out: dict = {}
    for d, t in decl.items():
        item: dict = {}
        if t.get("fields"):
            item["fields"] = {k: dict(v) for k, v in t["fields"].items()}
        if t.get("groups"):
            item["groups"] = [dict(g, fields=list(g.get("fields") or [])) for g in t["groups"]]
        out[d] = item
    return out


def glossary_warnings(pkg_dir) -> list:
    """读包词汇表时的可读告警（空 = 没声明或声明没问题）。**降级不静默**就看它。"""
    return list(_pkg_vocab_cached(pkg_dir)[1])


def groups_for(dom: str, pkg_dir=None) -> list:
    """该域的表单分组（深拷贝，调用方随便改）。

    **两层 = 包声明 > 框架默认**：包给了 `groups` 就是该域的**完整分组表**（整表替换，
    不合并）；包没给（或整段坏）→ 框架 `GROUPS`。不给 `pkg_dir` = 旧行为逐字不变。
    """
    pg = (_pkg_vocab_cached(pkg_dir)[0].get(dom) or {}).get("groups") if pkg_dir else None
    src = pg or GROUPS.get(dom, [])
    return [dict(g, fields=list(g.get("fields") or [])) for g in src]


def all_groups(pkg_dir=None) -> dict:
    """给前端：{域: [{id,label,icon,fields}]}（包声明了分组的域也一并列出）。"""
    out = {d: groups_for(d, pkg_dir) for d in GROUPS}
    if pkg_dir:
        for dom in _pkg_vocab_cached(pkg_dir)[0]:
            if dom not in out:
                g = groups_for(dom, pkg_dir)
                if g:
                    out[dom] = g
    return out


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
    "lore": "textarea",                # 碑文/铭文一类整段长文本（实测有整段碑文的条目）
    # 一行一条的字符串数组
    "exprs": "lines", "maps": "lines", "qualities": "chips",
    "affixes": "lines", "fixed_affixes": "lines",   # 名册装备的固定词条 id 列表（一行一个 id）
    # 0~1 的比值
    "chance": "pct", "mech_chance": "pct", "lifesteal": "pct", "cutoff": "pct",
    "guard_hp_pct": "pct", "heal_pct": "pct", "overload_heal_pct": "pct",
}

# 跨域引用：该字段填的应当是**另一个域的真 key**（编辑器据此给真候选，防拼错）
#
# ★ 第 2 层（2026-09-13）起：这份是**框架默认值（回退）**，不是真源 ——
#   真源是包自己的 `<pkg>/editor/relations.json`（读法见 `editor/relations.py`）。
#   两层规则：**包声明 > 框架默认**；包**没**声明时逐字段等于改造前（零回归）。
#   区别有一条很重要：**只有包声明的 ref 会进引用校验**（`relations.ref_errors`），
#   这份默认值只给「下拉候选」—— 否则既有包的数据会被新校验判红。
REF_DOMAINS = {
    "skills": "skills",        # monsters.skills —— 招式池
    "drops": "items",          # monsters.drops —— 掉落
    "blueprint_for": "items",  # items.blueprint_for —— 图纸产出
    "learn_skill": "skills",   # items.learn_skill —— 使用后学会的技能
    "start_classes": "classes",   # effect_rules.start_classes —— 归属职业
    "buff_key": "effect_rules",   # passive_proc.buff_key —— 效果 key
    "cap_key": "effect_rules",    # passive_proc.cap_key —— 资源上限 key
    "res": "effect_rules",        # passive_proc.res —— 资源 key
    # 装备名册（`equip_roster` 域）：这三个叶名都只指向名册装备 id，且实测只出现在名册相关处
    # （`roster_id` 只在 items、`rid` 在 items.pick_options[]、`boss_equip` 在副本掉落块里）
    "roster_id": "equip_roster",
    "rid": "equip_roster",
    "boss_equip": "equip_roster",
    # 传说专属特效（`legendary_effects` 域）：橙装/词条上的 `legendary` 字段引用的那批特效
    # （实测该字段不是单表引用 —— 有一部分取值不在这 93 条里，那种情况编辑器给不出候选，属正常）
    "legendary": "legendary_effects",
    # 怪物名册（`monster_roster` 域）：这三个叶名**实测只出现在 `instances`**（54 / 27 / 27 处，
    # 值全是怪 id）→ 给真候选；`monster` 故意**不加**（commands 里是 dict、instances.minions 里是
    # 原六元组，不是引用串），`line` 也**不加**（`affixes.line` 是文本、与行号无关）
    "boss": "monster_roster",
    "elite": "monster_roster",
    "monsters": "monster_roster",
    "elite_equip_drop": "equip_roster",
}

# 引擎面板键（**框架协议**，出自 `extends/ext_combat/battle/stats.py:117-122` 的 actor 面板读取）
# —— 给 stat_scale / panel.stat 这类字段做候选；与任何具体游戏无关。
PANEL_KEYS = ["atk", "def", "matk", "mdef", "spd", "crit", "dodge", "max_hp", "max_mp",
              "hp", "mp", "dmg_mult", "reduce"]
_PANEL_PATHS = {"stat_scale", "panel.stat", "debuff_scale", "stat"}


def widget_for(dom: str, path: str, pkg_dir=None) -> str | None:
    """字段该用哪种控件（None = 按 schema 类型默认渲染）。

    **两层 = 包声明 > 框架默认**：包词汇表写了 `widget` 就用它（精确路径 → 叶名），
    否则域内条目（精确 → 叶名），最后 `WIDGETS` 叶名表。不给 `pkg_dir` = 旧行为逐字不变。
    """
    if pkg_dir:
        pv = declared_vocab(pkg_dir, dom, path)
        if pv and pv.get("widget"):
            return pv["widget"]
    e = (GLOSSARY.get(dom) or {}).get(path) or (GLOSSARY.get(dom) or {}).get(str(path).split(".")[-1])
    if e and e.get("widget"):
        return e["widget"]
    leaf = str(path).split(".")[-1]
    return WIDGETS.get(leaf)


_REF_PATH_ONLY = ("start_classes", "mask", "cap_key", "buff_key")   # 只认全路径（叶名太泛，防外溢）


def ref_domain_for(dom: str, path: str) -> str | None:
    """该字段引用哪个域的 key（None = 不是跨域引用）。

    查法：**先全路径**（`REF_DOMAINS` 里可以写 `a.b` 形式的精确路径，用于叶名有歧义的字段），
    再退回叶名。`_REF_PATH_ONLY` 那几个字段只认全路径（例如 `mask` 在别的域里不是引用）。
    """
    p = str(path)
    if p in _REF_PATH_ONLY or p in REF_DOMAINS:
        return REF_DOMAINS.get(p)
    return REF_DOMAINS.get(p.split(".")[-1])


def suggest_meta(dom: str, path: str, pkg_dir=None) -> dict:
    """给前端一条「怎么联想」的说明（前端只管取候选）。

    **两层 = 包声明 > 框架默认**，包侧两处声明的优先级：
      ① `<pkg>/editor/relations.json`（`relations.declared_ref`）→ `ref_source="package"`
         —— 该字段会进**引用校验**（`relations.ref_errors`）；
      ② `<pkg>/editor/glossary/<域>.json` 的条目 `ref` → `ref_source="package_vocab"`
         —— **只给下拉候选**（校验面归 ①，一处声明一处校验，不两处打架）；
      ③ 都没命中 → 框架默认 `REF_DOMAINS`（`ref_source="builtin"`，只给候选、不校验）。
    不给 `pkg_dir` = 旧行为逐字不变。
    """
    key = str(path)
    ref = ref_domain_for(dom, path)
    source = "builtin" if ref else None
    by = "key"
    if pkg_dir:
        try:
            from . import relations as REL          # 同目录模块（不反向 import，无环）
            pr = REL.declared_ref(pkg_dir, dom, key)
        except Exception:                            # noqa: BLE001 —— 包声明坏 → 退回默认
            pr = None
        if pr:
            ref, by, source = pr.get("domain"), pr.get("by", "key"), "package"
        else:
            pv = declared_vocab(pkg_dir, dom, key)
            if pv and pv.get("ref"):
                ref, by, source = pv["ref"]["domain"], pv["ref"].get("by", "key"), "package_vocab"
    return {
        "widget": widget_for(dom, path, pkg_dir),
        "ref": ref,
        "ref_by": by,
        "ref_source": source,
        "panel": key in _PANEL_PATHS,
    }


def all_widgets(pkg_dir=None) -> dict:
    """给前端：{域: {字段: {widget, ref, ref_by, ref_source, panel}}}。

    不给 `pkg_dir` → 只认框架默认（旧行为逐字不变）。给了包目录 → **包声明优先**
    （`<pkg>/editor/relations.json` 与 `<pkg>/editor/glossary/<域>.json` 的字段都进表，
    包自带的新域一并列出）。
    """
    out = {}
    doms = list(DOMAIN_SCHEMA)
    decl: dict = {}
    if pkg_dir:
        try:
            from . import relations as REL
            decl = REL.package_relations(pkg_dir)
        except Exception:                            # noqa: BLE001
            decl = {}
        for d in PK.effective_domains(pkg_dir)[0]:
            if d not in doms:
                doms.append(d)
    for dom in doms:
        tbl = {}
        keys = list(GLOSSARY.get(dom, {})) + sorted(WIDGETS) + sorted(REF_DOMAINS)
        for k in (decl.get(dom) or {}):
            if k not in keys and k != "*":
                keys.append(k)
        for k in _pkg_fields(pkg_dir, dom):           # 包词汇表的字段（含精确路径）也进表
            if k not in keys:
                keys.append(k)
        for key in keys:
            meta = suggest_meta(dom, key, pkg_dir)
            if meta["widget"] or meta["ref"] or meta["panel"]:
                tbl[key] = meta
        out[dom] = tbl
    return out

# 域 → schema 文件：**从 packages.DOMAINS 派生**（别手写第二份 —— 手写的那份会漂：
# 加一个域时忘了同步，词条分组/控件就静默不生效。classes 无 schema → 不在此表）
# ★ 2026-09-23 第 4 批：域声明可以住在扩展包里（域跟消费端走）⇒ 词典口径取
#   `PK.known_domains()`（引擎默认集 + 自带扩展包域），不是 `PK.DOMAINS`（引擎默认集）。
DOMAIN_SCHEMA = {d: m["schema"] for d, m in PK.known_domains().items() if m.get("schema")}

# ───────────────────────────────────────────────────────────────────────── 查询
def lookup(dom: str, path: str, pkg_dir=None):
    """单字段词典条目。依次回退：**包词汇表**（精确 → 叶名）→ 域内精确 → 通用（叶名）。

    包词汇表命中的条目带 `source="package"`（前端/调用方据此能看出这条是谁说的）；
    框架侧命中不带 `source`（= 旧行为逐字不变）。不给 `pkg_dir` = 只认框架那份。
    """
    if not path:
        return None
    key0 = str(path)
    leaf = key0.split(".")[-1]
    if pkg_dir:
        try:
            tbl = _pkg_fields(pkg_dir, dom)
        except Exception:                                        # noqa: BLE001 —— 包声明坏 → 当没声明
            tbl = {}
        for k in (key0, leaf):
            e = tbl.get(k)
            if e:
                return dict(e, dom=dom, path=path, matched=k, source="package",
                            wiki=ref_url(e, pkg_dir))
    for key in (key0, leaf):
        e = (GLOSSARY.get(dom) or {}).get(key)
        if e:
            return dict(e, dom=dom, path=path, matched=key)
    e = GLOSSARY["*"].get(leaf)
    if e:
        return dict(e, dom=dom, path=path, matched=leaf, generic=True)
    return None


def all_entries(pkg_dir=None) -> dict:
    """给前端：域 → {字段: {zh, note, wiki}}（只发用得到的字段）。

    **两层 = 包声明 > 框架默认**：包词汇表的条目**整条覆盖**同名字段（不做字段级合并），
    包自带的新域一并列出。不给 `pkg_dir` = 旧行为逐字不变。
    """
    out = {"*": {}}
    for dom, table in GLOSSARY.items():
        out[dom] = {}
        for k, v in table.items():
            out[dom][k] = {
                "zh": v.get("zh", ""),
                "note": v.get("note", ""),
                "wiki": ref_url(v, pkg_dir),
            }
    if pkg_dir:
        try:
            decl = _pkg_vocab_cached(pkg_dir)[0]
        except Exception:                                        # noqa: BLE001
            decl = {}
        for dom, t in decl.items():
            tbl = out.setdefault(dom, {})
            for k, v in (t.get("fields") or {}).items():
                tbl[k] = {"zh": v.get("zh", ""), "note": v.get("note", ""),
                          "wiki": ref_url(v, pkg_dir)}
    return out


def ref_url(entry: dict | None, pkg_dir=None):
    """词典条目 → 编辑器内 wiki 深链（`wiki:<page>#find=<词>`）。无来源 = None。

    两处出处都认：条目的 `wiki`（**包词汇表**的显式文档出处 `["页.md", "页内词"]`）优先，
    否则 `ref`（框架词典沿用的 `(页, 词)` 元组）。⚠ 包词汇表条目里的 `ref` 是**跨域引用**
    （`{"domain": …, "by": …}`）—— 它不是文档出处，这里**返回 None**，不编一个像样的链接。

    给了 `pkg_dir` → 出链前先按「**包内页优先 → 框架页兜底**」核一次这页在不在；
    两边都没有 = 那个词条没有可打开的文档 → 返回 None（**不编链接**）。
    不给包 = 旧行为逐字不变（只做形状校验，不查文件是否存在）。
    """
    src = (entry or {}).get("wiki")
    ref = src if isinstance(src, (list, tuple)) else (entry or {}).get("ref")
    if not (isinstance(ref, (list, tuple)) and len(ref) == 2
            and all(isinstance(x, str) and x for x in ref)):
        return None
    page, term = ref
    if pkg_dir and not WK.page_path(page, pkg_dir):
        return None
    return f"wiki:{page}#find={term}"


def wiki_path(page: str, pkg_dir=None) -> str:
    """页名 → 文件路径：**包内 `docs/wiki` 优先 → 框架 `docs/engine-wiki` 兜底**。

    不给包 = 旧行为逐字不变（框架那份，**不做存在性检查** —— 调用方自己 `os.path.isfile`）。
    给了包：包内那份存在就用它；包内没有回退框架那份；两边都没有 → 仍返回框架路径
    （与旧口径一致：由调用方判定，**不抛**）。
    """
    if pkg_dir:
        p = WK.page_path(page, pkg_dir)
        if p:
            return p
    return os.path.join(WIKI_DIR, *page.split("/"))


# ───────────────────────────────────────────────────────── 报错 → 中文（带字段名）

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


def friendly(dom: str, errors, pkg_dir=None) -> list:
    """把 schema 原始报错翻成「字段中文名 + 可读原因」。

    输入两种形态都吃：
      - `["desc: '' should be non-empty"]`（编辑器 validate 的输出）
      - `[{"path": "desc", "message": "..."}]`

    给了 `pkg_dir` 时字段中文名/注脚**先取包词汇表**（包给游戏词汇起了名字就用包的名字）；
    不给 = 只认框架词典（旧行为逐字不变）。
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
        ent = lookup(dom, path, pkg_dir) if path else None
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


def missing_required(dom: str, data: dict, schema_def: dict, pkg_dir=None) -> list:
    """必填项体检（**只判 schema.required + 空值**，不猜业务规则）。

    给了 `pkg_dir` 时字段中文名/注脚取包词汇表（同 `friendly`）；不给 = 旧行为逐字不变。
    """
    data = data or {}
    out = []
    for k in (schema_def or {}).get("required", []) or []:
        v = data.get(k, None)
        bad = (k not in data) or v is None or (isinstance(v, str) and v.strip() == "")
        if bad:
            ent = lookup(dom, k, pkg_dir) or {}
            out.append({"path": k, "label": ent.get("zh") or "",
                        "note": ent.get("note") or "", "wiki": ent.get("wiki"),
                        "display": f"{k}（{ent.get('zh')}）" if ent.get("zh") else k})
    return out
