#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：命令**处理器登记**（`saintess_engine.command.registry` 的 bind 族）。

跑法：python tests/test_command_handlers.py
退出码：0 = 全绿；1 = 有失败。

三条不变量（对应设计稿 §2 的三条判据）：
  1. **同步 / 协程都能登记取出**：`handler_of()` 返回**原对象**（引擎不包装），
     `is_async()` 判定与 Python 侧的协程函数口径一致。
  2. **重复 key 默认抛**（与 `register()` 同口径：`ValueError` + `replace=True` 才覆盖）；
     被拒的那次**不留半个覆盖**。
  3. **未登记一律 `HandlerMissing` 并点名 key**（不是 None、不静默降级）——
     `handler_of` / `is_async` / `binding_of` 三条取件路都 fail-closed。

另外钉住「声明与处理器分开」：`register()` 的声明不产生处理器；`bind()` 的处理器
不产生声明 —— 两条路各自 fail-closed，谁都不替谁补全。
"""
import asyncio
import functools
import inspect
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine.command import (                                      # noqa: E402
    CommandBinding, CommandRegistry, CommandSpec, HandlerMissing)
from saintess_engine.command import registry as _registry_mod              # noqa: E402

passed = failed = 0


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


# ---------------------------------------------------------------- 回调样本
def sync_fn(env):
    """同步处理器：返回「已算好的行」（引擎不该动它）。"""
    return ["sync-line"]


async def async_fn(env):
    """协程处理器：原样登记，调用方自己 await。"""
    return ["async-line"]


async def async_gen_fn(env):
    """异步生成器函数：调用得 async generator（该 async for，不是 await）。"""
    yield "piece"


class SyncCallable:
    def __call__(self, env):
        return ["sync-call"]


class AsyncCallable:
    async def __call__(self, env):
        return ["async-call"]


# ---------------------------------------------------------------- 1 登记与判定
def t1_bind_sync_async():
    print("\n[1] 同步 / 协程 handler 都能登记取出，is_async 判定正确")
    reg = CommandRegistry(name="t1")
    check("bind 返回 None（登记件不回带）", reg.bind("sync", sync_fn) is None)
    reg.bind("coro", async_fn, guards=("hook:alpha",), params=("cmd=panel", "page"))
    reg.bind("partial_coro", functools.partial(async_fn))
    reg.bind("sync_call", SyncCallable())
    reg.bind("coro_call", AsyncCallable())
    reg.bind("agen", async_gen_fn)

    check("★ 同步 handler 取出即本体（同对象，未被包装）", reg.handler_of("sync") is sync_fn)
    check("★ 协程 handler 取出即本体（同对象，未被包装）", reg.handler_of("coro") is async_fn)
    check("is_async：同步函数 → False", reg.is_async("sync") is False)
    check("is_async：async def → True", reg.is_async("coro") is True)
    check("is_async：partial(async def) → True", reg.is_async("partial_coro") is True)
    check("is_async：同步 __call__ 对象 → False", reg.is_async("sync_call") is False)
    check("is_async：async __call__ 对象 → True", reg.is_async("coro_call") is True)
    check("is_async：异步生成器函数 → False（该 async for，不是 await）",
          reg.is_async("agen") is False)

    check("同步 handler 调用的返回值原样（不 render）",
          reg.handler_of("sync")(None) == ["sync-line"])
    out = reg.handler_of("coro")(None)
    try:
        check("★ 协程 handler 调用得 awaitable（不是已算好的行）", inspect.isawaitable(out))
        check("await 后拿到 handler 自己的返回值", asyncio.run(out) == ["async-line"])
    except Exception:                                              # noqa: BLE001
        out.close()
        raise
    check("★ 绑定后 handler 仍是协程函数（引擎没把它包成同步壳）",
          inspect.iscoroutinefunction(reg.handler_of("coro")) is True)
    check("CommandBinding.is_async 与 CommandRegistry.is_async 一致",
          all(b.is_async is reg.is_async(k) for k, b in reg.bindings()))


# ---------------------------------------------------------------- 2 重复 key
def t2_duplicate_key():
    print("\n[2] 重复 key → 默认抛（与 register 同口径）；replace=True 才覆盖")
    reg = CommandRegistry(name="t2")
    reg.bind("alpha", sync_fn, guards=("g1",))
    reg.bind("beta", sync_fn)

    try:
        reg.bind("alpha", async_fn)
        check("重复 key → 抛（与既有 register 同口径）", False, "没抛")
    except ValueError as e:
        check("★ 重复 key → ValueError（与既有 register 同口径）", True)
        check("报错点名 key 并提示 replace=True",
              "'alpha'" in str(e) and "replace=True" in str(e), str(e))
    check("★ 被拒的那次不留半个覆盖（handler 与元数据都没动）",
          reg.handler_of("alpha") is sync_fn and reg.binding_of("alpha").guards == ("g1",))
    check("被拒后 is_async 仍是旧判定", reg.is_async("alpha") is False)

    # 同口径对照：声明侧同 key 也抛 ValueError
    cmp = CommandRegistry()
    cmp.register(CommandSpec(key="alpha", patterns=("^a$",)))
    try:
        cmp.register(CommandSpec(key="alpha", patterns=("^a2$",)))
        spec_dup = False
    except ValueError:
        spec_dup = True
    check("对照：声明 register() 同 key 也是 ValueError", spec_dup)

    reg.bind("alpha", async_fn, replace=True)
    check("replace=True 才覆盖（handler 换新）", reg.handler_of("alpha") is async_fn)
    check("replace=True 后 is_async 跟着换", reg.is_async("alpha") is True)
    check("★ 覆盖不改 bind 顺序", [k for k, _ in reg.bindings()] == ["alpha", "beta"])

    def third(env):
        return ["third"]

    reg.bind("alpha", third, replace=True)
    check("再 replace 仍只留最后一条", reg.handler_of("alpha") is third)


# ---------------------------------------------------------------- 3 未登记
def t3_missing_is_fail_closed():
    print("\n[3] 未登记取处理器 → HandlerMissing（点名 key，不是 None）")
    reg = CommandRegistry(name="t3")
    reg.bind("known", sync_fn)

    for label, call in (
            ("handler_of", lambda: reg.handler_of("nope")),
            ("is_async", lambda: reg.is_async("nope")),
            ("binding_of", lambda: reg.binding_of("nope"))):
        try:
            got = call()
            check(f"{label} 未登记 → HandlerMissing（不是 None）", False, f"得到 {got!r}")
        except HandlerMissing as e:
            check(f"{label} 未登记 → HandlerMissing", True)
            check(f"{label} 报错点名 key", e.key == "nope" and "'nope'" in str(e), str(e))
            check(f"{label} 的 HandlerMissing 是 RuntimeError 子类", isinstance(e, RuntimeError))

    check("已登记的照常取得（fail-closed 只针对没登记的）", reg.handler_of("known") is sync_fn)

    # 声明 ≠ 处理器：声明过但没 bind 的 key 一样取不到
    declared = CommandRegistry(name="t3b")
    declared.register(CommandSpec(key="declared", patterns=("^d$",)))
    try:
        declared.handler_of("declared")
        check("★ 声明不代替处理器：声明过但没 bind → HandlerMissing", False, "取到了")
    except HandlerMissing:
        check("★ 声明不代替处理器：声明过但没 bind → HandlerMissing", True)
    # 反过来：bind 过但没声明的 key 也能取（与声明分离）
    rebind = CommandRegistry(name="t3c")
    rebind.bind("unbound", sync_fn)
    check("bind 不要求先声明（与声明分离）",
          rebind.handler_of("unbound") is sync_fn and rebind.get("unbound") is None
          and rebind.keys() == ())


# ---------------------------------------------------------------- 4 参数非法
def t4_invalid_args():
    print("\n[4] 参数非法 → 点名抛错（不静默收下）")
    reg = CommandRegistry(name="t4")
    for bad in ("", None, 7):
        try:
            reg.bind(bad, sync_fn)
            check(f"key={bad!r} 非法 → 抛错", False, "没抛")
        except ValueError as e:
            check(f"key={bad!r} 非法 → ValueError", True)
            check(f"key={bad!r} 报错点名该值", repr(bad) in str(e), str(e))

    try:
        reg.bind("alpha", "not-callable")
        check("handler 不可调用 → 抛错", False, "没抛")
    except TypeError as e:
        check("handler 不可调用 → TypeError", True)
        check("handler 报错点名 key", "'alpha'" in str(e), str(e))
    check("非法 bind 未落库", reg.bindings() == ())

    reg.bind("beta", sync_fn, guards="hook:alpha")
    check("单个字符串 guards → 一元组（不拆成字符）", reg.binding_of("beta").guards == ("hook:alpha",))
    try:
        reg.bind("gamma", sync_fn, guards=5)
        check("guards 不可迭代 → 抛错", False, "没抛")
    except TypeError as e:
        check("guards 不可迭代 → TypeError 并点名 key", "'gamma'" in str(e), str(e))
    check("guards 非法时未落库", "gamma" not in [k for k, _ in reg.bindings()])


# ---------------------------------------------------------------- 5 元数据与形状
def t5_binding_metadata():
    print("\n[5] 绑定元数据：guards / params 可原样取回；公开形状与规格一致")
    reg = CommandRegistry(name="t5")
    reg.bind("alpha", sync_fn, guards=("hook:alpha", "hook:beta"),
             params=("cmd=panel", "page"))
    reg.bind("plain", sync_fn)
    b = reg.binding_of("alpha")
    check("binding_of 返回 CommandBinding", isinstance(b, CommandBinding))
    check("binding_of：key / handler 对得上", b.key == "alpha" and b.handler is sync_fn)
    check("guards 原样存档", b.guards == ("hook:alpha", "hook:beta"), b.guards)
    check("params 原样存档", b.params == ("cmd=panel", "page"), b.params)
    check("缺省元数据 = 空元组", reg.binding_of("plain").guards == ()
          and reg.binding_of("plain").params == ())
    check("bindings() 保 bind 顺序", [k for k, _ in reg.bindings()] == ["alpha", "plain"])
    check("bind 不影响声明面（keys 只数声明）", reg.keys() == () and len(reg) == 0)
    reg.register(CommandSpec(key="alpha", patterns=("^a$",), guards=("hook:alpha",)))
    check("声明与处理器可同 key 并存（两条路互不覆盖）",
          reg.get("alpha").key == "alpha" and reg.handler_of("alpha") is sync_fn)

    # 规格签名：bind(key, handler, *, guards=(), params=(), replace=False)
    sig = inspect.signature(CommandRegistry.bind)
    ps = list(sig.parameters.values())
    names = [p.name for p in ps]
    check("bind 形参名 = (self, key, handler, guards, params, replace)",
          names == ["self", "key", "handler", "guards", "params", "replace"], names)
    check("bind：guards / params / replace 仅限关键字",
          all(ps[i].kind is inspect.Parameter.KEYWORD_ONLY for i in (3, 4, 5)))
    check("bind：guards / params 缺省为 ()，replace 缺省为 False",
          sig.parameters["guards"].default == ()
          and sig.parameters["params"].default == ()
          and sig.parameters["replace"].default is False)
    check("取件三方法的签名收一个位置 key",
          [p.name for p in inspect.signature(CommandRegistry.handler_of).parameters.values()]
          == ["self", "key"]
          and [p.name for p in inspect.signature(CommandRegistry.is_async).parameters.values()]
          == ["self", "key"])

    # 门面一致性：包门面转出的新符号必须与 registry 模块里的是同一对象
    import saintess_engine.command as _cmd
    check("门面转出 HandlerMissing / CommandBinding（与 registry 模块同一对象）",
          HandlerMissing is _registry_mod.HandlerMissing
          and CommandBinding is _registry_mod.CommandBinding)
    check("门面 __all__ 含新符号",
          {"HandlerMissing", "CommandBinding"} <= set(_cmd.__all__))


# ---------------------------------------------------------------- 6 零知识
def t6_zero_knowledge():
    print("\n[6] 零知识：模块与本测试里不得出现具体游戏的身份词")
    try:
        from test_no_game_vocabulary import GAME_TERMS
    except Exception as exc:                                       # noqa: BLE001
        GAME_TERMS = []
        check("词表可复用（取不到即红，不掩盖缺口）", False, repr(exc))
    else:
        check("词表可复用（复用同仓门禁的词表，本文件不写死词）", len(GAME_TERMS) > 0)

    import re as _re

    def _pat(term):
        if term.isascii():
            return _re.compile(r"(?<![A-Za-z0-9_])" + _re.escape(term) + r"(?![A-Za-z0-9_])")
        return _re.compile(_re.escape(term))

    bad = []
    for path in (os.path.join(ROOT, "saintess_engine", "command", "registry.py"),
                 os.path.abspath(__file__)):
        with open(path, encoding="utf-8") as fh:
            txt = fh.read()
        for i, line in enumerate(txt.splitlines(), 1):
            for term in GAME_TERMS:
                if _pat(term).search(line):
                    bad.append("%s:%d [%s]" % (os.path.basename(path), i, term))
    check("★ 引擎模块 + 本测试：零游戏身份词（取值 / 名词）", not bad, str(bad[:6]))


def main():
    print("== command 处理器登记门禁（bind / handler_of / is_async）==")
    t1_bind_sync_async()
    t2_duplicate_key()
    t3_missing_is_fail_closed()
    t4_invalid_args()
    t5_binding_metadata()
    t6_zero_knowledge()
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
