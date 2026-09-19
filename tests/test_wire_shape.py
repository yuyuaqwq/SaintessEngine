#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""wire 门禁：注入句柄 / 惰性模块 / 观测口 / 名字面 / 零知识 / 边界。

跑法：python tests/test_wire_shape.py
退出码：0 = 全绿；1 = 有失败。

钉住的地方（都是「改了就静默变行为」的）：
  ① **fail-closed**：取不到句柄 / 注入面 → `WireMissing` 且消息**点名**（绝不返回 None）
  ② **惰性**：登记不加载；首次取属性才加载，且只加载一次（计数器证明）
  ③ **同源**：传进去什么拿出来就是什么（同一只对象，不是拷贝）
  ④ **只读视图**：`handles()` 改不动
  ⑤ **零知识**：wire 源码里不得出现内容侧取值（注释 / docstring 一并算）
  ⑥ **边界**：wire 不 import 任何包内模块（只标准库）
"""
import ast
import os
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from collections.abc import Mapping                                                    # noqa: E402

from saintess_engine.wire import LazyRef, Surface, Wire, WireMissing                   # noqa: E402

WIRE_DIR = os.path.join(ROOT, "saintess_engine", "wire")
WIRE_SRC = os.path.join(WIRE_DIR, "__init__.py")

passed = failed = 0


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


def _boom():
    raise RuntimeError("取值器坏了")


# ---------------------------------------------------------------- 1 缺句柄
def t1_handle_fail_closed():
    print("\n[1] 缺句柄 fail-closed：未 bind → WireMissing（点名，不返回 None）")
    w = Wire()
    try:
        got = w.handle("db_path")
        check("未 bind → WireMissing（不返回 None）", False, f"返回了 {got!r}")
    except WireMissing as exc:
        check("未 bind → WireMissing（不返回 None）", True)
        check("★ 消息点名 `db_path`", "db_path" in str(exc), repr(str(exc)))
        check("name 属性同值（可编程判定）", exc.name == "db_path", repr(exc.name))
    check("bound() 未注入 → False", w.bound() is False)

    obj = object()
    w.bind(db_path=obj)
    check("bind 后 handle 取到", w.handle("db_path") is obj)
    check("bound() 有注入 → True", w.bound() is True)

    w.bind(clock=None)                      # None = 没给
    try:
        w.handle("clock")
        check("bind(None) = 没给 → 仍 WireMissing", False, "没抛")
    except WireMissing as exc:
        check("bind(None) = 没给 → 仍 WireMissing", True)
        check("消息点名 `clock`", "clock" in str(exc), repr(str(exc)))

    try:
        w.handle("")
        check("空名字 → 报错（不静默）", False, "没抛")
    except WireMissing:
        check("空名字 → 报错（不静默）", True)


# ---------------------------------------------------------------- 2 观测口
def t2_observability():
    print("\n[2] 观测口同理：未 bind → WireMissing（不是 None）")
    w = Wire()
    for attr in ("log", "tlog"):
        try:
            got = getattr(w, attr)
            check(f"未 bind {attr} → WireMissing", False, f"返回了 {got!r}")
        except WireMissing as exc:
            check(f"未 bind {attr} → WireMissing", True)
            check(f"消息点名 `{attr}`", attr in str(exc), repr(str(exc)))

    try:
        w.emit("some_kind", n=1)
        check("未 bind tlog → emit 也 WireMissing", False, "没抛")
    except WireMissing as exc:
        check("未 bind tlog → emit 也 WireMissing", True)
        check("emit 消息点名 `tlog`", "tlog" in str(exc), repr(str(exc)))

    seen = []

    class _Flow:
        def emit(self, kind, **fields):
            seen.append((kind, fields))
            return "written"

    log_obj = object()
    w.bind(log=log_obj, tlog=_Flow())
    check("bind 后 log 同源", w.log is log_obj)
    check("★ emit 透传 tlog.emit（kind + 字段原样）",
          w.emit("some_kind", n=1) == "written" and seen == [("some_kind", {"n": 1})], str(seen))

    w2 = Wire()
    w2.bind(tlog=object())
    try:
        w2.emit("some_kind")
        check("tlog 无 emit → WireMissing（不静默丢流水）", False, "没抛")
    except WireMissing as exc:
        check("tlog 无 emit → WireMissing（不静默丢流水）", True)
        check("消息点名 `tlog`", "tlog" in str(exc), repr(str(exc)))

    class _Angry:
        def emit(self, kind, **fields):
            raise ValueError("sink 挂了")

    w3 = Wire()
    w3.bind(tlog=_Angry())
    try:
        w3.emit("some_kind")
        check("tlog.emit 自身异常 → 原样上抛（本口不吞）", False, "没抛")
    except ValueError:
        check("tlog.emit 自身异常 → 原样上抛（本口不吞）", True)


# ---------------------------------------------------------------- 3 惰性
def t3_lazy():
    print("\n[3] 惰性：登记不加载 / 首次取属性才加载 / 只加载一次")
    calls = []
    mod = types.SimpleNamespace(VALUE=7)

    def loader():
        calls.append(1)
        return mod

    w = Wire()
    ref = w.lazy("some_mod", loader)
    check("★ 登记后 loader 未被调用", calls == [], str(calls))
    check("ref 是 LazyRef 且未加载", isinstance(ref, LazyRef) and ref.loaded is False)
    check("★ 首次 get() 触发加载（恰好一次）", ref.get() is mod and calls == [1], str(calls))
    check("★ 第二次 get() 不再调 loader", ref.get() is mod and calls == [1], str(calls))
    check("属性转发到已加载对象", ref.VALUE == 7)
    check("转发也不再多调 loader", calls == [1], str(calls))
    check("name / loaded 可读（不触发加载）", ref.name == "some_mod" and ref.loaded is True)
    check("repr 不触发加载", "LazyRef" in repr(w.lazy("repr_probe", loader)) and calls == [1],
          str(calls))

    calls.clear()
    w.lazy("another_mod", loader)
    check("handle(惰性名) 之前 loader 未被调用", calls == [], str(calls))
    check("★ handle(惰性名) 触发加载（同一个口）",
          w.handle("another_mod") is mod and calls == [1], str(calls))

    boom_calls = []

    def boom_loader():
        boom_calls.append(1)
        raise ValueError("内容侧装配坏了")

    r3 = w.lazy("boom_mod", boom_loader)
    errs = []
    for _ in range(2):
        try:
            r3.get()
            errs.append("NO-RAISE")
        except ValueError as exc:
            errs.append(str(exc))
        except Exception as exc:                                   # noqa: BLE001
            errs.append("WRONG:" + type(exc).__name__)
    check("★ loader 抛错 → 原样上抛（两次都是 ValueError）",
          errs == ["内容侧装配坏了"] * 2, str(errs))
    check("★ 失败不缓存（两次都真的调了 loader，可重试）", boom_calls == [1, 1], str(boom_calls))

    try:
        w.lazy("none_mod", lambda: None).get()
        check("loader 返回 None → WireMissing（点名）", False, "没抛")
    except WireMissing as exc:
        check("loader 返回 None → WireMissing（点名）", "none_mod" in str(exc), repr(str(exc)))

    try:
        w.lazy("some_mod", loader)
        check("同名重复登记 → ValueError（不静默覆盖）", False, "没抛")
    except ValueError:
        check("同名重复登记 → ValueError（不静默覆盖）", True)

    try:
        w.lazy("later_bound", loader)
        w.bind(later_bound=1)
        check("惰性名再 bind → ValueError（一个名字一种来源）", False, "没抛")
    except ValueError:
        check("惰性名再 bind → ValueError（一个名字一种来源）", True)

    try:
        w.lazy("bad", "not-callable")
        check("loader 不可调用 → TypeError", False, "没抛")
    except TypeError:
        check("loader 不可调用 → TypeError", True)


# ---------------------------------------------------------------- 4 名字面
def t4_surface():
    print("\n[4] 名字面：命中 / 未知 KeyError / missing 自检 / 别名")
    w = Wire()
    s = w.surface({"a": 1, "b": lambda: 2, "c": lambda: None, "d": _boom},
                  aliases={"alpha": "a"})
    check("names() 保序（声明序，不含别名）", s.names() == ["a", "b", "c", "d"], str(s.names()))
    check("has() 认声明名与别名，不认未知名",
          s.has("a") and s.has("alpha") and not s.has("zz"))
    check("resolve 命中：原值", s.resolve("a") == 1)
    check("resolve 命中：取值器", s.resolve("b") == 2)
    check("★ 别名 → 声明名", s.resolve("alpha") == 1)

    try:
        s.resolve("zz")
        check("★ 未知名字 → KeyError", False, "没抛")
    except KeyError as exc:
        check("★ 未知名字 → KeyError", True)
        check("KeyError 点名 `zz`", "zz" in str(exc), str(exc))

    try:
        s.resolve("c")
        check("声明了但取不到（返回值 None）→ WireMissing", False, "没抛")
    except WireMissing as exc:
        check("声明了但取不到（返回值 None）→ WireMissing", True)
        check("WireMissing 点名 `c`", "c" in str(exc), repr(str(exc)))

    try:
        s.resolve("d")
        check("取值器抛错 → WireMissing（保留原因）", False, "没抛")
    except WireMissing as exc:
        check("取值器抛错 → WireMissing（保留原因）", True)
        check("异常链保留原因（__cause__ 是原异常）",
              isinstance(exc.__cause__, RuntimeError), repr(exc.__cause__))

    check("★ missing() 只列「声明了但取不到」（保序）", s.missing() == ["c", "d"], str(s.missing()))
    check("干净的名单 → missing() 为空", w.surface({"x": 1}).missing() == [])

    custom = w.surface({"m": "content.some.mod"},
                       getter=lambda src, name: src + "->" + name)
    check("自定义取值器收到（源, 名字）", custom.resolve("m") == "content.some.mod->m")

    try:
        w.surface({"a": 1}, aliases={"x": "nope"})
        check("★ 别名指向未声明名 → 构造即 ValueError", False, "没抛")
    except ValueError:
        check("★ 别名指向未声明名 → 构造即 ValueError", True)

    try:
        w.surface(["a"])
        check("name_src 非映射 → TypeError", False, "没抛")
    except TypeError:
        check("name_src 非映射 → TypeError", True)

    check("Surface 可独立构造（不依赖 Wire）", Surface({"k": lambda: 3}).resolve("k") == 3)


# ---------------------------------------------------------------- 5 同源
def t5_identity():
    print("\n[5] 句柄同源：传进去什么拿出来就是什么（不是拷贝）")
    w = Wire()
    obj = object()
    data = {"k": [1, 2]}
    w.bind(thing=obj, data=data)
    check("★ handle 返回同一只对象", w.handle("thing") is obj)
    check("★ 映射句柄也是同一只（不浅拷贝）", w.handle("data") is data)
    data["k"].append(3)
    check("改原对象，面上立刻看得见（不是快照）", w.handle("data")["k"] == [1, 2, 3],
          str(w.handle("data")))
    check("只读视图里的值也是同一只", w.handles()["data"] is data)


# ---------------------------------------------------------------- 6 只读视图
def t6_readonly_view():
    print("\n[6] 只读视图：handles() 改不动")
    w = Wire()
    w.bind(a=1)
    view = w.handles()
    check("是 Mapping（映射视图）", isinstance(view, Mapping))
    try:
        view["a"] = 2
        check("★ 写入 → TypeError（改不动）", False, "竟然改成功了")
    except TypeError:
        check("★ 写入 → TypeError（改不动）", True)
    try:
        view["b"] = 3
        check("★ 新增键 → TypeError（改不动）", False, "竟然加进去了")
    except TypeError:
        check("★ 新增键 → TypeError（改不动）", True)
    check("值没被改掉", w.handle("a") == 1 and view["a"] == 1)
    try:
        view.update({"b": 2})
        check("update → 报错（改不动）", False, "竟然成功了")
    except AttributeError:
        check("update → 报错（改不动）", True)
    check("视图里没有偷偷多出来的键", sorted(view) == ["a"], str(sorted(view)))
    w.bind(b=2)
    check("视图是活的（后续 bind 反映出来）", view["b"] == 2)


# ---------------------------------------------------------------- 7 零知识
#: 内容侧取值（游戏身份 / 具体名词）—— 引擎源码里一个都不许有（含注释与 docstring）
BANNED = ("物品", "怪物", "公会", "职业", "奥兰迪亚", "余烬", "装备", "金币",
          "副本", "队伍", "等级", "dragonfall", "orlandia", "guild", "profession",
          "dungeon", "monster", "npc", "gold", "equip")


def t7_zero_knowledge():
    print("\n[7] 零知识：wire 源码里不得出现内容侧取值（注释/docstring 一并算）")
    bad = []
    for root, _dirs, files in os.walk(WIRE_DIR):
        if "__pycache__" in root:
            continue
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(root, fn)
            with open(path, encoding="utf-8") as fh:
                for i, line in enumerate(fh.read().splitlines(), 1):
                    low = line.lower()
                    for b in BANNED:
                        if (b in low) if b.isascii() else (b in line):
                            bad.append(f"{fn}:{i}:{b}")
    check("★ 源码无内容侧取值（形状名一律通用名词）", not bad, str(bad[:6]))
    check("扫描到 wire 源码文件", os.path.isfile(WIRE_SRC))


# ---------------------------------------------------------------- 8 边界
def t8_boundaries():
    print("\n[8] 边界：不 import 包内模块（只标准库）+ docstring 写了「有意不做的事」")
    with open(WIRE_SRC, encoding="utf-8") as fh:
        src = fh.read()
    tree = ast.parse(src)
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in sys.stdlib_module_names:
                    bad.append(a.name)
        elif isinstance(node, ast.ImportFrom):
            dotted = "." * node.level + (node.module or "")
            root = (node.module or "").split(".")[0]
            if node.level or root not in sys.stdlib_module_names:
                bad.append(dotted)
    check("★ 零包内 import（只标准库 / 相对导入也没有）", not bad, str(bad))

    mod_doc = ast.get_docstring(tree) or ""
    check("模块 docstring 含「有意不做的事」边界段", "有意不做的事" in mod_doc)
    for phrase in ("不认具体句柄名", "不做依赖注入容器", "不做单例注册表",
                   "不 import 任何包内模块"):
        check(f"边界写明：{phrase}", phrase in mod_doc)


def main():
    print("== wire 门禁：注入句柄 / 惰性模块 / 观测口 / 名字面 / 零知识 ==")
    t1_handle_fail_closed()
    t2_observability()
    t3_lazy()
    t4_surface()
    t5_identity()
    t6_readonly_view()
    t7_zero_knowledge()
    t8_boundaries()
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
