# 快照与计数形状（owner 键单行 JSON + 命名累计计数）

> 模块：`saintess_engine.store.snapshots`（`SnapshotSpec` / `SnapshotRepo` / `declare_snapshot`）
> 与 `saintess_engine.store.counters`（`CounterSpec` / `Counters` / `declare_counters`）。
> 一句话：**按 owner 取一行 JSON 快照（带可选时间戳与过期门）** + **一行若干命名计数字段的白名单 `+δ`**；
> 表名 / 列名 / 时间戳基准 / TTL 数值 / 过期动作 / 哪些列可加 —— 全部由内容侧注入，引擎零取值。

## 为什么有它

参考实现里，同一套形状被手写了好几遍：

| # | 重复 | 现状里的差别（全是**取值**） |
|---|---|---|
| 1 | owner 键单行 JSON 快照 + 时间戳 + TTL | 三份：时间戳基准不同（列 vs 载荷内键）· 过期动作不同（删行 / 打标保留 + 补销毁 / 不管）· 有没有 TTL 不同 |
| 2 | 递归清 `set` 的写入前清洗 | 两份**逐字同构**，第二份的注释自己点名了第一份 |
| 3 | 命名计数器 `col = col + δ` | 五份：键形态三种（单键单列 / 单键多列 / 复合主键单列）· 校验两种（白名单 / 没有） |
| 4 | 手写 upsert SQL 模板 | 同一句 `INSERT … ON CONFLICT(pk) DO UPDATE SET …` 在多处各写各的 |

把它们共有的**形状**抽出来（键是 owner、载荷是 JSON、时间戳与过期门可选、
计数是「白名单 + 自增」），剩下的取值留给注入面。

## 用法

```python
from saintess_engine.store import Database
from saintess_engine.store.snapshots import SnapshotSpec, declare_snapshot
from saintess_engine.store.counters import CounterSpec, declare_counters

db = Database(<路径由调用方定>)          # 引擎不读环境变量、不推导路径

# ① 快照：时间戳在列里（口径「最后活动」）
snap = declare_snapshot(db, SnapshotSpec(
    <表名>, owner=<owner 列>, blob=<JSON 列>, stamp=<时间戳列>,
    expired_key=<过期标记键>,            # keep 判真时打这个键
    extra=(<附加列声明>,)),              # 如展示名
    prepare=<写入前清洗函数>,)            # 如递归清 set；None = 不清

# ② 快照：时间戳在载荷里（口径「创建时刻」）—— stamp 与 stamp_key 二选一
snap2 = declare_snapshot(db, SnapshotSpec(
    <表名>, owner=<owner 列>, blob=<JSON 列>, stamp_key=<载荷内键>))

# ③ 计数：单键一行多列（fields 即白名单）
cnt = declare_counters(db, CounterSpec(<表名>, owner=<owner 列>,
                                       fields=(<列>, <列>, ...)))
# ④ 计数：复合键 (owner, subject) 一格一个值
cnt2 = declare_counters(db, CounterSpec(<表名>, owner=<owner 列>,
                                        fields=(<列>,), subject=<第二维列>))

with db.session() as conn:
    snap.put(conn, <owner>, {<载荷>}, stamp=<调用方的钟>)
    snap.get(conn, <owner>, now=<调用方的钟>, ttl=<秒>,
             keep=<「哪些过期也不删」判据>, on_expire=<过期动作回调>)
    snap.merge(conn, <owner>, {<补丁>}, stamp=...)   # 读→浅合并→写，回合并后载荷
    snap.drop(conn, <owner>); snap.sweep(conn, now=..., ttl=..., keep=...)
    snap.raw(conn, <owner>); snap.stamp_of(conn, <owner>)

    cnt.init(conn, <owner>); cnt.bump(conn, <owner>, <列>=<增量>)   # 白名单外 → ValueError
    cnt.read(conn, <owner>)          # 无行 → {}
    cnt.reset(conn, <owner>); cnt.next_of(conn, <owner>, <列>)      # 后者不写
    cnt.read_subject(conn, <owner>)  # 复合键表专用
```

## 引擎认什么（契约字段名）

| 层 | 角色键（**字段名**） | 边界（有意保留的口径） |
|---|---|---|
| 快照表 | `owner` / `blob` | 列名；引擎不写死任何键名。`blob` 走 `Repository` 的 `json_fields` 编解码 |
| 快照表 | `stamp` / `stamp_key` | 二选一；都给 → 构造期 `ValueError`。两者都没声明还传 `ttl`/`stamp` → 也当场抛 |
| 快照载荷 | `expired_key` | 可缺省；缺省 = 过期且 `keep` 判真时只保留、不打标 |
| 计数表 | `owner` / `fields` / `subject` | `fields` = 白名单（非空、无重复、不含 owner/subject）；`subject` 给了即复合主键 |
| 注入面 | `prepare` / `now` / `ttl` / `keep` / `on_expire` | 清洗规则 / 时钟 / 数值 / 内容判据 / 过期动作 —— 引擎一个都不认 |

> `SnapshotSpec` 与 `CounterSpec` 的 `pk` 只能是形状自带的主键（快照 = `(owner,)`；
> 计数 = `(owner,)` 或 `(owner, subject)`），给了别的值当场 `ValueError` —— 主键是形状，不是取值。

## 口径分歧（**故意不统一**）

| # | 分歧 | 引擎怎么表达 |
|---|---|---|
| ① | TTL 基准：列 vs 载荷内键 | `stamp` / `stamp_key` 二选一显式承载（「最后活动」与「创建时刻」语义不同），不给默认 |
| ② | 过期动作三态（删行 / 打标保留 / 触发销毁） | `keep` + `on_expire` 两个注入口；**默认 = 删**。两个分支都会调 `on_expire`（保留那一支也要补销毁） |
| ③ | 打标不改时间戳 | 打标只写载荷，绝不碰 `stamp`/`stamp_key` —— 否则「过期标记」会被自己续命 |
| ④ | 标量文本 vs 结构载荷 | `put` 只收 `dict`（标量走 `counters` 或内容侧自己转），两种口径不混进一个方法 |
| ⑤ | 「日」计数不做进 `counters` | 周期键 → 一格值归 `periodic.PeriodCounter`；`counters` 只收**永不归零的累计计数**，且**不 import `periodic`** |
| ⑥ | 复合主键计数器单列 | `CounterSpec.subject` 显式承载；每条 subject 一行，不挤进 `fields` 的列 |
| ⑦ | 白名单只在一处 | 收 `**deltas`（动态列名）的接口**必须**白名单 fail-closed；写死 SQL 的调用点保持原样 |
| ⑧ | 无行 → `{}` vs 建行 | `read` 无行回 `{}`（无副作用）；只有 `init` 才建行，两件事分开 |
| ⑨ | 清 `set` 而不是拒收 | `prepare` 注入口承载（历史档把 `set` 落成过字符串，转是修复口径）；默认 `None` |
| ⑩ | `sweep` 不做共享 KV 的前缀扫描 | 只扫自己那张表；按键前缀扫共享表是内容协议，留在内容侧。JSON 坏值的行保守不动 |

## 不变量（门禁逐条钉住）

* **不缓存、不自己开事务**：所有出口收 `conn`，`commit` 一律交调用方；引擎源码零 `.commit(`。
* **不读钟**：`now` 由调用方传；两个模块都不 import 时间/日期/随机库。
* **不拼键**：owner / subject / 前缀都是不透明值，引擎不解释格式。
* **构造 O(1)**：`SnapshotRepo` / `Counters` 构造期不开连接、不遍历数据。
* **取值 O(1)**：`raw` / `get` / `stamp_of` / `put` / `drop` / `count` / `owners` / 计数的
  `read` / `bump` / `reset` / `next_of` 各只发常数条 SQL（`sweep` 是全表扫，明确例外）。
* **顺序即语义**：非 `keep` 分支 `on_expire` 在删行**之前**（回调里行还在）；`keep` 分支打标在
  `on_expire` **之前**（回调拿到的是已打标载荷）；`sweep` 清单按表序返回**过期时的**载荷。
* **fail-closed**：注入面非法 / 白名单外 / 主键形态不符（单键表传 `subject`、复合表不传）
  一律当场抛，不留兜底分支、不留兼容壳。
* **只有标准库 + 相对导入**：两个模块都不 import 内容侧任何东西，也不 import
  `os`/`sys`/`json`/`datetime`/`time`/`calendar`/`random`（json 编解码复用
  `Repository` 的 `json_fields`）。

## 与其它形状的分工

| 相邻能力 | 归谁 | 说明 |
|---|---|---|
| 周期键 → 一格值 / 上限 / 冷却 | [clock-wall.md](clock-wall.md)（`periodic` 那一支） | 跨周期归零是它的活；本形状只收**累计**计数 |
| 一次运行内的节点 / 剩余池 / 预算 | [run.md](run.md) | `run.Progress` 生命周期 = 一次运行；快照是**跨会话**的整段状态 |
| 只读进度集合 + 档位领取 | [run.md](run.md) | `collect` 只读；本形状有**写**（`put` / `bump`） |
| 表级 CRUD 骨架（`Repository`） | 既有 `store` 包 | 本形状**复用**它：建表 / 补列 / JSON 编解码 / upsert 全走既有口，不自开一套 |
| 共享 KV 表（按键前缀的会话 / 标记桶） | 内容侧 | 前缀是内容协议；本形状不认键格式 |

## 已知边界（诚实列出）

* **不落库策略**：表名、列名、主键、TTL、清洗规则、过期动作全在内容侧；引擎只认形状。
* **不做后台定时清扫**：现状就是「惰性读门 + 显式 `sweep`」；引擎不注册回调、不引定时器。
* **不做跨周期归零**：日 / 周 / 月维度指向 `periodic`；本形状要么累计、要么由内容侧自己换键。
* **不做实体宽表**：一行几十列、一列一个实体属性的表不是计数器行，不进 `counters`。
* **不做复杂查询**：除 `owners(prefix=)` / `read_subject(order_by, limit)` 外不提供查询面；
  不生成 JOIN、不做聚合。
* **`sweep` 是全表扫**：这是形状里有意的例外（显式清扫入口），其余出口都是常数条 SQL。

## 门禁

`tests/test_store_blobs_shape.py`（137 断言，单文件自跑，不依赖 pytest）：

* 注入面 fail-closed 逐条（`stamp`/`stamp_key` 同给、owner / blob / fields 空、非法名、
  列重名、`pk` 不符、单键表传 `subject`、复合表不传 `subject`……）。
* 建表形状逐列（含与等价手写 `TableSpec` 的 `PRAGMA` 对照）。
* **TTL 三出口逐格**：未过期 / 过期 + `keep` 假（删行）/ 过期 + `keep` 真（打标保留且不改
  stamp）—— **两种时间戳形态各跑一遍**。
* `sweep` 返回过期清单 + 「内存存活优先」（`keep` 真者不被删）。
* `bump` 白名单外 → `ValueError`；`read` 无行 → `{}`；复合键不同 subject 互不干扰。
* **有牙反证 6 处**（TTL 恒不过期 / `keep` 被忽略 / 打标改 stamp / 白名单放开 /
  `read` 无行回 `None` / 复合键退化），逐处打印「预期变红 / 实测变红」；
  另加两处同坏 + 第三处仍绿的归因探针，以及两条顺序断言。
* 静态面：`store/*.py` 零字段字面量、零取值词、零禁用 import、零 `periodic` import。

引擎侧另有两条既有全仓门禁把关：`tests/test_engine_purity.py`（只相对导入 + 标准库）
与 `tests/test_no_game_vocabulary.py`（零游戏身份词）。
