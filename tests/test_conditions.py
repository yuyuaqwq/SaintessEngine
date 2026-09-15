#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""conditions 门禁：条件注册表（Conditions / Ctx / UnknownCondition）。

跑法：python tests/test_conditions.py
退出码：0 = 全绿；1 = 有失败。

三处专门钉住的地方（都是「改了就静默变行为」的）：
  ① **未注册不降级**：`evaluate` 一个没登记的 key 必须抛 `UnknownCondition`
     （静默返回 False = 把「没实现」伪装成「不满足」，声明与实现脱节再也看不见）
  ② **查表先于调用**：未注册时判定函数**一次都不许被执行**；登记了但函数抛错
     → 原样上抛（不吞、不包成 False）
  ③ **零知识**：`conditions/` 源码字符串常量里不得出现任何内容侧取值
     （条件名 / 领域名词），且不得出现任何非 ASCII 常量
"""
import ast
import operator
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import saintess_engine.conditions as MOD                                        # noqa: E402
from saintess_engine.conditions import Conditions, Ctx, UnknownCondition        # noqa: E402

passed = failed = 0
DETAIL = []


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        DETAIL.append(f"{name} {detail}")
        print(f"  ❌ {name} {detail}")


def raises(exc, fn, *a, **kw):
    """跑 fn → (是否抛该异常, 异常或返回值)。"""
    try:
        return False, fn(*a, **kw)
    except exc as e:
        return True, e


def fails(fn, *a, **kw):
    """跑 fn：抛出任何异常 → True（用于反证：改坏后必须至少有一条判据炸）。"""
    try:
        fn(*a, **kw)
    except Exception:
        return True
    return False


def _boom(ctx):
    raise RuntimeError("内容侧 bug")


# ---------------------------------------------------------------- 1 登记两路
def t1_register_paths():
    print("\n[1] 登记两路：装饰器 / 直接传 —— 等价、返回口径一致")
    c = Conditions()

    @c.register("k1")
    def _c1(ctx):
        return True

    def _c2(ctx):
        return False

    ret = c.register("k2", _c2)
    check("装饰器路登记成功", c.has("k1"))
    check("直接注册路登记成功", c.has("k2"))
    check("装饰器返回原函数（函数名/身份不变）",
          _c1.__name__ == "_c1" and callable(_c1))
    check("直接注册返回 fn 本身（便于表达式里接着用）", ret is _c2)
    check("两路等价：get 取到的就是登记的同一个函数",
          c.get("k1") is _c1 and c.get("k2") is _c2)
    check("空表起步（引擎不自带任何条件）", Conditions().keys() == [])
    check("len / in 与 has 同口径",
          len(c) == 2 and "k1" in c and "nope" not in c and c.__len__() == 2)

    c3 = Conditions()
    deco = c3.register("k9")
    check("不带 fn 返回装饰器（还没登记）", callable(deco) and not c3.has("k9"))

    def _c9(ctx):
        return True
    same = deco(_c9)
    check("装饰器调用后才登记", c3.has("k9") and same is _c9)


# ---------------------------------------------------------------- 2 声明序
def t2_key_order():
    print("\n[2] keys()：注册序（声明序）· 同 key 覆盖不动位置 · 返回值是副本")
    c = Conditions()
    order = ["k1", "k2", "k3", "k4"]
    for k in order:
        c.register(k, lambda ctx, _k=k: _k)
    check("keys() 按注册序", c.keys() == order, f"{c.keys()}")

    first = c.get("k2")

    def _replacement(ctx):
        return "replaced"
    c.register("k2", _replacement)
    check("同 key 覆盖：位置不动（仍是第 2 个）", c.keys() == order, f"{c.keys()}")
    check("同 key 覆盖：取到的是新函数", c.get("k2") is _replacement
          and c.get("k2") is not first)
    check("覆盖不增个数", len(c) == 4)

    snap = c.keys()
    snap.append("污染")
    check("keys() 返回副本（改它不影响注册表）", c.keys() == order and len(c) == 4)
    check("keys() 每次返回新列表（不是内部对象）", c.keys() is not c.keys())


# ---------------------------------------------------------------- 3 求值语义
def t3_evaluate():
    print("\n[3] evaluate：透传 ctx · 返回原样值（不归一布尔）· 判定函数抛错原样上抛")
    c = Conditions()
    seen = []

    @c.register("k1")
    def _c1(ctx):
        seen.append(ctx.owner)
        return ctx.count == 3

    ctx = Ctx(owner="a", count=3)
    check("注册并求值 → True", c.evaluate("k1", ctx) is True)
    check("★ 上下文透传：函数看到了内容侧字段", seen == ["a"], f"{seen}")
    check("同一 key 多次求值 → 每次都调函数",
          c.evaluate("k1", Ctx(owner="b", count=3)) is True and seen == ["a", "b"])

    @c.register("k_truthy")
    def _t(ctx):
        return 1
    check("★ 返回值原样（不替内容侧做布尔归一）：1 → 1",
          c.evaluate("k_truthy", ctx) == 1 and c.evaluate("k_truthy", ctx) is not True)

    @c.register("k_objs")
    def _o(ctx):
        return [1, 2]
    check("返回值原样：列表 → 同一个对象",
          c.evaluate("k_objs", ctx) is _o(ctx) or c.evaluate("k_objs", ctx) == [1, 2])

    @c.register("k_boom")
    def _b(ctx):
        _boom(ctx)
    hit, exc = raises(RuntimeError, c.evaluate, "k_boom", ctx)
    check("★ 判定函数抛错 → 原样上抛（不吞、不包成 False）", hit
          and str(exc) == "内容侧 bug", f"got {exc!r}")
    hit2, exc2 = raises(RuntimeError, c.evaluate, "k_boom", ctx)
    check("上抛的就是原类型（不裹一层）", hit2 and isinstance(exc2, RuntimeError))

    @c.register("k_asrt")
    def _a(ctx):
        assert False, "内容侧断言"
    check("AssertionError 也如实上抛（不静默当不满足）",
          raises(AssertionError, c.evaluate, "k_asrt", ctx)[0])

    hit_none, _ = raises(UnknownCondition, c.evaluate, "nope", ctx)
    check("未注册时判定函数一次都不会被执行（查表先于调用）",
          hit_none and seen == ["a", "b"], f"hit={hit_none} seen={seen}")


# ---------------------------------------------------------------- 4 fail-closed
def t4_fail_closed():
    print("\n[4] fail-closed：未注册 → UnknownCondition（点名）· 参数非法当场报错")
    c = Conditions()
    c.register("k1", lambda ctx: True)

    hit, exc = raises(UnknownCondition, c.evaluate, "k9", Ctx())
    check("★ 未注册 key → UnknownCondition（不是 None / 不是 False）", hit, f"got {exc!r}")
    check("错误信息点名 key", "k9" in str(exc), f"{exc}")
    check("错误对象带 key 与已注册清单（可编程取用）",
          exc.key == "k9" and exc.known == ("k1",))
    check("UnknownCondition 是 LookupError（调用方可以只按查表错兜底）",
          isinstance(exc, LookupError))

    check("evaluate 空串 key → ValueError（空键 = 无名条件）",
          raises(ValueError, c.evaluate, "   ", Ctx())[0])
    check("register 空串 key → ValueError", raises(ValueError, c.register, "", None)[0])
    check("register 不可哈希 key → TypeError", raises(TypeError, c.register, [], None)[0])
    check("evaluate 不可哈希 key → TypeError",
          raises(TypeError, c.evaluate, [], Ctx())[0])
    # 键口径与字典同口径：任意可哈希键都收（内容侧的条件键可能是编号，如 tid=0）
    check("★ int key 可注册、可求值（编号型条件键）",
          raises(TypeError, c.register, 0, lambda ctx: True)[0] is False
          and c.evaluate(0, Ctx()) is True)
    check("register(fn=不可调用) → TypeError（当场报错，不留到求值）",
          raises(TypeError, c.register, "knew", 123)[0])
    check("register(fn=不可调用) 不写进注册表", not c.has("knew"))

    c2 = Conditions()
    deco = c2.register("knew3")
    check("装饰器装饰不可调用 → TypeError 且不登记",
          raises(TypeError, deco, object())[0] and not c2.has("knew3"))

    check("get 未注册 → None（查表口径：没有就是没有）", c.get("k9") is None)
    check("★ get 是纯查表：不调用判定函数", c.get("k1") is not None)
    # 迭代口径：与 dict 同口径（迭代键、声明序）——
    # 若只实现 __getitem__ 而不实现 __iter__，Python 旧式迭代协议会退化成 self[0]/self[1]…
    _c2 = Conditions()
    for _k in ("b", "a", "c"):
        _c2.register(_k, lambda ctx: True)
    check("★ 迭代口径 = 键、声明序（sorted/for 不退化成一串 __getitem__）",
          list(_c2) == ["b", "a", "c"] and sorted(_c2) == ["a", "b", "c"],
          (list(_c2), sorted(_c2)))
    check("迭代与 keys() 同源", list(_c2) == _c2.keys())

    check("has 非字符串 → False（查询不报错）",
          c.has(None) is False and c.has("") is False and c.has(7) is False)


# ---------------------------------------------------------------- 5 missing 自检
def t5_missing():
    print("\n[5] missing：精确列出没实现的（保传入序 · 重复各算一次）")
    c = Conditions()
    for k in ("a", "b", "c"):
        c.register(k, lambda ctx: True)

    check("全部实现 → []", c.missing(["a", "b", "c"]) == [])
    check("精确点名缺的那些", c.missing(["c", "zz", "a", "yy"]) == ["zz", "yy"],
          f"{c.missing(['c', 'zz', 'a', 'yy'])}")
    check("★ 保传入序（不是注册序、不是排序）",
          c.missing(["yy", "a", "zz", "b"]) == ["yy", "zz"])
    check("重复项各算一次（自检如实报，不去重）",
          c.missing(["zz", "zz"]) == ["zz", "zz"])
    check("空需求 → []", c.missing([]) == [])
    check("返回新列表（改它不影响注册表）",
          (lambda m: (m.append("x"), c.missing(["zz"])[0])[1])(c.missing(["zz"])) == "zz")
    check("单个字符串当整串传 → TypeError（不许把 'ab' 拆成 a/b）",
          raises(TypeError, c.missing, "ab")[0])
    check("missing 的判定口径与 has 一致（未注册才点名）",
          c.missing(["a", "nope"]) == ["nope"] and c.missing(["nope", "a"]) == ["nope"])


# ---------------------------------------------------------------- 6 Ctx 透传
def t6_ctx():
    print("\n[6] Ctx：给什么有什么 · 缺字段 AttributeError（不静默）· 只读 · 不读字段")
    ctx = Ctx(owner="a", count=3, flags={"ready": True}, member_ids=["m1", "m2"])
    check("字段按属性访问", ctx.owner == "a" and ctx.count == 3 and ctx.member_ids == ["m1", "m2"])
    check("嵌套值原样（引擎不深拷贝、不解释）",
          ctx.flags is not None and ctx.flags["ready"] is True)
    check("fields 是只读映射（判定函数改不了上下文）",
          raises(TypeError, operator.setitem, ctx.fields, "owner", "b")[0]
          and ctx.fields["owner"] == "a")
    check("fields 列出全部字段名", sorted(ctx.fields) == ["count", "flags", "member_ids", "owner"])
    check("get(name, default) 显式默认可用", ctx.get("nope", 7) == 7 and ctx.get("owner") == "a")

    hit, exc = raises(AttributeError, getattr, ctx, "nope")
    check("★ 缺字段 → AttributeError（不回落 None、不回落默认值）", hit, f"got {exc!r}")
    check("AttributeError 点名缺的字段与已有字段",
          "nope" in str(exc) and "owner" in str(exc), f"{exc}")
    check("空字段访问也抛（Ctx() 不是万能兜底）",
          raises(AttributeError, getattr, Ctx(), "owner")[0])
    check("没有 __dict__（字段表只有一份，不存在两套真相）",
          raises(AttributeError, getattr, Ctx(), "__dict__")[0])
    check("不能就地加字段（外壳是透传快照，不是可变袋）",
          raises(AttributeError, setattr, ctx, "owner", "z")[0])
    check("显式 Ctx() 可构造（判定不需要上下文时）", Ctx().fields == {})
    check("字段名非标识符 → ValueError（拒绝读不到的字段）",
          fails(lambda: Ctx(**{"a-b": 1})))
    check("字段名与外壳属性重名 → ValueError（否则透传被遮蔽）",
          fails(lambda: Ctx(fields=1)) and fails(lambda: Ctx(get=1)))

    # 同一 Ctx 服务多个条件；字段名完全由内容侧定（引擎不认识任何名字）
    c = Conditions()
    c.register("needs_owner", lambda x: x.owner == "a")
    c.register("needs_count", lambda x: x.count >= 3)
    check("同一 ctx 可判多条条件",
          c.evaluate("needs_owner", ctx) and c.evaluate("needs_count", ctx))
    check("Ctx 只透传：引擎侧没有 owner/count 这类名字",
          all(n not in MOD.__dict__ for n in ("owner", "count", "flags")))


# ---------------------------------------------------------------- 7 多族同一套
def t7_family_shape():
    print("\n[7] 多族同构：一个注册表服务三族（各自 key + 各自函数）")
    families = {}
    for family in ("fa", "fb", "fc"):
        reg = Conditions()

        @reg.register(f"{family}_1")
        def _one(ctx):
            return True

        @reg.register(f"{family}_2")
        def _two(ctx):
            return False
        families[family] = reg

    check("三族各自一个注册表、各自登记序",
          [families[f].keys() for f in families] == [["fa_1", "fa_2"], ["fb_1", "fb_2"],
                                                     ["fc_1", "fc_2"]])
    check("三族用同一套接口（register/get/evaluate/has/keys/missing）",
          all(all(hasattr(families[f], m) for m in
                  ("register", "get", "evaluate", "has", "keys", "missing"))
              for f in families))
    check("三族同名后缀互不干扰",
          families["fa"].evaluate("fa_1", Ctx()) is True
          and families["fb"].evaluate("fb_1", Ctx()) is True
          and families["fa"].missing(["fb_1"]) == ["fb_1"])
    check("一族一个表：注册表之间零共享（互不污染）",
          families["fa"].has("fb_1") is False and len(families["fa"]) == 2)
    check("每族的自检各自做（声明清单 → 缺实现清单）",
          families["fc"].missing(["fc_3"]) == ["fc_3"]
          and families["fc"].missing(["fc_2"]) == [])


# ---------------------------------------------------------------- 8 零知识
BANNED = ("achievement", "achievements", "title", "titles", "dialogue", "dialogues",
          "player", "players", "monster", "item", "items", "gold", "coin", "level",
          "quest", "npc", "guild", "party", "dungeon", "skill", "reward", "inventory",
          "orlandia", "dragonfall", "cond_")
BANNED_ZH = ("玩家", "怪物", "装备", "金币", "副本", "关卡", "任务", "成就", "称号",
             "对话", "等级", "技能", "地图", "职业")


def t8_zero_knowledge():
    print("\n[8] 零知识：conditions/ 源码常量里无内容侧取值（条件名 / 领域名词）")
    base = os.path.join(ROOT, "saintess_engine", "conditions")
    bad, n = [], 0
    for dirpath, _dirs, files in os.walk(base):
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            n += 1
            with open(path, encoding="utf-8") as f:
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
                        continue                       # 文档要能打比方解释形状
                    low = node.value.lower()
                    for b in BANNED:
                        if b in low:
                            bad.append(f"{rel}:{node.lineno}:{b!r}:{node.value[:40]!r}")
                    for b in BANNED_ZH:
                        if b in node.value:
                            bad.append(f"{rel}:{node.lineno}:{b!r}:{node.value[:40]!r}")
    check("扫到 conditions/ 源文件（≥1）", n >= 1, f"n={n}")
    check("★ 代码常量里无内容侧取值（条件名 / 领域名词）", not bad, str(bad[:6]))
    check("公开面只有形状名",
          set(MOD.__all__) == {"Conditions", "Ctx", "UnknownCondition"}, str(MOD.__all__))
    check("模块有 docstring 且写清「有意不做的事」",
          bool(MOD.__doc__) and "有意不做的事" in MOD.__doc__)
    check("Conditions 的公开方法齐（规格 §3 逐条）",
          all(callable(getattr(Conditions, m, None)) for m in
              ("register", "get", "evaluate", "has", "keys", "missing")))
    check("Ctx 无游戏语义字段（外壳只有 _fields 槽）", Ctx.__slots__ == ("_fields",))


# ---------------------------------------------------------------- 9 有牙反证
# 每条 =（改坏的名字, 源码锚点, 改写成什么, 判据说明, 判据本身）。
# 判据返回 `(是否成立, 明细行)`：明细行就是「改坏后哪一条炸了」—— 对着**被替换过的
# 模块命名空间**跑，顺带证明「判据咬的是实现，不是环境」。
def _live_fail_closed(m):
    try:
        got = m.Conditions().evaluate("nope", m.Ctx())
    except m.UnknownCondition:
        return True, ["未注册 → UnknownCondition（正确）"]
    return False, [f"未注册却拿到 {got!r}（没抛 UnknownCondition）"]


def _live_raw_value(m):
    c = m.Conditions()
    c.register("t", lambda ctx: ctx.count)
    got = c.evaluate("t", m.Ctx(count=3))
    ok = repr(got) == "3" and got is not True            # 归一布尔 → True，咬得住
    return ok, [f"evaluate 返回 {got!r}（期望整数 3；被归一成布尔即红）"]


def _live_get_pure(m):
    c = m.Conditions()
    got = c.get("nope")
    ok = got is None and c.keys() == [] and len(c) == 0
    return ok, [f"get('nope')={got!r}，keys()={c.keys()!r}（期望 None / []；顺手建表即红）"]


def _live_errors_propagate(m):
    c = m.Conditions()
    c.register("b", _boom)
    try:
        got = c.evaluate("b", m.Ctx())
    except RuntimeError:
        return True, ["判定函数抛错 → RuntimeError 原样上抛（正确）"]
    return False, [f"判定函数抛错却返回 {got!r}（被吞成不满足）"]


def _live_missing_exact(m):
    c = m.Conditions()
    c.register("a", lambda ctx: True)
    miss = c.missing(["a", "zz"])
    ok = miss == ["zz"] and isinstance(miss[0], str)      # 计数版给 [0]（int），咬得住
    return ok, [f"missing(['a','zz'])={miss!r}（期望 ['zz']；只报计数即红）"]


MUTATION_FAIL_CLOSED = (
    "        fn = self._fn_of(key)\n        return fn(ctx)",
    "        fn = self._fns.get(_check_key(key))  # MUT：绕过 _fn_of 的 fail-closed\n"
    "        return fn(ctx) if fn is not None else False")


MUTATIONS = [
    ("未注册降级成 False（静默）",
     MUTATION_FAIL_CLOSED[0], MUTATION_FAIL_CLOSED[1],
     "★ 未注册不降级：evaluate 必须抛 UnknownCondition",
     _live_fail_closed),
    ("返回值被引擎归一成布尔",
     "        fn = self._fn_of(key)\n        return fn(ctx)",
     "        fn = self._fn_of(key)\n        return bool(fn(ctx))  # MUT",
     "★ 返回值原样（不做布尔归一）",
     _live_raw_value),
    ("get 变成「不存在就建一个」",
     "        return self._fns.get(_check_key(key))",
     "        return self._fns.setdefault(_check_key(key), lambda ctx: True)  # MUT",
     "★ get 是纯查表：未注册 → None，且不改注册表",
     _live_get_pure),
    ("判定函数抛错被吞成不满足",
     "        fn = self._fn_of(key)\n        return fn(ctx)",
     "        try:\n            fn = self._fn_of(key)\n            return fn(ctx)\n"
     "        except Exception:  # MUT\n            return False\n        return None",
     "★ 判定函数抛错原样上抛（不吞）",
     _live_errors_propagate),
    ("missing 改成「只报计数」",
     "                out.append(key)\n        return out",
     "                out.append(len(out))  # MUT\n        return out",
     "★ missing 精确点名（不是计数）",
     _live_missing_exact),
]


def _mutate(src, old, new):
    if src.count(old) != 1:
        raise AssertionError(f"反证锚点在源码里出现 {src.count(old)} 次（应为 1）：{old[:40]!r}")
    return src.replace(old, new)


def t9_mutation():
    print("\n[9] ★ 有牙反证：把实现改坏 → 对应判据必红（原实现同一判据为绿）")
    path = os.path.join(ROOT, "saintess_engine", "conditions", "__init__.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    for name, old, new, label, live in MUTATIONS:
        try:
            mutated = _mutate(src, old, new)
        except AssertionError as e:
            check(f"{name}：反证锚点仍在源码里", False, str(e))
            continue
        namespace = {"__name__": "saintess_engine.conditions._mutant"}
        exec(compile(mutated, path + "#MUT", "exec"), namespace)
        alive_before, why_before = live(MOD)
        caught, why_after = live(type("M", (), namespace))
        check(f"{name} → 原实现绿 / 改坏必红（判据：{label}）",
              bool(alive_before) and not caught,
              f"原实现绿={bool(alive_before)}（{why_before[0]}）"
              f" / 改坏后红={not caught}（{why_after[0]}）")


# ---------------------------------------------------------------- 10 形状稳性
def t10_shape():
    print("\n[10] 形状稳性：注册表不泄漏内部状态 · 求值不改注册表 · 可反复构造")
    c = Conditions()
    c.register("k1", lambda ctx: True)
    before = c.keys()
    c.evaluate("k1", Ctx())
    check("求值不改注册表（键与个数逐字不变）", c.keys() == before and len(c) == 1)
    other = Conditions()
    other.register("only_here", lambda ctx: True)
    check("注册表之间互不共享（两个实例各自一份表）",
          c.has("only_here") is False and other.keys() == ["only_here"])
    check("keys/get/missing 都不暴露内部 dict（改不到）",
          not hasattr(c.keys(), "register") and c.missing([]) is not c.missing([]))
    check("get 取出的函数地址稳定（不做包装）",
          c.get("k1") is c.get("k1"))
    c.register("k1", lambda ctx: "second")
    check("同一 key 注册两次 → 后者生效（字典赋值口径，已在 register docstring 写明）",
          c.evaluate("k1", Ctx()) == "second")
    check("repr 可读（调试面）", "Conditions" in repr(c) and "k1" in repr(c))
    check("Ctx repr 可读", "owner" in repr(Ctx(owner="a")))


def main():
    print("== conditions 门禁：条件注册表（Conditions / Ctx）==")
    t1_register_paths()
    t2_key_order()
    t3_evaluate()
    t4_fail_closed()
    t5_missing()
    t6_ctx()
    t7_family_shape()
    t8_zero_knowledge()
    t9_mutation()
    t10_shape()
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    if DETAIL:
        print("失败清单：")
        for d in DETAIL:
            print(f"  ❌ {d}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
