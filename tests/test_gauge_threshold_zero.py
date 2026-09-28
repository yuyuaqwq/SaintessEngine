# -*- coding: utf-8 -*-
"""门禁：敌身资源条（enemy_bar）阈值口径 —— 回落只认缺键，合法 0 原样保留（审计 L251 同族）。

**这个门禁守住什么**
`bar_trigger` 的阈值递增三参数 `threshold_base/inc/cap` 原先写成
`float(bd.get(k, D) or E)`。`or` 会把**合法 0** 吞成 E，而对这三个乘区来说
0 与缺键语义完全相反：

* `threshold_inc = 0`  → 语义是「阈值不递增」；被吞成 1.0 → 照样每次 +35%
* `threshold_cap = 0`  → 语义是「不封顶」；被吞成 1.0 → 变成「阈值 = base」
* `threshold_base = 0`→ 语义是「零蓄积即触发」；被吞成 50 → 触发后凭空按 50 重算

同时 `threshold_base` 的**同一个声明默认**在两个读点有两套值
（`bar_state` 回落 0 / `bar_trigger` 回落 50）⇒ 缺键时初始阈值与封顶基数分叉。

**零游戏、零宿主**：注入假 `enemy_bar` 配置，不碰内容侧真实数据、不 sleep。

跑法：python tests/test_gauge_threshold_zero.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, FW_ROOT)
sys.path.insert(0, os.path.join(FW_ROOT, "extends"))

from ext_combat import gauge as G  # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ " + name)
    else:
        FAIL += 1
        FAILURES.append(name)
        print("  ✗ " + name + ("  <- " + str(detail) if detail else ""))


# ---------------------------------------------------------------- 假装配
_CFG = {}


def _install(cfg):
    """注入假 enemy_bar 配置 + 空 cue 出口（不触发真实渲染链）。"""
    _CFG.clear()
    _CFG.update(cfg)
    G._battle_cfg = lambda key: _CFG if key == "enemy_bar" else {}
    G._cue = lambda battle, logs, cue, params: None


def _fire(bd, val=100.0):
    """走一遍「初始化 → 触发」，返回 (初始阈值, 触发后阈值)。"""
    _install({"probe": dict(bd)})
    enemy = {"effects": {}}
    state = G.bar_state(enemy, "probe", 1000.0)
    first = state["threshold"]
    state["val"] = val
    G.bar_trigger(None, enemy, "probe", logs=[], now=1000.0)
    return first, state["threshold"]


print("== 1. · ☐未修：正常配置逐字不变 ==")
# 50 -> floor(50*1.35)=67；连续触发后仍受 floor(base*cap)=125 封顶
first, after = _fire({"threshold_base": 50, "threshold_inc": 1.35, "threshold_cap": 2.5})
check("正常配置：初始 50 / 触发后 floor(50*1.35)=67", (first, after) == (50, 67), (first, after))

# 缺键时三个回落**都取声明默认**（1.35 / 2.5 / 50）—— 改前 inc/cap 回落成 1.0
first, after = _fire({"threshold_base": 50})
check("缺 inc/cap 键 → 回落声明默认（1.35）而非 1.0", after == 67, after)

print("== 2. · ☐合法 0 不得被吞 ==")
# ★ inc/cap 是**乘数**，0 的字面读法 = 乘 0（阈值塌到 0）—— 改前被 `or` 吞成 1.0。
#   这里钉住的是「0 不再被静默换成 1.0」这个口径本身，不是替内容侧选一个 inc 0 的语义。
#   ⚠ 顺带发现（已登记，**不在本轮裁决范围**）：inc=0 会让阈值塌到 0，此后每帧都满足
#   「val >= threshold」⇒ 反复触发。内容侧现行配置（orlandia mech_cfg_core / game_config）
#   只有 1.35/2.5 与 1.0/1.0/1.0，**无 0**，故生产面不受影响；是否给 inc/cap=0 单独
#   fail-closed，属「乘数 0 是非法配置还是合法档位」的口径题，需要产品侧拍板。
first, after = _fire({"threshold_base": 50, "threshold_inc": 0, "threshold_cap": 2.5})
check("inc=0 → 不再被换成 1.0（阈值按乘数塌到 0，不再是 50）", after == 0, after)
first, after = _fire({"threshold_base": 50, "threshold_inc": 1.35, "threshold_cap": 0})
check("cap=0 → 封顶为 0，不再被换成 1.0（不再 clamp 回 base=50）", after == 0, after)
first, after = _fire({"threshold_base": 0, "threshold_inc": 1.35, "threshold_cap": 2.5}, val=0.0)
check("base=0（零蓄积即触发）→ 两个读点同为 0（改前 bar_trigger 回落成 50）", (first, after) == (0, 0), (first, after))
first, after = _fire({"threshold_base": 50, "threshold_inc": 1.0, "threshold_cap": 1.0}, val=100.0)
check("inc=1.0/cap=1.0（orlandia 现行档）→ 阈值恒等 base", after == 50, after)

print("== 3. · 同一声明默认不得两套口径 ==")
# 不写 threshold_base 时，bar_state 初始值与 bar_trigger 内的 base 必须一致
# 改前：bar_state 缺键回落 **0**（or 0）、bar_trigger 回落 **50**（or 50）⇒ 同一默认两套值。
# 用「配了 inc/cap、只缺 base」这个**生产上真会出现**的形态（内容侧按需只写覆盖项）。
# ⚠ 不能用「三个键全缺」当用例：bar_def 走 `cfg or {}`，空定义 = 「该 bar 未定义」，
#   bar_trigger 会提前 return False（既有行为，不在本轮范围），测不到回落口径。
first, after = _fire({"threshold_inc": 1.35, "threshold_cap": 2.5}, val=100.0)
check("缺 threshold_base 键：bar_state 初值与 bar_trigger 基数同为 50（改前 0 vs 50）",
      (first, after) == (50, 67), (first, after))

print("== 4. · 反证：退回到旧写法必报红 ==")
# 把 bar_trigger 的三行换回旧的 `or` 写法，判据必须立马转红
import inspect  # noqa: E402
_src = inspect.getsource(G.bar_trigger)
_restored = (_src
             .replace('_num_cfg(bd, "threshold_base", 50.0)',
                      'float(bd.get("threshold_base", 50) or 50)')
             .replace('_num_cfg(bd, "threshold_inc", 1.35)',
                      'float(bd.get("threshold_inc", 1.35) or 1.0)')
             .replace('_num_cfg(bd, "threshold_cap", 2.5)',
                      'float(bd.get("threshold_cap", 2.5) or 1.0)')
             .replace('_num_cfg(bs, "threshold", base)',
                      'float(bs.get("threshold", base) or base)'))
check("能生成退回写法（否则本门禁是怀个的）",
      _restored != _src)
if _restored != _src:
    exec(compile(_restored, "<reverted>", "exec"), G.__dict__, G.__dict__)
    _f, _a = _fire({"threshold_base": 50, "threshold_inc": 0, "threshold_cap": 2.5})
    check("✗ 退回 `or` 写法后 inc=0 又被吞成 1.0 → 阈值 50（旧缺陷重现）",
          _a == 50, _a)
    exec(compile(_src, "<current>", "exec"), G.__dict__, G.__dict__)  # 恢复正式实现

# 恢复后再跑一次，确认修复真的有效
first, after = _fire({"threshold_base": 50, "threshold_inc": 0, "threshold_cap": 2.5})
check("恢复后 inc=0 真的生效（阈值 0）", after == 0, after)
first, after = _fire({"threshold_base": 50, "threshold_inc": 1.35, "threshold_cap": 2.5})
check("恢复后正常配置逐字不变（67）", after == 67, after)

print("== 结果：通过 %d / 共 %d ==" % (PASS, PASS + FAIL))
if FAILURES:
    print("失败：")
    for _f in FAILURES:
        print("  - " + _f)
raise SystemExit(1 if FAIL else 0)
