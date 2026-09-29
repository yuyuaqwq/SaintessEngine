#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""常驻门禁：列表视图状态写入失败不许零痕迹（晚到批 · 第二十九轮 · 注入面零门禁）。

跑法：python tests/test_cmd_liststate_not_silent.py

背景
----
saintess_engine/command/base.py::_record_list_state() 原先是：

    try:
        self._record_state(self.list_state_key(qq_id), json.dumps({...}))
    except Exception:
        pass

**零痕迹**。而 `self._record_state` 这一个形状同时编码了两种完全不同的情况：

· 基类空实现（base.py:72 `return None`）= 这个壳**没接**存储半边 ⇒ 合法
  （纯静态 / 测试链路），什么都不做是对的；
· host/shell.py:151 的实现 = `self._store.set_event_state(...)` ⇒ 真宿主，
  **接了却炸了**（列不存在 / 锁库 / 事务回滚）是真故障。

原写法下两者在运维侧完全一样：翻页快捷键用不到、`last_list_<qq>` 没写进去，
玩家下一次翻页**静默退回第 1 页**，零日志零异常 —— 不是降级，是丢功能。

该方法有 20+ 个真实调用点（grep games/orlandia：背包 / 商店 / 锻造 / 市场 /
公会 / 任务 / 技能列表 / 称号 / 百科 …），命中面是玩家的常用路径。

判定
----
1. 没接存储半边（用基类实现）⇒ 早退，**不告警、不抛**（合法）
2. 接了存储半边且写入成功 ⇒ 写进去的值逐字节正确（cmd/page/pages 三项齐全）
3. 接了存储半边但写入抛错 ⇒ **必须留痕**（warning），且提示玩家可感知的后果
4. 留痕必须点名是哪个 key 写失败（不是一句空泛的异常）
5. 合法早退路径**不产生** warning（别把「没接」也吵起来）
6. **两向反证**：把 except 改回 pass ⇒ 判据必须转红 —— 证明它真在钉这件事
7. 静态自证（AST）：_record_list_state 的写入段已无裸 pass
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

from saintess_engine.command.base import CommandBase             # noqa: E402

_BASE = os.path.join(_ROOT, "saintess_engine", "command", "base.py")


class _NoStore(CommandBase):
    """没接存储半边：用基类 _record_state 的空实现。"""


class _OkStore(CommandBase):
    def __init__(self):
        self.writes = {}

    def _record_state(self, key, value):
        self.writes[key] = value


class _BadStore(CommandBase):
    def __init__(self):
        self.warnings = []

    def _record_state(self, key, value):
        raise RuntimeError("no such column: last_list_u1 / database is locked")

    def _warn(self, msg, *args, **kwargs):
        self.warnings.append(msg % args if args else msg)


def test_no_store_is_legal_silent():
    """①⑤ 没接存储半边 ⇒ 早退，且不吵。"""
    c = _NoStore()
    msgs = []
    c._warn = lambda m, *a, **k: msgs.append(m)
    c._record_list_state("u1", "背包 材料", 3, 7)
    check("没接存储半边 ⇒ 不告警（实得 %d 条）" % len(msgs), msgs == [])


def test_writes_value():
    """②② 接了且成功 ⇒ 值逐字节正确。"""
    import json
    c = _OkStore()
    c._record_list_state("u1", "背包 材料", 3, 7)
    key = "last_list_u1"
    check("接了存储半边 ⇒ 写进了 %r" % key, key in c.writes)
    got = json.loads(c.writes.get(key, "{}"))
    check("写入值三项齐全（实得 %r）" % (got,),
          got == {"cmd": "背包 材料", "page": 3, "pages": 7})


def test_failure_leaves_trace():
    """③④ 接了却炸了 ⇒ 留痕，且点名 key。"""
    c = _BadStore()
    c._record_list_state("u1", "背包 材料", 3, 7)
    check("写失败 ⇒ 至少一条 warning（实得 %d 条）" % len(c.warnings), len(c.warnings) >= 1)
    txt = " | ".join(c.warnings)
    check("留痕点名是哪个 key（实得 %r）" % txt[:90], "last_list_u1" in txt)
    check("留痕说明玩家可感知的后果（翻页退回第 1 页）",
          "翻页" in txt)


def test_static_no_bare_pass():
    """⑦ 静态自证：_record_list_state 内无裸 pass。"""
    tree = ast.parse(open(_BASE, encoding="utf-8").read())
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_record_list_state":
            for sub in ast.walk(node):
                if isinstance(sub, ast.ExceptHandler):
                    for st in sub.body:
                        if isinstance(st, ast.Pass):
                            bad.append(sub.lineno)
    check("AST：_record_list_state 内无裸 pass（实得行 %r）" % (bad,), not bad)


def main() -> int:
    for fn in (test_no_store_is_legal_silent, test_writes_value,
               test_failure_leaves_trace, test_static_no_bare_pass):
        fn()
    print("PASS=%d FAIL=%d" % (PASS, len(FAILS)))
    for f in FAILS:
        print("  FAIL:", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
