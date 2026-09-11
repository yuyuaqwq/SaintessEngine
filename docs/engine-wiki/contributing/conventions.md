# 贡献指南：代码约定

来自引擎代码里**反复出现的注释与原话**。这些不是风格偏好，而是被踩过坑之后立的规矩。

## 1. 零默认值（最重要）

**没声明 = 没行为。** 不要写「贴心默认」：

```python
# ✗ 不要
pct = params.get("pct", 0.10)

# ✓ 要
pct = float(params.get("pct") or 0)
if pct <= 0:
    return
```

理由（`formulas.py:129-132` 的真实教训）：`skill_power_mult` 曾默认「每级 +10%」，
结果「误伤无 SKILL_UP 配置的怪物技能：按折算等级白吃成长 ×1.4」。

变体约定：

| 情形 | 写法 |
|---|---|
| 缺字段 → 不做事 | `x = params.get(k) or 0`，`if x <= 0: return` |
| 缺声明 → 恒通过（条件门） | `if not when: return True`（`_when_ok`，游戏仓 `game/services/class_mech_proc.py:2144-2145`） |
| 未知枚举值 → **fail-closed** | `else: return`（游戏仓 `game/services/class_mech_proc.py:1001-1002` 的 `passive_taken_reduce`、`eval_when:141`） |
| 未知名 → 静默跳过 | `continue`（`apply_effects:163-164`） |

「恒通过」与「fail-closed」的分界：**判据缺失 = 无此行为（跳过）**；
**判据写了但值不认识 = 按不命中处理**（防拼写漂移静默生效）。

## 2. 不留兼容壳

旧名字不留「两套并行」的实现。允许的兼容只有两种：

| 允许 | 形式 | 例 |
|---|---|---|
| **别名指向同一对象** | `new = old` | `cap_of = _cap_of`（`effects.py:81`）、`EFFECT_HANDLERS = ACTION_HANDLERS`（`effects.py:89`） |
| **兼容 shim 委托到新实现** | 一个函数体只有一次转发调用 | 引擎侧已不留这类 shim —— 旧的 `config.load_game_defaults` 随拆仓从引擎删净（`saintess_engine/config.py` 里 `strict` 附近有原话：框架不认识「默认配置」是什么）；拆仓前它有 52 个测试调用点 |

不允许：把旧逻辑复制一份留在原地、在引擎读源路径上做「旧字段也读一下」的回落。
存档迁移是唯一例外，而且**只允许一处**（`serialize._deserialize_actor`，
迁完立刻 `pop` 旧键，`serialize.py:99-108`）。

原文（`serialize.py:90-92`）：

> 存档数据迁移，非引擎读源回落——引擎读源一律 `bonus` 分域 get 兜底；
> 新档 actor 已带 bonus 容器则原样。

## 3. 落地只能走 `landing`

**任何模块自己扣 `hp` 都是 bug。** 引擎自己的 DOT 也走 `landing.deal_damage`
（`schedule.py:292`）。自己的动词也必须走：

```python
from saintess_engine.landing import deal_damage, heal_actor
```
（`landing.py:8-13` 原文：「若每个机制自己写扣血，会出现旧引擎那种『某技能绕过护盾
直接扣血』的 bug」）

## 4. 状态只能写 `effects`（或 shields/cooldown）

一个机制的持久状态请写 `actor["effects"][key]`。
`shields`（承伤资源）与 `cooldown`（调度）是**唯一**允许的独立容器
（`actors.py:112-115` 给了理由）。要放「引擎不读的自定义状态」用 `actor["ext"]`
（`actors.py:133-134`：**引擎绝不读**）。

⚠️ 三个容器都会随存档落盘。别把不可 JSON 化的对象塞进去。

## 5. 引擎不认识内容

改引擎前先问：**这个功能是不是可以在内容侧用 `register_action` + `triggers` 做？**
如果能，就不要改引擎。参考实现的比例：8 个引擎动词 vs **70+** 个内容侧扩展动词。

引擎里**不允许**：

- import `game.content` / `game.data` / 任何游戏仓（奥兰迪亚侧）的 `game.*`（门禁拦）
- 动态 import 绕过（门禁拦）
- 中文字面量 kind 常量（门禁拦，`tests/test_engine_purity.py:121-127`）
- 读游戏表

已知的**残留瑕疵**（不要扩散它们）：`landing` 的固定 key（`death_guard` /
`heal_down` / `sleep`）、`effects` 的 `key == "reduce"`、`battle` 的 `"player"` 阵营名、
`support/skill_kinds.py` 的中文枚举值。完整清单见
[../architecture/boundaries.md](../architecture/boundaries.md) 的「边界瑕疵」表。

## 6. 容错铁律：异常不阻断战斗

事件源、观察者、单个 handler 的异常都 `continue` / 吞掉（`effect_triggers.py:107-117`、
`effects.py:172-176`）。这是**有意为之**：一场战斗不能因为一个效果写错就崩。

代价是你必须自己写测试；并且**不要**用裸 `except: pass` 掩盖你自己的逻辑错误 ——
引擎的容错是为了「别人的错不连累我」，不是为了「我的错没人看见」。
参考实现的写法是「包住可能有脏数据的边界，逻辑本身不做 try」。

## 7. 注释要写「为什么」

引擎注释的普遍密度很高，且几乎总在解释**动机**而不是复述代码。举例（可直接对照）：

```python
# v181.M-R2：dir=gain（资源自然回）不依赖现有层数——0 层也要回
# （游侠 energy 耗到 0 若被 n<=0 拦截将永远回不了，卡死）
```
（`schedule.py:247-248`）

```python
# 事件主体过滤（N9 修正）：ctx.actor = 该事件的主体 actor——只处理主体 actor
# 自己声明的 triggers，避免旁观者（同阵营其他带装备 actor）效果被全局广播误触发。
```
（`effect_triggers.py:74-76`）

要写的四类内容：

1. **拒绝过的方案**及原因（例：`actions._deal_aoe` 里解释为何不迁旧 AOE 反推算法，
   `actions.py:298-300`）
2. **顺序依赖**（例：旋律基础叠层必须排 `act_cast` 首位，游戏仓 `game/services/class_mech_proc.py:2291-2293`）
3. **缺口**（例：游戏仓 `game/data/battle2_rules.py:218-224` 的「⚠️ 缺口（不硬凑）」段）
4. **数值权威来源**（例：「desc 权威：30%/20%」，游戏仓 `game/data/battle2_rules.py:768`）

## 8. 命名

| 类别 | 约定 | 例 |
|---|---|---|
| 引擎动词 | 小写下划线，语义动词 | `apply` / `consume` / `shield` / `cleanse` |
| 内容侧扩展动词 | **前缀分族** | `we_*`（装备特效）· `mech_cash_*` · `passive_*` · `class_*` · `bar_*` |
| 事件名 | 小写下划线，时态表达时机 | `battle_start` / `act_begin` / `on_taken` / `time_advance` |
| 事件名**常量元组** | 全大写单数 | `EVENTS` |
| 内部函数 | 下划线前缀 | `_after_act` / `_cap_of` |
| 公开符号（S2 固化后） | 无下划线；旧下划线名保别名 | `cap_of` / `normalize_ai` |
| 声明表 | 全大写 | `EFFECT_ACTIONS` / `EFFECT_RULES` / `MECH_CASH` / `PASSIVE_PROC` |
| hook 名 | 小写下划线，`fn` 结尾表示它是函数 | `panel_fn` / `formula_skeleton_fn` / `basic_fallback`（dict，故不叫 `_fn`） |

## 9. 提交约定

⚠️ **本仓库（框架仓）本次核实到的提交信息规范未取证** —— 没有 `CONTRIBUTING.md`，
没有 commit-msg 钩子，`docs/` 里也没有提交约定文档。已核实的**文档命名惯例**是
版本/主题前缀（如 `REFACTOR_v181P4_*`、`HANDOFF_*`、`ENGINE_*`），
但那是文档文件名而不是 commit 类型。见 [_selfcheck.md](../_selfcheck.md)。

从代码注释可观察到的**版本标记惯例**（供写 commit 参考）：
`v181.N5b4-5E`、`v181.M-R2e B3`、`N9.13`、`M-R2d` 这类编号。
注释里带编号的比例很高，说明提交/任务有版本号体系 —— 但具体规则待确认。

## 10. 改这四类东西要格外小心

| 改动 | 风险 | 必做的检查 |
|---|---|---|
| `EVENTS` 元组 | 覆盖率漏记（必须单行）+ 事件名一改全仓静默失效 | 全文检索事件名字符串 |
| `_fire_ctx` 的读写 | 嵌套 fire 覆盖 → 同批次后续动作失效 | 检查是否需要 save/restore |
| `landing.deal_damage` 的落地顺序 | 顺序有语义（闪避在防御前等） | 对照 `landing.py` 里的顺序注释 |
| `serialize` 的字段 | 旧档兼容 | 加迁移断言 |

## 相关

- 环境与测试 → [setup.md](setup.md)
- 分发前的清单 → [release.md](release.md)
- 设计决策的代价 → [../architecture/design-decisions.md](../architecture/design-decisions.md)
