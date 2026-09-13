# 官方宿主骨架（host-skeleton）

> 一句话：**第三方拿到一个内容包，只写三个函数就能跑起来。**
> 本目录是"第二个宿主实现"——它证明同一个包能被两个宿主跑（契约 §三 纪律 3），
> 而不是让大家再写一层宿主。

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
> 为什么让调用方给：挑怪 / 算数值 / 选池都是**内容策略**，不该长在宿主里 —— 见 §六「待接点」。

进去以后 **输入一行 = 一条消息**：

```
/help                    # 包信息 + 包内声明条数 + 当前生效的可选钩子
/battle                  # 跑一场演示战斗（示例处理器）
<包内某条指令的原文>      # 声明回显（骨架只读声明，不含处理器实现）
/quit
```

`--seed` 给定时同种子可复现同一场（数值排查用）；不给就走适配器 `rng()` 钩子或系统随机。

---

## 二、三函数对照表（唯一必填）

| # | 函数 | 契约 | 本骨架的 CLI 实现 | 你要换成的 |
|---|---|---|---|---|
| ① | `recv() -> ctx \| None` | None = 没有新消息（骨架自旋） | 从 stdin 读一行 | 平台事件队列取一条 |
| ② | `load_player(uid) -> dict \| None` | None = 新玩家（骨架先造初始档） | `store_sqlite.SQLiteStore` | 你的存储（SQLite/Redis/MySQL 都行） |
| ② | `save_player(uid, data)` | 骨架保证"改完必存"（一条消息一次） | 同上（JSON 列 upsert） | 同上 |
| ③ | `say(to, text)` | `to = {"uid", "group_id"}`；**text 已渲染** | `print` | 平台 SDK 发送 |

`ctx` 的**七个字段**（多给的字段骨架忽略；见 `adapter_template.py` 的映射写法）：

```python
uid: str        # 平台用户唯一 id
text: str       # 已去平台标记的纯文本
group_id: str|None
is_group: bool
at: list[str]   # 本条 @ 的 uid
ts: float       # 墙上时间（秒）
raw: Any        # 平台原始事件对象（骨架不解释，只透传）
```

---

## 三、可选钩子（不给也能跑，给了省事）

| 钩子 | 签名 | 不给时的行为 | 骨架里的落点 |
|---|---|---|---|
| 时间 | `clock() -> float` | `time.time()` | `Host.clock()` |
| 随机 | `rng() -> random.Random` | 系统随机（不可复现） | `Host.seed_now()` → 引擎全局随机流 |
| 流水 | `on_tlog(record: dict)` | 丢弃 | 战斗末段挂包内采集器 + 引擎 `tlog` 出口 |
| 额外持久化 | `load_blob(key)` / `save_blob(key, val)` | 进程内 dict | `Host.blob()` / `put_blob()`（组队/世界状态这类） |
| 事件总线 | `on_event(name, payload)` | 无 | `Host` 战斗观察者尾部（宿主自己的记账） |
| 停机 | `should_stop() -> bool` | 无 | `serve_forever()` 的优雅停机（**骨架扩展面**，非契约） |

---

## 四、目录里有什么

| 文件 | 职责 |
|---|---|
| `main.py` | 装配：`load_package()` → `install_engine()` → `apply_game_content()` → 开一场 → 落档 |
| `adapter_cli.py` | 命令行适配器（**真能玩**，冒烟入口；也是"接一个平台"的最小实例） |
| `adapter_template.py` | 接你自己的 IM：平台事件 → 契约七字段（模板，非可运行） |
| `store_sqlite.py` | `load_player` / `save_player` 的 SQLite 实现（JSON 列 + 一把锁 + `init_db`） |

与包的分工（**接缝纪律**，不可谈判）：

```
包（game.json 那个目录）              宿主（本目录）
────────────────────────────          ────────────────────────────
内容策略 / 数值 / 声明表 / 机制      收消息 / 认人 / 存档 + 锁 + 落库 / 投递 / 时间 / 流水出口
只拿普通 dict 进来、只交普通 dict 出去  ↑ 序列化、并发、迁移全在这边
```

---

## 五、30 分钟接入清单

1. **拿包**：解出一个包目录（有 `game.json`），路径传给 `Host(adapter, package_dir)`。
2. **抄三函数**：照 `adapter_template.py` 填 `recv` / `load_player` / `save_player` / `say`
   （平台差异都在适配器里吸收：@ 标记、群/私聊、时间戳、原始事件）。
3. **存档**：直接 `from store_sqlite import SQLiteStore`，或换成你的存储（形状仍是普通 dict）。
4. **起宿主**：`host = Host(adapter, pkg_dir, scenario=...); host.boot(); host.serve_forever()`；
   也可以在你自己的事件回调里直接调 `host.handle(ctx)`（一条消息一次）。
5. **验证**：`python tests/test_host_skeleton.py`（本仓门禁），看四项是否全绿。

接入成本实测：**20 行**（只填三个函数 + 一个 `rng` 钩子，内存 dict 当存档）——
见 `tests/test_host_skeleton.py` 里的假适配器与 `overnight/d3-host-skeleton.md`。

---

## 六、待接点（包内半边还没进包，骨架先留桩）

| 位置 | 骨架行为 | 包侧补齐后 |
|---|---|---|
| 战斗输入（挑怪/敌组数值） | 由调用方以 `Scenario` 给（宿主侧数据） | 问包要：`entry.open_encounter` / 包内流程 |
| 掉落 | 场景给了池请求就调包内 `content/loot.py::roll`，否则记桩 | 池选择策略进包，宿主只发放 |
| 结算（经验/金币） | `content/settlement.py` 缺失 → 记桩 | 接 `settlement.settle(...)`，发放留宿主 |
| 副本入口 | `content/flow/` 缺失 → 记桩 | 接 `flow.instance_gate / router` |
| 探索/药水效果 | `content/effects/` 缺失 → 记桩 | 接 `effects.poi_effects / potion_effects` |

桩**不留假数字**：缺什么就在 `BattleOutcome.stubs` 里写清"哪半边没进包"。

---

## 七、常见坑（踩过的）

1. **`entry` 是相对导入的根**：`content/apply.py` 靠 `content` 这个名字导入，
   所以骨架把包目录放进 `sys.path` 再 `importlib.import_module("content.apply")`。
   **一个进程一个包**（两个包的 `content` 会撞名）——要同时挂两个包请开两个进程。
2. **`entry` 声明了就必须有文件**：清单里写了 `entry` 而文件缺失 = 坏包，骨架直接报错
   （不静默降级）；不声明 `entry` 的纯数据包**跑不起来**（引擎能读数据，但没有装配入口）。
3. **引擎版本门槛**：`game.json.engine`（如 `">=0.1"`）不满足时**显式报错**，别指望降级能跑。
4. **`install_engine()` 是全局一次、幂等**；`apply_game_content(actor)` 是每个 actor 一次、幂等
   （包内用 `_content_applied` 打标记）。**顺序**：先 `install_engine()`，再装配 actor。
5. **别把 ORM 对象/连接句柄递给包**：接口只认普通 dict。给了会让包重新依赖宿主，
   整个"引擎 + 包"的可替换性当场失效。
6. **存 per-message 一次**：`Host.handle()` 是一条消息一条事务（改完必存）；
   战斗中间态不落盘 = 崩溃后回到战斗前，这是刻意的（要断点续战就自己加）。
7. **同种子复现**：引擎用模块级随机流，所以"设种子"的落点是**战斗构造完成、第一次行动之前**
   调 `random.seed(...)` —— 骨架在 `Host.seed_now()` 里就是这么做的。
8. **`text` 不用你加工**：包已经把文案渲染好了，宿主只管投递（多段/图片/语音走扩展面）。

---

## 八、这道骨架自己怎么被守

`tests/test_host_skeleton.py`（在 `tests/run_all.py` 里）：

* **import 白名单**：骨架只许 import 引擎 + 标准库 + 自己的兄弟模块（不许出现宿主/平台词）；
* **零游戏词汇**：骨架全文不得出现包内职业名 / 技能名 / 已知机制词（**游戏逻辑不许漏进宿主**）；
* **接入成本反证**：现场 20 行假适配器 → 真跑一场 → 伤害 > 0；
* **两宿主一致性（骨架侧半）**：同一配置同一种子下，骨架的伤害数字与包内桥直连口径逐条相同。
