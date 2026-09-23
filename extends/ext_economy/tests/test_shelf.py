#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""shelf 门禁：限量货架形状 —— 惰性 / 两类周期 / 取用 / 售罄下架 / 先到先得 / fail-closed / 零知识。

跑法：python tests/test_shelf.py
退出码：0 = 全绿；1 = 有失败。

四处专门钉住的地方（都是「改了就静默变行为」的）：
  ① **惰性且幂等**：`ensure` 只在到点那一次动作，同 tick 连调不重复生成（错过的周期不追赶）
  ② **两类周期分工**：换货 = 全量重生成；补货 = 保留未售罄（位置/载荷不变、份数补满）+ 补空位
  ③ **取用不改状态**：份数不够 → False 且簿记一个字节不动；扣到 0 即售罄下架
  ④ **fail-closed**：没 ensure 过 / 簿记坏 / 参数非法 → 抛错点名，不静默当空货架、不静默降级
外加：先到先得（并发不超卖）/ 零游戏词汇（词表取自 tests/test_no_game_vocabulary.py）/ 无后台定时器。
"""
import ast
import copy
import json
import os
import sys
import threading

# ---- 扩展包门禁路径（2026-09-23 从引擎 tests/ 搬到本包）----
# 本文件现在位于 extends/ext_economy/tests/ ⇒ 往上四级才是引擎根
_HERE = os.path.dirname(os.path.abspath(__file__))   # extends/ext_economy/tests
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))   # 引擎根
_EXT_BASE = os.path.join(ROOT, "extends")
for _p in (ROOT, _EXT_BASE, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ext_economy.shelf import Shelf, ShelfFillError, ShelfStateError  # noqa: E402
from test_no_game_vocabulary import GAME_TERMS                            # noqa: E402

passed = failed = 0


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


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


def feeds(payloads, stock=1):
    """造一个按批给新品的 `fill`：每批载荷带批次号（`名字@批号`），便于断言「换了一批」。"""
    box = {"batch": 0}

    def _fill():
        b = box["batch"]
        box["batch"] += 1
        return [{"payload": f"{p}@{b}", "stock": stock} for p in payloads]

    return _fill, box


def payloads(shelf, state):
    return [e["payload"] for e in shelf.items(state)]


# ---------------------------------------------------------------- 1 惰性 / 幂等
def t1_lazy():
    print("\n[1] 惰性 + 幂等：读时推进，同 tick 不重复生成")
    ck = Clock(0)
    fill, box = feeds(["a", "b", "c"])
    sh = Shelf(3, clock=ck, rotate_every=10, restock_every=5, fill=fill)
    s = {}
    check("ensure 返回同一个 state 对象", sh.ensure(s) is s)
    check("首次 ensure 就地建立货架并按 fill 上架",
          payloads(sh, s) == ["a@0", "b@0", "c@0"])
    check("初始剩余 = 满额", [e["left"] for e in sh.items(s)] == [1, 1, 1])
    before = copy.deepcopy(s)
    sh.ensure(s)
    check("★ 同一 tick 连调两次：簿记逐字节不变", s == before, f"{s} != {before}")
    check("★ 同一 tick 连调两次：fill 只被调用一次", box["batch"] == 1, str(box))
    ck.set(4)
    sh.ensure(s)
    check("没到任何一个周期 → 一个字节都不改（fill 也没调）",
          s == before and box["batch"] == 1)
    st = {"keep": 1}
    sh.ensure(st)
    sh.take(st, 0, 1)
    check("引擎只写 state['shelf']，不碰调用方的别的键",
          set(st) == {"shelf", "keep"} and st["keep"] == 1, str(sorted(st)))


# ---------------------------------------------------------------- 2 换货
def t2_rotate():
    print("\n[2] 换货周期到 → 全量重生成（未售罄的也换掉）")
    ck = Clock(0)
    fill, box = feeds(["a", "b"], stock=2)
    sh = Shelf(2, clock=ck, rotate_every=10, fill=fill)
    s = {}
    sh.ensure(s)
    sh.take(s, 0, 1)                                  # 0 号还留着 1 份没卖完
    ck.set(9)
    sh.ensure(s)
    check("差 1 秒不换货（载荷与剩余都不动）",
          payloads(sh, s) == ["a@0", "b@0"] and sh.items(s)[0]["left"] == 1, str(s))
    check("差 1 秒不换货：没白生成一批", box["batch"] == 1, str(box))
    ck.set(10)
    sh.ensure(s)
    check("★ 到点 → 全量重生成（没卖完的 a 也被换掉）", payloads(sh, s) == ["a@1", "b@1"])
    check("换货后剩余补满（含曾被扣过的 0 号）", [e["left"] for e in sh.items(s)] == [2, 2])
    check("换货只生成一批", box["batch"] == 2, str(box))
    before = copy.deepcopy(s)
    sh.ensure(s)
    check("★ 到点那一刻连调两次：不重复生成", s == before and box["batch"] == 2, str(box))
    ck.set(1000)
    sh.ensure(s)
    check("错过多个周期合并成一次（不追赶、不按次数补发）",
          payloads(sh, s) == ["a@2", "b@2"] and box["batch"] == 3, str(box))
    check("换货时刻推进到当前秒（不是按周期加）",
          sh.next_restock_at(s) == 1010, repr(sh.next_restock_at(s)))

    # 两个周期都到点 → 换货优先（整柜重来，而不是只补空位）
    ck2 = Clock(0)
    fill2, _box2 = feeds(["x"], stock=3)
    sh2 = Shelf(1, clock=ck2, rotate_every=5, restock_every=5, fill=fill2)
    s2 = {}
    sh2.ensure(s2)
    sh2.take(s2, 0, 1)
    ck2.set(5)
    sh2.ensure(s2)
    check("★ 两个周期都到点 → 换货优先（全量重生成，剩余补满）",
          payloads(sh2, s2) == ["x@1"] and sh2.items(s2)[0]["left"] == 3)


# ---------------------------------------------------------------- 3 补货
def t3_restock():
    print("\n[3] 补货周期到 → 保留未售罄 + 补满")
    ck = Clock(0)
    fill, box = feeds(["a", "b", "c"], stock=3)
    sh = Shelf(3, clock=ck, restock_every=10, fill=fill)
    s = {}
    sh.ensure(s)
    sh.take(s, 0, 3)                                  # 0 号售罄下架
    sh.take(s, 1, 1)                                  # 1 号剩 2
    check("售罄的 0 号已不在架（items 里没有它）", [e["slot"] for e in sh.items(s)] == [1, 2])
    check("售罄的 0 号在 sold_out 里", [e["slot"] for e in sh.sold_out(s)] == [0])
    ck.set(10)
    sh.ensure(s)
    after = {e["slot"]: e for e in sh.items(s)}
    check("★ 未售罄的 1 / 2 号：载荷不变", (after[1]["payload"], after[2]["payload"])
          == ("b@0", "c@0"), str(after))
    check("★ 未售罄的 1 / 2 号：位置不变", sorted(after) == [0, 1, 2])
    check("★ 未售罄的 1 号：份数补回满额", after[1]["left"] == 3)
    check("★ 售罄的 0 号：同位置补上新品", after[0]["payload"] == "a@1" and after[0]["left"] == 3)
    check("补货只生成一批，且只取需要的那几个新品", box["batch"] == 2, str(box))
    before = copy.deepcopy(s)
    sh.ensure(s)
    check("★ 补货那一刻连调两次：不重复生成", s == before and box["batch"] == 2, str(box))

    # 满架补货：一个新品都不生成
    ck2 = Clock(0)
    fill2, box2 = feeds(["x"], stock=1)
    sh2 = Shelf(1, clock=ck2, restock_every=5, fill=fill2)
    s2 = {}
    sh2.ensure(s2)
    ck2.set(5)
    sh2.ensure(s2)
    check("满架补货：一个新品也不生成（无空位就不问 fill）", box2["batch"] == 1, str(box2))
    check("满架补货：在架件原样保留", payloads(sh2, s2) == ["x@0"])

    # keep_unsold=False：补货等同整柜重来
    ck3 = Clock(0)
    fill3, _box3 = feeds(["p", "q"], stock=2)
    sh3 = Shelf(2, clock=ck3, restock_every=5, fill=fill3, keep_unsold=False)
    s3 = {}
    sh3.ensure(s3)
    sh3.take(s3, 0, 1)
    ck3.set(5)
    sh3.ensure(s3)
    check("★ keep_unsold=False：补货等同整柜重来", payloads(sh3, s3) == ["p@1", "q@1"])
    check("keep_unsold=False：整柜重来 ⇒ 换货时钟也一并推进",
          s3["shelf"]["rotated_at"] == 5, repr(s3["shelf"]["rotated_at"]))


# ---------------------------------------------------------------- 4 取用
def t4_take():
    print("\n[4] 取用：够才扣 / 不够不改状态 / 售罄即下架")
    ck = Clock(0)
    fill, _box = feeds(["a", "b"], stock=2)
    sh = Shelf(2, clock=ck, fill=fill)
    s = {}
    sh.ensure(s)
    check("扣 1 份 → True 且剩余减 1", sh.take(s, 0, 1) is True and sh.items(s)[0]["left"] == 1)
    check("只动点名的那一格", sh.items(s)[1]["left"] == 2)
    check("n 恰好等于剩余 → True", sh.take(s, 0, 1) is True)
    check("★ 扣到 0 即售罄下架（items 里没有它）", [e["slot"] for e in sh.items(s)] == [1])
    check("售罄格进 sold_out 且剩余 0", [(e["slot"], e["left"]) for e in sh.sold_out(s)] == [(0, 0)])
    snap = copy.deepcopy(s)
    check("★ 对已售罄的格子再扣 → False", sh.take(s, 0, 1) is False)
    check("★ False 路径一个字节都不改", s == snap, f"{s} != {snap}")
    check("★ 超库存（1 号剩 2、要 5）→ False", sh.take(s, 1, 5) is False)
    check("★ 超库存不改簿记（剩余仍是 2）", s == snap and sh.items(s)[0]["left"] == 2)
    check("n=2 恰好扣光 → True", sh.take(s, 1, 2) is True)
    check("全售罄 → items 空、sold_out 两个",
          sh.items(s) == [] and [e["slot"] for e in sh.sold_out(s)] == [0, 1])

    # 参数非法
    check("n 非整数 → TypeError", raises(TypeError, sh.take, s, 0, "1")[0]
          and raises(TypeError, sh.take, s, 0, 1.5)[0] and raises(TypeError, sh.take, s, 0, True)[0])
    check("n < 1 → ValueError", raises(ValueError, sh.take, s, 0, 0)[0]
          and raises(ValueError, sh.take, s, 0, -1)[0])
    check("slot 越界 → ValueError（不静默当没货）",
          raises(ValueError, sh.take, s, 2)[0] and raises(ValueError, sh.take, s, -1)[0])
    check("slot 非整数 → TypeError",
          raises(TypeError, sh.take, s, "0")[0] and raises(TypeError, sh.take, s, True)[0])

    # items / sold_out 是快照
    ck2 = Clock(0)
    sh2 = Shelf(1, clock=ck2, fill=feeds(["z"], stock=2)[0])
    s2 = {}
    sh2.ensure(s2)
    got = sh2.items(s2)
    got[0]["left"] = 999
    got[0]["payload"] = "污染"
    check("★ items 返回深拷贝（改返回值不影响簿记）",
          sh2.items(s2)[0]["left"] == 2 and sh2.items(s2)[0]["payload"] == "z@0")
    sh2.take(s2, 0, 2)
    out = sh2.sold_out(s2)
    out[0]["left"] = 7
    check("★ sold_out 返回深拷贝", sh2.sold_out(s2)[0]["left"] == 0)


# ---------------------------------------------------------------- 5 先到先得
def t5_first_come():
    print("\n[5] 先到先得：同一 state 上并发 take 不超卖")
    ck = Clock(0)
    sh = Shelf(1, clock=ck, fill=feeds(["a"], stock=5)[0])
    s = {}
    sh.ensure(s)
    wins = []
    barrier = threading.Barrier(24)

    def worker():
        barrier.wait()
        if sh.take(s, 0, 1):
            wins.append(1)

    ts = [threading.Thread(target=worker) for _ in range(24)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    check("★ 库存 5、24 个线程抢 → 恰好 5 个成功", len(wins) == 5, str(len(wins)))
    check("★ 无超卖：剩余恰好 0（没出现负数）",
          s["shelf"]["slots"][0]["left"] == 0 and sh.items(s) == [])

    sh2 = Shelf(2, clock=Clock(0), fill=feeds(["a", "b"], stock=3)[0])
    s2 = {}
    sh2.ensure(s2)
    wins2 = []
    barrier2 = threading.Barrier(16)

    def worker2(i):
        barrier2.wait()
        if sh2.take(s2, i % 2, 1):
            wins2.append(1)

    ts2 = [threading.Thread(target=worker2, args=(i,)) for i in range(16)]
    for t in ts2:
        t.start()
    for t in ts2:
        t.join()
    check("两格各 3 份、16 个线程抢 → 恰好 6 个成功", len(wins2) == 6, str(len(wins2)))
    check("两格都售罄且不为负",
          [e["left"] for e in sh2.sold_out(s2)] == [0, 0] and sh2.items(s2) == [])


# ---------------------------------------------------------------- 6 周期时刻
def t6_next_restock():
    print("\n[6] next_restock_at：整数秒 / 取最近的一次 / 不配周期 → None")
    ck = Clock(0)
    sh = Shelf(1, clock=ck, rotate_every=100, restock_every=10,
               fill=feeds(["a"], stock=1)[0])
    s = {}
    sh.ensure(s)
    check("两个周期都配 → 取最近的一次", sh.next_restock_at(s) == 10)
    check("返回值是整数秒", isinstance(sh.next_restock_at(s), int))
    sh.take(s, 0, 1)
    ck.set(10)
    sh.ensure(s)
    check("补货后按补货周期重新计时", sh.next_restock_at(s) == 20, repr(sh.next_restock_at(s)))
    ck.set(20)
    sh.ensure(s)
    check("再补一次仍是补货周期（换货时刻没被顶掉）",
          sh.next_restock_at(s) == 30, repr(sh.next_restock_at(s)))

    only_rot = Shelf(1, clock=Clock(7), rotate_every=50, fill=feeds(["a"])[0])
    s3 = {}
    only_rot.ensure(s3)
    check("只配换货 → 换货时刻（换货也是整柜变满）", only_rot.next_restock_at(s3) == 57)

    none_at_all = Shelf(1, clock=Clock(7), fill=feeds(["a"])[0])
    s4 = {}
    none_at_all.ensure(s4)
    check("一个周期都不配 → None", none_at_all.next_restock_at(s4) is None)

    stale = Shelf(1, clock=Clock(0), restock_every=10, fill=feeds(["a"])[0])
    s5 = {}
    stale.ensure(s5)
    stale.clock.set(100)
    check("到点但没 ensure → 返回的是已过去的时刻（不代推进、不撒谎）",
          stale.next_restock_at(s5) == 10 and stale.items(s5)[0]["payload"] == "a@0")


# ---------------------------------------------------------------- 7 fail-closed
def t7_fail_closed():
    print("\n[7] fail-closed：没货架 / 簿记坏 / 参数非法 → 抛错点名")
    ck = Clock(0)
    fill, _box = feeds(["a"], stock=1)
    sh = Shelf(1, clock=ck, fill=fill)
    s = {}
    check("★ 没 ensure 过就读 → ShelfStateError（不静默当空货架）",
          raises(ShelfStateError, sh.items, s)[0]
          and raises(ShelfStateError, sh.sold_out, s)[0]
          and raises(ShelfStateError, sh.next_restock_at, s)[0])
    sh.ensure(s)
    check("ensure 之后读得到", sh.items(s) != [])

    check("簿记写成 None → 报错（不覆盖、不当空）",
          raises(ShelfStateError, sh.ensure, {"shelf": None})[0])
    check("簿记不是映射 → 报错", raises(ShelfStateError, sh.items, {"shelf": [1, 2]})[0])
    check("簿记缺字段 → 报错点名",
          raises(ShelfStateError, sh.items,
                 {"shelf": {"size": 1, "rotated_at": 0, "restocked_at": 0}})[0])
    other = Shelf(2, clock=ck, fill=fill)
    check("★ 换个 slots 构造的货架读旧簿记 → 报错（不按新格子数重解释）",
          raises(ShelfStateError, other.ensure, copy.deepcopy(s))[0])
    broken = copy.deepcopy(s)
    broken["shelf"]["slots"][0]["slot"] = 5
    check("格子错位 → 报错", raises(ShelfStateError, sh.items, broken)[0])
    broken = copy.deepcopy(s)
    broken["shelf"]["slots"][0]["left"] = -1
    check("负剩余 → 报错", raises(ShelfStateError, sh.items, broken)[0])
    broken = copy.deepcopy(s)
    broken["shelf"]["slots"] = []
    check("格子表长度与 size 不符 → 报错", raises(ShelfStateError, sh.items, broken)[0])
    broken = copy.deepcopy(s)
    broken["shelf"]["slots"][0]["left"] = 9
    check("剩余 > 满额（自相矛盾）→ 报错", raises(ShelfStateError, sh.items, broken)[0])
    broken = copy.deepcopy(s)
    broken["shelf"]["slots"][0]["stock"] = 1.5
    check("满额不是整数 → 报错", raises(ShelfStateError, sh.items, broken)[0])
    broken = copy.deepcopy(s)
    del broken["shelf"]["slots"][0]["payload"]
    check("格子缺 payload → 报错", raises(ShelfStateError, sh.items, broken)[0])
    broken = copy.deepcopy(s)
    broken["shelf"]["rotated_at"] = "0"
    check("簿记时刻不是整数 → 报错", raises(ShelfStateError, sh.items, broken)[0])

    ck.set(-1)
    check("★ 时钟倒退 → 报错（不静默不换货、不按错乱时刻算）",
          raises(ShelfStateError, sh.items, s)[0])
    ck.set(0)

    check("时钟给浮点 → 装配即 TypeError（不拖到第一次调用）",
          raises(TypeError, Shelf, 1, clock=lambda: 1.5)[0])
    check("时钟给布尔 → TypeError（布尔不是整数秒）",
          raises(TypeError, Shelf, 1, clock=lambda: True)[0])
    check("时钟给字符串 → TypeError",
          raises(TypeError, Shelf, 1, clock=lambda: "0")[0])
    check("clock 不可调用 → TypeError", raises(TypeError, Shelf, 1, clock=None)[0])
    check("state 不是可读写映射 → TypeError", raises(TypeError, sh.ensure, [])[0])

    check("slots 非整数 → TypeError",
          raises(TypeError, Shelf, "2", clock=ck)[0] and raises(TypeError, Shelf, True, clock=ck)[0])
    check("slots < 1 → ValueError",
          raises(ValueError, Shelf, 0, clock=ck)[0] and raises(ValueError, Shelf, -3, clock=ck)[0])
    check("周期 <= 0 / 非整数 → 报错",
          raises(ValueError, Shelf, 1, clock=ck, fill=fill, rotate_every=0)[0]
          and raises(TypeError, Shelf, 1, clock=ck, fill=fill, rotate_every="10")[0]
          and raises(ValueError, Shelf, 1, clock=ck, fill=fill, restock_every=-1)[0])
    check("★ 配了周期却没有 fill → ValueError（不拖到第一次到点才炸）",
          raises(ValueError, Shelf, 1, clock=ck, restock_every=10)[0]
          and raises(ValueError, Shelf, 1, clock=ck, rotate_every=10)[0])
    check("fill 不是可调用 → TypeError", raises(TypeError, Shelf, 1, clock=ck, fill=[1])[0])
    check("keep_unsold 非 bool → TypeError",
          raises(TypeError, Shelf, 1, clock=ck, fill=fill, keep_unsold=1)[0])

    empty = Shelf(1, clock=Clock(0))
    e = {}
    empty.ensure(e)
    check("不配 fill 也不配周期 → 合法空货架（不是错误）",
          empty.items(e) == [] and empty.sold_out(e) == [] and empty.next_restock_at(e) is None)


# ---------------------------------------------------------------- 8 fill 契约
def t8_fill_contract():
    print("\n[8] fill 契约：产出不合规 → ShelfFillError（不猜、不降级）")
    ck = Clock(0)
    cases = [
        ("不是列表", lambda: {"payload": "a", "stock": 1}),
        ("是字符串", lambda: "payload"),
        ("元素不是映射", lambda: ["a"]),
        ("元素缺 payload", lambda: [{"stock": 1}]),
        ("元素缺 stock", lambda: [{"payload": "a"}]),
        ("stock 为负", lambda: [{"payload": "a", "stock": -1}]),
        ("stock 非整数", lambda: [{"payload": "a", "stock": 1.5}]),
        ("stock 是布尔", lambda: [{"payload": "a", "stock": True}]),
    ]
    for name, fn in cases:
        check(f"fill 产出{name} → ShelfFillError",
              raises(ShelfFillError, Shelf(1, clock=ck, fill=fn).ensure, {})[0])
    check("★ 报错点名第几个新品",
          "第 1 个" in str(raises(ShelfFillError, Shelf(2, clock=ck, fill=lambda: [
              {"payload": "a", "stock": 1}, {"payload": "b"}]).ensure, {})[1]))

    sh = Shelf(2, clock=ck, fill=lambda: [{"payload": i, "stock": 1} for i in range(5)])
    s = {}
    sh.ensure(s)
    check("新品多于格子数 → 取前 N 个（多余忽略）", payloads(sh, s) == [0, 1])
    sh2 = Shelf(3, clock=ck, fill=lambda: [{"payload": "a", "stock": 1}])
    s2 = {}
    sh2.ensure(s2)
    check("新品不足 → 剩余格子留空（不谎报有货）", payloads(sh2, s2) == ["a"])
    check("★ 空位不算售罄（从没上过架 ≠ 卖光了）", sh2.sold_out(s2) == [])

    box = {"n": 1}
    sh3 = Shelf(1, clock=ck, fill=lambda: [{"payload": box, "stock": 1}])
    s3 = {}
    sh3.ensure(s3)
    box["n"] = 999
    check("★ 载荷深拷贝进簿记（改内容侧对象不串）", sh3.items(s3)[0]["payload"]["n"] == 1)

    sh4 = Shelf(1, clock=ck, fill=lambda: [{"payload": "z", "stock": 0}])
    s4 = {}
    sh4.ensure(s4)
    check("stock=0 的新品上架即售罄（在架为空、sold_out 有它）",
          sh4.items(s4) == [] and [e["slot"] for e in sh4.sold_out(s4)] == [0])

    ck5 = Clock(0)
    sh5 = Shelf(2, clock=ck5, restock_every=5,
                fill=lambda: [{"payload": "a", "stock": 1}])
    s5 = {}
    sh5.ensure(s5)
    sh5.take(s5, 0, 1)
    ck5.set(5)
    sh5.ensure(s5)
    check("补货后仍然只有 1 个新品可给 → 另一个格子留空，不编造",
          payloads(sh5, s5) == ["a"])


# ---------------------------------------------------------------- 9 纯度 / 无定时器
def t9_purity():
    print("\n[9] 零知识 / 无后台定时器 / 簿记是纯数据")
    src_path = os.path.join(ROOT, "extends", "ext_economy", "shelf", "__init__.py")
    with open(src_path, encoding="utf-8") as fh:
        src = fh.read()
    low = src.lower()
    hits = [t for t in GAME_TERMS if (t if not t.isascii() else t.lower()) in low]
    check("★ 模块源码零游戏词汇（词表取自 tests/test_no_game_vocabulary.py）",
          not hits, str(hits))

    tree = ast.parse(src)
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            seg = ast.get_source_segment(src, node) or ""
            if seg.lstrip().startswith("from ."):
                continue                          # 相对导入：允许（不指向外部包）
            mods.add((node.module or "").split(".")[0])
    check("只依赖标准库（可分发性；全引擎 AST 断言另见 tests/test_engine_purity.py）",
          mods <= {"__future__", "copy", "threading", "collections", "typing"},
          str(sorted(mods)))
    timers = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ("sleep", "Timer"):
            timers.append(node.attr)
        if isinstance(node, ast.Name) and node.id in ("asyncio", "sched"):
            timers.append(node.id)
    check("★ 不起后台定时器（无 sleep / Timer / asyncio / sched）", not timers, str(timers))

    sh = Shelf(2, clock=Clock(0),
               fill=lambda: [{"payload": {"k": [1, 2]}, "stock": 2}])
    s = {}
    sh.ensure(s)
    sh.take(s, 0, 1)
    check("簿记是 JSON 可序列化的纯数据（不含引擎对象）",
          json.loads(json.dumps(s)) == s)
    check("簿记字段名是通用名（size / rotated_at / restocked_at / slots / left / stock / payload）",
          set(s["shelf"]) == {"size", "rotated_at", "restocked_at", "slots"}
          and set(s["shelf"]["slots"][0]) == {"slot", "left", "stock", "payload"})


def main():
    print("== shelf 门禁：限量货架（惰性 / 两类周期 / 取用 / 售罄下架 / 先到先得 / fail-closed）==")
    t1_lazy()
    t2_rotate()
    t3_restock()
    t4_take()
    t5_first_come()
    t6_next_restock()
    t7_fail_closed()
    t8_fill_contract()
    t9_purity()
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
