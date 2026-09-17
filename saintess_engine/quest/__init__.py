# -*- coding: utf-8 -*-
"""任务账本形状（quest）—— **任务账本**（`QuestLog`）+ **目标类型注册表**（`Objectives`/
`Objective`/`parse_needs`）+ **单条只读外壳**（`Quest`）。引擎零知识。

**为什么有它**：参考实现里，一个任务系统被写成了三套状态机（主线一条链 / 支线多条 /
每日多条）× 三份目标行渲染（接取单行 / 交付多行 / 面板进度行）× 一张目标类型词表。
把「哪个字段叫当前任务 / 哪个词算完成 / 哪些目标类型存在 / 需求数怎么数 / 行怎么写」
这些**取值**全部剥掉，剩下的只有三件形状：

| 形状 | 一件什么事 | 谁给 |
|---|---|---|
| `QuestLog` | 一个 mapping 的四条读口 + 六个状态迁移（**不落库**） | 字段名 / 状态词 / 子账本形态全注入 |
| `Objectives` | **有序**目标类型注册表：命中 / 需求数 / 折叠进度 / 出行文骨架 | 类型名与四个回调全在内容侧 |
| `Quest` | 一条任务的只读外壳（id + 目标 + 下一环） | 三个字段名由调用方注入 |

用法::

    from saintess_engine.quest import Objective, Objectives, Quest, QuestLog, parse_needs

    fields = {"current": ..., "status": ..., "progress": ...,
              "archive": ..., "lanes": ...}          # 取值：存档字段名（内容侧给）
    states = {"todo": ..., "live": ..., "ended": ...}  # 取值：状态词（内容侧给）
    lanes  = ((..., {"progress": dict}), ...)          # 取值：子账本名 + 进度容器形态

    log = QuestLog(db.get_quests(...), fields=fields, states=states, lanes=lanes)
    log.current / log.status / log.progress / log.done / log.lane(...) / log.entry(...)
    raw = log.deliver(lane=None, next_of=lambda cur: ...).snapshot()   # 调用方自己落库

    objs = Objectives(Objective(<类型名>, match=..., need=..., fold=..., text=...,
                                multi=False, modifiers=(...)), unknown=..., need_of=...)
    objs.keys() / objs.parts(obj) / objs.hits(obj, event) / objs.fold(obj, prog, event)
    objs.satisfied(obj, prog) / objs.complete(obj) / objs.lines(obj, text_of=...)
    parse_needs(obj, need_of=..., modifiers=(...))

**引擎认什么**：只认**结构字段名**与**注入口**。`fields` 的角色键是引擎的契约词汇：
`current` / `status` / `progress` / `archive` / `lanes`；`states` 的角色键同上只有三个：
`todo` / `live` / `ended`（`accept` 缺省用 `live`，`is_open` 只跟 `ended` 比）。
⚠️ 与设计稿的差别（**有意**，理由在下面「命名口径」）：设计稿把这两组角色键写成
`current`/`status`/`progress`/`done`/`lanes` 与 `open`/`running`/`ready`/`closed`，
而 `done` / `open` / `closed` / `running` / `ready` **本身就是取值词**（见下「零知识」），
引擎源码里出现即触门禁；因此角色键改用同义的引擎词（**属性名照旧叫 `done`**，
因为属性名不是字符串常量）。注入面的**语义一字未变**，只是角色键的名字换了。

**零知识（门禁逐条钉住）**
--------------------------
* 引擎源码的**代码路径**字符串常量里零取值词（目标类型词 / 状态词 / 字段名 / 事件名 …）。
* 引擎只 import 标准库 + 相对导入；**不** import `os` / `sys` / `json` / `datetime` /
  `time` / `calendar` / `random`（不落库、不读钟、不读环境）。
* 状态词、字段名、目标类型、需求数口径、行文模板、`unknown` 策略全部注入；引擎零默认取值。

**12 条口径分歧（故意不统一 —— 后人不得顺手统一）**
--------------------------------------------------

① **主线无终结状态**：主 lane 交付后 `status` 回 `todo`，完成写进 `archive`（保序列表，
   追加**不去重**）；子账本交付写条目 `status = ended`（最小终态一格），**不**追加历史。
   主线是单条链（「完成过哪些」是历史），子账本是多条目账本（每条要有终态）；
   统一成「都带终态」= 改存档（主线要多一列/多一格）。

② **三份目标行渲染不合并**：引擎只出 `list[str]` **骨架**（复合目标**全出**，行序 =
   目标 mapping 插入序），行文由各出口自己的 `text_of` 注入（现状 接取单行 / 交付多行 /
   面板进度行 的行文与覆盖面都不同）。引擎若自己产文案，就必然选一个口径 = 改玩家可见文案。

③ **进度容器 mapping ∪ int**：主/支线 lane 声明 `progress: dict`（复合目标按值分桶），
   每日 lane 声明 `progress: int`（单键目标的整格计数）。`deliver`/`accept` 清空时
   分别写 `{}` / `0`；`satisfied` 分别按「按值取键」/「整格比数」判定。这是**显式声明**的
   差异，不是强行归一。

④ **需求数两种口径**：`数量修饰 or 基础数` 与 `只看基础数` 都保留。引擎用 `need_of`
   注入口把口径**交还内容侧**（`Objective.need` 回调优先，其次注入的 `need_of`；
   `parse_needs` 的默认口径是「首个正整数修饰键，退 1」，修饰键名**必须**由调用方给）。
   现状两种写法在无数量修饰时等价，所以没炸；引擎不替内容侧选一个。

⑤ **未注册目标类型三出口**：引擎给 `unknown(key, value)` 策略注入口，**默认（未注入）=
   返回 `None`（不出行）**；内容侧各出口可返回 `"？"`（接取行兜底）或 `None`（面板不加行）。

⑥ **`next` 缺失 ≠ `next: null`**：`Quest.next` 对两者都返回 `None`（引擎不区分）；
   「None 是终章还是数据缺」由内容侧裁决 —— `QuestLog.deliver(next_of=...)` 把
   `next_of(None)` 交出去，内容侧决定映射成什么。

⑦ **进度键由内容侧决定，引擎不翻译**：`fold` 返回的补丁键原样写出；`satisfied` 只按
   「目标值 = 进度键」这一个口径读。含目标名的**历史老键**的聚合兼容（现状刻意保留）
   留在内容侧，引擎不许把它统一掉。

⑧ **三个门槛的失败语义不同**：`require_stats` 不满足 → 不出现且**无提示**（隐藏线）；
   等级/种族门槛不满足 → 不出现**且有提示**。引擎一个门槛都不认（无过滤 API、无门槛字段）。

⑨ **「不进列表」≠「面板不可见」**：引擎对条目**零过滤**（带任何标记的条目照常可读），
   列表过滤与面板展示的差异是内容侧的信息设计。

⑩ **每日任务键 = 名字（没有 id）**：条目键是**不透明字符串**，引擎原样保留（中文/空格都行），
   不做任何归一、不解析、不匹配源侧 id。

⑪ **跨天清理用系统钟，不用注入钟**：这是**缺口不是设计**（改它 = 越界行为修复）。
   引擎**一个钟都不读**：`QuestLog` 没有任何时钟注入口，`snapshot()` 只有原字段。

⑫ **行序 = 信息序**：`lines` 不重排、不去重；拒绝提示的「先接取行 → 再拒绝行 → 最后
   已完成提示」是刻意的信息序，引擎只保证保序，不发明顺序。

**明确不做的事**
----------------
* ❌ 目标类型词表（击败/收集/交谈/探索/寻找/使用 …）进引擎 —— 取值，内容侧原地注册。
* ❌ 状态词（未接取/进行中/可交付/已完成 …）进引擎 —— 取值，`states` 注入。
* ❌ 字段名默认值（内容字段名由调用方注入；引擎不内置任何内容字段名）。
* ❌ 奖励发放 / 声望 / 剧情文案 / 分支抉择 —— 取值 + 副作用，全落命令层。
* ❌ 日任务抽取、重复衰减、单日上限、随机源 —— 数值 + 随机机制。
* ❌ 跨天清理改走注入钟 —— 属行为修复，不在「只抽形状」范围。
* ❌ 面板渲染（图标 / 分隔线 / 分页 / 每日段 / 提示语）—— 渲染留内容侧。
* ❌ 存档 schema（表结构 / 列名 / 键格式 / 落盘 JSON 文本）—— **一字节不动**。
* ❌ 依赖解析 / 任务图校验（悬空 `next`、解锁闭环）—— 导出器职责；读路径零遍历。
* ❌ 落库（连接 / SQL / 事务边界）—— 引擎只搬值，落库由调用方显式做（`snapshot()`）。

**为什么不复用 `run.Progress` 与 `collect`**
--------------------------------------------
* `run.Progress` 是「**一次运行**内的有序节点 + 具名剩余池 + budget」，生命周期 = 一次运行，
  可变的线性进度；任务账本是**跨会话持久**的账本（当前条目 + 完成历史 + 多 lane）。
  名字里都有「进度」，但没有一处语义重合：`Progress` 不认「完成历史」，账本不认「节点池」。
* `collect` 是「条目集合 + 已发现集 + N/M 档位领取」的**只读**进度；任务账本要**写**
  （承接 / 交付 / 放弃）并返回新 mapping。`collect` 没有状态迁移，合并会让它长出不属于它的方法。
* 同理**不**与 `periodic` 合并：`periodic` 是「**周期键** → 一格值」，账本跨周期持久
  （每日 lane 只是其中一格），跨天清理是内容侧的活，不是周期槽的活。
"""
from __future__ import annotations

from collections.abc import Mapping

from .ledger import QuestLog
from .objective import Objective, Objectives, parse_needs

__all__ = ["Quest", "QuestLog", "Objective", "Objectives", "parse_needs"]


def _as_field(value, label: str) -> str:
    """字段名必须由调用方注入（引擎不内置任何内容字段名；非空字符串）。"""
    if not isinstance(value, str) or not value:
        raise TypeError(label + " 必须是由调用方注入的非空字段名（引擎不内置内容字段名）")
    return value


class Quest:
    """一条任务的**只读外壳**：id + 目标 + 下一环。构造 O(1)（只存引用 + 校验注入面）。

    三个字段名由调用方注入：`id_key`（通用契约名，缺省 `id`）· `objective_key` ·
    `next_key`（后两个是**内容字段名**，必须显式给 —— 引擎不内置内容取值）。
    `objective` 缺失 / 空 → `{}`；`next` 缺失或字面 `None` → `None`（引擎不区分，见口径⑥）。
    """

    __slots__ = ("_row", "_objs", "_id_key", "_obj_key", "_link_key")

    def __init__(self, row, *, objectives: Objectives, id_key="id",
                 objective_key=None, next_key=None) -> None:
        if not isinstance(row, Mapping):
            raise TypeError("row 必须是 mapping，收到 " + type(row).__name__)
        if not isinstance(objectives, Objectives):
            raise TypeError("目标注册表必须是 Objectives 实例，收到 "
                            + type(objectives).__name__)
        self._id_key = _as_field(id_key, "任务 id 字段名")
        self._obj_key = _as_field(objective_key, "目标字段名")
        self._link_key = _as_field(next_key, "下一环字段名")
        self._row = row
        self._objs = objectives

    @property
    def id(self):
        """任务 id（注入字段名的取值）；缺失 → `None`。"""
        return self._row.get(self._id_key)

    @property
    def objective(self):
        """目标 mapping；缺失 / 空 → `{}`（现状 `or {}` 口径）。"""
        return self._row.get(self._obj_key) or {}

    @property
    def next(self):
        """下一环的 id；缺失 / 字面 `None` → `None`（**不回落**，裁决交内容侧）。"""
        return self._row.get(self._link_key)

    def lines(self, *, progress=None) -> list:
        """接取 / 交付通知入口：目标行**骨架**（进度可缺）。"""
        return self._objs.lines(self.objective, progress=progress)

    def progress_lines(self, progress) -> list:
        """面板入口：同一骨架，**进度必给**（两个入口共用一份实现，不各自产文案）。"""
        return self._objs.lines(self.objective, progress=progress)

    def __repr__(self) -> str:
        return f"Quest(id={self.id!r})"
