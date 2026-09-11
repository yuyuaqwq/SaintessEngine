# 效果容器（单 effects）

## 一句话

actor 上只有**一个**状态容器：`actor["effects"]`。增益、减益、DOT、控制、标记、
职业资源、挂敌身条**全是它的条目**。条目的**行为**不在条目里，在
`EFFECT_RULES[key]` 的声明里。

```python
actor["effects"] = {
    "atk_up":  {"stacks": 1, "expire": 12.0, "stat": "atk", "op": "mul", "mult": 1.30},
    "zhan_yi": {"stacks": 4},
    "burn":    {"stacks": 2, "expire": None},
    "stun":    {"stacks": 1, "expire": 3.6, "mode": "skip"},
    "shield":  {"stacks": 5},                       # ← 参考实现里它是个"每层减伤"资源，
                                                    #    真护盾在 shields 容器（不是这个键）
}
```

## 为什么单容器

历史上有四个容器：`state` / `buffs` / `hot` / `debuffs`。它们的边界在代码里靠约定维持，
于是每个新机制都要问「这个东西算 buff 还是 state？」，而且**净化/到期/序列化要写四遍**。
合并成一个容器后（`actors.py:46-48` 的原文：`V 系列统一：四容器 → 单 effects 容器`）：

- 到期只有一处（`schedule._settle_time_effects`，`schedule.py:196-213`）
- 净化只有一处（`effects.act_cleanse`，`effects.py:496-500`）
- 面板折算只有一处（`stats._apply_effects`，`stats.py:40`）
- 序列化天然覆盖（`serialize._serialize_actor` 全字段带走，`serialize.py:53`）
- 「这个效果属于哪一类」不再需要回答——**行为由声明给，不由容器给**

**唯一例外**：`shields`（承伤资源）与 `cooldown`（调度）**故意留在 containers 之外**
（`actors.py:112-115`）。理由：它们不是「状态」，把盾塞进 `effects` 会让净化把盾清掉、
让面板折算把盾值当减伤。见 [actor-model.md](actor-model.md)。

## 条目字段全谱

条目是 **dict**（引擎只读 dict 形态条目，非 dict 会被跳过 ——
例 `schedule.py:200`、`stats.py:55`、`effects.py:384`）。

| 字段 | 谁写 | 谁读 | 含义 |
|---|---|---|---|
| `stacks` | `act_apply`（`effects.py:340/429`）/ `act_consume` / 周期 gain | `_cap_of` clamp、`stats` 折算、`schedule` 周期跳、`_apply_death_guard` | 层数。**允许 float**（小数刻度，如信仰每刻 −0.7） |
| `expire` | `act_apply` | `schedule._settle_time_effects`（`schedule.py:202-206`）、`Battle.act` 控制过期兜底（`battle.py:430-432`）、`actions._consume_hit_buffs` | **绝对时刻**；`None` = 永不到期 |
| `mode` | `act_apply` 控制分支 | `Battle.act` 控制消费（`battle.py:423-446`） | `"skip"` = 整跳行动 / `"no_skill"` = 技能转普攻 |
| `v` | `act_apply` value 型 | **无引擎消费者**（☞ 见下） | 值型数值（如减伤 0.45） |
| `stat` / `op` / `mult` | `act_apply` 快照分支 | `stats._apply_effects`（`stats.py:70-81`） | 面板增益快照 |
| `hit` | `act_apply` hit 子键 | `actions._consume_hit_buffs`（`actions.py:467`） | 出手消费型（`dmg_mult` / `guaranteed_crit` / `bonus_atk_pct`） |
| `period` | **内容侧**直接写入 | `schedule._settle_time_effects`（`schedule.py:239-247`） | 动态周期声明（条目自带优先，回落表声明） |
| `value` | 内容侧（`heal_amp_pct` 等） | `landing._apply_heal_mods`（`landing.py:376`） | 附加数值袋（形态自定，消费方自己解释） |

### `v` 字段的消费缺口

`act_apply` 的值型分支会写 `{"v": 0.45}`（`effects.py:366-368`），并给 `reduce` 额外写
`holder["reduce_left"]`（`effects.py:369-370`）。但：

- `effects["reduce"]["v"]` **没有消费者**（全仓 grep 见 [_selfcheck.md](../_selfcheck.md)）
- `actor["reduce_left"]` 也没有消费者

也就是说 `EFFECT_ACTIONS["reduce"]`（`game/data/battle2_rules.py:488`）走完会
**写一个不会被读的值**。真正生效的减伤是 `stat_scale: {"reduce": ...}` 经
`stats` 写 `st["reduce"]`……而 `st["reduce"]` 同样不被伤害路径消费
（`stats.py:66` 只写 → [_selfcheck.md](../_selfcheck.md)）。
**当前唯一生效的「受击减伤」通道是 `taken_calc` 事件的 `ctx["mult"]` 乘区**
（`landing.py:75-84`）。

## 层数数值口径：int 资源 vs float 刻度

引擎对 `stacks` 是**双口径**的（`effects.py:29-55`）：

| 函数 | 行为 |
|---|---|
| `_norm_stack(v)` / `norm_stack`（`effects.py:46`，S2 公开别名 `:80`） | 写回归一：整值 → `int`；小数 → `round(6)`（清 `10-0.7 → 9.3` 的二进制尾差） |
| `_fmt_stack(v)`（`effects.py:37`） | 日志显示：整值去掉 `.0`（`9.3` 显示成 `9.3`，`10.0` 显示成 `10`） |

**为什么需要 float**：资源可以有非整数速率（信仰每刻 −0.7、磐核每刻 +0.4）。
`apply` 的叠层分支读 `float()`（`effects.py:328`）、`consume` 读 `float()`
（`effects.py:418`）、`schedule` 的 gain 分支 `round(..., 6)`（`schedule.py:346`）。
读侧全用 `float()` 保真，写侧统一过 `norm_stack` 保持「int 资源看起来还是 int」。

## cap 的唯一收敛点

```python
def _cap_of(actor, key):                       # effects.py:58，S2 公开别名 cap_of
    base = int(state_def(key).get("cap") or 0) or 999999
    if base >= 999999:
        return base
    bonus = int(((actor.get("bonus") or {}).get("cap") or {}).get(key, 0) or 0)
    return base + max(0, bonus)
```

语义：

- `EFFECT_RULES[key].cap` 没声明（0）→ **999999**（不设限）
- 声明了 → `基础 cap + actor.bonus.cap[key]`（额外上限，被动 proc 的 `domain: "cap"` 写它）
- `bonus` 为负数时按 0 处理（`max(0, bonus)`）——**只增不减**

读它的地方（都是叠层 clamp）：`act_apply` 叠层分支（`effects.py:329`）、
`schedule` 周期 gain 分支（`schedule.py:343`，且**表声明可被 `period.cap` 覆盖**）。
内容侧的渠道攒取也走它（`class_mech_proc.py` 的 `class_res_channel_gain`）。

## 周期结算（`period`）

`period` 是「按刻重复发生」的声明，形态见 [../reference/effect-rules.md](../reference/effect-rules.md)。
引擎的实现要点（`schedule._settle_time_effects`，`schedule.py:226-362`）：

1. **首次挂不给跳**：第一次看到某 key 时只登记 `dot_next[key] = now + interval`
   （`schedule.py:254-257`，对齐旧引擎的「首跳延迟」）
2. **到点补跳**：`while now >= dot_next[key]`，一次最多补 20 跳（`guard < 20`）防死循环
3. **`dir` 四向**：`damage`（掉血）/ `heal`（回血 + 可选 mana_pct）/ `mana`（回蓝）/ `gain`（给自身叠层加/减，**静默**、clamp `[0, cap]`）
4. **`turns` 限跳**：跳够 `turns` 次就清层（计数器 `dot_jumps`，`schedule.py:351-359`）
5. **`dir="gain"` 不需要 `stacks > 0`**：0 层也要回（游侠精力耗到 0 若被拦将永远回不了，
   `schedule.py:247-250` 注释）
6. **boss 档**：`is_boss` 或 `role == "boss"` 时读 `pct_boss` / `pct_cur_boss`
   （`schedule.py:268` / `:272`）

⚠️ `dot_next` / `dot_jumps` 是 actor 上的运行期辅助字段，会**随存档落盘**（不在
`_STRIP_KEYS` 里）——这是续战行为能对上的原因，但如果你是手写存档要注意它们。

## 显示名 `name`

`EFFECT_RULES[key]["name"]` 不被引擎读（引擎日志用的是控制分支里硬编码的
`f"被【{key}】{turns} 刻"`）。内容侧用它做日志/UI 标签
（例：`class_mech_proc.py:1895` `name = rc.get("name") or rk`）。所以 `name` 是**可选**的。

## 相关

- 条目怎么被写出来（`apply` 五形态） → [declaration-tables.md](declaration-tables.md)
- 规则表的完整字段 schema → [../reference/effect-rules.md](../reference/effect-rules.md)
- 周期结算的时间语义 → [ctb-schedule.md](ctb-schedule.md)
