# -*- coding: utf-8 -*-
"""领域事件总线 + 懒计时器骨架的契约测试（`saintess_engine.events` / `saintess_engine.clock`）。

锁死的契约：
1. EventBus：注册序 = 执行序 = 输出行序；段落空行策略；未知事件「注册严 / 发布宽」；
   订阅方异常容忍（可关）；订阅管理与事件声明
2. LazyTimers：懒过期（读/列表/刷新三条路径都清理）；**三条删除路径都触发 on_expire**
   （防读路径绕过带副作用的清理）；主动删除不触发；时长优先级；存储回调正确性

**零游戏、零宿主**：只用标准库；时间用注入的假时钟（不 sleep）。

跑法：python tests/test_kit_events_clock.py
"""
import copy
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, FW_ROOT)

from saintess_engine.clock import LazyTimers  # noqa: E402
from saintess_engine.events import EventBus   # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "PASS", "FAIL", "FAILURES")


# ================================================================ EventBus
print("== 1. EventBus：注册序与输出 ==")
bus = EventBus(("order_paid", "order_refunded"))
check("事件声明序", bus.events == ("order_paid", "order_refunded"), bus.events)

order = []


def sub_a(ctx):
    order.append("a")
    return [f"A:{ctx['id']}"]


def sub_b(ctx):
    order.append("b")
    return ["B1", "B2"]


def sub_empty(ctx):
    order.append("empty")
    return None


bus.on("order_paid", sub_a)
bus.on("order_paid", sub_b)
bus.on("order_paid", sub_empty)
lines = bus.fire("order_paid", {"id": 7})
check("注册序执行", order == ["a", "b", "empty"], order)
check("行序 + 空段跳过 + 段间空行", lines == ["A:7", "", "B1", "B2"], lines)
check("ctx 补 event 字段", bus.fire("order_paid", {}) is not None)
ctx2 = {"id": 1}
bus.fire("order_paid", ctx2)
check("返回即 ctx[sink_key]（同一对象）", ctx2["lines"][0] == "A:1", ctx2.get("lines"))
check("ctx[event] = 事件名", ctx2["event"] == "order_paid", ctx2.get("event"))

bus2 = EventBus(("x",))
bus2.on("x", lambda c: ["1-1"], blank_line=False)
bus2.on("x", lambda c: ["2-1"], blank_line=False)
check("blank_line=False → 无空行", bus2.fire("x", {}) == ["1-1", "2-1"], bus2.fire("x", {}))

print("== 2. EventBus：未知事件策略 ==")
try:
    bus.on("no_such_event", sub_a)
    reg_strict = False
except ValueError:
    reg_strict = True
check("register 未知事件 → ValueError（防拼写）", reg_strict)

wrong = bus.fire("no_such_event", {"lines": ["已有"]})
check("fire 未知事件 → 不抛、返回收集器", wrong == ["已有"], wrong)

lenient = EventBus(("y",), strict_register=False)
lenient.on("brand_new", lambda c: ["ok"])
check("strict_register=False → 自动声明并注册",
      "brand_new" in lenient.events and lenient.fire("brand_new", {}) == ["ok"], lenient.events)

print("== 3. EventBus：异常容忍 ==")


def boom(ctx):
    raise RuntimeError("订阅方炸了")


bus3 = EventBus(("e",), logger=__import__("logging").getLogger("t"))
bus3.on("e", boom)
bus3.on("e", lambda c: ["继续了"])
out = bus3.fire("e", {})
check("默认容忍：坏的跳过、好的继续", out == ["继续了"], out)

bus4 = EventBus(("e",), tolerant_fire=False)
bus4.on("e", boom)
try:
    bus4.fire("e", {})
    strict_fire = False
except RuntimeError:
    strict_fire = True
check("tolerant_fire=False → 异常上抛", strict_fire)

print("== 4. EventBus：订阅管理 ==")
bus5 = EventBus(("k",))
cb = lambda c: ["x"]
bus5.on("k", cb)
bus5.on("k", sub_empty)
check("subscribers 列出注册序", len(bus5.subscribers("k")) == 2)
check("unsubscribe 移除 1 条", bus5.unsubscribe("k", cb) == 1)
check("unsubscribe 后不再执行", bus5.fire("k", {}) == [], bus5.fire("k", {}))
bus5.clear()
check("clear 清空", bus5.subscribers("k") == ())
check("has()", bus5.has("k") and not bus5.has("nope"))

print("== 4b. EventBus：str 返回 = 一行（审计 L2178） ==")

# 订阅方返回 str 时，早先 `lines.extend(seg)` 把一句话拆成逐字单行（玩家可见：
# 一句提示变成 5 行单字）。四种返回形态逐个钉住。
bus6 = EventBus(("s",))
bus6.on("s", lambda c: "已收到订单")
check("str 返回 = 一行（不逐字拆）", bus6.fire("s", {}) == ["已收到订单"], bus6.fire("s", {}))

bus7 = EventBus(("t",))
bus7.on("t", lambda c: ("行A", "行B"))
check("tuple 返回逐行保留", bus7.fire("t", {}) == ["行A", "行B"], bus7.fire("t", {}))

bus8 = EventBus(("n",))
bus8.on("n", lambda c: None)
check("None 返回 = 无输出", bus8.fire("n", {}) == [], bus8.fire("n", {}))

bus9 = EventBus(("m",))
bus9.on("m", lambda c: "")
bus9.on("m", lambda c: [])
check("空串 / 空列表 = 无输出", bus9.fire("m", {}) == [], bus9.fire("m", {}))

bus10 = EventBus(("x",))
bus10.on("x", lambda c: "整句", blank_line=False)
bus10.on("x", lambda c: ["第二条"], blank_line=False)
check("str 与 list 混排保持整句",
      bus10.fire("x", {}) == ["整句", "第二条"], bus10.fire("x", {}))


# ================================================================ LazyTimers
print("== 5. LazyTimers：懒过期与回调 ==")

# 类首行必须是 docstring：任何一条赋值抬到第一行都会把它挤成一句哑字面量。
# 改前实测 `LazyTimers.__doc__ is None`（整段 15 行类文档从未挂在任何地方，
# help() 与 IDE 都读不到、零报错）；与 `ext_life.timers.Timers` 是同一形态的缺陷。
_lt_doc = LazyTimers.__doc__
check("★ 类文档真的存在（非 None）", bool(_lt_doc) and len(_lt_doc) > 100, repr(_lt_doc))
check("★ 类文档首行就是类自述（不是兜底赋值之后的碎片）",
      bool(_lt_doc) and _lt_doc.lstrip().startswith("主体维度的懒计时器"),
      repr(_lt_doc[:40]) if _lt_doc else "None")
check("★ _warn_logger 兜底仍在（移位不得带走它）", LazyTimers._warn_logger is not None)


class FakeClock:
    def __init__(self, t=1000):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class MemStore:
    """模拟真实存储的序列化语义（深拷贝），并记录 remove 调用。"""

    def __init__(self):
        self.data = {}
        self.removed = []

    def load(self, owner):
        return copy.deepcopy(self.data.get(owner, {}))

    def save(self, owner, events):
        self.data[owner] = copy.deepcopy(events)

    def remove(self, owner):
        self.removed.append(owner)
        self.data.pop(owner, None)


clock = FakeClock(1000)
store = MemStore()
expired_log = []
timers = LazyTimers(load=store.load, save=store.save, remove=store.remove,
                    clock=clock, default_duration_sec=30,
                    logger=__import__("logging").getLogger("t"))
timers.register("encounter", duration_sec=600,
                on_expire=lambda owner, data: expired_log.append((owner, data)))
timers.register("flash")          # 无时长 → 用默认

exp = timers.set("u1", "spot:trader", "encounter", data={"map": "oak"})
check("set 返回过期戳（注册时长优先）", exp == 1000 + 600, exp)
ev = timers.get("u1", "spot:trader")
check("未过期 → 返回 type/data/expire/remain",
      ev and ev["type"] == "encounter" and ev["data"] == {"map": "oak"} and ev["remain"] == 600, ev)

exp2 = timers.set("u1", "spot:flash", "flash")
check("无注册时长 → 用默认（30s）", exp2 == 1030, exp2)

clock.advance(601)
ev = timers.get("u1", "spot:trader")
check("过期 → get 返回 None", ev is None, ev)
check("★ 过期清除触发 on_expire（读路径不绕过）",
      expired_log == [("u1", {"map": "oak"})], expired_log)
check("过期项已物理删除", "spot:trader" not in store.data["u1"], store.data.get("u1"))

print("== 6. LazyTimers：items / refresh / remove ==")
clock = FakeClock(5000)
store = MemStore()
log2 = []
timers = LazyTimers(load=store.load, save=store.save, remove=store.remove,
                    clock=clock, logger=__import__("logging").getLogger("t"))
timers.register("a", duration_sec=100, on_expire=lambda o, d: log2.append(("a", o)))
timers.register("b", duration_sec=100, on_expire=lambda o, d: log2.append(("b", o)))
timers.set("u2", "k1", "a", data={"map": "oak"})
timers.set("u2", "k2", "b", data={"map": "oak"})
timers.set("u2", "k3", "a", data={"map": "pine"})

got = timers.items("u2", type_key="a")
check("items 按时长键过滤", {g["key"] for g in got} == {"k1", "k3"}, got)
got = timers.items("u2", data_match={"map": "pine"})
check("items 按 data 子集过滤", [g["key"] for g in got] == ["k3"], got)

clock.advance(101)
got = timers.items("u2")
check("items 惰性清除过期（返回空）", got == [], got)
check("★ items 过期清除也触发 on_expire（全部 3 条）",
      sorted(log2) == [("a", "u2"), ("a", "u2"), ("b", "u2")], log2)
check("事件清空 → 调 remove(owner) 删整条记录", store.removed == ["u2"], store.removed)

# remove（主动）不触发回调
clock = FakeClock(9000)
store = MemStore()
log3 = []
timers = LazyTimers(load=store.load, save=store.save, remove=store.remove,
                    clock=clock, logger=__import__("logging").getLogger("t"))
timers.register("a", duration_sec=100, on_expire=lambda o, d: log3.append(o))
timers.set("u3", "k", "a")
check("remove 主动删除返回 True", timers.remove("u3", "k") is True)
check("★ 主动删除不触发 on_expire", log3 == [], log3)
check("remove 不存在 → False", timers.remove("u3", "k") is False)

print("== 7. LazyTimers：refresh 与时长优先级 ==")
clock = FakeClock(100)
store = MemStore()
log4 = []
timers = LazyTimers(load=store.load, save=store.save, remove=store.remove,
                    clock=clock, default_duration_sec=10,
                    logger=__import__("logging").getLogger("t"))
timers.register("t1", duration_sec=50, on_expire=lambda o, d: log4.append(o))
timers.set("u4", "a", "t1")
timers.set("u4", "b", "t1", duration_sec=1000)      # 参数覆盖
timers.set("u4", "c", "unregistered")               # 未注册类型 → 默认
check("set 时长优先级（参数 > 注册 > 默认）",
      store.data["u4"]["b"]["expire"] == 1100 and store.data["u4"]["c"]["expire"] == 110,
      store.data["u4"])
clock.advance(60)          # clock=160：a(expire150) 与 c(默认10s→expire110) 过期，b(1100) 未过期
n = timers.refresh("u4")
check("refresh 清理过期并返回条数", n == 2, n)
# a 有 on_expire 回调 → 触发一次；c 用的类型未注册（无回调）→ 不触发
check("★ refresh 触发有回调者的 on_expire（无回调的静默删除）",
      log4 == ["u4"], log4)
check("refresh 只清过期的（b 还在）", [g["key"] for g in timers.items("u4")] == ["b"])
check("refresh 无过期 → 0", timers.refresh("u4") == 0)

print("== 8. LazyTimers：回调异常容忍 ==")


def bad_cb(owner, data):
    raise RuntimeError("回调炸了")


clock = FakeClock(0)
store = MemStore()
timers = LazyTimers(load=store.load, save=store.save, remove=store.remove,
                    clock=clock, logger=__import__("logging").getLogger("t"))
timers.register("t", duration_sec=1, on_expire=bad_cb)
timers.set("u5", "k", "t")
clock.advance(2)
try:
    res = timers.get("u5", "k")
    tolerant_ok = res is None
except Exception as exc:                                    # noqa: BLE001
    tolerant_ok = False
check("on_expire 抛异常不影响清理", tolerant_ok)

print("== 8b. LazyTimers：坏时长 fail-closed（审计 L1348） ==")

# L1353 重复实现的后果之一：`LazyTimers` 与 `ext_life.timers.Timers` 是**同一形状的两份实现**，
# 但只有后者校验类型标签 / 事件 key。原来这里直接放行 ⇒ `set(o,k,123)` 把
# `{"type": 123}` 原样落盘（只有一条 WARNING），拼错类型名的后果到**到期时**才现形：
# `_fire_expire` 查不到回调 ⇒ 事件被物理删除、零回调。收口到与 ext_life 逐字相同的判据。

# 负时长 / bool / 0 原本被 `max(1, int(dur))` 一律压成 1 秒（行为与意图相反且不报错），
# 字符串被 `int()` 悄悄收下。改为与 `ext_life.timers._duration_of` 同一判据：点名报错。
clock = FakeClock(1000)
store = MemStore()
timers = LazyTimers(load=store.load, save=store.save, remove=store.remove,
                    clock=clock, default_duration_sec=30,
                    logger=__import__("logging").getLogger("t"))
timers.register("a")

for _bad, _exc in ((-500, ValueError), (0, ValueError), (True, TypeError), ("600", TypeError)):
    try:
        timers.set("u9", "k", "a", duration_sec=_bad)
        check(f"set duration_sec={_bad!r} 报错", False, "静默接受")
    except _exc as exc:
        check(f"set duration_sec={_bad!r} fail-closed（{_exc.__name__}）", True)
    except Exception as exc:                                   # noqa: BLE001
        check(f"set duration_sec={_bad!r} fail-closed", False, f"{type(exc).__name__}: {exc}")
check("坏时长未被写入事件表", "k" not in store.data.get("u9", {}), store.data.get("u9"))

try:
    LazyTimers(load=store.load, save=store.save, remove=store.remove,
               default_duration_sec="60")
    check("default_duration_sec 非整数 → 装配即报错", False, "静默接受")
except TypeError:
    check("default_duration_sec 非整数 → 装配即报错", True)
except Exception as exc:                                       # noqa: BLE001
    check("default_duration_sec 非整数 → 装配即报错", False, f"{type(exc).__name__}: {exc}")

try:
    timers.register("b", duration_sec=-1)
    check("register 非法 duration_sec → 注册即报错", False, "静默接受")
except ValueError:
    check("register 非法 duration_sec → 注册即报错", True)
except Exception as exc:                                       # noqa: BLE001
    check("register 非法 duration_sec → 注册即报错", False, f"{type(exc).__name__}: {exc}")

# 时长优先级与合法值行为逐字未变
exp = timers.set("u9", "ok", "a", duration_sec=600)
check("合法 duration_sec 行为未变", exp == 1600, exp)
check("合法 set 落盘 expire", store.data["u9"]["ok"]["expire"] == 1600, store.data["u9"])

print("== 8c. LazyTimers：类型标签 / 事件 key fail-closed（审计 L1353） ==")

clock = FakeClock(1000)
store = MemStore()
timers = LazyTimers(load=store.load, save=store.save, remove=store.remove,
                    clock=clock, default_duration_sec=30,
                    logger=__import__("logging").getLogger("t"))
timers.register("ok", duration_sec=10)

for bad in (123, None, "  ", b"ok", 0):
    try:
        timers.set("v1", "k", bad)
        check("★ set 非字符串/空 type_key 拒绝（%r）" % (bad,), False, "落盘了：%r" % bad)
    except (TypeError, ValueError) as exc:
        check("★ set 拒绝 type_key=%r" % (bad,), True, "")
    check("   拒绝后零落盘（type_key=%r）" % (bad,), "v1" not in store.data, store.data)

for bad in (123, "", "  ", b"k"):
    try:
        timers.set("v2", bad, "ok")
        check("★ set 拒绝事件 key=%r" % (bad,), False, "落盘了：%r" % bad)
    except (TypeError, ValueError):
        check("★ set 拒绝事件 key=%r" % (bad,), True, "")
    check("   拒绝后零落盘（key=%r）" % (bad,), "v2" not in store.data, store.data)

try:
    timers.register("")
    check("★ register 空 type_key 拒绝", False, "注册成功")
except ValueError:
    check("★ register 空 type_key 拒绝", True, "")
try:
    timers.register(123)
    check("★ register 非字符串 type_key 拒绝", False, "注册成功")
except TypeError:
    check("★ register 非字符串 type_key 拒绝", True, "")

# 合法值行为逐字未变（不许把判据写成「什么都拒」）
v = timers.set("v3", "good", "ok")
check("合法 set 落盘 expire 不变", v == 1010 and store.data["v3"]["good"]["expire"] == 1010,
      store.data.get("v3"))
check("合法 register/set 后 registered_types 仍可读", "ok" in timers.registered_types,
      timers.registered_types)

print("== 9. 零游戏 / 零宿主依赖 ==")
banned = []
for sub in ("events", "clock"):
    for dirpath, dirs, fs in os.walk(os.path.join(FW_ROOT, "saintess_engine", sub)):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in fs:
            if not f.endswith(".py"):
                continue
            for line in open(os.path.join(dirpath, f), encoding="utf-8").read().splitlines():
                s = line.strip()
                if not s.startswith(("import ", "from ")):
                    continue
                parts = s.split()
                mod = parts[1].split(".")[0] if len(parts) > 1 else ""
                if mod in ("game", "astrbot"):
                    banned.append(f"{f}: {s}")
check("events/clock 不 import 游戏包 / 宿主", not banned, banned)

print(f"\n=== 结果 PASS={PASS} FAIL={FAIL} ===")
if FAILURES:
    print("失败项：" + ", ".join(FAILURES))
sys.exit(1 if FAIL else 0)
