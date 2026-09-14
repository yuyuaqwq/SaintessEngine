# 参考：宿主 API（host contract）

> 一句话：**宿主 = 引擎的壳**。平台插件的代码里没有游戏知识，只有三函数 + 引擎装配 + 四个注入句柄；
> 游戏知识（数据 / 命令实现 / 文案 / 存档表 / 数值策略）全在**数据包**里。
> 同一个宿主换个 `package_dir` 就能跑另一个包 —— 这是本契约存在的理由。

实现：`saintess_engine/host/`（`Host` / `Package` / `Env` / `Scenario` / `BattleOutcome`）。
示例：`examples/host-skeleton/`（**最小适配器示例**，19 行假适配器即可接入）。
门禁：`tests/test_host_contract.py`（26 项）· `tests/test_host_skeleton.py`（4 项）。

---

## 一、三函数（宿主适配器唯一必填面）

```python
class MyAdapter:
    def recv(self):                       # ① 取一条消息；None = 没有新消息（循环自旋）
        return {"uid": ..., "text": ..., "group_id": ..., "is_group": ...,
                "at": [...], "ts": ..., "raw": <平台原始事件>}

    def load_player(self, uid):           # ② 读档；None = 新玩家（引擎会问包要初始档）
        return store.get(uid)

    def save_player(self, uid, data):     # ② 写档：**一条消息一次**（改完必存）
        store[uid] = data

    def say(self, to, text):              # ③ 回话：`to={"uid","group_id"}`；**text 已渲染好**
        platform.send(to, text)
```

`ctx` 七字段（多给忽略）：`uid` · `text` · `group_id` · `is_group` · `at[]` · `ts` · `raw`

**接缝纪律（不可谈判）**：包内**只拿普通 dict 进来、只交普通 dict 出去**。
序列化 / 并发锁 / 落库 / 迁移全在适配器侧。**别把 ORM 对象或连接句柄递给包** ——
那会让包重新依赖宿主，「引擎 + 包」的可替换性当场失效。

## 二、可选钩子（不给也能跑）

| 钩子 | 签名 | 不给时的行为 |
|---|---|---|
| 时间 | `clock() -> float` | `time.time()` |
| 随机 | `rng() -> random.Random` | 系统随机（不可复现） |
| 流水 | `on_tlog(record: dict)` | 丢弃 |
| 额外持久化 | `load_blob(key)` / `save_blob(key, val)` | 进程内 dict |
| 事件总线 | `on_event(name, payload)` | 无 |
| 停机 | `should_stop() -> bool` | 无（`serve_forever()` 的扩展面） |

## 三、包契约

```
<包目录>/game.json                 清单：id / name / engine / entry / domains / created
<包目录>/content/apply.py          entry：install_engine()（全局一次、幂等）
                                          apply_game_content(actor)（每 actor 一次、幂等）
                                          可选 initial_save(uid, ctx)（新玩家初始档 = 内容）
<包目录>/game.json 的 `bind`（可选）      ★ **注入声明**：{"module": "content/index.py", "func": "bind_host"}
                                          声明了 = 引擎在 import 命令模块**之前**，把宿主注入对象
                                          交给这个函数（见 §四「宿主注入面」）；不声明 = 无宿主耦合
<包目录>/content/data/commands.json       ★ 指令**声明**（平台无关元数据）：
                                          patterns / desc / category / usage / order / guards / page_size
<包目录>/content/commands.py              ★ 指令**处理器表**：
                                          COMMANDS = {key: {"guards": [...], "handler": "content.cmds.x:fn"}}
<包目录>/content/guards.py                可选：包侧守卫钩子 GUARDS = {name: callable(env, player)}
<包目录>/content/data|rules/<域>.json     域数据
<包目录>/content/<同名模块>               可选契约半边：bridge / settlement / loot / tlog_collect / flow / effects …
```

**包显式 `initial_save` 返回 `None` / 非 dict = 「本包要求先注册」** → 空档 → `player` 守卫拦截。

## 四、命令通道（声明在包 → 守卫 → `Env` → **包内处理器** → 回话）

```
玩家消息 ──▶ 宿主 recv ──▶ Host.handle(ctx)
                              ├─ load_player（新玩家则问包要 initial_save）
                              ├─ route：命中包内**声明**（正则来自包）
                              ├─ 跑守卫：声明里的 guards
                              │     · 内置名 `player` / `battle`（实现由宿主注入）
                              │     · `hook:<名>` → 包侧 content/guards.py::GUARDS
                              ├─ 构造 Env（注入面，见下）
                              ├─ 调包内 handler（content.cmds.x:fn）
                              └─ 落档：**处理器自己调 `env.save()`**（引擎不代劳 —— 见 §四末）
                                 ＋ 新玩家**建档**由引擎落一次（initial_save 有档时必须落库）
                                 ＋ say（逐段投递）
```

包没给处理器（纯数据包 / 尚未实现）→ **回显声明**（降级说明，不是兼容壳）。
处理器引用坏掉 → **明确回话**（不静默：静默失效是本项目最怕的故障）。

### `Env` 字段（包内只读的注入面）

| 字段 | 含义 |
|---|---|
| `key` | 命中的指令声明 key |
| `uid` / `group_id` | 平台用户 id（已由适配器归一） / 群或私聊容器 id |
| `text` | 本条消息的**参数原文**（已 strip；剥指令关键词用 `arg_text(cmd, aliases)`） |
| `raw` | 平台原始事件（宿主透传；**包内禁解释它**，只许原样传给包侧钩子） |
| `player` | 当前玩家档（普通 dict） |
| `save()` | 改完必存（一条消息一次）；**改了 player 必须调它** |
| `clock()` / `rng` | 墙上时间（秒） / 随机流（`seed_now()` 设种子 → 可复现） |
| `tlog(kind, **fields)` | 流水出口（落不落库由适配器 `on_tlog` 定） |
| `texts` | 文案表（`saintess_engine.text.TextTable` 或 None） |
| `blob_load(key)` / `blob_save(key, val)` | 额外持久化（组队/世界状态这类） |
| `state` | 本轮调用方注入的额外只读上下文（含 `spec` / `prefix` / `package`） |

便捷方法（都只是转发引擎既有原语，不在宿主侧重造第二份）：
`arg_text(cmd, aliases)` → `strip_command` · `page(raw)` → `parse_page` · `page_items(items, page, per_page)`。

### 处理器签名与返回值

```python
def my_cmd(env) -> str | list[str] | Iterable[str] | None: ...
```
返回「**已渲染文本段**」；引擎负责投递（`None` = 空回话）。**渲染属内容**（文案表在包里）。

### 宿主注入面（`inject`：一个 dict，两处用）

宿主用**一个 dict** 把「包运行期需要的宿主对象」交给引擎；引擎在两处用它：

| 时机 | 行为 |
|---|---|
| **加载期** | 包若在 `game.json` 声明了 `bind`，引擎在 **import `content/commands.py` 之前**调 `bind_host(**inject)`。**声明了却没给注入 → `PackageError`**（拒绝静默空跑：否则包会在 import 期炸在包内某模块里，错误指不到根因） |
| **运行期** | `inject` 并入每条消息的 `Env.state`：引擎自有键 `spec` / `prefix` / `package` 在前，注入键在后，**同名以注入为准** |

- 引擎**不解释** `inject` 的键值（零游戏知识，只原样转交）。
- 入口两个：`Host(adapter, package_dir, inject={...})` 与 `load_package(root, inject={...})`（同一个面）。
- `Package.command_handlers()` 只在「包确实没有 `content/commands.py`」时给空表；
  包自己 import 期抛的错**原样抛出**（曾经是 `except Exception → 空表`，把真错吞成静默失效）。

### 落档归处理器（引擎不代劳）

| 事情 | 归谁 |
|---|---|
| 处理一条消息后把改动写回 | **包内处理器**：改完调用 `env.save()` |
| 新玩家**建档**（`initial_save` 返回了非空档） | **引擎**：落库一次（否则"新玩家"永远是瞬时判断） |
| 「哪些字段可写」的过滤 | **适配器**：引擎把整份 player dict 交给 `save_player`，字段策略由宿主定 |

## 五、换包

```python
from saintess_engine.host import Host, load_package
pkg = load_package(package_dir)          # 路径由**配置**给，不是代码里写死
host = Host(adapter, package_dir, seed=12345)
host.boot()                              # 加载包 + 装引擎（install_engine）
host.serve_forever()                     # 或在自己的事件回调里 host.handle(ctx)
```

⚠️ **一个进程一个包**：`entry` 的 import 名（惯例 `content`）是包内相对导入的根，
`load_package()` 会把包目录放进 `sys.path`。「换包能跑」= **换配置 + 重启进程**，不是同进程热切换。

## 六、宿主必须满足的四条（门禁口径）

1. **量**：宿主平台面 ≤2k 行（实际参考实现 ≈1k）；
2. **零包知识**：宿主里 `grep -rEn "包名|from content\." == 0`（注释里的历史说明逐条登记）；
3. **换包能跑**：同一份宿主代码跑两个包各一场；
4. **过门禁**：`tests/test_host_contract.py` + `tests/test_host_skeleton.py`（import 白名单 / 零游戏词汇 /
   适配器接入成本 / 两宿主一致性）。

## 相关

- 包格式（域 / schema / 声明）：[package-format.md](package-format.md)
- 指令声明与文案表（声明驱动）：[declarative-commands-and-texts.md](declarative-commands-and-texts.md)
- 指令声明规格：[command-spec.md](command-spec.md)
- 挂钟与注入（`clock()` 钩子的落点）：[clock-wall.md](clock-wall.md)
- 流水出口（`on_tlog`）：[log.md](log.md)
- 宿主示例：`examples/host-skeleton/`（含 `README.md`、`adapter_template.py` 与 19 行假适配器；
  **不属于 wiki 页**，故此处只给路径不给相对链接）
