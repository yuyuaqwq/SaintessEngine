#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""常驻门禁：公式**段乘区**回落只认 `None`，合法 `0.0` 不被 `or` 吞（审计 L246 同族）。

跑法：python tests/test_l246_formula_mult_zero_gate.py

背景
----
审计 L5618 那一族（承伤乘区 `ctx.get("mult", 1.0) or 1.0`）已由 orlandia 87f473a 收口，
引擎侧 `landing.py` 早在 2026-09-11 就写明了权威口径：

    乘区值 **0.0 是合法值**（格挡 / 无敌帧 / 完全免伤），而 `0.0 or 1.0` 会被吞成 1.0
    ⇒ 0 乘区永远失效。None 才回落 1.0。

**同一族的另一半在引擎的公式解释器里没跟**：`resolve_formula` / `skill_expr_preview`
两处仍在 `float(seg.get("mult", 1.0) or 1.0)`。对「段乘区」而言 0 与缺键语义完全相反：

    0   = 这一段是零伤/零治疗段（作者可声明的合法配置）
    缺键 = 这一段不吃乘区（按 1.0 算）

⇒ 吞掉之后「零伤段 / 零治疗段」这类配置**做不出来**，且零报错、零日志。

判定
----
1. `resolve_formula`：`mult=0.0` 的段**不得**与 `mult=1.0` 同值（行为向，钉死"0 没被吞"）
2. `skill_expr_preview`：同上（它走的是另一条读法，曾实测 0.0 与 1.0 都出 10000.0）
3. **缺键 / 显式 None 仍回落 1.0**（收紧不得误伤真源没写乘区的那一段）
4. 非零取值逐值不变（0.5 / 1.0 / 2.0）
5. **静态向**：两个文件里不得再出现 `get("mult", 1.0) or 1.0` 这一形态
6. **两向反证**：把任一处改回旧写法，判据必须转红 —— 证明它真在钉这件事
7. ★ **第四轮新增（静态扫描根扩面 + 覆盖面自证）**：上面第 5 条只扫 `formulas.py` 一个文件
   —— 那正是包仓第一轮「列名 4 个文件」漏掉整个 `content/flow/` 的同一个坑。
   ⇒ 改为扫 `extends/` + `saintess_engine/` + `editor/` + `tools/` + `examples/` 整棵子树，
   **外加「扫到 >= 180 个 .py」的覆盖面断言**（实测 188 · 命中 0）。
   ⇒ ★ 反面约束：**不要**照「引擎里还有 `or`」去改别处。`x.get(k, 1.0) or 1.0` 只在
     **乘法读点**上吞 0；用在**布尔谓词**上是另一族（判据得分开写，见包仓门禁的分族判据）。
"""
from __future__ import annotations

import ast
import io
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "extends"))

from _check import bind_check                                    # noqa: E402
from _l246_surface_scan import MULT_KEYS as _MULT_KEYS           # noqa: E402
from _l246_surface_scan import doc_lines as _doc_lines           # noqa: E402
from _l246_surface_scan import scan_tree                         # noqa: E402

FAILS: list = []
PASS = 0
check = bind_check(globals(), "PASS", "FAIL", "FAILS")

_FORMULAS = os.path.join(_ROOT, "extends", "ext_combat", "battle", "formulas.py")

# ★ 审计 L246 同族 · 第四轮扩面：静态扫描根由「逐个列名的 1 个文件」扩到**引擎自有的整棵产品子树**。
#   同一形态在两个仓各犯一次（教训链）：
#     · 第一轮（包仓）：扫描根 = 逐个列名的 4 个文件 => 整个 content/flow/ 漏网（第二十二轮实测）
#     · 第二轮（包仓）：扩到 content/flow/，仍是「已知处 + 一个目录」=> 再按形态扫整棵 content/
#     · 第三轮（本文件）：扫描根 = **单个** formulas.py，且**没有覆盖面自证**
#       => 「我扫够了没有」永远无法判定（本轮实测整棵子树的文件数与命中数后才敢说清）。
#   ⇒ 这一条不是「多加几个断言」，是把「够宽」变成**可判定的**（Step 0g）。
# ★ `_MULT_KEYS` / `_doc_lines` / 扫描主体已收进**共享** `tests/_l246_surface_scan.py`
#   （第三十四轮收口）—— 本文件原来带着**第三份逐字复制**的扫描实现。
#   同族教训（Step 0f）：同一份判定逻辑在 N 个文件各存一份 = 双源，改一处忘另一处。
# 跳过目录里 games/ 是**子模块检出**（别人的仓）=> 由包仓那份 whole_tree 门禁管，本门禁不越界。
_SKIP_DIRS = {"__pycache__", ".git", "data", "docs", "design", "tests", "games"}
# 扫哪些子树：引擎自有的产品面。**不写死文件** —— 写死的根就是下一轮漏网的起点。
_SCAN_ROOTS = ("extends", "saintess_engine", "editor", "tools", "examples")
_ENGINE_PY_MIN = 180          # 覆盖面自证下限（实测 188，留余量给增删）

_STATS = {"atk": 1000, "matk": 0, "max_hp": 5000, "level": 10, "_skill_lv": 1}


def _formulas():
    from ext_combat.battle import formulas as F
    return F


def test_resolve_formula_zero_segment_not_swallowed():
    """行为向：`resolve_formula` 的段乘区 0.0 必须真的走到 0（不再被 `or` 吞成 1.0）。"""
    F = _formulas()
    seg = lambda m: [{"stat": "atk", "mult": m, "type": "phys"}]  # noqa: E731
    z, _ = F.resolve_formula(seg(0.0), dict(_STATS), 0, 0, variance=0.0, randomize=False)
    o, _ = F.resolve_formula(seg(1.0), dict(_STATS), 0, 0, variance=0.0, randomize=False)
    h, _ = F.resolve_formula(seg(0.5), dict(_STATS), 0, 0, variance=0.0, randomize=False)
    # 注：伤害走 calc_damage 的 `dmg = max(1, dmg)` 伤害下限（另一条有意规则），
    #     所以 0 段出参是 1 而不是 0 —— 判据钉的是「0 与 1.0 **不同值」」。
    check("resolve_formula 段乘区 0.0 与 1.0 不同值（0 未被 or 吞）", z != o, f"z={z} o={o}")
    check("resolve_formula 段乘区 0.5 落在 0 与 1.0 之间", 0 < h < o, f"h={h} o={o}")


def test_skill_expr_preview_zero_segment_not_swallowed():
    """行为向：`skill_expr_preview` 走另一条读法（曾实测 0.0 与 1.0 都出 10000.0）。"""
    F = _formulas()
    p = lambda m: F.skill_expr_preview({"heal_formula": [{"expr": "atk", "mult": m}]}, 1, dict(_STATS))  # noqa: E731
    check("skill_expr_preview 段乘区 0.0 得 0（未被 or 吞）", p(0.0) == 0.0, f"got={p(0.0)}")
    check("skill_expr_preview 段乘区 1.0 得 1000（对照）", p(1.0) == 1000.0, f"got={p(1.0)}")
    check("skill_expr_preview 段乘区 0.5 得 500（对照）", p(0.5) == 500.0, f"got={p(0.5)}")


def test_missing_and_none_still_fall_back_to_one():
    """缺键 / 显式 None 仍回落 1.0 —— 收紧不得误伤「真源没写乘区」那一段。"""
    F = _formulas()
    d, _ = F.resolve_formula([{"stat": "atk", "type": "phys"}], dict(_STATS), 0, 0,
                             variance=0.0, randomize=False)
    n, _ = F.resolve_formula([{"stat": "atk", "mult": None, "type": "phys"}], dict(_STATS), 0, 0,
                             variance=0.0, randomize=False)
    one, _ = F.resolve_formula([{"stat": "atk", "mult": 1.0, "type": "phys"}], dict(_STATS), 0, 0,
                               variance=0.0, randomize=False)
    check("resolve_formula 缺键回落 1.0", d == one, f"d={d} one={one}")
    check("resolve_formula 显式 None 回落 1.0", n == one, f"n={n} one={one}")
    p = F.skill_expr_preview({"heal_formula": [{"expr": "atk"}]}, 1, dict(_STATS))
    check("skill_expr_preview 缺键回落 1.0", p == 1000.0, f"got={p}")


def test_no_or_swallow_pattern_in_source():
    """静态向：段乘区读点不得再用 `get("mult", ...) or <默认>`（只扫代码，不扫 docstring）。

    刻意不用正则扫全文：本文件的 `_num` docstring 为了说明历史写法会**引用同一个字面串**
    （那是文档不是活代码）⇒ 走 AST 的 `BoolOp(op=Or)`，只看真代码。
    """
    tree = ast.parse(io.open(_FORMULAS, encoding="utf-8").read())
    bad = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or) and len(n.values) == 2):
            continue
        lhs = n.values[0]
        if (isinstance(lhs, ast.Call) and isinstance(lhs.func, ast.Attribute)
                and lhs.func.attr == "get" and lhs.args
                and isinstance(lhs.args[0], ast.Constant) and lhs.args[0].value == "mult"):
            bad.append(n.lineno)
    check("formulas.py 零处 `get(\"mult\", ...) or <默认>`", not bad, f"命中行 {bad}")


def test_both_call_sites_use_shared_helper():
    """两个段乘区读点都必须走共享回落（`_num`），防「改了一处漏一处」。"""
    tree = ast.parse(io.open(_FORMULAS, encoding="utf-8").read())
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for fname, var in (("resolve_formula", "fmult"), ("skill_expr_preview", "_total")):
        node = fns.get(fname)
        check(f"{fname} 存在", node is not None)
        if node is None:
            continue
        seg_get = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "get" and n.args
            and isinstance(n.args[0], ast.Constant) and n.args[0].value == "mult"
            for n in ast.walk(node))
        check(f"{fname} 仍读段 mult（不得改成硬编码）", seg_get)
        uses_num = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_num"
            for n in ast.walk(node))
        check(f"{fname} 段乘区走 _num 回落", uses_num)


def test_static_whole_engine_tree():
    """静态向：引擎自有子树零处 `get(乘区键, 非零默认) or 常量`（含覆盖面自证）。

    ★ 扫描主体走**共享** `scan_tree`（第三十四轮收口）：本文件原来带着第三份逐字复制，
      与 orlandia 那份、新增的两面门禁共三份实现 —— 同一族逻辑改一处忘一处是 Step 0f
      点名的双源形态。此处只保留**本门禁特有的三件事**：扫哪几棵子树、覆盖面下限、
      报告标签里的子树前缀（保持既有标签 `extends/.../formulas.py:NN` 不变）。
    """
    hits, scanned, parse_fail = [], 0, []
    for sub in _SCAN_ROOTS:
        root_dir = os.path.join(_ROOT, sub)
        if not os.path.isdir(root_dir):
            parse_fail.append("扫描根不存在: %s" % sub)
            continue
        n_scanned, n_hits, n_fail, _per = scan_tree(root_dir, skip_top=_SKIP_DIRS)
        scanned += n_scanned
        parse_fail.extend("%s: %s" % (sub, f) for f in n_fail)
        hits.extend("%s/%s" % (sub, h) for h in n_hits)
    check("引擎子树全部可解析（扫描前提）", not parse_fail, "解析失败 %s" % parse_fail)
    check("引擎自有子树扫到 >=%d 个 .py（覆盖面自证）" % _ENGINE_PY_MIN,
          scanned >= _ENGINE_PY_MIN, "只扫了 %s" % scanned)
    check("引擎自有子树零处 get(乘区键, 非零) or 常量", not hits, "命中 %s" % hits)


def main() -> int:
    test_resolve_formula_zero_segment_not_swallowed()
    test_skill_expr_preview_zero_segment_not_swallowed()
    test_missing_and_none_still_fall_back_to_one()
    test_no_or_swallow_pattern_in_source()
    test_both_call_sites_use_shared_helper()
    test_static_whole_engine_tree()
    print(f"\nPASS={PASS} FAIL={len(FAILS)}")
    for f in FAILS:
        print("  FAIL:", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
