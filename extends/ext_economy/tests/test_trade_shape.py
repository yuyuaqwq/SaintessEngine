#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""trade 门禁：交易形状（每日限购 / 成交结算 / 折价换算）+ 有牙反证。

跑法：python tests/test_trade_shape.py
退出码：0 = 全绿；1 = 有失败。

判据（对应作业书 §5，逐条打原始输出）
--------------------------------------
 ① 同值：`settle_sale` ↔ 包内 `content/shop.py` 的出售结算 —— **真调** `sell_one`
    （宿主面用假件注入，只替换取款/取效果两个外部面），6 组输入两边都打印
 ② 跨日重置：`today` 指向次日 → `used` 归零；反证：`today` 固定 → 累计不归零
 ③ 超限：cap=3 第 4 次 → `DailyLimitExceeded`，且 state 未变（前 3 次正常）
 ④ 回调：`on_change` 恰好 1 次（计数器），且净额为参数
 ⑤ `apply_rate`：用包内 `pawn_rate`/`PAWN_RATES` **真取到的折价率**逐例等值；floor 生效
 ⑥ 零知识：模块源码无具体游戏词汇（原文 grep + AST 常量双判据）
 ⑦ 反证：把实现改坏 6 处（类型守卫 / 上限守卫 / 下限 / 当日键 / 折价 floor / fail-closed），
    断言必须报红 —— 每处都成对：真模块守卫成立（探针 False）→ 改坏后探针 True

⚠ 反证是**进程内突变**：读模块源码、按锚点改坏、exec 到独立命名空间再跑探针；
锚点找不到即报红（防「反证变成空转」）。真模块（磁盘上的那份）只读不改。
"""
import ast
import importlib
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

from ext_economy.trade import (DailyLimit, DailyLimitExceeded, SaleResult,   # noqa: E402
                                   apply_rate, settle_sale)
import ext_economy.trade as trade                                          # noqa: E402

passed = failed = 0


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


# ════════════════════════════════════════════════════════ 包内真件（宿主面假件注入）
def load_pkg_shop():
    """import 包内 `content/shop.py`，只注入两个**外部面**假件：
    `C.mount_effects`（内容侧效果）与 `db.sell_item_atomic`（存档落库）。
    折价率 / 材料表 / 经济配置全部用包内真件 —— 比对的是真的那条算式。
    """
    pkg_root = os.path.join(ROOT, "games", "orlandia")
    for p in (pkg_root, ROOT):
        if p not in sys.path:
            sys.path.insert(0, p)
    import content.economy_host as economy_host

    class _FakeC:
        @staticmethod
        def mount_effects(player):
            return {}

    class _FakeDB:
        def __init__(self):
            self.calls = []

        def sell_item_atomic(self, group_id, qq_id, key, count, gold):
            self.calls.append((key, count, gold))
            return True

    fake_db = _FakeDB()
    economy_host.bind_host(C=_FakeC, db=fake_db)
    import content.shop as shop
    return shop, fake_db


_PLAYER = {"name": "tester", "gold": 0, "level": 1}


def pkg_sell_one(shop, price, rate, qty, *, slot=None, name="zzz-not-in-roster"):
    """真调包内 `shop.sell_one`（返回 (名, 件数, 实收) 或 None）。"""
    data = {"name": name, "price": price, "type": "x"}
    if slot:
        data["slot"] = slot
    it = {"key": "k1", "count": qty, "data": data}
    try:
        return shop.sell_one("g1", "q1", _PLAYER, it, rate)
    except Exception as exc:                                   # noqa: BLE001
        return f"EXC:{exc!r}"


def gold_of(out):
    """包内返回 `(名, 件数, 实收)` 或 `None`（= 拒绝成交）。"""
    return None if not isinstance(out, tuple) else out[2]


# ════════════════════════════════════════════════════════ ① 同值
def t1_same_values():
    print("\n[1] 同值：settle_sale ↔ 包内 content/shop.py 的出售结算（真调 sell_one）")
    try:
        shop, fake_db = load_pkg_shop()
    except Exception as exc:                                   # noqa: BLE001
        check("★ 包内 content/shop.py 可 import（比对必须有真件，不许静默跳过）", False,
              f"{exc!r}")
        return
    check("★ 包内 content/shop.py 可 import（比对必须有真件，不许静默跳过）", True)

    # 折价率真取（不是抄常数）：包内 pawn_rate 给的两个档
    rate_consumable = shop.pawn_rate(_PLAYER, {"name": "zzz-not-in-roster", "type": "x"})
    rate_equip = shop.pawn_rate(_PLAYER, {"slot": "x"}, is_smith_shop_=lambda p: True)
    print(f"  · pawn_rate 真取到的折价率：consumable={rate_consumable} equip={rate_equip}")

    rows = []
    # 例1 tax=0（基准；折价率来自 pawn_rate）
    rows.append(("例1 tax=0", dict(qty=3, price=100, rate=rate_consumable), 3, 0.0, 0))
    # 例2 tax=正（包内出售不扣税 → 这一例引擎多一项，两边都打印）
    rows.append(("例2 tax=0.05", dict(qty=2, price=1000, rate=1.0), 2, 0.05, 0))
    # 例3 qty 大
    rows.append(("例3 qty=7", dict(qty=7, price=100, rate=rate_consumable), 7, 0.0, 0))
    # 例4 unit_price=0
    rows.append(("例4 unit_price=0", dict(qty=2, price=0, rate=1.0), 2, 0.0, 0))
    # 例5 floor 生效（税额吃光毛额 → 净额被 floor 抬起；包内无 floor）
    rows.append(("例5 floor 生效", dict(qty=1, price=3, rate=1.0), 1, 1.0, 2))
    # 例6 负数（单价为负；数量为负由引擎显式拒）
    rows.append(("例6 负数", dict(qty=2, price=-5, rate=1.0), 2, 0.0, 0))

    for label, spec, qty, tax, floor in rows:
        pkg_out = pkg_sell_one(shop, spec["price"], spec["rate"], qty)
        unit = apply_rate(spec["price"], rate=spec["rate"], floor=0)
        res = settle_sale(qty, unit, tax=tax, floor=floor)
        print(f"  · {label:<16} 输入 qty={qty} price={spec['price']} rate={spec['rate']} "
              f"tax={tax} floor={floor}")
        print(f"      包内 shop.py: {pkg_out!r} → 实收 {gold_of(pkg_out)!r}")
        print(f"      引擎 trade  : gross={res.gross} tax={res.tax} net={res.net}"
              f"（unit={unit}）")

        if label == "例1 tax=0":
            check("例1 同值：包内 255 == 引擎 net 255（qty×折后单价）",
                  gold_of(pkg_out) == 255 and res.net == 255, f"{pkg_out!r} vs {res!r}")
        elif label == "例2 tax=0.05":
            check("例2 包内无税项：包内 2000，引擎 gross 2000 / 税额 100 / net 1900",
                  gold_of(pkg_out) == 2000 and (res.gross, res.tax, res.net) == (2000, 100, 1900),
                  f"{pkg_out!r} vs {res!r}")
        elif label == "例3 qty=7":
            check("例3 qty 大：包内 595 == 引擎 net 595", gold_of(pkg_out) == 595 and res.net == 595,
                  f"{pkg_out!r} vs {res!r}")
        elif label == "例4 unit_price=0":
            check("例4 unit_price=0：包内 None（拒收）⇔ 引擎 net=0（同判据：net<=0 = 无成交）",
                  gold_of(pkg_out) is None and res.net == 0, f"{pkg_out!r} vs {res!r}")
        elif label == "例5 floor 生效":
            check("例5 floor=2 生效：毛额 3、税额 3 → 净额被抬到 2（包内无 floor，对照 3）",
                  gold_of(pkg_out) == 3 and (res.gross, res.tax, res.net) == (3, 3, 2),
                  f"{pkg_out!r} vs {res!r}")
        elif label == "例6 负数":
            check("例6 单价为负：包内 None（拒收）⇔ 引擎 net=max(0, -10)=0",
                  gold_of(pkg_out) is None and res.net == 0, f"{pkg_out!r} vs {res!r}")

    # 例6b：数量为负 —— 引擎显式 ValueError（包内调用方根本不会传负件数）
    try:
        settle_sale(-1, 100)
        check("例6b qty=-1 → ValueError", False)
    except ValueError as exc:
        print(f"      引擎 trade  : qty=-1 → ValueError({exc})")
        check("例6b qty=-1 → ValueError", True)

    # 包内真件确实被调用（证明「真调」不是空转）
    check("★ 包内 sell_item_atomic 真被调用（比对链路不是空转）",
          len(fake_db.calls) > 0 and fake_db.calls[0][2] == 255, str(fake_db.calls[:2]))


# ════════════════════════════════════════════════════════ ② 跨日重置
def t2_daily_reset():
    print("\n[2] 跨日重置：today 指向次日 → used 归零（反证：today 固定 → 不归零）")
    box = {"day": "2026-01-01"}
    state = {}
    dl = DailyLimit(state, lambda: box["day"], namespace="limit")
    check("首日 consume → 已用 2", dl.consume("k", 2, cap=3) == 2 and dl.used("k") == 2)
    print(f"  · 首日 state = {state}")
    box["day"] = "2026-01-02"
    check("★ 次日 used 归零（当日标识换成新键）", dl.used("k") == 0, f"used={dl.used('k')}")
    check("次日 remaining 回满", dl.remaining("k", 3) == 3)
    print(f"  · 次日 state = {state}（首日计数还在，只是不再被今日读到）")
    check("次日 consume 从头计", dl.consume("k", 3, cap=3) == 3)
    check("reset() 清掉非今日残留 = 1 条", dl.reset() == 1)
    check("reset() 幂等：再调一次 0 条", dl.reset() == 0)
    check("reset() 后今日计数保留", dl.used("k") == 3)
    print(f"  · reset 后 state = {state}")

    # 反证：today 固定 → 累计不归零
    fixed = {}
    dl2 = DailyLimit(fixed, lambda: "2026-01-01")
    dl2.consume("k", 2)
    dl2.consume("k", 1)
    check("反证：today 固定 → 不归零（累计 3）", dl2.used("k") == 3, f"used={dl2.used('k')}")


# ════════════════════════════════════════════════════════ ③ 超限
def t3_over_limit():
    print("\n[3] 超限：cap=3 第 4 次 consume → DailyLimitExceeded（前 3 次正常）")
    state = {}
    dl = DailyLimit(state, lambda: "2026-01-01")
    check("cap=3 第 1 次 ok", dl.consume("k", 1, cap=3) == 1)
    check("cap=3 第 2 次 ok", dl.consume("k", 1, cap=3) == 2)
    check("cap=3 第 3 次 ok（刚好到上限）", dl.consume("k", 1, cap=3) == 3)
    check("remaining 到 0", dl.remaining("k", 3) == 0)
    before = dict(state)
    try:
        dl.consume("k", 1, cap=3)
        check("★ 第 4 次 → DailyLimitExceeded", False, "没抛")
    except DailyLimitExceeded as exc:
        print(f"  · 第 4 次原始异常：{type(exc).__name__}: {exc}")
        check("★ 第 4 次 → DailyLimitExceeded", True)
    check("★ 被拒后 state 一字未改（先判后写）", state == before, f"{state} vs {before}")
    # 整批语义：n 超过剩余额度 → 整批拒（不做部分成交）
    d2_state = {}
    d2 = DailyLimit(d2_state, lambda: "d1")
    d2.consume("k", 3, cap=5)
    before2 = dict(d2_state)
    try:
        d2.consume("k", 3, cap=5)
        check("已用 3 + n=3 > cap=5 → 整批拒（不做部分成交）", False)
    except DailyLimitExceeded:
        check("已用 3 + n=3 > cap=5 → 整批拒（不做部分成交）", True)
    check("整批拒后计数未动", d2_state == before2)
    check("刚好到上限（3+2=5）→ 过", d2.consume("k", 2, cap=5) == 5)
    check("不传 cap = 不判上限（不限购）", d2.consume("k", 100) == 105)
    fresh = DailyLimit({}, lambda: "d1")
    try:
        fresh.consume("z", 1, cap=0)
        check("cap=0 → 首次即拒", False)
    except DailyLimitExceeded:
        check("cap=0 → 首次即拒", True)


# ════════════════════════════════════════════════════════ ④ 回调
def t4_callback():
    print("\n[4] 回调：on_change 恰好 1 次（且收到净额）")
    seen = []
    r = settle_sale(3, 10, tax=0.05, on_change=seen.append)
    check("恰好调 1 次", seen == [28], str(seen))
    check("回调参数 = net", (r.gross, r.tax, r.net) == (30, 2, 28), repr(r))
    seen.clear()
    r2 = settle_sale(1, 1, tax=1.0, floor=5, on_change=seen.append)
    check("floor 生效时也恰好 1 次，且给的是抬升后的净额", seen == [5], str(seen))
    check("floor 生效的明细", (r2.gross, r2.tax, r2.net) == (1, 1, 5), repr(r2))
    seen.clear()
    settle_sale(2, 3, on_change=None)
    check("on_change=None 不炸、不产生调用", seen == [])
    seen.clear()

    def boom(net):
        seen.append(net)
        raise RuntimeError("内容侧回调炸了")

    try:
        settle_sale(2, 3, on_change=boom)
        check("回调抛错 → 原样向上抛（不吞）", False)
    except RuntimeError:
        check("回调抛错 → 原样向上抛（不吞）", True)
    check("回调抛错前也恰好调了 1 次", seen == [6], str(seen))
    try:
        settle_sale(2, 3, on_change="not-callable")
        check("on_change 不可调用 → TypeError", False)
    except TypeError:
        check("on_change 不可调用 → TypeError", True)


# ════════════════════════════════════════════════════════ ⑤ apply_rate
def t5_apply_rate():
    print("\n[5] apply_rate：用包内 pawn_rate / PAWN_RATES 真取到的折价率逐例等值；floor 生效")
    try:
        shop, _ = load_pkg_shop()
        from content import catalog_life as CL
    except Exception as exc:                                   # noqa: BLE001
        check("包内折价率真件可 import", False, f"{exc!r}")
        return
    rates = dict(CL.PAWN_RATES)                                 # 包内真率表
    rates["pawn_rate(equip)"] = shop.pawn_rate(_PLAYER, {"slot": "x"},
                                              is_smith_shop_=lambda p: True)
    rates["pawn_rate(consumable)"] = shop.pawn_rate(
        _PLAYER, {"name": "zzz-not-in-roster", "type": "x"})
    print(f"  · 包内真率表：{rates}")

    bad = []
    for label, rate in sorted(rates.items()):
        for price in (20, 100, 1000):                           # 乘积皆为整数（同语义用例）
            engine = apply_rate(price, rate=rate, floor=0)
            pkg = int(price * rate)                              # 包内算式（shop.py:261）
            out = pkg_sell_one(shop, price, rate, 3)
            if engine != pkg or gold_of(out) != pkg * 3:
                bad.append((label, price, rate, engine, pkg, out))
            print(f"  · {label:<22} price={price:<5} rate={rate:<5} "
                  f"引擎 apply_rate={engine:<5} 包内 int={pkg:<5} "
                  f"包内 sell_one(qty=3)={out!r}")
    check("★ 逐例等值：apply_rate == 包内 int(price×rate)（且 ×qty 也等值）", not bad, str(bad[:3]))

    # floor 生效
    check("floor 生效：apply_rate(3, rate=0.1) = round(0.3)=0 → 抬到 floor=1",
          apply_rate(3, rate=0.1) == 1, apply_rate(3, rate=0.1))
    check("floor=0 时如实给 0", apply_rate(3, rate=0.1, floor=0) == 0)
    check("默认 floor=1：apply_rate(0) = 1（不低于 1，不是 0）", apply_rate(0) == 1,
          apply_rate(0))
    check("显式 floor=0：apply_rate(0, floor=0) = 0", apply_rate(0, floor=0) == 0)
    check("rate × discount 两个系数都乘上（100×0.85×0.8 → 68）",
          apply_rate(100, rate=0.85, discount=0.8) == 68,
          apply_rate(100, rate=0.85, discount=0.8))
    check("单价为负 → 落到 floor（floor=0 归 0）", apply_rate(-5, floor=0) == 0)

    # 与包内 int 截断的口径差（如实打印，不藏）
    out = pkg_sell_one(shop, 1, 0.8, 1)
    print(f"  · 口径差例：price=1 rate=0.8 → 引擎 apply_rate={apply_rate(1, rate=0.8)}"
          f"（round 0.8=1 ≥ floor=1）/ 包内 sell_one={out!r}（int 0.8=0 → 拒收）")
    check("口径差如实可见：引擎 round+floor=1，包内 int 截断=0/拒收",
          apply_rate(1, rate=0.8) == 1 and out is None)


# ════════════════════════════════════════════════════════ ⑥ 零知识
BANNED = ("奥兰迪亚", "余烬", "公会", "职业", "怪物", "物品", "装备", "金币", "商店",
          "技能", "拍卖", "限定皮肤", "dungeon", "guild", "monster", "item", "gold",
          "equip", "player", "shop", "level", "quest", "npc")
_ASCII_PATS = [(b, re.compile(r"(?<![A-Za-z0-9_])" + re.escape(b) + r"(?![A-Za-z0-9_])"))
               for b in BANNED if b.isascii()]


def _trade_sources():
    base = os.path.join(ROOT, "extends", "ext_economy", "trade")
    out = []
    for dirpath, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in sorted(files):
            if fn.endswith(".py"):
                out.append(os.path.join(dirpath, fn))
    return out


def t6_zero_knowledge():
    print("\n[6] 零知识：引擎模块不得出现具体游戏词汇")
    check("模块目录存在且非空", bool(_trade_sources()), "extends/ext_economy/trade/")
    hits = []
    for path in _trade_sources():
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        with open(path, encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                for term, pat in _ASCII_PATS:
                    if pat.search(line):
                        hits.append(f"{rel}:{i} [{term}] {line.strip()[:60]}")
                for term in BANNED:
                    if not term.isascii() and term in line:
                        hits.append(f"{rel}:{i} [{term}] {line.strip()[:60]}")
    if hits:
        for h in hits[:10]:
            print(f"      {h}")
    check("★ 源码（含注释/文档串）无具体游戏词汇", not hits, f"{len(hits)} 处")

    # AST 常量面：字符串常量里也不许有（文档串另判 —— 这里只判代码取值）
    bad = []
    for path in _trade_sources():
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
        docs = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
                d = ast.get_docstring(node, clean=False)
                if d is not None:
                    docs.add(d)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in docs:
                    continue
                low = node.value.lower()
                for b in BANNED:
                    if (b in low) if b.isascii() else (b in node.value):
                        bad.append(f"{rel}:{node.lineno} [{b}]")
    check("★ 代码字符串常量无游戏词汇（AST）", not bad, str(bad[:6]))


# ════════════════════════════════════════════════════════ ⑦ 边界 / fail-closed
def t7_fail_closed():
    print("\n[7] fail-closed：坏输入一律显式报错（不静默吞）")
    # settle_sale
    for label, fn, exc in (
        ("qty=0 → ValueError", lambda: settle_sale(0, 10), ValueError),
        ("qty=-3 → ValueError", lambda: settle_sale(-3, 10), ValueError),
        ("qty=2.5 → TypeError", lambda: settle_sale(2.5, 10), TypeError),
        ("qty=True → TypeError", lambda: settle_sale(True, 10), TypeError),
        ("unit_price=1.5 → TypeError", lambda: settle_sale(1, 1.5), TypeError),
        ("floor=-1 → ValueError", lambda: settle_sale(1, 10, floor=-1), ValueError),
        ("floor=1.5 → TypeError", lambda: settle_sale(1, 10, floor=1.5), TypeError),
        ("tax=-0.1 → ValueError", lambda: settle_sale(1, 10, tax=-0.1), ValueError),
        ("tax='x' → TypeError", lambda: settle_sale(1, 10, tax="x"), TypeError),
        ("tax=True → TypeError", lambda: settle_sale(1, 10, tax=True), TypeError),
        ("apply_rate price=1.5 → TypeError", lambda: apply_rate(1.5), TypeError),
        ("apply_rate floor=-1 → ValueError", lambda: apply_rate(1, floor=-1), ValueError),
        ("apply_rate floor='x' → TypeError", lambda: apply_rate(1, floor="x"), TypeError),
    ):
        try:
            fn()
            check(label, False, "没抛")
        except exc:
            check(label, True)
        except Exception as other:                             # noqa: BLE001
            check(label, False, f"抛了 {type(other).__name__}")

    # DailyLimit 构造面
    cases = (
        ("namespace='' → ValueError",
         lambda: DailyLimit({}, lambda: "d", namespace=""), ValueError),
        ("namespace 含冒号 → ValueError",
         lambda: DailyLimit({}, lambda: "d", namespace="a:b"), ValueError),
        ("today 不可调用 → TypeError", lambda: DailyLimit({}, "d"), TypeError),
        ("state 非映射 → TypeError", lambda: DailyLimit([], lambda: "d"), TypeError),
    )
    for label, fn, exc in cases:
        try:
            fn()
            check(label, False, "没抛")
        except exc:
            check(label, True)
        except Exception as other:                             # noqa: BLE001
            check(label, False, f"抛了 {type(other).__name__}")
    for label, day in (("today() 返回空串 → ValueError", ""),
                       ("today() 含冒号 → ValueError", "a:b"),
                       ("today() 返回非字符串 → ValueError", 42)):
        dl = DailyLimit({}, lambda d=day: d)
        try:
            dl.used("k")
            check(label, False, "没抛")
        except ValueError:
            check(label, True)
    st = {"limit:d1:k": "oops"}
    try:
        DailyLimit(st, lambda: "d1").used("k")
        check("state 计数非整数 → ValueError（不静默当 0）", False)
    except ValueError as exc:
        print(f"  · 坏计数原始异常：{exc}")
        check("state 计数非整数 → ValueError（不静默当 0）", True)
    st2 = {"limit:d1:k": -1}
    try:
        DailyLimit(st2, lambda: "d1").used("k")
        check("state 计数为负 → ValueError", False)
    except ValueError:
        check("state 计数为负 → ValueError", True)
    st3 = {"limit:junk": 1}                                    # 本命名空间里的坏键
    try:
        DailyLimit(st3, lambda: "d1").reset()
        check("reset 遇坏键 → ValueError", False)
    except ValueError as exc:
        print(f"  · 坏键原始异常：{exc}")
        check("reset 遇坏键 → ValueError", True)

    dl = DailyLimit({}, lambda: "d1")
    for label, fn, exc in (
        ("consume n=0 → ValueError", lambda: dl.consume("k", 0), ValueError),
        ("consume n=-1 → ValueError", lambda: dl.consume("k", -1), ValueError),
        ("consume n=1.5 → TypeError", lambda: dl.consume("k", 1.5), TypeError),
        ("consume cap=1.5 → TypeError", lambda: dl.consume("k", 1, cap=1.5), TypeError),
        ("consume cap=-1 → ValueError", lambda: dl.consume("k", 1, cap=-1), ValueError),
        ("remaining cap=-1 → ValueError", lambda: dl.remaining("k", -1), ValueError),
    ):
        try:
            fn()
            check(label, False, "没抛")
        except exc:
            check(label, True)
        except Exception as other:                             # noqa: BLE001
            check(label, False, f"抛了 {type(other).__name__}")


# ════════════════════════════════════════════════════════ ⑧ 形状细节
def t8_shape_details():
    print("\n[8] 形状细节：state 键结构 / 返回类型 / 其它命名空间不被误清")
    state = {}
    dl = DailyLimit(state, lambda: "2026-01-01", namespace="limit")
    dl.consume("mat:iron", 2)                                  # key 里允许冒号
    check("state 键 = {namespace}:{today}:{key}",
          state == {"limit:2026-01-01:mat:iron": 2}, str(state))
    check("key_of 与写入键一致", dl.key_of("mat:iron") == "limit:2026-01-01:mat:iron")
    check("used 未记过 = 0", dl.used("nope") == 0)
    check("reset(key=…) 只清该 key", dl.reset("mat:iron") == 1 and dl.used("mat:iron") == 0)

    other = {"other:2020-01-01:k": 9, "limit:2000-01-01:old": 4, "unrelated": 1}
    dl2 = DailyLimit(other, lambda: "2026-01-01", namespace="limit")
    check("reset() 只动本命名空间的非今日条目（外部命名空间原样）",
          dl2.reset() == 1 and other == {"other:2020-01-01:k": 9, "unrelated": 1}, str(other))

    r = settle_sale(2, 5)
    check("SaleResult 是 NamedTuple（可下标/解包）",
          isinstance(r, tuple) and tuple(r) == (2, 5, 10, 0, 10), repr(r))
    check("SaleResult 字段名", SaleResult._fields == ("qty", "unit_price", "gross", "tax", "net"))
    check("DailyLimitExceeded 是 RuntimeError 子类", issubclass(DailyLimitExceeded, RuntimeError))
    check("consume 返回新的已用数", DailyLimit({}, lambda: "d").consume("k", 3) == 3)


# ════════════════════════════════════════════════════════ ⑨ 突变反证
_MUTATIONS = [
    ("类型守卫（qty<=0）",
     [("    if qty <= 0:", "    if qty <= -10 ** 9:")],
     lambda ns: _no_raise(lambda: ns["settle_sale"](0, 5), ValueError)),
    ("上限守卫（cap）",
     [("        if limit is not None and used + n > limit:", "        if False:")],
     lambda ns: _no_raise(lambda: _consume4(ns), DailyLimitExceeded)),
    ("净额下限（floor）",
     [("    net = max(floor, gross - tax_amount)", "    net = gross - tax_amount")],
     lambda ns: ns["settle_sale"](1, 3, tax=1.0, floor=2).net != 2),
    ("当日键（跨日重置）",
     [('        return f"{self._namespace}:{self._today_id()}:{key}"',
       '        return f"{self._namespace}:fixed-day:{key}"')],
     lambda ns: _used_after_next_day(ns) != 0),
    ("折价 floor",
     [("    return max(floor, value)", "    return value")],
     lambda ns: ns["apply_rate"](3, rate=0.1) != 1),
    ("fail-closed（坏计数）",
     [('            raise ValueError(f"当日计数不是整数：{raw!r}")', "            return 0")],
     lambda ns: _no_raise(lambda: ns["DailyLimit"]({"limit:d1:k": "oops"},
                                                   lambda: "d1").used("k"), ValueError)),
]


def _no_raise(fn, exc):
    """探针：改坏后**不再抛** exc → True（= 反证有牙）。"""
    try:
        fn()
    except exc:
        return False
    except Exception:                                          # noqa: BLE001
        return False
    return True


def _consume4(ns):
    dl = ns["DailyLimit"]({}, lambda: "d1")
    for _ in range(3):
        dl.consume("k", 1, cap=3)
    return dl.consume("k", 1, cap=3)


def _used_after_next_day(ns):
    box = {"day": "d1"}
    dl = ns["DailyLimit"]({}, lambda: box["day"])
    dl.consume("k")
    box["day"] = "d2"
    return dl.used("k")


def _load_mutated(edits):
    """按锚点改坏模块源码 → exec 到独立命名空间（锚点必须唯一命中，否则报错）。"""
    path = os.path.join(ROOT, "extends", "ext_economy", "trade", "__init__.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    for old, new in edits:
        if src.count(old) != 1:
            raise AssertionError(f"反证锚点命中 {src.count(old)} 次（应为 1）：{old!r}")
        src = src.replace(old, new, 1)
    ns = {"__name__": "ext_economy.trade._mutant", "__file__": path}
    exec(compile(src, path + " [mutant]", "exec"), ns)         # noqa: S102
    return ns


def t9_mutations():
    print("\n[9] 突变反证 —— 把实现改坏，断言必须报红（真模块只读，改坏在内存副本里做）")
    real_ns = vars(trade)
    for name, edits, probe in _MUTATIONS:
        check(f"反证·{name}｜真模块守卫成立（探针 False）", probe(real_ns) is False,
              f"probe={probe(real_ns)!r}")
        try:
            mut_ns = _load_mutated(edits)
        except Exception as exc:                               # noqa: BLE001
            check(f"反证·{name}｜改坏后探针 True（有牙）", False, f"突变加载失败：{exc!r}")
            continue
        got = probe(mut_ns)
        check(f"反证·{name}｜改坏后探针 True（有牙）", got is True, f"probe={got!r}")


# ════════════════════════════════════════════════════════ main
def main():
    print("== trade 门禁：交易形状（每日限购 / 成交结算 / 折价换算）==")
    t1_same_values()
    t2_daily_reset()
    t3_over_limit()
    t4_callback()
    t5_apply_rate()
    t6_zero_knowledge()
    t7_fail_closed()
    t8_shape_details()
    t9_mutations()
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
