# saintess_engine —— 零游戏知识的通用文字游戏框架

> 纯 Python、零第三方依赖、零游戏名词的**声明驱动**文字游戏框架，分**三层**：
> **引擎** / **扩展包** / **数据包**（依赖方向严格单向，见下）。
> 引擎只提供**机制**（事件总线、时间轴与时钟、文案表、指令路由、存储与存档、日志流水）；
> **游戏能力**（CTB 战斗、任务、地图与副本、经济、社交、产出、对话）在可插拔的**扩展包**里；
> **一款游戏的内容**（技能数值、状态名词、职业资源、被动 proc）在**数据包**里，经 `config` 注入。
> **换一套配置 = 新游戏，引擎代码零改动。**

本 wiki 是 **`saintess_engine` 框架自己的文档**，住在**框架独立仓 `framework-engine`** 的
`docs/engine-wiki/`。面向**第三方扩展包 / 内容包开发者**：想用一个已经跑通、
经过大量回归的引擎骨架，而不是从零写事件总线、结算链与时间轴的人。

> **仓库归属（先读）**：本框架已从游戏仓物理分离为独立仓 **`framework-engine`**（可分发、零游戏知识）。
> 游戏仓 **`dragonfall`**（《奥兰迪亚》）以 **git submodule `framework/`**（固定 commit）引用本框架，
> 它是本框架的**参考实现 + 压力测试**，不是本框架的一部分。
> 下方未显式标注「游戏仓」的路径，均指**框架仓**。

## 三层布局（2026-09-23 包栈重构）

```text
数据包  game-*      games/<包>/         一款游戏的内容（一个进程只允许一个）
                       │  depends（按 id 装扩展包）
                       ▼
扩展包  ext-*       extends/<包>/       可插拔的游戏能力（可互相依赖）
                       │  from saintess_engine …（随便用）
                       ▼
引擎    engine-core saintess_engine/   通用件，零游戏词汇
```

**依赖方向严格单向：数据包 → 扩展包 → 引擎**（门禁 `tests/test_layering.py` 机器钉死）。
反方向一律报错：扩展包 `depends` 数据包 = `PackageError`，依赖成环 = `PackageError`。

- 引擎目录：`saintess_engine/`（**19** 个子包 + **6** 个顶层模块；共 **64** 个 `.py` / **12 772** 行）
  —— 数字由 `tests/test_editor_wiki.py` 逐项对照磁盘锁定，改模块结构必同步（否则门禁红）
- 引擎侧的模块（与 `saintess_engine/__init__.py` 里的「模块布局」同一份口径，全部平级）：
  - **基础** `config`（注入面）· `domains`（引擎默认域集 + 合并规则）· `package`（包栈加载器）
  - **通用原语** `expr/`（表达式求值）· `formula/`（声明式公式表）· `conditions/` · `bonus/` ·
    `grant/` · `acts/`（动作序列执行器：动词注册表 + 按序执行 + 装配期 fail-closed）·
    `gates/`（数值预算门禁）· `wire/` · `_validators/`
  - **运行时** `store/` · `command/` · `events/` · `clock/` · `container/` · `text/` · `session/` ·
    `log/` · `tlog/` · `records/`
  - **宿主** `host/`（包加载 / 会话循环 / 命令通道 / 战斗驱动半边）
- 扩展包目录 `extends/`：引擎自带 **10** 个（见下表）。装法永远是一句话 ——
  数据包 `game.json` 里 `"depends": ["ext_xxx"]`，包栈按拓扑序装（被依赖者在前）
- 数据包目录 `games/`：一款游戏一个包（`games/orlandia` = 《奥兰迪亚》导出包，
  `games/my_game` = 演示包）。**一个进程只允许一个数据包**：指令路由 / 动作注册表 / 文案表 /
  时钟都是进程级单例，两个数据包会互撞 —— 要同时跑两款游戏就开两个进程

### 引擎自带的 10 个扩展包（18 个原语模块搬出后的新家 + 抽包工程新增）

| 扩展包 | 从引擎搬出去的模块 | 它提供什么 |
|---|---|---|
| `extends/ext_combat/` | `battle/` `gauge/` `formation/` `panel/` | CTB / 结算 / 效果 / 面板 / 计量条 / 站位（声明 `provides.battle`） |
| `extends/ext_quest/` | `quest/` | 任务账本 + 目标类型 |
| `extends/ext_world/` | `space/` `run/` | 地图节点与拓扑 · 准入链 / 进度 / 名单 |
| `extends/ext_life/` | `collect/` `periodic/` `timers/` `unlock/` | 收集计数 / 周期 / 倒计时 / 解锁闸门 |
| `extends/ext_economy/` | `trade/` `shelf/` `produce/` | 交易限购 / 货架 / 计时生产 |
| `extends/ext_social/` | `membership/` `presence/` | 成员职位与贡献 / 在场清单 |
| `extends/ext_loot/` | `loot/` | 掉落池 / 档位阶梯 / 槽位挂载 |
| `extends/ext_dialogue/` | `dialogue/` | 对话树与会话游标 |
| `extends/ext_reward/` | ——（2026-09-24 B4a 从**数据包**抽入） | 战斗流水采集半边（`tlog_collect.BattleTLog`：事件 → 流水，靠引擎观察者通道） |
| `extends/ext_achieve/` | ——（2026-09-24 B2a/B2b 从**数据包**抽入） | 条件判定与规则触发的通用形状：`cond.registry` 条件注册表（未知名按默认键兜底 · 声明表整表装配）+ `cond.envs` 环境位图（`EnvCtx` · 词表由调用方注入）+ `rule.engine` 规则触发（`match_cond` 条件判定 / `fire` 触发序列 · 规则表与时段/计数/背包/旗标/模板执行七个句柄全由调用方注入） + `earn.shape` 逐条求值形状（上下文外壳 `EvalCtx` 带钩子表与注入读口 / 参数化条件 `ParamCond` / `earned_flags` 逐条判：注册表命中 → 判定函数、否则参数化兜底、都不中 False） |

### 包栈：三层怎么装起来

```python
from saintess_engine.package import load_stack     # 唯一入口（宿主初始化用；失败抛 PackageError）
stack = load_stack("games/orlandia")               # 数据包目录；扩展包按约定搜索路径找
stack.install()                                    # 按拓扑序 install_engine()（扩展包在前）

from saintess_engine.package import probe_stack    # 工具 / 编辑器 / 子进程用：不抛，装进 dict
probe_stack("games/orlandia")["ok"]
```

| 概念 | 口径 | 落点 |
|---|---|---|
| `kind` | `"game"`（数据包，缺省）/ `"extension"`（扩展包）—— 只认这两个 | `game.json` |
| `depends` | 本包装哪些扩展包（按 id）。允许：数据包 → 扩展包 · 扩展包 → 扩展包；**禁止**：扩展包 → 数据包、成环 | `game.json` |
| 命名空间 | 数据包固定 `content`；扩展包 = 它**目录名**（须 `== id`，靠目录名在 `sys.path` 上取 import 名） | `package.manifest_of` |
| 域分层 | 引擎默认集（`commands` / `texts` / `tlogs`）→ 该包 `depends` 的扩展包声明 → 包自己的声明；后层**整域覆盖**前层 | `saintess_engine.domains.layered_decls`（编辑器与装载口**同一份**） |
| `provides` | 扩展包声明**能力提供者**：`{"battle": "ext_combat.battle.battle:Battle"}`；宿主 / 内容**按键取件**，引擎只认「键 + 引用」，不认识「战斗」这个词 | `PackageStack.provider(key)` |
| 扩展包搜索路径 | ① 环境变量 `SAINTESS_EXTENDS` → ② 数据包同级 `../extends` → ③ 引擎仓 `extends/` | `package.default_ext_dirs` |
| 失败口径 | 全部失败给**可读错误**（`PackageError` 或 `{"ok": False, "errors": [...]}`）：不猜、不兜底、不静默降级 | `package.py` 头注 |

域跟**消费端**走：`effect_rules` / `passive_proc` 住在 `ext_combat`，`maps` / `instances` 住在
`ext_world`，`drop_pools` 住在 `ext_loot` —— 数据包 `depends` 它们，这些域才出现在有效域表里
（引擎默认集只剩通用件自己的 3 个表）。权威规格见 [reference/package-format.md](reference/package-format.md)。

## 索引：路线图 · 形状 · 门禁 · 参考实现

- 路线图（待建形状 / 待搬骨架 / `log`·`tlog` 设计）：[reference/roadmap.md](reference/roadmap.md)
- 已建成的形状（**可拔插**，不配 = 不存在）—— 按层分组，每页顶部都有「归属」块：
  - **引擎侧**（上面那四类通用件自带）：[reference/log.md](reference/log.md)（日志门面）·
    [reference/tlog.md](reference/tlog.md)（结构化流水）·
    [reference/clock-wall.md](reference/clock-wall.md)（挂钟：可注入墙上时间 + 时区）·
    [reference/command-spec.md](reference/command-spec.md)（指令声明表装载：单源派生 + fail-closed）·
    [reference/store-blobs.md](reference/store-blobs.md)（owner 快照仓储 + 命名累计计数：TTL 三出口 / 复合键）·
    [reference/formula.md](reference/formula.md)（声明式公式表：`formula`/`aggregate`/`chain` 三类条目 / 4 种 `ref` 前缀 / V1–V12 fail-closed）·
    [reference/gates.md](reference/gates.md)（数值预算门禁：预算内 / 同组极差 / 成长单调 / 属性 cap / 占比 / 合计，六个纯函数校验器）
  - **扩展包侧**（**不在引擎里** —— 页内「归属」块写明它住哪个包；数据包要用先
    `"depends": ["ext_xxx"]`）：
    **`ext_combat`** → [reference/battle-declarations.md](reference/battle-declarations.md)（触发器声明编译器：五种去重键 / 四种写策略 / 未知名只告警）·
    [reference/panel.md](reference/panel.md)（面板栈：键级 add/mul/set 合成 / `when`·`status`·`weight` / 逐层归因 `trace`·`shares`）·
    **`ext_quest`** → [reference/quest.md](reference/quest.md)（任务形状：目标账本 / 进度提升 / 状态迁移 / 多 parts）·
    **`ext_world`** → [reference/space.md](reference/space.md)（空间形状）·
    [reference/run.md](reference/run.md)（运行形状：准入链 / 进度 / 名单）·
    **`ext_life`** → [reference/unlock.md](reference/unlock.md)（解锁闸门：`(kind,id)` 二元组目标 / 三档 fail-closed / 取条顺序 / `audit` 只报不改）·
    **`ext_loot`** → [reference/loot.md](reference/loot.md)（随机产出：掉落池 / 档位阶梯 / 槽位挂载）·
    **`ext_dialogue`** → [reference/dialogue.md](reference/dialogue.md)（对话树：节点 / 选项 / 条件槽 / 会话游标）·
    **`ext_social`** → [reference/presence.md](reference/presence.md)（在场形状：清单判定 / 当天派生 / 保底冷却）·
    [reference/skill-dimensions.md](reference/skill-dimensions.md)（技能 7 维：`cd`/`cast`/`recover`/`range`/`mp+res_cost`/`power`/功能性扁平键；**形状归包**，schema 住包）
- 分层门禁：`tests/test_layering.py`（依赖方向单向：引擎零游戏原语 / 扩展包只 import 自己的 `depends` /
  数据包不漏声明 / 每个扩展包都被某处用着 —— 逐条见 [architecture/boundaries.md](architecture/boundaries.md)）
- 纯度门禁：`tests/test_engine_purity.py`（AST 静态断言：引擎里每一条**绝对 import 都是标准库** ⇒ 整包可拷走）
- 词表门禁：`tests/test_no_game_vocabulary.py`（`saintess_engine/` `schemas/` `editor/` `examples/` 零某款游戏的专有名词）
- 参考实现（**游戏仓 `dragonfall` 侧**，已导出为数据包 `games/orlandia`）：《奥兰迪亚》内容侧
  （`game/data/battle_rules.py` + `game/services/`）—— 本 wiki **不**把它当规范，只当「可粘贴的真实声明样例」的来源

---

## 30 秒：起一场战斗

下面这段在本仓库**实测跑通**（`hero` 打 `wolf` 一拳 → 34 点伤害；`auto_run` 直到倒下）。
第 ① 段是必需的最小装配集，缺任一项都不能产生伤害 —— 原因见
[concepts/config-injection.md](concepts/config-injection.md) 与
[reference/api.md](reference/api.md) 的「未装配行为」节。

```python
import math
import saintess_engine
from ext_combat import Battle, make_actor
from saintess_engine import config
from ext_combat.battle import formulas as F           # 公式表（2026-09-23 起在扩展包 ext_combat）

# ① 挂最小配置（引擎不内置任何数值/名词；这几样是"能起战斗并打出伤害"的下界）
config.mount(
    formulas=F,
    kinds={"phys": "phys", "magi": "magi", "true": "true", "heal": "heal", "buff": "buff"},
    basic_fallback={"name": "普攻", "kind": "phys", "exprs": ["atk*1.0"]},
    skill_flat_fn=lambda: {"SKILL_FLAT_BASE": 12, "SKILL_FLAT_PER_PLAYER_LV": 1,
                           "SKILL_FLAT_PER_SKILL_LV": 2},
    formula_skeleton_fn=lambda: {"skill_growth": {
        "power_per_lv_divisor": 100, "buff_turns_base": 3, "buff_turns_per_lv": 1,
        "cond_default": 0.05, "mech_default_div": 2,
        "lifesteal_default": 0.2, "lifesteal_per_lv_divisor": 100},
        "skill_learn_cost": {"divisor": 6, "base": 2}},
    # CTB 时间模型：一次行动耗时（形状/参数你定；不装 → Battle(...) 直接抛 EngineNotConfigured）
    time_model_fn=lambda spd, base: base * math.sqrt(50.0 / max(float(spd or 0), 1.0)),
    action_base_fn=lambda action: {"defend": 0.6, "skill": 1.6}.get(action, 1.0),
)

# ② 造两个 actor（同构 dict：玩家与怪没有类型差异）
hero = make_actor("p1", "英雄", "player", kind="player", human_controlled=True,
                  hp=100, max_hp=100, atk=30, spd=60, level=10)
wolf = make_actor("e1", "野狼", "enemy", kind="monster",
                  hp=80, max_hp=80, atk=20, spd=40, level=8)

# ③ 起战斗：sides 是唯一入口
b = Battle(btype="monster", sides={"player": [hero], "enemy": [wolf]})

# ④ 打一拳 → 读日志；⑤ 跑到结束
logs, ended, who = b.human_act("attack", None)
print("\n".join(logs))          # 💥 野狼 受到 34 点伤害！（伤害有 ±15% 波动，实测 28~35）
b.auto_run([])                  # 测试/仿真辅助（内容侧生产路径是 human_act + advance）
print(b.result, hero["hp"], wolf["hp"])   # victory / 80 上下 / 0
```

> 实测记录（本仓库现场跑，非推测）：样例打印 `💥 野狼 受到 34 点伤害！`，
> `auto_run` 后 `result=victory`、`wolf["hp"]=0`、`hero["hp"]` 因随机波动落在 80 附近。

---

## 特性

> 下表大多是**扩展包 `ext_combat`（战斗）**的能力 —— 「层」列写清每行住哪；引擎侧只留通用件。
> 入口列的 `xxx.py` 直链按「**引擎包 → 扩展包 → 游戏包**」的优先级解析（战斗那几个文件现在落在
> `extends/ext_combat/battle/`）。

| 特性 | 一句话 | 入口 | 层 |
|---|---|---|---|
| **全同构 actor** | 玩家/怪/召唤物/变身是同一个 dict 模型，无身份分派 | `make_actor`（`actors.py:60`） | `ext_combat` |
| **单 effects 容器** | 增益/减益/DOT/控制/标记/资源全部是 `actor.effects[key]` 一个容器 | `effects.py` 的 `act_apply` | `ext_combat` |
| **事件总线** | 26 个引擎事件名（`EVENTS`）+ `fire()`；效果声明挂 `actor.triggers` | `effect_triggers.py:53/57` | `ext_combat` |
| **声明表驱动** | 效果行为查 `EFFECT_RULES`；名词→动词查 `EFFECT_ACTIONS` | `game/data/battle_rules.py`（游戏仓侧） | `ext_combat`（表在数据包） |
| **动词注册制** | 8 个引擎动词 + `register_action` 任意扩展（内容侧已扩到 70+） | `effects.py:100` | `ext_combat` |
| **CTB 绝对时刻制** | `ct` = 下次可行动时刻；耗时多少由**内容侧装配**（引擎零公式） | `schedule.py:95` + `time_model_fn` | `ext_combat` |
| **零默认值** | 未声明即无行为（`strict=False` 静默 / `strict=True` 抛错两档） | `config.py:109` | 引擎 |
| **存档/续战** | sides-only JSON，`to_state` / `from_state`，旧档字段迁移 | `serialize.py:34/59` | `ext_combat` |
| **注入式边界** | 引擎不 import 游戏；游戏把公式/面板/技能表 mount 进来 | `config.py:161` | 引擎 |

---

## 导航

| 章节 | 页面 | 读它做什么 |
|---|---|---|
| **上手** | [getting-started/installation.md](getting-started/installation.md) | 拿到引擎、Python 版本、零依赖说明 |
| | [getting-started/first-battle.md](getting-started/first-battle.md) | 手把手：造 actor → 起战斗 → 打一拳 → 读日志 |
| | [getting-started/first-mechanic.md](getting-started/first-mechanic.md) | 手把手：写第一条自定义机制（动词 + 声明 + 装配） |
| **概念** | [concepts/README.md](concepts/README.md) | 概念地图（先读这页） |
| | [concepts/actor-model.md](concepts/actor-model.md) | actor 同构模型 / 字段全集 / `effects`·`triggers`·`ext` |
| | [concepts/event-bus.md](concepts/event-bus.md) | `fire()` 语义 / subject 过滤 / `_owner` 注入 / ctx 约定 |
| | [concepts/declaration-tables.md](concepts/declaration-tables.md) | 为什么不写代码而写声明 |
| | [concepts/effects.md](concepts/effects.md) | 效果容器条目形态与 `EFFECT_RULES` 全谱 |
| | [concepts/ctb-schedule.md](concepts/ctb-schedule.md) | CTB 时间轴与绝对时刻制 |
| | [concepts/config-injection.md](concepts/config-injection.md) | 引擎/游戏边界：为什么引擎不 import 游戏 |
| | [concepts/acts.md](concepts/acts.md) | 动作序列形状：动词登记 / 声明序执行 / 短路 / 装配期 fail-closed |
| **指南** | [guides/write-a-mechanic.md](guides/write-a-mechanic.md) | 写一个机制动作（注册/参数/judge/装配钩子） |
| | [guides/add-a-resource.md](guides/add-a-resource.md) | 加一个职业资源（cap / channels / `when` / `per_dt`） |
| | [guides/add-a-passive.md](guides/add-a-passive.md) | 加一个被动 proc（声明 + 事件选型 + 测试） |
| | [guides/add-an-affix.md](guides/add-an-affix.md) | 加词条 / 装备特效 |
| | [guides/serialize-and-resume.md](guides/serialize-and-resume.md) | 存档与续战、旧档迁移约束 |
| | [guides/testing.md](guides/testing.md) | 给自己的内容写断言 |
| | [guides/use-engine-shapes.md](guides/use-engine-shapes.md) | **用引擎形状做包**（5 个常踩的坑 + 可照抄骨架） |
| **参考** | [reference/api.md](reference/api.md) | 公开 API 逐项（`Battle` 方法 + 各模块函数） |
| | [reference/events.md](reference/events.md) | 26 事件全集：时机 / ctx 字段 / 是否引擎自然点位 |
| | [reference/effect-rules.md](reference/effect-rules.md) | `EFFECT_RULES` 字段 schema |
| | [reference/effect-actions.md](reference/effect-actions.md) | `EFFECT_ACTIONS` 名词→动词映射格式 |
| | [reference/mech-cash.md](reference/mech-cash.md) | `MECH_CASH` 机制兑现声明（mode / key / per_layer / clear） |
| | [reference/passive-proc.md](reference/passive-proc.md) | `PASSIVE_PROC` 声明（event / action / judge / agg / also） |
| | [reference/judges.md](reference/judges.md) | judge 谓词清单（按动作分域） |
| | [reference/channels.md](reference/channels.md) | 渠道时机表 + 两形态 + `when` / `per_dt` |
| | [reference/package-format.md](reference/package-format.md) | **包格式权威规格**：`game.json` 全字段 / 依赖规则 / 命名空间 / 域分层 / 样板包 |
| | [reference/editor-extension-security.md](reference/editor-extension-security.md) | 编辑器扩展面：**为什么**不执行包代码（含包的 JS）/ 将来怎么设计 / 开启红线 |
| **架构** | [architecture/README.md](architecture/README.md) | 模块依赖图 + 一次战斗的模块协作 |
| | [architecture/data-flow.md](architecture/data-flow.md) | 从 `human_act` 到落地的完整调用链 |
| | [architecture/design-decisions.md](architecture/design-decisions.md) | ADR：为什么 actor 同构 / 单容器 / 声明表 / 零默认值 |
| | [architecture/boundaries.md](architecture/boundaries.md) | 三层的物理边界：哪一层能做什么 / 依赖方向 / 门禁在哪 |
| **贡献** | [contributing/setup.md](contributing/setup.md) | 开发环境 + 跑测试 |
| | [contributing/conventions.md](contributing/conventions.md) | 代码约定（零默认值 / 不留兼容壳 / 命名） |
| | [contributing/release.md](contributing/release.md) | 版本与分发、兼容性承诺 |
| **自检** | [_selfcheck.md](_selfcheck.md) | 本 wiki 未能取证的条目清单（「待确认」总表） |

### 本 wiki 相对结构规格的增减

结构来自 `workspace/ENGINE_DOCS_WIKI_SPEC.md`。相对它的清单，本文档集：

- **新增** `_selfcheck.md`：规格要求「诚实标缺口」，故单开一页集中列所有「待确认 / 未能取证」项，
  避免它们散落在正文里被漏读。
- **未建**独立 `index.md`：规格里 `index.md` 是「文档首页」的通用形态，
  本项目 README 已承担门面+导航职责，再建 index 会形成两个入口。若将来发布为独立仓库站，
  建议把本 README 重命名为 `index.md` 而非并存。
- **reference/mech-cash.md 与 passive-proc.md 的定位**：这两张表**物理上属于内容层**
  （`game/data/battle_rules.py`，**游戏仓侧**），由**内容侧装配器**（`game/services/class_mech_proc.py`）消费，
  引擎不认识它们（战斗形状的消费端 2026-09-23 起在扩展包 `extends/ext_combat/`）。它们进 wiki 是因为规格要求，且它们是「第三方照抄一份声明就能接机制」的
  最省力样板；两页开头都显式标注了这个边界。

---

## 缺口速览（详表见 [_selfcheck.md](_selfcheck.md)）

写文档时按代码取证发现的、**当前引擎里没有消费方**的东西。看到它们不要以为是笔误：

- 本节的模块名按「**引擎包 → 扩展包 → 游戏包**」解析：`effects.py` / `stats.py` / `actions.py` /
  `battle.py` / `schedule.py` / `effect_triggers.py` 现在都住在扩展包 `extends/ext_combat/battle/`
  （2026-09-23 搬出），`game/data/skills.py` 在游戏仓（奥兰迪亚）。

- `phase` / `player_low` / `pv_broken` 三个事件在 `EVENTS` 里，但**引擎没有任何 fire 点位**（由上层驱动）。
- `effects["reduce"]` 由 `stats.py` 写入面板，但**伤害路径不消费**它。
- 技能级 `accuracy`（`game/data/skills.py:1466,2284` 两处）与技能级 `crit` 字段**无引擎消费方**。
- `game/data/skills.py` 里有 **20 个** `effect=` 名词既不在 `EFFECT_ACTIONS` 也不是引擎动词 → **静默 no-op**。
- ~~`Battle.dmg_mult` / `Battle.pet` / `Battle._cast_ctx` / `Battle._target_ctx` / `Battle._events` /
  `Battle.__init__(st=…)` / `schedule.HOT_INTERVAL` / `schedule.CAST_ITEM` / `Battle.DEFAULT_CT_WAIT`~~
  —— **2026-09-11 已全部删除**。⚠️ 但 `dmg_mult` / `pet` 不是死字段：它们是
  **「调用方在写、引擎没读」的静默失效功能**（世界 Boss GM 伤害倍率 / 宠物参战），
  处置见 [_selfcheck.md §0.4](_selfcheck.md)。
