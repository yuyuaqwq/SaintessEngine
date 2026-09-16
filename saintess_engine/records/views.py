# -*- coding: utf-8 -*-
"""视图注册表 —— 「派生重建」的通用形状（引擎零领域知识）。

**为什么有它**：内容侧有一批**模块级派生状态**（从资料表算出来的常量表 / 索引 / 容器），
资料表热重载后它们不会自己跟着变 —— 命令层读到的会是旧值。内容侧各模块把自己的重建
函数登记到本形状，重建由**调用方**显式触发一次，引擎按登记序调用；哪些模块、重建什么，
引擎一概不认识（前缀由调用方给）。

**用法**::

    from saintess_engine.records import register_view, update_in_place, rebuild_views

    def _rebuild_view():
        update_in_place(THING, _R.thing.all())    # 容器：就地更新
        return [(OLD_TUPLE, new_tuple)]           # 非容器：交引擎按身份做别名回填

    register_view(_rebuild_view, order=10)        # 模块 import 期登记

    rebuild_views(module_prefix="content")        # 重建全部；返回成功的函数个数

**两条口径**:

* **可变容器**（`dict` / `list` / `set`）：重建函数用 `update_in_place(old, new)` **就地更新**
  —— 外部 `from X import Y` 拿到的是同一只对象，内容变了、身份没变。
* **非容器**（`tuple` / `frozenset` / 数字 / 字符串 / 函数）：重建函数把 `(旧对象, 新对象)`
  **列的序列返回**给引擎，引擎在 `module_prefix` 前缀的**已加载模块**里，把**值 `is` 旧对象**的
  全局名改指新对象（**通用别名回填**）。引擎不认识那些名字的含义，只比身份。

**fail-closed**：任一重建函数抛错 → `ViewsRebuildError`（点名函数 `__qualname__` / 登记序 /
原因 / 已完成数量），**不吞成成功**；已经跑过的函数不回滚（与「重建是幂等的全量重算」一致）。

**有意不做的事**
----------------
* **不猜顺序**：`order` 由登记方给（同 order 按登记序）；引擎不看依赖图。
* **不做自动失效**：什么时候重建是调用方的决定，本形状不挂 mtime、不开线程。
* **不认名字**：只比对象身份；`module_prefix` 之外的模块一律不碰。
* **不强引用**：登记是弱引用（模块回收后登记随之消失）。
"""
from __future__ import annotations

import sys
import weakref
from typing import Callable, Optional

__all__ = ["register_view", "views", "rebuild_views", "ViewsRebuildError",
           "update_in_place", "apply_replacements", "placeholder"]

#: 已登记的重建函数（弱引用 + 登记序）—— 模块被回收，登记随之消失（不强引用、不泄漏）。
_REGISTRY: list = []
#: 登记计数器：`(order, seq)` 的稳定次级键（同 order 按登记先后）。
_SEQ: int = 0


class _Placeholder:
    """模块级派生名字的**未构建占位对象**（每个名字一个独立实例）。"""

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:                                         # pragma: no cover
        return "<未构建：%s>" % (self.name,)


def placeholder(name: str) -> "_Placeholder":
    """给一个模块级派生名字造**独立**占位对象（import 期尚未构建时该名字的值）。

    为什么不用 `None` / `()` / `{}` 当占位：别名回填按**对象身份**（`id()`）匹配 ——
    共享的 `None` / 空 tuple 会让不同名字的替换互相串（同一个 `id` 被多个名字命中）。
    独立实例 ⇒ 每个名字一份身份，替换只落在它自己身上；引擎见到占位对象一律跳过。
    """
    return _Placeholder(name)


class ViewsRebuildError(RuntimeError):
    """重建失败：点名函数与原因；调用方据此 fail-closed（**不许静默降级**）。

    `func` = 出错的函数（`模块名.__qualname__`）；`order` = 它的登记序；
    `done` = 已成功重建的数量；`reason` = 原始异常的人读描述。
    """

    def __init__(self, func: str, order: int, done: int, reason: str) -> None:
        self.func = func
        self.order = order
        self.done = done
        self.reason = reason
        super().__init__(
            "视图重建失败：%s（登记序 %d）—— %s；已完成 %d 个" % (func, order, reason, done))


def register_view(fn: Callable, *, order: int = 0) -> None:
    """登记一个重建函数 `fn`（模块 import 期调用）。

    `order` 决定调用顺序（升序；同 `order` 按登记先后）。重复登记同一函数 =
    再登记一次（调用方负责不重复登记；本形状不去重，免得掩盖调用方的重复 import）。
    """
    global _SEQ
    _SEQ += 1
    _REGISTRY.append((order, _SEQ, weakref.ref(fn)))


def _live() -> list:
    """存活的登记 `[(order, seq, fn)]`（顺手清掉已回收的弱引用）。"""
    live = []
    for order, seq, ref in list(_REGISTRY):
        fn = ref()
        if fn is not None:
            live.append((order, seq, fn))
    if len(live) != len(_REGISTRY):
        _REGISTRY[:] = [
            (order, seq, ref) for order, seq, ref in _REGISTRY if ref() is not None]
    return live


def views() -> list:
    """已登记的重建函数副本（**构建序**，即 `(order, 登记序)` 升序）。

    返回新列表（不是内部容器）：调用方拿到的是**函数对象**本身，可直接调用/查看。
    """
    return [fn for _order, _seq, fn in sorted(_live(), key=lambda row: (row[0], row[1]))]


def _rebind(namespace: dict, replacements: dict) -> None:
    """把 `namespace` 里**值 `is` 旧对象**的全局名改指新对象（通用别名回填）。"""
    for key, value in list(namespace.items()):
        if key.startswith("__"):
            continue
        try:
            new = replacements.get(id(value))
        except TypeError:                                          # 不可哈希/异常值
            continue
        if new is not None and new is not value:
            namespace[key] = new


def _same_kind_container(old, new) -> bool:
    """`old` / `new` 同为 `dict` / `list` / `set`（就地更新只对同型容器成立）。"""
    return ((isinstance(old, dict) and isinstance(new, dict))
            or (isinstance(old, list) and isinstance(new, list))
            or (isinstance(old, set) and isinstance(new, set)))





def update_in_place(old, new) -> None:
    """把 `new` 的内容灌进 `old`（**不动 `old` 的身份**）—— 容器重建的公共写法。

    调用方（重建函数）用它把自己的模块级容器就地刷新；外部 `from X import Y` 拿到的是
    同一只对象，**身份不变、内容已新**。`old` / `new` 必须是同型 `dict` / `list` / `set`
    （不同型 → `TypeError`，不静默改成别的写法）。
    """
    if isinstance(old, dict) and isinstance(new, dict):
        old.clear()
        old.update(new)
    elif isinstance(old, list) and isinstance(new, list):
        old[:] = new
    elif isinstance(old, set) and isinstance(new, set):
        old.clear()
        old.update(new)
    else:
        raise TypeError(
            "update_in_place：需要同型 dict/list/set（收到 %s / %s）"
            % (type(old).__name__, type(new).__name__))


def apply_replacements(replacements, module_prefix: Optional[str] = None) -> int:
    """施加一份 `(旧对象, 新对象)` 序列（= `rebuild_views` 对返回值的处理），返回处理条数。

    给**内容侧 import 期自调用**用：模块登记完视图后立即调一次自己的重建函数，把返回的
    非容器替换用同一口径落到模块命名空间上 —— import 期与重载期因此走**完全相同**的写法。
    """
    return _apply_replacements(list(replacements or ()), module_prefix)


def _apply_replacements(replacements, module_prefix: Optional[str]) -> int:
    """对每条 `(旧对象, 新对象)` 施加**非容器别名回填**（见 `rebuild_views` 的「两条口径」）。

    `replacements` = `(旧, 新)` 对的**序列**（不是 `{旧: 新}` 映射）：旧对象可能就是不可哈希的，
    且 `(old1, new1)` / `(old2, new2)` 两条的 `old` 允许 `==` 相等（语义不同、身份不同）⇒
    序列不去重，逐条按身份处理。容器由重建函数用 `update_in_place` 自行就地更新。
    """
    aliases: dict = {}
    for old, new in replacements:
        if new is old or isinstance(old, _Placeholder):
            continue                                               # 首次构建：无需回填
        if _same_kind_container(old, new):
            raise TypeError(
                "rebuild_views：容器替换不许走别名映射（%s → %s）—— 容器请用 update_in_place "
                "就地更新" % (type(old).__name__, type(new).__name__))
        aliases[id(old)] = new
    if aliases and module_prefix:
        for module in _prefix_modules(module_prefix):
            namespace = getattr(module, "__dict__", None)
            if isinstance(namespace, dict):
                _rebind(namespace, aliases)
    return len(aliases)


def _prefix_modules(prefix: str) -> list:
    """`module_prefix` 前缀的已加载模块（含前缀自身的模块；`sys.modules` 快照）。"""
    out = []
    for name, module in list(sys.modules.items()):
        if module is None:
            continue
        if name == prefix or name.startswith(prefix + "."):
            out.append(module)
    return out


def rebuild_views(*, module_prefix: Optional[str] = None) -> int:
    """按 `(order, 登记序)` 依次调用已登记的重建函数；返回**成功重建的函数个数**。

    每个函数可返回 `[(旧对象, 新对象), …] | None`（**序列**，不是 `{旧: 新}` 映射：

    * `None` → 无替换（函数自己用 `update_in_place` 就地更新了它的容器）；
    * 序列里的每条 → **非容器**的别名回填：引擎在 `module_prefix` 前缀的已加载模块里，
      把值 `is` 旧对象的全局名改指新对象。旧对象可以是不可哈希的（`dict` / `list` / `set`
      之外都行）；两条的旧对象允许 `==` 相等（按身份区分，序列不去重）。容器请走
      `update_in_place`，不放进这个序列。全部函数跑完后统一施加 —— 故任一函数看到的都是
      本轮的终值。

    任一步失败 → `ViewsRebuildError`（点名函数 / 登记序 / 原因 / 已完成数量），
    **不吞成成功**（fail-closed）。
    """
    done = 0
    replacements: list = []
    for order, _seq, fn in sorted(_live(), key=lambda row: (row[0], row[1])):
        try:
            mapping = fn()
        except Exception as exc:                                   # noqa: BLE001
            name = "%s.%s" % (getattr(fn, "__module__", "?"),
                              getattr(fn, "__qualname__", repr(fn)))
            raise ViewsRebuildError(name, order, done,
                                    "%s: %s" % (type(exc).__name__, exc)) from exc
        if mapping:
            replacements.extend(mapping)
        done += 1
    if replacements:
        _apply_replacements(replacements, module_prefix)
    return done
