# 参考：`PASSIVE_PROC` 声明

> **归属**：本能力**不在引擎里**（2026-09-23 起）—— 表与装配器都在**内容侧**（`game/data/battle_rules.py` / `game/services/class_mech_proc.py`）；
> 它的**域声明** `passive_proc` 住在扩展包 `extends/ext_combat/`（`domains.json`，编辑器靠它认识这张表）。
> 数据包要用它：`game.json` 里写 `"depends": ["ext_combat"]`；配套形状（`triggers` / 动词执行器）也在该包（`battle/`）。
> 引擎侧只剩通用件，见 `../architecture/boundaries.md`；下文 `effects.py:NNN` / `actions.py:NNN` 都在 `extends/ext_combat/battle/` 下。
>
> ⚠️ **边界声明**：这张表**不属于引擎**。它在你的内容规则模块里
> （参考实现：**游戏仓 / 奥兰迪亚侧**的 `game/data/battle_rules.py:653`），由**你的装配器**读取并翻译成
> `actor["triggers"]`（参考实现：`game/services/class_mech_proc.py:1974`
> `apply_class_passives`）。引擎侧与扩展包都零代码认识 `PASSIVE_PROC`（它是纯内容表）。
> 下文出现的 proc 名（`poison_cap` / `arcane_constant` / `reflect_bar` …）都是**那只游戏的实例**，不是引擎名词。
>
> 任务导向的写法 → [../guides/add-a-passive.md](../guides/add-a-passive.md)。
> 本页只给字段与装配规则。

## 声明字段

| 字段 | 必填 | 装配器行为（`class_mech_proc.py` 行号） |
|---|---|---|
| `event` | ✅（除非 `domain`） | 逐字作为 `triggers` 的键（`:2065-2067`）。空 → 跳过 |
| `action` | ✅（除非 `domain`） | 作为 `triggers` 条目的 `type`，**不经名词翻译**（`:2035`） |
| `judge` | ✖ | 逐字透传（`:2035`）；动作里读 `params["judge"]` |
| `also` | ✖ | 第二条事件钩子（列表，见下） |
| `agg` | ✖ | 聚合族名；同 `(event, agg)` 的多条暂存后归并单条（`:2069-2070`, `:2097-2100`） |
| `domain` | ✖ | 静态域：`cap` / `cost`（见下），不产生 event 条目 |
| `cap_key` | ✖（`domain="cap"` 用） | 写 `bonus.cap[cap_key]`（`:2010`） |
| `when` | ✖（`domain="cost"` 用） | 条件域（`:2025-2031`） |
| `add` | ✖（`domain="cap"` 用） | 默认增量（技能 `passive.add` 优先，`:2012`） |
| `left_key` / `left_init` | ✖ | 计数器初始化：`effects[left_key] = {"stacks": left_init, "expire": None}`（`:2092-2095`） |
| `bar_field` | ✖ | 字段名 → `{key, gain}`（经 `BAR_INJECT_FIELDS` 解析，`:2051-2062`） |
| **其余键** | ✖ | **除** `event/action/judge/agg/domain/cap_key/when/add/also` 之外的键**全部并入条目**（`:2037-2041`），如 `ctrl` / `res` / `buff_key` / `spd_pct` |

数值参数来自**技能数据的 `passive` dict**：**除 `proc` 外全部并入条目**
（`:2043-2046`），`label` 缺省取技能名（`:2047`）。

> 合并顺序 = 先 `cfg` 的非结构字段，再 `passive` dict → **技能数据覆盖声明表**。
> 所以「数值放技能、结构放表」是这套约定的分工。

## `also`：第二条事件钩子

```python
for _also in (cfg.get("also") or []):
    _d2 = dict(d)                                  # 复制主条目参数
    _d2["type"] = _also.get("action") or d.get("type")
    if _also.get("judge"):  _d2["judge"] = _also["judge"]
    for _k in ("ctrl", "ctrl_any", "res", "left_key", "left_init",
               "cost_field", "buff_key"):
        if _also.get(_k) is not None:  _d2[_k] = _also[_k]
    _ev2 = _also.get("event") or ev
    ...
```
（`class_mech_proc.py:2075-2090`）

⚠️ **可覆盖的键是硬编码白名单**（7 个）：`ctrl` · `ctrl_any` · `res` · `left_key` ·
`left_init` · `cost_field` · `buff_key`。写别的键**不报错也不生效**。
要传其他参数，放进技能数据的 `passive` dict（它进主条目并被 `dict(d)` 复制过去）。

## `domain`：两个静态域

### `domain = "cap"` — 资源上限修正

```python
"poison_cap": { "domain": "cap", "cap_key": "poison" },        # 淬毒之心
"hunt_mark_cap": { "domain": "cap", "cap_key": "hunt_mark" },  # 追猎者
```

写入：`bonus.cap[cap_key] += add`（`add` 取 `passive.add` 或 `cfg.add`，**只累加正数**，
`:2008-2018`）。消费者是扩展包 `effects._cap_of`（`extends/ext_combat/battle/effects.py:77`）。

⚠️ `cap_key` 缺省 = `proc` 名本身（`:2010`）。所以 `proc` 名 ≠ 资源 key 时必须写 `cap_key`。

⚠️ **`cap` 域不 `continue`**：声明里同时有 `event` 时会继续走事件装配
（原文「双通道声明 → 不 continue，fall through」，`:2019`）。
真实样例 `soul_mark_cap` / `poison_cap_up` 就是双通道。

### `domain = "cost"` — 消耗折扣

```python
"arcane_constant": { "domain": "cost",
                     "when": [{"judge": {"mech_prefix": ["arcane"]}}] },
```

写入（`:2020-2034`）：

| 情况 | 写入 |
|---|---|
| 有 `when` | `bonus.cost["when"].append({**when[0], "mp_pct": 原值 + passive.mp_mult})` |
| 无 `when` 且 `mp_mult > 0` | `bonus.cost["mp_pct"] += passive.mp_mult` |

⚠️ 只读 `passive.mp_mult` 一个字段（**不读 `mp_flat` / `res`**）。消费者是扩展包
`actions._skill_pay_of`（`extends/ext_combat/battle/actions.py:293`）。
`cost` 域因为无 `event`，下方 `if not d.get("type"): continue` 自然拦截（`:2063-2064`）。

## `agg`：聚合族

同 `(event, agg)` 的多条声明暂存，循环后归并成**一条**（`:2097-2100`）。
归并函数 `_merge_agg_entry(agg, entries)`（`:2164-2198`）：

| `agg` | 归并规则 |
|---|---|
| `counter`（唯一已实现） | `counter_chance` 条目：`chance = max(...)`、`mult = min(...)`；`counter_up` 条目：`chance += chance_add`、`mult *= (1+dmg_add)` |
| 其他 | **返回 `None` → 整族被丢弃**（`:2198`） |

终值形态：`{"type": "passive_counter", "chance": min(chance, 0.9), "atk_pct": mult, "label": "A+B"}`。
缺字段（`chance<=0` 或 `mult<=0`）= 该条不参与（`零默认值铁律`，`:2183-2184`）。

## `bar_field`：从技能字段取推条量

```python
"reflect_bar": { "event": "on_taken", "action": "passive_reflect_bar",
                 "bar_field": "shaken_gain" },
```
（`game/data/battle_rules.py:821-826`）

装配器：`BAR_INJECT_FIELDS["shaken_gain"]` → `{"key": "shaken", "per_hit": True}`；
再读技能数据的 `info["shaken_gain"]` 作为数值 → 写进条目 `{"key": "shaken", "gain": N}`
（`:2051-2062`）。**数值单源 = 技能数据字段**，不在被动 dict 里重填。

## 参考实现统计（写文档时的 grep 结果）

- `PASSIVE_PROC` 共 **42** 条声明（`game/data/battle_rules.py:653-920`）
- 顶层字段出现次数：`event` 39 · `action` 39 · `judge` 22 · `also` 7 · `domain` 5 ·
  `cap_key` 4 · `agg` 2 · `when` 1 · `buff_key` 5
- `event` 用到的事件（10 个）：`act_cast` · `dmg_calc` · `dot_calc` · `heal_calc` ·
  `on_death` · `on_kill` · `on_taken` · `taken_calc` · `time_advance` · `turn_start`
- `also.event` 用到（6 个）：`act_cast` · `act_done` · `attack_hit` · `skill_hit` ·
  `taken_calc` · `turn_start`
- `action` 共 **24** 个不同动作：`passive_bar_decay_half` · `passive_cc_break` ·
  `passive_cond_crit` · `passive_counter` · `passive_ctrl_extend` · `passive_dmg_mult` ·
  `passive_dot_mult` · `passive_element_core_crit` · `passive_heal_overflow_shield` ·
  `passive_kill_gain` · `passive_lian_duan_soft` · `passive_lifesteal_buff` ·
  `passive_low_hp_core` · `passive_mark_enhance` · `passive_melody_duet` ·
  `passive_overflow_shield` · `passive_poison_spread` · `passive_poison_weaken` ·
  `passive_reflect_bar` · `passive_res_gain_turn` · `passive_revive_berserk` ·
  `passive_revive_guard` · `passive_shadow_buff` · `passive_taken_reduce`
  （全部注册在 `game/services/class_mech_proc.py`）
- `domain` 取值：`cap` · `cost`；`agg` 取值：`counter`

## `MECH_CASH` vs `PASSIVE_PROC` vs → 扩展包执行端

```
技能数据 kind="被动" + passive.proc ──┐
                                     ├─→ PASSIVE_PROC[proc] ──→ 装配器 ──→ triggers
PASSIVE_PROC 声明（event/action/judge）┘                                 │
                                                                        ↓
技能数据 mech ─→ MECH_CASH[mech] ──→ 装配器 ──→ triggers ──→ ext_combat fire()
                                                                        ↓
                                        EFFECT_ACTIONS[名词] ──→ 动词执行器
```

**扩展包 `ext_combat` 眼里只有最后一步**：`triggers` + `EFFECT_ACTIONS` + `ACTION_HANDLERS`。
前三层全在你的仓库里 —— 这是这套设计的可移植性来源，也是它的成本
（装配器要你自己维护，错了不报错）。

## 相关

- 任务导向的写法与坑 → [../guides/add-a-passive.md](../guides/add-a-passive.md)
- judge 谓词清单 → [judges.md](judges.md)
- 事件时机 → [events.md](events.md)
