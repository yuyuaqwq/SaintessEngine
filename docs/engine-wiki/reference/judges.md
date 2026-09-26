# 参考：judge 谓词

> ⚠️ **边界声明**：`judge` 是**内容侧装配约定**，不是引擎 API。
> 引擎只把 `triggers` 条目里的 `judge` 当普通 dict 透传给动词（`params["judge"]`）；
> **哪个 kind 被理解、怎么判、缺字段怎么办，全由动作自己决定**。
> 参考实现在**游戏仓 / 奥兰迪亚侧**的 `game/services/class_mech_proc.py`。
>
> 本页给「按动作分域的谓词清单」——因为谓词与动作是**一对耦合**：
> 你在声明里写 `judge.kind = "res_ge"`，就必须挂一个认识 `res_ge` 的动作。

## 通用形状

```python
"judge": {"kind": "res_ge", "res": "zhan_yi", "ge_field": "stacks"}
```

- `kind` — 谓词名；动作内部 `kind = judge.get("kind") or "<默认>"` 分派
- 其余键 — 谓词参数
- 阈值通常是**字段名**（`ge_field` / `layers_field`），实际值从
  `params[阈值字段]` 读 → 也就是从技能数据的 `passive` dict 来

## 按动作分域（已核实的清单）

### `passive_dmg_mult`（`dmg_calc` 乘区）— `class_mech_proc.py:703`

8 个 kind，全部在同一个 action 里分派（`:721-817`）：

| kind | 判据 | 参数 | 加成 |
|---|---|---|---|
| `mech_eq` | `info.mech == judge.mech` | `mech` | `params.mult` 或 `dmg_add` |
| `mech_prefix` | `info.mech` 以 `judge.mech` 开头 | `mech` | `params.mult` 或 `dmg_add` |
| `target_marks_all_ge` | 目标**多个**印记都 ≥ `layers` | `marks: [...]`（列表）、阈值 `params.layers` / `judge.layers`（缺省 1） | `params.mult` |
| `target_mark_any` | 目标带标记（层 > 0） | `mark`（单个 key） | `params.per_layer × 层数` |
| `target_debuff_kinds` | 目标**负面种数**（声明 `negative=True` 或 `on=="target"` 的条目数） | 数值 `params.per_debuff` + `params.cap` | `min(per_debuff × 种数, cap)` |
| `speed_ratio_ge` | 我方 spd ≥ `ratio × 敌方 spd`（敌 spd 为 0 时跳过） | 比值 `params.ratio` / `judge.ratio` | `params.dmg_add` 或 `mult` |
| `target_bar_ge` | 目标挂敌身条的 `val` ≥ 门槛 | `bar`（条名）、门槛字段 `judge.ge_field`（默认 `bar_at`） | `params.mult` / `dmg_add` |
| `target_bar_broken` | 目标条处于**破防期**（`trigger_count>0` 且 `immune_until > now`） | `bar` | `params.broken_mult` / `mult` / `dmg_add` |

**动作行为**：命中时 `ctx["mult"] *= (1 + 加成)`，`加成 <= 0` 则不动（`:815-818`）。
`target_bar_*` 会先 `bar_settle(tg, bar, now)` 把条结算到当刻再读（`:798-801`）。

### `passive_taken_reduce`（`taken_calc` 乘区）— `class_mech_proc.py:964`

3 个 kind（`:981-1002`）：

| kind | 判据 | 参数 |
|---|---|---|
| `res_ge` | 资源 `effects[res].stacks >= params[ge_field]` | `res`、`ge_field` |
| `has_effect` | `effects[key]` 是 dict（在位=生效） | `key` |
| `per_core` | `reduce = params.per_core × effects[res].stacks`（**float 读**，小数层保真） | `res`（阈值来自 `params.per_core`，无 `ge_field`） |

**动作行为**：`ctx["mult"] *= (1 - min(reduce, 0.9))`（`:1003`）。
⚠️ **未知 kind = fail-closed**（`else: return`，`:1001-1002`）——声明写错 = 完全不减伤。

### `passive_cond_crit`（`act_cast` 条件暴击）— `class_mech_proc.py:905`

| 判据键 | 语义 |
|---|---|
| `res` | 资源 key |
| `ge_field` | 阈值字段名（值从 `params` 读） |
| `mech`（可选） | 技能系过滤：`info.mech` 不匹配 → 清残留跳过 |
| `not_basic`（可选） | `info["_basic"]` 为真 → 清残留跳过（普攻不吃） |

额外语义：`act_cast` 在 `_spend_skill_cost` **之后** fire，所以动作会把
`info["res_cost"][res]` 加回当前层数，还原「**施放前**结余」再比较（`:946-954`）。

### `passive_overflow_shield`（`taken_calc` 溢出转盾）— `class_mech_proc.py:1406`

`res_ge`（走 `_res_ge_ok`）。参数 `res` / `shield_pct` / `turns`。

### `passive_dot_mult`（`dot_calc` DOT 乘区）— `class_mech_proc.py:1177`

| 键 | 语义 |
|---|---|
| `dot_key` | 只加成指定 DOT（`ctx["dot_key"] != allow` → 返回） |

`ctx["mult"] *= (1 + params.mult)`。

### `passive_poison_weaken`（`dot_calc` 条件 debuff）— `class_mech_proc.py:1202`

| 键 | 语义 |
|---|---|
| `dot_key` | DOT 过滤 |
| `layers_field` | 层数门槛字段名（值从 `params` 读） |

⚠️ **实现细节**：层数硬读 `target.effects["poison"]`（`:1221`），
`judge.dot_key` 只做过滤。所以 `dot_key` 不是 `poison` 时，门槛仍按 poison 层数算 —— 潜在不一致。

### 只用零星键的动作

| 动作 | 位置 | 读的键 |
|---|---|---|
| `passive_ctrl_extend`（控制时长延长） | `:643` | `judge.ctrl_keys` |
| `passive_bar_extend`（破防窗口延时） | `:821` | `judge.bar` |
| `passive_bar_decay_half`（条衰减减半） | `:1675` | `judge.bar` |
| `passive_poison_spread`（毒层扩散） | `:1774` | `judge.key`（+ 顶层 `mech_prefix` 键） |
| `passive_melody_duet` | `:580` | `judge.mech` |
| `passive_lian_duan_soft` | — | `res` / `gap`（顶层键） |
| `class_res_channel_gain`（渠道攒取） | `:180` | **不读 judge**，读 `params["when"]` 列表（见下） |

## `when` 条件门：另一套（更小的）谓词集

渠道的「条件攒取」用的是 `when` 列表而不是单个 `judge`。求值器 `_when_ok`
（`class_mech_proc.py:2134-2161`）：

```python
when = [{"judge": {"kind": "has_effect", "key": "guard_stance"}}, ...]
```

| kind | 判据 | 参数 |
|---|---|---|
| `has_effect` | `effects[key]` 是 dict | `key` |
| `res_ge` | `effects[res].stacks >= params[ge_field]`（阈值在 **when 条目**上，不是 params 顶层） | `res` + `ge_field` |

⚠️ **`_when_ok` 只认这 2 个 kind**，与 `passive_dmg_mult` 的 8 个完全不重叠 ——
同一个 `{"kind": ...}` 字典在不同动作下能表达的东西不同。**加新谓词时必须查它落在哪个求值器里。**

⚠️ `when` 的 `res_ge` 阈值读的是 **`w[ge_field]`**（when 条目自身，`_when_ok:2157`），
而 `judge` 的 `res_ge` 阈值读的是 **`params[ge_field]`**（`_res_ge_ok:2112`）。
两个同名谓词的阈值来源不同 —— 写声明时看错位置就会恒不满足。

## 两个共用的谓词实现

```python
def _res_ge_ok(actor, judge, params):     # class_mech_proc.py:2103
    res  = judge.get("res") or ""
    ge_field = judge.get("ge_field") or ""
    need = float(params.get(ge_field) or 0)      # ← 阈值在 params（技能 passive dict）
    ...
    return cur >= need

def _has_effect_ok(actor, judge):          # class_mech_proc.py:2120
    key = judge.get("key") or ""
    if not key: return False                      # 零默认值铁律
    return isinstance(actor.get("effects", {}).get(key), dict)
```

`_has_effect_ok` 的语义要点（docstring 原文）：**「过期由引擎结算删除
（schedule 时钟推进 ef.pop），故『在位 = 生效』」**（`:2123-2124`）。
所以 `has_effect` **不能**表达「层数够」——层数要用 `res_ge`。

## 成本判据（第三个独立谓词集）

`bonus.cost` 的 `when` 走的是**引擎侧**的 `_cost_judge_hit`
（`actions.py:217-234`），只认 3 个键，且语义完全不同：

| 键 | 判据 |
|---|---|
| `element` | `info.element` 非空 |
| `mech_prefix: [...]` | `info.mech` 以任一前缀开头 |
| `name_contains: [...]` | `info.name` 含任一子串 |

三条是 **OR**；空 judge = 恒命中。这里**没有 `kind` 字段** —— 别把
`PASSIVE_PROC` 的 judge 形状套到 cost 的 when 上。

## 三套谓词集对照（本页最容易记混的地方）

| 谓词集 | 位置 | 形状 | 求值器 | 首参是 |
|---|---|---|---|---|
| 动作 `judge` | 声明表 + 动作 | `{"kind": ..., 参数}` | 各动作内联 / `_res_ge_ok` / `_has_effect_ok` | `params["judge"]` |
| 渠道 `when` | `EFFECT_RULES[key].channels.*` | `[{"judge": {...}}, ...]` | `_when_ok`（`class_mech_proc.py:2134`） | `params["when"]` |
| 成本 `when` | `actor.bonus.cost` | `[{"mp_pct":..., "judge": {...}}]` | `_cost_judge_hit`（`actions.py:260`） | 技能的 `info` |

⚠️ 渠道 `when` 的 `res_ge` 阈值在 **when 条目自身**；
其余 `res_ge` 阈值都在 **params**（技能 passive dict）。这是最容易写错的一处。

## 相关

- 被动声明 schema → [passive-proc.md](passive-proc.md)
- 渠道 `when` 的完整用法 → [channels.md](channels.md)
- 加新谓词的做法 → [../guides/add-a-passive.md](../guides/add-a-passive.md)
