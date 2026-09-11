# 事件总线

## 一句话

引擎在固定点位调用 `fire(battle, event, ctx, logs)`；总线遍历所有存活 actor，
把 `actor["triggers"][event]` 里的效果声明交给效果系统执行。
**事件名是引擎协议（封闭集合 `EVENTS`），事件里挂什么是你的游戏名词。**

入口：`effect_triggers.fire`（`effect_triggers.py:57`）；事件名全集：`EVENTS`（`effect_triggers.py:48`）。

## 为什么要有事件总线

没有它的时候，加一个「暴击时回蓝」要改 `actions.py`；加一个「死亡时爆炸」要改 `landing.py`。
加 50 个机制 = 50 处 if 分支散落在引擎里，而且**每加一个都要回归整个战斗**。

事件总线的做法：引擎只负责**在语义正确的时刻喊一声**，喊话内容（ctx）标准化；
效果挂不挂、挂谁身上，全在数据里。原文（`effect_triggers.py:5-11`）：

> 所有「事件匹配触发」型效果声明何时触发，引擎在固定点 fire(event, ctx)，
> 不再为某个具体效果手写 if 分支。

## `fire()` 的四个语义

### 1. 事件名白名单

```python
if not event or event not in EVENTS:
    return                       # 静默忽略，不抛
```
（`effect_triggers.py:64-65`）

写错事件名不会报错，只是永不触发。`EVENTS` 是**单行元组**，原因是覆盖率工具按行 trace，
多行续行会永久漏记（`effect_triggers.py:46-47` 注释）。

### 2. `logs` 必须显式传

```python
if logs is None or not getattr(battle, "sides", None):
    return
```
（`effect_triggers.py:66-68`）

`logs` 可以是空 list，但不能是 `None`。没有 `sides` 的「非战斗上下文」里调用是安全的空转。

### 3. subject 过滤 —— 只处理事件主体的声明

```python
subject = ctx.get("actor")           # 事件主体（谁回合/谁施法/谁受击/谁被治疗）
...
for acts in battle.sides.values():
    for a in acts:
        if subject is not None and a is not subject:
            continue
        if not actor_alive(a) and a is not subject:
            continue
```
（`effect_triggers.py:77` 与 `:83-90`）

**为什么**：如果不过滤，同阵营其他人身上挂的装备特效会被全局广播误触发。
`None` = 无主体事件（典型：`battle_start` 全体触发）。

两个例外要注意：

- **主体死亡也执行**：`on_death` 的死者自己的声明照样跑（死亡遗言类效果）。
  判据是 `a is subject` 那一支。
- **有些事件故意不带 `actor`**：`act_done` 只放 `ctx["acted"]`，让效果侧自己判敌我
  （`battle.py:477-479` 注释：`randuin`/`ice_vein` 靠它监听「敌对 actor 行动」叠减速）。

### 4. `_owner` 注入

```python
_e2 = dict(_e); _e2.setdefault("_owner", a)
```
（`effect_triggers.py:99-102`）

每个效果 dict 的**副本**里被塞进 `_owner = 声明者**。扩展动词可以用它自查归属
（例：`passive_counter` 用 `params.get("_owner")` 找反击的宿主，
`game/services/class_mech_proc.py:881`）。用 `setdefault` 意味着你显式写了 `_owner`
就不会被覆盖。**注入的是副本**，不会污染 `actor["triggers"]` 里的原始声明。

### 5. ctx 暂存到 `battle._fire_ctx`

```python
ctx.setdefault("_event", event)
battle._fire_ctx = ctx
```
（`effect_triggers.py:81-82`）

这是**乘区型扩展动作改数值的通道**：内容侧动作把 `battle._fire_ctx["mult"]` 乘一下，
引擎在该事件的 fire 返回后读回：

```python
_fire(battle, "dmg_calc", _fctx, logs)
_m = float((getattr(battle, "_fire_ctx", {}) or {}).get("mult", 1.0) or 1.0)
if _m != 1.0:
    total = max(1, int(total * _m))
```
（`actions.py:416-422`，同款出现在 `landing.py:75-84` 的 `taken_calc`、
`actions.py:642-702` 的 `heal_calc`、`schedule.py:281-291` 的 `dot_calc`）

⚠️ **它是单槽、覆盖式、不落盘**（`effect_triggers.py:79-80` 注释）：
单线程同步 fire 所以成立；**别在异步/多线程里依赖它**。`dot_calc` 广播后
`_fire_ctx` 会被后续 fire 覆盖——所以读 `mult` 必须**紧跟在自己的 fire 之后**。

⚠️ **嵌套 fire 的坑（有真实踩坑记录）**：如果你的动作在自身执行过程中**又 fire
了另一个事件**，那个事件会把 `battle._fire_ctx` 覆盖掉，导致**你所在事件批次里排在
你之后的动作读到别人的 ctx 而静默失效**。参考实现的绕法（`class_mech_proc.py:238-244`）：

```python
_prev_ctx = getattr(battle, "_fire_ctx", None)
_fire(battle, "threshold", {"actor": owner, "key": res, "value": n}, logs)
battle._fire_ctx = _prev_ctx        # ← 广播后还原，否则同批次后续动作失效
```

原文注释解释了后果：渠道攒取（`class_res_channel_gain`）广播 `threshold` 后，
「同一事件批次里**排在渠道后的动作**（如 `guard_core_burst` 的 `skill_hit` 清层
`mech_cash_clear` 读 `info.mech`）会读到 `threshold` ctx 而静默失效」。
**任何会嵌套 fire 的扩展动作都要照抄这个 save/restore。**

### 6. 容错：全链路吞异常

- 单个 actor 的声明异常 → `continue`，其他源照跑（`effect_triggers.py:107-109`）
- 战斗级观察者 `on_event` 异常 → 吞（`effect_triggers.py:116-117`）

## ctx 约定

`effect_triggers.py:14-19` 定义了统一约定：

| 键 | 语义 |
|---|---|
| `actor` | **事件主体**（`on_death`=死者；`dot_tick`=受跳者；`buff_expire`=buff 持有者；`turn_start`/`act_begin`/`act_cast`=行动者；`skill_hit`/`attack_hit`/`crit`/`dmg_calc`=攻击者；`on_taken`/`on_heal`/`taken_calc`/`heal_calc`=承伤者/被治疗者） |
| `target` | **效果的作用目标**（`skill_hit`=被打者；`on_taken`=受击者；`on_heal`=被治疗者） |
| `caster` | 效果的施放方。**缺省 = 声明者自己**（`effect_triggers.py:70-72, 105`） |
| `info` | 技能 dict（可选） |
| `dmg` / `amount` / `real` / `overflow` | 数值（可选，各事件不同） |
| `source` | 攻击方（`on_taken` / `taken_calc` / `interrupt` 有） |
| `key` | 效果 key（`threshold` / `dot_tick` / `buff_expire` 有） |
| `_event` | 引擎填的事件名（`setdefault`，不落盘） |
| `mult` | 乘区型事件的**可写**乘法系数（初值 1.0） |

**关键推理**：「caster 缺省 = 声明者自己」使「受击自我强化」这类效果不需要显式施放方。
`fire` 调用时是 `apply_effects(battle, caster if caster is not None else a, target, ...)`
（`effect_triggers.py:105`）——`a` 就是声明者。

各事件的完整 ctx 字段表 → [../reference/events.md](../reference/events.md)。

## 执行语义

对匹配到的每个效果 dict：

```
actor["triggers"][event]
   → 深拷贝 + 注入 _owner
   → effects.apply_effects(battle, caster_or_owner, ctx.target, eff_list, logs)
   → effects.resolve_actions(名词)        查 EFFECT_ACTIONS
   → ACTIONS_HANDLERS[动词](battle, caster, target, params, logs)
```

`apply_effects`（`effects.py:137`）里的两条通用规则：

1. **概率 roll**：`eff["chance"]` 存在时 `random() >= chance` 就跳过（`effects.py:155-161`）
2. **参数合并**：`_merge_params` 让调用方参数优先于映射默认（`effects.py:125-134`）

## 引擎自然点位速查（26 个事件里哪些引擎会自己喊）

| | 事件 |
|---|---|
| **引擎有 fire 点位（23）** | `battle_start` `turn_start` `act_begin` `act_cast` `skill_hit`※ `attack_hit`※ `crit` `on_taken` `on_heal` `on_kill` `on_death` `dot_tick` `dot_calc` `on_act_consume` `on_hit_consume` `buff_expire` `threshold` `dmg_calc` `taken_calc` `heal_calc` `act_done` `interrupt` `time_advance` |
| **⚠️ 引擎无点位（3，必须上层驱动）** | `phase` `player_low` `pv_broken` |

※ `skill_hit` / `attack_hit` 的 fire 点位用变量选事件名（`actions.py:456`：
`ev = "attack_hit" if info.get("_basic") else "skill_hit"`），静态 grep 不到字面量。

精确点位（`文件:行号`）与每个事件的 ctx 字段见 [../reference/events.md](../reference/events.md)。

## 无点位的三个事件怎么用

`phase` / `player_low` / `pv_broken` 在 `EVENTS` 里声明了但它们**没有引擎自然点位**——
原文（`effect_triggers.py:38-40`）：

> N9 起：phase/player_low/pv_broken 无引擎自然点位（Boss 机制上层驱动），
> 由上层按需调 `fire()`，引擎已插桩自然点位 = 除这三个外 16 个。

也就是说：**你的命令层自己做阈值检查，然后自己 `fire(battle, "player_low", {"actor": who}, logs)`**。
引擎负责的是「事件名合法 + 按 subject 分发」这套机制，不负责判断「玩家是不是低血量了」
（那需要知道血量阈值，属于游戏知识）。

⚠️ 上面那段注释还写着「除这三个外 16 个」，与当前实际点数不符 —— 见
[_selfcheck.md](../_selfcheck.md)。

## 相关

- 事件全集的时机/ctx/是否自然点位 → [../reference/events.md](../reference/events.md)
- 效果条目与 `apply_effects` → [effects.md](effects.md)
- 一次行动里事件按什么顺序喊 → [../architecture/data-flow.md](../architecture/data-flow.md)
