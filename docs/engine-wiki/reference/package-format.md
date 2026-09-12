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
  game.json                     # 清单：id / name / desc / engine 要求 / domains / entry
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

**已进包 16 个域 / 4080 条**（框架 `DOMAINS` 一个不缺）：`items` 900 / `equip_roster` 687 /
`drop_pools` 596 / `pois` 457 / `monsters` 330 / `skills` 305 / `texts` 233 / `commands` 194 /
`maps` 121 / `effect_rules` 85 / `affixes` 76 / `passive_proc` 42 / `instances` 27 / `tlogs` 18 /
`classes` 8 / `loot_vocab` 1。清单与真源模块见 `games/orlandia/README.md`。

### 9.1 需要**拍板**的一件（不是干活问题，是形状问题）

**「怪物名册」的权威形状**。游戏侧的「怪物」不是一张表 —— 是散在 `subareas.py` / `instances.py` /
`mesh_rooms_*.py` 的 **840 条六元组模板**（`[id, 中文名, role, lv, [技能id], [掉落名]]`，
355 个唯一 id，**168 个 id 的 lv 跨表不一致**，10 个中文名对应两个 id）。两个候选：

| 候选 | 做法 | 代价 |
|---|---|---|
| A. 六元组 → 对象表（键 = 怪 id） | 新建 `monster_roster` 域，条目 = `{id,name,role,lv,skills,drops}`；框架 schema 里已有 `monster_template` def 就是描述六元组的 | 要先定「同一个 id 在两处 lv 不同时以谁为准」（或如实保留 `lv_by_source`） |
| B. 只建索引，不建名册 | 只导 `MONSTER_MODS`(140) + `HIDDEN_MONSTERS`(25) + 一张 `{中文名 → id}` 索引，供 `mon:`/`elite:` 按名引用解析 | 怪物本体仍不在包里，跨表引用只能解析到「名字对得上」的程度 |

定了形状就能一次消掉 `instances` 的 148 条怪 id 悬空 + `drop_pools` 的 363 条按名引用。

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
| 伙伴/坐骑 | `PET_POOL`(26) · `MOUNT_*`(22) · `SUMMONS`(5) | `pets` / `mounts` / `summons` |
| 生活技能 | `FISH_TIERS` · `FISH_POOL`(30) · `FISHING_SPOTS`(11) · `GATHER_*` · `MINING_*` | `fish` / `gather` |
| 其它 | `PROPS`(374) · `PORTALS`(11) · `RACES`(6) · `TIPS`(58) · `LEGENDARY_EFFECTS`(93) · `SETS`(92) · `MONSTER_MODS`(140) | 按需 |

**不建议进包**（属派生表/索引，进了就是第二份定义）：`MATERIALS_BY_NAME`(686) ·
`EQUIP_ROSTER_BY_NAME`(686) · `INSTANCE_STAGE_MAPS`/`INSTANCE_STAGE_NPCS`（已装配进 `instances.stages[]`）·
`SUBAREA_LINKS`（已装配进 `maps.links`）· `ENSY_*`/`MONSTER_LOCS` 等图鉴反查索引 · `GATHER_MAP_POOLS`（已派生成
`drop_pools` 的 `gather:*` 池）。
**只能随机制走**（不是数据）：`rules.py` 的规则条目、指令守卫实现、`SET_THEMES` 之类参数。

### 9.3 边界：这份包能当什么用 / 不能当什么用

- **能当**：结构 + 引用基本自洽的**内容只读快照** —— 编辑器可完整浏览/校验 16 域 4080 条、
  做内容审阅、形状回归、掉落/副本/地图的静态审计（`maps` 空间形状、`instances` 进度、
  `drop_pools` 展开与运行期逐格一致；带 `loot_vocab` 声明的掉落审计 0 问题）。
- **不能当**：**可运行的游戏包** —— 没有 `apply.py` / `content/mech/`，`passive_proc` 的 `action`
  与 `effect_rules` 的通道语义在包内查不到 handler（引擎 `fire()` 静默跳过）。
  这就是 §七 的 **P4（代码收口）**：从「数据包」到「可运行包」的那一步。
