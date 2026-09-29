# -*- coding: utf-8 -*-
"""L248/L566/L246 同族未收口门禁：防御姿态的缺省减伤与技能值上界已下沉 `FORMULA_SKELETON`。

背景
----
`extends/ext_combat/battle/landing.py::deal_damage` 的「防御姿态」段原先把**两个
玩家可见平衡数值**写死：缺省减伤 `_dr = 0.5` 与技能自带值的合法上界 `<= 0.95`。
同族的另外四个 cap —— `block_cap()`（V4 2026-09-16 迁）· `dodge_cap()`（E2 2026-09-25 迁）
· `taken_resist_cap()` · `taken_elem_resist_cap()`（均 2026-09-29 迁）—— **早已下沉**，
唯独这两个漏在引擎里 ⇒ 内容侧要调自己的防御姿态只能改引擎。

★★ 本批挖到的**真缺陷**（不止是「可配性」）
原判据是「`defend_reduce` 落在 `0 <= v <= 0.95` 才采纳」，于是**超界的值被整条丢掉**、
静默回落到缺省 0.5 —— 技能数据写「挡 99%」实跑只有「挡 50%」，**零报错、零诊断**。
（真跑取证：改前 `defend_reduce=0.99` → 实落伤害 500（= 减 50%），改后 → 50（= 减 95%）。）
现口径：**非数 → 回落缺省；是数 → 按 cap 封顶**。

本测试钉四件事（**缺一即红**）
----------------------------
A. **中性默认值 = 原写死值**：未装配 `formula_skeleton_fn` 时两个 getter 逐字返回
   0.50 / 0.95 ⇒ 玩家可见行为零变化（这是「迁移不改行为」的正证）。
B. **注入面真的通**：装上 `formula_skeleton_fn` 改挂载值 ⇒ getter 跟着变
   （证明内容侧能覆盖，不是写死的假 getter）。
C. **读点已收口**：`landing.py` 里不再有裸的 `0.5` 缺省与 `<= 0.95` 上界判据。
D. **黑盒端到端真跑 `deal_damage`**：9 格逐格比对（缺省 / 常用值 / 超界 / 下界 /
   bool / 字符串 / 负数），并**钉住那条静默失效已消失**（0.99 必须是 95% 减伤，
   而不是回落 50%）。

跑法：python tests/test_defend_posture_surface.py
"""
import ast
import io
import os
import sys
import types

ENGINE = r"C:/Users/yuyu/framework-engine"
sys.path.insert(0, ENGINE)
sys.path.insert(0, os.path.join(ENGINE, "extends"))

PASS, FAIL = 0, []
TOTAL = [0]


def check(cond, label, extra=""):
    TOTAL[0] += 1
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(f"{label}{(' :: ' + str(extra)) if extra else ''}")


from ext_combat.battle import formulas as F          # noqa: E402
from ext_combat.battle import landing as L           # noqa: E402
from ext_combat.battle.actors import DEFEND_TAG, open_window   # noqa: E402


# ═══════════════════════════════ A. 中性默认值 = 原写死值
def test_neutral_defaults():
    saved = F._skeleton
    F._skeleton = lambda: F._NEUTRAL_SKELETON
    try:
        check(F.defend_posture_default() == 0.50,
              "A1 中性缺省 = 0.50（原写死值）", F.defend_posture_default())
        check(F.defend_posture_cap() == 0.95,
              "A2 中性上界 = 0.95（原写死值）", F.defend_posture_cap())
    finally:
        F._skeleton = saved


# ═══════════════════════════════ B. 注入面真的通
def test_injection_surface():
    saved = F._skeleton
    try:
        F._skeleton = lambda: {"defend_posture": {"default": 0.25, "cap": 0.60}}
        check(F.defend_posture_default() == 0.25,
              "B1 内容侧改 default ⇒ getter 跟着变", F.defend_posture_default())
        check(F.defend_posture_cap() == 0.60,
              "B2 内容侧改 cap ⇒ getter 跟着变", F.defend_posture_cap())
        # 子组整个缺失 ⇒ 回落原写死值，不崩
        F._skeleton = lambda: {}
        check(F.defend_posture_default() == 0.50 and F.defend_posture_cap() == 0.95,
              "B3 子组缺失 ⇒ 回落原写死值，不崩")
    finally:
        F._skeleton = saved


# ═══════════════════════════════ C. 读点已收口（AST，不靠行号）
def test_readpoint_collapsed():
    path = os.path.join(ENGINE, "extends", "ext_combat", "battle", "landing.py")
    src = io.open(path, encoding="utf-8").read()
    tree = ast.parse(src)

    # C1：防御姿态段内不得再出现裸 0.5 缺省（赋值形态）
    bare_default = False
    for n in ast.walk(tree):
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name)
                and n.targets[0].id == "_dr"
                and isinstance(n.value, ast.Constant)
                and isinstance(n.value.value, (int, float))
                and n.value.value == 0.5):
            bare_default = True
    check(not bare_default, "C1 landing 不再有裸 `_dr = 0.5` 缺省", "仍写死")

    # C2：不得再有 `<= 0.95` 这个上界判据（比较形态）
    bare_cap = False
    for n in ast.walk(tree):
        if isinstance(n, ast.Compare):
            for op, cmp in zip(n.ops, n.comparators):
                if isinstance(cmp, ast.Constant) and isinstance(cmp.value, (int, float)) \
                        and abs(float(cmp.value) - 0.95) < 1e-9:
                    bare_cap = True
    check(not bare_cap, "C2 landing 不再有裸 `<= 0.95` 上界判据", "仍写死")

    # C3：两个 getter 各只有一个回落点（= 各自一处 _skel_sub_num 调用）
    fpath = os.path.join(ENGINE, "extends", "ext_combat", "battle", "formulas.py")
    fsrc = io.open(fpath, encoding="utf-8").read()
    for fn in ("defend_posture_default", "defend_posture_cap"):
        check(fsrc.count(f'def {fn}(') == 1, f"C3a {fn} 只有一个定义", fsrc.count(f'def {fn}('))
    check(fsrc.count('"defend_posture": {"default"') == 1,
          "C3b 中性骨架恰好一条 defend_posture 声明")
    check(landing_uses_guard(src), "C4 读点改走 getter（落地段真调 defend_posture_default）")


def landing_uses_guard(src: str) -> bool:
    """防御姿态段真调了 getter（不是只在别处定义）。"""
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr in ("defend_posture_default", "defend_posture_cap"):
            return True
    return False


# ═══════════════════════════════ D. 黑盒端到端真跑 deal_damage
def _one(dr, dmg=1000):
    t = {"uid": "u1", "name": "T", "max_hp": 1000, "hp": 1000,
         "effects": {}, "side": "enemy"}
    open_window(t, DEFEND_TAG, value=1, expire=None)
    return L.deal_damage(types.SimpleNamespace(btype="pve"), {}, t, dmg, [],
                         dmg_kind="phys", defend_reduce=dr)


def test_end_to_end():
    # ★ 改前/改后必须逐格相同的三格（= 「迁移不改行为」的正证）
    check(_one(None) == 500, "D1 缺省 ⇒ 减 50%（与改前逐字相同）", _one(None))
    check(_one(0.8) == 199, "D2 技能自带 0.8 ⇒ 与改前逐字相同", _one(0.8))
    check(_one(0.0) == 1000, "D3 技能自带 0.0（合法：完全不减伤）", _one(0.0))

    # ★★ 本批的核心：超界值**不再被静默丢弃**
    check(_one(0.99) == 50, "D4 ★超界 0.99 ⇒ 按 cap 封顶减 95%（改前静默回落成减 50%）",
          _one(0.99))
    check(_one(1.5) == 50, "D5 超界 1.5 ⇒ 同样封顶", _one(1.5))
    check(_one(0.95) == 50, "D6 恰好等于上界 ⇒ 全额采纳", _one(0.95))

    # 非数 / 布尔 ⇒ 回落缺省（**不**把 True 当 1.0 = 减 100%）
    check(_one(True) == 500, "D7 bool True ⇒ 回落缺省（不当作 1.0）", _one(True))
    check(_one("0.8") == 500, "D8 字符串 ⇒ 回落缺省", _one("0.8"))
    # 负数 ⇒ 夹到 0（不减伤），不产生「加伤」
    check(_one(-0.2) == 1000, "D9 负值 ⇒ 夹到 0 = 完全不减伤（不加伤）", _one(-0.2))


for fn in (test_neutral_defaults, test_injection_surface, test_readpoint_collapsed,
           test_end_to_end):
    try:
        fn()
    except Exception as exc:                     # noqa: BLE001
        import traceback
        FAIL.append(f"{fn.__name__} 抛异常：{exc}")
        traceback.print_exc()

print("=" * 60)
print(f"防御姿态下沉门禁：{PASS}/{TOTAL[0]} 通过")
if FAIL:
    print(f"✗ {len(FAIL)} 条失败：")
    for f in FAIL:
        print("   ✗", f)
    sys.exit(1)
print("✅ 全绿")
sys.exit(0)
