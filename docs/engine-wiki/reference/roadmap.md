# 路线图：待建的引擎形状与待搬的骨架

> 本文是**引擎侧**的排期（面向第三方使用者：想拿这套骨架做游戏的人，和想往上加模块的人）。
> 内容侧（具体游戏的数据与规则）的排期在各自游戏仓，不在这里。
>
> **口径（2026-09-12 与项目主理人对齐）**：功能要**可拔插** —— 用不用都行，但现成给好；
> 并且要方便**非程序员用编辑器改**。

---

## 一、判据：什么进引擎，什么留内容

只有一条判据：

```ini
搬形状（骨架 / 协议 / 流程） → 引擎
   判据：把常量、枚举、名词全拿掉，逻辑还成立吗？成立 = 形状
搬功能（策略 / 内容 / 数据） → 留内容侧
   整块搬进引擎 = 把某款游戏的假设焊进引擎
```

这条判据是从一次实测来的：引擎 `saintess_engine/` **7 770 行**（12 子包 + 2 顶层模块 +
`container/` 通用件），而一个真实的参考实现是 **≈126 000 行** —— 比例 1:18。
所以「引擎很薄」不是缺陷，**问题从来不是搬得不够多，是姿势**。

**⚠️ 搬一块就要搬干净**：引擎只留骨架、内容侧只留适配与内容、门禁锁住两边。
半搬 = 制造新的双源（同一个语义在两处各写一份，早晚漂移）。

已建成的形状示例 → [declarative-commands-and-texts.md](declarative-commands-and-texts.md)、
[../concepts/declaration-tables.md](../concepts/declaration-tables.md)。

---

## 二、排期表

「类型」一列区分三件事：**新建形状**（引擎里还没有的能力）、**搬形状**（形状已在内容侧、
搬进引擎）、**下游落地**（用新形状重写内容侧，属参考实现的活）。

| # | 项 | 类型 | 依赖 | 验收（可判定） |
|---|---|---|---|---|
| 1 | **`log` 日志门面** | 新建形状 | — | 不调 `configure` 时行为与现状**逐字一致**；随包 3 个 sink；内容侧 logger 名收敛到 1 处 |
| 2 | 补齐 3 个数值门禁 | 补门禁 | — | 胜率矩阵 / CTB 频率 / 装备依赖 从「跳过」变「真跑」 |
| 3 | **`tlog` 结构化流水** | 新建形状 | #1（复用 Sink 协议） | `Record`/`Sink`/`Reader`/`Replay` 骨架 + `tlogs` 域进编辑器；0 sink = 零行为；JSONL 往返读回一致 |
| 4 | `tlog` 落地：战斗流水 | 下游落地 | #3 | 打完一场 → 完整流水 → **能回放复现同一场** |
| 5 | `tlog` 落地：行为流水 | 下游落地 | #3 | 任务/交易/掉落流水落库；分析脚本能出「某玩家某段流水」 |
| 6 | 地图形状 → 引擎 | 搬形状 | — | 派生/邻接/出口匹配独立于具体地图数据；配 `maps` 域 → 编辑器能画地图 |
| 7 | 物品形状 → 引擎 | 搬形状 | — | 掉落/品质/词条规则与具体物品表解耦 |
| 8 | 副本形状 → 引擎 | 搬形状 | #6 #7 | 最大一块，依赖前置两块，**排最后** |
| 9 | 指令表迁移收尾 | 下游落地 | — | 剩余指令按模块批量迁（每批跑一次互斥矩阵门禁） |

**为什么 `log` 排第一**：它最便宜，且它的 **`Sink` 协议被 `tlog` 复用** —— 先做省的是一次返工。
**为什么 `tlog` 排在数值门禁之后**：流水是「事后证据」，门禁是「事前拦截」。
先有门禁，采到的数据才有人接；否则只是攒了一堆没人看的日志。

---

## 三、`log` 日志门面（形状）

**现状问题**（在参考实现里实测）：十多个文件各自 `import logging` + `getLogger(...)`，
名字还不统一，无格式约定、无级别开关、无落地约定 —— **有日志行为，没有日志模块**。

引擎提供（全部是形状，零内容）：

```python
from saintess_engine.log import get_logger, configure, MemorySink

log = get_logger("battle.turn")          # 名字统一：<prefix>.<name>，prefix 由宿主给
log.warning("回合超时 actor=%s", aid)

configure(level="INFO", fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
          sinks=[MemorySink()])          # ★ 显式调用才生效
```

| 形状 | 说明 |
|---|---|
| `get_logger(name)` | 统一命名；**不调 `configure` 时只是 stdlib 薄封装** —— 可拔插的落点 |
| `configure(*, level, fmt, sinks, prefix)` | 级别/格式/出口；`sinks=()` 默认不改任何出口 |
| `Sink` 协议 | `emit(record: LogRecord) -> None`；随包给 `StreamSink` / `FileSink(rotate=…)` / `MemorySink` |
| `bind(**ctx)` | 带上下文的 logger：上下文进 `record.__dict__`，sink 可落库（玩家/命令/耗时） |

**零知识**：不 import 宿主、不认玩家、不认任何游戏名词。

---

## 四、`tlog` 结构化流水（形状）

**口径（主理人 2026-09-12 确认）**：**行为 + 战斗统一一套** —— 同一个 `tlog`
覆盖「玩家做了什么」与「战斗里发生了什么」，可落库、可分析、可回放。

**现状**：战斗日志是内联文本列表，边打边拼、打完就散（不落库、不可回放、不可事后分析）；
内容侧 27 张表里**没有一张日志/流水表**。

```python
from saintess_engine.tlog import TLog, Record

tl = TLog(sinks=[JSONLSink("run/tlog.jsonl")])   # 0 个 sink = 零行为
tl.emit("battle.hit", actor="p1", subject="e1", dmg=34, kind="phys", crit=False)
tl.emit("quest.accept", actor="p1", quest="Q17")

for r in tl.reader().iter_records(kind="battle.hit", actor="p1", since=t0): ...
```

| 形状 | 说明 |
|---|---|
| `Record` | `ts` / `kind` / `actor` / `fields` / `tags`；`kind` 是点号字符串，**字典由内容侧给** |
| `TLog.emit(kind, actor=…, **fields)` | 分发给全部 sink；无 sink = 什么都不发生 |
| `Sink` 协议 | `write(iterable[Record])` / `flush()`；随包给 `JSONLSink`（落盘，可直读分析）+ `MemorySink` |
| `Reader.iter_records(kind/actor/since/until)` | 分析脚本与回放共用一个读口 |
| `Replay` | 按序重放 → 支撑「同一场战斗复现」与「匿名化审计」 |
| `EventLogBridge` | 订阅进程内事件总线 → 转成 record；**映射表由内容侧给**（与 [events.md](events.md) 分工：总线管实时，流水管可查/可回放） |
| `kinds` 声明表 | 「哪个 kind 有哪些字段」→ 一套 schema 域，**编辑器可编辑**（与 `commands` / `texts` 同规格） |

**零知识**：不认任何具体 kind、不认数据库。落地方式（表结构、索引、匿名化视图）全在内容侧。

---

## 五、为什么这两个必须「可拔插」

引擎的使用者可能：

* 只想要战斗骨架，日志用宿主自己的 → **不调 `configure` 就是宿主原来的 logging**
* 不想落流水 → **不配 sink 就是零行为**，零 IO、零依赖

所以两件套的对外契约都是「**不配置 = 不存在**」。门禁照此写：先断言「不配置时行为与现状逐字一致」，
再断言「配置后能拿到东西」—— 只测后者等于没测可拔插。

---

## 六、下游采用（内容侧）

以下不在本仓，列出来只为说明依赖方向（详见各游戏仓的排期）：

| 优先 | 项 | 依赖本仓 |
|---|---|---|
| 1 | 文案表接入内容侧（`TextTable` 已就绪但尚未被采用） | `text` |
| 2 | 结算类文案批量迁移（走渐进迁移口，不一次性重写） | `text` |
| 3 | 战斗流水落地 + 回放 | `tlog` |
| 4 | 行为流水落地 + 分析脚本 | `tlog` |
| 5 | 指令表剩余部分迁移 | `command.CommandRegistry` |
