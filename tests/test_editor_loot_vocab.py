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
import _domain_fixtures as FX                # noqa: E402  （内容域只能由包声明：B2b）
from ext_loot.loot import LootTable   # noqa: E402

REAL_PKG = os.path.join(ROOT, "games", "orlandia")
POOLS_REL = os.path.join("content", "data", "drop_pools.json")
VOCAB_REL = os.path.join("content", "rules", "loot_vocab.json")
EQUIP_POOL = "boss:inst_abyss_gate"     # 该池有 1 条 `equip:eq_*` 抽行（无声明时必报断链）

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
    # ★ B2b：`loot_vocab` / `items` / `equip_roster` 都是**内容域**（框架内置集只留引擎域）
    #   → 声明表与引用目标域都要由包自己声明，`domain_path()` 才认得（真源在包）。
    FX.declare(root, "loot_vocab", "items", "equip_roster", "drop_pools")
    with open(os.path.join(root, "game.json"), "w", encoding="utf-8") as f:
        json.dump({"id": name, "name": name, "engine": ">=0.1",
                   "domains": ["drop_pools", "loot_vocab", "items", "equip_roster"]}, f)
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
    # ★ B2b：`loot_vocab` 是**内容域**（引擎侧零消费端：只被 editor/loot_view.py:load_vocab()
    #   读，取值全是内容词汇）→ 从框架内置集**移出**，改由内容包声明（真源在包）。
    check("框架侧只留通用常量名（域名/键名），不认识任何取值",
          LV.VOCAB_DOMAIN == "loot_vocab" and LV.VOCAB_KEYS[0] == "inline_prefixes"
          and "loot_vocab" not in PK.DOMAINS,
          f"{LV.VOCAB_DOMAIN} / {sorted(PK.DOMAINS)}")

    # 声明表由**内容包**声明（真包 orlandia 的 editor/domains.json）+ 真包那条过校验 + 通用接口读得到
    meta = FX.meta_of("loot_vocab")
    entry = PK.get_entry(REAL_PKG, "loot_vocab", "drop_pools")
    check("声明表域 loot_vocab 由内容包声明且 kind=rules（框架内置集里没有它）",
          meta.get("kind") == "rules" and "loot_vocab" in PK.effective_domains(REAL_PKG)[0]
          and PK.domain_source(REAL_PKG, "loot_vocab") == "package", str(meta))
    check("声明表落 content/rules/（kind 决定的路径，不硬编码）",
          PK.domain_path(REAL_PKG, "loot_vocab").replace(os.sep, "/").endswith("content/rules/loot_vocab.json"),
          PK.domain_path(REAL_PKG, "loot_vocab"))
    check("真包声明表能被编辑器通用接口读到（get_entry）",
          isinstance(entry, dict) and "inline_prefixes" in entry, str(entry)[:140])
    check("声明表域**故意**无 schema（内容侧取值不该长出框架词汇表）→ 通用校验给空集",
          meta.get("schema") is None
          and VD.validate_entry("loot_vocab", entry or {}, REAL_PKG) == [],
          f"{meta.get('schema')!r} {VD.validate_entry('loot_vocab', entry or {}, REAL_PKG)[:2]}")
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
    check("声明不改引擎判定：`equip:` 仍不是 inline 前缀（不参与展开外列），而改走「前缀→域」**真判**",
          "equip:" not in v["inline_prefixes"]
          and v["ref_prefix_domains"].get("equip:") == "equip_roster"
          and "equip:" not in v["external_prefixes"], str(v)[:160])
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


def t6_prefix_domains():
    """`ref_prefix_domains`：带前缀的引用也能**真判**（剥前缀查那个域的主键）。

    这一节的核心是「收紧」：`external_prefixes` 只能说「别喊断链」，而这一条能说
    「这条引用对不上名册就是错的」。同时守三条纪律：只声明 external 时行为与旧版逐值相同、
    域名不认识时该前缀当没说（不制造假红）、`load_vocab()` 的结果再进 `audit_file()` 不掉语义。
    """
    print("\n-- 6. 前缀→域（ref_prefix_domains）：带前缀的引用也真判 --")
    pools = {"p1": {"type": "weighted", "entries": [
        {"item": "equip:eq_in", "weight": 1},       # 名册里有
        {"item": "equip:eq_out", "weight": 1},      # 名册里没有 → 真断链（收紧的意义所在）
        {"item": "raw_in", "weight": 1},            # 裸 ref → 由 ref_domains 判
    ]}}
    d = tempfile.mkdtemp(prefix="fw_loot_prefix_")
    root = os.path.join(d, "pkg")
    os.makedirs(os.path.join(root, "content", "data"))
    os.makedirs(os.path.join(root, "content", "rules"))
    # ★ B2b：同上 —— equip_roster / items / loot_vocab 是内容域，由包声明（真源在包）
    FX.declare(root, "loot_vocab", "equip_roster", "items", "drop_pools")
    with open(os.path.join(root, "game.json"), "w", encoding="utf-8") as f:
        json.dump({"id": "pkg", "name": "pkg", "engine": ">=0.1",
                   "domains": ["drop_pools", "equip_roster", "items", "loot_vocab"]}, f)
    with open(os.path.join(root, "content", "data", "equip_roster.json"), "w", encoding="utf-8") as f:
        json.dump({"eq_in": {"name": "在册"}, "other": {"name": "别的"}}, f, ensure_ascii=False)
    with open(os.path.join(root, "content", "data", "items.json"), "w", encoding="utf-8") as f:
        json.dump({"raw_in": {"name": "裸引用在 items 里"}}, f, ensure_ascii=False)
    with open(os.path.join(root, POOLS_REL), "w", encoding="utf-8") as f:
        json.dump(pools, f, ensure_ascii=False)

    def declare(obj):
        with open(os.path.join(root, VOCAB_REL), "w", encoding="utf-8") as f:
            json.dump({"drop_pools": obj}, f, ensure_ascii=False)

    def msgs(rep):
        return [i["message"] for i in (rep.get("issues") or [])]

    # ① 只声明「前缀→域」：在册的不报、不在册的**必须报**（这就是比 external 严的地方）
    declare({"version": 1, "ref_prefix_domains": {"equip:": "equip_roster"}})
    v = LV.load_vocab(root)                      # 真调用形状：load_vocab → audit_file（幂等）
    rep = LV.audit_file(pools, v)
    check("声明前缀→域后：在册的解得开、不在册的报断链（一共只报 1 条）",
          rep["issue_count"] == 1 and "equip:eq_out" in msgs(rep)[0],
          f"{rep['issue_count']} {msgs(rep)}")
    check("裸 ref 未被牵连（没声明 ref_domains 时它照旧不判）",
          "raw_in" not in " ".join(msgs(rep)), msgs(rep))

    # ② 只声明 external_prefixes → 旧行为：该前缀一律不问（连不在册的也不报）
    declare({"version": 1, "external_prefixes": ["equip:"]})
    rep = LV.audit_file(pools, LV.load_vocab(root))
    check("只声明 external_prefixes 时与旧版逐值一致（该前缀下一条都不报）",
          not any("equip:" in m for m in msgs(rep)), msgs(rep))

    # ③ 同一前缀两处都声明 → 更严的那句说了算（external 不能把收紧的话盖掉）
    declare({"version": 1, "external_prefixes": ["equip:"],
             "ref_prefix_domains": {"equip:": "equip_roster"}})
    rep = LV.audit_file(pools, LV.load_vocab(root))
    check("同一前缀 external + 前缀→域 并存 → 以更严的为准（仍报 1 条）",
          rep["issue_count"] == 1 and "equip:eq_out" in msgs(rep)[0], msgs(rep))

    # ④ 域名不认识 / 表不在包里 → 该前缀当没说：绝不把整族引用判成断链（假红）
    declare({"version": 1, "ref_prefix_domains": {"equip:": "no_such_domain"}})
    v = LV.load_vocab(root)
    rep = LV.audit_file(pools, v)
    check("域名不认识 → 声明降级成「没说」（declared=False 且 0 断链）",
          v["declared"] is False and rep["issue_count"] == 0, f"{v['declared']} {msgs(rep)}")

    # ⑤ 多个前缀命中时长的先比（`equip:eq_in` 不该被 `equip:` 抢走）
    declare({"version": 1, "ref_prefix_domains": {"equip:": "equip_roster", "equip:eq_in": "items"}})
    rep = LV.audit_file(pools, LV.load_vocab(root))
    check("长前缀优先：`equip:eq_in` 按 items 判（items 里没有 → 报）",
          any("equip:eq_in" in m for m in msgs(rep)), msgs(rep))

    # ⑥ 幂等：归一过的形状再归一次不丢「前缀→域」（丢了 = 服务端把整族引用全报断链）
    declare({"version": 1, "ref_prefix_domains": {"equip:": "equip_roster"}})
    v1 = LV.load_vocab(root)
    v2 = LV.normalize_vocab(v1)                  # 不带 pkg_dir 再归一次
    check("幂等：normalize 过的声明再 normalize 仍保留前缀→域（不带 pkg_dir 也不丢）",
          dict(v2["ref_prefix_keys"]) == dict(v1["ref_prefix_keys"]) and v2["declared"],
          f"{v1['ref_prefix_keys']} -> {v2['ref_prefix_keys']}")

    # ⑦ 预览侧：被「前缀→域」解释过的引用，不再补一句「要内容侧 resolver」
    declare({"version": 1, "ref_prefix_domains": {"equip:": "equip_roster"}})
    prev = LV.build_file(pools, "p1", LV.load_vocab(root))
    check("预览不为已声明的前缀引用补「需要内容侧 resolver」这句",
          not any("resolver" in w for w in (prev.get("warnings") or [])), prev.get("warnings"))

    # ⑧ 外列语义不变：前缀→域 也**不**参与 expand 外列（不猜权重）
    declare({"version": 1, "ref_prefix_domains": {"equip:": "equip_roster"}})
    a = LV.build_file(pools, "p1")
    b = LV.build_file(pools, "p1", LV.load_vocab(root))
    check("前缀→域 不改变展开数（只影响审计判定）",
          a["expanded_count"] == b["expanded_count"] and a["expanded_unique"] == b["expanded_unique"],
          f"{a['expanded_count']} vs {b['expanded_count']}")

    # ⑨ 内联前缀 + 「前缀→域」：内联引用默认「内容侧自管、不判」，但两者同时声明时**照判**
    #    （引擎侧靠回调上的 `judged_inline_prefixes` 开启例外；entries 与 roll 行两条路径都要生效）
    pools2 = {"p2": {"type": "table", "rolls": [{"pool": "tok:raw_in"}, {"pool": "tok:__nope__"}]},
              "p3": {"type": "weighted", "entries": [{"item": "tok:raw_in", "weight": 1},
                                                     {"item": "tok:__nope__", "weight": 1}]}}
    declare({"version": 1, "inline_prefixes": ["tok:"], "ref_prefix_domains": {"tok:": "items"}})
    vv = LV.load_vocab(root)
    rsv = LV._make_resolvable(vv)
    check("回调上挂出了「要判的内联前缀」（引擎靠它开例外）",
          getattr(rsv, "judged_inline_prefixes", None) == ("tok:",),
          str(getattr(rsv, "judged_inline_prefixes", None)))
    msgs2 = [i["message"] for i in LV.audit_file(pools2, vv)["issues"]]
    check("内联前缀 + 前缀→域：坏值被抓住（entries 1 条 + roll 行 1 条）",
          sum("tok:__nope__" in m for m in msgs2) == 2, str(msgs2))
    check("内联前缀 + 前缀→域：好值不报（`raw_in` 在 items 表里）",
          not any("tok:raw_in" in m for m in msgs2), str(msgs2))

    # ⑩ 只声明 inline、没有域映射 → 内联引用照旧跳过（对既有包零影响）
    declare({"version": 1, "inline_prefixes": ["tok:"]})
    msgs3 = [i["message"] for i in LV.audit_file(pools2, LV.load_vocab(root))["issues"]]
    check("只声明 inline 没有域映射 → 内联引用照旧不判（零影响）", not msgs3, str(msgs3))
    shutil.rmtree(d, ignore_errors=True)


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
    t6_prefix_domains()
    print(f"\n===== 结果：通过 {PASS} / {PASS + FAIL} =====")
    for f in FAILURES:
        print("  ❌", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
