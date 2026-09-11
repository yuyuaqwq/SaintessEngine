#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""框架仓测试运行器：跑 tests/ 下全部 test_*.py + 示例游戏冒烟。

用法：
    python tests/run_all.py            # 全量
    python tests/run_all.py --list     # 只列将运行的文件

退出码：0 = 全绿；1 = 有失败（含超时/崩溃）。
说明：框架仓是独立仓库，自带测试 —— 不依赖任何外部游戏包（奥兰迪亚侧
      `scripts/run_all_tests.py` 会先跑本脚本，见其注释）。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable
TIMEOUT = int(os.environ.get("FW_TEST_TIMEOUT", "600"))

SKIP = {"run_all.py", "conftest.py"}


def discover():
    files = sorted(f for f in os.listdir(HERE)
                   if f.startswith("test_") and f.endswith(".py") and f not in SKIP)
    paths = [os.path.join(HERE, f) for f in files]
    smoke = os.path.join(ROOT, "examples", "minimal-game", "tests", "test_smoke.py")
    if os.path.exists(smoke):
        paths.append(smoke)
    return paths


def main(argv):
    paths = discover()
    if "--list" in argv:
        for p in paths:
            print("  ", os.path.relpath(p, ROOT).replace("\\", "/"))
        return 0

    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    t0 = time.time()
    results = []
    for p in paths:
        rel = os.path.relpath(p, ROOT).replace("\\", "/")
        ts = time.time()
        try:
            pr = subprocess.run([PY, p], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", env=env,
                                timeout=TIMEOUT, cwd=os.path.dirname(p))
            ok, out = pr.returncode == 0, (pr.stdout or "") + (pr.stderr or "")
        except subprocess.TimeoutExpired:
            ok, out = False, f"TIMEOUT after {TIMEOUT}s"
        dt = time.time() - ts
        results.append((rel, ok))
        print(f"{'✅' if ok else '❌'} {rel} ({dt:.1f}s)", flush=True)
        if not ok:
            print("\n".join(out.strip().splitlines()[-30:]), flush=True)
            print("-" * 56, flush=True)

    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'=' * 56}\n文件: {len(results)} 个，通过 {passed}，失败 {len(results) - passed}，"
          f"总耗时 {time.time() - t0:.0f}s")
    return 1 if passed != len(results) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
