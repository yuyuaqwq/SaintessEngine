#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：声明驱动两域（指令 / 文案）在**编辑器**里可用。

光有框架侧的注册表不够 —— 用户要在编辑器里建包、填表、被 schema 校验拦住错。
本门禁把「编辑器 → 数据文件 → 框架装载」这条链跑通：

  1. 两域已注册（DOMAINS + schema 文件存在 + primary 指向 schema 里真有的 def）
  2. 建包脚手架把两域写进清单与数据文件
  3. **合法条目**过 schema 校验；**非法条目**被抓出来（不是静默放过）
  4. 写出的 JSON 能被框架的 `CommandRegistry` / `TextTable` 原样装载并工作
     （编辑器造的数据 = 框架能吃的声明，闭合）
  5. 词典与分组覆盖两域（否则编辑器面板是空白）
  6. ★ 2026-09-26 P-8：向导产物**直接过装载口** —— 引擎默认域三件（commands / texts / tlogs）
     的空表由向导建出，`probe_stack()` 零告警；抽掉一份 ⇒ 告警当场回来（有牙）
"""
import json
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
if FW_ROOT not in sys.path:
    sys.path.insert(0, FW_ROOT)
sys.path.insert(0, os.path.join(FW_ROOT, "editor"))

import editor.packages as PK            # noqa: E402
import editor.glossary as G             # noqa: E402
from saintess_engine.command import CommandRegistry   # noqa: E402
from saintess_engine.package import probe_stack       # noqa: E402
from saintess_engine.text import TextTable            # noqa: E402
from saintess_engine.tlog import KindTable            # noqa: E402

passed = failed = 0


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


print("== 声明驱动两域（指令 / 文案）编辑器门禁 ==")

# ---------------------------------------------------------------- 1. 域注册
print("\n【1. 域注册：DOMAINS + schema 文件 + primary def】")
NEW = ("commands", "texts")
for d in NEW:
    meta = PK.DOMAINS.get(d)
    check(f"{d} 已注册", bool(meta), PK.DOMAINS.keys())
    if not meta:
        continue
    sp = os.path.join(FW_ROOT, "schemas", meta["schema"])
    check(f"{d} schema 文件存在（{meta['schema']}）", os.path.exists(sp), sp)
    if os.path.exists(sp):
        sch = json.load(open(sp, encoding="utf-8"))
        check(f"{d} primary={meta['primary']!r} 在 schema $defs 里",
              meta["primary"] in (sch.get("$defs") or {}), list(sch.get("$defs") or {}))
check("域注册表与 glossary 的 DOMAIN_SCHEMA 对齐",
      all(G.DOMAIN_SCHEMA.get(d) == PK.DOMAINS[d]["schema"] for d in NEW
          if d in PK.DOMAINS and d in G.DOMAIN_SCHEMA))

# ---------------------------------------------------------------- 2. 建包
print("\n【2. 脚手架建包（含两域）】")
root = tempfile.mkdtemp(prefix="fw_pkg_")
try:
    r = PK.create_package("probe_pkg", "探测包", "声明驱动域冒烟", domains=list(NEW),
                          games_dir_=root)
    pkg = r["dir"]
    man = PK.load_manifest(pkg)
    check("清单 domains 含两域", set(NEW) <= set(man.get("domains") or []), man.get("domains"))
    for d in NEW:
        check(f"{d} 数据文件已建", os.path.exists(PK.domain_path(pkg, d)),
              PK.domain_path(pkg, d))

    # ------------------------------------------------------------ 2b. 向导产物 → 装载口（P-8）
    # ★ 2026-09-26 P-8：引擎默认域三件（commands / texts / tlogs）**默认就在有效域表里**
    #   （引擎默认集那一层兜底）⇒ 向导的产物必须把这三张**最小合法表**也建出来，
    #   否则一装载就吃装载口告警（`PackageStack._domain_warnings()` 第二条）、真读时
    #   `domain_path()` fail-closed。这里钉住「显式只点两域也一样会补上」「产物直接被
    #   `probe_stack()` 吃掉且零告警」「空表是零行为不是读不动」，并给一条反证。
    print("\n【2b. 向导产物 → 装载口直接吃掉（引擎默认域三件）】")
    THREE = ("commands", "texts", "tlogs")
    _exts = [os.path.join(FW_ROOT, "extends")]
    for d in THREE:
        check(f"显式只点两域时 {d} 也由向导建出", os.path.exists(PK.domain_path(pkg, d)),
              PK.domain_path(pkg, d))
    info = probe_stack(pkg, exts=_exts)
    check("向导产物可被 probe_stack 装载（ok=True）", info.get("ok") is True, info.get("errors"))
    check("装载告警为空（三张表都在 ⇒ 不报「所有层都没有文件」）",
          info.get("warnings") == [], info.get("warnings"))
    check("空指令表可被引擎消费端装载（零行为，不是读不动）",
          len(CommandRegistry.from_data(PK.read_json(PK.domain_path(pkg, "commands"), {}))) == 0)
    check("空文案表可装载（零行为）",
          len(TextTable.from_data(PK.read_json(PK.domain_path(pkg, "texts"), {}))) == 0)
    check("空流水声明表可装载（零行为）",
          len(KindTable.from_data(PK.read_json(PK.domain_path(pkg, "tlogs"), {}))) == 0)
    # 反证（两态）：抽掉一份 ⇒ 装载口当场点名（告警是判别的，不是恒亮）
    _tp = PK.domain_path(pkg, "tlogs")
    _saved = PK.read_json(_tp, {})
    os.remove(_tp)
    info_neg = probe_stack(pkg, exts=_exts)
    check("反证：抽掉 tlogs.json ⇒ 装载口当场报「所有层里都不存在」",
          info_neg.get("ok") is True
          and sum("所有层" in w for w in (info_neg.get("warnings") or [])) == 1
          and "tlogs" in " ".join(info_neg.get("warnings") or []),
          info_neg.get("warnings"))
    PK.write_json(_tp, _saved)
    # 编辑器 UI 走的那条路（只 POST id/name ⇒ domains=None）必须同样干净。
    # （同一进程里数据包命名空间固定是 `content`，第二次装载命中 sys.modules 缓存 ——
    #   这里要的只是「域落点 + 装载告警」，两者都按**路径**算，与模块缓存无关。）
    scaf_ui = PK.create_package("probe_pkg_ui", "向导默认包", "", None, games_dir_=root)
    check("向导默认路径（domains=None，UI 走这条）同样建出三张引擎默认表",
          all(os.path.exists(PK.domain_path(scaf_ui["dir"], d)) for d in THREE),
          [d for d in THREE if not os.path.exists(PK.domain_path(scaf_ui["dir"], d))])
    info_ui = probe_stack(scaf_ui["dir"], exts=_exts)
    check("向导默认路径产物同样零告警",
          info_ui.get("ok") is True and info_ui.get("warnings") == [],
          f"ok={info_ui.get('ok')} warnings={info_ui.get('warnings')}")

    # ------------------------------------------------------------ 3. 校验
    print("\n【3. schema 校验：合法过、非法拦】")
    good_cmd = {
        "key": "probe_move", "patterns": [r"^probe move(?:\s+(\w+))?$", r"^pm$"],
        "desc": "探测用移动", "category": "navigation", "usage": "probe move <place>",
        "guards": ["player"], "order": 1, "visible": True,
    }
    PK.put_entry(pkg, "commands", "probe_move", good_cmd)
    st = PK.domain_status(pkg, "commands")
    check("合法指令条目通过校验", st["ok"] is True, st)

    bad_cmd = {"key": "probe_bad", "patterns": []}      # patterns minItems=1
    PK.put_entry(pkg, "commands", "probe_bad", bad_cmd)
    st2 = PK.domain_status(pkg, "commands")
    check("非法指令条目被抓（patterns 空）", st2["ok"] is False
          and any(x["key"] == "probe_bad" for x in st2["invalid"]), st2)
    PK.delete_entry(pkg, "commands", "probe_bad")

    PK.put_entry(pkg, "texts", "battle.damage_taken",
                 {"value": "受到 {n} 点伤害", "desc": "受击提示", "category": "battle",
                  "params": ["n"]})
    PK.put_entry(pkg, "texts", "ui.button_confirm", {"value": "确认", "category": "ui"})
    st3 = PK.domain_status(pkg, "texts")
    check("合法文案条目通过校验", st3["ok"] is True, st3)

    PK.put_entry(pkg, "texts", "ui.bad_empty", {"value": ""})   # minLength=1
    st4 = PK.domain_status(pkg, "texts")
    check("非法文案条目被抓（空模板）", st4["ok"] is False
          and any(x["key"] == "ui.bad_empty" for x in st4["invalid"]), st4)
    PK.delete_entry(pkg, "texts", "ui.bad_empty")

    # ------------------------------------------------------------ 4. 闭合
    print("\n【4. 闭合：编辑器写出的数据 → 框架装载即可用】")
    cmd_table = PK.read_json(PK.domain_path(pkg, "commands"), {})
    reg = CommandRegistry.from_data(cmd_table)
    check("指令表可被 CommandRegistry 装载", len(reg) == 1 and "probe_move" in reg, reg.keys())
    check("装载后 validate 无告警", reg.validate() == [], reg.validate())
    check("装载后命中判定可用（别名也命中）",
          reg.hit("probe move north") is not None and reg.hit("pm") is not None)
    check("派生 pattern_map 与声明一致",
          reg.pattern_map()["probe_move"] == "(?:^probe move(?:\\s+(\\w+))?$)|(?:^pm$)",
          reg.pattern_map())

    txt_table = PK.read_json(PK.domain_path(pkg, "texts"), {})
    tt = TextTable.from_data(txt_table)
    check("文案表可被 TextTable 装载", len(tt) == 2, len(tt))
    check("装载后渲染可用", tt.render("battle.damage_taken", n=7) == "受到 7 点伤害",
          tt.render("battle.damage_taken", n=7))
    check("装载后 validate 无告警", tt.validate() == [], tt.validate())
    check("未定义 key 计入 missing（迁移待办可见）",
          tt.render("not.defined") == "not.defined" and tt.missing() == ("not.defined",))

    # 回写 round-trip（编辑器保存不丢字段）
    PK.put_entry(pkg, "texts", "battle.damage_taken", tt.spec("battle.damage_taken").to_dict())
    back = PK.read_json(PK.domain_path(pkg, "texts"), {})
    check("回写 round-trip 保真（value/params/desc 都在）",
          back["battle.damage_taken"]["value"] == "受到 {n} 点伤害"
          and back["battle.damage_taken"]["params"] == ["n"]
          and back["battle.damage_taken"]["desc"] == "受击提示", back)

    # ------------------------------------------------------------ 5. 面板
    print("\n【5. 编辑器面板：词典 + 分组覆盖两域】")
    entries = G.all_entries()
    for d in NEW:
        check(f"{d} 词典非空（面板能给中文名）", bool(entries.get(d)), list(entries))
    for d in NEW:
        gs = G.groups_for(d)
        check(f"{d} 有分组（≥3 组）", len(gs) >= 3, [g["id"] for g in gs])
    check("两域 schema 的顶层字段都分到了组里",
          all(G.GROUPS.get(d) for d in NEW))
finally:
    shutil.rmtree(root, ignore_errors=True)

print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
sys.exit(1 if failed else 0)
