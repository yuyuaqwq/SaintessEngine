#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：战斗日志「文案口」——`render_via(battle, …)` / `Battle(text=…)`。

为什么需要它（台账 T2）
----------------------
引擎原先有 61 处玩家可见中文内联在 f-string 里（landing / effects / actions /
schedule / battle + gauge），与「文案唯一真源在内容包的表」相左。迁移做法 = **构造注入**
（A 案）：`Battle(..., text=<文案表>)` 可选，调用点只给「key + 兜底模板 + 槽位」；
模块级结算函数（`gauge.bar_gain` / `gauge.bar_trigger`）拿不到 `Battle`，由动作侧
经 `text_of(battle)` 把表下传（`text=` 关键字）。

四条不变量：
  1. **注入生效（反证）**：给了表 → 输出**随表变**（证明注入不是死代码）。
  2. **未注入 = 兜底模板**：不传 `text` → 输出**逐字节等于历史内联串**（零回归）。
  3. **表缺 key 回落**：表里只声明一条 → 其余仍走兜底（渐进迁移语义）。
  4. **残留扫描**：`saintess_engine/battle/*.py` + `gauge/*.py` 的日志实参**零中文**
     （措辞全走「key + 兜底模板 + 槽位」；T2 第 2 轮已把 `gauge/` 两文件纳入本扫描）。

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
from saintess_engine import gauge as G                                 # noqa: E402
from saintess_engine.text import TextTable, render_or, render_via, text_of  # noqa: E402

passed = failed = 0


from _check import bind_check  # noqa: E402

check = bind_check(globals(), "passed", "failed")

CJK = re.compile(r"[\u4e00-\u9fff]")
BATTLE_DIR = os.path.join(FW_ROOT, "saintess_engine", "battle")
GAUGE_DIR = os.path.join(FW_ROOT, "saintess_engine", "gauge")


class _Stub:
    """假文案表（只实现 `render_or`）：返回可辨标记，便于断言「注入真生效」。"""

    def __init__(self, mapping=None):
        self.mapping = dict(mapping or {})
        self.asked = []

    def render_or(self, key, default, /, **slots):   # 位置专属：与真表同形状
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
# heal 路径：私有助手 `_apply_heal_mods` 拿不到 battle ⇒ 用只读持有者 `_TextHolder` 过文案口。
# （T2 第 1 轮此处漏了持有者定义 ⇒ 真 NameError，被包侧 heal/吸血用例抓到；本段钉死不再回归）
_h1 = make_actor("h1", "木桩", "enemy", kind="monster", hp=50, max_hp=100)
check("治疗落地返回真实回血（不再 NameError）", landing.heal_actor(b3, _h1, 30, []) == 30)
check("治疗量 clamp 到 max_hp（50+999 → 100，实回 20）",
      landing.heal_actor(b3, _h1, 999, []) == 20)
_h2 = make_actor("h2", "木桩", "enemy", kind="monster", hp=50, max_hp=100)
_h2.setdefault("effects", {})["heal_down"] = {"stacks": 1}
_lg = []
landing.heal_actor(b3, _h2, 30, _lg)
check("未注入 → 禁疗行 == 兜底模板（历史文案形状）",
      len(_lg) == 1 and _lg[0].startswith("🩸 禁疗：治疗量 -") and _lg[0].endswith("%！"), _lg)
b5, _p5, _e5 = _setup(text=_Stub({"battle.landing.heal_forbid": "F"}))
_h3 = make_actor("h3", "木桩", "enemy", kind="monster", hp=50, max_hp=100)
_h3.setdefault("effects", {})["heal_down"] = {"stacks": 1}
_lg2 = []
landing.heal_actor(b5, _h3, 30, _lg2)
check("★ 注入表 → 禁疗行取自表（heal 私有助手的文案口也通）", _lg2 == ["F"], _lg2)

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
print("\n【4. 残留扫描：battle/ + gauge/ 的日志实参零中文】")
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
for _label, _dir in (("battle", BATTLE_DIR), ("gauge", GAUGE_DIR)):
    for _f in sorted(os.listdir(_dir)):
        if _f.endswith(".py"):
            left.extend(("%s/%s:%d" % (_label, _f, ln), v)
                        for ln, v in _cjk_log_lits(os.path.join(_dir, _f)))
check("★ battle/ + gauge/ 日志实参零中文（措辞全走 key + 兜底模板）", not left, left[:4])

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


# ---------------------------------------------------------------- 6. gauge 文案口
print()
print("【5'. 文案口形参位置专属（槽位名可与 key / default / text 同名，不炸）】")
import inspect as _insp                                                    # noqa: E402

_pv = _insp.signature(render_via).parameters
check("render_via 前 3 形参位置专属（holder / key / default）",
      all(_pv[_n].kind is _insp.Parameter.POSITIONAL_ONLY for _n in ("holder", "key", "default")),
      str({_n: str(_pv[_n].kind) for _n in _pv}))
_p2 = _insp.signature(render_or).parameters
check("render_or 前 3 形参位置专属（text / key / default）",
      all(_p2[_n].kind is _insp.Parameter.POSITIONAL_ONLY for _n in ("text", "key", "default")),
      str({_n: str(_p2[_n].kind) for _n in _p2}))
check("★ 槽位名叫 key 也能渲染（未注入路径）",
      render_via(None, "k", "X {key} {name}", key="A", name="B") == "X A B")
check("★ 槽位名叫 key 也能渲染（注入表路径：不炸 + 取自表）",
      render_via(_Holder(_Stub({"k": "T"})), "k", "D", key="A") == "T")
check("★ 真 TextTable 同款（key 同名槽位）",
      TextTable({"k": "T {key}"}).render_or("k", "D", key="A") == "T A")

print()
print("【6. gauge 文案口：模块级 bar_gain / bar_trigger 收注入表（text=）】")
_saved_bar = (G.bar_def, G.bar_should_trigger, G.bar_trigger)
G.bar_def = lambda k: {"name": "破绽", "max": 100, "threshold_base": 10,
                       "trigger_effect": "skip_turn"}
_tbl = TextTable({"battle.gauge.gain": "／表：{bar} +{add}（{val}/{maxcap}）"})
_e1 = {"effects": {}}
_lg = []
G.bar_gain(_e1, "shaken", 5, _lg, now=0.0, text=_tbl)
check("★ 注入表 → 积蓄行取自表（gauge 的 text= 链通）",
      _lg == ["／表：shaken +5（5/100）"], _lg)
_e2 = {"effects": {}}
_lg = []
G.bar_gain(_e2, "shaken", 15, _lg, now=0.0, text=_tbl)
G.bar_trigger(_e2, "shaken", _lg, now=0.0, text=_tbl)
check("★ 表只声明一条 → 未声明的 key 回落兜底模板逐字",
      _lg[-1] == "💢 【破绽】触发！(第 1 次)", _lg)
_e3 = {"effects": {}}
_lg = []
G.bar_gain(_e3, "shaken", 5, _lg, now=0.0)
check("未注入 → 积蓄行逐字 == 搬运前文案",
      _lg == ["💥 shaken 积蓄 +5（5/100）"], _lg)
G.bar_def, G.bar_should_trigger, G.bar_trigger = _saved_bar


class _Holder1:
    """只带 `text` 一个字段的持有者（= Battle 的注入面形状）。"""

    def __init__(self, text):
        self.text = text


check("text_of 与 render_via 同源：读同一处 `.text`",
      text_of(_Holder1(_tbl)) is _tbl
      and render_via(_Holder1(_tbl), "battle.gauge.gain", "D", bar="b", add=1, val=2, maxcap=3)
      == "／表：b +1（2/3）")
check("text_of(None) / 无 text 替身 → None（未注入）",
      text_of(None) is None and text_of(object()) is None)

# ---------------------------------------------------------------- 7. 续战/恢复路径
print()
print("【7. 续战 / 面板恢复：from_state(text=…) 同口径注入（注入不停在首战）】")
_b7, _p7, _e7 = _setup(text=_Stub({"battle.landing.damage": "／表：续战伤害"}))
_st7 = _b7.to_state()
check("to_state 不落文案表（表不可 JSON 化；state 顶层与 actor 内都无 text）",
      "text" not in _st7 and all("text" not in a for acts in _st7["sides"].values() for a in acts),
      sorted(_st7)[:6])
_sig7 = _insp.signature(Battle.from_state).parameters
check("★ from_state 的 text 为关键字专属（不留位置参数口子）",
      "text" in _sig7 and _sig7["text"].kind is _insp.Parameter.KEYWORD_ONLY,
      str({_n: str(_pp.kind) for _n, _pp in _sig7.items()}))
_c7 = Battle.from_state(_st7, text=_Stub({"battle.landing.damage": "／表：续战伤害"}))
_lg7 = []
random.seed(7)
landing.deal_damage(_c7, None, _c7.sides_of("enemy")[0], 3, _lg7)
check("★ 恢复带 text= ⇒ 续战日志取自表（注入链不断在 from_state）",
      _lg7 == ["／表：续战伤害"], _lg7)
_c8 = Battle.from_state(_st7)
check("恢复不传 text ⇒ .text is None（未注入）", _c8.text is None)
_lg8 = []
random.seed(7)
landing.deal_damage(_c8, None, _c8.sides_of("enemy")[0], 3, _lg8)
check("未注入恢复 ⇒ 逐字节 == 兜底模板（历史内联串）",
      _lg8 == ["💥 房间怪 受到 3 点伤害！"], _lg8)
from saintess_engine import from_state as _fs_mod                            # noqa: E402
check("模块级 from_state 同款（text= 关键字透传）",
      _fs_mod(_st7, text=_Stub({"battle.landing.damage": "／表：模块级"})).text is not None)

print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
sys.exit(1 if failed else 0)
