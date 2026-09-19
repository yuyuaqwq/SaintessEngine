#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""membership 门禁：职位 / 贡献 / 申请 / 「只有一个成员集合」 / 零知识。

跑法：python tests/test_membership_shape.py
退出码：0 = 全绿；1 = 有失败。

四处专门钉住的地方（都是「改了就静默变行为」的）：
  ① **只有一个成员集合**：全引擎 `class .*Roster` 只许 `run/roster.py` 一处，
     membership 里不许 `Roster(...)` 造第二份名单，也不许缓存成员表（名字成员变动要立刻可见）
  ② **跨窗口由 `period_key()` 决定**：换周期 → 周期窗口归零且 `total` 不变；
     反证：`period_key` 固定 → 不归零（谁把「归零」挪进 `rotate()` 就会在这里报红）
  ③ **同分保序**：注入了名单就按**名单序**，未注入按账本序（不是「两套语义」，是名单为空时的同一条）
  ④ **fail-closed**：名单 / 账本 / 周期 / 上限给错 → 当场报错，不许静默当空
"""
import ast
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import saintess_engine.membership as MEMBERSHIP                        # noqa: E402
from saintess_engine.membership import (Applications, Contribution,   # noqa: E402
                                        QueueFull, RoleNotAllowed, RoleSlots)
from saintess_engine.run import Roster                                # noqa: E402

passed = failed = 0


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


def _membership_dir():
    return os.path.join(ROOT, "saintess_engine", "membership")


def _membership_sources():
    out = {}
    for fn in sorted(os.listdir(_membership_dir())):
        if fn.endswith(".py"):
            p = os.path.join(_membership_dir(), fn)
            out[f"membership/{fn}"] = open(p, encoding="utf-8").read()
    return out


# ---------------------------------------------------------------- 1 只有一个成员集合
def t1_single_roster():
    print("\n[1] 只有一个成员集合：`class .*Roster` 全引擎只许一处")
    pat = re.compile(r"^\s*class\s+\w*Roster\w*\b", re.M)
    hits = []
    for root, dirs, files in os.walk(os.path.join(ROOT, "saintess_engine")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            src = open(p, encoding="utf-8").read()
            for m in pat.finditer(src):
                hits.append(f"{rel}:{src[:m.start()].count(chr(10)) + 1}")
    files_hit = sorted({h.split(":")[0] for h in hits})
    check("★ 只有 run/roster.py 定义 Roster", files_hit == ["saintess_engine/run/roster.py"],
          str(hits))

    src = _membership_sources()
    made = []
    for rel, s in src.items():
        for node in ast.walk(ast.parse(s, filename=rel)):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id.endswith("Roster")):
                made.append(f"{rel}:{node.lineno}")
    check("★ membership 里不造第二份名单（代码里无 `Roster(...)` 调用）", not made, str(made))
    # 唯一的名单引用来自 run.roster 的转发，不是自带实现
    check("membership 里没有 Roster 的替代实现（无 members 列表字段定义）",
          not [rel for rel, s in src.items() if re.search(r"self\.members\s*=", s)], str(list(src)))


# ---------------------------------------------------------------- 2 职位
def t2_roles():
    print("\n[2] 职位：上限 / 互斥 / 幂等 / 在册 / 保序")
    r = Roster(["1001", "1002", "1003"])
    slots = RoleSlots({"lead": 1, "aide": 2}, roster=r)
    check("注入了名单 → roster 引用可查（不是副本）", slots.roster is r)
    check("在册 → 可任", slots.can_appoint("1001", "lead", r) is True)
    check("不在册 → 不可任", slots.can_appoint("9001", "lead", r) is False)
    check("未知职位 → 不可任", slots.can_appoint("1001", "nope", r) is False)
    check("未任命时 role_of → None", slots.role_of("1001") is None)
    check("holders 未知职位 → []", slots.holders("nope") == [])

    slots.appoint("1001", "lead")
    check("任命后 role_of", slots.role_of("1001") == "lead")
    check("★ 上限 cap=1：第二人被判不可任", slots.can_appoint("1002", "lead", r) is False)
    try:
        slots.appoint("1002", "lead")
        check("★ 上限 cap=1：第二人 appoint → RoleNotAllowed", False)
    except RoleNotAllowed:
        check("★ 上限 cap=1：第二人 appoint → RoleNotAllowed", True)
    check("被拒者没有拿到职位", slots.role_of("1002") is None)
    check("被拒者不在 holders 里", slots.holders("lead") == ["1001"])

    slots.appoint("1002", "aide")
    slots.appoint("1003", "aide")
    check("cap=2 的两职装满", slots.holders("aide") == ["1002", "1003"])
    try:
        slots.appoint("1001", "aide")
        check("★ 满员后再任命 → RoleNotAllowed", False)
    except RoleNotAllowed:
        check("★ 满员后再任命 → RoleNotAllowed", True)

    # 幂等：同人重复任命同职 → 不抛、不重复计
    slots.appoint("1001", "lead")
    check("★ 重复任命同职 → 幂等（holders 不多一条）", slots.holders("lead") == ["1001"])
    check("★ 幂等后 role_of 不变", slots.role_of("1001") == "lead")
    check("★ 幂等后 can_appoint 仍为 False（已是该职）",
          slots.can_appoint("1001", "lead", r) is False)

    # 互斥
    ex = RoleSlots({"lead": 1, "aide": 2}, roster=r, exclusive=True)
    ex.appoint("1001", "lead")
    check("★ exclusive：已在任 lead → 不能再任 aide",
          ex.can_appoint("1001", "aide", r) is False)
    try:
        ex.appoint("1001", "aide")
        check("★ exclusive：两职同任 → RoleNotAllowed", False)
    except RoleNotAllowed:
        check("★ exclusive：两职同任 → RoleNotAllowed", True)
    check("互斥被拒后职位不变", ex.role_of("1001") == "lead")
    ex.demote("1001")
    check("免职后可改任它职（互斥解除）", ex.can_appoint("1001", "aide", r) is True)

    # 免职：幂等、未知成员不炸
    slots.demote("1002")
    check("demote 清职位", slots.role_of("1002") is None and slots.holders("aide") == ["1003"])
    slots.demote("1002")
    slots.demote("9001")
    check("demote 不任任何职 / 未知成员 → 空操作（幂等）", slots.holders("aide") == ["1003"])
    check("免职后空出的槽可以再任", slots.can_appoint("1002", "aide", r) is True)

    # 上限 0 = 谁都不能任；纯槽位表（未注入名单）
    zero = RoleSlots({"ghost": 0}, roster=r)
    check("cap=0 → 谁都不能任", zero.can_appoint("1001", "ghost", r) is False)
    bare = RoleSlots({"x": 1})
    bare.appoint("whoever", "x")
    check("未注入名单 = 纯槽位表（不判在册、按任命序）",
          bare.roster is None and bare.holders("x") == ["whoever"])

    # fail-closed：上限给错当场报错
    for bad, exc in (({"x": -1}, ValueError), ({"x": "1"}, TypeError), ({"x": True}, TypeError),
                     ({"": 1}, ValueError)):
        try:
            RoleSlots(bad)
            check(f"非法职位表 {bad!r} → 报错", False)
        except exc:
            check(f"非法职位表 {bad!r} → {exc.__name__}", True)


# ---------------------------------------------------------------- 3 贡献
def t3_contribution():
    print("\n[3] 贡献：加后累计 / 排名 / 跨窗口 / rotate 幂等")
    led = {}
    week = {"k": "2026-W38"}
    c = Contribution(led, lambda: week["k"])
    check("注入了名单 → roster 引用可查（未注入为 None）", c.roster is None)
    check("★ add 返回值 = 加后累计", c.add("1001", 3) == 3 and c.add("1001", 2) == 5)
    check("of 读累计", c.of("1001") == 5)
    check("没记过的人 / 窗口 → 0", c.of("9001") == 0 and c.of("1001", window="week") == 0)
    check("负数也能记", c.add("1002", -2) == -2)
    check("周窗口独立累计", c.add("1001", 4, window="week") == 4)
    check("周窗口不影响 total", c.of("1001", window="week") == 4 and c.of("1001") == 5)

    # 排名：降序 + 同分保序（名单序）
    led2 = {}
    r = Roster(["m2", "m1", "m3"])
    c2 = Contribution(led2, lambda: "w1", roster=r)
    c2.add("m3", 5)                     # 账本序：m3, m1（与名单序 m2, m1, m3 不同）
    c2.add("m1", 5)
    c2.add("m2", 10)
    check("★ ranking 值降序", c2.ranking() == [("m2", 10), ("m1", 5), ("m3", 5)],
          str(c2.ranking()))
    check("★ ranking 同分按**名单序**（不是账本序）",
          [m for m, _ in c2.ranking()] == ["m2", "m1", "m3"], str(c2.ranking()))
    check("top=N 取前 N", c2.ranking(top=2) == [("m2", 10), ("m1", 5)])
    check("top=0 → []", c2.ranking(top=0) == [])
    check("top 超过条数 → 全给", len(c2.ranking(top=99)) == 3)
    c3 = Contribution({}, lambda: "w1")
    c3.add("m3", 5)
    c3.add("m1", 5)
    check("未注入名单 → 同分按账本序（同一条规则，名单为空）",
          c3.ranking() == [("m3", 5), ("m1", 5)], str(c3.ranking()))

    # ★ 跨窗口：period_key 指向次周 → 周窗口归零、total 不变
    week["k"] = "2026-W39"
    check("★ 跨窗口：周窗口归零", c.of("1001", window="week") == 0)
    check("★ 跨窗口：total 不变", c.of("1001") == 5)
    c.add("1001", 1, window="week")
    check("新周期重新起算", c.of("1001", window="week") == 1)
    # 反证（in-test）：period_key 固定 → 不归零
    cf = Contribution({}, lambda: "2026-W38")
    cf.add("1001", 7, window="week")
    cf.rotate()
    check("★ 反证：period_key 固定 → rotate 后周窗口不归零", cf.of("1001", window="week") == 7)

    # rotate：清旧周期，幂等，绝不动 total
    total_before = c.of("1001")
    c.rotate()
    snap = repr(led)
    c.rotate()
    check("★ rotate 幂等（第二次调用账本一字不改）", repr(led) == snap)
    check("★ rotate 不动 total", c.of("1001") == total_before == 5)
    check("rotate 清掉旧周期桶", "2026-W38" not in led.get("week", {}), str(led))
    check("rotate 保留当前周期桶", c.of("1001", window="week") == 1)
    check("rotate 不碰 total 桶", led.get("total", {}).get("1001") == 5)

    # fail-closed
    for bad_call, exc in (
        (lambda: Contribution([], lambda: "w"), TypeError),
        (lambda: Contribution({}, "not-callable"), TypeError),
        (lambda: Contribution({}, lambda: None).of("a", window="w"), TypeError),
        (lambda: Contribution({}, lambda: "").of("a", window="w"), TypeError),
        (lambda: Contribution({}, lambda: "w").add("a", "3"), TypeError),
        (lambda: Contribution({"total": 5}, lambda: "w").of("a"), TypeError),
    ):
        try:
            bad_call()
            check("非法注入 / 非法账本 → 报错（不静默当空）", False)
        except exc:
            check("非法注入 / 非法账本 → 报错（不静默当空）", True)
    try:
        Contribution({}, lambda: "w").ranking(top=-1)
        check("top 负数 → 报错", False)
    except ValueError:
        check("top 负数 → 报错", True)


# ---------------------------------------------------------------- 4 申请
def t4_applications():
    print("\n[4] 申请：去重 / 满 / 通过 / 拒绝 / 保序")
    q = Applications(cap=2)
    check("cap_of", q.cap_of() == 2 and Applications().cap_of() is None)
    check("push → True", q.push("x") is True)
    check("★ 重复 push → False（幂等）", q.push("x") is False)
    check("pending 保序", q.pending() == ["x"])
    check("push 第二人", q.push("y") is True)
    try:
        q.push("z")
        check("★ 满 → QueueFull", False)
    except QueueFull:
        check("★ 满 → QueueFull", True)
    check("满被拒者没进队", q.pending() == ["x", "y"])
    check("approve 不在队列 → False", q.approve("zz") is False)
    check("reject 不在队列 → False", q.reject("zz") is False)
    check("reject 出队", q.reject("y") is True and q.pending() == ["x"])
    check("★ approve 出队并返回 True", q.approve("x") is True and q.pending() == [])
    check("approve 已出队 → False（幂等）", q.approve("x") is False)
    check("pending 返回副本（改它不影响队列）",
          (lambda s: (s.append("污染"), q.pending())[1])(q.pending()) == [])
    check("腾出位置后可再入队", q.push("z") is True)
    z = Applications(cap=0)
    try:
        z.push("a")
        check("cap=0 → 任何入队 QueueFull", False)
    except QueueFull:
        check("cap=0 → 任何入队 QueueFull", True)
    for bad, exc in ((-1, ValueError), ("2", TypeError), (True, TypeError)):
        try:
            Applications(bad)
            check(f"非法 cap {bad!r} → 报错", False)
        except exc:
            check(f"非法 cap {bad!r} → {exc.__name__}", True)

    # 成员集合只有一个：approve 入册走名单；reject 不入册
    r = Roster([])
    q2 = Applications(roster=r)
    check("注入了名单 → roster 引用可查", q2.roster is r)
    q2.push("1009")
    q2.approve("1009")
    check("★ approve 即入册（名单是唯一成员集合）", r.members == ["1009"] and "1009" in r)
    q2.push("1010")
    q2.reject("1010")
    check("★ reject 不入册", r.members == ["1009"])
    q3 = Applications()
    q3.push("1011")
    check("未注入名单 = 只出队（显式退化，可查 roster is None）",
          q3.approve("1011") is True and q3.roster is None and q3.pending() == [])


# ---------------------------------------------------------------- 5 复用名单（保序 / 不复制）
def t5_reuse():
    print("\n[5] Roster 复用：holders 顺序 == 名单顺序（且不缓存、不复制）")
    r = Roster(["a", "b", "c"])
    slots = RoleSlots({"x": 3}, roster=r)
    slots.appoint("c", "x")
    slots.appoint("a", "x")
    slots.appoint("b", "x")
    check("★ holders 顺序 = 名单顺序（任命序被无视：任命序是 c,a,b）",
          slots.holders("x") == ["a", "b", "c"], str(slots.holders("x")))
    r.sort_by(lambda m: {"a": 1, "b": 2, "c": 3}[m], reverse=True)
    check("★ 名单重排后 holders 跟着变（读的是引用不是副本）",
          slots.holders("x") == ["c", "b", "a"], str(slots.holders("x")))
    r.leave("b")
    check("★ 离册者立刻不再占槽 / 不出现在 holders",
          slots.holders("x") == ["c", "a"] and slots.role_of("b") == "x")
    r3 = Roster(["m1", "m2"])
    s3 = RoleSlots({"z": 1}, roster=r3)
    s3.appoint("m1", "z")
    r3.leave("m1")
    check("★ 离册者不再占上限（空出的槽可再任，不必先 demote）",
          s3.holders("z") == [] and s3.can_appoint("m2", "z", r3) is True)

    r2 = Roster(["p", "q"])
    c = Contribution({}, lambda: "w", roster=r2)
    c.add("p", 1)
    c.add("q", 1)
    check("贡献排名读的是同一份名单（同分按名单序）",
          [m for m, _ in c.ranking()] == ["p", "q"], str(c.ranking()))
    r2.sort_by(lambda m: 0 if m == "q" else 1, reverse=False)
    check("名单重排后贡献同分序跟着变", [m for m, _ in c.ranking()] == ["q", "p"], str(c.ranking()))

    q = Applications(roster=r2)
    before = list(r2.members)
    q.push("zz")
    q.reject("zz")
    check("排队 / 拒绝不写名单（名单只在 approve 时被 join 一次）", r2.members == before)


# ---------------------------------------------------------------- 6 零知识
def t6_zero_knowledge():
    print("\n[6] 零知识：membership 源码里不得出现具体游戏的词汇")
    banned = ("guild", "party", "player", "monster", "quest", "dungeon", "item", "gold",
              "faith", "melody", "fury", "randuin", "dragonfall",
              "公会", "会长", "职业", "玩家", "队伍", "副本", "怪物", "金币", "物品",
              "等级", "经验", "战意", "旋律", "连段", "信仰", "奥术", "狂暴",
              "奥兰迪亚", "余烬")
    bad = []
    for rel, src in _membership_sources().items():
        for i, line in enumerate(src.splitlines(), 1):
            low = line.lower()
            for b in banned:
                hit = (b in low) if b.isascii() else (b in line)
                if hit and b.isascii():
                    hit = re.search(r"(?<![A-Za-z0-9_])" + re.escape(b) + r"(?![A-Za-z0-9_])",
                                    low) is not None
                if hit:
                    bad.append(f"{rel}:{i}:{b}")
    check("★ membership 零游戏词汇（guild/party/公会 等一概不许出现）", not bad, str(bad[:6]))
    check("模块 docstring 在（形状自带说明）", bool(MEMBERSHIP.__doc__))
    check("门面转出五个符号（职位 / 贡献 / 申请 + 两个异常）",
          MEMBERSHIP.__all__ == ["RoleSlots", "RoleNotAllowed", "Contribution",
                                 "Applications", "QueueFull"], str(MEMBERSHIP.__all__))


def main():
    print("== membership 门禁：职位 / 贡献 / 申请 / 单一名单 / 零知识 ==")
    t1_single_roster()
    t2_roles()
    t3_contribution()
    t4_applications()
    t5_reuse()
    t6_zero_knowledge()
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
