#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""有牙反证：逐条拆 declarative.py 的 8 条守卫 → 跑本门禁 → 数红。

跑法：python tests/_conditions_declar_mutant.py     退出码 0 = 8 条全有牙。
★ 这个文件是 tests/test_conditions_declar_failclosed.py 的**反证驱动器**，
  不是门禁本体（`run_all.py` 只收 `test_*.py`，本文件名不匹配，不会被当门禁跑）。
★ 必须带 `AFIX4_MUTANT_CHILD` 才允许跑 —— 防自举递归
  （子进程跑门禁 → 门禁又起子进程 → 无限递归；上一轮踩过 180s 超时且变异态留在真仓）。
★ 子进程必须 `cwd=ROOT` —— 否则从 temp 反算 ROOT、读的是另一棵树 ⇒ 变异态也全绿。
"""
import io
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TGT = os.path.join(ROOT, "saintess_engine", "conditions", "declarative.py")
GATE = os.path.join(ROOT, "tests", "test_conditions_declar_failclosed.py")

#: (守卫名, 原文整块, 替身整块) —— 替身**必须同缩进**，否则 IndentationError。
GUARDS = [
    ("L118 步必须是字典",
     '    if not isinstance(step, Mapping):\n'
     '        raise SpecError("步必须是字典，收到 %s" % type(step).__name__)\n',
     '    if not isinstance(step, Mapping):\n        pass\n'),
    ("L120 步的键不对",
     '    if not frozenset(step) <= _KEYS_STEP:\n'
     '        raise SpecError("步的键不对：%r" % (sorted(step),))\n',
     '    if not frozenset(step) <= _KEYS_STEP:\n        pass\n'),
    ("L125 key 必须是非空字符串",
     '    if not isinstance(key, str) or not key:\n'
     '        raise SpecError("步的 key 必须是非空字符串：%r" % (key,))\n',
     '    if not isinstance(key, str) or not key:\n        pass\n'),
    ("L184 步链必须是非空列表",
     '    if not isinstance(steps, list) or not steps:\n'
     '        raise SpecError("field 的步链必须是非空列表：%r" % (steps,))\n',
     '    if not isinstance(steps, list) or not steps:\n        pass\n'),
    ("L202 field 节点键不对",
     '        if frozenset(spec) != _KEYS_FIELD:\n'
     '            raise SpecError("field 节点的键不对：%r" % (sorted(spec),))\n',
     '        if not frozenset(spec) == _KEYS_FIELD:\n            pass\n'),
    ("L230 布尔节点键不对",
     '        if frozenset(spec) != _KEYS_BOOL:\n'
     '            raise SpecError("布尔节点的键不对：%r" % (sorted(spec),))\n',
     '        if not frozenset(spec) == _KEYS_BOOL:\n            pass\n'),
    ("L236 一元节点键不对",
     '        if frozenset(spec) != _KEYS_ARG:\n'
     '            raise SpecError("%s 节点的键不对：%r" % (op, sorted(spec)))\n',
     '        if not frozenset(spec) == _KEYS_ARG:\n            pass\n'),
    ("L273 args 必须是非空列表",
     '        if not isinstance(args, list) or not args:\n'
     '            raise SpecError("args 必须是非空列表：%r" % (args,))\n',
     '        if not isinstance(args, list) or not args:\n            pass\n'),
]


def _shadow_tree(dst_root):
    """把整棵仓**复制**到 dst_root（浅层：只复制会被 import 的 saintess_engine 包 + tests），
    在副本里改守卫 ⇒ **真仓零写入**。

    ★ 为什么必须这样做（2026-09-29 实踩）：
      第一版反证直接改真仓，子进程超时后**进程没死**（subprocess 只抛 TimeoutExpired，
      不 kill）⇒ 28 个递归子进程继续轮流往真仓写变异态，`git checkout` 刚还原就被
      下一个子进程覆盖 ⇒ 差点把生产码的守卫真的删掉。
      「带 AFIX4_MUTANT_CHILD 标记」只防**递归**，防不住**残留进程**。
    ⇒ 正确形态：变异只发生在一次性副本上，真仓从头到尾不参与。
    """
    import shutil
    shutil.copytree(os.path.join(ROOT, "saintess_engine"),
                    os.path.join(dst_root, "saintess_engine"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    os.makedirs(os.path.join(dst_root, "tests"), exist_ok=True)
    for name in ("_check.py", "test_conditions_declar_failclosed.py"):
        shutil.copyfile(os.path.join(ROOT, "tests", name),
                        os.path.join(dst_root, "tests", name))
    return dst_root


def main():
    if os.environ.get("AFIX4_MUTANT_CHILD"):
        raise SystemExit(3)                    # 防自举递归（副本口径下已不会发生，留作双保险）
    orig = io.open(TGT, encoding="utf-8", newline="").read()
    env = dict(os.environ)
    env["GWEN_FRAMEWORK_DIR"] = ROOT
    env["GWEN_HOST_DIR"] = r"C:/Users/yuyu/qqbot/data/plugins/dragonfall"
    env.pop("SAINTESS_EXTENDS", None)
    env["AFIX4_MUTANT_CHILD"] = "1"
    red = []
    import shutil
    import tempfile
    base = tempfile.mkdtemp(prefix="afix4_declar_")
    try:
        for name, old, new in GUARDS:
            if old not in orig:
                print("ANCHOR-MISS %s" % name)
                red.append(name + "(anchor)")
                continue
            shadow = os.path.join(base, name.split()[0])
            if os.path.isdir(shadow):
                shutil.rmtree(shadow)
            _shadow_tree(shadow)
            # 在副本里施加变异
            io.open(os.path.join(shadow, "saintess_engine", "conditions", "declarative.py"),
                    "w", encoding="utf-8", newline="").write(orig.replace(old, new, 1))
            penv = dict(env)
            penv["GWEN_FRAMEWORK_DIR"] = shadow      # ★ 门禁从 shadow 起步 ⇒ 读的是副本
            p = subprocess.run([sys.executable,
                                os.path.join(shadow, "tests",
                                             "test_conditions_declar_failclosed.py")],
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               cwd=shadow, env=penv, timeout=180)
            state = "RED" if p.returncode != 0 else "green"
            print("MUT %-30s %s" % (name, state))
            if p.returncode != 0:
                red.append(name)
            else:
                print("   ", ((p.stdout or "") + (p.stderr or ""))[-300:])
    finally:
        shutil.rmtree(base, ignore_errors=True)
    # 真仓从头到尾没被写过 —— 逐字核对
    same = io.open(TGT, encoding="utf-8", newline="").read() == orig
    print("REAL-REPO-UNTOUCHED %s" % ("OK" if same else "**CHANGED**"))
    print("TEETH %d/%d" % (len(red), len(GUARDS)))
    return 0 if (len(red) == len(GUARDS) and same) else 1


if __name__ == "__main__":
    raise SystemExit(main())
