# 手把手：起一场战斗

> **归属**：本页用的战斗能力（`Battle` / `make_actor` / `landing` …）**不在引擎里**（2026-09-23 起）—— 它在扩展包 `extends/ext_combat/`（`battle/`）。
> 数据包要用它：`game.json` 里写 `"depends": ["ext_combat"]`。
> 引擎侧只剩通用件（`config` / `text` / `expr` / `formula` …），见 `../architecture/boundaries.md`；下文裸文件名（`battle.py` / `actors.py` / `schedule.py` / `landing.py` / `serialize.py` / `effect_triggers.py`）与行号都在 `extends/ext_combat/battle/` 下。

本页所有代码块都在本仓库（框架仓 `framework-engine/`，引擎包是顶层 `saintess_engine/`）**当场跑过**。
目标：读完之后你能自己构造 sides、
驱动一次出手、读到日志，并知道每一步在引擎里的落点（带 `文件:行号` 与函数名）。

## 0. 准备：挂最小配置

引擎零游戏知识，所以第一件事是告诉它「数值怎么算」。最小可伤害装配集是 6 项
（第 ⑥ 项是 CTB 时间模型：**没有它连 `Battle(...)` 都构造不出来**，见 `_seed_ct_one`）：

```python
import math
import saintess_engine
from ext_combat import Battle, make_actor
from saintess_engine import config
from ext_combat.battle import formulas as F

config.mount(
    formulas=F,                                   # ① 数值公式对象（战斗包自带纯公式模块，extends/ext_combat/battle/formulas.py）
    kinds={"phys": "phys", "magi": "magi", "true": "true",
           "heal": "heal", "buff": "buff"},       # ② kind 语义值（引擎零 kind 字面量）
    basic_fallback={"name": "普攻", "kind": "phys", "exprs": ["atk*1.0"]},  # ③ 普攻兜底
    skill_flat_fn=lambda: {"SKILL_FLAT_BASE": 12, "SKILL_FLAT_PER_PLAYER_LV": 1,
                           "SKILL_FLAT_PER_SKILL_LV": 2},                   # ④ 基础值常量表
    formula_skeleton_fn=lambda: {"skill_growth": {                          # ⑤ 骨架参数表
        "power_per_lv_divisor": 100, "buff_turns_base": 3, "buff_turns_per_lv": 1,
        "cond_default": 0.05, "mech_default_div": 2,
        "lifesteal_default": 0.2, "lifesteal_per_lv_divisor": 100},
        "skill_learn_cost": {"divisor": 6, "base": 2}},
    # ⑥ CTB 时间模型：一次行动耗时（形状 + 参数由你定；引擎零公式，缺了直接抛错）
    time_model_fn=lambda spd, base: base * math.sqrt(50.0 / max(float(spd or 0), 1.0)),
    action_base_fn=lambda action: {"defend": 0.6, "skill": 1.6}.get(action, 1.0),
)
```

**为什么至少这几项**（框架仓实测，逐项摘除）：

| 装配集 | 结果 |
|---|---|
| 零装配 | `Battle(...)` 构造期抛 `EngineNotConfigured`（播种 ct 要 `time_model_fn`，**fail-closed**） |
| 仅 `formulas` | `TypeError: float() argument must be ... NoneType`（`skill_flat_value`） |
| + `basic_fallback` | 同上 |
| + `skill_flat_fn` | `KeyError: 'skill_growth'`（`skill_power_mult` 读骨架表） |
| + `formula_skeleton_fn` | 起得了战斗，但 `human_act` 返回 `[]`、目标 hp 不变 —— **静默 0 伤害**（R8 语义） |
| + `time_model_fn` / `action_base_fn` | ✅ `💥 野狼 受到 34 点伤害！` |

> ⚠️ **坑（建议改进）**：`config.mount(**hooks)`（`config.py:144`）只认 `_HOOKS`
> （`config.py:30-66`）名单里的 15 个名字，**未知名会被静默忽略**（`set_hook` 里
> `if name in _HOOKS` 没有 else 分支）。写错 hook 名不会报错，只是不生效。
> 开发期建议打开 `config.strict = True`（`config.py:92`）——未装配的 hook 会抛
> `EngineNotConfigured` 而不是让链深处抛 `TypeError`/`KeyError`。
> （`time_model_fn` / `action_base_fn` 是**唯一**两条不吃 `strict` 的：它们无论如何都抛。）

## 1. 造 actor

`make_actor(uid, name, side, kind=...)`（`actors.py:60`）返回一个**全同构 dict**：
玩家与怪除了字段值以外没有任何区别。

```python
hero = make_actor("p1", "英雄", "player", kind="player", human_controlled=True,
                  hp=60, max_hp=100, atk=30, spd=60, level=10)
wolf = make_actor("e1", "野狼", "enemy", kind="monster",
                  hp=80, max_hp=80, atk=20, spd=40, level=8)
```

要点：

- `kind` 只是**数据标签**（`"player"` / `"monster"` / 你自己的词），引擎不按它分支；
  真正决定「谁是人控」的是 `human_controlled`（`Battle.focus()` 只看它，`battle.py:218`）。
- 等级字段统一是 `level`；引擎不认 `lv`（`actors.py:81` 注释明写）。
- 额外关键字（`rank` / `reach` / `role` / `is_boss` / 你的自定义标签）会**原样透传**进 actor
  （`actors.py:139-145`）。`is_boss` / `role == "boss"` 是引擎真读的两个（控制时长减半、
  DOT `pct_boss` 档）——见 [reference/effect-rules.md](../reference/effect-rules.md)。
- 战斗可变状态已被播种：`effects` / `shields` / `cooldown` / `defending` / `charging` / `ct`
  （`_MUTABLE_KEYS`，`actors.py:51`）。

## 2. 起战斗：`sides` 是唯一入口

```python
b = Battle(btype="monster", sides={"player": [hero], "enemy": [wolf]})
```

`Battle.__init__`（`battle.py:33`）做的事，按顺序：

1. 把 `sides` 拷成 `self.sides`（dict，值是 list）—— `battle.py:75-78`
2. `hostile_map` 缺省 → 之后由 `hostile_sides()` 推「除自己外全部阵营」（`actors.py:195`）
3. 建技能索引 `actor["_skill_index"]`（`_index_skills` → `_index_one_actor`，`battle.py:187/117`）
4. **播种初始 ct**（`_seed_ct_one`，`battle.py:113`）：`ct = action_time(聚合 spd)`
   —— 快者先手、开局第一动也按速度排（`schedule.initial_ct`，`schedule.py:42`）

`sides` 的键名由你定；引擎唯一硬编码的约定是 **`"player"`** 这个键名
（`_check_side_end` 里 `alive[0] == "player"` → `result="victory"`，`battle.py:646`）。

## 3. 打一拳

```python
logs, ended, who = b.human_act("attack", None)
print("\n".join(logs))
```

实测输出：

```
💥 野狼 受到 34 点伤害！
```

`human_act`（`battle.py:271`）的返回是三元组：

| 位置 | 含义 |
|---|---|
| `logs` | 出手日志 + 推进期间自动 actor 的日志（list[str]） |
| `ended` | 战斗是否结束 |
| `who` | **下一个该决策的 actor**（多人调度用；`None` = 结束） |

`who` 是这套引擎对「多人同时在场」的答案：`human_act` 内部先 `act()`，
再 `_after_act` 推 caster 的 `ct`，然后 `advance()` 一路推进自动 actor，
直到撞上**下一个 ct 最小的人控 actor**（`schedule.advance`，`schedule.py:282`）。
单玩家场景 `who` 通常仍是自己。

内部调用链（详见 [../architecture/data-flow.md](../architecture/data-flow.md)）：

```
human_act → act(ctx) → do_attack → do_skill → _attack_damage_pipeline
          → _single_target_pipeline → _deal_hit → landing.deal_damage
          → _apply_damage（护盾 → 扣血 → 濒死保护 → 死亡/击杀事件）
```

## 4. 跑到结束

```python
b.auto_run([])                       # battle.py:333，全自动跑到 result != None
print(b.result, b.winner_side)       # victory / player
```

- `auto_run` 里人控 actor 也走普攻（`battle.py:343`），适合测试与仿真。
- 胜负判定在 `_check_side_end`（`battle.py:630`）：存活阵营数 ≤ 1 → 置 `result`；
  `alive[0] == "player"` → `"victory"`，否则 `"defeat"`；全灭 → `"defeat"`。
- `"fled"` 只由 `Battle._do_flee`（`battle.py:588`）写。

## 5. 读日志 / 读状态

引擎没有日志等级、没有事件回调表——**日志就是 list[str]**，由落地与动作层直接 append。
要拿结构化信息有两个正规通道：

| 通道 | 位置 | 用途 |
|---|---|---|
| `Battle.on_event` | 构造参数，`effect_triggers.fire` 尾部调用（`effect_triggers.py:116-121`） | 观察每个事件（记账 / 团队广播 / 存活同步） |
| `Battle.action_override` | 构造参数，`act()` 里非内置动作时调用（`battle.py:504`） | 接管 `use_item` 之类的自定义行动 |

`on_event(battle, event, ctx, logs)` 的签名与 ctx 字段见
[reference/events.md](../reference/events.md)。只读 ctx 或调引擎动词改状态，
**返回值不影响结算**；抛异常会被吞掉（`effect_triggers.py:116-117`）。

## 6. 存 / 取

```python
state = b.to_state()          # serialize.py:34 —— 纯 JSON 可序列化 dict
b2 = Battle.from_state(state) # serialize.py:57 —— 重建 sides/actors/时刻/胜负
```

注意 `from_state` 会 `seed_ct=False`（`serialize.py:73`）——**不重播初始 ct**，
且 `_started=True`（`serialize.py:80`）——**不重复 fire `battle_start`**。
这两条是续战正确性的关键，详见 [../guides/serialize-and-resume.md](../guides/serialize-and-resume.md)。

## 7. 加人（召唤 / 援军 / 变身）

```python
b.add_actor(make_actor("m1", "石像鬼", "enemy", hp=60, max_hp=60, atk=15, spd=30),
            side="enemy", front=True)
```

`add_actor(actor, side, front=False)`（`battle.py:244`）：入 sides → 建技能索引 →
播种 ct。`front=True` 插队首（存活序列第一名，默认 AI 目标先打它）。
因为 `sides` 是普通 dict 且调度/序列化都动态遍历它，**新 actor 自动参与行动与存档**。

## 下一步

- 加自己的第一条机制 → [first-mechanic.md](first-mechanic.md)
- 每一页 API 的签名 → [../reference/api.md](../reference/api.md)
- 事件能挂在哪 → [../reference/events.md](../reference/events.md)
