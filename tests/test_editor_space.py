# -*- coding: utf-8 -*-
"""maps 域（空间形状）编辑器门禁：域注册 / 词典与分组 / 视图派生 / HTTP 端到端。

守两条：
  ① **派生只有一份**：编辑器画图用的邻接/深度/出入口，必须来自引擎 `ext_world.space`
     （`editor/space_view.py` 只是适配），不是前端或编辑器里另写的一套。
  ② **编辑器 → 数据文件 → 引擎**这条链闭合：编辑器校验过的数据，喂给 `Space` 能算出图。

跑法：python tests/test_editor_space.py
"""
import json
import os
import sys
import threading
import tempfile
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import _domain_fixtures as FX             # noqa: E402  （域元数据：引擎默认集 / 扩展包域 / 内容域）
from editor import glossary as G          # noqa: E402
from editor import packages as PK         # noqa: E402
from editor import server as SRV          # noqa: E402
from editor import space_view as SV       # noqa: E402
from editor import validate as VD         # noqa: E402
from ext_world.space import Space   # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "PASS", "FAIL", "FAILURES")


def req(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method,
                               headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw}


STAR = {
    "name": "示例镇",
    "topology": "star",
    "roles": {"hub": "hub", "through": "through", "exit": "exit"},
    "nodes": [{"id": "plaza", "name": "中央广场", "role": "hub"},
              {"id": "smith", "name": "铁匠铺"},
              {"id": "east_road", "name": "东大街", "role": "through"},
              {"id": "outskirts", "name": "镇郊", "role": "exit"}],
}
PLAIN = {
    "name": "示例平原",
    "topology": "chain",
    "nodes": [{"id": "plain_1", "name": "平原入口"}, {"id": "plain_2", "name": "平原深处"}],
}


def t1_domain():
    print("\n[1] 域注册与词典覆盖")
    # maps 随消费端搬进扩展包 ext_world（2026-09-23 第 4 批）
    meta = FX.meta_of("maps")
    check("maps 域已注册（ext_world 声明）", bool(meta), sorted(FX.all_domains()))
    if meta:
        sp = os.path.join(ROOT, "schemas", meta["schema"])
        check(f"schema 文件存在（{meta['schema']}）", os.path.exists(sp), sp)
        sch = json.load(open(sp, encoding="utf-8"))
        check(f"primary={meta['primary']!r} 在 schema $defs 里",
              meta["primary"] in (sch.get("$defs") or {}), list(sch.get("$defs") or {}))
        check("schema 里零 enum（枚举值会是游戏分类，门禁红线）",
              "enum" not in json.dumps(sch, ensure_ascii=False))
    check("词典有 maps 域", "maps" in G.GLOSSARY and bool(G.GLOSSARY["maps"]))
    gs = G.groups_for("maps")
    check(f"表单分组 {len(gs)} 组，且每组非空", len(gs) >= 3 and all(g["fields"] for g in gs))
    listed = [k for g in gs for k in g["fields"]]
    check("分组无重复字段", len(listed) == len(set(listed)), listed)
    fields = ["name", "desc", "topology", "roles", "nodes", "links", "root", "gate", "id", "role"]
    check("schema 全部字段都分到组里", all(f in listed for f in fields),
          [f for f in fields if f not in listed])
    check("每个字段都有中文名", all((G.lookup("maps", f) or {}).get("zh") for f in fields),
          [f for f in fields if not (G.lookup("maps", f) or {}).get("zh")])
    check("词典引用可解析（页存在 + 词在页里）",
          all(not e.get("ref") or (os.path.isfile(G.wiki_path(e["ref"][0]))
                                   and e["ref"][1] in open(G.wiki_path(e["ref"][0]), encoding="utf-8").read())
              for e in G.GLOSSARY["maps"].values()), "见 test_editor_glossary 的同类断言")
    check("词典每条都有注脚（不留空壳）",
          all((e.get("note") or "").strip() for e in G.GLOSSARY["maps"].values()))


def t2_view_star():
    print("\n[2] 视图派生：星形（与引擎同一份代码）")
    out = SV.build(STAR)
    check("build 成功", out.get("ok") is True, str(out))
    v = out["view"]
    check("拓扑名 = star / 非显式", v["topology"] == "star" and v["explicit"] is False)
    check("节点 4 个、深度 = 声明序", [n["depth"] for n in v["nodes"]] == [0, 1, 2, 3])
    check("label 取 name", [n["label"] for n in v["nodes"]] == ["中央广场", "铁匠铺", "东大街", "镇郊"])
    check("枢纽不含出口、通道连出口+枢纽",
          ["smith", "east_road"] == [e[1] for e in v["edges"] if e[0] == "plaza"]
          and sorted(e[1] for e in v["edges"] if e[0] == "east_road") == ["outskirts", "plaza"],
          str(v["edges"]))
    check("gate = 出口角色节点", v["gate"] == "outskirts")
    check("audit 通过", v["audit"]["ok"] is True, str(v["audit"]))
    check("role_values 去重且有序", v["role_values"] == ["exit", "hub", "through"], v["role_values"])
    check("无警告", not out["warnings"], str(out["warnings"]))
    # 与引擎直算逐项一致（同一份代码的证据，不是「看起来一样」）
    sp = Space(nodes=STAR["nodes"], topology="star", roles=STAR["roles"], label_key="name")
    check("★ 与引擎 Space 直算逐项一致（邻接/深度/gate/审计）",
          all([sorted(sp.links(n["id"])) == sorted(e[1] for e in v["edges"] if e[0] == n["id"])
               for n in v["nodes"]])
          and [sp.depth(n["id"]) for n in v["nodes"]] == [n["depth"] for n in v["nodes"]]
          and sp.gate() == v["gate"] and sp.audit() == v["audit"])


def t3_view_variants():
    print("\n[3] 视图派生：链状 / 显式连通表 / 错误与警告")
    out = SV.build(PLAIN)
    check("链状图：首尾相连、gate = 首节点",
          out["view"]["topology"] == "chain" and out["view"]["gate"] == "plain_1"
          and out["view"]["nodes"][1]["depth"] == 1)
    mesh = {"name": "示例副本", "nodes": [{"id": "r1"}, {"id": "r2"}, {"id": "r3"}],
            "links": {"r1": ["r2"], "r2": ["r1", "r3"], "r3": ["r2"]}}
    out = SV.build(mesh)
    check("显式连通表：explicit=True 且深度走 BFS",
          out["view"]["explicit"] is True and out["view"]["topology"] == "mesh"
          and [n["depth"] for n in out["view"]["nodes"]] == [0, 1, 2])
    out = SV.build({"name": "冲突", "topology": "star", "nodes": [{"id": "a"}], "links": {"a": []}})
    check("同时给 topology 与 links → 连通表优先 + 明确警告",
          out["ok"] and out["view"]["explicit"] is True and any("连通表优先" in w for w in out["warnings"]),
          str(out.get("warnings")))
    for bad, why in (({"name": "x"}, "无节点"), ({"name": "x", "topology": "mesh"}, "mesh 无 links"),
                     ({"name": "x", "nodes": [{"id": "a"}], "roles": "hub"}, "roles 非对象")):
        out = SV.build(bad)
        check(f"坏数据被拦（{why}）", out.get("ok") is False and out.get("error"), str(out))
    out = SV.build({"name": "x", "nodes": [{"id": "a"}, {"id": "b"}], "topology": "不存在的形状"})
    check("未知形状名 → 报错文案带可用形状（不是 500）",
          out.get("ok") is False and "chain" in (out.get("error") or ""), str(out))
    out = SV.build_file({"m1": PLAIN}, "nope")
    check("build_file 缺 key → ok=False + 中文原因",
          out.get("ok") is False and "没有这条图" in (out.get("error") or ""), str(out))


def t4_schema_validation():
    print("\n[4] schema 校验：合法过、非法被拦")
    check("合法条目通过校验", VD.validate_entry("maps", STAR) == [], str(VD.validate_entry("maps", STAR)))
    check("合法链状条目通过", VD.validate_entry("maps", PLAIN) == [])
    e1 = VD.validate_entry("maps", {"nodes": [{"id": "a"}]})
    check("缺 name 被拦", any("name" in x for x in e1), str(e1))
    e2 = VD.validate_entry("maps", {"name": "x", "nodes": []})
    check("nodes 空数组被拦", bool(e2), str(e2))
    e3 = VD.validate_entry("maps", {"name": "x", "nodes": [{"name": "缺 id"}]})
    check("节点缺 id 被拦", any("id" in x for x in e3), str(e3))
    e4 = VD.validate_entry("maps", {"name": "x", "nodes": [{"id": "a"}], "links": {"a": "b"}})
    check("links 值不是数组被拦", bool(e4), str(e4))


def t5_http():
    print("\n[5] HTTP 端到端：编辑器 → 数据文件 → 引擎")
    gd = tempfile.mkdtemp(prefix="fw_editor_maps_")
    SRV.GAMES_DIR = gd
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), SRV.H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    st, j = req(base, "POST", "/api/packages", {"id": "map_demo", "name": "地图演示", "domains": ["maps"]})
    check("建包（只勾 maps 域）成功", st == 200 and j.get("ok"), f"{st} {j}")
    st, j = req(base, "GET", "/api/package/map_demo/d/maps")
    check("新建包的 maps 域可列（空表）", st == 200 and j.get("count") == 0, f"{st} {j}")
    st, j = req(base, "GET", "/api/schema/maps")
    check("GET /api/schema/maps 有 schema", st == 200 and j.get("ok") and j.get("schema"), f"{st}")
    for k, v in (("town_a", STAR), ("plain_a", PLAIN)):
        st, j = req(base, "PUT", f"/api/package/map_demo/d/maps/{k}", {"data": v})
        check(f"PUT {k} 落盘成功", st == 200 and j.get("ok"), f"{st} {j}")
    st, j = req(base, "GET", "/api/package/map_demo/d/maps")
    check("列表 2 条", st == 200 and j.get("count") == 2, f"{st} {j}")
    st, j = req(base, "GET", "/api/package/map_demo/d/maps/town_a/graph")
    check("GET graph 200", st == 200 and j.get("ok"), f"{st} {j}")
    check("★ 端到端视图 = 引擎派生（gate/深度/审计）",
          j.get("view", {}).get("gate") == "outskirts"
          and [n["depth"] for n in j.get("view", {}).get("nodes", [])] == [0, 1, 2, 3]
          and j.get("view", {}).get("audit", {}).get("ok") is True, str(j)[:200])
    st, j = req(base, "GET", "/api/package/map_demo/d/maps/plain_a/graph")
    check("链状图端到端", st == 200 and j.get("view", {}).get("topology") == "chain", f"{st} {j}")
    st, j = req(base, "GET", "/api/package/map_demo/d/maps/nope/graph")
    check("不存在的图 → 422 + 中文原因", st == 422 and "没有这条图" in (j.get("error") or ""), f"{st} {j}")
    st, j = req(base, "GET", "/api/package/map_demo/d/nosuchdom/x/graph")
    check("未知域 → 404", st == 404, f"{st} {j}")
    # 非法条目必须被**校验拦住**（不是落盘后再崩）
    st, j = req(base, "PUT", "/api/package/map_demo/d/maps/bad_one",
                {"data": {"name": "坏图", "nodes": [{"name": "没有 id"}]}})
    check("非法条目 PUT 被拦（4xx）", st >= 400, f"{st} {j}")
    st, j = req(base, "GET", "/api/package/map_demo/d/maps")
    check("被拦的条目没落盘（仍是 2 条）", j.get("count") == 2, f"{st} {j}")
    st, j = req(base, "GET", "/api/glossary")
    check("词典接口含 maps 域（编辑器面板不空白）",
          st == 200 and "maps" in (j.get("domains") or {}), f"{st}")
    check("分组接口含 maps 域", "maps" in (j.get("groups") or {}), str(list((j.get("groups") or {}))))
    # 域注册表不带包只有引擎默认集；要看扩展包带来的域（这 5 个随消费端搬走了）就带 pkg
    st, j = req(base, "GET", "/api/domains?pkg=map_demo")
    check("域列表里有 maps（前端 tab/模式判断的依据）",
          any(d.get("id") == "maps" for d in (j.get("domains") or [])), f"{st}")
    httpd.shutdown()


def main():
    print("== maps 域（空间形状）编辑器门禁 ==")
    t1_domain()
    t2_view_star()
    t3_view_variants()
    t4_schema_validation()
    t5_http()
    print(f"\n===== 结果：通过 {PASS} / {PASS + FAIL} =====")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
