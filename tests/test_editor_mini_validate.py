# -*- coding: utf-8 -*-
"""内置极简校验器（没装 jsonschema 时编辑器用的 fallback）门禁。

守三条：
  ① **anyOf 语义 = 任一支通过即通过**，oneOf = 恰好一支通过 —— 修复前 `_mini_validate`
     把 anyOf/oneOf 每个分支的错误都累加，于是真包 `drop_pools.json` 的 596 个池里
     **84 个假红**（`n` 是 `anyOf:[integer, array]` 形状，整数形态会去撞数组分支、
     区间形态会去撞整数分支）。
  ② 该拦的还拦得住：缺必填 / 类型错 / 枚举外取值 / 键名非法（含空格） / 结构越界。
  ③ **金标准对照**：同一批样例，内置校验器与 jsonschema 的结论**逐例一致**；
     内置器只允许「漏报」（保守，放过），**不允许「假红」**（编辑器里假红比漏报贵）。

跑法：python tests/test_editor_mini_validate.py
      本机没装 jsonschema 时也能跑（对照段自动跳过；①② 段本来就不依赖 jsonschema）。
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True

from editor import validate as VD          # noqa: E402
import _domain_fixtures as FX              # noqa: E402  （内容域只能由包声明：B2b）

POOLS_JSON = os.path.join(ROOT, "games/orlandia/content/data/drop_pools.json")
SKILLS_JSON = os.path.join(ROOT, "games/orlandia/content/data/skills.json")
ITEMS_JSON = os.path.join(ROOT, "games/orlandia/content/data/items.json")

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


class _force_mini:
    """强制走内置极简校验器路径（把 `VD._js` 置 None，与打包分发/无依赖机器一致）。"""

    def __enter__(self):
        self.saved_js = VD._js
        self.saved_mini = VD._mini_validate
        VD._js = None
        return self

    def __exit__(self, *exc):
        VD._js = self.saved_js
        VD._mini_validate = self.saved_mini
        return False


# ───────────────────────── 冻结的「修复前」实现（仅对照，勿用于生产）
def _legacy_mini_validate(sch, val, defs, path):
    """修复前的 `editor/validate.py:_mini_validate` 逐字副本 —— 用来证明「修的是真 bug」。"""
    errs = []
    if not isinstance(sch, dict):
        return errs
    if "$ref" in sch:
        ref = sch["$ref"].split("/")[-1]
        return _legacy_mini_validate(defs.get(ref, {}), val, defs, path)
    for key in ("allOf", "anyOf", "oneOf"):
        if key in sch:
            for s in sch[key]:
                errs += _legacy_mini_validate(s, val, defs, path)

    t = sch.get("type")
    if t == "object" and not isinstance(val, dict):
        return [f"{VD._path_join(path)}: 期望 object，实为 {type(val).__name__}"]
    if t == "array" and not isinstance(val, list):
        return [f"{VD._path_join(path)}: 期望 array，实为 {type(val).__name__}"]
    if t == "string" and not isinstance(val, str):
        return [f"{VD._path_join(path)}: 期望 string，实为 {type(val).__name__}"]
    if t in ("number", "integer") and not isinstance(val, (int, float)):
        return [f"{VD._path_join(path)}: 期望 {t}，实为 {type(val).__name__}"]
    if t == "boolean" and not isinstance(val, bool):
        return [f"{VD._path_join(path)}: 期望 boolean"]

    if isinstance(val, str):
        if sch.get("minLength") and len(val) < sch["minLength"]:
            errs.append(f"{VD._path_join(path)}: 长度需 ≥ {sch['minLength']}")
        if sch.get("enum") and val not in sch["enum"]:
            errs.append(f"{VD._path_join(path)}: 取值 {val!r} 不在枚举内")
    elif isinstance(val, (int, float)) and not isinstance(val, bool):
        if sch.get("minimum") is not None and val < sch["minimum"]:
            errs.append(f"{VD._path_join(path)}: 需 ≥ {sch['minimum']}")
        if sch.get("maximum") is not None and val > sch["maximum"]:
            errs.append(f"{VD._path_join(path)}: 需 ≤ {sch['maximum']}")

    if isinstance(val, dict):
        for r in sch.get("required", []):
            if r not in val:
                errs.append(f"{VD._path_join(path + [r])}: 必填字段缺失")
        props = sch.get("properties") or {}
        for k, v in val.items():
            if k in props:
                errs += _legacy_mini_validate(props[k], v, defs, path + [k])
            elif sch.get("additionalProperties") is False:
                errs.append(f"{VD._path_join(path + [k])}: 不允许的字段")
    if isinstance(val, list) and sch.get("items"):
        for i, x in enumerate(val):
            errs += _legacy_mini_validate(sch["items"], x, defs, path + [i])
    return errs


# ───────────────────────── 真数据
pools = json.load(open(POOLS_JSON, encoding="utf-8"))
POOL_INT_N = "boss:inst_abyss_gate"        # rolls[].n 为整数形态
POOL_RANGE_N = "chest:high"                # rolls[].n 为 [min,max] 形态


_CONTENT_PKG = None          # 声明的内容域（skills / items）的临时包 —— 由 main() 建


def _pkg_for(dom):
    """该域校验要带的包目录。

    ★ B2b：skills / items 是**内容域** —— 框架内置集里没有它们，域元数据（schema 名）
    只能由**包声明**得到；这个临时包不带 `schemas/`，所以 schema 仍解析到框架
    `schemas/<file>` 回退副本 → 校验口径与改造前逐字相同。引擎域（drop_pools）走内置那份。
    """
    return _CONTENT_PKG if dom in ("skills", "items") else None


def _jsonschema_ok(dom, entry, pkg=None):
    """金标准：直接问 jsonschema（本机装了才有）。返回 True/False/None。"""
    if VD._js is None:
        return None
    schema, name = VD.primary_def(dom, pkg if pkg is not None else _pkg_for(dom))
    defs = schema.get("$defs") or {}
    sub = dict(schema)
    sub.pop("$id", None)
    v = VD._js.Draft202012Validator(defs.get(name), resolver=VD._js.RefResolver.from_schema(sub))
    return not list(v.iter_errors(entry))


def main() -> int:                          # noqa: C901
    print("== 编辑器内置极简校验器（无 jsonschema 的 fallback）门禁 ==")

    # ★ B2b：skills / items 是内容域 —— 建一个「只声明域、不带 schemas/」的临时包，
    #   让它们的 schema 解析到框架 `schemas/<file>` 回退副本（口径与改造前逐字相同）。
    global _CONTENT_PKG
    _tmp = tempfile.mkdtemp(prefix="fw_mini_val_")
    _CONTENT_PKG = os.path.join(_tmp, "content_pkg")
    FX.declare(_CONTENT_PKG, "skills", "items")

    has_js = VD._js is not None
    print(f"  jsonschema 可用: {has_js}（{'装了，用作金标准对照' if has_js else '没装，对照段跳过'}）")
    print(f"  真包掉落池: {len(pools)} 池 —— {os.path.relpath(POOLS_JSON, ROOT)}")

    # ── ① anyOf：两种形态都过；坏形态仍被拦 ──────────────────────────
    print("\n[1] anyOf 语义（`n` = anyOf[integer, [int,int]]）—— 内置路径")
    with _force_mini():
        check("整数形态 n 通过", VD.validate_entry("drop_pools", pools[POOL_INT_N]) == [],
              f"{POOL_INT_N}: {VD.validate_entry('drop_pools', pools[POOL_INT_N])}")
        check("区间形态 n 通过", VD.validate_entry("drop_pools", pools[POOL_RANGE_N]) == [],
              f"{POOL_RANGE_N}: {VD.validate_entry('drop_pools', pools[POOL_RANGE_N])}")

        pool_int = {"type": "table", "rolls": [{"pool": "sub_x", "n": 5}]}
        pool_rng = {"type": "table", "rolls": [{"pool": "sub_x", "n": [1, 2]}]}
        pool_one = {"type": "table", "rolls": [{"pool": "sub_x", "n": [1]}]}
        pool_str = {"type": "table", "rolls": [{"pool": "sub_x", "n": "5"}]}
        pool_frac = {"type": "table", "rolls": [{"pool": "sub_x", "n": 1.5}]}
        check("n=5（整数）通过", VD.validate_entry("drop_pools", pool_int) == [],
              str(VD.validate_entry("drop_pools", pool_int)))
        check("n=[1,2] 通过", VD.validate_entry("drop_pools", pool_rng) == [],
              str(VD.validate_entry("drop_pools", pool_rng)))
        check("n=[1]（区间只有一项）被拦", len(VD.validate_entry("drop_pools", pool_one)) == 1,
              str(VD.validate_entry("drop_pools", pool_one)))
        check("n='5'（字符串）被拦", len(VD.validate_entry("drop_pools", pool_str)) == 1,
              str(VD.validate_entry("drop_pools", pool_str)))
        check("n=1.5（非整数）被拦", len(VD.validate_entry("drop_pools", pool_frac)) == 1,
              str(VD.validate_entry("drop_pools", pool_frac)))
        check("anyOf 全失败只报 1 条（不逐支累加）",
              len(VD.validate_entry("drop_pools", pool_str)) == 1)

        # allOf 仍是「全部都要过，错误累加」
        errs_all = VD._mini_validate({"allOf": [{"type": "string"}, {"minimum": 3}]}, 1, {}, [])
        check("allOf 仍累加（type/minimum 各自报）", len(errs_all) == 2, str(errs_all))
        # oneOf = 恰好一支
        check("oneOf 恰好一支通过",
              VD._mini_validate({"oneOf": [{"type": "integer"}, {"type": "string"}]}, 5, {}, []) == [])
        check("oneOf 零支通过被拦",
              len(VD._mini_validate({"oneOf": [{"type": "integer"}, {"type": "string"}]}, 1.5, {}, [])) == 1)
        check("oneOf 两支同时通过被拦",
              len(VD._mini_validate({"oneOf": [{"type": "number"}, {"type": "integer"}]}, 5, {}, [])) == 1)

    # ── ② 该拦的还拦得住（内置路径；含空格键名的表）─────────────────
    print("\n[2] 拦截能力（内置路径）")
    table_sch = {
        "type": "object",
        "propertyNames": {"pattern": "^[a-z][a-z0-9_]*$"},
        "additionalProperties": {
            "type": "object",
            "required": ["kind"],
            "properties": {"kind": {"enum": ["attack", "defense"]},
                           "lv": {"type": "integer", "minimum": 1}},
        },
    }
    good_row = {"row_a": {"kind": "attack", "lv": 3}}
    with _force_mini():
        check("合法表通过", VD._mini_validate(table_sch, good_row, {}, []) == [],
              str(VD._mini_validate(table_sch, good_row, {}, [])))
        e = VD._mini_validate(table_sch, {"bad key": {"kind": "attack"}}, {}, [])
        check("含空格的 key 被拦", len(e) == 1, str(e))
        e = VD._mini_validate(table_sch, {"row_a": {"lv": 3}}, {}, [])
        check("缺必填字段被拦", len(e) == 1 and "必填" in e[0], str(e))
        e = VD._mini_validate(table_sch, {"row_a": {"kind": "wizard"}}, {}, [])
        check("枚举外取值被拦", len(e) == 1 and "枚举" in e[0], str(e))
        e = VD._mini_validate(table_sch, {"row_a": {"kind": "attack", "lv": "3"}}, {}, [])
        check("类型错被拦", len(e) == 1 and "integer" in e[0], str(e))
        e = VD._mini_validate(table_sch, {"row_a": {"kind": "attack", "lv": 0}}, {}, [])
        check("minimum 越界被拦", len(e) == 1 and "1" in e[0], str(e))
        e = VD._mini_validate(table_sch, {"row_a": {"kind": "attack", "lv": 3, "junk": 1}}, {}, [])
        check("additionalProperties 未声明（默认 true）→ 放过", e == [], str(e))
        e = VD._mini_validate({"type": "object", "properties": {"a": {"type": "integer"}},
                               "additionalProperties": False}, {"a": 1, "b": 2}, {}, [])
        check("additionalProperties:false 的野字段被拦", len(e) == 1, str(e))

        # 域级：真实 drop_pools schema 上的必填/类型
        check("池缺必填 type 被拦",
              len(VD.validate_entry("drop_pools", {"entries": [{"item": "mat_a"}]})) == 1,
              str(VD.validate_entry("drop_pools", {"entries": [{"item": "mat_a"}]})))
        check("池 type 类型错被拦",
              len(VD.validate_entry("drop_pools", {"type": 5})) == 1,
              str(VD.validate_entry("drop_pools", {"type": 5})))
        check("条目缺必填 item 被拦",
              len(VD.validate_entry("drop_pools", {"type": "weighted", "entries": [{"w": 1}]})) == 1)
        check("抽行缺必填 pool 被拦",
              len(VD.validate_entry("drop_pools", {"type": "table", "rolls": [{"chance": 0.5}]})) == 1)
        check("w 为字符串被拦",
              len(VD.validate_entry("drop_pools",
                                    {"type": "weighted", "entries": [{"item": "a", "w": "5"}]})) == 1)
        check("chance 越界被拦",
              len(VD.validate_entry("drop_pools",
                                    {"type": "table", "rolls": [{"pool": "a", "chance": 1.5}]})) == 1)

    # ── ③ 金标准对照：内置 vs jsonschema，逐例一致 ──────────────────
    print("\n[3] 金标准对照（内置路径 vs jsonschema，逐例一致）")
    if not has_js:
        print("  ⚠ 本机没装 jsonschema —— 跳过对照段（①② 段已独立覆盖内置路径）")
    else:
        real_skill = json.load(open(SKILLS_JSON, encoding="utf-8"))
        sk_key = sorted(real_skill)[0]
        real_item = json.load(open(ITEMS_JSON, encoding="utf-8"))
        it_key = sorted(real_item)[0]
        bad_skill = json.loads(json.dumps(real_skill[sk_key]))
        bad_skill["aoe"] = "sideways"            # 真实 schema 的 enum 是 ["all","front"]
        bad_item = json.loads(json.dumps(real_item[it_key]))
        bad_item["quality"] = "rainbow"          # 真实 schema 的 enum 不含它
        p_int = json.loads(json.dumps(pools[POOL_INT_N]))
        p_rng = json.loads(json.dumps(pools[POOL_RANGE_N]))

        def mutate(p, fn):
            import copy
            q = copy.deepcopy(p)
            fn(q)
            return q

        def _del_type(q):
            q.pop("type")

        def _set_n_bad(q):
            q["rolls"][0]["n"] = "5"

        def _set_n_short(q):
            q["rolls"][0]["n"] = [1]

        def _entries_not_list(q):
            q["entries"] = "nope"

        def _entry_no_item(q):
            q["entries"] = [{"w": 1}]

        def _rolls_no_pool(q):
            q["rolls"] = [{"chance": 0.5}]

        def _w_str(q):
            q["entries"] = [{"item": "mat_a", "w": "5"}]

        def _w_negative(q):
            q["entries"] = [{"item": "mat_a", "w": -1}]

        def _chance_over(q):
            q["rolls"] = [{"pool": "sub", "chance": 1.5}]

        def _chance_str(q):
            q["rolls"] = [{"pool": "sub", "chance": "0.5"}]

        def _unknown_field(q):
            q["whatever_field"] = {"nested": [1, 2]}

        def _type_int(q):
            q["type"] = 7

        SAMPLES = [
            ("真池 n=int", "drop_pools", p_int),
            ("真池 n=[min,max]", "drop_pools", p_rng),
            ("缺 type", "drop_pools", mutate(p_int, _del_type)),
            ("n 为字符串", "drop_pools", mutate(p_int, _set_n_bad)),
            ("n 区间只有一项", "drop_pools", mutate(p_int, _set_n_short)),
            ("entries 非数组", "drop_pools", mutate(p_int, _entries_not_list)),
            ("条目缺 item", "drop_pools", mutate(p_int, _entry_no_item)),
            ("抽行缺 pool", "drop_pools", mutate(p_int, _rolls_no_pool)),
            ("w 为字符串", "drop_pools", mutate(p_int, _w_str)),
            ("w 为负", "drop_pools", mutate(p_int, _w_negative)),
            ("chance 越界", "drop_pools", mutate(p_int, _chance_over)),
            ("chance 为字符串", "drop_pools", mutate(p_int, _chance_str)),
            ("未知字段（schema 放行）", "drop_pools", mutate(p_int, _unknown_field)),
            ("type 为整数", "drop_pools", mutate(p_int, _type_int)),
            ("池非对象", "drop_pools", "not-an-object"),
            ("空池", "drop_pools", {}),
            ("真技能 good", "skills", real_skill[sk_key]),
            ("真技能 enum 外取值", "skills", bad_skill),
            ("真物品 good", "items", real_item[it_key]),
            ("真物品 enum 外取值", "items", bad_item),
        ]
        disagree = []
        n_bad = 0
        for label, dom, entry in SAMPLES:
            _pk = _pkg_for(dom)                 # 内容域要带包（真源在包）；引擎域不带
            with _force_mini():
                mini_ok = not VD.validate_entry(dom, entry, _pk)
            js_ok = _jsonschema_ok(dom, entry, _pk)
            if not js_ok:
                n_bad += 1
            if mini_ok != js_ok:
                disagree.append((label, dom, mini_ok, js_ok))
        check(f"对照 {len(SAMPLES)} 例结论逐例一致（其中 {n_bad} 例是坏数据）",
              not disagree, str(disagree))
        check(f"对照集里坏数据确实被 jsonschema 判坏（{n_bad} 例 > 0）", n_bad > 0)

        # 变异语料：真池上做确定性改坏，逐例比对结论
        REPL = [None, True, 0, -1, 3.5, "", "x", [], {}, [1, 2], [1], "5"]
        corpus_fr = []       # 假红：js 通过、内置报错（**必须 0**）
        corpus_miss = []     # 漏报：js 报错、内置放过（设计上允许，只统计）
        n_cases = 0
        for key in sorted(pools)[:60]:
            pool = pools[key]

            def set_at(obj, path, val):
                import copy
                o = copy.deepcopy(obj)
                cur = o
                for p in path[:-1]:
                    cur = cur[p]
                cur[path[-1]] = val
                return o

            def walk(x, prefix=(), depth=2):
                yield prefix
                if depth <= 0:
                    return
                if isinstance(x, dict):
                    for k, v in x.items():
                        yield from walk(v, prefix + (k,), depth - 1)
                elif isinstance(x, list):
                    for i, v in enumerate(x):
                        yield from walk(v, prefix + (i,), depth - 1)

            muts = []
            for i, path in enumerate(walk(pool)):
                if not path:
                    continue
                for j in range(2):
                    muts.append(set_at(pool, path, REPL[(i + j * 5) % len(REPL)]))
            for m in muts[:24]:
                n_cases += 1
                with _force_mini():
                    mini_ok = not VD.validate_entry("drop_pools", m)
                js_ok = _jsonschema_ok("drop_pools", m)
                if js_ok and not mini_ok:
                    corpus_fr.append((key, VD.validate_entry("drop_pools", m)))
                elif (not js_ok) and mini_ok:
                    corpus_miss.append(key)
        check(f"变异语料 {n_cases} 例：假红 = 0", not corpus_fr, str(corpus_fr[:3]))
        print(f"     （其中漏报 {len(corpus_miss)} 例 —— 内置器允许保守放过，不算失败）")

    # ── ④ 真数据回归：修复前 84 → 修复后 0 ────────────────────────
    print("\n[4] 真数据回归（596 个掉落池，内置路径）")
    sch, name = VD.primary_def("drop_pools")
    defs = sch.get("$defs") or {}
    target = defs[name]

    with _force_mini():
        VD._mini_validate = _legacy_mini_validate
        before = [k for k in pools if VD.validate_entry("drop_pools", pools[k])]
    with _force_mini():
        after = [k for k in pools if VD.validate_entry("drop_pools", pools[k])]
    js_fails = [] if not has_js else [k for k in pools if _jsonschema_ok("drop_pools", pools[k]) is False]

    print(f"     修复前（冻结副本）失败 {len(before)} 池；修复后失败 {len(after)} 池；"
          f"jsonschema {len(js_fails)} 池")
    check("修复前确有 ~84 池假红（bug 真实存在）", len(before) == 84, f"实为 {len(before)}")
    check("修复后 0 池失败", len(after) == 0, str(after[:5]))
    check("内置器与 jsonschema 在真包上结论一致（596/596）", len(js_fails) == 0, str(js_fails[:5]))
    if has_js:
        with _force_mini():
            mini_ok_map = {k: not VD.validate_entry("drop_pools", pools[k]) for k in pools}
        pairs = sum(1 for k in pools if mini_ok_map[k] == _jsonschema_ok("drop_pools", pools[k]))
        check("逐池对照一致 596/596", pairs == len(pools), f"{pairs}/{len(pools)}")

    # ── ⑤ 真·无 jsonschema 环境（子进程里把 import 打掉）────────────
    print("\n[5] 真·无 jsonschema 环境（子进程封掉 import）")
    child = (
        "import sys; sys.dont_write_bytecode=True\n"
        "sys.modules['jsonschema'] = None\n"                 # 让 `import jsonschema` 直接抛
        f"sys.path.insert(0, {ROOT!r})\n"
        "from editor import validate as VD\n"
        "assert VD._js is None, 'fallback 没生效'\n"
        f"import json; pools=json.load(open({POOLS_JSON!r}, encoding='utf-8'))\n"
        "bad=[k for k in pools if VD.validate_entry('drop_pools', pools[k])]\n"
        "print('CHILD_JS:', VD._js, 'CHILD_POOLS:', len(pools), 'CHILD_FAILS:', len(bad))\n"
    )
    pr = subprocess.run([sys.executable, "-c", child], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", cwd=ROOT,
                        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
                        timeout=300)
    out = (pr.stdout or "") + (pr.stderr or "")
    check("子进程里 import jsonschema 被打掉且 _js 为 None",
          pr.returncode == 0 and "CHILD_JS: None" in out, out.strip()[-300:])
    check("无 jsonschema 的机器上 596 池全绿",
          "CHILD_FAILS: 0" in out and "CHILD_POOLS: 596" in out, out.strip()[-300:])

    # ── 汇总 ────────────────────────────────────────────────────
    print(f"\n{'=' * 56}\n通过 {PASS}，失败 {FAIL}")
    if FAILURES:
        print("失败项：")
        for f in FAILURES:
            print("  -", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
