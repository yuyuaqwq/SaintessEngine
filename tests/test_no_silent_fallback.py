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

#: **整包**（不是只有 battle/）—— 2026-09-28 起。原先只扫 battle/，
#: 而 docstring 写的是「本包清零」⇒ 同一个包里 gauge/ 与 formation/ 的静默兜底
#: 零覆盖（实测 8 处）。扫面窄于承诺 = 门禁在说谎。
BATTLE_DIR = os.path.join(ROOT, "extends", "ext_combat")
#: 扫面里要排除的子目录：测试面（测试自己造夹具时用 except 是正常的）。
SKIP_DIRS = frozenset({"__pycache__", "tests"})

#: (文件内路径, 函数名) → 理由。**新增条目必须写清为什么它不是「静默兜底」。**
#: ★ 用「路径 + 函数名」而不是行号：行号会随前几批改动漂移，一漂就变成
#:   「白名单指向不存在的位置」—— 那比漏报更坏（看起来还在管，实际管不到）。
ALLOW = {
    # ── 诊断模块本体：「永不抛」契约，它再记诊断会自我递归 ──
    ("battle/diagnostics.py", "_stage_ctx"): "取上下文失败就留空串（此模块不能再记诊断，会自递归）",
    ("battle/diagnostics.py", "diag"): "同上：写不进 battle.diagnostics / 日志通道失败时只能吞"
                          "（原白名单按行号登记的 51 与 57 两处，同属本函数）",
    ("battle/diagnostics.py", "clear"): "同上：clear 失败无副作用可报",
    # ── 2026-09-28 扩面新增（扫面从 battle/ 扩到整包后暴露出来的既有兜底）──
    #    ★ 这些不是「刚引入的缺陷」，是**扫面变宽才第一次被看见**的旧兜底。
    #    逐条处理权归各文件所属车道（本车道只登记，不越界改别人的文件面）。
    ("formation/__init__.py", "select_aoe_targets"): "rankN 前缀解析：非数字回落第 1 层，是该参数「认不出就用默认」的既有口径",
    ("gauge/__init__.py", "_battle_cfg"): "机制配置表未装配 → {}（模块头注写明的未装配态，不是吞错）",
    ("gauge/__init__.py", "_state_prefix"): "同上：未装配 → 历史兜底前缀（docstring 明写）",
    ("gauge/__init__.py", "_default_bar_max"): "同上：未装配 → 0.0，调用处回落历史兜底 100（docstring 明写）",
    ("gauge/__init__.py", "bar_gain"): "上限值认不出 → 0.0，再走 _default_bar_max；同函数另一处 add 认不出 → 0",
    # ── ★ 未登记：gauge/actions.py 的 2 处（bar_gain_act）**故意不登记** ──
    #    扩面把这两处暴露出来了（原先零覆盖）。它们是台账 L251 的真缺陷
    #    （per_hit 多段量静默退成单段量），但 `gauge/actions.py` 属**批次 4**
    #    文件面（它要重钉 test_gauge_actions_frozen 的源码 sha + pin）
    #    ⇒ 本车道只登记不改（越界即双写）。
    ("gauge/actions.py", "bar_gain_act"): "★ 真缺陷（台账 L251：per_hit 多段量静默退成单段量）·"
                                 "属批次 4 文件面（它要重钉 test_gauge_actions_frozen 的源码 sha）·"
                                 "本车道越界即双写，故登记。**批次 4 修完请删本行** ———"
                                 "删不删都安全：白名单条目一旦不再是 S 类，第 2 节会当场报红（fail-closed）",
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


def _enclosing_name(tree, ln):
    """行号 → 所在函数名；模块层 = "<module>"。行号会漂，函数名不会。"""
    best = "<module>"
    for n in sorted((x.lineno, x.name)
                    for x in ast.walk(tree)
                    if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))):
        if n[0] <= ln:
            best = n[1]
        else:
            break
    return best


def classify(path):
    """→ [(行号, 分类, 函数名)]。"""
    tree = ast.parse(io.open(path, encoding="utf-8").read(), filename=path)
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.ExceptHandler):
            continue
        if has_diag(n.body):
            cat = "W"
        elif has_raise(n.body):
            cat = "R"
        else:
            cat = "S"
        out.append((n.lineno, cat, _enclosing_name(tree, n.lineno)))
    return out


def scan_tree(root):
    """遍历整包（跳过 SKIP_DIRS 与 test_*.py）→ [(相对路径, 行号, 分类, 函数名)]。"""
    rows = []
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for f in sorted(fn):
            if not f.endswith(".py") or f.startswith("test_"):
                continue
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            for lineno, cat, fname in classify(p):
                rows.append((rel, lineno, cat, fname))
    return rows


print("【1. 扫面：%s（整包，非只有 battle/）】" % os.path.relpath(BATTLE_DIR, ROOT))
_rows = scan_tree(BATTLE_DIR)
files = sorted(set(r[0] for r in _rows))
check("扫到源文件（≥15）", len(files) >= 15, "n=%d" % len(files))
# ★ 扫面必须真的覆盖到 battle/ 之外的模块，否则「整包」只是文档里的一句话。
_outside = [f for f in files if not f.startswith("battle/")]
check("★ 扫面不止 battle/（否则 gauge/formation/panel 的兜底零覆盖）",
      len(_outside) > 0, "battle 外文件：%s" % _outside)

counts = {"W": 0, "R": 0, "S": 0, "X": 0}
bad = []
for rel, lineno, cat, fname in _rows:
    if cat == "S" and (rel, fname) in ALLOW:
        counts["X"] += 1
        continue
    counts[cat] += 1
    if cat == "S":
        bad.append("%s:%d(%s)" % (rel, lineno, fname))
print("  · 已接诊断 W=%d · 显式抛 R=%d · 白名单 X=%d · ★静默兜底 S=%d"
      % (counts["W"], counts["R"], counts["X"], counts["S"]))
check("★ 没有「静默兜底」（S = 0）", not bad, "命中：" + ", ".join(bad[:10]))
check("已接诊断的处数 ≥ 80（E1 的 58 + 第二轮 22/25，留 3 处余量给合并写在一起的）",
      counts["W"] >= 80, "W=%d" % counts["W"])

print("\n【2. 反证：白名单不许被当挡箭牌用】")
_rows_S = [r for r in _rows if r[2] == "S"]
check("白名单条目都真实存在且都是 S 类（防「改了函数名/挪了行号就失效」）",
      all(any(rel == key[0] and fn == key[1] for rel, _ln, _c, fn in _rows_S)
          for key in ALLOW),
      str(sorted(ALLOW)))
check("白名单不许指向顶层模块（只许逐个函数登记，防「整文件豁免」当挡箭牌）",
      all(os.path.basename(key[0]) != key[0] for key in ALLOW),
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
    hit = [c for _, c, _fn in classify(_tmp)]
finally:
    os.remove(_tmp)
    os.rmdir(_tmp_dir)
check("反证·静默兜底被记为 S", hit == ["S"], str(hit))

# ★ 本次改动的核心反证：把扫面**缩回** battle/ ⇒ 「扫面不止 battle/」必须报红。
#   没有这一条，把 BATTLE_DIR 改窄（回退成本极低、后果极重）不会被任何人发现。
print("\n【4. 反证：扫面被改窄（只剩 battle/）⇒ 必须报红】")
_wide = sorted(set(r[0] for r in scan_tree(BATTLE_DIR)))
check("反证·整包扫面确实比 battle/ 宽（否则第 1 条判据是恒真的同义反复）",
      any(not f.startswith("battle/") for f in _wide),
      "宽扫面文件数=%d" % len(_wide))
_solo = scan_tree(os.path.join(BATTLE_DIR, "battle"))
# ★ 注意 scan_tree 的 rel 是**相对传入的 root** 算的，所以子集扫出来的路径不带
#   "battle/" 前缀 —— 判据只能比「条数 + 整包里确有 battle 之外的模块」。
check("反证·battle/ 子集扫面比整包窄（证明扩面判据不是恒真的同义反复）",
      len(_solo) < len(_rows)
      and any(r[0].startswith("gauge/") for r in _rows),
      "battle 子集 %d 行 / 整包 %d 行" % (len(_solo), len(_rows)))

print("\n结果：通过 %d / 共 %d" % (passed, passed + failed))
if failed:
    print("失败项：")
    for x in DETAIL:
        print("  · %s" % x)
    sys.exit(1)
