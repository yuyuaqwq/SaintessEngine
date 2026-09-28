# -*- coding: utf-8 -*-
"""门禁：records/shapes.py 的 ordered 顺序守卫（域序不可静默改序）。

跑法：python tests/test_records_shapes_ordered.py（退出码 0 = 全绿）。

为什么要有这一支（批次 4 · 验证侧缺口 · 生产码零改动）
--------------------------------------------------------
saintess_engine/records/shapes.py::ordered 有**两条** fail-closed 守卫：
  · order 声明里有重复键 → ValueError（"拒绝静默取首个"）
  · 域键集与声明不一致（缺 / 多）→ ValueError（点名缺几个 / 声明缺几个）
两条**全仓零断言**。立项依据不是推断，是**逐条变异实跑**：
把每条 raise 换成静默 pass 后跑全部 6 支 records 门禁，**6/6 全绿零转红**
（test_records_shape 里那条"声明有重复键"用例走的是 Records 包装层 ——
它自己复算了一遍顺序守卫再抛 RecordsOrderMismatch，**压根不进 shapes.ordered**）。

为什么这两条要紧
---------------
ordered 是**引擎给内容包用的公开口**（模块头注：42 个调用点，含 int_keys 等一整族），
它守着「域是 JSON 字典序、真源是插入序」这件事：**把源表改了一行而忘了改声明**，
原实现会静默改序 → 玩家看到的条目顺序整个翻转。重复键那条更毒：
{k: tbl[k] for k in keys} 遇到重复键会**同一个值落两次**，声明本身写错却零报错。
现已零消费者（views.py 只用 same_container），但**它是公开 API 面**，删不得、
也不该在没有断言的情况下留着。

钉住的判据
----------
1 重复键声明 → ValueError，文案点名「重复键」且给出 who / where（调用方措辞原样透传）。
2 键集不齐（缺 / 多）→ ValueError，文案带两侧**计数** + 缺键样本 + 未声明键样本。
3 ★ **合法档逐字不变**：按声明序重排、值逐个对应、键集不变（补判据不改行为）。
4 ★ **空表不抛、返回 {}**（模块头注明写"域读不到 → {} 不抛"）：钉的是"严格不放松"，
   不是"什么都抛" —— 否则下一个人会把这条判据改回宽放。
5 非 dict（None / [] / 空串 / 0）→ 一律 {} 不抛（同上，头注承诺）。
6 ★ **反证有牙**：两条守卫换回静默 pass 后本门禁必须转红。
"""
import ast
import importlib.util
import io
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine.records import shapes  # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []
TOTAL = 0

from _check import bind_check  # noqa: E402  P0-1 断言助手单源
check = bind_check(globals(), "PASS", "FAIL", "FAILURES", total="TOTAL")

# 各调用点自己的措辞（ordered 的参数就是为"各调用点措辞不同"设计的）
WHO, WHERE = "A组", "roster.json"
SUBJECT, NOUN, HINT = "的键集与序声明对不上", "域", "按声明序核对一下"
KW = dict(who=WHO, subject=SUBJECT, noun=NOUN, hint=HINT)

TBL = {"3": "c", "1": "a", "2": "b"}


def _raised(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except ValueError as e:
        return str(e)
    return None


# -- 1 重复键声明 -------------------------------------------------
print("\n[1] 序声明有重复键 → ValueError（拒绝静默取首个）")
for order in [("1", "1", "2", "3"), ("1", "2", "2"), ("x", "x", "x", "x")]:
    msg = _raised(shapes.ordered, dict(TBL), order, WHERE, **KW)
    check("重复键 %s → ValueError" % (order,), msg is not None,
          "没抛 —— 声明写错却零报错")
    check("重复键 %s 文案点名「重复键」" % (order,), "重复键" in (msg or ""),
          "文案未点名: %r" % (msg,))
    check("重复键 %s 文案带调用方给的 who/where" % (order,),
          (WHO in (msg or "")) and (WHERE in (msg or "")), "文案丢了调用方措辞: %r" % (msg,))

# ★ 后果取证：若守卫被拆，同一个键会被声明两次（这正是要拒的形状）
dup_count = len({k: 1 for k in ("1", "1", "2", "3")})
check("★ 取证：重复声明里同一个键出现两次（这正是要拒的形状）",
      dup_count == 3 and ("1", "1", "2", "3").count("1") == 2, "取证失败，判据失去意义")

# -- 2 键集不齐 ----------------------------------------------------
print("\n[2] 域键集与声明不一致 → ValueError（点名两侧计数）")
for tbl, order, why in [
        (dict(TBL), ("1", "2", "9"), "声明多一个 9"),
        (dict(TBL), ("1", "2"), "声明少一个 3"),
        ({"1": "a"}, ("1", "2", "3"), "域里只有 1")]:
    msg = _raised(shapes.ordered, tbl, order, WHERE, **KW)
    check("%s → ValueError" % why, msg is not None,
          "没抛 —— 源改了、门面会静默改序")
    check("%s 文案带 who/where" % why, (WHO in (msg or "")) and (WHERE in (msg or "")),
          "文案: %r" % (msg,))
    check("%s 文案带调用方给的 noun" % why, NOUN in (msg or ""), "文案: %r" % (msg,))

msg = _raised(shapes.ordered, dict(TBL), ("1", "2", "9"), WHERE, **KW)
check("★ 文案给出「域缺 N / 声明缺 N」两个计数",
      ("域缺 1" in (msg or "")) and ("声明缺 1" in (msg or "")), "文案没给两侧计数: %r" % (msg,))
check("★ 文案点名未声明的那个键 9", "9" in (msg or ""), "文案: %r" % (msg,))

# -- 3 合法档逐字不变 ----------------------------------------------
print("\n[3] 合法档：按声明序重排，值逐个对应")
out = shapes.ordered(dict(TBL), ("2", "1", "3"), WHERE, **KW)
check("合法档按声明序返回", list(out) == ["2", "1", "3"], "序不对: %r" % (list(out),))
check("合法档值逐个对应", [out[k] for k in ("2", "1", "3")] == ["b", "a", "c"], "值错位: %r" % (out,))
check("合法档键集不变", set(out) == {"1", "2", "3"}, "键集变了: %r" % (out,))
check("合法档入参不被就地改", list(TBL) == ["3", "1", "2"], "入参被就地改了: %r" % (TBL,))

# -- 4 空表不抛（严格不放松）---------------------------------------
print("\n[4] ★ 空表 / 非 dict → {} 不抛（模块头注承诺，补判据不放松）")
for tbl, why in [({}, "空 dict"), (None, "None"), ([], "空 list"), ("", "空串"), (0, "0")]:
    try:
        r = shapes.ordered(tbl, (1, 2), WHERE, **KW)
        ok = r == {}
    except Exception as e:                                        # noqa: BLE001
        r, ok = "raised %r" % (e,), False
    check("%s → {} 不抛" % why, ok, "实得 %r" % (r,))
check("★ 非 dict 且给了坏 order 也不抛（先判表后判序）",
      shapes.ordered("x", (1, 1, 1), WHERE, **KW) == {}, "顺序守卫提前触发了")

# -- 5 反证有牙 ----------------------------------------------------
print("\n[5] ★ 反证：把两条 raise 换成 pass")
_SHAPES = os.path.join(ROOT, "saintess_engine", "records", "shapes.py")
MUT = os.path.join(ROOT, "_shapes_mut_tmp.py")
with io.open(_SHAPES, "r", encoding="utf-8", newline="") as f:
    ORIG = f.read()


def _mutate_both():
    """把 ordered 里那两条 raise 整块换成 pass（同缩进），写到 MUT。

    ★ 为什么整块而非逐行 replace：两条 raise 都是**跨行**的
    （raise ValueError( 换行 字符串 换行 % (...)），按行删会留下悬空表达式
    → IndentationError / SyntaxError ⇒ 反证自身崩掉 = 反证无效。
    ★ 也不就地改真仓再还原：中途崩掉会把变异态留在真仓（本车道踩过一次）。
    """
    lines = ORIG.splitlines(True)
    tree = ast.parse(ORIG)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "ordered")
    spans = sorted({(n.lineno, n.end_lineno) for n in ast.walk(fn)
                    if isinstance(n, ast.Raise) and n.end_lineno}, reverse=True)
    for a, b in spans:
        ind = lines[a - 1][:len(lines[a - 1]) - len(lines[a - 1].lstrip())]
        lines[a - 1:b] = [ind + "pass\n"]
    with io.open(MUT, "w", encoding="utf-8", newline="") as f:
        f.write("".join(lines))
    return len(spans)


n = _mutate_both()
check("反证：定位到 ordered 的两条 raise", n == 2, "定位到 %d 条" % n)

try:
    spec = importlib.util.spec_from_file_location("_shapes_mut", MUT)
    mut_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mut_mod)

    leaked_dup = False
    try:
        leaked_dup = isinstance(mut_mod.ordered(dict(TBL), ("1", "1", "2", "3"), WHERE, **KW), dict)
    except ValueError:
        leaked_dup = False
    check("★ 反证有牙：拆守卫后重复键不再抛（门禁能逮到）", leaked_dup,
          "拆了还照抛，说明判据钉不到这条")

    # ★ 实跑定性：拆掉键集守卫后不是"静默返回"，而是下游 {k: tbl[k]} 直接 KeyError
    #   （错因从"点名 who/where 的 ValueError"退化成"裸 KeyError，归属全丢"）。
    #   ⇒ 判据钉"不再抛带归属的 ValueError"，不是钉"一定静默"。
    miss_exc = None
    try:
        mut_mod.ordered(dict(TBL), ("1", "2", "9"), WHERE, **KW)
        miss_exc = None
    except ValueError:
        miss_exc = "valueerror"
    except KeyError as e:
        miss_exc = "keyerror:%r" % (e,)
    check("★ 反证有牙：拆守卫后键集不齐不再抛带归属的 ValueError",
          miss_exc != "valueerror", "拆了还照抛点名的 ValueError")
    check("★ 反证记录了退化形态（裸 KeyError，归属全丢）",
          (miss_exc or "").startswith("keyerror"), "实得 %r" % (miss_exc,))
finally:
    if os.path.exists(MUT):
        os.remove(MUT)

with io.open(_SHAPES, "r", encoding="utf-8", newline="") as f:
    check("★ 反证后真仓一字未动", f.read() == ORIG, "变异态残留在真仓")

diff = subprocess.run(["git", "diff", "--stat", "--", "saintess_engine/records/shapes.py"],
                      cwd=ROOT, capture_output=True, text=True,
                      encoding="utf-8", errors="replace")
check("★ 生产码零改动（git diff 对 shapes.py 为空）", not diff.stdout.strip(),
      "有改动: %r" % diff.stdout)

print("\n" + "=" * 60)
print("通过 %d · 失败 %d · 总检查 %d" % (PASS, FAIL, TOTAL))
for f in FAILURES:
    print("  ❌ " + f)
sys.exit(1 if FAIL else 0)
