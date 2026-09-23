# ext_world —— 空间与运行形状（扩展包）

游戏级**能力**包（`kind: extension`）：把两类「与题材无关的空间 / 进行形状」装进来 ——
**空间形状**（谁和谁相邻 · 离入口多远 · 从哪进出 · 必经路径 · 结构审计）与
**运行形状**（一次运行的三件事：谁能进 · 谁在里面 · 打到哪了）。
任何数据包 `depends` 它就能用；不 depends 就是一个没有地图与副本框架的框架
（纯经营 / 纯数值 / 纯对话都照跑）。

## 装它

```python
from saintess_engine.package import load_stack
stack = load_stack("path/to/game", exts=["path/to/extends"])   # 数据包 depends: ["ext_world"]
```

## 用它

```python
from ext_world.space import Space, register_topology
from ext_world.run import Admission, Rule, Progress, Roster
```

`ext_world` 这个 import 名 = 本包**目录名**（扩展包命名空间约定）；包内模块一律相对导入，
因此同一进程里装多个扩展包互不冲突。

## 内容

| 模块 | 提供 |
|---|---|
| `space/__init__.py` | 包门面 + 口径说明（`__all__`） |
| `space/graph.py` | `Space`：节点表 + 拓扑 → 邻接 / 深度 / 出入口 / 必经路径 / 结构审计 / 纯 JSON 视图 |
| `space/topology.py` | 拓扑注册表（`MESH` / `chain` / `star`）+ `register_topology`（第三方自定义形状是扩展点） |
| `run/__init__.py` | 包门面 + 口径说明（`__all__`） |
| `run/admission.py` | `Admission` / `Rule` / `Verdict` / `PASS` / `DENY` / `SKIP`：准入链（首拒即返 · 副作用延后 · `all`/`any` 两种语义） |
| `run/progress.py` | `Progress`：有序节点 + 每节点具名剩余池 + 资源预算 + 当前位置（`to_dict` / `from_dict`） |
| `run/roster.py` | `Roster`：有序成员 + 队长 + 存活表 + 过滤 / 排序（`to_dict` / `from_dict`） |

## 依赖方向

```text
本包 → 标准库（`__future__` / `typing`）
本包 ✗→ saintess_engine（零引擎依赖：两套形状不读引擎任何配置面）
本包 ✗→ 任何数据包（角色名 / 节点 key / 池名 / 顺序依据全是内容侧取值）
```

## 边界

* **零知识**：引擎不认「城镇 / 野外 / 副本 / 层 / 房间 / 队伍 / 队长」；
  `hub` / `through` / `exit` 只是**角色名**，取值由内容侧给。
* **不进注册表**：`install_engine()` 是空实现 —— 拓扑注册表由**内容侧**按需
  `register_topology()` 填，引擎不预设形状集合。
* **不声明 `provides`**：本包只提供形状（类），没有「宿主按 key 取一个实现」那种能力
  （对比 `ext_combat` 的 `provides.battle`）。
* 形状判据见 `docs/engine-wiki/reference/space.md` 与 `docs/engine-wiki/reference/run.md`。

## 测试

随引擎仓统一门禁跑（`python tests/run_all.py`）—— 本包自身不带 `tests/`。
