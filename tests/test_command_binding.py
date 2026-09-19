#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：指令**声明式绑定**（`saintess_engine.command.binding` 的 `bind` 族）。

跑法：python tests/test_command_binding.py
退出码：0 = 全绿；1 = 有失败。

钉住的东西
----------
1. **三种 `call` 各一条正证**（`run` / `messages` / `sync`）：实现体签名 = 取参帧，
   返回值 = 行列表；`run` 的「只调 `plain_result` 不 yield」退路也钉住。
2. **调用帧**：`handler(*lead(env), sink, *args)` 与 `args` 声明顺序逐位对齐。
3. **失败路径逐条反证**（全部**装载期**抛 `BindError`，绝不静默降级）：
   未知 `call` / 未知 `args` 槽位 / `bind` 未知键 / handler 解析不到 / handler 不可调用 /
   `sync` 模式命中真 `await` / `messages` 模式拿到非 async generator。
4. **声明侧 fail-closed**：坏 `bind` 经 `CommandSpec.from_dict` / `CommandRegistry.load`
   当场抛（不是等到运行期少一条命令）；合法 `bind` 能 round-trip。
5. **文本收集替身 `TextSink`**：`plain_result` 收行并返回文本；`message_str` 读完真对象、
   本地赋值后以本地为准且不写回；其余属性读写都落真对象。

注：正证夹具把「实参帧」记在**真事件对象**上（`sink.<名> = …` 会被替身代理到真对象）
—— 这样不必跨模块共享全局（`bind_handler` 按名 import，会拿到本文件的**第二个模块实例**）。
"""
import asyncio
import os
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine.command import (                                        # noqa: E402
    ARG_TOKENS, CALL_MODES, BindError, BindSpec, CommandRegistry, CommandSpec,
    TextSink, bind_handler)

passed = failed = 0


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


# ---------------------------------------------------------------- 夹具
class _Env:
    """最小 `Env` 替身（只补 `bind.args` 的三个槽位 + `raw`）。"""

    def __init__(self, raw=None, group_id="g1", uid="u1", player=None):
        self.raw = raw
        self.group_id = group_id
        self.uid = uid
        self.player = player if player is not None else {}


class _Event:
    """最小平台事件替身：`plain_result` 之外只有 `message_str` 与一个私有方法。"""

    def __init__(self, msg="原始消息"):
        self.message_str = msg

    def get_message_str(self):
        return self.message_str

    def stop_event(self):
        self._stopped = True


def env_with(raw=None, **kw):
    """带真事件的 `_Env`（正证要把实参帧记在 `raw` 上）。"""
    return _Env(raw=raw if raw is not None else _Event(), **kw)


# ---------------------------------------------------------------- 正证用实现体
# 调用帧 = `handler(*lead(env), sink, *args)`；下面这批不带 lead ⇒ 第 1 个形参就是 sink。
async def _agen_run(sink, group_id, uid, player):
    """`run` 正证：yield 三行（含空行，验证空行不被吞），并把实参帧记到真事件上。"""
    sink.seen = (group_id, uid, player)
    yield "r1"
    yield ""
    yield "r3"


async def _agen_sink_only(sink, group_id):
    """`run` 退路：只调 `plain_result`、一个都不 yield。"""
    sink.plain_result("sink-only")
    for _ in ():
        yield _


async def _agen_resume(sink):
    """`run` 的纯协程链：`await` 一个普通协程后继续 yield。"""
    value = await _inner()
    yield "resumed:" + value


async def _inner():
    return "inner"


@types.coroutine
def _gen_coroutine():
    """生成器式协程：`await` 它会把 yield 交回驱动器（跑完要驱动器回送）。"""
    yield "tick"
    return "gen-done"


async def _leaf():
    return "leaf-done"


class _Handoff:
    """`await` 它时把**协程对象本身**交回驱动器 —— 覆盖「递归驱动后回送」那一支。"""

    def __await__(self):
        value = yield _leaf()
        return value


async def _agen_nested(sink):
    """`run` 的递归驱动：`await` 交出协程对象（驱动器必须递归驱动后回送）。"""
    value = await _Handoff()
    yield "nested:" + value


async def _agen_messages(sink, group_id, uid):
    """`messages` 正证：async generator 逐条产出。"""
    sink.seen = (group_id, uid)
    yield "m1"
    yield "m2"


async def _agen_sync(sink, group_id):
    """`sync` 正证：零 await 的 async generator。"""
    sink.seen = (group_id,)
    yield "s1"
    yield "s2"


class _Suspends:
    """真挂起：`await` 它会把控制权交回驱动器 —— 「零 await」模式必须在此报错。"""

    def __await__(self):
        yield self
        return "resumed"


async def _agen_awaits(sink):
    """`sync` 反证：命中真 await（挂起）。"""
    await _Suspends()
    yield "never"


async def _agen_frame(shell, sink, uid):
    """调用帧正证：`lead` 给的宿主句柄在最前，sink 紧随，args 其后。"""
    sink.frame = (shell, uid)
    yield "frame"


async def _plain_coro(env):
    """`messages` 反证：交的既不是 async generator 也不是协程。"""
    return ["not-a-gen"]


def _sync_list(sink):
    """`messages` 反证夹具：交一个普通 list。"""
    return ["not-a-gen"]


#: 供「handler 不可调用」反证用：模块级非可调用对象
NOT_CALLABLE = ["既不可调用，也不该被静默跳过"]

_MOD = "test_command_binding"


def _raises(fn, *a, **kw):
    """调用必须抛 `BindError`（其它异常 = 反证不成立）。"""
    try:
        fn(*a, **kw)
    except BindError:
        return True
    except Exception:                                                    # noqa: BLE001
        return False
    return False


# ---------------------------------------------------------------- 1 三种 call 正证
def t1_three_calls():
    print("\n[1] 三种 call 各一条正证：run / messages / sync")

    ev = _Event()
    fn = bind_handler(BindSpec(handler=_MOD + ":_agen_run", call="run",
                               args=("group_id", "uid", "player")))
    check("run：同步调用（不是协程函数）", not asyncio.iscoroutinefunction(fn))
    out = fn(_Env(raw=ev, player={"name": "P"}))
    check("run：返回行列表（空行原样保留）", out == ["r1", "", "r3"], out)
    check("run：取参帧按声明顺序对齐 args", ev.seen == ("g1", "u1", {"name": "P"}), ev.seen)

    fn2 = bind_handler(BindSpec(handler=_MOD + ":_agen_sink_only", call="run",
                                args=("group_id",)))
    check("run：一个都不 yield → 退回替身收集到的行",
          fn2(env_with()) == ["sink-only"], fn2(env_with()))

    fn3 = bind_handler(BindSpec(handler=_MOD + ":_agen_resume", call="run"))
    check("run：await 纯协程递归驱动后回送", fn3(env_with()) == ["resumed:inner"],
          fn3(env_with()))

    fn4 = bind_handler(BindSpec(handler=_MOD + ":_agen_nested", call="run"))
    check("run：await 交出协程对象（驱动器递归驱动后回送）",
          fn4(env_with()) == ["nested:leaf-done"], fn4(env_with()))

    aev = _Event()
    afn = bind_handler(BindSpec(handler=_MOD + ":_agen_messages", call="messages",
                                args=("group_id", "uid")))
    check("messages：处理器是协程函数（调用方 await）", asyncio.iscoroutinefunction(afn))
    aout = asyncio.run(afn(_Env(raw=aev)))
    check("messages：await 消费 async generator → 行列表", aout == ["m1", "m2"], aout)
    check("messages：取参帧按声明顺序对齐 args", aev.seen == ("g1", "u1"), aev.seen)

    sev = _Event()
    sfn = bind_handler(BindSpec(handler=_MOD + ":_agen_sync", call="sync",
                                args=("group_id",)))
    check("sync：同步调用", not asyncio.iscoroutinefunction(sfn))
    check("sync：零 await 的 async generator 被同步取空",
          sfn(_Env(raw=sev)) == ["s1", "s2"], sfn(_Env(raw=sev)))
    check("sync：取参帧同样按声明顺序", sev.seen == ("g1",), sev.seen)


# ---------------------------------------------------------------- 2 调用帧 / lead
def t2_call_frame():
    print("\n[2] 调用帧：handler(*lead(env), sink, *args)")
    ev = _Event()
    fn = bind_handler(BindSpec(handler=_MOD + ":_agen_frame", call="run", args=("uid",)),
                      lead=lambda env: ("SHELL",))
    out = fn(_Env(raw=ev, uid="u9"))
    check("lead 在最前、sink 紧随、args 其后", ev.frame == ("SHELL", "u9"), ev.frame)
    check("lead 版同样返回行列表", out == ["frame"], out)


# ---------------------------------------------------------------- 3 反证（fail-closed）
def t3_fail_closed():
    print("\n[3] 失败路径逐条反证：一律 BindError（装载期，不静默降级）")

    check("未知 call → 装载期报错",
          _raises(BindSpec.from_data, {"handler": "json:dumps", "call": "spawn"}))
    check("未知 args 槽位 → 装载期报错",
          _raises(BindSpec.from_data, {"handler": "json:dumps", "args": ["player_id"]}))
    check("bind 出现未知键 → 装载期报错（拼错 handler 不许静默变「没绑定」）",
          _raises(BindSpec.from_data, {"hander": "json:dumps"}))
    check("handler 缺失 / 空 → 装载期报错",
          _raises(BindSpec.from_data, {}) and _raises(BindSpec.from_data, {"handler": "  "}))
    check("bind 不是对象 → 装载期报错", _raises(BindSpec.from_data, ["json:dumps"]))
    check("args 不是序列 → 装载期报错",
          _raises(BindSpec.from_data, {"handler": "json:dumps", "args": 3}))

    check("handler 解析不到（模块在、名字不在）→ BindError",
          _raises(bind_handler, BindSpec(handler="json:__no_such_name__")))
    check("handler 解析不到（模块不在）→ BindError",
          _raises(bind_handler, BindSpec(handler="no_such_module_at_all:fn")))
    check("handler 不可调用 → BindError", _raises(bind_handler, BindSpec(handler="json:encoder")))
    check("handler 指向模块级非可调用对象 → BindError",
          _raises(bind_handler, BindSpec(handler=_MOD + ":NOT_CALLABLE")))
    check("resolve 口抛错 → BindError（原因原样带出）",
          _raises(bind_handler, BindSpec(handler="x:y"),
                  resolve=lambda ref: (_ for _ in ()).throw(RuntimeError("取件失败"))))

    awaits = bind_handler(BindSpec(handler=_MOD + ":_agen_awaits", call="sync"))
    check("sync 命中真 await → BindError", _raises(awaits, env_with()))

    msgs = bind_handler(BindSpec(handler=_MOD + ":_sync_list", call="messages"))
    check("messages 拿到非 async generator → BindError", _raises(asyncio.run, msgs(env_with())))

    check("词汇表就是这三个（不扩张）", CALL_MODES == ("run", "messages", "sync"), CALL_MODES)
    check("取参词汇表就是这三个（不扩张）", ARG_TOKENS == ("group_id", "uid", "player"), ARG_TOKENS)


# ---------------------------------------------------------------- 4 声明侧
def t4_declaration_side():
    print("\n[4] 声明侧 fail-closed + round-trip（装载期就抛，不留半张表）")
    good = {"key": "k", "patterns": ["^k$"],
            "bind": {"handler": "json:dumps", "call": "run", "args": ["uid"]}}
    spec = CommandSpec.from_dict(good)
    check("合法 bind 装进声明", isinstance(spec.bind, BindSpec) and spec.bind.call == "run")
    check("to_dict 带回 bind（round-trip 稳定）", spec.to_dict()["bind"] == good["bind"],
          spec.to_dict().get("bind"))
    check("缺省 call = run", BindSpec.from_data({"handler": "json:dumps"}).call == "run")
    check("缺省 args = 空", BindSpec.from_data({"handler": "json:dumps"}).args == ())
    check("无 bind 的声明 bind 为 None", CommandSpec.from_dict(
        {"key": "k2", "patterns": ["^k2$"]}).bind is None)

    check("CommandRegistry.load 遇坏 bind 当场抛（不留半成品注册表）",
          _raises(CommandRegistry(name="t4").load,
                  {"k": {"patterns": ["^k$"],
                         "bind": {"handler": "json:dumps", "call": "teleport"}}}))

    reg = CommandRegistry(name="t4b")
    reg.load({"k": good})
    check("注册表把 bind 原样带在声明上", reg.get("k").bind.args == ("uid",))


# ---------------------------------------------------------------- 5 TextSink
def t5_text_sink():
    print("\n[5] 文本收集替身 TextSink：只接管 plain_result / message_str")
    ev = _Event("原始消息")
    sink = TextSink(ev)
    check("plain_result 收行并返回文本本身",
          sink.plain_result("甲") == "甲" and sink.lines == ["甲"])
    check("message_str 未本地赋值 → 读真对象", sink.message_str == "原始消息")
    check("get_message_str 未本地赋值 → 问真对象", sink.get_message_str() == "原始消息")
    sink.message_str = "改写后"
    check("message_str 本地赋值后以本地为准",
          sink.message_str == "改写后" and sink.get_message_str() == "改写后")
    check("本地赋值不写回真对象", ev.message_str == "原始消息", ev.message_str)
    sink.stop_event()
    check("其余方法逐字代理真对象", getattr(ev, "_stopped", False) is True)
    sink.other = 7
    check("其余属性写入落真对象", getattr(ev, "other", None) == 7)
    check("真对象没有的属性照旧 AttributeError", not hasattr(sink, "__definitely_absent__"))
    check("lines 是本地状态（不写回真对象）",
          sink.lines == ["甲"] and not hasattr(ev, "lines"))


def main():
    t1_three_calls()
    t2_call_frame()
    t3_fail_closed()
    t4_declaration_side()
    t5_text_sink()
    print(f"\n== 结果：通过 {passed} / 共 {passed + failed} ==")
    if failed:
        return 1
    print("全绿 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
