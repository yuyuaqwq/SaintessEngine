# 随机产出形状（掉落池 / 档位阶梯 / 槽位挂载）

> **归属**：本能力**不在引擎里**（2026-09-23 起）—— 它在扩展包 `extends/ext_loot/`（`loot/`）。
> 数据包要用它：`game.json` 里写 `"depends": ["ext_loot"]`；掉落池数据对应它的域 `drop_pools`。
> 引擎侧只剩通用件，见 `../architecture/boundaries.md`；下文裸文件名（`pick.py` / `pool.py` / `tier.py` / `mount.py`）与行号都相对 `extends/ext_loot/loot/`。
>
> 模块：`ext_loot.loot` —— `LootTable`（池 + 策略注册表 + roll/expand/audit）·
> `TierTable`（有序档位 + 按等级插值的权重表）· `pick_weighted` / `pick_many` / `roll_range` ·
> `draw_slots`（固定 + 随机补足）· `count_for`（档位 → 条数）。
> 一句话：**数据说「有什么」，本形状管「怎么摸」**。

## 为什么有它

参考实现（游戏仓 `dragonfall`）里，「按权重摸一个」这件事散在**掉落池 / 采集 / 商店货架 /
签到 / 事件模板**里，各自 `random.choices(weights=…)` 或手写累加；「档位（品质）顺序与权重」
在装备 / 垂钓 / 锻造货架 / 签到四处各写一份；而 `game/drop_engine.py`（590 行）已经是一台
**手写在内容侧的掉落引擎** —— 池 / 策略注册表 / 展开 / 审计俱全，且**完全不含游戏名词**。
换一套池数据照样跑 → 按判据它是形状，于是搬进扩展包 `ext_loot`。

搬进来顺手砍掉的重复：`drop_engine._quality_weights_inline` 是 `core/fishing._quality_weights`
的**内联副本**（注释自称"防循环 import"）—— 现在两处都问 `TierTable.weights_at()`。

## 四件形状

### 1. 抽取原语（`loot/pick.py`）

```python
pick_weighted(entries, weight_key="w", rng=None)   # → entry | None
pick_many(entries, n, weighted=False, replace=False, where=None, rng=None)
roll_range([1, 2])        # → 1 或 2；int 原样；None → default
weigh(entries)            # → 权重列表（审计/展开用）
```

**语义逐字对齐参考实现的手写累加版**（`pick.py:41`）：

```ini
权重和 ≤ 0 或空表 → None
否则 roll = rng.random() × 权重和；按声明序累加，首个 acc > roll 者中选
浮点误差导致谁都没中 → 兜底返回**最后一个**（不是第一个）
```

⚠️ 这是**故意**的保守写法：换成 `random.choices` 会改随机流（消费的随机数个数不同）→
同一个种子抽出不同结果，迁移期的「逐格一致」比对当场红。门禁 `extends/ext_loot/tests/test_loot.py` 用
定值 rng 把「累加命中」与「末项兜底」两支各钉了一条断言。

### 2. 池 + 策略（`loot/pool.py:219` `LootTable`）

```python
t = LootTable(pools, resolver=my_resolver, strategies={"fish": my_fish},
              inline_prefixes=("gold:",), pool_key_prefixes=("weighted:",), special_refs=("bp",))
t.roll("gather:oak_plain", ctx, qty=2)   # 唯一入口；池不存在/抽空 → []（不抛错）
t.expand("chest:wild_low")               # 带权展开候选
t.audit()                                # {issues, pool_count, entry_count, ok}
```

| 内置策略 | 语义 | 数据形态 |
|---|---|---|
| `weighted` | 带权摸 `ctx.qty` 次；`min_lv`/`max_lv` 窗口过滤；抽空走 `ctx.fallback_roll` 钩子 | `entries[{item,w,n,min_lv,max_lv}]` |
| `fixed` | 全给（必掉清单） | `entries[{item,n}]` |
| `table` | 多层概率表：每行独立判定 `chance` | `rolls[{pool,chance,n,fallback,fallback_n}]` |
| `table_choice` | 互斥档：累计 `cutoff`，或按序首个命中的 `chance` | `rolls[{pool,cutoff\|chance,n}]` |

* **策略注册表**：`register_strategy(name, fn, doc=, uses="entries"|"rolls", needs_weights=, expand=)`；
  重名默认报错，覆盖要显式 `replace=True`。`LootTable(strategies={...})` 也能**实例级**加策略
  （参考实现的 `fish` 就这么挂）。
  `uses` / `needs_weights` / `expand` 是**元数据** —— 审计与展开靠它按策略分派，
  不再像旧实现那样把 `ptype in ("weighted","fish")` 写死。
* **内容侧绑定**（形状层零知识）：`resolver(ref, ctx)` 把引用解析成实物（本形状只调它，不认识前缀）；
  `inline_prefixes` / `pool_key_prefixes` / `special_refs` 是**内容词汇表**。
* **审计的判定与措辞也由内容侧给**：`audit(resolvable=…)` 里 `resolvable(ref, pool)` 返回
  `True`（解得开）/ `False`（断链，引擎给通用措辞）/ **字符串**（断链，且**这句**就是措辞 ——
  内容侧用自己的词汇表说话，如「物品缺失 / 名册缺失 / 子池缺失」）/ `None`（这条引用内容侧自己管，不判）。
  这样形状层不必知道"哪类引用该怎么称呼"，也不会出现「包报一句、内容再改写成另一句」的字符串兼容壳。
* `ctx` 是个宽容袋子（`SimpleCtx`：缺属性 → None；`hooks` 恒为 dict）。
  `roll(key, ctx, **kw)`：`ctx` 与 `kw` 都给 → **就地 `setattr` 到 ctx**（与参考实现一致，别改）。
* 策略抛错：默认吞掉返回 `[]`（"优雅跳过"，旧行为）；`strict=True` 抛出来（迁移期排查用）。

### 3. 档位阶梯（`loot/tier.py:29` `TierTable`）

```python
T = TierTable(order=["t1", ..., "t5"], info={"t1": {"mult": 1.0}}, aliases={"t1": "低"},
              weights_by_level={1: [...], 5: [...], 9: [...]}, clamp=(1, 9))
T.index("t2"); T.next_tier("t4"); T.info_of("t1"); T.resolve("低")
T.weights_at(3)                            # 等级 → 权重行（相邻两档**线性插值**，不取整）
T.pick(level=3, exclude=("t5",), rng=rng)  # 按权重抽一档
T.upgrade("t2", chance=0.05, rng=rng)      # 概率升档（封顶）
```

* `weights_at` 的插值**逐字**沿用参考实现（`tier.py:116`）：低于最小/高于最大取端点行，
  表内相邻两档线性插值（**浮点不取整** —— 取整会改概率分布）
* `clamp=(a, b)` 是内容策略（"副业等级 1..9"），本形状不预设范围
* `upgrade(key, chance, steps)` = 形状（罗盘 / 道具 / 锻造都用它），**chance 是多少**是内容
* 未知档位：`index` → `-1`、`next_tier`/`upgrade` → `None`（**不抛错**：内容侧拿它做"未知就放过"）

### 4. 槽位挂载与条数（`loot/mount.py:20` / `tier.py:175`）

```python
count_for({"t1": 0, "t5": [3, 4]}, "t5", extra_chance=0.20, rng=rng)   # → 3 或 4
draw_slots(pool_ids, 3, fixed=("series_mark",), no_dup=True, rng=rng)  # 固定在前 + 随机补足
```

「橙装 20% 概率多一条」= `{"t5": [3, 4]}` + `extra_chance=0.20`；「固定 1 条系列词条 + 随机补到
品质标准数」= `draw_slots(..., fixed=(...), count=品质条数)`。未知档位 → 0 条（零默认值）。

## 零知识

| 谁 | 给什么 |
|---|---|
| 扩展包 `ext_loot` | 池结构（`pool`/`entry`/`roll`/`n`/`w`）、策略分派、抽取 / 插值 / 升档 / 挂载、审计 |
| 内容 | 池数据、**引用前缀与解析**（`resolver`）、档位**取值**与顺序、`chance` / 权重 / 条数的具体数字、专属策略（`fish`） |

门禁有一条**静态断言**：`extends/ext_loot/loot/` 的**代码常量**里不得出现任何内容侧取值
（档位取值 / 引用前缀 / 专属策略名）—— 文档串可举例（`extends/ext_loot/tests/test_loot.py` 第 8 组）。

## API

| 形状 | 位置 | 说明 |
|---|---|---|
| `pick_weighted` / `pick_index` | `loot/pick.py:41` / `:59` | 加权抽一个 / 同语义返回下标 |
| `pick_many` | `loot/pick.py:77` | 等概率（委托 `rng.sample`）或带权；可放回 / 不放回；`where` 过滤 |
| `roll_range` | `loot/pick.py:116` | `int` / `[a,b]` / `None` → 数量 |
| `weigh` / `total_weight` | `loot/pick.py:32` / `:37` | 权重列表 / 权重和 |
| `LootTable` | `loot/pool.py:219` | 池 + 策略；`roll` `:306` / `expand` `:324` / `audit` `:334` / `audit_pretty` `:399` |
| `LootTable.audit(resolvable=…)` 的判定回调 | `loot/pool.py:411` | `resolvable(ref, pool)` → `True` / `False` / **措辞字符串** / `None` |
| `LootTable.roll_sub` / `roll_cfg` | `loot/pool.py:321` / `:271` | 子池/引用抽取 / 抽一行 roll（自定义策略也用得上） |
| `LootTable.fallback` / `sub_ctx` | `loot/pool.py:299` / `:251` | 兜底钩子 / 子上下文（qty 覆盖） |
| `register_strategy` / `strategy_names` | `loot/pool.py:47` / `:63` | 策略注册（`uses`/`needs_weights`/`expand` 元数据） |
| `SimpleCtx` | `loot/pool.py:95` | 宽容上下文（缺属性 → None） |
| `TierTable` | `loot/tier.py:29` | 档位阶梯；`weights_at` `:116` / `pick` `:165` / `upgrade` `:103` / `resolve` `:90` |
| `count_for` | `loot/tier.py:175` | 档位 → 条数（定值 / 区间 + 命中概率） |
| `draw_slots` | `loot/mount.py:20` | 固定前缀 + 随机补足（不可重复 / 可带权） |

门禁：`extends/ext_loot/tests/test_loot.py`（87 断言：抽取原语的随机流与末项兜底 / 策略注册表与元数据 /
四种内置策略 / 兜底钩子 / 展开与结构审计 / 档位插值与升档 / 挂载 / 零知识静态扫描 / rng 注入可复现）。

## 有意不做

* 不认识物品表、装备表、金币 —— **引用解析是内容侧的事**（`resolver` 钩子）
* 不预设档位取值与数量（五档只是参考实现的选择；本形状对 2 档、7 档一视同仁）
* 不做「保底 / 伪随机分布 / 概率修正」这类**数值策略**（属内容；本形状只提供 `where` 过滤与 `chance` 原语）
* 不做事务与落库（产出之后怎么入包/入账是宿主的事）
