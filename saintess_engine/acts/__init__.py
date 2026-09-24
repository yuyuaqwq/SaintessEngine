# -*- coding: utf-8 -*-
"""动作序列形状（Acts）—— 把「一组动作按序执行」从项目里拎出来。

**形状在哪**：机制 / 被动 / 触发这类内容，实现里长成一族同构的函数 ——
「读参数 → 逐条判 → 写状态 → 发文案」，一条机制一个函数、各自手写同一套样板
（`params.get(...) or 默认值` 的防线、`if not x: return` 的空跑、状态字段的 setdefault）。
把「动作是什么」拿掉之后，剩下的只是四件通用的事：

  * **登记** —— 动词名 → 实现（`{名字: 可调用}`，名字由调用方给）
  * **排序** —— 按声明序逐条执行，结果按序收（同 `sinks` 声明序那套口径）
  * **取值** —— 每个动词的实参由声明节点**现取**（复用 `conditions.declarative` 的节点编译，
    不另造第二套取值语法）
  * **短路** —— 某步的 `stop_if` 为真即停（后续步骤不执行）

**用法**::

    from saintess_engine.acts import Acts, UnknownVerb

    acts = Acts()

    @acts.register("pick")                          # 动词实现 = 内容侧的事
    def _pick(ctx, of=None, key=None, default=None):
        ...
        return {"key": key}

    acts.verbs["note"] = _note                      # 直接写表也行（对象共享，就地改即刻生效）

    tables = acts.compile_table({
        "rule_one": {
            "on": "evt_alpha",                       # 事件名：只是标记，谁订阅谁负责
            "seq": [
                {"verb": "pick", "of": "owner",
                 "key": {"field": [{"key": "params"}, {"key": "k"}]},   # 步链：ctx["params"]["k"]
                 "default": "k0"},
                {"verb": "note", "slot": "slot_alpha"},
            ],
        },
    })

    ctx = {"params": {"k": "k0"}, "owner": who}
    tables["rule_one"].run(ctx)                      # → [每步返回值, ...]（按声明序）

**调用约定（只有一种）**：每个动词调一次，签名 ``verb(ctx, **实参)`` —— `ctx` 原样透传
（本形状不读它的任何字段），实参是声明里那一项**逐值求值后**的结果。返回值原样收进结果列表。

**装配期 fail-closed**（`compile` / `compile_table` 里就报，不留到运行期）::

    · 表 / 条目不是映射（Mapping）                  → SpecError
    · `seq` 缺失 / 为空 / 含非映射条目               → SpecError
    · 步里没有 `verb`（字符串、非空）                → SpecError
    · `verb` 名的动词没登记                          → UnknownVerb（点名 + 列出已登记）
    · `when` / `stop_if` / 实参节点编译失败          → SpecError（原样带上底层报错）

**运行期口径**：`when` 为假 ⇒ **不执行、返回空列表**（不是 `None`，也不是「跑一半」）；
动词抛异常 ⇒ **原样上抛**（不吞、不「尽力而为」、不接着跑后面的步骤）。

**零知识**：本形状不认任何具体动词名、不认事件名、不解释实参含义 —— 三样全由调用方给。
事件从哪来（事件总线 / 战斗触发点 / 消息匹配）不管：`on` 是**标记**，不在这里做分发。

**有意不做的事**
----------------
* **不做默认动词 / 兜底动词**：没有内置动词表、没有「未知名就跳过」的分支。
* **不做全局注册表**：`compile_table` 返回普通 `dict`，谁用谁存（形状不带模块级状态）。
* **不做第二条取值语法**：实参节点交给 `conditions.declarative.compile_spec`（同一套 `field` /
  `const` / `op` 节点 —— `field` 的步是字典：`{"field": [{"key": "params"}, {"key": "key"}]}`），
  本形状只管「什么时候取、取来给谁」。
* **不做算术**：本形状**只取值、不演算** —— 需要算出来的数（乘区 / 减法 / 求和）走**动词内部**
  或**声明式公式表（`saintess_engine.formula`，E1）**；节点语言本身只有比较 / 布尔 / 长度 / 取整
  （`conditions.declarative` 的口径），别在这里加运算符。
* **不做重试 / 回滚 / 事务**：一步失败即上抛，已执行步骤的副作用由调用方负责（要事务就用 `store`）。
* **不做日志**：要留痕的动词自己记账，或用 `saintess_engine.log` 门面。
"""
from __future__ import annotations

from collections.abc import Callable, Mapping

from ..conditions.declarative import SpecError, compile_spec

__all__ = ["Acts", "Plan", "UnknownVerb", "SpecError"]


class UnknownVerb(LookupError):
    """装配期遇到没登记的动词名（fail-closed：不静默跳过、不退回默认实现）。"""


# 声明节点的保留键（与 conditions.declarative 的节点形状一致）——
# 出现这些键的映射按「节点」编译；不含这些键的映射按「字面量」递归重建。
_NODE_KEYS = frozenset({"const", "field", "op"})


def _verb_name(name) -> str:
    """动词名校验：不透明字符串，但必须非空（空名字登不进表，也点不了名）。"""
    if not isinstance(name, str):
        raise TypeError(f"动词名必须是字符串，收到 {type(name).__name__}")
    if not name.strip():
        raise ValueError("动词名不能为空")
    return name


def _is_node(value) -> bool:
    """这个值是不是声明节点？（单保留键、或带 `op` 的映射）"""
    if not isinstance(value, Mapping):
        return False
    keys = set(value)
    if "op" in keys:
        return True
    return len(keys) == 1 and bool(keys & _NODE_KEYS)


def _value(value, where: str):
    """实参值 → `fn(ctx) -> 值`。

    * 节点形状（`const` / `field` / `op`）⇒ 走 `conditions.declarative.compile_spec`
    * 映射 / 序列 ⇒ **递归重建**（字面量里的每一层都可以嵌节点）
    * 其余 ⇒ 常量
    """
    if _is_node(value):
        try:
            return compile_spec(value)
        except SpecError as e:
            raise SpecError(f"{where} 的取值节点不合法：{e}") from e
    if isinstance(value, Mapping):
        sub = {k: _value(v, f"{where}.{k}") for k, v in value.items()}
        return lambda ctx, _s=sub: {k: fn(ctx) for k, fn in _s.items()}
    if isinstance(value, (list, tuple)):
        sub = [_value(v, f"{where}[{i}]") for i, v in enumerate(value)]
        return lambda ctx, _s=sub, _t=type(value): _t(fn(ctx) for fn in _s)
    return lambda ctx, _v=value: _v


class Plan:
    """一条**已编译**的动作序列（不可变：`name` / `on` / 步表都在构造时冻结）。

    执行 = `run(ctx)`：`when` 为假 ⇒ 空列表；否则按声明序逐条调动词，结果按序收。
    """

    __slots__ = ("name", "on", "steps", "_when")

    def __init__(self, name: str, on, steps, when_fn) -> None:
        self.name = name
        self.on = on
        self.steps = tuple(steps)          # ((动词名, 动词, {实参名: 取值fn}, 短路fn|None), ...)
        self._when = when_fn

    def run(self, ctx, *, out: list | None = None) -> list:
        """执行序列；返回结果列表（给了 `out` 就往它里追加，不新建）。

        * `when` 给了且为假 ⇒ 返回 `out`（可能是空列表）
        * 每步：先取实参（按声明序）再调动词；`stop_if` 为真 ⇒ 记完这一步就停
        * 动词异常**原样上抛**
        """
        result: list = [] if out is None else out
        if self._when is not None and not self._when(ctx):
            return result
        for verb_name, verb, kwargs, stop_if in self.steps:
            args = {k: fn(ctx) for k, fn in kwargs.items()}
            result.append(verb(ctx, **args))
            if stop_if is not None and stop_if(ctx):
                break
        return result

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "Plan(name=%r, on=%r, steps=%d)" % (self.name, self.on, len(self.steps))


class Acts:
    """动作序列的**登记口 + 编译器**：动词表可变，编译出的 `Plan` 不可变。

    动词表是**对象本身**（`acts.verbs["x"] = fn` 即刻生效，与 `Conditions` 的表同口径）；
    编译只做一次校验 —— 编完之后再往动词表里加动词，不会回头改已编好的 `Plan`。
    """

    def __init__(self, *, verbs: Mapping[str, Callable] | None = None) -> None:
        self._verbs: dict = {}
        if verbs is not None:
            if not isinstance(verbs, Mapping):
                raise TypeError(f"verbs 必须是「动词名 → 可调用」的映射，收到 {type(verbs).__name__}")
            for name, fn in verbs.items():
                self._set(name, fn)

    # ------------------------------------------------------------ 动词表
    @property
    def verbs(self) -> dict:
        """动词表（**对象本身**，可直接读写：`acts.verbs["x"] = fn` / `pop` 即刻生效）。"""
        return self._verbs

    def register(self, name: str):
        """装饰器：把被装饰的可调用登记为动词 `name`。"""
        def _wrap(fn: Callable) -> Callable:
            self._set(name, fn)
            return fn
        return _wrap

    def _set(self, name, fn) -> None:
        key = _verb_name(name)
        if not callable(fn):
            raise TypeError(f"动词 {key!r} 必须是可调用的，收到 {type(fn).__name__}")
        self._verbs[key] = fn

    # ------------------------------------------------------------ 编译
    def compile(self, spec, *, name: str | None = None) -> Plan:
        """一条声明 → `Plan`（形状不对 / 动词未登记 / 节点编译失败 ⇒ 当场报错）。"""
        if not isinstance(spec, Mapping):
            raise SpecError(f"动作声明必须是映射，收到 {type(spec).__name__}")
        pid = name or spec.get("id")
        if not isinstance(pid, str) or not pid.strip():
            raise SpecError("动作声明必须有非空 `id`（或用 compile(spec, name=...) 给）")

        seq = spec.get("seq")
        if not isinstance(seq, (list, tuple)) or not seq:
            raise SpecError(f"{pid}: `seq` 必须是非空列表，收到 {type(seq).__name__}")

        when_fn = None
        if "when" in spec and spec["when"] is not None:
            try:
                when_fn = compile_spec(spec["when"])
            except SpecError as e:
                raise SpecError(f"{pid}: `when` 不合法：{e}") from e

        steps = []
        for i, step in enumerate(seq):
            where = f"{pid}.seq[{i}]"
            if not isinstance(step, Mapping):
                raise SpecError(f"{where} 必须是映射，收到 {type(step).__name__}")
            vname = step.get("verb")
            if not isinstance(vname, str) or not vname.strip():
                raise SpecError(f"{where} 缺少非空 `verb`")
            vname = _verb_name(vname)
            if vname not in self._verbs:
                raise UnknownVerb(
                    "%s 的动词未登记：%r（已登记：%s）"
                    % (where, vname, sorted(self._verbs) or "无"))
            kwargs = {k: _value(v, f"{where}.{k}")
                      for k, v in step.items() if k not in ("verb", "stop_if")}
            stop_if = None
            if step.get("stop_if") is not None:
                try:
                    stop_if = compile_spec(step["stop_if"])
                except SpecError as e:
                    raise SpecError(f"{where}.stop_if 不合法：{e}") from e
            steps.append((vname, self._verbs[vname], kwargs, stop_if))

        return Plan(pid, spec.get("on"), steps, when_fn)

    def compile_table(self, table: Mapping) -> dict:
        """声明表 `{id: 声明}` → `{id: Plan}`。**任一条不合法 ⇒ 整表不装**（先全编再返回）。"""
        if not isinstance(table, Mapping):
            raise SpecError(f"动作声明表必须是映射，收到 {type(table).__name__}")
        out: dict = {}
        for pid, spec in table.items():
            if not isinstance(pid, str) or not pid.strip():
                raise SpecError(f"动作声明的键必须是非空字符串，收到 {pid!r}")
            out[pid] = self.compile(spec, name=pid)
        return out

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "Acts(verbs=%d)" % (len(self._verbs),)
