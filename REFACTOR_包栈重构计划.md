# 包栈重构计划 —— 引擎通用化（2026-09-23 起）

> 进度：第 0–5 批 **已完成**；引擎 111 py / 24,840 行 → 63 py / 12,368 行（原 36 子包 → 18）。
> 第 3 批实际切法（与下面的初稿不同）：13 个形状 → **6 个扩展包**，六路并行搬迁。

> 目标：引擎从「战斗引擎 + 一堆游戏原语」变成**通用文字游戏框架**；
> 游戏原语（战斗 / 副本 / 任务 / 经济 / 社交 / 图鉴 / 世界）抽成**可插拔扩展包**。
> 终态判据（可判定）：
> ① 引擎不 import 任何游戏原语（门禁 AST 扫）
> ② **没有任何扩展包**时：能加载最小数据包、跑文字流程、不报「缺战斗」
> ③ 装上 `ext_combat` 时：能跑一场真战斗（真产生伤害）
> ④ 奥兰迪亚全量测试绿（迁移物验证「真东西装得下」）

---

## 已完成 · 第 0 批（机制）

```text
包栈加载器    saintess_engine/package.py 全文重写（+726 行）
              kind(game|extension) · depends · 拓扑加载 · 环检测 ·
              命名空间隔离（数据包 content / 扩展包 = 目录名）· 域分层
新门禁        tests/test_package_stack.py（15 项，全绿）
删除          host/package.py · package.load() · 旧门禁（不留兼容）
提交          787f8bf   全量：82 文件 · 通过 75 · 失败 7（全部为基线既有，零新增）
```

---

## 第 1 批 · 抽 `ext_quest`（最低风险，先验证流程）

```text
范围      saintess_engine/quest/（969 行 · 零内部依赖 —— 实测没有任何模块 import 它）
做       引擎删 quest/ → 建扩展包 ext-quest（game.json kind=extension）
         records 装载口去掉 quest 相关默认域；跟着搬的门禁
验收     包栈门禁仍绿；全量失败数不增（=7）；数据包 depends 后 quest 功能可用；
         不 depends 时引擎照常跑，不报错
风险     低。这一批的任务是**把「搬出去」的流程跑顺**，不是搬多少
```

## 第 2 批 · 抽 `ext_combat`（最重的一块，单独批次 + 单独回滚点）

```text
范围      battle(5,387) + gauge(465) + formation(239) + panel(326) = 6,417 行
附带      · 解耦 host → battle（host 改成「有战斗包就开战斗通道，没有就不开」）
         · 编辑器 4 文件（glossary · simulate_worker · dist · packages）改可选装配
         · examples/minimal-game 改 depends: ["ext_combat"]
         · 引擎 __init__ 不再 re-export Battle / make_actor（改从扩展包取）
         · 测试分家：约 10 个测试文件跟着战斗走
验收     全量失败数不增；minimal-game 冒烟跑通（含「真产生伤害」）；
         无战斗包时引擎能 import + 跑非战斗流程
风险     高 —— battle 是引擎最成熟的部分；**动它前后都记 HEAD，出事 checkout 秒回**
```

## 第 3 批 · 抽其余游戏原语（按引用量从少到多）

```text
3a 小件    dialogue(414) · collect(218) · trade(243) · produce(274) ·
           periodic(298) · timers(360) · unlock(285)
3b 世界    space(473) + run(679)              → ext_world（地图与副本）
3c 大件    loot(938)                          → ext_loot
           shelf(389) + trade + produce       → ext_economy
           membership(445) + presence(417)    → ext_social
验收       每件独立可插拔；每批跑全量
```

## 第 4 批 · 域归属重排

```text
跟着扩展包走   maps → ext_world · drop_pools → ext_loot · instances → ext_world
留在引擎       effect_rules · passive_proc · commands · texts · tlogs
验收           门禁绿；编辑器能显示「这个域来自哪一层」（domain_layers 已具备）
```

## 第 5 批 · 门禁与文档收口

```text
新门禁   引擎分层守卫：通用件不许 import 游戏原语（AST 扫，防回流）
文档     engine-wiki：模块图 · 包格式（已更新）· 迁移指南 · 参考页
公开面   引擎 __init__.py 按「通用件」重划（不再 re-export 游戏形状）
```

## 第 6 批 · 奥兰迪亚全量迁移（验证「真东西装得下」）

```text
做       奥兰迪亚 game.json 声明 depends 全套扩展包；140 处 battle import 改路径
验收     奥兰迪亚自己的 scripts/run_all_tests.py 绿
```

---

## 纪律（每批都适用）

```text
· 一批一个提交 + 回滚点（改前记 HEAD）
· 每批跑全量；失败数必须 = 基线 —— 用 stash 基线对比，不靠印象
· 不许留兼容壳，旧 API 全删（引擎铁律）
· 搬迁批次不混别的改动；文档跟着改（README 数字 / wiki / 包格式）
· 编辑仓内文件必须保 LF（io.open 要 newline=""，否则整文件 CRLF 污染）
```


## 已完成（实际，2026-09-23）

```text
第0批 ✅ 787f8bf  包栈加载器（kind/depends/拓扑/环检测/命名空间/域分层）
第1批 ✅ 80a9a6a  ext_quest（969 行）—— 打通「搬出去」的流程
第2批 ✅ f60e5c7  ext_combat（6,417 行 = battle+gauge+formation+panel）
                  + 引擎新增「能力提供者」声明 provides（引擎只认键+引用，零游戏词汇）
                  + 解耦 host→Battle（改走 provides.battle）
第3批 ✅ 本轮     6 个新扩展包 · 13 个形状（5,433 行）· 六路并行搬迁
                  ext_world(space+run 1,152) · ext_life(collect+periodic+timers+unlock 1,161)
                  ext_economy(trade+shelf+produce 906) · ext_social(membership+presence 862)
                  ext_loot(loot 938) · ext_dialogue(dialogue 414)
                  + 包栈支持「扩展包搜索路径的约定默认」（default_ext_dirs）
                  + 12 个形状门禁跟着包走 · 引擎门面只剩通用件
第4批 ✅ 域跟消费端走 —— 引擎默认集 8 → 3，5 个域随扩展包迁出；
         编辑器与装载口统一走 layered_decls（唯一一份分层合并）
第5批 ✅ 分层守卫（tests/test_layering.py：引擎/扩展包/数据包 的依赖方向）
         + 文档收口（README/boundaries/package-format/api/host-api + 17 篇参考页归属块
         + 新页 guides/build-a-game-package.md）
第6批 奥兰迪亚全量迁移（各批已顺带迁完，剩：跑它自己的全套测试做端到端验证）
```

---

## 收口记录（2026-09-23 夜）

| 批次 | 状态 | 提交 | 真实账 |
|---|---|---|---|
| 第 0 批 | ✅ | `787f8bf` | 包栈加载器（kind · depends · 拓扑加载 · 环检测 · 命名空间隔离 · 域分层） |
| 第 1 批 | ✅ | `80a9a6a` | `ext_quest` 969 行搬出（git 认 rename 100%） |
| 第 2 批 | ✅ | `f60e5c7` | `ext_combat` 6,417 行 + `provides` 能力提供者机制（host 不再 import Battle） |
| 第 3 批 | ✅ | `9e7ab1a` | 6 路并行 · 13 模块 5,433 行 → 6 个扩展包（2 分 4 秒） |
| 第 4 批 | ✅ | `ad4220f`+`b429f17` | 域跟消费端走 · 引擎默认域集 8 → 3 · `layered_decls()` 唯一源 · 奥兰迪亚 106 → 98 |
| 第 5 批 | ✅ | `24df283`+`14d7c56` | 分层守卫 `tests/test_layering.py`（6 项）· 4 路文档收口 · 新页《把一款游戏写成一个数据包》 |
| 第 6 批 | ✅ | 包仓 `8920ae7` | 奥兰迪亚全量 **286 个测试 → 286 绿 / 0 红** |

### 终态四条判据（逐条对账）

1. **引擎不 import 任何游戏原语** ✅ —— `tests/test_layering.py` AST 扫；引擎里 18 个已搬迁模块的目录也不许再出现。
2. **没有扩展包时能加载数据包、跑文字流程、不报「缺战斗」** ✅ —— `provides` 声明 + `stack.provider()`；`exts=[]` 严格模式门禁。
3. **装上 ext_combat 能跑一场真战斗（真产生伤害）** ✅ —— `examples/minimal-game` 冒烟 25/25（真跑战斗）。
4. **奥兰迪亚全量测试绿** ✅ —— 286/286。

### 遗留

* `test_v184_loot_pools` 的「未知 strategy」用例：引擎早先的 fail-closed 改造（未知策略不再静默回落 weighted）
  已按「测试跟随被测」单列为 D0 断言。
* 冻结门禁的历史快照执行环境由 `tests/_engine_move_shim.py`（**测试侧**垫片）提供 ——
  引擎侧不留兼容名（那正是重构要消灭的东西）。
* 未 push、未 bump 宿主仓 `framework/` 指针（线上机器人已停，等鱼鱼发话）。
