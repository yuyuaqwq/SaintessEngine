# -*- coding: utf-8 -*-
"""`saintess_engine.clock.LazyTimers` 的 `expire` 维度 fail-closed 门禁（审计修复 · 批次4）。

锁死的契约（本文件是 `expire` 这一维的**唯一**行为断言面，此前零覆盖 ——
变异实跑确认：把 `_expire_of` 的三条 `raise` 整块换成 `pass`，
`test_timers` / `test_events_clock` / `test_timer_data_shape` **三支全绿、零转红**）：

1. **缺 `expire` 键** → `TimerStorageError` 点名 owner 与 key；
2. **`expire` 是非整数**（`str` / `None` / `bool` / `list` / `dict`）→ 同款点名；
3. **记录本身不是映射** → 同款点名；
4. `float` 与 `bool` 的**精确口径**：`float` 收下并 `int()` 取整、`True` **拒绝**
   （`bool` 是 `int` 的子类，不加这一条判据就形同虚设）；
5. ★ **不许静默当已过期**：坏 `expire` 时事件**必须留在表里**、**不得触发 `on_expire`**
   —— 这是模块 docstring 自陈的后果（`.get("expire", 0)` ⇒ `now >= 0` 恒真 ⇒
   一行坏数据被当「已过期」静默物理删除并触发 `on_expire`，作废会话/平移结算
   这类副作用在无人察觉时发生）。本节是这条契约的**行为证据**，不是源码 grep。
6. ★ **三条读路径都走同一道校验**（`get` / `items` / `refresh`）——「过期即不可见」
   的一致性铁律不得在任何一条路径上被绕过。
7. 与同形状另一份实现（`ext_life.timers.Timers`）**口径同源**：异常类同一份
   （`is` 相等，非同名不同类），否则 `except TimerStorageError` 会漏捕另一层的错。

**零游戏、零宿主**：只用标准库 + 被测模块；时间用注入的假时钟（不 sleep）。
判据只加强：本文件是**新增**门禁，未改任何既有判据或冻结基线。

跑法：python tests/test_timer_expire_shape.py
"""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
for _p in (FW_ROOT, os.path.join(FW_ROOT, "extends")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from saintess_engine.clock.timer import LazyTimers, TimerStorageError  # noqa: E402
from saintess_engine.clock import timer as timer_mod                     # noqa: E402
import ext_life.timers as life_timers                                   # noqa: E402

from _check import bind_check  # noqa: E402  断言助手单源：tests/_check.py

PASS = 0
FAIL = 0
FAILURES = []
TOTAL = 0

check = bind_check(globals(), "PASS", "FAIL", "FAILURES", total="TOTAL")

NOW = {"t": 1000}


def _mk(store, *, on_expire=None, register=True, dur=500):
    fired = []
    t = LazyTimers(
        load=lambda o: dict(store.get(o, {})),
        save=lambda o, e: store.__setitem__(o, dict(e)),
        remove=lambda o: store.pop(o, None),
        clock=lambda: NOW["t"],
        default_duration_sec=60,
    )
    if register:
        t.register("grow", duration_sec=dur,
                   on_expire=(lambda o, d: fired.append((o, d)))
                   if on_expire is None else on_expire)
    return t, fired


def _seed(store, owner="U1", key="k1", drop=(), **over):
    """在存储里预置一条**坏记录**（绕过 set()，模拟存量坏数据）。

    `drop` = 要**整个删掉**的键（存活的坏档常是「缺键」而不是「键值是坏值」，
    两者触发的是同一条守卫但走的分支不同，必须分别造）。
    """
    ev = {"type": "grow", "data": {}, "expire": 2000}
    ev.update(over)
    for k in drop:
        ev.pop(k, None)
    store.setdefault(owner, {})[key] = ev
    return store[owner][key]


# ── A. 三种坏 expire 形态：点名 owner 与 key 后抛 ───────────────────────
BAD_RECORDS = [
    ("缺 expire 键", {"drop": ("expire",)}),
    ("缺 expire 键 + data 也在", {"drop": ("expire", "data")}),
    ("expire 是字符串", {"expire": "2000"}),
    ("expire 是 None", {"expire": None}),
    ("expire 是 bool True", {"expire": True}),
    ("expire 是 list", {"expire": [2000]}),
    ("expire 是 dict", {"expire": {"t": 2000}}),
]
for label, over in BAD_RECORDS:
    for path in ("get", "items", "refresh"):
        store = {}
        _seed(store, **over)
        t, fired = _mk(store)
        try:
            if path == "get":
                t.get("U1", "k1")
            elif path == "items":
                t.items("U1")
            else:
                t.refresh("U1")
            got = "没抛"
        except TimerStorageError as exc:
            got = str(exc)
        except Exception as exc:                       # noqa: BLE001
            got = "抛了非 TimerStorageError：%s: %s" % (type(exc).__name__, exc)
        ok = got != "没抛" and "U1" in got and "k1" in got and "TimerStorageError" not in got
        check("A %s · %s() 点名 owner/key 抛 TimerStorageError" % (label, path), ok,
              "实得：%r" % (got[:110],))

# ── B. 记录本身不是映射 ────────────────────────────────────────────────
for bad in ("坏字符串", 123, ["x"], ("x",), {1, 2}, 0.5):
    store = {"U1": {"k1": bad}}
    t, fired = _mk(store)
    try:
        t.get("U1", "k1")
        got = "没抛"
    except TimerStorageError as exc:
        got = str(exc)
    except Exception as exc:                           # noqa: BLE001
        got = "抛了非 TimerStorageError：%s: %s" % (type(exc).__name__, exc)
    check("B 记录不是映射（%s）→ 点名抛" % type(bad).__name__,
          got != "没抛" and "U1" in got and "k1" in got, "实得：%r" % (got[:110],))

# ── C. 合法面：float 收下取整、int 原样、坏值不被顺手改写 ───────────────
for label, value, want in [("int", 2000, 2000), ("float 整秒", 2000.0, 2000),
                           ("float 带小数", 2000.9, 2000), ("负数（已过期）", 10, 10)]:
    store = {}
    _seed(store, expire=value)
    t, fired = _mk(store)
    ev = t.get("U1", "k1")
    if value == 10:
        check("C 合法面 %s：过期即清除并回调（不是抛错）" % label,
              ev is None and len(fired) == 1, "ev=%r fired=%r" % (ev, fired))
    else:
        check("C 合法面 %s → expire=%d（int 收下取整）" % (label, want),
              ev is not None and ev.get("expire") == want, "ev=%r" % (ev,))

# ── D. ★ 不许静默当已过期：坏 expire 时事件留在表里、回调不触发 ─────────
for label, over in [("缺 expire 键", {"drop": ("expire",)}),
                    ("expire 是字符串", {"expire": "2000"}),
                    ("expire 是 None", {"expire": None})]:
    store = {}
    _seed(store, **over)
    t, fired = _mk(store)
    for path in ("get", "items", "refresh"):
        try:
            getattr(t, path)("U1") if path != "get" else t.get("U1", "k1")
        except TimerStorageError:
            pass
        alive = "k1" in store.get("U1", {})
        check("D ★ 坏 expire（%s）经 %s()：事件**留在表里**（未被静默当已过期删除）"
              % (label, path), alive,
              "删掉了 —— 这正是 docstring 自陈的「零回调无声蒸发」后果")
        check("D ★ 坏 expire（%s）经 %s()：on_expire **零触发**" % (label, path),
              len(fired) == 0, "回调触发了 %d 次" % len(fired))
        fired.clear()

# ── E. 与另一份实现（ext_life.timers）异常类同源 ────────────────────────
check("E 异常类跨层同源（is 相等，非同名不同类）",
      life_timers.TimerStorageError is TimerStorageError,
      "is 为 False ⇒ except TimerStorageError 会漏捕另一层的错")
check("E 另一份实现也用同一异常类抛（不另立同名类）",
      life_timers.TimerStorageError is timer_mod.TimerStorageError, "两者不同源")

# ── F. 反证：三条守卫换成静默形态后，本节判据必须转红 ──────────────────
src = timer_mod.__file__
with open(src, encoding="utf-8", newline="") as f:
    source = f.read()
exp_fn = source.split("def _expire_of(", 1)[1].split("\ndef ", 1)[0]
guards = len(re.findall(r"raise TimerStorageError\(", exp_fn))
check("F 源码侧：_expire_of 仍是三条守卫（防门禁被空转）", guards == 3,
      "扫到 %d 条 raise TimerStorageError（应为 3）" % guards)
# 变异：把三条 raise 整块换成 pass（同缩进），_expire_of 退化成"取不到就当 0"
mut = exp_fn
for m in list(re.finditer(r"^([ \t]*)raise TimerStorageError\(", mut, re.M))[::-1]:
    st = m.start()
    i = m.end() - 1                      # 指向 '('
    depth = 0
    for j in range(i, len(mut)):
        if mut[j] == "(":
            depth += 1
        elif mut[j] == ")":
            depth -= 1
            if depth == 0:
                break
    mut = mut[:st] + m.group(1) + "pass\n    return int(ev.get(\"expire\", 0) or 0)\n" + mut[j + 1:]
check("F ★ 反证：三条守卫换静默后 _expire_of 不再抛（反证有牙）",
      "raise TimerStorageError(" not in mut,
      "变异体里仍有 %d 条 raise（应 0）" % mut.count("raise TimerStorageError("))
check("F ★ 反证：静默形态复现改前的 `.get(\"expire\", 0)` → now>=0 恒真",
      'int(ev.get("expire", 0) or 0)' in mut, "静默替身未落到改前形态")
check("F 源码侧：_data_of 仍在（本文件不动它，别被误伤）",
      "def _data_of(" in source, "_data_of 没了")

print("\n=== PASS=%d FAIL=%d ===" % (PASS, FAIL))
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
sys.exit(1 if FAIL else 0)
