# 声明驱动的指令与文案（可拔插）

> 两个模块：`saintess_engine.command.CommandRegistry` · `saintess_engine.text.TextTable`
> 共同点：**声明即形状，内容用数据给**；不装载 = 零行为。

## 为什么有它

宿主命令层常见形态是「两处数据互相同步」：一叠 `@装饰器`（真实注册）+ 一张手工维护的
静态正则表（供 gate / 快捷转发 / 测试用）。两处 = 一定会漂移，只能「再加一个同步测试盯着」。
文案同样散在数据表内联与代码 f-string 之间，于是改一句话要动代码、编辑器覆盖不到文本。

两个模块把「一条指令 / 一条文案」抽成声明，注册表负责装载 / 查询 / 匹配 / 派生 / 自检。

## 指令：`CommandSpec` / `CommandRegistry`

| 字段 | 说明 |
|---|---|
| `key` | 指令标识（通常等于宿主 handler 名——漂移自检按它对齐） |
| `patterns` | 命中正则（首条为主，其余别名）；`combined()` 得合并串 |
| `desc` / `category` / `usage` | 帮助与编辑器用（分类取值由内容侧定，框架不设枚举） |
| `guards` | 守卫**名字**列表（语义由内容侧实现；框架不认「角色」这类概念） |
| `visible` / `order` / `page_size` | 帮助可见性 / 排序 / 列表每页条数 |
| `extra` | 内容侧自定义数据，框架不解释、原样带回 |

```python
reg = CommandRegistry.from_data({"go": "^go(?:\s+(\w+))?$",
                                 "look": {"patterns": ["^look$", "^l$"], "category": "移动"}})
reg.hits("go north")        # → 命中的全部声明（互斥矩阵自检用）
reg.hit("l").key            # → "look"
reg.patterns()              # → 正则池（宿主「怎样算一条指令」的 filter）
reg.pattern_map()           # → {key: 合并正则}；单条时逐字等于原声明
reg.validate()              # → 声明自身问题（空正则 / 非法正则 / 正则被多条共用）
reg.audit_handlers(names)   # → missing_spec（漏登记）/ missing_handler（死声明）
```

**它替代什么**：手工镜像表 + 「表与装饰器同步」测试。迁移可以**增量**做——
每迁一条，就把该 key 从字面量表里删掉，`COMMAND_REGEX = {**声明派生, **字面量}` 合并即可，
**同一个 key 只能有一个来源**（否则又是双源）。

## 文案：`TextSpec` / `TextTable`

```python
t = TextTable({"battle.hit": "命中 {n} 点"})
t.render("battle.hit", n=5)          # → "命中 5 点"
t.render("battle.hit", m=1)          # → "命中 {n} 点"（未知槽**原样保留**，不抛）
t.render("never.defined")            # → "never.defined"（并记入 missing）
t.render_or("new.key", "新文案 {a}", a=9)   # 渐进迁移：表里没有就用调用方默认串
t.missing(); t.unused(); t.validate()
```

缺失 key 的四种行为（可拔插语义）：`strict=True` 抛 `KeyError`（CI 用）→ `on_miss` 回调
→ `fallback` 模板 → 返回 key 本身。

**有意不做**：不做多语言切换（要几套语言就建几张表）；不做格式化 DSL（就用 `str.format`
的 `{slot}`）；不猜（模板缺槽保留原文，让问题可见）。

## 编辑器

两域已注册（`editor/packages.py` 的 `DOMAINS`）：`commands` / `texts`，各有 schema
（`schemas/command.schema.json` / `text.schema.json`）与字段分组。编辑器建包时勾选即生成
`content/data/commands.json` / `texts.json`，校验由 schema 把关。

> 表形态里**对象 key 就是标识**，所以条目值里不必再写 `key`（schema 的 `required` 只要求
> 「值本身必须给的字段」：指令是 `patterns`，文案是 `value`）。代码装载时也接受
> `{key: 模板串}` 简写。
