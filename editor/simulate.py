# -*- coding: utf-8 -*-
"""沙箱试跑（父进程侧）—— 只起子进程，**绝不 import saintess_engine**。

为什么必须子进程（与游戏侧编辑器同款理由，别改成直接 import）：
1. 装配副作用：`saintess_engine.config.mount()` 会把 hook 挂到引擎**进程级全局**面，跑一次
   就污染编辑器进程本身。
2. 隔离兜底：第三方游戏包的 apply.py 可能有异常/死循环 → 子进程超时可掐死，
   编辑器永不崩。
3. 循环导入：游戏包的 `content` 与引擎/数据之间常互相 import，主进程里装配易踩半初始化。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FRAMEWORK_ROOT = os.path.dirname(HERE)
WORKER = os.path.join(HERE, "simulate_worker.py")
TIMEOUT = int(os.environ.get("FW_SIM_TIMEOUT", "60"))
MARKER = "__FW_SIM_RESULT__"


def run(pkg_dir: str, payload: dict) -> dict:
    """把 payload 喂给 worker，解析 stdout 的 marker 行。"""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
           "FW_FRAMEWORK_ROOT": FRAMEWORK_ROOT, "FW_PKG_DIR": pkg_dir}
    try:
        pr = subprocess.run([sys.executable, WORKER], input=json.dumps(payload),
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", env=env, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"ok": False, "stage": "timeout",
                "message": f"试跑超时（{TIMEOUT}s）——检查包里的 apply.py 是否有死循环"}
    out = pr.stdout or ""
    for line in out.splitlines():
        if line.startswith(MARKER):
            try:
                return json.loads(line[len(MARKER):])
            except json.JSONDecodeError:
                break
    return {"ok": False, "stage": "crash",
            "message": "试跑子进程未返回结果",
            "stdout": out[-3000:], "stderr": (pr.stderr or "")[-3000:]}
