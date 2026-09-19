#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""grant 门禁：装包 / 合并 / 逐类发放 / 声明序 / fail-closed / 零知识 + 有牙反证。

跑法：python tests/test_grant.py
退出码：0 = 全绿；1 = 有失败。

四处专门钉住的地方（都是「改了就静默变行为」的）：
  ① **合并是追加不是覆盖**：同 kind 累加（self 在前、other 在后）、不去重；`merge` 的幂等性
     由内容侧约定（纯追加 ⇒ 同一个包并两次就是两份载荷）—— 反证：改成覆盖 → 判据必红。
  ② **未登记类别在发放点点名**：`add`/`merge` 只搬数据，`grant()` 在调**第一个** sink 之前
     就把未登记类别以 `UnknownSink` 抛掉（不静默跳过、不先发一部分）
     —— 反证：把守卫改成静默跳过 → 判据必红。
  ③ **发放顺序 = sinks 声明序**：与装包先后、与 `only` 给的顺序都无关；任一 sink 抛错
     **原样上抛**，后面的类别不再调（不吞、不「尽力而为」）
     —— 反证：改成装包序 / 吞异常 → 判据必红。
  ④ **零知识**：类别名与载荷全由内容侧给；模块与**本测试文件**里 grep 不到任何内容侧取值。
"""
import ast
import importlib
import inspect
import os
import re
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import saintess_engine.grant as GRANT                                          # noqa: E402
from saintess_engine.grant import Grant, UnknownSink                           # noqa: E402

passed = failed = 0


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


def _raises(exc, fn):
    try:
        fn()
    except exc:
        return True
    except Exception:
        return False
    return False


def _noop(ctx, payloads):
    return None


def _mk(name, calls):
    """记账 sink：记下 (name, ctx, payloads)，返回 "ok:<name>"。"""
    def _sink(ctx, payloads):
        calls.append((name, ctx, payloads))
        return "ok:" + name
    return _sink


# ---------------------------------------------------------------- 1 装包
def t1_accumulate():
    print("\n[1] 装包：同 kind 累加、登记序、载荷不透明、summary 是拷贝")
    g = Grant(sinks={k: _noop for k in ("alpha", "beta", "gamma")})
    g.add("alpha", 1)
    g.add("alpha", 2)
    g.add("beta", {"k": [3]})
    g.add("alpha", 4)
    check("同 kind 三条都在（累加，不覆盖）", g.summary()["alpha"] == [1, 2, 4], str(g.summary()))
    check("不同 kind 各归各", g.summary()["beta"] == [{"k": [3]}])
    check("登记序 = 各类首次装包的先后（alpha 先于 beta）",
          list(g.summary()) == ["alpha", "beta"], str(list(g.summary())))

    g2 = Grant(sinks={"alpha": _noop})
    for payload in (None, 0, "", False, [], {}, {"a": 1}, "raw", 3.5):
        g2.add("alpha", payload)
    check("载荷不透明：None / 0 / 空串 / 空表 / 映射 / 小数原样保存",
          g2.summary()["alpha"] == [None, 0, "", False, [], {}, {"a": 1}, "raw", 3.5],
          str(g2.summary()))

    snap = g.summary()
    snap["alpha"].append("污染")
    snap["alpha"][0] = "污染"
    snap["new"] = [1]
    check("summary 返回拷贝（改返回值不影响包）",
          g.summary()["alpha"] == [1, 2, 4] and "new" not in g.summary(), str(g.summary()))
    g.add("alpha", 5)
    check("改过拷贝之后继续装包也不受影响", g.summary()["alpha"] == [1, 2, 4, 5])

    g3 = Grant(sinks={" x ": _noop})
    g3.add(" x ", 1)
    check("kind 名字原样保留（不裁剪空白、不改写）", list(g3.summary()) == [" x "])
    check("空包 summary = {}", Grant(sinks={"alpha": _noop}).summary() == {})

    bad = Grant(sinks={"alpha": _noop})
    check("kind 非字符串 → TypeError", _raises(TypeError, lambda: bad.add(1, "x")))
    check("kind 空串 → ValueError", _raises(ValueError, lambda: bad.add("", "x")))
    check("kind 全空白 → ValueError", _raises(ValueError, lambda: bad.add("   ", "x")))
    check("被拒的 kind 没有进包（报错不留半条）", bad.summary() == {})


# ---------------------------------------------------------------- 2 合并
def t2_merge():
    print("\n[2] 合并：同 kind 追加（不覆盖、不去重）、新 kind 按 other 登记序")
    a = Grant(sinks={"alpha": _noop, "beta": _noop, "gamma": _noop})
    a.add("alpha", 1)
    a.add("gamma", 7)
    b = Grant(sinks={"alpha": _noop, "beta": _noop})
    b.add("beta", 2)
    b.add("alpha", 3)
    b.add("beta", 4)
    a.merge(b)
    check("★ 同 kind 追加：self 的在前、other 的在后",
          a.summary()["alpha"] == [1, 3], str(a.summary()))
    check("反证：不是覆盖（不能只剩 other 那一条 [3]）", a.summary()["alpha"] != [3])
    check("other 里新 kind 按 other 登记序接在后面",
          list(a.summary()) == ["alpha", "gamma", "beta"], str(list(a.summary())))
    check("同 kind 多条一起进（不合并成一个值）", a.summary()["beta"] == [2, 4])

    before = a.summary()
    check("合并后改 other 不影响本包的列表", a.summary()["gamma"] == before["gamma"])

    x = Grant(sinks={"alpha": _noop})
    x.add("alpha", 1)
    y = Grant(sinks={"alpha": _noop})
    y.add("alpha", 2)
    x.merge(y)
    once = x.summary()["alpha"]
    x.merge(y)
    check("★ 纯追加 ⇒ 同一个包并两次 = 两份（幂等性由内容侧约定）",
          once == [1, 2] and x.summary()["alpha"] == [1, 2, 2], str(x.summary()))
    b.add("gamma", 9)
    check("（接上）other 新装的东西不会漏进本包", a.summary()["gamma"] == [7])
    a.add("beta", 100)
    check("改本包不影响 other", b.summary()["beta"] == [2, 4])

    other = Grant(sinks={"alpha": _noop})
    other.add("zeta", 1)
    a2 = Grant(sinks={"alpha": _noop})
    a2.merge(other)
    check("合并只搬数据：other 的未登记 kind 照样进包（发放时才点名）",
          a2.summary() == {"zeta": [1]}, str(a2.summary()))
    check("merge 非 Grant → TypeError", _raises(TypeError, lambda: a2.merge({"zeta": [1]})))
    check("merge 自身 → ValueError（且包没被弄脏）",
          _raises(ValueError, lambda: a2.merge(a2)) and a2.summary() == {"zeta": [1]})


# ---------------------------------------------------------------- 3 发放
def t3_grant():
    print("\n[3] 发放：逐类调 sink、声明序、ctx/payloads、返回值")
    calls = []
    g = Grant(sinks={"beta": _mk("beta", calls), "alpha": _mk("alpha", calls),
                     "gamma": _mk("gamma", calls)})
    g.add("alpha", 1)
    g.add("gamma", 5)
    g.add("alpha", 2)
    g.add("beta", 9)
    ctx = {"who": "x"}
    out = g.grant(ctx)
    check("★ 调用序 = sinks 声明序（beta / alpha / gamma，不是装包序 alpha / gamma / beta）",
          [c[0] for c in calls] == ["beta", "alpha", "gamma"], str([c[0] for c in calls]))
    check("结果键序 = 调用序", list(out) == ["beta", "alpha", "gamma"], str(list(out)))
    check("每个 sink 收到同一个 ctx 对象（原样透传）",
          all(c[1] is ctx for c in calls))
    check("每个 sink 收到该类全部载荷（保序）",
          [c[2] for c in calls] == [[9], [1, 2], [5]], str([c[2] for c in calls]))
    check("结果 = {kind: sink 的返回值}",
          out == {"beta": "ok:beta", "alpha": "ok:alpha", "gamma": "ok:gamma"}, str(out))

    payloads_seen = []

    def _mutating(ctx, payloads):
        payloads.append("污染")
        payloads_seen.append(len(payloads))
        return payloads

    m = Grant(sinks={"alpha": _mutating})
    m.add("alpha", 1)
    m.grant({})
    check("★ sink 拿到的是列表拷贝：它改列表不影响包",
          m.summary()["alpha"] == [1], str(m.summary()))

    marker = object()
    r = Grant(sinks={"alpha": lambda c, p: None, "beta": lambda c, p: marker})
    r.add("alpha", 1)
    r.add("beta", 2)
    out2 = r.grant({})
    check("sink 返回 None / 对象都原样进结果",
          out2 == {"alpha": None, "beta": marker} and out2["beta"] is marker, str(out2))

    calls.clear()
    check("空包发放 → {} 且一个 sink 都不调",
          Grant(sinks={"alpha": _mk("alpha", calls)}).grant({}) == {} and calls == [])


# ---------------------------------------------------------------- 4 only
def t4_only():
    print("\n[4] only：只做筛选、不改发放序；未登记名字 → UnknownSink")
    calls = []
    g = Grant(sinks={"alpha": _mk("alpha", calls), "beta": _mk("beta", calls),
                     "gamma": _mk("gamma", calls), "delta": _mk("delta", calls)})
    g.add("alpha", 1)
    g.add("beta", 9)
    g.add("gamma", 5)
    ctx = {}
    out = g.grant(ctx, only=["gamma", "alpha"])
    check("★ only 顺序不改发放序（仍是声明序 alpha / gamma）",
          [c[0] for c in calls] == ["alpha", "gamma"], str([c[0] for c in calls]))
    check("结果只含被选中的类别（且键序 = 发放序）", list(out) == ["alpha", "gamma"], str(list(out)))
    check("没被选中的载荷还留在包里（grant 不消费）", g.summary()["beta"] == [9])

    calls.clear()
    g.grant(ctx, only=["beta", "beta"])
    check("only 里重复的名字只发一次", [c[0] for c in calls] == ["beta"], str(calls))

    calls.clear()
    check("only=[] → 空结果、一个 sink 都不调", g.grant(ctx, only=[]) == {} and calls == [])
    calls.clear()
    check("only 里已登记但本次无载荷的类别：跳过、不进结果、不报错",
          g.grant(ctx, only=["delta"]) == {} and calls == [])

    check("only 里的未登记名字 → UnknownSink（即便该类没有载荷）",
          _raises(UnknownSink, lambda: g.grant(ctx, only=["nope"])))
    calls.clear()
    check("only 混合（已登记 + 未登记）→ 报错且先校验后发放（一个 sink 都没调）",
          _raises(UnknownSink, lambda: g.grant(ctx, only=["alpha", "nope"])) and calls == [])
    check("only 传字符串 → TypeError（不许逐字符当类别名）",
          _raises(TypeError, lambda: g.grant(ctx, only="alpha")))
    check("only 传非可迭代 → TypeError", _raises(TypeError, lambda: g.grant(ctx, only=1)))
    check("only 里的类别名非法（非串 / 空串）→ TypeError / ValueError",
          _raises(TypeError, lambda: g.grant(ctx, only=[1]))
          and _raises(ValueError, lambda: g.grant(ctx, only=[""])))


# ---------------------------------------------------------------- 5 未登记
def t5_unknown():
    print("\n[5] fail-closed：未登记类别在发放点点名（装包不预判）")
    calls = []
    g = Grant(sinks={"alpha": _mk("alpha", calls)})
    g.add("alpha", 1)
    g.add("delta", 2)
    check("add 未登记 kind 不报错（装包只搬数据）", g.summary()["delta"] == [2])
    try:
        g.grant({})
        check("grant 遇未登记 → UnknownSink", False)
    except UnknownSink as exc:
        check("grant 遇未登记 → UnknownSink", True)
        check("异常点名类别与已登记名单", "delta" in str(exc) and "alpha" in str(exc), str(exc))
    check("★ 先校验后发放：报错时一个 sink 都没调", calls == [], str(calls))
    check("未登记类别还在包里（载荷一个没丢）", g.summary()["delta"] == [2])
    check("UnknownSink 是 LookupError 子类（可被更宽的 except 收）",
          issubclass(UnknownSink, LookupError))

    other = Grant(sinks={"alpha": _noop})
    other.add("omega", 3)
    g.merge(other)
    check("merge 进来的未登记类别同样点名",
          _raises(UnknownSink, lambda: g.grant({})) and calls == [])

    clean = Grant(sinks={"alpha": _mk("alpha", calls)})
    clean.add("alpha", 1)
    check("同一份数据换到干净包上照常发放（还原复绿）",
          clean.grant({}) == {"alpha": "ok:alpha"})


# ---------------------------------------------------------------- 6 sink 抛错
def t6_sink_error():
    print("\n[6] 任一 sink 抛错 → 原样上抛（不吞、不「尽力而为」）")
    boom = RuntimeError("sink 自己的错误")
    calls = []

    def _bad(ctx, payloads):
        calls.append(("beta", ctx, payloads))
        raise boom

    g = Grant(sinks={"alpha": _mk("alpha", calls), "beta": _bad, "gamma": _mk("gamma", calls)})
    for k in ("alpha", "beta", "gamma"):
        g.add(k, 1)
    try:
        g.grant({})
        check("sink 抛错 → 上抛", False)
    except RuntimeError as exc:
        check("sink 抛错 → 上抛", True)
        check("★ 抛的是同一个异常对象（没被包一层、没换成别的类型）", exc is boom)
    check("★ 不是「吞掉继续发」：抛错之后的 gamma 一次都没调",
          [c[0] for c in calls] == ["alpha", "beta"], str([c[0] for c in calls]))
    check("抛错不停留在包上（包没被改脏）", g.summary() == {"alpha": [1], "beta": [1], "gamma": [1]})

    calls.clear()

    def _bad2(ctx, payloads):
        calls.append(("alpha", ctx, payloads))
        raise ValueError("另一个错误")

    g2 = Grant(sinks={"alpha": _bad2})
    g2.add("alpha", 1)
    check("异常类型不被改写（ValueError 仍是 ValueError）",
          _raises(ValueError, lambda: g2.grant({})) and not _raises(RuntimeError, lambda: g2.grant({})))


# ---------------------------------------------------------------- 7 不改包
def t7_repeat():
    print("\n[7] 发放不改包：同一个包发两次 = 两次")
    calls = []
    g = Grant(sinks={"alpha": _mk("alpha", calls)})
    g.add("alpha", 1)
    r1 = g.grant({})
    r2 = g.grant({})
    check("grant 不改包（summary 逐次相同）", g.summary() == {"alpha": [1]})
    check("★ 同一包发两次 → sink 收两次（不静默吞第二次）",
          [c[0] for c in calls] == ["alpha", "alpha"], str(calls))
    check("两次结果相同（发放是只读）", r1 == r2 == {"alpha": "ok:alpha"})
    g.add("alpha", 2)
    calls.clear()
    g.grant({})
    check("发放后还能继续装包，下次发全量", calls[-1][2] == [1, 2], str(calls[-1][2]))


# ---------------------------------------------------------------- 8 构造 / 签名
def t8_ctor():
    print("\n[8] 构造与签名：sinks 校验、声明序冻结、log 约定")
    check("sinks=None → TypeError", _raises(TypeError, lambda: Grant(sinks=None)))
    check("sinks 非映射 → TypeError", _raises(TypeError, lambda: Grant(sinks=[("alpha", _noop)])))
    check("sinks 的 key 非字符串 → TypeError", _raises(TypeError, lambda: Grant(sinks={1: _noop})))
    check("sinks 的 key 空 / 全空白 → ValueError",
          _raises(ValueError, lambda: Grant(sinks={"": _noop}))
          and _raises(ValueError, lambda: Grant(sinks={"  ": _noop})))
    check("sink 非可调用 → TypeError",
          _raises(TypeError, lambda: Grant(sinks={"alpha": "not-callable"})))
    check("空 sinks 合法（发放时未登记照样点名）",
          Grant(sinks={}).summary() == {} and isinstance(Grant(sinks={}), Grant))

    check("log 非带 info 的句柄 → TypeError",
          _raises(TypeError, lambda: Grant(sinks={"alpha": _noop}, log=object())))
    check("log=None（缺省）合法", isinstance(Grant(sinks={"alpha": _noop}, log=None), Grant))

    calls = []
    table = {"beta": _mk("beta", calls), "alpha": _mk("alpha", calls)}
    g = Grant(sinks=table)
    table["gamma"] = _mk("gamma", calls)
    table["alpha"] = _mk("changed", calls)
    g.add("alpha", 1)
    g.add("beta", 2)
    out = g.grant({})
    check("★ sinks 构造即快照：改传入映射不改本包的名单与实现",
          list(out) == ["beta", "alpha"] and [c[0] for c in calls] == ["beta", "alpha"],
          str([c[0] for c in calls]))
    check("构造后新增的类别仍算未登记",
          _raises(UnknownSink, lambda: (g.add("gamma", 3), g.grant({}))))

    lines = []

    class _Log:
        def info(self, msg, *args):
            lines.append(msg % args)

    gl = Grant(sinks={"alpha": _mk("alpha", calls)}, log=_Log())
    gl.add("alpha", 1)
    gl.add("alpha", 2)
    gl.grant({})
    check("log 每发成一个类别记一行（类别名 + 载荷条数）",
          lines == ["grant kind=alpha payloads=2"], str(lines))

    sig = inspect.signature(Grant.__init__)
    kw = inspect.Parameter.KEYWORD_ONLY
    check("sinks / log 都是 keyword-only",
          sig.parameters["sinks"].kind == kw and sig.parameters["log"].kind == kw)
    check("sinks 必填（无缺省）、log 缺省 None",
          sig.parameters["sinks"].default is inspect.Parameter.empty
          and sig.parameters["log"].default is None)
    check("第 1 个位置参传 sinks → TypeError（签名拒绝）",
          _raises(TypeError, lambda: Grant({"alpha": _noop})))


# ---------------------------------------------------------------- 9 零知识
def _banned():
    """内容侧词表（具体游戏身份 + 具体类别取值）。

    词按**片段**拼出来（相邻字面量在编译期合并）：否则本文件自己会被自己扫中，门禁成空转。
    """
    zh = ("物" "品", "宠" "物", "坐" "骑", "称" "号", "金" "币", "经" "验", "装" "备",
          "道" "具", "副" "本", "怪" "物", "职" "业", "等" "级", "队" "伍")
    game = ("奥" "兰" "迪" "亚", "余" "烬", "战" "意", "旋" "律", "连" "段", "破" "绽",
            "信" "仰", "奥" "术", "狂" "暴")
    en = ("it" "em", "it" "ems", "pe" "t", "pe" "ts", "mou" "nt", "mou" "nts",
          "tit" "le", "bon" "us", "go" "ld", "e" "xp", "equ" "ip", "play" "er",
          "mon" "ster", "n" "pc", "dun" "geon", "que" "st", "lev" "el", "ski" "ll",
          "rew" "ard", "lo" "ot", "dr" "op", "dragon" "fall", "zhan" "_yi")
    return zh + game + en


def _hit(text, words):
    """文本里命中哪些词（ASCII 词按整词边界，中文词按子串）。"""
    low = text.lower()
    hits = []
    for w in words:
        if w.isascii():
            if re.search(r"(?<![A-Za-z0-9_])" + re.escape(w) + r"(?![A-Za-z0-9_])", low):
                hits.append(w)
        elif w in text:
            hits.append(w)
    return hits


def t9_zero_knowledge():
    print("\n[9] 零知识：模块 + 本测试文件里 grep 不到内容侧词汇")
    words = _banned()
    mod_dir = os.path.join(ROOT, "saintess_engine", "grant")
    mods = [os.path.join(mod_dir, f) for f in sorted(os.listdir(mod_dir)) if f.endswith(".py")]
    me = os.path.abspath(__file__)
    print(f"    词表 {len(words)} 个；扫描 {len(mods)} 个模块文件 + 本测试文件")

    raw_bad = []
    for path in mods + [me]:
        src = open(path, encoding="utf-8").read()
        for w in _hit(src, words):
            raw_bad.append(f"{os.path.relpath(path, ROOT)}:{w}")
    check("★ 模块 + 测试全文（含注释 / 文档串）0 命中", not raw_bad, str(raw_bad[:6]))

    doc_bad = []
    for path in mods:
        tree = ast.parse(open(path, encoding="utf-8").read())
        docs = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                d = ast.get_docstring(node, clean=False)
                if d is not None:
                    docs.add(d)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and node.value not in docs):
                for w in _hit(node.value, words):
                    doc_bad.append(f"{os.path.basename(path)}:{node.lineno}:{w}")
    check("★ 模块代码常量（跳过文档串）里 0 命中", not doc_bad, str(doc_bad[:6]))

    tree = ast.parse(open(me, encoding="utf-8").read())
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_banned":
            for sub in ast.walk(node):
                skip.add(id(sub))
    test_bad = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in skip):
            for w in _hit(node.value, words):
                test_bad.append(f"test_grant.py:{node.lineno}:{w}")
    check("★ 测试代码常量（词表自身除外）里 0 命中", not test_bad, str(test_bad[:6]))

    check("公开面就是 Grant / UnknownSink", GRANT.__all__ == ["Grant", "UnknownSink"])
    check("模块可独立 import（不依赖包门面改动）",
          importlib.import_module("saintess_engine.grant").Grant is Grant)


# ---------------------------------------------------------------- 10 反证
_SRC = os.path.join(ROOT, "saintess_engine", "grant", "__init__.py")

_A_MERGE = "            self._by_kind.setdefault(kind, []).extend(payloads)"
_R_MERGE = "            self._by_kind[kind] = list(payloads)"
_A_UNKNOWN = "        if unknown:"
_R_UNKNOWN = "        if False:"
_A_CALL = "            out[kind] = self._sinks[kind](ctx, payloads)"
_R_CALL = ("            try:\n"
           "                out[kind] = self._sinks[kind](ctx, payloads)\n"
           "            except Exception:\n"
           "                out[kind] = None")
_A_ORDER = "        order = [k for k in self._sinks if k in wanted and k in self._by_kind]"
_R_ORDER = "        order = [k for k in self._by_kind if k in wanted and k in self._sinks]"


def _variant(anchor, repl):
    """读**磁盘上的真模块** → 按唯一锚点改坏 → exec 到独立命名空间（磁盘文件一个字节不动）。

    锚点必须**整行**唯一命中（不是子串命中）：否则磁盘已被外部改坏时，锚点会落在别人
    缩进更深的那一行里，反证会变成语法错而不是判红。语法不合法的拷贝按「反证无效」报红。
    """
    lines = open(_SRC, encoding="utf-8").read().splitlines(keepends=True)
    hit = [i for i, ln in enumerate(lines) if ln.rstrip("\n") == anchor]
    if len(hit) != 1:
        raise AssertionError(f"锚点整行必须唯一命中（防反证空转）：{anchor!r} 命中 {len(hit)} 次")
    lines[hit[0]] = repl + "\n"
    ns = types.ModuleType("grant_variant")
    ns.__file__ = _SRC
    try:
        code = compile("".join(lines), _SRC, "exec")
    except SyntaxError as exc:
        raise AssertionError(f"改坏后的拷贝语法不合法：{exc}")
    exec(code, ns.__dict__)
    return ns


def _probe_merge(mod):
    """判据 1 的探针：同 kind 合并后必须是 [1, 2]。True = 判红。"""
    g = mod.Grant(sinks={"alpha": _noop})
    g.add("alpha", 1)
    other = mod.Grant(sinks={"alpha": _noop})
    other.add("alpha", 2)
    g.merge(other)
    return g.summary().get("alpha") != [1, 2]


def _probe_unknown(mod):
    """判据 2 的探针：未登记类别必须抛 UnknownSink。True = 判红。"""
    g = mod.Grant(sinks={"alpha": _noop})
    g.add("alpha", 1)
    g.add("delta", 2)
    try:
        g.grant({})
    except mod.UnknownSink:
        return False
    return True


def _probe_sink_error(mod):
    """判据 3 的探针：sink 的同一个异常对象必须原样上抛。True = 判红。"""
    boom = RuntimeError("sink 自己的错误")

    def _bad(ctx, payloads):
        raise boom

    g = mod.Grant(sinks={"alpha": _bad})
    g.add("alpha", 1)
    try:
        g.grant({})
    except RuntimeError as exc:
        return exc is not boom
    return True


def _probe_order(mod):
    """判据 4 的探针：调用序必须是 sinks 声明序。True = 判红。"""
    calls = []
    g = mod.Grant(sinks={"beta": _mk("beta", calls), "alpha": _mk("alpha", calls)})
    g.add("alpha", 1)
    g.add("beta", 2)
    g.grant({})
    return [c[0] for c in calls] != ["beta", "alpha"]


def t10_counterproof():
    print("\n[10] 有牙反证：把实现改坏 → 探针必红（真模块只读，改坏在内存拷贝里做）")
    cases = (
        ("merge 改成覆盖", _A_MERGE, _R_MERGE, _probe_merge),
        ("未登记类别静默跳过", _A_UNKNOWN, _R_UNKNOWN, _probe_unknown),
        ("sink 异常被吞", _A_CALL, _R_CALL, _probe_sink_error),
        ("发放顺序改成装包序", _A_ORDER, _R_ORDER, _probe_order),
    )
    for name, anchor, repl, probe in cases:
        try:
            bad_mod = _variant(anchor, repl)
        except AssertionError as exc:
            check(f"反证·{name}｜锚点唯一命中", False, str(exc))
            continue
        check(f"反证·{name}｜真模块探针未报红（判据当下成立）", probe(GRANT) is False)
        check(f"反证·{name}｜改坏后探针报红（有牙）", probe(bad_mod) is True)


def main():
    print("== grant 门禁：装包 / 合并 / 发放 / 声明序 / fail-closed / 零知识 / 反证 ==")
    t1_accumulate()
    t2_merge()
    t3_grant()
    t4_only()
    t5_unknown()
    t6_sink_error()
    t7_repeat()
    t8_ctor()
    t9_zero_knowledge()
    t10_counterproof()
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
