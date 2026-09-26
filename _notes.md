# w1 引擎线 交接单（2026-09-26 · 第二轮 · 收上一轮被额度墙砍剩的三条）

> 工作树 `C:/Users/yuyu/fw-wt/e8` · 分支 `e8-host-text` · 冻结点 `13a2f16`（已合入 main，继续在其上提交）
> 上一轮同树已落：`c53b427` P-54 · `4555c8b` P-59。本轮补 P-51 / P-3 / P-46 核实，P-1 只登记。

## 落链

- 分支 `e8-host-text` · 本轮三个提交（按序）：
  - `a49422a` **P-51** mp 两个入口声明化（基础回复 + 蓝不够不让放门槛）—— **22 文件**（+332/−61；
    引擎侧 3 文件 +126 行，其余 = wiki 文档行号随动 + 2 行数锚点）
  - `0473aec` **P-3** 装载口加装载告警（`$builtin:false` + 「引擎默认域无文件」）—— **4 文件**（+158/−8；
    引擎侧 1 文件 +68 行）
  - 本单 = 紧随 `0473aec` 之后的 `_notes.md` 单文件提交（**P-46 只写结论 + P-1 登记**，
    无任何引擎改动）；自身 sha 不自引用，见 `git log -1 --format=%h`。
- 交付后 `git status --porcelain` **空**（三个提交全部落地，无脏树）。

## 判据与证据（原始尾行）

```
① tests/run_all.py（本轮跑 4 次：首次 93/95 —— 红的两支是 wiki 行号/行数锚点，属改引擎行的
   **预期连带**，remap + 锚点同步后转绿；随后 two-state 撤改前后与终态共 3 次全绿）：
   文件: 95 个，通过 95，失败 0
② tools/check_wiki_refs.py：rc=0 · wiki 行号引用自检：可判定 336 处（另纯行号档 61 处）
   → drift 0 处；语义存疑 57 + 9 处；跨仓 149 处；未解析 0 处
③ P-51 单文件门禁：tests/test_engine_neutral_fallback.py：== 结果：通过 76 / 共 76 ==（新增 24 项）
④ P-3 单文件门禁：tests/test_package_stack.py：===== 结果：通过 23 / 23 =====（新增 7 项）
⑤ P-51 两态（撤改验证）：$LOCALAPPDATA/Temp/p51_twostate.py 在 `git stash` 前后各跑一次
   ⇒ 9447 B ↔ 9447 B，`cmp` **IDENTICAL ✅**（7 个 _skill_usable 用例 + 时间推进三拍
   含 DOT/HOT/时效 + 全场 to_state 快照）
⑥ P-3 两态（撤改验证）：$LOCALAPPDATA/Temp/p3_twostate.py 前后各跑一次 ⇒
   ok / errors / 有效域表 / domain_path 结果**逐字段相同**；唯一差别 = `warnings`
   （改前 `warnings_key_present=False`，改后 `True`）
⑦ P-3 真包实测：$LOCALAPPDATA/Temp/p3_warn_probe.py
   · examples/minimal-game ⇒ 告警：「包 minimal-game 的域声明写了 `$builtin: false`……被跳过的域：commands、texts、tlogs」（改前零告警、ok=True）
   · games/my_game ⇒ 3 条「引擎默认域 'X' 声明的文件在**所有层**里都不存在（找过：…）」
   · games/orlandia ⇒ 告警 0 条（它自己建了这三张表）· ok=False 的原因与 P-3 无关（缺宿主 bind 注入）
```

## 真源行（★ 主线合入时请落进 aetheran-plan）

- 台账 §3 变动（`00_总纲/AETHERAN_推进进度.md`）：
  - **P-51** ⏸ ⇒ **已落引擎侧一半**：两个入口（`mp_regen_fn` / `mp_gate_fn`）已开、**引擎零数值**、
    未装配 ⇒ 与打前逐字节相同（引擎 `a49422a`）。**内容侧那三条选项（甲/乙/丙）仍未裁** —— 甲档要真落
    「基础回复 + 蓝不够拦」只需内容侧声明这两个钩子（回复率 / 门槛线 / 句子都归内容侧）。
    建议在 P-51 条目尾补一句逐字：「★ 2026-09-26 引擎侧两个入口已开（`a49422a`：`mp_regen_fn` /
    `mp_gate_fn`，未声明 = 现状不变）；数值口径仍待拍板。」
  - **P-46** ⏸ ⇒ **已核实**（结论见下节）：`is_boss` / `role == "boss"` 已被 E3（`d01c1e0`，2026-09-25）
    收掉；`boss_pct_mult` 降级为「内容侧声明表字段名」。建议把 P-46 条目改写成「**2/3 已收**」并指向
    `extends/ext_combat/battle/traits.py`。
  - **P-3** ⏸ ⇒ **装载口警告已落**（引擎 `0473aec`：`PackageStack.warnings()` + `probe_stack["warnings"]`）；
    **另一半（引擎自带空模板 / 数据包自建 / 向导生成）仍待拍板**，本批只报不选。
  - **P-1** ⏸ ⇒ **仍未动**（只登记，见下节）。
- 其他真源（口径表 / 宪法 / 命令表）：本轮**无涉及**（没动数值、没动指令表、没动真相文档）。
- 引擎 wiki（已随提交落）：`concepts/config-injection.md`（+2 行 hook 表 · 「22 个 hook」→「25 个 hook」
  —— 该数字**在 P-54 时就已经是 23 而写着 22**，本批顺手改正）、
  `reference/package-format.md` 新增 §4.4.1「装载告警」、`reference/api.md` · `getting-started/first-battle.md`
  的 config 行号与 hook 数、`README.md` 引擎行数 12 772 → 12 862；14 篇文档的行号随动（46 处）。

## ③ P-46 核实（★ 只写结论，未改一行）

**核法**：全仓 grep（`saintess_engine/` · `extends/` · `editor/` · `tests/` · `examples/` · `games/`）
＋ 逐行读 E3 的提交 `d01c1e0`（`git show d01c1e0`）。原始命中见 `$LOCALAPPDATA/Temp/p46_evidence.txt`。

**结论（三样逐样）**

1. **`is_boss` / `role == "boss"`（引擎的身份判定）—— ✅ 已被 E3 收掉。**
   `saintess_engine/` 本轮 grep **零命中**；`extends/` 只剩两处**注释**（`battle/traits.py:4` ·
   `ext_achieve/rule/engine.py:140-141`）。E3 = 引擎 `d01c1e0`（2026-09-25 21:18
   `refactor(引擎): 「boss」这个游戏概念从引擎里搬出去（E3 刀1 · 审计 P-46 之一）`）三处一起搬：
   · `effects.py` 控制时长减半：`if holder.get("is_boss") or holder.get("role") == "boss"`
     → `traits.has_any(holder, state_def(key)["ctrl_half_traits"])`
   · `schedule.py` DoT 折扣档：`is_boss or role=="boss" or is_elite`
     → `traits.has_any(a, period["trait_tags"])`（`_trait_like`）
   · `ext_achieve/rule/engine.py`：把 `is_boss` / `is_elite` 两个**游戏字段**映射成 "boss" / "elite"
     标签 → 改成 `enemy["traits"]` **原样透传**，判定交给规则声明（`enemy_tag`）
   现行为由内容侧声明驱动：`extends/ext_combat/battle/traits.py`（`of/has/has_any`，空名单 ⇒ 一律 False）。
2. **`boss_pct_mult`（含同族 `pct_boss` / `pct_cur_boss`）—— ⚠️ 没收掉，但性质已降级。**
   它今天只出现在 `extends/ext_combat/battle/schedule.py:620-625`（`pct_boss` / `boss_pct_mult`）与
   `:637-639`（`pct_cur_boss`），且**两条分支的门槛都换成了内容侧标签名单**
   （`if _trait_like and period.get("pct_boss")` / `elif _trait_like and period.get("boss_pct_mult")`）
   —— 也就是说：引擎不再「自己判谁是 boss」，只是**按名读内容侧声明表里的一个键**。
   ⇒ P-46 点名的三样里 **2 样已收、第 3 样从「引擎内置游戏概念」降为「声明字段名」**。
   要把名字也收掉 = 连**内容侧声明表**一起改名（`extends/ext_combat` 的 effect_rules 声明 +
   orlandia `content/rules/effect_rules.json` 的 `pct_boss` / `boss_pct_mult` / `trait_tags` 同批改），
   属跨层改名 + 会动已配平数值面 ⇒ 本线**不擅动**，登记在此。
3. **顺带发现（只报不改）：wiki 文档没跟 E3。**
   `architecture/boundaries.md:189/190`（B4 / B5 行）· `_selfcheck.md:180`（B4 行）·
   `concepts/effects.md:114` · `concepts/actor-model.md:18/106` · `getting-started/first-battle.md:77` ·
   `architecture/design-decisions.md:17` · `editor/glossary.py:289` 的 note 都还按
   「**引擎真读** `is_boss` / `role == "boss"`」描述（E3 只改了它们的**行号**，没改判定描述）。
   建议主线把这几行的口径统一改成「身份标签由内容侧 `traits` 声明、引擎只做 `traits.has_any`」。

## ⑤ P-1（★ 只登记不做 · 本轮零改动）

现场（本轮 grep 复核，一行没动）：`extends/ext_combat/battle/stats.py:94-101`（缺省回落
`battle.title_bonus`，N10 前过渡语义「两路都活」）· `battle.py:35/67`（`Battle.__init__` 的
`title_bonus` 形参 + 实例字段）· `serialize.py:45/68`（存档写入 / 读回）· `serialize.py:107/113`
（actor 级 `title_bonus` → `stat_bonus` 迁移 + `pop`）。
⇒ 这一条要动**引擎公开签名 + 存档面**（老档兼容），按丙档口径**留给鱼鱼拍板**：本批不碰。

## 裁决记录（乙档自决的，逐条写理由）

1. **两个 mp 钩子的「回执形状」自决**：基础回复取 `{"mp": 数, "text": 可选}`（与既有
   `segment_plan_fn` 的 `{"cast":…, "recover":…}` 同形：**单一形状、键名显式**）；门槛取
   `None = 放行 / 非空文本 = 拦下并把这段当回话`（与 P-54 `route_miss_text_fn` 同一条规矩）。
   理由：红线的两条一起满足 —— （a）引擎**零数值**（「多少算不够」在 hook 里判，引擎只把
   `_skill_pay_of` 折算出的 `need_mp` 转述过去）；（b）引擎**零玩家文案**（拦下时说的话由内容侧给，
   不存在引擎内置兜底句）。
2. **「声明了却给不出可判读的回执」⇒ 抛 `EngineNotConfigured`（不静默放过）**：理由同上一条规矩
   （P-54 / `recover_*` 的既有口径）；但**「不配」是合法状态**（走 `optional_hook`，不受 strict 影响），
   否则「这款游戏没有基础回复」会被当成配置错误。
3. **基础回复的挂点 = `_settle_time_effects` 的逐 actor 循环**（每次时间推进结算问一次），
   而不是「每回合 / 每次行动」。理由：引擎**零节奏知识** —— 「多久回一次」必须留给内容侧；
   挂在这里内容侧按 `battle._now` 自己判节奏即可，且与既有 period 回复（`dir=mana`）同刻同层。
4. **只在 `actor["mp"]` 已存在时写回**（同 `_spend_skill_cost` 的守卫）：避免给怪 / 第三方 actor
   塞新字段 ⇒ **存档面一字不动**（红线）。
5. **P-3 告警只做两条、只挂在 `PackageStack`**（不扩到 `records.read_domain_decl`）：理由 = §2-4
   复现的陷阱就在装载口（`probe_stack`）这一层；扩到别的读口会改它们的输出面（超出「只加警告」）。
   告警收集用 try 包住、失败降级成一条告警 ⇒ `domain_decl()` 的抛错行为与 `probe_stack()` 的
   `ok` / `errors` 口径**逐字不变**（两态实测证实）。
6. **顺手改正「22 个 hook」→「25 个 hook」**：P-54 落了 `route_miss_text_fn`（已是 23）、E4 落了
   `expr_vars_fn`，文档数字一直没跟；本批再加 2 个 ⇒ 一并改成 25（只改文档数字，不动门禁判据）。

## 待鱼鱼拍板（丙档：本线没动的）

| 项 | 本批状态 | 要拍的是什么 |
|---|---|---|
| §6 **P-3 另一半** | 只落了「装载口警告」；语义一字未动 | 「引擎自带空模板 / 数据包自建 / 向导生成」三选一（择一才动逐文件作用域 / 新建包向导） |
| §6 **P-1** | ✅ **本轮已落**（2026-09-26，见下「P-1 N10 收口」段） | 原待拍「动 `battle.title_bonus` 回落 + `Battle` 签名 / 存档面」已由鱼鱼直接派单执行 |
| 台账 §3 **P-51 数值口径** | 引擎侧两个入口已开齐；**没有填任何数** | 甲（基础回复 + 蓝不够拦，需内容侧声明）/ 乙（撤掉玩家可见的「耗法」）/ 丙（不动）三选一 |
| 台账 §3 **P-46 残余** | 已核实结论；未动一行 | 要不要连内容侧声明表一起把 `pct_boss` / `boss_pct_mult` / `pct_cur_boss` 改名（跨层 + 触数值面） |
| 新（本轮发现） | 只报不改 | wiki 7 处（B4/B5 等）仍按「引擎真读 is_boss」描述 ⇒ 建议主线统一改成 traits 口径 |

---

## ★ 2026-09-26 交互会话（格温 · 引擎线直管）· 追加

鱼鱼口径：「**引擎先做完最好，能并发就并发**」⇒ 上一节那张「待鱼鱼拍板」表**五条全部开工/结案**，
四条并发车道（各自独立 worktree，不碰主工作树；本会话持引擎车道锁）：

| 项 | 裁决 | 车道 | 真源行（主线合入时请落进 aetheran-plan） |
|---|---|---|---|
| 台账 §3 **P-51 数值口径** | 选**甲**（内容侧声明两个钩子：基础回复 + 蓝不够拦） | 已由阿斯特兰线落链（`w-g-numeric` · 判据 `probe_mana`） | 台账 P-51 条目尾补逐字：「★ 2026-09-26 **甲档已落**：内容侧 `content/rules/mana.json` 声明回蓝（每 20 游戏秒 1 点）+ 「蓝不够」门槛（够这一手就放、不留底）+ 起手（档上有值照值、缺格算满），`content/mana.py` 挂 `mp_regen_fn` / `mp_gate_fn`；**引擎侧零改动**（`a49422a` 原样即够）。判据 = 新第 43 支 `scripts/probe_mana.py`。」 |
| §6 **P-1 N10 收口** | **删**（过渡壳不留）· 硬条件 = 数值一字不变 | `e10` / `p1-n10` | 落链后补：「★ 2026-09-26 **P-1 已收**：`stats.py` 不再回落 `battle.title_bonus`、`Battle.__init__` 去掉该形参、`serialize.py` 存档不再写该键（旧档双向兼容实测）；内容侧 battle 级 `title_bonus=` 冗余传参同批删。」 |
| §6 **P-3/P-8 默认域三件** | `$builtin` **保持层作用域语义**（不做语义改造）；默认域三件 **不做引擎自带空模板**（= silent fallback）⇒ **文档 + 向导** | `e11` / `p8-builtin` | 落链后补：「★ 2026-09-26 **P-8 已收**：`$builtin:false` 语义不动（害处=静默，已由 `0473aec` 的装载告警解决）；三条引擎默认域（commands/texts/tlogs）由**包自建**（空表即合法）、向导生成，引擎不代填。」 |
| 台账 §3 **P-46 残余（改名）** | **不改名**（三个名字是内容侧声明表自己的字段名；引擎 E3 后不再读） | 台账 P-46 条目尾补逐字：「★ 2026-09-26 裁：`pct_boss` / `boss_pct_mult` / `pct_cur_boss` **不改名** —— 引擎侧（E3 `d01c1e0`）已不再自己判 Boss，只按名读内容侧声明表的键；改名 = 跨层 + 触已配平数值面 + 冻结门禁重钉，收益仅名字，故留。」 |
| §6 **P-4 药水两处缺陷** | **只修缺陷、不接线**（两侧副本逐字一致） | `e12` / `p4-potion` | 抽包线待拍板 #4 尾补逐字：「★ 2026-09-26 P-4 缺陷已修（`random` 缺失 / `REACTION_TABLE` 未导入，两侧同名同对）；36 handler 的接线仍判停。」 |
| §6 **P-5 宿主门禁两红** | **本会话不碰**（他的门禁口径 + 宿主脏树） | — | 只登记 |
| §6 **P-2 / P-6 抽包判停项** | **不动** | — | 只登记 |

---

## P-1 「N10 收口」已落（2026-09-26 · 分支 `p1-n10`）

**动的是什么**：battle 级 `title_bonus` 这条过渡语义整体收掉 ——
`Battle.__init__` 形参 + `self.title_bonus` 字段 · `stats._player_base_stats` 的
`or getattr(battle, "title_bonus", None)` 半边回落 · `serialize.to_state` 写键 /
`from_state` 传参。面板增幅**唯一**容器 = per-actor `actor["bonus"]["panel"]`
（N5b4-4 拍板口径，本次只是把「两路都活」收成一路）。

**★ 数值不变性（实测，两引擎同 seed 逐字节对拍）**：6 个场景各跑 14 动，
`to_state()` **去掉被删的顶层 `title_bonus` 键后 sha 完全相同**：

| 场景 | 改前 sha(前16) | 改后 | 旧顶层 tb 值 |
|---|---|---|---|
| 野外普攻 | `dd80f6920b272f7f` | 同 | `{'hp': 30}` |
| 野外技能 | `7d69de318c7062c6` | 同 | `{'hp': 30}` |
| 世界Boss | `5126bc9f8c5e58bb` | 同 | `{'hp': 30}` |
| PVP | `56d0f24c0c71decb` | 同 | `{}` |
| 空 tb | `ff68abc8b175823f` | 同 | `{}` |
| 副本形态 | `0940af13035dd0a4` | 同 | `{}` |

逐动日志、逐 actor `actor_stats` 面板、`result` 全部逐字段相等。
探针：`_p1_n10_probe.py`（workspace）· 证据 JSON 在 `%LOCALAPPDATA%/Temp/p1n10/`。

**有牙反证**（证明删的是活代码、且该形状在奥兰迪亚不存在）：
唯一会分叉的形状 = 「actor 无 `bonus.panel` + battle 级非空」实测旧 21 / 新 16（`atk`）；
而奥兰迪亚**造不出**它 —— `monster_roster` 380 条 / `MONSTER_MODS` 140 条带
`class_name` **均为 0** ⇒ 敌侧从不进 `_player_base_stats`；两个非空站点
（`_open_battle` / `hunt_boss`）都把**同一份** tb 写进每个 player actor 的 `bonus.panel`。

**存档面**：旧档（带 `title_bonus` 键）→ 新引擎 `from_state` OK；新档（无键）→
新引擎 OK；二次往返 sha 稳定（`f3da9df94eff02bd`）。旧引擎读新档走它自己的
`st.get(...) or {}`（旧引擎未改）。

**门禁**：`tests/run_all.py` 95/95 · `check_wiki_refs` drift 0（remap 位移 147 +
`--fix-bare` 4 + 人工 6）· orlandia related 14/14 · consumers 86/86 ·
`_u1d2_triggers_gen.py --check` 自检通过 · 6 个 frozen 门禁 89/83/71/101/66/77 全绿。

**已知残余（报备，未动）**：`Battle.__init__` 的 `**kwargs` 仍在（`pet=` / `dmg_mult=`
等仍被它静默吞）——本批只收 `title_bonus` 这一条，`**kwargs` 的存废另案。

---

## P-1「N10 收口 3」已落（2026-09-26 · 分支 `p1-n10`）：`title_bonus` 全链改名 → `panel_bonus`

**为什么改**：N10 收口 1/2 删掉 battle 级容器与 `**kwargs` 后，剩下的是**同名不同物**：
`_title_bonus` 这个名指的东西早已不是「称号加成」而是**外部面板增幅**（称号+成就+收藏册，
v105→v174→N5b4-4 已把模块正名 `stat_bonus`）。本次把「值/键/钩子」四类名字全链收敛到一个名。

**映射（单一真源；token 级替换 + 逐行白名单，96 行落改）**

| 旧 | 新 | 语义 |
|---|---|---|
| `saintess_engine/host/shell.py::_title_bonus` | `_panel_bonus` | 外部面板增幅聚合口（真源 `content/stat_bonus.py`） |
| 包内 `self._title_bonus(gid,qid)`（30 处） | `self._panel_bonus(...)` | 同上 |
| `player["_title_bonus"]` | `player["_panel_bonus"]` | 运行期玩家 dict 字段（下划线 = 非 DB 列） |
| 副本 roster 快照 `"title_bonus"` | `"panel_bonus"` | 快照/载荷裸键（与 `class_name`/`hp` 同约定） |
| `hooks={"title_bonus": …}` / `ctx.hooks.get("title_bonus")` | `"panel_bonus"` | 事件模板钩子键 |
| `host.title_bonus` / `self.title_bonus`（gm 侧注入属性） | `panel_bonus` | `content/gm.py` |
| `panel_fn` 第 7 形参（`content/panel.py` / `examples/` / 文档 / 测试 kwarg） | `panel_bonus` | 引擎注入面形参名 |
| 局部变量 `title_bonus_names` | `titled_bonus_names` | 「带 bonus 的称号名集合」（语义本就如此） |

**不动的（历史/存档契约）**：`stat_bonus` 模块与函数名 · `serialize._deserialize_actor` 的
actor 级旧键迁移（`stat_bonus`/`title_bonus` → `bonus.panel`）· 冻结文本 `_FROZEN_TEXT` 里的
旧实现快照 · wiki/`_notes` 的历史叙述。

★ **顺带修掉一个 N10 收口 1 的漏网真缺陷**：`item_templates.py::_battle_cur_max` 原读
`st.get("title_bonus")` = 引擎旧 `to_state` 那份 **battle 级**副本；收口 1 删键后它静默读成
`{}` ⇒ **普通战斗的上限重算少了外部增幅**（物品「满血/满蓝」判定会误判）。
已改为读 actor 自己的容器 `ctx._focus["bonus"]["panel"]`（N5b4-4 唯一容器）。

**门禁**：引擎 `run_all` 96/96 · `ext_reward` 19/19 · wiki `drift 0` · orlandia related 14/14 ·
consumers 86/86（BASE/NEW 双边）· 8 个冻结门禁全绿（quest **72/72**、store、triggers 89/83、
wiring 77/66、dialogue、presence 101）· `_u1d2_quest_gen --check` 通过。
★ 数值不变性：6 场景 + 存档往返 sha **逐字节与改名前一模一样**。

**冻结门禁的「正规推进」（按仓库规矩，非放宽判据）**
`content/profession_quests.py::settle_daily_quest` 因本次改名由 **E → C**
（理由写在 `tests/_u1d2_quest_gen.py::CLASS` 注释里：行为逐字不变，只换键名；
13 064 格冻结网格实测无不一致），并跑 `--emit-live` 刷新 `_PIN["live"]`（只动 2 条 sha）。
`--check` 需要 base 副本：本次用 git 回溯重建
（`GWEN_U1D2_BASE_PKG=<临时目录，rev 1be39311，28 段里对上 27/28——与设计基线一致>`）。

★ **部署前置（不写迁移，出 PURGE）**：副本 roster 快照是**入库**的（`battle_state.state`
里的 `players.<qq_id>`），改名后「在飞的副本局」旧键读不到 ⇒ 部署时先清一次：

```sql
-- 只清「在飞的副本局」（副本 state 含 players 快照与 inst_id）；野外/PVP 局不受影响
DELETE FROM battle_state WHERE state LIKE '%"inst_id"%' AND state LIKE '%"title_bonus"%';
```

★ **部署顺序铁律**：本批引擎与包**必须同批上线**（包先、引擎后）——
「新包 + 旧引擎」照旧能跑（旧壳仍收旧名与 `**kwargs`），
「**新引擎 + 旧包**」会 `AttributeError: _title_bonus` / `TypeError: pet=` 当场炸。
