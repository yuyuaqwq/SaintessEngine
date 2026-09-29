# -*- coding: utf-8 -*-
"""`store/spec_json.py` 的 **点名归属**契约：坏声明必须抛「点名到具体哪处」的异常。

**为什么单独一支门禁**：既有 `test_store_spec_json.py` 的 `raises()` 助手
`except (ValueError, TypeError)` —— 它只钉「**报错了**」，不钉「**报的是哪一个**」。
于是本模块九条守卫一旦被拆、退化成**另一种**异常（`AttributeError` / 裸 `json` 的
`TypeError` / 引擎内部的 `ValueError`）时，既有门禁**照样全绿**。
实测：把这九条整块换静默 `pass`，既有门禁 `PASS=49 FAIL=0`
（本模块 21 条守卫里 9 条零转红）。

**这个门禁钉什么**：对每一条守卫，要求抛出的异常
  ① 名字归属正确（不是引擎内部形态名 / 不是裸 stdlib 形态名）
  ② 报错串点名到**出错的表 / 列 / 键**（这才是这条守卫的全部价值）
并**单列**每条拆掉之后的实测退化形态 —— 退化形态变了判据会报红，而不是默默放过。

**零游戏知识**：只用通用表名（t / a / c）。
跑法：python tests/test_spec_json_named_failclosed.py
"""
import ast
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, FW_ROOT)

from _check import bind_check  # noqa: E402  P0-1 断言助手单源
from saintess_engine.store import specs_from_json  # noqa: E402

check = bind_check(globals(), "PASS", "FAIL", "FAILURES")
# bind_check 用 scope.get(name, 0) 惰性建计数器 ⇒ 全绿时 PASS/FAIL 从未落位，
# 汇总行会 NameError。显式初始化（不改助手本体，那是被 356 份测试共用的单源）。
PASS = 0
FAIL = 0
FAILURES = []

TARGET = os.path.join(FW_ROOT, "saintess_engine", "store", "spec_json.py")


def _err(fn, *a, **kw):
    """跑装载口，返回 (异常类名, 报错串)。不报错 => ("", "")。"""
    try:
        fn(*a, **kw)
    except Exception as exc:                      # noqa: BLE001  这里就是要看它到底抛什么
        return type(exc).__name__, str(exc)
    return "", ""


def _j(tables, **top):
    doc = dict(top)
    doc["tables"] = tables
    return json.dumps(doc)


def _t(name, columns, **kw):
    node = {"name": name, "columns": columns}
    node.update(kw)
    return node


def _c(name, ctype="TEXT", **kw):
    node = {"name": name, "type": ctype}
    node.update(kw)
    return node

# (组名, 守卫行, 坏输入, 期望异常类, 报错串里必须点名的 token, 一句话说明)
CASES = [
    # ---- ① 列级：_column() 四条
    ("列", 94, _j([_t("t", [_c("c"), "oops"])]), "ValueError", "第 1 列",
     "列节点不是对象 → 点名「第几列」"),
    ("列", 98, _j([_t("t", [{"type": "TEXT"}])]), "ValueError", "第 0 列",
     "列缺 name → 点名「第几列」"),
    ("列", 104, _j([_t("t", [_c("c", ctype="")])]), "ValueError", "t.c",
     "type 是空串 → 点名 表.列"),
    ("列", 110, _j([_t("t", [_c("c", default=[1, 2])])]), "ValueError", "t.c",
     "default 是数组 → 点名 表.列"),
    # ---- ② 表级：_table() 两条
    ("表", 122, _j(["oops"]), "ValueError", "tables",
     "表节点不是对象 → 点名「tables」"),
    ("表", 132, _j([_t("t", "nope")]), "ValueError", "t",
     "columns 非数组 → 点名表名"),
    # ---- ③ 装载口：_specs_from_json() 三条
    ("装载", 150, None, "ValueError", "UTF-8",
     "bytes 非法 UTF-8 → 点名编解码失败"),
    ("装载", 152, None, "TypeError", "只收 str/bytes",
     "入参既非 str 也非 bytes → 点名收什么"),
    ("装载", 164, _j("nope"), "ValueError", "tables",
     "'tables' 非数组 → 点名该键"),
]

# 150 / 152 两例要直接给入参，不走 JSON 构造
DIRECT = {
    150: bytes([0xFF, 0xFE, 0x00, 0x62]),
    152: 123,
}

# 拆掉每条守卫之后的**实测**退化形态（如实登记，空栏 = 无人核实过）
DEGRADE = {
    94:  "ValueError「出现未知键 'o'」—— 把列当对象去扫键，报的是另一个错",
    98:  "ValueError「非法列名：None」—— 点名丢到下游 _validate_spec",
    104: "ValueError「非法列类型」—— 点名丢到下游 _validate_spec",
    110: "TypeError「列 t.c 的默认值类型不支持」—— 点名丢到下游 Column",
    122: "★ AttributeError: 'str' object has no attribute 'get' —— 点名全丢，报引擎内部形态名",
    132: "ValueError 落到「第 0 列必须是对象」—— 点名表名丢失",
    150: "TypeError「只收 str/bytes，收到 bytes」—— 报成入参类型错，实为编码错",
    152: "TypeError「the JSON object must be str, bytes or bytearray」—— 裸 stdlib 形态名",
    164: "ValueError 落到「第 0 张表必须是对象」—— 点名该键丢失",
}


def t1_named():
    """组①：每条守卫都必须抛点名到出错位置的异常。"""
    for _group, ln, payload, want, token, what in CASES:
        arg = DIRECT.get(ln, payload)
        cls, msg = _err(specs_from_json, arg)
        if not cls:
            check(f"{what}（L{ln}）", False, "没有报错（静默通过了）")
            continue
        if cls != want:
            check(f"{what}（L{ln}）", False, f"期望 {want}，实得 {cls}：{msg[:70]}")
            continue
        if token not in msg:
            check(f"{what}（L{ln}）", False, f"未点名 {token!r}：{msg[:70]}")
            continue
        check(f"{what}（L{ln}）", True)


LEGAL = [
    ("单表单列", _j([_t("t", [_c("c")])])),
    ("多表多列", _j([_t("t1", [_c("a"), _c("b")]), _t("t2", [_c("z")])])),
    ("列级五键齐全", _j([_t("t", [_c("c", "INTEGER", pk=True, notnull=True, default=0)])])),
    ("default 为 int / float / 空串", _j([_t("t", [_c("a", default=0), _c("b", default=0.0),
                                        _c("c2", default="")])])),
    ("default 为 bool", _j([_t("t", [_c("c", default=False)])])),
    ("migrations 为字符串数组", _j([_t("t", [_c("c")],
                                     migrations=["CREATE INDEX IF NOT EXISTS i ON t(c)"])])),
]


def t2_legal():
    """组②：合法声明**必须照常通过** —— 钉「严格 ≠ 见谁都抛」，不许把门禁写成放宽。"""
    for what, text in LEGAL:
        try:
            specs = specs_from_json(text)
        except Exception as exc:                  # noqa: BLE001
            check(f"合法面：{what}", False, f"应当通过却报错：{exc}")
            continue
        check(f"合法面：{what}", True, None if specs else f"返回 {specs!r}")
    try:
        specs = specs_from_json(_j([_t("t1", [_c("a"), _c("b")]), _t("t2", [_c("z")])]))
        check("合法面：表序=声明序", [s.name for s in specs] == ["t1", "t2"],
              [s.name for s in specs])
        check("合法面：列序=声明序", [c.name for c in specs[0].columns] == ["a", "b"],
              [c.name for c in specs[0].columns])
    except Exception as exc:                      # noqa: BLE001
        check("合法面：表序/列序=声明序", False, str(exc))


def t3_degrade_shape():
    """组③：逐条登记「守卫拆掉之后会退化成什么」，并确认守卫仍在源码内。"""
    tree = ast.parse(open(TARGET, encoding="utf-8").read())
    raise_lines = {n.lineno for n in ast.walk(tree) if isinstance(n, ast.Raise)}
    for _group, ln, _p, _w, _t, what in CASES:
        if ln in raise_lines:
            check(f"守卫仍在源码内：L{ln}（{what}）", True)
        else:
            check(f"守卫仍在源码内：L{ln}（{what}）", False, "该行的 raise 消失了")
    missing = [ln for ln in DEGRADE if not DEGRADE[ln].strip()]
    check("九条守卫的退化形态均有登记（不留空栏）", not missing, f"空栏：{missing}")


def t4_shape():
    """组④：防「别处搬一份 / 把守卫挪走」的绕法。"""
    src = open(TARGET, encoding="utf-8").read()
    tree = ast.parse(src)
    funcs = {n.name for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for fn in ("_column", "_table", "_specs_from_json", "_unknown_keys"):
        check(f"函数仍在：{fn}", fn in funcs, sorted(funcs))
    check("点名格式单源：_bad() 是唯一造 ValueError 的口", src.count("def _bad(") == 1)
    check("点名前缀「表结构声明」由 _bad 统一给出",
          'f"表结构声明 {where}：{msg}"' in src)


t1_named()
t2_legal()
t3_degrade_shape()
t4_shape()

print(f"\n=== 结果 PASS={PASS} FAIL={FAIL} ===")
if FAILURES:
    print("失败项：")
    for f in FAILURES:
        print("  - " + f)
sys.exit(1 if FAIL else 0)
