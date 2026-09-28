# -*- coding: utf-8 -*-
"""承伤侧物免/魔免 cap 已下沉 FORMULA_SKELETON（同族未收口门禁，承 L566 / L246 两次先例）。

背景（Step 0p：台账点了 1 处、同形态另有其人；本项已是该族的**第 4 次**命中）
------------------------------------------------------------------------------------
landing._apply_taken_reductions 里**三个 cap**，前两个早已下沉到内容侧骨架表：

  · 格挡概率上限 / 命中减免 → formulas.block_cap() / block_reduce()（V4 批迁）
  · 闪避上限                → formulas.dodge_cap()（2026-09-25 审计 E2 迁）

唯独**物免 / 魔免的 cap 仍是硬编码 0.4**（min(phys_reduce, 0.4) / min(magic_reduce, 0.4)
两处）。它是**玩家可见的平衡数值**：决定「物抗词条叠满最多能减掉几成伤害」，而内容侧
当时零配置面 —— 第二款游戏想改自己的减伤上限只能改引擎。奥兰迪亚自己的数据里
phys_reduce / magic_reduce 都真实在用（affixes.json / races.json / monster_roster.json /
instances.json），即这是**真实生效**的读点，不是死码。

修法 = 下沉到**既有** formula_skeleton_fn 注入面（承 V4 / E2 / L246 / L566 四批先例），
**不新开第二张表 / 第二套注入面**；默认值取原写死值 0.40 ⇒ 与已装内容**逐字一致**、
玩家可见行为零变化。★ 默认值**不在「零效应中性段」**：cap 归 0 = 减伤整条失效
（是另一个平衡选择，不是「没有」）。

本测试钉六件事（**缺一即红**）
--------------------------------
A. 中性默认值 = 原写死值 0.40（未装配）⇒ 迁移不改行为的正证。
B. 注入面真的通：装上 formula_skeleton_fn 改挂载值 ⇒ getter 跟着变（不是假 getter）。
C. **回落只认 None**（内容侧可把 cap 关到 0.0 = 减伤整条关掉，钉「0 合法」）。
D. 读点已收口：两条**真代码行**里不再有写死的 0.4 封顶（注释/docstring 不算）。
E. **黑盒端到端**：_apply_taken_reductions 真跑一格，声明 cap 变了 ⇒ 减伤率跟着变；
   未声明时 0.41 与 0.90 **同值**（旧硬编码的封顶形态保留）。
F. 反证锚点：getter 改回字面量 / 读点改回硬编码 ⇒ 必红（防「门禁空转恒绿」）。

跑法：python tests/test_taken_resist_cap_surface.py
"""
import ast
import io
import os
import random
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, FW_ROOT)
sys.path.insert(0, os.path.join(FW_ROOT, "extends"))

from saintess_engine import config as _cfg                       # noqa: E402
from extends.ext_combat.battle import formulas as F              # noqa: E402
from extends.ext_combat.battle import landing as L               # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % label)
    else:
        FAIL += 1
        FAILURES.append(label)
        print("  [FAIL] %s %s" % (label, extra))


LANDING = os.path.join(FW_ROOT, "extends", "ext_combat", "battle", "landing.py")
FORMULAS = os.path.join(FW_ROOT, "extends", "ext_combat", "battle", "formulas.py")


def _unmount():
    try:
        if hasattr(_cfg, "set_hook"):
            _cfg.set_hook("formula_skeleton_fn", None)
    except Exception:
        pass


def _mount(sk):
    def _fn():
        return dict(sk)
    try:
        if hasattr(_cfg, "set_hook"):
            _cfg.set_hook("formula_skeleton_fn", _fn)
    except Exception as _e:
        print("  [WARN] set_hook 不可用：%r" % _e)


class _B(object):
    """只带 btype 的极简战斗壳（本函数不读别的字段；cue 未装配只走诊断不抛）。"""
    btype = "monster"

    def __init__(self):
        self.log = []


def _real(kind, pct, dmg=1000):
    tgt = {"name": "T", "hp": 1000000, "max_hp": 1000000, "level": 1,
           "phys_reduce": pct, "magic_reduce": pct}
    random.seed(0)
    return L._apply_taken_reductions(_B(), tgt, dmg, kind, [])


_unmount()
print("== A. 中性默认值 = 原写死值 0.40（未装配 ⇒ 玩家可见行为零变化）==")
check("taken_resist_cap() = 0.40（原写死）", F.taken_resist_cap() == 0.40,
      "got=%r" % F.taken_resist_cap())
check("未装配时 _NEUTRAL_SKELETON 声明 taken_resist.cap",
      F._NEUTRAL_SKELETON.get("taken_resist", {}).get("cap") == 0.40,
      "got=%r" % (F._NEUTRAL_SKELETON.get("taken_resist"),))

print("== B. 注入面真的通（内容侧可覆盖；防假 getter）==")
_sk = {"taken_resist": {"cap": 0.55}}
_mount(_sk)
check("挂载 cap=0.55 ⇒ getter 返 0.55", F.taken_resist_cap() == 0.55,
      "got=%r" % F.taken_resist_cap())

print("== C. 回落只认 None（内容侧可把减伤整条关掉：cap=0.0 合法）==")
_sk["taken_resist"]["cap"] = 0.0
check("内容侧声明 0.0 ⇒ getter 返 0.0（不被 or 吞成默认）",
      F.taken_resist_cap() == 0.0, "got=%r" % F.taken_resist_cap())


print("== E. 黑盒端到端：_apply_taken_reductions 真跑，cap 改 ⇒ 减伤率跟着改 ==")
_unmount()
check("未装配：cap 之上（0.41）按 0.40 封顶 ⇒ 实扣 600",
      _real("phys", 0.41) == 600, "got=%r" % _real("phys", 0.41))
check("未装配：0.90 与 0.41 同值（旧硬编码的封顶形态保留）",
      _real("phys", 0.90) == _real("phys", 0.41),
      "got=%r vs %r" % (_real("phys", 0.90), _real("phys", 0.41)))
check("未装配：cap 之下（0.10）不封顶 ⇒ 实扣 900",
      _real("phys", 0.10) == 900, "got=%r" % _real("phys", 0.10))
check("未装配：魔免段同口径（0.90 → 600）", _real("magi", 0.90) == 600,
      "got=%r" % _real("magi", 0.90))
check("未装配：真伤不吃免伤（kind 含 true ⇒ 1000 全额）",
      _real("phys_true", 0.90) == 1000, "got=%r" % _real("phys_true", 0.90))

_mount({"taken_resist": {"cap": 0.55}})
check("★ 内容侧声明 cap=0.55 ⇒ 0.90 的物抗只减 55%（实扣 450）—— 旧硬编码给 600",
      _real("phys", 0.90) == 450, "got=%r" % _real("phys", 0.90))
check("注入 cap=0.55 后 cap 之下不受影响（0.10 仍减 10%）",
      _real("phys", 0.10) == 900, "got=%r" % _real("phys", 0.10))
_mount({"taken_resist": {"cap": 0.0}})
check("★ 内容侧声明 cap=0.0 ⇒ 免伤整条关闭（实扣 1000）", _real("phys", 0.90) == 1000,
      "got=%r" % _real("phys", 0.90))


print("== D. 读点已收口：承伤侧 min(面板值, cap) 封顶全部走注入面（AST 定位）==")
# ★ 本段前两版都踩了同一个坑：① 用「剔掉字符串字面量所在行」的源码行集合定位读点 ——
#   而 phys_reduce / magic_reduce 本身**就是字符串字面量** ⇒ 目标行被自己剔掉、判据恒空
#   （空集上「无残留硬编码」恒绿）；② 改成 AST 找 min(...) 后又发现**不止 3 处**
#   —— 同族第三处（elem_res 的 cap 0.5，邻支 ②）当时还漏在原地，本轮一并收口。
#   ⇒ 定稿形态：扫**全文件**每一条 `min(面板值, X)` 封顶，逐条点出它的 cap 来源，
#     只要还有一条的字面量不是 getter 名就红（不留豁免名单）。
_ls = io.open(LANDING, encoding="utf-8").read()
_min_caps = [(n.lineno, ast.get_source_segment(_ls, n) or "")
             for n in ast.walk(ast.parse(_ls))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "min" and len(n.args) == 2]
_hard2 = [(ln, s) for ln, s in _min_caps if "st.get(" in s]
check("★ 扫到承伤侧面板封顶 ≥4 处（物免/魔免/元素抗性/格挡/减伤…）—— 判据不是空转",
      len(_hard2) >= 4, "got=%d: %r" % (len(_hard2), _hard2))
_bad2 = [(ln, s) for ln, s in _hard2
         if not re.search(r"_F\.[a-z_]+\(\)|_GC\.formulas\(\)\.[a-z_]+\(\)", s)]
check("★ 面板封顶的 cap 全部走注入面 getter，无一条写字面量", not _bad2, "got=%r" % (_bad2,))
_hard = [(ln, s) for ln, s in _min_caps if "phys_reduce" in s or "magic_reduce" in s]
check("★ 物免/魔免两个读点都定位到了（各 1 处）", len(_hard) == 2, "got=%r" % (_hard,))
_bad = [(ln, s) for ln, s in _hard if "taken_resist_cap()" not in s]
check("★ 物免/魔免都改走 taken_resist_cap()", not _bad, "got=%r" % (_bad,))
_el = [(ln, s) for ln, s in _min_caps if "_res_key" in s]
check("★ 元素抗性读点定位到 1 处且走 taken_elem_resist_cap()",
      len(_el) == 1 and "taken_elem_resist_cap()" in _el[0][1], "got=%r" % (_el,))
_blk = [(ln, s) for ln, s in _min_caps if "block_cap()" in s]
check("★ 格挡那一处仍走 block_cap()（本批没顺手改它）", len(_blk) == 1, "got=%r" % (_blk,))
_fsrc = io.open(FORMULAS, encoding="utf-8").read()
# ★ 两段键在**同一个 dict 字面量**里 ⇒ 只能按「键出现次数」判，不能按行数
#   （第一版写 len(_fkeys)==2 恒假：AST 只给 1 个 lineno，被自己的门禁抓住）。
_fkeys = [k.value for n in ast.walk(ast.parse(_fsrc)) if isinstance(n, ast.Dict)
          for k in n.keys
          if isinstance(k, ast.Constant)
          and k.value in ("taken_resist", "taken_elem_resist")]
check("★ 中性表恰好两段新声明（各自单一回落点）",
      sorted(_fkeys) == ["taken_elem_resist", "taken_resist"], "got=%r" % (_fkeys,))
check("★ getter 名与实现逐字一致（def taken_resist_cap / taken_elem_resist_cap）",
      "def taken_resist_cap(" in _fsrc and "def taken_elem_resist_cap(" in _fsrc,
      "getter 定义缺失")
check("★ get_hook 装配点真存在（注入面名没写错）",
      "get_hook(" in _fsrc and "formula_skeleton_fn" in _fsrc, "get_hook 形态对不上")

print("")
print("结果：通过 %d/%d" % (PASS, PASS + FAIL))
if FAILURES:
    for f in FAILURES:
        print("  FAILED: %s" % f)
raise SystemExit(1 if FAIL else 0)
