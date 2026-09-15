# -*- coding: utf-8 -*-
"""接线层（wire）—— 包侧**唯一取件面**：注入句柄 / 惰性模块 / 观测口 / 名字聚合。

**为什么有它**：包内每个消费域都要「从宿主/引擎取件，取不到就 fail-closed」，同一段样板
被抄了七遍（存档注入面 / 包内惰性句柄 / 观测口 / 聚合门面 / 若干域取件口…）。每抄一遍，
「取不到怎么办」的口径就漂一点：有的抛、有的返回 None、有的悄悄给个默认值。
本模块把那套样板收成**一套形状**，口径只有一种 —— **取不到 → 显式点名报错**。

**四件事**（引擎只认这四件，名字全由调用方给）::

    from saintess_engine.wire import Wire

    w = Wire()
    w.bind(db_path="/srv/x.db", clock=time.time, log=my_log, tlog=my_flow)

    w.handle("db_path")         # 传进去什么拿出来就是什么（同一只对象，不拷贝）
    w.handles()                 # 只读视图（MappingProxyType，活的）
    w.bound()                   # 是否已注入过句柄（供「显式降级并留痕」判定）
    w.log                       # 未 bind → WireMissing（**不返回 None**）
    w.emit("some_kind", n=1)    # 透传 tlog.emit；未 bind tlog → WireMissing

    mod = w.lazy("some_mod", loader)   # 登记不加载（防循环 import）
    mod.SOMETHING                      # 首次属性访问才调 loader，之后缓存
    w.handle("some_mod")               # 惰性名同样从这一个口取（取时才加载）

    s = w.surface({"a": 1, "b": lambda: 2}, aliases={"alpha": "a"})
    s.resolve("a")              # 1
    s.resolve("alpha")          # 1（别名 → 声明名）
    s.resolve("zz")             # KeyError（点名）
    s.missing()                 # 声明了但取不到的（供自检）

**零知识**：引擎不认任何具体名字。`log` / `tlog` 只是两个**便捷属性**（名字是与调用方
之间的既有约定），其余句柄名一律由 `bind()` 给；本模块不知道「哪个域该有哪些句柄」。

**取件语义只有一种**：取不到 → `WireMissing` 且**消息点名**。唯一的例外是 `bound()` ——
它不取件，只回答「有没有注入面」，让调用方可以做「显式降级并留痕」而不是静默空跑。

有意不做的事
------------
* **不认具体句柄名**：`bind(**handles)` 收任意名字；没有内置句柄清单，也不校验「该有什么」。
* **不做依赖注入容器**：没有自动装配、没有按类型找件、没有构造注入 —— 只做「按名取」。
* **不做单例注册表**：`Wire` 是普通对象，谁建谁用；进程级唯一实例由调用方决定。
* **不 import 任何包内模块**：句柄与惰性 loader 都由调用方给 —— 所以本模块可以安全地
  出现在任何 import 窗口（含循环 import 的中段）；本文件只依赖标准库。
* **不吞异常**：惰性 loader 抛错原样上抛；名字面的取值器抛错包成 `WireMissing` 并保留
  原因（``raise ... from exc``）—— 绝不静默返回 None / 空表。
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional

__all__ = ["WireMissing", "LazyRef", "Surface", "Wire"]


def _missing(name: str, detail: str = "") -> "WireMissing":
    """构造一条点名报错（消息里一定含名字）。"""
    msg = "取件面缺少 `%s`" % (name,)
    if detail:
        msg += "：%s" % (detail,)
    return WireMissing(msg + " —— 拒绝静默空跑", name=name)


def _default_getter(src: Any, name: str) -> Any:
    """默认取值器：源可调用则调用，否则原值返回（`name` 只为诊断对齐签名）。"""
    return src() if callable(src) else src


class WireMissing(RuntimeError):
    """缺注入面 / 缺句柄（取不到）。

    **消息里必须点名是哪一个**；`name` 属性同值，便于程序化判定。
    构造器因此多收一个仅关键字参数 `name`（不传时等同普通 `RuntimeError`）。
    """

    def __init__(self, message: str, *, name: Optional[str] = None) -> None:
        super().__init__(message)
        self.name = name


class LazyRef:
    """惰性模块句柄：**首次取属性时**才调 `loader`，之后缓存（用来防循环 import）。

    * `get()`：触发加载并缓存；`loader` 抛错 → **原样上抛**
    * 加载失败**不缓存**（下次可重试，不会把一次瞬时故障钉死）
    * `loader` 返回 None → 视为取不到 → `WireMissing`（点名）
    * `ref.<属性>`：转发到已加载对象（同样触发加载）
    """

    __slots__ = ("_name", "_loader", "_loaded", "_obj")

    def __init__(self, name: str, loader: Callable[[], Any]) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("惰性句柄名必须是非空字符串")
        if not callable(loader):
            raise TypeError("惰性句柄的 loader 必须可调用：loader() -> 对象")
        self._name = name
        self._loader = loader
        self._loaded = False
        self._obj = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def loaded(self) -> bool:
        """是否已成功加载（`__repr__` 与自检用；不会触发加载）。"""
        return self._loaded

    def get(self) -> Any:
        """触发加载并缓存；返回加载到的对象。"""
        if not self._loaded:
            obj = self._loader()
            if obj is None:
                raise _missing(self._name, "惰性 loader 返回 None")
            self._obj = obj
            self._loaded = True
        return self._obj

    def __getattr__(self, attr: str) -> Any:
        # 内部名（`_name` 等）走正常查找；走到这里说明真没有 → 直接 AttributeError，
        # 避免「属性还没设好时自引用 → 递归」。
        if attr.startswith("_"):
            raise AttributeError("惰性句柄没有属性 %r" % (attr,))
        return getattr(self.get(), attr)

    def __repr__(self) -> str:
        return "<LazyRef %r %s>" % (self._name, "已加载" if self._loaded else "未加载")


class Surface:
    """名字聚合面：**名字 → 取值源**。名单由调用方给（引擎不认名字）。

    :param name_src: `{名字: 取值源}`；键序即 `names()` 的顺序（构造时快照）
    :param getter: `getter(源, 名字) -> 值 | None`；`None` → 用默认取值器
        （源可调用则调用，否则原值返回）
    :param aliases: `{别名: 声明名}`；别名只是另一种写法，不产生新名字，
        且目标**必须是已声明的名字**（否则构造即 `ValueError`，拒绝静默留空）

    `resolve()` 取到值；**未知名字 → `KeyError`（点名）**；声明了但取不到
    （取值器抛错 / 返回 None）→ `WireMissing`（点名）。两者分开是有意的：
    前者是调用方拼错名字（程序 bug），后者是装配缺陷（注入没接上）。
    """

    def __init__(self, name_src: Mapping, getter: Optional[Callable] = None,
                 *, aliases: Optional[Mapping] = None) -> None:
        if not isinstance(name_src, Mapping):
            raise TypeError("name_src 必须是映射（名字 → 取值源）")
        for name in name_src:
            if not isinstance(name, str) or not name:
                raise ValueError("名字必须是非空字符串：%r" % (name,))
        self._name_src = dict(name_src)
        self._aliases = dict(aliases or {})
        for alias, target in self._aliases.items():
            if not isinstance(alias, str) or not alias:
                raise ValueError("别名必须是非空字符串：%r" % (alias,))
            if target not in self._name_src:
                raise ValueError("别名 `%s` 指向未声明的名字：%r" % (alias, target))
        if getter is None:
            getter = _default_getter
        elif not callable(getter):
            raise TypeError("getter 必须可调用：getter(源, 名字) -> 值")
        self._getter = getter

    # ---------------------------------------------------------------- 读
    def names(self) -> list:
        """声明的名字（保序 = 传入顺序；**不含别名** —— 别名不是新名字）。"""
        return list(self._name_src)

    def has(self, name) -> bool:
        """名字是否在面上（含别名）。**只查声明，不触发取值器**。"""
        return name in self._name_src or name in self._aliases

    def resolve(self, name) -> Any:
        """按名取值。未知名字 → `KeyError`；取不到 → `WireMissing`。"""
        canonical = self._aliases.get(name, name)
        if canonical not in self._name_src:
            raise KeyError("名字聚合面未声明 `%s`" % (name,))
        src = self._name_src[canonical]
        try:
            value = self._getter(src, canonical)
        except Exception as exc:                                  # noqa: BLE001
            raise _missing(canonical, "取值器抛错（%s: %s）" % (type(exc).__name__, exc)) from exc
        if value is None:
            raise _missing(canonical, "取值器返回 None")
        return value

    def missing(self) -> list:
        """声明了但取不到的（供自检；顺序 = `names()`）。**只报不改**。"""
        out = []
        for name in self._name_src:
            try:
                self.resolve(name)
            except WireMissing:
                out.append(name)
        return out

    def __repr__(self) -> str:
        return "<Surface 名字 %d 个 / 别名 %d 个>" % (len(self._name_src), len(self._aliases))


class Wire:
    """包侧唯一取件面：**注入句柄 / 惰性模块 / 观测口 / 名字面**四件事。

    取件只有一种语义：**取不到 → `WireMissing`（点名）**。不做静默兜底 ——
    要降级可以，由调用方用 `bound()` 显式判、显式留痕。
    """

    def __init__(self) -> None:
        self._handles: dict = {}
        self._lazy: dict = {}

    # ---------------------------------------------------------------- 注入
    def bind(self, **handles) -> "Wire":
        """注入句柄（名字由调用方定）。返回 self，便于链式。

        * 值为 `None` = **没给**（不覆盖已有值；与包内既有注入面同口径）
        * 同名再 bind = **覆盖**（注入方后写者胜）
        * 名字已登记为惰性句柄 → `ValueError`（一个名字只能有一种来源，拒绝静默遮蔽）
        * 先整批校验再落盘：有一个名字非法则整批不生效（不留半套状态）
        """
        pending = {}
        for name, value in handles.items():
            if not isinstance(name, str) or not name:
                raise ValueError("句柄名必须是非空字符串：%r" % (name,))
            if name in self._lazy:
                raise ValueError(
                    "名字 `%s` 已登记为惰性句柄（先 lazy 后 bind 会静默遮蔽，拒绝）" % (name,))
            if value is None:
                continue
            pending[name] = value
        self._handles.update(pending)
        return self

    def handle(self, name) -> Any:
        """按名取件：**传进去什么拿出来就是什么**（同一只对象，不拷贝）。

        未注入 → 若该名登记过惰性句柄则触发加载；否则 `WireMissing`（点名）。
        """
        if name in self._handles:
            return self._handles[name]
        ref = self._lazy.get(name)
        if ref is not None:
            return ref.get()
        raise _missing(name, "该名未 bind（也未登记惰性句柄）")

    def handles(self) -> Mapping:
        """已注入句柄的**只读视图**（`MappingProxyType`）。

        视图是**活的**：之后的 `bind()` 会反映出来；但**改不动**（写入 → `TypeError`）。
        只含 `bind()` 注入的句柄；惰性句柄走 `lazy()` / `handle()`。
        """
        return MappingProxyType(self._handles)

    def bound(self) -> bool:
        """是否已注入过至少一个句柄。

        惰性登记**不算**（那是包侧自己声明的 loader，不证明宿主接上了）。
        """
        return bool(self._handles)

    def lazy(self, name: str, loader: Callable[[], Any]) -> LazyRef:
        """登记一个惰性模块句柄并返回它（**登记不加载**）。

        * 名字已 bind / 已登记 → `ValueError`（一个名字只能有一种来源）
        * 首次 `ref.get()` / `ref.<属性>` / `wire.handle(name)` 才调 `loader`
        * `loader` 抛错原样上抛（不缓存失败）；返回 None → `WireMissing`
        """
        if not isinstance(name, str) or not name:
            raise ValueError("惰性句柄名必须是非空字符串")
        if name in self._handles or name in self._lazy:
            raise ValueError("名字 `%s` 已存在（句柄或惰性句柄），拒绝静默覆盖" % (name,))
        ref = LazyRef(name, loader)
        self._lazy[name] = ref
        return ref

    # ---------------------------------------------------------------- 观测口
    @property
    def log(self):
        """文本日志句柄（未 bind → `WireMissing`；**不返回 None**、不悄悄换一棵日志树）。"""
        return self.handle("log")

    @property
    def tlog(self):
        """结构化流水句柄（未 bind → `WireMissing`；**不返回 None**）。"""
        return self.handle("tlog")

    def emit(self, kind: str, **fields) -> Any:
        """透传 `tlog.emit(kind, **fields)`；未 bind tlog → `WireMissing`。

        句柄在但**没有可调用的 `emit`** → 同样是装配缺陷 → `WireMissing`（点名，
        拒绝静默丢流水）。`tlog.emit` 自身的异常照原样上抛（本口不做吞异常）。
        """
        tlog = self.handle("tlog")
        emit = getattr(tlog, "emit", None)
        if not callable(emit):
            raise _missing("tlog", "已注入的 tlog 没有可调用的 emit(...)（拿到 %s）"
                           % (type(tlog).__name__,))
        return emit(kind, **fields)

    # ---------------------------------------------------------------- 名字面
    def surface(self, name_src: Mapping, *, aliases: Optional[Mapping] = None,
                getter: Optional[Callable] = None) -> Surface:
        """建一个名字聚合面（名单由调用方给）。`getter=None` → 用默认取值器。"""
        return Surface(name_src, getter, aliases=aliases)

    def __repr__(self) -> str:
        return "<Wire 句柄 %d 个 / 惰性 %d 个>" % (len(self._handles), len(self._lazy))
