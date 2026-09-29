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
    # ★ 审计 L251-4（2026-09-29）：`gauge/__init__.py` 的四条白名单**已全部删除**。
    #   它们当年被登记的理由是「未装配态回落，不是吞错」——但本轮实测量明那条理由**不成立**：
    #     · `game_config.mech_cfg` / `bar_prefix` 自己就 fail-closed（hook 未注册 → {} / ""）
    #     · `formulas.gauge_default_max` 未装配时自己给 0.0
    #   ⇒ 「未装配」根本走不到调用侧的 try；那个 except 只在**内容侧供体自己崩了**时命中，
    #     而那时静默回落的后果是敌身条整套参数无声换成引擎缺省（阈值/上限/递增率/键前缀）。
    #   现在这四条已真修：前三条删掉 try（异常现形），bar_gain 两处收窄成
    #   (TypeError, ValueError) 并接诊断通道 ⇒ 都不再是 S 类，白名单留着反而会
    #   让「白名单指向已修干净的函数」这种自欺条目继续存在（该门禁的反证条正是查这个）。
    #   ★ 这不是放宽判据：白名单**变短** = 扫面要求变严，S 判据本体一行未动。
}

passed = failed = 0
DETAIL = []

from _check import bind_check  # noqa: E402

check = bind_check(globals(), "passed", "failed", "DETAIL")


#: 处理块里一到就结束的语句 —— 它们**之后**的代码永远不执行。
_TERMINATORS = (ast.Return, ast.Raise, ast.Break, ast.Continue)


def _executable(body):
    """交出「处理块里真正会执行到」的语句。

    ★ 审计 L2313-②（2026-09-29，批次 3）：原判据用 `ast.walk` 走**整棵子树**，
    于是「诊断调用写在 `return` 之后」或「写在一个从没被调用的嵌套 `def` 里」
    同样算「已接诊断」⇒ 那样的 `except` 被判成 W（合格）而实际一个字都不出声。
    扫面变宽/重构改写时这类块会混进包，**门禁从此对它们失明**。
    这里收两处：① `return`/`raise`/`break`/`continue` 之后的部分不交；
    ② 不下钻进新的函数/类/lambda 作用域（那里面的调用不是本块的行为）。
    """
    out = []
    for st in body:
        out.append(st)
        if isinstance(st, _TERMINATORS):
            break
    return out


class _Shallow(ast.NodeVisitor):
    """只在本层找 `Call` / `Raise`，不下钻进新的作用域。"""

    def __init__(self):
        self.found = None

    def visit_Call(self, n):
        if self.found is not None:
            return
        nm = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
        if nm in ("diag", "_diag"):
            self.found = "diag"
            return
        self.generic_visit(n)

    def visit_Raise(self, n):
        if self.found is None:
            self.found = "raise"

    # ★ 新的作用域：里面的 `diag` / `raise` 不算本块的（没被调用就等于没出声）。
    def visit_FunctionDef(self, n):
        pass

    def visit_AsyncFunctionDef(self, n):
        pass

    def visit_ClassDef(self, n):
        pass

    def visit_Lambda(self, n):
        pass


def _scan_body(body):
    v = _Shallow()
    for st in _executable(body):
        v.visit(st)
    return v.found


def has_diag(body):
    return _scan_body(body) == "diag"


def has_raise(body):
    return _scan_body(body) == "raise"


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


def classify_text(src_text):
    """→ [分类]：给「构造出来的片段」用，与 `classify` **同一套**分类器。

    单独开这个口是为了让精度断言能钉分类器本身，而不必造临时文件去扫全包。
    """
    return [("W" if has_diag(h.body) else ("R" if has_raise(h.body) else "S"))
            for h in ast.walk(ast.parse(src_text))
            if isinstance(h, ast.ExceptHandler)]


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
# ★ 审计 L2313-②（2026-09-29，批次 3）：分类器自身的两条精度断言。
#   把分类器放宽只要三行（换回 `ast.walk` 走整棵子树）而后果极重 ——
#   「已接诊断」一旦认死代码里的调用，「静默兜底 S = 0」整条就是恒真的同义反复，
#   门禁从此对「写了诊断但一个字都不出声」的那批 `except` 失明。
#   这几条打的是**分类器**，与被测包的改动无关，恒定成立。
print("\n【4. 反证：分类器把「其实没出声的 except」判成 W/R ⇒ 必须报红】")
_CLS = [
    ("真·接诊断通道",
     "try:\n    pass\nexcept Exception:\n    _diag(b, 'x', e)\n", "W"),
    ("★diag 写在 return 之后（死代码）",
     "try:\n    pass\nexcept Exception:\n    return 0\n    _diag(b, 'x', e)\n", "S"),
    ("★diag 写在一个从没被调的嵌套 def 里",
     "try:\n    pass\nexcept Exception:\n    def _log():\n        _diag(b, 'x', e)\n", "S"),
    ("★diag 写进 lambda（没被调）",
     "try:\n    pass\nexcept Exception:\n    _f = lambda: _diag(b, 'x', e)\n", "S"),
    ("★raise 写在 return 之后（死代码）",
     "try:\n    pass\nexcept Exception:\n    return 0\n    raise ValueError('x')\n", "S"),
    ("真·显式抛",
     "try:\n    pass\nexcept Exception:\n    raise ValueError('x')\n", "R"),
    ("真·诊断写在 try 块里（不是处理块 ⇒ 不算接了诊断）",
     "try:\n    _diag(b, 'x', e)\nexcept Exception:\n    pass\n", "S"),
]
_wrong = ["%s 判成 %s（应 %s）" % (n, classify_text(b), w)
          for n, b, w in _CLS if classify_text(b) != [w]]
check("★分类器：死代码 / 嵌套作用域里的 diag·raise 不算『已出声』",
      not _wrong, "；".join(_wrong))
check("★分类器：真接诊断 / 真显式抛仍认得（防上面那条把自己收得过严）",
      classify_text(_CLS[0][1]) == ["W"] and classify_text(_CLS[5][1]) == ["R"],
      "接诊断=%s 显式抛=%s" % (classify_text(_CLS[0][1]), classify_text(_CLS[5][1])))


print("\n【5. 反证：扫面被改窄（只剩 battle/）⇒ 必须报红】")
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
