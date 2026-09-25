#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：作用域解析 —— `extends/ext_combat/battle/*.py` 里**不许出现解析不到的名字**。

为什么要有它（2026-09-25 实测两起同类真 bug）
------------------------------------------------------------------
① `schedule.py` 的 `pct_cur` 分支改标签口径时漏改一行：`_boss_like` 已改名成 `_trait_like`
   （定义也删了）却还在读 ⇒「按当前生命% 掉血」的 DoT（武器特效 `blood_trace`）一跳就抛
   `NameError`，异常直接冒到 `advance()`（战斗推进崩）。当时引擎自检 / 内容探针都全绿 ——
   因为没有任何用例走到那条分支。
② E1 批量把 `_diag(battle, …)` 插进 `except` 体时，有 5 处的**作用域里根本没有 `battle`**
   （方法里 `self` 才是那一场；纯计算 helper 连 battle 都拿不到）：
   `battle.py:128/618/637` · `formulas.py:398` · `landing.py:530`。
   这是**容错路径**上的地雷：真出错时抛 NameError，把「不再静默」变成「炸在诊断上」。

判据（AST 逐作用域，零依赖）
------------------------------------------------------------------
每个函数的作用域可见名 = 自己的绑定（参数 / 赋值 / import / 内层 def·class 名 / global·nonlocal）
  ∪ 外层函数链可见名 ∪ 模块级名 ∪ 内置名；`lambda` / 推导式按各自作用域处理。
扫 `Name(Load)`：不在可见集里 ⇒ 报红（file:行 + 所属函数）。

边界（有意保守）
  · 只看裸名，不判属性是否存在（`x.foo`）；不判运行期注入（本包不用 `globals()[…]=`）。
  · 嵌套函数体归嵌套作用域算，不摊到外层（否则会把闭包参数误报成越界）。

跑法：`python tests/test_battle_name_scope.py`；退出码 0 = 全绿 · 1 = 有失败。
"""
import ast
import builtins
import io
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__builtins__", "__package__"}
TARGET_DIR = os.path.join(ROOT, "extends", "ext_combat", "battle")

passed = failed = 0
DETAIL = []

from _check import bind_check  # noqa: E402

check = bind_check(globals(), "passed", "failed", "DETAIL")

_NESTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def module_names(tree):
    """模块级可见名（含 if/try/for 里赋的值、import 别名）。"""
    out = set()
    for n in ast.walk(ast.Module(body=tree.body, type_ignores=[])):
        if isinstance(n, _NESTED):
            out.add(n.name)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            out.add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            out.update(n.names)
    return out


def _args_of(args):
    out = {a.arg for a in list(getattr(args, "posonlyargs", [])) + list(args.args)
           + list(args.kwonlyargs)}
    if args.vararg:
        out.add(args.vararg.arg)
    if args.kwarg:
        out.add(args.kwarg.arg)
    return out


def own_bindings(node):
    """本作用域自己的绑定（嵌套 def/class 只收名字；lambda 体不进本作用域）。"""
    out = set()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        out |= _args_of(node.args)
    stack = list(node.body)
    while stack:
        cur = stack.pop()
        if isinstance(cur, _NESTED):
            out.add(cur.name)
            continue
        if isinstance(cur, ast.Lambda):
            continue                        # 自带作用域，由 loads_of 处理
        if isinstance(cur, ast.Name) and isinstance(cur.ctx, ast.Store):
            out.add(cur.id)
        elif isinstance(cur, (ast.Import, ast.ImportFrom)):
            for a in cur.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(cur, (ast.Global, ast.Nonlocal)):
            out.update(cur.names)
        elif isinstance(cur, ast.ExceptHandler) and cur.name:
            out.add(cur.name)
        stack.extend(ast.iter_child_nodes(cur))
    return out


def loads_of(body, visible):
    """本作用域内（不下钻嵌套函数/类）解析不到的名字 → [(行号, 名字)]"""
    bad = []
    stack = list(body)
    while stack:
        cur = stack.pop()
        if isinstance(cur, _NESTED):
            continue                        # 嵌套作用域交给 walk_body
        if isinstance(cur, ast.Lambda):
            inner = visible | _args_of(cur.args)
            for b in loads_of([cur.body], inner):
                bad.append(b)
            continue
        if isinstance(cur, ast.Name) and isinstance(cur.ctx, ast.Load):
            if cur.id not in visible and cur.id != "self":
                bad.append((cur.lineno, cur.id))
        stack.extend(ast.iter_child_nodes(cur))
    return bad


def scan_file(path):
    """→ [(行号, 名字, 所属函数)]"""
    tree = ast.parse(io.open(path, encoding="utf-8").read(), filename=path)
    top = module_names(tree) | BUILTINS
    bad = []

    def walk_body(body, visible):
        """逐层：函数/类各自成作用域；非 def 语句里嵌的 def 也要扫到。"""
        for stmt in body:
            if isinstance(stmt, _NESTED):
                vis = visible | own_bindings(stmt)
                bad.extend((ln, nm, stmt.name) for ln, nm in loads_of(stmt.body, vis))
                walk_body(stmt.body, vis)
            else:
                for sub in ast.iter_child_nodes(stmt):
                    if isinstance(sub, _NESTED):
                        vis = visible | own_bindings(sub)
                        bad.extend((ln, nm, sub.name) for ln, nm in loads_of(sub.body, vis))
                        walk_body(sub.body, vis)
                    else:
                        walk_body([sub], visible)

    walk_body(tree.body, top)
    bad.extend((ln, nm, "<module>") for ln, nm in loads_of(tree.body, top))
    return bad


print("【1. 扫面：%s】" % os.path.relpath(TARGET_DIR, ROOT))
files = sorted(f for f in os.listdir(TARGET_DIR) if f.endswith(".py"))
check("扫到源文件（≥15）", len(files) >= 15, "n=%d" % len(files))
all_bad = []
for fn in files:
    for lineno, name, owner in scan_file(os.path.join(TARGET_DIR, fn)):
        all_bad.append("%s:%d  名字 `%s`（在 `%s` 里）" % (fn, lineno, name, owner))
check("★ 无「解析不到的名字」（作用域里用到的都必须先绑定）", not all_bad,
      "命中 %d 处：" % len(all_bad) + " | ".join(all_bad[:8]))

print("\n【2. 反证：这两处历史地雷不许回归】")
src = io.open(os.path.join(TARGET_DIR, "schedule.py"), encoding="utf-8").read()
names = {n.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Name)}
check("反证·`_boss_like` 作为**名字**零出现（注释里提它不算；E3 刀1 改名漏改的那处）",
      "_boss_like" not in names, str(sorted(x for x in names if "boss_like" in x)))
check("反证·`_trait_like` 在 schedule.py 里「先绑定后使用」",
      src.index("_trait_like =") < src.index("_trait_like and"))

print("\n【3. 反证：故意造一个未定义名 ⇒ 扫描器必须报红（有牙）】")
_tmp = os.path.join(ROOT, "tests", "_scope_negative_tmp.py")
io.open(_tmp, "w", encoding="utf-8").write(
    "def outer(a):\n"
    "    def inner(b):\n"
    "        return b\n"
    "    return a + not_defined_anywhere + inner(a)\n"
    "\n"
    "L = lambda q: q + also_missing\n")
try:
    hit = scan_file(_tmp)
finally:
    os.remove(_tmp)
got = {x[1] for x in hit}
check("反证·外层未定义名被抓到（`not_defined_anywhere`）", "not_defined_anywhere" in got, str(sorted(got)))
check("反证·lambda 体里的未定义名被抓到（`also_missing`）", "also_missing" in got, str(sorted(got)))
check("反证·内层函数的参数**不**误报（`inner` 的 b 与闭包 a 都算已绑定）",
      "b" not in got and "a" not in got and "q" not in got, str(sorted(got)))

print("\n结果：通过 %d / 共 %d" % (passed, passed + failed))
if failed:
    print("失败项：")
    for x in DETAIL:
        print("  · %s" % x)
    sys.exit(1)
