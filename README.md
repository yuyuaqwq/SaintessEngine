# saintess_engine —— 通用文字游戏框架

> 零游戏知识的文字游戏框架：**换配置 + 挂机制 = 换游戏，框架代码零改动**。
> 从《奥兰迪亚：余烬纪年》的实战代码中提炼而来，那段历史完整保留在本仓库。

## 这是什么

一个**游戏框架**，不是某个游戏。包内 **12 个模块并列**（战斗 / 表达式 / 计量条 /
阵型 / 类别 / 存储 / 命令 / 事件 / 时钟 / 容器 / 会话 / 注入面），彼此零依赖或单向依赖
—— 每个都能单独理解、单独拷走：

| 框架提供（通用） | 使用方提供（内容） |
|---|---|
| CTB 调度 / 行动结算 / 效果叠层 / 事件总线 / 存档序列化 | 数值公式的具体系数、技能表、职业表、怪物表 |
| 声明表机制（`EFFECT_RULES` / `EFFECT_ACTIONS` / `PASSIVE_PROC` / `MECH_CASH`） | 那些声明表里的**条目** |
| `@register_action` 回调注册制（机制动作外挂，不进框架） | 机制动作实现（放自己的 `mech/`） |
| 存储 / 命令 / 事件 / 时钟 / 容器 / 会话骨架 | 业务查询、表结构、指令文案 |
| 中性兜底（未挂配置时不崩，走骨架值） | 装配入口 `apply.py`（内容 → 引擎方向） |

**架构铁律**：框架不 import 内容，也不认识任何游戏名词（`职业` / `技能` / `技能名` 都不认）。
方向永远是 **内容 → 框架**（`tests/test_engine_purity.py` 是这条的门禁）。

## 快速开始

```bash
# 1) 试跑最小示例游戏（不依赖任何外部数据）
python examples/minimal-game/main.py

# 2) 打开框架编辑器：新建/编辑一个自己的游戏包
python editor/server.py
```

两者都**只用 Python 标准库**（无需 pip install / Node / npm）。

## 目录

单包、**多模块并列** —— 纯度契约一致（只依赖相对导入 + 标准库，均可整包拷走）：

| 模块 | 定位 |
|---|---|
| `battle/` | **战斗域**：CTB 调度 / 行动结算 / 效果叠层 / 落地结算 / 存档 / AI / 面板公式 |
| `expr/` | 表达式求值器（数值公式任意自定义；白名单 tokenizer，不 eval 输入） |
| `gauge/` | 计量条：累积 / 衰减 / 阈值触发 / 免疫窗口 / 阶段保留 |
| `formation/` | 站位与目标选择几何（层数 / 射程 / AoE 范围） |
| `kinds/` | 技能与伤害类别域（类型元数据 / 前缀匹配） |
| `store/` | SQLite 骨架：连接/锁/事务 + 建表注册 + 列迁移 + Repository |
| `command/` | 命令层骨架：分页 / 文本剥离 / 守卫 / handler 路由 / 提示 / 基类 / **指令声明注册表** |
| `events/` | 领域事件总线：注册序执行 / 未知事件策略 / 异常容忍 |
| `clock/` | 懒计时器：类型注册 + 惰性过期 + 回调不绕路（不跑后台定时器） |
| `container/` | 容器骨架：容量受限的格子列表（仓库 / 邮件附件 / 公会仓库 同形） |
| `text/` | 文案模板表：装载 / 渲染（未知槽原样保留）/ 缺失与死文案自检 |
| `session/` | 会话骨架：宿主事件契约 + 参考实现(PlainEvent) + 会话标识适配点 |
| `config` | 注入面：内容侧把公式 / 面板 / 查询函数挂进来的唯一入口 |

```
saintess_engine/            # 框架包（可整包拷走）
  __init__.py       #   包门面：公开 API 面 + 12 个子模块转出
  config.py         #   注入面（内容侧把公式/面板/查询函数挂进来）
  battle/           #   战斗域（12 模块）
                    #     battle / actions / landing / effects / schedule /
                    #     ai / stats / formulas / actors /
                    #     effect_triggers / state_effects / serialize
  expr/             #   表达式求值器
  gauge/            #   计量条
  formation/        #   站位与目标选择几何
  kinds/            #   技能/伤害类别域
  store/            #   SQLite 骨架
  command/          #   命令层骨架
  events/           #   领域事件总线
  clock/            #   懒计时器
  container/        #   容量受限格子容器
  session/          #   宿主会话适配
editor/             # 框架编辑器：创造/编辑「游戏工具包」
examples/           # 示例游戏（第三方视角的验收物）
docs/               # 文档（含面向插件开发者的 wiki）
tools/              # 文档工具：wiki 行号引用自检 / 内容锚定位移
tests/              # 框架自身测试（纯度 + 中立性 + 行号 三门禁）
```

## 用法：三种角色

**① 只想跑一个现成游戏** —— 看该游戏的 README（它自带 `apply.py` + 数据）。

**② 想做一个新游戏** —— 用编辑器：`python editor/server.py` → 新建游戏包 →
按域填数据（技能/职业/怪物…）→ 试跑 → 导出。不需要写框架代码。

**②b 想用「声明驱动」管指令与文案**（可拔插，不用就零行为）

```python
from saintess_engine import CommandRegistry, TextTable

# 指令：一份声明同时供 匹配 / 帮助目录 / 静态表 / 漂移自检
reg = CommandRegistry.from_data(json.load(open("content/data/commands.json", encoding="utf-8")))
reg.pattern_map()                  # → {key: 正则}（宿主 filter 用）
reg.audit_handlers(handler_names)   # → 两个方向的漂移（漏登记 / 死声明）

# 文案：key → 模板；未定义的 key 会计入 missing（迁移待办清单）
text = TextTable(json.load(open("content/data/texts.json", encoding="utf-8")))
text.render("battle.damage_taken", n=7)   # 未知占位符原样保留，不炸玩家输出
text.missing(); text.unused(); text.validate()
```

两张表都能在**框架编辑器**里建与改（域 `commands` / `texts`，带 schema 校验 + 字段分组）。

**③ 想给框架加通用能力**（别人也能用） —— 加到 `saintess_engine/` 下**对应的模块**
（战斗语义 → `battle/`；通用原语 → 顶层子包；也可以按「模块」粒度新建一个平级子包），
跑本仓库测试；机制动作请优先放自己游戏包的 `mech/`（那才是「外挂」该待的地方）。

> **判定一段代码该不该进框架**（三条全过才行）：
> 1. **零游戏名词** —— 不含职业/技能/怪物/地图/物品/机制名（门禁 A/B 守）
> 2. **形状而非内容** —— 把常量与枚举拿掉，逻辑仍成立
> 3. **第二个游戏能用** —— 换个职业/数值/地图，它需要改框架代码吗？要改 = 不通通用
>
> 最快的是**追问测试**：逐行问「这行是不是只有某一只游戏才会写？」

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
