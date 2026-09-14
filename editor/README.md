# editor/ —— 框架编辑器（数据层 + HTTP + 前端）

给**非程序员**改游戏内容的工具：读游戏包 → 渲染表单（带 schema 校验）→ 写回 JSON。
编辑器主进程**零引擎副作用**（不 import `saintess_engine`；真跑战斗在子进程，见 `simulate.py`）。

## 一句话架构

```
浏览器（web/app.js）
   ↕ HTTP/JSON
server.py       路由 + 缓存（列表分页 / 增量校验 / 提示缓存）
   ↕
packages.py     包 IO（清单 / **域注册表** / 条目 CRUD / 路径解析）
validate.py     单条 schema 校验（**全编辑器唯一的 schema 读取点**）
glossary.py     字段词典（中文名 / 注脚 / wiki 深链）；`REF_DOMAINS` = **框架默认**引用表
hints.py        跨域引用候选 + 包内已有取值（联想；`ref_names` 供 by=name 下拉）
relations.py    第 2 层声明面：`editor/relations.json`（引用/联动）+ `editor/views.json`（视图分派）
actions.py      机制动词清单（AST 扫包的 content/mech/*.py）
*_view.py       域级视图（**内置**）：loot_view（掉落展开）/ instance_view（副本进度）/
                space_view（地图拓扑）/ table_view（通用表格，语义中立）
dist.py         导入 / 导出包（zip，四道闸；导出含包自带 editor/、schemas/）
wiki.py         引擎 wiki 渲染（文档树 / 搜索 / 源码片段）
web/            index.html + app.js（无构建步骤的纯前端）
```

## 不变量：**域的真源在包**（2026-09-13 起）

「编辑器认识哪些域」的答案是**包自己的** `<pkg>/editor/domains.json`，不是框架里的常量：

```
effective_domains(pkg) = 包 editor/domains.json ∪（可选）框架内置默认集
```

* `packages.py` 里那份常量已降级为 **`BUILTIN_DEFAULT_DOMAINS`（回退默认集）**：
  **只在包里没有可用声明时兜底**（第三方包 / 坏包 / 未迁移的老包）。
  ★ 2026-09-13 B2b：**19 → 8，只留「引擎域」** —— 只有引擎侧真有消费端代码的域才内置
  （`effect_rules` / `passive_proc` / `commands` / `texts` / `tlogs` / `maps` /
  `drop_pools` / `instances`，逐个的消费端证据写在 `packages.py` 的注释里）；
  **内容域**（`skills` / `items` / `monsters` … 11 个）**不再内置**，只能由内容包声明
  （`games/orlandia/editor/domains.json` 声明 73 域；反证门禁见下）。
  同名的域一律**以包为准**（那份不参与取值，但必进一条可读 warning）。
* **加一个域 = 改包内 3 个文件**：`editor/domains.json`（声明）+ `schemas/<域>.schema.json`（校验）
  + `content/data|rules/<域>.json`（数据）。框架**一行不改**。
  最小样板：`examples/minimal-game/`（6 域全自带 schema，`{"$builtin": false}`）。
* 包也可以写 `{"$builtin": false}` 表示「本包的域就这些，不要兜底」。
* 坏声明只**降级**：该条（或整份）忽略 + 黄条告警（`/api/domains`、包概览的 `warnings`）+
  回退默认集；**绝不**「列表里有它、点开 500」。
* schema 解析顺序：`<pkg>/schemas/<声明值>` → `<pkg>/<声明值>` → 框架 `schemas/<声明值>` → 不校验。

规格与合并规则全文：`docs/engine-wiki/reference/package-format.md` §十。

## 包的扩展面（声明式到哪层）

设计稿：工作区 `overnight/editor-extension-design.md`（三层扩展面）+ 第 3 层实施稿
`overnight/layer3-render-design.md`（§9 分批）。第 1、2 层与第 3 层的**声明面**（§9 批 1 声明 +
批 2 白名单派生/沙箱）均已上线；包能声明的东西全部落在包自己的 `editor/` 目录里，框架一行不改。

| 层 | 包侧文件 | 能改什么 | 框架侧 |
|---|---|---|---|
| **1** | `editor/domains.json` + `schemas/` | 域集（新增域 / 同名覆盖）、schema 解析 | 内置 **8 个引擎域** = `BUILTIN_DEFAULT_DOMAINS`（**回退默认集**） |
| **2** | `editor/relations.json` | 字段↔域引用（下拉候选 + **引用校验**）、表单联动/只读 | `glossary.REF_DOMAINS`（只给候选、**不校验**）+ 无联动（默认空） |
| **2** | `editor/views.json` | 域 → **内置**视图（`loot_view` / `instance_view` / `space_view` / `table` / `graph`） | `relations.BUILTIN_DEFAULT_VIEWS`（`maps→space_view`、`drop_pools→loot_view`、`instances→instance_view`） |
| **3 · 批 1** | `editor/render/<域>.json`（每域一份；历史单文件 `editor/render.json` 仍读、已弃用） | 自定义渲染·**声明面**：版面（5 种块 / 分组 / 逐字段覆盖）、受控交互槽（白名单） → 出**受限渲染树**，不执行包代码 | `editor/render.py`（读声明 / 规范化 / 建树 / 限额）+ `render_decl.py`（声明校验 + 白名单表） |
| **3 · 批 2** | 同上（声明里只**点名**框架的白名单纯函数 `DERIVE_FNS`，包**不提供函数体**） | **白名单派生只读值**：值由沙箱子进程算（跑的是**框架**代码） → 并回受限渲染树 | `editor/render_worker.py`（派生沙箱子进程：一次性 / import 白名单 / 超时 / 输出上限；父侧 `render.py` 惰性 import） |

合入规则与第 1 层同一套纪律：**包声明 > 框架默认**；包**不声明**时行为**逐项不变**
（框架那份降级为默认值，不删）；坏声明（坏 JSON / 未知 view 名 / 未知域 / 形状不对）
**只降级 + 一条可读告警，绝不 500**（告警出口：`/api/domains`、包概览的 `domain_warnings`、
`/api/package/<id>/relations`、`/api/package/<id>/views`）。

`editor/relations.json` 形状（`*` = 对所有域生效，只用于联动）：

```json
{"monsters": {"drop_pool": {"ref": {"domain": "drop_pools"}},
              "elite_equip": {"ref": {"domain": "equip_roster", "by": "name"}}},
 "*": {"when": {"frozen": true}, "readonly": ["name"]}}
```

* `ref.domain` = 目标域；`ref.by` = 拿目标条目的 `key`（缺省）还是 `name` 当选者。
* **只有包声明的 ref 会进引用校验**（`relations.ref_errors`，落点是保存 PUT / 草稿 check /
  域徽标 / 全包校验）；框架默认那份只给下拉候选 —— 否则既有包的数据会被新校验判红。
* `when` + `show` / `readonly` 是**纯声明**（服务端只回传，`/api/package/<id>/relations` 的
  `linkage`），框架原本没有联动逻辑 → 默认集为空。

`editor/views.json` 形状：`{"talent_trees": {"view": "table"}, "my_dungeons": {"view": "instance_view"}}`

* 视图实现**只有内置那 5 个**（包不写新代码）。通用入口
  `GET /api/package/<id>/d/<dom>/<key>/view[?view=<名>]`；既有 `/preview` 与 `/run` 的
  域门槛也从「写死 `dom != "drop_pools"` / `dom != "instances"`」改成「**视图分派**是不是
  `loot_view` / `instance_view`」。
* 前端：选包后 `/api/glossary?pkg=` 会带上包声明的控件/引用表（`ref_source: package`），
  引用字段照旧渲染成下拉；`by=name` 用 `/api/package/<id>/hints` 的 `ref_names`。

**第 3 层还没做的**（`overnight/layer3-render-design.md` §9 分批）：**批 3** 可选代码档
（`editor/render/<域>.py` 的受限 `derive()`，**当前决定：不做** —— 声明面只做存在性识别 + 标红）、
**批 4** 导入面风险标注 + 包内 `render/$schema.json`、**批 5** `<域>.html.js` 的 iframe 只读路径（默认关）。
另：包只能**点名**白名单控件/校验钩子（`glossary.PKG_WIDGETS` / `render_decl.HOOKS` 是固定词表），
**不能注册自己的实现**（不能自带新控件或自定义校验器）。字段词典的**中文名/释义/分组/控件**真源
已搬进包（`editor/glossary/<域>.json`；框架 `GLOSSARY` / `GROUPS` / `WIDGETS` 只是回退默认集）。

## 跑法

```bash
python editor/server.py                 # 起服务（默认 127.0.0.1:8766；--games-dir 可换包目录）
python tests/test_editor_step3_pkg_first.py     # 域的真源在包（可复现：把内置默认集整体置空后仍完整可编）
python tests/test_editor_layer2_relations.py    # 第 2 层声明面（引用/联动/视图；包声明 > 框架默认，坏声明不炸，零回归）
python tests/run_all.py                 # 框架全量回归
```

UI 设计稿与交互约定见 `editor/UI_DESIGN.md`。
