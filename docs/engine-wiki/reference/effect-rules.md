# 参考：`EFFECT_RULES` 字段 schema

> **归属**：本能力**不在引擎里**（2026-09-23 起）—— 它是扩展包 `extends/ext_combat/` 的域 `effect_rules`（**域声明**在 `extends/ext_combat/domains.json`）。
> 数据包要用它：`game.json` 里写 `"depends": ["ext_combat"]`。
> 引擎侧只剩通用件（`config` / `domains` 等），见 `../architecture/boundaries.md`；下文裸文件名（`effects.py` / `stats.py` / `landing.py` / `schedule.py` / `actions.py` / `state_effects.py`）与行号都在 `extends/ext_combat/battle/` 下。

`EFFECT_RULES` = 「效果 key → 行为规则」的表。它**不是引擎文件**，是你注入的内容表；
扩展包通过 `config.set_config("effect_rules", ...)` / `load_game_rules(module)` 读它，
读点在 `state_effects.state_def`（`extends/ext_combat/battle/state_effects.py:13`）。

**无条目 = 空 dict = 纯数值无规则**（`config.state_def`，`config.py:146-152`）——
这是合法状态，不是错误。

字段清单来自游戏仓参考实现（`game/data/battle_rules.py`，78 个 key）的**实际使用并集**，
加上扩展包代码里被读取的字段。每个字段都标了消费者：

- ✅ = 扩展包 `ext_combat` 消费
- ⚠️ = **当前无消费者**（声明了也不生效）

## 顶层字段

| 字段 | 类型 | 消费者 | 语义 |
|---|---|---|---|
| `cap` | int | ✅ `effects._cap_of`（`effects.py:59-76`） | 叠层上限基数。**收敛点唯一**：`apply op=add/set`、`schedule` gain、内容侧渠道攒取都走它。缺声明（0）→ **999999（不设限）** |
| `name` | str | ⚠️ 包不读 | 展示名。内容侧做日志/UI 标签（`class_mech_proc.py:1895`） |
| `stat_scale` | `{stat: 每层系数}` | ✅ `stats._apply_effects`（`stats.py:60-67`） | 每层面板修正。`st[stat] *= (1 + n×系数)`；特殊 stat：`dmg_mult`（写 `st["_state_dmg_mult"]`，伤害乘区读它）、`reduce`（写 `st["reduce"]`，⚠️ 见「已知死字段」） |
| `debuff_scale` | `{stat: 每层系数}` | ✅ **`ext_combat` 消费**（2026-09-11） | `landing.deal_damage` 遍历持有者状态：Σ(系数 × stacks) → 伤害 ×(1+Σ)。与 `stat_scale` 对称；层数上限由数据侧 `cap` 给。另仍是 `effects._is_stack_resource` 的判据关键词（`effects.py:278`，分派用） |
| `panel` | `{"stat","op","mult"}` | ✅ `effects.act_apply` 快照分支（`effects.py:459-471`） | 静态面板增益的默认值（动作参数缺省时查表）。`op`：`mul`（乘）/ `add`（加）；`op="reduce"` 特殊（见 `stats.py:75-76`） |
| `consume` | `{"mode": ...}` | ✅ `effects.act_apply`（`effects.py:351-354`）+ `Battle.act`（`battle.py:464-491`） | 控制型条目的消费模式：`"skip"`（整跳行动）/ `"no_skill"`（技能转普攻） |
| `period` | dict | ✅ `schedule._settle_time_effects`（`schedule.py:475-483`） | 周期结算声明（见下） |
| `cleanse` | bool | ✅ `effects.act_cleanse`（`effects.py:619`） | `True` = 可被净化 |
| `on` | `"caster"` \| `"target"` | ✅ `effects.act_cleanse`（`effects.py:619`，`on=="target"` 也清）；内容侧 `_mech_to_effect` 判 `on_target`（`effects.py:248`） | 效果的默认作用对象。`"target"` = 对敌标记类 |
| `negative` | bool | ⚠️ 包不读 | 「负面」标记。内容侧用它数「负面种数」（`class_mech_proc.py:767`，`target_debuff_kinds` judge） |
| `tag` | str | ⚠️ 包不读 | 旧 CLEANSE_TAGS 时代的标记。`act_apply` 读的是 **params** 的 `tag`（作为 `key` 的兜底，`effects.py:345`），不是 `cfg["tag"]` |
| `cd_mult` | float | ✅ `actions.do_skill`（`actions.py:90-98`） | 冷却倍率（`0.8` = CD −20%）。多态并存时**取最小**（最速） |
| `on_threshold` | `{层数: {...}}` | ⚠️ **无消费者** | 「满 N 层触发什么」。`threshold` **事件**有引擎点位（`effects.py:442`），但**这张映射表没被读**。目前要靠内容侧监听 `threshold` 自己实现 |
| `guard_hp_pct` | float | ✅ `landing._apply_death_guard`（`landing.py:329`） | 濒死保护触发后保底到的最大生命比例（缺省 0.10） |
| `heal_pct` | float | ✅ 同上（`landing.py:332`） | 濒死保护触发时额外回复的最大生命比例 |
| `wake_on_hit` | bool | ✅ **`ext_combat` 消费**（2026-09-11） | `landing.deal_damage:167-179`：承伤时遍历持有者状态，带该字段的态即被移除。数据侧声明在 `sleep` 上；接线前是 landing 内**硬编码 `"sleep"`**（游戏名词进引擎），现已数据化（引擎只认布尔字段） |
| `start_full` | bool | ⚠️ 包不读（内容侧装配器读：`class_mech_proc.py:2225`） | 开局满额 |
| `start_classes` | `[职业 id]` | ⚠️ 包不读（内容侧读：`class_mech_proc.py:1892/2228/2256`） | **归属过滤**。⚠️ 不声明 = 不装配某些内容侧钩子（详见下「归属门」） |
| `channels` | `{时机: 值}` | ⚠️ 包不读（内容侧读：`class_mech_proc.py:1889`） | 攒取渠道，见 [channels.md](channels.md) |
| `load_tiers` | `[{max, heal_mult, label, overload}]` | ⚠️ 包不读（内容侧读：`class_mech_proc.py:254/2271`） | 负载档位表 |
| `overload_heal_pct` | float | ⚠️ 包不读（内容侧读：`class_mech_proc.py:341`） | 过载触发的全队回复比例 |
| `dot` | — | ⚠️ **无实际消费者** | 只在 `_is_stack_resource` 的判据关键词列表里（`effects.py:278`）。V5 之后 DOT 统一走 `period`，参考实现 78 个 key 里**无一条**使用 |

### 归属门（`start_classes`）的一句话规则

`if _sc and _cn not in _sc: continue`（`class_mech_proc.py:1892-1894`）。

> **空列表 = 不设限 = 谁都能装。** 所以「这个资源只该给某职业」必须写 `start_classes`；
> 而通用效果键（`shield` / `melody_def` 这类）**不要**写它，
> 否则会被内容侧的「资源减伤乘区装配」跳过（`class_mech_proc.py:2247-2249` 原文）。

## `period` 子字段

`period = {"dir": ..., "interval": ..., 数值字段...}`。扩展包读点在
`schedule._settle_time_effects`（`extends/ext_combat/battle/schedule.py:466-610`）。

| 子字段 | 类型 | 默认 | 消费者/语义 |
|---|---|---|---|
| `dir` | str | `"damage"` | ✅ `:246`。四向：`damage` / `heal` / `mana` / `gain` |
| `interval` | float | `1.0` | ✅ `:251`。间隔刻数（**绝对时刻**，非「每 tick」） |
| `turns` | int | `0` | ✅ `:252`。限跳次数，跳到就清层（`0` = 无限）。计数器 `actor["dot_jumps"]`，`schedule.py:666-672` |
| `cap` | int | 0 → 回落 `_cap_of` | ✅ `:341`（仅 `gain` 向）。**可覆盖** `EFFECT_RULES.cap` |
| `amount` | float | 0 | ✅ `:340`（仅 `gain` 向）。每刻加/减量，**负值也走**（衰减），clamp 下限 0 |
| `pct_max_hp` | float | 0 | ✅ `:283`（`damage` 向）。每层每跳的最大生命比例 |
| `pct_boss` | float | — | ✅ `:275`（`damage` 向）。Boss/精英档**精确覆盖** `pct_max_hp`（与 `boss_pct_mult` 二者取一，**不叠乘**） |
| `pct_cur_hp` | float | 0 | ✅ `:287`。每层每跳的**当前**生命比例 |
| `pct_cur_boss` | float | — | ✅ `:286`。Boss 档覆盖 `pct_cur_hp` |
| `atk` | float | 0 | ✅ **2026-09-11（DOT 混合公式）**：`schedule.py:539-543`。乘**施法者强度快照**的 atk 系数（快照见 `entry["src"]` / `effects.note_dot_source`） |
| `matk` | float | 0 | ✅ 同上。乘施法者快照 matk 的系数 |
| `pct_cap` | float | — | ✅ `:280-282`。**单层**百分比上限（`pct` 被 `min` 到该值）；也用于 `atk/matk` 型 DOT（防极端叠层） |
| `boss_pct_mult` | float | — | ✅ `:277`。Boss/精英的 pct 段折扣系数（`pct_boss` 未声明时才用） |
| `double_low_hp_pct` | float | — | ✅ `:312-314`。目标当前生命 < `max_hp×该值` → 本刻伤害 ×2（流血处决线） |
| `resist_cap` | float | — | ✅ `:316-327`。声明即启用「总抗」段：`总抗 = min(resist_cap, actor.dot_res + actor.adapt[key])`，伤害 ×`(1−总抗)` |
| `entry.pct`（条目级） | float | — | ✅ `:264-266`。**条目**上的 `pct` 覆盖表里的 `pct_max_hp`（旧引擎同款语义） |
| `heal_pct` | float | 0 | ✅ `:304`（`heal` 向）。每跳回复最大生命比例 |
| `mana_pct` | float | 0 | ✅ `:311/323`（`heal` 与 `mana` 向）。每跳回复最大魔力比例 |
| `type` | str | — | ⚠️ **无消费者**（参考实现里 `bleed` 写了 `"type": "flat"`） |
| `per_layer` | int | — | ⚠️ **无消费者**（参考实现里 `bleed` 写了 `"per_layer": 0`） |
| `dmg_type` | str | — | ✅ **`ext_combat` 消费**（2026-09-11）：DOT 结算透传为落地 `dmg_kind`（`schedule.py:595`）。`"true"` = 真伤（物免/魔免/格挡全跳过，`landing` 内 `"true" not in kd` 守卫）；空/缺省 = 不减免（与接线前一致） |

**`damage` 向的兜底**：两个 pct 都 <= 0 且**未声明 atk/matk 系数**时 `dmg = max(1, n)`（层数当伤害，`schedule.py:531`）；声明了系数（系数型 DOT，如 poison=atk×0.8）则基线为 0，伤害全部来自系数段。
所以一个只声明 `dir/interval` 的 DOT 每跳掉「层数」点血。

### DOT 混合公式（2026-09-11 接线，权威 = 下游游戏的数值设计文档）

新引擎先前只读 `pct_max_hp`／`pct_cur_hp`，**丢了 atk/matk 系数段与总抗段**。现补齐为：

```
每层每刻 = ( src_atk×period.atk + src_matk×period.matk
             + max_hp×pct_max_hp×(boss折扣) )            ← 系数段 + 百分比段（同为「每层」）
           × 层数
           × (1 − 总抗)                                      ← 总抗 = min(resist_cap, dot_res + adapt[key])
```

- **施法者强度快照**（`src`）：挂 DOT 时由 `effects.note_dot_source()` 记录施法者面板；
  tick 端只读快照 → 「伤害跟**挂毒的人**，不跟当前谁在结算」。快照缺失 = 系数段为 0
  （老档／手工构造条目不崩，本刻 0 伤害不造假值）。
- **登记快照的时机**：引擎 `act_apply`（叠层/快照分支）与内容侧 `_add_stacks(battle=…, caster=…)`
  都调同一个 `note_dot_source`——两处入口，一份实现。
- **零变化保证**：未声明 `atk`/`matk` 系数 → 系数段恒 0；未声明 `resist_cap` → 总抗段跳过。
  既有只写 `pct_max_hp`+`pct_boss` 的条目（裂伤/烬燃等）行为逐字不变。
- **boss 折扣优先级**：条目级 `pct_boss`（精确值）> `boss_pct_mult`（折扣系数），二者取一。

**首跳延迟**：某 key 第一次被结算时只登记 `dot_next[key] = now + interval`
（`schedule.py:494-497`），不在当刻跳。这是对齐旧引擎的语义。

**补跳上限**：一次 `_settle_time_effects` 最多补 20 跳（`guard < 20`，`schedule.py:497`）。

## 三种「声明驱动」的对照组（便于理解哪个字段谁读）

| 你想要的 | 该写在哪 | 引擎会读吗 |
|---|---|---|
| 每层面板加成 | `stat_scale` | ✅ |
| 静态面板增益 | `panel` | ✅（动作参数缺省时） |
| 每层受击增伤 | `debuff_scale` | ✅ 扩展包直读（2026-09-11 接线）；`taken_calc` 仍可用于**条件**减伤 |
| 每刻掉血 | `period.dir="damage"` | ✅ |
| 每刻回资源 | `period.dir="gain"` | ✅ |
| 事件型攒资源 | `channels` | ❌ 内容侧装配器读 |
| 满层触发 | `on_threshold` | ❌ 监听 `threshold` 事件自己实现 |
| 上限加成 | 不在表里 → `actor.bonus.cap[key]` | ✅（`_cap_of` 读 `bonus`） |

## 已知死字段速查（写测试时优先覆盖）

```
on_threshold · wake_on_hit · tag · dot · name                 ← EFFECT_RULES 层
period.type · period.per_layer                                 ← period 层

（2026-09-11 起从死字段转活：debuff_scale · period.dmg_type · period.atk/matk/pct_cap/
  boss_pct_mult/double_low_hp_pct/resist_cap · wake_on_hit）
```

它们的共同特征：**声明了不报错、不生效**。
完整缺口清单 → [../_selfcheck.md](../_selfcheck.md)。

## 参考实现里的真实条目（照抄起点）

```python
# 叠层资源 + 每层面板加成 + 满层声明（cap/stat_scale 生效，on_threshold 不生效）
"zhan_yi": {
    "name": "战意",
    "cap": 10,
    "stat_scale": {"atk": 0.04},              # 每层攻击 +4%
    "on_threshold": {10: {"form": "fury"}},   # ⚠️ 无消费者
},
```
（`game/data/battle_rules.py:23-28`）

```python
# 对敌 DOT：每层每刻掉 3% 最大生命（无限跳）
"burn": {
    "cap": 5,
    "on": "target",
    "period": {"dir": "damage", "interval": 1.0, "pct_max_hp": 0.03},
},
```
（`game/data/battle_rules.py:274-278`）

```python
# 限时 DOT + Boss 档（3 跳后清层）
"blaze": {
    "cap": 3,
    "on": "target",
    "period": {"dir": "damage", "interval": 1.0, "pct_max_hp": 0.015,
               "pct_boss": 0.01, "turns": 3},
},
```
（`game/data/battle_rules.py:313-317`）

```python
# 控制（消费模式进表 → 技能 mech 不必带 mode 参数）
"stun": {"cap": 1, "consume": {"mode": "skip"}, "tag": "stun",
         "cleanse": True, "negative": True},
```
（`game/data/battle_rules.py:398`）

```python
# 静态面板增益（动作瘦身为 key-only，数值查表）
"atk_up": {"cap": 1, "panel": {"stat": "atk", "op": "mul", "mult": 1.30}},
```
（`game/data/battle_rules.py:375`）

## 相关

- 效果容器条目形态 → [../concepts/effects.md](../concepts/effects.md)
- `period` 的时间语义 → [../concepts/ctb-schedule.md](../concepts/ctb-schedule.md)
- 名词→动词表 → [effect-actions.md](effect-actions.md)
- 渠道声明 → [channels.md](channels.md)
