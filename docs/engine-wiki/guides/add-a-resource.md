# 指南：加一个职业资源

「职业资源」= 攒层、有上限、能被技能花掉、能在面板/伤害上生效的一种 `effects` 条目。
本页用一个**完整真实例子**（拳师磐核 `guard_core`）走一遍，最后给最小骨架。

资源**不需要引擎改动**。你需要给的只有：

```
① EFFECT_RULES 一条声明           ← 上限 / 每层效果 / 自然回复 / 攒取渠道
② 消费端（技能数据或 MECH_CASH）  ← 怎么花掉
③ 一个装配器（channels 是声明驱动的，写一次就通用）
```

## 完整例子：磐核（`guard_core`）

真实条目（游戏仓侧参考实现《奥兰迪亚》的职业资源），`game/data/battle_rules.py:225-241`：

```python
"guard_core": {
    "name": "磐核",
    "cap": 5,
    "start_classes": ["cls_wu_seng"],
    "stat_scale": {"reduce": 0.03},        # 每核减伤 +3%（经乘区钩子落地，见注①）
    "channels": {
        # 守线技能命中 +1（无条件）
        "skill_hit": 1,
        # 守御姿态下受击 +1（条件攒取：姿态效果键 has_effect 谓词）
        "taken": {"gain": 1,
                  "when": [{"judge": {"kind": "has_effect", "key": "guard_stance"}}]},
        # 守御姿态下每刻 +0.4（时钟事件；per_dt 按 dt 缩放）
        "tick": {"gain": 0.4, "per_dt": True,
                 "when": [{"judge": {"kind": "has_effect", "key": "guard_stance"}}]},
    },
},
```

逐字段读法：

| 字段 | 作用 | 引擎侧消费者 |
|---|---|---|
| `cap: 5` | 叠层上限 | `effects._cap_of`（`effects.py:64`）；`apply op=add` 与 `schedule` gain 都 clamp |
| `name` | 日志/UI 标签 | **引擎不读**；内容侧读（`class_mech_proc.py:1895`） |
| `start_classes` | 归属过滤（只有该职业装配） | **引擎不读**；内容侧装配器读（`class_mech_proc.py:1892`）。⚠️ 不声明 = 不装配 |
| `stat_scale.reduce: 0.03` | 每核减伤 | `stats._apply_effects`（`stats.py:60-65`）→ 写 `st["reduce"]` ⚠️ 但 `st["reduce"]` 无伤害路径消费者 → 真正生效另有通道（见下「注①」） |
| `channels` | 攒取渠道 | **引擎不读**；内容侧 `apply_class_channels`（`class_mech_proc.py:1871`）翻译成 `actor.triggers` |

注释里的 **注①** 是这套引擎最典型的一类坑，原文见 `game/data/battle_rules.py:218-224`：

> ① 「每核 减伤 +3%」经 `stat_scale.reduce` 声明——saintess_engine 伤害路径**不消费** `st["reduce"]`
> （stats 只写、instance 仅展示），故装配层（`class_mech_proc.apply_class_mech`）按本声明挂
> `taken_calc` 乘区钩子（`passive_taken_reduce` per_core 段）落地；`st["reduce"]` 冗余写入无害。

即：**声明照写**（它是数值权威），**装配器得把它翻译成真正生效的乘区**。
如果你不装这个乘区钩子，减伤就是**写了但没发生**。

## 攒取渠道：六个时机名

渠道声明的消费者是内容侧 `_CHANNEL_EVENTS`（`class_mech_proc.py:1861-1868`）：

| 渠道名 | 映射到的事件 | 附加过滤 | 语义 |
|---|---|---|---|
| `attack_hit` | `attack_hit` | — | 普攻命中 |
| `skill_hit` | `skill_hit` | — | 技能命中 |
| `heal_cast` | `act_cast` | `kind="治疗"` | 治疗施放（施放与命中同刻，避免多目标重复） |
| `taken` | `on_taken` | — | 受击（真实承伤后） |
| `cast` | `act_cast` | `not_basic=True` | （预留）技能施放 |
| `tick` | `time_advance` | — | 每刻时钟推进（ctx 带 `dt` / `now`） |

### 渠道值的两种形态

```python
"channels": {
    "skill_hit": 1,                                       # 形态 A：无条件简写
    "taken": {"gain": 1, "when": [...]},                  # 形态 B：带条件
    "tick":  {"gain": 0.4, "per_dt": True, "when": [...]} # 形态 B + per_dt
}
```

- **形态 A**：`(int|float)` = 无条件 gain。`gain <= 0` 直接跳过（`class_mech_proc.py:1906`）
- **形态 B**：`{"gain": ..., "when": [...], "per_dt": bool}`

### `when` 条件（动作入口求值）

`when` 是**列表**，逐条按 `judge.kind` 派发（`_when_ok`，`class_mech_proc.py:2134-2161`）。
**全部满足才攒**；未知 kind → **False（fail-closed）**，原文理由：

> 渠道条件写错时宁可漏攒，不可静默攒错（数值膨胀无声无息，比漏攒危险得多）

`when` 支持的谓词（`_when_ok` 只有一个子集）：

| kind | 判据 | 需要的字段 |
|---|---|---|
| `has_effect` | `actor.effects[key]` 是 dict（在位=生效，过期条目已被 schedule 删） | `key` |
| `res_ge` | `actor.effects[res].stacks >= 阈值` | `res` + 阈值字段名 |

⚠️ 「不过期的效果」永远算在位 —— `has_effect` 只能表达「有这个键」，
不能表达「层数够」。要层数用 `res_ge`。

### `per_dt`：按时间缩放

`per_dt=True` 时 gain 乘上事件的 `dt`（`class_res_channel_gain`，`class_mech_proc.py:213-215`）。
原因：`time_advance` 的 `dt` 可能不是 1.0（一次 `_advance_time` 可能跨好几刻），
不缩放就会出现「跨 3 刻只攒 1 次」的漏攒。

### `tick` 渠道 vs `period` 声明：两个不同的东西

| | `channels.tick` | `EFFECT_RULES[key].period` |
|---|---|---|
| 谁执行 | **内容侧**渠道动作 | **引擎** `schedule._settle_time_effects` |
| 写日志 | 有（渠道动作会写） | `dir="gain"` 静默 |
| 何时记录 | 事件驱动 | 时刻推进时结算 |

两者都能实现「每刻回资源」。区别是 `period` 在引擎里、与 DOT/HOT 同一套结算；
`channels.tick` 在内容侧、能挂 `when` 条件（如「守御姿态下才回」）。
`guard_core` 选 `channels.tick` 正是因为要用 `when`。

## 消费端：花掉资源

三条路，从简到繁：

### ① 技能数据的 `res_cost`（推荐）

```python
info["res_cost"] = {"guard_core": 3}     # 施放时扣 3 层
```

引擎原生消费（**这是引擎唯一直接认的资源字段**）：

- 预检：`_skill_usable`（`actions.py:143`）——条目存在且 `stacks < 需求` → 拦截 + 写日志
  「⚡ 核心资源不足：需要 X key，当前 Y！」
- 扣费：`_spend_skill_cost`（`actions.py:196`）——`stacks = norm_stack(max(0, cur - rv))`

⚠️ **一个重要的历史行为**：`res_cost` 只在 `actor.effects` **已经有该 key 条目**时才拦截
（`actions.py:188-191` 的 `continue`）。没条目 = 不拦（保持历史行为）。
所以「资源渠道没接通」时技能是**免费**的，不是被拦。原型期友善，生产期是漏洞。

### ② `MECH_CASH` 兑现（层数换伤害 + 清层）

```python
"guard_core_burst": {                     # game/data/battle_rules.py:555
    "name": "磐核",
    "mode": "dmg_mult_clear",             # owner=caster：读/清 caster 层
    "key": "guard_core",
    "per_layer": 0.7,                     # 每核 +70%（满 5 核 ×4.5）
    "clear": True,
},
```

装配器（`class_mech_proc.apply_class_mech`）把它翻成两个触发器：
`dmg_calc` 上挂乘区、`skill_hit` 上挂清层（`class_mech_proc.py:2350-2374`）。
mode 全谱 → [../reference/mech-cash.md](../reference/mech-cash.md)。

### ③ `consume_all`（清零）

```python
info["consume_all"] = {"key": "arcane"}    # actions.py:221-224：直接 ef.pop
```

## 自然回复 / 衰减

```python
"period": {"dir": "gain", "interval": 1.0, "amount": 18}    # 每刻 +18
"period": {"dir": "gain", "interval": 1.0, "amount": -0.7}  # 每刻 -0.7（允许负值）
```

- 引擎侧消费者：`schedule._settle_time_effects` 的 `gain` 分支（`schedule.py:712-731`）
- **静默**（不刷日志，`schedule.py:719-720` 注释）
- clamp 到 `[0, cap]`，cap 取 `period.cap` 或 `_cap_of`（表声明 + `bonus.cap`）
- 负数也走（信仰清醒档衰减），但**下限 0**，不会归负
- `dir="gain"` **不要求 `stacks > 0`** —— 0 层也要能回（`schedule.py:578-581`）

## 开局满额

```python
"energy": {"cap": 100, "start_full": True, "start_classes": ["cls_you_xia"], ...}
```

装配器在开战时把 `effects[key] = {"stacks": cap, "expire": 999999.0}`
（`class_mech_proc.py:2221-2236`）。⚠️ `expire: 999999.0` 是个「近似永久」的魔数，
不是 `None`（`None` 才是引擎语义的永久）。

## 归属过滤：为什么必须有 `start_classes`

装配器读 `start_classes` 决定「这个职业才装配」：

```python
_sc = _rc.get("start_classes") or []
if _sc and _cn not in _sc:
    continue        # class_mech_proc.py:1892-1894
```
（⚠️ 注意 `if _sc and ...`：**空列表 = 不设限 = 谁都能装**。所以通用资源键
——`shield` / `melody_def` 这类——千万别写 `start_classes` 为空却期望它只给某个职业。）

同样口径也用在 **`stat_scale.reduce → taken_calc` 乘区装配**上，原文说得最明白
（`class_mech_proc.py:2247-2249`）：

> 归属过滤 = start_classes（**必须**声明 start_classes 才装配——无归属声明的通用效果键
> 如 shield/melody_def 不接，防误加），零职业名硬编码。

也就是说：**没写 `start_classes` 的资源，它的 `stat_scale.reduce` 不会被装配成减伤乘区**。

## 最小骨架（照抄改）

```python
# game/data/battle_rules.py
EFFECT_RULES["my_res"] = {
    "name": "我的资源",
    "cap": 8,
    "start_classes": ["cls_my_class"],          # ← 不写就不会被装配
    "stat_scale": {"atk": 0.02},                # 每层攻击 +2%（stats 直接消费，无需装配器）
    "channels": {
        "skill_hit": 1,                          # 技能命中 +1
        "taken": {"gain": 1, "when": [{"judge": {"kind": "has_effect", "key": "my_form"}}]},
        "tick":  {"gain": 0.25, "per_dt": True,
                  "when": [{"judge": {"kind": "has_effect", "key": "my_form"}}]},
    },
    "period": {"dir": "gain", "interval": 1.0, "amount": -0.5},   # 每刻衰减 0.5
}
```

消费用 `res_cost`：技能数据写 `"res_cost": {"my_res": 4}`。

**验证清单**（每加一个资源都过一遍）：

1. 开战后 `actor["effects"]["my_res"]` 存在吗？→ 不存在 = 渠道没装配（检查 `start_classes`）
2. 打一下，`stacks` 涨了吗？→ 不涨 = 渠道名写错（`_CHANNEL_EVENTS` 里没有的会静默跳过，
   `class_mech_proc.py:1908-1910`）
3. 涨得对不对？→ `when` 条件是否满足、`per_dt` 是否该开
4. 到 cap 有停吗？→ cap 写对了吗（`_cap_of` 无声明 = 999999）
5. 技能花得掉吗？→ `res_cost` 的 key 与资源 key 一致吗
6. 面板/乘区生效了吗？→ `stat_scale.atk` 类会直接生效；`stat_scale.reduce` 类**需要装配器钩子**

## 相关

- `period` 与渠道的字段 schema → [../reference/effect-rules.md](../reference/effect-rules.md) ·
  [../reference/channels.md](../reference/channels.md)
- `MECH_CASH` 兑现 → [../reference/mech-cash.md](../reference/mech-cash.md)
- 规则声明的原理 → [../concepts/declaration-tables.md](../concepts/declaration-tables.md)
