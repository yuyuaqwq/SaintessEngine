#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：吸血衰减倍率**由内容侧声明**驱动，引擎零游戏知识（台账 L250 · 中 · 审计批次2）。

它守的是什么
------------------------------------------------------------------
改前 `ext_combat/battle/actions.py::_mortal_wound_mult` 里：

    mw = ef.get("mortal_wound")     # ← 引擎写死一个**减益键名**
    ...
    return 0.5                       # ← 引擎写死一个**倍率**

docstring 还自承「Boss『重创』（mortal_wound）」—— 引擎因此**认识一个 Boss 概念**。
换一款游戏、换一种减益名，引擎都得跟着改代码（第二款游戏判据挂在那）。

改后：引擎遍历 actor 身上**全部**已施加的 effects 条目，逐条问声明
`EFFECT_RULES[key]["lifesteal_mult"]`，取最衰减那档；**没声明 = 不适用 = 1.0**。
与本文件同形的既有先例：`actions.py` 里 `cd_mult` 那一段（同读口 `state_def`）。

判据
------------------------------------------------------------------
① 引擎源码里**零游戏名词**：`"mortal_wound"` 不作为字面量出现在
   `actions.py` 的可执行代码里（注释/docstring 不算 —— 用 AST 数，不要裸 grep）。
② 声明驱动：换声明值 ⇒ 倍率跟着变（引擎代码零改动）。
③ 新增减益免改引擎：临时往表里加一条**从没见过的** key 声明 0.8 ⇒ 生效。
④ 没声明 = 不适用：未声明的 key ⇒ 1.0；已过期条目 ⇒ 1.0；多条命中取最衰减。
⑤ 有牙（反证前提）：改前那一版（写死键名 + 写死 0.5）会被 ① 逮到。

跑法：`python tests/test_lifesteal_mult_declared.py`；退出码 0 = 全绿 · 1 = 有失败。
"""
import ast
import io
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
for _p in (ROOT, os.path.join(ROOT, "extends")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from _check import bind_check  # noqa: E402

from extends.ext_combat.battle import actions as A              # noqa: E402
from extends.ext_combat.battle import state_effects as SE       # noqa: E402

# ★ 引擎仓单跑没有内容包 —— 判据 §2/§3/§4 要问的是**内容侧声明**，所以本文件自己装
#   一份最小声明表（不 import 内容包，跨仓依赖会让门禁随包仓红绿漂）。
#   形状照 orlandia `content/rules/effect_rules.json` 的相关条目逐字裁剪。
GAME_KEY = "mortal_wound"
_MINI = {
    GAME_KEY: {"cap": 1, "tag": GAME_KEY, "negative": True, "lifesteal_mult": 0.5},
}

passed = failed = 0
DETAIL = []
check = bind_check(globals(), "passed", "failed", "DETAIL")

_ACT_PATH = os.path.join(ROOT, "extends", "ext_combat", "battle", "actions.py")


class _B:
    """战斗替身：`_mortal_wound_mult` 只读 `battle._now`。"""

    def __init__(self, now=0.0):
        self._now = now


def _actor(effects):
    return {"effects": effects, "level": 10}


# 装最小声明表。★ 取件口是 `game_config.load_game_rules(module)`（内容侧正式装法），
#   **不是**直接改 `get_effect_rules()` 的返回值 —— 后者是 `config` 里的引用，
#   改返回值等于改副本，生产路径读不到（2026-09-29 自己踩过：判据全红而生产是对的）。
from extends.ext_combat.battle import game_config as _GC   # noqa: E402
from saintess_engine import config as _CFG                 # noqa: E402


class _MiniRules:
    """形状 = 内容侧规则模块（`load_game_rules` 只认 `EFFECT_RULES` / `EFFECT_ACTIONS` 两个属性）。"""

    EFFECT_RULES = _MINI
    EFFECT_ACTIONS = {}


_BASE_SNAP = _GC.get_effect_rules()
_GC.load_game_rules(_MiniRules)
_tbl = _GC.get_effect_rules()          # 装完**现取**（不是改返回值）


# ---------------------------------------------------------------- (1) 引擎零游戏名词
print("【1. 引擎源码里零游戏名词（AST 数可执行代码；注释/docstring 不算）】")
_src = io.open(_ACT_PATH, encoding="utf-8").read()
_tree = ast.parse(_src)
_hits = []
for _n in ast.walk(_tree):
    # ① 裸字符串字面量 "mortal_wound"
    if isinstance(_n, ast.Constant) and _n.value == GAME_KEY:
        _hits.append("str:%d" % _n.lineno)
    # ② ef.get("mortal_wound") / effects["mortal_wound"] 这类下标/取值
    if isinstance(_n, ast.Attribute) and _n.attr == GAME_KEY:
        _hits.append("attr:%d" % _n.lineno)
check("`actions.py` 的可执行代码里 `%s` 零出现（键名不写死在引擎）" % GAME_KEY,
      not _hits, repr(_hits[:5]))
check("★ 引擎仍认得这个**机制**：`_declared_lifesteal_mult` + `_mortal_wound_mult` 都在",
      hasattr(A, "_declared_lifesteal_mult") and hasattr(A, "_mortal_wound_mult"))

# ---------------------------------------------------------------- (2)(3) 声明驱动
print(chr(10) + "【2. 换声明值 ⇒ 倍率跟着变（引擎代码零改动）】")
_saved = dict(_tbl.get(GAME_KEY) or {})
if not _saved:
    check("⚠ 本文件自装的最小声明表里没有 `%s`" % GAME_KEY, False, "未声明")
else:
    try:
        check("基线：声明了 %r ⇒ 倍率就是它" % _saved.get("lifesteal_mult"),
              A._mortal_wound_mult(_B(), _actor({GAME_KEY: {"stacks": 1, "expire": 99.0}}))
              == float(_saved["lifesteal_mult"]))
        _tbl[GAME_KEY]["lifesteal_mult"] = 0.25
        check("声明改成 0.25 ⇒ 倍率逐字变 0.25（证明读的是声明，不是写死）",
              A._mortal_wound_mult(_B(), _actor({GAME_KEY: {"stacks": 1, "expire": 99.0}})) == 0.25)
    finally:
        _tbl[GAME_KEY].update(_saved)

print(chr(10) + "【3. 新增一种减益：只加一行声明，引擎代码零改动即生效】")
NEWKEY = "gate_probe_new_debuff_never_seen"
check("先确认这个 key 现在**没**在表里（防上一轮残留）", NEWKEY not in _tbl)
try:
    _tbl[NEWKEY] = {"lifesteal_mult": 0.8}
    check("临时加一行声明 0.8 ⇒ 生效",
          A._mortal_wound_mult(_B(), _actor({NEWKEY: {"stacks": 1}})) == 0.8)
    check("★ 且不影响别的条目（未声明的 key 仍是 1.0）",
          A._mortal_wound_mult(_B(), _actor({"some_unrelated": {"stacks": 1}})) == 1.0)
finally:
    _tbl.pop(NEWKEY, None)

# ---------------------------------------------------------------- (4) 边界口径
print(chr(10) + "【4. 没声明 = 不适用 / 过期不算 / 多条取最衰减】")
check("身上一个 effects 都没有 ⇒ 1.0", A._mortal_wound_mult(_B(), _actor({})) == 1.0)
check("effects 为 None ⇒ 1.0", A._mortal_wound_mult(_B(), {"effects": None}) == 1.0)
check("未声明的 key ⇒ 1.0（零兜底，不猜）",
      A._mortal_wound_mult(_B(), _actor({"never_declined_xyz": {"stacks": 1}})) == 1.0)
check("非 dict 条目被跳过 ⇒ 1.0", A._mortal_wound_mult(_B(), _actor({"weird": 5})) == 1.0)
check("已过期条目（now >= expire）⇒ 1.0",
      A._mortal_wound_mult(_B(now=10.0), _actor({GAME_KEY: {"stacks": 1, "expire": 5.0}})) == 1.0)
check("未过期条目（now < expire）⇒ 生效",
      A._mortal_wound_mult(_B(now=1.0), _actor({GAME_KEY: {"stacks": 1, "expire": 5.0}}))
      == float(_saved.get("lifesteal_mult", 0.5)))
try:
    _tbl[GAME_KEY]["lifesteal_mult"] = 0.5
    _tbl["gate_probe_other"] = {"lifesteal_mult": 0.6}
    check("两条同时命中 ⇒ 取**最衰减**那档（0.5）",
          A._mortal_wound_mult(_B(), _actor(
              {GAME_KEY: {"stacks": 1}, "gate_probe_other": {"stacks": 1}})) == 0.5)
    check("已过期那条不参与取 min",
          A._mortal_wound_mult(_B(now=99.0), _actor(
              {GAME_KEY: {"stacks": 1, "expire": 1.0}, "gate_probe_other": {"stacks": 1}})) == 0.6)
finally:
    _tbl.pop("gate_probe_other", None)
    _tbl[GAME_KEY].update(_saved)

# ---------------------------------------------------------------- (5) 现场恢复
print(chr(10) + "【5. 现场恢复：临时 key 全部撤净、表值复原】")
check("临时 key `gate_probe_new_debuff_never_seen` 已撤", NEWKEY not in SE.all_state_effects())
check("临时 key `gate_probe_other` 已撤", "gate_probe_other" not in SE.all_state_effects())
_GC.load_game_rules(type("_Restore", (), {"EFFECT_RULES": _BASE_SNAP, "EFFECT_ACTIONS": {}}))
check("★ 整张声明表已复原成跑之前那张（本文件不留现场）",
      _GC.get_effect_rules() == _BASE_SNAP, "键集差 %s" % sorted(set(_GC.get_effect_rules()) ^ set(_BASE_SNAP)))

print(chr(10) + "=" * 56)
print("通过 %d · 失败 %d" % (passed, failed))
for _d in DETAIL:
    print("  " + _d)
sys.exit(1 if failed else 0)
