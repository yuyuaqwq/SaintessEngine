# -*- coding: utf-8 -*-
"""空间（Space）—— 节点表 + 拓扑 → 邻接 / 深度 / 出入口 / 必经路径 / 结构审计。

**为什么有它**：地图类数据里真正通用的东西只有四件 —— 谁和谁相邻、谁离入口多远、
从哪进出、走到哪必须先经过哪。这四件与「城镇 / 野外 / 副本」这类名词无关：
把名词换成角色名，逻辑照旧成立 → 属形状，不该写在某个游戏的代码里各写一份。

**用法**::

    from saintess_engine.space import Space

    sp = Space(
        nodes=[{"id": "a", "role": "hub"}, {"id": "b"}, {"id": "c", "role": "exit"}],
        topology="star",
        roles={"hub": "hub", "through": "through", "exit": "exit"},
    )
    sp.links("a")        # 邻接
    sp.depth("c")        # 深度
    sp.gate()            # 跨图落点 / 出图点
    sp.route("a", "c")   # 必经路径（含两端）
    sp.audit()           # {ok, dangling, asymmetric, isolated, unreachable, no_gate}
    sp.to_view()         # 纯 JSON 视图（编辑器画图 / 序列化）

**两种邻接来源**（互斥，显式优先）:

* **派生**（`links=None`）：由 `topology` 指定的形状函数算出（见 `topology.py`）
* **显式**（`links={id: [id…]}`）：内容侧直接给连通表，拓扑不参与（`topology="mesh"` 或省略）

**深度两口径（故意不同，勿「统一」）**:

* 显式连通表 → 从首节点 **BFS**（网状图没有天然顺序）
* 派生形状   → **声明序**（链状/星形里「数据顺序」本身就是作者给的由近及远）

**零知识**：`hub` / `through` / `exit` 只是**角色名**，角色**取值**由内容侧给
（本引擎不认任何具体取值，也不 import 宿主）。
"""
from __future__ import annotations

from .topology import MESH, TOPOLOGIES, get_topology, topology_names


class Space:
    """节点表 + 拓扑。构造后不可变（无 setter），派生结果构造期算好。"""

    def __init__(self, nodes, topology: str | None = None, *, roles=None, role_key: str = "role",
                 id_key: str = "id", label_key: str | None = None, links=None, root: str | None = None,
                 gate: str | None = None):
        self._raw = tuple(dict(n) for n in (nodes or ()))
        self._id_key = id_key
        self._role_key = role_key
        self._label_key = label_key
        self._roles = dict(roles or {})
        # 规范化视图：[{"id": …, "role": …}]，保持声明序
        self._nodes = tuple(
            {"id": n.get(id_key), "role": n.get(role_key)} for n in self._raw
        )
        self._ids = tuple(n["id"] for n in self._nodes)
        self._role_of = {n["id"]: n["role"] for n in self._nodes}
        self._explicit = links is not None
        if self._explicit:
            self._links_given = {k: list(v or ()) for k, v in dict(links).items()}
        else:
            self._links_given = None
        self._root = root if root is not None else (self._ids[0] if self._ids else "")
        # 拓扑名：显式连通表 = mesh（不派生）；否则内容侧给的形状名，未给 = 链状
        if self._explicit and topology is not None and topology != MESH:
            raise ValueError(
                f"给了显式连通表（links=…）就不能再给派生形状名 {topology!r} —— "
                f"两者互斥（要标注来源请用 topology={MESH!r}）"
            )
        self._topology = topology if topology is not None else (MESH if self._explicit else "chain")
        self._gate_override = gate
        self._links_map, self._gate_hint = self._compute()
        self._compute_depth()

    # ─────────────────────────────────────────────── 构造期派生
    def _compute(self):
        if self._explicit:
            return dict(self._links_given), self._root
        if self._topology == MESH:
            raise ValueError("mesh 是「显式连通表」的保留名 —— 请给 links={id: [id…]}")
        try:
            fn = get_topology(self._topology)
        except KeyError:
            raise ValueError(
                f"未知拓扑：{self._topology!r}；已注册：{list(topology_names())}（或显式给 links）"
            ) from None
        out = fn(self._nodes, roles=self._roles, role_key=self._role_key, root=self._root)
        return dict(out.get("links") or {}), out.get("gate", self._root)

    def _compute_depth(self):
        """落两种口径的深度表（构造期算一次；见模块文档「深度两口径」）。"""
        if not self._explicit:
            # 声明序：未知 id → 0（与原内容侧实现逐字一致）
            self._depth_index = {nid: i for i, nid in enumerate(self._ids)}
            self._depth_bfs = {}
            self._depth_fallback = 0
            return
        dist = {}
        if self._root:
            dist[self._root] = 0
            queue = [self._root]
            while queue:
                cur = queue.pop(0)
                for nxt in self._links_map.get(cur, ()):
                    if nxt not in dist:
                        dist[nxt] = dist[cur] + 1
                        queue.append(nxt)
        self._depth_index = {}
        self._depth_bfs = dist
        self._depth_fallback = len(self._ids)

    # ─────────────────────────────────────────────── 只读视图
    @property
    def nodes(self) -> tuple:
        """原始节点 dict（浅拷贝）的元组，保持声明序。"""
        return self._raw

    @property
    def ids(self) -> tuple:
        return self._ids

    @property
    def topology(self) -> str:
        return self._topology

    @property
    def explicit(self) -> bool:
        """邻接是否来自显式连通表（True）还是拓扑派生（False）。"""
        return self._explicit

    @property
    def roles(self) -> dict:
        return dict(self._roles)

    @property
    def root(self) -> str:
        return self._root

    def node(self, node_id) -> dict | None:
        """原始节点 dict 的浅拷贝；未知 id → None。"""
        for n, raw in zip(self._nodes, self._raw):
            if n["id"] == node_id:
                return dict(raw)
        return None

    def role_of(self, node_id):
        return self._role_of.get(node_id)

    def label_of(self, node_id, label_key: str | None = None):
        """显示名：label_key（构造参数或此处指定）读原始节点的字段；无则退回 id。"""
        key = label_key or self._label_key
        raw = self.node(node_id)
        if raw is None:
            return node_id
        if key and raw.get(key):
            return raw[key]
        return node_id

    # ─────────────────────────────────────────────── 派生查询
    def links(self, node_id) -> list:
        """邻接（可直达的节点 id 列表）。未知 id → []。"""
        return list(self._links_map.get(node_id, ()))

    def adjacency(self) -> dict:
        """全图邻接（含声明了却零邻接的节点 → 空列表）。"""
        return {nid: list(self._links_map.get(nid, ())) for nid in self._ids}

    def depth(self, node_id) -> int:
        """从入口算的深度。口径见模块文档:

        * 派生态 → **声明序**（与 `root` 无关：链状/星形里入口天然是首节点，顺序即作者的由近及远）
        * 显式连通表 → 从 `root` **BFS**（不可达 → 节点数）
        """
        if not self._explicit:
            return self._depth_index.get(node_id, 0)
        return self._depth_bfs.get(node_id, self._depth_fallback)

    def gate(self) -> str:
        """跨图落点 / 出图点（**同一个语义**）。

        解析顺序：显式 `gate=` 参数 > 拓扑声明 > 角色规则
        （首节点是枢纽角色且有出口角色节点 → 那个出口节点；否则首节点）。
        无节点 → `""`。
        """
        if self._gate_override is not None:
            return self._gate_override
        if not self._nodes:
            return ""
        if not self._explicit:
            return self._gate_hint
        hub_role = self._roles.get("hub")
        if hub_role is not None and self._role_of.get(self._root) == hub_role:
            val = self._roles.get("exit")
            if val is not None:
                for n in self._nodes:
                    if n["role"] == val:
                        return n["id"]
        return self._root

    # 语义别名：历史内容侧把它叫 entry（落点）也叫 exit（出图点），引擎只留一个名字。
    def entry(self) -> str:
        return self.gate()

    def route(self, src, dst) -> list:
        """必经路径（含两端）。同点 → `[src]`；任一端未知或不可达 → `[]`。

        BFS 最短路；多条同长路径取**邻接声明序**里靠前的那条（可复现，不随机）。
        """
        if src not in self._role_of or dst not in self._role_of:
            return []
        if src == dst:
            return [src]
        prev = {src: None}
        queue = [src]
        while queue:
            cur = queue.pop(0)
            if cur == dst:
                break
            for nxt in self._links_map.get(cur, ()):
                if nxt in prev or nxt not in self._role_of:
                    continue
                prev[nxt] = cur
                queue.append(nxt)
        if dst not in prev:
            return []
        out = []
        cur = dst
        while cur is not None:
            out.append(cur)
            cur = prev[cur]
        out.reverse()
        return out

    def route_names(self, src, dst, label_key: str | None = None) -> list:
        """必经路径的显示名列表（等价于 route() 后逐个 label_of）。"""
        return [self.label_of(i, label_key) for i in self.route(src, dst)]

    # ─────────────────────────────────────────────── 结构审计
    def audit(self) -> dict:
        """结构自检 —— **只报不改**（处置由内容侧决定）。"""
        known = set(self._ids)
        dangling, asymmetric, isolated = [], [], []
        back = {nid: set(v) for nid, v in self._links_map.items()}
        for nid in self._ids:
            nb = self._links_map.get(nid, ())
            if not nb and not any(nid in v for v in back.values()):
                isolated.append(nid)
            for tgt in nb:
                if tgt not in known:
                    dangling.append([nid, tgt])
                elif nid not in back.get(tgt, ()):
                    asymmetric.append([nid, tgt])
        # 可达性：从首节点 BFS（悬空边按「不存在」处理）
        seen = set()
        if self._root:
            seen.add(self._root)
            queue = [self._root]
            while queue:
                cur = queue.pop(0)
                for nxt in self._links_map.get(cur, ()):
                    if nxt in known and nxt not in seen:
                        seen.add(nxt)
                        queue.append(nxt)
        unreachable = [n for n in self._ids if n not in seen]
        exit_role = self._roles.get("exit")
        hub_role = self._roles.get("hub")
        no_gate = bool(
            exit_role is not None and hub_role is not None
            and self._role_of.get(self._root) == hub_role
            and not any(n["role"] == exit_role for n in self._nodes)
        )
        ok = not (dangling or asymmetric or isolated or unreachable or no_gate)
        return {"ok": ok, "dangling": dangling, "asymmetric": asymmetric, "isolated": isolated,
                "unreachable": unreachable, "no_gate": no_gate}

    # ─────────────────────────────────────────────── 视图
    def edges(self) -> list:
        """有向边列表 `[[from, to], …]`（按声明序；不对称的边也在里面，由 audit 报）。"""
        out = []
        for nid in self._ids:
            for tgt in self._links_map.get(nid, ()):
                out.append([nid, tgt])
        return out

    def to_view(self, label_key: str | None = None) -> dict:
        """纯 JSON 视图（画图 / 序列化 / 前端直接用）:
        `{topology, explicit, root, gate, nodes:[{id, role, label, depth}], edges, audit}`。
        """
        return {
            "topology": self._topology,
            "explicit": self._explicit,
            "root": self._root,
            "gate": self.gate(),
            "nodes": [
                {"id": n["id"], "role": n["role"], "depth": self.depth(n["id"]),
                 "label": self.label_of(n["id"], label_key)}
                for n in self._nodes
            ],
            "edges": self.edges(),
            "audit": self.audit(),
        }

    def __len__(self):
        return len(self._ids)

    def __repr__(self):
        return f"<Space {self._topology} nodes={len(self._ids)} explicit={self._explicit}>"
