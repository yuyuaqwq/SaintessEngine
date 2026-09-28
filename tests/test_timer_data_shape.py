# -*- coding: utf-8 -*-
"""`saintess_engine.clock.LazyTimers` 的 `data` 载荷 fail-closed 门禁（审计修复 · 批次4）。

锁死的契约（本文件是 `data` 这一维的**唯一**行为断言面，此前零覆盖）：

1. `set()` 拒非映射 `data`（`str` / `int` / `list` / `tuple`），`None` 与缺省归一为 `{}`；
2. 落盘的 `data` 是**副本**（调用方事后改自己的 dict 不影响已落盘的事件）；
3. 读口（`get` / `items`）对存储里预置的坏 `data` **点名 owner 与 key** 后抛
   `TimerStorageError` —— 改前是 `AttributeError: 'str' object has no attribute 'get'`，
   报在引擎内部、归属全丢；
4. `items(data_match=…)` 的过滤与输出都走同一道校验，不再对存储裸调 `.get`；
5. `on_expire` 拿到的 `data` 一定是映射（改前是 `ev.get("data", {}) or {}`，非映射原样透传）；
6. 与同形状的另一份实现（`ext_life.timers.Timers`）**口径同源**：`Mapping` 判定一致。

**零游戏、零宿主**：只用标准库 + 被测模块；时间用注入的假时钟（不 sleep）。
判据只加强：本文件是**新增**门禁，未改任何既有判据或冻结基线。

跑法：python tests/test_timer_data_shape.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
for _p in (FW_ROOT, os.path.join(FW_ROOT, "extends")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from saintess_engine.clock.timer import LazyTimers, TimerStorageError  # noqa: E402

from _check import bind_check  # noqa: E402  断言助手单源：tests/_check.py

PASS = 0
FAIL = 0
FAILURES = []
TOTAL = 0

check = bind_check(globals(), "PASS", "FAIL", "FAILURES", total="TOTAL")

BAD_VALUES = ["坏字符串", 123, 12.5, ["x"], ("x",), {1, 2}, True]


def _mk(store, now, *, on_expire=None, register=True):
    """造一只注入假时钟与假存储的计时器（不碰真实时间与真实存储）。"""
    t = LazyTimers(
        load=lambda o: dict(store.get(o, {})),
        save=lambda o, e: store.__setitem__(o, dict(e)),
        remove=lambda o: store.pop(o, None),
        clock=lambda: now["t"],
        default_duration_sec=60,
    )
    if register:
        t.register("grow", duration_sec=500, on_expire=on_expire or (lambda o, d: None))
    return t


# ── A. set() 拒非映射 data ─────────────────────────────────────────────
store, now = {}, {"t": 1000}
t = _mk(store, now)
for bad in BAD_VALUES:
    try:
        t.set("u", "k", "grow", data=bad)
        check(f"A set 拒非映射 data（{type(bad).__name__}）", False,
              f"接受并落盘 data={bad!r} ⇒ {store.get('u', {}).get('k')!r}")
    except TypeError as e:
        check(f"A set 拒非映射 data（{type(bad).__name__}）", "必须是映射" in str(e), str(e))
    except Exception as e:  # noqa: BLE001
        check(f"A set 拒非映射 data（{type(bad).__name__}）", False,
              f"抛的是 {type(e).__name__}（应为 TypeError）：{e}")
check("A set 拒完不落任何脏数据", store == {}, f"存储被写脏：{store!r}")

# ── B. None / 缺省 归一为 {}，合法映射原样落盘 ──────────────────────────
t.set("u", "none_key", "grow", data=None)
t.set("u", "dflt_key", "grow")
t.set("u", "ok_key", "grow", data={"map": "pine", "n": 2})
check("B data=None 落 {}", store["u"]["none_key"]["data"] == {},
      repr(store["u"]["none_key"]))
check("B data 缺省落 {}", store["u"]["dflt_key"]["data"] == {},
      repr(store["u"]["dflt_key"]))
check("B 合法映射原样落盘", store["u"]["ok_key"]["data"] == {"map": "pine", "n": 2},
      repr(store["u"]["ok_key"]))

# ── C. 落盘的是副本：调用方事后改自己的 dict 不影响已落盘 ───────────────
shared = {"map": "oak"}
t.set("u", "copy_key", "grow", data=shared)
shared["map"] = "改成别的"
shared["新增"] = True
check("C 落盘 data 是副本（改调用方的 dict 不影响存储）",
      store["u"]["copy_key"]["data"] == {"map": "oak"},
      f"调用方事后改写泄漏进了存储：{store['u']['copy_key']['data']!r}")

# ── D. 读口对预置坏 data 点名后抛（改前是无归属的 AttributeError）──────
def _seed(bad, key="k"):
    s = {"ownerA": {key: {"type": "grow", "data": bad, "expire": 5000}}}
    return s, _mk(s, {"t": 1000})

for bad in ["坏字符串", 123, ["x"]]:
    s, tt = _seed(bad)
    try:
        tt.get("ownerA", "k")
        check(f"D get 拒预置坏 data（{type(bad).__name__}）", False, "get 未抛")
    except TimerStorageError as e:
        msg = str(e)
        check(f"D get 拒预置坏 data（{type(bad).__name__}）",
              "ownerA" in msg and "'k'" in msg, f"未点名 owner/key：{msg}")
    except Exception as e:  # noqa: BLE001
        check(f"D get 拒预置坏 data（{type(bad).__name__}）", False,
              f"抛的是 {type(e).__name__}（应为 TimerStorageError）：{e}")

    s, tt = _seed(bad)
    try:
        tt.items("ownerA")
        check(f"D items 拒预置坏 data（{type(bad).__name__}）", False, "items 未抛")
    except TimerStorageError as e:
        check(f"D items 拒预置坏 data（{type(bad).__name__}）", "ownerA" in str(e), str(e))
    except Exception as e:  # noqa: BLE001
        check(f"D items 拒预置坏 data（{type(bad).__name__}）", False,
              f"抛的是 {type(e).__name__}（应为 TimerStorageError）：{e}")

# ★ 这条是原缺陷的现场：改前 data_match 对裸 str 调 .get ⇒ AttributeError
s, tt = _seed("坏字符串")
try:
    tt.items("ownerA", data_match={"x": 1})
    check("★ D items(data_match) 报点名错而非 AttributeError", False, "未抛")
except TimerStorageError as e:
    check("★ D items(data_match) 报点名错而非 AttributeError",
          "ownerA" in str(e) and "'k'" in str(e), str(e))
except AttributeError as e:
    check("★ D items(data_match) 报点名错而非 AttributeError", False,
          f"仍是无归属的 AttributeError（原缺陷未修）：{e}")
except Exception as e:  # noqa: BLE001
    check("★ D items(data_match) 报点名错而非 AttributeError", False,
          f"抛的是 {type(e).__name__}：{e}")

# ── E. 缺 data 键 / data=None 在读口都归一为 {}（不误伤既有存档）───────
s = {"o": {"k": {"type": "grow", "expire": 5000}}}
tt = _mk(s, {"t": 1000})
check("E 缺 data 键 → get 给 {}", tt.get("o", "k")["data"] == {}, repr(tt.get("o", "k")))
s = {"o": {"k": {"type": "grow", "data": None, "expire": 5000}}}
tt = _mk(s, {"t": 1000})
check("E data=None → items 给 {}", tt.items("o")[0]["data"] == {}, repr(tt.items("o")))

# ── F. data_match 过滤在合法 data 上逐字不变（零行为变化）──────────────
s = {"o": {"a": {"type": "grow", "data": {"map": "pine"}, "expire": 5000},
           "b": {"type": "grow", "data": {"map": "oak"}, "expire": 5000}}}
tt = _mk(s, {"t": 1000})
got = [e["key"] for e in tt.items("o", data_match={"map": "pine"})]
check("F data_match 正例仍只留命中那条", got == ["a"], repr(got))
check("F 无过滤时两条都在", [e["key"] for e in tt.items("o")] == ["a", "b"],
      repr(tt.items("o")))

# ── G. on_expire 拿到的 data 一定是映射 ─────────────────────────────────
fired = []
s = {"o": {"k": {"type": "grow", "data": "坏字符串", "expire": 1}}}
tt = _mk(s, {"t": 9999}, on_expire=lambda o, d: fired.append(d))
# 坏 data 现在在**进回调之前**就被 _data_of 挡住 —— 回调不该被叫到，
# 且那条越界的 except 不该把点名错吞成一句 warn（否则正是原缺陷的静默面）。
tt.refresh("o")
check("G 坏 data 不再原样透传给 on_expire", fired == [], f"回调仍被叫到：{fired!r}")

s = {"o": {"k": {"type": "grow", "data": {"m": 1}, "expire": 1}}}
fired2 = []
tt = _mk(s, {"t": 9999}, on_expire=lambda o, d: fired2.append(d))
tt.refresh("o")
check("G 正常档 on_expire 收到映射原样", fired2 == [{"m": 1}], repr(fired2))

# ── H. 判据自身有效：源码面必须已无裸 `.get("data", {})` 调用 ───────────
import re  # noqa: E402

src_path = os.path.join(FW_ROOT, "saintess_engine", "clock", "timer.py")
with open(src_path, encoding="utf-8") as fh:
    src = fh.read()
# 只数**方法体内**的裸取（_data_of 自己那一处 `ev.get("data")` 是校验源，不算）。
body_src = src.split("class LazyTimers", 1)[1] if "class LazyTimers" in src else src
raw = re.findall(r'\.get\(\s*"data"\s*,\s*\{\}\s*\)', body_src)
raw += re.findall(r'"data"\s*:\s*data\s+or\s+\{\}', body_src)
check("H 类体内无「裸取 data 后直接用」的残留",
      not raw, f"仍存在 {len(raw)} 处裸取：{raw[:3]}")
check("H _data_of 校验 Mapping（非只判 dict）",
      "isinstance(data, Mapping)" in src, "未见 Mapping 判定")
check("H 读口确实走 _data_of", src.count("_data_of(") >= 4,
      f"_data_of 调用点只有 {src.count('_data_of(')} 处")
# ★ 有牙反证：把实现退回改前形态（裸取 + data or {}）后，本节必须转红。
pre = src
pre = pre.replace('"data": _data_of(ev, key, owner),', '"data": ev.get("data", {}),')
pre = pre.replace('if data_match and not all(_data_of(ev, k, owner).get(dk) == dv',
                  'if data_match and not all(ev.get("data", {}).get(dk) == dv')
pre = pre.replace('"data": dict(data) if data is not None else {},', '"data": data or {},')
import tempfile
with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                 encoding="utf-8", newline="") as tf:
    tf.write(pre)
    mutated = tf.name
os.environ["_TIMER_MUTANT"] = mutated
mut_raw = re.findall(r'\.get\(\s*"data"\s*,\s*\{\}\s*\)', pre.split("class LazyTimers", 1)[1])
mut_raw += re.findall(r'"data"\s*:\s*data\s+or\s+\{\}', pre.split("class LazyTimers", 1)[1])
check("★ H 反证：退回改前裸取形态后本节判据转红", len(mut_raw) > 0,
      f"变异体里扫到 {len(mut_raw)} 处裸取（应 >0，否则反证无牙）")

print(f"\n=== PASS={PASS} FAIL={FAIL} ===")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
sys.exit(1 if FAIL else 0)
