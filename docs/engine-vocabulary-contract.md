# 引擎固定词汇表契约（engine vocabulary contract）

> 2026-09-11 定案。本文回答 wiki 自检 §4「边界瑕疵（引擎里的内容知识）」的 6 条 ——
> **哪些是"引擎领域模型的固定词汇"（= 契约，第三方照用），哪些是"待注入"（= v0.2 backlog）**。
>
> 背景：门禁 `tests/test_engine_purity.py` 只验证 **import 方向**（引擎不 import 游戏数据），
> 拦不住"语义残留"——比如引擎里出现中文枚举值、写死的效果键名。
> 那份清单曾是「待确认」，本次逐条取证后**定案**。

---

## 一、判断标准

引擎**允许**认识自己的领域概念（伤害通道、阵营、控制、濒死……）；**不允许**认识某个游戏的内容名词
（"破绽"/"磐核"/"旋律"/职业名）。

两者长得很像，区别在于：

| | 引擎领域概念 | 游戏内容名词 |
|---|---|---|
| 例子 | `phys`/`magi`、`sides["player"]`、`role == "boss"`、`sleep` 打醒 | `shaken`/`guard_core`/`melody`/`cls_wu_seng` |
| 引擎怎么处理 | 可以定义枚举/常量、可以比较 | **只能转发**：从 config 查表，或原样回传给内容侧动作 |
| 第三方换游戏 | 沿用（或用注入覆盖，见 §三） | 完全不需要知道 |

以下 6 条**全部落在左列**（引擎领域概念），因此定案为**公开契约**，而非"内容知识残留"。
真正的右列内容知识在 2026-09-11 清理中已清零（`gauge.charge_*` 是最后一个：它是《云海猎团》
弓手/时咒的职业机制，已删除）。

---

## 二、契约条目（逐条取证）

| # | 位置 | 内容 | 为什么是领域概念 | 契约说明 |
|---|---|---|---|---|
| **B1** | `kinds/__init__.py:27-34` | `SkillKind` 枚举值写死中文（`PHYS = "物理"` …） | 伤害通道枚举是引擎的**领域模型**。引擎内部**从不裸比较中文**（全仓无第二个裸字面量，已 grep 确认）——一律经 `SkillKind` / `kind_is()` / `kind_meta()` | 枚举**取值**沿用参考实现的写法；第三方数据用别的通道名 → 见 §三 injectable |
| **B2** | `landing.py:117,237,246,251,373-396` | 固定键：`sleep`（受击打醒）、`death_guard`（濒死保护）、`heal_amp_pct` / `heal_down` / `_anti_heal_pct`（受疗修正） | 这 5 个是**战斗物理规则里的固定语义位**（打醒/濒死/禁疗），与"护盾先挡"同级；`state_def()` 本来就查 config 表取参数 | 契约词汇。文档在 `reference/effect-rules.md` 登记；`sleep`/`death_guard` 改 config 查表 → §三 |
| **B3** | `effects.py:369` | `if key == "reduce":` | 特殊处理"减伤"这一**通道**（区别于普通叠层面板） | 契约词汇（同名 key 在内容侧 `EFFECT_ACTIONS` 也走 reduce 通道） |
| **B4** | `effects.py:305`、`schedule.py:268,272` | `is_boss` / `role == "boss"`（控制减半 / DOT `pct_boss`） | "Boss" 是**通用战斗角色概念**（与 `player` 同级）；值是内容侧数据标签 | 契约词汇。第三方用别的标签 → §三 |
| **B5** | `battle.py:170,515` | `sides["player"]` | 引擎需要**一个默认焦点侧**来找命令层焦点 actor（`human_controlled`） | 契约词汇：约定焦点侧名 = `"player"`。多焦点/改名 → §三 `focus_side` |
| **B6** | `effects.py:249-253` | `_is_stack_resource` 判据关键词含**无消费方**字段（`debuff_scale` / `dot` / `on_threshold` / `guard_hp_pct`） | 这是"死字段但**活判据**"：字段**存在与否会改变分派结果**（有 `debuff_scale` → 走 `apply op=add` 叠层；没有 → 走 `EFFECT_ACTIONS` 名词翻译） | ⚠️ **清理时必须同时考虑分派影响**——内容侧清理这些死字段前，先跑叠层分派回归 |

### 二·补：2026-09-11 新增的契约字段

| # | 字段 | 位置 | 语义 | 谁写 / 谁读 |
|---|---|---|---|---|
| **B7** | `actor["cc_immune"]` | `effects.act_apply` 控制分支 | **免疫控制**：控制类效果（`mode != None`）落地前，持有者带未过期的该态 → 本次控制不施加（不消耗、不叠层） | 内容侧写（带刻数，引擎按 `expire` 自动清理）；引擎读 |
| **B8** | `actor["guard_uid"]` | `landing.deal_damage` 最前 | **挡刀**：承伤转移——该字段指向保护者 uid，伤害改由保护者承受（递归深度 1）。是否真的转移由 `battle.redirect_hook(battle, victim, guard, amount, dmg_kind)` 决定（未设 hook = 默认转移） | 内容侧写（`team_guard`，到期清）；引擎读 |
| **B9** | `actor["heal_share_uid"]` | `landing.heal_actor` 最前 | **治疗分担**（faith_share）：治疗改由该 uid 承受；`battle.heal_redirect_hook` 决定是否转移 | 内容侧写；引擎读 |

> B7-B9 都是「引擎只读**字段名** + 调**内容侧回调**」的形态：引擎不认识「哪个技能给的免疫/谁在挡刀」，
> 只做通用的落地决策。与既有的 `target_picker` / `on_event` / `script_hook` / `redirect_hook`
> 一起构成引擎的**决策注入面**。
>
> ⚠️ 配套的真 bug 修复（同批）：`landing` / `actions` 里 3 处 `float(...get("mult", 1.0) or 1.0)`
> —— `0.0` 是 falsy，被 `or 1.0` 吞成 1.0 → **0 乘区永远失效**（格挡/无敌帧类效果做不出来）。
> 已改为「仅 `None` 回落 1.0」。

---

## 三、v0.2 backlog（可注入化 —— 不阻塞 v0.1 分发）

契约条目都可以"先用着"，但要让**第三方游戏用自己的一套词汇**，需要注入点。
按性价比排序（都属框架 v0.2，不进 v0.1）：

| 优先 | 项 | 设计草稿 | 成本 |
|---|---|---|---|
| 1 | `focus_side` | `Battle(focus_side="player")` 构造参数 + 默认 `"player"`；`_focus_actor` 读它 | S（~5 行） |
| 2 | `kind_labels` | `config.mount(kind_labels={"PHYS": "物理", ...})`；`kinds` 在 import 时读，缺省 = 现值（零行为变化） | M（enum 需动态构造，注意 `SkillKind` 的 property） |
| 3 | `boss_roles` | `config.mount(boss_roles=("boss",))`；B4 的两处比较改查表 | S（~6 行） |
| 4 | `builtin_keys` | `sleep`/`death_guard`/`heal_amp_pct`/`heal_down`/`_anti_heal_pct` 经 `config.key(name)` 解析，缺省 = 现值 | M（5 处替换 + 保底） |

> 定这个顺序的理由：`focus_side` 是纯改名，零语义风险；`builtin_keys` 涉及落地主链
> （打醒/濒死/禁疗），改动风险最高，放最后。

---

## 四、给第三方框架使用者的说明

写 v0.1 插件时按本契约做即可，**不需要等 v0.2**：

- 数据里的伤害类型用 `物理/魔法/治疗/增益/被动/召唤/真伤/嘲讽`（或经 `kind_meta()` 查表）；
- 焦点方阵营命名为 `player`；
- Boss 角色在 actor 上标 `is_boss: true` 或 `role: "boss"`；
- 用 `sleep` / `death_guard` / `heal_amp_pct` / `heal_down` 表达打醒 / 濒死保护 / 受疗修正；
- 叠层资源要在 `EFFECT_RULES` 里带 `stat_scale` / `period` / `debuff_scale` 之一（见 B6，它决定分派路径）。
