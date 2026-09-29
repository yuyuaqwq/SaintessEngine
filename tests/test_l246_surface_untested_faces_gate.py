# -*- coding: utf-8 -*-
r"""常驻门禁：L246 同族（乘区回落只认 None）在**两个此前无判据覆盖面**上的静态扫描。

为什么有这道门禁（第三十三轮的实测结论）
------------------------------------------
第 32 轮扫完四个面后写下这张表：

| 面 | 门禁 |
|---|---|
| 引擎自有子树 | `test_l246_formula_mult_zero_gate.py` |
| orlandia 包 | `games/orlandia/tests/test_l246_mult_zero_whole_tree_gate.py` |
| 宿主自有码 | **无门禁** ← 本文件 |
| aetheran 包 | **无门禁** ← 本文件 |

★ 最后两行当时是**缺口不是结论**：它们当轮干净（实测 30 次扫描里 0 命中），
但「干净」的原因是「我今天扫过」，不是任何判据保证 ⇒ 下一轮谁都不看那两面，
一个 `get("mult", 1.0) or 1.0` 就能悄悄长出来（Step 0g「收敛 ≠ 清零」）。

覆盖面自证（Step 0g 的教训链：第一轮门禁的扫描根是「逐个列名的 4 个文件」⇒ 整个
`content/flow/` 漏网；第二轮扩到一个目录 ⇒ 再按形态扫整棵树；第三轮加「扫到 ≥ N 个
.py」断言 ⇒ 「够宽」才成为**可判定**的）。本文件的 N 按实测取：
aetheran content/ = 60 · 宿主自有码 = 158（实测，不含 framework/ 子模块检出）。
留余量取下限 50 / 140 —— 上限不设：文件多了只会更严，不会更松。

★ 故意不扫 `framework/`：宿主仓里 `framework/` 是引擎的**子模块检出**（别人的仓），
  它的两个游戏包另有门禁（orlandia 那份）⇒ 宿主门禁越界扫 = 把别人的仓算进自己的覆盖面。
  写明这一点，否则「扫到 158」会给人「整仓都扫了」的错觉。

跑法：python tests/test_l246_surface_untested_faces_gate.py
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _ROOT)

from _check import bind_check                                    # noqa: E402
from _l246_surface_scan import scan_tree                          # noqa: E402

check = bind_check(globals(), "PASS", "FAIL", "FAILS")
FAILS: list = []

# 覆盖面下限（实测 60 / 158，留余量；上限不设 —— 多文件只会更严）
FACES = (
    # (标签, 仓根, 整棵排除的第一层目录, 覆盖面下限)
    ("aetheran 包 content/", r"C:/Users/yuyu/aetheran-package", ("tests", "scripts"), 50),
    ("宿主自有码", r"C:/Users/yuyu/qqbot/data/plugins/dragonfall", ("framework",), 140),
)

def _scan_face(label, root, skip_top, min_py):
    if not os.path.isdir(root):
        check("%s 仓存在（扫描前提）" % label, False, "仓不存在: %s" % root)
        return
    scanned, hits, parse_fail, _per = scan_tree(root, skip_top)
    check("%s 全部可解析（扫描前提）" % label, not parse_fail, "解析失败 %s" % parse_fail)
    check("%s 扫到 >= %d 个 .py（覆盖面自证）" % (label, min_py), scanned >= min_py,
          "只扫了 %s（若确有大规模删除，请同步下调本下限并在提交消息里说明）")
    check("%s 零处 get(乘区键, 非零) or 常量" % label, not hits, "命中 %s" % hits)


def test_faces():
    for label, root, skip_top, min_py in FACES:
        _scan_face(label, root, skip_top, min_py)


def test_face_roots_are_not_inside_each_other():
    """自纠：两个面必须指向**不同的仓**（写成同一个仓 = 覆盖面自证变成永真），
    且宿主那一面必须整棵排除 `framework/`（子模块检出 = 别人的仓，不越界）。"""
    roots = [os.path.normcase(os.path.abspath(f[1])) for f in FACES]
    check("两个面指向两个不同的仓（不得互相覆盖）", len(set(roots)) == len(roots),
          "roots=%s" % roots)
    host_root = r"C:/Users/yuyu/qqbot/data/plugins/dragonfall"
    skip = next((f[2] for f in FACES if os.path.normcase(f[1]) == os.path.normcase(host_root)), ())
    check("宿主面整棵排除 framework/（子模块检出=别人的仓，不越界）",
          "framework" in skip, "skip=%s" % (skip,))


def main() -> int:
    test_faces()
    test_face_roots_are_not_inside_each_other()
    print("\nPASS=%d FAIL=%d" % (PASS, len(FAILS)))
    for f in FAILS:
        print("  FAIL:", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
