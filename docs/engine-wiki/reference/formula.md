# `formula` · 声明式公式表

> **可拔插形状**：不配 = 不存在。引擎不装配 `formula_table_fn` 时，本形状零影响。
> **归属**：`saintess_engine/formula/__init__.py`（E1，2026-09-21）
> **为什么建**：`_HOOKS["formulas"]` 原来要内容侧交一个 **Python 模块对象**（实测被消费 13 个方法）
> ⇒ 想给新游戏换一套数值公式，必须写 Python。本形状让内容侧**只写一张 JSON 声明表**。

---

## 1. 形状总览

域（`kind: rules`）：`{条目 id: 条目对象}`，另可带一个保留键 `$const`（常量段，引擎不解释语义只取值）。

三类条目用 `kind` 区分：

| `kind` | 语义 | 专有字段 |
|---|---|---|
| `formula` | 单条表达式 | `expr` |
| `aggregate` | 对**多变来源列表**求和 / 连乘 | `op`(`sum`\|`prod`) · `over` · `item_expr` · `combine` |
| `chain` | 多步流水线（每步可引用**前面所有步**的结果） | `steps[]` · `random` |

**通用字段**：`kind` · `label` · `version`（≥1，缓存键，不做旧版兼容分支）· `vars`（变量域）·
`params`（`{名: 数 | {ref}}`）· `returns`（`number`\|`int`\|`pct`\|`tick`）· `clamp`（`[lo,hi]`，`null` = 不限）·
`floor`/`cap` · `guard`（**输入变量级**钳制，求值前施加）· `round`（默认 6）· `random` · `when` · `note`。

> ★ `returns` 在 `chain` 上**可省**（取最后一步的 `returns`）—— 因为顶层写是冗余。

---

## 2. `params.ref` 的四种前缀

| 前缀 | 例子 | 解析 |
|---|---|---|
| `const.` | `"ref": "const.k_rate_base"` | 同一份声明文件的 `$const` 段 |
| `formula.` | `"ref": "formula.k_def"` | 引用**另一条公式**（求值时先算它；**无环校验**：拓扑排序，成环 → 装配期报错） |
| `skeleton.` | `"ref": "skeleton.reduce.cap"` | 引用**既有骨架表**（`formula_skeleton_fn`）⇒ 不制造第二份参数源 |
| `param.` | `"ref": "param.curve.k_lv"` | 引用内容侧任意表（装配点经 `ctx["tables"]` 传入，引擎只按路径取、不解释） |

**取不到就报错**（点名路径 + 候选集），**不静默当 0**。

---

## 3. 校验规则 V1–V12（全部 fail-closed，异常 `FormulaDeclError(ValueError)`）

| # | 规则 |
|---|---|
| V1 | `kind` ∈ 三值；`returns` ∈ 四值 |
| V2 | 条目 id 非空唯一；**`formula.` 引用不成环** |
| V3 | `version` ≥1 且为 int |
| V4 | `expr` / `item_expr` / `combine` 能被 `expr.compile_expr` 编译通过（语法错装配期现形） |
| V5 | ★ **表达式里的变量名 ⊆ `vars` ∪ 步 id ∪ `params` 名 ∪ `guard`/`random` 注入名** |
| V6 | `params.ref` 前缀 ∈ 四种且**能解析到值** |
| V7 | 数值（`params` 常量 / `clamp` / `guard` / `random.pct`）必须是**有限数** |
| V8 | `clamp` 的 `lo ≤ hi`；`floor`/`cap` 与 `clamp` 不同时出现 |
| V9 | `aggregate.over` 必须存在于 `vars` |
| V10 | `chain.steps` 非空；步 id 非空且唯一；每步**恰好**有 `expr` 或 `use` 之一 |
| V11 | `round ≥ 0` |
| V12 | `when` 结构合法（映射或映射数组） |

> **V5 为什么必须有**：`expr.eval_expr` 对**未知变量取 0** ⇒ 表达式里拼错一个变量名会**静默算成 0**，
> 是最难查的一类错。V5 把它堵在装配期。

---

## 4. 接口

| 方法 | 签名 | 说明 |
|---|---|---|
| `FormulaTable.from_decl` | `(table: dict, *, skeleton_fn=None) -> FormulaTable` | 跑 V1–V12 + 预编译所有表达式（复用 `expr` 的编译缓存） |
| `.ids()` | `() -> list[str]` | 全部条目 id |
| `.vars_of` | `(id) -> frozenset[str]` | 该条的变量域（调用方传值前就知道要准备什么） |
| `.eval` | `(id, vars, *, ctx=None) -> float \| int` | 单条求值（`formula` / `aggregate`） |
| `.run` | `(id, vars, *, ctx=None) -> (value, list[StepRow])` | 跑 `chain`；返回最终值 + **逐步中间量** |
| `.check` | `(id, vars) -> list[str]` | 缺变量体检（**不抛**） |
| `.wrong_vars` | `(id, vars) -> list[str]` | 多变量体检（防拼写漂移，**不抛**） |

`StepRow` = `{step, label, in, out, delta_pct}`，可直接打印成"乘区链逐项"。

**求值纪律（写死）**：`eval` / `run` **不做 try/except 吞异常** —— 声明错在装配期已被 V1–V12 拦下；
运行期再出错 = 真 bug，必须现形。

**`ctx` 结构**（引擎构造、内容侧填）：`{"tables": {域: {键: 值}}, "flags": {...}}`。

---

## 5. 一个最小例子

```python
from saintess_engine.formula import FormulaTable

t = FormulaTable.from_decl({
  "$const": {"k_rate_base": 300, "k_rate_per_lv": 30},
  "k_def": {"kind": "formula", "version": 1, "vars": ["level"],
            "params": {"base": 100, "per_lv": 20},
            "expr": "base + per_lv * level", "returns": "number"},
  "act_time": {"kind": "formula", "version": 1, "vars": ["base", "spd"],
               "params": {"spd_ref": 100, "alpha": 0.5},
               "guard": {"spd": {"floor": 1, "cap": 300}},
               "expr": "base * (spd_ref / spd) ^ alpha", "returns": "tick"},
  "damage": {"kind": "chain", "version": 1,
             "vars": ["base", "mult", "dr", "crit_mult"],
             "steps": [
               {"id": "raw", "expr": "base * mult"},
               {"id": "after_dr", "expr": "raw * (1 - dr)"},
               {"id": "final", "expr": "after_dr * crit_mult", "returns": "int", "floor": 1}]},
})

t.eval("k_def", {"level": 50})            # 1100.0
t.eval("act_time", {"base": 1.0, "spd": 200})   # 0.707107  ← 用 `^` 幂
t.run("damage", {"base": 100, "mult": 1.5, "dr": 1/3, "crit_mult": 1.0})
# → (100, [StepRow(raw=150.0), StepRow(after_dr=100.0), StepRow(final=100)])
```

---

## 6. 已登记的边界（实测发现 · 本批不动）

`expr` 的 tokenizer 对**孤立的二元操作符**（前一个 token 已是操作数时出现的 `*` / `/` / `+`）
是**静默忽略**的 —— 例：`"a +* 3"` 会被当作 `a + 3` 求值，**不报错**。⇒ V4（"能编译通过"）抓不住这类笔误。

**为什么本批不动**：E1 设计的边界明写「不改 `expr/` 除 `^` 之外的任何一行」，
且改成报错会动到既有表达式的接受面（有零回归风险）。
**建议的下一轮处置**：把"孤立二元操作符"改为 `ExprError`，前置条件 = 先扫全部既有表达式串确认零命中。
