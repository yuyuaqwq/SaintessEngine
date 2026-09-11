# CTB 时间轴

## 一句话

**`ct` = 该 actor 下次可行动的绝对时刻。** 谁 `ct` 小谁先动；行动完把自己推到
`now + 耗时`。整场战斗有一个全局时钟 `battle._now`。

`1 刻 = 1 时刻 = 1 游戏秒`（`schedule.py:9`，`ACT_TICK=1`）。

## 为什么用绝对时刻而不是「行动条增量」

两种常见做法：

| 做法 | 问题 |
|---|---|
| 每 tick 给所有人加速度、到 100 就行动 | 需要「每 tick」这个循环；不同速度单位要统一；AOE/多段结算时的时间推进点很难说清 |
| **绝对时刻制**（本引擎） | 时间只在「从 A 到 B」时被推进；`_advance_time(battle, dt)` 一次推进就能结算期间所有到期事件 |

绝对时刻制的关键收益：**时间推进是一个显式函数调用**（`schedule._advance_time`，
`schedule.py:156`），它内部依次做「加时钟 → 结算周期/到期 → 广播 `time_advance`」。
所以「3 秒内发生了 3 次 DOT」这件事是确定的、可断言的，不依赖主循环被调用了几次。

## 公式

```python
def action_time(spd, base=CAST_ATK):          # schedule.py:32
    return float(base) * math.sqrt(SPD_REF / max(float(spd or 0), 1.0))
```

| 常量 | 值 | 位置 |
|---|---|---|
| `CAST_ATK` | 1.0 | `schedule.py:22` |
| `CAST_SKILL` | 1.6 | `schedule.py:23` |
| `CAST_DEFEND` | 0.6 | `schedule.py:24` |
| `CAST_ITEM` | 1.0 | `schedule.py:25` ⚠️ 引擎内无消费者（道具耗时由命令层自己算，见 [_selfcheck.md](../_selfcheck.md)） |
| `SPD_REF` | 50.0 | `schedule.py:26` |
| `HOT_INTERVAL` | 1.0 | `schedule.py:29` ⚠️ 无消费者 |
| `DEFAULT_CT_WAIT` | 2.0 | `battle.py:22` ⚠️ 无消费者（历史常量） |

速度是**开方**缩放的：`spd=50` 是基准；`spd=200` 耗时是 50 的 1/2（不是 1/4）；
`spd=2` 会慢约 5 倍。开方而非线性，是为了让速度收益递减、避免「堆速度=无限行动」。

**速度口径**：始终读**聚合面板** `stats.actor_spd(battle, actor)`（`stats.py:140`），
不是裸 `actor["spd"]`。播种（`battle._seed_ct_one`，`battle.py:100`）、
行动后推进（`schedule._after_act`，`schedule.py:143`）、`next_ct`（`schedule.py:46`）
三处一致。原因：玩家 actor 的裸 `spd` 可能是 0（面板要从职业/装备算），
用裸值会让排序崩（`battle.py:105-107` 注释）。

## 三个时刻相关函数

```python
initial_ct(spd)        # schedule.py:41 = action_time(spd) —— 开局第一动的等待
action_time(spd, base) # schedule.py:32 —— 单次行动耗时
next_ct(battle, actor) # schedule.py:46 —— 返回 actor 行动后的 ct（绝对时刻）
```

⚠️ `initial_ct` / `action_time` 是 S2 公开 API（被内容层与测试消费）；
`next_ct` **只有定义没有调用方**（[_selfcheck.md](../_selfcheck.md)）。
实际推进走的是 `_after_act`（直接 `actor["ct"] = now + action_time(...)`）。

## 推进：`advance()` 是命令层驱动的心脏

```python
def advance(battle, logs, max_steps=200):     # schedule.py:71
    while battle.result is None and guard < max_steps:
        fp   = _next_player_due(battle)       # ct 最小的存活「人控」
        auto = _next_auto_due(battle)         # ct 最小的存活「自动」
        if fp is None and auto is None: return ("over", None)
        if fp is not None and (auto is None or fp[1] <= auto[1] + 1e-9):
            _advance_time(battle, fp[1] - battle._now, logs)   # 推进到玩家时刻
            return ("player", fp[0])                           # 暂停，等真人输入
        # 自动 actor 先到点
        _advance_time(battle, auto[1] - battle._now, logs)
        battle.actor_auto(actor)              # 它自己行动（内部再推自己的 ct）
```

ASCII 时序（玩家 spd=60 → ct≈0.91；怪 spd=40 → ct≈1.12；普攻 cast=1.0）：

```
now=0.00  ┌─ 开局：玩家 ct=0.91，怪 ct=1.12（initial_ct 播种）
          │
now=0.00  │  human_act("attack")  ← 玩家此刻就能动（ct 是"最早能动时刻"，
          │                        命令层在此之前已 advance 过）
now=0.00  │  ├ act(attack) → 伤害落地
          │  └ _after_act → 玩家 ct = 0.00 + 1.0×sqrt(50/60) ≈ 0.91
          │
now=0.91  │  advance：怪 ct=1.12 > 玩家 ct=0.91 → 返回 ("player", 玩家)
          │
now=1.12  │  （下次 human_act 前，命令层会 advance → 推到怪的 1.12，
          │    怪 actor_auto 行动 → 怪 ct ≈ 1.12+1.0×sqrt(50/40)=2.24）
          └
```

**谁会被 `advance` 认为是「人控」**：`actor["human_controlled"]` 为真
（`schedule._next_player_due`，`schedule.py:113-125`）。**不是** `kind` / `side`。
如果没有配置 `human_controlled`，`advance` 会一路跑完所有自动行动 ——
这正是 `auto_run` 能「全自动打完」的原因。

> ⚠️ **`human_act` 不检查 ct**：它拿到 caster 就直接 `act()`（`battle.py:244-264`），
> 没有「你的 ct 还没到」这层校验。**时机由命令层负责** —— 正确用法是
> 「先 `advance()` 拿到它返回的 who，再用 `human_act(actor=who)` 让那个人出手」。
> 直接连点 `human_act` 等于给玩家无限行动权。

## 时间推进时发生什么

`_advance_time(battle, dt, logs)`（`schedule.py:156`）：

```python
battle._now += dt            # ① 时钟前进
_settle_time_effects(battle, logs)   # ② 到期 + 周期结算
fire(battle, "time_advance", {"dt": dt, "now": battle._now}, logs)   # ③ 广播
```

顺序很重要：**广播在结算之后**，所以监听 `time_advance` 的内容层读到的
`now` 已经是结算后的状态（`schedule.py:159-161` 注释：挂敌身条等按刻连续结算的
声明订阅此事件，「读点永远拿到当刻值」）。

`_settle_time_effects`（`schedule.py:175`）三轮：

1. **`effects` 到期**：`expire <= now` → pop，并 `fire("buff_expire", {"actor", "target", "key"})`
2. **`shields` 到期**：`expire_at <= now` → pop（`expire_at is None` = 永久盾不删）
3. **周期跳**：见 [effects.md](effects.md) 的「周期结算」节

`damage` 方向的周期跳在落地前会先 `fire("dot_calc", {"target", "dot_key", "dmg", "mult"})`
（`schedule.py:285`，**不带 `actor` 键** → 广播给所有人，因为施毒者不在承伤者身上；
效果侧用 `ctx["dot_key"]` 自己过滤）。落地后 `fire("dot_tick", {"actor", "target", "key", "dmg"})`
（`schedule.py:297`）。

## 行动耗时表（`action_base_of`，`schedule.py:58`）

| `action` | base |
|---|---|
| `"defend"` | 0.6 |
| `"skill"` | 1.6 |
| 其他（含 `"attack"` / 未知） | 1.0 |

⚠️ 自定义行动（`use_item` 等）**不会被 `action_base_of` 识别**——它们走
`Battle.action_override` 回调返回的耗时：返回 `str`（内置动作名）按上表缩放，
返回**数字**则当作绝对秒直接落 `ct`（`battle.py:272-281`）。

## 控制效果如何与时间轴互动

被控（`mode="skip"`）时的语义是「**行动浪费**」（`battle.py:439-446`）：

```
被控 actor 轮到行动 → 打日志 → 从 effects 删掉控制条目
                    → fire("on_act_consume", {actor, tag})
                    → battle._p_acts += 1      ← 记一次行动点
                    → return，不结算行动       ← 调用方照样推 ct
```

「照样推 ct」由调用方完成：`actor_auto`（`battle.py:393-395`）或 `human_act`
（`battle.py:269-283`）在 `act()` 返回后都调 `_after_act`。所以控制不是「冻结时间」，
而是「这次行动白费」——这是 CTB 类游戏的标准语义。

`mode="no_skill"`（沉默）不跳行动，只把 `attack` 换成 `skill` 清掉技能名
（`battle.py:434-437`），耗时按 `attack` 计（`human_act` 里 `ctx.action` 已被改写，
`battle.py:266-267` 注释）。

## 序列化与时钟

`to_state` 存 `now`（`serialize.py:40`）、actor 的 `ct` 随 actor 字段一起存。
`from_state` 恢复 `_now` 且 **`seed_ct=False`**（`serialize.py:68/70`）——
不重播初始 ct，因为存档里已经有每个 actor 的真实 ct。改这条会让续战起手错位。

## 相关

- 规则表里的 `period` 字段 → [../reference/effect-rules.md](../reference/effect-rules.md)
- 每个 fire 点位的精确行号 → [../reference/events.md](../reference/events.md)
- 一次行动的完整调用链 → [../architecture/data-flow.md](../architecture/data-flow.md)
