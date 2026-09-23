# ext_dialogue —— 对话树与会话游标（扩展包）

游戏级**能力**包（`kind: extension`）：提供「对话树形状 + 会话游标值对象」这套形状，
任何数据包都能 `depends` 它来用。它不提供「身份」（哪句台词 / 哪个 NPC / 什么条件 / 什么动作
全在数据包）。

## 装它

```python
from saintess_engine.package import load_stack
stack = load_stack("path/to/game", exts=["path/to/extends"])   # 数据包 depends: ["ext_dialogue"]
```

## 用它

```python
from ext_dialogue.dialogue import END_KEY, Cursor, Dialogue

cfg = Dialogue(end_marker=<结束哨兵>, fallback_text=<兜底文案>,
               conditions=<有 get(key) 的查表口>, unknown=<未注册键策略>,
               text_sources={<取值>: <生成器 fn(node, ctx)>})   # 前四个必填，text_sources 可选
dlg = cfg.of(tree)                    # O(1)：只换树引用
node = dlg.node(<节点 id>)            # 未知 id 静默回退 start
opts = dlg.options(node, ctx)         # 声明序；side_menu 项就地展开
line = dlg.text(node, ctx)            # texts 变体 → text_from → text → fallback_text
nxt = dlg.next_of(opts[0], failed=False)   # next / fail_next / end_marker

cur = Cursor.of(raw, subject_key=..., node_key=...)   # 存档映射 → 游标（坏值 → None）
raw2 = cur.moved_to(<节点 id>).state(subject_key=..., node_key=...)
```

`ext_dialogue` 这个 import 名 = 本包**目录名**（扩展包的命名空间约定）；
包内模块一律走这个命名空间，因此同一进程里装多个扩展包互不冲突。

## 内容

| 模块 | 提供 |
|---|---|
| `dialogue/__init__.py` | 包门面 + 口径说明（`__all__`）：`Dialogue`（树只读外壳：`node` / `has` / `is_end` / `of` / `satisfied` / `options` / `text` / `pick` / `next_of`）· `Cursor`（会话游标值：`of` / `state` / `moved_to` / `same_as`）· `END_KEY`（注入面形参名 `end_marker`） |

## 边界

* **零引擎依赖**：只 import 标准库（`collections.abc.Mapping`），不 import 引擎任何模块。
* **零游戏取值**：结束哨兵 / 兜底文案 / 条件名 / 自动文本源 / 动作载荷全靠注入面 —— 引擎源码里没有任何取值字面量。
* **不进注册表**：`install_engine()` 是空实现 —— 形状库按需取用，不需要全局装配。
* **不落盘、不渲染、不解析输入、不执行动作**：会话存储键名与 JSON 文本、玩家可见文案、
  裸数字消费、动作副作用全在调用方；游标只是**值**。
* 需要「跟谁说什么 / 什么条件 / 选了什么干什么」的规则？那属于数据包（内容），不属于这一层。
