# 设计决策记录（ADR 风格）

每条格式：**决策 → 背景 → 选择 → 代价 → 在哪能看到这个决策的痕迹**。
理由是「后来的人读到某段代码觉得奇怪」时最需要的部分。

---

## ADR-1：actor 全同构，不为玩家/怪/Boss 写分支

**背景**：旧引擎为玩家和怪各写一套面板/技能/行动路径（`_player_stats` vs `_enemy_stats`、
玩家技能路径 vs `_actor_skill`）。同一机制要写两遍，且经常只改了一边。

**选择**：actor 是一个 dict，字段全集一致；`kind` / `side` / `class_name` 只是数据标签，
引擎**不按字段猜身份**。「谁需要真人输入」由 `human_controlled` 一个 bool 决定。

**代价**：
- 想表达「Boss 特例」时不能加类型分支，只能读数据字段（`is_boss` / `role`）
- 面板公式必须对「无 `class_name`」的 actor 也有答案（`stats._monster_base_stats`）
- 调试时无法从类型看出「这是谁」，得看 `name` / `kind`

**痕迹**：
- `actors.py:1-9` 的模块 docstring 原文：「引擎逻辑只用字段值，不按字段猜身份」
- `Battle.focus()`：只认 `human_controlled`（`battle.py:181-190`）
- `schedule._next_player_due` / `_next_auto_due`：按同一个 bool 分流（`schedule.py:109/128`）
- `Battle.add_actor` 注释：「不认识随从/召唤/亡灵/援军，只做注册 + 索引 + 排程」（`battle.py:217`）

---

## ADR-2：单一 `effects` 容器（原四容器合并）

**背景**：曾有 `state` / `buffs` / `hot` / `debuffs` 四个容器。每加一种效果都要回答
「它算哪一类」，而且到期、净化、面板折算、序列化都要写四遍。

**选择**：合并成一个 `actor["effects"]`。**行为由 `EFFECT_RULES[key]` 声明决定，
不由容器决定。** 条目就是 `{stacks, expire, ...}`。

**代价**：
- 想「只清减益」时必须查声明（`cleanse` / `period` / `on == "target"` 三判据）
- 想「只对增益做某事」时必须查 `negative` 标记（而 `negative` 引擎不读，
  是内容侧约定 —— 见 [../reference/effect-rules.md](../reference/effect-rules.md)）
- 面板折算要遍历全部条目（`stats._apply_effects`）

**但保留了 2 个独立容器**：`shields`（承伤资源）与 `cooldown`（调度表）。理由见
`actors.py:112-115` 注释：它们不是「状态」，混进去会让净化清掉盾、让面板折算把盾当减伤。

**痕迹**：`actors.py:46-48` 的「V 系列统一：四容器 → 单 effects 容器」注释；
`_MUTABLE_KEYS`（`actors.py:49-55`）里四个键变三个。

---

## ADR-3：声明表而不是代码（`EFFECT_ACTIONS` / `EFFECT_RULES`）

**背景**：`if effect == "shield_self": ... elif effect == "taunt": ...` 式硬编码：
加效果 = 改引擎，改数值 = 改引擎，测试面随机制数线性膨胀。

**选择**：引擎只留**动词**（能力），名词→动词的翻译在表里（`EFFECT_ACTIONS`）；
行为规则（上限/折算/周期/净化/控制模式）在另一张表里（`EFFECT_RULES`）。
引擎不认识任何游戏名词。

**代价**：
- 写错 key = **静默 no-op**（没有任何提示）。这是真实的税：
  参考实现（游戏仓 / 奥兰迪亚侧）现有 20 个 `effect=` 名词没有映射（[_selfcheck.md](../_selfcheck.md)）
- 表的字段可能有「声明了但无人读」的死字段（`on_threshold` / `debuff_scale` / …）
- 表与动作之间是**约定耦合**：动作必须认识声明里的 `judge.kind`

**痕迹**：
- `effects.py:4-8` 原文：「引擎只提供【动词执行器】——能力，不含任何游戏内容判断」
- `config.py:8-9`：「换一套配置 = 换挂载的表 = 新游戏（引擎代码零改动）」
- `effect_triggers.py:11-12`：「事件名是引擎协议，效果内容是游戏名词」

---

## ADR-4：零默认值（没声明 = 没行为）

**背景**：兜底默认值（「没有配置就按每级 +10%」）会让**写错的配置看起来正常工作**。
引擎里有一处历史教训被写进注释：`formulas.skill_power_mult` 删掉了「默认每级 +10%」，
原因是「曾误伤无 SKILL_UP 配置的怪物技能：按折算等级白吃成长 ×1.4」
（`formulas.py:129-132`）。

**选择**：缺字段 = 不做事。所有扩展动作都是 `params.get(...)` + 判 `<= 0` 就 `return`。
`config.strict=True` 时未装配的 hook 直接抛 `EngineNotConfigured`。

**代价**：
- 报错少、调试难：症状是「没反应」而不是「抛异常」
- 必须自己写测试（[../guides/testing.md](../guides/testing.md)）
- 唯一的例外要记住：`stats._monster_base_stats` 的 `crit` 兜底 **0.05**
  （`stats.py:122`），而 `make_actor` 播种的是 0.0（`actors.py:98`）

**痕迹**：
- `config.py:66-70` 的 R8 说明：「静默降级」两档语义
- `formulas.py:72` 原文：「『零默认值』：无挂载 → 空 dict = 无成长配置」
- 内容侧 `_merge_agg_entry` 的注释：「缺字段 = 无此行为（零默认值铁律）」

---

## ADR-5：伤害/治疗统一落地收口（`landing`）

**背景**：如果每个机制自己扣血，就会出现「某技能绕过护盾直接扣血」这类 bug
（旧引擎真实存在）。

**选择**：一切来源（普攻/技能/效果 handler/DOT/反伤/职业模块）都调
`landing.deal_damage` / `landing.heal_actor`。落地链内部固化顺序：
等级压制 → 元素 → `taken_calc` 乘区 → 承伤倍率 → 闪避 → 防御 → 类型免伤/格挡 →
醒睡/打断 → 护盾 → 扣血 → 濒死保护 → 死亡/击杀事件。

**代价**：想加「在护盾之前生效的减伤」这类需求时不能改调用方，只能加事件钩子
（`taken_calc` 的 `mult`）。

**痕迹**：`landing.py:8-13` 原文（「为什么必须统一收口」）；
`effects.act_damage` 也只做「读参数 → 调 `landing.deal_damage`」（`effects.py:570-597`）。

---

## ADR-6：事件总线 + `triggers` 声明（而不是 if 分支）

**背景**：加「暴击回蓝」要改 `actions.py`，加「死亡爆炸」要改 `landing.py`。
机制数增长 = 引擎里散落的 if 数增长，且每加一处都要全量回归。

**选择**：引擎在语义正确的时刻 `fire(事件名, ctx, logs)`（26 个封闭事件名）；
actor 的 `triggers = {事件名: [效果声明]}` 决定响应什么。

**代价**：
- **ctx 约定要背**：谁是 `actor`（主体）、谁是 `target`、谁是 `caster`、谁在 `source`
- subject 过滤是「只处理主体 actor 自己的声明」——广播型效果的语义要自己造
  （`act_done` 故意不带 `actor`，效果侧自判敌我）
- `_fire_ctx` 单槽覆盖，嵌套 fire 要 save/restore（[../concepts/event-bus.md](../concepts/event-bus.md)）
- 3 个事件（`phase` / `player_low` / `pv_broken`）声明了但无引擎点位

**痕迹**：`effect_triggers.py:5-11` 原文；`fire()` 的 4 条语义（白名单/subject/`_owner`/`_fire_ctx`）。

---

## ADR-7：绝对时刻制（而不是 tick 循环）

**背景**：「每 tick 给所有人加速度，满 100 行动」需要主循环；跨多刻的结算说不清。

**选择**：`actor["ct"]` = 下次可行动的**绝对时刻**；`battle._now` 是全局时钟；
`_advance_time(dt)` 一次推进并结算期间一切（到期 / 周期 / 广播）。

**代价**：
- **命令层必须负责推进**（`advance()`）。`human_act` 不校验 ct，
  连点就是无限行动权（[../concepts/ctb-schedule.md](../concepts/ctb-schedule.md)）
- 「1 刻 = 1 秒」是隐含约定，没有单位类型来保证

**痕迹**：`schedule.py:4-11` 原文；`_advance_time` 的三步顺序（时钟 → 结算 → 广播）。

---

## ADR-8：注入面（`config`）而不是反向 import

**背景**：引擎曾有 15 条「引擎 → 内容」import 边（4 个文件：`actions`/`battle`/`stats`/`config`），
量化记录见游戏仓内部文档 `docs/ENGINE_CONTENT_SPLIT_PLAN.md` §3.2（含 R1–R15 逐条）。

**选择**：方向反过来 —— 内容侧把公式 / 面板 / 技能查询 / kind 常量 mount 进引擎
（13 个 hook）；引擎只调接口，不认识表内容。机器门禁：`tests/test_engine_purity.py`
（AST 断言「绝对 import 全是标准库」+ 零动态 import 穿透）。

**代价**：
- 装配不全时的错误**离现场很远**（`TypeError: float() ... NoneType` 从伤害链深处抛）
- `config` 是全局单例 → **一个进程只能装一套配置**，无法同时跑两套内容
  （`load_game_defaults` 是全局的）。游戏仓（奥兰迪亚）因此并存 `game.*` 与
  `data.plugins.dragonfall.game.*` **两套模块树**（同一份文件的两个模块对象），
  每棵树各自 hold 自己的 `config` 实例 —— 这也是 `config` 需要
  `register_hook_provider` 惰性装配的原因（游戏仓 `game/bootstrap.py:196-201`、
  引擎 `config.py:73-78`）。要做真正的多内容隔离，靠进程或模块树，不要靠全局单例
- 惰性装配器会在首次读 hook 时把整份内容拉进来（[../getting-started/installation.md](../getting-started/installation.md)）

**痕迹**：`config.py:11-15` 原文（「本包历史上直接 import `game.engine` / `game.content` /
`game.data`（15 条反向边）。现全部改走本模块的注入面」）。

---

## ADR-9：sides 是唯一的容器（没有 BattleUnit 类、没有 Team 类）

**背景**：战斗需要「谁和谁是一队」「谁还活着」「谁先动」三件事。

**选择**：`sides = {阵营名: [actor, ...]}` 是个**普通 dict**，没有封装类。
调度、序列化、事件广播都在运行期直接遍历它。

**代价**：
- 没有不变量保护：允许你手工把同一个人塞进两个阵营、塞进同一个 list 两次
- 「谁属于哪个阵营」有两处真相（`actor["side"]` 与 `battle.sides` 的键），
  于是需要 `actor_side_of`（`actors.py:178`）来定权威（sides 优先，字段兜底）

**收益**：`add_actor` 不需要通知任何人（`battle.py:217-219` 注释：
「sides 是普通 dict，调度与序列化均动态遍历 sides，故新 actor 自动参与行动与存档」）。

**痕迹**：`Battle.__init__` 里 `self.sides` 的构造（`battle.py:60-63`）。

---

## ADR-10：`Battle` 用注入钩子而不是子类继承

**背景**：命令层需要「打谁」的策略（仇恨/嘲讽）、事件观察、自定义行动（道具）、
Boss 剧本导演。这些都需要游戏知识。

**选择**：不做 `class MyBattle(Battle)` 继承，而是构造时注入 4 个 callable：
`target_picker` / `on_event` / `action_override` / `script_hook`。

**代价**：
- **它们不落盘**：`from_state` 只恢复 `btype/sides/title_bonus/hostile_map`，
  恢复后必须自己重挂（[../guides/serialize-and-resume.md](../guides/serialize-and-resume.md)）
- 异常被吞掉（`script_hook` 异常 → 回落默认行动，`battle.py:303-304`），
  钩子写错不容易发现

**痕迹**：`battle.py:40-52` 的三段注释；
`actor_auto` 里的调用顺序（script_hook → auto_act → ai → 普攻）。

---

## 决策的代价总结（做技术选型前先看这张）

| 决策 | 直接代价 | 你现在必须做的事 |
|---|---|---|
| actor 同构 | 无类型分支 | 用数据字段表达差异；面板要对无职业 actor 有答案 |
| 单 effects 容器 | 「只清减益」要查表 | 用好 `cleanse` / `negative` / `period` 声明 |
| 声明表驱动 | 写错静默失效 | 写测试；定期核对「表里的键 vs 代码里的消费者」 |
| 零默认值 | 没反应 ≠ 报错 | 开发期 `strict=True` + 逐 hook 断言 |
| 落地收口 | 自定义结算受限于既有顺序 | 用 `taken_calc` / `dmg_calc` 乘区而不是改链路 |
| 事件总线 | 要背 ctx 约定 | 读 [../reference/events.md](../reference/events.md) 的字段表 |
| 绝对时刻制 | 命令层要自己推时钟 | 用 `advance()` 的返回值决定谁能动 |
| config 注入 | 全局单例 | 一个进程一套内容；测试用独立进程/模块树 |
| sides 普通 dict | 无不变量保护 | 别手工改 sides；用 `add_actor` |
| 钩子不落盘 | 续战要重挂 | 在恢复后手动赋 `target_picker` 等 |

## 相关

- 边界的物理形态（框架仓 / 游戏仓的分离现状） → [boundaries.md](boundaries.md)
- 数据流 → [data-flow.md](data-flow.md)
