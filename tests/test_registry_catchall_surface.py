# -*- coding: utf-8 -*-
"""registry.validate() —— 可见 catch-all 声明必须被点名（审计·批次1 第35轮）。

判据钉**性质**不钉源码形态：
  A 段 黑盒 —— 可见 catch-all 必被点名；不可见的平台 gate（_maint_gate 同款）**不**点名
  B 段 真实数据 —— 奥兰迪亚真包 commands.json 的 validate() 仍是 0 问题（本条不得误伤生产面）
  C 段 反证锚点 —— 防「判据恒绿空转」：探针组非空 / 探针互不相干 / 判据能认出真 catch-all
  D 段 边界 —— 半 catch-all（只吞部分文本）不点名；非法正则不重复报
"""
import io, json, os, re, sys
sys.path.insert(0, "C:/Users/yuyu/framework-engine")
from saintess_engine.command.registry import CommandRegistry, _is_catch_all, _CATCHALL_PROBES

PASS = FAIL = 0
def check(cond, label, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print("PASS  %s" % label)
    else: FAIL += 1; print("FAIL  %s %s" % (label, extra))

GATE = "^(?:\[At:[^\]]+\]\s*)?(?:\[At:全体成员\]\s*)?(?:\[引用消息[^\]]*\]\s*)?"   # 抄 _maint_gate
ANY  = "^.*$"
HALF = "背包.*"
BROKEN = "背包("

def mk(spec):
    reg = CommandRegistry(name="t").load({"k": spec})
    return reg

# ---------- A 段：黑盒（真正的那条判据） ----------
p = mk({"patterns": [ANY], "visible": True, "category": "系统", "desc": "d", "usage": "u"}).validate()
check(any("catch-all" in x for x in p), "A1 可见 catch-all 被点名", p)
check(any("k" in x and ANY in x for x in p), "A2 告警点名声明 key 与正则原文", p)

p2 = mk({"patterns": [GATE], "visible": False, "category": "系统", "desc": "d", "usage": "u"}).validate()
check(p2 == [], "A3 不可见平台 gate（同款零宽正则）不被点名", p2)

p3 = mk({"patterns": [ANY], "visible": True, "category": "系统", "desc": "d", "usage": "u",
                 "priority": 100}).validate()
check(any("catch-all" in x for x in p3), "A4 高 priority 也不例外（口径只看 visible）", p3)

# ---------- B 段：真实生产数据零误伤 ----------
REAL = "C:/Users/yuyu/framework-engine/games/orlandia/content/data/commands.json"
if os.path.exists(REAL):
    d = json.load(io.open(REAL, encoding="utf-8"))
    reg = CommandRegistry(name="orlandia").load(d)
    pv = reg.validate()
    check(pv == [], "B1 奥兰迪亚真包 validate() 仍为 0 问题（本条不得误伤生产面）", pv)
    check(not any(s.visible and any(_is_catch_all(x) for x in s.patterns) for s in reg.specs()),
          "B2 真包里所有 catch-all 都是不可见的（口径与真源数据一致）")
else:
    check(False, "B1 真包 commands.json 在位（子模块未检出 ⇒ 判据会假绿空转）")

# ---------- C 段：反证锚点（防恒绿） ----------
check(len(_CATCHALL_PROBES) >= 5, "C1 探针组非空且足够多", len(_CATCHALL_PROBES))
check(len(set(_CATCHALL_PROBES)) == len(_CATCHALL_PROBES), "C2 探针互不相同")
check(_is_catch_all(GATE) and _is_catch_all(ANY), "C3 判据认得真 catch-all")
check(not _is_catch_all("背包.*") and not _is_catch_all("^加点"), "C4 判据不把普通正则当 catch-all")

# ---------- D 段：边界 ----------
check(mk({"patterns": [HALF], "visible": True, "category": "c", "desc": "d", "usage": "u"}).validate() == [],
      "D1 只吞部分文本的 regex 不点名")
pb = mk({"patterns": [BROKEN], "visible": True, "category": "c", "desc": "d", "usage": "u"}).validate()
check(any("正则非法" in x for x in pb) and not any("catch-all" in x for x in pb),
      "D2 非法正则只报「正则非法」，不重复报 catch-all", pb)

print("\nPASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
