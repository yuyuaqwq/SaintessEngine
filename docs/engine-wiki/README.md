# saintess_engine —— 零游戏知识的通用 CTB 战斗引擎

> 纯 Python、零第三方依赖、零游戏名词的**声明驱动**回合制（CTB）战斗引擎。
> 引擎只提供**机制**（行动、落地、事件总线、效果容器、时间轴、存档）；**游戏内容**
> （技能数值、状态名词、职业资源、被动 proc）全部由使用方通过 `config` 注入。
> **换一套配置 = 新游戏，引擎代码零改动。**

本 wiki 是 **`saintess_engine` 框架自己的文档**，住在**框架独立仓 `framework-engine`** 的
`docs/engine-wiki/`。面向**第三方插件的战斗系统开发者**：想用一个已经跑通、
经过大量战斗回归的引擎骨架，而不是从零写伤害链与时间轴的人。

> **仓库归属（先读）**：本框架已从游戏仓物理分离为独立仓 **`framework-engine`**（可分发、零游戏知识）。
> 游戏仓 **`dragonfall`**（《奥兰迪亚》）以 **git submodule `framework/`**（固定 commit）引用本框架，
> 它是本框架的**参考实现 + 压力测试**，不是本框架的一部分。
> 下方未显式标注「游戏仓」的路径，均指**框架仓**。

- 引擎目录：`saintess_engine/`（**14** 个子包 + **2** 个顶层模块；共 **51** 个 `.py` / **9 205** 行）
  —— 数字由 `tests/test_editor_wiki.py` 逐项对照磁盘锁定，改模块结构必同步（否则门禁红）
- 路线图（待建形状 / 待搬骨架 / `log`·`tlog` 设计）：[reference/roadmap.md](reference/roadmap.md)
- 纯度门禁：`tests/test_engine_purity.py`（AST 静态断言：引擎零「引擎→内容」import 边）
- 参考实现（**游戏仓 `dragonfall` 侧**）：《奥兰迪亚》内容侧（`game/data/battle_rules.py` + `game/services/`）
  —— 本 wiki **不**把它当规范，只当「可粘贴的真实声明样例」的来源

---

## 30 秒：起一场战斗

下面这段在本仓库**实测跑通**（`hero` 打 `wolf` 一拳 → 34 点伤害；`auto_run` 直到倒下）。
第 ① 段是必需的最小装配集，缺任一项都不能产生伤害 —— 原因见
[concepts/config-injection.md](concepts/config-injection.md) 与
[reference/api.md](reference/api.md) 的「未装配行为」节。

```python
import saintess_engine
from saintess_engine import Battle, make_actor, config
from saintess_engine import formulas as F          # 引擎自带的纯数值公式模块

# ① 挂最小配置（引擎不内置任何数值/名词；这三样是"能打出伤害"的下界）
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

| 特性 | 一句话 | 入口 |
|---|---|---|
| **全同构 actor** | 玩家/怪/召唤物/变身是同一个 dict 模型，无身份分派 | `make_actor`（`actors.py:58`） |
| **单 effects 容器** | 增益/减益/DOT/控制/标记/资源全部是 `actor.effects[key]` 一个容器 | `effects.py` 的 `act_apply` |
| **事件总线** | 26 个引擎事件名（`EVENTS`）+ `fire()`；效果声明挂 `actor.triggers` | `effect_triggers.py:52/57` |
| **声明表驱动** | 效果行为查 `EFFECT_RULES`；名词→动词查 `EFFECT_ACTIONS` | `game/data/battle_rules.py`（游戏仓侧） |
| **动词注册制** | 8 个引擎动词 + `register_action` 任意扩展（内容侧已扩到 70+） | `effects.py:95` |
| **CTB 绝对时刻制** | `ct` = 下次可行动时刻；耗时 = 基准 × `sqrt(50/spd)` | `schedule.py:28` |
| **零默认值** | 未声明即无行为（`strict=False` 静默 / `strict=True` 抛错两档） | `config.py:71` |
| **存档/续战** | sides-only JSON，`to_state` / `from_state`，旧档字段迁移 | `serialize.py:36/59` |
| **注入式边界** | 引擎不 import 游戏；游戏把公式/面板/技能表 mount 进来 | `config.py:129` |

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
| **指南** | [guides/write-a-mechanic.md](guides/write-a-mechanic.md) | 写一个机制动作（注册/参数/judge/装配钩子） |
| | [guides/add-a-resource.md](guides/add-a-resource.md) | 加一个职业资源（cap / channels / `when` / `per_dt`） |
| | [guides/add-a-passive.md](guides/add-a-passive.md) | 加一个被动 proc（声明 + 事件选型 + 测试） |
| | [guides/add-an-affix.md](guides/add-an-affix.md) | 加词条 / 装备特效 |
| | [guides/serialize-and-resume.md](guides/serialize-and-resume.md) | 存档与续战、旧档迁移约束 |
| | [guides/testing.md](guides/testing.md) | 给自己的内容写断言 |
| **参考** | [reference/api.md](reference/api.md) | 公开 API 逐项（`Battle` 方法 + 各模块函数） |
| | [reference/events.md](reference/events.md) | 26 事件全集：时机 / ctx 字段 / 是否引擎自然点位 |
| | [reference/effect-rules.md](reference/effect-rules.md) | `EFFECT_RULES` 字段 schema |
| | [reference/effect-actions.md](reference/effect-actions.md) | `EFFECT_ACTIONS` 名词→动词映射格式 |
| | [reference/mech-cash.md](reference/mech-cash.md) | `MECH_CASH` 机制兑现声明（mode / key / per_layer / clear） |
| | [reference/passive-proc.md](reference/passive-proc.md) | `PASSIVE_PROC` 声明（event / action / judge / agg / also） |
| | [reference/judges.md](reference/judges.md) | judge 谓词清单（按动作分域） |
| | [reference/channels.md](reference/channels.md) | 渠道时机表 + 两形态 + `when` / `per_dt` |
| **架构** | [architecture/README.md](architecture/README.md) | 模块依赖图 + 一次战斗的模块协作 |
| | [architecture/data-flow.md](architecture/data-flow.md) | 从 `human_act` 到落地的完整调用链 |
| | [architecture/design-decisions.md](architecture/design-decisions.md) | ADR：为什么 actor 同构 / 单容器 / 声明表 / 零默认值 |
| | [architecture/boundaries.md](architecture/boundaries.md) | 引擎与内容的物理边界 |
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
  引擎不认识它们。它们进 wiki 是因为规格要求，且它们是「第三方照抄一份声明就能接机制」的
  最省力样板；两页开头都显式标注了这个边界。

---

## 缺口速览（详表见 [_selfcheck.md](_selfcheck.md)）

写文档时按代码取证发现的、**当前引擎里没有消费方**的东西。看到它们不要以为是笔误：

- `phase` / `player_low` / `pv_broken` 三个事件在 `EVENTS` 里，但**引擎没有任何 fire 点位**（由上层驱动）。
- `effects["reduce"]` 由 `stats.py` 写入面板，但**伤害路径不消费**它。
- 技能级 `accuracy`（`game/data/skills.py:1466,2284` 两处）与技能级 `crit` 字段**无引擎消费方**。
- `game/data/skills.py` 里有 **20 个** `effect=` 名词既不在 `EFFECT_ACTIONS` 也不是引擎动词 → **静默 no-op**。
- ~~`Battle.dmg_mult` / `Battle.pet` / `Battle._cast_ctx` / `Battle._target_ctx` / `Battle._events` /
  `Battle.__init__(st=…)` / `schedule.HOT_INTERVAL` / `schedule.CAST_ITEM` / `Battle.DEFAULT_CT_WAIT`~~
  —— **2026-09-11 已全部删除**。⚠️ 但 `dmg_mult` / `pet` 不是死字段：它们是
  **「调用方在写、引擎没读」的静默失效功能**（世界 Boss GM 伤害倍率 / 宠物参战），
  处置见 [_selfcheck.md §0.4](_selfcheck.md)。
