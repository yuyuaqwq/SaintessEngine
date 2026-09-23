# ext_effect —— 场景交互效果层（POI）（扩展包）

游戏级**能力**包（`kind: extension`）：把「场景交互点（POI）效果」这套形状
（注册表 + 上下文 + 执行器）提供给任何数据包用。它不提供「身份」（材料名 / 池子里有什么 /
句子怎么写都属数据包）—— 那三样一律由调用方**注入**。

## 装它

```python
from saintess_engine.package import load_stack
stack = load_stack("path/to/game", exts=["path/to/extends"])   # 数据包 depends: ["ext_effect"]
```

## 用它

```python
from ext_effect.effects import POI_EFFECTS, PoiContext, execute_poi

ctx = PoiContext(group_id, uid, player, cur_map, poi_id, poi,
                 host=<写库对象>, dom=<内容域访问对象>,
                 text=<文案渲染(带槽位)>, static=<文案渲染(无槽位)>)
text = execute_poi("world:campfire", ctx)      # 未注册的键 → None（调用方显式告警）
```

## 注入面（本包**只**读这三组）

| 注入 | 用途 | 缺了会怎样 |
|---|---|---|
| `ctx.host` | 写库五动词（更新玩家 / 发物品 / 事件状态读写的两向 / 对话标记） | `AttributeError`（fail-loud） |
| `ctx.dom` | 材料表 · 两个文案池 · 图纸与装备生成器 · 副本名单视图 | 同上 |
| `ctx.text` / `ctx.static` | 文案渲染（句子在数据包的文案表里，本包一个字都不写） | 同上 |

## 从哪来 / 边界

2026-09-24（B7a）：`content/effects/poi_effects.py`（520 行）搬入本包。搬之前先把它的
**3 处包内耦合**换成注入面（`from .. import catalog_items / catalog_b143 / texts`
→ `ctx.dom.MATERIALS` / `ctx.dom.CAMPFIRE_FOOD_POOL` / `ctx.dom.HERB_POOL` /
`ctx.text` / `ctx.static`），共 43 个取件点逐点同名等价替换（函数体逻辑一字未动）。

* **药水效果半边**（`potion_effects.py`，811 行）**仍在数据包内**：它的 handler 签名没有 ctx，
  要先加模块级注入口才能搬（B7b）。
* 消费端 = 数据包 `content/combat_cmds.py::_handle_poi`（它构造 `PoiContext`、
  给 `dom` 替身 `_PoiDom` 与 `text`/`static`）。
