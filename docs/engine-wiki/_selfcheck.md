# 自检：未能取证 / 待确认清单

> 本页是**诚实清单**。所有条目都在写文档时逐项 grep / 运行核实过；
> 「结论」列是核实结果，「类型」列区分：
>
> - **`缺消费方`** = 代码/声明存在但没有读取它的地方（不是笔误，是真实历史遗留）
> - **`待确认`** = 我无法从代码或文档确定，需要人回答
> - **`注释≠代码`** = 注释/文档的陈述与代码当前行为不一致
> - **`未取证`** = 我没有做足够的验证就写进 wiki（一律标出）

## 1. 声明了但无消费方（`缺消费方`）

### 1.1 `EFFECT_RULES` 字段

| 字段 | 核实方法 | 结论 |
|---|---|---|
| `debuff_scale` | 全仓 `grep -rn "debuff_scale"` → 只命中 `effects.py:249` 的**判据关键词列表**与数据表注释 | **无任何折算消费方**。声明了「每层承伤 +N%」的 `hunt_mark` / `soul_mark` / `curse` 实际不生效 |
| `on_threshold` | 全仓 grep → 只有 `effects.py:211/244/250` 的判据关键词 + `battle2_rules.py:27` 的声明 | **无消费方**。`threshold` **事件**有引擎点位（`effects.py:349`），但这张映射表没被读 |
| `wake_on_hit` | 全仓 grep → 只有 `battle2_rules.py:400` 的声明 | **无消费方**。打醒睡眠由 `landing.py:117` 的硬编码 key 判断实现 |
| `tag` | grep `state_def(...).get("tag")` / `cfg.get("tag")` → 空 | **无消费方**。`act_apply` 读的是 params 的 `tag`（作 key 兜底，`effects.py:287`） |
| `dot` | 全仓 grep → 只有 `effects.py:249` 判据；78 个 key 里无一使用 | **无消费方**（V5 后 DOT 统一走 `period`） |
| `name` | 引擎无读取（内容侧读） | 引擎不读，**符合设计**（展示名属内容侧） |
| `negative` | 引擎无读取（内容侧 `class_mech_proc.py:767` 读） | 引擎不读，**但它是内容侧约定的关键字段** |
| `start_full` / `start_classes` / `channels` / `load_tiers` / `overload_heal_pct` | 引擎无读取，内容侧装配器读 | 引擎不读，**但缺 `start_classes` 会导致内容侧钩子不装配**（隐性） |

### 1.2 `period` 子字段

| 子字段 | 结论 |
|---|---|
| `type` | **无消费方**（参考实现 `bleed` 写了 `"type": "flat"`） |
| `per_layer` | **无消费方**（同上 `"per_layer": 0`） |
| `dmg_type` | **无消费方**（参考实现 `corros` 写了 `"dmg_type": "true"` 并注释「真伤 DOT」）。DOT 落地统一 `deal_damage(battle, None, a, dmg, logs)` **不传 `dmg_kind`**（`schedule.py:292`）→ 吃不到类型免伤/格挡是因为 kind 为空，**不是因为声明了真伤** |

### 1.3 引擎 API / 常量

| 名称 | 位置 | 结论 |
|---|---|---|
| `Battle.dmg_mult` | `battle.py:60` | 只赋值，**零消费者** |
| `Battle.pet` | `battle.py:61` | 只赋值，**零消费者**（docstring 也没解释它） |
| `Battle.__init__(st=...)` | `battle.py:37` | **签名里有、函数体从未引用**；全仓 0 处调用点传它 |
| `Battle._cast_ctx` / `_target_ctx` | `battle.py:73-74` | 只初始化，零使用 |
| `Battle._events` | `battle.py:82` | 只初始化，零使用 |
| `DEFAULT_CT_WAIT = 2.0` | `battle.py:22` | 常量零消费 |
| `schedule.CAST_ITEM = 1.0` | `schedule.py:25` | 引擎内零消费（内容侧 `battle2_item_use.py` 自己定义了同值常量） |
| `schedule.HOT_INTERVAL = 1.0` | `schedule.py:29` | 零消费 |
| `schedule.next_ct` | `schedule.py:46` | 有定义、无调用方（实际推进走 `_after_act`） |
| `state_effects.stat_scale_of` | `state_effects.py:18` | 仅测试引用 |
| `actions._aoe_falloff_apply` | `actions.py:524` | **占位实现**（原样返回 logs）。`info["aoe_falloff"]` 在 `actions.py:361` 被读取但随后被丢弃 → AOE falloff 实际未生效 |
| `formation.reachable_units` | `formation/__init__.py:28` | 零外部引用 |
| `expr.expr_or` | `expr/__init__.py:208` | 零外部引用 |
| `gauge.charge_*`（6 个） | `gauge/__init__.py:244-321` | **全部零外部引用** —— 蓄力三律无消费者 |
| `support.battle_bars.bar_should_trigger` / `bar_preserve` | `:164` / `:204` | 仅内部/单点引用（`bar_preserve` 被命令层 Boss 脚本用 1 处） |
| `effects.effects_from_skill(..., caster_side_is_player=True)` | `effects.py:188` | **第三个参数在函数体里从未使用** |
| `config.set_hook` | `config.py:123` | 零外部引用（都走 `mount`） |
| `serialize.to_state` 的 `flags` | `serialize.py:49` | 恒写入 `{}`；**没有读取方**，也没有写入方 |
| `Battle.auto_run(max_steps=500)` | `battle.py:302` | 全仓调用点**只在 `tests/`**（游戏仓 `test_battle2_add_actor.py:159`、游戏仓 `test_battle2_bridge.py:154`、游戏仓 `test_battle2_bar_procs.py:240` 等），内容侧零调用 —— 实质是**测试/AI 模式辅助**，不是生产路径（生产走 `human_act` + `advance`） |

### 1.4 `EFFECT_ACTIONS` / 技能数据侧的静默 no-op

| 项 | 结论 |
|---|---|
| `game/data/skills.py` 里 **20 个** `effect=` 名词既不在 `EFFECT_ACTIONS` 也不是引擎动词 | **静默 no-op**。完整清单 + 行号见 [reference/effect-actions.md](reference/effect-actions.md) 的缺口节 |
| `game/data/monster_mods.py` / `game/data/instances.py` 另有 4 个（`freeze_self` / `mortal_wound` / `stacks_clear` / `vulnerable`） | 同上 |
| `def_up` | **在 `EFFECT_RULES` 有 `panel` 声明，但不在 `EFFECT_ACTIONS`** → 声明白写（`skills.py:4195` 使用它） |
| `EFFECT_ACTIONS` 里的旧动词名（`control`/`buff`/`state_add`/`state_spend`/`state_set`） | V4 已合并进 `apply`/`consume`；表里若出现 = 静默 no-op（本次核实：51 个名词里**没有**出现旧的，已清干净） |

### 1.5 内容侧在 actor 上留下的「会被存档的标记」

| 项 | 结论 |
|---|---|
| `actor["_content_applied"]`（bool） | S7 的 `apply_game_content` 幂等标记（游戏仓 `game/content_rules/apply.py:81`）。**会随 actor 全量落进战斗存档 / PVP 状态**（引擎 `serialize._STRIP_KEYS` 只剥 `_skill_index`）。原文自记「无任何数值/读取语义依赖它，S9 若要清掉需改引擎 `serialize.py`」（游戏仓 `apply.py:55-58`） |
| `actor["dot_next"]` / `actor["dot_jumps"]`（dict） | 引擎周期结算的运行期辅助（`schedule.py:228-229` 惰性建），**同样落盘**。这是「续战能对上」的原因，但字段名与内容无关 |
| `actor["_dmg_taken_mult"]`（float） | 承伤乘区（`landing.py:86-91` 读）。由上层直写（例 游戏仓 `commands/boss_script.py:684`）；**同样落盘** |
| `actor["reduce_left"]` / `reduce_all_left` | `effects.act_apply` 写（`effects.py:370`）+ 内容侧 bridge 透传/播种；**无消费者**（见 §1.3） |
| `actor["act_count"]` | `actor_auto` 每动 +1（`battle.py:391`），AI 的 `round_mod` 谓词读它；落盘 |

## 2. 事件点位

| 事件 | 结论 |
|---|---|
| `phase` / `player_low` / `pv_broken` | **在 `EVENTS` 里但引擎零 fire 点位**（设计如此，由上层驱动 —— `effect_triggers.py:38-40`） |
| `skill_hit` / `attack_hit` | **有点位但静态 grep 不到**：`actions.py:456` 用变量选事件名（`ev = "attack_hit" if info.get("_basic") else "skill_hit"`）。文档若按 grep 结果断言「无点位」会是错的 |
| `EVENTS` 实际条目数 | **26**（不是 docstring 说的「19 时机」）。引擎插桩自然点位 **23** 个（不是注释说的「16 个」） |

## 3. `注释 ≠ 代码`（发现了 6 处）

| # | 位置 | 注释说 | 实际 |
|---|---|---|---|
| C1 | `effect_triggers.py:24` | 「19 时机 + …」（# 事件全集） | `EVENTS` 实际 26 项 |
| C2 | `effect_triggers.py:40` | 「引擎已插桩自然点位 = 除 phase/player_low/pv_broken 外 **16 个**」 | 实际 23 个 |
| C3 | 游戏仓 `battle2_rules.py:696` | 「基础 8% 走 `debuff_scale` **引擎天然段**」 | `debuff_scale` **无消费方**（§1.1） |
| C4 | 游戏仓 `battle2_rules.py:292` | `corros` 注释「**真伤** DOT」 | `period.dmg_type` 无消费方；实际不是真伤（§1.2） |
| C5 | 游戏仓 `battle2_rules.py:531` | `finisher.crit_at: 4`「声明先行——crit roll 前钩子就绪后生效」 | **声明先行 = 当前不生效**；装配器不读 `crit_at`，也没有消费它的钩子（已核实的缺口） |
| C6 | `battle2_rules.py:510` | `MECH_CASH` docstring 列 `bonus_clear` 模式 | 装配器 mode 分派里没有它（`class_mech_proc.py:2350` 只认 4 个 mode），注释也自承「R1b 未用」 |

另：`MECH_CASH` 声明了 `heal_clear`（`faith_unload`），装配器**不处理**该 mode
（`class_mech_proc.py:2350` 的 `if mode not in (...)` 直接 continue）——
兑现实际走技能数据的 `res_cost`，声明条目里的 `note` 字段自己写明了这件事。

## 4. 边界瑕疵（引擎里的内容知识）—— 门禁拦不住的部分

门禁 `tests/test_engine_purity.py` 只验证 **import 方向**。
以下都是已核实的**语义残留**：

| # | 瑕疵 | 位置 |
|---|---|---|
| B1 | `kinds/` 枚举值写死中文（`PHYS = "物理"` …） | `kinds/__init__.py:27-34` |
| B2 | 固定效果 key：`"sleep"`（打醒）、`"death_guard"`（濒死保护）、`"heal_amp_pct"` / `"heal_down"` / `"_anti_heal_pct"`（受疗修正） | `landing.py:117, 237, 373-396` |
| B3 | `effects.act_apply` 里 `if key == "reduce":` | `effects.py:369` |
| B4 | `is_boss` / `role == "boss"`（控制减半 / DOT `pct_boss`） | `effects.py:305` · `schedule.py:268,272` |
| B5 | `battle.py` 里 `"player"` 阵营名 | `battle.py:170, 515` |
| B6 | `_is_stack_resource` 的判据关键词含无消费方的字段（`debuff_scale` / `dot` / `on_threshold` / `guard_hp_pct`） | `effects.py:249-253` |

B6 值得单列说明：这些字段**没有消费者**，但它们**存在与否会改变 `mech` 的分派结果**
（有 `debuff_scale` → 走 `apply op=add` 叠层；没有 → 走 `EFFECT_ACTIONS` 名词翻译）。
所以它们是「死字段但活判据」—— 清理时必须同时考虑分派影响。

## 5. `未取证 / 待确认`（需要人回答）

### 5.0 快照与漂移警示

- **写入快照**：`git rev-parse HEAD` = `50eb8dc`
  （`feat(engine): 单一装配入口 apply_game_content（S7）+ S6' 内容层重组快照`）
- 写文档时 `git status` 显示工作树**除本 `docs/engine-wiki/` 外无改动**，
  即本文所有行号对应的是那次 HEAD 的**已提交状态**
- ⚠️ **行号会漂移**：`docs/ENGINE_CONTENT_SPLIT_PLAN.md` 自己记录过，
  侦察期检测到并行 agent 正在改 `game/data/battle2_rules.py` 与
  `game/services/class_mech_proc.py`，行号已漂移（`apply_class_mech` L2041→L2201）。
  本次写文档期间，`git log` 又前进了 4 个 commit（S5'/S6'/S7 落地）。
  **引擎侧（`saintess_engine/*`）的锚点在这些 commit 里未变**，但内容侧一定在动。
  → **引用时以符号名检索为准，行号只作快速定位**。

| # | 问题 | 我的把握程度 |
|---|---|---|
| Q1 | 引擎的**最低 Python 版本**要求 | 只知实机跑过 3.11 / 3.12（`__pycache__` 痕迹）。**无声明** |
| Q2 | **分发形态**最终选哪个（拷目录 / submodule / PyPI） | ~~spec 提到 submodule，但仓库里**无 `.gitmodules`**。未定~~ **拆仓后更新（本次实核实）**：游戏仓 `dragonfall` 已有 `.gitmodules`（`[submodule "framework"]` → 框架仓 `framework-engine`）→ **submodule 形态已采用**。是否再发 PyPI 仍未定 |
| Q3 | commit message **类型/前缀约定** | 无 `CONTRIBUTING.md`、无钩子、无相关文档。**未取证** |
| Q4 | 是否有**引擎独立 CHANGELOG / 版本号** | 无（`metadata.yaml` 的 `version: 0.105.0` 是插件版本） |
| Q5 | `Battle.dmg_mult` / `pet` / `st` 是**遗留待删**还是**预留接口** | 三个都只写不读；无从判断意图。**待确认** |
| Q6 | `support/battle_bars` 的 6 个 `charge_*` 是「将来接入」还是「已废弃」 | 零外部引用，但模块 docstring 把它当正式能力描述。**待确认** |
| Q7 | `_archive_unused/` 目录里的东西是否与引擎相关 | **未检查**（不在本次只读范围内） |
| Q8 | `game/data/skills.py` 的 20 个未映射 `effect=` 是「待实现」还是「已废弃数据」 | 只能证明「当前静默无效」，无法证明意图 |
| Q9 | `EFFECT_RULES` 里 `bleed` 的 `"type": "flat", "per_layer": 0` 是否曾被某版消费 | 当前无消费方；历史未知 |
| Q10 | 本 wiki 的行号在并发改动下会漂移多少 | `docs/ENGINE_CONTENT_SPLIT_PLAN.md` 自己记录过：侦察期检测到并行 agent 在改
`battle2_rules.py` 与 `class_mech_proc.py`，行号已漂移。**引擎侧（`saintess_engine/*`）锚点当时未变**，但本 wiki 写作期间这两个内容侧文件仍在被改 |

### 未取证的写作（明确标注）

以下内容我**没有**像其他条目那样逐项核实，属「按代码结构推断」：

| 项 | 位置 | 说明 |
|---|---|---|
| `support/battle_bars` 各函数的**语义细节**（条触发/免疫窗口的具体算法） | [reference/api.md](reference/api.md) 的函数表 | 我核实了函数存在、签名、外部引用情况；**没有逐行核算法** |
| `ai.py` 的 `weighted` 选择器边界行为（权重全 0 时的回落） | [reference/api.md](reference/api.md) | 只读了代码路径（`pool[0][1]` 回落），**没有实测** |
| `serialize` 在**极端旧档**（缺 `sides` / 缺 `killed`）下的行为 | [guides/serialize-and-resume.md](guides/serialize-and-resume.md) | 读了代码（`or {}` / `or []` 兜底），**没有实测** |
| 内容侧 `we_*` / `bar_*` / `cond_*` 动作的**逐字段清单** | [reference/effect-actions.md](reference/effect-actions.md) 的族名前缀表 | 只核实了前缀与数量，没有逐动作列参数 |
| `contributing/conventions.md` §9 的提交约定 | 该页 | 已明确标注为**未取证** |

## 6. 我实际运行过的验证（供复核）

写文档期间在仓库外跑的只读探针（**不改仓库**）：

1. **最小可跑性实验** — 裸引擎 / 逐项摘 hook → 定位「能打出伤害的最小装配集」；
   在 `game.` 上下文与「拷贝成顶层包 `saintess_engine`」两种形态下都跑通
2. **`first-mechanic` 示例实测** — 注册动词 + 名词声明 + `triggers` 装配，
   实测伤害与回血日志；另跑两个反例（未声明名词、缺参数）确认静默 no-op
3. **`EVENTS` 抄全核对** — 从 `effect_triggers.py` 正则抽出元组内容，得 26 项
4. **fire 点位扫描** — 对 `saintess_engine/**` 逐行匹配 `_fire(battle, "..."` 与
   `fire(self, "..."`，得出 23 个自然点位 + 3 个无点位 + `skill_hit`/`attack_hit` 的变量形式
5. **声明表结构化解析** — `ast` 解析 `battle2_rules.py`，得 `EFFECT_ACTIONS` 51 条、
   `EFFECT_RULES` 78 条、`MECH_CASH` 9 条、`PASSIVE_PROC` 42 条，
   及字段出现次数并集
6. **消费方 grep** — 对 `debuff_scale` / `on_threshold` / `wake_on_hit` / `tag` / `dot` /
   `period.type` / `period.per_layer` / `period.dmg_type` / `reduce` / `reduce_left` /
   `st["reduce"]` 逐项全仓检索
7. **零外部引用 API 扫描** — `ast` 收集 `saintess_engine/**` 全部模块级函数，
   对全仓（排除定义文件）统计引用数
8. **import 拓扑 AST 扫描** — 区分模块级与函数内 import，检出 2 对双向互指
9. **`strict=True` 实测** — 确认未装配 hook 抛 `EngineNotConfigured` 且消息点名 hook
10. **惰性装配副作用实测**（**拆仓前**在游戏仓记录） — `import game.battle2` + 首次读 hook 后，
    `game.content` / `game.data` 进入 `sys.modules`；13 个 hook 全部被 mount

## 相关

- 每个缺口的**使用者友好**表述散落在各 reference 页（本页是总表）
- 边界策略 → [architecture/boundaries.md](architecture/boundaries.md)
- 分发前清单 → [contributing/release.md](contributing/release.md)
