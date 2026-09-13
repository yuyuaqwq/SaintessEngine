#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：**游戏包自带 schema**（D3 步 2 —— schema 搬进包，框架只留回退）。

为什么需要它：`editor/packages.py:DOMAINS` 里 17 个域过去把 schema 写死成「框架里的文件」
（`framework/schemas/<file>`），于是「换个游戏就换一套校验规则」只能来改框架。
步 1 给了 `schema_path()` 的解析顺序（**包内优先 → 框架回退**），但框架 `schemas/` 还是
唯一真源。本门禁把这条路钉死，四件事：

  ★ 2026-09-13 B2b：域的真源在包（框架内置集只剩 8 个引擎域）。
  1. **包内优先**：`games/orlandia/schemas/` 的 17 份是框架那 17 份的**基线副本**（本批有
     演进：只许加子形状/说明），orlandia 声明的每个带 schema 的域解析出来一律是
     **包内那份**（路径含 `<pkg>/schemas/`）；
  2. **无 schemas/ 回退**：没自带 schema 的包仍解析到框架那份（**框架 `schemas/` 就是回退
     基线**），校验口径与之逐字相同
     （不 500、行为等同）；
  3. **改严生效**：包内那份给 primary def 加一条 `required` → 校验**真的**报新错
     （证明吃的是包内那份，不是框架那份的缓存/影子）；
  4. **坏 schema 不炸**：包内 schema 是非法 JSON → 不抛、不 500，**降级回退框架那份**
     并给一条可读告警（容错但**不静默** —— 静默「不校验」是今天反复踩的坑）。

另钉两条「别把回退删了」：框架 `schemas/` 的 17 份必须还在（sha 冻结）；没声明 schema 的域
（`classes` / `loot_vocab`）仍是「不校验」。

跑法：python tests/test_editor_package_schemas.py
退出码：0 = 全过；1 = 有失败。
"""
from __future__ import annotations

import hashlib
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
import _domain_fixtures as FX              # noqa: E402  （内容域只能由包声明：B2b）

REAL_ORLANDIA = os.path.join(ROOT, "games", "orlandia")
FW_SCHEMAS = os.path.join(ROOT, "schemas")
PKG_SCHEMAS = os.path.join(REAL_ORLANDIA, "schemas")
STRICT_FIELD = "__d3_strict_required"      # 用来「改严」的必填字段（占位名，真实数据里没有）

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


def _sha(path):
    """文件内容 sha256（**行尾归一**：CRLF → LF）。

    为什么归一：本处两条断言冻的是「schema **内容**」——① 框架基线 17 份不许悄悄改；
    ② 包内同名 schema 与框架基线是否逐字相同。取原始字节会让**同一个 commit 在两个克隆里
    得出不同哈希**（2026-09-13 实测：独立克隆 core.autocrlf=true → CRLF 5856B；
    游戏仓 submodule 克隆 → LF 5713B，9 份假红）→ 门禁不可移植。
    """
    with open(path, "rb") as f:
        return hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()


def _field_paths_of(path):
    """某个 schema 文件里「会被表单渲染」的字段路径集（与 `test_editor_glossary.field_paths`
    同一套口径：$defs 下每条 properties 递归；用于「包侧只许加子形状、不许丢字段」这条）。"""
    s = json.load(open(path, encoding="utf-8"))
    out = set()

    def walk(props, pre):
        for k, v in (props or {}).items():
            out.add(pre + k)
            if isinstance(v, dict) and isinstance(v.get("properties"), dict):
                walk(v["properties"], pre + k + ".")

    for _name, d in (s.get("$defs") or {}).items():
        walk(d.get("properties") or {}, "")
    return out


def _p(path):
    return os.path.normpath(str(path or "")).replace("\\", "/")


def _in_pkg_schemas(path, pkg_dir):
    return _p(path).startswith(_p(os.path.join(pkg_dir, "schemas")) + "/")


def make_pkg(root, pid, *, schemas=None, decl=None):
    """建一个最小包；`schemas` = {文件名: 原始字节(str) 或 对象}。"""
    pkg = os.path.join(root, pid)
    for sub in ("content/data", "content/rules"):
        os.makedirs(os.path.join(pkg, *sub.split("/")), exist_ok=True)
    # ★ B2b：内容域只能由包声明 —— 本门禁拿 skills 当样板，所以每个包都把它声明上
    #   （不声明的话 `skills` 这个域在这个包里根本不存在，schema 解析无从谈起）。
    decl_out = decl if decl is not None else FX.declare(None, "skills")
    PK.save_manifest(pkg, {"id": pid, "name": pid, "desc": "schema 门禁",
                           "engine": ">=0.1", "domains": list(PK.DOMAINS) + ["skills"],
                           "entry": "content/apply.py", "created": "2026-09-13 00:00:00"})
    if decl_out is not None:
        os.makedirs(os.path.join(pkg, "editor"), exist_ok=True)
        with open(PK.domains_decl_path(pkg), "w", encoding="utf-8", newline="\n") as f:
            f.write(decl_out if isinstance(decl_out, str)
                    else json.dumps(decl_out, ensure_ascii=False, indent=2) + "\n")
    for name, doc in (schemas or {}).items():
        os.makedirs(os.path.join(pkg, "schemas"), exist_ok=True)
        with open(os.path.join(pkg, "schemas", name), "w", encoding="utf-8", newline="\n") as f:
            f.write(doc if isinstance(doc, str)
                    else json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    return pkg


def _fw_schema(fn):
    with open(os.path.join(FW_SCHEMAS, fn), encoding="utf-8") as f:
        return json.load(f)


def _valid_skill_sample(pkg=None):
    """一条**框架口径下合法**的真技能条目（干净数据，305 条里挑第一条能过的）。"""
    with open(os.path.join(REAL_ORLANDIA, "content", "data", "skills.json"), encoding="utf-8") as f:
        tab = json.load(f)
    for k, v in tab.items():
        if isinstance(v, dict) and VD.validate_entry("skills", v, pkg) == []:
            return k, v
    return None, None


def main():
    gd = tempfile.mkdtemp(prefix="fw_pkg_schemas_")
    SRV.GAMES_DIR = gd
    print(f"== 游戏包自带 schema 门禁（临时包目录 {gd}）==")

    # ── 1. 逐字搬：包内 17 份 = 框架 17 份的字节相同副本；17 个域解析到包内那份
    #    （2026-09-13 D3 面板批次起：包侧又**自带**4 份新域 schema —— `races` / `sets` /
    #      `enhance_table` / `panel_rules`。新域在框架侧没有对应文件（域由包声明、schema 随包走），
    #      所以本节守两条：① 框架那 17 份逐字节搬进包、一份不少；② 包内多出来的**只允许**是这 4 份。）
    print("\n【1. 逐字搬 + 包内优先（games/orlandia 自带 17 份 schema）】")
    # ★ B2b：域的真源在包 —— 「哪些域带 schema」要问**包声明**，不是框架内置集
    #   （内置集只剩 8 个引擎域；内容域那批全在包侧）。
    schemas_meta = {d: m for d, m in PK.package_domains(REAL_ORLANDIA).items()
                    if m.get("schema")}
    pkg_files = sorted(f for f in os.listdir(PKG_SCHEMAS) if f.endswith(".schema.json"))
    fw_files = sorted(f for f in os.listdir(FW_SCHEMAS) if f.endswith(".schema.json"))
    # ★ 2026-09-13 收口：包自带**新域** schema（框架侧没有对应文件；域由包声明、schema 随包走）。
    #   D3 面板批次 4 份 + 收口批 `npcs`（NPC 域导出进包）。
    NEW_DOMAIN_SCHEMAS = {"races.schema.json", "sets.schema.json",
                          "enhance_table.schema.json", "panel_rules.schema.json",
                          "npcs.schema.json"}
    check(f"包内 schemas/ = 框架那 {len(fw_files)} 份 + 新域 {len(NEW_DOMAIN_SCHEMAS)} 份",
          len(pkg_files) == len(fw_files) + len(NEW_DOMAIN_SCHEMAS),
          f"{len(pkg_files)} 份 / 框架 {len(fw_files)} 份 / {len(schemas_meta)} 个声明了 schema 的域")
    check("框架那 17 份全在包内（一份不少）", set(fw_files) <= set(pkg_files),
          sorted(set(fw_files) - set(pkg_files)))
    check("包内多出来的正好是新域那 4 份（别的域不许偷偷多）",
          set(pkg_files) - set(fw_files) == NEW_DOMAIN_SCHEMAS,
          sorted(set(pkg_files) - set(fw_files)))
    check("框架 schemas/ 的 17 份**还在**（回退没被删）", len(fw_files) == 17, len(fw_files))
    # ★ 2026-09-13 收口：口径从「逐字节相同」升级成两条更准的（原口径成立的前提已经到期 —— 包侧
    #   schema 本批给 15 处自由形状补了子形状，是**该演进**的那半边；而框架侧那份是
    #   「迁移期基线 + 回退副本」，**必须保持游戏中立**（由 tests/test_no_game_vocabulary.py 守，
    #   实测：把包侧带游戏词 description 的 schema 拷进框架会当场报 11 处中立性违规））：
    #     ① 框架基线**不许悄悄改** —— 17 份 sha256 冻结在本文件里（**行尾归一口径**，
    #        2026-09-13 起：原取原始字节会因 core.autocrlf 差异跨克隆假红），改一个字节即红；
    #     ② 包内同名 schema 的**字段路径集 ⊇ 框架基线** —— 只许加子形状/说明，不许丢字段。
    _FW_BASELINE_SHA = {
        "affix.schema.json": "45d520daf62737400c459d19e3a1c0b06a9464d7966e381cb7f8615501949740",
        "command.schema.json": "8cdacbd60e0827b9430bc4a90ba11125ddd34a2fc50e3d3d403173ce529a0f6f",
        "drop_pools.schema.json": "34f9aaf5c13ce6f19019386a88325e2ee0b365ac4b8a541cc8ad493c4b82a5c7",
        "effect_rules.schema.json": "0de57f5efd8c72855a4c03ac498e7ceeef22f1a36f7a459834aac27288c7e7e5",
        "equip_roster.schema.json": "066c611a96283d8d5a8c88b4ec36f2e1b3e80ce141db042ba7c25c862aa58bfb",
        "instances.schema.json": "6fc513a58926c228a01d707ad6d95e1c834008f0e9eefc8afbb9a54e4d0ff24a",
        "item.schema.json": "18fa1f260d0cf8d14dadcd9032055b75b9e0b4796de3c747061c31a1091d8c2c",
        "legendary_effects.schema.json": "7151d3a418c01f6341816a52193b470467f602cd9b22c46a64e6a7d798f8965f",
        "maps.schema.json": "1493ade7eae208011cb71ee0fce164b11dbb639bead70a1fcc3202343fee74ac",
        "monster.schema.json": "f84ffe89c308611ebdc7803a35e9f299d8442c7fb31f9cf717715938bdf3d4c7",
        "monster_roster.schema.json": "d2cbf083b0380fe94d75ef9324284d43f053c7935587276d6fc225bc73a54e06",
        "passive_proc.schema.json": "11744f7f288bf4b93546e8a943c40d535b8ae461dd9d43b9e161f13f4e8d07c9",
        "pets.schema.json": "575359b695fe83f5779d8040ce938659721d4fc4972e699d1827c1de52433089",
        "pois.schema.json": "ecb77c1cdfe7f3ca8e3ccd4bb6bf80fcc5cab7931269917cc44a5fc3e65eadc4",
        "skill.schema.json": "87c0fef5d779cef4c45750970aec7f4a2ae68ea0af9fc22013f439c018b10f14",
        "text.schema.json": "f72760a1b04e56669fb3d11a031df44b3c4848ecafa46548a707ba51211eb396",
        "tlog.schema.json": "4e43b03352edc74a8eb93a2a27c493933809c731b2137778c75132766652ea19",
    }
    _fw_moved = [f for f, s in _FW_BASELINE_SHA.items() if _sha(os.path.join(FW_SCHEMAS, f)) != s]
    check("框架基线 17 份 sha 冻结（框架侧不许悄悄改；包侧演进不影响它）",
          _fw_moved == [], _fw_moved)
    _evolved, _lost = [], []
    for f in fw_files:
        pk = os.path.join(PKG_SCHEMAS, f)
        if _sha(pk) == _sha(os.path.join(FW_SCHEMAS, f)):
            continue
        _evolved.append(f)
        if not (_field_paths_of(os.path.join(FW_SCHEMAS, f))
                <= _field_paths_of(pk)):
            _lost.append(f)
    check(f"包内同名 schema 只许演进不许丢字段（本批演进 {len(_evolved)} 份）",
          _lost == [], f"丢字段的：{_lost}")
    if _evolved:
        print(f"  ℹ 包侧已演进（框架侧仍是基线；中立性/回退由上面的冻结与 game 内 schema 门禁守）：{_evolved}")

    from_pkg, not_pkg = [], []
    for d in schemas_meta:
        sp = PK.schema_path(REAL_ORLANDIA, d)
        (from_pkg if _in_pkg_schemas(sp, REAL_ORLANDIA) else not_pkg).append(d)
    check(f"包声明的 {len(schemas_meta)} 个带 schema 的域全部解析到 <pkg>/schemas/（包内优先）",
          len(from_pkg) == len(schemas_meta) and not not_pkg,
          f"包内 {len(from_pkg)} / 非包内 {not_pkg}")
    check("解析结果**不是**框架那份（包内优先不是摆设）",
          all(_p(PK.schema_path(REAL_ORLANDIA, d)) != _p(os.path.join(FW_SCHEMAS, m["schema"]))
              for d, m in schemas_meta.items()))
    check("没声明 schema 的域仍是不校验（classes / loot_vocab）",
          PK.schema_path(REAL_ORLANDIA, "classes") is None
          and PK.schema_path(REAL_ORLANDIA, "loot_vocab") is None
          and VD.load_schema("classes", REAL_ORLANDIA) is None)
    check("包内解析不产告警（正常路径必须安静）",
          all(VD.schema_warnings(d, REAL_ORLANDIA) == [] for d in schemas_meta))

    # 零回归：逐域抽样，包内解析 vs 框架解析结论必须逐字相同
    # ★ B2b：「框架解析」= 一个**声明了同样这些域、但不带 schemas/ 的包**（真源在包 →
    #   框架 `schemas/<file>` 回退那份）；不带包已经解析不出内容域了。
    pkg_fw = make_pkg(gd, "pkg_fw_baseline", decl=FX.declare(None, *PK.package_domains(REAL_ORLANDIA)))
    n_cmp, n_skip, mism = 0, 0, []
    for d in schemas_meta:
        _fw_fn = schemas_meta[d].get("schema")
        if not _fw_fn or not os.path.isfile(os.path.join(FW_SCHEMAS, _fw_fn)):
            n_skip += 1          # 包新增域（races/…）框架侧没有回退文件 → 不比
            continue
        fp = PK.domain_path(REAL_ORLANDIA, d)
        if not os.path.isfile(fp):
            continue
        with open(fp, encoding="utf-8") as f:
            tab = json.load(f)
        if not isinstance(tab, dict):
            continue
        for k, v in list(tab.items())[:30]:
            if not isinstance(v, dict):
                continue
            a, b = VD.validate_entry(d, v, REAL_ORLANDIA), VD.validate_entry(d, v, pkg_fw)
            n_cmp += 1
            if a != b:
                mism.append(f"{d}.{k}: 包内={a} 框架={b}")
    check(f"抽样 {n_cmp} 条：包内解析与框架回退解析的校验结论逐字相同（零回归；"
          f"{n_skip} 个新域框架侧无回退文件，未比）",
          mism == [], mism[:3])

    # ── 2. 没有 schemas/ 的包 → 回退框架，行为等同
    print("\n【2. 没自带 schemas/ 的包 → 回退框架 schema（行为等同、不 500）】")
    pkg_noschema = make_pkg(gd, "pkg_noschema")
    check("无包内 schema → 解析到框架 schemas/（回退）",
          _p(PK.schema_path(pkg_noschema, "skills"))
          == _p(os.path.join(FW_SCHEMAS, "skill.schema.json")),
          PK.schema_path(pkg_noschema, "skills"))
    check("无包内 schema → 读到的就是框架那份（逐个 dict 相等）",
          VD.load_schema("skills", pkg_noschema) == _fw_schema("skill.schema.json"))
    check("无包内 schema → 0 告警（缺文件不是错误）",
          VD.schema_warnings("skills", pkg_noschema) == [],
          VD.schema_warnings("skills", pkg_noschema))
    _sk_key, _sk_data = _valid_skill_sample(pkg_noschema)
    bad_skill = {"kind": "魔法"}                                   # 缺 name/source… 必被框架规则拦
    check("无包内 schema → 校验口径与框架逐字相同",
          VD.validate_entry("skills", bad_skill, pkg_noschema)
          == VD.validate_entry("skills", bad_skill, pkg_fw)
          == VD.validate_entry("skills", bad_skill, REAL_ORLANDIA),
          VD.validate_entry("skills", bad_skill, pkg_noschema))

    # ── 3. 包内 schema 改严 → 真的吃包内那份（报新错）
    print("\n【3. 包内 schema 改严（$defs 加一条 required）→ 校验真的报新错】")
    strict = _fw_schema("skill.schema.json")
    target = (strict.get("$defs") or {}).get("skill") or {}
    target["required"] = list(target.get("required") or []) + [STRICT_FIELD]
    pkg_strict = make_pkg(gd, "pkg_strict", schemas={"skill.schema.json": strict})
    check("改严的包 → 解析到包内那份", _in_pkg_schemas(PK.schema_path(pkg_strict, "skills"),
                                                    pkg_strict),
          PK.schema_path(pkg_strict, "skills"))
    check("包内那份的 $defs[skill].required 含新字段；框架那份不含",
          STRICT_FIELD in (VD.load_schema("skills", pkg_strict)["$defs"]["skill"]["required"])
          and STRICT_FIELD not in (VD.load_schema("skills", pkg_fw)["$defs"]["skill"]["required"]))
    check("改严的包没被降级（0 告警：这是**正当的**包内规则）",
          VD.schema_warnings("skills", pkg_strict) == [],
          VD.schema_warnings("skills", pkg_strict))
    e_strict = VD.validate_entry("skills", _sk_data, pkg_strict)
    check("框架下合法的条目，在改严的包里**报新错**（吃的是包内那份）",
          e_strict != [] and any(STRICT_FIELD in x for x in e_strict), e_strict)
    check("同一条数据在别的包 / 不包仍是「合法」（新规则只在改严那个包里）",
          VD.validate_entry("skills", _sk_data, pkg_noschema) == []
          and VD.validate_entry("skills", _sk_data, pkg_fw) == [])

    # ── 4. 坏 schema 不炸：非法 JSON → 降级回退框架 + 可读告警
    print("\n【4. 坏 schema（非法 JSON）→ 不炸、降级回退框架 + 可读告警，绝不 500】")
    pkg_bad = make_pkg(gd, "pkg_badschema", schemas={"skill.schema.json": "{oops"})
    check("坏 schema 的文件仍被解析到（不因坏文件改解析顺序）",
          _in_pkg_schemas(PK.schema_path(pkg_bad, "skills"), pkg_bad))
    check("坏 schema → 不抛，load_schema 降级回退框架那份",
          VD.load_schema("skills", pkg_bad) == _fw_schema("skill.schema.json"))
    w_bad = VD.schema_warnings("skills", pkg_bad)
    check("坏 schema → 可读告警（点名文件 + 说已回退，不静默）",
          len(w_bad) >= 2 and any("skill.schema.json" in w for w in w_bad)
          and any("回退" in w for w in w_bad), w_bad)
    check("坏 schema → 规则没丢：坏条目照样被拦住（不是静默「不校验」）",
          VD.validate_entry("skills", bad_skill, pkg_bad)
          == VD.validate_entry("skills", bad_skill, pkg_fw)
          != [])
    # 另一种坏法：合法 JSON 但缺 primary def（可读报错，不炸）
    pkg_shallow = make_pkg(gd, "pkg_shallow", schemas={"skill.schema.json": {"$defs": {}}})
    e_shallow = VD.validate_entry("skills", _sk_data, pkg_shallow)
    check("包内 schema 缺 primary def → 一句可读错（不抛、不静默放过）",
          len(e_shallow) == 1 and "$defs[skill]" in e_shallow[0], e_shallow)

    # ── 5. HTTP 端到端：四条路都不许 500
    print("\n【5. HTTP 端到端：包内优先 / 回退 / 改严 / 坏 schema 都不许 500】")
    shutil.copytree(REAL_ORLANDIA, os.path.join(gd, "orlandia"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), SRV.H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        st, j = req(base, "GET", "/api/schema/skills?pkg=orlandia")
        check("真包：/api/schema/skills?pkg=orlandia → 200 + 就是包内那份（0 告警）",
              st == 200 and j.get("ok") and (j.get("schema") or {}).get("$defs")
              and (j.get("warnings") or []) == [], f"{st} {j.get('warnings')}")
        st, j = req(base, "GET", "/api/schema/skills?pkg=pkg_noschema")
        check("无自带 schema 的包：HTTP 仍 200 且回退框架那份（行为等同）",
              st == 200 and j.get("ok") and (j.get("schema") or {}).get("$defs")
              and (j.get("warnings") or []) == [], f"{st}")
        st, j = req(base, "POST", "/api/package/pkg_noschema/d/skills/k1/check",
                    {"data": bad_skill})
        check("无自带 schema 的包：只校验接口仍按框架规则拦住坏草稿",
              st == 200 and not j.get("ok") and bool(j.get("errors")), f"{st} {j}")
        st, j = req(base, "GET", "/api/schema/skills?pkg=pkg_strict")
        check("改严的包：HTTP 给出的 schema 真的带新必填",
              st == 200 and STRICT_FIELD in (j.get("schema") or {})
              .get("$defs", {}).get("skill", {}).get("required", []), f"{st}")
        st, j = req(base, "PUT", f"/api/package/pkg_strict/d/skills/{_sk_key}",
                    {"data": _sk_data})
        check("改严的包：PUT 合法于框架的条目 → 422（包内规则真的在拦）",
              st == 422 and any(STRICT_FIELD in x
                                for x in (j.get("validation") or {}).get("errors") or []),
              f"{st} {j.get('validation')}")
        st, j = req(base, "GET", f"/api/package/pkg_strict/d/skills/{_sk_key}")
        check("被拦的条目没落盘（GET → 404）", st == 404, f"{st}")
        st, j = req(base, "GET", "/api/schema/skills?pkg=pkg_badschema")
        check("坏 schema：/api/schema 仍 200（不 500）+ 回退框架 + 告警送到前端",
              st == 200 and j.get("ok") and bool(j.get("schema"))
              and any("回退" in w for w in (j.get("warnings") or [])),
              f"{st} {j.get('warnings')}")
        st, j = req(base, "GET", "/api/package/pkg_badschema")
        check("坏 schema：包概览 200（域概览降级不 500）",
              st == 200 and j.get("ok")
              and len(j.get("domains") or []) == len(PK.effective_domains(pkg_bad)[0]),
              f"{st}")
        st, j = req(base, "GET", "/api/package/pkg_badschema/d/skills")
        check("坏 schema：条目列表 200（域状态降级不 500）", st == 200 and j.get("ok"), f"{st}")
        st, j = req(base, "POST", "/api/package/pkg_badschema/d/skills/k1/check",
                    {"data": bad_skill})
        check("坏 schema：只校验接口 200 且仍能拦住坏草稿（框架规则兜底）",
              st == 200 and not j.get("ok") and bool(j.get("errors")), f"{st} {j}")
        st, j = req(base, "GET", "/api/schema/skills?pkg=pkg_shallow")
        check("坏形状（缺 primary def）：/api/schema 也 200，schema 原文照给（不 500）",
              st == 200 and isinstance(j.get("schema"), dict), f"{st}")
        st, j = req(base, "GET", "/api/package/pkg_shallow/hints")
        check("坏形状的包：联想接口不 500（域级路由逐个走过）", st == 200 and j.get("ok"), f"{st}")
        st, j = req(base, "POST", "/api/package/pkg_badschema/validate")
        check("坏 schema：全包校验 200（不 500）", st == 200, f"{st}")
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(gd, ignore_errors=True)

    print(f"\n===== 结果：通过 {PASS} / {PASS + FAIL} =====")
    for f in FAILURES:
        print("  ❌", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
