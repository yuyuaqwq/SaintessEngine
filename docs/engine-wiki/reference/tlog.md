# 结构化流水（tlog）—— 发生过什么，能不能复现

> 模块：`saintess_engine.tlog` —— `TLog` / `Record` / `KindTable` / `Sink` / `Reader` / `Replay` /
> `EventLogBridge`。一句话：**一行一条、可落盘、可查、可回放、可脱敏**；**0 sink = 零行为**。

## 为什么有它

参考实现的战斗日志是**内联文本列表**：边打边拼、打完就散（不落库、不可回放、不可事后分析），
27 张内容表里**没有一张日志/流水表**。于是这些问题都得靠翻聊天记录：

* 「刚才那场为什么输」—— 没有结构化伤害/事件序列
* 「这个玩家昨天做了什么」—— 行为没有留痕
* 「复现一下这个 bug」—— 无可回放序列
* 「把数据交出去做分析」—— 直接给原始数据会带玩家身份

`tlog` 把这些收敛成**一条记录 + 一个出口 + 一套读口**，且**内容侧决定一切语义**（kind 词表、
字段、落库方式）。零知识：不认任何具体 kind、不认数据库。

## 可拔插契约（0 sink = 零行为）

| 状态 | 行为 |
|---|---|
| 不配 sink（`TLog()`） | `emit` 只构造并返回 `Record`，**零 IO、零依赖** |
| `TLog(sinks=[...])` | 每条记录交给全部 sink（**逐个隔离**：一个 sink 坏不牵连同批） |
| `remove_sink` / `add_sink` | 运行期增删出口 |
| 不配 `kinds`（声明表） | **不校验**（零行为）；配了才比对 |

## 用法

```python
from saintess_engine.tlog import TLog, JSONLSink, KindTable

tl = TLog(sinks=[JSONLSink("run/tlog.jsonl")], kinds=kt)   # 0 个 sink = 零行为
tl.emit("battle.hit", actor="p1", subject="e1", dmg=34)     # kind + 字段
tl.emit("quest.accept", actor="p1", quest="Q17")

for r in tl.reader().iter_records(kind="battle.", actor="p1", since=t0):
    print(r.ts, r.fields["dmg"])

tl.replay(kind="battle.").anonymize()      # 脱敏后的序列（交给分析侧）
```

> ⚠️ `emit(1st 参数 = 记录的 kind, actor=…, tags=…, **字段)`；**字段名与保留参数
> （`kind`/`actor`/`tags`/`fields`）撞名时用 `fields={...}` 显式传**
> （`tl.emit("battle.hit", fields={"kind": "phys"}, dmg=34)`），否则会
> `TypeError: got multiple values for argument 'kind'`。

## Record

| 字段 | 说明 |
|---|---|
| `kind` | 点号字符串（`battle.hit`）；**字典由内容侧给**，框架不认任何具体值 |
| `ts` | 事件时刻（秒 float）；由 `TLog` 注入时钟（可换，测试可控） |
| `actor` | 归属主体（字符串）；填什么由内容侧决定 |
| `fields` | 结构化字段（dmg / subject / crit …） |
| `tags` | 标签（内容侧自定）；用于粗筛 |

`to_dict()` **键序固定**（kind/ts/actor/fields/tags）—— 这是 JSONL 往返**逐字节一致**的前提。

## API

| 形状 | 位置 | 说明 |
|---|---|---|
| `Record` | `saintess_engine/tlog/record.py:32` | 一条流水 |
| `KindSpec` / `KindTable` | `tlog/record.py:76` / `:115` | 「哪个 kind 有哪些字段」的声明表 |
| `KindTable.check_record` / `audit` | `tlog/record.py:203` / `:218` | 记录↔声明差异；声明未发过 / 发过未声明 |
| `Sink` 协议 | `tlog/sinks.py:33` | `write(records)` + 可选 `flush()`/`close()` |
| `dispatch` | `tlog/sinks.py:50` | 逐个分发 + 异常隔离（返回成功数） |
| `JSONLSink` | `tlog/sinks.py:66` | 行式 JSON 落盘；`read_records()` 读回（坏行跳过记 `bad_lines`） |
| `MemorySink` | `tlog/sinks.py:121` | 内存快照；`limit` / `kinds()` / `of_kind()` |
| `TLog` / `emit` | `tlog/core.py:41` / `:68` | 门面 / 记一条 |
| `TLog.reader` / `audit` | `tlog/core.py:113` / `:127` | 开读口 / 自检汇总 |
| `Reader.iter_records` | `tlog/reader.py:51` | 读口（过滤口径见下） |
| `Replay` / `anonymize` | `tlog/reader.py:89` / `:139` | 按序重放 / 脱敏 |
| `EventLogBridge` / `attach` | `tlog/bridge.py:26` / `:80` | 事件总线 → 流水（映射表内容侧给） |

> **与 `log` 的关系（2026-09-19）**：`JSONLSink` 的文件生命周期与 sink 报错口径与 `log` 的出口
> **共用同一份代码** —— `saintess_engine/_sinkbase.py`（`FileSinkBase` / `sink_error()`）；
> 两侧各自只保留协议与分发形状（`write(records)` vs `emit(record)`）。

## Reader：一套筛选口径

```python
rd = tl.reader()
rd.iter_records(kind="battle.hit", actor="p1", tag="pvp", since=t0, until=t1)
```

* `kind`：字符串或列表；**`"battle."` 这种点结尾写法 = 前缀匹配整族**
* `actor` 精确 / `tag` 含标签 / `since`-`until` 时间窗（**左闭右开**）
* `count()` / `first()` / `kinds()` / `all()`；`replay(**filters)` = 先筛后放

## Replay：复现 / 概览 / 脱敏

```python
rp = tl.replay(kind="battle.")
rp.steps()            # 按 (ts, 写入序) 稳定排序的序列 → 逐条复现
rp.summary()          # {count, kinds, actors, span, per_kind}
rp.anonymize()        # actor → u1/u2…（按出现序自动编号）
rp.anonymize({"p1": "英雄甲"})   # 显式映射优先，未覆盖的自动补号
```

`anonymize` 返回**新** Replay（原对象不变）—— 原始流水要留着做审计。

## EventLogBridge：总线 → 流水

领域事件是「实时」（发生即分发），流水是「可查/可回放」—— 两者互补，桥把前者转成后者：

```python
br = EventLogBridge(tl, {
    "order_paid": "shop.paid",                                        # 简写：事件名 → kind
    "battle_end": {"kind": "battle.end", "fields": ["win"], "tags": ["battle"]},
})
br.attach(bus)      # 只挂「映射表 ∩ 总线已声明事件」
```

* **映射表由内容侧给**（框架不认任何事件名）
* 订阅方**返回 None** —— 它是旁路，不改变既有输出行
* `fields` 白名单 / `drop` 内部键（`lines`/`event`）/ 非标量字段转文本（保证可 JSON 落盘）
* 未映射事件记入 `missed`；`strict=True` 时直接抛（联调用）

## 声明表与编辑器

`kinds` 声明（「哪个 kind 有哪些字段」）是**一套 schema 域 `tlogs`**（与 `commands`/`texts` 同规格）：
`schemas/tlog.schema.json` + 编辑器域 `tlogs`（分组：基础 / 字段清单 / 分类与标签）。

装载后：`TLog(strict=True)` 按声明拦「多字段 / 少字段」；`audit()` 报「声明了没发过」
与「发过没声明」——**写的人和读的人有同一份依据**，而不是各自记。

## 与 `log` 的分工

| | `log` | `tlog`（本模块） |
|---|---|---|
| 问题 | 此刻出什么事了（运维视角） | 发生过什么、能不能复现（业务视角） |
| 单位 | `LogRecord`（级别 + 消息文本） | `Record`（kind + 结构化字段） |
| 出口 | Stream / File（轮转）/ Memory | `JSONLSink`（可直读分析）/ `MemorySink` |
| 生命周期 | 滚动、可丢弃 | 落库、可查、可回放、可脱敏 |

两者共用同一套 **Sink 心智模型与分发纪律**（逐个隔离 / 零出口零行为 / record 本体交给出口）。

## 有意不做

* 不认任何具体 kind、不认数据库（落库表结构 / 索引 / 匿名化视图全在内容侧）
* 不做采样 / 限流 / 轮转（要这些就在内容侧写一个 sink 包一层）
* 不做"自动记录一切"（记什么、记哪些字段是**内容侧的设计决定**）
