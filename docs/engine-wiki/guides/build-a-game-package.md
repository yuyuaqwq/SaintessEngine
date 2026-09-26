# 把一款游戏写成一个数据包

> **适用**：你想用这套引擎做一款新的文字游戏。本文只讲**落地路径**（建什么、放哪、怎么跑）；
> 机制细节看 `reference/package-format.md`，分层边界看 `architecture/boundaries.md`。

## 一句话

引擎不认识你的游戏。你要做的是写一个**数据包**（`games/<你的包>/`）：
在 `game.json` 里点名要哪几块**扩展包**（战斗 / 地图 / 任务 / 经济…），然后把内容填进 JSON
与少量内容侧代码。**引擎那一层你一行都不用改，也不可能改到**（它不 import 你的包）。

```text
数据包（你写的，只能一个）
   ↓ depends
扩展包（可插拔的游戏能力，引擎自带 8 个，也可以自己写）
   ↓ import
引擎（通用件：存储 / 命令 / 事件 / 时钟 / 文案 / 表达式 / 包栈 / 宿主）
```

## 七步

### ① 建骨架

最省事的办法是照抄一个现成的包，或者用编辑器新建（「新建包」向导会把**引擎默认域三件**
`commands` / `texts` / `tlogs` 的空表一起建出来，见 §③★）：

```text
games/<pkg>/
  game.json               清单：id / kind / depends / entry / domains
  content/
    __init__.py
    apply.py              ★ 唯一装配入口（install_engine / apply_game_content）
    data/*.json           数据表（编辑器读写这里）—— **含引擎默认域三件**（§③★）
    rules/*.json          声明表（`kind: "rules"` 的域落这里：effect_rules / passive_proc …）
    mech/*.py             本游戏自己的动词（@register_action 注册进引擎）
  editor/
    domains.json          你**自己的**数据表声明（机制域由扩展包带，别抄过来）
  schemas/                可选：你自己的 schema（不写就回退框架那份）
  tests/                  可选：本包的门禁
```

可照抄的样板：`examples/minimal-game/`（《铆炉回声》，最小但完整 —— 有一场真战斗、一条真委托）。

### ② 点名要哪几块能力

```json
// games/<pkg>/game.json
{
  "id": "my_game", "kind": "game", "name": "我的游戏",
  "engine": ">=0.1",
  "depends": ["ext_combat", "ext_world", "ext_life", "ext_economy", "ext_social", "ext_loot", "ext_dialogue"],
  "entry": "content/apply.py"
}
```

- 引擎自带的 10 个扩展包（见下表）；**用不到就别写** —— 没装就没有那张表、那段逻辑。
- 包栈按拓扑序装（依赖在前）；成环 / 找不到 / 扩展包反向依赖数据包都会**报错点名**，不猜。

| 扩展包 | 给什么 |
|---|---|
| `ext_combat` | 回合制战斗：CTB 调度 / 结算 / 效果 / 面板 / 计量条 / 站位（并声明 `provides.battle`） |
| `ext_quest` | 任务账本 + 目标类型 |
| `ext_world` | 地图节点与拓扑 · 准入链 / 进度 / 名单 |
| `ext_life` | 收集计数 / 周期 / 倒计时 / 解锁闸门 |
| `ext_economy` | 交易限购 / 货架 / 计时生产 |
| `ext_social` | 成员职位与贡献 / 在场清单 |
| `ext_loot` | 掉落池 / 档位阶梯 / 槽位挂载 |
| `ext_dialogue` | 对话树与会话游标 |
| `ext_reward` | 战斗流水采集半边（事件 → 流水；`tlog=None` ⇒ 零行为） |
| `ext_achieve` | 条件判定与规则触发的通用形状：条件注册表（未知名按默认键兜底 · 声明表整表装配）+ 环境位图（词表注入）+ 规则触发（`rule.match_cond` / `rule.fire`，七句柄全注入） |

### ③ 声明你自己的数据表

`editor/domains.json` 里**只写你自己的内容域**（技能 / 职业 / 怪物 / 物品…）：

```json
{ "skills": {"label": "技能", "kind": "data", "schema": "skill.schema.json",
             "primary": "skill", "icon": "⚔️"} }
```

★ 你 depends 的扩展包会**自动**带来它那几个机制域（`effect_rules` / `maps` / `drop_pools`…）——
编辑器里能看到、能编，但**不用你在声明里重复写**。有效域表是这样合的：

```text
引擎默认集（commands / texts / tlogs）
  → 你 depends 的扩展包声明
  → 你自己的 editor/domains.json（同名域整体覆盖前层）
```

（编辑器与数据装载口读的是**同一份**，所以「编辑器里编得到、跑起来读不到」这类事不会发生。）

#### ★ 引擎默认域三件：`commands` / `texts` / `tlogs` —— 新包**必须**自建

上面那张图的第一层不是可选的：这三个域**默认就在你的有效域表里**（除非你显式 `$builtin: false`），
而装载口对「在册却一层文件都没有」是 fail-closed 的 ⇒ **新包不自己建这三张表，就会先吃告警、再读不动。**
空表也是合法形态，所以代价只有三个 `{}` 文件（编辑器「新建包」向导也是这么给你建的）：

```json
// content/data/commands.json        content/data/texts.json        content/data/tlogs.json
{}                                  {}                             {}
// 没有指令 = 零行为；空文案表 = 零行为；没有 kind 声明 = 不做流水校验
```

① **为什么它们在 `BUILTIN_DEFAULT_DOMAINS`（引擎默认集）里声明** —— **域跟消费端走**：
  这三张表的消费端**都在引擎里**，所以域归引擎默认集（内容侧一个词都没有）：

```text
commands  → saintess_engine/command/registry.py   CommandRegistry.from_data（指令注册表）
texts     → saintess_engine/text/template.py      TextTable.from_data（通用文案表）
tlogs     → saintess_engine/tlog/record.py        KindTable.from_data（结构化流水声明表）
```

② **包不提供会怎样** —— 两道，都是 fail-closed（**不静默给空表**）：
  · 装载时就报（不用等有人去读）：`stack.warnings()` / `probe_stack(...)["warnings"]` 里一条
    「引擎默认域 'commands' 声明的文件在**所有层**里都不存在（找过：…）」；
  · 真去读它 → `domain_path()` 抛，逐字：

```text
PackageError: 域 'commands' 声明的文件在所有层里都不存在（找过：['<扩展包>/data/commands.json',
              '<你包>/content/data/commands.json'])
```

③ **`{"$builtin": false}` 是「层作用域」开关** —— 它**只关掉①引擎默认集那一层**，不清空下面各层
  （你 `depends` 的扩展包带来的域照旧生效）：

```text
写了它 ⇒ commands/texts/tlogs 不再在册：「所有层都没有文件」那条告警也就不亮了
        （域都不在有效域表里，装载口没什么可报的）—— 但装载口会**点名**「哪一层写的它 +
        被跳过的域有哪些」，别把它当免费开关。代价（真去读）：
        PackageError: 域 'commands' 既不在任何包的声明里、也不在引擎默认集里
                      —— 声明缺项，拒绝装载（不静默给空表）
```

⇒ 结论：**要么自建这三张空表（推荐，最省事），要么 `$builtin: false` + 自建你自己的**
指令 / 文案 / 流水表并在 `editor/domains.json` 里声明它们。两条路都一样：**文件与声明都得在包里。**

（可复现：`python tests/test_package_stack.py` ⑯~⑱ 与 `python tests/test_editor_declarative_domains.py`；
样板：`examples/minimal-game/`（走 `$builtin: false` 那一路）、`games/my_game/`（三张空表都在）。）

### ④ 填数据

- `content/data/<域>.json`：一个域一个文件（`kind: "data"`）
- `content/rules/<域>.json`：声明表（`kind: "rules"`）
- 文件名与**域 id 同名**；域声明里的 `kind` 决定它落哪个目录。

### ⑤ 写你自己的机制

引擎提供**动词执行器**，你的机制写成注册进它的动作：

```python
# content/mech/actions.py —— 本游戏自己的动词
from ext_combat import register_action        # 战斗动词注册面（来自 ext_combat）

@register_action("my_bleed")                  # 名字由你自己定，引擎只负责按名查表
def my_bleed(battle, actor, ctx, logs):
    ...
```

> **取件口径**：引擎侧只剩通用件（`config` `command` `events` `text` `tlog` `store` …）。
> 凡是被搬进扩展包的（战斗 / 掉落 / 地图 / 对话…），一律 `from ext_<包> import …`；
> 具体符号看那个包的门面 `__init__.py`。

**内容侧最常见的一处接线**是「渠道名 → 引擎事件名」与「时间模型」，见
`examples/minimal-game/content/apply.py`：引擎不内置任何公式，你挂什么它跑什么
（不挂 = 零默认值，不是「悄悄用一套中性公式」）。

### ⑥ 装配入口

`content/apply.py` 只要两个函数，都幂等：

```python
def install_engine():            # 全局一次：把公式表 / 面板 / 技能表 / 声明表挂进引擎 config
def apply_game_content(actor):   # 逐个 actor：把资源渠道 / 机制 / 被动 proc 翻成 triggers
```

### ⑦ 跑起来

```bash
# 编辑器（编数据 / 看校验 / 一键试玩）
python editor/server.py            # 默认 8766，cwd 必须是 framework 根

# 宿主（机器人 / CLI / 任何适配器）
```

```python
from saintess_engine import Host
from saintess_engine.package import load_stack

stack = load_stack("games/my_game")      # 扩展包搜索路径有约定默认，见下
stack.install()
host = Host(adapter, "games/my_game")
```

扩展包搜索路径的**约定默认**（不用手传）：

```text
① 环境变量 SAINTESS_EXTENDS（os.pathsep 分隔，部署/测试可覆盖）
② 数据包同级的 ../extends
③ 引擎仓根的 extends/
传 exts=[] 即「不搜」（门禁要的严格模式）
```

## 什么时候该写扩展包，而不是写进数据包

判据只有一条：**这块能力换一款游戏还会不会这么跑**。

```text
会  → 写扩展包（extends/<包>/）：它属于「这套规则」，多款游戏复用
不会 → 写数据包（content/mech/）：它属于「这款游戏的玩法」
```

扩展包长什么样、`game.json` 要写什么、要不要 `provides`，看
`extends/ext_quest/`（最简单的纯形状库）与 `extends/ext_combat/`（声明了 `provides.battle`）。

## 避坑

```text
· 引擎里**已有的**别重写：任务 / 掉落 / 对话 / 商店 / 生产 / 图鉴 / 队伍 / 地图 / 面板 /
  日志 / 周常都有现成形状 —— 先翻 reference/ 再动手写。
· 数据包**只能一个**（要同时跑两款游戏 → 开两个进程）。理由见 package-format.md。
· 域跟消费端走：你 depends 了谁，编辑器就多出谁的几张表；**别把机制域抄进自己的声明**。
· **引擎默认域三件**（`commands` / `texts` / `tlogs`）**必须自建**（三个 `{}` 空表就够）—— 不建的话
  装载口先报告警、真读时 fail-closed；写 `$builtin: false` 只是换个报法，不是免掉（§③★）。
· 装配方向单向：数据包 → 扩展包 → 引擎。反过来（引擎 import 你的包）由门禁
  `tests/test_layering.py` 钉死，一次都写不进去。
· 装不上的能力要**报得清楚**：宿主取不到 `provides.battle` 时报「这个包栈没有战斗能力」，
  而不是 import 炸 —— 你自己的可选能力也照这个写。
```
