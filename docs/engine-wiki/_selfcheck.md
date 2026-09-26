# 自检：未能取证 / 待确认清单

> 本页是**诚实清单**。所有条目都在写文档时逐项 grep / 运行核实过；
> 「结论」列是核实结果，「类型」列区分：
>
> - **`缺消费方`** = 代码/声明存在但没有读取它的地方（不是笔误，是真实历史遗留）
> - **`待确认`** = 我无法从代码或文档确定，需要人回答
> - **`注释≠代码`** = 注释/文档的陈述与代码当前行为不一致
> - **`未取证`** = 我没有做足够的验证就写进 wiki（一律标出）

## 0. 2026-09-11 处置结果（**先读这一节，再看下面的原始清单**）

写这份清单时（拆仓当天）引擎工作区正被并行改动，所以本页保留了**取证当时的原貌**。
2026-09-11 收尾轮把清单逐条复跑（**用当前仓库状态重跑，不信历史结论**）并处置如下。

### 0.1 已删除（零消费方代码）

| 项 | 处置 |
|---|---|
| `gauge.charge_*`（6 函数 + 蓄力三律整节） | **已删**。它是《云海猎团》弓手/时咒的**职业机制**残留（内容侧从未有技能声明电荷配置），与「引擎零内容知识」冲突。设计口径留档游戏仓 `docs/archive/REFACTOR_v181_CLASS_MECH_ASSEMBLY.md『v139 形态层设计留档』` + git 历史 |
| `Battle.dmg_mult` / `pet` / `st`（构造参数 + 字段） | **已删**。⚠️ 其中 `dmg_mult` 不是「遗留待删」而是「传了不读」的**活功能** → 见 §0.4 |
| `Battle._cast_ctx` / `_target_ctx` / `_events` | **已删**（只初始化、零读） |
| `DEFAULT_CT_WAIT` | **已删**（常量零消费） |
| `schedule.CAST_ITEM` / `HOT_INTERVAL` | **已删**（零消费；游戏仓 `game/core/constants.py` 自己有同值常量） |
| `actions._aoe_falloff_apply` + AOE falloff 假路径 | **已删**。原代码读了 `info["aoe_falloff"]` 却调一个原样返回的占位函数 → 「声明了不生效」的误导性半接线。现明确：**本引擎不实现 AOE falloff**；第三方请用 `dmg_calc` 触发器按 rank 自行乘算 |

### 0.2 已修正（注释 ≠ 代码）

C1（`19 时机` → 26）、C2（`16 个` → 23）已改。C3/C4/C5/C6 在**游戏仓**
`game/data/battle_rules.py` 已加取证纠正注释（`debuff_scale` / `period.dmg_type` /
`finisher.crit_at` / MECH_CASH 的 `heal_clear`·`bonus_clear` 两个 mode 装配器不分派）。

### 0.3 已定案（原「待确认 / 未取证」）

| # | 原问题 | 定案 |
|---|---|---|
| Q1 | 最低 Python 版本 | 未声明；实机跑过 3.11/3.12 → **发布前必须在元数据/README 声明**（v0.1 遗留项） |
| Q2 | 分发形态 | **submodule 已采用**（游戏仓 `.gitmodules`）；是否再发 PyPI 未定 |
| Q3 | commit message 约定 | 未取证 → **不引入新规范**，按现有 `feat/fix/chore(scope):` 惯例 |
| Q4 | 引擎独立 CHANGELOG / 版本号 | `saintess_engine/version.py` 已有版本常量（编辑器/模拟器 fail-closed 校验）；CHANGELOG 未建 |
| Q5 | `Battle.dmg_mult` / `pet` / `st` 是遗留还是预留 | ⚠️ **都不是** —— `dmg_mult`/`pet` 是**调用方在用、引擎没读**（静默失效的活功能）。见 §0.4 |
| Q6 | `charge_*` 是将来接入还是已废弃 | **已废弃** → 已删（§0.1） |
| Q8 | 20 个未映射 `effect=` 是「待实现」还是「废弃数据」 | **待实现**（玩家可见的静默 no-op）→ 游戏仓 `docs/archive/REFACTOR_v181_team_effects_plan.md` |
| Q9 | `bleed` 的 `type` / `per_layer` 是否曾被消费 | 无历史消费痕迹；与 `period.dmg_type` 同批处置 |
| Q10 | 行号漂移 | 已有门禁 `tests/test_wiki_refs.py`（drift 必须 0）+ 工具 `tools/remap_wiki_refs.py`（内容锚定位移） |
| — | §4 的 B1-B6「引擎里的内容知识」 | **定案为引擎公开词汇表契约** → [../engine-vocabulary-contract.md](../engine-vocabulary-contract.md) |

### 0.35 ★ 2026-09-11 第二波：DOT 混合公式补齐（另 3 个「重构丢功能」）

`dmg_mult` 同类问题在 DOT 通道上还有两处，同批修掉（权威 = 下游游戏 `32_数值设计.md` §DOT_DEFS）：

| 项 | 症状 | 处置 |
|---|---|---|
| **atk/matk 系数段** | 新引擎 `_settle_time_effects` 只读 `pct_max_hp`/`pct_cur_hp`，权威公式的 `atk×a + matk×m` 段丢失 → 依赖攻击力成长的 DOT（毒/流血/腐蚀）实机偏弱 | ✅ 接线：`period.atk`/`period.matk` × **施法者强度快照**（`entry["src"]`，`note_dot_source` 记录） |
| **总抗段 `(1−总抗)`** | 权威公式含 `× (1−总抗)`（`总抗=min(resist_cap, dot_res+adapt)`）；新引擎整段丢失 → `dot_res`/`adapt` 成死字段（**它们是「重构丢功能」，不是遗留冗余**） | ✅ 接线：`period.resist_cap` 声明即启用；未声明 = 行为不变 |
| **低血翻倍 / 单层上限 / boss 折扣** | 旧引擎的「放血 ×2」「pct_cap 1%/层」「boss pct×0.5」在新引擎缺失或只做了 per-entry `pct_boss` | ✅ 接线：`double_low_hp_pct` / `pct_cap` / `boss_pct_mult`（条目级 `pct_boss` 优先、不叠乘） |

**结论**：DOT 板块的真正问题不是「有死字段」，而是**权威公式在新引擎里只落了一半**。
接线后下游游戏把 4 个 DOT 的系数改为**生成自 DOT_DEFS**（单一字面源），
使数值门禁（模拟器读 DOT_DEFS）与实机公式重新一致。

### 0.4 ★ 本轮最重要的取证：`dmg_mult` 不是死字段

`Battle(dmg_mult=…)` 在**游戏仓 `game/commands/combat.py` 的世界 Boss 构造处是活调用**：

```python
# 旧引擎：_boss_dmg_filter 里 dmg = int(dmg * self.dmg_mult)（GM「gm_伤害」倍率）
# battle2：Battle.__init__ 只存 self.dmg_mult，全仓零读取 → GM 倍率静默失效
```

⇒ 教训：**「字段只写不读」要分两种** ——
① 谁都写的遗留字段（删）；② **调用方在写、引擎没读**（= 静默失效的活功能，修，不能删）。

本轮修法（**零引擎改动**）：内容侧 `game/services/battle_worldboss_procs.py` 走
`taken_calc` 承伤乘区挂到 Boss actor；测试 `tests/test_v181_worldboss_gm_dmg.py` **13/13**。
同一条判定还救了 `pet=`：宠物传了但引擎不读 → 归「随从 actor 工厂」线
（游戏仓 `docs/archive/REFACTOR_v181_companion_line.md`）。

---

## 1. 声明了但无消费方（`缺消费方`）

### 1.1 `EFFECT_RULES` 字段

| 字段 | 核实方法 | 结论 |
|---|---|---|
| `debuff_scale` | 全仓 `grep -rn "debuff_scale"` → **2026-09-11 已接线**：`landing.deal_damage` 逐状态累加乘区（对称 `stat_scale`） | ✅ **已消费**。`hunt_mark`（+8%/层 cap3）/ `soul_mark`（+6%/层 cap3）/ `curse`（+20% cap1）现已生效 |
| `on_threshold` | 全仓 grep → 只有 `effects.py:244/244/250` 的判据关键词 + `battle_rules.py:27` 的声明 | **无消费方**。`threshold` **事件**有引擎点位（`effects.py:456`），但这张映射表没被读 |
| `wake_on_hit` | 原只有 `battle_rules.py:400` 的声明 | ✅ **2026-09-11 已接线**：`landing.deal_damage:167-179` 遍历承伤者状态读该字段（同时删掉 landing 内硬编码的 `sleep` 游戏名词 —— 见 B2 表） |
| `tag` | grep `state_def(...).get("tag")` / `cfg.get("tag")` → 空 | **无消费方**。`act_apply` 读的是 params 的 `tag`（作 key 兜底，`effects.py:344`） |
| `dot` | 全仓 grep → 只有 `effects.py:280` 判据；78 个 key 里无一使用 | **无消费方**（V5 后 DOT 统一走 `period`） |
| `name` | 引擎无读取（内容侧读） | 引擎不读，**符合设计**（展示名属内容侧） |
| `negative` | 引擎无读取（内容侧 `class_mech_proc.py:767` 读） | 引擎不读，**但它是内容侧约定的关键字段** |
| `start_full` / `start_classes` / `channels` / `load_tiers` / `overload_heal_pct` | 引擎无读取，内容侧装配器读 | 引擎不读，**但缺 `start_classes` 会导致内容侧钩子不装配**（隐性） |

### 1.2 `period` 子字段

| 子字段 | 结论 |
|---|---|
| `type` | **无消费方**（参考实现 `bleed` 写了 `"type": "flat"`） |
| `per_layer` | **无消费方**（同上 `"per_layer": 0`） |
| `dmg_type` | **2026-09-11 已接线**：DOT 落地改传 `dmg_kind=period.get("dmg_type")`（`schedule.py:761`） | ✅ **已消费**。`corros` 的「真伤 DOT」声明现成立（真伤 → 物免/魔免/格挡全跳过）；非真伤 DOT 仍空 kind，行为与接线前一致 |

### 1.3 引擎 API / 常量

| 名称 | 位置 | 结论 |
|---|---|---|
| ~~`Battle.dmg_mult`~~ | ~~`battle.py:75`~~ | **已删**（2026-09-11）——⚠️ 实为『调用方在用、引擎没读』的静默失效功能，见 §0.4 |
| ~~`Battle.pet`~~ | ~~`battle.py:76`~~ | **已删**（2026-09-11）——同上（宠物参战归随从线，见 §0.4） |
| ~~`Battle.__init__(st=...)`~~ | ~~`battle.py:39`~~ | **已删**（2026-09-11，全仓 0 处传参） |
| ~~`Battle._cast_ctx` / `_target_ctx`~~ | ~~`battle.py:88-89`~~ | **已删**（2026-09-11） |
| ~~`Battle._events`~~ | ~~`battle.py:97`~~ | **已删**（2026-09-11） |

> ✅ **2026-09-26 补（N10 收口 2）**：上面三条「调用方在用、引擎没读」的**调用点实参**
> 也已清干净 —— `Battle.__init__` 的 `**kwargs` 一并删掉（签名即全部），
> `pet=` / `dmg_mult=` 这类幽灵参数现在**传即 TypeError**；内容侧对应实参全清。
> 门禁：`tests/test_n10_title_bonus_removed.py` 第 5 节（28/28）。
| ~~`DEFAULT_CT_WAIT = 2.0`~~ | ~~`battle.py:25`~~ | **已删**（2026-09-11） |
| ~~`schedule.CAST_ITEM = 1.0`~~ | ~~`schedule.py:29`~~ | **已删**（2026-09-11） |
| ~~`schedule.HOT_INTERVAL = 1.0`~~ | ~~`schedule.py:36`~~ | **已删**（2026-09-11） |
| `schedule.next_ct` | `schedule.py:48` | 有定义、无调用方（实际推进走 `_after_act`） |
| `state_effects.stat_scale_of` | `state_effects.py:18` | 仅测试引用 |
| `actions._aoe_falloff_apply` | `actions.py:569` | **占位实现**（原样返回 logs）。`info["aoe_falloff"]` 在 `actions.py:375` 被读取但随后被丢弃 → AOE falloff 实际未生效 |
| `formation.reachable_units` | `formation/__init__.py:28` | 零外部引用 |
| `expr.expr_or` | `expr/__init__.py:221` | 零外部引用 |
| `gauge.charge_*`（6 个） | `gauge/__init__.py:244-321` | **全部零外部引用** —— 蓄力三律无消费者 |
| `support.battle_bars.bar_should_trigger` / `bar_preserve` | `:164` / `:204` | 仅内部/单点引用（`bar_preserve` 被命令层 Boss 脚本用 1 处） |
| `effects.effects_from_skill(..., caster_side_is_player=True)` | `effects.py:217` | **第三个参数在函数体里从未使用** |
| `config.set_hook` | `config.py:148` | 零外部引用（都走 `mount`） |
| `serialize.to_state` 的 `flags` | `serialize.py:45` | 恒写入 `{}`；**没有读取方**，也没有写入方 |
| `Battle.auto_run(max_steps=500)` | `battle.py:344` | 全仓调用点**只在 `tests/`**（游戏仓 `test_battle_add_actor.py:159`、游戏仓 `test_battle_bridge.py:154`、游戏仓 `test_battle_bar_procs.py:240` 等），内容侧零调用 —— 实质是**测试/AI 模式辅助**，不是生产路径（生产走 `human_act` + `advance`） |

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
| `actor["dot_next"]` / `actor["dot_jumps"]`（dict） | 引擎周期结算的运行期辅助（`schedule.py:611-612` 惰性建），**同样落盘**。这是「续战能对上」的原因，但字段名与内容无关 |
| `actor["_dmg_taken_mult"]`（float） | 承伤乘区（`landing.py:96-103` 读）。由上层直写（例 游戏仓 `commands/boss_script.py:684`）；**同样落盘** |
| `actor["reduce_left"]` / `reduce_all_left` | `effects.act_apply` 写（`effects.py:486`）+ 内容侧 bridge 透传/播种；**无消费者**（见 §1.3） |
| `actor["act_count"]` | `actor_auto` 每动 +1（`battle.py:443`），AI 的 `round_mod` 谓词读它；落盘 |

## 2. 事件点位

| 事件 | 结论 |
|---|---|
| `phase` / `player_low` / `pv_broken` | **在 `EVENTS` 里但引擎零 fire 点位**（设计如此，由上层驱动 —— `effect_triggers.py:38-40`） |
| `skill_hit` / `attack_hit` | **有点位但静态 grep 不到**：`actions.py:501` 用变量选事件名（`ev = "attack_hit" if info.get("_basic") else "skill_hit"`）。文档若按 grep 结果断言「无点位」会是错的 |
| `EVENTS` 实际条目数 | **26**（不是 docstring 说的「19 时机」）。引擎插桩自然点位 **23** 个（不是注释说的「16 个」） |

## 3. `注释 ≠ 代码`（发现了 6 处）

| # | 位置 | 注释说 | 实际 |
|---|---|---|---|
| C1 | `effect_triggers.py:24` | 「19 时机 + …」（# 事件全集） | `EVENTS` 实际 26 项 |
| C2 | `effect_triggers.py:40` | 「引擎已插桩自然点位 = 除 phase/player_low/pv_broken 外 **16 个**」 | 实际 23 个 |
| C3 | 游戏仓 `battle_rules.py:696` | 「基础 8% 走 `debuff_scale` **引擎天然段**」 | `debuff_scale` **无消费方**（§1.1） |
| C4 | 游戏仓 `battle_rules.py:292` | `corros` 注释「**真伤** DOT」 | `period.dmg_type` 无消费方；实际不是真伤（§1.2） |
| C5 | 游戏仓 `battle_rules.py:531` | `finisher.crit_at: 4`「声明先行——crit roll 前钩子就绪后生效」 | **声明先行 = 当前不生效**；装配器不读 `crit_at`，也没有消费它的钩子（已核实的缺口） |
| C6 | `battle_rules.py:510` | `MECH_CASH` docstring 列 `bonus_clear` 模式 | 装配器 mode 分派里没有它（`class_mech_proc.py:2350` 只认 4 个 mode），注释也自承「R1b 未用」 |

另：`MECH_CASH` 声明了 `heal_clear`（`faith_unload`），装配器**不处理**该 mode
（`class_mech_proc.py:2350` 的 `if mode not in (...)` 直接 continue）——
兑现实际走技能数据的 `res_cost`，声明条目里的 `note` 字段自己写明了这件事。

## 4. 边界瑕疵（引擎里的内容知识）—— 门禁拦不住的部分

门禁 `tests/test_engine_purity.py` 只验证 **import 方向**。
以下都是已核实的**语义残留**：

| # | 瑕疵 | 位置 |
|---|---|---|
| B1 | ~~`kinds/` 枚举值写死中文（`PHYS = "物理"` …）~~ **2026-09-13 P4 下沉已消除** | 引擎侧无 `kinds/`（词表移居内容侧，引擎只经 `config.kind_of` 读值） |
| B2 | 固定效果 key：`"death_guard"`（濒死保护）、`"heal_amp_pct"` / `"heal_down"` / `"_anti_heal_pct"`（受疗修正）。（原含 `"sleep"` 打醒 —— **2026-09-11 已数据化**移除，改读 `wake_on_hit` 字段） | `landing.py:177-190, 248, 384-407` |
| B3 | `effects.act_apply` 里 `if key == "reduce":` | `effects.py:485` |
| B4 | `is_boss` / `role == "boss"`（控制减半 / DOT `pct_boss`） | `effects.py:383` · `schedule.py:658,286` |
| B5 | `battle.py` 里 `"player"` 阵营名 | `battle.py:188, 515` |
| B6 | `_is_stack_resource` 的判据关键词含无消费方的字段（`debuff_scale` / `dot` / `on_threshold` / `guard_hp_pct`） | `effects.py:277-281` |

B6 值得单列说明：这些字段**没有消费者**，但它们**存在与否会改变 `mech` 的分派结果**
（有 `debuff_scale` → 走 `apply op=add` 叠层；没有 → 走 `EFFECT_ACTIONS` 名词翻译）。
所以它们是「死字段但活判据」—— 清理时必须同时考虑分派影响。

## 5. `未取证 / 待确认`（需要人回答）

### 5.0 快照与漂移警示

- **写入快照**：`git rev-parse HEAD` = `50eb8dc`
  （`feat(engine): 单一装配入口 apply_game_content（S7）+ S6' 内容层重组快照`）
- 写文档时 `git status` 显示工作树**除本 `docs/engine-wiki/` 外无改动**，
  即本文所有行号对应的是那次 HEAD 的**已提交状态**
- ⚠️ **行号会漂移**：`docs/archive/ENGINE_CONTENT_SPLIT_PLAN.md` 自己记录过，
  侦察期检测到并行 agent 正在改 `game/data/battle_rules.py` 与
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
| Q10 | 本 wiki 的行号在并发改动下会漂移多少 | `docs/archive/ENGINE_CONTENT_SPLIT_PLAN.md` 自己记录过：侦察期检测到并行 agent 在改
`battle_rules.py` 与 `class_mech_proc.py`，行号已漂移。**引擎侧（`saintess_engine/*`）锚点当时未变**，但本 wiki 写作期间这两个内容侧文件仍在被改 |

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
5. **声明表结构化解析** — `ast` 解析 `battle_rules.py`，得 `EFFECT_ACTIONS` 51 条、
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
    `game.content` / `game.data` 进入 `sys.modules`；hook 全部被 mount（V3 起 15 个）

## 相关

- 每个缺口的**使用者友好**表述散落在各 reference 页（本页是总表）
- 边界策略 → [architecture/boundaries.md](architecture/boundaries.md)
- 分发前清单 → [contributing/release.md](contributing/release.md)
