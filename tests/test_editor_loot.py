# -*- coding: utf-8 -*-
"""drop_pools 域（随机产出形状）编辑器门禁：域注册 / 词典与分组 / 池预览 / HTTP 端到端。

守两条：
  ① **算法只有一份**：预览里的权重占比、展开候选、结构审计，必须来自引擎
     `saintess_engine.loot.LootTable`（`editor/loot_view.py` 只是适配），不是编辑器或前端另写的一套。
  ② **不装懂**：`resolver=None` —— 预览不假装知道某个引用是什么物品；需要解析的地方只能给 warning。

跑法：python tests/test_editor_loot.py
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

from editor import glossary as G            # noqa: E402
from editor import loot_view as LV          # noqa: E402
from editor import packages as PK           # noqa: E402
from editor import server as SRV            # noqa: E402
from editor import validate as VD           # noqa: E402
from saintess_engine.loot import LootTable  # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name} {detail}")
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
WEIGHTED = {
    "type": "weighted",
    "entries": [{"item": "mat_a", "w": 5, "n": 1},
                {"item": "equip_a", "w": 1, "min_lv": 20}],
    "fallback": "mat_z",
    "desc": "带权池",
}
FIXED = {
    "type": "fixed",
    "entries": [{"item": "mat_a", "n": 3}, {"item": "mat_b"}],
    "desc": "必掉清单",
}
TABLE = {
    "type": "table",
    "rolls": [{"pool": "pool_a", "chance": 0.3, "n": 2}],
    "desc": "多层概率表",
}
CHOICE = {
    "type": "table_choice",
    "rolls": [{"pool": "pool_a", "cutoff": 0.25, "n": [1, 2], "fallback": "mat_z"},
              {"pool": "pool_b", "cutoff": 0.75}],
    "desc": "互斥档",
}
POOL_A = {"type": "weighted", "entries": [{"item": "mat_b", "w": 2}]}
POOL_B = {"type": "fixed", "entries": [{"item": "mat_c"}, {"item": "mat_d", "n": 2}]}
FULL = {"weighted_a": WEIGHTED, "fixed_a": FIXED, "table_a": TABLE,
        "choice_a": CHOICE, "pool_a": POOL_A, "pool_b": POOL_B}


def t1_domain():
    print("\n[1] 域注册与 schema")
    meta = PK.DOMAINS.get("drop_pools")
    check("drop_pools 域已注册", bool(meta), list(PK.DOMAINS))
    if meta:
        check("label = 掉落池 / icon = 🎁 / kind = data",
              meta["label"] == "掉落池" and meta["icon"] == "🎁" and meta["kind"] == "data",
              str(meta))
        sp = os.path.join(ROOT, "schemas", meta["schema"])
        check(f"schema 文件存在（{meta['schema']}）", os.path.exists(sp), sp)
        sch = json.load(open(sp, encoding="utf-8"))
        defs = sch.get("$defs") or {}
        check(f"primary={meta['primary']!r} 在 schema $defs 里且 = x-primary",
              meta["primary"] in defs and sch.get("x-primary") == meta["primary"], list(defs))
        check("$defs 至少含 pool / pool_entry / pool_roll",
              {"pool", "pool_entry", "pool_roll"} <= set(defs), list(defs))
        check("schema 里零 enum（策略名/取值必须是自由串，枚举会是内容分类）",
              "enum" not in json.dumps(sch, ensure_ascii=False))
        check("pool.required 只有 type", defs["pool"].get("required") == ["type"],
              str(defs["pool"].get("required")))
        check("pool_entry 必填 item", defs["pool_entry"].get("required") == ["item"],
              str(defs["pool_entry"].get("required")))
        check("pool_entry 允许扩展字段（additionalProperties）",
              defs["pool_entry"].get("additionalProperties") is True)
        check("pool_roll 必填 pool", defs["pool_roll"].get("required") == ["pool"],
              str(defs["pool_roll"].get("required")))
        check("type 字段是字符串且不设枚举（内容侧可注册新策略）",
              (defs["pool"]["properties"]["type"] or {}).get("type") == "string")
        check("pool 有 2 个 examples", len(defs["pool"].get("examples") or []) == 2,
              str(len(defs["pool"].get("examples") or [])))
        check("examples 不含具体游戏词（只用 mat_a / pool_a 这类假名）",
              all(t in json.dumps(defs["pool"]["examples"], ensure_ascii=False)
                  for t in ("mat_a", "pool_a")))
        check("域 → schema 映射表里有 drop_pools（词典接口不会漏这个域）",
              G.DOMAIN_SCHEMA.get("drop_pools") == "drop_pools.schema.json",
              str(G.DOMAIN_SCHEMA.get("drop_pools")))


def t2_glossary():
    print("\n[2] 字段词典与分组")
    check("词典有 drop_pools 域且非空", "drop_pools" in G.GLOSSARY and bool(G.GLOSSARY["drop_pools"]))
    fields = ["type", "entries", "rolls", "fallback", "desc", "item", "w", "n",
              "min_lv", "max_lv", "pool", "chance", "cutoff", "fallback_n"]
    miss = [f for f in fields if not (G.lookup("drop_pools", f) or {}).get("zh")]
    check(f"schema 全部 {len(fields)} 个字段都有中文名", not miss, f"缺：{miss}")
    nonotes = [k for k, e in G.GLOSSARY["drop_pools"].items() if not (e.get("note") or "").strip()]
    check("每条词典都有注脚（不留空壳）", not nonotes, str(nonotes))
    bad = []
    for k, e in G.GLOSSARY["drop_pools"].items():
        ref = e.get("ref")
        if not ref:
            continue
        fp = G.wiki_path(ref[0])
        if not os.path.isfile(fp):
            bad.append(f"{k} → 页面不存在 {ref[0]}")
        elif ref[1] not in open(fp, encoding="utf-8").read():
            bad.append(f"{k} → {ref[0]} 里没有「{ref[1]}」")
    check("wiki 引用逐条可解析（页存在 + 词真在页里）", not bad, str(bad))

    gs = G.groups_for("drop_pools")
    check(f"表单分组 {len(gs)} 组（≥3），且每组非空",
          len(gs) >= 3 and all(g["fields"] for g in gs), str([g["id"] for g in gs]))
    listed = [k for g in gs for k in g["fields"]]
    check("分组无重复字段", len(listed) == len(set(listed)), str(listed))
    uncovered = [f for f in fields if f not in listed]
    check("全部字段一个不漏地分到组里", not uncovered, f"漏：{uncovered}")
    check("组里没有 schema 不存在的字段（防拼错）",
          not [k for k in listed if k not in fields], str([k for k in listed if k not in fields]))
    check("分组 id 唯一且都有标签",
          len({g["id"] for g in gs}) == len(gs) and all(g.get("label") for g in gs))
    check("all_groups 覆盖 drop_pools（前端面板不空白）", "drop_pools" in G.all_groups())
    check("chance / cutoff 是 0~1 → 给滑杆",
          G.widget_for("drop_pools", "chance") == "pct" and G.widget_for("drop_pools", "cutoff") == "pct",
          f"{G.widget_for('drop_pools', 'chance')} / {G.widget_for('drop_pools', 'cutoff')}")


def t3_preview_shapes():
    print("\n[3] 预览：四种内置策略的结构与权重")
    out = LV.build_file(FULL, "weighted_a")
    check("weighted 预览成功", out.get("ok") is True, str(out))
    check("type / strategy_uses 正确",
          out["type"] == "weighted" and out["strategy_uses"] == "entries", str(out.get("type")))
    rows = out["entries"]
    check("entries 按占比降序（最常见的在前）",
          [r["ref"] for r in rows] == ["mat_a", "equip_a"], str(rows))
    check("★ share = 权重 ÷ 池内权重和（5/6 与 1/6）",
          (rows[0]["share"], rows[1]["share"]) == (round(5 / 6, 4), round(1 / 6, 4))
          and (rows[0]["w"], rows[1]["w"]) == (5, 1), str(rows))
    check("share_pct 给人看的百分数",
          (rows[0]["share_pct"], rows[1]["share_pct"]) == (83.33, 16.67), str(rows))
    check("带等级窗口的条目原样列出（预览不替它判断会不会进候选）",
          rows[1]["min_lv"] == 20 and any("等级窗口" in w for w in out["warnings"]),
          str(out["warnings"]))
    check("expanded_count/unique 与引擎直算一致",
          out["expanded_count"] == 6 and out["expanded_unique"] == 2, str(out))
    check("审计通过（无断链）", out["audit"]["ok"] is True, str(out["audit"]))
    check("★ 不装懂：一定有 resolver warning",
          any("resolver" in w for w in out["warnings"]), str(out["warnings"]))

    out = LV.build_file(FULL, "fixed_a")
    rows = out["entries"]
    check("fixed 列出全部条目、保持声明序",
          out["ok"] and [r["ref"] for r in rows] == ["mat_a", "mat_b"], str(rows))
    check("fixed 的 share / w 都是 null（占比不适用，不给假数）",
          all(r["share"] is None and r["share_pct"] is None and r["w"] is None for r in rows), str(rows))
    check("fixed 的 n 原样带回", rows[1]["n"] is None and rows[0]["n"] == 3, str(rows))

    out = LV.build_file(FULL, "choice_a")
    check("table_choice 预览成功且有 rolls 无 entries",
          out["ok"] and out["rolls"] and not out["entries"], str(out)[:160])
    r0, r1 = out["rolls"]
    check("rolls 列出 cutoff（互斥档）",
          (r0["cutoff"], r1["cutoff"]) == (0.25, 0.75), str(out["rolls"]))
    check("rolls 列出 n 区间与 fallback",
          r0["n"] == [1, 2] and r0["fallback"] == "mat_z" and r0["fallback_n"] is None, str(r0))
    check("子池被识别（is_sub_pool）并递归展开",
          r0["is_sub_pool"] is True and r1["is_sub_pool"] is True
          and r0["expanded_count"] == 2 and r0["expanded"] == ["mat_b", "mat_b"], str(r0))
    check("cutoff 累计 = 1.0 → 不给「累计不足」警告",
          not any("cutoff 累计" in w for w in out["warnings"]), str(out["warnings"]))
    check("★ expanded_count = 引擎对子池递归展开的和（2 + 2）",
          out["expanded_count"] == 4 and out["expanded_unique"] == 3, str(out))

    out = LV.build_file(FULL, "table_a")
    check("table 列出 chance 与子池展开",
          out["ok"] and out["rolls"][0]["chance"] == 0.3
          and out["rolls"][0]["expanded_count"] == 2, str(out["rolls"]))
    check("table 的 cutoff 是 None（别把两种语义混起来）",
          out["rolls"][0]["cutoff"] is None)

    # 与引擎直算逐项一致（「同一份代码」的证据，不是「看起来一样」）
    t = LootTable(FULL, resolver=None)
    same = True
    for k in ("weighted_a", "fixed_a", "table_a", "choice_a"):
        v = LV.build_file(FULL, k)
        if v["expanded_count"] != len(t.expand(k)) or v["expanded_unique"] != len(set(t.expand(k))):
            same = False
    check("★ 四个池的展开计数与引擎 LootTable 直算逐项一致", same)
    rep = LootTable(FULL, resolver=None).audit()
    check("引擎审计：这批数据本身是干净的（issues 为空）", rep["ok"] is True, str(rep["issues"]))


def t4_preview_bad_data():
    print("\n[4] 预览：坏数据 / 池不存在 → 明确原因，不假装有内容")
    cases = [
        ({"a": WEIGHTED}, "nope", "没有这条池"),
        ({"a": []}, "a", "不是对象"),
        ({"a": {"entries": [{"item": "x"}]}}, "a", "缺少 type"),
        ({"a": {"type": "weighted", "entries": "mat_a"}}, "a", "必须是条目数组"),
        ({"a": {"type": "weighted", "entries": [{"w": 1}]}}, "a", "缺 item"),
        ({"a": {"type": "weighted", "entries": [{"item": "mat_a", "w": 0}]}}, "a", "权重和"),
        ({"a": {"type": "table", "rolls": [{"chance": 0.5}]}}, "a", "缺 pool"),
        ({"a": {"type": "table", "rolls": "pool_a"}}, "a", "必须是数组"),
    ]
    for data, key, want in cases:
        out = LV.build_file(data, key)
        check(f"坏数据被拦（{want}）→ ok=False", out.get("ok") is False, str(out)[:120])
        check(f"  └ 原因里出现「{want}」", want in (out.get("error") or ""), str(out.get("error"))[:120])
    check("整表不是对象也被拦", LV.build_file(["x"], "a").get("ok") is False)
    out = LV.build_file({"a": {"type": "table", "rolls": [{"pool": "ghost"}]}}, "a")
    check("子池不存在 → 明确 warning（前缀/引用由内容侧注册，预览不猜）",
          out["ok"] and any("不在本域数据里" in w for w in out["warnings"]), str(out["warnings"]))
    check("子池不存在 → 引擎审计报「断链」（预览与引擎同判）",
          out["audit"]["ok"] is False and any(i["level"] == "断链" for i in out["audit"]["issues"]),
          str(out["audit"]))
    cyc = {"a": {"type": "table", "rolls": [{"pool": "b"}]},
           "b": {"type": "table", "rolls": [{"pool": "a"}]}}
    out = LV.build_file(cyc, "a")
    check("循环引用 → 报「坏数据」而不是崩（不是 500/RecursionError 外泄）",
          out.get("ok") is False and "循环引用" in (out.get("error") or ""), str(out)[:140])
    mixed = {"good_a": WEIGHTED, "broken_a": {"type": "fixed", "entries": [{"n": 1}]}}
    out = LV.build_file(mixed, "good_a")
    check("审计只报**本池**的问题（不把别的池的断链算到自己头上）",
          out["ok"] and out["audit"]["ok"] is True, str(out["audit"]))
    out = LV.build_file({"a": {"type": "fish_x", "entries": [{"item": "mat_a", "w": 1}]}}, "a")
    check("未注册的策略名 → 明确警告 + 按引擎兜底策略解析",
          out["ok"] and out["strategy_uses"] == "entries"
          and any("不在内置策略表里" in w for w in out["warnings"]), str(out["warnings"]))


def t5_schema_validation():
    print("\n[5] schema 校验：合法过、非法被拦")
    for name, v in (("weighted", WEIGHTED), ("fixed", FIXED), ("table", TABLE), ("table_choice", CHOICE)):
        check(f"{name} 合法条目通过校验", VD.validate_entry("drop_pools", v) == [],
              str(VD.validate_entry("drop_pools", v)))
    e1 = VD.validate_entry("drop_pools", {"entries": [{"item": "mat_a"}]})
    check("缺 type 被拦", any("type" in x for x in e1), str(e1))
    e2 = VD.validate_entry("drop_pools", {"type": "weighted", "entries": [{"w": 1}]})
    check("条目缺 item 被拦", any("item" in x for x in e2), str(e2))
    e3 = VD.validate_entry("drop_pools", {"type": "table", "rolls": [{"chance": 0.4}]})
    check("roll 缺 pool 被拦", any("pool" in x for x in e3), str(e3))
    e5 = VD.validate_entry("drop_pools", {"type": "table", "rolls": [{"pool": "p", "chance": 1.5}]})
    check("chance > 1 被拦", bool(e5), str(e5))
    check("自由策略名能过校验（不设枚举的证据）",
          VD.validate_entry("drop_pools", {"type": "whatever_content_registers"}) == [],
          str(VD.validate_entry("drop_pools", {"type": "whatever_content_registers"})))


def t6_http():
    print("\n[6] HTTP 端到端：编辑器 → 数据文件 → 引擎")
    gd = tempfile.mkdtemp(prefix="fw_editor_loot_")
    SRV.GAMES_DIR = gd
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), SRV.H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    st, j = req(base, "POST", "/api/packages", {"id": "loot_demo", "name": "掉落演示",
                                               "domains": ["drop_pools"]})
    check("建包（只勾 drop_pools 域）成功", st == 200 and j.get("ok"), f"{st} {j}")
    st, j = req(base, "GET", "/api/package/loot_demo/d/drop_pools")
    check("新建包的 drop_pools 域可列（空表）", st == 200 and j.get("count") == 0, f"{st} {j}")
    st, j = req(base, "GET", "/api/schema/drop_pools")
    check("GET /api/schema/drop_pools 有 schema", st == 200 and j.get("ok") and j.get("schema"), f"{st}")

    for k, v in FULL.items():
        st, j = req(base, "PUT", f"/api/package/loot_demo/d/drop_pools/{k}", {"data": v})
        check(f"PUT {k}（{v['type']}）落盘成功", st == 200 and j.get("ok"), f"{st} {j}")
    st, j = req(base, "GET", "/api/package/loot_demo/d/drop_pools")
    check(f"列表 6 条", st == 200 and j.get("count") == len(FULL), f"{st} {j}")

    st, j = req(base, "GET", "/api/package/loot_demo/d/drop_pools/weighted_a/preview")
    check("GET preview（weighted）200", st == 200 and j.get("ok"), f"{st} {j}")
    check("★ 端到端占比 = 权重 ÷ 权重和（5/6）",
          j.get("entries", [{}])[0].get("share") == round(5 / 6, 4), str(j.get("entries"))[:160])
    check("★ 端到端展开计数 = 引擎 expand（6 / 2）",
          j.get("expanded_count") == 6 and j.get("expanded_unique") == 2, str(j)[:160])
    check("端到端带 resolver warning + 审计通过",
          any("resolver" in w for w in (j.get("warnings") or []))
          and (j.get("audit") or {}).get("ok") is True, str(j.get("warnings")))

    st, j = req(base, "GET", "/api/package/loot_demo/d/drop_pools/fixed_a/preview")
    check("preview（fixed）列出条目且 share=null",
          st == 200 and j.get("ok") and [e["ref"] for e in j["entries"]] == ["mat_a", "mat_b"]
          and j["entries"][0]["share"] is None, f"{st} {str(j)[:160]}")

    st, j = req(base, "GET", "/api/package/loot_demo/d/drop_pools/table_a/preview")
    check("preview（table）列出 chance + 子池展开",
          st == 200 and j["rolls"][0]["chance"] == 0.3 and j["rolls"][0]["expanded_count"] == 2,
          f"{st} {str(j)[:160]}")

    st, j = req(base, "GET", "/api/package/loot_demo/d/drop_pools/choice_a/preview")
    check("preview（table_choice）列出 cutoff",
          st == 200 and [r["cutoff"] for r in j["rolls"]] == [0.25, 0.75], f"{st} {str(j)[:160]}")

    st, j = req(base, "GET", "/api/package/loot_demo/d/drop_pools/ghost/preview")
    check("不存在的池 → 422 + 中文原因", st == 422 and "没有这条池" in (j.get("error") or ""), f"{st} {j}")
    check("不存在的池 → 不假装有内容（无 entries/rolls）",
          not j.get("ok") and not j.get("entries") and not j.get("rolls"), str(j)[:120])
    st, j = req(base, "GET", "/api/package/loot_demo/d/maps/nope/preview")
    check("预览只服务 drop_pools（别的域 → 404）", st == 404, f"{st} {j}")
    st, j = req(base, "GET", "/api/package/loot_demo/d/nosuchdom/x/preview")
    check("未知域 → 404", st == 404, f"{st} {j}")
    st, j = req(base, "GET", "/api/package/nope/d/drop_pools/weighted_a/preview")
    check("包不存在 → 404", st == 404, f"{st} {j}")

    # 非法条目必须被**校验拦住**（不是落盘后再崩）
    st, j = req(base, "PUT", "/api/package/loot_demo/d/drop_pools/bad_one",
                {"data": {"type": "weighted", "entries": [{"w": 3}]}})
    check("非法条目 PUT 被拦（4xx）", st >= 400, f"{st} {j}")
    st, j = req(base, "PUT", "/api/package/loot_demo/d/drop_pools/bad_two",
                {"data": {"type": "table", "rolls": [{"chance": 0.2}]}})
    check("roll 缺 pool 的条目 PUT 被拦（4xx）", st >= 400, f"{st} {j}")
    st, j = req(base, "GET", "/api/package/loot_demo/d/drop_pools")
    check("被拦的条目没落盘（仍是 6 条）", j.get("count") == len(FULL), f"{st} {j}")

    st, j = req(base, "GET", "/api/domains")
    check("域列表里有 drop_pools（前端 tab 的依据）",
          any(d.get("id") == "drop_pools" for d in (j.get("domains") or [])), f"{st}")
    st, j = req(base, "GET", "/api/glossary")
    check("词典接口含 drop_pools 域", st == 200 and "drop_pools" in (j.get("domains") or {}), f"{st}")
    check("分组接口含 drop_pools 域", "drop_pools" in (j.get("groups") or {}),
          str(list(j.get("groups") or {}))[:120])
    st, j = req(base, "GET", "/api/package/loot_demo")
    check("包概览里 drop_pools 域条目数正确（6）",
          st == 200 and any(d.get("id") == "drop_pools" and d.get("count") == len(FULL)
                            for d in (j.get("domains") or [])), str(j.get("domains"))[:200])
    httpd.shutdown()


def main():
    print("== drop_pools 域（随机产出形状）编辑器门禁 ==")
    t1_domain()
    t2_glossary()
    t3_preview_shapes()
    t4_preview_bad_data()
    t5_schema_validation()
    t6_http()
    print(f"\n===== 结果：通过 {PASS} / {PASS + FAIL} =====")
    for f in FAILURES:
        print("  ❌", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
