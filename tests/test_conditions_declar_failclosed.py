#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""declarative.py 的 8 条装载期 fail-closed 守卫门禁（验证侧缺口 · 生产码零改动）。

跑法：python tests/test_conditions_declar_failclosed.py
退出码：0 = 全绿；1 = 有失败。

★ 立项依据 = **逐条变异实跑**（不是照抄任何清单）：
  把 `saintess_engine/conditions/declarative.py` 的 8 条守卫逐条整块换成静默 `pass`，
  跑**该文件消费者所在的真门禁面**（test_conditions / test_acts / test_engine_purity /
  ext_achieve 包门禁 / ext_dialogue 形状门禁 / ext_life 周期解锁 = 7 支）⇒ **8 条全部零转红**。
  ⇒ 守卫本身是对的，缺的是零覆盖。

★ **退化形态逐条实测**（不假设"静默返回"）—— 这是本门禁的判据核心：
  6 条真洞 = **编译期静默接受坏声明**（返回一个可调用，内容侧看不出自己写坏了）：
    L120 步的键不对      → 编译成功
    L125 key 非空字符串  → 编译成功（空串 / 非 str 都过）
    L184 步链非空列表    → 编译成功（空列表过；非 list 退化成 "步必须是字典"）
    L202 field 节点键不对 → 编译成功
    L230 布尔节点键不对  → 编译成功
    L236 一元节点键不对   → 编译成功
  2 条退化仍抛但**点名全丢**（内容侧看到的是引擎内部形态名，拿不到契约）：
    L118 步必须是字典  → `TypeError: 'int' object is not iterable`
    L273 args 非空列表 → `TypeError: 'int' object is not iterable`
  ⇒ 判据统一钉「**不再抛点名带归属的 `SpecError`**」；退化形态另由【2】组单列钉住
    —— 退化形态若变化，判据会报红而不是默默放过。

★ 守卫在防什么：`declarative` 是**声明式条件编译入口**，内容侧把条件写成
  `{"op":"and","args":[...]}` 这类数据、装载期一次性编译成可调用。装载期守卫被拆 =
  内容侧**写错的声明当场通过**，随后在**玩家触发的那一刻**以引擎内部形态炸，
  而内容侧看到的是引擎变量名，既不知哪条声明坏、也拿不到"这里该是什么形状"。

★ 踩坑沉淀（留给下一轮改本文件的）：
  ① 本门禁的反证子进程**必须带 `AFIX4_MUTANT_CHILD` 标记**（防自举递归）·
     **必须 `cwd=ROOT`**（否则从 temp 反算 ROOT、读的是另一棵树 ⇒ 变异态也全绿，
     判据"看着有牙、实则无牙"，上一轮踩过）；还原用 `io.open(..., newline="")` 逐字。
  ② 造"多出一个键"的样本要小心**常量驻留**：`frozenset({...})` 逐字相同可能被 intern，
     所以本文件用**函数返回新 dict**（C/S/F）而不是模块级常量字面量。
"""
import copy
import io
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine.conditions import declarative as D                # noqa: E402

passed = failed = 0
DETAIL = []

from _check import bind_check                                            # noqa: E402

check = bind_check(globals(), "passed", "failed", "DETAIL")

TGT = os.path.join(ROOT, "saintess_engine", "conditions", "declarative.py")
PY = r"C:/Users/yuyu/AppData/Local/Programs/Python/Python312/python.exe"


# ---- 构造器写成函数：避免常量驻留/折叠导致"造得出多一个键的样本"失败 ----

def C(v):
    return {"const": v}


def S(k, default=None, or_=None):
    if or_ is None:
        return {"key": k, "default": default}
    return {"key": k, "or": or_}


def F(*steps):
    return {"field": [dict(s) for s in steps]}


def spec_of(fn, *a):
    """跑 fn → ('exc', 异常类名, 串) / ('ok', 值, '')"""
    try:
        return ("ok", fn(*a), "")
    except Exception as exc:                                            # noqa: BLE001
        return ("exc", type(exc).__name__, str(exc)[:120])


def raises_spec(fn, *a):
    kind, name, msg = spec_of(fn, *a)
    return kind == "exc" and name == "SpecError", (kind, name, msg)


# 8 条守卫各自的坏输入（key = 守卫标签；每条至少两个不同坏法）
BAD = {
    "L118 步必须是字典": [lambda: D.compile_spec({"field": [42]}),
                          lambda: D.compile_spec({"field": ["abc"]}),
                          lambda: D.compile_spec({"field": [None]})],
    "L120 步的键不对": [lambda: D.compile_spec({"field": [{"key": "a", "bogus": 1}]}),
                        lambda: D.compile_spec(F({"key": "a", "default": 1,
                                                 "or": 2, "extra": 3}))],
    "L125 key 必须是非空字符串": [lambda: D.compile_spec(F(S(""))),
                                  lambda: D.compile_spec(F(S(5))),
                                  lambda: D.compile_spec(F(S(None)))],
    "L184 步链必须是非空列表": [lambda: D.compile_spec({"field": []}),
                                lambda: D.compile_spec({"field": "abc"}),
                                lambda: D.compile_spec({"field": 5})],
    "L202 field 节点键不对": [lambda: D.compile_spec({"field": [S("a")], "x": 1}),
                              lambda: D.compile_spec({"field": [S("a")], "op": "not"})],
    "L230 布尔节点键不对": [lambda: D.compile_spec({"op": "and", "args": [C(1)], "x": 1}),
                            lambda: D.compile_spec({"op": "or", "args": [C(1)], "op2": 2})],
    "L236 一元节点键不对": [lambda: D.compile_spec({"op": "not", "arg": C(1), "x": 1}),
                            lambda: D.compile_spec({"op": "len", "arg": C(1), "x": 1}),
                            lambda: D.compile_spec({"op": "int", "arg": C(1), "x": 1}),
                            lambda: D.compile_spec({"op": "truthy", "arg": C(1), "x": 1})],
    "L273 args 必须是非空列表": [lambda: D.compile_spec({"op": "or", "args": []}),
                                  lambda: D.compile_spec({"op": "and", "args": 5}),
                                  lambda: D.compile_spec({"op": "and", "args": "ab"})],
}

# 合法面（钉「严格 ≠ 见谁都抛」）
GOOD = {
    "const": (C(7), 7),
    "field 单步": (F(S("a")), 3),
    # ★ 下面三处期望值是**实测**出来的，不是想当然（第一版我按"dict 里没这个键"写，
    #   门禁当场报红才发现取的是 ctx 里的实际值）。「带 default」= 键不存在时回落，
    #   所以键必须**真的不在** ctx 里；「多步」第一步没给 default ⇒ 缺键是 KeyError。
    "field 带 default（键不存在）": (F(S("zz", default={})), {}),
    "field 带 or（键不存在）": (F({"key": "zz", "default": None, "or": []}), []),
    "field 多步": (F(S("stats"), S("kills", default=0)), 7),
    "field 单步取实际值": (F(S("stats")), {"kills": 7}),
    "and": ({"op": "and", "args": [C(1), C(2)]}, 2),
    "or": ({"op": "or", "args": [C(1), C(2)]}, 1),
    "not": ({"op": "not", "arg": C(1)}, False),
    "len": ({"op": "len", "arg": C([1, 2])}, 2),
    "int": ({"op": "int", "arg": C(7)}, 7),
    "truthy": ({"op": "truthy", "arg": C(1)}, True),
    "contains": ({"op": "contains", "elem": C(1), "seq": C([1, 2])}, True),
    "eq": ({"op": "eq", "left": C(1), "right": C(1)}, True),
    "gt": ({"op": "gt", "left": C(2), "right": C(1)}, True),
}


def t1_bad_raises():
    """【1】8 条守卫的坏输入一律抛点名的 SpecError（逐组逐样本）"""
    for label, fns in BAD.items():
        for i, fn in enumerate(fns):
            check("[1] %s #%d → SpecError" % (label, i), *raises_spec(fn))


def t2_named_error_not_bare():
    """【2】退化形态单列：拆守卫后实到的是**裸 TypeError**（点名全丢），
    本组钉住「现在仍要点名 SpecError」，退化形态若变化判据会报红。"""
    for label, fn in (("L118 步不是 Mapping", lambda: D.compile_spec({"field": [42]})),
                      ("L273 args 不是 list", lambda: D.compile_spec({"op": "and", "args": 5}))):
        kind, name, msg = spec_of(fn)
        check("[2] %s 仍是点名 SpecError（不是裸 %s）" % (label, name),
              kind == "exc" and name == "SpecError", (kind, name, msg))


def t3_good_unchanged():
    """【3】合法面逐字不变（钉「严格 ≠ 见谁都抛」）"""
    ctx = {"a": 3, "stats": {"kills": 7}, "xs": [1, 2]}
    for label, (spec, want) in GOOD.items():
        try:
            got = D.compile_spec(spec)(copy.deepcopy(ctx))
        except Exception as exc:                                        # noqa: BLE001
            check("[3] 合法面 %s" % label, False, "%s: %s" % (type(exc).__name__, exc))
            continue
        check("[3] 合法面 %s" % label, got == want, (got, want))


def t4_table_fail_closed():
    """【4】整表编译：任一条坏 ⇒ 一条都不装（compile_specs / register_specs）"""
    check("[4] compile_specs 整表里有坏节点 → SpecError",
          *raises_spec(D.compile_specs, {"good": C(1), "bad": F(S(""))}))
    got = D.compile_specs({"a": C(1), "b": C(2)})
    check("[4] compile_specs 合法表逐字装上", sorted(got) == ["a", "b"], sorted(got))
    seen = []
    collect2 = lambda k, f: seen.append(k)                                # noqa: E731
    check("[4] register_specs 整表里有坏节点 → SpecError",
          *raises_spec(D.register_specs, collect2, {"good": C(1),
                                                    "bad": {"op": "or", "args": []}}))
    check("[4] register_specs 坏表一条都不登记", seen == [], seen)
    check("[4] compile_specs 非映射表 → SpecError", *raises_spec(D.compile_specs, [("a", 1)]))
    check("[4] register_specs 的 register_fn 不可调用 → SpecError",
          *raises_spec(D.register_specs, "notcallable", {"a": C(1)}))
    got_keys = []
    ok2 = D.register_specs(lambda k, f: got_keys.append(k), {"a": C(1), "b": C(2)})
    check("[4] register_specs 合法表逐条登记", got_keys == ["a", "b"], got_keys)
    check("[4] register_specs 返回值就是编译表", sorted(ok2) == ["a", "b"], sorted(ok2))


def t5_teeth():
    """【5】有牙反证：逐条拆 8 条守卫 → 本门禁必须每条都转红。

    ★ 驱动器在**一次性副本**上施加变异（`tests/_conditions_declar_mutant.py`），
      真仓全程零写入。2026-09-29 实踩：改成真仓变异后，子进程超时**不会被杀**
      （subprocess 只抛 TimeoutExpired）⇒ 一批残留进程继续往真仓写变异态，
      `git checkout` 刚还原就被下一个覆盖 ⇒ 差点真删掉生产码的守卫。
      ⇒ 「带递归标记」只防递归、防不住残留进程；**唯一稳的形态是变异不落在真仓**。
    """
    driver = os.path.join(_HERE, "_conditions_declar_mutant.py")
    env = dict(os.environ)
    env.pop("AFIX4_MUTANT_CHILD", None)      # 让驱动器能起跑
    p = subprocess.run([PY, driver], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=ROOT, env=env, timeout=540)
    out = (p.stdout or "") + (p.stderr or "")
    check("[5] 逐条拆守卫 8/8 全转红（判据有牙）", p.returncode == 0,
          out[-600:] if p.returncode else "")
    check("[5] 反证全程真仓零写入（REAL-REPO-UNTOUCHED OK）",
          "REAL-REPO-UNTOUCHED OK" in out, out[-300:])
    check("[5] 变异扫描未漏锚点", "ANCHOR-MISS" not in out, out[-300:])


def main():
    for fn in (t1_bad_raises, t2_named_error_not_bare, t3_good_unchanged,
               t4_table_fail_closed, t5_teeth):
        fn()
    print("通过 %d · 失败 %d" % (passed, failed))
    if failed:
        for d in DETAIL[:20]:
            print("  ❌", d)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
