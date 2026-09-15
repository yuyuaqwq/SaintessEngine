#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""timers 门禁：倒计时事件形状 —— 注册 / 挂载 / 三条过期路径 / 删除 / 懒计时 / 零知识。

跑法：python tests/test_timers.py
退出码：0 = 全绿；1 = 有失败。

三处专门钉住的地方（都是「改了就静默变行为」的）：
  ① **过期三条路径都回调、且只回调一次**：`get` / `due` / `refresh` 任一清掉过期项时
     `on_expire` 必须恰好触发一次（实现先清除并落盘、再回调 ⇒ 回调里重入读也不会二次触发）
  ② **`remove(fire=False)` 不回调**：主动结束不是过期，绝不触发清理副作用；
     `fire=True` 才回调，且仍只一次
  ③ **零知识 + 无后台定时器**：源码字符串常量里不得出现任何内容侧取值；
     不得 import 线程 / 异步 / 系统时间 —— 「时间」只来自注入的 `clock`
"""
import ast
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import saintess_engine.timers as TIMERS_MOD                                       # noqa: E402
from saintess_engine.timers import TimerStorageError, Timers                      # noqa: E402

MODULE_PATH = os.path.join(ROOT, "saintess_engine", "timers", "__init__.py")

passed = failed = 0
DETAIL = []


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        DETAIL.append(f"{name} {detail}")
        print(f"  ❌ {name} {detail}")


def raises(exc, fn, *a, **kw):
    """跑 fn → (是否抛该异常, 异常或返回值)。"""
    try:
        return False, fn(*a, **kw)
    except exc as e:
        return True, e


class Clock:
    """可推进的假时钟（引擎不读系统时间 —— 时刻全由外部给）。"""

    def __init__(self, t=0):
        self.t = int(t)

    def __call__(self):
        return self.t

    def set(self, t):
        self.t = int(t)
        return self.t


class Log:
    """收 WARNING 的假 logger（引擎「留痕」的落点）。"""

    def __init__(self):
        self.records = []

    def warning(self, msg, *args):
        self.records.append(msg % args if args else msg)


def mk(store, clock, **kw):
    return Timers(store, clock, **kw)


# ---------------------------------------------------------------- 1 注册 / 挂载
def t1_register_set():
    print("\n[1] 注册与挂载：时长优先级 / 顶替刷新 / 未注册留痕")
    st, ck, log = {}, Clock(1000), Log()
    tm = mk(st, ck, default_duration=60, log=log)

    check("未注册类型也能挂（取兜底时长 60）", tm.set("o1", "a", "k1") == 1060)
    check("★ 未注册类型留痕（WARNING 点名该类型）",
          any("k1" in m for m in log.records), str(log.records))

    tm.register("k1", duration=10)
    check("注册后类型时长生效", tm.set("o1", "b", "k1") == 1010)
    check("显式 duration 压过类型时长", tm.set("o1", "c", "k1", duration=3) == 1003)
    check("存储布局 = {事件 key: {type,data,expire}}（引擎不塞对象）",
          st["o1"]["c"] == {"type": "k1", "data": {}, "expire": 1003}, str(st))

    ck.set(1005)
    first = tm.set("o1", "b", "k1")                                   # 顶替刷新
    check("★ 同 key 重复 set = 顶替刷新（新 expire）", first == 1015, f"got {first}")
    ck.set(1006)
    second = tm.set("o1", "b", "k1", data={"n": 1})
    check("★ 顶替后 expire 再刷新", second == 1016, f"got {second}")
    check("★ 顶替后该格只有一条（不产生第二条）",
          set(st["o1"]) == {"a", "b", "c"}, str(sorted(st["o1"])))
    check("顶替换了 data", st["o1"]["b"] == {"type": "k1", "data": {"n": 1}, "expire": 1016},
          str(st["o1"]["b"]))
    check("★ 写路径不越权清理别的过期格（c 已过期但仍在，等读路径）",
          "c" in st["o1"])
    check("读路径一到就把 c 清掉（due 只留在列的）",
          sorted(e["key"] for e in tm.due("o1")) == ["a", "b"]
          and "c" not in st["o1"])

    tm.register("k1", duration=7)
    check("重复 register = 覆盖（新时长生效）", tm.set("o1", "d", "k1") == 1013)
    tm.register("k2")
    check("registered_types 是注册序", tm.registered_types == ("k1", "k2"),
          str(tm.registered_types))

    check("register 空 type_key → ValueError", raises(ValueError, tm.register, "")[0])
    check("register duration=0 → ValueError",
          raises(ValueError, tm.register, "zz", duration=0)[0])
    check("register duration 非整数 → TypeError",
          raises(TypeError, tm.register, "zz", duration=1.5)[0])
    check("on_expire 非可调用 → TypeError",
          raises(TypeError, tm.register, "zz", on_expire=1)[0])
    check("k2 没声明时长 → 落回兜底 60", tm.set("o1", "e", "k2") == 1066)


# ---------------------------------------------------------------- 2 三条过期路径
def t2_expire_paths():
    print("\n[2] ★ 过期三条路径（get / due / refresh）：都回调且只回调一次")

    # ---- get 路径
    fires = []
    st, ck = {}, Clock(0)
    tm = mk(st, ck)
    tm.register("k1", duration=10, on_expire=lambda o, k, d: fires.append((o, k, d)))
    tm.set("o1", "a", "k1", data={"n": 1})
    ck.set(9)
    check("未到点 get 拿到视图（remain=1）",
          tm.get("o1", "a") == {"type": "k1", "data": {"n": 1}, "expire": 10, "remain": 1},
          str(tm.get("o1", "a")))
    check("未到点不回调", fires == [])
    ck.set(10)
    check("★ 到点 get → None（过期即不可见）", tm.get("o1", "a") is None)
    check("★ get 路径回调一次，带 owner / key / data",
          fires == [("o1", "a", {"n": 1})], str(fires))
    check("★ 再 get 不二次触发（已清除）",
          tm.get("o1", "a") is None and len(fires) == 1, str(fires))
    check("过期项已物理清除（表空 → 键删掉，不留空壳）", "o1" not in st, str(st))

    # ---- due 路径
    fires = []
    st, ck = {}, Clock(0)
    tm = mk(st, ck)
    tm.register("k1", duration=10, on_expire=lambda o, k, d: fires.append((o, k, d)))
    tm.set("o1", "a", "k1", duration=10)
    tm.set("o1", "b", "k1", duration=100)
    ck.set(50)
    live = tm.due("o1")
    check("★ due 只留在列的（过期项被清掉并回调）",
          [e["key"] for e in live] == ["b"] and fires == [("o1", "a", {})], str(fires))
    check("due 视图形状 {key, type, data, expire, remain}",
          live[0] == {"key": "b", "type": "k1", "data": {}, "expire": 100, "remain": 50},
          str(live))
    check("★ 再 due 不二次触发（a 已清）", len(tm.due("o1")) == 1 and len(fires) == 1, str(fires))
    ck.set(200)
    check("refresh 返回 None（规格签名）", tm.refresh("o1") is None)
    check("★ refresh 清理并回调一次（b 到点）",
          fires == [("o1", "a", {}), ("o1", "b", {})], str(fires))
    check("refresh 后表空且键删掉", "o1" not in st, str(st))
    tm.refresh("o1")
    check("★ 再 refresh 不重复回调", len(fires) == 2, str(fires))

    # ---- get 只管自己那一格
    fires = []
    st, ck = {}, Clock(0)
    tm = mk(st, ck)
    tm.register("k1", duration=10, on_expire=lambda o, k, d: fires.append(k))
    tm.set("o1", "a", "k1")
    tm.set("o1", "b", "k1")
    ck.set(10)
    tm.get("o1", "a")
    check("★ get 只处理自己那一格（b 仍过期在表里、未回调）",
          fires == ["a"] and "b" in st["o1"], f"{fires} {st}")
    tm.refresh("o1")
    check("后续 refresh 把 b 也清掉并回调（不重复 a）", fires == ["a", "b"], str(fires))

    # ---- 回调重入
    fires, reentrant = [], []
    st, ck = {}, Clock(0)
    tm = mk(st, ck)

    def _cb(o, k, d):
        fires.append(k)
        reentrant.append(tm.get(o, k))                 # 回调里回读同一 key

    tm.register("k1", duration=5, on_expire=_cb)
    tm.set("o1", "a", "k1")
    ck.set(5)
    tm.refresh("o1")
    check("★ 回调里再读同一 key → None（已先清除落盘）",
          reentrant == [None] and fires == ["a"], f"{reentrant} {fires}")
    check("★ 回调重入不引发二次回调", len(fires) == 1, str(fires))

    # ---- 回调抛错
    fires, log = [], Log()
    st, ck = {}, Clock(0)
    tm = mk(st, ck, log=log)

    def _boom(o, k, d):
        raise RuntimeError("内容侧 bug")

    tm.register("bad", duration=5, on_expire=_boom)
    tm.register("ok", duration=5, on_expire=lambda o, k, d: fires.append(k))
    tm.set("o1", "a", "bad")
    tm.set("o1", "b", "ok")
    ck.set(5)
    tm.refresh("o1")
    check("★ 一个回调抛错不阻断同批其余回调", fires == ["b"], str(fires))
    check("★ 回调失败留痕（WARNING 点名类型）",
          any("bad" in m for m in log.records), str(log.records))
    check("★ 抛错的那条也已清除，不会二次触发",
          tm.due("o1") == [] and len(log.records) == 1, f"{tm.due('o1')} {log.records}")


# ---------------------------------------------------------------- 3 remove
def t3_remove():
    print("\n[3] 主动删除：fire=False 缺省不回调（与既有语义一致）")
    fires = []
    st, ck = {}, Clock(0)
    tm = mk(st, ck)
    tm.register("k1", duration=10, on_expire=lambda o, k, d: fires.append((o, k, d)))

    tm.set("o1", "a", "k1", data={"n": 2})
    check("remove 返回 None（规格签名）", tm.remove("o1", "a") is None)
    check("★ remove(fire=False) 不触发回调", fires == [], str(fires))
    check("remove 后已清除", tm.get("o1", "a") is None and "o1" not in st, str(st))

    tm.set("o1", "b", "k1", data={"n": 3})
    tm.remove("o1", "b", fire=True)
    check("★ remove(fire=True) 触发一次（带 owner / key / data）",
          fires == [("o1", "b", {"n": 3})], str(fires))
    check("再 remove 同一 key → 无事发生（不抛、不回调）",
          tm.remove("o1", "b") is None and len(fires) == 1, str(fires))
    check("remove 不存在的 key 不新建空键", tm.remove("nobody", "zz") is None and st == {},
          str(st))
    check("fire 非布尔 → TypeError", raises(TypeError, tm.remove, "o1", "a", fire=1)[0])
    check("remove 空 key → ValueError", raises(ValueError, tm.remove, "o1", "")[0])


# ---------------------------------------------------------------- 4 懒计时
def t4_lazy_clock():
    print("\n[4] ★ 懒计时：不跑定时器；时间来自注入的 clock / 显式 now")
    fires = []
    st, ck = {}, Clock(0)
    tm = mk(st, ck, default_duration=10)
    tm.register("k1", duration=10, on_expire=lambda o, k, d: fires.append(k))
    tm.set("o1", "a", "k1")
    ck.set(999)                                        # 钟跨过 expire，但没人读
    check("★ 时钟跨过 expire 而无人调用 → 一个回调都没跑（无后台定时器）", fires == [])
    check("★ 过期项仍留在存储里（只有读路径才清）", "a" in st.get("o1", {}), str(st))
    check("未传 now → 用注入的 clock（此刻已过期）", tm.get("o1", "a") is None)
    check("读路径一到 → 回调发生", fires == ["a"], str(fires))

    fires2 = []
    st2, ck2 = {}, Clock(0)
    tm2 = mk(st2, ck2)
    tm2.register("k1", duration=100, on_expire=lambda o, k, d: fires2.append(k))
    tm2.set("o1", "a", "k1")                           # expire = 100
    check("显式 now 压过 clock（now=99 → 未过期）", tm2.get("o1", "a", now=99) is not None)
    check("★ 显式 now 压过 clock（now=100 → 过期并回调）",
          tm2.get("o1", "a", now=100) is None and fires2 == ["a"], str(fires2))
    tm2.set("o1", "b", "k1")
    check("due 的 now 注入同样生效（now=100 清掉）",
          tm2.due("o1", now=100) == [] and fires2 == ["a", "b"], str(fires2))
    check("now 非整数 → TypeError", raises(TypeError, tm2.due, "o1", now=1.5)[0])
    check("now=bool → TypeError（bool 不算整数）",
          raises(TypeError, tm2.due, "o1", now=True)[0])

    src = open(MODULE_PATH, encoding="utf-8").read()
    tree = ast.parse(src, filename=MODULE_PATH)
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods.add(node.module.split(".")[0])
    check("★ 不 import threading / asyncio / sched（无后台定时器）",
          not (mods & {"threading", "asyncio", "sched", "multiprocessing", "signal"}),
          str(sorted(mods)))
    check("★ 不 import time（不读系统时间，时间只从 clock 来）",
          "time" not in mods, str(sorted(mods)))
    check("无 sleep 调用", ".sleep(" not in src and "sleep(" not in src)
    check("★ 无后台定时器类/线程原语",
          not any(w in src for w in ("Thread(", "Timer(", "ensure_future", "call_later")),
          "源码出现线程/定时器原语")


# ---------------------------------------------------------------- 5 fail-closed
def t5_fail_closed():
    print("\n[5] fail-closed：坏数据 / 拿不到注入面 / 非法参数 → 报错点名，不静默")
    bad_cases = (
        ("{不是 JSON", "非 JSON 字符串"),
        ({"a": "not-a-mapping"}, "条目不是映射"),
        ({"a": {"type": "k1", "data": {}, "expire": 5.5}}, "expire 非整数"),
        ({"a": {"type": "", "data": {}, "expire": 5}}, "type 空"),
        ({"a": {"type": "k1", "data": 5, "expire": 5}}, "data 非映射"),
        ({"a": {"data": {}, "expire": 5}}, "type 缺失"),
        (["a"], "值不是映射"),
        ({1: {"type": "k1", "data": {}, "expire": 5}}, "键不是字符串"),
    )
    for raw, label in bad_cases:
        st = {"o1": raw}
        tm = mk(st, Clock(0))
        hit, exc = raises(TimerStorageError, tm.due, "o1")
        check(f"★ 坏数据（{label}）→ TimerStorageError", hit, f"got {exc!r}")

    st = {"o1": "{不是 JSON"}
    tm = mk(st, Clock(0))
    hit, exc = raises(TimerStorageError, tm.get, "o1", "a")
    check("★ get 遇到同一份坏数据也报错（每条读路径都不静默）", hit, f"got {exc!r}")
    check("★ 坏数据不被静默改写 / 清空", st["o1"] == "{不是 JSON", str(st))
    check("缺失键读成「没有事件」（不是坏数据）",
          tm.get("nobody", "a") is None and tm.due("nobody") == []
          and tm.refresh("nobody") is None)

    for bad, label in ((None, "store=None"), (object(), "store=裸对象")):
        hit, exc = raises(TypeError, lambda b=bad: mk(b, Clock(0)))
        check(f"★ {label} → TypeError（拿不到注入面就报错）", hit, f"got {exc!r}")
    check("★ clock 不可调用 → TypeError", raises(TypeError, lambda: mk({}, None))[0])
    check("★ 时钟给不出整数秒 → TypeError（装配即校验）",
          raises(TypeError, lambda: mk({}, lambda: 1.5))[0])
    check("★ 时钟返回 bool → TypeError（不让 True 蒙混）",
          raises(TypeError, lambda: mk({}, lambda: True))[0])
    check("★ default_duration=0 → ValueError",
          raises(ValueError, lambda: mk({}, Clock(0), default_duration=0))[0])
    check("★ default_duration 非整数 → TypeError",
          raises(TypeError, lambda: mk({}, Clock(0), default_duration=1.5))[0])
    check("★ key 不可调用 → TypeError", raises(TypeError, lambda: mk({}, Clock(0), key=1))[0])

    st2 = {}
    tm2 = mk(st2, Clock(0))
    check("set 空 key → ValueError", raises(ValueError, tm2.set, "o1", "", "k1")[0])
    check("set 非字符串 key → TypeError", raises(TypeError, tm2.set, "o1", 1, "k1")[0])
    check("set 空 type_key → ValueError", raises(ValueError, tm2.set, "o1", "a", "")[0])
    check("set type_key 非字符串 → TypeError", raises(TypeError, tm2.set, "o1", "a", 1)[0])
    check("set duration=0 → ValueError",
          raises(ValueError, tm2.set, "o1", "a", "k1", duration=0)[0])
    check("set duration=-3 → ValueError",
          raises(ValueError, tm2.set, "o1", "a", "k1", duration=-3)[0])
    check("set data 非映射 → TypeError（不静默丢载荷）",
          raises(TypeError, tm2.set, "o1", "a", "k1", data=[1])[0])
    check("get 空 key → ValueError", raises(ValueError, tm2.get, "o1", "")[0])
    check("★ 非法参数不写入任何东西", st2 == {}, str(st2))
    check("key(owner) 返回空串 → ValueError（拒绝无名存储位）",
          raises(ValueError, lambda: mk({}, Clock(0), key=lambda o: "").due("o1"))[0])
    check("key(owner) 返回非 str → TypeError",
          raises(TypeError, lambda: mk({}, Clock(0), key=lambda o: 7).due("o1"))[0])
    check("时钟不给整数 → 读路径也拦（get 同口径）",
          raises(TypeError, lambda: mk({}, lambda: "1").get("o1", "a"))[0])


# ---------------------------------------------------------------- 6 形状
def t6_shape():
    print("\n[6] 形状：视图隔离 / 主体隔离 / 自定义键 / 存储序 / JSON 往返")
    st, ck = {}, Clock(0)
    tm = mk(st, ck)
    tm.register("k1", duration=10)
    tm.set("o1", "a", "k1", data={"deep": {"v": 1}})
    v = tm.get("o1", "a")
    v["data"]["deep"]["v"] = 99
    check("★ get 视图是深拷贝（改它不影响存储）",
          tm.get("o1", "a")["data"] == {"deep": {"v": 1}}, str(st))
    check("每次读存储、不缓存对象（两次 get 不是同一个字典）",
          tm.get("o1", "a") is not tm.get("o1", "a"))
    payload = {"deep": {"v": 1}}
    tm.set("o1", "b", "k1", data=payload)
    payload["deep"]["v"] = 42
    check("★ set 存快照（外部改原对象不影响存储）",
          tm.get("o1", "b")["data"] == {"deep": {"v": 1}}, str(st))

    tm.set("o2", "a", "k1")
    check("不同主体各一套键", set(st) == {"o1", "o2"}, str(sorted(st)))
    tm.remove("o1", "a")
    check("动一个主体不影响另一个", tm.get("o2", "a") is not None)
    check("空主体：get None / due [] / refresh None",
          (tm.get("nobody", "x"), tm.due("nobody"), tm.refresh("nobody")) == (None, [], None))

    st2, ck2 = {}, Clock(0)
    tm2 = mk(st2, ck2, key=lambda o: f"timers.{o}")
    tm2.register("k1", duration=10)
    tm2.set("o1", "a", "k1")
    check("自定义 key 生效", set(st2) == {"timers.o1"}, str(sorted(st2)))
    tm2.set("o2", "a", "k1")
    check("键随主体分域", set(st2) == {"timers.o1", "timers.o2"}, str(sorted(st2)))

    st3, ck3 = {}, Clock(0)
    tm3 = mk(st3, ck3)
    tm3.register("k1", duration=100)
    for k in ("c", "a", "b"):
        tm3.set("o1", k, "k1")
    check("due 顺序 = 事件在表里的存放序（稳定）",
          [e["key"] for e in tm3.due("o1")] == ["c", "a", "b"],
          str([e["key"] for e in tm3.due("o1")]))
    tm3.set("o1", "a", "k1")
    check("顶替刷新不改位置", [e["key"] for e in tm3.due("o1")] == ["c", "a", "b"])

    st4, ck4 = {}, Clock(0)
    tm4 = mk(st4, ck4)
    tm4.register("k1", duration=10)
    tm4.set("o1", "a", "k1", data={"n": 1})
    check("存储里是纯数据（三字段，可 JSON 往返）",
          set(st4["o1"]["a"]) == {"type", "data", "expire"}, str(st4))
    st5 = {"o1": json.dumps(st4["o1"], ensure_ascii=False)}
    tm5 = mk(st5, Clock(0))
    check("JSON 存储面读得回来", tm5.due("o1")[0]["data"] == {"n": 1}, str(st5))
    ck4.set(10)
    tm4.refresh("o1")
    check("表清空 → 删键（不留空壳）", "o1" not in st4, str(st4))


# ---------------------------------------------------------------- 7 零知识
BANNED = ("orlandia", "dragonfall", "timed_events", "qq_id", "group_id",
          "player", "monster", "npc", "quest", "dungeon", "guild", "profession",
          "玩家", "怪物", "副本", "公会", "任务", "金币", "装备", "道具",
          "地图", "等级", "经验", "职业", "采集")


def t7_zero_knowledge():
    print("\n[7] 零知识：源码字符串常量里不得出现内容侧取值 / 具体游戏词汇")
    bad, n = [], 0
    for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "saintess_engine", "timers")):
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            n += 1
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=path)
            # 跳过**文档串**：文档要能打比方解释形状；判据针对代码里写死的取值
            docs = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                     ast.AsyncFunctionDef)):
                    d = ast.get_docstring(node, clean=False)
                    if d is not None:
                        docs.add(d)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if node.value in docs:
                        continue
                    low = node.value.lower()
                    for b in BANNED:
                        if (b in node.value) if not b.isascii() else (b in low):
                            bad.append(f"{rel}:{node.lineno}:{b!r}:{node.value[:40]!r}")
    check("扫到 timers/ 源文件（≥1）", n >= 1, f"n={n}")
    check("★ 代码常量里无内容侧取值 / 游戏词汇", not bad, str(bad[:6]))
    check("模块 docstring 写清「无后台定时器」",
          bool(TIMERS_MOD.__doc__) and "无后台定时器" in TIMERS_MOD.__doc__)
    check("公开面只有形状名（无游戏语义）",
          set(TIMERS_MOD.__all__) == {"TimerStorageError", "Timers"},
          str(TIMERS_MOD.__all__))
    check("Timers 的公开方法是规格那六个",
          all(callable(getattr(Timers, m, None)) for m in
              ("register", "set", "get", "due", "remove", "refresh")))
    check("过期回调签名 = (owner, key, data)",
          "on_expire(owner, key, data)" in (Timers.register.__doc__ or ""))


# ---------------------------------------------------------------- 8 反证
def t8_negative():
    print("\n[8] ★ 反证：这些点在实现被改坏时必红（另有 out/LANDING.md 的突变实验）")

    # ① due 必须清理过期项（改坏成「只列不清」→ 这里红）
    fires = []
    st, ck = {}, Clock(0)
    tm = mk(st, ck)
    tm.register("k1", duration=5, on_expire=lambda o, k, d: fires.append(k))
    tm.set("o1", "a", "k1")
    ck.set(5)
    listed = tm.due("o1")
    check("① due 不含过期项（反证点：改坏成只列不清 → 这里会变成 [\"a\"]）",
          [e["key"] for e in listed] == [], str(listed))
    check("① due 触发过回调（反证点：不清 → 回调计数为 0）", fires == ["a"], str(fires))
    check("① 过期项已从存储消失（反证点：不清 → 键还在）", "o1" not in st, str(st))

    # ② remove(fire=False) 不回调（改坏成总回调 → 这里红）
    fires = []
    st, ck = {}, Clock(0)
    tm = mk(st, ck)
    tm.register("k1", duration=5, on_expire=lambda o, k, d: fires.append(k))
    tm.set("o1", "a", "k1")
    tm.remove("o1", "a")
    check("② remove(fire=False) 零回调（反证点：改坏成总回调 → 这里变成 [\"a\"]）",
          fires == [], str(fires))

    # ③ 同 key 顶替（改坏成「已存在就拒绝/追加」→ 这里红）
    st, ck = {}, Clock(0)
    tm = mk(st, ck)
    tm.register("k1", duration=10)
    tm.set("o1", "a", "k1", duration=10)
    ck.set(5)
    re_set = tm.set("o1", "a", "k1", duration=10)
    check("③ 顶替刷新给出新 expire（反证点：拒绝重复 → 这里红）", re_set == 15, str(re_set))
    check("③ 表里仍只有一条", list(st["o1"]) == ["a"], str(st))

    # ④ 未注册类型留痕（改坏成静默兜底 → 这里红）
    log = Log()
    tm = mk({}, Clock(0), log=log)
    tm.set("o1", "a", "no_such_type")
    check("④ 未注册类型必须留痕（反证点：静默 → 记录为空）",
          len(log.records) == 1 and "no_such_type" in log.records[0], str(log.records))


def main():
    print("== timers 门禁：倒计时事件形状（注册 / 过期三路 / 删除 / 懒计时 / 零知识）==")
    t1_register_set()
    t2_expire_paths()
    t3_remove()
    t4_lazy_clock()
    t5_fail_closed()
    t6_shape()
    t7_zero_knowledge()
    t8_negative()
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    if DETAIL:
        print("失败清单：")
        for d in DETAIL:
            print(f"  ❌ {d}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
