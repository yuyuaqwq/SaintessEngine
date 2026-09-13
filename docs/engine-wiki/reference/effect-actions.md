# 参考：`EFFECT_ACTIONS` 名词→动词映射

`EFFECT_ACTIONS` = 「游戏名词 → 引擎动词动作序列」的翻译表。它**不是引擎文件**；
引擎通过 `config.set_config("effect_actions", ...)` / `load_game_rules(module)` 读它，
读点在 `effects.resolve_actions`（`effects.py:135`）。

## 表格格式

```python
EFFECT_ACTIONS = {
    "名词":  [{"action": "动词", ...默认参数}, ...],   # 形态 1：列表
    "名词2": {"action": "动词", ...默认参数},           # 形态 2：单 dict（等价于单元素列表）
}
```

解析规则（`effects.resolve_actions`，`effects.py:135-150`）：

| 表里的形态 | 返回 |
|---|---|
| `list` | 原样返回 |
| `dict` | `[dict(mapped)]` |
| 没有该键，但名字是已注册动词 | `[{"action": <名字>}]`（动词直通） |
| 都没有 | `[]` → 调用方 `continue`（**静默 no-op**，`effects.py:191-192`） |

参数合并（`_merge_params`，`effects.py:153-162`）：**调用方显式参数优先**，
映射里的值只补 `缺失/None`。`action` 键本身不参与合并。

`eff["chance"]`（概率）由 `apply_effects` 消费（`effects.py:183-189`），与映射无关。

## 引擎动词全集（8 个）

注册在 `effects.py`（`@register_action`），这是**引擎能力边界**：

| 动词 | 注册行 | 参数要点 |
|---|---|---|
| `apply` | `effects.py:326` | 五形态按参数分流：`mode`→控制 / `op=add\|set`+无 `stat`→叠层 / `value`\|`pct_from_mech_val`→值型 / `stat`+`mult`→面板快照 / `hit`→出手消费 / 无→纯状态 |
| `consume` | `effects.py:490` | `key` + `amount`（不足则**不扣**并写提示，`effects.py:500-502`） |
| `shield` | `effects.py:517` | `key`（缺省 `"buff"`）/ `value` \| `pct` \| 缺省 20% max_hp / `turns`（缺省 3；`>=999` 或 `forever` = 永久）/ `halve` |
| `cleanse` | `effects.py:563` | 遍历目标 `effects`，按 `EFFECT_RULES[key]` 的 `period` \| `on=="target"` \| `cleanse` 三判据清 |
| `cleanse_all` | `effects.py:591` | 同上，`target or caster` |
| `heal` | `effects.py:599` | `pct`（max_hp 比例）/ `missing_pct`（已损比例）/ `value`；`info.hp_pct` 兜底 |
| `interrupt` | `effects.py:636` | 清 `target["charging"]`，fire `interrupt` |
| `damage` | `effects.py:654` | `value` / `pct`（`pct_max_hp` 别名）/ `kind`；`on=target`（缺省）或 `on=caster`（自伤/反伤） |

已删除的旧动词（V4 收敛）：`control` / `buff` / `state_add` / `state_spend` / `state_set`
→ 并入 `apply` / `consume`。**表里再出现这些名字 = 静默 no-op**（原文警告见 `effects.py:17-18`）。

## 扩展动词：`register_action` 是另一半能力面

引擎动词只有 8 个，其余全在内容侧注册。游戏仓参考实现注册了 **70+** 个：

```bash
grep -rho 'register_action("[^"]*")' game/services/*.py | sort -u | wc -l
```

按前缀分族（便于理解命名约定）：

| 族 | 前缀 | 例子 |
|---|---|---|
| 属性/控制/通用装备特效 | `we_` | `we_affix_dot` · `we_dmg_mult_cond` · `we_shield_taken` · `we_reflect` |
| 职业机制兑现 | `mech_cash_` | `mech_cash_dmg_mult` · `mech_cash_clear` · `mech_cash_fury_enter` |
| 被动 proc | `passive_` | `passive_dmg_mult` · `passive_taken_reduce` · `passive_counter` |
| 职业资源/形态 | `class_` | `class_res_channel_gain` · `class_faith_load_tier` · `class_melody_act` |
| 挂敌身条 | `bar_` | `bar_gain` · `bar_time_settle` · `bar_phase_preserve` |
| 条件倍率 | （无统一前缀） | `skill_cond_mult` |

**注册时机**：模块级 `@register_action` 装饰器 + 模块末尾 `install()` 幂等守卫
（例 `class_mech_proc.py:2379`）。表本身是全局单表（`effects.ACTION_HANDLERS`），
所以「谁先 import 谁注册」——重复注册同名动词会**静默覆盖**。

## 参考实现的 51 个名词（可粘贴起点）

以下全部来自 `game/data/battle_rules.py:421-495`（真实键，非示例）。
标注的含义：`→` 后是它映射到的动词。**除 `class_*` 三个外都是引擎动词**。

### 控制类（8）

```python
"stun":      [{"action": "apply", "key": "stun", "on": "target", "turns": 1}],
"freeze":    [{"action": "apply", "key": "freeze", "on": "target", "turns": 1}],
"sleep":     [{"action": "apply", "key": "sleep", "on": "target", "turns": 1}],
"silence":   [{"action": "apply", "key": "silence", "on": "target", "turns": 2}],
"slow":      [{"action": "apply", "key": "spd_down", "on": "target", "turns": 2, "mode": "skip"}],
"spd_down":  [{"action": "apply", "key": "spd_down", "on": "target", "turns": 2, "mode": "skip"}],
"cc_immune":     [{"action": "apply", "key": "cc_immune"}],
"purify_immune": [{"action": "apply", "key": "cc_immune"}],
```

注意 `stun` 等的 `turns` 由**动作参数**给（技能显式 `cc_turns` 可覆盖 —— 见下「技能数据侧」），
`mode` 走 `EFFECT_RULES[key].consume.mode` 查表（`effects.py:350-353`）。

> ### ⚠️ 自己加控制名词时的三个静默失效点（第三方第一版必踩）
>
> 写自己的控制类 `EFFECT_ACTIONS` 条目时，下面每一处都会**不打日志地失败**：
>
> | 漏了什么 | 引擎行为 | 代码 |
> |---|---|---|
> | `key`（或 `tag` / `mech`）全缺 | `if not key: return` → 效果**完全不施加** | `effects.py:315-308` |
> | `turns` ≤ 0 / 不写 | 控制分支 `if turns <= 0: return` → **不施加**（`turns` 不会被默认值兜底） | `effects.py:301-303` |
> | `on` 不写 | 缺省值是 **`"caster"`**（`params.get("on", "caster")`）→ **把控制挂到自己身上**（晕自己） | `effects.py:343, 300` |
>
> 正确写法 = 三个都给：
>
> ```python
> "my_taunt": [{"action": "apply", "key": "my_taunt", "on": "target", "turns": 2}],
> ```
>
> 另外控制分支要求 `target` 非空（`if not target: return`），且 `key` 必须在 `EFFECT_RULES` /
> `state_def` 里能查到 `consume.mode`（否则 `mode is None` → 落到叠层分支，语义完全不同）。


### 属性增益（写 caster，数值查 `EFFECT_RULES[key].panel`）

```python
"atk_up":    [{"action": "apply", "key": "atk_up"}],
"dodge_buff":  [{"action": "apply", "key": "dodge_up"}],
"spd_buff":    [{"action": "apply", "key": "spd_up"}],
"crit_hit_buff": [{"action": "apply", "key": "crit_up"}],
"atk_all":   [{"action": "apply", "key": "atk_up"}],        # 团队增益 → 自身有效键
"def_all":   [{"action": "apply", "key": "def_up"}],
"matk_all":  [{"action": "apply", "key": "matk_up_strong"}],
"crit_all":  [{"action": "apply", "key": "crit_up"}],
"spd_all":   [{"action": "apply", "key": "spd_up"}],
"atk_matk_all": [{"action": "apply", "key": "atk_up"},
                 {"action": "apply", "key": "matk_up"}],     # 一条名词 → 两个动词（序列）
```

`atk_matk_all` 是「一个名词映射成多个动作」的样例。

### 药水/食物别名（18，纯面板别名）

```python
"buff_atk"/"buff_atk_big"/"buff_atk_small"/"buff_atk_food"/"buff_def"/"buff_def_food"/
"buff_spd"/"buff_spd_small"/"buff_spd_food"/"buff_crit"/"buff_crit_small"/"buff_crit_big"/
"buff_crit_food"/"buff_matk"/"buff_matk_strong"/"buff_matk_food"/"food_spd_up_small"
```
全部 `[{"action": "apply", "key": <对应 EFFECT_RULES key>}]`。
这一族的价值在于示范「**一个名词可以只是一条 key 别名**」——
加道具 buff 不需要写代码。

### 一次性出手消费（3）

```python
"next_atk_up":    [{"action": "apply", "key": "next_atk_up",   "hit": {"dmg_mult": 1.50}}],
"buff_phys_next": [{"action": "apply", "key": "buff_phys_next","hit": {"dmg_mult": 1.40}}],
"stealth":        [{"action": "apply", "key": "stealth",       "hit": {"guaranteed_crit": True}}],
```

`hit` 子键由 `actions._consume_hit_buffs` 消费（`actions.py:470-512`），
出手时**消费并删除**该条目。

### 战斗核心（治疗 / 置值 / 打断 / 减伤 / 盾 / 净化）

```python
"heal_self":   [{"action": "heal", "on": "caster"}],
"heal_pct":    [{"action": "heal", "on": "caster"}],
"regen":       [{"action": "heal", "on": "caster"}],
"stacks_set":  [{"action": "apply", "op": "set", "on": "target"}],
"interrupt":   [{"action": "interrupt"}],
"reduce":      [{"action": "apply", "key": "reduce", "pct_from_mech_val": True}],
"shield_self": [{"action": "shield", "halve": False}],
"shield":      [{"action": "shield", "halve": True}],
"cleanse":     [{"action": "cleanse"}],
"cleanse_all": [{"action": "cleanse_all"}],
```

⚠️ **参数故意缺省**：`stacks_set` 没给 `key`（靠调用方 `mech`/`tag` 兜底，
`effects.py:344`）；`heal_self` 没给 `pct`（靠 `info.hp_pct`，`effects.py:620`）；
`shield` 没给 `value`（缺省取 `max_hp × 20%`，`effects.py:538`）。
这些是「零默认值 + 调用方优先」的取舍：**能省的都省，但缺了就是无行为**。

### 三个映射到内容侧扩展动词

```python
"shadow_dance": [{"action": "class_shadow_dance_enter"}],
"stance_guard": [{"action": "class_stance_guard_enter"}],
"guard_stance": [{"action": "class_guard_stance_enter"}],
```

它们把「进入某个形态」交给内容侧装配器（写 `effects` 条目 + 挂触发器）。
**这就是第三方加自己形态的入口**：注册一个 `my_*_enter` 动词，表里指过去。

## 技能数据侧：`mech` 字段的分派（另一条翻译路）

技能 dict 的 `mech` / `mech2` 不查 `EFFECT_ACTIONS` 的常规路径，而是先过
`effects.effects_from_skill`（`effects.py:216`）→ `_mech_to_effect`（`effects.py:235`）：

```python
cfg = state_def(mech)                      # 查 EFFECT_RULES
if _is_stack_resource(cfg):                # 有 stat_scale/debuff_scale/period/dot/
    return {"type": "apply", "op": "add",  #   on_threshold/guard_hp_pct，或 cap>1
            "key": mech, "amount": mval,
            "on": "target" if cfg.get("on") == "target" else "caster",
            "info": info}
# 否则：保留名词，交给 EFFECT_ACTIONS 翻译
_eff = {"type": mech, "stacks": mval, "mech": mech, "info": info}
if info.get("cc_turns"):     _eff["turns"] = int(info["cc_turns"])   # 显式刻数
if info.get("mech_chance") is not None: _eff["chance"] = float(...)  # 概率
```

`_is_stack_resource` 的判据（`effects.py:240-255`）：

```python
for f in ("stat_scale", "debuff_scale", "period", "dot",
          "on_threshold", "guard_hp_pct"):
    if cfg.get(f): return True
if int(cfg.get("cap") or 0) > 1: return True
return False
```

**这个判据决定了「技能 mech 走叠层还是走名词」**，是加新 mech 时最容易踩的一点：
你的 key 一旦有 `stat_scale`，它就再也不会走 `EFFECT_ACTIONS`。

`cc_turns` 的注释值得逐字读（`effects.py:253-257`）：

> 技能显式 `cc_turns` 才带 `turns`（覆盖 `EFFECT_ACTIONS` 默认刻数）；缺省不写 `turns`
> —— 否则恒 `turns=0` 覆盖默认致控制 0 刻不施加（盾击·誓「眩晕 1 刻」bug）

## 缺口：20 个 `effect=` 名词没有映射（静默 no-op）

> ## ⚠️ 2026-09-11 收尾：**已全部处置**（本节保留为取证原貌）
>
> 当天逐项复跑后处置结果：
>
> - **19 项已实装**（映射补齐 + 内容侧装配层 `game/services/battle_team_procs.py`）：
>   `shield_all` / `shield_block` / `shield_all_reduce` / `reduce_shield_all` / `arcane_shield` /
>   `reduce_all` / `dodge_reduce_all` / `arcane_matrix` / `hunt_team_dmg` / `star_lock` / `vuln` /
>   `all_stat_cc` / `stealth_cc` / `disengage_dodge` / `protect` / `block_reflect` /
>   `element_switch` / `arcane_field` / **`def_up`**（只需补一行映射）。
> - **1 项是误报**：`taunt`（嘲讽）**早已实装** —— 命令层 `game/commands/instance_router.py:260-273`
>   直读技能配置（`hate_taunt_mult` / `hate_lock_turns`）实现仇恨×N + 强制锁 N 刻，
>   不走 `EFFECT_ACTIONS`。原判据只看本表，属**单通道判定**的误报。
> - ★ 修复过程中发现两个**引擎侧真问题**（均已修 + 出 diff）：
>   ① 引擎增益管线 `actions._do_buff` 把 `effect=` 只作用于**施法者自己** →
>      「全队」技能在多人副本/PVP 下与 desc 不符（内容侧用 `team_apply` 面幅解决，引擎零改动）；
>   ② `landing`/`actions` 里 3 处 `.get("mult", 1.0) or 1.0` —— `0.0` 是 falsy 被吞成 `1.0`，
>      **0 乘区永远失效**（格挡/无敌帧类效果做不出来），已改为「仅 `None` 回落 1.0」。
> - 详见游戏仓 `docs/REFACTOR_v181_team_effects_plan.md` §七（落地记录 + 口径 + 验收 47/47）。

`game/data/skills.py`（玩家技能表）里出现但这些名词**既不在 `EFFECT_ACTIONS`
也不是引擎动词** → `resolve_actions` 返回 `[]` → `apply_effects` 静默跳过：

| 名词 | 出现行（`game/data/skills.py`） |
|---|---|
| `disengage_dodge` | `:570` |
| `shield_all` | `:993`, `:1137`, `:3509` |
| `shield_block` | `:1020` |
| `taunt` | `:1032` |
| `protect` | `:1191`, `:1292` |
| `reduce_all` | `:1204`, `:1305`, `:2426`, `:2497`, `:3355` |
| `shield_all_reduce` | `:1327` |
| `arcane_shield` | `:1504` |
| `element_switch` | `:1519` |
| `arcane_matrix` | `:1643` |
| `arcane_field` | `:1654` |
| `star_lock` | `:1970` |
| `dodge_reduce_all` | `:2060` |
| `hunt_team_dmg` | `:2159` |
| `vuln` | `:2918` |
| `stealth_cc` | `:2986` |
| `block_reflect` | `:3298` |
| `reduce_shield_all` | `:3630` |
| `all_stat_cc` | `:4064` |
| `def_up` | `:4195` |

**正好 20 个**（去重后）。另外 `game/data/monster_mods.py` 与 `game/data/instances.py`
还有 4 个未声明名词（`freeze_self` / `mortal_wound` / `stacks_clear` / `vulnerable`）。

⚠️ 其中 `def_up` **在 `EFFECT_RULES` 里有面板声明**（`panel: atk→def ×1.45`）
但**不在 `EFFECT_ACTIONS` 里** → 所以它不走 `apply`，声明白写。
这是「表里有 rule、没有 action 映射」的典型不一致。

**核对方法**（可复现）：

```python
import ast, re
rules = ...  # 读 game/data/battle_rules.py 的 EFFECT_ACTIONS
verbs = set(re.findall(r'@register_action\("([^"]+)"\)', open('saintess_engine/battle/effects.py').read()))
effs = set(re.findall(r'[\'"]effect[\'"]\s*:\s*[\'"]([^\'"]+)[\'"]', open('game/data/skills.py').read()))
print(sorted(e for e in effs if e not in rules and e not in verbs))
```

完整清单与背景 → [../_selfcheck.md](../_selfcheck.md)。

## 相关

- 声明系统的原理 → [../concepts/declaration-tables.md](../concepts/declaration-tables.md)
- 规则表字段 → [effect-rules.md](effect-rules.md)
- 扩展动词怎么写 → [../guides/write-a-mechanic.md](../guides/write-a-mechanic.md)
