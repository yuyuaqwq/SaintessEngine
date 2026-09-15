#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""框架仓测试运行器：跑 tests/ 下全部 test_*.py + 示例游戏冒烟。

用法：
    python tests/run_all.py              # 全量（默认并发：max(4, min(16, cpu_count))）
    python tests/run_all.py --jobs=N     # 显式并发度（N≥1；N=1 = 单 worker + 私有状态隔离）
    python tests/run_all.py --serial     # 纯串行（= 改动前的逐字行为；CI 对照 / 排障用）
    python tests/run_all.py --list       # 只列将运行的文件
    python tests/run_all.py --fail-fast  # 首个失败后停止（语义与串行一致）

（`--serial` 与 `--jobs=N` 同时给出 ⇒ 以 `--serial` 为准，并打印一行提示。）

并发口径（与游戏仓 `scripts/run_all_tests.py` **同语义**；口径正文见
`docs/engine-wiki/guides/testing.md`「跑测试」一节）：

  · `--jobs=N` 显式；**缺省 = 按核数自适应 `max(4, min(16, cpu_count))`**；
    `--serial` 恢复纯串行（不建 worker 目录、不注入任何隔离 env ⇒ 逐字等于旧实现）。
  · **每 worker 独立状态**（隔离点清单 —— 缺一个就会「并发假红」）：
      ① 库   ：`GWEN_GAME_DB=<worker 目录>/test_game_data_w<i>.db`
                （`i` = 文件在并行池里的序号，与 `--jobs` 无关
                 ⇒ 同一文件在任何并发度下都拿到同一条私有库路径）
      ② 临时 ：`TMP`/`TEMP`/`TMPDIR` → `<worker 目录>/tmp_w<i>`
                （并发文件绝不同 TMP 根；`tempfile.mkdtemp()` 的落点因此天然分开）
      ③ 端口 ：本仓 HTTP 用例一律 `ThreadingHTTPServer(("127.0.0.1", 0))` 绑 0 取临时端口，
                按进程天然隔离；另按 worker 注入 `FW_WORKER_ID` / `FW_WORKER_PORT_BASE`
                （将来出现写死端口的用例时用它分流）
  · **串行槽**：硬编码共享状态的文件不进并行池，先单独串行跑 —— 自动识别
    `os.environ["GWEN_GAME_DB"] = …test_game_data.db` 这类**直接赋值**（`setdefault` 不算：
    它尊重外层 env，会被 ① 覆盖 ⇒ `test_engine_neutral_fallback.py` 可并行）。
  · 汇总输出按**文件路径排序**（稳定）；失败清单与串行同构（同一份红集）。
  · worker 目录名带 pid + 时间戳 ⇒ 并发跑两份全量互不覆盖；跑完即删。

退出码：0 = 全绿；1 = 有失败（含超时/崩溃）。
说明：框架仓是独立仓库，自带测试 —— 不依赖任何外部游戏包（奥兰迪亚侧
      `scripts/run_all_tests.py` 会先跑本脚本，见其注释）。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable
TIMEOUT = int(os.environ.get("FW_TEST_TIMEOUT", "600"))

SKIP = {"run_all.py", "conftest.py"}

# 串行槽：硬编码共享状态（不认外层 env，无法用私有库隔离）的文件，与并行主体错开先跑。
# 引擎仓当前为空集；留作显式登记位（口径与游戏仓 `scripts/run_all_tests.py::SERIAL_SLOT` 同）。
SERIAL_SLOT: set[str] = set()

# 自动识别「直接赋值共享库」的测试文件（忽略注释行），命中自动进串行槽。
_SHARED_DB_RE = re.compile(
    r'os\.environ\[["\']GWEN_GAME_DB["\']\]\s*=\s*[^\n]*test_game_data\.db')


def discover():
    files = sorted(f for f in os.listdir(HERE)
                   if f.startswith("test_") and f.endswith(".py") and f not in SKIP)
    paths = [os.path.join(HERE, f) for f in files]
    smoke = os.path.join(ROOT, "examples", "minimal-game", "tests", "test_smoke.py")
    if os.path.exists(smoke):
        paths.append(smoke)
    return paths


def parse_args(argv):
    """(--serial, fail_fast, jobs, ) —— `--jobs=N` / `--jobs N` 两种写法都收。"""
    serial = "--serial" in argv
    fail_fast = "--fail-fast" in argv
    jobs = None
    i = 0
    while i < len(argv):
        a = argv[i]
        try:
            if a.startswith("--jobs="):
                jobs = int(a.split("=", 1)[1])
            elif a == "--jobs" and i + 1 < len(argv):
                i += 1
                jobs = int(argv[i])
        except ValueError:
            raise SystemExit(f"--jobs 需要一个整数：{a!r}")
        i += 1
    if jobs is not None and jobs < 1:
        raise SystemExit(f"--jobs 必须 >= 1（给了 {jobs}）")
    if serial and jobs is not None and jobs != 1:
        print(f"注意：--serial 与 --jobs={jobs} 同时给出 ⇒ 以 --serial 为准（纯串行）", flush=True)
    if jobs is None:
        # 缺省：按核数自适应 4~16（与游戏仓 scripts/run_all_tests.py 同款）；--serial 即 1
        jobs = 1 if serial else max(4, min(16, os.cpu_count() or 8))
    return serial, fail_fast, jobs


def _collect_serial_and_parallel(paths):
    """返回 (串行槽文件, 并行文件)。渲染/静态门禁类文件照常并行 —— 它们只读。"""
    serial, parallel = [], []
    for p in paths:
        name = os.path.basename(p)
        if name in SERIAL_SLOT:
            serial.append(p)
            continue
        if os.path.dirname(p) == HERE:  # 只对 tests/ 下的文件做「硬编码共享库」探测
            try:
                with open(p, encoding="utf-8") as fh:
                    code_lines = [ln for ln in fh.read().splitlines()
                                  if not ln.lstrip().startswith("#")]
                if _SHARED_DB_RE.search("\n".join(code_lines)):
                    serial.append(p)
                    continue
            except OSError:
                pass
        parallel.append(p)
    return serial, parallel


def _rel(path):
    return os.path.relpath(path, ROOT).replace("\\", "/")


def _run_one(path, env):
    """跑一个测试文件 → (ok, out, dt)。out 仅失败时用于打印尾部。"""
    ts = time.time()
    try:
        pr = subprocess.run([PY, path], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", env=env,
                            timeout=TIMEOUT, cwd=os.path.dirname(path))
        ok, out = pr.returncode == 0, (pr.stdout or "") + (pr.stderr or "")
    except subprocess.TimeoutExpired:
        ok, out = False, f"TIMEOUT after {TIMEOUT}s"
    return ok, out, time.time() - ts


def _report(rel, ok, out, dt):
    print(f"{'✅' if ok else '❌'} {rel} ({dt:.1f}s)", flush=True)
    if not ok:
        print("\n".join(out.strip().splitlines()[-30:]), flush=True)
        print("-" * 56, flush=True)


def _summary(results, t0):
    """汇总：计数行逐字沿用旧实现；失败清单**按文件路径排序**（稳定，与串行同构）。"""
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'=' * 56}\n文件: {len(results)} 个，通过 {passed}，失败 {len(results) - passed}，"
          f"总耗时 {time.time() - t0:.0f}s")
    failed = sorted(rel for rel, ok in results if not ok)
    if failed:
        print("失败文件:")
        for rel in failed:
            print(f"  ❌ {rel}")
    return 1 if passed != len(results) else 0


def _run_serial(paths, fail_fast):
    """纯串行 —— `--serial` 的逐字行为（env 与旧实现完全一致，无 worker 目录、无隔离注入）。"""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    t0 = time.time()
    results = []
    for p in paths:
        rel = _rel(p)
        ok, out, dt = _run_one(p, env)
        results.append((rel, ok))
        _report(rel, ok, out, dt)
        if fail_fast and not ok:
            break
    return _summary(results, t0)


def _run_parallel(serial_files, parallel_files, jobs, fail_fast):
    base_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    worker_dir = os.path.join(
        tempfile.gettempdir(),
        f"fw_run_all_workers_{os.getpid()}_{int(time.time())}")
    results = []
    t0 = time.time()
    fail_seen = False
    executor = None
    try:
        # 1) 串行槽（硬编码共享库的文件；保持旧行为先跑，不进并行池）
        for p in serial_files:
            rel = _rel(p)
            ok, out, dt = _run_one(p, base_env)
            results.append((rel, ok))
            _report(rel, ok, out, dt)
            if not ok:
                fail_seen = True
                if fail_fast:
                    break

        # 2) 并行主体（每个文件一条私有库 + 私有 TMP，互不污染）
        if parallel_files and not (fail_fast and fail_seen):
            for i in range(len(parallel_files)):
                os.makedirs(os.path.join(worker_dir, f"tmp_w{i}"), exist_ok=True)

            def make_env(i):
                tmp = os.path.join(worker_dir, f"tmp_w{i}")
                return {**base_env,
                        "GWEN_GAME_DB": os.path.join(worker_dir, f"test_game_data_w{i}.db"),
                        "TMP": tmp, "TEMP": tmp, "TMPDIR": tmp,
                        "FW_WORKER_ID": str(i),
                        "FW_WORKER_PORT_BASE": str(21000 + i * 10)}

            n = max(1, min(jobs, len(parallel_files)))
            executor = ThreadPoolExecutor(max_workers=n)
            queue = iter(enumerate(parallel_files))
            pending = {}

            def submit_next():
                if fail_fast and fail_seen:
                    return False
                try:
                    i, p = next(queue)
                except StopIteration:
                    return False
                pending[executor.submit(_run_one, p, make_env(i))] = p
                return True

            for _ in range(n):
                if not submit_next():
                    break
            while pending:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for fut in done:
                    p = pending.pop(fut)
                    rel = _rel(p)
                    ok, out, dt = fut.result()
                    results.append((rel, ok))
                    _report(rel, ok, out, dt)
                    if not ok:
                        fail_seen = True
                    submit_next()
    finally:
        if executor is not None:
            executor.shutdown(wait=True)
        shutil.rmtree(worker_dir, ignore_errors=True)
    return _summary(results, t0)


def main(argv):
    paths = discover()
    if "--list" in argv:
        for p in paths:
            print("  ", os.path.relpath(p, ROOT).replace("\\", "/"))
        return 0

    serial_mode, fail_fast, jobs = parse_args(argv)
    if serial_mode:
        return _run_serial(paths, fail_fast)

    serial_files, parallel_files = _collect_serial_and_parallel(paths)
    if serial_files:
        print(f"串行槽 {len(serial_files)} 个（硬编码共享状态）: "
              f"{', '.join(_rel(p) for p in serial_files)}", flush=True)
    return _run_parallel(serial_files, parallel_files, jobs, fail_fast)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
