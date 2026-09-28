# -*- coding: utf-8 -*-
"""L246 同族未收口门禁：伤害浮动幅度 `variance` 已下沉 `FORMULA_SKELETON`，注入面**真的通**。

背景（Step 0p：台账点了 1 处、同形态另有其人）
------------------------------------------------
L246（`8b1fa0a`）把 `battle/actions.py` 的 6 处写死平衡数值下沉了，但**同一笔账的邻支**
留在原地：`variance`（伤害浮动幅度 0.15）共三处硬编码

  ① `formulas.calc_damage(...)` 的**签名默认值**
  ② `formulas.resolve_formula(...)` 的**签名默认值**
  ③ `actions._roll_damage` expr 段的**实参** `variance=0.15`

它是**玩家可见的平衡数值**：浮动幅度决定「同一技能两次出手伤害差多少」，
而内容侧当时零配置面 —— 第二款游戏要改自己的手感只能改引擎。本批补齐，
**下沉到既有的 `formula_skeleton_fn` 注入面**（承 V4 / E2 / L246 三批先例），
不新开第二张表 / 第二套注入面。

修法上有一处**必须这么写**的约束（别改成签名默认值调 getter）
------------------------------------------------------------
签名默认值写成 `variance=None`，**函数体里**回落 `damage_variance()`。
理由：`import` 期内容侧的 `formula_skeleton_fn` 可能还没装配，在**默认参数表达式**里
调 getter 会把「装配时序」绑死在 import 上（本项目已有 `config` 的 `get_hook` 契约）。
`resolve_formula` 只把 `variance` 原样转交 `calc_damage` ⇒ **单一回落点**。

本测试钉五件事（**缺一即红**）
--------------------------------
A. 中性默认值 = 原写死值 0.15（未装配）⇒ 玩家可见行为零变化（迁移不改行为的正证）。
B. 注入面真的通：装上 `formula_skeleton_fn` 改挂载值 ⇒ getter 跟着变（不是假 getter）。
C. **回落只认 None**（签名默认是 0 不被吞）+ 内容侧可把浮动关到 0.0（钉"0 合法"）。
D. 读点已收口：三处**真代码行**里不再有 `variance=0.15`（注释/docstring 不算）。
E. 反证锚点：把签名的 `None` 哨兵改回写死 `0.15` / 把 getter 改回字面量 ⇒ 必红
   （防"门禁空转恒绿"—— 同 L246 既有门禁与 `test_gates_*` 的纪律）。

跑法：python tests/test_l246_variance_surface.py
"""
import ast
import io
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, FW_ROOT)
sys.path.insert(0, os.path.join(FW_ROOT, "extends"))

from saintess_engine import config as _cfg            # noqa: E402
from extends.ext_combat.battle import formulas as F  # noqa: E402

PASS = 0
FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % label)
    else:
        FAIL += 1
        print("  [FAIL] %s %s" % (label, extra))


def _strip_doc_and_comments(src):
    """返回「剔掉注释与字符串字面量」的源码行集合（判据扫**真代码**，非说明文字）。"""
    tree = ast.parse(src)
    kill = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for ln in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                kill.add(ln)
    out = []
    for i, ln in enumerate(src.splitlines(), 1):
        s = ln.strip()
        if not s or s.startswith("#") or i in kill:
            continue
        out.append((i, s))
    return out


print("== A. 中性默认值 = 原写死值（未装配）==")
_saved = _cfg.get_hook("formula_skeleton_fn")
try:
    if hasattr(_cfg, "set_hook"):
        _cfg.set_hook("formula_skeleton_fn", None)
except Exception:
    pass
check("damage_variance() = 0.15（原写死）", F.damage_variance() == 0.15, "got=%r" % F.damage_variance())
check("未装配时 _NEUTRAL_SKELETON 声明 damage.variance",
      F._NEUTRAL_SKELETON.get("damage", {}).get("variance") == 0.15,
      "got=%r" % (F._NEUTRAL_SKELETON.get("damage"),))

print("== B. 注入面真的通（内容侧可覆盖）==")
_mounted = {"damage": {"variance": 0.05}}


def _fake_skeleton():
    return dict(_mounted)


try:
    if hasattr(_cfg, "set_hook"):
        _cfg.set_hook("formula_skeleton_fn", _fake_skeleton)
except Exception as _e:
    print("  [WARN] set_hook 不可用：%r" % _e)
check("挂载后 damage_variance() = 0.05", F.damage_variance() == 0.05, "got=%r" % F.damage_variance())

# C-1 内容侧可把浮动**关到 0.0**（钉"0 是合法值"，防回落把它吞成默认）
_mounted["damage"]["variance"] = 0.0
check("内容侧声明 0.0 ⇒ getter 返 0.0（回落只认 None，不吞合法 falsy）",
      F.damage_variance() == 0.0, "got=%r" % F.damage_variance())

# C-2 显式传 0.0 也要透传（签名不吞）
import random as _rnd                                   # noqa: E402
_rnd.seed(7)
_got_zero = F.calc_damage(100, 0, dmg_type="true", level=1)
check("内容侧配 0.0 ⇒ calc_damage 零浮动（多跑取 min/max 判波动消失）",
      _got_zero == 100, "got=%r（期望 100 = 100×(1±0)）" % _got_zero)

_mounted["damage"]["variance"] = 0.15
_rnd.seed(11)
_seen = {F.calc_damage(100, 0, dmg_type="true", level=1) for _ in range(40)}
check("内容侧配 0.15 ⇒ 浮动恢复（40 次出现 >1 个值）", len(_seen) > 1, "got=%r" % _seen)

# 还原
try:
    if hasattr(_cfg, "set_hook"):
        _cfg.set_hook("formula_skeleton_fn", _saved)
except Exception:
    pass
check("还原后回到 0.15", F.damage_variance() == 0.15, "got=%r" % F.damage_variance())

print("== D. 读点已收口（三处真代码行无 variance=0.15）==")
_FORMULAS = os.path.join(FW_ROOT, "extends", "ext_combat", "battle", "formulas.py")
_ACTIONS = os.path.join(FW_ROOT, "extends", "ext_combat", "battle", "actions.py")
_res = []
for _p, _tag in ((_FORMULAS, "formulas.py"), (_ACTIONS, "actions.py")):
    for _i, _ln in _strip_doc_and_comments(io.open(_p, encoding="utf-8").read()):
        if re.search(r"variance\s*=\s*0\.15", _ln):
            _res.append("%s:%d %s" % (_tag, _i, _ln))
check("真代码行里无写死的 variance=0.15（注释/docstring 不算）", not _res, "残留=%r" % _res)

# 签名必须是 None 哨兵（不是回填 0.15）
_fsrc = io.open(_FORMULAS, encoding="utf-8").read()
_ftree = ast.parse(_fsrc)
# 形参表：位置参数在前、kwonly 在后，各自带 .value（默认表达式或 None）
_sigs = {}
for _n in _ftree.body:
    if isinstance(_n, ast.FunctionDef) and _n.name in ("calc_damage", "resolve_formula"):
        _pos = list(_n.args.args)
        _pos_def = list(_n.args.defaults)
        _pos_map = {}
        _off = len(_pos) - len(_pos_def)
        for _i, _a in enumerate(_pos):
            _pos_map[_a.arg] = _pos_def[_i - _off] if _i >= _off else None
        for _a, _d in zip(_n.args.kwonlyargs, _n.args.kw_defaults):
            _pos_map[_a.arg] = _d
        if "variance" in _pos_map:
            _sigs[_n.name] = _pos_map["variance"]


def _default_of(name):
    """形参的默认表达式：缺省 = None（形参不存在）；显式 None 也返回 ast.Constant(None)。"""
    return _sigs.get(name, "MISSING")


# ① resolve_formula 的 variance 默认值必须字面是 None
_v_rf = _default_of("resolve_formula")
check("resolve_formula 的 variance 默认值字面是 None（不是 0.15）",
      isinstance(_v_rf, ast.Constant) and _v_rf.value is None,
      "签名里 variance 默认值 = %r" % (ast.dump(_v_rf)[:60] if _v_rf != "MISSING" else "MISSING"))
# ② calc_damage 的 variance 必须**改为位置必填前移**或带 None 默认：它排在 is_crit 之后，
#    故必有默认表达式；该默认必须是 None（None 哨兵 = 函数体回落）
_v_cd = _default_of("calc_damage")
check("calc_damage 的 variance 默认值是 None 哨兵（函数体回落，非签名写死 0.15）",
      isinstance(_v_cd, ast.Constant) and _v_cd.value is None,
      "签名里 variance 默认值 = %r" % (ast.dump(_v_cd)[:60] if _v_cd != "MISSING" else "MISSING"))

print("== E. 反证锚点（防门禁空转恒绿）==")
_getter_node = next(n for n in _ftree.body
                    if isinstance(n, ast.FunctionDef) and n.name == "damage_variance")
check("getter 走 _skel_sub_num（真读骨架表，不是 return 0.15 字面量）",
      "_skel_sub_num" in ast.get_source_segment(_fsrc, _getter_node),
      "getter 体里没有 _skel_sub_num ⇒ 它是个假 getter（写死值）")
check("actions.py 的 expr 段实参已走 getter",
      "_F.damage_variance()" in _fsrc or
      "damage_variance()" in io.open(_ACTIONS, encoding="utf-8").read(),
      "actions.py 的 resolve_formula 调用点没有走 damage_variance()")

print("")
print("=== PASS=%d FAIL=%d ===" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
