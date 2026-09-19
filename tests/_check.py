# -*- coding: utf-8 -*-
"""测试断言助手 —— 全仓唯一实现（审计 P0-1 单源化）。

背景：三仓测试原本各自手抄一份 `def check(...)`（共 356 份），彼此的差异只有四处 ——
「计数器叫什么名 / 要不要收明细 / 要不要红 key / 失败是计数还是抛异常」。本模块是
**唯一**实现，各测试文件只保留一行绑定，并显式写出自己的名字：

    from _check import bind_check
    check = bind_check(globals(), "PASS", "FAIL", "FAILURES")

参数
----
scope    : 绑定到哪个命名空间 —— 测试文件一律传 `globals()`（等价于原先的 `global ...`）
ok / bad : 通过 / 失败**计数器**名（None = 不计数；各文件沿用原变量名 ⇒ 汇总代码零改动）
failures : 失败明细**列表**名（None = 不收集明细；条目格式 `"<名>: <明细>"`）
limit    : 明细截断长度（None = 不截断）
markers  : 「红 key」收集**集合**名（None = 不收集）；失败时把本次 `red_keys` 并进去
marker_label : 红 key 的打印前缀（默认 `"红 key"`；tlogs 门禁用 `"红 kind"`）
total    : 总检查数计数器名（None = 不计；给「只关心跑了多少条断言」的门禁用）
strict   : True = 失败时抛 `AssertionError`（保留 assert 型测试的语义：失败即中断）

唯一口径
--------
· 通过 → `  ✅ <名>`；失败 → `  ❌ <名>` +（有则）`  红 key: [...]` +（有则）明细。
· 返回值 = `bool(cond)`（可 `ok &= check(...)`，也可忽略）。
· 文本一律 UTF-8 安全化（`errors="replace"`）—— 收口原先散落在各文件里的
  `str(detail).encode("utf-8","replace")`，防代理字符把控制台打印打崩。
· `quiet=True` 只抑制**成功**行（失败必打）。
· `strict=True`：**先打印失败行再抛**，异常信息与打印内容同一份（不维护两套措辞）。

★ 本文件在「包 / 引擎 / 宿主」三仓 `tests/` 下内容**逐字节一致**：测试基础设施不跨仓 import。
"""
__all__ = ["bind_check"]


def _readable(v) -> str:
    """转成一定能 print 的文本（代理字符 / 非法编码一律 replace）。"""
    try:
        return str(v).encode("utf-8", "replace").decode("utf-8", "replace")
    except Exception:                                              # noqa: BLE001
        return "<unprintable detail>"


def bind_check(scope, ok=None, bad=None, failures=None, *, limit=None,
               markers=None, marker_label="红 key", total=None, strict=False):
    """把断言助手绑到 `scope` 上的 `ok` / `bad` / `failures` / `markers` / `total` 名字。

    各参数均为**能力开关**（None = 该文件不需要这项），不是兼容分支：
    每个测试文件按自己的汇总行需要传参，实现只有这一份。
    """
    def check(name, cond, detail="", red_keys=(), quiet=False):
        safe_name = _readable(name)
        if total is not None:
            scope[total] = scope.get(total, 0) + 1
        if cond:
            if ok is not None:
                scope[ok] = scope.get(ok, 0) + 1
            if not quiet:
                print("  ✅ " + safe_name)
            return True
        text = _readable(detail)
        if limit is not None:
            text = text[:limit]
        keys = sorted({_readable(k) for k in red_keys}) if red_keys else []
        if bad is not None:
            scope[bad] = scope.get(bad, 0) + 1
        if markers is not None and keys:
            scope.setdefault(markers, set()).update(keys)
        if failures is not None:
            scope.setdefault(failures, []).append("%s: %s" % (safe_name, text))
        print("  ❌ " + safe_name
              + (("  %s: %s" % (marker_label, keys)) if keys else "")
              + (" " + text if text else ""))
        if strict:
            raise AssertionError("%s: %s" % (safe_name, text))
        return False

    return check
