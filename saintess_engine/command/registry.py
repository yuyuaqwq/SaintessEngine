# -*- coding: utf-8 -*-
"""指令声明与注册骨架 —— 把「一条指令是什么」（形状）与「有哪些指令」（内容）分开。

为什么要它
----------
宿主命令层的常见形态是**两份数据互相同步**：一叠 `@装饰器`（真实注册）＋ 一张
手工维护的静态正则表（供 gate / 快捷转发 / 测试用）。两份 = 一定会漂移，
于是只能「再加一个同步测试盯着」。那是缺声明式的症状，不是解决办法。

本模块把「一条指令」抽成声明对象 `CommandSpec`，注册表负责：

* **装载**：数据（dict / JSON 友好）→ 声明；编辑器可写
* **查询**：按 key / 分类 / 可见性取，供帮助与目录用
* **匹配**：文本 → 命中哪条（宿主 filter 与「互斥矩阵」自检都用它）
* **派生**：把声明还原成宿主需要的形状 —— 正则池 / `{key: 正则}` 表
* **自检**：`validate()` 查声明自身；`audit_handlers()` 查**声明 ↔ 实际 handler 漂移**

声明与处理器分开
----------------
**声明**（`CommandSpec`：正则/分类/顺序/守卫名）与**处理器**（一段可调用）是两件事，
本模块各给一条登记路：

* `register()` / `load()` —— 登记声明；
* `bind()` —— 登记处理器（同步函数或**协程函数**都收，引擎**不包装**它：
  是否 render、要不要 `await`，都由使用方决定）；`handler_of()` / `is_async()` 取件，
  `binding_of()` / `bindings()` 取回绑定时的元数据（guards / params）。

未登记的处理器一律 `HandlerMissing`（点名 key，**不返回 None**）。声明了但没有处理器、
或登记了处理器但没声明，都是使用方自己的节奏 —— 模块不做隐式补全。

可拔插
------
本模块不依赖任何宿主、不注册任何东西、也不被自动调用：使用方显式建注册表、
显式装载、显式取派生结果。**不装载 = 零行为**（对既有代码无影响）；
**不 bind = 零处理器**（任何 key 取处理器都 fail-closed）。

引擎零知识
----------
只认「key / 正则 / 分类 / 顺序 / 优先级 / 可见性」这类通用形状字段；指令名、文案、
守卫语义一律由使用方给。守卫只记**名字**，语义由使用方自己实现（框架不认「角色」）。
处理器只被当作「可调用」保存与取出，引擎不解释它的参数与返回值。
"""
from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence

from .binding import BindSpec

__all__ = ["CommandSpec", "CommandRegistry", "CommandBinding", "HandlerMissing",
           "combine_patterns"]


def combine_patterns(patterns: Sequence[str]) -> str:
    """多条正则合成一条（非捕获组交替）—— 宿主 filter 只收一条时用。

    单条 → 原样返回（保证既有「逐字相等」的断言不被动到）。
    空 → 空串。非法正则不在这里校验（交给 `validate()` 报告，不抛）。
    """
    pats = [p for p in (patterns or ()) if p]
    if not pats:
        return ""
    if len(pats) == 1:
        return pats[0]
    return "|".join("(?:%s)" % p for p in pats)


@dataclass
class CommandSpec:
    """一条指令的声明。字段全为**通用形状**，无游戏语义。

    * `key`       —— 指令标识，通常等于宿主 handler 名（漂移自检靠它对齐）
    * `patterns`  —— 命中正则（首条为主，其余为别名；均行首锚定由使用方负责）
    * `desc`      —— 人读说明（帮助/编辑器）
    * `category`  —— 分类（帮助分组；内容由使用方给）
    * `usage`     —— 用法示例文本（帮助用）
    * `guards`    —— 守卫**名字**列表（如 "player" / "battle"；语义由使用方实现）
    * `page_size` —— 该指令列表输出的每页条数（0 = 不适用）
    * `visible`   —— 是否出现在帮助/目录
    * `order`     —— 帮助排序（小在前；同值按注册序）
    * `priority`  —— **命中优先级**（大在前；同值按注册序）。与 `order` 各管一头：
                     `order` 只排帮助/目录（`visible()`），`priority` 只排命中
                     （`hits()` / `hit()`），互不参与对方的排序
    * `bind`      —— **声明式绑定**（`BindSpec`；可选）：点名实现体 + 调用模式 + 取参槽位，
                     由 `binding.bind_handler()` 在装载期解析成处理器。字段解析**fail-closed**
                     （未知 `call` / 未知 `args` 槽位 / 未知键当场抛），不在运行期降级。
    * `extra`     —— 使用方自定义附加数据（框架不解释、原样带回）
    """
    key: str
    patterns: tuple = ()
    desc: str = ""
    category: str = ""
    usage: str = ""
    guards: tuple = ()
    page_size: int = 0
    visible: bool = True
    order: int = 0
    priority: int = 0
    bind: Optional[BindSpec] = None
    extra: dict = field(default_factory=dict)

    # ---------- 构造 ----------
    @classmethod
    def from_dict(cls, data: Mapping) -> "CommandSpec":
        """从 dict/JSON 装载。容错：别名键（name/regex/pattern）都认，坏值降级不抛。"""
        if not isinstance(data, Mapping):
            return cls(key=str(data))
        key = data.get("key", data.get("name", data.get("id", "")))
        raw = data.get("patterns", data.get("pattern", data.get("regex", ())))
        if isinstance(raw, str):
            pats = (raw,) if raw else ()
        else:
            pats = tuple(str(p) for p in (raw or ()) if p)
        raw_g = data.get("guards", data.get("guard", ()))
        guards = (raw_g,) if isinstance(raw_g, str) and raw_g else tuple(raw_g or ())
        try:
            page_size = int(data.get("page_size") or 0)
        except (TypeError, ValueError):
            page_size = 0
        try:
            order = int(data.get("order") or 0)
        except (TypeError, ValueError):
            order = 0
        try:
            priority = int(data.get("priority") or 0)   # "50" / 50 两种写法都认
        except (TypeError, ValueError):
            priority = 0
        raw_bind = data.get("bind")
        bind = None if raw_bind is None else BindSpec.from_data(
            raw_bind, key=str(key or ""), where="指令声明")
        return cls(
            key=str(key or ""),
            patterns=pats,
            desc=str(data.get("desc", "") or ""),
            category=str(data.get("category", "") or ""),
            usage=str(data.get("usage", "") or ""),
            guards=guards,
            page_size=page_size,
            visible=bool(data.get("visible", True)),
            order=order,
            priority=priority,
            bind=bind,
            extra=dict(data.get("extra") or {}),
        )

    def to_dict(self) -> dict:
        """回写成 JSON 友好结构（编辑器读；round-trip 稳定）。"""
        out = {"key": self.key, "patterns": list(self.patterns)}
        for k in ("desc", "category", "usage"):
            v = getattr(self, k)
            if v:
                out[k] = v
        if self.guards:
            out["guards"] = list(self.guards)
        if self.page_size:
            out["page_size"] = self.page_size
        if not self.visible:
            out["visible"] = False
        if self.order:
            out["order"] = self.order
        if self.priority:
            out["priority"] = self.priority
        if self.bind is not None:
            out["bind"] = self.bind.to_data()
        if self.extra:
            out["extra"] = dict(self.extra)
        return out

    # ---------- 便捷 ----------
    @property
    def pattern(self) -> str:
        """主正则（首条）；无声明 → 空串。"""
        return self.patterns[0] if self.patterns else ""

    def combined(self) -> str:
        """该指令合并后的正则（宿主 filter 只收一条时用）。"""
        return combine_patterns(self.patterns)

    def hits(self, text: str, *, mode: str = "search") -> bool:
        """文本是否命中本指令任一正则（默认 `search`，与宿主 filter 语义一致）。"""
        return _any_hit(self.patterns, text, mode)


def _any_hit(patterns: Sequence[str], text: str, mode: str = "search") -> bool:
    for pat in patterns or ():
        if not pat:
            continue
        try:
            rx = re.compile(pat)
        except re.error:
            continue
        try:
            m = rx.fullmatch(text) if mode == "fullmatch" else (
                rx.match(text) if mode == "match" else rx.search(text))
        except re.error:
            continue
        if m:
            return True
    return False


class HandlerMissing(RuntimeError):
    """取处理器时**没有这条登记**（fail-closed）。

    消息里必须点名是哪个 key；`key` 属性同值，便于程序化判定。
    与「声明缺失」分开：声明归 `validate()` / `audit_handlers()` 报告，
    本异常只说「这条处理器没登记（或 key 拼错）」。
    """

    def __init__(self, message: str, *, key: Any = None) -> None:
        super().__init__(message)
        self.key = key


def _handler_missing(key: Any) -> HandlerMissing:
    """构造一条点名报错：消息里一定含 key。"""
    return HandlerMissing(
        "未登记处理器：key=%r（先调用 bind() 登记；拒绝静默降级成 None）" % (key,),
        key=key)


def _checked_key(key: Any, where: str) -> str:
    """登记键必须是**非空字符串**；否则点名抛错（不静默转字符串）。"""
    if not isinstance(key, str) or not key:
        raise ValueError("%s：key 必须是非空字符串：%r" % (where, key))
    return key


def _as_tuple(value: Any, what: str, key: Any) -> tuple:
    """元数据归一成 tuple：`None` → `()`；单个字符串 → 一元组；其余照 `tuple()`。

    不可迭代 → 点名抛 `TypeError`（不静默丢）。
    """
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    try:
        return tuple(value)
    except TypeError:
        raise TypeError("%s 必须可迭代（key=%r）：%r" % (what, key, value)) from None


def _is_async_handler(handler: Any) -> bool:
    """处理器是不是**协程函数**（供调用方决定 `await` 与否）。

    * `async def` / `functools.partial(async def)` → True（`inspect` 会拆 partial）
    * 可调用对象且 `__call__` 是 `async def` → True
    * 同步函数 / 普通 lambda / 同步 `__call__` → False
    * **异步生成器函数 → False**：调用它得到 async generator（该 `async for`，不是 `await`）
    """
    if not callable(handler):
        return False
    if inspect.iscoroutinefunction(handler):
        return True
    if inspect.isfunction(handler) or inspect.ismethod(handler) or inspect.isbuiltin(handler):
        return False
    return inspect.iscoroutinefunction(getattr(handler, "__call__", None))


@dataclass(frozen=True)
class CommandBinding:
    """一条**处理器登记**（`bind()` 的存档）：处理器本体 + 声明侧元数据。

    * `key`     —— 登记键（= 声明 key）
    * `handler` —— 处理器本体，**原样保存**（引擎不包装：是否 render 由使用方决定）
    * `guards`  —— 守卫**名字**（通用元数据，引擎不解释语义）
    * `params`  —— 取参槽位（通用元数据，引擎不解释语义）
    * `is_async` —— 处理器是否协程函数（= `CommandRegistry.is_async(key)`，现场判定）
    """
    key: str
    handler: Any
    guards: tuple = ()
    params: tuple = ()

    @property
    def is_async(self) -> bool:
        return _is_async_handler(self.handler)


class CommandRegistry:
    """指令注册表：声明（装载 / 查询 / 匹配 / 派生 / 自检）+ 处理器登记（bind 族）。"""

    def __init__(self, *, name: str = "") -> None:
        self.name = name
        self._specs: dict = {}
        self._order: list = []
        self._bindings: dict = {}

    # ============================================================ 装载
    def register(self, spec: CommandSpec, *, replace: bool = False) -> CommandSpec:
        """登记一条声明。同 key 重复 → 默认抛 `ValueError`（防静默覆盖）。"""
        if not isinstance(spec, CommandSpec):
            spec = CommandSpec.from_dict(spec)
        if spec.key in self._specs and not replace:
            raise ValueError("指令 key 重复：%r（要覆盖请 replace=True）" % spec.key)
        if spec.key not in self._specs:
            self._order.append(spec.key)
        self._specs[spec.key] = spec
        return spec

    def extend(self, specs: Iterable, *, replace: bool = False) -> "CommandRegistry":
        for item in specs or ():
            self.register(item if isinstance(item, CommandSpec)
                          else CommandSpec.from_dict(item), replace=replace)
        return self

    def load(self, items) -> "CommandRegistry":
        """装载声明集合；`dict` 形态 `{key: {...}}` 或 `{key: "正则"}` 也认。"""
        if isinstance(items, Mapping):
            for k, v in items.items():
                if isinstance(v, Mapping):
                    d = dict(v)
                    d.setdefault("key", k)
                    self.register(CommandSpec.from_dict(d))
                elif isinstance(v, str):
                    self.register(CommandSpec(key=str(k), patterns=(v,)))
                else:
                    self.register(CommandSpec.from_dict(v))
            return self
        return self.extend(items)

    @classmethod
    def from_data(cls, items, **kw) -> "CommandRegistry":
        return cls(**kw).load(items)

    # ============================================================ 处理器登记
    def bind(self, key: str, handler, *, guards=(), params=(), replace: bool = False) -> None:
        """登记一条命令的**处理器**（与声明分离）。

        同 key 重复 → 默认抛 `ValueError`（与 `register()` 同口径，防静默覆盖）；
        `replace=True` 才覆盖。`handler` 可以是同步函数或协程函数，**引擎不包装**它
        （是否 render、要不要 `await` 由使用方决定）；`guards` / `params` 只原样存档
        （通用元数据，引擎不解释语义），经 `binding_of()` / `bindings()` 取回。

        参数非法（key 不是非空字符串 / handler 不可调用）→ 点名抛错。
        """
        k = _checked_key(key, "bind")
        if not callable(handler):
            raise TypeError("bind：handler 必须可调用（key=%r）：%r" % (k, handler))
        if k in self._bindings and not replace:
            raise ValueError("指令处理器 key 重复：%r（要覆盖请 replace=True）" % k)
        self._bindings[k] = CommandBinding(key=k, handler=handler,
                                           guards=_as_tuple(guards, "guards", k),
                                           params=_as_tuple(params, "params", k))

    def _binding(self, key) -> CommandBinding:
        """取一条登记；未登记 → `HandlerMissing`（点名 key）。"""
        try:
            return self._bindings[key]
        except (KeyError, TypeError):
            raise _handler_missing(key) from None

    def handler_of(self, key: str):
        """取处理器；未登记 → `HandlerMissing`（点名 key，fail-closed，**不是 None**）。"""
        return self._binding(key).handler

    def is_async(self, key: str) -> bool:
        """该处理器是不是协程函数（供调用方决定 `await` 与否）；未登记 → `HandlerMissing`。"""
        return self._binding(key).is_async

    def binding_of(self, key: str) -> CommandBinding:
        """取整条登记（处理器 + guards / params 元数据）；未登记 → `HandlerMissing`。"""
        return self._binding(key)

    def bindings(self) -> tuple:
        """全部登记，按 `bind()` 顺序 → `((key, CommandBinding), …)`（覆盖不改顺序）。"""
        return tuple(self._bindings.items())

    # ============================================================ 查询
    def get(self, key: str) -> Optional[CommandSpec]:
        return self._specs.get(key)

    def specs(self) -> tuple:
        """全部声明（注册序）。"""
        return tuple(self._specs[k] for k in self._order)

    def keys(self) -> tuple:
        return tuple(self._order)

    def __len__(self) -> int:
        return len(self._order)

    def __contains__(self, key) -> bool:
        return key in self._specs

    def __iter__(self):
        return iter(self.specs())

    def by_category(self) -> dict:
        """`{分类: (声明…)}`（分类内保持注册序）。空分类归 `""`。"""
        out: dict = {}
        for spec in self.specs():
            out.setdefault(spec.category, []).append(spec)
        return {k: tuple(v) for k, v in out.items()}

    def visible(self) -> tuple:
        """可见声明（按 `order` 升序，同值保持注册序）—— 帮助/目录用。"""
        vis = [s for s in self.specs() if s.visible]
        return tuple(sorted(vis, key=lambda s: s.order))

    # ============================================================ 匹配
    def _ranked(self, text: str, *, mode: str = "search",
                visible_only: bool = False) -> tuple:
        """命中集合的**唯一排序实现**（`priority` 降序，同值保持注册序）。

        `visible_only=True` → 候选只取 `visible=True` 的声明（路由口径，见 `first_hit()`）：
        不可见声明（平台 gate 之类）不参与包内路由。
        `hits()` / `first_hit()` 都只调这里，谁都不再自己排一遍 —— 排序只有一份实现
        （「两条路由路径口径不一致」的根因就是各排了一遍，见 B19e）。
        """
        t = (text or "").strip()
        got = [s for s in self.specs()
               if (s.visible or not visible_only) and s.hits(t, mode=mode)]
        return tuple(sorted(got, key=lambda s: -s.priority))

    def hits(self, text: str, *, mode: str = "search") -> tuple:
        """命中该文本的**全部**声明（`priority` 降序，同值保持注册序）—— 互斥矩阵自检用。"""
        return self._ranked(text, mode=mode)

    def hit(self, text: str, *, mode: str = "search") -> Optional[CommandSpec]:
        """命中该文本的**第一条**声明（`priority` 最高者，同值取注册序）；无 → None。

        口径 = `first_hit(text)`（缺省 `visible_only=False`：不可见声明**也算**候选）。
        路由（「玩家能发的指令」）请用 `first_hit(text, visible_only=True)`。
        """
        got = self.hits(text, mode=mode)
        return got[0] if got else None

    def first_hit(self, text: str, *, visible_only: bool = False,
                  mode: str = "search") -> Optional[CommandSpec]:
        """命中该文本的**第一条**声明；`visible_only=True` 时只在**可见**声明里排。

        排序口径与 `hit()` / `hits()` **完全一致**（`priority` 降序，同值按注册序）——
        共用 `_ranked()`，本方法自带零排序。唯一差别 = `visible_only`：
        为 True 时 `visible=False` 的声明（平台 gate 如 `_maint_gate`）**不参与**，
        因为路由是「玩家能发的指令」，gate 是适配器职责（计划 §11.3）。
        缺省 `False` ⇒ 与 `hit()` 逐字同结果（`hit()` = 本方法的缺省特例）。
        """
        got = self._ranked(text, mode=mode, visible_only=visible_only)
        return got[0] if got else None

    # ============================================================ 派生（还原成宿主形状）
    def patterns(self) -> tuple:
        """全部正则串（去重保序）—— 宿主「怎样算一条指令」的 filter 池。"""
        seen, out = set(), []
        for spec in self.specs():
            for p in spec.patterns:
                if p and p not in seen:
                    seen.add(p)
                    out.append(p)
        return tuple(out)

    def pattern_map(self) -> dict:
        """`{key: 合并正则}` —— 静态表/网关回落用的形状（单条时逐字等于原声明）。"""
        return {s.key: s.combined() for s in self.specs() if s.patterns}

    def to_data(self) -> list:
        """回写声明集合（编辑器/存档；round-trip 稳定）。"""
        return [s.to_dict() for s in self.specs()]

    # ============================================================ 自检
    def validate(self) -> list:
        """查声明自身问题，返回问题清单（空 = 通过）。**只报告，不抛。**"""
        problems = []
        for spec in self.specs():
            if not spec.key:
                problems.append("存在空 key 的声明")
                continue
            if not spec.patterns:
                problems.append("%s：未声明任何正则" % spec.key)
            for pat in spec.patterns:
                try:
                    re.compile(pat)
                except re.error as e:
                    problems.append("%s：正则非法（%s）—— %s" % (spec.key, e, pat))
        seen = {}
        for spec in self.specs():
            for p in spec.patterns:
                if p in seen and seen[p] != spec.key:
                    problems.append("正则被多条指令共用：%s ↔ %s（%s）"
                                    % (seen[p], spec.key, p))
                seen.setdefault(p, spec.key)
        return problems

    def audit_handlers(self, handler_names: Iterable[str]) -> dict:
        """声明 ↔ 实际 handler 的漂移自检（替代「手工镜像表 + 同步测试」）。

        返回 `{"declared": n, "actual": n, "missing_spec": [...],
                "missing_handler": [...], "ok": bool}`：
        * `missing_spec`    —— 有 handler 但没声明（漏登记）
        * `missing_handler` —— 声明了但没有对应 handler（死声明）
        """
        actual = {str(x) for x in (handler_names or ()) if x}
        declared = set(self._specs)
        miss_spec = sorted(actual - declared)
        miss_handler = sorted(declared - actual)
        return {
            "declared": len(declared),
            "actual": len(actual),
            "missing_spec": miss_spec,
            "missing_handler": miss_handler,
            "ok": not miss_spec and not miss_handler,
        }
