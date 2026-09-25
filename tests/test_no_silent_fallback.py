#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：战斗包**零静默兜底** —— 每个 `except` 块要么记诊断、要么显式抛（不许悄悄吞）。

为什么要有它（2026-09-25 两轮收口的产物）
------------------------------------------------------------------
E1 那轮把「`except` 后紧跟一行 pass/continue/return」的 58 处接上了 `_diag`；
但同类问题还有 25 处**别的形态**（体里给个默认值 / 跳过一段）没接 —— 它们同样把
「内容侧写错」吞掉：伤害照算、状态没加、一条日志都没有。
2026-09-25 第二轮把这 25 处也接上（行为零变化，只多一条诊断）⇒ 本包**清零**。

判据
------------------------------------------------------------------
扫 `extends/ext_combat/battle/*.py` 的每个 `except` 块，分类：
  W  体里有 `diag(...)` / `_diag(...)` → 合格
  R  体里有 `raise` → 合格（显式抛，属调用方的降级决定）
  X  白名单（**逐个写明理由**）→ 合格
  S  其余（悄悄吞）→ **红**
白名单只有一处：`diagnostics.py` 自身 —— 诊断模块的契约是「永不抛」，
它的 except 若再记诊断会自我递归。

跑法：`python tests/test_no_silent_fallback.py`；退出码 0 = 全绿 · 1 = 有失败。
"""
import ast
import io
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

BATTLE_DIR = os.path.join(ROOT, "extends", "ext_combat", "battle")

#: (文件名, except 行号) → 理由。**新增条目必须写清为什么它不是「静默兜底」。**
ALLOW = {
    ("diagnostics.py", 33): "「永不抛」契约：取上下文失败就留空串（此模块不能再记诊断，会自递归）",
    ("diagnostics.py", 51): "同上：写不进 battle.diagnostics 时只能吞（否则诊断自己炸）",
    ("diagnostics.py", 57): "同上：日志通道失败时只能吞",
    ("diagnostics.py", 71): "同上：clear 失败无副作用可报",
}

passed = failed = 0
DETAIL = []

from _check import bind_check  # noqa: E402

check = bind_check(globals(), "passed", "failed", "DETAIL")


def has_diag(body):
    for n in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(n, ast.Call):
            nm = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
            if nm in ("diag", "_diag"):
                return True
    return False


def has_raise(body):
    return any(isinstance(s, ast.Raise) for s in ast.walk(ast.Module(body=body, type_ignores=[])))


def classify(path):
    tree = ast.parse(io.open(path, encoding="utf-8").read(), filename=path)
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.ExceptHandler):
            continue
        body = n.body
        if has_diag(body):
            cat = "W"
        elif has_raise(body):
            cat = "R"
        else:
            cat = "S"
        out.append((n.lineno, cat))
    return out


print("【1. 扫面：%s】" % os.path.relpath(BATTLE_DIR, ROOT))
files = sorted(f for f in os.listdir(BATTLE_DIR) if f.endswith(".py"))
check("扫到源文件（≥15）", len(files) >= 15, "n=%d" % len(files))

counts = {"W": 0, "R": 0, "S": 0, "X": 0}
bad = []
for fn in files:
    for lineno, cat in classify(os.path.join(BATTLE_DIR, fn)):
        if cat == "S" and (fn, lineno) in ALLOW:
            counts["X"] += 1
            continue
        counts[cat] += 1
        if cat == "S":
            bad.append("%s:%d" % (fn, lineno))
print("  · 已接诊断 W=%d · 显式抛 R=%d · 白名单 X=%d · ★静默兜底 S=%d"
      % (counts["W"], counts["R"], counts["X"], counts["S"]))
check("★ 没有「静默兜底」（S = 0）", not bad, "命中：" + ", ".join(bad[:10]))
check("已接诊断的处数 ≥ 80（E1 的 58 + 第二轮 22/25，留 3 处余量给合并写在一起的）",
      counts["W"] >= 80, "W=%d" % counts["W"])

print("\n【2. 反证：白名单不许被当挡箭牌用】")
check("白名单条目都真实存在且都是 S 类（防「写了名字但代码已经改了」的僵尸条目）",
      all(any(ln == lineno and cat == "S"
              for ln, cat in classify(os.path.join(BATTLE_DIR, fn)))
          for fn, lineno in ALLOW),
      str(sorted(ALLOW)))

print("\n【3. 反证：造一个静默兜底 ⇒ 扫描器必须报红（有牙）】")
_tmp_dir = os.path.join(ROOT, "tests", "_fallback_negative_tmp")
os.makedirs(_tmp_dir, exist_ok=True)
_tmp = os.path.join(_tmp_dir, "zz_tmp_silent.py")
io.open(_tmp, "w", encoding="utf-8").write(
    "def f(x):\n"
    "    try:\n"
    "        return 1 / x\n"
    "    except Exception:\n"          # ← 典型静默兜底
    "        return 0\n")
try:
    hit = [c for _, c in classify(_tmp)]
finally:
    os.remove(_tmp)
    os.rmdir(_tmp_dir)
check("反证·静默兜底被记为 S", hit == ["S"], str(hit))

print("\n结果：通过 %d / 共 %d" % (passed, passed + failed))
if failed:
    print("失败项：")
    for x in DETAIL:
        print("  · %s" % x)
    sys.exit(1)
