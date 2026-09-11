# saintess_engine —— 通用 CTB 战斗框架

> 零游戏知识的回合制（CTB）战斗内核：**换配置 + 挂机制 = 换游戏，引擎代码零改动**。
> 从《奥兰迪亚：余烬纪年》的战斗引擎中物理分离而来，那段实战历史完整保留在本仓库。

## 这是什么

一个**战斗框架**，不是某个游戏：

| 框架提供（通用） | 使用方提供（内容） |
|---|---|
| CTB 调度 / 行动结算 / 效果叠层 / 事件总线 / 存档序列化 | 数值公式的具体系数、技能表、职业表、怪物表 |
| 声明表机制（`EFFECT_RULES` / `EFFECT_ACTIONS` / `PASSIVE_PROC` / `MECH_CASH`） | 那些声明表里的**条目** |
| `@register_action` 回调注册制（机制动作外挂，不进框架） | 机制动作实现（放自己的 `mech/`） |
| 中性兜底（未挂配置时不崩，走骨架值） | 装配入口 `apply.py`（内容 → 引擎方向） |

**架构铁律**：框架不 import 内容，也不认识任何游戏名词（`职业` / `技能` / `技能名` 都不认）。
方向永远是 **内容 → 引擎**（`tests/test_engine_purity.py` 是这条的门禁）。

## 快速开始

```bash
# 1) 试跑最小示例游戏（不依赖任何外部数据）
python examples/minimal-game/main.py

# 2) 打开框架编辑器：新建/编辑一个自己的游戏包
python editor/server.py
```

两者都**只用 Python 标准库**（无需 pip install / Node / npm）。

## 目录

```
saintess_engine/            # 引擎包（可整包拷走）
  __init__.py       #   公开 API 面
  config.py         #   配置挂载点（内容侧把公式/面板/查询函数挂进来）
  battle.py         #   战斗实例 + 行动入口
  schedule.py       #   CTB 调度与推进
  actions.py        #   技能施放判据链（可解析 / 冷却 / 资源）
  effects.py        #   效果容器与动作
  landing.py        #   伤害/治疗落地（类型免伤、格挡、承伤乘区）
  ai.py             #   通用怪 AI 决策器（条件表 / 权重 utility）
  serialize.py      #   战斗存档
  formulas.py       #   通用数值公式（不含任何游戏系数）
  support/          #   通用件：表达式求值 / 阵型 / 技能种类 / 敌身条
editor/             # 框架编辑器：创造/编辑「游戏工具包」
examples/           # 示例游戏（第三方视角的验收物）
docs/               # 文档（含面向插件开发者的 wiki）
tools/              # 文档工具：wiki 行号引用自检 / 内容锚定位移
tests/              # 引擎自身测试（含纯度门禁 + wiki 行号门禁）
```

## 用法：三种角色

**① 只想跑一个现成游戏** —— 看该游戏的 README（它自带 `apply.py` + 数据）。

**② 想做一个新游戏** —— 用编辑器：`python editor/server.py` → 新建游戏包 →
按域填数据（技能/职业/怪物…）→ 试跑 → 导出。不需要写框架代码。

**③ 想给引擎加通用能力**（别人也能用） —— 改 `saintess_engine/`，跑本仓库测试；
机制动作请优先放自己游戏包的 `mech/`（那才是「外挂」该待的地方）。

## 契约（第三方必读）

- `docs/engine-wiki/` —— 分层文档：概念 / 参考 / 指南 / 贡献
- `docs/engine-wiki/reference/skill-availability.md` —— 「技能放不放得出、何时能再放」四道判据
- `docs/engine-wiki/_selfcheck.md` —— **诚实清单**：已核实无消费方的字段、注释与代码不一致处

## 测试

```bash
python tests/run_all.py        # 引擎全量
```

## 许可

（待定 —— 由仓库 owner 填）
