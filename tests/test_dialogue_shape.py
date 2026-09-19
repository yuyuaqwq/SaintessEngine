#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""dialogue 门禁：对话树形状（`Dialogue` / `Cursor`）—— 规则逐条 / 兜底分支 / 零知识 / 口径分歧。

跑法：`python tests/test_dialogue_shape.py`
退出码：0 = 全绿；1 = 有失败（结尾打印 `结果：通过 X / 共 Y` + 失败清单）。

覆盖（照 `U1-I4_BATCHES.md` §1 的 L1 判据 + `U1-I4_DESIGN.md` §2 的规则表）：
  ① **规则逐条**：R-NEED / R-OPT / R-TEXT / R-ROUTE 每条规则一个断言，
     **每一条兜底分支各一个断言**（未知节点回退 / 缺 text / 缺 next / 越界 / 展开为空 …）。
  ② **不变量**：I1 构造零遍历（探针树 + 成本对照）· I2 不缓存 · I3 不可变 · I6 注入面 fail-closed ·
     I7 异常不吞 · I8 对象标识 · I9 幂等。
  ③ **零知识静态扫描**（`ast`）：字符串常量零取值词 · import 只有标准库且不含禁用模块 ·
     不 import 谓词注册表（鸭子类型）。
  ④ **十条口径分歧各一条断言**（故意不同的两口径**断言「它们确实不同」**，防后人顺手统一）。
  ⑤ **多故障场景**（两处同时坏 + 第三处仍绿）与**顺序断言**（need 短路序 / 展开插入位 / pick 对齐）。
  ⑥ **视图 / 序列化**：全程产物是纯 JSON，`json.dumps` 可用；跑完树指纹不变。

> **「注册表语义」这一组不设**：本形状**没有**引擎侧注册表（谓词表由内容侧注入，引擎只借
> `get(key)` 查表口，不持有、不登记、不缓存），故按「若适用」的口径跳过。
"""
import ast
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine.dialogue import END_KEY, Cursor, Dialogue  # noqa: E402

passed = failed = 0
DETAIL = []

# 注入面取值（**测试侧**给；引擎里没有任何默认值）。
END = "<<end>>"
FB = "FB"


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed", "DETAIL")


def raises(exc, fn, *a, **kw):
    """跑 fn → (是否抛该异常, 异常对象|None)。"""
    try:
        fn(*a, **kw)
    except exc as e:
        return True, e
    except Exception as e:                                     # noqa: BLE001
        return False, e
    return False, None


class Registry:
    """极简谓词查表口（引擎只要求 `.get(key)`；`None` = 未注册）。"""

    def __init__(self, fns=None):
        self.fns = dict(fns or {})

    def get(self, key):
        return self.fns.get(key)


def mk(tree=None, **kw):
    opt = dict(end_marker=END, conditions=Registry(),
               unknown=lambda k, v: True, fallback_text=FB)
    opt.update(kw)
    return Dialogue(tree, **opt)


# ─────────────────────────────────────────────────────────── ① I1 构造 O(1) / 零遍历
class _Tripwire(dict):
    """一碰就读的探针树：构造期若读它，立刻报错（证明「不遍历树」）。"""

    def get(self, *a, **kw):
        raise AssertionError("构造期读了树：get")

    def __getitem__(self, k):
        raise AssertionError("构造期读了树：[]")

    def __contains__(self, k):
        raise AssertionError("构造期读了树：in")

    def __iter__(self):
        raise AssertionError("构造期遍历了树：iter")

    def items(self):
        raise AssertionError("构造期遍历了树：items")

    def keys(self):
        raise AssertionError("构造期遍历了树：keys")

    def values(self):
        raise AssertionError("构造期遍历了树：values")


def t_construct_zero_walk():
    print("\n[1] I1 构造 O(1)：只校验注入面，不读树")
    tw = _Tripwire()
    dict.__setitem__(tw, "start", "a")
    dict.__setitem__(tw, "nodes", {})
    ok, why = True, ""
    try:
        d = mk(tw)
    except AssertionError as e:
        ok, why = False, str(e)
    check("★ 构造不读树（探针树的 get/[]/in/iter/items/keys/values 一次不碰）", ok, why)
    check("构造保留原对象（不拷贝：id 相同）", d.tree is tw)
    check("构造后无实例字典（不可变：只有 __slots__ 那几格）", not hasattr(d, "__dict__"))
    teeth = False
    try:
        d.node("a")
    except AssertionError:
        teeth = True
    check("探针有牙（一读就报错 → 上面那条不是「探针失效」的假绿）", teeth)

    big = {"start": "n0", "nodes": {f"n{i}": {"text": "t", "options": [{"text": "o"} for _ in range(3)]}
                                    for i in range(708)}}
    conds, unk = Registry(), (lambda k, v: True)
    import time

    def _loop(tree):
        t0 = time.perf_counter()
        for _ in range(20000):
            Dialogue(tree, end_marker=END, conditions=conds, unknown=unk, fallback_text=FB)
        return time.perf_counter() - t0

    t_big, t_empty = _loop(big), _loop({})
    check(f"大树构造耗时 ≈ 空树（零遍历：{t_big * 1e3:.0f}ms vs {t_empty * 1e3:.0f}ms）",
          t_big < t_empty * 3 + 0.5, f"{t_big:.3f}s vs {t_empty:.3f}s")


# ─────────────────────────────────────────────────────────── ② 读口
def t_read():
    print("\n[2] 读口：start / node / has / is_end / tree / of")
    snode = {"text": "S"}
    tree = {"start": "s", "nodes": {"s": snode, "x": None}}
    d = mk(tree)
    check("tree 属性 = 原对象（不拷贝）", d.tree is tree)
    check("start = 树上的 start 字段（不校验命中）", d.start == "s")
    check("start 缺失 → None（不补默认值）", mk({"nodes": {}}).start is None)
    check("node 命中 → 原对象（is 相同）", d.node("s") is snode)
    check("has 命中 → True", d.has("s") is True)
    check("★ 兜底：node 未知 id → 回退 start 节点（不是 {}）", d.node("zzz") is snode)
    check("has 不触发回退（未知 id → False）", d.has("zzz") is False)
    check("★ 兜底：node 未知 id 且 start 缺失 → {}", mk({"nodes": {}}).node("zzz") == {})
    check("★ 兜底：node 未知 id 且 nodes 缺失 → {}", mk({}).node("zzz") == {})
    check("★ 兜底：node 未知 id 且 tree=None → {}", mk(None).node("zzz") == {})
    check("is_end(结束哨兵) → True", d.is_end(END) is True)
    check("is_end(其它) → False", d.is_end("s") is False and d.is_end(None) is False)
    check("★ 口径⑨ 键在值为 None → 返回 None（不回退）", d.node("x") is None and d.node("zzz") is snode)
    fresh = d.of({"start": "q", "nodes": {"q": {"text": "Q"}}})
    check("of 返回新外壳（原外壳不动）", fresh is not d and d.tree is tree)
    check("of 共享注入面（新外壳仍认同一结束哨兵）", fresh.is_end(END) and fresh.node("q")["text"] == "Q")


# ─────────────────────────────────────────────────────────── ③ R-NEED
def _keyp(calls):
    def make(k):
        def _p(ctx, v):
            calls.append(k)
            return v
        return _p
    return make


def t_need():
    print("\n[3] R-NEED：need 判定（N1–N8 逐条）")
    calls = []
    d = mk(conditions=Registry({k: _keyp(calls)(k) for k in ("a", "b", "c")}))
    for need in (None, {}, [], "", 0):
        check(f"N1 假值 need={need!r} → 不限（True）", d.satisfied(need, {}) is True)
    hit, exc = raises(AttributeError, d.satisfied, "x", {})
    check("N2 need 非映射 → AttributeError（不吞、不降级）", hit, f"{exc!r}")
    calls.clear()
    check("N3 与关系：首个不满足即 False", d.satisfied({"a": True, "b": False, "c": True}, {}) is False)
    check("N3/N5 短路：后续键的谓词一次都没被调用", calls == ["a", "b"], calls)
    calls.clear()
    check("N3 按 dict 插入序（不重排）", d.satisfied({"c": True, "b": False, "a": True}, {}) is False
          and calls == ["c", "b"], calls)
    for label, val in (("False", False), ("None", None), ("0", 0), ("空串", ""), ("空表", [])):
        d2 = mk(conditions=Registry({"p": lambda c, v, _v=val: _v}))
        check(f"N5 谓词返回 {label} → False（真值判定）", d2.satisfied({"p": 1}, {}) is False)
    d3 = mk(conditions=Registry({"p": lambda c, v: 1}))
    check("N6 谓词返回真值 → 继续（全部过 → True）", d3.satisfied({"p": 1}, {}) is True)
    check("N7 无键 need 全过（多键）", d3.satisfied({"p": 1}, {}) is True)

    seen = []
    d4 = mk(unknown=lambda k, v: seen.append((k, v)) or True)
    check("★ 兜底 N4 未注册键 → 调 unknown；真 → 放行", d4.satisfied({"zz": 7}, {}) is True
          and seen == [("zz", 7)], seen)
    d5 = mk(unknown=lambda k, v: False)
    check("★ 兜底 N4 未注册键 → unknown 假 → False", d5.satisfied({"zz": 7}, {}) is False)
    boom = RuntimeError("unk")
    d6 = mk(unknown=lambda k, v: (_ for _ in ()).throw(boom))
    hit, exc = raises(RuntimeError, d6.satisfied, {"zz": 7}, {})
    check("N4 unknown 抛错 → 原样上抛", hit and exc is boom, f"{exc!r}")
    hit, exc = raises(RuntimeError, mk(conditions=Registry(
        {"p": lambda c, v: (_ for _ in ()).throw(RuntimeError("pred"))})).satisfied, {"p": 1}, {})
    check("N8 谓词抛错 → 原样上抛", hit, f"{exc!r}")


# ─────────────────────────────────────────────────────────── ④ R-OPT
def t_options():
    print("\n[4] R-OPT：可见选项（O1–O8 逐条）")
    d = mk()
    o1, o2, o3 = {"text": "1"}, {"text": "2"}, {"text": "3"}
    node = {"options": [o1, o2, o3]}
    out = d.options(node, {})
    check("O1 输出 = 声明序", [x["text"] for x in out] == ["1", "2", "3"], out)
    check("O7 普通项返回原对象（is 相同，不拷贝）", out[0] is o1 and out[1] is o2 and out[2] is o3)
    check("★ 兜底 O1 options 缺失 → []", d.options({}, {}) == [])
    check("★ 兜底 O1 options = None → []", d.options({"options": None}, {}) == [])
    check("★ 兜底 O8 need 不满足 → 跳过（保序）",
          mk(conditions=Registry({"no": lambda c, v: False})).options(
              {"options": [o1, dict(o2, need={"no": 1}), o3]}, {}) == [o1, o3])

    sm = {"text": "menu", "side_menu": {}}
    pm = {"text": "plain", "side_menu": None}
    check("★ 兜底 O2 side_menu={} → 走展开分支（expand=None → 整项消失）",
          d.options({"options": [sm, o1]}, {}) == [o1])
    check("★ 兜底 O2 side_menu=None → 普通分支（选项照常出现）",
          d.options({"options": [pm, o1]}, {}) == [pm, o1])
    called = []

    def exp(opt):
        called.append(opt)
        return [{"text": "s"}]

    d2 = mk(conditions=Registry({"no": lambda c, v: False}))
    check("★ 兜底 O3 展开分支 need 不满足 → 跳过且 expand 一次没调",
          d2.options({"options": [dict(sm, need={"no": 1})]}, {}, expand=exp) == [] and called == [])
    check("★ 兜底 O4 expand=None → subs=[] → 整项消失",
          d2.options({"options": [sm]}, {}, expand=None) == [])
    subs = [{"text": "s1"}, {"text": "s2"}]
    got = d2.options({"options": [o1, sm, o3]}, {}, expand=lambda o: subs)
    check("O5 展开项插回**该选项原来的位置**（不是追加末尾）",
          [x["text"] for x in got] == ["1", "s1", "s2", "3"], got)
    check("O5 展开项 = 回调给的对象（is 相同）", got[1] is subs[0] and got[2] is subs[1])
    check("★ 兜底 O6 展开为空 → 整项消失",
          d2.options({"options": [o1, sm, o3]}, {}, expand=lambda o: []) == [o1, o3])
    check("★ 兜底 O6 展开为假值（None）→ 整项消失",
          d2.options({"options": [sm]}, {}, expand=lambda o: None) == [])


# ─────────────────────────────────────────────────────────── ⑤ R-TEXT
def t_text():
    print("\n[5] R-TEXT：台词（T1–T5 逐条）")
    d = mk(text_sources={"auto": lambda node, ctx: ctx.get("auto_line")})
    check("口径④ T1 变体取声明序**第一条满足者**",
          d.text({"texts": [{"need": None, "text": "V1"}, {"need": None, "text": "V2"}], "text": "D"}, {}) == "V1")
    check("口径④ 两条对调 → 结果随之改变（确实按序，不是碰巧）",
          d.text({"texts": [{"need": None, "text": "V2"}, {"need": None, "text": "V1"}]}, {}) == "V2")
    d2 = mk(conditions=Registry({"no": lambda c, v: False}))
    check("★ 兜底 T1 首条变体不满足 → 取次条",
          d2.text({"texts": [{"need": {"no": 1}, "text": "V1"}, {"need": None, "text": "V2"}]}, {}) == "V2")
    hit, exc = raises(KeyError, d2.text, {"texts": [{"need": None}]}, {})
    check("口径⑤ 变体缺 text 键 → KeyError（不兜底）", hit, f"{exc!r}")
    check("口径⑤ 变体全部不满足且节点有 text → text（与上一条确实不同）",
          d2.text({"texts": [{"need": {"no": 1}, "text": "V"}], "text": "D"}, {}) == "D")
    check("T2 无变体、有 text → text", d2.text({"text": "D"}, {}) == "D")
    check("★ 兜底 T5 无变体、无 text → fallback_text", d2.text({}, {}) == FB)
    check("T3 text_from 命中注入表且返回真值 → 用它",
          d.text({"text_from": "auto", "text": "D"}, {"auto_line": "AUTO"}) == "AUTO")
    check("★ 兜底 T4 生成器返回空串 → 落 text",
          d.text({"text_from": "auto", "text": "D"}, {"auto_line": ""}) == "D")
    check("★ 兜底 T4 生成器返回 None → 落 fallback_text",
          d.text({"text_from": "auto"}, {"auto_line": None}) == FB)
    check("T1 变体优先于 text_from",
          d.text({"texts": [{"need": None, "text": "V"}], "text_from": "auto"}, {"auto_line": "AUTO"}) == "V")
    check("★ 兜底 T3 text_sources=None → 跳过自动源", mk().text({"text_from": "auto", "text": "D"}, {}) == "D")
    seen = []
    d3 = mk(text_sources={"known": lambda n, c: seen.append(1) or "X"})
    check("口径⑩ text_from 不在注入表内 → 不调任何生成器，落 text",
          d3.text({"text_from": "zzz", "text": "D"}, {}) == "D" and seen == [])
    d4 = mk(text_sources={"a": lambda n, c: "LA", "b": lambda n, c: "LB"})
    check("口径⑩ text_from 是「表」不是「枚举」（第二个取值照用，引擎零改动）",
          d4.text({"text_from": "a"}, {}) == "LA" and d4.text({"text_from": "b"}, {}) == "LB")


# ─────────────────────────────────────────────────────────── ⑥ R-ROUTE
def t_route():
    print("\n[6] R-ROUTE：pick / next_of / is_end（R1–R6 逐条）")
    d = mk()
    o = [{"text": "1", "next": "n1"}, {"text": "2"}]
    node = {"options": o}
    check("★ 兜底 R1 index=0 → None（0 的结束语义在调用方）", d.pick(node, 0, {}) is None)
    check("★ 兜底 R1 index=-1 → None", d.pick(node, -1, {}) is None)
    check("★ 兜底 R1 index=3（越界）→ None（不抛）", d.pick(node, 3, {}) is None)
    check("★ 兜底 R1 空选项表 → 任何 index 都 None", d.pick({"options": []}, 1, {}) is None)
    check("R2 index=1 → 第一个原对象", d.pick(node, 1, {}) is o[0])
    check("R2 index=2 → 第二个原对象", d.pick(node, 2, {}) is o[1])
    check("R3 next 存在 → 原样", d.next_of({"next": "n9"}) == "n9")
    check("★ 兜底 R3 next 缺失 → end_marker", d.next_of({"text": "x"}) == END)
    check("R4 failed 且有 fail_next → fail_next",
          d.next_of({"next": "a", "fail_next": "b"}, failed=True) == "b")
    check("★ 兜底 R4 failed 且无 fail_next → 回落 next",
          d.next_of({"next": "a"}, failed=True) == "a")
    check("★ 口径 R4 fail_next 存在但假值 → 就用它（**不回落**）",
          d.next_of({"next": "a", "fail_next": ""}, failed=True) == "")
    check("★ 兜底 R4 fail_next / next 都缺 → end_marker", d.next_of({}, failed=True) == END)
    check("R4 failed=False → 忽略 fail_next", d.next_of({"next": "a", "fail_next": "b"}) == "a")
    check("R5 is_end(哨兵) → True", d.is_end(END) is True)
    check("R5 is_end(其它 / None) → False", d.is_end("n1") is False and d.is_end(None) is False)
    check("R6 动作路由 token 对引擎不透明（原样带出）", d.next_of({"next": "route1"}) == "route1")


# ─────────────────────────────────────────────────────────── ⑦ Cursor
def t_cursor():
    print("\n[7] Cursor：值对象（state / of / moved_to / same_as）")
    c = Cursor("who", "n1")
    check("字段读口", (c.subject, c.node) == ("who", "n1"))
    check("state → 键名由调用方给（引擎不拼键）",
          c.state(subject_key="k1", node_key="k2") == {"k1": "who", "k2": "n1"})
    check("state 是纯 mapping（json.dumps 可用）",
          json.dumps(c.state(subject_key="npc", node_key="node"))
          == '{"npc": "who", "node": "n1"}')
    c2 = c.moved_to("n2")
    check("moved_to 返回**新**对象（不可变：原对象不动）",
          c2 is not c and (c2.subject, c2.node) == ("who", "n2") and (c.subject, c.node) == ("who", "n1"))
    check("same_as 同值 → True / 不同 → False",
          c.same_as(Cursor("who", "n1")) is True and c.same_as(c2) is False)
    check("same_as 非游标 → False", c.same_as(None) is False and c.same_as({"k1": "who"}) is False)
    raw = {"npc": "who", "node": "n1"}
    check("of 从存档映射还原（与构造出的同值）",
          Cursor.of(raw, subject_key="npc", node_key="node").same_as(Cursor("who", "n1")))
    for bad, label in ((None, "None"), ({}, "空 mapping"), ([], "list"), ("[]", "JSON 字符串"),
                       ("0", "字符串"), ({"npc": "who"}, "缺 node"), ({"node": "n1"}, "缺 subject"),
                       ({"npc": "", "node": "n1"}, "空 subject"), ({"npc": "who", "node": ""}, "空 node"),
                       ({"npc": 5, "node": "n1"}, "值非字符串")):
        check(f"★ 兜底 of 还原不出来 → None（{label}，不抛）",
              Cursor.of(bad, subject_key="npc", node_key="node") is None)
    check("of 键名可自定义（与 state 对称）",
          Cursor.of({"a": "x", "b": "y"}, subject_key="a", node_key="b")
          .state(subject_key="a", node_key="b") == {"a": "x", "b": "y"})
    check("口径⑦ 空 mapping 与坏值都回 None（**清理留在调用方**，引擎不做）",
          Cursor.of({}, subject_key="npc", node_key="node") is None
          and Cursor.of("[]", subject_key="npc", node_key="node") is None)


# ─────────────────────────────────────────────────────────── ⑧ I6/I7/I2/I3/I8/I9
def t_invariants():
    print("\n[8] 不变量：I6 注入面 fail-closed / I7 异常不吞 / I2 不缓存 / I3 I8 I9")
    reg, unk = Registry(), (lambda k, v: True)
    kw = dict(end_marker=END, conditions=reg, unknown=unk, fallback_text=FB)
    fails = [
        ("★ I6 缺 end_marker → TypeError", lambda: Dialogue()),
        ("★ I6 end_marker 非字符串 → TypeError", lambda: Dialogue(**dict(kw, end_marker=1))),
        ("★ I6 缺 conditions → TypeError", lambda: Dialogue(**{k: v for k, v in kw.items() if k != "conditions"})),
        ("★ I6 conditions 无 get 查表口 → TypeError", lambda: Dialogue(**dict(kw, conditions=object()))),
        ("★ I6 缺 unknown → TypeError", lambda: Dialogue(**{k: v for k, v in kw.items() if k != "unknown"})),
        ("★ I6 unknown 不可调用 → TypeError", lambda: Dialogue(**dict(kw, unknown="x"))),
        ("★ I6 缺 fallback_text → TypeError",
         lambda: Dialogue(**{k: v for k, v in kw.items() if k != "fallback_text"})),
        ("★ I6 fallback_text 非字符串 → TypeError", lambda: Dialogue(**dict(kw, fallback_text=5))),
        ("★ I6 text_sources 非查表口 → TypeError", lambda: Dialogue(**dict(kw, text_sources=[1]))),
    ]
    for label, fn in fails:
        hit, exc = raises(TypeError, fn)
        check(label, hit, f"{exc!r}")
    check("I6 text_sources=None 合法（唯一可选结构项）", isinstance(Dialogue(**kw), Dialogue))

    boom = RuntimeError("boom")

    def raiser(*a, **kw2):
        raise boom

    d = mk(conditions=Registry({"p": raiser}), text_sources={"s": raiser})
    hit, exc = raises(RuntimeError, d.satisfied, {"p": 1}, {})
    check("I7 谓词抛错 → 原样上抛", hit and exc is boom, f"{exc!r}")
    hit, exc = raises(RuntimeError, d.text, {"text_from": "s"}, {})
    check("I7 文本源抛错 → 原样上抛", hit and exc is boom, f"{exc!r}")
    hit, exc = raises(RuntimeError, d.options, {"options": [{"text": "m", "side_menu": {}}]}, {},
                      expand=raiser)
    check("I7 展开回调抛错 → 原样上抛", hit and exc is boom, f"{exc!r}")

    seq = [True, False]
    d2 = mk(conditions=Registry({"p": lambda c, v: seq.pop(0) if seq else True}))
    node = {"options": [{"text": "o", "need": {"p": 1}}]}
    r1, r2, r3 = d2.options(node, {}), d2.options(node, {}), d2.options(node, {})
    check("I2 不缓存：谓词序列 True/False/True → 三次结果随之变",
          len(r1) == 1 and len(r2) == 0 and len(r3) == 1, (len(r1), len(r2), len(r3)))

    tree = {"start": "a", "nodes": {
        "a": {"text": "A", "texts": [{"need": None, "text": "T"}],
              "options": [{"text": "o", "next": "b"}]},
        "b": {"text": "B"}}}
    d3 = mk(tree)
    node_a = d3.node("a")
    before = json.dumps(tree, sort_keys=True, ensure_ascii=False)
    snaps = [(d3.node("a"), d3.text(node_a, {}), [x["text"] for x in d3.options(node_a, {})],
              d3.pick(node_a, 1, {})["text"], d3.next_of({"next": "b"}), d3.is_end("b"))
             for _ in range(3)]
    check("I9 幂等：同一输入连调 3 次逐值相等", snaps[0] == snaps[1] == snaps[2])
    after = json.dumps(tree, sort_keys=True, ensure_ascii=False)
    check("I3 不可变：全程不改调用方的树（json 指纹前后一致）", before == after)
    opts = d3.options(node_a, {})
    check("I8 普通选项 = 传入原对象（is 相同）", opts[0] is node_a["options"][0])
    subs = [{"text": "s"}]
    got = d3.options({"options": [{"text": "m", "side_menu": {}}]}, {}, expand=lambda o: subs)
    check("I8 展开项 = 回调给的对象（is 相同）", got[0] is subs[0])


# ─────────────────────────────────────────────────────────── ⑨ 口径分歧十条
def t_divergences():
    print("\n[9] 十条口径分歧（每条一断言；故意不同的两口径断言「确实不同」）")
    snode = {"text": "S"}
    tree = {"start": "s", "nodes": {"s": snode, "x": None}}
    d = mk(tree)
    check("① 未知节点**回退 start**（不是判成结束）",
          d.node("zzz") is snode and d.is_end("zzz") is False)
    check("① 两口径确实不同：回退得到节点 / is_end 为 False",
          d.node("zzz") is not None and d.is_end("zzz") is not True)

    sm, pm = {"text": "m", "side_menu": {}}, {"text": "m", "side_menu": None}
    out_empty, out_null = d.options({"options": [sm]}, {}), d.options({"options": [pm]}, {})
    check("② side_menu={} 走展开（expand=None → 消失）；side_menu=None 走普通（出现）",
          out_empty == [] and out_null == [pm])
    check("② 两口径确实不同（{} 消失 vs None 出现）", out_empty != out_null)

    allow, deny = mk(unknown=lambda k, v: True), mk(unknown=lambda k, v: False)
    check("③ 未注册键三态不在引擎：注入策略决定放行 / 拦截",
          allow.satisfied({"zz": 1}, {}) is True and deny.satisfied({"zz": 1}, {}) is False)
    check("③ 两口径确实不同", allow.satisfied({"zz": 1}, {}) != deny.satisfied({"zz": 1}, {}))

    a = {"texts": [{"need": None, "text": "A"}, {"need": None, "text": "B"}]}
    b = {"texts": [{"need": None, "text": "B"}, {"need": None, "text": "A"}]}
    check("④ 变体取声明序第一条（不是「最具体」）", d.text(a, {}) == "A")
    check("④ 两口径确实不同（对调 → 结果对调）", d.text(a, {}) != d.text(b, {}))

    hit, _ = raises(KeyError, d.text, {"texts": [{"need": None}]}, {})
    check("⑤ 变体缺 text → KeyError；节点缺 text → 回落 fallback",
          hit and d.text({}, {}) == FB)
    check("⑤ 两条确实不同（一个炸、一个兜底）", hit and d.text({"text": "D"}, {}) == "D")

    o1 = {"text": "1"}
    check("⑥ options() 返回原对象（is 相同，不拷贝）", d.options({"options": [o1]}, {})[0] is o1)

    check("⑦ 空 mapping 与坏值都回 None（清残留的口径差异留在调用方）",
          Cursor.of({}, subject_key="npc", node_key="node") is None
          and Cursor.of("bad", subject_key="npc", node_key="node") is None)

    dn = mk(conditions=Registry({"p": lambda c, v: None}))
    check("⑧ 谓词返回 None → 不满足（不是「满足」）", dn.satisfied({"p": 1}, {}) is False)
    check("⑧ 两口径确实不同（真值判定 vs is False）",
          (dn.satisfied({"p": 1}, {}) is False) and (None is False) is False)

    check("⑨ 键在值为 None → 返回 None；键不在 → 回退 start",
          d.node("x") is None and d.node("zzz") is snode)

    seen = []
    d4 = mk(text_sources={"one": lambda n, c: "1", "two": lambda n, c: "2"})
    check("⑩ text_from 是注入表不是枚举（两个取值都走表）",
          d4.text({"text_from": "one"}, {}) == "1" and d4.text({"text_from": "two"}, {}) == "2")
    check("⑩ 表外取值 → 跳过（表 vs 枚举两口径确实不同）",
          d4.text({"text_from": "three", "text": "D"}, {}) == "D" and seen == [])


# ─────────────────────────────────────────────────────────── ⑩ 多故障 + 顺序
class _NeedBlind(Dialogue):
    __slots__ = ()

    def satisfied(self, need, ctx):
        return True                                    # 故障①：无视 need


class _LastVariant(Dialogue):
    __slots__ = ()

    def text(self, node, ctx):
        for variant in reversed(list(node.get("texts") or [])):
            if self.satisfied(variant.get("need"), ctx):
                return variant["text"]                 # 故障②：变体从末条往前取
        return super().text(node, ctx)


class _Both(_NeedBlind, _LastVariant):
    __slots__ = ()


def _probe_need(d):
    """探针①：need 被无视 → 红（True）。"""
    return len(d.options({"options": [{"text": "o", "need": {"no": 1}}]}, {})) > 0


def _probe_variant(d):
    """探针②：变体顺序取错 → 红（True）。"""
    return d.text({"texts": [{"need": None, "text": "V1"}, {"need": None, "text": "V2"}]}, {}) != "V1"


def _probe_route(d):
    """探针③：失败路由（与上面两条无共同代码路径）。"""
    return d.next_of({"next": "a", "fail_next": "b"}, failed=True) != "b"


def t_multi_fault():
    print("\n[10] 多故障：两处同时坏 + 第三处仍绿 + 还原回绿")
    reg = Registry({"no": lambda c, v: False})
    kw = dict(end_marker=END, conditions=reg, unknown=lambda k, v: True, fallback_text=FB)
    good, blind, last = mk(conditions=reg), _NeedBlind(None, **kw), _LastVariant(None, **kw)
    both = _Both(None, **kw)
    check("未破坏：三个探针全绿", not _probe_need(good) and not _probe_variant(good)
          and not _probe_route(good))
    check("破坏①（无视 need）→ 探针①变红、②③仍绿",
          _probe_need(blind) and not _probe_variant(blind) and not _probe_route(blind))
    check("破坏②（变体倒序）→ 探针②变红、①③仍绿",
          _probe_variant(last) and not _probe_need(last) and not _probe_route(last))
    check("★ 两处同时坏 → 两条探针**各自**变红（互不掩盖）",
          _probe_need(both) and _probe_variant(both))
    check("★ 两处同坏时第三处（失败路由）仍为绿", not _probe_route(both))
    check("还原（好实例）→ 两探针回绿", not _probe_need(good) and not _probe_variant(good))


def t_order():
    print("\n[11] 顺序断言：短路序 / 展开插入位 / pick 对齐 / 变体序")
    calls = []

    def mkp(k):
        def _p(ctx, v):
            calls.append(k)
            return v
        return _p

    d = mk(conditions=Registry({k: mkp(k) for k in ("a", "b", "c")}))
    calls.clear()
    d.satisfied({"a": True, "b": False, "c": True}, {})
    first = list(calls)
    calls.clear()
    d.satisfied({"c": True, "b": False, "a": True}, {})
    second = list(calls)
    check("顺序① need 键的**插入序**即短路序（重排 need → 调用序整体改变）",
          first == ["a", "b"] and second == ["c", "b"], (first, second))

    subs = [{"text": "s1"}, {"text": "s2"}, {"text": "s3"}]
    node = {"options": [{"text": "p"}, {"text": "m", "side_menu": {}}, {"text": "q"}]}
    out = d.options(node, {}, expand=lambda o: subs)
    check("顺序② 展开项插回原位置（整条展示序 = p, s1, s2, s3, q）",
          [x["text"] for x in out] == ["p", "s1", "s2", "s3", "q"], out)
    check("顺序③ pick 序号对齐**展示序**（第 2 项 = 第 1 个子选项）",
          d.pick(node, 2, {}, expand=lambda o: subs) is subs[0])
    check("顺序③ pick 越界对齐展开后的总条数（第 6 项 → None）",
          d.pick(node, 6, {}, expand=lambda o: subs) is None)
    node2 = {"options": [{"text": "p"}, {"text": "q"}, {"text": "m", "side_menu": {}}]}
    out2 = d.options(node2, {}, expand=lambda o: subs)
    check("顺序②′ 静态项顺序一变，展开项落点随之变（证明门禁真在看序）",
          [x["text"] for x in out2] == ["p", "q", "s1", "s2", "s3"], out2)
    check("顺序④ texts 声明序 = 优先级（对调 → 结果对调）",
          d.text({"texts": [{"need": None, "text": "V1"}, {"need": None, "text": "V2"}]}, {}) == "V1"
          and d.text({"texts": [{"need": None, "text": "V2"}, {"need": None, "text": "V1"}]}, {}) == "V2")


# ─────────────────────────────────────────────────────────── ⑪ 视图 / 序列化
def t_view():
    print("\n[12] 视图 / 序列化：纯 JSON 可序列化 + 原样带出")
    tree = {"start": "a", "nodes": {"a": {"text": "A", "options": [
        {"text": "o", "need": {"p": 1}, "action": {"k": 1}, "fail_next": "b"}]}}}
    d = mk(tree)
    out = d.options(d.node("a"), {})
    blob = json.dumps({"tree": d.tree, "options": out}, sort_keys=True, ensure_ascii=False)
    check("tree + options 是纯 JSON（json.dumps 不抛）", isinstance(blob, str) and '"o"' in blob)
    check("action 原样带出（引擎不解释载荷）", out[0]["action"] == {"k": 1})
    check("Cursor.state 可 json.dumps → loads 往返",
          json.loads(json.dumps(Cursor("w", "n").state(subject_key="npc", node_key="node")))
          == {"npc": "w", "node": "n"})


# ─────────────────────────────────────────────────────────── ⑫ 零知识静态扫描
_VALUE_WORDS = (
    "奥兰迪亚", "余烬", "镇长", "游商", "铁匠", "导师", "见习", "隐者", "见闻",
    "__end__", "story", "……",
    "npc", "dialogue", "npcs",
    "quest_done", "quest_active", "quest_pending", "quest_ready", "not_quest_done",
    "side_ready", "side_available", "quest_any_active", "apprentice", "not_apprentice",
    "is_novice", "not_novice", "class_any", "race_is", "hidden_unlocked", "hidden_current",
    "not_hidden_current", "evolve_ready",
    "quest_take", "set_flag", "side_offer", "side_take", "evolve_class",
    "apprentice_check", "tutor_skill", "consume_item", "give_item", "unlock_prof",
    "give_prof_exp", "open_shop", "hint", "unlock_class",
    "morning", "day", "evening", "night",
    "spring", "summer", "autumn", "winter",
    "sunny", "rain", "storm", "snow", "fog",
    "flag:", "item:", "quest:", "quest_done:", "stats:",
    "funcs", "roam", "appear", "period", "condition", "unlock", "inst_stage",
    "chance", "cycle", "duration", "lines", "title", "icon", "gender",
    "gold", "exp", "q1_1", "cls_novice", "npc_mayor",
)
_FORBIDDEN_IMPORTS = ("os", "sys", "json", "datetime", "time", "calendar", "zoneinfo", "random")


def t_zero_knowledge():
    print("\n[13] 零知识静态扫描（ast）：源码常量零取值词 / import 白名单")
    base = os.path.join(ROOT, "saintess_engine", "dialogue")
    files = [os.path.join(r, f) for r, _d, fs in os.walk(base)
             for f in sorted(fs) if f.endswith(".py")]
    check("扫到 dialogue/ 源文件（≥1）", len(files) >= 1, files)
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    bad_val, bad_imp = [], []
    for path in files:
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        docs = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc is not None:
                    docs.add(doc)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in docs:
                    continue                       # 判据只针对**代码路径**；散文里难免打比方
                for w in _VALUE_WORDS:
                    if w in node.value:
                        bad_val.append(f"{rel}:{node.lineno}:{w!r}:{node.value[:40]!r}")
            roots = []
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    continue                       # 相对导入不限
                roots.append((node.module or "").split(".")[0])
            elif isinstance(node, ast.Import):
                roots += [a.name.split(".")[0] for a in node.names]
            for root in roots:
                if root and (root not in stdlib or root in _FORBIDDEN_IMPORTS):
                    bad_imp.append(f"{rel}:{node.lineno}:{root}")
    check("★ 代码字符串常量里零取值词（表见 U1-I4_FROZEN_GATE §4）", not bad_val, bad_val[:6])
    check("★ import 只有标准库、且不含 os/sys/json/datetime/time/calendar/random",
          not bad_imp, bad_imp[:6])
    src = open(os.path.join(base, "__init__.py"), encoding="utf-8").read()
    check("零依赖：不 import 谓词注册表（只用鸭子类型 get(key)）",
          "saintess_engine.conditions" not in src and "from ..conditions" not in src)

    import saintess_engine.dialogue as mod
    check("__all__ 恰为设计给定的三个符号", mod.__all__ == ["Dialogue", "Cursor", "END_KEY"], mod.__all__)
    check("END_KEY 是「字段名」不是「取值」", END_KEY == "end_marker" and mod.END_KEY == END_KEY)
    check("模块 docstring 写清：口径分歧 / 明确不做 / 为什么不复用",
          all(k in (mod.__doc__ or "") for k in ("口径分歧", "明确不做", "为什么不复用")))
    # 注：docstring **不**参与 `_VALUE_WORDS` 扫描（判据只针对代码路径；模块名 `dialogue`
    # 本身就是引擎概念）。散文面的游戏专有名词由既有 `tests/test_no_game_vocabulary.py` 覆盖。


def main():
    print("== dialogue 形状门禁：对话树（Dialogue / Cursor）==")
    t_construct_zero_walk()
    t_read()
    t_need()
    t_options()
    t_text()
    t_route()
    t_cursor()
    t_invariants()
    t_divergences()
    t_multi_fault()
    t_order()
    t_view()
    t_zero_knowledge()
    print(f"\n===== 结果：通过 {passed} / 共 {passed + failed} =====")
    if DETAIL:
        print("失败清单：")
        for item in DETAIL:
            print(f"  ❌ {item}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
