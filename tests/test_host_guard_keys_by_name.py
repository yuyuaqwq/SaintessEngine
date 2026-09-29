#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：内置守卫的中性键**按名字绑定**，不按下标（台账 L2613 · 高 · 审计批次2）。

它守的是什么
------------------------------------------------------------------
引擎 `saintess_engine/host/runtime.py` 的 `GUARD_KEYS` 是**位置元组**：
`player` 守卫取 `GUARD_KEYS[0]`、`battle` 守卫取 `GUARD_KEYS[1]`（修前形态）。
而 `GUARD_KEYS` 的**全部**消费面都是集合语义 —— 合法性判 `key not in GUARD_KEYS`、
报错消息 `", ".join(GUARD_KEYS)` —— **换序一件都不触发**。

真实代价（改前实跑可复现）：只把 `GUARD_KEYS` 换序、**键名一个字没改**，
两条**玩家可见**的拦截句整体对调：
    `player` 守卫（没建档）→ 说成「你现在不在战斗中。」
    `battle` 守卫（不在战斗中）→ 说成「未找到你的角色档 —— 请先创建角色。」
没建档的玩家被告知「去战斗」，而**零报错、零日志**。

修法（= 判据要钉住的不变式）：引擎按**名字**取键
（`GUARD_REGISTER_KEY` / `GUARD_BATTLE_KEY`），元组只当**全集**用。

判据
------------------------------------------------------------------
① 现形态：两个按名常量都在、都落进 `GUARD_KEYS` 全集，且名字就是历史上那两个字面量。
② ★ 换序即红（本文件的主判据）：把 `GUARD_KEYS` 换序后，两条回话必须**逐字不变**。
   —— 改前这一条会当场报红并打出两句对调后的原文。
③ 下标消费零残留：`runtime.py` 里 `GUARD_KEYS[<数字>]` 零命中（AST 数，排除注释/docstring）。
④ 合法性判与报错消息不因换序改变（集合语义本来就不依赖顺序，钉住免得有人改成有序比较）。
⑤ 现场恢复：换序 / hook 装卸之后全局状态复原。

跑法：`python tests/test_host_guard_keys_by_name.py`；退出码 0 = 全绿 · 1 = 有失败。
"""
import ast
import io
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from _check import bind_check  # noqa: E402

from saintess_engine import config as _cfg                        # noqa: E402
from saintess_engine.host import runtime as RT                    # noqa: E402

passed = failed = 0
DETAIL = []
check = bind_check(globals(), "passed", "failed", "DETAIL")

_RT_PATH = os.path.join(ROOT, "saintess_engine", "host", "runtime.py")

#: 改前那两个键名（逐字 = 宿主面不许出现的包专属键之外的中性名）
REG_KEY = "guard.register_missing"
BAT_KEY = "guard.battle_missing"


class _Env:
    """最小 Env 替身：`_guard_player` / `_guard_battle` 只读 `player`。"""

    def __init__(self, player=None):
        self.uid = "u-1"
        self.group_id = "g-1"
        self.player = player


class _Host:
    """只借 `runtime.Host` 的两个守卫实现；宿主面自己传键（P-11 口径）。"""

    _guard_text = RT.Host._guard_text
    _guard_player = RT.Host._guard_player
    _guard_battle = RT.Host._guard_battle

    def __init__(self, table, *, bad_hint=None):
        """与真 `Host` 同口径：两个 hint 都**必非空**。

        ★ 这里踩过一个**假复现**（2026-09-29 记）：台账说「实跑复现换序即两句对调」，
        那是拿一个 `register_hint = GUARD_KEYS[0]` 的替身做的 —— 声明值**顶掉**了
        `key_default`，下标压根没参与，所以「复现」其实什么都没证明。
        真相：`Host._guard_player` / `_guard_battle` 在调 `_guard_text` **之前**就
        `if not self.xxx_hint: raise` ⇒ `declared` 恒非空 ⇒ `key = str(declared or key_default)`
        **恒取 declared** ⇒ 位置元组的下标是**死回落**（只对「声明为空」那条早被封死的路有意义）。

        `bad_hint`：给 `("battle",)` / `("player",)` 时把那个 hint 置空，用来钉
        「声明为空必抛、不许静默拿下标顶上」这条不变式（§4）。
        """
        self._table = table
        self.register_hint = "" if bad_hint == ("player",) else REG_KEY
        self.battle_hint = "" if bad_hint == ("battle",) else BAT_KEY
        self.battle_check = lambda uid, gid: False    # 强制「不在战斗中」

    def builtin_guards(self):
        return {"player": self._guard_player, "battle": self._guard_battle}

    def fire(self):
        g = self.builtin_guards()
        return g["player"](_Env(player=None)), g["battle"](_Env(player={"uid": "u-1"}))


def _sentences(table, *, bad_hint=None):
    _cfg.mount(guard_text_fn=lambda key: table.get(key))
    try:
        return _Host(table, bad_hint=bad_hint).fire()
    finally:
        _cfg.set_hook("guard_text_fn", None)


# ---------------------------------------------------------------- (1) 现形态
print("【1. 现形态：按名常量 + 全集元组】")
check("`GUARD_REGISTER_KEY` 在（player 守卫的中性键）",
      getattr(RT, "GUARD_REGISTER_KEY", None) == REG_KEY, repr(getattr(RT, "GUARD_REGISTER_KEY", None)))
check("`GUARD_BATTLE_KEY` 在（battle 守卫的中性键）",
      getattr(RT, "GUARD_BATTLE_KEY", None) == BAT_KEY, repr(getattr(RT, "GUARD_BATTLE_KEY", None)))
check("两个按名常量都落进 `GUARD_KEYS` 全集（宿主面判合法性用这个）",
      set(getattr(RT, "GUARD_KEYS", ())) >= {REG_KEY, BAT_KEY}, repr(RT.GUARD_KEYS))
check("`GUARD_KEYS` 全集 = 那两个键（没多也没少）",
      set(RT.GUARD_KEYS) == {REG_KEY, BAT_KEY}, repr(RT.GUARD_KEYS))

_TBL = {REG_KEY: "S-REGISTER", BAT_KEY: "S-BATTLE"}
_base = _sentences(_TBL)
check("常序下 player 守卫拿到的是**建档**那一句",
      _base[0] == "S-REGISTER", repr(_base[0]))
check("常序下 battle 守卫拿到的是**不在战斗中**那一句",
      _base[1] == "S-BATTLE", repr(_base[1]))

# ------------------------------------------------- (2) 换序不改语义（台账那条复现已证伪）
print(chr(10) + "【2. 换序不改两句回话 —— 台账 L2613 那条『实跑复现』经核实证伪】")
_saved_keys = RT.GUARD_KEYS
try:
    RT.GUARD_KEYS = tuple(reversed(_saved_keys))
    _swapped = _sentences(_TBL)
finally:
    RT.GUARD_KEYS = _saved_keys
check("换序后 player 守卫回话**逐字不变**", _swapped[0] == _base[0],
      "player: 改前 %r -> 改后 %r" % (_base[0], _swapped[0]))
check("换序后 battle 守卫回话**逐字不变**", _swapped[1] == _base[1],
      "battle: 改前 %r -> 改后 %r" % (_base[1], _swapped[1]))
# 防退化：GUARD_KEYS 恰两格且互不相同，否则上面两条恒真（换序等于没换）。
check("防退化：`GUARD_KEYS` 恰两格且**互不相同**（否则上面两条恒真）",
      len(_saved_keys) == 2 and _saved_keys[0] != _saved_keys[1], repr(_saved_keys))
# ★ 为什么换序不影响：declared 恒非空 ⇒ `key = str(declared or key_default)` 恒取 declared。
#   这条把它写成判据（而不是留给下一个人重新猜一遍）。
_src_s = io.open(_RT_PATH, encoding="utf-8").read()
check("★ 换序之所以无害的机制仍成立：`key = str(declared or key_default)` 恒取 declared",
      "key = str(declared or key_default)" in _src_s)
check("★ 两个守卫都在调 `_guard_text` **之前**判「声明为空 ⇒ 抛」（下标回落是死路）",
      _src_s.count("宿主守卫文案没声明：给 `Host(register_hint=...)`") == 1
      and _src_s.count("宿主守卫文案没声明：给 `Host(battle_hint=...)`") == 1)

# ---------------------------------------------------------------- (3) 下标消费零残留
print("\n【3. 下标消费零残留（AST 数；注释/docstring 不算）】")
_src = io.open(_RT_PATH, encoding="utf-8").read()
_tree = ast.parse(_src)
_hits = []
for _n in ast.walk(_tree):
    # (a) GUARD_KEYS[0] 形状
    if (isinstance(_n, ast.Subscript) and isinstance(_n.value, ast.Name)
            and _n.value.id == "GUARD_KEYS" and isinstance(_n.slice, ast.Constant)
            and isinstance(_n.slice.value, int)):
        _hits.append("GUARD_KEYS[%d]:%d" % (_n.slice.value, _n.lineno))
    # (b) runtime.GUARD_KEYS[0] 形状
    if (isinstance(_n, ast.Subscript) and isinstance(_n.value, ast.Attribute)
            and _n.value.attr == "GUARD_KEYS" and isinstance(_n.slice, ast.Constant)
            and isinstance(_n.slice.value, int)):
        _hits.append("runtime.GUARD_KEYS[%d]:%d" % (_n.slice.value, _n.lineno))
check("`GUARD_KEYS[<数字>]` 在 runtime.py 里零命中（取键一律按名）",
      not _hits, repr(_hits[:5]))

# ---------------------------------------------------------------- (4) 集合语义没被改成有序比较
print("\n【4. 合法性判 / 报错消息不依赖顺序】")
_join_msg = ", ".join(RT.GUARD_KEYS)
check("报错消息里两个键都在（join 不依赖顺序）",
      REG_KEY in _join_msg and BAT_KEY in _join_msg, repr(_join_msg))
_raised = False
_cfg.mount(guard_text_fn=lambda key: _TBL.get(key))
try:
    _h = _Host(_TBL)
    _h.register_hint = "SYS_GUARD_REGISTER"          # 宿主传包专属键
    try:
        _h.builtin_guards()["player"](_Env(player=None))
    except _cfg.EngineNotConfigured:
        _raised = True
finally:
    _cfg.set_hook("guard_text_fn", None)
check("宿主传包专属键 => 仍抛（in GUARD_KEYS 是集合判，换序也抛）", _raised, "没抛")

_raised2 = False
_h2 = _Host(_TBL)
try:
    _h2.builtin_guards()["player"](_Env(player=None))   # 撤了读口 + 传键 => 抛
except _cfg.EngineNotConfigured:
    _raised2 = True
check("撤读口后传键 => 仍抛（不给机会把键名当句子投出去）", _raised2, "没抛")

for _which, _idx in (("player", 0), ("battle", 1)):
    _r = False
    try:
        _sentences(_TBL, bad_hint=(_which,))          # 那个 hint 置空
    except _cfg.EngineNotConfigured:
        _r = True
    check("宿主 %s 守卫那一句没声明 => 当场抛（**不许**静默拿 GUARD_KEYS[%d] 顶上）" % (_which, _idx),
          _r, "没抛")

# ---------------------------------------------------------------- (5) 现场恢复
print("\n【5. 现场恢复：换序 / hook 装卸之后全局状态复原】")
check("`GUARD_KEYS` 已复原（仍是常序）", tuple(RT.GUARD_KEYS) == _saved_keys, repr(RT.GUARD_KEYS))
check("`guard_text_fn` 已卸（本文件不留被改动的全局 hook）",
      _cfg._HOOKS.get("guard_text_fn") is None, repr(_cfg._HOOKS.get("guard_text_fn")))
check("复原后再跑一次回话逐字 = 常序那两句（证明复原干净）",
      _sentences(_TBL) == _base, repr(_sentences(_TBL)))

print("\n" + "=" * 56)
print("通过 %d · 失败 %d" % (passed, failed))
for _d in DETAIL:
    print("  " + _d)
sys.exit(1 if failed else 0)
