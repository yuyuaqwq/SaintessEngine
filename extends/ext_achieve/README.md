# ext_achieve —— 条件判定与账本形状（扩展包）

游戏级**能力**包（`kind: extension`）：把「条件怎么登记、怎么判、怎么兜底」这套形状
提供给任何数据包用。它不提供**内容**：判定函数、环境词表、声明表全部由数据包给。

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

## 后续（同一批的余下几步）

`S2` ✅ **已完成 2026-09-24（B2b）** —— 规则触发形状（本包 `rule/`）。余
`S3` 条件注册表 + 称号求值 · `S4` 账本 / 领取 / 点数 ·
`S5` 收口（数据包只剩「注册 + 注入 + 数据」）。
每步独立提交、独立验收（本包门禁 + 数据包全量 + 引擎全量 + 试玩摘要 sha 不变）。
