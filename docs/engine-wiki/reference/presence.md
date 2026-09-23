# 在场形状（清单判定 + 当天派生 + 保底冷却）

> **归属**：本能力**不在引擎里**（2026-09-23 起）—— 它在扩展包 `extends/ext_social/`（`presence/`）。
> 数据包要用它：`game.json` 里写 `"depends": ["ext_social"]`；引到的 `ext_life` 形状见 `extends/ext_life/`。
> 引擎侧只剩通用件，见 `../architecture/boundaries.md`；下文裸文件名与行号都相对 `extends/ext_social/presence/`。
>
> 模块：`ext_social.presence` —— `Lookup`（多表首命中）+ `Presence`（在场清单）+
> 六个纯函数（`day_slot` / `day_hit` / `minutes_left` / `guarded_roll` / `cooldown_ok` /
> `merge_tables`）。一句话：**数据给「谁在、在哪」，本形状给「怎么筛、怎么编号、怎么算」**。

## 为什么有它

参考实现（游戏仓 `dragonfall`）里，「谁在这里」这件事的**判定与派生被抄了好几份**，
每一份都只差一点：

| # | 位置 | 内容 |
|---|---|---|
| 1 | `world_cmds.py` `_map_blocks` / `_hurry_section` / `_current_npcs` | **同形三份**列表装配：成员集合与过滤口径互不相同（有的是刻意差异） |
| 2 | `wild.py` `npc_map_id` / `town_npc_day_sa` | 同一套「日期哈希定位」手写两遍 |
| 3 | `wild.py` `town_npc_visible` / `town_npc_dialogue` | 同一套「日期哈希取档」各写一遍（出现概率 / 轮换台词） |
| 4 | 5 个文件约 20 处 `A.get(id) or B.get(id) or C.get(id)` | 多表首命中：有的两表、有的三表；`or` 是**真值**链 |
| 5 | `wild.py` `_roll_random` 与 `roll_wild_encounter` | 保底计数与冷却窗口的 `if` 散在两处 |
| 6 | `world_cmds.py` `_present_wild_hints` / `_start_talk_list` | `max(1, ceil(remain/60))` 与「静态 N 条 + 限时续号」各写一遍 |

把这些里的**取值**（哪个字段算概率、哪个前缀算解锁、盐怎么拼、时段词、地图 id）
全部拿掉，剩下的就是形状：**确定性日期派生、向上取整的展示、一次伯努利 + 保底、真值链、
保序装配、保序合并**。

## 形状总览

```python
from ext_social.presence import (Lookup, Presence, day_slot, day_hit,
                                      minutes_left, guarded_roll, cooldown_ok,
                                      merge_tables)

day_slot(739000, len(bucket), salt=row_id)        # 当天在候选桶里取第几个
day_hit(739000, salt=row_id + suffix, rate=0.8)   # 当天是否命中阈值（裸判据）
minutes_left(0)                                   # 1（ceil 且下限 1）
guarded_roll(6, guarantee=7, chance=0.2, rng=rng) # (hit, 剩余未中数, 是否该清计数)
cooldown_ok(last, now, 1800)                      # 没记过 → True

lk = Lookup(town_rows, wild_rows, hidden_rows)    # 真值链：空 mapping 会穿透
p = Presence(lk, keep=visible_today, place_of=place_of_today)
p.rows(ids, place=current_place, day=ordinal)     # [(id, row, 表下标)]，声明序
p.here(ids, place=current_place, day=ordinal)     # [row]（rows 的投影）
p.slots(static_items, timed_items)                # [(序号, "static"|"overlay", 项)]
p.slot_at(slots, 3)                               # 1-based；越界 → None
p.overlay(events, now=now_ts)                     # 限时事件视图（保有输入序）
merge_tables(wild_rows, hidden_rows, exclude=skip)  # 保序合并 → 新 dict
```

本形状**一个业务字段名都不认识**：`Lookup` / `Presence` 只拿**不透明的行**，
判据（`keep`）/ 定位（`place_of`）/ 标识（`key`）全部注入；`day` 是调用方给的
整数日序数（本形状不认识日历，不 import 时间/日期库）；随机只在注入的 `rng()` 里。

## 三个纯派生

### 日期派生：`day_slot` / `day_hit`

```
day_slot(seed, size, salt) = ((seed*2654435761 + Σord(salt)) & 0x7FFFFFFF) % size
day_hit(seed, salt, rate)  = day_slot(seed, 100, salt) >= int(rate*100)
```

* 同一天、同一个盐 → **全服一致的确定性答案**（没有随机源）；`size <= 0` → `ValueError`
  （空候选桶是调用方 bug，不许静默返回 0）。
* `day_hit` 是**裸阈值判据**：命中的是 `[int(rate*100), 100)` 这一段。
  正用（命中 = 出现）还是反用（命中 = 不出现）是**调用方**的语义 ——
  参考实现用它当「今天不出现」的判据。**不许**化简成 `slot/100 >= rate` 的百分比浮点比较：
  门槛是整数，浮点比较在进位误差与边界槽位上会漂（门禁对五档真值逐值钉死）。

### 展示派生：`minutes_left`

`max(1, ceil(remain/60))`：剩 0 秒也显示「1 分」，负数同样给 1。
展示「0 分」像 bug，下限 1 是刻意的展示口径。

### 保底与冷却：`guarded_roll` / `cooldown_ok`

```
guarded_roll(miss, guarantee, chance, rng):
    chance 假值        → (True,  miss, False)        # 不掷骰、不消耗 rng、不动计数
    miss >= guarantee  → (True,  0,    True)         # 保底；cleared 叫调用方清计数
    rng() < chance     → (True,  miss, False)        # 命中路径**不**清计数
    否则               → (False, miss+1, False)
cooldown_ok(last, now, window) = (not last) or (now - last >= window)
```

* **先判后写**：短路路径既不读 `rng`、也不产生 `miss+1`；本模块**不落盘**，
  调用方拿返回的 `miss_after` / `cleared` 在自己那里写。
* `rng` 必填：缺省 / 不可调用 → `TypeError`（本形状不许悄悄用系统随机）。

## 表与清单

| 形状 | 语义要点 |
|---|---|
| `Lookup(*tables)` | 按表序首命中；**真值链**（值为假值 → 继续下一张表，空 mapping 会穿透）；`first → (值, 表下标)` / `rows → [(id, 值, 表下标)]` 保序、缺席丢弃 |
| `Presence(lookup, keep, place_of, key)` | `rows` = 声明序 + 一条注入判据；`place is None` = **不做**定位过滤；每次现算、不缓存；不去重、不排序 |
| `Presence.slots(static, overlay)` | 静态在前、叠加**续号**（从 1 起）→ `(序号, "static"\|"overlay", 项)`；纯编号，不合并 |
| `Presence.slot_at(slots, i)` | 1-based 取整条；越界（含 `< 1`）→ `None`（不抛） |
| `Presence.overlay(events, now, minutes)` | 事件视图 → `[{key,row_id,place,minutes,raw}]`；保有输入序；`remain` 给了就用，否则 `expire - now` 现算 |
| `merge_tables(*tables, exclude=())` | 保序合并 → **新** dict；后表覆盖前表；`exclude` 的键在每张表里都跳过 |

## 口径分歧（故意不统一）

| # | 分歧 | 现状 | 为什么不统一 |
|---|---|---|---|
| ① | **确定性 vs 随机性** | 日期派生同一天全服一致；保底掷骰是个人运气 | 合并会出现「同一天同群玩家看到不同世界」或「蹲守刷屏」 |
| ② | **`day_hit` 是裸判据** | 逐字 `slot >= int(rate*100)` | 引擎不懂「出现」的语义；正反用由调用方定 |
| ③ | **展示下限 1** | `ceil` 且 `max(1, …)` | 「剩 0 分」像 bug |
| ④ | **假值即放行** | `chance` 假值 = 必定命中；`last` 假值 = 必定可触发 | 「没配概率 / 没记过」不是「永不」 |
| ⑤ | **命中不清计数** | `rng` 命中路径原样返回 `miss`；清计数只由 `cleared` 表达 | 否则保底路径的 `cleared` 语义会漂 |
| ⑥ | **真值链而非存在性链** | `Lookup.first` 与手写 `a.get(k) or b.get(k)` 同口径 | 改成 `is not None` 链会改「空壳值」的既有行为 |
| ⑦ | **保序 / 不去重 / 不排序** | 一律声明序；`slots` 静态在前、叠加续号 | 顺序本身就是数据；去重/排序会改玩家可见列表 |
| ⑧ | **后表覆盖前表** | `merge_tables` 与 `{**a, **b}` 同口径 | 合表方向是调用方口径，引擎不猜 |

## 为什么不复用既有形状（就地复用评估）

| 相邻形状 | 结论 | 理由 |
|---|---|---|
| `periodic.Cooldown`（现住 `extends/ext_life/`） | **不复用** | 它的存储键是**它自己拼的**，且把「读 → 判 → 写」绑在一个对象上；本形状只抽**算术**（`cooldown_ok(last, now, window)`），时间戳存在调用方自己的嵌套映射里，落盘留在调用点 |
| `timers.Timers`（现住 `extends/ext_life/`） | **不复用（它已经在用）** | 限时在场就是一张 `Timers` 事件表；本形状只做「把事件表读出来并派生展示分钟/保序编号」（`overlay` / `minutes_left`），过期懒清除与回调仍是 `Timers` 的职责。再包一层会造出第二套过期语义 |
| [`space.Space`](space.md) | **不复用** | 定位在这里是**一个不透明 id 的相等判定**，不是连通性/深度/必经路径；套 `Space` 会要求把定位取值归口成节点 id（= 改内容数据） |
| [`loot`](loot.md) / 加权抽取 | **不复用** | 日期派生是**确定性哈希**（同一天全服同答案），`loot` 的池+权重是随机抽取，形状不同；`guarded_roll` 只是一次伯努利 + 保底计数，套池/档位全是空转 |

## API

| 形状 | 说明 |
|---|---|
| `day_slot(seed, size, *, salt="")` | 当天槽位；`size <= 0` → `ValueError` |
| `day_hit(seed, *, salt="", rate)` | 裸阈值判据（`>= int(rate*100)`） |
| `minutes_left(remain_sec)` | `max(1, ceil(remain/60))` |
| `guarded_roll(miss, *, guarantee, chance, rng)` | `(hit, miss_after, cleared)`；`rng` 必填 |
| `cooldown_ok(last, now, window)` | `last` 假值 → `True` |
| `merge_tables(*tables, exclude=())` | 保序合并（新 dict） |
| `Lookup(*tables)` | `first` / `rows` / `tables` |
| `Presence(lookup, *, keep, place_of, key)` | `rows` / `here` / `slots` / `slot_at` / `overlay` / `lookup` / `key_of` |

门禁：`extends/ext_social/tests/test_presence_shape.py`（93 断言：逐值表 ≥1000 组 / `day_hit` 五档门槛 /
`minutes_left` 九格 / 保底写入时机 / 真值链 / 零知识静态扫描 / 口径分歧 /
多故障「两处同坏 + 第三处仍绿」/ 五条顺序断言 / 只读）。

## 有意不做

* 不认识日历：不 import 时间/日期库、不读钟；`day` 与 `now` 都由调用方给
* 不掷骰：不 import `random`；随机源一律注入（可复现、可测试）
* 不认字段：不读任何业务行的字段名；判据/定位/标识全经注入的可调用
* 不落盘 / 不缓存：`Presence.rows()` 每次现算；保底计数与冷却时间戳的读写留在调用点
* 不去重 / 不排序 / 不归并同名：这些是内容决策，本形状不替它决定
* 不做数值调参：保底阈值 / 冷却窗口 / 盐 / 概率全部由调用方给
