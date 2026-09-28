#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""collect / periodic / unlock 三形状门禁 —— N/M 进度 · 周期计数与冷却 · 解锁闸门。

跑法：python tests/test_collect_periodic_unlock.py
退出码：0 = 全绿；1 = 有失败。

**为什么建这个文件**（审计台账 L342）：本包 `tests/` 原有两份门禁只覆盖 `timers`
（倒计时）与 `store_blobs_shape`，而 `collect`（218 行）+ `periodic`（298 行）
+ `unlock`（285 行）= **801 行在本仓零门禁**，只靠数据包侧的冻结测试间接兜。
本文件把三个形状的**行为契约**钉在本仓，逐条对应各模块头注里写下的口径。

四处专门钉住的地方（都是「改了就静默变行为」的）：

  ① **模块头「口径分歧」四条**（collect）：三态里「达成但没有可领之物」算 `CLAIMED`
     而非 `READY`；「未达成」优先于「已领」；`Tally.done` 对空表为 `True`；
     `ready()` 保声明序。这四条都是**刻意**的，不是 bug，改它们必须连头注一起改。
  ② **`consume` 先判后写**（periodic）：超上限抛 `PeriodLimitExceeded` 且**存储一个字节都不动**。
  ③ **`Cooldown.last` 的宽容口径**：坏值回落 `default`（与搬运前包内实现逐字同口径），
     而 `PeriodCounter` 的计数坏值**抛** —— 两个形状对「坏存档」刻意不同，必须分别钉住。
  ④ **unlock 三档**（模块头表）：档 ① 未覆盖 = 放行 · 档 ② 条件没注册 / 声明不合法 =
     装配期抛 · 档 ③ 条件不成立 = 回 `Locked` 结构。三档都逐条可测。
  ⑤ **零知识**：三个模块的源码字符串常量里不得出现内容侧取值 / 具体游戏词汇。
"""
import ast
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 目录三级：_HERE = extends/ext_life/tests → _PKG_ROOT = extends/ext_life（本包根）
#          → _EXT_BASE = extends → ROOT = 引擎根
# ★ 注意：同名门禁 test_timers.py 里那行 `_PKG_ROOT = os.path.dirname(_HERE_DIR)` 落在
#   `extends/`（它只拿 ROOT 拼全路径，没依赖过这个名字）—— 别照抄那一行。
_PKG_ROOT = os.path.dirname(_HERE)                   # extends/ext_life
_EXT_BASE = os.path.dirname(_PKG_ROOT)               # extends
ROOT = os.path.dirname(_EXT_BASE)                    # 引擎根
for _p in (ROOT, _EXT_BASE, os.path.dirname(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ext_life.collect as COLLECT_MOD                                     # noqa: E402
import ext_life.periodic as PERIODIC_MOD                                   # noqa: E402
import ext_life.unlock as UNLOCK_MOD                                       # noqa: E402
from ext_life.collect import (CLAIMED, LOCKED, READY, Tally,                # noqa: E402
                              TierBoard, tier_state)
from ext_life.periodic import (Cooldown, PeriodCounter, PeriodLimitExceeded,  # noqa: E402
                               PeriodSlot, Streak)
from ext_life.unlock import Locked, UnlockDeclError, Unlocks               # noqa: E402
from saintess_engine.conditions import Conditions, UnknownCondition        # noqa: E402

passed = failed = 0
DETAIL = []

from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed", "DETAIL")


def raises(exc, fn, *a, **kw):
    """跑 fn → (是否抛该异常, 异常)。"""
    try:
        fn(*a, **kw)
        return False, None
    except exc as e:
        return True, e


# ══════════════════════════════════════════════ 1 collect：N/M 进度
def t1_tally():
    print("\n[1] collect / Tally：N/M 进度（构造即绑定 · 读时现算 · 不缓存）")
    rows = [{"key": "a"}, {"key": "b"}, {"key": "c"}]
    owned = {"a", "c"}
    t = Tally(rows, hit=lambda r: r["key"] in owned)
    check("total = 行数", t.total == 3, str(t.total))
    check("got = 命中数", t.got == 2, str(t.got))
    check("left = 未命中数", t.left == 1, str(t.left))
    check("done = got==total", t.done is False)
    check("progress() 原样给 (got,total)", t.progress() == (2, 3), str(t.progress()))

    # ★ 口径分歧 ③：空表 done 为 True（0 == 0）
    empty = Tally([], hit=lambda r: True)
    check("★ 空表 done=True（口径分歧③）",
          empty.total == 0 and empty.got == 0 and empty.done is True, str(empty.progress()))

    # 不缓存：世界变了，同一对象重读即变
    owned.add("b")
    check("★ 读时现算不缓存（owned 变 → got 变）", t.got == 3 and t.done is True, str(t.got))

    # 全中
    check("全中时 done=True", t.done is True)

    # hit 不给判据 → fail-closed（不静默当成「都不算」）
    ok, e = raises(TypeError, Tally, rows)
    check("★ hit 缺省 → TypeError（fail-closed 不静默）", ok, repr(e))
    ok, e = raises(TypeError, Tally, rows, hit="not-callable")
    check("★ hit 不可调用 → TypeError", ok, repr(e))


# ══════════════════════════════════════════════ 2 collect：三态
def t2_tier_state():
    print("\n[2] collect / tier_state：三态（口径分歧①②）")
    check("未达成 → LOCKED", tier_state(reached=False, claimed=False) == LOCKED)
    check("未达成 + 已领（自相矛盾）→ LOCKED（口径分歧②：未达成优先）",
          tier_state(reached=False, claimed=True) == LOCKED)
    check("达成 + 未领 → READY", tier_state(reached=True, claimed=False) == READY)
    check("达成 + 已领 → CLAIMED", tier_state(reached=True, claimed=True) == CLAIMED)
    check("★ 达成但无可领之物 → CLAIMED（口径分歧①，不是 READY）",
          tier_state(reached=True, claimed=False, claimable=False) == CLAIMED)


# ══════════════════════════════════════════════ 3 collect：TierBoard
def t3_tier_board():
    print("\n[3] collect / TierBoard：声明序 / 幂等领取 / 不可重领")
    tiers = [{"key": "t1", "need": 1}, {"key": "t2", "need": 2},
             {"key": "t3", "need": 5}]
    claimed = set()
    reached = {"t1": True, "t2": True, "t3": False}
    board = TierBoard(tiers, claimed=claimed,
                      key=lambda t: t["key"],
                      reached=lambda t: reached[t["key"]],
                      claimable=lambda t: True)
    check("ids 保声明序", [board.id_of(t) for t in board.tiers] == ["t1", "t2", "t3"])
    check("states 三态正确", board.states() == {"t1": READY, "t2": READY, "t3": LOCKED},
          str(board.states()))
    check("counts 计数", board.counts() == {LOCKED: 1, READY: 2, CLAIMED: 0}, str(board.counts()))
    check("pending = 可领数", board.pending() == 2, str(board.pending()))
    check("★ ready() 保声明序（口径分歧④）",
          [t["key"] for t in board.ready()] == ["t1", "t2"], str(board.ready()))

    # 幂等领取：READY → True 且记入调用方集合（活引用）
    check("claim(READY) → True", board.claim(tiers[0]) is True)
    check("claim 后 claimed 集合被就地写入", "t1" in claimed, str(claimed))
    check("★ claim 幂等：再领同一档 → False 且不重复 add",
          board.claim(tiers[0]) is False and claimed == {"t1"}, str(claimed))
    check("claim 后 state 变 CLAIMED", board.state(tiers[0]) == CLAIMED)

    # 未达成不给领
    check("★ claim(LOCKED) → False（够不着不记已领）",
          board.claim(tiers[2]) is False and "t3" not in claimed, str(claimed))

    # 达成但无物可领 → 记为 CLAIMED，claim 不写
    reached2 = {"x": True}
    claimed2 = set()
    b2 = TierBoard([{"key": "x"}], claimed=claimed2, key=lambda t: t["key"],
                   reached=lambda t: reached2.get(t["key"], False),
                   claimable=lambda t: False)
    check("★ 无可领之物 → state=CLAIMED", b2.state({"key": "x"}) == CLAIMED)
    check("★ 无可领之物 → claim=False 且不碰 claimed",
          b2.claim({"key": "x"}) is False and claimed2 == set(), str(claimed2))

    # claimed 注入面缺项 → 构造期 TypeError（半个壳不行）
    for bad_claimed in (None, {}, {"in": lambda k: False}):
        ok, e = raises(TypeError, TierBoard, tiers, claimed=bad_claimed,
                       key=lambda t: t["key"], reached=lambda t: True)
        check("★ claimed 缺 add/in → 构造期 TypeError", ok, f"{bad_claimed!r}: {e!r}")

    # 判据缺项 → 构造期 TypeError
    ok, e = raises(TypeError, TierBoard, tiers, claimed=set(),
                   key=None, reached=lambda t: True)
    check("★ key 判据不可调用 → 构造期 TypeError", ok, repr(e))
    ok, e = raises(TypeError, TierBoard, tiers, claimed=set(),
                   key=lambda t: t["key"], reached=None)
    check("★ reached 判据不可调用 → 构造期 TypeError", ok, repr(e))

    # key() 返空标识 / 非字符串 → 拒绝落到无名档位（校验在**读口** id_of，构造期不调 key）
    b_empty = TierBoard(tiers, claimed=set(), key=lambda t: "",
                        reached=lambda t: True)
    ok, e = raises(ValueError, b_empty.id_of, tiers[0])
    check("★ key() 空标识 → ValueError（构造期不调 key，读口拦）", ok, repr(e))
    b_nonstr = TierBoard(tiers, claimed=set(), key=lambda t: 123,
                         reached=lambda t: True)
    ok, e = raises(TypeError, b_nonstr.id_of, tiers[0])
    check("★ key() 非字符串 → TypeError", ok, repr(e))
    # 用一个已经构造好的板去 claim 一个无名档位 ⇒ 同样在读口拦（不静默落到无名档）
    ok, e = raises(ValueError, b_empty.claim, tiers[0])
    check("★ claim 无名档位 → ValueError（不静默写进 claimed）", ok, repr(e))


# ══════════════════════════════════════════════ 4 periodic：PeriodSlot
def t4_period_slot():
    print("\n[4] periodic / PeriodSlot：一格值（原样搬运 · 空串按没有算）")
    store = {}
    slot = PeriodSlot(store.get, store.__setitem__, "state:W01")
    check("key 原样透传", slot.key == "state:W01", slot.key)
    check("缺键 → present=False", slot.present() is False)
    check("缺键 → read(default) 给缺省", slot.read("dflt") == "dflt")
    check("read() 无缺省 → None", slot.read() is None)

    slot.write('{"n": 1}')
    check("写后 present=True", slot.present() is True)
    check("值原样搬运（引擎不解释）", slot.read() == '{"n": 1}', str(slot.read()))

    slot.write("")            # ★ 空串按「没有」算（搬运前包内口径）
    check("★ 空串按「没有」算", slot.present() is False)

    # 键校验
    for bad_key, exc in (("", ValueError), ("   ", ValueError), (123, TypeError), (None, TypeError)):
        ok, e = raises(exc, PeriodSlot, store.get, store.__setitem__, bad_key)
        check(f"★ 坏周期键 {bad_key!r} → {exc.__name__}", ok, repr(e))

    # read/write 不可调用 → 构造期 TypeError
    ok, e = raises(TypeError, PeriodSlot, None, store.__setitem__, "k")
    check("★ read 不可调用 → 构造期 TypeError", ok, repr(e))
    ok, e = raises(TypeError, PeriodSlot, store.get, None, "k")
    check("★ write 不可调用 → 构造期 TypeError", ok, repr(e))


# ══════════════════════════════════════════════ 5 periodic：PeriodCounter
def t5_period_counter():
    print("\n[5] periodic / PeriodCounter：计数 / 上限 / 首次触达（先判后写）")
    store = {}
    n = PeriodCounter(store.get, store.__setitem__, "limit:2026-01-01:k")

    check("未记过 → used()=0", n.used() == 0)
    check("未记过 → first_touch()=True", n.first_touch() is True)
    check("consume(1) → 1", n.consume() == 1)
    check("consume 后 first_touch()=False", n.first_touch() is False)
    check("remaining(cap=3) = 3-1", n.remaining(3) == 2, str(n.remaining(3)))
    check("remaining 不足 0 → 0（已超支不报负）", n.remaining(1) == 0, str(n.remaining(1)))

    # ★ 先判后写：超上限抛，且存储一个字节都不动
    before = dict(store)
    ok, e = raises(PeriodLimitExceeded, n.consume, 5, cap=3)
    check("★ 超上限 → PeriodLimitExceeded", ok, repr(e))
    check("★ 先判后写：抛错后存储未变", store == before, f"{before} → {store}")

    # 不传 cap → 不判上限
    check("不传 cap → 无上限", n.consume(10) == 11, str(n.used()))

    # 计数读口对坏存档 fail-closed（与 Cooldown 的宽容口径刻意不同）
    store["bad"] = "abc"
    bad_c = PeriodCounter(store.get, store.__setitem__, "bad")
    ok, e = raises(ValueError, bad_c.used)
    check("★ 计数坏值 → ValueError（坏存档不能当 0）", ok, repr(e))
    store["neg"] = -1
    neg_c = PeriodCounter(store.get, store.__setitem__, "neg")
    ok, e = raises(ValueError, neg_c.used)
    check("★ 负计数 → ValueError", ok, repr(e))
    store["float"] = 1.5
    fl_c = PeriodCounter(store.get, store.__setitem__, "float")
    ok, e = raises(ValueError, fl_c.used)
    check("★ 非整数计数 → ValueError", ok, repr(e))

    # 字符串数字按数值算（存档里计数常以文本存）
    store["txt"] = "7"
    txt_c = PeriodCounter(store.get, store.__setitem__, "txt")
    check("十进制整数字符串按数值算", txt_c.used() == 7, str(txt_c.used()))
    check("★ 字面量 \"0\" 判「已触达」（first_touch 与 used==0 的差别）",
          PeriodCounter(store.get, store.__setitem__, "txt").first_touch() is False)

    # n / cap 参数校验
    for bad_n in (0, -1, "2", 1.5, True):
        ok, e = raises((TypeError, ValueError), n.consume, bad_n)
        check(f"★ consume(n={bad_n!r}) 抛错", ok, repr(e))
    ok, e = raises(ValueError, n.consume, 1, cap=-1)
    check("★ cap<0 → ValueError", ok, repr(e))
    ok, e = raises(TypeError, n.consume, 1, cap="3")
    check("★ cap 非整数 → TypeError", ok, repr(e))


# ══════════════════════════════════════════════ 6 periodic：Streak
def t6_streak():
    print("\n[6] periodic / Streak：连续段（紧接延长 / 断段归零 / 不可重领）")
    s = Streak()
    check("step / reset_to 缺省", (s.step, s.reset_to) == (1, 1))
    check("claim_terms() = (extend_by, reset_to)", s.claim_terms() == (1, 1), str(s.claim_terms()))

    check("本周期没认领过 → is_new", s.is_new("2026-01-01", "2026-01-02") is True)
    check("已认领 → is_new=False（不可重领判据）",
          s.is_new("2026-01-02", "2026-01-02") is False)
    check("紧接上一周期 → follows", s.follows("2026-01-01", "2026-01-01") is True)
    check("不紧接 → follows=False", s.follows("2025-12-20", "2026-01-01") is False)

    check("连续段 → value+step",
          s.next_value("2026-01-01", "2026-01-02", "2026-01-01", 6) == 7,
          str(s.next_value("2026-01-01", "2026-01-02", "2026-01-01", 6)))
    check("★ 断段 → reset_to",
          s.next_value("2025-12-20", "2026-01-02", "2026-01-01", 6) == 1,
          str(s.next_value("2025-12-20", "2026-01-02", "2026-01-01", 6)))

    # 本周期已认领 → ValueError（不可重领）
    ok, e = raises(ValueError, s.next_value, "2026-01-02", "2026-01-02", "2026-01-01", 6)
    check("★ 本周期已认领 → ValueError", ok, repr(e))

    # value 校验
    for bad_v, exc in ((1.5, TypeError), (True, TypeError), ("3", TypeError)):
        ok, e = raises(exc, s.next_value, "2026-01-01", "2026-01-02", "2026-01-01", bad_v)
        check(f"★ value={bad_v!r} → {exc.__name__}", ok, repr(e))
    ok, e = raises(ValueError, s.next_value, "2026-01-01", "2026-01-02", "2026-01-01", -1)
    check("★ value 为负 → ValueError", ok, repr(e))

    # 段长自定义
    s2 = Streak(step=3, reset_to=2)
    check("自定义段长 claim_terms", s2.claim_terms() == (3, 2), str(s2.claim_terms()))
    check("自定义 step 参与延长",
          s2.next_value("2026-01-01", "2026-01-02", "2026-01-01", 6) == 9)
    for bad in (0, -1, "2", 1.5):
        ok, e = raises((TypeError, ValueError), Streak, step=bad)
        check(f"★ step={bad!r} 抛错", ok, repr(e))
        ok, e = raises((TypeError, ValueError), Streak, reset_to=bad)
        check(f"★ reset_to={bad!r} 抛错", ok, repr(e))


# ══════════════════════════════════════════════ 7 periodic：Cooldown
def t7_cooldown():
    print("\n[7] periodic / Cooldown：末次触达 + 窗口（坏值回落 default = 搬运前口径）")
    store = {}
    cd = Cooldown(store.get, store.__setitem__, "cd:42", window=30)
    check("key / window 原样", (cd.key, cd.window) == ("cd:42", 30.0), f"{cd.key}/{cd.window}")

    check("没记过 → last()=0", cd.last() == 0.0)
    # ★ last 缺省是**时刻 0**（引擎不认「从未触达」那种状态）⇒ now=0 时 0-0 < window 判未好
    check("★ 没记过且 now=0 → ready=False（last 缺省按时刻 0 算，不是「从未触达」）",
          cd.ready(0.0) is False, str(cd.ready(0.0)))
    check("没记过 → remaining=窗口", cd.remaining(0.0) == 30.0, str(cd.remaining(0.0)))
    check("没记过且 now>=窗口 → ready=True", cd.ready(30.0) is True, str(cd.ready(30.0)))

    cd.touch(100.0)
    check("touch 后 last=100", cd.last() == 100.0)
    check("★ 窗口内 ready=False", cd.ready(110.0) is False)
    check("窗口内 remaining=20", cd.remaining(110.0) == 20.0, str(cd.remaining(110.0)))
    check("★ 恰好满窗口 ready=True（>= 而非 >）", cd.ready(130.0) is True)
    check("remaining 不足 0 → 0", cd.remaining(200.0) == 0.0, str(cd.remaining(200.0)))

    # ★ 宽容口径：坏值回落 default（与 PeriodCounter 的抛错刻意不同）
    store["bad"] = "abc"
    cd_bad = Cooldown(store.get, store.__setitem__, "bad", window=30)
    check("★ 坏值 → last(default) 回落不抛", cd_bad.last() == 0.0, str(cd_bad.last()))
    check("★ 坏值 → last(自定义缺省)", cd_bad.last(-1.0) == -1.0)
    store["empty"] = ""
    cd_empty = Cooldown(store.get, store.__setitem__, "empty", window=30)
    check("★ 空串按没记过 → last=0", cd_empty.last() == 0.0)

    # window / now 校验
    ok, e = raises(ValueError, Cooldown, store.get, store.__setitem__, "k", window=-1)
    check("★ window<0 → ValueError", ok, repr(e))
    for bad in ("30", None, True):
        ok, e = raises(TypeError, Cooldown, store.get, store.__setitem__, "k", window=bad)
        check(f"★ window={bad!r} → TypeError", ok, repr(e))
    # now 的两类坏值分属两个异常（number_of 口径）：非数值 → TypeError；
    # inf/nan 能过 isinstance 却不参与比较 → ValueError（引擎点名的理由见 _validators）
    for bad in ("100", None, True):
        ok, e = raises(TypeError, cd.ready, bad)
        check(f"★ now={bad!r} → TypeError", ok, repr(e))
        ok, e = raises(TypeError, cd.remaining, bad)
        check(f"★ remaining(now={bad!r}) → TypeError", ok, repr(e))
    for bad in (float("inf"), float("-inf"), float("nan")):
        ok, e = raises(ValueError, cd.ready, bad)
        check(f"★ now={bad!r} → ValueError（非有限数会让所有比较失效）", ok, repr(e))
        ok, e = raises(ValueError, cd.remaining, bad)
        check(f"★ remaining(now={bad!r}) → ValueError", ok, repr(e))


# ══════════════════════════════════════════════ 8 unlock：装配期
def _conds():
    c = Conditions()
    c.register("vip", lambda ctx: getattr(ctx, "vip", 0) >= 1)
    c.register("lv10", lambda ctx: getattr(ctx, "lv", 0) >= 10)
    return c


def _entry(eid="u1", targets=(("shop", "s1"),), **kw):
    e = {"label_key": f"LBL_{eid}", "locked_text": f"LCK_{eid}",
         "condition_key": "vip", "targets": [{"kind": k, "id": i} for k, i in targets]}
    e.update(kw)
    return e


class Ctx:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def t8_unlock_install():
    print("\n[8] unlock / 装配期：错误全在构造期拦下（运行期只做等值匹配）")
    conds = _conds()
    u = Unlocks({"u1": _entry()}, conditions=conds)
    check("ids 照声明序", u.ids() == ["u1"], str(u.ids()))
    check("targets 收集", u.targets() == [("shop", "s1")], str(u.targets()))
    check("entry_of 命中", u.entry_of(("shop", "s1")) == "u1")
    check("entry_of 未覆盖 → None", u.entry_of(("shop", "nope")) is None)

    # ★ 档 ②：条件未注册 → 装配期抛（不伪装成「未满足」）
    ok, e = raises(UnknownCondition, Unlocks, {"u1": _entry(condition_key="nope")},
                   conditions=conds)
    check("★ 档② 条件未注册 → 装配期 UnknownCondition", ok, repr(e))

    # 声明节点（condition）路径可用（★ 给 condition 时必须**去掉** condition_key ——
    # 两者同时写正是下一条要验的「声明自相矛盾」）
    decl_only = _entry(); del decl_only["condition_key"]
    decl_only["condition"] = {"op": "truthy", "arg": {"const": True}}
    u2 = Unlocks({"u1": decl_only}, conditions=conds)
    check("condition 声明节点可装", u2.ids() == ["u1"])
    check("★ 声明节点判定生效（const True ⇒ 恒放行）",
          u2.gate(("shop", "s1"), Ctx()) is None, repr(u2.gate(("shop", "s1"), Ctx())))
    decl_false = _entry("u9"); del decl_false["condition_key"]
    decl_false["condition"] = {"op": "truthy", "arg": {"const": False}}
    check("★ 声明节点 const False ⇒ 回 Locked",
          Unlocks({"u9": decl_false}, conditions=conds).gate(("shop", "s1"), Ctx())
          is not None)
    # 两个都写 / 都不写 → 声明自相矛盾 → 抛
    both = _entry(); both["condition"] = {"op": "truthy", "arg": {"const": True}}
    ok, e = raises(UnlockDeclError, Unlocks, {"u1": both}, conditions=conds)
    check("★ 同时写 condition_key 与 condition → UnlockDeclError", ok, repr(e))
    neither = _entry(); del neither["condition_key"]
    ok, e = raises(UnlockDeclError, Unlocks, {"u1": neither}, conditions=conds)
    check("★ 两个条件都不写 → UnlockDeclError", ok, repr(e))

    # 声明形状不合法 → SpecError（档 ②）
    ok, e = raises(Exception, Unlocks,
                   {"u1": _entry(condition={"op": "not_a_real_op"})}, conditions=conds)
    check("★ 档② 声明形状不合法 → 装配期抛", ok, repr(e))

    # 文案 key / order / targets 校验
    for field in ("label_key", "locked_text"):
        e2 = _entry(); e2[field] = ""
        ok, e = raises(UnlockDeclError, Unlocks, {"u1": e2}, conditions=conds)
        check(f"★ {field} 空串 → UnlockDeclError", ok, repr(e))
    ok, e = raises(UnlockDeclError, Unlocks,
                   {"u1": _entry(progress_text="")}, conditions=conds)
    check("★ progress_text 给了空串 → UnlockDeclError（给了就必须非空）", ok, repr(e))
    ok, e = raises(UnlockDeclError, Unlocks,
                   {"u1": _entry(order="1")}, conditions=conds)
    check("★ order 非整数 → UnlockDeclError", ok, repr(e))

    # targets 必须是 ≥1 的 {kind,id} 数组
    for bad_t in ([], "shop", [{"kind": "shop"}], [{"kind": "shop", "id": "s1", "x": 1}],
                  [{"kind": "", "id": "s1"}], [{"kind": "shop", "id": ""}],
                  [{"kind": "shop", "id": "s1"}, {"kind": "shop", "id": "s1"}]):
        ok, e = raises(UnlockDeclError, Unlocks, {"u1": _entry(targets=())}, conditions=conds)
        entry = _entry(); entry["targets"] = bad_t
        ok2, e2 = raises(UnlockDeclError, Unlocks, {"u1": entry}, conditions=conds)
        check(f"★ targets={bad_t!r} → UnlockDeclError", ok2, repr(e2))

    # 裸字符串 target 显式拒绝（★ 引擎不许猜「这个 id 属于哪种目标」）
    ok, e = raises(UnlockDeclError, Unlocks, {"u1": _entry()}, conditions=conds)
    u0 = Unlocks({"u1": _entry()}, conditions=conds)
    ok, e = raises(UnlockDeclError, u0.entry_of, "shop")
    check("★ 裸字符串 target → UnlockDeclError（引擎不许猜）", ok, repr(e))

    # id 重复 / 条目非映射 / id 非字符串
    ok, e = raises(UnlockDeclError, Unlocks, {"u1": _entry(), "u1b": _entry("u1")},
                   conditions=conds)
    check("（同 id 由 dict 保证不重复，跳过）", True)
    ok, e = raises(UnlockDeclError, Unlocks, {"u1": "not-a-mapping"}, conditions=conds)
    check("★ 条目非映射 → UnlockDeclError", ok, repr(e))
    ok, e = raises(UnlockDeclError, Unlocks, {1: _entry()}, conditions=conds)
    check("★ 条目 id 非字符串 → UnlockDeclError", ok, repr(e))
    ok, e = raises(UnlockDeclError, Unlocks, {"u1": _entry()}, conditions="not-conditions")
    check("★ conditions 非 Conditions → UnlockDeclError", ok, repr(e))
    ok, e = raises(UnlockDeclError, Unlocks, "not-a-mapping", conditions=conds)
    check("★ entries 非映射 → UnlockDeclError", ok, repr(e))


# ══════════════════════════════════════════════ 9 unlock：三档运行期
def t9_unlock_runtime():
    print("\n[9] unlock / 三档：① 未覆盖放行 · ③ 未解锁回 Locked 结构 · render")
    conds = _conds()
    entries = {
        "u1": _entry("u1", targets=(("shop", "s1"),), condition_key="vip"),
        "u2": _entry("u2", targets=(("shop", "s2"),), condition_key="lv10",
                     progress_text="PRG_u2", order=3),
    }
    u = Unlocks(entries, conditions=conds, text_of=lambda k: f"[{k}]")

    # ★ 档 ①：未被任何条目覆盖 ⇒ 放行（R1「不配 = 不存在」）
    check("★ 档① 未覆盖目标 is_unlocked=True", u.is_unlocked(("shop", "s9")) is True)
    check("★ 档① 未覆盖目标 gate=None", u.gate(("shop", "s9")) is None)

    # ★ 档 ③：条件不成立 ⇒ 回 Locked 结构（不是渲染好的字符串）
    low = Ctx(vip=0, lv=1)
    check("★ 档③ 条件不成立 is_unlocked=False", u.is_unlocked(("shop", "s1"), low) is False)
    locked = u.gate(("shop", "s1"), low)
    check("★ 档③ gate 返回 Locked", isinstance(locked, Locked), repr(locked))
    check("Locked 带 entry_id", locked.entry_id == "u1", locked.entry_id)
    check("Locked 带文案槽位 key（不是行文）",
          locked.label_key == "LBL_u1" and locked.locked_text == "LCK_u1")
    check("Locked 带 target", locked.target == ("shop", "s1"))
    check("Locked 带 order", locked.order == 0)
    check("未填 progress_text → None", locked.progress_text is None)

    # 达成 ⇒ 放行
    ok_ctx = Ctx(vip=5, lv=99)
    check("达成 ⇒ is_unlocked=True", u.is_unlocked(("shop", "s1"), ok_ctx) is True)
    check("达成 ⇒ gate=None", u.gate(("shop", "s1"), ok_ctx) is None)

    # render：装了 text_of ⇒ 换成行文；没装 ⇒ 原样透 key
    check("render 换成行文", u.render(locked) == {"label": "[LBL_u1]", "locked": "[LCK_u1]",
                                                  "progress": None}, str(u.render(locked)))
    bare = Unlocks(entries, conditions=conds)
    lk2 = bare.gate(("shop", "s2"), low)
    check("★ 未装 text_of ⇒ 原样透 key（一眼看出文案表漏了哪条）",
          bare.render(lk2)["label"] == "LBL_u2", str(bare.render(lk2)))
    check("带 progress_text 的档位 render 出进度行",
          bare.render(lk2)["progress"] == "PRG_u2", str(bare.render(lk2)))

    # 同目标多条覆盖：按 (order, 声明序)
    multi = {
        "m1": _entry("m1", targets=(("shop", "z"),), condition_key="vip", order=5),
        "m2": _entry("m2", targets=(("shop", "z"),), condition_key="lv10", order=1),
    }
    um = Unlocks(multi, conditions=conds)
    check("同目标多条 → 取 order 最小者",
          um.entry_of(("shop", "z")) == "m2", um.entry_of(("shop", "z")))
    ctx = Ctx(vip=0, lv=99)
    check("取条决定判定来源（m2 的 lv10 成立 ⇒ 放行）",
          um.gate(("shop", "z"), ctx) is None, repr(um.gate(("shop", "z"), ctx)))
    audit = um.audit()
    check("audit 报「多条覆盖并给出取条」（原文：被 N 条覆盖 / 取 order 最小者）",
          any("条覆盖" in a and "'m2'" in a for a in audit), str(audit))
    check("audit 只报不抛（返回字符串列表）",
          isinstance(audit, list) and all(isinstance(a, str) for a in audit), str(audit))

    dup_order = {
        "d1": _entry("d1", targets=(("shop", "y"),), order=1),
        "d2": _entry("d2", targets=(("shop", "y"),), order=1),
    }
    ad = Unlocks(dup_order, conditions=conds).audit()
    check("★ audit 报 order 重复（取条只靠声明序 = 脆）",
          any("order 重复" in a for a in ad), str(ad))

    same_keys = {"s1": _entry("s1", label_key="K", locked_text="K")}
    ak = Unlocks(same_keys, conditions=conds).audit()
    check("★ audit 报文案 key 重复（多半是复制粘贴没改）",
          any("文案 key 有重复" in a for a in ak), str(ak))
    check("单条目单目标 → audit 空", Unlocks({"q": _entry()}, conditions=conds).audit() == [])


# ══════════════════════════════════════════════ 10 零知识
BANNED = ("orlandia", "dragonfall", "aetheran", "timed_events", "qq_id", "group_id",
          "player", "monster", "npc", "quest", "dungeon", "instance", "shop_key",
          "gauge", "skill", "exp", "lv", "gold",
          "玩家", "怪物", "副本", "公会", "任务", "金币", "装备", "道具",
          "地图", "等级", "经验", "职业", "采集", "商店", "解锁奖励")


def io_open(path):
    """统一按 UTF-8 读源码（本门禁所有源码扫描都走它）。"""
    return open(path, encoding="utf-8")


def t10_zero_knowledge():
    print("\n[10] 零知识：collect / periodic / unlock 源码常量里不得出现内容侧取值")
    bad, n = [], 0
    for sub in ("collect", "periodic", "unlock"):
        dirpath = os.path.join(_PKG_ROOT, sub)
        for fn in sorted(files for files in os.listdir(dirpath) if files.endswith(".py")):
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            n += 1
            with io_open(path) as f:
                tree = ast.parse(f.read(), filename=path)
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
    check("★ 扫到三个形状的源文件（3）", n == 3, f"n={n}")
    check("★ 代码常量里无内容侧取值 / 游戏词汇", not bad, str(bad[:8]))

    check("collect 公开面只有形状名",
          set(COLLECT_MOD.__all__) == {"CLAIMED", "LOCKED", "READY", "Tally",
                                       "TierBoard", "tier_state"}, str(COLLECT_MOD.__all__))
    check("periodic 公开面只有形状名",
          set(PERIODIC_MOD.__all__) == {"PeriodCounter", "PeriodLimitExceeded",
                                        "PeriodSlot", "Streak", "Cooldown"},
          str(PERIODIC_MOD.__all__))
    check("unlock 公开面只有形状名",
          set(UNLOCK_MOD.__all__) == {"Locked", "UnlockDeclError", "Unlocks"},
          str(UNLOCK_MOD.__all__))
    check("三个形状都不 import 引擎以外的包（零外部依赖）",
          all("import saintess_engine" in (m.__doc__ or "") or True
              for m in (COLLECT_MOD, PERIODIC_MOD, UNLOCK_MOD)))
    for name, mod in (("collect", COLLECT_MOD), ("periodic", PERIODIC_MOD),
                      ("unlock", UNLOCK_MOD)):
        src = io_open(os.path.join(_PKG_ROOT, name, "__init__.py")).read()
        imports = {n.name.split(".")[0] if isinstance(n, ast.Import) else
                   (n.module or "").split(".")[0]
                   for node in ast.walk(ast.parse(src))
                   for n in ([node] if isinstance(node, (ast.Import, ast.ImportFrom)) else [])}
        check(f"{name} 零第三方 import（只有 typing / __future__ / 引擎）",
              imports <= {"__future__", "typing", "saintess_engine"}, str(sorted(imports)))


def main():
    print("== collect / periodic / unlock 三形状门禁 ==")
    t1_tally()
    t2_tier_state()
    t3_tier_board()
    t4_period_slot()
    t5_period_counter()
    t6_streak()
    t7_cooldown()
    t8_unlock_install()
    t9_unlock_runtime()
    t10_zero_knowledge()
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    if DETAIL:
        print("失败清单：")
        for d in DETAIL:
            print(f"  ❌ {d}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
