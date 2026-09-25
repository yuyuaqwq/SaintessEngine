# 指南：写一个机制动作

> **归属**：本页主体是**内容侧扩展动词**（`register_action` 注册的动作在游戏仓）；
> 它依赖的配套形状（`effects` / `actions` / `landing` / `effect_triggers`）2026-09-23 起住在扩展包 `extends/ext_combat/`（`battle/`）。
> 数据包要用它们：`game.json` 里写 `"depends": ["ext_combat"]`；下文 `effects.py:NNN` / `actions.py:NNN` / `landing.py:NNN` / `schedule.py:NNN` 都在 `extends/ext_combat/battle/` 下。

适用：你要加一个**引擎不认识的行为**（「受击时反弹」「每层资源加伤害」「血量低于 X 时变身」）。

入门版见 [../getting-started/first-mechanic.md](../getting-started/first-mechanic.md)（动词 + 名词 + triggers）。
本页补三件进阶事：**参数约定**、**judge 谓词**、**乘区型钩子**。

## 决策：写成动词，还是写成声明？

先问自己一句：**这个机制能不能用已有的动词 + 参数凑出来？**

| 能不能 | 做法 |
|---|---|
| 能（加个数值 / 挂个层 / 上个控制 / 加个盾） | **只写声明**（`EFFECT_ACTIONS` + `EFFECT_RULES`），不写代码 |
| 不能（有分支逻辑 / 要读事件数值 / 要 roll 概率 + 多步副作用） | 写一个扩展动词 |

N3 之后战斗包（`ext_combat`）只留 8 个动词，其余全走扩展注册 —— 这个比例本身就是答案：
《奥兰迪亚》（游戏仓侧的参考实现）在内容侧注册了 **70+** 个扩展动词（`register_action` 在
`game/services/*.py` 里被调用 80 余次），但**没有一个是引擎改出来的**。

## 动作签名与四条铁律

```python
@register_action("my_verb")                    # effects.py:96
def my_verb(battle, caster, target, params, logs):
    ...
```

签名固定 `fn(battle, caster, target, params, logs)`（`effects.py:92`）。
四条铁律：

1. **落地一定走 `landing`**
   - 伤害：`landing.deal_damage(battle, source, target, amount, logs, dmg_kind=..., defend_reduce=..., element=...)`（`landing.py:28`）
   - 治疗：`landing.heal_actor(battle, target, amount, logs, source=None, label="")`（`landing.py:435`）
   - 自己 `target["hp"] -= dmg` 会丢掉护盾吸收、死亡判定、濒死保护、`on_taken`/`on_kill` 事件
2. **缺字段 = 无行为**（零默认值）。所有参数用 `params.get(...)`，判 `<= 0` 就 `return`。
   不要写 `params.get("pct", 0.1)` 这种「贴心默认」——参考实现（游戏仓内容侧）里所有扩展动作都没这么干
3. **异常不要抛**：`apply_effects` 会吞掉异常并跳过该动作（`effects.py:175-179`），
   但如果你**希望**异常可见（开发期），就让它抛出来再自己看日志 —— 别用裸 `except: pass`
   把错误吃掉
4. **日志就是 `logs.append(...)`**。引擎没有日志等级；格式惯例是 `emoji + 一句话`，
   数值用 `effects._fmt_stack`（`effects.py:40`）处理 int/float 观感

## 参数从哪里来：`params` 的三层合并

`apply_effects` 在调你的动词前做了合并（`_merge_params`，`effects.py:156`）：

```
params = dict(效果 dict)                      ← 声明方写的一切
for k, v in 映射动作.items():
    if k == "action": continue
    if k not in params or params[k] is None:  ← 调用方优先
        params[k] = v
```

所以参数的优先级是「**调用方显式 > 映射默认**」。举例（`first-mechanic` 里的血契）：

```python
"blood_pact": [{"action": "pact_heal", "pct": 0.05, "on": "caster"}]
```

技能数据里如果写 `{"type": "blood_pact", "pct": 0.10}`，就会覆盖成 10%。

另外两种参数注入：

| 来源 | 说明 |
|---|---|
| `eff["chance"]` | `apply_effects` 的通用概率 roll（`effects.py:184-190`）。`None` = 恒触发；`0.4` = 40% 才执行 |
| `_owner` | 事件总线注入的**声明者**（`effect_triggers.py:103-106`）。`params.get("_owner")` 拿宿主 —— 「谁带的这个装备」用它 |

事件数值（`dmg` / `heal` / `amount` / `is_crit` / `overflow` / `source`）**不在 params 里**，
在 `battle._fire_ctx`：

```python
ctx = getattr(battle, "_fire_ctx", None) or {}
attacker = ctx.get("source")
```
（`game/services/class_mech_proc.py:884` 与 `game/services/battle_we_procs.py:38-46` 的用法）

## 乘区型钩子：不改引擎就改数值

如果要「条件增伤 / 条件减伤」，不要重写伤害公式 —— 用四个乘区事件的
`ctx["mult"]`：

| 事件 | 谁读回 | 语义 | 包内点位（`extends/ext_combat/battle/`） |
|---|---|---|---|
| `dmg_calc` | 攻击方总伤 | ×mult 增伤 | `actions.py:436-443` |
| `taken_calc` | 承伤前 | ×mult 减伤（<1）或增伤（>1） | `landing.py:81-92` |
| `heal_calc` | 治疗量落地前 | ×mult 治疗增幅 | `actions.py:674-744` |
| `dot_calc` | DOT 每跳 | ×mult DOT 增伤 | `schedule.py:583-599` |

写法（实测可用的最小骨架）：

```python
@register_action("my_cond_mult")
def my_cond_mult(battle, caster, target, params, logs):
    ctx = getattr(battle, "_fire_ctx", None)
    if ctx is None:
        return
    owner = params.get("_owner") or ctx.get("actor") or caster
    # …你的判据…
    if not 命中:
        return
    ctx["mult"] = float(ctx.get("mult", 1.0) or 1.0) * (1.0 + float(params.get("mult") or 0))
```

三条注意：

- `ctx["mult"]` 初值由引擎置 1.0（`actions.py:439`），**累乘**多个源
- `_fire_ctx` 是**单槽覆盖式**：只在你自己那次 `fire` 的同步栈里有效
- 乘区在 `dmg_calc` 里改的是**已经算完的总伤**（多段之和，`actions.py:427-430` 之后）

## judge 谓词：把判据写成数据

「条件」往往长得很像：资源 ≥N、目标带某标记、目标破绽条 ≥N。这类判据在内容侧是
**声明化**的：`PASSIVE_PROC` 的 `judge` 字段 + 扩展动作里的 `judge.kind` 分派。

```python
"zhan_yi_full_reduce": {                      # game/data/battle_rules.py:738
    "event": "taken_calc", "action": "passive_taken_reduce",
    "judge": {"kind": "res_ge", "res": "zhan_yi", "ge_field": "stacks"},
    "also": [{"event": "turn_start", "action": "passive_cc_clear",
              "judge": {"kind": "res_ge", "res": "zhan_yi", "ge_field": "stacks"},
              "ctrl": "stun"}],
},
```

**judge 与动作是一对耦合**：动作必须认识自己声明的 `judge["kind"]`。
完整谓词清单（按动作分域）→ [../reference/judges.md](../reference/judges.md)。

写新 judge 的约定（`class_mech_proc.py` 里的通行做法）：

- **未知 kind = fail-closed**：`passive_taken_reduce` 里 `else: return`（`class_mech_proc.py:1001-1002`），
  注释原话「渠道条件写错时宁可漏攒，不可静默攒错」
- 但**判据不命中的 kind = 正常不生效**（例 `target_mark_any` 目标没标记 → 不加成）
- 阈值字段名从 `params` 读（`ge_field` 是**字段名**不是值）：
  `params.get(judge["ge_field"])`（`class_mech_proc.py:939`、`_res_ge_ok:2112`）

## 装配：把声明挂到 actor

三种挂点，按「什么时候知道」选：

| 时机 | 挂点 | 例子 |
|---|---|---|
| 开战前（按已学技能/已装备） | 命令层开战仪式调你的装配函数，写 `actor["triggers"]` | `apply_class_mech(actor)`（`class_mech_proc.py:2201`） |
| 战斗中途（某个效果生效时） | 在动词里直接改 `triggers`（会立刻生效，因为 fire 每次都现读） | 内容侧「进入守护姿态时挂反击 trigger」 |
| 一次性行动 | `Battle.action_override`（`battle.py:518`） | `use_item` 类自定义行动 |

装配器的最简形态（实测跑通）：

```python
def apply_my_mechanics(actor):
    trig = actor.setdefault("triggers", {})
    trig.setdefault("attack_hit", []).append({"type": "blood_pact"})
```

两条装配纪律：

- **幂等**：开战仪式可能被调多次；用 `setdefault` + 去重（内容侧对每个族都有
  `if not any(...)` 检查，如 `class_mech_proc.py:2289`）
- **「学什么挂什么」**：只扫 actor 实际拥有的技能/装备，别无条件挂（否则零噪音变成噪音。
  原文：`class_mech_proc.py:2281-2282`）

## 顺序契约（容易被忽略的坑）

同一个事件上挂多个动作时，**执行顺序 = 声明 list 的顺序**，而顺序有时决定正确性：

- 内容侧的旋律装配把基础叠层**插到 `act_cast` 首位**，因为被动族吟唱后置段要读叠层后的强度
  （`class_mech_proc.py:2291-2293`）
- 挂敌身条的「推条」必须早于「延长破防窗口」（`battle_bar_procs.apply_bar_procs` 头部 insert 注释）

如果你的动作依赖另一个动作的结果，**显式注释这个顺序依赖**，否则后人插一条就悄悄坏掉。

## 相关

- 事件怎么选（哪个事件在什么时候 fire） → [../reference/events.md](../reference/events.md)
- judge 谓词清单 → [../reference/judges.md](../reference/judges.md)
- 写测试 → [testing.md](testing.md)
