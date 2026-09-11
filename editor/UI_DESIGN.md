

---

## 7. 实施记录：字段词典 + 编辑器内文档（2026-09-11）

鱼鱼要求：「字段加个翻译，最好加点注脚」「之前做了 wiki，那个 wiki 能不能在网页访问，也可以放进编辑器来跳转」。

### 7.1 字段词典（`editor/glossary.py`）

schema 只说类型，说不清**谁读这个字段、写了会不会静默不生效**。词典把每个字段补成
**中文名 + 注脚 + 文档直链**，三条硬规矩：

| 规矩 | 做法 | 门禁 |
|---|---|---|
| 不发明事实 | 注脚只写 schema / `docs/engine-wiki/` / 源码读点能核实的语义 | `tests/test_editor_glossary.py` |
| 链接可解析 | 每条 wiki 引用**必须**在目标页正文里找到那个词 | 同上（100 条逐条核） |
| 不装懂 | wiki 没记载的键直说「未核实（用前看装配器）」 | 同上（空注脚 = 红） |

界面：`label` 后挂中文名（`lifesteal · 吸血比例`）、`ⓘ` 展开注脚、注脚里 `📖 打开文档`
跳到 wiki 那处并高亮。**注脚含「无消费者 / 未核实」的字段整块标黄** ——
`EFFECT_RULES` 的 6 个死字段（`debuff_scale` / `on_threshold` / `period.type` /
`period.per_layer` / `period.dmg_type` / `wake_on_hit`）现在在表单里一眼可见。

覆盖面：7 域 **182 个字段** 100% 有中文名（门禁断言）。

### 7.2 编辑器内文档（`editor/wiki.py` + 左栏「📖 文档」）

- 零依赖 markdown 渲染（标题/表格/代码块/列表/引用/行内码；HTML 一律转义）
- 34 页左导航（按 getting-started / concepts / guides / reference / architecture 分组）+ 本页目录
- **跨页搜词**（如 `debuff_scale`）→ 命中行列表 → 点进页面并高亮
- **源码直链**：正文里的 `effects.py:270` 可点 → 弹层显示该文件真实片段（带行号、标出目标行）；
  指向**游戏仓**的引用明确说「本仓读不到」，**不编源码**
- 深链 `#/wiki/<页>?find=<词>`：字段注脚与报错说明都走它，可分享、刷新保留
- mermaid 图：默认显示源码（离线可用），能联网时渐进增强渲染

### 7.3 顺带修掉的三个真 bug（都是实测抓的）

| # | 症状 | 根因 | 修法 |
|---|---|---|---|
| 1 | 切到别的 tab 再切回，**点原来那条条目毫无反应** | `openEntry` 的 `if (key === S.entryKey) return` 只看状态不看面板是否可见 | 判据改成「面板真在显示同一条」；切域走 `closeEntry()` 清状态 |
| 2 | **新建条目永远「未通过」，不知道什么规则** | `add()` 直接 PUT `desc:""`，被 schema `minLength` 拦（422）；前端读了 `validation.errors` 却只弹一句「新建失败」 | 改**草稿模式**：先开编辑器 → 实时列必填缺口 → 补全再落盘；422 报错翻成中文（`desc（描述）：不能为空`） |
| 3 | `GET /api/schema/<dom>` 404（潜伏） | 路由写成 `len(parts)==3`，2 段 URL 永不匹配（没人调用所以没暴露） | 修成 2/3 段均可，并补回归断言 |

新增 API：`/api/glossary`、`/api/wiki/tree|page|search|code`、
`POST /api/package/<id>/d/<dom>/[<key>]/check`（**只校验不写盘**）。
回归：`test_editor_api` 41 断言 · `test_editor_glossary` 18 · `test_editor_wiki` 25，框架全量 15 文件全绿。
