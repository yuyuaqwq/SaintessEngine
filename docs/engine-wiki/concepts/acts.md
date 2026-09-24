# 动作序列（`saintess_engine.acts`）

**一句话**：把「一组动作按序执行」这件事收成一个形状 —— 内容侧只声明*做什么*（动词 + 实参），
引擎负责*怎么跑*（登记 / 排序 / 取值 / 短路 / 装配期 fail-closed）。

## 为什么有它

机制、被动、触发这类内容，实现里长成一族同构的函数：

```python
# 每条机制一个函数，各自手写同一套样板
def some_passive(battle, caster, target, params, logs):
    ctx = getattr(battle, "_fire_ctx", None) or {}
    actor = ctx.get("actor") or caster
    if actor is None:
        return
    key = params.get("key") or "default_key"
    cap = cap_of(actor, key)
    if cap <= 0:
        return
    ef = actor.setdefault("effects", {})
    if not isinstance(ef.get(key), dict):
        ef[key] = {}
    ef[key]["stacks"] = float(cap)
    logs.append(_T.text("some.slot", ...))
```

把「动作是什么」拿掉之后，剩下的是四件通用的事：

| 事 | 本形状怎么做 |
|---|---|
| **登记** | 动词名 → 实现（`acts.verbs`，对象共享，就地改即刻生效） |
| **排序** | 按声明序逐条执行，返回值按序收 |
| **取值** | 每个动词的实参由声明节点**现取**（复用 `conditions.declarative` 的节点编译，不另造语法） |
| **短路** | 某步 `stop_if` 为真即停；整条 `when` 为假 ⇒ 不执行 |

## 用法

```python
from saintess_engine.acts import Acts, UnknownVerb

acts = Acts()

@acts.register("stacks_to_cap")                     # 动词实现 = 内容侧的事
def _stacks_to_cap(ctx, of=None, key=None, default=None):
    ...
    return {"key": key}

acts.verbs["say"] = _say                            # 直接写表也行

plans = acts.compile_table({
    "rule_one": {
        "on": "evt_alpha",                          # 事件名：只是标记，谁订阅谁负责
        "seq": [
            {"verb": "stacks_to_cap", "of": "actor",
             "key": {"field": [{"key": "params"}, {"key": "key"}]},
             "default": "k0"},
            {"verb": "say", "slot": "slot_alpha"},
        ],
    },
})

plans["rule_one"].run({"params": {"key": "k0"}, "actor": actor})   # → [每步返回值, …]
```

**调用约定（只有一种）**：每个动词调一次，签名 `verb(ctx, **实参)` —— `ctx` 原样透传
（本形状不读它的任何字段），实参是声明里那一项**逐值求值后**的结果。

## 装配期 fail-closed

**在 `compile` / `compile_table` 里就报，不留到运行期**：

| 情况 | 结果 |
|---|---|
| 表 / 条目不是映射、`seq` 缺失 / 空 / 含非映射条目、步缺非空 `verb` | `SpecError` |
| `verb` 名的动词没登记 | `UnknownVerb`（点名 + 列出已登记） |
| `when` / `stop_if` / 实参节点编译失败 | `SpecError`（原样带上底层报错） |

**运行期口径**：`when` 为假 ⇒ **不执行、返回空列表**（不是 `None`，也不是「跑一半」）；
动词抛异常 ⇒ **原样上抛**（不吞、不「尽力而为」、不接着跑后面的步骤）。

## 与其它形状的分工

| 要做的事 | 用哪个形状 |
|---|---|
| 条件 / 谓词（`when`、`stop_if`、实参节点） | `conditions.declarative`（本形状直接复用其节点编译） |
| 算出来的数（乘区 / 减法 / 求和） | `formula`（声明式公式表）或**动词内部** |
| 事件从哪来 | 不管 —— 事件总线 / 战斗触发点 / 消息匹配各自负责；`on` 只是标记 |
| 动作本身 | 动词（内容侧注册；引擎不认识任何动词名） |

## 有意不做的事

* **不做默认动词 / 兜底动词**：没有内置动词表、没有「未知名就跳过」的分支。
* **不做全局注册表**：`compile_table` 返回普通 `dict`，谁用谁存（形状不带模块级状态）。
* **不做第二条取值语法**：实参节点交给 `conditions.declarative`。
* **不做算术**：本形状只取值、不演算（要算的数走公式表或动词内部）。
* **不做重试 / 回滚 / 事务**：一步失败即上抛（要事务用 `store`）。
* **不做日志**：要留痕的动词自己记账，或用 `log` 门面。

## 活样板（数据包侧怎么落地）

`games/orlandia`（《奥兰迪亚》）的 **P2 试点**把 5 个重复度高的机制动作换成了这个形状：

```text
声明表   content/rules/mech_seq_{weapon,class}.json
动词     content/mech/seq_verbs_{weapon,class}.py   （按「操作」命名，可被多条机制复用）
执行壳   content/mech/seq_plans.py                  （ctx 形状 · run() · 装配期 load_plans()）
装配点   content/apply.py::install_engine() 里一行 load_plans()
门禁     tests/test_mech_seq_frozen.py（60 条行为冻结：换实现不许换行为）
```

★ 实测教训（值得后来者知道）：**这套形状省的是「每条机制的样板」，不是行数** —— 5 个动作的
体量上，动词的一次性投资摊不薄，净行数是**增加**的；它真正的收益在「机制从代码变成数据」
（可 diff、可给编辑器编、换游戏可复用）+ 装配口径统一（fail-closed）。
按操作命名动词、让多条机制共用，是摊薄投资的关键。
