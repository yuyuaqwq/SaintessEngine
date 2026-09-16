# 安装 / 拿到引擎

## 这是什么形态的依赖

引擎是**源码级的纯 Python 包**，不是 PyPI 发行包。它住在**框架独立仓 `framework-engine/` 的顶层**：

```
saintess_engine/
├── __init__.py           公开 API 门面（26 符号 re-export）
├── actors.py             actor 模型 / 工厂 / Sides 容器 / ActCtx
├── battle.py             Battle 主类（构造 / act / human_act / actor_auto / 胜负）
├── actions.py            行动结算链（普攻 / 技能 / 治疗 / 增益 / 吸血 / 公式段）
├── effects.py            效果系统（动词注册表 + 8 个引擎动词 + 名词翻译）
├── effect_triggers.py    事件总线（EVENTS + fire()）
├── landing.py            伤害/治疗落地收口
├── schedule.py           CTB 时间轴 / 推进 / 周期结算
├── serialize.py          to_state / from_state
├── stats.py              面板聚合（薄封装，公式走 hook）
├── state_effects.py      效果规则查表门面
├── formulas.py           引擎侧纯数值公式（零内容知识）
├── ai.py                 通用怪 AI（条件优先级表 / 权重）
└── support/              通用件：battle_bars / formation / formula_expr / skill_kinds
```

（本页路径除显式标注「游戏仓 / 奥兰迪亚侧」外，均指框架仓 `framework-engine/`。）

## 两种拿到它的方式

| 方式 | 适用 | 做法 |
|---|---|---|
| **拷贝目录** | 你的项目里只用一份、不改引擎 | 把 `saintess_engine/` 整个目录复制进你的项目（包名就是 `saintess_engine`；S4 改名议题已随拆仓定案：**不再改中性名**），`import` 路径随之调整 |
| **git submodule** | 想跟随上游更新、想给上游提 PR | 把**框架独立仓 `framework-engine`** 作为 submodule 挂在你的项目下 —— 这已是现实：游戏仓 `dragonfall` 就是这么接的（`.gitmodules` 里 `framework/` → 框架仓，固定 commit）；当年为拆仓准备的迁移方案见**游戏仓**文档 `dragonfall/docs/ENGINE_CONTENT_SPLIT_PLAN.md` §6/§7 |

⚠️ **实测结论（重要）**：框架仓本身就是「拷出来的独立包」形态 —— 顶层就是 `saintess_engine/`，
`import` 正常、`Battle` 可构造、可跑完一场战斗（本次文档编写期间实测通过）。
但**如果你的项目里同时还挂着游戏仓（奥兰迪亚侧）的 `game/` 包**，情况不同：
`game/__init__.py` 在 import 期登记了引擎的「hook 惰性装配器」，引擎首次读取 hook 时
会把 `game.content`（整份《奥兰迪亚》内容）拉进来（登记点在 `game/__init__.py:20-22` →
`game/bootstrap.py:196-207` 的 `install()`）。那是**游戏仓**的接线；框架仓里没有 `game/` 包，
`import saintess_engine` 干净无副作用（由 `tests/test_engine_purity.py` 保证）。
第三方项目请**直接使用框架仓（或从中拷出的）独立包 `saintess_engine/`**，不要依赖 `game` 包的 `__init__` 副作用。

## Python 版本

- 引擎代码使用 `from __future__ import annotations` + 现代类型标注（`dict | None`、`list[str]`），
  在 **Python 3.9+** 语义下即可运行；框架仓的字节码缓存里同时存在 `cpython-311` 与 `cpython-312`
  目录（`saintess_engine/__pycache__/`），即实机在 **3.11 / 3.12** 上跑过。
- 没有 `setup.py` / `pyproject.toml`，没有声明 `python_requires`。**具体的最低版本要求未取证**，
  见 [_selfcheck.md](../_selfcheck.md)。

## 第三方依赖：零

`saintess_engine/**` 的**全部** import 都是标准库或引擎内部相对导入。本次核实到的完整集合：

```
__future__(annotations) · dataclasses · typing · enum ·
json · math · random · re
```

没有 `numpy` / `pydantic` / `attrs` / 任何网络或数据库依赖。
落地层（`landing.py`）用 `random.random()` 做闪避/格挡 roll，无随机种子注入点
（要可复现测试请自己 `random.seed(n)`）。

## 目录之外还依赖什么？

引擎**本身不依赖**任何东西，但「能打出伤害」还需要你的项目提供数值公式与常量。
五条必需 hook：

| hook | 作用 | 不装的后果（实测） |
|---|---|---|
| `formulas` | 提供 `calc_damage` / `resolve_formula` / `skill_*` 等函数对象 | 落地为「零效应」兜底（`_NullFormulas`，伤害恒 0，**静默**） |
| `formula_skeleton_fn` | 公式骨架参数表（`{"skill_growth": {...}}`） | 伤害链内部抛 `KeyError: 'skill_growth'`（**硬崩**） |
| `skill_flat_fn` | 技能基础值常量表（`SKILL_FLAT_BASE` 等） | 伤害链内部抛 `TypeError: float() argument ... NoneType`（**硬崩**） |
| `time_model_fn` | CTB 一次行动耗时 `fn(spd, base) -> float`（形状 + 参数你定） | **`Battle(...)` 构造期**抛 `EngineNotConfigured`（播种 ct 要它；**fail-closed**，无默认公式） |
| `action_base_fn` | 行动类别 → 基准耗时 `fn(action) -> float` | 同上（`EngineNotConfigured`，点名 hook） |

完整清单与取值见 [concepts/config-injection.md](../concepts/config-injection.md) 与
[reference/api.md](../reference/api.md)。可跑的最小装配集见
[first-battle.md](first-battle.md)。

## 下一步

- 想先跑起来 → [first-battle.md](first-battle.md)
- 想加自己的东西 → [first-mechanic.md](first-mechanic.md)
- 想知道「为什么引擎长这样」 → [../concepts/README.md](../concepts/README.md)
