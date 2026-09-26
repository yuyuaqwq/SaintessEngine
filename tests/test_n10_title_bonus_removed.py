#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：N10 收口 —— battle 级 `title_bonus` 不许回归（唯一容器 = per-actor `bonus.panel`）。

为什么要有它（2026-09-26 · P-1）
------------------------------------------------------------------
外部面板增幅历史上走过**两条路**（E5-3 的过渡语义）：

  ① per-actor `actor["bonus"]["panel"]` —— N5b4-4 鱼鱼拍板**正式容器**；内容侧开战装配
     （`bridge.apply_battle_loadout`）写入、随 actor 落盘/恢复。
  ② battle 级 `Battle(title_bonus=…)` → `battle.title_bonus` —— 旧「野外单玩家整场一份」
     语义；`stats._player_base_stats` 曾写 `actor.bonus.panel or battle.title_bonus or {}`，
     即 **① 为空时才读到 ②**。

两条路都活 = 任何一处「只喂了 ②」的调用点都会被静默兜住（看不懂来源在哪）。N10 把这
条过渡语义整条删掉：构造形参、实例字段、存档键、回落分支四件全去。本文件把「删干净」
钉成判据 —— 谁把任一件加回来，这里当场红。

判据
------------------------------------------------------------------
① **形参面**：`Battle.__init__` 形参表无 `title_bonus`。
② **字段面**：实例上无 `title_bonus`（`hasattr` False）。
③ **读源面（有牙）**：配一个 `panel_fn` 桩，造**带 `bonus.panel`** 的 class actor ——
   面板必须**只**认 actor 那份；再给 battle 硬塞 `battle.title_bonus = {...}`（不同值），
   解析结果必须**一个字不变**（回归 = 又多了个隐蔽读源）。
④ **存档面**：`to_state` 不写 `"title_bonus"` 键；`from_state` 读**带该键的旧档**照旧能起
   （未知键忽略），且 旧档 → 新档 → 再往返 的值域幂等（逐字段相同）。
⑤ **源码面**：`extends/ext_combat/**` 里 `title_bonus` **不许作为属性名出现**
   （`.title_bonus` 零处）、`Battle.__init__` 的参数里也不许 —— 注释/文档串里提它不算
   （`serialize._deserialize_actor` 的 **actor 级旧名迁移** `actor.get("title_bonus")` /
   `actor.pop("title_bonus", None)` 是**另一件事**：那是存档里 actor 自己的旧键，
   与 battle 级容器无关，保留）。
⑥ **构造签名面（同批收口）**：`Battle.__init__` 不再有 `**kwargs` —— 签名之外的实参
   **当场 TypeError**。这是把「传了但引擎不读」的静默参（`title_bonus=`/`pet=`/
   `dmg_mult=`/`st=`）钉死的根因判据：只要 `**kwargs` 回来，静默吞就又成立了。

跑法：`python tests/test_n10_title_bonus_removed.py`；退出码 0 = 全绿 · 1 = 有失败。
"""
import ast
import copy
import io
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
for _p in (ROOT, os.path.join(ROOT, "extends")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ext_combat import Battle, make_actor                        # noqa: E402
from ext_combat.battle import stats as _S                        # noqa: E402
from saintess_engine import config as _cfg                       # noqa: E402

passed = failed = 0
DETAIL = []

from _check import bind_check  # noqa: E402

check = bind_check(globals(), "passed", "failed", "DETAIL")

BATTLE_PY = os.path.join(ROOT, "extends", "ext_combat", "battle", "battle.py")
STATS_PY = os.path.join(ROOT, "extends", "ext_combat", "battle", "stats.py")


# ---------------------------------------------------------------- 面板桩
def _stub_panel_fn(class_name, level, equipment, tier, attributes, evolve_path,
                   panel_bonus, race):
    """最小 `panel_fn`：基础面板 + 传入的 `panel_bonus`（= actor 那份）flat 加值。

    ★ 形参名沿用引擎注入面契约（`config._HOOKS["panel_fn"]` 的注释签名）：内容侧的面板
      公式**本来就叫这个名**，与本任务删掉的「battle 级容器」不是一个东西。
    """
    base = {"max_hp": 500, "atk": 100, "def": 10, "spd": 10, "crit": 0.05}
    for k, v in (panel_bonus or {}).items():
        base[k] = base.get(k, 0) + v
    return base


_cfg.set_hook("panel_fn", _stub_panel_fn)


def _mk_scene(panel):
    """一场最小战斗：1 个 class 玩家（可带 `bonus.panel`）+ 1 只纯怪。返回 (b, pa, ea)。"""
    pa = make_actor("p1", "甲", "player", kind="player", human_controlled=True,
                    class_name="probe_cls", level=1)
    if panel is not None:
        pa["bonus"] = {"panel": dict(panel), "cap": {}, "cost": {}}
    ea = make_actor("e1", "怪", "enemy", kind="monster", hp=9999, max_hp=9999,
                    atk=1, spd=5)
    b = Battle(btype="monster", sides={"player": [pa], "enemy": [ea]}, seed_ct=False)
    return b, pa, ea


print("【1. 形参面 / 字段面：Battle 不再有 title_bonus】")
b0, pa0, _ = _mk_scene({"atk": 7})
check("`Battle.__init__` 形参表无 title_bonus",
      "title_bonus" not in Battle.__init__.__code__.co_varnames,
      repr(Battle.__init__.__code__.co_varnames))
check("实例上无 title_bonus 字段", not hasattr(b0, "title_bonus"),
      "hasattr=True（有人在 __init__ 里把它加回来了）")
check("`Battle.from_state` 重建实例同样无该字段",
      not hasattr(Battle.from_state(b0.to_state()), "title_bonus"))

print("\n【2. 读源面（有牙）：面板只认 actor.bonus.panel】")
st_a = _S.actor_stats(b0, pa0)
check("带 bonus.panel 的 actor：atk = 100(基础) + 7(panel)", int(st_a.get("atk", 0)) == 107,
      "atk=%s" % st_a.get("atk"))
# 硬塞回同名实例字段（不同值）⇒ 面板必须一个字都不变
b0.title_bonus = {"atk": 90, "spd": 90, "max_hp": 900}
st_b = _S.actor_stats(b0, pa0)
check("硬塞 `battle.title_bonus` 后面板逐字段不变（无隐蔽读源）",
      dict(st_a) == dict(st_b),
      "atk %s→%s · spd %s→%s" % (st_a.get("atk"), st_b.get("atk"),
                                 st_a.get("spd"), st_b.get("spd")))
b1, pa1, _ = _mk_scene(None)          # 无 bonus 容器
b1.title_bonus = {"atk": 90}
st_c = _S.actor_stats(b1, pa1)
check("无 bonus 容器的 actor 也不吃 battle 级残留字段（面板 = 基础 100）",
      int(st_c.get("atk", 0)) == 100, "atk=%s" % st_c.get("atk"))
check("两态可区分：有容器 107 / 无容器 100（判据不是恒真）",
      int(st_a.get("atk", 0)) != int(st_c.get("atk", 0)))

print("\n【3. 存档面：新档不写该键；旧档（带键）照旧能起】")
b2, pa2, _ = _mk_scene({"spd": 3})
st_new = b2.to_state()
check('`to_state` 不再写 "title_bonus" 键', "title_bonus" not in st_new,
      str(sorted(st_new.keys())))
st_old = dict(st_new)
st_old["title_bonus"] = {"atk": 9999, "spd": 9999}      # 旧档（旧引擎必然写这键）
check("造出的旧档确实带该键（对照不许空跑）", "title_bonus" in st_old)
b_old = Battle.from_state(json.loads(json.dumps(st_old)))       # 旧档必须照旧能起
pa_old = b_old.sides_of("player")[0]
check("旧档恢复成功（btype/sides 都在）",
      b_old.btype == "monster" and len(b_old.sides_of("player")) == 1)
check("旧档恢复后实例仍无 title_bonus 字段", not hasattr(b_old, "title_bonus"))
check("旧档恢复后 actor 那份 bonus.panel 原样（数值真源在 actor 上）",
      ((pa_old.get("bonus") or {}).get("panel") or {}) == {"spd": 3},
      repr(pa_old.get("bonus")))
check("旧档恢复后面板 spd = 13（10 基础 + 3 来自 actor，不吃档里那份 9999）",
      int(_S.actor_stats(b_old, pa_old).get("spd", 0)) == 13,
      "spd=%s" % _S.actor_stats(b_old, pa_old).get("spd"))
rt1 = Battle.from_state(b_old.to_state()).to_state()
rt2 = Battle.from_state(rt1).to_state()
check("往返幂等（旧档 → 新档 → 新档，逐字段相同）", rt1 == rt2)
check("往返后仍无该键", "title_bonus" not in rt1 and "title_bonus" not in rt2)
# 旧引擎读新档的等价面：`st.get("title_bonus") or {}` 语义 = 缺键即 {}，不炸
check("新档在新引擎上恢复（缺键路径）不炸",
      Battle.from_state(copy.deepcopy(st_new)).btype == "monster")

print("\n【4. 源码面：extends/ext_combat/** 里 `.title_bonus` 零处 / 形参零处】")
attrs = []
args = []
for _root, _dirs, _files in os.walk(os.path.join(ROOT, "extends", "ext_combat")):
    _dirs[:] = [d for d in _dirs if d != "__pycache__"]
    for _f in _files:
        if not _f.endswith(".py"):
            continue
        _p = os.path.join(_root, _f)
        _tree = ast.parse(io.open(_p, encoding="utf-8").read(), filename=_p)
        for n in ast.walk(_tree):
            if isinstance(n, ast.Attribute) and n.attr == "title_bonus":
                attrs.append("%s:%d" % (os.path.relpath(_p, ROOT), n.lineno))
            if isinstance(n, ast.arg) and n.arg == "title_bonus":
                args.append("%s:%d" % (os.path.relpath(_p, ROOT), n.lineno))
check("`.title_bonus` 属性访问零处（battle / 别处都不许）", not attrs, str(attrs))
check("`title_bonus` 作为形参零处（`Battle.__init__` 的形参不许回归）", not args, str(args))
_src = io.open(STATS_PY, encoding="utf-8").read()
check("`stats._player_base_stats` 的读源行是「只读 actor 容器」",
      '_tb = (actor.get("bonus") or {}).get("panel") or {}' in _src,
      "读源行变了")
check("`stats.py` 里 `getattr(battle` 零处（battle 级回落的下落口）",
      "getattr(battle" not in _src, "残留 getattr(battle, …)")
_bsrc = io.open(BATTLE_PY, encoding="utf-8").read()
check('`battle.py` 里 `self.title_bonus` 零处', "self.title_bonus" not in _bsrc)
check('`serialize.py` 的 **actor 级**旧名迁移仍在（另一件事，不许顺手删）',
      'actor.get("title_bonus")' in io.open(
          os.path.join(ROOT, "extends", "ext_combat", "battle", "serialize.py"),
          encoding="utf-8").read())

print("\n【5. 构造签名面：无 `**kwargs`，签名之外的实参当场 TypeError】")
_SIG_NArg = Battle.__init__.__code__.co_argcount     # 只含位置/关键字参数（不含 *args/**kwargs）
_VARNAMES = Battle.__init__.__code__.co_varnames[:_SIG_NArg]
check("`Battle.__init__` 形参表无 `kwargs`（`**kwargs` 静默吞已去）",
      "kwargs" not in Battle.__init__.__code__.co_varnames, str(_VARNAMES))
for _bad_kw in ({"title_bonus": {"atk": 1}}, {"pet": {}}, {"dmg_mult": 2.0}, {"st": 1}):
    _name = next(iter(_bad_kw))
    _hit = None
    try:
        Battle("monster", sides={"player": [], "enemy": []}, **_bad_kw)
    except TypeError as _exc:
        _hit = str(_exc)
    check("幽灵参数 %s= 不再被静默吞（当场 TypeError）" % _name,
          _hit is not None and _name in _hit, "未抛：静默吞回来了")
check("真参数照旧能传（text= / hostile_map= 不误伤）",
      Battle("monster", sides={"player": [], "enemy": []},
             hostile_map={"player": ["enemy"]}, text=None).hostile_map == {"player": ["enemy"]})

print("\n结果：通过 %d / 共 %d" % (passed, passed + failed))
if failed:
    print("失败项：")
    for x in DETAIL:
        print("  · %s" % x)
    sys.exit(1)
