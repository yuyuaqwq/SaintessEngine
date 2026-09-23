# ext_life —— 生活循环形状（扩展包）

游戏级**形状**包（`kind: extension`）：把「日常经营循环」里反复手写的四件形状收成一份可插拔实现 ——
**收集进度 / 档位领取**（`collect`）· **周期键上的限额与连续段**（`periodic`）·
**倒计时事件**（`timers`）· **解锁闸门**（`unlock`）。
任何数据包都能 `depends` 它来用；它不提供「身份」（条目 / 档位 / 周期算法 / 门槛内容属于数据包）。

## 装它

```python
from saintess_engine.package import load_stack
stack = load_stack("path/to/game", exts=["path/to/extends"])   # 数据包 depends: ["ext_life"]
```

## 用它

```python
from ext_life.collect import Tally, TierBoard, tier_state, LOCKED, READY, CLAIMED
from ext_life.periodic import PeriodCounter, PeriodSlot, Streak, Cooldown
from ext_life.timers import Timers
from ext_life.unlock import Unlocks, Locked
```

`ext_life` 这个 import 名 = 本包**目录名**（扩展包的命名空间约定）；
包内模块一律走这个命名空间，因此同一进程里装多个扩展包互不冲突。

## 内容

| 模块 | 提供 |
|---|---|
| `collect/__init__.py` | `Tally`（N/M 计数）· `TierBoard`（档位三态：未达成 / 可领 / 已领）· `tier_state` · 状态字面量 `LOCKED` / `READY` / `CLAIMED` |
| `periodic/__init__.py` | `PeriodCounter`（周期键上的计数与上限）· `PeriodSlot`（周期键上的原样槽位）· `Streak`（连续段）· `Cooldown`（冷却窗口）· `PeriodLimitExceeded` |
| `timers/__init__.py` | `Timers`（类型注册 + 实例挂载/刷新 + 懒过期 + 过期回调；无后台定时器，读路径顺带清理）· `TimerStorageError` |
| `unlock/__init__.py` | `Unlocks`（按条目判「这块内容对玩家开放没有」，三档 fail-closed）· `Locked`（锁定结构）· `UnlockDeclError` |

## 依赖方向

```text
本包 → saintess_engine（_validators / log / conditions）
本包 ✗→ 任何数据包（条目表、判据回调、周期键拼法、条件声明一律由数据包装配进来）
```

## 边界

* **零游戏词汇**：不认「阶段 / 地图 / 系统 / 具体周期算法」；标识符一律当不透明字符串。
* **零落盘**：存储面（`store` / `read`+`write` / `claimed` 集合）由调用方注入，本包不缓存。
* **不进注册表**：`install_engine()` 是空实现 —— 形状按需取用，不需要全局装配
  （`timers` 的类型注册表挂在 `Timers` 实例上，不是模块级全局）。
* 需要「收集什么 / 几档 / 周期怎么算 / 门槛条件」的规则？那属于数据包（内容），不属于这一层。
