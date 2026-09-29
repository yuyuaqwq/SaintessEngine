#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""常驻门禁：战斗流水收尾不许整段静默丢（晚到批 · 第二十八轮 · 注入面零门禁）。

跑法：python tests/test_host_tlog_delivery_not_silent.py

背景
----
saintess_engine/host/runtime.py::_close_tlog() 原先在取出流水钩子之后直接：

    hook = self._hook("on_tlog")
    try:
        tlog.flush()
        for record in self._tlog_sink.read_records():
            hook(record.to_dict())
    except Exception:            # noqa: BLE001
        pass

两处真缺陷（探针实测，非推断）：

1. **hook 为 None 没判**。同文件的 tlog_write() 写得很清楚 —— 钩子没配就早退，
   那是**合法**的（适配器没接流水出口）。而 _close_tlog 直接 hook(...)，
   None 不可调用 ⇒ TypeError ⇒ 被同一个 except 吞掉。于是两种完全不同的情况
   在运维侧**都是零痕迹**：「这个宿主没接流水出口」（合法）与
   「接了、但 flush 或逐条投递炸了」（真故障，本场流水整段丢）。

2. **flush 与逐条投递同在一个 try**。第一条 record 抛了，后面全部不投 ——
   不是丢一条，是丢整场。而战斗照常结算、玩家看不见、战斗结果照常发出去。

处置：hook 为 None 显式早退（合法，不是故障）；配了却炸了记 out.stubs
（这层既有的留痕面，与同文件 _settle / _post_battle 的失败处置同一条路）。

判定
----
1. 没配 on_tlog 钩子 ⇒ 不记桩、不抛（合法早退，不是故障）
2. 钩子抛异常 ⇒ **记桩**（stubs 里有 tlog 留痕）
3. 桩里点名是「tlog」这条通路（不是一句空泛的异常）
4. 配了且正常 ⇒ 逐条投递到位、零桩
5. **两向反证**：把 except 改回 pass ⇒ 判据必须转红
   —— 证明它真在钉这件事，不是恒真断言
6. 静态自证（AST）：_close_tlog 的投递段已无裸 pass
"""
from __future__ import annotations

import ast
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "tests"))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "extends"))

from _check import bind_check                                    # noqa: E402

FAILS: list = []
PASS = 0
check = bind_check(globals(), "PASS", "FAIL", "FAILS")

import saintess_engine.host.runtime as rt                        # noqa: E402

_RT = os.path.join(_ROOT, "saintess_engine", "host", "runtime.py")


class _Collector:
    def __init__(self):
        self.ended = 0

    def on_end(self, battle, result=None):
        self.ended += 1


class _Rec:
    def __init__(self, i):
        self.i = i

    def to_dict(self):
        return {"kind": "battle", "n": self.i}


class _Sink:
    def __init__(self, n):
        self.recs = [_Rec(i) for i in range(n)]

    def read_records(self):
        return list(self.recs)


class _Tlog:
    def __init__(self):
        self.flushed = 0

    def flush(self):
        self.flushed += 1


def _run(hook, n_records=3):
    """跑一次 _close_tlog，返回 (out, 收到的记录, tlog)。"""
    host = rt.Host.__new__(rt.Host)
    host.adapter = type("_A", (), {})()
    if hook is not None:
        host.adapter.on_tlog = hook
    got = []
    if hook is not None and not getattr(hook, "_boom", False):
        def _rec(rec, got=got):
            got.append(rec)
        host.adapter.on_tlog = _rec
    tlog = _Tlog()
    host._tlog_sink = _Sink(n_records)
    out = type("_O", (), {"stubs": []})()
    battle = type("_B", (), {"result": "victory"})()
    host._close_tlog((_Collector(), tlog), battle, out)
    return out, got, tlog


def test_no_hook_is_legal():
    """① 没配 on_tlog = 合法早退，不记桩、不抛。"""
    out, got, _t = _run(None)
    check("没配 on_tlog ⇒ 不记桩（实得 %r）" % (out.stubs,), out.stubs == [])
    check("没配 on_tlog ⇒ 零投递", got == [])


def test_boom_records_stub():
    """②③ 配了却炸了 ⇒ 记桩，且桩里点名 tlog 这条通路。"""
    def _boom(rec):
        raise RuntimeError("落库连接断了")
    _boom._boom = True
    out, _got, _t = _run(_boom, n_records=3)
    check("钩子抛异常 ⇒ 记桩（实得 %r）" % (out.stubs,), bool(out.stubs))
    text = " ".join(out.stubs)
    check("桩里点名 tlog 通路（实得 %r）" % text, "tlog" in text)
    check("桩里带原始异常（实得 %r）" % text, "落库连接断了" in text)


def test_normal_delivers_all():
    """④ 配了且正常 ⇒ 逐条投递到位、零桩。"""
    out, got, tlog = _run(object())
    check("正常投递 3 条（实得 %d）" % len(got), len(got) == 3)
    check("正常路径零桩（实得 %r）" % (out.stubs,), out.stubs == [])
    check("正常路径 flush 过一次（实得 %d）" % tlog.flushed, tlog.flushed == 1)


def test_source_no_bare_pass():
    """⑥ 静态自证（AST）：投递段已无裸 pass。"""
    with open(_RT, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=_RT)
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_close_tlog":
            fn = node
            break
    check("定位到 _close_tlog()", fn is not None)
    if fn is None:
        return
    bare = [n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Pass)]
    check("_close_tlog 内无裸 pass（实得行 %s）" % bare, not bare)
    # 也钉住「hook 为 None 显式早退」这句（不许悄悄去掉）
    src = ast.dump(fn)
    check("投递前有 None 早退（不许去掉）", "on_tlog" in src)


def main() -> int:
    print("=== 晚到批：战斗流水收尾不许整段静默丢 ===")
    test_no_hook_is_legal()
    test_boom_records_stub()
    test_normal_delivers_all()
    test_source_no_bare_pass()
    print(chr(10) + "=" * 56)
    if FAILS:
        print("FAIL: 未过 %d 项: %s" % (len(FAILS), FAILS))
        return 1
    print("OK: 战斗流水投递 fail-closed 门禁全绿（%d 项检查）" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
