# 游戏包格式 —— 包栈权威规格（引擎 / 扩展包 / 数据包）

> 回答的问题：**能不能把一款游戏（如《奥兰迪亚》）做成一个"包"，里面既有 JSON 数据、
> 又有它自己写的 Python（注册 handler、机制扩展）？一款游戏的能力（战斗 / 任务 / 副本…）
> 能不能拆成可插拔的包？**
>
> 结论：**能，而且这套格式已经建成并在运行** —— 三层：引擎 `saintess_engine/` ·
> 扩展包 `extends/<包>/` · 数据包 `games/<包>/`；可照抄的两个样板见 §十二。
> 本文把这个格式写死，作为「引擎 + 扩展包 + 数据包」分发形态的权威规格。
>
> 实现真源：`saintess_engine/package.py`（包栈加载器：清单 / 依赖 / 拓扑 / 命名空间 / 域分层）
> 与 `saintess_engine/domains.py`（引擎默认集 + 分层合并规则）。
> 分层边界（谁能 import 谁）见 [architecture/boundaries.md](../architecture/boundaries.md)；
> 宿主侧字段级契约见 [host-api.md](host-api.md)。

---

## 一、包是什么

一个包 = **一个自包含目录**，装「引擎跑这款游戏（或提供这类能力）需要的一切」：

* **数据**（JSON）：技能 / 物品 / 怪物 / 地图 / 掉落池 / 副本……编辑器直接改。
* **声明**（JSON）：状态规则 / 被动触发 / 指令 / 文案 / 流水 kind —— 引擎按声明表查表执行。
* **代码**（Python）：这个包**自己写的**机制动作与装配逻辑 —— 引擎给不出的那部分。
* **清单**（`game.json`）：包的身份证 —— 我叫什么（`id`）· 我是哪一类（`kind`）· 我依赖谁
  （`depends`）· 我怎么被装起来（`entry` / `bind` / `provides`）。

引擎（`saintess_engine/`）**不认识任何一款游戏**，也不 import 任何包；
包反过来 import 引擎的公开 API。方向单一：**包 → 引擎**。

### 1.1 三层：引擎 / 扩展包 / 数据包（2026-09-23）

一个进程里装的不是「一个包」，而是一个**包栈**：

```
引擎（saintess_engine/） → 扩展包（N 个，可互相依赖）→ 数据包（1 个）
```

| 层 | 目录 | `kind` | 装几个 | 装什么 |
|---|---|---|---|---|
| **引擎** | `saintess_engine/` | —— | 就是引擎自己 | 通用件、零游戏词汇：`config` `domains` `package` `store` `command` `events` `clock` `container` `text` `session` `log` `tlog` `records` `conditions` `bonus` `grant` `gates` `wire` `expr` `formula` `host` `version` |
| **扩展包** | `extends/<包>/` | `"extension"` | N（可互相依赖） | 游戏级**能力**：`ext_combat` 战斗 · `ext_quest` 任务 · `ext_world` 世界与副本 · `ext_life` 生活 · `ext_economy` 经济 · `ext_social` 社交 · `ext_loot` 产出 · `ext_dialogue` 对话 |
| **数据包** | `games/<包>/` | 缺省 `"game"` | **1** | 一款游戏的**内容**：职业 / 技能 / 怪物 / 地图 / 委托 / 文案 / 存档形状 |

* **扩展包**只提供「这类事怎么做」，不提供「身份」（职业 / 技能 / 文案属数据包）——
  所以同一份 `ext_combat`，任何数据包都能 `depends` 它来用。它们是**可拔插的**：
  不装 = 这块能力不存在（引擎照样 import、照样跑文字流程）。
* 依赖方向只有两个：`数据包 → 扩展包` 与 `扩展包 → 扩展包`。`扩展包 → 数据包` = 方向错了
  （加载期报错）。加载顺序 = **拓扑序**（被依赖者在前，数据包永远最后）；**成环 → 报错**。
* 门禁 `tests/test_layering.py` 四条钉死方向：① 引擎零 import 游戏原语 / 扩展包；
  ② 扩展包只许 import 引擎 + 自己 `depends` 里的包；③ 数据包 import 的扩展包必须写进 `depends`；
  ④ 没有「丢进去没人用」的孤儿扩展包。
* 域分层见 **§4.4**；命名空间规则见 **§2.3**；扩展包搜索路径见 **§2.4**。

### 1.2 为什么数据包只能有一个（六条硬撞理由）

「只能一个」不是约定俗成，是六处**进程级单例** —— 两个数据包放进一个进程，必撞：

| # | 撞在哪儿 | 为什么两份内容放不下 | 落地在哪 |
|---|---|---|---|
| ① | **Python 命名空间** | 数据包的 import 名固定是 `content`，`sys.modules` 里同名唯一 —— 第二个包 import 进来就是**同一个** `content`，后装的把先装的顶掉 | `manifest_of()`（`namespace = "content"`）· `Package._full` |
| ② | **引擎注入面** | `config` 的挂载表是模块级单槽（`_LOADED` / `_HOOKS` / `_hook_provider`）：公式 / 面板 / 效果规则 / hook 自举器只能挂一份，第二份**静默覆盖**第一份 | `saintess_engine/config.py`（`mount` / `set_config` / `register_hook_provider`） |
| ③ | **指令表与路由** | 指令按 `key` 登记（同 key 重复**默认直接抛** `ValueError：指令 key 重复`，`replace=True` 才覆盖）；「一句话 → 一条指令」的路由是全局判定，两款游戏要抢同一句话 | `command/registry.py::CommandRegistry` |
| ④ | **动作注册表** | `@register_action("名字")` 在 **import 期**写全局表：动作名是全局键，两份内容各有同名动作 = 互相覆盖 | `register_action`（当前住扩展包 `extends/ext_combat/battle/effects.py`）· 内容侧 `content/mech/*.py` |
| ⑤ | **有效域表 / 记录装配点** | 一个进程一份有效域表、一个包根（`pkg_root`）：域按「域 = 一张表」读取，同名域只能有一份真源 | `domains.layered_decls()` · `records.read_domain_decl()`（§4.4） |
| ⑥ | **存档 · 时钟 · 流水** | `load_player(uid)` 的键空间、store 的库、时钟与流水的 kind 表都是进程级的：`uid` 在两款游戏里表示不同的人，「谁在何时做了什么」混成一条时间线 | 引擎 `host`（`store` / `clock` / `tlog` / `KindTable`） |

**结论**：要跑两款游戏 = **开两个进程**（换 `package_dir` 重启即可）。扩展包相反：它不提供
「身份」，同一进程里可以装任意多个。

---

## 二、物理结构

### 数据包（`kind` 缺省 = `"game"`）

```
<数据包目录>/                       ← 传给 load_stack(game_dir, …) 的那个目录
  game.json                        # 清单：id / name / desc / engine / depends / entry / bind / provides…
  editor/
    domains.json                   # 域声明（**域的真源在包** —— 见 §十；缺它 = 回退引擎默认集）
    glossary/<域>.json             # （可选）字段词表：中文名 / 分组 / 控件随包走（第 3 层扩展面）
  schemas/                         # 本包自带的 JSON Schema（按域名声明引用；缺 = 回退框架 schemas/）
    skill.schema.json  …
  content/
    data/                          # 【数据域】编辑器读写
      skills.json  classes.json  monsters.json  affixes.json  items.json
      maps.json    drop_pools.json  instances.json  …
    rules/                         # 【声明表】编辑器读写
      effect_rules.json  passive_proc.json  commands.json  texts.json  tlogs.json
    mech/                          # 【扩展代码】本游戏自己写的机制
      actions.py                   #   @register_action → import 即注册
      …（可再分文件：flow/ · persistence/ · effects/ 等，随包自定）
    apply.py                       # 【装配入口】唯一被引擎回调的文件
  docs/wiki/                       # （可选）包自带文档页 —— 见 §十一
```

包内 Python 的 import 名固定是 **`content`**（进程内唯一，因此包内既有的
`from content.x import y` 一律不用改 —— 也正因如此数据包只能有一个，见 §1.2 ①）。

`game.json` 的 `entry` 字段指向装配入口（惯例 `content/apply.py`）。**可选**：纯数据导出包
（内容侧机制尚未移植、只把 `content/data/*.json` 交给编辑器）不声明它；一旦声明，该文件
**必须存在**（`tests/test_editor_dist.py` 守这条 —— 声明了却缺文件 = 坏包，2026-09-12 的导出包
正踩过）。★ 但**要被 `load_stack()` 装起来**的数据包必须能给出 entry：`plan_stack()` 见到数据包
没有 entry 直接报错（「纯数据导出包不能当栈的底」）—— 也就是说不声明 `entry` 的包只能被编辑器
打开、不能当包栈的底。

### 2.1 `game.json` 字段表（全字段）

| 字段 | 必填 | 形状 | 语义 / 校验（实现：`saintess_engine/package.py`） |
|---|---|---|---|
| `id` | 否 | 字符串 | 包身份；缺省 → 回退目录名。`bind` 的报错文案、`depends` 的引用、`provides` 的层序都用它 |
| `name` / `desc` | 否 | 字符串 | 展示元数据（编辑器 / 宿主命令行）；引擎不解释 |
| `kind` | 否 | `"game"` \| `"extension"` | 缺省 `"game"`。**扩展包必须写 `"extension"`**，否则会被当成数据包；取值不是这两个 → `PackageError`（只认这两个，不猜） |
| `engine` | 否 | 门槛字符串（如 `">=0.1"`） | 版本门槛：不满足 → `PackageError`（**显式报错，不静默降级**） |
| `depends` | 否 | 字符串数组（**扩展包 id**） | 本包依赖哪些扩展包；数据包与扩展包都能声明，**扩展包不许依赖数据包**（见 §4.3）。缺省 = 不装任何扩展包 |
| `namespace` | 否 | 字符串 | **只对扩展包有意义**：Python 命名空间，**必须等于包目录名**（缺省 = `id`；不等 → `PackageError`）。数据包固定 `content`，写不写都一样 |
| `entry` | 否 | 包内相对路径 | 装配入口；数据包惯例 `content/apply.py`、扩展包惯例 `apply.py`（这两个就是各自的缺省值）。**声明了就必须存在**（缺文件 → `PackageError`） |
| `provides` | 否 | `{"<键>": "<模块>:<属性>"}` | ★ **能力提供者声明**（见 2.1.1）。引擎只认「键 + 引用」，**不认识键名**（零游戏词汇）；宿主 / 内容按**键**取件 |
| `domains` | 否 | 字符串数组 | 本包声明的域清单（编辑器 / 状态展示用）。★ 它**不是**域元数据的真源（真源是 `<包>/editor/domains.json`，见 §十），也不参与分层合并 |
| `domain_decl` | 否 | 相对路径 | 覆盖域声明文件位置（缺省：数据包 `editor/domains.json`，扩展包 `domains.json`） |
| `domain_dirs` | 否 | `{"data": …, "rules": …}` | 覆盖本包内的域落点，键 = 域的 `kind`（缺省：数据包 `content/{data,rules}`，扩展包 `{data,rules}`） |
| `bind` | 否 | `{"module": "<包内相对路径 .py>", "func": "<函数名>"}` | ★ **宿主注入声明**（见 2.2）。不声明 = 本包零宿主耦合 |
| `created` | 否 | 字符串 | 建档时间（元数据） |

清单里出现的**不认识**的键：引擎忽略（前向兼容靠它，但别拿它当注册表）。

#### 2.1.1 `provides`：能力提供者（引擎只认「键 + 引用」）

```json
{
  "id": "ext_combat", "kind": "extension", "entry": "apply.py",
  "provides": {"battle": "ext_combat.battle.battle:Battle"}
}
```

* **键叫什么是包的自由**（`battle` / `settlement` / `arena`…）：引擎**零游戏词汇**，只做两件事
  —— ① 按层序找**最近**的声明（数据包优先，其次扩展包，离数据包近的先）；② 把引用解析成对象。
* 取件口：`stack.provider("battle")`（没有任何层声明 → 返回缺省值/`None`）；
  `stack.providers()` = 逐层合并后的表（键 → `(包 id, 引用)`，审计用）。
* **声明了却解析不到 = 报错**（`PackageError`）：静默给 `None` 会把「配错了」变成「这个能力不存在」，
  两种故障分不清。
* 宿主就是这么解耦战斗的：`Host` **不 import** 战斗实现，按 `pkg.provider("battle")` 取件；
  这个栈里没有战斗能力时报一句可读的话（「装 ext_combat 并在数据包 `depends` 里声明即可」），
  而不是 import 就炸。

### 2.2 `bind`：宿主注入声明（可选）

包的代码如果需要**宿主对象**（存档句柄 / 平台客户端 / 通信出口……），不要在包内自己找宿主 ——
在 `game.json` 里声明一个中间人，引擎按契约把宿主的**注入对象**交给它：

```json
{
  "id": "my-game",
  "engine": ">=0.1",
  "entry": "content/apply.py",
  "bind": {"module": "content/index.py", "func": "bind_host"}
}
```

**形状**（两键都必填、都必须是字符串）：

| 键 | 形状 | 含义 |
|---|---|---|
| `module` | 包内相对路径（`.py` 可省） | 中间人模块；按**包根**解析成 import 名（`content/index.py` → `content.index`） |
| `func` | 函数名 | 中间人入口；签名 `func(**inject)`，返回值忽略 |

**语义**（引擎已实现；加载期与运行期用**同一个** `inject` dict）：

* **加载期**：包若声明了 `bind`，引擎在 **import 包命令模块（`content/commands.py`）之前**调
  `func(**inject)` —— 包命令模块因此可以在 import 期就 `from . import index` 并取宿主对象。
* **运行期**：`inject` 并入每条消息的 `Env.state`（引擎自有键 `spec` / `prefix` / `package`
  在前、注入键在后，**同名以注入为准**）。
* 入口是同一个面：`Host(adapter, package_dir, inject={...})` 与 `load_stack(root, inject={...})`。
* 引擎**不解释** `inject` 的键值（零游戏知识，只原样转交）—— 键名与含义由宿主与包约定。

**校验规则**（引擎已实现 → `PackageError`，绝不放行；宁可不跑，也不静默）：

| 情形 | 结果 |
|---|---|
| 声明了 `bind`，但宿主没给注入（`inject` 缺省 / 空 dict） | `PackageError`（**拒绝静默空跑**）—— 否则包会炸在包内某模块里，错误指不到根因 |
| `module` 或 `func` 缺失 / 空串 | `PackageError`（`bind` 声明不完整） |
| `module` 指向的模块 import 失败（文件不存在） | `PackageError` |
| `func` 不在该模块里，或不是可调用对象 | `PackageError`（`bind.func 不可调用`） |
| `bind` 函数自己抛错 | **原样抛出**（引擎不吞：包自己的错就是包自己的错） |
| 没声明 `bind` | 什么也不调（纯数据包 / 无宿主耦合的包照常加载） |

**最小示例**（「声明 `bind` + 提供 `inject`」的完整链路，可照抄成一个新包）：

```
<包目录>/
  game.json                 # bind: {"module": "content/index.py", "func": "bind_host"}
  content/
    index.py                # 中间人：宿主对象只从这里进来；取不到就抛（fail-closed）
    commands.py             # 命令模块：import 期就问 index 要宿主对象
    data/commands.json      # 指令声明（真源）
    apply.py                # 装配入口（install_engine / apply_game_content）
```

```python
# content/index.py —— 中间人
_HOST = {}

def bind_host(**objs):                 # 引擎在 import content/commands.py 之前调它
    for key, value in objs.items():
        if value is not None:
            _HOST[key] = value

def get(key):
    if key not in _HOST:
        raise RuntimeError("index：宿主对象 %s 取不到 —— 拒绝静默空跑" % key)
    return _HOST[key]
```

```python
# content/commands.py —— 命令模块：import 期就要求已注入（这就是 bind 的时序意义）
from . import index

_store = index.get("store")            # 宿主没注入 → 这里抛错（根因指到本行）

def hello(env):
    return ["store=%s；Env.state 里同名以注入为准：%s" % (_store, env.state.get("store"))]
```

宿主侧只多一个参数：

```python
host = Host(adapter, package_dir, inject={"store": my_store})
# 或：stack = load_stack(package_dir, inject={"store": my_store})
```

可运行的端到端演示见 `examples/host-skeleton/main.py`（`python main.py --demo-inject`：
零注入跑 `examples/minimal-game` + 内联合成包演示上面这条全链路）——它是 §十二 的第二个样板。
字段级契约见 [host-api.md](host-api.md) §四「宿主注入面」。

---

### 2.3 扩展包：目录名就是命名空间

```
<扩展包搜索路径>/            ← 装扩展包目录的**父目录**（默认见 §2.4；也可显式传 load_stack(..., exts=[…])）
  ext_quest/                 ← 目录名 == id == Python 命名空间（三者不一致 = 加载期报错）
    game.json                {"kind": "extension", "id": "ext_quest", "entry": "apply.py", "depends": […]}
    apply.py                 入口惯例在**包根**：install_engine()（可选 apply_game_content()）
    __init__.py              包门面（`from ext_quest.quest import QuestLog` 走它）
    quest/                   包内实现（`from . import helper` 相对导入照常可用）
      __init__.py  ledger.py  objective.py
    domains.json             本层带的域声明（可选；缺 = 这层不带域）
    data/<域>.json           本层带的「默认值」（可选；数据包要用自己的就整份覆盖）
    rules/<域>.json
    tests/                   包自带门禁（跟引擎仓 `python tests/run_all.py` 一起跑）
```

* **能带**：代码（必须）· 域声明 `domains.json`（可选）· 域默认值 `data|rules/*.json`（可选）·
  `provides` 声明（可选，见 2.1.1）· 宿主注入 `bind`（可选，见 2.2）。
* **不能带**：内容身份（职业 / 技能 / 怪物 / 文案 / 存档形状 —— 那是数据包的）· 另一款游戏的
  数据包（依赖方向错）· 引擎里的游戏原语（引擎零游戏词汇，门禁 §1.1 那条）。
* 落点能用 `domain_dirs` 改名，声明文件位置能用 `domain_decl` 改名。
* 扩展包的 `install_engine()` **可以是空实现**（像 `ext_quest` 那样的纯形状库：形状按需取用、
  不往引擎注册表里塞东西）—— 「入口存在」是为了让加载链对两种包完全同形；写空实现要在
  docstring 里说清为什么，别留含糊的空壳。
* `optional_submodule("commands")` / `bind.module` / handler 引用这些「按名取件」的面，在扩展包里
  都会**自动带上命名空间前缀**（`helper.py` → `<ns>.helper`）。

**为什么扩展包用目录名当命名空间**：数据包的 import 名固定是 `content`（一个进程只有一个数据包，
不会撞）；扩展包可以有多个，各自用自己的 `id` 当命名空间 —— 于是「一个数据包 + N 个扩展包」在同一
进程里互不干扰，包内的相对导入（`from . import x`）也照常可用。

**校验（加载期报错，不猜）**：

| 情形 | 结果 |
|---|---|
| `namespace` ≠ 包目录名 | `PackageError`（扩展包靠目录名在 `sys.path` 上取唯一 import 名，不与数据包的 `content` 冲突） |
| 目录名 ≠ `id` | 同上一条（缺省 `namespace = id` ⇒ 目录名 / `id` / `namespace` 三者必须一致） |
| 搜索路径里两个包 `id` 相同 | `PackageError`（不静默取后见的那一个） |
| 搜索路径某一层目录没有 `game.json`、或它的 `kind` 不是 `extension` | **跳过**（不是扩展包，不当成错） |

### 2.4 扩展包搜索路径：`default_ext_dirs()`

`load_stack()` / `probe_stack()` 不显式给 `exts=` 时，按**约定默认**找扩展包（顺序即优先级）：

```text
① 环境变量 SAINTESS_EXTENDS          ← os.pathsep 分隔（部署 / 测试可覆盖）
② 数据包同级的 ../extends             ← 游戏仓把扩展包放这儿时最省事
③ 引擎仓根下的 extends/               ← 引擎自带的扩展包（ext_combat / ext_quest / …）
```

```python
from saintess_engine.package import load_stack, default_ext_dirs

default_ext_dirs("games/orlandia")                # → ['<引擎仓>/extends']（只返回**存在**的目录，去重、保序）
stack = load_stack("games/orlandia")              # exts 缺省（None）→ 走上面这三条约定
stack = load_stack("games/orlandia", exts=[])     # 显式空 = **一个扩展包都不搜**（门禁的严格模式）
stack = load_stack("games/orlandia", exts=["C:/path/to/extends"])   # 显式给 = 上面三条不参与
```

* 每一条都是「**装扩展包目录的父目录**」（`<base>/<包>/game.json`），只认第一层。
* 路径不存在 → `PackageError`（不静默跳过）；`id` 冲突 → `PackageError`（§2.3）。
* **宿主侧**：`Host(adapter, package_dir, …)` 的 `ext_paths` **缺省是显式空** —— 宿主不给
  `ext_paths` 就**不搜**扩展包（会得到「数据包 X 依赖扩展包 'ext_combat'，但它不在扩展包搜索
  路径里（搜索路径：[]）」）。装带 `depends` 的数据包必须传：
  `Host(adapter, pkg_dir, ext_paths=[<extends 目录>])`。
* 编辑器试玩 / 分发自检 / 门禁走的是**同一套**（`load_stack` / `probe_stack`），不另立一份搜索逻辑。

---

## 三、三层内容，谁改什么

| 层 | 位置 | 谁改 | 引擎怎么用 |
|---|---|---|---|
| 数据 | 数据包 `content/data/*.json` | **编辑器（非程序员）** | 包自查表 → 喂给引擎 |
| 声明 | 数据包 `content/rules/*.json` | **编辑器（非程序员）** | 查表执行（零声明 = 零行为） |
| 代码 | 数据包 `content/mech/*.py`、`apply.py` | **写代码的人** | 装配期调用引擎公开 API |
| 扩展包默认值 | 扩展包 `data|rules/*.json` + `domains.json` | **写能力包的人** | 本层默认值 + 域声明；数据包要用自己的**整份覆盖**（§4.4） |

**关键分工**：编辑器**只碰 JSON**，永远不动 `mech/` 与 `apply.py`。
所以"非程序员用编辑器改数值 / 程序员加机制"两件事互不干扰 —— 这正是包的形状要解决的事。

---

## 四、加载契约

### 4.1 两个入口：`load_stack()`（宿主用） / `probe_stack()`（工具用）

**唯一入口**（宿主初始化走它，要的就是「失败就抛」）：

```python
from saintess_engine.package import load_stack

stack = load_stack("path/to/game", exts=None, inject=None)   # 依赖解析 → 拓扑排序 → 逐个 import
stack.install()                                              # 逐个 install_engine()（扩展包在前）

stack.ids        # ['ext_combat', 'ext_economy', 'ext_quest', 'minimal-game']  ← 拓扑序，数据包永远最后
stack.game       # 数据包对象（栈的身份 = 数据包的身份）
stack.exts       # 扩展包对象列表
```

* `exts`：扩展包搜索路径；`None` = §2.4 那三条约定默认，`[]` = 一个都不搜。
* `inject`：宿主注入对象（§2.2 的 `bind` 用它）。没声明 `bind` 的包，零注入照常装。
* **失败一律 `PackageError`**（可读、点名「谁要的、要谁」），没有「先跑起来再说」。

**工具 / 子进程 / 编辑器走它**（它们要的是一条可读的错误，不是栈）：

```python
from saintess_engine.package import probe_stack

info = probe_stack("path/to/game", install=True)
info["ok"]       # bool
info["errors"]   # [str, …] —— **不抛**：把失败全装进这里
info["plan"]     # [{"kind", "id", "namespace"}, …] ← 拓扑序（含数据包）
info["stack"]    # PackageStack | None
```

* `install=True`：顺带跑 `install_engine()`（「试玩 / 自检」要的是「能装配」，不只是「能 import」）。
* `exts` / `inject` 语义与 `load_stack()` 相同。
* 分发包里那条自检（`DIST_smoke.py`）与编辑器试玩 / 推演 worker 走的都是它。

### 4.2 包契约函数与四条不变量

包的装配入口（数据包 `content/apply.py`、扩展包 `apply.py`）对外只暴露这三个约定：

```python
def install_engine() -> None:
    """全局一次：把本包的公式 / 面板 / 声明表挂进引擎（幂等）"""

def apply_game_content(actor: dict) -> dict:
    """单个 actor：把本包的资源渠道 / 机制 / 被动翻成引擎认的 triggers"""

def initial_save(uid: str, ctx: dict) -> dict:      # 可选
    """新玩家初始档：包给了就用包里的；不给 = 宿主侧最小形状"""
```

* `install_engine()` **每个包都必须给**（缺 → `PackageError`：`… 未提供 install_engine()`）——
  装配不会半途而废。扩展包可以是空实现（见 §2.3）。
* `apply_game_content()` 只有数据包会用到（它挂在栈上，`stack.apply_game_content(actor)` 转发到数据包）。
* `initial_save()` 可选：不给 → 宿主侧最小档；包**显式**返回 `None` / 非 dict = 「本包要求先注册」。

四条不变量：

1. **单向依赖** —— 引擎不 import 包；包只能用 `saintess_engine.__all__` 里的公开 API
   （+ 自己 `depends` 的扩展包）。
2. **import 即注册** —— `mech/*.py` 里的 `@register_action("名字")` 在 import 期生效；
   **不 import 就等于这个动作不存在**（声明表里写了也跑不起来）。
3. **钩子自举** —— 包通过 `config.register_hook_provider(...)` 挂一个回调，
   引擎首次需要装配时回调它（`_lazy_mount`），**包没被 import 时引擎照常按零默认值跑**。
4. **零默认值** —— 表为空 = 该功能不存在，不是"用默认值兜底"。

### 4.3 依赖规则与报错

规则只有三条：

```text
允许   数据包 → 扩展包      game.json 的 depends 列出来，load_stack 按拓扑序装
允许   扩展包 → 扩展包      同上（例如副本包 depends 战斗包）
禁止   扩展包 → 数据包      方向错了 —— 加载期报错
```

**报错表**（全部 `PackageError`，fail-closed：宁可不跑，也不静默降级 / 静默给空表）：

| 情形 | 结果 / 文案要点 |
|---|---|
| 目录里没有 `game.json` | 不是包目录（缺 `game.json`） |
| `game.json` 顶层不是对象 | 顶层必须是对象 |
| `kind` 不是 `game` / `extension` | `kind=… 不认识`（只认这两个） |
| `plan_stack()` 第一个参数不是数据包 | 必须是数据包（`kind=game`） |
| 数据包没声明 `entry` | 「纯数据导出包不能当栈的底」 |
| 声明了 `entry` 但文件不存在 | `包 X 声明了 entry=…，但文件不存在` |
| 数据包 `depends` 的扩展包找不到 | 点名「谁要的、要谁」+ 打印搜索路径 |
| 扩展包 `depends` 的扩展包找不到 | 同上（扩展包视角） |
| 扩展包依赖数据包 | 「方向错了」（只允许 数据包 → 扩展包 与 扩展包 → 扩展包） |
| 依赖成环 | 打印整条环（`a → b → a`） |
| 扩展包搜索路径不存在 | `扩展包搜索路径不存在：…` |
| 两个扩展包 `id` 相同 | `扩展包 id 冲突`（不静默取后见的那个） |
| 扩展包 `namespace` ≠ 目录名 | 命名空间必须等于包目录的目录名（§2.3） |
| `engine` 版本门槛不满足 | `包 X 的引擎门槛不满足：…` |
| `entry` 未提供 `install_engine()` | `包 X 的 entry=… 未提供 install_engine()` |
| `bind` 声明不完整 / 模块 import 失败 / `func` 不可调用 / 宿主没给注入 | 逐条 `PackageError`（§2.2 那张表） |
| `provides` 声明了却解析不到 | `包 X 的能力提供者 provides.<键> 解析不到`（不给 `None`） |
| 域不在任何声明里 / 声明缺 `kind` / 所有层都没该域文件 | `PackageError`（§4.4，「不静默给空表」） |
| 包声明的域声明文件坏 JSON / 顶层不是非空映射 | `PackageError`（编辑器侧另有「黄条告警 + 回退默认集」的路，见 §十.2） |

可复现：`python tests/test_package_stack.py`（15 项，逐条钉住这一组行为）。

### 4.4 域分层：引擎默认集 → depends 的扩展包 → 包声明

**判据一句话**：**域跟消费端走** —— 谁读这张表，域就归谁。

```text
① 引擎默认集              引擎自己的通用表（当前 **3 个**：commands / texts / tlogs）
② 该包 depends 的扩展包    域声明住在 extends/<包>/domains.json：
                          effect_rules · passive_proc → ext_combat
                          maps · instances            → ext_world
                          drop_pools                  → ext_loot
③ 包自己的声明            <包>/editor/domains.json（+ schemas/ + data|rules/*.json）—— **真源在这层**
```

* **同名域整体覆盖前层**（不做字段级补缺 —— 逐字段补缺是编辑器的活，它要在读声明时就报出
  「哪个字段写坏了」）。
* `{"$builtin": false}`（写在包声明里）**只关掉 ①**：它说的是「不要引擎默认集兜底」，
  与「我依赖的扩展包带来的域」无关 —— 后者照旧生效。
* **合并规则只有一份**：`saintess_engine/domains.py:147` 的 `merge_decls`（单层合并）与同模块的
  `layered_decls`（三层合并）。编辑器 `editor.packages.effective_domains()` 与引擎装载口
  `records.read_domain_decl` **委托的是同一份** ⇒ 域元数据放包内、放扩展包、还是放引擎默认集里，
  两边看到的是**同一份有效域表**（装配点：`saintess_engine/records/__init__.py:590`）。

**装载期怎么读**（`PackageStack`；层序 = 拓扑序 + 数据包在最后）：

| 调用 | 作用 |
|---|---|
| `stack.domain_decl()` | 分层合并后的**有效域表**。每层只读自己的声明文件；**文件不存在的层跳过**（扩展包可不带声明）；文件在但坏 JSON / 顶层不是非空映射 → `PackageError` |
| `stack.domain_sources(域)` | 该域在各层的**候选文件**（按层序，数据包在最后）→ `[(包, 路径), …]` |
| `stack.domain_path(域)` | 该域**生效**的那一份文件（层序里最靠后的存在者）。`required=False` → 可选半边（缺 = `None`，如文案表、扩展包默认值） |
| `stack.domain(域)` | **分层读**该域的数据（`required=False` + `default=` 专给可选半边） |
| `stack.domain_layers(域)` | ★ **审计**：这个域的值到底来自**哪几层** → `[(包 id, 路径), …]`（只列实际存在的层） |
| `stack.providers()` / `stack.provider(键)` | 逐层合并的**能力提供者**表 / 按键取件（近数据包者胜；声明了却解析不到 → `PackageError`，见 2.1.1） |

**数据分层与域分层同形**：同一个域出现多份文件时，**后层整份覆盖前层**（扩展包给默认值；
数据包要用自己的就整份覆盖 —— 只想改一条 = 把这个域搬进数据包再改）。

可复现：`python tests/test_package_stack.py` 的 ⑤⑥⑦ 三项（数据包那份整份覆盖扩展包默认值 /
扩展包独有的域照样读得到 / `domain_layers` 报出层序），以及 `python tests/test_package_stack.py`
⑧~⑮ 对应的失败路径。

---

## 五、分发：JSON 与 Python **一起**走

导出 zip（编辑器左上角包名 → 导出）走 `os.walk` 收包内全部文件，
只跳过 `.pyc/.pyo/.pyd/.db/.sqlite/.log` —— 因此
**`content/apply.py` 与 `content/mech/*.py` 会在包里一起分发**，不是"只能导数据"。

导出时附两个**不属于包内容**的文件：

| 文件 | 作用 |
|---|---|
| `DIST_README.md` | 这是什么 / 怎么跑 / 引擎要求 |
| `DIST_smoke.py` | 一条命令跑通一场最小战斗（导入后用 `probe_stack()` 自检） |

引擎版本门槛：`game.json` 的 `engine` 字段（如 `">=0.1"`）由框架侧校验，
不满足**显式报错，不静默降级**。

---

## 六、包 vs 引擎：谁该拥有什么

判据只有一条（与 [roadmap.md](roadmap.md) 同源）：

```ini
形状（骨架 / 协议 / 流程）→ 引擎
内容（策略 / 数据 / 这款游戏的假设）→ 包
```

再补一条 2026-09-23 起的新判据（包栈重构的产物）：

```ini
「一类事怎么做」但跨游戏通用（战斗 / 任务 / 地图 / 掉落…）→ 扩展包 extends/<包>/
「这款游戏是什么」（职业 / 技能 / 怪物 / 文案 / 存档形状）    → 数据包 games/<包>/
```

因此下面这些**都该住在包里**（哪怕它们是代码）：

* `@register_action` 自定义动词（引擎给 8 个内置动词，其余由包扩展）
* 装配逻辑（把包的声明表翻成引擎认的结构）
* 这款游戏特有的 handler / 扩展

引擎里**不该出现**任何一款游戏的名词（`职业`、`技能名`、`眩晕` 这些名词住在包的声明表里）；
扩展包里**不该出现**任何一款游戏的取值（职业名 / 技能 id / 数值 —— 那些是数据包的内容）。

---

## 七、把《奥兰迪亚》搬成包：分期路线

现状：奥兰迪亚是**参考实现**（约 12.6 万行），内容散在 Python 模块里
（`game/data/*.py`、`game/commands/*.py`、`game/services/*`），
而包格式是**目标形态**。两者之间靠"搬运"逐步合拢，不是重写。

| 阶段 | 做什么 | 验收 | 现状（2026-09-23） |
|---|---|---|---|
| **P1** | 数据域导出：`game/data/*.py` → `content/data/*.json`（先物品域打样） | 编辑器能打开该域真数据；同步门禁锁住「JSON = 从 Python 重算」 | ✅ **完成**：导出器 `dragonfall/scripts/export_game_package.py`（items 900）、门禁 `tests/test_export_package_sync.py`、覆盖验收 `scripts/verify_package_coverage.py` |
| **P2** | 其余数据域：怪物 / 地图 / 掉落池 / 词条 / 职业 / 装备名册 … | 同上，逐域一条门禁 | ✅ **完成**：包内 75 个域（数据表 + 规则表），条数以覆盖门禁输出为准（§九） |
| **P3** | 声明表迁移：状态规则 / 被动 / 指令 / 文案 / 流水 → `content/rules` 与 `content/data` | 声明与调用不脱节（已有门禁体系） | ✅ **完成**：`effect_rules` / `passive_proc` 落 `content/rules/`；`commands` / `texts` / `tlogs` 落 `content/data/`（按域声明的 `kind`） |
| **P4** | 代码收口：扩展代码 → `content/mech/*.py`（+ `flow/` `persistence/` `effects/`）；装配入口 → `content/apply.py` | 引擎零改动即可跑起包；`mech/` import 即注册生效 | ✅ **主体已落地**：包内已有 `content/apply.py`（`install_engine` / `apply_game_content`）、`content/mech/*`、`content/flow/*`、`content/persistence/*`、`content/facade.py`（应答 `bind`），`game.json` 声明 `entry` + `bind`；宿主仓门禁驱动整包（游戏仓 `game/services/*` 仍在逐批切片搬） |
| **P5** | 奥兰迪亚仓瘦身为「宿主 + 包」：宿主只留平台耦合层（QQ / AstrBot 等） | 包可整包导出分发；宿主可替换 | ✅ **已完成拆仓（2026-09-15 B16）**：包独立成仓（见 `games/orlandia/README.md`），引擎仓与宿主仓各挂同一 submodule；宿主仓只留平台耦合层 |

**过渡期铁律**：同一份语义**不许两处各写一份**。P1~P3 期间 Python 仍是真源 →
JSON 由导出脚本生成，并由**同步门禁**断言「派生一致」；改一边不同步就红。

---

## 八、未决问题（待裁决，别当成已定）

1. **代码归属的边界**：一个游戏仓的 `commands/*.py`（含大量业务逻辑）哪些属于包的 `mech/`、
   哪些属于宿主平台层？需要一条可判定的切分判据。（2026-09-23 现状：奥兰迪亚已按
   `content/cmds_*.py` + `content/{flow,persistence,facade}` 落地，判据仍待写成明文。）
2. **`engine` 版本契约**：目前只是字符串比较，包依赖引擎具体能力（如某 shape 存在）
   时尚无能力级声明。
3. **超大包的编辑器体验**：单域上万条 JSON 时的列表/搜索性能 —— ✅ **已收口（2026-09-12）**：
   左栏改**定高虚拟滚动**（DOM 只留视口 ±12 行：2000 条时 2000 行 → 43 行，整表重画 77ms → 7ms）；
   搜索逐键防抖；后端 `domain_status` 改**按条目内容指纹缓存**（列表/概览/校验三条路共用，
   改一条只重算一条：热 178/229/207ms → 31/31/29ms）；列表接口加**可选** `?offset=&limit=`
   （不带参数 = 全量旧行为），前端「先画第一页、其余后台续取」。门禁
   `tests/test_editor_large_package.py`（2000 条合成包：条数/分页并集/冷热阈值/缓存失效/搜索窗口切片）。
4. **包的更新与用户数据**：包升级时玩家的存档/数据库如何迁移，尚无方案。

---

## 九、奥兰迪亚包：已进包 / 还没进包（2026-09-13 盘点）

> ★ **数字请以门禁输出为准，别抄本文**：域清单的真源是包内 `editor/domains.json`；
> 2026-09-23 复核 `games/orlandia/game.json` 的 `domains` 清单 = 106 条，包仓 README
> （2026-09-17 实测）记门禁口径 75 域 / 9445 条 —— 两者口径不同（清单 vs 有落点有 schema 的域），
> 条数随开发变化。下面这一节的逐域数字是 **2026-09-13 B2b 那次盘点的快照**，只作历史对照。

⚠️ 下列**逐域条数**是 **2026-09-13 B2b 那次盘点**的快照（当时合计 24 个域 / 5115 条，
此后收口 / D3 批与 `text_specs` 等陆续进包）—— 它**不等于**当前全量：
`items` 900 / `equip_roster` 687 /
`drop_pools` 596 / `pois` 457 / **`monster_roster` 380** / `monsters` 330 / `skills` 305 /
`texts` 233 / `commands` 194 / `maps` 121 / **`legendary_effects` 93** / `effect_rules` 85 /
`affixes` 76 / `passive_proc` 42 / `instances` 27 / `tlogs` 18 / **`pets` 16** / `classes` 8 /
`loot_vocab` 1（+ 收口/D3 批新增：`npcs` 431 / `sets` 92 / `enhance_table` 10 / `panel_rules` 7 /
`races` 6）。清单与真源模块见 `games/orlandia/README.md`。

★ 引擎默认集只剩 **3 个引擎域**（commands / texts / tlogs）；`effect_rules` `passive_proc`
`maps` `instances` `drop_pools` 这 5 个 2026-09-23 起随消费端住进扩展包（§4.4），
其余域由数据包自己声明。

### 9.1 名册类缺口**已补完**（2026-09-13）

三张「引用有落点」的名册都进包了：`equip_roster`(687) / `pois`(457) / **`monster_roster`(380)**。
其中怪物名册按设计稿 `workspace/editor-large-package-next/overnight/design-monster_roster.md` 落地：

* 键 = 怪 id；覆盖 = 355 六元组 id + 24 隐藏怪表专属 + 1 只个体补正表专属（380 条）；
* 跨来源冲突**不静默选一个**：`lv` 只是**基准值**，规则写在 `lv_rule`（当前 = `field_min`：野外记录最小值），
  每一处现场留在 `lv_variants`（语义化 scope，不用行号）与 `spawns`（`source/map/subarea/slot/line` 证据链）；
  **168 个等级冲突全量保留**；`name`/`role` 取多数值 + `*_variants`；`skills`/`drops` 取**并集**；
  14 个重名如实落 `name_peers`（不静默选一个）；
* **唯一待鱼鱼拍板的**：`lv_rule` 的取值（现在是「野外最小」）。想换成「副本值 / 多数值」只改导出器里那**一个常量**，
  名册的对照字段不用动。
* 闭合验收（`dragonfall/tests/test_monster_roster_closure.py`，已进仓）：`instances` 121 个怪 id 全命中、
  `drop_pools` 的 345 个 `mon:`/`elite:` 名字全命中、重名/等级对照结构齐全。

### 9.2 属「下一个域批次」的内容表（不影响当前包可用性）

盘点把游戏仓 `game/data/*.py`（84 模块）里的主要内容表逐张评估了（完整表见
`workspace/editor-large-package-next/overnight/package-inventory.md` §3），按家族归纳：

| 家族 | 代表表（条数） | 建议 |
|---|---|---|
| 生产/配方 | `CRAFT_RECIPES`(426) · `ALCHEMY_RECIPES`(91) · `COOKING_RECIPES`(59) · `ENCHANT_RECIPES`(7) · `REFINE_*`(15) | 一个 `recipes` 域 |
| 任务 | `MAIN_QUESTS`(70) · `SIDE_QUESTS`(144) · `DAILY_QUESTS`(24) · `WEEKLY_QUESTS`(12) | 一个 `quests` 域 |
| 角色成长 | `ACHIEVEMENTS`(119) · `TITLES`(68) · `COLLECTION_BOOKS`(5) · `SKILL_UP`(305) | 按需拆分 |
| 世界人物 | `NPCS`(362+47+22) · `DIALOGUES`(39) · `FACTIONS`(23) | `npcs` / `dialogues` / `factions` |
| 事件/世界 | `EXPLORE_EVENTS`(146) · `DAILY_MAP_EVENTS`(20) · `WORLD_BOSS_POOL` · `TRIAL_FLOORS`(30) | `events` / `world` |
| 经济 | `SHOP_*`(88) · `GUILD_SHOP_ITEMS` · `HONOR_SHOP` · `AUCTION_POOL` | `shop` |
| 伙伴/坐骑 | ~~`PET_POOL`(26)~~ **✅已进包（`pets` 16）** · `MOUNT_*`(22) · `SUMMONS`(5) | 余下 `mounts` / `summons`（`SUMMONS` 只有 5 条，可并入 `mounts` 一起开） |
| 生活技能 | `FISH_TIERS` · `FISH_POOL`(30) · `FISHING_SPOTS`(11) · `GATHER_*` · `MINING_*` | `fish` / `gather` |
| 其它 | `PROPS`(374) · `PORTALS`(11) · `RACES`(6) · `TIPS`(58) · ~~`LEGENDARY_EFFECTS`(93)~~ **✅已进包** · `SETS`(92) · ~~`MONSTER_MODS`(140)~~ **✅已并入 `monster_roster`** | 按需 |

**不建议进包**（属派生表/索引，进了就是第二份定义）：`MATERIALS_BY_NAME`(686) ·
`EQUIP_ROSTER_BY_NAME`(686) · `INSTANCE_STAGE_MAPS`/`INSTANCE_STAGE_NPCS`（已装配进 `instances.stages[]`）·
`SUBAREA_LINKS`（已装配进 `maps.links`）· `ENSY_*`/`MONSTER_LOCS` 等图鉴反查索引 · `GATHER_MAP_POOLS`（已派生成
`drop_pools` 的 `gather:*` 池）。
**只能随机制走**（不是数据）：`rules.py` 的规则条目、指令守卫实现、`SET_THEMES` 之类参数。

### 9.3 边界：这份包能当什么用 / 不能当什么用

- **能当**：① **内容只读快照** —— 编辑器可完整浏览 / 校验包内全部域、做内容审阅、形状回归、
  掉落 / 副本 / 地图的静态审计（`maps` 空间形状、`instances` 进度、`drop_pools` 展开与运行期逐格
  一致；带 `loot_vocab` 声明的掉落审计 0 问题）；② **可装的包栈** —— `entry`（`content/apply.py`）与
  `bind`（`content/facade.py`）已声明，包内机制（`content/mech/*`）import 即注册，宿主 / 编辑器
  试玩都按 §4.1 的入口装配（域清单真源在包内 `editor/domains.json`）。
- **不能当**：**引擎仓的测试样本** —— 它已拆为独立包仓（§七 P5），引擎仓里只是 submodule；
  改包要去包仓改（流程见 `games/orlandia/README.md` §一），条数一律以包仓 / 宿主仓的门禁输出为准。

---

## 十、编辑器扩展：**域的真源在包**（2026-09-13）

一句话：**加一个域 = 改包内 3 个文件**（域声明 + schema + 数据），框架一行不改。

### 10.1 三个文件

| 改哪 | 形状 | 说明 |
|---|---|---|
| `editor/domains.json` | `{"mech_verbs": {"label": "机制动词", "kind": "data", "schema": "schemas/mech_verbs.schema.json", "primary": "mech_verb", "icon": "🔧"}}` | 域声明。`kind` 决定落点（`data → content/data/`、`rules → content/rules/`）；`schema` 是**包内相对路径**；`primary` = schema `$defs` 里「一条数据」那个 def 名 |
| `schemas/<域>.schema.json` | 普通 JSON Schema（draft 2020-12）；`$defs.<primary>` 是单条形状 | 校验与表单渲染都读它。**不给 = 该域不校验**（编辑器照旧可增删改） |
| `content/data|rules/<域>.json` | `{条目 key: 条目对象}` | 数据本身；编辑器新建包 / 新建条目时会写它 |

（可选第 3 层：`editor/glossary/<域>.json` 字段词表 —— 中文名 / 分组 / 控件随包走，见 §十一.3 的字段深链。）

> 想给**已有**的域换名字/图标/schema：在 `editor/domains.json` 里写**同名域**即可（只写要改的字段，
> 其余沿用默认口径）。同名 → **包赢**，但编辑器会给一条可读告警（不静默）。

### 10.2 合并规则（引擎默认集 = **回退默认集**，不是真源）

层序与合并口径**与装载期完全同一份**（见 §4.4，唯一源 = `saintess_engine.domains.layered_decls`）：

```text
effective_domains(pkg) = ① 引擎默认集 → ② 该包 depends 的扩展包声明 → ③ 包 editor/domains.json
  · 同名域：包声明优先（前面那些层不参与该域取值）；真改了字段 → 一条可读 warning
  · 引擎默认集（**saintess_engine/domains.py:42** 的 BUILTIN_DEFAULT_DOMAINS，当前 **3 个引擎域**：
    commands / texts / tlogs —— 每个都能在 `saintess_engine/` 指到消费端；
    2026-09-23 起 effect_rules / passive_proc / maps / instances / drop_pools **随消费端搬进扩展包**
    （extends/ext_combat · ext_world · ext_loot 的 domains.json），要它们就在 `depends` 里装对应包；
    内容域一个都不内置，否则等于「框架里揣着某个游戏的域」）
    **只在包里没有可用声明时兜底**（第三方包 / 坏包 / 未迁移的老包）—— 它是回退，不是真源
  · ★ 合并规则**只有一份**：`saintess_engine/domains.py:147` 的 merge_decls —— 编辑器
    `effective_domains()` 与**引擎装载口** `records.read_domain_decl` 委托的是同一份
    ⇒ 域元数据放包内、放扩展包、还是放引擎默认集里，两边看到的是**同一份有效域表**
    （2026-09-20 T1 双向迁移演习的「一处装配点」：`saintess_engine/records/__init__.py:590`）
  · {"$builtin": false}：显式声明「本包的域就这些，不要引擎默认集兜底」（examples/minimal-game
    用的就是它）；注意它**只关 ①**，② 是「我依赖的包」带来的，照旧生效
  · 坏声明（坏 JSON / 缺 kind / kind 非法 / schema 越界 / 域 id 越界）→ 该条（或整份）忽略 +
    黄条告警 + 回退默认集，**绝不 500**（「列表里有它、点开 500」是不允许的）
  · schema 解析：<pkg>/schemas/<声明值> → <pkg>/<声明值> → 框架 schemas/<声明值> → 不校验
```

**实证（可复现）**：`python tests/test_editor_step3_pkg_first.py` —— 用 monkeypatch 把框架那份
常量**整个置空**后，`games/orlandia` 仍能列出完整域表、能读能写能校验、HTTP 端到端 200
（= 真源确实在包，框架那份可以被整体拿掉）；同一门禁钉住 `examples/minimal-game` 这个**最小样板**
（自带域声明 + schema，覆盖它声明的**全部**域，照它抄就是新游戏的加域姿势）。
另一条**反证**在 `python tests/test_editor_package_domains.py`（§4b）：内置集逐名 == **3 个引擎域** +
**拿掉**包内 `editor/domains.json` → orlandia 的域表立刻只剩引擎默认集那 3 个（内容域真的没有了，
不是换个来源）。

### 10.3 什么时候才该动框架

- **给某个游戏加/改域** → 只改那个包（§10.1 那三个文件）。框架那份默认集**不用动**。
- **改内置默认集** → 只有当你要换掉「所有没声明的包的兜底域集」时才动它；那是**所有包**的口径变更，
  不是给某个游戏加域的手段（`saintess_engine/domains.py:42` 起的常量段 + 该模块头注）。
- 尚未搬进包的框架侧扩展面：字段词典 `editor/glossary.py`、取值提示 `editor/hints.py`、
  专属视图分派 `editor/{loot,instance,space}_view.py`（第 2/3 层扩展面，见设计稿）。

---

## 十一、包内 wiki：`<包>/docs/wiki/**.md`（2026-09-13）

一句话：**包可以自带文档页** —— 编辑器「📖 文档」页按「**包优先、框架兜底**」渲染。
给某个游戏写专属说明，不必去改框架仓的 `docs/engine-wiki/`。

### 11.1 目录约定

```
<包目录>/
  docs/
    wiki/                  # 可选；缺它 = 这个包没自带 wiki（编辑器照旧只显示框架文档）
      README.md            # 相对路径沿用框架那套命名
      getting-started/  concepts/  guides/  reference/  architecture/  …
```

* 只认 `.md`；页的**相对路径就是它的身份**（如 `reference/effect-rules.md`）。
* 左导航的分组由**路径首段**决定，与框架共用同一张分组表（首段不认识 = 归「其他」）。

### 11.2 解析顺序（四条 wiki 路由一致）

| 情形 | 结果 |
|---|---|
| 包内有同名页（相对路径相同） | **包内那份**（框架那份不再参与） |
| 包内没有、框架有 | 回退**框架**页 |
| 两边都没有 | 照旧 404 / `None`（**绝不 500**） |
| `?pkg=` 指向不存在的包 id | 404「包不存在」 |
| 不给 `?pkg=`，或该包没有 `docs/wiki/` | **与没有这个功能时逐项一致**（零回归硬约束） |

页清单 `tree` 是**并集**：包内页 + 未被包内同名页遮住的框架页。`page` / `search` 同名只认包内那份。

### 11.3 字段深链

包词汇表（§10.1 提到的 `editor/glossary/<域>.json`）条目里的 `wiki: ["页.md", "页内词"]` 生成
`wiki:<页>#find=<词>`，这页按 11.2 的顺序解析（**包内页优先 → 框架页兜底**）。
沿用既有纪律：**「页内词」必须真出现在该页正文里**（门禁逐条断言），别编链接；
两边都没有这页 → 该条目**不出链接**（`None`），不凑一个像样的。

### 11.4 源码直链

`file.py:行号` 同样是**包内源码优先 → 框架源码兜底**；包内命中时返回里多一个
`"root": "package"` 标注「这段来自游戏包」。两边都没有 → 照旧明说「读不到」，**不猜**。

### 11.5 边界（**尚未做**的，别当成已定）

* **行号引用自检**（`tools/check_wiki_refs.py` / `tests/test_wiki_refs.py`）目前只扫框架
  `docs/engine-wiki/` —— 包内 wiki 里的行号引用**没有**进这条自检（包内页写行号引用请自己核）。
* 没有「本包只要自己的 wiki、不要框架兜底」的开关（对比域那边的 `{"$builtin": false}`）。
* 编辑器前端的「📖 文档」页目前**不带** `?pkg=`：接口面（四条路由）已就绪，
  前端接线（把当前包 id 传上去、切换包时重载文档树）属于下一步。

---

## 十二、两个可照抄的样板

要动手就先照抄这两个：**① 新能力包抄 `extends/ext_quest`**（最小扩展包）、
**② 新宿主抄 `examples/host-skeleton`**（最小适配器 + 三函数）。
另有一个**最小数据包**样板 `examples/minimal-game`（自带域声明 + schema + `{"$builtin": false}`）。

### 12.1 `extends/ext_quest` —— 最小扩展包（纯形状库）

```
extends/ext_quest/                 ← 目录名 == id == namespace（§2.3）
  game.json                        # 清单：kind=extension · entry=apply.py · 不声明 depends
  apply.py                         # 入口：install_engine() 空实现（形状库不碰引擎注册表）
  __init__.py                      # 包门面（`from ext_quest.quest import QuestLog` 走它）
  quest/{__init__,ledger,objective}.py
  tests/                           # 包自带门禁
  README.md                        # 装法 / 用法 / 边界（照它写自己包的 README）
```

```json
{
  "id": "ext_quest",
  "kind": "extension",
  "name": "任务账本与目标类型",
  "desc": "游戏级能力包：任务账本（QuestLog）+ 目标类型注册表（Objectives）…",
  "engine": ">=0.1",
  "entry": "apply.py",
  "created": "2026-09-23"
}
```

```python
# extends/ext_quest/apply.py
def install_engine() -> None:
    """本包没有引擎级装配（纯形状库）—— 保留函数体为空且显式说明，不留含糊的空壳。"""
    return None
```

数据包要用它：`game.json` 里写 `"depends": ["ext_quest"]`，然后
`from ext_quest.quest import QuestLog, Objectives` 直接取用（引擎的 `load_stack()` 会按拓扑序
把它装好）。需要向宿主 / 内容暴露「一个类」时，在 `game.json` 里加 `provides`
（样板：`extends/ext_combat/game.json` … `"provides": {"battle": "ext_combat.battle.battle:Battle"}`）。

**照抄时的四条**：① 目录名 = `id` = `namespace`；② **必须**写 `kind: "extension"`（否则会被当
数据包）；③ 要别的包的能力就在 `depends` 里声明（`tests/test_layering.py` B/C 两条钉住）；④ 不要
把游戏取值写进扩展包（职业名 / 技能 id / 文案 —— 那是数据包的内容）。

### 12.2 `examples/host-skeleton` —— 最小宿主（三函数 + 注入面）

> 一句话：**拿到一个内容包，只写三个函数就能跑起来。** 契约本体（字段级）见
> [host-api.md](host-api.md)；本目录是**导入后真能玩**的 CLI 实例。

```text
examples/host-skeleton/
  main.py                # 示例宿主（继承引擎 Host）：绑一条示例指令 + 一场演示战斗
  adapter_cli.py         # 命令行适配器（真能玩：`python adapter_cli.py --package <包目录>`）
  adapter_template.py    # 接你自己的 IM：平台事件 → 契约七字段（模板）
  store_sqlite.py        # load_player / save_player 的 SQLite 实现
```

```bash
python examples/host-skeleton/adapter_cli.py \
    --package <包目录> --db /tmp/demo.db --scenario /tmp/scenario.json --seed 12345
```

★ 本 CLI **只有** `--package` 等参数，**没有**「扩展包搜索路径」参数：`--package` 指向的包若带
`depends`，它不传 `ext_paths` 就等于「不搜扩展包」→ 会报「数据包 X 依赖扩展包 'ext_combat'，
但它不在扩展包搜索路径里（搜索路径：[]）」。要在骨架里跑带 `depends` 的包，照下面那三行自己构造
`Host(…, ext_paths=[<extends 目录>])`（或在自己的宿主里接这个参数）。

三函数（唯一必填）：`recv()` · `load_player(uid)` + `save_player(uid, data)` · `say(to, text)`；
可选钩子 `clock()` / `rng()` / `on_tlog(record)` / `load_blob`·`save_blob` / `on_event` /
`should_stop()`。装配是这样走的：

```python
from saintess_engine.host import Host

host = Host(adapter, package_dir, inject={"store": my_store},    # inject ← 包声明了 bind 就必须给（§2.2）
            ext_paths=[<extends 目录>])                           # ★ 不给 = 不搜扩展包（§2.4）
host.boot()          # 内部 = load_stack(package_dir, exts=ext_paths, inject=…) + install_engine()
host.handle(ctx)     # 一条消息一次；平台差异全在适配器里吸收
```

**照抄时的三条**：① 平台差异（@ 标记 / 群私聊 / 时间戳 / 原始事件）只许活在适配器里，
宿主零游戏知识；② 包声明了 `bind` 就必须给 `inject`（不给 = `PackageError`，§2.2）；
③ 装带 `depends` 的数据包必须给 `ext_paths`（不给 = 不搜扩展包，§2.4）。
门禁：`python tests/test_host_skeleton.py`（import 白名单 / 零游戏词汇 / 19 行接入成本反证 /
两宿主一致性 / 注入面反证）与 `python tests/test_host_contract.py`（命令通道逐环）。
