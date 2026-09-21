# 指南：加一个被动 proc

「被动 proc」= 一个**被动技能**（`kind="被动"` + `passive.proc`）声明它监听哪个事件、
跑哪个动作、判据是什么。装配器开战时读它，翻译成 `actor["triggers"]`。

**这整套是内容侧约定，不是引擎 API**。引擎只提供 `register_action` 与 `triggers`；
`PASSIVE_PROC` 表 + 装配器都在内容侧（`game/data/battle_rules.py:653` 的表、
`game/services/class_mech_proc.py:1974` 的 `apply_class_passives`）。
本页两个都讲，因为第三方最省力的做法就是照抄这套格式。

> 本页例子里的被动/技能（坚城之姿、战意、淬毒之心、反击之王…）都来自**游戏仓侧的参考实现《奥兰迪亚》**，
> 不是引擎自带 —— 引擎不认识任何具体技能。

## 四张表的一句话区别

| 表 | 触发源 | 例子 |
|---|---|---|
| `PASSIVE_PROC` | **被动技能**（`passive.proc`） | 「战意满 10 → 减伤 +10%」 |
| `MECH_CASH` | **主动技能**（`mech` 字段） | 「终结技：每层连段 +10% 伤害并清层」 |
| `EFFECT_ACTIONS` | 技能 `effect` 字段 / `triggers` 里的名词 | 「`atk_up` = 攻击 ×1.30」 |
| `EFFECT_RULES` | 任何 `effects` key | 「`burn` 每层每刻掉 3% 生命」 |

## 声明 schema

一条真实的**双通道**被动（`game/data/battle_rules.py:738-744`）：

```python
"zhan_yi_full_reduce": {   # 坚城之姿：战意满 10 → 减伤 +10%、免疫眩晕
    "event": "taken_calc", "action": "passive_taken_reduce",
    "judge": {"kind": "res_ge", "res": "zhan_yi", "ge_field": "stacks"},
    "also": [{"event": "turn_start", "action": "passive_cc_clear",
              "judge": {"kind": "res_ge", "res": "zhan_yi", "ge_field": "stacks"},
              "ctrl": "stun"}],
},
```

| 字段 | 必填 | 语义 |
|---|---|---|
| `event` | ✅（除非 `domain`） | 挂到哪个事件（必须已在 `EVENTS` 里，否则永不触发） |
| `action` | ✅（除非 `domain`） | 跑哪个**已注册动词**（`register_action` 的名字，**不经名词翻译**，见下） |
| `judge` | ✖ | 判据模板，原样透传进 `triggers` 条目 → 动作里 `params["judge"]` |
| `also` | ✖ | 同一被动的**第二条事件钩子**（列表，见下） |
| `agg` | ✖ | **聚合族**名（多条被动合成一条终值，见下） |
| `domain` | ✖ | **静态域**：不进 `triggers`，直接写 `actor.bonus`（见下） |
| 其余键 | ✖ | 除 `event/action/judge/agg/domain/cap_key/when/add/also` 外，**全部并入条目**传给动作（如 `ctrl` / `res` / `buff_key` / `left_key`） |

数值参数从**技能数据的 `passive` dict** 来（同一条声明服务多个技能）：
`mult` / `dmg_add` / `per_layer` / `layers` / `chance` / `add` / `cost` / `lose` …
合并规则见 `class_mech_proc.py:2043-2047`：`passive` dict 的键全部并入条目，
`label` 缺省取技能名。

## `also`：一条声明挂两个事件

`also` 的语义（`class_mech_proc.py:2075-2090`）：**复制主条目的参数**，
用 `also` 的 `action` / `judge` / `event` 覆盖，并额外接受一小撮专用键：

```
ctrl · ctrl_any · res · left_key · left_init · cost_field · buff_key
```

⚠️ 这个白名单是**硬编码的**。你在 `also` 里写别的键（比如 `spd_pct`），
不会报错也**不会生效**。要传别的参数，把它写进 `passive` dict（技能数据）里，
它会进主条目并被复制过去。

## 判别 1：`agg` 聚合族

场景：「以守为攻」35% 反击 80% 伤害 + 「反击之王」概率 +25%、伤害 +50%。
两条被动要的是**一个终值**，不是两次独立 roll。

```python
"agg": "counter"        # 两条声明都写 "counter"
```

装配器把它们暂存到 `_pending[(event, agg)]`，循环结束后调 `_merge_agg_entry` 归并成
**一条**（`class_mech_proc.py:2096-2100`）。归并算法是族特定的（`_merge_agg_entry`，
`class_mech_proc.py:2164-2198`）：

| proc | 归并规则 |
|---|---|
| `counter_chance` | `chance = max(...)`、`mult = min(...)`（取最强的一条做基准） |
| `counter_up` | `chance += chance_add`、`mult *= (1 + dmg_add)`（增强叠加） |

终值 = `{"type": "passive_counter", "chance": min(chance, 0.9), "atk_pct": mult, "label": "A+B"}`。

⚠️ **`agg` 是族特定的**：`_merge_agg_entry` 只实现了 `counter`，返回 `None` 会**丢弃整族**
（`class_mech_proc.py:2198`）。目前 42 条 `PASSIVE_PROC` 里只有 2 条用 `agg`。
要加新聚合族得同时写归并函数。

## 判别 2：`domain` 静态域

不是所有被动都「触发」，有些只是**静态修正**。这类声明没有 `event`，
装配器直接写 `actor["bonus"]`：

```python
"poison_cap": {          # 淬毒之心：毒层上限 +3
    "domain": "cap", "cap_key": "poison",
},
"arcane_constant": {     # 奥术恒常：奥术技能耗蓝 −50%
    "domain": "cost",
    "when": [{"judge": {"mech_prefix": ["arcane"]}}],
},
```

| `domain` | 写哪里 | 引擎消费者 | 数值来源 |
|---|---|---|---|
| `cap` | `actor["bonus"]["cap"][cap_key] += add` | `effects._cap_of`（`effects.py:72`） | `passive.add` 或 `cfg.add`，**只累加正数** |
| `cost` | `actor["bonus"]["cost"]`（`mp_pct` / `when[].mp_pct`） | `actions._skill_pay_of`（`actions.py:272`） | `passive.mp_mult`（如 0.5 = 打五折） |

`cap` 域**不 continue**：声明里同时有 `event` 时（如 `soul_mark_cap` / `poison_cap_up`）
会继续走事件装配（原文注释「双通道声明 → 不 continue，fall through」，
`class_mech_proc.py:2019`）。`cost` 域没有 `event` → 下方 `d.type` 为空自然跳过
（`class_mech_proc.py:2034`）。

## 判别 3：`left_key` / `left_init` 计数器

「每场 3 次」这类有次数上限的被动：

```python
"tenacity": {            # 坚韧：被控制时消耗 2 层战意跳过（每场 3 次）
    "event": "turn_start", "action": "passive_cc_break",
    "ctrl_any": True, "res": "zhan_yi", "cost_field": "cost",
    "left_key": "tenacity_break_left", "left_init": 3,
},
```

装配时初始化计数器：`actor["effects"]["tenacity_break_left"] = {"stacks": 3, "expire": None}`
（`class_mech_proc.py:2091-2095`）。动作自己扣它。`expire: None` = 永久（整场不清）。

## 事件选型决策表

「我的被动该挂哪个事件？」——按你要判的东西选：

| 我想... | 用 | 为什么 |
|---|---|---|
| 影响**我打出的伤害**（增伤/处决/破魔） | `dmg_calc` | 攻击方视角乘区，`actions.py:422` |
| 影响**我受到的伤害**（减伤/护盾转化） | `taken_calc` | 承伤方视角乘区，`landing.py:79` |
| 影响**我造成的治疗**（治疗增幅） | `heal_calc` | 施法者视角乘区，`actions.py:651` |
| 影响**DOT 每跳伤害** | `dot_calc` | 广播事件（无 subject），用 `ctx["dot_key"]` 过滤 |
| 命中后做事（叠层/挂条/上控制） | `skill_hit` / `attack_hit` | 主体=攻击者；普攻走 `attack_hit` |
| 受击后自我强化/反击 | `on_taken` | 主体=受击者，`ctx["source"]` = 攻击者 |
| 每次施放前（条件暴击/挂印/吸血面板） | `act_cast` | 扣费与冷却之后、结算之前，`actions.py:105` |
| 回合开始（免控/回资源） | `turn_start` | **早于**控制消费，所以「清除控制」等效免疫 |
| 死亡时（复活/遗言） | `on_death` | 死者**自己的**声明会执行（subject 例外） |
| 击杀时（回能/溅射） | `on_kill` | 主体=击杀者；DOT/环境杀无此事件 |
| 每刻时钟（持续衰减/半衰） | `time_advance` | ctx 带 `dt` / `now` |
| 一次性出手消费 | （不用被动）→ `effects[key]["hit"]` | 见 [../concepts/effects.md](../concepts/effects.md) |

**没有点位的事件**：`phase` / `player_low` / `pv_broken` —— 挂上去不会触发，
除非你的上层自己 `fire`。做「血量 <30%」这类被动时，内容侧的实际做法是挂在
`on_taken` 上每次自己判血量（例：`core_last_stand`，`game/data/battle_rules.py:852-858`，
注释直写「引擎无低血量事件 player_low，缺口见动作 docstring」）。

## 完整可抄模板

```python
# ① 内容侧声明（game/data/battle_rules.py）
PASSIVE_PROC["my_proc"] = {
    "event": "dmg_calc", "action": "passive_dmg_mult",
    "judge": {"kind": "res_ge", "res": "my_res", "ge_field": "stacks"},
}

# ② 内容侧动作（game/services/my_procs.py）——若已有动作族可复用
from saintess_engine.effects import register_action

@register_action("passive_dmg_mult")   # 已存在则不要重复注册
def _reuse_existing(): ...

# ③ 技能数据：被动技能 + passive dict
#    真实样例（game/data/skills.py:1123，狂热 zhan_yi_crit）：
#    'passive': {"proc": "zhan_yi_crit", "stacks": 8, "add": 0.15}
#    即：proc 选声明、stacks 是阈值（对应 judge.ge_field="stacks"）、add 是数值
#    本模板对应写成：'passive': {"proc": "my_proc", "stacks": 8, "mult": 0.15}

# ④ 开战装配
from game.content_rules.apply import apply_game_content
apply_game_content(actor)              # ← 内容侧单一入口（游戏仓侧 S7 步）：内含 apply_class_mech 等全部步骤
```

> ⚠️ 参考实现里 `apply_game_content`（`game/content_rules/apply.py:100`）是
> **唯一**开战装配入口，顺序契约写死在里面（① 引擎配置 → ② 装备词条 → ③ `apply_class_mech`
> → ④ 挂敌身条 → ⑤ 条件乘区 → ⑥ 食物），并用 actor 顶部标记 `_content_applied` 保证幂等。
> **自己写时不要绕过它单点调 `apply_class_mech`** —— 顺序错了会静默不生效
> （例：装备的 `bonus` 分域必须先于职业渠道装配）。
> 顺序契约详见 [../architecture/boundaries.md](../architecture/boundaries.md)。

`mult: 0.15` + `stacks: 8` 的含义完全由 `passive_dmg_mult` 决定：
在 `res_ge` 命中时 `ctx["mult"] *= (1 + 0.15)`（`class_mech_proc.py:817`），
阈值从 `params["stacks"]` 读（`_res_ge_ok` 读的是 `params[ge_field]`，`ge_field="stacks"`）。

## 三个高频坑

1. **动作名 vs 名词**：`triggers` 里的 `type` 字段是**动词名**（`action`），
   **不经 `EFFECT_ACTIONS` 翻译**（`effects.py:198-202`）。写名词会静默 no-op。
2. **未知 judge kind = fail-closed**：`passive_taken_reduce` 对未知 kind 直接 `return`
   （`class_mech_proc.py:1001-1002`）。加新 kind 必须同时改动作。
3. **表未声明的 proc = 静默跳过**：`cfg` 找不到就 `continue`（`class_mech_proc.py:2004-2006`），
   原文「记缺口跳过（不硬做）」。技能写了 `proc` 但表里没有 → 被动不存在，无任何提示。

## 相关

- judge 谓词全清单 → [../reference/judges.md](../reference/judges.md)
- `PASSIVE_PROC` 逐字段 schema → [../reference/passive-proc.md](../reference/passive-proc.md)
- 事件时机与 ctx → [../reference/events.md](../reference/events.md)
