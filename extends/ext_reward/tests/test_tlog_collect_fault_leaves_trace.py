#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""常驻门禁：战斗流水采集半边五处宽异常不许零痕迹（晚到批 · 第三十二轮）。

跑法：python extends/ext_reward/tests/test_tlog_collect_fault_leaves_trace.py

背景
----
ext_reward/tlog_collect.py 是战斗流水采集唯一实现，五处 except Exception: pass
把「本该发的流水发不出去 / 观察者装不上」全部压成静默：

  1. attach: b._battle_tlog = self   -> 战斗对象查不到采集器，零痕迹
  2. _wrap_landing 装 _dispatch_pending -> 整场打完 0 条 battle.end（最贵）
  3. _wrap_landing 内 _maybe_end       -> 每步静默重试、零痕迹
  4. _chain_observer 既有观察者        -> 别人的观察者坏了，流水侧零痕迹
  5. _wrap_human_act 内 on_act         -> 缺一条 battle.act，断档查不出原因

依赖方向约束：ext_reward/game.json 写明「零包内依赖，只吃引擎」
  => 报告口走引擎 log 门面（saintess_engine.log），不 import ext_combat.*

判据
----
(1) 五类真故障各必留 WARNING 痕（带故障点中文名 + 异常类型）
(2) 行为零变化：行动照打、其余挂载照做、流水条数与改前逐条相同、不抛给主流程
(3) 合法路径零日志（正常一场不该有任何 WARNING）
(4) tlog=None 时仍零行为（可拔插红线）
(5) AST 形状钉死：五处全部 as exc 绑定 + 调 _warn，无裸 pass
(6) 依赖方向钉死：不 import 任何 ext_* 包
"""
import ast
import io
import logging
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
for _p in (_ROOT, os.path.join(_ROOT, "extends"), os.path.join(_ROOT, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _check import bind_check
check = bind_check(globals(), "PASS", "FAIL", "FAILURES")


def _c(name):
    return int(globals().get(name, 0))


from saintess_engine import log as _log
from ext_reward import tlog_collect as T

SRC = os.path.join(_ROOT, "extends", "ext_reward", "tlog_collect.py")
_warnings = []


class _Cap(logging.Handler):
    def emit(self, r):
        if r.levelno >= logging.WARNING:
            _warnings.append(r.getMessage())


_lg = _log.get_logger("ext_reward.tlog_collect")
_lg.addHandler(_Cap())
_lg.setLevel(logging.DEBUG)


class _Sink:
    def __init__(self, boom_kinds=()):
        self.rows = []
        self.boom_kinds = set(boom_kinds)

    def emit(self, kind, actor="", tags=(), fields=None, **kw):
        if kind in self.boom_kinds:
            raise RuntimeError("boom-" + str(kind))
        self.rows.append(kind)

    def flush(self):
        return None


class _Battle:
    def __init__(self, boom_attach=False, boom_dispatch=False):
        self.result = "win"
        self._p_acts = 3
        self.acted = []
        self.boom_attach = boom_attach
        self.boom_dispatch = boom_dispatch

    def human_act(self, action, skill, actor=None, target=None, side=None):
        self.acted.append(action)
        return "act-ok"

    def _dispatch_pending(self, actor, slot, logs):
        return "dispatched"

    def focus(self):
        return {"actor": {"name": "P"}, "uid": "p1"}

    def __setattr__(self, k, v):
        if k == "_battle_tlog" and getattr(self, "boom_attach", False):
            raise RuntimeError("boom-attach")
        if k == "_dispatch_pending" and getattr(self, "boom_dispatch", False):
            raise RuntimeError("boom-dispatch")
        object.__setattr__(self, k, v)


def _play(boom_attach=False, boom_dispatch=False, boom_prev=False, boom_act=False):
    """跑一场，返回 (警告列表, sink, 采集器, 战斗对象, 行动返回值)。"""
    del _warnings[:]
    sink = _Sink(boom_kinds=("battle.act",) if boom_act else ())
    col = T.BattleTLog(tlog=sink)
    b = _Battle(boom_attach=boom_attach, boom_dispatch=boom_dispatch)
    if boom_prev:
        def bad_prev(*a):
            raise RuntimeError("boom-prev")
        b.on_event = bad_prev
    col.attach(b, player={"uid": "p1", "name": "P"}, enemies=[])
    b.on_event(b, "skill_hit", {"actor": {"uid": "p1"}}, [])
    b._dispatch_pending({}, 0, [])
    out = b.human_act("attack", "slash")
    return list(_warnings), sink, col, b, out

# ---------------------------------------------------------------- 1+2+3 · 五类故障各留痕、行为不变
warns, sink, col, b, out = _play()
check("合法路径零 WARNING（正常一场不该出声）", not warns, "warns=%s" % warns)
check("合法路径：行动照打、返回值不变", out == "act-ok" and b.acted == ["attack"],
      "out=%r acted=%s" % (out, b.acted))
check("合法路径：流水条数逐条钉死", sink.rows == ["battle.start", "battle.hit",
      "battle.end", "battle.act"], "rows=%s" % sink.rows)
base_rows = list(sink.rows)

warns, sink, col, b, out = _play(boom_attach=True)
check("① attach 挂载失败必留痕", len(warns) == 1 and "挂载采集器" in warns[0], "warns=%s" % warns)
check("① 留痕带异常类型名", bool(warns) and "RuntimeError" in warns[0], "warns=%s" % warns)
check("① 行为零变化：其余挂载照做、流水条数不变", sink.rows == base_rows,
      "rows=%s vs %s" % (sink.rows, base_rows))
check("① 不抛给主流程", out == "act-ok", "out=%r" % (out,))

warns, sink, col, b, out = _play(boom_dispatch=True)
check("② 包 _dispatch_pending 失败必留痕",
      len(warns) == 1 and "_dispatch_pending" in warns[0], "warns=%s" % warns)
check("② 留痕点名代价不会自动发 battle.end",
      bool(warns) and "battle.end" in warns[0], "warns=%s" % warns)
check("② 行为零变化：流水条数不变", sink.rows == base_rows,
      "rows=%s vs %s" % (sink.rows, base_rows))

warns, sink, col, b, out = _play(boom_prev=True)
check("③ 既有观察者抛错必留痕",
      len(warns) == 1 and "既有 on_event 观察者" in warns[0], "warns=%s" % warns)
check("③ 本包观察者照跑（纪律 3：两边各自隔离）", "battle.hit" in sink.rows, "rows=%s" % sink.rows)
check("③ 行为零变化：流水条数不变", sink.rows == base_rows,
      "rows=%s vs %s" % (sink.rows, base_rows))

warns, sink, col, b, out = _play(boom_act=True)
check("④ 记 battle.act 失败必留痕",
      len(warns) == 1 and "battle.act" in warns[0], "warns=%s" % warns)
check("④ 行动照打、返回值不变（不吞战斗）", out == "act-ok" and b.acted == ["attack"],
      "out=%r acted=%s" % (out, b.acted))
check("④ 只少那一条 act、其余不变",
      sink.rows == ["battle.start", "battle.hit", "battle.end"], "rows=%s" % sink.rows)

# ---------------------------------------------------------------- 4 · tlog=None 零行为（可拔插红线）
_off = T.BattleTLog(tlog=None)
_b2 = _Battle()
_off.attach(_b2, player={"uid": "p1", "name": "P"}, enemies=[])
check("tlog=None 不挂采集器", not hasattr(_b2, "_battle_tlog"), "挂了")
check("tlog=None 时 enabled=False", _off.enabled is False, "enabled=%r" % _off.enabled)

# ---------------------------------------------------------------- 5 · AST 形状钉死
with io.open(SRC, encoding="utf-8") as f:
    tree = ast.parse(f.read())
wide, no_bind, no_warn = [], [], []
for node in ast.walk(tree):
    if not isinstance(node, ast.ExceptHandler):
        continue
    if not (isinstance(node.type, ast.Name) and node.type.id == "Exception"):
        continue
    wide.append(node.lineno)
    if node.name != "exc":
        no_bind.append(node.lineno)
    if not any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_warn"
               for c in ast.walk(node)):
        no_warn.append(node.lineno)

check("恰有 5 处宽 except Exception", len(wide) == 5, "lines=%s" % wide)
check("5 处全部 as exc 绑定", not no_bind, "bad=%s" % no_bind)
check("5 处全部调 _warn（真故障必出声）", not no_warn, "未调=%s" % no_warn)

# ---------------------------------------------------------------- 6 · 依赖方向钉死
with io.open(SRC, encoding="utf-8") as f:
    src_text = f.read()
check("不 import 任何 ext_ 扩展包（game.json 声明零包内依赖）",
      "import ext_" not in src_text and "from ext_" not in src_text, "有 ext_ import")

# ---------------------------------------------------------------- 汇总
print("  --- 共 %d 条检查：通过 %d · 失败 %d"
      % (_c("PASS") + _c("FAIL"), _c("PASS"), _c("FAIL")))
if _c("FAIL"):
    for f_ in FAILURES:
        print("  ❌ " + str(f_))
    sys.exit(1)
print("  ✅ 全部通过")
