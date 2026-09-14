# 游戏包格式 —— 「数据包」= JSON 数据 + 扩展代码

> 回答的问题：**能不能把一款游戏（如《奥兰迪亚》）做成一个"包"，里面既有 JSON 数据、
> 又有它自己写的 Python（注册 handler、机制扩展）？**
>
> 结论：**能，而且这套格式已经建成并在运行**（示例包 `games/my_game/`）。
> 本文把这个格式写死，作为「引擎 + 数据包」分发形态的权威规格。

---

## 一、包是什么

一个游戏包 = **一个自包含目录**，装「引擎跑这款游戏需要的一切内容」：

* **数据**（JSON）：技能 / 物品 / 怪物 / 地图 / 掉落池 / 副本……编辑器直接改。
* **声明**（JSON）：状态规则 / 被动触发 / 指令 / 文案 / 流水 kind —— 引擎按声明表查表执行。
* **代码**（Python）：这款游戏**自己写的**机制动作与装配逻辑 —— 引擎给不出的那部分。

引擎（`saintess_engine/`）**不认识任何一款游戏**，也不 import 任何包；
包反过来 import 引擎的公开 API。方向单一：**包 → 引擎**。

---

## 二、物理结构

```
<包目录>/
  game.json                     # 清单：id / name / desc / engine 要求 / domains / entry / bind
  editor/
    domains.json                # 域声明（**域的真源在包** —— 见 §十；缺它 = 回退框架默认集）
  schemas/                      # 本包自带的 JSON Schema（按域名声明引用；缺 = 回退框架 schemas/）
    skill.schema.json  …
  content/
    data/                       # 【数据域】编辑器读写
      skills.json  classes.json  monsters.json  affixes.json  items.json
      maps.json    drop_pools.json  instances.json  …
    rules/                      # 【声明表】编辑器读写
      effect_rules.json  passive_proc.json  commands.json  texts.json  tlogs.json
    mech/                       # 【扩展代码】本游戏自己写的机制
      actions.py                #   @register_action → import 即注册
      …（可再分文件）
    apply.py                    # 【装配入口】唯一被引擎回调的文件
```

`game.json` 的 `entry` 字段指向装配入口（惯例 `content/apply.py`）。**可选**：纯数据导出包
（内容侧机制尚未移植、只把 `content/data/*.json` 交给编辑器）不声明它；一旦声明，该文件**必须存在**
（`tests/test_editor_dist.py` 守这条 —— 声明了却缺文件 = 坏包，2026-09-12 的导出包正踩过）。

### 2.1 `game.json` 字段表

| 字段 | 必填 | 形状 | 语义 / 校验（实现：`saintess_engine/host/package.py`） |
|---|---|---|---|
| `id` | 否 | 字符串 | 包身份；缺省 → 回退目录名（`Package.id`），`bind` 的报错文案里也用它 |
| `name` / `desc` | 否 | 字符串 | 展示元数据（编辑器 / 宿主命令行）；引擎不解释 |
| `engine` | 否 | 门槛字符串（如 `">=0.1"`） | 版本门槛：不满足 → `PackageError`（**显式报错，不静默降级**） |
| `entry` | 否 | 包内相对路径（惯例 `content/apply.py`） | 装配入口。**声明了就必须存在**（缺文件 → `PackageError`）；纯数据包不声明 |
| `domains` | 否 | 字符串数组 | 本包声明的域清单（编辑器 / 状态展示用） |
| `bind` | 否 | `{"module": "<包内相对路径 .py>", "func": "<函数名>"}` | ★ **宿主注入声明**（见 2.2）。不声明 = 本包零宿主耦合 |
| `created` | 否 | 字符串 | 建档时间（元数据） |

### 2.2 `bind`：宿主注入声明（可选）

包的代码如果需要**宿主对象**（存档句柄 / 平台客户端 / 通信出口……），不要在包内自己找宿主 ——
在 `game.json` 里声明一个中间人，引擎按契约把宿主的**注入对象**交给它：

```json
{
  "id": "my-game",
  "engine": ">=0.1",
  "entry": "content/apply.py",
  "bind": {"module": "content/index.py", "func": "bind_host"}
}
```

**形状**（两键都必填、都必须是字符串）：

| 键 | 形状 | 含义 |
|---|---|---|
| `module` | 包内相对路径（`.py` 可省） | 中间人模块；按**包根**解析成 import 名（`content/index.py` → `content.index`） |
| `func` | 函数名 | 中间人入口；签名 `func(**inject)`，返回值忽略 |

**语义**（引擎已实现；加载期与运行期用**同一个** `inject` dict）：

* **加载期**：包若声明了 `bind`，引擎在 **import 包命令模块（`content/commands.py`）之前**调
  `func(**inject)` —— 包命令模块因此可以在 import 期就 `from . import index` 并取宿主对象。
* **运行期**：`inject` 并入每条消息的 `Env.state`（引擎自有键 `spec` / `prefix` / `package`
  在前、注入键在后，**同名以注入为准**）。
* 入口是同一个面：`Host(adapter, package_dir, inject={...})` 与 `load_package(root, inject={...})`。
* 引擎**不解释** `inject` 的键值（零游戏知识，只原样转交）—— 键名与含义由宿主与包约定。

**校验规则**（引擎已实现 → `PackageError`，绝不放行；宁可不跑，也不静默）：

| 情形 | 结果 |
|---|---|
| 声明了 `bind`，但宿主没给注入（`inject` 缺省 / 空 dict） | `PackageError`（**拒绝静默空跑**）—— 否则包会炸在包内某模块里，错误指不到根因 |
| `module` 或 `func` 缺失 / 空串 | `PackageError`（`bind` 声明不完整） |
| `module` 指向的模块 import 失败（文件不存在） | `PackageError` |
| `func` 不在该模块里，或不是可调用对象 | `PackageError`（`bind.func 不可调用`） |
| `bind` 函数自己抛错 | **原样抛出**（引擎不吞：包自己的错就是包自己的错） |
| 没声明 `bind` | 什么也不调（纯数据包 / 无宿主耦合的包照常加载） |

**最小示例**（「声明 `bind` + 提供 `inject`」的完整链路，可照抄成一个新包）：

```
<包目录>/
  game.json                 # bind: {"module": "content/index.py", "func": "bind_host"}
  content/
    index.py                # 中间人：宿主对象只从这里进来；取不到就抛（fail-closed）
    commands.py             # 命令模块：import 期就问 index 要宿主对象
    data/commands.json      # 指令声明（真源）
    apply.py                # 装配入口（install_engine / apply_game_content）
```

```python
# content/index.py —— 中间人
_HOST = {}

def bind_host(**objs):                 # 引擎在 import content/commands.py 之前调它
    for key, value in objs.items():
        if value is not None:
            _HOST[key] = value

def get(key):
    if key not in _HOST:
        raise RuntimeError("index：宿主对象 %s 取不到 —— 拒绝静默空跑" % key)
    return _HOST[key]
```

```python
# content/commands.py —— 命令模块：import 期就要求已注入（这就是 bind 的时序意义）
from . import index

_store = index.get("store")            # 宿主没注入 → 这里抛错（根因指到本行）

def hello(env):
    return ["store=%s；Env.state 里同名以注入为准：%s" % (_store, env.state.get("store"))]
```

宿主侧只多一个参数：

```python
host = Host(adapter, package_dir, inject={"store": my_store})
# 或：pkg = load_package(package_dir, inject={"store": my_store})
```

可运行的端到端演示见 `examples/host-skeleton/main.py`（`python main.py --demo-inject`：
零注入跑 `examples/minimal-game` + 内联合成包演示上面这条全链路）。
字段级契约见 [host-api.md](host-api.md) §四「宿主注入面」。

---

## 三、三层内容，谁改什么

| 层 | 位置 | 谁改 | 引擎怎么用 |
|---|---|---|---|
| 数据 | `content/data/*.json` | **编辑器（非程序员）** | 包自查表 → 喂给引擎 |
| 声明 | `content/rules/*.json` | **编辑器（非程序员）** | 查表执行（零声明 = 零行为） |
| 代码 | `content/mech/*.py`、`apply.py` | **写代码的人** | 装配期调用引擎公开 API |

**关键分工**：编辑器**只碰 JSON**，永远不动 `mech/` 与 `apply.py`。
所以"非程序员用编辑器改数值 / 程序员加机制"两件事互不干扰 —— 这正是包的形状要解决的事。

---

## 四、加载契约

包对外只暴露**两个约定**（`content/apply.py`）：

```python
def install_engine() -> None:
    """全局一次：把本游戏的公式 / 面板 / 声明表挂进引擎（幂等）"""

def apply_game_content(actor: dict) -> dict:
    """单个 actor：把本游戏的资源渠道 / 机制 / 被动翻成引擎认的 triggers"""
```

四条不变量：

1. **单向依赖** —— 引擎不 import 包；包只能用 `saintess_engine.__all__` 里的公开 API。
2. **import 即注册** —— `mech/*.py` 里的 `@register_action("名字")` 在 import 期生效；
   **不 import 就等于这个动作不存在**（声明表里写了也跑不起来）。
3. **钩子自举** —— 包通过 `config.register_hook_provider(...)` 挂一个回调，
   引擎首次需要装配时回调它（`_lazy_mount`），**包没被 import 时引擎照常按零默认值跑**。
4. **零默认值** —— 表为空 = 该功能不存在，不是"用默认值兜底"。

---

## 五、分发：JSON 与 Python **一起**走

导出 zip（编辑器左上角包名 → 导出）走 `os.walk` 收包内全部文件，
只跳过 `.pyc/.pyo/.pyd/.db/.sqlite/.log` —— 因此
**`content/apply.py` 与 `content/mech/*.py` 会在包里一起分发**，不是"只能导数据"。

导出时附两个**不属于包内容**的文件：

| 文件 | 作用 |
|---|---|
| `DIST_README.md` | 这是什么 / 怎么跑 / 引擎要求 |
| `DIST_smoke.py` | 一条命令跑通一场最小战斗（导入后自检） |

引擎版本门槛：`game.json` 的 `engine` 字段（如 `">=0.1"`）由框架侧校验，
不满足**显式报错，不静默降级**。

---

## 六、包 vs 引擎：谁该拥有什么

判据只有一条（与 [roadmap.md](roadmap.md) 同源）：

```ini
形状（骨架 / 协议 / 流程）→ 引擎
内容（策略 / 数据 / 这款游戏的假设）→ 包
```

因此下面这些**都该住在包里**（哪怕它们是代码）：

* `@register_action` 自定义动词（引擎给 8 个内置动词，其余由包扩展）
* 装配逻辑（把包的声明表翻成引擎认的结构）
* 这款游戏特有的 handler / 扩展

引擎里**不该出现**任何一款游戏的名词（`职业`、`技能名`、`眩晕` 这些名词住在包的声明表里）。

---

## 七、把《奥兰迪亚》搬成包：分期路线

现状：奥兰迪亚是**参考实现**（约 12.6 万行），内容散在 Python 模块里
（`game/data/*.py`、`game/commands/*.py`、`game/services/*`），
而包格式是**目标形态**。两者之间靠"搬运"逐步合拢，不是重写。

| 阶段 | 做什么 | 验收 | 现状（2026-09-13） |
|---|---|---|---|
| **P1** | 数据域导出：`game/data/*.py` → `content/data/*.json`（先物品域打样） | 编辑器能打开该域真数据；同步门禁锁住「JSON = 从 Python 重算」 | ✅ **完成**：导出器 `dragonfall/scripts/export_game_package.py`（items 900）、门禁 `tests/test_export_package_sync.py`、覆盖验收 `scripts/verify_package_coverage.py` |
| **P2** | 其余数据域：怪物 / 地图 / 掉落池 / 词条 / 职业 / 装备名册 … | 同上，逐域一条门禁 | ✅ **除「装备名册」类无框架域的表外全部完成** —— 包内 13 域 / 2691 条（框架 DOMAINS 的 13 个域一个不缺）；无框架域的表见 §九 |
| **P3** | 声明表迁移：状态规则 / 被动 / 指令 / 文案 / 流水 → `content/rules/*.json` | 声明与调用不脱节（已有门禁体系） | ✅ **完成**：`effect_rules`(85) 与 `passive_proc`(42) 落 `content/rules/`；`commands`(194) / `texts`(233) / `tlogs`(18) 落 `content/data/`（按框架 `DOMAINS.kind`） |
| **P4** | 代码收口：扩展代码 → `content/mech/*.py`；装配入口 → `content/apply.py` | 引擎零改动即可跑起包；`mech/` import 即注册生效 | ⏳ **未开始 —— 这是剩下的大块**。包内现在**没有** `apply.py` / `content/mech/`：引擎能读这份数据、编辑器能改，但**跑不起来这款游戏**（机制的 26 个被动动作、指令守卫实现、战斗脚本等仍在游戏仓 `game/services/*`）。`game.json` 因此**不声明 `entry`**（纯数据包，声明了就必须有文件 —— 门禁守这条） |
| **P5** | 奥兰迪亚仓瘦身为「宿主 + 包」：宿主只留平台耦合层（QQ / AstrBot 等） | 包可整包导出分发；宿主可替换 | ⏳ 未开始 |

**过渡期铁律**：同一份语义**不许两处各写一份**。P1~P3 期间 Python 仍是真源 →
JSON 由导出脚本生成，并由**同步门禁**断言「派生一致」；改一边不同步就红。

---

## 八、未决问题（待裁决，别当成已定）

1. **代码归属的边界**：奥兰迪亚的 `game/commands/*.py`（25 个模块，含大量业务逻辑）
   哪些属于包的 `mech/`、哪些属于宿主平台层？需要一条可判定的切分判据。
2. **`engine` 版本契约**：目前只是字符串比较，包依赖引擎具体能力（如某 shape 存在）
   时尚无能力级声明。
3. **超大包的编辑器体验**：单域上万条 JSON 时的列表/搜索性能 —— ✅ **已收口（2026-09-12）**：
   左栏改**定高虚拟滚动**（DOM 只留视口 ±12 行：2000 条时 2000 行 → 43 行，整表重画 77ms → 7ms）；
   搜索逐键防抖；后端 `domain_status` 改**按条目内容指纹缓存**（列表/概览/校验三条路共用，
   改一条只重算一条：热 178/229/207ms → 31/31/29ms）；列表接口加**可选** `?offset=&limit=`
   （不带参数 = 全量旧行为），前端「先画第一页、其余后台续取」。门禁
   `tests/test_editor_large_package.py`（2000 条合成包：条数/分页并集/冷热阈值/缓存失效/搜索窗口切片）。
4. **包的更新与用户数据**：包升级时玩家的存档/数据库如何迁移，尚无方案。

---

## 九、奥兰迪亚包：已进包 / 还没进包（2026-09-13 盘点）

**已进包 73 个域 / 9361 条**（★ 2026-09-14 实测现状：`scripts/verify_package_coverage.py --check`
汇总行「域 73 个 / 条目合计 9361 / 失败 0」）。域的真源**在包里** —— 框架内置集只剩 8 个引擎域，
其余 65 个由 `games/orlandia/editor/domains.json` 声明（★ 2026-09-13 B2b 时该数是 16）。
⚠️ 下面这份**逐域条数**是 **2026-09-13 B2b 那次盘点的快照**（当时合计 24 个域 / 5115 条，
此后收口 / D3 批与 `text_specs` 等陆续进包）—— 它**不等于**当前 73 域的全量，数字请以实测为准：
`items` 900 / `equip_roster` 687 /
`drop_pools` 596 / `pois` 457 / **`monster_roster` 380** / `monsters` 330 / `skills` 305 /
`texts` 233 / `commands` 194 / `maps` 121 / **`legendary_effects` 93** / `effect_rules` 85 /
`affixes` 76 / `passive_proc` 42 / `instances` 27 / `tlogs` 18 / **`pets` 16** / `classes` 8 /
`loot_vocab` 1（+ 收口/D3 批新增：`npcs` 431 / `sets` 92 / `enhance_table` 10 / `panel_rules` 7 /
`races` 6）。清单与真源模块见 `games/orlandia/README.md`。

### 9.1 名册类缺口**已补完**（2026-09-13）

三张「引用有落点」的名册都进包了：`equip_roster`(687) / `pois`(457) / **`monster_roster`(380)**。
其中怪物名册按设计稿 `workspace/editor-large-package-next/overnight/design-monster_roster.md` 落地：

* 键 = 怪 id；覆盖 = 355 六元组 id + 24 隐藏怪表专属 + 1 只个体补正表专属（380 条）；
* 跨来源冲突**不静默选一个**：`lv` 只是**基准值**，规则写在 `lv_rule`（当前 = `field_min`：野外记录最小值），
  每一处现场留在 `lv_variants`（语义化 scope，不用行号）与 `spawns`（`source/map/subarea/slot/line` 证据链）；
  **168 个等级冲突全量保留**；`name`/`role` 取多数值 + `*_variants`；`skills`/`drops` 取**并集**；
  14 个重名如实落 `name_peers`（不静默选一个）；
* **唯一待鱼鱼拍板的**：`lv_rule` 的取值（现在是「野外最小」）。想换成「副本值 / 多数值」只改导出器里那**一个常量**，
  名册的对照字段不用动。
* 闭合验收（`dragonfall/tests/test_monster_roster_closure.py`，已进仓）：`instances` 121 个怪 id 全命中、
  `drop_pools` 的 345 个 `mon:`/`elite:` 名字全命中、重名/等级对照结构齐全。

### 9.2 属「下一个域批次」的内容表（不影响当前包可用性）

盘点把游戏仓 `game/data/*.py`（84 模块）里的主要内容表逐张评估了（完整表见
`workspace/editor-large-package-next/overnight/package-inventory.md` §3），按家族归纳：

| 家族 | 代表表（条数） | 建议 |
|---|---|---|
| 生产/配方 | `CRAFT_RECIPES`(426) · `ALCHEMY_RECIPES`(91) · `COOKING_RECIPES`(59) · `ENCHANT_RECIPES`(7) · `REFINE_*`(15) | 一个 `recipes` 域 |
| 任务 | `MAIN_QUESTS`(70) · `SIDE_QUESTS`(144) · `DAILY_QUESTS`(24) · `WEEKLY_QUESTS`(12) | 一个 `quests` 域 |
| 角色成长 | `ACHIEVEMENTS`(119) · `TITLES`(68) · `COLLECTION_BOOKS`(5) · `SKILL_UP`(305) | 按需拆分 |
| 世界人物 | `NPCS`(362+47+22) · `DIALOGUES`(39) · `FACTIONS`(23) | `npcs` / `dialogues` / `factions` |
| 事件/世界 | `EXPLORE_EVENTS`(146) · `DAILY_MAP_EVENTS`(20) · `WORLD_BOSS_POOL` · `TRIAL_FLOORS`(30) | `events` / `world` |
| 经济 | `SHOP_*`(88) · `GUILD_SHOP_ITEMS` · `HONOR_SHOP` · `AUCTION_POOL` | `shop` |
| 伙伴/坐骑 | ~~`PET_POOL`(26)~~ **✅已进包（`pets` 16）** · `MOUNT_*`(22) · `SUMMONS`(5) | 余下 `mounts` / `summons`（`SUMMONS` 只有 5 条，可并入 `mounts` 一起开） |
| 生活技能 | `FISH_TIERS` · `FISH_POOL`(30) · `FISHING_SPOTS`(11) · `GATHER_*` · `MINING_*` | `fish` / `gather` |
| 其它 | `PROPS`(374) · `PORTALS`(11) · `RACES`(6) · `TIPS`(58) · ~~`LEGENDARY_EFFECTS`(93)~~ **✅已进包** · `SETS`(92) · ~~`MONSTER_MODS`(140)~~ **✅已并入 `monster_roster`** | 按需 |

**不建议进包**（属派生表/索引，进了就是第二份定义）：`MATERIALS_BY_NAME`(686) ·
`EQUIP_ROSTER_BY_NAME`(686) · `INSTANCE_STAGE_MAPS`/`INSTANCE_STAGE_NPCS`（已装配进 `instances.stages[]`）·
`SUBAREA_LINKS`（已装配进 `maps.links`）· `ENSY_*`/`MONSTER_LOCS` 等图鉴反查索引 · `GATHER_MAP_POOLS`（已派生成
`drop_pools` 的 `gather:*` 池）。
**只能随机制走**（不是数据）：`rules.py` 的规则条目、指令守卫实现、`SET_THEMES` 之类参数。

### 9.3 边界：这份包能当什么用 / 不能当什么用

- **能当**：结构 + 引用基本自洽的**内容只读快照** —— 编辑器可完整浏览/校验 73 域 9361 条、
  做内容审阅、形状回归、掉落/副本/地图的静态审计（`maps` 空间形状、`instances` 进度、
  `drop_pools` 展开与运行期逐格一致；带 `loot_vocab` 声明的掉落审计 0 问题）。
- **不能当**：**可运行的游戏包** —— 没有 `apply.py` / `content/mech/`，`passive_proc` 的 `action`
  与 `effect_rules` 的通道语义在包内查不到 handler（引擎 `fire()` 静默跳过）。
  这就是 §七 的 **P4（代码收口）**：从「数据包」到「可运行包」的那一步。

---

## 十、编辑器扩展：**域的真源在包**（2026-09-13）

一句话：**加一个域 = 改包内 3 个文件**（域声明 + schema + 数据），框架一行不改。

### 10.1 三个文件

| 改哪 | 形状 | 说明 |
|---|---|---|
| `editor/domains.json` | `{"mech_verbs": {"label": "机制动词", "kind": "data", "schema": "schemas/mech_verbs.schema.json", "primary": "mech_verb", "icon": "🔧"}}` | 域声明。`kind` 决定落点（`data → content/data/`、`rules → content/rules/`）；`schema` 是**包内相对路径**；`primary` = schema `$defs` 里「一条数据」那个 def 名 |
| `schemas/<域>.schema.json` | 普通 JSON Schema（draft 2020-12）；`$defs.<primary>` 是单条形状 | 校验与表单渲染都读它。**不给 = 该域不校验**（编辑器照旧可增删改） |
| `content/data|rules/<域>.json` | `{条目 key: 条目对象}` | 数据本身；编辑器新建包 / 新建条目时会写它 |

> 想给**已有**的域换名字/图标/schema：在 `editor/domains.json` 里写**同名域**即可（只写要改的字段，
> 其余沿用默认口径）。同名 → **包赢**，但编辑器会给一条可读告警（不静默）。

### 10.2 合并规则（框架那份 = **回退默认集**，不是真源）

```
effective_domains(pkg) = 包 editor/domains.json  ∪（可选）框架内置默认集
  · 同名域：包声明优先（框架那份不参与该域取值）；真改了字段 → 一条可读 warning
  · 框架内置默认集（editor/packages.py 的 BUILTIN_DEFAULT_DOMAINS，**8 个引擎域**：
    effect_rules / passive_proc / commands / texts / tlogs / maps / drop_pools / instances
    —— 逐个都能在 `saintess_engine/` 指到消费端；内容域不内置，否则等于「框架里揣着某个游戏的域」）
     **只在包里没有可用声明时兜底**（第三方包 / 坏包 / 未迁移的老包）—— 它是回退，不是真源
  · {"$builtin": false}：显式声明「本包的域就这些，不要兜底」（examples/minimal-game 用的就是它）
  · 坏声明（坏 JSON / 缺 kind / kind 非法 / schema 越界 / 域 id 越界）→ 该条（或整份）忽略 +
    黄条告警 + 回退默认集，**绝不 500**（「列表里有它、点开 500」是不允许的）
  · schema 解析：<pkg>/schemas/<声明值> → <pkg>/<声明值> → 框架 schemas/<声明值> → 不校验
```

**实证（可复现）**：`python tests/test_editor_step3_pkg_first.py` —— 用 monkeypatch 把框架那份
常量**整个置空**后，`games/orlandia` 仍能列出完整 73 域、能读能写能校验、HTTP 端到端 200
（= 真源确实在包，框架那份可以被整体拿掉）；同一门禁钉住 `examples/minimal-game` 这个**最小样板**
（自带 6 域声明 + 6 份 schema，覆盖它声明的**全部**域，照它抄就是新游戏的加域姿势）。
另一条**反证**在 `python tests/test_editor_package_domains.py`（§4b）：内置集逐名 == 8 个引擎域 +
**拿掉**包内 `editor/domains.json` → orlandia 的 73 域立刻掉到 8（内容域真的没有了，不是换个来源）。

### 10.3 什么时候才该动框架

- **给某个游戏加/改域** → 只改那个包（§10.1 那三个文件）。框架那份默认集**不用动**。
- **改内置默认集** → 只有当你要换掉「所有没声明的包的兜底域集」时才动它；那是**所有包**的口径变更，
  不是给某个游戏加域的手段（`editor/packages.py:49`）。
- 尚未搬进包的框架侧扩展面：字段词典 `editor/glossary.py`、取值提示 `editor/hints.py`、
  专属视图分派 `editor/{loot,instance,space}_view.py`（第 2/3 层扩展面，见设计稿）。

---

## 十一、包内 wiki：`<包>/docs/wiki/**.md`（2026-09-13）

一句话：**包可以自带文档页** —— 编辑器「📖 文档」页按「**包优先、框架兜底**」渲染。
给某个游戏写专属说明，不必去改框架仓的 `docs/engine-wiki/`。

### 11.1 目录约定

```
<包目录>/
  docs/
    wiki/                  # 可选；缺它 = 这个包没自带 wiki（编辑器照旧只显示框架文档）
      README.md            # 相对路径沿用框架那套命名
      getting-started/  concepts/  guides/  reference/  architecture/  …
```

* 只认 `.md`；页的**相对路径就是它的身份**（如 `reference/effect-rules.md`）。
* 左导航的分组由**路径首段**决定，与框架共用同一张分组表（首段不认识 = 归「其他」）。

### 11.2 解析顺序（四条 wiki 路由一致）

| 情形 | 结果 |
|---|---|
| 包内有同名页（相对路径相同） | **包内那份**（框架那份不再参与） |
| 包内没有、框架有 | 回退**框架**页 |
| 两边都没有 | 照旧 404 / `None`（**绝不 500**） |
| `?pkg=` 指向不存在的包 id | 404「包不存在」 |
| 不给 `?pkg=`，或该包没有 `docs/wiki/` | **与没有这个功能时逐项一致**（零回归硬约束） |

页清单 `tree` 是**并集**：包内页 + 未被包内同名页遮住的框架页。`page` / `search` 同名只认包内那份。

### 11.3 字段深链

包词汇表（§10.1 的 `editor/glossary/`）条目里的 `wiki: ["页.md", "页内词"]` 生成
`wiki:<页>#find=<词>`，这页按 11.2 的顺序解析（**包内页优先 → 框架页兜底**）。
沿用既有纪律：**「页内词」必须真出现在该页正文里**（门禁逐条断言），别编链接；
两边都没有这页 → 该条目**不出链接**（`None`），不凑一个像样的。

### 11.4 源码直链

`file.py:行号` 同样是**包内源码优先 → 框架源码兜底**；包内命中时返回里多一个
`"root": "package"` 标注「这段来自游戏包」。两边都没有 → 照旧明说「读不到」，**不猜**。

### 11.5 边界（**尚未做**的，别当成已定）

* **行号引用自检**（`tools/check_wiki_refs.py` / `tests/test_wiki_refs.py`）目前只扫框架
  `docs/engine-wiki/` —— 包内 wiki 里的行号引用**没有**进这条自检（包内页写行号引用请自己核）。
* 没有「本包只要自己的 wiki、不要框架兜底」的开关（对比域那边的 `{"$builtin": false}`）。
* 编辑器前端的「📖 文档」页目前**不带** `?pkg=`：接口面（四条路由）已就绪，
  前端接线（把当前包 id 传上去、切换包时重载文档树）属于下一步。

