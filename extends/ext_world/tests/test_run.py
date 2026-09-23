#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""run 门禁：准入链 / 进度 / 名单 / 零知识。

跑法：python tests/test_run.py
退出码：0 = 全绿；1 = 有失败。

三处专门钉住的地方（都是「改了就静默变行为」的）：
  ① **首拒即返**：第一条拒绝之后的规则 `check` **一次都不许被调用**（旧实现就是 `return` 语义）
  ② **副作用延迟**：`consume` 只在全过之后按声明序各执行一次 —— 拒绝路径上**一次都不许执行**
     （「校验中段先扣东西、后面又拒绝」的白扣，从形状上不可能）
  ③ **零知识**：`run/` 源码常量里不得出现任何内容侧取值（层/房间/钥匙/队伍/金币带这类名词）
"""
import ast
import importlib
import os
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

import saintess_engine as SE                                                    # noqa: E402
from ext_world.run import (DENY, PASS, SKIP, Admission, Progress,         # noqa: E402
                                 Roster, Rule, Verdict)

passed = failed = 0


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


# ---------------------------------------------------------------- 1 准入链
def t1_admission():
    print("\n[1] 准入链：顺序 / 首拒即返 / 措辞")
    called = []

    def mk(name, ok):
        def _c(ctx):
            called.append(name)
            return ok
        return Rule(name, check=_c, reason=f"{name} 不行")

    v = Admission([mk("a", True), mk("b", True), mk("c", True)]).check({})
    check("全过：ok=True", v.ok and bool(v) and not v.denied)
    check("全过：rule=None / reason=''", v.rule is None and v.reason == "")
    check("全过：三条都判过（顺序与声明序一致）", called == ["a", "b", "c"], str(called))

    called.clear()
    v2 = Admission([mk("a", True), mk("b", False), mk("c", True)]).check({})
    check("首拒：ok=False 且 rule='b'", not v2.ok and v2.rule == "b", repr(v2))
    check("★ 首拒即返：拒绝之后的规则一次都不判", called == ["a", "b"], str(called))
    check("拒绝理由用该规则的 reason", v2.reason == "b 不行", repr(v2.reason))
    check("★ trace 把后续记成 skip", v2.trace == (("a", PASS, ""), ("b", DENY, "b 不行"),
                                                  ("c", SKIP, "")), str(v2.trace))

    # 就地给措辞：check 返回 str
    v3 = Admission([Rule("x", check=lambda c: "现场措辞")]).check({})
    check("check 返回 str → 用这个字符串当理由", v3.reason == "现场措辞")
    # reason 是 callable
    v4 = Admission([Rule("y", check=lambda c: False,
                         reason=lambda c: f"还差 {c['gap']}")]).check({"gap": 3})
    check("reason 支持 callable(ctx)", v4.reason == "还差 3", repr(v4.reason))
    # 默认措辞
    v5 = Admission([Rule("z", check=lambda c: False)]).check({})
    check("没给 reason → 默认「未通过：<name>」", v5.reason == "未通过：z", repr(v5.reason))
    # 无 check 的规则 = 无条件通过
    check("无 check 的规则恒通过", Admission([Rule("nop")]).check({}).ok)
    # 非布尔返回要报错（不静默当通过）
    try:
        Admission([Rule("bad", check=lambda c: 0)]).check({})
        check("check 返回非法类型 → 报错（不静默）", False)
    except TypeError:
        check("check 返回非法类型 → 报错（不静默）", True)
    # 规则内异常不吞
    def _boom(ctx):
        raise RuntimeError("内容侧 bug")
    try:
        Admission([Rule("boom", check=_boom)]).check({})
        check("规则内异常不吞（内容侧 bug 当场暴露）", False)
    except RuntimeError:
        check("规则内异常不吞（内容侧 bug 当场暴露）", True)


# ---------------------------------------------------------------- 2 副作用延迟
def t2_consume():
    print("\n[2] ★ 副作用延迟：全过才执行，按声明序各一次")
    log = []

    def _mk(name, ok, with_consume=True):
        return Rule(
            name,
            check=lambda c, _ok=ok, _n=name: log.append(f"check:{_n}") or _ok,
            reason=f"{name} no",
            consume=(lambda c, _n=name: log.append(f"consume:{_n}")) if with_consume else None,
        )

    v = Admission([_mk("a", True), _mk("b", True, with_consume=False), _mk("c", True)]).check({})
    check("全过 → 副作用按声明序执行", log == ["check:a", "check:b", "check:c",
                                               "consume:a", "consume:c"], str(log))
    check("全过 → v.consumed=True", v.consumed)

    log.clear()
    v2 = Admission([_mk("a", True), _mk("b", False), _mk("c", True)]).check({})
    check("★ 被拒 → 一个副作用都没执行（白扣从形状上不可能）",
          log == ["check:a", "check:b"], str(log))
    check("被拒 → v.consumed=False", not v2.consumed)

    # on_pass 钩子
    hits = []
    Admission([_mk("a", True)], on_pass=lambda c: hits.append(1)).check({})
    check("on_pass 在全过（含 consume）之后调一次", hits == [1], str(hits))
    hits.clear()
    Admission([_mk("a", False)], on_pass=lambda c: hits.append(1)).check({})
    check("被拒 → on_pass 不调", hits == [])

    # 真实形态：钥匙扣减只在位置/体力都过了之后
    state = {"keys": 1, "at_gate": False}
    adm = Admission([
        Rule("key", check=lambda c: c["keys"] > 0, reason="没钥匙",
             consume=lambda c: c.__setitem__("keys", c["keys"] - 1)),
        Rule("place", check=lambda c: c["at_gate"], reason="位置不对"),
    ])
    v3 = adm.check(state)
    check("★ 复刻旧坑：位置不过 → 钥匙**没被扣**（旧实现此处已扣走）",
          (not v3.ok) and v3.rule == "place" and state["keys"] == 1, str(state))
    state["at_gate"] = True
    check("位置过了 → 钥匙扣 1", adm.check(state).ok and state["keys"] == 0)


# ---------------------------------------------------------------- 3 审计
def t2b_any_mode():
    print("\n[2b] ★ any 模式：任一满足即放行（多条放行通道）")
    seen = []

    def mk(name, ok):
        def _c(ctx):
            seen.append(name)
            return ok
        return Rule(name, check=_c, reason=f"{name} 不满足")

    seen.clear()
    v = Admission([mk("a", False), mk("b", True), mk("c", True)],
                  mode="any", reason="都不满足").check({})
    check("任一通过 → ok=True", v.ok and v.rule is None and v.reason == "")
    check("★ 首个通过即止（后面的不再判）", seen == ["a", "b"], str(seen))
    check("trace 把后面的记成 skip", v.trace == (("a", DENY, "a 不满足"), ("b", PASS, ""),
                                                ("c", SKIP, "")), str(v.trace))
    seen.clear()
    v2 = Admission([mk("a", False), mk("b", False)], mode="any", reason="都不满足").check({})
    check("全不过 → 用链级 reason", (not v2.ok) and v2.reason == "都不满足", repr(v2))
    check("全不过 → 所有规则都判过", seen == ["a", "b"], str(seen))
    v3 = Admission([mk("a", False), mk("b", False)], mode="any").check({})
    check("没给链级 reason → 取末条规则的理由", v3.reason == "b 不满足", repr(v3.reason))
    hits = []
    Admission([Rule("k", check=lambda c: True, consume=lambda c: hits.append(1))],
              mode="any").check({})
    check("any 模式：通过那条规则的 consume 执行一次", hits == [1], str(hits))
    hits.clear()
    Admission([Rule("k", check=lambda c: False, consume=lambda c: hits.append(1))],
              mode="any").check({})
    check("any 模式：未通过的规则不执行 consume", hits == [], str(hits))
    check("any 空链 → 拒绝且理由为空串（不谎报放行）",
          Admission([], mode="any").check({}).ok is False)
    try:
        Admission([], mode="xor")
        check("非法 mode → 报错", False)
    except ValueError:
        check("非法 mode → 报错", True)


def t3_audit():
    print("\n[3] 准入链结构自检（只报不改）")
    check("空链 → 报「空链」", Admission([]).audit() and "空链" in Admission([]).audit()[0])
    check("重名 → 报重复",
          any("重复" in p for p in Admission([Rule("a"), Rule("a")]).audit()))
    check("空规则（无 check 无 consume）→ 报",
          any("空规则" in p for p in Admission([Rule("e")]).audit()))
    check("只有 consume 的规则不算空", Admission([Rule("c", consume=lambda c: None)]).audit() == [])
    check("非 Rule 成员 → 报", any("非 Rule" in p for p in Admission([object()]).audit()))
    check("干净链 → 零问题",
          Admission([Rule("a", check=lambda c: True), Rule("b", check=lambda c: True)]).audit() == [])
    check("rule_names 保序", Admission([Rule("a", check=lambda c: True),
                                        Rule("b", check=lambda c: True)]).rule_names() == ("a", "b"))


# ---------------------------------------------------------------- 4 进度
def t4_progress():
    print("\n[4] 进度：节点 / 位置 / 剩余池")
    p = Progress([{"key": "n1", "label": "一号"}, {"key": "n2", "label": "二号"},
                  {"key": "n3", "label": "三号"}])
    check("节点保序", p.keys == ("n1", "n2", "n3"))
    check("当前位置 = 首个节点", p.current_key == "n1" and p.index == 0)
    check("label_of / node 查得到", p.label_of("n2") == "二号" and p.node("n1") == {"key": "n1", "label": "一号"})
    check("index_of / has（不存在 → -1/False）", p.index_of("n3") == 2 and p.index_of("zz") == -1
          and p.has("n9") is False)
    check("is_last / next_key", p.is_last() is False and p.next_key() == "n2")
    check("goto 未知节点 → False 且不动", p.goto("zz") is False and p.current_key == "n1")
    check("goto 已知节点 → 定位", p.goto("n3") and p.current_key == "n3" and p.is_last())
    check("末节点 advance → False 且不越界", p.advance() is False and p.current_key == "n3")
    check("set_index 越界 → False", p.set_index(9) is False and p.set_index(1) and p.current_key == "n2")
    check("字符串节点也可用（label=自身）", Progress(["a", "b"]).label_of("a") == "a")

    # 剩余池：FIFO
    p.push("n1", "units", "m1")
    p.push("n1", "units", "m2")
    p.push_many("n1", "units", ["m3", "m4"])
    check("push 尾插 + push_many 保序", p.items("n1", "units") == ["m1", "m2", "m3", "m4"])
    check("take 弹首项（先放先出）", p.take("n1", "units") == "m1" and p.left("n1", "units") == 3)
    check("drop 按值移除", p.drop("n1", "units", "m3") and p.left("n1", "units") == 2)
    check("drop 不存在的值 → False（不抛错）", p.drop("n1", "units", "zz") is False)
    snap = p.items("n1", "units")
    snap.append("污染")
    check("items 返回副本（改副本不影响池）", p.left("n1", "units") == 2)
    check("空池 take → None", p.take("n9", "units") is None and p.take("n1", "nope") is None)
    check("left/items 未知节点 → 0/[]（不抛错）", p.left("zz", "x") == 0 and p.items("zz", "x") == [])
    p.push("n1", "marks", "a")
    check("pools_of 列出各池剩余", p.pools_of("n1") == {"units": 2, "marks": 1}, str(p.pools_of("n1")))
    check("node_cleared：有剩余 → False", p.node_cleared("n1") is False)
    check("node_cleared：未知节点 → False", p.node_cleared("zz") is False)
    p.take("n1", "units"); p.take("n1", "units"); p.take("n1", "marks")
    check("全池空 → node_cleared True", p.node_cleared("n1") is True)
    check("total_left 统计全节点", p.total_left() == 0)
    p.push("n2", "units", "x")
    p.push("n3", "units", "y")
    check("done：还有未清节点 → False", p.done is False)
    p.take("n2", "units"); p.take("n3", "units")
    check("★ 全节点清空 → done True", p.done is True)
    check("空节点表 done=False（不谎报清空）", Progress([]).done is False)
    check("未创建池的节点算已清（缺字段不是有内容）", Progress(["a"]).node_cleared("a") is True)

    # 往返
    q = Progress([{"key": "a", "label": "甲"}, {"key": "b", "label": "乙"}], index=1)
    q.push("b", "units", 1); q.push("b", "units", 2); q.set_budget("coin", 7)
    d = q.to_dict()
    q2 = Progress.from_dict(d)
    check("to_dict/from_dict 往返：位置与池一致",
          (q2.keys, q2.index, q2.items("b", "units"), q2.budget("coin"))
          == (("a", "b"), 1, [1, 2], 7))
    check("往返是深拷贝（改副本不影响原对象）",
          (q2.push("b", "units", 9), q.left("b", "units"))[1] == 2)
    check("节点 label 往返保留", q2.label_of("a") == "甲")


# ---------------------------------------------------------------- 5 预算
def t5_budget():
    print("\n[5] 预算：不足只给剩余 / 三种预算形态")
    p = Progress(["a"])
    p.set_budget("coin", 500)
    check("计数预算：够则全给", p.spend("coin", 300) == 300 and p.budget("coin") == 200)
    check("★ 计数预算：不足只给剩余", p.spend("coin", 900) == 200 and p.budget("coin") == 0)
    check("再扣 → 0（不出现负数）", p.spend("coin", 5) == 0 and p.budget("coin") == 0)
    check("want=0 / 负数 → 0", p.spend("coin", 0) == 0 and p.spend("coin", -3) == 0)
    check("未知预算 → 0（不抛错）", p.spend("nope", 3) == 0 and p.budget("nope") == 0)
    p.set_budget("mats", {"iron": 2})
    check("计数表预算：够则扣一件", p.spend_one("mats", "iron") is True
          and p.budget("mats") == {"iron": 1})
    p.spend_one("mats", "iron")
    check("★ 计数表预算：不够 → False 且不变负数", p.spend_one("mats", "iron") is False
          and p.budget("mats") == {"iron": 0})
    p.set_budget("eq", ["sword"])
    check("清单预算：在则移除", p.spend_one("eq", "sword") is True and p.budget("eq") == [])
    check("清单预算：不在 → False", p.spend_one("eq", "sword") is False)
    check("清单预算：可以有重复件（只移一个）",
          (p.set_budget("eq2", ["s", "s"]), p.spend_one("eq2", "s"), p.budget("eq2"))[2] == ["s"])
    try:
        p.spend("mats", 1)
        check("形态不匹配 → 报错（不静默按 0 处理）", False)
    except TypeError:
        check("形态不匹配 → 报错（不静默按 0 处理）", True)
    try:
        p.spend_one("coin", "x")
        check("spend_one 用在计数预算上 → 报错", False)
    except TypeError:
        check("spend_one 用在计数预算上 → 报错", True)
    check("budget 默认值可给", p.budget("missing", default=-1) == -1)


# ---------------------------------------------------------------- 6 名单
def t6_roster():
    print("\n[6] 名单：保序 / 队长 / 存活 / 过滤排序")
    r = Roster(["1001", "1002", "1003"], leader="1001")
    check("成员保序 + 队长", r.members == ["1001", "1002", "1003"] and r.leader == "1001")
    check("不给队长 → 首个成员当队长", Roster(["a", "b"]).leader == "a")
    check("空名单 → 队长 None", Roster([]).leader is None)
    check("len / in / is_member / index_of", len(r) == 3 and "1002" in r and r.is_member("1002")
          and r.index_of("1003") == 2 and r.index_of("zz") == -1)
    check("★ 未登记成员视为存活（缺字段不是死亡）", r.alive("1002") is True)
    r.mark_dead("1002")
    check("mark_dead → living 只剩存活", r.living() == ["1001", "1003"])
    check("alive_map 按成员列全", r.alive_map == {"1001": True, "1002": False, "1003": True})
    check("any_alive", r.any_alive() is True)
    r.set_alive("1002", True)
    check("revive/set_alive 复位", r.alive("1002") is True)
    r.set_alive("1002", False)
    check("keep 过滤（保序）", r.keep(lambda m: m != "1002") == ["1001", "1003"])
    check("★ only 取子集按**成员原序**（不是传入序）", r.only(["1003", "1001"]) == ["1001", "1003"])
    check("only 忽略名单外 key", r.only(["1003", "zz"]) == ["1003"])
    spd = {"1001": 10, "1002": 30, "1003": 20}
    r.sort_by(lambda m: spd[m], reverse=True)
    check("sort_by 原位重排（降序）", r.members == ["1002", "1003", "1001"])
    r.sort_by(lambda m: spd[m], reverse=False)
    check("sort_by 升序", r.members == ["1001", "1003", "1002"])
    check("join 追加 / 幂等", r.join("1004") is True and r.join("1004") is False
          and r.members == ["1001", "1003", "1002", "1004"])
    check("leave 移除", r.leave("1002") is True and r.leave("1002") is False)
    r2 = Roster(["a", "b"], leader="a")
    r2.leave("a")
    check("★ 队长离队 → 顺位给剩下第一个", r2.leader == "b")
    r2.leave("b")
    check("名单空 → 队长 None", r2.leader is None)
    check("成员全死 → any_alive False", Roster(["a"], alive={"a": False}).any_alive() is False)
    d = r.to_dict()
    r3 = Roster.from_dict(d)
    check("to_dict/from_dict 往返", (r3.members, r3.leader) == (r.members, r.leader))
    r3.join("zz")
    check("往返是深拷贝（改副本不影响原对象）", "zz" not in r.members)


# ---------------------------------------------------------------- 7 审计
def t7_audit():
    print("\n[7] 进度 / 名单结构自检")
    p = Progress([{"key": "a"}, {"key": "a"}])
    check("节点 key 重复 → 报", any("重复" in x for x in p.audit()))
    check("位置越界 → 报", any("越界" in x for x in Progress(["a"], index=5).audit()))
    bad = Progress(["a"])
    bad.push("zz", "units", 1)
    check("池挂在不存在的节点上 → 报", any("不存在" in x for x in bad.audit()))
    check("干净进度 → 零问题", Progress(["a", "b"]).audit() == [])
    r = Roster(["a", "a"], leader="b")
    check("成员重复 → 报", any("重复" in x for x in r.audit()))
    check("队长不在名单 → 报", any("队长不在名单" in x for x in r.audit()))
    r2 = Roster(["a"], leader="a")
    r2.set_alive("zz", True)
    check("存活表含名单外成员 → 报", any("名单外" in x for x in r2.audit()))
    check("干净名单 → 零问题", Roster(["a"], leader="a").audit() == [])


# ---------------------------------------------------------------- 8 零知识
def t8_zero_knowledge():
    print("\n[8] 零知识：引擎源码常量里不得出现内容侧取值")
    BANNED = ("副本", "房间", "关卡", "钥匙", "城镇", "野外", "队伍", "金币", "材料", "装备",
              "怪物", "职业", "等级", "dungeon", "instance", "player", "monster", "item",
              "gold", "equip", "level", "quest", "stage", "room", "key_item")
    bad = []
    for root, _dirs, files in os.walk(os.path.join(ROOT, "extends", "ext_world", "run")):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            with open(os.path.join(root, fn), encoding="utf-8") as f:
                tree = ast.parse(f.read())
            # 跳过**文档串**（模块/类/函数 docstring）：文档要能解释「分层 / 房间 / 队伍」
            # 这类形状类比本身，判据针对的是**代码里写死的取值**（那才是"把某款游戏焊进引擎"）
            docs = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
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
                            bad.append(f"{fn}:{node.lineno}:{b}")
    check("★ 代码常量里无内容侧取值（取值/措辞只由内容侧给）", not bad, str(bad[:6]))


# ---------------------------------------------------------------- 9 门面
def t9_facade():
    print("\n[9] 门面：子模块与公开符号（run 已迁到扩展包 ext_world，2026-09-23）")
    EXT = importlib.import_module("ext_world")
    sub = importlib.import_module("ext_world.run")
    check("`ext_world.run` 是同一模块对象", EXT.run is sub)
    for sym in ("Admission", "Rule", "Verdict", "Progress", "Roster"):
        check(f"门面转出 {sym}", hasattr(EXT, sym) and getattr(EXT, sym) is getattr(sub, sym))
    check("`from ext_world import run, Roster` 可用",
          all(x in EXT.__all__ for x in ("run", "Admission", "Rule", "Progress", "Roster")))
    check("引擎门面不再转出 run（已迁扩展包）", not hasattr(SE, "run"))
    check("Verdict 可构造（真值随 ok）", bool(Verdict(True, None, "", None, (), True)) is True
          and bool(Verdict(False, "r", "x", None, (), False)) is False)


def main():
    print("== run 门禁：准入链 / 进度 / 名单 / 零知识 ==")
    t1_admission()
    t2_consume()
    t2b_any_mode()
    t3_audit()
    t4_progress()
    t5_budget()
    t6_roster()
    t7_audit()
    t8_zero_knowledge()
    t9_facade()
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
