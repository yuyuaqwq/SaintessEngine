# -*- coding: utf-8 -*-
"""门禁：RecordsSet 的 `__getattr__` 契约守卫（下划线面 / 未初始化态回落）。

跑法：python tests/test_records_getattr_contract.py（退出码 0 = 全绿）。

为什么要有这一支（批次 4 · 验证侧缺口 · 生产码零改动）
--------------------------------------------------------
`records/__init__.py` 的 `RecordsSet.__getattr__` 里有**三条** fail-closed 守卫：
  · 未声明的域抛 AttributeError（已由 test_records_shape.py:154 钉住）
  · **下划线开头不接管**
  · **`_spec` 缺失时回落空声明**
后两条**全仓零断言**。立项依据不是推断，是**逐条变异实跑**（不是照抄清单）：
把每条守卫换成静默形态后跑全部 11 支 records 相关门禁，只有第一条会红，
后两条 **11/11 全绿**。守卫是 `__getattr__` 契约本体（它决定「属性找不到」时抛什么），
不是装饰品。

钉住的判据
----------
① 未初始化实例（`object.__new__`，copy/pickle 协议进行期态）：读任何面都抛
   **AttributeError**，不是 KeyError —— `__getattr__` 的契约就是 AttributeError。
   漏成 KeyError 会让 `hasattr()` 反过来把异常当「在不在」的探测通道
   （stdlib 的 copy 模块正是这么用的）。
② hasattr / getattr(·, 默认值) 在未初始化态不得被 KeyError 劫持。
③ copy / deepcopy 契约：结果都仍是 RecordsSet。
④ 合法实例面逐字不变（补判据不改行为）。
⑤ ★ 逐条归因（两条守卫缺一不可）：只拆 `_spec` 回落 ⇒ 未初始化态立刻漏 KeyError；
   只拆下划线守卫 ⇒ 未初始化态照旧 AttributeError（被前者兜住）= 单独拆**无害**。
⑥ ★ 反证有牙：两条换回旧静默形态后本门禁必须转红，且红因逐字指向 KeyError 泄漏。
   （只拆下划线守卫是**零行为变化**，所以反证必须两条一起拆，否则本门禁恒绿 = 无牙。）
"""
from __future__ import annotations

import copy
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if os.path.join(ROOT, "tests") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "tests"))

from saintess_engine.records import RecordsSet                    # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []

from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "PASS", "FAIL", "FAILURES")

SRC = os.path.join(ROOT, "saintess_engine", "records", "__init__.py")
GATE = os.path.join(ROOT, "tests", os.path.basename(__file__))
#: 反证自举守卫用的环境变量（本门禁被自己起成子进程跑时置 1 → 子进程跳过反证组）
NO_MUT = "AFIX4_NO_MUTATION"

# 两条待钉守卫的**逐字原文**（反证段按同一对原文替换 ⇒ 变异只可能改这两处）
M2_OLD = '        if domain.startswith("_"):\n            raise AttributeError(domain)\n'
M2_NEW = ""                                                    # 拆掉下划线守卫
M3_OLD = '        spec = obj.get("_spec") or {}\n'
M3_NEW = '        spec = obj["_spec"]\n'                         # 回落被拆 = 裸 KeyError


def _live():
    """正常实例（声明一个域；域文件不存在只让表 missing，不影响本组断言）。"""
    return RecordsSet(tempfile.mkdtemp(), {"alpha": {"key_type": int}})


def t1_uninitialized_is_attributeerror():
    print("\n[1] 未初始化态：任何面都抛 AttributeError（不是 KeyError）")
    raw = object.__new__(RecordsSet)
    for label, fn in (("_spec", lambda: raw._spec),
                      ("_tables", lambda: raw._tables),
                      ("未声明域 alpha", lambda: raw.alpha),
                      ("未声明域 beta", lambda: raw.beta)):
        try:
            got = fn()
            check("★ 未初始化态读 %s 必须抛" % label, False, "没抛，返回 %r" % (got,))
        except AttributeError:
            check("★ 未初始化态读 %s → AttributeError" % label, True)
        except KeyError as exc:
            check("★ 未初始化态读 %s → AttributeError" % label, False,
                  "漏成 KeyError: %s（__getattr__ 契约破了）" % (exc,))


def t2_hasattr_probe_channel():
    print("\n[2] hasattr / getattr(·, 默认) 不得被 KeyError 反向劫持")
    raw = object.__new__(RecordsSet)
    try:
        v = hasattr(raw, "alpha")
        check("★ hasattr(未初始化态, 域) → False（不是 KeyError 崩）", v is False, repr(v))
    except Exception as exc:                                      # noqa: BLE001
        check("★ hasattr(未初始化态, 域) → False（不是 KeyError 崩）", False,
              "%s: %s" % (type(exc).__name__, exc))
    try:
        v = getattr(raw, "alpha", "DEFAULT")
        check("★ getattr(未初始化态, 域, 默认) → 返回默认", v == "DEFAULT", repr(v))
    except Exception as exc:                                      # noqa: BLE001
        check("★ getattr(未初始化态, 域, 默认) → 返回默认", False,
              "%s: %s" % (type(exc).__name__, exc))


def t3_copy_contract():
    print("\n[3] copy / deepcopy 契约（stdlib 正是用 hasattr 探测 __getattr__ 的面）")
    for label, fn in (("copy.copy", copy.copy), ("copy.deepcopy", copy.deepcopy)):
        try:
            got = fn(_live())
            check("★ %s(RecordsSet) → 仍是 RecordsSet" % label,
                  isinstance(got, RecordsSet), type(got).__name__)
        except Exception as exc:                                  # noqa: BLE001
            check("★ %s(RecordsSet) → 仍是 RecordsSet" % label, False,
                  "%s: %s" % (type(exc).__name__, exc))


def t4_live_surface_unchanged():
    print("\n[4] 合法实例面逐字不变（补判据不改行为）")
    rs = _live()
    check("_spec 面 == 声明", rs._spec == {"alpha": {"key_type": int}}, repr(rs._spec))
    check("_tables 面初始为空（懒建未触发）", rs._tables == {}, repr(rs._tables))
    try:
        rs.beta
        check("★ 未声明域抛 AttributeError（不建空壳）", False, "没抛")
    except AttributeError as exc:
        check("★ 未声明域抛 AttributeError（不建空壳）", "未声明的域" in str(exc), str(exc)[:80])
    check("repr 仍报声明域", repr(rs) == "RecordsSet(domains=['alpha'])", repr(rs))
    check("missing_domains 面不受影响", rs.missing_domains() == ["alpha"],
          repr(rs.missing_domains()))


def t5_mutation_teeth():
    print("\n[5] ★ 反证：两条守卫换回旧静默形态 → 本门禁必须转红")
    with io.open(SRC, encoding="utf-8", newline="") as f:
        orig = f.read()
    n2, n3 = orig.count(M2_OLD), orig.count(M3_OLD)
    if n2 != 1 or n3 != 1:
        check("★ 反证前提：两条守卫原文各恰好出现一次", False,
              "M2 x%d / M3 x%d（源码已变，先核形态再决定反证怎么做）" % (n2, n3))
        return
    mutant = orig.replace(M2_OLD, M2_NEW, 1).replace(M3_OLD, M3_NEW, 1)

    # 探针单独落盘再起子进程：避免把脚本嵌进字符串时的转义地狱（实测连踩 4 次）。
    import subprocess
    probe = os.path.join(tempfile.gettempdir(), "_afix4_getattr_mutant.py")
    with io.open(probe, "w", encoding="utf-8", newline="\n") as f:
        f.write(_PROBE_SRC)
    try:
        env = dict(os.environ, **{NO_MUT: "1"})   # ★ 关键：子进程跳过反证组，防 A起B/B起A
        p = subprocess.run([sys.executable, probe], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600, env=env)
        out = p.stdout or ""
        vals = {}
        for line in out.splitlines():
            k, sep, v = line.partition("=")
            if sep and k.strip() in ("RC0", "RC1", "ORIG_GREEN", "MUTANT_RED", "MUTANT_HITS"):
                vals[k.strip()] = v.strip()
        check("★ 反证：基线（未变异）本门禁自跑必须全绿", vals.get("ORIG_GREEN") == "True",
              "rc0=%s / out=%s" % (vals.get("RC0"), out[-200:]))
        check("★ 反证：两条换回旧形态后本门禁必须转红（判据有牙）",
              vals.get("MUTANT_RED") == "True",
              "rc1=%s（=恒绿 ⇒ 判据无牙）/ out=%s" % (vals.get("RC1"), out[-200:]))
        check("★ 反证：转红处逐字指向 KeyError 泄漏",
              vals.get("MUTANT_HITS", "0") != "0" and "KeyError" in out,
              "hits=%s" % vals.get("MUTANT_HITS"))
    finally:
        with io.open(SRC, encoding="utf-8", newline="") as f:
            check("★ 反证收尾：源码已原样还原（字节一致）", f.read() == orig, "源码没还原！")
        try:
            os.remove(probe)
        except OSError:
            pass


# 探针脚本文本：起子进程跑本门禁两次（原形 / 变异形），把结果打成可解析的键值行。
# 路径与变异体在下面用 %s 占位，运行时替换 —— 免得把大段文本塞进 format。
_PROBE_SRC = r'''
import io, os, subprocess, sys

SRC = __SRC__
GATE = __GATE__
ROOT = __ROOT__
M2_OLD = __M2_OLD__
M2_NEW = __M2_NEW__
M3_OLD = __M3_OLD__
M3_NEW = __M3_NEW__
ORIG = io.open(SRC, encoding='utf-8', newline='').read()
MUT = ORIG.replace(M2_OLD, M2_NEW, 1).replace(M3_OLD, M3_NEW, 1)
assert MUT != ORIG, 'mutation was a no-op'


def run(src):
    io.open(SRC, 'w', encoding='utf-8', newline='').write(src)
    p = subprocess.run([sys.executable, GATE], cwd=__ROOT__, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=300)
    return p.returncode, (p.stdout or '') + (p.stderr or '')


try:
    rc0, _ = run(ORIG)
    rc1, out1 = run(MUT)
finally:
    io.open(SRC, 'w', encoding='utf-8', newline='').write(ORIG)

print('RC0=%d' % rc0)
print('ORIG_GREEN=%s' % (rc0 == 0))
print('RC1=%d' % rc1)
print('MUTANT_RED=%s' % (rc1 != 0))
hits = [l for l in out1.splitlines() if l.startswith('\u274c') or 'KeyError' in l]
print('MUTANT_HITS=%d' % len(hits))
for l in hits[:6]:
    print('HIT: ' + l)
'''

_PROBE_SRC = (_PROBE_SRC
              .replace("__SRC__", repr(SRC))
              .replace("__GATE__", repr(GATE))
              .replace("__ROOT__", repr(ROOT))
              .replace("__M2_OLD__", repr(M2_OLD))
              .replace("__M2_NEW__", repr(M2_NEW))
              .replace("__M3_OLD__", repr(M3_OLD))
              .replace("__M3_NEW__", repr(M3_NEW)))


def main() -> int:
    print("== 门禁：RecordsSet.__getattr__ 契约（下划线面 / 未初始化态回落）==")
    t1_uninitialized_is_attributeerror()
    t2_hasattr_probe_channel()
    t3_copy_contract()
    t4_live_surface_unchanged()
    # ★ 反证自举守卫：本门禁在反证段被自己起成子进程跑，子进程必须跳过本组，
    #   否则 A 起 B、B 起 A 无限递归（第一次跑就卡死 180s 超时，实测）。
    if os.environ.get(NO_MUT) == "1":
        print("\n[5] 反证组：子进程模式跳过（由外层负责验）")
    else:
        t5_mutation_teeth()
    print("-" * 56)
    print("通过 %d · 失败 %d" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
