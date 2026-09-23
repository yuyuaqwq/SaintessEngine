#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""presence 门禁：日期派生逐值表 / 保底写入时机 / 多表真值链 / 零知识 / 多故障。

跑法：python tests/test_presence_shape.py
退出码：0 = 全绿；1 = 有失败。

为什么这些断言非有不可
----------------------
① **算术形状必须逐值对表**（≥1000 组真值域）：`day_slot` / `day_hit` / `minutes_left`
   这类派生最容易被「顺手化简」成等价的浮点写法 —— 几个样例测不出来，逐值表能。
② **`day_hit` 不许化简成百分比浮点比较**：门槛是 `int(rate*100)` 这个**整数**；
   5 个真值（0.75/0.8/0.85/0.9/0.95）各一条断言钉住方向与门槛。
③ **保底/冷却的写入时机（先判后写）**：短路路径**不消耗 `rng`、不产生 `miss+1`**。
④ **零知识静态扫描（ast）**：引擎源码里不许出现取值词 / 业务字段名（docstring 除外）。
⑤ **多故障 + 顺序**：只坏一处证明不了顺序；两处同坏 + 第三处仍绿，
   以及「门序对才成立的输入」才是顺序证明。
"""
import ast
import hashlib
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ---- 扩展包门禁路径（2026-09-23 从引擎 tests/ 搬到本包）----
# 本文件现在位于 extends/<pkg>/tests/ ⇒ 往上四级才是**引擎根**，ROOT 重新绑定到它，
# 这样下面原有的 `os.path.join(ROOT, "saintess_engine", ...)` 一类路径扫描仍然指对地方。
_HERE_DIR = os.path.dirname(os.path.abspath(__file__))   # extends/<pkg>/tests
_PKG_ROOT = os.path.dirname(_HERE_DIR)                   # extends/<pkg>
_EXT_BASE = os.path.dirname(_PKG_ROOT)                   # extends
ROOT = os.path.dirname(_EXT_BASE)                        # 引擎根
for _p in (ROOT, _EXT_BASE, _HERE_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ext_social.presence as PRESENCE                              # noqa: E402
from ext_social.presence import (Lookup, Presence, cooldown_ok,     # noqa: E402
                                      day_hit, day_slot, guarded_roll,
                                      merge_tables, minutes_left)

PRESENCE_DIR = os.path.join(ROOT, "extends", "ext_social", "presence")
PRESENCE_SRC = os.path.join(PRESENCE_DIR, "__init__.py")

passed = failed = 0
CHECKS = 0


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


def _sources():
    out = {}
    for fn in sorted(os.listdir(PRESENCE_DIR)):
        if fn.endswith(".py"):
            p = os.path.join(PRESENCE_DIR, fn)
            out[f"presence/{fn}"] = open(p, encoding="utf-8").read()
    return out


# ─────────────────────────────────────────────── 独立参考实现（不调用被测模块）
def ref_day_slot(seed, size, salt=""):
    total = seed * 2654435761 + (sum(ord(c) for c in salt) if salt else 0)
    return (total & 0x7FFFFFFF) % size


def ref_day_hit(seed, salt, rate):
    return ref_day_slot(seed, 100, salt) >= int(rate * 100)


def ref_minutes(sec):
    return max(1, -(-int(sec) // 60))


def ref_guard(miss, guarantee, chance, rng):
    if not chance:
        return (True, miss, False)
    if miss >= guarantee:
        return (True, 0, True)
    if rng() < chance:
        return (True, miss, False)
    return (False, miss + 1, False)


# 真数据里的键形态（salt = id / id + ":appear" / id + ":line"）
TABLE_SALTS = ("", "h_owl", "w_trapper", "npc_anvil_mule", "npc_aurora_lantern",
               "npc_anvil_mule:appear", "npc_aurora_lantern:appear",
               "npc_boar_hunter:line")
SEEDS = range(730000, 740001)            # date.toordinal() 真值域
TABLE_SIZES = (1, 2, 3, 5, 7, 16, 47, 63, 100, 101, 731)
RATES = (0.75, 0.8, 0.85, 0.9, 0.95)     # 真数据里的五档
TOTAL = {"slots": 0, "hits": 0, "minutes": 0}


# ─────────────────────────────────────────────── 1 逐值表
def t1_day_slot_table():
    print("\n[1] day_slot 逐值表：((seed*2654435761 + Σord(salt)) & 0x7FFFFFFF) % size")
    bad = []
    n = 0
    for salt in TABLE_SALTS:
        for seed in SEEDS:
            got = day_slot(seed, 47, salt=salt)
            exp = ref_day_slot(seed, 47, salt=salt)
            n += 1
            if got != exp:
                bad.append((seed, 47, salt, exp, got))
    for size in TABLE_SIZES:
        for salt in TABLE_SALTS:
            for seed in range(730000, 740001, 41):
                got = day_slot(seed, size, salt=salt)
                exp = ref_day_slot(seed, size, salt=salt)
                n += 1
                if got != exp:
                    bad.append((seed, size, salt, exp, got))
    TOTAL["slots"] = n
    check(f"逐值表全等（{n} 组，≥1000）", not bad and n >= 1000, str(bad[:3]))

    # 中间量精确钉住：size = 2**31 时取模是恒等 ⇒ 拿到的就是裸哈希
    raw_bad = [(s, day_slot(s, 1 << 31, salt="h_owl"),
                (s * 2654435761 + sum(ord(c) for c in "h_owl")) & 0x7FFFFFFF)
               for s in range(730000, 730050)]
    check("裸哈希中间量与公式逐值相等（size=2**31 取模恒等）",
          all(a == b for _s, a, b in raw_bad), str(raw_bad[:2]))

    # 槽位覆盖 0..99：证明这张表不是退化成几个值
    seen = {day_slot(s, 100, salt="npc_anvil_mule") for s in SEEDS}
    check("某个盐下 0..99 全部槽位都被覆盖到", seen == set(range(100)), str(sorted(seen))[:60])

    # 边界与 fail-closed
    for bad_size, exc in ((0, ValueError), (-1, ValueError), ("3", TypeError), (True, TypeError)):
        try:
            day_slot(730000, bad_size)
            check(f"非法 size {bad_size!r} → {exc.__name__}", False)
        except exc:
            check(f"非法 size {bad_size!r} → {exc.__name__}", True)
    try:
        day_slot(730000, 47, salt=None)
        check("非字符串 salt → TypeError（不静默当空盐）", False)
    except TypeError:
        check("非字符串 salt → TypeError（不静默当空盐）", True)
    check("day_slot 是纯函数（同输入两次同值）",
          all(day_slot(s, 47, salt="w_trapper") == day_slot(s, 47, salt="w_trapper")
              for s in SEEDS))


def _seed_with_slot(slot, salt=""):
    """在真值域里取第一个落在该槽位的 seed（按盐缓存，避免重复扫）。"""
    table = _SLOT_SEEDS.get(salt)
    if table is None:
        table = {}
        for seed in SEEDS:
            table.setdefault(day_slot(seed, 100, salt=salt), seed)
        _SLOT_SEEDS[salt] = table
    if slot not in table:
        raise AssertionError(f"盐 {salt!r} 在真值域内没覆盖到槽位 {slot}")
    return table[slot]


_SLOT_SEEDS = {}


def t2_day_hit_threshold():
    print("\n[2] day_hit：不许化简成百分比浮点比较（五个真值各一条断言）")
    n = 0
    for rate in RATES:
        threshold = int(rate * 100)
        bad = []
        for salt in TABLE_SALTS:
            for seed in SEEDS:
                n += 1
                if day_hit(seed, salt=salt, rate=rate) != ref_day_hit(seed, salt, rate):
                    bad.append((seed, salt, rate))
        below = _seed_with_slot(threshold - 1, "h_owl")
        at = _seed_with_slot(threshold, "h_owl")
        check(
            f"rate={rate} 逐值全等 + 门槛恰在 {threshold}（<门槛 False / =门槛 True）",
            not bad
            and day_hit(below, salt="h_owl", rate=rate) is False
            and day_hit(at, salt="h_owl", rate=rate) is True
            and day_slot(below, 100, salt="h_owl") == threshold - 1
            and day_slot(at, 100, salt="h_owl") == threshold,
            str(bad[:2]))
    TOTAL["hits"] = n
    check(f"五个真值的逐值表合计 {n} 组（≥1000）", n >= 1000)

    # 「裸判据」方向：True 恰好是 [threshold, 100) 这一段（不是 [0, threshold)）
    counts = []
    for rate in RATES:
        t = int(rate * 100)
        slot_hits = sum(1 for x in range(100) if x >= t)
        got = sum(1 for x in range(100)
                  if day_hit(_seed_with_slot(x, "w_trapper"), salt="w_trapper", rate=rate))
        counts.append(got == slot_hits == 100 - t)
    check("True 的槽位集合 = [int(rate*100), 100)（裸判据方向被钉死）", all(counts), str(counts))
    check("rate=1.0 → 恒 False（门槛 100 不可达）；rate=0 → 恒 True",
          all(day_hit(s, rate=1.0) is False for s in range(730000, 730100))
          and all(day_hit(s, rate=0) is True for s in range(730000, 730100)))
    try:
        day_hit(730000, rate=None)
        check("非数值 rate → TypeError", False)
    except TypeError:
        check("非数值 rate → TypeError", True)


def t3_minutes_left():
    print("\n[3] minutes_left：九格逐值 + 下限恒 ≥1")
    table = {0: 1, 1: 1, 59: 1, 60: 1, 61: 2, 119: 2, 120: 2, 3599: 60, 3600: 60}
    bad = [(k, v, minutes_left(k)) for k, v in table.items() if minutes_left(k) != v]
    check("九格逐值 {0,1,59,60,61,119,120,3599,3600}", not bad, str(bad))
    n = 0
    bad2 = []
    for sec in range(-120, 7201, 7):
        n += 1
        got = minutes_left(sec)
        if got != ref_minutes(sec) or got < 1:
            bad2.append((sec, ref_minutes(sec), got))
    TOTAL["minutes"] = n
    check(f"参考表全等且下限恒 ≥1（{n} 格）；ceil 不是 floor（61→2 / 119→2）",
          not bad2 and minutes_left(61) == 2 and minutes_left(119) == 2, str(bad2[:3]))
    check("非法输入 → 报错（不静默当 0）",
          _raises(lambda: minutes_left(None), TypeError)
          and _raises(lambda: minutes_left(True), TypeError))


def _raises(fn, exc):
    try:
        fn()
    except exc:
        return True
    except Exception:
        return False
    return False


def t4_guarded_roll():
    print("\n[4] guarded_roll：先判后写（短路路径不消耗 rng、不产生 miss+1）")
    calls = {"n": 0}

    def rng():
        calls["n"] += 1
        return 0.0

    # ① chance 假值：miss 原样带回、rng 不读
    calls["n"] = 0
    check("chance 假值 → (True, miss, False)，miss 原样、rng 零调用",
          guarded_roll(5, guarantee=7, chance=0, rng=rng) == (True, 5, False)
          and guarded_roll(5, guarantee=7, chance=None, rng=rng) == (True, 5, False)
          and calls["n"] == 0)

    # ② 保底：cleared=True 表达「该清计数」，不是 miss+1、rng 不读
    calls["n"] = 0
    check("miss>=guarantee → (True, 0, True)（cleared，而非 miss+1）；rng 零调用",
          guarded_roll(7, guarantee=7, chance=0.5, rng=rng) == (True, 0, True)
          and calls["n"] == 0)

    # ③ rng 命中：miss 原样带回（命中路径不清计数），rng 被恰好读一次
    calls["n"] = 0

    def rng_hit():
        calls["n"] += 1
        return 0.499999

    check("rng()<chance → (True, miss, False)（命中不清计数）",
          guarded_roll(3, guarantee=7, chance=0.5, rng=rng_hit) == (True, 3, False)
          and calls["n"] == 1)

    # ④ 未中：唯一一次 miss+1
    check("落空 → (False, miss+1, False)",
          guarded_roll(3, guarantee=7, chance=0.5, rng=lambda: 0.5) == (False, 4, False))

    # 逐值表：与参考实现同输入同输出（含 rng 序列）
    seq = [0.1, 0.9, 0.5, 0.0, 0.99]
    got, exp, bad = [], [], []
    for miss in range(0, 10):
        for chance in (0, None, 0.5, 1):
            it = iter(seq * 4)
            live = guarded_roll(miss, guarantee=7, chance=chance, rng=lambda: next(it))
            it2 = iter(seq * 4)
            want = ref_guard(miss, 7, chance, lambda: next(it2))
            got.append(live)
            exp.append(want)
            if live != want:
                bad.append((miss, chance, live, want))
    check("保底/命中/落空逐值表全等（miss 0..9 × chance 4 档）", not bad, str(bad[:3]))
    check("guarded_roll 是纯函数（同输入同输出、无隐藏状态）",
          guarded_roll(6, guarantee=7, chance=0.5, rng=lambda: 0.9)
          == guarded_roll(6, guarantee=7, chance=0.5, rng=lambda: 0.9))
    for bad_miss in (-1, 1.0, True, "1"):
        try:
            guarded_roll(bad_miss, guarantee=7, chance=0.5, rng=lambda: 0.1)
            check(f"非法 miss {bad_miss!r} → 报错", False)
        except (TypeError, ValueError):
            check(f"非法 miss {bad_miss!r} → 报错", True)


def t5_cooldown():
    print("\n[5] cooldown_ok：没记过即放行 + 窗口边界")
    check("last 假值（0/None）→ True（没记过 = 可触发）",
          cooldown_ok(0, 10 ** 9, 1800) is True and cooldown_ok(None, 10 ** 9, 1800) is True)
    check("窗口边界：now-last == window → True；少 1 秒 → False",
          cooldown_ok(100, 1900, 1800) is True and cooldown_ok(100, 1899, 1800) is False)
    check("负差（时钟回拨）→ False", cooldown_ok(2000, 100, 1800) is False)


# ─────────────────────────────────────────────── 6 表语义 / 真值链
def t6_tables_and_lookup():
    print("\n[6] merge_tables 保序 + exclude；Lookup 真值链（空 mapping 穿透）")
    t0 = {"a": 1, "b": 2}
    t1 = {"b": 20, "c": 3}
    merged = merge_tables(t0, t1)
    check("保序合并：键序 = 表序 × 表内序，同名后者胜",
          list(merged) == ["a", "b", "c"] and merged == {"a": 1, "b": 20, "c": 3}, str(merged))
    check("返回新 dict，不写输入", merged is not t0 and merged is not t1
          and t0 == {"a": 1, "b": 2} and t1 == {"b": 20, "c": 3})
    ex = merge_tables(t0, t1, exclude=("b",))
    check("exclude 跳过（每一张表里都跳过、不占位）",
          list(ex) == ["a", "c"] and ex == {"a": 1, "c": 3}, str(ex))
    check("exclude 写成字符串 = 整体一个键（不拆成字符）",
          merge_tables(t0, exclude="a") == {"b": 2}
          and merge_tables(t0, exclude="ab") == {"a": 1, "b": 2})
    check("merge_tables() 空参 → 空 dict；非法表 → TypeError",
          merge_tables() == {} and _raises(lambda: merge_tables([("a", 1)]), TypeError))

    empty = {}
    lk = Lookup({"a": empty, "b": 0, "c": ""}, {"a": {"x": 1}, "b": {"y": 2}, "d": {"z": 3}})
    check("★ 真值链：空 dict / 0 / 空串都穿透到下一张表",
          lk.first("a") == ({"x": 1}, 1) and lk.first("b") == ({"y": 2}, 1)
          and lk.first("c") == (None, None))
    check("首表真值命中即止（下标 0）", Lookup({"a": {"x": 1}}, {"a": {"x": 2}}).first("a")
          == ({"x": 1}, 0))
    check("全落空 → (None, None)", lk.first("zzz") == (None, None))
    check("rows 保序 + 缺席丢弃",
          lk.rows(["d", "a", "zzz", "b"]) == [("d", {"z": 3}, 1), ("a", {"x": 1}, 1),
                                              ("b", {"y": 2}, 1)], str(lk.rows(["d", "a", "zzz", "b"])))
    check("tables 原对象只读元组；空 Lookup 全落空",
          Lookup(t0, t1).tables[0] is t0 and Lookup().first("a") == (None, None))
    check("Lookup 非法表 → TypeError", _raises(lambda: Lookup(5), TypeError))


# ─────────────────────────────────────────────── 7 Presence 规则逐条
def _rows():
    return {"r1": {"tag": 1}, "r2": {"tag": 2}, "r3": {"tag": 3}}


def t7_presence_rules():
    print("\n[7] Presence：声明序 + 一条注入判据（每条兜底分支各一断言）")
    rows = _rows()
    lk = Lookup(rows)

    seen = []
    p = Presence(lk, keep=lambda i, r: (seen.append(i), True)[1],
                 place_of=lambda i, r, d: "p" if i != "r2" else "q")
    check("keep 每次现算（不缓存）", p.rows(["r1"]) == [("r1", rows["r1"], 0)] and seen == ["r1"])
    check("rows 保序（含输入倒序）；重复 id 不去重",
          [x[0] for x in p.rows(["r3", "r1", "r1"])] == ["r3", "r1", "r1"]
          and [x[0] for x in p.rows(["r1", "r3"])] == ["r1", "r3"])
    check("place=None → 不做定位过滤（不是「定位为空」）",
          [x[0] for x in p.rows(["r1", "r2"])] == ["r1", "r2"])
    check("place 给值 → 定位相等才留（r2 被滤掉）",
          [x[0] for x in p.rows(["r1", "r2", "r3"], place="p")] == ["r1", "r3"])
    check("keep 为假丢弃（占位在第 2 位也被跳过后仍保序）",
          [x[0] for x in Presence(lk, keep=lambda i, r: i != "r2",
                                  place_of=lambda i, r, d: "p").rows(["r1", "r2", "r3"])]
          == ["r1", "r3"])
    check("here = rows 的行投影（仍保序）",
          Presence(lk, keep=lambda i, r: i != "r2", place_of=lambda i, r, d: "p").here(
              ["r3", "r2", "r1"]) == [rows["r3"], rows["r1"]])
    check("表下标随命中表变化", p.rows(["r1"])[0][2] == 0)
    check("lookup 原对象；key_of 缺省 = 传入 id",
          p.lookup is lk and p.key_of("r7", {"tag": 7}) == "r7")

    # 世界变了 → 下次调用立刻可见（不缓存）
    rows["r1"]["tag"] = 100
    check("★ J3 不缓存：行对象就变了 → 同一 Presence 的结果跟着变",
          p.here(["r1"]) == [{"tag": 100}])

    # fail-closed
    check("keep / place_of 不可调用 → TypeError",
          _raises(lambda: Presence(lk, keep=None, place_of=lambda *a: "p"), TypeError)
          and _raises(lambda: Presence(lk, keep=lambda *a: True, place_of="x"), TypeError))
    check("lookup 没有 rows(ids) → TypeError",
          _raises(lambda: Presence(object(), keep=lambda *a: True, place_of=lambda *a: None),
                  TypeError))


def t8_slots_and_overlay():
    print("\n[8] slots 续号 / slot_at 越界 / overlay 视图与序列化")
    lk = Lookup(_rows())
    p = Presence(lk, keep=lambda i, r: True, place_of=lambda i, r, d: "p")
    slots = p.slots(["A", "B"], ["C"])
    check("静态在前、叠加续号（从 1 起）",
          slots == [(1, "static", "A"), (2, "static", "B"), (3, "overlay", "C")], str(slots))
    check("空静态 / 空叠加各自退化",
          p.slots([], []) == [] and p.slots([], ["C"]) == [(1, "overlay", "C")]
          and p.slots(["A"], []) == [(1, "static", "A")])
    check("slot_at 1-based 取整条；越界（含 0/负）→ None",
          p.slot_at(slots, 1) == (1, "static", "A")
          and p.slot_at(slots, 3) == (3, "overlay", "C")
          and p.slot_at(slots, 0) is None and p.slot_at(slots, -1) is None
          and p.slot_at(slots, 4) is None and p.slot_at([], 1) is None)
    check("slot_at 非整数 → TypeError", _raises(lambda: p.slot_at(slots, "1"), TypeError))

    evs = [{"key": "k1", "row_id": "w1", "place": "m1", "remain": 61},
           {"key": "k2", "row_id": "w2", "place": "m1", "expire": 1000}]
    ov = p.overlay(evs, now=940)
    check("overlay 保有输入序；给 remain 用 remain，没给用 expire-now",
          [e["key"] for e in ov] == ["k1", "k2"]
          and ov[0]["minutes"] == 2 and ov[1]["minutes"] == 1, str(ov))
    check("overlay 原样带回 row_id/place/raw（raw 是原对象，不拷贝）",
          ov[0]["row_id"] == "w1" and ov[0]["place"] == "m1" and ov[0]["raw"] is evs[0]
          and ov[1]["row_id"] == "w2")
    check("minutes 口径经注入（可换）",
          p.overlay(evs[:1], now=0, minutes=lambda s: 999)[0]["minutes"] == 999)

    # 视图 / 序列化：纯 JSON 可 dumps（引擎不产不可序列化对象）
    blob = {
        "rows": p.rows(["r1", "r2"], place="p"),
        "here": p.here(["r1"]),
        "slots": p.slots(["A"], ["B"]),
        "overlay": p.overlay(evs, now=940),
        "lookup": Lookup(_rows()).rows(["r1"]),
        "merged": merge_tables({"a": 1}, {"b": 2}),
    }
    text = json.dumps(blob, ensure_ascii=False, sort_keys=True)
    check("全部视图纯 JSON 可序列化且 round-trip 稳定",
          text == json.dumps(json.loads(text), ensure_ascii=False, sort_keys=True))
    check("J9 幂等：同输入重复调用逐值相等",
          json.dumps(blob["rows"]) == json.dumps(p.rows(["r1", "r2"], place="p"))
          and p.slots(["A"], ["B"]) == [(1, "static", "A"), (2, "overlay", "B")])


# ─────────────────────────────────────────────── 9 零知识静态扫描
_VALUE_WORDS = (
    "奥兰迪亚", "余烬", "镇长", "游商", "铁匠", "导师", "见习", "隐者", "见闻",
    "__end__", "story", "……", "npc", "dialogue", "npcs",
    "quest_done", "quest_active", "quest_pending", "quest_ready", "not_quest_done",
    "side_ready", "side_available", "quest_any_active", "apprentice", "not_apprentice",
    "is_novice", "not_novice", "class_any", "race_is", "hidden_unlocked", "hidden_current",
    "not_hidden_current", "evolve_ready",
    "quest_take", "set_flag", "side_offer", "side_take", "evolve_class",
    "apprentice_check", "tutor_skill", "consume_item", "give_item", "unlock_prof",
    "give_prof_exp", "open_shop", "hint", "unlock_class",
    "morning", "day", "evening", "night", "spring", "summer", "autumn", "winter",
    "sunny", "rain", "storm", "snow", "fog",
    "flag:", "item:", "quest:", "quest_done:", "stats:",
    "funcs", "roam", "appear", "period", "condition", "unlock", "inst_stage",
    "chance", "cycle", "duration", "lines", "title", "icon", "gender",
    "gold", "exp", "q1_1", "cls_novice", "npc_mayor",
)
# 业务字段名（BRIEF §1.2-6 单列；不许作为**常量**出现，形参/局部名不算）
_FIELD_WORDS = ("map", "funcs", "roam", "appear", "chance", "cycle", "period",
                "condition", "unlock", "inst_stage")
_FORBIDDEN_IMPORTS = ("os", "sys", "json", "datetime", "time", "calendar", "zoneinfo", "random")


def _docstring_ids(tree):
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None) or []
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                ids.add(id(body[0].value))
    return ids


def _word_hits(text, words):
    hits = []
    for w in words:
        if text == w:
            hits.append(w)
        elif w.isascii():
            if re.search(r"(?<![A-Za-z0-9_])" + re.escape(w) + r"(?![A-Za-z0-9_])", text):
                hits.append(w)
        elif w in text:
            hits.append(w)
    return hits


def t9_zero_knowledge():
    print("\n[9] 零知识：取值词 / 业务字段名（常量，docstring 除外）+ import 面")
    bad, n = [], 0
    for rel, src in _sources().items():
        tree = ast.parse(src, filename=rel)
        docs = _docstring_ids(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and id(node) not in docs:
                n += 1
                hits = _word_hits(node.value, _VALUE_WORDS)
                if hits:
                    bad.append(f"{rel}:{node.lineno}:{hits}:{node.value[:40]!r}")
    check(f"非 docstring 字符串常量零取值词（扫了 {n} 个常量）", not bad, str(bad[:5]))

    field_bad = []
    for rel, src in _sources().items():
        tree = ast.parse(src, filename=rel)
        docs = _docstring_ids(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and id(node) not in docs:
                hits = _word_hits(node.value, _FIELD_WORDS)
                if hits:
                    field_bad.append(f"{rel}:{node.lineno}:{hits}")
    check("业务字段名零常量命中（形参/局部名不算）", not field_bad, str(field_bad[:5]))

    roots = set()
    for rel, src in _sources().items():
        for node in ast.walk(ast.parse(src, filename=rel)):
            if isinstance(node, ast.Import):
                roots.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level:
                roots.add((node.module or "").split(".")[0])
    check("零禁用 import（random/datetime/time/calendar/zoneinfo/os/sys/json）",
          not (roots & set(_FORBIDDEN_IMPORTS)), f"roots={sorted(roots)}")
    check("绝对 import 落在标准库 + 引擎通用件（可分发性；2026-09-23 起本形状在 extends/ext_social/）",
          roots <= (set(sys.stdlib_module_names) | {"saintess_engine"}), f"roots={sorted(roots)}")
    check("模块 docstring 在（形状自带说明）且 __all__ 与设计一致",
          bool(PRESENCE.__doc__)
          and PRESENCE.__all__ == ["Lookup", "Presence", "day_slot", "day_hit",
                                   "minutes_left", "guarded_roll", "cooldown_ok",
                                   "merge_tables"], str(PRESENCE.__all__))
    check("rng 缺省 / 显式 None → TypeError（不许悄悄用系统随机）",
          _raises(lambda: guarded_roll(0, guarantee=7, chance=0.5), TypeError)
          and _raises(lambda: guarded_roll(0, guarantee=7, chance=0.5, rng=None), TypeError))


# ─────────────────────────────────────────────── 10 口径分歧断言
def t10_divergence():
    print("\n[10] 口径分歧断言（逐条对应设计稿，故意不统一）")
    check("⑥ remain → 分钟用 ceil 且下限 1：0→1 / 60→1 / 61→2",
          (minutes_left(0), minutes_left(60), minutes_left(61)) == (1, 1, 2))
    check("⑨ chance 假值 = 必定命中（不是永不命中）",
          guarded_roll(0, guarantee=7, chance=0, rng=lambda: 1.0)[0] is True)
    check("⑪ rng 命中路径不清计数（cleared 只在保底那一路）",
          guarded_roll(3, guarantee=7, chance=0.9, rng=lambda: 0.0) == (True, 3, False)
          and guarded_roll(7, guarantee=7, chance=0.9, rng=lambda: 0.0) == (True, 0, True))
    check("⑤ 确定性（日期派生）vs 随机性（注入 rng）两口径不合并",
          day_slot(730000, 47, salt="h_owl") == day_slot(730000, 47, salt="h_owl")
          and day_hit(730000, salt="h_owl:appear", rate=0.8)
          == day_hit(730000, salt="h_owl:appear", rate=0.8)
          and guarded_roll(0, guarantee=7, chance=0.5, rng=lambda: 0.1)
          != guarded_roll(0, guarantee=7, chance=0.5, rng=lambda: 0.9))
    check("⑦ 保序 / 不去重 / 不排序：清单就是输入序（含重复项）",
          Presence(Lookup(_rows()), keep=lambda i, r: True, place_of=lambda i, r, d: "p").rows(
              ["r2", "r1", "r2"]) == [("r2", {"tag": 2}, 0), ("r1", {"tag": 1}, 0),
                                      ("r2", {"tag": 2}, 0)])
    check("③ 表合并后表胜前表 + exclude 只跳过不报错",
          merge_tables({"a": 1}, {"a": 2}, exclude=("zz",)) == {"a": 2})
    check("① 空 mapping 穿透（真值链，不是 is not None 链）",
          Lookup({"a": {}}, {"a": 0}, {"a": {"x": 1}}).first("a") == ({"x": 1}, 2))


# ─────────────────────────────────────────────── 11 多故障 + 顺序断言
class _Patch:
    """临时替换属性（进入记原值，退出原地还原；**不写盘**）。"""

    def __init__(self, obj, name, value):
        self.obj, self.name, self.value = obj, name, value
        self.had = hasattr(obj, name)
        self.old = getattr(obj, name, None)

    def __enter__(self):
        setattr(self.obj, self.name, self.value)
        return self

    def __exit__(self, *exc):
        if self.had:
            setattr(self.obj, self.name, self.old)
        else:
            delattr(self.obj, self.name)
        return False


def probes():
    """六个探针：返回 True = 活实现与参考实现不符（红）。

    一律经 `PRESENCE.<名>` 取活实现（不绑定 import 时的局部名）—— 这样
    monkeypatch 模块属性才能真正作用到探针上。
    """
    def p_slot():
        return any(PRESENCE.day_slot(s, 47, salt=x) != ref_day_slot(s, 47, x)
                   for x in TABLE_SALTS for s in range(730000, 731000))

    def p_hit():
        return any(PRESENCE.day_hit(s, salt=x, rate=r) != ref_day_hit(s, x, r)
                   for r in RATES for x in TABLE_SALTS for s in range(730000, 731000))

    def p_minutes():
        return any(PRESENCE.minutes_left(s) != ref_minutes(s) for s in range(-60, 7200, 13))

    def p_guard():
        return any(PRESENCE.guarded_roll(m, guarantee=7, chance=c, rng=lambda: 0.4)
                   != ref_guard(m, 7, c, lambda: 0.4)
                   for m in range(0, 10) for c in (0, None, 0.5, 1))

    def p_cooldown():
        return any(PRESENCE.cooldown_ok(l, n, 1800) is not ((True) if not l else (n - l) >= 1800)
                   for l in (0, 100, 2000) for n in (0, 100, 1900, 5000))

    def p_merge():
        return PRESENCE.merge_tables({"a": 1, "b": 2}, {"b": 3}, exclude=("a",)) != {"b": 3}

    def p_lookup():
        return PRESENCE.Lookup({"a": {}}, {"a": {"x": 1}}).first("a") != ({"x": 1}, 1)

    return {"slot": p_slot, "hit": p_hit, "minutes": p_minutes, "guard": p_guard,
            "cooldown": p_cooldown, "merge": p_merge, "lookup": p_lookup}


def t11_multifault_and_order():
    print("\n[11] 多故障（两处同坏 + 第三处仍绿）+ 顺序断言")
    ps = probes()
    check("未破坏时全部探针为绿", all(p() is False for p in ps.values()),
          str({k: p() for k, p in ps.items() if p()}))

    broken_slot = lambda seed, size, *, salt="": ref_day_slot(seed, size + 1, salt)
    broken_minutes = lambda sec: 0
    broken_merge = lambda *t, exclude=(): {}
    broken_cooldown = lambda last, now, window: False
    broken_hit = lambda seed, *, salt="", rate: not ref_day_hit(seed, salt, rate)

    # 两处同坏 → 两条探针各自红，且互不掩盖；第三处（merge）仍绿
    with _Patch(PRESENCE, "day_slot", broken_slot), _Patch(PRESENCE, "minutes_left", broken_minutes):
        check("同坏 A（day_slot + minutes_left）→ 两条探针各自变红",
              ps["slot"]() is True and ps["minutes"]() is True)
        check("同坏 A 时第三处（merge）必须仍绿（不是一个大探针管全部）",
              ps["merge"]() is False)
    check("还原 A → 探针回绿", ps["slot"]() is False and ps["minutes"]() is False)

    with _Patch(PRESENCE, "merge_tables", broken_merge), _Patch(PRESENCE, "cooldown_ok",
                                                               broken_cooldown):
        check("同坏 B（merge_tables + cooldown_ok）→ 两条探针各自变红、lookup 仍绿",
              ps["merge"]() is True and ps["cooldown"]() is True and ps["lookup"]() is False)
    check("还原 B → 探针回绿", ps["merge"]() is False and ps["cooldown"]() is False)

    with _Patch(PRESENCE, "day_hit", broken_hit), _Patch(PRESENCE, "guarded_roll",
                                                         lambda *a, **k: (False, 0, False)):
        check("同坏 C（day_hit + guarded_roll）→ 两条探针各自变红、minutes 仍绿",
              ps["hit"]() is True and ps["guard"]() is True and ps["minutes"]() is False)
    check("还原 C → 探针回绿", ps["hit"]() is False and ps["guard"]() is False)

    # 顺序 ①：guarded_roll 门序 —— 只有「chance 先判」才给出 (True, miss, False)
    calls = {"n": 0}
    got = guarded_roll(7, guarantee=7, chance=0, rng=lambda: calls.__setitem__("n", 1) or 0.0)
    check("★ 顺序① 门序：chance 假值先于保底 → (True, 7, False)（门序反了会得 (True,0,True)）",
          got == (True, 7, False) and calls["n"] == 0, str(got))

    # 顺序 ②：Lookup 表序 —— 同名真值时首表胜；反过来则另一表胜
    check("★ 顺序② 表序：Lookup 按传入表序首命中",
          Lookup({"a": {"n": 1}}, {"a": {"n": 2}}).first("a") == ({"n": 1}, 0)
          and Lookup({"a": {"n": 2}}, {"a": {"n": 1}}).first("a") == ({"n": 2}, 0))

    # 顺序 ③：merge_tables 键序 = 表序 × 表内序（对调表序则键序整体改变）
    fwd = list(merge_tables({"a": 1, "b": 2}, {"c": 3}))
    rev = list(merge_tables({"c": 3}, {"a": 1, "b": 2}))
    check("★ 顺序③ 合并键序随输入表序整体改变", fwd == ["a", "b", "c"] and rev == ["c", "a", "b"],
          f"{fwd} / {rev}")

    # 顺序 ④：Presence.rows 输出序 = ids 的声明序（正/倒序给出整体不同的序列）
    p = Presence(Lookup(_rows()), keep=lambda i, r: True, place_of=lambda i, r, d: "p")
    check("★ 顺序④ 清单序 = 输入 ids 序（倒序输入得倒序结果）",
          [x[0] for x in p.rows(["r1", "r2", "r3"])] == ["r1", "r2", "r3"]
          and [x[0] for x in p.rows(["r3", "r2", "r1"])] == ["r3", "r2", "r1"])

    # 顺序 ⑤：slots 续号 —— 静态 N 条 → 叠加项从 N+1 起；静态顺序改变则编号-内容对应整体改变
    a = p.slots(["A", "B"], ["C", "D"])
    b = p.slots(["B", "A"], ["C", "D"])
    check("★ 顺序⑤ 叠加续号：静态 2 条 → 叠加从 3 起；静态换序则编号-内容对应整体改变",
          [x[0] for x in a] == [1, 2, 3, 4] and a[2] == (3, "overlay", "C")
          and b[0] == (1, "static", "B") and b[2] == (3, "overlay", "C"))


# ─────────────────────────────────────────────── 12 只读 / 计数
def t12_readonly_and_counts():
    print("\n[12] 只读断言 + 计数校验（防「循环没跑」的假绿）")
    check(f"逐值表计数达标（slot={TOTAL['slots']} / hit={TOTAL['hits']} / "
          f"minutes={TOTAL['minutes']}，均 ≥1000）",
          TOTAL["slots"] >= 1000 and TOTAL["hits"] >= 1000 and TOTAL["minutes"] >= 1000,
          str(TOTAL))
    after = hashlib.sha256(open(PRESENCE_SRC, encoding="utf-8").read().encode("utf-8")).hexdigest()
    check("全程零写盘：引擎源码 sha256 与开跑时一致",
          after == _BOOT_DIGEST, f"{_BOOT_DIGEST} -> {after}")


_BOOT_DIGEST = hashlib.sha256(
    open(PRESENCE_SRC, encoding="utf-8").read().encode("utf-8")).hexdigest()


def main():
    print("== presence 门禁：逐值表 / 保底时机 / 真值链 / 零知识 / 多故障 ==")
    t1_day_slot_table()
    t2_day_hit_threshold()
    t3_minutes_left()
    t4_guarded_roll()
    t5_cooldown()
    t6_tables_and_lookup()
    t7_presence_rules()
    t8_slots_and_overlay()
    t9_zero_knowledge()
    t10_divergence()
    t11_multifault_and_order()
    t12_readonly_and_counts()
    print(f"\n===== 结果：通过 {passed} / 共 {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
