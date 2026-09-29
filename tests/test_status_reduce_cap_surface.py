# -*- coding: utf-8 -*-
"""状态减伤 cap 已下沉 FORMULA_SKELETON（同族未收口门禁，承 L246/L566/L248/crit 六批先例）。

背景（本项是该族的**第 7 次**命中）
------------------------------------------------------------------------------------
`battle/stats.py::_apply_effects` 里**两个** `min(..., 0.9)` 落点一直写死字面量：

  · 叠层累加型：`st["reduce"] = min(已累加 + n*per, 0.9)`（stat_scale.reduce）
  · 单条快照型：`st[stat] = int(st[stat] * (1.0 - min(mult, 0.9)))`（panel.op=reduce）

它们是**玩家可见的平衡数值**（决定「一堆减益叠满最多能减掉几成」），而内容侧**零配置面**：
两个读点在 orlandia / aetheran-package 全仓**零命中** ⇒ 第二款游戏想改自己的上限**只能改引擎**。
同族的 block / dodge / taken_resist / taken_elem_resist / defend_posture / crit 六个 cap
**早已下沉**到这张表，唯独 stats 这两个漏在原地 —— 一次收口只覆盖被点名的那个落点，
邻支不会顺带修掉（★ 该角度的命中率已连续 7 轮命中，上一轮已报给主线）。

★★ **为什么不复用 reduce.cap（V4 已迁、默认值 0.0）**：那条封的是**承伤侧累加的
taken_pct 声明值**（landing._taken_pct_total，读点 :500），这里封的是**面板折算里
减益状态能减掉几成**（stats._apply_effects）—— 两个消费者、两条平衡线、中性地值也不同
（那边 0.0 = 不减伤 / 这边 0.0 = 状态不再减伤）⇒ 另起 status_reduce 组，
**D4 专门钉这一点**（钉住两者不被绑成一条）。

本测试钉六件事（**缺一即红**）
--------------------------------
A. 中性默认值 = 原写死值 0.90（未装配）⇒ 迁移不改行为的正证。
B. 注入面真的通：装上 formula_skeleton_fn 改挂载值 ⇒ getter 跟着变（不是假 getter）。
C. **回落只认 None**（内容侧可把 cap 关到 0.0 = 状态不再减伤，钉「0 合法」）。
D. 读点已收口：**两处**都走 getter，真代码行里不再有写死的 0.9；组不被 reduce.cap 冒名。
E. **黑盒端到端**：stats._apply_effects 真跑 —— 未装配时累加仍封 0.90（逐字不变）；
   声明 0.5 后同一输入封 0.5 ⇒ 注入面真的进了计算。
F. 反证锚点：getter 改回字面量 / 任一读点改回硬编码 / 复用 reduce.cap ⇒ 必红。

跑法：python tests/test_status_reduce_cap_surface.py
"""
import ast
import copy
import io
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, FW_ROOT)
sys.path.insert(0, os.path.join(FW_ROOT, "extends"))

from saintess_engine import config as _cfg                       # noqa: E402
from extends.ext_combat.battle import formulas as F              # noqa: E402
from extends.ext_combat.battle import stats as S                  # noqa: E402
import extends.ext_combat.battle.state_effects as _se            # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []

FORMULAS = os.path.join(FW_ROOT, "extends", "ext_combat", "battle", "formulas.py")
STATS = os.path.join(FW_ROOT, "extends", "ext_combat", "battle", "stats.py")


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % label)
    else:
        FAIL += 1
        FAILURES.append(label)
        print("  [FAIL] %s %s" % (label, extra))


def _unmount():
    try:
        _cfg.set_hook("formula_skeleton_fn", None)
    except Exception:
        pass


def _mount(skel):
    data = copy.deepcopy(F._NEUTRAL_SKELETON)
    for k, v in (skel or {}).items():
        if isinstance(v, dict) and isinstance(data.get(k), dict):
            data[k].update(v)
        else:
            data[k] = v
    _cfg.set_hook("formula_skeleton_fn", lambda: data)
    return data

_SE_ORIG = _se.state_def


def _run_accumulate(per, stacks):
    """黑盒：叠层累加型读点。返回 st 里的 reduce 值。"""
    st = {}

    def fake(key):
        if key != "k":
            return {}
        return {"stat_scale": {"reduce": per}}

    def go():
        S._apply_effects(st, {"effects": {"k": {"stacks": stacks}}})
        return st.get("reduce")

    _se.state_def = fake
    try:
        return go()
    finally:
        _se.state_def = _SE_ORIG


def _run_single(mult, stat="atk", base=1000):
    """黑盒：单条快照型读点。返回 st[stat]。"""
    st = {stat: base}

    def fake(key):
        if key != "p":
            return {}
        return {"panel": {"stat": stat, "op": "reduce", "mult": mult}}

    def go():
        S._apply_effects(st, {"effects": {"p": {"stat": stat, "op": "reduce", "mult": mult}}})
        return st.get(stat)

    _se.state_def = fake
    try:
        return go()
    finally:
        _se.state_def = _SE_ORIG


print("== A. 中性默认值 = 原写死值 0.90（未装配 ⇒ 与改前逐字一致） ==")
_unmount()
check("A1 未装配时 status_reduce_cap() == 0.90（原字面量）",
      F.status_reduce_cap() == 0.90, F.status_reduce_cap())
check("A2 中性骨架表里 status_reduce.cap 已声明且为 0.90",
      F._NEUTRAL_SKELETON.get("status_reduce", {}).get("cap") == 0.90,
      F._NEUTRAL_SKELETON.get("status_reduce"))

print("== B. 注入面真的通（防假 getter） ==")
_mount({"status_reduce": {"cap": 0.5}})
check("B1 声明 status_reduce.cap=0.5 ⇒ getter 返回 0.5", F.status_reduce_cap() == 0.5,
      F.status_reduce_cap())
_mount({"status_reduce": {"cap": 0.25}})
check("B2 换成 0.25 ⇒ getter 跟着变", F.status_reduce_cap() == 0.25, F.status_reduce_cap())
_mount({"status_reduce": {}})
check("B3 status_reduce 组缺 cap 键 ⇒ 回落 0.90（不 KeyError）",
      F.status_reduce_cap() == 0.90, F.status_reduce_cap())

print("== C. 回落只认 None（0 是合法值：状态不再减伤） ==")
_mount({"status_reduce": {"cap": 0.0}})
check("C1 声明 0.0 ⇒ getter 返回 0.0（不被吞成 0.90）", F.status_reduce_cap() == 0.0,
      F.status_reduce_cap())
_mount({"status_reduce": {"cap": None}})
check("C2 声明 None ⇒ 回落 0.90", F.status_reduce_cap() == 0.90, F.status_reduce_cap())
_unmount()
check("C3 回落后仍是 0.90", F.status_reduce_cap() == 0.90, F.status_reduce_cap())

print("== D. 读点已收口：两处都走 getter，真代码行无写死 0.9 ==")
_st_src = io.open(STATS, encoding="utf-8").read()
_st_tree = ast.parse(_st_src)
# ★ 用 AST 找 Call / Constant 节点，不靠「剔掉字符串字面量所在行」那招 ——
#   键名 reduce 本身就是字符串字面量，按行剔会自剔成空集 ⇒ 空集上「无残留」恒绿。
_f_cap_calls = []
_hard09 = []
for _n in ast.walk(_st_tree):
    if isinstance(_n, ast.Call) and isinstance(_n.func, ast.Name) and _n.func.id == "_cap":
        _f_cap_calls.append(_n.lineno)
    if isinstance(_n, ast.Constant) and isinstance(_n.value, float) and _n.value == 0.9:
        _hard09.append(_n.lineno)
check("D1 stats.py 恰好两处调 _cap（两族两读点，不许只收一处）",
      len(_f_cap_calls) == 2, sorted(_f_cap_calls))
check("D2 stats.py 真代码里不再有写死浮点 0.9（注释/docstring 不算）",
      not _hard09, sorted(_hard09))
# ★ 本轮实测踩出来的第二个坑（第一版用**模块级** `from .formulas import ...`，直接打红
#   tests/test_editor_glossary.py）：stats.py 会被 spec_from_file_location **单文件装载**
#   （该判据直接取 stats._monster_base_stats 的键集），模块级相对 import 没有父包
#   ⇒ ImportError ⇒ 135 个文件里 4 个红。故 getter 必须走**函数内惰性 import**。
#   这条把那个坑钉成常驻判据（★ 判据只加强）。
check("D5 stats.py 不得有模块级 from .formulas import（会被单文件装载打 ImportError）",
      not any(isinstance(n, (ast.Import, ast.ImportFrom))
              and getattr(n, "module", None) and str(n.module).startswith("formulas")
              and any(isinstance(a, ast.ImportFrom) and a.level > 0 for a in
                      [n] if isinstance(n, ast.ImportFrom))
              for n in _st_tree.body), "模块级相对 import 回来了")
_f_src = io.open(FORMULAS, encoding="utf-8").read()
_f_tree = ast.parse(_f_src)
_fc = [n.lineno for n in ast.walk(_f_tree)
       if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_skel_sub_num"
       and any(isinstance(a, ast.Constant) and a.value == "status_reduce" for a in n.args)]
check("D3 getter 真读 status_reduce 组（防假 getter / 防串到别的组）", len(_fc) == 1, _fc)
check("D4 status_reduce 组与 reduce 组是两个独立键（别绑成一条平衡线）",
      F._NEUTRAL_SKELETON.get("status_reduce") is not None
      and F._NEUTRAL_SKELETON.get("reduce", {}).get("cap") == 0.0,
      (F._NEUTRAL_SKELETON.get("status_reduce"), F._NEUTRAL_SKELETON.get("reduce")))

print("== E. 黑盒端到端：stats._apply_effects 真跑 ==")
_unmount()
check("E1 累加型 50层x0.05=2.50 ⇒ 仍封 0.90（与改前逐字相同）",
      abs(_run_accumulate(0.05, 50) - 0.90) < 1e-9, _run_accumulate(0.05, 50))
# ★ 期望值取**改前的实跑事实**（1000 → 99），不是"好看"的 100：
#   1.0 - 0.9 = 0.09999999999999998（浮点）⇒ int 截断后是 99。
#   本条同时钉住「改前字面量 0.9 与改后 getter 回落 0.90 算得同一个数」——
#   写 100 会把一条**行为零变化**的迁移误判成回归（第一版就栽在这，如实记）。
check("E2 单条型 mult=0.99 ⇒ 封 0.90（1000 → 99，与改前逐字相同）",
      _run_single(0.99) == int(1000 * (1.0 - 0.9)) == 99, _run_single(0.99))
check("E3 单条型 mult=0.30 不触 cap ⇒ 1000 → 700（合法路径未被动过）",
      _run_single(0.30) == 700, _run_single(0.30))
_mount({"status_reduce": {"cap": 0.5}})
check("E4 声明 cap=0.5 ⇒ 累加型封 0.5（注入面真的进了计算）",
      abs(_run_accumulate(0.05, 50) - 0.5) < 1e-9, _run_accumulate(0.05, 50))
check("E5 声明 cap=0.5 ⇒ 单条型 mult=0.99 封 0.5（1000 → 500）",
      _run_single(0.99) == 500, _run_single(0.99))
_mount({"status_reduce": {"cap": 0.0}})
check("E6 声明 cap=0.0 ⇒ 减益状态不再减伤（1000 → 1000，0 是合法值不是缺键）",
      _run_single(0.99) == 1000, _run_single(0.99))
_unmount()

print("== F. 反证锚点（getter / 读点被改回硬编码 ⇒ 必红） ==")
check("F1 源码里 getter 名为 status_reduce_cap（防悄悄改名绕过判据）",
      "def status_reduce_cap(" in _f_src, "getter 名变了")
check("F2 stats.py 两处读点都写着 _cap(（防只改一处）",
      _st_src.count("_cap(") >= 2, _st_src.count("_cap("))
_old1 = 'float(per),' + chr(10) + '                                        0.9)'
_old2 = 'min(float(entry_mult), 0.9)'
check("F3 原两处 0.9 写法在 stats.py 里已消失（字符串形态也钉）",
      _old2 not in _st_src and "n * float(per), 0.9)" not in _st_src, "原写法还在")

print("")
print("========================================")
print("PASS: %d   FAIL: %d" % (PASS, FAIL))
if FAILURES:
    for f in FAILURES:
        print("  ! %s" % f)
    sys.exit(1)
print("状态减伤 cap 下沉门禁全绿")
