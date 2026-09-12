# 运行形状（准入链 + 进度 + 名单）

> 模块：`saintess_engine.run` —— `Admission`/`Rule`（准入链）+ `Progress`（进度）+ `Roster`（名单）。
> 一句话：**一次运行的三件事 —— 谁能进、谁在里面、打到哪了**；数据与措辞全由内容侧给。

## 为什么有它

参考实现（游戏仓 `dragonfall`）里，一趟「组队副本」的运行状态被拆成三份形状，
而每一份都被抄了好几遍：

| # | 位置 | 内容 |
|---|---|---|
| 1 | `world.py` `_instance_gate_block` | 徒步进图三档准入（任务放行 → 持钥匙 → 已通关豁免） |
| 2 | `instance.py` `_instance_start` | 开本准入：人数 → 队长 → 全队等级/血量/战斗中/副业等待 → 钥匙（**扣**）→ 入口 → 体力（**扣**） |
| 3 | `instance.py` 恢复路径 | 「与 `_instance_start` 同规则」的四连**重写**（注释自己承认同源） |
| 4 | `instance.py` `加入战斗` | 重复加入 / 满员 / 敌方全灭 / 0 血 |
| 5 | `instance.py` `_instance_build_state` | 同一个状态 dict **写了三遍**（分层 / 单层 Boss 房 / 老副本兜底） |
| 6 | `instance_router.py` 三处 | 「敌人清空 → 回地图模式」重置块**逐字抄了三遍** |
| 7 | 63 处 `members`/`alive` 读写 + 两处过滤函数 | 成员集合 + 队长 + 存活 + 「在场过滤」 |

把「副本 / 层 / 房间 / 钥匙 / 队伍」这些取值拿掉，三份逻辑都照旧成立 —— 按判据这就是形状。

## 三个子形状

```python
from saintess_engine.run import Admission, Rule, Progress, Roster

# ① 准入链：有序规则，首拒即返；副作用（消耗）延迟到全过才执行
adm = Admission([
    Rule("size",  check=size_ok, reason="人数不够"),
    Rule("key",   check=has_key, reason=key_text, consume=deduct_key),
    Rule("place", check=here,    reason="位置不对"),
], name="open")
v = adm.check(ctx)
if not v.ok:
    show(v.reason)          # 首个拒绝的规则给的措辞（内容侧逐字给）

# ② 进度：有序节点 + 每节点具名剩余池 + 预算
p = Progress([{"key": "l1", "label": "一号"}, {"key": "l2", "label": "二号"}])
p.push("l1", "units", mon); p.take("l1", "units"); p.left("l1", "units")
p.node_cleared("l1"); p.is_last(); p.advance(); p.goto("l1")
p.set_budget("coin", 500); p.spend("coin", 300)     # 不足只给剩余

# ③ 名单：保序成员 + 队长 + 存活 + 过滤排序
r = Roster(["1", "2"], leader="1")
r.alive("2"); r.living(); r.keep(lambda m: m in party); r.sort_by(key, reverse=True)
```

| 形状 | 语义要点 | 谁给 |
|---|---|---|
| `Rule` | 命名的单条校验；`check(ctx)` 返回 `None`/`True` 通过、`False` 用 `reason`、`str` 就地给措辞 | 引擎（规则体内容侧写） |
| `Admission` | **首拒即返**（后续规则不求值）、**副作用延迟**（全过才按声明序各一次）、`trace`/`audit` | 引擎 |
| `Progress` | 有序节点（线性 `advance` 或按 key `goto`）+ 具名剩余池（`push`/`take`/`drop`/`left`）+ 预算（`spend` 不足给剩余）+ 往返 | 引擎 |
| `Roster` | 保序成员 + 队长 + 存活（未登记 = 存活）+ `keep`/`only`/`sort_by`/`join`/`leave` + 往返 | 引擎 |
| 节点 key、池名、规则名、措辞、顺序依据 | **取值与措辞**，引擎不解释 | 内容侧 |

## 三条纪律（门禁逐条钉住）

### 1. 首拒即返

第一条拒绝的规则**之后**的规则 `check` 一次都不许被调用（旧实现就是 `yield …; return` 语义）。
`v.trace` 把后续记成 `skip`，便于对照：

```python
kinds = []
v = Admission([Rule("a", check=lambda c: kinds.append("a") or True),
               Rule("b", check=lambda c: kinds.append("b") or False),
               Rule("c", check=lambda c: kinds.append("c") or True)]).check({})
# kinds == ["a", "b"]        ← c 一次都没判
# v.trace == (("a","pass",""), ("b","deny","…"), ("c","skip",""))
```

### 2. 副作用延迟 ★

`consume` **只在全部规则通过后**按声明序各执行一次；拒绝路径上一个都不执行。

> 这条是从真缺陷倒推出来的：旧开本流程「全队校验过 → **扣钥匙** → 入口位置校验 → 体力扣减」，
> 位置或体力拒绝时**钥匙已经扣走**（白扣）。形状上把副作用挪到链尾之后，这类 bug 不可能再写出来。

### 3. 判定与措辞分离

`check` 只说通过与否，`reason`（str 或 `callable(ctx)`）负责怎么说。
引擎不含任何内容措辞 —— 同一个形状换个游戏只换措辞。

## 与其它形状的分工

| 相邻能力 | 归谁 | 说明 |
|---|---|---|
| 网状连通 / 必经路径 / 出入口 | `space` | `Progress.goto` 只做定位，**不校验连通性** |
| 池里产出什么（奖励、掉落） | `loot` | `Progress` 的池只记「还剩什么」，怎么抽是 `loot` 的事 |
| 时序推进（谁先动） | `battle.schedule` | `Roster.sort_by` 只按你给的键重排，不猜顺序 |

## 已知边界（诚实列出）

- `Progress.done` = **所有节点的所有池都空**；未创建池的节点算「已清」（缺字段不是有内容）。
  空节点表 → `done=False`（不谎报清空）。
- `Progress` 不持久化语义：`to_dict/from_dict` 只保证往返一致；**存档格式由内容侧定**。
- `Admission` 不吞异常：规则里抛错当场暴露（与「自己写 if 链」一致）。
- `run` 不含「运行阶段状态机」（进行/通关/失败/撤退的迁移规则）—— 边界未定，暂不抽。

## 门禁

`tests/test_run.py`（108 断言）：首拒即返 / 副作用延迟 / 审计 / 进度池与推进与往返 /
预算不足给剩余 / 名单过滤排序 / **零知识静态扫描**（跳过文档串）/ 门面 re-export。
