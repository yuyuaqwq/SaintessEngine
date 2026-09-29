# -*- coding: utf-8 -*-
"""`_lv_pressure` 等级压制曲线：docstring 与实跑一致（审计 afix1 第 26 轮）。

★ 起因：`_lv_pressure` 的 docstring 宣称「指数，封顶 ×0.30」，而代码是
  `for i in range(min(diff, 10))` + `max(0.30, mult)` —— 那个 `0.30` 下限
  **在 diff>=10 时永远不触发**（mult 停在 0.95^3*0.90^7 = 0.4101 > 0.30）。
  实跑 diff=11/15/30/59 四格**全部 410**，与 diff=10 同值 ⇒ 真实下界是 **×0.41**。

判据只加强零放宽：A 段是黑盒实跑（钉真实曲线，非钉 docstring 措辞）；
B 段钉 docstring 不得再宣称 0.30 封顶；C 段钉**曲线实现一字未动**（本次只改文档）。
"""
import sys, inspect, re
from ext_combat.battle.landing import _lv_pressure
OK=FAIL=0
def check(cond, label):
    global OK, FAIL
    if cond: OK+=1; print("PASS", label)
    else: FAIL+=1; print("FAIL", label)
class B: btype="pve"
b=B()
def d(atk,tgt,base=1000): return _lv_pressure(b,{"level":atk},{"level":tgt},base)
def dv(diff,base=1000): return d(1,1+diff,base)
# A 黑盒：真实曲线
check(dv(10)==410, "A1 diff=10 -> 410 (0.95^3*0.90^7 截断)")
check(dv(11)==dv(10)==dv(59)==410, "A2 diff>=10 恒 410（曲线已封顶）")
check(dv(59)!=300, "A3 ★ docstring 原写的 0.30 下界(300) 永不触发")
check(dv(4)==771, "A4 diff=4 -> 771 (跨 0.95->0.90 拐点)")
check(d(51,1)==d(81,1)==2691, "A5 高打低 diff>=50 恒 2691")
# B 判据：docstring 不得再宣称 0.30 封顶
src=inspect.getsource(_lv_pressure); doc=inspect.getdoc(_lv_pressure) or ""
check("×0.41" in doc, "B1 docstring 写明真实下界 ×0.41")
check(not re.search(r"指数，封顶\s*×0\.30", doc), "B2 ★ 原「指数，封顶 ×0.30」表述已删")
check("min(diff, 10)" in doc, "B3 docstring 点名 min(diff,10)")
# C 未改行为：曲线本身一字未动
check("min(diff, 10)" in src and "min(-diff, 50)" in src and "max(0.30, mult)" in src,
      "C1 曲线实现三处仍在（只改文档）")
# D 反证锚点：若代码真改成能到 0.30，B2/A3 会失去意义
check(0.95**3*0.90**7 > 0.30, "D1 封顶值 0.4101 > 0.30 ⇒ 0.30 是死下限（反证前提）")
print("RESULT ok=%d fail=%d" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
