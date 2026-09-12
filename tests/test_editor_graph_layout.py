# -*- coding: utf-8 -*-
"""拓扑视图布局（app.js 的 graphLayout）行为测试的**调度器** —— 有 node 就真跑，没有就明确跳过。

为什么要它：布局是「画得对不对」的唯一可钉住的部分（同 depth 同列、边端点落在节点框上、
空/坏数据不崩），而它是纯函数 —— 用 Node 把 `app.js` 里 `##GRAPH_LAYOUT_BEGIN/END##` 之间那段
抠出来真跑，比肉眼看图可靠。接线进 `tests/run_all.py` 后，改了布局忘了改测试会当场红。

跑法：python tests/test_editor_graph_layout.py
退出码：0 = 通过（或本机无 node 而显式跳过）；1 = 有断言失败。
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
JS = os.path.join(HERE, "js", "graph_layout_test.js")


def main() -> int:
    print("== 拓扑视图布局测试（app.js · graphLayout · Node 打桩）==")
    node = shutil.which("node")
    if not node:
        print("  ⚠ 本机没有 node —— 跳过（布局需人工用浏览器验证；这不影响生成本身）")
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
