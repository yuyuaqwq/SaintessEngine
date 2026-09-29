# -*- coding: utf-8 -*-
"""afix2：_apply_death_guard 不得「扣了层却没保住命」（写口顺序·无部分写）。

判据只认**行为**：真调生产函数 landing._apply_death_guard，注入一个会抛的
属性写口，断言「抛 => 状态原样」；再钉住正常路径四种形态逐值不变。
不重写一遍实现（Step 0f：那会变成测判据自己）。
"""
import sys, os
sys.path.insert(0, r"C:/Users/yuyu/framework-engine")
sys.path.insert(0, r"C:/Users/yuyu/framework-engine/extends")
from ext_combat.battle import landing as L

FAILS = []
def chk(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("FAIL:", msg)

def _mk(stacks, expire=0, mhp=1000, hp=0):
    return {"name": "目标", "hp": hp, "max_hp": mhp,
            "effects": {"death_guard": {"stacks": stacks, "expire": expire}}}

def _call(t, battle=None):
    cap = []
    oc = L._cue
    L._cue = lambda b, l, k, p=None: cap.append(k)
    try:
        r = L._apply_death_guard(battle if battle is not None else {"name": "b"}, t, [])
    finally:
        L._cue = oc
    return r, cap

# ── §1 抛错路径：层与条目必须原样留下（真缺陷的原形态）────────────────
for stacks in (1, 2, 5):
    t = _mk(stacks)
    orig = L.ATTR.set_current
    def boom(*a, **k):
        raise RuntimeError("属性层炸")
    L.ATTR.set_current = boom
    try:
        r, cap = _call(t)
    finally:
        L.ATTR.set_current = orig
    dg = t["effects"].get("death_guard")
    chk(dg is not None, "§1 stacks=%d 抛错后 death_guard 条目被删了（层白扣）" % stacks)
    chk(dg is not None and dg.get("stacks") == stacks,
        "§1 stacks=%d 抛错后层数被扣：%r（应原样 %d）" % (stacks, dg, stacks))
    chk(t["hp"] == 0, "§1 stacks=%d 抛错后 hp 被改了：%r" % (stacks, t["hp"]))
    chk(r is False, "§1 stacks=%d 抛错后返回 %r（应 False=没触发）" % (stacks, r))
    chk(cap == [], "§1 stacks=%d 抛错后仍发了 cue %r" % (stacks, cap))

# ── §2 正常路径：四种形态逐值钉住（防止修过头）────────────────────────
r, cap = _call(_mk(1, 0))
t = _mk(1, 0); r, cap = _call(t)
chk(r is True, "§2 正常路径没触发")
chk(t["hp"] == 100, "§2 保底 hp=%r（应 100 = max_hp×0.10）" % t["hp"])
chk("death_guard" not in t["effects"], "§2 最后一层 + 无 expire 应清条目")
chk(cap == ["battle.landing.death_guard"], "§2 cue 应恰好一条：%r" % cap)

t = _mk(3, 0); r, cap = _call(t)
chk(t["effects"]["death_guard"]["stacks"] == 2, "§2 3 层应剩 2")
chk("death_guard" in t["effects"], "§2 还有层时条目应保留")

t = _mk(1, 60); r, cap = _call(t)
chk(t["effects"]["death_guard"]["stacks"] == 0, "§2 expire 存在时层应减到 0")
chk("death_guard" in t["effects"], "§2 有 expire 时条目应保留（交给到期清）")

t = _mk(0, 0); r, cap = _call(t)
chk(r is False, "§2 无层不该触发")
chk(cap == [], "§2 无层不该发 cue")
chk("death_guard" in t["effects"], "§2 无层不该动条目")

# ── §3 防复发：写口顺序（层减必须在保命之后）──────────────────────────
import ast, inspect
src = inspect.getsource(L._apply_death_guard)
tree = ast.parse(src.replace("\t", " "))
fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
lns = {}
for n in ast.walk(fn):
    if isinstance(n, ast.Assign) and n.targets and isinstance(n.targets[0], ast.Subscript):
        key = ast.unparse(n.targets[0])
        lns.setdefault(key, n.lineno)
    if isinstance(n, ast.Call):
        nm = ast.unparse(n.func)
        if nm.endswith("set_current"):
            lns.setdefault("ATTR.set_current", n.lineno)
dec = lns.get("entry['stacks']") or lns.get('entry["stacks"]')
setc = lns.get("ATTR.set_current")
chk(dec is not None and setc is not None, "§3 没找到两个写口（判据自身失效）")
if dec is not None and setc is not None:
    chk(setc < dec, "§3 层减(L%d) 必须晚于保命写口(L%d)" % (dec, setc))

print("\n=== afix2 death_guard: %d 条 ===" % (len(FAILS) and -1 or 0))
if FAILS:
    print("FAILED %d" % len(FAILS))
    raise SystemExit(1)
print("PASS 0")
