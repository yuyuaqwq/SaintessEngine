# -*- coding: utf-8 -*-
"""容器骨架（`saintess_kit.container`）契约测试。

锁死的契约：
1. 载入容错：坏 JSON / 非列表 / None → 空容器（不炸）
2. 容量：满则 add 返回 False；`max_slots=None` 不限；free() 剩余格数
3. 下标为 **1-based**：peek/take/remove 越界一律安全返回
4. 落盘格式：dump 出的 JSON 能被 load 原样读回（往返一致）
5. 格子规整：脏数据（非 dict / 缺字段 / count=0）也能规整成合法格子
6. 零宿主 / 零游戏依赖

跑法：python tests/test_kit_container.py
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, FW_ROOT)

from saintess_kit.container import Slots, make_entry  # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        FAILURES.append(name)
        print(f"  ❌ {name}  {detail}")


print("== 1. 载入容错 ==")
check("None → 空容器", len(Slots.load(None)) == 0)
check("坏 JSON → 空容器", len(Slots.load("{不是 json")) == 0)
check("非列表 JSON → 空容器", len(Slots.load('{"a":1}')) == 0)
check("空串 → 空容器", len(Slots.load("")) == 0)
s = Slots.load(json.dumps([{"key": "a", "data": {"x": 1}, "count": 2}]))
check("正常列表 → 载入 1 格", len(s) == 1 and s.peek_at(1)["key"] == "a")

print("== 2. 容量 ==")
cap = Slots(max_slots=2)
check("初始未满", not cap.is_full() and cap.free() == 2)
check("第 1 格加入成功", cap.add("a"))
check("第 2 格加入成功", cap.add("b"))
check("★ 满了 add 返回 False（不抛错）", cap.add("c") is False)
check("满后 len 不变", len(cap) == 2)
check("满后 free=0", cap.free() == 0)
cap.remove_at(1)
check("腾出一格后可再加", cap.add("c") is True)
unlimited = Slots()
check("不限容量：free() → None", unlimited.free() is None)
for i in range(50):
    unlimited.add(f"k{i}")
check("不限容量：50 格不拦", len(unlimited) == 50 and not unlimited.is_full())

print("== 3. 下标语义（1-based）==")
sl = Slots(entries=[{"key": "a"}, {"key": "b"}, {"key": "c"}])
check("peek_at(1) 是首格", sl.peek_at(1)["key"] == "a")
check("peek_at(3) 是末格", sl.peek_at(3)["key"] == "c")
check("peek_at(0) 越界 → None", sl.peek_at(0) is None)
check("peek_at(4) 越界 → None", sl.peek_at(4) is None)
got = sl.take_at(2)
check("take_at 取走并返回该格", got["key"] == "b" and len(sl) == 2)
check("take_at 后后续格前移", sl.peek_at(2)["key"] == "c")
check("take_at 越界 → None 且不删", sl.take_at(0) is None and len(sl) == 2)
check("remove_at 越界 → False", sl.remove_at(9) is False)
check("remove_at 正常 → True", sl.remove_at(1) is True and len(sl) == 1)

print("== 4. 落盘往返 ==")
a = Slots(max_slots=5)
a.add("sword", {"lv": 3}, 1)
a.add("potion", {}, 1)
b = Slots.load(a.dump(), max_slots=5)
check("dump → load 往返一致", b.entries() == a.entries(), (a.entries(), b.entries()))
check("往返后容量策略仍生效", b.max_slots == 5)

print("== 5. 格子规整 ==")
check("make_entry 保证 count>=1", make_entry("x", None, 0)["count"] == 1)
_src = {"lv": 3}
_made = make_entry("x", _src)
check("make_entry 安全拷贝 data（不与来源同对象）",
      _made["data"] == _src and _made["data"] is not _src)
raw = Slots.load(json.dumps([
    "裸字符串",
    {"key": "k2"},
    {"key": "k3", "count": 0},
]))
ents = raw.entries()
check("脏数据一律规整成合法格子",
      all(isinstance(e, dict) and "key" in e and isinstance(e["data"], dict)
          and e["count"] >= 1 for e in ents), ents)
check("裸值也能成格（key 保留）", ents[0]["key"] == "裸字符串", ents[0])

print("== 6. entry= 用法与迭代 ==")
z = Slots(max_slots=1)
check("add(entry={...}) 成功", z.add(entry={"key": "e1", "data": {}, "count": 1}))
check("add(entry=) 也受容量约束", z.add(entry={"key": "e2"}) is False)
check("可迭代", [e["key"] for e in Slots(entries=[{"key": "i1"}, {"key": "i2"}])] == ["i1", "i2"])
z2 = Slots(entries=[{"key": "x"}])
z2.clear()
check("clear 清空", len(z2) == 0)

print("== 7. 零宿主 / 零游戏依赖 ==")
banned = []
src = os.path.join(FW_ROOT, "saintess_kit", "container")
for dirpath, dirs, fs in os.walk(src):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    for f in fs:
        if not f.endswith(".py"):
            continue
        for line in open(os.path.join(dirpath, f), encoding="utf-8").read().splitlines():
            st = line.strip()
            if not st.startswith(("import ", "from ")):
                continue
            parts = st.split()
            mod = parts[1].split(".")[0] if len(parts) > 1 else ""
            if mod in ("game", "astrbot"):
                banned.append(f"{f}: {st}")
check("不 import 游戏包 / 宿主", not banned, banned)

print(f"\n=== 结果 PASS={PASS} FAIL={FAIL} ===")
if FAILURES:
    print("失败项：" + ", ".join(FAILURES))
sys.exit(1 if FAIL else 0)
