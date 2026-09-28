# -*- coding: utf-8 -*-
"""L246 门禁：最后 6 处写死的平衡数值已下沉 `FORMULA_SKELETON`，且注入面**真的通**。

背景
----
`extends/ext_combat/battle/actions.py` 里 6 处**玩家可见平衡数值**原先直接写死
（幸运率 0.30 / 幸运倍率 1.3 / 吸血 cap 0.30 ×3），第二款游戏要改自己的手感只能改引擎。
本批把它们下沉到**既有的** `formula_skeleton_fn` 注入面（承 V4 2026-09-16 与
E2 2026-09-25 `dodge_cap` 的先例）—— 不新开第二张表 / 第二套注入面。

**刻意不下沉的 2 处**：`min(..., 0.99)` 折扣上限（消耗封顶）是**数学恒等式**
（保证扣减后 > 0、不出现 0 消耗），不是可调平衡数值 ⇒ 留在引擎并注释点明。
本门禁把这条边界也钉住（免得下一轮"顺手下沉"）。

本测试钉三件事（**缺一即红**）
------------------------------
A. **中性默认值 = 原写死值**：未装配 `formula_skeleton_fn` 时，三个 getter 逐字返回
   0.30 / 1.3 / 0.30 ⇒ 玩家可见行为零变化（这是"迁移不改行为"的正证）。
B. **注入面真的通**：装上 `formula_skeleton_fn` 后改挂载值 ⇒ getter 跟着变
   （证明内容侧能覆盖，不是写死的假 getter）。
C. **读点已收口**：`actions.py` 里不再有裸 `0.30` / `1.3` 平衡字面量
   （只剩注释与那 2 处 `0.99` 恒等式）。

跑法：python tests/test_l246_formula_surface.py
"""
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


print("== A. 中性默认值 = 原写死值（未装配）==")
# 显式卸掉挂载，保证走 _NEUTRAL_SKELETON
_saved = _cfg.get_hook("formula_skeleton_fn")
try:
    if hasattr(_cfg, "set_hook"):
        _cfg.set_hook("formula_skeleton_fn", None)
except Exception:
    pass

check("lucky_rate() = 0.30（原写死）", F.lucky_rate() == 0.30, "got=%r" % F.lucky_rate())
check("lucky_mult() = 1.3（原写死）", F.lucky_mult() == 1.3, "got=%r" % F.lucky_mult())
check("lifesteal_cap() = 0.30（原写死）", F.lifesteal_cap() == 0.30, "got=%r" % F.lifesteal_cap())

print("== B. 注入面真的通（内容侧可覆盖）==")
_mounted = {
    "lucky": {"rate": 0.5, "mult": 2.0},
    "lifesteal_cap": 0.45,
}


def _fake_skeleton():
    return dict(_mounted)


try:
    if hasattr(_cfg, "set_hook"):
        _cfg.set_hook("formula_skeleton_fn", _fake_skeleton)
except Exception as _e:
    print("  [WARN] set_hook 不可用：%r" % _e)

check("挂载后 lucky_rate() = 0.5", F.lucky_rate() == 0.5, "got=%r" % F.lucky_rate())
check("挂载后 lucky_mult() = 2.0", F.lucky_mult() == 2.0, "got=%r" % F.lucky_mult())
check("挂载后 lifesteal_cap() = 0.45", F.lifesteal_cap() == 0.45, "got=%r" % F.lifesteal_cap())

# 还原
try:
    if hasattr(_cfg, "set_hook"):
        _cfg.set_hook("formula_skeleton_fn", _saved)
except Exception:
    pass
check("还原后回到默认 0.30/1.3/0.30",
      (F.lucky_rate(), F.lucky_mult(), F.lifesteal_cap()) == (0.30, 1.3, 0.30),
      "got=%r" % ((F.lucky_rate(), F.lucky_mult(), F.lifesteal_cap()),))

print("== C. 读点已收口（actions.py 无裸平衡字面量）==")
_ACTIONS = os.path.join(FW_ROOT, "extends", "ext_combat", "battle", "actions.py")
_lines = io.open(_ACTIONS, encoding="utf-8").read().splitlines()

# 只看**真代码行**：剔除纯注释行 与 **docstring 行**（两者都是说明文字，不是执行路径）。
# ★ 本门禁第一版漏了 docstring（`:746` 那行以 `-` 开头的说明），把说明文字误判成
#   残留字面量 ⇒ 这里按「在字符串字面量内」再滤一次。
_bare = []
for _i, _ln in enumerate(_lines, 1):
    s = _ln.strip()
    if not s or s.startswith("#"):
        continue
    # docstring / 说明行：含中文标点或反引号包裹的键名，不是可执行表达式
    if ("FORMULA_SKELETON" in s and "`" in s) or s.startswith("- "):
        continue
    if re.search(r"[一-鿿]", s) and "=" not in s.split("#")[0].strip()[:1]:
        # 说明行（含中文且不是以 = 开头的赋值）
        if not re.match(r"^[\w\[\]._]+\s*=", s):
            continue
    if "min(rate, 0.30)" in s or "min(spct, 0.30)" in s or "min(rate_p, 0.30)" in s        or "min(rate_m, 0.30)" in s or "random.random() < 0.30" in s or "dmg * 1.3" in s:
        _bare.append((_i, s))
check("代码行里无裸 0.30/1.3 平衡字面量", not _bare, "残留=%r" % _bare)

# 折扣 0.99 那 2 处**故意留**（数学恒等式）—— 钉住它不被悄悄下沉/删掉
_nine9 = [i for i, ln in enumerate(_lines, 1) if "0.99" in ln and not ln.strip().startswith("#")]
check("消耗折扣 0.99 两处仍在引擎（恒等式，不下沉）", len(_nine9) == 2, "got=%r" % _nine9)

print("")
print("=== PASS=%d FAIL=%d ===" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
