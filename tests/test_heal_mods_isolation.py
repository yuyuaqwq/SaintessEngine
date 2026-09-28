# -*- coding: utf-8 -*-
"""治疗三修正**逐个隔离**门禁：坏值只废掉自己那一条（审计 L253 邻支 · 同族收口）。

背景
----
`extends/ext_combat/battle/landing.py::_apply_heal_mods` 里三个修正 —— 受疗增幅
(`heal_amp_pct`) · 禁疗 (`heal_down`) · 重伤 (`_anti_heal_pct`) —— 原先**共用一个
`try/except Exception`**。任一条目的数值形状坏（`float("abc")` 抛 `ValueError`），
异常直接跳到函数末尾的 `except` ⇒ **后面几个修正整段被跳过**。

缺陷实跑复现（改前，同一个 target 同时挂「合法禁疗」与「形状坏的受疗增幅」）::

    只挂禁疗(1 层, per_stack=0.5)          -> 50    <- 正确
    再挂一个坏的 heal_amp_pct(stacks="abc") -> 100   <- 禁疗被连带废掉

零异常、零文案（连本该发的「禁疗」cue 都没有）⇒ 玩家视角 = **禁疗悄悄不生效**。

本门禁钉五件事（**缺一即红**）
------------------------------
A. 隔离：坏 `heal_amp_pct` 不再连带废掉禁疗 / 重伤（本次修的那条）
B. 三个方向对称：禁疗坏 / 重伤坏 也不废掉其余两个
C. 合法路径逐字不变（两种 amp 形态 × 单跑/组合，共 6 格）
D. `effects` 形状不对（list）不再让整段修正崩掉
E. ★ 反证有牙：旧算法在同一组输入上必须给出旧缺陷值 100

跑法：python tests/test_heal_mods_isolation.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, FW_ROOT)
sys.path.insert(0, os.path.join(FW_ROOT, "extends"))

import saintess_engine                                       # noqa: E402,F401
from saintess_engine import config as CFG                    # noqa: E402
from extends.ext_combat.battle import landing as L           # noqa: E402

from _check import bind_check                               # noqa: E402  P0-1 断言助手单源

PASS = 0
FAIL = 0
FAILURES = []
check = bind_check(globals(), "PASS", "FAIL", "FAILURES")

# 挂真骨架表（禁疗每层 0.5、上限 1.0；重伤上限 1.0）—— 不挂则全落中性 0.0 = 判据空转
_saved = CFG._HOOKS.get("formula_skeleton_fn")
CFG._HOOKS["formula_skeleton_fn"] = lambda: {
    "heal_down": {"per_stack": 0.5, "cap": 1.0},
    "anti_heal": {"cap": 1.0},
}


def _mods(effects, amount=100):
    return L._apply_heal_mods(None, {"effects": effects}, amount, [])


_HD = {"heal_down": {"stacks": 1}}                    # 单层禁疗 ⇒ 100 -> 50
_WOUND = {"_anti_heal_pct": {"value": {"pct": 0.5}}}  # 重伤 50%  ⇒ 再 *0.5
_BAD_AMP = {"heal_amp_pct": {"stacks": "abc"}}
_BAD_HD = {"heal_down": {"stacks": "abc"}}
_BAD_WOUND = {"_anti_heal_pct": {"value": {"pct": "abc"}}}

print("== A. 隔离：坏受疗增幅不再连带废掉禁疗 / 重伤 ==")
check("坏amp + 禁疗 => 禁疗照常(50)", _mods({**_BAD_AMP, **_HD}) == 50,
      "got=%r" % (_mods({**_BAD_AMP, **_HD}),))
check("坏amp + 重伤 => 重伤照常(50)", _mods({**_BAD_AMP, **_WOUND}) == 50,
      "got=%r" % (_mods({**_BAD_AMP, **_WOUND}),))
check("坏amp + 禁疗 + 重伤 => 25（三段都跑）",
      _mods({**_BAD_AMP, **_HD, **_WOUND}) == 25,
      "got=%r" % (_mods({**_BAD_AMP, **_HD, **_WOUND}),))

print("== B. 三个方向对称：禁疗坏 / 重伤坏 也不废掉其余 ==")
check("坏禁疗 + 合法重伤 => 50（重伤照常）", _mods({**_BAD_HD, **_WOUND}) == 50,
      "got=%r" % (_mods({**_BAD_HD, **_WOUND}),))
check("坏重伤 + 合法禁疗 => 50（禁疗照常）", _mods({**_BAD_HD, **_WOUND}) == 50,
      "got=%r" % (_mods({**_BAD_HD, **_WOUND}),))
check("三段全坏 => 不崩、回落原值 100", _mods({**_BAD_AMP, **_BAD_HD, **_BAD_WOUND}) == 100,
      "got=%r" % (_mods({**_BAD_AMP, **_BAD_HD, **_BAD_WOUND}),))

print("== C. 合法路径逐字不变（两种 amp 形态 × 单跑/组合）==")
for _fx, _want, _label in (
        ({**_HD}, 50, "单跑禁疗 => 50"),
        ({**_WOUND}, 50, "单跑重伤 => 50"),
        ({**_HD, **_WOUND}, 25, "禁疗+重伤 => 25"),
        ({"heal_amp_pct": {"value": {"amp": 0.5}}}, 150, "受疗增幅 value.amp=0.5 => 150"),
        ({"heal_amp_pct": {"stacks": 1}}, 200, "受疗增幅 stacks 计数=1 => 200"),
        ({"heal_amp_pct": {"value": {"amp": 0.5}}, **_HD}, 75, "增幅+禁疗 => 75"),
        ({}, 100, "无任何修正 => 100"),
        (None, 100, "effects 缺键 => 100"),
):
    _g = _mods(_fx)
    check(_label, _g == _want, "got=%r want=%r" % (_g, _want))

print("== D. effects 形状不对不再让整段修正崩掉 ==")
for _bad_fx, _label in (([], "effects=[]"), ("oops", "effects='oops'"), (7, "effects=7")):
    _g = _mods(_bad_fx)
    check(_label + " => 回落 100", _g == 100, "got=%r" % (_g,))

print("== E. 反证有牙：旧算法（共用一个 try）必给旧缺陷值 ==")


def _old(effects, amount=100):
    """改前的原算法：三段共用一个 try/except，任一抛错就整段跳过。"""
    heal = amount
    try:
        ef = effects or {}
        amp_entry = ef.get("heal_amp_pct")
        if isinstance(amp_entry, dict):
            amp_pct = float(amp_entry.get("value", {}).get("amp", 0) or 0)                 if isinstance(amp_entry.get("value"), dict)                 else float(amp_entry.get("stacks", 0) or 0)
            if amp_pct > 0:
                heal = int(round(heal * (1 + min(amp_pct, 1.0))))
        hd_entry = ef.get("heal_down")
        if isinstance(hd_entry, dict):
            ehd = int(hd_entry.get("stacks", 0) or 0)
            if ehd > 0:
                heal = max(0, int(heal * 0.5))
        ah_entry = ef.get("_anti_heal_pct")
        if isinstance(ah_entry, dict):
            aheal = float((ah_entry.get("value") or {}).get("pct", 0) or 0)
            if aheal > 0:
                heal = max(0, int(heal * (1 - min(aheal, 1.0))))
    except Exception:
        pass
    return max(0, heal)


check("反证·旧算法「坏amp+禁疗」给 100（!= 新口径 50）",
      _old({**_BAD_AMP, **_HD}) == 100, "got=%r" % (_old({**_BAD_AMP, **_HD}),))
check("反证·旧算法「坏禁疗+重伤」给 100（!= 新口径 50）",
      _old({**_BAD_HD, **_WOUND}) == 100, "got=%r" % (_old({**_BAD_HD, **_WOUND}),))
check("反证·旧算法在**合法**输入上与新口径同值（证明改的是隔离、不是数值）",
      _old({**_HD, **_WOUND}) == _mods({**_HD, **_WOUND}),
      "old=%r new=%r" % (_old({**_HD, **_WOUND}), _mods({**_HD, **_WOUND})))

print(chr(10) + "== 结果：通过 %d / 共 %d ==" % (PASS, PASS + FAIL))
if FAIL:
    for _f in FAILURES:
        print("  FAIL: %s" % _f)
    sys.exit(1)
if _saved is None:
    CFG._HOOKS.pop("formula_skeleton_fn", None)
else:
    CFG._HOOKS["formula_skeleton_fn"] = _saved
print("全绿 ✅")
