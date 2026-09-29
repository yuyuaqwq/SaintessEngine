# -*- coding: utf-8 -*-
"""暴击倍率已下沉 FORMULA_SKELETON（同族未收口门禁，承 L246 / L566 / L248 五批先例）。

背景（本项是该族的**第 6 次**命中）
------------------------------------------------------------------------------------
`calc_damage` 里**两个**暴击倍率落点一直写死字面量 `1.5`：

  · 声明路径（槽位 `damage` 绑了声明时）：`"crit_mult": 1.5 if is_crit else 1.0`
  · 旧路径（未绑定的包走这条）：        `dmg = int(dmg * 1.5)`

它是**玩家可见的平衡数值**（决定「暴击打出多大成伤」），而内容侧**零配置面**：
两个读点在 orlandia / aetheran-package 全仓**零命中** ⇒ 第二款游戏想改自己的暴击
倍率**只能改引擎**。同族的 `lucky.mult = 1.3`（幸运一击倍率）早已下沉（`8b1fa0a`），
唯独暴击这两个漏在原地 —— 一次收口只覆盖被点名的那个落点，邻支不会顺带修掉。

修法 = 下沉到**既有** `formula_skeleton_fn` 注入面（不新开第二张表 / 第二套注入面）；
默认值取原写死值 1.5 ⇒ 与已装内容**逐字一致**、玩家可见行为零变化。
★ 默认值**不在零效应中性段**：归零 = 暴击不加成伤（另一个平衡选择，不是「没有这条规则」）。

本测试钉六件事（**缺一即红**）
--------------------------------
A. 中性默认值 = 原写死值 1.5（未装配）⇒ 迁移不改行为的正证。
B. 注入面真的通：装上 formula_skeleton_fn 改挂载值 ⇒ getter 跟着变（不是假 getter）。
C. **回落只认 None**（内容侧可把倍率关到 0.0 = 暴击不加成伤，钉「0 合法」）。
D. 读点已收口：两条**真代码行**里不再有写死的 1.5 暴击倍率（注释/docstring 不算）。
E. **黑盒端到端**：`calc_damage` 真跑 —— 未装配时 1000 伤暴击仍打 1500（逐字不变）；
   声明 crit.mult=2.0 后同一格打 2000 ⇒ 注入面真的进了计算。
F. 反证锚点：getter 改回字面量 / 读点改回硬编码 ⇒ 必红（防「门禁空转恒绿」）。

跑法：python tests/test_crit_mult_surface.py
"""
import ast
import io
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, FW_ROOT)
sys.path.insert(0, os.path.join(FW_ROOT, "extends"))

from saintess_engine import config as _cfg                       # noqa: E402
from extends.ext_combat.battle import formulas as F              # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []

FORMULAS = os.path.join(FW_ROOT, "extends", "ext_combat", "battle", "formulas.py")


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % label)
    else:
        FAIL += 1
        FAILURES.append(label)
        print("  [FAIL] %s %s" % (label, extra))


def _unmount():
    try:
        if hasattr(_cfg, "set_hook"):
            _cfg.set_hook("formula_skeleton_fn", None)
    except Exception:
        pass


def _mount(skel):
    import copy
    data = copy.deepcopy(F._NEUTRAL_SKELETON)
    for k, v in (skel or {}).items():
        if isinstance(v, dict) and isinstance(data.get(k), dict):
            data[k].update(v)
        else:
            data[k] = v
    _cfg.set_hook("formula_skeleton_fn", lambda: data)
    return data


print("== A. 中性默认值 = 原写死值 1.5（未装配 ⇒ 与改前逐字一致） ==")
_unmount()
check("A1 未装配时 crit_mult() == 1.5（原字面量）", F.crit_mult() == 1.5, F.crit_mult())
check("A2 中性骨架表里 crit.mult 已声明且为 1.5",
      F._NEUTRAL_SKELETON.get("crit", {}).get("mult") == 1.5,
      F._NEUTRAL_SKELETON.get("crit"))

print("== B. 注入面真的通（防假 getter） ==")
_mount({"crit": {"mult": 2.0}})
check("B1 声明 crit.mult=2.0 ⇒ getter 返回 2.0", F.crit_mult() == 2.0, F.crit_mult())
_mount({"crit": {"mult": 1.25}})
check("B2 换成 1.25 ⇒ getter 跟着变", F.crit_mult() == 1.25, F.crit_mult())
_mount({"crit": {}})   # 组在、键缺
check("B3 crit 组缺 mult 键 ⇒ 回落 1.5（不 KeyError）", F.crit_mult() == 1.5, F.crit_mult())

print("== C. 回落只认 None（0 是合法值：暴击不加成伤） ==")
_mount({"crit": {"mult": 0.0}})
check("C1 声明 0.0 ⇒ getter 返回 0.0（不被吞成 1.5）", F.crit_mult() == 0.0, F.crit_mult())
_mount({"crit": {"mult": None}})
check("C2 声明 None ⇒ 回落 1.5", F.crit_mult() == 1.5, F.crit_mult())
_unmount()
check("C3 回落后仍是 1.5", F.crit_mult() == 1.5, F.crit_mult())

print("== D. 读点已收口：真代码行里不再有写死的 1.5 暴击倍率 ==")
_src = io.open(FORMULAS, encoding="utf-8").read()
_tree = ast.parse(_src)
_hard = []
for _n in ast.walk(_tree):
    if isinstance(_n, ast.Constant) and isinstance(_n.value, float) and _n.value == 1.5:
        _ln = _src.splitlines()[_n.lineno - 1].strip()
        if _ln.startswith("#") or _ln.startswith('"') or _ln.startswith("*"):
            continue
        _hard.append("%s:%d %s" % (os.path.basename(FORMULAS), _n.lineno, _ln[:70]))
# 允许的：中性骨架表声明处 + getter 的回落默认（都是「默认值」，不是读点）
_allowed = 2
check("D1 calc_damage 两条读点已无写死 1.5（余下只应是骨架表声明 + getter 默认）",
      len(_hard) <= _allowed, _hard)
check("D2 声明路径用 _cm := crit_mult()（不是字面量三元）",
      '"crit_mult": _cm if is_crit else 1.0' in _src)
check("D3 旧路径调 crit_mult()（不是 dmg * 1.5）",
      "dmg = int(dmg * crit_mult())" in _src)
check("D4 两处读点共用同一个 getter（无第二处字面量回落）",
      _src.count("crit_mult()") >= 3, _src.count("crit_mult()"))

print("== E. 黑盒端到端：calc_damage 真跑 ==")
_unmount()
random.seed(20260929)
d = F.calc_damage(1000, 0, is_crit=True, variance=0.0)
check("E1 未装配：1000 伤暴击仍打 1500（与改前逐字一致）", d == 1500, d)
d2 = F.calc_damage(1000, 0, is_crit=False, variance=0.0)
check("E2 未装配：非暴击仍打 1000", d2 == 1000, d2)
_mount({"crit": {"mult": 2.0}})
d3 = F.calc_damage(1000, 0, is_crit=True, variance=0.0)
check("E3 声明 2.0：1000 伤暴击打 2000（注入面真进了计算）", d3 == 2000, d3)
_mount({"crit": {"mult": 0.0}})
d4 = F.calc_damage(1000, 0, is_crit=True, variance=0.0)
# 注意：结果不是 1000 而是 **1**。`calc_damage` 末尾有不可绕过的伤害下限
# `max(1, dmg)`（防 ZeroDivision / 伤害归零），它是**引擎不变量**、与本次改动无关。
# 这里语义链的是：0 被当成**合法倍率**了。若 0 被 `or` 吞掉回落 1.5
# 就会打 1500（旧行为），而不是 1 ⇒ 口径本身被验证。
check("E4 声明 0.0：0 被当合法倍率（伤害落到引擎下限 1，"
      "而非被吞回落 1.5 打 1500）", d4 == 1, d4)
check("E4b 同样的 0.0 下非暴击仍打 1000（下限不是本次引入）",
      F.calc_damage(1000, 0, is_crit=False, variance=0.0) == 1000)
_unmount()
d5 = F.calc_damage(1000, 0, is_crit=True, variance=0.0)
check("E5 卸载后回到 1500", d5 == 1500, d5)

print("== F. 反证锚点（防门禁空转恒绿；本段只做静态自检，运行期反证由我手工跑） ==")
check("F1 getter 名唯一（无双源）", _src.count("def crit_mult(") == 1)
check("F2 骨架表 crit 组只有 mult 一个键（没有偷偷塞别的东西）",
      list(F._NEUTRAL_SKELETON.get("crit", {}).keys()) == ["mult"],
      F._NEUTRAL_SKELETON.get("crit"))
check("F3 落点清单 = 2（声明路径 + 旧路径），不是 1（防只修一半）",
      _src.count("crit_mult()") - 1 >= 2, _src.count("crit_mult()"))

print("=" * 60)
print("结果：通过 %d / %d" % (PASS, PASS + FAIL))
if FAILURES:
    for _f in FAILURES:
        print("  FAIL: %s" % _f)
sys.exit(1 if FAIL else 0)
