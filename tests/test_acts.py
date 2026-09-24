#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""acts 门禁：动词登记 / 装配期 fail-closed / 按序执行 / 取值节点 / 零知识 + 有牙反证。

跑法：python tests/test_acts.py
退出码：0 = 全绿；1 = 有失败。

四处专门钉住的地方（都是「改了就静默变行为」的）：
  ① **未登记动词在装配期点名**：`compile` / `compile_table` 里就抛 `UnknownVerb`（点名 + 列出
     已登记），不留到运行期、不静默跳过、不退回默认实现 —— 反证：把守卫改成 `if False` → 判据必红。
  ② **执行序 = 声明序**：与动词表登记序无关；`when` 为假 ⇒ 空列表（不是 None、不是跑一半）；
     `stop_if` 为真 ⇒ 记完当步就停 —— 反证：把序列改 `reversed` → 判据必红。
  ③ **`when` 为假真的不执行**：不「先跑再说」—— 反证：把 `when` 判断改成 `if False` → 判据必红。
  ④ **动词异常原样上抛**：不吞、不「尽力而为」、不接着跑后面的步骤
     —— 反证：把调用包一层 `except: pass` → 判据必红。

另：本形状**零知识** —— 模块与**本测试文件**里 grep 不到任何内容侧取值（动词名 / 事件名 /
文案槽位全是中性的 demo 名），见 t9。
"""
import ast
import io
import os
import re
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import saintess_engine.acts as ACTS                                          # noqa: E402
from saintess_engine.acts import Acts, Plan, SpecError, UnknownVerb          # noqa: E402

passed = failed = 0


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")

_SRC = os.path.join(ROOT, "saintess_engine", "acts", "__init__.py")


def _raises(exc, fn):
    try:
        fn()
    except exc:
        return True
    except Exception:
        return False
    return False


def _mk_acts(verbs=("a", "b", "c"), calls=None):
    """造一个 Acts，登记若干记账动词（返回 ``(acts, calls)``，calls 记 (名字, 实参)）。"""
    calls = [] if calls is None else calls
    acts = Acts()
    for name in verbs:
        def _v(ctx, _n=name, **kw):
            calls.append((_n, dict(kw)))
            return _n
        acts.verbs[name] = _v
    return acts, calls


# ============================================================ 1 动词表
def t1_verbs():
    print("\n[1] 动词表：装饰器 / 直接写表 / 校验")
    acts = Acts()

    @acts.register("alpha")
    def _alpha(ctx, **kw):
        return 1

    check("register 返回原函数（可直接当实现用）", acts.verbs.get("alpha") is _alpha)

    def _beta(ctx, **kw):
        return 2

    acts.verbs["beta"] = _beta
    check("直接写表即刻生效（对象共享）", acts.verbs.get("beta") is _beta)

    def _beta2(ctx, **kw):
        return 3

    acts.verbs["beta"] = _beta2
    check("重名 = 就地覆盖（不报错、不叠加）", acts.verbs.get("beta") is _beta2)

    check("register 非可调用 ⇒ TypeError", _raises(TypeError, lambda: acts.register("x")(42)))
    check("构造时 verbs 非映射 ⇒ TypeError", _raises(TypeError, lambda: Acts(verbs=[("a", _alpha)])))
    check("构造时 verbs 里非可调用 ⇒ TypeError", _raises(TypeError, lambda: Acts(verbs={"a": 42})))
    check("空动词名 ⇒ ValueError", _raises(ValueError, lambda: acts.register("  ")(_alpha)))
    check("非字符串动词名 ⇒ TypeError", _raises(TypeError, lambda: acts.register(7)(_alpha)))


# ============================================================ 2 装配期 fail-closed
def t2_compile_fail_closed():
    print("\n[2] 装配期 fail-closed（全部在 compile / compile_table 里报）")
    acts, _ = _mk_acts()
    ok = {"id": "p1", "on": "evt", "seq": [{"verb": "a"}]}

    check("正常声明编得出 Plan", isinstance(acts.compile(ok), Plan))
    check("compile(spec, name=) 可给 id", acts.compile({"seq": [{"verb": "a"}]}, name="p2").name == "p2")
    check("表非映射 ⇒ SpecError", _raises(SpecError, lambda: acts.compile_table([1, 2])))
    check("条目非映射 ⇒ SpecError", _raises(SpecError, lambda: acts.compile(42)))
    check("缺 id ⇒ SpecError", _raises(SpecError, lambda: acts.compile({"seq": [{"verb": "a"}]})))
    check("id 空串 ⇒ SpecError", _raises(SpecError, lambda: acts.compile({"id": " ", "seq": []})))
    check("seq 缺失 ⇒ SpecError", _raises(SpecError, lambda: acts.compile({"id": "p"})))
    check("seq 空列表 ⇒ SpecError",
          _raises(SpecError, lambda: acts.compile({"id": "p", "seq": []})))
    check("seq 非列表 ⇒ SpecError",
          _raises(SpecError, lambda: acts.compile({"id": "p", "seq": {"verb": "a"}})))
    check("步非映射 ⇒ SpecError",
          _raises(SpecError, lambda: acts.compile({"id": "p", "seq": ["a"]})))
    check("步缺 verb ⇒ SpecError",
          _raises(SpecError, lambda: acts.compile({"id": "p", "seq": [{"kw": 1}]})))
    check("步 verb 空串 ⇒ SpecError",
          _raises(SpecError, lambda: acts.compile({"id": "p", "seq": [{"verb": ""}]})))

    try:
        acts.compile({"id": "p", "seq": [{"verb": "nope"}]})
        check("未登记动词 ⇒ UnknownVerb", False)
    except UnknownVerb as exc:
        msg = str(exc)
        check("未登记动词 ⇒ UnknownVerb", True)
        check("UnknownVerb 点名 + 列出已登记", "nope" in msg and "a" in msg, msg)

    check("when 不是合法节点 ⇒ SpecError",
          _raises(SpecError, lambda: acts.compile({"id": "p", "seq": [{"verb": "a"}],
                                                   "when": {"op": "nope"}})))
    check("stop_if 不是合法节点 ⇒ SpecError",
          _raises(SpecError, lambda: acts.compile({"id": "p",
                                                   "seq": [{"verb": "a", "stop_if": {"op": "nope"}}]})))
    check("实参里的节点不合法 ⇒ SpecError",
          _raises(SpecError, lambda: acts.compile({"id": "p", "seq": [{"verb": "a",
                                                                        "k": {"op": "nope"}}]})))

    # 整表不装：坏一条 ⇒ 一条都不返回（且好条目也没有副作用）
    table = {"good": {"seq": [{"verb": "a"}]}, "bad": {"seq": [{"verb": "nope"}]}}
    check("表里任一条坏 ⇒ 整表不装", _raises(UnknownVerb, lambda: acts.compile_table(table)))


# ============================================================ 3 执行
def t3_run():
    print("\n[3] 执行：序 / 结果 / out / when / stop_if / ctx 透传")
    acts, calls = _mk_acts()
    acts.verbs["stop"] = lambda ctx, **kw: calls.append(("stop", {})) or "stop"
    plans = acts.compile_table({
        "p": {"on": "evt", "seq": [{"verb": "a", "k": 1}, {"verb": "b"}, {"verb": "c"}]},
        "w": {"on": "evt", "when": {"field": [{"key": "flag"}]}, "seq": [{"verb": "a"}]},
        "s": {"on": "evt", "seq": [{"verb": "a"}, {"verb": "stop", "stop_if": {"const": True}},
                                  {"verb": "c"}]},
    })

    out = plans["p"].run({"flag": True})
    check("结果 = 每步返回值按声明序", out == ["a", "b", "c"], out)
    check("调用序 = 声明序", [c[0] for c in calls] == ["a", "b", "c"], calls)
    check("实参逐值求值后传给动词", calls[0][1] == {"k": 1}, calls[0][1])

    calls.clear()
    plans["p"].run({"flag": True}, out=["pre"])
    check("给了 out 就往它里追加", calls and True)
    got = plans["p"].run({"flag": True}, out=["pre"])
    check("out 追加在尾部且不新建", got == ["pre", "a", "b", "c"], got)

    calls.clear()
    check("when 假 ⇒ 空列表（不是 None）", plans["w"].run({"flag": False}) == [])
    check("when 假 ⇒ 一个动词都没调", calls == [], calls)
    check("when 真 ⇒ 正常执行", plans["w"].run({"flag": 1}) == ["a"])

    calls.clear()
    got = plans["s"].run({})
    check("stop_if 为真 ⇒ 记完当步就停", got == ["a", "stop"], got)
    check("stop_if 短路 ⇒ 后续步骤不执行", [c[0] for c in calls] == ["a", "stop"], calls)

    ctx = {"flag": True}
    seen = []
    acts2 = Acts()
    acts2.verbs["snap"] = lambda c, **kw: seen.append(c) or "x"
    acts2.compile({"id": "z", "seq": [{"verb": "snap"}]}).run(ctx)
    check("ctx 原样透传（同一个对象）", seen and seen[0] is ctx)

    check("Plan 不可变：steps 是元组", isinstance(plans["p"].steps, tuple))


# ============================================================ 4 取值节点
def t4_values():
    print("\n[4] 取值节点（复用 conditions.declarative 的语法，不另造）")
    acts = Acts()
    got = []
    acts.verbs["cap"] = lambda ctx, **kw: got.append(kw) or kw

    plans = acts.compile_table({
        "const": {"seq": [{"verb": "cap", "v": {"const": 7}}]},
        "field": {"seq": [{"verb": "cap", "v": {"field": [{"key": "a"}, {"key": "b"}]}}]},
        "op": {"seq": [{"verb": "cap", "v": {"op": "len", "arg": {"field": [{"key": "lst"}]}}}]},
        "literal": {"seq": [{"verb": "cap", "v": 3, "s": "txt"}]},
        "nested": {"seq": [{"verb": "cap", "v": {"slot": "x",
                                                 "args": {"who": {"field": [{"key": "n"}]}}}}]},
        "list": {"seq": [{"verb": "cap", "v": [1, {"field": [{"key": "n"}]}]}]},
    })
    ctx = {"a": {"b": 5}, "n": 10, "lst": [1, 2, 3]}

    plans["const"].run(ctx); check("const 节点", got[-1]["v"] == 7, got[-1])
    plans["field"].run(ctx); check("field 步链取值", got[-1]["v"] == 5, got[-1])
    plans["op"].run(ctx); check("op 节点（引擎算）", got[-1]["v"] == 3, got[-1])
    plans["literal"].run(ctx); check("字面量原样", got[-1]["v"] == 3 and got[-1]["s"] == "txt", got[-1])
    plans["nested"].run(ctx)
    check("字面量里的节点递归求值",
          got[-1]["v"] == {"slot": "x", "args": {"who": 10}}, got[-1])
    plans["list"].run(ctx); check("列表里的节点递归求值", list(got[-1]["v"]) == [1, 10], got[-1])


# ============================================================ 5 动词异常
def t5_verb_error():
    print("\n[5] 动词异常原样上抛")
    acts = Acts()
    boom = RuntimeError("动词自己的错误")
    acts.verbs["bad"] = lambda ctx, **kw: (_ for _ in ()).throw(boom)
    plan = acts.compile({"id": "p", "seq": [{"verb": "bad"}]})
    try:
        plan.run({})
        check("动词异常上抛", False)
    except RuntimeError as exc:
        check("动词异常原样上抛（同一个对象）", exc is boom, repr(exc))


# ============================================================ 6 零知识
def t6_zero_knowledge():
    print("\n[6] 零知识：模块与测试文件里没有内容侧取值")
    # 红词表按「拼」出来（否则词表自己就把自己判红）
    red = ["ene" + "rgy", "arc" + "ane", "cor" + "e", "sta" + "cks", "mon" + "ster",
           "dun" + "geon", "go" + "ld", "it" + "em", "副" + "本", "职" + "业",
           "公" + "会", "材" + "料", "金" + "币", "怪" + "物", "技" + "能"]
    for path in (_SRC, os.path.abspath(__file__)):
        src = io.open(path, encoding="utf-8", errors="replace").read()
        # ASCII 词按词边界判（否则单数形式会误伤 ``.items()`` 这种正常写法）；中文直接查
        hits = sorted({w for w in red
                       if (re.search(r"\b%s\b" % re.escape(w), src) if w.isascii() else w in src)})
        check(f"{os.path.basename(path)}：无内容侧取值", not hits, ",".join(hits))

    # 模块的 import：只许 stdlib 白名单 + 引擎内部相对边（不引任何内容侧/第三方件）
    allow = {"__future__", "collections.abc"}
    tree = ast.parse(io.open(_SRC, encoding="utf-8").read())
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.level or 0) == 0:
            if (node.module or "") not in allow:
                bad.append(node.module or "")
        if isinstance(node, ast.Import):
            bad.extend(a.name for a in node.names if a.name.split(".")[0] not in allow)
    check("模块只引 stdlib 白名单 + 引擎内部件", not bad, ",".join(bad))


# ============================================================ 7 有牙反证
def _variant(anchor, repl):
    """把真源改坏成一个**内存拷贝**（真源只读；锚点必须唯一命中）。"""
    src = io.open(_SRC, encoding="utf-8").read()
    if src.count(anchor) != 1:
        raise AssertionError("锚点在真源里不是唯一命中：%r（命中 %d 次）" % (anchor, src.count(anchor)))
    ns = types.ModuleType("acts_bad")
    ns.__file__ = _SRC
    ns.__package__ = "saintess_engine.acts"          # 让相对的 import 能解析
    exec(compile(src.replace(anchor, repl), _SRC, "exec"), ns.__dict__)
    return ns


def _probe_unknown(mod):
    """判据 1 探针：未登记动词必须抛 UnknownVerb。True = 判红。"""
    a = mod.Acts()
    a.verbs["a"] = lambda ctx, **kw: None
    try:
        a.compile({"id": "p", "seq": [{"verb": "nope"}]})
    except mod.UnknownVerb:
        return False
    except Exception:
        return True
    return True


def _probe_order(mod):
    """判据 2 探针：调用序必须是声明序（且 stop_if 记完当步就停）。True = 判红。"""
    a = mod.Acts()
    calls = []
    a.verbs["a"] = lambda ctx, **kw: calls.append("a") or "a"
    a.verbs["b"] = lambda ctx, **kw: calls.append("b") or "b"
    plan = a.compile({"id": "p", "seq": [{"verb": "a"}, {"verb": "b"}]})
    plan.run({})
    return calls != ["a", "b"]


def _probe_when(mod):
    """判据 3 探针：when 为假必须不执行。True = 判红。"""
    a = mod.Acts()
    calls = []
    a.verbs["a"] = lambda ctx, **kw: calls.append("a")
    plan = a.compile({"id": "p", "when": {"field": [{"key": "flag"}]}, "seq": [{"verb": "a"}]})
    out = plan.run({"flag": False})
    return bool(calls) or out != []


def _probe_error(mod):
    """判据 4 探针：动词异常必须原样上抛。True = 判红。"""
    a = mod.Acts()
    boom = RuntimeError("动词自己的错误")
    a.verbs["bad"] = lambda ctx, **kw: (_ for _ in ()).throw(boom)
    plan = a.compile({"id": "p", "seq": [{"verb": "bad"}]})
    try:
        plan.run({})
    except RuntimeError as exc:
        return exc is not boom
    return True


def t7_counterproof():
    print("\n[7] 有牙反证：把实现改坏 → 探针必红（真模块只读，改坏在内存拷贝里做）")
    cases = (
        ("未登记动词静默跳过",
         "            if vname not in self._verbs:",
         "            if False:",
         _probe_unknown),
        ("执行序改成反序",
         "        for verb_name, verb, kwargs, stop_if in self.steps:",
         "        for verb_name, verb, kwargs, stop_if in reversed(self.steps):",
         _probe_order),
        ("when 为假也照跑",
         "        if self._when is not None and not self._when(ctx):",
         "        if False:",
         _probe_when),
        ("动词异常被吞",
         "            result.append(verb(ctx, **args))",
         "            try:\n                result.append(verb(ctx, **args))\n            except Exception:\n                pass",
         _probe_error),
    )
    for name, anchor, repl, probe in cases:
        try:
            bad_mod = _variant(anchor, repl)
        except AssertionError as exc:
            check(f"反证·{name}｜锚点唯一命中", False, str(exc))
            continue
        check(f"反证·{name}｜真模块探针未报红（判据当下成立）", probe(ACTS) is False)
        check(f"反证·{name}｜改坏后探针报红（有牙）", probe(bad_mod) is True)


def main():
    print("== acts 门禁：动词登记 / fail-closed / 按序执行 / 取值节点 / 零知识 / 反证 ==")
    t1_verbs()
    t2_compile_fail_closed()
    t3_run()
    t4_values()
    t5_verb_error()
    t6_zero_knowledge()
    t7_counterproof()
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
