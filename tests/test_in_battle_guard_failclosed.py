#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""host 门禁：战斗判定守卫 fail-closed（审计 · host 族 · 2026-09-29 批次 1 第三十二轮）。

跑法：python tests/test_in_battle_guard_failclosed.py
退出码：0 = 全绿；1 = 有失败。

修的那条：saintess_engine/host/shell.py::ShellBase._in_any_battle 原写法是
`except Exception: return False` —— 守卫 fail-open。副本反查供体
`_instance_battle_for`（内容侧一长串：world_id 反查大陆实例 → 队长 battle 行
→ party 反查）任何一处出错（存档缺 state 键 / 锁库 / 坏形状），
玩家在副本战斗里都被判成脱战，战斗内指令被放行。

判据钉的是性质（守卫不 fail-open + 故障必留痕 + 合法路径逐字不变），不是源码形态。
"""
import ast
import asyncio
import io
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine.host import shell as SH  # noqa: E402
from saintess_engine.command.guards import require_battle  # noqa: E402

from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

passed = failed = 0
FAILS = []
check = bind_check(globals(), "passed", "failed", "FAILS")


class _Store:
    """只回战斗行的假存储半边。"""

    def __init__(self, row=None):
        self.row = row
        self.calls = 0

    def get_battle(self, group_id, qq_id):
        self.calls += 1
        return self.row


class _Boom:
    def __init__(self, exc):
        self.exc = exc

    def __call__(self, g, q):
        raise self.exc


class _Warn(list):
    """抓 _warn 的调用（壳的留痕面）。"""

    def __call__(self, msg, *a, **kw):
        self.append((msg, a, kw))


def _shell(row=None, inst=...):
    """造一个只够跑 _in_any_battle 的壳（绕开 __init__ 的装配链）。"""
    s = SH.ShellBase.__new__(SH.ShellBase)
    s._store = _Store(row)
    if inst is not ...:
        s._instance_battle_for = inst
    return s


# ============================ A 段 · 黑盒：守卫不 fail-open ============================
def _A():
    # A1 本条修的病：供体炸了 => 必须认作「在战斗」（拦下战斗内指令），不能放行。
    exc = RuntimeError("db locked")
    s = _shell(row=None, inst=_Boom(exc))
    s._warn = _Warn()
    got = s._in_any_battle("g", "q")
    check("A1 副本判定供体抛异常时认作在战斗（守卫 fail-closed，不放行）",
          got is True, "got=%r 期望 True" % (got,))

    # A2 故障必留痕，且必须点名（否则运维侧又是零痕迹）。
    w = s._warn
    check("A2 故障留痕：_warn 被调用", len(w) == 1, "调用 %d 次" % len(w))
    if w:
        msg, a, kw = w[0]
        check("A2b 留痕文本点名 fail-closed 方向", "fail-closed" in msg, "msg=%r" % msg)
        check("A2c 留痕带 exc_info=True（traceback 可追）", kw.get("exc_info") is True,
              "kwargs=%r" % (kw,))
        flat = [str(x) for x in a]
        check("A2d 留痕带上 group/user（可定位到人）",
              "g" in flat and "q" in flat, "args=%r" % (a,))

    # A3 抛异常不外泄（守卫不能把命令炸断 —— 口径同 host/env.py::page）。
    check("A3 守卫不把异常抛给调用方（A1 未抛即通过）", True)

    # A4 异常类型无关：KeyError / TypeError / 其它 同样必须 fail-closed。
    for label, e in (("KeyError", KeyError("state")),
                     ("TypeError", TypeError("bad shape")),
                     ("ZeroDivisionError", ZeroDivisionError("x"))):
        ss = _shell(row=None, inst=_Boom(e))
        ss._warn = _Warn()
        g2 = ss._in_any_battle("g", "q")
        check("A4 %s 也认作在战斗" % label, g2 is True, "got=%r" % (g2,))


# ============== B 段 · 合法路径逐字不变（不许把正常判成战斗） ==============
def _B():
    # B1 普通战斗行存在 => True（不碰反查）。
    boom = _Boom(RuntimeError("不该被调"))
    s = _shell(row={"state": {"type": "field"}}, inst=boom)
    s._warn = _Warn()
    check("B1 普通战斗行存在 => True", s._in_any_battle("g", "q") is True)
    check("B1b 普通战斗行存在时不调反查（短路仍是第一道）",
          len(s._warn) == 0, "留痕 %d 条" % len(s._warn))

    # B2 壳没接副本反查 = 无副本的游戏，真不在战斗 => False。
    s2 = _shell(row=None)
    s2._warn = _Warn()
    g2 = s2._in_any_battle("g", "q")
    check("B2 没接副本反查（无副本游戏）=> 仍 False（合法早退不被改成 True）",
          g2 is False, "got=%r" % (g2,))
    check("B2b 该早退不留痕（合法路径不刷日志）", len(s2._warn) == 0,
          "留痕 %d 条" % len(s2._warn))

    # B3 反查正常返回 None => False（真不在战斗）。
    s3 = _shell(row=None, inst=lambda g, q: None)
    s3._warn = _Warn()
    check("B3 反查返回 None => False", s3._in_any_battle("g", "q") is False)
    check("B3b 该路径不留痕", len(s3._warn) == 0, "留痕 %d 条" % len(s3._warn))

    # B4 反查正常返回真值（玩家在副本）=> True。
    s4 = _shell(row=None, inst=lambda g, q: {"state": {"type": "instance"}})
    s4._warn = _Warn()
    check("B4 反查返回真值 => True", s4._in_any_battle("g", "q") is True)
    check("B4b 该路径不留痕", len(s4._warn) == 0, "留痕 %d 条" % len(s4._warn))

    # B5 假值返回（空 dict / 0 / 空串）仍算「不在战斗」—— 别把 falsy 当真值。
    for label, v in (("空dict", {}), ("0", 0), ("空串", "")):
        s5 = _shell(row=None, inst=lambda g, q, v=v: v)
        s5._warn = _Warn()
        g5 = s5._in_any_battle("g", "q")
        check("B5 反查返回 %s => False（falsy 不当真值）" % label, g5 is False,
              "got=%r" % (g5,))


# ============ C 段 · 真守卫链：这个钩子确实拦得住（不只测它自己） ============
class _Event:
    def __init__(self):
        self.sent = []

    def plain_result(self, t):
        self.sent.append(t)
        return t


class _Owner:
    """照 require_battle 的用法造：只需 _uid / _in_any_battle / battle_none_hint。"""

    logger_name = ""

    def __init__(self, in_battle):
        self._in_battle = in_battle
        self.battle_none_hint = "你附近没有敌人！"

    def _uid(self, event):
        return ("g", "q")

    def _in_any_battle(self, group_id, qq_id):
        return self._in_battle

    def _warn(self, *a, **k):
        pass


@require_battle()
async def _cmd(self, event):
    yield event.plain_result("技能1")


def _C():
    import saintess_engine.command.guards as G

    def run(in_battle):
        ev = _Event()
        out = []
        cmd = G.require_battle()(_cmd)
        loop = asyncio.new_event_loop()
        try:
            async def go():
                async for r in cmd(_Owner(in_battle), ev):
                    out.append(r)
            loop.run_until_complete(go())
        finally:
            loop.close()
        return out

    # C1 真在战斗 => 放行到下游命令。
    r1 = run(True)
    check("C1 在战斗 => 守卫放行到下游", r1 == ["技能1"], "out=%r" % (r1,))
    # C2 fail-closed 后，判成「在战斗」就会把本该拦下的操作真的拦下（不是自嗨）。
    r2 = run(False)
    check("C2 不在战斗 => 守卫拦下并回提示", r2 == ["你附近没有敌人！"], "out=%r" % (r2,))
    check("C2b 拦下时下游命令没被执行（不是既放行又提示）", "技能1" not in r2)


# ====== D 段 · 反证锚点（防判据恒绿 / 防顺手删这条也能过） ======
def _D():
    src = io.open(SH.__file__, encoding="utf-8").read()
    tree = ast.parse(src)
    fn = None
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == "_in_any_battle":
            fn = n
            break
    check("D0 能在 AST 里定位 _in_any_battle", fn is not None)
    if fn is None:
        return
    # D1 故障分支必须真的往 True 走（不是 pass、也不是 return False）。
    vals = [n.value.value for n in ast.walk(fn)
            if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)]
    check("D1 故障分支回落 True（守卫 fail-closed）", True in vals, "常量 return=%r" % (vals,))
    check("D1b 仍有 False 回落（fn is None 那条合法早退不被删）", False in vals,
          "常量 return=%r" % (vals,))
    # D2 hook 真的被 require_battle 用着（防测了个没人调的私有函数）。
    gsrc = io.open(os.path.join(ROOT, "saintess_engine", "command", "guards.py"),
                   encoding="utf-8").read()
    check("D2 require_battle 源码里真的点名 _in_any_battle",
          "_in_any_battle" in gsrc)
    # D3 真消费方在内容侧（不是只有测试在用）。
    # games/orlandia 是 submodule（gitlink）—— 父仓 git grep 不下钻，必须进子仓 grep。
    sub = os.path.join(ROOT, "games", "orlandia")
    check("D3a 内容仓在位（submodule 已检出，否则 D3 恒绿空转）",
          os.path.isdir(os.path.join(sub, "content")))
    if os.path.isdir(os.path.join(sub, "content")):
        hits = subprocess.run(["git", "-C", sub, "grep", "-l", "_in_any_battle", "--",
                               "content"], capture_output=True, text=True,
                              encoding="utf-8")
        found = hits.stdout.strip()
        check("D3 内容侧有真消费方（guards / 塔 / 面板）",
              bool(found), "命中=%r" % (found[:160],))
        check("D3b 消费方不是只有 player_cmds 一处（守卫链不止一个调用点）",
              len([x for x in found.splitlines() if x.strip()]) >= 2,
              "命中 %d 处" % len([x for x in found.splitlines() if x.strip()]))


for _fn in (_A, _B, _C, _D):
    _fn()

print("=" * 60)
print("通过 %d / 失败 %d" % (passed, failed))
for _f in FAILS:
    print("  FAIL:", _f)
raise SystemExit(1 if failed else 0)
