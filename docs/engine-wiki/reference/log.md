# 日志门面与出口（可拔插）

> 模块：`saintess_engine.log` —— `get_logger` / `configure` / `bind` + `Sink` 协议与 3 个随包出口。
> 一句话：**统一命名 + 可拔插出口 + 结构化上下文**；不配置 = 不存在。

## 为什么有它

参考实现里十多个文件各自 `import logging` + `getLogger(...)`，名字还不统一 ——
**有日志行为，没有日志模块**：没有格式约定、没有级别开关、没有落地约定（输出完就散）。

痛点不是「难看」，是三件具体的事：

1. 想统一格式 / 想落地到文件 —— 得改十几个文件；
2. 想临时开 DEBUG —— 没有单点开关；
3. 想知道「刚才那次为什么慢」—— 日志是 stderr 里的一行文本，查不到结构化字段。

## 可拔插契约（不配置 = 不存在）

| 状态 | 行为 |
|---|---|
| 不调 `configure` | 只是标准库薄封装：`get_logger("x")` **就是** `logging.getLogger("<prefix>.x")` 本体（`is` 同一对象）；零 handler、级别与 `propagate` 不动 → 宿主原有 logging **逐字一致** |
| `configure(sinks=[...])` | 给 `<prefix>` logger 装一个桥接 handler，record 逐个交给 sink |
| `configure(sinks=())` | **不改任何出口**（空 = 「不管」，不是「清空」） |
| `remove_sinks()` | 摘掉**本门面装过的**出口（宿主自己 `addHandler` 的一律不碰） |

> ⚠️ 门禁口径（`tests/test_log.py`）：**先**断言「不配置时与现状逐字一致」，**再**断言「配置后能拿到东西」——
> 只测后者等于没测可拔插。

## 命名

全名 = `<prefix>.<name>`；`prefix` 默认 `"saintess_engine"`（引擎自己），宿主用
`configure(prefix="my_game")` 改。**应在装配早期设置** —— 它只影响之后的取名
（已建好的 logger 对象名字不会变）。

```python
get_logger("battle.turn")     # → saintess_engine.battle.turn
logger_name("battle.turn")    # → 同名（不开 logger，诊断/测试用）
```

## 用法

```python
from saintess_engine.log import get_logger, configure, bind, FileSink, MemorySink

log = get_logger("battle")
log.warning("回合超时 actor=%s", aid)      # 不配置 → 走宿主原有 logging

configure(prefix="my_game", level="INFO",
          fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
          sinks=[FileSink("run/app.log", rotate="size", max_bytes=2_000_000),
                 MemorySink(limit=500)])   # ★ 显式调用才生效

bind(log, actor="p1", command="攻击").info("结算完成")   # actor/command 进 record 字段
```

## API

| 形状 | 位置 | 说明 |
|---|---|---|
| `get_logger(name)` | `saintess_engine/log/facade.py:72` | 取 logger；不配置时等价 `logging.getLogger(全名)` |
| `configure(*, level, fmt, sinks, prefix, propagate)` | `saintess_engine/log/facade.py:80` | 显式配置；`sinks=()` 不动出口；重复调用**替换**（幂等） |
| `logger_name(name)` | `saintess_engine/log/facade.py:66` | 全名计算 |
| `remove_sinks(prefix=None)` | `saintess_engine/log/facade.py:127` | 摘掉本门面装的出口（返回摘掉几个） |
| `bind(logger, **ctx)` | `saintess_engine/log/facade.py:172` | 结构化上下文（见下） |
| `ContextAdapter` | `saintess_engine/log/facade.py:144` | `bind` 的返回类型；可链式 `.bind()` |
| `Sink` 协议 | `saintess_engine/log/sinks.py:38` | `emit(record)` 必须，`flush()` / `close()` 可选 |
| `dispatch(sinks, record)` | `saintess_engine/log/sinks.py:76` | 逐个分发 + 异常隔离（返回成功数） |

## 三个随包出口

| 出口 | 位置 | 特点 |
|---|---|---|
| `StreamSink(stream=None, fmt=…)` | `saintess_engine/log/sinks.py:112` | 默认 stderr（与标准库 lastResort 同去向）；每行即 flush |
| `FileSink(path, rotate=…)` | `saintess_engine/log/sinks.py:149` | 追加写；`rotate="size"`（或直接给字节数）按大小轮转 `path.1 … path.N`；父目录自动建 |
| `MemorySink(limit=None)` | `saintess_engine/log/sinks.py:239` | 收进内存；`limit` 保留最近 N 条；`messages()` / `find(level, contains)` |
| `SinkHandler(sinks)` | `saintess_engine/log/sinks.py:283` | 桥接件：把标准库 record 交给 sink；宿主也可自己 `addHandler` |

`configure(fmt=…)` 通过鸭子类型调用 sink 的 `set_format()` —— 不认识 `fmt` 的 sink（如 `MemorySink`）
自动跳过，不会报错。

## 结构化上下文：`bind`

```python
log = bind(get_logger("battle"), actor="p1")
log.info("命中")                      # record.actor == "p1" → sink 可按字段筛 / 落库
bind(log, target="e9").info("连击")   # 链式叠加（后写覆盖先写；原 adapter 不变）
```

* 上下文进 `record.__dict__` —— `MemorySink` 能按字段查，落库 sink 能直接取列名。
* **保留键直接报错**：`name` / `msg` / `levelname` / `args` / `message` / `asctime` … 凡是与
  `LogRecord` 内置属性冲突的键名 → `ValueError`。标准库碰到这种键会 `KeyError`；
  **静默吞掉用户写的字段是最难查的一类问题**，所以这里 fail-fast。

## 引擎侧收敛

引擎自己的 4 处历史写法（各自 `getLogger("saintess_engine.xxx")`）已全部改为走门面 ——
名字只此**一个来源**：

`events/bus.py:23` · `command/router.py:29` · `command/base.py:98` · `clock/timer.py:37`

`CommandBase.logger_name` 为空 = 用门面默认名（`<prefix>.command`）；宿主显式给名字
（如 `"astrbot"`）则**原样直通**，不套 prefix —— 这是「宿主已经有一套日志体系」时的让路。

## 与结构化流水 `tlog` 的分工

| | `log` | `tlog`（待建） |
|---|---|---|
| 问题 | 此刻出什么事了（运维视角） | 发生过什么、能不能复现（业务视角） |
| 单位 | `LogRecord`（级别 + 消息） | `Record`（kind + 结构化字段） |
| 出口 | 3 个随包 sink | JSONL / 库表 / 回放 |

两者共用**同一套 Sink 心智模型与分发纪律**（逐个隔离 / 零出口零行为 / record 本体交给出口）——
见 [roadmap.md](roadmap.md) 第四节。

## 有意不做

* 不认任何游戏名词、不认数据库、不认玩家（落地方式全在内容侧）
* 不做出口路由规则（要分流就在内容侧写一个 sink，自己判断 record）
* 不替宿主配置 root logger（那是宿主的领地）
