# -*- coding: utf-8 -*-
r"""共享扫描器：乘区/乘数回落「只认 None」这一族（审计 L246 同族）的静态扫描。

为什么要有这个文件
------------------
同一族在三个仓各犯过一次，门禁也各写过一次：
  · 引擎 `tests/test_l246_formula_mult_zero_gate.py`（扫 extends/ + saintess_engine/ + editor/ + tools/ + examples/）
  · orlandia `tests/test_l246_mult_zero_whole_tree_gate.py`（扫 content/ 子树）
而**aetheran 包**与**宿主自有码**这两面当时**没有常驻判据钉住** ——
第三十三轮实测它们当轮干净，但那是「我今天扫过」，不是判据保证（Step 0g「收敛 ≠ 清零」）。
⇒ 本文件把扫描逻辑收成**一份**，四面门禁共用；差异只由「扫哪些根 + 覆盖面下限 + 豁免表」表达。

判定形态（与三处既有门禁逐字同源，别各自改一套）
------------------------------------------------
命中 = 形如 `x.get(<乘区键>, <非零常量>) or <非零常量>` 的 `BoolOp(Or)`，且不在 docstring 里。
· 默认值 0.0 → 不命中（`x.get(k,0.0) or 0.0` 本来就在保留 0）
· 右值 0 → 不命中（`x or 0` 保留 0）
· 「乘区键」名单 `_MULT_KEYS` 与既有三处一致
★ 走 AST 不走正则：docstring 里为了说明历史写法会引用同一个字面串（那是文档不是活代码）。
"""
from __future__ import annotations

import ast
import io
import os

MULT_KEYS = ("mult", "atk_mult", "hp_mult", "pct", "factor", "rate", "ratio", "scale")
SKIP_DIRS = {"__pycache__", ".git", "data", "tests", "docs", "design"}


def doc_lines(tree):
    """返回「属于 docstring 的行号集合」—— 文档里引用旧写法不算活代码。"""
    bad = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if ast.get_docstring(node, clean=False) is None:
                continue
            first = node.body[0]
            bad.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return bad


def scan_tree(root, skip_top=()):
    r"""扫一棵目录树。返回 (scanned, hits, parse_fail, per_top)。

    skip_top：按「相对根的**第一层**目录名」整棵排除（子模块检出 = 别人的仓，不越界）。
    ★ 只看第一层（本轮实测钉住）：`root/skipme/x.py` 会被排除，`root/content/skipme/x.py`
      **不会** —— 它的第一层是 `content`。要排第二层请把它的第一层加进来。
    ★ 切分必须用 `/`：relpath 在 Windows 上给的是 `\`（本轮实测踩过 —— 用 `os.sep`
      切出来是整个 `framework/games/orlandia`，整棵别人的仓混进本仓覆盖面，30 个命中全是噪音）。
    """
    scanned, hits, parse_fail = 0, [], []
    per_top = {}
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root).replace("\\", "/")
        top = rel.split("/")[0] if rel != "." else ""
        if top in skip_top:
            dirnames[:] = []
            continue
        # ★ 归档目录整棵排除：`_归档_*` / `_archive*` 是搬走的历史件，不是活产品码
        #   （aetheran 仓有 `_归档_2026-09-22_删前`，2 个文件；计入覆盖面会虚高）。
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.startswith(("_归档", "_archive"))]
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            relfile = os.path.relpath(path, root).replace("\\", "/")
            src = io.open(path, encoding="utf-8", errors="replace").read()
            try:
                tree = ast.parse(src)
            except SyntaxError as exc:
                parse_fail.append("%s: %s" % (relfile, exc))
                continue
            scanned += 1
            per_top[top] = per_top.get(top, 0) + 1
            skip = doc_lines(tree)
            for node in ast.walk(tree):
                if not (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)
                        and len(node.values) == 2):
                    continue
                if node.lineno in skip:
                    continue
                lhs = node.values[0]
                if not (isinstance(lhs, ast.Call) and isinstance(lhs.func, ast.Attribute)
                        and lhs.func.attr == "get" and lhs.args
                        and isinstance(lhs.args[0], ast.Constant)):
                    continue
                if lhs.args[0].value not in MULT_KEYS or len(lhs.args) < 2:
                    continue
                try:
                    default = float(lhs.args[1].value)
                except (AttributeError, IndexError, TypeError, ValueError):
                    continue
                if default == 0.0:
                    continue
                try:
                    rhs = float(node.values[1].value)
                except (AttributeError, TypeError, ValueError):
                    rhs = None
                if rhs == 0.0:
                    continue
                hits.append("%s:%s" % (relfile, node.lineno))
    return scanned, hits, parse_fail, per_top
