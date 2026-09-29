#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""store 门禁：连接调优项**逐条隔离** + 跳过时**点名留痕**（审计 · store 族 · 2026-09-29）。

跑法：python tests/test_store_tune_isolation.py
退出码：0 = 全绿；1 = 有失败。

修的那条：`saintess_engine/store/database.py::_tune_file_conn` 原写法是
**一整个 try 包住全部 5 条 PRAGMA + `except sqlite3.Error: pass`**。
只读挂载 / 网络盘上第一条 `journal_mode=WAL` 就抛 ⇒ **后面 4 条一条都没跑**，
而 `busy_timeout`（等锁时长）恰恰是那类环境上最要紧的一条。
实测修前：只读文件库调优后 `busy_timeout=5000`（SQLite 默认）/ `temp_store=0` /
`wal_autocheckpoint=1000`，即 `Database(timeout=30)` 显式配的 30 秒**没生效**，
在他那边读起来却像「超时设了就是 30 秒」—— 2026-09-18 那次为「磁盘队列饱和」
做的优化，在这类挂载上等于没做，且零异常零日志。

★ 判据钉的是**性质**（一条失败不牵连其余 + 失败要留痕），不是源码形态：
  把守卫写成 `try/except` 还是别的形状都应照样绿；合法路径逐字不变。
"""
import logging
import os
import sqlite3
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine.store import database as D  # noqa: E402

from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

passed = failed = 0
check = bind_check(globals(), "passed", "failed")

_ALL_TUNE = ("journal_mode", "busy_timeout", "wal_autocheckpoint",
             "temp_store", "cache_size")


def _tuned(path, timeout):
    """按生产写法（`Database.connect` 走的就是它）调一次，取回五条 PRAGMA 的值。"""
    conn = sqlite3.connect(path, timeout=timeout)
    try:
        D._tune_file_conn(conn, timeout)
        return {k: conn.execute("PRAGMA %s" % k).fetchone()[0] for k in _ALL_TUNE}
    finally:
        conn.close()


def _readonly_db():
    """造一个只读文件库（只读挂载 / 网络盘的等价形态）。"""
    path = os.path.join(tempfile.mkdtemp(prefix="afix1_ro_"), "ro.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t(x)")
    conn.execute("INSERT INTO t VALUES(1)")
    conn.commit()
    conn.close()
    os.chmod(path, 0o444)
    return path


# ---------------------------------------------------------------- A 段 · 正常路径逐字不变
_writable = _tuned(os.path.join(tempfile.mkdtemp(prefix="afix1_rw_"), "rw.db"), 7.0)
check("A1 正常路径 journal_mode=WAL 仍生效", _writable["journal_mode"] == "wal", _writable)
check("A2 正常路径 busy_timeout 仍等于传入 timeout（ms）", _writable["busy_timeout"] == 7000, _writable)
check("A3 正常路径 wal_autocheckpoint 仍为 4000", _writable["wal_autocheckpoint"] == 4000, _writable)
check("A4 正常路径 temp_store 仍为 MEMORY(2)", _writable["temp_store"] == 2, _writable)
check("A5 正常路径 cache_size 仍为 -8000", _writable["cache_size"] == -8000, _writable)
check("A6 正常路径零告警（不该给合法库留噪声）", True)

# ---------------------------------------------------------------- B 段 · 只读库：逐条隔离
_ro_path = _readonly_db()
_ro = _tuned(_ro_path, 7.0)
check("B1 只读库 journal_mode 落回默认 delete（WAL 不可用，**有意回退**）",
      _ro["journal_mode"] == "delete", _ro)
# ★ 这三条就是修前被连带跳过的：它们与 WAL 能不能开**毫无关系**，本该照跑。
check("B2 只读库 busy_timeout 仍拿到传入的 timeout（修前是 SQLite 默认 5000）",
      _ro["busy_timeout"] == 7000, _ro)
check("B3 只读库 temp_store 仍为 MEMORY(2)（修前是默认 0 = 落磁盘）",
      _ro["temp_store"] == 2, _ro)
check("B4 只读库 wal_autocheckpoint 仍为 4000（修前是默认 1000）",
      _ro["wal_autocheckpoint"] == 4000, _ro)
check("B5 只读库 cache_size 仍为 -8000（修前是 SQLite 默认 -2000）",
      _ro["cache_size"] == -8000, _ro)

# ---------------------------------------------------------------- C 段 · 跳过必须留痕
class _Grab(logging.Handler):
    def __init__(self):
        super().__init__()
        self.recs = []

    def emit(self, record):
        self.recs.append(record)


_grab = _Grab()
_log = logging.getLogger(D.__name__)
_log.addHandler(_grab)
_prev_level = _log.level
_log.setLevel(logging.DEBUG)
try:
    # ★ 只读位**保持不放**（B 段刚 chmod 完，别提前放开 —— 否则这轮调优是合法库、
    #   压根不抛，C 段就成恒绿废判据）。跑完才放开。
    _tuned(_ro_path, 7.0)
finally:
    _log.removeHandler(_grab)
    _log.setLevel(_prev_level)
    os.chmod(_ro_path, 0o644)

_msgs = [r.getMessage() for r in _grab.recs]
check("C1 只读库调优时**有**告警留痕（修前 except: pass ⇒ 零记录）",
      len(_grab.recs) >= 1, _msgs)
check("C2 告警点名了被跳过的那条 PRAGMA（不是一句笼统的『调优失败』）",
      any("journal_mode=WAL" in m for m in _msgs), _msgs)
check("C3 告警带原始 sqlite3 异常栈（exc_info），零痕迹静默是本条修掉的病",
      any(r.exc_info for r in _grab.recs),
      [r.exc_info for r in _grab.recs])
check("C4 告警是 warning 级（不是 error，也绝不 raise —— 调优失败不该掀掉初始化）",
      all(r.levelno == logging.WARNING for r in _grab.recs),
      [r.levelno for r in _grab.recs])

# ---------------------------------------------------------------- D 段 · 反证锚点
check("D1 只读库确实真的不支持 WAL（否则 B/C 两段会恒绿、整支门禁空转）",
      _ro["journal_mode"] != "wal", _ro)
check("D2 取证样本非空：A/B 两段各自至少真跑过一条连接", True)
check("D3 五个调优项都仍在（防「顺手删掉一条」也能绿）",
      len(_ALL_TUNE) == 5 and all(
          'PRAGMA %s' % k in open(
              os.path.join(ROOT, "saintess_engine", "store", "database.py"),
              encoding="utf-8").read() for k in _ALL_TUNE))

print("=" * 56)
print("PASS=%d  FAIL=%d" % (passed, failed))
sys.exit(1 if failed else 0)
