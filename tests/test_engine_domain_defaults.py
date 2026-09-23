# -*- coding: utf-8 -*-
"""门禁：引擎默认域集 + 「包声明 ∪ 引擎默认集」合并规则 + 装载口**装配点**。

为什么有它（2026-09-20 T1 双向迁移演习）
----------------------------------------
T1 的硬判据是「一个域能从内容包上移到引擎、再迁回包，全程只改**声明 + 文件位置 + 一处装配点**，
前后快照逐字节不变」。干跑实测到一处真耦合：**编辑器的声明面能合并「引擎内置默认集」，
引擎自己的装载口（`records.read_domain_decl`）不能** —— 声明搬到引擎后装载口报
`RecordsDeclarationError`，运行层是断的（设计 + 证据见 `overnight/T1_DUAL_MIGRATION_DRILL.md` §六）。

本门禁钉住收口后的口径：

  A. 合并规则唯一源 = `saintess_engine.domains.merge_decls`（纯函数；同名包胜 / `$builtin:false`
     不兜底 / 顺序 = 引擎默认集序 + 包新增 / 不改入参）。
  B. **装配点**：`read_domain_decl` / `resolve_domain` / `records_from_domain` /
     `set_from_domains` 对「声明只在引擎默认集里」的域**照样可用** —— 声明放哪边，装载口与
     编辑器看到的是同一份有效域表（D 段对拍）。
  C. fail-closed 一条没放松：文件缺失 / 坏 JSON / 顶层形状不对 / 两个源都没有的域 → 照旧
     `RecordsDeclarationError`（**不静默空表**）。

跑法：python tests/test_engine_domain_defaults.py
退出码：0 = 全过；1 = 有失败。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
os.environ.setdefault("GWEN_GAME_DB",
                      os.path.join(FW_ROOT, "test_engine_domain_defaults.db"))
os.environ.setdefault("GWEN_TEST_MODE", "1")
sys.path.insert(0, FW_ROOT)

import _domain_fixtures as FX             # noqa: E402  （域表全貌：引擎默认集 + 扩展包域 + 内容域）
from editor import packages as PK                    # noqa: E402
from saintess_engine import domains as D             # noqa: E402
from saintess_engine import records as R             # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "PASS", "FAIL", "FAILURES")

#: 引擎默认集 = 3 个「**通用件自己**真有消费端代码」的表（内容域、游戏级形状都不许内置）。
#: ★ 2026-09-23 第 4 批：`effect_rules` / `passive_proc` / `maps` / `drop_pools` / `instances`
#:   的消费端（battle / space / run / loot）搬进扩展包后，这 5 个域**跟着消费端**搬进
#:   `extends/<包>/domains.json`，不再由引擎默认集兜底。
ENGINE_DOMAINS = ("commands", "texts", "tlogs")

_SKILL = {"label": "技能", "kind": "data", "schema": None, "primary": None, "icon": "⚔️"}
_INSTANCES = {"a1": {"name": "副本一"}, "a2": {"name": "副本二"}}
# instances 随消费端搬进扩展包（2026-09-23 第 4 批）⇒ 合成包自己声明它
_INST_meta = {"label": "副本", "kind": "data", "schema": "instances.schema.json",
              "primary": "instance", "icon": "🏯"}


def _mkpkg(root, name, decl, files=()):
    """造一个最小包：`editor/domains.json`（dict 或**原文串**）+ `content/<sub>/<域>.json`。"""
    pkg = os.path.join(root, name)
    os.makedirs(os.path.join(pkg, "editor"), exist_ok=True)
    with open(os.path.join(pkg, "editor", "domains.json"), "w",
              encoding="utf-8", newline="\n") as f:
        if isinstance(decl, str):
            f.write(decl)
        else:
            json.dump(decl, f, ensure_ascii=False, indent=2)
            f.write("\n")
    for sub, dom, body in files:
        d = os.path.join(pkg, "content", sub)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, dom + ".json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(body, f, ensure_ascii=False, indent=2)
    return pkg


def _raises(fn):
    """跑一次 → (是否抛 RecordsDeclarationError, 异常文本)。"""
    try:
        fn()
    except R.RecordsDeclarationError as exc:
        return True, str(exc)
    except Exception as exc:                              # noqa: BLE001
        return False, "%s: %s" % (type(exc).__name__, exc)
    return False, ""


def main() -> int:
    print("== 引擎默认域集 / 合并规则 / 装载口装配点 ==")
    gd = tempfile.mkdtemp(prefix="engine_domains_")

    # ──────────────────────────────────────────── A. 合并规则唯一源
    print("\n【A. 合并规则（merge_decls / decl_switch）】")
    check("引擎默认集逐名 == 3 个引擎域（通用件自己的表）",
          tuple(D.BUILTIN_DEFAULT_DOMAINS) == ENGINE_DOMAINS,
          sorted(D.BUILTIN_DEFAULT_DOMAINS))
    check("编辑器那份与引擎那份是**同一个对象**（常量已下移，不是两份拷贝）",
          PK.BUILTIN_DEFAULT_DOMAINS is D.BUILTIN_DEFAULT_DOMAINS)
    check("编辑器 DOMAINS 别名仍指向它（历史调用点零改动）",
          PK.DOMAINS is D.BUILTIN_DEFAULT_DOMAINS)
    _c = D.builtin_default_domains()
    _c.pop("commands", None)
    check("builtin_default_domains() 返回副本（改它不动常量）",
          "commands" in D.BUILTIN_DEFAULT_DOMAINS)

    merged = D.merge_decls({"skills": _SKILL, "instances": {"label": "我的副本",
                                                            "kind": "data"}})
    check("顺序 = 引擎默认集序 + 包新增域（追加末尾）",
          tuple(merged) == ENGINE_DOMAINS + ("skills", "instances"), tuple(merged))
    check("同名域整体以包为准（不做字段级补缺）",
          merged["instances"] == {"label": "我的副本", "kind": "data"}, merged["instances"])
    check("包新增域原样并入", merged["skills"] == _SKILL)
    check("use_builtin=False ⇒ 只剩包声明",
          tuple(D.merge_decls({"skills": _SKILL}, use_builtin=False)) == ("skills",))
    _in = {"skills": _SKILL}
    _out = D.merge_decls(_in)
    check("merge_decls 不改入参（只读地拷出一份新表）",
          tuple(_in) == ("skills",) and _out is not _in and _out["skills"] == _SKILL)

    raw = {"domains": {"skills": _SKILL}, "$builtin": False}
    decls, use_builtin = D.decl_switch(raw)
    check("decl_switch：包装层 + 开关（布尔值照吃）",
          decls == {"skills": _SKILL} and use_builtin is False, (decls, use_builtin))
    check("decl_switch 剥掉开关键（$builtin 不许漏进域表）",
          "$builtin" not in decls and "domains" not in decls)
    check("decl_switch 是纯函数（不改入参）",
          raw == {"domains": {"skills": _SKILL}, "$builtin": False}, raw)
    check("decl_switch：无开关 ⇒ 默认兜底 True",
          D.decl_switch({"skills": _SKILL})[1] is True)
    check("decl_switch：非布尔开关 ⇒ 按 True（与编辑器同口径）",
          D.decl_switch({"$builtin": "no"})[1] is True)

    # ──────────────────────────────────────────── B. 装载口装配点
    print("\n【B. 装配点：声明只在引擎默认集里，装载口照样可用】")
    pkg = _mkpkg(gd, "engine_side", {"skills": _SKILL, "instances": dict(_INST_meta)},
                 [("data", "instances", _INSTANCES),
                  ("data", "skills", {"s1": {"name": "技能一"}})])
    tbl = R.read_domain_decl(pkg)
    check("read_domain_decl 的有效域表 = 包声明 ∪ 引擎默认集（3 通用 + 包声明 2）",
          set(tbl) == set(ENGINE_DOMAINS) | {"skills", "instances"}, sorted(tbl))
    check("同名域仍以包为准（skills 用包那份）", tbl["skills"] == _SKILL)
    ok, err = _raises(lambda: R.records_from_domain(pkg, "instances"))
    check("★ 声明只在内置集里 → records_from_domain 可装载（不再断链）", not ok, err)
    rec = R.records_from_domain(pkg, "instances")
    check("装载内容正确（count=2）", len(rec.all()) == 2, len(rec.all()))
    check("resolve_domain 落点 == content/data（由声明 kind 派生）",
          R.resolve_domain(pkg, "instances").replace("\\", "/") == "content/data",
          R.resolve_domain(pkg, "instances"))
    bag = R.set_from_domains(pkg, ("skills", "instances"))
    check("set_from_domains 多域同吃（含内置集那一域），零 missing",
          bag.missing_domains() == [] and len(bag.instances.all()) == 2,
          bag.missing_domains())

    print("\n【B2. $builtin:false ⇒ 不兜底】")
    pkg_off = _mkpkg(gd, "builtin_off", {"$builtin": False, "skills": _SKILL},
                     [("data", "instances", _INSTANCES)])
    check("有效域表只剩包声明的（1 个）",
          sorted(R.read_domain_decl(pkg_off)) == ["skills"],
          sorted(R.read_domain_decl(pkg_off)))
    ok, err = _raises(lambda: R.records_from_domain(pkg_off, "instances"))
    check("★ 不兜底 ⇒ 声明缺项照旧拒绝装载（点名域与声明路径）",
          ok and "instances" in err and "domains.json" in err, err)

    print("\n【B3. 包装层写法与顶层同口径】")
    pkg_w = _mkpkg(gd, "wrapper", {"domains": {"skills": _SKILL}})
    check("包装层写法 == 顶层写法（域集合都是「包声明 ∪ 引擎默认集」）",
          set(R.read_domain_decl(pkg_w)) == set(ENGINE_DOMAINS) | {"skills"},
          sorted(R.read_domain_decl(pkg_w)))
    pkg_w2 = _mkpkg(gd, "wrapper_off", {"domains": {"skills": _SKILL}, "$builtin": False})
    check("包装层里的开关也认（$builtin:false ⇒ 只剩 skills）",
          sorted(R.read_domain_decl(pkg_w2)) == ["skills"],
          sorted(R.read_domain_decl(pkg_w2)))

    # ──────────────────────────────────────────── C. fail-closed 没被放松
    print("\n【C. fail-closed：兜底只发生在「文件在、但没写这个域」这一层】")
    pkg_nd = os.path.join(gd, "no_decl")
    os.makedirs(pkg_nd, exist_ok=True)
    ok, err = _raises(lambda: R.read_domain_decl(pkg_nd))
    check("声明文件缺失 → 照旧抛（不静默空表）", ok and "不存在" in err, err)
    ok, err = _raises(lambda: R.read_domain_decl(_mkpkg(gd, "badjson", "{")))
    check("坏 JSON → 照旧抛", ok and "坏 JSON" in err, err)
    ok, err = _raises(lambda: R.read_domain_decl(_mkpkg(gd, "notmap", "[]")))
    check("顶层不是非空映射 → 照旧抛", ok and "非空映射" in err, err)
    ok, err = _raises(lambda: R.records_from_domain(pkg, "affixes"))
    check("两个源都没有的域 → 照旧点名拒绝（文案说清两个源）",
          ok and "affixes" in err and "引擎默认集" in err, err)

    # ──────────────────────────────────────────── D. 编辑器 ⇄ 装载口 同看一份
    print("\n【D. ★ 唯一装配点的意义：编辑器与装载口同看一份有效域表】")
    real = os.path.join(FW_ROOT, "games", "orlandia")
    check("真包 games/orlandia 在位（对齐的判据面）",
          os.path.isfile(os.path.join(real, "editor", "domains.json")), real)
    if os.path.isfile(os.path.join(real, "editor", "domains.json")):
        eff, warns = PK.effective_domains(real)
        eng = R.read_domain_decl(real)
        check("真包：编辑器 effective_domains 域集合 == 装载口 read_domain_decl 域集合",
              set(eff) == set(eng), "%d vs %d；差 %r"
              % (len(eff), len(eng), sorted(set(eff) ^ set(eng))[:8]))
        check("真包：instances 两面 kind 一致（落点不会岔）",
              eff["instances"].get("kind") == eng["instances"].get("kind") == "data")
        check("真包：编辑器 0 告警（声明干净是前提）", warns == [], warns)
        check("真包：装载口对 instances 真能装载（count>0）",
              len(R.records_from_domain(real, "instances").all()) > 0)
    eff2, _w2 = PK.effective_domains(pkg)
    check("同型包（instances 由包自己声明）：编辑器与装载口同样看待它",
          set(eff2) == set(R.read_domain_decl(pkg))
          # ★ 2026-09-23 第 4 批：instances 不再由引擎默认集兜底 ⇒ 来源是**包声明**
          and PK.domain_source(pkg, "instances") == "package"
          and R.resolve_domain(pkg, "instances").replace("\\", "/") == "content/data",
          sorted(set(eff2) ^ set(R.read_domain_decl(pkg))))

    print("\n===== 结果：通过 %d / %d =====" % (PASS, PASS + FAIL))
    for f in FAILURES:
        print("  · " + f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
