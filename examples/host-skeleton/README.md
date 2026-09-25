# 宿主骨架（host-skeleton）—— **引擎 host 的最小适配器示例**

> 一句话：**拿到一个内容包，只写三个函数就能跑起来。**
> 2026-09-14 起，宿主运行时（`Host` / `load_stack` / `Scenario` / `BattleOutcome` / `Env`）
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

### 2.1 宿主注入面（`inject`，三函数之外唯一要接的面）

包若在 `game.json` 里声明了 `bind`（形状见
[`package-format.md`](../../docs/engine-wiki/reference/package-format.md) §2.2），宿主就必须用
**一个 dict** 把包运行期要用的宿主对象交进来：

```python
host = Host(adapter, package_dir, inject={"store": my_store},   # 或 load_stack(root, inject=...)
            # ★ 引擎 E2b 起**不再自带**守卫拦截文案 ⇒ 宿主必须声明这两句（属内容）：
            register_hint="未找到你的角色档 —— 请先创建角色。",
            battle_hint="你现在不在战斗中。")
```

* **加载期**：引擎在 import 包命令模块（`content/commands.py`）**之前**调 `bind_host(**inject)`
  （本骨架的 `Host` 已把 `inject` 透传给引擎 `Host`）；
* **运行期**：`inject` 并入每条消息的 `Env.state`（引擎自有键在后让位，**同名以注入为准**）；
* 引擎**不解释** `inject` 的键值（零游戏知识，只原样转交）；
* ★ **宿主若不提供注入、而包又声明了 `bind` → 引擎明确报 `PackageError`**（不是静默空表）。
  这是有意的 fail-closed：与其让包在 import 期炸在包内某模块里，不如在加载处把根因说清楚。

两条可跑的演示（`python examples/host-skeleton/main.py --demo-inject`）：

```
① 零注入   examples/minimal-game 不声明 bind → 不给 inject 也能加载
② 反证     同一份合成包「声明 bind 但不给 inject」→ PackageError
③ 全链路   合成包「声明 bind + 提供 inject」→ 命令表解析成功 → 处理器跑出回话
```

合成包是**临时目录里现写的**（`main.py::write_bind_demo_package`），不新增示例包目录。
反证由 `tests/test_host_skeleton.py` E 段逐条钉住。

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
4. **起宿主**：`host = Host(adapter, pkg_dir, seed=..., register_hint=..., battle_hint=...)`；
   ★ 那两个 `*_hint` 必须给（引擎 E2b 起不带玩家可见文案，命令用到内置 `player`/`battle`
   守卫时缺声明会抛 `EngineNotConfigured` —— 见 §三 的用法与 `adapter_template.py`）。
   `host.boot(); host.serve_forever()`；
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
* **两宿主一致性**：同一配置同一种子下，骨架的伤害数字与包内桥直连口径逐条相同；
* **注入面反证**：合成包声明 `bind` 不给 `inject` → `PackageError`；给了 → 命令表解析成功 +
  处理器跑出回话；`main.py --demo-inject`（子进程）另钉住「零注入包可加载」。

`tests/test_host_contract.py`（2026-09-14 新增）：命令通道逐环 —— 声明命中 / 内置守卫 / 包侧守卫 /
`Env` 字段面 / 处理器返回值规整 / 改完必存 / 坏引用明确回话 / 纯数据包降级。

---

## 六、被搬进引擎的东西（2026-09-14）

| 原位置（本目录） | 现位置 | 为什么 |
|---|---|---|
| `Host`（装配/循环/路由/战斗驱动/落档） | `saintess_engine/host/runtime.py` | 三个宿主（平台插件 / 命令行 / 编辑器）**只有一份编排**才不会三处漂移 |
| `load_stack` / `Package` / `PackageStack` / `PackageError` | `saintess_engine/package.py` | 包契约的解析只有一份 |
| `Scenario` / `BattleOutcome` / `StandIns` | `saintess_engine/host/outcome.py` | 通用形状（零游戏知识） |
| —— （新增） | `saintess_engine/host/env.py` | `Env` 注入面 + 守卫调度：**包内处理器**的契约 |
| 示例处理器 / `run_demo_battle` / CLI 入口 | 仍在本目录 `main.py` | 示例特有，不该进引擎 |
