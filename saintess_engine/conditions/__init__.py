# -*- coding: utf-8 -*-
"""条件注册表（conditions）—— `key → 判定函数` 的登记与求值。

**为什么有它**：项目里「某条内容能不能过」这件事被写成了一族一族同构的注册表，
每族自带一份 `CHECKS = {}` + `@register(key)` + 一堆判定函数；家族之间只差一个字典名，
函数签名（`(ctx) -> bool`）与查表口径（未注册即视为不可用）完全一致。把「条件是干什么用的」
拿掉之后，剩下的只有三件通用的事：**登记**（key → 函数）、**查表**（有没有 / 都是哪些）、
**求值**（拿上下文判一次）。本模块只做这三件事，判定函数与上下文形状全部由内容侧给。

**用法**::

    from saintess_engine.conditions import Ctx, Conditions, UnknownCondition

    conds = Conditions()

    @conds.register("k1")            # 装饰器路
    def _c1(ctx):
        return ctx.owner == "a" and ctx.count >= 2

    def _c2(ctx):
        return ctx.flags.get("ready", False)

    conds.register("k2", _c2)        # 直接注册路（同一个注册表，两路等价）

    conds.keys()                     # ['k1', 'k2'] —— 注册序（声明序）
    conds.has("k1")                  # True
    conds.get("nope")                # None（查表口径：没有就是没有）
    conds.evaluate("k1", Ctx(owner="a", count=3))    # True
    conds.evaluate("nope", Ctx())    # 抛 UnknownCondition（fail-closed，不静默 False）
    conds.missing(["k1", "k3"])      # ['k3'] —— 供「声明了但没实现」自检

**参数校验**（fail-closed：不合法就当场报错，不把错留到求值那一刻）::

    * `key` —— 非空字符串。空串 / 非字符串 → `ValueError` / `TypeError`
      （键是内容侧给的名字，引擎不替它猜、不做任何大小写或前后缀规整）。
    * `fn` —— 可调用对象。两路注册都按这个口径校验；不可调用 → `TypeError`。

**返回值口径**（有意为之）::

    * `evaluate` 原样返回判定函数的结果，**不替内容侧做布尔归一**
      （要严格 `bool` 的内容侧函数自己 `bool(...)`；引擎改了返回值 = 悄悄换语义）。
    * `get` 是纯查表：**不调用**函数。

**有意不做的事**
----------------
* **不自带任何条件名**：内置条件表 = 空表；引擎不认任何具体条件（通用名也不行）。
* **不解释上下文**：`Ctx` 只透传字段，引擎不读、不校验、不猜字段含义。
* **不吞错**：判定函数抛出的异常原样上抛；未注册 key 抛 `UnknownCondition`
  （静默 `False` 会把「没实现」伪装成「不满足」）。
* **不做缓存 / 不做超时 / 不做重试**：一次调用一次判定，判定自己的开销由内容侧负责。
* **不做重复注册拦截**：同 key 再注册 = 覆盖（与「一个字典赋值」同口径，见 `register`）。

细节见 `Conditions` / `Ctx`。
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Callable, Iterable, Optional

__all__ = ["Conditions", "Ctx", "UnknownCondition"]


class UnknownCondition(LookupError):
    """求值一个没注册的 key —— fail-closed：点名，不静默降级成 False/None。"""

    def __init__(self, key: object = None, known: Iterable[str] = ()) -> None:
        self.key = key
        self.known = tuple(known)
        super().__init__(f"未注册的条件：{key!r}（已注册：{list(self.known)}）")


def _check_key(key: object) -> str:
    """键的口径：非空字符串（不规整、不裁剪、不猜）。"""
    if not isinstance(key, str):
        raise TypeError(f"key 必须是字符串，收到 {type(key).__name__}：{key!r}")
    if not key.strip():
        raise ValueError("key 必须非空（空键 = 无名条件，拒绝登记与求值）")
    return key


def _check_field_name(name: object) -> str:
    """字段名的口径：合法标识符（能按属性访问）。不裁剪、不规整、不猜。"""
    if not isinstance(name, str) or not name.isidentifier():
        raise ValueError(
            f"字段名必须是合法标识符，收到 {name!r}（字段名由内容侧定，引擎只做透传）")
    return name


class Conditions:
    """条件注册表：`key → 判定函数`。引擎不认任何具体条件名。

    判定函数的调用约定只有一条：`fn(ctx) -> 结果`（结果按内容侧约定当真值用）。
    `ctx` 是 `Ctx`（或内容侧自己的对象）—— 引擎一个字段都不读，只负责**透传**。

    * 登记序 = `keys()` 的顺序（同 key 再注册只换函数、**不动位置**）。
    * `register` 同时支持 `@conds.register("k")`（装饰器）与 `conds.register("k", fn)`
      （直接传）两条路；两路走的是同一处实现，校验与返回口径一致。
    * `register("k")`（不带 fn）返回装饰器；`register("k", fn)` 返回 `fn` 本身 ——
      两种形态都返回「可继续使用的那个东西」（函数或装饰器）。
    """

    def __init__(self) -> None:
        self._fns: dict = {}

    # ---------------------------------------------------------------- 登记
    def register(self, key: str, fn: Optional[Callable] = None):
        """登记 `key` → `fn`；`fn` 省略时返回装饰器（`@conds.register("k")`）。

        * `fn` 省略 → 返回装饰器，装饰时把函数登记进去并**返回函数本身**。
        * `fn` 给了 → 直接登记，返回 `fn`。
        * `key` 非字符串 / 空串 → `TypeError` / `ValueError`；`fn` 不可调用 → `TypeError`。
        * 同 key 再注册 = **覆盖**（登记序保持首次位置）—— 与「一个字典赋值」同口径，
          引擎不替内容侧拦重复（重复与否是内容侧的自检，用 `missing` / 审计去看）。
        """
        cond_key = _check_key(key)
        if fn is None:
            def deco(func: Callable) -> Callable:
                self._put(cond_key, func)
                return func
            return deco
        self._put(cond_key, fn)
        return fn

    def _put(self, key: str, fn: Callable) -> None:
        if not callable(fn):
            raise TypeError(f"判定函数必须可调用，收到 {type(fn).__name__}（key={key!r}）")
        self._fns[key] = fn                         # 覆盖不改登记序（dict 语义）

    # ---------------------------------------------------------------- 查表
    def get(self, key: str) -> Optional[Callable]:
        """取判定函数；没登记 → None。**纯查表，不调用**。"""
        return self._fns.get(_check_key(key))

    def has(self, key) -> bool:
        """有没有这个 key；键不合法（非字符串 / 空串）→ False（只是查询，不报错）。"""
        try:
            return _check_key(key) in self._fns
        except (TypeError, ValueError):
            return False

    def __contains__(self, key) -> bool:
        """`key in conds` ≡ `conds.has(key)`（同一口径）。"""
        return self.has(key)

    def __len__(self) -> int:
        return len(self._fns)

    def keys(self) -> list:
        """已注册的 key，**声明序**（注册顺序；同 key 覆盖不动位置）。"""
        return list(self._fns)

    def missing(self, needed: Iterable[str]) -> list:
        """`needed` 里**没实现**的那些，按传入顺序（重复项各算一次）。

        供「内容侧声明了一串条件名，但实现没跟上」的自检 —— 精确点名，不糊成计数。
        """
        if isinstance(needed, (str, bytes, bytearray)):
            raise TypeError("needed 必须是一串 key，不是单个字符串（要单个就用 has/missing([k])）")
        out = []
        for key in needed:
            if not self.has(key):
                out.append(key)
        return out

    # ---------------------------------------------------------------- 求值
    def evaluate(self, key: str, ctx) -> bool:
        """用 `ctx` 判一次 `key`。**返回值 = 判定函数的原样返回**。

        * 未注册 → `UnknownCondition`（点名 key，并把已注册清单带上）——
          **绝不静默降级成 False**：「没实现」与「不满足」必须分得开。
        * 查表发生在调用**之前**：未注册时判定函数**一次都不会被执行**。
        * 判定函数抛错 → **原样上抛**（内容侧的 bug 当场暴露，不许吞）。
        """
        fn = self._fn_of(key)
        return fn(ctx)                              # 透传：引擎不读 ctx 的字段

    def _fn_of(self, key: str) -> Callable:
        fn = self._fns.get(_check_key(key))
        if fn is None:
            raise UnknownCondition(key, self._fns)
        return fn

    # ---------------------------------------------------------------- 门面
    def __repr__(self) -> str:
        return f"Conditions({list(self._fns)!r})"


class Ctx:
    """判定上下文外壳：把「主体 / 组 / 统计 / 进度」等**由内容定名的字段**透传。

    引擎不读、不校验、不猜任何字段含义 —— 它只保证两件事：

    * **给什么有什么**：`Ctx(owner="a", count=3)` → `ctx.owner` / `ctx.count` 属性访问。
    * **缺字段不静默**：没给的字段访问时抛 `AttributeError`（不回落 None、不回落默认值）。
    * `ctx.fields` 是**只读视图**（`MappingProxyType`）—— 判定函数改不了上下文。

    字段名由内容侧定（引擎只要求它是合法标识符且不与外壳自身属性同名）。
    字段值不做拷贝：判定函数看到的就是内容侧放进去的那个对象（要不要只读由内容侧决定）。
    """

    __slots__ = ("_fields",)

    #: 外壳自身的属性名 —— 内容侧字段不得占用（`ctx.fields` 必须是字段映射本身）。
    _RESERVED = frozenset({
        "fields", "_fields", "get", "keys", "register", "evaluate", "has", "missing",
        "__slots__", "__init__", "__getattr__", "__repr__", "__class__", "__dict__",
        "__doc__", "__module__", "__weakref__",
    })

    def __init__(self, **fields) -> None:
        for name in fields:
            _check_field_name(name)
            if name in self._RESERVED:
                raise ValueError(
                    f"字段名 {name!r} 与外壳自身属性重名，会让透传读不到该字段；"
                    f"请改名（要列字段用 .fields）")
        self._fields = MappingProxyType(dict(fields))

    @property
    def fields(self):
        """当前字段的**只读**映射（调试 / 序列化用；引擎自身不读它）。"""
        return self._fields

    def get(self, name: str, default=None):
        """按名字取字段，缺 → `default`。

        只有**调用方显式给默认值**时才用到它；属性访问（`ctx.x`）照旧 fail-closed。
        """
        return self._fields.get(name, default)

    def __getattr__(self, name: str):
        try:
            return self._fields[name]
        except KeyError:
            raise AttributeError(
                f"上下文没有字段 {name!r}（已有：{sorted(self._fields)}）") from None

    def __repr__(self) -> str:
        return f"Ctx({', '.join(f'{k}={v!r}' for k, v in self._fields.items())})"
