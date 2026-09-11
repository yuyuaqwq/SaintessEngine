# -*- coding: utf-8 -*-
"""前端渲染器（schema_form.js）行为测试的**调度器** —— 有 node 就真跑，没有就明确跳过。

为什么要它：控件形态（长文案给大框 / 0~1 给滑杆 / 枚举数组给多选）是「用对控件」这件事的
唯一证据。用 Node 打桩跑真渲染器，能钉住这些行为，不靠肉眼看点。

跑法：python tests/test_editor_schemaform.py
退出码：0 = 通过（或本机无 node 而显式跳过）；1 = 有断言失败。
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
JS = os.path.join(HERE, "js", "form_widgets_test.js")


def main() -> int:
    print("== 前端渲染器行为测试（schema_form.js · Node 打桩）==")
    node = shutil.which("node")
    if not node:
        print("  ⚠ 本机没有 node —— 跳过（前端行为需人工用浏览器验证；这不影响生成本身）")
        return 0
    if not os.path.exists(JS):
        print(f"  ❌ 找不到测试脚本：{JS}")
        return 1
    pr = subprocess.run([node, JS], capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=ROOT, timeout=120,
                        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (pr.stdout or "") + (pr.stderr or "")
    print(out.rstrip())
    if pr.returncode != 0:
        print(f"\n  ❌ node 退出码 {pr.returncode}（上面有失败断言）")
    return 1 if pr.returncode else 0


if __name__ == "__main__":
    sys.exit(main())
