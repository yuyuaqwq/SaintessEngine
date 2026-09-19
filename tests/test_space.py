#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""space 空间形状门禁：拓扑派生 / 深度两口径 / 出入口 / 必经路径 / 结构审计 / 注册表。

跑法：python tests/test_space.py
退出码：0 = 全绿；1 = 有失败。

三条口径要点（与 `docs/engine-wiki/reference/space.md` 对应）：
  ① **零知识**：角色取值由内容侧给，引擎不认任何具体取值 —— 换一套取值，结构必须一字不差。
  ② **两条防断链分支**是真实数据踩出来的，必须各有断言（删掉就红）。
  ③ **深度两口径**（派生=声明序 / 显式=BFS）故意不同 —— 断言它们**确实**不同，防后人「统一」掉。
"""
import ast
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine.space import MESH, Space, register_topology, topology_names   # noqa: E402
import saintess_engine.space.topology as T                                          # noqa: E402

passed = failed = 0

# 一套**非 ASCII** 角色取值（内容侧那样的取值）；引擎不认它们的含义。
R = {"hub": "中心", "through": "通道", "exit": "口"}
HUB, SPOKE, THROUGH, EXIT = "中心", "铺子", "通道", "口"


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


def mk(nodes, **kw):
    return Space(nodes=nodes, roles=R, **kw)


# ---------------------------------------------------------------- 1 空表 / 边界
def t1_empty():
    print("\n[1] 空表与边界")
    sp = Space(nodes=[], roles=R)
    check("空节点表：gate 为 ''（不是 None/异常）", sp.gate() == "")
    check("空节点表：links 为 []", sp.links("x") == [] and sp.adjacency() == {})
    check("空节点表：depth 为 0", sp.depth("x") == 0)
    check("空节点表：len 为 0 / root 为空串", len(sp) == 0 and sp.root == "")
    sp2 = mk([{"id": "a", "role": HUB}])
    check("单节点链状：无邻接、gate=自己", sp2.links("a") == [] and sp2.gate() == "a")
    check("未知 id：links→[] / depth→0 / role_of→None",
          sp2.links("zzz") == [] and sp2.depth("zzz") == 0 and sp2.role_of("zzz") is None)
    check("nodes 属性是原始 dict（含自定义字段）",
          Space(nodes=[{"id": "a", "extra": 7}]).node("a")["extra"] == 7)


# ---------------------------------------------------------------- 2 chain
def t2_chain():
    print("\n[2] chain 链状：声明序相邻")
    sp = mk([{"id": "a"}, {"id": "b"}, {"id": "c"}], topology="chain")
    check("链首只连下一个", sp.links("a") == ["b"])
    check("链中连前后（顺序=声明序）", sp.links("b") == ["a", "c"])
    check("链尾只连上一个", sp.links("c") == ["b"])
    check("gate=首节点（链状入口即出口）", sp.gate() == "a")
    check("深度=声明序", [sp.depth(x) for x in "abc"] == [0, 1, 2])
    check("拓扑名回读", sp.topology == "chain" and sp.explicit is False)
    check("未给拓扑名时默认 chain", mk([{"id": "a"}]).topology == "chain")


# ---------------------------------------------------------------- 3 star
def t3_star():
    print("\n[3] star 星形：枢纽 / 通道 / 出口 + 两条防断链分支")
    sp = mk([{"id": "h", "role": HUB}, {"id": "s1", "role": SPOKE}, {"id": "s2", "role": SPOKE},
             {"id": "t", "role": THROUGH}, {"id": "g", "role": EXIT}], topology="star")
    check("枢纽连辐条与通道、**不含出口**", sp.links("h") == ["s1", "s2", "t"])
    check("通道连出口 + 枢纽（出口在前）", sp.links("t") == ["g", "h"])
    check("出口连通道", sp.links("g") == ["t"])
    check("辐条只连枢纽", sp.links("s1") == ["h"] and sp.links("s2") == ["h"])
    check("gate=出口角色节点", sp.gate() == "g")
    check("无角色节点按辐条处理（归枢纽）", mk([{"id": "h", "role": HUB}, {"id": "x"}],
                                              topology="star").links("x") == ["h"])
    check("星形深度=声明序（★ 不是 BFS）", [sp.depth(x) for x in ("h", "s1", "s2", "t", "g")] == [0, 1, 2, 3, 4])
    check("结构审计全绿", sp.audit()["ok"] is True, str(sp.audit()))

    # 防断链 ①：无通道 → 枢纽额外直连出口
    b1 = mk([{"id": "h", "role": HUB}, {"id": "s", "role": SPOKE}, {"id": "g", "role": EXIT}],
            topology="star")
    check("★防断链①无通道时枢纽直连出口", b1.links("h") == ["s", "g"], str(b1.links("h")))
    check("★防断链①出口直连枢纽", b1.links("g") == ["h"])
    check("★防断链①仍可达（route 非空）", b1.route("s", "g") == ["s", "h", "g"])
    check("★防断链①审计全绿", b1.audit()["ok"] is True)

    # 防断链 ②：roles 里没声明 through 值 → through 视为不存在 → 走同一条分支
    r_no_through = {"hub": "中心", "exit": "口"}
    b2 = Space(nodes=[{"id": "h", "role": HUB}, {"id": "t", "role": THROUGH}, {"id": "g", "role": EXIT}],
               topology="star", roles=r_no_through)
    check("★防断链②没声明 through 角色时按无通道处理",
          b2.links("h") == ["t", "g"] and b2.links("t") == ["h"], str(b2.links("h")))
    check("★防断链②无出口角色节点：gate 回退首节点", mk([{"id": "h", "role": HUB}, {"id": "s"}],
                                                       topology="star").gate() == "h")


# ---------------------------------------------------------------- 4 mesh / 深度口径
def t4_mesh():
    print("\n[4] mesh 显式连通表 + 深度两口径")
    links = {"a": ["b"], "b": ["a", "c"], "c": ["b"]}
    sp = Space(nodes=[{"id": "a"}, {"id": "b"}, {"id": "c"}], links=links, roles=R)
    check("显式表原样生效", [sp.links(x) for x in "abc"] == [["b"], ["a", "c"], ["b"]])
    check("未给拓扑名时 topology 标为 mesh", sp.topology == MESH and sp.explicit is True)
    check("★同一张图：显式=BFS 深度（b=1,c=2）", [sp.depth(x) for x in "abc"] == [0, 1, 2])
    der = mk([{"id": "a"}, {"id": "b"}, {"id": "c"}], topology="chain")
    check("★两口径确实不同（链状声明序 == BFS 此处相同，但来源不同）",
          der.depth("c") == 2 and sp.depth("c") == 2 and der.explicit != sp.explicit)
    # 声明序与 BFS 真不同的场景：星形（声明序 gate=4，BFS gate=2）
    star = mk([{"id": "h", "role": HUB}, {"id": "s1", "role": SPOKE}, {"id": "s2", "role": SPOKE},
               {"id": "t", "role": THROUGH}, {"id": "g", "role": EXIT}], topology="star")
    mesh_same = Space(nodes=[{"id": "h", "role": HUB}, {"id": "s1", "role": SPOKE},
                             {"id": "s2", "role": SPOKE}, {"id": "t", "role": THROUGH},
                             {"id": "g", "role": EXIT}],
                      links=star.adjacency(), roles=R)
    check("★同一张星形图：派生 gate 深度 4 / 显式 BFS 深度 2（故意不统一）",
          star.depth("g") == 4 and mesh_same.depth("g") == 2, f"{star.depth('g')}/{mesh_same.depth('g')}")
    check("显式不可达节点深度=节点数", mesh_same.depth("zzz") == 5)
    check("显式 ggate=首节点（网状图无天然出入口）", sp.gate() == "a")
    check("显式 + 派生形状名 → ValueError（互斥）",
          _raises(ValueError, lambda: Space(nodes=[{"id": "a"}], topology="star", links={}, roles=R)))
    check("mesh 名 + 不给 links → ValueError（保留名不派生）",
          _raises(ValueError, lambda: mk([{"id": "a"}], topology=MESH)))
    check("未知拓扑名 → ValueError 且带可用名字",
          _raises(ValueError, lambda: mk([{"id": "a"}], topology="ring_不存在的")))


def _raises(exc, fn):
    try:
        fn()
    except exc:
        return True
    except Exception:                                     # noqa: BLE001
        return False
    return False


# ---------------------------------------------------------------- 5 route
def t5_route():
    print("\n[5] route 必经路径")
    sp = mk([{"id": "h", "role": HUB}, {"id": "s", "role": SPOKE}, {"id": "t", "role": THROUGH},
             {"id": "g", "role": EXIT}], topology="star")
    check("辐条→出口：含两端", sp.route("s", "g") == ["s", "h", "t", "g"])
    check("同点 → 单元素", sp.route("s", "s") == ["s"])
    check("未知端点 → []", sp.route("s", "zzz") == [] and sp.route("zzz", "s") == [])
    check("反向也通（相邻对称）", sp.route("g", "s") == ["g", "t", "h", "s"])
    check("route_names 走 label_key", sp.route_names("s", "g", "id") == ["s", "h", "t", "g"])
    iso = Space(nodes=[{"id": "a"}, {"id": "b"}], links={"a": [], "b": []})
    check("不可达 → []", iso.route("a", "b") == [])


# ---------------------------------------------------------------- 6 audit
def t6_audit():
    print("\n[6] 结构审计（只报不改）")
    sp = Space(nodes=[{"id": "a"}, {"id": "b"}, {"id": "c"}],
               links={"a": ["b", "ghost"], "b": ["a"]})
    au = sp.audit()
    check("悬空边被抓（a→ghost）", au["dangling"] == [["a", "ghost"]])
    check("不可达节点被抓（c）", au["unreachable"] == ["c"])
    check("孤立节点被抓（c 无进无出）", au["isolated"] == ["c"])
    check("不对称被抓（a→b 但 b↛a？此处对称，答案 False）", au["asymmetric"] == [])
    au2 = Space(nodes=[{"id": "a"}, {"id": "b"}], links={"a": ["b"], "b": []}).audit()
    check("不对称被抓（a→b 但 b 不连 a）", au2["asymmetric"] == [["a", "b"]])
    check("有洞时 ok=False", au2["ok"] is False and au["ok"] is False)
    check("无出口角色节点被标 no_gate", mk([{"id": "h", "role": HUB}, {"id": "s"}],
                                          topology="star").audit()["no_gate"] is True)
    check("链状图不报 no_gate（无 hub 角色）", mk([{"id": "a"}, {"id": "b"}]).audit()["no_gate"] is False)


# ---------------------------------------------------------------- 7 注册表（可拔插）
def t7_registry():
    print("\n[7] 拓扑注册表（第三方扩展点）")
    check("内置形状 = chain / star（mesh 是保留名不在表里）",
          set(topology_names()) == {"chain", "star"} and MESH not in topology_names())

    def _ring(nodes, *, roles, role_key, root):
        ids = [n["id"] for n in nodes]
        return {"links": {i: [ids[(k - 1) % len(ids)], ids[(k + 1) % len(ids)]]
                          for k, i in enumerate(ids)}, "gate": root}

    register_topology("ring_test", _ring, doc="测试用环形")
    sp = mk([{"id": "a"}, {"id": "b"}, {"id": "c"}], topology="ring_test")
    check("注册的形状可用（环形首尾相连）", sp.links("a") == ["c", "b"], str(sp.links("a")))
    check("注册后出现在 topology_names", "ring_test" in topology_names())
    check("重名注册默认报错（防静默覆盖）",
          _raises(ValueError, lambda: register_topology("ring_test", _ring)))
    check("replace=True 才允许覆盖",
          register_topology("ring_test", _ring, doc="覆盖", replace=True) is _ring)
    check("保留名 mesh 不能注册", _raises(ValueError, lambda: register_topology(MESH, _ring)))
    check("非可调用 → TypeError", _raises(TypeError, lambda: register_topology("bad", 123)))
    T.TOPOLOGIES.pop("ring_test", None)                    # 复原（门禁不污染全局）
    check("清理后回到两种内置形状", set(topology_names()) == {"chain", "star"})


# ---------------------------------------------------------------- 8 零知识
def t8_zero_knowledge():
    print("\n[8] 零知识：换一套角色取值，结构一字不差")
    n_zh = [{"id": "h", "role": HUB}, {"id": "s", "role": SPOKE}, {"id": "t", "role": THROUGH},
            {"id": "g", "role": EXIT}]
    n_en = [{"id": "h", "role": "hub"}, {"id": "s", "role": "spoke"}, {"id": "t", "role": "through"},
            {"id": "g", "role": "gate"}]
    a = Space(nodes=n_zh, topology="star", roles=R)
    b = Space(nodes=n_en, topology="star",
              roles={"hub": "hub", "through": "through", "exit": "gate"})
    check("★换取值：邻接逐格一致", a.adjacency() == b.adjacency())
    check("★换取值：深度/gate/审计一致",
          [a.depth(x) for x in a.ids] == [b.depth(x) for x in b.ids] and a.gate() == b.gate()
          and a.audit() == b.audit())
    # 静态：引擎源码里不得出现角色**取值**（只准出现角色名）
    bad = []
    for root, _dirs, files in os.walk(os.path.join(ROOT, "saintess_engine", "space")):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(root, fn)
            with open(p, encoding="utf-8") as f:
                src = f.read()
            tree = ast.parse(src)
            for node in ast.walk(tree):                    # 只看代码里的字符串常量（注释/docstring 不算证据）
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if node.value in (HUB, SPOKE, THROUGH, EXIT, "城镇", "城镇街道", "城镇出口"):
                        bad.append(f"{fn}:{node.lineno}:{node.value}")
                elif isinstance(node, ast.JoinedStr):
                    for v in node.values:
                        if isinstance(v, ast.Constant) and v.value in (HUB, SPOKE, THROUGH, EXIT):
                            bad.append(f"{fn}:{node.lineno}:{v.value}")
    check("★引擎代码常量里零角色取值（取值只由内容侧给）", not bad, str(bad))


# ---------------------------------------------------------------- 9 视图
def t9_view():
    print("\n[9] to_view（编辑器画图用）")
    sp = mk([{"id": "h", "role": HUB, "name": "枢纽"}, {"id": "g", "role": EXIT, "name": "门口"}],
            topology="star", label_key="name")
    v = sp.to_view()
    check("视图键齐（topology/explicit/root/gate/nodes/edges/audit）",
          set(v) == {"topology", "explicit", "root", "gate", "nodes", "edges", "audit"})
    check("节点带 role/depth/label", v["nodes"][0] == {"id": "h", "role": HUB, "depth": 0, "label": "枢纽"})
    check("label 缺字段时回退 id", v["nodes"][1]["label"] == "门口" and
          mk([{"id": "a"}]).label_of("a") == "a")
    check("边是有向对（含防断链补的那条）", [["h", "g"], ["g", "h"]] == v["edges"])
    check("视图是纯 JSON 可序列化",
          isinstance(__import__("json").dumps(v, ensure_ascii=False), str))
    check("gate 覆盖参数生效", Space(nodes=[{"id": "a"}, {"id": "b"}], gate="b").gate() == "b")
    check("root 覆盖参数生效（链状 gate=root；派生深度仍是声明序，与 root 无关）",
          Space(nodes=[{"id": "a"}, {"id": "b"}], topology="chain", root="b").gate() == "b"
          and Space(nodes=[{"id": "a"}, {"id": "b"}], topology="chain", root="b").depth("a") == 0)
    check("root 覆盖影响显式图的 BFS 深度",
          Space(nodes=[{"id": "a"}, {"id": "b"}, {"id": "c"}],
                links={"a": ["b"], "b": ["a", "c"], "c": ["b"]}, root="c").depth("a") == 2)
    check("entry() 与 gate() 同义（内容侧旧两名合一）", sp.entry() == sp.gate())
    check("role_key 可换（不叫 role 的字段也行）",
          Space(nodes=[{"id": "h", "type": HUB}, {"id": "g", "type": EXIT}], topology="star",
                roles=R, role_key="type").gate() == "g")
    check("id_key 可换", Space(nodes=[{"code": "a"}], id_key="code").ids == ("a",))


def main():
    print("== space 门禁：拓扑派生 / 深度两口径 / 出入口 / 必经路径 / 审计 / 注册表 / 零知识 ==")
    t1_empty()
    t2_chain()
    t3_star()
    t4_mesh()
    t5_route()
    t6_audit()
    t7_registry()
    t8_zero_knowledge()
    t9_view()
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
