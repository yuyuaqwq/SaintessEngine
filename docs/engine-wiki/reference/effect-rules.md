# 参考：`EFFECT_RULES` 字段 schema

`EFFECT_RULES` = 「效果 key → 行为规则」的表。它**不是引擎文件**，是你注入的内容表；
引擎通过 `config.set_config("effect_rules", ...)` / `load_game_rules(module)` 读它，
读点在 `state_effects.state_def`（`state_effects.py:13`）。

**无条目 = 空 dict = 纯数值无规则**（`config.state_def`，`config.py:110-116`）——
这是合法状态，不是错误。

字段清单来自游戏仓参考实现（`game/data/battle2_rules.py`，78 个 key）的**实际使用并集**，
加上引擎代码里被读取的字段。每个字段都标了消费者：

- ✅ = 引擎消费
- ⚠️ = **当前无消费者**（声明了也不生效）

## 顶层字段

| 字段 | 类型 | 消费者 | 语义 |
|---|---|---|---|
| `cap` | int | ✅ `effects._cap_of`（`effects.py:58-75`） | 叠层上限基数。**收敛点唯一**：`apply op=add/set`、`schedule` gain、内容侧渠道攒取都走它。缺声明（0）→ **999999（不设限）** |
| `name` | str | ⚠️ 引擎不读 | 展示名。内容侧做日志/UI 标签（`class_mech_proc.py:1895`） |
| `stat_scale` | `{stat: 每层系数}` | ✅ `stats._apply_effects`（`stats.py:61-68`） | 每层面板修正。`st[stat] *= (1 + n×系数)`；特殊 stat：`dmg_mult`（写 `st["_state_dmg_mult"]`，伤害乘区读它）、`reduce`（写 `st["reduce"]`，⚠️ 见「已知死字段」） |
| `debuff_scale` | `{stat: 每层系数}` | ⚠️ **无消费者** | 只在 `effects._is_stack_resource` 的判据关键词列表里出现（`effects.py:249`）。**「每层承伤 +N%」实际不生效** |
| `panel` | `{"stat","op","mult"}` | ✅ `effects.act_apply` 快照分支（`effects.py:376-388`） | 静态面板增益的默认值（动作参数缺省时查表）。`op`：`mul`（乘）/ `add`（加）；`op="reduce"` 特殊（见 `stats.py:76-77`） |
| `consume` | `{"mode": ...}` | ✅ `effects.act_apply`（`effects.py:293-296`）+ `Battle.act`（`battle.py:423-446`） | 控制型条目的消费模式：`"skip"`（整跳行动）/ `"no_skill"`（技能转普攻） |
| `period` | dict | ✅ `schedule._settle_time_effects`（`schedule.py:239-247`） | 周期结算声明（见下） |
| `cleanse` | bool | ✅ `effects.act_cleanse`（`effects.py:498`） | `True` = 可被净化 |
| `on` | `"caster"` \| `"target"` | ✅ `effects.act_cleanse`（`effects.py:498`，`on=="target"` 也清）；内容侧 `_mech_to_effect` 判 `on_target`（`effects.py:219`） | 效果的默认作用对象。`"target"` = 对敌标记类 |
| `negative` | bool | ⚠️ 引擎不读 | 「负面」标记。内容侧用它数「负面种数」（`class_mech_proc.py:767`，`target_debuff_kinds` judge） |
| `tag` | str | ⚠️ 引擎不读 | 旧 CLEANSE_TAGS 时代的标记。`act_apply` 读的是 **params** 的 `tag`（作为 `key` 的兜底，`effects.py:287`），不是 `cfg["tag"]` |
| `cd_mult` | float | ✅ `actions.do_skill`（`actions.py:89-97`） | 冷却倍率（`0.8` = CD −20%）。多态并存时**取最小**（最速） |
| `on_threshold` | `{层数: {...}}` | ⚠️ **无消费者** | 「满 N 层触发什么」。`threshold` **事件**有引擎点位（`effects.py:349`），但**这张映射表没被读**。目前要靠内容侧监听 `threshold` 自己实现 |
| `guard_hp_pct` | float | ✅ `landing._apply_death_guard`（`landing.py:258`） | 濒死保护触发后保底到的最大生命比例（缺省 0.10） |
| `heal_pct` | float | ✅ 同上（`landing.py:261`） | 濒死保护触发时额外回复的最大生命比例 |
| `wake_on_hit` | bool | ⚠️ **无消费者** | 声明在 `sleep` 上。实际「受击打醒」由 `landing.py:117` 的**硬编码 key 判断**实现（`if target.get("effects", {}).get("sleep")`），与这个字段无关 |
| `start_full` | bool | ⚠️ 引擎不读（内容侧装配器读：`class_mech_proc.py:2225`） | 开局满额 |
| `start_classes` | `[职业 id]` | ⚠️ 引擎不读（内容侧读：`class_mech_proc.py:1892/2228/2256`） | **归属过滤**。⚠️ 不声明 = 不装配某些内容侧钩子（详见下「归属门」） |
| `channels` | `{时机: 值}` | ⚠️ 引擎不读（内容侧读：`class_mech_proc.py:1889`） | 攒取渠道，见 [channels.md](channels.md) |
| `load_tiers` | `[{max, heal_mult, label, overload}]` | ⚠️ 引擎不读（内容侧读：`class_mech_proc.py:254/2271`） | 负载档位表 |
| `overload_heal_pct` | float | ⚠️ 引擎不读（内容侧读：`class_mech_proc.py:341`） | 过载触发的全队回复比例 |
| `dot` | — | ⚠️ **无实际消费者** | 只在 `_is_stack_resource` 的判据关键词列表里（`effects.py:249`）。V5 之后 DOT 统一走 `period`，参考实现 78 个 key 里**无一条**使用 |

### 归属门（`start_classes`）的一句话规则

`if _sc and _cn not in _sc: continue`（`class_mech_proc.py:1892-1894`）。

> **空列表 = 不设限 = 谁都能装。** 所以「这个资源只该给某职业」必须写 `start_classes`；
> 而通用效果键（`shield` / `melody_def` 这类）**不要**写它，
> 否则会被内容侧的「资源减伤乘区装配」跳过（`class_mech_proc.py:2247-2249` 原文）。

## `period` 子字段

`period = {"dir": ..., "interval": ..., 数值字段...}`。引擎读点在
`schedule._settle_time_effects`（`schedule.py:226-362`）。

| 子字段 | 类型 | 默认 | 消费者/语义 |
|---|---|---|---|
| `dir` | str | `"damage"` | ✅ `:246`。四向：`damage` / `heal` / `mana` / `gain` |
| `interval` | float | `1.0` | ✅ `:251`。间隔刻数（**绝对时刻**，非「每 tick」） |
| `turns` | int | `0` | ✅ `:252`。限跳次数，跳到就清层（`0` = 无限）。计数器 `actor["dot_jumps"]`，`schedule.py:351-359` |
| `cap` | int | 0 → 回落 `_cap_of` | ✅ `:341`（仅 `gain` 向）。**可覆盖** `EFFECT_RULES.cap` |
| `amount` | float | 0 | ✅ `:340`（仅 `gain` 向）。每刻加/减量，**负值也走**（衰减），clamp 下限 0 |
| `pct_max_hp` | float | 0 | ✅ `:264`（`damage` 向）。每层每跳的最大生命比例 |
| `pct_boss` | float | — | ✅ `:268`（`damage` 向）。Boss 档（`is_boss` / `role=="boss"`）覆盖 `pct_max_hp` |
| `pct_cur_hp` | float | 0 | ✅ `:265`。每层每跳的**当前**生命比例 |
| `pct_cur_boss` | float | — | ✅ `:272`。Boss 档覆盖 `pct_cur_hp` |
| `heal_pct` | float | 0 | ✅ `:304`（`heal` 向）。每跳回复最大生命比例 |
| `mana_pct` | float | 0 | ✅ `:311/323`（`heal` 与 `mana` 向）。每跳回复最大魔力比例 |
| `type` | str | — | ⚠️ **无消费者**（参考实现里 `bleed` 写了 `"type": "flat"`） |
| `per_layer` | int | — | ⚠️ **无消费者**（参考实现里 `bleed` 写了 `"per_layer": 0`） |
| `dmg_type` | str | — | ⚠️ **无消费者**（参考实现里 `corros` 写了 `"dmg_type": "true"`）。DOT 落地统一调 `deal_damage(battle, None, a, dmg, logs)`（`schedule.py:292`，**不传 `dmg_kind`**）→ 所以吃不到类型免伤与格挡，是因为 `dmg_kind` 为空，不是因为声明了真伤 |

**`damage` 向的兜底**：两个 pct 都 <= 0 时 `dmg = max(1, n)`（层数当伤害，`schedule.py:276`）。
所以一个只声明 `dir/interval` 的 DOT 每跳掉「层数」点血。

**首跳延迟**：某 key 第一次被结算时只登记 `dot_next[key] = now + interval`
（`schedule.py:254-257`），不在当刻跳。这是对齐旧引擎的语义。

**补跳上限**：一次 `_settle_time_effects` 最多补 20 跳（`guard < 20`，`schedule.py:261`）。

## 三种「声明驱动」的对照组（便于理解哪个字段谁读）

| 你想要的 | 该写在哪 | 引擎会读吗 |
|---|---|---|
| 每层面板加成 | `stat_scale` | ✅ |
| 静态面板增益 | `panel` | ✅（动作参数缺省时） |
| 每层受击增伤 | `debuff_scale` | ❌ 用 `taken_calc` 乘区代替 |
| 每刻掉血 | `period.dir="damage"` | ✅ |
| 每刻回资源 | `period.dir="gain"` | ✅ |
| 事件型攒资源 | `channels` | ❌ 内容侧装配器读 |
| 满层触发 | `on_threshold` | ❌ 监听 `threshold` 事件自己实现 |
| 上限加成 | 不在表里 → `actor.bonus.cap[key]` | ✅（`_cap_of` 读 `bonus`） |

## 已知死字段速查（写测试时优先覆盖）

```
debuff_scale · on_threshold · wake_on_hit · tag · dot · name   ← EFFECT_RULES 层
period.type · period.per_layer · period.dmg_type               ← period 层
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
（`game/data/battle2_rules.py:23-28`）

```python
# 对敌 DOT：每层每刻掉 3% 最大生命（无限跳）
"burn": {
    "cap": 5,
    "on": "target",
    "period": {"dir": "damage", "interval": 1.0, "pct_max_hp": 0.03},
},
```
（`game/data/battle2_rules.py:274-278`）

```python
# 限时 DOT + Boss 档（3 跳后清层）
"blaze": {
    "cap": 3,
    "on": "target",
    "period": {"dir": "damage", "interval": 1.0, "pct_max_hp": 0.015,
               "pct_boss": 0.01, "turns": 3},
},
```
（`game/data/battle2_rules.py:313-317`）

```python
# 控制（消费模式进表 → 技能 mech 不必带 mode 参数）
"stun": {"cap": 1, "consume": {"mode": "skip"}, "tag": "stun",
         "cleanse": True, "negative": True},
```
（`game/data/battle2_rules.py:398`）

```python
# 静态面板增益（动作瘦身为 key-only，数值查表）
"atk_up": {"cap": 1, "panel": {"stat": "atk", "op": "mul", "mult": 1.30}},
```
（`game/data/battle2_rules.py:375`）

## 相关

- 效果容器条目形态 → [../concepts/effects.md](../concepts/effects.md)
- `period` 的时间语义 → [../concepts/ctb-schedule.md](../concepts/ctb-schedule.md)
- 名词→动词表 → [effect-actions.md](effect-actions.md)
- 渠道声明 → [channels.md](channels.md)
