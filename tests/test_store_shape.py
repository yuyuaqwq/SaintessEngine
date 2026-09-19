#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""store 形状门禁：声明式建表（`Column` / `TableSpec` / `declare`）+ 自动 CRUD 装配。

跑法：python tests/test_store_shape.py
退出码：0 = 全绿；1 = 有失败。

判据（BRIEF §5 六条，逐节对应）：
  1 建表等价     declare 出来的表 vs 等价手写 DDL —— `PRAGMA table_info` 逐列一致
  2 幂等         连续 declare 两次：不抛错、PRAGMA 逐行相同、迁移器不重复注册
  3 缺列自愈     先建少一列的旧表 → declare 带那列 → 只补缺列（migrate 路径）
  4 非法名拒绝   表名 `x; DROP TABLE y` 等 → ValueError，且半份注册都不留
  5 CRUD 可用    upsert / get / all / count / delete + `json_fields` 编解码往返等值
  6 零游戏知识   `spec.py` 源码里 grep 不到任何具体游戏词汇

另钉两条 fail-closed（都有牙）：
  * 同表名、不同列声明 → ValueError（不静默覆盖语义）
  * 既有表的主键与声明不符 → ValueError（ALTER 加不了主键，不静默交回坏仓库）
"""
import json
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine.store import (Column, Database, DeclaredRepository,  # noqa: E402
                                   Repository, TableSpec, columns_of, declare)

passed = failed = 0


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


def _make_tmp():
    """临时目录：优先系统 temp；沙箱 ACL 下系统 temp 可能「建得出、写不进」→ 退到本目录。

    正常环境走系统 temp（与 `test_store.py` 同款）；退让只在系统 temp 真写不进去时发生，
    写成日志一行，不静默。
    """
    for kwargs in ({}, {"dir": _HERE}):
        try:
            d = tempfile.mkdtemp(prefix="store_shape_", **kwargs)
        except OSError:
            continue
        try:
            probe = os.path.join(d, ".probe")
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write("x")
            os.remove(probe)
            if kwargs:
                print(f"  注：系统 temp 不可写，临时目录退到 {d}")
            return d
        except OSError:
            shutil.rmtree(d, ignore_errors=True)
    raise RuntimeError("找不到可写临时目录")


TMP = _make_tmp()


def _db(name):
    return Database(os.path.join(TMP, name))


def _pragma(db, table):
    """`PRAGMA table_info` 的逐列原始行：列名/类型/非空/默认值/主键位。"""
    with db.readonly() as conn:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [(r[1], r[2], r[3], r[4], r[5]) for r in rows]


def _print_rows(title, rows):
    print(f"    {title}:")
    for r in rows:
        print(f"      name={r[0]!r} type={r[1]!r} notnull={r[2]} default={r[3]!r} pk={r[4]}")


def _reject(fn, exc=ValueError):
    """跑 fn，返回 (是否按 exc 拒绝, 异常文本或 '')。"""
    try:
        fn()
    except exc as e:
        return True, f"{type(e).__name__}: {e}"
    except Exception as e:                                        # noqa: BLE001
        return False, f"抛了别的：{type(e).__name__}: {e}"
    return False, "没抛"


# 声明与它等价的手写 DDL（§5.1 的对照物：两边逐列必须一模一样）
SPEC = TableSpec("records", [
    Column("id", "TEXT", pk=True),
    Column("label", "TEXT", notnull=True, default=""),
    Column("payload", "TEXT", default="{}"),
    Column("rank_no", "INTEGER", default=0),
])
HAND_DDL = """
CREATE TABLE IF NOT EXISTS records (
    id TEXT,
    label TEXT NOT NULL DEFAULT '',
    payload TEXT DEFAULT '{}',
    rank_no INTEGER DEFAULT 0,
    PRIMARY KEY (id)
);
"""


# ---------------------------------------------------------------- 1 建表等价
def t1_equivalence():
    print("\n[1] 建表等价：declare 生成 DDL vs 等价手写 DDL")
    db_a = _db("eq_declare.db")
    repo = declare(db_a, SPEC, json_fields=("payload",))
    rows_a = _pragma(db_a, "records")

    db_b = _db("eq_hand.db")
    db_b.register_schema("records", HAND_DDL)
    db_b.init()
    rows_b = _pragma(db_b, "records")

    _print_rows("declare 生成", rows_a)
    _print_rows("等价手写", rows_b)
    check("PRAGMA table_info 逐列完全一致（列名/类型/非空/默认/主键）",
          rows_a == rows_b, f"\n      declare={rows_a}\n      hand   ={rows_b}")
    check("主键位落在 id 上（pk=1）", [r for r in rows_a if r[4] == 1] == [("id", "TEXT", 0, None, 1)],
          str(rows_a))
    check("返回的仓库装配了 table / pk", (repo.table, repo.pk) == ("records", ("id",)), repr(repo))
    check("建表 SQL 以表名注册（schema_names 可见）", db_a.schema_names == ["records"],
          str(db_a.schema_names))


# ---------------------------------------------------------------- 2 幂等
def t2_idempotent():
    print("\n[2] 幂等：重复 declare 同一个 spec")
    db = _db("idem.db")
    repo1 = declare(db, SPEC, json_fields=("payload",))
    before = _pragma(db, "records")
    n_schemas, n_migrations = len(db._schemas), len(db._migrations)
    repo2 = declare(db, SPEC, json_fields=("payload",))
    after = _pragma(db, "records")
    _print_rows("第一次", before)
    _print_rows("第二次", after)
    check("第二次 declare 不抛错", True)
    check("第二次 PRAGMA 与第一次逐行相同（结构不变）", before == after,
          f"\n      before={before}\n      after ={after}")
    check("不重复注册 schema（同名仍只一条）", len(db._schemas) == n_schemas,
          f"{n_schemas} -> {len(db._schemas)}")
    check("不重复注册迁移器（含形状自带的那条）", len(db._migrations) == n_migrations,
          f"{n_migrations} -> {len(db._migrations)}")
    check("返回同一个仓库实例（幂等不新建）", repo2 is repo1)
    with db.session() as conn:
        repo2.upsert(conn, {"id": "r1", "label": "x"})
    with db.readonly() as conn:
        check("重复 declare 后仓库照旧可用（写读回）",
              repo2.get(conn, "r1")["label"] == "x")

    db2 = _db("idem_other.db")
    repo3 = declare(db2, SPEC, json_fields=("payload",))
    check("另一个 Database 上同名表各自独立（注册表按 db 分账）",
          repo3 is not repo1 and _pragma(db2, "records") == before)


# ---------------------------------------------------------------- 3 缺列自愈
def t3_self_heal():
    print("\n[3] 缺列自愈：旧表少 rank_no → declare 只补缺列（migrate 路径）")
    db = _db("heal.db")
    with db.session() as conn:
        conn.execute("CREATE TABLE records ("
                     "id TEXT PRIMARY KEY, label TEXT NOT NULL DEFAULT '', "
                     "payload TEXT DEFAULT '{}')")
    old = _pragma(db, "records")
    _print_rows("旧表", old)
    check("旧表确实少一列（rank_no 不在）", "rank_no" not in {r[0] for r in old}, str(old))

    seen = []
    spec = TableSpec("records", list(SPEC.columns),
                     migrations=[lambda conn: seen.append(sorted(columns_of(conn, "records")))])
    declare(db, spec, json_fields=("payload",))
    new = _pragma(db, "records")
    _print_rows("declare 之后", new)

    col = [r for r in new if r[0] == "rank_no"]
    check("缺的列被补上", len(col) == 1, str(new))
    check("补的列类型/非空/默认与声明一致",
          col == [("rank_no", "INTEGER", 0, "0", 0)], str(col))
    check("原有列一个没动（id/label/payload 逐行不变）",
          [r for r in new if r[0] != "rank_no"] == old, f"{old} vs {new}")
    check("附加迁移在补列之后执行（拿到的是补完列的表）",
          seen and "rank_no" in seen[0], str(seen))
    with db.session() as conn:
        conn.execute("INSERT INTO records (id, label) VALUES ('r1','x')")
    with db.readonly() as conn:
        got = conn.execute("SELECT rank_no FROM records WHERE id='r1'").fetchone()[0]
    check("补的列 DEFAULT 生效（未赋值 → 0）", got == 0, got)
    declare(db, spec, json_fields=("payload",))
    check("重复 declare（幂等）后仍只有一列 rank_no",
          _pragma(db, "records") == new)


# ---------------------------------------------------------------- 4 非法名拒绝
def t4_illegal():
    print("\n[4] 非法名拒绝：注入面必须 fail-closed")
    ok, msg = _reject(lambda: declare(_db("bad_0.db"),
                                      TableSpec("x; DROP TABLE y", [Column("id", "TEXT", pk=True)])))
    check("★ 表名 `x; DROP TABLE y` → ValueError（_check_ident 同款校验）", ok, msg)
    print(f"      {msg}")

    ok, msg = _reject(lambda: declare(_db("bad_1.db"),
                                      TableSpec("records", [Column("id; DROP TABLE y", "TEXT")])))
    check("列名带 `;` → ValueError", ok, msg)
    print(f"      {msg}")

    bad_types = ("TEXT); DROP TABLE records; --", "", "TEXT'", "TEXT NOT NULL) --")
    for bad in bad_types:
        ok, msg = _reject(lambda b=bad: declare(
            _db("bad_t.db"), TableSpec("records", [Column("id", b)])))
        check(f"非法类型串 {bad!r} → ValueError", ok, msg)
    ok, msg = _reject(lambda: declare(_db("bad_d.db"),
                                      TableSpec("records", [Column("id", "TEXT", default=object())])),
                      TypeError)
    check("不支持的默认值类型 → TypeError（不字符串化猜）", ok, msg)
    print(f"      {msg}")

    ok, msg = _reject(lambda: declare(_db("bad_dup.db"), TableSpec("records", [
        Column("id", "TEXT", pk=True), Column("id", "INTEGER")])))
    check("列名重复 → ValueError", ok, msg)
    ok, msg = _reject(lambda: declare(_db("bad_empty.db"), TableSpec("records", [])))
    check("空列声明 → ValueError", ok, msg)
    ok, msg = _reject(lambda: declare(_db("bad_spec.db"), ["records"]), TypeError)
    check("spec 不是 TableSpec → TypeError", ok, msg)
    ok, msg = _reject(lambda: declare(_db("bad_pk.db"), TableSpec("records", [
        Column("id", "TEXT", pk=True)]), json_fields=("nope; DROP",)))
    check("非法 json_fields 列名 → ValueError", ok, msg)

    # 关键：拒绝发生在注册之前 —— 库里不该留下半张表 / 半条注册
    db = _db("bad_after.db")
    _reject(lambda: declare(db, TableSpec("x; DROP TABLE y", [Column("id", "TEXT", pk=True)])))
    with db.readonly() as conn:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    check("★ 非法声明不留半份注册（schema_names 空、库里无表）",
          db.schema_names == [] and names == [], f"{db.schema_names} / {names}")


# ---------------------------------------------------------------- 5 CRUD
def t5_crud():
    print("\n[5] CRUD：declare 返回的 repo 直接可用")
    db = _db("crud.db")
    repo = declare(db, SPEC, json_fields=("payload",))
    check("类型：DeclaredRepository / Repository", isinstance(repo, DeclaredRepository)
          and isinstance(repo, Repository))
    check("table / pk / json_fields 从声明自动装配",
          (repo.table, repo.pk, repo.json_fields) == ("records", ("id",), ("payload",)),
          repr((repo.table, repo.pk, repo.json_fields)))

    payload = {"n": 1, "tags": ["a", "b"], "nested": {"k": "v"}}
    with db.session() as conn:
        repo.upsert(conn, {"id": "r1", "label": "x", "payload": payload, "rank_no": 3})
    with db.readonly() as conn:
        row = repo.get(conn, "r1")
    check("upsert + get：json_fields 自动解码，往返等值",
          row is not None and row["payload"] == payload and row["rank_no"] == 3,
          str(row))
    check("get 未知主键 → None", repo_get(repo, db, "zz") is None)

    with db.readonly() as conn:
        raw = conn.execute("SELECT payload FROM records WHERE id='r1'").fetchone()[0]
    check("落盘为 JSON 文本", isinstance(raw, str) and json.loads(raw) == payload, repr(raw))

    with db.session() as conn:
        repo.upsert(conn, {"id": "r1", "label": "y", "payload": {"n": 2}})
    with db.readonly() as conn:
        row = repo.get(conn, "r1")
    check("upsert 冲突走 UPDATE", row["label"] == "y" and row["payload"] == {"n": 2}, str(row))

    with db.session() as conn:
        repo.upsert_many(conn, [{"id": "r2", "label": "z"}, {"id": "r3", "label": "w"}])
    with db.readonly() as conn:
        rows = repo.all(conn, order_by="id DESC", limit=2)
        n = repo.count(conn)
    check("all(order_by, limit) / count", n == 3 and [r["id"] for r in rows] == ["r3", "r2"],
          f"n={n} rows={[r['id'] for r in rows]}")

    with db.session() as conn:
        gone = repo.delete(conn, "r3")
    with db.readonly() as conn:
        check("delete 返回行数 + 真删了", gone == 1 and repo.get(conn, "r3") is None
              and repo.count(conn) == 2, f"gone={gone}")

    # 复合主键：pk 顺序 = 声明顺序
    db2 = _db("crud_pk.db")
    spec2 = TableSpec("pairs", [
        Column("left_key", "TEXT", pk=True),
        Column("right_key", "TEXT", pk=True),
        Column("body", "TEXT", default=""),
    ])
    repo2 = declare(db2, spec2)
    check("复合主键按声明顺序装配", repo2.pk == ("left_key", "right_key"), repr(repo2.pk))
    with db2.session() as conn:
        repo2.upsert(conn, {"left_key": "a", "right_key": "b", "body": "1"})
        repo2.upsert(conn, {"left_key": "a", "right_key": "c", "body": "2"})
    with db2.readonly() as conn:
        check("复合主键 upsert/get 可用", repo2.count(conn) == 2
              and repo2.get(conn, "a", "c")["body"] == "2")


def repo_get(repo, db, *pk):
    with db.readonly() as conn:
        return repo.get(conn, *pk)


# ---------------------------------------------------------------- 7 fail-closed 加钉
def t7_fail_closed():
    print("\n[7] fail-closed 加钉：同表不同声明 / 既有主键与声明不符")
    db = _db("conflict.db")
    declare(db, SPEC, json_fields=("payload",))
    before = _pragma(db, "records")
    other = TableSpec("records", [
        Column("id", "TEXT", pk=True),
        Column("label", "TEXT"),
        Column("renamed", "INTEGER", default=0),
    ])
    ok, msg = _reject(lambda: declare(db, other))
    check("★ 同表不同声明 → ValueError（不静默覆盖语义）", ok, msg)
    print(f"      {msg}")
    check("被拒后原表结构与注册不变", _pragma(db, "records") == before
          and db.schema_names == ["records"], str(db.schema_names))

    db2 = _db("pk_mismatch.db")
    with db2.session() as conn:
        conn.execute("CREATE TABLE records (id TEXT, label TEXT)")
    ok, msg = _reject(lambda: declare(db2, SPEC))
    check("★ 既有表的主键与声明不符 → ValueError（ALTER 加不了主键，不静默交回坏仓库）",
          ok and "主键" in msg, msg)
    print(f"      {msg}")


# ---------------------------------------------------------------- 6 零游戏知识
def t6_zero_knowledge():
    print("\n[6] 零游戏知识：spec.py 里 grep 不到具体游戏词汇")
    BANNED = ("奥兰迪亚", "余烬", "公会", "职业", "怪物", "物品", "装备", "金币", "副本",
              "战意", "旋律", "连段", "破绽", "信仰", "奥术", "狂暴",
              "dragonfall", "zhan_yi", "lian_duan", "randuin", "ice_vein",
              "melody", "faith", "fury", "finisher", "cls_")
    path = os.path.join(ROOT, "saintess_engine", "store", "spec.py")
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    hits = [(i, term, ln.strip())
            for i, ln in enumerate(lines, 1) for term in BANNED if term in ln]
    check("★ 无具体游戏词汇（词表 = 中立性门禁 GAME_TERMS + 形状类名词）",
          not hits, str(hits[:6]))
    check("字段名全是通用名词（name / label / payload / rank_no）",
          not any(t in "".join(lines) for t in ("guild", "player", "monster", "quest")),
          "命中内容侧取值")
    print(f"      扫描 {path}")
    print(f"      grep -c 结果：{len(hits)} 处命中")


def main():
    print("== store 形状门禁：声明式建表（Column / TableSpec / declare）==")
    try:
        t1_equivalence()
        t2_idempotent()
        t3_self_heal()
        t4_illegal()
        t5_crud()
        t6_zero_knowledge()
        t7_fail_closed()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
