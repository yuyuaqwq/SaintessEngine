# 空间形状（节点表 + 拓扑 → 派生）

> **归属**：本能力**不在引擎里**（2026-09-23 起）—— 它在扩展包 `extends/ext_world/`（`space/`）。
> 数据包要用它：`game.json` 里写 `"depends": ["ext_world"]`；地图数据对应它的域 `maps`。
> 引擎侧只剩通用件，见 `../architecture/boundaries.md`；下文裸文件名与行号都相对 `extends/ext_world/space/`。
>
> 模块：`ext_world.space` —— `Space`（邻接 / 深度 / 出入口 / 必经路径 / 结构审计 / 视图）
> + 拓扑注册表（`chain` / `star` + 第三方可注册）。一句话：**数据给节点与角色，本形状给几何**。

## 为什么有它

参考实现（游戏仓 `dragonfall`）里，「谁和谁相邻 / 谁离入口多远 / 从哪进出 / 到哪必须先经过谁」
**同一份形状写了四遍**：

| # | 位置 | 内容 |
|---|---|---|
| 1 | `game/core/maps.py` `subarea_links` | 邻接：显式连通表 → 否则「城镇星形 / 野外线性」 |
| 2 | `game/core/maps.py` `subarea_depth` | 深度：显式连通表 BFS / 否则声明序 |
| 3 | `game/core/maps.py` `map_exit_subarea` + `map_entry_subarea` | **两份逐字相同的实现** |
| 4 | `game/services/travel.py` · `game/commands/world.py` | 又各抄一遍「星形必经链首」判断（文本提示用） |

四份都**不含任何游戏名词**：把「城镇 / 城镇街道 / 城镇出口」换成任意角色名，逻辑照样成立 ——
按判据这就是形状，于是搬进扩展包 `ext_world`；内容侧只留「哪个取值算哪个角色」的适配。

## 两个邻接来源（互斥，显式优先）

```python
from ext_world.space import Space, register_topology

sp = Space(
    nodes=[{"id": "a", "role": "hub"}, {"id": "b"}, {"id": "c", "role": "exit"}],
    topology="star",                                    # 派生形状名
    roles={"hub": "hub", "through": "through", "exit": "exit"},
    label_key="name",                                   # 可选：视图带出显示名
)

sp.links("a")        # 邻接（可直达 id 列表）
sp.depth("c")        # 深度
sp.gate()            # 跨图落点 / 出图点（★ 内容侧历史上叫 entry 也叫 exit，语义同一个）
sp.route("a", "c")   # 必经路径（含两端）；不可达 → []
sp.audit()           # 结构自检（只报不改）
sp.to_view()         # 纯 JSON 视图（编辑器画图 / 序列化）
```

| 来源 | 触发 | 邻接来自 | 深度口径 |
|---|---|---|---|
| **派生** | 给 `topology="chain"/"star"/自定义` | 拓扑函数算出 | **声明序**（数据顺序） |
| **显式** | 给 `links={id: [id…]}`（`topology` 缺省 = `mesh`） | 内容侧连通表 | 从 `root` **BFS** |

> 两者**互斥**：给了 `links` 再给派生形状名 → `ValueError`（互斥状态会让人误以为派生生效）。
> `mesh` 是**保留名**（= 不派生），不在注册表里，也不能被注册占用。

## 内置形状

### `chain` —— 链状 / 线性（`extends/ext_world/space/topology.py:79`）

按声明序相邻：`i ↔ i+1`；**出入口 = 首节点**。

### `star` —— 星形（`extends/ext_world/space/topology.py:93`）

```ini
枢纽(hub)     → 全部非 exit 节点；★ 若无 through 节点，枢纽**额外**直连 exit
通道(through) → 全部 exit 节点 + 枢纽
出口(exit)    → 全部 through 节点；若无 through，则直连枢纽
其余角色      → 枢纽
出入口        → 第一个 exit 角色节点；无 exit 则首节点
```

★ 那两条「无 through 时直连」是**防断链**分支，不是洁癖：真实现场有两个城镇没定义通道层，
不补边就是「枢纽 → 出口」不可达、提示指向自己、玩家出不了城。门禁对这两条**各有断言**
（删掉就红，见 `extends/ext_world/tests/test_space.py`）。

### `mesh` —— 显式连通表

内容侧直接给全图邻接（副本房间连通表就是这个形状）。**「无出口」是内容侧的事**，
本形状不判断 —— 副本本来就该是死路。

## 深度：两口径，故意不统一

| 来源 | 口径 | 未知 id |
|---|---|---|
| 派生（链 / 星） | **声明序**（作者的由近及远） | `0` |
| 显式连通表 | 从 `root` **BFS** | 节点数 |

网状图**没有**天然顺序，链/星形的顺序**本身就是数据**。同一张星形图两种口径会给出不同深度
（`gate` 深度 4 vs 2）—— 门禁专门断言「它们确实不同」，防后人为了「整齐」统一掉。

## 出图点：两口径，同样故意不统一

`gate()` 是**同一个语义**（找跨图落点）走两条实现，**与深度同源**的有意取舍：

| 来源 | 口径 |
|---|---|
| 派生（链 / 星） | 拓扑形状函数给的 `_gate_hint`（星形=出口角色节点；链状=首节点） |
| 显式连通表 | **角色规则**（首节点是枢纽角色且有出口角色节点 → 那个出口节点；否则首节点） |

**分歧条件只有一个**：显式图且「`root` 不是枢纽」。此时派生按形状走（仍给出口），
显式按角色规则回落（给 `root`）。`root` 即枢纽时两口径**必须同值** —— 门禁两侧各钉一条
（一条断言「它们确实不同」、一条断言「该同值时确实同值」），防后人为了「整齐」统一掉。

真数据侧：orlandia 121 张图该分歧条件 **0 次命中**（97 张走显式 `links`，要么显式给
`gate=`，要么 `root` 恰是枢纽）⇒ 这是**潜伏**分歧，不是正在发生的错。

## 必经路径：`route(src, dst)`

BFS 最短路，**含两端**；`route("a", "a") == ["a"]`；任一端未知或不可达 → `[]`。
多条同长路径取**邻接声明序**里靠前的那条（可复现，不随机）。
内容侧用它做「不能直达 → 提示必须先经过 X、Y」（`route_names()` 直接给显示名列表）。

## 结构审计：`audit()`（只报不改）

| 字段 | 抓什么 |
|---|---|
| `dangling` | 连到**不存在**的 id |
| `asymmetric` | `a→b` 但 `b↛a` |
| `isolated` | 无进无出 |
| `unreachable` | 从首节点不可达 |
| `no_gate` | 枢纽型图却没有出口角色节点 |

本形状**不替内容侧补边** —— 补边会掩盖数据错误；处置（修数据 / 接受现状）是内容决策。
`ok` = 五项全空。

## 第三方拓扑（可拔插）

```python
from ext_world.space import register_topology

def _ring(nodes, *, roles, role_key, root):
    ids = [n["id"] for n in nodes]
    return {"links": {i: [ids[(k - 1) % len(ids)], ids[(k + 1) % len(ids)]]
                      for k, i in enumerate(ids)},
            "gate": root}

register_topology("ring", _ring, doc="环形：首尾相连")
```

* 重名默认**报错**（防静默覆盖）；确实要覆盖写 `replace=True`
* 返回 `{"links": …, "gate": …}`；`links` **不必对称**（不对称由 `audit()` 报）
* 本形状不预设形状集合 —— 环形 / 网格 / 迷宫都是内容侧的事

## 零知识

`hub` / `through` / `exit` 只是**角色名**；角色**取值**由内容侧给（参考实现给的是中文取值）。
门禁里有一条**静态断言**：`extends/ext_world/space/` 的代码常量里不得出现任何角色取值
（只准出现角色名）—— 换一套取值，结构必须逐格一致（`extends/ext_world/tests/test_space.py` 门禁第 8 组）。

本形状不 import 宿主、不认地图、不认玩家、不认数据库。

## API

| 形状 | 位置 | 说明 |
|---|---|---|
| `Space(nodes, topology=None, *, roles, role_key, id_key, label_key, links, root, gate)` | `space/graph.py:65` | 构造即派生（不可变，无 setter） |
| `links(id)` | `space/graph.py:221` | 邻接；未知 id → `[]` |
| `adjacency()` | `space/graph.py:225` | 全图邻接（含零邻接节点 → 空列表） |
| `depth(id)` | `space/graph.py:229` | 深度（两口径见上） |
| `gate()` / `entry()` | `space/graph.py:239` / `:259` | 跨图落点 / 出图点（同义，`entry` 是内容侧旧名的别名） |
| `route(src, dst)` / `route_names(...)` | `space/graph.py:266` / `:296` | 必经路径 / 其显示名 |
| `audit()` | `space/graph.py:305` | 结构自检 |
| `edges()` / `to_view(label_key=None)` | `space/graph.py:343` / `:343` | 有向边 / 纯 JSON 视图 |
| `node(id)` / `role_of(id)` / `label_of(id)` | `space/graph.py:200` / `:199` / `:202` | 原始节点 / 角色 / 显示名 |
| `register_topology(name, fn, *, doc, replace)` | `space/topology.py:34` | 注册自定义形状 |
| `topology_names()` / `get_topology(name)` | `space/topology.py:51` / `:56` | 已注册形状名 / 取函数 |
| `MESH` | `space/topology.py:28` | 保留名（显式连通表） |

门禁：`extends/ext_world/tests/test_space.py`（74 断言：拓扑规则 / 两条防断链 / 深度两口径 / `route` / `audit` /
注册表 / 零知识静态扫描 / 视图）。

## 有意不做

* 不判断「这张图该不该有出口」「副本该不该是死路」—— 内容决策
* 不做跨图连边（图与图之间是另一层；参考实现放在内容侧 `MAP_CONNECTIONS`）
* 不替内容侧补对称边、不自动修数据
* 不做坐标 / 距离 / 寻路代价 —— 只有**连通**与**跳数**，几何是第三方的事
