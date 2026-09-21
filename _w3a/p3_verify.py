# -*- coding: utf-8 -*-
"""P3 验证：`expr` 扩 `^` 的**零回归 + 有牙**双证。

用法：  python _w3a/p3_verify.py

反证 1（零回归 · 结构层）：
    取**旧版** `expr/__init__.py`（`git show HEAD:...`）与**新版**各加载一次，
    对同一批表达式语料编译，逐项比较操作数栈 ⇒ 不含 `^` 的必须**逐项相同**。
反证 2（有牙 · 新语法真生效）：
    `^` 的求值/优先级/右结合/退化四条断言，任何一条坏了就报红。
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile

ENGINE = r"C:/Users/yuyu/framework-engine"


def load_expr_from(source: str, name: str):
    """把一段 expr 模块源码写成临时文件并加载（与真实模块隔离）。"""
    d = tempfile.mkdtemp()
    p = os.path.join(d, "exprmod.py")
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(source)
    spec = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def main():
    rel = "saintess_engine/expr/__init__.py"
    old_src = subprocess.run(["git", "-C", ENGINE, "show", f"HEAD:{rel}"],
                             capture_output=True).stdout.decode("utf-8")
    with open(os.path.join(ENGINE, rel), encoding="utf-8") as f:
        new_src = f.read()

    old = load_expr_from(old_src, "_expr_old")
    new = load_expr_from(new_src, "_expr_new")
    print("旧版/新版模块各加载一次  ✅")

    # ── 语料：既有写法（不含 ^）+ 真实数据里的公式形态
    corpus = [
        "atk*1.5", "atk * 2 + 10", "max_hp*0.1", "atk/2", "a-b-c", "a/b/c",
        "1+2*3-4/2", "(atk+10)*1.2", "-(atk*2)", "atk*(1-0.3)",
        "base+atk*skill_lv*0.1", "((a+b)*c-d)/e", "2*(3+4)*5", "a-(-b)",
        "spd*1", "1.0", "0.5*atk+0.5*matk", "crit_mult*(1+0.5)",
    ]
    print("\n【反证 1】零回归：不含 `^` 的表达式，编译产物逐项相同")
    bad = 0
    for e in corpus:
        try:
            a, b = old.compile_expr(e), new.compile_expr(e)
        except Exception as exc:                       # noqa: BLE001
            print(f"  ❌ {e!r} 编译异常 {exc}")
            bad += 1
            continue
        if a == b:
            print(f"  ✅ {e!r}  RPN {a}")
        else:
            print(f"  ❌ {e!r}\n     旧 {a}\n     新 {b}")
            bad += 1
    print(f"  ⇒ 语料 {len(corpus)} 条，逐项不同 {bad} 条 "
          f"{'✅ 零回归成立' if bad == 0 else '✗ 有回归，不许提交'}")

    print("\n【反证 2】有牙：`^` 的求值 / 优先级 / 右结合 / 退化")
    checks = [
        ("2^3", {}, 8.0, "基本求值"),
        ("2^3^2", {}, 512.0, "右结合 ⇒ 2^(3^2)=2^9；左结合会得 (2^3)^2=64"),
        ("-2^2", {}, -4.0, "一元负号优先级低于幂 ⇒ -(2^2)"),
        ("4^0.5", {}, 2.0, "分数指数（F5 的 α）"),
        ("(100/spd)^0.5", {"spd": 400.0}, 0.5, "F5 真实形态：(SPD_REF/spd)^α"),
        ("(100/spd)^0.5", {"spd": 100.0}, 1.0, "基准速度 ⇒ 1.0"),
        ("2*3^2", {}, 18.0, "幂高于乘 ⇒ 2*(3^2)"),
        ("2^0", {}, 1.0, "零次幂"),
        ("(-4)^0.5", {}, 0.0, "负底+分数指数 ⇒ 复数值 ⇒ 退化为 0（不抛）"),
    ]
    fail = 0
    for ex, vs, want, why in checks:
        got = new.eval_expr(ex, vs)
        ok = abs(got - want) < 1e-9
        fail += 0 if ok else 1
        print(f"  {'✅' if ok else '❌'} {ex:<16} = {got:<10.6f} 预期 {want:<8.3f}  ← {why}")
    print(f"  ⇒ {len(checks) - fail}/{len(checks)} 通过")

    print("\n" + ("=" * 60))
    if bad == 0 and fail == 0:
        print("P3 ✅ 全绿（零回归 + 有牙）")
        return 0
    print("P3 ✗ 未过，不许提交")
    return 1


if __name__ == "__main__":
    sys.exit(main())
