# saintess_engine —— 零游戏知识的通用文字游戏框架

> 纯 Python、零第三方依赖、零游戏名词的**声明驱动**框架，分**三层**：
> **引擎** / **扩展包** / **数据包**。**换一套配置 = 新游戏，引擎代码零改动。**
> 从《奥兰迪亚：余烬纪年》的实战代码里提炼而来，那段历史完整保留在本仓库。

## 三层布局

```text
数据包  game-*      games/<包>/         一款游戏的内容（一个进程只允许一个）
                       │  depends（按 id 装扩展包）
                       ▼
扩展包  ext-*       extends/<包>/       可插拔的游戏能力（可互相依赖）
                       │  from saintess_engine …（随便用）
                       ▼
引擎    engine-core saintess_engine/   通用件，零游戏词汇
```

**依赖方向严格单向：数据包 → 扩展包 → 引擎**（门禁 `tests/test_layering.py` 机器钉死）。

- 引擎目录：`saintess_engine/`（**19** 个子包 + **7** 个顶层模块；共 **65** 个 `.py` / **14 134** 行）
  —— 数字由 `tests/test_editor_wiki.py` 逐项对照磁盘锁定（本文件与 `docs/engine-wiki/README.md` 两处都要一致）
- 引擎侧的模块（与 `saintess_engine/__init__.py` 里的「模块布局」同一份口径，全部平级）：
  - **基础** `config`（注入面）· `domains`（引擎默认域集 + 合并规则）· `package`（包栈加载器）
  - **通用原语** `expr/` · `formula/` · `conditions/` · `bonus/` · `grant/` · `acts/` · `gates/`
    · `wire/` · `_validators/`
  - **运行时** `store/` · `command/` · `events/` · `clock/` · `container/` · `text/` · `session/`
    · `log/` · `tlog/` · `records/`
  - **宿主** `host/`（包加载 / 会话循环 / 命令通道 / 战斗驱动半边）
- 扩展包目录 `extends/`：引擎自带 **10** 个 —— `ext_combat`（CTB / 结算 / 效果 / 面板 / 计量条 /
  站位 / **标签** / **属性写口** / **表现事件 cue**）· `ext_quest` · `ext_world` · `ext_life` · `ext_economy` · `ext_social` · `ext_loot` ·
  `ext_dialogue` · `ext_achieve` · `ext_reward`。装法永远是一句话：数据包 `game.json` 里
  `"depends": ["ext_xxx"]`，包栈按拓扑序装
- 数据包目录 `games/`：一款游戏一个包（`games/orlandia` = 《奥兰迪亚》导出包 ·
  `games/my_game` = 演示包）。**一个进程只允许一个数据包**：指令路由 / 动作注册表 /
  文案表 / 时钟都是进程级单例，两个数据包会互撞 —— 要同时跑两款游戏就开两个进程

★ **游戏级能力在扩展包里，不在引擎里**（2026-09-23 起）。引擎只留「任何文字游戏都要的那一层」。
**架构铁律**：引擎不 import 内容，也不认识任何游戏名词（职业 / 技能 / 技能名都不认；
`tests/test_engine_purity.py` 是这条的门禁）。

## 表现层：文案怎么出去（cue · 引擎零文案）

玩家可见的每一行**都不是**引擎拼的：结算只发一条**表现事件（cue）**，措辞由内容侧订阅者
从自己的文案表渲染。

```text
结算（引擎/扩展包）                    内容包
  改动事实
    ↓
  _cue(battle, logs, "<key>", {槽位})   ← 引擎侧唯一出口（战斗 60 个点位全在册）
    ↓
  订阅表（内容侧 cue_subs_fn）           ← 「哪个 cue 归谁渲染」
    ↓
  render_required(key)：**必须命中**     ← 表不在 / 表里没这一格 ⇒ 抛
    ↓
  文案表（内容侧 text_table_fn）          ← 措辞真源（代码只传槽位，见下）
```

- 引擎侧**一条兜底模板都不剩**（`render_via` / `render_or(带 default)` / `Battle._t` /
  `text_of` 的调用点全部为 0；后两个 helper 已删）⇒ 换一句台词**只改内容包**，不动引擎。
- 出错方向是 **fail-closed**：装配期对账（声明的 cue 必须条条有订阅、条条有文案格）、
  运行期「必须命中」、真出问题落**一行可读坏数据 + 诊断通道**（不静默、不回落、不影响结算）。
- 形状与读法：`saintess_engine/cues.py`（总线 / 订阅表 / 三条硬规矩）·
  `extends/ext_combat/battle/cues.py`（`CUE_NAMES` 声明面）；门禁 `tests/test_cues_shape.py`。
- 对拍证据：`tools/_cue_freeze.py`（5 组固定战斗逐字节 + 状态 + 逐 cue 计数三通道对拍）·
  `tools/_cue_coverage.py`（覆盖率尺：61 条声明每条至少被真驱动一次）。

## 标签系统：一套查询面（tag · 照 GAS `GameplayTag` 那三件）

在 **`extends/ext_combat/battle/tags.py`**（254 行）+ `traits.py`（身份标签精确面）+
`state_effects.py`（状态容器）里 —— 引擎只做「名字 → 祖先 / 前缀」的结构运算，**不认识任何游戏名词**。

```text
授 tag 的三处来源（查询口合成一个面）           查询（父级命中子级）
  actor["traits"]      内容侧身份标签             has(a, "control")  →  命中 "control.stun"
  effects 的条目 key   状态本身就是标签            has_exact / has_any / has_all / match
  条目的 grants        一条状态可授多个 tag        sources_of（排障：这个 tag 谁授的）
撤销 = 条目被清（到期 / 被消费 / 离场）即随之消失，不另开接口 —— 生命周期跟着状态容器走
```

- **名字从哪来**：状态声明表（`EFFECT_RULES` 的键）+ 内容侧 `traits` + 引擎**固定词汇表**的**槽位名**
  （`DEFAULT_SLOTS`）。内容侧想在装配面把某个槽位改成点分名字（`immune_control` → `immune.control`）
  就声明 `tag_slots_fn`（`saintess_engine.config.mount(tag_slots_fn=…)`）—— 引擎只按槽位取名字。
- 与旧精确面的关系：**扁平名的精确判定走 `traits`（现行行为一字不动）**，**全来源 + 层级判定走 `tags`**；
  引擎新读点一律走 `tags`。落点 `7f3ef11`（注册表 + 统一查询面 + 层级 + 槽位名）·
  `88b7d9a`（声明层级继承 —— 前缀带行为）。
- 门禁 `tests/test_tags.py`；概念讲解 `docs/engine-wiki/concepts/actor-model.md`。

## 属性写口：`hp` / `mp` / `ct` 只有一个入口

**`extends/ext_combat/battle/attributes.py`** —— 照 GAS `AttributeSet` 的思路，把「改当前值」收成一处：

```python
attributes.set_current(actor, "hp", v,   reason="…", battle=b)   # 唯一写入口
attributes.add_current(actor, "mp", -8,  reason="skill_cost", battle=b)
# 读 / 边界：current() · ceiling() · floor_of()
```

- 引擎侧 **10 个写点**（调用点共 12 处）全部归口：`actions` 1 · `battle` 2 · `landing` 3 · `schedule` 4
  —— 各写点手写的 `max(0,…)` / `min(max,…)` 整句消失，钳制规则只剩一处。
- 预改 / 后改两个钩子是**注入面**：`attr_pre_fn` / `attr_post_fn`（登记进 `config._HOOKS`，
  **未装配 = 不存在**，一行都不进）；上下文（谁写的、为什么）一路带下去。
- **fail-closed**：认不出的键 / 非法值 ⇒ 抛，不静默改；等价性实测：改前改后 `logs` sha256 **5/5 逐字节相同**、
  `to_state()` **0 键差**。机器门禁 `tests/test_attrs_write_port.py` **禁止引擎代码再出现「对 hp/mp/ct
  下标直接赋值」**（白名单只有 `actions.py` 里一处**报价 dict**，条数恒 1）—— 漏改一处当场红。
- 落点 `c236e97` + `d374809`。

## 快速开始

```bash
# 1) 试跑最小示例游戏（不依赖任何外部数据）
python examples/minimal-game/main.py

# 2) 打开框架编辑器：新建/编辑一个自己的游戏包
python editor/server.py
```

两者都**只用 Python 标准库**（无需 pip install / Node / npm）。

## 用法：三种角色

**① 只想跑一个现成游戏** —— 看该游戏的 README（它自带 `apply.py` + 数据）。

**② 想做一个新游戏** —— 用编辑器：`python editor/server.py` → 新建游戏包 →
按域填数据（技能 / 职业 / 怪物 …）→ 试跑 → 导出。不需要写框架代码。

**②b 想用「声明驱动」管指令与文案**（可拔插，不用就零行为）

```python
from saintess_engine import CommandRegistry, TextTable

# 指令：一份声明同时供 匹配 / 帮助目录 / 静态表 / 漂移自检
reg = CommandRegistry.from_data(json.load(open("content/data/commands.json", encoding="utf-8")))
reg.pattern_map()                   # → {key: 正则}（宿主 filter 用）
reg.audit_handlers(handler_names)   # → 两个方向的漂移（漏登记 / 死声明）

# 文案：key → 模板；代码只传槽位，措辞全在表里（表现层走 cue，见上）
text = TextTable(json.load(open("content/data/texts.json", encoding="utf-8")))
text.render("battle.hit", n=7)      # 未知占位符原样保留，不炸玩家输出
text.missing(); text.unused(); text.validate()
```

两张表都能在**框架编辑器**里建与改（域 `commands` / `texts`，带 schema 校验 + 字段分组）。

**③ 想给框架加通用能力**（别人也能用） —— 加到 `saintess_engine/` 下**对应的模块**
（通用原语 → 顶层子包；也可以按「模块」粒度新建一个平级子包），跑本仓库测试；
**游戏级能力请放扩展包** `extends/ext_<名>/`（数据包 `depends` 装它），
机制动作放自己游戏包的 `mech/`（那才是「外挂」该待的地方）。

> **判定一段代码该不该进框架**（三条全过才行）：
> 1. **零游戏名词** —— 不含职业 / 技能 / 怪物 / 地图 / 物品 / 机制名（门禁守）
> 2. **形状而非内容** —— 把常量与枚举拿掉，逻辑仍成立
> 3. **第二个游戏能用** —— 换个职业 / 数值 / 地图，它需要改框架代码吗？要改 = 不通通用
>
> 最快的是**追问测试**：逐行问「这行是不是只有某一只游戏才会写？」

## 契约（第三方必读）

- `docs/engine-wiki/` —— 分层文档：概念 / 参考 / 指南 / 贡献（**入口**：`README.md`）
- `docs/engine-wiki/reference/skill-availability.md` —— 「技能放不放得出、何时能再放」四道判据
- `docs/engine-wiki/_selfcheck.md` —— **诚实清单**：已核实无消费方的字段、注释与代码不一致处

## 工具（`tools/`，都是离线只读）

| 工具 | 用途 |
|---|---|
| `check_wiki_refs.py` | wiki 的「文件:行」引用是否越界 / 指向空行（`drift 0`） |
| `remap_wiki_refs.py` | 改了代码行号后，把 wiki 引用按位移重锚 |
| `_cue_freeze.py` | **冻结对拍尺子**：5 组固定战斗的 logs sha256 / 逐 cue 计数 / `to_state` 三通道 |
| `_cue_coverage.py` | **覆盖尺**：61 条 cue 每条至少被真驱动一次（冻结 5 组 + 补驱动） |
| `export_actions.py` | 导出动词/动作清单（内容侧对账用） |

## 测试

```bash
python tests/run_all.py        # 引擎全量：tests/test_*.py + 各扩展包 extends/<包>/tests/*.py
python tests/run_all.py --serial   # 串行（排查并发发抖时用）
```

门禁里几条值得知道的：`test_layering`（三层依赖方向）· `test_engine_purity`（引擎零游戏词）·
`test_cues_shape`（表现事件形状 / 装配期对账 / 只读契约）· `test_cue_coverage`（覆盖尺 60/60）·
`test_editor_wiki`（**两处 README 的目录数字对照磁盘**）· 各扩展包自己的 `tests/`。

## 许可

（待定 —— 由仓库 owner 填）
