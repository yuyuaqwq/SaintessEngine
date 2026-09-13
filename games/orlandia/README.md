# 奥兰迪亚·余烬纪年 —— 引擎游戏包（**数据侧**，2026-09-13）

本目录是《奥兰迪亚·余烬纪年》（QQ 机器人文字 RPG，内容仓 = `dragonfall`）内容数据的
**单向导出物**：游戏仓是真源，这里是从真源重算出来的 JSON，供框架编辑器（`editor/`）与引擎读取。

> ⚠️ **不要手改本目录里的 JSON**。改数据 → 改游戏仓真源 → 重新导出（见 §二）。
> 同步门禁会逐字节对拍（包内文件 == 从真源重算），手改必红。

---

## 一、包里有什么

**24 个域 / 5115 条**，约 2 MB：

> ★ 2026-09-13 B2b：域的表**真源在本包的 `editor/domains.json`**（24 域）—— 框架内置集只剩
> 8 个**引擎域**（effect_rules / passive_proc / commands / texts / tlogs / maps / drop_pools /
> instances，每个都能在 `saintess_engine/` 指到消费端）；**内容域不内置**，只能由包声明
> （反证：拿掉本包那份声明 → 编辑器只认识那 8 个）。下表是 19 域那批的历史盘点，
> 其后新增的 5 个域：`npcs` 431 / `sets` 92 / `enhance_table` 10 / `panel_rules` 7 / `races` 6。

| 域 | 条数 | 文件 | 真源（游戏仓 `dragonfall/`） | 备注 |
|---|---:|---|---|---|
| items | 900 | `content/data/items.json` | `game/data/items.py::ITEMS` | 合表后的运行时态（含 price 覆盖） |
| equip_roster | 687 | `content/data/equip_roster.json` | `game/data/equip_roster.py::EQUIP_ROSTER`（+`SERIES_SETS`/`SERIES_FIXED_AFFIX`） | 装备名册：`equip:` / `roster_id` 的引用落点 |
| drop_pools | 596 | `content/data/drop_pools.json` | `game/data/drop_pools.py::DROP_POOLS` | 596 池 / 1435 条目 / 289 抽行 |
| pois | 457 | `content/data/pois.json` | `game/data/dungeon_pois.py::DUNGEON_POI_MOUNTS` + `mesh_rooms_*.py::MESH_POI_MOUNTS` | 交互点挂载，键 =「地图id:子区域id」 |
| **monster_roster** | **380** | `content/data/monster_roster.json` | `subareas.py` / `instances.py` / `mesh_rooms_*.py` 的 840 条元组 + `MONSTER_MODS` + `HIDDEN_MONSTERS` | **怪物名册**：键 = 怪 id。355 六元组 id + 24 隐藏怪专属 + 1 个体补正专属；跨来源冲突**不静默选一个**（`lv` 基准 + `lv_rule` + `lv_variants` + `spawns` 证据链） |
| monsters | 330 | `content/data/monsters.json` | `game/data/monsters.py::MONSTER_SKILLS` | 该域是**怪物技能**，不是怪物名册（名册是 `monster_roster`） |
| skills | 305 | `content/data/skills.json` | `game/data/skills.py` 三张表 | **扁平化**：`PLAYER_SKILLS`(61) + `BRANCH_SKILLS`(238) + `TUTOR_SKILLS`(6)，逐条附 `owner_class` |
| texts | 233 | `content/data/texts.json` | `game/data/text_specs.json` | 文案唯一真源；key 含中文（副本/日志/面板域） |
| commands | 194 | `content/data/commands.json` | `game/data/command_specs.json` | 指令声明表单源 |
| maps | 121 | `content/data/maps.json` | `game/data/subareas.py::SUBAREAS` + `_assembly.py::SUBAREA_LINKS_INDEX` + `maps.py::MAPS` | `topology: mesh(97)/star(24)`；节点 628 / 连边 1252 |
| **legendary_effects** | **93** | `content/data/legendary_effects.json` | `game/data/affixes.py::LEGENDARY_EFFECTS` | 传说专属特效：橙装 `legendary` 字段的引用落点（与 `affixes` 语义不同，故另立一域） |
| effect_rules | 85 | **`content/rules/effect_rules.json`** | `game/data/battle_rules.py::EFFECT_RULES` | 框架里 `kind="rules"` → 落 `rules/` |
| affixes | 76 | `content/data/affixes.json` | `game/data/affixes.py::AFFIXES` | 攻击 37 + 防御 39 |
| passive_proc | 42 | **`content/rules/passive_proc.json`** | `game/data/battle_rules.py::PASSIVE_PROC` | 装配层**声明**；动作实现**尚未进包**（见 §三.1） |
| instances | 27 | `content/data/instances.json` | `game/data/instances.py::INSTANCES`（装配后运行时表） | **投影**：内联怪元组 → 引用字符串，原值挂 `<槽位>_data` |
| tlogs | 18 | `content/data/tlogs.json` | `game/data/tlogs.json` | 埋点声明表（kind → 字段契约） |
| **pets** | **16** | `content/data/pets.json` | `game/data/pets.py::PET_POOL`（+`PET_EGG_ROLL`） | 宠物品种表；两张蛋规则表在导出期**连接进条目**（键是品质词，与 `pet_*` 互斥） |
| classes | 8 | `content/data/classes.json` | `game/data/classes.py::CLASSES` | 职业（含 `tutor` 元组 → list） |
| loot_vocab | 1 | **`content/rules/loot_vocab.json`** | `game/drop_engine.py` 的三张声明常量 | 掉落池**引用词汇声明**（内容侧告诉审计「哪些引用解得开」） |

`game.json` 声明：`id=orlandia` / `engine=">=0.1"` / `domains=[24 个域]` / `created=2026-09-12`。
**没有 `entry`**：本包是纯数据包（机制尚未移植），一旦声明 `entry` 就必须有那个文件
——`tests/test_editor_dist.py` 守这条不变量。

**引用闭合情况**（包内跨域引用，编辑器侧逐条判）：

```
装备名册侧   items.roster_id 14/14 · pick_options.rid 6/6 · drop_pools 的 equip: 97/97 ·
            instances.boss_equip_drop 22/22   → 全部命中
怪物名册侧   instances 怪 id 121/121 · drop_pools 的 mon:/elite: 345 个名字 345/345 → 全部命中
掉落池引用   176 处（equip: 119 / item: 30 / petegg: 27）**逐条判**（不是"不问"）：
            对不上名册就报断链（反证跑过：改坏即报 119/30/27 条）
技能侧       passive_proc 的 42 条声明全部有技能引用（孤儿 0）
审计口径     596 池 / 1435 条目 → 0 问题（与游戏仓自己的 audit_all() 同结论）
```

## 二、怎么重新导出 / 怎么验收

真源在游戏仓，导出器也在游戏仓：

```bash
cd C:/Users/yuyu/qqbot/data/plugins/dragonfall

# 单个域：导出（落盘）/ 只比对（不落盘）
python scripts/export_game_package.py --domain items
python scripts/export_game_package.py --domain items --check

# 全量覆盖验收（逐域导出 + --check + 编辑器侧条数/校验/联想候选）
python scripts/verify_package_coverage.py

# 同步门禁（包内文件 == 从真源重算，逐字节；含框架 schema 回环校验、落点 data|rules 断言）
python tests/test_export_package_sync.py

# 怪物名册闭合门禁（按名/按 id 两族引用；改名会被抓住）
python tests/test_monster_roster_closure.py
```

框架侧另有两道门禁会守这个包：`tests/test_editor_dist.py`（结构不变量：id/domains/落点/entry）
与 `tests/run_all.py`（全量回归）。

## 三、包里**没有**什么（说清楚，免得当成漏了）

1. **机制（action 的实现）**：`content/mech/*.py` 与 `content/apply.py` **还没有** ——
   也就是说引擎能读这份数据、编辑器能看能改，但**跑不起这款游戏**。
   `passive_proc` 声明里引用的 26 个动作一个都还没实现（编辑器里能直接看到这个缺口：
   `editor/actions.py:declared_missing()`，真包进度 = 声明 26 / 实现 8（全是引擎内置）/ 缺 26）。
   这是设计稿 `overnight/design-p4-mechanics-port.md` 的 P4。
2. **无框架域的整表**：任务/配方/成就/NPC/商店/坐骑/公会的对应表还在游戏仓（逐张理由见
   `docs/engine-wiki/reference/package-format.md` §九）。**名册类缺口已补完**（装备名册 / 怪物名册 / 交互点）。
3. **派生索引**（`EQUIP_ROSTER_BY_NAME` / `MATERIALS_BY_NAME` / `MONSTER_LOCS` / `ENCY_*` …）：
   故意不进包 —— 它们是「第二份定义」，属于同域双真源。
4. **一个已知的语义错配（不改）**：名册/怪物技能域的 `drops` 是**中文物名**，而
   `glossary.REF_DOMAINS["drops"] = "items"` 会给 items 的 **key** 候选 —— 对不上。
   这是 `drops` 叶名的既有语义（`monsters.drops` 同款），要改得先决定"按名引用"怎么表达。
