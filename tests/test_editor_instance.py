# -*- coding: utf-8 -*-
"""instances 域（运行形状）编辑器门禁：域注册 / 词典与分组 / schema 校验 / 进度视图 / HTTP 端到端。

守三条：
  ① **推进语义只有一份**：`is_last` / 每层剩余 / 总剩余 / done 必须来自引擎
     `saintess_engine.run.Progress`（`editor/instance_view.py` 只是适配），不是编辑器另写的一套。
  ② **不装懂**：怪名 / Boss / 钥匙 / 地图 / 层名都是内容侧词汇 —— 预览不判断某个引用是什么，
     需要解析的地方只能给 warning；数据不合法（层空 / Boss 不在末层）**如实报错**，不假装有内容。
  ③ **零 enum**：框架不预设怪物名、层名、钥匙名（那会是内容分类）。

跑法：python tests/test_editor_instance.py
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

import saintess_engine.run as ERUN        # noqa: E402
from editor import glossary as G          # noqa: E402
from editor import instance_view as IV    # noqa: E402
from editor import packages as PK         # noqa: E402
from editor import server as SRV          # noqa: E402
from editor import validate as VD         # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


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


# ───────────────────────────── 示例数据（全 ASCII 假名，不引用任何具体游戏词）
TWO_STAGE = {
    "name": "inst_a",
    "lv": 10,
    "icon": "x",
    "min_players": 1,
    "max_players": 3,
    "key_item": "key_a",
    "key_source": "src_a",
    "entry": {"map": "map_a", "subarea": "sub_a"},
    "boss": "boss_z",
    "hp_mult": 1.5,
    "atk_mult": 1.2,
    "stages": [
        {"name": "s1", "monsters": ["mon_a", "mon_b"], "pois": ["poi_a"]},
        {"name": "s2", "elite": ["eli_a"], "boss": ["boss_b"], "secret": "sec_a", "npc": "npc_a"},
    ],
    "gold": 100,
    "exp": 200,
    "materials": ["mat_a"],
    "desc": "两层样例",
}
FULL = {"inst_a": TWO_STAGE,
        "inst_b": {"name": "inst_b", "stages": [{"monsters": ["mon_c"]}]}}


def t1_domain():
    print("\n[1] 域注册与 schema")
    meta = PK.DOMAINS.get("instances")
    check("instances 域已注册", bool(meta), list(PK.DOMAINS))
    if not meta:
        return
    check("label = 副本 / icon = 🏯 / kind = data",
          meta["label"] == "副本" and meta["icon"] == "🏯" and meta["kind"] == "data", str(meta))
    sp = os.path.join(ROOT, "schemas", meta["schema"])
    check(f"schema 文件存在（{meta['schema']}）", os.path.exists(sp), sp)
    sch = json.load(open(sp, encoding="utf-8"))
    defs = sch.get("$defs") or {}
    check(f"primary={meta['primary']!r} 在 $defs 里且 = x-primary",
          meta["primary"] in defs and sch.get("x-primary") == meta["primary"], list(defs))
    check("$defs 含 instance / stage / entry_point",
          {"instance", "stage", "entry_point"} <= set(defs), list(defs))
    check("★ schema 里零 enum（怪名/层名/钥匙名必须是自由串，枚举会是内容分类）",
          "enum" not in json.dumps(sch, ensure_ascii=False))
    check("instance.required = [name, stages]",
          defs["instance"].get("required") == ["name", "stages"],
          str(defs["instance"].get("required")))
    check("stage 允许扩展字段（additionalProperties）",
          defs["stage"].get("additionalProperties") is True)
    check("stages 至少一层（minItems 1）",
          (defs["instance"]["properties"]["stages"] or {}).get("minItems") == 1)
    check("倍率是正数（exclusiveMinimum 0）",
          (defs["instance"]["properties"]["hp_mult"] or {}).get("exclusiveMinimum") == 0)
    check("域 → schema 映射表里有 instances（词典接口不会漏这个域）",
          G.DOMAIN_SCHEMA.get("instances") == "instances.schema.json",
          str(G.DOMAIN_SCHEMA.get("instances")))


def t2_glossary():
    print("\n[2] 字段词典与分组")
    check("词典有 instances 域且非空",
          "instances" in G.GLOSSARY and bool(G.GLOSSARY["instances"]))
    # 叶名（框架约定：$defs 逐层展开成叶名后查词典 —— entry.map / stages.monsters 都按叶名登记）
    fields = ["name", "lv", "icon", "min_players", "max_players", "key_item", "key_source",
              "entry", "map", "subarea", "boss", "hp_mult", "atk_mult", "stages",
              "monsters", "elite", "pois", "secret", "npc", "gold", "exp", "materials", "desc"]
    miss = [f for f in fields if not (G.lookup("instances", f) or {}).get("zh")]
    check(f"schema 全部 {len(fields)} 个字段都有中文名", not miss, f"缺：{miss}")
    nonotes = [k for k, e in G.GLOSSARY["instances"].items() if not (e.get("note") or "").strip()]
    check("每条词典都有注脚（不留空壳）", not nonotes, str(nonotes))
    grps = G.groups_for("instances")
    check("有字段分组且 ≥ 3 组（界面别平铺 23 个字段）", len(grps) >= 3, str(len(grps)))
    covered = {f for g in grps for f in g["fields"]}
    # 框架约定：分组要覆盖**全部 $defs 的字段名并集**（嵌套子键按叶名登记，同 drop_pools/maps）
    sch = json.load(open(os.path.join(ROOT, "schemas", "instances.schema.json"), encoding="utf-8"))
    allf = set()
    for d in (sch.get("$defs") or {}).values():
        allf |= set((d.get("properties") or {}).keys())
    check(f"全部 $defs 字段名（{len(allf)} 个）一个不漏地分到组里", allf <= covered,
          f"漏：{sorted(allf - covered)}")
    check("分组里没有 schema 不存在的字段（防拼错）", covered <= allf,
          f"幽灵：{sorted(covered - allf)}")
    check("引擎零知识：没有哪条词典把引用类字段写成枚举候选",
          all(not (e.get("choices") or []) for e in G.GLOSSARY["instances"].values()))


def t3_view():
    print("\n[3] 进度视图（引擎同一份 Progress）")
    check("★ 视图用的就是引擎的 Progress（不是编辑器另写的一套）",
          IV.Progress is ERUN.Progress)
    out = IV.build(TWO_STAGE, "inst_a")
    check("合法数据 → ok", out.get("ok") is True, str(out)[:160])
    if not out.get("ok"):
        return
    check("层数 = 2 / 单位总数 = 4（2 怪 + 1 精英 + 1 Boss）",
          out["stage_count"] == 2 and out["total_units"] == 4,
          f"{out['stage_count']} {out['total_units']}")
    check("节点序 = 层序（order）", out["order"] == ["s1", "s2"], str(out["order"]))
    s1, s2 = out["stages"]
    check("★ 末层标记来自引擎 is_last（第 1 层 False / 第 2 层 True）",
          s1["is_last"] is False and s2["is_last"] is True, f"{s1['is_last']} {s2['is_last']}")
    check("★ 每层剩余 = 引擎剩余池（第 1 层 2 / 第 2 层 2）",
          s1["left"] == 2 and s2["left"] == 2, f"{s1['left']} {s2['left']}")
    check("每层单位计数与构成（普通/精英/Boss/POI 分开列）",
          s1["monsters"] == 2 and s1["pois"] == ["poi_a"] and s2["elite"] == 1
          and s2["boss"] == 1 and s2["secret"] == "sec_a" and s2["npc"] == "npc_a",
          json.dumps([s1, s2], ensure_ascii=False)[:200])
    check("★ 全局剩余 / done 来自引擎（4 / False）",
          out["progress_check"]["total_left"] == 4 and out["progress_check"]["done"] is False,
          str(out["progress_check"]))
    check("层名为空时按序回退「第 N 层」",
          IV.build({"name": "i", "stages": [{"monsters": ["m"]}]}, "").get("order") == ["第 1 层"])
    check("不装懂：给 warning 说明引用是内容侧词汇",
          any("内容侧词汇" in w for w in out["warnings"]), str(out["warnings"])[:160])
    check("倍率原样带出（1.5 / 1.2）",
          out["scaling"] == {"hp_mult": 1.5, "atk_mult": 1.2}, str(out["scaling"]))

    print("\n[3b] 坏数据如实报错（不伪装）")
    cases = [
        ("层空（没有怪/精英/Boss）", {"name": "i", "stages": [{"name": "s", "pois": ["p"]}]},
         "没有任何战斗单位"),
        ("Boss 不在末层", {"name": "i", "stages": [{"monsters": ["m"], "boss": ["b"]},
                                                {"monsters": ["m2"]}]}, "不是末层"),
        ("stages 不是数组 / 为空", {"name": "i", "stages": []}, "非空数组"),
        ("缺 name", {"stages": [{"monsters": ["m"]}]}, "缺少 name"),
        ("min_players > max_players", {"name": "i", "min_players": 3, "max_players": 2,
                                       "stages": [{"monsters": ["m"]}]}, "人数区间不成立"),
        ("倍率 ≤ 0", {"name": "i", "hp_mult": 0, "stages": [{"monsters": ["m"]}]}, "倍率不成立"),
        ("monsters 不是数组", {"name": "i", "stages": [{"monsters": "m"}]}, "必须是数组"),
        ("层不是对象", {"name": "i", "stages": ["s"]}, "不是对象"),
    ]
    for label, data, needle in cases:
        o = IV.build(data, "k")
        check(f"★ {label} → ok=False（{needle}）",
              o.get("ok") is False and needle in (o.get("error") or ""), str(o)[:160])
        check(f"   {label}：不给 stages/order（不假装有内容）",
              not o.get("stages") and not o.get("order"), str(o)[:120])
    o = IV.build_file(FULL, "ghost")
    check("不存在的副本 → ok=False + 中文原因",
          o.get("ok") is False and "没有这条副本" in (o.get("error") or ""), str(o)[:120])


def t4_schema_validation():
    print("\n[4] schema 校验：合法过、非法被拦")
    check("合法条目通过校验", VD.validate_entry("instances", TWO_STAGE) == [],
          str(VD.validate_entry("instances", TWO_STAGE)))
    e1 = VD.validate_entry("instances", {"stages": [{"monsters": ["m"]}]})
    check("缺 name 被拦", any("name" in x for x in e1), str(e1))
    e2 = VD.validate_entry("instances", {"name": "i", "stages": []})
    check("stages 空被拦（minItems）", bool(e2), str(e2))
    e3 = VD.validate_entry("instances", {"name": "i", "stages": [{"monsters": ["m"]}], "hp_mult": 0})
    check("hp_mult = 0 被拦（exclusiveMinimum）", bool(e3), str(e3))
    e4 = VD.validate_entry("instances", {"name": "i", "stages": {"monsters": ["m"]}})
    check("stages 不是数组被拦", bool(e4), str(e4))


def t5_http():
    print("\n[5] HTTP 端到端：编辑器 → 数据文件 → 引擎")
    gd = tempfile.mkdtemp(prefix="fw_editor_instance_")
    SRV.GAMES_DIR = gd
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), SRV.H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    st, j = req(base, "POST", "/api/packages", {"id": "inst_demo", "name": "副本演示",
                                               "domains": ["instances"]})
    check("建包（只勾 instances 域）成功", st == 200 and j.get("ok"), f"{st} {j}")
    st, j = req(base, "GET", "/api/schema/instances")
    check("GET /api/schema/instances 有 schema", st == 200 and j.get("ok") and j.get("schema"), f"{st}")
    for k, v in FULL.items():
        st, j = req(base, "PUT", f"/api/package/inst_demo/d/instances/{k}", {"data": v})
        check(f"PUT {k} 落盘成功", st == 200 and j.get("ok"), f"{st} {j}")
    st, j = req(base, "GET", "/api/package/inst_demo/d/instances")
    check("列表 2 条", st == 200 and j.get("count") == len(FULL), f"{st} {j}")

    st, j = req(base, "GET", "/api/package/inst_demo/d/instances/inst_a/run")
    check("GET run → 200 + ok（进度视图）", st == 200 and j.get("ok"), f"{st} {str(j)[:160]}")
    check("★ 端到端末层标记 = 引擎 is_last",
          j.get("stages", [{}])[0].get("is_last") is False
          and j.get("stages", [{}, {}])[1].get("is_last") is True, str(j.get("stages"))[:200])
    check("★ 端到端每层剩余 = 引擎剩余池（2 / 2）",
          [s.get("left") for s in j.get("stages") or []] == [2, 2], str(j.get("stages"))[:200])
    check("端到端带「内容侧词汇」warning",
          any("内容侧词汇" in w for w in (j.get("warnings") or [])), str(j.get("warnings"))[:160])

    st, j = req(base, "GET", "/api/package/inst_demo/d/instances/ghost/run")
    check("不存在的副本 → 422 + 中文原因",
          st == 422 and "没有这条副本" in (j.get("error") or ""), f"{st} {j}")
    check("不存在的副本 → 不假装有内容（无 stages/order）",
          not j.get("ok") and not j.get("stages") and not j.get("order"), str(j)[:120])
    st, j = req(base, "GET", "/api/package/inst_demo/d/maps/nope/run")
    check("进度视图只服务 instances（别的域 → 404）", st == 404, f"{st} {j}")
    st, j = req(base, "GET", "/api/package/inst_demo/d/nosuchdom/x/run")
    check("未知域 → 404", st == 404, f"{st} {j}")
    st, j = req(base, "GET", "/api/package/nope/d/instances/inst_a/run")
    check("包不存在 → 404", st == 404, f"{st} {j}")

    st, j = req(base, "GET", "/api/domains")
    check("域列表里有 instances（前端 tab 的依据）",
          any(d.get("id") == "instances" for d in (j.get("domains") or [])), f"{st}")
    st, j = req(base, "GET", "/api/glossary")
    check("词典接口含 instances 域", st == 200 and "instances" in (j.get("domains") or {}), f"{st}")
    check("分组接口含 instances 域", "instances" in (j.get("groups") or {}),
          str(list(j.get("groups") or {}))[:120])
    st, j = req(base, "GET", "/api/package/inst_demo")
    check("包概览里 instances 域条目数正确（2）",
          st == 200 and any(d.get("id") == "instances" and d.get("count") == len(FULL)
                            for d in (j.get("domains") or [])), str(j.get("domains"))[:200])

    st, j = req(base, "PUT", "/api/package/inst_demo/d/instances/bad_one",
                {"data": {"stages": [{"monsters": ["m"]}]}})
    check("非法条目 PUT 被拦（4xx）", st >= 400, f"{st} {j}")
    httpd.shutdown()


def main():
    print("=" * 74)
    print("instances 域编辑器门禁：域注册 / 词典 / schema / 进度视图 / HTTP")
    print("=" * 74)
    t1_domain()
    t2_glossary()
    t3_view()
    t4_schema_validation()
    t5_http()
    print("\n" + "=" * 74)
    print(f"结果：通过 {PASS} / {PASS + FAIL}")
    print("=" * 74)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
