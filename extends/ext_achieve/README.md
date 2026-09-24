# ext_achieve —— 条件判定与账本形状（扩展包）

游戏级**能力**包（`kind: extension`）：把「条件怎么登记、怎么判、怎么兜底」这套形状
提供给任何数据包用。它不提供**内容**：判定函数、环境词表、声明表全部由数据包给。

形状清单（一个形状一步）：`cond/registry.py` 条件注册表 · `cond/envs.py` 环境位图 ·
`rule/engine.py` 规则触发 · `earn/shape.py` 逐条求值（上下文外壳 + 参数化条件 + 求值器）·
`ledger/shape.py` 账本（解锁遍历 / 领取 / 标签名 / 点数）。

## 装它

```python
from saintess_engine.package import load_stack
stack = load_stack("path/to/game", exts=["path/to/extends"])   # 数据包 depends: ["ext_achieve"]
```

## 用它

```python
from ext_achieve.cond import EnvCtx, Registry, bind_envs, envs_of

# ① 条件注册表：名字 → 判定函数（未知名按默认键兜底 · 声明表可整表装配）
REG = Registry(default_key="any")
CONDITIONS = REG.table                       # 普通 dict：外部直接写 / pop 即刻生效
register = REG.register
REG.register_specs(spec_table_from_json)     # 声明表：编译交给引擎，形状只管登记
REG.check("some_cond", ctx)

# ② 环境位图：场地 id × 注入的词表 → {环境名: bool}
bind_envs({"forest": ("wood", "glade"), ...})   # 也收「零参可调用」（惰性取值）
envs = envs_of("some_place_id")
ctx = EnvCtx("some_place_id", carrier, is_night, envs)
ctx.env("forest")
```

## 规则触发形状（`ext_achieve.rule`）

「条件 / 计数器 / 概率 → 执行某模板」这台机器本身（搬自数据包 `content/rule_engine.py`）。
规则**数据**、时段语义、计数落库、背包/旗标读口、模板执行一律由数据包注入：

```python
from ext_achieve.rule import bind, fire
bind(rules=lambda: _rules(),               # 规则表（也收 list 本身：对象共享，就地改即刻生效）
     is_time=lambda span: _is_time(span),  # 时段判定（白天/夜晚的钟点边界是玩法设定）
     counter_get=counter_get, counter_set=counter_set,   # 连续命中计数（落库在数据包）
     count_item=count_item, talk_flag=talk_flag,         # 背包持有数 / 对白旗标
     fire_event=fire_event)                # 执行 action 模板（EventContext + 模板引擎）
fire(gid, qq_id, player, cur_map, "explore_done", {"event": "empty"})
```

条件字段（**数据里写什么，形状就读什么**）：`map` / `map_type` / `time` / `level_min` /
`level_max` / `item` / `flag` / `event` / `enemy_tag` / `hp_pct_max` / `random_chance`；
规则字段：`trigger` / `enabled` / `cond` / `count{key,gte}` / `chance` / `action{template,params}`。

## 装配纪律（两条，都是 fail-loud）

| 纪律 | 为什么 |
|---|---|
| **未装配即取用当场报错** | 「空表 ⇒ 全 False / 全不满足」会把「装配忘了」伪装成「条件不成立」—— 症状是某条判定永不成立，只能靠翻数据发现 |
| **注入的是对象本身（不复制）** | 与原地「模块级表 + 调用时读」同语义：调用方后续就地补环境族 / 改关键词，立刻生效 |

另：`Registry(default_key=…)` 的默认键是**装配期契约** —— `check` 的兜底值是立即求值的，
默认键没登记时即便名字命中也会抛 `KeyError`（逐字沿用原地口径，不是这里「顺手改合理」的地方）。

## 边界（形状在包、内容在数据包）

| 半边 | 在哪 | 为什么 |
|---|---|---|
| 注册表 / 查表口径 / 声明表装配 | 本包 `cond/registry.py` | 纯形状：与「有哪些条件」无关 |
| 环境位图算法（id × 词表 → 位图） | 本包 `cond/envs.py` | 纯形状：**词表本身是内容**，调用方注入 |
| 判定函数（`_c_*` / `_t_*` 一类） | 数据包 | 读的是材料/地图/名册/任务 —— 内容是内容 |
| 环境词表（地名关键词 → 环境族） | 数据包 | 地名怎么起名是那款游戏的设定 |
| 声明表 JSON（`cond_specs.json` 的族） | 数据包 | 数据面 |

## 从哪来

2026-09-24 **B2a**（抽包工程 §2.1 的 B2 批第一步）：`content/hidden_cond.py`（82 行）
拆成两半 —— 形状进本包，内容词表与声明表留在数据包；数据包侧 `content/hidden_cond.py`
变成薄适配层（对外签名一字不改，`combat_cmds` 与既有门禁零改动）。

**为什么没有把环境词表搬进 JSON**（设计稿里给过一个备选）：`content/data/cond_specs.json`
的 **sha256 被冻结门禁钉着**（`tests/test_u1i4_dialogue_frozen.py` 的 `cond_specs_fp`），
新增一族 = 撞冻结门禁；另开数据域则要动「域表 / AUX 登记 / 清单」三处（`test_export_package_sync.py`）。
而本批真正要守的判据是「**扩展包零内容词表**」—— 词表留在数据包（它本来就该带内容身份）
同样满足，且改动面最小。

## 从哪来（B2b：规则触发形状）

2026-09-24 **B2b**（B2 批第二步）：`content/rule_engine.py`（251 行）里的触发形状进
`rule/engine.py`；数据包侧同名模块变成「规则表 + 存储读口 + 时段语义 + 模板执行桥」
（对外面一字未改：`fire` / `_get_counter` / `_is_time` / `RULES` 全在，消费者
`combat_cmds` / `settlement` / `facade` 的 wire 与测试打桩点零改动）。

## 逐条求值形状（`ext_achieve.earn`）

「一族条目（每条一个 id）逐条判是否达成」这台机器（搬自数据包 `title_conds.py`）。

```python
from ext_achieve.earn import EvalCtx, ParamCond, bind, earned_flags

bind(db=db)                      # 注入读口（= ctx._db() 的返回物；未装配就取用 ⇒ 当场报错）
ctx = EvalCtx(gid, qid, player, stats, rep, quests, hooks={...})   # 字段/位置序 = 形状契约
fallback = ParamCond("pro_", ("gather", ...), lambda ctx, key: ctx._db().get_prof_level(...))
flags = earned_flags(TABLE, ctx, CONDITIONS, fallback)             # 同长同序 · fallback 可省
```

| 形状 | 口径 |
|---|---|
| `EvalCtx` | 字段 + 钩子表（`hook(name, …)`：有则转给、没有回 `None`）+ 注入读口 `_db()` |
| `ParamCond` | `<前缀><类别><数字>` ⇒ 「该类别等级 ≥ 数字」；前缀/类别集合/读取器都是内容侧给的 |
| `earned_flags` | 注册表命中 ⇒ 判定函数；否则兜底匹配 ⇒ 调它；都不中 ⇒ `False`（未知 id 安全降级） |

两条硬口径：判定函数的返回值**原样收进来**（不做 `bool` 归一）；条目 `dict` 缺 `"id"` ⇒
`KeyError`（与原地 `t["id"]` 同口径，不静默降级）。

## 从哪来（B2-S3：逐条求值形状）

2026-09-24 **B2-S3**（B2 批第三步）：`content/title_conds.py` 的**上下文外壳**（`TitleCtx`）、
**逐条判循环**、**参数化条件**（`check_pro_title` 的 `pro_<prof><lv>`）三样进 `earn/shape.py`；
数据包侧只留 `_t_*` 判定函数、`pro_` 前缀与副业类别集合、称号表的喂入，并转出旧名
（`TitleCtx` / `check_pro_title`）与新出口 `earned_titles(ctx)`。
两个消费者 `content/economy_cmds.py::_earned_titles` 与 `content/stat_bonus.py` 的**重复循环**
因此合成一处（各自只留「喂 ctx」一行）。

## 账本形状（`ext_achieve.ledger`）

「一条账本怎么遍历、怎么领、怎么算」这台机器（搬自数据包 `content/achievements.py`）。

```python
from ext_achieve.ledger import bind, check, claim, labels, points

bind(entries=lambda: TABLE,        # 条目表（也收 list 本身：对象共享，就地改即刻生效）
     ledger_of=…, mark=…,          # 账本读口（归一到 {id, claimed, progress}）/ 落库口
     player_of=…, stats_of=…, profs_of=…, save_player=…,   # 玩家与统计读写
     cond_of=…,                    # 单条判据（内容侧注册表的总入口）
     clear_of=…, weight_of=…, label_of=…,   # 通关记录键 / 点数权重 / 标签名
     name_of=…, line_of=…, reward_of=…,     # 显示名 / 回执行 / 奖励三条支路
     phrase=…,                     # 文案槽位 → 文案（真源在数据包）
     machine=…, enrich=…, payout=…, grant=…, levelup=…)   # 三态机 / 加成 / 记账 / 发放 / 升级

check(gid, qid, player, extra)     # → 本次新解锁条目（副本，带奖励摘要；不自动发放）
claim(gid, qid)                    # → (lines, err)：三态机筛档位 → 汇总 → 发放 → 结算 → 落库
labels(qid); points(qid)           # 已解锁条目的标签名（源表序）/ 点数合计
```

| 口径 | 说明 |
|---|---|
| 条目表字段 | `id` / `cond` 是**形状契约**；奖励三条支路走 `reward_of` 现取（三个键名是数据包 schema） |
| 落库口径 | 解锁 = `(progress=1, claimed=0)` 待领取；领取 = `(1, 1)`；无物可领的待领项直接落成已领 |
| 幂等 | 「可领」判定走注入的三态机（`claim` 只在 READY 态记入），重复领取 ⇒ 空回执 + 提示 |
| 降级 | 形状**不吞异常**：读库/落库失败的兜底（记日志 + 回一句文案）留给调用方 |
| 文案 | 形状只传**槽位名 + 实参**（`reward_exp` / `claim_head` / `none` …），键名与措辞在数据包 |

## 后续（同一批的余下几步）

`S1` ✅ 2026-09-24 **B2a** —— 条件注册表 + 环境位图（本包 `cond/`）。
`S2` ✅ 2026-09-24 **B2b** —— 规则触发形状（本包 `rule/`）。
`S3` ✅ 2026-09-24 —— 逐条求值形状（本包 `earn/`）。
`S4` ✅ 2026-09-24 —— 账本形状（本包 `ledger/`：四函数进包、二十句柄注入、
数据包侧只剩「注入面 + 条件注册 + 统计读口 + 四函数薄壳」）。
`S5` ✅ 2026-09-24 **收口** —— 终检（AST，可证伪）：数据包侧四个文件
（`content/achievements.py` 392 行 · `title_conds.py` 230 · `rule_engine.py` 129 · `hidden_cond.py` 60）
残留函数**最大体 18 行、>30 行的 0 个**，全是「注册 / 注入 / 判据 / 薄壳」⇒ 「数据包只剩
注册 + 注入 + 数据」成立。收口四证：本包门禁 **152/152** · 数据包全量 **286/286** ·
引擎全量 **89/89** · 试玩摘要 `digests_sha = 2e683a67…`（与 B2 开工前**逐字节相同**）。
**B2 批（5 步）收口完毕。**

每步独立提交、独立验收（本包门禁 + 数据包全量 + 引擎全量 + 试玩摘要 sha 不变）。
