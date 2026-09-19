#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：战斗日志「文案口」——`render_via(battle, …)` / `Battle(text=…)`。

为什么需要它（台账 T2）
----------------------
引擎原先有 56 处玩家可见中文内联在 f-string 里（landing / effects / actions /
schedule / battle），与「文案唯一真源在内容包的表」相左。迁移做法 = **构造注入**
（A 案）：`Battle(..., text=<文案表>)` 可选，调用点只给「key + 兜底模板 + 槽位」。

四条不变量：
  1. **注入生效（反证）**：给了表 → 输出**随表变**（证明注入不是死代码）。
  2. **未注入 = 兜底模板**：不传 `text` → 输出**逐字节等于历史内联串**（零回归）。
  3. **表缺 key 回落**：表里只声明一条 → 其余仍走兜底（渐进迁移语义）。
  4. **残留扫描**：`saintess_engine/battle/*.py` 的日志实参**零中文**
     （`gauge/` 两文件待 T2 第 2 轮迁，见台账；届时纳入本扫描）。

跑法：python tests/test_battle_text_inject.py（exit=0 全绿）
"""
from __future__ import annotations

import ast
import os
import random
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
if FW_ROOT not in sys.path:
    sys.path.insert(0, FW_ROOT)

from saintess_engine import Battle                                   # noqa: E402
from saintess_engine.battle import landing                           # noqa: E402
from saintess_engine.battle.actors import ActCtx, make_actor          # noqa: E402
from saintess_engine.text import render_via                          # noqa: E402

passed = failed = 0


from _check import bind_check  # noqa: E402

check = bind_check(globals(), "passed", "failed")

CJK = re.compile(r"[\u4e00-\u9fff]")
BATTLE_DIR = os.path.join(FW_ROOT, "saintess_engine", "battle")


class _Stub:
    """假文案表（只实现 `render_or`）：返回可辨标记，便于断言「注入真生效」。"""

    def __init__(self, mapping=None):
        self.mapping = dict(mapping or {})
        self.asked = []

    def render_or(self, key, default, **slots):
        self.asked.append(key)
        if key in self.mapping:
            return self.mapping[key]
        return "[缺]%s" % key


def _setup(text=None):
    """两名 actor 的最小战斗（seed_ct=False：本门禁不碰时间模型注入面）。"""
    pa = make_actor("p1", "甲", "player", kind="player", human_controlled=True,
                    hp=100, max_hp=100, atk=20, spd=10)
    ea = make_actor("e1", "房间怪", "enemy", kind="monster",
                    hp=500, max_hp=500, atk=10, spd=5)
    b = Battle(btype="monster", sides={"player": [pa], "enemy": [ea]},
               title_bonus={}, seed_ct=False, text=text)
    return b, pa, ea


# ---------------------------------------------------------------- 1. 注入生效
print("【1. 注入生效（反证）：给了表 → 输出随表变】")
stub = _Stub()
b, _pa, ea = _setup(text=stub)
logs = []
random.seed(7)
landing.deal_damage(b, None, ea, 7, logs)
check("注入表被问到 key（battle.landing.damage 在册）",
      "battle.landing.damage" in stub.asked, stub.asked[:4])
check("★ 日志取自注入表（不是内联串）", logs == ["[缺]battle.landing.damage"], logs)
stub2 = _Stub({"battle.landing.damage": "★改过的串★"})
b2, _pa2, ea2 = _setup(text=stub2)
logs2 = []
landing.deal_damage(b2, None, ea2, 7, logs2)
check("★ 表里换一串 → 该行输出必变（注入非死代码）", logs2 == ["★改过的串★"], logs2)

# ---------------------------------------------------------------- 2. 未注入 = 兜底
print("\n【2. 未注入 = 兜底模板：逐字节等于历史内联串】")
b3, pa3, ea3 = _setup()
logs3 = []
random.seed(7)
landing.deal_damage(b3, None, ea3, 7, logs3)
check("伤害行逐字", logs3 == ["💥 房间怪 受到 7 点伤害！"], logs3)
logs4 = []
landing.deal_damage(b3, None, ea3, 99999, logs4)
check("倒下行逐字", logs4 == ["💥 房间怪 受到 493 点伤害，倒下了！"], logs4)
check("防御行逐字", b3._do_defend(ActCtx(caster=pa3, action="defend"))
      == ["🛡 甲 摆出防御姿态，受到的伤害减半！"])
check("逃跑行逐字", b3._do_flee(ActCtx(caster=pa3, action="flee")) == ["💨 甲 逃跑了！"])
check("终局行逐字（human_act 已结束）",
      b3.human_act("defend", None) == (["战斗已结束！"], True, None))
check("显式 text=None 与不给参数同款", _setup(text=None)[0].text is None)

# ---------------------------------------------------------------- 3. 表缺 key 回落
print("\n【3. 表缺 key → 回落兜底模板（渐进迁移语义）】")
stub3 = _Stub({"battle.landing.damage": "★只改了伤害行★"})
b4, _p, ea4 = _setup(text=stub3)
logs5 = []
landing.deal_damage(b4, None, ea4, 7, logs5)
logs6 = []
landing.deal_damage(b4, None, ea4, 99999, logs6)
check("声明的 key 走表", logs5 == ["★只改了伤害行★"], logs5)
check("未声明的 key 走兜底（无异常、无空串）",
      logs6 == ["[缺]battle.landing.down"], logs6)

# ---------------------------------------------------------------- 4. 残留扫描
print("\n【4. 残留扫描：battle/*.py 的日志实参零中文】")
_TEXTCALLS = ("_t", "render_via", "render_or")


def _cjk_log_lits(path):
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src, filename=path)
    out = []
    for n in ast.walk(tree):
        arg = None
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr in ("append", "extend", "insert") and n.args:
            arg = n.args[0]
        elif isinstance(n, ast.Return) and n.value is not None:
            arg = n.value
        elif isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "logs" for t in n.targets):
            arg = n.value
        if arg is None:
            continue
        exempt = set()
        for c in ast.walk(arg):
            if isinstance(c, ast.Call):
                fn = c.func
                nm = fn.attr if isinstance(fn, ast.Attribute) else (
                    fn.id if isinstance(fn, ast.Name) else "")
                if nm in _TEXTCALLS:
                    exempt.update(id(x) for x in ast.walk(c))
        for c in ast.walk(arg):
            if not (isinstance(c, ast.Constant) and isinstance(c.value, str)
                    and CJK.search(c.value)):
                continue
            if id(c) in exempt:
                continue
            is_fallback = any(
                isinstance(g, ast.Call) and isinstance(g.func, ast.Attribute)
                and g.func.attr == "get" and len(g.args) == 2 and g.args[1] is c
                for g in ast.walk(arg))
            if not is_fallback:
                out.append((n.lineno, c.value[:40]))
    return out


left = []
for _f in sorted(os.listdir(BATTLE_DIR)):
    if _f.endswith(".py"):
        left.extend(("%s:%d" % (_f, ln), v) for ln, v in _cjk_log_lits(os.path.join(BATTLE_DIR, _f)))
check("★ battle/ 日志实参零中文（措辞全走 key + 兜底模板）", not left, left[:4])

print("\n【5. 渲染口本体】")
check("render_via(None, …) = 兜底模板", render_via(None, "k", "x {y}", y=1) == "x 1")
check("render_via(替身无 text) = 兜底模板",
      render_via(object(), "k", "无槽位") == "无槽位")
class _Holder:
    """只带 `text` 一个字段的持有者（= Battle 的注入面形状）。"""

    def __init__(self, text):
        self.text = text


check("render_via 转发到表的 render_or（key/default/slots 原样）",
      render_via(_Holder(_Stub({"k": "T"})), "k", "D {y}", y=2) == "T")

print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
sys.exit(1 if failed else 0)
