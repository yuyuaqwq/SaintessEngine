# ext_loot —— 随机产出形状（扩展包）

游戏级**能力**包（`kind: extension`）：把「怎么随机产出一堆东西」这套**形状**装进来 ——
加权抽取原语 → 池 + 策略注册表 → 有序档位阶梯 → 槽位挂载 → 计数保底。
任何数据包 `depends` 它就能抽；不 depends 就是一个不随机产出的框架（纯经营 / 纯解谜照样跑）。

它不提供「身份」：池里装什么、档位叫什么、引用前缀怎么写、用哪个随机源，全在数据包。
引擎（与本包）都不知道「掉落」「品质」「词条」这些词。

## 装它

```python
from saintess_engine.package import load_stack
stack = load_stack("path/to/game", exts=["path/to/extends"])   # 数据包 depends: ["ext_loot"]
```

## 用它

```python
from ext_loot.loot import (LootTable, TierTable, SimpleCtx,
                           pick_weighted, pick_many, roll_range, weigh,
                           draw_slots, count_for, pity_force, pity_advance)

t = LootTable(pools, resolver=my_resolver, strategies={"fish": my_fish},
              inline_prefixes=("gold:", "item:"))          # 池数据 / 解析器 / 自定义策略由内容侧给
t.roll("gather:oak_plain", ctx, qty=2); t.expand("chest:wild_low"); t.audit()

T = TierTable(["white", "green", "blue", "purple", "orange"], info={...},
              weights_by_level={1: [...], 9: [...]})       # 档位取值由内容侧给
n = count_for({"orange": [3, 4]}, quality, extra_chance=0.20, rng=random)
ids = draw_slots(pool, n, fixed=("series_mark",), rng=random)
```

`ext_loot` 这个 import 名 = 本包**目录名**（扩展包的命名空间约定）；
包内模块一律相对导入，因此同一进程里装多个扩展包互不冲突。

## 内容

| 模块 | 提供 |
|---|---|
| `loot/__init__.py` | 包门面 + 形状判据（`__all__`） |
| `loot/pick.py` | 加权抽取原语：`pick_weighted` / `pick_index` / `pick_many` / `roll_range` / `weigh` / `total_weight` |
| `loot/pool.py` | `LootTable`（池集合 + 引用解析 + 策略注册表；`roll` / `expand` / `audit` / `audit_pretty`）+ `SimpleCtx` / `UnknownStrategy` / `register_strategy` |
| `loot/tier.py` | `TierTable`（有序档位 + 按等级插值的权重表 + 抽档 / 升档）+ `count_for`（档位 → 条数） |
| `loot/mount.py` | `draw_slots`（固定项在前 + 从池里随机补足、不重复、不足给尽） |
| `loot/pity.py` | `pity_force` / `pity_advance`（计数保底，纯函数、不持状态） |

## 依赖方向

```text
本包 → 标准库（random / copy）
本包 ✗→ saintess_engine（本包零引擎依赖：一个引擎通用件都没 import）
本包 ✗→ 任何数据包（池数据 / 档位取值 / 解析器一律由数据包注入）
```

## 边界

* **零游戏知识**：引擎与本包源码的代码常量里没有任何内容侧取值（档位取值 / 引用前缀 / 专属策略名）。
* **随机源注入**：所有随机都走传入的 `rng`（缺省标准库 `random`）—— 这是「可复现 + 可逐格比对」的前提。
* **不进注册表**：`install_engine()` 是空实现。唯一的模块级状态是本包内部的策略注册表
  `pool.STRATEGIES`（内置四个 + 内容侧 `register_strategy()` 追加），不挂引擎 hook 面。
* **不声明 `provides`**：引擎没有「随机产出」能力键；宿主取「掉什么」走数据包的
  `content/loot.py`（入口同级可选半边），本包只提供形状。
* **不做的事**：落库 / 发奖 / 池数据的真源 / 具体策略名（如「钓鱼」）—— 全是数据包的活。

## 测试

模块门禁（零知识 / 抽取语义 / 池与策略 / 审计 / 档位 / 挂载）随本批搬迁留在引擎仓
`tests/`，由主线在包栈重构后统一归位；本包目录当前不含 `tests/`。
