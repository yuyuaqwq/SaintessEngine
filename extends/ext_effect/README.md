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

| 半边 | 注入 | 用途 | 缺了会怎样 |
|---|---|---|---|
| POI | `ctx.host` | 写库五动词（更新玩家 / 发物品 / 事件状态读写的两向 / 对话标记） | `AttributeError`（fail-loud） |
| POI | `ctx.dom` | 材料表 · 两个文案池 · 图纸与装备生成器 · 副本名单视图 | 同上 |
| POI | `ctx.text` / `ctx.static` | 文案渲染（句子在数据包的文案表里，本包一个字都不写） | 同上（访问即炸） |
| 药水 | `potion_effects.bind(text=…, static=…, items=…, rules=…, neg_keys=…)` | 文案渲染 + 三张域表（`items` / `effect_rules` / `purify_neg_keys`） | **取用即报错**（未绑定代理 / `_resolve()` 校验） |

药水侧为什么是**模块级**而不是 ctx：handler 签名是 `(battle, player, value)`（没有 ctx），
73 个渲染点分散在 36 个 handler 里 —— 模块级句柄才能让那 73 个调用点一字不改
（数据包侧同款先例 = `content/obs.py::bind(log=…)`）。装配点唯一：
数据包 `content/apply.py::install_engine()` → `content/effects/__init__.py::bind_effects()`。

## 从哪来 / 边界

2026-09-24（B7a + B7b）：数据包 `content/effects/` 两个半边先后搬入本包 ——

* **B7a** `poi_effects.py`（520 行）：搬前先把它 3 处包内耦合换成注入面
  （`from .. import catalog_items / catalog_b143 / texts` → `ctx.dom.MATERIALS` /
  `ctx.dom.CAMPFIRE_FOOD_POOL` / `ctx.dom.HERB_POOL` / `ctx.text` / `ctx.static`），
  43 个取件点逐点同名等价替换（函数体逻辑一字未动）。
* **B7b** `potion_effects.py`（865 行）：同样先换注入面（`_T` 代理 + `bind()` 的三张表 +
  `DEFAULTS` 就地刷新），73 个渲染点与 36 个 handler 零改动。

消费端 = 数据包 `content/combat_cmds.py::_handle_poi`（POI）与
`content/mech/item_use.py` / `content/effects/__init__.py`（药水）。
