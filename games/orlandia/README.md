# 奥兰迪亚·余烬纪年 —— 引擎游戏包（**数据侧**，2026-09-13）

本目录是《奥兰迪亚·余烬纪年》（QQ 机器人文字 RPG，内容仓 = `dragonfall`）内容数据的
**单向导出物**：游戏仓是真源，这里是从真源重算出来的 JSON，供框架编辑器（`editor/`）与引擎读取。

> ⚠️ **不要手改本目录里的 JSON**。改数据 → 改游戏仓真源 → 重新导出（见下「怎么重新导出」）。
> 手改会被同步门禁抓住（`python tests/test_export_package_sync.py` 断言「包内文件 = 从真源重算」，
> 且要求逐字节相同）。

## 一、包里有什么

**13 个域 / 2691 条**（与框架 `editor/packages.py` 的 `DOMAINS` 13 个域一一对应，一个不缺），
合计约 987 KB：

| 域 | 条数 | 文件 | 真源（游戏仓 `dragonfall/`） | 备注 |
|---|---:|---|---|---|
| items | 900 | `content/data/items.json` | `game/data/items.py::ITEMS` | 合表后的运行时态（含 price 覆盖） |
| drop_pools | 596 | `content/data/drop_pools.json` | `game/data/drop_pools.py::DROP_POOLS` | 596 池 / 1435 条目 / 289 抽行 |
| monsters | 330 | `content/data/monsters.json` | `game/data/monsters.py::MONSTER_SKILLS` | 该域是「怪物技能」，不是怪物名册（见 §三） |
| texts | 233 | `content/data/texts.json` | `game/data/text_specs.json` | 文案唯一真源；key 含中文（副本/日志/面板域） |
| commands | 194 | `content/data/commands.json` | `game/data/command_specs.json` | 指令声明表单源 |
| maps | 121 | `content/data/maps.json` | `game/data/subareas.py::SUBAREAS` + `_assembly.py::SUBAREA_LINKS_INDEX` + `maps.py::MAPS` | `topology: mesh(97)/star(24)`；节点 628 / 连边 1252 |
| effect_rules | 85 | **`content/rules/effect_rules.json`** | `game/data/battle_rules.py::EFFECT_RULES` | 框架里 `kind="rules"` → 落 `rules/` |
| affixes | 76 | `content/data/affixes.json` | `game/data/affixes.py::AFFIXES` | 攻击 37 + 防御 39 |
| skills | 61 | `content/data/skills.json` | `game/data/skills.py::PLAYER_SKILLS` | **扁平化**：一条技能 = 一个 key，附 `owner_class` |
| passive_proc | 42 | **`content/rules/passive_proc.json`** | `game/data/battle_rules.py::PASSIVE_PROC` | 装配层**声明**；动作实现在游戏仓（见 §三） |
| instances | 27 | `content/data/instances.json` | `game/data/instances.py::INSTANCES`（装配后运行时表） | **投影**：内联怪元组 → 引用字符串，原值挂 `<槽位>_data` |
| tlogs | 18 | `content/data/tlogs.json` | `game/data/tlogs.json` | 埋点声明表（kind → 字段契约） |
| classes | 8 | `content/data/classes.json` | `game/data/classes.py::CLASSES` | 职业（含 `tutor` 元组 → list） |

`game.json` 声明：`id=orlandia` / `engine=">=0.1"` / `domains=[13 个域]` / `created=2026-09-12`。
**没有 `entry`**：本包是纯数据包（机制尚未移植），一旦声明 `entry` 就必须有那个文件
——`tests/test_editor_dist.py` 守这条不变量。

## 二、怎么重新导出 / 怎么验收

真源在游戏仓，导出器也在游戏仓：

```bash
cd C:/Users/yuyu/qqbot/data/plugins/dragonfall

# 单个域：导出（落盘）/ 只比对（不落盘）
python scripts/export_game_package.py --domain items
python scripts/export_game_package.py --domain items --check

# 全量覆盖验收（逐域导出 + --check + 编辑器侧条数/校验/联想候选）
python scripts/verify_package_coverage.py

# 同步门禁（包内文件 == 从真源重算，逐字节；含框架 schema 回环校验）
python tests/test_export_package_sync.py
```

框架侧另有两道门禁会守这个包：`tests/test_editor_dist.py`（结构不变量：id/domains/落点/entry）
与 `tests/run_all.py`（全量回归）。

## 三、包里**没有**什么（说清楚，免得当成漏了）

1. **机制/代码**：`content/apply.py`、`content/mech/*.py` 都还没有 —— 引擎因此只能读这份数据，
   **跑不起来这款游戏**。被动动作（26 个）、指令守卫实现、战斗脚本等仍在游戏仓 `game/services/*`、
   `game/commands/*`。这是 `docs/engine-wiki/reference/package-format.md` §七 的 **P4**，是剩下的大块。
2. **无框架域的内容表**：如装备名册 `EQUIP_ROSTER`(687)、符文 `RUNES`、传奇特效 `LEGENDARY_EFFECTS`(93)、
   套装固定词条 `SERIES_FIXED_AFFIX`(622)、`BRANCH_SKILLS` / `TUTOR_SKILLS` 等 —— 框架 `DOMAINS` 里
   没有对应域，要进包得**先加域**（DOMAINS + schema + 词典 + 路由 + 门禁）。
   → 逐张清单与建议见 `docs/engine-wiki/reference/package-format.md` §九。
3. **怪物名册**（id/中文名/role/lv/技能/掉落六元组）在游戏侧不是一张表，散在 `subareas.py` /
   `instances.py` / `mesh_rooms_*.py`；本包的 `monsters` 域是**怪物技能** `MONSTER_SKILLS`。
   因此 `drop_pools` 里按怪名的引用在包内解析不到（属已知，不是坏数据）。

## 四、这条链路的证据（都是一次性真跑出来的）

- 导出器：13 域逐个 `--check` 与真源一致；包内文件与 CLI 产物**逐字节相同**
- 框架侧回环：2691 条**每一条**都过框架 schema（`x-primary` def），待修 0
- 编辑器端到端：13 域全部 `ok=True`；每域首条可打开；域内特殊视图全通
  （`maps/<k>/graph` 121 图 628 节点/1252 连边、`instances/<k>/run` 27 本 81 层、
  `drop_pools/<k>/preview` 596 池）
- 框架全量回归 32/32；游戏仓全量回归 273/273
