# 包栈重构计划 —— 引擎通用化（2026-09-23 起）

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
