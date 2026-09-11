# 引擎与内容的物理边界

本页是**框架仓与游戏仓的边界现状快照**。引擎已物理分离为独立仓 `framework-engine`
（引擎包 `saintess_engine/`），游戏仓（奥兰迪亚）以 `git submodule framework/` 引用它；
方案与迁移细节引用游戏仓内部文档 `docs/ENGINE_CONTENT_SPLIT_PLAN.md`
（该文档不进本 wiki 的门面）。

## 边界在哪：一张图

```
┌──────────────────────── 你的仓库 ────────────────────────┐
│                                                          │
│  ┌────────────────────────────┐                          │
│  │  内容侧（游戏知识）          │                          │
│  │                            │                          │
│  │  · 数据表：技能 / 怪 / 道具 / 词条 / 规则表            │
│  │    EFFECT_ACTIONS · EFFECT_RULES · MECH_CASH ·        │
│  │    PASSIVE_PROC · BAR_INJECT_FIELDS …                 │
│  │  · 装配器：把数据表翻译成 actor["triggers"]            │
│  │    + 注册扩展动词 register_action                     │
│  │  · 公式实现 + 面板公式 + 技能查询函数                  │
│  │  · 命令层：输入 / 展示 / 持久化 / 上层事件（phase 等）  │
│  └───────────────┬────────────────────────┘              │
│                  │ mount / set_config（内容 → 引擎）      │
│                  │ 构造 actor + Battle(sides=...)         │
│                  ↓                                       │
│  ┌────────────────────────────────────────┐              │
│  │  引擎  saintess_engine/（零游戏知识）            │              │
│  │                                        │              │
│  │  actors · battle · actions · effects · │              │
│  │  effect_triggers · landing · schedule ·│              │
│  │  serialize · stats · state_effects ·   │              │
│  │  formulas · ai · config · support/     │              │
│  │                                        │              │
│  │  ✗ 不 import 内容                       │              │
│  │  ✓ 只读 config 的表 + actor 的字段       │              │
│  └────────────────────────────────────────┘              │
└──────────────────────────────────────────────────────────┘
```

**判断某个东西该放哪边**（`game/content_rules/__init__.py:10` 的判据）：

> **凡读游戏表或职业名 → 内容侧。** 引擎不得 import 内容包；
> 需要数值时经 `saintess_engine.config` 注入 hook 取。

三条自查问句：

1. 这段代码里出现了**职业 id / 表名 / 中文名词**吗？→ 内容侧
2. 这段代码在**别的游戏**里也成立吗？→ 可能引擎侧
3. 换个游戏要改这行吗？→ 内容侧

## 机器验证：门禁测试

`tests/test_engine_purity.py`（框架仓纯度门禁，AST 静态分析，不做运行时 import）断言：

| # | 断言 | 位置（`tests/test_engine_purity.py`） |
|---|---|---|
| 1 | `saintess_engine/**/*.py` 的**每一条绝对 import 都是标准库**（相对导入不限）—— 比旧的「零指向 `game.*` 的边」更强的**可分发性**闸门 | `STDLIB` 判据（`:28`/`:96-102`），断言 `:116` |
| 2 | 零动态 import 穿透（`importlib.import_module` / `__import__` 指向外部包） | `:103-106`，断言 `:118` |
| 3 | `actions.py` 不再持有 kind 中文字面量常量（`K_PHYS`/`K_MAGI`/`K_TRUE`/`K_HEAL`/`K_BUFF`） | `:121-128` |
| 4 | 注入面存在（7 个 hook 名在 `config.py` 里） | `:130-134` |
| 5 | 包门面 re-export 26 个符号，且 5 个私有符号的旧别名是同一对象 | `:136-152` |
| 6 | （游戏仓侧）内容层零 `saintess_engine.*._私有符号` 引用 —— 框架仓无内容层，此项不在框架门禁内 | 属游戏仓约束 |

跑法：框架仓 `python tests/run_all.py`（引擎全量 `tests/` + 示例游戏冒烟，exit=0 全绿）；
也可单跑 `python tests/test_engine_purity.py`。门禁另含「存档兼容：`Battle.from_state` /
`to_state` 在 API 面内」一条断言（`test_engine_purity.py:153-155`）。
（游戏仓侧的全量回归是另一回事：`python scripts/run_all_tests.py`，住在游戏仓。）

## 历史上的 15 条反向依赖边（为什么要建这道门）

来源：游戏仓内部文档 `docs/ENGINE_CONTENT_SPLIT_PLAN.md` §3.2（逐条 R1–R15）。

| 边 | 位置（快照） | 性质 |
|---|---|---|
| R1 | `actions.py:16` → `game.engine`（21 处公式调用） | 核心反向边 |
| R2 | `actions.py:17` → `game.core.constants` | 死 import |
| R3 | `actions.py:35` → `game.content`（`C.CLASSES` 直读） | 内容表直读 |
| R4 | `actions.py:337` → `game.core.formation` | 合规（通用纯函数，层级归属错） |
| R5 | `actions.py:720` → `game.core.formula_expr` | 合规（通用解释器） |
| R6 | `actions.py:767` → `game.engine.skill_buff_turns` | 反向边 |
| R7 | `actions.py:766` → `game.core.constants` | 死 import |
| R8 | `actions.py:799` → `game.engine.skill_mech_val` | 反向边 |
| R9 | `battle.py:120` → `game.engine`（技能表查询） | 反向边 |
| R10 | `battle.py:121` → `game.content.MONSTER_SKILLS` | 内容表直读 |
| R11 | `stats.py:16` → `game.engine.player_final_stats` | **最重的一条**（玩家面板全算） |
| R12 | `config.py:38` → `game.data.battle2_rules` | 位置不合规（装配逻辑落在引擎包内） |
| R13 | `stats.py:97` → 字面量 `"战士"` | 内容名侵入 |
| R14 | `actions.py:22-26` → 中文字面量 kind | 内容语义耦合 |
| R15 | `actions.py:42` → 字面量 `"攻击"` | 内容名侵入（普攻兜底） |

统计：**15 条边**（2 条死 import R2/R7；2 条合规但层级归属错 R4/R5；11 条真反向耦合）。

**现状**：R1–R15 全部已消除（门禁是可执行的证据）。
对应做法：`E.*` 调用改走 `config.formulas()`；`C.CLASSES` / `C.MONSTER_SKILLS` 改走
`skill_lookup` / `monster_skill_fn` hook；kind 字面量与 `"攻击"` 改走 `config.kind_of` /
`basic_fallback`；`"战士"` 默认值拆除；`formula_expr` / `formation` / `skill_kinds` /
`battle_bars` 四个通用件搬进 `saintess_engine/support/`（**模块化重排后**为顶层并列子包 `expr/` · `gauge/` · `formation/` · `kinds/`）。

## 当前的边界瑕疵（诚实清单）

门禁只验证「import 方向」，不能保证「引擎里零游戏知识」。以下都是已核实的残留：

| # | 瑕疵 | 位置 | 影响 |
|---|---|---|---|
| B1 | `support/skill_kinds.py` 的枚举值写死中文（`PHYS = "物理"` …） | `skill_kinds.py:27-34` | 与 `config.kind_of` 注入面**两套 kind 词表**；非中文 kind 的游戏用不了 `is_kind` / `is_damage_kind` / `seg_of` |
| B2 | `landing._apply_death_guard` / `heal_actor` / `stats` 里硬编码 key：`"death_guard"`、`"heal_amp_pct"` / `"heal_down"` / `"_anti_heal_pct"`、`"sleep"` | `landing.py:117,237,373-396` | 「濒死保护」「禁疗/受疗增幅」「睡眠打醒」四类机制**只认固定 key 名**。要换名只能改引擎（或复用这些名字） |
| B3 | `effects.act_apply` 里 `if key == "reduce":` 写 `holder["reduce_left"]` | `effects.py:369-370` | 引擎里出现了内容 key 字面量 |
| B4 | `schedule._settle_time_effects` 里 `pct_boss` / `is_boss` / `role == "boss"` | `schedule.py:268,272` | 「Boss」这个内容概念进了引擎（作为数据字段处理，尚可接受，但它是**唯一**被引擎认识的身份标签） |
| B5 | `effects.act_apply` 里 `if holder.get("is_boss") or holder.get("role") == "boss"` | `effects.py:305` | 同上（控制时长减半） |
| B6 | `effects._mech_to_effect` 的 `_is_stack_resource` 判据关键词含 `debuff_scale` / `dot` / `on_threshold` / `guard_hp_pct` | `effects.py:249-253` | 这些字段**没有消费者**，但它们的**存在与否改变分派结果** —— 声明了 `debuff_scale` 会意外让 mech 走叠层路径 |
| B7 | `battle.py` 里 `"player"` 阵营名硬编码 | `battle.py:555`（`_check_side_end`）、`:170`（`focus`） | 你的游戏若不叫 `player` 就得改引擎或用 `hostile_map` 绕过 |
| B8 | `B6` 的反面：`stats._monster_base_stats` 的 `crit` 兜底 0.05 与 `make_actor` 播种 0.0 不一致 | `stats.py:122` vs `actors.py:98` | 同一种 actor 在不同路径下暴击率不同 |

**结论**：引擎的 import 边界是干净的（机器可验），但**语义边界还没完全干净**：
B1/B2/B6/B7 属于拆仓时一并带进框架仓的残留，需要在「彻底零游戏知识」之前处理，
否则第三方拿去会遇到「引擎认识我不认识的词」的问题。

## 物理拆仓的历程（拆仓前为什么不能直接拆 —— 现已完成）

游戏仓内部文档 `docs/ENGINE_CONTENT_SPLIT_PLAN.md` §9 **在拆仓前**给出的结论（逐字要点，保留为历史判据）：

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

**进度表**（拆仓前按游戏仓 `git log` 核实；「状态」列已更新为拆仓后的现实）：

| 步 | 内容 | 状态 |
|---|---|---|
| S1 | 断 15 条反向依赖边（`d5e323e`） | ✅ 已完成（门禁可验） |
| S2 | 固化公开 API 面 | ✅ 已完成 |
| S3 | 通用件归位（`→ saintess_engine/support/`，后重排为顶层子包） | ✅ 已完成 |
| S4 | 引擎包改名 `saintess_engine → engine` | ❌ **已废止**（随拆仓定案：包名**保持 `saintess_engine`**，不再改中性名） |
| S5' | 拆 `game/engine.py` → `saintess_engine/battle/formulas.py` + `content_rules/*`（`5eae164`） | ✅ 已完成（旧 `game/engine.py` shim 已随 S9-2 删除） |
| S6' | 内容层重组快照 | ✅ 已完成 |
| S7 | 单一装配入口 `apply_game_content`（`50eb8dc`） | ✅ 已完成（见下） |
| S8 | 拆仓库 / submodule | ✅ **已完成**（引擎独立为 `framework-engine`；游戏仓 `git submodule framework/` 引用本仓固定 commit） |
| S9 | 收口清理过渡 shim | ✅ **已完成**（S9-2 已删 `game/engine.py` 与 `game/core/*` 过渡件） |

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

以下模块**不住在框架仓**（住在游戏仓 `dragonfall/game/...`），**不改引擎**，
但会让引擎里的声明真正生效 —— 它们进不了本 wiki 的参考页，因为它们不是引擎能力：

| 内容侧模块 | 职责 |
|---|---|
| `game/data/battle2_rules.py` | 四张声明表（本 wiki 用它的真实条目做样例） |
| `game/content_rules/apply.py` | **S7 单一装配入口**：`ensure_engine_configured()` + `apply_game_content(actor)`（顺序契约的权威） |
| `game/services/class_mech_proc.py` | 职业机制/被动/资源/旋律装配 + 38 个 `class_*` / `passive_*` / `mech_cash_*` 动作 |
| `game/services/battle2_equip_proc.py` | 装备特效/词条 → `triggers` 装配（含事件映射表） |
| `game/services/battle2_we_procs.py` | 27 个 `we_*` 武器特效族动作 |
| `game/services/battle2_bar_procs.py` | 挂敌身条装配（`BAR_INJECT_FIELDS` → `skill_hit` 触发器） |
| `game/services/battle2_cond_procs.py` | 技能条件倍率（`cond` → `dmg_calc`/`heal_calc` 乘区） |
| `game/services/battle2_bridge.py` | 命令层数据 → actor 翻译（`player_to_actor` / `monster_to_actor` / `build_sides`） |
| `game/bootstrap.py` | 内容侧装配入口（`mount_engine_hooks` / `load_engine_config`） |
| `game/content_rules/{skills,panel,gameplay}.py` | 技能表 / 面板公式 / 游戏规则（S5 从 `engine.py` 拆出） |

⚠️ **一个已核实的重要内容侧缺口**：技能数据的 `cond`（条件倍率）在引擎里是死字段 ——
`actions._do_heal` 里 `cond_mult = 1.0  # N2b 补，恒 1.0 起步`（`actions.py:679`）。
内容侧用 `battle2_cond_procs.py` 把它接回乘区（「**引擎零改动**，走既有装配层扩展动作模式」，
`battle2_cond_procs.py:5-11`）。第三方要 `cond` 就得自己写这个装配器。

## 相关

- 注入面细节 → [../concepts/config-injection.md](../concepts/config-injection.md)
- 每个 ADR 的代价 → [design-decisions.md](design-decisions.md)
- 分发清单 → [../contributing/release.md](../contributing/release.md)
- 未取证项总表 → [../_selfcheck.md](../_selfcheck.md)
