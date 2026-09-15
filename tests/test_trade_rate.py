#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""trade.apply_rate 门禁：取整方式（mode）与下界（floor）由调用方定 + 有牙反证。

跑法：python tests/test_trade_rate.py
退出码：0 = 全绿；1 = 有失败。

判据（对应作业书 §5，逐条打原始输出）
--------------------------------------
  ① 缺省不变：`apply_rate(price, rate=r, discount=d)` 与「改动前的冻结算式」
     `max(1, int(round(price×r×d)))` 在扫描网格上逐值相同（缺省 + 显式 floor 各口径）
  ② trunc 生效：`apply_rate(7, rate=0.85, mode="trunc")` = 5（`int(7×0.85)`）；
     同参 `mode="round"` = 6
  ③ floor=None 生效：`apply_rate(0, rate=0.85, floor=None)` = 0（不设下界）；缺省 = 1
  ④ 负值向零：`apply_rate(-7, rate=0.85, mode="trunc", floor=None)` = -5
     （是 `int()` 向零，不是 `floor()` 向下给的 -6）
  ⑤ fail-closed：`mode` 非法值 → `ValueError`；`floor` 非 int（含 bool）→ `TypeError`；
     `floor` 负 → `ValueError`（都贴原始异常）
  ⑥ 零知识：`saintess_engine/trade/` 源码 grep 不到具体游戏词汇（原文扫描）
  ⑦ 反证：把实现改坏 5 处（缺省 mode→trunc / floor=None 当 0 / mode 守卫失效 /
     trunc 退化成 round / floor 守卫失效），断言必须报红 —— 每处都成对：
     真模块探针「未报红」→ 改坏后探针「报红」

⚠ 反证是**进程内突变**：读模块源码、按锚点改坏、exec 到独立命名空间再跑探针；
锚点找不到即报红（防「反证变成空转」）。真模块（磁盘上的那份）只读不改。
"""
import inspect
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine.trade import apply_rate                                     # noqa: E402
import saintess_engine.trade as trade                                            # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name} {detail}")


# ════════════════════════════════════════════════════════ 冻结算式（改动前的行为）
def old_default(price, *, rate=1.0, discount=1.0, floor=1):
    """改动前 `apply_rate` 的算式（冻结参照，只用于比对，不是被交付的实现）。

    `value = int(round(price × rate × discount))`；`return max(floor, value)`。
    """
    return max(floor, int(round(price * float(rate) * float(discount))))


# 扫描网格：含 0 与负值（取整口径在负数上分叉）
_PRICES = list(range(-30, 301))
_RATES = (0.5, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0)
_DISCOUNTS = (1.0, 0.9, 0.8)
# 探针用的窄网格（便宜）
_GRID = [(p, r) for p in (0, 1, 3, 7, 20, 100, 999, -3, -7, -100)
         for r in (0.1, 0.5, 0.8, 0.85, 0.9, 1.0)]


# ════════════════════════════════════════════════════════ ① 缺省不变
def t1_default_unchanged():
    print("\n[1] 缺省不变：缺省调用 == 改动前冻结算式（扫描网格逐值相同）")
    bad = []
    total = 0
    for p in _PRICES:
        for r in _RATES:
            for d in _DISCOUNTS:
                got = apply_rate(p, rate=r, discount=d)
                want = old_default(p, rate=r, discount=d)
                total += 1
                if got != want:
                    bad.append((p, r, d, "floor 缺省(=1)", got, want))
                for fl in (0, 2):
                    got = apply_rate(p, rate=r, discount=d, floor=fl)
                    want = old_default(p, rate=r, discount=d, floor=fl)
                    total += 1
                    if got != want:
                        bad.append((p, r, d, f"floor={fl}", got, want))
    print(f"  · 比对网格：{len(_PRICES)} price × {len(_RATES)} rate × {len(_DISCOUNTS)} discount"
          f" × 3 floor 口径（缺省 / 0 / 2）= {total} 例")
    for row in bad[:5]:
        print(f"      ✗ price={row[0]} rate={row[1]} discount={row[2]} {row[3]}: "
              f"引擎={row[4]} 冻结={row[5]}")
    check(f"★ {total} 例缺省路径与改动前逐值相同", not bad, f"{len(bad)} 处不等")

    check("缺省例：apply_rate(100, rate=0.85) = 85", apply_rate(100, rate=0.85) == 85,
          apply_rate(100, rate=0.85))
    check("缺省例：apply_rate(7, rate=0.85) = 6（round(5.95)，旧口径）",
          apply_rate(7, rate=0.85) == 6, apply_rate(7, rate=0.85))
    check("缺省例：apply_rate(0) = 1（地板默认 1）", apply_rate(0) == 1, apply_rate(0))
    check("缺省例：两个系数都乘（100×0.85×0.8 = 68）",
          apply_rate(100, rate=0.85, discount=0.8) == 68,
          apply_rate(100, rate=0.85, discount=0.8))


# ════════════════════════════════════════════════════════ ② trunc 生效
def t2_trunc():
    print("\n[2] trunc 生效：向零截断 = int()；round 同参对照")
    got_t = apply_rate(7, rate=0.85, mode="trunc")
    got_r = apply_rate(7, rate=0.85, mode="round")
    print(f"  · price=7 rate=0.85 → 乘算 5.95：trunc={got_t} ｜ round={got_r} ｜ "
          f"旧 int 口径={int(7 * 0.85)}")
    check("★ apply_rate(7, rate=0.85, mode='trunc') == 5（= int(7×0.85)）", got_t == 5, got_t)
    check("apply_rate(7, rate=0.85, mode='round') == 6（= round(5.95)）", got_r == 6, got_r)
    check("apply_rate(3, rate=0.9, mode='trunc') == 2（旧 int 口径）",
          apply_rate(3, rate=0.9, mode="trunc") == 2)

    bad = []
    total = 0
    diff = 0
    for p, r in _GRID:
        total += 1
        if apply_rate(p, rate=r, mode="trunc", floor=None) != int(p * float(r)):
            bad.append((p, r, apply_rate(p, rate=r, mode="trunc", floor=None), int(p * float(r))))
        if p >= 0 and int(p * float(r)) != int(round(p * float(r))):
            diff += 1
    print(f"  · 窄网格 {total} 例：trunc 与 round 取整结果分叉 {diff} 例（口径差如实可见）")
    for row in bad[:5]:
        print(f"      ✗ price={row[0]} rate={row[1]}: trunc={row[2]} int={row[3]}")
    check(f"★ 窄网格 {total} 例：trunc（floor=None）== int(price×rate)", not bad, f"{len(bad)} 处不等")


# ════════════════════════════════════════════════════════ ③ floor=None 生效
def t3_floor_none():
    print("\n[3] floor=None 生效：不施加下界（0/负值原样给）；缺省仍为 1")
    print(f"  · apply_rate(0, rate=0.85, floor=None) = {apply_rate(0, rate=0.85, floor=None)}"
          f" ｜ 缺省 = {apply_rate(0, rate=0.85)}")
    check("★ apply_rate(0, rate=0.85, floor=None) == 0（不给地板）",
          apply_rate(0, rate=0.85, floor=None) == 0, apply_rate(0, rate=0.85, floor=None))
    check("对照：缺省 apply_rate(0, rate=0.85) == 1（地板默认 1）",
          apply_rate(0, rate=0.85) == 1, apply_rate(0, rate=0.85))
    check("floor=None 时小额不被抬起：apply_rate(3, rate=0.1, floor=None) == 0",
          apply_rate(3, rate=0.1, floor=None) == 0, apply_rate(3, rate=0.1, floor=None))
    check("★ floor=None 时负值不被抬到 0：apply_rate(-7, rate=0.85, mode='trunc', "
          "floor=None) == -5",
          apply_rate(-7, rate=0.85, mode="trunc", floor=None) == -5,
          apply_rate(-7, rate=0.85, mode="trunc", floor=None))
    check("显式 floor=5 仍生效（对照）：apply_rate(1, rate=0.1, floor=5) == 5",
          apply_rate(1, rate=0.1, floor=5) == 5)
    check("显式 floor=0 != None：apply_rate(-7, rate=0.85, mode='trunc', floor=0) == 0",
          apply_rate(-7, rate=0.85, mode="trunc", floor=0) == 0)


# ════════════════════════════════════════════════════════ ④ 负值向零
def t4_negative_toward_zero():
    print("\n[4] 负值向零：trunc 用 int()（向零），不是 floor()（向下）")
    got = apply_rate(-7, rate=0.85, mode="trunc", floor=None)
    got_r = apply_rate(-7, rate=0.85, mode="round", floor=None)
    print(f"  · price=-7 rate=0.85 → 乘算 -5.95：trunc={got} ｜ round={got_r} ｜ "
          f"floor() 口径 = -6")
    check("★ apply_rate(-7, rate=0.85, mode='trunc', floor=None) == -5", got == -5, got)
    check("对照：同参 mode='round' == -6（round(-5.95)）", got_r == -6, got_r)
    check("向零 ≠ 向下：trunc 的 -5 与 floor() 的 -6 不同", got != -6, got)

    bad = []
    for p, r in _GRID:
        if p >= 0:
            continue
        if apply_rate(p, rate=r, mode="trunc", floor=None) != int(p * float(r)):
            bad.append((p, r, apply_rate(p, rate=r, mode="trunc", floor=None), int(p * float(r))))
    check("★ 负价窄网格：trunc 全部 == int(price×rate)（向零）", not bad, f"{bad[:3]}")


# ════════════════════════════════════════════════════════ ⑤ fail-closed
def t5_fail_closed():
    print("\n[5] fail-closed：非法 mode / floor 一律显式报错（不静默回退）")
    cases = (
        ('mode="bad" → ValueError', lambda: apply_rate(1, mode="bad"), ValueError),
        ('mode="ROUND" → ValueError', lambda: apply_rate(1, mode="ROUND"), ValueError),
        ('mode="truncate" → ValueError', lambda: apply_rate(1, mode="truncate"), ValueError),
        ('mode="" → ValueError', lambda: apply_rate(1, mode=""), ValueError),
        ("mode=None → ValueError", lambda: apply_rate(1, mode=None), ValueError),
        ("mode=1 → ValueError", lambda: apply_rate(1, mode=1), ValueError),
        ("mode=True → ValueError", lambda: apply_rate(1, mode=True), ValueError),
        ('floor="1" → TypeError', lambda: apply_rate(1, floor="1"), TypeError),
        ("floor=1.5 → TypeError", lambda: apply_rate(1, floor=1.5), TypeError),
        ("floor=True → TypeError", lambda: apply_rate(1, floor=True), TypeError),
        ("floor=-1 → ValueError", lambda: apply_rate(1, floor=-1), ValueError),
        ('mode="bad" + floor=None → ValueError（mode 先于地板判定）',
         lambda: apply_rate(1, mode="bad", floor=None), ValueError),
        ("price=1.5 → TypeError（沿现约定）", lambda: apply_rate(1.5), TypeError),
    )
    for label, fn, exc in cases:
        try:
            out = fn()
            check(label, False, f"没抛，返回 {out!r}")
        except exc as e:
            print(f"  · {label}：{type(e).__name__}: {e}")
            check(label, True)
        except Exception as other:                                              # noqa: BLE001
            check(label, False, f"抛了 {type(other).__name__}: {other}")


# ════════════════════════════════════════════════════════ ⑥ 零知识
BANNED = ("奥兰迪亚", "余烬", "公会", "职业", "怪物", "物品", "装备", "金币", "商店",
          "技能", "拍卖", "限定皮肤", "dungeon", "guild", "monster", "item", "gold",
          "equip", "player", "shop", "level", "quest", "npc")
_ASCII_PATS = [(b, re.compile(r"(?<![A-Za-z0-9_])" + re.escape(b) + r"(?![A-Za-z0-9_])"))
               for b in BANNED if b.isascii()]


def _trade_sources():
    base = os.path.join(ROOT, "saintess_engine", "trade")
    out = []
    for dirpath, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in sorted(files):
            if fn.endswith(".py"):
                out.append(os.path.join(dirpath, fn))
    return out


def t6_zero_knowledge():
    print("\n[6] 零知识：trade 模块源码不含具体游戏词汇")
    check("模块目录存在且非空", bool(_trade_sources()), "saintess_engine/trade/")
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
    for h in hits[:10]:
        print(f"      {h}")
    check("★ 源码（含注释/文档串）无具体游戏词汇", not hits, f"{len(hits)} 处")


# ════════════════════════════════════════════════════════ ⑧ 签名形状
def t8_signature_shape():
    print("\n[8] 签名形状：mode / floor 是 keyword-only 参数（不是「新旧两条路径」的开关）")
    sig = inspect.signature(apply_rate)
    mode_p, floor_p = sig.parameters["mode"], sig.parameters["floor"]
    check("mode 是 keyword-only", mode_p.kind is inspect.Parameter.KEYWORD_ONLY)
    check("floor 是 keyword-only", floor_p.kind is inspect.Parameter.KEYWORD_ONLY)
    check("mode 缺省 == 'round'", mode_p.default == "round", repr(mode_p.default))
    check("floor 缺省 == 1", floor_p.default == 1, repr(floor_p.default))
    check("关键字调用可行：apply_rate(price=1, rate=0.5, mode='trunc', floor=None) == 0",
          apply_rate(price=1, rate=0.5, mode="trunc", floor=None) == 0)
    try:
        apply_rate(1, 1.0, 1.0, 1, "round")
        check("位置传参（第 5 个）→ TypeError", False, "没抛")
    except TypeError:
        check("位置传参（第 5 个）→ TypeError", True)


# ════════════════════════════════════════════════════════ ⑦ 突变反证
_SRC = os.path.join(ROOT, "saintess_engine", "trade", "__init__.py")


def _no_raise(fn, exc):
    """探针零件：不该抛 `exc` 却抛了别的 = 也不算「没抛」；没抛 → True（= 守卫失效）。"""
    try:
        fn()
    except exc:
        return False
    except Exception:                                                          # noqa: BLE001
        return False
    return True


def _default_grid_mismatch(ns):
    """缺省调用与改动前冻结算式出现不等值 → True（判据 1 报红）。"""
    fn = ns["apply_rate"]
    for p, r in _GRID:
        if fn(p, rate=r) != old_default(p, rate=r):
            return True
    return False


def _floor_none_clamped(ns):
    """floor=None 被当成 0（被下界夹住）→ True（判据 3 报红）。"""
    fn = ns["apply_rate"]
    return (fn(0, rate=0.85, floor=None) != 0
            or fn(-7, rate=0.85, mode="trunc", floor=None) != -5)


def _mode_guard_open(ns):
    """非法 mode 不再抛 ValueError → True（判据 5 报红）。"""
    return _no_raise(lambda: ns["apply_rate"](1, mode="bad"), ValueError)


def _trunc_is_round(ns):
    """trunc 退化成 round → True（判据 2/4 报红）。"""
    fn = ns["apply_rate"]
    return (fn(7, rate=0.85, mode="trunc") != 5
            or fn(-7, rate=0.85, mode="trunc", floor=None) != -5)


def _floor_guard_open(ns):
    """floor 类型/负值守卫失效 → True（判据 5 报红）。"""
    fn = ns["apply_rate"]
    return (_no_raise(lambda: fn(1, floor=-1), ValueError)
            or _no_raise(lambda: fn(1, floor=True), TypeError)
            or _no_raise(lambda: fn(1, floor="1"), TypeError))


_MUTATIONS = [
    ("缺省 mode 改成 trunc",
     [('floor=1, mode="round"', 'floor=1, mode="trunc"')],
     _default_grid_mismatch),
    ("floor=None 当 0 处理",
     [("    if floor is None:\n        return value",
       "    if floor is None:\n        floor = 0")],
     _floor_none_clamped),
    ("mode 守卫失效（非法值静默走 else）",
     [('    if mode not in ("round", "trunc"):', "    if False:")],
     _mode_guard_open),
    ("trunc 退化成 round",
     [("else int(scaled)", "else int(round(scaled))")],
     _trunc_is_round),
    ("floor 守卫失效（None 以外的类型/负值不判）",
     [("    if floor is not None:", "    if False:")],
     _floor_guard_open),
]


def _load_mutated(edits):
    """按锚点改坏模块源码 → exec 到独立命名空间（锚点必须唯一命中，否则报错）。"""
    with open(_SRC, encoding="utf-8") as fh:
        src = fh.read()
    for old, new in edits:
        n = src.count(old)
        if n != 1:
            raise AssertionError(f"反证锚点命中 {n} 次（应为 1）：{old!r}")
        src = src.replace(old, new, 1)
    ns = {"__name__": "saintess_engine.trade._mutant", "__file__": _SRC}
    exec(compile(src, _SRC + " [mutant]", "exec"), ns)                          # noqa: S102
    return ns


def t7_mutations():
    print("\n[7] 突变反证 —— 把实现改坏，断言必须报红（真模块只读，改坏在内存副本里做）")
    real_ns = vars(trade)
    for name, edits, probe in _MUTATIONS:
        check(f"反证·{name}｜真模块探针未报红", probe(real_ns) is False,
              f"probe={probe(real_ns)!r}")
        try:
            mut_ns = _load_mutated(edits)
        except Exception as exc:                                                # noqa: BLE001
            check(f"反证·{name}｜改坏后探针报红（有牙）", False, f"突变加载失败：{exc!r}")
            continue
        got = probe(mut_ns)
        check(f"反证·{name}｜改坏后探针报红（有牙）", got is True, f"probe={got!r}")


# ════════════════════════════════════════════════════════ ⑨ 反证演示（打判红行）
def _grid_mismatches(ns, limit=3):
    fn = ns["apply_rate"]
    out = []
    for p, r in _GRID:
        got, want = fn(p, rate=r), old_default(p, rate=r)
        if got != want:
            out.append((p, r, got, want))
        if len(out) >= limit:
            break
    return out


def t9_counterproof_demo():
    print("\n[9] 反证演示：改坏后，判据 1 / 判据 3 的原始判红行")
    miss = _grid_mismatches(
        _load_mutated([('floor=1, mode="round"', 'floor=1, mode="trunc"')]))
    print(f"  · 变体「缺省 mode='trunc'」下判据 1：不等值 {len(miss)}+ 处")
    for p, r, got, want in miss:
        print(f"      → 判红 price={p} rate={r}: 引擎={got} 冻结={want}")
    check("★ 反证：缺省 mode 改成 'trunc' → 判据 1 必红", bool(miss), "没有不等值")

    fn = _load_mutated([("    if floor is None:\n        return value",
                         "    if floor is None:\n        floor = 0")])["apply_rate"]
    literal = fn(0, rate=0.85, floor=None)
    negative = fn(-7, rate=0.85, mode="trunc", floor=None)
    print(f"  · 变体「floor=None 当 0」下判据 3 字面例："
          f"apply_rate(0, rate=0.85, floor=None) = {literal}（期望 0 ⇒ 0 与 0 不可区分）")
    print(f"      判别用负值例：apply_rate(-7, rate=0.85, mode='trunc', floor=None) = "
          f"{negative}（期望 -5）")
    check("★ 反证：floor=None 当 0 处理 → 判据 3（含负值判别例）必红",
          negative != -5, "负值例仍给 -5（反证空转）")


# ════════════════════════════════════════════════════════ main
def main():
    print("== trade.apply_rate 门禁：取整方式（mode）与下界（floor）由调用方定 ==")
    t1_default_unchanged()
    t2_trunc()
    t3_floor_none()
    t4_negative_toward_zero()
    t5_fail_closed()
    t6_zero_knowledge()
    t7_mutations()
    t8_signature_shape()
    t9_counterproof_demo()
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
