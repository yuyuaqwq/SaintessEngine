# ext_social —— 成员关系与在场（扩展包）

游戏级**能力**包（`kind: extension`）：把「一群人怎么组织」与「今天谁在这里」两套形状装进来。
任何数据包 `depends` 它就能用；装不装它，引擎其它部分行为一致 ——
它是**纯形状库**（零引擎注册、零模块级副作用）。

## 装它

```python
from saintess_engine.package import load_stack
stack = load_stack("path/to/game", exts=["path/to/extends"])   # 数据包 depends: ["ext_social"]
```

## 用它

```python
from ext_social.presence import (Presence, Lookup, day_slot, day_hit,
                                 minutes_left, guarded_roll, cooldown_ok, merge_tables)
from ext_social.membership import Applications, Contribution, RoleNotAllowed, RoleSlots
```

`ext_social` 这个 import 名 = 本包**目录名**（扩展包的命名空间约定）。
★ 从引擎搬出后，原来的 `from ext_social.presence import …` /
`from ext_social.membership import …` 一律换成上面的路径（数据包、测试同理）。

## 内容

| 模块 | 提供 |
|---|---|
| `presence/__init__.py` | 在场形状：`Lookup`（多表首命中 / 真值链）· `Presence`（在场清单装配，`rows` / `here` / `slots` / `slot_at`）· 当天派生 `day_slot` / `day_hit` · 展示口径 `minutes_left` · 保底与冷却 `guarded_roll` / `cooldown_ok` · `merge_tables` |
| `membership/__init__.py` | 成员关系三件形状的包门面 + 口径说明（`__all__`） |
| `membership/roles.py` | `RoleSlots` / `RoleNotAllowed`：可任职位表 + 每职人数上限 + 一人一职互斥 |
| `membership/contribution.py` | `Contribution`：累计值 + 周期窗口 + 排名（名单序实时读，不缓存） |
| `membership/applications.py` | `Applications` / `QueueFull`：待批队列（保序 / 去重 / 容量上限；通过时可入册） |

## 依赖方向

```text
本包 → saintess_engine（只有 presence 取 `_validators` 的通用守卫）
本包 ✗→ 数据包 / 其它扩展包（取值、判据、规则一律注入）
```

## 边界

* **零游戏知识**：职位名 / 周期名 / 贡献怎么算 / 在场判据 / 表名与表数 / 盐，全是数据包的取值；
  引擎一个字段名都不认识。
* **成员集合只有一个（铁律）**：`membership` 不定义成员表，只**持有名单引用**
  （`roster=` 可选注入面，`self.roster is None` 即留痕）；在册判定、名单序、入册一律转发给名单 ——
  鸭子类型取用它的口（`is_member` / `members` / `join`），**不 import 名单的类**。
  名单本体（`Roster`）不属于本包（本批它随 `ext_world` 离开引擎）。
* **不碰时间与随机**：`presence` 不 import 时间 / 日期库、不 import `random`；
  `day` 是调用方给的整数日序数，随机源一律经注入的 `rng()`（可复现、可测试）。
* **不判权限、不判入会条件**：那属内容侧；本包只判结构事（可任表 / 上限 / 互斥 / 重复 / 保序 / 去重）。

## 测试

门禁在引擎仓 `tests/`（`test_presence_shape.py` / `test_membership_shape.py`），
随 `python tests/run_all.py` 一起跑；它们原先按 `saintess_engine.*` 导入，
搬迁后需改成 `ext_social.*`（见「用它」一节）。
