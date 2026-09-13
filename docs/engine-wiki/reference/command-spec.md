# 指令声明表装载形状

> 模块：`saintess_engine.command.spec` —— `CommandSpecSource` / `load_table` /
> `build_registry` / `pattern_map_from_table` / `catalog_of`。
> 一句话：**「一份声明表 → 注册表 + 有效表 + 目录」的形状收在引擎；宿主只给「表在哪」和「怎么注册」。**

## 为什么有它

声明驱动（正则只在表里写一份）参考实现已经落地，但**装载这段形状**原先住在宿主，
而且住成了两份：

| # | 宿主位置 | 内容 | 问题 |
|---|---|---|---|
| 1 | `game/commands/_declared.py`（105 行） | 读表 → 建 `CommandRegistry` → `validate` → `declared(key)` 接平台装饰器 → 目录 | 表路径、注册动作与「fail-closed 口径」焊死在一起 |
| 2 | `game/commands/_registry.py`（74 行） | 从**同一份表**再派生一次 `COMMAND_REGEX`（自述「不 import 框架，便于标准库直载」） | 合并语义**抄了第二遍**（`(?:a)|(?:b)`），靠一个测试盯着防漂 |
| 3 | 两处的错误处理 | 一处「表坏了抛错」，另一处「表坏了返回空表」 | 「配了不生效」只在其中一条路径上静默 |

把「指令 / 前缀 / 平台装饰器」这些取值拿掉，剩下的形状在任何游戏里都成立 —— 按判据这是形状。

## 形状

```python
from saintess_engine.command import CommandSpecSource

src = CommandSpecSource("data/command_specs.json", name="mygame.commands")
src.pattern_map()      # {key: 合并正则}（多条 → (?:a)|(?:b)）
src.keys()             # 声明顺序的 key
src.spec("weekly")     # 一条声明的细节；表里没有 → KeyError（fail-closed，别让指令静默消失）
src.get("weekly")      # 软取：缺 → None
src.catalog()          # {分类: [声明, ...]}（仅 visible，组内保持 order）
src.reload()           # 丢缓存重建（改表要生效时）

# 「只能标准库直载」的薄表场景：纯函数，不读盘、不带动平台
pattern_map_from_table({...})
```

## 铁律

1. **fail-closed**：表缺失 / 为空 / JSON 坏 / key 重复 / 正则非法 / 未声明有效正则 → **抛错**，
   不静默降级（`version.py` 同名条款）。门禁里配了反证：坏输入**不是**返回空表。
2. **单一来源**：有效表与注册表同源 —— `pattern_map() == {k: spec.combined()}`，门禁锁死；
   宿主不再需要第二份合并实现（`pattern_map_from_table` 给的正是同一份语义）。
3. **纯派生**：`pattern_map_from_table()` 不读盘、不 import 平台相关代码（门禁 ⑤ 扫源码）。
4. **合并语义与既有实现逐字一致**：单正则逐字保留；多条 → `(?:a)|(?:b)`；空串滤掉、
   空白串**保留**（它是合法正则）—— 门禁用**独立实现**对 194 条真声明逐条对拍。
5. 表的内容（哪条指令、什么正则、什么分类）**不进引擎**：引擎只认形状。

## 门禁

`tests/test_command_spec_loader.py` —— 34 条断言：派生语义（含真数据 194 条逐条对拍独立实现）/
与注册表同源 / fail-closed 六种坏输入全拦（含反证）/ 装载器懒构建与 `reload` / 目录分组与 order /
源码内无宿主与游戏字样。
