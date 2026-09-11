# 声明表驱动

## 一句话

引擎里没有「火球术」这三个字，也没有「眩晕 2 刻」。**引擎认识的是动作与规则**；
「火球术 = 造成 150% 魔攻伤害 + 挂 3 层燃烧」这句话写在**表**里，由你的内容层维护。

一共四张表，各管一件事：

| 表 | 回答的问题 | 消费者（引擎侧） |
|---|---|---|
| `EFFECT_ACTIONS` | 这个**名词**对应哪些**动词**？ | `effects.resolve_actions`（`effects.py:107`） |
| `EFFECT_RULES` | 这个 **key** 的行为规则是什么（上限/折算/周期/净化/控制模式）？ | `state_effects.state_def`（`state_effects.py:13`）→ 引擎各处 |
| `MECH_CASH` | 这个技能的 **mech** 怎么兑现（花几层换多少伤害、清不清层）？ | **内容侧装配器**（`game/services/class_mech_proc.py:2201` `apply_class_mech`） |
| `PASSIVE_PROC` | 这个**被动**挂在哪个事件、跑哪个动作、判据是什么？ | **内容侧装配器**（同上，`apply_class_passives`） |

后两张表**不在引擎里**——它们是「内容侧装配约定」。区别很重要，见文末。

## 为什么要声明而不是写代码

旧引擎的做法是：`if effect == "shield_self": ... elif effect == "taunt": ...`。
后果：

1. **加一个效果 = 改引擎**（`actions.py` / `effects.py` 反复变胖，11000 行的由来）
2. **改一个数值 = 改引擎**（`BUFF_MULT["atk_up"] = 1.30` 藏在引擎常量里）
3. **测试面爆炸**：引擎每次改动都要回归全部机制

声明化的收益（引擎 `effects.py:4-8` 原文：「换一套配置 = 新游戏」）：

- **引擎代码零改动**就换游戏：调数值、加状态、改规则全在表里
- **一个动作服务多个名词**：`apply` 一个动词覆盖了「叠层资源 / 面板增益 / 控制 /
  一次性出手 buff / 纯状态标记」五种形态（判据在参数，不在名词）
- **可审计**：一张表能 diff、能生成文档、能被脚本校验（**游戏仓侧**确有这类脚本，
  如 `scripts/audit_v153.py`）

## 三级翻译链

```
技能数据 / 怪物模板            actor["triggers"]              引擎
   "effect": "reduce"   ─┐
                         ├─→ EFFECT_ACTIONS ──→ [{action, ...}] ──→ 动词执行器
   "mech": "burn"      ─┘        (名词→动词)                        (apply/...)
                                                                      │
                          EFFECT_RULES[key] ──── 行为规则（cap/period/consume）┘
```

举一条**真实条目**（`game/data/battle_rules.py:488`）：

```python
# 减伤（value 型 buff：mech_val 折算百分比 45→0.45）
"reduce":    [{"action": "apply", "key": "reduce", "pct_from_mech_val": True}],
```

对应的规则声明（`game/data/battle_rules.py:408`）：

```python
# reduce：value 型减伤（effects[key].v）；净化遍历查表清（原 CLEANSE_TAGS 含 reduce）
"reduce":   {"cap": 1, "cleanse": True, "negative": True},
```

链路读法：

1. 技能数据里写 `"effect": "reduce"`，`mech_val: 45`
2. `EFFECT_ACTIONS["reduce"]` 把它翻成 `apply` 动词，参数带 `pct_from_mech_val=True`
3. `apply` 查 `EFFECT_RULES["reduce"]` → `cap=1`、`cleanse=True`
4. `pct_from_mech_val` 把 `mech_val=45` 折成 0.45，写进 `actor.effects["reduce"]["v"]`
5. 净化时 `act_cleanse` 遍历查表，`cleanse=True` 命中 → 清除

**全程没有一个 if 分支带 "reduce" 字样。**

## 判据在参数：`apply` 的五种形态

这是理解声明系统最关键的一节。`act_apply`（`effects.py:269`）按**参数**分流：

```
params 里有什么                         →  写出的条目形态
──────────────────────────────────────────────────────────────
mode（来自动作参数，或 EFFECT_RULES[key].consume.mode）
                                     →  {expire, mode, stacks:1}      控制型
op="add" 且无 stat                    →  {stacks: += amount}          叠层加
op="set" 且无 stat                    →  {stacks: = amount}           叠层置
value 或 pct_from_mech_val            →  {stacks:1, expire, v}        值型
stat + mult（参数或 EFFECT_RULES[key].panel）
                                     →  {stacks:1, expire, stat, op, mult}  面板快照
hit（dict）                           →  {stacks:1, expire, hit}      出手消费
以上都没有                             →  {stacks:1, expire}           纯状态
```

（`effects.py:290-401`，逐支的注释与日志文案都在那一段）

`op="add"` 与 `op="mul"` 的区别是**有没有 `stat`**：面板增益的 `op` 是面板算子且必带
`stat`，所以走快照分支（`effects.py:320-323` 注释）。

## `EFFECT_RULES`：任何 key 都可以有规则，也可以没有

`state_def(key)`（`state_effects.py:13`）在无声明时返回 `{}`，即**纯数值无规则**。
这是特性不是缺陷：「我有一个叫 `custom_mark` 的标记，它只是存在」这种情况不需要声明。

有声明时，各字段的消费者（完整 schema 见 [../reference/effect-rules.md](../reference/effect-rules.md)）：

| 字段 | 谁读它 |
|---|---|
| `cap` | `effects._cap_of`（`effects.py:58`）← 叠层 clamp 的**唯一收敛点** |
| `stat_scale` | `stats._apply_effects`（`stats.py:61`）面板折算 |
| `debuff_scale` | ⚠️ **无消费者**（全仓 grep 只在 `effects._is_stack_resource` 的判据关键词里出现，`effects.py:249`）。声明了「每层承伤 +N%」的 `hunt_mark`/`soul_mark`/`curse` 实际**不生效**；真正生效的承伤乘区是 `target["_dmg_taken_mult"]`（`landing.py:86-91`，由上层直写） |
| `panel` | `effects.act_apply` 快照分支（`effects.py:376-388`） |
| `consume.mode` | `effects.act_apply` 控制分支（`effects.py:293-296`）+ `Battle.act` 的控制消费（`battle.py:423-446`） |
| `period` | `schedule._settle_time_effects`（`schedule.py:239-247`） |
| `cleanse` / `period` / `on=="target"` | `effects.act_cleanse`（`effects.py:496-500`） |
| `cd_mult` | `actions.do_skill` 冷却设置（`actions.py:89-97`，取多态最小） |
| `negative` | **内容侧**负面种数计数（`class_mech_proc.py:767`），引擎不读 |

## `MECH_CASH` / `PASSIVE_PROC`：内容侧约定，不是引擎 API

这两张表在 `game/data/battle_rules.py`，但**引擎没有任何代码读它们**。
读它们的是一个**内容侧装配器** `game/services/class_mech_proc.py`：

```python
# 引擎侧只提供能力：register_action + actor["triggers"]
# 内容侧装配器把表翻译成 triggers（开战前调一次）
trig.setdefault("dmg_calc", []).append(
    {"action": "mech_cash_dmg_mult", "mech": mech, "key": key,
     "per_layer": _per, "label": ...})
```
（`class_mech_proc.py:2359-2367`）

**为什么值得单独知道**：这意味着第三方可以**不采用**这两张表——
你完全可以写自己的装配器把「技能 → triggers」翻译出来，只要最终产出的是
`{"action": <你注册的动词>, ...judge/参数}` 这种形态。这两张表的价值是
**「一个可直接照抄的约定」**：字段名、mode 语义、judge 谓词族都已定好，
照抄就省掉自己设计装配格式的成本。

## 一处不对称：技能级名词 vs 事件级名词

| 路径 | 谁翻译 | 什么时候 |
|---|---|---|
| 技能 `effect` 字段 / `mech` 字段 | `apply_effects`（`effects.py:137`） | 命中后 / 施放时 |
| `actor["triggers"][事件]` 里的 dict | 同上（`fire` → `apply_effects`） | 事件点位 |
| `triggers` 里的 dict 的 `action` 字段 | **跳过名词翻译**，直通 `ACTIONS_HANDLERS` | 同上 |

第三条是内容侧扩展动作的入口：`{"action": "passive_dmg_mult", ...}` 不会去查
`EFFECT_ACTIONS`（`effects.py:169-173`：`act_name = act.get("action") or etype`，
然后直接取 handler）。所以「事件挂点」写的是**动词名**，「技能数据」写的是**名词名**。

## 相关

- 效果条目形态与 `apply` 五形态 → [effects.md](effects.md)
- 四张表的字段级 schema → [../reference/effect-actions.md](../reference/effect-actions.md) ·
  [../reference/effect-rules.md](../reference/effect-rules.md) ·
  [../reference/mech-cash.md](../reference/mech-cash.md) ·
  [../reference/passive-proc.md](../reference/passive-proc.md)
- 为什么不写在引擎里（边界） → [../architecture/boundaries.md](../architecture/boundaries.md)
