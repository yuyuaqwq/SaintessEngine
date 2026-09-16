# -*- coding: utf-8 -*-
"""对话树形状（dialogue）—— 节点 / 选项 / 条件槽 / 渲染槽 + 会话游标（引擎零知识）。

**为什么有它**：一棵「跟谁说话 → 说哪句 → 给哪些选项 → 选了去哪」的树，在真实项目里
被读了一遍又一遍 —— 取节点、过滤可见选项、按条件择优挑台词、把选项路由到下一节点、
把「当前聊到哪」写进存档再读回来。把「哪个主体 / 哪句台词 / 什么条件 / 什么动作」这些
**取值**拿掉，剩下的只有五件形状：

| 形状 | 一件什么事 | 谁给 |
|---|---|---|
| 树 | `nodes` 按 id 取节点；未知 id **回退 `start`** | 内容侧数据 |
| 条件槽 | 节点/选项上挂一个 `need`，逐键问注入的谓词查表口 | 谓词实现与条件名全在内容侧 |
| 渲染槽 | `text` / `texts`（条件变体）/ `text_from`（注入的自动文本源） | 台词与生成器全在内容侧 |
| 路由 | 选项 `next` / `fail_next` → 下一个节点 id | 节点 id 与失败转由数据给 |
| 游标 | 「跟谁 + 在哪」两个**不透明字符串** | 字段名与存储键由调用方给 |

**引擎一个取值都不认**：结束哨兵、兜底台词、自动文本源的取值、条件名、动作载荷
全部经**注入面**给（`end_marker` / `fallback_text` / `conditions` / `unknown` /
`text_sources`）。引擎源码里没有任何一个取值字面量（零知识静态扫描把这条钉住）。

**字段级契约**（引擎把调用方的原始 mapping **原样持有**：不归一、不拷贝、不补默认值，
只按下列**契约字段名**读）::

    树      start: str              缺失 → None（回退时 nodes.get(None, {}) → {}）
            nodes: {id: 任意}       缺失 → {}；值可以是任意对象（含 None）→ **原样**返回
    节点    text: str               缺失 → 注入的 fallback_text
            texts: [{need, text}]   声明序 = 优先级；取第一个满足者；变体缺 text → KeyError
            text_from: str          → text_sources 的键；不在注入表内 → 跳过
            options: [opt]          缺失 / 空 → []
    选项    text: str               **引擎不读**（渲染留调用方）
            next: str               缺失 → end_marker
            need: {str: 任意}       缺失 / 假值 → 不限
            action: 任意            **完全不透明**，只做「原样带出」
            fail_next: str          缺失 → 回落 next；**存在但假值 → 就用它**（不回落）
            side_menu: 任意         `is not None` → 走动态展开分支
    ctx     任意                    引擎一个字段都不读，只整体透传给注入的谓词 / 文本源

**注入面**（引擎里**没有任何默认取值**；前四个必填，`text_sources` 是唯一可选的结构项）::

    end_marker     结束哨兵（**取值**：数据里的约定，改它 = 内容侧改一行）
    fallback_text  节点没有台词时的兜底文案（**取值**：文案）
    conditions     谓词查表口：只需 `get(key) -> callable | None`（鸭子类型，引擎不 import 它）
    unknown        未注册 need 键的策略：`unknown(key, value) -> bool`（真 = 放行；可抛）
    text_sources   {text_from 取值: fn(node, ctx) -> str | None}（可选；`None` = 无自动文本源）

用法::

    from saintess_engine.dialogue import END_KEY, Cursor, Dialogue

    cfg = Dialogue(end_marker=<结束哨兵>, fallback_text=<兜底文案>,
                   conditions=<有 get(key) 的查表口>, unknown=<未注册键策略>,
                   text_sources={<取值>: <生成器 fn(node, ctx)>})
    dlg = cfg.of(tree)                       # O(1)：只换树引用；不遍历、不缓存
    node = dlg.node(dlg.start)               # 未知 id 静默回退 start
    opts = dlg.options(node, ctx, expand=expand_fn)      # 声明序；side_menu 就地展开
    line = dlg.text(node, ctx)                            # 变体 → 自动源 → text → 兜底
    opt = dlg.pick(node, 1, ctx, expand=expand_fn)        # 1-based；越界 → None（不抛）
    nxt = dlg.next_of(opt, failed=action_failed)          # next / fail_next / end_marker
    if dlg.is_end(nxt):
        ...                                  # 结束：会话怎么清由调用方决定（引擎不落盘）

    cur = Cursor.of(raw, subject_key=..., node_key=...)   # 存档映射 → 游标（坏值 → None）
    new = cur.moved_to(nid2)                              # 值对象：返回新游标，原对象不动
    raw = new.state(subject_key=..., node_key=...)        # 键名由调用方给（引擎不拼键）

**十条口径分歧（故意不统一 —— 后人不得顺手统一）**
--------------------------------------------------

1. **未知节点 ≠ 结束**：`node(未知 id)` **静默回退 `start` 节点**；`is_end` 只认注入的
   结束哨兵。悬空跳转是数据笔误；若把未知节点判成「结束」，笔误会静默吞掉整段对话，
   回退 `start` 至少还能看到开场白。
2. **`side_menu` 的空映射 ≠ `null`**：判据是 `is not None`。`{}` 走**展开分支**
   （展开为空 → 整项消失），`null` / 缺失走**普通分支**（选项照常出现）。
   `null` 是「这选项不是菜单」，`{}` 是「是菜单但没配参数」——用真值判定会把后者
   变成可见的空选项。
3. **未注册 need 键的三态（放行 / 拦截 / 抛错）不在引擎**：由注入的
   `unknown(key, value)` 决定（内容侧生产告警放行、测试抛错）。向后兼容旧数据与
   让单测抓数据笔误，两个目标都要，「什么算测试环境」由内容侧判定。
4. **`texts` 变体取「声明序第一个满足者」，不取「最具体」**：「最具体」需要引擎理解
   条件强弱，那是内容判断；声明序是数据作者能掌控的唯一口径。
5. **变体缺 `text` 键 → `KeyError`；节点缺 `text` → 回落 `fallback_text`**：
   变体是 schema 必填（笔误该炸）；节点默认台词允许缺省（构造期半成品数据）。
6. **`options()` 返回调用方的原对象**（`is` 相同），不拷贝：调用方要接着读它的
   `text` / `action` / `next`；拷贝会改内存语义，对每次渲染也是白开销。
7. **空 mapping 会话 ≠ 坏值会话**：`Cursor.of` 对二者都回 `None`（它只做「还原」，
   不做「清理」）；「空壳要不要清残留」留在调用方 —— 空壳清它无意义，坏值不清会
   永久拦住移动。两种口径不可统一成一句 `if not raw`。
8. **need 结果用真值判定**（`if not fn(ctx, value)`），**不用 `is False`**：谓词可能回
   缺省 `None` 或 `0`；`is False` 会把它们当「满足」= 静默放开选项。
9. **节点值可以是任意对象（含 `None`）**：判据是「键在不在」，不是「值真不真」——
   键在且值为 `None` → 返回 `None`（不去回退）；键不在才回退 `start`。
10. **`text_from` 是「注入表」而不是「枚举」**：引擎按表查键，**不把表限制成固定项**；
    加第二种自动台词 = 内容侧加一行，引擎零改动。

**不变量（门禁逐条钉住）**
--------------------------
* **构造 O(1)、零遍历**：`Dialogue(...)` 只存引用 + 校验注入面，**不遍历树、不建索引**。
* **不缓存**：同一实例上的重复判定不保证同值（谓词可读外部状态），引擎不做 memo。
* **不可变**：引擎不写树 / 节点 / 选项；`Cursor` 是值对象，`moved_to` 返回新对象。
* **异常不吞**：谓词 / 文本源 / 展开回调抛出的异常**原样上抛**。
* **顺序即语义**：`need` 键序 = 短路序；`texts` 声明序 = 优先级；选项声明序 = 展示序；
  动态展开插回**该选项原来的位置**。
* **只有标准库 + 相对导入**：本模块不 import 任何内容侧模块（连谓词注册表也不 import，
  只用鸭子类型），可与 `conditions` 各自独立拷走。

**明确不做的事**
----------------
* **不做条件谓词实现**：条件名与判定全是内容侧取值；引擎只借注入对象的「查表」一件。
* **不做自动文本生成**：扫表、正则、校验那套全在内容侧注入的生成器里。
* **不做动作执行**：`action` 对引擎**完全不透明**，只原样带出；副作用落调用方。
* **不做渲染**：序号行、头衔、图标、提示语、结束项——引擎不产字符串给玩家。
* **不做输入解析**：裸数字消费、结束词、越界文案、指令拦截全在命令层。
* **不做会话存储**：存档键与落盘 JSON 文本是内容侧 schema，引擎不落盘（游标只是**值**）。
* **不做全树校验 / 审计**：悬空 `next`、`start` 缺失、未注册 need 键的构建期扫描是
  导出器的活；读路径不做全树扫描（构造零遍历）。
* **不做通用流程图抽象**：本批只有一种节点形状，形状未稳前不发明 `register_node_type` 式机制。
* **不重造 `conditions` 的求值**：它已有的 `evaluate` 是**单参**形状，而这里要的是
  **两参** `fn(ctx, value)`；引擎只借它的「登记 + 查表」，不去改它的签名（见下）。

**为什么不复用 `space.Space`**
------------------------------
`Space` 是「节点表 + 拓扑 → 邻接 / 深度 / 必经路径」：边由角色派生、无载荷、无谓词，
遍历靠几何。对话树是「**显式选项边** + 每条边带 need / action / 失败转」，遍历靠玩家选择。
把载荷与谓词塞进 `Space` = 污染空间形状（它就不再是纯拓扑了），所以不合并。

**为什么不复用 `run.Progress`**
-------------------------------
`Progress` 是**可变**的有序**线性**进度（`advance` = 声明序下一站）。对话是**图**，
跳转任意（可以回头、可以跳到任意 id），而且引擎侧连「进度」都不持有（游标的值在调用方）。
`goto` 有名字上的重合，但没有一处语义重合。

**为什么不复用 `run.Admission` / `command` 路由 / `text.TextTable`**
-------------------------------------------------------------------
`Admission` 是「有序规则 + 首拒即返 + 副作用延迟」的**准入**形状（判据是一条，不是每条边）；
命令路由是「输入 → 指令」；文案表是「键 → 模板 + 参数填充」。三者与「选项边带条件、
选中后跳转」的形状都不同，合并只会让各自多出一堆空转参数。
"""
from __future__ import annotations

from collections.abc import Mapping

__all__ = ["Dialogue", "Cursor", "END_KEY"]

#: 注入面的**形参名**（字段名，不是取值）：结束哨兵由它注入。
END_KEY = "end_marker"

# ── 契约词汇（结构字段名；引擎只按这些字段名读调用方的树）────────────────────
_F_START = "start"
_F_NODES = "nodes"
_F_TEXT = "text"
_F_TEXTS = "texts"
_F_TEXT_FROM = "text_from"
_F_OPTIONS = "options"
_F_NEED = "need"
_F_NEXT = "next"
_F_FAIL_NEXT = "fail_next"
_F_SIDE_MENU = "side_menu"


# ───────────────────────────────────────────────────────── 校验口（fail-closed）
def _need_str(value, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} 必须是字符串，收到 {type(value).__name__}")
    return value


def _need_callable(value, label: str):
    if not callable(value):
        raise TypeError(f"{label} 必须可调用，收到 {type(value).__name__}")
    return value


def _need_getter(value, label: str):
    """查表口口径：只要有 `get(key)`（鸭子类型，不 import 内容侧任何模块）。"""
    if not callable(getattr(value, "get", None)):
        raise TypeError(f"{label} 必须提供 get(key) 查表口，收到 {type(value).__name__}")
    return value


def _key_name(name, label: str) -> str:
    """存档字段名的口径：非空字符串（由调用方给；引擎不拼键、不猜键）。"""
    if not isinstance(name, str):
        raise TypeError(f"{label} 必须是字符串，收到 {type(name).__name__}")
    if not name:
        raise ValueError(f"{label} 不能为空（它是存档字段名，由调用方给）")
    return name


# ───────────────────────────────────────────────────────── 对话树（只读外壳）
class Dialogue:
    """一棵对话树的**只读外壳**：构造 O(1)（只存引用 + 校验注入面），不遍历树、不缓存判定。

    对象本身**不可变**：没有 setter，也没有会改内部状态的读法；`tree` 拿到的是
    调用方的**原对象**（不拷贝）。要换一棵树就 `of(tree)` 拿一个新外壳（同样 O(1)）。
    """

    __slots__ = ("_tree", "_end", "_conds", "_unknown", "_fallback", "_sources")

    def __init__(self, tree=None, *, end_marker: str, conditions, unknown,
                 fallback_text: str, text_sources: dict = None) -> None:
        # 注入面 fail-closed：不合法当场报错，**不给任何默认取值**（默认值 = 悄悄换语义）。
        _need_str(end_marker, END_KEY)
        _need_getter(conditions, "谓词查表口（get(key) -> callable | None）")
        _need_callable(unknown, "unknown（unknown(key, value) -> bool）")
        _need_str(fallback_text, "fallback_text")
        if text_sources is not None:
            _need_getter(text_sources, "text_sources（{取值: fn(node, ctx)}）")
        # 构造期**不读树**：只有存引用这一件事（零遍历 → 大树的构造成本与空树同量级）。
        self._tree = tree
        self._end = end_marker
        self._conds = conditions
        self._unknown = unknown
        self._fallback = fallback_text
        self._sources = text_sources

    # ---------------------------------------------------------------- 读
    @property
    def tree(self):
        """调用方的**原对象**（不拷贝、不归一、不补默认值）；没给树 → `None`。"""
        return self._tree

    @property
    def start(self):
        """树上的 `start` 字段取值（**不校验命中**；「start 缺不缺」由导出器审计）。"""
        return self._root().get(_F_START)

    def node(self, node_id) -> dict:
        """按 id 取节点；不在 `nodes` 里 → **回退 `start` 节点**；再没有 → `{}`。

        判据是「键在不在」而不是「值真不真」：键在、值是 `None` → 返回 `None`。
        """
        nodes = self._nodes()
        if node_id in nodes:
            return nodes[node_id]
        return nodes.get(self._root().get(_F_START), {})

    def has(self, node_id) -> bool:
        """`node_id` 在不在 `nodes` 里（**不触发回退**）。"""
        return node_id in self._nodes()

    def is_end(self, node_id) -> bool:
        """是不是注入的结束哨兵（其余一切都不是；`None` → False）。"""
        return node_id == self._end

    def of(self, tree) -> "Dialogue":
        """**同一注入面 + 另一棵树** → 新的外壳（O(1)：只换引用；不遍历、不拷贝树）。

        供「一份配置 + 多棵树」的调用方用；原外壳一个字节都不动。
        """
        return Dialogue(tree, end_marker=self._end, conditions=self._conds,
                        unknown=self._unknown, fallback_text=self._fallback,
                        text_sources=self._sources)

    # ---------------------------------------------------------------- 判定
    def satisfied(self, need, ctx) -> bool:
        """条件槽判定：`need` 为假值 → 不限（True）；否则逐键**与**、**按声明序短路**。

        * 未注册键 → 交给注入的 `unknown(key, value)`：真 → 放行（继续下一键），假 → False。
        * 谓词结果按**真值**判定（`None` / `0` / `""` / `[]` 都算不满足）。
        * 谓词抛错 / `unknown` 抛错 → **原样上抛**。
        * `need` 不是 mapping → `.items()` 抛 `AttributeError`（不吞、不降级）。
        """
        if not need:
            return True
        for key, value in need.items():
            fn = self._conds.get(key)
            if fn is None:
                if self._unknown(key, value):
                    continue
                return False
            if not fn(ctx, value):
                return False
        return True

    def options(self, node, ctx, *, expand=None) -> list:
        """当前可见的选项（**保持声明序**）；不满足 `need` 的隐藏。

        带 `side_menu`（`is not None`，空的 `{}` 也算）的选项走**动态展开**：先用 `need`
        过一遍，再调注入的 `expand(opt)` 拿子选项；展开结果**插回该选项原来的位置**，
        展开为空（或没注入 `expand`）→ 整项消失。普通选项返回**原对象**（`is` 相同）。
        """
        out = []
        for opt in node.get(_F_OPTIONS) or []:
            if opt.get(_F_SIDE_MENU) is not None:
                if not self.satisfied(opt.get(_F_NEED), ctx):
                    continue
                subs = expand(opt) if expand else []
                if subs:
                    out.extend(subs)
                continue
            if self.satisfied(opt.get(_F_NEED), ctx):
                out.append(opt)
        return out

    def text(self, node, ctx) -> str:
        """节点台词：`texts` 条件变体（**声明序第一个满足者**）→ `text_from` 自动源 →
        `text` → 注入的 `fallback_text`。

        * 变体缺 `text` 键 → `KeyError`（**不兜底**：变体是必填 schema）。
        * `text_from` 取值不在注入表内 → **不调用任何生成器**，落 `text`。
        * 生成器返回假值（`None` / `""`）→ 落 `text`；生成器抛错 → **原样上抛**。
        """
        for variant in node.get(_F_TEXTS) or []:
            if self.satisfied(variant.get(_F_NEED), ctx):
                return variant[_F_TEXT]
        src = node.get(_F_TEXT_FROM)
        if isinstance(src, str) and self._sources is not None:
            gen = self._sources.get(src)
            if gen is not None:
                auto = gen(node, ctx)
                if auto:
                    return auto
        return node.get(_F_TEXT, self._fallback)

    # ---------------------------------------------------------------- 路由
    def pick(self, node, index, ctx, *, expand=None) -> dict | None:
        """**1-based** 取可见选项：`index < 1` 或超出条数 → `None`（**不抛**）。

        取到的是 `options()` 里的那一个**原对象**（`is` 相同）。`0` 的「结束」语义
        在调用方，引擎不认 `0`。
        """
        opts = self.options(node, ctx, expand=expand)
        if index < 1 or index > len(opts):
            return None
        return opts[index - 1]

    def next_of(self, option, *, failed=False) -> str:
        """选项路由：`option["next"]`，缺失 → 注入的结束哨兵。

        `failed=True` 且 `fail_next` **存在** → 用它（**哪怕它是假值也不回落**）；
        缺失 → 回落上面那条结果。动作路由的 token（成功/失败/结束）引擎**不认识**，
        由调用方把动作结果翻成一个 bool 传进来。
        """
        nxt = option.get(_F_NEXT, self._end)
        if failed:
            return option.get(_F_FAIL_NEXT, nxt)
        return nxt

    # ---------------------------------------------------------------- 内部
    def _root(self):
        """读口用的树根：没给树 → 空 mapping（其余原样；非 mapping 的树会在这里自然报错）。"""
        return {} if self._tree is None else self._tree

    def _nodes(self) -> dict:
        return self._root().get(_F_NODES, {})

    def __repr__(self) -> str:
        return f"Dialogue(nodes={len(self._nodes())}, {END_KEY}={self._end!r})"


# ───────────────────────────────────────────────────────── 会话游标（值对象）
class Cursor:
    """会话游标**值**：「跟谁 + 在哪」两个**不透明字符串**。

    * **不落盘、不缓存**：存储键怎么拼、JSON 怎么写全在调用方（存档 schema 不许动）。
    * **不持有上下文**：判定用的上下文每步**现取**，绝不塞进游标 —— 塞进去就等于把一份
      过期世界冻进存档，谓词会读到陈旧数据（与 `periodic` 同纪律：值进引擎、存储不进）。
    * **不可变**：`moved_to` 返回**新**对象，原对象不动。
    """

    __slots__ = ("_subject", "_node")

    def __init__(self, subject: str = "", node: str = "") -> None:
        self._subject = _need_str(subject, "subject")
        self._node = _need_str(node, "node")

    @property
    def subject(self) -> str:
        """跟谁（内容侧可能把它叫别的名字 —— 那只是**键名**的区别）。"""
        return self._subject

    @property
    def node(self) -> str:
        """在哪个节点。"""
        return self._node

    def state(self, *, subject_key: str, node_key: str) -> dict:
        """落盘用的**纯 mapping**（键名由调用方给；`json.dumps` 可直接序列化）。"""
        _key_name(subject_key, "subject_key")
        _key_name(node_key, "node_key")
        return {subject_key: self._subject, node_key: self._node}

    @classmethod
    def of(cls, raw, *, subject_key: str, node_key: str) -> "Cursor | None":
        """从存档映射还原游标；**还原不出来 → `None`（不抛）**。

        容忍口径（与存档读口的容错同款）：`None` / 非 mapping / 两个键缺任一 /
        值不是字符串 / 空串 → `None`。⚠️ 「空 mapping」与「坏值」在这里**都是 `None`**；
        两者的区别（要不要顺手清残留键）**留在调用方**，引擎不做清理。
        """
        _key_name(subject_key, "subject_key")
        _key_name(node_key, "node_key")
        if not isinstance(raw, Mapping):
            return None
        subject = raw.get(subject_key)
        node = raw.get(node_key)
        if not isinstance(subject, str) or not isinstance(node, str):
            return None
        if not subject or not node:
            return None
        return cls(subject, node)

    def moved_to(self, node_id) -> "Cursor":
        """同一主体、换一个节点 → **新**游标（原对象不动）。"""
        return Cursor(self._subject, node_id)

    def same_as(self, other) -> bool:
        """两个游标是不是「同一个人 + 同一个节点」；不是游标 → `False`。"""
        if not isinstance(other, Cursor):
            return False
        return self._subject == other._subject and self._node == other._node

    def __repr__(self) -> str:
        return f"Cursor(subject={self._subject!r}, node={self._node!r})"
