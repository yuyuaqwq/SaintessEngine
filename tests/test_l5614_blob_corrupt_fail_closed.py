#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""常驻门禁：`load_blob` 坏行 fail-closed（审计 L5614 **同族残留**）。

跑法：python tests/test_l5614_blob_corrupt_fail_closed.py

背景
----
审计 L5614 已经把 `load_player` 的「坏档回落成 `None`」修成 `CorruptSaveError`
（引擎 64a2304）。但**同文件、同形态**的另一半当时没被收：`SQLiteStore.load_blob`
在 :128 仍是 `except Exception: return None`。

为什么这半边同样是缺陷（不是「无害的宽松」）：

    `None` 在 blob 通路上是**合法业务值** —— 「这个 key 本来就没有」就走这一句。
    `runtime.py::blob` 拿 `None` 再去 `_blobs.get(key)` 回落。于是两种不同的事
    （没这个 key / 在、但 JSON 坏了）被压成同一个返回值 ⇒ 调用方无从分辨 ⇒
    坏值被当「没有」→ 下一次 `save_blob`（upsert）**覆盖掉残值** ⇒ 静默丢数据。

它与 `load_player` 的差别只在**残的是哪张表**（`blobs` vs `players`），而这恰恰
是**必须单起一条异常**的理由：`CorruptSaveError` 的文案与属性都写着「玩家档 /
别让建档路径覆盖它」，套到 blob 上会给出错误的处置指引。

判定
----
1. 坏行**炸**（`CorruptBlobError`），不是回落成 `None`  ← 缺陷本身
2. 坏行**保留**在库里（fail-closed 契约：原行不动）  ← 炸了但把数据弄丢了也是缺陷
3. 缺 key 仍返回 `None`（合法业务值，语义不得被这次收紧改变）
4. 合法值原样返回（收紧不得误伤正常路径）
5. **两向反证**：把 except 改回 `except Exception: return None` 判据必须转红
   —— 证明它真在钉这件事，不是恒真断言
6. **两向反证**：`CorruptBlobError` 不得被 `except RuntimeError` 之外的窄类型逃逸
   —— 且它**不得**是 `CorruptSaveError` 的子类（避免下游拿玩家档的处置指引去查 blob）
"""
from __future__ import annotations

import ast
import importlib.util
import io
import os
import sqlite3
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "tests"))

from _check import bind_check                                    # noqa: E402

FAILS: list = []
PASS = 0
check = bind_check(globals(), "PASS", "FAIL", "FAILS")

_SRC = os.path.join(_ROOT, "examples", "host-skeleton", "store_sqlite.py")
_BAD = "{ this is not json"


def _load_module():
    """按路径载入骨架的 store 模块（它不在包里、也不该被装进包）。"""
    spec = importlib.util.spec_from_file_location("_gw_store_sqlite", _SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fresh(mod):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    return mod.SQLiteStore(path), path


def test_corrupt_blob_raises():
    mod = _load_module()
    store, path = _fresh(mod)
    try:
        store.save_blob("party:7", {"leader": "u1", "members": ["u1", "u2"]})
        # 直接把那一行写成坏 JSON（模拟落库时截断 / 半写 / 外部改坏）。
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE blobs SET data=? WHERE key=?", (_BAD, "party:7"))
            conn.commit()
        raised = None
        try:
            got = store.load_blob("party:7")
        except mod.CorruptBlobError as exc:
            raised = exc
        except BaseException as exc:                             # noqa: BLE001
            check("坏 blob 抛的是 CorruptBlobError（实得 %s）" % type(exc).__name__, False)
            return
        check("坏 blob 不再回落成 None（fail-closed）", raised is not None)
        if raised is not None:
            check("异常带 key 属性可定位", getattr(raised, "key", None) == "party:7",
                  "key=%r" % getattr(raised, "key", None))
            check("异常带 raw 原行可手工修复", getattr(raised, "raw", None) == _BAD,
                  "raw=%r" % getattr(raised, "raw", None))
    finally:
        store._conn.close()
        try:
            os.unlink(path)
        except OSError:
            pass


def test_bad_row_stays_in_db():
    """fail-closed 的另一半：炸归炸，**原行不能被改掉**（炸了但数据没了同样是缺陷）。"""
    mod = _load_module()
    store, path = _fresh(mod)
    try:
        with sqlite3.connect(path) as conn:
            conn.execute("INSERT OR REPLACE INTO blobs(key, data, updated) VALUES(?,?,?)",
                         ("party:7", _BAD, 1.0))
            conn.commit()
        try:
            store.load_blob("party:7")
        except mod.CorruptBlobError:
            pass
        except BaseException:                                     # noqa: BLE001
            pass
        with sqlite3.connect(path) as conn:
            row = conn.execute("SELECT data FROM blobs WHERE key=?", ("party:7",)).fetchone()
        check("炸过之后原行仍在库里（可手工修复）", row is not None and row[0] == _BAD,
              "row=%r" % (row,))
    finally:
        store._conn.close()
        try:
            os.unlink(path)
        except OSError:
            pass


def test_missing_key_still_none():
    """收紧不得改掉「没这个 key」的合法语义。"""
    mod = _load_module()
    store, path = _fresh(mod)
    try:
        check("缺 key 仍返回 None（合法业务值未被改动）", store.load_blob("party:404") is None)
        store.save_blob("party:7", {"leader": "u1"})
        check("合法值原样返回（收紧未误伤正常路径）", store.load_blob("party:7") == {"leader": "u1"})
        store.save_blob("tlog:1", [1, 2, 3])
        check("非 dict 值也原样返回（blob 允许任意 JSON）", store.load_blob("tlog:1") == [1, 2, 3])
    finally:
        store._conn.close()
        try:
            os.unlink(path)
        except OSError:
            pass


def test_exception_type_not_conflated():
    """`CorruptBlobError` 不得是 `CorruptSaveError` 的子类。

    子类化会让下游「except CorruptSaveError」把 blob 故障当成玩家档故障去查，
    处置指引就错了（那是两条独立的表、两条独立的修法）。
    """
    mod = _load_module()
    check("两条例外互不隶属（不会误导处置指引）",
          not issubclass(mod.CorruptBlobError, mod.CorruptSaveError))


def test_no_broad_except_counterevidence():
    """静态反证：`load_blob` 里不得再有 `except Exception`（含 noqa 也不例外）。

    这条是给「有人日后把宽异常改回来」留的钉子 —— 行为断言靠真跑，
    这条额外把**形状**也钉住，宽异常一旦复活立即转红。
    """
    src = io.open(_SRC, encoding="utf-8").read()
    tree = ast.parse(src)
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "load_blob":
            fn = node
            break
    check("能定位到 load_blob 函数", fn is not None)
    if fn is None:
        return
    broad = []
    for node in ast.walk(fn):
        if isinstance(node, ast.ExceptHandler):
            t = node.type
            names = []
            if t is None:
                names = ["<bare except>"]
            elif isinstance(t, ast.Name):
                names = [t.id]
            elif isinstance(t, ast.Tuple):
                names = [e.id for e in t.elts if isinstance(e, ast.Name)]
            if "Exception" in names or "BaseException" in names or not names:
                broad.append("except %s" % ("/".join(names) or "bare"))
    check("load_blob 无宽异常（实得 %s）" % (broad or "无"), not broad)


def main() -> int:
    print("=== L5614 同族残留：load_blob 坏行 fail-closed ===")
    test_corrupt_blob_raises()
    test_bad_row_stays_in_db()
    test_missing_key_still_none()
    test_exception_type_not_conflated()
    test_no_broad_except_counterevidence()
    print("\n" + "=" * 56)
    if FAILS:
        print("❌ 未过 %d 项：%s" % (len(FAILS), FAILS))
        return 1
    print("✅ load_blob 坏行 fail-closed 门禁全绿（%d 项检查）" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
