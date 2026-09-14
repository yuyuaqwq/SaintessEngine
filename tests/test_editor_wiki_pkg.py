# -*- coding: utf-8 -*-
"""包自带 wiki（`<pkg>/docs/wiki/**.md`）门禁：**包优先 / 框架兜底 / 零回归逐项**。

守的底线
--------
1. **包优先**：包内页进得了左导航（tree）、渲染得出正文（page）、搜得到（search）；
   **同名页（相对路径相同）以包内那份为准**，框架那份不再参与。
2. **框架兜底**：包内没有的页回退框架页（内容与不给包时**逐项相同**）；两边都没有 =
   照旧 `None` / 404，**绝不 500**；路径逃逸（`../`）read 不出来。
3. **零回归（硬约束）**：包**没有** `docs/wiki/` 时，`tree / page / search / code_ref`
   与词典面（`wiki_path / ref_url / all_entries`）的输出与「不给包」**逐字节一致**
   —— 本文件既做逐项比对，也做 JSON 落盘 sha256 比对，HTTP 那层比对**原始字节**。
4. **深链不撒谎**：包词汇表 `wiki: [页, 词]` 的「词」必须真出现在**解析到的**（包优先）
   那页正文里 —— 沿用 `tests/test_editor_glossary.py` 的既有纪律，并在这里做反证。
5. **接口面**：4 条 wiki 路由都认 `?pkg=`；不认得的包 id → 404（不是 500）。

跑法：python tests/test_editor_wiki_pkg.py
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from editor import glossary as GL       # noqa: E402
from editor import packages as PK       # noqa: E402
from editor import server as SRV        # noqa: E402
from editor import wiki as W            # noqa: E402
import _domain_fixtures as FX           # noqa: E402

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


# ─────────────────────────────────────────────────────────────── 夹具
PKG_WIKI = "pkg_wiki"            # 自带 docs/wiki
PKG_PLAIN = "pkg_plain"          # **没有** docs/wiki（零回归对拍用）
PAGE = "例子.md"                 # 包内独有页
SHADOW = "reference/effect-rules.md"   # 与框架**同名** → 包内那份胜
BACK = "concepts/actor-model.md"       # 包内没有 → 框架兜底页
TERM = "包内独有词条"             # 只在包内页里
SHADOW_TERM = "包内覆盖标记"      # 只在**包内**那份同名页里
FW_TERM = "actor"                # 只在框架兜底页里

PAGE_MD = f"""# 包内示例页：例子

这一页只存在于**游戏包**里（`<包>/docs/wiki/{PAGE}`）。

包内独有词条就在这一行 —— 字段深链的 `#find=` 指的必须是它。
"""

SHADOW_MD = f"""# 包内的 `EFFECT_RULES` 参考（覆盖框架那份）

包内覆盖标记：相对路径与框架页同名时，渲染的是这一份。
"""

ACTIONS_PY = "\n".join([
    "# 包内机制动作（示例）",
    "from saintess_engine import register_action",
    "包内动作在第三行",                       # ← code_ref 要指向这一行
    "",
    "@register_action('包内示例')",
    "def 包内示例(battle, actor, params):",
    "    return None",
])


def make_pkg(root, pid, *, wiki_files=None, glossary=None):
    """最小包：manifest + 域声明（skills 是内容域，只能由包声明）+ 可选 docs/wiki 与词汇表。"""
    pkg = os.path.join(root, pid)
    os.makedirs(os.path.join(pkg, "content", "data"), exist_ok=True)
    decl = FX.declare(None, "skills")
    PK.save_manifest(pkg, {"id": pid, "name": pid, "desc": "包内 wiki 门禁", "engine": ">=0.1",
                           "domains": list(PK.DOMAINS) + list(decl)})
    FX.declare(pkg, "skills")
    for rel, text in (wiki_files or {}).items():
        p = os.path.join(pkg, "docs", "wiki", *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    for dom, obj in (glossary or {}).items():
        p = os.path.join(pkg, "editor", "glossary", f"{dom}.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.write("\n")
    return pkg


def deep_link_problems(pkg_dir) -> list:
    """包词汇表里每条 `wiki: [页, 词]` 自检：按「包优先、框架兜底」解析后，词必须在正文里。

    与 `tests/test_editor_glossary.py` 对框架词典的那条判据同口径（**门禁在测试侧**，
    `ref_url` 只负责按解析顺序出链 / 不出链）。
    """
    bad = []
    for dom, t in GL.package_glossary(pkg_dir).items():
        for field, e in (t.get("fields") or {}).items():
            wiki = e.get("wiki")
            if not wiki:
                continue
            page, term = wiki
            where = f"{dom}.{field}"
            if not GL.ref_url(e, pkg_dir):
                bad.append(f"{where} → 包内与框架都没有这一页：{page}")
                continue
            fp = GL.wiki_path(page, pkg_dir)
            text = open(fp, encoding="utf-8").read() if os.path.isfile(fp) else ""
            if term not in text:
                bad.append(f"{where} → {page} 正文里没有「{term}」")
    return bad


def digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                     indent=1).encode("utf-8")).hexdigest()


_RAW = {}


def req(base, path):
    """(status, 解析后的 JSON, 原始字节)。"""
    try:
        with urllib.request.urlopen(base + path, timeout=60) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw.decode("utf-8")), raw
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw.decode("utf-8")), raw
        except json.JSONDecodeError:
            return e.code, {"raw": raw.decode("utf-8", "replace")}, raw


def q(**kw) -> str:
    return "?" + urllib.parse.urlencode(kw) if kw else ""


def main() -> int:
    print("== 包自带 wiki（包优先 / 框架兜底 / 零回归）==")
    gd = tempfile.mkdtemp(prefix="fw_wiki_pkg_")
    try:
        return run(gd)
    finally:
        shutil.rmtree(gd, ignore_errors=True)


def run(gd: str) -> int:
    SRV.GAMES_DIR = gd
    wiki_pkg = make_pkg(gd, PKG_WIKI,
                        wiki_files={PAGE: PAGE_MD, SHADOW: SHADOW_MD},
                        glossary={"skills": {"fields": {
                            # ① 包内独有页的深链
                            "name": {"zh": "技能名（包内）", "note": "包内自有文档",
                                     "wiki": [PAGE, TERM]},
                            # ② 与框架同名页的深链 → 必须核到**包内**那份正文
                            "desc": {"zh": "描述（包内）", "wiki": [SHADOW, SHADOW_TERM]},
                            # ③ 包内没有的页 → 框架兜底
                            "lv": {"zh": "等级（包内）", "wiki": [BACK, FW_TERM]},
                        }}})
    act = os.path.join(wiki_pkg, "content", "mech", "actions.py")
    os.makedirs(os.path.dirname(act), exist_ok=True)
    with open(act, "w", encoding="utf-8", newline="\n") as f:
        f.write(ACTIONS_PY + "\n")
    plain_pkg = make_pkg(gd, PKG_PLAIN)          # 无 docs/wiki

    print("【1】包优先：包内页进树 / 能渲染 / 搜得到")
    fw_tree = W.tree()
    tr = W.tree(wiki_pkg)
    paths = [p["path"] for p in tr]
    check(f"包内独有页进左导航（{PAGE}）", PAGE in paths)
    check("同名页仍在（包内那份接管）", SHADOW in paths)
    check("框架页不被挤掉（并集：框架 ∪ 包内）", "README.md" in paths and len(tr) == len(fw_tree) + 1,
          f"{len(tr)} vs 框架 {len(fw_tree)}+1")
    check("包内页按路径首段归组（无首段 → 首页）",
          [p["group_label"] for p in tr if p["path"] == PAGE] == ["首页"])
    pg = W.page(PAGE, wiki_pkg)
    check("包内页渲染出正文 + 标题", bool(pg) and "<h1" in pg["html"] and pg["title"] == "包内示例页：例子",
          f"{pg and pg.get('title')}")
    check("包内页的上一页/下一页来自包 ∪ 框架的序", bool(pg["prev"]) and bool(pg["next"]),
          f"{pg and (pg['prev'], pg['next'])}")
    check("不给包时这一页不存在（回旧口径 None）", W.page(PAGE) is None)
    hits = W.search(TERM, pkg_dir=wiki_pkg)
    check("搜包内词命中包内页", any(h["path"] == PAGE for h in hits), f"{hits[:2]}")
    check("不给包时搜不到包内词（框架没这页）", W.search(TERM) == [])

    print("【2】同名页：包内那份胜（框架那份不参与）")
    pg_pkg = W.page(SHADOW, wiki_pkg)
    pg_fw = W.page(SHADOW)
    check("同名页解析到包内那份", bool(pg_pkg) and SHADOW_TERM in pg_pkg["html"],
          f"{pg_pkg and pg_pkg.get('title')}")
    check("框架那份仍在（不给包时照旧）", bool(pg_fw) and SHADOW_TERM not in pg_fw["html"])
    check("两份标题确实不同（不是同一个文件）", pg_pkg["title"] != pg_fw["title"],
          f"{pg_pkg['title']} vs {pg_fw['title']}")
    check("同名页不重复出现在树里",
          [p["path"] for p in tr].count(SHADOW) == 1)

    print("【3】框架兜底：包内没有的页 → 框架页；两边都没有 → None（不抛）")
    check("包内没有的页回退框架页（与不给包逐项相同）", W.page(BACK, wiki_pkg) == W.page(BACK))
    check("回退页的标题来自框架那份", W.page(BACK, wiki_pkg)["title"] == W.page(BACK)["title"])
    check("两边都没有的页 = None（不 500）", W.page("nope/没有这页.md", wiki_pkg) is None)
    check("路径逃逸到根外 → None（不 500）",
          W.page("../../../../../../Windows/win.ini", wiki_pkg) is None
          and W.page("../../../../../../Windows/win.ini") is None)
    # `..` **只允许在两个根内回落**（例如 `../../docs/engine-wiki/x.md` 归一化后落在框架根里
    # → 就是框架那一页，不算逃逸）；任何一步都不许跑出这两个根。
    roots = [os.path.normpath(W.WIKI_DIR), os.path.normpath(W.pkg_wiki_dir(wiki_pkg))]
    leak = []
    for rel in ("../game.json", "../../docs/engine-wiki/README.md", "..\\..\\editor\\wiki.py",
                "../../../*.py", "....//game.json"):
        for _pkg in (wiki_pkg, plain_pkg):
            p = W.page_path(rel, _pkg)
            if p and not any(p.startswith(r) for r in roots):
                leak.append(f"{os.path.basename(_pkg)}:{rel} → {p}")
    check("路径逃逸不越出两个根（`..` 只在根内归一化回落）", not leak, f"{leak}")
    check("包目录不存在也不抛", W.tree("/no/such/pkg") and W.page(BACK, "/no/such/pkg") == W.page(BACK))

    print("【4】零回归（硬约束）：包**无** docs/wiki 时逐项 / 逐字节一致")
    check("包内 wiki 目录确实不存在（前提成立）",
          not os.path.isdir(W.pkg_wiki_dir(plain_pkg)))
    zero = {
        "tree": (W.tree(plain_pkg), W.tree()),
        "page:README.md": (W.page("README.md", plain_pkg), W.page("README.md")),
        "page:reference/effect-rules.md": (W.page("reference/effect-rules.md", plain_pkg),
                                           W.page("reference/effect-rules.md")),
        "page:concepts/actor-model.md": (W.page("concepts/actor-model.md", plain_pkg),
                                         W.page("concepts/actor-model.md")),
        "search:debuff_scale": (W.search("debuff_scale", pkg_dir=plain_pkg),
                                W.search("debuff_scale")),
        "code_ref:effects.py:270": (W.code_ref("effects.py:270", pkg_dir=plain_pkg),
                                    W.code_ref("effects.py:270")),
        "code_ref:class_mech_proc.py:1895": (W.code_ref("class_mech_proc.py:1895", pkg_dir=plain_pkg),
                                             W.code_ref("class_mech_proc.py:1895")),
        "glossary:all_entries": (GL.all_entries(plain_pkg), GL.all_entries()),
        "glossary:wiki_path": (GL.wiki_path(BACK, plain_pkg), GL.wiki_path(BACK)),
        "glossary:ref_url": (GL.ref_url(GL.GLOSSARY["effect_rules"]["cap"], plain_pkg),
                             GL.ref_url(GL.GLOSSARY["effect_rules"]["cap"])),
    }
    for name, (a, b) in zero.items():
        check(f"{name}：带无 wiki 的包 == 不带包（逐项）", a == b)
        check(f"{name}：JSON sha256 相同（逐字节）", digest(a) == digest(b),
              f"{digest(a)[:12]} vs {digest(b)[:12]}")
    check("零回归对拍总 sha（10 项合一份 JSON）",
          digest({k: v[0] for k, v in zero.items()}) == digest({k: v[1] for k, v in zero.items()}))
    check("包没有 docs/wiki → page_path 直接给框架那份",
          W.page_path(BACK, plain_pkg) == W.page_path(BACK))

    print("【5】code_ref：包内源码优先 → 框架源码兜底")
    r = W.code_ref("actions.py:3", pkg_dir=wiki_pkg)
    check("包内 actions.py 命中包内那份（标 root=package）",
          r.get("ok") and r.get("root") == "package"
          and r["file"].replace("\\", "/") == "content/mech/actions.py", f"{r.get('file')}")
    check("包内命中的行号内容对得上",
          r.get("ok") and [x for x in r["lines"] if x["hit"]][0]["t"] == "包内动作在第三行")
    check("包内没有该文件 → 回退框架（与不给包一致）",
          W.code_ref("effects.py:270", pkg_dir=plain_pkg) == W.code_ref("effects.py:270"))
    check("两边都没有 → 照旧 ok=False + crossrepo，不猜",
          W.code_ref("nope_xyz.py:1", pkg_dir=wiki_pkg).get("crossrepo") is True)

    print("【6】深链：包内页优先 → 框架页兜底；词必须真在解析到的那页里")
    hit = GL.lookup("skills", "name", wiki_pkg)
    check("包词汇表条目出深链（包内页）",
          hit and hit.get("source") == "package"
          and hit["wiki"] == f"wiki:{PAGE}#find={TERM}", f"{hit and hit.get('wiki')}")
    check("wiki_path 包内优先", os.path.normpath(GL.wiki_path(PAGE, wiki_pkg))
          == os.path.normpath(os.path.join(wiki_pkg, "docs", "wiki", PAGE)))
    check("同名页的 wiki_path 也指向包内那份",
          GL.wiki_path(SHADOW, wiki_pkg) == os.path.join(wiki_pkg, "docs", "wiki",
                                                         *SHADOW.split("/")))
    check("包内没有的页 wiki_path 回退框架那份",
          GL.wiki_path(BACK, wiki_pkg) == GL.wiki_path(BACK))
    check("wiki_path 不给包 = 旧口径逐字不变", GL.wiki_path(BACK) == os.path.join(
        W.WIKI_DIR, *BACK.split("/")))
    check("包词汇表深链自检全绿", deep_link_problems(wiki_pkg) == [],
          f"{deep_link_problems(wiki_pkg)}")
    fw_bad = []
    for dom, tbl in GL.GLOSSARY.items():
        for k, e in tbl.items():
            if not e.get("ref"):
                continue
            page, term = e["ref"]
            fp = GL.wiki_path(page, plain_pkg)
            if GL.ref_url(e, plain_pkg) is None or not os.path.isfile(fp) \
                    or term not in open(fp, encoding="utf-8").read():
                fw_bad.append(f"{dom}.{k} → {page}#{term}")
    check("框架词典的深链在「带无 wiki 包」时逐条仍可解析", not fw_bad, f"{fw_bad[:4]}")

    print("【7】反证①：把包内页删掉 → 回退/消失，**不 500**")
    probe = os.path.join(gd, "pkg_probe")
    shutil.copytree(wiki_pkg, probe)
    os.remove(os.path.join(probe, "docs", "wiki", PAGE))
    check("删掉包内独有页 → tree 里没有它", PAGE not in [p["path"] for p in W.tree(probe)])
    check("删掉包内独有页 → page = None（不抛）", W.page(PAGE, probe) is None)
    check("删掉包内独有页 → 深链不再出链（不编）",
          GL.ref_url({"wiki": [PAGE, TERM]}, probe) is None)
    os.remove(os.path.join(probe, "docs", "wiki", "reference", "effect-rules.md"))
    check("删掉同名页 → page 回退框架那份（逐项相同）",
          W.page(SHADOW, probe) == W.page(SHADOW))
    check("删掉同名页 → wiki_path 回退框架那份",
          GL.wiki_path(SHADOW, probe) == GL.wiki_path(SHADOW))

    print("【8】反证②：深链的词改成页里没有的词 → 门禁口径报红")
    bad_pkg = os.path.join(gd, "pkg_badterm")
    shutil.copytree(wiki_pkg, bad_pkg)
    p = os.path.join(bad_pkg, "editor", "glossary", "skills.json")
    obj = json.load(open(p, encoding="utf-8"))
    obj["fields"]["name"]["wiki"] = [PAGE, "页里根本没有的词"]
    json.dump(obj, open(p, "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=2)
    probs = deep_link_problems(bad_pkg)
    check("坏词被自检抓出来（新页 → 没有那个词）",
          any("页里根本没有的词" in x for x in probs), f"{probs}")
    check("出链本身仍在（链接不撒谎 → 由门禁判词）",
          GL.ref_url({"wiki": [PAGE, "页里根本没有的词"]}, bad_pkg) ==
          f"wiki:{PAGE}#find=页里根本没有的词")
    obj["fields"]["desc"]["wiki"] = ["reference/不存在.md", "x"]
    json.dump(obj, open(p, "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=2)
    check("两边都没有的页 → 不出链（ref_url = None）",
          GL.ref_url({"wiki": ["reference/不存在.md", "x"]}, bad_pkg) is None)
    check("同一批坏声明被自检列为「包内与框架都没有这一页」",
          any("都没有这一页" in x for x in deep_link_problems(bad_pkg)),
          f"{deep_link_problems(bad_pkg)}")

    print("【9】HTTP 端到端：4 条路由都认 ?pkg=；未知包 → 404 不是 500")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), SRV.H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        _RAW["tree"] = req(base, "/api/wiki/tree")[2]
        _RAW["page:" + BACK] = req(base, "/api/wiki/page" + q(path=BACK))[2]
        st, j, _r = req(base, "/api/wiki/tree")
        check("GET /api/wiki/tree 200（不给包 = 框架清单）",
              st == 200 and [p["path"] for p in j["pages"]] == [p["path"] for p in fw_tree])
        st, j, _r = req(base, "/api/wiki/tree" + q(pkg=PKG_WIKI))
        check("GET /api/wiki/tree?pkg= 带出包内页", st == 200 and PAGE in [p["path"] for p in j["pages"]])
        st_p, j_p, raw_p = req(base, "/api/wiki/tree" + q(pkg=PKG_PLAIN))
        check("GET /api/wiki/tree?pkg=<无 wiki 包> 与不给包**原始字节一致**",
              st_p == 200 and raw_p == _RAW["tree"])
        st, j, _r = req(base, "/api/wiki/page" + q(path=PAGE, pkg=PKG_WIKI))
        check("GET /api/wiki/page?pkg= 渲染包内页", st == 200 and TERM in j["html"])
        st, j, _r = req(base, "/api/wiki/page" + q(path=PAGE))
        check("不带 pkg 打不开包内页 → 404", st == 404)
        st, j, _r = req(base, "/api/wiki/page" + q(path=SHADOW, pkg=PKG_WIKI))
        check("同名页 HTTP 层也走包内那份", st == 200 and SHADOW_TERM in j["html"])
        st_a, j_a, raw_a = req(base, "/api/wiki/page" + q(path=BACK, pkg=PKG_PLAIN))
        check("page?pkg=<无 wiki 包> 与不给包**原始字节一致**",
              st_a == 200 and raw_a == _RAW["page:" + BACK])
        st, j, _r = req(base, "/api/wiki/search" + q(q=TERM, pkg=PKG_WIKI))
        check("GET /api/wiki/search?pkg= 搜到包内页",
              st == 200 and any(h["path"] == PAGE for h in j["hits"]))
        st, j, _r = req(base, "/api/wiki/code" + q(ref="actions.py:3", pkg=PKG_WIKI))
        check("GET /api/wiki/code?pkg= 取包内源码", st == 200 and j.get("root") == "package")
        st, j, _r = req(base, "/api/wiki/page" + q(path="../server.py", pkg=PKG_WIKI))
        check("路径逃逸 → 404（不是 200 / 不是 500）", st == 404)
        st, j, _r = req(base, "/api/wiki/tree" + q(pkg="没有这个包"))
        check("未知包 id → 404 包不存在（不是 500）",
              st == 404 and "包不存在" in json.dumps(j, ensure_ascii=False))
        st, j, _r = req(base, "/api/wiki/page" + q(path="nope.md", pkg=PKG_WIKI))
        check("两边都没有的页 → 404", st == 404)
    finally:
        httpd.shutdown()

    print(f"\n{'-' * 46}\n通过 {PASS} / 失败 {FAIL}")
    for f in FAILURES:
        print("  ❌", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
