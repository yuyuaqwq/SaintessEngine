# -*- coding: utf-8 -*-
"""★ 审计修复车道 批次4 · 台账 L2735 第 3 条：`FileSinkBase` 的**底线行为**门禁。

判据来源（台账 L2735-3 原文，2026-09-28 审计）：
    「本单元的立项理由是「两套出口口径一致」，而**门禁 0 条直接覆盖
      `FileSinkBase`** ⇒ 底线行为（`flush()` 真刷、`close()` 真关、`sink_error`
      真出声）**全部无牙**。」

★ 本轮**变异测试实测复现**（不是照抄结论，命令与输出见提交消息）：
  ① `FileSinkBase.flush()` 体改成 `if False: pass` ⇒ `tests/test_log.py`
     **仍 76/76 全绿** ⇒ 具名断言真的零覆盖。
     （机制：`FileSink.emit` 在 `sinks.py:217` **自己** `fh.flush()`，
       所以生产写入路径根本不走 `FileSinkBase.flush` —— 要钉住它必须
       **直接拿底座句柄**写，不能拿 `emit` 写。这是本门禁第一版的错，已改。）
  ② `FileSinkBase.close()` 体改成 `return` ⇒ 红，但红在**测试清理阶段**
     `PermissionError [WinError 32]`，**不是任何一条具名断言**
     ⇒ 证明力来自崩溃副作用，不是「我们钉住了 close 真关」。

★ 反证形态：**子进程**跑变异版（`--mutant=flush|close`）——
  同进程内改类再跑断言会污染 PASS/FAIL 计数（第一版踩到：变异轮的失败
  记进了正常轮的账），所以变异版必须**独立进程**、独立计数、由父进程判红。
  子进程报的**具体红格**要与预期一致（不是「反正有红」）。

纪律：本文件**只加强** —— 不改任何既有判据、不放宽任何断言、**不改生产代码**。
"""
import contextlib
import io
import logging
import os
import shutil
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)  # 门禁落在仓内 tests/ 下 ⇒ 上一级就是仓根
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "extends"))
sys.path.insert(0, _HERE)

from _check import bind_check  # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []          # bind_check 把计数写回本模块的名字
check = bind_check(globals(), "PASS", "FAIL", "FAILURES")

from saintess_engine import _sinkbase as SB          # noqa: E402
from saintess_engine.log import sinks as LOG         # noqa: E402


def _apply_mutant(which):
    """把 `FileSinkBase` 的某个方法换成空实现 —— 门禁的反证输入。"""
    if which == "flush":
        SB.FileSinkBase.flush = lambda self: None
    elif which == "close":
        SB.FileSinkBase.close = lambda self: None
    else:
        return False
    return True


def _rec(msg):
    return logging.LogRecord("afix4", logging.INFO, __file__, 1, msg, (), None)


def _rm(blk):
    shutil.rmtree(blk, ignore_errors=True)


class _RawBase(SB.FileSinkBase):
    """**底座直用**：只借 `FileSinkBase` 的生命周期，不经 `FileSink.emit`
    —— 因为 `FileSink.emit` 自带 `fh.flush()`（`log/sinks.py:217`），
    走它就测不到 `FileSinkBase.flush` 本身了。"""

    def __init__(self, path):
        self.path = os.fspath(path)
        self.encoding = "utf-8"
        super().__init__()

    def write_raw(self, text):
        self._open().write(text)          # 故意**不** flush


# ────────────────────────────────────────────────── ① flush 真刷
def t_flush_actually_flushes():
    print("\n[1] FileSinkBase.flush() 真把缓冲写进文件（审计 L2735-3）")
    blk = tempfile.mkdtemp(prefix="afix4_flush_")
    p = os.path.join(blk, "a.log")
    try:
        s = _RawBase(p)
        s.write_raw("flush-probe\n")       # 只写不刷
        check("★ flush 前另开句柄还读不到（证明下面的「读得到」来自 flush）",
              not os.path.exists(p) or open(p, encoding="utf-8").read() == "",
              "缓冲已意外落盘 ⇒ 这条断言证明不了 flush")
        s.flush()
        with open(p, encoding="utf-8") as f:
            seen = f.read()
        check("★ flush() 后另开句柄读得到内容（原缺陷：哑掉 flush 仍全绿）",
              "flush-probe" in seen, repr(seen[:60]))
        s.close()
    finally:
        _rm(blk)


# ────────────────────────────────────────────────── ② close 真关
def t_close_releases_handle():
    print("\n[2] FileSinkBase.close() 真释放文件句柄（审计 L2735-3）")
    blk = tempfile.mkdtemp(prefix="afix4_close_")
    p = os.path.join(blk, "b.log")
    try:
        s = _RawBase(p)
        s.write_raw("close-probe\n")
        s.flush()
        s.close()
        check("★ close() 之后句柄真处于 closed 态",
              s._fh is not None and s._fh.closed, repr(getattr(s._fh, "closed", None)))
        try:
            os.remove(p)
            ok = True
        except OSError as exc:
            ok = False
            detail = "%s: %s" % (type(exc).__name__, exc)
        check("★ close() 之后文件删得掉（原缺陷：WinError 32，哑掉 close 只在清理期炸）",
              ok, "" if ok else detail)
    finally:
        _rm(blk)


# ────────────────────────────────────────────────── ③ sink_error 真出声且点名
def t_sink_error_names_the_sink():
    print("\n[3] sink_error 出声且点名出口（审计 L2735-2/-3）")
    blk = tempfile.mkdtemp(prefix="afix4_err_")
    try:
        with open(os.path.join(blk, "notadir"), "w", encoding="utf-8") as f:
            f.write("x")                  # 父路径是个文件 ⇒ makedirs 必炸
        fs = LOG.FileSink(os.path.join(blk, "notadir", "sub", "c.log"))
        buf = io.StringIO()
        before = SB.sink_error_stats()["errors"]
        with contextlib.redirect_stderr(buf):
            n = LOG.dispatch([fs], _rec("lifecycle-3"))
        out = buf.getvalue()
        check("★ 写失败时 dispatch 返回 0（记录没落盘就不算成功）", n == 0, "n=%s" % n)
        check("★ 写失败时 stderr 出声（原缺陷：一个字都没有）", "sink" in out, repr(out[:60]))
        check("★ 报错误里带出口路径（不用先猜是哪个文件）", "path=" in out, repr(out[:80]))
        check("★ 失败计数可查（丢了多少是事实）",
              SB.sink_error_stats()["errors"] == before + 1)
    finally:
        _rm(blk)


# ────────────────────────────────────────────────── ④ close 不是终态（审计 L2739 口径）
def t_close_then_write_reopens():
    print("\n[4] close() 之后再写会自动重开同一文件（审计 L2739 口径不漂）")
    blk = tempfile.mkdtemp(prefix="afix4_reopen_")
    p = os.path.join(blk, "d.log")
    try:
        s = _RawBase(p)
        s.write_raw("before-close\n")
        s.flush()
        s.close()
        s.write_raw("after-close\n")     # 走 _open() 的 closed 分支重开
        s.flush()
        with open(p, encoding="utf-8") as f:
            seen = f.read()
        check("★ close 后再写的内容续写进同一文件",
              "after-close" in seen and "before-close" in seen, repr(seen[:80]))
        s.close()
    finally:
        _rm(blk)


# ────────────────────────────────────────────────── ⑤ 反证（子进程隔离）
def t_counterproof():
    print("\n[5] 反向变异自检：哑掉 flush/close 后对应断言必须转红（带牙证明）")
    py = sys.executable
    for which, expect in (("flush", "flush() 后另开句柄读得到内容"),
                          ("close", "close() 之后文件删得掉")):
        r = subprocess.run([py, os.path.abspath(__file__), "--mutant=" + which],
                           capture_output=True, text=True, cwd=ROOT)
        out = r.stdout + r.stderr
        red = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("✗")]
        check("★ 反证：哑掉 %s() 的变异版**判红**" % which, r.returncode != 0,
              "rc=%d（变异后仍全绿 ⇒ 这格无牙）" % r.returncode)
        check("★ 反证：红在**预期那一条**（不是别处碰巧红了）",
              any(expect in ln for ln in red), "实际红格=%s" % (red or "无"))
    check("★ 反证跑完源码已还原（变异版是子进程，父进程源码零改动）",
          SB.FileSinkBase.flush.__name__ == "flush"
          and SB.FileSinkBase.close.__name__ == "close")


def main(argv):
    mutant = next((a.split("=", 1)[1] for a in argv if a.startswith("--mutant=")), None)
    if mutant:
        _apply_mutant(mutant)
    t_flush_actually_flushes()
    t_close_releases_handle()
    t_sink_error_names_the_sink()
    t_close_then_write_reopens()
    if not mutant:
        t_counterproof()
    print("\n===== 结果：通过 %d / %d =====" % (PASS, PASS + FAIL))
    for f in FAILURES:
        print("  ✗ " + str(f))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
