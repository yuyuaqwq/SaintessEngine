# -*- coding: utf-8 -*-
"""表结构声明的 JSON 装载口（`saintess_engine.store.spec_json`）契约测试。

锁死的契约（换游戏后照样成立）：

1. **装载**：JSON 文本/bytes/文件 → `TableSpec` 列表，表序 = 声明序、列序 = 声明序
2. **等价**：JSON 载入的声明与手写 `Column` / `TableSpec` 生成同一份建表语句与补列定义
3. **注册**：`declare_file` 逐表 `declare`，返回声明序的仓库列表；重复装载幂等
4. **fail-closed**：文件缺 / JSON 坏 / 顶层·表·列形状不对 / 未知键 / 重复表 ——
   一律当场报错并点名（路径 / 键 / 表 / 表.列），不猜、不静默跳过
5. **二次校验**：形状过关后仍走既有 `_validate_spec`（表名 / 列名 / 类型串 / 默认值）
6. **零游戏知识**：本文件只用通用名字（records / notes / payload）

**零游戏、零宿主**：只用标准库 + 临时目录。

跑法：python tests/test_store_spec_json.py
"""
import json
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, FW_ROOT)

from saintess_engine.store import (Database, declare_file,  # noqa: E402
                                   specs_from_file, specs_from_json)
from saintess_engine.store.spec import _column_decl, _ddl  # noqa: E402

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


TMP = tempfile.mkdtemp(prefix="store_spec_json_")


def write_json(name, doc):
    p = os.path.join(TMP, name)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return p


def raises(text, token=None, what=""):
    """断言装载这段 JSON 报错（可选：错误信息里点名 token）。返回错误信息。"""
    try:
        specs_from_json(text)
    except (ValueError, TypeError) as exc:
        msg = str(exc)
        if token is not None and token not in msg:
            check(f"{what}：报错点名 {token!r}", False, msg)
        else:
            check(what or f"报错：{text[:40]!r}", True)
        return msg
    check(what or f"报错：{text[:40]!r}", False, "没有报错（静默通过了）")
    return ""


def ok(text, what=""):
    try:
        return specs_from_json(text)
    except (ValueError, TypeError) as exc:
        check(what or f"合法：{text[:40]!r}", False, f"应当通过却报错：{exc}")
        return None


GOOD = {
    "tables": [
        {"name": "records", "columns": [
            {"name": "id", "type": "TEXT", "pk": True},
            {"name": "label", "type": "TEXT", "notnull": True},
            {"name": "payload", "type": "TEXT", "default": "{}"},
            {"name": "count", "type": "INTEGER", "default": 0},
        ]},
        {"name": "notes", "columns": [
            {"name": "id", "type": "INTEGER", "pk": True},
            {"name": "body", "type": "TEXT"},
        ], "migrations": ["CREATE INDEX IF NOT EXISTS idx_notes_body ON notes(body)"]},
    ]
}

_GOOD_TEXT = json.dumps(GOOD, ensure_ascii=False)


# ------------------------------------------------------------------ 1. 装载与顺序
print("== 1. 装载：表序 / 列序 / 取值 ==")
specs = specs_from_json(_GOOD_TEXT)
check("表数", specs is not None and len(specs) == 2, specs)
check("表序 = 声明序", [s.name for s in specs] == ["records", "notes"],
      [s.name for s in specs] if specs else None)
check("列序 = 声明序", [c.name for c in specs[0].columns] == ["id", "label", "payload", "count"],
      [c.name for c in specs[0].columns] if specs else None)
check("pk / notnull / default 逐列落位",
      specs[0].columns[0].pk is True and specs[0].columns[0].notnull is False
      and specs[0].columns[1].notnull is True
      and specs[0].columns[2].default == "{}"
      and specs[0].columns[3].default == 0,
      [vars(c) for c in specs[0].columns])
check("复合/单主键 pk_columns()",
      specs[0].pk_columns() == ("id",) and specs[1].pk_columns() == ("id",),
      (specs[0].pk_columns(), specs[1].pk_columns()))
check("bytes 与 str 同结果",
      [s.name for s in specs_from_json(_GOOD_TEXT.encode("utf-8"))] == ["records", "notes"])

# 与手写声明等价（同一份建表语句 / 补列定义）
manual = specs_from_json(_GOOD_TEXT)[0]
check("建表语句与手写 Column/TableSpec 同源",
      _ddl(manual) == _ddl(specs[0]), (_ddl(manual), _ddl(specs[0])))
check("补列定义与手写 Column/TableSpec 同源",
      [_column_decl(c, f"records.{c.name}") for c in manual.columns]
      == [_column_decl(c, f"records.{c.name}") for c in specs[0].columns])

# default 省略 == default: null == 不写 DEFAULT
omitted = specs_from_json('{"tables":[{"name":"t","columns":[{"name":"a","type":"TEXT"}]}]}')
nulled = specs_from_json('{"tables":[{"name":"t","columns":[{"name":"a","type":"TEXT","default":null}]}]}')
check("default 省略 = 不写 DEFAULT", omitted[0].columns[0].default is None
      and "DEFAULT" not in _ddl(omitted[0]))
check("default: null = 不写 DEFAULT（与省略同义）",
      nulled[0].columns[0].default is None and "DEFAULT" not in _ddl(nulled[0]))

# migrations 载入形态：SQL 字符串 → fn(conn)
mig_specs = specs_from_json(_GOOD_TEXT)
migs = mig_specs[1].migrations
check("migrations 载入为 fn(conn) 且可调用", len(migs) == 1 and callable(migs[0]), migs)
ran = []


class _FakeConn:
    def execute(self, sql):
        ran.append(sql)


migs[0](_FakeConn())
check("migrations 元素真执行那条 SQL", ran == [GOOD["tables"][1]["migrations"][0]], ran)


# ------------------------------------------------------------------ 2. 文件口
print("== 2. specs_from_file / 路径报错 ==")
good_path = write_json("good.json", GOOD)
from_file = specs_from_file(good_path)
check("文件口结果与文本口一致", [s.name for s in from_file] == ["records", "notes"])

missing = os.path.join(TMP, "nope", "missing.json")
try:
    specs_from_file(missing)
    check("文件不存在 → 报错", False, "没有报错")
except OSError as exc:
    check("文件不存在 → 报错", True)
    check("错误信息带绝对路径", os.path.abspath(missing) in str(exc), str(exc))

bad_path = os.path.join(TMP, "bad.json")
with open(bad_path, "w", encoding="utf-8", newline="\n") as fh:
    fh.write("{ not json")
try:
    specs_from_file(bad_path)
    check("非法 JSON 文件 → 报错", False, "没有报错")
except ValueError as exc:
    check("非法 JSON 文件 → 报错", True)
    check("错误信息带路径", os.path.abspath(bad_path) in str(exc), str(exc))


# ------------------------------------------------------------------ 3. declare_file
print("== 3. declare_file：注册 / 索引 / 幂等 ==")
db = Database(os.path.join(TMP, "t_declare.db"))
repos = declare_file(db, good_path)
check("返回声明序仓库列表",
      [r.table for r in repos] == ["records", "notes"], [r.table for r in repos])
check("仓库主键取自声明", repos[0].pk == ("id",), repos[0].pk)
with db.readonly() as conn:
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    cols = [r[1] for r in conn.execute("PRAGMA table_info(records)").fetchall()]
    idx = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_notes_body'").fetchone()
check("两张表都建了", {"records", "notes"} <= names, sorted(names))
check("列序落盘 = 声明序", cols == ["id", "label", "payload", "count"], cols)
check("migrations 里的 SQL 真建了索引", idx is not None)
repos2 = declare_file(db, good_path)
check("重复装载幂等（不报错、同表数）", [r.table for r in repos2] == ["records", "notes"],
      [r.table for r in repos2])

# json_fields 透传
db2 = Database(os.path.join(TMP, "t_fields.db"))
r2 = declare_file(db2, good_path, json_fields=("payload",))
check("json_fields 透传到仓库", r2[0].json_fields == ("payload",), r2[0].json_fields)

# 坏文件不落半点表（fail-closed 在声明之后才动库）
db3 = Database(os.path.join(TMP, "t_bad.db"))
try:
    declare_file(db3, bad_path)
    check("坏 JSON：declare_file 报错", False, "没有报错")
except ValueError:
    check("坏 JSON：declare_file 报错", True)
with db3.readonly() as conn:
    n = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
check("坏 JSON：库里没留下一张表", n == 0, n)


# ------------------------------------------------------------------ 4. fail-closed
print("== 4. fail-closed：形状 / 未知键 / 点名 ==")
raises("[]", "顶层", "顶层不是对象 → 报错点名")
raises("{}", "tables", "缺 tables 键 → 报错点名")
raises('{"tables":{}}', "tables", "tables 非数组 → 报错点名")
raises('{"tables":[]}', "空数组", "tables 空数组 → 报错点名")
raises('{"tables":[{"name":"t","columns":[{"name":"a","type":"TEXT"}]}],"extra":1}',
       "extra", "顶层未知键 → 报错点名那个键")
raises('{"tables":[{"name":"t","columns":[{"name":"a","type":"TEXT"}],"extra":1}]}',
       "extra", "表级未知键 → 报错点名那个键")
raises('{"tables":[{"name":"t","columns":[{"name":"a","type":"TEXT","extra":1}]}]}',
       "extra", "列级未知键 → 报错点名那个键")
raises('{"tables":[{"columns":[{"name":"a","type":"TEXT"}]}]}', "name", "表缺 name → 报错点名")
raises('{"tables":[{"name":"t","columns":{"a":"TEXT"}}]}', "t", "columns 非数组 → 报错点名表")
raises('{"tables":[{"name":"t","columns":[{"name":"a","type":"TEXT"}]},'
       '{"name":"t","columns":[{"name":"b","type":"TEXT"}]}]}', "t", "表名重复 → 报错点名表")
raises('{"tables":[{"name":"t","columns":[{"type":"TEXT"}]}]}', "t", "列缺 name → 报错点名表")
raises('{"tables":[{"name":"t","columns":[{"name":"a"}]}]}', "t.a", "列缺 type → 报错点名表.列")
raises('{"tables":[{"name":"t","columns":[{"name":"a","type":"TEXT","pk":1}]}]}',
       "t.a", "pk 非 bool → 报错点名表.列")
raises('{"tables":[{"name":"t","columns":[{"name":"a","type":"TEXT","notnull":"yes"}]}]}',
       "t.a", "notnull 非 bool → 报错点名表.列")
raises('{"tables":[{"name":"t","columns":[{"name":"a","type":"TEXT","default":[1]}]}]}',
       "t.a", "default 是数组 → 报错点名表.列")
raises('{"tables":[{"name":"t","columns":[{"name":"a","type":"TEXT","default":{"k":1}}]}]}',
       "t.a", "default 是对象 → 报错点名表.列")
raises('{"tables":[{"name":"t","columns":[{"name":"a","type":"TEXT"}],"migrations":"x"}]}',
       "t", "migrations 非数组 → 报错点名表")
raises('{"tables":[{"name":"t","columns":[{"name":"a","type":"TEXT"}],'
       '"migrations":[123]}]}', "t", "migrations 元素非字符串 → 报错点名表")

# 形状过关但仍走既有 _validate_spec：类型串 / 标识符
raises('{"tables":[{"name":"t","columns":[{"name":"a","type":"TEXT; DROP TABLE t"}]}]}',
       "t.a", "类型串不合规 → _validate_spec 报错")
raises('{"tables":[{"name":"1bad","columns":[{"name":"a","type":"TEXT"}]}]}',
       "表名", "表名不合规 → _validate_spec 报错")
raises('{"tables":[{"name":"t","columns":[]}]}', "t", "空列声明 → _validate_spec 报错")
raises('{"tables":[{"name":"t","columns":[{"name":"a","type":"TEXT"},'
       '{"name":"a","type":"INTEGER"}]}]}', "重复", "列名重复 → _validate_spec 报错")
try:
    specs_from_json({"tables": []})          # 不是 str/bytes
    check("非 str/bytes 入参 → TypeError", False, "没有报错")
except TypeError:
    check("非 str/bytes 入参 → TypeError", True)


print(f"\n=== 结果 PASS={PASS} FAIL={FAIL} ===")
if FAILURES:
    print("失败项：" + ", ".join(FAILURES))
sys.exit(1 if FAIL else 0)
