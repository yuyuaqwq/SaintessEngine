# 指南：给自己的内容写断言

引擎的容错策略是「**宁可静默不做，也不抛异常**」（见
[../concepts/event-bus.md](../concepts/event-bus.md)）。代价：你的声明写错时**没有任何提示**。
所以测试不是可选项 —— 它是唯一的安全网。

## 参考实现的测试写法（游戏仓侧，可直接照抄）

游戏仓侧的 `tests/test_battle_*.py` 全是**可独立运行的脚本**（不依赖 pytest 也能跑），
统一结构：

```python
# -*- coding: utf-8 -*-
"""<测试名>：<覆盖什么>。跑法：python tests/test_battle_xxx.py"""
import os, sys, random

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PLUGIN_DIR, "framework"))  # 引擎框架包（拆仓后为 framework/ submodule）
QQBOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(PLUGIN_DIR)))
TEST_DB = os.path.join(PLUGIN_DIR, "test_battle_xxx.db")
os.environ.setdefault("GWEN_GAME_DB", TEST_DB)
os.environ.setdefault("GWEN_TEST_MODE", "1")
sys.path.insert(0, QQBOT_DIR)
sys.path.insert(0, PLUGIN_DIR)

from saintess_engine import Battle as BT, make_actor, config as _b2config
from game.content_rules.apply import ensure_engine_configured
ensure_engine_configured()              # 内容侧规则表装配（引擎已删 load_game_defaults shim）

PASS = 0
FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")
        print(f"  ❌ {name} {detail}")


def main():
    print("=== xxx ===")
    test_something()
    print(f"\n=== 结果 PASS={PASS} FAIL={FAIL} ===")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
```

（样板取自游戏仓侧 `tests/test_battle_n4_schedule.py` 的尾部与 `tests/test_battle_n3_effects.py` 的头部）

> ⚠️ **归属**：上面的样板是**游戏仓（AstrBot 插件）**的测试外壳 —— `PLUGIN_DIR` / `QQBOT_DIR` /
> `GWEN_GAME_DB` / `GWEN_TEST_MODE` 都是那个插件的环境约定，`framework/` 是拆仓后挂进来的
> 引擎 submodule（真实样例见 游戏仓 `tests/test_battle_n4_schedule.py:18,33`）。
> **框架仓自身的测试不需要这些**：`tests/run_all.py` 用纯标准库 python 跑 `tests/test_*.py`。

要点：

- **`check(name, cond, detail)` 三参数**：`detail` 在失败时打印实际值，别省（否则调试要重跑）
- **`sys.exit(1 if FAIL else 0)`**：让 CI / 测试运行器（框架仓 `tests/run_all.py`、游戏仓 `scripts/run_all_tests.py`）能判红绿
- **随机种子**：伤害有 ±15% 波动、闪避/格挡/暴击都是 `random`。
  断言精确数值时必须 `random.seed(...)`
  （实例：`tests/test_battle_coverage.py` 尾部 `_r.seed(20260910)`，
  注释解释了为什么必须固定 —— 玩家真实面板有约 3% 基础闪避，会让防御减伤断言偶发假红）

## 四条该写的断言

| 断言类型 | 例子 | 为什么 |
|---|---|---|
| **声明存在性** | 「`EFFECT_RULES` 里有 `my_res` 且 `cap == 8`」 | 表写错 key 时静默无行为 |
| **行为可观察** | 「打一拳后 `target["hp"]` 减少 30±1」 | 端到端验证链路通 |
| **边界不越界** | 「叠 20 次后 `stacks == cap`」 | cap 是 clamp 行为，写错会数值崩坏 |
| **缺口不倒退** | 「未装配时 `human_act` 返回 `[]` 且不抛异常」 | 保护「零默认值」语义本身 |

第三条尤其重要：`_cap_of` 在**没有声明 `cap` 时返回 999999**（`effects.py:67`）——
「我明明写了 cap 为什么还涨到 20」的答案通常是 key 写错了。

## 测机制时的三个实用招式

### 招式 1：直接构造最小战斗，别拉整份内容

```python
def _battle(hero_hp=200, wolf_hp=300):
    hero = make_actor("p1", "英雄", "player", kind="player", human_controlled=True,
                      hp=hero_hp, max_hp=hero_hp, atk=30, spd=60, level=10)
    wolf = make_actor("e1", "野狼", "enemy", kind="monster",
                      hp=wolf_hp, max_hp=wolf_hp, atk=20, spd=40, level=8)
    return BT(btype="monster", sides={"player": [hero], "enemy": [wolf]})
```

血量给大一点，避免「还没验证完就打死对方」。

### 招式 2：手动写 `_now` 驱动时间

周期效果不要靠 `advance` 跑，直接拨时钟：

```python
from saintess_engine.schedule import _settle_time_effects as _ste

b = _battle()
b.human_act("skill", "施加燃烧")        # 或直接写 effects
e = b.sides["enemy"][0]
b._now = 1.5; _ste(b, [])              # 结算到 1.5 刻
hp1 = e["hp"]
b._now = 4.2; _ste(b, [])              # 一次补跳多刻
check("4.2 补跳 3 次（180 伤）", hp1 - e["hp"] == 180)
```

真实同款见 `tests/test_battle_n4_schedule.py` 的 `test_dot_interval_n74`。
注意断言里「补跳」的期望值 —— 一次 `_settle_time_effects` 最多补 20 跳
（`schedule.py:261` 的 `guard < 20`）。

### 招式 3：断言 `triggers` 装配结果，而不是行为

行为对了但装错了（比如给不该有的职业也装了）很难从日志看出来。直接断言结构：

```python
def test_assembly():
    actor = make_actor("p1", "h", "player", kind="player", class_name="my_class",
                       level=10, learned_skills=["我的被动"])
    apply_my_mechanisms(actor)
    trig = actor.get("triggers") or {}
    check("dmg_calc 有 1 条", len(trig.get("dmg_calc") or []) == 1)
    check("judge.kind 是 res_ge", (trig["dmg_calc"][0]["judge"] or {}).get("kind") == "res_ge")
    check("bonus.cap 写入", (actor.get("bonus") or {}).get("cap", {}).get("my_res") == 3)
```

### 招式 4：幂等断言

装配器会被重复调用（开战仪式可能重跑）。加一条：

```python
apply_my_mechanisms(actor)
apply_my_mechanisms(actor)          # 再调一次
check("幂等：不会堆两条", len(trig["dmg_calc"]) == 1)
```

## 跑测试

| 归属 | 目的 | 命令 |
|---|---|---|
| **框架仓** | 引擎全量（引擎自身测试 + 示例游戏冒烟） | `python tests/run_all.py`（纯标准库 python 即可） |
| **框架仓** | 引擎纯度门禁（改引擎后**必跑**） | `python tests/test_engine_purity.py`（exit=0 全绿） |
| **框架仓** | 单个引擎测试 | `python tests/test_<name>.py` |
| **游戏仓** | 单个内容测试 | `python tests/test_battle_n4_schedule.py` |
| **游戏仓** | 全量回归 | `python scripts/run_all_tests.py` |

⚠️ **游戏仓侧**全量的两个注意（`scripts/run_all_tests.py:15-25`）：

- **必须用 AstrBot 的 uv python**（带 `pypinyin`）：
  `C:/Users/yuyu/AppData/Roaming/uv/tools/astrbot/Scripts/python.exe`
- **跑全量期间不要改源文件**（避免中间态误判）

框架仓的 `tests/run_all.py` 没有这两个约束 —— 引擎零第三方依赖，纯标准库 python 即可跑。

细节见 [../contributing/setup.md](../contributing/setup.md)。

## 相关

- 缺口的完整清单（写测试时优先覆盖这些） → [../_selfcheck.md](../_selfcheck.md)
- 环境与跑测试的完整说明 → [../contributing/setup.md](../contributing/setup.md)
