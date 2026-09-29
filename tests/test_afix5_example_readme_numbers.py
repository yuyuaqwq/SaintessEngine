# -*- coding: utf-8 -*-
"""常驻门禁：examples/minimal-game/README.md 的**数字说法**不许和代码脱节。

★ 钉的是审计 L5616 的真实形态。台账那条写的是 README 段里两处描述，
此前几轮按「随 L5615 消解（文档未改）」销号 —— 本轮实测**一半是真的、一半是假的**：
  · `PY=".../astrbot/Scripts/python.exe"` 路径存在、命令真跑通（不是问题面）
  · 「20 行内的 main.py」**假**：main.py 现 36 行，且**是被 L5615 自己的修复改假的**
    （498c73e 给三个示例入口补 extends/ 自举，~20 → 36 行）
危害不是「文档不漂亮」：README 是**给第三方照抄的样板说明**。
照着「20 行」的预期只抄两行 sys.path，就会拿到 ImportError ——
正是 L5615 修的那个坑原样复发。

同文件同形态的另一半（Step 0p「台账点了 1 处、同形态实有 N 处」）：
紧接着那行的「冒烟测试 + 纯度自检（**20 项**，exit 0 全绿）」也过期了 ——
test_smoke.py 现在跑 **25 项**（L5615 那批加了出招窗口 / 装配挂载几条）。
两条一起钉，否则下一批又只会改被点名的那一个。

本门禁**只读**：跑真子进程量真数字，不 mock、不改任何产品码。
判据只加强：它不允许 README 与代码脱节，不允许把「不检查」当通过。
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXAMPLE = os.path.join(ROOT, "examples", "minimal-game")
README = os.path.join(EXAMPLE, "README.md")
MAIN_PY = os.path.join(EXAMPLE, "main.py")
SMOKE = os.path.join(EXAMPLE, "tests", "test_smoke.py")

PASS, FAIL = [], []


def check(cond, label):
    (PASS if cond else FAIL).append(label)


def _read(p):
    with io.open(p, encoding="utf-8", newline="") as f:
        return f.read()


def _main_py_lines() -> int:
    with io.open(MAIN_PY, encoding="utf-8", newline="") as f:
        return len(f.read().splitlines())


def _smoke_count() -> tuple[int, str]:
    """真跑 test_smoke.py，取它自己打印的「通过 N / N+failed」那个 N。"""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    p = subprocess.run([sys.executable, SMOKE], capture_output=True,
                       cwd=ROOT, env=env, timeout=300)
    out = (p.stdout or b"").decode("utf-8", "replace")
    m = re.search(r"通过\s*(\d+)\s*/\s*(\d+)", out)
    if not m:
        return -1, (p.stdout or b"").decode("utf-8", "replace")[-200:]
    return int(m.group(2)), out


def test_01_readme_main_py_line_claim_matches():
    """README 说的 main.py 行数 == main.py 真实行数。"""
    real = _main_py_lines()
    src = _read(README)
    claims = re.findall(r"（(\d+)\s*行[，,]\s*含 extends/ 自举）", src)
    claims += re.findall(r"^├─ main\.py\s+(\d+)\s*行跑完一场战斗", src, re.M)
    check(bool(claims), "README 里能取到 main.py 的行数说法（判据自身有输入）")
    for c in claims:
        check(int(c) == real,
              f"README 说的 main.py {c} 行 == 实际 {real} 行")
    check("20 行内的 main.py" not in src,
          "过期的「20 行内的 main.py」说法已不在 README 里")


def test_02_readme_smoke_count_claim_matches():
    """README 说的冒烟测试项数 == test_smoke.py 真跑出来的总项数。"""
    real, out = _smoke_count()
    check(real > 0, f"test_smoke.py 真跑出项数（实测 {real}）")
    src = _read(README)
    claims = re.findall(r"冒烟测试 \+ 纯度自检（(\d+)\s*项", src)
    check(bool(claims), "README 里能取到冒烟测试项数的说法（判据自身有输入）")
    for c in claims:
        check(int(c) == real, f"README 说的 {c} 项 == 实跑 {real} 项")


def test_03_no_stale_twenty_claims_left():
    """反向护栏：整个 minimal-game 目录里不许再残留「20 行 / 20 项」这种过期数字。"""
    hits = []
    for dp, dn, fn in os.walk(EXAMPLE):
        dn[:] = [d for d in dn if d != "__pycache__"]
        for f in fn:
            if not f.endswith((".md", ".py")):
                continue
            p = os.path.join(dp, f)
            try:
                s = _read(p)
            except Exception:
                continue
            for m in re.finditer(r"20\s*(?:行内|行跑完|项)", s):
                hits.append("%s: %s" % (os.path.relpath(p, ROOT).replace("\\", "/"), m.group(0)))
    check(not hits, "minimal-game 全目录零「20 行/20 项」过期数字（实测 %d 处）" % len(hits))
    for h in hits:
        FAIL.append("残留: " + h)


def main():
    for fn in (test_01_readme_main_py_line_claim_matches,
               test_02_readme_smoke_count_claim_matches,
               test_03_no_stale_twenty_claims_left):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            FAIL.append(f"{fn.__name__} 抛异常: {exc!r}")
    for x in PASS:
        print(f"  ✅ {x}")
    for x in FAIL:
        print(f"  ❌ {x}")
    print(f"\n{'=' * 56}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
