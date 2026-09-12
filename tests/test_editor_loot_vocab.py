# -*- coding: utf-8 -*-
"""掉落池「包内引用词汇声明」门禁（`content/rules/loot_vocab.json`）。

守三条：
  ① **声明起作用**：真包（596 池）带声明时，编辑器审计 **0 断链**（并且走 HTTP 端点也一样）；
     不声明时与**加这功能之前**逐格一致（= 引擎 `LootTable(pools, resolver=None).audit()` 的口径）。
  ② **零知识**：框架不认识任何具体前缀/池名 —— 它只是把包内声明机械地转给引擎
     （用一条框架从没见过的假前缀 `zzz:` 验证：声明了就不报，没声明就报）。
  ③ **坏声明不崩**：文件缺失 / 不是 JSON / 顶层不是对象 / 值类型不对 / 域不认识
     → 一律降级成「没声明」（与旧行为逐值相同），绝不 500、绝不抛。

跑法：python tests/test_editor_loot_vocab.py
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from editor import loot_view as LV           # noqa: E402
from editor import packages as PK            # noqa: E402
from editor import server as SRV             # noqa: E402
from editor import validate as VD            # noqa: E402
from saintess_engine.loot import LootTable   # noqa: E402

REAL_PKG = os.path.join(ROOT, "games", "orlandia")
POOLS_REL = os.path.join("content", "data", "drop_pools.json")
VOCAB_REL = os.path.join("content", "rules", "loot_vocab.json")
EQUIP_POOL = "boss:inst_abyss_gate"     # 该池有 1 条 `equip:eq_*` 抽行（无声明时必报断链）

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
        with urllib.request.urlopen(r, timeout=120) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw}


def _real_data() -> dict:
    with open(os.path.join(REAL_PKG, POOLS_REL), encoding="utf-8") as f:
        return json.load(f)


def _tmp_pkg(pools: dict, vocab=None, raw_vocab_text=None, name="pkg") -> str:
    """造一个临时包：只放 drop_pools.json（可选放词汇声明表，或直接写一段原始文本）。

    声明表形状 = `{"drop_pools": {…}}`（一条 = 一个域）；`vocab` 传的是**内层**声明对象。
    """
    d = tempfile.mkdtemp(prefix="fw_loot_vocab_")
    root = os.path.join(d, name)
    os.makedirs(os.path.join(root, "content", "data"))
    os.makedirs(os.path.join(root, "content", "rules"))
    with open(os.path.join(root, "game.json"), "w", encoding="utf-8") as f:
        json.dump({"id": name, "name": name, "engine": ">=0.1", "domains": ["drop_pools"]}, f)
    with open(os.path.join(root, POOLS_REL), "w", encoding="utf-8") as f:
        json.dump(pools, f, ensure_ascii=False)
    if raw_vocab_text is not None:
        with open(os.path.join(root, VOCAB_REL), "w", encoding="utf-8") as f:
            f.write(raw_vocab_text)
    elif vocab is not None:
        with open(os.path.join(root, VOCAB_REL), "w", encoding="utf-8") as f:
            json.dump({"drop_pools": vocab}, f, ensure_ascii=False, indent=2)
    return root


def _baseline(pools: dict) -> int:
    """加这功能之前的编辑器口径：引擎默认（什么声明都没有）。"""
    return len(LootTable(pools, resolver=None).audit()["issues"])


# ────────────────────────── [1] 真包：175 → 0
def t1_real_package():
    print("\n[1] 真包：带包内声明 → 审计 0 断链（不声明 = 旧口径）")
    data = _real_data()
    strict_v = LV.load_vocab(REAL_PKG)
    check("真包有词汇声明且被读到（declared=True）", strict_v["declared"] is True, str(strict_v)[:200])
    check("声明里的 ref_domains 落地成包内主键集（900 条 items）",
          strict_v["ref_domains"] == ("items",) and len(strict_v["ref_keys"]) == 900,
          f"{strict_v['ref_domains']} / {len(strict_v['ref_keys'])}")

    base = LV.audit_file(data)                       # 不声明
    after = LV.audit_file(data, strict_v)            # 带声明
    check(f"★ 不声明 = 旧口径（{base['issue_count']} 处，与引擎默认逐值同）",
          base["issue_count"] == _baseline(data) and base["vocab_declared"] is False,
          f"{base['issue_count']} vs {_baseline(data)}")
    check("★ 带声明 = 0 断链", after["issue_count"] == 0 and after["ok"] is True and after["by_kind"] == {},
          str(after)[:200])
    check("池数 / 条目数与之前一致（596 / 1435）",
          after["pool_count"] == 596 and after["entry_count"] == 1435 and base["pool_count"] == 596,
          f"{after['pool_count']}/{after['entry_count']}")
    print(f"      （真包审计：不声明 {base['issue_count']} 处 / 79 池 → 带声明 {after['issue_count']} 处）")

    # 单条预览：有 `equip:` 抽行的池是最容易看出效果的一例
    p_after = LV.build_file(data, EQUIP_POOL, strict_v)
    p_before = LV.build_file(data, EQUIP_POOL)
    check("★ 单条预览：带声明 audit.ok=True；不带 = 断链",
          p_after["audit"]["ok"] is True and p_before["audit"]["ok"] is False
          and any(i["level"] == "断链" for i in p_before["audit"]["issues"]),
          str(p_before["audit"]["issues"])[:200])
    check("预览回报「本包声明了词汇」（前端可据此说明）",
          p_after.get("vocab_declared") is True and p_before.get("vocab_declared") is False, "")
    check("声明过的外部引用在预览里不再被说成断链",
          any("是包内声明过的引用" in w for w in p_after["warnings"]), str(p_after["warnings"])[:200])
    check("没声明的包照旧给「需要内容侧 resolver」warning",
          any("resolver" in w for w in p_before["warnings"]), str(p_before["warnings"])[:160])


# ────────────────────────── [2] 零知识：框架照着声明机械执行
def t2_zero_knowledge():
    print("\n[2] 零知识：一条框架从没见过的假前缀也能被声明（框架不认识它的含义）")
    pools = {"p1": {"type": "table", "rolls": [{"pool": "zzz:whatever", "chance": 1.0}]}}
    seen = LV.audit_file(pools)
    with_decl = LV.audit_file(pools, {"inline_prefixes": ["zzz:"], "ref_domains": ["items"]})
    check("不声明 → 报断链（旧行为）", seen["issue_count"] == 1 and seen["by_kind"] == {"断链": 1},
          str(seen)[:160])
    check("包声明了 `zzz:` → 不报（框架只转发，不解释）", with_decl["issue_count"] == 0, str(with_decl)[:160])
    check("声明文件只认通用键（不认识的值照收，未知键忽略）",
          LV.normalize_vocab({"inline_prefixes": "zzz:", "whatever_key": [1, 2]})["inline_prefixes"] == ("zzz:",)
          and LV.normalize_vocab({"whatever_key": [1, 2]})["declared"] is False, "")
    check("框架源码里没有具体游戏词汇（本门禁自身不在扫描范围）: 只查通用常量名",
          "loot_vocab.json" in PK.domain_path(".", LV.VOCAB_DOMAIN).replace(os.sep, "/") and LV.VOCAB_KEYS[0] == "inline_prefixes", "")

    # 声明表是**框架域**（注册 + schema + 真包那条过校验 + 编辑器通用接口读得到）
    meta = PK.DOMAINS.get("loot_vocab") or {}
    entry = PK.get_entry(REAL_PKG, "loot_vocab", "drop_pools")
    check("声明表域 loot_vocab 已注册且 kind=rules", meta.get("kind") == "rules", str(meta))
    check("声明表落 content/rules/（kind 决定的路径，不硬编码）",
          PK.domain_path("pkg", "loot_vocab").replace(os.sep, "/").endswith("content/rules/loot_vocab.json"),
          PK.domain_path("pkg", "loot_vocab"))
    check("真包声明表能被编辑器通用接口读到（get_entry）",
          isinstance(entry, dict) and "inline_prefixes" in entry, str(entry)[:140])
    check("声明表域**故意**无 schema（内容侧取值不该长出框架词汇表）→ 通用校验给空集",
          (PK.DOMAINS.get("loot_vocab") or {}).get("schema") is None
          and VD.validate_entry("loot_vocab", entry or {}) == [],
          f"{meta.get('schema')!r} {VD.validate_entry('loot_vocab', entry or {})[:2]}")
    check("声明表在包的 domains 清单里（分发/概览都靠它）",
          "loot_vocab" in (PK.load_manifest(REAL_PKG).get("domains") or []),
          str(PK.load_manifest(REAL_PKG).get("domains")))


# ────────────────────────── [3] 坏声明 → 降级（与旧行为逐值相同）
def t3_bad_declarations():
    print("\n[3] 坏声明 / 缺声明 → 不崩，降级成旧行为（逐值相同）")
    data = _real_data()
    base = LV.audit_file(data)
    base_build = LV.build_file(data, EQUIP_POOL)
    cases = [
        ("缺文件", None, None),
        ("不是 JSON（'{'）", None, "{"),
        ("顶层是数组（[1,2]）", None, "[1, 2]"),
        ("声明表里没有本域那条（只有别的域）", None, '{"instances": {"inline_prefixes": ["x:"]}}'),
        ("值是错的类型", {"inline_prefixes": 3, "special_refs": {"a": 1}, "pool_key_prefixes": None}, None),
        ("列表里混了非字符串", {"inline_prefixes": [1, None, {"x": 1}]}, None),
        ("只写了未知键", {"whatever": 1, "version": 9}, None),
        ("ref_domains 指向不认识的域", {"ref_domains": ["nosuch_domain"]}, None),
        ("ref_domains 是字符串不是数组", {"ref_domains": "items"}, None),
    ]
    for label, vocab, raw in cases:
        root = _tmp_pkg(data, vocab=vocab, raw_vocab_text=raw)
        try:
            v = LV.load_vocab(root)                 # ← 不许抛
            rep = LV.audit_file(data, v)
            ok_same = (rep["issue_count"] == base["issue_count"] and rep["pool_count"] == base["pool_count"])
            b = LV.build_file(data, EQUIP_POOL, v)
            ok_build = (b["ok"] is True and b["audit"]["ok"] == base_build["audit"]["ok"]
                        and b.get("vocab_declared") is False)
            check(f"{label} → 降级成空声明且与旧行为一致", v["declared"] is False and ok_same and ok_build,
                  f"declared={v['declared']} {rep['issue_count']} vs {base['issue_count']}")
        except Exception as e:                      # noqa: BLE001
            check(f"{label} → 不许抛异常", False, f"{type(e).__name__}: {e}")
        finally:
            shutil.rmtree(os.path.dirname(root), ignore_errors=True)

    # 半份声明（合法但不全）：允许 —— 只是不崩，绝不假报「全绿」
    root = _tmp_pkg(data, vocab={"inline_prefixes": ["gold:"], "ref_domains": ["nosuch_domain"]})
    try:
        v = LV.load_vocab(root)
        rep = LV.audit_file(data, v)
        check("半份声明不崩、且不假装 0 断链",
              v["declared"] is True and rep["issue_count"] > 0 and rep["ok"] is False,
              str(rep)[:160])
    finally:
        shutil.rmtree(os.path.dirname(root), ignore_errors=True)


# ────────────────────────── [4] HTTP 端到端
def t4_http():
    print("\n[4] HTTP 端到端：域级审计端点 + 预览端点（真包 vs 无声明临时包）")
    gd = tempfile.mkdtemp(prefix="fw_loot_vocab_gd_")
    # 真包（含声明）以符号/拷贝方式放进临时 GAMES_DIR：用拷贝，避免动到框架仓
    real_copy = os.path.join(gd, "orlandia")
    shutil.copytree(REAL_PKG, real_copy)
    bare = _tmp_pkg(_real_data(), name="orlandia_bare")   # 同一份数据，**没有**声明文件
    shutil.move(bare, os.path.join(gd, "orlandia_bare"))

    SRV.GAMES_DIR = gd
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), SRV.H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        st, j = req(base, "GET", "/api/package/orlandia/loot/audit")
        check("★ GET /api/package/orlandia/loot/audit → 200 / 0 断链 / 596 池",
              st == 200 and j.get("ok") is True and j.get("issue_count") == 0
              and j.get("pool_count") == 596 and j.get("vocab_declared") is True, f"{st} {str(j)[:200]}")

        st, j = req(base, "GET", f"/api/package/orlandia/d/drop_pools/{EQUIP_POOL}/preview")
        check("★ 预览（含 equip: 抽行的池）→ 200 且 audit.ok",
              st == 200 and j.get("ok") and j.get("audit", {}).get("ok") is True, f"{st} {str(j)[:200]}")

        st, j = req(base, "GET", "/api/package/orlandia_bare/loot/audit")
        check("无声明包：审计端点 → 422（就是现在那批断链）",
              st == 422 and j.get("issue_count", 0) > 0 and j.get("vocab_declared") is False,
              f"{st} {str(j)[:160]}")

        st, j = req(base, "GET", f"/api/package/orlandia_bare/d/drop_pools/{EQUIP_POOL}/preview")
        check("无声明包：预览照旧报断链（行为与现在一致）",
              st == 200 and j.get("ok") and j.get("audit", {}).get("ok") is False, f"{st} {str(j)[:200]}")

        st, j = req(base, "GET", "/api/package/nope/loot/audit")
        check("包不存在 → 404", st == 404, f"{st} {j}")
    finally:
        httpd.shutdown()
        shutil.rmtree(gd, ignore_errors=True)


# ────────────────────────── [5] 声明不该顺手改掉的东西
def t5_no_side_effects():
    print("\n[5] 声明只影响「引用判定」：权重/展开/池数据一律不动")
    data = _real_data()
    v = LV.load_vocab(REAL_PKG)
    pairs = [("weighted 型池", "mon:丘陵狼"), ("table 型池", "chest:high"), ("fixed 型池", "elite:丘陵狼王·铁牙")]
    for label, key in pairs:
        a = LV.build_file(data, key)
        b = LV.build_file(data, key, v)
        same_entries = a.get("entries") == b.get("entries")
        same_rolls = [(r["pool"], r["chance"], r["cutoff"]) for r in a.get("rolls") or []] == \
                     [(r["pool"], r["chance"], r["cutoff"]) for r in b.get("rolls") or []]
        check(f"{label} 的条目/抽行逐值不变（只有审计判定变）", same_entries and same_rolls, f"{key}")
    check("声明不改引擎判定：`equip:` 在引擎内仍不是 inline 前缀（框架用 resolvable 单独处理）",
          "equip:" not in v["inline_prefixes"] and "equip:" in v["external_prefixes"], str(v)[:160])
    a = LV.build_file(data, EQUIP_POOL)
    b = LV.build_file(data, EQUIP_POOL, v)
    check("`external_prefixes` 只影响判定、**不**混进展开外列（该池展开数不变）",
          a["expanded_count"] == b["expanded_count"] and a["expanded_unique"] == b["expanded_unique"],
          f"{a['expanded_count']} vs {b['expanded_count']}")
    c = LV.build_file(data, "chest:high")
    d = LV.build_file(data, "chest:high", v)
    check("声明过的 inline 前缀按引擎语义参与展开外列（chest:high 变多，是**有意**的）",
          d["expanded_count"] > c["expanded_count"],
          f"{c['expanded_count']} -> {d['expanded_count']}")


def main():
    print("== 掉落池「包内引用词汇声明」门禁 ==")
    if not os.path.exists(os.path.join(REAL_PKG, POOLS_REL)):
        print(f"❌ 真包不在：{REAL_PKG}")
        return 1
    t1_real_package()
    t2_zero_knowledge()
    t3_bad_declarations()
    t4_http()
    t5_no_side_effects()
    print(f"\n===== 结果：通过 {PASS} / {PASS + FAIL} =====")
    for f in FAILURES:
        print("  ❌", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
