#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""常驻门禁：文本出口写失败不许零痕迹（晚到批 · 第三十二轮）。

跑法：python tests/test_log_stream_sink_flush_reported.py

背景
----
`log/sinks.py` 是**同一个模块里两套口径**：

  · `dispatch` / `_flush_sinks` / `_close_sinks` 三处都走本模块自己的 `sink_error()`
    （计数 + stderr + 到 SINK_ERROR_ESCALATE 升级硬告警）；
  · `StreamSink.emit` / `StreamSink.flush` 两处却写 `except Exception: pass`
    ⇒ flush 失败**永远记不到**，「丢了多少」既不可查也不出声。

而 `_sinkbase.py` 的模块纪律写死「出口写失败**默认出声**」（审计 L2730）⇒
这两处与自己的纪律文档矛盾，且 `tests/test_no_silent_fallback.py` 的扫面是
`extends/ext_combat`、`saintess_engine/log` **零覆盖**。

实测（改前）：StreamSink.flush 抛错 → sink_error 计数 0→0；同模块 dispatch 抛错 → 0→1。

判据
----
(1) flush 失败**必留痕**：`StreamSink.emit` / `StreamSink.flush` 抛错时
    `sink_error_stats()["errors"]` 各 +1，且 kinds 记下可区分的 what
(2) **行为零变化**：仍不抛（不把日志故障带崩主流程）；合法路径计数不动、stderr 零字
(3) **write 失败不归它管**：`stream.write` 抛错由 `dispatch` 捕获并用**它自己的**
    `sink_error` 记账（纪律 1：日志不该把主流程带崩）；StreamSink 这两处只管 flush。
    ⇒ write 故障**恰好记一笔**（不许重复计数、不许静默）
(4) 静态自证：两处 handler 全部 `as exc` 绑定 + 调 `sink_error`，无裸 `pass`
(5) 两向反证：改回 `pass` -> 红（rc=1）；只改一处 -> 也红
"""
import ast
import contextlib
import io
import logging
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "tests"))

from _check import bind_check
check = bind_check(globals(), "PASS", "FAIL", "FAILURES")


def _c(name):
    return int(globals().get(name, 0))

from saintess_engine._sinkbase import sink_error_stats
from saintess_engine.log import sinks as S

SRC = os.path.join(_ROOT, "saintess_engine", "log", "sinks.py")


class _WriteBoom:
    """write 抛错（flush 正常）。"""
    def write(self, s):
        raise OSError("boom-write")
    def flush(self):
        return None


class _FlushBoom:
    """write 正常 / flush 抛错。"""
    def write(self, s):
        return len(s)
    def flush(self):
        raise OSError("boom-flush")


def _rec():
    return logging.LogRecord("gate", logging.INFO, __file__, 1, "hello", None, None)


def _errors():
    return sink_error_stats()["errors"]


def _kinds():
    return sink_error_stats()["kinds"]


# ---------------------------------------------------------------- 1 · flush 失败必留痕
before = _errors()
S.StreamSink(stream=_FlushBoom()).flush()
after = _errors()
check("StreamSink.flush 抛错 -> sink_error 计数 +1", after == before + 1,
      "errors %d -> %d" % (before, after))
check("StreamSink.flush 的 kinds 记下可区分的 what",
      any("flush" in k for k in _kinds()), "kinds=%s" % _kinds())

before = _errors()
S.StreamSink(stream=_FlushBoom()).emit(_rec())
after = _errors()
check("StreamSink.emit 内 flush 抛错 -> sink_error 计数 +1", after == before + 1,
      "errors %d -> %d" % (before, after))

# ---------------------------------------------------------------- 2 · 行为零变化 / 合法路径静默
before = _errors()
err = io.StringIO()
buf = io.StringIO()
try:
    with contextlib.redirect_stderr(err):
        sk = S.StreamSink(stream=buf)
        sk.emit(_rec())
        sk.flush()
    raised = None
except Exception as exc:                                          # pragma: no cover
    raised = exc
check("合法路径不抛", raised is None, "raised=%r" % (raised,))
check("合法路径 sink_error 计数不动", _errors() == before,
      "errors %d -> %d" % (before, _errors()))
check("合法路径 stderr 零字", err.getvalue() == "", "stderr=%r" % err.getvalue()[:120])
check("合法路径行真的写出去了", "hello" in buf.getvalue(), "buf=%r" % buf.getvalue()[:80])

# ---------------------------------------------------------------- 3 · write 失败不归它管
# ★ 口径更正（写这条断言时我先弄反了，被门禁当场逮住）：`dispatch` **按设计捕获**
#   sink 抛的异常（纪律 1「一个 sink 抛错不牵连主流程」）⇒ write 失败**不会**向上抛，
#   而是由 dispatch 自己的 sink_error 记账、返回成功数 0。
#   StreamSink 这两处的职责边界 = 「write 抛错归 dispatch 管」，
#   「flush 抛错归本模块 sink_error 管」—— 两段各自出声，不许一段把另一段吞掉。
before = _errors()
ok = S.dispatch([S.StreamSink(stream=_WriteBoom())], _rec())
check("write 抛错由 dispatch 捕获、不带崩主流程（纪律 1）", ok == 0, "ok=%r" % (ok,))
check("write 抛错由 dispatch 的 sink_error 记账", _errors() == before + 1,
      "errors %d -> %d" % (before, _errors()))

# write 抛错时 emit 自己**不该**再记一次（否则一次故障记两笔、计数虚高）
check("write 抛错不被 StreamSink 重复计数", _errors() == before + 1,
      "errors %d -> %d" % (before, _errors()))

# ---------------------------------------------------------------- 4 · 静态自证
with io.open(SRC, encoding="utf-8") as f:
    tree = ast.parse(f.read())
cls = next(n for n in tree.body
           if isinstance(n, ast.ClassDef) and n.name == "StreamSink")
handled = []
for fn in cls.body:
    if not isinstance(fn, ast.FunctionDef) or fn.name not in ("emit", "flush"):
        continue
    for node in ast.walk(fn):
        if not isinstance(node, ast.ExceptHandler):
            continue
        binds = node.name
        calls_sink_error = any(
            isinstance(c, ast.Call) and getattr(c.func, "id", "") == "sink_error"
            for c in ast.walk(node))
        bare_pass = len(node.body) == 1 and isinstance(node.body[0], ast.Pass)
        handled.append((fn.name, binds, calls_sink_error, bare_pass))

check("StreamSink 里恰有两处宽异常 handler", len(handled) == 2, "found=%d" % len(handled))
check("两处都 as exc 绑定（不吞异常身份）",
      all(b == "exc" for _, b, _, _ in handled), "binds=%s" % [b for _, b, _, _ in handled])
check("两处都调 sink_error（走本模块统一口径）",
      all(c for _, _, c, _ in handled), "calls=%s" % [c for _, _, c, _ in handled])
check("两处都无裸 pass（形状钉死，防改回静默）",
      not any(p for _, _, _, p in handled), "pass=%s" % [p for _, _, _, p in handled])

# ---------------------------------------------------------------- 汇总
print("  --- 共 %d 条检查：通过 %d · 失败 %d"
      % (_c("PASS") + _c("FAIL"), _c("PASS"), _c("FAIL")))
if _c("FAIL"):
    for f_ in FAILURES:
        print("  ❌ " + str(f_))
    sys.exit(1)
print("  ✅ 全部通过")
