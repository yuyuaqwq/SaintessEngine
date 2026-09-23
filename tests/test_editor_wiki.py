# -*- coding: utf-8 -*-
"""编辑器内文档（engine wiki）回归：渲染 / 导航 / 死链 / 源码直链。

守的底线
--------
1. **每页都能渲染**（34 页全过）：markdown 是手写渲染器，任何一页渲染炸掉 = 文档打不开。
2. **页内链接不指向不存在的页**：wiki 里大量相对 `.md` 链接，改文件名就会留死链 ——
   本文件把「链接目标文件是否真存在」变成门禁（现在是 0 死链，以后断了会红）。
3. **源码直链不撒谎**：`file.py:NNN` 点开必须给出该文件的真实片段、目标行内容对得上；
   指向**游戏仓**的引用要明确说「读不到」，不能编一段代码出来。
4. **渲染转义**：markdown 里的 HTML 必须被转义（文档里有 `<br/>` 之类字面量）。

跑法：python tests/test_editor_wiki.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from editor import wiki as W          # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "PASS", "FAIL", "FAILURES")


def main() -> int:
    print("== 编辑器文档（wiki）回归 ==")

    # 1. 页清单 = 磁盘上的 md（不许漏）
    on_disk = sorted(os.path.relpath(os.path.join(r, f), W.WIKI_DIR).replace("\\", "/")
                     for r, _d, fs in os.walk(W.WIKI_DIR) for f in fs if f.endswith(".md"))
    tr = W.tree()
    check(f"页清单覆盖磁盘全部 md（{len(on_disk)} 页）",
          sorted(p["path"] for p in tr) == on_disk, f"{len(tr)} vs {len(on_disk)}")
    check("页清单按分组顺序排（首页 → 上手 → 概念 → 指南 → 参考 → 架构 → 贡献）",
          [p["group"] for p in tr] == sorted((p["group"] for p in tr),
                                             key=lambda g: [x[0] for x in W.GROUPS].index(g)))
    check("每页有标题", all(p["title"] and p["title"] != p["path"] for p in tr))
    check("分组标签已归位（至少 5 类）", len({p["group_label"] for p in tr}) >= 5)

    # 2. 全页渲染 + 死链扫描
    render_bad, dead, no_h1 = [], [], []
    for p in tr:
        pg = W.page(p["path"])
        if not pg or not pg.get("html") or "<h1" not in pg["html"]:
            render_bad.append(p["path"])
            continue
        for m in re.finditer(r"\]\(([^)\s]+)\)", W._read(p["path"])):
            url = m.group(1)
            if not url.endswith(".md") and ".md#" not in url:
                continue
            base = os.path.dirname(p["path"])
            tgt = os.path.normpath(os.path.join(base, url.split("#")[0])).replace("\\", "/")
            if not os.path.isfile(os.path.join(W.WIKI_DIR, *tgt.split("/"))):
                dead.append(f"{p['path']} → {url}")
    check(f"{len(tr)} 页全部渲染出正文（h1 + 非空）", not render_bad, f"渲染失败：{render_bad[:5]}")
    check("页内相对 md 链接零死链", not dead, f"死链：{dead[:6]}")

    # 3. 页内导航（上一页/下一页 + 目录）
    pg = W.page("reference/effect-rules.md")
    check("有上一页/下一页", bool(pg["prev"]) and bool(pg["next"]), f"{pg['prev']} / {pg['next']}")
    check("目录抓到小标题（≥6 条）", len(pg["toc"]) >= 6, f"{len(pg['toc'])}")
    check("小标题都有锚点 id", all(t.get("id") for t in pg["toc"]))

    # 4. 源码直链：解析正确 + 目标行内容对得上
    r = W.code_ref("effects.py:270")
    check("effects.py:270 可解析", r.get("ok"), f"{r.get('reason')}")
    if r.get("ok"):
        n, t = r["line"], [x for x in r["lines"] if x["hit"]][0]["t"]
        real = open(os.path.join(W.FW_ROOT, *r["file"].split("/")), encoding="utf-8").read().splitlines()[n - 1]
        check(f"行号对得上（{r['file']}:{n} = {t.strip()[:34]}）", t == real)
        check("只给窗口不整文件（≤ 2×14+1 行）", len(r["lines"]) <= 29, f"{len(r['lines'])}")
    r2 = W.code_ref("class_mech_proc.py:1895")          # 游戏仓文件
    check("游戏仓引用 → 明确报「读不到」且标 crossrepo",
          not r2.get("ok") and r2.get("crossrepo"), f"{r2}")
    check("垃圾输入不崩", not W.code_ref("随便什么").get("ok"))
    r3 = W.code_ref("battle.py:1")
    # 战斗已迁成扩展包（2026-09-23）：同名文件仍按「引擎包 → 扩展包 → 游戏包」的优先级解析，
    # 而 battle.py 现在只存在于扩展包里 ⇒ 应解析到 extends/ext_combat/ 下那一份。
    check("同名文件按优先级解析（引擎包 → 扩展包），battle.py 落到 ext_combat",
          r3.get("ok") and r3["file"].startswith("extends/ext_combat/"), f"{r3.get('file')}")

    # 5. 渲染细节（表格 / 代码 / 强调 / 转义）
    h, _toc = W.render_md("| a | b |\n|---|---|\n| 1 | `x` |\n\n**粗** *斜* `code`\n")
    check("表格渲染", '<table class="md-table">' in h and "<th>a</th>" in h, h[:120])
    check("行内代码 / 强调", "<code>x</code>" in h and "<strong>粗</strong>" in h and "<em>斜</em>" in h)
    h2, toc2 = W.render_md("# 标题一\n\n## 二级 B\n")
    check("标题带锚点", '<h1 id="标题一">' in h2 and toc2[1]["id"] == "二级-b", h2[:80])
    h3, _ = W.render_md('一个字面 <br/> 与 <script>alert(1)</script>')
    check("HTML 被转义（防注入）", "&lt;script&gt;" in h3 and "<script>" not in h3, h3[:80])
    h4, _ = W.render_md("```python\nx = 1\n```")
    check("代码块带语言标记", 'data-lang="python"' in h4 and "x = 1" in h4)
    h5, _ = W.render_md("```mermaid\nflowchart TD\n  A --> B\n```")
    check("mermaid 图给源码兜底 + 可渲染容器",
          'class="mermaid"' in h5 and 'data-src="flowchart TD' in h5
          and 'A --&gt; B' in h5 and 'mermaid-src' in h5, h5[:150])
    h6, _ = W.render_md("- a\n- b\n\n1. c\n2. d\n")
    check("列表渲染（ul + ol）", "md-list" in h6 and "<li>a</li>" in h6 and "<li>c</li>" in h6, h6[:120])

    # 6. 搜词（配字段时最常用） + 深链目标必须真存在
    hits = W.search("debuff_scale")
    pages = {h["path"] for h in hits}
    check("搜 debuff_scale 命中 effect-rules 参考页", "reference/effect-rules.md" in pages, f"{sorted(pages)[:5]}")
    check("短词不搜（<2 字符）", W.search("a") == [])
    from editor import glossary as G
    bad_terms = []
    for dom, tbl in G.GLOSSARY.items():
        for k, e in tbl.items():
            if not e.get("ref"):
                continue
            page, term = e["ref"]
            if term.lower() not in W._read(page).lower():
                bad_terms.append(f"{dom}.{k}→{page}#{term}")
    check("词典深链目标词在页内（大小写不敏感复核）", not bad_terms, f"{bad_terms[:5]}")

    # 7. README 声明的模块/文件/行数 == 磁盘（防文档数字静默过期）
    test_readme_counts()

    # 8. ★ PKG_WIKI_BEGIN（B18-L11）：包自带 wiki —— 纯增量，见文件末同名段标记
    test_pkg_wiki()
    # ★ PKG_WIKI_END

    print(f"\n{'-' * 46}\n通过 {PASS} / 失败 {FAIL}")
    for f in FAILURES:
        print("  ❌", f)
    return 1 if FAIL else 0



def test_readme_counts():
    """wiki README 声明的模块/文件/行数必须与磁盘一致（防文档数字静默过期）。

    为什么要有这条：该行原先写「14 个模块 + support/ 4 个通用件，共 18 个 .py / 5 202 行」，
    实际是 **42 个 .py / 7 770 行**，且 `support/` 早已改名 `container/` —— 文档数字没人盯着
    就会烂很久。判据取自 README 本身（单一真源），测试只做对照，不另存一份数字。
    """
    print("【wiki README 数字对照磁盘】")
    import re
    import os as _os
    readme = _os.path.join(W.WIKI_DIR, "README.md")
    with open(readme, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"\*\*(\d+)\*\* 个子包 \+ \*\*(\d+)\*\* 个顶层模块；"
                  r"共 \*\*(\d+)\*\* 个 `\.py` / \*\*([\d ]+)\*\* 行", text)
    check("README 有一行可解析的引擎目录数字", m is not None,
          "格式：**N** 个子包 + **N** 个顶层模块；共 **N** 个 `.py` / **N NNN** 行")
    if not m:
        return
    pk, top, files, lines = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4).replace(" ", ""))
    pkg_dir = _os.path.join(W.FW_ROOT, "saintess_engine")

    dirs = [d for d in _os.listdir(pkg_dir)
            if _os.path.isdir(_os.path.join(pkg_dir, d)) and d != "__pycache__"]
    mods = [f for f in _os.listdir(pkg_dir)
            if f.endswith(".py") and f != "__init__.py"]
    all_py, total = [], 0
    for root, _d, fs in _os.walk(pkg_dir):
        if "__pycache__" in root:
            continue
        for f in fs:
            if f.endswith(".py"):
                all_py.append(_os.path.join(root, f))
                with open(_os.path.join(root, f), encoding="utf-8") as fh:
                    total += len(fh.readlines())

    check(f"子包数 {pk} == 磁盘 {len(dirs)}", pk == len(dirs), f"{sorted(dirs)}")
    check(f"顶层模块数 {top} == 磁盘 {len(mods)}", top == len(mods), f"{sorted(mods)}")
    check(f".py 总数 {files} == 磁盘 {len(all_py)}", files == len(all_py))
    check(f"总行数 {lines} == 磁盘 {total}", lines == total, f"差 {total - lines}")


# ★═════════════════════════ PKG_WIKI_BEGIN（B18-L11）═════════════════════════
# 包自带 wiki（`<pkg>/docs/wiki/**.md`）的**纯增量**断言：渲染 / 死链 / 深链。
# 删掉这一整段（连同 main() 里那三行调用）= 回到改造前，其余断言不受影响。
# 完整门禁（包优先 / 框架兜底 / 零回归逐字节）在 `tests/test_editor_wiki_pkg.py`。
def test_pkg_wiki():
    """包内页能渲染、页内相对链接无死链、包词汇表的深链能定位到**解析到的**那页。"""
    print("【包自带 wiki：包优先 → 框架兜底（纯增量）】")
    import json
    import shutil
    import tempfile

    root = tempfile.mkdtemp(prefix="fw_wiki_inc_")
    try:
        pkg = os.path.join(root, "inc_pkg")
        page_rel = "guides/包内指南.md"
        term = "包内指南专属词"
        os.makedirs(os.path.join(pkg, "docs", "wiki", "guides"), exist_ok=True)
        os.makedirs(os.path.join(pkg, "editor", "glossary"), exist_ok=True)
        with open(os.path.join(pkg, "game.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump({"id": "inc_pkg", "name": "增量门禁用包"}, f, ensure_ascii=False)
        with open(os.path.join(pkg, "docs", "wiki", *page_rel.split("/")), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(f"# 包内指南\n\n{term}：这一页只存在于游戏包里。\n\n"
                    "回[框架首页](../README.md)，或看[与框架同名的参考页](../reference/effect-rules.md)。\n")
        # ★ 2026-09-23 第 4 批：`effect_rules` 随消费端搬进扩展包（ext_combat），引擎默认集不再兜底
        #   ⇒ 这个合成包要**自己声明**它，词汇表才会被编辑器认到。
        with open(os.path.join(pkg, "editor", "domains.json"), "w",
                  encoding="utf-8", newline="\n") as f:
            json.dump({"effect_rules": {"label": "声明表", "kind": "rules",
                                        "schema": "effect_rules.schema.json",
                                        "primary": "effect_rule", "icon": "📜"}}, f, ensure_ascii=False)
        # 包词汇表：带上 wiki 深链
        with open(os.path.join(pkg, "editor", "glossary", "effect_rules.json"), "w",
                  encoding="utf-8", newline="\n") as f:
            json.dump({"fields": {"cap": {"zh": "包·叠层上限", "note": "包内文档出处",
                                          "wiki": [page_rel, term]}}}, f, ensure_ascii=False)

        pg = W.page(page_rel, pkg)
        check("包内页能渲染（h1 + 非空）", bool(pg) and "<h1" in pg["html"] and pg["title"] == "包内指南",
              f"{pg and pg.get('title')}")
        check("包内页进了页清单", page_rel in [p["path"] for p in W.tree(pkg)])
        check("不给包时这一页不存在", W.page(page_rel) is None)

        dead = []
        # 扫「包 ∪ 框架」的全部页。链接判活的规则与上面框架那条**同口径**（按当前页自己的根
        # 归一化，允许 `../` 落到 wiki 目录外，如框架 `_selfcheck.md` → `../engine-vocabulary-contract.md`），
        # 另外接受「包内没有 → 框架兜底」：两条里任一命中即不算死链。
        pk_root, fw_root = os.path.normpath(W.pkg_wiki_dir(pkg)), os.path.normpath(W.WIKI_DIR)
        for rel in [p["path"] for p in W.tree(pkg)]:
            own = pk_root if os.path.isfile(os.path.join(pk_root, *rel.split("/"))) else fw_root
            for m in re.finditer(r"\]\(([^)\s]+)\)", W._read(rel, pkg)):
                url = m.group(1)
                if not url.endswith(".md") and ".md#" not in url:
                    continue
                base = os.path.dirname(rel)
                tgt = os.path.normpath(os.path.join(base, url.split("#")[0])).replace("\\", "/")
                cand = os.path.normpath(os.path.join(own, *tgt.split("/")))
                if not os.path.isfile(cand) and not W.page_path(tgt, pkg):
                    dead.append(f"{rel} → {url}")
        check("包内页的相对 md 链接零死链（含回退到框架页的那条）", not dead, f"{dead[:4]}")

        from editor import glossary as G2
        hit = G2.lookup("effect_rules", "cap", pkg)
        check("包词汇表的深链出链（指到包内页）",
              hit and hit["wiki"] == f"wiki:{page_rel}#find={term}", f"{hit and hit.get('wiki')}")
        check("深链的「页内词」真在**解析到的**那页正文里",
              term in open(G2.wiki_path(page_rel, pkg), encoding="utf-8").read())
        check("包内没有的页 → wiki_path 回退框架那份",
              G2.wiki_path("reference/effect-rules.md", pkg) == G2.wiki_path("reference/effect-rules.md"))
    finally:
        shutil.rmtree(root, ignore_errors=True)
# ★═════════════════════════ PKG_WIKI_END ═════════════════════════════


if __name__ == "__main__":
    sys.exit(main())
