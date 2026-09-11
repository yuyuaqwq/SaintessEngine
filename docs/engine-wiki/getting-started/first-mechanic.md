# 手把手：写你的第一条机制

「机制」= **引擎不认识的一个游戏名词**，被翻译成引擎认识的动词，或挂到引擎事件上执行。
本页做一个最小但完整的机制：**血契 —— 每次普攻命中后，攻击者回复 5% 最大生命**。

下面三段代码在本仓库（框架仓，`import saintess_engine`）**当场跑通**（实测日志见文末）。它演示了加机制的完整三段式：

```
① 写动词（能力）        ② 写名词声明（翻译）        ③ 装配到 actor（触发条件）
register_action       config.set_config           actor["triggers"]
```

## ① 写动词：`register_action`

动词签名**固定**为 `fn(battle, caster, target, params, logs)` —— 与引擎自带的
8 个动词（`apply` / `consume` / `shield` / `cleanse` / `cleanse_all` / `heal` /
`interrupt` / `damage`，注册于 `effects.py`）完全同构。注意：

- `battle` 是战斗实例；`logs` 是 list，直接 `append` 就是玩家看到的日志
- **不要自己扣血/加血** —— 落地必须走 `landing.heal_actor` / `landing.deal_damage`
  （`landing.py:390` / `:23`）。绕过落地会丢掉护盾、死亡判定、濒死保护、`on_heal` 事件
- 抛异常会被 `apply_effects` 吞掉并跳过该动作（`effects.py:172-176`），不会中断战斗

```python
from saintess_engine import register_action

@register_action("pact_heal")
def pact_heal(battle, caster, target, params, logs):
    from saintess_engine.landing import heal_actor
    holder = target if params.get("on") == "target" else caster
    pct = float(params.get("pct") or 0)
    if holder is None or pct <= 0:
        return                       # 零默认值：没给 pct 就是无行为
    amount = int((holder.get("max_hp") or 1) * pct)
    real = heal_actor(battle, holder, amount, logs)
    if real > 0:
        logs.append(f"🩸 血契：{holder.get('name')} 回复 {real} 点生命")
```

`register_action`（`effects.py:95`）就是个装饰器，往 `ACTION_HANDLERS`（`effects.py:87`）
里塞一条。`EFFECT_HANDLERS` 是同一张表的旧别名（`effects.py:89`）。

## ② 写名词声明：同名名词 → 动词序列

游戏数据/技能表里写的是**名词**（`"blood_pact"`），引擎靠 `EFFECT_ACTIONS`
把它翻译成**动词动作列表**。用 `config.set_config("effect_actions", {...})` 挂表
（`config.py:82`）。

```python
from saintess_engine import config

config.set_config("effect_actions", {
    **config.get_effect_actions(),                       # 保留已挂的（合并而非覆盖）
    "blood_pact": [{"action": "pact_heal", "pct": 0.05, "on": "caster"}],
})
```

翻译规则（`effects.resolve_actions`，`effects.py:107`）：

| 表里写什么 | 引擎怎么处理 |
|---|---|
| `"名词": [{"action": "动词", ...参数}]` | 逐个执行；`action` 之外的键是**映射默认参数** |
| `"名词": {"action": "动词", ...}` | 等价于单元素列表 |
| 表里没有该名词，但名字本身是已注册动词 | 按动词直通执行 `{"action": <名词>}` |
| 表里没有、也不是动词 | **静默跳过**（`effects.py:163-164` `continue`） ← 最常见的「我的效果没生效」原因 |

参数合并语义（`_merge_params`，`effects.py:125`）：**调用方显式给的参数优先**，
映射默认只在该参数缺失/为 None 时补位。所以同一名词被不同技能引用时，
技能数据可以覆盖 `pct`。

## ③ 装配到 actor：`triggers` 是触发条件的家

动词与名词都只是「能做什么」。**什么时候做**写在 `actor["triggers"]`：

```python
def equip_blood_pact(actor):
    actor.setdefault("triggers", {}).setdefault("attack_hit", []).append(
        {"type": "blood_pact"})
```

`triggers` 结构 = `{事件名: [效果 dict, ...]}`（`actors.py:120-123` 注释）。
引擎在固定点位 `fire(事件名, ctx, logs)`，总线遍历所有存活 actor 找 `triggers[事件名]`，
逐个交给 `apply_effects` 翻译执行（`effect_triggers.fire`，`effect_triggers.py:61`）。

`attack_hit` 的触发点在 `_single_target_pipeline` 尾部（`actions.py:459`）：
**普攻命中且伤害管线跑完之后**，`ctx = {"actor": 攻击者, "target": 挨打者, "info": 技能, "dmg": 总伤}`。

## 跑起来

```python
hero = make_actor("p1", "英雄", "player", kind="player", human_controlled=True,
                  hp=60, max_hp=100, atk=30, spd=60, level=10)
wolf = make_actor("e1", "野狼", "enemy", kind="monster",
                  hp=80, max_hp=80, atk=20, spd=40, level=8)
equip_blood_pact(hero)                       # ← 只给 hero 装

b = Battle(btype="monster", sides={"player": [hero], "enemy": [wolf]})
logs, ended, who = b.human_act("attack", None)
print("\n".join(logs))
```

实测输出：

```
💥 野狼 受到 29 点伤害！
🩸 血契：英雄 回复 5 点生命
hero hp: 65
```

`hp` 从 60 → 65，正好是 `max_hp(100) × 0.05 = 5`。

## 两个反例（都要知道）

实测同一套代码的两个变体：

| 变体 | 结果 |
|---|---|
| 只给 hero 装 `{"type": "no_such_name"}`（名词没在表里） | 日志只有伤害、hp 不变、**无异常** —— 静默 no-op |
| 名词声明为 `[{"action": "pact_heal"}]`（没给 `pct`） | 同样无行为 —— 动词里 `pct <= 0` 直接 `return`（零默认值） |

**结论**：引擎的容错策略是「宁可静默不做，也不抛异常打断战斗」。
代价是你必须自己写断言（见 [../guides/testing.md](../guides/testing.md)）。

## 名词也可以直接挂在技能数据上

上面走的是「事件触发」路子。另一条路是**技能数据驱动**：技能 dict 里的 `mech`
字段经 `effects_from_skill`（`effects.py:188`）转成 effect 列表，在命中后由
`_apply_hit_effects`（`actions.py:515`）执行。分派判据见 `_mech_to_effect`
（`effects.py:207`）——「叠层资源型」走 `apply op=add`，否则保留名词走 `EFFECT_ACTIONS`。

更完整的机制写法（judge 谓词 / 乘区钩子 / 计数器）见
[../guides/write-a-mechanic.md](../guides/write-a-mechanic.md)。

## 下一步

- 事件全集与 ctx 字段 → [../reference/events.md](../reference/events.md)
- 效果容器的条目形态 → [../concepts/effects.md](../concepts/effects.md)
- 事件总线的执行语义（subject 过滤 / `_owner`） → [../concepts/event-bus.md](../concepts/event-bus.md)
