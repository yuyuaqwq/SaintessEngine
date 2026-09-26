# 参考：事件全集

> **本页的 `EVENTS` 元组是从代码逐字抄的**（`extends/ext_combat/battle/effect_triggers.py:53`），
> 不是凭记忆或文档转述。核对方式：打开该文件搜 `EVENTS = (`。

## 元组原文（26 个）

```python
EVENTS = ("battle_start", "turn_start", "act_begin", "act_cast", "skill_hit", "attack_hit", "crit", "on_taken", "on_heal", "on_kill", "on_death", "dot_tick", "dot_calc", "on_act_consume", "on_hit_consume", "effect_expire", "threshold", "dmg_calc", "taken_calc", "heal_calc", "act_done", "phase", "player_low", "pv_broken", "interrupt", "time_advance")
```

⚠️ **必须单行定义** —— 覆盖率工具按行 trace，多行续行会永久漏记
（`effect_triggers.py:46-47` 注释）。改这行时别为了可读性折行。

⚠️ 模块 docstring 里写的「19 时机 + …」与「除 phase/player_low/pv_broken 外 16 个」
是**落后于代码的注释**：实际是 26 个事件名，引擎自己插桩了 **23** 个。
见 [_selfcheck.md](../_selfcheck.md)。

## 事件表（26 行）

`ctx` 列只列引擎**实际传的键**；`caster` 与 `_event` 由 `fire` 补
（`effect_triggers.py:76-87`）。`subject` = `ctx["actor"]`（决定谁能触发）。

| # | 事件 | 引擎 fire 点位（`文件:行号`） | `ctx` 字段 | subject | 时机语义 |
|---|---|---|---|---|---|
| 1 | `battle_start` | `battle.py:638`（`_ensure_battle_started`） | `{}` | **无**（全体触发） | 首个 actor 行动前，**整场一次**（`_started` 守卫） |
| 2 | `turn_start` | `battle.py:470`（`act`） | `actor` | 行动者 | 回合开始，**先于控制检查**（所以「回合开始回蓝」被晕也触发） |
| 3 | `act_begin` | `battle.py:511`（`act`） | `actor`, `target` | 行动者 | 控制通过、行动执行前 |
| 4 | `act_cast` | `actions.py:113`（`do_skill`） | `actor`, `target`, `info` | 施法者 | 扣费与冷却之后、结算之前 |
| 5 | `skill_hit` | `actions.py:450-452`（`_single_target_pipeline`） | `actor`, `target`, `info`, `dmg` | 攻击者 | 技能命中后（伤害已落地）；AOE 每目标各触发一次 |
| 6 | `attack_hit` | 同上（`info["_basic"]` 为真时选它） | 同上 | 攻击者 | 普攻命中后 |
| 7 | `crit` | `actions.py:483-481` | `actor`, `target`, `info`, `dmg` | 攻击者 | 暴击命中（`skill_hit`/`attack_hit` 的子集，**紧跟其后**） |
| 8 | `on_taken` | `landing.py:222`（`deal_damage`） | `actor`, `target`, `source`, `dmg` | 受击者 | 承伤落地后；**死者不触发**（走 `on_death`） |
| 9 | `on_heal` | `landing.py:494`（`heal_actor`） | `actor`, `target`, `source`, `amount`, `overflow` | 被治疗者 | 实际回血 > 0 时 |
| 10 | `on_kill` | `landing.py:407`（`_apply_damage`） | `actor`, `target`, `dmg` | **击杀者** | 致死伤害落地后；`source is None`（DOT/环境杀）不触发 |
| 11 | `on_death` | `battle.py:658`（`_on_actor_dead`） | `actor`, `target` | 死者 | 所有死亡路径统一在此；**死者的声明仍会执行**（subject 例外） |
| 12 | `dot_tick` | `schedule.py:772`（`_settle_time_effects`） | `actor`, `target`, `key`, `dmg` | 受跳者 | DOT 每一跳 |
| 13 | `dot_calc` | `schedule.py:715`（同上） | `target`, `dot_key`, `dmg`, `mult` | **无**（广播） | DOT 伤害落地**前**的乘区钩子 |
| 14 | `on_act_consume` | `battle.py:499`（`act`） | `actor`, `tag` | 行动者 | 被控跳过行动（`mode="skip"`）时 |
| 15 | `on_hit_consume` | `actions.py:552`（`_consume_hit_buffs`） | `actor`, `key` | 出手者 | 一次性出手 buff 被消费时 |
| 16 | `effect_expire` | `schedule.py:551`（`_settle_time_effects`） | `actor`, `target`, `key` | 条目持有者 | `effects` 条目到期被删时（**E5 改名**：原 `buff_expire`；线上零消费者，纯删名） |
| 17 | `threshold` | `effects.py:456`（`act_apply` 叠层分支） | `actor`, `key`, `value` | 条目持有者 | 叠层数值变化后（「战意满 10 → 狂暴」类） |
| 18 | `dmg_calc` | `actions.py:455`（`_single_target_pipeline`） | `actor`, `target`, `dmg`, `is_crit`, `info`, `mult` | 攻击者 | 伤害算出后、落地前（攻击方乘区） |
| 19 | `taken_calc` | `landing.py:121`（`deal_damage`） | `actor`, `target`, `source`, `dmg`, `mult` | 承伤者 | 承伤修正（承伤方乘区） |
| 20 | `heal_calc` | `actions.py:752`（`_do_heal`） | `actor`, `target`, `heal`, `info`, `mult` | 施法者 | 治疗量算出后、落地前 |
| 21 | `act_done` | `battle.py:599`（`act` 尾部） | `acted`（**不是** `actor`） | **无**（全员广播） | 行动完成；被控跳过不触发 |
| 22 | `phase` | ⚠️ **无引擎点位** | — | — | Boss 阶段转换（上层驱动） |
| 23 | `player_low` | ⚠️ **无引擎点位** | — | — | 玩家低血量（上层驱动） |
| 24 | `pv_broken` | ⚠️ **无引擎点位** | — | — | 破防（上层驱动） |
| 25 | `interrupt` | `landing.py:210`（伤害打断蓄力）/ `effects.py:707`（`act_interrupt` 动词） | `actor`, `target`, `source` | 被打断者 | 读条被打断 |
| 26 | `time_advance` | `schedule.py:551`（`_advance_time`） | `dt`, `now` | **无**（广播） | 时钟推进（结算**之后**广播） |

### 关于 `skill_hit` / `attack_hit` 的「静态 grep 不到」

`actions.py:501` 是：

```python
ev = "attack_hit" if info.get("_basic") else "skill_hit"
_fire(battle, ev, {...}, logs)
```

事件名由变量给出，所以 `grep '"skill_hit"'` 在引擎里**找不到 fire 调用**
（只能找到 `EVENTS` 里的声明）。这是本页最容易误判成「无点位」的一处。

## 引擎无点位的三个：怎么自己 fire

`fire()` 是公开 API（`__init__.py` re-export，门面表内），所以上层可以直接调：

```python
from saintess_engine import fire

# 例：你的命令层在每次行动后检查玩家血量
if player_actor["hp"] < int(player_actor["max_hp"] * 0.3):
    fire(battle, "player_low", {"actor": player_actor}, logs)
```

注意事项：

- `ctx` 里的 `actor` 会变成 **subject**（只触发该 actor 自己的声明）。
  想让「所有人都能被这个事件触发」就别传 `actor`
- ⚠️ 阈值判断（「多少算低血」）是**游戏知识**，必须留在你的层。
  这也是引擎不给点位的原因（`effect_triggers.py:38-40`）
- 内容侧的现实做法：不加事件，把判据挂到 `on_taken` / `act_done` 上每次自查
  （例：`core_last_stand`，`game/data/battle_rules.py:852-858`，
  注释直写「引擎无低血量事件 player_low，缺口见动作 docstring」）

## `_fire_ctx`：乘区型事件的读写口径

四个带 `mult` 的事件（`dmg_calc` / `taken_calc` / `heal_calc` / `dot_calc`）走**同一套**读写：

```python
ctx.setdefault("_event", event)
battle._fire_ctx = ctx            # effect_triggers.py:87-88 —— 单槽覆盖
```

引擎读回（例 `landing.py:119-108`）：

```python
_fire(battle, "taken_calc", _fctx, logs)
_m = float((getattr(battle, "_fire_ctx", {}) or {}).get("mult", 1.0) or 1.0)
if _m != 1.0:
    dmg = max(1, int(dmg * _m))
```

- 初值由引擎置 `mult: 1.0`
- **累乘**：多个源各乘一次
- **单槽**：下一次 `fire` 就覆盖。所以**必须同步读完**，不能存起来等会儿读
- **不落盘**（每次 fire 重建）

## `on_event`：战斗级观察者

```python
Battle(on_event=lambda battle, event, ctx, logs: ...)
```

`fire` 的**最后一步**调用（`effect_triggers.py:116-124`），**每个** fire 都会调（包括
`battle_start` 与无点位事件——只要有人调 `fire`）。

约定：

| 项 | 说明 |
|---|---|
| 收到的是 | `battle`, `event`（str）, `ctx`（dict，含 `mult` 等）, `logs` |
| 可以 | 只读 ctx、调引擎动词改状态、往 logs 里 append |
| 不可以 | 用返回值影响结算（返回值被忽略） |
| 异常 | 被吞掉（观察者容错，`effect_triggers.py:117-118`） |
| 调用次数 | 每个事件一次（**不是**每个 actor 一次） |

内容侧用法（`battle.py:49-51` 注释）：命令层记账 / 团队技能广播 / 存活同步。

## 事件顺序：一次普攻命中时的 fire 时序

```
act()                        → turn_start
                             → [控制检查]
                             → act_begin
   do_attack → do_skill      → act_cast
     → _single_target_pipeline
         → dmg_calc  ← 攻击方乘区（有 mult 读回）
         → _deal_hit → deal_damage
               → taken_calc   ← 承伤方乘区
               → [闪避 roll / defending / 免伤 / 醒睡 / 打断(interrupt)]
               → _apply_damage（护盾 → 扣血 → death_guard）
                     → on_kill（若致死）
                     → _on_actor_dead → on_death
               → on_taken（未死才有）
         → _apply_hit_effects（技能 mech）
         → attack_hit（普攻）/ skill_hit（技能）
         → crit（若是暴击）
         → bonus_atk_pct 附伤段（若有）
   [回 act()]
                             → act_done
                             → _check_side_end
```

（`actions.py:353-442` + `landing.py:28-162` + `battle.py:450-547`）

另外的时间线事件：`_advance_time` → `_settle_time_effects`
（`effect_expire` × n → `dot_calc` → `deal_damage` → `dot_tick` × n）→ `time_advance`
（`schedule.py:417-453`）。

## 相关

- 事件总线的匹配/过滤/注入语义 → [../concepts/event-bus.md](../concepts/event-bus.md)
- 乘区型扩展动作怎么写 → [../guides/write-a-mechanic.md](../guides/write-a-mechanic.md)
- 用事件表装配的框架（`PASSIVE_PROC` / 装备事件映射） → [passive-proc.md](passive-proc.md)
