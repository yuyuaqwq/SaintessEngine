# 宿主骨架（host-skeleton）—— **引擎 host 的最小适配器示例**

> 一句话：**拿到一个内容包，只写三个函数就能跑起来。**
> 2026-09-14 起，宿主运行时（`Host` / `load_package` / `Scenario` / `BattleOutcome` / `Env`）
> 已**提升为引擎模块** `saintess_engine.host` —— 本目录随之从「第三个宿主实现」
> 退回成**「引擎 host 的最小适配器示例」**：演示三函数怎么接、声明驱动的命令通道怎么走。
> 契约本体（字段级）：[`docs/engine-wiki/reference/host-api.md`](../../docs/engine-wiki/reference/host-api.md)。

---

## 一、30 秒跑起来（真能玩）

```bash
# 在框架仓根目录（saintess_engine/ 的上一层）
python examples/host-skeleton/adapter_cli.py \
    --package games/orlandia \
    --db /tmp/demo.db \
    --scenario /tmp/scenario.json \
    --seed 12345
```

> `--scenario` 是这场战斗的**输入数据**（玩家档 + 敌组 + 可选掉落池请求，形状见 `main.Scenario`）。
> 为什么让调用方给：挑怪 / 算数值 / 选池都是**内容策略**，不该长在宿主里。

进去以后 **输入一行 = 一条消息**：

```
/help                    # 包信息 + 包内声明条数 + 已实现处理器条数 + 当前生效的可选钩子
/battle                  # 跑一场演示战斗（本示例绑的示例处理器）
<包内某条指令的原文>      # 命中包内声明 → 引擎调**包内处理器**；包没给处理器则回显声明
/quit
```

`--seed` 给定时同种子可复现同一场（数值排查用）；不给就走适配器 `rng()` 钩子或系统随机。

---

## 二、三函数对照表（唯一必填）

完整字段级契约见 [`host-api.md`](../../docs/engine-wiki/reference/host-api.md) §一。速览：

| # | 函数 | 契约 | 本骨架的 CLI 实现 | 你要换成的 |
|---|---|---|---|---|
| ① | `recv() -> ctx \| None` | None = 没有新消息（骨架自旋） | 从 stdin 读一行 | 平台事件队列取一条 |
| ② | `load_player(uid) -> dict \| None` | None = 新玩家（引擎造初始档 / 问包要） | `store_sqlite.SQLiteStore` | 你的存储（SQLite/Redis/MySQL 都行） |
| ② | `save_player(uid, data)` | 骨架保证「改完必存」（一条消息一次） | 同上 | 同上 |
| ③ | `say(to, text)` | `to = {"uid","group_id"}`；**text 已渲染** | `print` | 平台 SDK 发送 |

`ctx` 七字段：`uid` · `text` · `group_id` · `is_group` · `at[]` · `ts` · `raw`
（多给的字段忽略；映射写法见 `adapter_template.py`）

可选钩子（不给也能跑）：`clock()` · `rng()` · `on_tlog(record)` · `load_blob`/`save_blob` ·
`on_event(name, payload)` · `should_stop()`。

---

## 三、目录里有什么

| 文件 | 职责 |
|---|---|
| `main.py` | **示例宿主**（继承引擎 `Host`）：绑一条示例指令 + 一场演示战斗；三函数由适配器给 |
| `adapter_cli.py` | 命令行适配器（**真能玩**，冒烟入口；也是「接一个平台」的最小实例） |
| `adapter_template.py` | 接你自己的 IM：平台事件 → 契约七字段（模板，非可运行） |
| `store_sqlite.py` | `load_player` / `save_player` 的 SQLite 实现（JSON 列 + 一把锁 + `init_db`） |

与包的分工（**接缝纪律**，不可谈判）：

```
包（game.json 那个目录）              宿主（本目录 + 引擎 host）
────────────────────────────          ────────────────────────────
内容策略 / 数值 / 声明表 / 机制      收消息 / 认人 / 存档 + 锁 + 落库 / 投递 / 时间 / 流水出口
命令实现 / 文案渲染 / 存档表结构      平台三函数 + 引擎装配 + 四个注入句柄
只拿普通 dict 进来、只交普通 dict 出去  ↑ 序列化、并发、迁移全在这边
```

---

## 四、30 分钟接入清单

1. **拿包**：解出一个包目录（有 `game.json`），路径传给 `Host(adapter, package_dir)`。
2. **抄三函数**：照 `adapter_template.py` 填 `recv` / `load_player` / `save_player` / `say`
   （平台差异都在适配器里吸收：@ 标记、群/私聊、时间戳、原始事件）。
3. **存档**：直接 `from store_sqlite import SQLiteStore`，或换成你的存储（形状仍是普通 dict）。
4. **起宿主**：`host = Host(adapter, pkg_dir, seed=...); host.boot(); host.serve_forever()`；
   也可以在你自己的事件回调里直接调 `host.handle(ctx)`（一条消息一次）。
5. **验证**：`python tests/test_host_skeleton.py` + `python tests/test_host_contract.py`，看是否全绿。

接入成本实测：**19 行**（只填三个函数 + 一个 `rng` 钩子，内存 dict 当存档）——
见 `tests/test_host_skeleton.py` 里的假适配器。

---

## 五、这道骨架自己怎么被守

`tests/test_host_skeleton.py`（在 `tests/run_all.py` 里）：

* **import 白名单**：骨架只许 import 引擎 + 标准库 + 自己的兄弟模块（不许出现宿主/平台词）；
* **零游戏词汇**：骨架全文不得出现包内职业名 / 技能名 / 已知机制词（**游戏逻辑不许漏进宿主**）；
* **接入成本反证**：现场 19 行假适配器 → 真跑一场 → 伤害 > 0；
* **两宿主一致性**：同一配置同一种子下，骨架的伤害数字与包内桥直连口径逐条相同。

`tests/test_host_contract.py`（2026-09-14 新增）：命令通道逐环 —— 声明命中 / 内置守卫 / 包侧守卫 /
`Env` 字段面 / 处理器返回值规整 / 改完必存 / 坏引用明确回话 / 纯数据包降级。

---

## 六、被搬进引擎的东西（2026-09-14）

| 原位置（本目录） | 现位置 | 为什么 |
|---|---|---|
| `Host`（装配/循环/路由/战斗驱动/落档） | `saintess_engine/host/runtime.py` | 三个宿主（平台插件 / 命令行 / 编辑器）**只有一份编排**才不会三处漂移 |
| `load_package` / `Package` / `PackageError` | `saintess_engine/host/package.py` | 包契约的解析只有一份 |
| `Scenario` / `BattleOutcome` / `StandIns` | `saintess_engine/host/outcome.py` | 通用形状（零游戏知识） |
| —— （新增） | `saintess_engine/host/env.py` | `Env` 注入面 + 守卫调度：**包内处理器**的契约 |
| 示例处理器 / `run_demo_battle` / CLI 入口 | 仍在本目录 `main.py` | 示例特有，不该进引擎 |
