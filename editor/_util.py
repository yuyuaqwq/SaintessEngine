# -*- coding: utf-8 -*-
"""编辑器内部的纯 stdlib 小工具 —— 只收「多模块各抄一份」的东西。

为什么有它
----------
`relations.py` / `render.py` / `server.py` 原先各自持一份**同体**的「文件签名
（`mtime_ns` + `size`）」小函数：`_sig` ×2 **逐字相同**，`server._file_sig` 同体
（只多一行 docstring）。它是**缓存失效判据的唯一口径** —— 三处必须完全一致，
否则同一个文件在不同模块里会被判成「变了 / 没变」两种结果，缓存一半生效一半失效。

本模块**只依赖标准库**（`os`），且**不 import 本包任何其它模块** —— 所以
`render.py` 那条「不 import `editor.packages` / `editor.relations`」的纪律不受影响
（那两个会级联 `install_engine()`）。同理，**子进程自足**的实现（`render_worker.py`
的 `split_path`：那文件不 import 本仓任何模块）不在这里收。
"""
from __future__ import annotations

import os


def file_sig(path: str):
    """文件签名（`mtime_ns` + `size`）；取不到（不存在 / 无权限）→ `None`。

    `None` = 「没法判」——调用方一律当作**缓存失效**处理（宁可重算，不用旧结果）。
    """
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None
