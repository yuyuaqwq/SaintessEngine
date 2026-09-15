# 指南：用引擎形状做包（5 个常踩的坑）

「引擎形状」= 引擎提供的**通用机制**：`records`（读资料表）· `store`（存档表 / CRUD / 迁移）·
`produce`（计时作业）· `wire`（取件接线）· `bonus`（数值修正）· `command` / `text` / `tlog` / `loot` / `space` …

做数据包时**这些都不该自己写** —— 你只给「数据 + 声明」。本页的 5 条全部来自一次
**真实的「新包体验」实证**：在 `examples/minimal-game` 里加了一个小闭环
（派队员去据点勘探 → 到点收取 → 记录访问次数 → 据点加成生效），业务文件
`examples/minimal-game/content/outpost.py` **只有 92 行**，里面**零** `import json`、
**零** `CREATE TABLE`、**零**取件样板。**那整份文件可以当骨架照抄**（见 §6）。

下面 5 处就是那次实证里真正被卡住的地方 —— 每条都给出「症状 → 原因 → 正确姿势」。

---

## 1 `records`：`sub` 是「相对包根的目录」，不是你想的 `data/`

```python
# ✗ 症状：表是空的，而且不报错
R = Records(pkg_root, "sites", sub="data")
R.all()          # {}   ← 你以为读 <pkg>/data/sites.json，其实找的是 <pkg>/data/sites.json
```

**原因**：`sub` 是**相对包根**的目录名。引擎自己的示例包把数据放在 `content/data/`，
于是 `sub="data"` 会去找 `<pkg>/data/sites.json` —— **不存在**，于是按「缺文件不抛」的口径给空表。
只有 `R.problems` 里留了一行原因（这是刻意的：读表缺文件不该炸，但要**留痕**）。

```python
# ✓ 正确姿势：把包内真实相对路径写全
R = Records(pkg_root, "sites", sub="content/data")
```

**自查**：装配完后打一行 `RecordsSet.missing_domains()` —— 非空就是有域没读到（别等到玩家那边才发现）。

---

## 2 `produce.Jobs`：`store` 必须宿主给，别在包里造 dict

```python
# ✗ 症状：作业能排、能收，但**重启就没了**（玩家说"我的勘探不见了"）
JOBS = Jobs(store={}, clock=now)          # 包内自造的 dict = 内存态
```

**原因**：`Jobs` 只负责**队列语义**（开工 / 到点 / 清槽 / 多槽），**落哪儿**是使用方的事。
包里自己造一个 dict，得到的是一个「重启丢作业」的假闭环。

```python
# ✓ 正确姿势：把存储当句柄，由宿主（或存档域）给
jobs = Jobs(store=wire.handle("jobs"),                 # 宿主给的 MutableMapping
            clock=lambda: int(wall.now()),             # 见 §3
            max_slots=2)
```

**口径**：作业状态属于**存档**（跨会话要活），所以它要么由宿主持久化后注入，要么直接落一个
`store.declare` 出来的存档表。别用模块级变量。

---

## 3 `produce.Jobs`：`clock` 必须**整数秒**

```python
# ✗ 症状：当场炸，不是静默
Jobs(store=st, clock=wall.now)
# TypeError: 时钟必须给整数秒，收到 float：1700000000.5
```

**原因**：引擎把「时刻」定成**整数秒**（存档友好、跨进程可比）；而 `clock.wall.now()` 是浮点。

```python
# ✓ 正确姿势：适配层一行
jobs = Jobs(store=st, clock=lambda: int(wall.now()))
```

**两个口径别混**（实证里栽过）：**时长/时刻** 用整数秒时钟；**「日历日」**（每日限购、签到这类）
用 `wall.day_key()`。它们取自同一个 provider，但**语义不同**，不要互相顶替。

---

## 4 `bonus`：同来源要「全量重算」，不是「每趟累加」

`Bonus.add(domain, src, value, mode=...)` 对同一个 `(domain, src)` 是**幂等覆盖**：
重复 `add` 同来源 = 用**新值替换**旧值，而不是叠加。这不是限制，是**设计**——
它让「按当前状态重算这个来源」成为唯一写法。

```python
# ✗ 症状：去 4 次得 12（每趟 +3 累加），而游戏设计里第 4 趟应该已被上限截断
bonus.add("panel", "tide_mill", per_visit)          # 每次访问都加一笔 → 累加

# ✓ 正确姿势：每次按当前状态**重算这个来源的值**（幂等覆盖）
bonus.add("panel", "tide_mill", min(visits, MAX_VISITS) * per_visit)
```

**为什么**：装备卸下、状态变化、上限截断 —— 只要来源当前应给多少就写多少，
「撤销」自然发生（甚至不需要 `drop`）。测试要钉住的是**上限截断后的值**，不是累加值。

---

## 5 `store.declare`：复合主键按**声明序位置**传参

```python
repo = declare(db, TableSpec("visits", [Column("member", "TEXT", pk=True),
                                        Column("site_id", "TEXT", pk=True)]))
# ✓ 按声明序传
repo.get(conn, member, site_id)
# ✗ 声明序一改成 [site_id, member]，这里就**静默错位**（不报错，取到别人的记录）
repo.get(conn, member, site_id)
```

**原因**：`Repository.get(conn, *pk_values)` 是**位置参数**（有意不做 ORM / 不做字段名映射）。

**正确姿势**：声明列时把主键顺序**当成公开契约**看待 ——
① 调用点全部按同一顺序写；② 在测试里钉住一次 `get(...)` 的取值；
③ 真要改序，当成**迁移**来做（而不是改一行声明）。

---

## 6 最小骨架（可整份照抄）

`examples/minimal-game/content/outpost.py`（92 行）的骨架形状 —— 用到的**全是引擎形状**：

```python
from saintess_engine.records import RecordsSet
from saintess_engine.store import Column, TableSpec, declare
from saintess_engine.produce import Job, Jobs
from saintess_engine.wire import Wire
from saintess_engine.bonus import Bonus

# ① 数据 + 声明（不写读口代码）
R = RecordsSet(PKG_ROOT, {"sites": {"sub": "content/data"}})

# ② 存档表（不写 DDL / CRUD）
repo = declare(db, TableSpec("visits", [
    Column("member", "TEXT", pk=True), Column("site_id", "TEXT", pk=True),
    Column("times", "INTEGER", notnull=True, default=0),
]))

# ③ 计时作业（不写队列 / 到点 / 清槽）
jobs = Jobs(store=wire.handle("jobs"), clock=lambda: int(wall.now()), max_slots=1)

# ④ 取件（不写 7 套取件样板）
wire.bind(db=db, clock=wall, jobs=job_store)

# ⑤ 数值修正（不写面板合成）
bonus = Bonus(seed=base_panel)
bonus.add("panel", site_id, min(times, site["max_bonus"]) * site["per_visit"])
```

**判据（可以拿来验自己的包）**：

```bash
wc -l content/<你的业务>.py
grep -nE "import json|CREATE TABLE|SELECT |INSERT |UPDATE |sqlite3|_HOST_PKG|_resolve_host|os\.environ" \
    content/<你的业务>.py || echo "★ 零命中：通用机制一行都没写"
```

零命中 + 业务跑通 = 你的包**没有重造轮子**。
