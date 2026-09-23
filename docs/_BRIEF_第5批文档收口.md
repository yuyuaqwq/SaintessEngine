# 第 5 批 · 文档收口作业书（每路一节，只做自己那一路）

## 背景：这个仓刚刚做完一次架构重构

`C:\Users\yuyu\framework-engine` 是一个**通用文字游戏引擎**。2026-09-23 的「包栈重构」
把原本混在引擎里的**游戏原语**全部抽了出去，现在是三层：

```text
引擎 engine-core          saintess_engine/     通用件，零游戏词汇
扩展包 ext-*              extends/<包>/        可插拔的游戏能力（能互相依赖）
数据包 game-*             games/<包>/          一款游戏的内容（只允许一个）
依赖方向严格单向： 数据包 → 扩展包 → 引擎（门禁 tests/test_layering.py 钉死）
```

**已经搬走的 18 个模块 → 8 个扩展包**（文档里凡是讲这些模块的地方，口径都过时了）：

| 原引擎模块 | 新家 | 消费端 / 语义 |
|---|---|---|
| `battle/` `gauge/` `formation/` `panel/` | `extends/ext_combat/` | CTB / 结算 / 效果 / 面板 / 计量条 / 站位 |
| `quest/` | `extends/ext_quest/` | 任务账本 + 目标类型 |
| `space/` `run/` | `extends/ext_world/` | 地图节点与拓扑 · 准入链/进度/名单 |
| `collect/` `periodic/` `timers/` `unlock/` | `extends/ext_life/` | 收集计数 / 周期 / 倒计时 / 解锁闸门 |
| `trade/` `shelf/` `produce/` | `extends/ext_economy/` | 交易限购 / 货架 / 计时生产 |
| `membership/` `presence/` | `extends/ext_social/` | 成员职位与贡献 / 在场清单 |
| `loot/` | `extends/ext_loot/` | 掉落池 / 档位阶梯 / 槽位挂载 |
| `dialogue/` | `extends/ext_dialogue/` | 对话树与会话游标 |

引擎里现在只剩：`config` `domains` `package` `store` `command` `events` `clock` `container`
`text` `session` `log` `tlog` `records` `conditions` `bonus` `grant` `gates` `wire` `expr`
`formula` `host` `version` `_validators` `_sinkbase`。

**另外两条口径也都变了**：

```text
① 装法：数据包在 game.json 里写 "depends": ["ext_combat", "ext_world", ...]，
        包栈按拓扑序装好（引擎仓的 extends/ 是默认搜索路径；也可用环境变量
        SAINTESS_EXTENDS 或数据包同级的 ../extends）。
② 域（编辑器里的数据表声明）跟消费端走：effect_rules / passive_proc 住在 ext_combat，
        maps / instances 住在 ext_world，drop_pools 住在 ext_loot。
        分层 = 引擎默认集（commands/texts/tlogs）→ 该包 depends 的扩展包 → 包自己的声明。
        编辑器与装载口共用同一份（saintess_engine.domains.layered_decls）。
③ 能力提供者：扩展包可以在 game.json 里声明 "provides": {"battle": "ext_combat.battle.battle:Battle"}，
        宿主/内容按**键**取件（引擎只认「键 + 引用」，不认识"战斗"这个词）。
```

## 硬约束（每一路都守）

- **不许新建或删除任何 `.md` 文件** —— wiki 有页清单门禁（`tests/test_editor_wiki.py` 会红）。
  要新建文件请报告给主线（主线统一改页清单）。
- **只改自己那一路的文件**，别碰别人的。
- 用 `execute_code` 里的 Python 读写文件（`io.open(path, encoding="utf-8", newline="")`）。
  ★ 这台机器的 `terminal` 走 git-bash 且 `.bashrc` 有问题 —— **不要用 bash 命令**。
- **不要跑 git 命令**（多路并发会撞 index.lock），也不要跑全量测试。
- 写完后用 `python -c "import ast"` 无关（md 不是 py）；改成：自查「旧路径零残留」
  （`saintess_engine/<已搬走的模块名>` 的写法一处都不该留）。
- 口径统一：**引擎 / 扩展包 / 数据包**（别再造新词）；一句"装法"永远是
  `"depends": ["ext_xxx"]`。
- 保留原文风格（这些文档是中文、偏技术手册口吻、爱用表格与代码块）—— **别整篇重写成博客**，
  要改的是**过时的口径**，不是文风。

## 报告格式（人话、简洁）

```text
改了哪些文件（行数前后）
每处改动的性质：路径repair / 口径更新 / 新增段落（例：顶部加「此能力在扩展包」块）
旧路径残留自查：0 处 / 剩下哪些（说明原因）
需要主线处理的：新建文件 / 页清单 / 别的
```

---

## 路 A：总览与边界

**文件**：`docs/engine-wiki/README.md`、`docs/engine-wiki/architecture/boundaries.md`

- README：把「模块布局」改成三层（引擎 / 扩展包 / 数据包）；说明包栈（kind / depends /
  namespace / 域分层 / provides）；**保持那行「引擎目录数字」可解析**（门禁靠正则抓它，
  格式是 `（**N** 个子包 + **M** 个顶层模块；共 **K** 个 `.py` / **L** 行）` —— 数字**别改**，
  主线会跟代码一起校准）。
- boundaries.md：分层边界那套论断按三层重写（哪一层能做什么、依赖方向、门禁在哪）。

## 路 B：包格式权威规格

**文件**：`docs/engine-wiki/reference/package-format.md`（467 行，是权威规格）

要覆盖到：`game.json` 全字段（`id` / `kind: game|extension` / `depends` / `namespace` /
`engine` / `entry` / `provides` / `domains` / `bind` / `domain_decl` / `domain_dirs`）、
目录结构、加载入口（`load_stack` / `probe_stack`）、命名空间规则（数据包固定 `content`，
扩展包 = 目录名）、依赖规则（数据包→扩展包、扩展包→扩展包、扩展包依赖数据包 = 报错、成环 =
报错）、**域分层**（引擎默认集 → depends 的扩展包 → 包声明；`domain_layers()` 审计）、
扩展包搜索路径（`default_ext_dirs`：环境变量 → 数据包同级 `../extends` → 引擎仓 `extends/`）、
数据包只能一个的六条硬撞理由、`examples/host-skeleton` 与 `extends/ext_quest` 两个可照抄的样板。

## 路 C：15 篇「已搬迁模块」参考页

**文件**（都在 `docs/engine-wiki/reference/` 与 `guides/` 下）：

```text
reference/battle-declarations.md · reference/panel.md · reference/effect-rules.md ·
reference/passive-proc.md · reference/effect-actions.md · reference/loot.md ·
reference/quest.md · reference/space.md · reference/run.md · reference/dialogue.md ·
reference/presence.md · reference/unlock.md · reference/store-blobs.md ·
getting-started/first-battle.md · guides/use-engine-shapes.md ·
guides/add-a-passive.md · guides/write-a-mechanic.md
```

每篇**在顶部（H1 之后）加一个统一的归属块**，并把正文里「引擎某模块」的措辞改成扩展包口径：

```markdown
> **归属**：本能力**不在引擎里**（2026-09-23 起）—— 它在扩展包 `extends/<包>/`。
> 数据包要用它：`game.json` 里写 `"depends": ["<包>"]`。
> 引擎侧只剩通用件，见 `architecture/boundaries.md`。
```

（`<包>` 按上面那张表填；`guides/*` 两篇讲机制的若主体仍是引擎侧（`content/mech/`），
只加「配套的引擎形状现在在哪个包」一句即可。）

## 路 D：API 面

**文件**：`docs/engine-wiki/reference/api.md`（421 行）、`docs/engine-wiki/reference/host-api.md`（165 行）

- api.md：引擎门面（`saintess_engine/__init__.py` 的 `__all__`）现在**只有通用件**；
  需要 `Battle` / `Space` / `LootTable` / `Dialogue` … 的写法是 `from ext_combat import Battle`
  这类。★ 里面有一处引用 `saintess_engine/__init__.py:82-105`（`__all__` 的行号区间）——
  行号由 `tools/remap_wiki_refs.py` 统一校准，**别手改行号**，只改文字口径。
- host-api.md：宿主现在通过包栈加载（`load_stack` / `Host(...)`），战斗能力走
  `provides` 声明（没装战斗包时报一句可读的话，不是 import 炸）。
