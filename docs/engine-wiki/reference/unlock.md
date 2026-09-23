# `unlock` · 解锁闸门

> **归属**：`extends/ext_life/unlock/__init__.py`（E4，2026-09-21）· **形状，零 hook**
> **为什么建**：引擎已有 `run` / `quest` / `presence`，但**都不是解锁闸门** ——
> `run` 管一次战斗流程、`quest` 管任务状态机、`presence` 管在场集合，
> 没有任何一个的语义是「**这个东西对玩家开放了没有**」。
> 于是内容侧把判据散在各命令分支里：同一道门槛写两遍、改一处漏一处，
> 更糟的是**判不成立时静默 `return`**（玩家看到"什么都没发生"）。

## 零游戏词汇口径

引擎**不出现**「阶段 / 地图 / 指令 / 系统」这些字面量：
`targets[].kind` 的取值集合**由包声明**（包的 `unlock_kinds` 域），
引擎只当**不透明字符串**做等值匹配 —— 引擎不猜"这个 id 属于哪种目标"。

判据也不新造：条件真源一律是 `conditions.Conditions`
（`condition_key` 引用已注册 key，或 `condition` 给声明节点由 `declarative.compile_spec` 编译）。

## 对外形状

```python
from ext_life.unlock import Unlocks, Locked

u = Unlocks(entries,                       # {条目 id: 条目 dict}（包数据）
            conditions=conds,              # conditions.Conditions 实例（条件真源）
            condition_key_of=None,         # 可选 fn(条目 id, 条目) -> 条件 key
            text_of=None)                  # 可选 fn(文案 key) -> 自然语言

u.is_unlocked(("system", "craft"), ctx)    # -> bool
u.gate(("system", "craft"), ctx)           # -> None（放行）| Locked（未解锁）
u.entry_of(("system", "craft"))            # -> 条目 id | None
u.render(locked)                           # -> {"label":…, "locked":…, "progress":…}
u.audit()                                  # -> [问题文案]（只报不改）
```

## 条目字段

| 字段 | 类型 | 必填 | 语义 |
|---|---|---|---|
| `condition` | object（声明节点） | 与 `condition_key` 二选一 | 判「解锁了没有」；形状不合法 ⇒ 装配期 `SpecError` |
| `condition_key` | string | 与 `condition` 二选一 | 引用已注册条件；未注册 ⇒ `UnknownCondition` |
| `targets` | `array<{kind, id}>` | ✅ ≥1 | 这条解锁覆盖哪些东西 |
| `label_key` | string | ✅ | 回执标题的「【？】」（文案表 key） |
| `locked_text` | string | ✅ | 回执正文模板 key |
| `progress_text` | string | 可选 | 回执第三行；不给 ⇒ 回执只有条件行 |
| `order` | integer | 可选（默认 0） | 同目标被多条覆盖时的取条顺序（**不猜，由数据给**） |

**为什么 `targets` 是二元组而不是裸字符串**：同一个目标往往同时是「一个系统 + 若干指令 + 一张地图」，
裸 id 会逼引擎猜它属于哪一种 —— 引擎不许猜。二元组把语义留给内容侧，引擎只做等值匹配。

## ★ 三档行为（fail-closed，逐档可测）

| 档 | 情形 | 行为 |
|---|---|---|
| ① | 目标**未被任何条目覆盖** | **放行** —— R1「不配 = 不存在」。★ 不许把「没声明」当「没解锁」 |
| ② | 目标被覆盖，但条件**未注册 / 声明形状不合法** | **装配期抛**（`UnknownCondition` / `SpecError`）。★ 不许把「没实现」伪装成「未满足」 |
| ③ | 目标被覆盖，条件判**不成立** | `gate()` 返回 `Locked`（**结构**）；命令层必须回执并 `return` |

**档 ② 是这套设计的关键**：把「没实现」和「未满足」分成两种**不同的失败** ——
前者必须**炸在装配期**（开发时就知道），后者才是运行期的正常业务。

## 取条顺序

同一目标被多条覆盖 ⇒ 取 `(order, 声明序)` 最小者。
`audit()` 会报出「同目标多条覆盖且 `order` 重复」——那种情况下取条顺序只靠声明序，**脆**。

`audit()` 三类只报不改：① order 重复 ② 同目标多条覆盖（提示）③ 同条目内文案 key 重复（多半复制粘贴没改）。
