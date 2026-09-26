# 三层的物理边界：引擎 / 扩展包 / 数据包

本页是**三层边界的现状快照**（2026-09-23 包栈重构后）。仓库形态没变：引擎物理分离为独立仓
`framework-engine`（引擎包 `saintess_engine/`），游戏仓（奥兰迪亚）以 `git submodule framework/`
引用它；方案与迁移细节引用游戏仓内部文档 `docs/archive/ENGINE_CONTENT_SPLIT_PLAN.md`
（该文档不进本 wiki 的门面）。

## 边界在哪：一张图

```text
一个进程 = 一次 load_stack(...)：数据包（1 个）+ 扩展包（N 个）+ 引擎

数据包  games/<pkg>/              kind="game"（缺省）· 命名空间固定 content
        · 内容表：技能 / 怪 / 道具 / 词条 / 职业 / 地图 / 文案 …
        · 装配器：数据表 → actor["triggers"] + register_action
        · 命令层：输入 / 展示 / 持久化 / 上层事件（phase 等）
        · 一个进程只允许一个（指令路由 / 动作注册表 / 文案表 / 时钟都是单例）
            │
            │  depends: ["ext_combat", "ext_world", …]
            │  （按 id 装，拓扑序：被依赖者在前；成环 = PackageError）
            ▼
扩展包  extends/<pkg>/            kind="extension" · 命名空间 = 目录名
        · 游戏能力：CTB 战斗 / 任务 / 地图与副本 / 经济 / 社交 / 产出 / 对话
        · 可装 N 个、可互相 depends —— 不提供「身份」，只提供「这类事怎么做」
        · 带自己的 domains.json；可声明 provides（能力提供者）
            │
            │  from saintess_engine …（随便用）
            ▼
引擎    saintess_engine/          通用件，零游戏词汇
        · 基础   config · domains · package（包栈加载器）
        · 原语   expr/ formula/ conditions/ bonus/ grant/ gates/ wire/ _validators/
        · 运行时 store/ command/ events/ clock/ container/ text/ session/ log/ tlog/ records/
        · 宿主   host/（包加载 / 会话循环 / 命令通道 / 战斗驱动半边）
        ✗ 不 import 扩展包 / 数据包；不再有任何游戏原语目录
        ✓ 只读 config 的表 + actor 的字段 + 包栈给的清单
```

依赖方向只有一条：**数据包 → 扩展包 → 引擎**。反向 = 报错（扩展包 `depends` 数据包 →
`PackageError`），成环 = 报错，扩展包偷偷 import 没写进 `depends` 的包 = 门禁红。

## 每层能做什么 / 不许做什么

| 层 | 目录 | 能做什么 | 不许做什么 |
|---|---|---|---|
| **引擎** | `saintess_engine/` | 通用件：注入面（`config`）、域合并规则（`domains`）、包栈加载器（`package`）、表达式 / 公式 / 条件 / 预算门禁、存储 / 指令 / 事件 / 时钟 / 容器 / 文案 / 会话 / 日志 / 流水 / 记录读取、宿主运行时（`host`） | 认识任何游戏原语（`battle/` `quest/` `space/` … 一个目录都不许有）· import 扩展包或数据包 · 写死表名 / 中文名词 / 职业 id |
| **扩展包** | `extends/<pkg>/` | 装游戏能力：类与形状、`install_engine()` 注册动作与规则、自己的 `domains.json` 域声明、可选 `provides` 能力键；可 `depends` 别的扩展包 | `depends` 数据包（报错）· 偷偷 import 没写进 `depends` 的包（门禁 B）· 占「身份」（谁的玩家 / 哪款游戏） |
| **数据包** | `games/<pkg>/` | 装一款游戏的全部内容：数据表 + 声明表 + 装配器（`install_engine()` / `apply_game_content(actor)`）+ 命令层；`depends` 任意扩展包 | 一个进程装两个（指令路由 / 动作注册表 / 文案表 / 时钟都是进程级单例，会互撞 —— 要跑两款游戏就开两个进程）· 要求别人 import 它 |

**判断某个东西该放哪一层**（沿用游戏仓 `game/content_rules/__init__.py:10` 的判据）：

> **凡读游戏表或职业名 → 数据包。** 引擎不得 import 内容包；
> 需要数值时经 `saintess_engine.config` 注入 hook 取。

四条自查问句：

1. 这段代码里出现了**职业 id / 表名 / 中文名词**吗？→ 数据包
2. 这段代码在**别的游戏**里也成立吗？→ 可能引擎侧
3. 换个游戏要改这行吗？→ 数据包
4. 这段代码**任何文字游戏都要**吗？→ 引擎；只有**某一类玩法**要（战斗 / 任务 / 地图 / 掉落…）→ 扩展包

★ 一条经验判据：**域跟消费端走**。某个数据域（`effect_rules` / `passive_proc` / `maps` /
`instances` / `drop_pools` …）住哪一层，看它的消费端代码住哪一层 —— 消费端在引擎 → 域进
引擎默认集（现在只剩 `commands` / `texts` / `tlogs` 三个通用表）；消费端在 `ext_combat` /
`ext_world` / `ext_loot` → 域随包走，落在 `<包>/domains.json`。合并规则只有一份：
`saintess_engine.domains.layered_decls`（编辑器与装载口共用）。

## 机器验证：门禁在哪

| 门禁 | 守什么 | 判据要点 |
|---|---|---|
| `tests/test_layering.py` | **依赖方向**（三层） | A 引擎里零游戏原语目录、零 import 扩展包 / 原语名 · B 扩展包只 import 引擎 / 自己 / 写进 `depends` 的包 · C 数据包 import 的扩展包必须在 `depends` 里 · D 反证：每个扩展包都被某个数据包或样板依赖（没有「丢进去没人用」的孤儿） |
| `tests/test_engine_purity.py` | 引擎**可分发性** | 引擎内每一条**绝对 import 都是标准库**（零动态 import 穿透）· 门面 re-export 齐 · `Battle.from_state` / `to_state` 在 API 面内 · `ext_combat/battle/actions.py` 零 kind 中文字面量 |
| `tests/test_no_game_vocabulary.py` | 框架层**零游戏身份** | `saintess_engine/` `schemas/` `editor/` `examples/` 零某款游戏的专有名词（`games/` 天然带身份，不在扫描内）· `schemas/*.json` 的 `enum` 取值不得含非 ASCII |
| `tests/test_package_stack.py` | 包栈装载契约 | `kind` / `depends` / 拓扑序 / 环检测 / 命名空间 / 域分层 / `provides` |
| `tests/test_editor_wiki.py` | 本 wiki 自己 | 页清单 / 渲染 / 零死链 / 源码直链（同名文件按「引擎包 → 扩展包 → 游戏包」解析）/ README 数字对磁盘 |

跑法：`python tests/run_all.py`（引擎全量 + 示例包冒烟，exit=0 全绿）；单跑一道即可，
例如 `python tests/test_layering.py`。
（游戏仓侧的全量回归是另一回事：`python scripts/run_all_tests.py`，住在游戏仓。）

> 一道诚实备注：`tests/test_engine_purity.py` 的 docstring 里还留着 2026-09-13 那版模块清单
> （写着 `expr/ gauge/ formation/`）。判据以本页与**代码**为准 —— `gauge/` `formation/`
> 2026-09-23 起在 `extends/ext_combat/`。文档与代码不一致时，先认代码。

### 游戏仓侧常驻哨兵：`tests/test_patch_surface.py`

壳化会让「测试改写宿主模块属性来控制行为」这种写法**悄悄失效**（见下一节）。
游戏仓为此常驻一道哨兵（PATCHAUDIT 2026-09-14 落地，PFIX 2026-09-15 加固为
「**按名字**判定取件」）：AST 扫 `tests/**` 里所有对宿主模块属性的改写，逐条判定
「这次改写是否真的能控制行为」：

| 判定 | 含义 | 处理 |
|---|---|---|
| `effective_alias` | 宿主名 == 包内实现模块对象（别名壳） | 放行 |
| `effective_bridge` | 包内实现**按这个名字**经宿主命名空间取件（`_host_attr("core.x","NAME")` / `_src("NAME")`），或宿主壳把该名绑成 `source=lambda: NAME` | 放行 |
| `effective_host_native` | 包内无同名实现（宿主即实现） | 放行 |
| `dead_noop` | 实现已进包、包内**自持**该名 ⇒ 改写只落在宿主命名空间 | **报红**（除非 `WHITELIST` 显式登记并写明理由） |
| `unknown` | 动态属性名，静态判不了 | 报红（人工确认） |

跑法：`python tests/test_patch_surface.py`（exit=0 通过）；有牙自证
`python tests/test_patch_surface.py --self-test`（注入一条**已知失效**改写必须报红 +
一条别名壳改写必须放行 + 一条已知有效桥必须放行）。本哨兵是**常驻门禁**，
已进游戏仓全量 `scripts/run_all_tests.py`（文件名 `test_*.py` 自动收）。

## 内容包壳化：别名壳 / 调用时取件，**禁止自指桥**

把实现从宿主搬进内容包（B1/B2/B13/B18 各线）后，宿主原文件退化成「壳」。
仓内允许**两种**壳；**第三种「自指桥」禁止使用** —— 它是唯一会让测试**静默失效**的桥型：

| 壳形态 | 代码形态 | 「测试改写宿主模块属性」的后果 |
|---|---|---|
| **别名壳**（安全） | `_sys.modules[__name__] = _impl` | 宿主名与包内实现**是同一个模块对象** ⇒ 改写 == 改实现 |
| **调用时取件**（安全，首选） | 包内 `_host_attr("core.x", "NAME")` / `_src("NAME")`；宿主壳 `bind_spec_path(source=lambda: NAME)` | 取件发生在**每次调用**、读宿主命名空间 ⇒ 改写可见 |
| **自指桥**（★禁止） | 包内 `from .本模块 import NAME as fn`（或任何只读**包内自己**的间接层） | 包内实现读自己的全局；宿主那份是 import 期**拷贝** ⇒ 宿主壳改写**永久静默 no-op**：不报错，测试假绿 / 夜间偶红 |

**为什么必须写死这一条**：自指桥**不会报错**。它把「测试钉死时钟 / 数据」的意图悄悄吃掉，
症状是「白天全绿、深夜或换机才红」——最贵的一类缺陷。别名壳与调用时取件都把
「名字解析」放在**运行时**，与真源「函数体查本模块全局」的语义一致；自指桥把解析
固定在**包内**，与宿主壳（测试的打桩面）脱钩。

**本仓实证（PFIX P1，2026-09-15）**：`content/rule_engine.py::_time_check()` 曾写成
`from .rule_engine import _is_time as fn`（自指到包内自己）⇒
`tests/test_v97_05_rule_engine.py:35` 的 `RE._is_time = lambda span: span == "day"`
（改写宿主 `game/core/rule_engine.py` —— 它是 `_is_time = _pkg._is_time` 的**拷贝壳**）
完全不被看见 ⇒ 23:00–05:00 跑该测试**必红**（`rule_explore_ghost` 的 `cond time=deep_night`
真的命中，chance 0.18 在 `seed(1)` 下触发）。已改成调用时取件
`_host_attr("core.rule_engine", "_is_time")`（取不到回落包内 `_is_time`）⇒
**同一深夜窗口 78/0 绿**；把它改回自指桥 ⇒ 测试 **77/1 红** + 哨兵 `dead_noop` 报红
（有牙反证，见 `out/logs/P1_counterproof_*.log`）。

**判据（新增壳 / 改桥时照做）**：

1. 壳化某个名字后，跑 `python tests/test_patch_surface.py` —— 必须放行；
2. 若该名字被测试改写，做一次「删掉取件、退回自指」的反证：测试必须**由绿转红**
   （防「改绿了但没牙」）；
3. 桥只允许两种形态：**别名壳**（模块自替换）或**调用时取件**（每次调用读宿主命名空间）。

## 历史上的 15 条反向依赖边（为什么要建这道门）

来源：游戏仓内部文档 `docs/archive/ENGINE_CONTENT_SPLIT_PLAN.md` §3.2（逐条 R1–R15）。

> **口径更新（2026-09-23）**：这一节是**拆仓前**的历史 —— 那时只有两层（引擎 / 内容）。
> 现在第二层叫**数据包**，中间多了一层**扩展包**；边名换了，方向没变。今天同类毛病叫
> **「回流」**：引擎里重新长出 `battle/` `quest/` … 这些目录，或写一句 `import ext_combat`。
> 它由 `tests/test_layering.py` 的 A 项守着（不是靠自觉）。

| 边 | 位置（快照） | 性质 |
|---|---|---|
| R1 | `actions.py:16` → `game.engine`（21 处公式调用） | 核心反向边 |
| R2 | `actions.py:20` → `game.core.constants` | 死 import |
| R3 | `actions.py:39` → `game.content`（`C.CLASSES` 直读） | 内容表直读 |
| R4 | `actions.py:366` → `game.core.formation` | 合规（通用纯函数，层级归属错） |
| R5 | `actions.py:784` → `game.core.formula_expr` | 合规（通用解释器） |
| R6 | `actions.py:818` → `game.engine.skill_buff_turns` | 反向边 |
| R7 | `actions.py:804` → `game.core.constants` | 死 import |
| R8 | `actions.py:865` → `game.engine.skill_mech_val` | 反向边 |
| R9 | `battle.py:138` → `game.engine`（技能表查询） | 反向边 |
| R10 | `battle.py:139` → `game.content.MONSTER_SKILLS` | 内容表直读 |
| R11 | `stats.py:15` → `game.engine.player_final_stats` | **最重的一条**（玩家面板全算） |
| R12 | `config.py:35` → `game.data.battle_rules` | 位置不合规（装配逻辑落在引擎包内） |
| R13 | `stats.py:96` → 字面量 `"战士"` | 内容名侵入 |
| R14 | `actions.py:26-30` → 中文字面量 kind | 内容语义耦合 |
| R15 | `actions.py:48` → 字面量 `"攻击"` | 内容名侵入（普攻兜底） |

统计：**15 条边**（2 条死 import R2/R7；2 条合规但层级归属错 R4/R5；11 条真反向耦合）。

**现状**：R1–R15 全部已消除（门禁是可执行的证据）。
对应做法：`E.*` 调用改走 `config.formulas()`；`C.CLASSES` / `C.MONSTER_SKILLS` 改走
`skill_lookup` / `monster_skill_fn` hook；kind 字面量与 `"攻击"` 改走 `config.kind_of` /
`basic_fallback`；`"战士"` 默认值拆除；`formula_expr` / `formation` / `skill_kinds` /
`battle_bars` 四个通用件搬进 `saintess_engine/support/`（该容器后改名 `container/`；**模块化重排后**为顶层并列子包 `expr/` · `gauge/` · `formation/` · `kinds/`）。
> **2026-09-13 更新（P4 下沉）**：其中 `kinds/` 后来被实测证明「引擎内部零消费者」，
> 已从引擎**删掉**、词表归内容侧（游戏仓 `game/data/kinds.py`）。现存顶层子包即上列前三者。
> **2026-09-23 更新（包栈重构）**：前三者里 `gauge/`（计量条）与 `formation/`（站位）又被实测
> 证明是**游戏原语**（只有战斗在消费），已随 `battle/` `panel/` 搬进扩展包 `extends/ext_combat/`；
> 引擎侧只留 `expr/`，外加 `formula/` `conditions/` 等纯通用件。判据始终是那一条：**谁来消费**。

## 当前的边界瑕疵（诚实清单）

老的担心是「引擎里藏着游戏词汇」。2026-09-23 之后这个问题**换了主人**：带游戏词汇的模块整体
搬进了扩展包，引擎侧只剩通用件（词表门禁 `tests/test_no_game_vocabulary.py` + 纯度门禁
`tests/test_engine_purity.py` 一起钉）。下表是沿用下来的已核实残留，逐条标注它**现在住哪**：

| # | 瑕疵 | 位置（旧快照） | 影响 | 现在住哪（2026-09-23 起） |
|---|---|---|---|---|
| B1 | ~~`kinds/` 的枚举值写死中文（`PHYS = "物理"` …）~~ **2026-09-13 P4 下沉已消除** | 引擎侧无此模块（词表移居内容侧；引擎只经 `config.kind_of` 注入面读 kind 值） | 原「两套 kind 词表」问题随之下线：引擎侧只此一个注入面，非中文 kind 的游戏不受影响 | ——（已消除） |
| B2 | `landing._apply_death_guard` / `heal_actor` / `stats` 里硬编码 key：`"death_guard"`、`"heal_amp_pct"` / `"heal_down"` / `"_anti_heal_pct"` | `landing.py:273,384-407` | 「濒死保护」「禁疗/受疗增幅」三类机制**只认固定 key 名**。要换名只能改这个包（或复用这些名字）。（原「睡眠打醒」硬编码 `"sleep"` —— **2026-09-11 已数据化**为 `wake_on_hit` 字段，不再属本表） | `extends/ext_combat/battle/landing.py`（`stats.py` 同在 `battle/`） |
| B3 | `effects.act_apply` 里 `if key == "reduce":` 写 `holder["reduce_left"]` | `effects.py:485-486` | 包里出现了内容 key 字面量 | `extends/ext_combat/battle/effects.py` |
| B4 | `schedule._settle_time_effects` 里 `pct_boss` / `boss_pct_mult` / `is_boss` / `role == "boss"` / `is_elite` | `schedule.py:658,275-285` | 「Boss」这个内容概念进了包（作为数据字段处理，尚可接受，但它是**唯一**被包认识的身份标签） | `extends/ext_combat/battle/schedule.py` |
| B5 | `effects.act_apply` 里 `if holder.get("is_boss") or holder.get("role") == "boss"` | `effects.py:383` | 同上（控制时长减半） | `extends/ext_combat/battle/effects.py` |
| B6 | `effects._mech_to_effect` 的 `_is_stack_resource` 判据关键词含 `debuff_scale` / `dot` / `on_threshold` / `guard_hp_pct` | `effects.py:277-281` | 这些字段**没有消费者**（`debuff_scale` 已于 2026-09-11 接线），但它们的**存在与否改变分派结果** —— 声明了 `debuff_scale` 会意外让 mech 走叠层路径 | `extends/ext_combat/battle/effects.py` |
| B7 | `battle.py` 里 `"player"` 阵营名硬编码 | `battle.py:669`（`_check_side_end`）、`:170`（`focus`） | 你的游戏若不叫 `player` 就得改这个包或用 `hostile_map` 绕过 | `extends/ext_combat/battle/battle.py` |
| B8 | `B6` 的反面：`stats._monster_base_stats` 的 `crit` 兜底 0.05 与 `make_actor` 播种 0.0 不一致 | `stats.py:145` vs `actors.py:100` | 同一种 actor 在不同路径下暴击率不同 | `extends/ext_combat/battle/stats.py` vs `battle/actors.py` |

**结论（三层后，边界瑕疵分成两类）**：

| 类 | 现状 |
|---|---|
| **引擎** | import 边界干净（机器可验）；**语义边界也干净了** —— 游戏词汇与游戏原语都已搬走，剩下的通用件不认识任何具体游戏。今后要守的是**回流**（门禁 A） |
| **扩展包** | B2–B8 随模块搬进 `extends/ext_combat/battle/`：**装了战斗包的第三方照样会撞上这些硬编码**（固定 key 名 / Boss 身份标签 / 阵营名 `player` / 暴击兜底不一致）。它们不再是「引擎不通用」的问题，而是「这个包的形状够不够通用」的问题 |

处置顺序也随之变了：先按 `tests/test_layering.py` 防回流（引擎侧永远不许再长回游戏原语），
再谈把 `ext_combat` 里那几处 key 字面量数据化 —— 那是**扩展包自己的**技术债，与引擎通用性无关。

## 物理拆仓的历程（拆仓前为什么不能直接拆 —— 现已完成）

游戏仓内部文档 `docs/archive/ENGINE_CONTENT_SPLIT_PLAN.md` §9 **在拆仓前**给出的结论（逐字要点，保留为历史判据）：

> **现在不能直接拆。** 引擎自身纯度已经很高（13 个模块里 9 个零出边、0 处 `cls_*`、
> 0 处 `PLAYER_SKILLS`/`INSTANCES`），但 4 个文件持有 15 条指向内容层的 import 边，
> 且内容层绕过包门面直接依赖引擎内部模块与 5 个下划线私有符号。
>
> **前置 = S1 + S2 + S3**（三步都不移动文件、都能单独 revert、每步都有「241 绿 +
> 零反向边」的机器可验证断言）。三步之后才是 S4 起的物理搬迁。
>
> **一句话**：先做「断反向边 + 固 API + 通用件归位」，再谈 submodule 物理分离；
> 直接 `git mv` 会带着 15 条反向 import 边一起进 submodule，等于把耦合换个地方放。

**以上是拆仓前的判断，已被执行完毕**：S1–S3 落地后即做了物理拆分 —— 引擎包 `saintess_engine/`
已成为独立仓 `framework-engine`，游戏仓（奥兰迪亚）以 `git submodule framework/`
引用本仓的固定 commit。

**进度表**（上半段拆仓前按游戏仓 `git log` 核实、「状态」列已更新为拆仓后的现实；
下半段是 2026-09-23 的**包栈重构**，见 `REFACTOR_包栈重构计划.md`）：

| 步 | 内容 | 状态 |
|---|---|---|
| S1 | 断 15 条反向依赖边（`d5e323e`） | ✅ 已完成（门禁可验） |
| S2 | 固化公开 API 面 | ✅ 已完成 |
| S3 | 通用件归位（`→ saintess_engine/support/`，后改名 `container/` 并重排为顶层子包） | ✅ 已完成 |
| S4 | 引擎包改名 `saintess_engine → engine` | ❌ **已废止**（随拆仓定案：包名**保持 `saintess_engine`**，不再改中性名） |
| S5' | 拆 `game/engine.py` → `extends/ext_combat/battle/formulas.py` + `content_rules/*`（`5eae164`） | ✅ 已完成（旧 `game/engine.py` shim 已随 S9-2 删除） |
| S6' | 内容层重组快照 | ✅ 已完成 |
| S7 | 单一装配入口 `apply_game_content`（`50eb8dc`） | ✅ 已完成（见下） |
| S8 | 拆仓库 / submodule | ✅ **已完成**（引擎独立为 `framework-engine`；游戏仓 `git submodule framework/` 引用本仓固定 commit） |
| S9 | 收口清理过渡 shim | ✅ **已完成**（S9-2 已删 `game/engine.py` 与 `game/core/*` 过渡件） |
| 第 0 批 | 包栈加载器 `package.py` 重写：`kind` / `depends` / 拓扑加载 / 环检测 / 命名空间隔离 / 域分层 | ✅ 已完成（2026-09-23） |
| 第 1 批 | 抽 `ext_quest`（打通「搬出去」的流程） | ✅ 已完成 |
| 第 2 批 | 抽 `ext_combat`（`battle` `gauge` `formation` `panel`）+ 引擎新增 `provides` 能力提供者 + 解耦 `host → Battle` | ✅ 已完成 |
| 第 3 批 | 13 个形状 → 6 个扩展包（`ext_world` `ext_life` `ext_economy` `ext_social` `ext_loot` `ext_dialogue`），六路并行搬迁 | ✅ 已完成 |
| 第 4 批 | 域归属重排：`maps` / `instances` / `drop_pools` 跟消费端走 | ✅ 已完成（`<包>/domains.json`） |
| 第 5 批 | 门禁与文档收口：`tests/test_layering.py`（三层依赖守卫）+ engine-wiki 口径 | 🔄 本轮 |
| 第 6 批 | 奥兰迪亚全量迁移验证（各批已顺带迁完，剩验证） | 🔄 游戏仓侧 `scripts/run_all_tests.py` |

所以**引擎的物理形态已经是独立仓 `framework-engine` 里的 `saintess_engine/` 包**（可整包拷走、
零外部依赖），游戏仓（奥兰迪亚）以 `git submodule framework/` 引用它。
「反向边 + 公开 API + 通用件 + 单一装配入口」四件事在拆仓前已完成，
本 wiki 描述的 API 面就是当前状态。

### S7 的产物：内容侧单一装配入口

`game/content_rules/apply.py`（156 行，S7 新增）：

```python
def ensure_engine_configured() -> None:                    # game/content_rules/apply.py:88
    """引擎配置一次性装配（旧 load_game_defaults 的收敛点，幂等）"""

def apply_game_content(actor: dict, ctx: dict | None = None) -> dict:   # game/content_rules/apply.py:100
    """开战/进场内容装配的唯一收敛点（幂等）"""
```

内容侧的**调用顺序契约**写死在 `apply_game_content` 里（原文注释：
「铁律，写死在 `apply_game_content` 里——命令层不得再自行排列」）。逐字顺序
（`game/content_rules/apply.py:24-41` 的 docstring）：

| # | 调用 | 说明 |
|---|---|---|
| ① | `ensure_engine_configured()` | 引擎 hook + 规则表装配（=`game.bootstrap.load_engine_config`），先于一切内容装配 |
| ② | `equip_proc.apply_to_actor(actor)` | 装备/词条/武器特效 → `triggers` + `bonus` 分域。⚠️ **必须先于 ③**（EP 的 `bonus` 是 ③ 渠道装配的输入） |
| ③ | `class_mech_proc.apply_class_mech(actor)` | 职业 mech 兑现（`start_full` / `channels` / 被动族 / 磐核减伤 / 旋律）；**其内部**顺序 = bar_gain 注入 → mech 段 → `apply_bar_procs` → `apply_cond_procs` |
| ④ | `bar_procs.apply_bar_procs(actor)` | 挂敌身条（`BAR_INJECT_FIELDS` → `skill_hit` 注入）；③ 已挂时为空操作，显式保留以便单独演进 / 单测直调 |
| ⑤ | `cond_procs.apply_cond_procs(actor)` | 技能条件乘区（`info.cond` → `dmg_calc`/`heal_calc`） |
| ⑥ | `food_proc.install_food_fx(actor, aids, logs)` | 食物效果（仅当 `ctx` 传 `aids` 时执行） |

**对第三方的意义**：这是「开战前要调哪些装配器、什么顺序」的**权威答案**。
你自己做时，照这个结构写一个 `apply_my_content(actor)`，把顺序写成契约并加幂等测试。

⚠️ **S7 的已知副作用（值得学）**：`apply_game_content` 的幂等靠 actor 顶部标记键
`_content_applied`（`game/content_rules/apply.py:81`）实现，而**该键会随 actor 全量落进战斗存档 / PVP 状态**
（`serialize._STRIP_KEYS` 只剥 `_skill_index`）。原文自己记了这件事：
「无任何数值/读取语义依赖它，S9 若要清掉需改引擎 `serialize.py`（引擎改动，本步不做）」
（`game/content_rules/apply.py:55-58`）。**教训**：往 actor 上加内部标记 = 进存档。

## 内容侧（游戏仓 / 奥兰迪亚侧）还有哪些 **不属于** 引擎文档的东西

以下模块**不住在框架仓的 `saintess_engine/`**（住在游戏仓 `dragonfall/game/...`，2026-09-23 起
以**数据包** `games/orlandia` 的形式导出到框架仓），**不改引擎**，
但会让引擎里的声明真正生效 —— 它们进不了本 wiki 的参考页，因为它们不是**引擎**能力
（它们是**数据包**层的活）：

| 内容侧模块 | 职责 |
|---|---|
| `game/data/battle_rules.py` | 四张声明表（本 wiki 用它的真实条目做样例） |
| `game/content_rules/apply.py` | **S7 单一装配入口**：`ensure_engine_configured()` + `apply_game_content(actor)`（顺序契约的权威） |
| `game/services/class_mech_proc.py` | 职业机制/被动/资源/旋律装配 + 38 个 `class_*` / `passive_*` / `mech_cash_*` 动作 |
| `game/services/battle_equip_proc.py` | 装备特效/词条 → `triggers` 装配（含事件映射表） |
| `game/services/battle_we_procs.py` | 27 个 `we_*` 武器特效族动作 |
| `game/services/battle_bar_procs.py` | 挂敌身条装配（`BAR_INJECT_FIELDS` → `skill_hit` 触发器） |
| `game/services/battle_cond_procs.py` | 技能条件倍率（`cond` → `dmg_calc`/`heal_calc` 乘区） |
| `game/services/battle_bridge.py` | 命令层数据 → actor 翻译（`player_to_actor` / `monster_to_actor` / `build_sides`） |
| `game/bootstrap.py` | 内容侧装配入口（`mount_engine_hooks` / `load_engine_config`） |
| `game/content_rules/{skills,panel,gameplay}.py` | 技能表 / 面板公式 / 游戏规则（S5 从 `engine.py` 拆出） |

⚠️ **一个已核实的重要内容侧缺口**：技能数据的 `cond`（条件倍率）在引擎里是死字段 ——
`actions._do_heal` 里 `cond_mult = 1.0  # N2b 补，恒 1.0 起步`（`actions.py:732`）。
内容侧用 `battle_cond_procs.py` 把它接回乘区（「**引擎零改动**，走既有装配层扩展动作模式」，
游戏仓 `battle_cond_procs.py:5-11`）。第三方要 `cond` 就得自己写这个装配器。

## 相关

- 注入面细节 → [../concepts/config-injection.md](../concepts/config-injection.md)
- 每个 ADR 的代价 → [design-decisions.md](design-decisions.md)
- 分发清单 → [../contributing/release.md](../contributing/release.md)
- 包格式权威规格（`game.json` 全字段 / 依赖 / 命名空间 / 域分层）→ [../reference/package-format.md](../reference/package-format.md)
- 三层依赖守卫的运行方式 → `tests/test_layering.py`（A 引擎零原语 · B 扩展包只认 `depends` · C 数据包不漏声明 · D 无孤儿包）
- 未取证项总表 → [../_selfcheck.md](../_selfcheck.md)
- 壳化打桩面哨兵（游戏仓，常驻门禁）→ `tests/test_patch_surface.py`（`--self-test` 有牙自证）
