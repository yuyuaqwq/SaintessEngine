# -*- coding: utf-8 -*-
"""r22 门禁：技能叠层数「面板承诺」与「实机落下」必须逐格相等（等级成长曲线同源）。

背景（本门禁为什么存在）
------------------------------------------------------------------
`extends/ext_combat/battle/effects.py::effects_from_skill` 原先恒取**裸** `mech_val`
（`int(info.get("mech_val", 0) or 0)`），把形参 `lv` 收下**却从不读**。
而内容侧技能面板（`combat_cmds.py` 的 `_skill_list_gains` / `_skill_gains_curve`）
打的是 `skill_mech_val(info, lv)` = `base + (lv-1)//m`（默认每 2 级 +1 层）。

⇒ **玩家在面板上看到的层数与实机真正落下的层数在 Lv≥2 全不相等**：真包实测
   110 格（21 条技能 × 各等级）里 **72 格对不上**（Lv.3 起逐级偏低，如
   横扫 Lv.5 面板写 3 层 / 实机只落 1 层，机制触发门槛随之差一整级）。
   同包 `actions.py` 的护盾路**早就**走 `skill_mech_val` ⇒ 本函数是**同族漏网**。

本门禁钉四件事（**缺一即红**）
------------------------------
A. **同源**：真包逐格对拍「`effects_from_skill` 落下的层数」vs「`skill_mech_val`」
   —— 21 条带 mech 的技能 × 全部等级，**零不等**。
B. **注入面真的通**（不是写死）：挂上 `skill_up_fn` 后改 `m`（成长间隔）⇒
   落下层数跟着变 ⇒ 证明走的是曲线而非硬编码。
C. **无装配中性**：`formula_skeleton_fn` / `skill_up_fn` 都没挂时，
   `skill_mech_val({'mech_val': 2}, 1)` 恒等于裸值 2（Lv.1 不成长）⇒
   **未装配包零行为变化**（迁移不改行为的正证）。
D. **源码形状**：读点已收口 —— `effects_from_skill` 函数体里不再有裸
   `int(info.get("mech_val"` 取值（免得下轮"顺手改回去"）。

跑法：python tests/test_r22_mech_stack_lv_curve.py
"""
import io
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, FW_ROOT)
sys.path.insert(0, os.path.join(FW_ROOT, "extends"))

from saintess_engine import config as _cfg                      # noqa: E402
from extends.ext_combat.battle import formulas as F            # noqa: E402
from extends.ext_combat.battle import effects as EF             # noqa: E402

PASS = 0
FAIL = 0
def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  OK  %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s  %s" % (label, detail))


def _mech_stacks(effs, mech):
    """从 effects_from_skill 的产物里取某个 mech 落下的层数/值（无则 None）。"""
    for e in effs or []:
        if e.get("mech") == mech and "stacks" in e:
            return e.get("stacks")
        if e.get("type") == "apply" and e.get("key") == mech and "amount" in e:
            return e.get("amount")
    return None


# ══════════════════════════════════════════════════════════════
# A. 同源：叠层是「层数型」mech（面板真的会打"叠层 N"）才纳入对拍。
#    分数型 mech（如引燃 mark_burst=0.35）面板打的是别的维度，不属本门禁口径
#    —— 它另有一条"面板把 0.35 折成 0 层"的显示问题（内容侧，已登记留主线）。
# ══════════════════════════════════════════════════════════════
_CURVE_SKILLS = [
    # (skill_id, mech, mech_val, max_lv, skill_up)
    ("taunt",      "taunt",        3.0,  5, None),
    ("standfast",  "unstoppable", 300,  5, None),
    ("bulwark",    "oath_shield", 300,  5, None),
    ("rearguard",  "hold_line",   150,  5, None),
    ("sunder",     "def_break",    30,  5, None),
    ("blooddebt",  "blood_price", 200,  5, None),
    ("riposte",    "riposte",    180,  5, None),
    ("sweep",      "blood_sweep",  1,  5, None),
    ("quickstep",  "advance_ct",  30,  5, None),
    ("pindown",    "pin_down",   100,  5, None),
    ("silence",    "silence_lock",100, 5, None),
    ("frostveil",  "frostveil",  240,  5, None),
    ("aegis",      "aegis",       30,  5, None),
    ("lullaby",    "lullaby",    300,  5, None),
    ("matins",     "matins",     100,  5, None),
    ("nightwatch", "nightwatch", 250,  5, None),
    ("bleed",      "bleed",      300,  5, None),
    ("sever",      "sever",      200,  5, None),
    ("sidestep",   "sidestep",   180,  5, None),
]

print("A. 叠层同源对拍（面板承诺 vs 实机落下）")
_mismatch = []
for sid, mech, mval, mx, up in _CURVE_SKILLS:
    info = {"key": sid, "name": sid, "mech": mech, "mech_val": mval, "max_lv": mx}
    for lv in range(1, mx + 1):
        effs = EF.effects_from_skill(dict(info), lv)
        got = _mech_stacks(effs, mech)
        want = F.skill_mech_val(dict(info), lv)
        if got != want:
            _mismatch.append((sid, mech, lv, got, want))
check("A1 19 条叠层技能 × 全部等级零不等（%d 格）" % (len(_CURVE_SKILLS) * 5),
      not _mismatch, "不等格：%s" % (_mismatch[:6],))

# A2. 精确钉住一格历史上对不上的（横扫 Lv.5：面板 3 / 旧实机 1）
_info = {"key": "sweep", "mech": "blood_sweep", "mech_val": 1, "max_lv": 5}
check("A2 横扫 Lv.5 实机落 3 层（旧写法落 1）",
      _mech_stacks(EF.effects_from_skill(dict(_info), 5), "blood_sweep") == 3,
      "实得 %r" % (_mech_stacks(EF.effects_from_skill(dict(_info), 5), "blood_sweep"),))

# A3. Lv.1 零成长（两条路必须相等 —— 这一格历史上就相等，用来钉住"没把 Lv.1 也改坏"）
check("A3 Lv.1 层数 = 裸 mech_val（无成长）",
      _mech_stacks(EF.effects_from_skill(dict(_info), 1), "blood_sweep") == 1,
      "实得 %r" % (_mech_stacks(EF.effects_from_skill(dict(_info), 1), "blood_sweep"),))

# ══════════════════════════════════════════════════════════════
# B. 注入面真的通：改 m（成长间隔）⇒ 落下层数跟着变
# ══════════════════════════════════════════════════════════════
print("B. 注入面真的通（skill_up_fn 可改成长间隔）")
_orig_up = _cfg.get_hook("skill_up_fn")
try:
    _cfg.set_hook("skill_up_fn", lambda info: {"m": 4})
    got4 = _mech_stacks(EF.effects_from_skill(dict(_info), 5), "blood_sweep")
    check("B1 成长间隔 m=4 ⇒ Lv.5 落 2 层（m=2 时是 3）", got4 == 2, "实得 %r" % (got4,))
finally:
    if _orig_up is None:
        _cfg.set_hook("skill_up_fn", None)
    else:
        _cfg.set_hook("skill_up_fn", _orig_up)

# ══════════════════════════════════════════════════════════════
# C. 无装配中性：Lv.1 恒等于裸值 ⇒ 未装配包零行为变化
# ══════════════════════════════════════════════════════════════
print("C. 无装配中性（未装 formula_skeleton / skill_up 时）")
check("C1 skill_mech_val({'mech_val': 2}, 1) == 2（Lv.1 不成长）",
      F.skill_mech_val({"mech_val": 2}, 1) == 2, "实得 %r" % (F.skill_mech_val({"mech_val": 2}, 1),))
check("C2 effects_from_skill 零装配 Lv.1 落裸值 2",
      _mech_stacks(EF.effects_from_skill({"mech": "taunt", "mech_val": 2, "max_lv": 5}, 1),
                   "taunt") == 2,
      "实得 %r" % (_mech_stacks(EF.effects_from_skill({"mech": "taunt", "mech_val": 2, "max_lv": 5}, 1), "taunt"),))

# ══════════════════════════════════════════════════════════════
# D. 源码形状：读点已收口（不再有裸 mech_val 取值）
# ══════════════════════════════════════════════════════════════
print("D. 源码形状（读点已收口）")
_src = io.open(os.path.join(FW_ROOT, "extends", "ext_combat", "battle", "effects.py"),
               encoding="utf-8").read()
_m = re.search(r"def effects_from_skill\(.*?\n(?=def )", _src, re.S)
_body = _m.group(0) if _m else ""
check("D1 effects_from_skill 体内不再取裸 int(info.get('mech_val'",
      'int(info.get("mech_val"' not in _body, "仍有一行裸取值")
check("D2 该函数确实调了 skill_mech_val（钉住走的是曲线）",
      "skill_mech_val" in _body, "没找到 skill_mech_val 调用")

print("\nPASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
