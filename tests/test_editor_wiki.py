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


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name} {detail}")
        print(f"  ❌ {name} {detail}")


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
    check("同名文件优先取引擎包（saintess_engine/...）",
          r3.get("ok") and r3["file"].startswith("saintess_engine/"), f"{r3.get('file')}")

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


if __name__ == "__main__":
    sys.exit(main())
