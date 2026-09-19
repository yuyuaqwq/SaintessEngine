#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""日志门面门禁：可拔插契约 + 三个 sink + 结构化上下文 + 引擎侧收敛。

跑法：python tests/test_log.py
退出码：0 = 全绿；1 = 有失败。

为什么这么测（可拔插的判据）
--------------------------
「不配置 = 不存在」这件事，**只测「配置后能拿到东西」等于没测**。
必须先断言**不配置时与标准库逐字一致**（同一 logger 对象、零 handler、级别/propagate 未动），
再断言配置后生效 —— 这是 `reference/roadmap.md` §五写下的口径。
"""
import io
import logging
import os
import re
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine import log as L                              # noqa: E402

passed = failed = 0


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


def _restore():
    """收尾：摘掉门面装的出口 + 前缀还原（用例之间不互相污染）。"""
    L.remove_sinks(prefix="saintess_engine")
    L.configure(prefix=L.DEFAULT_PREFIX)


def _rec(msg, level=logging.INFO, name="n"):
    return logging.LogRecord(name, level, "", 0, msg, (), None)


# ---------------------------------------------------------------- 1 不配置
def t1_unconfigured_is_thin():
    print("\n[1] 不配置 = 标准库薄封装（逐字一致）")
    lg = L.get_logger("battle.turn")
    check("get_logger 返回 stdlib logger **本体**（is 同一对象）",
          lg is logging.getLogger("saintess_engine.battle.turn"), lg.name)
    check("logger_name = <prefix>.<name>", L.logger_name("a.b") == "saintess_engine.a.b")
    check("空 name → 就是 prefix", L.logger_name("") == "saintess_engine")
    check("显式 prefix 只影响本次取名（不改状态）",
          L.logger_name("x", prefix="other") == "other.x"
          and L.logger_name("x") == "saintess_engine.x")
    root_p = logging.getLogger("saintess_engine")
    snap, lv, prop = list(root_p.handlers), root_p.level, root_p.propagate
    L.get_logger("x.y")
    L.logger_name("z")
    check("调用门面不改出口 / 级别 / 冒泡",
          list(root_p.handlers) == snap and root_p.level == lv and root_p.propagate == prop)
    check("不配置时零 handler", snap == [], str(snap))


# ---------------------------------------------------------------- 2 零 sink
def t2_zero_sinks_is_noop():
    print("\n[2] 零 sink = 零行为")
    snap = list(logging.getLogger("saintess_engine").handlers)
    L.configure(sinks=())                       # 空 sinks = 「不管」，不是「清空」
    check("configure(sinks=()) 不改出口", list(logging.getLogger("saintess_engine").handlers) == snap)
    check("没装过 → remove_sinks() 返回 0", L.remove_sinks() == 0)
    check("dispatch([]) 返回 0（什么都不发生）", L.dispatch([], _rec("m")) == 0)


# ---------------------------------------------------------------- 3 configure
def t3_configure_effective_and_idempotent():
    print("\n[3] configure 生效 / 幂等 / 回收")
    P = "t3probe"
    mem = L.MemorySink()
    lg = L.configure(prefix=P, level="INFO", fmt="%(levelname)s|%(message)s",
                     sinks=[mem], propagate=False)
    check("configure 返回 prefix logger", lg is logging.getLogger(P))
    check("prefix 生效（影响后续取名）", L.get_logger("a.b").name == f"{P}.a.b")
    log = L.get_logger("a.b")
    log.info("hello %s", "world")
    log.debug("hidden")
    check("INFO 进 sink", [r.getMessage() for r in mem.records] == ["hello world"])
    check("DEBUG 被级别挡掉", mem.find(level="DEBUG") == [])
    check("级别已设到 prefix logger", logging.getLogger(P).level == logging.INFO)
    check("handler 只挂 prefix 一处（子 logger 冒泡上来）",
          len(logging.getLogger(P).handlers) == 1)
    check("propagate 已关（宿主 root 有 handler 时去重）",
          logging.getLogger(P).propagate is False)

    mem2 = L.MemorySink()
    L.configure(prefix=P, sinks=[mem2])
    check("重复 configure 不叠加 handler（替换）",
          len(logging.getLogger(P).handlers) == 1)
    L.get_logger("c").warning("second")
    check("新 sink 收到、旧 sink 停收",
          len(mem2.records) == 1 and len(mem.records) == 1)
    check("remove_sinks 摘掉 1 个", L.remove_sinks(prefix=P) == 1)
    check("摘掉后 handler 归零", logging.getLogger(P).handlers == [])
    check("再摘返回 0", L.remove_sinks(prefix=P) == 0)
    try:
        L.configure(prefix="   ")
        ok = False
    except ValueError:
        ok = True
    check("空 prefix 报错（不静默接受）", ok)
    _restore()


# ---------------------------------------------------------------- 4 sinks
def t4_sinks():
    print("\n[4] 三个随包 sink")
    buf = io.StringIO()
    s = L.StreamSink(buf, fmt="%(levelname)s|%(message)s")
    s.emit(_rec("warn-me", logging.WARNING))
    check("StreamSink 按 fmt 输出", buf.getvalue() == "WARNING|warn-me\n", repr(buf.getvalue()))
    check("StreamSink 默认流向 stderr", L.StreamSink().stream is sys.stderr)
    s.set_format("%(message)s")
    s.emit(_rec("again", logging.WARNING))
    check("set_format 生效（configure(fmt=…) 走的正是它）",
          buf.getvalue().endswith("again\n"), repr(buf.getvalue()))
    check("format_record 可单独用", L.format_record(_rec("x"), "%(message)s") == "x")

    m = L.MemorySink(limit=2)
    for i in range(3):
        m.emit(_rec(f"m{i}"))
    check("MemorySink limit 保留最近 N",
          [r.getMessage() for r in m.records] == ["m1", "m2"])
    check("MemorySink.messages()", m.messages() == ["m1", "m2"])
    check("MemorySink.find(contains)", [r.getMessage() for r in m.find(contains="m2")] == ["m2"])
    m.clear()
    check("MemorySink.clear()", m.records == [])

    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "sub", "app.log")
        f = L.FileSink(p)
        f.emit(_rec("file-me", logging.ERROR))
        f.close()
        check("FileSink 写文件（父目录自动建）",
              os.path.exists(p) and "file-me" in open(p, encoding="utf-8").read())

        p2 = os.path.join(td, "rot.log")
        f2 = L.FileSink(p2, rotate="size", max_bytes=120, backups=2, fmt="%(message)s")
        for i in range(20):
            f2.emit(_rec(f"line-{i}" * 4))
        f2.close()
        check("FileSink 按大小轮转（生成 .1）", os.path.exists(p2 + ".1"))
        check("轮转份数受 backups 限制（无 .3）", not os.path.exists(p2 + ".3"))
        tail = open(p2, encoding="utf-8").read() + open(p2 + ".1", encoding="utf-8").read()
        check("最新记录未被丢弃", "line-19" in tail)
        check("rotate=int 等价 size 模式",
              L.FileSink(os.path.join(td, "a.log"), rotate=50).max_bytes == 50)
        try:
            L.FileSink(os.path.join(td, "b.log"), rotate="week")
            ok = False
        except ValueError:
            ok = True
        check("非法 rotate 取值报错", ok)


# ---------------------------------------------------------------- 5 bind
def t5_bind_context():
    print("\n[5] 结构化上下文 bind")
    P = "t5probe"
    mem = L.MemorySink()
    L.configure(prefix=P, level="DEBUG", sinks=[mem], propagate=False)
    log = L.get_logger("battle")
    bl = L.bind(log, actor="p1")
    bl.info("hit")
    check("bind 上下文进 record 字段（sink 可按字段查）",
          getattr(mem.records[-1], "actor", None) == "p1")
    bl2 = L.bind(bl, target="e9")
    bl2.info("combo")
    r = mem.records[-1]
    check("bind 可链式叠加", (r.actor, r.target) == ("p1", "e9"))
    bl.bind(actor="p2").info("again")
    check("后写的覆盖先写的", mem.records[-1].actor == "p2")
    check("链式不可变（原 adapter 不受影响）", bl.extra.get("actor") == "p1")
    log.info("from-logger", extra={"elapsed": 3})
    check("与 stdlib extra 共存（同进 record）", getattr(mem.records[-1], "elapsed", None) == 3)
    check("消息正文未被上下文污染", mem.records[-1].getMessage() == "from-logger")

    for bad in ("name", "msg", "levelname", "args", "message", "asctime"):
        try:
            L.bind(log, **{bad: 1})
            ok = False
        except ValueError:
            ok = True
        check(f"保留键 {bad!r} 报错（不静默吞字段）", ok)
    check("RESERVED_KEYS 至少含 message/asctime", {"message", "asctime"} <= L.RESERVED_KEYS)
    check("bind 接受 ContextAdapter 本身", L.bind(bl, x=1).extra["x"] == 1)
    _restore()


# ---------------------------------------------------------------- 6 fan-out
def t6_dispatch_discipline():
    print("\n[6] 分发纪律（一个 sink 坏不牵连同批）+ SinkHandler")
    class Boom:
        def emit(self, record):
            raise RuntimeError("sink 坏了")

    mem = L.MemorySink()
    old = logging.raiseExceptions
    logging.raiseExceptions = False                     # 别把 traceback 打到测试输出
    try:
        n = L.dispatch([Boom(), mem], _rec("ok"))
    finally:
        logging.raiseExceptions = old
    check("dispatch 返回成功数", n == 1, f"n={n}")
    check("坏 sink 不牵连同批其他 sink", [r.getMessage() for r in mem.records] == ["ok"])

    P = "t6probe"
    mem2, extra = L.MemorySink(), L.MemorySink()
    h = L.SinkHandler([mem2])
    check("SinkHandler.sinks 可读", h.sinks == (mem2,))
    lg = logging.getLogger(P)
    lg.addHandler(h)
    lg.setLevel(logging.DEBUG)
    lg.propagate = False
    lg.info("via-handler")
    check("SinkHandler 桥接 stdlib record", [r.getMessage() for r in mem2.records] == ["via-handler"])
    h.add_sink(extra)
    lg.info("two")
    check("add_sink 生效（fan-out）", len(extra.records) == 1)
    check("remove_sink 返回移除数", h.remove_sink(extra) == 1)
    lg.removeHandler(h)
    h.close()


# ---------------------------------------------------------------- 7 引擎收敛
def t7_engine_uses_facade():
    print("\n[7] 引擎侧收敛：logger 名只有一个来源")
    hits = []
    for root, dirs, files in os.walk(os.path.join(ROOT, "saintess_engine")):
        if "__pycache__" in root or os.path.basename(root) == "log":
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(root, fn)
            for i, line in enumerate(open(path, encoding="utf-8"), 1):
                if re.search(r'getLogger\(\s*["\']', line):
                    hits.append(f"{os.path.relpath(path, ROOT).replace(os.sep, '/')}:{i}")
    check("引擎业务模块零硬编码 logger 名（全走门面）", not hits, str(hits))

    from saintess_engine.command.base import CommandBase       # noqa: E402

    class _Plain(CommandBase):
        pass

    class _Host(CommandBase):
        logger_name = "astrbot"

    check("CommandBase 默认 logger 名收敛到门面",
          _Plain.__new__(_Plain)._logger().name == "saintess_engine.command")
    check("宿主显式 logger_name 直通（不套 prefix）",
          _Host.__new__(_Host)._logger().name == "astrbot")

    from saintess_engine.clock.timer import _LOG as CLK        # noqa: E402
    check("clock 模块 logger 名 = saintess_engine.clock", CLK.name == "saintess_engine.clock")


# ---------------------------------------------------------------- 8 接管引擎日志
def t8_takes_over_engine_logs():
    print("\n[8] 门面能接管引擎自己的日志（EventBus 未声明事件告警）")
    from saintess_engine.events import EventBus                # noqa: E402
    mem = L.MemorySink()
    L.configure(prefix="saintess_engine", level="WARNING", sinks=[mem], propagate=False)
    try:
        EventBus(("known",)).fire("nope", {})                  # 未声明 → 走门面 logger
        check("引擎 fallback 告警进了门面 sink",
              any("nope" in r.getMessage() for r in mem.records),
              str([r.getMessage() for r in mem.records]))
    finally:
        _restore()
    snap = list(logging.getLogger("saintess_engine").handlers)
    EventBus(("known",)).fire("nope2", {})                     # 摘掉出口后：回到宿主 logging
    check("摘掉出口后不再进 sink（可拔插的另一半）",
          list(logging.getLogger("saintess_engine").handlers) == snap == [])


def main():
    print("== 日志门面门禁：可拔插契约 + sink + 上下文 + 引擎侧收敛 ==")
    t1_unconfigured_is_thin()
    t2_zero_sinks_is_noop()
    t3_configure_effective_and_idempotent()
    t4_sinks()
    t5_bind_context()
    t6_dispatch_discipline()
    t7_engine_uses_facade()
    t8_takes_over_engine_logs()
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
