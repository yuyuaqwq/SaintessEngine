# ext_combat —— 回合制战斗（扩展包）

游戏级**能力**包：把「一场 CTB 回合制战斗怎么算」整个装进来。任何数据包 `depends` 它就能打，
不 depends 就是一个**跑得起来的非战斗框架**（纯经营 / 纯冒险 / 纯解谜都能用）。

## 装它

```python
from saintess_engine.package import load_stack
stack = load_stack("path/to/game", exts=["path/to/extends"])   # 数据包 depends: ["ext_combat"]
```

宿主想开战：`Host.run_battle(...)` 会按 `provides.battle` 取到战斗类（本包在 `game.json` 里声明）。

## 用它

```python
from ext_combat import Battle, make_actor, deal_damage, register_action, actor_stats
# 或按子模块：from ext_combat.battle.effects import register_action
```

## 内容

| 子包 | 提供 |
|---|---|
| `battle/` | CTB 调度（`schedule`）· 行动结算（`actions`）· 效果叠层与动词注册表（`effects`）· 落地（`landing`）· 面板聚合（`stats`）· 纯公式（`formulas`）· 通用怪 AI（`ai`）· 存档（`serialize`）· 事件（`effect_triggers`） |
| `gauge/` | 计量条（累积 / 衰减 / 阈值触发 / 免疫窗口） |
| `formation/` | 站位与目标选择几何 |
| `panel/` | 面板栈（E2：属性聚合的声明式形状） |

## 依赖方向

```text
本包 → saintess_engine（config / text / expr / formula / records / store …）
本包 ✗→ 任何数据包（内容取值一律由数据包装配进来）
```

## 边界

* **零游戏知识**：本包不含职业 / 技能 / 怪物 / 数值；那些是数据包的取值。
* 战斗依赖的**注入面**（公式骨架 / 行动耗时表 / 技能 schema）由数据包挂：
  见 `saintess_engine.config` 的 hook 面。
* 数值与规则表（`effect_rules` / `passive_proc`）仍由数据包声明 —— 本包只读引擎给的规则。
