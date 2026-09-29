#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""常驻门禁：宿主装配面四处「真故障 -> 合法回落」不许零痕迹（晚到批 · 第三十轮）。

跑法：python tests/test_host_runtime_fault_leaves_trace.py

背景
----
saintess_engine/host/runtime.py 有四处 `except Exception` 把**真故障**压成
**合法结果**、且不留任何痕迹：

| 处 | 合法回落 | 真故障被压成 | 运维侧原来看到什么 |
|---|---|---|---|
| _load_texts | 无文案表 -> None（上一行已 return，合法） | 读到数据但装表炸 | texts=None + 全兜底文案，零报错 |
| tlog_write | 无 on_tlog -> return（上面 fn is None） | 钩子接了却炸 | 这条流水永久丢失 |
| _guard_battle | 守卫说不许进 -> 拦下 | 守卫本身炸了 | 与「真不在战斗中」无法区分 |
| declared_hit | 没命中 -> None | 匹配层炸了 | 整条命令通道静默瘫掉 |

判据
----
(1) 合法路径**返回值逐字节不变**（无钩子/无文案表 -> 仍 None / return）
(2) 真故障**必须留痕**：走引擎既有日志门面 log.get_logger("host.runtime")
    的 .error(...)，且带 exc_info=True
(3) 不静默：宽异常 handler 内**不允许裸 pass**，且每处 handler 都有日志调用
(4) _load_texts 真故障**向上抛**（回落 None 正是「包没文案表」的合法值，
    回落会让「表坏了」伪装成「包没写文案」）；其余三处**保留安全回落 + 留痕**
(5) 静态自证：四处 handler 全部 as exc 绑定 + 都调了 _log.error
(6) 两向反证：把任一处改回 pass / return None -> 本门禁转红（rc=1）
"""
import ast
import io
import logging
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from saintess_engine.host.runtime import Host

_RT = os.path.join(_ROOT, "saintess_engine", "host", "runtime.py")

PASS, FAILS = 0, []


def check(cond, label):
    global PASS
    if cond:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAILS.append(label)
        print("  FAIL %s" % label)


class _LogCap(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self, level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


def _capture(fn):
    import saintess_engine.host.runtime as rt
    cap = _LogCap()
    log = rt._log
    old_level, old_prop = log.level, log.propagate
    log.addHandler(cap)
    log.setLevel(logging.DEBUG)
    log.propagate = False
    exc = None
    out = None
    try:
        out = fn()
    except BaseException as e:
        exc = e
    finally:
        log.removeHandler(cap)
        log.setLevel(old_level)
        log.propagate = old_prop
    return out, exc, list(cap.records)


def _bare_host():
    h = Host.__new__(Host)
    h.stack = None
    h.texts = None
    h._messages = 0
    h._blobs = {}
    h._tlog_sink = None
    h.adapter = None
    h.commands = None
    h.texts_domain = "texts"
    h.register_hint = ""
    h.battle_hint = ""
    h.battle_check = None
    return h


def test_load_texts_no_table_is_legal():
    h = _bare_host()
    out, exc, recs = _capture(h._load_texts)
    check(out is None and exc is None and not recs,
          "无文案表 -> None 且零留痕（out=%r exc=%r recs=%d）" % (out, exc, len(recs)))


def test_load_texts_broken_table_raises():
    h = _bare_host()

    class _FakeStack(object):
        id = "demo"

        def domain(self, name, required=False, default=None):
            # 真会炸的坏形状：params 声明成 int（from_dict 里 tuple(p) 直接 TypeError）
            return {"a.key": {"zh": "甲", "params": 7}}

    h.stack = _FakeStack()
    out, exc, recs = _capture(h._load_texts)
    check(exc is not None, "坏文案表向上抛（out=%r）" % (out,))
    check(len(recs) == 1 and recs[0].levelno == logging.ERROR,
          "坏文案表留 error 痕（%d 条）" % len(recs))
    check(bool(recs) and recs[0].exc_info is not None, "留痕带 exc_info（可追栈）")
    check(bool(recs) and h.texts_domain in recs[0].getMessage(),
          "留痕点名域 %r" % h.texts_domain)


def test_tlog_no_hook_is_legal():
    h = _bare_host()
    out, exc, recs = _capture(lambda: h.tlog_write("x", a=1))
    check(out is None and exc is None and not recs,
          "无 on_tlog -> 正常返回零留痕（recs=%d）" % len(recs))


def test_tlog_broken_hook_leaves_trace():
    h = _bare_host()
    seen = {}

    def _boom(payload):
        seen["got"] = payload
        raise RuntimeError("sink 挂了")

    h.adapter = type("A", (), {"on_tlog": staticmethod(_boom)})()
    out, exc, recs = _capture(lambda: h.tlog_write("battle.round", n=3))
    check(exc is None, "钩子炸了不抛给调用方（%r）" % (exc,))
    check(seen.get("got", {}).get("kind") == "battle.round",
          "载荷照旧交给钩子（%r）" % (seen.get("got"),))
    check(len(recs) == 1 and recs[0].levelno == logging.ERROR,
          "钩子炸了留 error 痕（%d 条）" % len(recs))
    check(bool(recs) and recs[0].exc_info is not None, "留痕带 exc_info")
    check(bool(recs) and "battle.round" in recs[0].getMessage(),
          "留痕点名 kind（找得到丢的是哪条）")


def test_guard_battle_no_check_is_legal():
    h = _bare_host()
    env = type("E", (), {"uid": "u1", "group_id": "g1"})()
    out, exc, recs = _capture(lambda: h._guard_battle(env))
    check(out is None and exc is None and not recs,
          "无 battle_check -> 不拦且零留痕（recs=%d）" % len(recs))


def test_guard_battle_false_is_legal():
    h = _bare_host()
    h.battle_check = lambda uid, gid: False
    h.battle_hint = "不在战斗中。"
    env = type("E", (), {"uid": "u1", "group_id": "g1"})()
    out, exc, recs = _capture(lambda: h._guard_battle(env))
    check(isinstance(out, str) and out and exc is None and not recs,
          "守卫说不 -> 拦下且零留痕（out=%r recs=%d）" % (out, len(recs)))


def test_guard_battle_broken_check_leaves_trace():
    h = _bare_host()

    def _boom(uid, gid):
        raise RuntimeError("查不到战斗态")

    h.battle_check = _boom
    h.battle_hint = "不在战斗中。"
    env = type("E", (), {"uid": "u42", "group_id": "g7"})()
    out, exc, recs = _capture(lambda: h._guard_battle(env))
    check(exc is None, "守卫炸了不抛给调用方（%r）" % (exc,))
    check(isinstance(out, str) and out, "守卫炸了仍按拦下处理（out=%r）" % (out,))
    check(len(recs) == 1 and recs[0].levelno == logging.ERROR,
          "守卫炸了留 error 痕（%d 条）" % len(recs))
    check(bool(recs) and recs[0].exc_info is not None, "留痕带 exc_info")
    check(bool(recs) and "u42" in recs[0].getMessage() and "g7" in recs[0].getMessage(),
          "留痕点名 uid/gid（找得到是谁）")


def test_declared_hit_no_match_is_legal():
    h = _bare_host()
    h.commands = type("R", (), {"first_hit": staticmethod(lambda t, visible_only=False: None)})()
    out, exc, recs = _capture(lambda: h.declared_hit("   "))
    check(out is None and exc is None and not recs, "空文本 -> None 零留痕（recs=%d）" % len(recs))
    out, exc, recs = _capture(lambda: h.declared_hit("没这条指令"))
    check(out is None and exc is None and not recs, "没命中 -> None 零留痕（recs=%d）" % len(recs))


def test_declared_hit_normal_unchanged():
    h = _bare_host()
    got = {"name": "看背包", "priority": 1}
    h.commands = type("R", (), {"first_hit": staticmethod(lambda t, visible_only=False: got)})()
    out, exc, recs = _capture(lambda: h.declared_hit("看背包"))
    check(out is got and exc is None and not recs,
          "命中原样返回（out=%r recs=%d）" % (out, len(recs)))


def test_declared_hit_broken_leaves_trace():
    h = _bare_host()

    def _boom(text, visible_only=False):
        raise RuntimeError("正则炸了")

    h.commands = type("R", (), {"first_hit": staticmethod(_boom)})()
    out, exc, recs = _capture(lambda: h.declared_hit("看背包"))
    check(out is None and exc is None, "匹配层炸了回落未命中不抛（out=%r exc=%r）" % (out, exc))
    check(len(recs) == 1 and recs[0].levelno == logging.ERROR,
          "匹配层炸了留 error 痕（%d 条）" % len(recs))
    check(bool(recs) and recs[0].exc_info is not None, "留痕带 exc_info")


def test_static_all_four_leave_trace():
    tree = ast.parse(io.open(_RT, encoding="utf-8").read())
    fns = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name in (
                "_load_texts", "tlog_write", "_guard_battle", "declared_hit"):
            fns[n.name] = n
    check(len(fns) == 4, "四个目标函数都在（%r）" % (sorted(fns),))
    problems = []
    for name, fn in sorted(fns.items()):
        handlers = [n for n in ast.walk(fn) if isinstance(n, ast.ExceptHandler)]
        if not handlers:
            problems.append((name, "无 handler"))
            continue
        for h in handlers:
            bound = h.name == "exc"        # Py3：except as X 的 h.name 是字符串
            calls_log = any(
                isinstance(s, ast.Call)
                and isinstance(s.func, ast.Attribute)
                and s.func.attr == "error"
                and isinstance(s.func.value, ast.Name)
                and s.func.value.id == "_log"
                for s in ast.walk(h))
            has_pass = any(isinstance(st, ast.Pass) for st in h.body)
            if not bound or not calls_log or has_pass:
                problems.append((name, h.lineno, bound, calls_log, has_pass))
    check(not problems, "AST：四处 handler 均 as exc + _log.error + 无裸 pass（%r）" % (problems,))


def main() -> int:
    for fn in (test_load_texts_no_table_is_legal,
               test_load_texts_broken_table_raises,
               test_tlog_no_hook_is_legal,
               test_tlog_broken_hook_leaves_trace,
               test_guard_battle_no_check_is_legal,
               test_guard_battle_false_is_legal,
               test_guard_battle_broken_check_leaves_trace,
               test_declared_hit_no_match_is_legal,
               test_declared_hit_normal_unchanged,
               test_declared_hit_broken_leaves_trace,
               test_static_all_four_leave_trace):
        fn()
    print("PASS=%d FAIL=%d" % (PASS, len(FAILS)))
    for f in FAILS:
        print("  FAIL:", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
