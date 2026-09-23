# ext_economy —— 交易与产出形状（扩展包）

游戏级**能力**包（`kind: extension`）：提供「交易类玩法」的三件通用形状 ——
**限购计数** · **限量货架** · **计时生产**。它不提供「身份」（商品 / 定价 / 产出物 /
时长公式都属于数据包）。

## 装它

```python
from saintess_engine.package import load_stack
stack = load_stack("path/to/game", exts=["path/to/extends"])   # 数据包 depends: [ext_economy]
```

## 用它

```python
from ext_economy.trade import DailyLimit, DailyLimitExceeded, apply_rate, settle_sale
from ext_economy.shelf import Shelf
from ext_economy.produce import AlreadyBusy, Job, Jobs
```

`ext_economy` 这个 import 名 = 本包**目录名**（扩展包的命名空间约定）；
包内模块一律走这个命名空间，因此同一进程里装多个扩展包互不冲突。

## 内容

| 模块 | 提供 |
|---|---|
| `trade/__init__.py` | `DailyLimit` / `DailyLimitExceeded`（「当日标识 + key」计数，跨日自动归零）· `apply_rate`（折价乘算 + 取整）· `settle_sale` / `SaleResult`（成交结算：毛额 / 税 / 净额，只回调一次 `on_change`） |
| `shelf/__init__.py` | `Shelf`：N 个格子 + 每格库存 + 两类周期（换货 / 补货）+ 售罄下架 + 先到先得；`ensure` 惰性推进，引擎不起定时器。fail-closed：读不出簿记 → `ShelfStateError`，`fill()` 不合契约 → `ShelfFillError` |
| `produce/__init__.py` | `Job` / `Jobs`：每人 1..N 槽的计时作业队列（`begin` / `current` / `all_of` / `settle` / `due` / `clear`）；到点判据只用注入的时钟；存储取不出作业表 → `ProduceStorageError`（绝不静默清空） |

## 边界

* **零引擎知识**：三个模块都只用标准库，不 import 引擎任何游戏形状；商品 / 定价 /
  日历日 / 时长 / 产出规则全部由内容侧注入。
* **不落盘、不起定时器**：`state` / `store` 是调用方给的映射，「到点」只靠注入的
  `clock()` 与调用方主动调 `ensure` / `settle` 推进 —— 引擎不读系统时间、不建线程。
* **不进注册表**：`install_engine()` 是空实现（本包没有 `provides` 声明）——
  形状库按需取用，不需要全局装配。

## 测试

本包随第 3 批搬迁从 `saintess_engine/` 移出，门禁归属由主线统一安排
（`tests/` 不在本批搬迁范围内）。
