#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：表现事件（cue）形状 —— 订阅表 / 装配期对账 / emit 硬规矩 / 端到端 / **B2 判据**。

为什么需要它（cue 解耦 B1 + B2）
-------------------------------
结算函数原先「算值 → 选模板 → 填槽位 → 决定顺序」写在同一条语句里。cue 解耦把
「玩家看到什么」从结算里拆出来：结算只发事实，表现由订阅方渲染（`saintess_engine/cues.py`）。
拆出来的同时必须钉住几件事，否则解耦会静默地改变玩家看到的东西：

  1. **装配期对账有牙**：已声明的 cue 缺订阅 / 订阅表里有引擎不认的名字 /
     同一 cue 声明 ≥2 个 text 订阅者 ⇒ **抛**（不是警告）；
  2. **运行期 fail-closed**：`emit` 时该 cue 没有订阅者 ⇒ 抛（`strict=False` 诊断面才降级成一行坏数据）；
  3. **只读契约 + 坏回执**：`call` 订阅者产出日志行必须显式声明 `emits_lines`；
     回执形状不是 None/str/序列 ⇒ 抛；payload 必须**只读**（引擎给副本）；
  4. **端到端**：真调用点（`landing` 的闪避 / 元素免疫 / 伤害落地…）在装配了订阅表之后
     **真的走 emit**，输出**逐字节等于**迁移前那句文案（现在从内容侧文案表取）；
  5. **★ B2「文案必须命中」**（本文件 §7）：已迁移点位的引擎模板**已删净** ⇒
     表里没有该 key **报错**（诊断 + 一行可读坏数据），**绝不回落任何引擎措辞**；
     并且「模板串是否真删净」用静态扫描钉住（不是靠自觉）。

跑法：python tests/test_cues_shape.py（exit=0 全绿）
"""
from __future__ import annotations

import ast
import importlib
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_ROOT, os.path.join(_ROOT, "extends"), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from saintess_engine import config as CFG                                   # noqa: E402
from saintess_engine.cues import (MISS_LINE, CueBus, CueContractError,      # noqa: E402
                                  audit_subs, build_bus, normalize_subs)
from saintess_engine.text import TextTable, extract_params, safe_format     # noqa: E402
from ext_combat.battle.cues import CUE_NAMES                                # noqa: E402
from _cue_text_fixture import SUBS as FIX_SUBS                              # noqa: E402
from _cue_text_fixture import TEMPLATES as FIX_TEMPLATES                    # noqa: E402
from _cue_text_fixture import TEXT as FIX_TEXT                              # noqa: E402

passed = failed = 0

from _check import bind_check  # noqa: E402

check = bind_check(globals(), "passed", "failed")

BATTLE_DIR = os.path.join(_ROOT, "extends", "ext_combat")
CUES_FILE = os.path.join(BATTLE_DIR, "battle", "cues.py")


def _emit_calls_in_cues() -> list:
    """`cues.py` 里的 `bus.emit(logs, name, …)` 直发点 → `[(函数名, 行号, 源码)]`。

    ★ 判别方式：实参里出现**名字就叫 `name` 的形参**。早先写成
    `isinstance(args[1], ast.Constant) and args[1].value == "name"` —— `name` 在真代码里
    是 `ast.Name` 不是字面量 ⇒ 扫到 0 处 ⇒ 这条静态门禁恒绿（假绿）。已修。
    """
    out = []
    for fn in [n for n in ast.parse(open(CUES_FILE, encoding="utf-8").read()).body
               if isinstance(n, ast.FunctionDef)]:
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "emit" and len(node.args) == 3):
                continue
            if not (isinstance(node.args[1], ast.Name) and node.args[1].id == "name"):
                continue
            out.append((fn.name, node.lineno, ast.unparse(node)))
    return out


def _ast_all_ext_combat() -> list:
    """扫 `ext_combat` 全包（`battle/cues.py` 除外）的 `bus.emit(...)` 直发点。

    保护什么：`cue()` 是补时刻的**唯一**出口。只要有第二处直接 emit（有人为了「省一步」
    自己 emit 了一条），那一支就绕过补格 ⇒ 包侧的 `{t}` 在那条点位上变成字面量。
    这条门禁是**加强**方向的：它现在会红，不放松。
    """
    out = []
    for dirpath, _dirs, files in os.walk(BATTLE_DIR):
        for fn in sorted(files):
            if not fn.endswith(".py") or fn.startswith("test_"):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, BATTLE_DIR).replace("\\", "/")
            if rel == "battle/cues.py":
                continue          # 那一处已由上一条 check 单独钉住（就应该是它）
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "emit" and len(node.args) == 3):
                    continue
                if not (isinstance(node.args[1], ast.Name) and node.args[1].id == "name"):
                    continue
                out.append("%s:%d %s" % (rel, node.lineno, ast.unparse(node)))
    return out


def _S_count() -> int:
    """跑一遍「零静默兜底」扫描器，返回 `ext_combat` 里 S 类（静默吞）的条数。

    为什么在这里复跑它：本车道给 `now_of` 加了一个 `except`（脏时钟 ⇒ 给 0），
    那条门禁（`tests/test_no_silent_fallback.py`）会扫到它。把它的判据借过来当场量一次，
    是为了**不让「加了 except」这件事悄悄依赖另一个车道的运行顺序**（并行跑时看不到）。
    """
    import subprocess
    res = subprocess.run([sys.executable, os.path.join(_HERE, "test_no_silent_fallback.py")],
                         capture_output=True, text=True, encoding="utf-8")
    out = (res.stdout or "") + (res.stderr or "")
    # 口径行形如「… 白名单 X=12 · ★静默兜底 S=0」（**没有**空格）—— 正则取 S= 后面那个数。
    import re
    for line in out.splitlines():
        if "静默兜底" not in line or "=" not in line:
            continue
        m = re.search(r"S\s*=\s*(\d+)", line)
        if m:
            return int(m.group(1))
    return -1                      # 读不到口径行 = 门禁本身炸了 = 当红


def _raises(fn, exc=CueContractError):
    """跑 `fn`，期待抛 `exc`；返回异常消息（没抛返回 None）。"""
    try:
        fn()
    except exc as e:
        return str(e)
    except Exception as e:                                   # noqa: BLE001
        return "<别的异常 %s: %s>" % (type(e).__name__, e)
    return None


# ============================================================
# 1. 订阅表规范化（形状不对 = 当场现形）
# ============================================================
print("\n【1. 订阅表规范化】")
check("★ 合规表 → 规范化成 {名: (订阅者,)}",
      normalize_subs({"a": {"kind": "text", "key": "a"}}) == {"a": ({"kind": "text", "key": "a"},)},
      str(normalize_subs({"a": {"kind": "text", "key": "a"}})))
check("非映射（列表）⇒ 抛", _raises(lambda: normalize_subs(["a"])) is not None)
check("空名字 ⇒ 抛", _raises(lambda: normalize_subs({"": {"kind": "text", "key": "k"}})) is not None)
check("未知 kind ⇒ 抛", _raises(lambda: normalize_subs({"a": {"kind": "sound"}})) is not None)
check("text 缺 key ⇒ 抛", _raises(lambda: normalize_subs({"a": {"kind": "text"}})) is not None)
check("call 的 handler 是字符串（没解析）⇒ 抛",
      _raises(lambda: normalize_subs({"a": {"kind": "call", "handler": "pkg.mod:fn"}})) is not None)
check("空订阅者序列 ⇒ 抛", _raises(lambda: normalize_subs({"a": ()})) is not None)

# ============================================================
# 2. 装配期对账（三种缺口都要有牙）
# ============================================================
print("\n【2. 装配期对账】")
_NAMES = ("x.a", "x.b", "x.c")
_ok = {"x.a": {"kind": "text", "key": "x.a"}, "x.b": {"kind": "text", "key": "x.b"},
       "x.c": {"kind": "text", "key": "x.c"}}
check("齐全 ⇒ 零问题", audit_subs(_NAMES, normalize_subs(_ok)) == [],
      str(audit_subs(_NAMES, normalize_subs(_ok))))
_miss = dict(_ok)
_miss.pop("x.b")
_p = audit_subs(_NAMES, normalize_subs(_miss))
check("★ 缺订阅 ⇒ 点名缺口 + 条数", len(_p) == 1 and "x.b" in _p[0] and "共 1 条" in _p[0], str(_p))
_p2 = audit_subs(_NAMES, normalize_subs(dict(_ok, **{"x.zzz": {"kind": "text", "key": "k"}})))
check("★ 订阅表里有引擎不认的名字 ⇒ 现形", len(_p2) == 1 and "x.zzz" in _p2[0], str(_p2))
_p3 = audit_subs(_NAMES, normalize_subs(dict(_ok, **{"x.a": (
    {"kind": "text", "key": "x.a"}, {"kind": "text", "key": "x.a2"})})))
check("★ 同一 cue 两个 kind=text ⇒ 现形（一行会变多行）",
      len(_p3) == 1 and "kind=text" in _p3[0], str(_p3))

# ============================================================
# 3. emit 三条硬规矩（同步就地 / 只读契约 / 坏回执）+ 文案必须命中
# ============================================================
print("\n【3. emit：同步就地 · 只读契约 · 坏回执 · 文案必须命中】")
_seen: list = []


def _probe(payload):
    _seen.append(payload)
    return None


class _Table:
    """鸭子类型同内容侧文案表（`render_or(key, default, **slots)` + 命中判定 `in`）。"""

    def __init__(self, mapping):
        self.mapping = dict(mapping)

    def __contains__(self, key):
        return key in self.mapping

    def render_or(self, key, default, /, **slots):
        tpl = self.mapping.get(key, default)
        return tpl.format(**slots) if slots else tpl


_bus = CueBus(normalize_subs({
    "x.a": ({"kind": "text", "key": "x.a"}, {"kind": "call", "handler": _probe}),
}), table=_Table({"x.a": "T:{n}"}))
_logs: list = ["头"]
_bus.emit(_logs, "x.a", {"n": 7})
check("★ 就地 append + 顺序 = 订阅者声明序（先 text 后 call，头行不动）",
      _logs == ["头", "T:7"], str(_logs))
check("call 订阅者的回执 None ⇒ 不产出行", len(_seen) == 1 and _seen[0] == {"n": 7}, str(_seen))

_ret_ok = CueBus(normalize_subs({"x.a": {"kind": "call", "handler": lambda p: ["行1", "行2"],
                                          "emits_lines": True}}))
_l2: list = []
_ret_ok.emit(_l2, "x.a", {})
check("call + emits_lines=True ⇒ 回执逐条 append（不是拼成一行）", _l2 == ["行1", "行2"], str(_l2))

check("★ call 产出日志行却没声明 emits_lines ⇒ 抛（只读契约）",
      _raises(lambda: CueBus(normalize_subs(
          {"x.a": {"kind": "call", "handler": lambda p: "偷偷加一行"}}
      )).emit([], "x.a", {})) is not None)
check("★ 坏回执（返回 int）⇒ 抛", _raises(lambda: CueBus(normalize_subs(
    {"x.a": {"kind": "call", "handler": lambda p: 3, "emits_lines": True}}
)).emit([], "x.a", {})) is not None)

_payload = {"n": 1}
_cap: list = []


def _peek(p):
    _cap.append(p)
    p["n"] = 999          # 订阅者乱改：引擎给的必须是**副本**
    return None


CueBus(normalize_subs({"x.a": {"kind": "call", "handler": _peek}})).emit([], "x.a", _payload)
check("★ payload 只读（引擎给副本：订阅者改它不影响调用方）",
      _cap[0] is not _payload and _payload == {"n": 1},
      "副本=%s 原件=%s 同一个对象=%s" % (_cap[0], _payload, _cap[0] is _payload))

_nostrict = CueBus({}, strict=False)
_l3: list = []
_nostrict.emit(_l3, "x.a", {})
check("★ strict=False（诊断面）⇒ 不崩：中性坏数据行 + 问题落 problems（机器名不进玩家面）",
      _l3 == [MISS_LINE] and any("x.a" in p for p in _nostrict.problems),
      "%s / %s" % (_l3, _nostrict.problems))
try:
    CueBus({}, strict=True).emit([], "x.a", {})
    _strict_raised = None
except Exception as e:                                       # noqa: BLE001
    _strict_raised = type(e).__name__ + ": " + str(e)
check("★ strict=True 运行期缺订阅 ⇒ 抛 EngineNotConfigured（点名 cue）",
      _strict_raised is not None and "EngineNotConfigured" in _strict_raised
      and "x.a" in _strict_raised, str(_strict_raised))

# ---- ★ B2：kind=text 的渲染是「必须命中内容侧文案表」——缺表/缺 key 一律报错 ----
_miss_bus = CueBus(normalize_subs({"x.a": {"kind": "text", "key": "x.a"}}),
                  table=_Table({"x.other": "别人的行"}))
_lc: list = []
check("★ 表里没这个 key ⇒ 抛（引擎手里没有模板可回落）",
      _raises(lambda: _miss_bus.emit(_lc, "x.a", {"n": 1})) is not None and _lc == [], str(_lc))
_notable = CueBus(normalize_subs({"x.a": {"kind": "text", "key": "x.a"}}), table=None)
check("★ 整张表不在（未注入）⇒ 同样抛（不是「走 default」）",
      _raises(lambda: _notable.emit([], "x.a", {})) is not None)


class _NoHit:
    """只实现 `render_or` 的手写替身：**答不出**「有没有这个 key」。"""

    def render_or(self, key, default, /, **slots):
        return "手写替身:%s" % key


check("★ 表答不出命中（没有 `__contains__`）⇒ 当作没命中（fail-closed，不许当「有」）",
      _raises(lambda: CueBus(normalize_subs(
          {"x.a": {"kind": "text", "key": "x.a"}}), table=_NoHit()).emit([], "x.a", {})) is not None)

_miss_diag = CueBus(normalize_subs({"x.a": {"kind": "text", "key": "x.a"}}),
                    table=_Table({}), strict=False)
_lc2: list = []
_miss_diag.emit(_lc2, "x.a", {"n": 1})
check("★ strict=False ⇒ 不崩：一行可读坏数据 + 问题落 problems（**不是**措辞兜底）",
      _lc2 == [MISS_LINE] and any("x.a" in p for p in _miss_diag.problems),
      "%s / %s" % (_lc2, _miss_diag.problems))

# ---- ★ 审计 L2060：key **命中了**却渲染出空串 —— 原写法 `return [line] if line else []`
#   把整行静默蒸发（logs 行数 0 / problems 空 / strict=True 也不抛），且 `audit_subs`
#   查不出（key 命中了）⇒ 只有真机上那一行不见时才现形。与本模块头注「不静默丢行」
#   「坏数据就地一行可读」自相矛盾。口径 = 与上面「缺 key」**同级**：strict 抛、
#   宽松态记问题 + 出 MISS_LINE（`TextTable.validate()` 早已把「模板为空」列为坏数据）。
_empty_tpl = CueBus(normalize_subs({"x.e": {"kind": "text", "key": "x.e"}}),
                    table=_Table({"x.e": ""}), strict=False)
_le: list = []
_empty_tpl.emit(_le, "x.e", {})
check("★ key 命中但模板为空 ⇒ 出 MISS_LINE 一行（不静默丢行）+ 问题落 problems",
      _le == [MISS_LINE] and any("x.e" in p for p in _empty_tpl.problems),
      "%s / %s" % (_le, _empty_tpl.problems))

check("★ 同上 strict=True ⇒ 抛 CueContractError（点名 cue 名与 key）",
      _raises(lambda: CueBus(normalize_subs({"x.e": {"kind": "text", "key": "x.e"}}),
                             table=_Table({"x.e": ""}), strict=True).emit([], "x.e", {})) is not None)

_notempty = CueBus(normalize_subs({"x.f": {"kind": "text", "key": "x.f"}}),
                   table=_Table({"x.f": "打中 {n} 点"}))
_nl: list = []
_notempty.emit(_nl, "x.f", {"n": 7})
check("★ 反证：非空渲染逐字不变（正常路径不受影响，且 problems 仍为空）",
      _nl == ["打中 7 点"] and not _notempty.problems, "%s / %s" % (_nl, _notempty.problems))

# 槽位给空串时**行仍非空**（模板有字面量）⇒ 属正常渲染，不是坏数据
_slotempty = CueBus(normalize_subs({"x.g": {"kind": "text", "key": "x.g"}}),
                    table=_Table({"x.g": "打中 {n} 点"}))
_sle: list = []
_slotempty.emit(_sle, "x.g", {"n": ""})
check("★ 反证：槽位空但模板有字面量 ⇒ 照常出行、不记问题（不把正常渲染当坏数据）",
      _sle == ["打中  点"] and not _slotempty.problems,
      "%s / %s" % (_sle, _slotempty.problems))

# ---- ★ 审计 L2054：一条 cue 要么整条渲染出来，要么一行都不留 ----
# 原先逐行 append：第二个订阅者的 key 没命中时抛错，第一个订阅者已写进 logs 的
# 真行留了下来（实测 ['第一行:7']）⇒ 半条真行 + 一条坏数据行。
_half = CueBus(normalize_subs({
    "x.a": [{"kind": "text", "key": "x.a"},
            {"kind": "text", "key": "x.missing"}]}),
    table=_Table({"x.a": "第一行:{n}"}))
_hl: list = []
check("★ 中途抛错 ⇒ logs 一行都不留（不是半渲染）",
      _raises(lambda: _half.emit(_hl, "x.a", {"n": 7})) is not None and _hl == [], str(_hl))

_half_tol = CueBus(normalize_subs({
    "x.a": [{"kind": "text", "key": "x.a"},
            {"kind": "text", "key": "x.missing"}]}),
    table=_Table({"x.a": "第一行:{n}"}), strict=False)
_ht: list = []
_half_tol.emit(_ht, "x.a", {"n": 7})
check("★ strict=False 下的半渲染 = 真行 + 一条坏数据行（宽松模式本就出坏数据行）",
      _ht == ["第一行:7", MISS_LINE], str(_ht))

_ok2 = CueBus(normalize_subs({
    "x.a": [{"kind": "text", "key": "x.a"},
            {"kind": "text", "key": "x.b"}]}),
    table=_Table({"x.a": "甲:{n}", "x.b": "乙:{n}"}))
_ol: list = []
_ok2.emit(_ol, "x.a", {"n": 7})
check("全部命中 ⇒ 行序 = 订阅者声明序（先渲染后一次 append 不改序）",
      _ol == ["甲:7", "乙:7"], str(_ol))

# ============================================================
# 4. 装载口（config hook `cue_subs_fn`）
# ============================================================
print("\n【4. 装载口 cue_subs_fn】")
_saved = CFG._HOOKS.get("cue_subs_fn")
try:
    CFG._HOOKS["cue_subs_fn"] = None
    check("★ 不装配 ⇒ None（不问 strict：这款游戏不用 cue 是合法状态）",
          build_bus(_NAMES) is None)
    CFG._HOOKS["cue_subs_fn"] = lambda: _ok
    _b = build_bus(_NAMES, strict=True)
    check("装了且齐全 ⇒ 建出总线", isinstance(_b, CueBus) and len(_b.subs) == 3)
    CFG._HOOKS["cue_subs_fn"] = lambda: _miss
    _msg = _raises(lambda: build_bus(_NAMES, strict=True))
    check("★ 装了但缺一条 ⇒ 装配期抛，且消息点名缺的那条",
          _msg is not None and "x.b" in _msg and "缺订阅" in _msg, str(_msg))
    _b2 = build_bus(_NAMES, strict=False)
    check("strict=False ⇒ 不抛，问题落在 bus.problems（诊断面可读）",
          isinstance(_b2, CueBus) and bool(_b2.problems), str(getattr(_b2, "problems", None)))
finally:
    CFG._HOOKS["cue_subs_fn"] = _saved

# ============================================================
# 5. 端到端：真调用点（landing）× 真装配 × 真文案表
# ============================================================
print("\n【5. 端到端（真调用点 × 真装配 × 夹具文案表）】")
from ext_combat import Battle, make_actor                             # noqa: E402
from ext_combat.battle import landing as L                            # noqa: E402

_hits: list = []


def _count(payload):
    _hits.append(dict(payload))
    return None


_SUBS_E2E = {n: ({"kind": "text", "key": n},) for n in CUE_NAMES}
_SUBS_E2E["battle.landing.dodged"] = ({"kind": "text", "key": "battle.landing.dodged"},
                                      {"kind": "call", "handler": _count})
_saved2 = CFG._HOOKS.get("cue_subs_fn")
_saved3 = CFG._HOOKS.get("formula_skeleton_fn")
try:
    CFG._HOOKS["cue_subs_fn"] = lambda: _SUBS_E2E
    # 让「必闪」确定：闪避上限本来读内容侧骨架表（未装配 ⇒ 0.40）⇒ 本测试自己声明 1.0
    CFG._HOOKS["formula_skeleton_fn"] = lambda: {"dodge": {"cap": 1.0}}
    _me = make_actor("p1", "甲", "player", kind="player", human_controlled=True,
                     level=5, hp=100, max_hp=100, spd=50)
    _foe = make_actor("e1", "乙", "enemy", kind="monster", level=5,
                      hp=100, max_hp=100, spd=50, dodge=1.0)
    _b = Battle(sides={"player": [_me], "enemy": [_foe]}, seed_ct=False, text=FIX_TEXT)
    check("★ 装配过订阅表 ⇒ Battle 带总线", _b.cues is not None)
    _lg: list = []
    _got = L.deal_damage(_b, _me, _foe, 30, _lg)
    check("真调用点发出去了（订阅者被调用 = 走的是 emit，不是旧路）",
          len(_hits) == 1 and "name" in _hits[0], "%s / dmg=%s" % (_hits, _got))
    check("★ 输出逐字节 = 迁移前那句文案（现在取自内容侧文案表）",
          _lg == ["💨 乙 闪避了攻击！"], str(_lg))
    check("闪避 ⇒ 本次不扣血", int(_foe["hp"]) == 100 and _got == 0, "%s / %s" % (_foe["hp"], _got))

    # ---- ★ B2 反证：装了总线但**文案表缺这一条** ⇒ 报错不回落，且结算一字不改 ----
    _partial = TextTable({k: v for k, v in FIX_TEMPLATES.items()
                          if k != "battle.landing.dodged"})
    _me_p = make_actor("p1", "甲", "player", kind="player", human_controlled=True,
                       level=5, hp=100, max_hp=100, spd=50)
    _foe_p = make_actor("e1", "乙", "enemy", kind="monster", level=5,
                        hp=100, max_hp=100, spd=50, dodge=1.0)
    _bp = Battle(sides={"player": [_me_p], "enemy": [_foe_p]}, seed_ct=False, text=_partial)
    _lgp: list = []
    _gotp = L.deal_damage(_bp, _me_p, _foe_p, 30, _lgp)
    check("★ 表缺该 key ⇒ 一行可读坏数据（**不是**引擎模板那句）",
          _lgp == [MISS_LINE] and "闪避" not in "".join(_lgp), str(_lgp))
    check("★ 表缺该 key ⇒ 结算一字不改（闪避仍判定成立、伤害仍被挡下）",
          int(_foe_p["hp"]) == 100 and _gotp == 0, "%s / %s" % (_foe_p["hp"], _gotp))
    _dp = [d for d in getattr(_bp, "diagnostics", []) if d.get("stage") == "cue().emit"]
    check("★ 缺 key 进诊断通道（点名 cue 名，可查）",
          bool(_dp) and "battle.landing.dodged" in _dp[0].get("msg", ""), str(_dp))
finally:
    CFG._HOOKS["cue_subs_fn"] = _saved2
    CFG._HOOKS["formula_skeleton_fn"] = _saved3

# 不装配时（内容侧没接 cue）同一个调用点必须出一行坏数据 + 诊断，输出**不回落**旧模板
_saved4 = CFG._HOOKS.get("formula_skeleton_fn")
try:
    CFG._HOOKS["formula_skeleton_fn"] = lambda: {"dodge": {"cap": 1.0}}
    _me2 = make_actor("p1", "甲", "player", kind="player", human_controlled=True,
                      level=5, hp=100, max_hp=100, spd=50)
    _foe2 = make_actor("e1", "乙", "enemy", kind="monster", level=5,
                       hp=100, max_hp=100, spd=50, dodge=1.0)
    _b2 = Battle(sides={"player": [_me2], "enemy": [_foe2]}, seed_ct=False)
    _lg2: list = []
    L.deal_damage(_b2, _me2, _foe2, 30, _lg2)
    check("★ 未装配（内容侧没接 cue）⇒ **不**落回旧路：出一行坏数据 + 记诊断，"
          "且结算不受影响（伤害仍被挡下）",
          _b2.cues is None and int(_foe2["hp"]) == 100
          and _lg2 == [MISS_LINE],
          "%s / hp=%s / %s" % (_b2.cues, _foe2["hp"], _lg2))
    _d2 = [d for d in getattr(_b2, "diagnostics", []) if d.get("stage") == "cue()"]
    check("★ 缺口进诊断（点名缺总线 = 可查）", len(_d2) == 1, str(getattr(_b2, "diagnostics", None)))
finally:
    CFG._HOOKS["formula_skeleton_fn"] = _saved4

# ============================================================
# 5b. 表现层异常**绝不出结算路径**（Lane-2 实测挖出的洞：点位住在 try/except 里）
# ============================================================
print("\n【5b. 表现层异常不许改结算】")


class _Boom:
    """坏文案表：**命中判定说有**，取的时候炸（`render_or` 抛）。"""

    def __contains__(self, key):
        return True

    def render_or(self, key, default, /, **slots):
        raise RuntimeError("文案表炸了")


_saved5 = CFG._HOOKS.get("cue_subs_fn")
_saved6 = CFG._HOOKS.get("formula_skeleton_fn")
try:
    CFG._HOOKS["cue_subs_fn"] = lambda: {n: ({"kind": "text", "key": n},) for n in CUE_NAMES}
    CFG._HOOKS["formula_skeleton_fn"] = lambda: {"dodge": {"cap": 1.0}}
    _me3 = make_actor("p1", "甲", "player", kind="player", human_controlled=True,
                      level=5, hp=100, max_hp=100, spd=50)
    _foe3 = make_actor("e1", "乙", "enemy", kind="monster", level=5,
                       hp=100, max_hp=100, spd=50, dodge=1.0)
    _b3 = Battle(sides={"player": [_me3], "enemy": [_foe3]}, text=_Boom(), seed_ct=False)
    _lg3: list = []
    _got3 = L.deal_damage(_b3, _me3, _foe3, 30, _lg3)
    check("★ 文案表抛 ⇒ **闪避判定不受影响**（伤害仍被挡下，结算一字不改）",
          int(_foe3["hp"]) == 100 and _got3 == 0, "hp=%s dmg=%s" % (_foe3["hp"], _got3))
    check("★ 文案表抛 ⇒ 仍出一行可读坏数据（不静默丢行，也**不**落回旧模板）",
          _lg3 == [MISS_LINE], str(_lg3))
    _d3 = [d for d in getattr(_b3, "diagnostics", []) if d.get("stage") == "cue().emit"]
    check("★ 异常进了诊断通道（不进玩家可见日志 = 不静默）",
          len(_d3) == 1 and _d3[0].get("kind") == "RuntimeError", str(getattr(_b3, "diagnostics", None)))

    # ---- ★ B2：答不出命中的表 ⇒ 同一处置（报错 → 坏数据行 + 诊断，结算不改） ----
    _me4 = make_actor("p1", "甲", "player", kind="player", human_controlled=True,
                      level=5, hp=100, max_hp=100, spd=50)
    _foe4 = make_actor("e1", "乙", "enemy", kind="monster", level=5,
                       hp=100, max_hp=100, spd=50, dodge=1.0)
    _b4 = Battle(sides={"player": [_me4], "enemy": [_foe4]}, text=_NoHit(), seed_ct=False)
    _lg4: list = []
    _got4 = L.deal_damage(_b4, _me4, _foe4, 30, _lg4)
    check("★ 表答不出命中 ⇒ 同款处置（坏数据行 + 结算不改 + 诊断现形）",
          int(_foe4["hp"]) == 100 and _got4 == 0 and _lg4 == [MISS_LINE]
          and getattr(_b4, "diagnostics", None), "%s / %s" % (int(_foe4["hp"]), _lg4))
finally:
    CFG._HOOKS["cue_subs_fn"] = _saved5
    CFG._HOOKS["formula_skeleton_fn"] = _saved6

# ============================================================
# 6. 示例包（内容侧真源）：订阅表 / 文案表 / 注入面 与引擎声明**同源**
# ============================================================
print("\n【6. 示例包：订阅表覆盖 CUE_NAMES + 文案表逐字】")
_EX = os.path.join(_ROOT, "examples", "minimal-game")
if _EX not in sys.path:
    sys.path.insert(0, _EX)
_EX_CONTENT = importlib.import_module("content")          # import 即 install_engine()
_EX_TEXTS = importlib.import_module("content.texts")
_EX_CUES = importlib.import_module("content.cues")

check("★ 引擎 CUE_NAMES 全部被示例包声明（缺一条 ⇒ 装配期会抛）",
      audit_subs(CUE_NAMES, normalize_subs(_EX_CUES.SUBS)) == [],
      str(audit_subs(CUE_NAMES, normalize_subs(_EX_CUES.SUBS))))
check("示例包不多声明引擎不认的名字（拼写漂移现形）",
      not [k for k in _EX_CUES.SUBS if k not in CUE_NAMES], str(sorted(_EX_CUES.SUBS)))
check("CUE_NAMES 无重复（同名即接口）", len(set(CUE_NAMES)) == len(CUE_NAMES), str(CUE_NAMES))
check("★ CUE_NAMES = B1 3 + B2 14 + B3 25 + B4 18 + B5 1（收口第 2 批）+ B6 1（减伤互斥）= 62",
      len(CUE_NAMES) == 62, str(len(CUE_NAMES)))
check("★ 示例包文案表与订阅表同源（订阅键集 = 文案 key 集）",
      set(_EX_CUES.SUBS) == set(_EX_TEXTS.TEMPLATES), str(sorted(_EX_TEXTS.TEMPLATES)))
check("★ 门禁夹具与示例包文案表**逐字**相同（夹具只是副本，不是第二真源）",
      _EX_TEXTS.TEMPLATES == FIX_TEMPLATES,
      str([(k, _EX_TEXTS.TEMPLATES.get(k), FIX_TEMPLATES.get(k))
           for k in sorted(set(_EX_TEXTS.TEMPLATES) ^ set(FIX_TEMPLATES))][:5]
          + [(k, _EX_TEXTS.TEMPLATES.get(k), FIX_TEMPLATES.get(k))
             for k in sorted(set(_EX_TEXTS.TEMPLATES) & set(FIX_TEMPLATES))
             if _EX_TEXTS.TEMPLATES[k] != FIX_TEMPLATES[k]][:5]))
check("★ 示例包的 `text_table_fn` 真挂上了（install_engine 之后）",
      CFG._HOOKS.get("text_table_fn") is not None
      and CFG._HOOKS["text_table_fn"]() is _EX_TEXTS.TEXT,
      "%s" % (CFG._HOOKS.get("text_table_fn"),))
check("★ 示例包每条已迁移 key 都能从它自己的表渲染出（不漏条）",
      not [k for k in CUE_NAMES if k not in _EX_TEXTS.TEXT], str(CUE_NAMES))
check("示例包文案表自身合法（占位符与声明一致；`audit` 零问题）",
      _EX_TEXTS.TEXT.audit()["problems"] == [], str(_EX_TEXTS.TEXT.audit()["problems"]))
check("示例包 cue_subs 的供体形状可直接进装配期对账（不缺 key）",
      all(len(v) == 1 and v[0].get("kind") == "text" and v[0].get("key") == k
          for k, v in _EX_CUES.SUBS.items()), str(_EX_CUES.SUBS))

# ============================================================
# 7. ★ B2 判据：文案必须命中 + 引擎侧模板删净（静态扫描，不靠自觉）
# ============================================================
print("\n【7. B2：文案必须命中 · 引擎侧模板删净】")

# 7a. 每个已迁移点位的逐字文案都在夹具表里，且能渲染出（槽位全填）
_bad_render = []
_bus_fix = CueBus({n: ({"kind": "text", "key": n},) for n in CUE_NAMES}, table=FIX_TEXT)
for _k in CUE_NAMES:
    _slots = {s: 1 for s in extract_params(FIX_TEMPLATES[_k])}
    _out: list = []
    _bus_fix.emit(_out, _k, _slots)
    if len(_out) != 1 or not _out[0] or _out[0] == MISS_LINE or "{" in _out[0]:
        _bad_render.append((_k, _out))
check("★ 17 个已迁移点位都能从文案表渲染出一行（非空 · 非坏数据 · 槽位全填）",
      not _bad_render, str(_bad_render[:4]))

# 7b. 静态扫描：引擎侧已迁移点位不许再持有措辞
_ENG_SRC = {}
for _dp, _dirs, _files in os.walk(BATTLE_DIR):
    if "__pycache__" in _dp:
        continue
    for _f in sorted(_files):
        if _f.endswith(".py"):
            _p = os.path.join(_dp, _f)
            with open(_p, encoding="utf-8") as _fh:
                _ENG_SRC[_p] = _fh.read()

# ① 键位不许再走「渐进迁移」口（render_via / render_or / self._t）
_KEYRX = re.compile(r'(?:render_via|render_or)\(\s*[A-Za-z_][\w\.]*\s*,\s*"([^"]+)"')
_TRX = re.compile(r'\._t\(\s*"([^"]+)"')
_still_keys = []
for _p, _src in _ENG_SRC.items():
    for _m in list(_KEYRX.finditer(_src)) + list(_TRX.finditer(_src)):
        if _m.group(1) in CUE_NAMES:
            _still_keys.append((os.path.basename(_p), _m.group(1)))
check("★ 已迁移的点位不再出现在 `render_via/render_or/._t` 的键位上（引擎不再取兜底模板）",
      not _still_keys, str(_still_keys[:6]))

# ② `_cue(...)` 调用点：第 3 个实参必须是已迁移的 cue 名，**后面不许再有字符串实参**（= 模板）
_ctx = {}
for _p, _src in _ENG_SRC.items():
    _ctx[_p] = ast.parse(_src, filename=_p)
_bad_calls = []
_seen_call_keys = []
for _p, _tree in _ctx.items():
    for _n in ast.walk(_tree):
        if not isinstance(_n, ast.Call):
            continue
        _fn = _n.func
        _nm = _fn.attr if isinstance(_fn, ast.Attribute) else getattr(_fn, "id", "")
        if _nm not in ("_cue", "cue") or len(_n.args) < 3:
            continue
        _key = _n.args[2]
        if not (isinstance(_key, ast.Constant) and isinstance(_key.value, str)):
            _bad_calls.append((os.path.basename(_p), _n.lineno, "第 3 个实参不是字符串 cue 名"))
            continue
        _seen_call_keys.append(_key.value)
        if _key.value not in CUE_NAMES:
            _bad_calls.append((os.path.basename(_p), _n.lineno, "cue 名不在 CUE_NAMES：%r" % _key.value))
        for _a in _n.args[3:]:
            if isinstance(_a, ast.Constant) and isinstance(_a.value, str):
                _bad_calls.append((os.path.basename(_p), _n.lineno,
                                   "还有字符串实参（= 引擎侧模板）：%r" % _a.value))
check("★ 每条 `_cue(...)` 只给「cue 名 + 槽位」，不再有字符串模板实参",
      not _bad_calls, str(_bad_calls[:6]))
check("★ 17 个已迁移点位在引擎侧都有调用点（没有「只删模板没改调用」）",
      set(CUE_NAMES) <= set(_seen_call_keys), str(sorted(set(CUE_NAMES) - set(_seen_call_keys))))

# ③ 逐字扫描：landing.py / cues.py 里不得出现任何已迁移点位的模板串
_TMPL_HITS = []
for _p, _src in _ENG_SRC.items():
    if os.path.basename(_p) not in ("landing.py", "cues.py", "battle.py"):
        continue
    for _k in CUE_NAMES:
        if FIX_TEMPLATES[_k] in _src:
            _TMPL_HITS.append((os.path.basename(_p), _k))
check("★ 逐字扫描：引擎的 landing/cues/battle 里零条已迁移点位模板串（措辞真删净）",
      not _TMPL_HITS, str(_TMPL_HITS[:6]))

# ============================================================
# 8. 只读契约「有牙」两态（设计案 §3.5④）
# ============================================================
print("\n【8. 只读契约有牙：挂一个「改 actor」的订阅者 ⇒ 两态 to_state 必须不同】")
#: 目的：证明**冻结尺子的 state 通道**抓得住「订阅者越权改状态」这类改动 ——
#: 设计 §3.5④ 的原话：「挂一个『改 actor』的订阅者 ⇒ 两态 `to_state` 必须不同 ⇒ 门禁必须红」。
#: 三态对照（同一场构造 + 同一手结算，只差订阅者干了什么）：
#:   ① 干净订阅者（只渲染）      ② 只改 payload（引擎给副本 ⇒ 不该影响状态）
#:   ③ 直接改 actor（越权）      ⇒ 只有 ③ 必须让 state 变 —— 那正是尺子能报出来的那一档。
_two_state_box: dict = {}


def _subs_with(extra):
    subs = {n: ({"kind": "text", "key": n},) for n in CUE_NAMES}
    subs["battle.landing.dodged"] = ({"kind": "text", "key": "battle.landing.dodged"},) + extra
    return subs


def _dodged_state(extra_subs):
    """跑一场「必闪」战斗（发一次 `battle.landing.dodged`）→ 返回 (logs, to_state, 敌 actor)。"""
    _s2 = CFG._HOOKS.get("cue_subs_fn")
    _s3 = CFG._HOOKS.get("formula_skeleton_fn")
    try:
        CFG._HOOKS["cue_subs_fn"] = lambda: _subs_with(extra_subs)
        CFG._HOOKS["formula_skeleton_fn"] = lambda: {"dodge": {"cap": 1.0}}
        me = make_actor("p1", "甲", "player", kind="player", human_controlled=True,
                        level=5, hp=100, max_hp=100, spd=50)
        foe = make_actor("e1", "乙", "enemy", kind="monster", level=5,
                         hp=100, max_hp=100, spd=50, dodge=1.0)
        _two_state_box["foe"] = foe
        b = Battle(sides={"player": [me], "enemy": [foe]}, seed_ct=False, text=FIX_TEXT)
        lg: list = []
        L.deal_damage(b, me, foe, 30, lg)
        return lg, b.to_state(), foe
    finally:
        CFG._HOOKS["cue_subs_fn"] = _s2
        CFG._HOOKS["formula_skeleton_fn"] = _s3


def _only_payload(p):                      # ② 只改 payload（引擎给的是副本）
    p["n"] = 999
    return None


def _steal_hp(p):                          # ③ 越权：直接改 actor（订阅者不该有这条能力）
    _two_state_box["foe"]["hp"] = int(_two_state_box["foe"]["hp"]) - 7
    return None


_lg_clean, _st_clean, _foe_clean = _dodged_state(())
_lg_pay, _st_pay, _foe_pay = _dodged_state(({"kind": "call", "handler": _only_payload},))
_lg_dirty, _st_dirty, _foe_dirty = _dodged_state(({"kind": "call", "handler": _steal_hp},))

check("① 干净态：那一行照旧渲染（对照基准）",
      _lg_clean == ["💨 乙 闪避了攻击！"], str(_lg_clean))
check("★ ② 只改 payload ⇒ 两态 to_state **相同**（引擎给副本：订阅者碰不到状态）",
      _st_pay == _st_clean)
check("★ ③ 直接改 actor ⇒ 两态 to_state **不同**（越权可被 state 通道抓住）",
      _st_dirty != _st_clean,
      "干净 hp=%s / 越权 hp=%s" % (_foe_clean["hp"], _foe_dirty["hp"]))
check("★ ③ 且差的就是被改的那一格（不是别处漂移）",
      _st_clean["sides"]["enemy"][0]["hp"] != _st_dirty["sides"]["enemy"][0]["hp"]
      and _st_clean["sides"]["enemy"][0]["uid"] == _st_dirty["sides"]["enemy"][0]["uid"])

# ============================================================
# 9. ★ 绝对时刻（2026-09-28）：**每**一条 cue 的 payload 都必含 TIME_SLOT
# ============================================================
from ext_combat.battle.cues import TIME_SLOT, now_of, with_now                # noqa: E402
from _cue_time_probe import run as _probe_cue_time                            # noqa: E402

print("\n【9. 绝对时刻：每条 cue 的 payload 都必含 %r】" % TIME_SLOT)

check("★ 键名 = %r（中性词；单位/呈现归内容侧，引擎不内置措辞）" % TIME_SLOT,
      TIME_SLOT == "t")

# ---- 9.1 主判据：覆盖尺真驱动出来的**每一条** cue 的 payload 都带 `t` ----
# 为什么用覆盖尺而不是手搓几条：这 62 条里有大量「只有特定战斗形态才会发」的点位
# （dot_tick / gauge.* / taken_mult_skipped …）。手搓会漏，漏了门禁就变成自证。
# 覆盖尺的驱动走的是引擎**真结算路径**（`tests/test_cue_coverage.py` §3 已钉死不许直接发 cue），
# 所以这里量到的是「真实那 62 条」，不是「我挑的几条」。
_seen_slots, _fired, _missing = _probe_cue_time(seal=True)

check("★ 覆盖尺真驱动跑通（union == CUE_NAMES，%d 条都真打到）" % len(CUE_NAMES),
      _fired == len(CUE_NAMES), "驱动到 %d / 声明 %d" % (_fired, len(CUE_NAMES)))
check("★ 声明的每一条都真发过一次（不是「没发到所以没查」）", not _missing,
      str(_missing)[:150])
_bad_t = sorted(n for n, s in _seen_slots.items() if TIME_SLOT not in s)
check("★★ 判据：每条 cue 的 payload 都含 %r（一条都不许缺）" % TIME_SLOT,
      not _bad_t, "缺 %r 的：%s" % (TIME_SLOT, str(_bad_t)[:150]))
check("★ 且拿到的是**数**（不是 None / 字符串 / bool 冒充）",
      all(isinstance(s.get(TIME_SLOT), (int, float)) and not isinstance(s.get(TIME_SLOT), bool)
          for s in _seen_slots.values()),
      str([(n, s.get(TIME_SLOT)) for n, s in sorted(_seen_slots.items())][:3]))
check("★ 时刻**有真的在动**（不是恒 0：冻结 5 组推进过时间轴）",
      len({s.get(TIME_SLOT) for s in _seen_slots.values()}) > 1,
      str(sorted({s.get(TIME_SLOT) for s in _seen_slots.values()})[:6]))

# ---- 9.2 反证：拿掉补格那一步 ⇒ 判据当场红（证明它真的在保护东西）----
_anti_seen, _anti_fired, _ = _probe_cue_time(seal=False)
check("★★ 反证：出口不补 %r ⇒ 同一批 cue 全部缺格（判据有牙，不是恒真）" % TIME_SLOT,
      _anti_fired > 0 and all(TIME_SLOT not in s for s in _anti_seen.values()),
      "反证里发到 %d 条，其中仍带 %r 的：%s"
      % (_anti_fired, TIME_SLOT,
         [n for n, s in _anti_seen.items() if TIME_SLOT in s][:3]))

# ---- 9.3 补格位置：唯一出口，且不改调用点传进来的那个 dict ----
_orig = {"name": "乙", "dmg": 3}
_sealed = with_now(_b2, _orig)
check("★ 补格只做在新副本上（调用点的 dict 一个字节都不动 —— 只读契约）",
      TIME_SLOT not in _orig and TIME_SLOT in _sealed and _sealed["name"] == "乙",
      "原件=%s 副本=%s" % (_orig, _sealed))
check("★ 补格不覆盖调用点已有的 %r（时刻只由发出那一刻的钟决定）" % TIME_SLOT,
      with_now(_b2, {TIME_SLOT: 42})[TIME_SLOT] == 42)
check("★ 调用点没给 %r 时 = 取引擎内部那一个钟（不是 0、也不是新钟）" % TIME_SLOT,
      with_now(_b2, {})[TIME_SLOT] == now_of(_b2) == float(_b2._now),
      "with_now=%s _now=%s" % (with_now(_b2, {})[TIME_SLOT], _b2._now))

# ---- 9.4 给不了的时刻必须是 0，且是**合法**的 0（不许缺格、不许 None）----
class _NoClock:                          # 战斗未接入 schedule：没有 _now
    cues = None
check("★ 无 `_now` 的战斗 ⇒ 给 0（不是缺格、不是 None）",
      with_now(_NoClock(), {})[TIME_SLOT] == 0.0)
check("★ battle=None ⇒ 给 0（照样是 float）",
      with_now(None, None)[TIME_SLOT] == 0.0
      and isinstance(with_now(None, None)[TIME_SLOT], float))
check("★ `_now` 是 None / 非法值 ⇒ 给 0（不把脏值透给包侧）",
      with_now(type("X", (), {"_now": None, "cues": None})(), {})[TIME_SLOT] == 0.0
      and with_now(type("Y", (), {"_now": "坏值", "cues": None})(), {})[TIME_SLOT] == 0.0)
check("★ 脏时钟**不是静默兜底**：`tests/test_no_silent_fallback.py` 的 S 判据仍绿",
      _S_count() == 0, "S=%s" % (_S_count(),))
_dirty = type("Z", (), {"_now": "坏值", "cues": None})()
with_now(_dirty, {})
_dd = [d for d in (getattr(_dirty, "diagnostics", None) or [])]
check("★ 且脏时钟会**记诊断**（内容侧探针钉着「整场 diagnostics 必须为空」）",
      len(_dd) == 1 and _dd[0].get("stage") == "cue().now_of", str(_dd)[:120])
check("★ 刚构造、没推进过的战斗 ⇒ 0（开战前这一刻 = 合法取值，不是缺格）",
      now_of(_b2) == 0.0, "now_of=%r" % (now_of(_b2),))

# ---- 9.5 静态：补格只在这一个地方做（不许第二个出口偷偷漏掉）----
_emit_sites = _emit_calls_in_cues()
check("★ 静态：`cues.py` 里只有 `cue()` 一处直接 emit（补格点唯一 ⇒ 将来加 cue 也会漏不掉）",
      len(_emit_sites) == 1 and _emit_sites[0][0] == "cue", str(_emit_sites)[:150])
check("★ 且那一处 emit 传的是 `with_now(...)`（不是原 payload）",
      bool(_emit_sites) and "with_now(" in _emit_sites[0][2],
      _emit_sites[0][2] if _emit_sites else "")
check("★ 静态：ext_combat 全包没有第二处 `bus.emit(...)` 直发（漏了就没法保证每条都有 %r）"
      % TIME_SLOT, not _ast_all_ext_combat(), str(_ast_all_ext_combat())[:150])

print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
sys.exit(1 if failed else 0)
