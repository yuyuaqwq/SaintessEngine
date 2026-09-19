# -*- coding: utf-8 -*-
"""测试断言助手 —— 全仓唯一实现（审计 P0-1 单源化）。

背景：三仓测试原本各自手抄一份 `def check(name, cond, detail="")`（共 356 份），
彼此的差别只有「计数器叫什么名」和「print 装饰」两处。本模块是**唯一**实现，
各测试文件只保留一行绑定，并显式写出自己的计数器名：

    from _check import bind_check
    check = bind_check(globals(), "PASS", "FAIL", "FAILURES")

参数
----
scope    : 绑定到哪个命名空间 —— 测试文件一律传 `globals()`（等价于原先的 `global ...`）
ok / bad : 通过 / 失败计数器名（各文件结果汇总行沿用原名 ⇒ 汇总代码零改动）
failures : 失败明细列表名（None = 该文件不收集明细）
limit    : 明细截断长度（None = 不截断）

唯一口径
--------
· 通过 → `  ✅ <name>`；失败 → `  ❌ <name> <detail>`；返回值 = `bool(cond)`（可用可不用）。
· 失败明细条目 = `"<name>: <detail>"`。
· 明细一律做 UTF-8 安全化（`errors="replace"`）—— 收口原先散落在各文件里的
  `str(detail).encode("utf-8","replace")`，防代理字符把控制台打印打崩。
· `quiet=True` 只抑制**成功**行（失败必打）。

★ 本文件在「包 / 引擎 / 宿主」三仓 `tests/` 下内容一致：测试基础设施不跨仓 import。
"""
__all__ = ["bind_check"]


def _readable(v) -> str:
    """转成一定能 print 的文本（代理字符 / 非法编码一律 replace）。"""
    try:
        return str(v).encode("utf-8", "replace").decode("utf-8", "replace")
    except Exception:                                              # noqa: BLE001
        return "<unprintable detail>"


def bind_check(scope, ok, bad, failures=None, *, limit=None):
    """把断言助手绑到 `scope` 上的 `ok` / `bad` / `failures` 三个名字。"""
    def check(name, cond, detail="", quiet=False):
        safe_name = _readable(name)
        if cond:
            scope[ok] = scope.get(ok, 0) + 1
            if not quiet:
                print("  ✅ " + safe_name)
        else:
            scope[bad] = scope.get(bad, 0) + 1
            text = _readable(detail)
            if limit is not None:
                text = text[:limit]
            if failures:
                scope.setdefault(failures, []).append("%s: %s" % (safe_name, text))
            print("  ❌ " + safe_name + " " + text)
        return bool(cond)

    return check
