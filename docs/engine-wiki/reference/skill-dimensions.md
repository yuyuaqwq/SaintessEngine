# 技能 7 维（E5）

> **形状归属**：**住包**（`<pkg>/schemas/skill.schema.json` + `<pkg>/editor/domains.json` 的 `skills` 域声明）。
> **引擎默认域集不新增「技能」域** —— 框架 `schemas/skill.schema.json` 那份只作**回退副本**。
> 引擎侧 E5 只补两样：`_validators.segment_of / layer_of` 两个守卫 + `segment_plan_fn` 这个 hook。

---

## 1. 七个维度

| # | 维度 | 字段 | 类型 | 取值 | 引擎端 |
|---|---|---|---|---|---|
| 1 | 冷却 | `cd` | integer | `≥ 0`（单位 = 刻） | 已读 |
| 2 | 第一段耗时 | `cast` | number / `{base}` / str | `≥ 0` | ★ 见 §2 |
| 3 | 第二段耗时 | `recover` | number / `{base}` / str | `≥ 0` | ★ 见 §2 |
| 4 | 射程 | `range` | integer | `≥ 1`（1 = 贴身） | 已读（与目标 `rank` 比大小） |
| 5 | 资源消耗 | `mp` + `res_cost` | integer + `{str: integer}` | `≥ 0` | 已读 |
| 6 | 威力 | `power` | number | `≥ 0` | 已读 |
| 7 | 功能性 | **扁平键并集** | 各键自带 | 见下 | 已读（分散） |

### `func` 维：**不新造容器**

`func` **不是**一个数组字段，而是**引擎既有协议键的任意子集**（扁平写在条目顶层）：
`kind_override` · `effect` · `mech` / `mech_val` / `mech2` / `mech2_val` · `buff_turns` · `hits` ·
`aoe` · `element` · `target` · `summon` · `lifesteal` · `hp_pct`。

> **为什么**：引擎的读点已经散在这些键上；另造 `func: [...]` 会立刻产生**双源**（要同步两处）。
> 「功能越强 ⇒ 伤害 PE 越低」的**量化不进引擎**：`K_func` 由内容侧给，门禁（E3）只做结果校验。

---

## 2. 两段耗时的三种形态（★ 引擎侧唯一的语义区分点）

| 形态 | 例子 | 语义 | 吃速度模型吗 |
|---|---|---|---|
| `str` | `"skill"` | **行动类别名** | ✅ 吃（按类别取基准） |
| `number` | `0.5` | **绝对秒** | ❌ **绕过**速度/施法急速模型 |
| `{"base": n}` | `{"base": 0.8}` | **基准秒** | ✅ 吃（过内容侧时间模型） |

**为什么要区分**：混用会让同一条数值在"吃不吃速度"上不确定 —— 基准 0.5 在 `spd=100` 下 = 0.5 秒、
在 `spd=400` 下 = 0.25 秒；而数字 `0.5` 永远是 0.5 秒。

**引擎侧落点**：
- 守卫 `_validators.segment_of(value, label)`：只校验**形状**（四形态 + `{"base":…}` 只允许一个键）。
  **校验不了"类别名合不合法"** —— 类别集在内容侧时间模型里，枚举收紧属内容侧 schema 的职责。
- 守卫 `_validators.layer_of(value, label, *, default=None)`：射程层号（整数 ≥ 1）。
  ★ 补掉旧调用点 `int(info.get("reach") or 3)` 遇到 `"near"` 抛**裸 ValueError**（栈里看不出哪条）的硬伤。
- hook `segment_plan_fn`：`fn(actor, action, entry) -> {"cast": …, "recover": …} | None`。
  **不配 = 不存在**（引擎连问都不问）；配了但返回 `None` ⇒ 落回既有「行动类别基准」路径。

---

## 3. schema 住包的三个理由

1. **口径已定死**：`package-format.md` 写明「加一个域 = 改包内 3 个文件，框架一行不改」。
2. **它过不了「引擎域」的判据**：`domains.py` 内置集只有 8 个引擎域，判据是「声明里的键/取值全是引擎协议词」；
   而 7 维里 `range`（射程怎么影响战斗）、`func`（效果清单）、`power` 的取值域都是**内容语义**。
3. **放框架会撞门禁**：`test_no_game_vocabulary.py` 的判定项 A 要求 `schemas/*.json` 的 `enum` 取值**不得含非 ASCII**；
   新游戏的射程档名与功能性枚举都是中文 ⇒ 放框架要么过不了门禁，要么被迫退回英文 token 而与内容侧词表**分叉**。

### 新包相对框架回退副本的两处**收紧**

| 项 | 框架回退副本 | 新包 | 效果 |
|---|---|---|---|
| `additionalProperties` | `true` | **`false`** | 字段名写错当场红 |
| `cast`/`recover` 的 str 分支 | 裸 `string` | **`enum`**（4 个行动类别名） | 「把枚举名当耗时」被拦下 |

> ★ 那个 `enum` 与内容侧 `TIME_MODEL.cast` 的键集**是同源点，改一处要改两处** —— 已登记为待同步项。

### 一条实测教训

`cast`/`recover` 的 `anyOf` 必须**内联**，**不能用 `$ref: "#/$defs/segment"`** ——
引擎在未装 `jsonschema` 时走**最小校验器**（`editor/validate.py`），它**不解析 `$ref`**。
