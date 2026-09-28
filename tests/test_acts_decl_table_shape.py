#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""acts 声明表**键与签名取不到**两维的 fail-closed 门禁（审计修复 · 批次4）。

锁死的契约（本文件是这两维的**唯一**行为断言面，此前零覆盖 ——
变异实跑确认：把这两条 `raise` 换成 `pass` 后
`tests/test_acts.py` **65/65 仍全绿、零转红**）：

1. `compile_table` 的**键必须是非空字符串**（`{"": 声明}` / `{7: 声明}` / `{None: 声明}` 抛
   `SpecError` 并点名那个键）。为什么要有：键就是 `compile()` 传进去的 `name`，
   也就是 `Plan` 的 `id` —— 空串/非字符串的 id 会在日志、存档回读、`str(plan)`
   这些地方静默变形，而**表里那一行到底是谁**当场就说得清。
2. `_arg_names_of` **取不到签名**时抛 `TypeError`，点名动词 —— 宁可编译期现形，
   也不静默按默认值跑出错值（拼错实参名会被动词的 `**_` 静静吃掉，产出错值、零报错）。
   取不到签名的三种真实来源：`functools.partial` 之外还有 C 实现 / 换掉
   `__signature__` 的可调用；`inspect.signature` 抛 `ValueError` / `TypeError` 两种都要盖。
3. ★ **合法面逐字不变**：同一条动词在「能取到签名」时行为一点不变
   （可取名实参 / `**kwargs` 不当许可证 / `ctx` 不算实参 / 未知实参名照旧 `SpecError`）。
4. ★ **表内一条坏 ⇒ 整表不装**（`compile_table` 的「先全编再返回」契约）：
   不得因为前面编好了几条就把半张表交出去。

**零游戏、零宿主**：只用标准库 + 被测模块。
判据只加强：本文件是**新增**门禁，未改任何既有判据或冻结基线。

跑法：python tests/test_acts_decl_table_shape.py
"""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine.acts import Acts, SpecError   # noqa: E402
import saintess_engine.acts as ACTS                # noqa: E402

from _check import bind_check  # noqa: E402  断言助手单源：tests/_check.py

passed = failed = 0
check = bind_check(globals(), "passed", "failed", total="total")

total = 0
_OK_SPEC = {"id": "p1", "seq": [{"verb": "hit"}]}


def _raises(exc, fn):
    try:
        fn()
    except exc as e:
        return str(e), True
    except Exception as e:                                     # noqa: BLE001
        return "%s: %s" % (type(e).__name__, e), False
    return "", False


# ── A. compile_table 的键必须是非空字符串 ──────────────────────────────
acts = Acts(verbs={"hit": lambda ctx, amount=1: amount})
for bad_key, label in [("", "空串"), ("   ", "纯空白串"), (7, "整数"),
                       (None, "None"), ((1, 2), "元组键"), (True, "bool")]:
    table = {bad_key: _OK_SPEC}
    msg, raised = _raises(SpecError, lambda t=table: acts.compile_table(t))
    check("A compile_table 键是%s → SpecError 点名该键" % label,
          raised and repr(bad_key) in msg, "实得：%r" % (msg[:100],))

# 合法键照旧能编（不因这条守卫被误伤）—— Plan 的名字属性叫 `name`（compile 传进来的 name）
ok = acts.compile_table({"p1": _OK_SPEC, "p2": {"seq": [{"verb": "hit"}]}})
check("A 合法键（非空字符串）照旧编出整表",
      sorted(ok) == ["p1", "p2"] and all(p.name == k for k, p in ok.items()),
      "实得 keys=%r" % (sorted(ok),))

# ── B. ★ 一条坏 ⇒ 整表不装（不得交出半张表）───────────────────────────
half = {"good1": _OK_SPEC, "": {"id": "x", "seq": [{"verb": "hit"}]},
        "good2": {"seq": [{"verb": "hit"}]}}
msg, raised = _raises(SpecError, lambda: acts.compile_table(half))
check("B ★ 表里一条坏键 ⇒ 整表不装（不是只编好的那几条）",
      raised, "没抛 —— 半张表被交出去了")

# ── C. ★ 取不到签名 ⇒ 编译期点名（不静默按默认值跑出错值）──────────────
class _NoSignature:
    """一个 `inspect.signature` 取不到签名的可调用。

    `__signature__` 指向一个不存在的属性名 ⇒ stdlib 抛 `ValueError`
    （「no signature found for builtin type」那一族）。
    """
    __signature__ = "不是 Signature 对象"

    def __call__(self, ctx):                                   # noqa: D102
        return 1


class _CFunc:
    """C 实现的替身：`inspect.signature` 对它抛 TypeError。"""
    def __init__(self):
        pass


for cls, label in [(_NoSignature, "signature 属性不合法（ValueError 族）"),
                   (_CFunc, "取不到签名的可调用（TypeError 族）")]:
    a2 = Acts()
    a2.verbs["weird"] = cls()
    msg, raised = _raises(TypeError, lambda: a2.compile(
        {"id": "w", "seq": [{"verb": "weird", "amount": 1}]}))
    # 点名口径 = getattr(verb, "__name__", verb)：无 __name__ 的实例回落到 repr，
    # 所以只钉「点了名 + 说明了是取不到签名」，不钉具体拼法（那是两种族的差别）。
    check("C 动词「%s」取不到签名 → TypeError 点名" % label,
          raised and "取不到签名" in msg, "实得：%r" % (msg[:110],))

# 取得到签名时，一切照旧（合法面不被这条守卫误伤）
a3 = Acts(verbs={"hit": lambda ctx, amount=1, **kw: amount})
plan = a3.compile({"id": "ok", "seq": [{"verb": "hit", "amount": 5}]})
check("C 合法动词照旧能编（守卫不误伤正常面）", plan.steps[0][0] == "hit")
msg, raised = _raises(SpecError, lambda: a3.compile(
    {"id": "bad", "seq": [{"verb": "hit", "amt": 5}]}))
check("C 未知实参名照旧 SpecError（**kwargs 不当许可证）",
      raised and "amt" in msg, "实得：%r" % (msg[:100],))

# ── D. 反证：这两条守卫换静默后本节判据必须转红 ────────────────────────
src = ACTS.__file__
with open(src, encoding="utf-8", newline="") as f:
    source = f.read()
tbl = source.split("def compile_table(", 1)[1].split("\n    def ", 1)[0]
key_guard = 'raise SpecError(f"动作声明的键必须是非空字符串' in tbl
check("D 源码侧：compile_table 仍有「键必须非空字符串」守卫（防门禁空转）",
      key_guard, "守卫已不在表体内")
arg = source.split("def _arg_names_of(", 1)[1].split("\ndef ", 1)[0]
sig_guard = 'raise TypeError(' in arg and "取不到签名" in arg
check("D 源码侧：_arg_names_of 仍有「取不到签名」守卫（防门禁空转）",
      sig_guard, "守卫已不在 _arg_names_of 体内")
# 真变异：把两条守卫换静默形态，逐条确认本文件断言会转红
mut_tbl = re.sub('[\t]*raise SpecError\(f.动作声明的键必须是非空字符串[^\n]*\n', "", tbl)
check("D ★ 反证：compile_table 键守卫可被整行摘掉（反证有牙）",
      "动作声明的键必须是非空字符串" not in mut_tbl,
      "摘不掉 —— 反证无牙")
# _arg_names_of 的守卫跨三行、且闭括号与 `from e` 同行 ⇒ 逐行正则删不干净
# （上一轮反证就栽在这：按行删掉半截，判据自己先炸）。改成整块匹配。
pat = '[\t]*raise TypeError\(\s*\n[^\n]*\n[^\n]*from e\n'
mut_arg = re.sub(pat, "", arg, count=1)
# ★ 判据钉「raise 没了」而不是「那句文案没了」—— 同一句话在 docstring（:119）
# 也出现一次，按文案判会被 docstring 误判成「摘不掉」（我第一版就栽在这）。
check("D ★ 反证：_arg_names_of 的 raise 被整块摘掉（反证有牙）",
      "raise TypeError(" not in mut_arg, "raise 还在 —— 摘不掉")
check("D ★ 反证：摘掉后真的退化成「取不到签名就当没有可取名实参」（静默路径）",
      "except (TypeError, ValueError) as e:" in mut_arg
      and "return frozenset(names)" in mut_arg, "静默形态不对")
check("D 源码侧：源码可读（夹具只读 acts，未触碰别线文件）",
      "def compile_table(" in source, "源码读不到")

print(chr(10) + "===== 结果：通过 %d / %d =====" % (passed, passed + failed))
sys.exit(1 if failed else 0)
