# 触发器声明编译器（数据行 → `actor["triggers"]`）

> **归属**：本能力**不在引擎里**（2026-09-23 起）—— 它在扩展包 `extends/ext_combat/`（`battle/declarations.py`）。
> 数据包要用它：`game.json` 里写 `"depends": ["ext_combat"]`。
> 引擎侧只剩通用件，见 `../architecture/boundaries.md`；下文裸文件名（`effect_triggers.py` / `declarations.py`）与行号都在 `extends/ext_combat/battle/` 下。
>
> 模块：`ext_combat.battle.declarations` —— `Declaration`（一条声明行）+ `Compiler`
> （`compile` / `validate` / `unknown_name` / `mount` / `purge` / `events_of`）
> + `compile_rows` / `mount`（模块级入口）。
> 一句话：**把「行表 → `{事件名: [载荷, …]}` → 幂等写进宿主容器」抽成扩展包形状**；
> 事件名取自战斗包的事件全集（`EVENTS`，见 `extends/ext_combat/battle/effect_triggers.py:53`），
> 去重键 / 写策略 / 未知名策略 / 载荷全部由调用方给，**引擎零游戏知识**。
> **不进 battle 门面**：内容侧走子模块直取（`from ext_combat.battle.declarations import Compiler`）。

## 为什么有它

参考实现里，「把数据行翻译成触发声明并挂到 actor 上」这件事被写了 **8 个文件 / 13 处**，
其中**判重动作抄了 6 份、旧名展开循环抄了 4 份、事件名告警只有 1 份**：

| # | 重复 | 现状 |
|---|---|---|
| 1 | **幂等挂载** | 有的逐键判重、有的按 `(动词,目标态)`、有的按 `动作`、有的按 `类型`、有的**完全不判重** |
| 2 | **写策略** | 多数「判重后追加」、「命中就地浅盖」、「未命中前插桶首（执行序）」三种并存 |
| 3 | **旧名展开** | 同一段「外层旧名 → 内层新名元组 → 桶内 extend」被抄 4 遍 |
| 4 | **事件名校验** | 只有带旧名迁移表的那一层告警；其余七处只写引擎原生名，无校验 |

把「用哪个键判同一件事、命中怎么处理、未命中放哪、未知名怎么办、载荷长什么样」这些
**取值**剥掉，剩下的就是本模块的三件形状：**分桶 + 幂等写入 + 事件名校验**。

## 用法

```python
from ext_combat.battle.declarations import Compiler, Declaration, compile_rows, mount
from ext_combat.battle.effect_triggers import EVENTS          # 战斗包事件全集（可默认取）

# ① 注入面（形状层零默认取值：旧名迁移 / 去重键 / 未知名策略 / 归属字段都由内容侧给）
_DECL = Compiler(
    events=EVENTS,                       # 缺省即 EVENTS；给空序列 = 不做未知名校验
    map_event=<旧名 → 新名元组>,          # mapping 形态才用（list 形态直取事件名）
    key_of=<载荷 → 去重键>,               # 缺省 None = 不去重
    on_unknown=<未知名回调>,              # 只告警不改行为；缺省不回调
    host_key="triggers",                 # 宿主容器键（契约词）
    owner_key="_owner",                  # 挂载期归属字段；缺省 None = 不注入
    event_key="event",                   # list 形态行的事件名字段
    action_key="action",                 # 动词字段（只给 action_of / 去重键用）
)

# ② 两输入形态：mapping（现状数据形态）与 list（行 mapping 或 Declaration）
out = _DECL.compile({"旧名": [载荷, ...]})          # → {事件名: [载荷, ...]}（载荷原对象）
out = _DECL.compile([{"event": <事件名>, "action": <动词>, ...}])
_DECL.validate(rows)                                # → 未知名清单（保序去重、不抛）

# ③ 挂载（返回新挂条数；幂等命中的不计）
_DECL.mount(actor, rows, merge="replace", owner=actor)

# ④ 撤除（现状「倍率回落撤声明」的承载口）
_DECL.purge(actor, event=<事件名>, match=lambda d: d.get("action") == <动词>)
```

## 扩展包认什么（契约字段名）

| 层 | 角色键（**字段名**，可注入） | 边界（有意保留的口径） |
|---|---|---|
| 宿主容器 | `host_key`（默认 `triggers`） | 缺失 → 懒建；已存在非 mapping → `TypeError`（fail-closed） |
| 事件名 | 战斗包事件全集 `EVENTS`（`extends/ext_combat/battle/effect_triggers.py`，可注入替换） | **取值**：引擎只做成员判定；未知 → 告警 + 放行 |
| mapping 行 | `{旧事件名: [载荷, …]}` | 桶值必须是 `list`/`tuple`；旧名经 `map_event` 展开（保序） |
| list 行 | `event_key` / `action_key`（默认 `event` / `action`） | 行原对象即载荷；其余键原样搬；`action_key` **不用于分发** |
| 载荷 | ——（**完全不透明、原对象**） | 引擎不读它的键、不拷贝它；非 mapping 载荷一律不去重 |
| 去重键 | `key_of(载荷)` | 缺省 `None` = 不去重；命中后的处理由 `merge` 定 |
| 归属 | `owner_key` | `owner` 给了才 `setdefault(owner_key, owner)`（幂等） |

## 8 条口径分歧（**故意不统一**）

| # | 分歧 | 形状层怎么表达 |
|---|---|---|
| ① | 去重键**五种** | `key_of` 回调：`(动词,目标态)` / `目标态` / `动词` / `类型` / 无（`None`）。键的语义是「同一效果的身份由什么决定」，统一一个键 = 改行为 |
| ② | 写策略**四种** | `merge`：`replace`（命中就地浅盖）/ `keep`（命中保留既有）/ `append`（命中留旧再追加）/ `prepend`（未命中前插桶首 = 执行序；命中不重排） |
| ③ | 归属**两处注入** | 挂载期（`owner` + `owner_key`，`setdefault` 幂等）与消费期（`fire()` 兜底）都留；两处都是 `setdefault`，挂载期那份会被消费期跳过 |
| ④ | 事件名校验**只在迁移层** | 编译器把校验统一给到全部调用点；带旧名迁移的那层可继续用 `map_event` 自己告警（去重缓存仍留内容侧） |
| ⑤ | 未知名：**告警 + 放行，不抛** | `on_unknown` 注入；`validate` 返回清单；`compile` 默认告警一次/未知名但**照常入桶**。fail-closed 会炸掉整场装配 |
| ⑥ | `compile` **不排序事件桶** | 桶键 = 行表插入序；桶内**列表序**是执行序，保序不丢 |
| ⑦ | **两输入形态并存** | mapping 是现状数据形态（改它 = 改数据表）；list 是更通用的新形态。list 形态**不走** `map_event` |
| ⑧ | `action_key` 只用于**去重键与读取**，不用于分发 | 分发（`type` 优先还是 `action` 优先）是 `effects` 的事；编译器只提供 `action_of` |

## 为什么不改 `fire()`

消费端已经在位，且它的口径是**刻意的**：`fire()` 对不在 `EVENTS` 的事件名**静默 `return`**
（防拼写漂移），这是「装错一个名字 = 永不触发且无痕」的既有设计。本批补的是**生产端**校验：
在装配时把未知名收集/告警一次，**但不改变触发行为**。

若把 `fire()` 改成未知名抛错：① 会把「静默失效」换成「整场装配断链」（外层逐步吞异常，
反而更难定位）；② 会动 `effect_triggers.py`（消费端 + `EVENTS` 定义，共享冻结面，本批一字节不
许碰）。**生产端留痕 + 消费端静默 = 配套，不是遗漏。**

## 为什么默认不去重

`key_of` 缺省 `None`（= 不去重）是**最保守的默认**：默认行为必须是「明确不合并」。
若默认 `(动词, 目标态)`，会把参考实现里**有意非幂等**的装配（三流合并靠外层只跑一次）
悄悄改成幂等 —— 那是改行为，而且改得看不出来。去重键是内容侧取值，必须**显式给**；
`key_of` 返回 `None`（或载荷不是 mapping）同样 = 不去重。

## 明确不做

* ❌ 数据行 → 载荷的翻译（各族翻译器）—— 取值，留内容侧
* ❌ 旧事件名迁移表 —— 内容协议，注入 `map_event`
* ❌ `EVENTS` 的定义改造、`fire()` / `apply_effects` 的改造 —— 消费端已在位
* ❌ 效果动词实现 —— 取值，留内容侧
* ❌ 业务语义（哪种情形该撤声明、倍率回落等）—— 编译器只给 `purge`
* ❌ 动词分发（`type` / `action` 优先级）—— `effects` 的事
* ❌ 与 `conditions` 的 fail-closed 校验合并 —— 校验对象与失败语义都不同
* ❌ 进 `battle` 门面 / `saintess_engine` 门面 —— 走子模块直取（减少共享面）

## 不变量（门禁逐条钉住）

* **构造 O(1)**：`Compiler` 只校验注入面 + 存引用；不遍历行表、不建索引、不缓存。
* **two 输入形态等价**：同一逻辑声明，mapping / list 行 mapping / `Declaration` 行三形态落出同构容器。
* **载荷原对象**：`mount` 后桶里就是传入的那个对象（不拷贝、不包壳）。
* **顺序即语义**：外层行表序 → `map_event` 元组序 → 桶内追加序；`prepend` 是执行序。
* **异常不吞**：`map_event` / `key_of` 回调自身抛出的异常原样上抛（「不抛」只指**未知名**不抛）。
* **fail-closed**：注入面缺角色键 / 类型不对当场抛；行缺登记键 → `KeyError`；宿主键处非 mapping → `TypeError`。
* **不建多余键**：`mount` 空行表不建宿主键；`purge` 撤空桶默认**保留**空列表（`drop_empty=True` 才删键）。
* **零取值**：代码路径字符串常量里没有任何游戏取值词（`ast` 扫描钉住）；`EVENTS` 只经 import。

## 与其它形状的分工

| 相邻能力 | 归谁 | 说明 |
|---|---|---|
| 事件总线 / 触发执行 | [events.md](events.md) `fire()` | 消费端；编译器只生产声明，不触发 |
| 名词 → 动词分发与执行 | [effect-actions.md](effect-actions.md) | `effects.apply_effects`；编译器不碰 |
| 效果叠层 / 状态规则 | [effect-rules.md](effect-rules.md) | 与「声明挂在哪」正交 |
| 条件名 → 谓词 | [declarative-commands-and-texts.md](declarative-commands-and-texts.md) | 那是 fail-closed 的判定表，校验对象不同 |
| 数据表本身 | 内容侧 | 行表形态与取值零改动 |

## 已知边界（诚实列出）

* **不校验载荷内容**：载荷不透明，写错字段不会在编译器这一层报错（那是效果执行端的容错）。
* **不做动词分发**：一个载荷该执行什么由 `effects` 决定，编译器只负责挂。
* **不排序事件桶**：`compile` 出的 mapping 是插入序；需要确定序的调用方自己定行表序。
* **空桶不出事件名**：mapping 里某个旧名的载荷列表为空时，不产生该事件的桶（无可挂即无声明），
  `validate` 也因此不会报告这个空桶上的名字。
* **`events_of` 返回原对象**：缺失 → `{}` 且**不建键**；调用方若要快照请自己浅拷。
