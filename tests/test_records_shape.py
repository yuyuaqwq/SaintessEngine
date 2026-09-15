#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""records 门禁：类型还原 / 顺序守卫 / 缺文件坏 JSON / 索引 / 剥字段 / 零知识。

跑法：python tests/test_records_shape.py
退出码：0 = 全绿；1 = 有失败。

钉住的都是「改了就静默错值 / 静默改序 / 静默吞掉」的地方：
  ① **类型还原**：`key_type=int` 不还原 → `get(3)` 恒 None（真源按 int 查 = **静默错值**）
  ② **顺序守卫**：`order` 与域不符（多 / 少 / 重复键）→ 必须 `RecordsOrderMismatch`（不许静默改序）
  ③ **缺文件 / 坏 JSON**：→ `{}` 且 `missing is True`（不许抛，也不许假装有数据）
  ④ **索引**：`by` / `group_by` / `index_of`（重名收全）/ `where`（保序）
  ⑤ **drop**：指定字段剥掉、其余字段逐字段逐序保留；剥空条目不留空壳
  ⑥ **零知识**：本模块源码不得出现具体游戏词汇

语料全部建在一个临时语料根里（跑完删掉）：先试系统临时目录（正常机器），
沙箱 ACL 下 `%TEMP%` 建得出写不进 → 退到本仓 `_records_shape_tmp/`（同一 finally 里必删）。
"""
import json
import os
import re
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine.records import (Records, RecordsOrderMismatch,   # noqa: E402
                                     RecordsSet)

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name} {detail}")


# ---------------------------------------------------------------- 语料
ROSTER = {
    "1": {"name": "alice", "kind": "x", "n": 2, "note": "one"},
    "2": {"name": "bob", "kind": "x", "n": 5, "note": "two"},
    "3": {"name": "alice", "kind": "y", "n": 1, "note": "three"},
}
DROP = {
    "7": {"name": "seven", "_injected": {"src": "x"}, "n": 7, "tags": ["a"]},
    "8": {"name": "eight", "_injected": True, "n": 8, "tags": []},
}
SHELL = {"9": {"_injected": 1}, "10": {"_injected": 2, "name": "ten"}}
SPARSE = {
    "1": {"name": "a"},
    "2": {"n": 7},
    "3": {"name": None},
    "4": ["raw", "line"],
}
MIXED = {"3": {"name": "three"}, "x": {"name": "ex"}}


def _make_fixtures(root):
    data = os.path.join(root, "data")
    rules = os.path.join(root, "rules")
    os.makedirs(data, exist_ok=True)
    os.makedirs(rules, exist_ok=True)
    for name, doc in (("roster", ROSTER), ("roster_str", ROSTER), ("drop", DROP),
                      ("shell", SHELL), ("sparse", SPARSE), ("mixed", MIXED),
                      ("empty", {}), ("list", [1, 2, 3])):
        with open(os.path.join(data, "%s.json" % name), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
    with open(os.path.join(data, "bad.json"), "w", encoding="utf-8") as f:
        f.write('{"1": {"name": }')                       # 故意坏 JSON
    with open(os.path.join(rules, "grade.json"), "w", encoding="utf-8") as f:
        json.dump({"10": {"score": 1}, "2": {"score": 2}}, f, ensure_ascii=False)


# ---------------------------------------------------------------- 1 类型还原
def t1_type_restore(root):
    print("\n[1] 类型还原：key_type=int 还原 str 键（不还原 = 恒 None = 静默错值）")
    r = Records(root, "roster", key_type=int).load()
    check("get(3) 命中（键已还原成 int）",
          (r.get(3) or {}).get("note") == "three", repr(r.get(3)))
    check("get('3') 不命中（未还原的 str 键不是同一个键）",
          r.get("3") is None, repr(r.get("3")))
    check("表键是 int：3 in / '3' not in",
          3 in r.all() and "3" not in r.all(), repr(list(r.all())))
    check("还原后仍保插入序 [1, 2, 3]",
          list(r.all()) == [1, 2, 3], repr(list(r.all())))

    s = Records(root, "roster_str").load()                # key_type 缺省 = str
    check("key_type=str（缺省）：get('3') 命中 / get(3) 不命中",
          (s.get("3") or {}).get("note") == "three" and s.get(3) is None)
    check("两把键都在：str 表键 '3' 与 int 表键 3 是不同表", list(s.all()) == ["1", "2", "3"])

    m = Records(root, "mixed", key_type=int).load()
    check("还原不了的键原样保留、不静默丢（{3, 'x'} 都在）",
          set(m.all()) == {3, "x"}, repr(list(m.all())))


# ---------------------------------------------------------------- 2 顺序守卫
def t2_order_guard(root):
    print("\n[2] 顺序守卫：order 一致 → 按 order；多 / 少 / 重复 → RecordsOrderMismatch")
    r = Records(root, "roster", key_type=int, order=(3, 1, 2)).load()
    check("完全一致 → 按 order 顺序返回 [3, 1, 2]",
          list(r.all()) == [3, 1, 2], repr(list(r.all())))
    check("按 order 排后 get(1) 仍是同一条目", r.get(1)["note"] == "one")

    for label, order in (("少一项", (1, 2)), ("多一项", (1, 2, 3, 4)),
                         ("声明有重复键", (1, 1, 2, 3)),
                         ("键型不符（声明 str / 还原成 int）", ("1", "2", "3"))):
        bad = Records(root, "roster", key_type=int, order=order)
        try:
            bad.load()
            check("★ %s → RecordsOrderMismatch" % label, False, "没抛")
        except RecordsOrderMismatch as exc:
            check("★ %s → RecordsOrderMismatch" % label, True)
            check("★ %s：表不发布（missing True / all()=={}）" % label,
                  bad.missing is True and bad.all() == {}, repr(bad.all()))
            check("★ %s：留痕一条（problems）" % label, bool(bad.problems))

    check("顺序声明通过时 problems 干净（无假留痕）",
          Records(root, "roster", key_type=int, order=(1, 2, 3)).load().problems == [])
    check("空表不做顺序守卫（与包内 _ordered 同口径，不抛）",
          Records(root, "empty", order=(9,)).load().all() == {})


# ---------------------------------------------------------------- 3 缺文件不抛
def t3_missing_file(root):
    print("\n[3] 缺文件不抛：不存在的域 → {} + missing True + 留痕")
    r = Records(root, "nope")
    try:
        r.load()
        ok = True
    except Exception as exc:                               # noqa: BLE001
        ok = False
        check("★ 缺文件 load() 不抛", False, repr(exc))
    if ok:
        check("★ 缺文件 load() 不抛", True)
    check("缺文件 → all() == {}", r.all() == {}, repr(r.all()))
    check("缺文件 → missing is True", r.missing is True)
    check("缺文件 → problems 留痕一条（不静默吞）", len(r.problems) == 1, repr(r.problems))
    check("合法空表 {} 也算 missing（空表 = 供 fail-closed 用）",
          Records(root, "empty").missing is True)

    bag = RecordsSet(root, {"roster": {"key_type": int, "order": [1, 2, 3]},
                            "nope": {}, "empty": {}})
    check("RecordsSet：声明过的域惰性读 + get 命中", bag.roster.get(1)["note"] == "one")
    check("RecordsSet：同一域返回同一对象（缓存）", bag.roster is bag.roster)
    check("RecordsSet：读不到的域 missing_domains() == ['empty', 'nope']",
          bag.missing_domains() == ["empty", "nope"], repr(bag.missing_domains()))
    try:
        bag.ghost
        check("★ 未声明的域报 AttributeError（不建空壳）", False, "没抛")
    except AttributeError:
        check("★ 未声明的域报 AttributeError（不建空壳）", True)
    check("RecordsSet：sub 覆盖（rules 域）",
          RecordsSet(root, {"grade": {"sub": "rules", "key_type": int}}
                     ).grade.get(10)["score"] == 1)


# ---------------------------------------------------------------- 4 坏 JSON 不抛
def t4_bad_json(root):
    print("\n[4] 坏 JSON / 顶层非映射不抛：→ {} + missing True + 留痕")
    for label, domain in (("坏 JSON", "bad"), ("顶层是 list（不是 {id: {...}}）", "list")):
        r = Records(root, domain)
        try:
            r.load()
            check("★ %s → load() 不抛" % label, True)
        except Exception as exc:                           # noqa: BLE001
            check("★ %s → load() 不抛" % label, False, repr(exc))
            continue
        check("★ %s → all() == {}" % label, r.all() == {}, repr(r.all()))
        check("★ %s → missing is True" % label, r.missing is True)
        check("★ %s → problems 留痕一条" % label, len(r.problems) == 1, repr(r.problems))


# ---------------------------------------------------------------- 5 索引
def t5_indices(root):
    print("\n[5] 索引：by / group_by / index_of（重名收全）/ where（保序）/ into")
    r = Records(root, "roster", key_type=int).load()
    check("by('name','alice') 命中表序首个（id=1）",
          (r.by("name", "alice") or {}).get("note") == "one", repr(r.by("name", "alice")))
    check("by 未命中 → None / 可覆盖 default",
          r.by("name", "zed") is None and r.by("name", "zed", default="X") == "X")
    check("index_of('name') 重名收全 {'alice': [1, 3], 'bob': [2]}",
          r.index_of("name") == {"alice": [1, 3], "bob": [2]}, repr(r.index_of("name")))
    check("index_of 返回同一索引（惰性建一次）",
          r.index_of("name") is r.index_of("name"))
    check("group_by('kind') == {'x': {1, 2}, 'y': {3}}",
          {k: list(v) for k, v in r.group_by("kind").items()} == {"x": [1, 2], "y": [3]},
          repr({k: list(v) for k, v in r.group_by("kind").items()}))
    check("where(n > 1) 保序 → [1, 2]",
          list(r.where(lambda e: e["n"] > 1)) == [1, 2],
          repr(list(r.where(lambda e: e["n"] > 1))))

    o = Records(root, "roster", key_type=int, order=(3, 2, 1)).load()
    check("where 保的是**表序**（order=(3,2,1) 时 n>1 → [2, 1]，不是数值序）",
          list(o.where(lambda e: e["n"] > 1)) == [2, 1],
          repr(list(o.where(lambda e: e["n"] > 1))))

    copies = r.into(dict)
    check("into(dict)：保序保键 + 值是副本（不是同一对象）",
          list(copies) == [1, 2, 3] and copies[1] == r.all()[1]
          and copies[1] is not r.all()[1])
    check("into(取字段)：{1: 2, 2: 5, 3: 1}",
          r.into(lambda e: e["n"]) == {1: 2, 2: 5, 3: 1}, repr(r.into(lambda e: e["n"])))

    sp = Records(root, "sparse", key_type=int).load()
    check("sparse：index_of('name') 只收有效值 {'a': [1]}（缺 / None / 非映射不入索引）",
          sp.index_of("name") == {"a": [1]}, repr(sp.index_of("name")))
    check("sparse：group_by('name') == {'a': {1}}",
          {k: list(v) for k, v in sp.group_by("name").items()} == {"a": [1]},
          repr({k: list(v) for k, v in sp.group_by("name").items()}))
    check("sparse：跳过 3 条有留痕（显式降级，不静默）",
          any("跳过 3 条" in p for p in sp.problems), repr(sp.problems))


# ---------------------------------------------------------------- 6 drop
def t6_drop(root):
    print("\n[6] drop：指定字段被剥掉，其它字段逐字段逐序保留；剥空不留空壳")
    with open(os.path.join(root, "data", "drop.json"), encoding="utf-8") as f:
        raw = json.load(f)
    r = Records(root, "drop", key_type=int, drop=("_injected",)).load()
    kept_expect = {k: v for k, v in raw["7"].items() if k != "_injected"}
    check("_injected 被剥掉（整键移除，不留 None/{} 占位）",
          "_injected" not in r.get(7), repr(r.get(7)))
    check("其余字段**逐字节**保留（json.dumps 原样相等）",
          json.dumps(r.get(7), ensure_ascii=False) == json.dumps(kept_expect, ensure_ascii=False),
          repr(r.get(7)))
    check("其余字段**顺序**保持原样（name, n, tags）",
          list(r.get(7)) == ["name", "n", "tags"], repr(list(r.get(7))))
    check("drop 后 problems 干净", r.problems == [], repr(r.problems))

    sh = Records(root, "shell", key_type=int, drop=("_injected",)).load()
    check("剥空条目不留空壳（9 被移除，{} 不出现）",
          9 not in sh.all() and sh.all()[10] == {"name": "ten"}, repr(sh.all()))
    check("剥空 → 留痕一条（不静默丢条目）",
          any("剥空" in p or "不留空壳" in p for p in sh.problems), repr(sh.problems))
    try:
        Records(root, "shell", key_type=int, order=(9, 10), drop=("_injected",)).load()
        check("★ 剥空后与序声明不符 → RecordsOrderMismatch（两条守卫联动）", False, "没抛")
    except RecordsOrderMismatch:
        check("★ 剥空后与序声明不符 → RecordsOrderMismatch（两条守卫联动）", True)


# ---------------------------------------------------------------- 7 零知识
_GAME_TERMS = (
    # 具体游戏 / 仓库名
    "奥兰迪亚", "余烬", "dragonfall",
    # 内容侧身份名词（引擎不得出现）
    "公会", "职业", "物品", "怪物", "装备", "技能", "任务", "地图",
    "guild", "monster", "npc", "quest", "sword", "potion",
    # 具体游戏的机制 id
    "zhan_yi", "randuin", "ice_vein", "melody", "faith", "fury",
)


def t7_zero_knowledge():
    print("\n[7] 零知识：records 源码不得出现具体游戏词汇")
    base = os.path.join(ROOT, "saintess_engine", "records")
    hits = []
    for dirpath, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            lines = open(path, encoding="utf-8").read().splitlines()
            for i, line in enumerate(lines, 1):
                for t in _GAME_TERMS:
                    pat = (re.compile(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(t))
                           if t.isascii() else re.compile(re.escape(t)))
                    if pat.search(line):
                        hits.append("%s:%d [%s] %s" % (fn, i, t, line.strip()[:70]))
    check("★ 扫描 %d 个词零命中" % len(_GAME_TERMS), not hits, "\n      " + "\n      ".join(hits))
    print("      （扫描目录：saintess_engine/records/ · 命中 0）")


def _writable(d):
    """这个目录建得出**子目录**、写得进文件吗（沙箱 ACL 下 %TEMP% 会假通过）。"""
    sub = os.path.join(d, "probe")
    try:
        os.makedirs(sub, exist_ok=True)
        with open(os.path.join(sub, "x"), "w", encoding="utf-8") as f:
            f.write("ok")
        shutil.rmtree(sub, ignore_errors=True)
        return True
    except OSError:
        return False


def _fixture_root():
    """语料根：系统临时目录优先；不可写 → 退到本仓 `_records_shape_tmp/`（finally 里删）。"""
    try:
        d = tempfile.mkdtemp(prefix="records_shape_")
    except OSError:
        d = ""
    if d and _writable(d):
        try:
            os.chmod(d, 0o755)                             # 沙箱 ACL：0o700 会「建得出写不进」
        except OSError:
            pass
        return d
    if d:
        shutil.rmtree(d, ignore_errors=True)
    fallback = os.path.join(ROOT, "_records_shape_tmp")
    shutil.rmtree(fallback, ignore_errors=True)
    os.makedirs(fallback, exist_ok=True)
    print(f"  （系统临时目录不可写 → 语料根退到 {fallback}）")
    return fallback


def main():
    print("== records 门禁：类型还原 / 顺序守卫 / 缺文件坏 JSON / 索引 / drop / 零知识 ==")
    root = _fixture_root()
    try:
        _make_fixtures(root)
        t1_type_restore(root)
        t2_order_guard(root)
        t3_missing_file(root)
        t4_bad_json(root)
        t5_indices(root)
        t6_drop(root)
        t7_zero_knowledge()
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
