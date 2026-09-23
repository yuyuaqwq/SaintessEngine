#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""store 快照 / 计数器形状门禁：`store.snapshots`（owner 键单行 JSON 快照 + TTL）
+ `store.counters`（命名累计计数 + 复合键）。

跑法：python tests/test_store_blobs_shape.py
退出码：0 = 全绿；1 = 有失败。

判据（BRIEF §3，逐节对应）：
  1 注入面 fail-closed   stamp/stamp_key 同给、owner 空、fields 空…… 一律当场抛
  2 建表形状             声明 → TableSpec → 既有 declare 建表（owner 主键 / blob / stamp / extra）
  3 TTL 三出口逐格       未过期 / 过期 + keep 假（删行）/ 过期 + keep 真（打标保留且不改 stamp）
  4 sweep 返回过期清单   且「内存存活优先」（keep 真者不被删）
  5 bump 白名单 fail-closed（白名单外 → ValueError）；read 无行 → {}
  6 复合键（subject）    同一 owner 不同 subject 互不干扰
  7 引擎源码静态面       零 random/datetime/time import；字符串常量零取值词
  8 零字段知识           store/*.py 无 qq_id/state/updated_at/created_at/kills/stats 字面量
  9 不 import periodic    避让判据（不造第二套周期计数）
 10 写路径不自己 commit  事务边界交调用方（代理连接计数 commit）
 11 构造/取值 O(1)       语句数不随行数增长（sweep 除外）

另钉（都有牙）：
  * 有牙反证 6 处（逐处打印「预期变红 / 实测变红」）+ 两处同坏 + 第三处仍绿
  * 顺序断言：非 keep 分支 `on_expire` 在删行**之前**；keep 分支打标在 `on_expire` **之前**
"""
import ast
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ---- 扩展包门禁路径（2026-09-23 从引擎 tests/ 搬到本包）----
# 本文件现在位于 extends/<pkg>/tests/ ⇒ 往上四级才是**引擎根**，ROOT 重新绑定到它，
# 这样下面原有的 `os.path.join(ROOT, "saintess_engine", ...)` 一类路径扫描仍然指对地方。
_HERE_DIR = os.path.dirname(os.path.abspath(__file__))   # extends/<pkg>/tests
_PKG_ROOT = os.path.dirname(_HERE_DIR)                   # extends/<pkg>
_EXT_BASE = os.path.dirname(_PKG_ROOT)                   # extends
ROOT = os.path.dirname(_EXT_BASE)                        # 引擎根
for _p in (ROOT, _EXT_BASE, _HERE_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from saintess_engine.store import Column, Database, TableSpec, declare  # noqa: E402
from saintess_engine.store.counters import (CounterSpec, Counters,     # noqa: E402
                                            declare_counters)
from saintess_engine.store.snapshots import (SnapshotRepo, SnapshotSpec,  # noqa: E402
                                             declare_snapshot)

passed = failed = 0


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


def _make_tmp():
    """临时目录：优先系统 temp；沙箱 ACL 下系统 temp 可能「建得出、写不进」→ 退到本目录。"""
    for kwargs in ({}, {"dir": _HERE}):
        try:
            d = tempfile.mkdtemp(prefix="store_blobs_", **kwargs)
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
    with db.readonly() as conn:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [(r[1], r[2], r[3], r[4], r[5]) for r in rows]


def _reject(fn, exc=ValueError):
    """跑 fn，返回 (是否按 exc 拒绝, 异常文本或 '')。"""
    try:
        fn()
    except exc as e:
        return True, f"{type(e).__name__}: {e}"
    except Exception as e:                                        # noqa: BLE001
        return False, f"抛了别的：{type(e).__name__}: {e}"
    return False, "没抛"


class _SpyConn:
    """连接代理：数 `execute` 次数、数 `commit` 次数（判据 10 / 11 的取证工具）。"""

    def __init__(self, conn):
        self._conn = conn
        self.executes = 0
        self.commits = 0
        self.rollbacks = 0

    def execute(self, sql, params=()):
        self.executes += 1
        return self._conn.execute(sql, params)

    def executemany(self, sql, seq):
        self.executes += 1
        return self._conn.executemany(sql, seq)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


# ───────────────────────────────────────────────────────── 声明（测试用形状，零取值）
SNAP_SPEC = SnapshotSpec("notes", owner="owner_key", blob="body", stamp="stamp_col",
                         expired_key="stale_mark",
                         extra=(Column("label", "TEXT", default=""),))
SNAP_KEY_SPEC = SnapshotSpec("notes_in", owner="owner_key", blob="body",
                             stamp_key="born_at", expired_key="stale_mark")
COUNT_SPEC = CounterSpec("tally", owner="owner_key", fields=("a", "b", "c"),
                         extra=(Column("spare", "INTEGER", default=0),))
COUNT_SUB_SPEC = CounterSpec("tally_sub", owner="owner_key", fields=("n",),
                             subject="topic")


def _snap(name, spec=SNAP_SPEC, **kw):
    db = _db(name)
    return db, declare_snapshot(db, spec, **kw)


def _cnt(name, spec=COUNT_SPEC, **kw):
    db = _db(name)
    return db, declare_counters(db, spec, **kw)


# ───────────────────────────────────────────── 1 注入面 fail-closed
def t1_fail_closed():
    print("\n[1] 注入面 fail-closed：SnapshotSpec / CounterSpec / 装配口")
    ok, msg = _reject(lambda: SnapshotSpec("notes", owner="", blob="body"))
    check("owner 空 → ValueError", ok and "owner" in msg, msg)
    ok, msg = _reject(lambda: SnapshotSpec("notes", owner="owner_key", blob=""))
    check("blob 空 → ValueError", ok and "blob" in msg, msg)
    ok, msg = _reject(lambda: SnapshotSpec("", owner="owner_key", blob="body"))
    check("table 空 → ValueError", ok, msg)
    ok, msg = _reject(lambda: SnapshotSpec("x; DROP TABLE y", owner="owner_key", blob="body"))
    check("表名带 `;` → ValueError", ok, msg)
    ok, msg = _reject(lambda: SnapshotSpec("notes", owner="o; DROP", blob="body"))
    check("owner 列名带 `;` → ValueError", ok, msg)
    ok, msg = _reject(lambda: SnapshotSpec("notes", owner="owner_key", blob="body",
                                           stamp="stamp_col", stamp_key="born_at"))
    check("★ stamp 与 stamp_key 同给 → ValueError", ok, msg)
    print(f"      {msg}")
    ok, msg = _reject(lambda: SnapshotSpec("notes", owner="owner_key", blob="body",
                                           stamp_key=""))
    check("stamp_key 给空串 → ValueError", ok, msg)
    ok, msg = _reject(lambda: SnapshotSpec("notes", owner="owner_key", blob="body",
                                           stamp="body"))
    check("stamp 与 blob 同名（列重名）→ ValueError", ok, msg)
    ok, msg = _reject(lambda: SnapshotSpec("notes", owner="owner_key", blob="body",
                                           extra=("label",)), TypeError)
    check("extra 不是 Column → TypeError", ok, msg)
    ok, msg = _reject(lambda: SnapshotSpec("notes", owner="owner_key", blob="body",
                                           pk=("label",)))
    check("pk 不含 owner → ValueError", ok, msg)
    ok, msg = _reject(lambda: SnapshotSpec("notes", owner="owner_key", blob="body",
                                           pk=("owner_key", "nope")))
    check("pk 指向未声明的列 → ValueError", ok, msg)

    ok, msg = _reject(lambda: declare_snapshot(_db("bad_s1.db"), ["notes"]), TypeError)
    check("spec 不是 SnapshotSpec → TypeError", ok, msg)
    ok, msg = _reject(lambda: declare_snapshot(
        _db("bad_s2.db"), SnapshotSpec("notes", owner="owner_key", blob="body"),
        prepare="nope"), TypeError)
    check("prepare 不可调用 → TypeError", ok, msg)

    ok, msg = _reject(lambda: CounterSpec("tally", owner="owner_key", fields=()))
    check("★ fields 空 → ValueError", ok, msg)
    print(f"      {msg}")
    ok, msg = _reject(lambda: CounterSpec("tally", owner="owner_key", fields=("a; DROP",)))
    check("fields 含非法列名 → ValueError", ok, msg)
    ok, msg = _reject(lambda: CounterSpec("tally", owner="owner_key", fields=("a", "a")))
    check("fields 重复 → ValueError", ok, msg)
    ok, msg = _reject(lambda: CounterSpec("tally", owner="owner_key", fields=("owner_key",)))
    check("fields 含 owner（同列两义）→ ValueError", ok, msg)
    ok, msg = _reject(lambda: CounterSpec("tally", owner="owner_key", fields=("a",),
                                          subject="a"))
    check("subject 与 fields 同列 → ValueError", ok, msg)
    ok, msg = _reject(lambda: CounterSpec("tally", owner="owner_key", fields=("a",),
                                          subject="owner_key"))
    check("subject 与 owner 同列 → ValueError", ok, msg)
    ok, msg = _reject(lambda: declare_counters(_db("bad_c1.db"), ["tally"]), TypeError)
    check("spec 不是 CounterSpec → TypeError", ok, msg)

    # 非法声明不留半份注册
    db = _db("bad_after.db")
    _reject(lambda: declare_snapshot(db, SnapshotSpec("x; DROP TABLE y", owner="owner_key",
                                                      blob="body")))
    with db.readonly() as conn:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    check("★ 非法声明不留半份注册（schema_names 空、库里无表）",
          db.schema_names == [] and names == [], f"{db.schema_names} / {names}")


# ───────────────────────────────────────────── 2 建表形状
def t2_table_shape():
    print("\n[2] 建表形状：声明 → TableSpec → 既有 declare")
    db, repo = _snap("snap_shape.db")
    cols = _pragma(db, "notes")
    check("列序 = owner / blob / stamp / extra", [c[0] for c in cols] ==
          ["owner_key", "body", "stamp_col", "label"], str(cols))
    check("主键位只落在 owner_key",
          [c[0] for c in cols if c[4]] == ["owner_key"], str(cols))
    check("返回 SnapshotRepo，且装配了 table / owner / blob",
          isinstance(repo, SnapshotRepo) and repo.table == "notes"
          and repo.owner_col == "owner_key" and repo.blob_col == "body", repr(repo))

    # 等价手写 TableSpec（同一份声明走既有 declare 路径，PRAGMA 应逐列一致）
    db2 = _db("snap_hand.db")
    declare(db2, TableSpec("notes", [
        Column("owner_key", "TEXT", pk=True), Column("body", "TEXT", default="{}"),
        Column("stamp_col", "INTEGER"), Column("label", "TEXT", default=""),
    ]), json_fields=("body",))
    check("与等价手写 TableSpec 的 PRAGMA 逐列一致", _pragma(db2, "notes") == cols,
          f"{_pragma(db2, 'notes')} vs {cols}")

    dbk, repok = _snap("snap_key.db", SNAP_KEY_SPEC)
    colsk = _pragma(dbk, "notes_in")
    check("stamp_key 形态不建时间列（只有 owner/blob）",
          [c[0] for c in colsk] == ["owner_key", "body"], str(colsk))

    dbc, cnt = _cnt("cnt_shape.db")
    colsc = _pragma(dbc, "tally")
    check("计数器列：owner + 声明列 + extra（默认 0）",
          [c[0] for c in colsc] == ["owner_key", "a", "b", "c", "spare"], str(colsc))
    check("计数器声明列默认值 0 且非空（extra 不在此约束内）",
          all(c[3] == "0" and c[2] == 1 for c in colsc[1:4]), str(colsc))
    check("extra 列按声明建（default 0、可空）",
          colsc[4] == ("spare", "INTEGER", 0, "0", 0), str(colsc[4]))
    check("Counters.fields 回声明列元组（不含 extra）", cnt.fields == ("a", "b", "c"),
          repr(cnt.fields))

    dbs, cnts = _cnt("cnt_sub.db", COUNT_SUB_SPEC)
    colss = _pragma(dbs, "tally_sub")
    check("复合键形态：主键 = (owner, subject) 且顺序一致",
          [c[0] for c in colss if c[4]] == ["owner_key", "topic"], str(colss))
    check("复合键表列序 = owner / fields / subject",
          [c[0] for c in colss] == ["owner_key", "n", "topic"], str(colss))


# ───────────────────────────────────────────── 3 TTL 三出口
def t3_ttl_three_exits():
    print("\n[3] TTL 三出口逐格：未过期 / 过期 + keep 假（删）/ 过期 + keep 真（打标保留）")
    for spec, tag in ((SNAP_SPEC, "stamp 列"), (SNAP_KEY_SPEC, "stamp_key 载荷键")):
        db, repo = _snap(f"ttl_{len(tag)}.db", spec)
        seen = []

        def on_expire(owner, payload, _seen=seen):
            _seen.append((owner, dict(payload)))

        def body(n, stamp=100):
            """该形态下落库后的载荷期望值（stamp_key 形态把时间戳写进载荷）。"""
            if spec.stamp_key is not None and stamp is not None:
                return {"n": n, spec.stamp_key: stamp}
            return {"n": n}

        with db.session() as conn:
            repo.put(conn, "fresh", {"n": 1}, stamp=100)
            repo.put(conn, "stale", {"n": 2}, stamp=100)
            repo.put(conn, "kept", {"n": 3}, stamp=100)
            repo.put(conn, "no_stamp", {"n": 4})
        with db.readonly() as conn:
            check(f"[{tag}] 格 A：未过期 → 载荷原样返回",
                  repo.get(conn, "fresh", now=105, ttl=10) == body(1),
                  str(repo.get(conn, "fresh", now=105, ttl=10)))
            check(f"[{tag}] 格 A：未过期 → 行仍在", repo.raw(conn, "fresh") == body(1))
            check(f"[{tag}] 边界：恰好在期（now-stamp == ttl）→ 未过期",
                  repo.get(conn, "fresh", now=110, ttl=10) == body(1))

        with db.session() as conn:
            got = repo.get(conn, "stale", now=1000, ttl=10, on_expire=on_expire)
        with db.readonly() as conn:
            check(f"[{tag}] 格 B：过期 + keep 假 → 返回 None", got is None)
            check(f"[{tag}] 格 B：过期 + keep 假 → 行被删", repo.raw(conn, "stale") is None)
            check(f"[{tag}] 格 B：on_expire 被调一次且拿到 (owner, 载荷)",
                  seen == [("stale", body(2))], str(seen))

        with db.session() as conn:
            got = repo.get(conn, "kept", now=1000, ttl=10,
                           keep=lambda owner, payload: True, on_expire=on_expire)
        with db.readonly() as conn:
            row = repo.raw(conn, "kept")
            stamp = repo.stamp_of(conn, "kept")
            check(f"[{tag}] 格 C：过期 + keep 真 → 仍返回 None", got is None)
            check(f"[{tag}] 格 C：行保留（没被删）", row is not None, str(row))
            check(f"[{tag}] 格 C：载荷被打标 stale_mark=True",
                  row is not None and row.get("stale_mark") is True, str(row))
            check(f"[{tag}] 格 C：★ 打标不改 stamp（仍是 100）", stamp == 100, repr(stamp))
            check(f"[{tag}] 格 C：on_expire 拿到的是已打标的载荷",
                  seen[-1] == ("kept", dict(body(3), stale_mark=True)), str(seen[-1]))
            check(f"[{tag}] 无 stamp 的行不参与过期门（0/None → 不过期）",
                  repo.get(conn, "no_stamp", now=99999, ttl=1) == {"n": 4})

        with db.readonly() as conn:
            check(f"[{tag}] ttl=None → 不过期门（等价 raw）",
                  repo.get(conn, "kept", now=99999, ttl=None) is not None)

    # ttl 给值但没声明 stamp/stamp_key → fail-closed（不静默「永不过期」）
    db, repo = _snap("ttl_nostamp.db",
                     SnapshotSpec("notes_plain", owner="owner_key", blob="body"))
    with db.session() as conn:
        repo.put(conn, "o1", {"n": 1})
    ok, msg = _reject(lambda: _call(lambda c: repo.get(c, "o1", now=1, ttl=1), db))
    check("★ 未声明 stamp/stamp_key 却传 ttl → ValueError", ok, msg)
    print(f"      {msg}")
    ok, msg = _reject(lambda: _call(lambda c: repo.put(c, "o1", {"n": 1}, stamp=5), db))
    check("★ 未声明 stamp/stamp_key 却传 stamp= → ValueError", ok, msg)
    print(f"      {msg}")

    # 坏 JSON → raw 回 None（保守）
    db, repo = _snap("ttl_badjson.db")
    with db.session() as conn:
        conn.execute("INSERT INTO notes (owner_key, body, stamp_col) VALUES (?,?,?)",
                     ("broken", "{not json", 100))
    with db.readonly() as conn:
        check("JSON 坏值 → raw 回 None（不抛）", repo.raw(conn, "broken") is None)


def _call(fn, db):
    with db.session() as conn:
        return fn(conn)


# ───────────────────────────────────────────── 4 sweep
def t4_sweep():
    print("\n[4] sweep：返回过期清单 + 内存存活优先（keep 真者不被删）")
    db, repo = _snap("sweep.db")
    keep = lambda owner, payload: payload.get("keep_me") is True      # noqa: E731
    seen = []
    with db.session() as conn:
        repo.put(conn, "alive", {"n": 1}, stamp=995)
        repo.put(conn, "drop_1", {"n": 2}, stamp=100)
        repo.put(conn, "keep_1", {"n": 3, "keep_me": True}, stamp=100)
        repo.put(conn, "drop_2", {"n": 4}, stamp=100)
        repo.put(conn, "keep_2", {"n": 5, "keep_me": True}, stamp=100)
    with db.session() as conn:
        gone = repo.sweep(conn, now=1000, ttl=10, keep=keep,
                          on_expire=lambda o, p: seen.append(o))
    with db.readonly() as conn:
        check("sweep 返回全部过期 owner（表序，含 keep 真者）",
              [o for o, _ in gone] == ["drop_1", "keep_1", "drop_2", "keep_2"],
              str([o for o, _ in gone]))
        check("sweep 清单里带过期时的载荷原值",
              [p for _, p in gone] == [{"n": 2}, {"n": 3, "keep_me": True},
                                       {"n": 4}, {"n": 5, "keep_me": True}], str(gone))
        check("keep 为假者被删", repo.raw(conn, "drop_1") is None
              and repo.raw(conn, "drop_2") is None)
        check("★ keep 为真者不被删（内存存活优先）",
              repo.raw(conn, "keep_1") is not None and repo.raw(conn, "keep_2") is not None)
        check("★ keep 为真者被打标且 stamp 未变",
              repo.raw(conn, "keep_1")["stale_mark"] is True
              and repo.stamp_of(conn, "keep_1") == 100, str(repo.raw(conn, "keep_1")))
        check("未过期者不动（无标、无副作用）",
              repo.raw(conn, "alive") == {"n": 1} and repo.stamp_of(conn, "alive") == 995)
        check("on_expire 对每个过期行都调用（keep 真者也调，供内容侧补销毁动作）",
              seen == ["drop_1", "keep_1", "drop_2", "keep_2"], str(seen))
        check("count 与实际行数一致", repo.count(conn) == 3, str(repo.count(conn)))
    with db.session() as conn:
        check("再 sweep 一次（幂等）：已删的不在、打标过的仍在且再次打标",
              [o for o, _ in repo.sweep(conn, now=1005, ttl=10, keep=keep)]
              == ["keep_1", "keep_2"])


# ───────────────────────────────────────────── 5 raw/put/merge/drop/owners
def t5_snapshot_crud():
    print("\n[5] 快照读写口：raw / put / merge / drop / owners / count")
    db, repo = _snap("crud.db")
    with db.session() as conn:
        repo.put(conn, "o1", {"n": 1, "deep": {"k": "v"}}, stamp=100)
        repo.put(conn, "o1", {"n": 2}, stamp=200)
    with db.readonly() as conn:
        check("put 是整行 upsert（旧载荷被整体替换）",
              repo.raw(conn, "o1") == {"n": 2} and repo.stamp_of(conn, "o1") == 200)
        check("raw 未知 owner → None", repo.raw(conn, "nobody") is None)

    with db.session() as conn:
        merged = repo.merge(conn, "o1", {"extra": True}, stamp=300)
    with db.readonly() as conn:
        check("merge 回合并后载荷（供「继承旧字段」用）",
              merged == {"n": 2, "extra": True}, str(merged))
        check("merge 落库 + 更新 stamp",
              repo.raw(conn, "o1") == {"n": 2, "extra": True}
              and repo.stamp_of(conn, "o1") == 300)

    caller_payload = {}
    with db.session() as conn:
        repo.put(conn, "o2", caller_payload, stamp=1)
    check("★ put 不写调用方传进来的 dict（stamp 落列，不塞回 dict）",
          caller_payload == {}, str(caller_payload))

    with db.session() as conn:
        repo.put(conn, "o3", {"n": 3}, stamp=1)
        repo.put(conn, "o4", {"n": 4}, stamp=1)
    with db.readonly() as conn:
        check("owners(prefix=) 只用 owner 列（不给 → 全量）",
              sorted(repo.owners(conn, prefix="o")) == ["o1", "o2", "o3", "o4"]
              and sorted(repo.owners(conn)) == ["o1", "o2", "o3", "o4"],
              str(sorted(repo.owners(conn))))
    with db.session() as conn:
        n = repo.drop(conn, "o4")
        n0 = repo.drop(conn, "o4")
    check("drop 回受影响行数（删到 1 / 无行 0）", (n, n0) == (1, 0), f"{n}/{n0}")

    ok, msg = _reject(lambda: _call(lambda c: repo.put(c, "o5", ["not", "dict"]), db),
                      TypeError)
    check("put 载荷不是 dict → TypeError（形状口径 ④）", ok, msg)

    # stamp_key 形态：stamp 写在载荷里，且不污染调用方 dict
    dbk, repok = _snap("crud_key.db", SNAP_KEY_SPEC)
    payload = {"n": 1}
    with dbk.session() as conn:
        repok.put(conn, "o1", payload, stamp=555)
    with dbk.readonly() as conn:
        check("stamp_key 形态：时间落进载荷键（列只有 owner/blob）",
              repok.raw(conn, "o1") == {"n": 1, "born_at": 555}
              and repok.stamp_of(conn, "o1") == 555)
        check("stamp_key 形态：调用方 dict 未被写入",
              payload == {"n": 1}, str(payload))
        check("stamp_key 形态：get 用载荷内的键判过期",
              repok.get(conn, "o1", now=1000, ttl=10) is None)


# ───────────────────────────────────────────── 6 计数器
def t6_accumulate():
    print("\n[6] 计数器：init 建行 + bump 累加 + read 全列")
    db, cnt = _cnt("cnt.db")
    with db.readonly() as conn:
        check("★ read 无行 → {}（逐字保留现状口径）", cnt.read(conn, "nobody") == {})

    with db.session() as conn:
        cnt.init(conn, "o1")
        cnt.bump(conn, "o1", a=1, b=5)
        cnt.bump(conn, "o1", a=2)
        cnt.bump(conn, "o1", c=-1)
    with db.readonly() as conn:
        row = cnt.read(conn, "o1")
    check("init 建行 + bump 累加（含负增量）",
          (row.get("a"), row.get("b"), row.get("c")) == (3, 5, -1), str(row))
    check("read 回该行全部列（含 extra）",
          set(row) == {"owner_key", "a", "b", "c", "spare"}, str(sorted(row)))

    with db.session() as conn:
        cnt.init(conn, "o1")                     # INSERT OR IGNORE：不覆盖既有值
    with db.readonly() as conn:
        check("init 不覆盖既有值（与现状 init_stats 同口径）",
              cnt.read(conn, "o1")["a"] == 3)

    with db.session() as conn:
        cnt.init(conn, "o2")
    with db.readonly() as conn:
        check("init 建的新行：声明列默认 0",
              cnt.read(conn, "o2") == {"owner_key": "o2", "a": 0, "b": 0, "c": 0,
                                       "spare": 0}, str(cnt.read(conn, "o2")))


def t6b_whitelist():
    print("\n[6b] 白名单 fail-closed：声明外字段当场抛，且一个字节都没写")
    db, cnt = _cnt("cnt_wl.db")
    ok, msg = _reject(lambda: _call(lambda c: cnt.bump(c, "o1", nope=1), db))
    check("★ bump 白名单外 → ValueError", ok, msg)
    print(f"      {msg}")
    ok, msg = _reject(lambda: _call(lambda c: cnt.bump(c, "o1", spare=1), db))
    check("★ extra 列不在 fields 声明里 → 同样 ValueError", ok, msg)
    with db.session() as conn:
        cnt.init(conn, "o1")
    ok, msg = _reject(lambda: _call(lambda c: cnt.bump(c, "o1", a=1, nope=2), db))
    check("混入一个非法名 → 整条拒（合法名也没写）", ok and "nope" in msg, msg)
    with db.readonly() as conn:
        check("被拒后行值仍是 0（无部分写入）", cnt.read(conn, "o1")["a"] == 0)
    ok, msg = _reject(lambda: _call(lambda c: cnt.bump(c, "o1"), db))
    check("空 deltas → ValueError（不拼出 `SET  WHERE` 坏 SQL）", ok, msg)
    ok, msg = _reject(lambda: _call(lambda c: cnt.reset(c, "o1", fields=("zz",)), db))
    check("reset 白名单外 → ValueError", ok, msg)

    with db.session() as conn:
        cnt.bump(conn, "o1", a=4, b=9)
    with db.session() as conn:
        cnt.reset(conn, "o1", fields=("a",))
    with db.readonly() as conn:
        check("reset(fields=) 只清指定列", cnt.read(conn, "o1")["a"] == 0
              and cnt.read(conn, "o1")["b"] == 9)
    with db.session() as conn:
        cnt.reset(conn, "o1")
    with db.readonly() as conn:
        check("reset() 清全部声明列（extra 不在其中）",
              cnt.read(conn, "o1")["b"] == 0 and cnt.read(conn, "o1")["spare"] == 0)

    with db.session() as conn:
        cnt.bump(conn, "o1", a=4)
    with db.readonly() as conn:
        check("next_of 回「当前值 + 1」且不写库",
              cnt.next_of(conn, "o1", "a") == 5 and cnt.read(conn, "o1")["a"] == 4)
        check("next_of 无行 → 1", cnt.next_of(conn, "zz", "a") == 1)


def t6c_composite_key():
    print("\n[6c] 复合键（subject）：同一 owner 不同 subject 互不干扰")
    db, cnt = _cnt("cnt_sub.db", COUNT_SUB_SPEC)
    with db.session() as conn:
        cnt.init(conn, "o1", subject="x")
        cnt.init(conn, "o1", subject="y")
        cnt.init(conn, "o2", subject="x")
        cnt.bump(conn, "o1", subject="x", n=1)
        cnt.bump(conn, "o1", subject="y", n=5)
        cnt.bump(conn, "o1", subject="x", n=2)
        cnt.bump(conn, "o2", subject="x", n=9)
    with db.readonly() as conn:
        check("★ 同一 owner 不同 subject：各记各的",
              (cnt.read(conn, "o1", subject="x")["n"],
               cnt.read(conn, "o1", subject="y")["n"]) == (3, 5),
              str(cnt.read(conn, "o1", subject="x")))
        check("★ 同一 subject 不同 owner：各记各的",
              cnt.read(conn, "o2", subject="x")["n"] == 9)
        check("无该 (owner, subject) → {}", cnt.read(conn, "o1", subject="zz") == {})
        check("read_subject 列举该 owner 全部 subject 行",
              sorted(r["topic"] for r in cnt.read_subject(conn, "o1")) == ["x", "y"],
              str(cnt.read_subject(conn, "o1")))
        check("read_subject(order_by, limit) 可用",
              [r["topic"] for r in cnt.read_subject(conn, "o1", order_by="n DESC",
                                                    limit=1)] == ["y"])
    with db.session() as conn:
        cnt.reset(conn, "o1", subject="x")
    with db.readonly() as conn:
        check("reset(subject=) 只清那一格", cnt.read(conn, "o1", subject="x")["n"] == 0
              and cnt.read(conn, "o1", subject="y")["n"] == 5)

    db2, cnt1 = _cnt("cnt_single.db")
    ok, msg = _reject(lambda: _call(lambda c: cnt1.init(c, "o1", subject="x"), db2))
    check("★ 单键声明却传 subject → ValueError（不静默退化）", ok, msg)
    print(f"      {msg}")
    ok, msg = _reject(lambda: _call(lambda c: cnt.read(c, "o1"), db2))
    check("★ 复合键声明不传 subject → ValueError（不静默读错行）", ok, msg)
    print(f"      {msg}")


# ───────────────────────────────────────────── 7 不自己 commit
def t7_no_commit():
    print("\n[7] 写路径不自己 commit（事务边界交调用方）")
    db, repo = _snap("commit.db")
    dbk, repok = _snap("commit_key.db", SNAP_KEY_SPEC)
    dbc, cnt = _cnt("commit_cnt.db")
    dbs, cnts = _cnt("commit_sub.db", COUNT_SUB_SPEC)
    total = 0
    with db.session() as conn:
        spy = _SpyConn(conn)
        repo.put(spy, "o1", {"n": 1}, stamp=1)
        repo.merge(spy, "o1", {"m": 2}, stamp=2)
        repo.drop(spy, "o1")
        repo.sweep(spy, now=9, ttl=1)
        total += spy.commits
    with dbk.session() as conn:
        spy = _SpyConn(conn)
        repok.put(spy, "o1", {"n": 1}, stamp=1)
        repok.get(spy, "o1", now=9, ttl=1, keep=lambda o, p: True)
        repok.sweep(spy, now=9, ttl=1, keep=lambda o, p: True)
        total += spy.commits
    with dbc.session() as conn:
        spy = _SpyConn(conn)
        cnt.init(spy, "o1")
        cnt.bump(spy, "o1", a=1)
        cnt.reset(spy, "o1")
        cnt.next_of(spy, "o1", "a")
        cnt.read(spy, "o1")
        total += spy.commits
    with dbs.session() as conn:
        spy = _SpyConn(conn)
        cnts.init(spy, "o1", subject="x")
        cnts.bump(spy, "o1", subject="x", n=1)
        cnts.read(spy, "o1", subject="x")
        cnts.reset(spy, "o1", subject="x")
        cnts.next_of(spy, "o1", "n", subject="x")
        cnts.read_subject(spy, "o1")
        total += spy.commits
    check("★ 全部写路径 commit 次数 = 0", total == 0, f"commit={total}")

    # 只读口不许 commit；也不许有隐藏写（读路径只 SELECT）
    with db.session() as conn:
        repo.put(conn, "o9", {"n": 9}, stamp=1)
    with db.readonly() as conn:
        spy = _SpyConn(conn)
        repo.raw(spy, "o9")
        repo.get(spy, "o9", now=1, ttl=None)
        repo.stamp_of(spy, "o9")
        repo.owners(spy)
        repo.count(spy)
        check("只读口零 commit", spy.commits == 0, f"commit={spy.commits}")


# ───────────────────────────────────────────── 8 O(1)
def t8_constant_time():
    print("\n[8] 构造/取值 O(1)：语句数不随行数增长（sweep 除外）")
    db_s, repo_s = _snap("o1_small.db")
    db_b, repo_b = _snap("o1_big.db")
    db_cs, cnt_s = _cnt("o1_small_cnt.db")
    db_cb, cnt_b = _cnt("o1_big_cnt.db")
    with db_b.session() as conn:
        conn.executemany("INSERT INTO notes (owner_key, body, stamp_col) VALUES (?,?,?)",
                         [(f"o{i}", "{}", 100) for i in range(3000)])
    with db_cb.session() as conn:
        conn.executemany("INSERT INTO tally (owner_key) VALUES (?)",
                         [(f"o{i}",) for i in range(3000)])
    with db_s.session() as conn:
        repo_s.put(conn, "o1", {"n": 1}, stamp=100)
    with db_cs.session() as conn:
        cnt_s.init(conn, "o1")

    counts = {}
    with db_b.readonly() as conn:
        for label, fn in (("raw", lambda c: repo_b.raw(c, "o1500")),
                          ("get", lambda c: repo_b.get(c, "o1500", now=1, ttl=None)),
                          ("stamp_of", lambda c: repo_b.stamp_of(c, "o1500")),
                          ("count", lambda c: repo_b.count(c)),
                          ("owners", lambda c: repo_b.owners(c, prefix="o150"))):
            spy = _SpyConn(conn)
            fn(spy)
            counts[label] = spy.executes
    with db_b.session() as conn:
        spy = _SpyConn(conn)
        repo_b.put(spy, "o1500", {"n": 1}, stamp=100)
        counts["put"] = spy.executes
        spy = _SpyConn(conn)
        repo_b.drop(spy, "o1500")
        counts["drop"] = spy.executes
    with db_cb.readonly() as conn:
        spy = _SpyConn(conn)
        cnt_b.read(spy, "o1500")
        counts["cnt_read"] = spy.executes
        spy = _SpyConn(conn)
        cnt_b.next_of(spy, "o1500", "a")
        counts["cnt_next"] = spy.executes
    with db_cb.session() as conn:
        spy = _SpyConn(conn)
        cnt_b.bump(spy, "o1500", a=1)
        counts["cnt_bump"] = spy.executes
        spy = _SpyConn(conn)
        cnt_b.reset(spy, "o1500")
        counts["cnt_reset"] = spy.executes

    with db_s.readonly() as conn:
        small = {}
        spy = _SpyConn(conn)
        repo_s.raw(spy, "o1")
        small["raw"] = spy.executes
        spy = _SpyConn(conn)
        repo_s.get(spy, "o1", now=1, ttl=None)
        small["get"] = spy.executes
        spy = _SpyConn(conn)
        repo_s.stamp_of(spy, "o1")
        small["stamp_of"] = spy.executes
        spy = _SpyConn(conn)
        repo_s.count(spy)
        small["count"] = spy.executes
    with db_cs.readonly() as conn:
        spy = _SpyConn(conn)
        cnt_s.read(spy, "o1")
        small["cnt_read"] = spy.executes
        spy = _SpyConn(conn)
        cnt_s.next_of(spy, "o1", "a")
        small["cnt_next"] = spy.executes
    with db_s.session() as conn:
        spy = _SpyConn(conn)
        repo_s.put(spy, "o1", {"n": 1}, stamp=100)
        small["put"] = spy.executes
        spy = _SpyConn(conn)
        repo_s.drop(spy, "o1")
        small["drop"] = spy.executes
    with db_cs.session() as conn:
        spy = _SpyConn(conn)
        cnt_s.bump(spy, "o1", a=1)
        small["cnt_bump"] = spy.executes
        spy = _SpyConn(conn)
        cnt_s.reset(spy, "o1")
        small["cnt_reset"] = spy.executes

    print(f"      3000 行: {counts}")
    print(f"        1 行: {small}")
    check("★ 逐口语句数 ≤ 4 且不随行数增长",
          all(v <= 4 for v in counts.values())
          and all(counts[k] == small[k] for k in small),
          f"big={counts} small={small}")

    # 构造 O(1)：把仓库所属 Database 的 connect 换成炸弹，构造期一开连接就炸
    db_ctor = _db("ctor.db")
    db_ctor2 = _db("ctor_cnt.db")
    snap = declare_snapshot(db_ctor, SNAP_SPEC)
    cnts = declare_counters(db_ctor2, COUNT_SPEC)
    inner_s, inner_c = snap.repo, cnts.repo

    def boom(*_a, **_k):
        raise AssertionError("构造期不得开连接")

    db_ctor.connect = boom
    db_ctor2.connect = boom
    n = 50000
    for _ in range(n):
        SnapshotRepo(inner_s, SNAP_SPEC)
        Counters(inner_c, COUNT_SPEC)
    check(f"构造 {n * 2} 次不开连接（构造 O(1)、零遍历）", True)


# ───────────────────────────────────────────── 9 静态面
VALUE_WORDS = (
    "奥兰迪亚", "余烬", "镇长", "游商", "见闻", "师门",
    "main_quest", "main_status", "main_progress", "completed_main", "side", "daily",
    "pending", "active", "ready", "done", "closed", "open", "running",
    "kill", "collect", "collect_count", "explore", "find", "use", "talk",
    "kill_any", "kill_elite", "kill_boss", "complete_side", "collect_any",
    "objective", "next", "giver", "board", "unlock", "min_level", "min_lv",
    "require_stats", "require_race", "suggest_lv", "chain", "branch", "endings",
    "qq_id", "monster", "state", "updated_at", "created_at", "used", "kills",
    "total", "stats", "battle_state", "props_use", "bestiary", "fishing",
    "event_state", "instance_world_", "talk_", "wildmeta_", "timed_events_",
    "data.plugins.dragonfall",
    "battle_start", "turn_start", "act_begin", "act_cast", "skill_hit", "attack_hit",
    "crit", "on_taken", "on_heal", "on_kill", "on_death", "dot_tick", "dot_calc",
    "on_act_consume", "on_hit_consume", "buff_expire", "threshold", "dmg_calc",
    "taken_calc", "heal_calc", "act_done", "phase", "player_low", "pv_broken",
    "interrupt", "time_advance",
    "__end__", "story", "……",
)
FORBIDDEN_IMPORTS = ("os", "sys", "json", "datetime", "time", "calendar",
                     "zoneinfo", "random")
FIELD_WORDS = ("qq_id", "state", "updated_at", "created_at", "kills", "stats")
STORE_DIR = os.path.join(ROOT, "saintess_engine", "store")
NEW_MODULES = ("snapshots.py", "counters.py")


def _docstrings(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            d = ast.get_docstring(node, clean=False)
            if d is not None:
                out.add(d)
    return out


def _tree(name):
    path = os.path.join(STORE_DIR, name)
    return path, ast.parse(open(path, encoding="utf-8").read(), filename=path)


def t9_static_scan():
    print("\n[9] 静态面：import 白名单 / 零取值词 / 零字段知识 / 不 import periodic")
    for name in NEW_MODULES:
        path, tree = _tree(name)
        bad_imp = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                root = mod.split(".")[0]
                if root in FORBIDDEN_IMPORTS or "periodic" in mod.split("."):
                    bad_imp.append(f"L{node.lineno}: from {mod}")
                if not node.level and root and root not in sys.stdlib_module_names:
                    bad_imp.append(f"L{node.lineno}: 非标准库 from {mod}")
            elif isinstance(node, ast.Import):
                for a in node.names:
                    root = a.name.split(".")[0]
                    if root in FORBIDDEN_IMPORTS or root not in sys.stdlib_module_names:
                        bad_imp.append(f"L{node.lineno}: import {a.name}")
        check(f"★ {name}：只相对导入 + 标准库；零 {'/'.join(FORBIDDEN_IMPORTS)}",
              not bad_imp, str(bad_imp))

        ds = _docstrings(tree)
        vals = [n for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and n.value not in ds]
        hits_exact = [v.value for v in vals if v.value in VALUE_WORDS]
        hits_sub = sorted({w for v in vals for w in VALUE_WORDS if w in v.value})
        check(f"★ {name}：代码字符串常量零取值词（精确匹配）", not hits_exact,
              str(hits_exact))
        check(f"★ {name}：代码字符串常量零取值词（子串匹配）", not hits_sub,
              str(hits_sub))

        fh = [v.value for v in vals if any(w in v.value for w in FIELD_WORDS)]
        check(f"★ {name}：零字段知识（不含 {'/'.join(FIELD_WORDS)}）", not fh, str(fh))
        print(f"      扫描 {path}：代码字符串常量 {len(vals)} 个")

    all_bad = []
    for name in sorted(os.listdir(STORE_DIR)):
        if not name.endswith(".py"):
            continue
        _p, tree = _tree(name)
        ds = _docstrings(tree)
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) \
                    and n.value not in ds and any(w in n.value for w in FIELD_WORDS):
                all_bad.append(f"{name}:L{n.lineno} {n.value!r}")
    check("★ store/*.py 全包零字段字面量（含既有 6 文件）", not all_bad, str(all_bad[:5]))

    for name in NEW_MODULES:
        _p, tree = _tree(name)
        per = [f"L{n.lineno}: {n.module}" for n in ast.walk(tree)
               if isinstance(n, ast.ImportFrom)
               and "periodic" in (n.module or "").split(".")]
        per += [f"L{n.lineno}: import {a.name}" for n in ast.walk(tree)
                if isinstance(n, ast.Import) for a in n.names
                if "periodic" in a.name.split(".")]
        check(f"★ {name}：import periodic 命中 0（避让判据 ⑤；docstring 提到不算）",
              not per, str(per))
        src = open(os.path.join(STORE_DIR, name), encoding="utf-8").read()
        check(f"★ {name}：源码无 .commit( 调用（判据 10 静态侧）",
              ".commit(" not in src)


# ───────────────────────────────────────────── 10 有牙反证
def _green(probe):
    try:
        return bool(probe()), ""
    except Exception as e:                                        # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def _tooth(label, probe, mutate, restore):
    ok0, d0 = _green(probe)
    check(f"[牙前] {label}：原实现下探针绿", ok0, d0)
    mutate()
    try:
        ok1, d1 = _green(probe)
    finally:
        restore()
    check(f"★ [牙] {label}：预期变红 / 实测{'仍绿' if ok1 else '变红'}", not ok1, d1)


def _probe_ttl_expired():
    db, repo = _snap("tooth_ttl.db")
    with db.session() as conn:
        repo.put(conn, "o1", {"n": 1}, stamp=100)
    with db.readonly() as conn:
        return repo.get(conn, "o1", now=1000, ttl=10) is None


def _probe_keep_survives():
    db, repo = _snap("tooth_keep.db")
    with db.session() as conn:
        repo.put(conn, "o1", {"n": 1}, stamp=100)
        repo.get(conn, "o1", now=1000, ttl=10, keep=lambda o, p: True)
    with db.readonly() as conn:
        row = repo.raw(conn, "o1")
    return row is not None and row.get("stale_mark") is True


def _probe_stamp_frozen():
    db, repo = _snap("tooth_stamp.db")
    with db.session() as conn:
        repo.put(conn, "o1", {"n": 1}, stamp=100)
        repo.get(conn, "o1", now=1000, ttl=10, keep=lambda o, p: True)
    with db.readonly() as conn:
        return repo.stamp_of(conn, "o1") == 100


def _probe_bump_whitelist():
    db, cnt = _cnt("tooth_wl.db")
    with db.session() as conn:
        cnt.init(conn, "o1")
        try:
            cnt.bump(conn, "o1", spare=1)          # extra 列：存在，但不在 fields 声明里
        except ValueError:
            return True
    return False


def _probe_read_empty():
    db, cnt = _cnt("tooth_read.db")
    with db.readonly() as conn:
        return cnt.read(conn, "nobody") == {}


def _probe_subject_isolated():
    db, cnt = _cnt("tooth_sub.db", COUNT_SUB_SPEC)
    with db.session() as conn:
        cnt.init(conn, "o1", subject="x")
        cnt.init(conn, "o1", subject="y")
        cnt.bump(conn, "o1", subject="x", n=1)
        cnt.bump(conn, "o1", subject="y", n=5)
    with db.readonly() as conn:
        return (cnt.read(conn, "o1", subject="x")["n"] == 1
                and cnt.read(conn, "o1", subject="y")["n"] == 5)


def t10_teeth():
    print("\n[10] 有牙反证（逐处：预期变红 / 实测变红）")

    # ① TTL 判定改成「永远不过期」
    orig_get = SnapshotRepo.get

    def m1():
        SnapshotRepo.get = lambda self, conn, owner, **kw: self.raw(conn, owner)
    _tooth("① TTL 恒不过期（get 退化成 raw）", _probe_ttl_expired, m1,
           lambda: setattr(SnapshotRepo, "get", orig_get))

    # ② keep 分支被忽略（过期一律删）
    orig_exp = SnapshotRepo._expire_row

    def m2():
        def _ignore_keep(self, conn, owner, payload, **kw):
            self.drop(conn, owner)
        SnapshotRepo._expire_row = _ignore_keep
    _tooth("② keep 被忽略（过期一律删）", _probe_keep_survives, m2,
           lambda: setattr(SnapshotRepo, "_expire_row", orig_exp))

    # ③ 打标顺手改 stamp
    orig_mark = SnapshotRepo._mark_expired

    def m3():
        def _mark_and_touch(self, conn, owner, payload):
            orig_mark(self, conn, owner, payload)
            if self.spec.stamp:
                conn.execute(f"UPDATE {self.spec.table} SET {self.spec.stamp}=?"
                             f" WHERE {self.spec.owner}=?", (999, owner))
        SnapshotRepo._mark_expired = _mark_and_touch
    _tooth("③ 打标顺手改 stamp（过期标记自我续命）", _probe_stamp_frozen, m3,
           lambda: setattr(SnapshotRepo, "_mark_expired", orig_mark))

    # ④ bump 白名单放行任意列名
    orig_bump = Counters.bump

    def m4():
        def _bump_open(self, conn, owner, *, subject=None, **deltas):
            self._subject_of(subject)
            sets = ", ".join(f"{k}={k}+?" for k in deltas)
            conn.execute(f"UPDATE {self.spec.table} SET {sets}"
                         f" WHERE {self.spec.owner}=?", (*deltas.values(), owner))
        Counters.bump = _bump_open
    _tooth("④ bump 白名单放开（任意列名可写）", _probe_bump_whitelist, m4,
           lambda: setattr(Counters, "bump", orig_bump))

    # ⑤ read 无行 → None（而不是 {}）
    orig_read = Counters.read

    def m5():
        Counters.read = lambda self, conn, owner, **kw: self.repo.get(conn, owner)
    _tooth("⑤ read 无行回 None（丢了空值口径）", _probe_read_empty, m5,
           lambda: setattr(Counters, "read", orig_read))

    # ⑥ 复合键退化成单键（subject 被忽略）
    def m6():
        def _bump_single(self, conn, owner, *, subject=None, **deltas):
            self._subject_of(subject)
            bad = [k for k in deltas if k not in self.fields]
            if bad:
                raise ValueError(f"bump 非法字段: {bad}（不在声明白名单）")
            sets = ", ".join(f"{k}={k}+?" for k in deltas)
            conn.execute(f"UPDATE {self.spec.table} SET {sets}"
                         f" WHERE {self.spec.owner}=?", (*deltas.values(), owner))
        Counters.bump = _bump_single
    _tooth("⑥ 复合键退化（subject 未进 WHERE）", _probe_subject_isolated, m6,
           lambda: setattr(Counters, "bump", orig_bump))


def t11_multifault_and_order():
    print("\n[11] 多故障 + 顺序断言（只坏一处证明不了顺序）")
    orig_get = SnapshotRepo.get
    orig_bump = Counters.bump

    def m_two():
        SnapshotRepo.get = lambda self, conn, owner, **kw: self.raw(conn, owner)
        Counters.bump = lambda self, conn, owner, **kw: None
    m_two()
    try:
        ok1, _ = _green(_probe_ttl_expired)
        ok2, _ = _green(_probe_subject_isolated)
        ok3, _ = _green(_probe_read_empty)
    finally:
        SnapshotRepo.get = orig_get
        Counters.bump = orig_bump
    check("★ 两处同坏（TTL + bump）→ 两个对应探针都红", (not ok1) and (not ok2),
          f"ttl={'红' if not ok1 else '绿'} subject={'红' if not ok2 else '绿'}")
    check("★ 第三处（read 无行 → {}）仍绿（故障可归因）", ok3)

    # 顺序①：非 keep 分支 on_expire 在删行之前
    db, repo = _snap("order1.db")
    seen = []

    def probe_order1():
        with db.session() as conn:
            repo.put(conn, "o1", {"n": 1}, stamp=100)
        with db.session() as conn:
            repo.get(conn, "o1", now=1000, ttl=10,
                     on_expire=lambda o, p: seen.append(repo.raw(conn, o)))
        return seen == [{"n": 1}]
    check("★ 顺序：on_expire 回调里行还在（回调在 DELETE 之前）", probe_order1(),
          str(seen))

    # 顺序②：keep 分支打标在 on_expire 之前
    db2, repo2 = _snap("order2.db")
    seen2 = []
    with db2.session() as conn:
        repo2.put(conn, "o1", {"n": 1}, stamp=100)
        repo2.get(conn, "o1", now=1000, ttl=10, keep=lambda o, p: True,
                  on_expire=lambda o, p: seen2.append(dict(p)))
    check("★ 顺序：keep 分支 on_expire 拿到的是已打标载荷（打标在前）",
          seen2 == [{"n": 1, "stale_mark": True}], str(seen2))


def main():
    print("== store 快照/计数器形状门禁：snapshots + counters ==")
    try:
        t1_fail_closed()
        t2_table_shape()
        t3_ttl_three_exits()
        t4_sweep()
        t5_snapshot_crud()
        t6_accumulate()
        t6b_whitelist()
        t6c_composite_key()
        t7_no_commit()
        t8_constant_time()
        t9_static_scan()
        t10_teeth()
        t11_multifault_and_order()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n===== 结果：通过 {passed} / 共 {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
