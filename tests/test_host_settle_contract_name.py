# -*- coding: utf-8 -*-
"""门禁：宿主 _settle 不得再认「零生产者的推测合同名」，缺实现时必须点名留桩。
真源改动 = saintess_engine/host/runtime.py::_settle（审计批次 2 自开口）。"""
import ast, io, os, re, sys
FE = "C:/Users/yuyu/framework-engine"
sys.path.insert(0, os.path.join(FE, "tests"))
from _check import bind_check
check = bind_check(globals(), "PASS", "FAIL", "FAILS")
PASS = FAIL = 0
FAILS = []

RT = os.path.join(FE, "saintess_engine/host/runtime.py")
src = io.open(RT, encoding="utf-8").read()
tree = ast.parse(src)
settle = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_settle"), None)
check("S0 _settle 存在", settle is not None)
seg = ast.get_source_segment(src, settle)

# 剥注释与 docstring 后取源码（★ 批内同族坑：不剥会撞上我自己写的说明注释 ⇒ 恒红）
stripped = "\n".join(ln for ln in seg.splitlines() if not ln.strip().startswith("#"))
d0, d1 = stripped.index('"""'), stripped.index('"""', stripped.index('"""') + 3)
stripped = stripped[:d0] + stripped[d1 + 3:]

check("S1 代码里不再认 victory_settle_plan（剥 docstring/注释后）",
      "victory_settle_plan" not in stripped)

# ★ 自纠（假门禁）：内建 `getattr(x, "n", d)` 的 `n.func` 是 **ast.Name**（id="getattr"），
#   不是 ast.Attribute ⇒ 只判 `isinstance(n.func, ast.Attribute)` 的版本一条都匹配不到 ⇒ 集合为空 ⇒
#   子集判误过（永远绿）。第一版正是这个：把双名 shell 装回去后 S2 仍报绿。
#   两种形式（Name / Attribute）都要签收。
def _is_getattr(node):
    f = node.func
    return ((isinstance(f, ast.Name) and f.id == "getattr")
            or (isinstance(f, ast.Attribute) and f.attr == "getattr"))

attr_names = set()
for n in ast.walk(settle):
    if isinstance(n, ast.Call) and _is_getattr(n):
        if len(n.args) >= 2 and isinstance(n.args[1], ast.Constant):
            attr_names.add(n.args[1].value)
check("S2 getattr 只认唯一契约名（不得有第二个退化名）",
      attr_names == {"settlement_plan"}, "getattr names=%s" % sorted(attr_names))
check("S3 合同名 = settlement_plan", "settlement_plan" in stripped)

stub_msgs = " ".join(re.findall(r"out\.stubs\.append\((.*?)\)\n", seg, re.S))
check("S4 缺实现时留桩文案点名唯一契约名 settlement_plan",
      "settlement_plan" in stub_msgs, "stub msgs found=%d" % bool(stub_msgs))
check("S5 包没装半边仍走 _stub_missing（合法缺席不误伤）",
      "optional_submodule" in stripped and "_stub_missing" in stripped)
check("S6 注释钉住「零生产者」这一事实（防下个读者当有意兼容又加回来）",
      "零生产者" in seg)

producers = []
for root in (FE, "C:/Users/yuyu/framework-engine/games/orlandia",
             "C:/Users/yuyu/aetheran-package"):
    for dp, dn, fn_ in os.walk(root):
        dn[:] = [d for d in dn if d not in (".git", "__pycache__")]
        for f in fn_:
            if f != "settlement.py":
                continue
            p2 = os.path.join(dp, f)
            if os.path.abspath(p2) == os.path.abspath(RT):
                continue
            t2 = io.open(p2, encoding="utf-8", errors="replace").read()
            for nm in ("victory_settle_plan", "settlement_plan", "settle"):
                if re.search(r"^def " + nm + r"\s*\(", t2, re.M):
                    producers.append(p2.replace(FE, "FE:") + ":" + nm)
check("S7 各包 settlement 半边零模块级生产者（前提事实仍成立）",
      not producers, "producers=%s" % producers)

print("PASS=%d FAIL=%d" % (PASS, FAIL))
for f in FAILS:
    print("  x " + f)
sys.exit(1 if FAIL else 0)
