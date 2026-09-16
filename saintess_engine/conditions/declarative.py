# -*- coding: utf-8 -*-
"""声明式判定装配 —— 把「形状固定」的判定从代码搬进数据（conditions 的配套件）。

`Conditions` 只做三件事：登记 / 查表 / 求值 —— 判定**从哪来**它不管。
本模块给出**一种**来源：一段 JSON 形状的声明，由内容侧写在数据里。

节点形状（只有三种）
--------------------
取值：
    {"const": <任意值>}                          常量，原样返回（不做布尔归一）
    {"field": [<步>, <步>, ...]}                  按步链取值，见下

比较 / 布尔 / 尺寸 / 成员：
    {"op": "eq"|"ne"|"lt"|"le"|"gt"|"ge", "left": <节点>, "right": <节点>}
    {"op": "and"|"or", "args": [<节点>, ...]}
    {"op": "not", "arg": <节点>}
    {"op": "truthy", "arg": <节点>}              取 bool()
    {"op": "len", "arg": <节点>}                 取 len()
    {"op": "int", "arg": <节点>}                  取 int(v or 0)
    {"op": "contains", "elem": <节点>, "seq": <节点>}     elem in seq

`and` / `or` 用 Python 原生语义：短路，且返回**原操作数**（不是归一后的 bool）。
这条是必须的 —— 内容侧旧写法 `a and b` / `a or []` 的返回值形状就是这样，
改成 bool 归一就不再是「同输入同结果」。

步链（`field`）为什么不是点分字符串
-----------------------------------
内容侧旧写法的取数链是**逐步不同口径**的，混着四种动作：

    ctx.stats.get("kills", 0)                       属性取 + .get(键, 缺省)
    (ctx.quests.get("side") or {}).get(sid, {})       .get 后再 `or {}` 兜底
    (player or {}).get("faction")                    `or {}` 兜底后再 .get
    (player or {})["qq_id"]                          直接下标（缺键就炸）

点分字符串表达不了「哪一步兜底、兜成什么」，于是本模块把每一步写成显式的一步：

    {"key": "<键>", "default": <任意>, "or": <任意>}     后两个都可省

    * `default` 给了 → 这一步按 `.get(键, default)` 口径（取不到给 default）；
      没给 → 直接下标/属性取（取不到就抛，与旧写法一致）。
    * `or` 给了 → 这一步取完再 `v = v or <or>`（对应内容侧的 `or {}` / `or []`）。

    第一步在**上下文对象**上取：映射用下标、其它对象用属性。
    其后每一步在**上一步的值**上取：直接调它的 `.get(键, default)` / `[键]`
    —— 所以「上一步是 None / 字符串」这类输入会抛出和旧写法**同一个类型**的异常。

装载期校验（`compile_spec` / `compile_specs` / `register_specs`）
----------------------------------------------------------------
算子不认识 / 节点形状不对 / `field` 步链为空 / `args` 空 → `SpecError`。
**绝不**把不认识的算子当永假或恒真：那样「声明写错了」会伪装成「判定不满足」。
求值期的类型错误照 Python 原样抛：不吞、不强转 —— 旧判定怎么写，新装配就怎么判。

有意不做的事
------------
* 不做算术：四则运算见 `saintess_engine.expr`；这里只有比较 / 布尔 / 长度 / 成员。
* 不认识任何具体字段名、键名、域名词：全部由内容侧在数据里给 —— 引擎零领域知识。
* 不做缓存、不打日志、不吞异常、不做超时。
* 不读文件：调用方把数据读成映射再传进来（本模块只管形状）。

多参旧签名（`names`）
---------------------
旧判定函数常常是多参形状（`fn(a, b, c, ...)`）。`names` 给出形参名序列后，
`bind_spec` 返回 `fn(*args)`：把位置实参按 `names` 绑成一个映射再求值 ——
**调用方一行不用改**，签名与实参个数校验都保持不变。
"""
from __future__ import annotations

from collections.abc import Mapping

__all__ = ["SpecError", "compile_spec", "compile_specs", "bind_spec", "register_specs"]

_CMP = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "lt": lambda a, b: a < b,
    "le": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "ge": lambda a, b: a >= b,
}

_OPS = frozenset(_CMP) | {"and", "or", "not", "truthy", "len", "int", "contains"}

_KEYS_CONST = frozenset({"const"})
_KEYS_FIELD = frozenset({"field"})
_KEYS_STEP = frozenset({"key", "default", "or"})
_KEYS_CMP = frozenset({"op", "left", "right"})
_KEYS_BOOL = frozenset({"op", "args"})
_KEYS_ARG = frozenset({"op", "arg"})
_KEYS_MEMBER = frozenset({"op", "elem", "seq"})


#: 「这一步没给 default」哨兵（与「default 就是 None」分开）
_MISSING = object()


class SpecError(ValueError):
    """声明形状不合法 —— 装载期错误，绝不静默降级。"""


def _step(step):
    """一步 → `(键, 取值函数, 是否有 or, or 值)`。形状不对 → SpecError。"""
    if not isinstance(step, Mapping):
        raise SpecError("步必须是字典，收到 %s" % type(step).__name__)
    if not frozenset(step) <= _KEYS_STEP:
        raise SpecError("步的键不对：%r" % (sorted(step),))
    if "key" not in step:
        raise SpecError("步必须给 key：%r" % (sorted(step),))
    key = step["key"]
    if not isinstance(key, str) or not key:
        raise SpecError("步的 key 必须是非空字符串：%r" % (key,))
    if "or" in step:
        or_value = step["or"]
        return key, step.get("default", _MISSING), True, or_value
    return key, step.get("default", _MISSING), False, None


def _take_root(ctx, key, default):
    """第一步：在**上下文对象**上取 —— 映射用下标/`.get`，其它对象用属性。"""
    if isinstance(ctx, Mapping):
        if default is _MISSING:
            return ctx[key]
        return ctx.get(key, default)
    if default is _MISSING:
        return getattr(ctx, key)
    return getattr(ctx, key, default)


def _take_step(cur, key, default):
    """其后每一步：在**上一步的值**上取 —— 按旧写法就是 `.get(键, 缺省)` / `[键]`。

    这里刻意**不做**「不是映射就兜底」：旧写法在上一步是 None / 字符串时抛什么，
    这里就抛什么（同一个异常类型），否则「同输入同结果」就不成立了。
    """
    if default is _MISSING:
        return cur[key]
    return cur.get(key, default)


def _compile_field(steps):
    if not isinstance(steps, list) or not steps:
        raise SpecError("field 的步链必须是非空列表：%r" % (steps,))
    parsed = [_step(s) for s in steps]

    def _field(ctx):
        key, default, has_or, or_value = parsed[0]
        cur = _take_root(ctx, key, default)
        if has_or:
            cur = cur or or_value
        for key, default, has_or, or_value in parsed[1:]:
            cur = _take_step(cur, key, default)
            if has_or:
                cur = cur or or_value
        return cur

    return _field


def _compile(spec):
    """声明节点 → 单参可调用（`fn(ctx) -> 任意值`）。形状不对当场 SpecError。"""
    if not isinstance(spec, Mapping):
        raise SpecError("声明节点必须是字典，收到 %s" % type(spec).__name__)
    if "const" in spec:
        if frozenset(spec) != _KEYS_CONST:
            raise SpecError("const 节点的键不对：%r" % (sorted(spec),))
        value = spec["const"]
        return lambda ctx, _v=value: _v
    if "field" in spec:
        if frozenset(spec) != _KEYS_FIELD:
            raise SpecError("field 节点的键不对：%r" % (sorted(spec),))
        return _compile_field(spec["field"])
    if "op" in spec:
        return _compile_op(spec)
    raise SpecError("声明节点必须含 const / field / op 之一：%r" % (sorted(spec),))


def _compile_op(spec):
    op = spec["op"]
    if op in _CMP:
        if frozenset(spec) != _KEYS_CMP:
            raise SpecError("比较节点的键不对：%r" % (sorted(spec),))
        left = _compile(spec["left"])
        right = _compile(spec["right"])
        cmp_fn = _CMP[op]
        return lambda ctx, _l=left, _r=right, _f=cmp_fn: _f(_l(ctx), _r(ctx))
    if op in ("and", "or"):
        if frozenset(spec) != _KEYS_BOOL:
            raise SpecError("布尔节点的键不对：%r" % (sorted(spec),))
        args = spec["args"]
        if not isinstance(args, list) or not args:
            raise SpecError("args 必须是非空列表：%r" % (args,))
        fns = [_compile(a) for a in args]
        if op == "and":
            def _and(ctx, _fns=fns):
                out = None
                for fn in _fns:
                    out = fn(ctx)
                    if not out:
                        return out
                return out
            return _and

        def _or(ctx, _fns=fns):
            out = None
            for fn in _fns:
                out = fn(ctx)
                if out:
                    return out
            return out
        return _or
    if op == "not":
        if frozenset(spec) != _KEYS_ARG:
            raise SpecError("not 节点的键不对：%r" % (sorted(spec),))
        arg = _compile(spec["arg"])
        return lambda ctx, _a=arg: not _a(ctx)
    if op == "truthy":
        if frozenset(spec) != _KEYS_ARG:
            raise SpecError("truthy 节点的键不对：%r" % (sorted(spec),))
        arg = _compile(spec["arg"])
        return lambda ctx, _a=arg: bool(_a(ctx))
    if op == "len":
        if frozenset(spec) != _KEYS_ARG:
            raise SpecError("len 节点的键不对：%r" % (sorted(spec),))
        arg = _compile(spec["arg"])
        return lambda ctx, _a=arg: len(_a(ctx))
    if op == "int":
        if frozenset(spec) != _KEYS_ARG:
            raise SpecError("int 节点的键不对：%r" % (sorted(spec),))
        arg = _compile(spec["arg"])
        return lambda ctx, _a=arg: int(_a(ctx) or 0)
    if op == "contains":
        if frozenset(spec) != _KEYS_MEMBER:
            raise SpecError("contains 节点的键不对：%r" % (sorted(spec),))
        elem = _compile(spec["elem"])
        seq = _compile(spec["seq"])
        return lambda ctx, _e=elem, _s=seq: _e(ctx) in _s(ctx)
    raise SpecError("算子不认识：%r（可用：%r）" % (op, sorted(_OPS)))


def compile_spec(spec):
    """声明节点 → `fn(ctx) -> 任意值`。形状不对 → `SpecError`。"""
    return _compile(spec)


def bind_spec(spec, names=None):
    """单条声明 → 可调用（`names` 的口径见 `compile_specs`）。"""
    fn = _compile(spec)
    if not names:
        return fn
    names = tuple(names)
    if len(names) == 1:
        return fn

    def _bound(*args, _n=names, _f=fn):
        if len(args) != len(_n):
            raise TypeError("实参个数不对：期望 %d，收到 %d" % (len(_n), len(args)))
        return _f(dict(zip(_n, args)))

    return _bound


def compile_specs(table, names=None):
    """声明表（`{键: 节点}`）→ `{键: 可调用}`。任一条不合法 → `SpecError`（整表不装）。

    `names`：多参旧签名的形参名序列。
    * 不给 / 只给一个名 → 返回单参可调用，直接吃调用方给的上下文对象。
    * 给多个名 → 返回 `fn(*args)`，按 `names` 把位置实参绑成映射再求值。
    """
    if not isinstance(table, Mapping):
        raise SpecError("声明表必须是字典，收到 %s" % type(table).__name__)
    out = {}
    for key, spec in table.items():
        out[key] = bind_spec(spec, names)
    return out


def register_specs(register_fn, table, names=None):
    """把声明表登记进一个注册口：`register_fn(键, 可调用)`。

    先整表编译（任一条不合法 → 一条都不登记），再逐条登记。
    返回 `{键: 可调用}`，方便调用方自行取用。
    """
    if not callable(register_fn):
        raise SpecError("register_fn 必须可调用，收到 %s" % type(register_fn).__name__)
    compiled = compile_specs(table, names)
    for key, fn in compiled.items():
        register_fn(key, fn)
    return compiled
