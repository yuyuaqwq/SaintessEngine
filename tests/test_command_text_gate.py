# -*- coding: utf-8 -*-
"""`command/text.py` 的**前缀护栏门禁**（审计 L300 · 2026-09-29 批次4）。

背景
----
台账 L300：`strip_command` 用 `msg.startswith(cmd)` **裸前缀匹配**，
缺陷形状为真且可复现 —— `strip_command("看起来", "看")` → `'起来'`。

但台账那句「当前 orlandia 别名表无前缀包含关系（已核）故未爆」**在数据漂移面前不可靠**：
真实声明里就有 10 对前缀包含（`装备` ⊂ `装备重锻`、`烹饪` ⊂ `烹饪列表`、
`副本` ⊂ `副本地图` …）。今天不炸，靠的是**路由层先选中了更长的那条**，
不是靠剥词函数本身正确。

⇒ **本门禁不修 L300**（真修法要动 196 条声明的「指令词后可否直接跟内容」口径，
属内容侧契约决策，见台账），而是**把「今天为什么不炸」钉成判据**：
一旦有人改声明口径 / 改路由排序 / 改 `first_hit` 可见性，
让短词真的先命中，本门禁立刻报红并点名是哪一对。

三组判据
--------
A 组 剥词函数自身口径（逐字钉，不改行为）
B 组 **端到端不变量**：真实声明表上，每对前缀包含词，路由必须选中**长词**，
    且长词剥完后 `arg` 不得残留指令词本体（这一条就是玩家侧可感知的那一面）
C 组 有牙反证（进程内换模块属性，真仓零写入、不起子进程、无自举）

跑法：python tests/test_command_text_gate.py
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, FW_ROOT)

from _check import bind_check  # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []
check = bind_check(globals(), "PASS", "FAIL", "FAILURES")

import saintess_engine.command.text as text_mod  # noqa: E402
from saintess_engine.command import text as text_mod  # noqa: E402,F811
from saintess_engine.command.text import strip_at_prefix, strip_command  # noqa: E402

CMDS_JSON = os.path.join(FW_ROOT, "games", "orlandia", "content", "data", "commands.json")

# ================================================================ A. 剥词函数口径
print("== A. 剥词函数自身口径 ==")
check("剥 At 前缀", strip_at_prefix("[At:某人] 背包") == "背包")
check("剥 引用消息 前缀", strip_at_prefix("[引用消息 你好] 背包") == "背包")
check("无前缀 → 原样去空白", strip_at_prefix("  背包  ") == "背包")
check("完整命中 → 空串", strip_command("背包", "背包") == "")
check("分隔符后取参数", strip_command("背包  材料", "背包") == "材料")
check("都不命中 → 原样", strip_command("随便聊聊", "背包") == "随便聊聊")
check("alias 生效", strip_command("我的角色 属性", "角色", ("我的角色",)) == "属性")
check("alias == cmd 时跳过（不自己剥自己）",
      strip_command("我的角色 x", "我的角色", ("我的角色",)) == "x")
check("先剥平台前缀再剥指令词",
      strip_command("[At:某人] 背包 材料", "背包") == "材料")

# ★ L300 的缺陷形状 —— 断言它**仍是缺陷**（文档化当前行为，不是判它对）。
#   若将来真修 L300，这一条会转红，**提示同步更新口径**（那是好事，不是回归）。
check("★ L300 缺陷形状仍在：裸前缀匹配会把词内内容当成参数",
      strip_command("看起来", "看") == "起来",
      ("strip_command('看起来','看') =", repr(strip_command("看起来", "看"))))

# ================================================================ B. 端到端不变量
print("== B. 端到端不变量：前缀包含词必须由路由选中长词 ==")

_HAS_REG = os.path.exists(CMDS_JSON)
if not _HAS_REG:
    check("声明表在（前置）", False, CMDS_JSON)
    print(chr(10) + '=== 结果 PASS=%d FAIL=%d ===" % (PASS, FAIL))')
    sys.exit(1 if FAIL else 0)

with open(CMDS_JSON, encoding="utf-8") as f:
    _DECL = json.load(f)

from saintess_engine.command.registry import CommandRegistry  # noqa: E402

_reg = CommandRegistry(name="text_gate")
_reg.load(_DECL)

# 取每条声明自己声明的 cmd= 词（这是 handler 剥词时真正用的那个词）
_cmd_of = {}
for _k, _v in _DECL.items():
    for _p in (_v.get("params") or []):
        _m = __import__("re").match(r"^cmd=(.+)$", str(_p))
        if _m:
            _cmd_of[_k] = _m.group(1).strip()
            break

_words = sorted(set(_cmd_of.values()))
_pairs = [(a, b) for a in _words for b in _words if a != b and b.startswith(a)]
check("★ 前缀包含对确实存在（证明 L300 在真实数据上不是纯理论问题）",
      len(_pairs) > 0, ("对数", len(_pairs)))

for _short, _long in _pairs:
    _hit = _reg.first_hit(_long, visible_only=True)
    _ok = _hit is not None and getattr(_hit, "key", None) == _cmd_of and False
    # 正确断言：路由必须落到**声明长词**的那一条
    _expect_key = next((k for k, c in _cmd_of.items() if c == _long), None)
    _got = getattr(_hit, "key", None) if _hit is not None else None
    check("路由 %r → 长词 %r 的 handler" % (_long, _long),
          _expect_key is not None and _got == _expect_key,
          ("期望", _expect_key, "实得", _got, "对", (_short, _long)))
    # 剥完不得残留指令词本体
    if _got is not None and _got in _cmd_of:
        _arg = strip_command(_long, _cmd_of[_got])
        check("剥词后无残留（%r → %r）" % (_long, _got),
              not _arg.startswith(_long[:1]),
              ("arg", _arg))

check("★ B 组扫到对数 > 0（防空转）", len(_pairs) >= 10, ("对数", len(_pairs)))

# ================================================================ C. 有牙反证
print("== C. 有牙反证：抽掉路由的「长词优先」⇒ 必须报红 ==")
# 证明 B 组不是恒绿：把 first_hit 的排序打乱（让短词声明先命中），
# B 组第二条判据必须转红。**进程内换属性** ⇒ 真仓零写入、无子进程、无自举。
# （本车道上一轮「子进程 + 影子树」反证实测报 STILL_RAISES，故不用。）
_real_first_hit = _reg.first_hit


def _sabotage_first_hit(text, visible_only=True, **kw):
    # 强制返回「短词」那条声明：让路由做出错误选择
    for _k2, _c2 in _cmd_of.items():
        for _p2 in (_DECL.get(_k2) or {}).get("patterns") or []:
            if _reg.hits(_c2) and any(
                    getattr(h, "key", None) == _k2 for h in _reg.hits(text)) and _c2 != text:
                return type("H", (), {"key": _k2})()
    return _real_first_hit(text, visible_only=visible_only, **kw)


_reg.first_hit = _sabotage_first_hit
try:
    _sabot = []
    for _short, _long in _pairs:
        _h = _reg.first_hit(_long, visible_only=True)
        _exp = next((k for k, c in _cmd_of.items() if c == _long), None)
        _g = getattr(_h, "key", None) if _h is not None else None
        if _g != _exp:
            _sabot.append((_long, _exp, _g))
    check("★ 有牙：制造错误路由后 B 组判据必须能识破",
          len(_sabot) > 0, ("未能识破的对数", len(_sabot)))
finally:
    _reg.first_hit = _real_first_hit

check("★ 反证还原后路由恢复正常",
      all(getattr(_reg.first_hit(l, visible_only=True), "key", None)
          == next((k for k, c in _cmd_of.items() if c == l), None)
          for _s, l in _pairs))

print(chr(10) + "=== 结果 PASS=%d FAIL=%d ===" % (PASS, FAIL))
if FAILURES:
    print("失败项：" + ", ".join(FAILURES))
sys.exit(1 if FAIL else 0)
