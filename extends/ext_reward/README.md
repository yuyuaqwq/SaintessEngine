# ext_reward —— 流水采集与奖励发放形状（扩展包）

游戏级**能力**包（`kind: extension`）：把「战斗流水采集」这套形状（事件 → 流水记录）
提供给任何数据包用。它不提供「身份」（事件名映射表的下游 kind 名、文案都属数据包）。

## 装它

```python
from saintess_engine.package import load_stack
stack = load_stack("path/to/game", exts=["path/to/extends"])   # 数据包 depends: ["ext_reward"]
```

## 用它

★ 下面这段**逐行跑通过**（不是示意）。★ 导入路径只认下面这一行：
本包**唯一的模块**是 `tlog_collect`（旧版文档写的那个「多一层目录」的名字在本包**不存在** ——
照抄旧版会 `ModuleNotFoundError`）。

```python
import json, os, sys
sys.path.insert(0, "<引擎仓根>"); sys.path.insert(0, "<引擎仓根>/extends")

from saintess_engine.tlog import JSONLSink, KindTable, TLog      # 引擎侧：sink / TLog
from ext_reward.tlog_collect import BattleTLog, EVENT_KINDS, REPRO_KEYS

# ① kind 表由**调用方**从数据包自己的 content/data/tlogs.json 读出来
kt = KindTable.from_data(json.load(open("content/data/tlogs.json", encoding="utf-8")))
# ② TLog(sinks, *, kinds=..., strict=..., name=...) —— sink 由调用方构造后传进来
tlog = TLog([JSONLSink("battle.jsonl")], kinds=kt, name="demo")
# ③ 构造签名逐字是 `BattleTLog(tlog=None, *, tags=(), name="")`：
#    **只有 tlog 是位置参数**；kind 表不在参数里（`EVENT_KINDS` 是模块级映射表，采集器自读）。
#    旧版文档给的构造调用带**三个位置参数**（战斗对象 / sink / kind 表）—— 真实签名不收，
#    照抄旧版即 TypeError；战斗对象一律走下面 ④ 的 attach()。
collector = BattleTLog(tlog, tags=("v1",), name="collector-1")
# ④ 战斗对象走 attach()，不是构造参数
collector.attach(battle, btype="monster", player=hero, enemies=foes)
# ⑤ 事件侧由引擎 fire 触发（战斗对象上的 on_event 被包一层），这里直接喂一条示例
collector.on_event(battle, "skill_hit",
                   {"actor": {"uid": "p1"}, "target": {"uid": "e1"}, "dmg": 7}, [])
collector.flush(); tlog.flush()
# ⇒ battle.jsonl 落下 battle.start + battle.hit 两行，battle.hit 带 tags=["v1"]
```

* `BattleTLog(tlog=None)` ⇒ **全部方法零行为**（可拔插红线：不链观察者、不包 `human_act`、
  不写一个字段）。
* 出口（`JSONLSink` / `MemorySink` / 宿主自己的 sink）与 `TLog` 实例由调用方构造 ——
  本包**不读盘、不写盘、不认识任何游戏专名**。

## 边界（三半边的归属）

| 半边 | 在哪 | 为什么 |
|---|---|---|
| 采集（本包） | `ext_reward/tlog_collect.py` | 纯形状：事件 → 流水，零包内依赖 |
| 回放 | 数据包 `content/tlog_replay.py` | 要宿主重建链与 `event_state`（内容侧的活） |
| 落库（DB sink / 开关） | **宿主** | 平台面（DB 路径、单进程锁） |

## 从哪来

2026-09-24（B4a）：`content/tlog_collect.py`（271 行）**逐字**搬入本包 —— 该文件
`grep` 实测**零包内依赖**（只 import `saintess_engine.tlog` + `typing`），是本轮抽包里
唯一「整文件可搬、一行不用改」的模块。
