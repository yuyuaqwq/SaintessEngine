#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：`pct_cur` 型 DoT（按**当前生命%** 掉血）的档位口径 + 两态 + 反证。

为什么要有它（2026-09-25 实测的真 bug）
------------------------------------------------------------------
武器特效 `blood_trace`（败血，`effect_rules.json` 的 `period.pct_cur_hp` 0.02 /
`period.pct_cur_boss` 0.015）走的是 `_settle_time_effects` 里 `elif pct_cur > 0:` 这条分支。
E3 刀1 把「谁是 boss」从硬编码改成内容侧标签名单时，**只改了 `pct` 那条分支**（`_boss_like`
→ `_trait_like`），这条分支还读 `_boss_like` —— 那个名字已经不存在 ⇒ 每跳抛
`NameError: name '_boss_like' is not defined`，而这条分支外面没有 except ⇒ 异常冒到
`advance()`（**战斗推进崩**）。当时引擎自检 90/90、内容探针 36/36 全绿：没有任何用例走到这条分支。

判据（两态 + 反证）
------------------------------------------------------------------
① 零异常：带 `pct_cur_hp` 的 period 跳一次不许抛（回归判据）。
② 无标签的怪 ⇒ 扣 `int(当前血 × pct_cur_hp)`。
③ `traits` 命中声明名单（`period["trait_tags"]`）⇒ 扣 `int(当前血 × pct_cur_boss)`。
④ 名单不匹配（或没声明名单）⇒ 走普通档（名单为空 = 这条规则不适用于任何人）。
⑤ 反证：源码里 `_boss_like` 作为**名字**零出现、`_trait_like` 先绑定后使用（旧名不许回归）。

跑法：`python tests/test_dot_cur_hp_shape.py`；退出码 0 = 全绿 · 1 = 有失败。
"""
import ast
import io
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
# 扩展包目录也要进 sys.path：`ext_combat` 住 `extends/` 下（run_all.py 给 worker 设 PYTHONPATH，
# 但本文件要能**独立**跑 —— 直接 `python tests/test_dot_cur_hp_shape.py` 也不许因为路径而红）。
for _p in (ROOT, os.path.join(ROOT, "extends")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ext_combat import Battle, make_actor                        # noqa: E402
from ext_combat.battle import diagnostics as DG                   # noqa: E402
from ext_combat.battle import schedule as SCH                    # noqa: E402

passed = failed = 0
DETAIL = []

from _check import bind_check  # noqa: E402

check = bind_check(globals(), "passed", "failed", "DETAIL")

#: 逐字抄自线上数据 `games/orlandia/content/rules/effect_rules.json` 的 `blood_trace/period`
#: （`trait_tags` 是拿掉 boss 档折扣那次修补后补上的声明，与 bleed/burn/corros/poison 同款）
BLOOD_TRACE = {"dir": "damage", "interval": 1.0, "pct_cur_hp": 0.02,
               "pct_cur_boss": 0.015, "turns": 4, "trait_tags": ["boss", "elite"]}


def scene(traits, period, dt=1.05):
    """造一场最小战斗，把 period 挂在怪身上，推进 dt 秒 → (血前, 血后, 跳伤表, 异常, 诊断)"""
    pa = make_actor("p1", "甲", "player", kind="player", human_controlled=True,
                    hp=100, max_hp=100, atk=20, spd=10)
    ea = make_actor("e1", "怪", "enemy", kind="monster", hp=309, max_hp=309, atk=10, spd=5)
    if traits is not None:
        ea["traits"] = list(traits)
    b = Battle(btype="monster", sides={"player": [pa], "enemy": [ea]},
               title_bonus={}, seed_ct=False)
    ea["effects"]["probe_dot"] = {"stacks": 1, "period": dict(period)}
    SCH._advance_time(b, 0.1, [])              # 登记首跳（now + interval）
    hp0 = int(ea["hp"])
    logs = []
    err = None
    try:
        SCH._advance_time(b, dt, logs)
    except BaseException as e:                 # noqa: BLE001
        err = e
    ticks = [int(x) for x in re.findall(r"损失 (\d+) 生命", " ".join(logs))]
    return hp0, int(ea["hp"]), ticks, err, DG.of(b)


print("【1. ★ 零异常：带 pct_cur_hp 的 DoT 跳一次不许抛（E3 刀1 的 NameError 回归判据）】")
h0, h1, ticks, err, diags = scene(None, BLOOD_TRACE)
check("不抛异常（原先 NameError: _boss_like）", err is None, repr(err))
check("出了 DoT 日志（真的结算了，不是被吞掉）", bool(ticks), repr(ticks))
check("这一场零诊断（正常路径不该有诊断）", not diags, repr(diags[:2]))

print("\n【2. 普通档：无标签的怪 ⇒ int(当前血 × pct_cur_hp)】")
exp = max(1, int(h0 * 0.02))
check("扣血 = int(当前血 × 0.02)", (h0 - h1) == exp and ticks == [exp],
      "%d→%d · %r（期望 %d）" % (h0, h1, ticks, exp))

print("\n【3. ★ 声明驱动：traits 命中 trait_tags ⇒ 走 pct_cur_boss 档】")
h0b, h1b, ticksb, errb, diagsb = scene(["boss"], BLOOD_TRACE)
expb = max(1, int(h0b * 0.015))
check("不抛异常", errb is None, repr(errb))
check("扣血 = int(当前血 × 0.015)（= 声明里给的 pct_cur_boss）", (h0b - h1b) == expb and ticksb == [expb],
      "%d→%d · %r（期望 %d）" % (h0b, h1b, ticksb, expb))
check("boss 档 ≠ 普通档（标签名单真的被读了）", (h0 - h1) != (h0b - h1b),
      "%d vs %d" % (h0 - h1, h0b - h1b))

print("\n【4. 反向：名单不匹配 / 没声明名单 ⇒ 一律走普通档（零兜底）】")
_no_tags = {k: v for k, v in BLOOD_TRACE.items() if k != "trait_tags"}
h0c, h1c, ticksc, errc, _ = scene(["boss"], _no_tags)
expc = max(1, int(h0c * 0.02))
check("没声明 trait_tags ⇒ 即使身上有 boss 标签也不打折", (h0c - h1c) == expc,
      "%d→%d · %r" % (h0c, h1c, ticksc))
h0d, h1d, ticksd, errd, _ = scene(["undead"], BLOOD_TRACE)
check("声明名单有 boss/elite、身上只有**别的**标签（undead）⇒ 不打折",
      (h0d - h1d) == max(1, int(h0d * 0.02)), "%d→%d · %r" % (h0d, h1d, ticksd))
h0f, h1f, ticksf, errf, _ = scene(["elite"], BLOOD_TRACE)
check("名单是「任一命中」：身上是 elite（名单第二个）⇒ 照样打折",
      (h0f - h1f) == max(1, int(h0f * 0.015)), "%d→%d · %r" % (h0f, h1f, ticksf))

print("\n【5. 多跳：每跳按「跳前当前血」递推（间隔 1 秒、推进 2.05 秒 → 两跳）】")
h0e, h1e, tickse, erre, _ = scene(None, BLOOD_TRACE, dt=2.05)
e1 = max(1, int(h0e * 0.02))
e2 = max(1, int((h0e - e1) * 0.02))
check("两跳合计 = 逐跳递推值", (h0e - h1e) == e1 + e2 and tickse == [e1, e2],
      "%d→%d · %r（期望 %r）" % (h0e, h1e, tickse, [e1, e2]))

print("\n【6. 反证：旧名不许回归】")
src = io.open(os.path.join(ROOT, "extends", "ext_combat", "battle", "schedule.py"),
              encoding="utf-8").read()
names = {n.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Name)}
check("`_boss_like` 作为名字零出现（注释里提到不算）", "_boss_like" not in names,
      str(sorted(x for x in names if "boss_like" in x)))
check("`_trait_like` 先绑定后使用", src.index("_trait_like =") < src.index("_trait_like and"))
check("`pct_cur_boss` 那条分支读的是 `_trait_like`（不是别的名字）",
      "if _trait_like and period.get(\"pct_cur_boss\")" in src)

print("\n结果：通过 %d / 共 %d" % (passed, passed + failed))
if failed:
    print("失败项：")
    for x in DETAIL:
        print("  · %s" % x)
    sys.exit(1)
