# 参考：渠道时机表

> ⚠️ **边界声明**：`channels` 是**内容侧装配约定**，不是引擎 API。
> 声明写在 `EFFECT_RULES[资源key].channels` 里；读它并翻译成 `actor["triggers"]` 的是
> 你的装配器（参考实现：`game/services/class_mech_proc.py:1871` `apply_class_channels`，
> 时机映射表在 `:1861-1868`）。引擎侧零代码认识 `channels`。

## 时机名 → 引擎事件（六个）

```python
_CHANNEL_EVENTS = {                             # class_mech_proc.py:1861
    "attack_hit": ("attack_hit", {}),           # 普攻命中
    "skill_hit":  ("skill_hit",  {}),           # 技能命中
    "heal_cast":  ("act_cast", {"kind": "治疗"}),# 治疗施放
    "taken":      ("on_taken",  {}),            # 受击（真实承伤后，subject=受击者）
    "cast":       ("act_cast", {"not_basic": True}),  # （预留）技能施放（未装配用）
    "tick":       ("time_advance", {}),         # 每刻时钟推进（ctx 带 dt/now）
}
```

第二个元素是**附加过滤参数**，装配时并进触发器条目（`class_mech_proc.py:1913`）。

| 时机名 | 会被过滤掉什么 | 说明 |
|---|---|---|
| `attack_hit` | — | 普攻命中（`info["_basic"]` 为真的那一支） |
| `skill_hit` | — | 技能命中 |
| `heal_cast` | `kind != "治疗"` 的行动 | 「治疗『施放』与『命中』同刻 → 用 `act_cast` + `kind=治疗`」；每技能施放 fire 1 次，**不会多目标重复**；普攻（basic 也走 `do_skill`）的 `kind` 是物理 → 天然被排除 |
| `taken` | — | 受击；`on_taken` 的 subject 是受击者 |
| `cast` | `info["_basic"]` 为真 | 注释标注「（预留）未装配用」——⚠️ 参考实现里 `EFFECT_RULES` **没有**任何资源用 `cast` |
| `tick` | — | 时钟推进；⚠️ **不是每秒一次**，是每次 `_advance_time` 一次（`dt` 可能 != 1） |

未映射的时机名 → **静默跳过**（`class_mech_proc.py:1908-1910`，注释：
「版本漂移保护，同 affix 翻译器缺口词条行为」）。

## 渠道值的两种形态

```python
"channels": {
    "skill_hit": 1,                                        # 形态 A：无条件
    "taken": {"gain": 1, "when": [{"judge": {...}}]},       # 形态 B：条件
    "tick":  {"gain": 0.4, "per_dt": True,
              "when": [{"judge": {...}}]},                  # 形态 B + per_dt
},
```

解析（`class_mech_proc.py:1896-1919`）：

| 形态 | 读取 |
|---|---|
| A：`int` / `float` | `gain = 值`；`when = None`；`per_dt = None` |
| B：`dict` | `gain = cv["gain"]`；`when = cv["when"]`；`per_dt = cv["per_dt"]` |

校验：`gain` 必须是 `int|float` 且 `> 0`（`:1906-1907`），否则跳过。
**所以渠道值不能是 0 或负数** —— 要减资源用 `period.amount` 负值（
[effect-rules.md](effect-rules.md)）。

## 装配产出

每条有效渠道产出一个触发器（`:1911-1920`）：

```python
{"type": "class_res_channel_gain", "res": <资源key>, "gain": <float>,
 "label": <name>, "icon": "✦", **附加过滤参数}
# when 存在时才写：  "when": [...]
# per_dt 为真时才写："per_dt": True
```

再按 `_CHANNEL_EVENTS` 挂到对应事件上（`:1920`）。
**零默认值**：无 `when` 就**不写 `when` 键**（不是写 `when: []`）。

## `when` 条件求值

动作入口求值 `_when_ok(actor, params)`（`class_mech_proc.py:2134-2161`）：

- `when` 是**列表**，逐条求值，**全部满足才攒**（AND）
- 每条形如 `{"judge": {"kind": ...}}`
- 支持的 kind：`has_effect` / `res_ge`（只有这两个，`else: return False`）
- 无 `when` 声明 → 恒 True

⚠️ **阈值位置**：渠道 `when` 的 `res_ge` 从 **when 条目自身**读阈值
（`_res_ge_ok(actor, j, w)` 第三参是 `w`），不是从 `params` 顶层读。
与被动 judge 的 `res_ge` 不同 —— 详见 [judges.md](judges.md) 的三套谓词集对照。

## `per_dt`：按时间缩放

```python
if params.get("per_dt"):
    gain = gain * float(ctx.get("dt", 1.0) or 1.0)
```
（`class_mech_proc.py:213-215` 附近）

**为什么必须**：`time_advance` 的 `dt` 可能不是 1.0（一次 `_advance_time` 可以跨几刻，
见 `schedule.advance`）。不缩放会出现「跨 3 刻只攒一次」。

参考实现的真实用例（`guard_core` 的 `tick` 渠道）：

```python
"tick": {"gain": 0.4, "per_dt": True,
         "when": [{"judge": {"kind": "has_effect", "key": "guard_stance"}}]},
```
（`game/data/battle2_rules.py:238-239`）—— 「守御姿态下每刻 +0.4 磐核」。

## 参考实现里的渠道使用情况

`EFFECT_RULES` 78 个 key 中**只有 2 个**声明了 `channels`（本次核实）：

```python
"faith": {                                    # game/data/battle2_rules.py:174
    "start_classes": ["cls_mu_shi"],
    "channels": {"heal_cast": 2, "taken": 1},
    ...
}
"guard_core": {                               # game/data/battle2_rules.py:230
    "channels": {
        "skill_hit": 1,
        "taken": {"gain": 1, "when": [{"judge": {"kind": "has_effect",
                                                 "key": "guard_stance"}}]},
        "tick": {"gain": 0.4, "per_dt": True,
                 "when": [{"judge": {"kind": "has_effect", "key": "guard_stance"}}]},
    },
}
```

出现过的时机名（并集）：`heal_cast` · `skill_hit` · `taken` · `tick`。
`attack_hit` 与 `cast` 在参考实现里**未被使用**。

## 渠道 vs `period` vs 触发器：三种「定时给东西」

| 手段 | 声明位置 | 执行者 | 能带条件 | 有日志 |
|---|---|---|---|---|
| `channels.<时机>` | `EFFECT_RULES[key].channels` | 内容侧动作 `class_res_channel_gain` | ✅ `when` | ✅（动作会写） |
| `period`（`dir="gain"`） | `EFFECT_RULES[key].period` | 引擎 `schedule._settle_time_effects` | ❌ | ❌ 静默 |
| 直接写 `triggers` | 任何地方 | 引擎 `fire` | ❌（动作自己判） | 看动作 |

**选择建议**：

- 「每刻回资源 + 带条件」→ `channels.tick`（引擎的 `period` 不支持条件）
- 「每刻回资源，无条件/纯衰减」→ `period.dir="gain"`（引擎原生，少一层内容代码）
- 「命中/受击时攒」→ `channels.<hit时机>`
- 「一次性/特殊时机」→ 自己往 `triggers` 里写

## 加一个新渠道

1. 在 `_CHANNEL_EVENTS` 里加一行 `"时机名": (事件名, 附加参数)`
   （**必须在内容侧**，引擎不认识渠道名）
2. 在资源的 `channels` 里用它：

```python
"my_res": {
    "cap": 8, "start_classes": ["cls_x"],
    "channels": {"my_timing": {"gain": 1, "when": [...]}},
}
```

3. 确认目标事件在 `EVENTS` 里（否则 `fire` 静默忽略，见 [events.md](events.md)）

⚠️ 加渠道**不需要改引擎**，但**需要改装配器** —— 这是「内容侧约定」的代价。

## 相关

- 资源声明的完整写法 → [../guides/add-a-resource.md](../guides/add-a-resource.md)
- `EFFECT_RULES` 字段 → [effect-rules.md](effect-rules.md)
- 谓词的三套形态 → [judges.md](judges.md)
- 事件时机 → [events.md](events.md)
