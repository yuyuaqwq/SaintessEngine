#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gates 门禁：引擎里**不得出现内容侧游戏词表**（准则 1 的注释侧变体 · 审计 L1740 / L1741 / L1744）。

跑法：python tests/test_gates_no_game_vocab.py
退出码：0 = 全绿；1 = 有失败。

台账三条的原判（逐条回读原文核对后，结论与修法如下）：
  · L1741 `within_budget:89` 写死 `PE(装等 L, 品阶 Q) = PE_base(L) x (1 + 0.08 x Q)`、
    `:109` 写死「同装等+同品阶+同槽位 / 同职业+同等级段」
    —— 与本模块 docstring「有意不做：不算 PE / 不猜分组键」**自相矛盾**：
    判据全在注释里，而引擎根本不认识这些词。
  · L1740 `within_cap:200-202` 的字段词表**过期**。台账给的证据是反的
    （它写「`heal_power` 0 文件、实际叫 `heal_pow`」）—— 实测 `heal_pow` 全盘**零命中**，
    `heal_power` 在 orlandia 12 个文件真实在用；同段的 `crit_dmg` 上限注释写 1.5，
    内容侧真源 `content/rules/panel_rules.json` 的 `pct_caps` 实为 **1.0**；`haste` 两仓均零命中。
  · L1744 `spread_within:130-132` 注释承诺「取极差贡献最大的若干条」，
    实现是**原输入序**取前 6（实跑复现：hi=100/lo=50/小偏离=99/大偏离=51
    ⇒ 输出 `小偏离, 大偏离, ...` 恰是原输入序）。台账定级「低」且注明只影响点名顺序。

★ 修法统一为**删注释里的内容词表**（不是排序实现）：三条都只碰注释/文档串，
**生产行为逐字节不变**（已对拍，见作业书）。
★ 判据钉的是**性质**（引擎里零游戏词），不是「某几个词不许出现」——
所以这条门禁**没有豁免名单**：任何游戏词写进引擎都会被它抓住，
包括下一个人新写的。词表在 `GAME_VOCAB` 里，改词表 = 改判据（会被反证抓到）。
★ 防「空转恒绿」：末尾有一条反证锚点 —— 若词表与断言都失效（比如有人把
  `GAME_VOCAB` 清空），第一条立刻转红。
"""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

# 内容侧游戏词表（准则 1 禁止出现在引擎里的那一族）
GAME_VOCAB = (
    "装等", "品阶", "职业", "槽位", "装备", "词条", "词缀", "职业套装",
    "haste", "heal_power", "heal_pow", "elem_res", "abyss_res", "lifesteal",
    "crit_dmg", "PE_base", "PctCaps", "panel_rules",
)
# 反向声明里合法的「非游戏词」对照（这些是引擎自己的词，不在词表内）
PURE_ENGINE_WORDS = ("budget", "tol", "cap", "label", "rows", "order_key")

TARGET = os.path.join(ROOT, "saintess_engine", "gates", "__init__.py")

import io as _io  # noqa: E402

_lines = _io.open(TARGET, encoding="utf-8").read().splitlines()
_src = "\n".join(_lines)

passed = failed = 0
check = bind_check(globals(), "passed", "failed")

# ---------------------------------------------------------------- ① 词表本身非空
#  ★ 词表自身的反证锚点：**逐条钉住 L1740/L1741 原文里出现过的游戏词**。
#    只查「非空」是空转判据 —— 有人把词逐条删掉、门禁照样绿（本轮自抓过）。
_VOCAB_ANCHOR = ("装等", "品阶", "职业", "槽位", "装备", "词条",
                 "haste", "heal_power", "elem_res", "crit_dmg", "PE_base")
_lost = [w for w in _VOCAB_ANCHOR if w not in GAME_VOCAB]
check("反证锚点：GAME_VOCAB 逐条覆盖 L1740/L1741 原始词（减一条即红）",
      not _lost, f"缺={_lost}")

# ---------------------------------------------------------------- ② 引擎里零游戏词
_hits = []
for _n, _line in enumerate(_lines, 1):
    for _w in GAME_VOCAB:
        if _w in _line:
            _hits.append(f"{_n}:{_w}")
check("gates/__init__.py 零内容侧游戏词（准则 1 注释侧 · L1740/L1741）",
      not _hits, "; ".join(_hits[:12]))

# ---------------------------------------------------------------- ③ 注释承诺与实现相符（L1744）
#  判据钉的是「注释不再承诺它做不到的事」：一旦有人把「按输入序」改回
#  「取极差贡献最大」而实现没跟着改，这里立刻红。
_claim_lines = [L for L in _lines if ("贡献最大" in L or "贡献排序" in L)
                 and "真要按偏离度排序是内容侧读文案时的事" not in L]
def _body_of(name):
    """取某个 def 的函数体原文（判据钉行为，不钉全文件 grep）。"""
    i = _src.index("def " + name + "(")
    j = _src.index(chr(10) + "def ", i + 1)
    return _src[i:j]

#  ★ 本轮自抓的一条空转：`sorted(` 在 monotone_by 里**合法**（它真排序），
#   拿全文件 grep 当「已排序」⇒ 恒 True ⇒ L1744 那条永远绿。
#   正解 = 只看 spread_within 自己的函数体。
_sp_body = _body_of("spread_within")
_bad_sorted = "sorted(" in _sp_body
check("L1744 判据真会红（反证锚点：spread_within 此刻无排序 = 承诺若出现必红）",
      not _bad_sorted)
check("spread_within 不再承诺「按贡献排序」而实现是输入序（L1744 注释/实现相符）",
      not _claim_lines or _bad_sorted, str(_claim_lines[:3]))

# ---------------------------------------------------------------- ④ 生产行为逐字节不变
#  这三条全是注释改动，行为面必须一模一样（黑盒对拍）。
from saintess_engine import gates  # noqa: E402

check("within_budget 合法输入仍返回空（注释改动零行为影响）",
      gates.within_budget(10.0, budget=20.0, label="L1") == [])
check("within_budget 越界仍给一条中文可读文案",
      len(gates.within_budget(30.0, budget=20.0, label="L1")) == 1)
check("within_cap cap=None 仍恒通过（None 语义未动）",
      gates.within_cap(999.0, cap=None, label="L1") == [])
check("within_cap 越界仍给一条文案",
      len(gates.within_cap(9.0, cap=1.0, label="L1")) == 1)
_sp = gates.spread_within([("hi", 100.0), ("lo", 50.0), ("a", 99.0), ("b", 51.0)],
                          tol=0.10, label="L1")
check("spread_within 点名顺序仍是原输入序（本次刻意不排序）",
      _sp and "越界条目：hi, lo, a, b" in _sp[0], _sp)
check("spread_within 通过时仍返回空",
      gates.spread_within([("a", 1.0), ("b", 1.0)], tol=0.5, label="L1") == [])

print(f"  passed={passed}  failed={failed}")
sys.exit(1 if failed else 0)
