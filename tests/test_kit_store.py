# -*- coding: utf-8 -*-
"""通用存储骨架（`saintess_kit.store`）契约测试。

锁死的契约（每条都是「换游戏后照样得成立」的性质）：
1. 建表：注册序执行 / `init()` 幂等 / 同名注册覆盖
2. 事务：`session()` 自动提交、异常回滚；`readonly()` 不提交；`atomic()` 单事务
3. 锁：**可重入**（会话内再开会话不死锁 —— RLock 的关键理由）
4. 迁移：`ensure_columns` 缺才补、幂等、返回补了哪些；标识符非法即拒
5. 仓库：主键取/写/删、`json_fields` 编解码、未知列静默丢弃、缺主键即拒、复合主键

**零游戏、零宿主**：本测试只用标准库 + 临时目录。

跑法：python tests/test_kit_store.py
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, FW_ROOT)

from saintess_kit.store import Database, Repository, columns_of, ensure_columns  # noqa: E402
from saintess_kit.store.migrate import _check_ident, missing_columns  # noqa: E402

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
        FAILURES.append(name)
        print(f"  ❌ {name}  {detail}")


TMP = tempfile.mkdtemp(prefix="kit_store_")


def new_db(path_name):
    db = Database(os.path.join(TMP, path_name))
    db.register_schema("core", """
        CREATE TABLE IF NOT EXISTS players (
            qq_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            level INTEGER DEFAULT 1,
            equipment TEXT DEFAULT '{}'
        );
    """)
    db.register_schema("extra", """
        CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, body TEXT);
    """)
    db.init()
    return db


# ------------------------------------------------------------------ 1. 建表
print("== 1. 建表注册 ==")
db = new_db("t1.db")
check("注册序保持", db.schema_names == ["core", "extra"], db.schema_names)
with db.readonly() as conn:
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
check("两张表都建了", {"players", "notes"} <= names, sorted(names))
db.init()   # 幂等
with db.readonly() as conn:
    n = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
check("init() 幂等（表数不增）", n == len(names), (n, len(names)))

db2 = Database(os.path.join(TMP, "t2.db"))
db2.register_schema("s", "CREATE TABLE a (x INTEGER);")
db2.register_schema("s", "CREATE TABLE b (y INTEGER);")
db2.init()
with db2.readonly() as conn:
    nm = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
check("同名注册覆盖（只有 b）", "b" in nm and "a" not in nm, sorted(nm))


# ------------------------------------------------------------------ 2. 事务
print("== 2. 事务语义 ==")
db = new_db("t3.db")
with db.session() as conn:
    conn.execute("INSERT INTO players (qq_id, name) VALUES ('1','甲')")
with db.readonly() as conn:
    got = conn.execute("SELECT name FROM players WHERE qq_id='1'").fetchone()
check("session() 自动提交", got is not None and got[0] == "甲", got)

try:
    with db.session() as conn:
        conn.execute("INSERT INTO players (qq_id, name) VALUES ('2','乙')")
        raise RuntimeError("boom")
except RuntimeError:
    pass
with db.readonly() as conn:
    got = conn.execute("SELECT name FROM players WHERE qq_id='2'").fetchone()
check("session() 异常回滚", got is None, got)

try:
    with db.readonly() as conn:
        conn.execute("INSERT INTO players (qq_id, name) VALUES ('3','丙')")
        raise RuntimeError("丢弃")
except RuntimeError:
    pass
with db.readonly() as conn:
    got = conn.execute("SELECT name FROM players WHERE qq_id='3'").fetchone()
check("readonly() 不提交（写被丢弃）", got is None, got)

with db.atomic() as conn:
    conn.execute("INSERT INTO players (qq_id, name) VALUES ('4','丁')")
with db.readonly() as conn:
    got = conn.execute("SELECT name FROM players WHERE qq_id='4'").fetchone()
check("atomic() 提交", got is not None and got[0] == "丁", got)


# ------------------------------------------------------------------ 3. 锁可重入
print("== 3. 锁可重入（RLock） ==")
reentered = {"ok": False, "err": None}
try:
    with db.session() as conn:
        # 会话内再开会话/atomic：Lock 会死锁，RLock 不会
        with db.readonly() as conn2:
            conn2.execute("SELECT 1").fetchone()
        reentered["ok"] = True
except Exception as exc:                      # noqa: BLE001
    reentered["err"] = f"{type(exc).__name__}: {exc}"
check("会话内可重入（不死锁）", reentered["ok"], reentered["err"])


# ------------------------------------------------------------------ 4. 迁移
print("== 4. 列迁移 ==")
db = new_db("t4.db")
with db.session() as conn:
    cols = columns_of(conn, "players")
check("columns_of 取到现有列", {"qq_id", "name", "level", "equipment"} <= cols, sorted(cols))
with db.session() as conn:
    miss = missing_columns(conn, "players", ["qq_id", "hp", "mp"])
check("missing_columns 只报缺的", miss == ["hp", "mp"], miss)

with db.session() as conn:
    added = ensure_columns(conn, "players", {
        "hp": "INTEGER DEFAULT 100",
        "mp": "INTEGER DEFAULT 50",
        "level": "INTEGER DEFAULT 1",          # 已有 → 跳过
    })
check("ensure_columns 只补缺失并返回补的", added == ["hp", "mp"], added)
with db.session() as conn:
    added2 = ensure_columns(conn, "players", {"hp": "INTEGER DEFAULT 100"})
check("ensure_columns 幂等（第二次 0 补）", added2 == [], added2)
with db.session() as conn:
    conn.execute("INSERT INTO players (qq_id, name, hp) VALUES ('9','己',777)")
with db.readonly() as conn:
    row = conn.execute("SELECT hp FROM players WHERE qq_id='9'").fetchone()
check("补的列可用（写入的值读得回）", row is not None and row[0] == 777, row)
with db.session() as conn:
    conn.execute("INSERT INTO players (qq_id, name) VALUES ('10','庚')")
with db.readonly() as conn:
    row = conn.execute("SELECT hp FROM players WHERE qq_id='10'").fetchone()
check("补的列 DEFAULT 生效（未赋值 → 100）", row is not None and row[0] == 100, row)

banned = []
for bad in ("players; DROP TABLE players", "1abc", "a b", "", "a-b"):
    try:
        _check_ident(bad, "表名")
    except ValueError:
        banned.append(bad)
check("非法标识符一律拒（防注入）", len(banned) == 5, banned)
try:
    with db.session() as conn:
        ensure_columns(conn, "players", {"hp; DROP": "INTEGER"})
    bad_rejected = False
except ValueError:
    bad_rejected = True
check("ensure_columns 拒非法列名", bad_rejected)


# ------------------------------------------------------------------ 5. Repository
print("== 5. Repository ==")


class Players(Repository):
    table = "players"
    pk = ("qq_id",)
    json_fields = ("equipment",)


db = new_db("t5.db")
repo = Players(db)

with db.session() as conn:
    repo.upsert(conn, {"qq_id": "p1", "name": "杰洛", "level": 5,
                       "equipment": {"sword": 1, "shield": 2}})
with db.readonly() as conn:
    row = repo.get(conn, "p1")
check("upsert + get（json_fields 自动解码）",
      row and row["name"] == "杰洛" and row["equipment"] == {"sword": 1, "shield": 2}, row)
with db.readonly() as conn:
    raw = conn.execute("SELECT equipment FROM players WHERE qq_id='p1'").fetchone()[0]
check("落盘为 JSON 文本", isinstance(raw, str) and json.loads(raw)["sword"] == 1, raw)

with db.session() as conn:
    repo.upsert(conn, {"qq_id": "p1", "name": "杰洛", "level": 9,
                       "equipment": {"sword": 3}})
with db.readonly() as conn:
    row = repo.get(conn, "p1")
check("upsert 冲突走 UPDATE", row["level"] == 9 and row["equipment"] == {"sword": 3}, row)
with db.readonly() as conn:
    check("count()", repo.count(conn) == 1)

with db.session() as conn:
    repo.upsert(conn, {"qq_id": "p2", "name": "薇", "未知列": "会被丢弃"})
with db.readonly() as conn:
    row = repo.get(conn, "p2")
check("未知列静默丢弃（不写坏 SQL）", row and row["name"] == "薇", row)

try:
    with db.session() as conn:
        repo.upsert(conn, {"name": "无主键"})
    pk_rejected = False
except ValueError:
    pk_rejected = True
check("upsert 缺主键即拒", pk_rejected)

with db.session() as conn:
    n = repo.delete(conn, "p2")
with db.readonly() as conn:
    check("delete 返回行数 + 真删了", n == 1 and repo.get(conn, "p2") is None, n)
with db.readonly() as conn:
    check("all() 列表", len(repo.all(conn)) == 1)


class Notes(Repository):
    table = "notes"
    pk = ("id",)


db6 = new_db("t6.db")
nrepo = Notes(db6)
with db6.session() as conn:
    nrepo.upsert_many(conn, [{"id": 1, "body": "a"}, {"id": 2, "body": "b"}])
with db6.readonly() as conn:
    check("upsert_many 批量", nrepo.count(conn) == 2)
    got = nrepo.all(conn, order_by="id DESC", limit=1)
check("all(order_by, limit)", len(got) == 1 and got[0]["id"] == 2, got)

try:
    Repository(db6)
    base_rejected = False
except ValueError:
    base_rejected = True
check("基类未声明 table 即拒", base_rejected)


# ------------------------------------------------------------------ 6. 零依赖
print("== 6. 零游戏 / 零宿主依赖 ==")
src_root = os.path.join(FW_ROOT, "saintess_kit")
banned_imports = []
for dirpath, dirs, fs in os.walk(src_root):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    for f in fs:
        if not f.endswith(".py"):
            continue
        txt = open(os.path.join(dirpath, f), encoding="utf-8").read()
        for line in txt.splitlines():
            s = line.strip()
            if not s.startswith(("import ", "from ")):
                continue
            parts = s.split()
            root_mod = parts[1].split(".")[0] if len(parts) > 1 else ""
            if root_mod in ("game", "astrbot"):
                banned_imports.append(f"{os.path.relpath(os.path.join(dirpath, f), FW_ROOT)}: {s}")
check("不 import 游戏包 / 宿主", not banned_imports, banned_imports)

shutil.rmtree(TMP, ignore_errors=True)

print(f"\n=== 结果 PASS={PASS} FAIL={FAIL} ===")
if FAILURES:
    print("失败项：" + ", ".join(FAILURES))
sys.exit(1 if FAIL else 0)
