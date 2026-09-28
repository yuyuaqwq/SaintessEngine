# -*- coding: utf-8 -*-
"""★ 审计修复车道 批次4 · 台账 L1185 第 4 条：`ext_dialogue` 包根**不得**再长出门面。

判据来源（台账 L1185-4 原文，2026-09-28 审计）：
    「包门面 re-export **零消费者**：`git grep "from ext_dialogue import"`（引擎）
      与 orlandia 全仓 = **0 处**（两边全部走 `ext_dialogue.dialogue.*` 子路径）。
      docstring:8 自己写「把 `from saintess_engine import X` 改成
      `from ext_dialogue import X`」——**这条建议至今无人执行**。
      …… 要么按 docstring 指引把三处 import 改到包根（一次 sed），要么删门面。
      **注**：`api.md:25` 文档里也写着 `from ext_dialogue import`
      ⇒ 若删门面需同步改文档。」

本轮选了**「删门面」**那一支（不是「改三处 import」）：实跑核实过
`from ext_dialogue import` 在全仓（含 orlandia 与全部测试）= **0 处**
⇒ 没有任何调用方需要它，「改三处 import」实际要改的是**零处**，
门面纯属一层没人用的兼容壳 ⇒ 按「不留兼容壳」删净，不留别名。

★ 为什么还要一支门禁（而不是改完就算）：门面是**极易复活**的形状 ——
  下一个包作者按老习惯 `from ext_dialogue import Dialogue` 会发现能跑
  （门面一回来就又能跑），于是又添一层。本门禁把它钉成「一回来就红」。

★ 三条断言只加强、不放宽：① 包根不导出那三个名字 ② 全仓零 `from ext_dialogue import`
  ③ 文档与 apply.py 教的 import 写法 == 实际取件口（防止**文档**把门面教回来）。
"""
import ast
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "extends"))
sys.path.insert(0, _HERE)

from _check import bind_check  # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []
check = bind_check(globals(), "PASS", "FAIL", "FAILURES")

PKG_DIR = os.path.join(ROOT, "extends", "ext_dialogue")
FACADE_NAMES = ("Dialogue", "Cursor", "END_KEY")


def _py_files():
    for base in (ROOT, os.path.join(ROOT, "games")):
        if not os.path.isdir(base):
            continue
        for r, dirs, fs in os.walk(base):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
            for fn in fs:
                if fn.endswith(".py"):
                    yield os.path.join(r, fn)


def t_package_root_no_facade():
    print("\n[1] ext_dialogue 包根不再门面 re-export（审计 L1185-4）")
    init = os.path.join(PKG_DIR, "__init__.py")
    tree = ast.parse(open(init, encoding="utf-8").read(), filename=init)
    exported = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "dialogue":
            exported |= {a.name for a in node.names}
        if isinstance(node, ast.ImportFrom) and node.module is None and node.level:
            exported |= {a.name for a in node.names}   # `from .dialogue import …`
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "__all__":
                    exported |= {e.value for e in node.value.elts
                                 if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    bad = sorted(set(FACADE_NAMES) & exported)
    check("★ 包根不再导出 %s（门面复活即判红）" % " / ".join(FACADE_NAMES),
          not bad, "残留=%s" % bad)
    ns = {}
    exec(compile(tree, init, "exec"), ns)
    leaked = sorted(n for n in FACADE_NAMES if n in ns)
    check("★ 包根命名空间里也没有这三个名字（别名壳一并禁）",
          not leaked, "残留=%s" % leaked)
    check("★ 装配入口没被误删（install_engine 仍在 apply.py）",
          os.path.exists(os.path.join(PKG_DIR, "apply.py"))
          and "install_engine" in open(os.path.join(PKG_DIR, "apply.py"),
                                       encoding="utf-8").read())


def t_no_consumer_needs_facade():
    print("\n[2] 全仓零 `from ext_dialogue import`（零消费者 = 删门面安全）")
    hits = []
    for p in _py_files():
        try:
            src = open(p, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(src.splitlines(), 1):
            code = line.split("#", 1)[0]
            if re.search(r"^\s*from\s+ext_dialogue\s+import\s+\w", code):
                hits.append("%s:%d" % (os.path.relpath(p, ROOT).replace("\\", "/"), i))
    check("★ 没有任何生产/测试代码走包根门面（否则删门面即断链）",
          not hits, "命中=%s" % hits)


def t_docs_teach_the_real_path():
    print("\n[3] 文档与装配说明教的是真取件口（防止文档把门面教回来）")
    docs = os.path.join(ROOT, "docs", "engine-wiki", "reference", "api.md")
    txt = open(docs, encoding="utf-8").read()
    bad = [m for m in re.findall(r"from\s+ext_dialogue\s+import\s+[\w, ]+", txt)]
    check("★ api.md 不再教 `from ext_dialogue import`（审计点名的文档残留）",
          not bad, "命中=%s" % bad)
    check("★ api.md 那一行已改成真路径 ext_dialogue.dialogue",
          "from ext_dialogue.dialogue import" in txt)
    # 本文件的 docstring 现在就是**整个文件**（包根不再有任何代码）⇒ 按全文断言。
    init_txt = open(os.path.join(PKG_DIR, "__init__.py"), encoding="utf-8").read()
    stale = re.findall(r"改成.{0,20}from ext_dialogue import X", init_txt)
    check("★ 门面 docstring 里那句「改成 from ext_dialogue import」已不在",
          not stale, "命中=%s" % stale)
    check("★ 包根 docstring 写明唯一取件口 = ext_dialogue.dialogue",
          "唯一取件口" in init_txt and "ext_dialogue.dialogue" in init_txt)


def main():
    t_package_root_no_facade()
    t_no_consumer_needs_facade()
    t_docs_teach_the_real_path()
    print("\n===== 结果：通过 %d / %d =====" % (PASS, PASS + FAIL))
    for f in FAILURES:
        print("  ✗ " + str(f))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
