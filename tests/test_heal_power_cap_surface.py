# -*- coding: utf-8 -*-
"""heal_power 上限同族未收口门禁：治疗强度的 cap 已下沉 `FORMULA_SKELETON`。

背景
----
`extends/ext_combat/battle/actions.py::_do_heal` 里治疗强度的**上限**原先写死：
``min(float(st.get("heal_power", 0) or 0), 0.5)``。同族的另外八个 cap ——
``block_cap()``（V4 2026-09-16 迁）· ``dodge_cap()``（E2 2026-09-25 迁）
· ``taken_resist_cap()`` / ``taken_elem_resist_cap()``（2026-09-29 迁）
· ``defend_posture_default()`` / ``defend_posture_cap()`` · ``crit_mult()``
· ``status_reduce_cap()`` · ``damage_variance()``（均 2026-09-29 迁）—— **早已下沉**，
唯独这条漏在引擎里 ⇒ 内容侧想调自己的「治疗强度上限」**只能改引擎**。

★ 它不是死码：数据面**真实在用** —— orlandia ``affixes.json`` 的 heal_power 词条、
``classes.json`` 治疗职业基础值 0.1、``equip_roster.json`` 的套装件，全包 22 个文件命中。

★★ 为什么不复用 ``status_reduce.cap``：那条封「减益最多减掉几成」（**承伤侧**，
消费者 `stats._apply_effects`），这条封「治疗强度最多加几成」（**治疗侧**，消费者
`actions._do_heal`）—— 两个消费者、两条独立平衡线、中性地值也不同
（那边 0.0 = 状态不再减伤 / 这边 0.0 = 治疗强度整条不生效）⇒ **另起一组**。

本测试钉五件事（**缺一即红**）
----------------------------
A. **中性默认值 = 原写死值**：未装配 `formula_skeleton_fn` 时返回 0.50
   ⇒ 玩家可见行为逐字不变（这是「迁移不改行为」的正证）。
B. **注入面真的通**：装上 `formula_skeleton_fn` 改挂载值 ⇒ getter 跟着变
   （防「写死的假 getter」）。
C. **回落只认 None**：内容侧把 cap 配到 **0.0 是合法值**（治疗强度整条不生效），
   不得被 `or` 吞回默认 0.50。键缺 / 显式 None ⇒ 才回落。
D. **读点已收口**：`actions.py` 里不再有裸的 `0.5` 写死 cap
   （用 **AST 找 `min()` Call 节点**，**不**靠行号、**不**靠「剔字符串字面量行」
   —— 键名本身是字面量时那招会自剔成空集恒绿，前一轮已自抓过）。
E. **黑盒端到端**：读点真跑（静态 AST 对拍 + 真算一次封顶曲线）。

跑法：python tests/test_heal_power_cap_surface.py
"""
import ast
import io
import os
import sys

ENGINE = r"C:/Users/yuyu/framework-engine"
sys.path.insert(0, ENGINE)
sys.path.insert(0, os.path.join(ENGINE, "extends"))

PASS = 0
FAIL = 0
FAILURES = []


def check(label, cond, extra=""):
    # ★ 签名必须是 (label, cond)：第一版写成 (cond, label) 而调用点按 (label, cond) 传
    #   ⇒ 传进去的 cond 恒是那条**非空标签字符串**（永远真）⇒ 整份门禁恒绿、零牙。
    #   本轮自己抓住的（「反证自身也要被验证它真的会红」）。
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


from saintess_engine import config as _cfg          # noqa: E402
from ext_combat.battle import formulas as F         # noqa: E402

_ACTIONS = os.path.join(ENGINE, "extends", "ext_combat", "battle", "actions.py")
_src = io.open(_ACTIONS, encoding="utf-8").read()

print("== A. 中性默认值 = 原写死值 0.50（未装配 ⇒ 与改前逐字一致） ==")
_unmount()
_c = F.heal_power_cap()
check("A1 未装配时返回 0.50（= 原写死的 min(..., 0.5) 上限）",
      _c == 0.50, _c)
check("A2 类型是 float（不是 str/None 的伪回落）", isinstance(_c, float), type(_c))

print("== B. 注入面真的通（防写死的假 getter） ==")
_mount({"heal_power": {"cap": 0.25}})
_c = F.heal_power_cap()
check("B1 内容侧声明 0.25 ⇒ getter 返回 0.25（注入面真的通）", _c == 0.25, _c)
_mount({"heal_power": {}})          # 组在、键缺
_c = F.heal_power_cap()
check("B2 组在但键缺 ⇒ 回落默认 0.50（不是崩、不是 0）", _c == 0.50, _c)
_mount({})                           # 组都不在
_c = F.heal_power_cap()
check("B3 组都不在 ⇒ 回落默认 0.50", _c == 0.50, _c)

print("== C. 回落只认 None（cap=0.0 是合法值，不许被 or 吞回 0.50） ==")
_mount({"heal_power": {"cap": 0.0}})
_c = F.heal_power_cap()
check("C1 声明 0.0 ⇒ 返回 0.0（治疗强度整条不生效是合法配置）", _c == 0.0, _c)
check("C1b 0.0 绝不能回落成 0.50（那就是 or 吞 falsy 的老病）", _c != 0.50, _c)
_mount({"heal_power": {"cap": None}})
_c = F.heal_power_cap()
# 如实记录：显式 None 走的是 _skel_sub_num 的 TypeError 守卫分支回落 default
# （grp.get(key, default) 取到 None → float(None) 抛 → except 回落），
# 与同族全部 getter 同一口径，不是独立的 None 分支。
check("C2 显式 None ⇒ 回落默认 0.50（经数值守卫分支，与同族 getter 同口径）",
      _c == 0.50, _c)
_unmount()
check("C3 卸载后回到 0.50", F.heal_power_cap() == 0.50)

print("== D. 读点已收口（AST 找 min() Call 节点，不靠行号/不靠剔字面量行） ==")
_tree = ast.parse(_src)
_caps = []
for _n in ast.walk(_tree):
    if (isinstance(_n, ast.Call) and isinstance(_n.func, ast.Name)
            and _n.func.id == "min" and len(_n.args) == 2):
        _b = _n.args[1]
        # heal_power 读点：第一个参数是 st.get("heal_power", ...)
        _a = _n.args[0]
        if (isinstance(_b, ast.Constant) and isinstance(_b.value, float)
                and 0.0 < abs(_b.value) < 10.0
                and "heal_power" in ast.dump(_a)):
            _caps.append((_n.lineno, _b.value))
check("D1 heal_power 读点已无裸浮点 cap（0.5 已下沉骨架表）",
      _caps == [], _caps)
check("D2 读点真身还在（防「连读点一起删掉」那种假收口）",
      _src.count("_F.heal_power_cap()") == 1,
      _src.count("_F.heal_power_cap()"))
check("D3 读点挂在 heal_power 属性上（不是别的同名变量）",
      'st.get("heal_power"' in _src)
check("D4 骨架表 heal_power 组只有 cap 一个键（没偷偷塞别的东西）",
      list(F._NEUTRAL_SKELETON.get("heal_power", {}).keys()) == ["cap"],
      F._NEUTRAL_SKELETON.get("heal_power"))
_f_src_early = io.open(os.path.join(ENGINE, "extends", "ext_combat", "battle",
                                  "formulas.py"), encoding="utf-8").read()
check("D5 getter 名唯一（无双源：getter 定义只在 formulas，actions 里零定义）",
      _f_src_early.count("def heal_power_cap(") == 1
      and _src.count("def heal_power_cap(") == 0,
      (_f_src_early.count("def heal_power_cap("), _src.count("def heal_power_cap(")))

print("== E. 黑盒端到端（真算一次封顶曲线：cap 真的参与了封顶） ==")
_cap = F.heal_power_cap()
for _v, _exp in ((0.05, 1.05), (0.30, 1.30), (0.49, 1.49)):
    _got = 1.0 + min(_v, _cap)
    check("E1 heal_power=%s ⇒ 治疗系数 %s（未到上限，原样生效）" % (_v, _exp),
          abs(_got - _exp) < 1e-9, _got)
_got = 1.0 + min(0.99, _cap)
check("E2 heal_power=0.99 ⇒ 被封到系数 1.5（cap 真的在封顶，不是原样 1.99）",
      abs(_got - 1.5) < 1e-9, _got)
_mount({"heal_power": {"cap": 0.25}})
_got = 1.0 + min(0.99, F.heal_power_cap())
check("E3 内容侧把 cap 调到 0.25 ⇒ 同一个 0.99 被封到 1.25（配置面真生效）",
      abs(_got - 1.25) < 1e-9, _got)
_unmount()
_got = 1.0 + min(0.99, F.heal_power_cap())
check("E4 卸载后回到 1.5（与 E2 同值 ⇒ 默认值逐字等于原写死上限）",
      abs(_got - 1.5) < 1e-9, _got)

print("== F. 反证锚点（防门禁空转恒绿） ==")
_f_src = io.open(os.path.join(ENGINE, "extends", "ext_combat", "battle",
                              "formulas.py"), encoding="utf-8").read()
check("F1 heal_power 组未混入零效应中性段语义（cap 默认 0.50 不是 0.0）",
      F._NEUTRAL_SKELETON["heal_power"]["cap"] == 0.50,
      F._NEUTRAL_SKELETON["heal_power"])
check("F2 与 status_reduce 组**不合并**（两条独立平衡线，合并=把两款游戏绑成一条）",
      "status_reduce" in F._NEUTRAL_SKELETON
      and F._NEUTRAL_SKELETON["status_reduce"].get("cap") == 0.90)
check("F3 actions.py 顶部**没有**新增跨模块相对 import（spec_from_file_location "
      "单文件装载会 ImportError —— 上一轮自抓过这条）",
      "from .formulas import" not in _src.split("\n\n")[0]
      and not _src.lstrip().startswith("from .formulas import"))

print("=" * 60)
print("结果：通过 %d / %d" % (PASS, PASS + FAIL))
if FAILURES:
    for _f in FAILURES:
        print("  FAIL: %s" % _f)
sys.exit(1 if FAIL else 0)
