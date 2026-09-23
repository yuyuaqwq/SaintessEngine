# ext_quest —— 任务账本与目标类型（扩展包）

游戏级**能力**包（`kind: extension`）：提供「任务账本 + 目标类型注册表」这套形状，
任何数据包都能 `depends` 它来用。它不提供「身份」（职业 / 技能 / 文案属于数据包）。

## 装它

```python
from saintess_engine.package import load_stack
stack = load_stack("path/to/game", exts=["path/to/extends"])   # 数据包 depends: ["ext_quest"]
```

## 用它

```python
from ext_quest.quest import QuestLog, Objectives
```

`ext_quest` 这个 import 名 = 本包**目录名**（扩展包的命名空间约定）；
包内模块一律走这个命名空间，因此同一进程里装多个扩展包互不冲突。

## 内容

| 模块 | 提供 |
|---|---|
| `quest/__init__.py` | 包门面 + 口径说明（`__all__`） |
| `quest/ledger.py` | `QuestLog`：任务账本（进度 / 完成 / 领取状态机） |
| `quest/objective.py` | `Objectives` / `Objective` / `parse_needs`：目标类型注册表与解析 |

## 测试

`tests/`（本包自带，跟着引擎仓 `python tests/run_all.py` 一起跑）。

## 边界

* **零引擎依赖**：本包只用标准库，不 import 引擎任何游戏形状。
* **不进注册表**：`install_engine()` 是空实现 —— 形状库按需取用，不需要全局装配。
* 需要「任务怎么发 / 怎么给奖励」的规则？那属于数据包（内容），不属于这一层。
