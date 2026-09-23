# `panel` · 面板栈

> **归属**：本能力**不在引擎里**（2026-09-23 起）—— 它在扩展包 `extends/ext_combat/`（`panel/`，E2，2026-09-21）。
> 数据包要用它：`game.json` 里写 `"depends": ["ext_combat"]`。
> 引擎侧只剩通用件，见 `../architecture/boundaries.md`；下文裸文件名与行号都在 `extends/ext_combat/battle/` 下。
> **可拔插形状**：不配 = 不存在。宿主不装配 `panel_layers_fn` 时，本形状零影响。
> **为什么建**：`_HOOKS["panel_fn"]` 的**形参就是游戏词汇**
> （`fn(class_name, level, equipment, tier, evolve_path, title_bonus, race)` —— 实测 8 个位置参数、6/8 是游戏词）
> ⇒ 引擎纯度缺陷；且面板聚合本体写在内容侧的 Python 里。
> 本形状把「有哪些层、每层怎么作用到哪些键」变成**声明**，形状层负责逐键合并 + 钳制 + 归因（原先是引擎里的面板聚合本体，现随包迁出）。

---

## 1. 与 `Bonus` 的边界（写死，防止两套形状互相蚕食）

| 语义 | 落哪个形状 |
|---|---|
| **面板键级合成**（atk/def/spd…） | **`PanelStack`** |
| 叠层上限的 flat 增量（`cap`） | `Bonus`（不动） |
| 技能消耗修正（`cost`，嵌套声明 `res{}` / `when[]`） | `Bonus`（不动） |
| 面板增幅的**来源标签** | `PanelStack` 层的 `src` |

---

## 2. 栈级字段

| 字段 | 类型 | 必填 | 语义 |
|---|---|---|---|
| `version` | int ≥1 | **是** | 声明版本；形状层按 `(stack_id, version)` 缓存校验结果（版本变 ⇒ 重新校验，**不做旧版兼容分支**） |
| `base.mode` | `"actor"` \| `"value"` | **是** | `actor` = 从 actor 裸字段读（调用方按 `base.keys` 取值传入）；`value` = 用 `base.value` 常量 |
| `base.keys` | str[] | `mode=actor` 时**是** | **必须显式列键**（零默认值口径：形状层不猜键集） |
| `base.value` | `{键: 数}` | `mode=value` 时**是** | 常量基础值 |
| `layers` | Layer[] | **是**（可 `[]`） | 有序；顺序即合并序 |
| `emit.int_keys` | str[] | 否 | 这些键最终落 `int` |
| `emit.round` | int ≥0 | 否（默认 6） | 其余键的小数位（对齐 `Bonus` 的 `round(6)`） |
| `audit.targets` / `tolerance` / `max_share` | 映射/数 | 否 | ★ **只被打印与门禁读**，不参与求值 |

---

## 3. 层字段

| 字段 | 类型 | 必填 | 语义 |
|---|---|---|---|
| `id` | str | **是** | 层名；非空且栈内唯一 |
| `src` | str | **是** | 来源标签（打印/归因用）；纯空白 → 报错 |
| `group` | str | **是** | **归因分组**（来源占比按它汇总；内容侧词） |
| `mode` | `"add"` \| `"mul"` \| `"set"` | **是** | 合并模式 |
| `keys` | str[] \| `"*"` | **是** | 本层作用的键；`"*"` = 基础键全集 |
| `values` | `{键: 数}` | 与 `ref` 二选一 | 常量系数/加数 |
| `ref` | str | 与 `values` 二选一 | 取数路径 `"$<域>.<键>"`，只从 `ctx["refs"]` 取；**取不到 → 报错**（不静默 0） |
| `apply` | `"per_key"` \| `"whole"` | 否（默认 `per_key`） | `mul` 时：逐键乘 / 用 `values["*"]` 一个系数乘全键 |
| `order` | int | 否（默认数组下标） | 显式层序；重号 → 报错 |
| `weight` | int | 否（默认 0） | **只用于**：① `set` 竞争（同键多个 `set` ⇒ 大者胜，同则声明序后者胜）；② 归因打印排序。**不改 add/mul 的结果** |
| `cap` / `floor` | number | 否 | 层内合并后对本层作用键钳上下界。**`set` 层不钳** |
| `when` | object \| object[] | 否（缺省恒真） | 对象 = 逐条 `key==值`（AND）；数组 = 任一命中（OR）。**写了但值不认识 → 按不命中处理（fail-closed）** |
| `status` | `"active"` \| `"inactive"` | 否（默认 `active`） | `inactive` = 整层跳过（**仍是声明，不是删除**） |

---

## 4. 求值顺序（逐键）

```
v = base(key)                                   # 见 base.mode；缺失键 = 不出现（不补 0）
for L in sorted(layers, key=(order, 声明序)):
    if L.status == "inactive":        continue
    if not when_ok(L.when, ctx):      continue
    if L.mode == "set":
        for k in keys_of(L): v[k] = value_of(L, k, ctx)      # 不 clamp
        continue
    for k in keys_of(L):
        c = value_of(L, k, ctx)                  # values 或 ref；取不到 → 报错
        v[k] = v.get(k, 0) + c  if add  else  v.get(k, 0) * c
        if L.cap   is not None: v[k] = min(v[k], L.cap)
        if L.floor is not None: v[k] = max(v[k], L.floor)
最后：emit.int_keys → int()；其余 → round(emit.round)
```

### 三条有意定死的语义

1. **`mul` 的键若不在基础里 ⇒ 结果 0**（与 `Bonus` 既有口径一致）。
   **不**改成"1 则不变" —— 静默把 ×0 变 ×1 = 悄悄改了数值。
2. **`cap`/`floor` 只作用于 `add`/`mul`，不作用于 `set`** —— `set` 的语义是"这层说了算"；
   钳它会让"设置值"与"声明值"不一致。要限 `set` 就把范围写进 `values`。
3. **不提供 `drop`/撤销口** —— 面板聚合是**每次全量重算**（纯函数，无状态累积）。
   层是"声明"不是"账本"；要撤销 = 改声明 / 置 `status: "inactive"`。

---

## 5. 接口

| 方法 | 签名 | 说明 |
|---|---|---|
| `PanelStack.from_decl` | `(decl: dict) -> PanelStack` | 一次校验 → 不可变对象；非法 → `PanelDeclError(ValueError)` |
| `.resolve` | `(base: dict, ctx=None) -> ResolvedPanel` | 求值。`ResolvedPanel` 是 `Mapping[str, number]` ⇒ 可直接当 dict 用 |
| `ResolvedPanel.trace` | `(key) -> list[TraceRow]` | 逐层中间量（打印数据源）；`TraceRow = {layer, src, group, mode, in, out, delta}` |
| `ResolvedPanel.shares` | `(key) -> dict[group, float]` | 按 `group` 汇总的来源占比（只算 `add` 层） |
| `cached_stack` | `(stack_id, decl) -> PanelStack` | 按 `(stack_id, version)` 缓存校验结果 |

**`ctx` 结构**：`{"refs": {域: {键: 值}}, "flags": {...}, "actor": …, "battle": …}`。
`refs` 是**不透明**的（内容侧装配点塞，形状层只按路径取）。

---

## 6. 一个最小例子

```python
from ext_combat.panel import PanelStack

st = PanelStack.from_decl({
  "version": 1,
  "base": {"mode": "value", "value": {"hp": 100, "atk": 12}},
  "layers": [
    {"id": "lv",   "src": "等级成长", "group": "base", "mode": "add",
     "keys": ["hp", "atk"], "values": {"hp": 900, "atk": 88}},
    {"id": "gear", "src": "武器",     "group": "gear", "mode": "add",
     "keys": ["atk"], "values": {"atk": 200}},
    {"id": "aff",  "src": "词条",     "group": "affix", "mode": "mul",
     "keys": ["atk"], "values": {"atk": 1.10}},
  ],
  "emit": {"int_keys": ["hp", "atk"], "round": 6},
})

p = st.resolve({})
p["hp"]        # 1000
p["atk"]       # (12 + 88 + 200) × 1.10 = 330
p.trace("atk") # 3 行：in → out → delta
p.shares("atk")# {"base": 0.303…, "gear": 0.606…}
```
