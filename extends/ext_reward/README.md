# ext_reward —— 流水采集与奖励发放形状（扩展包）

游戏级**能力**包（`kind: extension`）：把「战斗流水采集」这套形状（事件 → 流水记录）
提供给任何数据包用。它不提供「身份」（事件名映射表的下游 kind 名、文案都属数据包）。

## 装它

```python
from saintess_engine.package import load_stack
stack = load_stack("path/to/game", exts=["path/to/extends"])   # 数据包 depends: ["ext_reward"]
```

## 用它

```python
from ext_reward.tlog import BattleTLog, EVENT_KINDS, REPRO_KEYS

collector = BattleTLog(battle, tlog, EVENT_KINDS)   # tlog / kind 表都由调用方给
```

* `BattleTLog(tlog=None)` ⇒ **全部方法零行为**（可拔插红线：不链观察者、不包 `human_act`、
  不写一个字段）。
* 出口（`JSONLSink` / `MemorySink` / 宿主自己的 sink）与 `TLog` 实例由调用方构造 ——
  本包**不读盘、不写盘、不认识任何游戏专名**。

## 边界（三半边的归属）

| 半边 | 在哪 | 为什么 |
|---|---|---|
| 采集（本包） | `ext_reward/tlog/collect.py` | 纯形状：事件 → 流水，零包内依赖 |
| 回放 | 数据包 `content/tlog_replay.py` | 要宿主重建链与 `event_state`（内容侧的活） |
| 落库（DB sink / 开关） | **宿主** | 平台面（DB 路径、单进程锁） |

## 从哪来

2026-09-24（B4a）：`content/tlog_collect.py`（271 行）**逐字**搬入本包 —— 该文件
`grep` 实测**零包内依赖**（只 import `saintess_engine.tlog` + `typing`），是本轮抽包里
唯一「整文件可搬、一行不用改」的模块。
