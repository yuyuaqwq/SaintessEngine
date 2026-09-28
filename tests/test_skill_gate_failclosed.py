# -*- coding: utf-8 -*-
"""门禁：battle/actions 两个注入式门槛回执口的 fail-closed 守卫（此前一条零断言）。

跑法：python tests/test_skill_gate_failclosed.py（退出码 0 = 全绿）。

为什么要有这一支（批次 4 · 验证侧缺口 · **生产码零改动**）
--------------------------------------------------------
`extends/ext_combat/battle/actions.py` 的两个门槛回执规范化函数各带两条守卫。
本轮**逐条变异实跑**（把每条 raise 换成静默 pass）后跑 **56 支真门禁面**
（引擎 tests 的 battle/skill/neutral 族 + 包仓 battle/skill/passive/cmdflow 族）：

    守卫                              变异后 newly-red
    --------------------------------  -------------------------------
    :204 mp_gate_fn  形状守卫          test_engine_neutral_fallback  有牙
    :208 mp_gate_fn  空回执守卫        test_engine_neutral_fallback  有牙
    :239 skill_gate_fn 空回执守卫      test_passive_p5               有牙
    :235 skill_gate_fn **形状守卫**    **NONE（56 支面全绿）**        <-- 本门禁

只有 :235 那一条是**真缺口**。`mp_gate_fn` 有 `test_engine_neutral_fallback`
钉着（它两条断言恰好点名同款形状错），`skill_gate_fn` 那侧**一条都没有**
—— 两个 hook 逐字同款的守卫，只有 mp 那一半被钉住。

后果为什么值得钉
----------------
:235 守的是 `skill_gate_fn` 的回执**形状**。内容侧 hook 若返回一个既不是
`None`、也不是 str/序列的东西（最常见：把 bool / 数字 / dict 当"拦不拦"
的标志返回），守卫被拆时的**实测退化形态不是"静默返回"，而是**：

    UnboundLocalError: cannot access local variable 'out' where it is not
    associated with a value

—— `out` 只在 isinstance 两个分支里赋值，形状不对时直接读到未绑定的局部变量。
⇒ **点名归属全丢**：内容侧看到的是一个引擎内部变量名，
既不知道是自己哪个 hook 写错了，也拿不到「要 None 或非空 str/序列」这条契约。
这正是本批反复实测到的退化形态（点名异常 → 裸异常），**不假设它静默**。

★ 只加强：新增门禁，未改任何既有判据、未动任何冻结基线、生产码零改动。
"""
import ast
import io
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
for _p in (ROOT, os.path.join(ROOT, "extends")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from saintess_engine.config import EngineNotConfigured                 # noqa: E402
from ext_combat.battle.actions import (                              # noqa: E402
    _mp_gate_text, _use_gate_text, _skill_usable,
)
from saintess_engine import config as _cfg                            # noqa: E402

TARGET = os.path.join(ROOT, "extends", "ext_combat", "battle", "actions.py")
PY = os.environ.get("AFIX4_PY") or sys.executable
# ★ 防自举递归：本门禁的反证段会起子进程跑本文件；子进程必须带这个标记，
#   否则 A 起 B / B 起 A 无限递归（上一轮踩过：180s 超时且变异态留在真仓）。
_CHILD = "AFIX4_MUTANT_CHILD"

PASS = 0
FAIL = 0
FAILURES = []
TOTAL = 0

from _check import bind_check  # noqa: E402  P0-1 断言助手单源
check = bind_check(globals(), "PASS", "FAIL", "FAILURES", total="TOTAL")

_BATTLE = {"_key": 1}
_ACTOR = {"class_name": "x"}
_INFO = {"name": "s"}
_MUTATE = os.environ.get("AFIX4_MUTATE") == "1"


def _caught(fn, *a):
    """跑 fn，回 ('EngineNotConfigured', 文本) / ('<类名>', 文本) / (None, 返值)。"""
    try:
        return None, fn(*a)
    except EngineNotConfigured as e:
        return "EngineNotConfigured", str(e)
    except Exception as e:                                           # noqa: BLE001
        return type(e).__name__, str(e)


def _gate(returns):
    return lambda *a: returns


# ------------------------------------------------ 1. 形状守卫（核心缺口）
print("== 组 1 · _use_gate_text 形状守卫（零断言那条） ==")
# ★ 写这一支时我踩到并修掉的一处**自己的错**（产品码一字未改）：原先把
#   `{1, 2}` 当「形状错」，实测它**合法** —— isinstance 那一支收的是
#   (list, tuple, set, frozenset)，set 成员照样被转成 str 交出去。
#   判据改成钉「set 是合法面」而不是硬塞进坏形状组。
#   ★ set 本身**不是可判读形状**（无序）这一点是另一条议题（台账 L2057
#   已在 cues 侧把无序 set 从回执里请出去），battle 侧这四条守卫**没有**
#   那个口径 ⇒ 归一化层不属这两条守卫的职责，不在本门禁范围。
for _label, _bad in [("int", 3), ("float", 1.5), ("bool", True),
                     ("dict", {"a": 1}), ("bytes", b"x")]:
    _exc, _msg = _caught(_use_gate_text, _gate(_bad), _BATTLE, _ACTOR, _INFO)
    check("形状错 %s ⇒ 抛点名 EngineNotConfigured" % _label,
          _exc == "EngineNotConfigured", "拿到 %s: %s" % (_exc, _msg[:70]))
    check("  · 文案点名 hook 名 skill_gate_fn", "skill_gate_fn" in (_msg or ""),
          "文案缺 hook 名: %s" % (_msg or "")[:70])

_exc, _msg = _caught(_use_gate_text, _gate(object()), _BATTLE, _ACTOR, _INFO)
check("形状错 任意对象 ⇒ 点名且带类型名",
      _exc == "EngineNotConfigured" and "object" in (_msg or ""),
      "拿到 %s: %s" % (_exc, (_msg or "")[:70]))

# ★ 端到端：这条守卫是 _skill_usable 那一段的唯一出口，端到端也要钉
_saved = _cfg._HOOKS.get("skill_gate_fn")
try:
    _cfg._HOOKS["skill_gate_fn"] = _gate(3)
    _exc, _msg = _caught(_skill_usable, _BATTLE, _ACTOR, _INFO, [])
    check("端到端 · hook 形状错 ⇒ 点名 EngineNotConfigured",
          _exc == "EngineNotConfigured", "拿到 %s: %s" % (_exc, str(_msg)[:70]))
finally:
    _cfg._HOOKS["skill_gate_fn"] = _saved


# --------------------------------- 2. 空回执守卫（同款，防回退时被拆）
print("== 组 2 · 空回执守卫 ==")
for _label, _bad in [("空串", ""), ("空列表", []), ("全被挑空的列表", [None, ""]),
                     ("空集合", set())]:
    _exc, _msg = _caught(_use_gate_text, _gate(_bad), _BATTLE, _ACTOR, _INFO)
    check("空回执 %s ⇒ 抛点名 EngineNotConfigured" % _label,
          _exc == "EngineNotConfigured", "拿到 %s: %s" % (_exc, str(_msg)[:70]))


# --------------------------------- 3. 合法面逐字不变（钉「不放松」而非「都抛」）
print("== 组 3 · 合法面逐字不变 ==")
for _label, _got, _want in [
    ("None 放行 ⇒ []", None, []),
    ("非空 str 原样", "血线不足", ["血线不足"]),
    ("非空 list 原样", ["甲", "乙"], ["甲", "乙"]),
    ("tuple 原样", ("甲", "乙"), ["甲", "乙"]),
    ("序列挑掉 None 与空串", ["甲", None, "", "乙"], ["甲", "乙"]),
    ("序列成员转 str", [7, 8], ["7", "8"]),
    ("set 成员转 str（本实现收 set·实测合法）", {1, 2}, ["1", "2"]),
]:
    _exc, _out = _caught(_use_gate_text, _gate(_got), _BATTLE, _ACTOR, _INFO)
    check("合法面 %s" % _label, _exc is None and _out == _want,
          "拿到 %s %r（期望 %r）" % (_exc, _out, _want))


# ------------------------- 4. mp 侧逐字同款（两 hook 同款，一起钉）
print("== 组 4 · mp_gate_fn 同款 ==")
for _label, _bad in [("int", 3), ("bool", True), ("dict", {"a": 1}), ("空串", "")]:
    _exc, _msg = _caught(_mp_gate_text, _gate(_bad), _BATTLE, _ACTOR, _INFO, 5)
    check("mp 形状或空回执 %s ⇒ 点名" % _label, _exc == "EngineNotConfigured",
          "拿到 %s: %s" % (_exc, str(_msg)[:70]))
    check("  · 文案点名 hook 名 mp_gate_fn", "mp_gate_fn" in (_msg or ""),
          "文案缺 hook 名: %s" % (_msg or "")[:70])
_exc, _out = _caught(_mp_gate_text, _gate("蓝量不足"), _BATTLE, _ACTOR, _INFO, 5)
check("mp 合法面 非空 str 原样", _exc is None and _out == ["蓝量不足"],
      "拿到 %s %r" % (_exc, _out))


# --------------------------------- 5. 源码面结构（钉 raise 还在，不钉文案）
print("== 组 5 · 源码面结构 ==")
with io.open(TARGET, encoding="utf-8", newline="") as _f:
    _src = _f.read()
_tree = ast.parse(_src)


def _guards(fn_name):
    _fn = next(n for n in _tree.body
               if isinstance(n, ast.FunctionDef) and n.name == fn_name)
    return [ast.get_source_segment(_src, n) or ""
            for n in ast.walk(_fn) if isinstance(n, ast.Raise)]


for _fn_name, _hook in [("_use_gate_text", "skill_gate_fn"),
                        ("_mp_gate_text", "mp_gate_fn")]:
    _gs = _guards(_fn_name)
    check("%s 有两条 raise" % _fn_name, len(_gs) == 2, "实到 %d 条" % len(_gs))
    check("  · 两条都点名 %s" % _hook, all(_hook in _g for _g in _gs),
          "实到 %r" % _gs)

# ★ 判据钉「raise 没了」而不是「那句文案没了」——同一句在 docstring 里也出现过一次
check("源码面 · 形状守卫文案只出现在两处 raise 上",
      _src.count("回执形状不对") == 2, "实到 %d 次" % _src.count("回执形状不对"))


# --------------------------------- 6. 有牙反证（★ 改真仓实跑）
print("== 组 6 · 有牙反证 ==")
if _MUTATE:
    # 被外部脚本以变异态起：只记录退化形态，不做自举反证
    _exc, _msg = _caught(_use_gate_text, _gate(3), _BATTLE, _ACTOR, _INFO)
    check("变异态 · 退化形态被记录（点名异常消失即判红）",
          _exc == "UnboundLocalError" and "out" in (_msg or ""),
          "实测退化形态 = %s（判据按此写死）" % _exc)
    check("变异态 · mp 侧同款守卫仍点名（未被连带拆掉）",
          _caught(_mp_gate_text, _gate(3), _BATTLE, _ACTOR, _INFO, 5)[0]
          == "EngineNotConfigured", "mp 侧也被拆了？")
else:
    with io.open(TARGET, encoding="utf-8", newline="") as _f:
        _orig = _f.read()
    _lines = _orig.splitlines(keepends=True)
    _i = next(k for k, l in enumerate(_lines)
              if "skill_gate_fn 的回执形状不对" in l)
    while "raise " not in _lines[_i]:
        _i -= 1
    _depth, _j, _started = 0, _i, False
    while _j < len(_lines):
        _depth += _lines[_j].count("(") - _lines[_j].count(")")
        if "(" in _lines[_j]:
            _started = True
        if _started and _depth == 0:
            break
        _j += 1
    _ind = _lines[_i][:len(_lines[_i]) - len(_lines[_i].lstrip())]
    _mut = list(_lines)
    for _k in range(_i, _j + 1):
        _mut[_k] = ""
    _mut.insert(_i, _ind + "pass  # MUTATED" + chr(10))
    try:
        with io.open(TARGET, "w", encoding="utf-8", newline="") as _f:
            _f.write("".join(_mut))
        _comp = subprocess.run([PY, "-m", "py_compile", TARGET],
                               capture_output=True)
        if _comp.returncode != 0:
            check("反证 · 变异态语法可编译", False,
                  "py_compile 失败: " + _comp.stderr.decode("utf-8", "replace")[-120:])
        else:
            _e = dict(os.environ)
            _e["AFIX4_MUTATE"] = "1"
            _e[_CHILD] = "1"
            # ★ cwd=ROOT：子进程必须在本仓跑，否则它反算出的是另一棵树，
            #   会读着变异态全绿，判据「看着有牙、实则无牙」
            _r = subprocess.run([PY, __file__], cwd=ROOT, env=_e,
                                capture_output=True)
            _out = (_r.stdout + _r.stderr).decode("utf-8", "replace")
            check("反证 · 拆掉形状守卫后本门禁转红（rc=1）", _r.returncode == 1,
                  "rc=%d" % _r.returncode)
            check("  · 报红原文逐字是退化形态那条", "UnboundLocalError" in _out,
                  "子进程尾行: %s" % _out[-160:].replace(chr(10), " | "))
            check("  · 合法面组仍跑过（判据没被整体放宽）", "合法面" in _out,
                  "子进程输出里没有合法面组")
    finally:
        with io.open(TARGET, "w", encoding="utf-8", newline="") as _f:
            _f.write(_orig)
        # ★ 超时或 kill 之后第一件事是回读真仓，别假设脚本自己还原了
        with io.open(TARGET, encoding="utf-8", newline="") as _f:
            check("反证 · 真仓已逐字还原", _f.read() == _orig, "真仓与还原内容不一致")

print(chr(10) + "== 结果：通过 %d / 共 %d ==" % (PASS, TOTAL))
if FAIL:
    print("失败：")
    for _f in FAILURES:
        print("  x " + _f)
    sys.exit(1)
print("全绿 OK")
