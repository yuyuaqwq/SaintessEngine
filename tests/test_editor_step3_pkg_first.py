#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：**域的真源在包**（内置那份只是回退）—— 编辑器扩展步 3。

为什么需要它：`editor/packages.py` 里那份常量过去是「编辑器认识哪些域」的唯一答案，
于是「加一个域」= 来改框架。步 1/2 把**域声明**与 **schema** 搬进了包；本门禁钉住步 3 的
结论 —— **内置那份已降级为「内置默认集」**，只在包没声明时兜底：

  1. **反证「真源在包」**：用 monkeypatch 把内置默认集**整个置空**后，`games/orlandia`
     仍能列出完整 24 域、能读能写能校验、schema 仍生效（HTTP 端到端也走一遍）
     —— 说明框架那份可以被整体拿掉，谁都不靠它；
     ★ 2026-09-13 B2b：内置默认集 19 → **3 个引擎域**（内容域不再内置）；
     orlandia 的 24 域全靠包内那份声明（本门禁把「置空后仍完整」这条钉得更紧了）。
  2. **最小样板**：`examples/minimal-game` 自带 `editor/domains.json` + `schemas/`
     （覆盖它声明的**全部**域），能列能存 —— 新游戏照着它加域即可；
  3. **同名冲突包胜**：包声明与内置同名时包赢、且必有一条可读 warning（不静默）；
  4. **回退仍好使**：没声明 `editor/domains.json` 的包 → 回退内置默认集（8 引擎域 / 0 告警 / 不 500）；
     脚手架建的新包自带声明（不再依赖框架那份）。

跑法：python tests/test_editor_step3_pkg_first.py
退出码：0 = 全过；1 = 有失败。
"""
from __future__ import annotations

import _domain_fixtures as FX             # noqa: E402  （扩展包域元数据：第 4 批）
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

from editor import packages as PK          # noqa: E402
from editor import server as SRV           # noqa: E402
from editor import validate as VD          # noqa: E402

REAL_ORLANDIA = os.path.join(ROOT, "games", "orlandia")
REAL_MINIMAL = os.path.join(ROOT, "examples", "minimal-game")

PASS = 0
FAIL = 0
FAILURES = []


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "PASS", "FAIL", "FAILURES")


def req(base, method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method,
                               headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(r, timeout=180) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw}


def decl_of(pkg_dir) -> dict:
    """直接读包内那份声明文件（= 真源）：只取域 → meta 部分（$开关与包装层去掉），不经框架合并。"""
    raw = decl_of_raw(pkg_dir)
    if isinstance(raw.get("domains"), dict):
        raw = {**{k: v for k, v in raw.items() if k != "domains"}, **raw["domains"]}
    return {k: v for k, v in raw.items() if not str(k).startswith("$")}


def decl_of_raw(pkg_dir) -> dict:
    """包内那份声明文件的**原始内容**（含 `$builtin` 之类的开关）。"""
    with open(PK.domains_decl_path(pkg_dir), encoding="utf-8") as f:
        return json.load(f)


def make_pkg(root, pid, decl, *, domains=None, schemas=None):
    pkg = os.path.join(root, pid)
    for sub in ("content/data", "content/rules"):
        os.makedirs(os.path.join(pkg, *sub.split("/")), exist_ok=True)
    PK.save_manifest(pkg, {"id": pid, "name": pid, "desc": "步 3 门禁", "engine": ">=0.1",
                           "domains": domains if domains is not None else list(ORIG),
                           "entry": "content/apply.py", "created": "2026-09-13 00:00:00"})
    if decl is not None:
        os.makedirs(os.path.join(pkg, "editor"), exist_ok=True)
        with open(PK.domains_decl_path(pkg), "w", encoding="utf-8", newline="\n") as f:
            f.write(decl if isinstance(decl, str)
                    else json.dumps(decl, ensure_ascii=False, indent=2) + "\n")
    for name, doc in (schemas or {}).items():
        os.makedirs(os.path.join(pkg, "schemas"), exist_ok=True)
        with open(os.path.join(pkg, "schemas", name), "w", encoding="utf-8", newline="\n") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
    return pkg


class builtin_emptied:
    """把**内置默认集整个置空**（= 设计稿步 3 的「抽掉框架内置那份」）→ 退出时还原。

    两份都要换：`BUILTIN_DEFAULT_DOMAINS`（真名）与 `DOMAINS`（兼容别名），并清掉各级缓存。
    """

    def __enter__(self):
        self.saved = (PK.BUILTIN_DEFAULT_DOMAINS, PK.DOMAINS)
        empty: dict = {}
        PK.BUILTIN_DEFAULT_DOMAINS = empty
        PK.DOMAINS = empty
        return self

    def __exit__(self, *exc):
        PK.BUILTIN_DEFAULT_DOMAINS, PK.DOMAINS = self.saved
        _clear_caches()
        return False


def _clear_caches():
    PK._DOMAINS_CACHE.clear()
    VD._cache.clear()
    for name in ("_STATUS_CACHE", "_VAL_CACHE", "_HINTS_CACHE", "_OVERVIEW_CACHE"):
        c = getattr(SRV, name, None)
        if isinstance(c, dict):
            c.clear()


ORIG = dict(PK.DOMAINS)                    # 未置空前的内置默认集（比对真值用）


def main():
    gd = tempfile.mkdtemp(prefix="fw_step3_")
    SRV.GAMES_DIR = gd
    print(f"== 编辑器扩展步 3 门禁：域的真源在包（临时包目录 {gd}）==")

    # 造包：真包两份（orlandia / minimal-game 的副本）+ 各种小包
    shutil.copytree(REAL_ORLANDIA, os.path.join(gd, "orlandia"))
    shutil.copytree(REAL_MINIMAL, os.path.join(gd, "minimal-game"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # 同名覆盖：拿**内置（引擎）域** commands 做样板（内容域不在内置集里，属「新域」那条路）
    pkg_conflict = make_pkg(gd, "pkg_conflict", {"commands": {
        "label": "本包指令", "kind": "data", "schema": "schemas/my_command.schema.json",
        "primary": "my_command", "icon": "🎯"}}, schemas={"my_command.schema.json": {
            "$defs": {"my_command": {"type": "object", "required": ["name"],
                                     "properties": {"name": {"type": "string"}}}}}})
    pkg_plain = make_pkg(gd, "pkg_plain", None)                       # 没声明 → 回退内置
    pkg_opt = make_pkg(gd, "pkg_opt", {"$builtin": False, "lake_spots": {
        "label": "钓鱼点", "kind": "rules", "icon": "🎣"}})
    pkg_opt_bad = make_pkg(gd, "pkg_opt_bad", {"$builtin": "no", "lake_spots": {
        "label": "钓鱼点", "kind": "rules"}})
    pkg_opt_empty = make_pkg(gd, "pkg_opt_empty", {"$builtin": False})
    pkg_wrap = make_pkg(gd, "pkg_wrap", {"domains": {"lake_spots": {
        "label": "钓鱼点", "kind": "rules"}}, "$builtin": False})

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), SRV.H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    orl = os.path.join(gd, "orlandia")

    try:
        # ──────────────────────────────────────────────────────────── 1. 真源在包（库级）
        print("\n【1. 反证：内置默认集置空后，orlandia 仍完整（库级）】")
        with builtin_emptied():
            decl = decl_of(orl)
            n_orl = len(decl)
            eff, warns = PK.effective_domains(orl)
            check("内置默认集置空 → 共享常量确实为空（置空生效）",
                  PK.DOMAINS == {} and PK.BUILTIN_DEFAULT_DOMAINS == {})
            # ★ 2026-09-23 第 4 批：orlandia depends 了扩展包 ⇒ 域表 = 扩展包带来的 5 个（在前）
            #   ∪ 包自己声明的 {n_orl} 个（同名以包声明为准）。★ 奥兰迪亚现在**不再**重复声明
            #   那 8 条（3 个通用表 + 5 个游戏级形状）—— 分层就是干这个的：包只写它自己的内容域。
            _ext_only = set(eff) - set(decl)
            check(f"orlandia 仍列出**完整**域表（{n_orl} 个包内声明 + {len(_ext_only)} 个扩展包带来的）",
                  set(decl) <= set(eff) and _ext_only <= set(FX.EXT_DOMAINS),
                  f"{len(eff)} vs {n_orl}；多出 {sorted(_ext_only)}")
            check("包内声明的那部分逐字段 == 声明文件（不是框架那份）",
                  all(eff[k] == decl[k] for k in decl),
                  {k: (decl.get(k), eff.get(k)) for k in decl if decl.get(k) != eff.get(k)})
            check("来源标注对得上（包声明的 → package；扩展包带来的 → extension）",
                  all(PK.domain_source(orl, d) == "package" for d in decl)
                  and all(PK.domain_source(orl, d) == "extension" for d in _ext_only))
            check("0 告警（等值搬迁 + 无冲突）", warns == [], warns)
            check(f"包概览 {len(eff)} 域 / 全 ok", _overview_ok(orl))
            check("条目列表可用（pets 非空）", PK.list_entries(orl, "pets")["count"] > 0,
                  PK.list_entries(orl, "pets")["count"])
            check("域状态 ok（校验链路不依赖框架常量）",
                  PK.domain_status(orl, "skills")["ok"] is True, PK.domain_status(orl, "skills"))
            check("坏技能条目仍被包内 schema 抓住",
                  PK.domain_status(orl, "skills")["ok"] is True
                  and VD.validate_entry("skills", {"kind": "魔法"}, orl) != [],
                  VD.validate_entry("skills", {"kind": "魔法"}, orl))
            check("全部域的 schema 都解析到包内那份（无一处落到框架回退）",
                  all(os.path.normpath(PK.schema_path(orl, d) or "").startswith(
                      os.path.normpath(os.path.join(orl, "schemas")))
                      for d in eff if eff[d].get("schema")), _nonpkg_schemas(orl, eff))
            PK.put_entry(orl, "skills", "sk_step3_probe", {"name": "步3探针", "kind": "冲击",
                                                           "exprs": ["atk*1.0"]})
            check("能写新条目（守卫技能域，写的是真文件）",
                  PK.get_entry(orl, "skills", "sk_step3_probe")["name"] == "步3探针")
            check("能删（读写都没靠框架那份常量）", PK.delete_entry(orl, "skills", "sk_step3_probe"))

        # ──────────────────────────────────────────────────────────── 2. 真源在包（HTTP）
        print("\n【2. 同一条结论走 HTTP 端到端（仍在内置置空状态）】")
        with builtin_emptied():
            st, j = req(base, "GET", "/api/domains?pkg=orlandia")
            ids = [d["id"] for d in (j.get("domains") or [])]
            # ★ 2026-09-23 第 4 批：orlandia depends 了扩展包 ⇒ 域表 = 扩展包带来的 5 个（在前）
            #   ∪ 包自己声明的 106 个（同名以包声明为准，位置保持首次插入）。
            check("域注册表 200 且含全部包声明域（外加扩展包带来的那几个）",
                  st == 200 and set(decl_of(orl)) <= set(ids), f"{st} {len(ids)}")
            _ext_ids = set(FX.EXT_DOMAINS)
            check("域注册表里包声明与扩展包带的域都标了来源（from_package）",
                  all(d["from_package"] for d in j["domains"] if d["id"] in decl_of(orl))
                  and all(not d["from_package"] for d in j["domains"]
                          if d["id"] in _ext_ids and d["id"] not in decl_of(orl)))
            st, j = req(base, "GET", "/api/domains")
            check("不带包时域注册表 200 且为空（= 框架内置那份真被拿掉了，没人依赖它）",
                  st == 200 and (j.get("domains") or []) == [], f"{st} {len(j.get('domains') or [])}")
            st, j = req(base, "GET", "/api/package/orlandia")
            od = {d["id"]: d for d in (j.get("domains") or [])}
            check("包概览 200 / 域表齐全（= 有效域表）/ 逐域有 status",
                  st == 200 and len(od) == len(PK.effective_domains(orl)[0])
                  and all("ok" in v for v in od.values()), f"{st} {len(od)}")
            st, j = req(base, "GET", "/api/package/orlandia/d/items?limit=1")
            check("条目列表 200（分页仍好使）", st == 200 and j.get("count", 0) > 0, f"{st}")
            st, j = req(base, "GET", "/api/package/orlandia/d/pets/nonexistent_zz")
            check("单条读 404（不是 500）", st == 404, f"{st}")
            st, j = req(base, "PUT", "/api/package/orlandia/d/skills/sk_step3_http",
                        {"data": {"name": "步3HTTP", "kind": "冲击", "exprs": ["atk*1.1"]}})
            check("现编的粗条目被包内 schema 拦下（422 —— schema 真在起作用）",
                  st == 422 and not j.get("ok"), f"{st}")
            sk_key = PK.list_entries(orl, "skills")["entries"][0]["key"]
            valid_skill = dict(PK.get_entry(orl, "skills", sk_key))
            valid_skill["name"] = "步3HTTP探针"
            st, j = req(base, "PUT", "/api/package/orlandia/d/skills/sk_step3_http",
                        {"data": valid_skill})
            check("PUT 合法条目 200（拿真仓已存在那条克隆一份）",
                  st == 200 and j.get("ok"), f"{st} {j.get('message')}")
            st, j = req(base, "PUT", "/api/package/orlandia/d/skills/sk_step3_bad",
                        {"data": {"kind": "魔法"}})
            check("PUT 非法条目 422（包内 schema 仍在拦）",
                  st == 422 and not j.get("ok"), f"{st}")
            st, j = req(base, "GET", "/api/package/orlandia/d/skills/sk_step3_bad")
            check("被拦的条目没落盘", st == 404, f"{st}")
            st, j = req(base, "DELETE", "/api/package/orlandia/d/skills/sk_step3_http")
            check("DELETE 200（删得掉）", st == 200 and j.get("ok"), f"{st}")
            st, j = req(base, "POST", "/api/package/orlandia/validate")
            check("全包校验 200 且 ok", st == 200 and j.get("ok") is True, f"{st}")
            st, j = req(base, "GET", "/api/package/orlandia/d/pets")
            check("域级视图路由不 500", st == 200, f"{st}")

        # ──────────────────────────────────────────────────────────── 3. minimal-game 样板
        print("\n【3. 最小样板 examples/minimal-game：自带域声明 + schema 覆盖全部域】")
        eff_m, warns_m = PK.effective_domains(REAL_MINIMAL)
        decl_m = decl_of(REAL_MINIMAL)
        check("样板包自带 editor/domains.json 且被认到",
              os.path.isfile(PK.domains_decl_path(REAL_MINIMAL))
              and set(PK.package_domains(REAL_MINIMAL)) == set(decl_m), sorted(decl_m))
        check("声明里写了 $builtin: false（域表 = 它自己声明的，不夹带框架内置域）",
              PK.package_uses_builtin_defaults(REAL_MINIMAL) is False)
        # ★ 2026-09-23 第 4 批：`$builtin: false` 只关「引擎默认集」那一层 ——
        #   样板包 depends 了 ext_combat，它带来的 effect_rules / passive_proc 照样在
        #   （域跟消费端走：这两个域的声明现在也住在 ext_combat 里）。样板自己那 7 个一个不少。
        check("有效域表 ⊇ 声明那 7 个（$builtin:false 只关引擎默认集，扩展包域照旧）",
              set(decl_m) <= set(eff_m)
              and set(eff_m) - set(decl_m) <= set(FX.EXT_DOMAINS),
              list(eff_m))
        check("框架内置域一个都没混进来（items / instances / texts 等不在）",
              not (set(eff_m) & {"items", "instances", "texts", "commands", "maps"}))
        check("每一域的来源都是 package", all(PK.domain_source(REAL_MINIMAL, d) == "package"
                                          for d in eff_m))
        check("每域 schema 都在包内（自带、不落框架回退）",
              all(os.path.normpath(PK.schema_path(REAL_MINIMAL, d) or "").startswith(
                  os.path.normpath(os.path.join(REAL_MINIMAL, "schemas"))) for d in eff_m),
              _nonpkg_schemas(REAL_MINIMAL, eff_m))
        check("声明里每个域都指向一份**存在**的包内 schema 文件",
              all(os.path.isfile(os.path.join(REAL_MINIMAL, "schemas",
                                              str(decl_m[d]["schema"]).split("/")[-1]))
                  for d in decl_m))
        check("0 告警（声明干净）", warns_m == [], warns_m)
        check("自带的『包新增域』mech_verbs 有真数据（3 个机制动词）",
              PK.list_entries(REAL_MINIMAL, "mech_verbs")["count"] == 3,
              PK.list_entries(REAL_MINIMAL, "mech_verbs")["count"])
        check("mech_verbs 条目全部通过包内 schema",
              PK.domain_status(REAL_MINIMAL, "mech_verbs")["ok"] is True)
        check("样板包自带 game.json 清单（能被编辑器当包打开）",
              PK.resolve_package(REAL_MINIMAL) == REAL_MINIMAL)
        check("清单 domains 与包内声明一致",
              set(PK.load_manifest(REAL_MINIMAL)["domains"]) == set(decl_m))

        # ──────────────────────────────────────────────────────────── 4. 样板包能列能存
        print("\n【4. 样板包副本走 HTTP：清单 / 列表 / 存 / 校验 / schema】")
        st, j = req(base, "GET", "/api/domains?pkg=minimal-game")
        doms_m = {d["id"]: d for d in (j.get("domains") or [])}
        check("域注册表 200 且 7 域、每一域 from_package",
              st == 200 and len(doms_m) == 7 and all(d["from_package"] for d in doms_m.values()),
              f"{st} {sorted(doms_m)}")
        check("域注册表 0 告警", (j.get("warnings") or []) == [], j.get("warnings"))
        st, j = req(base, "GET", "/api/package/minimal-game")
        od = {d["id"]: d for d in (j.get("domains") or [])}
        check("包概览 200 / 7 域 / 全 ok",
              st == 200 and j.get("ok") and len(od) == 7 and all(v["ok"] for v in od.values()),
              f"{st}")
        # ★ B2b：package_domains = 差值口径（内置集里没有的域）= 样板包声明的内容域 + mech_verbs
        _expect_pkgonly = sorted(set(eff_m) - set(PK.DOMAINS))
        check(f"package_domains（内置没有的域）== {_expect_pkgonly}",
              sorted(j.get("package_domains") or []) == _expect_pkgonly,
              j.get("package_domains"))
        st, j = req(base, "GET", "/api/package/minimal-game/d/mech_verbs")
        check("自带的域能列（3 条）", st == 200 and j.get("count") == 3, f"{st}")
        st, j = req(base, "PUT", "/api/package/minimal-game/d/mech_verbs/quake_vent",
                    {"data": {"key": "quake_vent", "name": "震炉", "desc": "示例：新增一个动词"}})
        check("自带的域能存（PUT 200）", st == 200 and j.get("ok"), f"{st} {j.get('message')}")
        st, j = req(base, "GET", "/api/package/minimal-game/d/mech_verbs/quake_vent")
        check("存进去的真在（读回一致）",
              st == 200 and (j.get("data") or {}).get("name") == "震炉", f"{st}")
        st, j = req(base, "PUT", "/api/package/minimal-game/d/mech_verbs/bad_verb",
                    {"data": {"name": "缺 key 与 desc"}})
        check("不合法条目被拦住（422，包内 schema 在起作用）",
              st == 422 and not j.get("ok"), f"{st}")
        st, j = req(base, "GET", "/api/package/minimal-game/d/mech_verbs/bad_verb")
        check("被拦的没落盘", st == 404, f"{st}")
        st, j = req(base, "DELETE", "/api/package/minimal-game/d/mech_verbs/quake_vent")
        check("能删", st == 200 and j.get("ok"), f"{st}")
        st, j = req(base, "GET", "/api/schema/skills?pkg=minimal-game")
        pkg_schema = json.load(open(os.path.join(REAL_MINIMAL, "schemas",
                                                "skill.schema.json"), encoding="utf-8"))
        check("schema 端点给出的是**包内那份**（不是框架 schemas/）",
              st == 200 and j.get("ok") and j.get("schema") == pkg_schema, f"{st}")
        st, j = req(base, "GET", "/api/schema/classes?pkg=minimal-game")
        check("框架原本「无 schema」的域（classes）在样板包里也有 schema",
              st == 200 and j.get("ok") and bool((j.get("schema") or {}).get("$defs")), f"{st}")
        st, j = req(base, "POST", "/api/package/minimal-game/validate")
        check("全包校验 200 / ok", st == 200 and j.get("ok") is True, f"{st}")

        # ──────────────────────────────────────────────────────────── 5. 同名冲突包胜
        print("\n【5. 内置与包声明冲突：包胜 + 必进 warning（不静默）】")
        eff_c, warns_c = PK.effective_domains(pkg_conflict)
        check("同名域以包为准（5 个字段全按包里那份）",
              eff_c["commands"] == PK.package_domains(pkg_conflict)["commands"], eff_c["commands"])
        check("内置那份的值一个都没混进来",
              eff_c["commands"] != ORIG["commands"]
              and eff_c["commands"]["label"] == "本包指令"
              and eff_c["commands"]["icon"] == "🎯", eff_c["commands"])
        check("来源标记为 package", PK.domain_source(pkg_conflict, "commands") == "package")
        check("必产 warning（点名域名 + 「覆盖」+ 改了哪些字段）",
              len(warns_c) == 1 and "commands" in warns_c[0] and "覆盖" in warns_c[0]
              and "label" in warns_c[0] and "schema" in warns_c[0], warns_c)
        check("框架那份常量本身没被改",
              PK.BUILTIN_DEFAULT_DOMAINS["commands"] == ORIG["commands"])
        check("覆盖后的 schema 也是包内那份",
              os.path.normpath(PK.schema_path(pkg_conflict, "commands"))
              == os.path.normpath(os.path.join(pkg_conflict, "schemas", "my_command.schema.json")),
              PK.schema_path(pkg_conflict, "commands"))
        st, j = req(base, "GET", "/api/domains?pkg=pkg_conflict")
        d_c = {d["id"]: d for d in (j.get("domains") or [])}
        check("HTTP 侧同名覆盖也生效（label 用包值 / from_package=True）",
              st == 200 and d_c["commands"]["label"] == "本包指令"
              and d_c["commands"]["from_package"] is True, f"{st} {d_c.get('commands')}")
        check("HTTP 侧把「覆盖」warning 送到前端",
              any("覆盖" in w for w in (j.get("warnings") or [])), j.get("warnings"))
        with builtin_emptied():
            eff_c2, _w = PK.effective_domains(pkg_conflict)
            check("内置置空后，同名域仍完整可用（声明写全 = 不需要那份回退）",
                  eff_c2["commands"] == PK.package_domains(pkg_conflict)["commands"]
                  and PK.domain_source(pkg_conflict, "commands") == "package")

        # ──────────────────────────────────────────────────────────── 6. 回退仍好使
        print("\n【6. 没声明的包 → 回退内置默认集（不 500）】")
        eff_p, warns_p = PK.effective_domains(pkg_plain)
        check("没声明 → 有效域表逐字段等于内置默认集",
              eff_p == ORIG and len(eff_p) == len(ORIG), f"{len(eff_p)} vs {len(ORIG)}")
        check("没声明 → 0 告警（缺文件不是错误）", warns_p == [], warns_p)
        check("来源标记为 builtin（回退）",
              all(PK.domain_source(pkg_plain, d) == "builtin" for d in eff_p))
        st, j = req(base, "GET", "/api/package/pkg_plain")
        check("包概览 200 / 回退域表可见",
              st == 200 and len(j.get("domains") or []) == len(ORIG), f"{st}")
        st, j = req(base, "GET", "/api/domains?pkg=pkg_plain")
        check("域注册表 = 内置默认集 / 全部 from_package=False（是回退，不是包声明）",
              st == 200 and len(j.get("domains") or []) == len(ORIG)
                  and not any(d["from_package"] for d in j["domains"]), f"{st}")
        # ★ B2b：脚手架只认**内置（引擎）域**（内容域要包自己声明；见 packages.create_package）
        scaf = PK.create_package("scaffold_pkg", "脚手架包", "步 3", ["commands", "texts"],
                                 games_dir_=gd)
        check("脚手架建包：自带 editor/domains.json（不再靠框架那份）",
              os.path.isfile(PK.domains_decl_path(scaf["dir"])))
        check("脚手架声明的域来源 == package",
              all(PK.domain_source(scaf["dir"], d) == "package" for d in PK.declared_domain_ids(scaf["dir"])))
        eff_s, warns_s = PK.effective_domains(scaf["dir"])
        check("等值声明不产 warning（零回归）/ 域表仍等于内置默认集",
              warns_s == [] and len(eff_s) == len(ORIG), f"{warns_s} {len(eff_s)}")

        # ──────────────────────────────────────────────────────────── 7. `$builtin` 开关
        print("\n【7. `\"$builtin\": false`（只用本包声明的域）】")
        eff_o, warns_o = PK.effective_domains(pkg_opt)
        check("关掉内置默认集 → 域表只有自己声明的那个", list(eff_o) == ["lake_spots"], list(eff_o))
        check("落点按 kind=rules（无需框架那份）",
              os.path.normpath(PK.domain_path(pkg_opt, "lake_spots"))
              == os.path.normpath(os.path.join(pkg_opt, "content", "rules", "lake_spots.json")))
        eff_b, warns_b = PK.effective_domains(pkg_opt_bad)
        check("非布尔写法 → 可读告警 + 按 true 处理（内置默认集照常兜底）",
              PK.package_uses_builtin_defaults(pkg_opt_bad) is True
              and len(eff_b) == len(ORIG) + 1 and "lake_spots" in eff_b
              and any("$builtin" in w for w in warns_b), f"{len(eff_b)} {warns_b}")
        eff_e, warns_e = PK.effective_domains(pkg_opt_empty)
        check("关掉且一条可用声明都没有 → 域表为空 + 可读 warning（不抛）",
              eff_e == {} and any("$builtin" in w for w in warns_e), warns_e)
        st, j = req(base, "GET", "/api/domains?pkg=pkg_opt_empty")
        check("空域表的包 HTTP 仍 200（不 500）", st == 200, f"{st}")
        st, j = req(base, "GET", "/api/package/pkg_opt_empty")
        check("空域表的包概览也 200（降级不静默）", st == 200 and j.get("domain_warnings"), f"{st}")
        st, j = req(base, "GET", "/api/domains?pkg=pkg_wrap")
        check('{"domains": {…}} 包装写法也认 `$builtin`',
              st == 200 and [d["id"] for d in j["domains"]] == ["lake_spots"],
              f"{st} {[d['id'] for d in (j.get('domains') or [])]}")
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(gd, ignore_errors=True)
        _clear_caches()

    print(f"\n===== 结果：通过 {PASS} / {PASS + FAIL} =====")
    for f in FAILURES:
        print("  ❌", f)
    return 1 if FAIL else 0


def _overview_ok(pkg_dir) -> bool:
    """概览列出的域数 == **有效域表**（含 depends 的扩展包带来的域，2026-09-23 第 4 批）且全 ok。"""
    ov = PK.package_overview(pkg_dir)
    want = len(PK.effective_domains(pkg_dir)[0])
    return len(ov["domains"]) == want and all(d.get("ok") for d in ov["domains"])


def _nonpkg_schemas(pkg_dir, eff) -> list:
    """哪些域的 schema 没解析到包内（应当为空）。"""
    out = []
    for d, meta in eff.items():
        if not meta.get("schema"):
            continue
        p = PK.schema_path(pkg_dir, d) or ""
        if not os.path.normpath(p).startswith(os.path.normpath(os.path.join(pkg_dir, "schemas"))):
            out.append((d, p))
    return out


if __name__ == "__main__":
    sys.exit(main())
