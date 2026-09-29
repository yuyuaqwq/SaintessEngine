#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""常驻门禁：`Repository._decode` 的 JSON 解码不许静默换型（晚到批 · 第三十轮）。

跑法：python tests/test_store_json_decode_no_type_drift.py

背景
----
saintess_engine/store/repository.py::_decode 原先是：

    for f in self.json_fields:
        if f in d and isinstance(d[f], str):
            try:
                d[f] = json.loads(d[f])
            except Exception:
                pass

两处缺陷：
① **静默换型** —— `json.loads` 连标量一起解。`event_state.value` 这类列存的是
   **任意标量文本**（实测：`""` · `"2026-09-29|炼金|3|100|0|0"` · `"1"`），
   于是写进去的 `"1"` 读回来是 `int 1`、`"true"` 是 `True`、`"null"` 是 `None`
   ⇒ 业务按 str 用的值凭空变型，**零痕迹**（写回时又编回同名字符串，roundtrip 看不出）。
② **宽异常** —— `except Exception: pass` 吞掉一切（含 `TypeError` / 递归爆栈这类
   真故障）。

本版处置 = 按形状分流：**只解 dict / list**；标量与非法 JSON 文本一律保留原值。
`json_fields` 的语义是「这列存一份 JSON 数据」，落盘面真在用的三个点
（快照 blob · props_use.used · battle_state.state）**全是容器**，故对它们逐字节不变。

判据
----
① 容器形状照旧解出（dict / list）
② 标量 JSON 文本**类型不漂**（`"1"`→str `"1"`，不是 int 1）
③ 非 JSON 文本原样返回（不是 None、不是被吞掉）
④ 写回不引入格式漂移（`_encode` 对同一值产出逐字节相同的列内容）
⑤ 静态自证：无宽异常 / 无裸 pass
⑥ ★ 两向反证：把源码改回旧写法 ⇒ 本门禁转红（rc=1）
"""
import ast
import io
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from saintess_engine.store.repository import Repository

_REPO = os.path.join(_ROOT, "saintess_engine", "store", "repository.py")

PASS, FAILS = 0, []


def check(cond, label):
    global PASS
    if cond:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAILS.append(label)
        print("  FAIL %s" % label)


class _Row(dict):
    pass


def _repo(*json_fields):
    r = Repository.__new__(Repository)
    r.table = "t"
    r.pk = ("k",)
    r.json_fields = json_fields
    return r


def _dec(r, **row):
    return r._decode(_Row(k="x", **row))["value"]


def test_containers_still_decode():
    """① dict / list 照旧解出（这是三个真使用点依赖的形状）。"""
    r = _repo("value")
    got = _dec(r, value=json.dumps({"a": 1, "b": [2, 3]}))
    check(got == {"a": 1, "b": [2, 3]}, "dict 容器照旧解出（实得 %r）" % (got,))
    got = _dec(r, value=json.dumps([1, 2, 3]))
    check(got == [1, 2, 3], "list 容器照旧解出（实得 %r）" % (got,))
    got = _dec(r, value=json.dumps({}, ensure_ascii=False))
    check(got == {}, "空 dict 容器照旧解出（实得 %r）" % (got,))
    got = _dec(r, value=json.dumps([], ensure_ascii=False))
    check(got == [], "空 list 容器照旧解出（实得 %r）" % (got,))


def test_scalar_no_type_drift():
    """② ★ 标量 JSON 文本类型不漂 —— 这是本门禁的主判据。"""
    r = _repo("value")
    for raw in ("1", "0", "-5", "1758512345", "1.5", "true", "false", "null",
                '"abc"'):
        got = _dec(r, value=raw)
        check(got == raw and isinstance(got, str),
              "标量 %r 原样返回（实得 %r/%s）" % (raw, got, type(got).__name__))


def test_non_json_text_survives():
    """③ 非 JSON 文本（业务合法值）原样返回，不是 None。"""
    r = _repo("value")
    for raw in ("", "2026-09-29|炼金|3|100|0|0", "chat", "wish_ok", "  ",
                "{不是json", "很长的自由文本"):
        got = _dec(r, value=raw)
        check(got == raw and isinstance(got, str),
              "非 JSON 文本 %r 原样返回（实得 %r）" % (raw, got))


def test_roundtrip_no_format_drift():
    """④ 写回不引入格式漂移：同一值 _encode 后列内容逐字节相同。"""
    r = _repo("value")
    for raw in ("1", "true", "null", "", "chat", '{"a": 1}', "[1, 2]",
                "2026-09-29|炼金|3|100|0|0"):
        enc = r._encode({"value": _dec(r, value=raw)})["value"]
        check(enc == raw, "roundtrip %r 逐字节一致（实得 %r）" % (raw, enc))


def test_missing_column_untouched():
    """⑤ 该列不存在时不动 dict（不多塞键、不改其它列）。"""
    r = _repo("value", "other")
    d = r._decode(_Row(k="x", other=7))
    check("value" not in d and d["other"] == 7,
          "缺失列不补键（实得 %r）" % (d,))
    check(r._decode(None) is None, "row=None 仍返回 None")


def test_static_no_broad_except():
    """⑥ 静态自证：_decode 内无宽异常、无裸 pass。"""
    tree = ast.parse(io.open(_REPO, encoding="utf-8").read())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_decode")
    broad, bare = [], []
    for h in [n for n in ast.walk(fn) if isinstance(n, ast.ExceptHandler)]:
        t = h.type
        names = []
        if t is None:
            names = ["<裸except>"]
        elif isinstance(t, ast.Name):
            names = [t.id]
        elif isinstance(t, ast.Tuple):
            names = [e.id for e in t.elts if isinstance(e, ast.Name)]
        if any(n in ("Exception", "BaseException", "<裸except>") for n in names):
            broad.append((h.lineno, names))
        for st in h.body:
            if isinstance(st, ast.Pass):
                bare.append(h.lineno)
    check(not broad, "AST：_decode 内无宽异常（实得 %r）" % (broad,))
    check(not bare, "AST：_decode 内无裸 pass（实得 %r）" % (bare,))


def main() -> int:
    for fn in (test_containers_still_decode, test_scalar_no_type_drift,
               test_non_json_text_survives, test_roundtrip_no_format_drift,
               test_missing_column_untouched, test_static_no_broad_except):
        fn()
    print("PASS=%d FAIL=%d" % (PASS, len(FAILS)))
    for f in FAILS:
        print("  FAIL:", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
