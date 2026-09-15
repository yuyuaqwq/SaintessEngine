# -*- coding: utf-8 -*-
"""奖励发放编排（Grant）—— 奖励包 → 分类发放。

**形状在哪**：「发奖励」在实现里通常长成一个把「若干类别的奖励条目」逐类交给各自实现的
入口函数 —— 分几类、每类怎么发、按什么顺序发，全写死在入口里。把「发的是什么」拿掉之后，
剩下的只是三件通用的事：**装包**（类别名 + 载荷）、**合并**（同类累加）、**派发**（按注册表逐类调）。
本模块把这三件事收成一个对象；类别名与实现**全部**由内容侧给。

**用法**::

    from saintess_engine.grant import Grant, UnknownSink

    def sink_alpha(ctx, payloads):                # 这一类怎么发 = 内容侧的事
        ...                                       # 返回值原样收进 grant() 的结果
        return {"n": len(payloads)}

    g = Grant(sinks={"alpha": sink_alpha, "beta": sink_beta}, log=my_logger)
    g.add("alpha", {"k": 1})                      # 同 kind 追加（不是覆盖）
    g.add("alpha", {"k": 2})
    g.add("beta", "raw")                          # 载荷不透明：映射 / 字符串 / 数字都收
    g.merge(other)                                # 并入另一个奖励包（同类追加）
    g.summary()                                   # {'alpha': [{'k': 1}, {'k': 2}], 'beta': ['raw']}
    g.grant(ctx)                                  # 逐类调 sink → {'alpha': ..., 'beta': ...}
    g.grant(ctx, only=["alpha"])                  # 只发 alpha

**调用约定（只有一种）**：每个类别调一次 sink，签名 ``sink(ctx, payloads)`` ——
`ctx` 原样透传（引擎不读它的任何字段），`payloads` 是该类载荷的**列表拷贝**（即 `summary()`
里该类的值）。sink 的返回值原样收进结果 `{kind: 结果}`。该类没装载荷就不调它。

**发放顺序 = `sinks` 的声明序**（与装包先后、与 `only` 给的顺序都无关）：同一份包在同一个
`Grant` 上重复发放，调用序列逐次相同。

**合并语义（只有一种）**：同 kind **追加** —— `self` 的载荷在前、`other` 的在后；不覆盖、
不去重；`other` 里本包没有的 kind 按 `other` 的登记序接在后面。
**`merge` 的幂等性由内容侧约定**：本方法是纯追加，同一个包并两次，载荷就出现两次
（引擎不替内容侧判断「这个包是不是已经并过了」）。要「不会翻倍」，内容侧每次并的是新包，
或者自己保证每个包只并一次。

**发放不改包**：`grant()` 只读包；发完 `summary()` 不变 —— 同一个包发两次就是发两次
（不把包变成一次性凭证，也不静默吞掉第二次）。

**零知识**：引擎不认任何具体类别名，也不解释载荷 —— `kind` 是不透明字符串（非空），
`payload` 原样保存、原样交给 sink；类别名单只来自 `sinks`。

**`log` 约定**：给了 `log`（一个带 `info(...)` 的日志句柄，如 `saintess_engine.log` 门面
给出的 logger），每发成一个类别记一行「kind + 载荷条数」；不给就不记。

**有意不做的事**
----------------
* **不做默认类别**：没有内置 kind、没有兜底 sink、没有「未知类别就丢掉」的分支 ——
  `sinks` 里没登记的 kind 在发放时以 `UnknownSink` **点名**（fail-closed）。
* **不做错误吞并**：任一 sink 抛错**原样上抛**，不「尽力而为」、不接着发后面的类别。
* **不消费包**：`grant()` 不改包，不把载荷标记成「已发」。
* **不做兼容壳**：没有开关、没有「静默模式」；`sinks` / `log` / kind / `only` 非法一律当场报错。
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

__all__ = ["Grant", "UnknownSink"]


class UnknownSink(LookupError):
    """发放时遇到未登记的类别名（fail-closed：不静默跳过、不丢载荷）。"""


def _kind(kind) -> str:
    """类别名校验：不透明字符串，但必须非空（空名字装不进包，也点不了名）。"""
    if not isinstance(kind, str):
        raise TypeError(f"类别名必须是字符串，收到 {type(kind).__name__}")
    if not kind.strip():
        raise ValueError("类别名不能为空")
    return kind


def _sink_table(sinks) -> dict:
    """`sinks` 归一：必须是「类别名 → 可调用」的映射；声明序在归一后**冻结**。"""
    if not isinstance(sinks, Mapping):
        raise TypeError(f"sinks 必须是「类别名 → 可调用」的映射，收到 {type(sinks).__name__}")
    table: dict = {}
    for kind in sinks:
        fn = sinks[kind]
        name = _kind(kind)
        if not callable(fn):
            raise TypeError(f"类别 {name!r} 的 sink 必须是可调用的，收到 {type(fn).__name__}")
        table[name] = fn
    return table


def _logger(log):
    """`log` 归一：`None` = 不记；否则必须是带 `info(...)` 的日志句柄（不静默丢日志）。"""
    if log is None:
        return None
    if not callable(getattr(log, "info", None)):
        raise TypeError(f"log 必须是带 info(...) 的日志句柄，收到 {type(log).__name__}")
    return log


class Grant:
    """奖励包（**可变**）：装包 / 合并 / 逐类发放。类别名与实现全由 `sinks` 给。"""

    def __init__(self, *, sinks: Mapping[str, Callable], log=None) -> None:
        """`sinks` = `{类别名: 发放实现}`（声明序 = 发放序，构造即冻结、构造即校验）；
        `log` = 可选的日志句柄（带 `info(...)`），每发成一类记一行。
        """
        self._sinks = _sink_table(sinks)
        self._log = _logger(log)
        self._by_kind: dict = {}

    # ------------------------------------------------------------ 装包
    def add(self, kind: str, payload) -> None:
        """累加一类奖励：同 kind **追加**一条（不覆盖、不去重）。

        `payload` 不透明（引擎不解释、不转换、不深拷贝）。`kind` 未登记**不在这里报错** ——
        装包只搬数据，发放点（`grant()`）才是 fail-closed 的口子。
        """
        self._by_kind.setdefault(_kind(kind), []).append(payload)

    def merge(self, other: "Grant") -> None:
        """把 `other` 的载荷**追加**进本包（同 kind 累加：`self` 在前、`other` 在后）。

        纯追加 ⇒ **不幂等**：同一个包并两次即两份载荷（幂等性由内容侧约定，见模块 docstring）。
        合并只看数据、不看 sink —— 两个包的 `sinks` 可以不同，未登记的 kind 在发放时点名。
        """
        if other is self:
            raise ValueError("不能把奖励包并入自身")
        if not isinstance(other, Grant):
            raise TypeError(f"merge 只收 Grant，收到 {type(other).__name__}")
        for kind in other._by_kind:
            payloads = other._by_kind[kind]
            self._by_kind.setdefault(kind, []).extend(payloads)

    # ------------------------------------------------------------ 读取
    def summary(self) -> dict:
        """`{kind: [payload, ...]}`（按各类**首次装包**的登记序，供渲染 / 日志）。

        返回新字典 + 每类新列表：改返回值不影响包；载荷本身原样（不透明，引擎不做深拷贝）。
        """
        return {kind: list(self._by_kind[kind]) for kind in self._by_kind}

    # ------------------------------------------------------------ 发放
    def grant(self, ctx, *, only=None) -> dict:
        """逐类调 sink；返回 `{kind: sink 的返回值}`。

        * 顺序 = `sinks` 声明序；`only`（可迭代的类别名）只做筛选，不改顺序
        * `only=None` → 包里全部类别；`only` 给的类别**必须都已登记**，否则 `UnknownSink`
        * 先校验后发放：有任何未登记的类别，在调第一个 sink **之前**报错（不会先发一部分）
        * 已登记但本次没有载荷的类别不调 sink、也不进结果
        * sink 的异常**原样上抛**；本方法不改包（同一个包可以再发一次）
        """
        order, unknown = self._plan(only)
        if unknown:
            raise UnknownSink(
                "未登记的发放类别：%s（已登记：%s）"
                % ("、".join(repr(k) for k in unknown), list(self._sinks)))
        out: dict = {}
        for kind in order:
            payloads = list(self._by_kind[kind])
            out[kind] = self._sinks[kind](ctx, payloads)
            if self._log is not None:
                self._log.info("grant kind=%s payloads=%d", kind, len(payloads))
        return out

    def _requested(self, only) -> list:
        """本次要发的类别名（去重、保序）；`only` 非法当场报错。"""
        if only is None:
            return list(self._by_kind)
        if isinstance(only, (str, bytes)) or not isinstance(only, Iterable):
            raise TypeError(f"only 必须是类别名的可迭代，收到 {type(only).__name__}")
        names: list = []
        for kind in only:
            name = _kind(kind)
            if name not in names:
                names.append(name)
        return names

    def _plan(self, only):
        """返回 `(按声明序的发放名单, 未登记的类别名)` —— 两者都在调 sink 之前算好。

        未登记名单按**请求序**列出（不是集合序）：点名与报错文案都可复现。
        """
        requested = self._requested(only)
        wanted = set(requested)
        order = [k for k in self._sinks if k in wanted and k in self._by_kind]
        unknown = [k for k in requested if k not in self._sinks]
        return order, unknown

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "Grant(kinds=%s, registered=%s)" % (
            {k: len(self._by_kind[k]) for k in self._by_kind}, list(self._sinks))
