# -*- coding: utf-8 -*-
"""常驻门禁：tests/run_all.py 的失败输出**不许把真断言顶出控制台窗口**。

★ 这条门禁钉的是 2026-09-29 晚到批的真实缺陷（`_report` 直接 `[-30:]`）：
断言先炸、收尾噪音（atexit 的 DeprecationWarning / 惰性 import 的 SyntaxWarning）
排在 traceback 之后 ⇒ 窗口里 100% 是噪音、零证据 ⇒ 排障的人**看不到哪条断言炸了**。
  本车道第 35/36/37 三轮各被它挡了一次（当时只拿到「一堆 Warning」，
  拿不到失败断言原文 ⇒ 反复把工具缺陷当成「别线引入的假红」）。

本门禁走**子进程真跑**（不 mock）——注入一个自带收尾噪音的失败用例，
真调 run_all.py 的 `_report`，断言控制台窗口里能看见真断言，且完整输出落盘。
两向反证（把窗口改回 [-30:] ⇒ 本门禁真转红）随落账记录。
"""
from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RUNNER = os.path.join(HERE, "run_all.py")
PY = sys.executable

PASS, FAIL = [], []


def check(cond, label):
    (PASS if cond else FAIL).append(label)


def _load_runner():
    spec = importlib.util.spec_from_file_location("fw_run_all", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- ① 失败用例：断言先炸，atexit 收尾再吐 40 行噪音（复刻真实形态）----
_NOISY_TEST = '''# -*- coding: utf-8 -*-
import atexit, sys
def _late_noise():
    for i in range(40):
        print("noisy/dep.py:%d: DeprecationWarning: late noise %d" % (i, i), file=sys.stderr)
atexit.register(_late_noise)
raise AssertionError("AFIX5-REAL-ASSERT-MARKER")
'''


def test_01_noisy_failure_evidence_is_not_lost():
    """真跑一个「噪音 > 窗口」的自造失败用例，证据必须可见。"""
    d = tempfile.mkdtemp(prefix="afix5_win_")
    logdir = os.path.join(d, "logs")
    tpath = os.path.join(d, "test_afix5_fixture.py")
    io.open(tpath, "w", encoding="utf-8", newline="").write(_NOISY_TEST)
    pr = subprocess.run([PY, tpath], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", cwd=d)
    out = pr.stdout + pr.stderr
    check("AFIX5-REAL-ASSERT-MARKER" in out, "夹具：失败输出里确有真断言标记")

    env = {**os.environ, "FW_TEST_LOG_DIR": logdir}
    spec = importlib.util.spec_from_file_location("fw_run_all_env", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    os.environ["FW_TEST_LOG_DIR"] = logdir
    spec.loader.exec_module(mod)

    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mod._report("tests/test_afix5_fixture.py", False, out, 1.0)
    console = buf.getvalue()
    check("AFIX5-REAL-ASSERT-MARKER" in console,
          "★ 控制台窗口内可见真断言（旧实现此处为 0 —— 缺陷本体）")
    check("Traceback" in console, "控制台窗口内可见 Traceback 头")
    logs = os.listdir(logdir) if os.path.isdir(logdir) else []
    check(len(logs) == 1, "完整输出落盘一个日志文件")
    if logs:
        full = io.open(os.path.join(logdir, logs[0]), encoding="utf-8", newline="").read()
        check("AFIX5-REAL-ASSERT-MARKER" in full
              and full.count("DeprecationWarning") == 40,
              "落盘的是**完整**输出（真断言 + 40 行噪音都在）")
    check("⚠" in console, "截断时控制台**显式标注**（不再无声切窗口）")
    check(env is not None, "env 已就绪")


def test_02_short_output_not_flagged():
    """短输出（≤ 窗口）原样全打，且**不**标截断。"""
    mod = _load_runner()
    lines = ["line %d" % i for i in range(10)]
    w, trunc = mod._evidence_window(lines)
    check(w == lines and trunc is False, "≤窗口的行原样返回且不标截断")


def test_03_pure_noise_falls_back_to_tail():
    """一条证据都认不出 ⇒ 回落尾部 + 标截断（旧行为保留但如实说）。"""
    mod = _load_runner()
    w, trunc = mod._evidence_window(["junk %d" % i for i in range(50)])
    check(len(w) == 30 and trunc is True, "纯噪音回落尾部 30 行并标截断")


def test_04_pass_branch_prints_nothing_extra():
    """ok=True 时不得打印任何日志/警告（不刷屏）。"""
    import contextlib
    mod = _load_runner()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mod._report("tests/test_x.py", True, "", 0.5)
    s = buf.getvalue()
    check("✅" in s and "⚠" not in s and "Traceback" not in s,
          "通过分支只打 ✅（无噪音）")


def main():
    for fn in (test_01_noisy_failure_evidence_is_not_lost,
               test_02_short_output_not_flagged,
               test_03_pure_noise_falls_back_to_tail,
               test_04_pass_branch_prints_nothing_extra):
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
